import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from alerts.funding_alerts import FundingAlertStore
from alerts.funding_exchange_store import FundingExchangeStore
from alerts.multi_funding_alerts import matching_crossings
from exchanges.funding import PublicFundingClient
from handlers.multi_funding import build_funding_menu, format_funding_rates

UTC = timezone.utc


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))


class FakeBitunix:
    def get_all_funding_rates(self):
        return [{"symbol": "BTCUSDT", "fundingRate": "0.25"}]

    def get_all_tickers(self):
        return [
            {
                "symbol": "BTCUSDT",
                "open": "100",
                "lastPrice": "102",
            }
        ]


class PublicFundingAdapterTests(unittest.TestCase):
    def test_binance_ratio_is_normalized_to_percentage_points(self):
        session = FakeSession([
            [{"symbol": "BTCUSDT", "lastFundingRate": "0.0001"}],
            [{"symbol": "BTCUSDT", "priceChangePercent": "2.5"}],
        ])
        rates = PublicFundingClient(
            session=session,
            bitunix_client=FakeBitunix(),
        ).load("binance")
        self.assertEqual(rates[0]["fundingRate"], "0.01")
        self.assertEqual(rates[0]["priceChange24h"], "2.5")

    def test_bybit_bitget_and_gate_are_normalized(self):
        bybit = PublicFundingClient(
            session=FakeSession([
                {
                    "retCode": 0,
                    "result": {
                        "list": [
                            {
                                "symbol": "ETHUSDT",
                                "fundingRate": "-0.0002",
                                "price24hPcnt": "0.03",
                            }
                        ]
                    },
                }
            ]),
            bitunix_client=FakeBitunix(),
        ).load("bybit")
        self.assertEqual(bybit[0]["fundingRate"], "-0.02")
        self.assertEqual(bybit[0]["priceChange24h"], "3")

        bitget = PublicFundingClient(
            session=FakeSession([
                {
                    "code": "00000",
                    "data": [
                        {"symbol": "ETHUSDT", "fundingRate": "0.0003"}
                    ],
                },
                {
                    "code": "00000",
                    "data": [
                        {"symbol": "ETHUSDT", "change24h": "-0.02"}
                    ],
                },
            ]),
            bitunix_client=FakeBitunix(),
        ).load("bitget")
        self.assertEqual(bitget[0]["fundingRate"], "0.03")
        self.assertEqual(bitget[0]["priceChange24h"], "-2")

        gate = PublicFundingClient(
            session=FakeSession([
                [
                    {
                        "contract": "SOL_USDT",
                        "funding_rate": "0.0004",
                        "change_percentage": "1.2",
                    }
                ]
            ]),
            bitunix_client=FakeBitunix(),
        ).load("gate")
        self.assertEqual(gate[0]["symbol"], "SOLUSDT")
        self.assertEqual(gate[0]["fundingRate"], "0.04")

    def test_bitunix_keeps_native_percentage_point_scale(self):
        rates = PublicFundingClient(
            session=FakeSession([]),
            bitunix_client=FakeBitunix(),
        ).load("bitunix")
        self.assertEqual(rates[0]["fundingRate"], "0.25")
        self.assertEqual(rates[0]["priceChange24h"], "2")


class FundingViewTests(unittest.TestCase):
    def test_menu_contains_exchange_switches(self):
        markup = build_funding_menu(0, 1, "bybit")
        labels = [
            button.text
            for row in markup.inline_keyboard
            for button in row
        ]
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]
        self.assertIn("✅ Bybit", labels)
        self.assertIn("menu:funding-exchange:binance", callbacks)
        self.assertIn("menu:funding-exchange:gate", callbacks)
        self.assertIn(
            "Фандинг Bybit",
            format_funding_rates([], exchange="bybit"),
        )


class FundingExchangeStoreTests(unittest.TestCase):
    def test_defaults_to_bitunix_and_prevents_empty_selection(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            base = FundingAlertStore(path)
            base.set_enabled(
                10,
                True,
                now=datetime(2026, 7, 28, tzinfo=UTC),
            )
            store = FundingExchangeStore(path)
            self.assertEqual(store.selected(10), ("bitunix",))
            with self.assertRaises(ValueError):
                store.toggle(10, "bitunix")
            self.assertEqual(
                store.toggle(10, "binance"),
                ("bitunix", "binance"),
            )

    def test_migrates_existing_bitunix_crossings(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "funding.sqlite3"
            base = FundingAlertStore(path)
            base.set_enabled(
                10,
                True,
                now=datetime(2026, 7, 28, tzinfo=UTC),
            )
            base.replace_crossings(
                10,
                {("BTCUSDT", "positive"): Decimal("0.4")},
            )
            store = FundingExchangeStore(path)
            self.assertIn(
                ("bitunix", "BTCUSDT", "positive"),
                store.crossing_values(10),
            )

    def test_matching_respects_selected_exchanges(self):
        settings = {
            "threshold": Decimal("0.3"),
            "notify_positive": True,
            "notify_negative": True,
        }
        snapshot = {
            "binance": [
                {"symbol": "BTCUSDT", "fundingRate": "0.4"}
            ],
            "bybit": [
                {"symbol": "ETHUSDT", "fundingRate": "-0.5"}
            ],
        }
        matches = matching_crossings(snapshot, settings, ("bybit",))
        self.assertEqual(
            matches,
            {("bybit", "ETHUSDT", "negative"): Decimal("-0.5")},
        )


if __name__ == "__main__":
    unittest.main()
