"""Persistent cross-process circuit breaker for watchdog restart requests."""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


UTC = timezone.utc


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


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return _utc(parsed)


class ProcessRestartGuard:
    """Atomically enforce a bounded restart-request window and cooldown."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

    def __init__(
        self,
        path: str | os.PathLike | None = None,
        *,
        max_requests: int = 3,
        window_seconds: float = 3600,
        cooldown_seconds: float = 3600,
        history_retention_days: int = 30,
    ):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(1.0, float(window_seconds))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self.history_retention_days = max(1, int(history_retention_days))
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
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _prepare(self):
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS process_restart_guard_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    blocked_until TEXT,
                    trip_count INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT,
                    last_request_id TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS process_restart_requests (
                    request_id TEXT PRIMARY KEY,
                    requested_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    silence_seconds REAL,
                    restart_mode TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    decision_reason TEXT NOT NULL,
                    blocked_until TEXT,
                    status TEXT NOT NULL,
                    error_class TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_process_restart_requests_time
                    ON process_restart_requests(requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_process_restart_requests_allowed_time
                    ON process_restart_requests(allowed, requested_at DESC);
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO process_restart_guard_state(
                    singleton, blocked_until, trip_count, last_reason,
                    last_request_id, updated_at
                ) VALUES(1, NULL, 0, NULL, NULL, ?)
                """,
                (_utc().isoformat(),),
            )

    @staticmethod
    def _state(row):
        if row is None:
            return None
        result = dict(row)
        result["trip_count"] = int(result["trip_count"])
        return result

    @staticmethod
    def _request(row):
        result = dict(row)
        result["allowed"] = bool(result["allowed"])
        if result["silence_seconds"] is not None:
            result["silence_seconds"] = float(result["silence_seconds"])
        return result

    def decide(
        self,
        *,
        reason: str,
        silence_seconds: float | None,
        restart_mode: str,
        now: datetime | None = None,
    ) -> dict:
        current = _utc(now)
        timestamp = current.isoformat()
        window_start = (current - timedelta(seconds=self.window_seconds)).isoformat()
        retention_cutoff = (
            current - timedelta(days=self.history_retention_days)
        ).isoformat()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = connection.execute(
                "SELECT * FROM process_restart_guard_state WHERE singleton=1"
            ).fetchone()
            blocked_until = _parse_time(state["blocked_until"] if state else None)
            if blocked_until is not None and blocked_until > current:
                connection.execute(
                    """
                    DELETE FROM process_restart_requests
                    WHERE request_id IN (
                        SELECT request_id FROM process_restart_requests
                        WHERE requested_at<?
                        ORDER BY requested_at
                        LIMIT 100
                    )
                    """,
                    (retention_cutoff,),
                )
                connection.commit()
                return {
                    "allowed": False,
                    "request_id": None,
                    "decision_reason": "cooldown",
                    "blocked_until": blocked_until.isoformat(),
                    "requests_in_window": int(
                        connection.execute(
                            """
                            SELECT COUNT(*) FROM process_restart_requests
                            WHERE allowed=1 AND requested_at>=?
                            """,
                            (window_start,),
                        ).fetchone()[0]
                    ),
                }

            requests_in_window = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM process_restart_requests
                    WHERE allowed=1 AND requested_at>=?
                    """,
                    (window_start,),
                ).fetchone()[0]
            )
            request_id = str(uuid.uuid4())
            if requests_in_window >= self.max_requests:
                blocked_until = current + timedelta(seconds=self.cooldown_seconds)
                connection.execute(
                    """
                    INSERT INTO process_restart_requests(
                        request_id, requested_at, reason, silence_seconds,
                        restart_mode, allowed, decision_reason, blocked_until,
                        status, error_class, error_message, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 'limit_reached', ?,
                              'blocked', NULL, NULL, ?)
                    """,
                    (
                        request_id,
                        timestamp,
                        str(reason)[:500],
                        float(silence_seconds) if silence_seconds is not None else None,
                        str(restart_mode)[:100],
                        blocked_until.isoformat(),
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    UPDATE process_restart_guard_state
                    SET blocked_until=?,
                        trip_count=trip_count+1,
                        last_reason='limit_reached',
                        last_request_id=?,
                        updated_at=?
                    WHERE singleton=1
                    """,
                    (blocked_until.isoformat(), request_id, timestamp),
                )
                connection.execute(
                    """
                    DELETE FROM process_restart_requests
                    WHERE request_id IN (
                        SELECT request_id FROM process_restart_requests
                        WHERE requested_at<?
                        ORDER BY requested_at
                        LIMIT 100
                    )
                    """,
                    (retention_cutoff,),
                )
                connection.commit()
                return {
                    "allowed": False,
                    "request_id": request_id,
                    "decision_reason": "limit_reached",
                    "blocked_until": blocked_until.isoformat(),
                    "requests_in_window": requests_in_window,
                }

            connection.execute(
                """
                INSERT INTO process_restart_requests(
                    request_id, requested_at, reason, silence_seconds,
                    restart_mode, allowed, decision_reason, blocked_until,
                    status, error_class, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 'allowed', NULL,
                          'requested', NULL, NULL, ?)
                """,
                (
                    request_id,
                    timestamp,
                    str(reason)[:500],
                    float(silence_seconds) if silence_seconds is not None else None,
                    str(restart_mode)[:100],
                    timestamp,
                ),
            )
            connection.execute(
                """
                UPDATE process_restart_guard_state
                SET blocked_until=NULL,
                    last_reason='allowed',
                    last_request_id=?,
                    updated_at=?
                WHERE singleton=1
                """,
                (request_id, timestamp),
            )
            connection.execute(
                """
                DELETE FROM process_restart_requests
                WHERE request_id IN (
                    SELECT request_id FROM process_restart_requests
                    WHERE requested_at<?
                    ORDER BY requested_at
                    LIMIT 100
                )
                """,
                (retention_cutoff,),
            )
            connection.commit()
        return {
            "allowed": True,
            "request_id": request_id,
            "decision_reason": "allowed",
            "blocked_until": None,
            "requests_in_window": requests_in_window + 1,
        }

    def mark_failed(
        self,
        request_id: str,
        error: BaseException,
        *,
        now: datetime | None = None,
    ) -> bool:
        timestamp = _utc(now).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE process_restart_requests
                SET status='failed',
                    error_class=?,
                    error_message=?,
                    updated_at=?
                WHERE request_id=? AND allowed=1
                """,
                (
                    type(error).__name__,
                    str(error)[:2000],
                    timestamp,
                    str(request_id),
                ),
            )
        return cursor.rowcount == 1

    def state(self) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM process_restart_guard_state WHERE singleton=1"
            ).fetchone()
        return self._state(row)

    def requests(self, *, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM process_restart_requests
                ORDER BY requested_at DESC, request_id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [self._request(row) for row in rows]

    def summary(self, *, now: datetime | None = None) -> dict:
        current = _utc(now)
        window_start = (current - timedelta(seconds=self.window_seconds)).isoformat()
        with self._connect() as connection:
            state = connection.execute(
                "SELECT * FROM process_restart_guard_state WHERE singleton=1"
            ).fetchone()
            requests_in_window = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM process_restart_requests
                    WHERE allowed=1 AND requested_at>=?
                    """,
                    (window_start,),
                ).fetchone()[0]
            )
            latest = connection.execute(
                """
                SELECT * FROM process_restart_requests
                ORDER BY requested_at DESC, request_id DESC LIMIT 1
                """
            ).fetchone()
        state_value = self._state(state)
        blocked_until = _parse_time(state_value.get("blocked_until") if state_value else None)
        return {
            "max_requests": self.max_requests,
            "window_seconds": self.window_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "requests_in_window": requests_in_window,
            "blocked": bool(blocked_until and blocked_until > current),
            "blocked_until": blocked_until.isoformat() if blocked_until else None,
            "trip_count": int(state_value.get("trip_count") or 0),
            "latest_request": self._request(latest) if latest is not None else None,
        }
