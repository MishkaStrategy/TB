import unittest
from unittest.mock import MagicMock, patch

import bot


class BotStartupFailureTests(unittest.TestCase):
    def test_application_construction_failure_is_recorded(self):
        coordinator = MagicMock()
        failure = RuntimeError("builder failed")
        with (
            patch.object(bot, "TELEGRAM_TOKEN", "token"),
            patch("bot.get_runtime_coordinator", return_value=coordinator),
            patch("bot.Application.builder", side_effect=failure),
        ):
            with self.assertRaisesRegex(RuntimeError, "builder failed"):
                bot.main()

        coordinator.begin_start.assert_called_once()
        coordinator.mark_process_failed.assert_called_once_with(failure)


if __name__ == "__main__":
    unittest.main()
