# Changelog

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

### Эксплуатация

- для обновления VDS рекомендуется иметь не менее 1 ГБ свободного места на файловой системе `/opt`;
- runtime-state в `/var/lib/fvg-alert-bot` и секреты в `/etc/fvg-alert-bot.env` сохраняются между обновлениями;
- стабильную production-установку следует обновлять только при критической необходимости.

История release candidates `1.0.0-rc1`–`1.0.0-rc10` сохранена в Git history и соответствующих тегах.
