import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import tarfile

from database.backup_audit import build_manifest, sha256_file, verify_archive


UTC = timezone.utc


class BackupChecksumBindingTests(unittest.TestCase):
    def test_correct_digest_with_wrong_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "settings.json").write_text("{}", encoding="utf-8")
            build_manifest(
                snapshot,
                run_id="run-1",
                created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
                archive_name="backup.tar.gz",
            )
            archive = root / "backup.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                output.add(snapshot, arcname=".")
            checksum = root / "backup.tar.gz.sha256"
            checksum.write_text(
                f"{sha256_file(archive)}  different.tar.gz\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "filename"):
                verify_archive(archive, checksum_path=checksum)


if __name__ == "__main__":
    unittest.main()
