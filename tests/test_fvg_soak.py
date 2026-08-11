import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from operations.fvg_soak import run_soak


class FvgSoakTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_pipeline_soak_drains_outbox(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "soak.sqlite3"
            report = await run_soak(
                database,
                events=20,
                recipients=3,
                batch_size=7,
                # This unit test verifies correctness, not host performance.
                # CI enforces the production timing threshold in a separate
                # bounded 500x10 soak run.
                max_peak_memory_mb=64,
            )
            self.assertTrue(report.passed, report.failures)
            self.assertEqual(report.events_persisted, 20)
            self.assertEqual(report.deliveries_persisted, 60)
            self.assertEqual(report.bot_messages, 60)
            self.assertEqual(report.outbox_remaining, 0)
            self.assertGreater(report.deliveries_per_second, 0)
            self.assertGreater(report.database_bytes, 0)

    async def test_refuses_to_reuse_database_without_reset(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "soak.sqlite3"
            first = await run_soak(database, events=2, recipients=1)
            self.assertTrue(first.passed)
            with self.assertRaises(FileExistsError):
                await run_soak(database, events=2, recipients=1)

            second = await run_soak(
                database,
                events=3,
                recipients=2,
                reset=True,
            )
            self.assertTrue(second.passed)
            self.assertEqual(second.deliveries_persisted, 6)

    async def test_threshold_failure_is_reported_not_hidden(self):
        with TemporaryDirectory() as directory:
            report = await run_soak(
                Path(directory) / "soak.sqlite3",
                events=2,
                recipients=1,
                max_seconds=0,
            )
            self.assertFalse(report.passed)
            self.assertTrue(any("duration" in item for item in report.failures))

    async def test_wall_clock_limit_cancels_slow_delivery(self):
        async def slow_deliver(*args, **kwargs):
            await asyncio.sleep(10)

        with TemporaryDirectory() as directory:
            started = time.perf_counter()
            with patch(
                "operations.fvg_soak.FvgAlertService.deliver",
                new=slow_deliver,
            ):
                report = await run_soak(
                    Path(directory) / "soak.sqlite3",
                    events=2,
                    recipients=1,
                    batch_size=1,
                    max_seconds=0.05,
                )
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, 1.0)
            self.assertFalse(report.passed)
            self.assertTrue(
                any("reached limit" in item for item in report.failures),
                report.failures,
            )


if __name__ == "__main__":
    unittest.main()
