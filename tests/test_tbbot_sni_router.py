from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "manage_tbbot_sni_router.sh"
STREAM = ROOT / "deploy" / "mini-app" / "nginx-stream-sni.conf.template"
HTTPS = ROOT / "deploy" / "mini-app" / "nginx-mini-app-https.conf.template"
HTTP = ROOT / "deploy" / "mini-app" / "nginx-site.conf.template"


class TBBotSniRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_bash_syntax_and_transaction_commands(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("preflight", "prepare", "apply", "status", "verify", "commit", "rollback"):
            self.assertIn(f"{command})", self.script)
        self.assertIn("set -euo pipefail", self.script)
        self.assertIn("flock -n 9", self.script)

    def test_snapshot_and_automatic_rollback_are_fail_closed(self) -> None:
        self.assertIn("/var/backups/tbbot-sni-router", self.script)
        self.assertIn("docker commit --pause=true", self.script)
        self.assertIn("container-inspect.json", self.script)
        self.assertIn("sha256sum --check --strict", self.script)
        self.assertIn("systemd-run", self.script)
        self.assertIn("--on-active=30m", self.script)
        self.assertIn("AUTO ROLLBACK ARMED", self.script)
        self.assertIn("if (( rc != 0 )); then rollback", self.script)
        self.assertNotIn("commit_change \"${SNAPSHOT}\"", self.script)

    def test_sni_routes_only_approved_name_and_defaults_to_xray(self) -> None:
        stream = STREAM.read_text(encoding="utf-8")
        self.assertIn("tbbot.duckdns.org mini_app_https;", stream)
        self.assertIn("default             amnezia_xray;", stream)
        self.assertIn("server 127.0.0.1:8443;", stream)
        self.assertIn("server 127.0.0.1:2443;", stream)
        self.assertIn("listen 0.0.0.0:443;", stream)
        self.assertIn("ssl_preread on;", stream)
        self.assertNotIn("ssl_certificate", stream)

    def test_internal_services_are_loopback_only(self) -> None:
        https = HTTPS.read_text(encoding="utf-8")
        self.assertIn("listen 127.0.0.1:8443 ssl;", https)
        self.assertIn("proxy_pass http://127.0.0.1:18080;", https)
        for forbidden in ("0.0.0.0:8443", "0.0.0.0:2443", "0.0.0.0:18080"):
            self.assertNotIn(forbidden, STREAM.read_text() + https)

    def test_certbot_uses_http_webroot_only(self) -> None:
        self.assertIn("certbot certonly --webroot", self.script)
        self.assertIn("--webroot-path", self.script)
        self.assertNotIn("certbot --nginx", self.script)
        self.assertIn("/.well-known/acme-challenge/", HTTP.read_text(encoding="utf-8"))

    def test_preflight_rejects_missing_source_sni_conflict_and_email(self) -> None:
        self.assertIn("no canonical Compose or Amnezia source", self.script)
        self.assertIn("is already an Xray Reality serverName", self.script)
        self.assertIn("Xray image digest changed", self.script)
        self.assertIn("TLS certificate does not match", self.script)
        self.assertIn("an automatic rollback timer is already active", self.script)

    def test_recreation_changes_only_target_binding_and_rollback_restores_inspect(self) -> None:
        self.assertIn("container_port == '443/tcp' and mode == 'sni'", self.script)
        self.assertIn("hi,hp='127.0.0.1','2443'", self.script)
        self.assertIn("image=d['Image']", self.script)
        self.assertIn("payload_image", self.script)
        self.assertIn("docker','cp", self.script)
        self.assertIn('recreate_container "${SNAPSHOT}" original', self.script)
        self.assertIn('rm -f "${STREAM_CONFIG}"', self.script)
        self.assertNotIn("rm -rf /etc/nginx", self.script)
        self.assertIn("docker port", self.script)
        rollback_body = self.script.split("rollback()", 1)[1].split("verify()", 1)[0]
        self.assertLess(rollback_body.index("systemctl stop nginx"), rollback_body.index("recreate_container"))
        self.assertLess(rollback_body.index("recreate_container"), rollback_body.index("systemctl start nginx"))
        self.assertIn("Nginx did not release external port 443", rollback_body)

    def test_verify_preserves_production_and_xray_invariants(self) -> None:
        self.assertIn("verify_xray_invariants", self.script)
        self.assertIn("Xray invariants: OK", self.script)
        self.assertIn("bot-env.sha256", self.script)
        self.assertIn("bot-state.txt", self.script)
        self.assertIn("Mini App backend must remain disabled", self.script)
        self.assertIn("protected port 8080 changed", self.script)

    def test_protected_production_surfaces_are_not_modified(self) -> None:
        lowered = self.script.lower()
        self.assertNotIn("ufw allow", lowered)
        self.assertNotIn("ufw delete", lowered)
        self.assertIn("sha256sum /etc/fvg-alert-bot.env", self.script)
        self.assertNotIn(">/etc/fvg-alert-bot.env", self.script)
        self.assertNotIn("source /etc/fvg-alert-bot.env", self.script)
        self.assertNotIn("systemctl restart fvg-alert-bot", self.script)
        self.assertIn("systemctl is-active --quiet doh-socks-files.service", self.script)
        self.assertNotIn("systemctl restart doh-socks-files", self.script)
        self.assertNotIn("systemctl stop doh-socks-files", self.script)
        self.assertNotIn("setmenubutton", lowered)
        self.assertNotIn("botfather", lowered)

    def test_commit_requires_separate_external_vpn_confirmation(self) -> None:
        self.assertIn("vpn-external-confirmed", self.script)
        self.assertIn("external Amnezia/VPN confirmation marker is missing", self.script)
        commit_body = self.script.split("commit_change()", 1)[1].split("usage()", 1)[0]
        self.assertLess(commit_body.index("verify\n"), commit_body.index("systemctl stop"))


if __name__ == "__main__":
    unittest.main()
