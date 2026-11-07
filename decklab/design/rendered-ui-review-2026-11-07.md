# DeckLab rendered UI review ? 7 November 2026

Source: `matt439/DeckLab@ea781f9e5e7960690210b4783f4cbf5144918da9`. Review date: 7 November 2026, Australia/Brisbane. This dated report continues an earlier source assessment of 84 screen/state coverage groups.

This pass reproduced four bounded UI problems in disposable synthetic states. It also captured receipt layout observations. It does **not** complete the prior 84-group rendered review, qualify real devices or authorize implementation.

## Prioritized findings

| ID | Priority | Reproduced behavior | Practical effect |
|---|---|---|---|
| R02 | P1 | Wishlist sheet reports “None in your collection yet” when both availability counts are unknown | A failure to read availability becomes a false claim of no owned cards, potentially misleading a buying decision |
| R01 | P2 | Wishlist Zoom closes the editor and loses an unsaved Notes edit | Inspecting the card silently discards local work |
| R04 | P2 | Accessory outer Save succeeds while an active crop remains unapplied | The saved result does not include the visible crop adjustment unless Done was used first |
| R03 | P2 | Library How to play opens the top of Overview | A task-specific link does not reach the existing guide |

Priorities express review judgment about user impact, not a production incident count. R02’s unknown state was deliberately injected; R01, R03 and R04 used ordinary application interactions over synthetic fixture records. No application fix was made.

## Environment and evidence boundary

- Native Chrome controlled through `cua_repl`. The requested Browser connector reported its access host unavailable, so this continuation used native Chrome.
- Real, unmodified DeckLab web assets at the source pin above, served by the repository’s disposable `FixtureServer` with richer synthetic seeds. No household records or live DeckLab service was used.
- Initial Chrome Responsive configuration: 390 × 844 CSS pixels, DPR 2, light. Later captures used 428/430px responsive widths and 1440 × 900 desktop. All captures in this pass are light theme. Responsive emulation is not an iPhone, Safari or physical-touch acceptance pass.
- Seeds: one long-title casual deck with four invented guide topics; known-owned and known-zero Wishlist entries; an unknown-count adapter; shared synthetic sleeves/box; one three-card pending receipt. The same placeholder image was reused, so physical-card recognition cannot be judged.
- Dedicated process with `fixture_runtime` installed before application imports; temporary config/inventory and MemoryStore; database/download/worker denial; loopback-only socket/DNS checks; child-process denial. These are process-local accident guards, not a system sandbox. The fixture implementation is [FixtureServer](../safari/fixture.py); [run metadata](rendered-ui-review-2026-11-07/run-metadata.json) records the guards and synthetic seeds used for this pass.
- The bounded accessory saves described in R04 affected disposable fixture data only. No Wishlist final Save, receipt Record arrival, real Forge run, service management, migration or live-data write was performed.
- Fourteen PNGs were retained. They are evidence artifacts, not fourteen independent passes. Some receipt captures have framing/lazy-image/overlay limitations, documented below.
- Application code was unchanged during the review. This report and its evidence were subsequently added to the repository. The fixture stopped with exit 0, temporary data was removed, its process was absent and its port was closed; see [run metadata](rendered-ui-review-2026-11-07/run-metadata.json).

## R02 — Unknown Wishlist availability is presented as zero

**P1; reproduced at 390 × 844, DPR 2, light.**

The control state for Llanowar Elves was **3 owned, 1 on the way**. A scratch control file then made the fixture’s Wishlist pool unavailable. The resulting API explicitly returned `have: {owned: null, on_the_way: null}` and a warning that collection counts were unavailable. The page displayed that warning, but the item sheet nevertheless said **“None in your collection yet”**.

This is a false zero claim within the item’s decision context, not merely missing information. It does not establish how frequently an equivalent backend failure occurs in production.

**Evidence:** [04-wishlist-unknown-counts-false-zero-390-light.png](rendered-ui-review-2026-11-07/04-wishlist-unknown-counts-false-zero-390-light.png), [wishlist-unknown-response.json](rendered-ui-review-2026-11-07/wishlist-unknown-response.json). The known control counts are recorded in [run-metadata.json](rendered-ui-review-2026-11-07/run-metadata.json).

**Source corroboration:** `decklab/web/wishlist.js:79–83` returns `null` for both unknown counts and known zero/zero. The item sheet at `wishlist.js:228` falls back to “None in your collection yet” for either result.

**Recommended direction:** retain unknown, known zero and known nonzero as distinct states. Say that counts are unavailable in the sheet when they cannot be read; use the zero wording only for a successful zero result. Do not infer ownership from a failed read.

**Acceptance:** render known 3/1, known 0/0, missing/null `have`, and each count individually unknown. Confirm consistent card-tile and sheet wording; failure must never claim zero. Restore successful counts and check recovery.

## R01 — Wishlist Zoom loses an unsaved Notes edit

**P2; reproduced at 390 × 844, DPR 2, light.**

1. Open the synthetic Wishlist item. Saved Notes is `Synthetic saved note: keep me after Zoom.`
2. Replace it with `UNSAVED REVIEW NOTE — preserve after Zoom`.
3. Activate Zoom, then close the viewer.
4. The UI returns to the list. Reopen the item editor.
5. Notes is the original saved value. No Save was clicked and no discard warning appeared.

**Evidence:** [01 initial state](rendered-ui-review-2026-11-07/01-wishlist-known-390-light.png), [02 unsaved replacement](rendered-ui-review-2026-11-07/02-wishlist-unsaved-note-390-light.png), [03 after Zoom/reopen](rendered-ui-review-2026-11-07/03-wishlist-after-zoom-note-lost-390-light.png).

**Source corroboration:** `wishlist.js:199–205` creates Notes from `entry.notes`; the Zoom callback at `wishlist.js:214–219` closes the sheet before opening the card viewer. Its local inputs are not retained by that path.

**Recommended direction:** retain the editor and draft through Zoom, then return to that context when the viewer closes. Keep Save as the explicit persistence boundary. If an action intentionally ends editing, make any discard consequence clear before the work is lost.

**Acceptance:** edit Notes, Source and printing independently; open/close Zoom and navigate the viewer where applicable; retain draft values and sensible focus. Explicit Save persists; explicit cancel/discard follows clear, consistent behavior. Repeat phone/desktop and keyboard paths. These are future checks, not current passes.

## R04 — Outer accessory Save omits the visible active crop

**P2; reproduced at 1440 × 900, light.**

The synthetic sleeves record started with blank crop. In its cropper, dragging the northeast corner produced an approximately **75% × 87%** selection. Activating the outer **Save** without cropper **Done** closed the sheet and reported **“Synthetic Review sleeves saved.”** A fresh API read still had `crop: ""`.

A positive control reopened the record, repeated the adjustment, scrolled until **Done** was visible, clicked Done, then Save. A fresh read now stored `crop: "0,0.1269,0.752,0.8731"`, and the thumbnail showed the crop. The successful control establishes that fixture accessory writes worked; the first result was not caused by a generally unwritable fixture.

**Evidence:** [12 active crop](rendered-ui-review-2026-11-07/12-accessory-active-crop-1440-light.png), [13 Done and Save](rendered-ui-review-2026-11-07/13-accessory-done-and-save-1440-light.png), [14 saved cropped thumbnail](rendered-ui-review-2026-11-07/14-accessory-after-done-save-1440-light.png), [after outer Save JSON](rendered-ui-review-2026-11-07/accessory-after-outer-save.json), [after Done then Save JSON](rendered-ui-review-2026-11-07/accessory-after-done-save.json).

**Source corroboration:** `decklab/web/accessory-pictures.js:170–171` starts local crop geometry, and `accessory-pictures.js:252` copies it to `ctx.pic.crop` only on Done. `decklab/web/accessories.js:731` serializes `pic.crop`; `accessories.js:740–751` permits the outer Save independently. This is the implemented two-stage contract; the rendered concern is that a visible pending adjustment can be omitted while Save reports success.

**Recommended direction:** make the active crop’s save boundary unambiguous. Either apply its current selection with outer Save, or require an explicit Done/Cancel decision before allowing that Save. Preserve deliberate Cancel and avoid silently committing a cancelled crop.

**Acceptance:** active changed crop + outer Save cannot silently report success with the old crop; Done + Save persists; cropper Cancel preserves the old crop; keyboard resizing follows the same rules. Verify footer/cropper action visibility at short desktop and phone heights.

## R03 — How to play lands at Overview’s top

**P2; reproduced at 1440 × 900, light.**

The library’s **How to play** link was visible and clickable for the synthetic long-title casual deck. Activating it opened the generic deck URL with `&v=target` and no guide destination. The first viewport showed the deck hero/readiness, Played at home and Forge content. The guide existed below in DOM section `#sec-guide`.

**Evidence:** [10 library entry](rendered-ui-review-2026-11-07/10-library-how-to-play-1440-light.png), [11 destination](rendered-ui-review-2026-11-07/11-how-to-play-lands-overview-top-1440-light.png).

**Source corroboration:** `decklab/web/library-glance.js:71–80` uses `deckHref(d.id)` without a guide target. `decklab/web/deck.js:424–443` puts `guideSection(data)` last in Overview; `decklab/web/guide.js:11` supplies `id="sec-guide"`.

**Recommended direction:** make this link reach the existing guide through the app’s section-navigation behavior. Preserve the rest of Overview and its lead-feature evidence.

**Acceptance:** reach the guide from the library, preserve expected Back/forward and reading position, handle no-guide/stale-guide states, and repeat on a populated Commander deck/phone. Scroll distance was **not measured** here; neither a full-data Commander state nor Back behavior was exercised.

## Receipt observations — geometry and recovery remain open

The rendered receipt at displayed **428px** showed two picture columns; **430px** showed three. The images visibly lose roughly one third of their width. A rough screenshot-contour calculation, including dark edges/shadows, suggested about **198 versus 132 CSS pixels**; this is not a DOM box measurement and is secondary evidence only. The better comparison PNGs are 856 × 1688 and 860 × 1688 pixels respectively at DPR 2. A displayed 429px emulation state also showed three columns, so emulation rounding or effective-width uncertainty prevents claiming an exact observed breakpoint. Source CSS declares two columns through 429px, and three below 600px otherwise (`decklab/web/receipts.css:105–113`).

Use [05 two columns at displayed 428](rendered-ui-review-2026-11-07/05-receipt-two-columns-428-light.png) and [08 three-column cards at displayed 430](rendered-ui-review-2026-11-07/08-receipt-three-columns-cards-430-light.png) as the better geometry examples. [06](rendered-ui-review-2026-11-07/06-receipt-three-columns-430-light.png) has partial card-top framing, and [07 full capture](rendered-ui-review-2026-11-07/07-receipt-three-columns-full-430-light.png) has lazy-image/overlay capture limitations. Do not treat those as clean like-for-like recognition evidence or missing-art product defects.

[09 selected recovery state](rendered-ui-review-2026-11-07/09-receipt-selected-recovery-430-light.png) shows **1/3** selected, a small **“1 with no condition or language”** recovery control, and Record arrival enabled. No final arrival was recorded. Target size was not computed and pointer mode was not verified; this is not a reproduced touch-target failure. Source `.rcpt-blanks` uses a 24px minimum (`receipts.css:264–270`), which remains a measurement prompt.

The geometry change warrants continued recognition testing; repeated placeholder art cannot establish that physical cards are hard to distinguish. No receipt defect is promoted from these observations alone.

## Coverage and continuation ledger

| Scope | Observed in this pass | Still untested / limited |
|---|---|---|
| Wishlist | Known counts, unsaved Notes/Zoom/reopen, injected unknown counts | Other fields, final Save, error recovery, keyboard/focus, privacy/member states |
| Library → deck guide | Click destination on long-title casual deck, desktop light | Phone/full-data Commander, actual scroll distance, no/stale guide, Back/forward |
| Accessories | Active crop + outer Save; Done + Save positive control; fresh API reads | Phone/short heights, keyboard resizing, cancellation, upload/fetch, ownership restrictions |
| Receipt | Displayed 428/430 layouts, three cards, selected blank-metadata state | Exact effective widths, measured targets/contrast, recognition, 999/1000, larger/split parcels, preview/final record |
| Core editor | No substantive edit workflow qualification | Quick/full editor, Add/free-copy semantics, nested viewer, drafts/conflicts/Save/history |
| Testing | No successful result-state qualification | Popular complete/partial/stale/unreadable, pair/variant results, handoffs, all runs |
| Wider 84-group assessment | Prior source assessment retained | Remaining groups and ancillary dialogs; no blanket rendered completion |
| Device/style | Chromium responsive and desktop, light | Dark, 320px reflow, 200% text/zoom, real Safari/iPhone/iPad, hardware/software keyboard, screen reader, reduced motion |

Fixture gaps observed during this pass: `/api/shopping` returned 500 because the synthetic seed lacks a watchlist; Forge/library summary requests could return 500 when reaching an intentionally forbidden fixture helper. These are fixture coverage limits, not app findings. Do not assess the failed/partial page as its successful full-data state.

## Stopped follow-up and next review order

A follow-up attempt ended before any new rendered checks: the computer-use tool stopped because it could not verify the current browser URL confidently enough to enforce policy. No second fixture was started. Source-derived preparation does not count as rendered evidence, and the four findings above remain the only reproduced product findings in this review.

Continue with disposable synthetic data in this order:

1. Member variant results: editable member-deck return/save actions, with a public read-only control.
2. Editor recovery: nested Add/viewer return, local and kept drafts, save blockers, conflicts and rebase.
3. Populated Testing: complete, partial, stale, failed and unreadable results, including review handoffs without real simulation runs.
4. Responsive checks: receipt boundaries, dark mode, 320px reflow, enlarged text and keyboard navigation. Actual Safari, touch and screen-reader acceptance remain separate.

## Safe continuation

1. Start a fresh dedicated disposable fixture; the service used for this pass is stopped. Workstation-specific scripts, logs, control files and runtime paths are not part of this evidence package. Retain DB/download/worker and loopback guards.
2. Repair only the scratch seed/response coverage needed for the next state. Keep synthetic adapters and ordinary production behavior distinguishable.
3. Continue with exact effective viewport/DPR, theme, pointer, fonts/images and state provenance recorded. Measure receipt geometry/targets before judging recognition or touch suitability.
4. Exercise the pending editor, full-data Commander and Testing states without a real run. Keep live installation, member privacy, real-card recognition and real-device acceptance separate.
5. Any implementation should be a new scoped task with focused regression checks. This request continued review; it did not authorize a speculative redesign or application changes.


## Evidence index

[Machine-readable findings](rendered-ui-review-2026-11-07/rendered-findings.json), [PNG dimensions and SHA-256 digests](rendered-ui-review-2026-11-07/screenshot-manifest.json) and [run metadata](rendered-ui-review-2026-11-07/run-metadata.json) retain this pass separately from the prior source coverage. Raw workstation logs and machine-specific launch files are excluded from the public evidence package.
