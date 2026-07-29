"""Copy old terminal FVG events to a separate SQLite before runtime deletion."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc
ACTIVE_OUTBOX_STATUSES = (
    "pending",
    "processing",
    "retry_scheduled",
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


class FvgHistoryArchive:
    """Idempotently archive one bounded event batch before source deletion."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | os.PathLike = "data/archive/fvg_history.sqlite3",
        *,
        batch_size: int = 500,
    ):
        self.path = Path(path)
        self.batch_size = max(1, min(int(batch_size), 500))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()

    def _connect(self):
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _prepare(self):
        existed = self.path.exists()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS archive_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS archived_fvg_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    candle_c_close_time TEXT,
                    payload_json TEXT NOT NULL,
                    archived_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_archived_fvg_detected_at
                    ON archived_fvg_events(detected_at);
                CREATE INDEX IF NOT EXISTS idx_archived_fvg_symbol_detected
                    ON archived_fvg_events(symbol, detected_at);
                CREATE TABLE IF NOT EXISTS archived_fvg_deliveries (
                    event_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    PRIMARY KEY(event_id, chat_id),
                    FOREIGN KEY(event_id) REFERENCES archived_fvg_events(event_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_archived_delivery_time
                    ON archived_fvg_deliveries(delivered_at);
                CREATE TABLE IF NOT EXISTS fvg_archive_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cutoff_at TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    delivery_count INTEGER NOT NULL,
                    source_deleted_count INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT INTO archive_metadata(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(self.SCHEMA_VERSION),),
            )
        if not existed:
            os.chmod(self.path, 0o600)

    @staticmethod
    def _table_exists(connection, name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
            (str(name),),
        ).fetchone() is not None

    def _eligible_events(self, source, cutoff: str) -> list[dict]:
        telegram_guard = ""
        parameters: list[object] = [str(cutoff)]
        if self._table_exists(source, "telegram_outbox"):
            placeholders = ",".join("?" for _ in ACTIVE_OUTBOX_STATUSES)
            telegram_guard = f"""
                AND NOT EXISTS (
                    SELECT 1 FROM telegram_outbox AS telegram
                    WHERE telegram.event_id = event.event_id
                      AND telegram.status IN ({placeholders})
                )
            """
            parameters.extend(ACTIVE_OUTBOX_STATUSES)
        parameters.append(self.batch_size)
        rows = source.execute(
            f"""
            SELECT event.event_id, event.event_type, event.symbol,
                   event.timeframe, event.direction, event.detected_at,
                   event.candle_c_close_time, event.payload_json
            FROM events AS event
            WHERE event.detected_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM outbox AS legacy
                  WHERE legacy.event_id = event.event_id
              )
              {telegram_guard}
            ORDER BY event.detected_at, event.event_id
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _deliveries(source, event_ids: list[str]) -> list[dict]:
        if not event_ids:
            return []
        placeholders = ",".join("?" for _ in event_ids)
        rows = source.execute(
            f"""
            SELECT event_id, chat_id, delivered_at
            FROM deliveries
            WHERE event_id IN ({placeholders})
            ORDER BY event_id, chat_id
            """,
            event_ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def archive_and_delete(
        self,
        source: sqlite3.Connection,
        *,
        cutoff: datetime,
        now: datetime | None = None,
    ) -> dict:
        archived_at = _utc(now).isoformat()
        cutoff_at = _utc(cutoff).isoformat()
        events = self._eligible_events(source, cutoff_at)
        event_ids = [str(item["event_id"]) for item in events]
        deliveries = self._deliveries(source, event_ids)
        if not event_ids:
            return {
                "events_archived": 0,
                "deliveries_archived": 0,
                "source_deleted": 0,
                "batch_full": False,
            }

        with self._connect() as archive:
            archive.execute("BEGIN IMMEDIATE")
            archive.executemany(
                """
                INSERT INTO archived_fvg_events(
                    event_id, event_type, symbol, timeframe, direction,
                    detected_at, candle_c_close_time, payload_json, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                [
                    (
                        item["event_id"],
                        item["event_type"],
                        item["symbol"],
                        item["timeframe"],
                        item["direction"],
                        item["detected_at"],
                        item["candle_c_close_time"],
                        item["payload_json"],
                        archived_at,
                    )
                    for item in events
                ],
            )
            archive.executemany(
                """
                INSERT INTO archived_fvg_deliveries(
                    event_id, chat_id, delivered_at, archived_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_id, chat_id) DO NOTHING
                """,
                [
                    (
                        item["event_id"],
                        item["chat_id"],
                        item["delivered_at"],
                        archived_at,
                    )
                    for item in deliveries
                ],
            )
            placeholders = ",".join("?" for _ in event_ids)
            verified = int(
                archive.execute(
                    f"""
                    SELECT COUNT(*) FROM archived_fvg_events
                    WHERE event_id IN ({placeholders})
                    """,
                    event_ids,
                ).fetchone()[0]
            )
            if verified != len(event_ids):
                raise RuntimeError(
                    f"FVG archive verification failed: {verified} != {len(event_ids)}"
                )
            archive.commit()

        placeholders = ",".join("?" for _ in event_ids)
        cursor = source.execute(
            f"DELETE FROM events WHERE event_id IN ({placeholders})",
            event_ids,
        )
        deleted = max(0, int(cursor.rowcount))
        if deleted != len(event_ids):
            raise RuntimeError(
                f"FVG source deletion incomplete: {deleted} != {len(event_ids)}"
            )

        with self._connect() as archive:
            archive.execute(
                """
                INSERT INTO fvg_archive_runs(
                    cutoff_at, archived_at, event_count,
                    delivery_count, source_deleted_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cutoff_at,
                    archived_at,
                    len(event_ids),
                    len(deliveries),
                    deleted,
                ),
            )

        return {
            "events_archived": len(event_ids),
            "deliveries_archived": len(deliveries),
            "source_deleted": deleted,
            "batch_full": len(event_ids) >= self.batch_size,
        }

    def summary(self) -> dict:
        with self._connect() as connection:
            events = int(
                connection.execute(
                    "SELECT COUNT(*) FROM archived_fvg_events"
                ).fetchone()[0]
            )
            deliveries = int(
                connection.execute(
                    "SELECT COUNT(*) FROM archived_fvg_deliveries"
                ).fetchone()[0]
            )
            last_run = connection.execute(
                "SELECT * FROM fvg_archive_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "events": events,
            "deliveries": deliveries,
            "last_run": dict(last_run) if last_run is not None else None,
        }
