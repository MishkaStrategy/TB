import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "telegram-mini-app" / "src"
MAIN = SRC / "main.tsx"
ACCESSIBILITY = SRC / "navigationAccessibility.ts"
AUDIT_STYLES = SRC / "design-audit.css"


class MiniAppDesignAuditTests(unittest.TestCase):
    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")
        self.accessibility = ACCESSIBILITY.read_text(encoding="utf-8")
        self.styles = AUDIT_STYLES.read_text(encoding="utf-8")

    def test_accessibility_enhancer_is_started(self):
        self.assertIn('import { startNavigationAccessibility } from "./navigationAccessibility";', self.main)
        self.assertIn("startNavigationAccessibility();", self.main)

    def test_profile_dialog_has_keyboard_and_focus_management(self):
        self.assertIn('event.key === "Escape"', self.accessibility)
        self.assertIn('event.key !== "Tab"', self.accessibility)
        self.assertIn("focusableElements(sheet)", self.accessibility)
        self.assertIn('document.body.style.overflow = "hidden"', self.accessibility)
        self.assertIn('CLOSE_BUTTON_CLASS = "profile-sheet-close"', self.accessibility)
        self.assertIn('aria-haspopup", "dialog"', self.accessibility)
        self.assertIn('aria-current", "page"', self.accessibility)

    def test_navigation_labels_are_bilingual_and_specific(self):
        self.assertIn('primaryNavigation: "Основная навигация"', self.accessibility)
        self.assertIn('primaryNavigation: "Primary navigation"', self.accessibility)
        self.assertIn('closeProfile: "Закрыть меню профиля"', self.accessibility)
        self.assertIn('closeProfile: "Close profile menu"', self.accessibility)

    def test_audit_styles_load_last_and_raise_readability_floor(self):
        redesign = self.main.index('import "./navigation-redesign.css";')
        audit = self.main.index('import "./design-audit.css";')
        self.assertLess(redesign, audit)
        self.assertIn(".bottom-nav button small", self.styles)
        self.assertIn("font-size: 11px", self.styles)
        self.assertIn("width: 44px", self.styles)
        self.assertIn("height: 44px", self.styles)
        self.assertIn("@media (max-width: 360px)", self.styles)


if __name__ == "__main__":
    unittest.main()
