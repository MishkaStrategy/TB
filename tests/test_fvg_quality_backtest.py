import csv
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from alerts.fvg_models import Candle
from research.fvg_quality import (
    analyze_fvg_quality,
    build_quality_report,
    load_candles_csv,
    run_quality_backtest,
)


UTC = timezone.utc


def candle(index, *, open_, high, low, close):
    open_time = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        is_closed=True,
        is_complete=True,
    )


def bullish_fixture():
    return [
        candle(0, open_=100, high=101, low=99, close=100),
        candle(1, open_=100, high=103, low=100, close=102),
        candle(2, open_=102, high=104, low=102, close=103),
        candle(3, open_=103, high=105, low=101.5, close=104),
        candle(4, open_=104, high=104.5, low=100.5, close=101),
        candle(5, open_=101, high=102, low=100, close=101),
    ]


class FvgQualityBacktestTests(unittest.TestCase):
    def test_uses_only_candles_after_c_for_touch_and_fill(self):
        outcomes = analyze_fvg_quality(bullish_fixture(), horizons=(1, 2, 3))
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.direction, "BULLISH")
        self.assertEqual(outcome.first_touch_bars, 1)
        self.assertEqual(outcome.full_fill_bars, 2)
        self.assertTrue(outcome.horizons[1].touched)
        self.assertFalse(outcome.horizons[1].fully_filled)
        self.assertTrue(outcome.horizons[2].fully_filled)
        self.assertGreater(outcome.horizons[1].mfe_percent, 0)
        self.assertGreater(outcome.horizons[1].mae_percent, 0)

    def test_report_uses_eligible_denominator_per_horizon(self):
        outcomes = analyze_fvg_quality(bullish_fixture(), horizons=(1, 4))
        report = build_quality_report(outcomes, horizons=(1, 4))
        self.assertEqual(report["total_events"], 1)
        self.assertEqual(report["horizons"]["1"]["eligible_events"], 1)
        self.assertEqual(report["horizons"]["4"]["eligible_events"], 0)
        self.assertIsNone(report["horizons"]["4"]["touch_rate_percent"])
        self.assertFalse(report["pnl_backtest"])

    def test_csv_loader_sorts_deduplicates_and_repairs_ohlc_envelope(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candles.csv"
            rows = [
                {
                    "time": "2026-01-01T00:15:00Z",
                    "open": "100",
                    "high": "99",
                    "low": "101",
                    "close": "100.5",
                },
                {
                    "time": "2026-01-01T00:00:00Z",
                    "open": "99",
                    "high": "100",
                    "low": "98",
                    "close": "99.5",
                },
                {
                    "time": "2026-01-01T00:30:00Z",
                    "open": "101",
                    "high": "103",
                    "low": "101",
                    "close": "102",
                },
                # Last duplicate wins.
                {
                    "time": "2026-01-01T00:15:00Z",
                    "open": "100",
                    "high": "102",
                    "low": "99",
                    "close": "101",
                },
            ]
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=("time", "open", "high", "low", "close"),
                )
                writer.writeheader()
                writer.writerows(rows)

            candles = load_candles_csv(path, symbol="btcusdt")
            self.assertEqual(len(candles), 3)
            self.assertEqual(candles[0].symbol, "BTCUSDT")
            self.assertEqual(candles[1].high, Decimal("102"))
            self.assertEqual(candles[1].low, Decimal("99"))
            self.assertLess(candles[0].open_time, candles[1].open_time)

    def test_end_to_end_report_can_include_events(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=("time", "open", "high", "low", "close"),
                )
                writer.writeheader()
                for item in bullish_fixture():
                    writer.writerow(
                        {
                            "time": item.open_time.isoformat(),
                            "open": item.open,
                            "high": item.high,
                            "low": item.low,
                            "close": item.close,
                        }
                    )
            report = run_quality_backtest(
                path,
                symbol="BTCUSDT",
                horizons=(1, 2),
                include_events=True,
            )
            self.assertEqual(report["input"]["candles"], 6)
            self.assertEqual(report["total_events"], 1)
            self.assertEqual(len(report["events"]), 1)


if __name__ == "__main__":
    unittest.main()
