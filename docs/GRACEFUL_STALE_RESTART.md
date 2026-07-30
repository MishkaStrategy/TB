# Graceful stale-process restart

The existing FVG process watchdog requests a restart after prolonged active-symbol
WebSocket candle silence. Historically it called `os._exit(1)`, which bypassed
PTB shutdown hooks and any bounded delivery drain.

This stage adds an opt-in SIGTERM path while preserving the immediate-exit
default.

## Configuration

```env
FVG_PROCESS_RESTART_STALE_SECONDS=1000
FVG_PROCESS_GRACEFUL_RESTART_ENABLED=false
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS=25
```

When `FVG_PROCESS_GRACEFUL_RESTART_ENABLED=true`, effective
`GRACEFUL_SHUTDOWN_ENABLED` is also true even if its environment value is
`false`. This guarantees that the restart uses the lifecycle/post-stop stream
and persistent outbox drain introduced by the graceful-shutdown stage.

## Restart sequence

After the configured candle-silence threshold:

1. the watchdog writes the restart reason, mode, timestamp and measured silence
   to runtime health;
2. it increments restart-request counters;
3. it sets a process-local, thread-safe restart marker;
4. it sends `SIGTERM` to the current PID;
5. PTB stops polling and JobQueue execution;
6. PTB `post_stop` performs the bounded watchdog/stream/outbox cleanup;
7. `Application.shutdown` completes;
8. `bot.main` sees the restart marker and exits with code `1`;
9. the production systemd unit uses `Restart=on-failure` and starts a new
   process.

The non-zero exit is deliberately delayed until after PTB cleanup. External
`SIGTERM` or `systemctl stop` does not set the marker, so it remains a clean exit
and is not restarted by `Restart=on-failure`.

## One-shot behavior

The watchdog uses a restart latch:

- after one successful restart request, later evaluations do not send another
  signal;
- the watchdog task stops its evaluation loop after the request;
- if `os.kill` fails, the marker and latch are cleared so a later evaluation can
  retry;
- signal-request failures increment `process_restart_request_failures` and store
  `process_restart_request_error`.

This prevents repeated SIGTERM requests while the event loop is already
shutting down.

## Health fields

The request records:

- `process_restart_requested_at`;
- `process_restart_mode` (`sigterm_then_failure_exit` or `immediate_exit`);
- `process_restart_silence_seconds`;
- `process_restart_request_error`, when the request fails;
- `stale_process_restart_requests`;
- the existing `stale_process_restarts` counter for backward compatibility.

The legacy counter represents watchdog restart requests, including an attempted
request whose callback subsequently failed. Use
`process_restart_request_failures` to distinguish those failures.

## Default and rollback

With the flag `false`, the watchdog still selects `os._exit(1)` and behaves as
before.

Rollback requires only:

```env
FVG_PROCESS_GRACEFUL_RESTART_ENABLED=false
```

and a restart. No schema migration is involved.

## Rollout

1. Deploy with the flag `false`.
2. Confirm graceful shutdown/lifecycle stages are stable on normal service stop.
3. Enable `FVG_PROCESS_GRACEFUL_RESTART_ENABLED=true`.
4. In a controlled environment, inject a stale watchdog clock or block market
   candle updates.
5. Confirm lifecycle shows a clean bounded stop followed by a new instance.
6. Confirm systemd reports the previous process exit code as non-zero and the
   service restarts under `Restart=on-failure`.
7. Verify no duplicate restart request is recorded for the same process.

## Not included

- restart loops or rate-limit policy beyond systemd's existing settings;
- automatic rollback after repeated stale restarts;
- admin restart controls;
- changing the stale threshold default;
- replacing systemd as the process supervisor.
