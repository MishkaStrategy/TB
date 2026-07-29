"""Compatibility bridge between FVG's legacy outbox and generic Outbox V2."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.telegram_outbox import OutboxStatus, TERMINAL_STATUSES, TelegramOutboxStore


UTC = timezone.utc


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _utc(value=None):
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class FvgOutboxCompatibility:
    """Keep the old FVG outbox usable as a feature-flag rollback path."""

    def __init__(self, path):
        self.path = Path(path)
        self._prepare()

    def _connect(self):
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _prepare(self):
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS telegram_outbox_domain_sync (
                    outbox_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _table_exists(connection, table):
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def copy_legacy_to_v2(
        self,
        store: TelegramOutboxStore,
        *,
        default_ttl_seconds=3600,
        max_attempts=8,
        now=None,
    ):
        current = _utc(now)
        copied = skipped_delivered = 0
        with self._connect() as connection:
            if not self._table_exists(connection, "outbox"):
                return {"copied": 0, "skipped_delivered": 0}
            rows = connection.execute(
                """
                SELECT event_id, chat_id, message_text, attempts,
                       next_attempt_at, last_error, created_at, updated_at
                FROM outbox ORDER BY created_at
                """
            ).fetchall()
            has_deliveries = self._table_exists(connection, "deliveries")

        for row in rows:
            if has_deliveries:
                with self._connect() as connection:
                    delivered = connection.execute(
                        "SELECT 1 FROM deliveries WHERE event_id=? AND chat_id=?",
                        (row["event_id"], row["chat_id"]),
                    ).fetchone()
                if delivered:
                    skipped_delivered += 1
                    continue
            try:
                created = _utc(datetime.fromisoformat(row["created_at"]))
            except (TypeError, ValueError):
                created = current
            expires_at = (
                None
                if default_ttl_seconds is None
                else created + timedelta(
                    seconds=max(1, int(default_ttl_seconds))
                )
            )
            item = store.enqueue(
                notification_type="fvg",
                event_type="legacy_fvg",
                event_id=row["event_id"],
                chat_id=row["chat_id"],
                payload={"text": row["message_text"]},
                idempotency_key=f"fvg:{row['event_id']}:{row['chat_id']}",
                expires_at=expires_at,
                max_attempts=max_attempts,
                now=created,
            )
            copied += int(item["inserted"])
            if item["inserted"] and int(row["attempts"] or 0) > 0:
                with store._connect() as outbox_connection:
                    outbox_connection.execute(
                        """
                        UPDATE telegram_outbox
                        SET status=?, attempts=?, next_attempt_at=?,
                            last_error_code=?, last_error_message=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            OutboxStatus.RETRY_SCHEDULED.value,
                            int(row["attempts"] or 0),
                            row["next_attempt_at"] or current.isoformat(),
                            "legacy_delivery_error" if row["last_error"] else None,
                            row["last_error"],
                            row["updated_at"] or current.isoformat(),
                            item["id"],
                        ),
                    )
        return {"copied": copied, "skipped_delivered": skipped_delivered}

    def cleanup_orphaned_sync(self, *, limit=500):
        """Bound compatibility metadata after terminal outbox retention cleanup."""
        with self._connect() as connection:
            if not self._table_exists(connection, "telegram_outbox"):
                return 0
            rows = connection.execute(
                """
                SELECT synced.outbox_id
                FROM telegram_outbox_domain_sync AS synced
                LEFT JOIN telegram_outbox AS item ON item.id=synced.outbox_id
                WHERE item.id IS NULL
                ORDER BY synced.synced_at
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM telegram_outbox_domain_sync WHERE outbox_id=?",
                    [(row["outbox_id"],) for row in rows],
                )
        return len(rows)

    def sync_terminal(self, store, event_store, *, limit=500, now=None):
        del store
        self.cleanup_orphaned_sync(limit=limit)
        if event_store is None:
            return 0
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT item.id, item.status, item.event_id, item.chat_id
                FROM telegram_outbox AS item
                LEFT JOIN telegram_outbox_domain_sync AS synced
                  ON synced.outbox_id=item.id
                WHERE item.event_id IS NOT NULL
                  AND item.status IN ({placeholders})
                  AND synced.outbox_id IS NULL
                ORDER BY item.finalized_at, item.created_at
                LIMIT ?
                """,
                (*sorted(TERMINAL_STATUSES), max(1, int(limit))),
            ).fetchall()

        completed = 0
        timestamp = _utc(now).isoformat()
        for row in rows:
            if row["status"] == OutboxStatus.DELIVERED.value:
                method = getattr(event_store, "mark_delivered", None)
            else:
                method = getattr(event_store, "abandon_delivery", None)
            if not callable(method):
                continue
            method(row["chat_id"], row["event_id"])
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO telegram_outbox_domain_sync(
                        outbox_id, status, synced_at
                    ) VALUES (?, ?, ?)
                    """,
                    (row["id"], row["status"], timestamp),
                )
            completed += 1
        return completed
