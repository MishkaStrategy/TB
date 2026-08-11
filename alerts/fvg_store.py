"""Persistence facade for FVG preferences and event history."""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - production and CI are Unix-like.
    fcntl = None

from alerts.fvg_detector import price_allowed, size_allowed
from alerts.fvg_models import FvgDirection, FvgEvent, FvgEventType
from alerts.sqlite_event_store import FvgEventStore
from config import MAX_ACTIVE_SYMBOLS, MAX_SYMBOLS_PER_USER
from exchanges.funding import normalize_exchange
from exchanges.fvg_candles import (
    CONFIRMED_TIMEFRAMES,
    is_bitcoin_symbol,
    normalize_fvg_symbol,
)


UTC = timezone.utc
_STORE_LOCKS: dict[str, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


class AtomicJsonStore:
    """Atomic JSON storage retained for low-frequency user preferences."""

    def __init__(self, path: str):
        self.path = Path(path)
        resolved = str(self.path.resolve())
        with _STORE_LOCKS_GUARD:
            self._lock = _STORE_LOCKS.setdefault(resolved, threading.RLock())

    @contextmanager
    def transaction_lock(self):
        """Serialize read-modify-write transactions across threads and processes."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if fcntl is None:
                yield
                return
            lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
            with lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            return value if isinstance(value, dict) else {}

    def write(self, data: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(
                f"{self.path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)


def instrument_key(exchange: str, symbol: str) -> str:
    """Keep legacy Bitunix keys while namespacing every other exchange."""
    exchange = normalize_exchange(exchange)
    symbol = normalize_fvg_symbol(symbol)
    return symbol if exchange == "bitunix" else f"{exchange}|{symbol}"


def split_instrument_key(value: str) -> tuple[str, str]:
    if "|" not in str(value):
        return "bitunix", normalize_fvg_symbol(value)
    exchange, symbol = str(value).split("|", 1)
    return normalize_exchange(exchange), normalize_fvg_symbol(symbol)


def _normalize_timeframes(values) -> list[str]:
    selected = {
        str(value).strip().lower()
        for value in (values or ())
        if str(value).strip()
    }
    invalid = selected.difference(CONFIRMED_TIMEFRAMES)
    if invalid:
        raise ValueError(f"Неподдерживаемые таймфреймы: {', '.join(sorted(invalid))}")
    ordered = [value for value in CONFIRMED_TIMEFRAMES if value in selected]
    if not ordered:
        raise ValueError("Выберите хотя бы один таймфрейм.")
    return ordered


def _symbol_defaults(
    exchange: str = "bitunix",
    symbol: str = "BTCUSDT",
    timeframes=None,
) -> dict:
    return {
        "exchange": normalize_exchange(exchange),
        "symbol": normalize_fvg_symbol(symbol),
        "timeframes": _normalize_timeframes(timeframes or ("15m",)),
        "enabled": True,
        "created_at": datetime.now(UTC).isoformat(),
        "price_filter": {
            "enabled": False,
            "min": None,
            "max": None,
            "apply_to_pre_fvg": True,
            "apply_to_confirmed_fvg": True,
            "apply_to_bullish": True,
            "apply_to_bearish": True,
        },
        "size_filter": {
            "enabled": False,
            "unit": "USD",
            "min": None,
            "max": None,
            "apply_to_pre_fvg": True,
            "apply_to_confirmed_fvg": True,
            "apply_to_bullish": True,
            "apply_to_bearish": True,
        },
    }


def _user_defaults() -> dict:
    return {
        "enabled": False,
        "notify_confirmed_fvg": True,
        "notify_pre_fvg": False,
        "bullish_enabled": True,
        "bearish_enabled": True,
        "symbols": {},
    }


def _parse_boundary(value, *, label: str):
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"Некорректная граница {label}") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(
            f"Граница {label} должна быть конечным неотрицательным числом"
        )
    return parsed


def _decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("NaN")


def _normalize_config(key: str, value: dict | None) -> tuple[str, dict]:
    value = deepcopy(value) if isinstance(value, dict) else {}
    exchange = value.get("exchange")
    symbol = value.get("symbol")
    if exchange is None or symbol is None:
        key_exchange, key_symbol = split_instrument_key(key)
        exchange = exchange or key_exchange
        symbol = symbol or key_symbol
    normalized_key = instrument_key(exchange, symbol)
    defaults = _symbol_defaults(exchange, symbol, value.get("timeframes") or ("15m",))
    defaults.update(value)
    defaults["exchange"] = normalize_exchange(exchange)
    defaults["symbol"] = normalize_fvg_symbol(symbol)
    defaults["timeframes"] = _normalize_timeframes(
        defaults.get("timeframes") or ("15m",)
    )
    defaults["enabled"] = bool(defaults.get("enabled", True))
    for filter_name in ("price_filter", "size_filter"):
        merged = deepcopy(_symbol_defaults(exchange, symbol)[filter_name])
        if isinstance(value.get(filter_name), dict):
            merged.update(value[filter_name])
        defaults[filter_name] = merged
    return normalized_key, defaults


def _normalize_user(value: dict | None) -> dict:
    defaults = _user_defaults()
    if isinstance(value, dict):
        for key in (
            "enabled",
            "notify_confirmed_fvg",
            "notify_pre_fvg",
            "bullish_enabled",
            "bearish_enabled",
        ):
            if key in value:
                defaults[key] = bool(value[key])
        raw_symbols = value.get("symbols", {})
        if isinstance(raw_symbols, dict):
            defaults["symbols"] = dict(
                _normalize_config(key, config)
                for key, config in raw_symbols.items()
            )
    return defaults


class FvgAlertSettings:
    SCHEMA_VERSION = 3

    def __init__(self, path: str = "data/fvg_alert_settings.json"):
        self.store = AtomicJsonStore(path)
        self.path = self.store.path

    def _read(self) -> dict:
        raw = self.store.read()
        if raw.get("schema_version") == self.SCHEMA_VERSION:
            return {
                **raw,
                "users": {
                    str(chat_id): _normalize_user(user)
                    for chat_id, user in raw.get("users", {}).items()
                },
            }

        if raw.get("schema_version") == 2:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "users": {
                    str(chat_id): _normalize_user(user)
                    for chat_id, user in raw.get("users", {}).items()
                },
                "legacy_last_event_key": raw.get("legacy_last_event_key"),
                "legacy_last_pre_event_key": raw.get("legacy_last_pre_event_key"),
            }

        users = {}
        known_ids = set(raw.get("enabled_chat_ids", [])) | set(
            raw.get("pre_enabled_chat_ids", [])
        )
        for chat_id in known_ids:
            user = _user_defaults()
            # Preserve the legacy implicit-BTC contract only while migrating
            # users that were already present in the pre-schema settings file.
            user["symbols"] = {
                instrument_key("bitunix", "BTCUSDT"): _symbol_defaults()
            }
            user["enabled"] = True
            user["notify_confirmed_fvg"] = chat_id in raw.get(
                "enabled_chat_ids", []
            )
            user["notify_pre_fvg"] = chat_id in raw.get(
                "pre_enabled_chat_ids", []
            )
            users[str(chat_id)] = user
        return {
            "schema_version": self.SCHEMA_VERSION,
            "users": users,
            "legacy_last_event_key": raw.get("last_event_key"),
            "legacy_last_pre_event_key": raw.get("last_pre_event_key"),
        }

    def _write(self, data: dict) -> None:
        data["schema_version"] = self.SCHEMA_VERSION
        self.store.write(data)

    def _transaction(self, mutate):
        with self.store.transaction_lock():
            data = self._read()
            result = mutate(data)
            self._write(data)
            return result

    def user(self, chat_id: int) -> dict:
        return deepcopy(
            self._read().get("users", {}).get(str(chat_id), _user_defaults())
        )

    def update_user(self, chat_id: int, **values) -> None:
        def mutate(data):
            data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            ).update(values)

        self._transaction(mutate)

    def enabled_chat_ids(self):
        return frozenset(
            int(key)
            for key, value in self._read().get("users", {}).items()
            if value.get("enabled") and value.get("notify_confirmed_fvg", True)
        )

    def pre_enabled_chat_ids(self):
        return frozenset(
            int(key)
            for key, value in self._read().get("users", {}).items()
            if value.get("enabled")
            and value.get("notify_pre_fvg", False)
            and any(
                config.get("enabled", True)
                and is_bitcoin_symbol(config.get("symbol", ""))
                and "15m" in config.get("timeframes", ())
                for config in value.get("symbols", {}).values()
            )
        )

    def is_enabled(self, chat_id):
        return bool(self.user(chat_id).get("enabled"))

    def is_pre_enabled(self, chat_id):
        user = self.user(chat_id)
        return bool(user.get("enabled") and user.get("notify_pre_fvg"))

    def set_enabled(self, chat_id, enabled):
        self.update_user(chat_id, enabled=bool(enabled))

    def set_confirmed_enabled(self, chat_id, enabled):
        self.update_user(chat_id, notify_confirmed_fvg=bool(enabled))

    def set_pre_enabled(self, chat_id, enabled):
        self.update_user(chat_id, enabled=True, notify_pre_fvg=bool(enabled))

    def set_direction_enabled(
        self,
        chat_id,
        direction: FvgDirection,
        enabled: bool,
    ):
        key = (
            "bullish_enabled"
            if direction is FvgDirection.BULLISH
            else "bearish_enabled"
        )
        self.update_user(chat_id, **{key: bool(enabled)})

    @staticmethod
    def _find_key(user: dict, value: str, exchange: str | None = None) -> str | None:
        symbols = user.setdefault("symbols", {})
        if value in symbols:
            return value
        if exchange is not None:
            candidate = instrument_key(exchange, value)
            return candidate if candidate in symbols else None
        symbol = normalize_fvg_symbol(value)
        bitunix = instrument_key("bitunix", symbol)
        if bitunix in symbols:
            return bitunix
        matches = [
            key
            for key, config in symbols.items()
            if config.get("symbol") == symbol
        ]
        return matches[0] if len(matches) == 1 else None

    def add_instrument(
        self,
        chat_id: int,
        exchange: str,
        symbol: str,
        timeframes,
    ) -> str:
        key = instrument_key(exchange, symbol)
        normalized_timeframes = _normalize_timeframes(timeframes)

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            symbols = user.setdefault("symbols", {})
            if key in symbols:
                raise ValueError(
                    "Этот инструмент уже добавлен. Измените его таймфреймы в настройках."
                )
            if len(symbols) >= MAX_SYMBOLS_PER_USER:
                raise ValueError(
                    f"Можно добавить не более {MAX_SYMBOLS_PER_USER} инструментов."
                )
            symbols[key] = _symbol_defaults(exchange, symbol, normalized_timeframes)
            user["enabled"] = True
            return key

        return self._transaction(mutate)

    def add_symbol(self, chat_id: int, symbol: str) -> None:
        key = instrument_key("bitunix", symbol)

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            symbols = user.setdefault("symbols", {})
            if key not in symbols and len(symbols) >= MAX_SYMBOLS_PER_USER:
                raise ValueError(
                    f"Можно добавить не более {MAX_SYMBOLS_PER_USER} инструментов."
                )
            symbols.setdefault(key, _symbol_defaults("bitunix", symbol, ("15m",)))

        self._transaction(mutate)

    def update_instrument_timeframes(
        self,
        chat_id: int,
        key: str,
        timeframes,
    ) -> None:
        normalized = _normalize_timeframes(timeframes)

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            resolved = self._find_key(user, key)
            if resolved is None:
                raise ValueError("Инструмент уже удалён или не найден.")
            user["symbols"][resolved]["timeframes"] = normalized

        self._transaction(mutate)

    def set_instrument_enabled(self, chat_id: int, key: str, enabled: bool) -> None:
        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            resolved = self._find_key(user, key)
            if resolved is None:
                raise ValueError("Инструмент уже удалён или не найден.")
            user["symbols"][resolved]["enabled"] = bool(enabled)

        self._transaction(mutate)

    def remove_instrument(self, chat_id: int, key: str) -> None:
        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            resolved = self._find_key(user, key)
            if resolved is not None:
                user.setdefault("symbols", {}).pop(resolved, None)

        self._transaction(mutate)

    def remove_symbol(self, chat_id: int, symbol: str) -> None:
        self.remove_instrument(chat_id, instrument_key("bitunix", symbol))

    def _ensure_filter_instrument(self, user: dict, value: str) -> str:
        resolved = self._find_key(user, value)
        if resolved is not None:
            return resolved
        symbols = user.setdefault("symbols", {})
        if len(symbols) >= MAX_SYMBOLS_PER_USER:
            raise ValueError(
                f"Можно добавить не более {MAX_SYMBOLS_PER_USER} инструментов."
            )
        key = instrument_key("bitunix", value)
        symbols[key] = _symbol_defaults("bitunix", value, ("15m",))
        return key

    def set_price_filter(
        self,
        chat_id: int,
        symbol: str,
        minimum: str | None,
        maximum: str | None,
        enabled: bool = True,
        apply_to_pre: bool = True,
        apply_to_confirmed: bool = True,
        apply_to_bullish: bool = True,
        apply_to_bearish: bool = True,
    ) -> None:
        min_value = _parse_boundary(minimum, label="цены")
        max_value = _parse_boundary(maximum, label="цены")
        if min_value is not None and max_value is not None and min_value > max_value:
            raise ValueError("Минимальная цена не может быть выше максимальной")

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            key = self._ensure_filter_instrument(user, symbol)
            user["symbols"][key]["price_filter"] = {
                "enabled": bool(enabled),
                "min": str(min_value) if min_value is not None else None,
                "max": str(max_value) if max_value is not None else None,
                "apply_to_pre_fvg": bool(apply_to_pre),
                "apply_to_confirmed_fvg": bool(apply_to_confirmed),
                "apply_to_bullish": bool(apply_to_bullish),
                "apply_to_bearish": bool(apply_to_bearish),
            }

        self._transaction(mutate)

    def set_size_filter(
        self,
        chat_id: int,
        symbol: str,
        minimum: str | None,
        maximum: str | None,
        unit: str = "USD",
        enabled: bool = True,
        apply_to_pre: bool = True,
        apply_to_confirmed: bool = True,
        apply_to_bullish: bool = True,
        apply_to_bearish: bool = True,
    ) -> None:
        del maximum
        unit = unit.upper()
        if unit not in {"USD", "PERCENT"}:
            raise ValueError("Единица размера должна быть USD или PERCENT")
        min_value = _parse_boundary(minimum, label="размера FVG")

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            key = self._ensure_filter_instrument(user, symbol)
            user["symbols"][key]["size_filter"] = {
                "enabled": bool(enabled),
                "unit": unit,
                "min": str(min_value) if min_value is not None else None,
                "max": None,
                "apply_to_pre_fvg": bool(apply_to_pre),
                "apply_to_confirmed_fvg": bool(apply_to_confirmed),
                "apply_to_bullish": bool(apply_to_bullish),
                "apply_to_bearish": bool(apply_to_bearish),
            }

        self._transaction(mutate)

    def active_markets(self) -> tuple[tuple[str, str, str], ...]:
        markets: set[tuple[str, str, str]] = set()
        for user in self._read().get("users", {}).values():
            if not user.get("enabled") or not user.get("notify_confirmed_fvg", True):
                continue
            for config in user.get("symbols", {}).values():
                if not config.get("enabled", True):
                    continue
                for timeframe in config.get("timeframes", ("15m",)):
                    markets.add((config["exchange"], config["symbol"], timeframe))
        return tuple(sorted(markets)[:MAX_ACTIVE_SYMBOLS])

    def pre_active_markets(self) -> tuple[tuple[str, str], ...]:
        markets: set[tuple[str, str]] = set()
        for user in self._read().get("users", {}).values():
            if not user.get("enabled") or not user.get("notify_pre_fvg", False):
                continue
            for config in user.get("symbols", {}).values():
                if (
                    config.get("enabled", True)
                    and "15m" in config.get("timeframes", ())
                    and is_bitcoin_symbol(config.get("symbol", ""))
                ):
                    markets.add((config["exchange"], config["symbol"]))
        return tuple(sorted(markets)[:MAX_ACTIVE_SYMBOLS])

    def active_symbols(self) -> frozenset[str]:
        """Bitunix symbols retained for the existing shared WebSocket."""
        symbols: set[str] = set()
        for user in self._read().get("users", {}).values():
            if not user.get("enabled"):
                continue
            for config in user.get("symbols", {}).values():
                if config.get("exchange") != "bitunix" or not config.get("enabled", True):
                    continue
                confirmed = (
                    user.get("notify_confirmed_fvg", True)
                    and "15m" in config.get("timeframes", ())
                )
                preliminary = (
                    user.get("notify_pre_fvg", False)
                    and is_bitcoin_symbol(config.get("symbol", ""))
                    and "15m" in config.get("timeframes", ())
                )
                if confirmed or preliminary:
                    symbols.add(config["symbol"])
        return frozenset(sorted(symbols)[:MAX_ACTIVE_SYMBOLS])

    def recipients(self, event: FvgEvent) -> list[int]:
        recipients = []
        if event.event_type is FvgEventType.PRE_FVG and not is_bitcoin_symbol(event.symbol):
            return recipients
        event_key = instrument_key(event.exchange, event.symbol)
        for key, user in self._read().get("users", {}).items():
            if not user.get("enabled"):
                continue
            type_key = (
                "notify_pre_fvg"
                if event.event_type is FvgEventType.PRE_FVG
                else "notify_confirmed_fvg"
            )
            if not user.get(
                type_key,
                event.event_type is FvgEventType.CONFIRMED_FVG,
            ):
                continue
            direction_key = (
                "bullish_enabled"
                if event.direction is FvgDirection.BULLISH
                else "bearish_enabled"
            )
            if not user.get(direction_key, True):
                continue

            symbol_config = user.get("symbols", {}).get(event_key)
            if not symbol_config or not symbol_config.get("enabled", True):
                continue
            if event.timeframe not in symbol_config.get("timeframes", ("15m",)):
                continue

            apply_key = (
                "apply_to_pre_fvg"
                if event.event_type is FvgEventType.PRE_FVG
                else "apply_to_confirmed_fvg"
            )
            direction_apply_key = (
                "apply_to_bullish"
                if event.direction is FvgDirection.BULLISH
                else "apply_to_bearish"
            )

            price = symbol_config.get("price_filter", {})
            use_price_filter = (
                price.get("enabled", False)
                and price.get(apply_key, True)
                and price.get(direction_apply_key, True)
            )
            if not price_allowed(
                event.signal_price,
                use_price_filter,
                _decimal(price.get("min")),
                _decimal(price.get("max")),
            ):
                continue

            size = symbol_config.get("size_filter", {})
            use_size_filter = (
                size.get("enabled", False)
                and size.get(apply_key, True)
                and size.get(direction_apply_key, True)
            )
            if not size_allowed(
                event.zone_size,
                event.signal_price,
                use_size_filter,
                size.get("unit", "USD"),
                _decimal(size.get("min")),
                None,
            ):
                continue
            recipients.append(int(key))
        return recipients

    def is_new(self, event_key):
        return self._read().get("legacy_last_event_key") != event_key

    def mark_sent(self, event_key):
        self._transaction(
            lambda data: data.update(legacy_last_event_key=event_key)
        )

    def is_new_pre_event(self, event_key):
        return self._read().get("legacy_last_pre_event_key") != event_key

    def mark_pre_sent(self, event_key):
        self._transaction(
            lambda data: data.update(legacy_last_pre_event_key=event_key)
        )


__all__ = [
    "AtomicJsonStore",
    "FvgAlertSettings",
    "FvgEventStore",
    "instrument_key",
    "split_instrument_key",
]
