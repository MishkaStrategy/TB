import unittest

from fvg_ui_localization import translate_fvg_label, translate_fvg_text
from handlers.fvg_dashboard import (
    build_fvg_dashboard_menu,
    build_fvg_signal_menu,
    dashboard_snapshot,
    format_fvg_dashboard_text,
)


class FakeSettings:
    def __init__(self, user):
        self.value = user

    def user(self, chat_id):
        return self.value

    def is_enabled(self, chat_id):
        return bool(self.value.get("enabled"))


class FvgDashboardTests(unittest.TestCase):
    def test_summary_covers_exchanges_timeframes_filters_and_pre_fvg(self):
        settings = FakeSettings({
            "enabled": True,
            "notify_confirmed_fvg": True,
            "notify_pre_fvg": True,
            "bullish_enabled": True,
            "bearish_enabled": False,
            "symbols": {
                "BTCUSDT": {
                    "exchange": "bitunix",
                    "symbol": "BTCUSDT",
                    "timeframes": ["15m", "1h"],
                    "enabled": True,
                    "price_filter": {"enabled": True},
                    "size_filter": {"enabled": False},
                },
                "binance|ETHUSDT": {
                    "exchange": "binance",
                    "symbol": "ETHUSDT",
                    "timeframes": ["4h"],
                    "enabled": False,
                    "price_filter": {"enabled": False},
                    "size_filter": {"enabled": True},
                },
            },
        })
        summary = dashboard_snapshot(42, settings)
        self.assertTrue(summary["module_enabled"])
        self.assertTrue(summary["pre_capable"])
        self.assertEqual(summary["instrument_count"], 2)
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["exchanges"], ["binance", "bitunix"])
        self.assertEqual(summary["timeframes"], ["15m", "1h", "4h"])
        self.assertEqual(summary["price_filter_count"], 1)
        self.assertEqual(summary["size_filter_count"], 1)

        text = format_fvg_dashboard_text(42, settings)
        self.assertIn("2 из 10", text)
        self.assertIn("Bitunix", text)
        self.assertIn("Binance", text)
        self.assertIn("15м, 1ч, 4ч", text)
        self.assertIn("пред-FVG BTC", text)

    def test_pre_fvg_requires_bitcoin_on_15_minutes(self):
        settings = FakeSettings({
            "enabled": True,
            "notify_confirmed_fvg": True,
            "notify_pre_fvg": True,
            "bullish_enabled": True,
            "bearish_enabled": True,
            "symbols": {
                "BTCUSDT": {
                    "exchange": "bitunix",
                    "symbol": "BTCUSDT",
                    "timeframes": ["1h"],
                    "enabled": True,
                },
                "binance|ETHUSDT": {
                    "exchange": "binance",
                    "symbol": "ETHUSDT",
                    "timeframes": ["15m"],
                    "enabled": True,
                },
            },
        })
        summary = dashboard_snapshot(42, settings)
        self.assertFalse(summary["pre_capable"])
        labels = [
            button.text
            for row in build_fvg_signal_menu(42, settings).inline_keyboard
            for button in row
        ]
        self.assertIn("ℹ️ Пред-FVG: нужен BTC · 15м", labels)
        self.assertNotIn("✅ Пред-FVG BTC · 15м", labels)

    def test_dashboard_exposes_add_flow_and_limit_state(self):
        under_limit = FakeSettings({
            "enabled": False,
            "symbols": {
                "BTCUSDT": {
                    "exchange": "bitunix",
                    "symbol": "BTCUSDT",
                    "timeframes": ["15m"],
                }
            },
        })
        callbacks = [
            button.callback_data
            for row in build_fvg_dashboard_menu(42, under_limit).inline_keyboard
            for button in row
        ]
        self.assertIn("fvg-inst:add", callbacks)
        self.assertIn("fvg-inst:open", callbacks)
        self.assertIn("fvg-inst:faq:main", callbacks)

        full = FakeSettings({
            "enabled": True,
            "symbols": {
                f"symbol-{index}": {
                    "exchange": "bitunix",
                    "symbol": f"TOKEN{index}USDT",
                    "timeframes": ["15m"],
                }
                for index in range(10)
            },
        })
        buttons = [
            button
            for row in build_fvg_dashboard_menu(42, full).inline_keyboard
            for button in row
        ]
        self.assertIn("🔒 Лимит 10/10", [button.text for button in buttons])
        self.assertNotIn("fvg-inst:add", [button.callback_data for button in buttons])

    def test_expanded_fvg_interface_has_english_translation(self):
        self.assertEqual(
            translate_fvg_label("➕ Добавить инструмент", "en"),
            "➕ Add instrument",
        )
        translated = translate_fvg_text(
            "📉 <b>FVG-центр</b>\nИнструменты: 2 из 10",
            "en",
        )
        self.assertIn("FVG center", translated)
        self.assertIn("Instruments:", translated)
        self.assertIn("2 of 10", translated)


if __name__ == "__main__":
    unittest.main()
