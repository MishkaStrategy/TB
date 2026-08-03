"""Persistent background-task leases, execution state and bounded run history."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


UTC = timezone.utc
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
CANCELLED = "cancelled"
SKIPPED = "skipped"
STALE = "stale"
IDLE = "idle"
FINAL_RUN_STATUSES = frozenset({SUCCESS, FAILED, CANCELLED, SKIPPED, STALE})


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


def _json(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None) -> dict:
    try:
        result = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


class BackgroundTaskRegistry:
    """Coordinate scheduled tasks across workers through SQLite leases."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

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
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS background_task_state (
                    task_name TEXT PRIMARY KEY,
                    task_kind TEXT NOT NULL,
                    expected_interval_seconds REAL,
                    registered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_run_id TEXT,
                    owner_id TEXT,
                    lease_until TEXT,
                    heartbeat_at TEXT,
                    last_started_at TEXT,
                    last_completed_at TEXT,
                    last_success_at TEXT,
                    last_failure_at TEXT,
                    last_duration_seconds REAL,
                    last_error_class TEXT,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    cancelled_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    stale_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_background_task_status
                    ON background_task_state(status, lease_until);
                CREATE INDEX IF NOT EXISTS idx_background_task_schedule
                    ON background_task_state(expected_interval_seconds, last_started_at);

                CREATE TABLE IF NOT EXISTS background_task_runs (
                    run_id TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    owner_id TEXT,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    heartbeat_at TEXT,
                    lease_until TEXT,
                    completed_at TEXT,
                    duration_seconds REAL,
                    error_class TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(task_name) REFERENCES background_task_state(task_name)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_background_task_runs_task_started
                    ON background_task_runs(task_name, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_background_task_runs_status
                    ON background_task_runs(status, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_background_task_runs_retention
                    ON background_task_runs(completed_at);
                """
            )

    @staticmethod
    def _state(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        for key in (
            "consecutive_failures",
            "run_count",
            "success_count",
            "failure_count",
            "cancelled_count",
            "skipped_count",
            "stale_count",
        ):
            result[key] = int(result[key] or 0)
        return result

    @staticmethod
    def _run(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = _load_json(result.pop("metadata_json", None))
        return result

    @staticmethod
    def _register_unlocked(
        connection: sqlite3.Connection,
        task_name: str,
        *,
        task_kind: str,
        expected_interval_seconds: float | None,
        timestamp: str,
    ) -> None:
        interval = (
            max(1.0, float(expected_interval_seconds))
            if expected_interval_seconds is not None
            else None
        )
        connection.execute(
            """
            INSERT INTO background_task_state(
                task_name, task_kind, expected_interval_seconds,
                registered_at, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_name) DO UPDATE SET
                task_kind=excluded.task_kind,
                expected_interval_seconds=excluded.expected_interval_seconds,
                updated_at=excluded.updated_at
            """,
            (str(task_name), str(task_kind), interval, timestamp, IDLE, timestamp),
        )

    def register(
        self,
        task_name: str,
        *,
        task_kind: str = "job_queue",
        expected_interval_seconds: float | None = None,
        now: datetime | None = None,
    ) -> dict:
        timestamp = _utc(now).isoformat()
        with self._connect() as connection:
            self._register_unlocked(
                connection,
                task_name,
                task_kind=task_kind,
                expected_interval_seconds=expected_interval_seconds,
                timestamp=timestamp,
            )
            row = connection.execute(
                "SELECT * FROM background_task_state WHERE task_name=?",
                (str(task_name),),
            ).fetchone()
        return self._state(row)

    @staticmethod
    def _mark_stale_unlocked(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        timestamp: str,
        reason: str = "task_lease_expired",
    ) -> bool:
        run_id = row["current_run_id"]
        if row["status"] != RUNNING or not run_id:
            return False
        connection.execute(
            """
            UPDATE background_task_runs
            SET status=?, completed_at=?,
                duration_seconds=MAX(0, (julianday(?) - julianday(started_at)) * 86400.0),
                error_class='TaskLeaseExpired', error_code=?, error_message=?
            WHERE run_id=? AND status=?
            """,
            (STALE, timestamp, timestamp, reason, reason, run_id, RUNNING),
        )
        cursor = connection.execute(
            """
            UPDATE background_task_state
            SET status=?, current_run_id=NULL, owner_id=NULL, lease_until=NULL,
                heartbeat_at=NULL, last_completed_at=?, last_failure_at=?,
                last_duration_seconds=MAX(0, (julianday(?) - julianday(last_started_at)) * 86400.0),
                last_error_class='TaskLeaseExpired', last_error_code=?,
                last_error_message=?, consecutive_failures=consecutive_failures+1,
                failure_count=failure_count+1, stale_count=stale_count+1,
                updated_at=?
            WHERE task_name=? AND current_run_id=? AND status=?
            """,
            (
                STALE,
                timestamp,
                timestamp,
                timestamp,
                reason,
                reason,
                timestamp,
                row["task_name"],
                run_id,
                RUNNING,
            ),
        )
        return cursor.rowcount == 1

    def recover_stale(
        self,
        *,
        now: datetime | None = None,
        limit: int = 500,
    ) -> int:
        timestamp = _utc(now).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM background_task_state
                WHERE status=? AND lease_until IS NOT NULL AND lease_until<=?
                ORDER BY lease_until
                LIMIT ?
                """,
                (RUNNING, timestamp, max(1, int(limit))),
            ).fetchall()
            recovered = sum(
                int(self._mark_stale_unlocked(connection, row, timestamp=timestamp))
                for row in rows
            )
            connection.commit()
        return recovered

    def try_begin(
        self,
        task_name: str,
        *,
        owner_id: str,
        lease_seconds: float,
        task_kind: str = "job_queue",
        expected_interval_seconds: float | None = None,
        trigger: str = "scheduled",
        metadata: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        current = _utc(now)
        timestamp = current.isoformat()
        lease_until = (
            current + timedelta(seconds=max(1.0, float(lease_seconds)))
        ).isoformat()
        attempted_run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._register_unlocked(
                connection,
                task_name,
                task_kind=task_kind,
                expected_interval_seconds=expected_interval_seconds,
                timestamp=timestamp,
            )
            row = connection.execute(
                "SELECT * FROM background_task_state WHERE task_name=?",
                (str(task_name),),
            ).fetchone()
            if (
                row["status"] == RUNNING
                and row["lease_until"] is not None
                and row["lease_until"] <= timestamp
            ):
                self._mark_stale_unlocked(connection, row, timestamp=timestamp)
                row = connection.execute(
                    "SELECT * FROM background_task_state WHERE task_name=?",
                    (str(task_name),),
                ).fetchone()

            if row["status"] == RUNNING:
                connection.execute(
                    """
                    INSERT INTO background_task_runs(
                        run_id, task_name, trigger, owner_id, status,
                        started_at, completed_at, duration_seconds,
                        error_class, error_code, error_message, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        attempted_run_id,
                        str(task_name),
                        str(trigger),
                        str(owner_id),
                        SKIPPED,
                        timestamp,
                        timestamp,
                        "TaskOverlapPrevented",
                        "overlap_prevented",
                        f"Active run {row['current_run_id']} still owns the task lease",
                        _json(metadata),
                    ),
                )
                connection.execute(
                    """
                    UPDATE background_task_state
                    SET skipped_count=skipped_count+1, updated_at=?
                    WHERE task_name=?
                    """,
                    (timestamp, str(task_name)),
                )
                connection.commit()
                return {
                    "started": False,
                    "reason": "overlap",
                    "run_id": attempted_run_id,
                    "active_run_id": row["current_run_id"],
                }

            connection.execute(
                """
                INSERT INTO background_task_runs(
                    run_id, task_name, trigger, owner_id, status,
                    started_at, heartbeat_at, lease_until, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempted_run_id,
                    str(task_name),
                    str(trigger),
                    str(owner_id),
                    RUNNING,
                    timestamp,
                    timestamp,
                    lease_until,
                    _json(metadata),
                ),
            )
            connection.execute(
                """
                UPDATE background_task_state
                SET status=?, current_run_id=?, owner_id=?, lease_until=?,
                    heartbeat_at=?, last_started_at=?, last_error_class=NULL,
                    last_error_code=NULL, last_error_message=NULL,
                    run_count=run_count+1, updated_at=?
                WHERE task_name=?
                """,
                (
                    RUNNING,
                    attempted_run_id,
                    str(owner_id),
                    lease_until,
                    timestamp,
                    timestamp,
                    timestamp,
                    str(task_name),
                ),
            )
            connection.commit()
        return {
            "started": True,
            "reason": None,
            "run_id": attempted_run_id,
            "lease_until": lease_until,
        }

    def heartbeat(
        self,
        task_name: str,
        run_id: str,
        *,
        owner_id: str,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        current = _utc(now)
        timestamp = current.isoformat()
        lease_until = (
            current + timedelta(seconds=max(1.0, float(lease_seconds)))
        ).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE background_task_state
                SET heartbeat_at=?, lease_until=?, updated_at=?
                WHERE task_name=? AND current_run_id=? AND owner_id=? AND status=?
                """,
                (
                    timestamp,
                    lease_until,
                    timestamp,
                    str(task_name),
                    str(run_id),
                    str(owner_id),
                    RUNNING,
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE background_task_runs
                    SET heartbeat_at=?, lease_until=?
                    WHERE run_id=? AND owner_id=? AND status=?
                    """,
                    (timestamp, lease_until, str(run_id), str(owner_id), RUNNING),
                )
            connection.commit()
        return cursor.rowcount == 1

    def _finish(
        self,
        task_name: str,
        run_id: str,
        *,
        owner_id: str,
        status: str,
        error: BaseException | None = None,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if status not in {SUCCESS, FAILED, CANCELLED}:
            raise ValueError(f"Unsupported task final status: {status}")
        current = _utc(now)
        timestamp = current.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT state.*, run.started_at
                FROM background_task_state AS state
                JOIN background_task_runs AS run ON run.run_id=state.current_run_id
                WHERE state.task_name=? AND state.current_run_id=?
                  AND state.owner_id=? AND state.status=? AND run.status=?
                """,
                (str(task_name), str(run_id), str(owner_id), RUNNING, RUNNING),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            started_at = _utc(datetime.fromisoformat(row["started_at"]))
            duration = max(0.0, (current - started_at).total_seconds())
            error_class = type(error).__name__ if error is not None else None
            error_message = str(error)[:2000] if error is not None else None
            connection.execute(
                """
                UPDATE background_task_runs
                SET status=?, completed_at=?, duration_seconds=?,
                    error_class=?, error_code=?, error_message=?
                WHERE run_id=? AND owner_id=? AND status=?
                """,
                (
                    status,
                    timestamp,
                    duration,
                    error_class,
                    error_code,
                    error_message,
                    str(run_id),
                    str(owner_id),
                    RUNNING,
                ),
            )
            success = status == SUCCESS
            failure = status == FAILED
            cancelled = status == CANCELLED
            connection.execute(
                """
                UPDATE background_task_state
                SET status=?, current_run_id=NULL, owner_id=NULL, lease_until=NULL,
                    heartbeat_at=NULL, last_completed_at=?,
                    last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,
                    last_failure_at=CASE WHEN ? THEN ? ELSE last_failure_at END,
                    last_duration_seconds=?, last_error_class=?,
                    last_error_code=?, last_error_message=?,
                    consecutive_failures=CASE
                        WHEN ? THEN 0
                        WHEN ? THEN consecutive_failures+1
                        ELSE consecutive_failures
                    END,
                    success_count=success_count+?, failure_count=failure_count+?,
                    cancelled_count=cancelled_count+?, updated_at=?
                WHERE task_name=? AND current_run_id=? AND owner_id=? AND status=?
                """,
                (
                    status,
                    timestamp,
                    int(success),
                    timestamp,
                    int(failure),
                    timestamp,
                    duration,
                    error_class,
                    error_code,
                    error_message,
                    int(success),
                    int(failure),
                    int(success),
                    int(failure),
                    int(cancelled),
                    timestamp,
                    str(task_name),
                    str(run_id),
                    str(owner_id),
                    RUNNING,
                ),
            )
            connection.commit()
        return True

    def finish_success(self, task_name: str, run_id: str, *, owner_id: str, now=None):
        return self._finish(
            task_name,
            run_id,
            owner_id=owner_id,
            status=SUCCESS,
            now=now,
        )

    def finish_failure(
        self,
        task_name: str,
        run_id: str,
        *,
        owner_id: str,
        error: BaseException,
        error_code: str = "task_failed",
        now=None,
    ):
        return self._finish(
            task_name,
            run_id,
            owner_id=owner_id,
            status=FAILED,
            error=error,
            error_code=error_code,
            now=now,
        )

    def finish_cancelled(
        self,
        task_name: str,
        run_id: str,
        *,
        owner_id: str,
        reason: str = "task_cancelled",
        now=None,
    ):
        return self._finish(
            task_name,
            run_id,
            owner_id=owner_id,
            status=CANCELLED,
            error=RuntimeError(reason),
            error_code=reason,
            now=now,
        )

    def state(self, task_name: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM background_task_state WHERE task_name=?",
                (str(task_name),),
            ).fetchone()
        return self._state(row)

    def states(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM background_task_state ORDER BY task_name"
            ).fetchall()
        return [self._state(row) for row in rows]

    def runs(self, task_name: str, *, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM background_task_runs
                WHERE task_name=?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (str(task_name), max(1, int(limit))),
            ).fetchall()
        return [self._run(row) for row in rows]

    def overdue_tasks(
        self,
        *,
        stale_multiplier: float = 3.0,
        now: datetime | None = None,
    ) -> list[dict]:
        current = _utc(now)
        self.recover_stale(now=current)
        result = []
        for state in self.states():
            interval = state.get("expected_interval_seconds")
            if interval is None or state["status"] == RUNNING:
                continue
            reference_text = state.get("last_started_at") or state.get("registered_at")
            if not reference_text:
                continue
            try:
                reference = _utc(datetime.fromisoformat(reference_text))
            except (TypeError, ValueError):
                continue
            threshold = max(1.0, float(interval)) * max(1.0, float(stale_multiplier))
            age = max(0.0, (current - reference).total_seconds())
            if age >= threshold:
                result.append(
                    {
                        **state,
                        "age_seconds": age,
                        "overdue_seconds": age - threshold,
                        "threshold_seconds": threshold,
                    }
                )
        return sorted(result, key=lambda item: item["overdue_seconds"], reverse=True)

    def summary(self, *, now: datetime | None = None, stale_multiplier: float = 3.0) -> dict:
        states = self.states()
        counts: dict[str, int] = {}
        for state in states:
            counts[state["status"]] = counts.get(state["status"], 0) + 1
        overdue = self.overdue_tasks(now=now, stale_multiplier=stale_multiplier)
        return {
            "total": len(states),
            "counts": counts,
            "overdue_count": len(overdue),
            "overdue_tasks": [item["task_name"] for item in overdue],
        }

    def prune_runs(
        self,
        *,
        retention_days: int = 30,
        batch_size: int = 500,
        now: datetime | None = None,
    ) -> int:
        cutoff = (_utc(now) - timedelta(days=max(1, int(retention_days)))).isoformat()
        placeholders = ",".join("?" for _ in FINAL_RUN_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT run_id FROM background_task_runs
                WHERE status IN ({placeholders}) AND completed_at<?
                ORDER BY completed_at
                LIMIT ?
                """,
                (*sorted(FINAL_RUN_STATUSES), cutoff, max(1, int(batch_size))),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM background_task_runs WHERE run_id=?",
                    [(row["run_id"],) for row in rows],
                )
        return len(rows)
