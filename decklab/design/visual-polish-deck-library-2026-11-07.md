# Visual polish: populated decks and library

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This implements the next bounded slice of the [visual direction](visual-polish-direction-2026-11-07.md). Wider typography, state and device acceptance remain open.

## What changed

- The deck page uses a small art crop beside a semibold title on neutral ground. Actions sit beside the identity on wide screens and beneath the full-width title at 1000–1280px. The former hero, title scrim, over-art controls and tinted metadata band are removed. Previous/next remain the original guarded controls, now beside the metadata.
- Availability uses a neutral bordered surface, explicit state words and its warning icon. Unknown checks, missing cards, incoming sources, listed-printing costs, physical-assembly qualifications and recorded box-check dates keep their existing wording and actions.
- Known empty play history is one line. Populated history retains its named section, last date, game count and list changes. An unread history response still contributes no claim.
- Library tiles and detail panes use neutral reading surfaces, quieter status tags and semibold names/section labels. Art, pips and stripes retain deck identity. Edit/Open sit directly after the detail identity; art is capped at `min(180px, 24dvh)`.
- At 1000–1280px the library's name occupies the first line beside the thumbnail; availability and results follow beneath. Wider layouts retain their aligned evidence columns. Existing selection, routes, capabilities and keyboard order remain.

## Matched comparisons

Both runs used the same finalized disposable fixture/harness, Chrome 156.0.8078.80, Playwright Core 1.65.0, DPR 2 and explicit pointer/theme settings. Before uses a detached checkout of `dc831dab`; after uses this slice. The temporary checkout was removed. Raw source fingerprints retain Git checkout line-ending differences; [proof](visual-polish-deck-library-2026-11-07/proof.json) identifies the seven code changes separately after LF normalization.

The fixture has four visible home decks, including a long-titled Commander deck with recorded games and a guide, an unplayed casual deck and an empty idea. Its deliberately sparse lists, placeholder art, invented rules data and dated records qualify layout only. They are not deck-building advice, real results or household records.

| Screen | Before | After |
|---|---|---|
| Commander Overview, 1440×900 light | [Before](visual-polish-deck-library-2026-11-07/before-commander-1440-light.png) | [After](visual-polish-deck-library-2026-11-07/after-commander-1440-light.png) |
| Commander Overview, 1440×900 dark | [Before](visual-polish-deck-library-2026-11-07/before-commander-1440-dark.png) | [After](visual-polish-deck-library-2026-11-07/after-commander-1440-dark.png) |
| Unplayed casual Overview, 393×700 light | [Before](visual-polish-deck-library-2026-11-07/before-casual-393-light.png) | [After](visual-polish-deck-library-2026-11-07/after-casual-393-light.png) |
| Unplayed casual Overview, 393×700 dark | [Before](visual-polish-deck-library-2026-11-07/before-casual-393-dark.png) | [After](visual-polish-deck-library-2026-11-07/after-casual-393-dark.png) |
| Library work area, 1180×746 coarse light | [Before](visual-polish-deck-library-2026-11-07/before-library-work-1180-light.png) | [After](visual-polish-deck-library-2026-11-07/after-library-work-1180-light.png) |
| Library work area, 1180×746 coarse dark | [Before](visual-polish-deck-library-2026-11-07/before-library-work-1180-dark.png) | [After](visual-polish-deck-library-2026-11-07/after-library-work-1180-dark.png) |

All twelve retained PNGs were visually inspected; the [manifest](visual-polish-deck-library-2026-11-07/screenshot-manifest.json) records their unchanged bytes. Library work-area cases request the same container at 80px clearance. Before/after scroll offsets match through 1470px, including the retained 1180px pair. QHD reaches the document scroll limit instead (396px before, 336px after), so its captures are state coverage rather than a fixed-offset composition comparison. Separate top-of-page cases preserve the fixture's tall stale-table warning; those images do not establish row/detail composition. Initial exploratory captures omitted the work area, and an incorrect failure selector was corrected before the final paired runs.

Measured allocations, identical in both themes for these cases:

| Element | Before | After | Implication |
|---|---:|---:|---|
| 1440px deck header height | 287px | 137.2px | About 150px more room before substantive Overview content. |
| 1440px Overview tab top | 514px | 364.2px | Same readiness contents, earlier tab/content start. |
| 393px casual empty-history block | 92px | 21px | Empty history no longer competes as a leading panel. |
| 1180px library row identity width | 129.7px | 385.7px | Long names can wrap across the available first line. |

The design judgment is that identity, current action and supporting evidence are easier to distinguish. The library keeps clear selection while the detail loses its broad colour wash. These are bounded visual comparisons, not a general quality score or final acceptance of the app.

## Verification and limits

Both final composition runs completed **38/38 cases**, with no uncaught page errors or document-wide horizontal overflow. They cover short-phone deck views/history/guide, library tiles, tablet portrait/landscape, laptop and QHD library, empty deck/filter and failed-library states. Native desktop library selection updated the detail and route. Every composition case retained the saved Commander response digest. Source fingerprints stayed stable during each run, browser closure was confirmed, fixtures exited 0 and temporary runtimes were removed.

The existing **42-case capture matrix and editor interaction suite** also completed on the same final source digest, including Wishlist Zoom retention, guide destinations and blocked editor Save recovery. Saved deck and server-kept draft digests remained unchanged. The proof retains their outcome and cleanup separately from composition.

Focused guarded deck checks passed 119 tests, library/device/keyboard checks passed 157, and the harness checks passed with one existing link-creation skip. The full guarded suite passed **12,294 tests, with 456 expected skips**, in 1,210 seconds. Ruff, the source-inventory tests and the source-length guard passed. Database integration, native runtime and real Forge remain separate qualification workflows.

No household configuration/database, visibility setting, Forge game or normal server was changed. Final saves remain denied in both harness HTTP layers; dry deck checks retain their existing exception. Browser persistence and database durability are separate qualifications.

Next: element-level typography/spacing and remaining populated/error/busy page families; narrow variant evidence, receipt filter/bulk-action hierarchy and empty Considering composition remain candidates. Qualify QHD deck Overview separately: this run's QHD case is the library. Actual browser/OS enlargement, real art, software keyboards, Safari, physical touch and a screen reader remain open. The empty idea's pre-existing “Ready to build” wording with zero cards is an unresolved state-semantic question, not evidence of build validity. Keep `E11-S30` open.
