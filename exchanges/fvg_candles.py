"""Public multi-exchange candle adapters for confirmed and BTC pre-FVG."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests

from alerts.fvg_models import Candle
from exchanges.bitunix import BitunixClient
from exchanges.funding import EXCHANGE_ORDER, normalize_exchange


UTC = timezone.utc
REQUEST_TIMEOUT_SECONDS = 15
CONFIRMED_TIMEFRAMES = ("15m", "1h", "4h", "1d")
ALL_TIMEFRAMES = ("1m", *CONFIRMED_TIMEFRAMES)
TIMEFRAME_STEPS = {
    "1m": timedelta(minutes=1),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def normalize_fvg_symbol(value: str) -> str:
    compact = (
        str(value or "")
        .strip()
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )
    if compact and not compact.endswith(("USDT", "USDC", "USD")):
        compact += "USDT"
    if not compact.isalnum() or not 5 <= len(compact) <= 24:
        raise ValueError("Введите инструмент, например BTCUSDT или BTC/USDT.")
    return compact


def base_asset(symbol: str) -> str:
    normalized = normalize_fvg_symbol(symbol)
    for quote in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)]
    return normalized


def is_bitcoin_symbol(symbol: str) -> bool:
    return base_asset(symbol) == "BTC"


def timeframe_step(timeframe: str) -> timedelta:
    try:
        return TIMEFRAME_STEPS[timeframe]
    except KeyError as error:
        raise ValueError(f"Unsupported FVG timeframe: {timeframe}") from error


def timeframe_due(timeframe: str, now: datetime) -> bool:
    """Return True immediately after a configured candle boundary in UTC."""
    now = now.astimezone(UTC)
    if timeframe == "15m":
        return now.minute % 15 == 0
    if timeframe == "1h":
        return now.minute == 0
    if timeframe == "4h":
        return now.minute == 0 and now.hour % 4 == 0
    if timeframe == "1d":
        return now.minute == 0 and now.hour == 0
    return False


def _decimal(value) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Malformed exchange candle price") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("Exchange candle contains invalid price")
    return parsed


def _milliseconds(value) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, UTC)


def _seconds(value) -> datetime:
    return datetime.fromtimestamp(int(value), UTC)


def _candle(symbol: str, timeframe: str, open_time: datetime, raw_prices, now) -> Candle:
    open_price, high, low, close = map(_decimal, raw_prices)
    high = max(high, open_price, close)
    low = min(low, open_price, close)
    close_time = open_time + timeframe_step(timeframe)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=close_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        is_closed=close_time <= now,
        is_complete=True,
    )


def _exchange_symbol(exchange: str, symbol: str) -> str:
    if exchange == "bingx" and symbol.endswith("USDT"):
        return f"{symbol[:-4]}-USDT"
    if exchange == "gate" and symbol.endswith("USDT"):
        return f"{symbol[:-4]}_USDT"
    return symbol


class PublicCandleClient:
    """Load normalized public futures candles from every attached exchange."""

    BINANCE_BASE_URL = "https://fapi.binance.com"
    BYBIT_BASE_URL = "https://api.bybit.com"
    BINGX_BASE_URL = "https://open-api.bingx.com"
    BITGET_BASE_URL = "https://api.bitget.com"
    GATE_BASE_URL = "https://api.gateio.ws/api/v4"

    def __init__(self, session=None, bitunix_client=None):
        self.session = session or requests
        self.bitunix = bitunix_client or BitunixClient(session=session)

    def _get_json(self, url: str, *, params=None):
        response = self.session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def load(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        limit: int = 3,
        now: datetime | None = None,
    ) -> list[Candle]:
        exchange = normalize_exchange(exchange)
        symbol = normalize_fvg_symbol(symbol)
        if timeframe not in ALL_TIMEFRAMES:
            raise ValueError(f"Unsupported FVG timeframe: {timeframe}")
        now = (now or datetime.now(UTC)).astimezone(UTC)
        rows = getattr(self, f"_load_{exchange}")(
            _exchange_symbol(exchange, symbol),
            timeframe,
            max(1, int(limit)) + 2,
            now,
            symbol,
        )
        closed = sorted(
            (item for item in rows if item.is_closed and item.is_complete),
            key=lambda item: item.open_time,
        )
        return closed[-max(1, int(limit)) :]

    def symbol_exists(self, exchange: str, symbol: str) -> bool:
        try:
            return bool(self.load(exchange, symbol, "15m", limit=1))
        except (KeyError, TypeError, ValueError):
            return False

    def _load_bitunix(self, exchange_symbol, timeframe, limit, now, symbol):
        response = self.bitunix.get_candles(exchange_symbol, timeframe, limit)
        result = []
        for raw in response.get("data", []):
            if not isinstance(raw, dict):
                continue
            try:
                result.append(
                    _candle(
                        symbol,
                        timeframe,
                        _milliseconds(raw["time"]),
                        (raw["open"], raw["high"], raw["low"], raw["close"]),
                        now,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _load_binance(self, exchange_symbol, timeframe, limit, now, symbol):
        payload = self._get_json(
            f"{self.BINANCE_BASE_URL}/fapi/v1/klines",
            params={"symbol": exchange_symbol, "interval": timeframe, "limit": limit},
        )
        result = []
        for raw in payload if isinstance(payload, list) else []:
            try:
                result.append(
                    _candle(
                        symbol,
                        timeframe,
                        _milliseconds(raw[0]),
                        (raw[1], raw[2], raw[3], raw[4]),
                        now,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def _load_bybit(self, exchange_symbol, timeframe, limit, now, symbol):
        interval = {"1m": "1", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}[timeframe]
        payload = self._get_json(
            f"{self.BYBIT_BASE_URL}/v5/market/kline",
            params={
                "category": "linear",
                "symbol": exchange_symbol,
                "interval": interval,
                "limit": limit,
            },
        )
        if str(payload.get("retCode", "0")) != "0":
            raise ValueError(payload.get("retMsg", "Bybit candle error"))
        result = []
        for raw in payload.get("result", {}).get("list", []):
            try:
                result.append(
                    _candle(
                        symbol,
                        timeframe,
                        _milliseconds(raw[0]),
                        (raw[1], raw[2], raw[3], raw[4]),
                        now,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def _load_bingx(self, exchange_symbol, timeframe, limit, now, symbol):
        payload = self._get_json(
            f"{self.BINGX_BASE_URL}/openApi/swap/v3/quote/klines",
            params={"symbol": exchange_symbol, "interval": timeframe, "limit": limit},
        )
        if str(payload.get("code", "0")) != "0":
            raise ValueError(payload.get("msg", "BingX candle error"))
        result = []
        for raw in payload.get("data", []):
            try:
                if isinstance(raw, dict):
                    open_time = _milliseconds(raw.get("time", raw.get("openTime")))
                    prices = (raw["open"], raw["high"], raw["low"], raw["close"])
                else:
                    open_time = _milliseconds(raw[0])
                    prices = (raw[1], raw[2], raw[3], raw[4])
                result.append(_candle(symbol, timeframe, open_time, prices, now))
            except (IndexError, KeyError, TypeError, ValueError):
                continue
        return result

    def _load_bitget(self, exchange_symbol, timeframe, limit, now, symbol):
        granularity = {
            "1m": "1m",
            "15m": "15m",
            "1h": "1H",
            "4h": "4H",
            "1d": "1D",
        }[timeframe]
        payload = self._get_json(
            f"{self.BITGET_BASE_URL}/api/v2/mix/market/candles",
            params={
                "symbol": exchange_symbol,
                "productType": "usdt-futures",
                "granularity": granularity,
                "limit": limit,
            },
        )
        if payload.get("code") != "00000":
            raise ValueError(payload.get("msg", "Bitget candle error"))
        result = []
        for raw in payload.get("data", []):
            try:
                result.append(
                    _candle(
                        symbol,
                        timeframe,
                        _milliseconds(raw[0]),
                        (raw[1], raw[2], raw[3], raw[4]),
                        now,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result

    def _load_gate(self, exchange_symbol, timeframe, limit, now, symbol):
        payload = self._get_json(
            f"{self.GATE_BASE_URL}/futures/usdt/candlesticks",
            params={
                "contract": exchange_symbol,
                "interval": timeframe,
                "limit": limit,
            },
        )
        result = []
        for raw in payload if isinstance(payload, list) else []:
            try:
                result.append(
                    _candle(
                        symbol,
                        timeframe,
                        _seconds(raw[0]),
                        (raw[5], raw[3], raw[4], raw[2]),
                        now,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        return result


__all__ = [
    "ALL_TIMEFRAMES",
    "CONFIRMED_TIMEFRAMES",
    "EXCHANGE_ORDER",
    "PublicCandleClient",
    "base_asset",
    "is_bitcoin_symbol",
    "normalize_fvg_symbol",
    "timeframe_due",
    "timeframe_step",
]
