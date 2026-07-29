# SQLite observability

Этот этап добавляет исторические снимки размера и структуры SQLite без destructive maintenance. Он не выполняет `VACUUM`, `ANALYZE`, удаление продуктовых данных или принудительный WAL checkpoint.

## Базы

По умолчанию наблюдаются:

- `data/fvg_event_store.sqlite3` под ключом `fvg`;
- `data/funding_alerts.sqlite3` под ключом `funding`.

История сохраняется в существующей FVG-базе, поэтому входит в текущий SQLite backup и не создаёт третий runtime-файл.

## Снимок базы

Для каждого запуска сохраняются:

- размер основного файла;
- размер `-wal`;
- размер `-shm`;
- `page_size`;
- `page_count`;
- `freelist_count`;
- allocated, free и used bytes;
- `journal_mode`;
- `user_version`;
- `schema_version`;
- доступность `dbstat`;
- ошибка открытия или чтения;
- optional результат `PRAGMA quick_check`.

Отдельная таблица хранит размеры SQLite-объектов:

- имя объекта;
- тип: table/index;
- bytes;
- pages;
- optional row count.

Если `dbstat` недоступен в конкретной сборке SQLite, общий снимок всё равно записывается, а object sizes остаются пустыми.

## Read-only collector

Целевая база открывается через SQLite URI `mode=ro`. Коллектор не создаёт отсутствующую target-базу и записывает состояние `database_file_missing`.

Storage-соединение открывается отдельно только после закрытия read-only target-соединения.

## Таблицы observability

### `database_observation_runs`

Один row на базу и timestamp. Содержит file/page metrics, состояние доступности и optional integrity result.

Unique key:

```text
(database_key, captured_at)
```

Повторная запись того же snapshot идемпотентно обновляет run.

### `database_object_snapshots`

Нормализованные object metrics с foreign key на run и `ON DELETE CASCADE`.

## Growth

`SQLiteObservabilityStore.growth()` сравнивает первый и последний доступный снимок и возвращает:

- elapsed seconds;
- main file delta;
- WAL delta;
- allocated bytes delta;
- used bytes delta.

Это позволяет позже показывать администратору фактический рост за выбранный период, а не только текущий общий размер файлов.

## Retention

История observability имеет отдельный bounded retention. Cleanup удаляет не более 500 runs за один вызов; object snapshots удаляются каскадно.

Product tables `events`, `deliveries`, funding crossings и snapshots этим cleanup не затрагиваются.

## Feature flags

```env
DATABASE_OBSERVABILITY_ENABLED=false
DATABASE_OBSERVABILITY_INTERVAL_SECONDS=3600
DATABASE_OBSERVABILITY_RETENTION_DAYS=90
DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED=false
DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED=false
```

Все новые функции выключены по умолчанию.

## Стоимость diagnostics

### Row counts

`DATABASE_OBSERVABILITY_ROW_COUNTS_ENABLED=true` запускает точный `COUNT(*)` для каждой пользовательской таблицы. На больших таблицах это может создавать заметную read-нагрузку, поэтому scheduled default — `false`.

### Integrity check

`DATABASE_OBSERVABILITY_INTEGRITY_CHECK_ENABLED=true` запускает `PRAGMA quick_check` для каждого snapshot. Ежечасное выполнение на большой базе может быть дорогим, поэтому scheduled default — `false`.

Полную integrity-проверку безопаснее запускать отдельно перед backup/restore или вручную из будущего maintenance workflow.

## Scheduler

При включённом флаге регистрируется job:

```text
sqlite-observability
```

Default interval — 3600 секунд. Повторный вызов scheduler не создаёт второй job с тем же именем.

Ошибка snapshot логируется, но не останавливает FVG, funding или delivery jobs.

## Rollout

1. Выпустить код с `DATABASE_OBSERVABILITY_ENABLED=false`.
2. Включить snapshots без row counts и quick check.
3. Проверить размеры `database_observation_runs` и `database_object_snapshots`.
4. Сравнить growth за 24–72 часа.
5. Только при необходимости временно включать row counts или integrity check.

## Не входит в этап

- автоматический VACUUM;
- `ANALYZE`;
- принудительный WAL checkpoint;
- архивирование продуктовых таблиц;
- удаление FVG/funding history;
- admin UI;
- уведомления о превышении порогов роста.
