import unittest
from pathlib import Path

from alerts.fvg_limited_service import FvgAlertService as LimitedFvgAlertService
from alerts.fvg_service_v2 import OutboxV2FvgAlertService
from alerts.fvg_store import FvgAlertSettings
from config import MAX_FVG_INSTRUMENTS_PER_USER, MAX_SYMBOLS_PER_USER
from database.fvg_history_status import read_fvg_history_status
from database.process_restart_guard_status import read_restart_guard_status
from exchanges.fvg_candles import CONFIRMED_TIMEFRAMES


class Release134ContractTests(unittest.TestCase):
    def test_release_version_and_vds_default(self):
        self.assertEqual(Path("VERSION").read_text(encoding="utf-8").strip(), "1.3.4")
        updater = Path("scripts/update_vds.sh").read_text(encoding="utf-8")
        self.assertIn('EXPECTED_VERSION="${EXPECTED_VERSION:-1.3.4}"', updater)
        self.assertIn("TARGET_REF=v1.3.4 EXPECTED_VERSION=1.3.4", updater)

    def test_candidate_tests_are_isolated_from_production_env(self):
        installer = Path("scripts/install_vds.sh").read_text(encoding="utf-8")
        helper = Path("scripts/run_candidate_tests.sh").read_text(encoding="utf-8")
        self.assertNotIn('cp "${ENV_FILE}" "${STAGING_DIR}/.env"', installer)
        self.assertIn("run_candidate_tests.sh", installer)
        self.assertIn("env -i", helper)
        self.assertIn("TELEGRAM_TOKEN=ci-placeholder", helper)
        self.assertIn("MAX_SYMBOLS_PER_USER=10", helper)

    def test_backup_suppresses_macos_metadata(self):
        backup = Path("scripts/backup_data.sh").read_text(encoding="utf-8")
        self.assertIn("COPYFILE_DISABLE=1 tar", backup)
        self.assertIn("--exclude '._*'", backup)
        self.assertIn("--exclude '.DS_Store'", backup)

    def test_fvg_timeframes_settings_schema_and_limit(self):
        self.assertEqual(CONFIRMED_TIMEFRAMES, ("15m", "1h", "4h", "1d"))
        self.assertEqual(FvgAlertSettings.SCHEMA_VERSION, 3)
        self.assertEqual(MAX_FVG_INSTRUMENTS_PER_USER, 10)
        self.assertLessEqual(MAX_SYMBOLS_PER_USER, 10)
        self.assertTrue(issubclass(OutboxV2FvgAlertService, LimitedFvgAlertService))

    def test_release_workflow_is_immutable(self):
        workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("refusing to republish it from", workflow)
        self.assertNotIn("--clobber", workflow)
        self.assertIn("release_created", workflow)

    def test_admin_operations_readers_are_available(self):
        self.assertTrue(callable(read_restart_guard_status))
        self.assertTrue(callable(read_fvg_history_status))

    def test_bot_api_only_deployment_remains_available_alongside_mini_app(self):
        wrapper = Path("scripts/update_vds_bot_api_only.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("TELEGRAM_TOKEN", wrapper)
        self.assertIn("TELEGRAM_API_HASH", wrapper)
        self.assertTrue(Path("telegram-mini-app").is_dir())
        self.assertTrue(Path("mini_app_backend").is_dir())
        self.assertNotIn("deploy_tbbot_mini_app.sh", wrapper)


if __name__ == "__main__":
    unittest.main()
