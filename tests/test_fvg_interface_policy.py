import unittest

from handlers.fvg_instruments import (
    FAQ_TEXTS,
    available_timeframes,
    build_timeframe_menu,
    format_timeframe_text,
)


class FvgInterfacePolicyTests(unittest.TestCase):
    def test_bitcoin_exposes_all_confirmed_timeframes(self):
        self.assertEqual(
            available_timeframes("BTCUSDT"),
            ("15m", "1h", "4h", "1d"),
        )
        menu = build_timeframe_menu({
            "symbol": "BTCUSDT",
            "timeframes": ["15m", "1h"],
        })
        labels = [button.text for row in menu.inline_keyboard for button in row]
        self.assertIn("✅ 15 минут", labels)
        self.assertIn("✅ 1 час", labels)
        self.assertIn("⬜ 4 часа", labels)
        self.assertIn("⬜ 1 день", labels)
        self.assertIn("Выбрать все", labels)

    def test_non_bitcoin_exposes_only_fifteen_minutes(self):
        self.assertEqual(available_timeframes("ETHUSDT"), ("15m",))
        menu = build_timeframe_menu({
            "symbol": "ETHUSDT",
            "timeframes": ["15m", "1h", "4h"],
        })
        labels = [button.text for row in menu.inline_keyboard for button in row]
        callbacks = [
            button.callback_data
            for row in menu.inline_keyboard
            for button in row
        ]
        self.assertIn("✅ 15 минут", labels)
        self.assertNotIn("1 час", " ".join(labels))
        self.assertNotIn("4 часа", " ".join(labels))
        self.assertNotIn("1 день", " ".join(labels))
        self.assertNotIn("Выбрать все", labels)
        self.assertNotIn("fvg-inst:tf:1h", callbacks)

    def test_timeframe_screen_explains_current_policy(self):
        btc_text = format_timeframe_text({
            "action": "add",
            "exchange": "bitunix",
            "symbol": "BTCUSDT",
            "timeframes": ["15m"],
        })
        alt_text = format_timeframe_text({
            "action": "add",
            "exchange": "bitunix",
            "symbol": "ETHUSDT",
            "timeframes": ["15m"],
        })
        self.assertIn("Для BTC доступны 15м, 1ч, 4ч и 1д", btc_text)
        self.assertIn("только таймфрейм 15 минут", alt_text)

    def test_faq_matches_market_policy(self):
        self.assertIn("Для BTC доступны", FAQ_TEXTS["confirmed"])
        self.assertIn("остальных активов", FAQ_TEXTS["confirmed"])
        self.assertIn("15 минутах", FAQ_TEXTS["confirmed"])
        self.assertIn("выбранном таймфрейме 15 минут", FAQ_TEXTS["pre"])


if __name__ == "__main__":
    unittest.main()
