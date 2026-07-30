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

## Preflight

```bash
sudo test -r /etc/fvg-alert-bot.env
sudo systemctl is-active fvg-alert-bot
sudo systemctl is-enabled fvg-alert-bot
cd /root/TB
git status --short
```

`git status --short` must be empty.

## Update to 1.3.0

Use the published tag and exact audited commit:

```bash
cd /root/TB
git fetch origin --tags --prune
git checkout main
git pull --ff-only origin main

sudo env \
  TARGET_REF=v1.3.0 \
  EXPECTED_VERSION=1.3.0 \
  EXPECTED_COMMIT=<audited-full-commit-sha> \
  bash scripts/update_vds_bot_api_only.sh
```

Before the tag exists, do not deploy a moving integration branch to production. The wrapper first verifies Bot API-only credentials and then delegates to `scripts/update_vds.sh`, preserving its backup, candidate build, unit tests, atomic switch, rollback, systemd, version, commit, and SQLite checks.

## Post-deploy

```bash
cat /opt/fvg-alert-bot/VERSION
cat /opt/fvg-alert-bot/BUILD_COMMIT
systemctl is-active fvg-alert-bot
systemctl is-enabled fvg-alert-bot
journalctl -u fvg-alert-bot -n 150 --no-pager

sqlite3 /var/lib/fvg-alert-bot/fvg_event_store.sqlite3 'PRAGMA quick_check;'
sqlite3 /var/lib/fvg-alert-bot/funding_alerts.sqlite3 'PRAGMA quick_check;'
```

Expected results:

- installed version is `1.3.0`;
- installed commit matches the audited release SHA;
- service is `active` and `enabled`;
- both SQLite checks return `ok`;
- no startup traceback appears in the journal;
- no Telegram App or user-session credentials are present in `/etc/fvg-alert-bot.env`.

## 1.3.0 smoke checks

- FVG instruments allow exchange, pair and `15m/1h/4h/1d` selection;
- existing schema-v2 FVG settings appear as Bitunix `15m` without losing filters;
- `⚙️ Операции` shows restart circuit-breaker status;
- `⚙️ Операции` shows read-only FVG archive status;
- Telegram Mini App is not deployed or required.

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
