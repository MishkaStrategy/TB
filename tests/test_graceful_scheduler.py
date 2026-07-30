import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        self.retry_calls = []

    async def retry_pending(self, bot, *, limit):
        self.retry_calls.append((bot, limit))
        return 4


class GracefulSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_stream = scheduler._FVG_STREAM
        self.original_task = scheduler._FVG_TASK

    async def asyncTearDown(self):
        task = scheduler._FVG_TASK
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        scheduler._FVG_STREAM = self.original_stream
        scheduler._FVG_TASK = self.original_task

    def test_schedule_bridge_keeps_funding_and_fvg_factories_distinct(self):
        application = SimpleNamespace()
        with (
            patch.object(scheduler, "schedule_fvg_alerts", return_value="scheduled"),
            patch.object(scheduler_multi, "register_background_tasks"),
            patch.object(scheduler_multi, "schedule_database_observability"),
            patch.object(scheduler_multi, "schedule_background_task_watchdog"),
        ):
            result = scheduler_multi.schedule_fvg_alerts(application)

        self.assertEqual(result, "scheduled")
        self.assertIs(scheduler.get_funding_service, scheduler_multi.get_funding_service)
        self.assertIs(scheduler.get_fvg_service, scheduler_multi.get_fvg_service)

    async def test_disabled_graceful_mode_uses_legacy_stop(self):
        application = SimpleNamespace()
        legacy_stop = AsyncMock()
        with (
            patch.object(scheduler_multi, "GRACEFUL_SHUTDOWN_ENABLED", False),
            patch.object(scheduler, "stop_fvg_stream", legacy_stop),
        ):
            result = await scheduler_multi.stop_fvg_stream(
                application,
                timeout_seconds=1,
            )

        legacy_stop.assert_awaited_once_with(application)
        self.assertFalse(result["graceful"])
        self.assertFalse(result["timeout"])

    async def test_graceful_stop_cancels_task_when_drain_budget_expires(self):
        service = Service()
        stream = GracefulBitunixFvgStream(service)
        stop_called = False

        def stop_accepting():
            nonlocal stop_called
            stop_called = True

        async def drain(*, timeout_seconds):
            del timeout_seconds
            return {
                "drained": False,
                "pending_before": 2,
                "pending_after": 2,
                "timeout": True,
            }

        stream.stop_accepting = stop_accepting
        stream.drain = drain
        scheduler._FVG_STREAM = stream
        scheduler._FVG_TASK = asyncio.create_task(asyncio.Event().wait())

        with patch.object(scheduler_multi, "GRACEFUL_SHUTDOWN_ENABLED", True):
            result = await scheduler_multi.stop_fvg_stream(
                SimpleNamespace(),
                timeout_seconds=0.1,
            )

        self.assertTrue(stop_called)
        self.assertTrue(result["task_cancelled"])
        self.assertTrue(result["timeout"])
        self.assertIsNone(scheduler._FVG_STREAM)
        self.assertIsNone(scheduler._FVG_TASK)

    async def test_final_outbox_pass_reports_completed_count(self):
        service = Service()
        bot = object()
        with patch.object(scheduler_multi, "get_fvg_service", return_value=service):
            result = await scheduler_multi.drain_fvg_outbox(
                SimpleNamespace(bot=bot),
                timeout_seconds=1,
            )

        self.assertEqual(service.retry_calls, [(bot, 1000)])
        self.assertTrue(result["enabled"])
        self.assertTrue(result["supported"])
        self.assertEqual(result["completed"], 4)
        self.assertFalse(result["timeout"])

    async def test_final_outbox_pass_is_bounded(self):
        class SlowService(Service):
            async def retry_pending(self, bot, *, limit):
                del bot, limit
                await asyncio.Event().wait()

        with patch.object(
            scheduler_multi,
            "get_fvg_service",
            return_value=SlowService(),
        ):
            result = await scheduler_multi.drain_fvg_outbox(
                SimpleNamespace(bot=object()),
                timeout_seconds=0.01,
            )

        self.assertTrue(result["supported"])
        self.assertTrue(result["timeout"])
        self.assertEqual(result["completed"], 0)


if __name__ == "__main__":
    unittest.main()
