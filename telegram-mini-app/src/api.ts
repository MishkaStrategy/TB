import { mockSettings } from "./mock";
import { getInitData, getTelegramUser } from "./telegram";
import type { AppSettings, SaveSettingsRequest, SettingsEnvelope } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

function mockEnvelope(settings: AppSettings = mockSettings): SettingsEnvelope {
  return {
    settings: structuredClone(settings),
    user: getTelegramUser(),
    source: "mock",
    updatedAt: new Date().toISOString(),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": getInitData(),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `API request failed with status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export async function loadSettings(): Promise<SettingsEnvelope> {
  if (!API_BASE_URL) return mockEnvelope();
  return request<SettingsEnvelope>("/api/mini-app/settings");
}

export async function saveSettings(settings: AppSettings): Promise<SettingsEnvelope> {
  if (!API_BASE_URL) {
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    return mockEnvelope(settings);
  }

  const payload: SaveSettingsRequest = { settings };
  return request<SettingsEnvelope>("/api/mini-app/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}
