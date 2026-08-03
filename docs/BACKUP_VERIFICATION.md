# Verified runtime backups

`backup_data.sh` создаёт transactionally consistent копии SQLite и публикует архив только после проверки snapshot и временного tar.

## Артефакты

Один успешный запуск создаёт:

```text
fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz
fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz.sha256
backup_history.sqlite3
```

`backup_history.sqlite3` хранится в backup-каталоге и не входит в runtime data directory.

## Порядок создания

1. Процесс получает non-blocking `flock` на `.backup.lock`.
2. В `backup_history.sqlite3` создаётся run со статусом `running`.
3. JSON и прочие runtime-файлы копируются через `rsync`.
4. Обе SQLite-базы копируются через SQLite backup API.
5. Для каждого snapshot-файла вычисляется SHA-256.
6. Каждый `.sqlite3` проходит `PRAGMA quick_check`.
7. Создаётся `BACKUP_MANIFEST.json`.
8. Формируется временный tar.gz.
9. Временный архив проверяется через Python `tarfile`.
10. Только после проверки архив переименовывается в final path.
11. Создаётся `.sha256` sidecar.
12. Final archive повторно проверяется вместе с sidecar.
13. History run переводится в `success`.

Если любой обязательный шаг завершается ошибкой, final archive не публикуется до этапа `publish_archive`, а run получает статус `failed` и имя шага.

## Manifest

`BACKUP_MANIFEST.json` содержит:

- schema version;
- UUID run;
- UTC timestamp;
- final archive name;
- release ref;
- количество файлов;
- суммарный uncompressed size;
- для каждого файла: relative path, size, SHA-256 и kind;
- для SQLite-файлов: `quick_check: ok`.

Manifest не перечисляет сам себя. Его SHA-256 сохраняется в history после проверки final archive.

## Archive safety

Verifier отклоняет:

- абсолютные пути;
- `..` path traversal;
- duplicate members;
- symlink и hardlink;
- device/FIFO/socket members;
- файлы, отсутствующие в manifest;
- лишние файлы;
- несовпадение size или SHA-256;
- duplicate/non-canonical manifest paths;
- неверный `file_count` или total size;
- corrupted SQLite;
- sidecar с другим checksum или filename.

SQLite-файлы извлекаются во временный каталог verifier-а и повторно проходят `quick_check` уже из содержимого tar.

## History statuses

- `running` — backup начат;
- `success` — final archive, manifest и checksum проверены;
- `failed` — обязательный шаг завершился ошибкой;
- `interrupted` — предыдущий run оставался `running` более 24 часов.

History хранит:

- started/completed timestamps;
- archive path и bytes;
- archive SHA-256;
- manifest SHA-256;
- file count и uncompressed bytes;
- failure step и error message.

## Retention

```env
RETENTION_DAYS=14
HISTORY_RETENTION_DAYS=180
```

`RETENTION_DAYS` удаляет старые archive и checksum sidecar.

`HISTORY_RETENTION_DAYS` независимо удаляет только final history rows. Cleanup bounded: не более 500 rows за запуск.

## Ручная проверка

```bash
PYTHONPATH=/opt/fvg-alert-bot \
/opt/fvg-alert-bot/.venv/bin/python -m database.backup_audit verify \
  --archive /var/backups/fvg-alert-bot/fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz \
  --checksum /var/backups/fvg-alert-bot/fvg-alert-bot-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

Команда возвращает JSON с archive/manifest SHA-256, размером, run ID и file count.

## Restore gate

Перед восстановлением:

1. выполнить `verify` для archive и sidecar;
2. распаковать только в новый временный каталог;
3. проверить ownership и permissions;
4. остановить bot service;
5. сохранить отдельную pre-restore копию текущего `data/`;
6. заменить runtime files;
7. запустить post-deploy checks;
8. только после успешной проверки удалить временные файлы.

Автоматическое восстановление в этом этапе намеренно не добавлено.

## Параллельные запуски

Второй backup не ждёт первый. Он завершается с exit code `75` и сообщением `Another backup process is already running`.

## Не входит в этап

- автоматический restore;
- удалённая репликация;
- object storage upload;
- encryption at rest;
- admin UI для history;
- product-table archiving.
