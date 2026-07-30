import unittest
from types import SimpleNamespace
from unittest.mock import patch

from alerts.scheduler_multi import (
    run_database_observability,
    schedule_database_observability,
)


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


class FakeService:
    def __init__(self):
        self.calls = 0

    def capture(self):
        self.calls += 1
        return {"snapshots": []}


class SQLiteObservabilitySchedulerTests(unittest.IsolatedAsyncioTestCase):
    def test_disabled_flag_does_not_register_job(self):
        application = SimpleNamespace(job_queue=FakeJobQueue())
        with patch("alerts.scheduler_multi.DATABASE_OBSERVABILITY_ENABLED", False):
            self.assertIsNone(schedule_database_observability(application))
        self.assertEqual(application.job_queue.calls, [])

    def test_enabled_flag_registers_once_with_configured_interval(self):
        application = SimpleNamespace(job_queue=FakeJobQueue())
        service = FakeService()
        with (
            patch("alerts.scheduler_multi.DATABASE_OBSERVABILITY_ENABLED", True),
            patch(
                "alerts.scheduler_multi.DATABASE_OBSERVABILITY_INTERVAL_SECONDS",
                3600,
            ),
            patch(
                "alerts.scheduler_multi.get_database_observability_service",
                return_value=service,
            ),
        ):
            first = schedule_database_observability(application)
            second = schedule_database_observability(application)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(application.job_queue.calls), 1)
        callback, kwargs = application.job_queue.calls[0]
        self.assertIs(callback, run_database_observability)
        self.assertEqual(kwargs["interval"], 3600)
        self.assertEqual(kwargs["first"], 60)
        self.assertEqual(kwargs["name"], "sqlite-observability")
        self.assertIs(kwargs["data"]["database_observability_service"], service)

    async def test_job_runs_capture_off_event_loop(self):
        service = FakeService()
        context = SimpleNamespace(
            job=SimpleNamespace(
                data={"database_observability_service": service}
            )
        )

        await run_database_observability(context)

        self.assertEqual(service.calls, 1)


if __name__ == "__main__":
    unittest.main()
