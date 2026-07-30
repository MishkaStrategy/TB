#!/usr/bin/env bash
# Update an existing VDS installation in Bot API-only mode.
# This wrapper rejects Telegram user-app credentials and delegates the
# transactional deployment to scripts/update_vds.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-/etc/fvg-alert-bot.env}"
UPDATER_SCRIPT="${UPDATER_SCRIPT:-${SCRIPT_DIR}/update_vds.sh}"

fail() {
  echo "Ошибка Bot API-only обновления: $*" >&2
  exit 1
}

[[ -r "${ENV_FILE}" ]] || fail "не найден или недоступен env-файл: ${ENV_FILE}"
[[ -f "${UPDATER_SCRIPT}" ]] || fail "не найден основной updater: ${UPDATER_SCRIPT}"
command -v python3 >/dev/null 2>&1 || fail "не найден python3"

python3 - "${ENV_FILE}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
values = {}

for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].lstrip()
    if "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key] = value

if not values.get("TELEGRAM_TOKEN", "").strip():
    raise SystemExit(
        "TELEGRAM_TOKEN отсутствует: для Bot API-only режима нужен только токен BotFather"
    )

forbidden = (
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "API_ID",
    "API_HASH",
    "TELETHON_SESSION",
    "PYROGRAM_SESSION",
    "STRING_SESSION",
)
configured = sorted(key for key in forbidden if values.get(key, "").strip())
if configured:
    raise SystemExit(
        "обнаружены Telegram App/user-session credentials, запрещённые в Bot API-only режиме: "
        + ", ".join(configured)
    )

print("Telegram mode: Bot API only; Telegram App credentials are not configured.")
PY

exec bash "${UPDATER_SCRIPT}"
