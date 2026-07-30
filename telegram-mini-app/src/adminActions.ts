import { getInitData, impact, notify } from "./telegram";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

type AdminCapabilities = {
  accessWrite: boolean;
  allowlistWrite: boolean;
  backup: boolean;
  restart: boolean;
};

type AllowedUser = {
  telegramId: number;
  name: string;
  username?: string;
  source: "env" | "runtime";
};

type AdminState = {
  available: boolean;
  publicAccessEnabled: boolean;
  allowedUsers: AllowedUser[];
  capabilities?: AdminCapabilities;
};

type SettingsResponse = {
  settings?: { admin?: AdminState };
};

type Confirmation = {
  token: string;
  action: string;
  confirmationText: string;
  expiresAt: string;
};

type ApiErrorPayload = {
  error?: { code?: string; message?: string; field?: string };
};

class AdminApiError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AdminApiError";
    this.code = code;
  }
}

const COPY = {
  ru: {
    title: "Управление доступом и операциями",
    description: "Все изменения требуют отдельного одноразового подтверждения",
    demo: "Административные операции недоступны в демо-режиме.",
    unsaved: "Сначала сохраните текущие изменения настроек.",
    accessTitle: "Режим доступа",
    accessPublic: "Сейчас публичный",
    accessPrivate: "Сейчас приватный",
    makePublic: "Сделать публичным",
    makePrivate: "Сделать приватным",
    allowlistTitle: "Добавить в allowlist",
    telegramId: "Telegram ID",
    name: "Имя — необязательно",
    username: "Username — необязательно",
    add: "Добавить",
    runtimeUsers: "Runtime allowlist",
    noRuntimeUsers: "Runtime-записей нет.",
    remove: "Удалить",
    protected: "Env/admin запись защищена",
    operationsTitle: "Служебные операции",
    backup: "Создать backup",
    restart: "Перезапустить бота",
    unavailable: "Не подключено к production adapter",
    confirmationTitle: "Подтвердите действие",
    confirmationHint: "Введите точную фразу:",
    confirmationPlaceholder: "Фраза подтверждения",
    cancel: "Отмена",
    confirm: "Подтвердить",
    invalidId: "Введите положительный числовой Telegram ID.",
    success: "Операция выполнена.",
    accessChanged: "Режим доступа изменён.",
    userAdded: "Пользователь добавлен в allowlist.",
    userRemoved: "Пользователь удалён из allowlist.",
    backupAccepted: "Запрос backup принят.",
    restartAccepted: "Запрос перезапуска принят.",
    loading: "Загружаем административные возможности…",
    endpointUnavailable: "Backend Mini App не настроен.",
  },
  en: {
    title: "Access and operations control",
    description: "Every change requires a separate one-time confirmation",
    demo: "Administrative operations are unavailable in demo mode.",
    unsaved: "Save the current settings changes first.",
    accessTitle: "Access mode",
    accessPublic: "Currently public",
    accessPrivate: "Currently private",
    makePublic: "Make public",
    makePrivate: "Make private",
    allowlistTitle: "Add to allowlist",
    telegramId: "Telegram ID",
    name: "Name — optional",
    username: "Username — optional",
    add: "Add",
    runtimeUsers: "Runtime allowlist",
    noRuntimeUsers: "No runtime records.",
    remove: "Remove",
    protected: "Env/admin record is protected",
    operationsTitle: "Service operations",
    backup: "Create backup",
    restart: "Restart bot",
    unavailable: "Not connected to a production adapter",
    confirmationTitle: "Confirm action",
    confirmationHint: "Enter the exact phrase:",
    confirmationPlaceholder: "Confirmation phrase",
    cancel: "Cancel",
    confirm: "Confirm",
    invalidId: "Enter a positive numeric Telegram ID.",
    success: "Operation completed.",
    accessChanged: "Access mode changed.",
    userAdded: "User added to the allowlist.",
    userRemoved: "User removed from the allowlist.",
    backupAccepted: "Backup request accepted.",
    restartAccepted: "Restart request accepted.",
    loading: "Loading administrative capabilities…",
    endpointUnavailable: "Mini App backend is not configured.",
  },
} as const;

type CopyKey = keyof typeof COPY.ru;

function language(): "ru" | "en" {
  return document.documentElement.dataset.language === "en" ? "en" : "ru";
}

function t(key: CopyKey): string {
  return COPY[language()][key];
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!API_BASE_URL) {
    throw new AdminApiError("ADMIN_ENDPOINT_UNAVAILABLE", t("endpointUnavailable"));
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": getInitData(),
      ...init?.headers,
    },
  });
  const payload = await response.json().catch(() => null) as ApiErrorPayload | T | null;
  if (!response.ok) {
    const error = (payload as ApiErrorPayload | null)?.error;
    const field = error?.field ? ` (${error.field})` : "";
    throw new AdminApiError(
      error?.code ?? "ADMIN_REQUEST_FAILED",
      `${error?.message ?? `Request failed with status ${response.status}`}${field}`,
    );
  }
  return payload as T;
}

async function loadAdminState(): Promise<AdminState | null> {
  const payload = await request<SettingsResponse>("/api/mini-app/settings");
  return payload.settings?.admin ?? null;
}

async function createConfirmation(action: string, telegramId?: number): Promise<Confirmation> {
  return request<Confirmation>("/api/mini-app/admin/confirmations", {
    method: "POST",
    body: JSON.stringify({
      action,
      ...(telegramId !== undefined ? { telegramId } : {}),
    }),
  });
}

function hasUnsavedSettings(): boolean {
  return Boolean(document.querySelector(".save-bar.visible"));
}

function showConfirmation(challenge: Confirmation): Promise<string | null> {
  return new Promise((resolve) => {
    const overlay = element("div", "admin-confirmation-overlay");
    const dialog = element("div", "admin-confirmation-dialog");
    const title = element("h3", "", t("confirmationTitle"));
    const hint = element("p", "", t("confirmationHint"));
    const phrase = element("code", "admin-confirmation-phrase", challenge.confirmationText);
    const input = element("input", "admin-confirmation-input");
    input.placeholder = t("confirmationPlaceholder");
    input.autocomplete = "off";
    input.spellcheck = false;
    const actions = element("div", "admin-confirmation-buttons");
    const cancel = element("button", "", t("cancel"));
    cancel.type = "button";
    const confirm = element("button", "primary", t("confirm"));
    confirm.type = "button";
    confirm.disabled = true;

    const close = (value: string | null) => {
      overlay.remove();
      resolve(value);
    };
    input.addEventListener("input", () => {
      confirm.disabled = input.value !== challenge.confirmationText;
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close(null);
      if (event.key === "Enter" && !confirm.disabled) close(input.value);
    });
    cancel.addEventListener("click", () => close(null));
    confirm.addEventListener("click", () => close(input.value));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close(null);
    });

    actions.append(cancel, confirm);
    dialog.append(title, hint, phrase, input, actions);
    overlay.append(dialog);
    document.body.append(overlay);
    window.setTimeout(() => input.focus(), 0);
  });
}

async function confirmedAction(
  action: string,
  execute: (challenge: Confirmation, confirmationText: string) => Promise<unknown>,
  telegramId?: number,
): Promise<boolean> {
  if (hasUnsavedSettings()) {
    throw new AdminApiError("UNSAVED_SETTINGS", t("unsaved"));
  }
  const challenge = await createConfirmation(action, telegramId);
  const confirmationText = await showConfirmation(challenge);
  if (confirmationText === null) return false;
  await execute(challenge, confirmationText);
  return true;
}

function hideLegacyAdminWrites(): void {
  document.querySelectorAll<HTMLElement>(".card").forEach((card) => {
    const title = card.querySelector("h2")?.textContent?.trim().toLowerCase() ?? "";
    if (
      title === "опасные операции"
      || title === "dangerous operations"
      || title === "allowlist"
    ) {
      card.hidden = true;
    }
  });
  document.querySelectorAll<HTMLElement>(".setting-row").forEach((row) => {
    const title = row.querySelector("strong")?.textContent?.trim().toLowerCase() ?? "";
    if (
      title === "публичный доступ"
      || title === "приватный доступ"
      || title === "public access"
      || title === "private access"
    ) {
      const toggle = row.querySelector<HTMLButtonElement>(".toggle");
      if (toggle) {
        toggle.disabled = true;
        toggle.title = t("description");
      }
    }
  });
}

function statusNode(card: HTMLElement): HTMLElement {
  let node = card.querySelector<HTMLElement>("[data-admin-action-status]");
  if (!node) {
    node = element("div", "admin-action-status");
    node.dataset.adminActionStatus = "";
    card.append(node);
  }
  return node;
}

function setStatus(card: HTMLElement, message: string, isError = false): void {
  const node = statusNode(card);
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function actionButton(label: string, enabled: boolean, onClick: () => void): HTMLButtonElement {
  const button = element("button", "admin-operation-button", label);
  button.type = "button";
  button.disabled = !enabled;
  button.addEventListener("click", () => {
    impact("medium");
    onClick();
  });
  return button;
}

function renderAdminCard(state: AdminState): HTMLElement {
  const card = element("section", "card admin-action-card");
  card.dataset.miniAdminActions = "";

  const heading = element("div", "card-heading");
  const headingCopy = element("div");
  headingCopy.append(
    element("h2", "", t("title")),
    element("p", "", t("description")),
  );
  heading.append(headingCopy);
  card.append(heading);

  const capabilities = state.capabilities ?? {
    accessWrite: false,
    allowlistWrite: false,
    backup: false,
    restart: false,
  };

  const access = element("div", "admin-action-section");
  access.append(
    element("strong", "", t("accessTitle")),
    element(
      "small",
      "",
      state.publicAccessEnabled ? t("accessPublic") : t("accessPrivate"),
    ),
  );
  const accessButton = actionButton(
    state.publicAccessEnabled ? t("makePrivate") : t("makePublic"),
    capabilities.accessWrite,
    () => {
      const next = !state.publicAccessEnabled;
      const action = next ? "access.public" : "access.private";
      void confirmedAction(
        action,
        (challenge, confirmationText) => request("/api/mini-app/admin/access", {
          method: "PUT",
          body: JSON.stringify({
            publicAccessEnabled: next,
            confirmationToken: challenge.token,
            confirmationText,
          }),
        }),
      ).then((completed) => {
        if (!completed) return;
        notify("success");
        setStatus(card, t("accessChanged"));
        window.setTimeout(() => window.location.reload(), 500);
      }).catch((error: unknown) => {
        notify("error");
        setStatus(card, error instanceof Error ? error.message : String(error), true);
      });
    },
  );
  access.append(accessButton);
  card.append(access);

  const allowlist = element("div", "admin-action-section");
  allowlist.append(element("strong", "", t("allowlistTitle")));
  const form = element("div", "admin-allowlist-form");
  const idInput = element("input");
  idInput.inputMode = "numeric";
  idInput.placeholder = t("telegramId");
  const nameInput = element("input");
  nameInput.placeholder = t("name");
  const usernameInput = element("input");
  usernameInput.placeholder = t("username");
  const addButton = actionButton(t("add"), capabilities.allowlistWrite, () => {
    const telegramId = Number(idInput.value.trim());
    if (!Number.isSafeInteger(telegramId) || telegramId <= 0) {
      setStatus(card, t("invalidId"), true);
      notify("warning");
      return;
    }
    void confirmedAction(
      "allowlist.add",
      (challenge, confirmationText) => request("/api/mini-app/admin/allowlist", {
        method: "POST",
        body: JSON.stringify({
          telegramId,
          name: nameInput.value.trim() || undefined,
          username: usernameInput.value.trim() || undefined,
          confirmationToken: challenge.token,
          confirmationText,
        }),
      }),
      telegramId,
    ).then((completed) => {
      if (!completed) return;
      notify("success");
      setStatus(card, t("userAdded"));
      window.setTimeout(() => window.location.reload(), 500);
    }).catch((error: unknown) => {
      notify("error");
      setStatus(card, error instanceof Error ? error.message : String(error), true);
    });
  });
  form.append(idInput, nameInput, usernameInput, addButton);
  allowlist.append(form, element("strong", "admin-runtime-title", t("runtimeUsers")));

  const runtimeUsers = state.allowedUsers.filter((user) => user.source === "runtime");
  const users = element("div", "admin-runtime-users");
  if (!runtimeUsers.length) {
    users.append(element("div", "empty-state", t("noRuntimeUsers")));
  } else {
    runtimeUsers.forEach((user) => {
      const row = element("div", "admin-runtime-user");
      const copy = element("div");
      copy.append(
        element("strong", "", user.name || String(user.telegramId)),
        element(
          "small",
          "",
          `${user.telegramId}${user.username ? ` · @${user.username}` : ""}`,
        ),
      );
      const remove = actionButton(t("remove"), capabilities.allowlistWrite, () => {
        void confirmedAction(
          "allowlist.remove",
          (challenge, confirmationText) => request(
            `/api/mini-app/admin/allowlist/${user.telegramId}`,
            {
              method: "DELETE",
              body: JSON.stringify({
                confirmationToken: challenge.token,
                confirmationText,
              }),
            },
          ),
          user.telegramId,
        ).then((completed) => {
          if (!completed) return;
          notify("success");
          setStatus(card, t("userRemoved"));
          window.setTimeout(() => window.location.reload(), 500);
        }).catch((error: unknown) => {
          notify("error");
          setStatus(card, error instanceof Error ? error.message : String(error), true);
        });
      });
      row.append(copy, remove);
      users.append(row);
    });
  }
  allowlist.append(users);
  card.append(allowlist);

  const operations = element("div", "admin-action-section");
  operations.append(element("strong", "", t("operationsTitle")));
  const operationButtons = element("div", "admin-operation-grid");
  const backup = actionButton(t("backup"), capabilities.backup, () => {
    void confirmedAction(
      "backup.create",
      (challenge, confirmationText) => request("/api/mini-app/admin/backup", {
        method: "POST",
        body: JSON.stringify({
          confirmationToken: challenge.token,
          confirmationText,
        }),
      }),
    ).then((completed) => {
      if (!completed) return;
      notify("success");
      setStatus(card, t("backupAccepted"));
    }).catch((error: unknown) => {
      notify("error");
      setStatus(card, error instanceof Error ? error.message : String(error), true);
    });
  });
  const restart = actionButton(t("restart"), capabilities.restart, () => {
    void confirmedAction(
      "bot.restart",
      (challenge, confirmationText) => request("/api/mini-app/admin/restart", {
        method: "POST",
        body: JSON.stringify({
          confirmationToken: challenge.token,
          confirmationText,
        }),
      }),
    ).then((completed) => {
      if (!completed) return;
      notify("success");
      setStatus(card, t("restartAccepted"));
    }).catch((error: unknown) => {
      notify("error");
      setStatus(card, error instanceof Error ? error.message : String(error), true);
    });
  });
  if (!capabilities.backup) backup.title = t("unavailable");
  if (!capabilities.restart) restart.title = t("unavailable");
  operationButtons.append(backup, restart);
  operations.append(operationButtons);
  if (!capabilities.backup || !capabilities.restart) {
    operations.append(element("small", "admin-capability-note", t("unavailable")));
  }
  card.append(operations);
  return card;
}

let scheduled = false;
let loading = false;
let lastLanguage = "";

async function enhanceAdminScreen(): Promise<void> {
  scheduled = false;
  const pageTitle = document.querySelector(".page-title h1")?.textContent?.trim().toLowerCase();
  const isAdmin = pageTitle === "администрирование" || pageTitle === "administration";
  if (!isAdmin || loading) return;

  hideLegacyAdminWrites();
  const currentLanguage = language();
  const existing = document.querySelector<HTMLElement>("[data-mini-admin-actions]");
  if (existing && lastLanguage === currentLanguage) return;
  existing?.remove();

  const stack = document.querySelector<HTMLElement>(".content .screen-stack");
  if (!stack) return;
  const placeholder = element("section", "card admin-action-card");
  placeholder.dataset.miniAdminActions = "";
  placeholder.append(element("div", "empty-state", t("loading")));
  stack.append(placeholder);
  lastLanguage = currentLanguage;

  if (!API_BASE_URL) {
    placeholder.replaceChildren(element("div", "empty-state", t("demo")));
    return;
  }

  loading = true;
  try {
    const state = await loadAdminState();
    if (!state?.available) {
      placeholder.remove();
      return;
    }
    placeholder.replaceWith(renderAdminCard(state));
  } catch (error: unknown) {
    placeholder.replaceChildren(
      element("div", "empty-state", error instanceof Error ? error.message : String(error)),
    );
  } finally {
    loading = false;
  }
}

function scheduleEnhancement(): void {
  if (scheduled) return;
  scheduled = true;
  window.setTimeout(() => void enhanceAdminScreen(), 20);
}

export function startAdminActionsEnhancer(): () => void {
  const observer = new MutationObserver(scheduleEnhancement);
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["class", "data-language"],
  });
  scheduleEnhancement();
  return () => observer.disconnect();
}
