"""Telegram JobQueue integration for FVG alerts."""

import asyncio
import logging
from datetime import datetime, timezone

from alerts.fvg_service import FvgAlertService
from alerts.fvg_stream import BitunixFvgStream


logger = logging.getLogger(__name__)


_FVG_SERVICE = None
_FVG_STREAM = None
_FVG_TASK = None


def get_fvg_service():
    global _FVG_SERVICE
    if _FVG_SERVICE is None:
        _FVG_SERVICE = FvgAlertService()
    return _FVG_SERVICE


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


def schedule_fvg_alerts(application):
    """Register FVG control points, retry outbox and REST recovery."""
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
