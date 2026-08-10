"""Read-only operational diagnostics exposed to Mini App administrators."""

from __future__ import annotations

import os
import resource
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

UTC = timezone.utc
PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"


def empty_admin_diagnostics() -> dict:
    """Return the stable diagnostics schema used for unavailable values."""

    return {
        "websocket": "unknown",
        "lastWebsocketMessage": None,
        "lastRestRecovery": None,
        "lastError": None,
        "outbox": 0,
        "deliveries": 0,
        "deliveryFailures": 0,
        "deliveryRetries": 0,
        "deliveryPermanentFailures": 0,
        "databases": "unknown",
        "fvgDatabaseStatus": "unknown",
        "fvgDatabaseBytes": 0,
        "fundingDatabaseStatus": "unknown",
        "fundingDatabaseBytes": 0,
        "jsonSettingsBytes": 0,
        "processMemoryBytes": 0,
        "loadAverage": None,
        "diskFreeBytes": 0,
        "diskTotalBytes": 0,
        "pid": os.getpid(),
        "release": "unknown",
        "gitCommit": "unknown",
        "pythonVersion": sys.version.split()[0],
    }


def normalize_admin_diagnostics(value: Any) -> dict:
    """Merge a provider result into the stable public diagnostics schema."""

    result = empty_admin_diagnostics()
    if isinstance(value, dict):
        for key in result:
            if key in value:
                result[key] = value[key]
    return result


def _time_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _sqlite_status(path: Path | None) -> tuple[str, int]:
    if path is None or not path.exists():
        return "unknown", 0
    try:
        with closing(sqlite3.connect(path, timeout=5)) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        status = "ok" if row and row[0] == "ok" else "warning"
    except (OSError, sqlite3.Error):
        status = "warning"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return status, max(0, int(size))


def _memory_bytes() -> int:
    proc_status = Path("/proc/self/status")
    if proc_status.exists():
        try:
            for line in proc_status.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines():
                if line.startswith("VmRSS:"):
                    return max(0, int(line.split()[1]) * 1024)
        except (OSError, ValueError, IndexError):
            pass
    try:
        amount = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, ValueError):
        return 0
    # Linux reports KiB; macOS reports bytes. Production is Linux.
    return max(0, amount * 1024)


def _read_text(path: Path, default: str = "unknown") -> str:
    try:
        return path.read_text(encoding="utf-8").strip() or default
    except OSError:
        return default


def collect_admin_diagnostics(
    *,
    funding_database_path: str | os.PathLike,
    event_store_provider: Callable[[], Any] | None = None,
    project_dir: Path | None = None,
    data_dir: Path | None = None,
) -> dict:
    """Collect bounded operational metrics without performing mutations."""

    project = Path(project_dir or PROJECT_DIR)
    data = Path(data_dir or DATA_DIR)
    result = empty_admin_diagnostics()
    funding_path = Path(funding_database_path)
    event_path: Path | None = None

    provider = event_store_provider
    if provider is None:
        def provider():
            from alerts.scheduler_15m import get_fvg_service

            return get_fvg_service().event_store

    try:
        event_store = provider()
        event_path = Path(event_store.path)
        health = event_store.health()
        connected = health.get("ws_connected")
        result.update(
            {
                "websocket": (
                    "connected"
                    if connected is True
                    else "disconnected"
                    if connected is False
                    else "unknown"
                ),
                "lastWebsocketMessage": _time_text(health.get("last_ws_message")),
                "lastRestRecovery": _time_text(health.get("last_rest_recovery")),
                "lastError": str(health.get("last_error")) if health.get("last_error") else None,
                "outbox": int(health.get("outbox") or 0),
                "deliveries": int(health.get("deliveries") or 0),
                "deliveryFailures": int(health.get("delivery_failures") or 0),
                "deliveryRetries": int(health.get("delivery_retries") or 0),
                "deliveryPermanentFailures": int(
                    health.get("delivery_permanent_failures") or 0
                ),
            }
        )
    except Exception:
        # Diagnostics must not make the settings endpoint unavailable.
        pass

    fvg_status, fvg_bytes = _sqlite_status(event_path)
    funding_status, funding_bytes = _sqlite_status(funding_path)
    statuses = (fvg_status, funding_status)
    if statuses and all(status == "ok" for status in statuses):
        database_status = "ok"
    elif any(status == "warning" for status in statuses):
        database_status = "warning"
    else:
        database_status = "unknown"

    json_files = (
        "fvg_alert_settings.json",
        "user_preferences.json",
        "runtime_settings.json",
        "access_control.json",
        "user_activity.json",
    )
    json_bytes = 0
    for name in json_files:
        try:
            json_bytes += (data / name).stat().st_size
        except OSError:
            continue

    try:
        load_average = [round(float(value), 2) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load_average = None

    try:
        disk = shutil.disk_usage(data if data.exists() else project)
        disk_free, disk_total = int(disk.free), int(disk.total)
    except OSError:
        disk_free, disk_total = 0, 0

    result.update(
        {
            "databases": database_status,
            "fvgDatabaseStatus": fvg_status,
            "fvgDatabaseBytes": fvg_bytes,
            "fundingDatabaseStatus": funding_status,
            "fundingDatabaseBytes": funding_bytes,
            "jsonSettingsBytes": max(0, int(json_bytes)),
            "processMemoryBytes": _memory_bytes(),
            "loadAverage": load_average,
            "diskFreeBytes": max(0, disk_free),
            "diskTotalBytes": max(0, disk_total),
            "pid": os.getpid(),
            "release": _read_text(project / "VERSION"),
            "gitCommit": _read_text(project / "BUILD_COMMIT"),
            "pythonVersion": sys.version.split()[0],
        }
    )
    return normalize_admin_diagnostics(result)
