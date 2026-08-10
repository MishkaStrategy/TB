import { setUiLanguage } from "./i18n";
import { mockSettings } from "./mock";
import { getInitData, getTelegramUser } from "./telegram";
import type { AppSettings, SaveSettingsRequest, SettingsEnvelope } from "./types";

const CONFIGURED_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const MOCK_MODE = String(import.meta.env.VITE_MOCK_MODE ?? "false").toLowerCase() === "true";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${CONFIGURED_API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": getInitData(),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as {
      error?: { message?: string; field?: string };
    } | null;
    const field = payload?.error?.field ? ` (${payload.error.field})` : "";
    throw new Error(
      `${payload?.error?.message ?? `API request failed with status ${response.status}`}${field}`,
    );
  }

  return response.json() as Promise<T>;
}

export async function loadSettings(): Promise<SettingsEnvelope> {
  if (MOCK_MODE) return mockEnvelope();
  return announceLanguage(await request<SettingsEnvelope>("/api/mini-app/settings"));
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
