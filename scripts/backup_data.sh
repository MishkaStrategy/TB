#!/usr/bin/env bash
# Create a transactionally consistent runtime-state backup.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/fvg-alert-bot}"
DATA_DIR="${DATA_DIR:-${INSTALL_DIR}/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fvg-alert-bot}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
PYTHON="${PYTHON:-${INSTALL_DIR}/.venv/bin/python}"

if [[ ! "${RETENTION_DAYS}" =~ ^[0-9]+$ ]]; then
  echo "RETENTION_DAYS must be a non-negative integer" >&2
  exit 1
fi
if [[ ! -d "${DATA_DIR}" ]]; then
  echo "Runtime data directory does not exist: ${DATA_DIR}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" ]]; then
  echo "Python executable does not exist: ${PYTHON}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="${BACKUP_DIR}/.fvg-alert-bot-${timestamp}.tar.gz.tmp"
archive="${BACKUP_DIR}/fvg-alert-bot-${timestamp}.tar.gz"
snapshot="$(mktemp -d "${BACKUP_DIR}/.snapshot-${timestamp}.XXXXXX")"

cleanup() {
  rm -rf "${snapshot}"
  rm -f "${temporary}"
}
trap cleanup EXIT

# Copy low-frequency JSON state, excluding live SQLite files and sidecars.
rsync -a \
  --exclude 'fvg_event_store.sqlite3' \
  --exclude 'fvg_event_store.sqlite3-wal' \
  --exclude 'fvg_event_store.sqlite3-shm' \
  "${DATA_DIR}/" "${snapshot}/"

# SQLite's backup API produces a consistent image while the bot is writing.
event_database="${DATA_DIR}/fvg_event_store.sqlite3"
if [[ -f "${event_database}" ]]; then
  PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" - \
    "${event_database}" "${snapshot}/fvg_event_store.sqlite3" <<'PY'
import sys
from alerts.sqlite_event_store import FvgEventStore

source, destination = sys.argv[1:3]
FvgEventStore(source).backup_to(destination)
PY
fi

tar -C "${snapshot}" -czf "${temporary}" .
chmod 600 "${temporary}"
mv "${temporary}" "${archive}"

find "${BACKUP_DIR}" -type f -name 'fvg-alert-bot-*.tar.gz' \
  -mtime "+${RETENTION_DAYS}" -delete

echo "Backup created: ${archive}"
