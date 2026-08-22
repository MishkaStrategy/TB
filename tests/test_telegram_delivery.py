import sqlite3
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.telegram_errors import (
    TelegramDeliveryStatus,
    TelegramErrorKind,
    TelegramErrorDecision,
    classify_telegram_error,
)
from database.telegram_delivery import TelegramDeliveryRegistry
from database.telegram_outbox import OutboxStatus, TelegramOutboxStore


class Forbidden(Exception):
    pass


class RetryAfter(Exception):
    def __init__(self, seconds):
        self.retry_after = seconds
        super().__init__(f"Retry after {seconds}")


class TimedOut(Exception):
    pass


class ConnectTimeout(Exception):
    pass


class BadRequest(Exception):
    pass


class TelegramErrorClassifierTests(unittest.TestCase):
    def test_blocked_user_is_permanent(self):
        decision = classify_telegram_error(
            Forbidden("Forbidden: bot was blocked by the user")
        )
        self.assertEqual(decision.kind, TelegramErrorKind.PERMANENT)
        self.assertEqual(decision.code, "bot_blocked_by_user")
        self.assertEqual(decision.delivery_status, TelegramDeliveryStatus.BLOCKED)
        self.assertFalse(decision.retryable)

    def test_rate_limit_uses_retry_after(self):
        decision = classify_telegram_error(RetryAfter(timedelta(seconds=17)))
        self.assertEqual(decision.kind, TelegramErrorKind.TEMPORARY)
        self.assertEqual(decision.code, "rate_limited")
        self.assertEqual(decision.retry_after_seconds, 17)

    def test_unknown_timeout_is_ambiguous_but_legacy_retryable(self):
        decision = classify_telegram_error(TimedOut("request timed out"))
        self.assertTrue(decision.retryable)
        self.assertTrue(decision.ambiguous_delivery)
        self.assertEqual(decision.code, "timeout")

    def test_connect_timeout_is_safe_to_retry(self):
        error = TimedOut("connection timed out")
        error.__cause__ = ConnectTimeout("connection not established")
        decision = classify_telegram_error(error)
        self.assertTrue(decision.retryable)
        self.assertFalse(decision.ambiguous_delivery)
        self.assertEqual(decision.code, "timeout_before_send")

    def test_message_not_modified_is_ignorable(self):
        decision = classify_telegram_error(BadRequest("Message is not modified"))
        self.assertEqual(decision.kind, TelegramErrorKind.IGNORABLE)
        self.assertFalse(decision.retryable)


class TelegramDeliveryRegistryTests(unittest.TestCase):
    def test_blocked_status_discards_backlog_and_recovers_on_interaction(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=True,
            )
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE outbox(event_id TEXT, chat_id TEXT, message_text TEXT)"
                )
                connection.executemany(
                    "INSERT INTO outbox VALUES (?, ?, ?)",
                    [
                        ("one", "42", "old"),
                        ("two", "42", "old"),
                        ("three", "7", "keep"),
                    ],
                )
                connection.commit()

            decision = classify_telegram_error(
                Forbidden("Forbidden: bot was blocked by the user")
            )
            result = registry.record_failure(42, decision, Forbidden("blocked"))
            self.assertEqual(result["status"], TelegramDeliveryStatus.BLOCKED.value)
            self.assertEqual(result["discarded_outbox"], 2)
            self.assertFalse(registry.can_deliver(42))

            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    1,
                )

            recovered = registry.record_interaction(42, 42)
            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["status"], TelegramDeliveryStatus.ACTIVE.value)
            self.assertEqual(recovered["consecutive_failures"], 0)
            self.assertTrue(registry.can_deliver(42))

    def test_blocked_status_cancels_v2_pending_and_retry_backlog(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = TelegramOutboxStore(path)
            pending = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "old pending"},
                idempotency_key="blocked-pending",
            )
            retrying = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "old retry"},
                idempotency_key="blocked-retry",
            )
            other = store.enqueue(
                notification_type="fvg",
                chat_id=7,
                payload={"text": "keep"},
                idempotency_key="other-user",
            )
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    UPDATE telegram_outbox
                    SET status=?, next_attempt_at='2099-01-01T00:00:00+00:00'
                    WHERE id=?
                    """,
                    (OutboxStatus.RETRY_SCHEDULED.value, retrying["id"]),
                )
                connection.commit()

            registry = TelegramDeliveryRegistry(path)
            decision = classify_telegram_error(
                Forbidden("Forbidden: bot was blocked by the user")
            )
            result = registry.record_failure(42, decision, Forbidden("blocked"))

            self.assertEqual(result["discarded_outbox"], 2)
            self.assertEqual(
                store.get(pending["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )
            self.assertEqual(
                store.get(retrying["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )
            self.assertEqual(
                store.get(other["id"])["status"],
                OutboxStatus.PENDING.value,
            )

            recovered = registry.record_interaction(42, 42)
            self.assertTrue(recovered["recovered"])
            self.assertEqual(
                store.get(pending["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )
            self.assertEqual(
                store.get(retrying["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )

    def test_recovery_cancels_stale_v2_backlog_from_older_version(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = TelegramOutboxStore(path)
            legacy_registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=False,
            )
            decision = classify_telegram_error(
                Forbidden("Forbidden: bot was blocked by the user")
            )
            legacy_registry.record_failure(
                42,
                decision,
                Forbidden("blocked"),
                discard_outbox=False,
            )
            stale = store.enqueue(
                notification_type="fvg",
                chat_id=42,
                payload={"text": "must never replay"},
                idempotency_key="legacy-stale-v2",
            )
            self.assertEqual(
                store.get(stale["id"])["status"],
                OutboxStatus.PENDING.value,
            )

            registry = TelegramDeliveryRegistry(path)
            recovered = registry.record_interaction(42, 42)

            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["discarded_outbox"], 1)
            self.assertEqual(
                store.get(stale["id"])["status"],
                OutboxStatus.CANCELLED.value,
            )
            self.assertTrue(registry.can_deliver(42))

    def test_tracking_only_records_status_without_discarding_backlog(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=False,
            )
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE outbox(event_id TEXT, chat_id TEXT, message_text TEXT)"
                )
                connection.execute(
                    "INSERT INTO outbox VALUES ('one', '42', 'pending')"
                )
                connection.commit()

            decision = classify_telegram_error(
                Forbidden("Forbidden: bot was blocked by the user")
            )
            result = registry.record_failure(42, decision, Forbidden("blocked"))

            self.assertEqual(result["status"], TelegramDeliveryStatus.BLOCKED.value)
            self.assertEqual(result["discarded_outbox"], 0)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    1,
                )

    def test_temporary_failure_does_not_discard_outbox(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(
                path,
                discard_outbox_by_default=True,
            )
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE outbox(event_id TEXT, chat_id TEXT, message_text TEXT)"
                )
                connection.execute(
                    "INSERT INTO outbox VALUES ('one', '42', 'pending')"
                )
                connection.commit()

            decision = classify_telegram_error(TimedOut("timeout"))
            result = registry.record_failure(42, decision, TimedOut("timeout"))
            self.assertEqual(
                result["status"],
                TelegramDeliveryStatus.TEMPORARILY_UNAVAILABLE.value,
            )
            self.assertEqual(result["discarded_outbox"], 0)
            self.assertTrue(registry.can_deliver(42))

            success = registry.record_success(42)
            self.assertEqual(success["status"], TelegramDeliveryStatus.ACTIVE.value)
            self.assertEqual(success["consecutive_failures"], 0)
            self.assertIsNone(success["last_error_code"])

    def test_summary_counts_statuses(self):
        with TemporaryDirectory() as directory:
            registry = TelegramDeliveryRegistry(
                Path(directory) / "events.sqlite3",
                discard_outbox_by_default=False,
            )
            registry.record_interaction(1, 1)
            decision = TelegramErrorDecision(
                kind=TelegramErrorKind.PERMANENT,
                code="bot_blocked_by_user",
                retryable=False,
                delivery_status=TelegramDeliveryStatus.BLOCKED,
            )
            registry.record_failure(2, decision, Forbidden("blocked"))
            self.assertEqual(registry.summary(), {"active": 1, "blocked": 1})


if __name__ == "__main__":
    unittest.main()
