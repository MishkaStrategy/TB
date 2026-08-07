import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from alerts.fvg_limited_service import FvgAlertService
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_stream_15m import FifteenMinuteBitunixFvgStream


UTC = timezone.utc
NOW = datetime(2026, 8, 7, 12, 15, tzinfo=UTC)


class FifteenMinuteCandlePolicyTests(unittest.TestCase):
    def test_multi_exchange_skips_higher_timeframes_before_request_for_all_assets(self):
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            with self.subTest(symbol=symbol):
                candle_client = Mock()
                poller = MultiExchangeFvgPoller(candle_client=candle_client)
                self.assertEqual(
                    poller.confirmed("binance", symbol, "1h", NOW),
                    [],
                )
                candle_client.load.assert_not_called()

    def test_multi_exchange_loads_only_15m(self):
        candle_client = Mock()
        candle_client.load.return_value = []
        poller = MultiExchangeFvgPoller(candle_client=candle_client)

        poller.confirmed("binance", "BTCUSDT", "15m", NOW)

        candle_client.load.assert_called_once_with(
            "binance",
            "BTCUSDT",
            "15m",
            limit=3,
            now=NOW,
        )

    def test_bitunix_rest_recovery_loads_only_15m_for_every_asset(self):
        for symbol in ("BTCUSDT", "SOLUSDT"):
            with self.subTest(symbol=symbol):
                client = Mock()
                client.get_candles.return_value = {"data": []}
                event_store = SimpleNamespace(
                    update_health=lambda **values: None,
                    increment_health=lambda *args: None,
                )
                service = FvgAlertService(
                    client=client,
                    settings=SimpleNamespace(),
                    event_store=event_store,
                    delivery_registry=object(),
                    suppress_unavailable_users=False,
                )

                service.recover(symbol, NOW)

                client.get_candles.assert_called_once_with(symbol, "15m", 20)

    def test_bitunix_websocket_has_only_15m_channel_for_every_asset(self):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    FifteenMinuteBitunixFvgStream._channels_for(symbol),
                    ("market_kline_15min",),
                )


if __name__ == "__main__":
    unittest.main()
