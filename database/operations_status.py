"""Read-only admin snapshot across runtime lifecycle, tasks and DB observations."""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.process_restart_guard_status import read_restart_guard_status


UTC = timezone.utc
PROBLEM_STATUSES = frozenset({"failed", "stale"})


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


def _load_json(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OperationsStatusReader:
    """Inspect optional operational tables without creating or modifying them."""

    DEFAULT_PATH = Path("data/fvg_event_store.sqlite3")

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else self.DEFAULT_PATH

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=5,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _tables(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            ).fetchall()
        }

    @staticmethod
    def _lifecycle(connection, tables: set[str]) -> dict:
        if "runtime_lifecycle_state" not in tables:
            return {"available": False, "state": None, "recent_events": []}
        row = connection.execute(
            "SELECT * FROM runtime_lifecycle_state WHERE singleton=1"
        ).fetchone()
        state = dict(row) if row is not None else None
        if state is not None:
            state["pid"] = int(state.get("pid") or 0)
            state["details"] = _load_json(state.pop("details_json", None))

        recent_events = []
        if "runtime_lifecycle_events" in tables:
            rows = connection.execute(
                """
                SELECT status, phase, occurred_at, error_class, error_message
                FROM runtime_lifecycle_events
                ORDER BY occurred_at DESC, id DESC
                LIMIT 5
                """
            ).fetchall()
            recent_events = [dict(item) for item in rows]
        return {
            "available": True,
            "state": state,
            "recent_events": recent_events,
        }

    @staticmethod
    def _tasks(
        connection,
        tables: set[str],
        *,
        now: datetime,
        stale_multiplier: float,
    ) -> dict:
        if "background_task_state" not in tables:
            return {
                "available": False,
                "total": 0,
                "counts": {},
                "expired_lease_count": 0,
                "overdue_count": 0,
                "problems": [],
            }

        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM background_task_state ORDER BY task_name"
            ).fetchall()
        ]
        counts = Counter(str(row.get("status") or "unknown") for row in rows)
        problems = []
        expired_lease_count = 0
        overdue_count = 0
        multiplier = max(1.0, float(stale_multiplier))

        for row in rows:
            status = str(row.get("status") or "unknown")
            lease_until = _parse_time(row.get("lease_until"))
            expired_lease = bool(
                status == "running" and lease_until is not None and lease_until < now
            )
            if expired_lease:
                expired_lease_count += 1

            interval = row.get("expected_interval_seconds")
            reference = _parse_time(
                row.get("last_started_at") or row.get("registered_at")
            )
            overdue = False
            age_seconds = None
            threshold_seconds = None
            if interval is not None and reference is not None and status != "running":
                age_seconds = max(0.0, (now - reference).total_seconds())
                threshold_seconds = max(1.0, float(interval)) * multiplier
                overdue = age_seconds >= threshold_seconds
            if overdue:
                overdue_count += 1

            consecutive_failures = int(row.get("consecutive_failures") or 0)
            if (
                status in PROBLEM_STATUSES
                or expired_lease
                or overdue
                or consecutive_failures > 0
            ):
                problems.append(
                    {
                        "task_name": str(row.get("task_name")),
                        "status": status,
                        "expired_lease": expired_lease,
                        "overdue": overdue,
                        "age_seconds": age_seconds,
                        "threshold_seconds": threshold_seconds,
                        "consecutive_failures": consecutive_failures,
                        "last_error_class": row.get("last_error_class"),
                        "last_error_code": row.get("last_error_code"),
                        "last_error_message": row.get("last_error_message"),
                        "last_started_at": row.get("last_started_at"),
                        "last_completed_at": row.get("last_completed_at"),
                    }
                )

        problems.sort(
            key=lambda item: (
                not item["expired_lease"],
                not item["overdue"],
                item["status"] not in PROBLEM_STATUSES,
                -item["consecutive_failures"],
                item["task_name"],
            )
        )
        return {
            "available": True,
            "total": len(rows),
            "counts": dict(sorted(counts.items())),
            "expired_lease_count": expired_lease_count,
            "overdue_count": overdue_count,
            "problems": problems[:10],
        }

    @staticmethod
    def _database_observations(
        connection,
        tables: set[str],
        *,
        now: datetime,
    ) -> dict:
        if "database_observation_runs" not in tables:
            return {
                "available": False,
                "latest": [],
                "growth_24h": [],
            }

        rows = connection.execute(
            """
            SELECT runs.*
            FROM database_observation_runs AS runs
            JOIN (
                SELECT database_key, MAX(captured_at) AS captured_at
                FROM database_observation_runs
                GROUP BY database_key
            ) AS latest
              ON latest.database_key = runs.database_key
             AND latest.captured_at = runs.captured_at
            ORDER BY runs.database_key
            """
        ).fetchall()
        latest = []
        for row in rows:
            item = dict(row)
            item["id"] = int(item["id"])
            item["available"] = bool(item["available"])
            latest.append(item)

        since = (now - timedelta(hours=24)).isoformat()
        history_rows = connection.execute(
            """
            SELECT database_key, captured_at, main_bytes, wal_bytes, shm_bytes,
                   allocated_bytes, used_bytes
            FROM database_observation_runs
            WHERE available=1 AND captured_at>=?
            ORDER BY database_key, captured_at
            """,
            (since,),
        ).fetchall()
        by_key = defaultdict(list)
        for row in history_rows:
            by_key[str(row["database_key"])].append(dict(row))

        growth = []
        for database_key, items in sorted(by_key.items()):
            if len(items) < 2:
                continue
            first, last = items[0], items[-1]

            def delta(name):
                left, right = first.get(name), last.get(name)
                if left is None or right is None:
                    return None
                return int(right) - int(left)

            growth.append(
                {
                    "database_key": database_key,
                    "from_captured_at": first["captured_at"],
                    "to_captured_at": last["captured_at"],
                    "main_bytes_delta": delta("main_bytes"),
                    "wal_bytes_delta": delta("wal_bytes"),
                    "shm_bytes_delta": delta("shm_bytes"),
                    "allocated_bytes_delta": delta("allocated_bytes"),
                    "used_bytes_delta": delta("used_bytes"),
                }
            )
        return {
            "available": True,
            "latest": latest,
            "growth_24h": growth,
        }

    def snapshot(
        self,
        *,
        now: datetime | None = None,
        stale_multiplier: float = 3.0,
    ) -> dict:
        current = _utc(now)
        result = {
            "database_path": str(self.path),
            "captured_at": current.isoformat(),
            "available": False,
            "error_message": None,
            "lifecycle": {"available": False, "state": None, "recent_events": []},
            "tasks": {
                "available": False,
                "total": 0,
                "counts": {},
                "expired_lease_count": 0,
                "overdue_count": 0,
                "problems": [],
            },
            "restart_guard": {
                "available": False,
                "blocked": False,
                "blocked_until": None,
                "trip_count": 0,
                "requests_in_window": 0,
                "max_requests": 0,
                "window_seconds": 0,
                "cooldown_seconds": 0,
                "latest_request": None,
                "recent_requests": [],
            },
            "databases": {"available": False, "latest": [], "growth_24h": []},
        }
        if not self.path.exists():
            result["error_message"] = "database_file_missing"
            return result

        try:
            with self._connect() as connection:
                tables = self._tables(connection)
                result["lifecycle"] = self._lifecycle(connection, tables)
                result["tasks"] = self._tasks(
                    connection,
                    tables,
                    now=current,
                    stale_multiplier=stale_multiplier,
                )
                result["restart_guard"] = read_restart_guard_status(
                    connection,
                    tables,
                    now=current,
                )
                result["databases"] = self._database_observations(
                    connection,
                    tables,
                    now=current,
                )
        except (OSError, sqlite3.DatabaseError) as error:
            result["error_message"] = str(error)[:2000]
            return result

        result["available"] = True
        return result
