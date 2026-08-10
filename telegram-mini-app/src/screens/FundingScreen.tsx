import { Chip, Icon, Metric, PageHeader, Section, StatusBadge, Toggle, exchangeLabels, exchangeOrder, formatDate, formatInterval, tx } from "../ui";
import type { Exchange, FundingSettings, Language } from "../types";

const intervalOptions = [15, 30, 60, 120, 240, 480, 720, 1440, 2880];

export function FundingScreen({ settings, language, onChange, onToggleDirection, onToggleExchange }: {
  settings: FundingSettings;
  language: Language;
  onChange: (changes: Partial<FundingSettings>) => void;
  onToggleDirection: (key: "notifyPositive" | "notifyNegative") => void;
  onToggleExchange: (exchange: Exchange) => void;
}) {
  const threshold = Number(settings.threshold.replace(",", "."));
  const bumpThreshold = (delta: number) => {
    const next = Math.max(0.0001, (Number.isFinite(threshold) ? threshold : 0.1) + delta);
    onChange({ threshold: next.toFixed(next < 0.1 ? 4 : 2).replace(/0+$/, "").replace(/\.$/, "") });
  };

  return <div className="screen-stack funding-screen">
    <PageHeader eyebrow="Funding" title={tx(language, "Funding-уведомления", "Funding Alerts")} description={tx(language, "Мультибиржевой контроль порога, направлений и расписания.", "Multi-exchange control for threshold, directions and schedule.")} trailing={<Toggle checked={settings.enabled} onChange={(enabled) => onChange({ enabled })} label={tx(language, "Включить Funding", "Enable Funding")} />} />

    <Section className="funding-summary">
      <div className="funding-summary-top"><StatusBadge active={settings.enabled}>{settings.enabled ? tx(language, "Уведомления включены", "Funding alerts on") : tx(language, "Уведомления выключены", "Funding alerts off")}</StatusBadge><span>{settings.exchanges.length} {tx(language, "бирж", "exchanges")}</span></div>
      <div className="funding-big-metrics"><Metric label={tx(language, "Порог", "Threshold")} value={`${settings.threshold}%`} /><Metric label={tx(language, "Интервал", "Interval")} value={formatInterval(settings.intervalMinutes, language)} /><Metric label={tx(language, "Следующая проверка", "Next check")} value={formatDate(settings.nextCheckAt, language)} /></div>
    </Section>

    <Section title={tx(language, "Порог", "Threshold")} subtitle={tx(language, "Абсолютное значение funding rate в процентах", "Absolute funding-rate percentage") }>
      <div className="stepper"><button type="button" aria-label={tx(language, "Уменьшить порог", "Decrease threshold")} onClick={() => bumpThreshold(-0.01)}>−</button><label><input inputMode="decimal" value={settings.threshold} onChange={(event) => onChange({ threshold: event.target.value })} /><span>%</span></label><button type="button" aria-label={tx(language, "Увеличить порог", "Increase threshold")} onClick={() => bumpThreshold(0.01)}>+</button></div>
      <div className="helper-row"><span>{tx(language, "Например 0.1%", "Example: 0.1%")}</span><span>{tx(language, "Положительное число", "Positive number")}</span></div>
    </Section>

    <Section title={tx(language, "Интервал", "Interval")} subtitle={tx(language, "Допустимо 15–2880 минут, шаг 15 минут", "Allowed range: 15–2880 minutes in 15-minute steps") }>
      <div className="chip-grid intervals">{intervalOptions.map((minutes) => <Chip key={minutes} active={settings.intervalMinutes === minutes} onClick={() => onChange({ intervalMinutes: minutes })}>{formatInterval(minutes, language)}</Chip>)}</div>
      <label className="field inline-field"><span>{tx(language, "Точный интервал", "Custom interval")}</span><div className="suffix-input"><input type="number" min={15} max={2880} step={15} value={settings.intervalMinutes} onChange={(event) => onChange({ intervalMinutes: Number(event.target.value) })} /><span>{tx(language, "мин", "min")}</span></div></label>
    </Section>

    <Section title={tx(language, "Направления", "Directions")} subtitle={tx(language, "Минимум одно направление обязательно", "At least one direction is required") }>
      <div className="direction-cards"><button type="button" className={`direction-card positive ${settings.notifyPositive ? "selected" : ""}`} aria-pressed={settings.notifyPositive} onClick={() => onToggleDirection("notifyPositive")}><div><Icon name="chart" size={20} /><strong>{tx(language, "Положительные", "Positive")}</strong></div><span>{settings.notifyPositive ? tx(language, "Выбрано", "Selected") : tx(language, "Выбрать", "Select")}</span></button><button type="button" className={`direction-card negative ${settings.notifyNegative ? "selected" : ""}`} aria-pressed={settings.notifyNegative} onClick={() => onToggleDirection("notifyNegative")}><div><Icon name="chart" size={20} /><strong>{tx(language, "Отрицательные", "Negative")}</strong></div><span>{settings.notifyNegative ? tx(language, "Выбрано", "Selected") : tx(language, "Выбрать", "Select")}</span></button></div>
    </Section>

    <Section title={tx(language, "Биржи", "Exchanges")} subtitle={tx(language, "Выберите площадки для funding-уведомлений", "Choose exchanges for funding alerts") }>
      <div className="exchange-select-grid">{exchangeOrder.map((exchange) => { const active = settings.exchanges.includes(exchange); return <button type="button" key={exchange} className={`exchange-select ${active ? "selected" : ""}`} aria-pressed={active} onClick={() => onToggleExchange(exchange)}><span className="exchange-avatar">{exchangeLabels[exchange].slice(0, 1)}</span><strong>{exchangeLabels[exchange]}</strong><span className="exchange-check">{active ? <Icon name="check" size={15} /> : null}</span></button>; })}</div>
    </Section>
  </div>;
}
