import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.fvg_history_archive import FvgHistoryArchive
from operations.fvg_archive_audit import audit_fvg_archive
from run_fvg_archive_audit import main, write_report


UTC = timezone.utc


def create_archive(path: Path) -> FvgHistoryArchive:
    archive = FvgHistoryArchive(path)
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC).isoformat()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO archived_fvg_events(
                event_id, event_type, symbol, timeframe, direction,
                detected_at, candle_c_close_time, payload_json, archived_at
            ) VALUES('event-1', 'CONFIRMED_FVG', 'BTCUSDT', '15m',
                     'BULLISH', ?, NULL, ?, ?)
            """,
            (now, json.dumps({"event_id": "event-1"}), now),
        )
        connection.execute(
            """
            INSERT INTO archived_fvg_deliveries(
                event_id, chat_id, delivered_at, archived_at
            ) VALUES('event-1', '123', ?, ?)
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO fvg_archive_runs(
                cutoff_at, archived_at, event_count,
                delivery_count, source_deleted_count
            ) VALUES (?, ?, 1, 1, 1)
            """,
            (now, now),
        )
    return archive


def create_runtime_health(path: Path, **values):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE health(key TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO health(key, value_json) VALUES (?, ?)",
            [
                (str(key), json.dumps(value, ensure_ascii=False))
                for key, value in values.items()
            ],
        )


class FvgArchiveAuditTests(unittest.TestCase):
    def test_healthy_archive_passes_structural_and_payload_checks(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            create_archive(path)

            result = audit_fvg_archive(path)

            self.assertTrue(result["passed"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["schema_version"], "1")
            self.assertEqual(result["quick_check"], "ok")
            self.assertEqual(
                result["counts"],
                {"events": 1, "deliveries": 1, "runs": 1},
            )
            self.assertEqual(result["payload_sampled"], 1)
            self.assertEqual(result["payload_errors"], 0)
            self.assertTrue(result["run_reconciliation"]["event_rows_match"])

    def test_missing_archive_fails_unless_explicitly_allowed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing.sqlite3"

            failed = audit_fvg_archive(path)
            allowed = audit_fvg_archive(path, allow_missing=True)

            self.assertFalse(failed["passed"])
            self.assertEqual(failed["errors"], ["archive_file_missing"])
            self.assertTrue(allowed["passed"])
            self.assertEqual(allowed["warnings"], ["archive_file_missing"])
            self.assertFalse(path.exists())

    def test_missing_schema_is_a_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")

            result = audit_fvg_archive(path)

            self.assertFalse(result["passed"])
            self.assertTrue(result["errors"][0].startswith("missing_tables:"))

    def test_payload_mismatch_is_a_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            create_archive(path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "UPDATE archived_fvg_events SET payload_json=? WHERE event_id='event-1'",
                    (json.dumps({"event_id": "different"}),),
                )

            result = audit_fvg_archive(path)

            self.assertFalse(result["passed"])
            self.assertEqual(result["payload_errors"], 1)
            self.assertIn("payload_integrity_failed", result["errors"])

    def test_orphan_delivery_is_a_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            create_archive(path)
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC).isoformat()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    """
                    INSERT INTO archived_fvg_deliveries(
                        event_id, chat_id, delivered_at, archived_at
                    ) VALUES('missing-event', '999', ?, ?)
                    """,
                    (now, now),
                )

            result = audit_fvg_archive(path)

            self.assertFalse(result["passed"])
            self.assertEqual(result["orphan_deliveries"], 1)
            self.assertIn("orphan_deliveries", result["errors"])

    def test_retry_inflated_run_totals_are_warning_not_corruption(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            create_archive(path)
            now = datetime(2026, 7, 29, 12, 1, tzinfo=UTC).isoformat()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    INSERT INTO fvg_archive_runs(
                        cutoff_at, archived_at, event_count,
                        delivery_count, source_deleted_count
                    ) VALUES (?, ?, 1, 1, 1)
                    """,
                    (now, now),
                )

            result = audit_fvg_archive(path)

            self.assertTrue(result["passed"])
            self.assertEqual(result["errors"], [])
            self.assertIn("event_run_total_mismatch", result["warnings"])
            self.assertIn("delivery_run_total_mismatch", result["warnings"])
            self.assertIn("source_delete_total_mismatch", result["warnings"])
            self.assertFalse(result["run_reconciliation"]["event_rows_match"])

    def test_runtime_counter_mismatch_and_last_error_are_warnings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "archive.sqlite3"
            runtime_path = root / "runtime.sqlite3"
            create_archive(archive_path)
            create_runtime_health(
                runtime_path,
                events_archived=99,
                deliveries_archived=88,
                last_archive_error="old failure",
            )

            result = audit_fvg_archive(
                archive_path,
                runtime_path=runtime_path,
            )

            self.assertTrue(result["passed"])
            self.assertTrue(result["runtime_health"]["available"])
            self.assertIn("runtime_event_counter_mismatch", result["warnings"])
            self.assertIn("runtime_delivery_counter_mismatch", result["warnings"])
            self.assertIn("runtime_last_archive_error_present", result["warnings"])

    def test_quick_check_can_be_skipped_explicitly(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive.sqlite3"
            create_archive(path)

            result = audit_fvg_archive(path, include_quick_check=False)

            self.assertTrue(result["passed"])
            self.assertIsNone(result["quick_check"])

    def test_cli_writes_atomic_json_and_returns_exit_code(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "archive.sqlite3"
            output_path = root / "reports" / "archive-audit.json"
            create_archive(archive_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--archive",
                        str(archive_path),
                        "--runtime",
                        str(root / "missing-runtime.sqlite3"),
                        "--skip-quick-check",
                        "--payload-sample-size",
                        "10",
                        "--output",
                        str(output_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.is_file())
            self.assertFalse(output_path.with_suffix(".json.tmp").exists())
            from_file = json.loads(output_path.read_text(encoding="utf-8"))
            from_stdout = json.loads(stdout.getvalue())
            self.assertEqual(from_file, from_stdout)
            self.assertTrue(from_file["passed"])
            self.assertIsNone(from_file["quick_check"])

    def test_write_report_replaces_existing_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text('{"old": true}', encoding="utf-8")

            write_report({"passed": True}, path)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"passed": True},
            )


if __name__ == "__main__":
    unittest.main()
