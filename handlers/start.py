import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from alerts.fvg_store import FvgAlertSettings
from database.user_preferences import UserPreferences
from handlers.auth import authorized
from handlers.menu import show_menu


PREFERENCES = UserPreferences()


def _enable_confirmed_fvg_for_new_user(chat_id: int, settings: FvgAlertSettings | None = None) -> bool:
    settings = settings or FvgAlertSettings()
    user = settings.user(chat_id)
    user["enabled"] = True
    user["notify_confirmed_fvg"] = True

    def register(data):
        users = data.setdefault("users", {})
        key = str(chat_id)
        if key in users:
            return False
        users[key] = user
        return True

    return bool(settings._transaction(register))


@authorized
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await asyncio.to_thread(_enable_confirmed_fvg_for_new_user, chat_id)
    preferences = await asyncio.to_thread(PREFERENCES.user, chat_id)
    language = preferences.get("language", "ru")

    if language == "en":
        text = (
            "🤖 <b>TB Trading Assistant</b>\n\n"
            "FVG and multi-exchange funding monitoring inside Telegram.\n"
            "Use the pinned buttons below for the main sections; Telegram's command menu remains available for advanced actions."
        )
    else:
        text = (
            "🤖 <b>TB Trading Assistant</b>\n\n"
            "Мониторинг FVG и мультибиржевого фандинга прямо в Telegram.\n"
            "Основные разделы доступны на закреплённых кнопках ниже; расширенные действия остаются в меню команд Telegram."
        )

    await update.effective_message.reply_text(text, parse_mode="HTML")
    await show_menu(update.effective_message, chat_id)
