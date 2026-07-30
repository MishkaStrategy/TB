import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPOSITORY_ROOT / "scripts" / "update_vds_bot_api_only.sh"


class BotApiOnlyVdsUpdateTests(unittest.TestCase):
    def run_wrapper(self, env_text: str):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            env_file = directory / "bot.env"
            marker = directory / "updater-ran"
            updater = directory / "update-stub.sh"

            env_file.write_text(env_text, encoding="utf-8")
            updater.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'ok' > \"${UPDATE_MARKER}\"\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "ENV_FILE": str(env_file),
                    "UPDATER_SCRIPT": str(updater),
                    "UPDATE_MARKER": str(marker),
                }
            )
            result = subprocess.run(
                ["bash", str(WRAPPER)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            return result, marker.exists()

    def test_delegates_when_only_bot_token_is_configured(self):
        result, updater_ran = self.run_wrapper(
            "TELEGRAM_TOKEN=test-token\nADMIN_TELEGRAM_IDS=123456789\n"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(updater_ran)
        self.assertIn("Telegram mode: Bot API only", result.stdout)
        self.assertNotIn("test-token", result.stdout + result.stderr)

    def test_rejects_missing_bot_token(self):
        result, updater_ran = self.run_wrapper("ADMIN_TELEGRAM_IDS=123456789\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(updater_ran)
        self.assertIn("TELEGRAM_TOKEN", result.stderr)

    def test_rejects_telegram_app_credentials(self):
        result, updater_ran = self.run_wrapper(
            "TELEGRAM_TOKEN=test-token\nTELEGRAM_API_ID=12345\nTELEGRAM_API_HASH=secret\n"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(updater_ran)
        self.assertIn("TELEGRAM_API_ID", result.stderr)
        self.assertIn("TELEGRAM_API_HASH", result.stderr)
        self.assertNotIn("test-token", result.stdout + result.stderr)

    def test_accepts_exported_and_quoted_bot_token(self):
        result, updater_ran = self.run_wrapper(
            "export TELEGRAM_TOKEN='test-token'\n# TELEGRAM_API_ID=not-configured\n"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(updater_ran)


if __name__ == "__main__":
    unittest.main()
