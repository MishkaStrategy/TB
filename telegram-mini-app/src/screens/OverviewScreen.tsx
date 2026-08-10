import { EmptyState, Icon, PageHeader, PriceChange, Section, StatusBadge, activeFilterCount, exchangeLabels, formatInterval, tx } from "../ui";
import type { AppSettings, Language, MarketInstrumentSnapshot } from "../types";

export function OverviewScreen({ settings, market, maxSymbols, language, onNavigate, onOpenInstrument }: {
  settings: AppSettings;
  market: Map<string, MarketInstrumentSnapshot>;
  maxSymbols: number;
  language: Language;
  onNavigate: (tab: "fvg" | "funding") => void;
  onOpenInstrument: (key: string) => void;
}) {
  const uniqueTimeframes = new Set(settings.fvg.symbols.flatMap((item) => item.timeframes)).size;
  return <div className="screen-stack overview-screen">
    <PageHeader
      eyebrow="TB"
      title={tx(language, "Trading signals control center", "Trading signals control center")}
      description={tx(language, "Рыночные модули, правила и состояние ваших сигналов в одном компактном dashboard.", "Market modules, rules and signal state in one compact dashboard.")}
    />

    <div className="summary-grid">
      <button type="button" className="summary-card" onClick={() => onNavigate("fvg")}>
        <div className="summary-card-top"><span className="summary-icon cyan"><Icon name="fvg" /></span><StatusBadge active={settings.fvg.enabled}>{settings.fvg.enabled ? tx(language, "Включён", "On") : tx(language, "Выключен", "Off")}</StatusBadge></div>
        <div className="summary-card-title"><strong>FVG</strong><Icon name="chevron" size={17} /></div>
        <div className="summary-metrics"><div><b>{settings.fvg.symbols.filter((item) => item.enabled).length} / {maxSymbols}</b><span>{tx(language, "активных инструментов", "active instruments")}</span></div><div><b>{uniqueTimeframes}</b><span>{tx(language, "таймфрейма", "timeframes")}</span></div></div>
      </button>
      <button type="button" className="summary-card" onClick={() => onNavigate("funding")}>
        <div className="summary-card-top"><span className="summary-icon blue"><Icon name="funding" /></span><StatusBadge active={settings.funding.enabled}>{settings.funding.enabled ? tx(language, "Включён", "On") : tx(language, "Выключен", "Off")}</StatusBadge></div>
        <div className="summary-card-title"><strong>Funding</strong><Icon name="chevron" size={17} /></div>
        <div className="summary-metrics"><div><b>{settings.funding.exchanges.length}</b><span>{tx(language, "бирж", "exchanges")}</span></div><div><b>{settings.funding.threshold}%</b><span>{formatInterval(settings.funding.intervalMinutes, language)}</span></div></div>
      </button>
    </div>

    <Section title={tx(language, "Мои инструменты", "My instruments")} subtitle={tx(language, "24h изменение цены привязано к конкретной бирже", "24h price change is tied to the selected exchange") } action={<button className="icon-action" type="button" onClick={() => onNavigate("fvg")} aria-label={tx(language, "Настроить FVG", "Configure FVG")}><Icon name="settings" size={18} /></button>}>
      {settings.fvg.symbols.length ? <div className="market-list">{settings.fvg.symbols.map((item) => {
        const snapshot = market.get(item.key);
        const filters = activeFilterCount(item);
        return <button type="button" className="market-row" key={item.key} onClick={() => onOpenInstrument(item.key)}>
          <div className="market-row-main"><div className="market-symbol-line"><strong>{item.symbol}</strong><span className={`mini-dot ${item.enabled ? "active" : ""}`} /></div><span>{exchangeLabels[item.exchange]} · {item.timeframes.join(" · ")}</span><small>{item.enabled ? tx(language, "Active", "Active") : tx(language, "Paused", "Paused")}{filters ? ` · ${filters} ${tx(language, "фильтра", "filters")}` : ""}</small></div>
          <div className="market-row-side"><PriceChange value={snapshot?.priceChange24hPct} /><span>24h</span><Icon name="chevron" size={16} /></div>
        </button>;
      })}</div> : <EmptyState title={tx(language, "У вас пока нет инструментов", "No instruments yet")} description={tx(language, "Добавьте первую exchange + symbol пару для FVG.", "Add your first exchange + symbol pair for FVG.")} action={<button type="button" className="primary-button compact" onClick={() => onNavigate("fvg")}><Icon name="plus" size={18} />{tx(language, "Добавить первый инструмент", "Add first instrument")}</button>} />}
    </Section>
  </div>;
}
