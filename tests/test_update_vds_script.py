import unittest
from pathlib import Path


class UpdateVdsScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = Path("scripts/update_vds.sh").read_text(encoding="utf-8")

    def test_supports_reviewed_tag_or_remote_branch(self):
        self.assertIn('TARGET_REF="${TARGET_REF:-main}"', self.script)
        self.assertIn('refs/remotes/origin/${TARGET_REF}^{commit}', self.script)
        self.assertIn('refs/tags/${TARGET_REF}^{commit}', self.script)
        self.assertIn('checkout --detach "refs/tags/${TARGET_REF}"', self.script)

    def test_can_pin_exact_audited_commit(self):
        self.assertIn('EXPECTED_COMMIT="${EXPECTED_COMMIT:-}"', self.script)
        self.assertIn('ожидался commit ${EXPECTED_COMMIT}', self.script)

    def test_keeps_backup_and_sqlite_verification(self):
        self.assertIn('bash "${PROJECT_DIR}/scripts/backup_data.sh"', self.script)
        self.assertIn('PRAGMA quick_check', self.script)
        self.assertIn('funding_alerts.sqlite3', self.script)
        self.assertIn('fvg_event_store.sqlite3', self.script)


if __name__ == "__main__":
    unittest.main()
