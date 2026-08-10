import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.fvg_history_archive import FvgHistoryArchive
from database.operations_status import OperationsStatusReader
from handlers.admin_settings import format_operations_status


UTC = timezone.utc


def _runtime_database(path: Path, health: dict | None = None) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE health(key TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
        )
        if health:
            connection.executemany(
                "INSERT INTO health(key, value_json) VALUES (?, ?)",
                [
                    (str(key), json.dumps(value, ensure_ascii=False))
                    for key, value in health.items()
                ],
            )
        connection.commit()


def _minimal_snapshot(archive: dict) -> dict:
    return {
        "available": True,
        "captured_at": "2026-07-30T00:00:00+00:00",
        "lifecycle": {"available": False, "state": None},
        "restart_guard": {"available": False},
        "fvg_archive": archive,
        "tasks": {
            "available": False,
            "total": 0,
            "counts": {},
            "overdue_count": 0,
            "expired_lease_count": 0,
            "problems": [],
        },
        "databases": {
            "available": False,
            "latest": [],
            "growth_24h": [],
        },
    }


class FvgArchiveOperationsReaderTests(unittest.TestCase):
    def test_missing_archive_file_is_not_created(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "runtime.sqlite3"
            archive_path = root / "archive" / "fvg_history.sqlite3"
            _runtime_database(runtime_path)

            result = OperationsStatusReader(
                runtime_path,
                archive_path=archive_path,
            ).snapshot()

            self.assertTrue(result["available"])
            self.assertFalse(result["fvg_archive"]["exists"])
            self.assertFalse(result["fvg_archive"]["available"])
            self.assertFalse(archive_path.exists())

    def test_reads_latest_run_file_size_and_runtime_health(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "runtime.sqlite3"
            archive_path = root / "archive" / "fvg_history.sqlite3"
            _runtime_database(
                runtime_path,
                {
                    "events_archived": 1250,
                    "deliveries_archived": 900,
                    "events_pruned": 1250,
                    "fvg_archive_failures": 2,
                    "fvg_archive_backlog_possible": True,
                    "last_archive_at": "2026-07-29T23:55:00+00:00",
                    "last_archive_error": "temporary archive write failure",
                },
            )
            FvgHistoryArchive(archive_path)
            with closing(sqlite3.connect(archive_path)) as connection:
                connection.execute(
                    """
                    INSERT INTO fvg_archive_runs(
                        cutoff_at, archived_at, event_count,
                        delivery_count, source_deleted_count
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "2026-05-01T00:00:00+00:00",
                        "2026-07-29T23:55:00+00:00",
                        500,
                        375,
                        500,
                    ),
                )
                connection.commit()

            result = OperationsStatusReader(
                runtime_path,
                archive_path=archive_path,
            ).snapshot(now=datetime(2026, 7, 30, tzinfo=UTC))
            archive = result["fvg_archive"]

            self.assertTrue(archive["exists"])
            self.assertTrue(archive["available"])
            self.assertEqual(str(archive["schema_version"]), "1")
            self.assertGreater(archive["total_bytes"], 0)
            self.assertEqual(archive["latest_run"]["event_count"], 500)
            self.assertEqual(archive["latest_run"]["delivery_count"], 375)
            self.assertEqual(archive["latest_run"]["source_deleted_count"], 500)
            self.assertEqual(archive["runtime_health"]["events_archived"], 1250)
            self.assertTrue(
                archive["runtime_health"]["fvg_archive_backlog_possible"]
            )

            with closing(sqlite3.connect(archive_path)) as connection:
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM fvg_archive_runs"
                ).fetchone()[0]
            self.assertEqual(run_count, 1)

    def test_incomplete_archive_schema_is_reported_without_migration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_path = root / "runtime.sqlite3"
            archive_path = root / "archive.sqlite3"
            _runtime_database(runtime_path)
            with closing(sqlite3.connect(archive_path)) as connection:
                connection.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
                connection.commit()

            archive = OperationsStatusReader(
                runtime_path,
                archive_path=archive_path,
            ).snapshot()["fvg_archive"]

            self.assertFalse(archive["available"])
            self.assertIn("missing_tables", archive["error_message"])
            with closing(sqlite3.connect(archive_path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                }
            self.assertEqual(tables, {"unrelated"})


class FvgArchiveAdminFormatTests(unittest.TestCase):
    def test_formats_archive_health_latest_batch_and_backlog(self):
        text = format_operations_status(
            _minimal_snapshot(
                {
                    "exists": True,
                    "available": True,
                    "error_message": None,
                    "total_bytes": 1536,
                    "latest_run": {
                        "cutoff_at": "2026-05-01T00:00:00+00:00",
                        "archived_at": "2026-07-29T23:55:00+00:00",
                        "event_count": 500,
                        "delivery_count": 375,
                        "source_deleted_count": 500,
                    },
                    "runtime_health": {
                        "events_archived": 1250,
                        "deliveries_archived": 900,
                        "fvg_archive_failures": 2,
                        "fvg_archive_backlog_possible": True,
                        "last_archive_at": "2026-07-29T23:55:00+00:00",
                        "last_archive_error": "temporary failure",
                    },
                }
            )
        )

        self.assertIn("Архив FVG", text)
        self.assertIn("Файл: доступен · 1.5 КБ", text)
        self.assertIn("событий 500, доставок 375, удалено 500", text)
        self.assertIn("событий 1250, доставок 900", text)
        self.assertIn("Ошибок архивирования: 2", text)
        self.assertIn("Backlog возможен: да", text)
        self.assertIn("Последняя ошибка: temporary failure", text)
        self.assertNotIn("Экспорт", text)
        self.assertNotIn("Восстановить", text)
        self.assertLess(len(text), 4096)

    def test_formats_missing_archive_file(self):
        text = format_operations_status(
            _minimal_snapshot(
                {
                    "exists": False,
                    "available": False,
                    "error_message": None,
                    "total_bytes": 0,
                    "latest_run": None,
                    "runtime_health": {},
                }
            )
        )

        self.assertIn("Файл: не создан", text)

    def test_formats_archive_schema_error(self):
        text = format_operations_status(
            _minimal_snapshot(
                {
                    "exists": True,
                    "available": False,
                    "error_message": "missing_tables:archive_metadata",
                    "total_bytes": 4096,
                    "latest_run": None,
                    "runtime_health": {},
                }
            )
        )

        self.assertIn("Файл: ошибка", text)
        self.assertIn("Ошибка чтения: missing_tables", text)


if __name__ == "__main__":
    unittest.main()
