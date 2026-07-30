import json
import os
import subprocess
import sys
import unittest

import config


class GracefulShutdownConfigTests(unittest.TestCase):
    def test_lifecycle_and_graceful_shutdown_are_disabled_by_default(self):
        self.assertFalse(config.RUNTIME_LIFECYCLE_ENABLED)
        self.assertFalse(config.FVG_PROCESS_GRACEFUL_RESTART_ENABLED)
        self.assertFalse(config.GRACEFUL_SHUTDOWN_ENABLED)
        self.assertEqual(config.GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS, 25)
        self.assertEqual(config.RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS, 30)

    def test_graceful_restart_implies_bounded_shutdown(self):
        environment = {
            **os.environ,
            "FVG_PROCESS_GRACEFUL_RESTART_ENABLED": "true",
            "GRACEFUL_SHUTDOWN_ENABLED": "false",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json, config; "
                    "print(json.dumps(["
                    "config.FVG_PROCESS_GRACEFUL_RESTART_ENABLED, "
                    "config.GRACEFUL_SHUTDOWN_ENABLED]))"
                ),
            ],
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(json.loads(result.stdout), [True, True])


if __name__ == "__main__":
    unittest.main()
