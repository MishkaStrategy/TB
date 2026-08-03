# FVG Alert Bot 1.3.1

`1.3.1` — installer hotfix для audited feature-релиза `1.3.0`.

## Исправлено

- candidate unit tests запускаются в чистом allowlisted environment через `env -i`;
- production `/etc/fvg-alert-bot.env` больше не копируется в staging до тестов;
- реальные Telegram credentials и operational feature flags не попадают в test process;
- полный вывод candidate suite сохраняется в `/var/log/fvg-alert-bot/candidate-tests-1.3.1-<UTC>.log`;
- installer сохраняет исходный exit code тестового процесса и останавливается до `systemctl stop` и atomic switch;
- устаревший override `MAX_SYMBOLS_PER_USER` больше не может повысить FVG-лимит выше 10;
- legacy settings с более чем 10 инструментами не обрезаются: пользователь может удалять их, но не может добавлять новые до снижения количества ниже лимита.

## Причина hotfix

При первой попытке установки `v1.3.0` production env содержал `MAX_SYMBOLS_PER_USER=20`. Старый override был скопирован в staging и изменил поведение unit tests кандидата. Focused test с production env падал, а тот же тест и полный suite в clean environment проходили.

Установка остановилась до atomic switch. Production осталась на `1.2.0`; rollback не потребовался, SQLite-базы не изменялись.

## Безопасность и совместимость

- runtime-state `/var/lib/fvg-alert-bot` сохраняется;
- `/etc/fvg-alert-bot.env` не переписывается hotfix-логикой;
- Telegram работает только через Bot API token;
- Telegram Mini App, `API_ID/API_HASH`, Telethon, Pyrogram и пользовательские Telegram-сессии не входят в релиз;
- operational feature flags остаются выключенными до отдельного staged rollout.

## Проверка релиза

Release audit проверяет:

- shell syntax installer/update/helper;
- изоляцию candidate process от загрязнённого parent environment;
- отсутствие утечки Telegram token и Telegram ID в test log;
- сохранение child exit code и persistent log;
- effective FVG limit 10 при stale override 20;
- сохранение legacy over-limit settings;
- полный unit suite;
- bounded soak `500 × 10`;
- production systemd unit render;
- отсутствие Telegram Mini App.

## Production deployment

Production deployment не является частью подготовки релиза. После публикации `v1.3.1` обновление должно быть закреплено на точном tag commit и выполняться через `scripts/update_vds_bot_api_only.sh` с preflight, backup и post-deploy smoke-test.
