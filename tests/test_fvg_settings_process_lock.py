import multiprocessing
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.fvg_store import FvgAlertSettings


def _pause_then_disable_module(path, entered, release):
    settings = FvgAlertSettings(path)

    def mutate(data):
        user = data["users"]["42"]
        entered.set()
        if not release.wait(5):
            raise RuntimeError("timed out waiting to release first transaction")
        user["enabled"] = False

    settings._transaction(mutate)


def _disable_instrument(path, ready, entered):
    settings = FvgAlertSettings(path)
    ready.set()

    def mutate(data):
        entered.set()
        data["users"]["42"]["symbols"]["BTCUSDT"]["enabled"] = False

    settings._transaction(mutate)


@unittest.skipUnless(os.name == "posix", "cross-process flock is used on Unix")
class FvgSettingsProcessLockTests(unittest.TestCase):
    def test_concurrent_processes_do_not_overwrite_disabled_state(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "settings.json")
            settings = FvgAlertSettings(path)
            settings.add_symbol(42, "BTCUSDT")
            settings.set_enabled(42, True)

            context = multiprocessing.get_context("spawn")
            first_entered = context.Event()
            release_first = context.Event()
            second_ready = context.Event()
            second_entered = context.Event()

            first = context.Process(
                target=_pause_then_disable_module,
                args=(path, first_entered, release_first),
            )
            second = context.Process(
                target=_disable_instrument,
                args=(path, second_ready, second_entered),
            )

            first.start()
            self.assertTrue(first_entered.wait(5))
            second.start()
            self.assertTrue(second_ready.wait(5))

            # The second process is alive and ready, but it must not enter the
            # read-modify-write transaction until the first process releases
            # the file lock. Without the process lock both writers read the
            # same stale JSON and one disabled state is lost.
            self.assertFalse(second_entered.wait(0.5))
            release_first.set()

            first.join(5)
            second.join(5)
            if first.is_alive():
                first.terminate()
                first.join()
                self.fail("first settings process did not exit")
            if second.is_alive():
                second.terminate()
                second.join()
                self.fail("second settings process did not exit")

            self.assertEqual(first.exitcode, 0)
            self.assertEqual(second.exitcode, 0)
            self.assertTrue(second_entered.is_set())

            saved = FvgAlertSettings(path).user(42)
            self.assertFalse(saved["enabled"])
            self.assertFalse(saved["symbols"]["BTCUSDT"]["enabled"])


if __name__ == "__main__":
    unittest.main()
