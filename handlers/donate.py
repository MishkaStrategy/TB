"""Donation information shown from the persistent Telegram menu."""

from telegram import Update
from telegram.ext import ContextTypes

from handlers.auth import authorized

DONATION_ADDRESS = "0xA525804A2B752ccB5bc17233017bd322DD8b058f"


def format_donation_text() -> str:
    return (
        "❤️ <b>Поддержать проект</b>\n\n"
        "Спасибо за поддержку разработки и работы бота.\n\n"
        "<b>USDT · ETH · BNB</b>\n"
        "EVM-адрес:\n"
        f"<code>{DONATION_ADDRESS}</code>\n\n"
        "⚠️ Перед отправкой проверьте выбранную сеть. Адрес предназначен для совместимых EVM-сетей."
    )


async def send_donation(message) -> None:
    await message.reply_text(format_donation_text(), parse_mode="HTML")


@authorized
async def donate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_donation(update.effective_message)
