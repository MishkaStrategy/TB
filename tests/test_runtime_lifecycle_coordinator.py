import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from database.runtime_lifecycle import RuntimeLifecycleStore
from operations.runtime_lifecycle import RuntimeLifecycleCoordinator


class Metrics:
    def __init__(self):
        self.values = {}
        self.counters = {}

    def update_health(self, **values):
        self.values.update(values)

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount


class RuntimeLifecycleCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_clean_graceful_stop_is_ordered_persistent_and_idempotent(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            metrics = Metrics()
            calls = []

            async def stop_watchdog(application):
                calls.append(("watchdog", application))

            async def stop_stream(application, *, timeout_seconds):
                calls.append(("stream", application, timeout_seconds))
                return {"drained": True, "timeout": False}

            async def drain_outbox(application, *, timeout_seconds):
                calls.append(("outbox", application, timeout_seconds))
                return {
                    "enabled": True,
                    "supported": True,
                    "completed": 3,
                    "timeout": False,
                }

            coordinator = RuntimeLifecycleCoordinator(
                store=store,
                stop_watchdog=stop_watchdog,
                stop_stream=stop_stream,
                drain_outbox=drain_outbox,
                graceful_enabled=True,
                timeout_seconds=5,
                metrics=metrics,
            )
            coordinator.begin_start(details={"release": "abc"})
            coordinator.mark_running()
            application = SimpleNamespace(bot=object())

            first = await coordinator.stop(application)
            second = await coordinator.stop(application)

            self.assertIs(first, second)
            self.assertEqual([call[0] for call in calls], ["watchdog", "stream", "outbox"])
            self.assertEqual(first["outbox"]["completed"], 3)
            self.assertFalse(first["timed_out"])
            self.assertEqual(store.current()["status"], "stopped")
            self.assertEqual(store.current()["shutdown_outcome"], "clean")
            self.assertEqual(metrics.values["runtime_status"], "stopped")

    async def test_lifecycle_only_stops_services_without_outbox_pass(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            outbox_calls = 0

            async def stop_watchdog(application):
                del application

            async def stop_stream(application, *, timeout_seconds):
                del application, timeout_seconds
                return {"graceful": False, "timeout": False}

            async def drain_outbox(application, *, timeout_seconds):
                nonlocal outbox_calls
                del application, timeout_seconds
                outbox_calls += 1

            coordinator = RuntimeLifecycleCoordinator(
                store=store,
                stop_watchdog=stop_watchdog,
                stop_stream=stop_stream,
                drain_outbox=drain_outbox,
                graceful_enabled=False,
                timeout_seconds=5,
            )
            coordinator.begin_start()
            coordinator.mark_running()

            result = await coordinator.stop(SimpleNamespace())

            self.assertEqual(outbox_calls, 0)
            self.assertFalse(result["outbox"]["enabled"])
            self.assertEqual(store.current()["shutdown_outcome"], "clean")

    async def test_stream_timeout_marks_shutdown_timeout_and_continues_outbox(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            outbox_calls = 0

            async def stop_watchdog(application):
                del application

            async def stop_stream(application, *, timeout_seconds):
                del application, timeout_seconds
                return {"drained": False, "timeout": True}

            async def drain_outbox(application, *, timeout_seconds):
                nonlocal outbox_calls
                del application, timeout_seconds
                outbox_calls += 1
                return {
                    "enabled": True,
                    "supported": True,
                    "completed": 1,
                    "timeout": False,
                }

            coordinator = RuntimeLifecycleCoordinator(
                store=store,
                stop_watchdog=stop_watchdog,
                stop_stream=stop_stream,
                drain_outbox=drain_outbox,
                graceful_enabled=True,
                timeout_seconds=5,
            )
            coordinator.begin_start()
            coordinator.mark_running()

            result = await coordinator.stop(SimpleNamespace())

            self.assertTrue(result["timed_out"])
            self.assertIn("fvg_stream", result["timeouts"])
            self.assertEqual(outbox_calls, 1)
            self.assertEqual(store.current()["status"], "shutdown_timeout")
            self.assertEqual(store.current()["shutdown_outcome"], "timeout")

    async def test_component_error_is_recorded_without_masking_other_cleanup(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            stream_calls = 0

            async def stop_watchdog(application):
                del application
                raise RuntimeError("watchdog broken")

            async def stop_stream(application, *, timeout_seconds):
                nonlocal stream_calls
                del application, timeout_seconds
                stream_calls += 1
                return {"drained": True, "timeout": False}

            async def drain_outbox(application, *, timeout_seconds):
                del application, timeout_seconds
                return {
                    "enabled": True,
                    "supported": True,
                    "completed": 0,
                    "timeout": False,
                }

            coordinator = RuntimeLifecycleCoordinator(
                store=store,
                stop_watchdog=stop_watchdog,
                stop_stream=stop_stream,
                drain_outbox=drain_outbox,
                graceful_enabled=True,
                timeout_seconds=5,
            )
            coordinator.begin_start()
            coordinator.mark_running()

            result = await coordinator.stop(SimpleNamespace())

            self.assertEqual(stream_calls, 1)
            self.assertEqual(result["errors"][0]["component"], "process_watchdog")
            self.assertEqual(store.current()["status"], "failed")
            self.assertEqual(store.current()["shutdown_outcome"], "component_error")

    async def test_application_error_preserves_stopping_state(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")
            metrics = Metrics()

            async def noop(*args, **kwargs):
                del args, kwargs

            coordinator = RuntimeLifecycleCoordinator(
                store=store,
                stop_watchdog=noop,
                stop_stream=noop,
                drain_outbox=noop,
                metrics=metrics,
            )
            coordinator.begin_start()
            coordinator.mark_running()
            store.transition(
                coordinator.instance_id,
                "stopping",
                phase="test",
            )

            coordinator.record_application_error(ValueError("handled"))

            state = store.current()
            self.assertEqual(state["status"], "stopping")
            self.assertEqual(state["last_error_class"], "ValueError")
            self.assertEqual(metrics.counters["application_errors"], 1)


if __name__ == "__main__":
    unittest.main()
