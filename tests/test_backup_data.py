import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts" / "backup_data.sh"


class RuntimeBackupTests(unittest.TestCase):
    def test_backup_contains_consistent_event_and_funding_databases(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            data_dir = root / "data"
            backup_dir = root / "backups"
            data_dir.mkdir()

            event_path = data_dir / "fvg_event_store.sqlite3"
            funding_path = data_dir / "funding_alerts.sqlite3"
            event_connection = sqlite3.connect(event_path)
            funding_connection = sqlite3.connect(funding_path)

            for connection, table, value in (
                (event_connection, "backup_probe", "event-row"),
                (funding_connection, "backup_probe", "funding-row"),
            ):
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(f"CREATE TABLE {table}(value TEXT NOT NULL)")
                connection.execute(f"INSERT INTO {table}(value) VALUES (?)", (value,))
                connection.commit()

            (data_dir / "runtime_settings.json").write_text(
                '{"public_access_enabled": false}',
                encoding="utf-8",
            )

            environment = {
                **os.environ,
                "INSTALL_DIR": str(PROJECT_ROOT),
                "DATA_DIR": str(data_dir),
                "BACKUP_DIR": str(backup_dir),
                "RETENTION_DAYS": "14",
                "PYTHON": sys.executable,
            }
            try:
                result = subprocess.run(
                    ["bash", str(BACKUP_SCRIPT)],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                event_connection.close()
                funding_connection.close()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            archives = list(backup_dir.glob("fvg-alert-bot-*.tar.gz"))
            self.assertEqual(len(archives), 1)
            extract_dir = root / "extracted"
            extract_dir.mkdir()
            with tarfile.open(archives[0], "r:gz") as archive:
                archive.extractall(extract_dir)

            self.assertTrue((extract_dir / "runtime_settings.json").is_file())
            self.assertFalse((extract_dir / "fvg_event_store.sqlite3-wal").exists())
            self.assertFalse((extract_dir / "funding_alerts.sqlite3-wal").exists())

            for database, expected in (
                ("fvg_event_store.sqlite3", "event-row"),
                ("funding_alerts.sqlite3", "funding-row"),
            ):
                path = extract_dir / database
                self.assertTrue(path.is_file())
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        connection.execute("SELECT value FROM backup_probe").fetchone()[0],
                        expected,
                    )
                    self.assertEqual(
                        connection.execute("PRAGMA quick_check").fetchone()[0],
                        "ok",
                    )


if __name__ == "__main__":
    unittest.main()
