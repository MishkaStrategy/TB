# FVG Alert Bot 1.1.0

Дата подготовки: 27 июля 2026 года.

## Основное изменение

Версия `1.1.0` добавляет персональные уведомления о ставках фандинга Bitunix.
Пользователь может настроить интервал от 1 до 48 часов, минимальный абсолютный
процент и направление: положительное, отрицательное или оба.

Общий снимок ставок загружается один раз в час в `HH:50 UTC`. Для каждого
пользователя применяется собственное расписание. Повторное сообщение не
отправляется, пока инструмент остаётся за порогом; новое уведомление появляется
после возврата в диапазон и следующего пересечения.

## Хранение

Добавлена SQLite/WAL-база:

```text
data/funding_alerts.sqlite3
```

В ней хранится только конфигурация пользователей и текущее состояние пересечений.
Устаревшие пересечения удаляются через 7 дней, выключенные неактивные настройки —
через 180 дней. Раз в сутки выполняются checkpoint и incremental vacuum.

## Подготовка VDS

- backup-скрипт теперь делает согласованные SQLite-снимки обеих баз через backup API;
- live-файлы `funding_alerts.sqlite3-wal` и `funding_alerts.sqlite3-shm` не копируются в архив;
- добавлен `scripts/update_vds.sh` для preflight, предварительного backup,
  fast-forward обновления, атомарной установки и post-deploy проверки;
- после установки проверяются systemd, версия, runtime-ссылка и `PRAGMA quick_check`;
- установленный Git commit записывается в `/opt/fvg-alert-bot/BUILD_COMMIT`.

## Обновление существующего сервера

```bash
ssh root@IP_АДРЕС_СЕРВЕРА
cd /root/TB
git fetch origin --prune
git checkout main
git pull --ff-only origin main
EXPECTED_VERSION=1.1.0 bash scripts/update_vds.sh
```

Скрипт сам создаёт backup до остановки бота и затем запускает существующий
атомарный установщик. Runtime-state в `/var/lib/fvg-alert-bot` и секреты в
`/etc/fvg-alert-bot.env` сохраняются.

## Проверка

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
journalctl -u fvg-alert-bot -n 100 --no-pager
ls -lah /var/backups/fvg-alert-bot
```

Ожидаемая версия:

```text
1.1.0
```

В Telegram откройте `/funding` → `🔔 Уведомления`, сохраните настройки и проверьте,
что следующая контрольная точка назначена на `HH:50`.

## Rollback

Установщик сохраняет предыдущий релиз в `/opt/fvg-alert-bot.previous`. Если новый
процесс не запускается, rollback выполняется автоматически. Ручная процедура
описана в [`VDS_DEPLOYMENT.md`](VDS_DEPLOYMENT.md).
