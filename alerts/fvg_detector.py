"""Pure confirmed FVG detection and filter rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable

from alerts.fvg_models import Candle, FvgDirection, FvgEvent, FvgEventType, event_id


UTC = timezone.utc
TIMEFRAME_STEPS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def are_consecutive(candles: Iterable[Candle], step: timedelta) -> bool:
    items = list(candles)
    return all(
        right.open_time - left.open_time == step
        for left, right in zip(items, items[1:])
    )


class FvgDetector:
    def detect_confirmed(
        self,
        candles: Iterable[Candle],
        detected_at: datetime | None = None,
    ) -> FvgEvent | None:
        """Return a confirmed FVG for three closed consecutive supported candles."""
        items = sorted(candles, key=lambda candle: candle.open_time)
        if len(items) != 3:
            return None
        timeframes = {candle.timeframe for candle in items}
        if len(timeframes) != 1:
            return None
        timeframe = next(iter(timeframes))
        step = TIMEFRAME_STEPS.get(timeframe)
        if step is None:
            return None
        if not all(candle.is_closed and candle.is_complete for candle in items):
            return None
        if len({candle.symbol for candle in items}) != 1:
            return None
        if not are_consecutive(items, step):
            return None
        return self._event(items[0], items[1], items[2], detected_at)

    @staticmethod
    def _event(
        candle_a: Candle,
        candle_b: Candle,
        candle_c: Candle,
        detected_at: datetime | None,
    ) -> FvgEvent | None:
        if candle_c.low > candle_a.high:
            direction = FvgDirection.BULLISH
            zone_low, zone_high = candle_a.high, candle_c.low
        elif candle_c.high < candle_a.low:
            direction = FvgDirection.BEARISH
            zone_low, zone_high = candle_c.high, candle_a.low
        else:
            return None
        detected_at = (detected_at or datetime.now(UTC)).astimezone(UTC)
        return FvgEvent(
            event_id=event_id(
                candle_c.symbol,
                candle_c.timeframe,
                direction,
                candle_c.open_time,
                FvgEventType.CONFIRMED_FVG,
            ),
            event_type=FvgEventType.CONFIRMED_FVG,
            symbol=candle_c.symbol,
            timeframe=candle_c.timeframe,
            direction=direction,
            candle_a_open_time=candle_a.open_time,
            candle_b_open_time=candle_b.open_time,
            candle_c_open_time=candle_c.open_time,
            candle_c_close_time=candle_c.close_time,
            zone_low=zone_low,
            zone_high=zone_high,
            zone_size=zone_high - zone_low,
            signal_price=candle_c.close,
            detected_at=detected_at,
            is_confirmed=True,
            data_complete=True,
        )


def _finite(value: Decimal | None) -> bool:
    return value is None or value.is_finite()


def price_allowed(
    signal_price: Decimal,
    enabled: bool,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    if not enabled:
        return True
    if not signal_price.is_finite() or not _finite(minimum) or not _finite(maximum):
        return False
    try:
        if minimum is not None and signal_price < minimum:
            return False
        if maximum is not None and signal_price > maximum:
            return False
    except InvalidOperation:
        return False
    return True


def fvg_size_value(
    zone_size: Decimal,
    signal_price: Decimal,
    unit: str,
) -> Decimal:
    if not zone_size.is_finite() or zone_size < 0:
        raise ValueError("FVG size must be finite and non-negative")
    if not signal_price.is_finite() or signal_price <= 0:
        raise ValueError("Signal price must be finite and positive")
    if unit == "USD":
        return zone_size
    if unit == "PERCENT":
        return zone_size / signal_price * Decimal("100")
    raise ValueError("FVG size unit must be USD or PERCENT")


def size_allowed(
    zone_size: Decimal,
    signal_price: Decimal,
    enabled: bool,
    unit: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    if not enabled:
        return True
    if not _finite(minimum) or not _finite(maximum):
        return False
    try:
        value = fvg_size_value(zone_size, signal_price, unit)
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    except (InvalidOperation, ValueError):
        return False
    return True


__all__ = [
    "FvgDetector",
    "TIMEFRAME_STEPS",
    "are_consecutive",
    "fvg_size_value",
    "price_allowed",
    "size_allowed",
]
