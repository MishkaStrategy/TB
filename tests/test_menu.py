import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import BOT_COMMANDS, configure_bot_interface
from alerts.fvg_store import FvgAlertSettings
from handlers.auth import PUBLIC_ACCESS_ENABLED, authorized
from handlers.fvg_alert import build_fvg_stats_period_menu
from handlers.menu import build_fvg_settings_menu, build_main_menu


class EnabledSettings:
    def is_enabled(self, chat_id):
        return chat_id == 42

    def is_pre_enabled(self, chat_id):
        return False


class MenuTests(unittest.TestCase):
    def test_main_menu_contains_fvg_actions_and_funding(self):
        keyboard = build_main_menu(42, settings=EnabledSettings()).inline_keyboard
        labels = [row[0].text for row in keyboard]
        callbacks = [row[0].callback_data for row in keyboard]

        self.assertEqual(labels, ["🔔 Настройки FVG 15м", "📊 Статистика FVG", "💸 Фандинг"])
        self.assertIn("🔔 Настройки FVG 15м", labels)
        self.assertIn("📊 Статистика FVG", labels)
        self.assertIn("menu:fvg-settings", callbacks)
        self.assertIn("menu:fvg-stats", callbacks)
        self.assertIn("menu:funding", callbacks)

    def test_fvg_filter_buttons_show_enabled_and_paused_status(self):
        class Settings:
            def user(self, chat_id):
                return {
                    "enabled": True,
                    "notify_confirmed_fvg": True,
                    "notify_pre_fvg": True,
                    "bullish_enabled": True,
                    "bearish_enabled": True,
                    "symbols": {
                        "BTCUSDT": {
                            "price_filter": {"enabled": True},
                            "size_filter": {"enabled": False},
                        }
                    },
                }

        rows = build_fvg_settings_menu(42, Settings()).inline_keyboard
        labels = [button.text for row in rows for button in row]
        self.assertIn("✅ Цена", labels)
        self.assertIn("⏸️ 📏 Размер FVG", labels)

    def test_real_price_and_size_changes_refresh_settings_menu_status(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.add_symbol(42, "BTCUSDT")

            settings.set_price_filter(42, "BTCUSDT", "60000", "90000")
            labels = [
                button.text
                for row in build_fvg_settings_menu(42, settings).inline_keyboard
                for button in row
            ]
            self.assertIn("✅ Цена", labels)
            self.assertIn("⏸️ 📏 Размер FVG", labels)

            settings.set_size_filter(42, "BTCUSDT", "0.1", None, unit="PERCENT")
            labels = [
                button.text
                for row in build_fvg_settings_menu(42, settings).inline_keyboard
                for button in row
            ]
            self.assertIn("✅ Цена", labels)
            self.assertIn("✅ 📏 Размер FVG", labels)

    def test_fvg_statistics_period_menu_contains_all_periods(self):
        buttons = build_fvg_stats_period_menu(30).inline_keyboard[0]

        self.assertEqual(
            [button.text for button in buttons],
            ["7 дней", "✓ 30 дней", "Всё время"],
        )
        self.assertEqual(
            [button.callback_data for button in buttons],
            ["menu:fvg-stats:7", "menu:fvg-stats:30", "menu:fvg-stats:all"],
        )


class TelegramMenuButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_configures_compact_telegram_menu_button(self):
        bot = SimpleNamespace(
            set_my_commands=AsyncMock(),
            set_chat_menu_button=AsyncMock(),
        )

        await configure_bot_interface(SimpleNamespace(bot=bot))

        bot.set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
        bot.set_chat_menu_button.assert_awaited_once()
        self.assertEqual(BOT_COMMANDS[0].command, "menu")


class PublicAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_handlers_are_public_while_admin_panel_is_disabled(self):
        calls = []

        @authorized
        async def handler(update, context):
            calls.append((update, context))

        update = SimpleNamespace(effective_user=None, effective_message=None)
        await handler(update, "context")

        self.assertTrue(PUBLIC_ACCESS_ENABLED)
        self.assertEqual(calls, [(update, "context")])
