"""Bridge FVG scheduling to multi-exchange funding, Outbox V2 and DB metrics."""

import asyncio
import logging

from alerts import scheduler as base
from alerts.multi_funding_alerts import MultiFundingAlertService
from config import (
    DATABASE_OBSERVABILITY_ENABLED,
    DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED,
    DATABASE_OBSERVABILITY_INTERVAL_SECONDS,
    DATABASE_OBSERVABILITY_RETENTION_DAYS,
    DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED,
    OUTBOX_RETRY_POLICY_ENABLED,
)
from database.sqlite_observability import SQLiteObservabilityService
from handlers.multi_funding import CACHE_KEY


LOGGER = logging.getLogger(__name__)
_FUNDING_SERVICE = None
_DATABASE_OBSERVABILITY_SERVICE = None
_BASE_GET_FVG_SERVICE = base.get_fvg_service


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


async def run_funding_alerts(context):
    rates = await get_funding_service().run(context.bot)
    if rates is not None:
        context.bot_data[CACHE_KEY] = rates


async def run_database_observability(context):
    service = context.job.data["database_observability_service"]
    try:
        await asyncio.to_thread(service.capture)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("SQLite observability snapshot failed")


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


def schedule_fvg_alerts(application):
    base.run_funding_alerts = run_funding_alerts
    base.get_funding_service = get_funding_service
    base.get_fvg_service = get_fvg_service
    result = base.schedule_fvg_alerts(application)
    schedule_database_observability(application)
    return result


start_fvg_stream = base.start_fvg_stream
stop_fvg_stream = base.stop_fvg_stream
