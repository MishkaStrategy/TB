import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from database.background_tasks import BackgroundTaskRegistry
from operations.task_watchdog import BackgroundTaskWatchdog


UTC = timezone.utc


class Metrics:
    def __init__(self):
        self.values = {}
        self.counters = {}

    def update_health(self, **values):
        self.values.update(values)

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class BackgroundTaskWatchdogTests(unittest.TestCase):
    def test_overdue_task_marks_health_degraded_without_restart(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            metrics = Metrics()
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            registry.register(
                "funding-quarter-hour",
                expected_interval_seconds=10,
                now=started,
            )
            watchdog = BackgroundTaskWatchdog(
                registry,
                metrics=metrics,
                stale_multiplier=3,
                history_retention_days=30,
            )

            result = watchdog.evaluate_once(now=started + timedelta(seconds=31))

            self.assertTrue(result["degraded"])
            self.assertEqual(result["overdue_count"], 1)
            self.assertEqual(result["stale_count"], 0)
            self.assertEqual(
                result["overdue_tasks"][0]["task_name"],
                "funding-quarter-hour",
            )
            self.assertTrue(metrics.values["background_tasks_degraded"])
            self.assertEqual(metrics.values["background_tasks_overdue_count"], 1)
            self.assertEqual(
                metrics.values["background_tasks_overdue_names"],
                ["funding-quarter-hour"],
            )
            self.assertEqual(metrics.values["background_tasks_stale_count"], 0)

    def test_expired_running_task_is_recovered_and_immediately_degraded(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            metrics = Metrics()
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            registry.try_begin(
                "fvg-rest-recovery",
                owner_id="crashed",
                lease_seconds=10,
                expected_interval_seconds=300,
                now=started,
            )
            watchdog = BackgroundTaskWatchdog(registry, metrics=metrics)

            result = watchdog.evaluate_once(now=started + timedelta(seconds=11))

            self.assertTrue(result["degraded"])
            self.assertEqual(result["stale_recovered"], 1)
            self.assertEqual(result["stale_count"], 1)
            self.assertEqual(result["overdue_count"], 0)
            self.assertEqual(
                result["stale_tasks"][0]["task_name"],
                "fvg-rest-recovery",
            )
            self.assertEqual(registry.state("fvg-rest-recovery")["status"], "stale")
            self.assertEqual(metrics.counters["background_task_stale_recoveries"], 1)
            self.assertEqual(metrics.values["background_tasks_stale_count"], 1)
            self.assertEqual(
                metrics.values["background_tasks_stale_names"],
                ["fvg-rest-recovery"],
            )

    def test_healthy_recent_task_clears_degraded_health(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            metrics = Metrics()
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            claim = registry.try_begin(
                "job",
                owner_id="worker",
                lease_seconds=60,
                expected_interval_seconds=60,
                now=started,
            )
            registry.finish_success(
                "job",
                claim["run_id"],
                owner_id="worker",
                now=started + timedelta(seconds=1),
            )
            watchdog = BackgroundTaskWatchdog(registry, metrics=metrics)

            result = watchdog.evaluate_once(now=started + timedelta(seconds=30))

            self.assertFalse(result["degraded"])
            self.assertEqual(result["overdue_count"], 0)
            self.assertEqual(result["stale_count"], 0)
            self.assertFalse(metrics.values["background_tasks_degraded"])


if __name__ == "__main__":
    unittest.main()
