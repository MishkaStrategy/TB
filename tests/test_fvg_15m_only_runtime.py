import json
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from alerts.fvg_limited_service import FvgAlertService
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_settings_15m import FvgAlertSettings
from alerts.fvg_stream_15m import FifteenMinuteBitunixFvgStream
from alerts.scheduler_15m import _run_confirmed_15m
from bot import BOT_COMMANDS
from handlers.fvg_filter_ui import build_filter_menu
from handlers.fvg_instruments_15m import FAQ_TEXTS, build_timeframe_menu, format_instruments_text
from operations.graceful_fvg_stream_15m import FifteenMinuteGracefulBitunixFvgStream


UTC = timezone.utc
NOW = datetime(2026, 8, 7, 12, 0, 5, tzinfo=UTC)


class FakeEventStore:
    path = None

    def __init__(self):
        self.health = {}

    def increment_health(self, key, amount=1):
        self.health[key] = self.health.get(key, 0) + amount

    def update_health(self, **values):
        self.health.update(values)


class FakeBitunixClient:
    def __init__(self):
        self.calls = []

    def get_candles(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        return {"data": []}


class SettingsCompatibilityTests(unittest.TestCase):
    def test_legacy_timeframes_are_preserved_while_pre_is_retired(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/settings.json"
            with open(path, "w", encoding="utf-8") as target:
                json.dump(
                    {
                        "schema_version": 3,
                        "users": {
                            "1": {
                                "enabled": True,
                                "notify_confirmed_fvg": True,
                                "notify_pre_fvg": True,
                                "bullish_enabled": True,
                                "bearish_enabled": True,
                                "symbols": {
                                    "BTCUSDT": {
                                        "exchange": "bitunix",
                                        "symbol": "BTCUSDT",
                                        "timeframes": ["1h", "4h", "1d"],
                                        "enabled": True,
                                    }
                                },
                            }
                        },
                    },
                    target,
                )

            settings = FvgAlertSettings(path)
            user = settings.user(1)
            self.assertFalse(user["notify_pre_fvg"])
            self.assertEqual(user["symbols"]["BTCUSDT"]["timeframes"], ["1h", "4h", "1d"])
            self.assertEqual(settings.pre_active_markets(), ())
            self.assertEqual(settings.pre_enabled_chat_ids(), frozenset())


class ActiveServiceTests(unittest.TestCase):
    def test_bitcoin_recovery_requests_only_15m(self):
        client = FakeBitunixClient()
        service = FvgAlertService(
            client=client,
            event_store=FakeEventStore(),
            delivery_registry=object(),
            suppress_unavailable_users=False,
        )
        service.recover("BTCUSDT", NOW)
        self.assertEqual(client.calls, [("BTCUSDT", "15m", 20)])

    def test_minute_websocket_payload_is_rejected(self):
        service = FvgAlertService(
            client=FakeBitunixClient(),
            event_store=FakeEventStore(),
            delivery_registry=object(),
            suppress_unavailable_users=False,
        )
        with self.assertRaisesRegex(ValueError, "15m"):
            service.ingest_ws({"ch": "market_kline_1min"}, NOW)


class MultiExchangePollingTests(unittest.TestCase):
    def test_higher_timeframe_request_still_downloads_only_15m(self):
        class CandleClient:
            def __init__(self):
                self.calls = []

            def load(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return []

        client = CandleClient()
        poller = MultiExchangeFvgPoller(candle_client=client)
        with self.assertRaisesRegex(RuntimeError, "No closed 15m"):
            poller.confirmed("binance", "ETHUSDT", "1h", NOW)
        self.assertEqual(len(client.calls), 1)
        args, kwargs = client.calls[0]
        self.assertEqual(args[:3], ("binance", "ETHUSDT", "15m"))
        self.assertEqual(kwargs["limit"], 16)


class StreamPolicyTests(unittest.TestCase):
    def test_all_bitunix_stream_variants_subscribe_only_15m(self):
        self.assertEqual(
            FifteenMinuteBitunixFvgStream._channels_for("BTCUSDT"),
            ("market_kline_15min",),
        )
        self.assertEqual(
            FifteenMinuteGracefulBitunixFvgStream._channels_for("ETHUSDT"),
            ("market_kline_15min",),
        )


class SchedulerPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_timeframes_are_grouped_per_market(self):
        class Settings:
            def active_markets(self):
                return (
                    ("binance", "BTCUSDT", "15m"),
                    ("binance", "BTCUSDT", "1h"),
                    ("bybit", "ETHUSDT", "4h"),
                    ("bybit", "ETHUSDT", "1d"),
                )

        class Poller:
            def __init__(self):
                self.calls = []

            def confirmed_many(self, exchange, symbol, timeframes, now):
                self.calls.append((exchange, symbol, tuple(timeframes)))
                return []

        poller = Poller()
        service = SimpleNamespace(
            settings=Settings(),
            event_store=FakeEventStore(),
            deliver=AsyncMock(),
        )
        context = SimpleNamespace(
            bot=object(),
            job=SimpleNamespace(
                data={
                    "fvg_service": service,
                    "fvg_poller": poller,
                    "clock": lambda: NOW,
                }
            ),
        )
        await _run_confirmed_15m(context)
        self.assertEqual(
            poller.calls,
            [
                ("binance", "BTCUSDT", ("15m", "1h")),
                ("bybit", "ETHUSDT", ("4h",)),
            ],
        )
        service.deliver.assert_not_awaited()


class UserInterfacePolicyTests(unittest.TestCase):
    def test_pre_fvg_is_removed_from_commands_and_faq(self):
        commands = [item.command for item in BOT_COMMANDS]
        self.assertNotIn("fvg_pre_alert", commands)
        all_faq = " ".join(FAQ_TEXTS.values()).lower()
        self.assertNotIn("пред-fvg", all_faq)

    def test_instrument_screen_explains_source_and_target_timeframes(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            text = format_instruments_text(1, settings)
            self.assertIn("только закрытые 15м", text)
            self.assertIn("15м / 1ч / 4ч / 1д", text)

    def test_timeframe_menu_contains_all_supported_timeframes(self):
        markup = build_timeframe_menu(
            {"exchange": "binance", "symbol": "ETHUSDT", "timeframes": ["15m", "4h"]}
        )
        labels = [button.text for row in markup.inline_keyboard for button in row]
        self.assertTrue(any("15 минут" in label for label in labels))
        self.assertTrue(any("1 час" in label for label in labels))
        self.assertTrue(any("4 часа" in label for label in labels))
        self.assertTrue(any("1 день" in label for label in labels))

    def test_filter_menu_has_no_pre_or_event_type_toggle(self):
        class Settings:
            def user(self, chat_id):
                return {
                    "symbols": {
                        "BTCUSDT": {
                            "symbol": "BTCUSDT",
                            "exchange": "bitunix",
                            "price_filter": {"enabled": False},
                        }
                    }
                }

        buttons = [
            button
            for row in build_filter_menu(1, "price", "BTCUSDT", Settings()).inline_keyboard
            for button in row
        ]
        callbacks = [button.callback_data for button in buttons]
        labels = [button.text.lower() for button in buttons]
        self.assertFalse(any(":pre:" in value for value in callbacks))
        self.assertFalse(any("пред-fvg" in value for value in labels))


if __name__ == "__main__":
    unittest.main()
