import unittest

import config


class GracefulShutdownConfigTests(unittest.TestCase):
    def test_lifecycle_and_graceful_shutdown_are_disabled_by_default(self):
        self.assertFalse(config.RUNTIME_LIFECYCLE_ENABLED)
        self.assertFalse(config.GRACEFUL_SHUTDOWN_ENABLED)
        self.assertEqual(config.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS, 25)
        self.assertEqual(config.RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS, 30)


if __name__ == "__main__":
    unittest.main()
