import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from alerts.fvg_store import FvgAlertSettings
from database.runtime_settings import RuntimeSettings
from handlers import auth
from handlers.admin import admin_keyboard
from operations.admin_service import disable_symbol_for_all_users


class AdminRuntimeSettingsTests(unittest.TestCase):
    def test_maintenance_mode_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            settings = RuntimeSettings(path)

            self.assertFalse(settings.maintenance_enabled())
            self.assertTrue(settings.toggle_maintenance())
            self.assertTrue(RuntimeSettings(path).maintenance_enabled())
            self.assertFalse(settings.toggle_maintenance())

    def test_admin_keyboard_shows_access_and_maintenance(self):
        keyboard = admin_keyboard(public_access=False, maintenance=True)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertTrue(any("приватный" in label for label in labels))
        self.assertTrue(any("Обслуживание: включено" in label for label in labels))

    def test_disable_symbol_for_all_users(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = FvgAlertSettings(Path(directory) / "settings.json")
            settings.set_enabled(1, True)
            settings.add_symbol(1, "ETHUSDT")
            settings.set_enabled(2, True)
            settings.add_symbol(2, "ETHUSDT")

            affected = disable_symbol_for_all_users(settings, "ethusdt")

            self.assertEqual(2, affected)
            self.assertNotIn("ETHUSDT", settings.active_symbols())


class MaintenanceAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_maintenance_blocks_non_admin_but_allows_admin(self):
        calls = []

        async def handler(update, context):
            calls.append(update.effective_user.id)

        wrapped = auth.authorized(handler)
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=123),
            effective_message=message,
        )

        with (
            patch.object(auth, "maintenance_enabled", return_value=True),
            patch.object(auth, "is_admin", return_value=False),
        ):
            await wrapped(update, None)

        self.assertEqual([], calls)
        message.reply_text.assert_awaited_once()

        message.reply_text.reset_mock()
        with (
            patch.object(auth, "maintenance_enabled", return_value=True),
            patch.object(auth, "is_admin", return_value=True),
            patch.object(auth, "public_access_enabled", return_value=True),
        ):
            await wrapped(update, None)

        self.assertEqual([123], calls)
        message.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
