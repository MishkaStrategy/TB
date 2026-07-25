"""Synthetic end-to-end soak test for FVG persistence and delivery."""

from __future__ import annotations

import asyncio
import json
import os
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from alerts.fvg_models import (
    FvgDirection,
    FvgEvent,
    FvgEventType,
    event_id,
)
from alerts.fvg_service import FvgAlertService
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc


class StaticRecipients:
    def __init__(self, chat_ids):
        self.chat_ids = tuple(int(value) for value in chat_ids)

    def recipients(self, event):
        return list(self.chat_ids)


class CountingBot:
    def __init__(self):
        self.messages = 0

    async def send_message(self, **kwargs):
        self.messages += 1
        await asyncio.sleep(0)


@dataclass(frozen=True)
class SoakReport:
    events_requested: int
    recipients: int
    expected_deliveries: int
    events_persisted: int
    deliveries_persisted: int
    outbox_remaining: int
    bot_messages: int
    duration_seconds: float
    deliveries_per_second: float
    peak_memory_mb: float
    database_bytes: int
    passed: bool
    failures: tuple[str, ...]

    def to_json(self):
        return asdict(self)


def make_event(index: int, *, base_time: datetime) -> FvgEvent:
    direction = (
        FvgDirection.BULLISH if index % 2 == 0 else FvgDirection.BEARISH
    )
    event_type = (
        FvgEventType.CONFIRMED_FVG
        if index % 3
        else FvgEventType.PRE_FVG
    )
    symbol = f"S{index % 100:03d}USDT"
    candle_c_open = base_time + timedelta(minutes=15 * index)
    if direction is FvgDirection.BULLISH:
        zone_low, zone_high = Decimal("100"), Decimal("101")
        signal = Decimal("102")
    else:
        zone_low, zone_high = Decimal("99"), Decimal("100")
        signal = Decimal("98")
    return FvgEvent(
        event_id=event_id(
            symbol,
            "15m",
            direction,
            candle_c_open,
            event_type,
        ),
        event_type=event_type,
        symbol=symbol,
        timeframe="15m",
        direction=direction,
        candle_a_open_time=candle_c_open - timedelta(minutes=30),
        candle_b_open_time=candle_c_open - timedelta(minutes=15),
        candle_c_open_time=candle_c_open,
        candle_c_close_time=candle_c_open + timedelta(minutes=15),
        zone_low=zone_low,
        zone_high=zone_high,
        zone_size=zone_high - zone_low,
        signal_price=signal,
        detected_at=candle_c_open + timedelta(minutes=15),
        is_confirmed=event_type is FvgEventType.CONFIRMED_FVG,
        data_complete=True,
    )


def database_size(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (
            path,
            Path(str(path) + "-wal"),
            Path(str(path) + "-shm"),
        )
        if candidate.exists()
    )


async def run_soak(
    database: str | os.PathLike,
    *,
    events: int = 1000,
    recipients: int = 10,
    batch_size: int = 100,
    max_seconds: float | None = None,
    max_peak_memory_mb: float | None = None,
    reset: bool = False,
) -> SoakReport:
    if events <= 0 or recipients <= 0 or batch_size <= 0:
        raise ValueError("events, recipients and batch_size must be positive")
    path = Path(database)
    if path.exists() and not reset:
        raise FileExistsError(
            f"Refusing to reuse existing soak database without reset: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if reset:
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            candidate.unlink(missing_ok=True)

    store = FvgEventStore(path)
    chat_ids = tuple(range(1_000_000, 1_000_000 + recipients))
    service = FvgAlertService(
        settings=StaticRecipients(chat_ids),
        event_store=store,
    )
    bot = CountingBot()
    base_time = datetime.now(UTC).replace(second=0, microsecond=0)

    tracemalloc.start()
    started = time.perf_counter()
    for offset in range(0, events, batch_size):
        batch = [
            make_event(index, base_time=base_time)
            for index in range(offset, min(offset + batch_size, events))
        ]
        await service.deliver(bot, batch)
    duration = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    health = store.health()
    expected_deliveries = events * recipients
    failures = []
    if health["events"] != events:
        failures.append(
            f"persisted events {health['events']} != expected {events}"
        )
    if health["deliveries"] != expected_deliveries:
        failures.append(
            "persisted deliveries "
            f"{health['deliveries']} != expected {expected_deliveries}"
        )
    if health["outbox"] != 0:
        failures.append(f"outbox is not empty: {health['outbox']}")
    if bot.messages != expected_deliveries:
        failures.append(
            f"bot messages {bot.messages} != expected {expected_deliveries}"
        )
    peak_mb = peak / 1024 / 1024
    if max_seconds is not None and duration > max_seconds:
        failures.append(
            f"duration {duration:.3f}s exceeds limit {max_seconds:.3f}s"
        )
    if max_peak_memory_mb is not None and peak_mb > max_peak_memory_mb:
        failures.append(
            f"peak memory {peak_mb:.3f}MB exceeds limit "
            f"{max_peak_memory_mb:.3f}MB"
        )

    throughput = expected_deliveries / duration if duration else float("inf")
    return SoakReport(
        events_requested=events,
        recipients=recipients,
        expected_deliveries=expected_deliveries,
        events_persisted=int(health["events"]),
        deliveries_persisted=int(health["deliveries"]),
        outbox_remaining=int(health["outbox"]),
        bot_messages=bot.messages,
        duration_seconds=round(duration, 6),
        deliveries_per_second=round(throughput, 3),
        peak_memory_mb=round(peak_mb, 3),
        database_bytes=database_size(path),
        passed=not failures,
        failures=tuple(failures),
    )


def write_report(report: SoakReport, path: str | os.PathLike) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
