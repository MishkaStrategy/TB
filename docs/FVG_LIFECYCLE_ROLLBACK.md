# FVG lifecycle: staged rollout and rollback

## Scope of the foundation release

This release adds an optional, shadow-only FVG lifecycle engine. It does not
edit Telegram messages, filter notifications, calculate Smart Filter scores or
render charts.

When enabled, the background job:

1. reads confirmed FVG events already persisted by the existing alert service;
2. creates one stable lifecycle zone per confirmed formation;
3. replays closed 1-minute candles from the shared cache;
4. persists significant lifecycle events in additive SQLite tables;
5. writes operational counters to the existing health store.

The existing detector, recipient filtering, Telegram `send_message` path,
`deliveries` table and persistent `outbox` remain unchanged.

## Feature flags

```dotenv
FVG_LIFECYCLE_ENABLED=false
FVG_LIFECYCLE_SHADOW_MODE=true
FVG_LIFECYCLE_SYNC_INTERVAL_SECONDS=30
FVG_LIFECYCLE_MAX_AGE_BARS=96
FVG_LIFECYCLE_APPROACHING_ZONE_WIDTHS=1
FVG_LIFECYCLE_INVALIDATION_BUFFER_RATIO=0
```

Production default is disabled.

## Safe rollout

1. Deploy the code with `FVG_LIFECYCLE_ENABLED=false`.
2. Verify that current FVG and funding notifications are unchanged.
3. Create a normal SQLite backup with the existing backup tooling.
4. Set `FVG_LIFECYCLE_ENABLED=true` and keep shadow mode enabled.
5. Restart the service.
6. Confirm these health keys begin updating:
   - `lifecycle_enabled`;
   - `lifecycle_last_sync`;
   - `lifecycle_zones`;
   - `lifecycle_active_zones`;
   - `lifecycle_zone_events`.
7. Compare lifecycle counters with raw confirmed FVG events before enabling any
   future user-visible message editing.

## Immediate rollback

Set:

```dotenv
FVG_LIFECYCLE_ENABLED=false
```

Then restart the service.

No database downgrade is required. The scheduled lifecycle job is not created,
and the bot continues using the original detector, delivery outbox and Telegram
messages.

## Code rollback

It is safe to deploy the previous application version. New tables are additive:

- `fvg_lifecycle_metadata`;
- `fvg_zones`;
- `fvg_zone_events`.

The previous code does not query these tables. Existing tables are not renamed,
removed or changed.

## Optional data cleanup

Do not drop lifecycle tables during an emergency rollback. Leaving them in place
preserves diagnostics and allows the feature to resume later.

After a confirmed permanent removal, a maintenance window may be used to back up
and drop only the three lifecycle tables. This is not part of normal rollback.

## Failure isolation

Lifecycle SQLite and replay work runs through `asyncio.to_thread`. Exceptions are
caught by the lifecycle job and increment `lifecycle_sync_failures`. A lifecycle
failure does not stop:

- WebSocket ingestion;
- confirmed or preliminary FVG detection;
- recipient filtering;
- Telegram delivery retries;
- funding alerts.

## Current limitations

The foundation release intentionally uses REST recovery for symbols retained only
by an active lifecycle zone. User-visible real-time editing will require a later
stage that adds those lifecycle-only symbols to the shared WebSocket subscription
without allowing them to generate new user notifications.
