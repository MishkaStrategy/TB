import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "telegram-mini-app" / "src" / "App.tsx"
MAIN = ROOT / "telegram-mini-app" / "src" / "main.tsx"
STYLES = ROOT / "telegram-mini-app" / "src" / "navigation-redesign.css"


class MiniAppNavigationTests(unittest.TestCase):
    def setUp(self):
        self.app = APP.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.styles = STYLES.read_text(encoding="utf-8")

    def test_bottom_navigation_has_only_three_primary_destinations(self):
        start = self.app.index("const primaryNavItems")
        end = self.app.index("  ];", start)
        nav = self.app[start:end]
        self.assertIn('["overview", "⌂", "Главная"]', nav)
        self.assertIn('["fvg", "◫", "FVG"]', nav)
        self.assertIn('["funding", "≋", "Фандинг"]', nav)
        self.assertNotIn('"general"', nav)
        self.assertNotIn('"notifications"', nav)
        self.assertNotIn('"admin"', nav)

    def test_secondary_sections_are_grouped_under_profile_menu(self):
        self.assertIn('className="profile-sheet"', self.app)
        self.assertIn('navigate("general")', self.app)
        self.assertIn('navigate("notifications")', self.app)
        self.assertIn('settings.admin.available ? (', self.app)
        self.assertIn('navigate("admin")', self.app)
        self.assertIn('className="top-back"', self.app)

    def test_fvg_instrument_ui_uses_server_limit_without_truncation(self):
        self.assertIn('envelope.limits?.maxFvgSymbols ?? 10', self.app)
        self.assertIn('const atInstrumentLimit = settings.fvg.symbols.length >= maxSymbols', self.app)
        self.assertIn('settings.fvg.symbols.map((item)', self.app)
        self.assertNotIn('settings.fvg.symbols.slice(', self.app)
        self.assertIn('className="instrument-list"', self.app)
        self.assertIn('Достигнут технический лимит:', self.app)

    def test_redesign_styles_are_loaded_after_base_styles(self):
        base = self.main.index('import "./styles.css";')
        redesign = self.main.index('import "./navigation-redesign.css";')
        self.assertLess(base, redesign)
        self.assertIn('.bottom-nav {', self.styles)
        self.assertIn('.profile-sheet {', self.styles)
        self.assertIn('.instrument-list {', self.styles)


if __name__ == "__main__":
    unittest.main()
