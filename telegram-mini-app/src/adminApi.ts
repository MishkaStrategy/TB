import { getInitData } from "./telegram";
import type { AdminConfirmation } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const REQUEST_TIMEOUT_MS = 10_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": getInitData(),
        ...init?.headers,
      },
    });
    const payload = await response.json().catch(() => null) as { error?: { message?: string; field?: string } } | T | null;
    if (!response.ok) {
      const error = (payload as { error?: { message?: string; field?: string } } | null)?.error;
      const field = error?.field ? ` (${error.field})` : "";
      throw new Error(`${error?.message ?? `Request failed with status ${response.status}`}${field}`);
    }
    return payload as T;
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Admin API timeout");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export function createAdminConfirmation(action: string, telegramId?: number): Promise<AdminConfirmation> {
  return request<AdminConfirmation>("/api/mini-app/admin/confirmations", {
    method: "POST",
    body: JSON.stringify({ action, ...(telegramId !== undefined ? { telegramId } : {}) }),
  });
}

export async function setPublicAccess(publicAccessEnabled: boolean, confirmation: AdminConfirmation, confirmationText: string): Promise<void> {
  await request("/api/mini-app/admin/access", {
    method: "PUT",
    body: JSON.stringify({ publicAccessEnabled, confirmationToken: confirmation.token, confirmationText }),
  });
}

export async function addAllowlistUser(telegramId: number, name: string, username: string, confirmation: AdminConfirmation, confirmationText: string): Promise<void> {
  await request("/api/mini-app/admin/allowlist", {
    method: "POST",
    body: JSON.stringify({ telegramId, name: name || undefined, username: username || undefined, confirmationToken: confirmation.token, confirmationText }),
  });
}

export async function removeAllowlistUser(telegramId: number, confirmation: AdminConfirmation, confirmationText: string): Promise<void> {
  await request(`/api/mini-app/admin/allowlist/${telegramId}`, {
    method: "DELETE",
    body: JSON.stringify({ confirmationToken: confirmation.token, confirmationText }),
  });
}

export async function createBackup(confirmation: AdminConfirmation, confirmationText: string): Promise<void> {
  await request("/api/mini-app/admin/backup", {
    method: "POST",
    body: JSON.stringify({ confirmationToken: confirmation.token, confirmationText }),
  });
}

export async function restartBot(confirmation: AdminConfirmation, confirmationText: string): Promise<void> {
  await request("/api/mini-app/admin/restart", {
    method: "POST",
    body: JSON.stringify({ confirmationToken: confirmation.token, confirmationText }),
  });
}
