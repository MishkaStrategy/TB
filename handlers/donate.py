"""Donation information shown from the persistent Telegram menu."""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from database.user_preferences import UserPreferences
from handlers.auth import authorized

DONATION_ADDRESS = "0xA525804A2B752ccB5bc17233017bd322DD8b058f"
PREFERENCES = UserPreferences()


def format_donation_text(language: str = "ru") -> str:
    if language == "en":
        return (
            "❤️ <b>Support the project</b>\n\n"
            "Thank you for supporting development and keeping the bot running.\n\n"
            "<b>USDT · ETH · BNB</b>\n"
            "EVM address:\n"
            f"<code>{DONATION_ADDRESS}</code>"
        )
    return (
        "❤️ <b>Поддержать проект</b>\n\n"
        "Спасибо за поддержку разработки и работы бота.\n\n"
        "<b>USDT · ETH · BNB</b>\n"
        "EVM-адрес:\n"
        f"<code>{DONATION_ADDRESS}</code>"
    )


async def _language_for_chat(chat_id: int) -> str:
    preferences = await asyncio.to_thread(PREFERENCES.user, chat_id)
    return str(preferences.get("language", "ru"))


async def send_donation(message, *, language: str | None = None) -> None:
    if language is None:
        chat_id = getattr(message, "chat_id", None)
        language = await _language_for_chat(chat_id) if chat_id is not None else "ru"
    await message.reply_text(format_donation_text(language), parse_mode="HTML")


@authorized
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = await _language_for_chat(update.effective_chat.id)
    await send_donation(update.effective_message, language=language)
