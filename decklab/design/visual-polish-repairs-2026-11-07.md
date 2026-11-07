# Visual polish: interaction and readability repairs

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This continues the [first implementation](visual-polish-implementation-2026-11-07.md) and implements the six remaining repairs in the [rendered change plan](rendered-ui-change-plan-2026-11-07.md). Wider visual composition and device acceptance remain open.

## What changed

- **R02, Wishlist availability:** tiles and sheets distinguish known zero, positive counts and unavailable counts. Missing data or either unread count says **Collection counts unavailable**; only known zero says **None in your collection yet**. Recovery uses the newly returned counts.
- **R01, Wishlist Zoom:** the existing edit sheet stays underneath the viewer, retaining Notes, Source and the local printing choice. The viewer keeps the whole list's order and returns focus to Zoom. Close/Escape/Back end inspection; the sheet's Close abandons its local draft and Save remains explicit. Route, person and away-lock cleanup dispose the private sheet, its picker and its own viewer; late picker answers cannot update a replacement context.
- **R05, result handoffs:** Back to the editor and Save this change follow a response-only current edit capability for home/member casual and Commander decks. Both actions recheck the ordinary editor response's ID, kind, editable state and `may_save`. Route, profile, result, connected control and local-draft ownership are checked before navigation/replacement and after a Replace confirmation. Save this change prepares a local draft; the ordinary editor Save still persists it. Commander swaps use saved recipe sections to retain Commander placement, partners, printing rows and Sideboard. Missing removals or ambiguous Commander changes require editor review instead of writing a partial draft.
- **R03, How to play:** the library link uses the supported `part=guide` destination, renders Overview, then focuses the existing guide with sticky-tab clearance. The deferred move belongs to the original screen, route and person. Manual tab selection clears the destination. Version links and Back/Forward retain it.
- **R04, accessory crop:** outer Save resolves the current owned crop rectangle through the same local commit as Done, then makes its existing single save request. Cancel restores the previous geometry. Unloaded/failed crops refuse Save with recovery guidance. Picture replacement and sheet disposal clear abandoned crop handlers; late image/drag events cannot change another preview.
- **R07, exclusion reasons:** omitted-opponent rows use a dashed boundary and explicit wording, with fully opaque text and links. Necessary explanation is readable in both themes.

These are interaction/readability repairs, not completion of the wider visual direction. The narrow variant group table, populated deck/library treatment, receipt filter/bulk-action hierarchy and empty Considering composition still need their own comparisons.

## Rendered evidence

The final headless run completed **42 capture cases and the editor interaction suite**, with no failed captures, uncaught page errors or document-wide overflow. Chrome 156.0.8078.80, Playwright Core 1.65.0, DPR 2; both themes and explicit pointer configurations. [Curated proof](visual-polish-repairs-2026-11-07/proof.json) retains every case's outcome, source fingerprints, interaction observations, HTTP classifications, contrast measurements and cleanup. [The manifest](visual-polish-repairs-2026-11-07/screenshot-manifest.json) identifies eight unchanged PNGs; all eight were visually inspected.

| Repaired state | Light | Dark |
|---|---|---|
| Wishlist after editing Notes/Source/printing and returning from Zoom, 390px | [Light](visual-polish-repairs-2026-11-07/wishlist-zoom-light.png) | [Dark](visual-polish-repairs-2026-11-07/wishlist-zoom-dark.png) |
| Unknown Wishlist counts, 390px | [Light](visual-polish-repairs-2026-11-07/wishlist-unknown-light.png) | [Dark](visual-polish-repairs-2026-11-07/wishlist-unknown-dark.png) |
| Own-space member result actions and exclusion reason, 390px | [Light](visual-polish-repairs-2026-11-07/variant-member-light.png) | [Dark](visual-polish-repairs-2026-11-07/variant-member-dark.png) |
| Guide reached from the library, 1440px | [Light](visual-polish-repairs-2026-11-07/guide-desktop-light.png) | [Dark](visual-polish-repairs-2026-11-07/guide-desktop-dark.png) |

Wishlist browser checks at 390px coarse and 1440px fine retained all three local fields through Close, Escape and browser Back, including navigation to the other card and back. Focus returned to Zoom each time. Saved Wishlist digests stayed identical. Explicit sheet closure and reopening recovered the saved values. Unknown-count sheets and known-zero/positive tile controls were checked separately.

Guide checks followed the actual desktop library link, then Back/Forward; copied guide destinations were checked at 390px too. Overview, guide focus and heading clearance passed in both themes. The short fixture can reach the document's scroll limit before the guide reaches the top; the heading still remains visible below the tabs. The new guide topic is fixture content, so these are destination proofs rather than controlled before/after composition comparisons.

The sampled ordinary 14px exclusion reason measured **9.867:1 light** and **9.932:1 dark**, using computed foregrounds, composited ancestor backgrounds and opacity 1 throughout. This qualifies that explanation on those surfaces, not every text colour in the app. Member result screenshots use a synthetic result adapter with the production current-edit-capability helper; production result visibility/capability is separately covered by guarded API tests.

Earlier exploratory runs found harness selector/timing and case-list problems; they were corrected before this final run. Their cleanup completed. No product acceptance is inferred from those failed captures.

## Verification boundaries and next work

Focused guarded tests cover Wishlist count variants/recovery, local draft Save/cancel and route/person disposal; all four home/member deck kinds, permission revocation and stale/changed draft handoffs; actual Commander/partner swaps; guide destinations and late focus callbacks; and active crop Save versus Done+Save, cancellation, load failure, retry/conflict and abandoned picture handlers. Ruff and the source-length guard passed.

The full guarded run ran **12,290 tests, with 456 skips**, and found two outdated source assertions: the prior editor grid's badge placement and a blanket ban on the word `uncommitted` that also matched a local-crop comment. The checks now require full-width narrow-row identity/badge lines and reject retired persistence state in the Save path. After those test-only corrections, all **56 affected accessibility/page/Wishlist/crop/handoff checks passed**. The full suite was not repeated after those corrections; captured application/tool source hashes still match.

Every rendered run used disposable invented records and a temporary headless browser profile. Both HTTP layers retained blanket final-write denial, except existing dry deck checks. No real configuration, household records, visibility settings, Forge games or running service were changed. The final run confirms browser closure, fixture exit 0 and temporary-data removal; saved deck and server-kept draft digests stayed unchanged.

Rendered final Wishlist Save, crop persistence, and final deck publication were deliberately not attempted by this harness. Crop persistence has deterministic DOM/request coverage; database durability and browser persistence remain separate qualification. Guide browser cases use a casual fixture; populated Commander guides, long content, actual browser enlargement, real art, physical Safari/touch/software keyboards and a screen reader remain open.

Next: compare populated deck Overview/library pages with the same restrained visual grammar, and qualify typography/spacing and the remaining page/state families. Keep `E11-S30` open.
