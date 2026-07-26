import threading
import time

import requests

from config import BITUNIX_REQUESTS_PER_SECOND


class _SharedRateLimiter:
    """Process-wide spacing for Bitunix REST requests."""

    def __init__(self, requests_per_second: float):
        self.interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_request_at = max(now, self._next_request_at) + self.interval


class BitunixClient:

    BASE_URL = "https://fapi.bitunix.com"
    REQUEST_TIMEOUT_SECONDS = 15
    MAX_KLINE_LIMIT = 200
    INTERVAL_MILLISECONDS = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }
    _RATE_LIMITER = _SharedRateLimiter(BITUNIX_REQUESTS_PER_SECOND)

    def __init__(self, session=None):
        self.session = session or requests
        # Unit tests normally inject a fake session and should not sleep.
        self._use_rate_limiter = session is None or isinstance(
            self.session, requests.Session
        )

    def _get(self, url, **kwargs):
        if self._use_rate_limiter:
            self._RATE_LIMITER.acquire()
        return self.session.get(
            url,
            timeout=self.REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

    @classmethod
    def _normalize_kline_limit(cls, limit) -> int:
        try:
            parsed = int(limit)
        except (TypeError, ValueError) as error:
            raise ValueError("Kline limit must be an integer") from error
        if parsed <= 0:
            raise ValueError("Kline limit must be positive")
        return min(parsed, cls.MAX_KLINE_LIMIT)

    def get_candles(
        self,
        symbol="BTCUSDT",
        interval="15m",
        limit=100,
        start_time=None,
        end_time=None,
    ):
        url = f"{self.BASE_URL}/api/v1/futures/market/kline"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": self._normalize_kline_limit(limit),
        }
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)

        response = self._get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_ticker(self, symbol="BTCUSDT"):
        response = self._get(
            f"{self.BASE_URL}/api/v1/futures/market/tickers",
            params={"symbols": symbol},
        )
        response.raise_for_status()
        data = response.json()
        tickers = data.get("data", [])

        if not tickers:
            raise ValueError(f"No ticker returned for {symbol}")

        return tickers[0]

    def get_all_tickers(self):
        """Return 24-hour ticker data for all futures instruments."""
        response = self._get(
            f"{self.BASE_URL}/api/v1/futures/market/tickers",
        )
        response.raise_for_status()
        tickers = response.json().get("data", [])
        if not isinstance(tickers, list):
            raise ValueError("Unexpected tickers format from Bitunix")
        return tickers

    def get_trading_pairs(self, symbols=None):
        """Return public futures instruments; no API credentials are required."""
        params = {}
        if symbols:
            params["symbols"] = ",".join(symbols) if not isinstance(symbols, str) else symbols
        response = self._get(
            f"{self.BASE_URL}/api/v1/futures/market/trading_pairs",
            params=params,
        )
        response.raise_for_status()
        return response.json().get("data", [])

    def is_open_symbol(self, symbol):
        return any(
            item.get("symbol") == symbol.upper()
            and item.get("symbolStatus") == "OPEN"
            for item in self.get_trading_pairs([symbol.upper()])
        )

    def get_funding_rate(self, symbol):
        response = self._get(
            f"{self.BASE_URL}/api/v1/futures/market/funding_rate",
            params={"symbol": symbol},
        )
        response.raise_for_status()
        rates = response.json().get("data")

        if isinstance(rates, dict):
            return rates
        if isinstance(rates, list) and rates:
            return rates[0]

        if not rates:
            raise ValueError(f"No funding rate returned for {symbol}")

        raise ValueError(f"Unexpected funding rate format for {symbol}")

    def get_all_funding_rates(self):
        """Return current funding rates for all futures instruments."""
        response = self._get(
            f"{self.BASE_URL}/api/v1/futures/market/funding_rate/batch",
        )
        response.raise_for_status()
        rates = response.json().get("data", [])
        if isinstance(rates, dict):
            return [rates]
        if isinstance(rates, list):
            return rates
        raise ValueError("Unexpected funding rates format from Bitunix")

    def get_historical_candles(
        self,
        symbol,
        interval,
        start_time,
        end_time,
        limit=MAX_KLINE_LIMIT,
    ):
        """Download a complete, de-duplicated candle range in chronological order."""
        if interval not in self.INTERVAL_MILLISECONDS:
            raise ValueError(f"Unsupported interval: {interval}")
        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time")
        limit = self._normalize_kline_limit(limit)

        candles_by_time = {}
        cursor = int(end_time)

        while cursor > start_time:
            response = self.get_candles(
                symbol=symbol,
                interval=interval,
                limit=limit,
                end_time=cursor,
            )
            batch = response.get("data", [])

            if not batch:
                break

            oldest_time = min(int(candle["time"]) for candle in batch)
            for candle in batch:
                candle_time = int(candle["time"])
                if start_time <= candle_time <= end_time:
                    candles_by_time[candle_time] = candle

            if oldest_time >= cursor:
                raise RuntimeError("Bitunix returned a non-progressing candle page")

            cursor = oldest_time - 1

        return [
            candles_by_time[candle_time]
            for candle_time in sorted(candles_by_time)
        ]
