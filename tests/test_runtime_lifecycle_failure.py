import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from database.runtime_lifecycle import RuntimeLifecycleStore
from operations.runtime_lifecycle import RuntimeLifecycleCoordinator


class RuntimeLifecycleFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_failure_is_not_reclassified_as_clean_stop(self):
        with TemporaryDirectory() as directory:
            store = RuntimeLifecycleStore(Path(directory) / "runtime.sqlite3")

            async def stop_watchdog(application):
                del application

            async def stop_stream(application, *, timeout_seconds):
                del application, timeout_seconds
                return {"timeout": False}

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
            coordinator.mark_startup_failed(RuntimeError("startup failed"))

            result = await coordinator.stop(SimpleNamespace())

            self.assertTrue(result["prior_failure"])
            self.assertEqual(result["prior_outcome"], "startup_failed")
            self.assertEqual(store.current()["status"], "failed")
            self.assertEqual(store.current()["shutdown_outcome"], "startup_failed")
            self.assertEqual(store.current()["last_error_class"], "RuntimeError")
            self.assertEqual(store.current()["last_error_message"], "startup failed")


if __name__ == "__main__":
    unittest.main()
