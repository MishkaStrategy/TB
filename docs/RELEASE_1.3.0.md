# Release 1.3.0

Дата подготовки: 2026-07-30.

Версия `1.3.0` собрана поверх актуального `main` и объединяет новые FVG-функции с полным зависимым operational-стеком. Telegram Mini App и новый графический интерфейс из PR #53 в этот релиз не входят.

## Состав релиза

### Новые FVG-функции — PR #54

- пошаговая настройка `биржа → пара → таймфреймы → подтверждение`;
- до 10 уникальных комбинаций `биржа + торговая пара` на Telegram ID;
- подтверждённые FVG для `15m`, `1h`, `4h`, `1d`;
- расчёт только после закрытия свечи C;
- BTC-only пред-FVG только на `15m`;
- публичные candle adapters для Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- изменение таймфреймов, пауза и удаление инструмента;
- отдельный FAQ;
- exchange-aware фильтры и FVG-уведомления.

### Operational stack

Стек включён в порядке зависимостей:

1. PR #51 — статусы Telegram-доставки и suppression заблокированных чатов;
2. PR #52 — Outbox V2 с явной state machine и bounded retries;
3. PR #56 — read-only SQLite observability;
4. PR #57 — проверяемые backup, manifest, SHA-256 и история запусков;
5. PR #58 — persistent leases и watchdog фоновых задач;
6. PR #59 — lifecycle и bounded graceful shutdown;
7. PR #60 — read-only экран `⚙️ Операции`;
8. PR #61 — archive-before-delete для terminal FVG history;
9. PR #62 — read-only CLI audit архива;
10. PR #63 — graceful stale-process restart;
11. PR #64 — persistent restart circuit breaker;
12. PR #65 — read-only состояние circuit breaker в `⚙️ Операции`;
13. PR #66 — read-only состояние и статистика FVG archive в `⚙️ Операции`.

PR #65 включён до PR #66, как требует stacked dependency chain.

## Экран «⚙️ Операции»

После релиза экран показывает без управляющих действий:

- lifecycle процесса;
- recurring background jobs и leases;
- SQLite observability snapshots;
- состояние restart circuit breaker, cooldown, quota и последние решения;
- наличие и размеры FVG archive main/WAL/SHM;
- schema metadata архива;
- последнюю и недавние archive runs;
- количество событий, доставок и source deletes последнего batch;
- runtime archive counters, failures, backlog signal и последнюю ошибку.

Экран открывает SQLite через `mode=ro` и `PRAGMA query_only=ON`. Он не запускает migration, repair, quick_check, archive COUNT, export, restore, compaction, circuit reset или restart.

## Миграции и совместимость

- FVG settings schema обновляется до версии 3;
- schema v2 автоматически и идемпотентно преобразуется в exchange-aware instruments;
- старые символы получают биржу Bitunix и таймфрейм `15m`;
- направления, пред-FVG и фильтры сохраняются;
- SQLite-изменения operational-стека аддитивны;
- optional tables создаются только соответствующими runtime-компонентами, а read-only UI их не создаёт;
- предыдущая версия игнорирует новые optional tables;
- `/etc/fvg-alert-bot.env` и `/var/lib/fvg-alert-bot` сохраняются.

## Rollout flags

Рискованные изменения остаются выключенными по умолчанию и включаются поэтапно:

```dotenv
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

Новые FVG-инструменты и read-only административные экраны не требуют включения Telegram Mini App.

## Что исключено

- PR #53;
- каталог `telegram-mini-app`;
- Telegram WebApp backend/frontend;
- BotFather Mini App URL;
- вход через Telegram App, `API_ID`, `API_HASH`, Telethon или пользовательскую сессию;
- automatic restore и automatic remediation;
- управляющие archive/circuit-breaker действия.

## Обязательный CI перед выпуском

Финальный `Release audit` выполняет на едином integration SHA:

- shell validation и release metadata;
- `pip-audit`;
- compileall;
- контракт `1.3.0` и запрет Mini App;
- FVG schema v2 → v3 migration tests;
- `15m/1h/4h/1d` и multi-exchange FVG tests;
- Outbox V2 + limited recovery integration test;
- restart circuit-breaker status UI tests;
- FVG archive status UI tests;
- restart guard и archive SQLite tests;
- полный unit suite;
- bounded 500 × 10 notification soak;
- production systemd verification.

Релиз нельзя объединять в `main`, пока GitHub-hosted `Release audit` не завершится успешно.

## VDS update — Bot API only

После публикации тега и фиксации проверенного SHA:

```bash
cd /root/TB
git status --short
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.0 \
  EXPECTED_VERSION=1.3.0 \
  EXPECTED_COMMIT=<audited-release-sha> \
  bash scripts/update_vds_bot_api_only.sh
```

Updater проверяет Bot API-only credentials, создаёт pre-update backup, собирает кандидата, запускает unit suite до остановки процесса, выполняет atomic switch, rollback, systemd checks, VERSION/BUILD_COMMIT verification и `PRAGMA quick_check` обеих runtime SQLite-баз.

## Post-deploy

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
journalctl -u fvg-alert-bot -n 150 --no-pager
sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
```

Telegram smoke:

- `/start` и нижнее меню;
- FVG instrument wizard;
- добавление Bitunix/Binance пары;
- выбор `15m`, `1h`, `4h`, `1d`;
- сохранение и повторное открытие настроек;
- `⚙️ Операции`: restart guard и FVG archive sections;
- RU/EN и compact/detailed;
- `/funding`, `/admin`, `/donate`.

## Rollback

Установщик автоматически возвращает `/opt/fvg-alert-bot.previous`, если новая служба не запускается. Feature-level rollback выполняется выключением соответствующих flags и перезапуском. Аддитивные SQLite-таблицы не требуют downgrade для возврата к `1.2.0`.
