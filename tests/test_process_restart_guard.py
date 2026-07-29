import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.process_restart_guard import ProcessRestartGuard


UTC = timezone.utc


class ProcessRestartGuardTests(unittest.TestCase):
    def test_limit_trips_one_persistent_cooldown_without_denied_row_spam(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            guard = ProcessRestartGuard(
                path,
                max_requests=2,
                window_seconds=60,
                cooldown_seconds=120,
            )
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

            first = guard.decide(
                reason="stale",
                silence_seconds=1000,
                restart_mode="sigterm",
                now=started,
            )
            second = guard.decide(
                reason="stale",
                silence_seconds=1001,
                restart_mode="sigterm",
                now=started + timedelta(seconds=1),
            )
            tripped = guard.decide(
                reason="stale",
                silence_seconds=1002,
                restart_mode="sigterm",
                now=started + timedelta(seconds=2),
            )
            cooldown = guard.decide(
                reason="stale",
                silence_seconds=1003,
                restart_mode="sigterm",
                now=started + timedelta(seconds=3),
            )

            self.assertTrue(first["allowed"])
            self.assertTrue(second["allowed"])
            self.assertFalse(tripped["allowed"])
            self.assertEqual(tripped["decision_reason"], "limit_reached")
            self.assertFalse(cooldown["allowed"])
            self.assertEqual(cooldown["decision_reason"], "cooldown")
            self.assertIsNone(cooldown["request_id"])
            self.assertEqual(len(guard.requests(limit=10)), 3)
            summary = guard.summary(now=started + timedelta(seconds=3))
            self.assertTrue(summary["blocked"])
            self.assertEqual(summary["trip_count"], 1)
            self.assertEqual(summary["requests_in_window"], 2)

    def test_cooldown_persists_across_instances_and_allows_after_expiry(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            first = ProcessRestartGuard(
                path,
                max_requests=1,
                window_seconds=30,
                cooldown_seconds=60,
            )
            self.assertTrue(
                first.decide(
                    reason="stale",
                    silence_seconds=1000,
                    restart_mode="exit",
                    now=started,
                )["allowed"]
            )
            self.assertFalse(
                first.decide(
                    reason="stale",
                    silence_seconds=1001,
                    restart_mode="exit",
                    now=started + timedelta(seconds=1),
                )["allowed"]
            )

            second = ProcessRestartGuard(
                path,
                max_requests=1,
                window_seconds=30,
                cooldown_seconds=60,
            )
            blocked = second.decide(
                reason="stale",
                silence_seconds=1002,
                restart_mode="exit",
                now=started + timedelta(seconds=10),
            )
            allowed = second.decide(
                reason="stale",
                silence_seconds=1062,
                restart_mode="exit",
                now=started + timedelta(seconds=62),
            )

            self.assertEqual(blocked["decision_reason"], "cooldown")
            self.assertTrue(allowed["allowed"])
            self.assertFalse(second.summary(now=started + timedelta(seconds=62))["blocked"])

    def test_callback_failure_is_persisted(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            guard = ProcessRestartGuard(path)
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            decision = guard.decide(
                reason="stale",
                silence_seconds=1000,
                restart_mode="sigterm",
                now=started,
            )

            self.assertTrue(
                guard.mark_failed(
                    decision["request_id"],
                    OSError("signal denied"),
                    now=started + timedelta(seconds=1),
                )
            )
            request = guard.requests(limit=1)[0]
            self.assertEqual(request["status"], "failed")
            self.assertEqual(request["error_class"], "OSError")
            self.assertEqual(request["error_message"], "signal denied")

    def test_history_retention_is_bounded_during_decision(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            guard = ProcessRestartGuard(
                path,
                max_requests=10,
                history_retention_days=1,
            )
            started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
            for index in range(3):
                guard.decide(
                    reason="old",
                    silence_seconds=1000,
                    restart_mode="exit",
                    now=started + timedelta(seconds=index),
                )
            guard.decide(
                reason="new",
                silence_seconds=1000,
                restart_mode="exit",
                now=started + timedelta(days=3),
            )

            requests = guard.requests(limit=10)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["reason"], "new")

    def test_atomic_decision_allows_only_one_concurrent_request(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.sqlite3"
            ProcessRestartGuard(
                path,
                max_requests=1,
                window_seconds=60,
                cooldown_seconds=60,
            )
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

            def decide(index):
                guard = ProcessRestartGuard(
                    path,
                    max_requests=1,
                    window_seconds=60,
                    cooldown_seconds=60,
                )
                return guard.decide(
                    reason=f"worker-{index}",
                    silence_seconds=1000,
                    restart_mode="exit",
                    now=now,
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(decide, range(2)))

            self.assertEqual(sum(1 for item in results if item["allowed"]), 1)
            self.assertEqual(
                sum(
                    1
                    for item in results
                    if item["decision_reason"] == "limit_reached"
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
