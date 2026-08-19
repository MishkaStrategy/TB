import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "telegram-mini-app" / "src"
STYLES = SRC / "trading-dashboard.css"
FINAL_STYLES = SRC / "final-minimal.css"
MAIN = SRC / "main.tsx"
UI = SRC / "ui.tsx"
OVERVIEW = SRC / "screens" / "OverviewScreen.tsx"
FVG = SRC / "screens" / "FvgScreen.tsx"
FUNDING = SRC / "screens" / "FundingScreen.tsx"
SETTINGS = SRC / "screens" / "SettingsScreen.tsx"


class MiniAppDesignAuditTests(unittest.TestCase):
    def setUp(self):
        self.styles = STYLES.read_text(encoding="utf-8")
        self.final_styles = FINAL_STYLES.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.ui = UI.read_text(encoding="utf-8")
        self.overview = OVERVIEW.read_text(encoding="utf-8")
        self.fvg = FVG.read_text(encoding="utf-8")
        self.funding = FUNDING.read_text(encoding="utf-8")
        self.settings = SETTINGS.read_text(encoding="utf-8")

    def test_dark_trading_design_tokens_are_explicit(self):
        for token in (
            "--bg: #070b12",
            "--surface: #101722",
            "--surface-2: #121b28",
            "--primary: #2f9bff",
            "--cyan: #32d5ff",
            "--success: #26d99a",
            "--danger: #ff5d6c",
            "--text: #f5f7fb",
            "--muted: #8d9aaf",
        ):
            self.assertIn(token, self.styles)
        self.assertIn("border-radius: 16px", self.styles)

    def test_approved_final_minimal_layer_is_loaded_last(self):
        self.assertIn('import "./trading-dashboard.css";', self.main)
        self.assertIn('import "./ui-audit.css";', self.main)
        self.assertIn('import "./final-minimal.css";', self.main)
        self.assertGreater(
            self.main.index('import "./final-minimal.css";'),
            self.main.index('import "./ui-audit.css";'),
        )
        for token in (
            "--bg: #080a0c",
            "--surface: #111315",
            "--text: #f4f4f2",
            "--muted: #96989d",
            "--success: #43d17a",
            "--danger: #ff575f",
        ):
            self.assertIn(token, self.final_styles)
        self.assertIn("background-image: none", self.final_styles)
        self.assertNotIn("#2f9bff", self.final_styles)

    def test_approved_overview_composition_matches_selected_reference(self):
        for marker in (
            'className="summary-card final-summary-card"',
            'className="final-summary-lines"',
            'className="overview-instruments"',
            'className="market-row final-market-row"',
            "function AssetMark",
            "function Sparkline",
            "24h change",
        ):
            self.assertIn(marker, self.overview)
        self.assertIn("grid-template-columns: 46px minmax(0, 1fr) 78px 86px", self.final_styles)
        self.assertIn(".asset-btc", self.final_styles)
        self.assertIn(".market-sparkline", self.final_styles)

    def test_final_navigation_is_neutral_and_keeps_accessible_target_size(self):
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr))", self.final_styles)
        self.assertIn("min-height: 56px", self.final_styles)
        self.assertIn(".bottom-nav button.active::before", self.final_styles)
        self.assertIn("background: #f5f5f3", self.final_styles)
        self.assertIn("env(safe-area-inset-bottom, 0px)", self.styles)

    def test_ui_uses_one_svg_icon_system_not_emoji_navigation(self):
        self.assertIn("export function Icon", self.ui)
        self.assertIn('viewBox="0 0 24 24"', self.ui)
        self.assertNotIn("⌂", self.ui)
        self.assertNotIn("◫", self.ui)
        self.assertNotIn("≋", self.ui)

    def test_overview_and_fvg_show_exchange_aware_24h_change(self):
        self.assertIn("market.get(item.key)", self.overview)
        self.assertIn("PriceChange value={snapshot?.priceChange24hPct}", self.overview)
        self.assertIn("exchangeLabels[item.exchange]", self.overview)
        self.assertIn("market.get(item.key)", self.fvg)
        self.assertIn("PriceChange value={snapshot?.priceChange24hPct}", self.fvg)

    def test_fvg_editor_preserves_required_controls(self):
        for value in ("Bullish", "Bearish", "Confirmed FVG", "Price filter", "FVG size filter"):
            self.assertIn(value, self.fvg)
        for timeframe in ('"15m"', '"1h"', '"4h"', '"1d"'):
            self.assertIn(timeframe, (SRC / "ui.tsx").read_text(encoding="utf-8"))

    def test_funding_and_settings_keep_existing_semantics(self):
        self.assertIn("15–2880", self.funding)
        self.assertIn("notifyPositive", self.funding)
        self.assertIn("notifyNegative", self.funding)
        self.assertIn("exchangeOrder.map", self.funding)
        self.assertIn('language: "ru"', self.settings)
        self.assertIn('language: "en"', self.settings)
        self.assertIn('messageMode: "compact"', self.settings)
        self.assertIn('messageMode: "detailed"', self.settings)


if __name__ == "__main__":
    unittest.main()
