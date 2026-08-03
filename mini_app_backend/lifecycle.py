"""Optional in-process lifecycle for the Telegram Mini App API."""

from __future__ import annotations

import logging
import os

from aiohttp import web

from config import TELEGRAM_TOKEN, parse_bool, parse_positive_int

from .web import create_mini_app_application

LOGGER = logging.getLogger(__name__)
RUNNER_KEY = "mini_app_backend_runner"


async def start_mini_app_backend(application) -> None:
    """Start the API only when explicitly enabled in the environment.

    Hosting it inside the bot process keeps all low-frequency JSON stores under
    the same process locks and avoids a second writer racing the Telegram bot.
    """

    enabled = parse_bool(os.getenv("MINI_APP_BACKEND_ENABLED"), default=False)
    if not enabled:
        return
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is required for Mini App backend")

    host = os.getenv("MINI_APP_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = parse_positive_int(
        os.getenv("MINI_APP_BACKEND_PORT"), 18080, "MINI_APP_BACKEND_PORT"
    )
    auth_max_age = parse_positive_int(
        os.getenv("MINI_APP_AUTH_MAX_AGE_SECONDS"),
        3600,
        "MINI_APP_AUTH_MAX_AGE_SECONDS",
    )
    allowed_origins = os.getenv("MINI_APP_ALLOWED_ORIGINS", "")

    api = create_mini_app_application(
        bot_token=TELEGRAM_TOKEN,
        auth_max_age_seconds=auth_max_age,
        allowed_origins=allowed_origins,
    )
    runner = web.AppRunner(api, access_log=LOGGER)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    application.bot_data[RUNNER_KEY] = runner
    LOGGER.info("Telegram Mini App backend listening on %s:%s", host, port)


async def stop_mini_app_backend(application) -> None:
    bot_data = getattr(application, "bot_data", None)
    if bot_data is None:
        return
    runner = bot_data.pop(RUNNER_KEY, None)
    if runner is not None:
        await runner.cleanup()
