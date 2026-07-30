"""Backup manifests, archive verification and durable backup-run history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath


UTC = timezone.utc
MANIFEST_NAME = "BACKUP_MANIFEST.json"
MANIFEST_SCHEMA_VERSION = 1
RUNNING = "running"
SUCCESS = "success"
FAILED = "failed"
INTERRUPTED = "interrupted"
FINAL_STATUSES = frozenset({SUCCESS, FAILED, INTERRUPTED})


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        result = datetime.now(UTC)
    elif isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _iso(value: datetime | str | None = None) -> str:
    return _utc(value).isoformat()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(source) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def sqlite_quick_check(path: str | os.PathLike) -> str:
    path = Path(path).resolve()
    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(
        uri,
        uri=True,
        timeout=30,
        factory=_ClosingConnection,
    )
    with connection:
        rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    return "; ".join(rows)


def _safe_relative_path(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in {"", "."}:
        return ""
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe archive path: {value}")
    return path.as_posix()


def _snapshot_files(snapshot_dir: Path) -> list[Path]:
    files = []
    for root, dirnames, filenames in os.walk(snapshot_dir, followlinks=False):
        root_path = Path(root)
        for name in dirnames:
            path = root_path / name
            if path.is_symlink():
                raise ValueError(f"Snapshot symlink is not allowed: {path}")
        for name in filenames:
            path = root_path / name
            if path.is_symlink():
                raise ValueError(f"Snapshot symlink is not allowed: {path}")
            if not path.is_file():
                raise ValueError(f"Snapshot special file is not allowed: {path}")
            if path.name == MANIFEST_NAME and path.parent == snapshot_dir:
                continue
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(snapshot_dir).as_posix())


def build_manifest(
    snapshot_dir: str | os.PathLike,
    *,
    run_id: str,
    created_at: datetime | str,
    archive_name: str,
    release_ref: str | None = None,
) -> dict:
    snapshot_dir = Path(snapshot_dir).resolve()
    if not snapshot_dir.is_dir():
        raise ValueError(f"Snapshot directory does not exist: {snapshot_dir}")

    files = []
    total_bytes = 0
    for path in _snapshot_files(snapshot_dir):
        relative = path.relative_to(snapshot_dir).as_posix()
        size = int(path.stat().st_size)
        item = {
            "path": relative,
            "size": size,
            "sha256": sha256_file(path),
            "kind": "sqlite" if path.suffix == ".sqlite3" else "file",
        }
        if item["kind"] == "sqlite":
            check = sqlite_quick_check(path)
            if check != "ok":
                raise RuntimeError(f"SQLite quick_check failed for {relative}: {check}")
            item["quick_check"] = check
        files.append(item)
        total_bytes += size

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": str(run_id),
        "created_at": _iso(created_at),
        "archive_name": str(archive_name),
        "release_ref": str(release_ref or "unknown"),
        "file_count": len(files),
        "total_uncompressed_bytes": total_bytes,
        "files": files,
    }
    destination = snapshot_dir / MANIFEST_NAME
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(destination)
    return manifest


def _archive_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        relative = _safe_relative_path(member.name)
        if relative == "":
            if not member.isdir():
                raise ValueError("Archive root member must be a directory")
            continue
        if member.isdir():
            continue
        # Compatibility with pre-fix archives created on macOS.  Only known
        # Apple filesystem metadata is ignored; every other unexpected member
        # remains subject to strict manifest verification below.
        if any(part.startswith("._") or part == ".DS_Store" for part in relative.split("/")):
            continue
        if not member.isfile():
            raise ValueError(f"Archive special member is not allowed: {member.name}")
        if relative in members:
            raise ValueError(f"Duplicate archive member: {relative}")
        members[relative] = member
    return members


def _validated_manifest(manifest: dict) -> tuple[dict[str, dict], int]:
    if int(manifest.get("schema_version", 0)) != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError("Unsupported backup manifest schema")
    items = manifest.get("files")
    if not isinstance(items, list):
        raise RuntimeError("Backup manifest files must be a list")

    expected: dict[str, dict] = {}
    total_bytes = 0
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("Backup manifest file entry must be an object")
        original = str(item.get("path", ""))
        relative = _safe_relative_path(original)
        if not relative or relative != original:
            raise RuntimeError(f"Backup manifest path is not canonical: {original}")
        if relative == MANIFEST_NAME:
            raise RuntimeError("Backup manifest cannot list itself")
        if relative in expected:
            raise RuntimeError(f"Duplicate backup manifest path: {relative}")
        size = int(item.get("size", -1))
        if size < 0:
            raise RuntimeError(f"Invalid backup manifest size: {relative}")
        digest = str(item.get("sha256", "")).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(f"Invalid backup manifest SHA-256: {relative}")
        kind = str(item.get("kind", ""))
        if kind not in {"file", "sqlite"}:
            raise RuntimeError(f"Invalid backup manifest file kind: {relative}")
        if kind == "sqlite" and item.get("quick_check") != "ok":
            raise RuntimeError(f"SQLite manifest entry is not verified: {relative}")
        expected[relative] = item
        total_bytes += size

    if int(manifest.get("file_count", -1)) != len(expected):
        raise RuntimeError("Backup manifest file_count does not match entries")
    if int(manifest.get("total_uncompressed_bytes", -1)) != total_bytes:
        raise RuntimeError("Backup manifest total_uncompressed_bytes does not match")
    if not str(manifest.get("run_id", "")):
        raise RuntimeError("Backup manifest run_id is missing")
    if not str(manifest.get("archive_name", "")):
        raise RuntimeError("Backup manifest archive_name is missing")
    return expected, total_bytes


def verify_archive(
    archive_path: str | os.PathLike,
    *,
    checksum_path: str | os.PathLike | None = None,
) -> dict:
    archive_path = Path(archive_path)
    archive_sha256 = sha256_file(archive_path)
    if checksum_path is not None:
        line = Path(checksum_path).read_text(encoding="utf-8").strip()
        parts = line.split()
        if not parts or parts[0].lower() != archive_sha256:
            raise RuntimeError("Archive checksum sidecar does not match")
        if len(parts) < 2 or Path(parts[-1].lstrip("*")).name != archive_path.name:
            raise RuntimeError("Archive checksum sidecar filename does not match")

    with tarfile.open(archive_path, "r:gz") as archive:
        members = _archive_members(archive)
        manifest_member = members.get(MANIFEST_NAME)
        if manifest_member is None:
            raise RuntimeError(f"Archive does not contain {MANIFEST_NAME}")
        source = archive.extractfile(manifest_member)
        if source is None:
            raise RuntimeError("Manifest cannot be read from archive")
        manifest_bytes = source.read()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        expected_files, total_bytes = _validated_manifest(manifest)

        expected_names = set(expected_files) | {MANIFEST_NAME}
        if set(members) != expected_names:
            missing = sorted(expected_names - set(members))
            extra = sorted(set(members) - expected_names)
            raise RuntimeError(
                f"Archive members differ from manifest missing={missing} extra={extra}"
            )

        with tempfile.TemporaryDirectory(prefix="backup-verify-") as tempdir_value:
            tempdir = Path(tempdir_value)
            for relative, item in sorted(expected_files.items()):
                member = members[relative]
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Archive member cannot be read: {relative}")
                digest, size = _sha256_stream(source)
                if digest != str(item["sha256"]).lower():
                    raise RuntimeError(f"SHA-256 mismatch for {relative}")
                if size != int(item["size"]):
                    raise RuntimeError(f"Size mismatch for {relative}")
                if item["kind"] == "sqlite":
                    destination = tempdir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise RuntimeError(
                            f"SQLite archive member cannot be read: {relative}"
                        )
                    with destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    check = sqlite_quick_check(destination)
                    if check != "ok":
                        raise RuntimeError(
                            f"Archived SQLite quick_check failed for {relative}: {check}"
                        )

    return {
        "archive_sha256": archive_sha256,
        "archive_bytes": int(archive_path.stat().st_size),
        "archive_name": str(manifest["archive_name"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "file_count": len(expected_files),
        "total_uncompressed_bytes": total_bytes,
        "run_id": str(manifest["run_id"]),
    }


def write_checksum(
    archive_path: str | os.PathLike,
    checksum_path: str | os.PathLike,
) -> str:
    archive_path = Path(archive_path)
    checksum_path = Path(checksum_path)
    digest = sha256_file(archive_path)
    temporary = checksum_path.with_suffix(checksum_path.suffix + ".tmp")
    temporary.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(checksum_path)
    return digest


class BackupHistoryStore:
    """Durable operational history stored alongside backup archives."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare()
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _prepare(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS backup_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    archive_bytes INTEGER,
                    archive_sha256 TEXT,
                    manifest_sha256 TEXT,
                    file_count INTEGER,
                    total_uncompressed_bytes INTEGER,
                    error_step TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_backup_runs_started
                    ON backup_runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_backup_runs_status
                    ON backup_runs(status, started_at DESC);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def mark_stale_running(
        self,
        *,
        max_age_hours: int = 24,
        now: datetime | str | None = None,
    ) -> int:
        current = _utc(now)
        cutoff = (current - timedelta(hours=max(1, int(max_age_hours)))).isoformat()
        timestamp = current.isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE backup_runs
                SET status=?, completed_at=?, error_step='process',
                    error_message='Backup process ended without final status',
                    updated_at=?
                WHERE status=? AND started_at < ?
                """,
                (INTERRUPTED, timestamp, timestamp, RUNNING, cutoff),
            )
        return max(0, int(cursor.rowcount))

    def begin(
        self,
        archive_path: str | os.PathLike,
        *,
        run_id: str | None = None,
        started_at: datetime | str | None = None,
    ) -> str:
        self.mark_stale_running(now=started_at)
        run_id = str(run_id or uuid.uuid4())
        timestamp = _iso(started_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backup_runs(
                    run_id, started_at, status, archive_path,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    timestamp,
                    RUNNING,
                    str(Path(archive_path)),
                    timestamp,
                    timestamp,
                ),
            )
        return run_id

    def finish_success(
        self,
        run_id: str,
        archive_path: str | os.PathLike,
        checksum_path: str | os.PathLike,
        *,
        completed_at: datetime | str | None = None,
    ) -> dict:
        archive_path = Path(archive_path)
        summary = verify_archive(archive_path, checksum_path=checksum_path)
        if summary["run_id"] != str(run_id):
            raise RuntimeError("Archive manifest run ID does not match history run")
        if summary["archive_name"] != archive_path.name:
            raise RuntimeError("Archive manifest filename does not match final archive")
        timestamp = _iso(completed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE backup_runs
                SET status=?, completed_at=?, archive_path=?, archive_bytes=?,
                    archive_sha256=?, manifest_sha256=?, file_count=?,
                    total_uncompressed_bytes=?, error_step=NULL,
                    error_message=NULL, updated_at=?
                WHERE run_id=? AND status=?
                """,
                (
                    SUCCESS,
                    timestamp,
                    str(archive_path),
                    summary["archive_bytes"],
                    summary["archive_sha256"],
                    summary["manifest_sha256"],
                    summary["file_count"],
                    summary["total_uncompressed_bytes"],
                    timestamp,
                    str(run_id),
                    RUNNING,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Backup history run is missing or already finalized")
        return summary

    def finish_failure(
        self,
        run_id: str,
        *,
        error_step: str,
        error_message: str,
        completed_at: datetime | str | None = None,
    ) -> bool:
        timestamp = _iso(completed_at)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE backup_runs
                SET status=?, completed_at=?, error_step=?, error_message=?,
                    updated_at=?
                WHERE run_id=? AND status=?
                """,
                (
                    FAILED,
                    timestamp,
                    str(error_step)[:200],
                    str(error_message)[:2000],
                    timestamp,
                    str(run_id),
                    RUNNING,
                ),
            )
        return cursor.rowcount == 1

    def get(self, run_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM backup_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
        return self._row(row)

    def latest(self, *, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM backup_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(
        self,
        *,
        retention_days: int = 180,
        batch_size: int = 500,
        now: datetime | str | None = None,
    ) -> int:
        cutoff = (_utc(now) - timedelta(days=max(0, int(retention_days)))).isoformat()
        placeholders = ",".join("?" for _ in FINAL_STATUSES)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT run_id FROM backup_runs
                WHERE status IN ({placeholders}) AND completed_at < ?
                ORDER BY completed_at
                LIMIT ?
                """,
                (*sorted(FINAL_STATUSES), cutoff, max(1, int(batch_size))),
            ).fetchall()
            if rows:
                connection.executemany(
                    "DELETE FROM backup_runs WHERE run_id=?",
                    [(row["run_id"],) for row in rows],
                )
        return len(rows)


def _command_begin(args) -> None:
    store = BackupHistoryStore(args.history)
    print(store.begin(args.archive, started_at=args.started_at))


def _command_build_manifest(args) -> None:
    manifest = build_manifest(
        args.snapshot,
        run_id=args.run_id,
        created_at=args.created_at,
        archive_name=args.archive_name,
        release_ref=args.release_ref,
    )
    print(json.dumps({"file_count": manifest["file_count"]}, sort_keys=True))


def _command_verify(args) -> None:
    summary = verify_archive(args.archive, checksum_path=args.checksum)
    print(json.dumps(summary, sort_keys=True))


def _command_checksum(args) -> None:
    print(write_checksum(args.archive, args.output))


def _command_finish_success(args) -> None:
    store = BackupHistoryStore(args.history)
    summary = store.finish_success(
        args.run_id,
        args.archive,
        args.checksum,
        completed_at=args.completed_at,
    )
    print(json.dumps(summary, sort_keys=True))


def _command_finish_failure(args) -> None:
    store = BackupHistoryStore(args.history)
    store.finish_failure(
        args.run_id,
        error_step=args.step,
        error_message=args.message,
        completed_at=args.completed_at,
    )


def _command_prune(args) -> None:
    store = BackupHistoryStore(args.history)
    print(store.prune(retention_days=args.retention_days))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    begin = commands.add_parser("begin")
    begin.add_argument("--history", required=True)
    begin.add_argument("--archive", required=True)
    begin.add_argument("--started-at", required=True)
    begin.set_defaults(func=_command_begin)

    manifest = commands.add_parser("build-manifest")
    manifest.add_argument("--snapshot", required=True)
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--created-at", required=True)
    manifest.add_argument("--archive-name", required=True)
    manifest.add_argument("--release-ref", default="unknown")
    manifest.set_defaults(func=_command_build_manifest)

    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--checksum")
    verify.set_defaults(func=_command_verify)

    checksum = commands.add_parser("checksum")
    checksum.add_argument("--archive", required=True)
    checksum.add_argument("--output", required=True)
    checksum.set_defaults(func=_command_checksum)

    success = commands.add_parser("finish-success")
    success.add_argument("--history", required=True)
    success.add_argument("--run-id", required=True)
    success.add_argument("--archive", required=True)
    success.add_argument("--checksum", required=True)
    success.add_argument("--completed-at", required=True)
    success.set_defaults(func=_command_finish_success)

    failure = commands.add_parser("finish-failure")
    failure.add_argument("--history", required=True)
    failure.add_argument("--run-id", required=True)
    failure.add_argument("--step", required=True)
    failure.add_argument("--message", required=True)
    failure.add_argument("--completed-at", required=True)
    failure.set_defaults(func=_command_finish_failure)

    prune = commands.add_parser("prune")
    prune.add_argument("--history", required=True)
    prune.add_argument("--retention-days", required=True, type=int)
    prune.set_defaults(func=_command_prune)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
