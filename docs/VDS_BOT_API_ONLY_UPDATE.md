# VDS update in Telegram Bot API-only mode

This deployment mode uses only a BotFather token. It does not use a Telegram App, `API_ID`, `API_HASH`, Telethon, Pyrogram, a phone-number login, or a user-session string.

## Required Telegram settings

The production environment file is `/etc/fvg-alert-bot.env`.

Required:

```dotenv
TELEGRAM_TOKEN=<BotFather token>
ADMIN_TELEGRAM_IDS=<numeric Telegram ID>
ALLOWED_TELEGRAM_IDS=<numeric Telegram ID>
```

Forbidden in Bot API-only mode when non-empty:

```text
TELEGRAM_API_ID
TELEGRAM_API_HASH
API_ID
API_HASH
TELETHON_SESSION
PYROGRAM_SESSION
STRING_SESSION
```

The update wrapper validates this without printing the bot token.

## Release history relevant to deployment

`v1.3.5` remains the currently deployed immutable production release at commit `e9fdaae934a083b1f1bd054d6f0c8fff04776581`. It must not be moved or rewritten.

`v1.3.6` is the next immutable patch release. It publishes the audited dark trading dashboard and its compatible authenticated market-overview backend. The existing Telegram UI remains the primary fallback interface. Release publication does not modify production env, SQLite, runtime state, BotFather settings, Xray, or port 443.

## Preflight

```bash
sudo test -r /etc/fvg-alert-bot.env
sudo systemctl is-active fvg-alert-bot
sudo systemctl is-enabled fvg-alert-bot
cd /root/TB
git status --short
```

`git status --short` must be empty. Also verify both runtime SQLite databases with `PRAGMA quick_check`, record the current `NRestarts`, and confirm at least 1 GB free space plus 5000 inode on `/opt`.

Before changing production, record the currently installed code and active configuration:

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
sudo grep -E '^(MAX_ACTIVE_SYMBOLS|MAX_SYMBOLS_PER_USER|MINI_APP_BACKEND_ENABLED|MINI_APP_BACKEND_HOST|MINI_APP_BACKEND_PORT|MINI_APP_ALLOWED_ORIGINS)=' /etc/fvg-alert-bot.env || true
```

Do not print `TELEGRAM_TOKEN` or other secret values.

## Update to 1.3.6

Deploy only the published immutable tag and exact audited commit from the deployment issue:

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.6 \
  EXPECTED_VERSION=1.3.6 \
  EXPECTED_COMMIT=<audited-full-commit-sha> \
  bash scripts/update_vds_bot_api_only.sh
```

Do not deploy a moving integration branch. The wrapper first verifies Bot API-only credentials and then delegates to `scripts/update_vds.sh`, preserving its backup, clean candidate environment, full unit suite, atomic switch, rollback, systemd, version, commit and SQLite checks.

The release workflow does not execute this command and does not deploy production automatically.

## Candidate test guarantees

Before the production process is stopped:

- candidate tests run in a clean allowlisted environment;
- production `/etc/fvg-alert-bot.env` is not copied into staging;
- production Telegram credentials and feature flags are not inherited;
- `MAX_SYMBOLS_PER_USER` is fixed to the release contract value 10 for tests;
- stdout/stderr are saved under `/var/log/fvg-alert-bot/candidate-tests-<version>-<UTC>.log`;
- the original child exit code is preserved through `tee`;
- a failing suite exits before backup-after-stop and atomic switch.

The installed service continues to read the external production file through systemd `EnvironmentFile=/etc/fvg-alert-bot.env`.

## Backup portability

The backup script excludes existing Finder metadata (`._*` and `.DS_Store`) from the runtime snapshot and runs tar with `COPYFILE_DISABLE=1`. This prevents macOS from synthesizing unmanifested AppleDouble members after the manifest is built. Archive verification remains strict for all ordinary unmanifested members.

## FVG 1.3.6 production contract

- the exchange data source is always closed `15m` candles;
- confirmed target timeframes are `15m`, `1h`, `4h`, `1d`;
- `1h`, `4h`, `1d` are aggregated locally from `15m` on UTC boundaries;
- no `1m` data and no pre-FVG job/UI are active;
- one source download is shared by all due target timeframes of one `exchange + symbol`;
- `MAX_ACTIVE_SYMBOLS` counts unique instruments, not timeframe rows;
- a completely empty candle source for an active multi-exchange market is an operational failure and must be visible in journal/health counters;
- a failure on one market must not stop processing of the remaining markets.

## Telegram Mini App release contract

The official `v1.3.6` source archive contains both `mini_app_backend/` and `telegram-mini-app/`, plus the backend lifecycle wiring in `bot.py`.

The frontend entrypoint mounts `TradingApp`, provides five bottom tabs and loads exchange-aware `priceChange24hPct` through authenticated `GET /api/mini-app/market-overview`. Unavailable market values remain `null` in the API and render as `—` rather than `0%`.

Production-safe defaults remain:

```dotenv
MINI_APP_BACKEND_ENABLED=false
MINI_APP_BACKEND_HOST=127.0.0.1
MINI_APP_BACKEND_PORT=18080
MINI_APP_AUTH_MAX_AGE_SECONDS=3600
MINI_APP_ALLOWED_ORIGINS=https://tbbot.mstrategy.com.ru
```

These values are deployment examples only. Release publication does not write them to `/etc/fvg-alert-bot.env` and does not enable the backend automatically.

The backend validates raw Telegram `initData` using the BotFather `TELEGRAM_TOKEN` and HMAC-SHA-256. Runtime code is not hard-wired to `tbbot.mstrategy.com.ru`; the domain is supplied through the origin allowlist. The frontend uses same-origin `/api/` requests. Production builds use `VITE_MOCK_MODE=false` and publish no source maps.

The public HTTPS reverse-proxy/TLS setup, BotFather Mini App URL/menu button, and `MINI_APP_BACKEND_ENABLED=true` are a separate controlled activation stage after the audited release has been deployed. Xray and external port 443 are outside this release task.

## Post-deploy

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
systemctl show fvg-alert-bot -p NRestarts -p ExecMainStatus -p MemoryCurrent -p MemoryMax
journalctl -u fvg-alert-bot -n 150 --no-pager

sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
```

Expected results:

- installed version is `1.3.6`;
- installed commit matches the audited release SHA;
- service is `active` and `enabled`;
- `NRestarts` does not grow during observation;
- both SQLite checks return `ok`;
- no startup traceback or Telegram polling conflict appears;
- no Telegram App or user-session credentials are present in `/etc/fvg-alert-bot.env`;
- Mini App backend remains disabled unless the deployment owner explicitly enabled it in a separate step.

## 1.3.6 smoke checks

- FVG instruments allow exchange, pair and `15m/1h/4h/1d` selection;
- pre-FVG is absent from UI and commands;
- configure at least one non-BTC instrument on `15m` and confirm it remains configured after reopening the menu;
- configure or verify at least one instrument on a non-Bitunix exchange;
- after a 15-minute control point, inspect journal for multi-exchange source failures;
- `No closed 15m FVG candles returned for <exchange> <symbol>` remains a visible data-source failure;
- `⚙️ Операции` shows restart circuit-breaker and read-only FVG archive status;
- Telegram UI remains fully usable with the Mini App backend disabled;
- operational feature flags remain default-off for the first launch.

A market does not need to produce an FVG on every control point. The production smoke validates that every configured market is actually scanned and that failures are visible; it must not manufacture test alerts.

## Secret-safe credential check

This command prints only key names, never values:

```bash
sudo awk -F= '
  /^[[:space:]]*(export[[:space:]]+)?(TELEGRAM_API_ID|TELEGRAM_API_HASH|API_ID|API_HASH|TELETHON_SESSION|PYROGRAM_SESSION|STRING_SESSION)[[:space:]]*=/ {
    key=$1
    sub(/^[[:space:]]*export[[:space:]]+/, "", key)
    gsub(/[[:space:]]/, "", key)
    print key
  }
' /etc/fvg-alert-bot.env
```

For a clean Bot API-only configuration, it should print nothing.
