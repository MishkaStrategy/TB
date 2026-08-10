# Changelog

## 1.3.7 — 2026-08-11

Patch-релиз по результатам аудита актуального `main` после `1.3.6`.

### Исправлено и оптимизировано

- `FundingExchangeStore` гарантированно закрывает context-managed SQLite connections, а `journal_mode=WAL` больше не переустанавливается на каждом чтении;
- смена funding exchange selection и сброс crossing-state выполняются одной транзакцией;
- Telegram update hot path переиспользует один `UserActivityRegistry` вместо создания объекта на каждый update;
- sync settings/admin storage Mini App вынесено из `aiohttp` event loop через worker threads;
- `aiohttp.Application` использует typed `web.AppKey`, устраняя `NotAppKeyWarning`;
- повреждённый saved instrument или отдельная некорректная ticker row больше не обрушает весь market overview;
- GitHub Actions переведены на точный allowlist capability selectors, release/systemd проверки закреплены за `[self-hosted, Linux]`;
- release publication проверяет наличие `sha256sum`, `tar` и `gh` до создания immutable assets.

### Проверки и совместимость

- добавлены регрессии SQLite connection lifecycle, atomic crossing reset, off-loop Mini App storage, shared activity registry и malformed market rows;
- runner selector policy проверяется отдельным workflow и обычным unit suite;
- Telegram/FVG/funding/Mini App API контракты не меняются;
- production env, SQLite/runtime-state и существующие immutable tags не изменяются автоматически;
- релиз публикуется отдельным immutable tag `v1.3.7`.

## 1.3.6 — 2026-08-11

### Telegram Mini App

- добавлен новый тёмный trading dashboard на `TradingApp` с вкладками Главная, FVG, Funding, Уведомления и Настройки;
- добавлены отдельный защищённый Admin screen и единая SVG-система интерфейсных иконок;
- добавлен аутентифицированный `GET /api/mini-app/market-overview` с exchange-aware изменением цены за 24 часа;
- недоступные market data отображаются как `—`, а сбой одной биржи не ломает весь overview;
- production frontend использует real same-origin API, mock mode остаётся только для изолированных visual staging builds.

### Надёжность и безопасность

- сохранены HMAC-проверка Telegram `initData`, admin challenge и существующие settings/API contracts;
- production env, SQLite, пользовательские настройки, operational flags, BotFather, Xray и сетевые порты автоматически не меняются;
- релиз публикуется отдельным immutable tag `v1.3.6`; `v1.3.5` и более ранние теги не перемещаются.

## 1.3.5 — 2026-08-10

Immutable patch-релиз, синхронизирующий `main`, `VERSION` и новый официальный tag после merge Telegram Mini App.

### Добавлено в официальный релиз

- `mini_app_backend/**` и `telegram-mini-app/**` впервые входят в официальный immutable release archive;
- lifecycle Mini App backend уже подключён к `bot.py`, но backend остаётся выключен по умолчанию;
- production frontend использует same-origin `/api/`, а production build выполняется с `VITE_MOCK_MODE=false`;
- production Mini App domain документирован как `https://tbbot.mstrategy.com.ru` без жёсткой привязки runtime-кода к домену.

### Исправлено

- устранена рассинхронизация после `v1.3.4`, когда Mini App был объединён в `main`, но `VERSION` остался `1.3.4`;
- release workflow создаёт новый tag только из merge commit `main`, никогда не перемещает существующий tag и fail-closed при несовпадении commit;
- повторный запуск для уже корректного tag/release идемпотентен и загружает только отсутствующие immutable assets;
- release archive теперь отдельно проверяется на наличие Mini App backend/frontend и отсутствие `.env`, SQLite, `node_modules`, frontend `dist`, Python caches и AppleDouble metadata;
- release audit проверяет неизменность `v1.3.4`, dependency/security contract, Mini App production build, backup checksum binding и полный `500 × 10` soak.

### Production safety

- Telegram UI остаётся основным и резервным интерфейсом;
- `MINI_APP_BACKEND_ENABLED=false` по умолчанию;
- default backend listener — `127.0.0.1:18080`;
- production env, SQLite и пользовательские runtime-данные автоматически не изменяются;
- Mini App использует только BotFather `TELEGRAM_TOKEN`; `API_ID/API_HASH`, Telethon, Pyrogram и user sessions не используются;
- operational feature flags автоматически не включаются;
- deployment релиза и отдельное включение Mini App выполняются контролируемыми этапами после публикации;
- `v1.3.4` и более ранние теги остаются immutable.

## 1.3.4 — 2026-08-09

Patch-релиз мультибиржевого FVG runtime после повторного production-аудита.

### Исправлено

- восстановлены подтверждённые FVG на `15m`, `1h`, `4h`, `1d` при единственном биржевом источнике закрытых `15m` свечей;
- `1h/4h/1d` агрегируются локально из `15m` по UTC-границам, без прямых запросов старших свечей;
- пред-FVG и минутные `1m` свечи остаются удалёнными;
- сохранённые `1h/4h/1d` больше не перезаписываются в `15m`;
- исправлен Gate Futures parser для объектного payload `t/o/h/l/c`;
- `MAX_ACTIVE_SYMBOLS` теперь ограничивает уникальные `exchange + symbol`, а не отдельные timeframe rows;
- один источник `15m` переиспользуется для всех due-таймфреймов одного рынка;
- пустой candle source становится observable operational failure вместо молчаливого «FVG нет»;
- сбой одного рынка не останавливает остальные;
- возвращён выбор `15m / 1h / 4h / 1d` в Telegram UI без возврата пред-FVG.

### Проверено

- payload contracts Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- non-BTC end-to-end путь `15m source → FVG event → recipient`;
- локальная агрегация `1h/4h/1d` и неполные source buckets;
- dependency audit, compilation и полный unit suite;
- bounded pipeline smoke и `500 × 10` notification soak;
- VDS candidate isolation и production systemd verification.

### Релизная безопасность

- `v1.3.4` публикуется отдельным immutable patch-тегом;
- release workflow больше не должен перезаписывать assets уже существующего тега новым содержимым `main`;
- production deployment выполняется отдельно по точному audited SHA.

## 1.3.3 — 2026-07-30

Кроссплатформенный hotfix verified backup для macOS.

### Исправлено

- macOS BSD tar больше не добавляет AppleDouble `._*` members после построения manifest;
- backup запускает tar с `COPYFILE_DISABLE=1`;
- существующие `._*` и `.DS_Store` исключаются из runtime snapshot;
- manifest verifier остаётся строгим для обычных неподтверждённых файлов;
- добавлен behavior-level regression test с контролируемым tar wrapper.

### Проверено

- полный unit suite;
- candidate environment isolation;
- dependency audit;
- bounded `500 × 10` soak;
- production systemd render/verify;
- Telegram Mini App по-прежнему исключён.

## 1.3.2 — 2026-07-30

Immutable metadata follow-up к installer hotfix `1.3.1`. Runtime-fix не изменён.

### Исправлено

- README, install/update examples и release links синхронизированы с `VERSION=1.3.2`;
- Bot API-only VDS инструкция указывает актуальный deployment tag/version;
- stable status больше не отображается как release candidate;
- обязательные CI jobs перенесены с production VDS на GitHub-hosted Ubuntu;
- добавлен regression test согласованности VERSION, README, updater, release audit и VDS документации.

### Гарантии

- теги `v1.3.0` и `v1.3.1` не переписываются;
- runtime-state и production env не изменяются release-процессом;
- Telegram Mini App PR #53 не входит;
- production deployment выполняется отдельно и только по точному SHA тега.

## 1.3.1 — 2026-07-30

Installer hotfix для релиза `1.3.0`. Первая production-попытка остановилась до atomic switch, поэтому VDS осталась на `1.2.0` и rollback не потребовался.

### Исправлено

- candidate unit tests теперь запускаются через `env -i` и не наследуют production `/etc/fvg-alert-bot.env`;
- реальные Telegram credentials и operational feature flags не попадают в staging test process;
- полный candidate test log сохраняется в `/var/log/fvg-alert-bot`;
- installer сохраняет исходный exit code test process и останавливается до выключения production-службы;
- `MAX_SYMBOLS_PER_USER` ограничен сверху значением 10, даже если старый production env содержит большее значение;
- legacy-настройки с количеством инструментов выше лимита сохраняются без обрезки;
- добавлены regression tests изоляции candidate environment, защиты секретов и legacy over-limit settings.

### Совместимость

- функции FVG и operational stack из `1.3.0` не изменены;
- `/etc/fvg-alert-bot.env` и `/var/lib/fvg-alert-bot` не переписываются автоматически;
- Telegram Mini App, `API_ID/API_HASH` и пользовательские Telegram-сессии не входят в релиз.

## 1.3.0 — 2026-07-30

Единый feature-релиз новых FVG-функций и полного operational-стека поверх актуального `main`. Telegram Mini App из PR #53 исключён.

### FVG

- exchange-aware FVG-инструменты для Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- до 10 комбинаций `биржа + торговая пара` на Telegram ID;
- подтверждённые FVG на `15m`, `1h`, `4h`, `1d` после закрытия свечи C;
- BTC-only пред-FVG T−3 на `15m`;
- изменение таймфреймов, pause/delete, FAQ и exchange-aware фильтры;
- автоматическая миграция FVG settings schema v2 → v3 с сохранением фильтров.

### Operations и администрирование

- Telegram delivery profiles и suppression недоступных чатов;
- Outbox V2 с state machine, bounded retry, expiration и dead-letter;
- SQLite observability;
- verified backup с manifest, SHA-256 и durable history;
- background task leases и watchdog;
- lifecycle и graceful shutdown/restart;
- archive-before-delete и read-only FVG archive audit;
- persistent restart circuit breaker;
- read-only состояние circuit breaker в `⚙️ Операции` из PR #65;
- read-only состояние и статистика FVG archive в `⚙️ Операции` из PR #66.

### Аудит интеграции

- PR #65 включён со всем зависимым stacked-стеком до PR #66;
- PR #66 включён отдельным следующим шагом;
- PR #54 вручную объединён с operational-стеком;
- исправлено наследование Outbox V2, чтобы сохранялась limited non-BTC recovery policy;
- полный GitHub-hosted CI проверяет migration, `4h`, оба новых admin sections, SQLite, soak и systemd;
- версия VDS updater обновлена до `1.3.0`;
- Telegram Mini App, `API_ID/API_HASH` и user sessions не входят в релиз.

## 1.2.0 — 2026-07-28

Объединены последние подтверждённые изменения из параллельных рабочих чатов поверх production-версии `1.1.0` и подготовлено безопасное обновление VDS.

### Добавлено

- постоянное нижнее Telegram-меню: FVG, фандинг, уведомления, статистика, настройки и донат;
- русский и английский интерфейс отдельно для каждого Telegram ID;
- компактный и подробный формат FVG- и funding-уведомлений;
- расширенная админ-панель: allowlist, WebSocket, outbox, SQLite, ресурсы, backup, версия и подтверждаемый restart;
- донат-раздел для USDT, ETH и BNB с EVM-адресом;
- поддержка BingX в дополнение к Bitunix, Binance, Bybit, Bitget и Gate;
- process watchdog для восстановления зависшего polling-процесса;
- политика capability labels для self-hosted GitHub Actions runners;
- release-документ `docs/RELEASE_1.2.0.md` и VDS target `1.2.0`.

### Исправлено аудитом

- `user_preferences.json` больше не читается и не парсится перед каждой отправкой Telegram;
- предпочтения загружаются один раз на процесс и записываются только при изменении;
- устранена регрессия bounded soak, при которой 5 000 доставок занимали около 990 секунд;
- ручные архивы `.manual_backups` исключены из последующих backup;
- добавлены тесты запрета административных действий для не-администратора и подтверждаемого restart;
- сохранены атомарное VDS-обновление, rollback и `PRAGMA quick_check` обеих SQLite-баз.

### Совместимость

- runtime-state `/var/lib/fvg-alert-bot` и `/etc/fvg-alert-bot.env` сохраняются;
- существующие FVG/funding-настройки не сбрасываются;
- для существующих пользователей язык и формат по умолчанию — `ru` и `detailed` до ручного изменения;
- целевая команда обновления: `EXPECTED_VERSION=1.2.0 bash scripts/update_vds.sh`.

## 1.1.0 — 2026-07-27

Добавлены персональные уведомления о ставках фандинга и подготовлено безопасное обновление существующей VDS-установки.

### Добавлено

- настройки частоты funding-уведомлений от 1 до 48 часов;
- пользовательский процентный порог;
- независимый выбор положительного и отрицательного фандинга;
- общий снимок ставок один раз в час в `HH:50 UTC`;
- подавление повторов до выхода инструмента из условия и нового пересечения;
- SQLite/WAL-хранилище `funding_alerts.sqlite3` с ограниченным retention;
- `scripts/update_vds.sh` для preflight, backup, fast-forward обновления, атомарной установки и post-deploy проверки;
- запись установленного Git SHA в `/opt/fvg-alert-bot/BUILD_COMMIT`.

### Исправлено

- funding-база больше не копируется в backup обычным `rsync` вместе с live WAL;
- обе SQLite-базы архивируются согласованно через SQLite backup API;
- WAL/SHM sidecar-файлы исключены из backup-архива;
- добавлен регрессионный тест восстановления обеих SQLite-баз из архива.

### Эксплуатация

- целевая версия VDS-обновления — `1.1.0`;
- runtime-state и секреты сохраняются между релизами;
- перед переключением создаётся отдельный pre-update backup;
- после установки выполняются systemd-проверки и `PRAGMA quick_check`.

## 1.0.0 — 2026-07-27

Первый стабильный релиз FVG Alert Bot. Версия утверждена после production-проверки основных сценариев и фиксирует функциональность `1.0.0-rc10` как завершённую.

### Статус

- проект переведён в режим feature freeze;
- новые функции и плановые изменения не принимаются;
- допустимы только критические production-исправления и security fixes;
- стабильная версия публикуется тегом `v1.0.0` и обычным GitHub Release.

### Основные функции

- подтверждённые и предварительные FVG-уведомления Bitunix;
- индивидуальные символы, направления, фильтры цены и размера зоны;
- WebSocket-поток с watchdog и REST recovery;
- постоянные SQLite/WAL event store, outbox и health-метрики;
- рейтинг ставок фандинга;
- приватный/публичный режим из Telegram-админ-панели;
- атомарное VDS-обновление, backup и rollback;
- event-quality backtest без искусственного P&L.