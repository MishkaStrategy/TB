import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from alerts.fvg_models import (
    FvgDirection,
    FvgEvent,
    FvgEventType,
    event_id,
)
from alerts.fvg_service_v2 import OutboxV2FvgAlertService
from alerts.scheduler_multi import get_fvg_service
from alerts.telegram_outbox import OutboxRetryPolicy, TelegramOutboxWorker
from database.outbox_compat import FvgOutboxCompatibility
from database.telegram_delivery import TelegramDeliveryRegistry
from database.telegram_outbox import OutboxStatus, TelegramOutboxStore
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc


def make_event(*, event_type=FvgEventType.CONFIRMED_FVG):
    now = datetime.now(UTC).replace(microsecond=0)
    candle_c_open = now - timedelta(minutes=15)
    return FvgEvent(
        event_id=event_id(
            "BTCUSDT",
            "15m",
            FvgDirection.BULLISH,
            candle_c_open,
            event_type,
        ),
        event_type=event_type,
        symbol="BTCUSDT",
        timeframe="15m",
        direction=FvgDirection.BULLISH,
        candle_a_open_time=candle_c_open - timedelta(minutes=30),
        candle_b_open_time=candle_c_open - timedelta(minutes=15),
        candle_c_open_time=candle_c_open,
        candle_c_close_time=(
            now + timedelta(minutes=3)
            if event_type is FvgEventType.PRE_FVG
            else now
        ),
        zone_low=Decimal("100"),
        zone_high=Decimal("101"),
        zone_size=Decimal("1"),
        signal_price=Decimal("102"),
        detected_at=now,
        is_confirmed=event_type is FvgEventType.CONFIRMED_FVG,
        data_complete=True,
    )


class RecipientSettings:
    def recipients(self, event):
        return [42]


class SuccessfulBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.messages))


class RetryAfter(Exception):
    def __init__(self, seconds):
        self.retry_after = seconds
        super().__init__(f"Retry after {seconds}")


class FailingBot:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        raise self.error


class FvgOutboxV2Tests(unittest.IsolatedAsyncioTestCase):
    def build_service(self, path, *, expiration_enabled=False):
        event_store = FvgEventStore(path)
        outbox_store = TelegramOutboxStore(path)
        compatibility = FvgOutboxCompatibility(path)
        registry = TelegramDeliveryRegistry(path)
        worker = TelegramOutboxWorker(
            outbox_store,
            delivery_registry=registry,
            metrics=event_store,
            compatibility=compatibility,
            policy=OutboxRetryPolicy(max_attempts=3),
        )
        return OutboxV2FvgAlertService(
            settings=RecipientSettings(),
            event_store=event_store,
            delivery_registry=registry,
            outbox_store=outbox_store,
            outbox_worker=worker,
            outbox_compatibility=compatibility,
            expiration_enabled=expiration_enabled,
            default_ttl_seconds=3600,
        )

    async def test_success_preserves_legacy_delivery_stats_and_deduplicates(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            service = self.build_service(path)
            event = make_event()
            bot = SuccessfulBot()

            await service.deliver(bot, [event])
            await service.deliver(bot, [event])

            self.assertEqual(len(bot.messages), 1)
            self.assertEqual(service.event_store.health()["deliveries"], 1)
            self.assertEqual(
                service.outbox_store.counts(),
                {OutboxStatus.DELIVERED.value: 1},
            )
            self.assertFalse(
                service.event_store.delivery_needed(42, event.event_id)
            )

    async def test_retry_remains_in_v2_and_legacy_rollback_mirror(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            service = self.build_service(path)
            event = make_event()
            bot = FailingBot(RetryAfter(60))

            await service.deliver(bot, [event])

            self.assertEqual(bot.calls, 1)
            self.assertEqual(
                service.outbox_store.counts(),
                {OutboxStatus.RETRY_SCHEDULED.value: 1},
            )
            self.assertEqual(service.event_store.health()["outbox"], 1)
            self.assertTrue(
                service.event_store.delivery_needed(42, event.event_id)
            )

    def test_pre_fvg_expires_at_candle_close(self):
        with TemporaryDirectory() as directory:
            service = self.build_service(
                Path(directory) / "events.sqlite3",
                expiration_enabled=True,
            )
            event = make_event(event_type=FvgEventType.PRE_FVG)
            self.assertEqual(service._expires_at(event), event.candle_c_close_time)


class SchedulerOutboxSelectionTests(unittest.TestCase):
    def test_selects_v2_service_only_when_flag_is_enabled(self):
        from alerts import scheduler as base

        original = base._FVG_SERVICE
        try:
            base._FVG_SERVICE = None
            sentinel = object()
            with (
                patch("alerts.scheduler_multi.OUTBOX_RETRY_POLICY_ENABLED", True),
                patch(
                    "alerts.fvg_service_v2.OutboxV2FvgAlertService",
                    return_value=sentinel,
                ),
            ):
                self.assertIs(get_fvg_service(), sentinel)
        finally:
            base._FVG_SERVICE = original


if __name__ == "__main__":
    unittest.main()
