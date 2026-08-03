import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.sqlite_event_store import FvgEventStore
from database.fvg_history_archive import FvgHistoryArchive
from operations.fvg_history_retention import configure_fvg_history_retention


UTC = timezone.utc


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
            json.dumps({"event_id": event_id}),
        ),
    )


class FvgHistoryRetentionTests(unittest.TestCase):
    def test_disabled_rollout_preserves_original_prune_method(self):
        with TemporaryDirectory() as directory:
            store = FvgEventStore(Path(directory) / "runtime.sqlite3")
            original = store._prune_if_due

            configured = configure_fvg_history_retention(store, enabled=False)

            self.assertFalse(configured)
            self.assertEqual(store._prune_if_due, original)
            self.assertFalse(hasattr(store, "_history_archive_configured"))

    def test_enabled_retention_archives_and_updates_health(self):
        with TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            store = FvgEventStore(runtime)
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            with store._connect() as connection:
                insert_event(connection, "old", now - timedelta(days=100))
                connection.execute(
                    "INSERT INTO deliveries VALUES('old', '123', ?)",
                    ((now - timedelta(days=99)).isoformat(),),
                )

            configured = configure_fvg_history_retention(
                store,
                enabled=True,
                archive_path=archive_path,
                retention_days=90,
                batch_size=10,
                max_batches=2,
            )
            with store._connect() as connection:
                store._prune_if_due(connection, now)

            self.assertTrue(configured)
            self.assertEqual(store.health()["events"], 0)
            health = store.health()
            self.assertEqual(health["events_archived"], 1)
            self.assertEqual(health["deliveries_archived"], 1)
            self.assertEqual(health["events_pruned"], 1)
            self.assertIsNone(health["last_archive_error"])
            archive = FvgHistoryArchive(archive_path)
            self.assertEqual(archive.summary()["events"], 1)
            self.assertEqual(archive.summary()["deliveries"], 1)

    def test_bounded_max_batches_leaves_backlog_signal(self):
        with TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            store = FvgEventStore(runtime)
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            with store._connect() as connection:
                for index in range(3):
                    insert_event(
                        connection,
                        f"old-{index}",
                        now - timedelta(days=100, minutes=index),
                    )

            configure_fvg_history_retention(
                store,
                enabled=True,
                archive_path=archive_path,
                retention_days=90,
                batch_size=1,
                max_batches=2,
            )
            with store._connect() as connection:
                store._prune_if_due(connection, now)

            health = store.health()
            self.assertEqual(health["events"], 1)
            self.assertEqual(health["events_archived"], 2)
            self.assertTrue(health["fvg_archive_backlog_possible"])
            self.assertEqual(FvgHistoryArchive(archive_path).summary()["events"], 2)

    def test_archive_failure_rolls_back_prune_but_allows_source_transaction(self):
        class FailingArchive:
            def archive_and_delete(self, source, *, cutoff, now):
                del source, cutoff, now
                raise sqlite3.OperationalError("archive offline")

        with TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            store = FvgEventStore(runtime)
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            with store._connect() as connection:
                insert_event(connection, "old", now - timedelta(days=100))

            configure_fvg_history_retention(
                store,
                enabled=True,
                archive_path=archive_path,
                archive=FailingArchive(),
            )
            with store._connect() as connection:
                store._prune_if_due(connection, now)
                insert_event(connection, "new", now)

            health = store.health()
            self.assertEqual(health["events"], 2)
            self.assertEqual(health["fvg_archive_failures"], 1)
            self.assertIn("archive offline", health["last_archive_error"])
            self.assertNotIn("last_pruned_at", health)

    def test_configuration_is_idempotent_and_rejects_source_as_archive(self):
        with TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.sqlite3"
            archive_path = Path(directory) / "archive.sqlite3"
            store = FvgEventStore(runtime)
            self.assertTrue(
                configure_fvg_history_retention(
                    store,
                    enabled=True,
                    archive_path=archive_path,
                )
            )
            method = store._prune_if_due
            self.assertTrue(
                configure_fvg_history_retention(
                    store,
                    enabled=True,
                    archive_path=archive_path,
                )
            )
            self.assertEqual(store._prune_if_due, method)

            other = FvgEventStore(Path(directory) / "other.sqlite3")
            with self.assertRaisesRegex(ValueError, "must differ"):
                configure_fvg_history_retention(
                    other,
                    enabled=True,
                    archive_path=other.path,
                )


if __name__ == "__main__":
    unittest.main()
