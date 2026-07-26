import asyncio

from telegram import BotCommand, MenuButtonCommands
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, TypeHandler

from alerts.scheduler import schedule_fvg_alerts, start_fvg_stream, stop_fvg_stream
from config import TELEGRAM_TOKEN

from handlers.start import start
from handlers.fvg_alert import (
    fvg_alert,
    fvg_pre_alert,
    fvg_stats,
)
from handlers.safe_fvg_symbol import fvg_symbol
from handlers.fvg_filter_ui import build_fvg_filter_handlers
from handlers.funding import funding
from handlers.menu import menu, menu_callback
from handlers.admin import admin, admin_callback
from database.user_activity import UserActivityRegistry


BOT_COMMANDS = (
    BotCommand("menu", "Настройки FVG"),
    BotCommand("admin", "Админ-панель"),
    BotCommand("fvg_alert", "Включить или выключить FVG"),
    BotCommand("fvg_pre_alert", "Настроить пред-FVG T−3"),
    BotCommand("fvg_symbol", "Настроить инструменты FVG"),
    BotCommand("fvg_price", "Фильтр цены FVG"),
    BotCommand("fvg_size", "Фильтр размера FVG"),
    BotCommand("fvg_stats", "Статистика FVG"),
    BotCommand("funding", "Топ ставок фандинга"),
)


async def configure_bot_interface(application):
    """Enable Telegram's compact menu button beside the message field."""
    await application.bot.set_my_commands(BOT_COMMANDS)
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def post_init(application):
    await configure_bot_interface(application)
    schedule_fvg_alerts(application)
    await start_fvg_stream(application)


async def track_user_activity(update, context):
    """Record incoming activity without blocking the Telegram event loop."""
    user = update.effective_user
    if user is not None:
        await asyncio.to_thread(UserActivityRegistry().touch, user)


def main():

    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_shutdown(stop_fvg_stream)
        .build()
    )

    app.add_handler(TypeHandler(object, track_user_activity), group=-1)

    # FVG notifications, settings, statistics, funding, and administration.
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("fvg_alert", fvg_alert)
    )
    app.add_handler(CommandHandler("fvg_pre_alert", fvg_pre_alert))
    app.add_handler(CommandHandler("fvg_stats", fvg_stats))
    app.add_handler(CommandHandler("fvg_symbol", fvg_symbol))
    app.add_handler(CommandHandler("funding", funding))
    for handler in build_fvg_filter_handlers():
        app.add_handler(handler)

    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))

    print("Trading Assistant запущен 🚀")

    app.run_polling()


if __name__ == "__main__":
    main()
