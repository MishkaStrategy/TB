# Runtime lifecycle and graceful shutdown

This stage adds opt-in process lifecycle history and a bounded shutdown drain for
FVG delivery. It does not change FVG detection, funding schedules or normal
Telegram delivery while the flags are disabled.

## Feature flags

```env
RUNTIME_LIFECYCLE_ENABLED=false
GRACEFUL_SHUTDOWN_ENABLED=false
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS=25
RUNTIME_LIFECYCLE_HISTORY_RETENTION_DAYS=30
```

Both functional flags are disabled by default.

`RUNTIME_LIFECYCLE_ENABLED` records process startup, running, stopping and
terminal states. It also moves stream/watchdog cleanup to PTB `post_stop`, but it
does not run an additional persistent outbox pass.

`GRACEFUL_SHUTDOWN_ENABLED` implies lifecycle tracking and additionally:

1. stops accepting new FVG stream events;
2. drains events already accepted into the in-memory delivery queue;
3. waits for the stream task to exit;
4. uses the remaining deadline for one final persistent FVG outbox pass.

The default 25-second deadline leaves shutdown overhead after the drain before
the process manager's existing stop budget is exhausted.

## PTB lifecycle placement

The bounded drain runs in `ApplicationBuilder.post_stop`.

At that point polling and JobQueue execution have stopped, so no new scheduled
FVG/funding job should begin. `Application.shutdown` has not run yet, so the
Telegram bot is still available for the final delivery pass.

When both flags are disabled, the previous `post_shutdown` cleanup path remains
in use.

## Persistent state

Lifecycle state is stored in the existing FVG SQLite database:

- `runtime_lifecycle_state` contains one current process instance;
- `runtime_lifecycle_events` contains bounded transition history.

Recorded states include:

- `starting`;
- `running`;
- `stopping`;
- `stopped`;
- `failed`;
- `shutdown_timeout`;
- `interrupted` for an active previous instance replaced by a new startup.

The state includes PID, instance UUID, timestamps, shutdown deadline/outcome,
last phase, error class/message and structured details.

A new process marks a previous `starting`, `running` or `stopping` instance as
`interrupted`. This is evidence of an unclean previous exit; it does not trigger
an automatic restart or restore.

## Deadline behavior

The coordinator uses one monotonic deadline for all shutdown work:

1. stop the process watchdog;
2. allocate 75% of the then-remaining budget to the stream queue and stream task;
3. allocate all final remaining time to the persistent outbox pass.

Each await is wrapped independently by the same deadline. A component cannot
extend total shutdown indefinitely by ignoring its own timeout argument.

Outcomes:

- `clean`: all requested cleanup completed without timeout or component error;
- `component_error`: cleanup continued, but at least one component raised;
- `timeout`: at least one component or the global budget expired.

A stream task force-cancelled after its drain budget is reported as a timeout,
not as a clean shutdown.

## Delivery semantics

Events accepted before shutdown are drained through the normal
`FvgAlertService.deliver` path. Events produced after `stop_accepting()` are not
added to the in-memory queue and increment
`delivery_events_rejected_during_shutdown`. REST/WebSocket recovery can discover
those events again after the next startup.

The final persistent outbox pass uses the existing `retry_pending` method and
its delivery lock. For Outbox V2, existing atomic claims, attempt limits,
expiration and ambiguous-delivery safeguards remain authoritative.

Graceful shutdown does not promise that every Telegram request completes before
the deadline. It promises bounded shutdown and a persistent record of whether
the drain was clean, failed or timed out.

## Rollout

1. Deploy with both flags `false`.
2. Enable only `RUNTIME_LIFECYCLE_ENABLED=true`.
3. Restart once and verify `starting -> running -> stopping -> stopped` events.
4. Verify normal service stop remains within the process-manager stop budget.
5. Enable `GRACEFUL_SHUTDOWN_ENABLED=true`.
6. Stop during a controlled FVG queue load and inspect:
   - `runtime_shutdown_outcome`;
   - `runtime_shutdown_duration_seconds`;
   - `runtime_shutdown_timed_out`;
   - lifecycle events and queue/outbox details.
7. Keep the 25-second default until production evidence supports another value.

## Rollback

Set both flags to `false` and restart. Existing lifecycle tables remain inert and
are included in the normal SQLite backup. No destructive migration is required.

## Not included

- replacement of the existing stale-candle `os._exit` watchdog behavior;
- automatic restart decisions based on lifecycle history;
- automatic restore or replay of rejected in-memory events;
- admin lifecycle controls;
- graceful draining of arbitrary third-party tasks outside the registered FVG
  stream and persistent outbox paths.
