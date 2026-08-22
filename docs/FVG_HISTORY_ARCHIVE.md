# FVG history archive

Old terminal FVG history uses verified archive-before-delete retention. Runtime
retention remains 90 days by default, but destructive delete-only pruning is not
a supported mode.

## Safety invariant

A historical FVG event may leave runtime SQLite only after it has been copied to
the archive and verified there. If archive retention cannot run, source history
is preserved.

The configuration switch controls whether runtime pruning is allowed at all:

- `FVG_HISTORY_ARCHIVE_ENABLED=true` — archive, verify, then delete eligible
  terminal history from runtime SQLite;
- `FVG_HISTORY_ARCHIVE_ENABLED=false` — preserve history in runtime SQLite and
  perform no retention deletion.

`false` never restores the legacy delete-only implementation.

## Configuration

```env
FVG_HISTORY_ARCHIVE_ENABLED=true
FVG_HISTORY_ARCHIVE_PATH=data/archive/fvg_history.sqlite3
FVG_HISTORY_RETENTION_DAYS=90
FVG_HISTORY_ARCHIVE_BATCH_SIZE=500
FVG_HISTORY_ARCHIVE_MAX_BATCHES=10
```

One retention pass archives at most `batch size × max batches` events. The
archive implementation caps each SQL batch at 500 event IDs to remain below
portable SQLite parameter limits.

## Startup integration

`bot.post_init` configures the existing FVG event-store instance before the
scheduler and market streams start.

Archive retention is enabled by default. Only that event-store instance receives
an archive-aware prune implementation. Detector, filters, recovery, delivery and
statistics APIs are unchanged.

If an existing deployment still carries
`FVG_HISTORY_ARCHIVE_ENABLED=false`, startup installs a no-prune guard over the
legacy `FvgEventStore._prune_if_due`. This is deliberately fail-closed: the
runtime database can grow, but old history cannot be silently destroyed.

Changing the value to `true` on a later restart installs verified
archive-before-delete retention normally.

## Archive schema

The separate SQLite contains:

- `archived_fvg_events` with the complete original event payload;
- `archived_fvg_deliveries` with historical recipients and delivery times;
- `fvg_archive_runs` with batch totals;
- `archive_metadata` with the archive schema version.

The event ID and `(event_id, chat_id)` delivery key remain unique, so a retry
after a partial process failure is idempotent.

## Copy-before-delete order

For every bounded batch:

1. acquire a runtime `BEGIN IMMEDIATE` write transaction;
2. select events older than the retention cutoff;
3. exclude events that still have a legacy outbox row;
4. exclude events with Outbox V2 status `pending`, `processing` or
   `retry_scheduled`;
5. copy events and deliveries into the archive transaction;
6. verify every selected event exists in the archive;
7. commit the archive transaction;
8. delete exactly the verified event IDs from runtime SQLite;
9. verify the runtime delete count.

The runtime write lock prevents another worker from creating an outbox row
between eligibility evaluation and deletion.

## Failure behavior

Runtime deletions run under a savepoint.

If archive creation, write, verification, run-history write or source deletion
fails:

- runtime event deletions are rolled back;
- the new FVG event that triggered retention can still be persisted;
- `fvg_archive_failures` is incremented;
- `last_archive_error` and `last_archive_failure_at` are recorded;
- `last_pruned_at` is not advanced.

Archive rows committed before a runtime rollback are harmless. The next pass
uses primary keys to verify/copy them idempotently before retrying deletion.

If archive initialization itself fails during startup, startup must fail rather
than continue with delete-only retention.

## Health metrics

Successful passes update:

- `last_archive_at`;
- `last_pruned_at`;
- `events_archived`;
- `deliveries_archived`;
- `events_pruned`;
- `fvg_archive_backlog_possible`.

`fvg_archive_backlog_possible=true` means the final configured batch was full;
another daily retention pass may still have eligible history to process.

When pruning is explicitly disabled, `last_pruned_at` is not advanced because no
retention deletion occurred.

## Backup contract

The archive SQLite is not copied by raw `rsync`.

`backup_data.sh`:

- excludes the configured archive main/WAL/SHM files when the archive is inside
  `DATA_DIR`;
- creates a read-only SQLite backup snapshot;
- runs source `PRAGMA quick_check`;
- converts the snapshot to portable `journal_mode=DELETE`;
- includes it in `BACKUP_MANIFEST.json` with size, SHA-256 and `quick_check`;
- fails if any unexpected SQLite WAL/SHM sidecar remains in the snapshot.

A configured archive outside `DATA_DIR` is included at
`archive/fvg_history.sqlite3` in the backup.

## Deployment checks

Before enabling pruning on an existing deployment:

1. confirm the archive path has sufficient disk space;
2. confirm the path is covered by the verified backup contract;
3. use `FVG_HISTORY_ARCHIVE_ENABLED=true`;
4. restart the bot and confirm the archive file is created with mode `0600`;
5. inspect archive health metrics after the first retention pass;
6. verify a runtime backup contains the archive SQLite and passes manifest
   verification;
7. keep batch/max-batch defaults until production archive duration is measured.

A deployment may temporarily use `FVG_HISTORY_ARCHIVE_ENABLED=false` if archive
I/O must be disabled. In that state old FVG rows remain in runtime SQLite and
operators must monitor disk growth.

## Rollback

Set `FVG_HISTORY_ARCHIVE_ENABLED=false` and restart only when preserving all
runtime history is preferable to archive I/O. The existing archive remains
readable and backed up. Runtime retention deletion stops completely; it does not
return to the old destructive implementation.

## Not included

- automatic restore from the history archive;
- admin archive search/export;
- archive compaction or `VACUUM`;
- funding-history archival;
- deletion of active outbox events;
- remote archive replication.
