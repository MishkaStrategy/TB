import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from alerts.fvg_multi_exchange import (
    MultiExchangeFvgPoller,
    aggregate_15m_candles,
    required_15m_candles,
)
from alerts.fvg_models import Candle


UTC = timezone.utc
STEP = timedelta(minutes=15)
BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
UNITS = {"1h": 4, "4h": 16, "1d": 96}


def source_candle(index, high, low, *, symbol="ETHUSDT"):
    open_time = BASE + index * STEP
    close = (Decimal(str(high)) + Decimal(str(low))) / 2
    return Candle(
        symbol=symbol,
        timeframe="15m",
        open_time=open_time,
        close_time=open_time + STEP,
        open=close,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close,
        is_closed=True,
        is_complete=True,
    )


def three_target_blocks(timeframe, *, symbol="ETHUSDT"):
    units = UNITS[timeframe]
    values = ((100, 90), (108, 96), (112, 105))
    candles = []
    for block, (high, low) in enumerate(values):
        for offset in range(units):
            candles.append(
                source_candle(block * units + offset, high, low, symbol=symbol)
            )
    return candles


class AggregationTests(unittest.TestCase):
    def test_required_lookback_covers_three_closed_targets_and_partial_bucket(self):
        self.assertEqual(required_15m_candles(("15m",)), 3)
        self.assertEqual(required_15m_candles(("1h",)), 16)
        self.assertEqual(required_15m_candles(("4h",)), 64)
        self.assertEqual(required_15m_candles(("1d",)), 384)
        self.assertEqual(required_15m_candles(("15m", "1h", "4h", "1d")), 384)

    def test_aggregates_three_complete_candles_for_each_higher_timeframe(self):
        for timeframe in ("1h", "4h", "1d"):
            with self.subTest(timeframe=timeframe):
                source = three_target_blocks(timeframe)
                now = source[-1].close_time
                result = aggregate_15m_candles(source, timeframe, now)
                self.assertEqual(len(result), 3)
                self.assertEqual([item.timeframe for item in result], [timeframe] * 3)
                self.assertEqual(result[0].high, Decimal("100"))
                self.assertEqual(result[2].low, Decimal("105"))
                self.assertEqual(result[-1].close_time, now)

    def test_incomplete_source_bucket_is_not_aggregated(self):
        source = three_target_blocks("1h")
        source.pop(5)
        result = aggregate_15m_candles(source, "1h", source[-1].close_time)
        self.assertEqual(len(result), 2)


class PollerTests(unittest.TestCase):
    def test_detects_higher_timeframe_fvg_from_15m_only(self):
        for timeframe in ("1h", "4h", "1d"):
            with self.subTest(timeframe=timeframe):
                source = three_target_blocks(timeframe)

                class CandleClient:
                    def __init__(self, values):
                        self.values = values
                        self.calls = []

                    def load(self, exchange, symbol, source_timeframe, *, limit, now):
                        self.calls.append((exchange, symbol, source_timeframe, limit))
                        return self.values

                client = CandleClient(source)
                poller = MultiExchangeFvgPoller(candle_client=client)
                events = poller.confirmed(
                    "binance",
                    "ETHUSDT",
                    timeframe,
                    source[-1].close_time,
                )
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].timeframe, timeframe)
                self.assertEqual(events[0].exchange, "binance")
                self.assertEqual(client.calls[0][2], "15m")

    def test_confirmed_many_downloads_source_once(self):
        source = three_target_blocks("4h")

        class CandleClient:
            def __init__(self):
                self.calls = []

            def load(self, exchange, symbol, source_timeframe, *, limit, now):
                self.calls.append((exchange, symbol, source_timeframe, limit))
                return source

        client = CandleClient()
        poller = MultiExchangeFvgPoller(candle_client=client)
        poller.confirmed_many(
            "bybit",
            "ETHUSDT",
            ("15m", "1h", "4h"),
            source[-1].close_time,
        )
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][2], "15m")
        self.assertEqual(client.calls[0][3], 64)


if __name__ == "__main__":
    unittest.main()
