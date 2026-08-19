import { EmptyState, Icon, PageHeader, PriceChange, StatusBadge, exchangeLabels, formatInterval, tx } from "../ui";
import type { AppSettings, Language, MarketInstrumentSnapshot } from "../types";

function AssetMark({ symbol }: { symbol: string }) {
  const asset = symbol.toUpperCase().replace(/(USDT|USDC|USD|PERP)$/u, "");
  const kind = asset === "BTC" ? "btc" : asset === "ETH" ? "eth" : asset === "SOL" ? "sol" : asset === "XRP" ? "xrp" : asset === "DOGE" ? "doge" : "generic";
  const glyph = kind === "btc" ? "₿" : kind === "eth" ? "◆" : kind === "sol" ? "S" : kind === "xrp" ? "X" : kind === "doge" ? "Ð" : asset.slice(0, 1) || "·";
  return <span className={`asset-mark asset-${kind}`} aria-hidden="true">{glyph}</span>;
}

function Sparkline({ value }: { value: number | null | undefined }) {
  const numeric = typeof value === "number" && Number.isFinite(value) ? value : null;
  const tone = numeric === null ? "flat" : numeric > 0 ? "up" : numeric < 0 ? "down" : "flat";
  const points = tone === "up"
    ? "2,25 8,21 14,23 20,17 26,19 32,14 38,16 44,11 50,14 56,9 62,12 68,6 74,9 82,4"
    : tone === "down"
      ? "2,7 8,11 14,8 20,15 26,13 32,18 38,16 44,22 50,19 56,24 62,21 68,26 74,23 82,25"
      : "2,16 12,15 22,17 32,14 42,16 52,15 62,17 72,15 82,16";
  return <svg className={`market-sparkline ${tone}`} viewBox="0 0 84 30" aria-hidden="true"><polyline points={points} /></svg>;
}

export function OverviewScreen({ settings, market, maxSymbols, language, onNavigate, onOpenInstrument }: {
  settings: AppSettings;
  market: Map<string, MarketInstrumentSnapshot>;
  maxSymbols: number;
  language: Language;
  onNavigate: (tab: "fvg" | "funding") => void;
  onOpenInstrument: (key: string) => void;
}) {
  const activeCount = settings.fvg.symbols.filter((item) => item.enabled).length;
  const uniqueTimeframes = new Set(settings.fvg.symbols.flatMap((item) => item.timeframes)).size;

  return <div className="screen-stack overview-screen final-overview">
    <PageHeader
      title="TB"
      description={tx(language, "Центр управления сигналами", "Trading signals control center")}
    />

    <div className="summary-grid final-summary-grid">
      <button type="button" className="summary-card final-summary-card" onClick={() => onNavigate("fvg")}>
        <div className="summary-card-top"><div className="final-summary-heading"><span className="summary-icon muted"><Icon name="fvg" /></span><strong>FVG</strong></div><StatusBadge active={settings.fvg.enabled}>{settings.fvg.enabled ? "ON" : "OFF"}</StatusBadge></div>
        <div className="final-summary-lines">
          <div><span>{tx(language, "Активные инструменты", "Active instruments")}</span><strong>{activeCount}/{maxSymbols}</strong></div>
          <div><span>{tx(language, "Таймфреймы", "Timeframes")}</span><strong>{uniqueTimeframes}</strong></div>
        </div>
      </button>

      <button type="button" className="summary-card final-summary-card" onClick={() => onNavigate("funding")}>
        <div className="summary-card-top"><div className="final-summary-heading"><span className="summary-icon muted"><Icon name="funding" /></span><strong>Funding</strong></div><StatusBadge active={settings.funding.enabled}>{settings.funding.enabled ? "ON" : "OFF"}</StatusBadge></div>
        <div className="final-summary-lines">
          <div><span>{tx(language, "Биржи", "Exchanges")}</span><strong>{settings.funding.exchanges.length}</strong></div>
          <div><span>{tx(language, "Порог", "Threshold")}</span><strong>{settings.funding.threshold}%</strong></div>
          <div><span>{tx(language, "Интервал", "Interval")}</span><strong>{formatInterval(settings.funding.intervalMinutes, language)}</strong></div>
        </div>
      </button>
    </div>

    <section className="overview-instruments" aria-labelledby="overview-instruments-title">
      <header className="overview-section-head"><h2 id="overview-instruments-title">{tx(language, "Мои инструменты", "My instruments")}</h2><span>{activeCount}/{maxSymbols} {tx(language, "активно", "active")}</span></header>
      {settings.fvg.symbols.length ? <div className="market-list final-market-list">{settings.fvg.symbols.map((item) => {
        const snapshot = market.get(item.key);
        return <button type="button" className="market-row final-market-row" key={item.key} onClick={() => onOpenInstrument(item.key)}>
          <AssetMark symbol={item.symbol} />
          <div className="market-row-main final-market-copy">
            <strong>{item.symbol}</strong>
            <span>{exchangeLabels[item.exchange]}</span>
            <div className="final-market-meta"><div className="timeframe-line">{item.timeframes.map((timeframe) => <span key={timeframe}>{timeframe}</span>)}</div><small className={item.enabled ? "active" : ""}><i />{item.enabled ? tx(language, "Активен", "Active") : tx(language, "На паузе", "Paused")}</small></div>
          </div>
          <Sparkline value={snapshot?.priceChange24hPct} />
          <div className="final-change"><span>{tx(language, "24ч", "24h change")}</span><PriceChange value={snapshot?.priceChange24hPct} /></div>
        </button>;
      })}</div> : <EmptyState title={tx(language, "У вас пока нет инструментов", "No instruments yet")} description={tx(language, "Добавьте первую пару «биржа + символ» для FVG.", "Add your first exchange + symbol pair for FVG.")} action={<button type="button" className="primary-button compact" onClick={() => onNavigate("fvg")}><Icon name="plus" size={18} />{tx(language, "Добавить первый инструмент", "Add first instrument")}</button>} />}
    </section>
  </div>;
}
