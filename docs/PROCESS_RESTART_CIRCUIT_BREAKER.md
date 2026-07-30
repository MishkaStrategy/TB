# Process restart circuit breaker

This stage adds an opt-in persistent circuit breaker for stale-candle process
restart requests. It complements systemd `StartLimit*`: systemd protects against
rapid crash loops, while this guard also limits slow repeated restarts separated
by the 1000-second stale-candle threshold.

## Configuration

```env
FVG_PROCESS_RESTART_GUARD_ENABLED=false
FVG_PROCESS_RESTART_MAX_REQUESTS=3
FVG_PROCESS_RESTART_WINDOW_SECONDS=3600
FVG_PROCESS_RESTART_COOLDOWN_SECONDS=3600
FVG_PROCESS_RESTART_HISTORY_RETENTION_DAYS=30
```

The feature is disabled by default. It can protect either restart mode:

- legacy `immediate_exit`;
- `sigterm_then_failure_exit` from the graceful stale-restart stage.

## Persistent schema

When enabled, the guard creates two tables in the existing FVG runtime SQLite:

- `process_restart_guard_state`: one current cooldown/trip state;
- `process_restart_requests`: bounded allowed/blocked request history.

The decision is made under `BEGIN IMMEDIATE`, so concurrent watchdog/process
instances cannot both consume the same remaining restart slot.

## Decision algorithm

For each stale watchdog restart request:

1. read the persistent `blocked_until` value;
2. if cooldown is active, deny without inserting another denied row;
3. count allowed restart requests in the configured rolling window;
4. if the count reached the limit, insert one `blocked` decision, increment the
   trip counter and set `blocked_until`;
5. otherwise insert an allowed `requested` row and permit the restart callback.

Allowed callback attempts remain part of the window even if `os.kill` later
fails. This prevents a broken signal path from being hammered every 30 seconds.
The request row is updated to `failed` with its error class/message.

## Local suppression

After a persistent denial, the current watchdog stores the returned
`blocked_until` locally. Evaluations during that interval return without another
SQLite decision or health-counter increment.

A guard SQLite error is fail-closed:

- no restart signal is sent;
- `process_restart_guard_failures` is incremented;
- the error is stored in `process_restart_guard_error`;
- the watchdog waits at least one normal check interval (minimum 30 seconds)
  before another guard attempt.

## Health fields

The watchdog records:

- `process_restart_guard_blocked`;
- `process_restart_guard_reason`;
- `process_restart_guard_blocked_until`;
- `process_restart_guard_request_id`;
- `process_restart_guard_requests_in_window`;
- `process_restart_guard_error`.

Counters:

- `process_restart_guard_suppressions`;
- `process_restart_guard_failures`;
- `process_restart_guard_finalize_failures`.

## Example default timeline

With three requests per hour and a one-hour cooldown:

- requests 1–3 inside the hour are allowed;
- request 4 trips the circuit and is suppressed;
- all later evaluations in the cooldown are suppressed locally/persistently;
- after cooldown expiry, old requests outside the rolling hour no longer count
  and a new request can be allowed.

## Retention

Each guard decision deletes at most 100 history rows older than the configured
retention period. Cleanup is bounded and does not run on a separate schedule.

## Rollout

1. Keep the guard disabled while validating graceful stale restarts.
2. Enable it with the defaults above.
3. Confirm the guard tables are created in the FVG runtime SQLite.
4. Exercise a controlled sequence with a reduced test threshold/window.
5. Verify the fourth request is suppressed and the cooldown persists across a
   process restart.
6. Restore production values before normal operation.
7. Monitor suppressions, guard errors and systemd service state.

## Rollback

Set `FVG_PROCESS_RESTART_GUARD_ENABLED=false` and restart. Existing tables remain
inert and are included in the normal verified FVG SQLite backup.

## Not included

- automatic feature-flag rollback;
- Telegram admin controls;
- automatic circuit reset before cooldown expiry;
- systemd unit changes;
- restart requests for failure types other than the FVG stale-candle watchdog.
