import unittest
from unittest.mock import patch

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

    def bot(self, value):
        del value
        return self

    def post_init(self, callback):
        del callback
        return self

    def post_stop(self, callback):
        del callback
        return self

    def post_shutdown(self, callback):
        del callback
        return self

    def build(self):
        return self.application


class GracefulRestartExitTests(unittest.TestCase):
    def run_main(self, restart_requested):
        application = FakeApplication()
        builder = FakeBuilder(application)
        patches = (
            patch.object(bot, "TELEGRAM_TOKEN", "token"),
            patch("bot.get_runtime_coordinator", return_value=None),
            patch("bot.Application.builder", return_value=builder),
            patch("bot.LocalizedExtBot", return_value=object()),
            patch("bot.build_settings_handlers", return_value=[]),
            patch("bot.build_fvg_filter_handlers", return_value=[]),
            patch("bot.build_funding_alert_handlers", return_value=[]),
            patch(
                "bot.graceful_restart_requested",
                return_value=restart_requested,
            ),
        )
        for context in patches:
            context.start()
        try:
            bot.main()
        finally:
            for context in reversed(patches):
                context.stop()
        return application

    def test_normal_polling_return_remains_clean_exit(self):
        application = self.run_main(False)
        self.assertEqual(application.run_calls, 1)

    def test_self_requested_restart_exits_with_failure_after_polling(self):
        with self.assertRaises(SystemExit) as captured:
            self.run_main(True)
        self.assertEqual(captured.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
