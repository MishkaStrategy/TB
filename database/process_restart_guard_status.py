"""Read-only restart circuit-breaker snapshot for the admin operations screen."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from database.process_restart_guard_config import (
    FVG_PROCESS_RESTART_COOLDOWN_SECONDS,
    FVG_PROCESS_RESTART_MAX_REQUESTS,
    FVG_PROCESS_RESTART_WINDOW_SECONDS,
)


UTC = timezone.utc
_REQUIRED_TABLES = frozenset(
    {"process_restart_guard_state", "process_restart_requests"}
)


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


def _request(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["allowed"] = bool(item.get("allowed"))
    if item.get("silence_seconds") is not None:
        item["silence_seconds"] = float(item["silence_seconds"])
    return item


def read_restart_guard_status(
    connection: sqlite3.Connection,
    tables: set[str],
    *,
    now: datetime | None = None,
    max_requests: int = FVG_PROCESS_RESTART_MAX_REQUESTS,
    window_seconds: float = FVG_PROCESS_RESTART_WINDOW_SECONDS,
    cooldown_seconds: float = FVG_PROCESS_RESTART_COOLDOWN_SECONDS,
    recent_limit: int = 5,
) -> dict:
    """Read guard state without creating tables, pruning history or changing cooldown."""
    if not _REQUIRED_TABLES.issubset(tables):
        return {
            "available": False,
            "blocked": False,
            "blocked_until": None,
            "trip_count": 0,
            "last_reason": None,
            "last_request_id": None,
            "updated_at": None,
            "requests_in_window": 0,
            "max_requests": max(1, int(max_requests)),
            "window_seconds": max(1.0, float(window_seconds)),
            "cooldown_seconds": max(1.0, float(cooldown_seconds)),
            "latest_request": None,
            "recent_requests": [],
        }

    current = _utc(now)
    window = max(1.0, float(window_seconds))
    window_start = (current - timedelta(seconds=window)).isoformat()
    state_row = connection.execute(
        "SELECT * FROM process_restart_guard_state WHERE singleton=1"
    ).fetchone()
    requests_in_window = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM process_restart_requests
            WHERE allowed=1 AND requested_at>=?
            """,
            (window_start,),
        ).fetchone()[0]
    )
    rows = connection.execute(
        """
        SELECT request_id, requested_at, reason, silence_seconds,
               restart_mode, allowed, decision_reason, blocked_until,
               status, error_class, error_message, updated_at
        FROM process_restart_requests
        ORDER BY requested_at DESC, request_id DESC
        LIMIT ?
        """,
        (max(1, int(recent_limit)),),
    ).fetchall()
    recent_requests = [_request(row) for row in rows]

    state = dict(state_row) if state_row is not None else {}
    blocked_until = _parse_time(state.get("blocked_until"))
    return {
        "available": True,
        "blocked": bool(blocked_until and blocked_until > current),
        "blocked_until": blocked_until.isoformat() if blocked_until else None,
        "trip_count": int(state.get("trip_count") or 0),
        "last_reason": state.get("last_reason"),
        "last_request_id": state.get("last_request_id"),
        "updated_at": state.get("updated_at"),
        "requests_in_window": requests_in_window,
        "max_requests": max(1, int(max_requests)),
        "window_seconds": window,
        "cooldown_seconds": max(1.0, float(cooldown_seconds)),
        "latest_request": recent_requests[0] if recent_requests else None,
        "recent_requests": recent_requests,
    }
