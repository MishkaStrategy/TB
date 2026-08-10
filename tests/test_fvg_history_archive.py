import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.fvg_history_archive import FvgHistoryArchive


UTC = timezone.utc


def prepare_source(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            direction TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            candle_c_close_time TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE deliveries (
            event_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            delivered_at TEXT NOT NULL,
            PRIMARY KEY(event_id, chat_id),
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
        );
        CREATE TABLE outbox (
            event_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            PRIMARY KEY(event_id, chat_id),
            FOREIGN KEY(event_id) REFERENCES events(event_id) ON DELETE CASCADE
        );
        CREATE TABLE telegram_outbox (
            id TEXT PRIMARY KEY,
            event_id TEXT,
            status TEXT NOT NULL
        );
        """
    )
    return connection


def insert_event(connection, event_id: str, detected_at: datetime):
    connection.execute(
        """
        INSERT INTO events(
            event_id, event_type, symbol, timeframe, direction,
            detected_at, candle_c_close_time, payload_json
        ) VALUES (?, 'CONFIRMED_FVG', 'BTCUSDT', '15m', 'BULLISH', ?, ?, ?)
        """,
        (
            event_id,
            detected_at.isoformat(),
            (detected_at + timedelta(minutes=15)).isoformat(),
            '{"event_id":"%s"}' % event_id,
        ),
    )


class FvgHistoryArchiveTests(unittest.TestCase):
    def test_archives_events_and_deliveries_before_source_delete(self):
        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            source = prepare_source(source_path)
            self.addCleanup(source.close)
            insert_event(source, "old-one", now - timedelta(days=100))
            insert_event(source, "old-two", now - timedelta(days=95))
            insert_event(source, "recent", now - timedelta(days=5))
            source.execute(
                "INSERT INTO deliveries VALUES('old-one', '123', ?)",
                ((now - timedelta(days=99)).isoformat(),),
            )
            source.commit()
            archive = FvgHistoryArchive(archive_path, batch_size=10)

            source.execute("BEGIN IMMEDIATE")
            result = archive.archive_and_delete(
                source,
                cutoff=now - timedelta(days=90),
                now=now,
            )
            source.commit()

            self.assertEqual(result["events_archived"], 2)
            self.assertEqual(result["deliveries_archived"], 1)
            self.assertEqual(result["source_deleted"], 2)
            self.assertFalse(result["batch_full"])
            remaining = {
                row[0] for row in source.execute("SELECT event_id FROM events")
            }
            self.assertEqual(remaining, {"recent"})
            summary = archive.summary()
            self.assertEqual(summary["events"], 2)
            self.assertEqual(summary["deliveries"], 1)
            self.assertEqual(summary["last_run"]["source_deleted_count"], 2)

    def test_active_legacy_and_v2_outbox_events_are_not_deleted(self):
        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            source = prepare_source(source_path)
            self.addCleanup(source.close)
            for event_id in ("legacy", "v2-active", "v2-terminal"):
                insert_event(source, event_id, now - timedelta(days=100))
            source.execute("INSERT INTO outbox VALUES('legacy', '1')")
            source.execute(
                "INSERT INTO telegram_outbox VALUES('active', 'v2-active', 'retry_scheduled')"
            )
            source.execute(
                "INSERT INTO telegram_outbox VALUES('terminal', 'v2-terminal', 'delivered')"
            )
            source.commit()
            archive = FvgHistoryArchive(archive_path)

            source.execute("BEGIN IMMEDIATE")
            result = archive.archive_and_delete(
                source,
                cutoff=now - timedelta(days=90),
                now=now,
            )
            source.commit()

            self.assertEqual(result["events_archived"], 1)
            self.assertEqual(result["source_deleted"], 1)
            remaining = {
                row[0] for row in source.execute("SELECT event_id FROM events")
            }
            self.assertEqual(remaining, {"legacy", "v2-active"})
            self.assertEqual(archive.summary()["events"], 1)

    def test_existing_archive_rows_make_retry_idempotent(self):
        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            source = prepare_source(source_path)
            self.addCleanup(source.close)
            insert_event(source, "old", now - timedelta(days=100))
            source.commit()
            archive = FvgHistoryArchive(archive_path)
            with closing(sqlite3.connect(archive_path)) as connection:
                connection.execute(
                    """
                    INSERT INTO archived_fvg_events(
                        event_id, event_type, symbol, timeframe, direction,
                        detected_at, candle_c_close_time, payload_json, archived_at
                    ) VALUES('old', 'CONFIRMED_FVG', 'BTCUSDT', '15m', 'BULLISH', ?, NULL, '{}', ?)
                    """,
                    (
                        (now - timedelta(days=100)).isoformat(),
                        (now - timedelta(minutes=1)).isoformat(),
                    ),
                )
                connection.commit()

            source.execute("BEGIN IMMEDIATE")
            result = archive.archive_and_delete(
                source,
                cutoff=now - timedelta(days=90),
                now=now,
            )
            source.commit()

            self.assertEqual(result["events_archived"], 1)
            self.assertEqual(result["source_deleted"], 1)
            self.assertEqual(archive.summary()["events"], 1)

    def test_archive_write_failure_leaves_source_untouched(self):
        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            source = prepare_source(source_path)
            self.addCleanup(source.close)
            insert_event(source, "old", now - timedelta(days=100))
            source.commit()
            archive = FvgHistoryArchive(archive_path)

            def fail_connect():
                raise sqlite3.OperationalError("archive unavailable")

            archive._connect = fail_connect
            source.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "archive unavailable"):
                archive.archive_and_delete(
                    source,
                    cutoff=now - timedelta(days=90),
                    now=now,
                )
            source.rollback()

            self.assertEqual(
                source.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
