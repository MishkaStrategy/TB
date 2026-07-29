import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from mini_app_backend.web import create_mini_app_application


BOT_TOKEN = "123456:test-token"


def signed_init_data(user_id=42):
    fields = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAExampleQuery",
        "user": json.dumps(
            {"id": user_id, "first_name": "Михаил", "username": "michael"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class StubSettingsService:
    def __init__(self):
        self.saved = None

    @staticmethod
    def _envelope(user, settings=None):
        return {
            "settings": settings or {"general": {"language": "ru"}},
            "user": {"id": user.id, "firstName": user.first_name},
            "source": "api",
            "updatedAt": "2026-07-29T12:00:00+00:00",
        }

    def read_settings(self, user):
        return self._envelope(user)

    def save_settings(self, user, settings):
        self.saved = settings
        return self._envelope(user, settings)


class MiniAppWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = StubSettingsService()
        app = create_mini_app_application(
            bot_token=BOT_TOKEN,
            service=self.service,
            allowed_origins={"https://app.example.com"},
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_health_does_not_require_telegram_auth(self):
        response = await self.client.get("/healthz")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["status"], "ok")

    async def test_settings_requires_init_data(self):
        response = await self.client.get("/api/mini-app/settings")
        self.assertEqual(response.status, 401)
        payload = await response.json()
        self.assertEqual(payload["error"]["code"], "MISSING_INIT_DATA")

    async def test_get_settings_uses_verified_user(self):
        response = await self.client.get(
            "/api/mini-app/settings",
            headers={"X-Telegram-Init-Data": signed_init_data(42)},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["user"]["id"], 42)

    async def test_put_settings_forwards_only_settings_object(self):
        settings = {"general": {"language": "en"}}
        response = await self.client.put(
            "/api/mini-app/settings",
            headers={"X-Telegram-Init-Data": signed_init_data(42)},
            json={"settings": settings, "telegramId": 777},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(self.service.saved, settings)

    async def test_invalid_json_returns_structured_error(self):
        response = await self.client.put(
            "/api/mini-app/settings",
            headers={
                "X-Telegram-Init-Data": signed_init_data(42),
                "Content-Type": "application/json",
            },
            data="{invalid",
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["error"]["code"], "INVALID_JSON")

    async def test_cors_allows_only_configured_origin(self):
        response = await self.client.options(
            "/api/mini-app/settings",
            headers={
                "Origin": "https://app.example.com",
                "Access-Control-Request-Method": "PUT",
            },
        )
        self.assertEqual(response.status, 204)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "https://app.example.com",
        )

        denied = await self.client.options(
            "/api/mini-app/settings",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "PUT",
            },
        )
        self.assertEqual(denied.status, 403)


if __name__ == "__main__":
    unittest.main()
