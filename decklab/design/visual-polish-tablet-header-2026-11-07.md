# Visual polish: tablet header allocation

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This fixes the narrow-shell overflow recorded in the [variant group slice](visual-polish-variant-groups-2026-11-07.md), continuing the [visual direction](visual-polish-direction-2026-11-07.md). Wider page/state and device acceptance remain open.

## What changed and why

The casual header's search field required 300px even beside a long Back link and the 44px avatar. At 600/624/625px, the avatar extended beyond the viewport. The contextual page title could shrink to zero, but the search could not.

Within the existing casual 600–999px media query, `shell.css` now lets the search shrink below its preferred width and limits its box to the available width. The contextual title has a zero flex basis, so it grows into the space left after the other header controls. Its existing scroll-triggered visibility and ellipsis remain. The rule follows the earlier casual `flex` shorthand so that shorthand cannot reset the new basis.

A shrink-only experiment removed document overflow but left just 12.47px of typing space in the 600px enlarged-root case: the invisible title still consumed width. That treatment was rejected. The final layout keeps about 192px of input space there, without reducing text or the avatar target.

The field/icon query and `/` focus behavior are unchanged. Phone icon mode, short-landscape navigation and desktop field sizing retain their existing rules. No DOM, route, permission or data contract changed.

## Matched comparisons

Both retained phases used the same finalized `shell-layout` harness, invented content, viewport/pointer/theme settings, top-of-page position, Chrome 156.0.8078.80, Playwright Core 1.65.0 and DPR 2. Baseline application source is `e152f1b`; only `shell.css` differs between the phases' source fingerprints. Tooling and read adapters are identical. The [proof](visual-polish-tablet-header-2026-11-07/proof.json) retains all 54 paired cases, geometry, keyboard observations, source hashes, request classifications and cleanup. The [manifest](visual-polish-tablet-header-2026-11-07/screenshot-manifest.json) identifies fourteen unchanged PNGs, all visually inspected.

| Screen | Before | After |
|---|---|---|
| 600px, light | [Before](visual-polish-tablet-header-2026-11-07/before-back-600-light.png) | [After](visual-polish-tablet-header-2026-11-07/after-back-600-light.png) |
| 600px, dark | [Before](visual-polish-tablet-header-2026-11-07/before-back-600-dark.png) | [After](visual-polish-tablet-header-2026-11-07/after-back-600-dark.png) |
| 600px, CSS root-font 200%, light | [Before](visual-polish-tablet-header-2026-11-07/before-back-root200-600-light.png) | [After](visual-polish-tablet-header-2026-11-07/after-back-root200-600-light.png) |
| 600px, CSS root-font 200%, dark | [Before](visual-polish-tablet-header-2026-11-07/before-back-root200-600-dark.png) | [After](visual-polish-tablet-header-2026-11-07/after-back-root200-600-dark.png) |
| Synthetic activity, 820px light | [Before](visual-polish-tablet-header-2026-11-07/before-running-820-light.png) | [After](visual-polish-tablet-header-2026-11-07/after-running-820-light.png) |
| Desktop control, 1000px dark | [Before](visual-polish-tablet-header-2026-11-07/before-back-1000-dark.png) | [After](visual-polish-tablet-header-2026-11-07/after-back-1000-dark.png) |

Supplementary focused-search captures show the complete ring and avatar clearance at enlarged 600px in [light](visual-polish-tablet-header-2026-11-07/after-back-root200-600-light-search.png) and [dark](visual-polish-tablet-header-2026-11-07/after-back-root200-600-dark-search.png). These are after-only interaction views, not matched baseline framing.

| Document width, both themes | Before | After |
|---|---:|---:|
| 600px ordinary text | 629px | 600px |
| 624px ordinary text | 639px | 624px |
| 625px ordinary text | 640px | 625px |
| 600px CSS root-font stress | 629px | 600px |
| 600px synthetic activity, ordinary and enlarged root | 632px | 600px |

The visual judgment is that Back, search and the person menu now form one complete header at these widths. The ordinary/enlarged 600px input is 191.61px wide; the smallest sampled tablet input is 187.61px with synthetic activity. The native input clips its placeholder within its own viewport; typed text can scroll normally. At wider tablet widths the contextual title has space again. The sampled phone, short-landscape and desktop header geometry compares equal.

## Verification and limits

Both phases completed **54/54 cases**: 320/393/599/600/624/625/699/700/820/999/1000/1199/1200/1440px, short 740×360 landscape, explicit root-font stress at 320/600/820/1000/1440px, home library and receipt headers, and synthetic activity at 600/820px, all in both themes. The repeat command is `python scripts/ui_review.py --suite shell-layout`; its eight-case smoke subset is documented in the [headless workflow](../ui_review/README.md).

All final initial, search-focused, avatar-menu and scrolled measurements have no document overflow, expanded layout viewport, overlapping header siblings or controls outside the configured width. Initial leaf-control rectangles, including the visible activity button, are disjoint. Avatars remain 44×44px. `/` targets the same visible bar input or search sheet in each phase; Escape closes sheets and avatar menus, returning avatar-menu focus to the avatar. Focused tablet fields retain their full ring and at least 180px of typing space in these fixtures. Scrolled title geometry is recorded, not inferred from a hidden title.

The activity slot still follows its existing size-container policy: below 44px of free space the button is hidden. It remains hidden in the sampled 600px and enlarged 820px states. At ordinary 820px the final allocation makes room for its full 44px button, which the baseline hid. The fixture exercises the ordinary poll and activity renderer with an invented read response; it does not qualify real running-job semantics or the progress/Stop details.

The existing **44-case capture matrix and editor interaction sequence** also completed, with saved-deck and server-kept-draft proofs unchanged. Guarded focused shell, global-search, device, harness, accessibility, privacy, source-inventory and web checks passed **147 tests in 30.372 seconds, one existing skip**. Ruff, JavaScript syntax and the 1,200-line source guard passed. The unrelated full backend suite was not repeated.

Both retained phases and the regression run have stable source fingerprints, zero uncaught page errors or unexpected fixture HTTP/blocked requests, confirmed browser closure, fixture exit 0 and temporary-runtime removal. Only existing dry-run deck checks were allowed; final writes and visit telemetry remained blocked. The normal local server stayed stopped. No household records, private configuration, visibility setting or Forge game was used or changed.

Actual browser/OS enlargement, physical Safari/touch/software keyboards, screen readers and real-art recognition remain unqualified. This bounded matrix does not cover every route, profile, label or busy/error state. Next: receipt filter/bulk-action hierarchy and empty Considering composition, then the remaining populated/error/busy page families. Keep `E11-S30` partial.
