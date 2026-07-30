"""Supplementary RU/EN translations for the expanded FVG interface."""

from __future__ import annotations

import re


EXACT_BUTTONS = {
    "📉 FVG-центр": "📉 FVG center",
    "🔔 Настройки FVG": "🔔 FVG settings",
    "🔕 Настройки FVG": "🔕 FVG settings",
    "✅ Модуль включён": "✅ Module enabled",
    "⏸️ Модуль выключен": "⏸️ Module disabled",
    "➕ Добавить инструмент": "➕ Add instrument",
    "🔔 Сигналы и направления": "🔔 Signals and directions",
    "💰 Фильтр цены": "💰 Price filter",
    "📏 Фильтр размера": "📏 Size filter",
    "📊 Статистика FVG": "📊 FVG statistics",
    "❓ FAQ по FVG": "❓ FVG FAQ",
    "⬅️ FVG-центр": "⬅️ FVG center",
    "✅ Подтверждённые FVG": "✅ Confirmed FVG",
    "⏸️ Подтверждённые FVG": "⏸️ Confirmed FVG",
    "✅ Пред-FVG BTC · 15м": "✅ BTC pre-FVG · 15m",
    "⏸️ Пред-FVG BTC · 15м": "⏸️ BTC pre-FVG · 15m",
    "ℹ️ Пред-FVG: нужен BTC · 15м": "ℹ️ Pre-FVG: requires BTC · 15m",
    "📉 FVG-сигналы": "📉 FVG signals",
    "📉 Настройки FVG": "📉 FVG center",
    "📉 FVG-инструменты": "📉 FVG instruments",
    "📌 Инструменты": "📌 Instruments",
    "❓ FAQ": "❓ FAQ",
    "⬅️ Настройки FVG": "⬅️ FVG center",
    "Отмена": "Cancel",
    "Выбрать все": "Select all",
    "Продолжить": "Continue",
    "✅ Подтвердить": "✅ Confirm",
    "✏️ Изменить": "✏️ Change",
    "🕒 Изменить таймфреймы": "🕒 Change timeframes",
    "⏸️ Отключить уведомления": "⏸️ Disable alerts",
    "▶️ Включить уведомления": "▶️ Enable alerts",
    "⏳ Выключить пред-FVG": "⏳ Disable pre-FVG",
    "⏳ Включить пред-FVG": "⏳ Enable pre-FVG",
    "🗑 Удалить инструмент": "🗑 Delete instrument",
    "⬅️ Мои инструменты": "⬅️ My instruments",
    "Удалить": "Delete",
    "Как добавить инструмент": "How to add an instrument",
    "FVG и подтверждение": "FVG and confirmation",
    "Пред-FVG": "Pre-FVG",
    "Лимиты и настройки": "Limits and settings",
    "⬅️ Все вопросы": "⬅️ All topics",
    "⬅️ FVG-инструменты": "⬅️ FVG instruments",
    "🔔 Центр уведомлений": "🔔 Alert center",
    "💸 Уведомления о фандинге": "💸 Funding alerts",
}

TEXT_REPLACEMENTS = (
    ("📉 <b>FVG-центр</b>", "📉 <b>FVG center</b>"),
    ("🔔 <b>FVG-сигналы</b>", "🔔 <b>FVG signals</b>"),
    ("🔔 <b>Центр уведомлений</b>", "🔔 <b>Alert center</b>"),
    ("📉 <b>FVG-уведомления</b>", "📉 <b>FVG alerts</b>"),
    ("❓ <b>FAQ по FVG</b>", "❓ <b>FVG FAQ</b>"),
    ("➕ <b>Как добавить инструмент</b>", "➕ <b>How to add an instrument</b>"),
    ("✅ <b>FVG и подтверждение</b>", "✅ <b>FVG and confirmation</b>"),
    ("⏳ <b>Пред-FVG</b>", "⏳ <b>Pre-FVG</b>"),
    ("⚙️ <b>Лимиты и настройки</b>", "⚙️ <b>Limits and settings</b>"),
    ("🔎 <b>Проверьте настройки</b>", "🔎 <b>Review settings</b>"),
    ("Добавление FVG-инструмента", "Adding an FVG instrument"),
    ("Изменение FVG-инструмента", "Editing an FVG instrument"),
    (
        "Настройте FVG-сигналы и уведомления о фандинге отдельно.",
        "Configure FVG signals and funding alerts separately.",
    ),
    (
        "Подтверждённые FVG приходят после закрытия свечи C. Пред-FVG доступен только для BTC на 15-минутном таймфрейме.",
        "Confirmed FVG alerts arrive after candle C closes. Pre-FVG is available only for BTC on the 15-minute timeframe.",
    ),
    (
        "Добавьте первый инструмент: выберите биржу, пару и один или несколько таймфреймов.",
        "Add your first instrument: choose an exchange, pair, and one or more timeframes.",
    ),
    (
        "Пред-FVG формируется только для BTC на 15м. Для остальных инструментов доступны только подтверждённые сигналы после закрытия свечи C.",
        "Pre-FVG is generated only for BTC on 15m. Other instruments receive confirmed signals only after candle C closes.",
    ),
    (
        "Пред-FVG доступен только после добавления BTC-инструмента с таймфреймом 15 минут.",
        "Pre-FVG becomes available after adding a BTC instrument with the 15-minute timeframe.",
    ),
    (
        "Пред-FVG доступен только для BTC-инструмента с таймфреймом 15 минут.",
        "Pre-FVG is available only for a BTC instrument on the 15-minute timeframe.",
    ),
    ("Удалите один инструмент, чтобы освободить место.", "Delete an instrument to free a slot."),
    ("Добавлено инструментов:", "Instruments added:"),
    (
        "У вас пока нет инструментов. Добавьте биржу, торговую пару и таймфреймы.",
        "You have no instruments yet. Add an exchange, trading pair, and timeframes.",
    ),
    (
        "Выберите раздел. Здесь объясняется, когда приходит сигнал, почему пред-FVG доступен только для Bitcoin и как считается лимит инструментов.",
        "Choose a topic to learn when alerts arrive, why pre-FVG is Bitcoin-only, and how the instrument limit is calculated.",
    ),
    ("1. Выберите биржу.", "1. Choose an exchange."),
    ("2. Введите пару: BTC, BTCUSDT или BTC/USDT.", "2. Enter a pair: BTC, BTCUSDT, or BTC/USDT."),
    ("3. Отметьте таймфреймы.", "3. Select timeframes."),
    ("4. Проверьте настройки и подтвердите сохранение.", "4. Review the settings and confirm."),
    (
        "Одинаковая пара на разных биржах считается разными инструментами, потому что свечи и котировки могут отличаться.",
        "The same pair on different exchanges counts as separate instruments because candles and prices can differ.",
    ),
    (
        "FVG — ценовой дисбаланс между тремя свечами. Обычное уведомление приходит только после закрытия свечи C, которая подтверждает зону.",
        "FVG is a price imbalance across three candles. A standard alert arrives only after candle C closes and confirms the zone.",
    ),
    (
        "Доступные таймфреймы: 15 минут, 1 час, 4 часа и 1 день. Одна и та же подтверждённая зона повторно не отправляется.",
        "Available timeframes: 15 minutes, 1 hour, 4 hours, and 1 day. The same confirmed zone is not sent twice.",
    ),
    (
        "Пред-FVG предупреждает о возможной 15-минутной зоне до закрытия свечи C. Эта функция доступна только для пар с базовым активом BTC.",
        "Pre-FVG warns about a possible 15-minute zone before candle C closes. It is available only for pairs with BTC as the base asset.",
    ),
    (
        "Для ETH, SOL и остальных активов уведомление приходит исключительно после подтверждения закрытой свечой.",
        "For ETH, SOL, and other assets, alerts arrive only after confirmation by a closed candle.",
    ),
    ("Несколько таймфреймов одной пары занимают одно место.", "Multiple timeframes for one pair use a single slot."),
    (
        "Отключённый инструмент сохраняет настройки и продолжает занимать место. После удаления место освобождается.",
        "A disabled instrument keeps its settings and still uses a slot. Deleting it frees the slot.",
    ),
    (
        "Выберите хотя бы один таймфрейм. Уведомление придёт только после закрытия подтверждающей свечи.",
        "Select at least one timeframe. The alert arrives only after the confirming candle closes.",
    ),
    (
        "Сигнал будет отправлен только после закрытия свечи, подтверждающей FVG.",
        "The alert will be sent only after the candle confirming the FVG closes.",
    ),
    ("Инструмент уже удалён или не найден.", "The instrument was deleted or could not be found."),
    ("Модуль:", "Module:"),
    ("Инструменты:", "Instruments:"),
    ("Биржи:", "Exchanges:"),
    ("Таймфреймы:", "Timeframes:"),
    ("Сигналы:", "Signals:"),
    ("Направления:", "Directions:"),
    ("Фильтры:", "Filters:"),
    ("Подтверждённые:", "Confirmed:"),
    ("Пред-FVG BTC:", "BTC pre-FVG:"),
    ("Бычьи:", "Bullish:"),
    ("Медвежьи:", "Bearish:"),
    ("Действие:", "Action:"),
    ("Уведомления:", "Alerts:"),
    ("Пред-FVG:", "Pre-FVG:"),
    ("активны", "active"),
    ("включены", "enabled"),
    ("включён", "enabled"),
    ("выключены", "disabled"),
    ("выключен", "disabled"),
    ("без подтверждённых", "confirmed disabled"),
    ("подтверждённые", "confirmed"),
    ("пред-FVG BTC выключен", "BTC pre-FVG disabled"),
    ("пред-FVG BTC", "BTC pre-FVG"),
    ("пред-FVG недоступен", "pre-FVG unavailable"),
    ("нужен BTC с таймфреймом 15м", "requires BTC on 15m"),
    ("🐮 бычьи", "🐮 bullish"),
    ("🐻 медвежьи", "🐻 bearish"),
    ("не выбраны", "not selected"),
)


def translate_fvg_label(text: str, language: str) -> str:
    if language != "en" or not isinstance(text, str):
        return text
    if text in EXACT_BUTTONS:
        return EXACT_BUTTONS[text]
    translated = text
    dynamic_replacements = (
        ("Мои инструменты", "My instruments"),
        ("Лимит", "Limit"),
        ("Добавить инструмент", "Add instrument"),
        ("Подтверждённые FVG", "Confirmed FVG"),
        ("Пред-FVG BTC", "BTC pre-FVG"),
        ("Пред-FVG", "Pre-FVG"),
        ("Бычьи", "Bullish"),
        ("Медвежьи", "Bearish"),
        ("15 минут", "15 minutes"),
        ("1 час", "1 hour"),
        ("4 часа", "4 hours"),
        ("1 день", "1 day"),
    )
    for source, target in dynamic_replacements:
        translated = translated.replace(source, target)
    return translated


def translate_fvg_text(text: str, language: str) -> str:
    if language != "en" or not isinstance(text, str):
        return text
    translated = text
    for source, target in TEXT_REPLACEMENTS:
        translated = translated.replace(source, target)
    translated = re.sub(r"\bиз\b", "of", translated)
    return translated
