import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bot


class RecordingActivityRegistry:
    def __init__(self):
        self.calls = []

    def touch(self, user):
        self.calls.append((user.id, threading.get_ident()))


class BotActivityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_track_user_activity_reuses_shared_registry_off_loop(self):
        registry = RecordingActivityRegistry()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42),
        )
        event_loop_thread = threading.get_ident()

        with (
            patch.object(bot, "USER_ACTIVITY_REGISTRY", registry),
            patch.object(bot, "DELIVERY_REGISTRY", None),
        ):
            await bot.track_user_activity(update, SimpleNamespace())
            await bot.track_user_activity(update, SimpleNamespace())

        self.assertEqual([user_id for user_id, _ in registry.calls], [42, 42])
        self.assertTrue(
            all(thread_id != event_loop_thread for _, thread_id in registry.calls)
        )


if __name__ == "__main__":
    unittest.main()
