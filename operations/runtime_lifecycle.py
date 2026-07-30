"""Application startup/shutdown lifecycle and bounded graceful drain."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from database.runtime_lifecycle import RuntimeLifecycleStore


LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


class RuntimeLifecycleCoordinator:
    def __init__(
        self,
        *,
        store: RuntimeLifecycleStore | None,
        stop_watchdog,
        stop_stream,
        drain_outbox,
        graceful_enabled: bool = False,
        timeout_seconds: float = 25,
        history_retention_days: int = 30,
        metrics=None,
    ):
        self.store = store
        self.stop_watchdog = stop_watchdog
        self.stop_stream = stop_stream
        self.drain_outbox = drain_outbox
        self.graceful_enabled = bool(graceful_enabled)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.history_retention_days = max(1, int(history_retention_days))
        self.metrics = metrics
        self.instance_id = str(uuid.uuid4())
        self._start_begun = False
        self._stop_lock = asyncio.Lock()
        self._stop_result = None

    def _current(self):
        if self.store is None:
            return None
        try:
            return self.store.current()
        except Exception:
            LOGGER.exception("Runtime lifecycle current-state read failed")
            return None

    def _transition(self, status, *, phase, **kwargs):
        if self.store is None:
            return False
        try:
            return self.store.transition(
                self.instance_id,
                status,
                phase=phase,
                **kwargs,
            )
        except Exception:
            LOGGER.exception(
                "Runtime lifecycle transition failed status=%s phase=%s",
                status,
                phase,
            )
            return False

    def _write_health(self, **values):
        try:
            method = getattr(self.metrics, "update_health", None)
            if callable(method):
                method(**values)
        except Exception:
            LOGGER.exception("Runtime lifecycle health write failed")

    def begin_start(self, *, details=None):
        if self._start_begun:
            return self.instance_id
        self._start_begun = True
        if self.store is None:
            return self.instance_id
        try:
            self.store.begin_start(
                instance_id=self.instance_id,
                pid=os.getpid(),
                details=details,
            )
            self.store.prune(retention_days=self.history_retention_days)
        except Exception:
            LOGGER.exception("Runtime lifecycle startup persistence failed")
        return self.instance_id

    def mark_running(self, *, details=None):
        self._transition("running", phase="post_init", details=details)
        self._write_health(
            runtime_instance_id=self.instance_id,
            runtime_status="running",
            runtime_running_at=datetime.now(UTC).isoformat(),
        )

    def mark_startup_failed(self, error):
        self._transition(
            "failed",
            phase="startup",
            outcome="startup_failed",
            error=error,
            details={"pid": os.getpid()},
        )
        self._write_health(
            runtime_instance_id=self.instance_id,
            runtime_status="failed",
            runtime_last_error=str(error),
        )

    def mark_process_failed(self, error):
        current = self._current()
        if current and current.get("instance_id") == self.instance_id:
            if current.get("status") == "failed":
                return
            startup = current.get("status") == "starting"
        else:
            startup = not self._start_begun
        phase = "startup" if startup else "runtime"
        outcome = "startup_failed" if startup else "process_failed"
        self._transition(
            "failed",
            phase=phase,
            outcome=outcome,
            error=error,
            details={"pid": os.getpid()},
        )
        self._write_health(
            runtime_instance_id=self.instance_id,
            runtime_status="failed",
            runtime_last_error=str(error),
        )

    def record_application_error(self, error):
        current = self._current()
        status = "running"
        if current and current.get("instance_id") == self.instance_id:
            status = current.get("status") or status
        self._transition(
            status,
            phase="application_error",
            error=error,
            details={"handled": True},
        )
        try:
            method = getattr(self.metrics, "increment_health", None)
            if callable(method):
                method("application_errors")
        except Exception:
            LOGGER.exception("Application error counter update failed")

    @staticmethod
    def _remaining(loop, deadline_monotonic):
        return max(0.0, deadline_monotonic - loop.time())

    @staticmethod
    async def _bounded(awaitable, timeout_seconds):
        return await asyncio.wait_for(
            awaitable,
            timeout=max(0.01, float(timeout_seconds)),
        )

    async def stop(self, application):
        async with self._stop_lock:
            if self._stop_result is not None:
                return self._stop_result

            previous = self._current()
            prior_failure = bool(
                previous
                and previous.get("instance_id") == self.instance_id
                and previous.get("status") == "failed"
            )
            prior_outcome = (
                previous.get("shutdown_outcome") if prior_failure else None
            )

            loop = asyncio.get_running_loop()
            started = loop.time()
            deadline_monotonic = started + self.timeout_seconds
            deadline_at = datetime.now(UTC) + timedelta(seconds=self.timeout_seconds)
            result = {
                "instance_id": self.instance_id,
                "graceful_enabled": self.graceful_enabled,
                "prior_failure": prior_failure,
                "prior_outcome": prior_outcome,
                "watchdog_stopped": False,
                "stream": None,
                "outbox": None,
                "errors": [],
                "timeouts": [],
                "timed_out": False,
            }
            self._transition(
                "stopping",
                phase="post_stop",
                deadline=deadline_at,
                details={
                    "timeout_seconds": self.timeout_seconds,
                    "graceful_enabled": self.graceful_enabled,
                    "prior_failure": prior_failure,
                },
            )
            self._write_health(
                runtime_instance_id=self.instance_id,
                runtime_status="stopping",
                runtime_shutdown_deadline_at=deadline_at.isoformat(),
            )

            remaining = self._remaining(loop, deadline_monotonic)
            if remaining <= 0:
                result["timed_out"] = True
                result["timeouts"].append("process_watchdog")
            else:
                try:
                    await self._bounded(self.stop_watchdog(application), remaining)
                    result["watchdog_stopped"] = True
                except asyncio.TimeoutError:
                    result["timed_out"] = True
                    result["timeouts"].append("process_watchdog")
                except Exception as error:
                    LOGGER.exception("Process watchdog stop failed")
                    result["errors"].append(
                        {"component": "process_watchdog", "error": str(error)[:500]}
                    )

            remaining = self._remaining(loop, deadline_monotonic)
            if remaining <= 0:
                result["timed_out"] = True
                result["timeouts"].append("fvg_stream")
            else:
                stream_budget = max(0.01, remaining * 0.75)
                try:
                    result["stream"] = await self._bounded(
                        self.stop_stream(
                            application,
                            timeout_seconds=stream_budget,
                        ),
                        stream_budget,
                    )
                    if result["stream"].get("timeout"):
                        result["timed_out"] = True
                        result["timeouts"].append("fvg_stream")
                except asyncio.TimeoutError:
                    result["timed_out"] = True
                    result["timeouts"].append("fvg_stream")
                except Exception as error:
                    LOGGER.exception("FVG stream stop failed")
                    result["errors"].append(
                        {"component": "fvg_stream", "error": str(error)[:500]}
                    )

            if self.graceful_enabled:
                remaining = self._remaining(loop, deadline_monotonic)
                if remaining <= 0:
                    result["timed_out"] = True
                    result["timeouts"].append("outbox")
                else:
                    try:
                        result["outbox"] = await self._bounded(
                            self.drain_outbox(
                                application,
                                timeout_seconds=remaining,
                            ),
                            remaining,
                        )
                        if result["outbox"].get("timeout"):
                            result["timed_out"] = True
                            result["timeouts"].append("outbox")
                    except asyncio.TimeoutError:
                        result["timed_out"] = True
                        result["timeouts"].append("outbox")
                    except Exception as error:
                        LOGGER.exception("Persistent outbox shutdown drain failed")
                        result["errors"].append(
                            {"component": "outbox", "error": str(error)[:500]}
                        )
            else:
                result["outbox"] = {
                    "enabled": False,
                    "supported": None,
                    "completed": 0,
                    "timeout": False,
                }

            result["duration_seconds"] = max(0.0, loop.time() - started)
            if prior_failure:
                status = "failed"
                outcome = prior_outcome or "process_failed"
            elif result["timed_out"]:
                status = "shutdown_timeout"
                outcome = "timeout"
            elif result["errors"]:
                status = "failed"
                outcome = "component_error"
            else:
                status = "stopped"
                outcome = "clean"

            self._transition(
                status,
                phase="post_stop",
                outcome=outcome,
                details=result,
            )
            self._write_health(
                runtime_instance_id=self.instance_id,
                runtime_status=status,
                runtime_shutdown_outcome=outcome,
                runtime_shutdown_duration_seconds=result["duration_seconds"],
                runtime_shutdown_timed_out=result["timed_out"],
            )
            self._stop_result = result
            return result

    def mark_shutdown_complete(self):
        current = self._current()
        if current and current.get("instance_id") == self.instance_id:
            if current.get("status") == "stopping":
                self._transition(
                    "stopped",
                    phase="post_shutdown",
                    outcome="shutdown_complete",
                    details=self._stop_result or {},
                )
        self._write_health(
            runtime_instance_id=self.instance_id,
            runtime_shutdown_complete_at=datetime.now(UTC).isoformat(),
        )
