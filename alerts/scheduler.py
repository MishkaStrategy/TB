"""Telegram JobQueue integration for FVG and funding alerts."""

import asyncio
import logging
from datetime import datetime, timezone

from alerts.funding_alerts import FundingAlertService
from alerts.funding_quarter_hour import next_quarter_hour
from alerts.fvg_service import FvgAlertService
from alerts.fvg_stream import BitunixFvgStream
from alerts.health_monitor import HealthAlertMonitor
from config import (
    ADMIN_TELEGRAM_IDS,
    HEALTH_ALERT_COOLDOWN_SECONDS,
    HEALTH_ALERT_INTERVAL_SECONDS,
    HEALTH_ALERT_OUTBOX_THRESHOLD,
    HEALTH_ALERT_STALE_WS_SECONDS,
)
from handlers.funding import CACHE_KEY as FUNDING_CACHE_KEY


logger = logging.getLogger(__name__)


_FVG_SERVICE = None
_FVG_STREAM = None
_FVG_TASK = None
_FUNDING_SERVICE = None


def get_fvg_service():
    global _FVG_SERVICE
    if _FVG_SERVICE is None:
        _FVG_SERVICE = FvgAlertService()
    return _FVG_SERVICE


def get_funding_service():
    global _FUNDING_SERVICE
    if _FUNDING_SERVICE is None:
        _FUNDING_SERVICE = FundingAlertService()
    return _FUNDING_SERVICE


async def run_fvg_recovery(context):
    """Periodic REST safety net; WebSocket remains the primary source."""
    service = context.job.data["fvg_service"]
    for symbol in sorted(service.settings.active_symbols()):
        try:
            events = await asyncio.to_thread(service.recover, symbol)
            await service.deliver(context.bot, events)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Bitunix FVG recovery failed for %s: %s", symbol, error)
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("recovery_failures")


async def run_fvg_control_point(context):
    """Evaluate cached candles around boundaries without another REST request."""
    service = context.job.data["fvg_service"]
    now = context.job.data.get("clock", None)
    if callable(now):
        now = now()
    if now is None:
        now = datetime.now(timezone.utc)
    for symbol in sorted(service.settings.active_symbols()):
        try:
            await service.deliver(context.bot, service.evaluate(symbol, now))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("FVG control point failed for %s", symbol)
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("control_point_failures")


async def run_fvg_delivery_retry(context):
    """Drain the persistent Telegram outbox even after process restarts."""
    service = context.job.data["fvg_service"]
    try:
        await service.retry_pending(context.bot, limit=200)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Persistent FVG delivery retry failed")
        service.event_store.update_health(last_error=str(error))
        service.event_store.increment_health("delivery_retry_job_failures")


async def run_operational_health(context):
    """Send throttled operational warnings and recovery notices to admins."""
    service = context.job.data["fvg_service"]
    monitor = context.job.data["health_monitor"]
    try:
        health = await asyncio.to_thread(service.event_store.health)
        active_symbols = await asyncio.to_thread(service.settings.active_symbols)
        alerts = monitor.evaluate(
            health,
            has_active_symbols=bool(active_symbols),
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("Operational health evaluation failed")
        service.event_store.update_health(last_error=str(error))
        service.event_store.increment_health("health_monitor_failures")
        return

    for message in alerts:
        for admin_id in sorted(ADMIN_TELEGRAM_IDS):
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Failed to send health alert to admin=%s: %s",
                    admin_id,
                    error,
                )
                service.event_store.increment_health(
                    "health_alert_delivery_failures"
                )


async def run_funding_alerts(context):
    """Refresh funding on each quarter hour and notify users whose schedules are due."""
    service = context.job.data["funding_service"]
    try:
        rates = await service.run(context.bot)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Quarter-hour funding alert job failed")
        return
    if rates is not None:
        # One shared cache instead of one full rates list per Telegram user.
        context.bot_data[FUNDING_CACHE_KEY] = rates


def schedule_fvg_alerts(application):
    """Register FVG control points, funding, outbox, health and REST recovery."""
    if application.job_queue is None:
        raise RuntimeError("Telegram JobQueue is unavailable")
    service = get_fvg_service()
    seconds = datetime.now(timezone.utc).timestamp() % 900
    confirmed_delay = 900 - seconds + 5
    pre_delay = (725 - seconds) % 900
    if pre_delay < 1:
        pre_delay += 900

    application.job_queue.run_repeating(
        run_fvg_control_point,
        interval=900,
        first=confirmed_delay,
        name="fvg-confirmed-control",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        run_fvg_control_point,
        interval=900,
        first=pre_delay,
        name="fvg-pre-control-t-minus-3",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        run_fvg_delivery_retry,
        interval=30,
        first=5,
        name="fvg-delivery-outbox-retry",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        run_fvg_recovery,
        interval=300,
        first=15,
        name="fvg-rest-recovery",
        data={"fvg_service": service},
    )
    application.job_queue.run_repeating(
        run_operational_health,
        interval=HEALTH_ALERT_INTERVAL_SECONDS,
        first=min(30, HEALTH_ALERT_INTERVAL_SECONDS),
        name="fvg-operational-health",
        data={
            "fvg_service": service,
            "health_monitor": HealthAlertMonitor(
                stale_ws_seconds=HEALTH_ALERT_STALE_WS_SECONDS,
                outbox_threshold=HEALTH_ALERT_OUTBOX_THRESHOLD,
                cooldown_seconds=HEALTH_ALERT_COOLDOWN_SECONDS,
            ),
        },
    )

    now = datetime.now(timezone.utc)
    funding_delay = (next_quarter_hour(now) - now).total_seconds()
    application.job_queue.run_repeating(
        run_funding_alerts,
        interval=900,
        first=funding_delay,
        name="funding-quarter-hour",
        data={"funding_service": get_funding_service()},
    )


async def start_fvg_stream(application):
    global _FVG_STREAM, _FVG_TASK
    service = get_fvg_service()
    _FVG_STREAM = BitunixFvgStream(service)
    _FVG_TASK = asyncio.create_task(
        _FVG_STREAM.run(application.bot),
        name="bitunix-fvg-stream",
    )


async def stop_fvg_stream(application):
    global _FVG_TASK
    if _FVG_STREAM is not None:
        _FVG_STREAM.stop()
    if _FVG_TASK is not None:
        _FVG_TASK.cancel()
        await asyncio.gather(_FVG_TASK, return_exceptions=True)
        _FVG_TASK = None
