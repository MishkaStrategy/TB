#!/usr/bin/env bash
# Run candidate tests in a deterministic environment that cannot inherit
# production credentials or feature flags.
set -euo pipefail

if (( $# < 2 || $# > 3 )); then
  echo "Usage: $0 CANDIDATE_DIR LOG_FILE [SERVICE_USER]" >&2
  exit 2
fi

CANDIDATE_DIR="$(cd "$1" && pwd)"
LOG_FILE="$2"
SERVICE_USER="${3:-}"
PYTHON="${CANDIDATE_DIR}/.venv/bin/python"
TMP_ROOT="${CANDIDATE_DIR}/tmp"
MPL_CONFIG="${TMP_ROOT}/mpl"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Candidate Python not found: ${PYTHON}" >&2
  exit 2
fi

mkdir -p "$(dirname "${LOG_FILE}")" "${TMP_ROOT}" "${MPL_CONFIG}"
touch "${LOG_FILE}"
chmod 600 "${LOG_FILE}"

candidate_command=(
  env -i
  "HOME=${TMP_ROOT}"
  "PATH=${CANDIDATE_DIR}/.venv/bin:/usr/bin:/bin"
  "TELEGRAM_TOKEN=ci-placeholder"
  "ADMIN_TELEGRAM_IDS=1"
  "ALLOWED_TELEGRAM_IDS=1"
  "PUBLIC_ACCESS_ENABLED=true"
  "MAX_SYMBOLS_PER_USER=10"
  "PYTHONDONTWRITEBYTECODE=1"
  "TMPDIR=${TMP_ROOT}"
  "MPLCONFIGDIR=${MPL_CONFIG}"
  "${PYTHON}"
  -m unittest discover -s tests -v
)

cd "${CANDIDATE_DIR}"
set +e
if [[ -n "${SERVICE_USER}" && "$(id -un)" != "${SERVICE_USER}" ]]; then
  runuser -u "${SERVICE_USER}" -- "${candidate_command[@]}" 2>&1 | tee "${LOG_FILE}"
  candidate_status="${PIPESTATUS[0]}"
else
  "${candidate_command[@]}" 2>&1 | tee "${LOG_FILE}"
  candidate_status="${PIPESTATUS[0]}"
fi
set -e

chmod 600 "${LOG_FILE}"
exit "${candidate_status}"
