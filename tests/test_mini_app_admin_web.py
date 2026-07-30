import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from database.access_control import AccessRegistry
from database.runtime_settings import RuntimeSettings
from database.user_activity import UserActivityRegistry
from mini_app_backend.admin_actions import MiniAppAdminActions
from mini_app_backend.web import create_mini_app_application


BOT_TOKEN = "123456:test-token"


def signed_init_data(user_id=1):
    fields = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAAdminQuery",
        "user": json.dumps(
            {"id": user_id, "first_name": "Admin", "username": "admin"},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class StubSettingsService:
    def __init__(self, access, activity, runtime):
        self.access_registry = access
        self.activity_registry = activity
        self.runtime_settings = runtime
        self.env_allowed_ids = frozenset({1, 9})
        self.env_admin_ids = frozenset({1})
        self.admin_checker = lambda telegram_id: telegram_id == 1

    def read_settings(self, user):
        return {
            "settings": {
                "general": {"language": "ru"},
                "admin": {
                    "available": self.admin_checker(user.id),
                    "publicAccessEnabled": self.runtime_settings.public_access_enabled(
                        default=False
                    ),
                    "allowedUsers": [],
                    "diagnostics": {},
                },
            },
            "user": {"id": user.id, "firstName": user.first_name},
            "source": "api",
            "updatedAt": "2026-07-30T00:00:00+00:00",
        }

    def save_settings(self, user, settings):
        return self.read_settings(user)


class MiniAppAdminWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.access = AccessRegistry(root / "access.json")
        self.activity = UserActivityRegistry(root / "activity.json")
        self.runtime = RuntimeSettings(root / "runtime.json")
        service = StubSettingsService(self.access, self.activity, self.runtime)
        actions = MiniAppAdminActions.from_settings_service(service)
        app = create_mini_app_application(
            bot_token=BOT_TOKEN,
            service=service,
            admin_actions=actions,
            allowed_origins={"https://app.example.com"},
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.admin_headers = {"X-Telegram-Init-Data": signed_init_data(1)}

    async def asyncTearDown(self):
        await self.client.close()
        self.temporary.cleanup()

    async def confirmation(self, action, telegram_id=None):
        payload = {"action": action}
        if telegram_id is not None:
            payload["telegramId"] = telegram_id
        response = await self.client.post(
            "/api/mini-app/admin/confirmations",
            headers=self.admin_headers,
            json=payload,
        )
        self.assertEqual(response.status, 201)
        return await response.json()

    async def test_settings_exposes_fail_closed_admin_capabilities(self):
        response = await self.client.get(
            "/api/mini-app/settings",
            headers=self.admin_headers,
        )
        self.assertEqual(response.status, 200)
        capabilities = (await response.json())["settings"]["admin"]["capabilities"]
        self.assertTrue(capabilities["accessWrite"])
        self.assertTrue(capabilities["allowlistWrite"])
        self.assertFalse(capabilities["backup"])
        self.assertFalse(capabilities["restart"])

    async def test_non_admin_cannot_create_challenge(self):
        response = await self.client.post(
            "/api/mini-app/admin/confirmations",
            headers={"X-Telegram-Init-Data": signed_init_data(42)},
            json={"action": "backup.create"},
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"]["code"], "ADMIN_REQUIRED")

    async def test_allowlist_add_and_remove_full_http_flow(self):
        challenge = await self.confirmation("allowlist.add", 42)
        response = await self.client.post(
            "/api/mini-app/admin/allowlist",
            headers=self.admin_headers,
            json={
                "telegramId": 42,
                "name": "Михаил",
                "username": "michael",
                "confirmationToken": challenge["token"],
                "confirmationText": challenge["confirmationText"],
            },
        )
        self.assertEqual(response.status, 201)
        self.assertTrue(self.access.is_allowed(42))

        remove = await self.confirmation("allowlist.remove", 42)
        response = await self.client.delete(
            "/api/mini-app/admin/allowlist/42",
            headers=self.admin_headers,
            json={
                "confirmationToken": remove["token"],
                "confirmationText": remove["confirmationText"],
            },
        )
        self.assertEqual(response.status, 200)
        self.assertIsNone(self.access.status(42))

    async def test_access_mode_uses_dedicated_confirmed_endpoint(self):
        challenge = await self.confirmation("access.public")
        response = await self.client.put(
            "/api/mini-app/admin/access",
            headers=self.admin_headers,
            json={
                "publicAccessEnabled": True,
                "confirmationToken": challenge["token"],
                "confirmationText": challenge["confirmationText"],
            },
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(self.runtime.public_access_enabled(default=False))

    async def test_confirmation_cannot_be_retargeted(self):
        challenge = await self.confirmation("allowlist.add", 42)
        response = await self.client.post(
            "/api/mini-app/admin/allowlist",
            headers=self.admin_headers,
            json={
                "telegramId": 43,
                "confirmationToken": challenge["token"],
                "confirmationText": challenge["confirmationText"],
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["error"]["code"],
            "CONFIRMATION_MISMATCH",
        )

    async def test_unwired_backup_fails_closed_after_confirmation(self):
        challenge = await self.confirmation("backup.create")
        response = await self.client.post(
            "/api/mini-app/admin/backup",
            headers=self.admin_headers,
            json={
                "confirmationToken": challenge["token"],
                "confirmationText": challenge["confirmationText"],
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(
            (await response.json())["error"]["code"],
            "BACKUP_ACTION_UNAVAILABLE",
        )

    async def test_cors_advertises_admin_methods(self):
        response = await self.client.options(
            "/api/mini-app/admin/allowlist",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertEqual(response.status, 204)
        methods = response.headers["Access-Control-Allow-Methods"]
        self.assertIn("POST", methods)
        self.assertIn("DELETE", methods)


if __name__ == "__main__":
    unittest.main()
