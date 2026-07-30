import unittest

import config


class BackgroundTaskConfigTests(unittest.TestCase):
    def test_registry_and_watchdog_are_disabled_by_default(self):
        self.assertFalse(config.BACKGROUND_TASK_REGISTRY_ENABLED)
        self.assertFalse(config.BACKGROUND_TASK_WATCHDOG_ENABLED)
        self.assertEqual(config.BACKGROUND_TASK_HISTORY_RETENTION_DAYS, 30)
        self.assertEqual(config.BACKGROUND_TASK_HEARTBEAT_SECONDS, 30)
        self.assertEqual(config.BACKGROUND_TASK_MIN_LEASE_SECONDS, 120)
        self.assertEqual(config.BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS, 60)
        self.assertEqual(config.BACKGROUND_TASK_STALE_MULTIPLIER, 3)


if __name__ == "__main__":
    unittest.main()
