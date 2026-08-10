"""Mapping and validation between the Mini App JSON model and bot stores."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from alerts.funding_alerts import parse_threshold
from alerts.funding_exchange_store import FundingExchangeStore
from alerts.funding_quarter_hour import FundingAlertStore, parse_interval_minutes
from alerts.fvg_store import (
    FvgAlertSettings,
    instrument_key,
    split_instrument_key,
)
from config import (
    ADMIN_TELEGRAM_IDS,
    ALLOWED_TELEGRAM_IDS,
    MAX_SYMBOLS_PER_USER,
    PUBLIC_ACCESS_ENABLED,
    is_admin,
)
from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from database.user_preferences import UserPreferences
from exchanges.funding import normalize_exchange, normalize_exchanges
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES

from .auth import TelegramUser

UTC = timezone.utc
_SYMBOL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_FVG_EXCHANGES = frozenset(("bitunix", "binance", "bybit", "bingx", "bitget", "gate"))


class SettingsValidationError(ValueError):
    """A field-addressable validation error suitable for an API response."""

    def __init__(self, message: str, *, code: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.field = field


def _object(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise SettingsValidationError(
            "Ожидался JSON-объект.", code="INVALID_OBJECT", field=field
        )
    return value


def _list(value: Any, field: str) -> list:
    if not isinstance(value, list):
        raise SettingsValidationError(
            "Ожидался JSON-массив.", code="INVALID_LIST", field=field
        )
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsValidationError(
            "Значение должно быть true или false.",
            code="INVALID_BOOLEAN",
            field=field,
        )
    return value


def _choice(value: Any, choices: set[str], field: str, code: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise SettingsValidationError(
            f"Допустимые значения: {', '.join(sorted(choices))}.",
            code=code,
            field=field,
        )
    return value


def _decimal_boundary(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().replace(",", ".")
    try:
        parsed = Decimal(normalized)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise SettingsValidationError(
            "Значение должно быть числом.", code="INVALID_DECIMAL", field=field
        ) from error
    if not parsed.is_finite() or parsed < 0:
        raise SettingsValidationError(
            "Значение должно быть конечным неотрицательным числом.",
            code="INVALID_DECIMAL",
            field=field,
        )
    return format(parsed, "f")


def _normalize_symbol(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise SettingsValidationError(
            "Инструмент должен быть строкой.", code="INVALID_SYMBOL", field=field
        )
    symbol = value.strip().upper().replace("/", "")
    if not 5 <= len(symbol) <= 20 or any(char not in _SYMBOL_CHARS for char in symbol):
        raise SettingsValidationError(
            "Укажите инструмент из 5–20 латинских букв и цифр, например BTCUSDT.",
            code="INVALID_SYMBOL",
            field=field,
        )
    return symbol


def _normalize_fvg_exchange(value: Any, field: str) -> str:
    try:
        exchange = normalize_exchange(str(value or "bitunix"))
    except (TypeError, ValueError) as error:
        raise SettingsValidationError(
            "Неподдерживаемая биржа FVG.",
            code="INVALID_FVG_EXCHANGE",
            field=field,
        ) from error
    if exchange not in _FVG_EXCHANGES:
        raise SettingsValidationError(
            "Неподдерживаемая биржа FVG.",
            code="INVALID_FVG_EXCHANGE",
            field=field,
        )
    return exchange


def _normalize_timeframes(value: Any, field: str) -> list[str]:
    rows = _list(value if value is not None else ["15m"], field)
    selected = {str(item).strip().lower() for item in rows if str(item).strip()}
    invalid = selected.difference(CONFIRMED_TIMEFRAMES)
    if invalid:
        raise SettingsValidationError(
            f"Неподдерживаемые таймфреймы: {', '.join(sorted(invalid))}.",
            code="INVALID_FVG_TIMEFRAMES",
            field=field,
        )
    ordered = [item for item in CONFIRMED_TIMEFRAMES if item in selected]
    if not ordered:
        raise SettingsValidationError(
            "Выберите хотя бы один таймфрейм FVG.",
            code="FVG_TIMEFRAME_REQUIRED",
            field=field,
        )
    return ordered


def _scope(value: Any, field: str) -> dict:
    source = _object(value, field)
    return {
        # 1.3.4 removed pre-FVG from runtime. Keep the storage key false only
        # for schema compatibility; the Mini App API no longer exposes it.
        "apply_to_pre_fvg": False,
        "apply_to_confirmed_fvg": _boolean(
            source.get("confirmedFvg"), f"{field}.confirmedFvg"
        ),
        "apply_to_bullish": _boolean(source.get("bullish"), f"{field}.bullish"),
        "apply_to_bearish": _boolean(source.get("bearish"), f"{field}.bearish"),
    }


def _normalize_settings_payload(payload: Any, *, max_symbols: int) -> dict:
    root = _object(payload, "settings")
    general = _object(root.get("general"), "settings.general")
    fvg = _object(root.get("fvg"), "settings.fvg")
    funding = _object(root.get("funding"), "settings.funding")
    admin = _object(root.get("admin", {}), "settings.admin")

    normalized_general = {
        "language": _choice(
            general.get("language"),
            {"ru", "en"},
            "settings.general.language",
            "INVALID_LANGUAGE",
        ),
        "message_mode": _choice(
            general.get("messageMode"),
            {"compact", "detailed"},
            "settings.general.messageMode",
            "INVALID_MESSAGE_MODE",
        ),
    }

    symbol_rows = _list(fvg.get("symbols"), "settings.fvg.symbols")
    if len(symbol_rows) > max_symbols:
        raise SettingsValidationError(
            f"Можно добавить не более {max_symbols} инструментов.",
            code="FVG_SYMBOL_LIMIT",
            field="settings.fvg.symbols",
        )

    symbols: dict[str, dict] = {}
    for index, raw_item in enumerate(symbol_rows):
        base_field = f"settings.fvg.symbols[{index}]"
        item = _object(raw_item, base_field)
        exchange = _normalize_fvg_exchange(
            item.get("exchange", "bitunix"), f"{base_field}.exchange"
        )
        symbol = _normalize_symbol(item.get("symbol"), f"{base_field}.symbol")
        timeframes = _normalize_timeframes(
            item.get("timeframes", ["15m"]), f"{base_field}.timeframes"
        )
        key = instrument_key(exchange, symbol)
        supplied_key = item.get("key")
        if supplied_key not in (None, "", key):
            raise SettingsValidationError(
                "Ключ инструмента не соответствует бирже и символу.",
                code="INVALID_FVG_INSTRUMENT_KEY",
                field=f"{base_field}.key",
            )
        if key in symbols:
            raise SettingsValidationError(
                f"Инструмент {exchange}:{symbol} указан несколько раз.",
                code="DUPLICATE_INSTRUMENT",
                field=f"{base_field}.symbol",
            )

        price = _object(item.get("priceFilter"), f"{base_field}.priceFilter")
        price_min = _decimal_boundary(
            price.get("min"), f"{base_field}.priceFilter.min"
        )
        price_max = _decimal_boundary(
            price.get("max"), f"{base_field}.priceFilter.max"
        )
        if (
            price_min is not None
            and price_max is not None
            and Decimal(price_min) > Decimal(price_max)
        ):
            raise SettingsValidationError(
                "Минимальная цена не может быть выше максимальной.",
                code="INVALID_PRICE_RANGE",
                field=f"{base_field}.priceFilter.min",
            )
        price_scope = _scope(
            price.get("scope"), f"{base_field}.priceFilter.scope"
        )

        size = _object(item.get("sizeFilter"), f"{base_field}.sizeFilter")
        size_min = _decimal_boundary(size.get("min"), f"{base_field}.sizeFilter.min")
        size_unit = _choice(
            size.get("unit"),
            {"USD", "PERCENT"},
            f"{base_field}.sizeFilter.unit",
            "INVALID_SIZE_UNIT",
        )
        size_scope = _scope(size.get("scope"), f"{base_field}.sizeFilter.scope")

        symbols[key] = {
            "exchange": exchange,
            "symbol": symbol,
            "timeframes": timeframes,
            "enabled": _boolean(item.get("enabled"), f"{base_field}.enabled"),
            "price_filter": {
                "enabled": _boolean(
                    price.get("enabled"), f"{base_field}.priceFilter.enabled"
                ),
                "min": price_min,
                "max": price_max,
                **price_scope,
            },
            "size_filter": {
                "enabled": _boolean(
                    size.get("enabled"), f"{base_field}.sizeFilter.enabled"
                ),
                "unit": size_unit,
                "min": size_min,
                "max": None,
                **size_scope,
            },
        }

    normalized_fvg = {
        "enabled": _boolean(fvg.get("enabled"), "settings.fvg.enabled"),
        "notify_confirmed_fvg": _boolean(
            fvg.get("notifyConfirmedFvg"), "settings.fvg.notifyConfirmedFvg"
        ),
        "notify_pre_fvg": False,
        "bullish_enabled": _boolean(
            fvg.get("bullishEnabled"), "settings.fvg.bullishEnabled"
        ),
        "bearish_enabled": _boolean(
            fvg.get("bearishEnabled"), "settings.fvg.bearishEnabled"
        ),
        "symbols": symbols,
    }

    try:
        interval = parse_interval_minutes(funding.get("intervalMinutes"))
    except ValueError as error:
        raise SettingsValidationError(
            str(error),
            code="INVALID_FUNDING_INTERVAL",
            field="settings.funding.intervalMinutes",
        ) from error
    try:
        threshold = parse_threshold(funding.get("threshold"))
    except ValueError as error:
        raise SettingsValidationError(
            str(error),
            code="INVALID_FUNDING_THRESHOLD",
            field="settings.funding.threshold",
        ) from error

    positive = _boolean(
        funding.get("notifyPositive"), "settings.funding.notifyPositive"
    )
    negative = _boolean(
        funding.get("notifyNegative"), "settings.funding.notifyNegative"
    )
    if not positive and not negative:
        raise SettingsValidationError(
            "Нужно выбрать хотя бы одно направление фандинга.",
            code="FUNDING_DIRECTION_REQUIRED",
            field="settings.funding.notifyPositive",
        )
    try:
        exchanges = normalize_exchanges(
            _list(funding.get("exchanges"), "settings.funding.exchanges")
        )
    except ValueError as error:
        raise SettingsValidationError(
            str(error),
            code="INVALID_FUNDING_EXCHANGES",
            field="settings.funding.exchanges",
        ) from error

    normalized_funding = {
        "enabled": _boolean(funding.get("enabled"), "settings.funding.enabled"),
        "interval_minutes": interval,
        "threshold": threshold,
        "notify_positive": positive,
        "notify_negative": negative,
        "exchanges": exchanges,
    }

    normalized_admin = {}
    if "publicAccessEnabled" in admin:
        normalized_admin["public_access_enabled"] = _boolean(
            admin.get("publicAccessEnabled"),
            "settings.admin.publicAccessEnabled",
        )

    return {
        "general": normalized_general,
        "fvg": normalized_fvg,
        "funding": normalized_funding,
        "admin": normalized_admin,
    }


class MiniAppSettingsService:
    """Read and write Mini App settings through the existing bot stores."""

    def __init__(
        self,
        *,
        preferences: UserPreferences | None = None,
        fvg_settings: FvgAlertSettings | None = None,
        funding_settings: FundingAlertStore | None = None,
        funding_exchanges: FundingExchangeStore | None = None,
        runtime_settings: RuntimeSettings | None = None,
        access_registry: AccessRegistry | None = None,
        activity_registry: UserActivityRegistry | None = None,
        admin_checker: Callable[[int], bool] = is_admin,
        env_allowed_ids=frozenset(ALLOWED_TELEGRAM_IDS),
        env_admin_ids=frozenset(ADMIN_TELEGRAM_IDS),
        public_access_default: bool = PUBLIC_ACCESS_ENABLED,
        max_symbols_per_user: int = MAX_SYMBOLS_PER_USER,
        diagnostics_provider: Callable[[], dict] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.preferences = preferences or UserPreferences()
        self.fvg_settings = fvg_settings or FvgAlertSettings()
        self.funding_settings = funding_settings or FundingAlertStore()
        self.funding_exchanges = funding_exchanges or FundingExchangeStore(
            self.funding_settings.path
        )
        self.runtime_settings = runtime_settings or RuntimeSettings()
        self.access_registry = access_registry or AccessRegistry()
        self.activity_registry = activity_registry or UserActivityRegistry()
        self.admin_checker = admin_checker
        self.env_allowed_ids = frozenset(int(value) for value in env_allowed_ids)
        self.env_admin_ids = frozenset(int(value) for value in env_admin_ids)
        self.public_access_default = bool(public_access_default)
        self.max_symbols_per_user = int(max_symbols_per_user)
        if self.max_symbols_per_user <= 0:
            raise ValueError("max_symbols_per_user must be positive")
        self.diagnostics_provider = diagnostics_provider or self._default_diagnostics
        self.now = now or (lambda: datetime.now(UTC))

    def public_access_enabled(self) -> bool:
        return self.runtime_settings.public_access_enabled(
            default=self.public_access_default
        )

    def is_authorized(self, telegram_id: int) -> bool:
        telegram_id = int(telegram_id)
        return bool(
            self.public_access_enabled()
            or telegram_id in self.env_allowed_ids
            or telegram_id in self.env_admin_ids
            or self.access_registry.is_allowed(telegram_id)
            or self.admin_checker(telegram_id)
        )

    def read_settings(self, user: TelegramUser) -> dict:
        if not self.is_authorized(user.id):
            raise PermissionError("Доступ к Mini App не разрешён.")
        self.activity_registry.touch(user)
        return self._envelope(user)

    def save_settings(self, user: TelegramUser, settings_payload: Any) -> dict:
        if not self.is_authorized(user.id):
            raise PermissionError("Доступ к Mini App не разрешён.")
        normalized = _normalize_settings_payload(
            settings_payload, max_symbols=self.max_symbols_per_user
        )

        current_general = self.preferences.ensure(user.id)
        if current_general["language"] != normalized["general"]["language"]:
            self.preferences.set_language(user.id, normalized["general"]["language"])
        if current_general["message_mode"] != normalized["general"]["message_mode"]:
            self.preferences.set_message_mode(
                user.id, normalized["general"]["message_mode"]
            )

        self._replace_fvg_user(user.id, normalized["fvg"])
        self._save_funding(user.id, normalized["funding"])

        if self.admin_checker(user.id) and "public_access_enabled" in normalized["admin"]:
            self.runtime_settings.set_public_access_enabled(
                normalized["admin"]["public_access_enabled"]
            )

        self.activity_registry.touch(user)
        return self._envelope(user)

    def _replace_fvg_user(self, telegram_id: int, normalized_user: dict) -> None:
        def mutate(data):
            data.setdefault("users", {})[str(telegram_id)] = normalized_user

        # FvgAlertSettings owns the transaction and schema-version write. The
        # full payload is validated before this single atomic JSON replacement.
        self.fvg_settings._transaction(mutate)

    def _save_funding(self, telegram_id: int, desired: dict) -> None:
        current = self.funding_settings.user(telegram_id)
        if (
            current["notify_positive"] != desired["notify_positive"]
            or current["notify_negative"] != desired["notify_negative"]
        ):
            self.funding_settings.set_directions(
                telegram_id,
                notify_positive=desired["notify_positive"],
                notify_negative=desired["notify_negative"],
            )
        current = self.funding_settings.user(telegram_id)
        if current["interval_minutes"] != desired["interval_minutes"]:
            self.funding_settings.set_interval(
                telegram_id, desired["interval_minutes"]
            )
        current = self.funding_settings.user(telegram_id)
        if current["threshold"] != desired["threshold"]:
            self.funding_settings.set_threshold(telegram_id, desired["threshold"])
        selected = self.funding_exchanges.selected(telegram_id)
        if tuple(selected) != tuple(desired["exchanges"]):
            self.funding_exchanges.set_selected(telegram_id, desired["exchanges"])
        current = self.funding_settings.user(telegram_id)
        if current["enabled"] != desired["enabled"]:
            self.funding_settings.set_enabled(telegram_id, desired["enabled"])

    def _envelope(self, user: TelegramUser) -> dict:
        preferences = self.preferences.ensure(
            user.id,
            language=(
                "en"
                if str(user.language_code or "").lower().startswith("en")
                else "ru"
            ),
        )
        fvg = self.fvg_settings.user(user.id)
        funding = self.funding_settings.user(user.id)
        admin_available = bool(self.admin_checker(user.id))

        return {
            "settings": {
                "general": {
                    "language": preferences["language"],
                    "messageMode": preferences["message_mode"],
                },
                "fvg": {
                    "enabled": bool(fvg.get("enabled", False)),
                    "notifyConfirmedFvg": bool(
                        fvg.get("notify_confirmed_fvg", True)
                    ),
                    "bullishEnabled": bool(fvg.get("bullish_enabled", True)),
                    "bearishEnabled": bool(fvg.get("bearish_enabled", True)),
                    "symbols": [
                        self._serialize_symbol(key, config)
                        for key, config in fvg.get("symbols", {}).items()
                    ],
                },
                "funding": {
                    "enabled": funding["enabled"],
                    "intervalMinutes": funding["interval_minutes"],
                    "threshold": format(funding["threshold"], "f"),
                    "notifyPositive": funding["notify_positive"],
                    "notifyNegative": funding["notify_negative"],
                    "exchanges": list(self.funding_exchanges.selected(user.id)),
                    "nextCheckAt": (
                        funding["next_check_at"].astimezone(UTC).isoformat()
                        if funding["next_check_at"] is not None
                        else None
                    ),
                },
                "admin": self._admin_settings(admin_available),
            },
            "user": {
                "id": user.id,
                "firstName": user.first_name,
                **({"username": user.username} if user.username else {}),
            },
            "limits": {"maxFvgSymbols": self.max_symbols_per_user},
            "source": "api",
            "updatedAt": self.now().astimezone(UTC).isoformat(),
        }

    @staticmethod
    def _serialize_scope(config: dict) -> dict:
        return {
            "confirmedFvg": bool(config.get("apply_to_confirmed_fvg", True)),
            "bullish": bool(config.get("apply_to_bullish", True)),
            "bearish": bool(config.get("apply_to_bearish", True)),
        }

    @classmethod
    def _serialize_symbol(cls, key: str, config: dict) -> dict:
        key_exchange, key_symbol = split_instrument_key(key)
        exchange = str(config.get("exchange") or key_exchange)
        symbol = str(config.get("symbol") or key_symbol)
        timeframes = [
            timeframe
            for timeframe in CONFIRMED_TIMEFRAMES
            if timeframe in config.get("timeframes", ("15m",))
        ] or ["15m"]
        normalized_key = instrument_key(exchange, symbol)
        price = config.get("price_filter", {})
        size = config.get("size_filter", {})
        return {
            "key": normalized_key,
            "exchange": exchange,
            "symbol": symbol,
            "timeframes": timeframes,
            "enabled": bool(config.get("enabled", True)),
            "priceFilter": {
                "enabled": bool(price.get("enabled", False)),
                "min": price.get("min"),
                "max": price.get("max"),
                "scope": cls._serialize_scope(price),
            },
            "sizeFilter": {
                "enabled": bool(size.get("enabled", False)),
                "unit": size.get("unit", "USD"),
                "min": size.get("min"),
                "scope": cls._serialize_scope(size),
            },
        }

    def _admin_settings(self, available: bool) -> dict:
        if not available:
            return {
                "available": False,
                "publicAccessEnabled": False,
                "allowedUsers": [],
                "diagnostics": {
                    "websocket": "unknown",
                    "outbox": 0,
                    "deliveryFailures": 0,
                    "databases": "unknown",
                    "release": "unknown",
                },
            }
        return {
            "available": True,
            "publicAccessEnabled": self.public_access_enabled(),
            "allowedUsers": self._allowed_users(),
            "diagnostics": self.diagnostics_provider(),
        }

    def _allowed_users(self) -> list[dict]:
        runtime = self.access_registry.users(status="allowed")
        activity = self.activity_registry.users()
        ids = sorted(self.env_allowed_ids | {int(value) for value in runtime})
        users = []
        for telegram_id in ids:
            record = runtime.get(str(telegram_id), {})
            tracked = activity.get(str(telegram_id), {})
            name = record.get("name") or tracked.get("name") or "Без имени"
            username = record.get("username") or tracked.get("username")
            item = {
                "telegramId": telegram_id,
                "name": name,
                "source": "env" if telegram_id in self.env_allowed_ids else "runtime",
            }
            if username:
                item["username"] = username
            users.append(item)
        return users

    def _default_diagnostics(self) -> dict:
        websocket = "unknown"
        outbox = 0
        delivery_failures = 0
        database_paths = [Path(self.funding_settings.path)]
        try:
            from alerts.scheduler_15m import get_fvg_service

            event_store = get_fvg_service().event_store
            health = event_store.health()
            connected = health.get("ws_connected")
            websocket = (
                "connected"
                if connected is True
                else "disconnected"
                if connected is False
                else "unknown"
            )
            outbox = int(health.get("outbox") or 0)
            delivery_failures = int(health.get("delivery_failures") or 0)
            database_paths.append(Path(event_store.path))
        except Exception:
            pass

        checks = [self._quick_check(path) for path in database_paths]
        if checks and all(value == "ok" for value in checks):
            database_status = "ok"
        elif any(value == "warning" for value in checks):
            database_status = "warning"
        else:
            database_status = "unknown"

        version_path = Path(__file__).resolve().parents[1] / "VERSION"
        try:
            release = version_path.read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            release = "unknown"
        return {
            "websocket": websocket,
            "outbox": outbox,
            "deliveryFailures": delivery_failures,
            "databases": database_status,
            "release": release,
        }

    @staticmethod
    def _quick_check(path: Path) -> str:
        if not path.exists():
            return "unknown"
        try:
            with sqlite3.connect(path, timeout=5) as connection:
                row = connection.execute("PRAGMA quick_check").fetchone()
            return "ok" if row and row[0] == "ok" else "warning"
        except (OSError, sqlite3.Error):
            return "warning"
