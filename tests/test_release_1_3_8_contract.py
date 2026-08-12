import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Release138UiUxContractTests(unittest.TestCase):
    def test_release_version_and_documents(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.3.8")
        self.assertTrue((ROOT / "docs" / "RELEASE_1.3.8.md").is_file())
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 1.3.8", changelog)
        self.assertIn("## 1.3.7", changelog)

    def test_telegram_navigation_is_localized_and_compact(self):
        menu = (ROOT / "handlers" / "menu.py").read_text(encoding="utf-8")
        settings = (ROOT / "handlers" / "settings.py").read_text(encoding="utf-8")
        start = (ROOT / "handlers" / "start.py").read_text(encoding="utf-8")
        donate = (ROOT / "handlers" / "donate.py").read_text(encoding="utf-8")

        self.assertIn('REPLY_MENU_FUNDING_EN = "💸 Funding"', menu)
        self.assertIn('input_field_placeholder=placeholder', menu)
        self.assertIn('"⚙️ Settings": "settings"', settings)
        self.assertIn("Bottom menu updated.", settings)
        self.assertIn("TB Trading Assistant", start)
        self.assertIn("USDT · ETH · BNB", donate)
        self.assertNotIn("⚠️", donate)

    def test_async_ui_storage_paths_do_not_block_event_loop(self):
        start = (ROOT / "handlers" / "start.py").read_text(encoding="utf-8")
        settings = (ROOT / "handlers" / "settings.py").read_text(encoding="utf-8")
        donate = (ROOT / "handlers" / "donate.py").read_text(encoding="utf-8")
        self.assertIn("await asyncio.to_thread", start)
        self.assertIn("await asyncio.to_thread", settings)
        self.assertIn("await asyncio.to_thread", donate)

    def test_mini_app_audit_layer_is_loaded(self):
        main = (ROOT / "telegram-mini-app" / "src" / "main.tsx").read_text(encoding="utf-8")
        css = (ROOT / "telegram-mini-app" / "src" / "ui-audit.css").read_text(encoding="utf-8")
        self.assertIn('import "./ui-audit.css";', main)
        self.assertIn("min-height: 44px", css)
        self.assertIn("input::placeholder", css)
        self.assertIn(".bottom-nav button.active::before", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_selection_and_navigation_semantics_are_preserved(self):
        ui = (ROOT / "telegram-mini-app" / "src" / "ui.tsx").read_text(encoding="utf-8")
        funding = (ROOT / "telegram-mini-app" / "src" / "screens" / "FundingScreen.tsx").read_text(encoding="utf-8")
        app = (ROOT / "telegram-mini-app" / "src" / "TradingApp.tsx").read_text(encoding="utf-8")
        self.assertIn("aria-pressed={onClick ? active : undefined}", ui)
        self.assertIn("aria-pressed={settings.notifyPositive}", funding)
        self.assertIn("aria-pressed={active}", funding)
        self.assertIn('aria-current={tab === value ? "page" : undefined}', app)

    def test_external_mini_app_menu_button_is_never_overwritten(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertNotIn("set_chat_menu_button", bot)
        self.assertNotIn("MenuButtonCommands", bot)
        self.assertIn("set_my_commands", bot)

    def test_production_defaults_remain_fail_closed(self):
        lifecycle = (ROOT / "mini_app_backend" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn("default=False", lifecycle)
        self.assertIn('"127.0.0.1"', lifecycle)
        self.assertIn("18080", lifecycle)

    def test_release_assets_do_not_require_github_cli(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("uploadReleaseAsset", workflow)
        self.assertIn("assetNames.has(name)", workflow)
        self.assertNotIn("command -v gh", workflow)
        self.assertNotIn("gh release upload", workflow)


if __name__ == "__main__":
    unittest.main()
