import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

from alerts.fvg_store import FvgAlertSettings
from bot import BOT_COMMANDS, BOT_COMMANDS_EN, configure_bot_interface
from handlers.auth import PUBLIC_ACCESS_ENABLED, authorized
from handlers.donate import DONATION_ADDRESS, format_donation_text
from handlers.fvg_alert import build_fvg_stats_period_menu
from handlers.menu import build_fvg_settings_menu, build_main_menu, build_reply_menu
from handlers.settings import MENU_ALIASES, settings_keyboard


class EnabledSettings:
    def is_enabled(self, chat_id):
        return chat_id == 42


class MenuTests(unittest.TestCase):
    def test_main_menu_contains_supported_actions(self):
        keyboard = build_main_menu(42, settings=EnabledSettings()).inline_keyboard
        labels = [row[0].text for row in keyboard]
        callbacks = [row[0].callback_data for row in keyboard]
        self.assertEqual(
            labels,
            ["🔔 Настройки FVG", "📊 Статистика FVG", "💸 Фандинг", "⚙️ Настройки"],
        )
        self.assertIn("menu:fvg-settings", callbacks)
        self.assertIn("menu:fvg-stats", callbacks)
        self.assertIn("menu:funding", callbacks)
        self.assertIn("settings:open", callbacks)

    def test_reply_keyboard_contains_only_supported_sections(self):
        keyboard = build_reply_menu()
        self.assertEqual(
            [[button.text for button in row] for row in keyboard.keyboard],
            [
                ["📉 FVG", "💸 Фандинг"],
                ["🔔 Уведомления", "📊 Статистика"],
                ["⚙️ Настройки", "❤️ Донат"],
            ],
        )
        self.assertTrue(keyboard.resize_keyboard)
        self.assertTrue(keyboard.is_persistent)
        self.assertEqual(MENU_ALIASES["⚙️ Settings"], "settings")
        self.assertEqual(MENU_ALIASES["💸 Funding"], "funding")

    def test_settings_keyboard_contains_language_and_message_modes(self):
        keyboard = settings_keyboard(
            42,
            preferences={"language": "ru", "message_mode": "detailed"},
        ).inline_keyboard
        labels = [button.text for row in keyboard for button in row]
        callbacks = [button.callback_data for row in keyboard for button in row]
        self.assertIn("✅ Русский", labels)
        self.assertIn("✅ Подробные", labels)
        self.assertIn("settings:language:en", callbacks)
        self.assertIn("settings:mode:compact", callbacks)

    def test_donation_text_contains_supported_assets_and_wallet(self):
        text = format_donation_text()
        self.assertIn(DONATION_ADDRESS, text)
        self.assertIn("USDT", text)
        self.assertIn("ETH", text)
        self.assertIn("BNB", text)
        self.assertNotIn("Избран", text)

    def test_fvg_filter_buttons_show_enabled_and_paused_status(self):
        class Settings:
            def user(self, chat_id):
                return {
                    "enabled": True,
                    "notify_confirmed_fvg": True,
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
        callbacks = [button.callback_data for row in rows for button in row]
        self.assertIn("✅ Цена", labels)
        self.assertIn("⏸️ 📏 Размер FVG", labels)
        self.assertIn("📌 Инструменты", labels)
        self.assertIn("❓ FAQ по FVG", labels)
        self.assertIn("✅ Подтверждённые FVG", labels)
        self.assertNotIn("Пред-FVG BTC", labels)
        self.assertIn("fvg15:open", callbacks)
        self.assertIn("fvg15:faq:main", callbacks)

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
        self.assertEqual([button.text for button in buttons], ["7 дней", "✓ 30 дней", "Всё время"])
        self.assertEqual(
            [button.callback_data for button in buttons],
            ["menu:fvg-stats:7", "menu:fvg-stats:30", "menu:fvg-stats:all"],
        )


class TelegramMenuButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_configures_localized_telegram_commands(self):
        bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
        await configure_bot_interface(SimpleNamespace(bot=bot))
        self.assertEqual(
            bot.set_my_commands.await_args_list,
            [
                call(BOT_COMMANDS),
                call(BOT_COMMANDS, language_code="ru"),
                call(BOT_COMMANDS_EN, language_code="en"),
            ],
        )
        bot.set_chat_menu_button.assert_awaited_once()
        self.assertEqual(BOT_COMMANDS[0].command, "menu")
        commands = [command.command for command in BOT_COMMANDS]
        self.assertIn("funding", commands)
        self.assertIn("donate", commands)
        self.assertNotIn("fvg_pre_alert", commands)


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
