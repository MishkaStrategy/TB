#!/usr/bin/env bash
# Atomic installation/update of FVG Alert Bot on Ubuntu/Debian VDS.
# Run as root from a checked-out repository:
#   sudo bash scripts/install_vds.sh

set -euo pipefail

SERVICE_USER="fvgbot"
SERVICE_NAME="fvg-alert-bot"
BACKUP_SERVICE_NAME="fvg-alert-bot-backup"
INSTALL_DIR="/opt/fvg-alert-bot"
STAGING_DIR="${INSTALL_DIR}.staging.$$"
PREVIOUS_DIR="${INSTALL_DIR}.previous"
STATE_DIR="/var/lib/fvg-alert-bot"
ENV_FILE="/etc/fvg-alert-bot.env"
BACKUP_DIR="/var/backups/fvg-alert-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -d "${STAGING_DIR}" ]]; then
    rm -rf "${STAGING_DIR}"
  fi
}
trap cleanup EXIT

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите скрипт с sudo: sudo bash scripts/install_vds.sh" >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/bot.py" ]]; then
  echo "Скрипт нужно запускать из папки проекта FVG Alert Bot." >&2
  exit 1
fi

echo "Устанавливаю системные зависимости…"
apt update
apt install -y git python3 python3-venv python3-pip rsync

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  adduser --system --group --home /var/lib/fvgbot "${SERVICE_USER}"
fi

mkdir -p "${STATE_DIR}" "${BACKUP_DIR}" /tmp/trading-assistant-mpl
chmod 700 "${STATE_DIR}" "${BACKUP_DIR}" /tmp/trading-assistant-mpl
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}" /tmp/trading-assistant-mpl
chown root:root "${BACKUP_DIR}"

# Migrate runtime state and secrets from installations created by older scripts.
if [[ -d "${INSTALL_DIR}/data" && ! -L "${INSTALL_DIR}/data" ]]; then
  rsync -a "${INSTALL_DIR}/data/" "${STATE_DIR}/"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${INSTALL_DIR}/.env" ]]; then
    cp "${INSTALL_DIR}/.env" "${ENV_FILE}"
  else
    cp "${PROJECT_DIR}/.env.example" "${ENV_FILE}"
    read -r -s -p "Введите токен BotFather: " TELEGRAM_TOKEN
    echo
    read -r -p "Введите ваш числовой Telegram ID (админ): " TELEGRAM_ID
    if [[ -z "${TELEGRAM_TOKEN}" || ! "${TELEGRAM_ID}" =~ ^[0-9]+$ ]]; then
      echo "Токен или Telegram ID заполнен неверно. Установка остановлена." >&2
      exit 1
    fi
    sed -i "s|^TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=${TELEGRAM_TOKEN}|" "${ENV_FILE}"
    sed -i "s|^ADMIN_TELEGRAM_IDS=.*|ADMIN_TELEGRAM_IDS=${TELEGRAM_ID}|" "${ENV_FILE}"
    sed -i "s|^ALLOWED_TELEGRAM_IDS=.*|ALLOWED_TELEGRAM_IDS=${TELEGRAM_ID}|" "${ENV_FILE}"
  fi
fi
chown root:"${SERVICE_USER}" "${ENV_FILE}"
chmod 640 "${ENV_FILE}"

# Build a complete candidate release without touching the running installation.
rm -rf "${STAGING_DIR}"
mkdir -p "${STAGING_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.venv-ci' \
  --exclude '.env' \
  --exclude 'data' \
  "${PROJECT_DIR}/" "${STAGING_DIR}/"

cp "${ENV_FILE}" "${STAGING_DIR}/.env"
mkdir -p "${STAGING_DIR}/data"
chown root:"${SERVICE_USER}" "${STAGING_DIR}/.env"
chmod 640 "${STAGING_DIR}/.env"
chown "${SERVICE_USER}:${SERVICE_USER}" "${STAGING_DIR}/data"
chmod 700 "${STAGING_DIR}/data"

echo "Создаю виртуальное окружение кандидата…"
python3 -m venv "${STAGING_DIR}/.venv"
"${STAGING_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${STAGING_DIR}/.venv/bin/python" -m pip install \
  -r "${STAGING_DIR}/requirements.txt"

echo "Проверяю кандидат до остановки работающего бота…"
"${STAGING_DIR}/.venv/bin/python" -m compileall -q \
  "${STAGING_DIR}/bot.py" \
  "${STAGING_DIR}/config.py" \
  "${STAGING_DIR}/alerts" \
  "${STAGING_DIR}/database" \
  "${STAGING_DIR}/exchanges" \
  "${STAGING_DIR}/handlers" \
  "${STAGING_DIR}/tests"
runuser -u "${SERVICE_USER}" -- bash -c "
  set -euo pipefail
  cd '${STAGING_DIR}'
  export PUBLIC_ACCESS_ENABLED=true
  export PYTHONDONTWRITEBYTECODE=1
  export MPLCONFIGDIR=/tmp/trading-assistant-mpl
  .venv/bin/python -m unittest discover -s tests -v
"

# The final release contains no writable code or local secrets/state.
rm -f "${STAGING_DIR}/.env"
rm -rf "${STAGING_DIR}/data"
chown -R root:root "${STAGING_DIR}"
ln -s "${STATE_DIR}" "${STAGING_DIR}/data"
chmod 750 "${STAGING_DIR}/scripts/backup_data.sh"

WAS_ACTIVE=false
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  WAS_ACTIVE=true
  systemctl stop "${SERVICE_NAME}"
fi

# Capture writes that happened after the initial migration, then back up the
# exact state that the new release will use. Before the first switch there is no
# active INSTALL_DIR yet, so the backup must explicitly use the staging code and
# staging Python interpreter.
if [[ -d "${INSTALL_DIR}/data" && ! -L "${INSTALL_DIR}/data" ]]; then
  rsync -a "${INSTALL_DIR}/data/" "${STATE_DIR}/"
fi
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}"
chmod 700 "${STATE_DIR}"
INSTALL_DIR="${STAGING_DIR}" \
DATA_DIR="${STATE_DIR}" \
BACKUP_DIR="${BACKUP_DIR}" \
RETENTION_DAYS=14 \
PYTHON="${STAGING_DIR}/.venv/bin/python" \
  "${STAGING_DIR}/scripts/backup_data.sh"

rm -rf "${PREVIOUS_DIR}"
if [[ -d "${INSTALL_DIR}" ]]; then
  rm -f "${INSTALL_DIR}/.env"
  rm -rf "${INSTALL_DIR}/data"
  chown -R root:root "${INSTALL_DIR}"
  ln -s "${STATE_DIR}" "${INSTALL_DIR}/data"
  mv "${INSTALL_DIR}" "${PREVIOUS_DIR}"
fi
mv "${STAGING_DIR}" "${INSTALL_DIR}"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=FVG Alert Bot
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
UMask=0077
StateDirectory=fvg-alert-bot
StateDirectoryMode=0700
RuntimeDirectory=fvg-alert-bot
RuntimeDirectoryMode=0700
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=MPLCONFIGDIR=/run/fvg-alert-bot/mpl
ExecStart=${INSTALL_DIR}/.venv/bin/python -u bot.py
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
LimitNOFILE=4096
TasksMax=128
MemoryMax=512M

NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${STATE_DIR}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
EOF

cat > "/etc/systemd/system/${BACKUP_SERVICE_NAME}.service" <<EOF
[Unit]
Description=Backup FVG Alert Bot runtime data

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
Environment=INSTALL_DIR=${INSTALL_DIR}
Environment=DATA_DIR=${STATE_DIR}
Environment=BACKUP_DIR=${BACKUP_DIR}
Environment=RETENTION_DAYS=14
ExecStart=${INSTALL_DIR}/scripts/backup_data.sh
Nice=10
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${STATE_DIR} ${BACKUP_DIR}
EOF

cat > "/etc/systemd/system/${BACKUP_SERVICE_NAME}.timer" <<EOF
[Unit]
Description=Daily FVG Alert Bot runtime-data backup

[Timer]
OnCalendar=*-*-* 03:15:00 UTC
Persistent=true
RandomizedDelaySec=15m
Unit=${BACKUP_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

rollback_release() {
  local failed_dir="${INSTALL_DIR}.failed.$(date -u +%Y%m%dT%H%M%SZ)"
  systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
  if [[ -d "${INSTALL_DIR}" ]]; then
    mv "${INSTALL_DIR}" "${failed_dir}"
  fi
  if [[ -d "${PREVIOUS_DIR}" ]]; then
    mv "${PREVIOUS_DIR}" "${INSTALL_DIR}"
    systemctl daemon-reload
    systemctl restart "${SERVICE_NAME}" || true
    echo "Новый релиз не запустился. Выполнен rollback: ${failed_dir}" >&2
  else
    echo "Новый релиз не запустился, предыдущего релиза нет: ${failed_dir}" >&2
  fi
  exit 1
}

systemctl daemon-reload
if ! systemctl enable --now "${SERVICE_NAME}"; then
  rollback_release
fi
sleep 3
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  rollback_release
fi
systemctl enable --now "${BACKUP_SERVICE_NAME}.timer"

echo
echo "Готово. Статус службы:"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
echo
echo "Логи:       journalctl -u ${SERVICE_NAME} -f"
echo "Статус:     systemctl status ${SERVICE_NAME}"
echo "Рестарт:    systemctl restart ${SERVICE_NAME}"
echo "Бэкапы:     systemctl list-timers ${BACKUP_SERVICE_NAME}.timer"
echo "Проверка:   systemctl start ${BACKUP_SERVICE_NAME}.service"
echo "Предыдущий: ${PREVIOUS_DIR}"
