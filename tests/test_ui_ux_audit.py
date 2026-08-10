import unittest
from pathlib import Path

from handlers.donate import format_donation_text
from handlers.menu import build_reply_menu


ROOT = Path(__file__).resolve().parents[1]


def keyboard_text(markup):
    return tuple(tuple(button.text for button in row) for row in markup.keyboard)


class UiUxAuditTests(unittest.TestCase):
    def test_bot_startup_does_not_overwrite_persistent_mini_app_button(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertNotIn("MenuButtonCommands", bot)
        self.assertNotIn("set_chat_menu_button", bot)

    def test_reply_keyboard_follows_selected_language(self):
        ru = build_reply_menu("ru")
        en = build_reply_menu("en")
        ru_rows = keyboard_text(ru)
        en_rows = keyboard_text(en)

        self.assertEqual(ru.input_field_placeholder, "Выберите раздел")
        self.assertEqual(en.input_field_placeholder, "Choose a section")
        self.assertEqual(ru_rows[0], ("📉 FVG", "💸 Фандинг"))
        self.assertEqual(en_rows[0], ("📉 FVG", "💸 Funding"))
        self.assertIn("🔔 Уведомления", ru_rows[1])
        self.assertIn("🔔 Alerts", en_rows[1])
        self.assertIn("⚙️ Настройки", ru_rows[2])
        self.assertIn("⚙️ Settings", en_rows[2])

    def test_telegram_ui_storage_reads_stay_off_event_loop(self):
        start = (ROOT / "handlers" / "start.py").read_text(encoding="utf-8")
        donate = (ROOT / "handlers" / "donate.py").read_text(encoding="utf-8")
        settings = (ROOT / "handlers" / "settings.py").read_text(encoding="utf-8")
        self.assertIn("await asyncio.to_thread(_enable_confirmed_fvg_for_new_user", start)
        self.assertIn("await asyncio.to_thread(PREFERENCES.user", start)
        self.assertIn("await asyncio.to_thread(PREFERENCES.user", donate)
        self.assertIn("await asyncio.to_thread(PREFERENCES.user", settings)
        self.assertIn("await asyncio.to_thread(PREFERENCES.set_language", settings)

    def test_donation_panel_is_localized_and_has_no_extra_warning(self):
        ru = format_donation_text("ru")
        en = format_donation_text("en")
        self.assertIn("Поддержать проект", ru)
        self.assertIn("Support the project", en)
        self.assertIn("USDT · ETH · BNB", ru)
        self.assertIn("USDT · ETH · BNB", en)
        self.assertNotIn("⚠️", ru)
        self.assertNotIn("⚠️", en)

    def test_mini_app_loads_audited_visual_layer(self):
        main = (ROOT / "telegram-mini-app" / "src" / "main.tsx").read_text(
            encoding="utf-8"
        )
        css = (ROOT / "telegram-mini-app" / "src" / "ui-audit.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('import "./ui-audit.css";', main)
        self.assertIn(".bottom-nav button.active::before", css)
        self.assertIn("font-size: 10px", css)
        self.assertIn("input::placeholder", css)
        self.assertIn("color: #78879d", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_mini_app_selection_controls_expose_pressed_state(self):
        ui = (ROOT / "telegram-mini-app" / "src" / "ui.tsx").read_text(
            encoding="utf-8"
        )
        funding = (
            ROOT / "telegram-mini-app" / "src" / "screens" / "FundingScreen.tsx"
        ).read_text(encoding="utf-8")
        trading_app = (
            ROOT / "telegram-mini-app" / "src" / "TradingApp.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("aria-pressed={onClick ? active : undefined}", ui)
        self.assertIn("aria-pressed={settings.notifyPositive}", funding)
        self.assertIn("aria-pressed={active}", funding)
        self.assertIn('aria-current={tab === value ? "page" : undefined}', trading_app)

    def test_russian_mini_app_copy_avoids_known_mixed_language_regressions(self):
        overview = (
            ROOT / "telegram-mini-app" / "src" / "screens" / "OverviewScreen.tsx"
        ).read_text(encoding="utf-8")
        fvg = (
            ROOT / "telegram-mini-app" / "src" / "screens" / "FvgScreen.tsx"
        ).read_text(encoding="utf-8")
        settings = (
            ROOT / "telegram-mini-app" / "src" / "screens" / "SettingsScreen.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("Центр управления сигналами", overview)
        self.assertIn('tx(language, "Активен", "Active")', overview)
        self.assertIn('tx(language, "Фильтр цены", "Price filter")', fvg)
        self.assertIn('tx(language, "Компактный", "Compact")', settings)


if __name__ == "__main__":
    unittest.main()
