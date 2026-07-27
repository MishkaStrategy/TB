"""Runtime Russian/English localization and notification formatting."""

from __future__ import annotations

import re
from contextvars import ContextVar

CURRENT_CHAT_ID: ContextVar[int | None] = ContextVar("current_chat_id", default=None)


def set_current_chat_id(chat_id: int | None) -> None:
    CURRENT_CHAT_ID.set(chat_id)


BUTTONS = {
    "💸 Фандинг": "💸 Funding", "🔔 Уведомления": "🔔 Alerts",
    "📊 Статистика": "📊 Statistics", "⚙️ Настройки": "⚙️ Settings",
    "❤️ Донат": "❤️ Donate", "🔔 Настройки FVG 15м": "🔔 FVG 15m settings",
    "🔕 Настройки FVG 15м": "🔕 FVG 15m settings", "📊 Статистика FVG": "📊 FVG statistics",
    "Модуль FVG": "FVG module", "Подтверждённые": "Confirmed",
    "Пред-FVG T−3": "Pre-FVG T−3", "🐮 Бычьи": "🐮 Bullish", "🐻 Медвежьи": "🐻 Bearish",
    "➕ Инструменты": "➕ Instruments", "Цена": "Price", "📏 Размер FVG": "📏 FVG size",
    "Положительный": "Positive", "Отрицательный": "Negative", "📈 Топ ставок": "📈 Top rates",
    "🔎 Проверка фандинга": "🔎 Funding check", "🔎 Проверить другой": "🔎 Check another",
    "🔄 Показать актуальные": "🔄 Refresh", "⬅️ Главное меню": "⬅️ Main menu",
    "⬅️ Настройки": "⬅️ Settings", "7 дней": "7 days", "30 дней": "30 days",
    "Всё время": "All time", "Русский": "Russian", "Английский": "English",
    "Компактные": "Compact", "Подробные": "Detailed", "📉 Настройки FVG": "📉 FVG settings",
    "🔔 Уведомления о фандинге": "🔔 Funding alerts", "🛠 Админ-настройки": "🛠 Admin settings",
    "👥 Разрешённые пользователи": "👥 Allowed users", "📡 WebSocket": "📡 WebSocket",
    "📨 Очередь уведомлений": "📨 Notification queue", "🗄 Базы данных": "🗄 Databases",
    "🖥 Память и нагрузка": "🖥 Memory and load", "💾 Резервная копия": "💾 Backup",
    "🏷 Версия релиза": "🏷 Release version", "♻️ Перезапустить бота": "♻️ Restart bot",
    "✅ Да, перезапустить": "✅ Yes, restart", "❌ Отмена": "❌ Cancel",
    "🌐 Доступ: публичный": "🌐 Access: public", "🔐 Доступ: приватный": "🔐 Access: private",
}

PHRASES = {
    "Доступ к боту не разрешён.": "Access to this bot is not allowed.",
    "Эта панель доступна только администраторам.": "This panel is available to administrators only.",
    "Главное меню закреплено на клавиатуре ниже.": "The main menu is pinned below the message field.",
    "Панель управления:": "Control panel:", "Панель управления FVG:": "FVG control panel:",
    "Настройки применяются отдельно для твоего Telegram ID.": "Settings are applied separately to your Telegram ID.",
    "🤖 FVG Alert Bot запущен!": "🤖 FVG Alert Bot started!",
    "Бот отслеживает FVG на Bitunix и ставки фандинга на нескольких биржах.": "The bot tracks FVG on Bitunix and funding rates across multiple exchanges.",
    "Поддерживаются Bitunix, Binance, Bybit, Bitget, Gate и BingX.": "Supported exchanges: Bitunix, Binance, Bybit, Bitget, Gate and BingX.",
    "Команды:": "Commands:",
    "Основные разделы всегда доступны на клавиатуре под полем сообщения.": "The main sections are always available below the message field.",
    "Уведомления о подтверждённых FVG включены автоматически для BTCUSDT.": "Confirmed FVG alerts were enabled automatically for BTCUSDT.",
    "Пред-FVG остаются выключенными — их можно включить командой /fvg_pre_alert on.": "Pre-FVG alerts remain disabled; enable them with /fvg_pre_alert on.",
    "Поддержать проект": "Support the project", "Спасибо за поддержку разработки и работы бота.": "Thank you for supporting the bot's development and operation.",
    "EVM-адрес:": "EVM address:", "Перед отправкой проверьте выбранную сеть.": "Check the selected network before sending.",
    "Адрес предназначен для совместимых EVM-сетей.": "The address is intended for compatible EVM networks.",
    "Уведомления о фандинге": "Funding alerts", "Статус:": "Status:", "Частота:": "Frequency:",
    "Порог:": "Threshold:", "Направление:": "Direction:", "Биржи:": "Exchanges:",
    "Следующая проверка:": "Next check:", "включены": "enabled", "выключены": "disabled",
    "каждые": "every", "положительный и отрицательный": "positive and negative",
    "положительный": "positive", "отрицательный": "negative",
    "после включения — в ближайшие :50": "after enabling — at the next :50", "в ближайшие :50": "at the next :50",
    "Общий снимок выбранных бирж обновляется в 50 минут каждого часа.": "A shared snapshot of selected exchanges is refreshed at minute 50 of every hour.",
    "Введите частоту уведомлений целым числом от 1 до 48.": "Enter the alert frequency as an integer from 1 to 48.",
    "Введите порог фандинга в процентах положительным числом.": "Enter a positive funding threshold in percent.",
    "Введите инструмент": "Enter an instrument", "Например:": "Example:",
    "Частота сохранена:": "Frequency saved:", "Порог сохранён:": "Threshold saved:",
    "Не получилось:": "Could not save:", "Попробуйте ещё раз.": "Try again.", "Попробуйте позже.": "Try again later.",
    "Текущая ставка и изменение цены за 24 часа.": "Current rate and 24-hour price change.",
    "Страница": "Page", "Положительный фандинг": "Positive funding", "Отрицательный фандинг": "Negative funding",
    "Нет данных": "No data", "Проверка фандинга": "Funding check",
    "Бот покажет текущую ставку на всех подключённых биржах.": "The bot will show the current rate on every connected exchange.",
    "Текущая ставка по подключённым биржам:": "Current rate across connected exchanges:",
    "API временно недоступен": "API temporarily unavailable", "контракт не найден": "contract not found",
    "ставка недоступна": "rate unavailable", "Настройки FVG 15м": "FVG 15m settings",
    "Модуль:": "Module:", "Подтверждённые:": "Confirmed:", "Пред-FVG за 3 минуты:": "Pre-FVG 3 minutes early:",
    "Бычьи:": "Bullish:", "медвежьи:": "bearish:", "Инструменты:": "Instruments:",
    "не выбраны": "not selected", "вкл.": "on", "выкл.": "off", "Бычьи": "Bullish", "Медвежьи": "Bearish",
    "подтверждено": "confirmed", "предварительных": "preliminary", "Отправлено уведомлений пользователям:": "User notifications sent:",
    "FVG-события": "FVG events", "всё время": "all time", "дней": "days", "Инструмент": "Instrument",
    "Таймфрейм": "Timeframe", "Направление": "Direction", "Зона FVG": "FVG zone", "Размер зоны": "Zone size",
    "Цена сигнала": "Signal price", "Время C": "C time", "Статус": "Status",
    "Предварительный сигнал: свеча C ещё не закрыта": "Preliminary signal: candle C is not closed yet",
    "Подтверждён закрытием свечи C": "Confirmed by candle C close", "Возможный бычий FVG": "Possible bullish FVG",
    "Возможный медвежий FVG": "Possible bearish FVG", "Подтверждённый бычий FVG": "Confirmed bullish FVG",
    "Подтверждённый медвежий FVG": "Confirmed bearish FVG", "Бычий": "Bullish", "Медвежий": "Bearish",
    "Фандинг пересёк заданный порог": "Funding crossed the configured threshold",
    "Продолжение уведомления о фандинге": "Funding alert continued", "Выбери инструмент": "Select an instrument",
    "Сначала добавь инструмент командой": "First add an instrument with", "Фильтр включён": "Filter enabled",
    "Фильтр выключен": "Filter disabled", "Проценты": "Percent", "Доллары": "USD",
    "Ввести минимум": "Enter minimum", "Ввести диапазон": "Enter range", "Минимальный размер": "Minimum size",
    "Диапазон": "Range", "Все остальные настройки меняются кнопками ниже.": "All other settings are changed with the buttons below.",
    "Попробуй ещё раз или /cancel.": "Try again or use /cancel.", "Админ-настройки": "Admin settings",
    "Публичный доступ включён.": "Public access enabled.", "Приватный доступ включён.": "Private access enabled.",
    "Бот теперь принимает команды от всех Telegram-пользователей.": "The bot now accepts commands from all Telegram users.",
    "Бот принимает команды только от пользователей из allowlist и одобренных заявок.": "The bot accepts commands only from allowlisted users and approved requests.",
    "Разрешённые пользователи": "Allowed users", "Всего:": "Total:", "Список пуст.": "The list is empty.",
    "Без имени": "Unnamed", "WebSocket Bitunix": "Bitunix WebSocket", "подключён": "connected",
    "отключён": "disconnected", "неизвестно": "unknown", "Последняя свеча": "Last candle",
    "Последний REST recovery": "Last REST recovery", "Последняя ошибка": "Last error",
    "Очередь уведомлений": "Notification queue", "Сообщений в outbox": "Messages in outbox",
    "Успешных доставок": "Successful deliveries", "Ошибок доставки": "Delivery failures",
    "Повторных доставок": "Delivery retries", "Навсегда отклонено Telegram": "Permanently rejected by Telegram",
    "Состояние баз данных": "Database status", "не создана": "not created", "ошибка": "error",
    "JSON-настройки": "JSON settings", "Память и нагрузка": "Memory and load", "Память процесса": "Process memory",
    "Свободно на диске": "Free disk space", "Версия установленного релиза": "Installed release version",
    "Версия": "Version", "не записан": "not recorded", "Резервная копия создана.": "Backup created.",
    "Не удалось создать резервную копию.": "Could not create a backup.", "Перезапустить бота?": "Restart the bot?",
    "Процесс завершится с ошибкой, после чего systemd запустит его снова.": "The process will exit with an error and systemd will start it again.",
    "Бот перезапускается…": "The bot is restarting…", "Язык изменён.": "Language updated.",
    "Формат уведомлений изменён.": "Alert format updated.", "Нижнее меню обновлено.": "Bottom menu updated.",
}


def translate_label(text: str, language: str) -> str:
    if language != "en":
        return text
    selected, core = "", text
    match = re.match(r"^([✅▫️⏸️]\s*)", core)
    if match:
        selected, core = match.group(1), core[match.end():]
    prefix = "✓ " if core.startswith("✓ ") else ""
    if prefix:
        core = core[2:]
    translated = BUTTONS.get(core, core)
    for source, target in sorted(PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, target)
    return selected + prefix + translated


def _translate_text(text: str) -> str:
    translated = text
    for exchange in ("Bitunix", "Binance", "Bybit", "Bitget", "Gate", "BingX"):
        translated = translated.replace(f"Фандинг {exchange}", f"{exchange} funding")
    for source, target in sorted(PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, target)
    return re.sub(r"\bиз\b", "of", translated)


def _line_value(lines: list[str], *labels: str) -> str | None:
    for line in lines:
        for label in labels:
            prefix = f"{label}:"
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    return None


def _compact_fvg(text: str, language: str) -> str:
    lines = text.splitlines()
    symbol = _line_value(lines, "Инструмент", "Instrument") or "?"
    timeframe = _line_value(lines, "Таймфрейм", "Timeframe") or "15m"
    zone = _line_value(lines, "Зона FVG", "FVG zone") or "—"
    signal = _line_value(lines, "Цена сигнала", "Signal price") or "—"
    title = lines[0] if lines else "FVG"
    preliminary = "Возможный" in title or "Possible" in title or "Предварительный" in text
    icon_match = re.match(r"^(\S+)", title)
    icon = icon_match.group(1) if icon_match else "🔔"
    if language == "en":
        return f"{icon} FVG {symbol} · {timeframe}\nZone: {zone} · Price: {signal}\n{'Preliminary' if preliminary else 'Confirmed'}"
    return f"{icon} FVG {symbol} · {timeframe}\nЗона: {zone} · Цена: {signal}\n{'Предварительный' if preliminary else 'Подтверждённый'}"


def _compact_funding(text: str, language: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    threshold = _line_value(lines, "Порог", "Threshold") or "—"
    rate_lines = [line for line in lines if "<code>" in line]
    header = f"🔔 Funding alert · threshold {threshold}" if language == "en" else f"🔔 Фандинг · порог {threshold}"
    return "\n".join([header, *rate_lines])


def localize_text(text: str, language: str, mode: str = "detailed") -> str:
    if not isinstance(text, str) or not text:
        return text
    is_fvg = "Зона FVG:" in text or "FVG zone:" in text
    is_funding = "Фандинг пересёк заданный порог" in text or "Funding crossed the configured threshold" in text or "Продолжение уведомления о фандинге" in text
    if mode == "compact" and is_fvg:
        return _compact_fvg(text, language)
    if mode == "compact" and is_funding:
        return _compact_funding(text, language)
    return text if language == "ru" else _translate_text(text)
