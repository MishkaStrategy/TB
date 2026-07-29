import unittest

from database import process_restart_guard_config as config


class ProcessRestartGuardConfigTests(unittest.TestCase):
    def test_guard_rollout_is_disabled_and_bounded_by_default(self):
        self.assertFalse(config.FVG_PROCESS_RESTART_GUARD_ENABLED)
        self.assertEqual(config.FVG_PROCESS_RESTART_MAX_REQUESTS, 3)
        self.assertEqual(config.FVG_PROCESS_RESTART_WINDOW_SECONDS, 3600)
        self.assertEqual(config.FVG_PROCESS_RESTART_COOLDOWN_SECONDS, 3600)
        self.assertEqual(config.FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS, 30)


if __name__ == "__main__":
    unittest.main()
