import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from alerts.fvg_store import FvgAlertSettings, instrument_key


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "run_candidate_tests.sh"
INSTALLER = ROOT / "scripts" / "install_vds.sh"


class CandidateTestIsolationTests(unittest.TestCase):
    def _candidate(self, directory: str, exit_code: int) -> Path:
        candidate = Path(directory) / "candidate"
        python = candidate / ".venv" / "bin" / "python"
        (candidate / "tests").mkdir(parents=True)
        (candidate / "tmp" / "mpl").mkdir(parents=True)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text(
            "#!/usr/bin/env bash\n"
            'printf "MAX_SYMBOLS_PER_USER=%s\\n" "${MAX_SYMBOLS_PER_USER-<missing>}"\n'
            'printf "OUTBOX_RETRY_POLICY_ENABLED=%s\\n" "${OUTBOX_RETRY_POLICY_ENABLED-<missing>}"\n'
            'printf "FVG_HISTORY_ARCHIVE_ENABLED=%s\\n" "${FVG_HISTORY_ARCHIVE_ENABLED-<missing>}"\n'
            'printf "TELEGRAM_TOKEN=%s\\n" "${TELEGRAM_TOKEN-<missing>}"\n'
            'printf "ADMIN_TELEGRAM_IDS=%s\\n" "${ADMIN_TELEGRAM_IDS-<missing>}"\n'
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        return candidate

    def _run_helper(self, exit_code: int):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        candidate = self._candidate(temporary.name, exit_code)
        log = Path(temporary.name) / "candidate.log"
        environment = os.environ.copy()
        environment.update(
            {
                "MAX_SYMBOLS_PER_USER": "20",
                "OUTBOX_RETRY_POLICY_ENABLED": "true",
                "FVG_HISTORY_ARCHIVE_ENABLED": "true",
                "TELEGRAM_TOKEN": "production-secret-must-not-leak",
                "ADMIN_TELEGRAM_IDS": "987654321",
            }
        )
        result = subprocess.run(
            [
                "bash",
                str(HELPER),
                str(candidate),
                str(log),
                os.environ.get("USER", ""),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, log

    def test_helper_uses_allowlisted_environment(self):
        result, log = self._run_helper(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = log.read_text(encoding="utf-8")
        self.assertIn("MAX_SYMBOLS_PER_USER=10", text)
        self.assertIn("OUTBOX_RETRY_POLICY_ENABLED=<missing>", text)
        self.assertIn("FVG_HISTORY_ARCHIVE_ENABLED=<missing>", text)
        self.assertIn("TELEGRAM_TOKEN=ci-placeholder", text)
        self.assertIn("ADMIN_TELEGRAM_IDS=1", text)
        self.assertNotIn("production-secret-must-not-leak", text)
        self.assertNotIn("987654321", text)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_helper_preserves_child_exit_code_and_log(self):
        result, log = self._run_helper(7)
        self.assertEqual(result.returncode, 7)
        self.assertTrue(log.is_file())
        self.assertIn("MAX_SYMBOLS_PER_USER=10", log.read_text(encoding="utf-8"))

    def test_installer_runs_isolated_tests_before_service_stop(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertNotIn('cp "${ENV_FILE}" "${STAGING_DIR}/.env"', installer)
        test_position = installer.index("run_candidate_tests.sh")
        stop_position = installer.index('systemctl stop "${SERVICE_NAME}"')
        self.assertLess(test_position, stop_position)
        self.assertIn("Candidate unit tests failed.", installer)
        self.assertIn("Full log:", installer)


class FvgInstrumentLimitTests(unittest.TestCase):
    def _configured_limit(self, value):
        environment = os.environ.copy()
        if value is None:
            environment.pop("MAX_SYMBOLS_PER_USER", None)
        else:
            environment["MAX_SYMBOLS_PER_USER"] = str(value)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import config; print(config.MAX_SYMBOLS_PER_USER)",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        return int(result.stdout.strip())

    def test_limit_is_capped_at_ten(self):
        self.assertEqual(self._configured_limit(None), 10)
        self.assertEqual(self._configured_limit(5), 5)
        self.assertEqual(self._configured_limit(10), 10)
        self.assertEqual(self._configured_limit(11), 10)
        self.assertEqual(self._configured_limit(20), 10)

    def test_legacy_over_limit_settings_are_preserved_but_cannot_grow(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            symbols = {
                instrument_key("binance", f"ASSET{index}USDT"): {
                    "exchange": "binance",
                    "symbol": f"ASSET{index}USDT",
                    "timeframes": ["15m"],
                    "enabled": True,
                }
                for index in range(11)
            }
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "users": {
                            "1": {
                                "enabled": True,
                                "symbols": symbols,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            settings = FvgAlertSettings(str(path))
            self.assertEqual(len(settings.user(1)["symbols"]), 11)
            with self.assertRaisesRegex(ValueError, "не более 10"):
                settings.add_instrument(1, "bybit", "EXTRAUSDT", ("15m",))

            settings.remove_instrument(
                1, instrument_key("binance", "ASSET0USDT")
            )
            self.assertEqual(len(settings.user(1)["symbols"]), 10)
            with self.assertRaisesRegex(ValueError, "не более 10"):
                settings.add_instrument(1, "bybit", "EXTRAUSDT", ("15m",))

            settings.remove_instrument(
                1, instrument_key("binance", "ASSET1USDT")
            )
            settings.add_instrument(1, "bybit", "EXTRAUSDT", ("15m",))
            self.assertEqual(len(settings.user(1)["symbols"]), 10)


if __name__ == "__main__":
    unittest.main()
