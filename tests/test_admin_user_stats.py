import unittest
from datetime import datetime, timezone

from handlers.admin import admin_keyboard, format_user_stats


class _Registry:
    def users(self):
        return {
            "1": {
                "name": "Алиса",
                "username": "alice",
                "last_seen": "2026-08-02T09:00:00+00:00",
            },
            "2": {
                "name": "Борис",
                "username": None,
                "last_seen": "2026-07-28T09:00:00+00:00",
            },
            "3": {
                "name": "Без даты",
                "username": "nodate",
                "last_seen": "invalid",
            },
        }


class AdminUserStatsTests(unittest.TestCase):
    def test_admin_keyboard_contains_user_statistics(self):
        markup = admin_keyboard(public_access=False)
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]

        self.assertEqual(callbacks.count("admin:users"), 1)

    def test_format_user_stats_counts_activity_windows(self):
        text = format_user_stats(
            _Registry(),
            now=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        )

        self.assertIn("Всего пользователей: 3", text)
        self.assertIn("Активны за 24 часа: 1", text)
        self.assertIn("Активны за 7 дней: 2", text)
        self.assertIn("Активны за 30 дней: 2", text)
        self.assertIn("• Алиса @alice —", text)
        self.assertIn("• Без даты @nodate — —", text)


if __name__ == "__main__":
    unittest.main()
