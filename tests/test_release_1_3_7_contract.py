import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Release137HistoricalMiniAppContractTests(unittest.TestCase):
    def test_release_document_and_history_are_preserved(self):
        release = ROOT / "docs" / "RELEASE_1.3.7.md"
        self.assertTrue(release.is_file())
        self.assertIn("# FVG Alert Bot 1.3.7", release.read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 1.3.7", changelog)
        self.assertTrue((ROOT / "mini_app_backend" / "service.py").is_file())
        self.assertTrue((ROOT / "telegram-mini-app" / "src" / "TradingApp.tsx").is_file())

    def test_backend_is_wired_but_default_off_and_loopback_only_by_default(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "mini_app_backend" / "lifecycle.py").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("start_mini_app_backend", bot)
        self.assertIn("stop_mini_app_backend", bot)
        self.assertIn('parse_bool(os.getenv("MINI_APP_BACKEND_ENABLED"), default=False)', lifecycle)
        self.assertIn('os.getenv("MINI_APP_BACKEND_HOST", "127.0.0.1")', lifecycle)
        self.assertIn('os.getenv("MINI_APP_BACKEND_PORT"), 18080', lifecycle)
        self.assertIn('os.getenv("MINI_APP_ALLOWED_ORIGINS", "")', lifecycle)
        self.assertIn("MINI_APP_BACKEND_ENABLED=false", env_example)
        self.assertIn("MINI_APP_BACKEND_HOST=127.0.0.1", env_example)
        self.assertIn("MINI_APP_BACKEND_PORT=18080", env_example)

    def test_bot_startup_preserves_external_web_app_menu_button(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertNotIn("set_chat_menu_button", bot)
        self.assertNotIn("MenuButtonCommands", bot)
        self.assertIn("set_my_commands", bot)

    def test_init_data_validation_is_hmac_based(self):
        auth = (ROOT / "mini_app_backend" / "auth.py").read_text(encoding="utf-8")
        self.assertIn('b"WebAppData"', auth)
        self.assertIn("hmac.compare_digest", auth)
        self.assertIn("auth_date", auth)
        self.assertIn("max_age_seconds", auth)
        self.assertIn("values supplied by the request body are never trusted", auth)

    def test_frontend_is_same_origin_and_mock_is_opt_in(self):
        api = (ROOT / "telegram-mini-app" / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn('?? ""', api)
        self.assertIn('VITE_MOCK_MODE ?? "false"', api)
        self.assertIn('request<SettingsEnvelope>("/api/mini-app/settings")', api)
        self.assertIn('request<MarketOverviewEnvelope>("/api/mini-app/market-overview")', api)

        entrypoint = (ROOT / "telegram-mini-app" / "src" / "main.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("<TradingApp />", entrypoint)

        frontend_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "telegram-mini-app" / "src").glob("**/*")
            if path.is_file()
        )
        self.assertNotIn("TELEGRAM_TOKEN", frontend_source)
        self.assertNotIn("TELEGRAM_API_ID", frontend_source)
        self.assertNotIn("TELEGRAM_API_HASH", frontend_source)
        self.assertIsNone(re.search(r"\bAPI_ID\b|\bAPI_HASH\b", frontend_source))
        self.assertIsNone(re.search(r"\d{8,10}:[A-Za-z0-9_-]{30,}", frontend_source))

    def test_bot_api_only_dependencies(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        self.assertNotIn("telethon", requirements)
        self.assertNotIn("pyrogram", requirements)

        wrapper = (ROOT / "scripts" / "update_vds_bot_api_only.sh").read_text(encoding="utf-8")
        self.assertIn("TELEGRAM_TOKEN", wrapper)
        self.assertIn("TELEGRAM_API_ID", wrapper)
        self.assertIn("TELEGRAM_API_HASH", wrapper)

    def test_origin_allowlist_and_production_domain_are_documented_without_runtime_pinning(self):
        lifecycle = (ROOT / "mini_app_backend" / "lifecycle.py").read_text(encoding="utf-8")
        web = (ROOT / "mini_app_backend" / "web.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs" / "VDS_BOT_API_ONLY_UPDATE.md").read_text(encoding="utf-8")

        self.assertIn("MINI_APP_ALLOWED_ORIGINS", lifecycle)
        self.assertIn("_normalize_origins", web)
        self.assertIn("origin not in origins", web)
        self.assertIn("MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru", docs)
        self.assertIn("MINI_APP_BACKEND_HOST=127.0.0.1", docs)
        self.assertIn("MINI_APP_BACKEND_PORT=18080", docs)
        self.assertNotIn("tbbot.mstrategy.com.ru", lifecycle)
        self.assertNotIn("tbbot.mstrategy.com.ru", web)

    def test_release_workflow_audits_archive_and_is_immutable(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("two-parent merge commit on main", workflow)
        self.assertIn("git archive", workflow)
        self.assertIn("mini_app_backend/service.py", workflow)
        self.assertIn("telegram-mini-app/package.json", workflow)
        self.assertIn("refusing to republish it from", workflow)
        self.assertIn("archive_missing", workflow)
        self.assertIn("checksum_missing", workflow)
        self.assertNotIn("--clobber", workflow)


if __name__ == "__main__":
    unittest.main()
