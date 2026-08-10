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
    def read_settings(self, user):
        return {
            "settings": {"admin": {"available": False}},
            "user": {"id": user.id, "firstName": user.first_name},
        }


class StubMarketOverview:
    def __init__(self):
        self.user_ids = []

    def read_overview(self, user):
        self.user_ids.append(user.id)
        return {
            "instruments": [
                {
                    "key": "binance|BTCUSDT",
                    "exchange": "binance",
                    "symbol": "BTCUSDT",
                    "price": None,
                    "priceChange24hPct": 1.42,
                    "source": "ticker",
                }
            ],
            "updatedAt": "2026-08-10T12:00:00+00:00",
        }


class StubAdminActions:
    @staticmethod
    def capabilities(_user):
        return {
            "accessWrite": False,
            "allowlistWrite": False,
            "backup": False,
            "restart": False,
        }


class MiniAppMarketWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.market = StubMarketOverview()
        app = create_mini_app_application(
            bot_token=BOT_TOKEN,
            service=StubSettingsService(),
            market_overview=self.market,
            admin_actions=StubAdminActions(),
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_market_overview_requires_verified_init_data(self):
        response = await self.client.get("/api/mini-app/market-overview")
        self.assertEqual(response.status, 401)
        self.assertEqual((await response.json())["error"]["code"], "MISSING_INIT_DATA")
        self.assertEqual(self.market.user_ids, [])

    async def test_market_overview_uses_verified_user_and_typed_field(self):
        response = await self.client.get(
            "/api/mini-app/market-overview",
            headers={"X-Telegram-Init-Data": signed_init_data(42)},
        )
        self.assertEqual(response.status, 200)
        payload = await response.json()
        self.assertEqual(self.market.user_ids, [42])
        self.assertEqual(payload["instruments"][0]["priceChange24hPct"], 1.42)
        self.assertEqual(payload["instruments"][0]["key"], "binance|BTCUSDT")


if __name__ == "__main__":
    unittest.main()
