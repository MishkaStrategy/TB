#!/usr/bin/env bash
# Установка FVG Alert Bot на Ubuntu/Debian VDS.
# Запуск: sudo bash scripts/install_vds.sh

set -euo pipefail

SERVICE_USER="fvgbot"
INSTALL_DIR="/opt/fvg-alert-bot"
SERVICE_NAME="fvg-alert-bot"
BACKUP_SERVICE_NAME="fvg-alert-bot-backup"
BACKUP_DIR="/var/backups/fvg-alert-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите скрипт с sudo: sudo bash scripts/install_vds.sh"
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/bot.py" ]]; then
  echo "Скрипт нужно запускать из папки проекта FVG Alert Bot."
  exit 1
fi

echo "Устанавливаю системные зависимости…"
apt update
apt install -y git python3 python3-venv python3-pip rsync

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  adduser --system --group --home /var/lib/fvgbot "${SERVICE_USER}"
fi

mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.venv-ci' \
  --exclude '.env' \
  --exclude 'data' \
  "${PROJECT_DIR}/" "${INSTALL_DIR}/"

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"

  read -r -s -p "Введите токен BotFather: " TELEGRAM_TOKEN
  echo
  read -r -p "Введите ваш числовой Telegram ID (админ): " TELEGRAM_ID

  if [[ -z "${TELEGRAM_TOKEN}" || ! "${TELEGRAM_ID}" =~ ^[0-9]+$ ]]; then
    echo "Токен или Telegram ID заполнен неверно. Установка остановлена."
    exit 1
  fi

  sed -i "s|^TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=${TELEGRAM_TOKEN}|" "${INSTALL_DIR}/.env"
  sed -i "s|^ADMIN_TELEGRAM_IDS=.*|ADMIN_TELEGRAM_IDS=${TELEGRAM_ID}|" "${INSTALL_DIR}/.env"
  sed -i "s|^ALLOWED_TELEGRAM_IDS=.*|ALLOWED_TELEGRAM_IDS=${TELEGRAM_ID}|" "${INSTALL_DIR}/.env"
fi

mkdir -p "${INSTALL_DIR}/data" /tmp/trading-assistant-mpl "${BACKUP_DIR}"
chmod 700 "${INSTALL_DIR}/data" /tmp/trading-assistant-mpl "${BACKUP_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/data" /tmp/trading-assistant-mpl

# Install and update the virtual environment as root, then lock all executable
# code down. The service account receives write access only to runtime data.
echo "Создаю виртуальное окружение и устанавливаю зависимости…"
python3 -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${INSTALL_DIR}/.venv/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt"

chown -R root:root "${INSTALL_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/data"
chown root:"${SERVICE_USER}" "${INSTALL_DIR}/.env"
chmod 640 "${INSTALL_DIR}/.env"
chmod 750 "${INSTALL_DIR}/scripts/backup_data.sh"

echo "Проверяю код перед запуском службы…"
runuser -u "${SERVICE_USER}" -- bash -c "
  set -euo pipefail
  cd '${INSTALL_DIR}'
  export PUBLIC_ACCESS_ENABLED=true
  export MPLCONFIGDIR=/tmp/trading-assistant-mpl
  .venv/bin/python -m compileall -q \
    bot.py config.py alerts database exchanges handlers tests
  .venv/bin/python -m unittest discover -s tests -v
"

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
UMask=0077
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
ReadWritePaths=${INSTALL_DIR}/data
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
Environment=BACKUP_DIR=${BACKUP_DIR}
Environment=RETENTION_DAYS=14
ExecStart=${INSTALL_DIR}/scripts/backup_data.sh
Nice=10
IOSchedulingClass=idle
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}/data ${BACKUP_DIR}
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

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl enable --now "${BACKUP_SERVICE_NAME}.timer"

echo
echo "Готово. Статус службы:"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
echo
echo "Логи:      journalctl -u ${SERVICE_NAME} -f"
echo "Статус:    systemctl status ${SERVICE_NAME}"
echo "Рестарт:   systemctl restart ${SERVICE_NAME}"
echo "Бэкапы:    systemctl list-timers ${BACKUP_SERVICE_NAME}.timer"
echo "Проверка:  systemctl start ${BACKUP_SERVICE_NAME}.service"
