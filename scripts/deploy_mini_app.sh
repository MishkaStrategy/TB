#!/usr/bin/env bash
# Staged production deployment for the Telegram Mini App.
#
# Usage:
#   sudo MINI_APP_DOMAIN=example.duckdns.org bash scripts/deploy_mini_app.sh prepare
#   sudo MINI_APP_DOMAIN=example.duckdns.org LETSENCRYPT_EMAIL=admin@example.com \
#     bash scripts/deploy_mini_app.sh https
#   MINI_APP_DOMAIN=example.duckdns.org bash scripts/deploy_mini_app.sh verify
#
# This script deliberately does not edit /etc/fvg-alert-bot.env, restart the bot,
# register a BotFather URL, or add a Mini App button to the production bot.

set -euo pipefail

COMMAND="${1:-}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${PROJECT_DIR}/telegram-mini-app"
TEMPLATE_FILE="${PROJECT_DIR}/deploy/mini-app/nginx-site.conf.template"
DOMAIN="${MINI_APP_DOMAIN:-}"
BACKEND_PORT="${MINI_APP_BACKEND_PORT:-8080}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
WEB_ROOT="/var/www/tb-mini-app"
RELEASES_DIR="${WEB_ROOT}/releases"
CURRENT_LINK="${WEB_ROOT}/current"
NGINX_SITE="/etc/nginx/sites-available/tb-mini-app"
NGINX_ENABLED="/etc/nginx/sites-enabled/tb-mini-app"
KEEP_RELEASES="${MINI_APP_KEEP_RELEASES:-3}"
BUILD_DIR=""

usage() {
  cat <<'EOF'
Usage:
  sudo MINI_APP_DOMAIN=<host> bash scripts/deploy_mini_app.sh prepare
  sudo MINI_APP_DOMAIN=<host> LETSENCRYPT_EMAIL=<email> bash scripts/deploy_mini_app.sh https
  MINI_APP_DOMAIN=<host> bash scripts/deploy_mini_app.sh verify

Commands:
  prepare  Build the frontend, install an atomic static release, and install the
           initial HTTP Nginx site when it does not exist yet.
  https    Issue/renew a Let's Encrypt certificate through Certbot and redirect
           HTTP to HTTPS. DNS must already point at this VDS.
  verify   Verify the HTTPS frontend and the proxied backend health endpoint.
EOF
}

cleanup() {
  if [[ -n "${BUILD_DIR}" && -d "${BUILD_DIR}" ]]; then
    rm -rf "${BUILD_DIR}"
  fi
}
trap cleanup EXIT

fail() {
  echo "Ошибка: $*" >&2
  exit 1
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "запустите скрипт через sudo"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "не найдена команда '$1'"
}

validate_configuration() {
  [[ -n "${DOMAIN}" ]] || fail "задайте MINI_APP_DOMAIN, например tb-mini-app.duckdns.org"
  [[ "${DOMAIN}" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || \
    fail "MINI_APP_DOMAIN должен быть корректным доменным именем в нижнем регистре"
  [[ "${BACKEND_PORT}" =~ ^[0-9]+$ ]] || fail "MINI_APP_BACKEND_PORT должен быть числом"
  (( BACKEND_PORT >= 1 && BACKEND_PORT <= 65535 )) || fail "недопустимый MINI_APP_BACKEND_PORT"
  [[ "${KEEP_RELEASES}" =~ ^[1-9][0-9]*$ ]] || fail "MINI_APP_KEEP_RELEASES должен быть положительным числом"
}

check_node_version() {
  local version major minor
  version="$(node -p 'process.versions.node')"
  IFS='.' read -r major minor _ <<<"${version}"
  if ! (( (major == 20 && minor >= 19) || major >= 22 )); then
    fail "для Vite 7 требуется Node.js 20.19+ или 22.12+; установлена версия ${version}"
  fi
}

build_frontend() {
  require_command node
  require_command npm
  require_command rsync
  check_node_version
  [[ -f "${APP_DIR}/package-lock.json" ]] || fail "не найден telegram-mini-app/package-lock.json"

  BUILD_DIR="$(mktemp -d /tmp/tb-mini-app-build.XXXXXX)"
  rsync -a --delete \
    --exclude node_modules \
    --exclude dist \
    "${APP_DIR}/" "${BUILD_DIR}/"

  (
    cd "${BUILD_DIR}"
    npm ci --no-audit --no-fund
    VITE_API_BASE_URL="https://${DOMAIN}" npm run build
  )

  [[ -f "${BUILD_DIR}/dist/index.html" ]] || fail "frontend build не создал dist/index.html"
}

install_nginx_site_if_missing() {
  local rendered created=false
  require_command nginx
  require_command systemctl
  [[ -f "${TEMPLATE_FILE}" ]] || fail "не найден шаблон ${TEMPLATE_FILE}"

  if [[ -f "${NGINX_SITE}" ]]; then
    grep -Fq "server_name ${DOMAIN};" "${NGINX_SITE}" || \
      fail "существующий ${NGINX_SITE} настроен для другого домена"
    grep -Fq "127.0.0.1:${BACKEND_PORT}" "${NGINX_SITE}" || \
      fail "существующий ${NGINX_SITE} использует другой backend port"
  else
    rendered="$(mktemp /tmp/tb-mini-app-nginx.XXXXXX)"
    sed \
      -e "s/__MINI_APP_DOMAIN__/${DOMAIN}/g" \
      -e "s/__MINI_APP_BACKEND_PORT__/${BACKEND_PORT}/g" \
      "${TEMPLATE_FILE}" >"${rendered}"
    install -o root -g root -m 0644 "${rendered}" "${NGINX_SITE}"
    rm -f "${rendered}"
    created=true
  fi

  ln -sfn "${NGINX_SITE}" "${NGINX_ENABLED}"
  if ! nginx -t; then
    rm -f "${NGINX_ENABLED}"
    [[ "${created}" == true ]] && rm -f "${NGINX_SITE}"
    fail "новая Nginx-конфигурация не прошла проверку"
  fi
}

install_frontend_release() {
  local release_id release_dir old_target current_target
  release_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  release_dir="${RELEASES_DIR}/${release_id}"
  old_target="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"

  install -d -o root -g root -m 0755 "${WEB_ROOT}" "${RELEASES_DIR}"
  install -d -o root -g root -m 0755 "${release_dir}"
  rsync -a --delete "${BUILD_DIR}/dist/" "${release_dir}/"
  chown -R root:root "${release_dir}"
  find "${release_dir}" -type d -exec chmod 0755 {} +
  find "${release_dir}" -type f -exec chmod 0644 {} +

  ln -sfn "${release_dir}" "${CURRENT_LINK}.new"
  mv -Tf "${CURRENT_LINK}.new" "${CURRENT_LINK}"

  if ! nginx -t; then
    if [[ -n "${old_target}" && -d "${old_target}" ]]; then
      ln -sfn "${old_target}" "${CURRENT_LINK}.rollback"
      mv -Tf "${CURRENT_LINK}.rollback" "${CURRENT_LINK}"
    else
      rm -f "${CURRENT_LINK}"
    fi
    fail "nginx -t завершился ошибкой; frontend symlink возвращён назад"
  fi

  if ! systemctl reload nginx; then
    if [[ -n "${old_target}" && -d "${old_target}" ]]; then
      ln -sfn "${old_target}" "${CURRENT_LINK}.rollback"
      mv -Tf "${CURRENT_LINK}.rollback" "${CURRENT_LINK}"
      systemctl reload nginx || true
    else
      rm -f "${CURRENT_LINK}"
    fi
    fail "Nginx не перезагрузился; frontend symlink возвращён назад"
  fi

  current_target="$(readlink -f "${CURRENT_LINK}")"
  find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -nr \
    | awk -v keep="${KEEP_RELEASES}" 'NR > keep {sub(/^[^ ]+ /, ""); print}' \
    | while IFS= read -r obsolete; do
        [[ -n "${obsolete}" && "${obsolete}" != "${current_target}" ]] && rm -rf "${obsolete}"
      done

  echo "Frontend release: ${release_dir}"
}

print_backend_environment() {
  cat <<EOF

Для отдельного этапа включения backend добавьте в /etc/fvg-alert-bot.env:
MINI_APP_BACKEND_ENABLED=true
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=${BACKEND_PORT}
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://${DOMAIN}

После изменения env backend начнёт слушать только localhost. Не открывайте порт ${BACKEND_PORT} в firewall.
EOF
}

prepare() {
  require_root
  validate_configuration
  require_command systemctl
  build_frontend
  install_nginx_site_if_missing
  install_frontend_release
  print_backend_environment
  echo
  echo "HTTP preparation complete: http://${DOMAIN}"
  echo "Следующий этап: дождитесь DNS и выполните команду 'https'."
}

enable_https() {
  require_root
  validate_configuration
  require_command certbot
  require_command nginx
  require_command getent
  require_command curl
  [[ -f "${NGINX_SITE}" ]] || fail "сначала выполните команду prepare"
  [[ -n "${LETSENCRYPT_EMAIL}" ]] || fail "задайте LETSENCRYPT_EMAIL для Let's Encrypt"
  [[ "${LETSENCRYPT_EMAIL}" == *@*.* ]] || fail "LETSENCRYPT_EMAIL выглядит некорректно"

  getent ahostsv4 "${DOMAIN}" >/dev/null 2>&1 || \
    fail "DNS ${DOMAIN} ещё не разрешается; проверьте запись DuckDNS"

  certbot --nginx \
    --non-interactive \
    --agree-tos \
    --redirect \
    --email "${LETSENCRYPT_EMAIL}" \
    -d "${DOMAIN}"

  nginx -t
  systemctl reload nginx
  curl --fail --silent --show-error --location --max-time 15 \
    "https://${DOMAIN}/" >/dev/null
  echo "HTTPS включён: https://${DOMAIN}"
}

verify() {
  validate_configuration
  require_command curl

  local frontend_tmp health_tmp
  frontend_tmp="$(mktemp /tmp/tb-mini-app-frontend.XXXXXX)"
  health_tmp="$(mktemp /tmp/tb-mini-app-health.XXXXXX)"
  trap 'rm -f "${frontend_tmp}" "${health_tmp}"; cleanup' EXIT

  curl --fail --silent --show-error --location --max-time 15 \
    "https://${DOMAIN}/" -o "${frontend_tmp}"
  grep -Fq '<div id="root"></div>' "${frontend_tmp}" || \
    fail "HTTPS frontend ответил, но index.html Mini App не найден"

  curl --fail --silent --show-error --max-time 15 \
    "https://${DOMAIN}/healthz" -o "${health_tmp}"
  grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' "${health_tmp}" || \
    fail "backend health endpoint не вернул status=ok"

  echo "Проверка пройдена: frontend и backend доступны через https://${DOMAIN}"
}

case "${COMMAND}" in
  prepare)
    prepare
    ;;
  https)
    enable_https
    ;;
  verify)
    verify
    ;;
  -h|--help|help|"")
    usage
    [[ -n "${COMMAND}" ]] || exit 2
    ;;
  *)
    usage >&2
    fail "неизвестная команда '${COMMAND}'"
    ;;
esac
