import { setUiLanguage } from "./i18n";
import { mockSettings } from "./mock";
import { getInitData, getTelegramUser } from "./telegram";
import type {
  AppSettings,
  MarketOverviewEnvelope,
  SaveSettingsRequest,
  SettingsEnvelope,
} from "./types";

const CONFIGURED_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const MOCK_MODE = String(import.meta.env.VITE_MOCK_MODE ?? "false").toLowerCase() === "true";
const REQUEST_TIMEOUT_MS = 10_000;

function announceLanguage(envelope: SettingsEnvelope): SettingsEnvelope {
  setUiLanguage(envelope.settings.general.language);
  return envelope;
}

function mockEnvelope(settings: AppSettings = mockSettings): SettingsEnvelope {
  return announceLanguage({
    settings: structuredClone(settings),
    user: getTelegramUser(),
    limits: { maxFvgSymbols: 10 },
    source: "mock",
    updatedAt: new Date().toISOString(),
  });
}

function mockMarketOverview(): MarketOverviewEnvelope {
  const demoChanges = [1.42, -2.71, 0.38, -0.64];
  return {
    instruments: mockSettings.fvg.symbols.map((instrument, index) => ({
      key: instrument.key,
      exchange: instrument.exchange,
      symbol: instrument.symbol,
      price: null,
      priceChange24hPct: demoChanges[index % demoChanges.length] ?? null,
      source: "ticker",
    })),
    updatedAt: new Date().toISOString(),
  };
}

function requestFailureMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Сервер Mini App не отвечает. Проверьте соединение и повторите попытку.";
  }
  if (error instanceof TypeError) {
    return "Не удалось подключиться к серверу Mini App. Проверьте соединение и повторите попытку.";
  }
  return error instanceof Error ? error.message : "Не удалось выполнить запрос к Mini App API.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${CONFIGURED_API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": getInitData(),
        ...init?.headers,
      },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { error?: { message?: string; field?: string } } | null;
      const field = payload?.error?.field ? ` (${payload.error.field})` : "";
      throw new Error(`${payload?.error?.message ?? `API request failed with status ${response.status}`}${field}`);
    }
    return await response.json() as T;
  } catch (error: unknown) {
    throw new Error(requestFailureMessage(error));
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function loadSettings(): Promise<SettingsEnvelope> {
  if (MOCK_MODE) return mockEnvelope();
  return announceLanguage(await request<SettingsEnvelope>("/api/mini-app/settings"));
}

export async function loadMarketOverview(): Promise<MarketOverviewEnvelope> {
  if (MOCK_MODE) return mockMarketOverview();
  return request<MarketOverviewEnvelope>("/api/mini-app/market-overview");
}

export async function saveSettings(settings: AppSettings): Promise<SettingsEnvelope> {
  if (MOCK_MODE) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return mockEnvelope(settings);
  }
  const payload: SaveSettingsRequest = { settings };
  return announceLanguage(await request<SettingsEnvelope>("/api/mini-app/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  }));
}
