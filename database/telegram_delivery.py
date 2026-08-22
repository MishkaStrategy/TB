"""Persistent Telegram delivery status per chat."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alerts.telegram_errors import TelegramDeliveryStatus, TelegramErrorDecision


UTC = timezone.utc
FINAL_UNAVAILABLE_STATUSES = frozenset(
    {
        TelegramDeliveryStatus.BLOCKED,
        TelegramDeliveryStatus.DEACTIVATED,
        TelegramDeliveryStatus.SUSPENDED,
    }
)


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now() -> datetime:
    return datetime.now(UTC)


class TelegramDeliveryRegistry:
    """Store chat-level Telegram reachability separately from access settings."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

    def __init__(
        self,
        path: str | os.PathLike | None = None,
        *,
        discard_outbox_by_default: bool | None = None,
    ):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Final-unavailable Telegram states are a delivery safety invariant.
        # Explicit False remains available only for injected compatibility tests;
        # production callers that omit the argument always suppress old backlog.
        self.discard_outbox_by_default = (
            True
            if discard_outbox_by_default is None
            else bool(discard_outbox_by_default)
        )
        self._prepare()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_delivery_profiles (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    blocked_at TEXT,
                    deactivated_at TEXT,
                    suspended_at TEXT,
                    recovered_at TEXT,
                    suspension_reason TEXT,
                    last_interaction_at TEXT,
                    status_changed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_delivery_status_updated
                    ON telegram_delivery_profiles(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_telegram_delivery_user
                    ON telegram_delivery_profiles(user_id);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None, chat_id: int | str) -> dict:
        if row is None:
            return {
                "chat_id": int(chat_id),
                "user_id": None,
                "status": TelegramDeliveryStatus.ACTIVE.value,
                "last_success_at": None,
                "last_error_at": None,
                "last_error_code": None,
                "last_error_message": None,
                "consecutive_failures": 0,
                "blocked_at": None,
                "deactivated_at": None,
                "suspended_at": None,
                "recovered_at": None,
                "suspension_reason": None,
                "last_interaction_at": None,
                "status_changed_at": None,
                "updated_at": None,
            }
        result = dict(row)
        result["chat_id"] = int(result["chat_id"])
        if result.get("user_id") is not None:
            result["user_id"] = int(result["user_id"])
        result["consecutive_failures"] = int(result["consecutive_failures"] or 0)
        return result

    def profile(self, chat_id: int | str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_delivery_profiles WHERE chat_id = ?",
                (str(chat_id),),
            ).fetchone()
        return self._row(row, chat_id)

    def can_deliver(self, chat_id: int | str) -> bool:
        try:
            status = TelegramDeliveryStatus(self.profile(chat_id)["status"])
        except ValueError:
            return False
        return status not in FINAL_UNAVAILABLE_STATUSES

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None

    @classmethod
    def _discard_outbox(
        cls,
        connection: sqlite3.Connection,
        chat_id: int | str,
        timestamp: str,
    ) -> int:
        """Terminalize queued work for a final-unavailable chat.

        Legacy FVG rows can be deleted because they have no explicit terminal
        state. Outbox V2 rows are retained as cancelled audit evidence. Rows
        already being processed are left to their worker so we never steal a
        processing lease or overwrite an in-flight delivery outcome.
        """
        discarded = 0
        if cls._table_exists(connection, "outbox"):
            cursor = connection.execute(
                "DELETE FROM outbox WHERE chat_id = ?",
                (str(chat_id),),
            )
            discarded += max(cursor.rowcount, 0)

        if cls._table_exists(connection, "telegram_outbox"):
            cursor = connection.execute(
                """
                UPDATE telegram_outbox
                SET status='cancelled',
                    last_error_class='DeliverySuppressed',
                    last_error_code='delivery_suppressed_inactive_user',
                    last_error_message='Queued notification cancelled because chat is unavailable',
                    finalized_at=?,
                    updated_at=?
                WHERE chat_id=? AND status IN ('pending', 'retry_scheduled')
                """,
                (timestamp, timestamp, str(chat_id)),
            )
            discarded += max(cursor.rowcount, 0)
        return discarded

    def record_success(
        self,
        chat_id: int | str,
        *,
        user_id: int | str | None = None,
        now: datetime | None = None,
    ) -> dict:
        timestamp = (now or _now()).astimezone(UTC).isoformat()
        previous = self.profile(chat_id)
        recovered = previous["status"] != TelegramDeliveryStatus.ACTIVE.value
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO telegram_delivery_profiles(
                    chat_id, user_id, status, last_success_at,
                    consecutive_failures, recovered_at, status_changed_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, telegram_delivery_profiles.user_id),
                    status = excluded.status,
                    last_success_at = excluded.last_success_at,
                    last_error_at = NULL,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    consecutive_failures = 0,
                    recovered_at = CASE
                        WHEN telegram_delivery_profiles.status <> excluded.status
                        THEN excluded.recovered_at
                        ELSE telegram_delivery_profiles.recovered_at
                    END,
                    suspension_reason = NULL,
                    status_changed_at = CASE
                        WHEN telegram_delivery_profiles.status <> excluded.status
                        THEN excluded.status_changed_at
                        ELSE telegram_delivery_profiles.status_changed_at
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    str(chat_id),
                    str(user_id) if user_id is not None else None,
                    TelegramDeliveryStatus.ACTIVE.value,
                    timestamp,
                    timestamp if recovered else None,
                    timestamp,
                    timestamp,
                ),
            )
        return self.profile(chat_id)

    def record_failure(
        self,
        chat_id: int | str,
        decision: TelegramErrorDecision,
        error: BaseException,
        *,
        user_id: int | str | None = None,
        now: datetime | None = None,
        discard_outbox: bool | None = None,
    ) -> dict:
        should_discard = (
            self.discard_outbox_by_default
            if discard_outbox is None
            else bool(discard_outbox)
        )
        timestamp = (now or _now()).astimezone(UTC).isoformat()
        previous = self.profile(chat_id)
        previous_status = previous["status"]
        new_status = (
            decision.delivery_status.value
            if decision.delivery_status is not None
            else previous_status
        )
        status_changed = new_status != previous_status
        blocked_at = timestamp if new_status == TelegramDeliveryStatus.BLOCKED.value else None
        deactivated_at = (
            timestamp if new_status == TelegramDeliveryStatus.DEACTIVATED.value else None
        )
        suspended_at = (
            timestamp if new_status == TelegramDeliveryStatus.SUSPENDED.value else None
        )
        suspension_reason = (
            decision.code
            if new_status == TelegramDeliveryStatus.SUSPENDED.value
            else None
        )
        discarded = 0

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO telegram_delivery_profiles(
                    chat_id, user_id, status, last_error_at, last_error_code,
                    last_error_message, consecutive_failures, blocked_at,
                    deactivated_at, suspended_at, suspension_reason,
                    status_changed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = COALESCE(excluded.user_id, telegram_delivery_profiles.user_id),
                    status = excluded.status,
                    last_error_at = excluded.last_error_at,
                    last_error_code = excluded.last_error_code,
                    last_error_message = excluded.last_error_message,
                    consecutive_failures = telegram_delivery_profiles.consecutive_failures + 1,
                    blocked_at = COALESCE(telegram_delivery_profiles.blocked_at, excluded.blocked_at),
                    deactivated_at = COALESCE(telegram_delivery_profiles.deactivated_at, excluded.deactivated_at),
                    suspended_at = COALESCE(telegram_delivery_profiles.suspended_at, excluded.suspended_at),
                    suspension_reason = excluded.suspension_reason,
                    status_changed_at = CASE
                        WHEN telegram_delivery_profiles.status <> excluded.status
                        THEN excluded.status_changed_at
                        ELSE telegram_delivery_profiles.status_changed_at
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    str(chat_id),
                    str(user_id) if user_id is not None else None,
                    new_status,
                    timestamp,
                    decision.code,
                    str(error)[:2000],
                    blocked_at,
                    deactivated_at,
                    suspended_at,
                    suspension_reason,
                    timestamp if status_changed else previous.get("status_changed_at") or timestamp,
                    timestamp,
                ),
            )
            if (
                should_discard
                and decision.delivery_status in FINAL_UNAVAILABLE_STATUSES
            ):
                discarded = self._discard_outbox(connection, chat_id, timestamp)
            connection.commit()

        result = self.profile(chat_id)
        result["discarded_outbox"] = discarded
        return result

    def record_interaction(
        self,
        user_id: int | str,
        chat_id: int | str,
        *,
        now: datetime | None = None,
        discard_outbox: bool | None = None,
    ) -> dict:
        should_discard = (
            self.discard_outbox_by_default
            if discard_outbox is None
            else bool(discard_outbox)
        )
        timestamp = (now or _now()).astimezone(UTC).isoformat()
        previous = self.profile(chat_id)
        previous_status = previous["status"]
        recovered = previous_status != TelegramDeliveryStatus.ACTIVE.value
        discard_backlog = (
            should_discard
            and previous_status in {
                status.value for status in FINAL_UNAVAILABLE_STATUSES
            }
        )
        discarded = 0

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Clean stale backlog before making the profile active. This also
            # upgrades databases produced by older versions that only deleted
            # the legacy `outbox` table on a block event.
            if discard_backlog:
                discarded = self._discard_outbox(connection, chat_id, timestamp)
            connection.execute(
                """
                INSERT INTO telegram_delivery_profiles(
                    chat_id, user_id, status, consecutive_failures,
                    recovered_at, last_interaction_at, status_changed_at,
                    updated_at
                ) VALUES (?, ?, ?, 0, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    status = excluded.status,
                    last_error_at = NULL,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    consecutive_failures = 0,
                    recovered_at = CASE
                        WHEN telegram_delivery_profiles.status <> excluded.status
                        THEN excluded.recovered_at
                        ELSE telegram_delivery_profiles.recovered_at
                    END,
                    suspension_reason = NULL,
                    last_interaction_at = excluded.last_interaction_at,
                    status_changed_at = CASE
                        WHEN telegram_delivery_profiles.status <> excluded.status
                        THEN excluded.status_changed_at
                        ELSE telegram_delivery_profiles.status_changed_at
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    str(chat_id),
                    str(user_id),
                    TelegramDeliveryStatus.ACTIVE.value,
                    timestamp if recovered else None,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()

        result = self.profile(chat_id)
        result.update(recovered=recovered, discarded_outbox=discarded)
        return result

    def summary(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM telegram_delivery_profiles
                GROUP BY status
                """
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}
