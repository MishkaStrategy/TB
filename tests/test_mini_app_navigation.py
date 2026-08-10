import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "telegram-mini-app" / "src"
APP = SRC / "TradingApp.tsx"
MAIN = SRC / "main.tsx"
STYLES = SRC / "trading-dashboard.css"


class MiniAppNavigationTests(unittest.TestCase):
    def setUp(self):
        self.app = APP.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.styles = STYLES.read_text(encoding="utf-8")

    def test_bottom_navigation_has_five_product_destinations(self):
        start = self.app.index("const navItems")
        end = self.app.index("  ];", start)
        nav = self.app[start:end]
        self.assertIn('["overview", "home", "Главная", "Home"]', nav)
        self.assertIn('["fvg", "fvg", "FVG", "FVG"]', nav)
        self.assertIn('["funding", "funding", "Funding", "Funding"]', nav)
        self.assertIn('["notifications", "bell", "Уведомления", "Alerts"]', nav)
        self.assertIn('["settings", "settings", "Настройки", "Settings"]', nav)
        self.assertNotIn('["admin"', nav)

    def test_admin_is_secondary_and_server_capability_gated(self):
        self.assertIn('next === "admin" && !settings.admin.available', self.app)
        self.assertIn('onOpenAdmin={() => navigate("admin")}', self.app)
        self.assertIn('return <AdminScreen admin={settings.admin}', self.app)

    def test_fvg_uses_server_limit_without_client_truncation(self):
        self.assertIn('envelope.limits?.maxFvgSymbols ?? 10', self.app)
        self.assertIn('settings.fvg.symbols.length >= maxSymbols', self.app)
        self.assertNotIn('.slice(0, maxSymbols)', self.app)

    def test_mobile_navigation_and_safe_area_are_explicit(self):
        self.assertIn('grid-template-columns: repeat(5, minmax(0, 1fr))', self.styles)
        self.assertIn('env(safe-area-inset-bottom, 0px)', self.styles)
        self.assertIn('min-height: 50px', self.styles)
        self.assertIn('@media (max-width: 380px)', self.styles)
        self.assertIn('@media (prefers-reduced-motion: reduce)', self.styles)

    def test_new_react_app_replaces_legacy_dom_enhancers(self):
        self.assertIn('import TradingApp from "./TradingApp";', self.main)
        self.assertIn('import "./trading-dashboard.css";', self.main)
        self.assertNotIn("startAdminActionsEnhancer", self.main)
        self.assertNotIn("startNavigationAccessibility", self.main)
        self.assertNotIn('from "./i18n"', self.app)
        self.assertIn('document.documentElement.lang = language', self.app)


if __name__ == "__main__":
    unittest.main()
