"""Read-only SQLite size snapshots with bounded historical storage."""

from __future__ import annotations

import os
import sqlite3
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


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class SQLiteSnapshotCollector:
    """Collect file, page and object metrics without modifying the target DB."""

    def __init__(
        self,
        *,
        include_row_counts: bool = False,
        include_integrity_check: bool = False,
    ):
        self.include_row_counts = bool(include_row_counts)
        self.include_integrity_check = bool(include_integrity_check)

    @staticmethod
    def _base_snapshot(database_key: str, path: Path, captured_at: datetime) -> dict:
        return {
            "database_key": str(database_key),
            "database_path": str(path),
            "captured_at": captured_at.isoformat(),
            "available": False,
            "error_message": None,
            "main_bytes": _file_size(path),
            "wal_bytes": _file_size(Path(f"{path}-wal")),
            "shm_bytes": _file_size(Path(f"{path}-shm")),
            "page_size": None,
            "page_count": None,
            "freelist_count": None,
            "allocated_bytes": None,
            "free_bytes": None,
            "used_bytes": None,
            "journal_mode": None,
            "user_version": None,
            "schema_version": None,
            "quick_check": None,
            "dbstat_available": False,
            "objects": [],
        }

    @staticmethod
    def _object_types(connection: sqlite3.Connection) -> dict[str, str]:
        rows = connection.execute(
            """
            SELECT name, type
            FROM sqlite_schema
            WHERE name IS NOT NULL
              AND name NOT IN ('sqlite_schema', 'sqlite_sequence')
              AND name NOT LIKE 'sqlite_stat%'
            """
        ).fetchall()
        return {str(row["name"]): str(row["type"]) for row in rows}

    def _objects(self, connection: sqlite3.Connection) -> tuple[list[dict], bool]:
        object_types = self._object_types(connection)
        sizes: dict[str, tuple[int | None, int | None]] = {}
        dbstat_available = True
        try:
            rows = connection.execute(
                """
                SELECT name, SUM(pgsize) AS bytes, COUNT(*) AS pages
                FROM dbstat
                GROUP BY name
                """
            ).fetchall()
            sizes = {
                str(row["name"]): (
                    int(row["bytes"] or 0),
                    int(row["pages"] or 0),
                )
                for row in rows
            }
        except sqlite3.DatabaseError:
            dbstat_available = False

        objects = []
        for name, object_type in sorted(object_types.items()):
            bytes_value, pages_value = sizes.get(name, (None, None))
            row_count = None
            if self.include_row_counts and object_type == "table" and not name.startswith("sqlite_"):
                row_count = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(name)}"
                    ).fetchone()[0]
                )
            objects.append(
                {
                    "object_name": name,
                    "object_type": object_type,
                    "bytes": bytes_value,
                    "pages": pages_value,
                    "row_count": row_count,
                }
            )
        return objects, dbstat_available

    def collect(
        self,
        database_key: str,
        path: str | os.PathLike,
        *,
        now: datetime | None = None,
    ) -> dict:
        captured_at = _utc(now)
        path = Path(path)
        snapshot = self._base_snapshot(database_key, path, captured_at)
        if not path.exists():
            snapshot["error_message"] = "database_file_missing"
            return snapshot

        try:
            uri = f"{path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(
                uri,
                uri=True,
                timeout=30,
                factory=_ClosingConnection,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=30000")
            with connection:
                page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
                page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
                freelist_count = int(
                    connection.execute("PRAGMA freelist_count").fetchone()[0]
                )
                journal_mode = str(
                    connection.execute("PRAGMA journal_mode").fetchone()[0]
                )
                user_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                schema_version = int(
                    connection.execute("PRAGMA schema_version").fetchone()[0]
                )
                quick_check = None
                if self.include_integrity_check:
                    quick_check = "; ".join(
                        str(row[0])
                        for row in connection.execute("PRAGMA quick_check").fetchall()
                    )
                objects, dbstat_available = self._objects(connection)
        except (OSError, sqlite3.DatabaseError) as error:
            snapshot["error_message"] = str(error)[:2000]
            return snapshot

        allocated_bytes = page_size * page_count
        free_bytes = page_size * freelist_count
        snapshot.update(
            available=True,
            page_size=page_size,
            page_count=page_count,
            freelist_count=freelist_count,
            allocated_bytes=allocated_bytes,
            free_bytes=free_bytes,
            used_bytes=max(0, allocated_bytes - free_bytes),
            journal_mode=journal_mode,
            user_version=user_version,
            schema_version=schema_version,
            quick_check=quick_check,
            dbstat_available=dbstat_available,
            objects=objects,
        )
        return snapshot


class SQLiteObservabilityStore:
    """Persist bounded database and object snapshots in the existing FVG DB."""

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
                CREATE TABLE IF NOT EXISTS database_observation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    database_key TEXT NOT NULL,
                    database_path TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    available INTEGER NOT NULL,
                    error_message TEXT,
                    main_bytes INTEGER NOT NULL,
                    wal_bytes INTEGER NOT NULL,
                    shm_bytes INTEGER NOT NULL,
                    page_size INTEGER,
                    page_count INTEGER,
                    freelist_count INTEGER,
                    allocated_bytes INTEGER,
                    free_bytes INTEGER,
                    used_bytes INTEGER,
                    journal_mode TEXT,
                    user_version INTEGER,
                    schema_version INTEGER,
                    quick_check TEXT,
                    dbstat_available INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(database_key, captured_at)
                );
                CREATE INDEX IF NOT EXISTS idx_database_observation_latest
                    ON database_observation_runs(database_key, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_database_observation_retention
                    ON database_observation_runs(captured_at);

                CREATE TABLE IF NOT EXISTS database_object_snapshots (
                    run_id INTEGER NOT NULL,
                    object_name TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    bytes INTEGER,
                    pages INTEGER,
                    row_count INTEGER,
                    PRIMARY KEY(run_id, object_name, object_type),
                    FOREIGN KEY(run_id) REFERENCES database_observation_runs(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_database_object_history
                    ON database_object_snapshots(object_name, run_id);
                """
            )

    @staticmethod
    def _run(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["id"] = int(result["id"])
        result["available"] = bool(result["available"])
        result["dbstat_available"] = bool(result["dbstat_available"])
        return result

    def record(self, snapshot: dict) -> int:
        captured_at = str(snapshot["captured_at"])
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO database_observation_runs(
                    database_key, database_path, captured_at, available,
                    error_message, main_bytes, wal_bytes, shm_bytes,
                    page_size, page_count, freelist_count, allocated_bytes,
                    free_bytes, used_bytes, journal_mode, user_version,
                    schema_version, quick_check, dbstat_available, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(database_key, captured_at) DO UPDATE SET
                    database_path=excluded.database_path,
                    available=excluded.available,
                    error_message=excluded.error_message,
                    main_bytes=excluded.main_bytes,
                    wal_bytes=excluded.wal_bytes,
                    shm_bytes=excluded.shm_bytes,
                    page_size=excluded.page_size,
                    page_count=excluded.page_count,
                    freelist_count=excluded.freelist_count,
                    allocated_bytes=excluded.allocated_bytes,
                    free_bytes=excluded.free_bytes,
                    used_bytes=excluded.used_bytes,
                    journal_mode=excluded.journal_mode,
                    user_version=excluded.user_version,
                    schema_version=excluded.schema_version,
                    quick_check=excluded.quick_check,
                    dbstat_available=excluded.dbstat_available,
                    created_at=excluded.created_at
                """,
                (
                    str(snapshot["database_key"]),
                    str(snapshot["database_path"]),
                    captured_at,
                    int(bool(snapshot.get("available"))),
                    snapshot.get("error_message"),
                    int(snapshot.get("main_bytes") or 0),
                    int(snapshot.get("wal_bytes") or 0),
                    int(snapshot.get("shm_bytes") or 0),
                    snapshot.get("page_size"),
                    snapshot.get("page_count"),
                    snapshot.get("freelist_count"),
                    snapshot.get("allocated_bytes"),
                    snapshot.get("free_bytes"),
                    snapshot.get("used_bytes"),
                    snapshot.get("journal_mode"),
                    snapshot.get("user_version"),
                    snapshot.get("schema_version"),
                    snapshot.get("quick_check"),
                    int(bool(snapshot.get("dbstat_available"))),
                    created_at,
                ),
            )
            run_id = int(
                connection.execute(
                    """
                    SELECT id FROM database_observation_runs
                    WHERE database_key=? AND captured_at=?
                    """,
                    (str(snapshot["database_key"]), captured_at),
                ).fetchone()[0]
            )
            connection.execute(
                "DELETE FROM database_object_snapshots WHERE run_id=?",
                (run_id,),
            )
            connection.executemany(
                """
                INSERT INTO database_object_snapshots(
                    run_id, object_name, object_type, bytes, pages, row_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        str(item["object_name"]),
                        str(item["object_type"]),
                        item.get("bytes"),
                        item.get("pages"),
                        item.get("row_count"),
                    )
                    for item in snapshot.get("objects", [])
                ],
            )
            connection.commit()
        return run_id

    def objects(self, run_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT object_name, object_type, bytes, pages, row_count
                FROM database_object_snapshots
                WHERE run_id=?
                ORDER BY bytes DESC, object_name
                """,
                (int(run_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest(self, database_key: str | None = None):
        with self._connect() as connection:
            if database_key is not None:
                row = connection.execute(
                    """
                    SELECT * FROM database_observation_runs
                    WHERE database_key=?
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """,
                    (str(database_key),),
                ).fetchone()
                return self._run(row)
            rows = connection.execute(
                "SELECT * FROM database_observation_runs ORDER BY captured_at DESC"
            ).fetchall()
        latest_by_key = {}
        for row in rows:
            key = str(row["database_key"])
            latest_by_key.setdefault(key, self._run(row))
        return latest_by_key

    def growth(self, database_key: str, *, since: datetime | None = None) -> dict | None:
        params: list[object] = [str(database_key)]
        where = "database_key=? AND available=1"
        if since is not None:
            where += " AND captured_at>=?"
            params.append(_utc(since).isoformat())
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM database_observation_runs
                WHERE {where}
                ORDER BY captured_at
                """,
                params,
            ).fetchall()
        if len(rows) < 2:
            return None
        first = self._run(rows[0])
        last = self._run(rows[-1])
        started = datetime.fromisoformat(first["captured_at"])
        finished = datetime.fromisoformat(last["captured_at"])

        def delta(name: str):
            left = first.get(name)
            right = last.get(name)
            if left is None or right is None:
                return None
            return int(right) - int(left)

        return {
            "database_key": str(database_key),
            "from_captured_at": first["captured_at"],
            "to_captured_at": last["captured_at"],
            "elapsed_seconds": max(0.0, (finished - started).total_seconds()),
            "main_bytes_delta": delta("main_bytes"),
            "wal_bytes_delta": delta("wal_bytes"),
            "allocated_bytes_delta": delta("allocated_bytes"),
            "used_bytes_delta": delta("used_bytes"),
        }

    def prune(
        self,
        *,
        retention_days: int = 90,
        batch_size: int = 500,
        now: datetime | None = None,
    ) -> int:
        cutoff = (_utc(now) - timedelta(days=max(1, int(retention_days)))).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id FROM database_observation_runs
                WHERE captured_at < ?
                ORDER BY captured_at
                LIMIT ?
                """,
                (cutoff, max(1, int(batch_size))),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM database_observation_runs WHERE id=?",
                    [(int(row["id"]),) for row in rows],
                )
            connection.commit()
        return len(rows)


class SQLiteObservabilityService:
    """Collect both runtime DBs and retain a bounded history."""

    DEFAULT_DATABASES = {
        "fvg": Path("data/fvg_event_store.sqlite3"),
        "funding": Path("data/funding_alerts.sqlite3"),
    }

    def __init__(
        self,
        *,
        databases: dict[str, str | os.PathLike] | None = None,
        store: SQLiteObservabilityStore | None = None,
        include_row_counts: bool = False,
        include_integrity_check: bool = False,
        retention_days: int = 90,
    ):
        self.databases = {
            str(key): Path(path)
            for key, path in (databases or self.DEFAULT_DATABASES).items()
        }
        self.store = store or SQLiteObservabilityStore()
        self.collector = SQLiteSnapshotCollector(
            include_row_counts=include_row_counts,
            include_integrity_check=include_integrity_check,
        )
        self.retention_days = max(1, int(retention_days))

    def capture(self, *, now: datetime | None = None) -> dict:
        captured_at = _utc(now)
        snapshots = []
        for database_key, path in sorted(self.databases.items()):
            snapshot = self.collector.collect(
                database_key,
                path,
                now=captured_at,
            )
            snapshot["run_id"] = self.store.record(snapshot)
            snapshots.append(snapshot)
        pruned = self.store.prune(
            retention_days=self.retention_days,
            now=captured_at,
        )
        return {
            "captured_at": captured_at.isoformat(),
            "snapshots": snapshots,
            "pruned": pruned,
        }
