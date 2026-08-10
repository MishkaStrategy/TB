# FVG Alert Bot

![Version](https://img.shields.io/badge/version-1.3.5-2ea44f)
![Python](https://img.shields.io/badge/Python-3.12-3776ab)
![Telegram](https://img.shields.io/badge/interface-Telegram-2aabee)
![Status](https://img.shields.io/badge/status-stable-2ea44f)

Telegram-бот для мониторинга **Fair Value Gap (FVG)** и ставок фандинга на фьючерсных биржах. Бот собирает публичные рыночные данные, применяет персональные фильтры, отправляет уведомления и показывает операционное состояние прямо в Telegram.

Бот **не открывает сделки**, не управляет средствами пользователя и не является финансовой рекомендацией.

Текущий релиз: **1.3.5**. Это immutable patch-релиз актуального мультибиржевого FVG runtime и впервые официальный релиз, содержащий Telegram Mini App frontend и защищённый backend. Mini App backend выключен по умолчанию, Telegram UI остаётся основным и резервным интерфейсом, а deployment/активация Mini App выполняются отдельным контролируемым этапом без автоматического изменения production env, SQLite, BotFather, Xray или port 443.

## Что входит в 1.3.x

### FVG

- настройка по схеме `биржа → пара → таймфреймы → подтверждение`;
- до 10 уникальных комбинаций `биржа + торговая пара` на Telegram ID;
- подтверждённые FVG на `15m`, `1h`, `4h`, `1d`;
- сигнал только после закрытия свечи C;
- единый источник рыночных данных FVG — закрытые `15m` свечи;
- `1h = 4 × 15m`, `4h = 16 × 15m`, `1d = 96 × 15m` по UTC-границам;
- пред-FVG и `1m` не используются;
- Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- отдельное включение бычьих и медвежьих сигналов;
- pause/delete и изменение таймфреймов;
- exchange-aware фильтры цены и размера зоны;
- отдельный FAQ по FVG-инструментам;
- один общий набор `15m` на уникальный `exchange + symbol` переиспользуется для всех закрывшихся целевых таймфреймов;
- пустой market-data source считается operational failure, а не молчаливым отсутствием FVG.

Старые FVG settings schema v2 автоматически мигрируют в schema v3: существующие символы получают биржу Bitunix и таймфрейм `15m`, направления и фильтры сохраняются. После версии, где таймфреймы могли быть принудительно нормализованы в `15m`, рекомендуется один раз проверить сохранённые `1h/4h/1d` для существующих инструментов.

Верхний публичный лимит — 10 инструментов. Старый env override не может повысить его. Legacy-настройки, где уже сохранено больше 10 инструментов, не обрезаются: пользователь может удалять их, но не может добавлять новые до снижения количества ниже лимита. Глобальный `MAX_ACTIVE_SYMBOLS` считается по уникальным `exchange + symbol`, а не по числу выбранных таймфреймов.

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

### Telegram Mini App

Официальный `v1.3.5` содержит `telegram-mini-app/` и `mini_app_backend/`.

- frontend: React 19 + TypeScript + Vite;
- production frontend по умолчанию обращается к same-origin `/api/...`;
- mock включается только явно через `VITE_MOCK_MODE=true`, production build использует `VITE_MOCK_MODE=false`;
- backend использует тот же Bot API token и проверяет raw `Telegram.WebApp.initData` через HMAC-SHA-256;
- backend запускается внутри bot process только при `MINI_APP_BACKEND_ENABLED=true`;
- default listener — `127.0.0.1:18080`;
- origin allowlist задаётся через `MINI_APP_ALLOWED_ORIGINS`;
- FVG-модель Mini App соответствует schema v3: `exchange + symbol + timeframes`, включая `15m/1h/4h/1d` и шесть бирж;
- одинаковый symbol на разных биржах хранится независимо;
- pre-FVG/T−3 не экспонируется и не может быть повторно включён legacy payload;
- funding, RU/EN, compact/detailed и административная диагностика используют существующие stores;
- admin access/allowlist writes требуют одноразового challenge;
- backup/restart остаются fail-closed без production callbacks;
- Mini App не удаляет и не заменяет существующий Telegram UI.

Для production Mini App зарезервирован `https://tbbot.mstrategy.com.ru`, но runtime-код не привязан к домену жёстко. Публичный HTTPS reverse proxy, регистрация URL в BotFather/menu button и включение backend выполняются отдельным deployment-этапом. Релиз не изменяет Amnezia/Xray и внешний port `443`.

Подробнее: [`telegram-mini-app/README.md`](telegram-mini-app/README.md) и [`telegram-mini-app/API_CONTRACT.md`](telegram-mini-app/API_CONTRACT.md).

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
- macOS-safe backup без AppleDouble `._*` и `.DS_Store`;
- persistent leases и watchdog фоновых задач;
- bounded graceful shutdown;
- archive-before-delete для terminal FVG history;
- read-only archive audit CLI;
- persistent restart circuit breaker;
- атомарная VDS-установка и автоматический rollback;
- Bot API-only deployment без Telegram App credentials;
- candidate unit tests в `env -i` без production secrets и feature flags;
- полный candidate test log в `/var/log/fvg-alert-bot`;
- обязательный CI на GitHub-hosted Ubuntu, не на production VDS;
- immutable release tag/assets: существующий tag нельзя перемещать или перепубликовывать содержимым другого commit.

Рискованные operational-функции выключены по умолчанию и включаются поэтапно через `.env`.

Подробности:

- [`docs/RELEASE_1.3.5.md`](docs/RELEASE_1.3.5.md);
- [`docs/RELEASE_1.3.4.md`](docs/RELEASE_1.3.4.md);
- [`docs/RELEASE_1.3.3.md`](docs/RELEASE_1.3.3.md);
- [`docs/RELEASE_1.3.2.md`](docs/RELEASE_1.3.2.md);
- [`docs/RELEASE_1.3.1.md`](docs/RELEASE_1.3.1.md);
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
test "$(cat VERSION)" = "1.3.5"
FVG_INSTALL_MIN_FREE_MB=1024 bash scripts/install_vds.sh
```

Установщик собирает staging-релиз и запускает unit suite в чистом окружении до остановки работающего процесса. Production `.env` не копируется в staging. Затем создаётся backup, выполняется атомарное переключение, а при ошибке запуска автоматически возвращается предыдущая версия.

## Обновление существующего VDS до 1.3.5

Production обновляется только после публикации проверенного тега `v1.3.5` и точного SHA из deployment issue. Релизный архив называется `fvg-alert-bot-1.3.5.tar.gz`.

```bash
cd /root/TB
git status --short
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.5 \
  EXPECTED_VERSION=1.3.5 \
  EXPECTED_COMMIT=ПРОВЕРЕННЫЙ_SHA \
  bash scripts/update_vds_bot_api_only.sh
```

Сохраняются `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot`, пользовательские настройки и SQLite. Wrapper блокирует Telegram App/user-session credentials, не печатая токен. Сам release workflow production deployment не выполняет.

## Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
systemctl show fvg-alert-bot -p NRestarts -p ExecMainStatus -p MemoryCurrent -p MemoryMax
journalctl -u fvg-alert-bot -n 150 --no-pager

sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
```

Ожидается версия `1.3.5`, точный audited SHA, `active`, `enabled`, стабильный `NRestarts` и `ok` для обеих SQLite-баз.

Telegram smoke:

- `/start`, `/menu`, `/funding`, `/admin`, `/donate`;
- проверить список сохранённых FVG-инструментов и нужные `15m/1h/4h/1d`;
- добавить non-BTC инструмент минимум на `15m` и убедиться, что он присутствует в настройках после повторного открытия;
- проверить instrument на другой бирже, а не только BTC/Bitunix;
- убедиться, что в UI нет pre-FVG;
- RU/EN и compact/detailed;
- `⚙️ Операции`: restart guard и FVG archive;
- убедиться, что Telegram UI работает независимо от Mini App;
- убедиться, что Mini App backend остаётся выключен, если `MINI_APP_BACKEND_ENABLED` явно не включён.

После первой 15-минутной контрольной точки проверить journal: для активных рынков не должно быть `No closed 15m FVG candles returned`. Если такая ошибка есть, она должна быть видна как operational failure, а не скрываться как «FVG нет».

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

MINI_APP_BACKEND_ENABLED=false
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru
```

Эти Mini App значения — безопасный deployment example. Release publication не записывает их в production env и не включает backend автоматически.

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
| Candidate test logs | `/var/log/fvg-alert-bot` |
| Резервные копии | `/var/backups/fvg-alert-bot` |
| systemd units | `/etc/systemd/system/fvg-alert-bot*` |

## Backup и rollback

```bash
systemctl list-timers fvg-alert-bot-backup.timer
systemctl start fvg-alert-bot-backup.service
journalctl -u fvg-alert-bot-backup.service -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Установщик хранит предыдущий релиз в `/opt/fvg-alert-bot.previous`. Verified backup включает manifest, SHA-256 и согласованные SQLite snapshots. Live WAL/SHM не копируются как обычные файлы. При упаковке на macOS `COPYFILE_DISABLE=1` запрещает создание AppleDouble sidecars, а `._*` и `.DS_Store` исключаются из snapshot.

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

Для Mini App CI дополнительно выполняет Node.js 22 `npm ci`, TypeScript typecheck, production build с `VITE_MOCK_MODE=false`, проверяет same-origin API, отсутствие credential identifiers/source maps и публикует frontend artifact, привязанный к точному commit SHA.

Общий CI включает dependency audit, compilation, release metadata consistency, candidate environment isolation, exchange-adapter contracts, FVG multi-timeframe aggregation, non-BTC end-to-end delivery, Mini App auth/service/runtime/web/admin regressions, backup portability regression, полный unit suite, bounded `500 × 10` soak и production systemd verification.

Release workflow для версии 1.3.5 создаёт `v1.3.5` только из merge commit `main`, сохраняет immutable tag/assets, создаёт `fvg-alert-bot-1.3.5.tar.gz` и SHA-256 checksum, а повторный запуск при уже корректном tag/release является идемпотентным.
