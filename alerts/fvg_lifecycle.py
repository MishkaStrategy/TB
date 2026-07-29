"""Deterministic, exchange-independent FVG lifecycle state machine.

The module has no Telegram, network or persistence calls. It accepts one closed
market candle and returns a new immutable zone state plus idempotent domain
events. The complete feature can therefore be disabled without changing the
existing alert path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import blake2b

from alerts.fvg_models import Candle, FvgDirection, FvgEvent


UTC = timezone.utc
ZERO = Decimal("0")
HUNDRED = Decimal("100")
LIFECYCLE_VERSION = "fvg_lifecycle_v1"
TERMINAL_STATUSES = frozenset({"FILLED", "INVALIDATED", "EXPIRED"})
TIMEFRAME_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


class FvgLifecycleStatus(str, Enum):
    DETECTED = "DETECTED"
    APPROACHING = "APPROACHING"
    TOUCHED = "TOUCHED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class FvgLifecycleEventType(str, Enum):
    DETECTED = "DETECTED"
    APPROACHED = "APPROACHED"
    FIRST_TOUCH = "FIRST_TOUCH"
    RETOUCH = "RETOUCH"
    FILL_25 = "FILL_25"
    FILL_50 = "FILL_50"
    FILL_75 = "FILL_75"
    FILL_90 = "FILL_90"
    FULLY_TRAVERSED = "FULLY_TRAVERSED"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class ZoneRelation(str, Enum):
    UNKNOWN = "UNKNOWN"
    ABOVE = "ABOVE"
    INSIDE = "INSIDE"
    BELOW = "BELOW"


@dataclass(frozen=True)
class FvgLifecycleConfig:
    """Versioned rules used by the first lifecycle implementation."""

    approaching_zone_widths: Decimal = Decimal("1")
    invalidation_buffer_ratio: Decimal = Decimal("0")
    max_age_bars: int = 96
    fill_thresholds: tuple[int, ...] = (25, 50, 75, 90)

    def __post_init__(self) -> None:
        if (
            not self.approaching_zone_widths.is_finite()
            or self.approaching_zone_widths <= 0
        ):
            raise ValueError("approaching_zone_widths must be finite and positive")
        if (
            not self.invalidation_buffer_ratio.is_finite()
            or self.invalidation_buffer_ratio < 0
        ):
            raise ValueError("invalidation_buffer_ratio must be finite and non-negative")
        if self.max_age_bars <= 0:
            raise ValueError("max_age_bars must be positive")
        if tuple(sorted(set(self.fill_thresholds))) != self.fill_thresholds:
            raise ValueError("fill_thresholds must be unique and sorted")
        if any(value not in {25, 50, 75, 90} for value in self.fill_thresholds):
            raise ValueError("v1 supports only 25/50/75/90 fill thresholds")


@dataclass(frozen=True)
class FvgZoneState:
    fvg_id: str
    source_event_id: str
    exchange: str
    symbol: str
    timeframe: str
    direction: FvgDirection
    lower_bound: Decimal
    upper_bound: Decimal
    formation_time: datetime
    formation_close_time: datetime
    signal_price: Decimal
    status: FvgLifecycleStatus = FvgLifecycleStatus.DETECTED
    current_price: Decimal | None = None
    current_fill_percent: Decimal = ZERO
    max_fill_percent: Decimal = ZERO
    fill_threshold_mask: int = 0
    touch_count: int = 0
    first_approach_at: datetime | None = None
    first_touch_at: datetime | None = None
    first_touch_price: Decimal | None = None
    first_touch_candle_time: datetime | None = None
    first_touch_depth_percent: Decimal | None = None
    filled_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_price: Decimal | None = None
    invalidation_reason: str | None = None
    expired_at: datetime | None = None
    expiration_reason: str | None = None
    last_relation: ZoneRelation = ZoneRelation.UNKNOWN
    last_processed_candle: datetime | None = None
    processed_bars: int = 0
    state_version: int = 1
    lifecycle_version: str = LIFECYCLE_VERSION
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.formation_time.tzinfo is None or self.formation_close_time.tzinfo is None:
            raise ValueError("Zone times must be timezone-aware")
        if self.timeframe not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported zone timeframe: {self.timeframe}")
        if self.lower_bound <= 0 or self.upper_bound <= self.lower_bound:
            raise ValueError("FVG bounds must be positive and ordered")
        if self.signal_price <= 0:
            raise ValueError("signal_price must be positive")

    @property
    def zone_size(self) -> Decimal:
        return self.upper_bound - self.lower_bound

    @property
    def is_terminal(self) -> bool:
        return self.status.value in TERMINAL_STATUSES


@dataclass(frozen=True)
class FvgZoneEvent:
    event_type: FvgLifecycleEventType
    event_time: datetime
    price: Decimal | None = None
    fill_percent: Decimal | None = None
    touch_count: int | None = None
    candle_time: datetime | None = None
    payload: dict | None = None

    def dedupe_key(self, fvg_id: str) -> str:
        if self.event_type == FvgLifecycleEventType.RETOUCH:
            suffix = (self.candle_time or self.event_time).astimezone(UTC).isoformat()
            return f"{fvg_id}:{self.event_type.value}:{suffix}"
        return f"{fvg_id}:{self.event_type.value}"


@dataclass(frozen=True)
class FvgLifecycleTransition:
    zone: FvgZoneState
    events: tuple[FvgZoneEvent, ...]
    changed: bool


def stable_fvg_id(event: FvgEvent, exchange: str = "bitunix") -> str:
    """Return an ID shared by PRE/CONFIRMED representations of one formation."""
    timestamp = event.candle_c_open_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
    natural_key = "|".join(
        (
            exchange.lower(),
            event.symbol.upper(),
            event.timeframe,
            timestamp,
            event.direction.value,
        )
    )
    digest = blake2b(natural_key.encode("utf-8"), digest_size=16).hexdigest()
    return f"fvg_{digest}"


def zone_from_event(event: FvgEvent, exchange: str = "bitunix") -> FvgZoneState:
    now = event.detected_at.astimezone(UTC)
    return FvgZoneState(
        fvg_id=stable_fvg_id(event, exchange),
        source_event_id=event.event_id,
        exchange=exchange.lower(),
        symbol=event.symbol.upper(),
        timeframe=event.timeframe,
        direction=event.direction,
        lower_bound=event.zone_low,
        upper_bound=event.zone_high,
        formation_time=event.candle_c_open_time.astimezone(UTC),
        formation_close_time=event.candle_c_close_time.astimezone(UTC),
        signal_price=event.signal_price,
        created_at=now,
        updated_at=now,
    )


def detected_event(zone: FvgZoneState) -> FvgZoneEvent:
    return FvgZoneEvent(
        event_type=FvgLifecycleEventType.DETECTED,
        event_time=zone.created_at or zone.formation_close_time,
        price=zone.signal_price,
        fill_percent=ZERO,
        touch_count=0,
        candle_time=zone.formation_time,
        payload={"lifecycle_version": zone.lifecycle_version},
    )


def _clamp_percent(value: Decimal) -> Decimal:
    return max(ZERO, min(HUNDRED, value))


def _relation(price: Decimal, zone: FvgZoneState) -> ZoneRelation:
    if price > zone.upper_bound:
        return ZoneRelation.ABOVE
    if price < zone.lower_bound:
        return ZoneRelation.BELOW
    return ZoneRelation.INSIDE


def _overlaps(candle: Candle, zone: FvgZoneState) -> bool:
    return candle.low <= zone.upper_bound and candle.high >= zone.lower_bound


def _fill_percent(candle: Candle, zone: FvgZoneState) -> Decimal:
    penetration = (
        zone.upper_bound - candle.low
        if zone.direction == FvgDirection.BULLISH
        else candle.high - zone.lower_bound
    )
    return _clamp_percent(penetration / zone.zone_size * HUNDRED)


def _distance(candle: Candle, zone: FvgZoneState) -> Decimal:
    if candle.close > zone.upper_bound:
        return candle.close - zone.upper_bound
    if candle.close < zone.lower_bound:
        return zone.lower_bound - candle.close
    return ZERO


def _expected_entry_relation(zone: FvgZoneState) -> ZoneRelation:
    return (
        ZoneRelation.ABOVE
        if zone.direction == FvgDirection.BULLISH
        else ZoneRelation.BELOW
    )


def _touch_price(zone: FvgZoneState) -> Decimal:
    # OHLC data has no exact intrabar touch price. The near boundary is a
    # deterministic estimate and its source is retained in the event payload.
    return (
        zone.upper_bound
        if zone.direction == FvgDirection.BULLISH
        else zone.lower_bound
    )


def _threshold_event_type(threshold: int) -> FvgLifecycleEventType:
    return {
        25: FvgLifecycleEventType.FILL_25,
        50: FvgLifecycleEventType.FILL_50,
        75: FvgLifecycleEventType.FILL_75,
        90: FvgLifecycleEventType.FILL_90,
    }[threshold]


def _elapsed_zone_bars(zone: FvgZoneState, candle: Candle) -> int:
    seconds = max(
        0.0,
        (candle.close_time - zone.formation_close_time).total_seconds(),
    )
    step_seconds = TIMEFRAME_MINUTES[zone.timeframe] * 60
    return max(zone.processed_bars, int(seconds // step_seconds))


def advance_zone(
    zone: FvgZoneState,
    candle: Candle,
    config: FvgLifecycleConfig | None = None,
) -> FvgLifecycleTransition:
    """Advance one zone for one closed market candle."""
    config = config or FvgLifecycleConfig()
    if zone.is_terminal:
        return FvgLifecycleTransition(zone, (), False)
    if (
        candle.symbol.upper() != zone.symbol
        or not candle.is_closed
        or not candle.is_complete
    ):
        return FvgLifecycleTransition(zone, (), False)
    if candle.close_time <= zone.formation_close_time:
        return FvgLifecycleTransition(zone, (), False)
    if zone.last_processed_candle and candle.open_time <= zone.last_processed_candle:
        return FvgLifecycleTransition(zone, (), False)

    current_fill = _fill_percent(candle, zone)
    max_fill = max(zone.max_fill_percent, current_fill)
    relation_after = _relation(candle.close, zone)
    overlaps = _overlaps(candle, zone)
    expected_entry = _expected_entry_relation(zone)
    events: list[FvgZoneEvent] = []

    touch_count = zone.touch_count
    first_touch_at = zone.first_touch_at
    first_touch_price = zone.first_touch_price
    first_touch_candle_time = zone.first_touch_candle_time
    first_touch_depth = zone.first_touch_depth_percent

    if overlaps and touch_count == 0:
        touch_count = 1
        first_touch_at = candle.open_time
        first_touch_price = _touch_price(zone)
        first_touch_candle_time = candle.open_time
        first_touch_depth = current_fill
        events.append(
            FvgZoneEvent(
                FvgLifecycleEventType.FIRST_TOUCH,
                candle.open_time,
                price=first_touch_price,
                fill_percent=current_fill,
                touch_count=touch_count,
                candle_time=candle.open_time,
                payload={
                    "touch_price_source": "boundary_estimate",
                    "entry_relation": zone.last_relation.value,
                },
            )
        )
    elif overlaps and zone.last_relation == expected_entry:
        touch_count += 1
        events.append(
            FvgZoneEvent(
                FvgLifecycleEventType.RETOUCH,
                candle.open_time,
                price=_touch_price(zone),
                fill_percent=current_fill,
                touch_count=touch_count,
                candle_time=candle.open_time,
                payload={"touch_price_source": "boundary_estimate"},
            )
        )

    threshold_mask = zone.fill_threshold_mask
    for index, threshold in enumerate(config.fill_thresholds):
        bit = 1 << index
        if max_fill >= Decimal(threshold) and not threshold_mask & bit:
            threshold_mask |= bit
            events.append(
                FvgZoneEvent(
                    _threshold_event_type(threshold),
                    candle.close_time,
                    price=candle.close,
                    fill_percent=max_fill,
                    touch_count=touch_count,
                    candle_time=candle.open_time,
                    payload={"threshold": threshold},
                )
            )

    buffer_value = zone.zone_size * config.invalidation_buffer_ratio
    invalidated = (
        candle.close < zone.lower_bound - buffer_value
        if zone.direction == FvgDirection.BULLISH
        else candle.close > zone.upper_bound + buffer_value
    )

    first_approach_at = zone.first_approach_at
    filled_at = zone.filled_at
    invalidated_at = zone.invalidated_at
    invalidation_price = zone.invalidation_price
    invalidation_reason = zone.invalidation_reason
    expired_at = zone.expired_at
    expiration_reason = zone.expiration_reason
    status = zone.status

    if invalidated:
        if max_fill >= HUNDRED:
            events.append(
                FvgZoneEvent(
                    FvgLifecycleEventType.FULLY_TRAVERSED,
                    candle.close_time,
                    price=candle.close,
                    fill_percent=HUNDRED,
                    touch_count=touch_count,
                    candle_time=candle.open_time,
                )
            )
        status = FvgLifecycleStatus.INVALIDATED
        invalidated_at = candle.close_time
        invalidation_price = candle.close
        invalidation_reason = "close_beyond_far_edge"
        events.append(
            FvgZoneEvent(
                FvgLifecycleEventType.INVALIDATED,
                candle.close_time,
                price=candle.close,
                fill_percent=max_fill,
                touch_count=touch_count,
                candle_time=candle.open_time,
                payload={
                    "reason": invalidation_reason,
                    "buffer_ratio": str(config.invalidation_buffer_ratio),
                },
            )
        )
    elif max_fill >= HUNDRED:
        status = FvgLifecycleStatus.FILLED
        filled_at = candle.close_time
        events.append(
            FvgZoneEvent(
                FvgLifecycleEventType.FILLED,
                candle.close_time,
                price=candle.close,
                fill_percent=HUNDRED,
                touch_count=touch_count,
                candle_time=candle.open_time,
            )
        )
    elif touch_count:
        status = (
            FvgLifecycleStatus.PARTIALLY_FILLED
            if max_fill > ZERO
            else FvgLifecycleStatus.TOUCHED
        )
    else:
        distance = _distance(candle, zone)
        near = distance <= zone.zone_size * config.approaching_zone_widths
        if near:
            if zone.status == FvgLifecycleStatus.DETECTED:
                first_approach_at = candle.close_time
                events.append(
                    FvgZoneEvent(
                        FvgLifecycleEventType.APPROACHED,
                        candle.close_time,
                        price=candle.close,
                        fill_percent=ZERO,
                        touch_count=0,
                        candle_time=candle.open_time,
                        payload={
                            "distance": str(distance),
                            "mode": "zone_width_multiple",
                            "threshold": str(config.approaching_zone_widths),
                        },
                    )
                )
            status = FvgLifecycleStatus.APPROACHING

    processed_bars = _elapsed_zone_bars(zone, candle)
    if status.value not in TERMINAL_STATUSES and processed_bars >= config.max_age_bars:
        status = FvgLifecycleStatus.EXPIRED
        expired_at = candle.close_time
        expiration_reason = "max_age_bars"
        events.append(
            FvgZoneEvent(
                FvgLifecycleEventType.EXPIRED,
                candle.close_time,
                price=candle.close,
                fill_percent=max_fill,
                touch_count=touch_count,
                candle_time=candle.open_time,
                payload={
                    "reason": expiration_reason,
                    "max_age_bars": config.max_age_bars,
                },
            )
        )

    updated = replace(
        zone,
        status=status,
        current_price=candle.close,
        current_fill_percent=current_fill,
        max_fill_percent=max_fill,
        fill_threshold_mask=threshold_mask,
        touch_count=touch_count,
        first_approach_at=first_approach_at,
        first_touch_at=first_touch_at,
        first_touch_price=first_touch_price,
        first_touch_candle_time=first_touch_candle_time,
        first_touch_depth_percent=first_touch_depth,
        filled_at=filled_at,
        invalidated_at=invalidated_at,
        invalidation_price=invalidation_price,
        invalidation_reason=invalidation_reason,
        expired_at=expired_at,
        expiration_reason=expiration_reason,
        last_relation=relation_after,
        last_processed_candle=candle.open_time,
        processed_bars=processed_bars,
        state_version=zone.state_version + 1,
        updated_at=candle.close_time,
    )
    return FvgLifecycleTransition(updated, tuple(events), True)
