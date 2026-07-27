"""Restart the systemd-managed process after prolonged WS candle silence."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from config import FVG_PROCESS_RESTART_STALE_SECONDS


logger = logging.getLogger(__name__)
UTC = timezone.utc
DEFAULT_CHECK_INTERVAL_SECONDS = 30.0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_health_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _as_utc(parsed)


def candle_silence_seconds(
    health: dict,
    *,
    watch_since: datetime,
    now: datetime,
) -> float:
    """Measure silence without inheriting stale timestamps from a previous process."""
    current = _as_utc(now)
    reference = _as_utc(watch_since)
    last_ws_message = _parse_health_timestamp(health.get("last_ws_message"))
    if last_ws_message is not None and last_ws_message > reference:
        reference = last_ws_message
    return max(0.0, (current - reference).total_seconds())


class FvgProcessWatchdog:
    """Exit with failure so systemd restarts a process that stopped receiving candles."""

    def __init__(
        self,
        settings=None,
        event_store=None,
        *,
        stale_seconds: float = FVG_PROCESS_RESTART_STALE_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        restart_process: Callable[[int], object] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if settings is None or event_store is None:
            from alerts.fvg_store import FvgAlertSettings, FvgEventStore

            settings = settings or FvgAlertSettings()
            event_store = event_store or FvgEventStore()
        self.settings = settings
        self.event_store = event_store
        self.stale_seconds = float(stale_seconds)
        self.check_interval_seconds = float(check_interval_seconds)
        if self.stale_seconds <= 0:
            raise ValueError("stale_seconds must be greater than zero")
        if self.check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be greater than zero")
        self.restart_process = restart_process or os._exit
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stopping = False
        self._watch_since = _as_utc(self.clock())

    def evaluate_once(self) -> float | None:
        """Evaluate current health and request one process restart when stale."""
        now = _as_utc(self.clock())
        active_symbols = self.settings.active_symbols()
        if not active_symbols:
            self._watch_since = now
            return None

        health = self.event_store.health()
        age = candle_silence_seconds(
            health,
            watch_since=self._watch_since,
            now=now,
        )
        if age < self.stale_seconds:
            return age

        message = (
            "FVG process restart requested: no Bitunix WS candles for "
            f"{int(age)} seconds"
        )
        logger.critical(message)
        self.event_store.update_health(last_error=message)
        self.event_store.increment_health("stale_process_restarts")
        self.restart_process(1)
        return age

    async def run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.to_thread(self.evaluate_once)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("FVG process watchdog evaluation failed")
                try:
                    await asyncio.to_thread(
                        self.event_store.update_health,
                        last_error=str(error),
                    )
                    await asyncio.to_thread(
                        self.event_store.increment_health,
                        "process_watchdog_failures",
                    )
                except Exception:
                    logger.exception("Failed to persist process watchdog failure")
            await asyncio.sleep(self.check_interval_seconds)

    def stop(self) -> None:
        self._stopping = True


_WATCHDOG: FvgProcessWatchdog | None = None
_WATCHDOG_TASK: asyncio.Task | None = None


async def start_process_watchdog(application) -> None:
    del application
    global _WATCHDOG, _WATCHDOG_TASK
    if _WATCHDOG_TASK is not None and not _WATCHDOG_TASK.done():
        return
    _WATCHDOG = FvgProcessWatchdog()
    _WATCHDOG_TASK = asyncio.create_task(
        _WATCHDOG.run(),
        name="fvg-process-restart-watchdog",
    )


async def stop_process_watchdog(application) -> None:
    del application
    global _WATCHDOG, _WATCHDOG_TASK
    if _WATCHDOG is not None:
        _WATCHDOG.stop()
    if _WATCHDOG_TASK is not None:
        _WATCHDOG_TASK.cancel()
        await asyncio.gather(_WATCHDOG_TASK, return_exceptions=True)
    _WATCHDOG = None
    _WATCHDOG_TASK = None
