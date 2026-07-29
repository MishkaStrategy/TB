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
    HEALTH_ALERT_INTERVAL_SECONDS,
    OUTBOX_RETRY_POLICY_ENABLED,
)
from database.background_tasks import BackgroundTaskRegistry
from database.sqlite_observability import SQLiteObservabilityService
from handlers.multi_funding import CACHE_KEY
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
        # The persistent runner has already recorded the uncaught failure.
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


start_fvg_stream = base.start_fvg_stream
stop_fvg_stream = base.stop_fvg_stream
