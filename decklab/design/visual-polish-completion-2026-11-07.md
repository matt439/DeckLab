# Visual polish: remaining pages and browser qualification

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This completes the implementation lane of the [visual direction](visual-polish-direction-2026-11-07.md). Household acceptance remains separate; the story stays partial.

## Result

The remaining pages use the shared reading/action hierarchy. Table labels use Figtree at the density's metadata size, semibold and ordinary case; numerical evidence keeps its existing mono treatment. Collection names are semibold, condition/language words use the reading font, and pending search results retain readable ink beside their loading status. Shopping's page links are quieter, printing/reason lines grow with text, and card identity has more table width. Activity groups changes on one surface per day with dividers. Field hints retain regular weight instead of inheriting label emphasis.

Collection's conditional storage forecast keeps its concise count/capacity comparison and uncertainty/over-capacity warnings visible. General assumptions, sources and exclusions sit in one native disclosure. The calculation, conditional wording, permissions and existing source-list lifecycle are retained. With the same invented 51 pending copies at 1440px, the table header moves from y=867.5px to y=656.5px, before the final name-width/hint refinements. Its labels change from 10.5px mono capitals to 13px Figtree/600 while retaining a 30px header height. The purpose is to reach the cards sooner without concealing uncertainty.

The receipt bar reflows relative to available text width. If it consumes more than 40% of the viewport left between shell bars, the same native controls move into normal flow. Only sticky height reserves focus/guidance clearance. Narrow List rows reflow names and chips; Tools no longer expands the layout viewport. Resize listeners/observers stop on stale or detached views. Selection, blockers, native dates, preview/apply and ownership rules are unchanged.

## Evidence and comparisons

The receipt repair comparison uses the original 16-case harness and identical synthetic data. The baseline reproduces four enlarged-root pointer failures; the paired after run completes all 16. At 600px CSS root stress the initial bar changes from 1,488px high to 204px; choosing another date grows it to 260px and activates normal flow. At 320px it uses normal flow, leaving the board reachable. This is CSS text-size stress, separately from actual page zoom.

The page-family baseline captures 36 ordinary phone/desktop cases with the same invented cards, parcels, queue and history. Final coverage adds tablet, empty primary lists, unavailable reads and pending reads. Activity and database-only Settings use explicit invented read adapters; ordinary inventory/deck/receipt readers use the owned disposable backend. Baseline and final main captures use the same viewport, theme, pointer and top-of-page position. Expanded forecast and state-anchor images are supplemental.

Actual Chromium page zoom uses fresh, owned profiles under the private temporary runtime, a fixed physical window and no CSS enlargement. Acceptance requires CDP page zoom 2, visual/pinch scale 1, unchanged outer window width, half the CSS layout viewport and twice the CSS-to-device scale. Both 1470px and 640px windows are compared in light/dark themes over 13 task/page families. Raw CDP viewport PNGs retain the complete physical viewport; the earlier Playwright screenshot crop experiment is rejected as visual evidence.

The editor interactions include native quantity changes, Remove, footer Undo, More/Escape and a nine-row Commander removal review. Its long diff must preserve all removed identities, allow the blocker to be reached by scrolling, keep final Save disabled, and restore enabled Undo/Discard after Keep editing. Saved deck responses must remain unchanged.

Save blockers now precede the proposed changes in the review body. A long list of removals therefore cannot push the reason for disabled Save below the first screen. The existing empty-list confirmation, draft ownership and final-save predicates are retained; the browser check also requires the blocker to be visible before it scrolls the review.

Receipt qualification includes ordinary pointer Tools/layout/date controls, first/last checks, Record hit-testing without activating it, keyboard clearance, a 24-copy parcel and a two-part parcel with a local copy split. Reload requires explicit Resume and must restore the local checking draft exactly. Saved receipt responses stay unchanged. No preview or arrival write is allowed.

The [proof](visual-polish-completion-2026-11-07/proof.json) retains source fingerprints, case measurements/assertions, requests and cleanup. The [manifest](visual-polish-completion-2026-11-07/screenshot-manifest.json) identifies 30 unchanged curated PNGs. Representative comparisons and final views were inspected by the implementation and independent review agents.

| Comparison | Before | After |
|---|---|---|
| Collection, 1440px light | [Before](visual-polish-completion-2026-11-07/before-collection-rows-populated-1440-light.png) | [After](visual-polish-completion-2026-11-07/after-collection-rows-populated-1440-light.png) |
| Shopping, 393px dark | [Before](visual-polish-completion-2026-11-07/before-shopping-populated-393-dark.png) | [After](visual-polish-completion-2026-11-07/after-shopping-populated-393-dark.png) |
| Activity, 1440px dark | [Before](visual-polish-completion-2026-11-07/before-activity-populated-1440-dark.png) | [After](visual-polish-completion-2026-11-07/after-activity-populated-1440-dark.png) |
| Settings hints, 1440px light | [Before](visual-polish-completion-2026-11-07/before-settings-populated-1440-light.png) | [After](visual-polish-completion-2026-11-07/after-settings-populated-1440-light.png) |
| Receipt Tools, 320px root stress dark | [Before](visual-polish-completion-2026-11-07/before-receipt-320x700-root200-coarse-dark-tools.png) | [After](visual-polish-completion-2026-11-07/after-receipt-320x700-root200-coarse-dark-tools.png) |

Final views include the [expanded forecast](visual-polish-completion-2026-11-07/final-collection-rows-393-dark-forecast.png), [unavailable maintenance](visual-polish-completion-2026-11-07/final-settings-failed-393-light.png), [reachable enlarged Record](visual-polish-completion-2026-11-07/final-receipt-320x700-root200-coarse-dark-primary-focus.png), [resumed multipart draft](visual-polish-completion-2026-11-07/final-split_receipt-393x700-coarse-light-resumed.png), [actual-zoom editor](visual-polish-completion-2026-11-07/zoom-editor-window-640-zoom2-light.png) and [initial blocked long review](visual-polish-completion-2026-11-07/zoom-editor-blocker-window-1470-zoom2-light-review-initial.png).

## Verification

- **106/106 final page/state cases**, including native forecast disclosure, readable busy results, regular hints/semibold labels, maintenance-state anchors and token preference reload.
- **104/104 actual-zoom cases**, including 52 measured 200% comparisons and 120 complete viewport PNGs. Native quantity/Undo/menu/date and long-review checks pass; saved decks are unchanged.
- **24/24 final receipt cases**, all with pointer/focus reachability, exact reload/resume and unchanged saved receipts; four multipart cases retain local splits. No preview/apply is invoked.
- The **44-case capture matrix and editor sequence**, **40 composition**, **26 variant**, **54 shell** and **28 task** cases complete. Default capture/editor and task suites were repeated after the final hint, Shopping-width and review-blocker refinements. The proof identifies every run's source.
- Guarded frontend regression: **3,154 tests, two skips**, 457.394 seconds. Final affected editor, web/device, Shopping, forecast, tooling, privacy and source checks: **179 tests, one existing directory-symlink skip**, 58.426 seconds. Independent focused page checks also pass. Ruff, JavaScript syntax, whitespace and the 1,200-line source guard pass.

Every retained run has stable source fingerprints and confirmed browser closure, fixture exit and private-runtime removal. There are no unexpected HTTP/page errors. Initial actual-zoom pages fit their viewports. Two long-review **Keep editing transitions at 312 CSS pixels retain 4px horizontal scroll**; all controls remain readable and reachable. This sub-320 diagnostic is retained, rather than hidden behind a blanket zero-overflow claim. Separate 320px reflow cases pass.

## Acceptance boundary

This finishes the repository UI implementation and repeatable desktop Chromium qualification. It does not close `E11-S30`: household iPhone/iPad touch ergonomics, Safari on the changed UI, software keyboards, VoiceOver/screen-reader use, varied real-art recognition and production database durability remain human/runtime acceptance. Browser reload checks cover local receipt drafts and a token search preference, not final Wishlist/deck/arrival writes in a production browser. Their save paths retain fixture/API regression coverage.

No household configuration, records, visibility switch or Forge game is used or changed. The normal local server remains stopped. The headless fixtures refuse final writes, external requests, database connections and simulation workers; each run records source consistency and browser/fixture/runtime cleanup separately. A captured screenshot alone is not an aesthetic or accessibility pass.
