import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from alerts.fvg_detector import FvgDetector
from alerts.fvg_models import Candle, FvgEventType, event_id
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_store import FvgAlertSettings, instrument_key
from alerts.scheduler import run_fvg_control_point
from exchanges.fvg_candles import (
    CONFIRMED_TIMEFRAMES,
    is_bitcoin_symbol,
    normalize_fvg_symbol,
    timeframe_due,
)
from handlers.fvg_instruments import FAQ_TEXTS, format_instruments_text


UTC = timezone.utc
BASE = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
STEPS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def candle(index, high, low, *, symbol="BTCUSDT", timeframe="15m", closed=True):
    step = STEPS[timeframe]
    open_time = BASE + index * step
    close = (Decimal(str(high)) + Decimal(str(low))) / 2
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + step,
        open=close,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close,
        is_closed=closed,
        is_complete=True,
    )


class InstrumentSettingsTests(unittest.TestCase):
    def test_one_instrument_can_have_all_timeframes_and_counts_once(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", CONFIRMED_TIMEFRAMES)

            user = settings.user(1)
            config = user["symbols"][instrument_key("binance", "ETHUSDT")]

            self.assertEqual(len(user["symbols"]), 2)  # existing BTC plus ETH
            self.assertEqual(tuple(config["timeframes"]), CONFIRMED_TIMEFRAMES)

    def test_same_symbol_on_two_exchanges_is_two_instruments(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", ("15m",))
            settings.add_instrument(1, "bybit", "ETHUSDT", ("1h",))

            symbols = settings.user(1)["symbols"]
            self.assertIn(instrument_key("binance", "ETHUSDT"), symbols)
            self.assertIn(instrument_key("bybit", "ETHUSDT"), symbols)
            self.assertEqual(len(symbols), 3)

    def test_duplicate_exchange_and_symbol_is_rejected(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_instrument(1, "binance", "ETHUSDT", ("15m",))
            with self.assertRaisesRegex(ValueError, "уже добавлен"):
                settings.add_instrument(1, "binance", "ETHUSDT", ("1h",))

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

    def test_cannot_save_empty_timeframe_selection(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            with self.assertRaisesRegex(ValueError, "хотя бы один"):
                settings.add_instrument(1, "binance", "ETHUSDT", ())

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

    def test_timeframe_selection_filters_recipients(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_enabled(1, True)
            event = FvgDetector().detect_confirmed([
                candle(0, 100, 90, timeframe="1h"),
                candle(1, 108, 96, timeframe="1h"),
                candle(2, 112, 105, timeframe="1h"),
            ])
            self.assertEqual(settings.recipients(event), [])

            settings.update_instrument_timeframes(
                1,
                instrument_key("bitunix", "BTCUSDT"),
                ("1h",),
            )
            self.assertEqual(settings.recipients(event), [1])

    def test_pre_fvg_is_rejected_for_non_bitcoin(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.remove_symbol(1, "BTCUSDT")
            settings.add_instrument(1, "bitunix", "ETHUSDT", ("15m",))
            settings.set_enabled(1, True)
            settings.set_pre_enabled(1, True)
            detector = FvgDetector()
            a = candle(0, 100, 90, symbol="ETHUSDT")
            b = candle(1, 108, 96, symbol="ETHUSDT")
            c = candle(2, 112, 105, symbol="ETHUSDT", closed=False)
            event = detector.detect_pre(a, b, c, c.open_time + timedelta(minutes=12))

            self.assertEqual(event.event_type, FvgEventType.PRE_FVG)
            self.assertEqual(settings.recipients(event), [])
            self.assertEqual(settings.pre_active_markets(), ())

    def test_pre_fvg_works_for_bitcoin_on_selected_exchange(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.remove_symbol(1, "BTCUSDT")
            settings.add_instrument(1, "binance", "BTCUSDT", ("15m",))
            settings.set_enabled(1, True)
            settings.set_pre_enabled(1, True)
            detector = FvgDetector()
            a = candle(0, 100, 90)
            b = candle(1, 108, 96)
            c = candle(2, 112, 105, closed=False)
            original = detector.detect_pre(a, b, c, c.open_time + timedelta(minutes=12))
            event = replace(
                original,
                exchange="binance",
                event_id=event_id(
                    original.symbol,
                    original.timeframe,
                    original.direction,
                    original.candle_c_open_time,
                    original.event_type,
                    "binance",
                ),
            )

            self.assertEqual(settings.recipients(event), [1])
            self.assertEqual(settings.pre_active_markets(), (("binance", "BTCUSDT"),))

    def test_schema_two_migrates_to_exchange_and_timeframes(self):
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
                                "price_filter": {"enabled": True, "min": "60000"},
                            }
                        },
                    }
                },
            }
            with open(path, "w", encoding="utf-8") as target:
                json.dump(legacy, target)

            config = FvgAlertSettings(path).user(7)["symbols"][
                instrument_key("bitunix", "BTCUSDT")
            ]
            self.assertEqual(config["exchange"], "bitunix")
            self.assertEqual(config["symbol"], "BTCUSDT")
            self.assertEqual(config["timeframes"], ["15m"])
            self.assertTrue(config["price_filter"]["enabled"])


class DetectorAndScheduleTests(unittest.TestCase):
    def test_confirmed_detector_supports_all_requested_timeframes(self):
        detector = FvgDetector()
        for timeframe in CONFIRMED_TIMEFRAMES:
            event = detector.detect_confirmed([
                candle(0, 100, 90, timeframe=timeframe),
                candle(1, 108, 96, timeframe=timeframe),
                candle(2, 112, 105, timeframe=timeframe),
            ])
            self.assertIsNotNone(event, timeframe)
            self.assertEqual(event.timeframe, timeframe)

    def test_timeframe_due_matches_boundaries(self):
        self.assertTrue(timeframe_due("15m", BASE.replace(minute=15)))
        self.assertTrue(timeframe_due("1h", BASE.replace(minute=0)))
        self.assertTrue(timeframe_due("4h", BASE.replace(hour=12, minute=0)))
        self.assertTrue(timeframe_due("1d", BASE.replace(hour=0, minute=0)))
        self.assertFalse(timeframe_due("4h", BASE.replace(hour=13, minute=0)))
        self.assertFalse(timeframe_due("1d", BASE.replace(hour=12, minute=0)))

    def test_symbol_normalization_and_bitcoin_detection(self):
        self.assertEqual(normalize_fvg_symbol(" btc/usdt "), "BTCUSDT")
        self.assertEqual(normalize_fvg_symbol("btc"), "BTCUSDT")
        self.assertTrue(is_bitcoin_symbol("BTCUSDC"))
        self.assertFalse(is_bitcoin_symbol("WBTCUSDT"))

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


class SharedSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_market_is_calculated_once_for_all_users(self):
        class Settings:
            def active_markets(self):
                return (("binance", "ETHUSDT", "15m"),)

        class Service:
            def __init__(self):
                self.settings = Settings()
                self.event_store = SimpleNamespace(
                    update_health=lambda **values: None,
                    increment_health=lambda *args: None,
                )
                self.deliver = AsyncMock()

        class Poller:
            def __init__(self):
                self.calls = []

            def confirmed(self, exchange, symbol, timeframe, now):
                self.calls.append((exchange, symbol, timeframe))
                return []

        service = Service()
        poller = Poller()
        context = SimpleNamespace(
            bot=object(),
            job=SimpleNamespace(data={
                "fvg_service": service,
                "fvg_poller": poller,
                "mode": "confirmed",
                "clock": lambda: BASE.replace(minute=15, second=5),
            }),
        )

        await run_fvg_control_point(context)

        self.assertEqual(poller.calls, [("binance", "ETHUSDT", "15m")])
        service.deliver.assert_awaited_once()


class FaqTests(unittest.TestCase):
    def test_faq_is_separate_and_explains_core_rules(self):
        self.assertIn("FAQ", FAQ_TEXTS["main"])
        self.assertIn("закрытия свечи", FAQ_TEXTS["confirmed"])
        self.assertIn("только для пар", FAQ_TEXTS["pre"])
        self.assertIn("не более 10", FAQ_TEXTS["limits"])

    def test_instrument_screen_shows_exchange_and_limit(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            text = format_instruments_text(1, settings)
            self.assertIn("1 из 10", text)
            self.assertIn("Bitunix", text)
            self.assertIn("15м", text)


if __name__ == "__main__":
    unittest.main()
