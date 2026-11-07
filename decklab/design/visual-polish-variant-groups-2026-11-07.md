# Visual polish: narrow variant group evidence

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This continues the [visual direction](visual-polish-direction-2026-11-07.md) and its optional O06 group treatment. Wider page/state coverage and device acceptance remain open.

## What changed and why

The three-column By group tables allocated fixed space to identity and deck count, leaving the graph and range caption squeezed on phones. At 393px the scale's Worse/Better phrases wrapped; at 320px with CSS root-font stress, headers and numerical words fragmented and the group axes overflowed.

`variant.js` retains one native table per grouping, its column and row headers, all counts, notes, unknown values and the common `vtSpan`. `variant.css` now reflows each row into a name/count line followed by full-width evidence when the group container is at most `36em`. The threshold follows available width and inherited text size. In this fixture, the normal layout changes between 624px and 625px viewports; 600px with enlarged text also stacks. Wider tables retain their existing geometry.

The count gains a visible deck/decks unit in the stacked layout. That extra unit is decorative to assistive technology because the Decks column header remains available. Explicit table/rowgroup/row/header/cell roles accompany the CSS reflow; clipped column headers remain in the accessibility tree. The purely decorative scale footer is excluded. Native table navigation on real Safari/VoiceOver still requires acceptance.

## Matched comparisons

Both phases used the same finalized `variant-layout` harness, synthetic fixture, Chrome 156.0.8078.80, Playwright Core 1.65.0 and DPR 2. Baseline production source was `85e6ed4`; only `variant.js` and `variant.css` differ between the retained phases. The [proof](visual-polish-variant-groups-2026-11-07/proof.json) retains source hashes, all 26 cases' evidence comparisons, geometry, accessibility snapshots, request classifications and cleanup. The [manifest](visual-polish-variant-groups-2026-11-07/screenshot-manifest.json) identifies twelve unchanged PNGs, all visually inspected.

| Screen | Before | After |
|---|---|---|
| Short phone, 393×700 light | [Before](visual-polish-variant-groups-2026-11-07/before-groups-393-light.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-393-light.png) |
| Short phone, 393×700 dark | [Before](visual-polish-variant-groups-2026-11-07/before-groups-393-dark.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-393-dark.png) |
| Unknown and negative groups, 393px light | [Before](visual-polish-variant-groups-2026-11-07/before-groups-393-light-lower.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-393-light-lower.png) |
| 320px, CSS root-font 200%, light | [Before](visual-polish-variant-groups-2026-11-07/before-groups-root200-320-light.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-root200-320-light.png) |
| 600px, CSS root-font 200%, light | [Before](visual-polish-variant-groups-2026-11-07/before-groups-root200-600-light.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-root200-600-light.png) |
| Desktop, 1440×900 dark | [Before](visual-polish-variant-groups-2026-11-07/before-groups-1440-dark.png) | [After](visual-polish-variant-groups-2026-11-07/after-groups-1440-dark.png) |

Primary complete-result captures position By group at about 80px. Supplementary lower-group captures attempt the same clearance for By number of colours, but the shorter after page reaches its bottom scroll limit first. Their framing is recorded separately; they are not identical scroll positions. The primary 320px root-stress pair also has different layout-viewport expansion because the baseline overflows. Compare the configured width and measured group area rather than treating this as browser zoom.

| First group bar, both themes | Before | After |
|---|---:|---:|
| 320px ordinary text | 116.8px | 272px |
| 393px ordinary text | 166.5px | 345px |
| 600px ordinary text | 296.4px | 536px |
| 624px ordinary text | 312.7px | 560px |
| 625px ordinary text | 313.4px | 313.4px |
| 820px ordinary text | 446px | 446px |
| 1440px ordinary text | 840.4px | 840.4px |
| 320px CSS root-font stress | 53.8px | 272px |
| 600px CSS root-font stress | 233.4px | 536px |

The visual judgment is that group identity, sample size and evidence now read as one unit. Ordinary 320/393px scale phrases fit on one line; the 393px unknown and negative ranges remain explicit. At extreme root-font stress, phrases may still wrap at spaces. Every group bar's left edge and width match its own axis, and all bars retain the same numerical domain. This is a layout improvement, not a new statistical interpretation.

## Verification and limits

Each retained phase completed **26/26 cases**, plus two lower-group PNGs: 320/393/599/600/624/625/820/1440px, short 740×360 landscape, 320/600px CSS root-font stress, and failed/running states, all in both themes. All group labels, column headings, counts, range text, omitted explanations, bar labels/inline positions and numerical scales compare equal after excluding decorative unit words. Action measurements also compare equal. Native explanation disclosures open and close without changing the evidence. The running fixture correctly has no finished group tables.

Chrome's accessibility snapshots retain named tables, column headers, row headers and cells after reflow. This is bounded browser evidence, not a screen-reader check. Failed synthetic variants retain illustrative old result rows; that adapter choice is not production result semantics or a newly discovered defect.

The existing **44-case capture matrix and editor interaction sequence** completed too, with saved deck/server-kept draft proofs unchanged. Guarded focused web, variant handoff/buying/queue, device, accessibility, harness, privacy and source-inventory checks passed **163 tests in 23.418 seconds, one existing skip**. Ruff and the 1,200-line source guard passed. The full unrelated backend suite was not repeated.

The first exploratory run incorrectly equated configured viewport width with a browser-expanded layout viewport and expected finished tables while a test was running. Those harness checks were corrected before both retained phases. Its owned processes and runtime also cleaned up. The opt-in [repeat command](../ui_review/README.md) is `python scripts/ui_review.py --suite variant-layout`; baseline overflow remains diagnostic, never an automatic visual pass.

At 320px/root200, document width improves from 429px to 320px. **Separate shell overflow remains** in both phases at 600/624/625px ordinary text, and at 600px/root200: the top-bar avatar extends past the configured width, with layout widths of 629/639/640px respectively. Group tables stay inside their containers. This records a reproducible remaining shell finding; this slice does not qualify narrow-header enlargement. Other sampled ordinary widths have no document overflow.

Both phases and the regression run retained stable source fingerprints during execution, zero uncaught page errors, no unexpected fixture HTTP failures or blocked requests, confirmed browser closure, fixture exit 0 and temporary-runtime removal. The group suite performs no dry checks or accepted writes; the default suite retains its existing dry-run editor checks. No household records, private configuration, visibility setting or Forge game was used or changed.

Next: the recorded narrow-shell overflow, receipt filter/bulk-action hierarchy and empty Considering composition, followed by populated/error/busy Collection, Shopping, Tokens, accessories, Game log and Activity. Actual browser/OS enlargement, software keyboards, real art, Safari, physical touch and screen-reader acceptance remain open. Keep `E11-S30` partial.
