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

`v1.3.3` is the current audited deployment target. It also prevents macOS BSD tar from adding AppleDouble `._*` metadata files to verified backup archives. Telegram Mini App PR #53 is excluded.

## Preflight

```bash
sudo test -r /etc/fvg-alert-bot.env
sudo systemctl is-active fvg-alert-bot
sudo systemctl is-enabled fvg-alert-bot
cd /root/TB
git status --short
```

`git status --short` must be empty. Also verify both runtime SQLite databases with `PRAGMA quick_check`, record the current `NRestarts`, and confirm at least 1 GB free space plus 5000 inode on `/opt`.

## Update to 1.3.3

Use the published tag and exact audited commit from the production deployment issue:

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.3 \
  EXPECTED_VERSION=1.3.3 \
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

- installed version is `1.3.3`;
- installed commit matches the audited release SHA;
- service is `active` and `enabled`;
- `NRestarts` does not grow during observation;
- both SQLite checks return `ok`;
- no startup traceback or Telegram polling conflict appears;
- no Telegram App or user-session credentials are present in `/etc/fvg-alert-bot.env`.

## 1.3.3 smoke checks

- FVG instruments allow exchange, pair and `15m/1h/4h/1d` selection;
- existing schema-v2 FVG settings appear as Bitunix `15m` without losing filters;
- legacy settings above 10 instruments are preserved but cannot grow;
- `⚙️ Операции` shows restart circuit-breaker status;
- `⚙️ Операции` shows read-only FVG archive status;
- Telegram Mini App is not deployed or required;
- operational feature flags remain default-off for the first launch.

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
