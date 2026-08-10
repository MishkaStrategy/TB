import type { Language } from "./types";

const ENGLISH: Record<string, string> = {
  "Не удалось загрузить настройки": "Could not load settings",
  "Настройки сохранены": "Settings saved",
  "Не удалось сохранить настройки": "Could not save settings",
  "Загружаем настройки": "Loading settings",
  "Подготавливаем персональный интерфейс": "Preparing your personalized interface",
  "Настройки недоступны": "Settings are unavailable",
  "Откройте Mini App из Telegram-бота ещё раз.": "Open the Mini App from the Telegram bot again.",
  "Введите корректный инструмент, например ETHUSDT": "Enter a valid instrument, for example ETHUSDT",
  "Выберите хотя бы одно направление": "Select at least one direction",
  "Выберите хотя бы одну биржу": "Select at least one exchange",
  "Пред-FVG T−3": "Pre-FVG T−3",
  "Подтверждённые": "Confirmed",
  "Бычьи": "Bullish",
  "Медвежьи": "Bearish",
  "Центр управления": "Control center",
  "Настройки торговых сигналов": "Trading signal settings",
  "Все персональные фильтры собраны в одном месте. Бот продолжает отвечать за сигналы, статистику и рыночные данные.": "All personal filters are in one place. The bot continues to handle signals, statistics and market data.",
  "инструментов": "instruments",
  "бирж": "exchanges",
  "частота": "frequency",
  "Активен": "Active",
  "Пауза": "Paused",
  "15-минутные зоны, направления, инструменты и персональные фильтры.": "15-minute zones, directions, instruments and personal filters.",
  "Инструменты, биржи, таймфреймы, направления и персональные фильтры.": "Instruments, exchanges, timeframes, directions and personal filters.",
  "T−3 включён": "T−3 enabled",
  "Только подтверждённые": "Confirmed only",
  "Фандинг": "Funding",
  "Порог": "Threshold",
  "Порог, направления, периодичность и шесть фьючерсных бирж.": "Threshold, directions, frequency and six futures exchanges.",
  "Быстрые настройки": "Quick settings",
  "Самые часто используемые переключатели": "The most frequently used controls",
  "FVG-уведомления": "FVG alerts",
  "Главный переключатель модуля": "Main module switch",
  "Формат сообщений": "Message format",
  "Компактный или со всеми полями": "Compact or with all fields",
  "Кратко": "Compact",
  "Подробно": "Detailed",
  "Сводка всех действующих правил": "Summary of all active rules",
  "Открыть": "Open",
  "Персонализация": "Personalization",
  "Общие настройки": "General settings",
  "Интерфейс и формат уведомлений сохраняются отдельно для вашего Telegram ID.": "The interface and notification format are saved separately for your Telegram ID.",
  "Язык интерфейса": "Interface language",
  "Применяется к меню и сообщениям бота": "Applies to the bot menu and messages",
  "Русский": "Russian",
  "Формат уведомлений": "Notification format",
  "Выберите объём информации в каждом сигнале": "Choose how much information each signal contains",
  "Компактный": "Compact",
  "Инструмент, значение и статус. Быстро читается в потоке сообщений.": "Instrument, value and status. Easy to scan in a busy message feed.",
  "Подробный": "Detailed",
  "Все доступные поля сигнала, фильтров и рыночного состояния.": "All available signal, filter and market-state fields.",
  "Сводка": "Summary",
  "Активные уведомления": "Active notifications",
  "Быстрый обзор всех правил, которые сейчас применяет бот.": "A quick overview of all rules currently used by the bot.",
  "Единый формат для FVG и фандинга": "One format for FVG and funding",
  "Изменить": "Change",
  "Текущая конфигурация сигналов": "Current signal configuration",
  "Статус": "Status",
  "Инструменты": "Instruments",
  "Да": "Yes",
  "Нет": "No",
  "Включён": "Enabled",
  "Выключен": "Disabled",
  "Открыть настройки FVG": "Open FVG settings",
  "Текущие правила мультибиржевой рассылки": "Current multi-exchange notification rules",
  "Частота": "Frequency",
  "Направления": "Directions",
  "Биржи": "Exchanges",
  "Биржа": "Exchange",
  "Таймфреймы": "Timeframes",
  "Следующая проверка": "Next check",
  "Открыть настройки фандинга": "Open funding settings",
  "Оба направления": "Both directions",
  "Положительный": "Positive",
  "Отрицательный": "Negative",
  "Модуль сигналов": "Signal module",
  "Управляйте типами сигналов и точными фильтрами отдельно для каждого инструмента.": "Manage signal types and precise filters separately for each instrument.",
  "Основные параметры": "Core settings",
  "Главный статус и типы событий": "Main status and event types",
  "Главный статус подтверждённых FVG": "Main confirmed FVG status",
  "Модуль FVG": "FVG module",
  "Отключает все FVG-уведомления": "Disables all FVG notifications",
  "Подтверждённые FVG": "Confirmed FVG",
  "Сигнал после закрытия 15-минутной свечи": "Signal after the 15-minute candle closes",
  "Сигнал только после закрытия свечи C": "Signal only after candle C closes",
  "Предварительный сигнал до подтверждения зоны": "Preliminary signal before the zone is confirmed",
  "Можно оставить одно или оба направления": "Keep one or both directions enabled",
  "Бычьи зоны": "Bullish zones",
  "Импульс вверх": "Upward impulse",
  "Медвежьи зоны": "Bearish zones",
  "Импульс вниз": "Downward impulse",
  "Вкл": "On",
  "Выкл": "Off",
  "Например, ETHUSDT": "For example, ETHUSDT",
  "Добавить": "Add",
  "Добавьте первый инструмент для настройки фильтров.": "Add your first instrument to configure filters.",
  "Выберите источник рыночных данных": "Choose the market-data source",
  "Биржа, таймфреймы и персональные фильтры": "Exchange, timeframes and personal filters",
  "Персональные фильтры инструмента": "Personal instrument filters",
  "Инструмент активен": "Instrument enabled",
  "Учитывается при поиске FVG": "Included in FVG detection",
  "Учитывается при поиске подтверждённых FVG": "Included in confirmed FVG detection",
  "Источник закрытых 15m свечей": "Source of closed 15m candles",
  "15m источник; старшие интервалы агрегируются локально": "15m source; higher timeframes are aggregated locally",
  "💰 Фильтр цены": "💰 Price filter",
  "Диапазон цены сигнала": "Signal price range",
  "Минимальная цена": "Minimum price",
  "Без минимума": "No minimum",
  "Максимальная цена": "Maximum price",
  "Без максимума": "No maximum",
  "Применять к сигналам": "Apply to signals",
  "📏 Фильтр размера FVG": "📏 FVG size filter",
  "Минимальная ширина зоны": "Minimum zone width",
  "Минимальный размер": "Minimum size",
  "Единица": "Unit",
  "Мультибиржевой модуль": "Multi-exchange module",
  "Уведомления о фандинге": "Funding notifications",
  "Настройте момент отправки, порог ставки и рынки, которые нужно отслеживать.": "Configure delivery timing, rate threshold and the markets to monitor.",
  "Рассылка": "Notifications",
  "Общий снимок бирж обновляется каждые 15 минут": "The combined exchange snapshot updates every 15 minutes",
  "Уведомления приостановлены": "Notifications are paused",
  "Частота уведомлений": "Notification frequency",
  "Минимальный абсолютный процент": "Minimum absolute percentage",
  "Например, 0.3 — уведомлять при ставке ≥ 0.3% или ≤ −0.3%": "For example, 0.3 sends an alert at a rate ≥ 0.3% or ≤ −0.3%",
  "Направление ставки": "Rate direction",
  "Должно быть выбрано хотя бы одно направление": "At least one direction must be selected",
  "Ставка выше нуля": "Rate above zero",
  "Ставка ниже нуля": "Rate below zero",
  "Можно выбрать одну или несколько площадок": "Select one or more exchanges",
  "Поток данных": "Data feed",
  "WebSocket Bitunix и REST recovery": "Bitunix WebSocket and REST recovery",
  "Последняя свеча": "Latest candle",
  "Последняя ошибка": "Latest error",
  "Очередь и доставки": "Queue and deliveries",
  "Состояние постоянного Telegram outbox": "Persistent Telegram outbox status",
  "В outbox": "In outbox",
  "Успешно": "Delivered",
  "Ошибки": "Failures",
  "Повторы": "Retries",
  "Отклонено навсегда": "Permanent failures",
  "Хранилища": "Storage",
  "JSON-настройки": "JSON settings",
  "Ресурсы процесса": "Process resources",
  "Память, нагрузка и свободное место": "Memory, system load and free disk space",
  "Память": "Memory",
  "Свободно на диске": "Free disk space",
  "Версия": "Version",
  "Установленный релиз и runtime": "Installed release and runtime",
  "Релиз": "Release",
  "Подключён": "Connected",
  "Отключён": "Disconnected",
  "Исправно": "Healthy",
  "Требует внимания": "Needs attention",
  "Нет данных": "No data",
  "Защищённый раздел": "Protected section",
  "Администрирование": "Administration",
  "Раздел отображается только после серверной проверки административных прав.": "This section is shown only after the server verifies administrator rights.",
  "Нет доступа": "Access denied",
  "Эта панель доступна только администраторам проекта.": "This panel is available only to project administrators.",
  "Режим доступа": "Access mode",
  "Определяет, кто может пользоваться ботом": "Controls who can use the bot",
  "Публичный доступ": "Public access",
  "Приватный доступ": "Private access",
  "Команды доступны всем Telegram-пользователям": "Commands are available to all Telegram users",
  "Только allowlist и одобренные заявки": "Allowlist and approved requests only",
  "Список разрешённых пользователей пуст.": "The allowed-user list is empty.",
  "Опасные операции": "Dangerous operations",
  "Требуют отдельных endpoint и повторного подтверждения": "Require dedicated endpoints and an additional confirmation",
  "Создать backup": "Create backup",
  "Перезапустить бота": "Restart bot",
  "Кнопки намеренно заблокированы до реализации защищённых серверных операций.": "These buttons are intentionally disabled until protected server operations are implemented.",
  "Главная": "Home",
  "Общие": "General",
  "Админ": "Admin",
  "Демо-режим": "Demo mode",
  "Подключено к боту": "Connected to bot",
  "Есть несохранённые изменения": "You have unsaved changes",
  "Они применятся ко всем следующим уведомлениям": "They will apply to all future notifications",
  "Сохраняем…": "Saving…",
  "Сохранить": "Save",
  "Доступ к Mini App не разрешён.": "Access to the Mini App is not allowed.",
  "Нужно выбрать хотя бы одно направление фандинга.": "Select at least one funding direction.",
  "Нужно выбрать хотя бы одну биржу.": "Select at least one exchange.",
  "Минимальная цена не может быть выше максимальной.": "The minimum price cannot be greater than the maximum price.",
  "Значение должно быть числом.": "The value must be a number.",
  "Значение должно быть конечным неотрицательным числом.": "The value must be a finite non-negative number.",
  "FVG · Фандинг": "FVG · Funding"
};

const textState = new WeakMap<Text, { original: string; rendered: string }>();
const attributeState = new WeakMap<Element, Map<string, { original: string; rendered: string }>>();
const LOCALIZED_ATTRIBUTES = ["placeholder", "title", "aria-label"] as const;
let currentLanguage: Language = navigator.language.toLowerCase().startsWith("en") ? "en" : "ru";
let observer: MutationObserver | null = null;
let applying = false;
let scheduled = false;

function translateDate(text: string): string | null {
  const match = text.match(/^(\d{2})\.(\d{2})\.(\d{4}),?\s+(\d{2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, day, month, year, hour, minute, second] = match;
  const date = new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
  );
  return date.toLocaleString("en-US");
}

function translateCore(text: string): string {
  const exact = ENGLISH[text];
  if (exact) return exact;

  const fieldSuffix = text.match(/^(.*?)(\s+\([A-Za-z][^)]+\))$/);
  if (fieldSuffix) return `${translateCore(fieldSuffix[1])}${fieldSuffix[2]}`;

  const date = translateDate(text);
  if (date) return date;

  const bytes = text.match(/^(\d+(?:[.,]\d+)?)\s+(Б|КБ|МБ|ГБ|ТБ)$/);
  if (bytes) {
    const units: Record<string, string> = { Б: "B", КБ: "KB", МБ: "MB", ГБ: "GB", ТБ: "TB" };
    return `${bytes[1].replace(",", ".")} ${units[bytes[2]]}`;
  }

  const minutes = text.match(/^(\d+)\s+мин$/);
  if (minutes) return `${minutes[1]} min`;

  const hours = text.match(/^(\d+)\s+ч(?:\s+(\d+)\s+мин)?$/);
  if (hours) return hours[2] ? `${hours[1]} h ${hours[2]} min` : `${hours[1]} h`;

  const every = text.match(/^Каждые\s+(.+)$/);
  if (every) return `Every ${translateCore(every[1])}`;

  const nextCheck = text.match(/^Следующая проверка:\s+(.+)$/);
  if (nextCheck) return `Next check: ${translateCore(nextCheck[1])}`;

  const threshold = text.match(/^Порог\s+(.+)%$/);
  if (threshold) return `Threshold ${threshold[1]}%`;

  const language = text.match(/^Язык:\s+(Русский|English)$/);
  if (language) return `Language: ${language[1] === "Русский" ? "Russian" : "English"}`;

  const added = text.match(/^Добавлено\s+(\d+)\s+из\s+(\d+)$/);
  if (added) return `Added ${added[1]} of ${added[2]}`;

  const instrumentUsage = text.match(/^(\d+)\s+из\s+(\d+)\s+инструментов$/);
  if (instrumentUsage) return `${instrumentUsage[1]} of ${instrumentUsage[2]} instruments`;

  const exchangeCount = text.match(/^(\d+)\s+бирж$/);
  if (exchangeCount) return `${exchangeCount[1]} exchanges`;

  const remove = text.match(/^Удалить\s+(.+)$/);
  if (remove) return `Remove ${remove[1]}`;

  const limit = text.match(/^Достигнут лимит:\s+(\d+)\s+инструментов$/);
  if (limit) return `Limit reached: ${limit[1]} instruments`;

  const technicalLimit = text.match(/^Достигнут технический лимит:\s+(\d+)\s+инструментов\.\s+Удалите один инструмент, чтобы добавить новый\.$/);
  if (technicalLimit) return `Technical limit reached: ${technicalLimit[1]} instruments. Remove one instrument to add another.`;

  const allowedUsers = text.match(/^(\d+)\s+разрешённых пользователей$/);
  if (allowedUsers) return `${allowedUsers[1]} allowed users`;

  const overallStatus = text.match(/^Общий статус:\s+(.+)$/);
  if (overallStatus) return `Overall status: ${translateCore(overallStatus[1])}`;

  const total = text.match(/^из\s+(.+)$/);
  if (total) return `of ${translateCore(total[1])}`;

  return text;
}

export function translateUiText(value: string, language: Language): string {
  if (language === "ru" || !value.trim()) return value;
  const leading = value.match(/^\s*/)?.[0] ?? "";
  const trailing = value.match(/\s*$/)?.[0] ?? "";
  const end = Math.max(leading.length, value.length - trailing.length);
  const core = value.slice(leading.length, end).replace(/\s+/g, " ");
  return `${leading}${translateCore(core)}${trailing}`;
}

function localizeTextNode(node: Text): void {
  const current = node.nodeValue ?? "";
  let state = textState.get(node);
  if (!state || current !== state.rendered) {
    state = { original: current, rendered: current };
    textState.set(node, state);
  }
  const next = translateUiText(state.original, currentLanguage);
  state.rendered = next;
  if (current !== next) node.nodeValue = next;
}

function localizeAttribute(element: Element, name: string): void {
  const current = element.getAttribute(name);
  if (current === null) return;
  let attributes = attributeState.get(element);
  if (!attributes) {
    attributes = new Map();
    attributeState.set(element, attributes);
  }
  let state = attributes.get(name);
  if (!state || current !== state.rendered) {
    state = { original: current, rendered: current };
    attributes.set(name, state);
  }
  const next = translateUiText(state.original, currentLanguage);
  state.rendered = next;
  if (current !== next) element.setAttribute(name, next);
}

function markLanguageControls(root: ParentNode): void {
  const buttons = root.querySelectorAll<HTMLButtonElement>("button");
  buttons.forEach((button) => {
    const label = button.textContent?.trim();
    if (label === "Русский" || label === "Russian") button.dataset.uiLanguage = "ru";
    if (label === "English") button.dataset.uiLanguage = "en";
  });
}

function detectSelectedLanguage(root: ParentNode): Language | null {
  const active = root.querySelector<HTMLButtonElement>("button.active[data-ui-language]");
  const language = active?.dataset.uiLanguage;
  return language === "ru" || language === "en" ? language : null;
}

function localizeTree(root: Node): void {
  if (root.nodeType === Node.TEXT_NODE) {
    localizeTextNode(root as Text);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  if (root instanceof Element) {
    LOCALIZED_ATTRIBUTES.forEach((name) => localizeAttribute(root, name));
  }
  root.childNodes.forEach((child) => localizeTree(child));
}

function applyLocalization(): void {
  scheduled = false;
  if (applying || !document.body) return;
  applying = true;
  try {
    markLanguageControls(document.body);
    const selectedLanguage = detectSelectedLanguage(document.body);
    if (selectedLanguage) currentLanguage = selectedLanguage;
    document.documentElement.lang = currentLanguage;
    document.documentElement.dataset.language = currentLanguage;
    localizeTree(document.body);
  } finally {
    applying = false;
  }
}

function scheduleLocalization(): void {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(applyLocalization);
}

export function setUiLanguage(language: Language): void {
  currentLanguage = language;
  scheduleLocalization();
}

export function startUiLocalization(): () => void {
  if (observer) return () => undefined;

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest<HTMLButtonElement>("button[data-ui-language]");
    const language = button?.dataset.uiLanguage;
    if (language === "ru" || language === "en") setUiLanguage(language);
  }, true);

  observer = new MutationObserver(() => scheduleLocalization());
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["class", "placeholder", "title", "aria-label"],
  });
  scheduleLocalization();

  return () => {
    observer?.disconnect();
    observer = null;
  };
}
