import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from handlers.admin_settings import admin_callback


class AdminSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_admin_cannot_execute_admin_callback(self):
        query = SimpleNamespace(
            data="admin:restart_confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
        )

        with patch("handlers.admin_settings.is_admin", return_value=False):
            await admin_callback(update, SimpleNamespace())

        query.answer.assert_awaited_once_with(
            "Эта панель доступна только администраторам.",
            show_alert=True,
        )
        query.edit_message_text.assert_not_awaited()

    async def test_admin_restart_requires_confirmed_callback(self):
        query = SimpleNamespace(
            data="admin:restart_confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=7),
        )
        loop = Mock()

        with (
            patch("handlers.admin_settings.is_admin", return_value=True),
            patch("handlers.admin_settings.asyncio.get_running_loop", return_value=loop),
        ):
            await admin_callback(update, SimpleNamespace())

        query.answer.assert_awaited_once_with()
        query.edit_message_text.assert_awaited_once_with("♻️ Бот перезапускается…")
        loop.call_later.assert_called_once()
        delay, callback = loop.call_later.call_args.args
        self.assertEqual(delay, 1.0)
        self.assertTrue(callable(callback))


if __name__ == "__main__":
    unittest.main()
