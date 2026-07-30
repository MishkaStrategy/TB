# Background task registry

Этот этап добавляет cross-process leases, историю запусков и наблюдение за просроченными recurring jobs. Он не перезапускает процесс, не отменяет jobs и не меняет FVG detector, WebSocket или delivery semantics.

## Область действия

Через registry проходят JobQueue tasks:

- `fvg-confirmed-control`;
- `fvg-pre-control-t-minus-3`;
- `fvg-delivery-outbox-retry`;
- `fvg-rest-recovery`;
- `fvg-operational-health`;
- `funding-quarter-hour`;
- `sqlite-observability`, если соответствующий модуль включён.

`background-task-watchdog` намеренно не отслеживает сам себя, чтобы его отказ не создавал рекурсивный lease/overdue cycle.

## Feature flags

```env
BACKGROUND_TASK_REGISTRY_ENABLED=false
BACKGROUND_TASK_WATCHDOG_ENABLED=false
BACKGROUND_TASK_HISTORY_RETENTION_DAYS=30
BACKGROUND_TASK_HEARTBEAT_SECONDS=30
BACKGROUND_TASK_MIN_LEASE_SECONDS=120
BACKGROUND_TASK_WATCHDOG_INTERVAL_SECONDS=60
BACKGROUND_TASK_STALE_MULTIPLIER=3
```

Оба функциональных флага выключены по умолчанию.

`BACKGROUND_TASK_WATCHDOG_ENABLED=true` также включает lease wrapper для наблюдаемых jobs, даже если отдельный registry flag выключен. Watchdog без leases не смог бы отличить зависший run от никогда не запущенного callback.

## State table

`background_task_state` хранит один агрегированный row на task:

- task name/kind;
- expected interval;
- registered timestamp;
- current status/run/owner;
- lease and heartbeat;
- last start/completion/success/failure;
- last duration;
- last error class/code/message;
- consecutive failures;
- run/success/failure/cancelled/skipped/stale counters.

Основные статусы:

- `idle` — task зарегистрирован, но ещё не выполнялся;
- `running` — lease принадлежит активному run;
- `success` — последний run завершился успешно;
- `failed` — uncaught exception вышел из callback;
- `cancelled` — coroutine отменена shutdown или scheduler-ом;
- `stale` — lease истёк без финального результата.

## Run history

`background_task_runs` хранит отдельные runs со статусами:

- `running`;
- `success`;
- `failed`;
- `cancelled`;
- `skipped`;
- `stale`.

History включает trigger, owner, started/heartbeat/lease/completed timestamps, duration, error и metadata JSON.

Retention удаляет только final run rows и не более 500 rows за один pass. Aggregate state не удаляется.

## Atomic non-overlap

Перед callback worker выполняет `BEGIN IMMEDIATE` и `try_begin()`:

1. task metadata регистрируется или обновляется;
2. expired active lease переводится в `stale`;
3. если действующий lease ещё активен, создаётся отдельный `skipped` run с кодом `overlap_prevented`;
4. иначе создаётся новый `running` run и ownership записывается атомарно.

Второй процесс не может начать тот же task одновременно, даже если оба scheduler-а сработали в одну секунду.

## Lease и heartbeat

Default lease рассчитывается как:

```text
max(BACKGROUND_TASK_MIN_LEASE_SECONDS, expected_interval * 2)
```

Heartbeat выполняется не реже configured interval и не позже одной трети lease. Продление принимается только от текущего `owner_id` и `run_id`.

Если process завершился между callback и финализацией, watchdog или следующий `try_begin()` переводит истёкший run в `stale`.

## Failure semantics

Registry фиксирует только execution-level результат wrapper-а:

- uncaught exception;
- cancellation;
- lease loss/stale;
- overlap skip;
- normal callback completion.

Некоторые существующие callbacks обрабатывают ошибки отдельных символов/получателей внутри себя и возвращаются нормально. Такие domain-level failures продолжают учитываться существующими FVG/funding health counters и не превращают весь scheduled run в `failed`.

Это разделение намеренное: task registry отвечает за выполнение job, а не за бизнес-результат каждой записи внутри batch.

## Watchdog

Watchdog:

1. восстанавливает expired running leases в `stale`;
2. считает task overdue, если с последнего старта прошло не меньше `expected_interval * stale_multiplier`;
3. записывает агрегат в существующий health store;
4. bounded-cleanup старой run history.

Health keys:

- `background_tasks_degraded`;
- `background_tasks_overdue_count`;
- `background_tasks_overdue_names`;
- `background_tasks_last_check`;
- `background_task_runs_pruned`;
- counter `background_task_stale_recoveries`;
- counter `background_task_overlap_skips`;
- counter `background_task_uncaught_failures`;
- counter `background_task_watchdog_failures`.

Watchdog не вызывает `os._exit`, не перезапускает systemd unit и не изменяет расписание.

## Compatibility

Интеграция выполнена в `alerts/scheduler_multi.py`:

- base scheduler продолжает регистрировать прежние jobs и timings;
- перед регистрацией его callback references заменяются tracked wrappers;
- detector, base scheduler calculations и FVG lifecycle не переписываются;
- при выключенных flags operation вызывается напрямую без создания registry DB tables.

Это снижает конфликт с отдельным FVG lifecycle PR.

## Rollout

1. Выпустить с обоими flags `false`.
2. Включить `BACKGROUND_TASK_REGISTRY_ENABLED=true`.
3. Проверить state/run history и overlap counters минимум один operating cycle.
4. Убедиться, что leases заметно длиннее обычных durations.
5. Включить `BACKGROUND_TASK_WATCHDOG_ENABLED=true`.
6. Наблюдать overdue/stale без автоматического restart.

## Rollback

Оба flags можно выключить без миграции назад. Existing JobQueue callbacks снова вызываются напрямую. Additive tables остаются в FVG SQLite и входят в backup.

## Не входит в этап

- автоматический restart;
- task enable/disable из админ-панели;
- ручной rerun;
- graceful queue drain;
- startup/shutdown lifecycle state;
- WebSocket/ping/recovery child-task registry;
- alerts администраторам по task state.
