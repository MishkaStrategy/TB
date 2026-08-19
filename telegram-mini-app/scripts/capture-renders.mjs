import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn } from "node:child_process";

const baseUrl = process.env.TB_SMOKE_URL || "http://127.0.0.1:4173";
const chromeBin = process.env.CHROME_BIN;
const port = Number(process.env.TB_CDP_PORT || "9333");
const outputDir = resolve("render-capture");
if (!chromeBin) throw new Error("CHROME_BIN is required");
mkdirSync(outputDir, { recursive: true });

const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));

async function waitHttp(url, timeoutMs = 15000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {}
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result ?? {});
    });
  }
  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolvePromise, reject) => {
      socket.addEventListener("open", resolvePromise, { once: true });
      socket.addEventListener("error", reject, { once: true });
    });
    return new CdpClient(socket);
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolvePromise, reject) => {
      this.pending.set(id, { resolve: resolvePromise, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { this.socket.close(); }
}

async function main() {
  const userDataDir = mkdtempSync(join(tmpdir(), "tb-render-capture-"));
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

  let client;
  try {
    await waitHttp(`http://127.0.0.1:${port}/json/version`);
    const targetResponse = await fetch(
      `http://127.0.0.1:${port}/json/new?${encodeURIComponent(baseUrl)}`,
      { method: "PUT" },
    );
    if (!targetResponse.ok) throw new Error(`Could not create Chrome target: ${targetResponse.status}`);
    const target = await targetResponse.json();
    client = await CdpClient.connect(target.webSocketDebuggerUrl);

    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 2,
      mobile: true,
      screenWidth: 390,
      screenHeight: 844,
    });
    await client.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `
        window.Telegram = { WebApp: {
          initData: "render-capture",
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
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || "Runtime.evaluate failed");
      return response.result?.value;
    }

    async function waitFor(expression, label, timeoutMs = 10000) {
      const started = Date.now();
      while (Date.now() - started < timeoutMs) {
        if (await evaluate(expression)) return;
        await sleep(100);
      }
      throw new Error(`Timed out waiting for ${label}`);
    }

    async function clickNav(label, heading) {
      const clicked = await evaluate(`(() => {
        const button = [...document.querySelectorAll('.bottom-nav button')]
          .find((item) => item.textContent?.trim() === ${JSON.stringify(label)});
        if (!button) return false;
        button.click();
        return true;
      })()`);
      if (!clicked) throw new Error(`Navigation button not found: ${label}`);
      await waitFor(`document.querySelector('.page-heading h1')?.textContent === ${JSON.stringify(heading)}`, `${label} heading`);
      await evaluate(`window.scrollTo(0, 0)`);
      await sleep(180);
    }

    async function capture(slug) {
      const shot = await client.send("Page.captureScreenshot", {
        format: "jpeg",
        quality: 90,
        fromSurface: true,
        captureBeyondViewport: false,
      });
      writeFileSync(join(outputDir, `${slug}.jpg`), Buffer.from(shot.data, "base64"));
      writeFileSync(join(outputDir, `${slug}.jpg.b64`), `${shot.data}\n`);
      console.log(`[render-capture] ${slug}.jpg`);
    }

    await client.send("Page.navigate", { url: baseUrl });
    await waitFor(`Boolean(document.querySelector('.bottom-nav') && !document.querySelector('.skeleton-shell'))`, "Mini App hydration");
    await waitFor(`document.querySelectorAll('.final-market-row').length === 5`, "overview instruments");
    await sleep(250);
    await capture("01-home");

    await clickNav("FVG", "Fair Value Gap");
    await capture("02-fvg");
    await clickNav("Funding", "Funding");
    await capture("03-funding");
    await clickNav("Alerts", "Alerts");
    await capture("04-alerts");
    await clickNav("Settings", "Settings");
    await capture("05-settings");

    console.log("[render-capture] PASS: captured exact v1.3.9 UI at 390x844 CSS px / DPR 2");
  } finally {
    client?.close();
    if (chrome.exitCode === null) chrome.kill("SIGTERM");
    await Promise.race([new Promise((resolvePromise) => chrome.once("exit", resolvePromise)), sleep(2000)]);
    if (chrome.exitCode === null) chrome.kill("SIGKILL");
  }
}

main().catch((error) => {
  console.error(`[render-capture] FAIL: ${error.stack || error}`);
  process.exitCode = 1;
});
