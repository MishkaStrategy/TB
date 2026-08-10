import unittest
from decimal import Decimal
from types import SimpleNamespace

from mini_app_backend.auth import TelegramUser
from mini_app_backend.market_overview import MarketOverviewService


class StubSettingsService:
    def __init__(self, instruments, authorized=True):
        self.instruments = instruments
        self.authorized = authorized
        self.reads = 0

    def is_authorized(self, telegram_id):
        return self.authorized and telegram_id == 42

    def read_settings(self, user):
        self.reads += 1
        return {
            "settings": {"fvg": {"symbols": self.instruments}},
            "user": {"id": user.id},
        }


class FakeFundingClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    def load(self, exchange):
        self.calls.append(exchange)
        value = self.responses[exchange]
        if isinstance(value, Exception):
            raise value
        return value


class FakeCandleClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    def load(self, exchange, symbol, timeframe, limit=3):
        self.calls.append((exchange, symbol, timeframe, limit))
        value = self.responses.get((exchange, symbol))
        if isinstance(value, Exception):
            raise value
        return value or []


def candles(previous="100", current="105"):
    rows = [SimpleNamespace(close=Decimal(previous)) for _ in range(97)]
    rows[-1] = SimpleNamespace(close=Decimal(current))
    return rows


class MiniAppMarketOverviewTests(unittest.TestCase):
    def setUp(self):
        self.user = TelegramUser(id=42, first_name="Михаил")
        self.instruments = [
            {
                "key": "binance|BTCUSDT",
                "exchange": "binance",
                "symbol": "BTCUSDT",
            },
            {
                "key": "bybit|BTCUSDT",
                "exchange": "bybit",
                "symbol": "BTCUSDT",
            },
            {
                "key": "bingx|ETHUSDT",
                "exchange": "bingx",
                "symbol": "ETHUSDT",
            },
        ]
        self.funding_calls = []
        self.candle_calls = []
        self.funding_responses = {
            "binance": [{"symbol": "BTCUSDT", "priceChange24h": "1.42"}],
            "bybit": [{"symbol": "BTCUSDT", "priceChange24h": "-2.71"}],
            "bingx": [{"symbol": "ETH-USDT", "priceChange24h": None}],
        }
        self.candle_responses = {("bingx", "ETHUSDT"): candles("100", "103")}
        self.monotonic_value = 100.0

    def build(self, settings=None):
        settings = settings or StubSettingsService(self.instruments)
        return MarketOverviewService(
            settings,
            funding_client_factory=lambda: FakeFundingClient(
                self.funding_responses, self.funding_calls
            ),
            candle_client_factory=lambda: FakeCandleClient(
                self.candle_responses, self.candle_calls
            ),
            cache_ttl_seconds=30,
            max_workers=2,
            now=lambda: __import__("datetime").datetime(
                2026, 8, 10, 12, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            monotonic=lambda: self.monotonic_value,
        )

    def test_exchange_aware_ticker_change_and_candle_fallback(self):
        result = self.build().read_overview(self.user)
        rows = {item["key"]: item for item in result["instruments"]}
        self.assertEqual(rows["binance|BTCUSDT"]["priceChange24hPct"], 1.42)
        self.assertEqual(rows["bybit|BTCUSDT"]["priceChange24hPct"], -2.71)
        self.assertAlmostEqual(rows["bingx|ETHUSDT"]["priceChange24hPct"], 3.0)
        self.assertEqual(rows["bingx|ETHUSDT"]["source"], "candles")
        self.assertEqual(
            self.candle_calls,
            [("bingx", "ETHUSDT", "15m", 97)],
        )

    def test_partial_exchange_failure_isolated_as_unavailable(self):
        self.funding_responses["bybit"] = TimeoutError("down")
        result = self.build().read_overview(self.user)
        rows = {item["key"]: item for item in result["instruments"]}
        self.assertEqual(rows["binance|BTCUSDT"]["priceChange24hPct"], 1.42)
        self.assertIsNone(rows["bybit|BTCUSDT"]["priceChange24hPct"])
        self.assertEqual(rows["bybit|BTCUSDT"]["source"], "unavailable")

    def test_malformed_ticker_row_does_not_poison_exchange(self):
        self.funding_responses["binance"] = [
            {"symbol": "???", "priceChange24h": "99"},
            {"symbol": "BTCUSDT", "priceChange24h": "1.42"},
        ]
        result = self.build().read_overview(self.user)
        row = next(
            item for item in result["instruments"] if item["key"] == "binance|BTCUSDT"
        )
        self.assertEqual(row["priceChange24hPct"], 1.42)
        self.assertEqual(row["source"], "ticker")

    def test_malformed_saved_instrument_is_skipped(self):
        settings = StubSettingsService(
            [
                {"key": "bad", "exchange": "unknown", "symbol": "???"},
                *self.instruments,
            ]
        )
        result = self.build(settings).read_overview(self.user)
        self.assertEqual(
            [row["key"] for row in result["instruments"]],
            [row["key"] for row in self.instruments],
        )

    def test_cache_avoids_repeat_market_requests_until_ttl(self):
        service = self.build()
        first = service.read_overview(self.user)
        calls_after_first = list(self.funding_calls)
        second = service.read_overview(self.user)
        self.assertEqual(first, second)
        self.assertEqual(self.funding_calls, calls_after_first)

        self.monotonic_value += 31
        service.read_overview(self.user)
        self.assertGreater(len(self.funding_calls), len(calls_after_first))

    def test_unknown_market_value_is_null_not_zero(self):
        self.funding_responses["bingx"] = [
            {"symbol": "ETH-USDT", "priceChange24h": None}
        ]
        self.candle_responses[("bingx", "ETHUSDT")] = []
        result = self.build().read_overview(self.user)
        row = next(item for item in result["instruments"] if item["exchange"] == "bingx")
        self.assertIsNone(row["priceChange24hPct"])
        self.assertEqual(row["source"], "unavailable")

    def test_unauthorized_user_is_rejected_before_market_io(self):
        service = self.build(StubSettingsService(self.instruments, authorized=False))
        with self.assertRaises(PermissionError):
            service.read_overview(self.user)
        self.assertEqual(self.funding_calls, [])


if __name__ == "__main__":
    unittest.main()
