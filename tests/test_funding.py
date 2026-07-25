import unittest
from decimal import Decimal

from handlers.funding import build_funding_menu, format_funding_rates, funding_page_count, top_funding_rates


class FundingTests(unittest.TestCase):
    def test_sorts_positive_descending_and_negative_ascending(self):
        rates = [
            {"symbol": "BTCUSDT", "fundingRate": "0.0001"},
            {"symbol": "ETHUSDT", "fundingRate": "-0.0002"},
            {"symbol": "SOLUSDT", "fundingRate": "0.0003"},
            {"symbol": "XRPUSDT", "fundingRate": "-0.0005"},
            {"symbol": "ZEROUSDT", "fundingRate": "0"},
        ]

        positive, negative = top_funding_rates(rates)

        self.assertEqual(positive, [("SOLUSDT", Decimal("0.0003"), None), ("BTCUSDT", Decimal("0.0001"), None)])
        self.assertEqual(negative, [("XRPUSDT", Decimal("-0.0005"), None), ("ETHUSDT", Decimal("-0.0002"), None)])

    def test_formats_two_leaderboards_as_percentages(self):
        text = format_funding_rates([
            {"symbol": "BTCUSDT", "fundingRate": "0.0001", "lastPrice": "110", "open": "100"},
            {"symbol": "ETHUSDT", "fundingRate": "-0.0002"},
        ])

        self.assertIn("Положительный фандинг", text)
        self.assertIn("Отрицательный фандинг", text)
        self.assertIn("изменение цены за сутки", text)
        self.assertIn("+0.0001%", text)
        self.assertIn("+10.00%", text)
        self.assertIn("−0.0002%", text)

    def test_paginates_top_fifty_with_navigation_arrows(self):
        rates = [
            {"symbol": f"P{index}USDT", "fundingRate": str(100 - index)}
            for index in range(55)
        ]

        self.assertEqual(funding_page_count(rates), 5)
        second_page = format_funding_rates(rates, page=1)
        self.assertIn("Страница 2 из 5", second_page)
        self.assertIn("11. P10USDT", second_page)
        self.assertNotIn(" 1. P0USDT", second_page)

        buttons = [button for row in build_funding_menu(1, 5).inline_keyboard for button in row]
        self.assertEqual([button.text for button in buttons[:3]], ["◀️", "2/5", "▶️"])
