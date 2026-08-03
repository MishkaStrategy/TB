from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_mini_app.sh"
TBBOT_DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_tbbot_mini_app.sh"
TBBOT_PROFILE = ROOT / "deploy" / "mini-app" / "tbbot.env"
NGINX_TEMPLATE = ROOT / "deploy" / "mini-app" / "nginx-site.conf.template"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
VALIDATOR = ROOT / "scripts" / "validate_mini_app_artifact.py"
COMMIT = "a" * 40
DOMAIN = "tbbot.duckdns.org"
API_BASE_URL = f"https://{DOMAIN}"


class MiniAppDeploymentAssetsTests(unittest.TestCase):
    def test_deploy_scripts_have_valid_bash_syntax(self) -> None:
        for script in (DEPLOY_SCRIPT, TBBOT_DEPLOY_SCRIPT):
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    ["bash", "-n", str(script)],
                    cwd=ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_deploy_script_keeps_production_activation_separate(self) -> None:
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("prepare-artifact", script)
        self.assertIn("validate_mini_app_artifact.py", script)
        self.assertIn("MINI_APP_ALLOWED_ORIGINS=https://${DOMAIN}", script)
        self.assertNotIn("npm ci", script)
        self.assertNotIn("npm run build", script)
        self.assertNotIn("require_command node", script)
        self.assertNotIn("require_command npm", script)
        self.assertNotIn("systemctl restart fvg-alert-bot", script)
        self.assertNotIn("systemctl enable --now fvg-alert-bot", script)
        self.assertNotIn("/etc/fvg-alert-bot.env", script)
        self.assertNotIn("ufw", script.lower())
        self.assertNotIn("setmenubutton", script.lower())

    def test_tbbot_profile_is_locked_to_approved_public_target(self) -> None:
        profile = TBBOT_PROFILE.read_text(encoding="utf-8")
        wrapper = TBBOT_DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("MINI_APP_DOMAIN=tbbot.duckdns.org", profile)
        self.assertIn("MINI_APP_EXPECTED_IPV4=188.137.236.73", profile)
        self.assertIn("MINI_APP_BACKEND_PORT=18080", profile)
        self.assertNotIn("DUCKDNS_TOKEN=", profile)
        self.assertNotIn("TELEGRAM_TOKEN=", profile)

        self.assertIn('[[ "${DOMAIN}" == "tbbot.duckdns.org" ]]', wrapper)
        self.assertIn('[[ "${EXPECTED_IPV4}" == "188.137.236.73" ]]', wrapper)
        self.assertIn("getent ahostsv4", wrapper)
        self.assertIn("HTTPS-развёртывание остановлено", wrapper)
        self.assertNotIn("systemctl restart fvg-alert-bot", wrapper)

    def test_nginx_template_only_exposes_local_backend(self) -> None:
        template = NGINX_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("server_name __MINI_APP_DOMAIN__;", template)
        self.assertIn("127.0.0.1:__MINI_APP_BACKEND_PORT__", template)
        self.assertIn("location /api/", template)
        self.assertIn("location = /healthz", template)
        self.assertIn("https://telegram.org", template)
        self.assertNotIn("0.0.0.0:__MINI_APP_BACKEND_PORT__", template)
        rendered = template.replace("__MINI_APP_BACKEND_PORT__", "18080")
        self.assertIn("127.0.0.1:18080", rendered)
        self.assertNotIn("0.0.0.0:18080", rendered)
        self.assertNotIn("[::]:18080", rendered)

    def test_nginx_template_supports_spa_and_safe_caching(self) -> None:
        template = NGINX_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("try_files $uri $uri/ /index.html;", template)
        self.assertIn("location = /index.html", template)
        self.assertIn("expires -1;", template)
        self.assertIn("location /assets/", template)
        self.assertIn("expires 1y;", template)

    def test_ci_builds_and_publishes_bound_frontend_artifact(self) -> None:
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('node-version: "22"', workflow)
        self.assertIn("npm ci --no-audit --no-fund", workflow)
        self.assertIn("npm run typecheck", workflow)
        self.assertIn("VITE_API_BASE_URL: https://tbbot.duckdns.org", workflow)
        self.assertIn("test -f dist/index.html", workflow)
        self.assertIn("tb-mini-app-frontend", workflow)
        self.assertIn('"commit": "%s"', workflow)
        self.assertIn('"domain": "tbbot.duckdns.org"', workflow)
        self.assertIn('"apiBaseUrl": "https://tbbot.duckdns.org"', workflow)
        self.assertIn('"builtAt": "%s"', workflow)

    def _artifact(self, directory: Path, **manifest_overrides: str) -> Path:
        artifact = directory / "artifact"
        artifact.mkdir()
        (artifact / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
        manifest = {
            "commit": COMMIT,
            "domain": DOMAIN,
            "apiBaseUrl": API_BASE_URL,
            "builtAt": "2026-08-03T12:00:00Z",
            **manifest_overrides,
        }
        (artifact / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return artifact

    def _validate(self, artifact: Path, output: Path, *, commit: str = COMMIT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(VALIDATOR),
                "--artifact",
                str(artifact),
                "--output",
                str(output),
                "--commit",
                commit,
                "--domain",
                DOMAIN,
                "--api-base-url",
                API_BASE_URL,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_artifact_manifest_and_index_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = self._artifact(root)
            completed = self._validate(artifact, root / "output")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((root / "output" / "index.html").is_file())

            (artifact / "index.html").unlink()
            completed = self._validate(artifact, root / "missing-index")
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("index.html", completed.stderr)

    def test_artifact_rejects_wrong_manifest_bindings(self) -> None:
        cases = {
            "domain": "evil.example",
            "apiBaseUrl": "https://evil.example",
            "commit": "b" * 40,
        }
        for key, value in cases.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                artifact = self._artifact(root, **{key: value})
                completed = self._validate(artifact, root / "output")
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(key, completed.stderr)

    def test_artifact_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "artifact.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("../escape", "unsafe")
                zipped.writestr("index.html", "<div id=\"root\"></div>")
                zipped.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "commit": COMMIT,
                            "domain": DOMAIN,
                            "apiBaseUrl": API_BASE_URL,
                            "builtAt": "2026-08-03T12:00:00Z",
                        }
                    ),
                )
            completed = self._validate(archive, root / "output")
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unsafe artifact path", completed.stderr)
            self.assertFalse((root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
