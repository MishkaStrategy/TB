import { useMemo, useState } from "react";
import { addAllowlistUser, createAdminConfirmation, createBackup, removeAllowlistUser, restartBot, setPublicAccess } from "../adminApi";
import { Icon, Metric, PageHeader, Section, formatBytes, formatDate, tx } from "../ui";
import { notify } from "../telegram";
import type { AdminConfirmation, AdminSettings, Language } from "../types";

type PendingAction = {
  confirmation: AdminConfirmation;
  execute: (confirmationText: string) => Promise<void>;
};

export function AdminScreen({ admin, language, dirty, onRefresh }: {
  admin: AdminSettings;
  language: Language;
  dirty: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [allowlistId, setAllowlistId] = useState("");
  const [allowlistName, setAllowlistName] = useState("");
  const [allowlistUsername, setAllowlistUsername] = useState("");
  const d = admin.diagnostics;
  const runtimeUsers = useMemo(() => admin.allowedUsers.filter((item) => item.source === "runtime"), [admin.allowedUsers]);
  const capabilities = admin.capabilities ?? { accessWrite: false, allowlistWrite: false, backup: false, restart: false };

  const begin = async (action: string, execute: (confirmation: AdminConfirmation, text: string) => Promise<void>, telegramId?: number) => {
    if (dirty) {
      setMessage(tx(language, "Сначала сохраните изменения обычных настроек.", "Save regular settings changes first."));
      notify("warning");
      return;
    }
    try {
      setMessage("");
      const confirmation = await createAdminConfirmation(action, telegramId);
      setConfirmationText("");
      setPending({ confirmation, execute: (text) => execute(confirmation, text) });
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : String(error));
      notify("error");
    }
  };

  const confirm = async () => {
    if (!pending || confirmationText !== pending.confirmation.confirmationText || working) return;
    setWorking(true);
    try {
      await pending.execute(confirmationText);
      setPending(null);
      setConfirmationText("");
      setMessage(tx(language, "Операция выполнена.", "Operation completed."));
      notify("success");
      await onRefresh();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : String(error));
      notify("error");
    } finally {
      setWorking(false);
    }
  };

  const addUser = () => {
    const telegramId = Number(allowlistId.trim());
    if (!Number.isSafeInteger(telegramId) || telegramId <= 0) {
      setMessage(tx(language, "Введите корректный положительный Telegram ID.", "Enter a valid positive Telegram ID."));
      notify("warning");
      return;
    }
    void begin("allowlist.add", async (confirmation, text) => {
      await addAllowlistUser(telegramId, allowlistName.trim(), allowlistUsername.trim(), confirmation, text);
      setAllowlistId(""); setAllowlistName(""); setAllowlistUsername("");
    }, telegramId);
  };

  if (!admin.available) return null;
  return <div className="screen-stack admin-screen">
    <PageHeader eyebrow="Admin" title={tx(language, "Администрирование", "Administration")} description={tx(language, "Runtime, storage, delivery state и подтверждаемые operational actions.", "Runtime, storage, delivery state and confirmed operational actions.")} />
    {message ? <div className="inline-message"><Icon name="alert" size={17} /><span>{message}</span></div> : null}

    <div className="admin-grid">
      <Section title="Runtime" className="admin-metric-panel"><div className="diagnostic-grid"><Metric label="Release" value={d.release || "—"} hint={d.gitCommit || undefined} /><Metric label="PID" value={d.pid || "—"} /><Metric label="Python" value={d.pythonVersion || "—"} /><Metric label="Load" value={d.loadAverage?.map((item) => item.toFixed(2)).join(" · ") || "—"} /></div></Section>
      <Section title="WebSocket / REST" className="admin-metric-panel"><div className="diagnostic-grid"><Metric label="WebSocket" value={d.websocket} /><Metric label={tx(language, "Последнее WS", "Last WS")} value={formatDate(d.lastWebsocketMessage, language)} /><Metric label={tx(language, "REST recovery", "REST recovery")} value={formatDate(d.lastRestRecovery, language)} /><Metric label={tx(language, "Последняя ошибка", "Last error")} value={d.lastError || "—"} /></div></Section>
      <Section title="SQLite" className="admin-metric-panel"><div className="diagnostic-grid"><Metric label="FVG" value={d.fvgDatabaseStatus} hint={formatBytes(d.fvgDatabaseBytes)} /><Metric label="Funding" value={d.fundingDatabaseStatus} hint={formatBytes(d.fundingDatabaseBytes)} /><Metric label="JSON" value={formatBytes(d.jsonSettingsBytes)} /><Metric label={tx(language, "Общий статус", "Overall status")} value={d.databases} /></div></Section>
      <Section title="Outbox" className="admin-metric-panel"><div className="diagnostic-grid"><Metric label="Queued" value={d.outbox} /><Metric label="Deliveries" value={d.deliveries} /><Metric label="Retries" value={d.deliveryRetries} /><Metric label="Permanent" value={d.deliveryPermanentFailures} hint={`${d.deliveryFailures} failures`} /></div></Section>
      <Section title={tx(language, "Ресурсы", "Resources")} className="admin-metric-panel"><div className="diagnostic-grid"><Metric label="Memory" value={formatBytes(d.processMemoryBytes)} /><Metric label="Disk free" value={formatBytes(d.diskFreeBytes)} hint={`${formatBytes(d.diskTotalBytes)} total`} /></div></Section>
    </div>

    <Section title={tx(language, "Доступ", "Access")} subtitle={tx(language, "Server-side admin check остаётся единственным источником полномочий", "Server-side admin check remains the authority") }>
      <div className="admin-access-row"><div><strong>{admin.publicAccessEnabled ? tx(language, "Публичный доступ", "Public access") : tx(language, "Приватный доступ", "Private access")}</strong><small>{admin.publicAccessEnabled ? tx(language, "Mini App разрешён всем прошедшим Telegram auth", "Mini App allowed for all Telegram-authenticated users") : tx(language, "Только allowlist и admins", "Allowlist and admins only")}</small></div><button type="button" className="secondary-button" disabled={!capabilities.accessWrite} onClick={() => void begin(admin.publicAccessEnabled ? "access.private" : "access.public", (confirmation, text) => setPublicAccess(!admin.publicAccessEnabled, confirmation, text))}>{admin.publicAccessEnabled ? tx(language, "Сделать приватным", "Make private") : tx(language, "Сделать публичным", "Make public")}</button></div>
    </Section>

    <Section title="Allowlist" subtitle={tx(language, "Env/admin записи защищены; удаляются только runtime-записи", "Env/admin entries are protected; only runtime entries can be removed") }>
      <div className="allowlist-form"><input inputMode="numeric" value={allowlistId} onChange={(event) => setAllowlistId(event.target.value)} placeholder="Telegram ID" /><input value={allowlistName} onChange={(event) => setAllowlistName(event.target.value)} placeholder={tx(language, "Имя", "Name")} /><input value={allowlistUsername} onChange={(event) => setAllowlistUsername(event.target.value)} placeholder="Username" /><button type="button" className="primary-button" disabled={!capabilities.allowlistWrite} onClick={addUser}><Icon name="plus" size={17} />{tx(language, "Добавить", "Add")}</button></div>
      <div className="allowlist-list">{admin.allowedUsers.map((user) => <div className="allowlist-row" key={`${user.source}-${user.telegramId}`}><div><strong>{user.name || String(user.telegramId)}</strong><span>{user.telegramId}{user.username ? ` · @${user.username}` : ""}</span></div>{user.source === "runtime" ? <button type="button" className="icon-action danger-soft" disabled={!capabilities.allowlistWrite} onClick={() => void begin("allowlist.remove", (confirmation, text) => removeAllowlistUser(user.telegramId, confirmation, text), user.telegramId)} aria-label={tx(language, "Удалить пользователя", "Remove user")}><Icon name="trash" size={17} /></button> : <span className="protected-label">{user.source}</span>}</div>)}</div>
      {!runtimeUsers.length ? <small className="admin-note">{tx(language, "Runtime allowlist пуст.", "Runtime allowlist is empty.")}</small> : null}
    </Section>

    <Section title={tx(language, "Опасные операции", "Dangerous operations")} subtitle={tx(language, "Всегда требуют отдельной одноразовой фразы подтверждения", "Always require a separate one-time confirmation phrase")} className="danger-zone">
      <div className="danger-actions"><button type="button" className="secondary-button" disabled={!capabilities.backup} onClick={() => void begin("backup.create", (confirmation, text) => createBackup(confirmation, text))}><Icon name="database" size={18} />{tx(language, "Создать backup", "Create backup")}</button><button type="button" className="danger-button" disabled={!capabilities.restart} onClick={() => void begin("bot.restart", (confirmation, text) => restartBot(confirmation, text))}><Icon name="refresh" size={18} />{tx(language, "Перезапустить бота", "Restart bot")}</button></div>
      {(!capabilities.backup || !capabilities.restart) ? <small className="admin-note">{tx(language, "Недоступные действия остаются fail-closed, пока production callbacks не подключены.", "Unavailable actions remain fail-closed until production callbacks are connected.")}</small> : null}
    </Section>

    {pending ? <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !working) setPending(null); }}><div className="confirmation-modal" role="dialog" aria-modal="true" aria-labelledby="confirmation-title"><span className="modal-icon danger-soft"><Icon name="shield" size={22} /></span><h2 id="confirmation-title">{tx(language, "Подтвердите действие", "Confirm action")}</h2><p>{tx(language, "Введите точную одноразовую фразу:", "Enter the exact one-time phrase:")}</p><code>{pending.confirmation.confirmationText}</code><input autoFocus autoComplete="off" spellCheck={false} value={confirmationText} onChange={(event) => setConfirmationText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void confirm(); if (event.key === "Escape" && !working) setPending(null); }} placeholder={tx(language, "Фраза подтверждения", "Confirmation phrase")} /><div className="modal-actions"><button type="button" className="secondary-button" disabled={working} onClick={() => setPending(null)}>{tx(language, "Отмена", "Cancel")}</button><button type="button" className="danger-button" disabled={working || confirmationText !== pending.confirmation.confirmationText} onClick={() => void confirm()}>{tx(language, "Подтвердить", "Confirm")}</button></div></div></div> : null}
  </div>;
}
