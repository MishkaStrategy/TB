# FVG Alert Bot 1.3.9

`1.3.9` is the immutable visual patch for the Telegram Mini App approved by the product owner on 2026-08-19. It preserves the trading, Telegram, storage and security contracts of `1.3.8` while replacing the previous blue/cyan presentation with the selected dark/white minimalist TB design.

## Telegram Mini App

- near-black page background with neutral charcoal content surfaces;
- white primary hierarchy and cool-gray secondary text;
- green/red reserved for market and status semantics;
- thin neutral borders and compact rounded cards without neon/decorative glow;
- Overview uses two FVG/Funding module cards followed by individual instrument cards;
- instrument rows keep symbol, exchange, selected timeframes, active/paused text, a neutral decorative sparkline and exchange-aware 24h price change in one scan;
- unavailable market data remains `—`, never a fabricated `0%`;
- bottom navigation remains five destinations with Telegram safe-area handling and a neutral white active marker;
- existing accessibility layer remains active: direct controls retain practical mobile targets, selection/focus semantics remain explicit, and reduced-motion is respected.

The decorative sparklines are derived only from the already loaded direction of `priceChange24hPct`; they do not add exchange requests, chart libraries or a second market-data pipeline.

## Compatibility and security

Unchanged contracts include:

- Telegram Bot API token-only operation;
- raw Telegram Mini App `initData` HMAC authentication;
- `GET/PUT /api/mini-app/settings`;
- `GET /api/mini-app/market-overview`;
- FVG exchange + symbol + timeframe schema and filters;
- Funding interval/threshold/direction/exchange constraints;
- RU/EN and compact/detailed settings;
- server-side admin/access checks and one-time admin confirmation challenges;
- backup/restart fail-closed behavior;
- external Web App Menu Button preservation introduced in `1.3.7`.

Production env, SQLite/runtime state, BotFather settings, Xray, Nginx and external network ports are not changed by release publication.

## Verification gate

The reviewed release commit must pass:

- TypeScript typecheck;
- production Mini App build with `VITE_MOCK_MODE=false`;
- Mini App design/navigation/UI regressions;
- dependency audit and Python compilation;
- complete Python unit suite;
- candidate environment isolation;
- backup contracts and bounded notification soak;
- Linux systemd verification and full Release audit;
- mobile browser smoke at approximately 390px for Overview, FVG, Funding, Alerts and Settings;
- horizontal-overflow check and final diff/security/contract review.

## Release safety

`v1.3.9` is created only from the reviewed two-parent merge commit on `main`. Existing `v1.3.8` and earlier tags/assets remain immutable and are never moved or overwritten.

The release workflow creates:

- `fvg-alert-bot-1.3.9.tar.gz`;
- `fvg-alert-bot-1.3.9.tar.gz.sha256`.

Production deployment remains a separate guarded operation using the exact published release SHA.
