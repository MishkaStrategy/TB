# Установка и обновление FVG Alert Bot на VDS

Инструкция рассчитана на Ubuntu 22.04/24.04 или Debian 12. Production-установка
использует изолированную systemd-службу, отдельный runtime-state, ежедневные
backup и автоматический rollback при неудачном запуске нового релиза.

> Один Telegram-токен может обслуживаться только одним polling-процессом. Перед
> включением VDS остановите локальный экземпляр бота.

## Размещение файлов

| Назначение | Путь |
|---|---|
| Git checkout для обновлений | `/root/TB` |
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state | `/var/lib/fvg-alert-bot` |
| Секреты и настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

Код и virtualenv принадлежат `root`. Пользователь `fvgbot` может изменять только
`/var/lib/fvg-alert-bot`.

## Первая установка 1.1.0

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
apt update && apt install -y git
git clone https://github.com/mishkacher/TB.git /root/TB
cd /root/TB
git checkout main
test "$(cat VERSION)" = "1.1.0"
FVG_INSTALL_MIN_FREE_MB=1024 bash scripts/install_vds.sh
```

Скрипт запросит токен BotFather и Telegram ID администратора, затем создаст:

- `fvg-alert-bot.service` — основной бот;
- `fvg-alert-bot-backup.timer` — ежедневный backup runtime-state;
- системного пользователя `fvgbot` без интерактивного входа.

## Безопасное обновление существующего сервера

Для обновления до `1.1.0` используйте wrapper:

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
cd /root/TB
git fetch origin --prune
git checkout main
git pull --ff-only origin main
EXPECTED_VERSION=1.1.0 bash scripts/update_vds.sh
```

Wrapper выполняет:

1. проверку root, Git checkout и существующей установки;
2. отказ при несохранённых локальных изменениях;
3. fast-forward обновление ветки `main`;
4. проверку целевой версии;
5. согласованный pre-update backup JSON и SQLite-state;
6. запуск атомарного `install_vds.sh`;
7. проверку systemd, версии и runtime-ссылки;
8. `PRAGMA quick_check` для `fvg_event_store.sqlite3` и
   `funding_alerts.sqlite3`;
9. запись Git SHA в `/opt/fvg-alert-bot/BUILD_COMMIT`.

Атомарный установщик сначала собирает staging-релиз и выполняет все unit-тесты.
Работающий бот останавливается только после успешных проверок. Если новый процесс
не запускается, `/opt/fvg-alert-bot.previous` возвращается автоматически.

## Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
```

Ожидаемая версия:

```text
1.1.0
```

Проверьте базы:

```bash
/opt/fvg-alert-bot/.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path

root = Path('/var/lib/fvg-alert-bot')
for name in ('fvg_event_store.sqlite3', 'funding_alerts.sqlite3'):
    path = root / name
    with sqlite3.connect(path) as connection:
        print(name, connection.execute('PRAGMA quick_check').fetchone()[0])
PY
```

В Telegram откройте `/funding` → `🔔 Уведомления`, сохраните настройки и
проверьте, что следующая контрольная точка назначена на `HH:50 UTC`.

## Production-настройки

```bash
nano /etc/fvg-alert-bot.env
chown root:fvgbot /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
```

Минимальная конфигурация:

```env
TELEGRAM_TOKEN=токен_из_BotFather
ADMIN_TELEGRAM_IDS=ваш_Telegram_ID
ALLOWED_TELEGRAM_IDS=ваш_Telegram_ID
PUBLIC_ACCESS_ENABLED=false
```

API-ключи Bitunix для FVG и funding не требуются.

## Резервные копии

Таймер запускается ежедневно около `03:15 UTC` с небольшим случайным сдвигом.
Архивы по умолчанию хранятся 14 дней.

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Backup содержит:

- JSON-настройки из `/var/lib/fvg-alert-bot`;
- согласованный снимок `fvg_event_store.sqlite3`;
- согласованный снимок `funding_alerts.sqlite3`.

Live-файлы `*-wal` и `*-shm` не копируются. Для обеих баз используется SQLite
backup API, поэтому архив остаётся согласованным при работающем боте.

## Восстановление runtime-state

```bash
systemctl stop fvg-alert-bot
mkdir -p /var/lib/fvg-alert-bot.before-restore
cp -a /var/lib/fvg-alert-bot/. /var/lib/fvg-alert-bot.before-restore/
rm -rf /var/lib/fvg-alert-bot/*
tar -C /var/lib/fvg-alert-bot -xzf \
  /var/backups/fvg-alert-bot/fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz
chown -R fvgbot:fvgbot /var/lib/fvg-alert-bot
chmod 700 /var/lib/fvg-alert-bot
systemctl start fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
```

## Ручной rollback релиза

```bash
systemctl stop fvg-alert-bot
mv /opt/fvg-alert-bot /opt/fvg-alert-bot.failed-manual
mv /opt/fvg-alert-bot.previous /opt/fvg-alert-bot
systemctl daemon-reload
systemctl start fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
```

Runtime-state и `/etc/fvg-alert-bot.env` при rollback не меняются.

## Диагностика

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
systemd-analyze security fvg-alert-bot.service
systemctl cat fvg-alert-bot.service
df -h / /tmp /opt
df -ih / /tmp /opt
getent hosts api.telegram.org
getent hosts fapi.bitunix.com
namei -l /opt/fvg-alert-bot/bot.py
namei -l /var/lib/fvg-alert-bot
namei -l /etc/fvg-alert-bot.env
```

Telegram `Conflict` означает, что тот же токен используется другим
polling-процессом.
