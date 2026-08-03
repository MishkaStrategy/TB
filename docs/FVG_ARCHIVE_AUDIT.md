# FVG archive audit

`run_fvg_archive_audit.py` is an explicit, read-only diagnostic for the FVG
history archive. It is not scheduled by the bot and does not repair, compact,
export or delete data.

## Usage

```bash
python run_fvg_archive_audit.py \
  --archive data/archive/fvg_history.sqlite3 \
  --runtime data/fvg_event_store.sqlite3 \
  --output archive-audit.json
```

The command prints a JSON report. When `--output` is provided, the same report is
written atomically through a temporary file and rename.

Exit codes:

- `0`: no structural integrity errors;
- `1`: archive missing without `--allow-missing`, unsupported/missing schema,
  failed `quick_check`, orphan deliveries, invalid sampled payloads or an
  unreadable archive.

## Options

```text
--archive PATH
--runtime PATH
--skip-quick-check
--payload-sample-size N
--allow-missing
--output PATH
```

`--allow-missing` is intended for rollout validation before the archive feature
has created its first file. The report passes with the warning
`archive_file_missing`.

`--skip-quick-check` avoids `PRAGMA quick_check`. Counts and payload sampling are
still performed.

## Structural checks

The audit opens SQLite through `mode=ro` and `PRAGMA query_only=ON`.

It verifies:

- required archive tables exist;
- archive schema version is `1`;
- optional `PRAGMA quick_check` returns `ok`;
- archived deliveries do not reference missing events;
- sampled `payload_json` values are objects whose `event_id` matches the row.

These failures indicate an archive that should not be trusted for recovery and
produce exit code `1`.

## Run reconciliation

The report compares unique archive rows with sums from `fvg_archive_runs`:

- event rows;
- delivery rows;
- source-deleted rows.

A mismatch is a warning, not structural corruption. The archive implementation
commits copied rows and a run record before the surrounding runtime transaction
is guaranteed to commit. After a process failure, a retry can legitimately add
another run record while primary keys keep archive event/delivery rows unique.

The `run_reconciliation` object shows each exact-match result and warnings use:

- `event_run_total_mismatch`;
- `delivery_run_total_mismatch`;
- `source_delete_total_mismatch`.

## Runtime health comparison

When the runtime FVG SQLite contains the `health` table, the audit reads archive
counters and recent failure state.

Counter mismatches and a retained `last_archive_error` are warnings because:

- health counters can be reset or migrated independently;
- a previous archive failure can remain recorded after later successful work;
- archive rows are the authoritative durable history.

Warnings include:

- `runtime_event_counter_mismatch`;
- `runtime_delivery_counter_mismatch`;
- `runtime_last_archive_error_present`;
- `runtime_health_unavailable`.

## Cost

This audit is intentionally explicit because it can be more expensive than the
scheduled low-cost observability collector:

- exact `COUNT(*)` is executed on archive events, deliveries and runs;
- `PRAGMA quick_check` scans archive structures unless skipped;
- up to `--payload-sample-size` recent payloads are decoded.

It is not called from polling, JobQueue, admin callbacks or startup.

## Safety

The tool does not:

- create a missing archive;
- modify archive or runtime SQLite;
- recover or delete rows;
- run `VACUUM`, `ANALYZE` or checkpoint;
- change feature flags;
- trigger Telegram messages.

## Recommended operational use

Run after enabling archival, after restoring a backup, and before relying on an
archive for manual recovery. Keep the JSON report with release/backup evidence.
