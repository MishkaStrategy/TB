"""Persistent application lifecycle state and bounded transition history."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


UTC = timezone.utc
ACTIVE_STATUSES = frozenset({"starting", "running", "stopping"})


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


def _json(value) -> str:
    return json.dumps(
        value or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_json(value: str | None) -> dict:
    try:
        result = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


class RuntimeLifecycleStore:
    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
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
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _prepare(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_lifecycle_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    instance_id TEXT NOT NULL,
                    pid INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    running_at TEXT,
                    stopping_at TEXT,
                    stopped_at TEXT,
                    shutdown_deadline_at TEXT,
                    shutdown_outcome TEXT,
                    last_phase TEXT,
                    last_error_class TEXT,
                    last_error_message TEXT,
                    details_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_lifecycle_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    error_class TEXT,
                    error_message TEXT,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runtime_lifecycle_events_time
                    ON runtime_lifecycle_events(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_runtime_lifecycle_events_instance
                    ON runtime_lifecycle_events(instance_id, occurred_at DESC);
                """
            )

    @staticmethod
    def _state(row):
        if row is None:
            return None
        result = dict(row)
        result["pid"] = int(result["pid"])
        result["details"] = _load_json(result.pop("details_json", None))
        return result

    @staticmethod
    def _event(row):
        result = dict(row)
        result["id"] = int(result["id"])
        result["details"] = _load_json(result.pop("details_json", None))
        return result

    @staticmethod
    def _append_event(
        connection,
        *,
        instance_id,
        status,
        phase,
        timestamp,
        error=None,
        details=None,
    ):
        connection.execute(
            """
            INSERT INTO runtime_lifecycle_events(
                instance_id, status, phase, occurred_at,
                error_class, error_message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(instance_id),
                str(status),
                str(phase),
                timestamp,
                type(error).__name__ if error is not None else None,
                str(error)[:2000] if error is not None else None,
                _json(details),
            ),
        )

    def begin_start(
        self,
        *,
        instance_id: str | None = None,
        pid: int | None = None,
        now: datetime | None = None,
        details: dict | None = None,
    ) -> str:
        current = _utc(now)
        timestamp = current.isoformat()
        instance_id = str(instance_id or uuid.uuid4())
        pid = int(pid if pid is not None else os.getpid())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT * FROM runtime_lifecycle_state WHERE singleton=1"
            ).fetchone()
            if previous is not None and previous["status"] in ACTIVE_STATUSES:
                self._append_event(
                    connection,
                    instance_id=previous["instance_id"],
                    status="interrupted",
                    phase="previous_instance",
                    timestamp=timestamp,
                    details={
                        "previous_status": previous["status"],
                        "replacement_instance_id": instance_id,
                    },
                )
            connection.execute(
                """
                INSERT INTO runtime_lifecycle_state(
                    singleton, instance_id, pid, status, started_at,
                    last_phase, details_json, updated_at
                ) VALUES (1, ?, ?, 'starting', ?, 'startup', ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    instance_id=excluded.instance_id,
                    pid=excluded.pid,
                    status=excluded.status,
                    started_at=excluded.started_at,
                    running_at=NULL,
                    stopping_at=NULL,
                    stopped_at=NULL,
                    shutdown_deadline_at=NULL,
                    shutdown_outcome=NULL,
                    last_phase=excluded.last_phase,
                    last_error_class=NULL,
                    last_error_message=NULL,
                    details_json=excluded.details_json,
                    updated_at=excluded.updated_at
                """,
                (instance_id, pid, timestamp, _json(details), timestamp),
            )
            self._append_event(
                connection,
                instance_id=instance_id,
                status="starting",
                phase="startup",
                timestamp=timestamp,
                details=details,
            )
            connection.commit()
        return instance_id

    def transition(
        self,
        instance_id: str,
        status: str,
        *,
        phase: str,
        now: datetime | None = None,
        deadline: datetime | None = None,
        outcome: str | None = None,
        error: BaseException | None = None,
        details: dict | None = None,
    ) -> bool:
        timestamp = _utc(now).isoformat()
        running_at = timestamp if status == "running" else None
        stopping_at = timestamp if status == "stopping" else None
        stopped_at = (
            timestamp
            if status in {"stopped", "shutdown_timeout", "failed"}
            else None
        )
        deadline_at = _utc(deadline).isoformat() if deadline is not None else None
        error_class = type(error).__name__ if error is not None else None
        error_message = str(error)[:2000] if error is not None else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runtime_lifecycle_state
                SET status=?,
                    running_at=COALESCE(running_at, ?),
                    stopping_at=COALESCE(stopping_at, ?),
                    stopped_at=COALESCE(stopped_at, ?),
                    shutdown_deadline_at=COALESCE(shutdown_deadline_at, ?),
                    shutdown_outcome=COALESCE(?, shutdown_outcome),
                    last_phase=?,
                    last_error_class=COALESCE(?, last_error_class),
                    last_error_message=COALESCE(?, last_error_message),
                    details_json=?,
                    updated_at=?
                WHERE singleton=1 AND instance_id=?
                """,
                (
                    str(status),
                    running_at,
                    stopping_at,
                    stopped_at,
                    deadline_at,
                    outcome,
                    str(phase),
                    error_class,
                    error_message,
                    _json(details),
                    timestamp,
                    str(instance_id),
                ),
            )
            if cursor.rowcount == 1:
                self._append_event(
                    connection,
                    instance_id=instance_id,
                    status=status,
                    phase=phase,
                    timestamp=timestamp,
                    error=error,
                    details=details,
                )
            connection.commit()
        return cursor.rowcount == 1

    def current(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runtime_lifecycle_state WHERE singleton=1"
            ).fetchone()
        return self._state(row)

    def events(self, *, instance_id: str | None = None, limit: int = 50):
        with self._connect() as connection:
            if instance_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM runtime_lifecycle_events
                    ORDER BY occurred_at DESC, id DESC LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM runtime_lifecycle_events
                    WHERE instance_id=?
                    ORDER BY occurred_at DESC, id DESC LIMIT ?
                    """,
                    (str(instance_id), max(1, int(limit))),
                ).fetchall()
        return [self._event(row) for row in rows]

    def prune(
        self,
        *,
        retention_days: int = 30,
        batch_size: int = 500,
        now: datetime | None = None,
    ) -> int:
        cutoff = (
            _utc(now) - timedelta(days=max(1, int(retention_days)))
        ).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM runtime_lifecycle_events
                WHERE occurred_at<? ORDER BY occurred_at LIMIT ?
                """,
                (cutoff, max(1, int(batch_size))),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM runtime_lifecycle_events WHERE id=?",
                    [(int(row["id"]),) for row in rows],
                )
        return len(rows)
