import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";

const baseUrl = process.env.TB_SMOKE_URL || "http://127.0.0.1:4173";
const chromeBin = process.env.CHROME_BIN;
const port = Number(process.env.TB_CDP_PORT || "9222");

if (!chromeBin) throw new Error("CHROME_BIN is required");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitHttp(url, timeoutMs = 15_000) {
  const started = Date.now();
  let lastError;
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${url}: ${String(lastError ?? "no response")}`);
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(`${message.error.message} (${message.error.code})`));
        else pending.resolve(message.result ?? {});
        return;
      }
      if (message.method) {
        for (const listener of this.listeners.get(message.method) ?? []) listener(message.params ?? {});
      }
    });
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", reject, { once: true });
    });
    return new CdpClient(socket);
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) ?? [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const userDataDir = mkdtempSync(join(tmpdir(), "tb-mini-app-chrome-"));
  const chrome = spawn(chromeBin, [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    `--remote-debugging-port=${port}`,
    "--remote-debugging-address=127.0.0.1",
    `--user-data-dir=${userDataDir}`,
    "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });

  let chromeErrors = "";
  chrome.stderr.on("data", (chunk) => { chromeErrors += String(chunk); });

  let client;
  try {
    await waitHttp(`http://127.0.0.1:${port}/json/version`);
    const targetResponse = await fetch(
      `http://127.0.0.1:${port}/json/new?${encodeURIComponent(baseUrl)}`,
      { method: "PUT" },
    );
    assert(targetResponse.ok, `Could not create Chrome target: ${targetResponse.status}`);
    const target = await targetResponse.json();
    client = await CdpClient.connect(target.webSocketDebuggerUrl);

    const pageErrors = [];
    client.on("Runtime.exceptionThrown", ({ exceptionDetails }) => {
      pageErrors.push(exceptionDetails?.exception?.description || exceptionDetails?.text || "Runtime exception");
    });
    client.on("Log.entryAdded", ({ entry }) => {
      if (entry?.level === "error") pageErrors.push(entry.text || "Console error");
    });
    client.on("Runtime.consoleAPICalled", ({ type, args }) => {
      if (type === "error") pageErrors.push(args?.map((item) => item.value ?? item.description).join(" ") || "console.error");
    });

    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Log.enable");
    await client.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: true,
      screenWidth: 390,
      screenHeight: 844,
    });
    await client.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `
        window.Telegram = { WebApp: {
          initData: "visual-audit",
          initDataUnsafe: { user: { id: 812345678, first_name: "Alex", username: "alexkim" } },
          ready() {}, expand() {}, close() {}, setHeaderColor() {}, setBackgroundColor() {},
          enableClosingConfirmation() {}, disableClosingConfirmation() {},
          HapticFeedback: { impactOccurred() {}, notificationOccurred() {} }
        } };
      `,
    });

    async function evaluate(expression) {
      const response = await client.send("Runtime.evaluate", {
        expression,
        returnByValue: true,
        awaitPromise: true,
      });
      if (response.exceptionDetails) {
        throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text || "Runtime.evaluate failed");
      }
      return response.result?.value;
    }

    async function waitFor(expression, label, timeoutMs = 10_000) {
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
        if (await evaluate(expression)) return;
        await sleep(100);
      }
      throw new Error(`Timed out waiting for ${label}`);
    }

    async function clickNav(label) {
      const clicked = await evaluate(`(() => {
        const button = [...document.querySelectorAll('.bottom-nav button')]
          .find((item) => item.textContent?.trim() === ${JSON.stringify(label)});
        if (!button) return false;
        button.click();
        return true;
      })()`);
      assert(clicked, `Navigation button not found: ${label}`);
      await sleep(80);
    }

    async function assertNoOverflow(label) {
      const metrics = await evaluate(`(() => ({
        innerWidth: window.innerWidth,
        html: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        navCount: document.querySelectorAll('.bottom-nav button').length,
        current: document.querySelector('.bottom-nav button[aria-current="page"]')?.textContent?.trim() || ''
      }))()`);
      assert(metrics.navCount === 5, `${label}: expected 5 primary navigation buttons, got ${metrics.navCount}`);
      assert(metrics.html <= metrics.innerWidth + 1, `${label}: html horizontal overflow ${metrics.html} > ${metrics.innerWidth}`);
      assert(metrics.body <= metrics.innerWidth + 1, `${label}: body horizontal overflow ${metrics.body} > ${metrics.innerWidth}`);
      console.log(`[browser-smoke] ${label}: width=${metrics.innerWidth}, scroll=${Math.max(metrics.html, metrics.body)}, active=${metrics.current}`);
    }

    await client.send("Page.navigate", { url: baseUrl });
    await waitFor(
      `Boolean(document.querySelector('.bottom-nav') && !document.querySelector('.skeleton-shell'))`,
      "Mini App hydration",
    );
    await waitFor(`document.querySelectorAll('.final-market-row').length === 5`, "five approved overview instruments");
    const overviewTitle = await evaluate(`document.querySelector('.page-heading h1')?.textContent`);
    assert(overviewTitle === "TB", `Overview heading mismatch: ${overviewTitle}`);
    await assertNoOverflow("Overview 390px");

    const screens = [
      ["FVG", "Fair Value Gap"],
      ["Funding", "Funding"],
      ["Alerts", "Alert operations"],
      ["Settings", "Settings"],
    ];
    for (const [navLabel, heading] of screens) {
      await clickNav(navLabel);
      await waitFor(`document.querySelector('.page-heading h1')?.textContent === ${JSON.stringify(heading)}`, `${navLabel} heading`);
      await assertNoOverflow(`${navLabel} 390px`);
    }

    await clickNav("Home");
    await waitFor(`document.querySelector('.page-heading h1')?.textContent === 'TB'`, "Overview return");
    for (const width of [360, 430, 390]) {
      await client.send("Emulation.setDeviceMetricsOverride", {
        width,
        height: 844,
        deviceScaleFactor: 1,
        mobile: true,
        screenWidth: width,
        screenHeight: 844,
      });
      await sleep(80);
      await assertNoOverflow(`Overview ${width}px responsive`);
    }

    await clickNav("Settings");
    await waitFor(`document.querySelector('.page-heading h1')?.textContent === 'Settings'`, "Settings before dirty/save");
    const changed = await evaluate(`(() => {
      const button = [...document.querySelectorAll('button')].find((item) => item.textContent?.trim() === 'Detailed');
      if (!button) return false;
      button.click();
      return true;
    })()`);
    assert(changed, "Could not change message mode for dirty/save smoke");
    await waitFor(`Boolean(document.querySelector('.save-bar.visible'))`, "dirty save bar");
    const saved = await evaluate(`(() => {
      const button = document.querySelector('.save-bar.visible .primary-button');
      if (!button) return false;
      button.click();
      return true;
    })()`);
    assert(saved, "Could not trigger mock save");
    await waitFor(`!document.querySelector('.save-bar.visible')`, "save completion");
    await assertNoOverflow("Settings after save");

    assert(pageErrors.length === 0, `Browser console/runtime errors:\n${pageErrors.join("\n")}`);
    console.log("[browser-smoke] PASS: 5 tabs, 360/390/430 responsive overflow, Telegram user, dirty/save flow");
  } finally {
    client?.close();
    chrome.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => chrome.once("exit", resolve)),
      sleep(2_000),
    ]);
    if (!chrome.killed) chrome.kill("SIGKILL");
    rmSync(userDataDir, { recursive: true, force: true });
    if (chrome.exitCode && chrome.exitCode !== 0 && !client) {
      console.error(chromeErrors.slice(-4_000));
    }
  }
}

main().catch((error) => {
  console.error(`[browser-smoke] FAIL: ${error.stack || error}`);
  process.exitCode = 1;
});
