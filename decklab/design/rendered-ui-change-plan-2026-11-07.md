# Rendered UI review: change plan

Date: 7 November 2026, Australia/Brisbane. Status: **proposed; no application fixes implemented by this task**. Owner: `E11-S30`.

The next work should correct misleading information and interrupted editing first, then improve task emphasis and constrained layouts. Keep the current visual system. The screenshots support specific changes to existing components; they do not justify another whole-app redesign.

This plan consolidates the [initial rendered review](rendered-ui-review-2026-11-07.md) and [pass 2](rendered-ui-review-2026-11-07-pass2.md), and adds a fresh screenshot analysis. Those reports retain the original reproductions and their limits. The older [UI-REVIEW.md](../UI-REVIEW.md) describes the already implemented October redesign.

## Fresh evidence and scope

Ran `python scripts/ui_review.py` against commit `58e2e4365daa39da2bc555cfdbd5cfcccb25da5f`: **32 capture cases and the editor interaction suite completed**, with zero failed captures and no uncaught page errors. Browser: Chrome 156.0.8078.80, Playwright Core 1.65.0, DPR 2. Both themes, verified fine/coarse pointer configurations and exact CSS widths were recorded. Application web assets are unchanged from the earlier reports' `ea781f9` pin.

The run used a dedicated disposable synthetic fixture. It read no household configuration or database, ran no Forge games, and permitted only reads and dry-run deck checks. Final deck, receipt, accessory and Wishlist saves were blocked. The editor's saved-deck and kept-draft proofs stayed unchanged. Browser closure, fixture exit 0 and temporary-data removal were confirmed. [Curated proof and all 32 cases' measurements](rendered-ui-change-plan-2026-11-07/review-proof.json) retain these facts without workstation runtime paths.

Fourteen unchanged PNGs are retained in the [manifest](rendered-ui-change-plan-2026-11-07/screenshot-manifest.json). All fourteen were visually inspected; additional failed/running/stale result captures were inspected in the local run. Capturing a case is not a design pass. Pair captures include the already documented missing synthetic opponent destination; that fixture gap is not a product defect.

R06 and O03 were measured again; the member result's missing actions and O02 hierarchy remain visible. R01–R04 were **not interaction-retested** in this run. R07's numeric contrast result belongs to pass 2; it was not remeasured here. No additional confirmed product defect is claimed.

The fresh deck has 60 cards, including 52 Forest. Root-font stress means CSS root/body 32px at 320px, not browser zoom. Synthetic result ordering, scores and extra review prose do not establish production behavior. Placeholder cards do not establish art or printing recognition. Fixed bars appearing midway through full-page PNGs are capture artifacts, not proof that content is unreachable. Receipt captures are viewport images at different scroll positions, so their vertical framing is not a controlled first-screen comparison.

## Screenshot analysis

### Testing: make the selected task lead

The [1440px light board](rendered-ui-change-plan-2026-11-07/board-1440-light.png) and [320px dark board](rendered-ui-change-plan-2026-11-07/board-320-dark.png) show **Popular decks** selected while **Play a matchup** remains the dominant page action. This corroborates O02: the primary action belongs to a different task. The rows already have correctly scoped Play and Details actions.

**Recommended change:** on Popular, let the per-deck actions lead and make pairing secondary. Keep Play a matchup primary on Matchups. Rankings remains a reading task. Do not invent Play all, select a deck silently or start a run when changing tabs.

Current and historical rows also put their figures in different places: current evidence sits right, while historical evidence moves below the left-hand explanation. This makes comparison harder in the [wide dark view](rendered-ui-change-plan-2026-11-07/board-1440-dark.png). A later polish pass can give each row a consistent title/state, evidence and actions structure, while keeping historical evidence explicitly historical. Repeated synthetic notes inflate these captures; deleting production explanations is not supported by that repetition.

### Editor: preserve card identity when text grows

The [light](rendered-ui-change-plan-2026-11-07/editor-root200-320-light.png) and [dark](rendered-ui-change-plan-2026-11-07/editor-root200-320-dark.png) CSS-root stress images show Elvish Mystic and Llanowar Elves reduced to narrow name fragments beside quantity controls, with crowded printing text. All 32 sampled pages had no document-wide horizontal overflow, but that alone does not establish readable rows.

**Recommended experiment:** when row content no longer fits, give the name a full-width line and place quantity, printing/availability and More on subsequent lines. Preserve the original controls, DOM ownership, row identity and keyboard order. Scope the change to constrained rows instead of shrinking text or touch controls. Confirm actual browser enlargement and ordinary long names before choosing its final breakpoint. This is O04, a rendered readability observation; actual 200% browser/OS behavior is still unqualified.

The [empty-list review](rendered-ui-change-plan-2026-11-07/editor-empty-list-review-390-light.png) clearly shows its blocker and disabled final Save in the three-row fixture. After Keep editing, [footer Undo and Discard are disabled](rendered-ui-change-plan-2026-11-07/editor-after-keep-editing-390-light.png) despite a dirty draft and history length 3. Row Undo remains available. That is the existing R06 recovery defect, not total draft loss. Long-diff blocker discovery remains untested.

### Receive delivery: give the checking task more room

At [430px light](rendered-ui-change-plan-2026-11-07/receipt-430-coarse-light.png) and [430px dark](rendered-ui-change-plan-2026-11-07/receipt-430-coarse-dark.png), filters wrap, instructions precede the pictures, and the arrival bar occupies substantial vertical space above the tab bar. Three picture columns measure about 127.3px each, versus 194.5px in the [429px two-column layout](rendered-ui-change-plan-2026-11-07/receipt-429-coarse-light.png): a 34.5% reduction at the declared breakpoint. At [1000px](rendered-ui-change-plan-2026-11-07/receipt-1000-coarse-dark.png), cards and the selected-row guidance occupy separate panes.

**Required correction:** the blank-condition/language recovery button is still 24px high in all 16 receipt configurations. O03 violates this project's coarse-pointer 44px floor. Fix its target and remeasure the expanded bar's clearance.

**Recommended experiment:** keep two picture columns through phone widths, and consolidate repeated instructions into concise default guidance with additional help on demand. Keep the selection count, unknown-metadata recovery, arrival date and explicit review/record actions available. Compare with varied real card art and a larger parcel before choosing the final grid rule. This is O05, a layout recommendation, not a proven recognition failure or a breakpoint malfunction. Measure the usable board area and scroll/focus clearance before changing footer behavior.

### Variant results: restore the next step and readable explanations

The [light](rendered-ui-change-plan-2026-11-07/variant-member-390-light.png) and [dark](rendered-ui-change-plan-2026-11-07/variant-member-390-dark.png) member results still show Play more without the editor return/save handoffs. R05's earlier ordinary editor API control established `may_save: true` for the synthetic own-space member deck. Fix capability handling rather than merely accepting one more ID prefix.

The omitted-opponent explanation is visibly faded. Pass 2 measured its ordinary light text at 3.796:1; R07's fix must retain readable necessary text in both themes. Narrow By group tables also wrap Worse/Better scale labels across lines. A later compact vertical group layout is worth comparing, preserving the identical numerical scale and explicit figures. This latter observation and Testing row alignment are O06 polish, below the correctness and recovery fixes.

## Implementation order

Each row is a bounded slice. Status is **planned**, not built. R02/R05 are P1; the remaining reproduced findings and O03 are P2. O02/O04/O05 are recommended design work; O06 is P3 polish. Complete the confirmed fixes before expanding the polish scope.

| Order | Scope | Concrete change | Source seam / existing regression coverage |
|---|---|---|---|
| 1 | R02: truthful Wishlist counts | Distinguish unknown, known zero and nonzero in both tile and sheet. Unknown says counts are unavailable. | `wishlist.js`; `test_wishlist_ui.py` |
| 2 | R05: permitted result handoffs | Resolve deck kind and current edit capability for home/member casual and Commander. Recheck fresh `may_save` and active route/person before replacing a local draft or navigating. | `variant.js`, existing `core.js` deck helpers; a bounded capability in `lib/api/variant_page.py` if needed; `test_web_variant.py`, `test_variant_api.py`, `test_variant_privacy.py` |
| 3 | R06: usable footer recovery | Synchronize retained Undo/Discard when the current Save/check attempt ends or its review returns. | `editor-save.js`, `editor-screen.js`; `test_editor_action_bar_ui.py`, `test_editor_ui.py`, `test_editor_keyboard_ui.py`, headless editor suite |
| 4 | R01: Wishlist Zoom retains work | Keep the local edit context through the viewer and return to it with Notes, Source and printing intact. | `wishlist.js`, existing `openCardViewer` group/trigger focus return; `test_wishlist_ui.py` |
| 5 | R04: Save includes the visible crop | Outer Save resolves the current active crop into its existing single save request. Done remains a local preview step; cropper Cancel restores its previous geometry. | `accessory-pictures.js`, `accessories.js`; `test_accessory_upload_ui.py`, `test_feature_ui_accessories.py`, `test_accessories_sheet_ui.py` |
| 6 | R03: How to play reaches the guide | Use an explicit supported guide destination, render Overview, then reach the existing guide with sticky clearance. | `library-glance.js`, `deck.js`, existing `app.js` section navigation; `test_library_ui.py`, `test_deck_page_ui.py` |
| 7 | R07: readable exclusion reasons | Remove whole-row fading from necessary text/links; preserve the excluded state through words and appropriate decoration. | `variant.css`, dropped-row markup only if needed; `test_web_variant.py` and rendered composite contrast checks |
| 8 | O03: touch-sized receipt recovery | Use the shared touch token for the recovery control on coarse pointers, with wrapping and measured footer height. | `receipts.css`; `test_device_layout_ui.py`, `test_receipt_bar_ui.py` |
| 9 | O02: selected Testing task leads | Make pairing secondary on Popular/Rankings and primary on Matchups; reuse exact per-deck Popular actions. | `matchups-overview.js`, `gauntlet-board.js`; `test_gauntlet_board_ui.py`, `test_web_matchups.py`, `test_matchups_play_ui.py` |
| 10 | O04: constrained editor rows | Compare a stacked name-first row at narrow/enlarged text and ordinary long names; implement the measured layout. | `editor.css`, row markup only if necessary; editor row/device UI coverage and browser captures |
| 11 | O05: phone receipt layout | Compare two-column phone pictures and concise guidance, then choose the measured layout. | `receipts.css`, existing receipt guidance/bar components; receipt page/bar/selected-row UI coverage |
| 12 | O06: result scanning polish | Compare consistent historical/current board alignment and vertical narrow group results. Ship only improvements supported by populated-state comparisons. | Board/variant CSS and their existing UI tests |

R02 and R01 share Wishlist code and should land sequentially. R05 needs its permission source settled before changing buttons: `editable` is not `may_save`. Existing syntax checks alone do not establish permission. Keep production result visibility/masking and home-only buying rules intact. The adapted Public control in pass 2 is not production authorization acceptance.

R04 needs an explicit active-crop lifecycle before Save integration. Clear its pending handler on Done, Cancel, redraw, image replacement and disposal. Resolve it only for the current owned sheet. Do not scrape visible CSS as crop state. Failed saves must retain the draft for retry.

## Acceptance for the fixes

| Scope | Required behavior after implementation |
|---|---|
| R02 | Cover 3 owned/1 incoming, 0/0, absent/null `have`, and either count individually unknown. No failed read becomes zero. Recovery restores successful counts. |
| R05 | Compare own home/member casual and Commander, generated/unsupported IDs and visible read-only decks. Unknown/refused capability offers no misleading save action. Fresh permission refusal and route/person changes during fetch/confirmation cause no draft replacement or navigation. Permitted handoff has the correct ID/version/changes and remains unsaved. |
| R06 | Ordinary Remove → blocked Save → Keep editing immediately restores correct footer controls without another edit. Repeat failed checks, stale reviews and new/edit modes. A stale sheet cannot update or reclaim focus from a replacement editor. |
| R01 | Edit Notes, Source and printing separately; Zoom, viewer navigation, Escape/Back and close retain the local draft and appropriate focus. Explicit Save persists; explicit cancellation follows the existing discard contract. Route/person changes do not resurrect an old sheet. |
| R04 | Active crop + Save and Done + Save store matching geometry. Cancel retains the old crop. Cover pointer/keyboard, existing/uploaded/staged images, loading/error, retry/conflict and stale ownership without an extra write or weakened hash check. |
| R03 | Library guide action reaches existing guide on phone/desktop and populated Commander/casual decks. Back/forward and no/stale-guide states work. Delayed scrolling belongs to the current route. |
| R07 | Measure final composited foreground/background, including ancestor opacity: ordinary reason/link text meets the UI kit's 4.5:1 requirement in both themes. Exclusion remains explicit. Check other muted families separately. |
| O03 | Recovery target is at least 44px on coarse pointers at 429/430/999/1000 in both themes. Last row, native date and actions remain reachable by scrolling and focus after the bar grows. Blank metadata stays optional; no automatic preview/save. |

For O02, compare every Testing view with populated, empty, failed/no-catalogue and restricted-run states; switching views must not start a simulation. For O04, require readable full card identity, separate printing/facts, working steppers/More and logical focus order at 320px and actual 200% enlargement. For O05, use equal viewport and scroll positions, varied art, a larger/split parcel and a software keyboard; do not decide from placeholder art alone. Preserve receipt selection/drafts, row associations and exact preview/apply semantics.

## Validation and remaining review

Use `python scripts/test_fixtures.py <affected modules>` for each implementation slice, then repeat its relevant screenshot family. Measure changes instead of treating captured PNGs as tests. Update UI-KIT/HISTORY when behavior ships. After the combined fixes, run `python scripts/ui_review.py` and inspect its captures, request classifications, source consistency and cleanup proof. Run the repository's required code/CI checks when implementation is made. This task changes documentation/evidence only.

Add bounded disposable cases as each missing state is needed. Current fixture write denial means Wishlist Save, crop persistence, draft publication and final receipt recording need separately guarded disposable qualification; do not point this harness at the live server or relax its blanket write protections for convenience. R05 also needs a production-authorized read-only result fixture before its full permission experience can be accepted.

The next coverage work, in order, is:

1. **Short real-device viewports and actual enlargement:** 393×700 and 402×720 portrait, short phone landscape, iPad 820×1106/1180×746, MacBook 1470×830, and QHD 2560×1305; both themes and relevant pointer modes. Include scrolled/focused states, editor dock, receipt bar and software keyboard. Current 390×844/320×844 captures do not qualify those geometries.
2. **Longer real UI states over invented records:** a long Save diff with a blocker, populated Commander overview/guide, large/split receipt, Wishlist failure/recovery, crop load/cancel/retry, and production-shaped result handoffs. Keep fixture-added review prose separate from product copy.
3. **Remaining page/state families:** extend the dated coverage ledger for Collection, library, Shopping, Tokens, accessories, Game log, Activity and ancillary sheets. The prior 84-group source assessment remains incomplete as a rendered review.
4. **Household acceptance:** real Safari/iPhone/iPad, touch/software keyboards, screen reader, actual OS/browser text settings and varied real-art recognition. Database durability, genuine cross-device drafts and production saved-result semantics retain their own checks.

Completion of these planned fixes will not by itself close `E11-S30` or the wider rendered review. Close individual findings with new evidence, and keep device and state gaps visible in TODO rather than inferring acceptance from fixture success.
