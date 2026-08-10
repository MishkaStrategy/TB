import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.tag = f"v{self.version}"

    def test_version_is_semver(self):
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+$")

    def test_readme_matches_version(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"version-{self.version}-", readme)
        self.assertIn(f"Текущий релиз: **{self.version}**", readme)
        self.assertIn(f"TARGET_REF={self.tag}", readme)
        self.assertIn(f"EXPECTED_VERSION={self.version}", readme)
        self.assertIn(f"fvg-alert-bot-{self.version}.tar.gz", readme)
        self.assertNotIn("status-release--candidate", readme)
        self.assertNotIn("Следующий релиз:", readme)

    def test_updater_matches_version(self):
        updater = (ROOT / "scripts" / "update_vds.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f'EXPECTED_VERSION="${{EXPECTED_VERSION:-{self.version}}}"',
            updater,
        )
        self.assertIn(
            f"TARGET_REF={self.tag} EXPECTED_VERSION={self.version}",
            updater,
        )

    def test_vds_documentation_matches_version(self):
        document = (ROOT / "docs" / "VDS_BOT_API_ONLY_UPDATE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"## Update to {self.version}", document)
        self.assertIn(f"TARGET_REF={self.tag}", document)
        self.assertIn(f"EXPECTED_VERSION={self.version}", document)
        self.assertIn(f"installed version is `{self.version}`", document)
        self.assertIn("MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru", document)
        self.assertIn("MINI_APP_BACKEND_HOST=127.0.0.1", document)
        self.assertIn("MINI_APP_BACKEND_PORT=18080", document)

    def test_release_documents_and_changelog_exist(self):
        release_path = ROOT / "docs" / f"RELEASE_{self.version}.md"
        self.assertTrue(release_path.is_file(), release_path)
        release_text = release_path.read_text(encoding="utf-8")
        self.assertIn(f"# FVG Alert Bot {self.version}", release_text)
        self.assertIn("Telegram Mini App", release_text)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(
            changelog,
            rf"(?m)^## {re.escape(self.version)}(?:\s|—)",
        )

    def test_release_audit_matches_version(self):
        workflow = (
            ROOT / ".github" / "workflows" / "release-audit.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            f'test "$(tr -d \'\\r\\n\' < VERSION)" = "{self.version}"',
            workflow,
        )
        self.assertIn(
            f'EXPECTED_VERSION="${{EXPECTED_VERSION:-{self.version}}}"',
            workflow,
        )
        self.assertIn("tests.test_release_1_3_7_contract", workflow)
        self.assertIn("VITE_MOCK_MODE", workflow)
        self.assertIn('"/api/mini-app/market-overview"', workflow)
        self.assertIn("<TradingApp />", workflow)

    def test_release_workflow_is_immutable_and_idempotent(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("existingRef.data.object.sha !== context.sha", workflow)
        self.assertIn("refusing to republish it from", workflow)
        self.assertIn("two-parent merge commit on main", workflow)
        self.assertNotIn("--clobber", workflow)
        self.assertIn("archive_missing", workflow)
        self.assertIn("checksum_missing", workflow)
        self.assertIn("mini_app_backend/service.py", workflow)
        self.assertIn("telegram-mini-app/package.json", workflow)


if __name__ == "__main__":
    unittest.main()
