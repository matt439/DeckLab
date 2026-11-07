# Visual polish: first implementation

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This is the first production slice of the [visual direction](visual-polish-direction-2026-11-07.md), with the remaining work still open.

The subsequent [interaction/readability repairs](visual-polish-repairs-2026-11-07.md) implement R01–R05 and R07. Unfixed status below records the boundary of this first slice.

## What changed

- Shared secondary buttons use neutral borders and ink, quieter labels and 8px corners. Primary actions keep their violet fill. Short segmented choices use a neutral selected surface; page-view navigation uses underlined tabs. The main navigation has a current-section underline. Font families, reading sizes, focus rings, disabled states and touch floors remain.
- Testing has a shorter introduction and an explicit format/1v1/sample-size scope. General explanation is available through About these results; answer-specific notes remain visible. Play a matchup is primary only on Matchups. Current and historical evidence occupy the same desktop column, retaining all original historical wording. Phone rows stack identity, evidence and actions.
- Receive delivery puts order metadata and general checking instructions in native disclosures. Checks and unknown metadata remain visible. The footer groups progress/recovery and arrival date/Record controls. Recovery is at least 44px tall. The existing preview/confirmation/apply and picture-column rules remain.
- Editor names get a full-width line when their pane is constrained. At the smallest relative width, printing details get their own line too. The retained Undo/Discard controls now reflect the current draft immediately after a blocked, stale or failed Save attempt; a completion cannot update a replacement editor.

This delivers R06 and the O03 control-size correction, O02's Testing action hierarchy, and bounded O04/O05/O06 visual improvements. R01–R05 and R07 remain unfixed. O04's actual browser enlargement, O05's art/grid decision and O06's narrow variant evidence remain separate work.

## Rendered comparisons

These use the same disposable synthetic capture matrix as the earlier [change plan](rendered-ui-change-plan-2026-11-07.md). The comparison preserves viewport, pointer, theme and fixture contents. Receipt captures perform the same local checkbox/scroll sequence; that sequence does not guarantee identical scroll offsets after reflow. Fixed bars in full-page PNGs appear at the captured viewport position. Placeholder images and repeated fixture prose are not production content.

| Screen | Before | After |
|---|---|---|
| Testing, 1440 light | [Before](rendered-ui-change-plan-2026-11-07/board-1440-light.png) | [After](visual-polish-implementation-2026-11-07/testing-1440-light.png) |
| Testing, 1440 dark | [Before](rendered-ui-change-plan-2026-11-07/board-1440-dark.png) | [After](visual-polish-implementation-2026-11-07/testing-1440-dark.png) |
| Testing, 320 light | [Before](rendered-ui-change-plan-2026-11-07/board-320-light.png) | [After](visual-polish-implementation-2026-11-07/testing-320-light.png) |
| Testing, 320 dark | [Before](rendered-ui-change-plan-2026-11-07/board-320-dark.png) | [After](visual-polish-implementation-2026-11-07/testing-320-dark.png) |
| Receipt, 430 touch light | [Before](rendered-ui-change-plan-2026-11-07/receipt-430-coarse-light.png) | [After](visual-polish-implementation-2026-11-07/receipt-430-light.png) |
| Receipt, 430 touch dark | [Before](rendered-ui-change-plan-2026-11-07/receipt-430-coarse-dark.png) | [After](visual-polish-implementation-2026-11-07/receipt-430-dark.png) |
| Editor, 320 root-font stress light | [Before](rendered-ui-change-plan-2026-11-07/editor-root200-320-light.png) | [After](visual-polish-implementation-2026-11-07/editor-root200-320-light.png) |
| Editor, 320 root-font stress dark | [Before](rendered-ui-change-plan-2026-11-07/editor-root200-320-dark.png) | [After](visual-polish-implementation-2026-11-07/editor-root200-320-dark.png) |
| Editor after Keep editing, 390 light | [Before](rendered-ui-change-plan-2026-11-07/editor-after-keep-editing-390-light.png) | [After](visual-polish-implementation-2026-11-07/editor-after-keep-editing.png) |

The inspected comparisons show less competing violet decoration, a clearer distinction between navigation and actions, stable historical evidence placement, and readable editor identity/printing lines. Receipt checking begins earlier, with a deliberately grouped footer. The receipt's wrapped filter track and prominent bulk shortcut still need refinement; Testing's broad header and editor's empty Considering ceremony remain candidates. This is progress toward the direction, not aesthetic acceptance of every page.

## Verification

The final `python scripts/ui_review.py` run completed all **32 capture cases and the editor interaction suite**, with zero failed cases or uncaught page errors. Every case had no document-wide horizontal overflow. Chrome 156.0.8078.80, Playwright Core 1.65.0, DPR 2; both themes and explicit fine/coarse emulation. [Curated proof](visual-polish-implementation-2026-11-07/proof.json) records source fingerprints, element-level typography, row allocations, native disclosure checks and cleanup; [manifest](visual-polish-implementation-2026-11-07/screenshot-manifest.json) identifies the retained images.

- Receipt recovery measured **44px** at 429/430/999/1000 in both themes and pointer configurations. The 430px coarse-pointer footer measured **134.5px** high. Order details and Checking help opened and closed through their native summaries in all 16 receipt cases, retaining the checked row.
- About these results opened and closed in all four board cases. Historical rows retain their Before/older-engine explanations rather than presenting a current headline.
- At 320px with 200% CSS-root text, the browser checks require each editor identity and printing area to occupy at least 80% of its row width. This is layout stress, not actual browser zoom.
- The ordinary editor interaction flow removed the fixture rows, opened blocked Save, returned through Keep editing, and immediately found connected, enabled 44px Undo/Discard controls with the dirty draft/history intact. Row Undo and kept-draft resume completed. Saved deck and server-kept draft digests were unchanged.
- All **2,914 UI fixture tests passed**. Regressions cover all three Testing views without starting runs; historical evidence scope; receipt disclosures and retained state; and failed, stale and blocked editor checks in edit/new modes. The focused static/web run passed 137 checks; the tooling/editor/device/board run discovered 84 with one separately qualified process check skipped. Ruff and the source-length guard passed.

The run used only isolated invented data, read-only result adapters and dry deck checks. No real data was read or saved, and no Forge games ran. Browser closure, fixture exit 0 and temporary-runtime removal were confirmed. The normal listener was not answering on 8642, so it was left stopped.

Remaining qualification includes populated deck/library and other page comparisons, actual 200% browser enlargement, long production-shaped content, real-art receipt recognition, scrolled last-row/focus clearance, software keyboards, Safari, physical touch and a screen reader. Do not close `E11-S30` from this slice.
