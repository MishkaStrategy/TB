import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "telegram-mini-app" / "src"


class MiniAppFinalVisualAuditTests(unittest.TestCase):
    def test_audit_corrections_load_after_final_theme(self):
        main = (SRC / "main.tsx").read_text(encoding="utf-8")
        self.assertIn('import "./final-minimal.css";', main)
        self.assertIn('import "./final-minimal-audit.css";', main)
        self.assertGreater(
            main.index('import "./final-minimal-audit.css";'),
            main.index('import "./final-minimal.css";'),
        )

    def test_enabled_switch_is_semantic_green_not_neutral_primary(self):
        audit_css = (SRC / "final-minimal-audit.css").read_text(encoding="utf-8")
        self.assertIn(".tb-toggle.on", audit_css)
        self.assertIn("background: var(--success)", audit_css)

    def test_instrument_metadata_stacks_for_mobile_stability(self):
        audit_css = (SRC / "final-minimal-audit.css").read_text(encoding="utf-8")
        self.assertIn(".final-market-meta", audit_css)
        self.assertIn("flex-direction: column", audit_css)
        self.assertIn("align-items: flex-start", audit_css)

    def test_browser_smoke_covers_selected_mobile_breakpoints_and_primary_tabs(self):
        smoke = (ROOT / "telegram-mini-app" / "scripts" / "browser-smoke.mjs").read_text(encoding="utf-8")
        for width in ("360", "390", "430"):
            self.assertIn(width, smoke)
        for label in ("Home", "FVG", "Funding", "Alerts", "Settings"):
            self.assertIn(label, smoke)
        self.assertIn("horizontal overflow", smoke)
        self.assertIn("dirty/save", smoke)


if __name__ == "__main__":
    unittest.main()
