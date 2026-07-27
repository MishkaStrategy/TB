"""User settings and multilingual persistent-menu routing."""

from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from config import is_admin
from database.user_preferences import UserPreferences
from handlers.auth import authorized
from handlers.donate import send_donation
from handlers.fvg_alert import send_fvg_stats
from handlers.menu import build_fvg_settings_menu, build_main_menu, build_reply_menu
from handlers.multi_funding import show_funding
from handlers.multi_funding_alert_ui import (
    build_menu as build_funding_alert_menu,
    format_settings as format_funding_alert_settings,
)


PREFERENCES = UserPreferences()
MENU_ALIASES = {
    "📉 FVG": "fvg",
    "💸 Фандинг": "funding",
    "💸 Funding": "funding",
    "🔔 Уведомления": "alerts",
    "🔔 Alerts": "alerts",
    "📊 Статистика": "stats",
    "📊 Statistics": "stats",
    "⚙️ Настройки": "settings",
    "⚙️ Settings": "settings",
    "❤️ Донат": "donate",
    "❤️ Donate": "donate",
}
MENU_PATTERN = rf"^(?:{'|'.join(re.escape(label) for label in MENU_ALIASES)})$"


def format_settings_text(chat_id: int, preferences=None) -> str:
    preferences = preferences or PREFERENCES.user(chat_id)
    language = preferences["language"]
    mode = preferences["message_mode"]
    if language == "en":
        mode_name = "Compact" if mode == "compact" else "Detailed"
        return (
            "⚙️ <b>User settings</b>\n\n"
            "🌐 Language: English\n"
            f"📱 Alert format: {mode_name}\n\n"
            "Compact alerts contain the instrument, FVG/funding value and status. "
            "Detailed alerts include all available fields."
        )
    mode_name = "Компактные" if mode == "compact" else "Подробные"
    return (
        "⚙️ <b>Пользовательские настройки</b>\n\n"
        "🌐 Язык: Русский\n"
        f"📱 Формат уведомлений: {mode_name}\n\n"
        "Компактные уведомления содержат инструмент, значение FVG/фандинга и статус. "
        "Подробные показывают все доступные поля."
    )


def settings_keyboard(chat_id: int, preferences=None) -> InlineKeyboardMarkup:
    preferences = preferences or PREFERENCES.user(chat_id)
    language = preferences["language"]
    mode = preferences["message_mode"]

    def selected(value: str, current: str) -> str:
        return "✅ " if value == current else "▫️ "

    if language == "en":
        rows = [
            [
                InlineKeyboardButton(
                    f"{selected('ru', language)}Russian",
                    callback_data="settings:language:ru",
                ),
                InlineKeyboardButton(
                    f"{selected('en', language)}English",
                    callback_data="settings:language:en",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{selected('compact', mode)}Compact",
                    callback_data="settings:mode:compact",
                ),
                InlineKeyboardButton(
                    f"{selected('detailed', mode)}Detailed",
                    callback_data="settings:mode:detailed",
                ),
            ],
            [InlineKeyboardButton("📉 FVG settings", callback_data="settings:fvg")],
            [InlineKeyboardButton("🔔 Funding alerts", callback_data="settings:funding")],
        ]
        admin_label = "🛠 Admin settings"
        back_label = "⬅️ Main menu"
    else:
        rows = [
            [
                InlineKeyboardButton(
                    f"{selected('ru', language)}Русский",
                    callback_data="settings:language:ru",
                ),
                InlineKeyboardButton(
                    f"{selected('en', language)}English",
                    callback_data="settings:language:en",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{selected('compact', mode)}Компактные",
                    callback_data="settings:mode:compact",
                ),
                InlineKeyboardButton(
                    f"{selected('detailed', mode)}Подробные",
                    callback_data="settings:mode:detailed",
                ),
            ],
            [InlineKeyboardButton("📉 Настройки FVG", callback_data="settings:fvg")],
            [InlineKeyboardButton("🔔 Уведомления о фандинге", callback_data="settings:funding")],
        ]
        admin_label = "🛠 Админ-настройки"
        back_label = "⬅️ Главное меню"

    if is_admin(chat_id):
        rows.append([InlineKeyboardButton(admin_label, callback_data="settings:admin")])
    rows.append([InlineKeyboardButton(back_label, callback_data="settings:main")])
    return InlineKeyboardMarkup(rows)


async def show_settings(message, chat_id: int, *, edit: bool = False) -> None:
    preferences = PREFERENCES.user(chat_id)
    method = message.edit_text if edit else message.reply_text
    await method(
        format_settings_text(chat_id, preferences),
        reply_markup=settings_keyboard(chat_id, preferences),
        parse_mode="HTML",
    )


@authorized
async def persistent_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    action = MENU_ALIASES.get(message.text)
    if action == "fvg":
        await message.reply_text(
            "Настройки применяются отдельно для твоего Telegram ID.",
            reply_markup=build_fvg_settings_menu(chat_id),
        )
    elif action == "funding":
        await show_funding(message, context, edit=False)
    elif action == "alerts":
        await message.reply_text(
            format_funding_alert_settings(chat_id),
            reply_markup=build_funding_alert_menu(chat_id),
            parse_mode="HTML",
        )
    elif action == "stats":
        await send_fvg_stats(message)
    elif action == "settings":
        await show_settings(message, chat_id)
    elif action == "donate":
        await send_donation(message)


@authorized
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    chat_id = update.effective_chat.id
    action = query.data.removeprefix("settings:")

    if action.startswith("language:"):
        language = action.split(":", 1)[1]
        PREFERENCES.set_language(chat_id, language)
        await query.answer("Язык изменён." if language == "ru" else "Language updated.")
        await show_settings(query.message, chat_id, edit=True)
        await query.message.reply_text(
            "Нижнее меню обновлено." if language == "ru" else "Bottom menu updated.",
            reply_markup=build_reply_menu(),
        )
        return

    if action.startswith("mode:"):
        mode = action.split(":", 1)[1]
        preferences = PREFERENCES.set_message_mode(chat_id, mode)
        await query.answer(
            "Формат уведомлений изменён."
            if preferences["language"] == "ru"
            else "Alert format updated."
        )
        await show_settings(query.message, chat_id, edit=True)
        return

    await query.answer()
    if action in {"open", "back"}:
        await show_settings(query.message, chat_id, edit=True)
    elif action == "fvg":
        await query.message.edit_text(
            "Настройки применяются отдельно для твоего Telegram ID.",
            reply_markup=build_fvg_settings_menu(chat_id),
        )
    elif action == "funding":
        await query.message.edit_text(
            format_funding_alert_settings(chat_id),
            reply_markup=build_funding_alert_menu(chat_id),
            parse_mode="HTML",
        )
    elif action == "admin":
        from handlers.admin_settings import show_admin_panel

        await show_admin_panel(query.message, chat_id, edit=True)
    elif action == "main":
        await query.message.edit_text(
            "Панель управления:",
            reply_markup=build_main_menu(chat_id),
        )


def build_settings_handlers():
    return (
        MessageHandler(filters.Regex(MENU_PATTERN), persistent_menu),
        CallbackQueryHandler(settings_callback, pattern=r"^settings:"),
    )
