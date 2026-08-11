import unittest
from tempfile import TemporaryDirectory

from alerts.fvg_store import FvgAlertSettings
from handlers.start import _enable_confirmed_fvg_for_new_user


class StartDefaultsTests(unittest.TestCase):
    def test_new_user_gets_confirmed_fvg_module_without_default_instrument(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")

            created = _enable_confirmed_fvg_for_new_user(42, settings)
            user = settings.user(42)

            self.assertTrue(created)
            self.assertTrue(user["enabled"])
            self.assertTrue(user["notify_confirmed_fvg"])
            self.assertFalse(user["notify_pre_fvg"])
            self.assertEqual(user["symbols"], {})
            self.assertEqual(settings.enabled_chat_ids(), frozenset({42}))
            self.assertEqual(settings.active_symbols(), frozenset())
            self.assertEqual(settings.active_markets(), ())

    def test_repeated_start_does_not_override_manual_opt_out(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            self.assertTrue(_enable_confirmed_fvg_for_new_user(42, settings))
            settings.set_enabled(42, False)

            created = _enable_confirmed_fvg_for_new_user(42, settings)

            self.assertFalse(created)
            self.assertFalse(settings.is_enabled(42))
            self.assertEqual(settings.enabled_chat_ids(), frozenset())
            self.assertEqual(settings.user(42)["symbols"], {})


if __name__ == "__main__":
    unittest.main()
