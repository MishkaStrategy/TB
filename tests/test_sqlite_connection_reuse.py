import json
import sqlite3
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.fvg_models import FvgDirection, FvgEvent, FvgEventType, event_id
from alerts.fvg_store import FvgEventStore


UTC = timezone.utc


def make_event() -> FvgEvent:
    candle_c_open = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
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


class SqliteConnectionReuseTests(unittest.TestCase):
    def test_same_thread_reuses_connection_and_commits_each_method(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = FvgEventStore(path)
            event = make_event()

            first = store._connect()
            store.record_event(event)
            store.enqueue_deliveries(event.event_id, [42], "pending")
            store.mark_delivered(42, event.event_id)
            store.increment_health("notifications_sent")
            second = store._connect()

            self.assertIs(first, second)
            with closing(sqlite3.connect(path)) as observer:
                delivered = observer.execute(
                    "SELECT COUNT(*) FROM deliveries"
                ).fetchone()[0]
                pending = observer.execute(
                    "SELECT COUNT(*) FROM outbox"
                ).fetchone()[0]
                raw_health = observer.execute(
                    "SELECT value_json FROM health WHERE key = 'notifications_sent'"
                ).fetchone()[0]
                mode = observer.execute("PRAGMA journal_mode").fetchone()[0]

            self.assertEqual(delivered, 1)
            self.assertEqual(pending, 0)
            self.assertEqual(json.loads(raw_health), 1)
            self.assertEqual(mode.lower(), "wal")
            store.close()

    def test_different_threads_do_not_share_connections(self):
        with TemporaryDirectory() as directory:
            store = FvgEventStore(Path(directory) / "events.sqlite3")
            main_connection = store._connect()
            worker_connection_ids = []

            def worker():
                connection = store._connect()
                worker_connection_ids.append(id(connection))
                store.increment_health("worker_updates")
                store.close()

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()

            self.assertEqual(len(worker_connection_ids), 1)
            self.assertNotEqual(id(main_connection), worker_connection_ids[0])
            self.assertEqual(store.health()["worker_updates"], 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
