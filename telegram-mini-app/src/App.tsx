import { useEffect, useMemo, useState } from "react";
import { loadSettings, saveSettings } from "./api";
import { impact, notify, setUnsavedChanges } from "./telegram";
import type {
  AdminDiagnostics,
  AppSettings,
  Exchange,
  FilterScope,
  FvgSizeUnit,
  FvgSymbolSettings,
  FvgTimeframe,
  SettingsEnvelope,
} from "./types";

const exchangeLabels: Record<Exchange, string> = {
  bitunix: "Bitunix",
  binance: "Binance",
  bybit: "Bybit",
  bingx: "BingX",
  bitget: "Bitget",
  gate: "Gate",
};

const exchangeOrder = Object.keys(exchangeLabels) as Exchange[];
const timeframeOrder: FvgTimeframe[] = ["15m", "1h", "4h", "1d"];
const defaultScope: FilterScope = {
  confirmedFvg: true,
  bullish: true,
  bearish: true,
};

const makeInstrumentKey = (exchange: Exchange, symbol: string) => (
  exchange === "bitunix" ? symbol : `${exchange}|${symbol}`
);

type Tab = "overview" | "general" | "notifications" | "fvg" | "funding" | "admin";
type PrimaryTab = "overview" | "fvg" | "funding";

type ToggleProps = {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
};

function Toggle({ checked, onChange, disabled = false }: ToggleProps) {
  return (
    <button
      type="button"
      className={`toggle ${checked ? "is-on" : ""}`}
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => {
        impact("light");
        onChange(!checked);
      }}
    >
      <span />
    </button>
  );
}

function Card({ title, description, children, accent }: {
  title: string;
  description?: string;
  children: React.ReactNode;
  accent?: string;
}) {
  return (
    <section
      className="card"
      style={accent ? { "--card-accent": accent } as React.CSSProperties : undefined}
    >
      <div className="card-heading">
        <div>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function SettingRow({ icon, title, description, children }: {
  icon: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="setting-row">
      <div className="setting-copy">
        <span className="setting-icon">{icon}</span>
        <div>
          <strong>{title}</strong>
          {description ? <small>{description}</small> : null}
        </div>
      </div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

function Segmented<T extends string>({ value, options, onChange }: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented">
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          className={value === option.value ? "active" : ""}
          onClick={() => {
            impact("light");
            onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function StatusPill({ active, children }: {
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className={`status-pill ${active ? "active" : "paused"}`}>
      {children}
    </span>
  );
}

function formatInterval(minutes: number): string {
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

function formatBytes(value: number): string {
  let amount = Math.max(0, Number(value) || 0);
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return index === 0 ? `${Math.round(amount)} ${units[index]}` : `${amount.toFixed(1)} ${units[index]}`;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU");
}

function statusText(value: string): string {
  const labels: Record<string, string> = {
    connected: "Подключён",
    disconnected: "Отключён",
    ok: "Исправно",
    warning: "Требует внимания",
    unknown: "Нет данных",
  };
  return labels[value] ?? value;
}

function Metric({ label, value, hint }: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}

function App() {
  const [envelope, setEnvelope] = useState<SettingsEnvelope | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [baseline, setBaseline] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [profileOpen, setProfileOpen] = useState(false);
  const [selectedInstrumentKey, setSelectedInstrumentKey] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newExchange, setNewExchange] = useState<Exchange>("bitunix");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    let active = true;
    loadSettings()
      .then((result) => {
        if (!active) return;
        setEnvelope(result);
        setSettings(result.settings);
        setBaseline(JSON.stringify(result.settings));
        setSelectedInstrumentKey(result.settings.fvg.symbols[0]?.key ?? "");
      })
      .catch((loadError: unknown) => {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить настройки");
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const dirty = useMemo(
    () => Boolean(settings && baseline && JSON.stringify(settings) !== baseline),
    [settings, baseline],
  );

  useEffect(() => setUnsavedChanges(dirty), [dirty]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const updateSettings = (updater: (current: AppSettings) => AppSettings) => {
    setSettings((current) => (current ? updater(current) : current));
  };

  const updateGeneral = (changes: Partial<AppSettings["general"]>) => {
    updateSettings((current) => ({
      ...current,
      general: { ...current.general, ...changes },
    }));
  };

  const updateFvg = (changes: Partial<AppSettings["fvg"]>) => {
    updateSettings((current) => ({
      ...current,
      fvg: { ...current.fvg, ...changes },
    }));
  };

  const updateFunding = (changes: Partial<AppSettings["funding"]>) => {
    updateSettings((current) => ({
      ...current,
      funding: { ...current.funding, ...changes },
    }));
  };

  const updateAdmin = (changes: Partial<AppSettings["admin"]>) => {
    updateSettings((current) => ({
      ...current,
      admin: { ...current.admin, ...changes },
    }));
  };

  const updateInstrument = (
    key: string,
    updater: (item: FvgSymbolSettings) => FvgSymbolSettings,
  ) => {
    updateSettings((current) => ({
      ...current,
      fvg: {
        ...current.fvg,
        symbols: current.fvg.symbols.map((item) => (
          item.key === key ? updater(item) : item
        )),
      },
    }));
  };

  const navigate = (next: Tab) => {
    setTab(next);
    setProfileOpen(false);
    impact("light");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const save = async () => {
    if (!settings || saving || !dirty) return;
    setSaving(true);
    setError("");
    try {
      const result = await saveSettings(settings);
      setEnvelope(result);
      setSettings(result.settings);
      setBaseline(JSON.stringify(result.settings));
      if (!result.settings.fvg.symbols.some((item) => item.key === selectedInstrumentKey)) {
        setSelectedInstrumentKey(result.settings.fvg.symbols[0]?.key ?? "");
      }
      setToast("Настройки сохранены");
      notify("success");
    } catch (saveError: unknown) {
      const message = saveError instanceof Error
        ? saveError.message
        : "Не удалось сохранить настройки";
      setError(message);
      notify("error");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <main className="state-screen">
        <div className="loader" />
        <strong>Загружаем настройки</strong>
        <span>Подготавливаем персональный интерфейс</span>
      </main>
    );
  }

  if (!settings || !envelope) {
    return (
      <main className="state-screen">
        <div className="state-icon">⚠️</div>
        <strong>Настройки недоступны</strong>
        <span>{error || "Откройте Mini App из Telegram-бота ещё раз."}</span>
      </main>
    );
  }

  const maxSymbols = envelope.limits?.maxFvgSymbols ?? 10;
  const atInstrumentLimit = settings.fvg.symbols.length >= maxSymbols;
  const selected = settings.fvg.symbols.find((item) => item.key === selectedInstrumentKey)
    ?? settings.fvg.symbols[0];

  const addInstrument = () => {
    const normalized = newSymbol.trim().toUpperCase().replace("/", "");
    if (!/^[A-Z0-9]{5,20}$/.test(normalized)) {
      setToast("Введите корректный инструмент, например ETHUSDT");
      notify("warning");
      return;
    }
    const key = makeInstrumentKey(newExchange, normalized);
    if (settings.fvg.symbols.some((item) => item.key === key)) {
      setSelectedInstrumentKey(key);
      setNewSymbol("");
      return;
    }
    if (atInstrumentLimit) {
      setToast(`Достигнут лимит: ${maxSymbols} инструментов`);
      notify("warning");
      return;
    }
    const instrument: FvgSymbolSettings = {
      key,
      exchange: newExchange,
      symbol: normalized,
      timeframes: ["15m"],
      enabled: true,
      priceFilter: {
        enabled: false,
        min: null,
        max: null,
        scope: { ...defaultScope },
      },
      sizeFilter: {
        enabled: false,
        unit: "USD",
        min: null,
        scope: { ...defaultScope },
      },
    };
    updateFvg({ symbols: [...settings.fvg.symbols, instrument] });
    setSelectedInstrumentKey(key);
    setNewSymbol("");
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
      setToast("Такой инструмент уже добавлен на выбранной бирже");
      notify("warning");
      return;
    }
    updateInstrument(instrument.key, (item) => ({ ...item, exchange, key: nextKey }));
    setSelectedInstrumentKey(nextKey);
    impact("medium");
  };

  const toggleTimeframe = (instrument: FvgSymbolSettings, timeframe: FvgTimeframe) => {
    const active = instrument.timeframes.includes(timeframe);
    if (active && instrument.timeframes.length === 1) {
      setToast("Выберите хотя бы один таймфрейм");
      notify("warning");
      return;
    }
    const selectedTimeframes = new Set(instrument.timeframes);
    if (active) selectedTimeframes.delete(timeframe);
    else selectedTimeframes.add(timeframe);
    updateInstrument(instrument.key, (item) => ({
      ...item,
      timeframes: timeframeOrder.filter((value) => selectedTimeframes.has(value)),
    }));
    impact("light");
  };

  const toggleFundingDirection = (key: "notifyPositive" | "notifyNegative") => {
    const next = { ...settings.funding, [key]: !settings.funding[key] };
    if (!next.notifyPositive && !next.notifyNegative) {
      setToast("Выберите хотя бы одно направление");
      notify("warning");
      return;
    }
    updateFunding({ [key]: next[key] });
  };

  const toggleExchange = (exchange: Exchange) => {
    const selectedExchanges = new Set(settings.funding.exchanges);
    if (selectedExchanges.has(exchange)) {
      if (selectedExchanges.size === 1) {
        setToast("Выберите хотя бы одну биржу");
        notify("warning");
        return;
      }
      selectedExchanges.delete(exchange);
    } else {
      selectedExchanges.add(exchange);
    }
    updateFunding({
      exchanges: exchangeOrder.filter((item) => selectedExchanges.has(item)),
    });
    impact("light");
  };

  const renderScope = (
    scope: FilterScope,
    onChange: (scope: FilterScope) => void,
  ) => (
    <div className="scope-grid">
      {([
        ["confirmedFvg", "Подтверждённые"],
        ["bullish", "Бычьи"],
        ["bearish", "Медвежьи"],
      ] as Array<[keyof FilterScope, string]>).map(([key, label]) => (
        <button
          type="button"
          key={key}
          className={scope[key] ? "scope-chip active" : "scope-chip"}
          onClick={() => onChange({ ...scope, [key]: !scope[key] })}
        >
          <span>{scope[key] ? "✓" : ""}</span>{label}
        </button>
      ))}
    </div>
  );

  const renderOverview = () => (
    <div className="screen-stack">
      <section className="dashboard-hero">
        <div className="dashboard-copy">
          <span className="eyebrow">Центр управления</span>
          <h1>Настройки торговых сигналов</h1>
          <p>Все персональные фильтры собраны в одном месте. Бот продолжает отвечать за сигналы, статистику и рыночные данные.</p>
        </div>
        <div className="dashboard-status-grid">
          <div className="dashboard-stat">
            <span>FVG</span>
            <strong>{settings.fvg.enabled ? "Включён" : "Выключен"}</strong>
            <small>{settings.fvg.symbols.length} / {maxSymbols}</small>
          </div>
          <div className="dashboard-stat">
            <span>Фандинг</span>
            <strong>{settings.funding.enabled ? "Включён" : "Выключен"}</strong>
            <small>{settings.funding.exchanges.length} бирж</small>
          </div>
          <div className="dashboard-stat">
            <span>Формат сообщений</span>
            <strong>{settings.general.messageMode === "compact" ? "Компактный" : "Подробный"}</strong>
            <small>{settings.general.language === "ru" ? "Русский" : "English"}</small>
          </div>
        </div>
      </section>

      <div className="module-grid">
        <button type="button" className="module-card fvg" onClick={() => navigate("fvg")}>
          <div className="module-top">
            <span>◫</span>
            <StatusPill active={settings.fvg.enabled}>{settings.fvg.enabled ? "Активен" : "Пауза"}</StatusPill>
          </div>
          <h3>Fair Value Gap</h3>
          <p>Инструменты, биржи, таймфреймы, направления и персональные фильтры.</p>
          <div className="module-footer"><span>{settings.fvg.symbols.length} из {maxSymbols} инструментов</span><b>→</b></div>
        </button>
        <button type="button" className="module-card funding" onClick={() => navigate("funding")}>
          <div className="module-top">
            <span>≋</span>
            <StatusPill active={settings.funding.enabled}>{settings.funding.enabled ? "Активен" : "Пауза"}</StatusPill>
          </div>
          <h3>Фандинг</h3>
          <p>Порог, направления, периодичность и шесть фьючерсных бирж.</p>
          <div className="module-footer"><span>Порог {settings.funding.threshold}%</span><b>→</b></div>
        </button>
      </div>

      <Card title="Быстрые настройки" description="Самые часто используемые переключатели">
        <SettingRow icon="🔔" title="FVG-уведомления" description="Главный переключатель модуля">
          <Toggle checked={settings.fvg.enabled} onChange={(enabled) => updateFvg({ enabled })} />
        </SettingRow>
        <SettingRow icon="💸" title="Funding alerts" description={`Каждые ${formatInterval(settings.funding.intervalMinutes)}`}>
          <Toggle checked={settings.funding.enabled} onChange={(enabled) => updateFunding({ enabled })} />
        </SettingRow>
        <SettingRow icon="📱" title="Формат сообщений" description="Компактный или со всеми полями">
          <Segmented
            value={settings.general.messageMode}
            options={[
              { value: "compact", label: "Кратко" },
              { value: "detailed", label: "Подробно" },
            ]}
            onChange={(messageMode) => updateGeneral({ messageMode })}
          />
        </SettingRow>
        <SettingRow icon="🔎" title="Активные уведомления" description="Сводка всех действующих правил">
          <button type="button" className="text-button" onClick={() => navigate("notifications")}>Открыть</button>
        </SettingRow>
      </Card>
    </div>
  );

  const renderGeneral = () => (
    <div className="screen-stack">
      <div className="page-title">
        <span>Персонализация</span>
        <h1>Общие настройки</h1>
        <p>Интерфейс и формат уведомлений сохраняются отдельно для вашего Telegram ID.</p>
      </div>
      <Card title="Язык интерфейса" description="Применяется к меню и сообщениям бота">
        <Segmented
          value={settings.general.language}
          options={[
            { value: "ru", label: "Русский" },
            { value: "en", label: "English" },
          ]}
          onChange={(language) => updateGeneral({ language })}
        />
      </Card>
      <Card title="Формат уведомлений" description="Выберите объём информации в каждом сигнале">
        <div className="choice-cards">
          <button type="button" className={settings.general.messageMode === "compact" ? "choice active" : "choice"} onClick={() => updateGeneral({ messageMode: "compact" })}>
            <span className="choice-icon">⚡</span>
            <strong>Компактный</strong>
            <small>Инструмент, значение и статус. Быстро читается в потоке сообщений.</small>
          </button>
          <button type="button" className={settings.general.messageMode === "detailed" ? "choice active" : "choice"} onClick={() => updateGeneral({ messageMode: "detailed" })}>
            <span className="choice-icon">▤</span>
            <strong>Подробный</strong>
            <small>Все доступные поля сигнала, фильтров и рыночного состояния.</small>
          </button>
        </div>
      </Card>
    </div>
  );

  const renderNotifications = () => {
    const fundingDirection = settings.funding.notifyPositive && settings.funding.notifyNegative
      ? "Оба направления"
      : settings.funding.notifyPositive
        ? "Положительный"
        : "Отрицательный";
    const timeframeCount = new Set(settings.fvg.symbols.flatMap((item) => item.timeframes)).size;
    return (
      <div className="screen-stack">
        <div className="page-title">
          <span>Сводка</span>
          <h1>Активные уведомления</h1>
          <p>Быстрый обзор всех правил, которые сейчас применяет бот.</p>
        </div>
        <Card title="Формат сообщений" description="Единый формат для FVG и фандинга">
          <SettingRow icon="📱" title={settings.general.messageMode === "compact" ? "Компактный" : "Подробный"} description={`Язык: ${settings.general.language === "ru" ? "Русский" : "English"}`}>
            <button type="button" className="text-button" onClick={() => navigate("general")}>Изменить</button>
          </SettingRow>
        </Card>
        <Card title="Fair Value Gap" description="Текущая конфигурация подтверждённых сигналов" accent="#23d5ab">
          <div className="diagnostic-grid">
            <Metric label="Статус" value={settings.fvg.enabled ? "Включён" : "Выключен"} />
            <Metric label="Инструменты" value={settings.fvg.symbols.length} />
            <Metric label="Таймфреймы" value={timeframeCount} />
            <Metric label="Подтверждённые" value={settings.fvg.notifyConfirmedFvg ? "Да" : "Нет"} />
            <Metric label="Бычьи" value={settings.fvg.bullishEnabled ? "Да" : "Нет"} />
            <Metric label="Медвежьи" value={settings.fvg.bearishEnabled ? "Да" : "Нет"} />
          </div>
          <button type="button" className="text-button" onClick={() => navigate("fvg")}>Открыть настройки FVG</button>
        </Card>
        <Card title="Фандинг" description="Текущие правила мультибиржевой рассылки" accent="#ffb545">
          <div className="diagnostic-grid">
            <Metric label="Статус" value={settings.funding.enabled ? "Включён" : "Выключен"} />
            <Metric label="Частота" value={formatInterval(settings.funding.intervalMinutes)} />
            <Metric label="Порог" value={`${settings.funding.threshold}%`} />
            <Metric label="Направления" value={fundingDirection} />
            <Metric label="Биржи" value={settings.funding.exchanges.length} hint={settings.funding.exchanges.map((item) => exchangeLabels[item]).join(", ")} />
            <Metric label="Следующая проверка" value={formatDate(settings.funding.nextCheckAt)} />
          </div>
          <button type="button" className="text-button" onClick={() => navigate("funding")}>Открыть настройки фандинга</button>
        </Card>
      </div>
    );
  };

  const renderFvg = () => (
    <div className="screen-stack">
      <div className="page-title">
        <span>Модуль сигналов</span>
        <h1>Fair Value Gap</h1>
        <p>Биржевые данные берутся из закрытых 15m свечей; 1h/4h/1d строятся локально по UTC-границам.</p>
      </div>
      <Card title="Основные параметры" description="Главный статус подтверждённых FVG" accent="#23d5ab">
        <SettingRow icon="◉" title="Модуль FVG" description="Отключает все FVG-уведомления">
          <Toggle checked={settings.fvg.enabled} onChange={(enabled) => updateFvg({ enabled })} />
        </SettingRow>
        <SettingRow icon="✓" title="Подтверждённые FVG" description="Сигнал только после закрытия свечи C">
          <Toggle checked={settings.fvg.notifyConfirmedFvg} onChange={(notifyConfirmedFvg) => updateFvg({ notifyConfirmedFvg })} />
        </SettingRow>
      </Card>
      <Card title="Направления" description="Можно оставить одно или оба направления">
        <div className="direction-grid">
          <button type="button" className={settings.fvg.bullishEnabled ? "direction-card active" : "direction-card"} onClick={() => updateFvg({ bullishEnabled: !settings.fvg.bullishEnabled })}>
            <span>🐮</span><div><strong>Бычьи зоны</strong><small>Импульс вверх</small></div><i>{settings.fvg.bullishEnabled ? "Вкл" : "Выкл"}</i>
          </button>
          <button type="button" className={settings.fvg.bearishEnabled ? "direction-card active" : "direction-card"} onClick={() => updateFvg({ bearishEnabled: !settings.fvg.bearishEnabled })}>
            <span>🐻</span><div><strong>Медвежьи зоны</strong><small>Импульс вниз</small></div><i>{settings.fvg.bearishEnabled ? "Вкл" : "Выкл"}</i>
          </button>
        </div>
      </Card>
      <Card title="Инструменты" description={`Добавлено ${settings.fvg.symbols.length} из ${maxSymbols}`}>
        <div className="instrument-limit">
          <div><span>Инструменты</span><strong>{settings.fvg.symbols.length} / {maxSymbols}</strong></div>
          <div className="instrument-limit-track"><span style={{ width: `${Math.min(100, (settings.fvg.symbols.length / Math.max(1, maxSymbols)) * 100)}%` }} /></div>
        </div>

        {!atInstrumentLimit ? (
          <div className="add-instrument-block">
            <div className="filter-header"><div><strong>Биржа</strong><small>Выберите источник рыночных данных</small></div></div>
            <div className="exchange-grid compact-exchanges">
              {exchangeOrder.map((exchange) => (
                <button type="button" key={exchange} className={newExchange === exchange ? "exchange-card active" : "exchange-card"} onClick={() => setNewExchange(exchange)}>
                  <span>{exchangeLabels[exchange].slice(0, 1)}</span><strong>{exchangeLabels[exchange]}</strong><i>{newExchange === exchange ? "✓" : ""}</i>
                </button>
              ))}
            </div>
            <div className="symbol-add">
              <input value={newSymbol} onChange={(event) => setNewSymbol(event.target.value.toUpperCase())} onKeyDown={(event) => event.key === "Enter" && addInstrument()} placeholder="Например, ETHUSDT" maxLength={20} />
              <button type="button" onClick={addInstrument}>Добавить</button>
            </div>
          </div>
        ) : (
          <div className="limit-notice">Достигнут технический лимит: {maxSymbols} инструментов. Удалите один инструмент, чтобы добавить новый.</div>
        )}

        {settings.fvg.symbols.length ? (
          <div className="instrument-list">
            {settings.fvg.symbols.map((item) => (
              <button type="button" key={item.key} className={selected?.key === item.key ? "instrument-item active" : "instrument-item"} onClick={() => setSelectedInstrumentKey(item.key)}>
                <span className={item.enabled ? "dot active" : "dot"} />
                <div>
                  <strong>{item.symbol}</strong>
                  <small>{exchangeLabels[item.exchange]} · {item.timeframes.join(" · ")}</small>
                </div>
                <b>›</b>
              </button>
            ))}
          </div>
        ) : <div className="empty-state">Добавьте первый инструмент для настройки фильтров.</div>}
      </Card>

      {selected ? (
        <Card title={`${selected.symbol} · ${exchangeLabels[selected.exchange]}`} description="Биржа, таймфреймы и персональные фильтры" accent="#5d7cff">
          <SettingRow icon="◫" title="Инструмент активен" description="Учитывается при поиске подтверждённых FVG">
            <Toggle checked={selected.enabled} onChange={(enabled) => updateInstrument(selected.key, (item) => ({ ...item, enabled }))} />
          </SettingRow>

          <div className="filter-panel">
            <div className="filter-header"><div><strong>Биржа</strong><small>Источник закрытых 15m свечей</small></div></div>
            <div className="exchange-grid">
              {exchangeOrder.map((exchange) => (
                <button type="button" key={exchange} className={selected.exchange === exchange ? "exchange-card active" : "exchange-card"} onClick={() => changeInstrumentExchange(selected, exchange)}>
                  <span>{exchangeLabels[exchange].slice(0, 1)}</span><strong>{exchangeLabels[exchange]}</strong><i>{selected.exchange === exchange ? "✓" : ""}</i>
                </button>
              ))}
            </div>
          </div>

          <div className="filter-panel">
            <div className="filter-header"><div><strong>Таймфреймы</strong><small>15m источник; старшие интервалы агрегируются локально</small></div></div>
            <div className="scope-grid timeframe-grid">
              {timeframeOrder.map((timeframe) => {
                const active = selected.timeframes.includes(timeframe);
                return (
                  <button type="button" key={timeframe} className={active ? "scope-chip active" : "scope-chip"} onClick={() => toggleTimeframe(selected, timeframe)}>
                    <span>{active ? "✓" : ""}</span>{timeframe}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="filter-panel">
            <div className="filter-header">
              <div><strong>💰 Фильтр цены</strong><small>Диапазон цены сигнала</small></div>
              <Toggle checked={selected.priceFilter.enabled} onChange={(enabled) => updateInstrument(selected.key, (item) => ({ ...item, priceFilter: { ...item.priceFilter, enabled } }))} />
            </div>
            <div className="field-grid two">
              <label><span>Минимальная цена</span><input inputMode="decimal" value={selected.priceFilter.min ?? ""} onChange={(event) => updateInstrument(selected.key, (item) => ({ ...item, priceFilter: { ...item.priceFilter, min: event.target.value || null } }))} placeholder="Без минимума" /></label>
              <label><span>Максимальная цена</span><input inputMode="decimal" value={selected.priceFilter.max ?? ""} onChange={(event) => updateInstrument(selected.key, (item) => ({ ...item, priceFilter: { ...item.priceFilter, max: event.target.value || null } }))} placeholder="Без максимума" /></label>
            </div>
            <span className="sub-label">Применять к сигналам</span>
            {renderScope(selected.priceFilter.scope, (scope) => updateInstrument(selected.key, (item) => ({ ...item, priceFilter: { ...item.priceFilter, scope } })))}
          </div>

          <div className="filter-panel">
            <div className="filter-header">
              <div><strong>📏 Фильтр размера FVG</strong><small>Минимальная ширина зоны</small></div>
              <Toggle checked={selected.sizeFilter.enabled} onChange={(enabled) => updateInstrument(selected.key, (item) => ({ ...item, sizeFilter: { ...item.sizeFilter, enabled } }))} />
            </div>
            <div className="field-grid size-fields">
              <label><span>Минимальный размер</span><input inputMode="decimal" value={selected.sizeFilter.min ?? ""} onChange={(event) => updateInstrument(selected.key, (item) => ({ ...item, sizeFilter: { ...item.sizeFilter, min: event.target.value || null } }))} placeholder="0" /></label>
              <label><span>Единица</span><Segmented<FvgSizeUnit> value={selected.sizeFilter.unit} options={[{ value: "USD", label: "$" }, { value: "PERCENT", label: "%" }]} onChange={(unit) => updateInstrument(selected.key, (item) => ({ ...item, sizeFilter: { ...item.sizeFilter, unit } }))} /></label>
            </div>
            <span className="sub-label">Применять к сигналам</span>
            {renderScope(selected.sizeFilter.scope, (scope) => updateInstrument(selected.key, (item) => ({ ...item, sizeFilter: { ...item.sizeFilter, scope } })))}
          </div>

          <button type="button" className="danger-button" onClick={() => removeInstrument(selected.key)}>Удалить {selected.symbol} · {exchangeLabels[selected.exchange]}</button>
        </Card>
      ) : null}
    </div>
  );

  const renderFunding = () => (
    <div className="screen-stack">
      <div className="page-title">
        <span>Мультибиржевой модуль</span>
        <h1>Уведомления о фандинге</h1>
        <p>Настройте момент отправки, порог ставки и рынки, которые нужно отслеживать.</p>
      </div>
      <Card title="Рассылка" description="Общий снимок бирж обновляется каждые 15 минут" accent="#ffb545">
        <SettingRow icon="🔔" title="Funding alerts" description={settings.funding.enabled ? `Следующая проверка: ${formatDate(settings.funding.nextCheckAt)}` : "Уведомления приостановлены"}>
          <Toggle checked={settings.funding.enabled} onChange={(enabled) => updateFunding({ enabled })} />
        </SettingRow>
        <div className="range-block">
          <div className="range-copy"><strong>Частота уведомлений</strong><span>{formatInterval(settings.funding.intervalMinutes)}</span></div>
          <input type="range" min={15} max={2880} step={15} value={settings.funding.intervalMinutes} onChange={(event) => updateFunding({ intervalMinutes: Number(event.target.value) })} />
          <div className="range-labels"><span>15 мин</span><span>24 ч</span><span>48 ч</span></div>
        </div>
        <label className="single-field">
          <span>Минимальный абсолютный процент</span>
          <div className="input-suffix"><input inputMode="decimal" value={settings.funding.threshold} onChange={(event) => updateFunding({ threshold: event.target.value.replace(",", ".") })} /><b>%</b></div>
          <small>Например, 0.3 — уведомлять при ставке ≥ 0.3% или ≤ −0.3%</small>
        </label>
      </Card>
      <Card title="Направление ставки" description="Должно быть выбрано хотя бы одно направление">
        <div className="direction-grid">
          <button type="button" className={settings.funding.notifyPositive ? "direction-card positive active" : "direction-card positive"} onClick={() => toggleFundingDirection("notifyPositive")}><span>↗</span><div><strong>Положительный</strong><small>Ставка выше нуля</small></div><i>{settings.funding.notifyPositive ? "Вкл" : "Выкл"}</i></button>
          <button type="button" className={settings.funding.notifyNegative ? "direction-card negative active" : "direction-card negative"} onClick={() => toggleFundingDirection("notifyNegative")}><span>↘</span><div><strong>Отрицательный</strong><small>Ставка ниже нуля</small></div><i>{settings.funding.notifyNegative ? "Вкл" : "Выкл"}</i></button>
        </div>
      </Card>
      <Card title="Биржи" description="Можно выбрать одну или несколько площадок">
        <div className="exchange-grid">
          {exchangeOrder.map((exchange) => {
            const active = settings.funding.exchanges.includes(exchange);
            return (
              <button type="button" key={exchange} className={active ? "exchange-card active" : "exchange-card"} onClick={() => toggleExchange(exchange)}>
                <span>{exchangeLabels[exchange].slice(0, 1)}</span><strong>{exchangeLabels[exchange]}</strong><i>{active ? "✓" : ""}</i>
              </button>
            );
          })}
        </div>
      </Card>
    </div>
  );

  const renderAdminDiagnostics = (diagnostics: AdminDiagnostics) => (
    <>
      <Card title="Поток данных" description="FVG stream и REST recovery" accent="#5d7cff">
        <div className="diagnostic-grid">
          <Metric label="WebSocket" value={statusText(diagnostics.websocket)} />
          <Metric label="Последняя свеча" value={formatDate(diagnostics.lastWebsocketMessage)} />
          <Metric label="REST recovery" value={formatDate(diagnostics.lastRestRecovery)} />
          <Metric label="Последняя ошибка" value={diagnostics.lastError || "—"} />
        </div>
      </Card>
      <Card title="Очередь и доставки" description="Состояние постоянного Telegram outbox">
        <div className="diagnostic-grid">
          <Metric label="В outbox" value={diagnostics.outbox} />
          <Metric label="Успешно" value={diagnostics.deliveries} />
          <Metric label="Ошибки" value={diagnostics.deliveryFailures} />
          <Metric label="Повторы" value={diagnostics.deliveryRetries} />
          <Metric label="Отклонено навсегда" value={diagnostics.deliveryPermanentFailures} />
        </div>
      </Card>
      <Card title="Хранилища" description={`Общий статус: ${statusText(diagnostics.databases)}`}>
        <div className="diagnostic-grid">
          <Metric label="FVG SQLite" value={statusText(diagnostics.fvgDatabaseStatus)} hint={formatBytes(diagnostics.fvgDatabaseBytes)} />
          <Metric label="Funding SQLite" value={statusText(diagnostics.fundingDatabaseStatus)} hint={formatBytes(diagnostics.fundingDatabaseBytes)} />
          <Metric label="JSON-настройки" value={formatBytes(diagnostics.jsonSettingsBytes)} />
        </div>
      </Card>
      <Card title="Ресурсы процесса" description="Память, нагрузка и свободное место">
        <div className="diagnostic-grid">
          <Metric label="Память" value={formatBytes(diagnostics.processMemoryBytes)} />
          <Metric label="Load average 1/5/15" value={diagnostics.loadAverage?.join(" / ") || "—"} />
          <Metric label="Свободно на диске" value={formatBytes(diagnostics.diskFreeBytes)} hint={`из ${formatBytes(diagnostics.diskTotalBytes)}`} />
          <Metric label="PID" value={diagnostics.pid || "—"} />
        </div>
      </Card>
      <Card title="Версия" description="Установленный релиз и runtime">
        <div className="diagnostic-grid">
          <Metric label="Релиз" value={diagnostics.release} />
          <Metric label="Git commit" value={diagnostics.gitCommit} />
          <Metric label="Python" value={diagnostics.pythonVersion} />
        </div>
      </Card>
    </>
  );

  const renderAdmin = () => (
    <div className="screen-stack">
      <div className="page-title">
        <span>Защищённый раздел</span>
        <h1>Администрирование</h1>
        <p>Раздел отображается только после серверной проверки административных прав.</p>
      </div>
      {!settings.admin.available ? (
        <Card title="Нет доступа"><div className="empty-state">Эта панель доступна только администраторам проекта.</div></Card>
      ) : (
        <>
          <Card title="Режим доступа" description="Определяет, кто может пользоваться ботом" accent="#b881ff">
            <SettingRow icon={settings.admin.publicAccessEnabled ? "🌐" : "🔐"} title={settings.admin.publicAccessEnabled ? "Публичный доступ" : "Приватный доступ"} description={settings.admin.publicAccessEnabled ? "Команды доступны всем Telegram-пользователям" : "Только allowlist и одобренные заявки"}>
              <Toggle checked={settings.admin.publicAccessEnabled} onChange={(publicAccessEnabled) => updateAdmin({ publicAccessEnabled })} />
            </SettingRow>
          </Card>
          <Card title="Allowlist" description={`${settings.admin.allowedUsers.length} разрешённых пользователей`}>
            {settings.admin.allowedUsers.length ? (
              <div className="user-list">
                {settings.admin.allowedUsers.map((user) => (
                  <div className="user-row" key={user.telegramId}>
                    <span>{user.name.slice(0, 1).toUpperCase()}</span>
                    <div><strong>{user.name}</strong><small>{user.telegramId}{user.username ? ` · @${user.username}` : ""}</small></div>
                    <i>{user.source}</i>
                  </div>
                ))}
              </div>
            ) : <div className="empty-state">Список разрешённых пользователей пуст.</div>}
          </Card>
          {renderAdminDiagnostics(settings.admin.diagnostics)}
          <Card title="Опасные операции" description="Серверные действия остаются fail-closed до production wiring">
            <div className="admin-actions">
              <button type="button" disabled>Создать backup</button>
              <button type="button" className="danger" disabled>Перезапустить бота</button>
            </div>
            <p className="integration-note">Общий settings PUT не выполняет административные операции.</p>
          </Card>
        </>
      )}
    </div>
  );

  const content = tab === "overview" ? renderOverview()
    : tab === "general" ? renderGeneral()
      : tab === "notifications" ? renderNotifications()
        : tab === "fvg" ? renderFvg()
          : tab === "funding" ? renderFunding()
            : renderAdmin();

  const primaryNavItems: Array<[PrimaryTab, string, string]> = [
    ["overview", "⌂", "Главная"],
    ["fvg", "◫", "FVG"],
    ["funding", "≋", "Фандинг"],
  ];

  const secondaryTitle = tab === "general"
    ? "Общие настройки"
    : tab === "notifications"
      ? "Сводка"
      : tab === "admin"
        ? "Администрирование"
        : "";
  const secondary = Boolean(secondaryTitle);

  return (
    <div className="app-shell">
      <header className="topbar">
        {secondary ? (
          <button type="button" className="top-back" onClick={() => navigate("overview")} aria-label="Главная">
            <span>←</span><div><strong>{secondaryTitle}</strong><small>Главная</small></div>
          </button>
        ) : (
          <div className="brand">
            <span className="brand-mark">T</span>
            <div><strong>TB Settings</strong><small>{envelope.source === "mock" ? "Демо-режим" : "Подключено к боту"}</small></div>
          </div>
        )}
        <button type="button" className="profile-trigger" onClick={() => { setProfileOpen((value) => !value); impact("light"); }} aria-expanded={profileOpen}>
          <span>{envelope.user.firstName.slice(0, 1).toUpperCase()}</span>
          <div><strong>{envelope.user.firstName}</strong>{envelope.user.username ? <small>@{envelope.user.username}</small> : null}</div>
          <b>⌄</b>
        </button>
      </header>

      {profileOpen ? (
        <>
          <button type="button" className="profile-backdrop" aria-label="Главная" onClick={() => setProfileOpen(false)} />
          <aside className="profile-sheet" role="dialog" aria-modal="true">
            <div className="profile-sheet-header">
              <span>{envelope.user.firstName.slice(0, 1).toUpperCase()}</span>
              <div><strong>{envelope.user.firstName}</strong>{envelope.user.username ? <small>@{envelope.user.username}</small> : null}</div>
            </div>
            <div className="profile-menu">
              <button type="button" onClick={() => navigate("general")} className={tab === "general" ? "active" : ""}>
                <span>⚙</span><div><strong>Общие настройки</strong><small>{settings.general.language === "ru" ? "Русский" : "English"} · {settings.general.messageMode === "compact" ? "Компактный" : "Подробный"}</small></div><b>›</b>
              </button>
              <button type="button" onClick={() => navigate("notifications")} className={tab === "notifications" ? "active" : ""}>
                <span>🔔</span><div><strong>Активные уведомления</strong><small>FVG · Фандинг</small></div><b>›</b>
              </button>
              {settings.admin.available ? (
                <button type="button" onClick={() => navigate("admin")} className={tab === "admin" ? "active" : ""}>
                  <span>◇</span><div><strong>Администрирование</strong><small>{settings.admin.publicAccessEnabled ? "Публичный доступ" : "Приватный доступ"}</small></div><b>›</b>
                </button>
              ) : null}
            </div>
          </aside>
        </>
      ) : null}

      <main className="content">{content}</main>

      {error ? <div className="error-banner">{error}<button type="button" onClick={() => setError("")}>×</button></div> : null}
      {toast ? <div className="toast">{toast}</div> : null}

      <div className={`save-bar ${dirty ? "visible" : ""}`}>
        <div><span className="save-dot" /><div><strong>Есть несохранённые изменения</strong><small>Они применятся ко всем следующим уведомлениям</small></div></div>
        <button type="button" onClick={save} disabled={saving}>{saving ? "Сохраняем…" : "Сохранить"}</button>
      </div>

      <nav className="bottom-nav" aria-label="Главная">
        {primaryNavItems.map(([value, icon, label]) => (
          <button type="button" key={value} className={tab === value ? "active" : ""} onClick={() => navigate(value)}>
            <span>{icon}</span><small>{label}</small>
          </button>
        ))}
      </nav>
    </div>
  );
}

export default App;
