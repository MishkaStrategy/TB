import unittest
from decimal import Decimal

from exchanges.bitunix import BitunixClient
from handlers.funding import (
    build_funding_menu,
    enrich_funding_rates,
    format_funding_rates,
    funding_page_count,
    top_funding_rates,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.responses.pop(0))


class FundingFormattingTests(unittest.TestCase):
    def test_formats_live_api_rate_as_percent_points(self):
        text = format_funding_rates(
            [
                {
                    "symbol": "BTCUSDT",
                    "fundingRate": "1.514051",
                    "open": "100",
                    "lastPrice": "102",
                },
                {
                    "symbol": "ETHUSDT",
                    "fundingRate": "-0.125",
                    "open": "200",
                    "lastPrice": "190",
                },
            ]
        )

        self.assertIn("+1.5141%", text)
        self.assertIn("−0.1250%", text)
        self.assertIn("+2.00%", text)
        self.assertIn("-5.00%", text)
        self.assertNotIn("+151.4051%", text)

    def test_ticker_funding_field_cannot_override_batch_rate(self):
        rates = [
            {
                "symbol": "TESTUSDT",
                "fundingRate": "-1.514051",
                "fundingInterval": 4,
            }
        ]
        tickers = [
            {
                "symbol": "TESTUSDT",
                "fundingRate": "0.01514",
                "open": "100",
                "lastPrice": "101",
            }
        ]

        enriched = enrich_funding_rates(rates, tickers)
        text = format_funding_rates(enriched)

        self.assertEqual(enriched[0]["fundingRate"], "-1.514051")
        self.assertEqual(enriched[0]["fundingInterval"], 4)
        self.assertEqual(enriched[0]["open"], "100")
        self.assertEqual(enriched[0]["lastPrice"], "101")
        self.assertIn("−1.5141%", text)
        self.assertNotIn("−151.4051%", text)
        self.assertNotIn("+0.0151%", text)

    def test_sorts_positive_and_negative_rates_by_extremity(self):
        positive, negative = top_funding_rates(
            [
                {"symbol": "AUSDT", "fundingRate": "0.01"},
                {"symbol": "BUSDT", "fundingRate": "0.07"},
                {"symbol": "CUSDT", "fundingRate": "-0.02"},
                {"symbol": "DUSDT", "fundingRate": "-0.09"},
                {"symbol": "ZEROUSDT", "fundingRate": "0"},
                {"symbol": "BROKEN", "fundingRate": "not-a-number"},
            ]
        )

        self.assertEqual([item[0] for item in positive], ["BUSDT", "AUSDT"])
        self.assertEqual([item[0] for item in negative], ["DUSDT", "CUSDT"])
        self.assertEqual(positive[0][1], Decimal("0.07"))

    def test_paginates_top_fifty_in_each_direction(self):
        rates = [
            {"symbol": f"P{index}USDT", "fundingRate": str(index / 100)}
            for index in range(1, 26)
        ]
        self.assertEqual(funding_page_count(rates), 3)

        markup = build_funding_menu(1, 3)
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("menu:funding-page:0", callbacks)
        self.assertIn("menu:funding-page:current", callbacks)
        self.assertIn("menu:funding-page:2", callbacks)
        self.assertIn("funding-alert:open", callbacks)
        self.assertIn("menu:funding-refresh", callbacks)
        self.assertIn("menu:funding-back", callbacks)


class BitunixFundingClientTests(unittest.TestCase):
    def test_get_all_funding_rates_uses_public_batch_endpoint(self):
        session = FakeSession(
            [{"code": 0, "data": [{"symbol": "BTCUSDT", "fundingRate": "0.0005"}]}]
        )
        client = BitunixClient(session=session)

        rates = client.get_all_funding_rates()

        self.assertEqual(rates[0]["symbol"], "BTCUSDT")
        self.assertEqual(
            session.calls[0][0],
            "https://fapi.bitunix.com/api/v1/futures/market/funding_rate/batch",
        )
        self.assertEqual(session.calls[0][1]["timeout"], 15)

    def test_get_all_tickers_omits_symbol_filter(self):
        session = FakeSession(
            [{"code": 0, "data": [{"symbol": "BTCUSDT", "lastPrice": "60000"}]}]
        )
        client = BitunixClient(session=session)

        tickers = client.get_all_tickers()

        self.assertEqual(tickers[0]["symbol"], "BTCUSDT")
        self.assertEqual(
            session.calls[0][0],
            "https://fapi.bitunix.com/api/v1/futures/market/tickers",
        )
        self.assertNotIn("params", session.calls[0][1])

    def test_rejects_unexpected_batch_payload(self):
        session = FakeSession([{"code": 0, "data": "invalid"}])
        client = BitunixClient(session=session)

        with self.assertRaisesRegex(ValueError, "Unexpected funding rates format"):
            client.get_all_funding_rates()


if __name__ == "__main__":
    unittest.main()
