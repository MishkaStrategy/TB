# Audit verification gates — 2026-08-11

The reliability/performance audit is accepted only when the exact final pull-request head satisfies all of the following:

- dependency audit succeeds with no known vulnerabilities in pinned/runtime requirements;
- Python sources compile successfully;
- the complete unit suite passes, including SQLite connection hygiene, WAL initialization, funding transaction, Mini App event-loop, market-overview and Telegram activity-registry regressions;
- Mini App frontend TypeScript typecheck and production build pass;
- candidate VDS tests run without production credentials or feature flags;
- backup contract tests pass;
- bounded notification soak completes within configured time/memory limits with an empty remaining outbox;
- production systemd units render and pass `systemd-analyze verify` on `[self-hosted, Linux]`;
- exact runner-selector policy and dependency runner policy pass;
- a second CI + Release audit run succeeds on the same final commit SHA before merge;
- review has no blocking requested changes or unresolved threads;
- release publication creates a new immutable tag from the reviewed merge commit and never moves an existing tag.

Production VDS deployment is explicitly outside this audit PR and remains a separate guarded operation using the exact published release SHA.
