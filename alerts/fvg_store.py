"""Persistence facade for FVG preferences and event history."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alerts.fvg_detector import price_allowed, size_allowed
from alerts.fvg_models import FvgDirection, FvgEvent, FvgEventType
from alerts.sqlite_event_store import FvgEventStore
from config import MAX_ACTIVE_SYMBOLS, MAX_SYMBOLS_PER_USER


_STORE_LOCKS: dict[str, threading.RLock] = {}
_STORE_LOCKS_GUARD = threading.Lock()


class AtomicJsonStore:
    """Atomic JSON storage retained for low-frequency user preferences."""

    def __init__(self, path: str):
        self.path = Path(path)
        resolved = str(self.path.resolve())
        with _STORE_LOCKS_GUARD:
            self._lock = _STORE_LOCKS.setdefault(resolved, threading.RLock())

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


def _symbol_defaults() -> dict:
    return {
        "enabled": True,
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
        "symbols": {"BTCUSDT": _symbol_defaults()},
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
        # Filter helpers fail closed for non-finite values.
        return Decimal("NaN")


class FvgAlertSettings:
    SCHEMA_VERSION = 2

    def __init__(self, path: str = "data/fvg_alert_settings.json"):
        self.store = AtomicJsonStore(path)
        self.path = self.store.path

    def _read(self) -> dict:
        raw = self.store.read()
        if raw.get("schema_version") == self.SCHEMA_VERSION:
            return raw

        users = {}
        known_ids = set(raw.get("enabled_chat_ids", [])) | set(
            raw.get("pre_enabled_chat_ids", [])
        )
        for chat_id in known_ids:
            user = _user_defaults()
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
        with self.store._lock:
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
            if value.get("enabled") and value.get("notify_pre_fvg", False)
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

    def add_symbol(self, chat_id: int, symbol: str) -> None:
        symbol = symbol.upper()

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            symbols = user.setdefault("symbols", {})
            if symbol not in symbols and len(symbols) >= MAX_SYMBOLS_PER_USER:
                raise ValueError(
                    f"Можно добавить не более {MAX_SYMBOLS_PER_USER} инструментов."
                )
            symbols.setdefault(symbol, _symbol_defaults())

        self._transaction(mutate)

    def remove_symbol(self, chat_id: int, symbol: str) -> None:
        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            user.setdefault("symbols", {}).pop(symbol.upper(), None)

        self._transaction(mutate)

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
            symbol_data = user.setdefault("symbols", {}).setdefault(
                symbol.upper(), _symbol_defaults()
            )
            symbol_data["price_filter"] = {
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
        del maximum  # Size filters intentionally use a minimum only.
        unit = unit.upper()
        if unit not in {"USD", "PERCENT"}:
            raise ValueError("Единица размера должна быть USD или PERCENT")
        min_value = _parse_boundary(minimum, label="размера FVG")

        def mutate(data):
            user = data.setdefault("users", {}).setdefault(
                str(chat_id), _user_defaults()
            )
            symbol_data = user.setdefault("symbols", {}).setdefault(
                symbol.upper(), _symbol_defaults()
            )
            symbol_data["size_filter"] = {
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

    def active_symbols(self) -> frozenset[str]:
        symbols: set[str] = set()
        for user in self._read().get("users", {}).values():
            if user.get("enabled"):
                symbols.update(
                    symbol
                    for symbol, config in user.get("symbols", {}).items()
                    if config.get("enabled", True)
                )
        return frozenset(sorted(symbols)[:MAX_ACTIVE_SYMBOLS])

    def recipients(self, event: FvgEvent) -> list[int]:
        recipients = []
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

            symbol_config = user.get("symbols", {}).get(event.symbol)
            if not symbol_config or not symbol_config.get("enabled", True):
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

    # Compatibility with the old tests/API.
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
]
