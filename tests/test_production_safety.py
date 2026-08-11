import asyncio
import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from alerts.fvg_detector import price_allowed
from alerts.fvg_service import parse_rest_candle
from alerts.fvg_store import FvgAlertSettings
from alerts.fvg_stream import BitunixFvgStream
from config import (
    MAX_ACTIVE_SYMBOLS,
    MAX_SYMBOLS_PER_USER,
    parse_bool,
    parse_positive_int,
)
from database.user_activity import UserActivityRegistry
from exchanges.bitunix import BitunixClient


UTC = timezone.utc


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload=None):
        self.payload = payload or {"data": []}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


class FakeEventStore:
    def __init__(self):
        self.health_updates = []
        self.health_increments = []

    def update_health(self, **values):
        self.health_updates.append(values)

    def increment_health(self, key, amount=1):
        self.health_increments.append((key, amount))


class ProductionSafetyTests(unittest.TestCase):
    def test_rejects_non_finite_exchange_candle(self):
        raw = {
            "time": 1_700_000_000_000,
            "open": "100",
            "high": "NaN",
            "low": "99",
            "close": "101",
        }
        with self.assertRaisesRegex(ValueError, "non-finite"):
            parse_rest_candle(raw, "BTCUSDT", "15m", datetime.now(UTC))

    def test_nan_filter_boundary_fails_closed_without_exception(self):
        self.assertFalse(
            price_allowed(
                Decimal("100"),
                True,
                Decimal("NaN"),
                None,
            )
        )
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(str(Path(directory) / "settings.json"))
            with self.assertRaisesRegex(ValueError, "конечным"):
                settings.set_price_filter(42, "BTCUSDT", "NaN", None)

    def test_symbol_quota_is_enforced_per_user(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(str(Path(directory) / "settings.json"))
            for index in range(MAX_SYMBOLS_PER_USER):
                settings.add_symbol(42, f"S{index:03d}USDT")
            self.assertEqual(len(settings.user(42)["symbols"]), MAX_SYMBOLS_PER_USER)
            with self.assertRaisesRegex(ValueError, "не более"):
                settings.add_symbol(42, "OVERLIMITUSDT")

    def test_bitunix_kline_limit_is_capped_at_official_maximum(self):
        session = FakeSession()
        client = BitunixClient(session=session)
        client.get_candles(limit=1000)
        _, kwargs = session.calls[-1]
        self.assertEqual(kwargs["params"]["limit"], 200)

    def test_stream_caps_active_symbols(self):
        symbols = {
            f"S{index:03d}USDT"
            for index in range(MAX_ACTIVE_SYMBOLS + 25)
        }
        service = SimpleNamespace(
            settings=SimpleNamespace(active_symbols=lambda: symbols),
            event_store=FakeEventStore(),
        )
        stream = BitunixFvgStream(service)
        self.assertEqual(len(stream._active_symbols()), MAX_ACTIVE_SYMBOLS)

    def test_configuration_parsers_reject_unsafe_values(self):
        self.assertFalse(parse_bool(None, default=False))
        self.assertTrue(parse_bool("yes"))
        with self.assertRaises(ValueError):
            parse_bool("sometimes")
        with self.assertRaises(ValueError):
            parse_positive_int("0", 1, "LIMIT")

    def test_user_activity_is_throttled_per_user(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            registry = UserActivityRegistry(str(path))
            user = SimpleNamespace(
                id=42,
                first_name="Test",
                last_name="User",
                username="tester",
            )
            self.assertTrue(registry.touch(user))
            self.assertFalse(registry.touch(user))
            self.assertEqual(registry.users()["42"]["visits"], 2)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["users"]["42"]["visits"], 1)


class DeliveryWorkerSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_survives_failure_and_allows_retry(self):
        event_store = FakeEventStore()

        class Service:
            def __init__(self):
                self.calls = 0
                self.event_store = event_store
                self.settings = SimpleNamespace(active_symbols=lambda: set())

            async def deliver(self, bot, events):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary failure")

        service = Service()
        stream = BitunixFvgStream(service)
        event = SimpleNamespace(event_id="BTCUSDT:15m:test")
        worker = asyncio.create_task(stream._deliver_worker(SimpleNamespace()))
        try:
            stream._enqueue([event])
            await asyncio.wait_for(stream._delivery_queue.join(), timeout=1)
            stream._enqueue([event])
            await asyncio.wait_for(stream._delivery_queue.join(), timeout=1)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        self.assertEqual(service.calls, 2)
        self.assertIn(("delivery_worker_failures", 1), event_store.health_increments)


if __name__ == "__main__":
    unittest.main()
