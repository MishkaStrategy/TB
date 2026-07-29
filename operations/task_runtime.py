"""Async execution wrapper for persistent task leases and heartbeats."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from database.background_tasks import BackgroundTaskRegistry


LOGGER = logging.getLogger(__name__)


class TaskLeaseLost(RuntimeError):
    """The persistent lease no longer belongs to this running callback."""


@dataclass(frozen=True)
class TaskExecutionResult:
    started: bool
    run_id: str
    result: Any = None
    skip_reason: str | None = None
    active_run_id: str | None = None


class TrackedTaskRunner:
    """Run one coroutine under a cross-process SQLite lease."""

    def __init__(
        self,
        registry: BackgroundTaskRegistry,
        *,
        owner_id: str | None = None,
        heartbeat_interval_seconds: float = 30,
        history_retention_days: int = 30,
    ):
        self.registry = registry
        self.owner_id = owner_id or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"
        )
        self.heartbeat_interval_seconds = max(
            0.01,
            float(heartbeat_interval_seconds),
        )
        self.history_retention_days = max(1, int(history_retention_days))

    async def _prune_history(self) -> None:
        try:
            await asyncio.to_thread(
                self.registry.prune_runs,
                retention_days=self.history_retention_days,
            )
        except Exception:
            LOGGER.exception("Background task history cleanup failed")

    async def _heartbeat_loop(
        self,
        task_name: str,
        run_id: str,
        *,
        lease_seconds: float,
    ) -> None:
        interval = min(
            self.heartbeat_interval_seconds,
            max(0.01, float(lease_seconds) / 3.0),
        )
        while True:
            await asyncio.sleep(interval)
            renewed = await asyncio.to_thread(
                self.registry.heartbeat,
                task_name,
                run_id,
                owner_id=self.owner_id,
                lease_seconds=lease_seconds,
            )
            if not renewed:
                raise TaskLeaseLost(
                    f"Background task lease was lost task={task_name} run_id={run_id}"
                )

    async def run(
        self,
        task_name: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        lease_seconds: float,
        expected_interval_seconds: float | None = None,
        task_kind: str = "job_queue",
        trigger: str = "scheduled",
        metadata: dict | None = None,
    ) -> TaskExecutionResult:
        claim = await asyncio.to_thread(
            self.registry.try_begin,
            task_name,
            owner_id=self.owner_id,
            lease_seconds=lease_seconds,
            task_kind=task_kind,
            expected_interval_seconds=expected_interval_seconds,
            trigger=trigger,
            metadata=metadata,
        )
        if not claim["started"]:
            await self._prune_history()
            return TaskExecutionResult(
                started=False,
                run_id=claim["run_id"],
                skip_reason=claim.get("reason"),
                active_run_id=claim.get("active_run_id"),
            )

        run_id = claim["run_id"]
        operation_task = asyncio.create_task(
            operation(),
            name=f"task-operation:{task_name}",
        )
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                task_name,
                run_id,
                lease_seconds=lease_seconds,
            ),
            name=f"task-heartbeat:{task_name}",
        )
        try:
            done, _ = await asyncio.wait(
                {operation_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                heartbeat_error = heartbeat_task.exception()
                if heartbeat_error is not None:
                    operation_task.cancel()
                    await asyncio.gather(operation_task, return_exceptions=True)
                    raise heartbeat_error
                raise TaskLeaseLost(
                    f"Background task heartbeat stopped task={task_name} run_id={run_id}"
                )
            result = await operation_task
        except asyncio.CancelledError:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            await asyncio.to_thread(
                self.registry.finish_cancelled,
                task_name,
                run_id,
                owner_id=self.owner_id,
            )
            raise
        except Exception as error:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            finalized = await asyncio.to_thread(
                self.registry.finish_failure,
                task_name,
                run_id,
                owner_id=self.owner_id,
                error=error,
                error_code=(
                    "task_lease_lost"
                    if isinstance(error, TaskLeaseLost)
                    else "uncaught_task_exception"
                ),
            )
            if not finalized:
                LOGGER.error(
                    "Background task failure could not be finalized task=%s run_id=%s",
                    task_name,
                    run_id,
                )
            raise
        else:
            finalized = await asyncio.to_thread(
                self.registry.finish_success,
                task_name,
                run_id,
                owner_id=self.owner_id,
            )
            if not finalized:
                raise TaskLeaseLost(
                    f"Background task result lost its lease task={task_name} run_id={run_id}"
                )
            return TaskExecutionResult(
                started=True,
                run_id=run_id,
                result=result,
            )
        finally:
            heartbeat_task.cancel()
            operation_task.cancel()
            await asyncio.gather(
                heartbeat_task,
                operation_task,
                return_exceptions=True,
            )
            await self._prune_history()
