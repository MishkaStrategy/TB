"""Safe operational actions and metrics for the Telegram admin panel."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone


UTC = timezone.utc


def process_memory_bytes() -> int:
    """Return current resident memory on Linux, with a portable fallback."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as source:
            resident_pages = int(source.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(usage) if sys.platform == "darwin" else int(usage) * 1024
        except (ImportError, OSError, ValueError):
            return 0


def active_user_count(registry, now=None, hours=24) -> int:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = now - timedelta(hours=hours)
    count = 0
    for user in registry.users().values():
        try:
            last_seen = datetime.fromisoformat(user.get("last_seen", "")).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        count += last_seen >= cutoff
    return count


def event_counts(event_store, now=None) -> tuple[int, int]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    hour_cutoff = (now - timedelta(hours=1)).isoformat()
    day_cutoff = (now - timedelta(days=1)).isoformat()
    with event_store._connect() as connection:
        row = connection.execute(
            """
            SELECT
              SUM(CASE WHEN detected_at >= ? THEN 1 ELSE 0 END) AS hour_count,
              SUM(CASE WHEN detected_at >= ? THEN 1 ELSE 0 END) AS day_count
            FROM events
            """,
            (hour_cutoff, day_cutoff),
        ).fetchone()
    return int(row["hour_count"] or 0), int(row["day_count"] or 0)


def problematic_symbols(event_store, limit=5) -> list[dict]:
    with event_store._connect() as connection:
        rows = connection.execute(
            """
            SELECT event.symbol AS symbol,
                   COUNT(*) AS pending,
                   COALESCE(SUM(outbox.attempts), 0) AS attempts,
                   MAX(outbox.last_error) AS last_error
            FROM outbox
            JOIN events AS event ON event.event_id = outbox.event_id
            GROUP BY event.symbol
            ORDER BY attempts DESC, pending DESC, event.symbol
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def clear_stuck_outbox(event_store, *, attempts=3, older_than_minutes=60) -> int:
    cutoff = (datetime.now(UTC) - timedelta(minutes=older_than_minutes)).isoformat()
    with event_store._connect() as connection:
        cursor = connection.execute(
            """
            DELETE FROM outbox
            WHERE attempts >= ? OR created_at < ?
            """,
            (max(1, int(attempts)), cutoff),
        )
        removed = max(0, int(cursor.rowcount))
    if removed:
        event_store.increment_health("admin_cleared_outbox", removed)
    return removed


def disable_symbol_for_all_users(settings, symbol: str) -> int:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    def mutate(data):
        affected = 0
        for user in data.setdefault("users", {}).values():
            symbol_data = user.setdefault("symbols", {}).get(symbol)
            if symbol_data and symbol_data.get("enabled", True):
                symbol_data["enabled"] = False
                affected += 1
        return affected

    return settings._transaction(mutate)


def background_tasks(application) -> list[str]:
    names = set()
    job_queue = application.job_queue
    if job_queue is not None:
        jobs = job_queue.jobs() if callable(getattr(job_queue, "jobs", None)) else ()
        names.update(job.name or "job-without-name" for job in jobs)
    for task in asyncio.all_tasks():
        if not task.done() and task.get_name():
            names.add(task.get_name())
    return sorted(names)


async def run_recovery(service, bot) -> tuple[int, int]:
    symbols = sorted(await asyncio.to_thread(service.settings.active_symbols))
    events_count = 0
    failures = 0
    for symbol in symbols:
        try:
            events = await asyncio.to_thread(service.recover, symbol)
            events_count += len(events)
            await service.deliver(bot, events)
            service.event_store.increment_health("rest_recoveries")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures += 1
            service.event_store.update_health(last_error=str(error))
            service.event_store.increment_health("recovery_failures")
    service.event_store.increment_health("manual_recoveries")
    return events_count, failures
