import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from alerts.telegram_outbox import TelegramOutboxWorker
from database.telegram_outbox import TelegramOutboxStore


class BackloggedCompatibility:
    def sync_terminal(self, store, metrics, *, limit=500, now=None):
        return limit


class SuccessfulBot:
    def __init__(self):
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(message_id=1)


class OutboxDomainSyncBacklogTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_sync_batch_pauses_maintenance_and_claims(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                event_id="e1",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="fvg:e1:42",
            )
            worker = TelegramOutboxWorker(
                store,
                compatibility=BackloggedCompatibility(),
            )
            bot = SuccessfulBot()

            self.assertEqual(await worker.drain(bot, limit=100), 0)
            self.assertEqual(bot.calls, 0)
            self.assertEqual(store.get(item["id"])["status"], "pending")
            self.assertEqual(worker.last_claimed_count, 0)


if __name__ == "__main__":
    unittest.main()
