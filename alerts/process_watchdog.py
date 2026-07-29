"""Restart the systemd-managed process after prolonged WS candle silence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from config import FVG_PROCESS_RESTART_STALE_SECONDS
from database.process_restart_guard import ProcessRestartGuard
from database.process_restart_guard_config import (
    FVG_PROCESS_RESTART_COOLDOWN_SECONDS,
    FVG_PROCESS_RESTART_GUARD_ENABLED,
    FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS,
    FVG_PROCESS_RESTART_MAX_REQUESTS,
    FVG_PROCESS_RESTART_WINDOW_SECONDS,
)
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
        restart_guard=None,
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
        self._restart_blocked_until: datetime | None = None
        self._watch_since = _as_utc(self.clock())

        if restart_guard is not None:
            self.restart_guard = restart_guard
        elif FVG_PROCESS_RESTART_GUARD_ENABLED:
            path = getattr(event_store, "path", None)
            if path is None:
                raise RuntimeError(
                    "FVG restart guard requires an event_store with a SQLite path"
                )
            self.restart_guard = ProcessRestartGuard(
                path,
                max_requests=FVG_PROCESS_RESTART_MAX_REQUESTS,
                window_seconds=FVG_PROCESS_RESTART_WINDOW_SECONDS,
                cooldown_seconds=FVG_PROCESS_RESTART_COOLDOWN_SECONDS,
                history_retention_days=FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS,
            )
        else:
            self.restart_guard = None

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    def _guard_decision(self, *, now: datetime, age: float, message: str) -> dict:
        if self.restart_guard is None:
            return {
                "allowed": True,
                "request_id": None,
                "decision_reason": "guard_disabled",
                "blocked_until": None,
                "requests_in_window": None,
            }
        try:
            return self.restart_guard.decide(
                reason=message,
                silence_seconds=age,
                restart_mode=self.restart_mode,
                now=now,
            )
        except Exception as error:
            retry_at = now + timedelta(
                seconds=max(30.0, self.check_interval_seconds)
            )
            self._restart_blocked_until = retry_at
            self.event_store.increment_health("process_restart_guard_failures")
            self.event_store.update_health(
                process_restart_guard_blocked=True,
                process_restart_guard_reason="guard_error",
                process_restart_guard_blocked_until=retry_at.isoformat(),
                process_restart_guard_error=(
                    f"{type(error).__name__}: {error}"
                )[:2000],
            )
            logger.exception("FVG process restart guard evaluation failed")
            return {
                "allowed": False,
                "request_id": None,
                "decision_reason": "guard_error",
                "blocked_until": retry_at.isoformat(),
                "requests_in_window": None,
            }

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
        if self._restart_blocked_until is not None:
            if now < self._restart_blocked_until:
                return age
            self._restart_blocked_until = None

        message = (
            "FVG process restart requested: no Bitunix WS candles for "
            f"{int(age)} seconds"
        )
        decision = self._guard_decision(now=now, age=age, message=message)
        if not decision["allowed"]:
            blocked_until = _parse_health_timestamp(decision.get("blocked_until"))
            self._restart_blocked_until = blocked_until
            self.event_store.increment_health("process_restart_guard_suppressions")
            self.event_store.update_health(
                process_restart_guard_blocked=True,
                process_restart_guard_reason=decision["decision_reason"],
                process_restart_guard_blocked_until=(
                    blocked_until.isoformat() if blocked_until else None
                ),
                process_restart_guard_requests_in_window=(
                    decision.get("requests_in_window")
                ),
            )
            logger.error(
                "FVG process restart suppressed reason=%s blocked_until=%s",
                decision["decision_reason"],
                decision.get("blocked_until"),
            )
            return age

        logger.critical(message)
        self.event_store.update_health(
            last_error=message,
            process_restart_requested_at=now.isoformat(),
            process_restart_mode=self.restart_mode,
            process_restart_silence_seconds=age,
            process_restart_request_error=None,
            process_restart_guard_blocked=False,
            process_restart_guard_reason=decision["decision_reason"],
            process_restart_guard_blocked_until=None,
            process_restart_guard_request_id=decision.get("request_id"),
            process_restart_guard_requests_in_window=(
                decision.get("requests_in_window")
            ),
            process_restart_guard_error=None,
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
            request_id = decision.get("request_id")
            if request_id and self.restart_guard is not None:
                try:
                    self.restart_guard.mark_failed(request_id, error, now=now)
                except Exception as guard_error:
                    self.event_store.increment_health(
                        "process_restart_guard_finalize_failures"
                    )
                    self.event_store.update_health(
                        process_restart_guard_error=(
                            f"{type(guard_error).__name__}: {guard_error}"
                        )[:2000]
                    )
                    logger.exception("Failed to finalize restart guard request")
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
