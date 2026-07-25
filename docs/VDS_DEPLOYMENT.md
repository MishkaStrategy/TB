# Установка FVG Alert Bot на VDS

Инструкция рассчитана на Ubuntu 22.04/24.04 или Debian 12. Установочный скрипт
создаёт изолированную systemd-службу, проверяет релиз до переключения, сохраняет
runtime-state отдельно от кода и выполняет автоматический rollback, если новый
процесс не запустился.

> Один Telegram-токен может обслуживаться только одним polling-процессом. Перед
> включением VDS остановите локальный экземпляр бота.

## Быстрая установка

Подключитесь к серверу под `root` и выполните:

```bash
apt update && apt install -y git
git clone https://github.com/mishkacher/TB.git /root/TB
cd /root/TB
bash scripts/install_vds.sh
```

Скрипт запросит токен BotFather и Telegram ID администратора. После успешных
тестов он создаст и запустит:

- `fvg-alert-bot.service` — основной бот;
- `fvg-alert-bot-backup.timer` — ежедневный backup runtime-state;
- отдельного системного пользователя `fvgbot` без интерактивного входа.

## Размещение файлов

| Назначение | Путь |
|---|---|
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state | `/var/lib/fvg-alert-bot` |
| Секреты и настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

Код и virtualenv принадлежат `root` и недоступны для записи процессу бота.
Пользователь `fvgbot` может изменять только `/var/lib/fvg-alert-bot`.

## Настройки

Изменяйте production-конфигурацию здесь:

```bash
nano /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
chown root:fvgbot /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
```

Минимальная конфигурация:

```env
TELEGRAM_TOKEN=токен_из_BotFather
ADMIN_TELEGRAM_IDS=ваш_Telegram_ID
ALLOWED_TELEGRAM_IDS=ваш_Telegram_ID
PUBLIC_ACCESS_ENABLED=false
```

`PUBLIC_ACCESS_ENABLED=false` — безопасный production-default. Публичный режим
нужно включать только осознанно. API-ключи Bitunix для FVG-уведомлений не нужны.

Доступны защитные лимиты:

```env
MAX_ACTIVE_SYMBOLS=100
MAX_SYMBOLS_PER_USER=20
FVG_DELIVERY_QUEUE_SIZE=1000
HEALTH_WRITE_INTERVAL_SECONDS=30
BITUNIX_REQUESTS_PER_SECOND=8
```

## Проверка службы

```bash
systemctl status fvg-alert-bot
journalctl -u fvg-alert-bot -f
systemctl is-enabled fvg-alert-bot
systemctl is-active fvg-alert-bot
```

Проверка применённого sandboxing:

```bash
systemd-analyze security fvg-alert-bot.service
systemctl cat fvg-alert-bot.service
```

Служба использует, среди прочего, `NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, пустой capability set, ограничение address families, лимиты памяти,
файловых дескрипторов и процессов.

## Безопасное обновление

Обновите исходный checkout и повторно запустите установщик:

```bash
cd /root/TB
git pull --ff-only
bash scripts/install_vds.sh
```

Обновление проходит так:

1. код копируется в staging-каталог;
2. создаётся новый virtualenv;
3. выполняются `compileall` и все unit-тесты;
4. работающий бот останавливается только после успешных тестов;
5. делается backup runtime-state;
6. staging атомарно становится `/opt/fvg-alert-bot`;
7. systemd проверяет запуск нового процесса;
8. при ошибке автоматически возвращается предыдущий релиз.

Таким образом, ошибка зависимостей или тестов не останавливает текущий процесс.

## Резервные копии

Таймер запускается ежедневно около `03:15 UTC` с небольшим случайным сдвигом.
По умолчанию архивы хранятся 14 дней.

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service
ls -lah /var/backups/fvg-alert-bot
```

Архив содержит содержимое `/var/lib/fvg-alert-bot`, а не только символическую
ссылку `data` из каталога релиза.

### Восстановление state

```bash
systemctl stop fvg-alert-bot
rm -rf /var/lib/fvg-alert-bot/*
tar -C /var/lib/fvg-alert-bot -xzf \
  /var/backups/fvg-alert-bot/fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz
chown -R fvgbot:fvgbot /var/lib/fvg-alert-bot
chmod 700 /var/lib/fvg-alert-bot
systemctl start fvg-alert-bot
```

Перед восстановлением сохраните отдельную копию текущего state.

## Ручной rollback релиза

Установщик оставляет один предыдущий релиз:

```bash
systemctl stop fvg-alert-bot
mv /opt/fvg-alert-bot /opt/fvg-alert-bot.failed-manual
mv /opt/fvg-alert-bot.previous /opt/fvg-alert-bot
systemctl start fvg-alert-bot
systemctl status fvg-alert-bot
```

Runtime-state и `/etc/fvg-alert-bot.env` при rollback не меняются.

## Диагностика

### Telegram сообщает `Conflict`

С тем же токеном работает другой polling-процесс. Остановите локальный бот или
другую VDS-службу.

### Служба перезапускается

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
```

### Проверка сети

Боту нужен исходящий HTTPS/WSS-доступ к Telegram и Bitunix. Входящие TCP-порты
для polling-бота открывать не требуется.

### Проверка файловых прав

```bash
namei -l /opt/fvg-alert-bot/bot.py
namei -l /var/lib/fvg-alert-bot
namei -l /etc/fvg-alert-bot.env
```

Код должен принадлежать `root`, state — `fvgbot`, а env-файл — `root:fvgbot` с
правами `640`.
