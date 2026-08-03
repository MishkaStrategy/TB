"""Bridge FVG scheduling to funding, Outbox V2, DB metrics and task leases."""

import asyncio
import logging

from alerts import scheduler as base
from alerts.multi_funding_alerts import MultiFundingAlertService
from config import (
    BACKGROUND_TASK_HEARTBEAT_SECONDS,
    BACKGROUND_TASK_HISTORY_RETENTION_DAYS,
    BACKGROUND_TASK_MIN_LEASE_SECONDS,
    BACKGROUND_TASK_REGISTRY_ENABLED,
    BACKGROUND_TASK_STALE_MULTIPLIER,
    BACKGROUND_TASK_WATCHDOG_ENABLED,
    BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS,
    DATABASE_OBSERVABILITY_ENABLED,
    DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED,
    DATABASE_OBSERVABILITY_INTERVAL_SECONDS,
    DATABASE_OBSERVABILITY_RETENTION_DAYS,
    DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED,
    GRACEFUL_SHUTDOWN_ENABLED,
    HEALTH_ALERT_INTERVAL_SECONDS,
    OUTBOX_RETRY_POLICY_ENABLED,
)
from database.background_tasks import BackgroundTaskRegistry
from database.sqlite_observability import SQLiteObservabilityService
from handlers.multi_funding import CACHE_KEY
from operations.graceful_fvg_stream import GracefulBitunixFvgStream
from operations.task_runtime import TrackedTaskRunner
from operations.task_watchdog import BackgroundTaskWatchdog


LOGGER = logging.getLogger(__name__)
_FUNDING_SERVICE = None
_DATABASE_OBSERVABILITY_SERVICE = None
_BACKGROUND_TASK_REGISTRY = None
_BACKGROUND_TASK_RUNNER = None
_BACKGROUND_TASK_WATCHDOG = None

_BASE_GET_FVG_SERVICE = base.get_fvg_service
_BASE_RUN_FVG_RECOVERY = base.run_fvg_recovery
_BASE_RUN_FVG_CONTROL_POINT = base.run_fvg_control_point
_BASE_RUN_FVG_DELIVERY_RETRY = base.run_fvg_delivery_retry
_BASE_RUN_OPERATIONAL_HEALTH = base.run_operational_health


def get_funding_service():
    global _FUNDING_SERVICE
    if _FUNDING_SERVICE is None:
        _FUNDING_SERVICE = MultiFundingAlertService()
    return _FUNDING_SERVICE


def get_database_observability_service():
    global _DATABASE_OBSERVABILITY_SERVICE
    if _DATABASE_OBSERVABILITY_SERVICE is None:
        _DATABASE_OBSERVABILITY_SERVICE = SQLiteObservabilityService(
            include_row_counts=DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED,
            include_integrity_check=(
                DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED
            ),
            retention_days=DATABASE_OBSERVABILITY_RETENTION_DAYS,
        )
    return _DATABASE_OBSERVABILITY_SERVICE


def get_fvg_service():
    if not OUTBOX_RETRY_POLICY_ENABLED:
        return _BASE_GET_FVG_SERVICE()
    if base._FVG_SERVICE is None:
        from alerts.fvg_service_v2 import OutboxV2FvgAlertService

        base._FVG_SERVICE = OutboxV2FvgAlertService()
    return base._FVG_SERVICE


def _task_registry_active() -> bool:
    return BACKGROUND_TASK_REGISTRY_ENABLED or BACKGROUND_TASK_WATCHDOG_ENABLED


def get_background_task_registry():
    global _BACKGROUND_TASK_REGISTRY
    if _BACKGROUND_TASK_REGISTRY is None:
        path = getattr(get_fvg_service().event_store, "path", None)
        _BACKGROUND_TASK_REGISTRY = BackgroundTaskRegistry(path)
    return _BACKGROUND_TASK_REGISTRY


def get_background_task_runner():
    global _BACKGROUND_TASK_RUNNER
    if _BACKGROUND_TASK_RUNNER is None:
        _BACKGROUND_TASK_RUNNER = TrackedTaskRunner(
            get_background_task_registry(),
            heartbeat_interval_seconds=BACKGROUND_TASK_HEARTBEAT_SECONDS,
            history_retention_days=BACKGROUND_TASK_HISTORY_RETENTION_DAYS,
        )
    return _BACKGROUND_TASK_RUNNER


def get_background_task_watchdog():
    global _BACKGROUND_TASK_WATCHDOG
    if _BACKGROUND_TASK_WATCHDOG is None:
        _BACKGROUND_TASK_WATCHDOG = BackgroundTaskWatchdog(
            get_background_task_registry(),
            metrics=get_fvg_service().event_store,
            stale_multiplier=BACKGROUND_TASK_STALE_MULTIPLIER,
            history_retention_days=BACKGROUND_TASK_HISTORY_RETENTION_DAYS,
        )
    return _BACKGROUND_TASK_WATCHDOG


def _lease_seconds(expected_interval_seconds: float) -> float:
    return max(
        float(BACKGROUND_TASK_MIN_LEASE_SECONDS),
        float(expected_interval_seconds) * 2.0,
    )


def _increment_task_metric(key: str, amount: int = 1) -> None:
    try:
        method = getattr(get_fvg_service().event_store, "increment_health", None)
        if callable(method):
            method(key, amount)
    except Exception:
        LOGGER.exception("Background task metric write failed key=%s", key)


async def _run_tracked(
    task_name: str,
    expected_interval_seconds: float,
    operation,
):
    if not _task_registry_active():
        return await operation()
    try:
        execution = await get_background_task_runner().run(
            task_name,
            operation,
            lease_seconds=_lease_seconds(expected_interval_seconds),
            expected_interval_seconds=expected_interval_seconds,
            task_kind="job_queue",
            trigger="scheduled",
            metadata={"callback": task_name},
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("Tracked background job failed task=%s", task_name)
        _increment_task_metric("background_task_uncaught_failures")
        return None
    if not execution.started:
        LOGGER.info(
            "Background job overlap prevented task=%s active_run=%s",
            task_name,
            execution.active_run_id,
        )
        _increment_task_metric("background_task_overlap_skips")
        return None
    return execution.result


async def run_fvg_recovery(context):
    return await _run_tracked(
        "fvg-rest-recovery",
        300,
        lambda: _BASE_RUN_FVG_RECOVERY(context),
    )


async def run_fvg_control_point(context):
    task_name = getattr(context.job, "name", None) or "fvg-control-point"
    return await _run_tracked(
        task_name,
        900,
        lambda: _BASE_RUN_FVG_CONTROL_POINT(context),
    )


async def run_fvg_delivery_retry(context):
    return await _run_tracked(
        "fvg-delivery-outbox-retry",
        30,
        lambda: _BASE_RUN_FVG_DELIVERY_RETRY(context),
    )


async def run_operational_health(context):
    return await _run_tracked(
        "fvg-operational-health",
        HEALTH_ALERT_INTERVAL_SECONDS,
        lambda: _BASE_RUN_OPERATIONAL_HEALTH(context),
    )


async def _run_multi_funding_impl(context):
    rates = await get_funding_service().run(context.bot)
    if rates is not None:
        context.bot_data[CACHE_KEY] = rates
    return rates


async def run_funding_alerts(context):
    return await _run_tracked(
        "funding-quarter-hour",
        900,
        lambda: _run_multi_funding_impl(context),
    )


async def _run_database_observability_impl(context):
    service = context.job.data["database_observability_service"]
    return await asyncio.to_thread(service.capture)


async def run_database_observability(context):
    return await _run_tracked(
        "sqlite-observability",
        DATABASE_OBSERVABILITY_INTERVAL_SECONDS,
        lambda: _run_database_observability_impl(context),
    )


async def run_background_task_watchdog(context):
    watchdog = context.job.data["background_task_watchdog"]
    try:
        return await asyncio.to_thread(watchdog.evaluate_once)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("Background task watchdog failed")
        _increment_task_metric("background_task_watchdog_failures")
        return None


def schedule_database_observability(application):
    if not DATABASE_OBSERVABILITY_ENABLED:
        return None
    if application.job_queue is None:
        raise RuntimeError("Telegram JobQueue is unavailable")
    job_name = "sqlite-observability"
    get_jobs = getattr(application.job_queue, "get_jobs_by_name", None)
    if callable(get_jobs) and get_jobs(job_name):
        return None
    return application.job_queue.run_repeating(
        run_database_observability,
        interval=DATABASE_OBSERVABILITY_INTERVAL_SECONDS,
        first=min(60, DATABASE_OBSERVABILITY_INTERVAL_SECONDS),
        name=job_name,
        data={
            "database_observability_service": (
                get_database_observability_service()
            )
        },
    )


def _task_definitions():
    definitions = {
        "fvg-confirmed-control": 900,
        "fvg-pre-control-t-minus-3": 900,
        "fvg-delivery-outbox-retry": 30,
        "fvg-rest-recovery": 300,
        "fvg-operational-health": float(HEALTH_ALERT_INTERVAL_SECONDS),
        "funding-quarter-hour": 900,
    }
    if DATABASE_OBSERVABILITY_ENABLED:
        definitions["sqlite-observability"] = float(
            DATABASE_OBSERVABILITY_INTERVAL_SECONDS
        )
    return definitions


def register_background_tasks():
    if not _task_registry_active():
        return []
    registry = get_background_task_registry()
    return [
        registry.register(
            task_name,
            task_kind="job_queue",
            expected_interval_seconds=interval,
        )
        for task_name, interval in sorted(_task_definitions().items())
    ]


def schedule_background_task_watchdog(application):
    if not BACKGROUND_TASK_WATCHDOG_ENABLED:
        return None
    if application.job_queue is None:
        raise RuntimeError("Telegram JobQueue is unavailable")
    job_name = "background-task-watchdog"
    get_jobs = getattr(application.job_queue, "get_jobs_by_name", None)
    if callable(get_jobs) and get_jobs(job_name):
        return None
    return application.job_queue.run_repeating(
        run_background_task_watchdog,
        interval=BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS,
        first=min(30, BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS),
        name=job_name,
        data={"background_task_watchdog": get_background_task_watchdog()},
    )


def schedule_fvg_alerts(application):
    base.run_fvg_recovery = run_fvg_recovery
    base.run_fvg_control_point = run_fvg_control_point
    base.run_fvg_delivery_retry = run_fvg_delivery_retry
    base.run_operational_health = run_operational_health
    base.run_funding_alerts = run_funding_alerts
    base.get_funding_service = get_funding_service
    base.get_fvg_service = get_fvg_service
    register_background_tasks()
    result = base.schedule_fvg_alerts(application)
    schedule_database_observability(application)
    schedule_background_task_watchdog(application)
    return result


async def start_fvg_stream(application):
    if not GRACEFUL_SHUTDOWN_ENABLED:
        return await base.start_fvg_stream(application)
    if base._FVG_TASK is not None and not base._FVG_TASK.done():
        return base._FVG_TASK
    base._FVG_STREAM = GracefulBitunixFvgStream(get_fvg_service())
    base._FVG_TASK = asyncio.create_task(
        base._FVG_STREAM.run(application.bot),
        name="bitunix-fvg-stream",
    )
    return base._FVG_TASK


async def stop_fvg_stream(application, *, timeout_seconds: float | None = None):
    if not GRACEFUL_SHUTDOWN_ENABLED or not isinstance(
        base._FVG_STREAM,
        GracefulBitunixFvgStream,
    ):
        await base.stop_fvg_stream(application)
        return {
            "graceful": False,
            "drained": None,
            "pending_before": None,
            "pending_after": None,
            "task_cancelled": False,
            "timeout": False,
        }

    stream = base._FVG_STREAM
    task = base._FVG_TASK
    budget = max(0.01, float(timeout_seconds or 1.0))
    loop = asyncio.get_running_loop()
    started = loop.time()
    task_cancelled = False
    task_error = None
    drain_result = {
        "drained": False,
        "pending_before": stream.pending_delivery_count,
        "pending_after": stream.pending_delivery_count,
        "timeout": False,
    }

    stream.stop_accepting()
    try:
        drain_budget = max(0.01, budget * 0.8)
        drain_result = await stream.drain(timeout_seconds=drain_budget)
        remaining = max(0.0, budget - (loop.time() - started))

        if task is not None and not task.done():
            if drain_result["drained"] and remaining > 0:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
                except asyncio.TimeoutError:
                    task.cancel()
                    task_cancelled = True
            else:
                task.cancel()
                task_cancelled = True

        if task is not None:
            results = await asyncio.gather(task, return_exceptions=True)
            if results and isinstance(results[0], BaseException):
                if not isinstance(results[0], asyncio.CancelledError):
                    task_error = str(results[0])[:500]
    except asyncio.CancelledError:
        if task is not None and not task.done():
            task.cancel()
        worker = getattr(stream, "_delivery_worker_task", None)
        if worker is not None and not worker.done():
            worker.cancel()
        await asyncio.gather(
            *[item for item in (task, worker) if item is not None],
            return_exceptions=True,
        )
        raise
    finally:
        base._FVG_TASK = None
        base._FVG_STREAM = None

    timeout = bool(drain_result["timeout"] or task_cancelled)
    return {
        "graceful": True,
        **drain_result,
        "task_cancelled": task_cancelled,
        "task_error": task_error,
        "timeout": timeout,
    }


async def drain_fvg_outbox(application, *, timeout_seconds: float) -> dict:
    service = get_fvg_service()
    method = getattr(service, "retry_pending", None)
    if not callable(method):
        return {
            "enabled": True,
            "supported": False,
            "completed": 0,
            "timeout": False,
        }
    try:
        completed = await asyncio.wait_for(
            method(application.bot, limit=1000),
            timeout=max(0.01, float(timeout_seconds)),
        )
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        return {
            "enabled": True,
            "supported": True,
            "completed": 0,
            "timeout": True,
        }
    return {
        "enabled": True,
        "supported": True,
        "completed": int(completed or 0),
        "timeout": False,
    }
