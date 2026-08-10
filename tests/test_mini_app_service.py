import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from alerts.funding_exchange_store import FundingExchangeStore
from alerts.funding_quarter_hour import FundingAlertStore
from alerts.fvg_store import FvgAlertSettings, instrument_key
from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from database.user_preferences import UserPreferences
from mini_app_backend.auth import TelegramUser
from mini_app_backend.service import MiniAppSettingsService, SettingsValidationError


UTC = timezone.utc


class MiniAppSettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        funding = FundingAlertStore(root / "funding.sqlite3")
        self.runtime = RuntimeSettings(root / "runtime.json")
        self.fvg = FvgAlertSettings(root / "fvg.json")
        self.service = MiniAppSettingsService(
            preferences=UserPreferences(root / "preferences.json"),
            fvg_settings=self.fvg,
            funding_settings=funding,
            funding_exchanges=FundingExchangeStore(funding.path),
            runtime_settings=self.runtime,
            access_registry=AccessRegistry(root / "access.json"),
            activity_registry=UserActivityRegistry(root / "activity.json"),
            admin_checker=lambda telegram_id: telegram_id == 1,
            env_allowed_ids={1, 42},
            env_admin_ids={1},
            public_access_default=False,
            max_symbols_per_user=3,
            diagnostics_provider=lambda: {
                "websocket": "connected",
                "outbox": 3,
                "deliveryFailures": 1,
                "databases": "ok",
                "release": "test",
            },
            now=lambda: datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        )
        self.user = TelegramUser(
            id=42,
            first_name="Михаил",
            username="michael",
            language_code="ru",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def settings(self):
        return copy.deepcopy(self.service.read_settings(self.user)["settings"])

    def test_read_returns_existing_defaults_and_server_limit(self):
        envelope = self.service.read_settings(self.user)
        self.assertEqual(envelope["user"]["id"], 42)
        self.assertEqual(envelope["limits"]["maxFvgSymbols"], 3)
        instrument = envelope["settings"]["fvg"]["symbols"][0]
        self.assertEqual(instrument["key"], "BTCUSDT")
        self.assertEqual(instrument["exchange"], "bitunix")
        self.assertEqual(instrument["symbol"], "BTCUSDT")
        self.assertEqual(instrument["timeframes"], ["15m"])
        self.assertNotIn("notifyPreFvg", envelope["settings"]["fvg"])
        self.assertNotIn("preFvg", instrument["priceFilter"]["scope"])
        self.assertFalse(envelope["settings"]["admin"]["available"])

    def test_save_round_trip_updates_all_user_stores(self):
        settings = self.settings()
        settings["general"] = {"language": "en", "messageMode": "compact"}
        settings["fvg"].update(
            {
                "enabled": True,
                "notifyConfirmedFvg": True,
                "bullishEnabled": False,
                "bearishEnabled": True,
            }
        )
        settings["fvg"]["symbols"] = [
            {
                "key": "binance|ETHUSDT",
                "exchange": "binance",
                "symbol": "ethusdt",
                "timeframes": ["15m", "1h", "4h"],
                "enabled": True,
                "priceFilter": {
                    "enabled": True,
                    "min": "2000,5",
                    "max": "4000",
                    "scope": {
                        "confirmedFvg": True,
                        "bullish": True,
                        "bearish": False,
                    },
                },
                "sizeFilter": {
                    "enabled": True,
                    "unit": "PERCENT",
                    "min": "0,25",
                    "scope": {
                        "confirmedFvg": True,
                        "bullish": False,
                        "bearish": True,
                    },
                },
            }
        ]
        settings["funding"].update(
            {
                "enabled": True,
                "intervalMinutes": 45,
                "threshold": "0,3",
                "notifyPositive": False,
                "notifyNegative": True,
                "exchanges": ["binance", "bybit"],
            }
        )

        saved = self.service.save_settings(self.user, settings)
        result = saved["settings"]
        self.assertEqual(result["general"]["language"], "en")
        self.assertEqual(result["general"]["messageMode"], "compact")
        self.assertTrue(result["fvg"]["enabled"])
        instrument = result["fvg"]["symbols"][0]
        self.assertEqual(instrument["key"], "binance|ETHUSDT")
        self.assertEqual(instrument["exchange"], "binance")
        self.assertEqual(instrument["symbol"], "ETHUSDT")
        self.assertEqual(instrument["timeframes"], ["15m", "1h", "4h"])
        self.assertEqual(instrument["priceFilter"]["min"], "2000.5")
        self.assertEqual(instrument["sizeFilter"]["min"], "0.25")
        self.assertEqual(result["funding"]["intervalMinutes"], 45)
        self.assertEqual(result["funding"]["threshold"], "0.3")
        self.assertEqual(result["funding"]["exchanges"], ["binance", "bybit"])
        self.assertIsNotNone(result["funding"]["nextCheckAt"])

        stored = self.fvg.user(self.user.id)
        stored_instrument = stored["symbols"]["binance|ETHUSDT"]
        self.assertEqual(stored_instrument["exchange"], "binance")
        self.assertEqual(stored_instrument["symbol"], "ETHUSDT")
        self.assertEqual(stored_instrument["timeframes"], ["15m", "1h", "4h"])
        self.assertFalse(stored["notify_pre_fvg"])
        self.assertFalse(stored_instrument["price_filter"]["apply_to_pre_fvg"])

    def test_same_symbol_on_multiple_exchanges_round_trips_independently(self):
        self.fvg.add_instrument(42, "bitunix", "BTCUSDT", ["15m", "1h"])
        # Default BTCUSDT already exists on Bitunix; update it instead of adding twice.
        self.fvg.update_instrument_timeframes(42, "BTCUSDT", ["15m", "1h"])
        self.fvg.add_instrument(42, "binance", "BTCUSDT", ["4h", "1d"])

        settings = self.settings()
        instruments = {item["key"]: item for item in settings["fvg"]["symbols"]}
        self.assertEqual(instruments["BTCUSDT"]["exchange"], "bitunix")
        self.assertEqual(instruments["BTCUSDT"]["timeframes"], ["15m", "1h"])
        self.assertEqual(instruments["binance|BTCUSDT"]["exchange"], "binance")
        self.assertEqual(instruments["binance|BTCUSDT"]["timeframes"], ["4h", "1d"])

        instruments["BTCUSDT"]["enabled"] = False
        instruments["binance|BTCUSDT"]["enabled"] = True
        self.service.save_settings(self.user, settings)
        stored = self.fvg.user(42)["symbols"]
        self.assertFalse(stored["BTCUSDT"]["enabled"])
        self.assertTrue(stored["binance|BTCUSDT"]["enabled"])
        self.assertEqual(stored["BTCUSDT"]["timeframes"], ["15m", "1h"])
        self.assertEqual(stored["binance|BTCUSDT"]["timeframes"], ["4h", "1d"])

    def test_legacy_pre_fvg_cannot_be_reenabled_by_payload(self):
        settings = self.settings()
        settings["fvg"]["notifyPreFvg"] = True
        settings["fvg"]["symbols"][0]["priceFilter"]["scope"]["preFvg"] = True
        self.service.save_settings(self.user, settings)
        stored = self.fvg.user(42)
        self.assertFalse(stored["notify_pre_fvg"])
        self.assertFalse(
            stored["symbols"]["BTCUSDT"]["price_filter"]["apply_to_pre_fvg"]
        )

    def test_invalid_price_range_is_rejected_before_writes(self):
        settings = self.settings()
        settings["general"]["language"] = "en"
        settings["fvg"]["symbols"][0]["priceFilter"].update(
            {"enabled": True, "min": "10", "max": "5"}
        )
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "INVALID_PRICE_RANGE")
        self.assertEqual(self.service.read_settings(self.user)["settings"]["general"]["language"], "ru")

    def test_symbol_limit_is_enforced(self):
        settings = self.settings()
        template = settings["fvg"]["symbols"][0]
        settings["fvg"]["symbols"] = []
        for exchange, symbol in (
            ("bitunix", "BTCUSDT"),
            ("binance", "ETHUSDT"),
            ("bybit", "SOLUSDT"),
            ("gate", "XRPUSDT"),
        ):
            item = copy.deepcopy(template)
            item["exchange"] = exchange
            item["symbol"] = symbol
            item["key"] = instrument_key(exchange, symbol)
            settings["fvg"]["symbols"].append(item)
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "FVG_SYMBOL_LIMIT")

    def test_duplicate_normalized_instrument_is_rejected(self):
        settings = self.settings()
        duplicate = copy.deepcopy(settings["fvg"]["symbols"][0])
        duplicate["symbol"] = "btcusdt"
        duplicate["key"] = "BTCUSDT"
        settings["fvg"]["symbols"].append(duplicate)
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "DUPLICATE_INSTRUMENT")

    def test_invalid_timeframe_and_key_are_rejected(self):
        settings = self.settings()
        settings["fvg"]["symbols"][0]["timeframes"] = ["5m"]
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "INVALID_FVG_TIMEFRAMES")

        settings = self.settings()
        settings["fvg"]["symbols"][0]["key"] = "binance|BTCUSDT"
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "INVALID_FVG_INSTRUMENT_KEY")

    def test_funding_requires_direction_and_exchange(self):
        settings = self.settings()
        settings["funding"]["notifyPositive"] = False
        settings["funding"]["notifyNegative"] = False
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "FUNDING_DIRECTION_REQUIRED")

        settings = self.settings()
        settings["funding"]["exchanges"] = []
        with self.assertRaises(SettingsValidationError) as context:
            self.service.save_settings(self.user, settings)
        self.assertEqual(context.exception.code, "INVALID_FUNDING_EXCHANGES")

    def test_non_admin_payload_cannot_change_public_access(self):
        settings = self.settings()
        settings["admin"]["publicAccessEnabled"] = True
        self.service.save_settings(self.user, settings)
        self.assertFalse(self.runtime.public_access_enabled(default=False))

    def test_admin_can_change_public_access(self):
        admin = TelegramUser(id=1, first_name="Admin")
        settings = copy.deepcopy(self.service.read_settings(admin)["settings"])
        settings["admin"]["publicAccessEnabled"] = True
        saved = self.service.save_settings(admin, settings)
        self.assertTrue(self.runtime.public_access_enabled(default=False))
        self.assertTrue(saved["settings"]["admin"]["available"])
        self.assertEqual(saved["settings"]["admin"]["diagnostics"]["outbox"], 3)

    def test_private_mode_rejects_unknown_user(self):
        stranger = TelegramUser(id=777, first_name="Unknown")
        with self.assertRaises(PermissionError):
            self.service.read_settings(stranger)


if __name__ == "__main__":
    unittest.main()
