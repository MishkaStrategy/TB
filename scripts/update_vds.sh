#!/usr/bin/env bash
# Safely update an existing FVG Alert Bot VDS installation from a reviewed ref.
# Run as root from the repository checkout:
#   TARGET_REF=v1.3.1 EXPECTED_VERSION=1.3.1 bash scripts/update_vds.sh

set -euo pipefail

SERVICE_NAME="fvg-alert-bot"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_DIR="${INSTALL_DIR:-/opt/fvg-alert-bot}"
STATE_DIR="${STATE_DIR:-/var/lib/fvg-alert-bot}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fvg-alert-bot}"
TARGET_REF="${TARGET_REF:-main}"
EXPECTED_VERSION="${EXPECTED_VERSION:-1.3.1}"
EXPECTED_COMMIT="${EXPECTED_COMMIT:-}"
MIN_FREE_MB="${FVG_INSTALL_MIN_FREE_MB:-1024}"

fail() {
  echo "Ошибка обновления: $*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "запустите скрипт от root: sudo bash scripts/update_vds.sh"
fi
if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
  fail "не найден Git checkout: ${PROJECT_DIR}"
fi
if [[ ! -d "${INSTALL_DIR}" || ! -d "${STATE_DIR}" ]]; then
  fail "существующая VDS-установка не найдена; для первой установки используйте scripts/install_vds.sh"
fi
if [[ -n "$(git -C "${PROJECT_DIR}" status --porcelain)" ]]; then
  fail "в ${PROJECT_DIR} есть несохранённые изменения; сохраните или отмените их"
fi

current_commit="$(git -C "${PROJECT_DIR}" rev-parse HEAD)"
current_version="$(cat "${INSTALL_DIR}/VERSION" 2>/dev/null || echo unknown)"
echo "Текущая установка: version=${current_version}, checkout=${current_commit}"

echo "Получаю актуальный ref ${TARGET_REF}…"
git -C "${PROJECT_DIR}" fetch origin --tags --prune

if git -C "${PROJECT_DIR}" rev-parse --verify --quiet \
  "refs/remotes/origin/${TARGET_REF}^{commit}" >/dev/null; then
  if git -C "${PROJECT_DIR}" show-ref --verify --quiet \
    "refs/heads/${TARGET_REF}"; then
    git -C "${PROJECT_DIR}" checkout "${TARGET_REF}"
  else
    git -C "${PROJECT_DIR}" checkout -b "${TARGET_REF}" \
      --track "origin/${TARGET_REF}"
  fi
  git -C "${PROJECT_DIR}" merge --ff-only "origin/${TARGET_REF}"
elif git -C "${PROJECT_DIR}" rev-parse --verify --quiet \
  "refs/tags/${TARGET_REF}^{commit}" >/dev/null; then
  git -C "${PROJECT_DIR}" checkout --detach "refs/tags/${TARGET_REF}"
else
  fail "не найден remote branch или tag: ${TARGET_REF}"
fi

target_commit="$(git -C "${PROJECT_DIR}" rev-parse HEAD)"
target_version="$(tr -d '[:space:]' < "${PROJECT_DIR}/VERSION")"
if [[ -n "${EXPECTED_VERSION}" && "${target_version}" != "${EXPECTED_VERSION}" ]]; then
  fail "ожидалась версия ${EXPECTED_VERSION}, в checkout указана ${target_version}"
fi
if [[ -n "${EXPECTED_COMMIT}" && "${target_commit}" != "${EXPECTED_COMMIT}"* ]]; then
  fail "ожидался commit ${EXPECTED_COMMIT}, получен ${target_commit}"
fi

echo "Целевой релиз: ref=${TARGET_REF}, version=${target_version}, commit=${target_commit}"

installed_python="${INSTALL_DIR}/.venv/bin/python"
if [[ ! -x "${installed_python}" ]]; then
  fail "не найден Python текущей установки: ${installed_python}"
fi

# Create a transactionally consistent pre-update backup using the new backup
# implementation before the running process is stopped by the installer.
echo "Создаю предварительный backup runtime-state…"
INSTALL_DIR="${PROJECT_DIR}" \
DATA_DIR="${STATE_DIR}" \
BACKUP_DIR="${BACKUP_DIR}" \
RETENTION_DAYS=14 \
PYTHON="${installed_python}" \
  bash "${PROJECT_DIR}/scripts/backup_data.sh"

latest_backup="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \
  -name 'fvg-alert-bot-*.tar.gz' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
[[ -n "${latest_backup}" && -s "${latest_backup}" ]] || fail "backup не создан"
echo "Backup: ${latest_backup}"

echo "Запускаю атомарный установщик…"
FVG_INSTALL_MIN_FREE_MB="${MIN_FREE_MB}" \
  bash "${PROJECT_DIR}/scripts/install_vds.sh"

systemctl is-active --quiet "${SERVICE_NAME}" || fail "служба не активна после установки"
systemctl is-enabled --quiet "${SERVICE_NAME}" || fail "служба не включена в автозапуск"

installed_version="$(tr -d '[:space:]' < "${INSTALL_DIR}/VERSION")"
[[ "${installed_version}" == "${target_version}" ]] || \
  fail "установлена версия ${installed_version}, ожидалась ${target_version}"
[[ -L "${INSTALL_DIR}/data" ]] || fail "${INSTALL_DIR}/data должен быть символической ссылкой"
[[ "$(readlink -f "${INSTALL_DIR}/data")" == "$(readlink -f "${STATE_DIR}")" ]] || \
  fail "runtime data указывает не на ${STATE_DIR}"

printf '%s\n' "${target_commit}" > "${INSTALL_DIR}/BUILD_COMMIT"
chown root:root "${INSTALL_DIR}/BUILD_COMMIT"
chmod 644 "${INSTALL_DIR}/BUILD_COMMIT"

# FundingAlertStore is initialized during bot startup. Allow a short startup
# window, then verify every existing SQLite database with PRAGMA quick_check.
for _ in {1..10}; do
  [[ -f "${STATE_DIR}/funding_alerts.sqlite3" ]] && break
  sleep 1
done

"${INSTALL_DIR}/.venv/bin/python" - "${STATE_DIR}" <<'PY'
import sqlite3
import sys
from pathlib import Path

state_dir = Path(sys.argv[1])
for name in ("fvg_event_store.sqlite3", "funding_alerts.sqlite3"):
    path = state_dir / name
    if not path.exists():
        raise SystemExit(f"missing SQLite database: {path}")
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"SQLite quick_check failed for {path}: {result}")
    print(f"SQLite OK: {path}")
PY

echo
echo "VDS успешно обновлён."
echo "Ref: ${TARGET_REF}"
echo "Версия: ${installed_version}"
echo "Коммит: ${target_commit}"
echo "Backup: ${latest_backup}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
journalctl -u "${SERVICE_NAME}" -n 30 --no-pager || true
