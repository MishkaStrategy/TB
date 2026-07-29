import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from alerts import scheduler, scheduler_multi
from operations.graceful_fvg_stream import GracefulBitunixFvgStream


class EventStore:
    def increment_health(self, key, amount=1):
        del key, amount

    def update_health(self, **values):
        del values


class Service:
    def __init__(self):
        self.event_store = EventStore()


class GracefulSchedulerCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        task = scheduler._FVG_TASK
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        scheduler._FVG_TASK = None
        scheduler._FVG_STREAM = None

    async def test_cancelled_stop_cleans_global_stream_and_task(self):
        stream = GracefulBitunixFvgStream(Service())
        drain_started = asyncio.Event()

        async def hanging_drain(*, timeout_seconds):
            del timeout_seconds
            drain_started.set()
            await asyncio.Event().wait()

        stream.drain = hanging_drain
        running_task = asyncio.create_task(asyncio.Event().wait())
        scheduler._FVG_STREAM = stream
        scheduler._FVG_TASK = running_task

        with patch.object(scheduler_multi, "GRACEFUL_SHUTDOWN_ENABLED", True):
            stop_task = asyncio.create_task(
                scheduler_multi.stop_fvg_stream(
                    SimpleNamespace(),
                    timeout_seconds=5,
                )
            )
            await drain_started.wait()
            stop_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await stop_task

        self.assertTrue(running_task.cancelled())
        self.assertIsNone(scheduler._FVG_TASK)
        self.assertIsNone(scheduler._FVG_STREAM)


if __name__ == "__main__":
    unittest.main()
