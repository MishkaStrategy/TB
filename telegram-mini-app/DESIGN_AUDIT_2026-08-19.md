# Telegram Mini App — final design audit (2026-08-19)

## Decision

The approved visual direction is the first dark/white minimalist TB dashboard selected by the product owner on 2026-08-19. This audit freezes that direction so future UI work can refine behavior without drifting into a different visual language.

The implementation is presentation-only. Telegram authentication, Mini App API contracts, FVG settings, Funding settings, admin authorization, dirty-state handling, haptics and market-overview behavior remain unchanged.

## Visual contract

- near-black page background (`#080a0c`);
- neutral charcoal surfaces (`#111315` / `#151719`);
- white primary hierarchy and cool gray secondary text;
- green/red used only for market/status semantics;
- no blue/cyan decorative gradient in the final layer;
- thin neutral borders, no neon glow and no decorative glassmorphism on content cards;
- compact rounded cards with 14–15px radii;
- system/SF-style font stack;
- Overview uses two compact module cards and individual market cards rather than a nested card wall;
- each market row keeps symbol, exchange, timeframes, active state, a neutral sparkline and exchange-aware 24h change visible in one scan;
- bottom navigation remains five destinations and uses a white active marker, neutral inactive icons and Telegram safe-area padding.

## UX audit

### Information hierarchy

PASS.

The overview order is fixed as:

1. TB identity / control-center label;
2. FVG + Funding state summary;
3. instrument list;
4. persistent five-item navigation.

Trading values use tabular numerals where applicable. The 24h percentage remains the strongest market value in each row while timeframes and exchange remain secondary.

### Interaction model

PASS.

No navigation destination or trading control was removed. Existing FVG/Funding editors, at-least-one constraints, save/dirty behavior and admin gating remain in the React application. The design layer does not invent client-side market state or bypass server validation.

### Mobile ergonomics

PASS by static contract; browser smoke is required before merge.

- direct controls retain the existing >=44px hit-area audit;
- bottom navigation uses >=56px buttons;
- `safe-area-inset-bottom` remains in the base navigation contract;
- the market grid collapses at <=380px by removing only the decorative sparkline, not data;
- no horizontal scrolling is intentionally introduced.

### Accessibility

PASS by code audit; automated/browser checks are required before merge.

- SVG navigation icon system is retained;
- `aria-current` / `aria-pressed` semantics remain unchanged;
- focus-visible remains explicit and is recolored to neutral white for the final theme;
- green/red are never the only signal for instrument state: text labels and percentage signs remain visible;
- reduced-motion rules remain active.

## Performance audit

PASS by design.

The final style adds one static CSS file and one inline SVG polyline per visible overview instrument. There are no external fonts, image requests, chart libraries, animation libraries or runtime design dependencies. Sparklines are decorative and derived from the already loaded 24h direction; they do not trigger additional market requests.

## Security and contract audit

PASS.

No changes are made to:

- Telegram `initData` authentication;
- `/api/mini-app/settings`;
- `/api/mini-app/market-overview`;
- server-side admin/access checks;
- one-time admin confirmations;
- production deployment, BotFather, reverse proxy or VDS settings.

## Required verification gate

Before merge to `main`:

- TypeScript typecheck;
- production Mini App build with `VITE_MOCK_MODE=false`;
- Mini App design/navigation regressions;
- complete project CI / release audit required by the repository;
- mobile browser smoke at ~390px width;
- verify Overview, FVG, Funding, Alerts and Settings navigation;
- verify no horizontal overflow;
- verify market `null` still renders as `—`;
- verify settings dirty/save flow;
- final PR diff review with no blocking findings.

## Files implementing the visual contract

- `src/final-minimal.css` — final presentation layer, imported last;
- `src/screens/OverviewScreen.tsx` — approved overview composition;
- `src/main.tsx` — final layer import;
- `tests/test_mini_app_design_audit.py` — regression lock for the approved direction.
