import { Icon, Metric, PageHeader, Section, StatusBadge, activeFilterCount, exchangeLabels, formatInterval, tx } from "../ui";
import type { AppSettings, Language } from "../types";

export function NotificationsScreen({ settings, language, onNavigate }: {
  settings: AppSettings;
  language: Language;
  onNavigate: (tab: "fvg" | "funding" | "settings") => void;
}) {
  const uniqueTimeframes = new Set(settings.fvg.symbols.flatMap((item) => item.timeframes)).size;
  const activeFilters = settings.fvg.symbols.reduce((sum, item) => sum + activeFilterCount(item), 0);
  const fundingDirections = [settings.funding.notifyPositive ? "Positive" : "", settings.funding.notifyNegative ? "Negative" : ""].filter(Boolean).join(" · ");
  return <div className="screen-stack notifications-screen">
    <PageHeader eyebrow={tx(language, "Уведомления", "Alerts")} title={tx(language, "Операционная сводка", "Alert operations")} description={tx(language, "Что именно сейчас может прислать бот и какими правилами это управляется.", "What the bot can send now and which rules control it.")} />
    <Section className="alert-rule-card">
      <div className="rule-head"><div className="rule-title"><span className="summary-icon cyan"><Icon name="fvg" size={19} /></span><div><strong>FVG alerts</strong><small>Fair Value Gap</small></div></div><StatusBadge active={settings.fvg.enabled}>{settings.fvg.enabled ? "ON" : "OFF"}</StatusBadge></div>
      <div className="rule-metrics"><Metric label={tx(language, "Инструменты", "Instruments")} value={settings.fvg.symbols.length} /><Metric label={tx(language, "Таймфреймы", "Timeframes")} value={uniqueTimeframes} /><Metric label={tx(language, "Фильтры", "Filters")} value={activeFilters} /></div>
      <div className="rule-tags"><span className={settings.fvg.bullishEnabled ? "on positive" : ""}>Bullish</span><span className={settings.fvg.bearishEnabled ? "on negative" : ""}>Bearish</span><span className={settings.fvg.notifyConfirmedFvg ? "on" : ""}>Confirmed</span></div>
      <button type="button" className="secondary-button full" onClick={() => onNavigate("fvg")}><Icon name="edit" size={17} />{tx(language, "Изменить FVG", "Edit FVG")}</button>
    </Section>
    <Section className="alert-rule-card">
      <div className="rule-head"><div className="rule-title"><span className="summary-icon blue"><Icon name="funding" size={19} /></span><div><strong>Funding alerts</strong><small>Multi-exchange funding</small></div></div><StatusBadge active={settings.funding.enabled}>{settings.funding.enabled ? "ON" : "OFF"}</StatusBadge></div>
      <div className="rule-metrics"><Metric label={tx(language, "Порог", "Threshold")} value={`${settings.funding.threshold}%`} /><Metric label={tx(language, "Интервал", "Interval")} value={formatInterval(settings.funding.intervalMinutes, language)} /><Metric label={tx(language, "Биржи", "Exchanges")} value={settings.funding.exchanges.length} hint={settings.funding.exchanges.map((item) => exchangeLabels[item]).join(", ")} /></div>
      <div className="rule-tags"><span className="on">{fundingDirections}</span></div>
      <button type="button" className="secondary-button full" onClick={() => onNavigate("funding")}><Icon name="edit" size={17} />{tx(language, "Изменить Funding", "Edit Funding")}</button>
    </Section>
    <Section className="alert-rule-card compact-rule"><div className="rule-head"><div className="rule-title"><span className="summary-icon muted"><Icon name="message" size={19} /></span><div><strong>{tx(language, "Формат сообщений", "Message format")}</strong><small>{settings.general.language === "ru" ? "RU" : "EN"} · {settings.general.messageMode === "compact" ? "Compact" : "Detailed"}</small></div></div><button type="button" className="text-action" onClick={() => onNavigate("settings")}>{tx(language, "Изменить", "Edit")}<Icon name="chevron" size={15} /></button></div></Section>
  </div>;
}
