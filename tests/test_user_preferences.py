import unittest
from tempfile import TemporaryDirectory

from database.user_preferences import UserPreferences
from localization import localize_text, translate_label


class UserPreferencesTests(unittest.TestCase):
    def test_defaults_and_updates_are_persistent(self):
        with TemporaryDirectory() as directory:
            path = f"{directory}/preferences.json"
            store = UserPreferences(path)
            self.assertEqual(
                store.user(42),
                {"language": "ru", "message_mode": "detailed"},
            )
            store.ensure(42, language="en")
            store.set_message_mode(42, "compact")
            self.assertEqual(
                UserPreferences(path).user(42),
                {"language": "en", "message_mode": "compact"},
            )

    def test_rejects_unknown_values(self):
        with TemporaryDirectory() as directory:
            store = UserPreferences(f"{directory}/preferences.json")
            with self.assertRaises(ValueError):
                store.set_language(42, "de")
            with self.assertRaises(ValueError):
                store.set_message_mode(42, "silent")


class LocalizationTests(unittest.TestCase):
    FVG_MESSAGE = (
        "🟢🐮 Подтверждённый бычий FVG\n"
        "Инструмент: BTCUSDT\n"
        "Таймфрейм: 15m\n"
        "Направление: Бычий\n"
        "Зона FVG: 60000 — 61000\n"
        "Размер зоны: 1000\n"
        "Цена сигнала: 60500\n"
        "Время C: 2026-07-28 10:00 UTC\n"
        "Статус: Подтверждён закрытием свечи C"
    )

    def test_english_detailed_fvg(self):
        text = localize_text(self.FVG_MESSAGE, "en", "detailed")
        self.assertIn("Confirmed bullish FVG", text)
        self.assertIn("Instrument: BTCUSDT", text)
        self.assertIn("Signal price: 60500", text)

    def test_compact_fvg_in_both_languages(self):
        ru = localize_text(self.FVG_MESSAGE, "ru", "compact")
        en = localize_text(self.FVG_MESSAGE, "en", "compact")
        self.assertEqual(
            ru,
            "🟢🐮 FVG BTCUSDT · 15m\nЗона: 60000 — 61000 · Цена: 60500\nПодтверждённый",
        )
        self.assertEqual(
            en,
            "🟢🐮 FVG BTCUSDT · 15m\nZone: 60000 — 61000 · Price: 60500\nConfirmed",
        )

    def test_translates_keyboard_labels(self):
        self.assertEqual(translate_label("⚙️ Настройки", "en"), "⚙️ Settings")
        self.assertEqual(translate_label("💸 Фандинг", "en"), "💸 Funding")
