#!/usr/bin/env bash
# Create and verify a transactionally consistent runtime-state backup.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/fvg-alert-bot}"
DATA_DIR="${DATA_DIR:-${INSTALL_DIR}/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fvg-alert-bot}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
HISTORY_RETENTION_DAYS="${HISTORY_RETENTION_DAYS:-180}"
PYTHON="${PYTHON:-${INSTALL_DIR}/.venv/bin/python}"
RELEASE_REF="${RELEASE_REF:-}"

for value_name in RETENTION_DAYS HISTORY_RETENTION_DAYS; do
  value="${!value_name}"
  if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
    echo "${value_name} must be a non-negative integer" >&2
    exit 1
  fi
done
if [[ ! -d "${DATA_DIR}" ]]; then
  echo "Runtime data directory does not exist: ${DATA_DIR}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" ]]; then
  echo "Python executable does not exist: ${PYTHON}" >&2
  exit 1
fi
for command_name in flock rsync tar; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

exec 9>"${BACKUP_DIR}/.backup.lock"
if ! flock -n 9; then
  echo "Another backup process is already running" >&2
  exit 75
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
temporary="${BACKUP_DIR}/.fvg-alert-bot-${timestamp}.tar.gz.tmp"
archive="${BACKUP_DIR}/fvg-alert-bot-${timestamp}.tar.gz"
checksum="${archive}.sha256"
history="${BACKUP_DIR}/backup_history.sqlite3"
snapshot="$(mktemp -d "${BACKUP_DIR}/.snapshot-${timestamp}.XXXXXX")"
run_id=""
current_step="initializing"
backup_finalized=0

cleanup() {
  status=$?
  if [[ -n "${run_id}" && "${backup_finalized}" -eq 0 ]]; then
    PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
      finish-failure \
      --history "${history}" \
      --run-id "${run_id}" \
      --step "${current_step}" \
      --message "backup process exited with status ${status}" \
      --completed-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      >/dev/null 2>&1 || true
  fi
  rm -rf "${snapshot}"
  rm -f "${temporary}" "${checksum}.tmp"
}
trap cleanup EXIT

current_step="history_begin"
run_id="$(PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  begin \
  --history "${history}" \
  --archive "${archive}" \
  --started-at "${started_at}")"

current_step="copy_runtime_files"
rsync -a \
  --exclude '.manual_backups' \
  --exclude 'fvg_event_store.sqlite3' \
  --exclude 'fvg_event_store.sqlite3-wal' \
  --exclude 'fvg_event_store.sqlite3-shm' \
  --exclude 'funding_alerts.sqlite3' \
  --exclude 'funding_alerts.sqlite3-wal' \
  --exclude 'funding_alerts.sqlite3-shm' \
  "${DATA_DIR}/" "${snapshot}/"

event_database="${DATA_DIR}/fvg_event_store.sqlite3"
if [[ -f "${event_database}" ]]; then
  current_step="snapshot_fvg_database"
  "${PYTHON}" - \
    "${event_database}" "${snapshot}/fvg_event_store.sqlite3" <<'PY'
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2])
temporary = destination.with_suffix(destination.suffix + ".tmp")
temporary.unlink(missing_ok=True)
uri = f"{source.as_uri()}?mode=ro"
with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_connection:
    checks = [row[0] for row in source_connection.execute("PRAGMA quick_check")]
    if checks != ["ok"]:
        raise RuntimeError(f"Source SQLite quick_check failed: {checks}")
    with closing(sqlite3.connect(temporary, timeout=30)) as target:
        source_connection.backup(target)
        target.commit()
os.chmod(temporary, 0o600)
temporary.replace(destination)
PY
fi

funding_database="${DATA_DIR}/funding_alerts.sqlite3"
if [[ -f "${funding_database}" ]]; then
  current_step="snapshot_funding_database"
  "${PYTHON}" - \
    "${funding_database}" "${snapshot}/funding_alerts.sqlite3" <<'PY'
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2])
temporary = destination.with_suffix(destination.suffix + ".tmp")
temporary.unlink(missing_ok=True)
uri = f"{source.as_uri()}?mode=ro"
with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_connection:
    checks = [row[0] for row in source_connection.execute("PRAGMA quick_check")]
    if checks != ["ok"]:
        raise RuntimeError(f"Source SQLite quick_check failed: {checks}")
    with closing(sqlite3.connect(temporary, timeout=30)) as target:
        source_connection.backup(target)
        target.commit()
os.chmod(temporary, 0o600)
temporary.replace(destination)
PY
fi

if [[ -z "${RELEASE_REF}" ]] && command -v git >/dev/null 2>&1; then
  RELEASE_REF="$(git -C "${INSTALL_DIR}" rev-parse HEAD 2>/dev/null || true)"
fi
RELEASE_REF="${RELEASE_REF:-unknown}"

current_step="build_manifest"
PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  build-manifest \
  --snapshot "${snapshot}" \
  --run-id "${run_id}" \
  --created-at "${started_at}" \
  --archive-name "$(basename "${archive}")" \
  --release-ref "${RELEASE_REF}" \
  >/dev/null

current_step="create_archive"
tar -C "${snapshot}" -czf "${temporary}" .
chmod 600 "${temporary}"

current_step="verify_temporary_archive"
PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  verify --archive "${temporary}" >/dev/null

current_step="publish_archive"
mv "${temporary}" "${archive}"

current_step="write_checksum"
PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  checksum --archive "${archive}" --output "${checksum}" >/dev/null
chmod 600 "${checksum}"

current_step="verify_final_archive"
PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  finish-success \
  --history "${history}" \
  --run-id "${run_id}" \
  --archive "${archive}" \
  --checksum "${checksum}" \
  --completed-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  >/dev/null
backup_finalized=1

current_step="archive_retention"
find "${BACKUP_DIR}" -type f -name 'fvg-alert-bot-*.tar.gz' \
  -mtime "+${RETENTION_DAYS}" -delete
find "${BACKUP_DIR}" -type f -name 'fvg-alert-bot-*.tar.gz.sha256' \
  -mtime "+${RETENTION_DAYS}" -delete

current_step="history_retention"
PYTHONPATH="${INSTALL_DIR}" "${PYTHON}" -m database.backup_audit \
  prune \
  --history "${history}" \
  --retention-days "${HISTORY_RETENTION_DAYS}" \
  >/dev/null

current_step="complete"
echo "Backup created and verified: ${archive}"
