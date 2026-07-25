#!/usr/bin/env python3
"""Download public Bitunix candles for offline research."""

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from exchanges.bitunix import BitunixClient


UTC = timezone.utc


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use an ISO date/time, for example 2026-01-01 or 2026-01-01T00:00:00Z"
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download chronological public Bitunix futures candles."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--start", required=True, type=parse_time)
    parser.add_argument("--end", required=True, type=parse_time)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if args.start >= args.end:
        parser.error("--start must be earlier than --end")

    client = BitunixClient()
    candles = client.get_historical_candles(
        symbol=args.symbol.upper(),
        interval=args.interval,
        start_time=int(args.start.timestamp() * 1000),
        end_time=int(args.end.timestamp() * 1000),
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("time", "open", "high", "low", "close"),
        )
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "time": candle["time"],
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                }
            )
    temporary.replace(destination)
    print(f"Saved {len(candles)} candles to {destination}")


if __name__ == "__main__":
    main()
