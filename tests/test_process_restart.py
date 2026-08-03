import signal
import unittest
from unittest.mock import patch

from operations import process_restart


class ProcessRestartTests(unittest.TestCase):
    def setUp(self):
        process_restart._GRACEFUL_RESTART_REQUESTED.clear()

    def tearDown(self):
        process_restart._GRACEFUL_RESTART_REQUESTED.clear()

    def test_rollout_is_disabled_by_default(self):
        self.assertFalse(process_restart.FVG_PROCESS_GRACEFUL_RESTART_ENABLED)
        callback, mode = process_restart.default_restart_process()
        self.assertIs(callback, process_restart.os._exit)
        self.assertEqual(mode, "immediate_exit")

    def test_enabled_rollout_selects_sigterm(self):
        with patch.object(
            process_restart,
            "FVG_PROCESS_GRACEFUL_RESTART_ENABLED",
            True,
        ):
            callback, mode = process_restart.default_restart_process()

        self.assertIs(callback, process_restart.request_sigterm_restart)
        self.assertEqual(mode, "sigterm_then_failure_exit")

    def test_sigterm_request_targets_current_process_and_sets_marker(self):
        with (
            patch.object(process_restart.os, "getpid", return_value=4321),
            patch.object(process_restart.os, "kill") as kill,
        ):
            process_restart.request_sigterm_restart(1)

        kill.assert_called_once_with(4321, signal.SIGTERM)
        self.assertTrue(process_restart.graceful_restart_requested())

    def test_failed_sigterm_request_clears_marker(self):
        with (
            patch.object(process_restart.os, "getpid", return_value=4321),
            patch.object(
                process_restart.os,
                "kill",
                side_effect=OSError("signal denied"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "signal denied"):
                process_restart.request_sigterm_restart(1)

        self.assertFalse(process_restart.graceful_restart_requested())


if __name__ == "__main__":
    unittest.main()
