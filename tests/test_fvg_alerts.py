import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from alerts.fvg_detector import FvgDetector, fvg_size_value, price_allowed, size_allowed
from alerts.fvg_models import Candle, FvgDirection
from alerts.fvg_service import FvgAlertService, format_fvg_message, parse_rest_candle, parse_ws_candle
from alerts.fvg_settings_15m import FvgAlertSettings
from alerts.fvg_store import FvgEventStore
from handlers.fvg_filter_ui import (
    FILTER_INPUT_KEY,
    fvg_filter_callback,
    parse_filter_callback,
    parse_filter_range,
    parse_size_minimum,
    receive_filter_range,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def candle(index, high, low, close=None, *, closed=True, complete=True):
    step = timedelta(minutes=15)
    start = BASE + index * step
    close = Decimal(
        str(
            close
            if close is not None
            else (Decimal(str(high)) + Decimal(str(low))) / 2
        )
    )
    return Candle(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=start,
        close_time=start + step,
        open=close,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close,
        is_closed=closed,
        is_complete=complete,
    )


class FvgDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = FvgDetector()

    def test_bullish_confirmed_fvg(self):
        event = self.detector.detect_confirmed([
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105),
        ])
        self.assertEqual(event.direction, FvgDirection.BULLISH)
        self.assertEqual(
            (event.zone_low, event.zone_high),
            (Decimal("100"), Decimal("105")),
        )
        self.assertEqual(event.signal_price, Decimal("108.5"))
        self.assertTrue(event.is_confirmed)
        self.assertEqual(event.timeframe, "15m")

    def test_bearish_confirmed_fvg(self):
        event = self.detector.detect_confirmed([
            candle(0, 110, 100),
            candle(1, 104, 95),
            candle(2, 94, 90),
        ])
        self.assertEqual(event.direction, FvgDirection.BEARISH)
        self.assertEqual(
            (event.zone_low, event.zone_high),
            (Decimal("94"), Decimal("100")),
        )

    def test_no_gap_and_equal_boundaries_are_not_fvg(self):
        self.assertIsNone(
            self.detector.detect_confirmed([
                candle(0, 100, 90),
                candle(1, 106, 95),
                candle(2, 110, 100),
            ])
        )

    def test_rejects_incomplete_open_or_nonconsecutive_candles(self):
        incomplete = [
            candle(0, 100, 90),
            candle(1, 108, 96, complete=False),
            candle(2, 112, 105),
        ]
        opened = [
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105, closed=False),
        ]
        skipped = [
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(3, 112, 105),
        ]
        self.assertIsNone(self.detector.detect_confirmed(incomplete))
        self.assertIsNone(self.detector.detect_confirmed(opened))
        self.assertIsNone(self.detector.detect_confirmed(skipped))

    def test_rejects_non_15m_timeframe(self):
        values = [candle(0, 100, 90), candle(1, 108, 96), candle(2, 112, 105)]
        hourly = [
            Candle(**{**item.__dict__, "timeframe": "1h"})
            for item in values
        ]
        self.assertIsNone(self.detector.detect_confirmed(hourly))


class CandleParsingPolicyTests(unittest.TestCase):
    def test_rest_parser_rejects_minute_candles(self):
        raw = {
            "time": int(BASE.timestamp() * 1000),
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
        }
        with self.assertRaisesRegex(ValueError, "15m"):
            parse_rest_candle(raw, "BTCUSDT", "1m", BASE)

    def test_websocket_parser_rejects_minute_channel(self):
        payload = {
            "ch": "market_kline_1min",
            "symbol": "BTCUSDT",
            "ts": int(BASE.timestamp() * 1000),
            "data": {"o": "100", "h": "110", "l": "90", "c": "105"},
        }
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            parse_ws_candle(payload, BASE)


class FilterRuleTests(unittest.TestCase):
    def test_price_boundaries(self):
        self.assertTrue(price_allowed(Decimal("1"), False, Decimal("10"), Decimal("20")))
        self.assertTrue(price_allowed(Decimal("10"), True, Decimal("10"), Decimal("20")))
        self.assertFalse(price_allowed(Decimal("9.99"), True, Decimal("10"), None))
        self.assertFalse(price_allowed(Decimal("20.01"), True, None, Decimal("20")))

    def test_size_usd_and_percent(self):
        self.assertEqual(
            fvg_size_value(Decimal("5"), Decimal("100"), "USD"),
            Decimal("5"),
        )
        self.assertEqual(
            fvg_size_value(Decimal("5"), Decimal("100"), "PERCENT"),
            Decimal("5"),
        )
        self.assertTrue(
            size_allowed(
                Decimal("5"),
                Decimal("100"),
                True,
                "USD",
                Decimal("5"),
                Decimal("5"),
            )
        )

    def test_compact_filter_inputs(self):
        self.assertEqual(parse_filter_range("0,1 - 0,5%"), ("0.1", "0.5"))
        self.assertEqual(parse_filter_range("60000-"), ("60000", None))
        self.assertEqual(parse_filter_range("-90000"), (None, "90000"))
        self.assertEqual(parse_size_minimum("0,1%"), "0.1")
        self.assertEqual(parse_size_minimum("10 $"), "10")

    def test_filter_callbacks_keep_action_kind_and_symbol(self):
        self.assertEqual(
            parse_filter_callback("fvg-filter:select:price:BTCUSDT"),
            ("select", "price", "BTCUSDT"),
        )
        self.assertEqual(
            parse_filter_callback("fvg-filter:select:size:BTCUSDT"),
            ("select", "size", "BTCUSDT"),
        )
        self.assertEqual(
            parse_filter_callback("fvg-filter:open:price"),
            ("open", "price", None),
        )


class SettingsAndDedupTests(unittest.TestCase):
    def test_size_filter_keeps_only_minimum_and_discards_maximum(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_size_filter(
                1,
                "BTCUSDT",
                "0.1",
                "5",
                unit="PERCENT",
            )
            saved = settings.user(1)["symbols"]["BTCUSDT"]["size_filter"]
            self.assertEqual(saved["min"], "0.1")
            self.assertIsNone(saved["max"])
            self.assertFalse(saved["apply_to_pre_fvg"])
            self.assertTrue(saved["apply_to_confirmed_fvg"])

    def test_legacy_pre_choice_is_retired(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/settings.json"
            with open(path, "w", encoding="utf-8") as file:
                file.write('{"enabled_chat_ids":[1,2],"pre_enabled_chat_ids":[2]}')
            settings = FvgAlertSettings(path)
            self.assertTrue(settings.is_enabled(1))
            self.assertFalse(settings.is_pre_enabled(1))
            self.assertFalse(settings.is_pre_enabled(2))
            self.assertEqual(settings.pre_active_markets(), ())

    def test_direction_symbol_and_price_are_user_scoped(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_enabled(1, True)
            settings.set_enabled(2, True)
            settings.set_price_filter(
                1,
                "BTCUSDT",
                "100",
                "110",
                apply_to_pre=False,
                apply_to_confirmed=True,
            )
            event = FvgDetector().detect_confirmed([
                candle(0, 100, 90),
                candle(1, 108, 96),
                candle(2, 112, 105),
            ])
            self.assertEqual(settings.recipients(event), [1, 2])
            settings.set_direction_enabled(2, FvgDirection.BULLISH, False)
            self.assertEqual(settings.recipients(event), [1])

    def test_price_filter_can_target_only_bullish_fvg(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.set_enabled(1, True)
            settings.set_price_filter(
                1,
                "BTCUSDT",
                "200",
                None,
                apply_to_bullish=True,
                apply_to_bearish=False,
            )
            detector = FvgDetector()
            bullish = detector.detect_confirmed([
                candle(0, 100, 90),
                candle(1, 108, 96),
                candle(2, 112, 105),
            ])
            bearish = detector.detect_confirmed([
                candle(0, 110, 100),
                candle(1, 104, 95),
                candle(2, 94, 90),
            ])
            self.assertEqual(settings.recipients(bullish), [])
            self.assertEqual(settings.recipients(bearish), [1])

    def test_market_event_and_user_deliveries_are_separate_and_persistent(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/events.sqlite3"
            event = FvgDetector().detect_confirmed([
                candle(0, 100, 90),
                candle(1, 108, 96),
                candle(2, 112, 105),
            ])
            store = FvgEventStore(path)
            self.assertTrue(store.record_event(event))
            self.assertFalse(store.record_event(event))
            store.mark_delivered(1, event.event_id)
            restarted = FvgEventStore(path)
            self.assertFalse(restarted.delivery_needed(1, event.event_id))
            self.assertTrue(restarted.delivery_needed(2, event.event_id))

    def test_message_has_mandatory_fields_and_no_trading_advice(self):
        event = FvgDetector().detect_confirmed([
            candle(0, 100, 90),
            candle(1, 108, 96),
            candle(2, 112, 105),
        ])
        text = format_fvg_message(event)
        for expected in (
            "BTCUSDT",
            "15m",
            "Бычий",
            "Зона FVG",
            "Размер зоны",
            "Цена сигнала",
            "Подтверждён",
        ):
            self.assertIn(expected, text)
        for forbidden in ("вход", "стоп", "тейк", "плеч"):
            self.assertNotIn(forbidden, text.lower())


class DeliveryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_range_input_persists_and_enables_both_filter_kinds(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_symbol(42, "BTCUSDT")
            cases = (("price", "60000-90000"), ("size", "0,1"))
            for kind, text in cases:
                message = SimpleNamespace(text=text, reply_text=AsyncMock())
                update = SimpleNamespace(
                    effective_message=message,
                    effective_chat=SimpleNamespace(id=42),
                )
                state = {"kind": kind, "symbol": "BTCUSDT"}
                context = SimpleNamespace(
                    user_data={FILTER_INPUT_KEY: state},
                    chat_data={FILTER_INPUT_KEY: state},
                )
                with patch(
                    "handlers.fvg_filter_ui.FvgAlertSettings",
                    return_value=settings,
                ):
                    await receive_filter_range(update, context)
                key = "price_filter" if kind == "price" else "size_filter"
                saved = settings.user(42)["symbols"]["BTCUSDT"][key]
                self.assertTrue(saved["enabled"])
                self.assertFalse(saved["apply_to_pre_fvg"])
                self.assertTrue(saved["apply_to_confirmed_fvg"])
                if kind == "size":
                    self.assertEqual(saved["min"], "0.1")
                    self.assertIsNone(saved["max"])
                self.assertIsNone(context.user_data.get(FILTER_INPUT_KEY))
                self.assertIsNone(context.chat_data.get(FILTER_INPUT_KEY))
                message.reply_text.assert_awaited_once()

    async def test_price_and_size_symbol_buttons_open_filter_screen(self):
        for kind in ("price", "size"):
            message = SimpleNamespace(edit_text=AsyncMock(), reply_text=AsyncMock())
            query = SimpleNamespace(
                data=f"fvg-filter:select:{kind}:BTCUSDT",
                answer=AsyncMock(),
                message=message,
            )
            update = SimpleNamespace(
                callback_query=query,
                effective_chat=SimpleNamespace(id=42),
            )
            context = SimpleNamespace(user_data={}, chat_data={})
            settings = SimpleNamespace(
                user=lambda chat_id: {
                    "symbols": {
                        "BTCUSDT": {
                            "symbol": "BTCUSDT",
                            "exchange": "bitunix",
                            "price_filter": {"enabled": False},
                            "size_filter": {"enabled": False, "unit": "USD"},
                        }
                    }
                }
            )
            with patch(
                "handlers.fvg_filter_ui.FvgAlertSettings",
                return_value=settings,
            ):
                await fvg_filter_callback(update, context)
            query.answer.assert_awaited_once()
            message.edit_text.assert_awaited_once()

    async def test_two_users_receive_once_and_restart_does_not_duplicate(self):
        class Bot:
            def __init__(self):
                self.calls = []

            async def send_message(self, chat_id, text):
                self.calls.append((chat_id, text))

        with TemporaryDirectory() as directory:
            settings_path = f"{directory}/settings.json"
            events_path = f"{directory}/events.sqlite3"
            settings = FvgAlertSettings(settings_path)
            settings.set_enabled(1, True)
            settings.set_enabled(2, True)
            event = FvgDetector().detect_confirmed([
                candle(0, 100, 90),
                candle(1, 108, 96),
                candle(2, 112, 105),
            ])
            bot = Bot()
            service = FvgAlertService(
                settings=settings,
                event_store=FvgEventStore(events_path),
                suppress_unavailable_users=False,
            )
            await service.deliver(bot, [event, event])
            restarted = FvgAlertService(
                settings=FvgAlertSettings(settings_path),
                event_store=FvgEventStore(events_path),
                suppress_unavailable_users=False,
            )
            await restarted.deliver(bot, [event])
            self.assertEqual([call[0] for call in bot.calls], [1, 2])


if __name__ == "__main__":
    unittest.main()
