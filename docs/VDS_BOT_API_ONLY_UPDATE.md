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

The first `v1.3.0` production attempt stopped during candidate tests before `systemctl stop` and atomic switch. Production remained on `1.2.0`; rollback was not required and runtime SQLite data were not changed.

The confirmed cause was production environment contamination: a stale `MAX_SYMBOLS_PER_USER=20` override affected candidate unit tests. Releases `1.3.1` and later isolate candidate tests with `env -i`, retain a complete test log and cap the effective FVG instrument limit at 10.

`v1.3.4` is the current audited deployment target. It restores multi-timeframe confirmed FVG from a `15m`-only exchange data source, keeps pre-FVG and `1m` disabled, fixes the Gate candle adapter and makes empty multi-exchange sources observable. Telegram Mini App PR #53 is excluded.

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
sudo grep -E '^(MAX_ACTIVE_SYMBOLS|MAX_SYMBOLS_PER_USER)=' /etc/fvg-alert-bot.env || true
```

Do not print `TELEGRAM_TOKEN` or other secret values.

## Update to 1.3.4

Use the published tag and exact audited commit from the production deployment issue:

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.4 \
  EXPECTED_VERSION=1.3.4 \
  EXPECTED_COMMIT=<audited-full-commit-sha> \
  bash scripts/update_vds_bot_api_only.sh
```

Do not deploy a moving integration branch. The wrapper first verifies Bot API-only credentials and then delegates to `scripts/update_vds.sh`, preserving its backup, clean candidate environment, full unit suite, atomic switch, rollback, systemd, version, commit and SQLite checks.

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

## FVG 1.3.4 production contract

- the exchange data source is always closed `15m` candles;
- confirmed target timeframes are `15m`, `1h`, `4h`, `1d`;
- `1h`, `4h`, `1d` are aggregated locally from `15m` on UTC boundaries;
- no `1m` data and no pre-FVG job/UI are active;
- one source download is shared by all due target timeframes of one `exchange + symbol`;
- `MAX_ACTIVE_SYMBOLS` counts unique instruments, not timeframe rows;
- a completely empty candle source for an active multi-exchange market is an operational failure and must be visible in journal/health counters;
- a failure on one market must not stop processing of the remaining markets.

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

- installed version is `1.3.4`;
- installed commit matches the audited release SHA;
- service is `active` and `enabled`;
- `NRestarts` does not grow during observation;
- both SQLite checks return `ok`;
- no startup traceback or Telegram polling conflict appears;
- no Telegram App or user-session credentials are present in `/etc/fvg-alert-bot.env`.

## 1.3.4 smoke checks

- FVG instruments allow exchange, pair and `15m/1h/4h/1d` selection;
- pre-FVG is absent from UI and commands;
- verify existing instrument timeframe selections because the previous `15m`-only compatibility layer could persist normalized `15m` settings after a write;
- configure at least one non-BTC instrument on `15m` and confirm it remains configured after reopening the menu;
- configure or verify at least one instrument on a non-Bitunix exchange;
- after a 15-minute control point, inspect journal for multi-exchange source failures;
- `No closed 15m FVG candles returned for <exchange> <symbol>` must be treated as a visible data-source failure, not as proof that no FVG exists;
- `⚙️ Операции` shows restart circuit-breaker status;
- `⚙️ Операции` shows read-only FVG archive status;
- Telegram Mini App is not deployed or required;
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
