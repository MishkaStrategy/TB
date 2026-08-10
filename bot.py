import asyncio
import logging

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, TypeHandler

from alerts.process_watchdog import start_process_watchdog, stop_process_watchdog
from alerts.scheduler_15m import (
    drain_fvg_outbox,
    get_fvg_service,
    schedule_fvg_alerts,
    start_fvg_stream,
    stop_fvg_stream,
)
from config import (
    DELIVERY_STATUS_TRACKING_ENABLED,
    GRACEFUL_SHUTDOWN_ENABLED,
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    RUNTIME_LIFECYCLE_ENABLED,
    RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS,
    TELEGRAM_TOKEN,
    USER_BLOCK_STATUS_ENABLED,
)
from database.runtime_lifecycle import RuntimeLifecycleStore
from database.telegram_delivery import TelegramDeliveryRegistry
from database.user_activity import UserActivityRegistry
from database.user_preferences import UserPreferences
from handlers.admin_settings import admin, admin_callback
from handlers.donate import donate
from handlers.fvg_alert_15m import fvg_alert, fvg_stats
from handlers.fvg_filter_ui import build_fvg_filter_handlers
from handlers.fvg_instruments_15m import build_fvg_instrument_handlers
from handlers.menu import menu, menu_callback
from handlers.multi_funding import funding, funding_menu_callback
from handlers.multi_funding_alert_ui import build_handlers as build_funding_alert_handlers
from handlers.safe_fvg_symbol import fvg_symbol
from handlers.settings import build_settings_handlers
from handlers.start import start
from localization import set_current_chat_id
from localized_bot import LocalizedExtBot
from mini_app_backend.lifecycle import start_mini_app_backend, stop_mini_app_backend
from operations.fvg_history_retention import configure_fvg_history_retention
from operations.process_restart import graceful_restart_requested
from operations.runtime_lifecycle import RuntimeLifecycleCoordinator


LOGGER = logging.getLogger(__name__)
USER_PREFERENCES = UserPreferences()
DELIVERY_REGISTRY = (
    TelegramDeliveryRegistry()
    if DELIVERY_STATUS_TRACKING_ENABLED or USER_BLOCK_STATUS_ENABLED
    else None
)
_RUNTIME_COORDINATOR = None


BOT_COMMANDS = (
    BotCommand("menu", "Открыть главное меню"),
    BotCommand("admin", "Админ-панель"),
    BotCommand("fvg_alert", "Включить или выключить FVG"),
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
    BotCommand("fvg_symbol", "Configure FVG instruments"),
    BotCommand("fvg_price", "FVG price filter"),
    BotCommand("fvg_size", "FVG size filter"),
    BotCommand("fvg_stats", "FVG statistics"),
    BotCommand("funding", "Top rates and alerts"),
    BotCommand("donate", "Support the project"),
)


def runtime_lifecycle_active() -> bool:
    return RUNTIME_LIFECYCLE_ENABLED or GRACEFUL_SHUTDOWN_ENABLED


def get_runtime_coordinator():
    global _RUNTIME_COORDINATOR
    if not runtime_lifecycle_active():
        return None
    if _RUNTIME_COORDINATOR is None:
        service = get_fvg_service()
        path = getattr(service.event_store, "path", None)
        _RUNTIME_COORDINATOR = RuntimeLifecycleCoordinator(
            store=RuntimeLifecycleStore(path),
            stop_watchdog=stop_process_watchdog,
            stop_stream=stop_fvg_stream,
            drain_outbox=drain_fvg_outbox,
            graceful_enabled=GRACEFUL_SHUTDOWN_ENABLED,
            timeout_seconds=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
            history_retention_days=RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS,
            metrics=service.event_store,
        )
    return _RUNTIME_COORDINATOR


async def configure_bot_interface(application):
    await application.bot.set_my_commands(BOT_COMMANDS)
    await application.bot.set_my_commands(BOT_COMMANDS, language_code="ru")
    await application.bot.set_my_commands(BOT_COMMANDS_EN, language_code="en")


async def post_init(application):
    coordinator = get_runtime_coordinator()
    if coordinator is not None:
        coordinator.begin_start(
            details={
                "graceful_shutdown_enabled": GRACEFUL_SHUTDOWN_ENABLED,
                "lifecycle_enabled": RUNTIME_LIFECYCLE_ENABLED,
            }
        )
    try:
        await configure_bot_interface(application)
        configure_fvg_history_retention(get_fvg_service().event_store)
        schedule_fvg_alerts(application)
        await start_fvg_stream(application)
        await start_process_watchdog(application)
        await start_mini_app_backend(application)
    except Exception as error:
        if coordinator is not None:
            coordinator.mark_startup_failed(error)
        raise
    if coordinator is not None:
        coordinator.mark_running(
            details={
                "graceful_shutdown_enabled": GRACEFUL_SHUTDOWN_ENABLED,
                "lifecycle_enabled": RUNTIME_LIFECYCLE_ENABLED,
            }
        )


async def post_stop(application):
    coordinator = get_runtime_coordinator()
    if coordinator is not None:
        return await coordinator.stop(application)
    return None


async def post_shutdown(application):
    await stop_mini_app_backend(application)
    coordinator = get_runtime_coordinator()
    if coordinator is not None:
        coordinator.mark_shutdown_complete()
        return
    await stop_process_watchdog(application)
    await stop_fvg_stream(application)


async def record_application_error(update, context):
    del update
    error = context.error or RuntimeError("Unknown Telegram application error")
    coordinator = get_runtime_coordinator()
    if coordinator is not None:
        coordinator.record_application_error(error)
    LOGGER.error(
        "Unhandled Telegram application error",
        exc_info=(type(error), error, error.__traceback__),
    )


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
    await asyncio.to_thread(
        USER_PREFERENCES.ensure,
        chat_id,
        language=suggested_language,
    )


async def track_user_activity(update, context):
    user = update.effective_user
    chat = update.effective_chat
    if user is not None:
        await asyncio.to_thread(UserActivityRegistry().touch, user)
    if DELIVERY_REGISTRY is not None and user is not None and chat is not None:
        await asyncio.to_thread(
            DELIVERY_REGISTRY.record_interaction,
            user.id,
            chat.id,
        )


def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")

    coordinator = get_runtime_coordinator()
    if coordinator is not None:
        coordinator.begin_start(
            details={
                "graceful_shutdown_enabled": GRACEFUL_SHUTDOWN_ENABLED,
                "lifecycle_enabled": RUNTIME_LIFECYCLE_ENABLED,
            }
        )

    try:
        builder = (
            Application.builder()
            .bot(LocalizedExtBot(token=TELEGRAM_TOKEN, preferences=USER_PREFERENCES))
            .post_init(post_init)
            .post_shutdown(post_shutdown)
        )
        if coordinator is not None:
            builder = builder.post_stop(post_stop)
        app = builder.build()

        app.add_handler(TypeHandler(object, prepare_user_context), group=-2)
        app.add_handler(TypeHandler(object, track_user_activity), group=-1)
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("fvg_alert", fvg_alert))
        app.add_handler(CommandHandler("fvg_stats", fvg_stats))
        app.add_handler(CommandHandler("fvg_symbol", fvg_symbol))
        app.add_handler(CommandHandler("funding", funding))
        app.add_handler(CommandHandler("donate", donate))

        for handler in build_settings_handlers():
            app.add_handler(handler)
        for handler in build_fvg_filter_handlers():
            app.add_handler(handler)
        for handler in build_fvg_instrument_handlers():
            app.add_handler(handler, group=2)
        for handler in build_funding_alert_handlers():
            app.add_handler(handler, group=1)

        app.add_handler(CommandHandler("menu", menu))
        app.add_handler(
            CallbackQueryHandler(funding_menu_callback, pattern=r"^menu:funding")
        )
        app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))
        app.add_handler(CommandHandler("admin", admin))
        app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin:"))
        app.add_error_handler(record_application_error)

        print("Trading Assistant запущен 🚀")
        app.run_polling()
        if graceful_restart_requested():
            raise SystemExit(1)
    except Exception as error:
        if coordinator is not None:
            coordinator.mark_process_failed(error)
        raise


if __name__ == "__main__":
    main()
