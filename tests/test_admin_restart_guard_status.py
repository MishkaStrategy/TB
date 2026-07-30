import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.operations_status import OperationsStatusReader
from database.process_restart_guard import ProcessRestartGuard
from handlers.admin_settings import format_operations_status


UTC = timezone.utc


def minimal_snapshot(restart_guard: dict) -> dict:
    return {
        "available": True,
        "captured_at": "2026-07-30T00:00:00+00:00",
        "lifecycle": {"available": False, "state": None},
        "restart_guard": restart_guard,
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


class RestartGuardOperationsReaderTests(unittest.TestCase):
    def test_missing_guard_tables_remain_missing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE existing(id INTEGER PRIMARY KEY)")

            result = OperationsStatusReader(path).snapshot()

            self.assertTrue(result["available"])
            self.assertFalse(result["restart_guard"]["available"])
            with sqlite3.connect(path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_schema WHERE type='table'"
                    )
                }
            self.assertEqual(tables, {"existing"})

    def test_reads_active_cooldown_quota_and_latest_blocked_request(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            now = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
            guard = ProcessRestartGuard(
                path,
                max_requests=3,
                window_seconds=3600,
                cooldown_seconds=1800,
            )
            for offset in (40, 30, 20):
                decision = guard.decide(
                    reason="stale candles",
                    silence_seconds=1000,
                    restart_mode="sigterm_then_failure_exit",
                    now=now - timedelta(seconds=offset),
                )
                self.assertTrue(decision["allowed"])
            blocked = guard.decide(
                reason="stale candles",
                silence_seconds=1010,
                restart_mode="sigterm_then_failure_exit",
                now=now - timedelta(seconds=10),
            )
            self.assertFalse(blocked["allowed"])

            result = OperationsStatusReader(path).snapshot(now=now)
            status = result["restart_guard"]

            self.assertTrue(status["available"])
            self.assertTrue(status["blocked"])
            self.assertEqual(status["requests_in_window"], 3)
            self.assertEqual(status["max_requests"], 3)
            self.assertEqual(status["trip_count"], 1)
            self.assertEqual(status["latest_request"]["status"], "blocked")
            self.assertEqual(
                status["latest_request"]["decision_reason"],
                "limit_reached",
            )
            self.assertEqual(len(status["recent_requests"]), 4)

    def test_reads_latest_failed_restart_request(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            now = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
            guard = ProcessRestartGuard(path)
            decision = guard.decide(
                reason="stale candles",
                silence_seconds=1000,
                restart_mode="sigterm_then_failure_exit",
                now=now - timedelta(seconds=5),
            )
            guard.mark_failed(
                decision["request_id"],
                OSError("signal failed"),
                now=now - timedelta(seconds=4),
            )

            status = OperationsStatusReader(path).snapshot(now=now)["restart_guard"]

            self.assertFalse(status["blocked"])
            self.assertEqual(status["latest_request"]["status"], "failed")
            self.assertEqual(status["latest_request"]["error_class"], "OSError")
            self.assertEqual(status["latest_request"]["error_message"], "signal failed")


class RestartGuardAdminFormatTests(unittest.TestCase):
    def test_formats_active_cooldown_and_latest_block(self):
        text = format_operations_status(
            minimal_snapshot(
                {
                    "available": True,
                    "blocked": True,
                    "blocked_until": "2026-07-30T00:30:00+00:00",
                    "trip_count": 2,
                    "requests_in_window": 3,
                    "max_requests": 3,
                    "window_seconds": 3600,
                    "cooldown_seconds": 1800,
                    "latest_request": {
                        "status": "blocked",
                        "decision_reason": "limit_reached",
                        "requested_at": "2026-07-29T23:59:50+00:00",
                        "reason": "stale candles",
                        "error_class": None,
                        "error_message": None,
                    },
                }
            )
        )

        self.assertIn("Защита перезапуска", text)
        self.assertIn("Статус: заблокирован", text)
        self.assertIn("Окно: 3/3 за 1 ч", text)
        self.assertIn("Срабатываний: 2", text)
        self.assertIn("Cooldown до:", text)
        self.assertIn("заблокирован · достигнут лимит", text)
        self.assertIn("Причина: stale candles", text)
        self.assertNotIn("Сбросить", text)
        self.assertLess(len(text), 4096)

    def test_formats_latest_failure_and_truncates_long_error(self):
        long_error = "signal failed " * 100
        text = format_operations_status(
            minimal_snapshot(
                {
                    "available": True,
                    "blocked": False,
                    "blocked_until": None,
                    "trip_count": 0,
                    "requests_in_window": 1,
                    "max_requests": 3,
                    "window_seconds": 3600,
                    "cooldown_seconds": 3600,
                    "latest_request": {
                        "status": "failed",
                        "decision_reason": "allowed",
                        "requested_at": "2026-07-29T23:59:50+00:00",
                        "reason": "stale candles",
                        "error_class": "OSError",
                        "error_message": long_error,
                    },
                }
            )
        )

        self.assertIn("Статус: разрешён", text)
        self.assertIn("ошибка · разрешён", text)
        self.assertIn("Ошибка: OSError: signal failed", text)
        self.assertIn("…", text)
        self.assertLess(len(text), 4096)

    def test_formats_missing_guard_tables(self):
        text = format_operations_status(
            minimal_snapshot(
                {
                    "available": False,
                    "blocked": False,
                    "latest_request": None,
                }
            )
        )

        self.assertIn("circuit breaker: нет данных", text)


if __name__ == "__main__":
    unittest.main()
