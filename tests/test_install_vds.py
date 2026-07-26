import unittest
from pathlib import Path


class InstallVdsScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = Path("scripts/install_vds.sh").read_text(encoding="utf-8")

    def test_pre_switch_backup_uses_staging_runtime(self):
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

        self.assertIn(expected, self.script)

    def test_backup_happens_before_staging_becomes_active(self):
        backup_call = self.script.index('"${STAGING_DIR}/scripts/backup_data.sh"')
        activate_release = self.script.index('mv "${STAGING_DIR}" "${INSTALL_DIR}"')

        self.assertLess(backup_call, activate_release)

    def test_install_checks_free_space_and_inodes(self):
        self.assertIn('MIN_FREE_MB="${FVG_INSTALL_MIN_FREE_MB:-512}"', self.script)
        self.assertIn(
            'MIN_FREE_INODES="${FVG_INSTALL_MIN_FREE_INODES:-5000}"',
            self.script,
        )
        self.assertIn('df -Pk "${filesystem_path}"', self.script)
        self.assertIn('df -Pi "${filesystem_path}"', self.script)
        self.assertGreaterEqual(self.script.count("check_storage_capacity"), 4)

    def test_pip_and_tests_use_staging_temp_without_cache(self):
        self.assertGreaterEqual(self.script.count("PIP_NO_CACHE_DIR=1"), 2)
        self.assertIn('TMPDIR="${STAGING_DIR}/tmp"', self.script)
        self.assertIn("export TMPDIR='${STAGING_DIR}/tmp'", self.script)
        self.assertIn("export MPLCONFIGDIR='${STAGING_DIR}/tmp/mpl'", self.script)
        self.assertIn('rm -rf "${STAGING_DIR}/data" "${STAGING_DIR}/tmp"', self.script)


if __name__ == "__main__":
    unittest.main()
