# Manual administrator restart

The Telegram administrator panel provides an explicitly confirmed bot restart.
This path is separate from the automatic stale-candle restart watchdog and its
persistent circuit breaker.

## Restart sequence

A confirmed manual restart follows this order:

1. verify the existing `is_admin` authorization check;
2. require the explicit `admin:restart_confirm` callback;
3. await the Telegram confirmation message so the administrator sees that
   shutdown is starting;
4. call `operations.process_restart.request_sigterm_restart()`;
5. mark the process as a deliberate graceful-restart request and send SIGTERM to
   the current process;
6. let python-telegram-bot handle SIGTERM through its normal shutdown path;
7. run registered PTB `post_stop` / `post_shutdown` hooks;
8. after `run_polling()` returns, `bot.main()` observes the graceful-restart
   marker and exits non-zero;
9. the production systemd unit restarts the service according to its existing
   restart policy.

The admin handler must never call `os._exit()` for a manual restart.

## Graceful shutdown interaction

When the runtime lifecycle/graceful shutdown features are enabled, PTB
`post_stop` delegates to the existing runtime coordinator. That coordinator can
stop accepting new FVG work and perform the configured bounded delivery drain
before process exit.

When optional graceful lifecycle features are disabled, SIGTERM still uses
PTB's normal shutdown hooks instead of bypassing them with a hard process exit.

## Failure behavior

If the process cannot request SIGTERM (for example `os.kill()` returns an
`OSError`), `request_sigterm_restart()` clears its marker and re-raises the
error. The Telegram admin handler reports that failure instead of falling back
to `os._exit()`.

A failed manual restart request therefore does not pretend that a restart is in
progress and does not deliberately kill the process through a second path.

## Circuit-breaker boundary

`ProcessRestartGuard` remains scoped to the automatic stale-candle watchdog as
documented in `PROCESS_RESTART_CIRCUIT_BREAKER.md`. A deliberate administrator
restart is not added to the watchdog request quota/cooldown by this change.

Changing that governance boundary would require a separate design decision.

## Verification

Regression tests must prove:

- non-admin users cannot trigger the callback;
- the confirmation message completes before SIGTERM is requested;
- `request_sigterm_restart()` is called exactly once;
- `os._exit()` is not called by the admin path;
- an `OSError` from the SIGTERM request is reported to the administrator;
- existing process-restart and PTB lifecycle tests remain green.

Related issue: #128.
