# FVG Alert Bot

Telegram-бот для отслеживания Fair Value Gap (FVG) на фьючерсном рынке
Bitunix. Он специализируется только на FVG: уведомлениях, настройках и
статистике событий. Бот не открывает сделки и не является финансовой
рекомендацией.

## Возможности

- предварительные FVG-уведомления в точке T−3;
- подтверждённые FVG на 15-минутном таймфрейме;
- настройка инструментов, направлений, цены и размера зоны отдельно для
  каждого Telegram-пользователя;
- статистика бычьих и медвежьих FVG, включая доставленные уведомления;
- админ-панель со статистикой пользователей и состоянием сервиса;
- общий WebSocket Bitunix с REST-восстановлением пропущенных данных;
- bounded delivery queue, REST rate limiting и повторные попытки доставки;
- production-default с закрытым доступом и ограничениями ресурсов;
- SQLite/WAL для событий, доставок, persistent outbox и health-метрик;
- атомарное VDS-обновление, rollback и ежедневные резервные копии;
- event-quality backtest без выдуманных торговых правил и P&L.

## Локальный запуск

1. Создайте `.env` рядом с `bot.py`, используя `.env.example`:

   ```env
   TELEGRAM_TOKEN=токен_от_BotFather
   ALLOWED_TELEGRAM_IDS=123456789
   ADMIN_TELEGRAM_IDS=123456789
   PUBLIC_ACCESS_ENABLED=false
   ```

2. Создайте virtualenv и установите зависимости:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. Запустите бота:

   ```bash
   .venv/bin/python bot.py
   ```

`PUBLIC_ACCESS_ENABLED=false` — безопасный режим по умолчанию. Публичный доступ
нужно включать явно. `BITUNIX_API_KEY` и `BITUNIX_SECRET` для FVG не требуются.

Для локального перезапуска доступен `./restart_bot.py`: он останавливает только
экземпляры `bot.py`, запущенные из текущей папки проекта.

## Установка на Ubuntu/Debian VDS

Инструкция рассчитана на Ubuntu 22.04/24.04 и Debian 12. Установщик создаёт
изолированную службу `systemd`, отдельного системного пользователя, постоянное
хранилище SQLite, автоматические резервные копии и rollback при неудачном
обновлении.

> Один Telegram-токен может обслуживаться только одним polling-процессом.
> Перед запуском на VDS остановите локальный экземпляр бота и другие службы,
> использующие тот же токен.

### Что потребуется

- VDS с Ubuntu 22.04/24.04 или Debian 12;
- доступ к серверу под `root` или пользователь с `sudo`;
- токен Telegram-бота, полученный у BotFather;
- числовой Telegram ID администратора;
- исходящий доступ по HTTPS/WSS к Telegram и Bitunix;
- не менее 512 МБ свободного места и 5000 свободных inode на файловой системе `/opt`.

Входящие порты для работы polling-бота открывать не требуется. Домен и
веб-сервер также не нужны.

### Быстрая установка рекомендуемого релиза

Подключитесь к серверу под `root`:

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
```

Установите Git, скачайте проект и выберите текущий release candidate:

```bash
apt update && apt install -y git
git clone https://github.com/mishkacher/TB.git /root/TB
cd /root/TB
git fetch --tags
git checkout v1.0.0-rc4
bash scripts/install_vds.sh
```

Во время первой установки скрипт последовательно запросит:

1. токен BotFather — ввод скрыт;
2. числовой Telegram ID администратора — ввод отображается.

Введённый ID автоматически записывается одновременно в
`ADMIN_TELEGRAM_IDS` и `ALLOWED_TELEGRAM_IDS`. Production-доступ остаётся
закрытым для остальных пользователей.

Установщик автоматически:

- проверит свободное место и inode до загрузки зависимостей и запуска тестов;
- установит `python3`, `python3-venv`, `python3-pip`, `rsync` и Git;
- создаст системного пользователя `fvgbot` без интерактивного входа;
- подготовит новый релиз в отдельном staging-каталоге;
- установит зависимости в изолированный virtualenv без сохранения `pip`-кэша;
- разместит временные файлы `pip`, SQLite-тестов и Matplotlib внутри staging;
- выполнит компиляцию Python и полный набор unit-тестов;
- остановит работающий бот только после успешной проверки кандидата;
- сохранит runtime-state и создаст резервную копию;
- атомарно переключит активный релиз;
- создаст и запустит `systemd`-службу;
- включит ежедневный backup-таймер;
- автоматически вернёт предыдущий релиз, если новый процесс не запустится.

Повторный запуск установщика не спрашивает токен и ID заново: он использует
существующий файл `/etc/fvg-alert-bot.env`.

Если установка старого релиза остановилась с одним из сообщений:

```text
duration ... exceeds limit 20.000s
Python executable does not exist: /opt/fvg-alert-bot/.venv/bin/python
sqlite3.OperationalError: database or disk is full
```

проверьте и освободите место, затем переключитесь на исправленный релиз:

```bash
df -h / /tmp /opt
df -ih / /tmp /opt
rm -rf /root/.cache/pip
find /opt -maxdepth 1 -type d -name 'fvg-alert-bot.staging.*' -print -exec rm -rf -- {} +
apt-get clean

cd /root/TB
git fetch --tags --prune
git checkout v1.0.0-rc4
bash scripts/install_vds.sh
```

Не удаляйте `/etc/fvg-alert-bot.env` и `/var/lib/fvg-alert-bot`. Токен и
Telegram ID уже сохранены; повторно вводить их не потребуется. На чистой
установке отсутствие unit-файла после этих ошибок нормально: сбой произошёл до
атомарного переключения релиза. Подробности приведены в
[памятке восстановления](docs/VDS_FIRST_INSTALL_RECOVERY.md).

### Проверка после установки

Проверьте, что служба активна и включена в автозагрузку:

```bash
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
```

Посмотрите последние логи:

```bash
journalctl -u fvg-alert-bot -n 100 --no-pager
```

Для просмотра логов в реальном времени:

```bash
journalctl -u fvg-alert-bot -f
```

Проверьте резервное копирование:

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl status fvg-alert-bot-backup.timer --no-pager
```

После этого откройте Telegram, отправьте боту `/menu`, а затем `/admin`.
В админ-панели отображаются состояние WebSocket, REST recovery, SQLite и
Telegram outbox.

### Где хранятся файлы

| Назначение | Путь |
|---|---|
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state и SQLite | `/var/lib/fvg-alert-bot` |
| Секреты и production-настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

Код и virtualenv принадлежат `root`. Процесс `fvgbot` может записывать данные
только в `/var/lib/fvg-alert-bot`.

### Изменение production-настроек

Откройте конфигурацию:

```bash
nano /etc/fvg-alert-bot.env
```

Минимальная конфигурация:

```env
TELEGRAM_TOKEN=токен_из_BotFather
ADMIN_TELEGRAM_IDS=123456789
ALLOWED_TELEGRAM_IDS=123456789
PUBLIC_ACCESS_ENABLED=false
```

Несколько Telegram ID перечисляются через запятую без пробелов или с пробелами:

```env
ADMIN_TELEGRAM_IDS=123456789,987654321
ALLOWED_TELEGRAM_IDS=123456789,987654321,555555555
```

При закрытом доступе ID администратора должен присутствовать и в
`ALLOWED_TELEGRAM_IDS`. Не публикуйте токен в GitHub, чатах, логах или
скриншотах.

После редактирования восстановите права и перезапустите службу:

```bash
chown root:fvgbot /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
```

Доступные защитные лимиты и operational alerts:

```env
MAX_ACTIVE_SYMBOLS=100
MAX_SYMBOLS_PER_USER=20
FVG_DELIVERY_QUEUE_SIZE=1000
HEALTH_WRITE_INTERVAL_SECONDS=30
BITUNIX_REQUESTS_PER_SECOND=8
HEALTH_ALERT_INTERVAL_SECONDS=60
HEALTH_ALERT_STALE_WS_SECONDS=180
HEALTH_ALERT_OUTBOX_THRESHOLD=100
HEALTH_ALERT_COOLDOWN_SECONDS=1800
```

### Безопасное обновление

Для production рекомендуется обновляться между опубликованными тегами. Вместо
`vНОВАЯ_ВЕРСИЯ` подставьте нужный тег из раздела Releases:

```bash
cd /root/TB
git fetch --tags --prune
git checkout vНОВАЯ_ВЕРСИЯ
bash scripts/install_vds.sh
```

Для тестового обновления непосредственно из `main`:

```bash
cd /root/TB
git checkout main
git pull --ff-only
bash scripts/install_vds.sh
```

Установщик сначала полностью проверяет staging-релиз. Работающая служба
останавливается только после успешной установки зависимостей, компиляции и
unit-тестов. Если новый процесс не становится активным, выполняется
автоматический rollback.

### Резервные копии

Backup-таймер запускается ежедневно около `03:15 UTC` с небольшим случайным
сдвигом. По умолчанию архивы хранятся 14 дней.

Запустить резервное копирование вручную:

```bash
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Перед любым ручным восстановлением сначала сделайте отдельную копию текущего
содержимого `/var/lib/fvg-alert-bot`.

### Ручной rollback

Установщик сохраняет один предыдущий релиз. Убедитесь, что каталог существует:

```bash
test -d /opt/fvg-alert-bot.previous && echo "Предыдущий релиз найден"
```

Затем выполните:

```bash
FAILED_DIR="/opt/fvg-alert-bot.failed-manual.$(date -u +%Y%m%dT%H%M%SZ)"
systemctl stop fvg-alert-bot
mv /opt/fvg-alert-bot "${FAILED_DIR}"
mv /opt/fvg-alert-bot.previous /opt/fvg-alert-bot
systemctl start fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
```

Runtime-state в `/var/lib/fvg-alert-bot` и секреты в
`/etc/fvg-alert-bot.env` при rollback не изменяются.

### Диагностика

#### Telegram сообщает `Conflict`

С тем же токеном работает другой polling-процесс. Остановите локальный бот или
другую VDS-службу с этим токеном.

#### Служба перезапускается или не запускается

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
```

#### Проверка диска и inode

```bash
df -h / /tmp /opt
df -ih / /tmp /opt
du -xh /root/.cache/pip /opt /var/log --max-depth=1 2>/dev/null | sort -h
```

По умолчанию установщик требует 512 МБ свободного места и 5000 inode на `/opt`.
Порог можно повысить для конкретного запуска:

```bash
FVG_INSTALL_MIN_FREE_MB=1024 FVG_INSTALL_MIN_FREE_INODES=10000 \
  bash scripts/install_vds.sh
```

#### Проверка сети

```bash
getent hosts api.telegram.org
getent hosts fapi.bitunix.com
```

Боту нужен исходящий HTTPS/WSS-доступ. Входящие TCP-порты для polling-режима
не требуются.

#### Проверка прав на файлы

```bash
namei -l /opt/fvg-alert-bot/bot.py
namei -l /var/lib/fvg-alert-bot
namei -l /etc/fvg-alert-bot.env
```

Код должен принадлежать `root`, state — `fvgbot`, а env-файл —
`root:fvgbot` с правами `640`.

Расширенная процедура backup/restore и canary-проверки описана в
[отдельном документе](docs/VDS_DEPLOYMENT.md).

## Команды

- `/menu` — панель настроек FVG;
- `/fvg_alert on|off` — включить или выключить FVG-уведомления;
- `/fvg_pre_alert on|off` — включить или выключить пред-FVG T−3;
- `/fvg_symbol add ETHUSDT` — добавить инструмент в наблюдение;
- `/fvg_symbol remove ETHUSDT` — убрать инструмент;
- `/fvg_price BTCUSDT 50000 90000 both` — настроить ценовой фильтр;
- `/fvg_size` — настроить фильтр размера зоны;
- `/fvg_stats` — показать статистику FVG;
- `/admin` — админ-панель, статистика пользователей и состояние сервиса.

## Историческая проверка FVG

Загрузите публичные свечи Bitunix:

```bash
.venv/bin/python download_bitunix_history.py \
  --symbol BTCUSDT --interval 15m \
  --start 2025-01-01 --end 2026-01-01 \
  --output data/historical/btcusdt_15m_2025.csv
```

Постройте event-quality отчёт:

```bash
.venv/bin/python run_fvg_quality_backtest.py \
  --data-file data/historical/btcusdt_15m_2025.csv \
  --symbol BTCUSDT \
  --output data/reports/btcusdt_fvg_quality_2025.json
```

Отчёт измеряет touch/full fill, задержку заполнения, MFE/MAE и горизонты
1/4/16/96 свечей. Он не считает доходность, потому что бот не задаёт entry,
stop-loss и take-profit. Методология описана в
[документе бэктеста](docs/FVG_BACKTEST.md).

## Проверки

Текущие handler-тесты используют явно включённый публичный test fixture:

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

CI проверяет shell-скрипты, компиляцию Python, unit-тесты, dependency audit,
bounded soak, Linux/systemd units и non-blocking research smoke по публичным
данным Bitunix.
