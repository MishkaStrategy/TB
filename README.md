# FVG Alert Bot

![Version](https://img.shields.io/badge/version-1.3.0-2ea44f)
![Python](https://img.shields.io/badge/Python-3.12-3776ab)
![Telegram](https://img.shields.io/badge/interface-Telegram-2aabee)
![Status](https://img.shields.io/badge/status-release--candidate-f59e0b)

Telegram-бот для мониторинга **Fair Value Gap (FVG)** и ставок фандинга на фьючерсных биржах. Бот собирает публичные рыночные данные, применяет персональные фильтры, отправляет уведомления и показывает операционное состояние прямо в Telegram.

Бот **не открывает сделки**, не управляет средствами пользователя и не является финансовой рекомендацией.

Следующий релиз: **1.3.0**. Telegram Mini App и новый графический WebApp-интерфейс в эту версию не входят.

## Что входит в 1.3.0

### FVG

- настройка по схеме `биржа → пара → таймфреймы → подтверждение`;
- до 10 уникальных комбинаций `биржа + торговая пара` на Telegram ID;
- подтверждённые FVG на `15m`, `1h`, `4h`, `1d`;
- сигнал только после закрытия свечи C;
- BTC-only пред-FVG T−3 только на `15m`;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- отдельное включение бычьих и медвежьих сигналов;
- pause/delete и изменение таймфреймов;
- exchange-aware фильтры цены и размера зоны;
- отдельный FAQ по FVG-инструментам;
- один расчёт на уникальную комбинацию `биржа + символ + таймфрейм`, независимо от числа получателей.

Старые FVG settings schema v2 автоматически мигрируют в schema v3: существующие символы получают биржу Bitunix и таймфрейм `15m`, направления и фильтры сохраняются.

### Мультибиржевой фандинг

Поддерживаются Bitunix, Binance, Bybit, BingX, Bitget и Gate.

- общий снимок каждые 15 минут на `:00`, `:15`, `:30`, `:45` UTC;
- интервал уведомлений от `15` до `2880` минут с шагом `15` минут;
- минимальный абсолютный процент;
- положительное, отрицательное или оба направления;
- выбор одной или нескольких бирж;
- только три последних сжатых снимка в `funding_snapshot_history`.

### Telegram-интерфейс

После `/start` доступно постоянное нижнее меню:

- `📉 FVG`;
- `💸 Фандинг`;
- `🔔 Уведомления`;
- `📊 Статистика`;
- `⚙️ Настройки`;
- `❤️ Донат`.

Для каждого Telegram ID отдельно сохраняются язык RU/EN, compact/detailed формат, FVG-инструменты и фильтры, funding alerts и выбранные биржи.

### Админ-панель и «⚙️ Операции»

Команда `/admin` доступна только ID из `ADMIN_TELEGRAM_IDS`.

Панель показывает WebSocket, REST recovery, outbox, ошибки доставки, SQLite, ресурсы, backup, VERSION/BUILD_COMMIT и позволяет выполнить подтверждаемый systemd restart.

Read-only экран `⚙️ Операции` дополнительно показывает:

- lifecycle процесса и фоновые задачи;
- SQLite observability snapshots;
- состояние restart circuit breaker, cooldown, quota и последние решения;
- состояние FVG history archive;
- размеры archive main/WAL/SHM;
- schema metadata, последние archive runs и batch statistics;
- archive counters, failures, backlog signal и последнюю ошибку.

Operational readers открывают SQLite через `mode=ro` и `PRAGMA query_only=ON`. Экран не выполняет migration, repair, archive audit, export/restore, compaction, circuit reset или restart.

## Надёжность

- persistent Telegram delivery status;
- feature-flagged Outbox V2 с bounded retry, expiration и dead-letter;
- SQLite/WAL event store и funding store;
- read-only SQLite growth observability;
- проверяемые backup с manifest и SHA-256;
- persistent leases и watchdog фоновых задач;
- bounded graceful shutdown;
- archive-before-delete для terminal FVG history;
- read-only archive audit CLI;
- persistent restart circuit breaker;
- атомарная VDS-установка и автоматический rollback;
- Bot API-only deployment без Telegram App credentials.

Рискованные operational-функции выключены по умолчанию и включаются поэтапно через `.env`.

Подробности:

- [`docs/RELEASE_1.3.0.md`](docs/RELEASE_1.3.0.md);
- [`docs/FVG_MULTI_INSTRUMENTS.md`](docs/FVG_MULTI_INSTRUMENTS.md);
- [`docs/ADMIN_OPERATIONS_STATUS.md`](docs/ADMIN_OPERATIONS_STATUS.md);
- [`docs/PROCESS_RESTART_CIRCUIT_BREAKER.md`](docs/PROCESS_RESTART_CIRCUIT_BREAKER.md);
- [`docs/FVG_HISTORY_ARCHIVE.md`](docs/FVG_HISTORY_ARCHIVE.md);
- [`docs/VDS_BOT_API_ONLY_UPDATE.md`](docs/VDS_BOT_API_ONLY_UPDATE.md).

## Telegram credentials

Для работы нужен только Bot API token от BotFather:

```env
TELEGRAM_TOKEN=токен_от_BotFather
ADMIN_TELEGRAM_IDS=123456789
ALLOWED_TELEGRAM_IDS=123456789
PUBLIC_ACCESS_ENABLED=false
```

Не используются `API_ID`, `API_HASH`, Telethon, Pyrogram, вход по номеру телефона или user-session string.

API-ключи бирж для текущих FVG и funding-данных не требуются.

## Локальный запуск

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
PUBLIC_ACCESS_ENABLED=true .venv/bin/python bot.py
```

## Первая установка на Ubuntu/Debian VDS

Поддерживаются Ubuntu 22.04/24.04 и Debian 12. Рекомендуется не менее 1 ГБ свободного места на `/opt` и 5000 inode.

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
apt update && apt install -y git
git clone https://github.com/MishkaStrategy/TB.git /root/TB
cd /root/TB
git checkout main
test "$(cat VERSION)" = "1.3.0"
FVG_INSTALL_MIN_FREE_MB=1024 bash scripts/install_vds.sh
```

Установщик собирает staging-релиз и запускает unit suite до остановки работающего процесса. Затем создаёт backup, атомарно переключает релиз и автоматически возвращает предыдущую версию при ошибке запуска.

## Обновление существующего VDS до 1.3.0

Production обновляется только после публикации проверенного тега `v1.3.0` и SHA:

```bash
cd /root/TB
git status --short
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.0 \
  EXPECTED_VERSION=1.3.0 \
  EXPECTED_COMMIT=ПРОВЕРЕННЫЙ_SHA \
  bash scripts/update_vds_bot_api_only.sh
```

Сохраняются `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot`, пользовательские настройки и SQLite. Wrapper блокирует Telegram App/user-session credentials, не печатая токен.

## Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 150 --no-pager

sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
```

Ожидается версия `1.3.0`, точный audited SHA, `active`, `enabled` и `ok` для обеих SQLite-баз.

Telegram smoke:

- `/start`, `/menu`, `/funding`, `/admin`, `/donate`;
- добавление FVG-инструмента и выбор `15m/1h/4h/1d`;
- повторное открытие и сохранение настроек;
- RU/EN и compact/detailed;
- `⚙️ Операции`: restart guard и FVG archive.

## Production flags

```env
MAX_ACTIVE_SYMBOLS=100
MAX_SYMBOLS_PER_USER=10
FVG_DELIVERY_QUEUE_SIZE=1000

DELIVERY_STATUS_TRACKING_ENABLED=false
USER_BLOCK_STATUS_ENABLED=false
OUTBOX_RETRY_POLICY_ENABLED=false
OUTBOX_EXPIRATION_ENABLED=false
DATABASE_OBSERVABILITY_ENABLED=false
BACKGROUND_TASK_REGISTRY_ENABLED=false
BACKGROUND_TASK_WATCHDOG_ENABLED=false
RUNTIME_LIFECYCLE_ENABLED=false
GRACEFUL_SHUTDOWN_ENABLED=false
FVG_HISTORY_ARCHIVE_ENABLED=false
FVG_PROCESS_GRACEFUL_RESTART_ENABLED=false
FVG_PROCESS_RESTART_GUARD_ENABLED=false
```

После ручного изменения:

```bash
chown root:fvgbot /etc/fvg-alert-bot.env
chmod 640 /etc/fvg-alert-bot.env
systemctl restart fvg-alert-bot
```

## Файлы на VDS

| Назначение | Путь |
|---|---|
| Активный релиз | `/opt/fvg-alert-bot` |
| Предыдущий релиз | `/opt/fvg-alert-bot.previous` |
| Runtime-state и SQLite | `/var/lib/fvg-alert-bot` |
| Секреты и production-настройки | `/etc/fvg-alert-bot.env` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

## Backup и rollback

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Установщик хранит предыдущий релиз в `/opt/fvg-alert-bot.previous`. Verified backup включает manifest, SHA-256 и согласованные SQLite snapshots. Live WAL/SHM не копируются как обычные файлы.

## Диагностика

```bash
journalctl -u fvg-alert-bot -n 200 --no-pager
systemctl show fvg-alert-bot \
  -p NRestarts -p ExecMainStatus -p Result -p MemoryCurrent
df -h / /tmp /opt
df -ih / /tmp /opt
```

Telegram `Conflict` означает, что тот же Bot API token используется другим polling-процессом.

## Команды

- `/menu` — открыть меню;
- `/fvg_alert on|off` — подтверждённые FVG;
- `/fvg_pre_alert on|off` — пред-FVG T−3;
- `/fvg_symbol` — FVG instruments wizard;
- `/fvg_price` — ценовой фильтр;
- `/fvg_size` — фильтр размера зоны;
- `/fvg_stats` — статистика FVG;
- `/funding` — рейтинг и funding alerts;
- `/admin` — админ-панель;
- `/donate` — поддержать проект.

## Проверки

```bash
PUBLIC_ACCESS_ENABLED=true \
MPLCONFIGDIR=/tmp/trading-assistant-mpl \
  .venv/bin/python -m unittest discover -s tests -v
```

CI включает dependency audit, compilation, release contract, FVG migration/timeframe tests, оба новых read-only admin sections, полный unit suite, bounded 500×10 soak и production systemd verification.

После публикации release workflow создаёт тег `v1.3.0`, GitHub Release, архив `fvg-alert-bot-1.3.0.tar.gz` и SHA-256 checksum.
