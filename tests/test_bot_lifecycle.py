import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bot


class FakeApplication:
    def __init__(self):
        self.handlers = []
        self.error_handlers = []
        self.run_calls = 0

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))

    def add_error_handler(self, callback):
        self.error_handlers.append(callback)

    def run_polling(self):
        self.run_calls += 1


class FakeBuilder:
    def __init__(self, application):
        self.application = application
        self.bot_value = None
        self.post_init_callback = None
        self.post_stop_callback = None
        self.post_shutdown_callback = None

    def bot(self, value):
        self.bot_value = value
        return self

    def post_init(self, callback):
        self.post_init_callback = callback
        return self

    def post_stop(self, callback):
        self.post_stop_callback = callback
        return self

    def post_shutdown(self, callback):
        self.post_shutdown_callback = callback
        return self

    def build(self):
        return self.application


class BotLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_init_marks_running_after_all_components_start(self):
        coordinator = MagicMock()
        application = SimpleNamespace()
        calls = []

        async def configure(app):
            calls.append(("configure", app))

        def schedule(app):
            calls.append(("schedule", app))

        async def start_stream(app):
            calls.append(("stream", app))

        async def start_watchdog(app):
            calls.append(("watchdog", app))

        with (
            patch("bot.get_runtime_coordinator", return_value=coordinator),
            patch("bot.configure_bot_interface", configure),
            patch("bot.schedule_fvg_alerts", schedule),
            patch("bot.start_fvg_stream", start_stream),
            patch("bot.start_process_watchdog", start_watchdog),
        ):
            await bot.post_init(application)

        self.assertEqual(
            [name for name, _ in calls],
            ["configure", "schedule", "stream", "watchdog"],
        )
        coordinator.begin_start.assert_called_once()
        coordinator.mark_running.assert_called_once()
        coordinator.mark_startup_failed.assert_not_called()

    async def test_post_init_failure_is_persisted_and_re_raised(self):
        coordinator = MagicMock()
        failure = RuntimeError("interface failed")
        with (
            patch("bot.get_runtime_coordinator", return_value=coordinator),
            patch("bot.configure_bot_interface", AsyncMock(side_effect=failure)),
        ):
            with self.assertRaisesRegex(RuntimeError, "interface failed"):
                await bot.post_init(SimpleNamespace())

        coordinator.mark_startup_failed.assert_called_once_with(failure)
        coordinator.mark_running.assert_not_called()

    async def test_post_stop_delegates_to_coordinator(self):
        coordinator = MagicMock()
        coordinator.stop = AsyncMock(return_value={"outcome": "clean"})
        application = SimpleNamespace()
        with patch("bot.get_runtime_coordinator", return_value=coordinator):
            result = await bot.post_stop(application)

        self.assertEqual(result, {"outcome": "clean"})
        coordinator.stop.assert_awaited_once_with(application)

    async def test_post_shutdown_preserves_legacy_cleanup_without_coordinator(self):
        application = SimpleNamespace()
        stop_watchdog = AsyncMock()
        stop_stream = AsyncMock()
        with (
            patch("bot.get_runtime_coordinator", return_value=None),
            patch("bot.stop_process_watchdog", stop_watchdog),
            patch("bot.stop_fvg_stream", stop_stream),
        ):
            await bot.post_shutdown(application)

        stop_watchdog.assert_awaited_once_with(application)
        stop_stream.assert_awaited_once_with(application)

    async def test_application_error_is_recorded(self):
        coordinator = MagicMock()
        failure = ValueError("handler failed")
        context = SimpleNamespace(error=failure)
        with (
            patch("bot.get_runtime_coordinator", return_value=coordinator),
            patch.object(bot.LOGGER, "error"),
        ):
            await bot.record_application_error(object(), context)

        coordinator.record_application_error.assert_called_once_with(failure)

    def test_main_registers_post_stop_only_when_lifecycle_is_active(self):
        application = FakeApplication()
        builder = FakeBuilder(application)
        coordinator = MagicMock()
        with (
            patch.object(bot, "TELEGRAM_TOKEN", "token"),
            patch("bot.get_runtime_coordinator", return_value=coordinator),
            patch("bot.Application.builder", return_value=builder),
            patch("bot.LocalizedExtBot", return_value=object()),
            patch("bot.build_settings_handlers", return_value=[]),
            patch("bot.build_fvg_filter_handlers", return_value=[]),
            patch("bot.build_funding_alert_handlers", return_value=[]),
        ):
            bot.main()

        self.assertIs(builder.post_init_callback, bot.post_init)
        self.assertIs(builder.post_stop_callback, bot.post_stop)
        self.assertIs(builder.post_shutdown_callback, bot.post_shutdown)
        self.assertEqual(application.error_handlers, [bot.record_application_error])
        self.assertEqual(application.run_calls, 1)
        coordinator.begin_start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
