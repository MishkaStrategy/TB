"""Central localization for native Telegram button labels.

Telegram renders reply/inline button chrome itself. This module translates the
controllable part of that surface — button copy — while preserving callback_data,
URLs and the existing handler flow.
"""

from __future__ import annotations

import re

from localization import translate_label


BUTTON_TRANSLATIONS = {
    "Добавить инструмент": "Add instrument",
    "Отмена": "Cancel",
    "Выбрать все": "Select all",
    "Продолжить": "Continue",
    "Подтвердить": "Confirm",
    "Изменить": "Edit",
    "Изменить таймфреймы": "Edit timeframes",
    "Отключить уведомления": "Disable alerts",
    "Включить уведомления": "Enable alerts",
    "Удалить инструмент": "Delete instrument",
    "Мои инструменты": "My instruments",
    "Удалить": "Delete",
    "Как добавить инструмент": "How to add an instrument",
    "FVG и подтверждение": "FVG and confirmation",
    "Лимиты и настройки": "Limits and settings",
    "Все вопросы": "All questions",
    "FVG-инструменты": "FVG instruments",
    "Фильтр включён": "Filter enabled",
    "Фильтр выключен": "Filter disabled",
    "Бычьи": "Bullish",
    "Медвежьи": "Bearish",
    "Проценты": "Percent",
    "Доллары": "USD",
    "Ввести минимум": "Enter minimum",
    "Ввести диапазон": "Enter range",
    "Инструменты": "Instruments",
    "Уведомления включены": "Alerts enabled",
    "Уведомления выключены": "Alerts disabled",
    "Положительный": "Positive",
    "Отрицательный": "Negative",
    "Проверка фандинга": "Check funding",
    "Проверить другой": "Check another",
    "Топ ставок": "Top rates",
    "Показать актуальные": "Refresh rates",
    "Главное меню": "Main menu",
    "Настройки FVG": "FVG settings",
    "15 минут": "15 min",
    "30 минут": "30 min",
    "1 час": "1 h",
    "2 часа": "2 h",
    "4 часа": "4 h",
    "8 часов": "8 h",
    "12 часов": "12 h",
    "24 часа": "24 h",
    "48 часов": "48 h",
}

# Prefixes are visual cues only. They are intentionally retained exactly while
# the human-readable label to their right is translated recursively.
PREFIX_RE = re.compile(
    r"^(?P<prefix>(?:✅|▫️|⏸️|⏸|▶️|⬜|➕|❓|⬅️|✏️|🕒|🗑|🔎|📈|🔄|⚙️|🐮|🐻|💰|📏|⏱)\s+)(?P<core>.+)$"
)


def _translate_dynamic(core: str) -> str:
    value = re.sub(r"(?<!\w)(\d+)\s*ч\.", r"\1 h", core)
    value = re.sub(r"(?<!\w)(\d+)\s*мин\.", r"\1 min", value)
    return value


def translate_button_label(text: str, language: str) -> str:
    """Translate one Telegram button label without changing interaction data."""

    value = str(text or "")
    if str(language or "ru").lower() != "en":
        return value

    direct = BUTTON_TRANSLATIONS.get(value)
    if direct is not None:
        return direct

    match = PREFIX_RE.match(value)
    if match:
        core = match.group("core")
        translated_core = translate_button_label(core, "en")
        if translated_core != core:
            return f"{match.group('prefix')}{translated_core}"

    translated = translate_label(value, "en")
    if translated != value:
        return translated

    return _translate_dynamic(value)
