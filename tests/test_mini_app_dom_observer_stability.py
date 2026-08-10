import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "telegram-mini-app" / "src" / "i18n.ts"
NAVIGATION = ROOT / "telegram-mini-app" / "src" / "navigationAccessibility.ts"


class MiniAppDomObserverStabilityTests(unittest.TestCase):
    def setUp(self):
        self.i18n = I18N.read_text(encoding="utf-8")
        self.navigation = NAVIGATION.read_text(encoding="utf-8")

    def test_language_root_attributes_are_written_only_when_changed(self):
        self.assertIn(
            "if (document.documentElement.lang !== currentLanguage)",
            self.i18n,
        )
        self.assertIn(
            "if (document.documentElement.dataset.language !== currentLanguage)",
            self.i18n,
        )

    def test_navigation_attributes_observed_by_i18n_are_idempotent(self):
        self.assertIn("function setAttributeIfChanged(", self.navigation)
        self.assertIn(
            'setAttributeIfChanged(trigger, "aria-label", copy.profileTrigger)',
            self.navigation,
        )
        self.assertIn(
            'setAttributeIfChanged(nav, "aria-label", copy.primaryNavigation)',
            self.navigation,
        )
        self.assertIn(
            'setAttributeIfChanged(sheet, "aria-label", copy.profileDialog)',
            self.navigation,
        )
        self.assertIn(
            'setAttributeIfChanged(close, "aria-label", copy.closeProfile)',
            self.navigation,
        )

    def test_observers_keep_the_cross_observed_attributes_explicit(self):
        self.assertIn('attributeFilter: ["class", "data-language"]', self.navigation)
        self.assertIn('"aria-label"', self.i18n)


if __name__ == "__main__":
    unittest.main()
