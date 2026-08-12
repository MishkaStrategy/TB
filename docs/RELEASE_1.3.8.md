# FVG Alert Bot 1.3.8

`1.3.8` is an immutable UI/UX audit patch built directly from the canonical `1.3.7` main branch. It preserves the Telegram Mini App Menu Button hotfix while improving the Telegram chat interface and the Mini App visual/accessibility layer.

## Telegram interface

- persistent reply keyboard follows the selected RU/EN language;
- changing language immediately refreshes the bottom reply keyboard;
- main inline labels are shorter and use compact state cues to reduce wrapping;
- `/start` provides concise onboarding and routes users to persistent navigation instead of dumping advanced commands;
- the donation panel is localized and keeps the approved USDT/ETH/BNB EVM address presentation without the removed warning line;
- preference/onboarding storage on the touched async handlers runs through `asyncio.to_thread`;
- runtime startup still does not call `setChatMenuButton`, so an externally configured Mini App Web App button is preserved.

Telegram native reply/inline buttons retain Telegram's own visual rendering. Their controllable design surface is label wording, emoji cues, row grouping, ordering, state wording and navigation depth; the release improves those dimensions rather than pretending native buttons support arbitrary CSS.

## Telegram Mini App visual design

- critical secondary copy is raised out of the previous 8–10px range into a practical 11–13px range;
- direct mobile form/control targets are at least 44px tall while compact switch visuals remain visually small inside a larger hit area;
- bottom navigation has clearer active-state treatment and larger targets;
- focus-visible states are reinforced for keyboard/accessibility navigation;
- selectable chips, Funding directions and exchanges expose `aria-pressed` state;
- the active bottom tab retains `aria-current="page"`;
- input placeholder contrast is improved on the dark field surface;
- `prefers-reduced-motion` disables non-essential interface animation/transition behavior;
- primary Overview, FVG, Funding, Alerts and Settings screens no longer mix avoidable English status/filter labels into the Russian locale;
- the existing dark trading-dashboard direction and API contracts are preserved.

## Verification

The reviewed release commit must pass:

- dependency audit and Python compilation;
- complete Python unit suite, including `tests.test_ui_ux_audit` and updated Telegram menu contracts;
- bounded pipeline/research smoke and notification soak;
- Telegram Mini App TypeScript typecheck and production build with `VITE_MOCK_MODE=false`;
- Mini App redesign verification;
- backup contract tests;
- production systemd render/verify;
- a second CI and Release audit run on the exact same final SHA;
- review with no blocking requested changes or unresolved threads.

## Compatibility and production safety

- Telegram/FVG/funding/Mini App API routes and data schemas are unchanged;
- `v1.3.7` remains immutable and is never moved or rewritten;
- production env, SQLite/runtime state, BotFather settings, Xray, Nginx and network ports are not changed by release publication;
- Mini App remains default-off and loopback-only until explicitly enabled in deployment configuration;
- public access and operational feature flags remain fail-closed/default-off;
- production VDS deployment is a separate guarded operation using the exact published release SHA.

## Release archive

The release workflow creates `fvg-alert-bot-1.3.8.tar.gz` and `fvg-alert-bot-1.3.8.tar.gz.sha256` only from the reviewed two-parent merge commit on `main`.

Release assets are uploaded through the authenticated GitHub API action instead of relying on a runner-local `gh` executable. Existing tag and asset names are detected and left unchanged, preserving immutable and idempotent publication.
