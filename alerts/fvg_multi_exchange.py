"""Shared multi-exchange polling with 15m-only market-data downloads."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from alerts.fvg_detector import FvgDetector, are_consecutive
from alerts.fvg_models import Candle, FvgEvent, event_id
from alerts.fvg_service import parse_rest_candle
from exchanges.funding import normalize_exchange
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES, PublicCandleClient


UTC = timezone.utc
SOURCE_TIMEFRAME = "15m"
SOURCE_STEP = timedelta(minutes=15)
TARGET_UNITS = {
    "15m": 1,
    "1h": 4,
    "4h": 16,
    "1d": 96,
}
TARGET_STEPS = {
    "15m": SOURCE_STEP,
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def _bucket_open(value: datetime, timeframe: str) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    if timeframe == "15m":
        return value.replace(minute=value.minute - value.minute % 15)
    if timeframe == "1h":
        return value.replace(minute=0)
    if timeframe == "4h":
        return value.replace(hour=value.hour - value.hour % 4, minute=0)
    if timeframe == "1d":
        return value.replace(hour=0, minute=0)
    raise ValueError(f"Unsupported FVG timeframe: {timeframe}")


def required_15m_candles(timeframes) -> int:
    """Return a bounded source lookback that guarantees three closed target candles."""
    selected = [item for item in CONFIRMED_TIMEFRAMES if item in set(timeframes or ())]
    if not selected:
        return 0
    required = 3
    for timeframe in selected:
        units = TARGET_UNITS[timeframe]
        # Four target windows cover three complete candles plus the currently
        # forming target candle at any point inside its UTC-aligned bucket.
        required = max(required, 3 if units == 1 else units * 4)
    return required


def aggregate_15m_candles(
    candles,
    timeframe: str,
    now: datetime,
) -> list[Candle]:
    """Aggregate complete UTC-aligned target candles from closed 15m candles."""
    if timeframe not in TARGET_UNITS:
        raise ValueError(f"Unsupported FVG timeframe: {timeframe}")
    now = now.astimezone(UTC)
    source_by_time = {
        candle.open_time: candle
        for candle in candles
        if candle.timeframe == SOURCE_TIMEFRAME
        and candle.is_closed
        and candle.is_complete
        and candle.close_time <= now
    }
    source = sorted(source_by_time.values(), key=lambda candle: candle.open_time)
    if timeframe == SOURCE_TIMEFRAME:
        return source

    expected = TARGET_UNITS[timeframe]
    target_step = TARGET_STEPS[timeframe]
    groups: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in source:
        groups[_bucket_open(candle.open_time, timeframe)].append(candle)

    result = []
    for open_time in sorted(groups):
        close_time = open_time + target_step
        if close_time > now:
            continue
        items = sorted(groups[open_time], key=lambda candle: candle.open_time)
        if len(items) != expected:
            continue
        if items[0].open_time != open_time:
            continue
        if items[-1].close_time != close_time:
            continue
        if not are_consecutive(items, SOURCE_STEP):
            continue
        if len({item.symbol for item in items}) != 1:
            continue
        result.append(
            Candle(
                symbol=items[0].symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=items[0].open,
                high=max(item.high for item in items),
                low=min(item.low for item in items),
                close=items[-1].close,
                is_closed=True,
                is_complete=True,
            )
        )
    return result


class MultiExchangeFvgPoller:
    def __init__(self, candle_client=None, detector=None):
        self.candle_client = candle_client or PublicCandleClient()
        self.detector = detector or FvgDetector()

    @staticmethod
    def _with_exchange(event: FvgEvent | None, exchange: str) -> FvgEvent | None:
        if event is None:
            return None
        exchange = normalize_exchange(exchange)
        return replace(
            event,
            exchange=exchange,
            event_id=event_id(
                event.symbol,
                event.timeframe,
                event.direction,
                event.candle_c_open_time,
                event.event_type,
                exchange,
            ),
        )

    def _load_bitunix_history(
        self,
        symbol: str,
        limit: int,
        now: datetime,
    ) -> list[Candle]:
        bitunix = getattr(self.candle_client, "bitunix", None)
        history_loader = getattr(bitunix, "get_historical_candles", None)
        if not callable(history_loader):
            return self.candle_client.load(
                "bitunix",
                symbol,
                SOURCE_TIMEFRAME,
                limit=limit,
                now=now,
            )
        margin = 4
        start = now - SOURCE_STEP * (limit + margin)
        rows = history_loader(
            symbol,
            SOURCE_TIMEFRAME,
            int(start.timestamp() * 1000),
            int(now.timestamp() * 1000),
        )
        result = []
        for raw in rows:
            try:
                candle = parse_rest_candle(raw, symbol, SOURCE_TIMEFRAME, now)
            except (KeyError, TypeError, ValueError):
                continue
            if candle.is_closed and candle.is_complete:
                result.append(candle)
        return sorted(result, key=lambda candle: candle.open_time)[-limit:]

    def _load_source(
        self,
        exchange: str,
        symbol: str,
        limit: int,
        now: datetime,
    ) -> list[Candle]:
        exchange = normalize_exchange(exchange)
        if exchange == "bitunix" and limit > 200:
            return self._load_bitunix_history(symbol, limit, now)
        return self.candle_client.load(
            exchange,
            symbol,
            SOURCE_TIMEFRAME,
            limit=limit,
            now=now,
        )

    def confirmed_many(
        self,
        exchange: str,
        symbol: str,
        timeframes,
        now: datetime | None = None,
    ) -> list[FvgEvent]:
        """Evaluate multiple target timeframes from one shared 15m source download."""
        selected = tuple(
            timeframe
            for timeframe in CONFIRMED_TIMEFRAMES
            if timeframe in set(timeframes or ())
        )
        if not selected:
            return []
        now = (now or datetime.now(UTC)).astimezone(UTC)
        source = self._load_source(
            exchange,
            symbol,
            required_15m_candles(selected),
            now,
        )
        if not source:
            normalized_exchange = normalize_exchange(exchange)
            raise RuntimeError(
                "No closed 15m FVG candles returned for "
                f"{normalized_exchange} {symbol}"
            )
        events = []
        for timeframe in selected:
            candles = aggregate_15m_candles(source, timeframe, now)
            if len(candles) < 3:
                continue
            event = self.detector.detect_confirmed(candles[-3:], now)
            event = self._with_exchange(event, exchange)
            if event is not None:
                events.append(event)
        return events

    def confirmed(
        self,
        exchange: str,
        symbol: str,
        timeframe: str = "15m",
        now: datetime | None = None,
    ) -> list[FvgEvent]:
        return self.confirmed_many(exchange, symbol, (timeframe,), now)


__all__ = [
    "MultiExchangeFvgPoller",
    "SOURCE_TIMEFRAME",
    "TARGET_UNITS",
    "aggregate_15m_candles",
    "required_15m_candles",
]
