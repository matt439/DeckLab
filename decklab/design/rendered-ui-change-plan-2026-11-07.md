# Rendered UI review: change plan

Date: 7 November 2026, Australia/Brisbane. Status: **repair lane implemented; wider visual rollout and acceptance open**. Owner: `E11-S30`.

The [first implementation record](visual-polish-implementation-2026-11-07.md) supersedes the planned status for R06, O03 and O02, and records bounded editor/receipt/board composition work for O04–O06. The [second repair slice](visual-polish-repairs-2026-11-07.md) implements R01–R05 and R07, with 42 rendered cases and separate guarded permission/crop coverage. Browser persistence and device qualification remain open. Earlier observations and acceptance criteria below are retained; original capture reports describe the pre-fix code.

The [populated deck/library slice](visual-polish-deck-library-2026-11-07.md) implements their next composition work, with 38-case paired runs and a repeat of the existing capture/editor suites. Wider typography/state and remaining page-family qualification still follow the visual direction.

Matt's clarified objective is to understand and resolve why the interface looks amateurish, rather than only fix individual defects. The [visual diagnosis and proposed direction](visual-polish-direction-2026-11-07.md) now lead this work. Revise the shared control language, hierarchy and page composition while preserving product behavior, privacy and accessibility. The functional fixes below remain a separate necessary repair lane; completing them alone will not deliver a polished interface.

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

The omitted-opponent explanation is visibly faded. Pass 2 measured its ordinary light text at 3.796:1; R07's fix must retain readable necessary text in both themes. Narrow By group tables also wrap Worse/Better scale labels across lines. A later compact vertical group layout is worth comparing, preserving the identical numerical scale and explicit figures. O06's stable Testing row alignment contributes to the core visual composition alongside repairs; optional narrow-group refinement follows that work.

## Typography, emphasis, colour and useful space

Added after Matt's follow-up on 7 November: the initial plan considered enlargement, contrast and some layout allocation, but did not systematically review all these visual choices. **O07 is an explicit cross-page visual audit**, to run alongside the fixes and before choosing the layout changes in slices 9–12. A new serious readability finding takes its appropriate priority; typography and spacing are not automatically low-priority polish. This section proposes the audit and records bounded visual judgments, not a completed computed-style audit.

The current baseline is declared in [tokens.css](../web/tokens.css), [base.css](../web/base.css) and the [UI kit](../UI-KIT.md): Figtree for UI/prose, JetBrains Mono for numerical evidence and code, semantic size/weight tokens, and a 4px spacing ladder. Casual, touch-lab and fine-pointer lab densities have different intended sizes. Those declarations are verified source facts; the rendered value of each element still needs measuring. The sampled board, result and blocker screenshots generally distinguish headings, item names and supporting facts. They provide no reason to replace the font families globally.

| Aspect | What to assess | Recommended starting direction |
|---|---|---|
| Font family | Readability of names, prose, controls and numerals; actual loaded face/fallback, italic face and alignment of comparable figures. | Retain Figtree and JetBrains Mono in their existing roles. Keep printing labels and ordinary words in the reading font; avoid making a whole sentence mono just because it contains a number. Confirm guide/Notes prose and special characters separately. |
| Size, line height and line length | Actual CSS-pixel sizes at each density; heading/body/meta distinction; long titles, wrapping, enlarged text and text over art. | Use semantic type tokens and readable supporting text. Fix constrained allocation before shrinking text, as with O04's fragmented editor names. Keep reading lines bounded on large screens; compare the actual short laptop/phone viewports as well as large captures. |
| Boldness | Whether the first, second and supporting facts have a clear order; how many elements compete through heavy text, filled buttons or badges. | Use regular text for prose and supporting facts, stronger weights for names/key figures, and the strongest emphasis for the page/task lead. Start from existing weight tokens; do not make every line bold. O02 needs action emphasis to match the selected task. |
| Italics | Whether emphasis has meaning and remains readable, including rules reminder text, guides and Notes. | Retain semantic reminder/emphasis styling. Avoid long italic instructions and using italics alone to convey a warning, state or action. No misuse was established in the sampled screens; prose-heavy examples remain to inspect. |
| Underlining | Whether readers can distinguish links, card-inspection links, buttons and ordinary labels, including hover/focus/touch behavior. | Keep inline links recognizable and the existing dotted treatment for inline card links where appropriate. Avoid decorative underlining on noninteractive text. Do not depend on hover to reveal that an inline action exists. No general underline defect was established by these samples. |
| Colour and opacity | Text on its final composited surface, links, selection, warning/error, deck identity and historical/disabled states in both themes. | Preserve the current semantic palette. Use colour with words/icons for states; keep action/selection emphasis intentional. R07 requires readable exclusion reasons rather than whole-row fading. A smaller/lighter caption is not a solution for important text competing with a heading. |
| Spacing and alignment | Margins, padding, row/column gaps, grouping, reading width, distance from a fact to its action, and usable content area after sticky/fixed chrome. | Keep gaps within a task smaller than gaps between tasks. Reclaim space from repeated guidance, arbitrary minimum heights and disconnected controls before reducing readable type, card size or touch separation. Reflow related content together; do not fill every blank area. |

### Where whitespace earns its place

Keep room around paragraphs and section headings so people can read and group information; between controls so taps are distinct; inside cards so text does not crowd their edges; and around a consequential confirmation so its decision is clear. A bounded text column can deliberately leave unused width on a large screen. Reserved space can also prevent disruptive movement while content loads. Each serves a task and should survive a density change when still useful.

On the wide Testing board, some right-hand space comes from deliberate results/reading-width limits (`.gb` is capped at 64rem; its introduction at 72ch). Stretching the prose across the window to consume that space is not the goal. Instead check whether titles, figures and their actions stay easy to associate. The current/historical alignment difference in O06 is a more concrete improvement candidate than the mere presence of a blank right edge.

On the phone receipt, the instruction/filter/help stack and arrival bar compete with the checking area. O05 should first compare shorter repeated guidance and better grouping at equal viewport/scroll positions. Keep useful separation around the arrival action and preserve touch targets. On the enlarged-text editor, space is misallocated when the name becomes a sliver beside controls: reflow the row so the name can use the width rather than compressing everything equally.

### Audit record and acceptance

For each representative page and sheet, record the title, section heading, item/card name, body instruction, metadata, key number, link, primary/secondary action and state message. Capture each element's font family, size, weight, style, decoration, line height, foreground/background/ancestor opacity, available width and wrapping. Record container padding/gaps and the viewport area consumed by fixed/sticky controls. Keep measured values separate from judgments about hierarchy or wasted space.

Compare both themes at the relevant casual, touch-lab and fine-pointer lab widths, with long/short content, empty/populated/error states, 320px reflow and actual 200% enlargement. Include guide/Notes prose to qualify italics and inline-link treatment, and real-art backgrounds where text overlays them. Before/after captures must use the same content, viewport, pointer, theme and scroll position. Accept a change when the intended reading/action order is clearer, important words remain readable, related controls remain associated, and the existing touch/focus/contrast requirements hold. A lower whitespace percentage or fewer pixels scrolled is not, alone, a successful design outcome.

Use the existing typography, colour and spacing tokens; component changes belong in the shared component owner. If a shared token itself is wrong, compare its effects across representative pages before changing it globally. O07 produces element-level findings with evidence and priorities, then feeds the relevant slice instead of authorizing blanket size, boldness or colour changes.

## Implementation order

The [visual direction](visual-polish-direction-2026-11-07.md#delivery-order) owns the overall delivery order: prove the shared design on representative screens, implement the common visual foundations, then compose each task page and extend the comparison. The following table retains the repair order and source seams; the implementation record above identifies delivered scopes. R02/R05 are P1; the remaining reproduced findings and O03 are P2. O02/O04/O05 also contribute to the visual direction. O06's board alignment is implemented; optional narrow-group polish follows it.

O07's typography/space audit accompanies the relevant slices and informs layout decisions before slices 9–12. Its page/element findings receive their own measured priority; it is not a completed audit or a thirteenth blanket restyling task.

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

Use `python scripts/test_fixtures.py <affected modules>` for each implementation slice, then repeat its relevant screenshot family. Measure changes instead of treating captured PNGs as tests. Update UI-KIT/HISTORY when behavior ships. After the combined fixes, run `python scripts/ui_review.py` and inspect its captures, request classifications, source consistency and cleanup proof. Run the repository's required code/CI checks when implementation is made.

Add bounded disposable cases as each missing state is needed. Current fixture write denial means Wishlist Save, crop persistence, draft publication and final receipt recording need separately guarded disposable qualification; do not point this harness at the live server or relax its blanket write protections for convenience. R05 also needs a production-authorized read-only result fixture before its full permission experience can be accepted.

The next coverage work, in order, is:

1. **Short real-device viewports and actual enlargement:** 393×700 and 402×720 portrait, short phone landscape, iPad 820×1106/1180×746, MacBook 1470×830, and QHD 2560×1305; both themes and relevant pointer modes. Include scrolled/focused states, editor dock, receipt bar and software keyboard. Current 390×844/320×844 captures do not qualify those geometries.
2. **Longer real UI states over invented records:** a long Save diff with a blocker, populated Commander overview/guide, large/split receipt, Wishlist failure/recovery, crop load/cancel/retry, and production-shaped result handoffs. Keep fixture-added review prose separate from product copy.
3. **Remaining page/state families:** extend the dated coverage ledger for Collection, library, Shopping, Tokens, accessories, Game log, Activity and ancillary sheets. The prior 84-group source assessment remains incomplete as a rendered review.
4. **Household acceptance:** real Safari/iPhone/iPad, touch/software keyboards, screen reader, actual OS/browser text settings and varied real-art recognition. Database durability, genuine cross-device drafts and production saved-result semantics retain their own checks.

Completion of these planned fixes will not by itself close `E11-S30` or the wider rendered review. Close individual findings with new evidence, and keep device and state gaps visible in TODO rather than inferring acceptance from fixture success.
