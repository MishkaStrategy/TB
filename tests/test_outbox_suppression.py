import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from alerts.telegram_outbox import TelegramOutboxWorker
from database.telegram_outbox import OutboxStatus, TelegramOutboxStore


class BlockedRegistry:
    def can_deliver(self, chat_id):
        return False

    def record_success(self, chat_id):
        return None

    def record_failure(self, chat_id, decision, error, **kwargs):
        return None


class SuccessfulBot:
    def __init__(self):
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(message_id=1)


class OutboxSuppressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracking_only_does_not_cancel_blocked_profile(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="tracking-only",
            )
            worker = TelegramOutboxWorker(
                store,
                delivery_registry=BlockedRegistry(),
                suppress_unavailable_users=False,
            )
            bot = SuccessfulBot()

            delivered = await worker.drain(bot)

            self.assertEqual(delivered, 1)
            self.assertEqual(bot.calls, 1)
            self.assertEqual(
                store.get(item["id"])["status"],
                OutboxStatus.DELIVERED.value,
            )

    async def test_suppression_cancels_without_calling_telegram(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="suppressed",
            )
            worker = TelegramOutboxWorker(
                store,
                delivery_registry=BlockedRegistry(),
                suppress_unavailable_users=True,
            )
            bot = SuccessfulBot()

            delivered = await worker.drain(bot)

            self.assertEqual(delivered, 0)
            self.assertEqual(bot.calls, 0)
            self.assertEqual(
                store.get(item["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )


if __name__ == "__main__":
    unittest.main()
