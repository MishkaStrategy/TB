"""Read-only FVG history archive status for the admin operations screen."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from database.fvg_history_config import (
    FVG_HISTORY_ARCHIVE_BATCH_SIZE,
    FVG_HISTORY_ARCHIVE_ENABLED,
    FVG_HISTORY_ARCHIVE_MAX_BATCHES,
    FVG_HISTORY_ARCHIVE_PATH,
    FVG_HISTORY_RETENTION_DAYS,
)


UTC = timezone.utc
_REQUIRED_TABLES = frozenset({"archive_metadata", "fvg_archive_runs"})
_HEALTH_KEYS = (
    "events_archived",
    "deliveries_archived",
    "events_pruned",
    "fvg_archive_failures",
    "fvg_archive_backlog_possible",
    "last_archive_at",
    "last_archive_error",
    "last_archive_failure_at",
    "last_pruned_at",
)


def _read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA query_only=ON")
    return connection


def _load(value):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _runtime_health(connection, tables: set[str]) -> dict:
    if "health" not in tables:
        return {}
    placeholders = ",".join("?" for _ in _HEALTH_KEYS)
    rows = connection.execute(
        f"SELECT key, value_json FROM health WHERE key IN ({placeholders})",
        _HEALTH_KEYS,
    ).fetchall()
    return {str(row["key"]): _load(row["value_json"]) for row in rows}


def _file_bytes(path: Path) -> dict:
    main = path.stat().st_size if path.exists() else 0
    wal_path = Path(str(path) + "-wal")
    shm_path = Path(str(path) + "-shm")
    wal = wal_path.stat().st_size if wal_path.exists() else 0
    shm = shm_path.stat().st_size if shm_path.exists() else 0
    return {
        "main_bytes": int(main),
        "wal_bytes": int(wal),
        "shm_bytes": int(shm),
        "total_bytes": int(main + wal + shm),
    }


def read_fvg_history_status(
    runtime_connection: sqlite3.Connection,
    runtime_tables: set[str],
    *,
    archive_path: str | os.PathLike = FVG_HISTORY_ARCHIVE_PATH,
) -> dict:
    """Read archive metadata and latest run without creating or auditing the DB."""
    path = Path(archive_path)
    health = _runtime_health(runtime_connection, runtime_tables)
    result = {
        "enabled": bool(FVG_HISTORY_ARCHIVE_ENABLED),
        "archive_path": str(path),
        "exists": path.exists(),
        "available": False,
        "error_message": None,
        "schema_version": None,
        "latest_run": None,
        "recent_runs": [],
        "retention_days": int(FVG_HISTORY_RETENTION_DAYS),
        "batch_size": int(FVG_HISTORY_ARCHIVE_BATCH_SIZE),
        "max_batches": int(FVG_HISTORY_ARCHIVE_MAX_BATCHES),
        "runtime_health": health,
        **_file_bytes(path),
    }
    if not path.exists():
        return result

    try:
        with closing(_read_only(path)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
            missing = sorted(_REQUIRED_TABLES - tables)
            if missing:
                result["error_message"] = "missing_tables:" + ",".join(missing)
                return result

            schema_row = connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()
            result["schema_version"] = schema_row[0] if schema_row else None
            rows = connection.execute(
                """
                SELECT id, cutoff_at, archived_at, event_count,
                       delivery_count, source_deleted_count
                FROM fvg_archive_runs
                ORDER BY id DESC
                LIMIT 5
                """
            ).fetchall()
            recent = [dict(row) for row in rows]
            for item in recent:
                item["id"] = int(item["id"])
                item["event_count"] = int(item["event_count"])
                item["delivery_count"] = int(item["delivery_count"])
                item["source_deleted_count"] = int(item["source_deleted_count"])
            result["recent_runs"] = recent
            result["latest_run"] = recent[0] if recent else None
    except (OSError, sqlite3.DatabaseError) as error:
        result["error_message"] = f"{type(error).__name__}: {error}"[:2000]
        return result

    result["available"] = True
    return result
