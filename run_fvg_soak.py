#!/usr/bin/env python3
"""Run a synthetic end-to-end FVG persistence/delivery soak test."""

import argparse
import asyncio
import json
import sys

from operations.fvg_soak import run_soak, write_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate synthetic FVG events and verify SQLite/outbox throughput, "
            "memory and delivery invariants without real Telegram traffic."
        )
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--events", type=int, default=1000)
    parser.add_argument("--recipients", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--max-peak-memory-mb", type=float)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = asyncio.run(
        run_soak(
            args.database,
            events=args.events,
            recipients=args.recipients,
            batch_size=args.batch_size,
            max_seconds=args.max_seconds,
            max_peak_memory_mb=args.max_peak_memory_mb,
            reset=args.reset,
        )
    )
    if args.output:
        write_report(report, args.output)
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    if not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
