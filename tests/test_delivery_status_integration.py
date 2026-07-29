import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from telegram.error import Forbidden

from alerts.funding_exchange_store import FundingExchangeStore
from alerts.funding_quarter_hour import FundingAlertStore
from alerts.funding_snapshot_store import FundingSnapshotStore
from alerts.fvg_models import (
    FvgDirection,
    FvgEvent,
    FvgEventType,
    event_id,
)
from alerts.fvg_service import FvgAlertService
from alerts.fvg_store import FvgEventStore
from alerts.multi_funding_alerts import MultiFundingAlertService
from alerts.telegram_errors import classify_telegram_error
from database.telegram_delivery import TelegramDeliveryRegistry


UTC = timezone.utc


def make_event(index=0):
    candle_c_open = datetime(2026, 7, 29, 12, 0, tzinfo=UTC) + timedelta(
        minutes=15 * index
    )
    return FvgEvent(
        event_id=event_id(
            "BTCUSDT",
            "15m",
            FvgDirection.BULLISH,
            candle_c_open,
            FvgEventType.CONFIRMED_FVG,
        ),
        event_type=FvgEventType.CONFIRMED_FVG,
        symbol="BTCUSDT",
        timeframe="15m",
        direction=FvgDirection.BULLISH,
        candle_a_open_time=candle_c_open - timedelta(minutes=30),
        candle_b_open_time=candle_c_open - timedelta(minutes=15),
        candle_c_open_time=candle_c_open,
        candle_c_close_time=candle_c_open + timedelta(minutes=15),
        zone_low=Decimal("100"),
        zone_high=Decimal("101"),
        zone_size=Decimal("1"),
        signal_price=Decimal("102"),
        detected_at=candle_c_open + timedelta(minutes=15),
        is_confirmed=True,
        data_complete=True,
    )


class RecipientSettings:
    def recipients(self, event):
        return [42]


class BlockedBot:
    def __init__(self):
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        raise Forbidden("bot was blocked by the user")


class SuccessfulBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class ForbiddenDeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracking_only_records_block_without_suppressing_future_fvg(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=False,
            )
            service = FvgAlertService(
                settings=RecipientSettings(),
                event_store=FvgEventStore(path),
                delivery_registry=registry,
                suppress_unavailable_users=False,
            )
            bot = BlockedBot()

            await service.deliver(bot, [make_event(0)])
            await service.deliver(bot, [make_event(1)])

            self.assertEqual(bot.calls, 2)
            self.assertEqual(registry.profile(42)["status"], "blocked")

    async def test_fvg_block_stops_future_outbox_and_interaction_recovers(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = FvgEventStore(path)
            registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=True,
            )
            service = FvgAlertService(
                settings=RecipientSettings(),
                event_store=store,
                delivery_registry=registry,
                suppress_unavailable_users=True,
            )
            blocked_bot = BlockedBot()

            await service.deliver(blocked_bot, [make_event(0)])
            self.assertEqual(blocked_bot.calls, 1)
            self.assertEqual(registry.profile(42)["status"], "blocked")
            self.assertEqual(store.health()["outbox"], 0)

            await service.deliver(blocked_bot, [make_event(1)])
            self.assertEqual(blocked_bot.calls, 1)
            self.assertEqual(store.health()["outbox"], 0)

            recovered = registry.record_interaction(42, 42)
            self.assertTrue(recovered["recovered"])
            successful_bot = SuccessfulBot()
            await service.deliver(successful_bot, [make_event(2)])

            self.assertEqual(len(successful_bot.messages), 1)
            self.assertEqual(registry.profile(42)["status"], "active")
            self.assertEqual(store.health()["deliveries"], 1)

    async def test_tracking_only_keeps_blocked_funding_due(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            funding_path = root / "funding.sqlite3"
            delivery_path = root / "events.sqlite3"
            settings = FundingAlertStore(funding_path)
            registry = TelegramDeliveryRegistry(
                delivery_path,
                discard_outbox_by_default=False,
            )
            start = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            due = start + timedelta(minutes=15)
            settings.set_enabled(42, True, now=start)

            async def loader():
                return {
                    "bitunix": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.25"}
                    ]
                }

            service = MultiFundingAlertService(
                settings_store=settings,
                exchange_store=FundingExchangeStore(funding_path),
                snapshot_store=FundingSnapshotStore(funding_path),
                loader=loader,
                delivery_registry=registry,
                suppress_unavailable_users=False,
            )
            await service.run(BlockedBot(), now=due)

            self.assertEqual(registry.profile(42)["status"], "blocked")
            self.assertEqual(settings.user(42)["next_check_at"], due)

    async def test_blocked_funding_is_consumed_without_backlog(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            funding_path = root / "funding.sqlite3"
            delivery_path = root / "events.sqlite3"
            settings = FundingAlertStore(funding_path)
            exchanges = FundingExchangeStore(funding_path)
            snapshots = FundingSnapshotStore(funding_path)
            registry = TelegramDeliveryRegistry(
                delivery_path,
                discard_outbox_by_default=True,
            )
            start = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            due = start + timedelta(minutes=15)
            settings.set_enabled(42, True, now=start)
            registry.record_failure(
                42,
                classify_telegram_error(
                    Forbidden("bot was blocked by the user")
                ),
                Forbidden("bot was blocked by the user"),
            )

            async def loader():
                return {
                    "bitunix": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.25"}
                    ]
                }

            service = MultiFundingAlertService(
                settings_store=settings,
                exchange_store=exchanges,
                snapshot_store=snapshots,
                loader=loader,
                delivery_registry=registry,
                suppress_unavailable_users=True,
            )
            bot = SuccessfulBot()
            await service.run(bot, now=due)

            self.assertEqual(bot.messages, [])
            self.assertGreater(settings.user(42)["next_check_at"], due)
            self.assertIn(
                ("bitunix", "BTCUSDT", "positive"),
                exchanges.crossing_values(42),
            )

            registry.record_interaction(42, 42)
            await service.run(bot, now=settings.user(42)["next_check_at"])
            self.assertEqual(
                bot.messages,
                [],
                "A crossing consumed while blocked must not be replayed after recovery.",
            )


if __name__ == "__main__":
    unittest.main()
