#!/usr/bin/env python3
"""Reject workflow runner selectors outside the project capability allowlist."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED = {
    "[self-hosted, fast]",
    "[self-hosted, docker]",
    "[self-hosted, backtester]",
    "[self-hosted, Linux]",
    "[self-hosted, macOS, ARM64]",
}
RUNS_ON = re.compile(r"^\s+runs-on:\s*(?P<value>.*?)\s*(?:#.*)?$")


def main() -> int:
    errors: list[str] = []
    workflows = Path(".github/workflows")
    for path in sorted(workflows.glob("*.y*ml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = RUNS_ON.match(line)
            if not match:
                continue
            selector = match.group("value")
            if selector not in ALLOWED:
                errors.append(
                    f"{path}:{number}: forbidden runs-on selector {selector!r}"
                )

    if errors:
        print("Allowed runner selectors are:", file=sys.stderr)
        for selector in sorted(ALLOWED):
            print(f"  - {selector}", file=sys.stderr)
        print("Violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Runner selector policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
