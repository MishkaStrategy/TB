import io
import json
import os
import sqlite3
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.backup_audit import (
    BACKUP_MANIFEST_NAME if False else MANIFEST_NAME,
    BackupHistoryStore,
    build_manifest,
    verify_archive,
    write_checksum,
)


UTC = timezone.utc


def create_database(path: Path, value="row"):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE probe(value TEXT NOT NULL)")
        connection.execute("INSERT INTO probe(value) VALUES (?)", (value,))
        connection.commit()


def create_archive(snapshot: Path, archive: Path):
    with tarfile.open(archive, "w:gz") as output:
        output.add(snapshot, arcname=".")


class BackupManifestTests(unittest.TestCase):
    def test_manifest_and_archive_verification_cover_files_and_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            database = snapshot / "state.sqlite3"
            create_database(database)
            (snapshot / "settings.json").write_text('{"enabled": true}', encoding="utf-8")
            created_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

            manifest = build_manifest(
                snapshot,
                run_id="run-1",
                created_at=created_at,
                archive_name="backup.tar.gz",
                release_ref="abc123",
            )
            archive = root / "backup.tar.gz"
            create_archive(snapshot, archive)
            checksum = root / "backup.tar.gz.sha256"
            write_checksum(archive, checksum)
            summary = verify_archive(archive, checksum_path=checksum)

            self.assertEqual(manifest["run_id"], "run-1")
            self.assertEqual(manifest["file_count"], 2)
            self.assertEqual(summary["run_id"], "run-1")
            self.assertEqual(summary["file_count"], 2)
            files = {item["path"]: item for item in manifest["files"]}
            self.assertEqual(files["state.sqlite3"]["quick_check"], "ok")
            self.assertEqual(len(files["settings.json"]["sha256"]), 64)

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "settings.json").write_text("{}", encoding="utf-8")
            build_manifest(
                snapshot,
                run_id="run-1",
                created_at=datetime.now(UTC),
                archive_name="backup.tar.gz",
            )
            archive = root / "backup.tar.gz"
            create_archive(snapshot, archive)
            checksum = root / "backup.tar.gz.sha256"
            checksum.write_text("0" * 64 + "  backup.tar.gz\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "checksum"):
                verify_archive(archive, checksum_path=checksum)

    def test_archive_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                payload = b"unsafe"
                member = tarfile.TarInfo("../outside.txt")
                member.size = len(payload)
                output.addfile(member, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
                verify_archive(archive)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_snapshot_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (snapshot / "link.txt").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symlink"):
                build_manifest(
                    snapshot,
                    run_id="run-1",
                    created_at=datetime.now(UTC),
                    archive_name="backup.tar.gz",
                )


class BackupHistoryStoreTests(unittest.TestCase):
    def test_success_history_is_verified_from_final_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            create_database(snapshot / "state.sqlite3")
            archive = root / "backup.tar.gz"
            checksum = root / "backup.tar.gz.sha256"
            history = BackupHistoryStore(root / "backup_history.sqlite3")
            started_at = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
            run_id = history.begin(archive, run_id="run-1", started_at=started_at)
            build_manifest(
                snapshot,
                run_id=run_id,
                created_at=started_at,
                archive_name=archive.name,
            )
            create_archive(snapshot, archive)
            write_checksum(archive, checksum)

            summary = history.finish_success(
                run_id,
                archive,
                checksum,
                completed_at=started_at + timedelta(minutes=1),
            )
            row = history.get(run_id)

            self.assertEqual(row["status"], "success")
            self.assertEqual(row["archive_sha256"], summary["archive_sha256"])
            self.assertGreater(row["archive_bytes"], 0)
            self.assertEqual(row["file_count"], 1)
            self.assertEqual(history.latest(limit=1)[0]["run_id"], run_id)

    def test_failure_stale_interruption_and_bounded_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            history = BackupHistoryStore(Path(directory) / "history.sqlite3")
            start = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
            failed = history.begin("failed.tar.gz", run_id="failed", started_at=start)
            history.finish_failure(
                failed,
                error_step="manifest",
                error_message="broken",
                completed_at=start + timedelta(minutes=1),
            )
            history.begin("stale.tar.gz", run_id="stale", started_at=start)

            interrupted = history.mark_stale_running(
                max_age_hours=24,
                now=start + timedelta(days=2),
            )
            deleted = history.prune(
                retention_days=1,
                batch_size=1,
                now=start + timedelta(days=3),
            )

            self.assertEqual(interrupted, 1)
            self.assertEqual(deleted, 1)
            self.assertEqual(len(history.latest(limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
