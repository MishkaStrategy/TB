import asyncio
import unittest
from types import SimpleNamespace

from operations.graceful_fvg_stream import GracefulBitunixFvgStream


class FakeEventStore:
    def __init__(self):
        self.counters = {}
        self.health = {}

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount

    def update_health(self, **values):
        self.health.update(values)


class FakeService:
    def __init__(self, *, fail=False):
        self.event_store = FakeEventStore()
        self.delivered = []
        self.fail = fail

    async def deliver(self, bot, events):
        del bot
        if self.fail:
            raise RuntimeError("delivery failed")
        self.delivered.extend(event.event_id for event in events)


class GracefulFvgStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_accepting_rejects_new_events_and_records_metric(self):
        service = FakeService()
        stream = GracefulBitunixFvgStream(service)
        stream.stop_accepting()

        stream._enqueue([
            SimpleNamespace(event_id="one"),
            SimpleNamespace(event_id="two"),
        ])

        self.assertFalse(stream.accepting_events)
        self.assertEqual(stream.pending_delivery_count, 0)
        self.assertEqual(
            service.event_store.counters["delivery_events_rejected_during_shutdown"],
            2,
        )

    async def test_worker_drains_all_events_accepted_before_shutdown(self):
        service = FakeService()
        stream = GracefulBitunixFvgStream(service)
        stream._enqueue([
            SimpleNamespace(event_id="one"),
            SimpleNamespace(event_id="two"),
        ])
        stream.stop_accepting()
        worker = asyncio.create_task(stream._deliver_until_drained(object()))

        result = await stream.drain(timeout_seconds=1)
        await worker

        self.assertTrue(result["drained"])
        self.assertFalse(result["timeout"])
        self.assertEqual(result["pending_after"], 0)
        self.assertEqual(service.delivered, ["one", "two"])

    async def test_delivery_error_releases_queue_join_and_is_recorded(self):
        service = FakeService(fail=True)
        stream = GracefulBitunixFvgStream(service)
        stream._enqueue([SimpleNamespace(event_id="one")])
        stream.stop_accepting()
        worker = asyncio.create_task(stream._deliver_until_drained(object()))

        result = await stream.drain(timeout_seconds=1)
        await worker

        self.assertTrue(result["drained"])
        self.assertEqual(
            service.event_store.counters["delivery_worker_failures"],
            1,
        )
        self.assertEqual(service.event_store.health["last_error"], "delivery failed")

    async def test_graceful_run_exits_after_market_stop_and_queue_drain(self):
        service = FakeService()
        stream = GracefulBitunixFvgStream(service)

        async def fake_market():
            while not stream._stopping:
                await asyncio.sleep(0.01)

        stream._run_market = fake_market
        task = asyncio.create_task(stream.run(object()))
        await asyncio.sleep(0)
        stream._enqueue([SimpleNamespace(event_id="one")])
        stream.stop_accepting()

        result = await stream.drain(timeout_seconds=1)
        await asyncio.wait_for(task, timeout=1)

        self.assertTrue(result["drained"])
        self.assertEqual(service.delivered, ["one"])
        self.assertIsNone(stream._delivery_worker_task)

    async def test_forced_outer_cancellation_cancels_delivery_worker(self):
        service = FakeService()
        stream = GracefulBitunixFvgStream(service)
        market_started = asyncio.Event()

        async def fake_market():
            market_started.set()
            await asyncio.Event().wait()

        stream._run_market = fake_market
        task = asyncio.create_task(stream.run(object()))
        await market_started.wait()
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNone(stream._delivery_worker_task)


if __name__ == "__main__":
    unittest.main()
