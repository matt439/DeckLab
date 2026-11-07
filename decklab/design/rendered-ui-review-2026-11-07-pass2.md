# DeckLab rendered UI review - continuation pass 2

Date: 7 November 2026, Australia/Brisbane. Application source pin: `ea781f9e5e7960690210b4783f4cbf5144918da9`. During this pass the checkout was `1bbda39bae4bcb7df634e68daf171c32cb59423a`; the intervening commit contains only the first review documentation/evidence. A current diff verified the web assets, fixture sources and runtime guard unchanged from the application pin.

This pass continues [the first rendered report](rendered-ui-review-2026-11-07.md). The first pass's four reproduced findings remain recorded there; they are not automatically retested or fixed by this continuation. The wider 84-group source review is not equivalent to completed rendered coverage.

**Reusable workflow:** the [headless review command](../ui_review/README.md) is now checked in. The dated evidence below retains this run and its original scratch-tool provenance.

## Scope and evidence boundary

Requested order: member variant actions, editor recovery, populated Testing, then responsive/style/keyboard checks. Only disposable invented records and explicit synthetic result payloads are permitted. No real Forge games, household records, production writes or application implementation are part of this review.

This report separates executed observations from pending cases. Browser, viewport/theme, adapters and fixture isolation are recorded below; unknown pointer/computed metrics remain explicit. A prepared state or HTTP 200 is not a visual pass. Synthetic saved results can validate presentation and action availability, not production ranking, simulator correctness or real-device behavior.

## Environment

- Native Chrome through CUA supplied 25 captures. After the explicit request to use a script, isolated headless Chrome supplied 35 additional published images without native input. Headless runtime: installed Chrome 156.0.8078.80 with scratch Playwright Core 1.65.0; no automation dependency is committed to DeckLab. Native captures retain their unmeasured pointer/effective-width limits; headless DOM metrics are recorded separately below.
- Fresh dedicated FixtureServer with temporary FileInventory/MemoryStore records. The runner retains pre-import fixture guards, database/download/worker denial, loopback-only socket/DNS checks and child-process denial. No real result generation or Forge run is represented.
- An allowlisted scratch identity transport selects synthetic Matt or User2. It models a tunnel identity so ordinary profile/space/edit permissions can run against synthetic config. This is not Cloudflare Access or authentication acceptance.
- Result GET adapters supply invented variant/pair/board JSON while leaving web JavaScript unmodified. Variant adapters bypass the production result-read authorization/masking path; this limits the public read-only control below. See [fixture provenance](rendered-ui-review-2026-11-07-pass2/run-metadata.json) for adapter provenance and limitations.
- The synthetic home deck is Public only in temporary MemoryStore to provide a member read-only control. The synthetic member deck stays private. No real visibility switch was changed.
- The first four screenshots and ordinary editor permission responses are recorded below. Variant next-action handoff/save was not activated. The editor checks below caused no successful browser deck save; a deliberate scratch control created one external synthetic baseline change. No real simulation action was executed.
- No application source changes were made by this review. Scratch fixture scripts and raw logs remain outside the repository. This report and its sanitized evidence were subsequently added to the repository.

## Findings from this pass

| ID | Priority | Reproduced behavior | Scope |
|---|---|---|---|
| R05 | P1 | Member variant omits Back to the editor and Save this change despite own-deck `may_save: true` | Unmodified renderer with synthetic result GET; ordinary editor permission control |
| R06 | P2 | Keep editing after a blocked Save leaves footer Undo/Discard disabled | Native More/Remove actions; draft and row Undo remain available |
| R07 | P2 | Omitted-opponent explanation renders at 3.796:1 contrast in light | Actual rendered normal explanation text; one bounded state |

O02 below is a hierarchy observation. R07 is a bounded rendered contrast finding, not a whole-site conformance claim.

## R05 - Member variant result omits the editor next actions

**P1; reproduced in the unmodified renderer over synthetic result data.** Reported viewport 1440 x 900, light.

The home variant result displays **Back to the editor** and **Save this change** beside Play more. The otherwise equivalent member result for `user2/casual/member-fixture` displays only Play more. Its ordinary member editor is accessible with enabled card controls and Save. Fresh ordinary editor API reads report `may_save: true` for the member's own deck. The missing result actions therefore cannot be explained by that member lacking edit permission on the synthetic deck.

**Evidence:** [home actions](rendered-ui-review-2026-11-07-pass2/p2-01-home-variant-actions-1440-light.png), [member actions missing](rendered-ui-review-2026-11-07-pass2/p2-02-member-variant-missing-actions-1440-light.png), [ordinary member editor enabled](rendered-ui-review-2026-11-07-pass2/p2-03-member-editor-enabled-1440-light.png), [permission summary](rendered-ui-review-2026-11-07-pass2/variant-permission-control.json), [ordinary editor permission responses](rendered-ui-review-2026-11-07-pass2/editor-permission-controls.json).

**Source corroboration:** `decklab/web/variant.js:545-548` checks the base ID with `/^(casual|commander)\//` for each next action. A space-prefixed ID does not satisfy that test. The page is running the real unmodified JavaScript; the adapter supplies its structured result state.

**Recommended direction:** derive supported deck kind and next-action availability from the existing deck-ID and edit-permission model. Keep allowed member decks usable while retaining read-only behavior when editing is forbidden. Save this change must retain its existing reviewed editor handoff semantics rather than imply immediate persistence.

**Acceptance to verify after a fix:** compare editable home and member casual/Commander IDs, unsupported/generated IDs and a visible read-only control. An allowed member gets the same appropriate next actions; a viewer without edit permission gets no misleading edit/save action. Open the handoff in a disposable fixture and verify correct deck identity and unsaved draft contents. No handoff or final save was executed in this recorded comparison.

### Public read-only render control - not backend authorization acceptance

Under synthetic User2, the ordinary editor API for the Public home deck reports `may_save: false`, with the normal own-collection refusal reason. The adapted home variant result still displays Back to the editor and Save this change: [render control](rendered-ui-review-2026-11-07-pass2/p2-04-public-home-variant-render-control-1440-light.png). The `editable` field is true in both ordinary editor answers, so it must not be mistaken for the actual `may_save` permission.

This control demonstrates that the current **renderer** follows the syntactic ID branch for the supplied result, independently of the ordinary editor save permission. The adapter bypasses production variant-read authorization and masking, and no save/write was attempted. It is **not a reproduced unauthorized server read/write or a new security finding**. A production-authorized result fixture is still required before judging the complete read-only result experience.

## R06 - Blocked Save leaves footer Undo and Discard disabled

**P2; reproduced with native ordinary controls at 1440 x 900, dark.** This is a footer recovery-state defect, not global draft loss.

1. Start with the clean synthetic 61-card deck, including 53 Forest.
2. Use each of the three card rows' ordinary **More -> Remove** actions. No direct quantity injection was used for this qualification.
3. The draft is now empty with three changes; footer **Undo** and **Discard** are both enabled. [Before Save](rendered-ui-review-2026-11-07-pass2/p2-19-native-empty-draft-controls-enabled-1440-dark.png).
4. Activate footer Save. The actual empty-list blocker review opens, with its final Save disabled.
5. Choose **Keep editing**. The draft remains visible, main footer Save is enabled to revisit review, and each removed row's own Undo is enabled, but footer **Undo** and **Discard** are now disabled. [After Keep editing](rendered-ui-review-2026-11-07-pass2/p2-20-native-keep-editing-footer-disabled-1440-dark.png).
6. Use the Forest row's Undo: 53 Forest return, and a redraw restores the footer Undo/Discard enabled state.

No Empty the deck anyway action or successful Save write occurred. The remaining per-row recovery worked. Keyboard recovery was not tested, so this is not classified as total inability to undo or discard work.

**Source corroboration:** `editor-save.js:435` sets `ed.saving`; `editor-screen.js:1003,1005` derives footer disabled states from it. The save finally block clears `ed.saving` but only unbusies Save and refreshes keyboard hints (`editor-save.js:460-463`), without redrawing those retained footer controls. This explains why a later ordinary redraw restores them.

**Recommended direction:** refresh the retained footer action states when the save/check attempt ends and when returning from its review, using the current editor ownership guards. Preserve the blocked save and draft; do not turn Keep editing into persistence.

**Acceptance:** create an empty draft through ordinary Remove, open Save's blocker, choose Keep editing: footer Undo/Discard reflect the current live draft and history immediately. Repeat a stale-save review and a failed check, compare new/edit modes and ensure closing a stale or foreign sheet cannot update a newer editor. Verify the same recovery without an extra edit/redraw. This review did not implement or test a fix.

## Editor observations - bounded recovery paths exercised

Reported viewport **390 x 844, light**, over ordinary temporary editor/draft APIs. The initial phone recovery sequences below did not reproduce a defect; the separate native desktop qualification reproduced R06 above.

### Add inspection and Undo

In the phone Add sheet, searching Opt and opening its card viewer worked. Closing the viewer returned to the same Add query/result. Adding one Opt made the draft **61 cards**, with **1 unsaved change / +1 copies**. Done closed Add; Undo returned the deck to 60. Evidence: [nested viewer](rendered-ui-review-2026-11-07-pass2/p2-05-editor-nested-viewer-390-light.png), [added card/dirty draft](rendered-ui-review-2026-11-07-pass2/p2-06-editor-added-opt-dirty-390-light.png).

This qualifies the observed Add-search/viewer state and one-card Undo path. It does not establish that every Notes, printing, deck-details or nested-picker draft survives every inspection path.

### Leave guard and local resume

Increasing Forest from 52 to 53 made a local draft. Trying Decks opened **Leave without saving?**; Keep editing retained 53. Leaving again through **Leave, and keep them for later**, then reopening the editor, restored the local draft and showed an Unsaved changes banner with 61 cards. Evidence: [leave guard](rendered-ui-review-2026-11-07-pass2/p2-07-editor-leave-guard-390-light.png), [local draft restored](rendered-ui-review-2026-11-07-pass2/p2-08-editor-restored-local-draft-390-light.png).

This is local-device draft recovery. The later kept-for-later sequence below exercises the ordinary draft API against MemoryStore; actual database/cross-device behavior and collision handling are separate.

### Kept-for-later draft and Resume

A separate native-control sequence at **1440 x 900, dark** started from saved Forest53, used the row's plus action to make Forest54 / 62 cards, then chose **More ways to save -> Save draft for later**. The ordinary draft API returned `available: true`, `revision: 1`, a base of Forest53 / 61 cards and draft content Forest54 / 62 cards. A [compact proof](rendered-ui-review-2026-11-07-pass2/kept-draft-proof.json) retains these facts; the bulky raw answer stays outside the publication package.

After explicitly discarding only the local draft, reloading showed the saved deck with Forest53 and **A draft kept for later**. Resume it restored the Forest54 / 62-card unsaved draft with **You picked up the draft kept for later**. Evidence: [kept draft entry](rendered-ui-review-2026-11-07-pass2/p2-21-kept-draft-entry-1440-dark.png), [resumed draft](rendered-ui-review-2026-11-07-pass2/p2-22-kept-draft-resumed-54-1440-dark.png).

The UI's Android device label came from the emulated User-Agent. This was the same browser with temporary MemoryStore, not actual Android, database durability, cloud synchronization or physical cross-device qualification. The ordinary deck itself was not saved. The on-every-device discard action was not used. Collision cases remain pending.

### Stale baseline and explicit reapply

The scratch external-change control saved a fresh synthetic baseline with **53 Forest** (the browser draft's original baseline had 52). Save then showed the changed-deck refusal and an explicit reapply choice. Reapply produced a local draft of **54 Forest / 62 cards**, with the clear explanation that the latest version has 53, the base had 52, and the local +1 makes 54. A fresh API read still held 53, proving reapply did not automatically save the browser draft. Discarding the rebase, with confirmation, returned to the latest saved 53.

Evidence: [stale-save review](rendered-ui-review-2026-11-07-pass2/p2-09-editor-conflict-review-390-light.png), [reapplied draft](rendered-ui-review-2026-11-07-pass2/p2-10-editor-rebased-54-390-light.png), [compact persistence proof](rendered-ui-review-2026-11-07-pass2/editor-rebase-proof.json). Bulky raw editor responses are not needed for the public evidence package.

### Empty Planned list blocker

Setting the three list quantities to zero and using Save opened the normal review. The three removed-card rows preceded the blocker, but **This can't be saved yet** was visible within the first viewport and final Save was disabled. **Empty the deck anyway** was not activated. Evidence: [empty-list review](rendered-ui-review-2026-11-07-pass2/p2-11-editor-empty-save-blocker-390-light.png).

This confirms the source order in the small three-row case without reproducing the hypothesized long-diff blocker-discovery problem. Long diffs, other full editor pane variants and other blocker families remain untested. Ordinary sub-60 casual size is a warning, not this empty-list confirmation blocker.

Source corroboration for retained recovery behavior: `editor.js:826` owns the leave choice; `editor-screen.js:241-275` renders local draft/reapply/stale notices; `editor-save.js:339-347` owns the empty-list confirmation and `editor-save.js:560-563` the explicit stale reapply actions.

## O02 - Popular decks keeps a two-deck pairing as its lead action

**Hierarchy observation; source hypothesis borne out at 390px, light.** This is a task-emphasis judgment, not a claim that the pairing button misstates its literal label or fails to work.

With Popular decks selected, the page's dominant **Play a matchup** action opened the ordinary **Deck 1 / Deck 2** pairing sheet. The sheet was closed without Start. The prominent action therefore belongs to the two-house-deck task while the visible lead view is about a deck against popular opponents. The Popular rows' own Play actions remain secondary.

Evidence: [lead action opens pairing](rendered-ui-review-2026-11-07-pass2/p2-12-popular-lead-opens-pair-sheet-390-light.png). The selected Popular view is also shown in [320px dark layout](rendered-ui-review-2026-11-07-pass2/p2-14-popular-320-dark-keyboard-focus.png) and [wide mixed board](rendered-ui-review-2026-11-07-pass2/p2-15-popular-all-states-1440-dark.png). Source `matchups-overview.js:525-532` creates this global primary from `openPlaySheet`, independently of the selected view's task.

Recommended direction: let the selected Testing view determine the lead task/action hierarchy, while retaining the existing two-deck flow and permitted per-row actions. Preserve the intended Popular-first navigation and simulation gates. This remains a scoped product decision before implementation.

Acceptance: opening each Testing view makes its appropriate lead task clear before activation; any pairing action still says and does pairing; each Popular action retains its own deck/sample scope. Repeat with no results, a failed board, restricted run permissions and phone/desktop. No run was started here.

## Testing and responsive observations

### Mixed Popular board, failure and retry

The unmodified renderer displayed all five synthetic board states: **complete 54%, 20/20 opponents**; **partial 67%, 3/20**, with Partly tested; changed-list historical **48%**; older-engine historical **61%**; and an unreadable-list reason. Dark captures include [390px mixed rows](rendered-ui-review-2026-11-07-pass2/p2-13-popular-mixed-390-dark.png) and [1440px all five states](rendered-ui-review-2026-11-07-pass2/p2-15-popular-all-states-1440-dark.png).

Case `failed` returned a deliberate board HTTP503 and produced a visible failure with Try again. After changing the fixture back to complete, activating Try again restored the Synthetic complete board. Evidence: [failure](rendered-ui-review-2026-11-07-pass2/p2-16-popular-failed-1440-dark.png). This qualifies that injected failure/retry presentation, not production service reliability.

The board order is invented. The extra UI-review notes and Commander 1v1/sample sentence are adapter prose, not verified production wording. Most row IDs are unseeded, so deep Details destinations are outside this fixture's coverage. No sorting, ranking, sample validity or numerical simulation correctness is established.

### Pair complete and stale-list states

The pair renderer showed an invented **57%**, **54-60%** range, **800 games**, format/life scope and its ordinary result controls: [complete pair](rendered-ui-review-2026-11-07-pass2/p2-17-pair-complete-1440-dark.png). Switching the fixture to stale produced an Older list warning and **Today's lists** in place of adding more games to the old result: [stale pair](rendered-ui-review-2026-11-07-pass2/p2-18-pair-stale-list-1440-dark.png).

These are renderer-state checks only. The second deck is not seeded for deep navigation, no details were opened, and no Play more/Today's lists run was started. Production result reads, backend authorization, confidence calculation and opponent data integrity remain unqualified.

### Dark mode and narrow keyboard spot check

Dark was chosen through the app avatar and saved only in temporary profile MemoryStore. At **320px**, the operator observed the Testing heading, lead buttons, view/format controls and navigation wrapping. After clicking the Testing heading, three Tab steps focused Play a matchup, Try a precon and Popular decks with visible focus rings. [Narrow capture](rendered-ui-review-2026-11-07-pass2/p2-14-popular-320-dark-keyboard-focus.png).

This native sequence is a bounded visual/focus spot check. The later headless captures add document-width measurements for the sampled pages; neither establishes complete keyboard operation, modal focus qualification or mobile/Safari acceptance.

## R07 - Light omitted-result explanation has insufficient normal-text contrast

**P2; measured in the actual 1440 x 900 light renderer.**

A pixel audit of [the member variant capture](rendered-ui-review-2026-11-07-pass2/p2-02-member-variant-missing-actions-1440-light.png) found the omitted-opponent explanation rendered with repeated flat foreground RGB `(124,129,125)` over row background `(250,250,248)`, yielding **3.796:1**. The foreground occurs in 1,038 pixels in the explanation's text area, rather than merely on antialias fringes. See [measurement provenance](rendered-ui-review-2026-11-07-pass2/variant-light-contrast.json).

This matches the real renderer's dropped-row branch (`variant.js:573-574`), ordinary `.sub` text using `--ink-2`, and parent opacity `.65` (`variant.css:62,66`). The source sets `--fs-sm: .875rem`; this is ordinary-sized text at the recorded viewport. W3C requires 4.5:1 for ordinary text, with separate exceptions for large or incidental/inactive content: [SC 1.4.3](https://www.w3.org/TR/WCAG22/#contrast-minimum).

The native UI operator confirmed that this is ordinary explanatory text stating why an opponent was omitted, not an inactive control. The measured 3.796:1 is below the 4.5:1 ordinary-text threshold. This finding is limited to that rendered light state; it does not establish every muted field/gauntlet/variant state, dark theme contrast or whole-site conformance.

Recommended direction: preserve readable exclusion reasons and links while de-emphasizing appropriate chart/decorative content. Avoid fading the entire row's necessary reading text.

Acceptance: verify the reason's foreground against its final composite background, including parent opacity, at normal text size in both themes. Meet the ordinary-text contrast threshold without hiding the reason or implying the omitted games count. Repeat the other actual muted result-row families separately; their source similarity is not a rendered pass.

## Receipt boundary and enlargement observations

The retained dark receipt captures show the same 900px-high synthetic order in **stacked layout at displayed 999px**, and **split board/guidance at displayed 1000px and 1001px**. In split layout, the guidance occupies the side pane and the board displays two card columns. Evidence: [displayed 999](rendered-ui-review-2026-11-07-pass2/p2-23-receipt-displayed-999-dark.png), [displayed 1000](rendered-ui-review-2026-11-07-pass2/p2-24-receipt-displayed-1000-dark.png), [displayed 1001](rendered-ui-review-2026-11-07-pass2/p2-25-receipt-displayed-1001-split-dark.png).

The initial native observation at 1000 appeared stacked, but its retained screenshot is split. Effective CSS width and pointer mode were not computed, so the images support the captured layout change without establishing a fractional-width/media-query defect. Source `receipts.css:46-51` declares the split from 1000px. No receipt rows were checked in this native boundary sequence and no arrival was previewed or recorded. The later headless target measurement deliberately checked one local row without recording it. The native sequence did not measure targets; the headless measurements below supply that evidence. Content/focus clearance and physical-card recognition remain open.

A native Chrome zoom attempt reached a visible 200% browser popup, but the emulated page's text geometry did not visibly enlarge. Ctrl+0 reset it and removed the zoom icon. No screenshot or enlarged-text pass is claimed. Actual browser/OS 200% enlargement remains **not qualified**. A separate headless 200% CSS-root stress below is labeled by its actual mechanism; device-toolbar preview scale must not stand in for text scaling.

## Headless follow-up and exact measurements

The script follow-up used an isolated temporary headless browser context, same-origin request allowlisting and simulation-write denial. Only the read-only `POST /api/deck/check` was additionally allowed for editor qualification. No visible desktop input was sent. The browser was closed in each finally path. The 32 capture configurations report no page errors, loaded Figtree/JetBrains Mono and matching intended fine/coarse pointer flags; [curated DOM metrics](rendered-ui-review-2026-11-07-pass2/headless-metrics-summary.json) exclude host paths, process IDs, ports and URLs.

Two initial CSS-root stress captures blocked the dry-run check endpoint. Those are superseded by corrected recaptures. An earlier editor qualification attempt used the wrong viewport/missed a confirmation; that scratch failure is also excluded. Neither is an application finding or a pass. The published headless set contains 30 main captures, 2 corrected root-stress captures and 3 images from the successful editor qualification: 35 images, alongside 25 native images. Image count is not a count of independent passed screens.

Full-page screenshots retain fixed bars at the original capture viewport position. Their mid-image overlays are a capture characteristic; they do not by themselves establish unreachable page content. Placeholder art still does not qualify physical recognition. Synthetic failed/running variant adapters retain invented result data; the captures exercise state branches, not production error/result-generation semantics.

### Exact receipt geometry

Both themes and both verified pointer modes gave the same grid geometry, with `innerWidth == clientWidth` at the requested width:

| Exact CSS width | Computed grid tracks | Track widths | Layout |
|---|---|---|---|
|429|2|194.5px each|Stacked board/guidance|
|430|3|127.328-127.344px|Stacked board/guidance|
|999|5 available tracks; only 3 filled|180.594-180.609px|Stacked board/guidance|
|1000|2|232px each|Board plus 452px guidance aside|

The 429-to-430 track width reduction is approximately 34.5%. This resolves the earlier nominal-toolbar width uncertainty for these headless configurations. It confirms the declared responsive rule; it is not a breakpoint bug. No page-wide horizontal overflow appeared in these measured cases. Recognition and physical touch suitability remain open.

### O03 - Recovery target below the project's touch floor

The **1 with no condition or language** recovery button's measured height is **24 CSS pixels** in all 16 receipt configurations, including every verified coarse-pointer case. This does not meet DeckLab's deliberate 44px touch floor (`UI-KIT.md:922`; source `receipts.css:264-267`). The geometry is confirmed; the P2 recommendation is to apply the project's touch sizing consistently without changing the recovery action or requiring metadata guesses.

This is not classified as an automatic WCAG AA failure. WCAG 2.2's minimum target criterion uses 24px with defined exceptions/spacing conditions: [SC2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). Actual device ergonomics and the complete target-spacing check remain separate.

### Root-font 200% stress at 320px

Corrected light/dark runs set only the root CSS font size to 200%, producing measured root/body fonts of 32px at a 320 ? 844 viewport, with `scrollWidth == clientWidth == 320`. The long synthetic editor page remained vertically scrollable; names/prose wrap or truncate in the dense controls. This records the specific CSS stress and sampled document-width behavior, not blanket legibility, OS/browser zoom, on-screen keyboard or device acceptance. The ordinary dry-run deck check was allowed; no deck-save write was allowed.

### Scripted editor qualification

Ordinary Playwright clicks repeated R06 at measured 390 ? 844, DPR 2, light. After three real row More/Remove actions, footer Undo/Discard were enabled. After blocked Save and Keep editing, both were disabled despite model `saving:false`, `asking:false`, `leaving:false`, dirty true and history length 3. Row Undo restored the retained footer state. The saved deck SHA/lists and kept draft were unchanged. Existing kept-draft Resume was also observed in this isolated same-browser context; this is not cross-device/collision acceptance. [Curated assertions](rendered-ui-review-2026-11-07-pass2/headless-editor-proof.json).

### Headless image index

| Family | Light | Dark |
|---|---|---|
|Popular board 1440|[wide](rendered-ui-review-2026-11-07-pass2/hl-01-board-mixed-1440-light.png)|[wide](rendered-ui-review-2026-11-07-pass2/hl-17-board-mixed-1440-dark.png)|
|Popular board 320|[narrow](rendered-ui-review-2026-11-07-pass2/hl-02-board-mixed-320-light.png)|[narrow](rendered-ui-review-2026-11-07-pass2/hl-18-board-mixed-320-dark.png)|
|Variant failed 1440|[failed](rendered-ui-review-2026-11-07-pass2/hl-03-variant-failed-1440-light.png)|[failed](rendered-ui-review-2026-11-07-pass2/hl-19-variant-failed-1440-dark.png)|
|Variant running 1440|[running](rendered-ui-review-2026-11-07-pass2/hl-04-variant-running-1440-light.png)|[running](rendered-ui-review-2026-11-07-pass2/hl-20-variant-running-1440-dark.png)|
|Member variant 390|[complete](rendered-ui-review-2026-11-07-pass2/hl-05-variant-member-390-light.png)|[complete](rendered-ui-review-2026-11-07-pass2/hl-21-variant-member-390-dark.png)|
|Pair failed 1440|[failed](rendered-ui-review-2026-11-07-pass2/hl-06-pair-failed-1440-light.png)|[failed](rendered-ui-review-2026-11-07-pass2/hl-22-pair-failed-1440-dark.png)|
|Pair stale 1440|[stale](rendered-ui-review-2026-11-07-pass2/hl-07-pair-stale-1440-light.png)|[stale](rendered-ui-review-2026-11-07-pass2/hl-23-pair-stale-1440-dark.png)|
|Receipt 429|[fine](rendered-ui-review-2026-11-07-pass2/hl-08-receipt-429-fine-light.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-09-receipt-429-coarse-light.png)|[fine](rendered-ui-review-2026-11-07-pass2/hl-24-receipt-429-fine-dark.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-25-receipt-429-coarse-dark.png)|
|Receipt 430|[fine](rendered-ui-review-2026-11-07-pass2/hl-10-receipt-430-fine-light.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-11-receipt-430-coarse-light.png)|[fine](rendered-ui-review-2026-11-07-pass2/hl-26-receipt-430-fine-dark.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-27-receipt-430-coarse-dark.png)|
|Receipt 999|[fine](rendered-ui-review-2026-11-07-pass2/hl-12-receipt-999-fine-light.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-13-receipt-999-coarse-light.png)|[fine](rendered-ui-review-2026-11-07-pass2/hl-28-receipt-999-fine-dark.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-29-receipt-999-coarse-dark.png)|
|Receipt 1000|[fine](rendered-ui-review-2026-11-07-pass2/hl-14-receipt-1000-fine-light.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-15-receipt-1000-coarse-light.png)|[fine](rendered-ui-review-2026-11-07-pass2/hl-30-receipt-1000-fine-dark.png),[coarse](rendered-ui-review-2026-11-07-pass2/hl-31-receipt-1000-coarse-dark.png)|
|Corrected CSS-root stress 320|[200% root](rendered-ui-review-2026-11-07-pass2/hl-16-editor-root200-320-light.png)|[200% root](rendered-ui-review-2026-11-07-pass2/hl-32-editor-root200-320-dark.png)|
|Editor qualification 390|[blocker](rendered-ui-review-2026-11-07-pass2/he-01-empty-list-review-390-light.png),[footer state](rendered-ui-review-2026-11-07-pass2/he-02-after-keep-editing-footer-390-light.png),[Resume](rendered-ui-review-2026-11-07-pass2/he-03-kept-draft-resumed-390-light.png)|Not repeated|

## Execution and coverage ledger

| ID | Task/state | Required comparison | Evidence status |
|---|---|---|---|
| MV1 | Member editable variant result | Home editable versus `user2/...` deck IDs | R05 reproduced action omission; ordinary member editor permission checked; handoff/save not executed |
| MV2 | Variant read-only control | Public home deck under User2, ordinary `may_save: false` | Renderer control captured; adapter bypasses production result authorization/masking, so backend/read-only acceptance remains open |
| ED1 | Editor Add inspection | Add Opt query/result -> viewer -> return, add one, Done and Undo | Observed at 390px; focus return and all full-pane/nested draft types not qualified |
| ED2 | Local and kept drafts/resume | Local leave/reopen, ordinary kept-draft API revision1 and Resume | Both functional paths observed in same browser/MemoryStore; collisions, database durability and actual cross-device resume untested |
| ED3 | Save blockers and long delta | Three-row empty Planned list review; native More/Remove -> blocked Save -> Keep editing | Final review Save disabled; R06 footer-state defect reproduced; confirmation not activated; long-diff hierarchy remains open |
| ED4 | Conflict/rebase | Local +1 over externally changed 52-to-53 baseline | Reapply 54 observed; stored baseline stayed 53; explicit discard returned latest 53 |
| TS1 | Popular board | Five synthetic states; lead action destination; failure503/Try again recovery | Rendered phone/desktop, light/dark; O02 hierarchy observation; ordering/deep links/numbers not qualified |
| TS2 | Pair/variant results | Variant complete and pair complete/stale | Native and headless complete/running/failed/stale renderer branches recorded; deep details and production result semantics remain open |
| RP1 | Receipt Pictures near 430px | Prior pass two/three-column observation | Headless exact429/430 computed grids and target measurement recorded; real recognition remains open |
| RP2 | Receipt around 1000px | Same unselected order at displayed 999/1000/1001, dark | Native captures plus exact headless999/1000 fine/coarse geometry; clearance not fully tested and no receipt write |
| RP3 | Dark result states | Dark avatar setting, mixed board and pair complete/stale | Rendered states observed; light omitted explanation has R07 measurement; dark/state-wide contrast remains open |
| RP4 | 320px reflow | Testing header, controls/navigation and first result | Native spot plus headless sampled document widths checked; complete controls/sheets/focus reachability remains open |
| RP5 | Enlarged text/browser zoom | Native zoom attempt showed 200% popup without visible page text enlargement | Browser/OS zoom not qualified; separate CSS-root200% stress measured root/body32px and no sampled page overflow |
| RP6 | Keyboard path | Three Tab steps from Testing heading | Visible focus spot observed; shortcuts/modal containment/return/full clearance not qualified |

The ledger distinguishes bounded observations from remaining states; preparing a fixture or checklist is not a rendered pass.

## Validation still outside this pass

Real Safari and physical iPhone/iPad, actual on-screen keyboards and touch ergonomics, screen reader use, OS text settings, real art/printing recognition, production saved-result semantics, full member privacy/state coverage and every ancillary dialog remain unqualified unless separately observed and recorded.

## Cleanup

The dedicated fixture stopped with exit 0; its process and listening port were absent, and its temporary root was removed. Main headless capture, corrected stress and successful editor qualification browsers all closed in finally paths. The editor qualification completed with no close error. The CUA session was completed and reset; no further native desktop input was sent. Visible Chrome was left under the user's control, with no claim that its window was closed. [Sanitized cleanup proof](rendered-ui-review-2026-11-07-pass2/cleanup-summary.json).

## Evidence package

[Run provenance](rendered-ui-review-2026-11-07-pass2/run-metadata.json),[image dimensions/digests](rendered-ui-review-2026-11-07-pass2/screenshot-manifest.json),[headless metrics](rendered-ui-review-2026-11-07-pass2/headless-metrics-summary.json) and [editor assertions](rendered-ui-review-2026-11-07-pass2/headless-editor-proof.json) retain this pass. Raw runner/logs, host paths, process IDs, ephemeral URLs, bulky API snapshots and failed/superseded attempts are excluded.
