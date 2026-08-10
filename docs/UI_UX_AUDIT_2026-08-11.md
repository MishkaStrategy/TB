# UI/UX Audit — 2026-08-11

## Scope

This audit reviews the user-facing Telegram bot and Telegram Mini App directly from the current canonical `main`. It covers visual hierarchy, readability, localization, interaction semantics, navigation, onboarding, persistent/reply keyboards and preservation of the externally managed Telegram Mini App Menu Button.

## Findings and changes

### Telegram bot

1. **Persistent keyboard language drift — fixed.** The reply keyboard was always rendered in Russian even though user preferences and routing already supported RU/EN aliases. `build_reply_menu(language)` now renders the selected language and the keyboard is refreshed immediately when the language changes.
2. **Main inline menu hierarchy — improved.** Primary labels were shortened and status is communicated with a compact `✅ / ⏸` prefix, reducing wrapping in Telegram clients.
3. **Onboarding density — improved.** `/start` no longer dumps the advanced command reference into the conversation. It gives a short product introduction and routes the user to the pinned navigation; Telegram's command menu remains available for advanced actions.
4. **Donation panel — simplified and localized.** The panel now supports RU/EN, keeps the approved USDT/ETH/BNB EVM address presentation and removes the extra warning line from the interface.
5. **Event-loop safety on high-frequency UI paths — improved.** User-preference and onboarding persistence calls introduced or touched by this audit execute through `asyncio.to_thread` rather than blocking Telegram async handlers.
6. **Mini App Menu Button — regression guarded.** The UI regression contract verifies that runtime startup code does not call `set_chat_menu_button` or replace the externally configured Web App button with `MenuButtonCommands`.
7. **Deep legacy menus — residual UX debt.** FVG instrument management, funding-alert advanced controls and parts of the admin panel still contain Russian-first legacy copy. The main navigation and high-frequency settings paths are bilingual; deeper legacy localization should be completed separately with full flow-level regression coverage.

### Telegram Mini App

1. **Critical text was too small — fixed.** Multiple metadata, helper and navigation labels were rendered at 8–10 px. The audited visual layer raises critical secondary copy to a practical 11–13 px range while retaining compact information density.
2. **Bottom navigation readability — fixed.** Navigation targets are larger, labels are more legible and the active tab receives a clearer visual indicator. The existing semantic `aria-current="page"` state is retained.
3. **Touch targets — fixed.** Direct mobile form/control targets are at least 44 px tall; the switch keeps its compact visual track inside a larger hit area.
4. **Selection semantics — improved.** Reusable chips and Funding direction/exchange selectors expose `aria-pressed` state in addition to color/checkmark state.
5. **Reduced motion — added.** `prefers-reduced-motion` disables non-essential screen and control motion.
6. **Focus visibility — reinforced.** Major card/action/navigation controls receive an explicit focus ring.
7. **Placeholder contrast — improved.** Input placeholder color is raised to a more readable level on the dark field surface instead of relying on the weaker previous muted value.
8. **Mixed-language Russian UI — fixed on primary screens.** Overview, FVG, Funding, Notifications and Settings no longer use avoidable English status/filter labels in the Russian locale. Product/market terms such as FVG, Funding, Telegram and exchange names remain unchanged where they are domain names rather than untranslated copy.
9. **Existing design direction preserved.** The dark trading dashboard, color roles, information architecture and core API behavior are unchanged. The audit is an accessibility/readability refinement, not a visual rewrite.

## Telegram button design constraints

Telegram native reply/inline buttons do not expose arbitrary per-button typography, colors, borders or custom graphics to the bot. Their practical design surface is therefore label wording, emoji/icon choice, row grouping, order, state wording and navigation depth. This audit improves those controllable dimensions rather than pretending native Telegram buttons can be CSS-styled like Mini App controls.

## Visual design principles applied

- mobile-first density without sub-10 px critical UI text;
- 44 px or larger interactive targets where the Mini App controls the rendering;
- status conveyed by text/icon/state as well as color;
- one consistent dark trading palette and spacing rhythm;
- no decorative animation required for understanding;
- concise Telegram labels to reduce button wrapping;
- localization treated as part of interface quality, not only translation.

## Verification contract

The audit is not merge-ready until the exact final branch SHA passes:

- dependency audit and Python compilation;
- complete project unit suite, including `tests.test_ui_ux_audit`, Telegram menu contracts and release contracts;
- bounded pipeline/research smoke, backup contracts and notification soak;
- Telegram Mini App TypeScript typecheck and production build with `VITE_MOCK_MODE=false`;
- Mini App redesign, runner selector and dependency policy checks;
- production systemd render/verify;
- a second CI and Release audit run on the same exact final SHA;
- review confirming no regression to BotFather/Bot API Menu Button configuration or production runtime state.

## Release

The UI/UX audit is the next free immutable patch release: `1.3.8`. Existing `v1.3.7` remains historical and must not be moved or rewritten. The still-open reliability/performance audit PR #94 must be synchronized with the new `main` after this release and use a later free patch version rather than competing for `v1.3.8`.

Production VDS deployment is outside this audit PR and remains a separate guarded operation using the exact published release SHA.
