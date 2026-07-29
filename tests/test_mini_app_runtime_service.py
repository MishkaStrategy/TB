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
        self.root = Path(self.temporary.name)
        self.funding = FundingAlertStore(self.root / "funding.sqlite3")
        self.exchanges = FundingExchangeStore(self.funding.path)
        self.service = self._service()
        self.user = TelegramUser(id=42, first_name="Михаил")

    def _service(self, *, admin=False, diagnostics_provider=lambda: {}):
        return MiniAppSettingsService(
            preferences=UserPreferences(self.root / "preferences.json"),
            fvg_settings=FvgAlertSettings(self.root / "fvg.json"),
            funding_settings=self.funding,
            funding_exchanges=self.exchanges,
            runtime_settings=RuntimeSettings(self.root / "runtime.json"),
            access_registry=AccessRegistry(self.root / "access.json"),
            activity_registry=UserActivityRegistry(self.root / "activity.json"),
            admin_checker=(lambda telegram_id: admin and telegram_id == 42),
            env_allowed_ids={42},
            env_admin_ids={42} if admin else set(),
            public_access_default=False,
            diagnostics_provider=diagnostics_provider,
        )

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

    def test_non_admin_receives_stable_empty_diagnostics(self):
        diagnostics = self.service.read_settings(self.user)["settings"]["admin"][
            "diagnostics"
        ]
        self.assertEqual(diagnostics["websocket"], "unknown")
        self.assertIsNone(diagnostics["lastWebsocketMessage"])
        self.assertEqual(diagnostics["deliveries"], 0)
        self.assertIn("pythonVersion", diagnostics)
        self.assertIn("diskTotalBytes", diagnostics)

    def test_admin_partial_provider_is_normalized(self):
        service = self._service(
            admin=True,
            diagnostics_provider=lambda: {
                "websocket": "connected",
                "outbox": 7,
                "release": "test",
            },
        )
        admin = service.read_settings(self.user)["settings"]["admin"]
        self.assertTrue(admin["available"])
        self.assertEqual(admin["diagnostics"]["websocket"], "connected")
        self.assertEqual(admin["diagnostics"]["outbox"], 7)
        self.assertEqual(admin["diagnostics"]["deliveryFailures"], 0)
        self.assertEqual(admin["diagnostics"]["gitCommit"], "unknown")


if __name__ == "__main__":
    unittest.main()
