import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "telegram-mini-app" / "src"


class Release139FinalMiniAppDesignContractTests(unittest.TestCase):
    def test_release_version_and_documents(self):
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.3.9")
        self.assertTrue((ROOT / "docs" / "RELEASE_1.3.9.md").is_file())
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 1.3.9", changelog)
        self.assertIn("## 1.3.8", changelog)

    def test_final_minimal_visual_layer_is_production_entrypoint(self):
        main = (SRC / "main.tsx").read_text(encoding="utf-8")
        css = (SRC / "final-minimal.css").read_text(encoding="utf-8")
        self.assertIn('import "./final-minimal.css";', main)
        self.assertGreater(
            main.index('import "./final-minimal.css";'),
            main.index('import "./ui-audit.css";'),
        )
        self.assertIn("--bg: #080a0c", css)
        self.assertIn("--surface: #111315", css)
        self.assertIn("--text: #f4f4f2", css)
        self.assertIn("--success: #43d17a", css)
        self.assertIn("--danger: #ff575f", css)
        self.assertNotIn("#2f9bff", css)

    def test_overview_matches_approved_information_architecture(self):
        overview = (SRC / "screens" / "OverviewScreen.tsx").read_text(encoding="utf-8")
        self.assertIn('title="TB"', overview)
        self.assertIn('className="summary-card final-summary-card"', overview)
        self.assertIn('className="overview-instruments"', overview)
        self.assertIn("function AssetMark", overview)
        self.assertIn("function Sparkline", overview)
        self.assertIn("market.get(item.key)", overview)
        self.assertIn("PriceChange value={snapshot?.priceChange24hPct}", overview)

    def test_five_tab_navigation_and_accessibility_contract_survive_visual_patch(self):
        app = (SRC / "TradingApp.tsx").read_text(encoding="utf-8")
        audit_css = (SRC / "ui-audit.css").read_text(encoding="utf-8")
        final_css = (SRC / "final-minimal.css").read_text(encoding="utf-8")
        for entry in (
            '["overview", "home", "Главная", "Home"]',
            '["fvg", "fvg", "FVG", "FVG"]',
            '["funding", "funding", "Funding", "Funding"]',
            '["notifications", "bell", "Уведомления", "Alerts"]',
            '["settings", "settings", "Настройки", "Settings"]',
        ):
            self.assertIn(entry, app)
        self.assertIn('aria-current={tab === value ? "page" : undefined}', app)
        self.assertIn("min-height: 44px", audit_css)
        self.assertIn("min-height: 56px", final_css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", final_css)

    def test_market_null_and_security_contracts_are_unchanged(self):
        ui = (SRC / "ui.tsx").read_text(encoding="utf-8")
        api = (SRC / "api.ts").read_text(encoding="utf-8")
        auth = (ROOT / "mini_app_backend" / "auth.py").read_text(encoding="utf-8")
        lifecycle = (ROOT / "mini_app_backend" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn('return <strong className="price-change unavailable">—</strong>', ui)
        self.assertIn('"/api/mini-app/settings"', api)
        self.assertIn('"/api/mini-app/market-overview"', api)
        self.assertIn("hmac.compare_digest", auth)
        self.assertIn("default=False", lifecycle)
        self.assertIn('"127.0.0.1"', lifecycle)


if __name__ == "__main__":
    unittest.main()
