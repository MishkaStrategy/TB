"""Production FVG scheduling with one confirmed 15-minute data path."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from alerts import scheduler as scheduler_base
from alerts import scheduler_multi as scheduler_multi
from alerts.funding_quarter_hour import next_quarter_hour
from config import (
    DATABASE_OBSERVABILITY_ENABLED,
    DATABASE_OBSERVABILITY_INTERVAL_SECONDS,
    GRACEFUL_SHUTDOWN_ENABLED,
    HEALTH_ALERT_INTERVAL_SECONDS,
)
from alerts.fvg_stream_15m import FifteenMinuteBitunixFvgStream
from operations.graceful_fvg_stream_15m import FifteenMinuteGracefulBitunixFvgStream


async def _run_confirmed_15m(context):
    service = context.job.data["fvg_service"]
    poller = context.job.data.get("fvg_poller") or scheduler_base.get_fvg_poller()
    clock = context.job.data.get("clock")
    now = clock() if callable(clock) else datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    if now.minute % 15 != 0:
        return None

    markets = {
        (exchange, symbol)
        for exchange, symbol, _timeframe in service.settings.active_markets()
    }
    all_events = []
    for exchange, symbol in sorted(markets):
        try:
            events = await asyncio.to_thread(
                poller.confirmed,
                exchange,
                symbol,
                "15m",
                now,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            scheduler_base.logger.warning(
                "Confirmed 15m FVG control point failed for %s %s: %s",
                exchange,
                symbol,
                error,
            )
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("control_point_failures")
            continue
        all_events.extend(events)

    if all_events:
        await service.deliver(context.bot, all_events)
    return all_events


async def run_fvg_control_point(context):
    return await scheduler_multi._run_tracked(
        "fvg-confirmed-control",
        900,
        lambda: _run_confirmed_15m(context),
    )


def _register_background_tasks() -> list:
    if not scheduler_multi._task_registry_active():
        return []
    definitions = {
        "fvg-confirmed-control": 900,
        "fvg-delivery-outbox-retry": 30,
        "fvg-rest-recovery": 300,
        "fvg-operational-health": float(HEALTH_ALERT_INTERVAL_SECONDS),
        "funding-quarter-hour": 900,
    }
    if DATABASE_OBSERVABILITY_ENABLED:
        definitions["sqlite-observability"] = float(
            DATABASE_OBSERVABILITY_INTERVAL_SECONDS
        )
    registry = scheduler_multi.get_background_task_registry()
    return [
        registry.register(
            task_name,
            task_kind="job_queue",
            expected_interval_seconds=interval,
        )
        for task_name, interval in sorted(definitions.items())
    ]


def schedule_fvg_alerts(application):
    """Register confirmed FVG, delivery, health and funding jobs without pre-FVG."""
    if application.job_queue is None:
        raise RuntimeError("Telegram JobQueue is unavailable")

    service = scheduler_multi.get_fvg_service()
    poller = scheduler_base.get_fvg_poller()
    seconds = datetime.now(timezone.utc).timestamp() % 900
    confirmed_delay = 900 - seconds + 5

    _register_background_tasks()
    application.job_queue.run_repeating(
        run_fvg_control_point,
        interval=900,
        first=confirmed_delay,
        name="fvg-confirmed-control",
        data={"fvg_service": service, "fvg_poller": poller},
    )
    application.job_queue.run_repeating(
        scheduler_multi.run_fvg_delivery_retry,
        interval=30,
        first=5,
        name="fvg-delivery-outbox-retry",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        scheduler_multi.run_fvg_recovery,
        interval=300,
        first=15,
        name="fvg-rest-recovery",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        scheduler_multi.run_operational_health,
        interval=HEALTH_ALERT_INTERVAL_SECONDS,
        first=min(30, HEALTH_ALERT_INTERVAL_SECONDS),
        name="fvg-operational-health",
        data={
            "fvg_service": service,
            "health_monitor": scheduler_base.HealthAlertMonitor(
                stale_ws_seconds=scheduler_base.HEALTH_ALERT_STALE_WS_SECONDS,
                outbox_threshold=scheduler_base.HEALTH_ALERT_OUTBOX_THRESHOLD,
                cooldown_seconds=scheduler_base.HEALTH_ALERT_COOLDOWN_SECONDS,
            ),
        },
    )

    now = datetime.now(timezone.utc)
    funding_delay = (next_quarter_hour(now) - now).total_seconds()
    application.job_queue.run_repeating(
        scheduler_multi.run_funding_alerts,
        interval=900,
        first=funding_delay,
        name="funding-quarter-hour",
        data={"funding_service": scheduler_multi.get_funding_service()},
    )
    scheduler_multi.schedule_database_observability(application)
    scheduler_multi.schedule_background_task_watchdog(application)


async def start_fvg_stream(application):
    service = scheduler_multi.get_fvg_service()
    if scheduler_base._FVG_TASK is not None and not scheduler_base._FVG_TASK.done():
        return scheduler_base._FVG_TASK

    stream_class = (
        FifteenMinuteGracefulBitunixFvgStream
        if GRACEFUL_SHUTDOWN_ENABLED
        else FifteenMinuteBitunixFvgStream
    )
    scheduler_base._FVG_STREAM = stream_class(service)
    scheduler_base._FVG_TASK = asyncio.create_task(
        scheduler_base._FVG_STREAM.run(application.bot),
        name="bitunix-fvg-stream",
    )
    return scheduler_base._FVG_TASK


get_fvg_service = scheduler_multi.get_fvg_service
stop_fvg_stream = scheduler_multi.stop_fvg_stream
drain_fvg_outbox = scheduler_multi.drain_fvg_outbox


__all__ = [
    "drain_fvg_outbox",
    "get_fvg_service",
    "run_fvg_control_point",
    "schedule_fvg_alerts",
    "start_fvg_stream",
    "stop_fvg_stream",
]
