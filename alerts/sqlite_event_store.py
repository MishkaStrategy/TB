"""SQLite/WAL persistence for FVG events, deliveries and health metrics."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alerts.fvg_models import FvgEvent


UTC = timezone.utc
_SCHEMA_VERSION = 1
_MIGRATION_LOCKS: dict[str, threading.Lock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str | None, default=None):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class FvgEventStore:
    """Thread-safe SQLite store with automatic legacy JSON import.

    A separate connection is opened for every operation. SQLite serializes
    writers while WAL allows readers and the WebSocket ingestion path to
    continue without rewriting the complete event history.
    """

    RETENTION_DAYS = 90
    PRUNE_INTERVAL = timedelta(days=1)
    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")
    LEGACY_DEFAULT_PATH = Path("data/fvg_event_store.json")

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
            self._migration_lock = _MIGRATION_LOCKS.setdefault(
                resolved, threading.Lock()
            )
        with self._migration_lock:
            self._prepare_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _prepare_database(self) -> None:
        legacy_data = None

        # An explicit test/legacy path may itself contain the old JSON format.
        if self.path.exists() and not self._is_sqlite_file(self.path):
            legacy_data = self._read_legacy_json(self.path)
            backup = self.path.with_suffix(self.path.suffix + ".legacy-json")
            backup.unlink(missing_ok=True)
            self.path.replace(backup)

        if legacy_data is None and self.legacy_json_path is not None:
            if self.legacy_json_path.exists():
                legacy_data = self._read_legacy_json(self.legacy_json_path)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._create_schema(connection)
                already_imported = connection.execute(
                    "SELECT value_json FROM metadata WHERE key = 'legacy_json_imported'"
                ).fetchone()
                if legacy_data and already_imported is None:
                    self._import_legacy(connection, legacy_data)
                    connection.execute(
                        "INSERT OR REPLACE INTO metadata(key, value_json) VALUES (?, ?)",
                        ("legacy_json_imported", _json_dump(_utc_now().isoformat())),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _is_sqlite_file(path: Path) -> bool:
        try:
            with path.open("rb") as source:
                return source.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    @staticmethod
    def _read_legacy_json(path: Path) -> dict | None:
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

            CREATE TABLE IF NOT EXISTS health (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value_json) VALUES (?, ?)",
            ("schema_version", _json_dump(_SCHEMA_VERSION)),
        )

    def _import_legacy(self, connection: sqlite3.Connection, data: dict) -> None:
        events = data.get("events", {})
        if isinstance(events, dict):
            for event_id, payload in events.items():
                if not isinstance(payload, dict):
                    continue
                normalized = {**payload, "event_id": payload.get("event_id", event_id)}
                detected_at = normalized.get("detected_at")
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
                        str(normalized["event_id"]),
                        str(normalized.get("event_type", "UNKNOWN")),
                        str(normalized.get("symbol", "UNKNOWN")),
                        str(normalized.get("timeframe", "15m")),
                        str(normalized.get("direction", "UNKNOWN")),
                        detected_at,
                        normalized.get("candle_c_close_time"),
                        _json_dump(normalized),
                    ),
                )

        deliveries = data.get("deliveries", {})
        if isinstance(deliveries, dict):
            for event_id, recipients in deliveries.items():
                if not isinstance(recipients, dict):
                    continue
                event_exists = connection.execute(
                    "SELECT 1 FROM events WHERE event_id = ?", (str(event_id),)
                ).fetchone()
                if event_exists is None:
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
            for key, value in health.items():
                connection.execute(
                    "INSERT OR REPLACE INTO health(key, value_json) VALUES (?, ?)",
                    (str(key), _json_dump(value)),
                )

    def record_event(self, event: FvgEvent) -> bool:
        payload = event.to_json()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._prune_if_due(connection, _utc_now())
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
                        _json_dump(payload),
                    ),
                )
                connection.execute("COMMIT")
                return cursor.rowcount == 1
            except Exception:
                connection.execute("ROLLBACK")
                raise

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
                (event_id, str(chat_id), _utc_now().isoformat()),
            )

    def update_health(self, **values) -> None:
        if not values:
            return
        rows = [(str(key), _json_dump(value)) for key, value in values.items()]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO health(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                rows,
            )

    def increment_health(self, key: str, amount: int = 1) -> None:
        amount = int(amount)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT value_json FROM health WHERE key = ?", (key,)
                ).fetchone()
                current = _json_load(row["value_json"], 0) if row else 0
                try:
                    value = int(current) + amount
                except (TypeError, ValueError):
                    value = amount
                connection.execute(
                    """
                    INSERT INTO health(key, value_json) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                    """,
                    (key, _json_dump(value)),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def health(self) -> dict:
        with self._connect() as connection:
            health_rows = connection.execute(
                "SELECT key, value_json FROM health"
            ).fetchall()
            event_count = connection.execute(
                "SELECT COUNT(*) AS value FROM events"
            ).fetchone()["value"]
            delivery_count = connection.execute(
                "SELECT COUNT(*) AS value FROM deliveries"
            ).fetchone()["value"]
        result = {
            row["key"]: _json_load(row["value_json"])
            for row in health_rows
        }
        result.update(events=event_count, deliveries=delivery_count)
        return result

    def summary(self, days: int | None = 7) -> dict:
        cutoff = None
        if days is not None:
            cutoff = (_utc_now() - timedelta(days=days)).isoformat()

        where = ""
        parameters: tuple = ()
        if cutoff is not None:
            where = "WHERE detected_at >= ?"
            parameters = (cutoff,)

        result: dict[str, object] = {}
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT direction, event_type, COUNT(*) AS count
                FROM events
                {where}
                GROUP BY direction, event_type
                """,
                parameters,
            ).fetchall()
            delivery_row = connection.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM deliveries AS delivery
                JOIN events AS event ON event.event_id = delivery.event_id
                {('WHERE event.detected_at >= ?' if cutoff is not None else '')}
                """,
                parameters,
            ).fetchone()

        counts = {
            (row["direction"], row["event_type"]): int(row["count"])
            for row in rows
        }
        for direction in ("BULLISH", "BEARISH"):
            confirmed = counts.get((direction, "CONFIRMED_FVG"), 0)
            preliminary = counts.get((direction, "PRE_FVG"), 0)
            result[direction] = {
                "confirmed": confirmed,
                "pre": preliminary,
                "total": confirmed + preliminary,
            }
        result["deliveries"] = int(delivery_row["count"])
        return result

    def checkpoint(self, *, truncate: bool = False) -> tuple[int, int, int]:
        """Flush WAL pages, primarily for backups and maintenance."""
        mode = "TRUNCATE" if truncate else "PASSIVE"
        with self._connect() as connection:
            row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        return tuple(row) if row is not None else (0, 0, 0)

    def backup_to(self, destination: str | os.PathLike) -> Path:
        """Create a transactionally consistent SQLite backup."""
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination_path.with_suffix(destination_path.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        with self._connect() as source:
            with sqlite3.connect(temporary) as target:
                source.backup(target)
        os.chmod(temporary, 0o600)
        temporary.replace(destination_path)
        return destination_path

    def _prune_if_due(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        row = connection.execute(
            "SELECT value_json FROM health WHERE key = 'last_pruned_at'"
        ).fetchone()
        if row is not None:
            raw = _json_load(row["value_json"])
            try:
                last_pruned = datetime.fromisoformat(raw).astimezone(UTC)
            except (TypeError, ValueError):
                last_pruned = None
            if last_pruned and now - last_pruned < self.PRUNE_INTERVAL:
                return

        cutoff = (now - timedelta(days=self.RETENTION_DAYS)).isoformat()
        cursor = connection.execute(
            "DELETE FROM events WHERE detected_at < ?",
            (cutoff,),
        )
        connection.execute(
            """
            INSERT INTO health(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            ("last_pruned_at", _json_dump(now.isoformat())),
        )
        if cursor.rowcount:
            existing = connection.execute(
                "SELECT value_json FROM health WHERE key = 'events_pruned'"
            ).fetchone()
            previous = _json_load(existing["value_json"], 0) if existing else 0
            try:
                total = int(previous) + int(cursor.rowcount)
            except (TypeError, ValueError):
                total = int(cursor.rowcount)
            connection.execute(
                """
                INSERT INTO health(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                ("events_pruned", _json_dump(total)),
            )
