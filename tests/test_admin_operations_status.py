import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers import admin_settings


class AdminOperationsStatusTests(unittest.IsolatedAsyncioTestCase):
    def test_admin_keyboard_contains_read_only_operations_button(self):
        keyboard = admin_settings.admin_keyboard(public_access=False)
        buttons = [
            button
            for row in keyboard.inline_keyboard
            for button in row
        ]
        operations = [
            button
            for button in buttons
            if button.callback_data == "admin:operations"
        ]
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].text, "⚙️ Операции")

    def test_formats_runtime_tasks_and_database_growth(self):
        snapshot = {
            "available": True,
            "captured_at": "2026-07-29T12:00:00+00:00",
            "lifecycle": {
                "available": True,
                "state": {
                    "status": "running",
                    "pid": 321,
                    "last_phase": "post_init",
                    "updated_at": "2026-07-29T11:59:00+00:00",
                    "shutdown_outcome": None,
                    "last_error_class": None,
                    "last_error_message": None,
                },
            },
            "tasks": {
                "available": True,
                "total": 3,
                "counts": {"failed": 1, "running": 1, "success": 1},
                "overdue_count": 1,
                "expired_lease_count": 1,
                "problems": [
                    {
                        "task_name": "funding-quarter-hour",
                        "status": "failed",
                        "expired_lease": False,
                        "overdue": True,
                        "consecutive_failures": 2,
                        "last_error_code": "exchange_timeout",
                    },
                    {
                        "task_name": "fvg-rest-recovery",
                        "status": "running",
                        "expired_lease": True,
                        "overdue": False,
                        "consecutive_failures": 0,
                        "last_error_code": None,
                    },
                ],
            },
            "databases": {
                "available": True,
                "latest": [
                    {
                        "database_key": "fvg",
                        "available": True,
                        "main_bytes": 1024,
                        "wal_bytes": 512,
                        "shm_bytes": 0,
                        "captured_at": "2026-07-29T11:00:00+00:00",
                        "error_message": None,
                    }
                ],
                "growth_24h": [
                    {
                        "database_key": "fvg",
                        "main_bytes_delta": 512,
                        "used_bytes_delta": -128,
                    }
                ],
            },
        }

        text = admin_settings.format_operations_status(snapshot)

        self.assertIn("⚙️ Операционное состояние", text)
        self.assertIn("Статус: работает", text)
        self.assertIn("funding-quarter-hour: ошибка", text)
        self.assertIn("ошибок подряд 2", text)
        self.assertIn("fvg-rest-recovery: работает · lease", text)
        self.assertIn("FVG: доступна · 1.5 КБ", text)
        self.assertIn("файл +512 Б, used −128 Б", text)
        self.assertLess(len(text), 4096)

    def test_formats_missing_operational_tables_without_error(self):
        snapshot = {
            "available": True,
            "captured_at": "2026-07-29T12:00:00+00:00",
            "lifecycle": {"available": False, "state": None},
            "tasks": {
                "available": False,
                "total": 0,
                "counts": {},
                "overdue_count": 0,
                "expired_lease_count": 0,
                "problems": [],
            },
            "databases": {
                "available": False,
                "latest": [],
                "growth_24h": [],
            },
        }

        text = admin_settings.format_operations_status(snapshot)

        self.assertIn("lifecycle history: нет данных", text)
        self.assertIn("registry: нет данных", text)
        self.assertIn("observability: нет данных", text)

    def test_formats_unavailable_runtime_database(self):
        text = admin_settings.format_operations_status(
            {
                "available": False,
                "error_message": "database_file_missing",
            }
        )

        self.assertIn("Runtime SQLite недоступна", text)
        self.assertIn("database_file_missing", text)

    async def test_operations_callback_edits_message_with_read_only_status(self):
        query = SimpleNamespace(
            data="admin:operations",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=123),
        )
        with (
            patch("handlers.admin_settings.is_admin", return_value=True),
            patch(
                "handlers.admin_settings.format_operations_status",
                return_value="operations-status",
            ),
            patch("handlers.admin_settings.admin_keyboard", return_value="keyboard"),
        ):
            await admin_settings.admin_callback(update, SimpleNamespace())

        query.answer.assert_awaited_once_with()
        query.edit_message_text.assert_awaited_once_with(
            "operations-status",
            reply_markup="keyboard",
        )


if __name__ == "__main__":
    unittest.main()
