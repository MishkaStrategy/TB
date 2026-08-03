# FVG Alert Bot 1.3.2

`1.3.2` — финальная metadata-проверка и immutable follow-up к installer hotfix `1.3.1`.

## Runtime

Runtime-исправления идентичны проверенному hotfix `1.3.1`:

- candidate unit tests запускаются в чистом allowlisted environment через `env -i`;
- production `/etc/fvg-alert-bot.env` не копируется в staging до тестов;
- реальные Telegram credentials и operational flags не попадают в test process;
- полный candidate test log сохраняется в `/var/log/fvg-alert-bot`;
- installer сохраняет child exit code и останавливается до `systemctl stop`/atomic switch при test failure;
- effective `MAX_SYMBOLS_PER_USER` ограничен сверху значением 10;
- legacy over-limit settings сохраняются без автоматического удаления.

## Что дополнительно исправлено

- README показывает фактическую текущую версию и stable status;
- VDS Bot API-only инструкция указывает актуальный tag/version;
- release links, install/update examples и expected post-deploy version синхронизированы с `VERSION`;
- добавлен regression test согласованности release metadata, чтобы stale версия в документации снова не прошла CI;
- обязательные build/test jobs выполняются на GitHub-hosted Ubuntu и не используют production VDS как CI runner.

## История production

Попытка установки `v1.3.0` остановилась до atomic switch из-за production environment contamination (`MAX_SYMBOLS_PER_USER=20`). Production осталась на `1.2.0`; rollback не потребовался, SQLite не изменялись.

## Исключения

- Telegram Mini App PR #53 не входит;
- Telegram App `API_ID/API_HASH`, Telethon, Pyrogram и user sessions не используются;
- operational feature flags не включаются автоматически;
- production deployment не выполняется release workflow.

## Проверка

Release audit включает dependency audit, compileall, metadata consistency, candidate environment isolation, полный unit suite, bounded soak `500 × 10`, systemd render/verify и проверку отсутствия Mini App.
