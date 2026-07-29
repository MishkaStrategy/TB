"""Restart the systemd-managed process after prolonged WS candle silence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from config import FVG_PROCESS_RESTART_STALE_SECONDS
from operations.process_restart import default_restart_process


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
    """Request one systemd restart when active-symbol candles remain stale."""

    def __init__(
        self,
        settings=None,
        event_store=None,
        *,
        stale_seconds: float = FVG_PROCESS_RESTART_STALE_SECONDS,
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
        restart_process: Callable[[int], object] | None = None,
        restart_mode: str | None = None,
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
        if restart_process is None:
            restart_process, selected_mode = default_restart_process()
        else:
            selected_mode = "custom"
        self.restart_process = restart_process
        self.restart_mode = str(restart_mode or selected_mode)
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stopping = False
        self._restart_requested = False
        self._watch_since = _as_utc(self.clock())

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    def evaluate_once(self) -> float | None:
        """Evaluate current health and request at most one process restart."""
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
        if age < self.stale_seconds or self._restart_requested:
            return age

        message = (
            "FVG process restart requested: no Bitunix WS candles for "
            f"{int(age)} seconds"
        )
        logger.critical(message)
        self.event_store.update_health(
            last_error=message,
            process_restart_requested_at=now.isoformat(),
            process_restart_mode=self.restart_mode,
            process_restart_silence_seconds=age,
            process_restart_request_error=None,
        )
        self.event_store.increment_health("stale_process_restarts")
        self.event_store.increment_health("stale_process_restart_requests")
        self._restart_requested = True
        try:
            self.restart_process(1)
        except Exception as error:
            self._restart_requested = False
            self.event_store.increment_health("process_restart_request_failures")
            self.event_store.update_health(
                process_restart_request_error=(
                    f"{type(error).__name__}: {error}"
                )[:2000]
            )
            raise
        self._stopping = True
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
            if self._stopping:
                break
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
