import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from alerts.fvg_models import Candle
from alerts.fvg_multi_exchange import MultiExchangeFvgPoller
from alerts.fvg_settings_15m import FvgAlertSettings
from alerts.fvg_store import instrument_key
from exchanges.fvg_candles import PublicCandleClient


UTC = timezone.utc
OPEN = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
OPEN_MS = int(OPEN.timestamp() * 1000)
OPEN_S = int(OPEN.timestamp())


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.payload)


class FakeBitunixClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_candles(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        return self.payload


class ExchangeAdapterContractTests(unittest.TestCase):
    def _assert_one_closed_eth_candle(self, exchange, payload):
        session = FakeSession(payload)
        client = PublicCandleClient(session=session)
        candles = client.load(exchange, "ETHUSDT", "15m", limit=1, now=NOW)
        self.assertEqual(len(candles), 1)
        candle = candles[0]
        self.assertEqual(candle.symbol, "ETHUSDT")
        self.assertEqual(candle.timeframe, "15m")
        self.assertEqual(candle.open_time, OPEN)
        self.assertEqual(candle.close_time, OPEN + timedelta(minutes=15))
        self.assertTrue(candle.is_closed)
        self.assertTrue(candle.is_complete)
        self.assertEqual(candle.open, Decimal("100"))
        self.assertEqual(candle.high, Decimal("110"))
        self.assertEqual(candle.low, Decimal("90"))
        self.assertEqual(candle.close, Decimal("105"))
        return session

    def test_binance_15m_payload_contract(self):
        session = self._assert_one_closed_eth_candle(
            "binance",
            [[OPEN_MS, "100", "110", "90", "105"]],
        )
        _, params, _ = session.calls[0]
        self.assertEqual(params["symbol"], "ETHUSDT")
        self.assertEqual(params["interval"], "15m")

    def test_bybit_15m_payload_contract(self):
        session = self._assert_one_closed_eth_candle(
            "bybit",
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "list": [[str(OPEN_MS), "100", "110", "90", "105"]]
                },
            },
        )
        _, params, _ = session.calls[0]
        self.assertEqual(params["symbol"], "ETHUSDT")
        self.assertEqual(params["interval"], "15")

    def test_bingx_15m_payload_contract(self):
        session = self._assert_one_closed_eth_candle(
            "bingx",
            {
                "code": 0,
                "msg": "",
                "data": [
                    {
                        "time": OPEN_MS,
                        "open": "100",
                        "high": "110",
                        "low": "90",
                        "close": "105",
                    }
                ],
            },
        )
        _, params, _ = session.calls[0]
        self.assertEqual(params["symbol"], "ETH-USDT")
        self.assertEqual(params["interval"], "15m")

    def test_bitget_15m_payload_contract(self):
        session = self._assert_one_closed_eth_candle(
            "bitget",
            {
                "code": "00000",
                "msg": "success",
                "data": [[str(OPEN_MS), "100", "110", "90", "105"]],
            },
        )
        _, params, _ = session.calls[0]
        self.assertEqual(params["symbol"], "ETHUSDT")
        self.assertEqual(params["granularity"], "15m")
        self.assertEqual(params["productType"], "usdt-futures")

    def test_gate_15m_object_payload_contract(self):
        session = self._assert_one_closed_eth_candle(
            "gate",
            [
                {
                    "t": OPEN_S,
                    "o": "100",
                    "h": "110",
                    "l": "90",
                    "c": "105",
                    "v": "1",
                }
            ],
        )
        _, params, _ = session.calls[0]
        self.assertEqual(params["contract"], "ETH_USDT")
        self.assertEqual(params["interval"], "15m")

    def test_bitunix_15m_payload_contract(self):
        bitunix = FakeBitunixClient(
            {
                "code": 0,
                "data": [
                    {
                        "time": OPEN_MS,
                        "open": "100",
                        "high": "110",
                        "low": "90",
                        "close": "105",
                    }
                ],
            }
        )
        client = PublicCandleClient(
            session=FakeSession({}),
            bitunix_client=bitunix,
        )
        candles = client.load("bitunix", "ETHUSDT", "15m", limit=1, now=NOW)
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0].symbol, "ETHUSDT")
        self.assertEqual(candles[0].timeframe, "15m")
        self.assertTrue(candles[0].is_closed)
        self.assertEqual(bitunix.calls[0][0:2], ("ETHUSDT", "15m"))


class NonBitcoinEndToEndTests(unittest.TestCase):
    @staticmethod
    def _gap_candle(index, high, low, close):
        open_time = OPEN + timedelta(minutes=15 * index)
        return Candle(
            symbol="ETHUSDT",
            timeframe="15m",
            open_time=open_time,
            close_time=open_time + timedelta(minutes=15),
            open=Decimal(str(close)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            is_closed=True,
            is_complete=True,
        )

    def test_non_btc_15m_event_reaches_configured_recipient(self):
        source = [
            self._gap_candle(0, 100, 90, 95),
            self._gap_candle(1, 108, 96, 101),
            self._gap_candle(2, 112, 105, 108),
        ]

        class CandleClient:
            def __init__(self):
                self.calls = []

            def load(self, exchange, symbol, timeframe, limit, now):
                self.calls.append((exchange, symbol, timeframe, limit, now))
                return list(source)

        candle_client = CandleClient()
        poller = MultiExchangeFvgPoller(candle_client=candle_client)
        events = poller.confirmed("binance", "ETHUSDT", "15m", NOW)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.exchange, "binance")
        self.assertEqual(event.symbol, "ETHUSDT")
        self.assertEqual(event.timeframe, "15m")
        self.assertEqual(candle_client.calls[0][2], "15m")

        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.remove_symbol(42, "BTCUSDT")
            settings.add_instrument(42, "binance", "ETHUSDT", ("15m",))
            settings.set_enabled(42, True)
            self.assertIn(
                ("binance", "ETHUSDT", "15m"),
                settings.active_markets(),
            )
            self.assertIn(
                instrument_key("binance", "ETHUSDT"),
                settings.user(42)["symbols"],
            )
            self.assertEqual(settings.recipients(event), [42])


class ActiveInstrumentCapTests(unittest.TestCase):
    def test_one_instrument_keeps_all_selected_timeframes_inside_cap(self):
        with TemporaryDirectory() as directory:
            settings = FvgAlertSettings(f"{directory}/settings.json")
            settings.remove_symbol(1, "BTCUSDT")
            settings.add_instrument(
                1,
                "binance",
                "ETHUSDT",
                ("15m", "1h", "4h", "1d"),
            )
            settings.add_instrument(1, "bybit", "SOLUSDT", ("15m",))
            settings.set_enabled(1, True)

            with patch("alerts.fvg_settings_15m.MAX_ACTIVE_SYMBOLS", 1):
                markets = settings.active_markets()

            self.assertEqual(
                markets,
                (
                    ("binance", "ETHUSDT", "15m"),
                    ("binance", "ETHUSDT", "1h"),
                    ("binance", "ETHUSDT", "4h"),
                    ("binance", "ETHUSDT", "1d"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
