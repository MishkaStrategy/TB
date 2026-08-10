# FVG Alert Bot 1.3.7

`1.3.7` is an immutable reliability and performance patch release produced by a post-1.3.6 project audit. It preserves Telegram/Mini App behavior while removing avoidable blocking I/O, tightening SQLite lifecycle handling, isolating malformed market rows, and enforcing the project runner policy.

## Included in 1.3.7

### Runtime reliability and performance

- `FundingExchangeStore` closes every context-managed SQLite connection and configures WAL once during store initialization instead of on every read;
- funding exchange selection replacement and crossing-state reset are committed atomically;
- Telegram update activity tracking reuses one process-wide `UserActivityRegistry` instead of rebuilding it for every update;
- Mini App settings and synchronous admin storage operations run outside the aiohttp event-loop thread;
- Mini App application state uses typed `aiohttp.web.AppKey` keys, removing `NotAppKeyWarning` noise;
- malformed persisted instruments or malformed exchange ticker rows no longer make the entire market overview unavailable.

### Telegram Mini App compatibility

The Telegram Mini App API paths, authenticated settings contract, market overview schema, safe loopback/default-off backend posture and existing Telegram UI remain compatible with `1.3.6`. This patch changes execution and failure isolation, not the user-facing contract.

### CI and release safety

- self-hosted workflow routing is restricted to the documented exact selector allowlist;
- fast checks use `[self-hosted, fast]`, Linux/systemd and release checks use `[self-hosted, Linux]`;
- release publication explicitly preflights `sha256sum`, `tar` and `gh` on the Linux capability runner;
- runner selector policy is enforced both as a dedicated workflow and in the Python unit suite;
- GitHub-hosted runners are no longer used where an approved self-hosted capability exists.

## Compatibility and production safety

- no Telegram commands, FVG/funding contracts, Mini App API paths, schemas, BotFather settings or production environment values are changed;
- `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot`, SQLite databases and user settings are preserved;
- Mini App remains opt-in and loopback-only by default (`MINI_APP_BACKEND_ENABLED=false`, `127.0.0.1:18080`);
- public access remains fail-closed unless explicitly enabled;
- existing immutable tags, including `v1.3.6`, are never moved.

## Verification contract

Before publication, CI must verify the exact release commit with dependency audit, Python compilation, the full unit suite, Mini App backend regressions, frontend typecheck/build, runner selector policy, candidate environment isolation, backup checks, bounded notification soak and Linux systemd verification. A second exact-SHA CI run is required before merge.

## Release archive

The release workflow creates:

- `fvg-alert-bot-1.3.7.tar.gz`;
- `fvg-alert-bot-1.3.7.tar.gz.sha256`.

`v1.3.7` may be created only from the reviewed merge commit on `main`. Production deployment remains a separate guarded operation using the exact audited release SHA.
