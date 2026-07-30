import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from alerts import scheduler_multi
from database.background_tasks import BackgroundTaskRegistry
from operations.task_runtime import TrackedTaskRunner


class FakeJobQueue:
    def __init__(self):
        self.jobs = {}
        self.calls = []

    def get_jobs_by_name(self, name):
        return tuple(self.jobs.get(name, ()))

    def run_repeating(self, callback, **kwargs):
        self.calls.append((callback, kwargs))
        job = SimpleNamespace(name=kwargs["name"], data=kwargs.get("data"))
        self.jobs.setdefault(kwargs["name"], []).append(job)
        return job


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def register(self, task_name, **kwargs):
        self.calls.append((task_name, kwargs))
        return {"task_name": task_name}


class TaskSchedulerBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_registry = scheduler_multi._BACKGROUND_TASK_REGISTRY
        self.original_runner = scheduler_multi._BACKGROUND_TASK_RUNNER
        self.original_watchdog = scheduler_multi._BACKGROUND_TASK_WATCHDOG

    async def asyncTearDown(self):
        scheduler_multi._BACKGROUND_TASK_REGISTRY = self.original_registry
        scheduler_multi._BACKGROUND_TASK_RUNNER = self.original_runner
        scheduler_multi._BACKGROUND_TASK_WATCHDOG = self.original_watchdog

    async def test_disabled_registry_calls_operation_directly(self):
        calls = 0

        async def operation():
            nonlocal calls
            calls += 1
            return "done"

        with (
            patch("alerts.scheduler_multi.BACKGROUND_TASK_REGISTRY_ENABLED", False),
            patch("alerts.scheduler_multi.BACKGROUND_TASK_WATCHDOG_ENABLED", False),
        ):
            result = await scheduler_multi._run_tracked("job", 60, operation)

        self.assertEqual(result, "done")
        self.assertEqual(calls, 1)

    async def test_overlap_does_not_execute_original_callback(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            registry.try_begin(
                "shared-job",
                owner_id="other-worker",
                lease_seconds=60,
                expected_interval_seconds=60,
            )
            scheduler_multi._BACKGROUND_TASK_REGISTRY = registry
            scheduler_multi._BACKGROUND_TASK_RUNNER = TrackedTaskRunner(
                registry,
                owner_id="current-worker",
            )
            calls = 0

            async def operation():
                nonlocal calls
                calls += 1

            with patch(
                "alerts.scheduler_multi.BACKGROUND_TASK_REGISTRY_ENABLED",
                True,
            ):
                result = await scheduler_multi._run_tracked(
                    "shared-job",
                    60,
                    operation,
                )

            self.assertIsNone(result)
            self.assertEqual(calls, 0)
            self.assertEqual(registry.state("shared-job")["skipped_count"], 1)

    def test_registers_expected_jobs_and_optional_observability(self):
        registry = FakeRegistry()
        scheduler_multi._BACKGROUND_TASK_REGISTRY = registry
        with (
            patch("alerts.scheduler_multi.BACKGROUND_TASK_REGISTRY_ENABLED", True),
            patch("alerts.scheduler_multi.DATABASE_OBSERVABILITY_ENABLED", True),
            patch(
                "alerts.scheduler_multi.DATABASE_OBSERVABILITY_INTERVAL_SECONDS",
                3600,
            ),
        ):
            result = scheduler_multi.register_background_tasks()

        names = {name for name, _ in registry.calls}
        self.assertEqual(len(result), 7)
        self.assertEqual(
            names,
            {
                "fvg-confirmed-control",
                "fvg-pre-control-t-minus-3",
                "fvg-delivery-outbox-retry",
                "fvg-rest-recovery",
                "fvg-operational-health",
                "funding-quarter-hour",
                "sqlite-observability",
            },
        )

    def test_watchdog_schedule_is_opt_in_and_idempotent(self):
        application = SimpleNamespace(job_queue=FakeJobQueue())
        sentinel = object()
        with (
            patch("alerts.scheduler_multi.BACKGROUND_TASK_WATCHDOG_ENABLED", True),
            patch(
                "alerts.scheduler_multi.BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS",
                60,
            ),
            patch(
                "alerts.scheduler_multi.get_background_task_watchdog",
                return_value=sentinel,
            ),
        ):
            first = scheduler_multi.schedule_background_task_watchdog(application)
            second = scheduler_multi.schedule_background_task_watchdog(application)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(application.job_queue.calls), 1)
        callback, kwargs = application.job_queue.calls[0]
        self.assertIs(callback, scheduler_multi.run_background_task_watchdog)
        self.assertEqual(kwargs["interval"], 60)
        self.assertEqual(kwargs["first"], 30)
        self.assertIs(kwargs["data"]["background_task_watchdog"], sentinel)


if __name__ == "__main__":
    unittest.main()
