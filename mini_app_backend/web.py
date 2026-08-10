"""aiohttp application for the Telegram Mini App settings API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from typing import Any, Callable

from aiohttp import web

from .admin_actions import AdminActionError, MiniAppAdminActions
from .auth import TelegramInitDataError, TelegramUser, validate_init_data
from .market_overview import MarketOverviewService
from .runtime_service import MiniAppSettingsService
from .service import SettingsValidationError

LOGGER = logging.getLogger(__name__)
INIT_DATA_HEADER = "X-Telegram-Init-Data"
DEFAULT_CLIENT_MAX_SIZE = 256 * 1024


def _error_response(
    status: int,
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> web.Response:
    error = {"code": code, "message": message}
    if field:
        error["field"] = field
    return web.json_response({"error": error}, status=status)


def _normalize_origins(values: Iterable[str] | str | None) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = values.split(",")
    return frozenset(
        str(value).strip().rstrip("/")
        for value in values
        if str(value).strip()
    )


def create_mini_app_application(
    *,
    bot_token: str,
    service: MiniAppSettingsService | None = None,
    market_overview: MarketOverviewService | None = None,
    admin_actions: MiniAppAdminActions | None = None,
    backup_callback: Callable[[TelegramUser], Any] | None = None,
    restart_callback: Callable[[TelegramUser], Any] | None = None,
    auth_max_age_seconds: int = 3600,
    allowed_origins: Iterable[str] | str | None = None,
    client_max_size: int = DEFAULT_CLIENT_MAX_SIZE,
) -> web.Application:
    """Build the API app without starting a listener.

    Keeping construction separate from the bot lifecycle makes the handlers
    directly testable and allows the production bot to host the API in the
    same process as its JSON stores.
    """

    if not bot_token:
        raise RuntimeError("TELEGRAM_TOKEN is required for Mini App backend")
    if auth_max_age_seconds <= 0:
        raise ValueError("auth_max_age_seconds must be positive")
    if client_max_size <= 0:
        raise ValueError("client_max_size must be positive")

    settings_service = service or MiniAppSettingsService()
    market_service = market_overview or MarketOverviewService(settings_service)
    action_service = admin_actions or MiniAppAdminActions.from_settings_service(
        settings_service,
        backup_callback=backup_callback,
        restart_callback=restart_callback,
    )
    origins = _normalize_origins(allowed_origins)

    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if request.method == "OPTIONS":
            if origin and origins and origin not in origins:
                return _error_response(
                    403, "ORIGIN_NOT_ALLOWED", "Этот источник не разрешён."
                )
            response = web.Response(status=204)
        else:
            response = await handler(request)

        if origin and origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                f"Content-Type, {INIT_DATA_HEADER}"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, PUT, POST, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    @web.middleware
    async def error_middleware(request: web.Request, handler):
        try:
            return await handler(request)
        except TelegramInitDataError as error:
            return _error_response(401, error.code, str(error))
        except AdminActionError as error:
            return _error_response(
                error.status,
                error.code,
                str(error),
                field=error.field,
            )
        except SettingsValidationError as error:
            return _error_response(
                400, error.code, str(error), field=error.field
            )
        except PermissionError as error:
            return _error_response(403, "ACCESS_DENIED", str(error))
        except web.HTTPException:
            raise
        except json.JSONDecodeError:
            return _error_response(400, "INVALID_JSON", "Некорректный JSON.")
        except Exception:
            LOGGER.exception("Unhandled Mini App API error")
            return _error_response(
                500,
                "INTERNAL_ERROR",
                "Не удалось обработать запрос. Попробуйте ещё раз.",
            )

    app = web.Application(
        middlewares=[error_middleware, cors_middleware],
        client_max_size=client_max_size,
    )
    app["mini_app_bot_token"] = bot_token
    app["mini_app_auth_max_age_seconds"] = int(auth_max_age_seconds)
    app["mini_app_settings_service"] = settings_service
    app["mini_app_market_overview"] = market_service
    app["mini_app_admin_actions"] = action_service

    def authenticated_user(request: web.Request) -> TelegramUser:
        return validate_init_data(
            request.headers.get(INIT_DATA_HEADER, ""),
            request.app["mini_app_bot_token"],
            max_age_seconds=request.app["mini_app_auth_max_age_seconds"],
        )

    async def json_object(request: web.Request) -> dict:
        if request.content_type != "application/json":
            raise AdminActionError(
                "Ожидается Content-Type application/json.",
                code="UNSUPPORTED_MEDIA_TYPE",
                status=415,
            )
        try:
            body = await request.json(loads=json.loads)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise AdminActionError(
                "Некорректный JSON.",
                code="INVALID_JSON",
            ) from error
        if not isinstance(body, dict):
            raise AdminActionError(
                "Ожидается JSON-объект.",
                code="INVALID_JSON_OBJECT",
            )
        return body

    def enriched_envelope(user: TelegramUser, envelope: dict) -> dict:
        settings = envelope.get("settings")
        admin = settings.get("admin") if isinstance(settings, dict) else None
        if isinstance(admin, dict):
            admin["capabilities"] = action_service.capabilities(user)
        return envelope

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "telegram-mini-app"})

    async def get_settings(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        envelope = request.app["mini_app_settings_service"].read_settings(user)
        return web.json_response(enriched_envelope(user, envelope))

    async def get_market_overview(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        overview = await asyncio.to_thread(
            request.app["mini_app_market_overview"].read_overview,
            user,
        )
        return web.json_response(overview)

    async def put_settings(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        if "settings" not in body:
            return _error_response(
                400,
                "SETTINGS_REQUIRED",
                "В теле запроса отсутствует объект settings.",
                field="settings",
            )
        envelope = request.app["mini_app_settings_service"].save_settings(
            user, body["settings"]
        )
        return web.json_response(enriched_envelope(user, envelope))

    async def create_confirmation(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = action_service.create_confirmation(
            user,
            action=body.get("action"),
            target_telegram_id=body.get("telegramId"),
        )
        return web.json_response(result, status=201)

    async def put_access_mode(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = action_service.set_public_access(
            user,
            public_access_enabled=body.get("publicAccessEnabled"),
            confirmation_token=body.get("confirmationToken"),
            confirmation_text=body.get("confirmationText"),
        )
        return web.json_response({"result": result})

    async def add_allowlist(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = action_service.add_allowlist(
            user,
            target_telegram_id=body.get("telegramId"),
            name=body.get("name"),
            username=body.get("username"),
            confirmation_token=body.get("confirmationToken"),
            confirmation_text=body.get("confirmationText"),
        )
        return web.json_response({"result": result}, status=201)

    async def remove_allowlist(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = action_service.remove_allowlist(
            user,
            target_telegram_id=request.match_info.get("telegram_id"),
            confirmation_token=body.get("confirmationToken"),
            confirmation_text=body.get("confirmationText"),
        )
        return web.json_response({"result": result})

    async def create_backup(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = await action_service.create_backup(
            user,
            confirmation_token=body.get("confirmationToken"),
            confirmation_text=body.get("confirmationText"),
        )
        return web.json_response({"result": result}, status=202)

    async def restart_bot(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        body = await json_object(request)
        result = await action_service.restart_bot(
            user,
            confirmation_token=body.get("confirmationToken"),
            confirmation_text=body.get("confirmationText"),
        )
        return web.json_response({"result": result}, status=202)

    async def options(_request: web.Request) -> web.Response:
        return web.Response(status=204)

    app.router.add_get("/healthz", health)
    app.router.add_get("/api/mini-app/settings", get_settings)
    app.router.add_get("/api/mini-app/market-overview", get_market_overview)
    app.router.add_put("/api/mini-app/settings", put_settings)
    app.router.add_post(
        "/api/mini-app/admin/confirmations", create_confirmation
    )
    app.router.add_put("/api/mini-app/admin/access", put_access_mode)
    app.router.add_post("/api/mini-app/admin/allowlist", add_allowlist)
    app.router.add_delete(
        "/api/mini-app/admin/allowlist/{telegram_id}", remove_allowlist
    )
    app.router.add_post("/api/mini-app/admin/backup", create_backup)
    app.router.add_post("/api/mini-app/admin/restart", restart_bot)
    app.router.add_route("OPTIONS", "/{tail:.*}", options)
    return app
