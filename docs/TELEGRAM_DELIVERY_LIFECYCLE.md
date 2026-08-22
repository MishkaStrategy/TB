# Telegram delivery lifecycle

This document defines the delivery-safety contract for Telegram recipients.

## States

The persistent delivery registry keeps Telegram reachability separate from user access settings.

- `active` — delivery is allowed.
- `temporarily_unavailable` — a retryable transport or rate-limit condition; delivery remains eligible for bounded retry.
- `blocked` — Telegram reported that the user blocked the bot; delivery is suppressed.
- `deactivated` — Telegram reported a deleted/deactivated account; delivery is suppressed.
- `suspended` — a permanent/unknown forbidden state that must fail closed; delivery is suppressed.

`rate_limited` is represented by the Telegram error code while the persistent reachability state remains `temporarily_unavailable` so normal retry semantics are preserved.

## Final-unavailable invariant

Blocked/deactivated/suspended suppression is mandatory product behavior, not an optional rollout flag.

When Telegram classifies a chat as final-unavailable:

1. the reachability state is persisted;
2. future FVG/funding delivery is filtered before Telegram is called where possible;
3. legacy pending `outbox` rows for that chat are removed;
4. Outbox V2 rows in `pending` or `retry_scheduled` are retained as audit evidence but moved to `cancelled`;
5. an item already under a processing lease is not stolen by the registry; its worker owns the terminal outcome;
6. signal/history records are not deleted.

This prevents retry churn and prevents notifications accumulated during an unavailable period from being replayed after recovery.

## Recovery

A fresh inbound user interaction restores the delivery profile to `active`; `/start` is the canonical recovery action. The interaction handler runs before command handlers, so `/start` restores reachability before the welcome/menu response is sent.

Before the profile is changed back to `active`, the registry performs one more backlog cancellation pass. This is required for databases produced by older versions where Outbox V2 rows could survive a blocked period.

Recovery never changes FVG/funding preferences or historical signal data.

## Retryable conditions

Temporary network failures and Telegram `RetryAfter` do not discard backlog. They remain bounded by the existing retry/backoff policy. A later successful send returns the reachability state to `active`.

## Operational notes

- `USER_BLOCK_STATUS_ENABLED` is a legacy rollout variable and is no longer a supported switch for disabling final-unavailable suppression.
- `DELIVERY_STATUS_TRACKING_ENABLED` may still be used for additional diagnostics, but blocked/deactivated/suspended safety does not depend on it.
- Outbox V2 remains separately controlled by its rollout settings; the final-unavailable contract applies to both legacy and V2 queues whenever their tables exist.

Related issue: #117.
