import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Release137AuditContractTests(unittest.TestCase):
    def test_release_version_and_documents(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.3.7")
        self.assertTrue((ROOT / "docs" / "RELEASE_1.3.7.md").is_file())
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 1.3.7", changelog)

    def test_runtime_audit_fixes_are_present(self):
        funding_store = (ROOT / "alerts" / "funding_exchange_store.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class _ClosingConnection(sqlite3.Connection)", funding_store)
        self.assertIn("factory=_ClosingConnection", funding_store)
        self.assertIn('connection.execute("BEGIN IMMEDIATE")', funding_store)

        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn("USER_ACTIVITY_REGISTRY = UserActivityRegistry()", bot)
        self.assertIn("USER_ACTIVITY_REGISTRY.touch", bot)

        mini_app_web = (ROOT / "mini_app_backend" / "web.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("web.AppKey", mini_app_web)
        self.assertIn("await asyncio.to_thread", mini_app_web)

        overview = (ROOT / "mini_app_backend" / "market_overview.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _normalize_instruments", overview)
        self.assertIn("def _ticker_index", overview)

    def test_runner_policy_is_exact_and_release_runs_on_linux(self):
        checker = (ROOT / ".github" / "scripts" / "check_runner_selectors.py").read_text(
            encoding="utf-8"
        )
        for selector in (
            "[self-hosted, fast]",
            "[self-hosted, docker]",
            "[self-hosted, backtester]",
            "[self-hosted, Linux]",
            "[self-hosted, macOS, ARM64]",
        ):
            self.assertIn(selector, checker)

        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("runs-on: [self-hosted, Linux]", release)
        self.assertIn("command -v sha256sum", release)
        self.assertIn("command -v gh", release)

    def test_production_defaults_remain_fail_closed(self):
        lifecycle = (ROOT / "mini_app_backend" / "lifecycle.py").read_text(
            encoding="utf-8"
        )
        config = (ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn('default=False', lifecycle)
        self.assertIn('"127.0.0.1"', lifecycle)
        self.assertIn("PUBLIC_ACCESS_ENABLED = parse_bool", config)
        self.assertIn("default=False", config)


if __name__ == "__main__":
    unittest.main()
