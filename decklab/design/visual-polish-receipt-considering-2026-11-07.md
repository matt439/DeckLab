# Visual polish: receipt tools and empty Considering

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This implements the next bounded slice of the [visual direction](visual-polish-direction-2026-11-07.md); the redesign remains partial.

## What changed

Receipt filters keep their original native buttons, pressed state, row counts and predicates, but omit the enclosing grey track. On phones they use the available toolbar width. Relative container queries use two columns when constrained, then one under severe text/width constraint so labels need not break mid-word. The existing selected outline, keyboard focus, forced-colour treatment and touch floors remain inherited from the shared component.

A single card/token part groups **Everything arrived as ordered** beside **Tools** below the filters. Mixed orders retain the one delivery-level shortcut above the board, outside unselected parts; whole products retain that scope too. The original node is reparented through board redraws. Its confirmation, selection, hiding and focus recovery remain, as do per-part tools, exact row associations, drafts, checks and preview/apply. Picture-column rules are unchanged.

An empty Considering section in full and Quick editors has one heading, zero count and Add action. The original explanation is in native **About Considering** help. Duplicate empty prose and the empty row region are removed. Populated alternatives retain their existing rows, actions and explanation. Add/Remove/Undo remain local draft changes, joining normal check/Save.

## Matched comparisons

Both phases use the same invented decks/cards, viewport/pointer/theme settings, capture sequence and finalized comparison harness, on Chrome 156.0.8078.80 / Playwright Core 1.65.0 at DPR 2. The kept-draft notice's run-local time varies; it is not deck data or a typography change. Baseline application source is `2031a1e`. Source fingerprints, measurements, requests and process cleanup are retained in the [proof](visual-polish-receipt-considering-2026-11-07/proof.json); the [manifest](visual-polish-receipt-considering-2026-11-07/screenshot-manifest.json) identifies unchanged screenshot bytes. All sixteen retained images were visually inspected, with selected originals also checked at full size.

| Screen | Before | After |
|---|---|---|
| Receipt, 430px light | [Before](visual-polish-receipt-considering-2026-11-07/before-receipt-430-light-top.png) | [After](visual-polish-receipt-considering-2026-11-07/after-receipt-430-light-top.png) |
| Receipt, 430px dark | [Before](visual-polish-receipt-considering-2026-11-07/before-receipt-430-dark-top.png) | [After](visual-polish-receipt-considering-2026-11-07/after-receipt-430-dark-top.png) |
| Empty Considering, 393px light | [Before](visual-polish-receipt-considering-2026-11-07/before-considering-393-light.png) | [After](visual-polish-receipt-considering-2026-11-07/after-considering-393-light.png) |
| Empty Considering, 393px dark | [Before](visual-polish-receipt-considering-2026-11-07/before-considering-393-dark.png) | [After](visual-polish-receipt-considering-2026-11-07/after-considering-393-dark.png) |
| Empty Considering, 820px light | [Before](visual-polish-receipt-considering-2026-11-07/before-considering-820-light.png) | [After](visual-polish-receipt-considering-2026-11-07/after-considering-820-light.png) |
| Empty Considering, 820px dark | [Before](visual-polish-receipt-considering-2026-11-07/before-considering-820-dark.png) | [After](visual-polish-receipt-considering-2026-11-07/after-considering-820-dark.png) |

At 430px the receipt grid begins **54px earlier**, at y=401px versus 455px, with the same checked row and footer. The toolbar itself grows from 90px to 96px: the gain comes from grouping the bulk action with the tools rather than leaving a separate leading row. The calmer filters and nearby utility row make the checking area easier to identify. This is an allocation/design judgment for these records, not evidence about recognizing real card art.

Empty Considering measures **222px to 105px at 393px**, and **198px to 105px at 820px**, in both themes. Add now accompanies the empty heading, while general explanation remains available without preceding the next task. Captures target an 80px section clearance; shorter final pages can reach their scroll limit first, so the before/after section y-coordinate is not always identical. Compare section height and composition rather than implying equal scroll offsets.

## Verification and boundaries

The opt-in `python scripts/ui_review.py --suite task-layout` completes **28/28 cases per phase**: receipt at 320/393/430/600/820/1440px, empty editors at 320/393/820/1440px, and explicit CSS root-font stress at 320/600px for both tasks, in both themes. Twenty ordinary cases use pointer clicks; eight root-font cases use native keyboard activation. Local selection, layout, filters and note preferences remain; Considering help and Add open/close, dirty state remains stable, and saved deck responses are unchanged. The separate final **44-case capture matrix and editor interaction sequence** also complete with unchanged saved data and confirmed cleanup.

Matched runs have stable source fingerprints, no uncaught page or unexpected HTTP errors, and no document overflow in their retained snapshots. These snapshots do not cover every transition. Only the existing dry deck check is allowed; final saves, arrival recording, visits, external requests, database access and Forge execution retain the fixture guards. Browser closure, fixture exit 0 and private-runtime removal are confirmed.

The delivery scope regression covers one retained shortcut through redraw, cancellation without changes, confirmation, focus after hiding, mixed orders with every part off, and a product's still-explicit storage choice. Empty Considering regression covers Add, last Remove focus and Undo in full/Quick modes without a write or playable-list change. Existing receipt and editor suites retain preview/apply, stale ownership and populated behavior coverage.

All **2,939 guarded UI fixture tests** passed in 256.957 seconds. Final focused web/device/receipt/editor/harness/privacy/source checks ran **137 tests, one existing directory-symlink skip**, in 31.690 seconds. Ruff, JavaScript syntax, whitespace and the source-length guard passed. The unrelated full backend suite was not repeated; database integration, native runtime and real devices retain their own qualification.

The paired proof's `receiptEverything` field is unpopulated because its initial measurement selector used an abbreviated label. It is not evidence that the shortcut is absent. Screenshots and lifecycle tests establish placement; a subsequent measurement-only selector repair and eight-case after-only smoke provide the corrected field. They do not replace the original matched comparisons.

**Enlarged receipt qualification remains open.** Preliminary pointer runs reproduced a Tools layout control outside the hit area after switching to List at 320px root stress, and a card checkbox blocked by the fixed footer at 600px root stress. Both rejected runs and cleanup are retained in the proof. Native keyboard activation completes the matched matrix, but does not establish those pointer problems fixed. At 600px root stress the footer measures 1,488px high in a 700px viewport, unchanged between phases. At 320px the final readable single-column toolbar is taller than baseline. This slice does not claim successful enlarged-text receipt usability merely because retained snapshots fit horizontally.

These are **CSS root-font stress cases**, not actual browser zoom or OS text scaling. Next: receipt enlargement/pointer/footer and scrolled last-row/focus coverage, followed by remaining populated/error/busy page families. Large/split parcels, varied real art, software keyboards, real Safari/touch, screen readers, browser persistence and production durability remain separate acceptance. No household records, visibility switches or real games were used or changed; the normal local server stays stopped.
