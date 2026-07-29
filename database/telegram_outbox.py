"""Generic SQLite outbox with explicit states, leases and idempotency."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path


UTC = timezone.utc


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    DELIVERED = "delivered"
    FAILED_PERMANENT = "failed_permanent"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


TERMINAL_STATUSES = frozenset(
    {
        OutboxStatus.DELIVERED.value,
        OutboxStatus.FAILED_PERMANENT.value,
        OutboxStatus.EXPIRED.value,
        OutboxStatus.CANCELLED.value,
        OutboxStatus.DEAD_LETTER.value,
    }
)
DUE_STATUSES = (
    OutboxStatus.PENDING.value,
    OutboxStatus.RETRY_SCHEDULED.value,
)


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _load_json(value: str | None, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


class TelegramOutboxStore:
    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")
    MAINTENANCE_INTERVAL = timedelta(days=1)

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_outbox (
                    id TEXT PRIMARY KEY,
                    notification_type TEXT NOT NULL,
                    event_type TEXT,
                    event_id TEXT,
                    user_id TEXT,
                    chat_id TEXT NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'send_message',
                    telegram_message_id TEXT,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    last_attempt_at TEXT,
                    processing_started_at TEXT,
                    lease_until TEXT,
                    worker_id TEXT,
                    last_error_class TEXT,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    delivered_at TEXT,
                    finalized_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_outbox_due
                    ON telegram_outbox(status, next_attempt_at, lease_until);
                CREATE INDEX IF NOT EXISTS idx_telegram_outbox_chat_status
                    ON telegram_outbox(chat_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_telegram_outbox_finalized
                    ON telegram_outbox(status, finalized_at);

                CREATE TABLE IF NOT EXISTS telegram_outbox_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outbox_id TEXT NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    started_at TEXT,
                    finished_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    error_class TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    FOREIGN KEY(outbox_id) REFERENCES telegram_outbox(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_outbox_attempt_item
                    ON telegram_outbox_attempts(outbox_id, attempt_no);

                CREATE TABLE IF NOT EXISTS telegram_outbox_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["attempts"] = int(result["attempts"])
        result["max_attempts"] = int(result["max_attempts"])
        result["payload"] = _load_json(result.pop("payload_json"), {})
        return result

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def enqueue(
        self,
        *,
        notification_type: str,
        chat_id: int | str,
        payload: dict,
        idempotency_key: str,
        event_type: str | None = None,
        event_id: str | None = None,
        user_id: int | str | None = None,
        operation: str = "send_message",
        expires_at: datetime | None = None,
        max_attempts: int = 8,
        now: datetime | None = None,
    ) -> dict:
        current = _utc(now)
        timestamp = current.isoformat()
        item_id = str(uuid.uuid4())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO telegram_outbox(
                    id, notification_type, event_type, event_id, user_id,
                    chat_id, operation, payload_json, idempotency_key, status,
                    attempts, max_attempts, next_attempt_at, created_at,
                    updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    str(notification_type),
                    event_type,
                    event_id,
                    str(user_id) if user_id is not None else None,
                    str(chat_id),
                    operation,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    str(idempotency_key),
                    OutboxStatus.PENDING.value,
                    max(1, int(max_attempts)),
                    timestamp,
                    timestamp,
                    timestamp,
                    _iso(expires_at),
                ),
            )
            inserted = cursor.rowcount == 1
            row = connection.execute(
                "SELECT * FROM telegram_outbox WHERE idempotency_key = ?",
                (str(idempotency_key),),
            ).fetchone()
        result = self._row(row)
        result["inserted"] = inserted
        return result

    def migrate_legacy_fvg_outbox(
        self,
        *,
        default_ttl_seconds: int = 3600,
        max_attempts: int = 8,
        now: datetime | None = None,
    ) -> dict:
        current = _utc(now)
        migrated = skipped_delivered = 0
        with self._connect() as connection:
            if not self._table_exists(connection, "outbox"):
                return {"migrated": 0, "skipped_delivered": 0}
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT event_id, chat_id, message_text, attempts,
                       next_attempt_at, last_error, created_at, updated_at
                FROM outbox
                ORDER BY created_at
                """
            ).fetchall()
            has_deliveries = self._table_exists(connection, "deliveries")
            for row in rows:
                if has_deliveries and connection.execute(
                    "SELECT 1 FROM deliveries WHERE event_id=? AND chat_id=?",
                    (row["event_id"], row["chat_id"]),
                ).fetchone():
                    skipped_delivered += 1
                    connection.execute(
                        "DELETE FROM outbox WHERE event_id=? AND chat_id=?",
                        (row["event_id"], row["chat_id"]),
                    )
                    continue
                try:
                    created = datetime.fromisoformat(row["created_at"])
                except (TypeError, ValueError):
                    created = current
                created = _utc(created)
                expires = created + timedelta(seconds=max(1, int(default_ttl_seconds)))
                status = (
                    OutboxStatus.EXPIRED.value
                    if expires <= current
                    else (
                        OutboxStatus.RETRY_SCHEDULED.value
                        if int(row["attempts"] or 0) > 0
                        else OutboxStatus.PENDING.value
                    )
                )
                finalized = current.isoformat() if status == OutboxStatus.EXPIRED.value else None
                item_id = str(uuid.uuid4())
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO telegram_outbox(
                        id, notification_type, event_type, event_id, chat_id,
                        operation, payload_json, idempotency_key, status,
                        attempts, max_attempts, next_attempt_at, last_error_code,
                        last_error_message, created_at, updated_at, expires_at,
                        finalized_at
                    ) VALUES (?, 'fvg', 'legacy_fvg', ?, ?, 'send_message', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        row["event_id"],
                        row["chat_id"],
                        json.dumps({"text": row["message_text"]}, ensure_ascii=False),
                        f"fvg:{row['event_id']}:{row['chat_id']}",
                        status,
                        int(row["attempts"] or 0),
                        max(1, int(max_attempts)),
                        row["next_attempt_at"] or current.isoformat(),
                        "legacy_delivery_error" if row["last_error"] else None,
                        row["last_error"],
                        row["created_at"] or current.isoformat(),
                        row["updated_at"] or current.isoformat(),
                        expires.isoformat(),
                        finalized,
                    ),
                )
                migrated += max(cursor.rowcount, 0)
                connection.execute(
                    "DELETE FROM outbox WHERE event_id=? AND chat_id=?",
                    (row["event_id"], row["chat_id"]),
                )
            connection.commit()
        return {"migrated": migrated, "skipped_delivered": skipped_delivered}

    @staticmethod
    def _record_attempt(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        outcome: str,
        error_class: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        finished_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO telegram_outbox_attempts(
                outbox_id, attempt_no, started_at, finished_at, outcome,
                error_class, error_code, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                int(row["attempts"]),
                row["last_attempt_at"],
                finished_at,
                outcome,
                error_class,
                error_code,
                error_message[:2000] if error_message else None,
            ),
        )

    def _recover_stale_unlocked(
        self,
        connection: sqlite3.Connection,
        timestamp: str,
        *,
        limit: int,
    ) -> int:
        rows = connection.execute(
            """
            SELECT * FROM telegram_outbox
            WHERE status=? AND lease_until IS NOT NULL AND lease_until <= ?
            ORDER BY lease_until LIMIT ?
            """,
            (OutboxStatus.PROCESSING.value, timestamp, max(1, int(limit))),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                UPDATE telegram_outbox
                SET status=?, worker_id=NULL, lease_until=NULL,
                    last_error_class='ProcessRestart',
                    last_error_code='delivery_outcome_unknown',
                    last_error_message='Processing lease expired before outcome was persisted',
                    finalized_at=?, updated_at=?
                WHERE id=? AND status=?
                """,
                (
                    OutboxStatus.DEAD_LETTER.value,
                    timestamp,
                    timestamp,
                    row["id"],
                    OutboxStatus.PROCESSING.value,
                ),
            )
            self._record_attempt(
                connection,
                row,
                outcome=OutboxStatus.DEAD_LETTER.value,
                error_class="ProcessRestart",
                error_code="delivery_outcome_unknown",
                error_message="Processing lease expired before outcome was persisted",
                finished_at=timestamp,
            )
        return len(rows)

    def _expire_due_unlocked(
        self,
        connection: sqlite3.Connection,
        timestamp: str,
        *,
        limit: int,
    ) -> int:
        rows = connection.execute(
            """
            SELECT id FROM telegram_outbox
            WHERE status IN (?, ?) AND expires_at IS NOT NULL AND expires_at <= ?
            ORDER BY expires_at LIMIT ?
            """,
            (*DUE_STATUSES, timestamp, max(1, int(limit))),
        ).fetchall()
        if rows:
            connection.executemany(
                """
                UPDATE telegram_outbox
                SET status=?, last_error_code='notification_expired',
                    finalized_at=?, updated_at=?
                WHERE id=? AND status IN (?, ?)
                """,
                [
                    (
                        OutboxStatus.EXPIRED.value,
                        timestamp,
                        timestamp,
                        row["id"],
                        *DUE_STATUSES,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def claim_due(
        self,
        *,
        worker_id: str,
        limit: int = 100,
        lease_seconds: float = 120,
        now: datetime | None = None,
    ) -> list[dict]:
        current = _utc(now)
        timestamp = current.isoformat()
        lease_until = (current + timedelta(seconds=max(1, lease_seconds))).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._recover_stale_unlocked(connection, timestamp, limit=limit)
            self._expire_due_unlocked(connection, timestamp, limit=limit)
            rows = connection.execute(
                """
                SELECT id FROM telegram_outbox
                WHERE status IN (?, ?) AND next_attempt_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY next_attempt_at, created_at
                LIMIT ?
                """,
                (*DUE_STATUSES, timestamp, timestamp, max(1, int(limit))),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                connection.executemany(
                    """
                    UPDATE telegram_outbox
                    SET status=?, attempts=attempts+1, last_attempt_at=?,
                        processing_started_at=?, lease_until=?, worker_id=?,
                        updated_at=?
                    WHERE id=? AND status IN (?, ?)
                    """,
                    [
                        (
                            OutboxStatus.PROCESSING.value,
                            timestamp,
                            timestamp,
                            lease_until,
                            worker_id,
                            timestamp,
                            item_id,
                            *DUE_STATUSES,
                        )
                        for item_id in ids
                    ],
                )
                placeholders = ",".join("?" for _ in ids)
                claimed = connection.execute(
                    f"SELECT * FROM telegram_outbox WHERE id IN ({placeholders}) AND worker_id=? ORDER BY next_attempt_at, created_at",
                    (*ids, worker_id),
                ).fetchall()
            else:
                claimed = []
            connection.commit()
        return [self._row(row) for row in claimed]

    def _finish_processing(
        self,
        item_id: str,
        worker_id: str,
        *,
        status: OutboxStatus,
        error: BaseException | None = None,
        error_code: str | None = None,
        next_attempt_at: datetime | None = None,
        telegram_message_id: int | str | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM telegram_outbox WHERE id=? AND status=? AND worker_id=?",
                (item_id, OutboxStatus.PROCESSING.value, worker_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            terminal = status.value in TERMINAL_STATUSES
            connection.execute(
                """
                UPDATE telegram_outbox
                SET status=?, telegram_message_id=COALESCE(?, telegram_message_id),
                    next_attempt_at=COALESCE(?, next_attempt_at),
                    last_error_class=?, last_error_code=?, last_error_message=?,
                    worker_id=NULL, lease_until=NULL,
                    delivered_at=CASE WHEN ?=? THEN ? ELSE delivered_at END,
                    finalized_at=CASE WHEN ? THEN ? ELSE NULL END,
                    updated_at=?
                WHERE id=? AND status=? AND worker_id=?
                """,
                (
                    status.value,
                    str(telegram_message_id) if telegram_message_id is not None else None,
                    _iso(next_attempt_at),
                    type(error).__name__ if error is not None else None,
                    error_code,
                    str(error)[:2000] if error is not None else None,
                    status.value,
                    OutboxStatus.DELIVERED.value,
                    timestamp,
                    int(terminal),
                    timestamp,
                    timestamp,
                    item_id,
                    OutboxStatus.PROCESSING.value,
                    worker_id,
                ),
            )
            self._record_attempt(
                connection,
                row,
                outcome=status.value,
                error_class=type(error).__name__ if error is not None else None,
                error_code=error_code,
                error_message=str(error) if error is not None else None,
                finished_at=timestamp,
            )
            connection.commit()
        return True

    def mark_delivered(self, item_id, worker_id, *, telegram_message_id=None, now=None):
        return self._finish_processing(
            item_id,
            worker_id,
            status=OutboxStatus.DELIVERED,
            telegram_message_id=telegram_message_id,
            now=now,
        )

    def schedule_retry(self, item_id, worker_id, *, next_attempt_at, error, error_code, now=None):
        return self._finish_processing(
            item_id,
            worker_id,
            status=OutboxStatus.RETRY_SCHEDULED,
            next_attempt_at=next_attempt_at,
            error=error,
            error_code=error_code,
            now=now,
        )

    def mark_permanent(self, item_id, worker_id, *, error, error_code, now=None):
        return self._finish_processing(
            item_id,
            worker_id,
            status=OutboxStatus.FAILED_PERMANENT,
            error=error,
            error_code=error_code,
            now=now,
        )

    def mark_dead_letter(self, item_id, worker_id, *, error, error_code, now=None):
        return self._finish_processing(
            item_id,
            worker_id,
            status=OutboxStatus.DEAD_LETTER,
            error=error,
            error_code=error_code,
            now=now,
        )

    def mark_cancelled(self, item_id, worker_id, *, error_code, now=None):
        return self._finish_processing(
            item_id,
            worker_id,
            status=OutboxStatus.CANCELLED,
            error=RuntimeError(error_code),
            error_code=error_code,
            now=now,
        )

    def maintenance(
        self,
        *,
        terminal_retention_days: int = 30,
        batch_size: int = 500,
        now: datetime | None = None,
        force_cleanup: bool = False,
    ) -> dict:
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stale = self._recover_stale_unlocked(connection, timestamp, limit=batch_size)
            expired = self._expire_due_unlocked(connection, timestamp, limit=batch_size)
            row = connection.execute(
                "SELECT value FROM telegram_outbox_meta WHERE key='last_terminal_cleanup_at'"
            ).fetchone()
            last_cleanup = None
            if row:
                try:
                    last_cleanup = _utc(datetime.fromisoformat(row["value"]))
                except (TypeError, ValueError):
                    pass
            cleanup_due = (
                force_cleanup
                or last_cleanup is None
                or current - last_cleanup >= self.MAINTENANCE_INTERVAL
            )
            cleaned = 0
            if cleanup_due:
                cutoff = (
                    current - timedelta(days=max(1, int(terminal_retention_days)))
                ).isoformat()
                placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
                rows = connection.execute(
                    f"SELECT id FROM telegram_outbox WHERE status IN ({placeholders}) AND finalized_at < ? ORDER BY finalized_at LIMIT ?",
                    (*sorted(TERMINAL_STATUSES), cutoff, max(1, int(batch_size))),
                ).fetchall()
                if rows:
                    connection.executemany(
                        "DELETE FROM telegram_outbox WHERE id=?",
                        [(row["id"],) for row in rows],
                    )
                    cleaned = len(rows)
                connection.execute(
                    """
                    INSERT INTO telegram_outbox_meta(key, value)
                    VALUES ('last_terminal_cleanup_at', ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (timestamp,),
                )
            connection.commit()
        return {
            "stale_dead_lettered": stale,
            "expired": expired,
            "cleaned": cleaned,
        }

    def get(self, item_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_outbox WHERE id=?",
                (item_id,),
            ).fetchone()
        return self._row(row) if row is not None else None

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM telegram_outbox GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def attempts(self, item_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM telegram_outbox_attempts WHERE outbox_id=? ORDER BY attempt_no, id",
                (item_id,),
            ).fetchall()
        return [dict(row) for row in rows]
