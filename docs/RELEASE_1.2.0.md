# FVG Alert Bot 1.2.0

Дата подготовки: 2026-07-28.

`1.2.0` собран не из устаревшей release-ветки: сначала в новую интеграционную ветку был влит актуальный `main`, включая PR #43 с 15-минутным funding scheduler и ограниченной историей снимков. Затем поверх объединённого кода проведён повторный CI/VDS-аудит.

## Что входит

- FVG Bitunix: предварительные T−3 и подтверждённые 15m-события;
- process watchdog, WebSocket stale-watchdog и REST recovery;
- мультибиржевой фандинг Bitunix, Binance, Bybit, BingX, Bitget и Gate;
- общий funding-снимок на границах `:00`, `:15`, `:30` и `:45` UTC;
- персональные funding-уведомления от 15 минут до 48 часов с шагом 15 минут;
- автоматическая миграция старых `interval_hours` в `interval_minutes` без изменения фактической частоты;
- только три последних сжатых funding-снимка в `funding_snapshot_history` с атомарным удалением старого снимка и WAL checkpoint;
- постоянное нижнее Telegram-меню;
- русский и английский интерфейс на уровне пользователя;
- компактный и подробный формат FVG/funding-уведомлений;
- расширенная админ-панель: доступ, allowlist, WebSocket, outbox, SQLite, ресурсы, backup, версия и подтверждаемый restart;
- донат-раздел для USDT, ETH и BNB с EVM-адресом;
- обязательные capability labels для self-hosted GitHub Actions runners.

## Исправления повторного аудита

### Интеграция с актуальным main

PR #42 был основан на `main` до PR #43. Релиз пересобран в новой ветке после явного merge текущего `main`, поэтому 15-минутный scheduler, миграция интервалов и bounded snapshot history не потеряны.

### RU/EN для нового funding UI

Новые тексты PR #43 изначально не входили в словарь локализации PR #42. Добавлены переводы и тесты для:

- ближайшей четверти часа;
- ввода интервала 15–2880 минут;
- шага 15 минут;
- сообщений о трёх последних снимках;
- ошибок валидации и кнопок длительности.

### Notification hot path

`user_preferences.json` загружается один раз на процесс и разделяется всеми экземплярами хранилища. Запись выполняется только при фактическом изменении языка или формата. Регрессионный тест запрещает чтение preference-файла на каждую Telegram-доставку.

### Release workflow

Публикация больше не зависит от недоступного self-hosted runner:

- job публикации выполняется на `ubuntu-latest`;
- создаётся тег и GitHub Release из `VERSION`;
- формируется `fvg-alert-bot-1.2.0.tar.gz` через `git archive`;
- рядом публикуется SHA-256 checksum;
- повторный запуск workflow идемпотентен.

### VDS update pinning

`scripts/update_vds.sh` поддерживает `TARGET_REF` для remote branch или тега и опциональный `EXPECTED_COMMIT`. Production можно обновлять по проверенному `v1.2.0`, а не по движущемуся `main`.

### Backup и SQLite

- `.manual_backups` не попадает внутрь последующего backup-архива;
- live WAL/SHM не копируются обычным `rsync`;
- обе SQLite-базы архивируются через SQLite Backup API;
- после установки выполняется `PRAGMA quick_check` обеих баз;
- исправлен путь проверки funding-базы: `/var/lib/fvg-alert-bot/funding_alerts.sqlite3`.

## CI-аудит

Добавлен независимый GitHub-hosted workflow `Release audit`, который проверяет:

1. shell syntax установочных и backup-скриптов;
2. `VERSION=1.2.0` и release metadata;
3. установку закреплённых зависимостей и `pip-audit`;
4. компиляцию Python-кода;
5. полный unit suite;
6. bounded notification soak `500 × 10` с лимитом 180 секунд и 256 МБ;
7. рендер production systemd units и `systemd-analyze verify`;
8. sandboxing, `MemoryMax=512M`, `ReadWritePaths` и persistent backup timer.

Отдельный GitHub-hosted funding job проверяет миграцию интервалов, четыре плановых запуска, сохранение только трёх снимков и WAL checkpoint. Self-hosted jobs остаются дополнительными проверками, но больше не являются единственным способом подтвердить релиз.

## Сохраняемые данные

Обновление не удаляет:

- `/etc/fvg-alert-bot.env`;
- `/var/lib/fvg-alert-bot/fvg_alert_settings.json`;
- `/var/lib/fvg-alert-bot/funding_alerts.sqlite3`;
- `/var/lib/fvg-alert-bot/fvg_event_store.sqlite3`;
- `/var/lib/fvg-alert-bot/runtime_settings.json`;
- `/var/lib/fvg-alert-bot/access_control.json`;
- `/var/lib/fvg-alert-bot/user_activity.json`;
- `/var/lib/fvg-alert-bot/user_preferences.json`.

Для существующих пользователей язык и формат по умолчанию будут `ru` и `detailed`, пока пользователь не изменит их в Telegram. Старые часовые funding-настройки мигрируют в минуты автоматически.

## Требования перед обновлением

- чистый Git checkout `/root/TB`;
- активная существующая установка `/opt/fvg-alert-bot`;
- runtime-state `/var/lib/fvg-alert-bot`;
- не менее 1 ГБ свободного места на файловой системе `/opt`;
- не менее 5000 свободных inode;
- доступ к Telegram и публичным API бирж.

## Обновление VDS

После публикации тега:

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main
TARGET_REF=v1.2.0 EXPECTED_VERSION=1.2.0 bash scripts/update_vds.sh
```

Для максимальной фиксации проверенного релиза:

```bash
TARGET_REF=v1.2.0 \
EXPECTED_VERSION=1.2.0 \
EXPECTED_COMMIT=ПРОВЕРЕННЫЙ_SHA \
  bash scripts/update_vds.sh
```

Wrapper получает указанный ref, проверяет версию и SHA, создаёт согласованный pre-update backup, запускает атомарную установку, проверяет systemd, симлинк runtime-state и обе SQLite-базы.

## Проверка после обновления

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl status fvg-alert-bot --no-pager --full
journalctl -u fvg-alert-bot -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Ожидаемые первые результаты:

```text
1.2.0
active
enabled
```

SQLite:

```bash
sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 \
  'SELECT captured_at, exchange_count, rate_count, compressed_bytes FROM funding_snapshot_history ORDER BY captured_at DESC;'
```

Обе первые команды должны вернуть `ok`, а последняя — не более трёх строк.

В Telegram проверить:

1. `/start` и постоянное нижнее меню;
2. переключение RU/EN и compact/detailed;
3. `/funding`, все шесть бирж и интервалы `15`, `45 мин`, `1ч`, `1,5ч`;
4. ближайшее время проверки на четверти часа;
5. `/admin`, backup, SQLite и просмотр версии;
6. `/donate` и корректность EVM-адреса.

## Rollback

При неуспешном запуске `install_vds.sh` автоматически возвращает `/opt/fvg-alert-bot.previous`. Runtime-state хранится отдельно и не откатывается вместе с кодом. Перед переключением `update_vds.sh` создаёт отдельный архив в `/var/backups/fvg-alert-bot`.
