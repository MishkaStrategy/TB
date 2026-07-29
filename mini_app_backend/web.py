"""aiohttp application for the Telegram Mini App settings API."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable

from aiohttp import web

from .auth import TelegramInitDataError, validate_init_data
from .service import MiniAppSettingsService, SettingsValidationError

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
    return frozenset(str(value).strip().rstrip("/") for value in values if str(value).strip())


def create_mini_app_application(
    *,
    bot_token: str,
    service: MiniAppSettingsService | None = None,
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
            response.headers["Access-Control-Allow-Methods"] = "GET, PUT, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        return response

    @web.middleware
    async def error_middleware(request: web.Request, handler):
        try:
            return await handler(request)
        except TelegramInitDataError as error:
            return _error_response(401, error.code, str(error))
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

    def authenticated_user(request: web.Request):
        return validate_init_data(
            request.headers.get(INIT_DATA_HEADER, ""),
            request.app["mini_app_bot_token"],
            max_age_seconds=request.app["mini_app_auth_max_age_seconds"],
        )

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "telegram-mini-app"})

    async def get_settings(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        envelope = request.app["mini_app_settings_service"].read_settings(user)
        return web.json_response(envelope)

    async def put_settings(request: web.Request) -> web.Response:
        user = authenticated_user(request)
        if request.content_type != "application/json":
            return _error_response(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                "Ожидается Content-Type application/json.",
            )
        try:
            body = await request.json(loads=json.loads)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return _error_response(400, "INVALID_JSON", "Некорректный JSON.")
        if not isinstance(body, dict) or "settings" not in body:
            return _error_response(
                400,
                "SETTINGS_REQUIRED",
                "В теле запроса отсутствует объект settings.",
                field="settings",
            )
        envelope = request.app["mini_app_settings_service"].save_settings(
            user, body["settings"]
        )
        return web.json_response(envelope)

    app.router.add_get("/healthz", health)
    app.router.add_get("/api/mini-app/settings", get_settings)
    app.router.add_put("/api/mini-app/settings", put_settings)
    app.router.add_route("OPTIONS", "/{tail:.*}", lambda _request: web.Response(status=204))
    return app
