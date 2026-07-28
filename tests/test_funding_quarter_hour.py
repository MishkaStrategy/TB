import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alerts.funding_alerts import FundingAlertStore as LegacyFundingAlertStore
from alerts.funding_quarter_hour import (
    FundingAlertStore,
    next_quarter_hour,
    parse_interval_minutes,
)
from alerts.funding_snapshot_store import FundingSnapshotStore
from alerts.multi_funding_alerts import MultiFundingAlertService
from handlers.multi_funding_alert_ui import format_interval

UTC = timezone.utc


class FakeBot:
    async def send_message(self, **kwargs):
        return kwargs


class FundingQuarterHourParsingTests(unittest.TestCase):
    def test_next_slot_is_the_nearest_future_quarter_hour(self):
        self.assertEqual(
            next_quarter_hour(datetime(2026, 7, 28, 14, 1, tzinfo=UTC)),
            datetime(2026, 7, 28, 14, 15, tzinfo=UTC),
        )
        self.assertEqual(
            next_quarter_hour(datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
            datetime(2026, 7, 28, 14, 30, tzinfo=UTC),
        )
        self.assertEqual(
            next_quarter_hour(datetime(2026, 7, 28, 14, 59, tzinfo=UTC)),
            datetime(2026, 7, 28, 15, 0, tzinfo=UTC),
        )

    def test_interval_parser_uses_fifteen_minute_steps(self):
        self.assertEqual(parse_interval_minutes("15"), 15)
        self.assertEqual(parse_interval_minutes("45 мин"), 45)
        self.assertEqual(parse_interval_minutes("1ч"), 60)
        self.assertEqual(parse_interval_minutes("1,5ч"), 90)
        self.assertEqual(parse_interval_minutes("48h"), 2880)
        for invalid in (0, 10, 16, 2895, "abc"):
            with self.assertRaises(ValueError):
                parse_interval_minutes(invalid)

    def test_formats_compact_human_readable_intervals(self):
        self.assertEqual(format_interval(15), "15 мин.")
        self.assertEqual(format_interval(60), "1 ч.")
        self.assertEqual(format_interval(90), "1 ч. 30 мин.")


class FundingQuarterHourMigrationTests(unittest.TestCase):
    def test_migrates_legacy_hours_without_changing_effective_frequency(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            legacy = LegacyFundingAlertStore(path)
            now = datetime(2026, 7, 28, 14, 1, tzinfo=UTC)
            legacy.set_interval(10, 4, now=now)
            legacy.set_enabled(10, True, now=now)

            store = FundingAlertStore(path)
            settings = store.user(10)
            self.assertEqual(settings["interval_minutes"], 240)
            self.assertIsNone(settings["next_check_at"])
            self.assertEqual(
                len(store.due_users(datetime(2026, 7, 28, 14, 15, tzinfo=UTC))),
                1,
            )

            store.set_interval(10, 45, now=now)
            settings = store.user(10)
            self.assertEqual(settings["interval_minutes"], 45)
            self.assertEqual(
                settings["next_check_at"],
                datetime(2026, 7, 28, 14, 15, tzinfo=UTC),
            )
            self.assertEqual(
                store.advance(10, datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
                datetime(2026, 7, 28, 15, 0, tzinfo=UTC),
            )

            with sqlite3.connect(path) as connection:
                row = connection.execute(
                    "SELECT interval_hours, interval_minutes "
                    "FROM funding_alert_settings WHERE chat_id = '10'"
                ).fetchone()
            self.assertEqual(row, (1, 45))


class FundingSnapshotStoreTests(unittest.TestCase):
    def test_keeps_only_three_compressed_full_market_snapshots(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            store = FundingSnapshotStore(path)
            for minute in (0, 15, 30, 45):
                store.save(
                    {
                        "binance": [
                            {
                                "symbol": "BTCUSDT",
                                "fundingRate": str(minute / 1000),
                                "priceChange24h": "1.5",
                            }
                        ],
                        "bingx": [],
                    },
                    captured_at=datetime(2026, 7, 28, 14, minute, tzinfo=UTC),
                )

            self.assertEqual(store.count(), 3)
            latest = store.latest()
            self.assertEqual(
                [item["captured_at"].minute for item in latest],
                [45, 30, 15],
            )
            self.assertEqual(latest[0]["exchange_count"], 2)
            self.assertEqual(latest[0]["rate_count"], 1)
            self.assertEqual(
                latest[0]["snapshot"]["binance"][0]["symbol"],
                "BTCUSDT",
            )
            self.assertGreater(latest[0]["compressed_bytes"], 0)


class MultiFundingSnapshotIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduled_service_retains_only_last_three_downloads(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            settings = FundingAlertStore(path)
            history = FundingSnapshotStore(path)
            call = 0

            async def loader():
                nonlocal call
                call += 1
                return {
                    "binance": [
                        {
                            "symbol": "BTCUSDT",
                            "fundingRate": str(call / 100),
                        }
                    ]
                }

            service = MultiFundingAlertService(
                settings_store=settings,
                snapshot_store=history,
                loader=loader,
            )
            for minute in (0, 15, 30, 45):
                await service.run(
                    FakeBot(),
                    now=datetime(2026, 7, 28, 14, minute, tzinfo=UTC),
                )

            self.assertEqual(call, 4)
            self.assertEqual(history.count(), 3)
            self.assertEqual(
                [item["captured_at"].minute for item in history.latest()],
                [45, 30, 15],
            )


if __name__ == "__main__":
    unittest.main()
