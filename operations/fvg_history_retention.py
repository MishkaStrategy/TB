"""Opt-in archive-before-delete retention for the runtime FVG event store."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MethodType

from database.fvg_history_archive import FvgHistoryArchive
from database.fvg_history_config import (
    FVG_HISTORY_ARCHIVE_BATCH_SIZE,
    FVG_HISTORY_ARCHIVE_ENABLED,
    FVG_HISTORY_ARCHIVE_MAX_BATCHES,
    FVG_HISTORY_ARCHIVE_PATH,
    FVG_HISTORY_RETENTION_DAYS,
)


UTC = timezone.utc


def _load(value, default=None):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _increment(connection, key: str, amount: int):
    row = connection.execute(
        "SELECT value_json FROM health WHERE key=?",
        (str(key),),
    ).fetchone()
    previous = _load(row["value_json"], 0) if row else 0
    try:
        value = int(previous) + int(amount)
    except (TypeError, ValueError):
        value = int(amount)
    connection.execute(
        """
        INSERT INTO health(key, value_json) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json
        """,
        (str(key), _dump(value)),
    )


def _set_health(connection, **values):
    connection.executemany(
        """
        INSERT INTO health(key, value_json) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json
        """,
        [(str(key), _dump(value)) for key, value in values.items()],
    )


def _archive_prune_if_due(self, connection, now: datetime):
    # record_event calls prune before its INSERT. Acquire the runtime write lock
    # before selecting candidates so no concurrent outbox row can appear between
    # eligibility evaluation and source deletion.
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")

    row = connection.execute(
        "SELECT value_json FROM health WHERE key='last_pruned_at'"
    ).fetchone()
    if row:
        raw = _load(row["value_json"])
        try:
            last_pruned = datetime.fromisoformat(raw).astimezone(UTC)
        except (TypeError, ValueError):
            last_pruned = None
        if last_pruned and now - last_pruned < self.PRUNE_INTERVAL:
            return

    cutoff = now - timedelta(days=self._history_retention_days)
    totals = {
        "events_archived": 0,
        "deliveries_archived": 0,
        "source_deleted": 0,
    }
    batch_full = False
    connection.execute("SAVEPOINT fvg_history_archive")
    try:
        for _ in range(self._history_archive_max_batches):
            result = self._history_archive.archive_and_delete(
                connection,
                cutoff=cutoff,
                now=now,
            )
            for key in totals:
                totals[key] += int(result.get(key) or 0)
            batch_full = bool(result.get("batch_full"))
            if not batch_full or not result.get("source_deleted"):
                break
    except Exception as error:
        connection.execute("ROLLBACK TO fvg_history_archive")
        connection.execute("RELEASE fvg_history_archive")
        _increment(connection, "fvg_archive_failures", 1)
        _set_health(
            connection,
            last_archive_error=f"{type(error).__name__}: {error}"[:2000],
            last_archive_failure_at=now.isoformat(),
        )
        return
    connection.execute("RELEASE fvg_history_archive")

    _set_health(
        connection,
        last_pruned_at=now.isoformat(),
        last_archive_at=now.isoformat(),
        last_archive_error=None,
        fvg_archive_backlog_possible=batch_full,
    )
    if totals["events_archived"]:
        _increment(connection, "events_archived", totals["events_archived"])
        _increment(connection, "events_pruned", totals["source_deleted"])
    if totals["deliveries_archived"]:
        _increment(
            connection,
            "deliveries_archived",
            totals["deliveries_archived"],
        )


def configure_fvg_history_retention(
    event_store,
    *,
    enabled: bool = FVG_HISTORY_ARCHIVE_ENABLED,
    archive_path: str | Path = FVG_HISTORY_ARCHIVE_PATH,
    retention_days: int = FVG_HISTORY_RETENTION_DAYS,
    batch_size: int = FVG_HISTORY_ARCHIVE_BATCH_SIZE,
    max_batches: int = FVG_HISTORY_ARCHIVE_MAX_BATCHES,
    archive: FvgHistoryArchive | None = None,
) -> bool:
    """Install one idempotent per-instance prune override before stream startup."""
    if not enabled:
        return False
    if getattr(event_store, "_history_archive_configured", False):
        return True

    source_path = Path(event_store.path).resolve()
    archive_path = Path(archive_path).resolve()
    if source_path == archive_path:
        raise ValueError("FVG history archive path must differ from runtime DB")

    event_store._history_archive = archive or FvgHistoryArchive(
        archive_path,
        batch_size=batch_size,
    )
    event_store._history_retention_days = max(1, int(retention_days))
    event_store._history_archive_max_batches = max(1, int(max_batches))
    event_store._history_archive_original_prune = event_store._prune_if_due
    event_store._prune_if_due = MethodType(_archive_prune_if_due, event_store)
    event_store._history_archive_configured = True
    return True
