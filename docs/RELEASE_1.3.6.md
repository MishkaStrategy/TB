# FVG Alert Bot 1.3.6

`1.3.6` is an immutable patch release that promotes the audited Telegram Mini App trading dashboard and its compatible read-only market overview backend.

## Included in 1.3.6

- the new dark `TradingApp` dashboard with Overview, FVG, Funding, Notifications, Settings and protected Admin screens;
- five-tab bottom navigation optimized for Telegram mobile WebView;
- exchange-aware `priceChange24hPct` values with `—` for unavailable market data;
- authenticated `GET /api/mini-app/market-overview` with bounded cache and per-exchange failure isolation;
- the existing settings, admin challenge, Bot API-only authentication and same-origin security contracts;
- production frontend builds with `VITE_MOCK_MODE=false` and no source maps;
- synchronized release metadata on `VERSION=1.3.6`.

## Production safety

- `/etc/fvg-alert-bot.env`, `/var/lib/fvg-alert-bot`, SQLite databases and user settings are preserved;
- Telegram authentication uses only the BotFather `TELEGRAM_TOKEN` and validated raw `initData`;
- API ID/hash, Telethon, Pyrogram, phone login and user sessions are not used;
- operational feature flags are not enabled automatically;
- Xray, SNI routing, UFW, port 8080 and BotFather configuration are outside the release update;
- the existing Telegram chat UI remains available independently of the Mini App.

## Release archive contract

The release workflow creates:

- `fvg-alert-bot-1.3.6.tar.gz`;
- `fvg-alert-bot-1.3.6.tar.gz.sha256`.

The archive includes the Mini App frontend/backend sources and excludes `.env`, SQLite, runtime data, `node_modules`, frontend `dist`, Python caches and AppleDouble metadata.

## Verification

Before publication CI verifies:

- dependency audit, Python compilation and the full unit suite;
- Mini App authentication, settings, admin and market-overview regressions;
- frontend typecheck and production build;
- candidate environment isolation and Bot API-only deployment checks;
- strict backup manifest/checksum verification;
- bounded `500 × 10` notification soak with an empty outbox;
- systemd unit rendering and immutable release metadata.

## Publication and rollback

`v1.3.6` may be created only from the two-parent merge commit on `main` after all required checks pass. Existing tags, including `v1.3.5`, are never moved. Production deployment uses the guarded Bot API-only updater, which creates a backup, performs an atomic switch and restores the prior release automatically on failure.
