import { useEffect, useMemo, useState } from "react";
import { loadMarketOverview, loadSettings, saveSettings } from "./api";
import { notify, impact, setUnsavedChanges } from "./telegram";
import { AdminScreen } from "./screens/AdminScreen";
import { FundingScreen } from "./screens/FundingScreen";
import { FvgScreen } from "./screens/FvgScreen";
import { NotificationsScreen } from "./screens/NotificationsScreen";
import { OverviewScreen } from "./screens/OverviewScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { Icon, tx } from "./ui";
import type {
  AppSettings,
  Exchange,
  FilterScope,
  FvgSymbolSettings,
  FvgTimeframe,
  MarketOverviewEnvelope,
  SettingsEnvelope,
} from "./types";

type Tab = "overview" | "fvg" | "funding" | "notifications" | "settings" | "admin";

const defaultScope: FilterScope = {
  confirmedFvg: true,
  bullish: true,
  bearish: true,
};

const makeInstrumentKey = (exchange: Exchange, symbol: string) => (
  exchange === "bitunix" ? symbol : `${exchange}|${symbol}`
);

export default function TradingApp() {
  const [envelope, setEnvelope] = useState<SettingsEnvelope | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [baseline, setBaseline] = useState("");
  const [marketOverview, setMarketOverview] = useState<MarketOverviewEnvelope | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [selectedInstrumentKey, setSelectedInstrumentKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [marketError, setMarketError] = useState("");
  const [toast, setToast] = useState("");

  const refreshMarket = async () => {
    try {
      setMarketError("");
      setMarketOverview(await loadMarketOverview());
    } catch (error: unknown) {
      setMarketOverview(null);
      setMarketError(error instanceof Error ? error.message : "Market data unavailable");
    }
  };

  const applyEnvelope = (result: SettingsEnvelope) => {
    setEnvelope(result);
    setSettings(result.settings);
    setBaseline(JSON.stringify(result.settings));
    setSelectedInstrumentKey((current) => (
      current && result.settings.fvg.symbols.some((item) => item.key === current)
        ? current
        : result.settings.fvg.symbols[0]?.key ?? ""
    ));
  };

  const refreshSettings = async () => {
    const result = await loadSettings();
    applyEnvelope(result);
  };

  const hydrate = async () => {
    setLoading(true);
    setSettingsError("");
    try {
      await refreshSettings();
      await refreshMarket();
    } catch (error: unknown) {
      setSettingsError(error instanceof Error ? error.message : "Не удалось загрузить Mini App");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void hydrate(); }, []);

  const dirty = useMemo(
    () => Boolean(settings && baseline && JSON.stringify(settings) !== baseline),
    [settings, baseline],
  );

  useEffect(() => {
    setUnsavedChanges(dirty);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  useEffect(() => {
    const language = settings?.general.language;
    if (!language) return;
    document.documentElement.lang = language;
    document.documentElement.dataset.language = language;
  }, [settings?.general.language]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const market = useMemo(
    () => new Map((marketOverview?.instruments ?? []).map((item) => [item.key, item])),
    [marketOverview],
  );

  if (loading) {
    return <main className="app-shell skeleton-shell"><header className="topbar"><div className="brand"><div className="brand-mark skeleton-box" /><div><span className="skeleton-line w60" /><span className="skeleton-line w40" /></div></div><div className="profile-avatar skeleton-box" /></header><div className="content skeleton-dashboard"><div className="skeleton-line title" /><div className="skeleton-line subtitle" /><div className="summary-grid"><div className="skeleton-card" /><div className="skeleton-card" /></div><div className="skeleton-card tall" /></div></main>;
  }

  if (!settings || !envelope) {
    return <main className="state-screen"><div className="state-symbol"><Icon name="alert" size={25} /></div><strong>Mini App unavailable</strong><span>{settingsError || "Open the Mini App from Telegram and try again."}</span><button type="button" className="primary-button" onClick={() => void hydrate()}><Icon name="refresh" size={18} />Retry</button></main>;
  }

  const language = settings.general.language;
  const maxSymbols = envelope.limits?.maxFvgSymbols ?? 10;
  const selected = settings.fvg.symbols.find((item) => item.key === selectedInstrumentKey) ?? settings.fvg.symbols[0];
  const initials = (envelope.user.firstName || "TB").trim().slice(0, 2).toUpperCase();

  const updateSettings = (updater: (current: AppSettings) => AppSettings) => {
    setSettings((current) => current ? updater(current) : current);
  };
  const updateGeneral = (changes: Partial<AppSettings["general"]>) => {
    updateSettings((current) => ({ ...current, general: { ...current.general, ...changes } }));
  };
  const updateFvg = (changes: Partial<AppSettings["fvg"]>) => updateSettings((current) => ({ ...current, fvg: { ...current.fvg, ...changes } }));
  const updateFunding = (changes: Partial<AppSettings["funding"]>) => updateSettings((current) => ({ ...current, funding: { ...current.funding, ...changes } }));
  const updateInstrument = (key: string, updater: (item: FvgSymbolSettings) => FvgSymbolSettings) => updateSettings((current) => ({ ...current, fvg: { ...current.fvg, symbols: current.fvg.symbols.map((item) => item.key === key ? updater(item) : item) } }));

  const navigate = (next: Tab) => {
    if (next === "admin" && !settings.admin.available) return;
    setTab(next);
    impact("light");
    window.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    setSettingsError("");
    try {
      const result = await saveSettings(settings);
      applyEnvelope(result);
      setToast(tx(result.settings.general.language, "Настройки сохранены", "Settings saved"));
      notify("success");
      await refreshMarket();
    } catch (error: unknown) {
      setSettingsError(error instanceof Error ? error.message : "Save failed");
      notify("error");
    } finally {
      setSaving(false);
    }
  };

  const addInstrument = (exchange: Exchange, rawSymbol: string) => {
    const symbol = rawSymbol.trim().toUpperCase().replace(/[\/_\-\s]/g, "");
    if (!/^[A-Z0-9]{5,20}$/.test(symbol)) {
      setToast(tx(language, "Введите корректный symbol, например ETHUSDT", "Enter a valid symbol, e.g. ETHUSDT"));
      notify("warning");
      return;
    }
    if (settings.fvg.symbols.length >= maxSymbols) {
      setToast(tx(language, `Достигнут лимит: ${maxSymbols}`, `Limit reached: ${maxSymbols}`));
      notify("warning");
      return;
    }
    const key = makeInstrumentKey(exchange, symbol);
    if (settings.fvg.symbols.some((item) => item.key === key)) {
      setSelectedInstrumentKey(key);
      setToast(tx(language, "Инструмент уже добавлен", "Instrument already exists"));
      return;
    }
    const instrument: FvgSymbolSettings = {
      key,
      exchange,
      symbol,
      timeframes: ["15m"],
      enabled: true,
      priceFilter: { enabled: false, min: null, max: null, scope: { ...defaultScope } },
      sizeFilter: { enabled: false, unit: "USD", min: null, scope: { ...defaultScope } },
    };
    updateFvg({ symbols: [...settings.fvg.symbols, instrument] });
    setSelectedInstrumentKey(key);
    impact("medium");
  };

  const removeInstrument = (key: string) => {
    const next = settings.fvg.symbols.filter((item) => item.key !== key);
    updateFvg({ symbols: next });
    setSelectedInstrumentKey(next[0]?.key ?? "");
    impact("medium");
  };

  const changeInstrumentExchange = (instrument: FvgSymbolSettings, exchange: Exchange) => {
    const nextKey = makeInstrumentKey(exchange, instrument.symbol);
    if (settings.fvg.symbols.some((item) => item.key === nextKey && item.key !== instrument.key)) {
      setToast(tx(language, "Такая exchange + symbol пара уже существует", "This exchange + symbol pair already exists"));
      notify("warning");
      return;
    }
    updateInstrument(instrument.key, (item) => ({ ...item, exchange, key: nextKey }));
    setSelectedInstrumentKey(nextKey);
  };

  const toggleTimeframe = (instrument: FvgSymbolSettings, timeframe: FvgTimeframe) => {
    const active = instrument.timeframes.includes(timeframe);
    if (active && instrument.timeframes.length === 1) {
      setToast(tx(language, "Выберите хотя бы один таймфрейм", "Select at least one timeframe"));
      notify("warning");
      return;
    }
    const selectedTimeframes = new Set(instrument.timeframes);
    active ? selectedTimeframes.delete(timeframe) : selectedTimeframes.add(timeframe);
    const order: FvgTimeframe[] = ["15m", "1h", "4h", "1d"];
    updateInstrument(instrument.key, (item) => ({ ...item, timeframes: order.filter((value) => selectedTimeframes.has(value)) }));
  };

  const toggleFundingDirection = (key: "notifyPositive" | "notifyNegative") => {
    const next = { ...settings.funding, [key]: !settings.funding[key] };
    if (!next.notifyPositive && !next.notifyNegative) {
      setToast(tx(language, "Выберите хотя бы одно направление", "Select at least one direction"));
      notify("warning");
      return;
    }
    updateFunding({ [key]: next[key] });
  };

  const toggleFundingExchange = (exchange: Exchange) => {
    const chosen = new Set(settings.funding.exchanges);
    if (chosen.has(exchange)) {
      if (chosen.size === 1) {
        setToast(tx(language, "Выберите хотя бы одну биржу", "Select at least one exchange"));
        notify("warning");
        return;
      }
      chosen.delete(exchange);
    } else chosen.add(exchange);
    const order: Exchange[] = ["bitunix", "binance", "bybit", "bingx", "bitget", "gate"];
    updateFunding({ exchanges: order.filter((item) => chosen.has(item)) });
  };

  const renderScreen = () => {
    if (tab === "overview") return <OverviewScreen settings={settings} market={market} maxSymbols={maxSymbols} language={language} onNavigate={navigate} onOpenInstrument={(key) => { setSelectedInstrumentKey(key); navigate("fvg"); }} />;
    if (tab === "fvg") return <FvgScreen enabled={settings.fvg.enabled} notifyConfirmedFvg={settings.fvg.notifyConfirmedFvg} bullishEnabled={settings.fvg.bullishEnabled} bearishEnabled={settings.fvg.bearishEnabled} instruments={settings.fvg.symbols} selected={selected} market={market} maxSymbols={maxSymbols} language={language} onToggleEnabled={(enabled) => updateFvg({ enabled })} onToggleConfirmed={(notifyConfirmedFvg) => updateFvg({ notifyConfirmedFvg })} onToggleBullish={(bullishEnabled) => updateFvg({ bullishEnabled })} onToggleBearish={(bearishEnabled) => updateFvg({ bearishEnabled })} onSelect={setSelectedInstrumentKey} onAdd={addInstrument} onRemove={removeInstrument} onToggleInstrument={(key, enabled) => updateInstrument(key, (item) => ({ ...item, enabled }))} onChangeExchange={changeInstrumentExchange} onToggleTimeframe={toggleTimeframe} onUpdatePriceFilter={(instrument, changes) => updateInstrument(instrument.key, (item) => ({ ...item, priceFilter: { ...item.priceFilter, ...changes } }))} onUpdateSizeFilter={(instrument, changes) => updateInstrument(instrument.key, (item) => ({ ...item, sizeFilter: { ...item.sizeFilter, ...changes } }))} />;
    if (tab === "funding") return <FundingScreen settings={settings.funding} language={language} onChange={(changes) => { if (changes.intervalMinutes !== undefined && Number.isFinite(changes.intervalMinutes)) { const intervalMinutes = Math.max(15, Math.min(2880, Math.round(changes.intervalMinutes / 15) * 15)); updateFunding({ ...changes, intervalMinutes }); } else updateFunding(changes); }} onToggleDirection={toggleFundingDirection} onToggleExchange={toggleFundingExchange} />;
    if (tab === "notifications") return <NotificationsScreen settings={settings} language={language} onNavigate={navigate} />;
    if (tab === "settings") return <SettingsScreen general={settings.general} user={envelope.user} admin={settings.admin} language={language} onChangeGeneral={updateGeneral} onOpenAdmin={() => navigate("admin")} />;
    return <AdminScreen admin={settings.admin} language={language} dirty={dirty} onRefresh={async () => { await refreshSettings(); }} />;
  };

  const navItems: Array<[Exclude<Tab, "admin">, "home" | "fvg" | "funding" | "bell" | "settings", string, string]> = [
    ["overview", "home", "Главная", "Home"],
    ["fvg", "fvg", "FVG", "FVG"],
    ["funding", "funding", "Funding", "Funding"],
    ["notifications", "bell", "Уведомления", "Alerts"],
    ["settings", "settings", "Настройки", "Settings"],
  ];

  return <main className="app-shell">
    <header className="topbar">
      <button type="button" className="brand" onClick={() => navigate("overview")} aria-label="TB Home"><span className="brand-mark">TB</span><span className="brand-copy"><strong>TB</strong><small>mini app</small></span></button>
      <button type="button" className="profile-button" onClick={() => navigate("settings")} aria-label={tx(language, "Профиль", "Profile")}><span className="profile-copy"><strong>{envelope.user.firstName || "Trader"}</strong><small>{settings.admin.available ? "Admin · Telegram" : "Telegram"}</small></span>{dirty ? <i className="unsaved-dot" title={tx(language, "Есть несохранённые изменения", "Unsaved changes")} /> : null}<span className="profile-avatar">{initials}</span></button>
    </header>

    <div className="content">{marketError && (tab === "overview" || tab === "fvg") ? <div className="market-warning"><span><Icon name="alert" size={16} />{tx(language, "24h market data временно недоступны для части инструментов", "24h market data is temporarily unavailable for some instruments")}</span><button type="button" onClick={() => void refreshMarket()}><Icon name="refresh" size={15} />{tx(language, "Повторить", "Retry")}</button></div> : null}{settingsError ? <div className="inline-error"><Icon name="alert" size={16} />{settingsError}</div> : null}{renderScreen()}</div>

    <nav className="bottom-nav" aria-label={tx(language, "Основная навигация", "Primary navigation")}>{navItems.map(([value, icon, ru, en]) => <button type="button" key={value} className={tab === value ? "active" : ""} aria-current={tab === value ? "page" : undefined} onClick={() => navigate(value)}><Icon name={icon} size={20} /><small>{tx(language, ru, en)}</small></button>)}</nav>

    {dirty ? <div className="save-bar visible"><div><span className="save-indicator"><Icon name="save" size={17} /></span><div><strong>{tx(language, "Есть изменения", "Unsaved changes")}</strong><small>{tx(language, "Сохраните, чтобы применить правила", "Save to apply the rules")}</small></div></div><button type="button" className="primary-button compact" disabled={saving} onClick={() => void save()}>{saving ? tx(language, "Сохранение…", "Saving…") : tx(language, "Сохранить", "Save")}</button></div> : null}
    {toast ? <div className="toast" role="status">{toast}</div> : null}
  </main>;
}
