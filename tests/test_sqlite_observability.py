import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.sqlite_observability import (
    SQLiteObservabilityService,
    SQLiteObservabilityStore,
    SQLiteSnapshotCollector,
)


UTC = timezone.utc


def create_database(path: Path, rows=2):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO items(value) VALUES (?)",
            [(f"value-{index}",) for index in range(rows)],
        )
        connection.commit()


def snapshot(database_key, captured_at, main_bytes, *, objects=None):
    return {
        "database_key": database_key,
        "database_path": f"/tmp/{database_key}.sqlite3",
        "captured_at": captured_at.isoformat(),
        "available": True,
        "error_message": None,
        "main_bytes": main_bytes,
        "wal_bytes": 0,
        "shm_bytes": 0,
        "page_size": 4096,
        "page_count": main_bytes // 4096,
        "freelist_count": 0,
        "allocated_bytes": main_bytes,
        "free_bytes": 0,
        "used_bytes": main_bytes,
        "journal_mode": "wal",
        "user_version": 1,
        "schema_version": 1,
        "quick_check": None,
        "dbstat_available": True,
        "objects": objects or [],
    }


class SQLiteSnapshotCollectorTests(unittest.TestCase):
    def test_collects_read_only_page_object_and_optional_diagnostics(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "target.sqlite3"
            create_database(path, rows=3)
            collector = SQLiteSnapshotCollector(
                include_row_counts=True,
                include_integrity_check=True,
            )

            result = collector.collect(
                "target",
                path,
                now=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            )

            self.assertTrue(result["available"])
            self.assertGreater(result["main_bytes"], 0)
            self.assertGreater(result["page_size"], 0)
            self.assertGreater(result["page_count"], 0)
            self.assertEqual(result["quick_check"], "ok")
            objects = {item["object_name"]: item for item in result["objects"]}
            self.assertIn("items", objects)
            self.assertEqual(objects["items"]["row_count"], 3)

    def test_missing_database_is_recordable_without_creating_target(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite3"
            result = SQLiteSnapshotCollector().collect("missing", path)
            self.assertFalse(result["available"])
            self.assertEqual(result["error_message"], "database_file_missing")
            self.assertFalse(path.exists())


class SQLiteObservabilityStoreTests(unittest.TestCase):
    def test_record_is_idempotent_and_growth_uses_first_and_last(self):
        with TemporaryDirectory() as directory:
            store = SQLiteObservabilityStore(Path(directory) / "store.sqlite3")
            first_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
            last_at = first_at + timedelta(days=1)
            first = snapshot(
                "fvg",
                first_at,
                4096,
                objects=[
                    {
                        "object_name": "events",
                        "object_type": "table",
                        "bytes": 2048,
                        "pages": 1,
                        "row_count": 5,
                    }
                ],
            )
            first_id = store.record(first)
            self.assertEqual(store.record(first), first_id)
            last_id = store.record(snapshot("fvg", last_at, 12288))

            latest = store.latest("fvg")
            self.assertEqual(latest["id"], last_id)
            self.assertEqual(store.objects(first_id)[0]["row_count"], 5)
            growth = store.growth("fvg")
            self.assertEqual(growth["main_bytes_delta"], 8192)
            self.assertEqual(growth["used_bytes_delta"], 8192)
            self.assertEqual(growth["elapsed_seconds"], 86400)

    def test_prune_is_bounded_and_cascades_objects(self):
        with TemporaryDirectory() as directory:
            store = SQLiteObservabilityStore(Path(directory) / "store.sqlite3")
            recent = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            old_id = store.record(
                snapshot(
                    "fvg",
                    recent - timedelta(days=2),
                    4096,
                    objects=[
                        {
                            "object_name": "events",
                            "object_type": "table",
                            "bytes": 4096,
                            "pages": 1,
                            "row_count": None,
                        }
                    ],
                )
            )
            recent_id = store.record(snapshot("fvg", recent, 8192))

            deleted = store.prune(
                retention_days=1,
                batch_size=1,
                now=recent + timedelta(hours=12),
            )

            self.assertEqual(deleted, 1)
            self.assertEqual(store.objects(old_id), [])
            self.assertEqual(store.latest("fvg")["id"], recent_id)


class SQLiteObservabilityServiceTests(unittest.TestCase):
    def test_capture_records_all_configured_databases(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fvg_path = root / "fvg.sqlite3"
            funding_path = root / "funding.sqlite3"
            create_database(fvg_path, rows=1)
            create_database(funding_path, rows=2)
            store = SQLiteObservabilityStore(root / "observations.sqlite3")
            service = SQLiteObservabilityService(
                databases={"fvg": fvg_path, "funding": funding_path},
                store=store,
                include_row_counts=True,
                retention_days=90,
            )

            result = service.capture(
                now=datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            )

            self.assertEqual(len(result["snapshots"]), 2)
            self.assertTrue(all(item["available"] for item in result["snapshots"]))
            self.assertEqual(set(store.latest()), {"fvg", "funding"})
            self.assertEqual(result["pruned"], 0)


if __name__ == "__main__":
    unittest.main()
