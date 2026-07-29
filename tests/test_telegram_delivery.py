import sqlite3
import unittest
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


class Forbidden(Exception):
    pass


class RetryAfter(Exception):
    def __init__(self, seconds):
        self.retry_after = seconds
        super().__init__(f"Retry after {seconds}")


class TimedOut(Exception):
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

    def test_timeout_is_temporary(self):
        decision = classify_telegram_error(TimedOut("request timed out"))
        self.assertTrue(decision.retryable)
        self.assertEqual(decision.code, "timeout")

    def test_message_not_modified_is_ignorable(self):
        decision = classify_telegram_error(BadRequest("Message is not modified"))
        self.assertEqual(decision.kind, TelegramErrorKind.IGNORABLE)
        self.assertFalse(decision.retryable)


class TelegramDeliveryRegistryTests(unittest.TestCase):
    def test_blocked_status_discards_backlog_and_recovers_on_interaction(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(path)
            with sqlite3.connect(path) as connection:
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

            decision = classify_telegram_error(
                Forbidden("Forbidden: bot was blocked by the user")
            )
            result = registry.record_failure(42, decision, Forbidden("blocked"))
            self.assertEqual(result["status"], TelegramDeliveryStatus.BLOCKED.value)
            self.assertEqual(result["discarded_outbox"], 2)
            self.assertFalse(registry.can_deliver(42))

            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
                    1,
                )

            recovered = registry.record_interaction(42, 42)
            self.assertTrue(recovered["recovered"])
            self.assertEqual(recovered["status"], TelegramDeliveryStatus.ACTIVE.value)
            self.assertEqual(recovered["consecutive_failures"], 0)
            self.assertTrue(registry.can_deliver(42))

    def test_temporary_failure_does_not_discard_outbox(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            registry = TelegramDeliveryRegistry(path)
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE outbox(event_id TEXT, chat_id TEXT, message_text TEXT)"
                )
                connection.execute(
                    "INSERT INTO outbox VALUES ('one', '42', 'pending')"
                )

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
            registry = TelegramDeliveryRegistry(Path(directory) / "events.sqlite3")
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
