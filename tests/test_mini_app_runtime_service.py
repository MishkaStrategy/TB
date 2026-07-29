import copy
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from alerts.funding_exchange_store import FundingExchangeStore
from alerts.funding_quarter_hour import FundingAlertStore
from alerts.fvg_store import FvgAlertSettings
from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from database.user_preferences import UserPreferences
from mini_app_backend.auth import TelegramUser
from mini_app_backend.runtime_service import MiniAppSettingsService


class MiniAppRuntimeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        funding = FundingAlertStore(root / "funding.sqlite3")
        self.exchanges = FundingExchangeStore(funding.path)
        self.service = MiniAppSettingsService(
            preferences=UserPreferences(root / "preferences.json"),
            fvg_settings=FvgAlertSettings(root / "fvg.json"),
            funding_settings=funding,
            funding_exchanges=self.exchanges,
            runtime_settings=RuntimeSettings(root / "runtime.json"),
            access_registry=AccessRegistry(root / "access.json"),
            activity_registry=UserActivityRegistry(root / "activity.json"),
            admin_checker=lambda _telegram_id: False,
            env_allowed_ids={42},
            env_admin_ids=set(),
            public_access_default=False,
            diagnostics_provider=lambda: {},
        )
        self.user = TelegramUser(id=42, first_name="Михаил")

    def tearDown(self):
        self.temporary.cleanup()

    def _settings(self):
        return copy.deepcopy(self.service.read_settings(self.user)["settings"])

    def _seed_crossing(self):
        self.exchanges.replace_crossings(
            42,
            {("bitunix", "BTCUSDT", "positive"): Decimal("0.2")},
        )
        self.assertTrue(self.exchanges.crossing_values(42))

    def test_threshold_change_clears_multi_exchange_crossings(self):
        settings = self._settings()
        self._seed_crossing()
        settings["funding"]["threshold"] = "0.3"
        self.service.save_settings(self.user, settings)
        self.assertEqual(self.exchanges.crossing_values(42), {})

    def test_direction_change_clears_multi_exchange_crossings(self):
        settings = self._settings()
        self._seed_crossing()
        settings["funding"]["notifyPositive"] = False
        self.service.save_settings(self.user, settings)
        self.assertEqual(self.exchanges.crossing_values(42), {})

    def test_unrelated_general_change_preserves_crossings(self):
        settings = self._settings()
        self._seed_crossing()
        settings["general"]["messageMode"] = "compact"
        self.service.save_settings(self.user, settings)
        self.assertTrue(self.exchanges.crossing_values(42))


if __name__ == "__main__":
    unittest.main()
