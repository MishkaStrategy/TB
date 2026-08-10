import { Chip, Icon, PageHeader, Section, tx } from "../ui";
import type { AdminSettings, GeneralSettings, Language, TelegramUserSummary } from "../types";

export function SettingsScreen({ general, user, admin, language, onChangeGeneral, onOpenAdmin }: {
  general: GeneralSettings;
  user: TelegramUserSummary;
  admin: AdminSettings;
  language: Language;
  onChangeGeneral: (changes: Partial<GeneralSettings>) => void;
  onOpenAdmin: () => void;
}) {
  const initials = (user.firstName || "TB").trim().slice(0, 2).toUpperCase();
  return <div className="screen-stack settings-screen">
    <PageHeader eyebrow={tx(language, "Настройки", "Settings")} title={tx(language, "Интерфейс и профиль", "Interface & profile")} description={tx(language, "Только общие параметры. Торговые правила остаются в своих модулях.", "Only global preferences. Trading rules stay inside their modules.")} />

    <Section title={tx(language, "Интерфейс", "Interface")}>
      <div className="settings-row"><div className="settings-row-copy"><span className="row-icon"><Icon name="language" size={18} /></span><div><strong>{tx(language, "Язык", "Language")}</strong><small>{tx(language, "Язык Mini App и сообщений", "Mini App and message language")}</small></div></div><div className="chip-row compact"><Chip active={general.language === "ru"} onClick={() => onChangeGeneral({ language: "ru" })}>RU</Chip><Chip active={general.language === "en"} onClick={() => onChangeGeneral({ language: "en" })}>EN</Chip></div></div>
      <div className="settings-row"><div className="settings-row-copy"><span className="row-icon"><Icon name="message" size={18} /></span><div><strong>{tx(language, "Формат сообщений", "Message format")}</strong><small>{tx(language, "Плотность информации в уведомлениях", "Information density in alerts")}</small></div></div><div className="chip-row compact"><Chip active={general.messageMode === "compact"} onClick={() => onChangeGeneral({ messageMode: "compact" })}>Compact</Chip><Chip active={general.messageMode === "detailed"} onClick={() => onChangeGeneral({ messageMode: "detailed" })}>Detailed</Chip></div></div>
    </Section>

    <Section title={tx(language, "Профиль", "Profile")}>
      <div className="profile-card"><span className="profile-avatar large">{initials}</span><div className="profile-card-copy"><div><strong>{user.firstName || tx(language, "Трейдер", "Trader")}</strong>{admin.available ? <span className="admin-badge">Admin</span> : null}</div><span>{user.username ? `@${user.username}` : "Telegram user"}</span>{user.id !== null ? <small>Telegram ID · {user.id}</small> : null}</div></div>
    </Section>

    {admin.available ? <Section title={tx(language, "Система", "System")}><button type="button" className="settings-link" onClick={onOpenAdmin}><span className="row-icon danger-soft"><Icon name="shield" size={18} /></span><div><strong>{tx(language, "Администрирование", "Administration")}</strong><small>{tx(language, "Runtime, SQLite, outbox, access, backup и restart", "Runtime, SQLite, outbox, access, backup and restart")}</small></div><Icon name="chevron" size={18} /></button></Section> : null}
  </div>;
}
