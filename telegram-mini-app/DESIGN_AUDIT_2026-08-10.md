# Telegram Mini App — design and structure audit

Date: 2026-08-10
Scope: PR #88, `agent/mini-app-navigation-redesign`
Base: `main` 1.3.5

## Result

The redesigned information architecture is suitable for merge after CI and release-audit verification. No business capability is intentionally removed.

## Information architecture

- Primary navigation is limited to three high-frequency destinations: Home, FVG, Funding.
- General settings, notification summary and Administration are secondary destinations grouped under the profile menu.
- Administration remains capability-gated by the server-provided admin state.
- Secondary screens have an explicit path back to Home while the primary navigation remains globally available.

Status: PASS.

## Mobile ergonomics and visual hierarchy

- Primary navigation uses large touch targets and is constrained to a compact floating bar.
- The dashboard exposes module state, message format and FVG capacity before detailed controls.
- FVG instruments are presented as a readable list rather than a horizontally hidden tab strip.
- The list renders all stored instruments; it does not truncate with `slice()`.
- The add-instrument flow disappears only at the server-provided technical limit; existing instruments remain editable/removable.
- Final polish raises undersized navigation/status typography and preserves a minimum 44x44 close control.
- An additional <=360px rule protects narrow Telegram webviews.

Status: PASS after audit polish.

## Accessibility and interaction audit

Audit polish adds runtime semantics without changing settings behavior:

- specific bilingual labels for the profile trigger, dialog and primary navigation;
- `aria-haspopup=dialog`, `aria-controls`, and `aria-current=page`;
- a visible 44x44 close button in the profile dialog;
- Escape closes the profile dialog;
- Tab/Shift+Tab remain inside the open dialog;
- keyboard focus moves into the dialog on open and returns to the trigger on explicit close;
- background scrolling is locked while the dialog is open;
- the full-screen visual backdrop is removed from the keyboard tab order.

Status: PASS after audit polish.

## Capacity and technical-limit behavior

- The client reads `envelope.limits.maxFvgSymbols` from the backend.
- Capacity is shown as `current / max`.
- No client-side list truncation is used.
- At the limit, adding is disabled by flow while edit/delete remains available.
- The backend remains the authority for the actual limit and payload validation.

Status: PASS.

## Functional preservation

The redesign retains:

- FVG module toggle and confirmed-FVG toggle;
- bullish/bearish directions;
- exchange selection;
- 15m/1h/4h/1d timeframe selection;
- per-instrument price and FVG-size filters;
- Funding module, interval, threshold, directions and exchanges;
- general language/message-format settings;
- notification summary;
- protected administration and existing admin enhancer behavior;
- unsaved-changes and save flow.

Status: PASS by source/diff review; automated regression checks remain mandatory before merge.

## Verification required before merge

- Telegram Mini App typecheck and production build;
- full Python unit suite including navigation/design contracts;
- dependency audit;
- bounded pipeline/research smoke;
- funding storage verification;
- Linux VDS systemd verification;
- release audit including Mini App regressions, backup contracts and bounded notification soak.

## Residual risk

This audit is code-, structure- and responsive-style-based. It does not replace a human screenshot review inside every Telegram client/device combination. The CSS explicitly covers narrow mobile viewports and Telegram safe-area insets, and CI must verify the production frontend build before merge.
