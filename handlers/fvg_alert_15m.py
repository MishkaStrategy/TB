"""Confirmed-only FVG command facade for the 15-minute runtime."""

from telegram import Update
from telegram.ext import ContextTypes

from alerts.fvg_store import FvgAlertSettings
from handlers.auth import authorized
from handlers.fvg_alert import fvg_stats


@authorized
async def fvg_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    setting = context.args[0].lower() if context.args else "status"
    settings = FvgAlertSettings()
    chat_id = update.effective_chat.id
    if setting in {"on", "off"}:
        settings.set_enabled(chat_id, setting == "on")
    user = settings.user(chat_id)
    status = "вкл." if user.get("enabled") else "выкл."
    confirmed = "вкл." if user.get("notify_confirmed_fvg", True) else "выкл."
    await update.effective_message.reply_text(
        "⚙️ Настройки FVG 15м\n"
        f"Модуль: {status}\n"
        f"Подтверждённые FVG: {confirmed}\n"
        "Источник данных: только закрытые 15-минутные свечи.\n"
        "Предварительные FVG отключены."
    )


__all__ = ["fvg_alert", "fvg_stats"]
