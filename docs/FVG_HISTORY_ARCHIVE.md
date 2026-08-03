# FVG history archive

This stage adds opt-in archive-before-delete retention for old terminal FVG
events. The default runtime retention remains 90 days and the feature is
disabled until explicitly rolled out.

## Configuration

```env
FVG_HISTORY_ARCHIVE_ENABLED=false
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
scheduler and Bitunix stream start.

When the flag is `false`, the original `FvgEventStore._prune_if_due` method is
untouched and the existing delete-only retention behavior remains active.

When the flag is `true`, only that event-store instance receives an
archive-aware prune implementation. Detector, filters, recovery, delivery and
statistics APIs are unchanged.

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

## Rollout

1. Deploy with `FVG_HISTORY_ARCHIVE_ENABLED=false`.
2. Confirm the archive path has sufficient disk space and is covered by backup.
3. Enable the flag with the 90-day default.
4. Restart the bot and confirm the archive file is created with mode `0600`.
5. Inspect health metrics after the first retention pass.
6. Verify a runtime backup contains the archive SQLite and passes manifest
   verification.
7. Keep batch/max-batch defaults until production archive duration is measured.

## Rollback

Set `FVG_HISTORY_ARCHIVE_ENABLED=false` and restart. The existing archive remains
readable and backed up, while runtime retention returns to the previous
implementation. No destructive migration is required.

## Not included

- automatic restore from the history archive;
- admin archive search/export;
- archive compaction or `VACUUM`;
- funding-history archival;
- deletion of active outbox events;
- remote archive replication.
