import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database.background_tasks import BackgroundTaskRegistry
from operations.task_runtime import TaskLeaseLost, TrackedTaskRunner


class LeaseLosingRegistry(BackgroundTaskRegistry):
    def heartbeat(self, *args, **kwargs):
        return False


class TrackedTaskRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_result_and_finalizes_run(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            runner = TrackedTaskRunner(
                registry,
                owner_id="worker-1",
                heartbeat_interval_seconds=0.01,
            )

            async def operation():
                await asyncio.sleep(0)
                return {"ok": True}

            result = await runner.run(
                "successful-job",
                operation,
                lease_seconds=10,
                expected_interval_seconds=60,
            )

            self.assertTrue(result.started)
            self.assertEqual(result.result, {"ok": True})
            self.assertEqual(registry.state("successful-job")["status"], "success")

    async def test_uncaught_failure_is_recorded_and_re_raised(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            runner = TrackedTaskRunner(registry, owner_id="worker-1")

            async def operation():
                raise ValueError("broken")

            with self.assertRaisesRegex(ValueError, "broken"):
                await runner.run(
                    "failed-job",
                    operation,
                    lease_seconds=10,
                )

            state = registry.state("failed-job")
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["last_error_class"], "ValueError")
            self.assertEqual(state["last_error_code"], "uncaught_task_exception")

    async def test_cancellation_is_not_counted_as_failure(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            runner = TrackedTaskRunner(registry, owner_id="worker-1")
            started = asyncio.Event()

            async def operation():
                started.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(
                runner.run(
                    "cancelled-job",
                    operation,
                    lease_seconds=10,
                )
            )
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            state = registry.state("cancelled-job")
            self.assertEqual(state["status"], "cancelled")
            self.assertEqual(state["cancelled_count"], 1)
            self.assertEqual(state["failure_count"], 0)

    async def test_overlap_returns_without_running_operation(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            registry.try_begin(
                "shared-job",
                owner_id="other-worker",
                lease_seconds=60,
            )
            runner = TrackedTaskRunner(registry, owner_id="worker-1")
            calls = 0

            async def operation():
                nonlocal calls
                calls += 1

            result = await runner.run(
                "shared-job",
                operation,
                lease_seconds=60,
            )

            self.assertFalse(result.started)
            self.assertEqual(result.skip_reason, "overlap")
            self.assertEqual(calls, 0)

    async def test_heartbeat_extends_short_lease_during_long_operation(self):
        with TemporaryDirectory() as directory:
            registry = BackgroundTaskRegistry(Path(directory) / "tasks.sqlite3")
            runner = TrackedTaskRunner(
                registry,
                owner_id="worker-1",
                heartbeat_interval_seconds=0.02,
            )
            observed = []

            async def operation():
                await asyncio.sleep(0.06)
                observed.append(registry.state("heartbeat-job"))

            result = await runner.run(
                "heartbeat-job",
                operation,
                lease_seconds=0.03,
            )

            self.assertTrue(result.started)
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0]["status"], "running")
            self.assertIsNotNone(observed[0]["heartbeat_at"])

    async def test_lost_lease_cancels_operation_and_records_failure(self):
        with TemporaryDirectory() as directory:
            registry = LeaseLosingRegistry(Path(directory) / "tasks.sqlite3")
            runner = TrackedTaskRunner(
                registry,
                owner_id="worker-1",
                heartbeat_interval_seconds=0.01,
            )
            started = asyncio.Event()
            cancelled = asyncio.Event()

            async def operation():
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

            with self.assertRaises(TaskLeaseLost):
                await runner.run(
                    "lease-loss-job",
                    operation,
                    lease_seconds=1,
                )

            self.assertTrue(started.is_set())
            self.assertTrue(cancelled.is_set())
            state = registry.state("lease-loss-job")
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["last_error_code"], "task_lease_lost")


if __name__ == "__main__":
    unittest.main()
