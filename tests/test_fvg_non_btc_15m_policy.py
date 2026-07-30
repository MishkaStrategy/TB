import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from alerts.fvg_limited_service import FvgAlertService
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_stream import BitunixFvgStream


UTC = timezone.utc
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


class NonBitcoinCandlePolicyTests(unittest.TestCase):
    def test_multi_exchange_skips_non_btc_higher_timeframes_before_request(self):
        candle_client = Mock()
        poller = MultiExchangeFvgPoller(candle_client=candle_client)

        self.assertEqual(
            poller.confirmed("binance", "ETHUSDT", "1h", NOW),
            [],
        )
        candle_client.load.assert_not_called()

    def test_multi_exchange_keeps_btc_higher_timeframes(self):
        candle_client = Mock()
        candle_client.load.return_value = []
        poller = MultiExchangeFvgPoller(candle_client=candle_client)

        poller.confirmed("binance", "BTCUSDT", "4h", NOW)

        candle_client.load.assert_called_once_with(
            "binance",
            "BTCUSDT",
            "4h",
            limit=3,
            now=NOW,
        )

    def test_bitunix_rest_recovery_loads_only_15m_for_non_btc(self):
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
        )

        service.recover("SOLUSDT", NOW)

        client.get_candles.assert_called_once_with("SOLUSDT", "15m", 20)

    def test_bitunix_rest_recovery_keeps_btc_minute_candles(self):
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
        )

        service.recover("BTCUSDT", NOW)

        self.assertEqual(
            client.get_candles.call_args_list,
            [
                unittest.mock.call("BTCUSDT", "15m", 20),
                unittest.mock.call("BTCUSDT", "1m", 25),
            ],
        )

    def test_bitunix_websocket_channels_depend_on_base_asset(self):
        self.assertEqual(
            BitunixFvgStream._channels_for("ETHUSDT"),
            ("market_kline_15min",),
        )
        self.assertEqual(
            BitunixFvgStream._channels_for("BTCUSDT"),
            ("market_kline_1min", "market_kline_15min"),
        )


if __name__ == "__main__":
    unittest.main()
