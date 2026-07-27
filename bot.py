import asyncio

from telegram import BotCommand, MenuButtonCommands
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, TypeHandler

from alerts.process_watchdog import start_process_watchdog, stop_process_watchdog
from alerts.scheduler_multi import schedule_fvg_alerts, start_fvg_stream, stop_fvg_stream
from config import TELEGRAM_TOKEN
from database.user_activity import UserActivityRegistry
from database.user_preferences import UserPreferences
from handlers.admin_settings import admin, admin_callback
from handlers.donate import donate
from handlers.fvg_alert import fvg_alert, fvg_pre_alert, fvg_stats
from handlers.fvg_filter_ui import build_fvg_filter_handlers
from handlers.menu import menu, menu_callback
from handlers.multi_funding import funding, funding_menu_callback
from handlers.multi_funding_alert_ui import build_handlers as build_funding_alert_handlers
from handlers.safe_fvg_symbol import fvg_symbol
from handlers.settings import build_settings_handlers
from handlers.start import start
from localization import set_current_chat_id
from localized_bot import LocalizedExtBot


BOT_COMMANDS = (
    BotCommand("menu", "Открыть главное меню"),
    BotCommand("admin", "Админ-панель"),
    BotCommand("fvg_alert", "Включить или выключить FVG"),
    BotCommand("fvg_pre_alert", "Настроить пред-FVG T−3"),
    BotCommand("fvg_symbol", "Настроить инструменты FVG"),
    BotCommand("fvg_price", "Фильтр цены FVG"),
    BotCommand("fvg_size", "Фильтр размера FVG"),
    BotCommand("fvg_stats", "Статистика FVG"),
    BotCommand("funding", "Топ ставок и уведомления"),
    BotCommand("donate", "Поддержать проект"),
)
BOT_COMMANDS_EN = (
    BotCommand("menu", "Open the main menu"),
    BotCommand("admin", "Admin panel"),
    BotCommand("fvg_alert", "Enable or disable FVG"),
    BotCommand("fvg_pre_alert", "Configure pre-FVG T−3"),
    BotCommand("fvg_symbol", "Configure FVG instruments"),
    BotCommand("fvg_price", "FVG price filter"),
    BotCommand("fvg_size", "FVG size filter"),
    BotCommand("fvg_stats", "FVG statistics"),
    BotCommand("funding", "Top rates and alerts"),
    BotCommand("donate", "Support the project"),
)


async def configure_bot_interface(application):
    await application.bot.set_my_commands(BOT_COMMANDS)
    await application.bot.set_my_commands(BOT_COMMANDS, language_code="ru")
    await application.bot.set_my_commands(BOT_COMMANDS_EN, language_code="en")
    await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def post_init(application):
    await configure_bot_interface(application)
    schedule_fvg_alerts(application)
    await start_fvg_stream(application)
    await start_process_watchdog(application)


async def post_shutdown(application):
    await stop_process_watchdog(application)
    await stop_fvg_stream(application)


async def prepare_user_context(update, context):
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id if chat is not None else None
    set_current_chat_id(chat_id)
    if chat_id is None:
        return
    suggested_language = (
        "en"
        if user is not None and str(user.language_code or "").lower().startswith("en")
        else "ru"
    )
    await asyncio.to_thread(UserPreferences().ensure, chat_id, language=suggested_language)


async def track_user_activity(update, context):
    user = update.effective_user
    if user is not None:
        await asyncio.to_thread(UserActivityRegistry().touch, user)


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")

    app = (
        Application.builder()
        .bot(LocalizedExtBot(token=TELEGRAM_TOKEN))
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(TypeHandler(object, prepare_user_context), group=-2)
    app.add_handler(TypeHandler(object, track_user_activity), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fvg_alert", fvg_alert))
    app.add_handler(CommandHandler("fvg_pre_alert", fvg_pre_alert))
    app.add_handler(CommandHandler("fvg_stats", fvg_stats))
    app.add_handler(CommandHandler("fvg_symbol", fvg_symbol))
    app.add_handler(CommandHandler("funding", funding))
    app.add_handler(CommandHandler("donate", donate))

    for handler in build_settings_handlers():
        app.add_handler(handler)
    for handler in build_fvg_filter_handlers():
        app.add_handler(handler)
    for handler in build_funding_alert_handlers():
        app.add_handler(handler, group=1)

    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(
        CallbackQueryHandler(funding_menu_callback, pattern=r"^menu:funding")
    )
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))

    print("Trading Assistant запущен 🚀")
    app.run_polling()


if __name__ == "__main__":
    main()
