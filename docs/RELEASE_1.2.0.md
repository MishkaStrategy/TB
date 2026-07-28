# FVG Alert Bot 1.2.0

Дата подготовки: 2026-07-28.

`1.2.0` объединяет актуальный production-код `1.1.0` и последние подтверждённые изменения из параллельных рабочих чатов. Релиз предназначен для обновления существующей VDS-установки через `scripts/update_vds.sh`.

## Что входит

- FVG Bitunix: предварительные T−3 и подтверждённые 15m-события;
- process watchdog, WebSocket stale-watchdog и REST recovery;
- мультибиржевой фандинг Bitunix, Binance, Bybit, Bitget, Gate и BingX;
- персональные funding-уведомления с частотой 1–48 часов, порогом, направлением и выбором бирж;
- постоянное нижнее Telegram-меню;
- русский и английский интерфейс на уровне пользователя;
- компактный и подробный формат FVG/funding-уведомлений;
- расширенная админ-панель: доступ, allowlist, WebSocket, outbox, SQLite, ресурсы, backup, версия и подтверждаемый restart;
- донат-раздел для USDT, ETH и BNB с EVM-адресом;
- обязательные capability labels для self-hosted GitHub Actions runners.

## Что было исправлено аудитом

Первый CI новой локализации обнаружил производительную регрессию: `user_preferences.json` читался с диска перед каждой отправкой Telegram. При 5 000 доставок bounded soak занимал около 990 секунд.

В `1.2.0` предпочтения загружаются один раз на процесс и разделяются всеми экземплярами хранилища. Запись на диск выполняется только при фактическом изменении языка или формата. Регрессионный тест запрещает чтение preference-файла на notification hot path.

Также добавлены проверки:

- не-администратор не может выполнить административный callback;
- restart выполняется только после отдельного подтверждения администратора;
- `.manual_backups` не попадает внутрь последующего backup-архива;
- live SQLite/WAL остаётся защищён SQLite Backup API и `PRAGMA quick_check`.

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

Для существующих пользователей язык и формат по умолчанию будут `ru` и `detailed`, пока пользователь не изменит их в Telegram.

## Требования перед обновлением

- чистый Git checkout `/root/TB`;
- активная существующая установка `/opt/fvg-alert-bot`;
- runtime-state `/var/lib/fvg-alert-bot`;
- не менее 1 ГБ свободного места на файловой системе `/opt`;
- доступ к Telegram и публичным API бирж.

## Обновление VDS

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main
EXPECTED_VERSION=1.2.0 bash scripts/update_vds.sh
```

Wrapper выполняет preflight, согласованный pre-update backup, fast-forward обновление, атомарную установку, systemd-проверки, проверку версии и `PRAGMA quick_check` обеих SQLite-баз.

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

В Telegram проверить:

1. `/start` и постоянное нижнее меню;
2. переключение RU/EN и compact/detailed в настройках;
3. `/funding`, все шесть бирж и funding alerts;
4. `/admin`, backup и просмотр версии;
5. `/donate` и корректность EVM-адреса.

## Rollback

При неуспешном запуске `install_vds.sh` автоматически возвращает `/opt/fvg-alert-bot.previous`. Runtime-state хранится отдельно и не откатывается вместе с кодом. Перед переключением `update_vds.sh` создаёт отдельный архив в `/var/backups/fvg-alert-bot`.
