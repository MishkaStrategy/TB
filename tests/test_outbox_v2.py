import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from alerts.telegram_outbox import OutboxRetryPolicy, TelegramOutboxWorker
from database.outbox_compat import FvgOutboxCompatibility
from database.telegram_outbox import OutboxStatus, TelegramOutboxStore


UTC = timezone.utc


class RetryAfter(Exception):
    def __init__(self, seconds):
        self.retry_after = seconds
        super().__init__(f"Retry after {seconds}")


class Forbidden(Exception):
    pass


class TimedOut(Exception):
    pass


class SuccessfulBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=123)


class FailingBot:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    async def send_message(self, **kwargs):
        self.calls += 1
        raise self.error


class TelegramOutboxStoreTests(unittest.TestCase):
    def test_enqueue_is_idempotent_and_claim_is_exclusive(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            first = store.enqueue(
                notification_type="fvg",
                event_id="event-1",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="fvg:event-1:42",
            )
            second = store.enqueue(
                notification_type="fvg",
                event_id="event-1",
                chat_id=42,
                payload={"text": "different"},
                idempotency_key="fvg:event-1:42",
            )
            self.assertTrue(first["inserted"])
            self.assertFalse(second["inserted"])
            self.assertEqual(first["id"], second["id"])

            claimed = store.claim_due(worker_id="one", limit=10)
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0]["status"], OutboxStatus.PROCESSING.value)
            self.assertEqual(store.claim_due(worker_id="two", limit=10), [])

    def test_expired_items_are_not_claimed(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "old"},
                idempotency_key="old",
                expires_at=now - timedelta(seconds=1),
                now=now - timedelta(minutes=5),
            )
            self.assertEqual(store.claim_due(worker_id="one", now=now), [])
            self.assertEqual(
                store.get(item["id"])["status"],
                OutboxStatus.EXPIRED.value,
            )

    def test_stale_processing_becomes_dead_letter_instead_of_duplicate_retry(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            start = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="stale",
                now=start,
            )
            store.claim_due(worker_id="crashed", lease_seconds=10, now=start)
            self.assertEqual(
                store.claim_due(
                    worker_id="new",
                    now=start + timedelta(seconds=11),
                ),
                [],
            )
            recovered = store.get(item["id"])
            self.assertEqual(
                recovered["status"],
                OutboxStatus.DEAD_LETTER.value,
            )
            self.assertEqual(
                recovered["last_error_code"],
                "delivery_outcome_unknown",
            )

    def test_migrates_legacy_outbox_once(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.sqlite3"
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
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    "INSERT INTO outbox VALUES ('e1', '42', 'hello', 1, ?, 'timeout', ?, ?)",
                    (now, now, now),
                )
                connection.commit()
            store = TelegramOutboxStore(path)
            result = store.migrate_legacy_fvg_outbox(default_ttl_seconds=3600)
            self.assertEqual(result["migrated"], 1)
            self.assertEqual(
                store.counts()[OutboxStatus.RETRY_SCHEDULED.value],
                1,
            )
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    0,
                )


class LegacyDeliveryMetrics:
    def __init__(self, path):
        self.path = path
        self.counters = {}

    def increment_health(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount

    def mark_delivered(self, chat_id, event_id):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                "DELETE FROM outbox WHERE event_id=? AND chat_id=?",
                (event_id, str(chat_id)),
            )
            connection.commit()

    def abandon_delivery(self, chat_id, event_id):
        self.mark_delivered(chat_id, event_id)


class TelegramOutboxWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_persists_message_id_and_attempt(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="success",
            )
            bot = SuccessfulBot()
            worker = TelegramOutboxWorker(store)
            self.assertEqual(await worker.drain(bot), 1)
            result = store.get(item["id"])
            self.assertEqual(result["status"], OutboxStatus.DELIVERED.value)
            self.assertEqual(result["telegram_message_id"], "123")
            self.assertEqual(len(store.attempts(item["id"])), 1)

    async def test_retry_after_schedules_exact_delay(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            start = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="retry",
                now=start,
            )
            worker = TelegramOutboxWorker(store)
            await worker.drain(FailingBot(RetryAfter(17)), now=start)
            result = store.get(item["id"])
            self.assertEqual(
                result["status"],
                OutboxStatus.RETRY_SCHEDULED.value,
            )
            self.assertEqual(
                datetime.fromisoformat(result["next_attempt_at"]),
                start + timedelta(seconds=17),
            )

    async def test_blocked_is_permanent(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="blocked",
            )
            worker = TelegramOutboxWorker(store)
            await worker.drain(
                FailingBot(Forbidden("bot was blocked by the user"))
            )
            self.assertEqual(
                store.get(item["id"])["status"],
                OutboxStatus.FAILED_PERMANENT.value,
            )

    async def test_ambiguous_timeout_goes_to_dead_letter_without_retry(self):
        with TemporaryDirectory() as directory:
            store = TelegramOutboxStore(Path(directory) / "outbox.sqlite3")
            item = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "hello"},
                idempotency_key="timeout",
            )
            worker = TelegramOutboxWorker(store)
            bot = FailingBot(TimedOut("read timed out"))
            await worker.drain(bot)
            self.assertEqual(bot.calls, 1)
            self.assertEqual(
                store.get(item["id"])["status"],
                OutboxStatus.DEAD_LETTER.value,
            )
            self.assertEqual(store.claim_due(worker_id="other"), [])

    async def test_terminal_state_synchronizes_legacy_rollback_mirror(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "outbox.sqlite3"
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
                now = datetime.now(UTC).isoformat()
                connection.execute(
                    "INSERT INTO outbox VALUES ('e1', '42', 'hello', 0, ?, NULL, ?, ?)",
                    (now, now, now),
                )
                connection.commit()
            store = TelegramOutboxStore(path)
            compatibility = FvgOutboxCompatibility(path)
            result = compatibility.copy_legacy_to_v2(
                store,
                default_ttl_seconds=3600,
            )
            self.assertEqual(result["copied"], 1)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    1,
                )
            worker = TelegramOutboxWorker(
                store,
                metrics=LegacyDeliveryMetrics(path),
                compatibility=compatibility,
            )
            self.assertEqual(await worker.drain(SuccessfulBot()), 1)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM telegram_outbox_domain_sync"
                    ).fetchone()[0],
                    1,
                )

    def test_retry_policy_has_bounded_jitter(self):
        policy = OutboxRetryPolicy(
            base_delay_seconds=10,
            max_delay_seconds=100,
            jitter_ratio=0.2,
        )
        self.assertEqual(policy.retry_delay(1, random_value=0), 8)
        self.assertAlmostEqual(policy.retry_delay(1, random_value=1), 12)
        self.assertEqual(policy.retry_delay(10, random_value=1), 100)


if __name__ == "__main__":
    unittest.main()
