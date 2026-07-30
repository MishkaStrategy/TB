# FVG Alert Bot 1.3.3

`1.3.3` — кроссплатформенный hotfix verified backup поверх стабильного `1.3.2`.

## Исправлено

- macOS BSD tar больше не добавляет AppleDouble `._*` members после построения `BACKUP_MANIFEST.json`;
- `scripts/backup_data.sh` запускает tar с `COPYFILE_DISABLE=1`;
- существующие Finder metadata `._*` и `.DS_Store` исключаются из runtime snapshot;
- manifest verification остаётся строгой для обычных неподтверждённых членов архива;
- добавлен behavior-level regression test, проверяющий переменную окружения tar и фактическое отсутствие metadata в manifest и архиве.

## Почему это важно

На Linux VDS проблема обычно не проявляется. На macOS системный BSD tar может синтезировать AppleDouble sidecars для extended attributes уже после создания manifest. В результате корректный backup ошибочно отклонялся как содержащий лишние неподтверждённые данные.

Hotfix устраняет источник лишних файлов, а не ослабляет проверку целостности архива.

## Совместимость

- application runtime и FVG-логика не изменены;
- пользовательские настройки и SQLite не мигрируются и не удаляются;
- production env не изменяется;
- Telegram работает только через Bot API token;
- Telegram Mini App PR #53 не включён;
- operational feature flags остаются default-off.

## Проверка релиза

Release audit проверяет:

- shell syntax;
- release metadata consistency;
- macOS AppleDouble regression;
- candidate environment isolation;
- полный unit suite;
- dependency audit;
- bounded soak `500 × 10`;
- production systemd render/verify;
- отсутствие Telegram Mini App.

## Production deployment

Deployment выполняется отдельно по immutable tag `v1.3.3` и точному SHA из deployment issue. Production VDS не обновлялась при подготовке этого hotfix.
