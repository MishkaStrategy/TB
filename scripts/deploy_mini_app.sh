#!/usr/bin/env bash
# Deploy a CI-built Telegram Mini App artifact. This script never builds frontend.

set -euo pipefail

COMMAND="${1:-}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_FILE="${PROJECT_DIR}/deploy/mini-app/nginx-site.conf.template"
VALIDATOR="${PROJECT_DIR}/scripts/validate_mini_app_artifact.py"
DOMAIN="${MINI_APP_DOMAIN:-}"
BACKEND_PORT="${MINI_APP_BACKEND_PORT:-18080}"
ARTIFACT="${MINI_APP_ARTIFACT:-}"
EXPECTED_COMMIT="${MINI_APP_EXPECTED_COMMIT:-}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
WEB_ROOT="/var/www/tb-mini-app"
RELEASES_DIR="${WEB_ROOT}/releases"
CURRENT_LINK="${WEB_ROOT}/current"
NGINX_SITE="/etc/nginx/sites-available/tb-mini-app"
NGINX_ENABLED="/etc/nginx/sites-enabled/tb-mini-app"
KEEP_RELEASES="${MINI_APP_KEEP_RELEASES:-3}"
STAGING_DIR=""

fail() { echo "Ошибка: $*" >&2; exit 1; }
require_root() { [[ "${EUID}" -eq 0 ]] || fail "запустите скрипт через sudo"; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "не найдена команда '$1'"; }
cleanup() { [[ -z "${STAGING_DIR}" || ! -d "${STAGING_DIR}" ]] || rm -rf -- "${STAGING_DIR}"; }
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage:
  sudo MINI_APP_DOMAIN=<host> MINI_APP_BACKEND_PORT=18080 \
    MINI_APP_EXPECTED_COMMIT=<full-sha> MINI_APP_ARTIFACT=<path> \
    bash scripts/deploy_mini_app.sh prepare-artifact
  sudo MINI_APP_DOMAIN=<host> LETSENCRYPT_EMAIL=<email> bash scripts/deploy_mini_app.sh https
  MINI_APP_DOMAIN=<host> bash scripts/deploy_mini_app.sh verify
EOF
}

validate_configuration() {
  [[ -n "${DOMAIN}" ]] || fail "задайте MINI_APP_DOMAIN"
  [[ "${DOMAIN}" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || fail "некорректный MINI_APP_DOMAIN"
  [[ "${BACKEND_PORT}" =~ ^[0-9]+$ ]] || fail "MINI_APP_BACKEND_PORT должен быть числом"
  (( BACKEND_PORT >= 1 && BACKEND_PORT <= 65535 )) || fail "недопустимый MINI_APP_BACKEND_PORT"
  [[ "${KEEP_RELEASES}" =~ ^[1-9][0-9]*$ ]] || fail "некорректный MINI_APP_KEEP_RELEASES"
}

stage_artifact() {
  [[ -n "${ARTIFACT}" ]] || fail "задайте MINI_APP_ARTIFACT"
  [[ -e "${ARTIFACT}" ]] || fail "artifact не найден: ${ARTIFACT}"
  [[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "задайте полный MINI_APP_EXPECTED_COMMIT"
  require_command python3
  [[ -f "${VALIDATOR}" ]] || fail "не найден validator ${VALIDATOR}"
  STAGING_DIR="$(mktemp -d /var/tmp/tb-mini-app-artifact.XXXXXX)"
  python3 "${VALIDATOR}" \
    --artifact "${ARTIFACT}" \
    --output "${STAGING_DIR}" \
    --commit "${EXPECTED_COMMIT}" \
    --domain "${DOMAIN}" \
    --api-base-url "https://${DOMAIN}"
}

install_nginx_site_if_missing() {
  local rendered created=false
  require_command nginx
  require_command systemctl
  [[ -f "${TEMPLATE_FILE}" ]] || fail "не найден шаблон Nginx"
  if [[ -f "${NGINX_SITE}" ]]; then
    grep -Fq "server_name ${DOMAIN};" "${NGINX_SITE}" || fail "Nginx site использует другой домен"
    grep -Fq "127.0.0.1:${BACKEND_PORT}" "${NGINX_SITE}" || fail "Nginx site использует другой backend port"
  else
    rendered="$(mktemp /var/tmp/tb-mini-app-nginx.XXXXXX)"
    sed -e "s/__MINI_APP_DOMAIN__/${DOMAIN}/g" -e "s/__MINI_APP_BACKEND_PORT__/${BACKEND_PORT}/g" "${TEMPLATE_FILE}" >"${rendered}"
    install -o root -g root -m 0644 "${rendered}" "${NGINX_SITE}"
    rm -f "${rendered}"
    created=true
  fi
  ln -sfn "${NGINX_SITE}" "${NGINX_ENABLED}"
  if ! nginx -t; then
    rm -f "${NGINX_ENABLED}"
    [[ "${created}" != true ]] || rm -f "${NGINX_SITE}"
    fail "новая Nginx-конфигурация не прошла проверку"
  fi
}

install_frontend_release() {
  local release_id release_dir old_target current_target
  release_id="${EXPECTED_COMMIT}-$(date -u +%Y%m%dT%H%M%SZ)"
  release_dir="${RELEASES_DIR}/${release_id}"
  old_target="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  install -d -o root -g root -m 0755 "${WEB_ROOT}" "${RELEASES_DIR}" "${release_dir}"
  cp -a "${STAGING_DIR}/." "${release_dir}/"
  chown -R root:root "${release_dir}"
  find "${release_dir}" -type d -exec chmod 0755 {} +
  find "${release_dir}" -type f -exec chmod 0644 {} +
  ln -sfn "${release_dir}" "${CURRENT_LINK}.new"
  mv -Tf "${CURRENT_LINK}.new" "${CURRENT_LINK}"
  if ! nginx -t || ! systemctl reload nginx; then
    if [[ -n "${old_target}" && -d "${old_target}" ]]; then
      ln -sfn "${old_target}" "${CURRENT_LINK}.rollback"
      mv -Tf "${CURRENT_LINK}.rollback" "${CURRENT_LINK}"
      systemctl reload nginx || true
    else
      rm -f "${CURRENT_LINK}"
    fi
    fail "Nginx validation/reload failed; frontend release rolled back"
  fi
  current_target="$(readlink -f "${CURRENT_LINK}")"
  find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk -v keep="${KEEP_RELEASES}" 'NR > keep {sub(/^[^ ]+ /, ""); print}' | while IFS= read -r obsolete; do
    [[ -z "${obsolete}" || "${obsolete}" == "${current_target}" ]] || rm -rf -- "${obsolete}"
  done
  echo "Frontend release: ${release_dir}"
}

print_backend_environment() {
  cat <<EOF
Future backend activation (separate stage):
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=${BACKEND_PORT}
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://${DOMAIN}
Do not open port ${BACKEND_PORT} in the firewall.
EOF
}

prepare_artifact() {
  require_root
  validate_configuration
  require_command systemctl
  stage_artifact
  install_nginx_site_if_missing
  install_frontend_release
  print_backend_environment
  echo "HTTP artifact deployment complete: http://${DOMAIN}"
}

enable_https() {
  require_root
  validate_configuration
  require_command certbot; require_command nginx; require_command getent; require_command curl
  [[ -f "${NGINX_SITE}" ]] || fail "сначала выполните prepare-artifact"
  [[ -n "${LETSENCRYPT_EMAIL}" && "${LETSENCRYPT_EMAIL}" == *@*.* ]] || fail "задайте корректный LETSENCRYPT_EMAIL"
  getent ahostsv4 "${DOMAIN}" >/dev/null 2>&1 || fail "DNS ${DOMAIN} не разрешается"
  certbot --nginx --non-interactive --agree-tos --redirect --email "${LETSENCRYPT_EMAIL}" -d "${DOMAIN}"
  nginx -t
  systemctl reload nginx
  curl --fail --silent --show-error --location --max-time 15 "https://${DOMAIN}/" >/dev/null
  echo "HTTPS включён: https://${DOMAIN}"
}

verify() {
  validate_configuration
  require_command curl
  local frontend_tmp health_tmp
  frontend_tmp="$(mktemp /var/tmp/tb-mini-app-frontend.XXXXXX)"
  health_tmp="$(mktemp /var/tmp/tb-mini-app-health.XXXXXX)"
  trap 'rm -f "${frontend_tmp}" "${health_tmp}"; cleanup' EXIT
  curl --fail --silent --show-error --location --max-time 15 "https://${DOMAIN}/" -o "${frontend_tmp}"
  grep -Fq '<div id="root"></div>' "${frontend_tmp}" || fail "index.html Mini App не найден"
  curl --fail --silent --show-error --max-time 15 "https://${DOMAIN}/healthz" -o "${health_tmp}"
  grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' "${health_tmp}" || fail "health endpoint не вернул status=ok"
}

case "${COMMAND}" in
  prepare-artifact) prepare_artifact ;;
  https) enable_https ;;
  verify) verify ;;
  -h|--help|help|"") usage; [[ -n "${COMMAND}" ]] || exit 2 ;;
  *) usage >&2; fail "неизвестная команда '${COMMAND}'" ;;
esac
