"""Read-only integrity and reconciliation audit for FVG history archives."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc
EXPECTED_TABLES = frozenset(
    {
        "archive_metadata",
        "archived_fvg_events",
        "archived_fvg_deliveries",
        "fvg_archive_runs",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_only(path: Path):
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA query_only=ON")
    return connection


def _runtime_health(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"available": False, "values": {}, "error": None}
    keys = (
        "events_archived",
        "deliveries_archived",
        "events_pruned",
        "fvg_archive_failures",
        "fvg_archive_backlog_possible",
        "last_archive_at",
        "last_archive_error",
        "last_archive_failure_at",
    )
    try:
        with closing(_read_only(path)) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='health'"
            ).fetchone()
            if table is None:
                return {"available": False, "values": {}, "error": None}
            placeholders = ",".join("?" for _ in keys)
            rows = connection.execute(
                f"SELECT key, value_json FROM health WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
    except (OSError, sqlite3.DatabaseError) as error:
        return {
            "available": False,
            "values": {},
            "error": f"{type(error).__name__}: {error}"[:2000],
        }
    values = {}
    for row in rows:
        try:
            values[str(row["key"])] = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            values[str(row["key"])] = row["value_json"]
    return {"available": True, "values": values, "error": None}


def _counter_mismatch(value, expected: int) -> bool:
    if value is None:
        return False
    try:
        return int(value) != int(expected)
    except (TypeError, ValueError):
        return True


def audit_fvg_archive(
    archive_path: str | os.PathLike,
    *,
    runtime_path: str | os.PathLike | None = None,
    include_quick_check: bool = True,
    payload_sample_size: int = 500,
    allow_missing: bool = False,
) -> dict:
    archive = Path(archive_path)
    runtime = Path(runtime_path) if runtime_path is not None else None
    result = {
        "archive_path": str(archive),
        "runtime_path": str(runtime) if runtime is not None else None,
        "audited_at": _utc_now(),
        "exists": archive.exists(),
        "allow_missing": bool(allow_missing),
        "passed": False,
        "errors": [],
        "warnings": [],
        "schema_version": None,
        "quick_check": None,
        "counts": {"events": 0, "deliveries": 0, "runs": 0},
        "run_totals": {
            "events": 0,
            "deliveries": 0,
            "source_deleted": 0,
        },
        "run_reconciliation": {
            "event_rows_match": True,
            "delivery_rows_match": True,
            "source_delete_rows_match": True,
        },
        "orphan_deliveries": 0,
        "payload_sampled": 0,
        "payload_errors": 0,
        "latest_run": None,
        "runtime_health": _runtime_health(runtime),
    }
    if not archive.exists():
        if allow_missing:
            result["passed"] = True
            result["warnings"].append("archive_file_missing")
        else:
            result["errors"].append("archive_file_missing")
        return result

    try:
        with closing(_read_only(archive)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
            missing_tables = sorted(EXPECTED_TABLES - tables)
            if missing_tables:
                result["errors"].append(
                    "missing_tables:" + ",".join(missing_tables)
                )
                return result

            schema_row = connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()
            result["schema_version"] = schema_row[0] if schema_row else None
            if str(result["schema_version"]) != "1":
                result["errors"].append(
                    f"unsupported_schema_version:{result['schema_version']}"
                )

            if include_quick_check:
                checks = [
                    str(row[0])
                    for row in connection.execute("PRAGMA quick_check").fetchall()
                ]
                result["quick_check"] = "; ".join(checks)
                if checks != ["ok"]:
                    result["errors"].append("quick_check_failed")

            result["counts"] = {
                "events": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM archived_fvg_events"
                    ).fetchone()[0]
                ),
                "deliveries": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM archived_fvg_deliveries"
                    ).fetchone()[0]
                ),
                "runs": int(
                    connection.execute(
                        "SELECT COUNT(*) FROM fvg_archive_runs"
                    ).fetchone()[0]
                ),
            }
            totals = connection.execute(
                """
                SELECT COALESCE(SUM(event_count), 0),
                       COALESCE(SUM(delivery_count), 0),
                       COALESCE(SUM(source_deleted_count), 0)
                FROM fvg_archive_runs
                """
            ).fetchone()
            result["run_totals"] = {
                "events": int(totals[0]),
                "deliveries": int(totals[1]),
                "source_deleted": int(totals[2]),
            }
            latest = connection.execute(
                "SELECT * FROM fvg_archive_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            result["latest_run"] = dict(latest) if latest is not None else None

            result["orphan_deliveries"] = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM archived_fvg_deliveries AS delivery
                    LEFT JOIN archived_fvg_events AS event
                      ON event.event_id=delivery.event_id
                    WHERE event.event_id IS NULL
                    """
                ).fetchone()[0]
            )
            if result["orphan_deliveries"]:
                result["errors"].append("orphan_deliveries")

            rows = connection.execute(
                """
                SELECT event_id, payload_json
                FROM archived_fvg_events
                ORDER BY detected_at DESC, event_id
                LIMIT ?
                """,
                (max(1, int(payload_sample_size)),),
            ).fetchall()
            result["payload_sampled"] = len(rows)
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    result["payload_errors"] += 1
                    continue
                if not isinstance(payload, dict) or str(payload.get("event_id")) != str(
                    row["event_id"]
                ):
                    result["payload_errors"] += 1
            if result["payload_errors"]:
                result["errors"].append("payload_integrity_failed")

            reconciliation = {
                "event_rows_match": (
                    result["run_totals"]["events"] == result["counts"]["events"]
                ),
                "delivery_rows_match": (
                    result["run_totals"]["deliveries"]
                    == result["counts"]["deliveries"]
                ),
                "source_delete_rows_match": (
                    result["run_totals"]["source_deleted"]
                    == result["counts"]["events"]
                ),
            }
            result["run_reconciliation"] = reconciliation
            if not reconciliation["event_rows_match"]:
                result["warnings"].append("event_run_total_mismatch")
            if not reconciliation["delivery_rows_match"]:
                result["warnings"].append("delivery_run_total_mismatch")
            if not reconciliation["source_delete_rows_match"]:
                result["warnings"].append("source_delete_total_mismatch")
    except (OSError, sqlite3.DatabaseError) as error:
        result["errors"].append(f"{type(error).__name__}:{error}"[:2000])
        return result

    health = result["runtime_health"]
    if health.get("available"):
        values = health.get("values", {})
        if _counter_mismatch(values.get("events_archived"), result["counts"]["events"]):
            result["warnings"].append("runtime_event_counter_mismatch")
        if _counter_mismatch(
            values.get("deliveries_archived"),
            result["counts"]["deliveries"],
        ):
            result["warnings"].append("runtime_delivery_counter_mismatch")
        if values.get("last_archive_error"):
            result["warnings"].append("runtime_last_archive_error_present")
    elif health.get("error"):
        result["warnings"].append("runtime_health_unavailable")

    result["passed"] = not result["errors"]
    return result
