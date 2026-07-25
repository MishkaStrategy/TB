import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.fvg_models import (
    FvgDirection,
    FvgEvent,
    FvgEventType,
    event_id,
)
from alerts.fvg_service import FvgAlertService
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc


def make_pre_event():
    candle_c_open = datetime.now(UTC).replace(second=0, microsecond=0)
    return FvgEvent(
        event_id=event_id(
            "BTCUSDT",
            "15m",
            FvgDirection.BULLISH,
            candle_c_open,
            FvgEventType.PRE_FVG,
        ),
        event_type=FvgEventType.PRE_FVG,
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
        detected_at=datetime.now(UTC),
        is_confirmed=False,
        data_complete=True,
    )


class RecipientSettings:
    def recipients(self, event):
        return [42]


class FailingBot:
    def __init__(self):
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        raise RuntimeError("temporary Telegram outage")


class SuccessfulBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class PersistentDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_pre_fvg_retries_after_restart_without_reevaluation(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "events.sqlite3"
            store = FvgEventStore(database)
            event = make_pre_event()
            first_service = FvgAlertService(
                settings=RecipientSettings(),
                event_store=store,
            )
            failing_bot = FailingBot()

            await first_service.deliver(failing_bot, [event])
            self.assertEqual(failing_bot.calls, 1)
            self.assertEqual(store.health()["outbox"], 1)
            self.assertEqual(store.health()["deliveries"], 0)
            self.assertEqual(store.due_deliveries(), [])

            # Simulate elapsed backoff and a process restart. No market event is
            # evaluated again; the new service drains the persisted outbox.
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "UPDATE outbox SET next_attempt_at = ?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
                )
                connection.commit()

            restarted_service = FvgAlertService(
                settings=RecipientSettings(),
                event_store=FvgEventStore(database),
            )
            successful_bot = SuccessfulBot()
            delivered = await restarted_service.retry_pending(successful_bot)

            self.assertEqual(delivered, 1)
            self.assertEqual(len(successful_bot.messages), 1)
            self.assertEqual(successful_bot.messages[0]["chat_id"], 42)
            self.assertEqual(store.health()["outbox"], 0)
            self.assertEqual(store.health()["deliveries"], 1)
            self.assertFalse(store.delivery_needed(42, event.event_id))


if __name__ == "__main__":
    unittest.main()
