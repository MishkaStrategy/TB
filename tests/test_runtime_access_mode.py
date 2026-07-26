import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database.runtime_settings import RuntimeSettings
from handlers import auth
from handlers.admin import admin_keyboard


class RuntimeSettingsTests(unittest.TestCase):
    def test_uses_default_until_admin_saves_a_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = RuntimeSettings(Path(directory) / "runtime_settings.json")

            self.assertFalse(settings.public_access_enabled(default=False))
            self.assertTrue(settings.public_access_enabled(default=True))

    def test_toggle_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime_settings.json"
            settings = RuntimeSettings(path)

            self.assertTrue(settings.toggle_public_access(default=False))
            self.assertTrue(RuntimeSettings(path).public_access_enabled())
            self.assertFalse(settings.toggle_public_access(default=False))
            self.assertFalse(RuntimeSettings(path).public_access_enabled(default=True))

    def test_admin_keyboard_shows_current_mode(self):
        private_button = admin_keyboard(False).inline_keyboard[-1][0]
        public_button = admin_keyboard(True).inline_keyboard[-1][0]

        self.assertIn("приватный", private_button.text)
        self.assertIn("публичный", public_button.text)
        self.assertEqual("admin:toggle_access", private_button.callback_data)
        self.assertEqual("admin:toggle_access", public_button.callback_data)


class DynamicAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_mode_changes_without_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = RuntimeSettings(Path(directory) / "runtime_settings.json")
            calls = []

            async def handler(update, context):
                calls.append(update.effective_user.id)

            wrapped = auth.authorized(handler)
            message = SimpleNamespace(reply_text=AsyncMock())
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=999),
                effective_message=message,
            )

            with (
                patch.object(auth, "_RUNTIME_SETTINGS", settings),
                patch.object(auth, "is_authorized", return_value=False),
                patch.object(auth, "AccessRegistry") as registry_class,
            ):
                registry_class.return_value.is_allowed.return_value = False

                await wrapped(update, None)
                self.assertEqual([], calls)
                message.reply_text.assert_awaited_once_with(
                    "Доступ к боту не разрешён."
                )

                settings.set_public_access_enabled(True)
                message.reply_text.reset_mock()
                await wrapped(update, None)

                self.assertEqual([999], calls)
                message.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
