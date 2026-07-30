"""Domain types for the exchange-independent FVG alert engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


UTC = timezone.utc


class FvgDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class FvgEventType(str, Enum):
    PRE_FVG = "PRE_FVG"
    CONFIRMED_FVG = "CONFIRMED_FVG"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    is_closed: bool
    is_complete: bool

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("Candle times must be timezone-aware")
        if self.close_time <= self.open_time:
            raise ValueError("Candle close_time must be after open_time")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Candle prices must be positive")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("Invalid OHLC envelope")


@dataclass(frozen=True)
class FvgEvent:
    event_id: str
    event_type: FvgEventType
    symbol: str
    timeframe: str
    direction: FvgDirection
    candle_a_open_time: datetime
    candle_b_open_time: datetime
    candle_c_open_time: datetime
    candle_c_close_time: datetime
    zone_low: Decimal
    zone_high: Decimal
    zone_size: Decimal
    signal_price: Decimal
    detected_at: datetime
    is_confirmed: bool
    data_complete: bool
    exchange: str = "bitunix"

    def to_json(self) -> dict:
        result = asdict(self)
        for key, value in tuple(result.items()):
            if isinstance(value, datetime):
                result[key] = value.astimezone(UTC).isoformat()
            elif isinstance(value, Decimal):
                result[key] = str(value)
            elif isinstance(value, Enum):
                result[key] = value.value
        return result


def event_id(
    symbol: str,
    timeframe: str,
    direction: FvgDirection,
    candle_c_open_time: datetime,
    event_type: FvgEventType,
    exchange: str = "bitunix",
) -> str:
    timestamp = candle_c_open_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
    base = f"{symbol}:{timeframe}:{direction.value}:{timestamp}:{event_type.value}"
    # Preserve existing Bitunix identifiers so an upgrade cannot resend old events.
    return base if exchange == "bitunix" else f"{exchange}:{base}"
