import unittest
from pathlib import Path


class InstallVdsScriptTests(unittest.TestCase):
    def test_pre_switch_backup_uses_staging_runtime(self):
        script = Path("scripts/install_vds.sh").read_text(encoding="utf-8")
        expected = "\n".join(
            [
                'INSTALL_DIR="${STAGING_DIR}" \\',
                'DATA_DIR="${STATE_DIR}" \\',
                'BACKUP_DIR="${BACKUP_DIR}" \\',
                'RETENTION_DAYS=14 \\',
                'PYTHON="${STAGING_DIR}/.venv/bin/python" \\',
                '  "${STAGING_DIR}/scripts/backup_data.sh"',
            ]
        )

        self.assertIn(expected, script)

    def test_backup_happens_before_staging_becomes_active(self):
        script = Path("scripts/install_vds.sh").read_text(encoding="utf-8")
        backup_call = script.index('"${STAGING_DIR}/scripts/backup_data.sh"')
        activate_release = script.index('mv "${STAGING_DIR}" "${INSTALL_DIR}"')

        self.assertLess(backup_call, activate_release)


if __name__ == "__main__":
    unittest.main()
