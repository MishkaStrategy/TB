#!/usr/bin/env bash
# Create a compressed backup of runtime state and remove old archives.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/fvg-alert-bot}"
DATA_DIR="${INSTALL_DIR}/data"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/fvg-alert-bot}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [[ ! "${RETENTION_DAYS}" =~ ^[0-9]+$ ]]; then
  echo "RETENTION_DAYS must be a non-negative integer" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

if [[ ! -d "${DATA_DIR}" ]]; then
  echo "Runtime data directory does not exist: ${DATA_DIR}" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="${BACKUP_DIR}/.fvg-alert-bot-${timestamp}.tar.gz.tmp"
archive="${BACKUP_DIR}/fvg-alert-bot-${timestamp}.tar.gz"

tar -C "${INSTALL_DIR}" -czf "${temporary}" data
chmod 600 "${temporary}"
mv "${temporary}" "${archive}"

find "${BACKUP_DIR}" -type f -name 'fvg-alert-bot-*.tar.gz' \
  -mtime "+${RETENTION_DAYS}" -delete

echo "Backup created: ${archive}"
