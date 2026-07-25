#!/usr/bin/env python3
"""Run an event-quality FVG backtest from historical 15m CSV candles."""

import argparse
import json

from research.fvg_quality import (
    DEFAULT_HORIZONS,
    run_quality_backtest,
    write_report,
)


def parse_horizons(value: str) -> tuple[int, ...]:
    try:
        horizons = tuple(sorted({int(item.strip()) for item in value.split(",")}))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Horizons must be comma-separated integers"
        ) from error
    if not horizons or any(item <= 0 for item in horizons):
        raise argparse.ArgumentTypeError("Horizons must be positive")
    return horizons


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure confirmed FVG touch/fill latency and MFE/MAE without "
            "inventing entry or exit rules."
        )
    )
    parser.add_argument("--data-file", required=True, help="15m OHLC CSV file")
    parser.add_argument("--symbol", required=True, help="for example BTCUSDT")
    parser.add_argument(
        "--horizons",
        type=parse_horizons,
        default=DEFAULT_HORIZONS,
        help="future candle horizons, default: 1,4,16,96",
    )
    parser.add_argument("--output", help="optional JSON report path")
    parser.add_argument(
        "--include-events",
        action="store_true",
        help="include every individual FVG outcome in the JSON report",
    )
    args = parser.parse_args()

    report = run_quality_backtest(
        args.data_file,
        symbol=args.symbol,
        horizons=args.horizons,
        include_events=args.include_events,
    )
    if args.output:
        write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
