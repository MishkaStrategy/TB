from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "deploy" / "mini-app" / "tbbot.env"
WRAPPER = ROOT / "scripts" / "deploy_tbbot_mini_app.sh"


class TBBotDeploymentProfileTests(unittest.TestCase):
    def test_profile_contains_only_approved_public_values(self) -> None:
        assignments = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in PROFILE.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        }
        self.assertEqual(
            assignments,
            {
                "MINI_APP_DOMAIN": "tbbot.duckdns.org",
                "MINI_APP_EXPECTED_IPV4": "188.137.236.73",
                "MINI_APP_BACKEND_PORT": "18080",
            },
        )

    def test_wrapper_is_fail_closed_around_dns_and_bot_activation(self) -> None:
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("preflight", wrapper)
        self.assertIn("getent ahostsv4", wrapper)
        self.assertIn('[[ "${DOMAIN}" == "tbbot.duckdns.org" ]]', wrapper)
        self.assertIn('[[ "${EXPECTED_IPV4}" == "188.137.236.73" ]]', wrapper)
        self.assertIn('[[ "${BACKEND_PORT}" == "18080" ]]', wrapper)
        self.assertIn("127.0.0.1:18080", wrapper)
        self.assertNotIn("MINI_APP_BACKEND_PORT=8080", wrapper)
        self.assertNotIn("0.0.0.0:18080", wrapper)
        self.assertNotIn("[::]:18080", wrapper)
        self.assertNotIn("systemctl restart fvg-alert-bot", wrapper)
        self.assertNotIn("setmenubutton", wrapper.lower())


if __name__ == "__main__":
    unittest.main()
