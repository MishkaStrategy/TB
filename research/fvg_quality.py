"""Historical quality analysis for confirmed 15-minute FVG events.

The report intentionally does not calculate trading P&L because the alert bot
has no entry, stop-loss or take-profit rules. It measures observable event
outcomes without introducing a strategy that does not exist in production.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from alerts.fvg_detector import FvgDetector
from alerts.fvg_models import Candle, FvgDirection, FvgEvent


UTC = timezone.utc
FIFTEEN_MINUTES = timedelta(minutes=15)
DEFAULT_HORIZONS = (1, 4, 16, 96)
_TIME_COLUMNS = ("time", "timestamp", "open_time", "datetime", "date")


@dataclass(frozen=True)
class HorizonObservation:
    bars: int
    touched: bool
    fully_filled: bool
    mfe_percent: float
    mae_percent: float


@dataclass(frozen=True)
class FvgQualityOutcome:
    event_id: str
    symbol: str
    direction: str
    candle_c_open_time: str
    zone_low: str
    zone_high: str
    zone_size: str
    zone_size_percent: float
    signal_price: str
    available_future_bars: int
    future_gap_after_bars: int | None
    future_gap_expected_open_time: str | None
    future_gap_actual_open_time: str | None
    first_touch_bars: int | None
    full_fill_bars: int | None
    horizons: dict[int, HorizonObservation]

    def to_json(self) -> dict:
        value = asdict(self)
        value["horizons"] = {
            str(key): asdict(observation)
            for key, observation in self.horizons.items()
        }
        return value


def _parse_timestamp(value: str) -> datetime:
    raw = str(value).strip()
    if not raw:
        raise ValueError("Candle time is empty")
    try:
        numeric = Decimal(raw)
    except InvalidOperation:
        numeric = None

    if numeric is not None and numeric.is_finite():
        number = float(numeric)
        if abs(number) >= 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, UTC)

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Unsupported candle time: {raw}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(value: str, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Malformed {field}: {value}") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return parsed


def load_candles_csv(
    path: str | Path,
    *,
    symbol: str,
    timeframe: str = "15m",
) -> list[Candle]:
    """Load chronological, de-duplicated OHLC candles from a CSV file."""
    if timeframe != "15m":
        raise ValueError("FVG quality backtest currently supports only 15m")
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        normalized = {name.strip().lower(): name for name in reader.fieldnames}
        time_key = next((normalized[key] for key in _TIME_COLUMNS if key in normalized), None)
        required = {
            field: normalized.get(field)
            for field in ("open", "high", "low", "close")
        }
        missing = [field for field, key in required.items() if key is None]
        if time_key is None:
            missing.append("time")
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(missing)}")

        by_time: dict[datetime, Candle] = {}
        for line_number, row in enumerate(reader, start=2):
            try:
                open_time = _parse_timestamp(row[time_key])
                prices = {
                    field: _decimal(row[column], field)
                    for field, column in required.items()
                }
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid candle at CSV line {line_number}: {error}") from error
            prices["high"] = max(prices["high"], prices["open"], prices["close"])
            prices["low"] = min(prices["low"], prices["open"], prices["close"])
            by_time[open_time] = Candle(
                symbol=symbol.upper(),
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + FIFTEEN_MINUTES,
                is_closed=True,
                is_complete=True,
                **prices,
            )
    candles = [by_time[key] for key in sorted(by_time)]
    if len(candles) < 3:
        raise ValueError("At least three candles are required")
    return candles


def _touches(event: FvgEvent, candle: Candle) -> bool:
    if event.direction is FvgDirection.BULLISH:
        return candle.low <= event.zone_high
    return candle.high >= event.zone_low


def _fully_fills(event: FvgEvent, candle: Candle) -> bool:
    if event.direction is FvgDirection.BULLISH:
        return candle.low <= event.zone_low
    return candle.high >= event.zone_high


def _excursions(event: FvgEvent, candles: list[Candle]) -> tuple[float, float]:
    if not candles:
        return 0.0, 0.0
    signal = event.signal_price
    if event.direction is FvgDirection.BULLISH:
        favorable = (max(candle.high for candle in candles) - signal) / signal
        adverse = (signal - min(candle.low for candle in candles)) / signal
    else:
        favorable = (signal - min(candle.low for candle in candles)) / signal
        adverse = (max(candle.high for candle in candles) - signal) / signal
    return (
        float(max(Decimal("0"), favorable) * Decimal("100")),
        float(max(Decimal("0"), adverse) * Decimal("100")),
    )


def _contiguous_future(
    items: list[Candle],
    index: int,
    max_bars: int,
) -> tuple[list[Candle], datetime | None, datetime | None]:
    """Return only consecutive 15m rows after candle C.

    A missing or duplicated timestamp is a hard data boundary. Rows after that
    boundary are not allowed to masquerade as the next bar in latency or
    horizon metrics.
    """

    future: list[Candle] = []
    expected = items[index].open_time + FIFTEEN_MINUTES
    for candle in items[index + 1:]:
        if len(future) >= max_bars:
            break
        if candle.open_time != expected:
            return future, expected, candle.open_time
        future.append(candle)
        expected += FIFTEEN_MINUTES
    return future, None, None


def _continuity_gap_count(candles: Iterable[Candle]) -> int:
    items = sorted(candles, key=lambda candle: candle.open_time)
    return sum(
        current.open_time != previous.open_time + FIFTEEN_MINUTES
        for previous, current in zip(items, items[1:])
    )


def analyze_fvg_quality(
    candles: Iterable[Candle],
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[FvgQualityOutcome]:
    """Detect confirmed FVGs and evaluate only contiguous candles after candle C."""
    items = sorted(candles, key=lambda candle: candle.open_time)
    horizon_values = tuple(sorted({int(value) for value in horizons}))
    if not horizon_values or any(value <= 0 for value in horizon_values):
        raise ValueError("Horizons must contain positive candle counts")
    detector = FvgDetector()
    outcomes: list[FvgQualityOutcome] = []
    max_horizon = max(horizon_values)

    for index in range(2, len(items)):
        event = detector.detect_confirmed(
            items[index - 2:index + 1],
            detected_at=items[index].close_time,
        )
        if event is None:
            continue
        future, gap_expected, gap_actual = _contiguous_future(
            items,
            index,
            max_horizon,
        )
        first_touch = next(
            (offset for offset, candle in enumerate(future, start=1) if _touches(event, candle)),
            None,
        )
        full_fill = next(
            (offset for offset, candle in enumerate(future, start=1) if _fully_fills(event, candle)),
            None,
        )
        observations = {}
        for horizon in horizon_values:
            if len(future) < horizon:
                continue
            sample = future[:horizon]
            mfe, mae = _excursions(event, sample)
            observations[horizon] = HorizonObservation(
                bars=horizon,
                touched=any(_touches(event, candle) for candle in sample),
                fully_filled=any(_fully_fills(event, candle) for candle in sample),
                mfe_percent=round(mfe, 8),
                mae_percent=round(mae, 8),
            )
        zone_percent = event.zone_size / event.signal_price * Decimal("100")
        outcomes.append(
            FvgQualityOutcome(
                event_id=event.event_id,
                symbol=event.symbol,
                direction=event.direction.value,
                candle_c_open_time=event.candle_c_open_time.isoformat(),
                zone_low=str(event.zone_low),
                zone_high=str(event.zone_high),
                zone_size=str(event.zone_size),
                zone_size_percent=round(float(zone_percent), 8),
                signal_price=str(event.signal_price),
                available_future_bars=len(future),
                future_gap_after_bars=(len(future) if gap_expected is not None else None),
                future_gap_expected_open_time=(
                    gap_expected.isoformat() if gap_expected is not None else None
                ),
                future_gap_actual_open_time=(
                    gap_actual.isoformat() if gap_actual is not None else None
                ),
                first_touch_bars=first_touch,
                full_fill_bars=full_fill,
                horizons=observations,
            )
        )
    return outcomes


def _rate(count: int, total: int) -> float | None:
    return round(count / total * 100, 4) if total else None


def _average(values: list[float]) -> float | None:
    return round(mean(values), 8) if values else None


def _median(values: list[float | int]) -> float | None:
    return round(float(median(values)), 8) if values else None


def _zone_bucket(value: float) -> str:
    if value < 0.05:
        return "<0.05%"
    if value < 0.10:
        return "0.05-0.10%"
    if value < 0.25:
        return "0.10-0.25%"
    if value < 0.50:
        return "0.25-0.50%"
    return ">=0.50%"


def build_quality_report(
    outcomes: Iterable[FvgQualityOutcome],
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict:
    items = list(outcomes)
    horizon_values = tuple(sorted({int(value) for value in horizons}))
    direction_counts = Counter(item.direction for item in items)
    monthly = Counter(item.candle_c_open_time[:7] for item in items)
    zone_buckets = Counter(_zone_bucket(item.zone_size_percent) for item in items)

    horizon_report = {}
    for horizon in horizon_values:
        observations = [item.horizons[horizon] for item in items if horizon in item.horizons]
        touched = sum(observation.touched for observation in observations)
        filled = sum(observation.fully_filled for observation in observations)
        horizon_report[str(horizon)] = {
            "eligible_events": len(observations),
            "touched": touched,
            "touch_rate_percent": _rate(touched, len(observations)),
            "fully_filled": filled,
            "full_fill_rate_percent": _rate(filled, len(observations)),
            "average_mfe_percent": _average(
                [observation.mfe_percent for observation in observations]
            ),
            "median_mfe_percent": _median(
                [observation.mfe_percent for observation in observations]
            ),
            "average_mae_percent": _average(
                [observation.mae_percent for observation in observations]
            ),
            "median_mae_percent": _median(
                [observation.mae_percent for observation in observations]
            ),
        }

    touch_latencies = [item.first_touch_bars for item in items if item.first_touch_bars is not None]
    fill_latencies = [item.full_fill_bars for item in items if item.full_fill_bars is not None]
    max_horizon = max(horizon_values) if horizon_values else 0
    gap_truncated = sum(item.future_gap_after_bars is not None for item in items)
    end_truncated = sum(
        item.future_gap_after_bars is None
        and item.available_future_bars < max_horizon
        for item in items
    ) if max_horizon else 0
    complete = sum(
        item.available_future_bars >= max_horizon
        for item in items
    ) if max_horizon else 0
    return {
        "report_type": "fvg_event_quality",
        "pnl_backtest": False,
        "pnl_note": (
            "The alert bot has no entry, stop-loss or take-profit rules; "
            "this report measures event outcomes only."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "total_events": len(items),
        "directions": {
            "BULLISH": direction_counts.get("BULLISH", 0),
            "BEARISH": direction_counts.get("BEARISH", 0),
        },
        "first_touch_median_bars": _median(touch_latencies),
        "full_fill_median_bars": _median(fill_latencies),
        "horizons": horizon_report,
        "data_quality": {
            "max_horizon_bars": max_horizon,
            "events_with_complete_max_horizon": complete,
            "events_truncated_by_gap": gap_truncated,
            "events_truncated_by_end_of_data": end_truncated,
        },
        "zone_size_buckets": dict(sorted(zone_buckets.items())),
        "monthly_events": dict(sorted(monthly.items())),
    }


def run_quality_backtest(
    data_file: str | Path,
    *,
    symbol: str,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    include_events: bool = False,
) -> dict:
    candles = load_candles_csv(data_file, symbol=symbol)
    outcomes = analyze_fvg_quality(candles, horizons=horizons)
    report = build_quality_report(outcomes, horizons=horizons)
    report["input"] = {
        "data_file": str(data_file),
        "symbol": symbol.upper(),
        "timeframe": "15m",
        "candles": len(candles),
        "continuity_gaps": _continuity_gap_count(candles),
        "start": candles[0].open_time.isoformat(),
        "end": candles[-1].close_time.isoformat(),
    }
    if include_events:
        report["events"] = [outcome.to_json() for outcome in outcomes]
    return report


def write_report(report: dict, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
