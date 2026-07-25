"""Pure FVG detection, aggregation and price-filter rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable

from alerts.fvg_models import Candle, FvgDirection, FvgEvent, FvgEventType, event_id


UTC = timezone.utc
FIFTEEN_MINUTES = timedelta(minutes=15)
ONE_MINUTE = timedelta(minutes=1)


def are_consecutive(candles: Iterable[Candle], step: timedelta) -> bool:
    items = list(candles)
    return all(
        right.open_time - left.open_time == step
        for left, right in zip(items, items[1:])
    )


def aggregate_current_15m(
    symbol: str,
    minute_candles: Iterable[Candle],
    interval_open: datetime,
    now: datetime,
) -> Candle | None:
    """Build the forming 15m candle from consecutive, closed 1m candles."""
    expected_count = int((now - interval_open).total_seconds() // 60)
    minutes = sorted(
        (
            candle
            for candle in minute_candles
            if candle.symbol == symbol
            and candle.timeframe == "1m"
            and interval_open <= candle.open_time < interval_open + FIFTEEN_MINUTES
            and candle.is_closed
            and candle.is_complete
        ),
        key=lambda candle: candle.open_time,
    )
    if expected_count <= 0 or len(minutes) != expected_count:
        return None
    if minutes[0].open_time != interval_open or not are_consecutive(minutes, ONE_MINUTE):
        return None
    return Candle(
        symbol=symbol,
        timeframe="15m",
        open_time=interval_open,
        close_time=interval_open + FIFTEEN_MINUTES,
        open=minutes[0].open,
        high=max(candle.high for candle in minutes),
        low=min(candle.low for candle in minutes),
        close=minutes[-1].close,
        is_closed=False,
        is_complete=True,
    )


class FvgDetector:
    def detect_confirmed(
        self, candles: Iterable[Candle], detected_at: datetime | None = None
    ) -> FvgEvent | None:
        items = sorted(candles, key=lambda candle: candle.open_time)
        if len(items) != 3:
            return None
        if not all(c.is_closed and c.is_complete and c.timeframe == "15m" for c in items):
            return None
        if len({c.symbol for c in items}) != 1 or not are_consecutive(items, FIFTEEN_MINUTES):
            return None
        return self._event(items[0], items[1], items[2], FvgEventType.CONFIRMED_FVG, detected_at)

    def detect_pre(
        self,
        candle_a: Candle,
        candle_b: Candle,
        current_c: Candle,
        now: datetime,
    ) -> FvgEvent | None:
        control_start = current_c.open_time + timedelta(minutes=12)
        if not (control_start <= now < control_start + ONE_MINUTE):
            return None
        if not candle_a.is_closed or not candle_b.is_closed:
            return None
        if current_c.is_closed:
            return None
        if not all(c.is_complete for c in (candle_a, candle_b, current_c)):
            return None
        if len({c.symbol for c in (candle_a, candle_b, current_c)}) != 1:
            return None
        if not are_consecutive((candle_a, candle_b, current_c), FIFTEEN_MINUTES):
            return None
        return self._event(candle_a, candle_b, current_c, FvgEventType.PRE_FVG, now)

    @staticmethod
    def _event(
        candle_a: Candle,
        candle_b: Candle,
        candle_c: Candle,
        event_type: FvgEventType,
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
                candle_c.symbol, "15m", direction, candle_c.open_time, event_type
            ),
            event_type=event_type,
            symbol=candle_c.symbol,
            timeframe="15m",
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
            is_confirmed=event_type is FvgEventType.CONFIRMED_FVG,
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
