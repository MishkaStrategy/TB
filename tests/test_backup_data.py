import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts" / "backup_data.sh"
MANIFEST_NAME = "BACKUP_MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_environment(data_dir: Path, backup_dir: Path) -> dict:
    return {
        **os.environ,
        "INSTALL_DIR": str(PROJECT_ROOT),
        "DATA_DIR": str(data_dir),
        "BACKUP_DIR": str(backup_dir),
        "RETENTION_DAYS": "14",
        "HISTORY_RETENTION_DAYS": "180",
        "PYTHON": sys.executable,
        "RELEASE_REF": "test-release",
        "FVG_HISTORY_ARCHIVE_PATH": str(
            data_dir / "archive" / "fvg_history.sqlite3"
        ),
    }


class RuntimeBackupTests(unittest.TestCase):
    def test_backup_contains_verified_manifest_databases_and_history(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            data_dir = root / "data"
            backup_dir = root / "backups"
            data_dir.mkdir()
            (data_dir / "archive").mkdir()

            event_path = data_dir / "fvg_event_store.sqlite3"
            funding_path = data_dir / "funding_alerts.sqlite3"
            archive_path = data_dir / "archive" / "fvg_history.sqlite3"
            event_connection = sqlite3.connect(event_path)
            funding_connection = sqlite3.connect(funding_path)
            archive_connection = sqlite3.connect(archive_path)

            for connection, table, value in (
                (event_connection, "backup_probe", "event-row"),
                (funding_connection, "backup_probe", "funding-row"),
                (archive_connection, "backup_probe", "archive-row"),
            ):
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(f"CREATE TABLE {table}(value TEXT NOT NULL)")
                connection.execute(f"INSERT INTO {table}(value) VALUES (?)", (value,))
                connection.commit()

            (data_dir / "runtime_settings.json").write_text(
                '{"public_access_enabled": false}',
                encoding="utf-8",
            )
            manual_backups = data_dir / ".manual_backups"
            manual_backups.mkdir()
            (manual_backups / "old-backup.tar.gz").write_bytes(b"not recursive")

            try:
                result = subprocess.run(
                    ["bash", str(BACKUP_SCRIPT)],
                    cwd=PROJECT_ROOT,
                    env=backup_environment(data_dir, backup_dir),
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                event_connection.close()
                funding_connection.close()
                archive_connection.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("created and verified", result.stdout)

            archives = list(backup_dir.glob("fvg-alert-bot-*.tar.gz"))
            checksums = list(backup_dir.glob("fvg-alert-bot-*.tar.gz.sha256"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(len(checksums), 1)
            expected_checksum = checksums[0].read_text(encoding="utf-8").split()[0]
            self.assertEqual(expected_checksum, sha256_file(archives[0]))

            extract_dir = root / "extracted"
            extract_dir.mkdir()
            with tarfile.open(archives[0], "r:gz") as archive:
                archive.extractall(extract_dir)

            self.assertTrue((extract_dir / "runtime_settings.json").is_file())
            self.assertTrue((extract_dir / MANIFEST_NAME).is_file())
            self.assertFalse((extract_dir / ".manual_backups").exists())
            self.assertFalse((extract_dir / "fvg_event_store.sqlite3-wal").exists())
            self.assertFalse((extract_dir / "funding_alerts.sqlite3-wal").exists())
            self.assertFalse(
                (extract_dir / "archive" / "fvg_history.sqlite3-wal").exists()
            )

            manifest = json.loads(
                (extract_dir / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["release_ref"], "test-release")
            self.assertEqual(manifest["file_count"], 4)
            manifest_files = {item["path"]: item for item in manifest["files"]}
            self.assertEqual(
                set(manifest_files),
                {
                    "archive/fvg_history.sqlite3",
                    "fvg_event_store.sqlite3",
                    "funding_alerts.sqlite3",
                    "runtime_settings.json",
                },
            )

            for relative, item in manifest_files.items():
                path = extract_dir / relative
                self.assertEqual(item["size"], path.stat().st_size)
                self.assertEqual(item["sha256"], sha256_file(path))

            for database, expected in (
                ("fvg_event_store.sqlite3", "event-row"),
                ("funding_alerts.sqlite3", "funding-row"),
                ("archive/fvg_history.sqlite3", "archive-row"),
            ):
                path = extract_dir / database
                self.assertTrue(path.is_file())
                self.assertEqual(manifest_files[database]["quick_check"], "ok")
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute("SELECT value FROM backup_probe").fetchone()[0],
                        expected,
                    )
                    self.assertEqual(
                        connection.execute("PRAGMA quick_check").fetchone()[0],
                        "ok",
                    )

            history_path = backup_dir / "backup_history.sqlite3"
            self.assertTrue(history_path.is_file())
            with sqlite3.connect(history_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute("SELECT * FROM backup_runs").fetchall()
            self.assertEqual(len(rows), 1)
            history = dict(rows[0])
            self.assertEqual(history["status"], "success")
            self.assertEqual(history["archive_sha256"], expected_checksum)
            self.assertEqual(
                history["manifest_sha256"],
                sha256_file(extract_dir / MANIFEST_NAME),
            )
            self.assertEqual(history["file_count"], 4)
            self.assertIsNone(history["error_message"])

    def test_backup_suppresses_macos_appledouble_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            data_dir = root / "data"
            backup_dir = root / "backups"
            tools_dir = root / "tools"
            data_dir.mkdir()
            tools_dir.mkdir()

            (data_dir / "runtime_settings.json").write_text(
                '{"public_access_enabled": false}',
                encoding="utf-8",
            )
            (data_dir / "._runtime_settings.json").write_bytes(b"appledouble")
            (data_dir / ".DS_Store").write_bytes(b"finder metadata")

            real_tar = shutil.which("tar")
            self.assertIsNotNone(real_tar)
            tar_wrapper = tools_dir / "tar"
            tar_wrapper.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [[ "${COPYFILE_DISABLE:-}" != "1" ]]; then
  echo "COPYFILE_DISABLE was not enabled" >&2
  exit 97
fi
exec "${REAL_TAR}" "$@"
""",
                encoding="utf-8",
            )
            tar_wrapper.chmod(0o755)

            environment = backup_environment(data_dir, backup_dir)
            environment["REAL_TAR"] = str(real_tar)
            environment["PATH"] = f"{tools_dir}{os.pathsep}{environment['PATH']}"
            result = subprocess.run(
                ["bash", str(BACKUP_SCRIPT)],
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archives = list(backup_dir.glob("fvg-alert-bot-*.tar.gz"))
            self.assertEqual(len(archives), 1)
            with tarfile.open(archives[0], "r:gz") as archive:
                names = [
                    name.removeprefix("./")
                    for name in archive.getnames()
                    if name not in {"", ".", "./"}
                ]
                manifest_member = archive.extractfile(MANIFEST_NAME)
                self.assertIsNotNone(manifest_member)
                manifest = json.load(manifest_member)

            self.assertFalse(
                any(Path(name).name.startswith("._") for name in names),
                names,
            )
            self.assertNotIn(".DS_Store", names)
            self.assertEqual(
                {item["path"] for item in manifest["files"]},
                {"runtime_settings.json"},
            )

    def test_corrupt_source_database_is_not_published_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            data_dir = root / "data"
            backup_dir = root / "backups"
            data_dir.mkdir()
            (data_dir / "fvg_event_store.sqlite3").write_bytes(b"not a sqlite database")

            result = subprocess.run(
                ["bash", str(BACKUP_SCRIPT)],
                cwd=PROJECT_ROOT,
                env=backup_environment(data_dir, backup_dir),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(backup_dir.glob("fvg-alert-bot-*.tar.gz")), [])
            self.assertEqual(
                list(backup_dir.glob("fvg-alert-bot-*.tar.gz.sha256")),
                [],
            )
            with sqlite3.connect(backup_dir / "backup_history.sqlite3") as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute("SELECT * FROM backup_runs").fetchone()
            self.assertIsNotNone(row)
            row = dict(row)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["error_step"], "snapshot_fvg_database")
            self.assertIn("status", row["error_message"])


if __name__ == "__main__":
    unittest.main()
