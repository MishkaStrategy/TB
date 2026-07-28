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

UTC = timezone.utc


class FundingStorageStdlibTests(unittest.TestCase):
    def test_quarter_hour_parser_and_legacy_migration(self):
        self.assertEqual(parse_interval_minutes("15"), 15)
        self.assertEqual(parse_interval_minutes("1,5ч"), 90)
        self.assertEqual(
            next_quarter_hour(datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
            datetime(2026, 7, 28, 14, 30, tzinfo=UTC),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            now = datetime(2026, 7, 28, 14, 1, tzinfo=UTC)
            legacy = LegacyFundingAlertStore(path)
            legacy.set_interval(10, 4, now=now)
            legacy.set_enabled(10, True, now=now)

            store = FundingAlertStore(path)
            settings = store.user(10)
            self.assertEqual(settings["interval_minutes"], 240)
            self.assertIsNone(settings["next_check_at"])

            store.set_interval(10, 45, now=now)
            self.assertEqual(store.user(10)["interval_minutes"], 45)
            self.assertEqual(
                store.advance(10, datetime(2026, 7, 28, 14, 15, tzinfo=UTC)),
                datetime(2026, 7, 28, 15, 0, tzinfo=UTC),
            )

    def test_history_keeps_three_rows_and_checkpoints_wal(self):
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
                            }
                        ],
                        "bingx": [],
                    },
                    captured_at=datetime(2026, 7, 28, 14, minute, tzinfo=UTC),
                )

            self.assertEqual(store.count(), 3)
            self.assertEqual(
                [item["captured_at"].minute for item in store.latest()],
                [45, 30, 15],
            )
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM funding_snapshot_history"
                    ).fetchone()[0],
                    3,
                )
            wal_path = Path(f"{path}-wal")
            self.assertTrue(not wal_path.exists() or wal_path.stat().st_size == 0)


if __name__ == "__main__":
    unittest.main()
