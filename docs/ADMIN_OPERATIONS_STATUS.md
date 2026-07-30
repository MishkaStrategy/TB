# Read-only admin operations status

The admin panel contains a `⚙️ Операции` screen that summarizes process
lifecycle, the persistent restart circuit breaker, FVG history archive health,
background jobs and the latest SQLite observability snapshots.

The screen is intentionally read-only. It does not add rerun, enable, disable,
restart, circuit reset, archive export/restore, lease recovery or retention
actions.

## Data sources

The reader opens the existing FVG runtime SQLite file through a SQLite URI with
`mode=ro` and enables `PRAGMA query_only=ON`.

It first inspects `sqlite_schema` and only queries runtime tables that already
exist:

- `runtime_lifecycle_state` and `runtime_lifecycle_events`;
- `process_restart_guard_state` and `process_restart_requests`;
- `health` archive counters;
- `background_task_state`;
- `database_observation_runs`.

The configured FVG history archive is opened through a separate `mode=ro`,
`query_only` connection. Only these archive tables are read:

- `archive_metadata`;
- `fvg_archive_runs`.

If a feature has never been enabled and its tables or archive file do not exist,
the screen shows `нет данных` or `Файл: не создан`. Opening the screen does not
create the runtime database, archive file or any optional table.

## Process section

When lifecycle data exists, the screen displays:

- current status;
- PID;
- last lifecycle phase;
- last update time;
- shutdown outcome;
- last recorded lifecycle error, when present.

This is a view of the state written by the lifecycle stage. The admin screen does
not change or finalize that state.

## Restart circuit-breaker section

When persistent restart-guard tables exist, the screen displays:

- whether restart requests are currently allowed or blocked;
- allowed requests inside the configured rolling window;
- configured request limit and window duration;
- total circuit trips;
- active or last stored cooldown deadline;
- latest request status and decision reason;
- latest request reason and signal error, when present.

The values for the request limit, rolling window and cooldown are read from the
same environment-backed configuration used by the watchdog. Request rows and
state are read directly from SQLite.

Opening the screen does not instantiate `ProcessRestartGuard` and therefore does
not:

- create or migrate guard tables;
- run `BEGIN IMMEDIATE` guard decisions;
- add denied request rows;
- extend or clear cooldown;
- reset the trip counter;
- mark a request failed;
- send a signal or restart the process.

The reader returns at most five recent request rows. The Telegram formatter only
shows the latest one and truncates long reason/error text so the full screen
stays below Telegram's message-size limit.

## FVG archive section

The archive section displays:

- whether the configured archive file exists and can be read;
- combined main/WAL/SHM file size;
- archive schema version;
- latest archive run time and cutoff;
- event, delivery and source-delete counts for the latest batch;
- cumulative event/delivery counters stored in runtime health;
- archive failure count;
- the saved `fvg_archive_backlog_possible` signal;
- last archive update and last stored archive error.

The reader intentionally does not query `archived_fvg_events` or
`archived_fvg_deliveries`. It reads only metadata, at most five run rows and the
already stored runtime-health values. Therefore opening the Telegram screen does
not perform:

- `COUNT(*)` over archive history;
- `PRAGMA quick_check`;
- payload JSON validation;
- orphan-delivery detection;
- archive reconciliation;
- checkpoint, compaction, export or restore.

Those deeper checks remain available only through the explicit
`run_fvg_archive_audit.py` CLI documented in `docs/FVG_ARCHIVE_AUDIT.md`.

## Background task section

The screen displays:

- total registered jobs;
- counts by current status;
- read-only overdue count;
- running jobs whose stored lease is already expired;
- up to five jobs that require attention.

A non-running job is considered overdue when the time since its last start (or
registration if it never started) is at least three configured intervals. This
matches the default task-watchdog multiplier but does not invoke
`recover_stale()` and does not mutate the registry.

Attention items include failed/stale jobs, expired running leases, overdue jobs
and jobs with consecutive failures.

## Database snapshot section

When SQLite observability history exists, the screen displays the latest
snapshot for each database and a 24-hour delta when at least two available
snapshots exist in that window.

The admin reader only queries stored observation rows. It does not run:

- `PRAGMA quick_check`;
- `COUNT(*)` over product tables;
- `dbstat`;
- a new observability capture;
- `VACUUM`, `ANALYZE` or WAL checkpoint.

Therefore opening the admin screen has bounded cost and does not replace the
scheduled observability collector.

## Security and access

The callback remains under the existing `is_admin` authorization check. No
operational data is exposed to non-admin Telegram users.

## Failure behavior

- Missing runtime database: the screen reports `database_file_missing` and does
  not create a file.
- Busy or unreadable runtime SQLite: the error is displayed without retry loops
  or migrations.
- Missing optional runtime tables: the corresponding section reports no data
  while the rest of the screen remains available.
- Missing archive file: the archive section reports `Файл: не создан` and does
  not create it.
- Incomplete or unreadable archive schema: the archive section reports the
  read error without running migration or repair.
- Malformed guard timestamps: the reader does not treat them as an active
  cooldown and continues showing the stored request history.

## Not included

- task rerun or cancellation;
- feature-flag changes;
- restart circuit reset/unblock actions;
- archive export, restore or compaction;
- dead-letter actions;
- backup-history inspection;
- automatic remediation;
- operational alerts generated by viewing the screen.
