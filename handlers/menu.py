"""Button-based Telegram interface for confirmed multi-timeframe FVG controls."""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from alerts.fvg_models import FvgDirection
from alerts.fvg_store import FvgAlertSettings
from database.user_preferences import UserPreferences
from handlers.auth import authorized
from handlers.fvg_alert import build_fvg_stats_period_menu, format_fvg_stats, send_fvg_stats
from handlers.fvg_instruments_15m import show_fvg_instruments


PREFERENCES = UserPreferences()

REPLY_MENU_FVG = "📉 FVG"
REPLY_MENU_FUNDING = "💸 Фандинг"
REPLY_MENU_ALERTS = "🔔 Уведомления"
REPLY_MENU_STATS = "📊 Статистика"
REPLY_MENU_SETTINGS = "⚙️ Настройки"
REPLY_MENU_DONATE = "❤️ Донат"

REPLY_MENU_FUNDING_EN = "💸 Funding"
REPLY_MENU_ALERTS_EN = "🔔 Alerts"
REPLY_MENU_STATS_EN = "📊 Statistics"
REPLY_MENU_SETTINGS_EN = "⚙️ Settings"
REPLY_MENU_DONATE_EN = "❤️ Donate"


def _is_english(language: str) -> bool:
    return str(language or "ru").lower().startswith("en")


def build_reply_menu(language: str = "ru") -> ReplyKeyboardMarkup:
    if _is_english(language):
        rows = [
            [REPLY_MENU_FVG, REPLY_MENU_FUNDING_EN],
            [REPLY_MENU_ALERTS_EN, REPLY_MENU_STATS_EN],
            [REPLY_MENU_SETTINGS_EN, REPLY_MENU_DONATE_EN],
        ]
        placeholder = "Choose a section"
    else:
        rows = [
            [REPLY_MENU_FVG, REPLY_MENU_FUNDING],
            [REPLY_MENU_ALERTS, REPLY_MENU_STATS],
            [REPLY_MENU_SETTINGS, REPLY_MENU_DONATE],
        ]
        placeholder = "Выберите раздел"
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=placeholder,
    )


def build_main_menu(chat_id, settings=None, language: str = "ru"):
    settings = settings or FvgAlertSettings()
    enabled = settings.is_enabled(chat_id)
    if _is_english(language):
        fvg_label = "✅ FVG" if enabled else "⏸ FVG"
        stats_label = "📊 Statistics"
        funding_label = "💸 Funding"
        settings_label = "⚙️ Settings"
    else:
        fvg_label = "✅ FVG" if enabled else "⏸ FVG"
        stats_label = "📊 Статистика"
        funding_label = "💸 Фандинг"
        settings_label = "⚙️ Настройки"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(fvg_label, callback_data="menu:fvg-settings")],
            [InlineKeyboardButton(stats_label, callback_data="menu:fvg-stats")],
            [InlineKeyboardButton(funding_label, callback_data="menu:funding")],
            [InlineKeyboardButton(settings_label, callback_data="settings:open")],
        ]
    )


def build_fvg_settings_menu(chat_id, settings=None, language: str = "ru"):
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)

    def mark(enabled):
        return "✅" if enabled else "⏸"

    instruments = list(user.get("symbols", {}).items())
    price_enabled = any(
        item.get("price_filter", {}).get("enabled", False)
        for _, item in instruments
    )
    size_enabled = any(
        item.get("size_filter", {}).get("enabled", False)
        for _, item in instruments
    )

    if _is_english(language):
        module_label = "FVG module"
        confirmed_label = "Confirmed"
        bull_label = "🐮 Bullish"
        bear_label = "🐻 Bearish"
        instruments_label = "📌 Instruments"
        price_label = "Price"
        size_label = "📏 FVG size"
        faq_label = "❓ FVG FAQ"
        back_label = "⬅️ Main menu"
    else:
        module_label = "Модуль FVG"
        confirmed_label = "Подтверждённые"
        bull_label = "🐮 Бычьи"
        bear_label = "🐻 Медвежьи"
        instruments_label = "📌 Инструменты"
        price_label = "Цена"
        size_label = "📏 Размер FVG"
        faq_label = "❓ FAQ по FVG"
        back_label = "⬅️ Главное меню"

    rows = [
        [InlineKeyboardButton(
            f"{mark(user['enabled'])} {module_label}",
            callback_data="menu:fvg-toggle",
        )],
        [InlineKeyboardButton(
            f"{mark(user['notify_confirmed_fvg'])} {confirmed_label}",
            callback_data="menu:fvg-confirmed-toggle",
        )],
        [
            InlineKeyboardButton(
                f"{mark(user['bullish_enabled'])} {bull_label}",
                callback_data="menu:fvg-bull-toggle",
            ),
            InlineKeyboardButton(
                f"{mark(user['bearish_enabled'])} {bear_label}",
                callback_data="menu:fvg-bear-toggle",
            ),
        ],
        [
            InlineKeyboardButton(instruments_label, callback_data="fvg15:open"),
            InlineKeyboardButton(f"{mark(price_enabled)} {price_label}", callback_data="menu:fvg-price"),
        ],
        [InlineKeyboardButton(f"{mark(size_enabled)} {size_label}", callback_data="menu:fvg-size")],
        [InlineKeyboardButton(faq_label, callback_data="fvg15:faq:main")],
        [InlineKeyboardButton(back_label, callback_data="menu:fvg-back")],
    ]
    return InlineKeyboardMarkup(rows)


async def _language(chat_id: int) -> str:
    preferences = await asyncio.to_thread(PREFERENCES.user, chat_id)
    return str(preferences.get("language", "ru"))


async def show_menu(message, chat_id):
    language = await _language(chat_id)
    if _is_english(language):
        keyboard_note = "Main sections are pinned below the message field."
        panel_title = "Control panel:"
    else:
        keyboard_note = "Основные разделы закреплены на клавиатуре ниже."
        panel_title = "Панель управления:"
    await message.reply_text(
        keyboard_note,
        reply_markup=build_reply_menu(language),
    )
    await message.reply_text(
        panel_title,
        reply_markup=build_main_menu(chat_id, language=language),
    )


@authorized
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update.effective_message, update.effective_chat.id)


@authorized
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith("menu:"):
        return
    await query.answer()
    action = query.data.removeprefix("menu:")
    message = query.message
    chat_id = update.effective_chat.id
    language = await _language(chat_id)
    english = _is_english(language)

    if action == "fvg-settings":
        settings = FvgAlertSettings()
        await message.edit_text(
            (
                "Only closed 15m candles are loaded from exchanges. "
                "FVG is calculated for 15m, 1h, 4h and 1d."
                if english
                else "С бирж загружаются только закрытые 15м свечи. FVG рассчитывается на 15м, 1ч, 4ч и 1д."
            ),
            reply_markup=build_fvg_settings_menu(chat_id, settings, language),
        )
    elif action == "fvg-toggle":
        settings = FvgAlertSettings()
        settings.set_enabled(chat_id, not settings.is_enabled(chat_id))
        await message.edit_reply_markup(
            reply_markup=build_fvg_settings_menu(chat_id, settings, language)
        )
    elif action == "fvg-confirmed-toggle":
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        settings.set_confirmed_enabled(chat_id, not user["notify_confirmed_fvg"])
        await message.edit_reply_markup(
            reply_markup=build_fvg_settings_menu(chat_id, settings, language)
        )
    elif action in {"fvg-bull-toggle", "fvg-bear-toggle"}:
        settings = FvgAlertSettings()
        user = settings.user(chat_id)
        direction = (
            FvgDirection.BULLISH
            if action == "fvg-bull-toggle"
            else FvgDirection.BEARISH
        )
        key = (
            "bullish_enabled"
            if direction is FvgDirection.BULLISH
            else "bearish_enabled"
        )
        settings.set_direction_enabled(chat_id, direction, not user[key])
        await message.edit_reply_markup(
            reply_markup=build_fvg_settings_menu(chat_id, settings, language)
        )
    elif action == "fvg-symbol-help":
        await show_fvg_instruments(message, chat_id, edit=False)
    elif action == "fvg-back":
        await message.edit_text(
            "Control panel:" if english else "Панель управления:",
            reply_markup=build_main_menu(chat_id, language=language),
        )
    elif action == "fvg-stats":
        await send_fvg_stats(message)
    elif action.startswith("fvg-stats:"):
        period = action.split(":", 1)[1]
        days = None if period == "all" else int(period)
        await message.edit_text(
            format_fvg_stats(days),
            reply_markup=build_fvg_stats_period_menu(days),
        )
