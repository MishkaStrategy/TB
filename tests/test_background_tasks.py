import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.background_tasks import BackgroundTaskRegistry


UTC = timezone.utc


class BackgroundTaskRegistryTests(unittest.TestCase):
    def test_successful_run_updates_state_and_history(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            claim = registry.try_begin(
                "funding-quarter-hour",
                owner_id="worker-1",
                lease_seconds=120,
                expected_interval_seconds=900,
                now=started,
            )

            self.assertTrue(claim["started"])
            self.assertTrue(
                registry.finish_success(
                    "funding-quarter-hour",
                    claim["run_id"],
                    owner_id="worker-1",
                    now=started + timedelta(seconds=7),
                )
            )

            state = registry.state("funding-quarter-hour")
            self.assertEqual(state["status"], "success")
            self.assertEqual(state["run_count"], 1)
            self.assertEqual(state["success_count"], 1)
            self.assertEqual(state["consecutive_failures"], 0)
            self.assertAlmostEqual(state["last_duration_seconds"], 7)
            run = registry.runs("funding-quarter-hour", limit=1)[0]
            self.assertEqual(run["status"], "success")
            self.assertAlmostEqual(run["duration_seconds"], 7)

    def test_overlap_creates_skipped_history_without_stealing_lease(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            first = registry.try_begin(
                "fvg-rest-recovery",
                owner_id="worker-1",
                lease_seconds=120,
                expected_interval_seconds=300,
                now=started,
            )
            second = registry.try_begin(
                "fvg-rest-recovery",
                owner_id="worker-2",
                lease_seconds=120,
                expected_interval_seconds=300,
                now=started + timedelta(seconds=1),
            )

            self.assertTrue(first["started"])
            self.assertFalse(second["started"])
            self.assertEqual(second["reason"], "overlap")
            self.assertEqual(second["active_run_id"], first["run_id"])
            state = registry.state("fvg-rest-recovery")
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["current_run_id"], first["run_id"])
            self.assertEqual(state["skipped_count"], 1)
            statuses = [item["status"] for item in registry.runs("fvg-rest-recovery")]
            self.assertEqual(statuses, ["skipped", "running"])

    def test_expired_lease_becomes_stale_and_allows_new_run(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            first = registry.try_begin(
                "fvg-delivery-outbox-retry",
                owner_id="crashed",
                lease_seconds=10,
                expected_interval_seconds=30,
                now=started,
            )

            recovered = registry.recover_stale(now=started + timedelta(seconds=11))
            second = registry.try_begin(
                "fvg-delivery-outbox-retry",
                owner_id="replacement",
                lease_seconds=10,
                expected_interval_seconds=30,
                now=started + timedelta(seconds=12),
            )

            self.assertEqual(recovered, 1)
            self.assertTrue(second["started"])
            self.assertNotEqual(second["run_id"], first["run_id"])
            state = registry.state("fvg-delivery-outbox-retry")
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["stale_count"], 1)
            self.assertEqual(state["failure_count"], 1)
            stale = next(
                item
                for item in registry.runs("fvg-delivery-outbox-retry")
                if item["run_id"] == first["run_id"]
            )
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["error_code"], "task_lease_expired")

    def test_heartbeat_requires_current_owner_and_extends_lease(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            claim = registry.try_begin(
                "fvg-operational-health",
                owner_id="worker-1",
                lease_seconds=10,
                expected_interval_seconds=60,
                now=started,
            )

            self.assertFalse(
                registry.heartbeat(
                    "fvg-operational-health",
                    claim["run_id"],
                    owner_id="worker-2",
                    lease_seconds=20,
                    now=started + timedelta(seconds=5),
                )
            )
            self.assertTrue(
                registry.heartbeat(
                    "fvg-operational-health",
                    claim["run_id"],
                    owner_id="worker-1",
                    lease_seconds=20,
                    now=started + timedelta(seconds=5),
                )
            )
            state = registry.state("fvg-operational-health")
            self.assertEqual(
                datetime.fromisoformat(state["lease_until"]),
                started + timedelta(seconds=25),
            )

    def test_failure_and_cancellation_have_distinct_counters(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            failed = registry.try_begin(
                "job",
                owner_id="worker",
                lease_seconds=60,
                now=started,
            )
            registry.finish_failure(
                "job",
                failed["run_id"],
                owner_id="worker",
                error=ValueError("broken"),
                error_code="unit_failure",
                now=started + timedelta(seconds=2),
            )
            cancelled = registry.try_begin(
                "job",
                owner_id="worker",
                lease_seconds=60,
                now=started + timedelta(seconds=3),
            )
            registry.finish_cancelled(
                "job",
                cancelled["run_id"],
                owner_id="worker",
                now=started + timedelta(seconds=4),
            )

            state = registry.state("job")
            self.assertEqual(state["status"], "cancelled")
            self.assertEqual(state["failure_count"], 1)
            self.assertEqual(state["cancelled_count"], 1)
            self.assertEqual(state["consecutive_failures"], 1)
            statuses = [item["status"] for item in registry.runs("job")]
            self.assertEqual(statuses, ["cancelled", "failed"])

    def test_overdue_and_bounded_run_retention(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            started = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
            registry.register(
                "never-started",
                expected_interval_seconds=10,
                now=started,
            )
            for index in range(2):
                claim = registry.try_begin(
                    "old-job",
                    owner_id="worker",
                    lease_seconds=60,
                    expected_interval_seconds=10,
                    now=started + timedelta(seconds=index * 2),
                )
                registry.finish_success(
                    "old-job",
                    claim["run_id"],
                    owner_id="worker",
                    now=started + timedelta(seconds=index * 2 + 1),
                )

            overdue = registry.overdue_tasks(
                stale_multiplier=3,
                now=started + timedelta(seconds=33),
            )
            deleted = registry.prune_runs(
                retention_days=1,
                batch_size=1,
                now=started + timedelta(days=3),
            )

            self.assertEqual(
                {item["task_name"] for item in overdue},
                {"never-started", "old-job"},
            )
            self.assertEqual(deleted, 1)
            self.assertEqual(len(registry.runs("old-job", limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
