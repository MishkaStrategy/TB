import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from alerts.telegram_outbox import OutboxRetryPolicy, TelegramOutboxWorker
from database.outbox_compat import FvgOutboxCompatibility
from database.telegram_outbox import TelegramOutboxStore


UTC = timezone.utc


class SuccessfulBot:
    async def send_message(self, **kwargs):
        return SimpleNamespace(message_id=1)


class LegacyDeliveryMetrics:
    def __init__(self, path):
        self.path = path

    def increment_health(self, key, amount=1):
        return None

    def mark_delivered(self, chat_id, event_id):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "DELETE FROM outbox WHERE event_id=? AND chat_id=?",
                (event_id, str(chat_id)),
            )
            connection.commit()

    def abandon_delivery(self, chat_id, event_id):
        self.mark_delivered(chat_id, event_id)


class OutboxCompatibilityRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_cleanup_removes_orphaned_domain_sync(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.sqlite3"
            started = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE outbox(
                        event_id TEXT, chat_id TEXT, message_text TEXT,
                        attempts INTEGER, next_attempt_at TEXT, last_error TEXT,
                        created_at TEXT, updated_at TEXT,
                        PRIMARY KEY(event_id, chat_id)
                    )
                    """
                )
                timestamp = started.isoformat()
                connection.execute(
                    "INSERT INTO outbox VALUES ('e1', '42', 'hello', 0, ?, NULL, ?, ?)",
                    (timestamp, timestamp, timestamp),
                )
                connection.commit()

            store = TelegramOutboxStore(path)
            compatibility = FvgOutboxCompatibility(path)
            compatibility.copy_legacy_to_v2(store, default_ttl_seconds=None)
            worker = TelegramOutboxWorker(
                store,
                metrics=LegacyDeliveryMetrics(path),
                compatibility=compatibility,
                policy=OutboxRetryPolicy(terminal_retention_days=1),
            )

            self.assertEqual(await worker.drain(SuccessfulBot(), now=started), 1)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM telegram_outbox_domain_sync"
                    ).fetchone()[0],
                    1,
                )

            await worker.drain(
                SuccessfulBot(),
                now=started + timedelta(days=2),
            )

            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM telegram_outbox").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM telegram_outbox_domain_sync"
                    ).fetchone()[0],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
