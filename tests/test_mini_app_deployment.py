from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_mini_app.sh"
NGINX_TEMPLATE = ROOT / "deploy" / "mini-app" / "nginx-site.conf.template"


class MiniAppDeploymentAssetsTests(unittest.TestCase):
    def test_deploy_script_has_valid_bash_syntax(self) -> None:
        completed = subprocess.run(
            ["bash", "-n", str(DEPLOY_SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_deploy_script_keeps_production_activation_separate(self) -> None:
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('VITE_API_BASE_URL="https://${DOMAIN}"', script)
        self.assertIn("MINI_APP_ALLOWED_ORIGINS=https://${DOMAIN}", script)
        self.assertNotIn("systemctl restart fvg-alert-bot", script)
        self.assertNotIn("systemctl enable --now fvg-alert-bot", script)
        self.assertNotIn("setmenubutton", script.lower())

    def test_nginx_template_only_exposes_local_backend(self) -> None:
        template = NGINX_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("server_name __MINI_APP_DOMAIN__;", template)
        self.assertIn("127.0.0.1:__MINI_APP_BACKEND_PORT__", template)
        self.assertIn("location /api/", template)
        self.assertIn("location = /healthz", template)
        self.assertIn("https://telegram.org", template)
        self.assertNotIn("0.0.0.0:__MINI_APP_BACKEND_PORT__", template)

    def test_nginx_template_supports_spa_and_safe_caching(self) -> None:
        template = NGINX_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("try_files $uri $uri/ /index.html;", template)
        self.assertIn("location = /index.html", template)
        self.assertIn("expires -1;", template)
        self.assertIn("location /assets/", template)
        self.assertIn("expires 1y;", template)


if __name__ == "__main__":
    unittest.main()
