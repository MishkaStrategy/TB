import json
import sqlite3
import threading
import unittest
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
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc


def make_event(
    *,
    detected_at=None,
    direction=FvgDirection.BULLISH,
    event_type=FvgEventType.CONFIRMED_FVG,
):
    candle_c_open = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    detected_at = detected_at or candle_c_open + timedelta(minutes=15)
    return FvgEvent(
        event_id=event_id(
            "BTCUSDT", "15m", direction, candle_c_open, event_type
        ),
        event_type=event_type,
        symbol="BTCUSDT",
        timeframe="15m",
        direction=direction,
        candle_a_open_time=candle_c_open - timedelta(minutes=30),
        candle_b_open_time=candle_c_open - timedelta(minutes=15),
        candle_c_open_time=candle_c_open,
        candle_c_close_time=candle_c_open + timedelta(minutes=15),
        zone_low=Decimal("100"),
        zone_high=Decimal("101"),
        zone_size=Decimal("1"),
        signal_price=Decimal("102"),
        detected_at=detected_at,
        is_confirmed=event_type is FvgEventType.CONFIRMED_FVG,
        data_complete=True,
    )


class SqliteEventStoreTests(unittest.TestCase):
    def test_records_deduplicates_delivers_and_summarizes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = FvgEventStore(path)
            event = make_event()

            self.assertTrue(store.record_event(event))
            self.assertFalse(store.record_event(event))
            self.assertTrue(store.delivery_needed(42, event.event_id))
            store.mark_delivered(42, event.event_id)
            self.assertFalse(store.delivery_needed(42, event.event_id))

            store.update_health(ws_connected=True, last_error=None)
            store.increment_health("notifications_sent")
            store.increment_health("notifications_sent", 2)
            health = store.health()
            self.assertEqual(health["events"], 1)
            self.assertEqual(health["deliveries"], 1)
            self.assertEqual(health["notifications_sent"], 3)
            self.assertTrue(health["ws_connected"])

            summary = store.summary(days=None)
            self.assertEqual(summary["BULLISH"]["confirmed"], 1)
            self.assertEqual(summary["deliveries"], 1)

            with sqlite3.connect(path) as connection:
                mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_imports_legacy_json_once(self):
        with TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "legacy.json"
            database_path = Path(directory) / "events.sqlite3"
            event = make_event()
            payload = event.to_json()
            legacy_path.write_text(
                json.dumps(
                    {
                        "events": {event.event_id: payload},
                        "deliveries": {
                            event.event_id: {"42": datetime.now(UTC).isoformat()}
                        },
                        "health": {"notifications_sent": 1},
                    }
                ),
                encoding="utf-8",
            )

            first = FvgEventStore(
                database_path,
                legacy_json_path=legacy_path,
            )
            self.assertFalse(first.record_event(event))
            self.assertFalse(first.delivery_needed(42, event.event_id))
            self.assertEqual(first.health()["notifications_sent"], 1)

            # Reopening does not duplicate rows or reapply changed legacy values.
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            legacy["health"]["notifications_sent"] = 99
            legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
            second = FvgEventStore(
                database_path,
                legacy_json_path=legacy_path,
            )
            self.assertEqual(second.health()["notifications_sent"], 1)
            self.assertEqual(second.health()["events"], 1)

    def test_concurrent_health_increments_are_atomic(self):
        with TemporaryDirectory() as directory:
            store = FvgEventStore(Path(directory) / "events.sqlite3")

            def increment_many():
                for _ in range(25):
                    store.increment_health("messages")

            threads = [threading.Thread(target=increment_many) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(store.health()["messages"], 100)

    def test_backup_is_consistent_and_readable(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "events.sqlite3"
            backup = Path(directory) / "backup.sqlite3"
            store = FvgEventStore(source)
            event = make_event()
            store.record_event(event)
            store.mark_delivered(42, event.event_id)
            store.backup_to(backup)

            restored = FvgEventStore(backup)
            self.assertEqual(restored.health()["events"], 1)
            self.assertEqual(restored.health()["deliveries"], 1)
            self.assertFalse(restored.delivery_needed(42, event.event_id))

    def test_retention_removes_old_events_and_deliveries(self):
        with TemporaryDirectory() as directory:
            store = FvgEventStore(Path(directory) / "events.sqlite3")
            old = make_event(detected_at=datetime.now(UTC) - timedelta(days=120))
            current = make_event(
                detected_at=datetime.now(UTC),
                direction=FvgDirection.BEARISH,
            )
            store.record_event(old)
            store.mark_delivered(42, old.event_id)
            # Force the next record to run retention again.
            with sqlite3.connect(store.path) as connection:
                connection.execute(
                    "DELETE FROM health WHERE key = 'last_pruned_at'"
                )
            store.record_event(current)

            self.assertEqual(store.health()["events"], 1)
            self.assertEqual(store.health()["deliveries"], 0)
            self.assertEqual(store.summary(days=None)["BEARISH"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
