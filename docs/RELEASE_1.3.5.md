# FVG Alert Bot 1.3.5

`1.3.5` is an immutable patch release that publishes the Telegram Mini App already merged into `main` after the official `v1.3.4` release.

## Root cause

`v1.3.4` was created at commit `f568f2282435099e2b12718de45e4bbe802a0b79` before Telegram Mini App PR #53 was merged. The Mini App integration later reached `main`, but `VERSION` remained `1.3.4`. The release workflow therefore attempted to publish an already-existing immutable tag from different source content and correctly failed.

The `v1.3.4` tag is not changed by this release.

## Included in 1.3.5

- `mini_app_backend/**` is included in the official source tree and release archive for the first time;
- `telegram-mini-app/**` is included in the official source tree and release archive for the first time;
- `bot.py` contains the Mini App backend lifecycle wiring;
- Telegram `initData` is verified with HMAC-SHA-256 using the BotFather `TELEGRAM_TOKEN`;
- frontend production requests use same-origin `/api/`;
- release metadata is synchronized on `VERSION=1.3.5`;
- immutable tag handling is idempotent when `v1.3.5` already points to the current release commit and fails closed if the tag points elsewhere;
- the release archive and SHA-256 checksum are audited before publication.

## Production safety

The Mini App backend remains disabled by default:

```dotenv
MINI_APP_BACKEND_ENABLED=false
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru
```

The domain is a deployment example and allowlist value only; runtime code is not hard-wired to it.

Release publication does **not**:

- deploy to the production VDS;
- change `/etc/fvg-alert-bot.env`;
- change SQLite or runtime-state under `/var/lib/fvg-alert-bot`;
- enable `MINI_APP_BACKEND_ENABLED`;
- enable any operational feature flag;
- change BotFather Mini App/menu settings;
- change Xray or external port 443.

The existing Telegram UI remains the primary and fallback interface whether or not the Mini App is later activated.

## Telegram credentials

Only the Bot API token from BotFather is used:

```dotenv
TELEGRAM_TOKEN=<BotFather token>
```

`API_ID`, `API_HASH`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, Telethon, Pyrogram, phone login and user-session strings are not part of the release runtime contract.

## Release archive contract

The release workflow creates:

- `fvg-alert-bot-1.3.5.tar.gz`;
- `fvg-alert-bot-1.3.5.tar.gz.sha256`.

The archive must contain at least:

- `mini_app_backend/service.py`;
- `mini_app_backend/auth.py`;
- `telegram-mini-app/package.json`;
- `telegram-mini-app/src/api.ts`;
- `bot.py`.

The archive must not contain production `.env`, SQLite files, `node_modules`, frontend `dist`, Python cache directories, AppleDouble metadata, `.DS_Store`, secrets, or runtime data.

## Release audit

Before merge, CI verifies:

- Python compilation and full unit suite;
- Mini App auth/service/web/runtime/admin regressions;
- release metadata consistency and the `1.3.5` regression contract;
- Bot API-only updater contract and candidate test isolation;
- dependency audit without masking a failing exit code;
- shell syntax;
- backup manifest/checksum binding and macOS metadata exclusion;
- bounded `500 × 10` soak with 500 events, 5,000 persisted/sent deliveries, empty outbox and no failures;
- production systemd rendering with `systemd-analyze verify`;
- Node.js install, frontend typecheck and production build with `VITE_MOCK_MODE=false`;
- same-origin API path, no credential identifiers and no source maps in the production frontend bundle;
- unchanged `v1.3.4` commit and `VERSION` content.

## Publication and rollback

`v1.3.5` may be created only from the two-parent merge commit on `main` after the release PR has passed all required checks. Existing tags are never moved and release assets are never clobbered.

Before any future deployment, production continues running the official `v1.3.4`. After a separately approved deployment, `scripts/update_vds_bot_api_only.sh` preserves the previous release and creates the normal runtime backup so rollback remains available.

Mini App activation for `https://tbbot.mstrategy.com.ru` is a separate controlled deployment stage after the audited `v1.3.5` release is installed.
