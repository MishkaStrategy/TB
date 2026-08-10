import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.background_tasks import BackgroundTaskRegistry
from database.operations_status import OperationsStatusReader
from database.runtime_lifecycle import RuntimeLifecycleStore
from database.sqlite_observability import SQLiteObservabilityStore


UTC = timezone.utc


class OperationsStatusReaderTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite3"
            result = OperationsStatusReader(path).snapshot()

            self.assertFalse(result["available"])
            self.assertEqual(result["error_message"], "database_file_missing")
            self.assertFalse(path.exists())

    def test_reader_does_not_create_optional_tables(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "plain.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE existing(id INTEGER PRIMARY KEY)")
                connection.commit()

            result = OperationsStatusReader(path).snapshot()

            self.assertTrue(result["available"])
            self.assertFalse(result["lifecycle"]["available"])
            self.assertFalse(result["tasks"]["available"])
            self.assertFalse(result["databases"]["available"])
            with closing(sqlite3.connect(path)) as connection:
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                }
            self.assertEqual(names, {"existing"})

    def test_reads_lifecycle_task_problems_and_database_growth(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

            lifecycle = RuntimeLifecycleStore(path)
            lifecycle.begin_start(
                instance_id="instance-1",
                pid=321,
                now=now - timedelta(minutes=2),
            )
            lifecycle.transition(
                "instance-1",
                "running",
                phase="post_init",
                now=now - timedelta(minutes=1),
            )

            tasks = BackgroundTaskRegistry(path)
            tasks.register(
                "healthy-job",
                expected_interval_seconds=60,
                now=now - timedelta(seconds=30),
            )
            tasks.register(
                "overdue-job",
                expected_interval_seconds=10,
                now=now - timedelta(seconds=40),
            )
            tasks.try_begin(
                "expired-job",
                owner_id="old-worker",
                lease_seconds=10,
                expected_interval_seconds=300,
                now=now - timedelta(seconds=20),
            )
            failed_claim = tasks.try_begin(
                "failed-job",
                owner_id="worker",
                lease_seconds=60,
                expected_interval_seconds=60,
                now=now - timedelta(seconds=10),
            )
            tasks.finish_failure(
                "failed-job",
                failed_claim["run_id"],
                owner_id="worker",
                error=RuntimeError("broken"),
                error_code="test_failure",
                now=now - timedelta(seconds=5),
            )

            observations = SQLiteObservabilityStore(path)
            base_snapshot = {
                "database_key": "fvg",
                "database_path": str(path),
                "available": True,
                "error_message": None,
                "wal_bytes": 0,
                "shm_bytes": 0,
                "page_size": 4096,
                "page_count": 10,
                "freelist_count": 0,
                "allocated_bytes": 40960,
                "free_bytes": 0,
                "journal_mode": "wal",
                "user_version": 0,
                "schema_version": 1,
                "quick_check": None,
                "dbstat_available": False,
                "objects": [],
            }
            observations.record(
                {
                    **base_snapshot,
                    "captured_at": (now - timedelta(hours=2)).isoformat(),
                    "main_bytes": 1000,
                    "used_bytes": 30000,
                }
            )
            observations.record(
                {
                    **base_snapshot,
                    "captured_at": now.isoformat(),
                    "main_bytes": 1500,
                    "used_bytes": 32000,
                }
            )

            result = OperationsStatusReader(path).snapshot(now=now)

            self.assertTrue(result["available"])
            self.assertEqual(result["lifecycle"]["state"]["status"], "running")
            self.assertEqual(result["lifecycle"]["state"]["pid"], 321)
            self.assertEqual(result["tasks"]["total"], 4)
            self.assertEqual(result["tasks"]["expired_lease_count"], 1)
            self.assertEqual(result["tasks"]["overdue_count"], 1)
            problem_names = {
                item["task_name"] for item in result["tasks"]["problems"]
            }
            self.assertEqual(
                problem_names,
                {"expired-job", "failed-job", "overdue-job"},
            )
            failed = next(
                item
                for item in result["tasks"]["problems"]
                if item["task_name"] == "failed-job"
            )
            self.assertEqual(failed["last_error_code"], "test_failure")
            self.assertEqual(result["databases"]["latest"][0]["main_bytes"], 1500)
            self.assertEqual(
                result["databases"]["growth_24h"][0]["main_bytes_delta"],
                500,
            )
            self.assertEqual(
                result["databases"]["growth_24h"][0]["used_bytes_delta"],
                2000,
            )


if __name__ == "__main__":
    unittest.main()
