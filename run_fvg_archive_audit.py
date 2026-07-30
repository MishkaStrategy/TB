#!/usr/bin/env python3
"""Run an explicit read-only audit of the FVG history archive."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from database.fvg_history_config import FVG_HISTORY_ARCHIVE_PATH
from operations.fvg_archive_audit import audit_fvg_archive


def write_report(report: dict, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the FVG history archive read-only: schema, quick_check, "
            "orphan deliveries, sampled payloads and run reconciliation."
        )
    )
    parser.add_argument(
        "--archive",
        default=FVG_HISTORY_ARCHIVE_PATH,
        help="Path to fvg_history.sqlite3",
    )
    parser.add_argument(
        "--runtime",
        default="data/fvg_event_store.sqlite3",
        help="Optional runtime FVG SQLite for health-counter comparison",
    )
    parser.add_argument(
        "--skip-quick-check",
        action="store_true",
        help="Skip PRAGMA quick_check for a lower-cost diagnostic run",
    )
    parser.add_argument(
        "--payload-sample-size",
        type=int,
        default=500,
        help="Maximum recent archived event payloads to validate",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Treat a missing archive as a successful rollout-not-enabled state",
    )
    parser.add_argument(
        "--output",
        help="Atomically write the JSON report to this path",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.payload_sample_size <= 0:
        raise SystemExit("--payload-sample-size must be greater than zero")

    report = audit_fvg_archive(
        args.archive,
        runtime_path=args.runtime,
        include_quick_check=not args.skip_quick_check,
        payload_sample_size=args.payload_sample_size,
        allow_missing=args.allow_missing,
    )
    if args.output:
        write_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
