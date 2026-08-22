import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

    async def test_admin_restart_confirms_before_requesting_sigterm(self):
        events = []

        async def edit_message_text(text, **kwargs):
            events.append(("edit", text, kwargs))

        def request_restart():
            events.append(("sigterm",))

        query = SimpleNamespace(
            data="admin:restart_confirm",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(side_effect=edit_message_text),
            message=SimpleNamespace(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=7),
        )

        with (
            patch("handlers.admin_settings.is_admin", return_value=True),
            patch(
                "handlers.admin_settings.request_sigterm_restart",
                side_effect=request_restart,
            ) as restart,
            patch("handlers.admin_settings.os._exit") as hard_exit,
        ):
            await admin_callback(update, SimpleNamespace())

        query.answer.assert_awaited_once_with()
        restart.assert_called_once_with()
        hard_exit.assert_not_called()
        self.assertEqual(events[0][0], "edit")
        self.assertIn("завершает работу", events[0][1])
        self.assertEqual(events[1], ("sigterm",))

    async def test_admin_restart_signal_failure_is_reported_without_hard_exit(self):
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

        with (
            patch("handlers.admin_settings.is_admin", return_value=True),
            patch(
                "handlers.admin_settings.request_sigterm_restart",
                side_effect=OSError("signal denied"),
            ) as restart,
            patch("handlers.admin_settings.os._exit") as hard_exit,
        ):
            await admin_callback(update, SimpleNamespace())

        query.answer.assert_awaited_once_with()
        restart.assert_called_once_with()
        hard_exit.assert_not_called()
        self.assertEqual(query.edit_message_text.await_count, 2)
        first = query.edit_message_text.await_args_list[0].args[0]
        second = query.edit_message_text.await_args_list[1].args[0]
        self.assertIn("завершает работу", first)
        self.assertIn("Не удалось запросить перезапуск", second)
        self.assertIn("signal denied", second)


if __name__ == "__main__":
    unittest.main()
