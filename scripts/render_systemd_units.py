#!/usr/bin/env python3
"""Extract the exact systemd units embedded in install_vds.sh for CI checks."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


UNIT_PATTERNS = {
    "fvg-alert-bot.service": (
        r'cat > "/etc/systemd/system/\$\{SERVICE_NAME\}\.service" <<EOF\n'
        r"(.*?)\nEOF"
    ),
    "fvg-alert-bot-backup.service": (
        r'cat > "/etc/systemd/system/\$\{BACKUP_SERVICE_NAME\}\.service" '
        r"<<EOF\n(.*?)\nEOF"
    ),
    "fvg-alert-bot-backup.timer": (
        r'cat > "/etc/systemd/system/\$\{BACKUP_SERVICE_NAME\}\.timer" '
        r"<<EOF\n(.*?)\nEOF"
    ),
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--service-user", required=True)
    parser.add_argument("--service-group", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--backup-dir", required=True)
    return parser.parse_args()


def substitute(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    unresolved = sorted(set(re.findall(r"\$\{([A-Z0-9_]+)\}", rendered)))
    if unresolved:
        raise RuntimeError(
            "Unresolved installer variables: " + ", ".join(unresolved)
        )
    return rendered + "\n"


def main():
    args = parse_args()
    installer = Path(args.installer).read_text(encoding="utf-8")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    values = {
        "SERVICE_USER": args.service_user,
        "SERVICE_NAME": "fvg-alert-bot",
        "BACKUP_SERVICE_NAME": "fvg-alert-bot-backup",
        "INSTALL_DIR": args.install_dir,
        "STATE_DIR": args.state_dir,
        "ENV_FILE": args.env_file,
        "BACKUP_DIR": args.backup_dir,
    }

    for filename, pattern in UNIT_PATTERNS.items():
        match = re.search(pattern, installer, flags=re.DOTALL)
        if match is None:
            raise RuntimeError(
                f"Could not extract {filename} from {args.installer}"
            )
        rendered = substitute(match.group(1), values)
        if filename == "fvg-alert-bot.service":
            rendered = rendered.replace(
                f"Group={args.service_user}",
                f"Group={args.service_group}",
            )
        (output / filename).write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
