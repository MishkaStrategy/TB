import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from alerts.funding_alerts import (
    FundingAlertService,
    FundingAlertStore,
    matching_crossings,
    next_hour_at_50,
    parse_interval_hours,
    parse_threshold,
)


UTC = timezone.utc


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class FundingAlertParsingTests(unittest.TestCase):
    def test_next_hour_slot_is_always_minute_fifty(self):
        self.assertEqual(
            next_hour_at_50(datetime(2026, 7, 27, 14, 23, tzinfo=UTC)),
            datetime(2026, 7, 27, 14, 50, tzinfo=UTC),
        )
        self.assertEqual(
            next_hour_at_50(datetime(2026, 7, 27, 14, 55, tzinfo=UTC)),
            datetime(2026, 7, 27, 15, 50, tzinfo=UTC),
        )

    def test_validates_interval_and_threshold(self):
        self.assertEqual(parse_interval_hours("48"), 48)
        self.assertEqual(parse_threshold("0,30%"), Decimal("0.3"))
        for invalid in (0, 49, "1.5", "abc"):
            with self.assertRaises(ValueError):
                parse_interval_hours(invalid)
        for invalid in (0, -1, "abc"):
            with self.assertRaises(ValueError):
                parse_threshold(invalid)

    def test_matches_selected_directions(self):
        matches = matching_crossings(
            [
                {"symbol": "PUSDT", "fundingRate": "0.4"},
                {"symbol": "NUSDT", "fundingRate": "-0.5"},
                {"symbol": "LOW", "fundingRate": "0.1"},
            ],
            {
                "threshold": Decimal("0.3"),
                "notify_positive": True,
                "notify_negative": False,
            },
        )
        self.assertEqual(matches, {("PUSDT", "positive"): Decimal("0.4")})


class FundingAlertStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "funding.sqlite3"
        self.store = FundingAlertStore(self.path)
        self.now = datetime(2026, 7, 27, 14, 23, tzinfo=UTC)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_settings_schedule_and_crossings_are_bounded(self):
        self.store.set_interval(10, 4, now=self.now)
        self.store.set_threshold(10, "0.3", now=self.now)
        settings = self.store.set_enabled(10, True, now=self.now)
        self.assertEqual(settings["next_check_at"], datetime(2026, 7, 27, 14, 50, tzinfo=UTC))
        self.assertEqual(self.store.due_users(datetime(2026, 7, 27, 14, 49, tzinfo=UTC)), [])
        self.assertEqual(len(self.store.due_users(datetime(2026, 7, 27, 14, 50, tzinfo=UTC))), 1)

        self.store.replace_crossings(
            10,
            {
                ("BTCUSDT", "positive"): Decimal("0.4"),
                ("ETHUSDT", "negative"): Decimal("-0.5"),
            },
            now=datetime(2026, 7, 27, 14, 50, tzinfo=UTC),
        )
        self.store.replace_crossings(
            10,
            {("BTCUSDT", "positive"): Decimal("0.45")},
            now=datetime(2026, 7, 27, 18, 50, tzinfo=UTC),
        )
        self.assertEqual(self.store.active_crossings(10), {("BTCUSDT", "positive")})
        self.assertEqual(
            self.store.advance(10, datetime(2026, 7, 27, 14, 50, tzinfo=UTC)),
            datetime(2026, 7, 27, 18, 50, tzinfo=UTC),
        )

    def test_cannot_disable_both_directions(self):
        with self.assertRaises(ValueError):
            self.store.set_directions(
                10,
                notify_positive=False,
                notify_negative=False,
                now=self.now,
            )

    def test_cleanup_removes_old_disabled_rows_and_stale_crossings(self):
        self.store.set_enabled(10, True, now=self.now)
        self.store.replace_crossings(
            10,
            {("BTCUSDT", "positive"): Decimal("0.4")},
            now=self.now,
        )
        old = self.now - timedelta(days=200)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "UPDATE funding_alert_settings SET enabled = 0, updated_at = ? WHERE chat_id = '10'",
                (old.isoformat(),),
            )
            connection.execute(
                "UPDATE funding_alert_crossings SET last_seen_at = ? WHERE chat_id = '10'",
                (old.isoformat(),),
            )
        result = self.store.cleanup(self.now, force=True)
        self.assertEqual(result["settings"], 1)
        self.assertEqual(result["crossings"], 1)
        self.assertFalse(self.store.path.stat().st_size == 0)


class FundingAlertServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_notifies_only_on_new_threshold_crossings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            store = FundingAlertStore(Path(tempdir) / "funding.sqlite3")
            start = datetime(2026, 7, 27, 14, 23, tzinfo=UTC)
            store.set_threshold(42, "0.3", now=start)
            store.set_enabled(42, True, now=start)
            payload = [
                {"symbol": "PUSDT", "fundingRate": "0.4"},
                {"symbol": "NUSDT", "fundingRate": "-0.5"},
            ]
            calls = 0

            async def loader():
                nonlocal calls
                calls += 1
                return payload

            bot = FakeBot()
            service = FundingAlertService(store=store, loader=loader)

            await service.run(bot, now=datetime(2026, 7, 27, 14, 50, tzinfo=UTC))
            self.assertEqual(len(bot.messages), 1)
            self.assertIn("PUSDT", bot.messages[0]["text"])
            self.assertIn("NUSDT", bot.messages[0]["text"])

            await service.run(bot, now=datetime(2026, 7, 27, 15, 50, tzinfo=UTC))
            self.assertEqual(len(bot.messages), 1)

            payload[:] = [{"symbol": "PUSDT", "fundingRate": "0.1"}]
            await service.run(bot, now=datetime(2026, 7, 27, 16, 50, tzinfo=UTC))
            self.assertEqual(store.active_crossings(42), set())

            payload[:] = [{"symbol": "PUSDT", "fundingRate": "0.4"}]
            await service.run(bot, now=datetime(2026, 7, 27, 17, 50, tzinfo=UTC))
            self.assertEqual(len(bot.messages), 2)
            self.assertEqual(calls, 4)


if __name__ == "__main__":
    unittest.main()
