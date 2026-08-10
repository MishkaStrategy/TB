"""Read-only market snapshots for saved Mini App FVG instruments.

The overview intentionally reuses the project's public exchange adapters. 24h
price change comes from ``PublicFundingClient`` ticker payloads where the
exchange already exposes it. If an exchange adapter does not provide that field
(BingX today) a bounded candle fallback compares closed 15m prices 24 hours
apart. Missing market data never affects settings reads/writes.
"""

from __future__ import annotations

import copy
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable

from exchanges.funding import PublicFundingClient, normalize_exchange
from exchanges.fvg_candles import PublicCandleClient, normalize_fvg_symbol

from .auth import TelegramUser
from .runtime_service import MiniAppSettingsService

UTC = timezone.utc


def _finite_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _normalize_instruments(values) -> list[dict]:
    """Normalize valid persisted rows without letting one bad row poison a read."""
    normalized: list[dict] = []
    for item in values if isinstance(values, list) else ():
        if (
            not isinstance(item, dict)
            or not item.get("key")
            or not item.get("exchange")
            or not item.get("symbol")
        ):
            continue
        try:
            normalized.append(
                {
                    "key": str(item["key"]),
                    "exchange": normalize_exchange(item["exchange"]),
                    "symbol": normalize_fvg_symbol(item["symbol"]),
                }
            )
        except (TypeError, ValueError):
            continue
    return normalized


def _ticker_index(rows) -> dict[str, dict]:
    """Index valid ticker rows while isolating malformed exchange payload entries."""
    result: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        try:
            symbol = normalize_fvg_symbol(row.get("symbol"))
        except (TypeError, ValueError):
            continue
        result[symbol] = row
    return result


class MarketOverviewService:
    """Build cached exchange-aware 24h snapshots for saved FVG instruments."""

    def __init__(
        self,
        settings_service: MiniAppSettingsService,
        *,
        funding_client_factory: Callable[[], PublicFundingClient] = PublicFundingClient,
        candle_client_factory: Callable[[], PublicCandleClient] = PublicCandleClient,
        cache_ttl_seconds: float = 30.0,
        max_workers: int = 3,
        max_cache_entries: int = 256,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ):
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if max_cache_entries <= 0:
            raise ValueError("max_cache_entries must be positive")
        self.settings_service = settings_service
        self.funding_client_factory = funding_client_factory
        self.candle_client_factory = candle_client_factory
        self.cache_ttl_seconds = float(cache_ttl_seconds)
        self.max_workers = int(max_workers)
        self.max_cache_entries = int(max_cache_entries)
        self.now = now or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._cache_lock = threading.Lock()

    def read_overview(self, user: TelegramUser) -> dict:
        """Return a market overview for instruments saved by this user only."""
        if not self.settings_service.is_authorized(user.id):
            raise PermissionError("Доступ к Mini App не разрешён.")

        envelope = self.settings_service.read_settings(user)
        instruments = envelope.get("settings", {}).get("fvg", {}).get("symbols", [])
        normalized = _normalize_instruments(instruments)
        cache_key = (
            int(user.id),
            tuple((item["key"], item["exchange"], item["symbol"]) for item in normalized),
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        by_exchange: dict[str, list[dict]] = {}
        for item in normalized:
            by_exchange.setdefault(item["exchange"], []).append(item)

        rows_by_key: dict[str, dict] = {}
        if by_exchange:
            worker_count = min(self.max_workers, len(by_exchange))
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="mini-app-market",
            ) as executor:
                futures = {
                    executor.submit(self._load_exchange, exchange, rows): exchange
                    for exchange, rows in by_exchange.items()
                }
                for future in as_completed(futures):
                    exchange = futures[future]
                    try:
                        rows_by_key.update(future.result())
                    except Exception:
                        for item in by_exchange[exchange]:
                            rows_by_key[item["key"]] = self._unavailable(item)

        updated_at = self.now().astimezone(UTC).isoformat()
        result = {
            "instruments": [
                rows_by_key.get(item["key"], self._unavailable(item))
                for item in normalized
            ],
            "updatedAt": updated_at,
        }
        self._store_cached(cache_key, result)
        return copy.deepcopy(result)

    def _load_exchange(self, exchange: str, instruments: list[dict]) -> dict[str, dict]:
        funding_client = self.funding_client_factory()
        candle_client = self.candle_client_factory()
        ticker_rows = funding_client.load(exchange)
        ticker_rows_by_symbol = _ticker_index(ticker_rows)

        result: dict[str, dict] = {}
        for instrument in instruments:
            ticker = ticker_rows_by_symbol.get(instrument["symbol"], {})
            change = _finite_decimal(ticker.get("priceChange24h"))
            source = "ticker"
            if change is None:
                change = self._candle_change_24h(
                    candle_client,
                    instrument["exchange"],
                    instrument["symbol"],
                )
                source = "candles" if change is not None else "unavailable"
            result[instrument["key"]] = {
                **instrument,
                "price": None,
                "priceChange24hPct": _number(change),
                "source": source,
            }
        return result

    @staticmethod
    def _candle_change_24h(
        client: PublicCandleClient,
        exchange: str,
        symbol: str,
    ) -> Decimal | None:
        try:
            candles = client.load(exchange, symbol, "15m", limit=97)
        except Exception:
            return None
        if len(candles) < 97:
            return None
        previous = _finite_decimal(candles[-97].close)
        current = _finite_decimal(candles[-1].close)
        if previous in (None, Decimal("0")) or current is None:
            return None
        return (current / previous - Decimal("1")) * Decimal("100")

    @staticmethod
    def _unavailable(instrument: dict) -> dict:
        return {
            **instrument,
            "price": None,
            "priceChange24hPct": None,
            "source": "unavailable",
        }

    def _get_cached(self, key: tuple) -> dict | None:
        now = self.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            expires_at, value = cached
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return copy.deepcopy(value)

    def _store_cached(self, key: tuple, value: dict) -> None:
        expires_at = self.monotonic() + self.cache_ttl_seconds
        with self._cache_lock:
            if len(self._cache) >= self.max_cache_entries and key not in self._cache:
                oldest_key = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest_key, None)
            self._cache[key] = (expires_at, copy.deepcopy(value))
