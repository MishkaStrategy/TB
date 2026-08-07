import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory

from alerts.fvg_detector import FvgDetector
from alerts.fvg_models import Candle
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_settings_15m import FvgAlertSettings
from alerts.fvg_store import instrument_key
from exchanges.fvg_candles import normalize_fvg_symbol
from handlers.fvg_instruments_15m import (
    FAQ_TEXTS,
    build_confirmation_menu,
    format_confirmation_text,
    format_instruments_text,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def candle(index, high, low, *, symbol="BTCUSDT", closed=True):
    open_time = BASE + index * STEP
    close = (Decimal(str(high)) + Decimal(str(low))) / 2
    return Candle(
        symbol=symbol,
        timeframe="15m",
        open_time=open_time,
        close_time=open_time + STEP,
        open=close,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close,
        is_closed=closed,
        is_complete=True,
    )


class InstrumentSettingsTests(unittest.TestCase):
    def test_every_instrument_is_normalized_to_15m(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", ("1h", "4h"))

            config = settings.user(1)["symbols"][instrument_key("binance", "ETHUSDT")]
            self.assertEqual(config["timeframes"], ["15m"])

    def test_same_symbol_on_two_exchanges_is_two_instruments(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", ("15m",))
            settings.add_instrument(1, "bybit", "ETHUSDT", ("15m",))

            symbols = settings.user(1)["symbols"]
            self.assertIn(instrument_key("binance", "ETHUSDT"), symbols)
            self.assertIn(instrument_key("bybit", "ETHUSDT"), symbols)
            self.assertEqual(len(symbols), 3)

    def test_duplicate_exchange_and_symbol_is_rejected(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", ("15m",))
            with self.assertRaisesRegex(ValueError, "уже добавлен"):
                settings.add_instrument(1, "binance", "ETHUSDT", ("15m",))

    def test_limit_is_ten_and_delete_frees_a_slot(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.remove_symbol(1, "BTCUSDT")
            for index in range(10):
                settings.add_instrument(
                    1,
                    "binance",
                    f"ASSET{index}USDT",
                    ("15m",),
                )
            self.assertEqual(len(settings.user(1)["symbols"]), 10)
            with self.assertRaisesRegex(ValueError, "не более 10"):
                settings.add_instrument(1, "bybit", "EXTRAUSDT", ("15m",))

            settings.remove_instrument(
                1,
                instrument_key("binance", "ASSET0USDT"),
            )
            settings.add_instrument(1, "bybit", "EXTRAUSDT", ("15m",))
            self.assertEqual(len(settings.user(1)["symbols"]), 10)

    def test_disabled_instrument_keeps_slot_and_stops_delivery(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_enabled(1, True)
            key = instrument_key("bitunix", "BTCUSDT")
            event = FvgDetector().detect_confirmed([
                candle(0, 100, 90),
                candle(1, 108, 96),
                candle(2, 112, 105),
            ])
            self.assertEqual(settings.recipients(event), [1])

            settings.set_instrument_enabled(1, key, False)
            self.assertEqual(len(settings.user(1)["symbols"]), 1)
            self.assertEqual(settings.recipients(event), [])

    def test_preference_facade_disables_pre_fvg(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_enabled(1, True)
            settings.set_pre_enabled(1, True)
            self.assertFalse(settings.is_pre_enabled(1))
            self.assertEqual(settings.pre_enabled_chat_ids(), frozenset())
            self.assertEqual(settings.pre_active_markets(), ())

    def test_schema_two_migrates_to_15m_and_disables_pre(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/settings.json"
            legacy = {
                "schema_version": 2,
                "users": {
                    "7": {
                        "enabled": True,
                        "notify_confirmed_fvg": True,
                        "notify_pre_fvg": True,
                        "symbols": {
                            "BTCUSDT": {
                                "enabled": True,
                                "timeframes": ["1h", "4h", "1d"],
                                "price_filter": {"enabled": True, "min": "60000"},
                            }
                        },
                    }
                },
            }
            with open(path, "w", encoding="utf-8") as target:
                json.dump(legacy, target)

            user = FvgAlertSettings(path).user(7)
            config = user["symbols"][instrument_key("bitunix", "BTCUSDT")]
            self.assertEqual(config["exchange"], "bitunix")
            self.assertEqual(config["symbol"], "BTCUSDT")
            self.assertEqual(config["timeframes"], ["15m"])
            self.assertFalse(user["notify_pre_fvg"])
            self.assertTrue(config["price_filter"]["enabled"])
            self.assertFalse(config["price_filter"]["apply_to_pre_fvg"])
            self.assertTrue(config["price_filter"]["apply_to_confirmed_fvg"])


class DetectorTests(unittest.TestCase):
    def test_confirmed_detector_accepts_closed_15m_candles(self):
        event = FvgDetector().detect_confirmed([
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105),
        ])
        self.assertIsNotNone(event)
        self.assertEqual(event.timeframe, "15m")
        self.assertTrue(event.is_confirmed)

    def test_unclosed_confirming_candle_does_not_signal(self):
        event = FvgDetector().detect_confirmed([
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105, closed=False),
        ])
        self.assertIsNone(event)

    def test_symbol_normalization(self):
        self.assertEqual(normalize_fvg_symbol(" btc/usdt "), "BTCUSDT")
        self.assertEqual(normalize_fvg_symbol("btc"), "BTCUSDT")

    def test_exchange_prefix_keeps_bitunix_event_id_compatible(self):
        event = FvgDetector().detect_confirmed([
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105),
        ])
        bitunix = MultiExchangeFvgPoller._with_exchange(event, "bitunix")
        binance = MultiExchangeFvgPoller._with_exchange(event, "binance")
        self.assertEqual(bitunix.event_id, event.event_id)
        self.assertTrue(binance.event_id.startswith("binance:"))


class InterfaceAndFaqTests(unittest.TestCase):
    def test_review_screen_requires_explicit_confirmation_and_fixed_15m(self):
        state = {
            "exchange": "binance",
            "symbol": "ETHUSDT",
            "timeframes": ["15m"],
        }
        text = format_confirmation_text(state)
        buttons = [
            button
            for row in build_confirmation_menu().inline_keyboard
            for button in row
        ]
        self.assertIn("Проверьте настройки", text)
        self.assertIn("ETHUSDT", text)
        self.assertIn("Таймфрейм: 15 минут", text)
        self.assertEqual(
            [button.callback_data for button in buttons],
            ["fvg15:confirm", "fvg15:cancel"],
        )

    def test_faq_is_separate_and_explains_15m_confirmation(self):
        self.assertIn("FAQ", FAQ_TEXTS["main"])
        self.assertIn("15-минутным", FAQ_TEXTS["confirmed"])
        self.assertNotIn("pre", " ".join(FAQ_TEXTS).lower())
        self.assertIn("не более 10", FAQ_TEXTS["limits"])

    def test_instrument_screen_shows_exchange_limit_and_fixed_timeframe(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            text = format_instruments_text(1, settings)
            self.assertIn("1 из 10", text)
            self.assertIn("Bitunix", text)
            self.assertIn("15 минут", text)


if __name__ == "__main__":
    unittest.main()
