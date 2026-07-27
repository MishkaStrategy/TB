import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from alerts.funding_alerts import FundingAlertStore
from alerts.funding_exchange_store import FundingExchangeStore
from alerts.multi_funding_alerts import matching_crossings
from exchanges.funding import PublicFundingClient
from handlers.multi_funding import (
    build_funding_menu,
    format_funding_rates,
    format_symbol_funding,
    normalize_funding_symbol,
)

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

    def test_bingx_public_batch_is_normalized(self):
        session = FakeSession([
            {
                "code": 0,
                "msg": "",
                "data": [
                    {
                        "symbol": "BTC-USDT",
                        "lastFundingRate": "0.0005",
                        "nextFundingTime": 1780000000000,
                    },
                    {
                        "symbol": "BTC-USD",
                        "lastFundingRate": "0.0007",
                    },
                ],
            }
        ])
        rates = PublicFundingClient(
            session=session,
            bitunix_client=FakeBitunix(),
        ).load("bingx")
        self.assertEqual(rates, [{
            "exchange": "bingx",
            "symbol": "BTCUSDT",
            "fundingRate": "0.05",
            "priceChange24h": None,
        }])
        self.assertIn("/openApi/swap/v2/quote/premiumIndex", session.calls[0][0])
        self.assertNotIn("headers", session.calls[0][1])

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
    def test_menu_contains_exchange_switches_and_symbol_check(self):
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
        self.assertIn("BingX", labels)
        self.assertIn("menu:funding-exchange:binance", callbacks)
        self.assertIn("menu:funding-exchange:bingx", callbacks)
        self.assertIn("menu:funding-exchange:gate", callbacks)
        self.assertIn("menu:funding-check", callbacks)
        self.assertIn(
            "Фандинг Bybit",
            format_funding_rates([], exchange="bybit"),
        )

    def test_normalizes_symbol_input(self):
        self.assertEqual(normalize_funding_symbol("btc"), "BTCUSDT")
        self.assertEqual(normalize_funding_symbol("eth/usdt"), "ETHUSDT")
        self.assertEqual(normalize_funding_symbol("1000pepe-usdt"), "1000PEPEUSDT")
        with self.assertRaises(ValueError):
            normalize_funding_symbol("???")

    def test_formats_one_symbol_across_all_exchanges(self):
        text = format_symbol_funding(
            "BTC",
            {
                "bitunix": [
                    {
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.25",
                        "priceChange24h": "2",
                    }
                ],
                "binance": [],
                "bingx": [
                    {"symbol": "BTCUSDT", "fundingRate": "0.05"}
                ],
                "bitget": [
                    {"symbol": "BTCUSDT", "fundingRate": "-0.03"}
                ],
                "gate": [
                    {"symbol": "BTCUSDT", "fundingRate": "0"}
                ],
            },
        )
        self.assertIn("Проверка фандинга BTCUSDT", text)
        self.assertIn("Bitunix</b>: <code>+0.2500%</code>", text)
        self.assertIn("BingX</b>: <code>+0.0500%</code>", text)
        self.assertIn("Bitget</b>: <code>-0.0300%</code>", text)
        self.assertIn("Binance</b>: контракт не найден", text)
        self.assertIn("Bybit</b>: API временно недоступен", text)
        self.assertIn("Gate</b>: <code>0.0000%</code>", text)


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
                store.toggle(10, "bingx"),
                ("bitunix", "bingx"),
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
            "bingx": [
                {"symbol": "BTCUSDT", "fundingRate": "0.4"}
            ],
            "bybit": [
                {"symbol": "ETHUSDT", "fundingRate": "-0.5"}
            ],
        }
        matches = matching_crossings(snapshot, settings, ("bingx",))
        self.assertEqual(
            matches,
            {("bingx", "BTCUSDT", "positive"): Decimal("0.4")},
        )


if __name__ == "__main__":
    unittest.main()
