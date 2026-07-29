"""Telegram JobQueue integration for FVG and funding alerts."""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from alerts.funding_alerts import FundingAlertService
from alerts.funding_quarter_hour import next_quarter_hour
from alerts.fvg_lifecycle import FvgLifecycleConfig
from alerts.fvg_lifecycle_store import FvgLifecycleStore
from alerts.fvg_lifecycle_tracker import FvgLifecycleTracker
from alerts.fvg_service import FvgAlertService, parse_rest_candle
from alerts.fvg_stream import BitunixFvgStream
from alerts.health_monitor import HealthAlertMonitor
from config import (
    ADMIN_TELEGRAM_IDS,
    FVG_LIFECYCLE_APPROACHING_ZONE_WIDTHS,
    FVG_LIFECYCLE_ENABLED,
    FVG_LIFECYCLE_INVALIDATION_BUFFER_RATIO,
    FVG_LIFECYCLE_MAX_AGE_BARS,
    FVG_LIFECYCLE_SHADOW_MODE,
    FVG_LIFECYCLE_SYNC_INTERVAL_SECONDS,
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
_FVG_LIFECYCLE_TRACKER = None
_FUNDING_SERVICE = None


def get_fvg_service():
    global _FVG_SERVICE
    if _FVG_SERVICE is None:
        _FVG_SERVICE = FvgAlertService()
    return _FVG_SERVICE


def get_fvg_lifecycle_tracker():
    """Build the additive lifecycle tracker only when explicitly enabled."""
    global _FVG_LIFECYCLE_TRACKER
    if not FVG_LIFECYCLE_ENABLED:
        return None
    if _FVG_LIFECYCLE_TRACKER is None:
        service = get_fvg_service()
        store = FvgLifecycleStore(getattr(service.event_store, "path", None))
        config = FvgLifecycleConfig(
            approaching_zone_widths=Decimal(
                str(FVG_LIFECYCLE_APPROACHING_ZONE_WIDTHS)
            ),
            invalidation_buffer_ratio=Decimal(
                str(FVG_LIFECYCLE_INVALIDATION_BUFFER_RATIO)
            ),
            max_age_bars=FVG_LIFECYCLE_MAX_AGE_BARS,
        )
        _FVG_LIFECYCLE_TRACKER = FvgLifecycleTracker(
            store=store,
            config=config,
            health_store=service.event_store,
        )
    return _FVG_LIFECYCLE_TRACKER


def get_funding_service():
    global _FUNDING_SERVICE
    if _FUNDING_SERVICE is None:
        _FUNDING_SERVICE = FundingAlertService()
    return _FUNDING_SERVICE


async def _recover_lifecycle_only_symbol(service, symbol: str) -> None:
    """Refresh 1m candles without detecting or delivering new FVG events.

    A symbol may remain required only because it has an active lifecycle zone.
    Calling the normal recovery method for that symbol would also discover new
    FVGs and could keep the symbol alive forever.  This narrow recovery path
    updates only the candle cache used by existing zones.
    """
    now = datetime.now(timezone.utc)
    response = await asyncio.to_thread(service.client.get_candles, symbol, "1m", 25)
    for raw in response.get("data", []):
        try:
            candle = parse_rest_candle(raw, symbol, "1m", now)
        except (ValueError, KeyError, TypeError):
            service.event_store.increment_health("invalid_candles")
            continue
        service.cache.put(candle)


async def run_fvg_recovery(context):
    """Periodic REST safety net; WebSocket remains the primary source."""
    service = context.job.data["fvg_service"]
    tracker = context.job.data.get("fvg_lifecycle_tracker")
    user_symbols = set(service.settings.active_symbols())
    lifecycle_symbols = set(tracker.active_symbols()) if tracker is not None else set()

    for symbol in sorted(user_symbols):
        try:
            events = await asyncio.to_thread(service.recover, symbol)
            await service.deliver(context.bot, events)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Bitunix FVG recovery failed for %s: %s", symbol, error)
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("recovery_failures")

    for symbol in sorted(lifecycle_symbols - user_symbols):
        try:
            await _recover_lifecycle_only_symbol(service, symbol)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "Lifecycle-only candle recovery failed for %s: %s",
                symbol,
                error,
            )
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("lifecycle_recovery_failures")


async def run_fvg_lifecycle_shadow(context):
    """Persist lifecycle transitions without changing Telegram messages."""
    service = context.job.data["fvg_service"]
    tracker = context.job.data["fvg_lifecycle_tracker"]
    now = datetime.now(timezone.utc)
    try:
        created = await asyncio.to_thread(tracker.sync_detected_events)
        domain_events = 0
        for symbol in sorted(tracker.active_symbols()):
            candles = service.cache.series(symbol, "1m", now)
            domain_events += await asyncio.to_thread(tracker.observe_many, candles)
        counts = await asyncio.to_thread(tracker.counts)
        service.event_store.update_health(
            lifecycle_enabled=True,
            lifecycle_shadow_mode=bool(FVG_LIFECYCLE_SHADOW_MODE),
            lifecycle_last_sync=now.isoformat(),
            lifecycle_last_zones_created=created,
            lifecycle_last_domain_events=domain_events,
            lifecycle_zones=counts["zones"],
            lifecycle_active_zones=counts["active_zones"],
            lifecycle_zone_events=counts["zone_events"],
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception("FVG lifecycle shadow sync failed")
        service.event_store.update_health(last_error=str(error))
        service.event_store.increment_health("lifecycle_sync_failures")


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
    tracker = context.job.data.get("fvg_lifecycle_tracker")
    try:
        health = await asyncio.to_thread(service.event_store.health)
        active_symbols = set(await asyncio.to_thread(service.settings.active_symbols))
        if tracker is not None:
            active_symbols.update(tracker.active_symbols())
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
    lifecycle_tracker = get_fvg_lifecycle_tracker()
    if lifecycle_tracker is not None and not FVG_LIFECYCLE_SHADOW_MODE:
        logger.warning(
            "Only lifecycle shadow mode is implemented in this release; "
            "Telegram delivery remains unchanged"
        )

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
        data={
            "fvg_service": service,
            "fvg_lifecycle_tracker": lifecycle_tracker,
        },
    )
    if lifecycle_tracker is not None:
        application.job_queue.run_repeating(
            run_fvg_lifecycle_shadow,
            interval=FVG_LIFECYCLE_SYNC_INTERVAL_SECONDS,
            first=min(20, FVG_LIFECYCLE_SYNC_INTERVAL_SECONDS),
            name="fvg-lifecycle-shadow",
            data={
                "fvg_service": service,
                "fvg_lifecycle_tracker": lifecycle_tracker,
            },
        )
    application.job_queue.run_repeating(
        run_operational_health,
        interval=HEALTH_ALERT_INTERVAL_SECONDS,
        first=min(30, HEALTH_ALERT_INTERVAL_SECONDS),
        name="fvg-operational-health",
        data={
            "fvg_service": service,
            "fvg_lifecycle_tracker": lifecycle_tracker,
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
