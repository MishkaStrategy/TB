"""SQLite/WAL persistence for FVG events, deliveries and retry outbox."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alerts.fvg_models import FvgEvent


UTC = timezone.utc
SCHEMA_VERSION = 2
_MIGRATION_LOCKS: dict[str, threading.Lock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3.Connection and then close explicitly."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now() -> datetime:
    return datetime.now(UTC)


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(value: str | None, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class FvgEventStore:
    """Transactional event store with WAL and automatic JSON migration."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")
    LEGACY_DEFAULT_PATH = Path("data/fvg_event_store.json")
    RETENTION_DAYS = 90
    PRUNE_INTERVAL = timedelta(days=1)

    def __init__(
        self,
        path: str | os.PathLike | None = None,
        *,
        legacy_json_path: str | os.PathLike | None = None,
    ):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.legacy_json_path = (
            Path(legacy_json_path)
            if legacy_json_path is not None
            else (self.LEGACY_DEFAULT_PATH if path is None else None)
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        resolved = str(self.path.resolve())
        with _MIGRATION_LOCKS_GUARD:
            lock = _MIGRATION_LOCKS.setdefault(resolved, threading.Lock())
        with lock:
            self._prepare_database()

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

    def _prepare_database(self) -> None:
        legacy_data = None
        if self.path.exists() and not self._is_sqlite(self.path):
            legacy_data = self._read_json(self.path)
            backup = self.path.with_suffix(self.path.suffix + ".legacy-json")
            backup.unlink(missing_ok=True)
            self.path.replace(backup)
        elif self.legacy_json_path and self.legacy_json_path.exists():
            legacy_data = self._read_json(self.legacy_json_path)

        with self._connect() as connection:
            self._create_schema(connection)

        if not legacy_data:
            return
        with self._connect() as connection:
            imported = connection.execute(
                "SELECT 1 FROM metadata WHERE key = 'legacy_json_imported'"
            ).fetchone()
            if imported is None:
                self._import_legacy(connection, legacy_data)
                connection.execute(
                    "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
                    ("legacy_json_imported", _dump(_now().isoformat())),
                )

    @staticmethod
    def _is_sqlite(path: Path) -> bool:
        try:
            with path.open("rb") as source:
                return source.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                candle_c_close_time TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_detected_at
                ON events(detected_at);
            CREATE INDEX IF NOT EXISTS idx_events_direction_type_detected
                ON events(direction, event_type, detected_at);
            CREATE TABLE IF NOT EXISTS deliveries (
                event_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                delivered_at TEXT NOT NULL,
                PRIMARY KEY(event_id, chat_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_deliveries_delivered_at
                ON deliveries(delivered_at);
            CREATE TABLE IF NOT EXISTS outbox (
                event_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(event_id, chat_id),
                FOREIGN KEY(event_id) REFERENCES events(event_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_due
                ON outbox(next_attempt_at, attempts);
            CREATE TABLE IF NOT EXISTS health (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value_json) VALUES (?, ?)",
            ("schema_version", _dump(SCHEMA_VERSION)),
        )

    def _import_legacy(self, connection: sqlite3.Connection, data: dict) -> None:
        events = data.get("events", {})
        if isinstance(events, dict):
            for event_id, payload in events.items():
                if not isinstance(payload, dict):
                    continue
                payload = {
                    **payload,
                    "event_id": payload.get("event_id", str(event_id)),
                }
                detected_at = payload.get("detected_at")
                if not isinstance(detected_at, str):
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO events(
                        event_id, event_type, symbol, timeframe, direction,
                        detected_at, candle_c_close_time, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(payload["event_id"]),
                        str(payload.get("event_type", "UNKNOWN")),
                        str(payload.get("symbol", "UNKNOWN")),
                        str(payload.get("timeframe", "15m")),
                        str(payload.get("direction", "UNKNOWN")),
                        detected_at,
                        payload.get("candle_c_close_time"),
                        _dump(payload),
                    ),
                )

        deliveries = data.get("deliveries", {})
        if isinstance(deliveries, dict):
            for event_id, recipients in deliveries.items():
                if not isinstance(recipients, dict):
                    continue
                exists = connection.execute(
                    "SELECT 1 FROM events WHERE event_id = ?", (str(event_id),)
                ).fetchone()
                if exists is None:
                    continue
                for chat_id, delivered_at in recipients.items():
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO deliveries(
                            event_id, chat_id, delivered_at
                        ) VALUES (?, ?, ?)
                        """,
                        (str(event_id), str(chat_id), str(delivered_at)),
                    )

        health = data.get("health", {})
        if isinstance(health, dict):
            connection.executemany(
                "INSERT OR REPLACE INTO health(key, value_json) VALUES (?, ?)",
                [(str(key), _dump(value)) for key, value in health.items()],
            )

    def record_event(self, event: FvgEvent) -> bool:
        payload = event.to_json()
        with self._connect() as connection:
            self._prune_if_due(connection, _now())
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_id, event_type, symbol, timeframe, direction,
                    detected_at, candle_c_close_time, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.symbol,
                    event.timeframe,
                    event.direction.value,
                    payload["detected_at"],
                    payload.get("candle_c_close_time"),
                    _dump(payload),
                ),
            )
            return cursor.rowcount == 1

    def enqueue_deliveries(
        self,
        event_id: str,
        chat_ids,
        message_text: str,
    ) -> int:
        now = _now().isoformat()
        inserted = 0
        with self._connect() as connection:
            for chat_id in chat_ids:
                delivered = connection.execute(
                    "SELECT 1 FROM deliveries WHERE event_id = ? AND chat_id = ?",
                    (event_id, str(chat_id)),
                ).fetchone()
                if delivered is not None:
                    continue
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO outbox(
                        event_id, chat_id, message_text, attempts,
                        next_attempt_at, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, 0, ?, NULL, ?, ?)
                    """,
                    (event_id, str(chat_id), message_text, now, now, now),
                )
                inserted += max(cursor.rowcount, 0)
        return inserted

    def due_deliveries(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> list[dict]:
        now_text = (now or _now()).astimezone(UTC).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, chat_id, message_text, attempts,
                       next_attempt_at, last_error, created_at
                FROM outbox
                WHERE next_attempt_at <= ?
                ORDER BY next_attempt_at, created_at
                LIMIT ?
                """,
                (now_text, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def delivery_needed(self, chat_id: int, event_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM deliveries WHERE event_id = ? AND chat_id = ?",
                (event_id, str(chat_id)),
            ).fetchone()
        return row is None

    def mark_delivered(self, chat_id: int, event_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO deliveries(event_id, chat_id, delivered_at)
                VALUES (?, ?, ?)
                """,
                (event_id, str(chat_id), _now().isoformat()),
            )
            connection.execute(
                "DELETE FROM outbox WHERE event_id = ? AND chat_id = ?",
                (event_id, str(chat_id)),
            )

    def mark_delivery_failed(
        self,
        chat_id: int,
        event_id: str,
        error: str,
        *,
        retry_after_seconds: float,
    ) -> None:
        retry_at = _now() + timedelta(seconds=max(1, retry_after_seconds))
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE outbox
                SET attempts = attempts + 1,
                    next_attempt_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE event_id = ? AND chat_id = ?
                """,
                (
                    retry_at.isoformat(),
                    str(error)[:2000],
                    _now().isoformat(),
                    event_id,
                    str(chat_id),
                ),
            )

    def abandon_delivery(self, chat_id: int, event_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM outbox WHERE event_id = ? AND chat_id = ?",
                (event_id, str(chat_id)),
            )

    def update_health(self, **values) -> None:
        if not values:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO health(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                [(str(key), _dump(value)) for key, value in values.items()],
            )

    def increment_health(self, key: str, amount: int = 1) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value_json FROM health WHERE key = ?", (key,)
            ).fetchone()
            current = _load(row["value_json"], 0) if row else 0
            try:
                value = int(current) + int(amount)
            except (TypeError, ValueError):
                value = int(amount)
            connection.execute(
                """
                INSERT INTO health(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, _dump(value)),
            )
            connection.commit()

    def health(self) -> dict:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM health"
            ).fetchall()
            event_count = connection.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            delivery_count = connection.execute(
                "SELECT COUNT(*) FROM deliveries"
            ).fetchone()[0]
            outbox_count = connection.execute(
                "SELECT COUNT(*) FROM outbox"
            ).fetchone()[0]
        result = {row["key"]: _load(row["value_json"]) for row in rows}
        result.update(
            events=event_count,
            deliveries=delivery_count,
            outbox=outbox_count,
        )
        return result

    def summary(self, days: int | None = 7) -> dict:
        cutoff = None if days is None else (_now() - timedelta(days=days)).isoformat()
        event_where = "" if cutoff is None else "WHERE detected_at >= ?"
        delivery_where = "" if cutoff is None else "WHERE event.detected_at >= ?"
        parameters = () if cutoff is None else (cutoff,)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT direction, event_type, COUNT(*) AS count
                FROM events {event_where}
                GROUP BY direction, event_type
                """,
                parameters,
            ).fetchall()
            deliveries = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM deliveries AS delivery
                JOIN events AS event ON event.event_id = delivery.event_id
                {delivery_where}
                """,
                parameters,
            ).fetchone()["count"]

        counts = {
            (row["direction"], row["event_type"]): int(row["count"])
            for row in rows
        }
        result: dict[str, object] = {}
        for direction in ("BULLISH", "BEARISH"):
            confirmed = counts.get((direction, "CONFIRMED_FVG"), 0)
            preliminary = counts.get((direction, "PRE_FVG"), 0)
            result[direction] = {
                "confirmed": confirmed,
                "pre": preliminary,
                "total": confirmed + preliminary,
            }
        result["deliveries"] = int(deliveries)
        return result

    def checkpoint(self, *, truncate: bool = False) -> tuple[int, int, int]:
        mode = "TRUNCATE" if truncate else "PASSIVE"
        with self._connect() as connection:
            row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return tuple(row) if row is not None else (0, 0, 0)

    def backup_to(self, destination: str | os.PathLike) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        with self._connect() as source, sqlite3.connect(
            temporary,
            factory=_ClosingConnection,
        ) as target:
            source.backup(target)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
        return destination

    def _prune_if_due(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        row = connection.execute(
            "SELECT value_json FROM health WHERE key = 'last_pruned_at'"
        ).fetchone()
        if row:
            raw = _load(row["value_json"])
            try:
                last_pruned = datetime.fromisoformat(raw).astimezone(UTC)
            except (TypeError, ValueError):
                last_pruned = None
            if last_pruned and now - last_pruned < self.PRUNE_INTERVAL:
                return

        cutoff = (now - timedelta(days=self.RETENTION_DAYS)).isoformat()
        cursor = connection.execute(
            "DELETE FROM events WHERE detected_at < ?", (cutoff,)
        )
        connection.execute(
            """
            INSERT INTO health(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            ("last_pruned_at", _dump(now.isoformat())),
        )
        if cursor.rowcount:
            existing = connection.execute(
                "SELECT value_json FROM health WHERE key = 'events_pruned'"
            ).fetchone()
            previous = _load(existing["value_json"], 0) if existing else 0
            try:
                total = int(previous) + int(cursor.rowcount)
            except (TypeError, ValueError):
                total = int(cursor.rowcount)
            connection.execute(
                """
                INSERT INTO health(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                ("events_pruned", _dump(total)),
            )
