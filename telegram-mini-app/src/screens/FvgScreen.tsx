import { useState } from "react";
import { Chip, EmptyState, Icon, PageHeader, PriceChange, Section, StatusBadge, Toggle, activeFilterCount, exchangeLabels, exchangeOrder, timeframeOrder, tx } from "../ui";
import type { Exchange, FilterScope, FvgSizeUnit, FvgSymbolSettings, FvgTimeframe, Language, MarketInstrumentSnapshot } from "../types";

function ScopeSelector({ scope, language, onChange }: { scope: FilterScope; language: Language; onChange: (scope: FilterScope) => void }) {
  const rows: Array<[keyof FilterScope, string, string]> = [
    ["confirmedFvg", "Подтверждённые", "Confirmed FVG"],
    ["bullish", "Бычьи", "Bullish"],
    ["bearish", "Медвежьи", "Bearish"],
  ];
  return <div className="scope-row">{rows.map(([key, ru, en]) => <Chip key={key} active={scope[key]} onClick={() => onChange({ ...scope, [key]: !scope[key] })}>{tx(language, ru, en)}</Chip>)}</div>;
}

export function FvgScreen({
  enabled, notifyConfirmedFvg, bullishEnabled, bearishEnabled, instruments, selected, market,
  maxSymbols, language, onToggleEnabled, onToggleConfirmed, onToggleBullish, onToggleBearish,
  onSelect, onAdd, onRemove, onToggleInstrument, onChangeExchange, onToggleTimeframe,
  onUpdatePriceFilter, onUpdateSizeFilter,
}: {
  enabled: boolean;
  notifyConfirmedFvg: boolean;
  bullishEnabled: boolean;
  bearishEnabled: boolean;
  instruments: FvgSymbolSettings[];
  selected?: FvgSymbolSettings;
  market: Map<string, MarketInstrumentSnapshot>;
  maxSymbols: number;
  language: Language;
  onToggleEnabled: (value: boolean) => void;
  onToggleConfirmed: (value: boolean) => void;
  onToggleBullish: (value: boolean) => void;
  onToggleBearish: (value: boolean) => void;
  onSelect: (key: string) => void;
  onAdd: (exchange: Exchange, symbol: string) => void;
  onRemove: (key: string) => void;
  onToggleInstrument: (key: string, value: boolean) => void;
  onChangeExchange: (instrument: FvgSymbolSettings, exchange: Exchange) => void;
  onToggleTimeframe: (instrument: FvgSymbolSettings, timeframe: FvgTimeframe) => void;
  onUpdatePriceFilter: (instrument: FvgSymbolSettings, changes: Partial<FvgSymbolSettings["priceFilter"]>) => void;
  onUpdateSizeFilter: (instrument: FvgSymbolSettings, changes: Partial<FvgSymbolSettings["sizeFilter"]>) => void;
}) {
  const [newExchange, setNewExchange] = useState<Exchange>("bitunix");
  const [newSymbol, setNewSymbol] = useState("");
  const atLimit = instruments.length >= maxSymbols;
  const submitAdd = () => {
    onAdd(newExchange, newSymbol);
    if (newSymbol.trim()) setNewSymbol("");
  };

  return <div className="screen-stack fvg-screen">
    <PageHeader eyebrow="FVG" title="Fair Value Gap" description={tx(language, "Инструменты по биржам, таймфреймы и фильтры подтверждённых FVG.", "Exchange-aware instruments, timeframes and confirmed FVG filters.")} trailing={<Toggle checked={enabled} onChange={onToggleEnabled} label={tx(language, "Включить FVG", "Enable FVG")} />} />

    <div className="module-status-strip"><StatusBadge active={enabled}>{enabled ? tx(language, "Модуль активен", "Module active") : tx(language, "Модуль на паузе", "Module paused")}</StatusBadge><span>{instruments.length} / {maxSymbols} {tx(language, "инструментов", "instruments")}</span></div>

    <Section title={tx(language, "Инструменты", "Instruments")} subtitle={tx(language, "Одинаковый символ на разных биржах считается отдельным инструментом", "The same symbol on different exchanges is a separate instrument")}>
      {instruments.length ? <div className="instrument-list">{instruments.map((item) => {
        const snapshot = market.get(item.key);
        const filters = activeFilterCount(item);
        return <button type="button" key={item.key} className={`instrument-card ${selected?.key === item.key ? "selected" : ""}`} onClick={() => onSelect(item.key)}>
          <div className="instrument-card-copy"><div><strong>{item.symbol}</strong><span>{exchangeLabels[item.exchange]}</span></div><div className="timeframe-line">{item.timeframes.map((tf) => <span key={tf}>{tf}</span>)}</div><small>{item.enabled ? tx(language, "Активен", "Active") : tx(language, "На паузе", "Paused")}{filters ? ` · ${filters} ${tx(language, "фильтров", "filters active")}` : ""}</small></div>
          <div className="instrument-card-side"><PriceChange value={snapshot?.priceChange24hPct} /><span>24h</span><Icon name="chevron" size={17} /></div>
        </button>;
      })}</div> : <EmptyState title={tx(language, "У вас пока нет инструментов", "No instruments yet")} description={tx(language, "Добавьте первую пару «биржа + символ».", "Add your first exchange + symbol pair.")} />}
    </Section>

    <Section title={tx(language, "Добавить инструмент", "Add instrument")} subtitle={atLimit ? tx(language, `Достигнут технический лимит: ${maxSymbols}.`, `Technical limit reached: ${maxSymbols}.`) : tx(language, "Новый инструмент начинает работу с таймфрейма 15m", "New instruments start with the 15m timeframe")} className="add-instrument-panel">
      <div className="add-instrument-form"><label><span>{tx(language, "Биржа", "Exchange")}</span><select value={newExchange} onChange={(event) => setNewExchange(event.target.value as Exchange)} disabled={atLimit}>{exchangeOrder.map((exchange) => <option key={exchange} value={exchange}>{exchangeLabels[exchange]}</option>)}</select></label><label className="symbol-field"><span>{tx(language, "Символ", "Symbol")}</span><input value={newSymbol} disabled={atLimit} placeholder="BTCUSDT" autoCapitalize="characters" onChange={(event) => setNewSymbol(event.target.value.toUpperCase())} onKeyDown={(event) => { if (event.key === "Enter") submitAdd(); }} /></label><button type="button" className="primary-button" disabled={atLimit} onClick={submitAdd}><Icon name="plus" size={18} />{tx(language, "Добавить", "Add")}</button></div>
    </Section>

    {selected ? <Section title={`${selected.symbol} · ${exchangeLabels[selected.exchange]}`} subtitle={tx(language, "Настройки инструмента", "Instrument configuration")} action={<Toggle checked={selected.enabled} onChange={(value) => onToggleInstrument(selected.key, value)} label={tx(language, "Включить инструмент", "Enable instrument")} />} className="instrument-editor">
      <div className="editor-grid">
        <label className="field"><span>{tx(language, "Биржа", "Exchange")}</span><select value={selected.exchange} onChange={(event) => onChangeExchange(selected, event.target.value as Exchange)}>{exchangeOrder.map((exchange) => <option key={exchange} value={exchange}>{exchangeLabels[exchange]}</option>)}</select></label>
        <label className="field"><span>{tx(language, "Символ", "Symbol")}</span><input value={selected.symbol} readOnly aria-readonly="true" /></label>
      </div>
      <div className="editor-block"><div className="editor-label"><strong>{tx(language, "Таймфреймы", "Timeframes")}</strong><span>{tx(language, "Минимум один", "At least one")}</span></div><div className="chip-row">{timeframeOrder.map((timeframe) => <Chip key={timeframe} active={selected.timeframes.includes(timeframe)} onClick={() => onToggleTimeframe(selected, timeframe)}>{timeframe}</Chip>)}</div></div>
      <div className="editor-block"><div className="editor-label"><strong>{tx(language, "Направления и подтверждение", "Directions and confirmation")}</strong><span>{tx(language, "Общие для FVG-модуля", "Applies to the FVG module")}</span></div><div className="chip-row"><Chip active={bullishEnabled} tone="positive" onClick={() => onToggleBullish(!bullishEnabled)}>{tx(language, "Бычьи", "Bullish")}</Chip><Chip active={bearishEnabled} tone="negative" onClick={() => onToggleBearish(!bearishEnabled)}>{tx(language, "Медвежьи", "Bearish")}</Chip><Chip active={notifyConfirmedFvg} onClick={() => onToggleConfirmed(!notifyConfirmedFvg)}>{tx(language, "Подтверждённые", "Confirmed FVG")}</Chip></div></div>

      <div className="filter-card"><div className="filter-card-head"><div><span className="filter-icon"><Icon name="filter" size={17} /></span><div><strong>{tx(language, "Фильтр цены", "Price filter")}</strong><small>{tx(language, "Диапазон цены и область применения", "Price range and application scope")}</small></div></div><Toggle checked={selected.priceFilter.enabled} onChange={(value) => onUpdatePriceFilter(selected, { enabled: value })} label={tx(language, "Фильтр цены", "Price filter")} /></div><div className="filter-fields"><label><span>Min</span><input inputMode="decimal" value={selected.priceFilter.min ?? ""} onChange={(event) => onUpdatePriceFilter(selected, { min: event.target.value || null })} placeholder="0" /></label><label><span>Max</span><input inputMode="decimal" value={selected.priceFilter.max ?? ""} onChange={(event) => onUpdatePriceFilter(selected, { max: event.target.value || null })} placeholder="—" /></label></div><ScopeSelector scope={selected.priceFilter.scope} language={language} onChange={(scope) => onUpdatePriceFilter(selected, { scope })} /></div>

      <div className="filter-card"><div className="filter-card-head"><div><span className="filter-icon"><Icon name="filter" size={17} /></span><div><strong>{tx(language, "Фильтр размера FVG", "FVG size filter")}</strong><small>{tx(language, "Минимальный размер FVG", "Minimum FVG size")}</small></div></div><Toggle checked={selected.sizeFilter.enabled} onChange={(value) => onUpdateSizeFilter(selected, { enabled: value })} label={tx(language, "Фильтр размера FVG", "FVG size filter")} /></div><div className="filter-fields"><label><span>Min</span><input inputMode="decimal" value={selected.sizeFilter.min ?? ""} onChange={(event) => onUpdateSizeFilter(selected, { min: event.target.value || null })} placeholder="0" /></label><label><span>{tx(language, "Единица", "Unit")}</span><select value={selected.sizeFilter.unit} onChange={(event) => onUpdateSizeFilter(selected, { unit: event.target.value as FvgSizeUnit })}><option value="USD">USD</option><option value="PERCENT">%</option></select></label></div><ScopeSelector scope={selected.sizeFilter.scope} language={language} onChange={(scope) => onUpdateSizeFilter(selected, { scope })} /></div>

      <button type="button" className="danger-button" onClick={() => onRemove(selected.key)}><Icon name="trash" size={18} />{tx(language, "Удалить инструмент", "Delete instrument")}</button>
    </Section> : null}
  </div>;
}
