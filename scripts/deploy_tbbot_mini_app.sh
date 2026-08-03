#!/usr/bin/env bash
# Project-specific guarded wrapper for tbbot.duckdns.org.
#
# Usage:
#   bash scripts/deploy_tbbot_mini_app.sh preflight
#   sudo bash scripts/deploy_tbbot_mini_app.sh prepare-artifact
#   sudo LETSENCRYPT_EMAIL=admin@example.com bash scripts/deploy_tbbot_mini_app.sh https
#   bash scripts/deploy_tbbot_mini_app.sh verify

set -euo pipefail

COMMAND="${1:-}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_FILE="${PROJECT_DIR}/deploy/mini-app/tbbot.env"
GENERIC_DEPLOY="${PROJECT_DIR}/scripts/deploy_mini_app.sh"

fail() {
  echo "Ошибка: $*" >&2
  exit 1
}

[[ -f "${PROFILE_FILE}" ]] || fail "не найден профиль ${PROFILE_FILE}"
# shellcheck disable=SC1090
source "${PROFILE_FILE}"

DOMAIN="${MINI_APP_DOMAIN:-}"
EXPECTED_IPV4="${MINI_APP_EXPECTED_IPV4:-}"
BACKEND_PORT="${MINI_APP_BACKEND_PORT:-18080}"
CHECKOUT_COMMIT="$(git -C "${PROJECT_DIR}" rev-parse HEAD 2>/dev/null || true)"

validate_profile() {
  [[ "${DOMAIN}" == "tbbot.duckdns.org" ]] || \
    fail "профиль должен использовать tbbot.duckdns.org"
  [[ "${EXPECTED_IPV4}" == "188.137.236.73" ]] || \
    fail "профиль должен использовать IPv4 188.137.236.73"
  [[ "${BACKEND_PORT}" == "18080" ]] || \
    fail "профиль должен использовать локальный backend port 18080"
  [[ "${CHECKOUT_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || \
    fail "не удалось определить полный commit текущего checkout"
  if [[ -n "${MINI_APP_EXPECTED_COMMIT:-}" ]]; then
    [[ "${MINI_APP_EXPECTED_COMMIT}" == "${CHECKOUT_COMMIT}" ]] || \
      fail "MINI_APP_EXPECTED_COMMIT не совпадает с текущим checkout"
  fi
  [[ -x "${GENERIC_DEPLOY}" || -f "${GENERIC_DEPLOY}" ]] || \
    fail "не найден ${GENERIC_DEPLOY}"
}

resolve_ipv4() {
  command -v getent >/dev/null 2>&1 || fail "не найдена команда getent"
  getent ahostsv4 "${DOMAIN}" \
    | awk '{print $1}' \
    | sort -u
}

preflight() {
  local resolved
  validate_profile
  resolved="$(resolve_ipv4 || true)"
  [[ -n "${resolved}" ]] || \
    fail "DNS ${DOMAIN} ещё не возвращает IPv4-адрес"

  if ! grep -Fxq "${EXPECTED_IPV4}" <<<"${resolved}"; then
    echo "DNS ${DOMAIN} сейчас возвращает:" >&2
    printf '%s\n' "${resolved}" >&2
    fail "ожидался IPv4 ${EXPECTED_IPV4}; HTTPS-развёртывание остановлено"
  fi

  echo "DNS preflight пройден: ${DOMAIN} → ${EXPECTED_IPV4}"
}

run_deploy() {
  preflight
  exec env \
    MINI_APP_DOMAIN="${DOMAIN}" \
    MINI_APP_BACKEND_PORT="${BACKEND_PORT}" \
    MINI_APP_EXPECTED_COMMIT="${CHECKOUT_COMMIT}" \
    bash "${GENERIC_DEPLOY}" "${COMMAND}"
}

case "${COMMAND}" in
  preflight)
    preflight
    ;;
  prepare-artifact|https|verify)
    run_deploy
    ;;
  -h|--help|help|"")
    cat <<'EOF'
Usage:
  bash scripts/deploy_tbbot_mini_app.sh preflight
  sudo bash scripts/deploy_tbbot_mini_app.sh prepare-artifact
  sudo LETSENCRYPT_EMAIL=<email> bash scripts/deploy_tbbot_mini_app.sh https
  bash scripts/deploy_tbbot_mini_app.sh verify

The wrapper is locked to:
  domain: tbbot.duckdns.org
  IPv4:   188.137.236.73
  API:    127.0.0.1:18080
EOF
    [[ -n "${COMMAND}" ]] || exit 2
    ;;
  *)
    fail "неизвестная команда '${COMMAND}'"
    ;;
esac
