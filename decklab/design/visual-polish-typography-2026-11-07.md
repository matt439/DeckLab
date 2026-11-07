# Visual polish: shared typography

7 November 2026, Australia/Brisbane. Owner: `E11-S30`. This continues the [visual direction](visual-polish-direction-2026-11-07.md) with the shared type hierarchy. Remaining page families and device acceptance stay open.

## What changed and why

The previous scale gave a desktop deck title 22px while ordinary page titles were 32px, section headings often 24px, controls 13px and implicit body copy 16px. The dormant desktop `--fs-body` value was 13px: changing that token alone would not have changed the actual body. This inconsistency made sections compete with identity and small controls sit beside larger incidental copy.

- Shared page headings now use 28px/600 and section headings 20px/600. The old tablet heading jump is removed. Existing heading margins remain; this slice does not compress every gap.
- Desktop task copy, navigation and generic sheet copy consume `--fs-body` at 14px. Fine-pointer buttons and fields also use 14px; metadata grows from 12px to 13px. Control minimums, semantic status colours, focus and actions retain their existing behavior.
- Phone/tablet-portrait body text stays 16px. Touch-lab buttons stay 15px and fields 16px, with their 44px floors. Phone deck titles keep 24px beside their actions; saved editor titles use 24px below 1000px and 28px above, with semibold weight.
- Play-guide prose explicitly stays 16px with its 1.65 line height and bounded reading column, independent of the smaller desktop task scale. Card identity, table headers and Forge numeric evidence retain their separate sizes.
- The existing 112.5% QHD root enlargement remains: task text is 15.75px, metadata 14.625px, page titles 31.5px and guide prose 18px. The typefaces, palette and interaction contracts stay the same.

This is a deliberate 16→14px reduction for inherited desktop task copy and a 13→14px increase for fine-pointer controls. It is not a blanket text enlargement. Table typography and long/error/busy states on the remaining page families still need their own rendered qualification.

## Matched comparisons

Both phases used the same disposable synthetic fixture and finalized capture scripts, Chrome 156.0.8078.80, Playwright Core 1.65.0, DPR 2 and explicit theme/pointer settings. Baseline is the production CSS at `aeabcac`, with the expanded measurement harness. Only four production stylesheets differ between the before and after runs: `tokens.css`, `base.css`, `editor.css` and `guide.css`. [Proof](visual-polish-typography-2026-11-07/proof.json) retains source digests, changed-file hashes, per-case outcomes and measurements; the [manifest](visual-polish-typography-2026-11-07/screenshot-manifest.json) identifies the unchanged PNG bytes.

| Screen | Before | After |
|---|---|---|
| Testing, 1440×900 light | [Before](visual-polish-typography-2026-11-07/before-testing-1440-light.png) | [After](visual-polish-typography-2026-11-07/after-testing-1440-light.png) |
| Testing, 1440×900 dark | [Before](visual-polish-typography-2026-11-07/before-testing-1440-dark.png) | [After](visual-polish-typography-2026-11-07/after-testing-1440-dark.png) |
| Short-phone Testing, 393×700 light | [Before](visual-polish-typography-2026-11-07/before-testing-393-light.png) | [After](visual-polish-typography-2026-11-07/after-testing-393-light.png) |
| Short-phone Testing, 393×700 dark | [Before](visual-polish-typography-2026-11-07/before-testing-393-dark.png) | [After](visual-polish-typography-2026-11-07/after-testing-393-dark.png) |
| Commander Overview, 1440×900 light | [Before](visual-polish-typography-2026-11-07/before-commander-1440-light.png) | [After](visual-polish-typography-2026-11-07/after-commander-1440-light.png) |
| Commander Overview, 1440×900 dark | [Before](visual-polish-typography-2026-11-07/before-commander-1440-dark.png) | [After](visual-polish-typography-2026-11-07/after-commander-1440-dark.png) |
| QHD Commander Overview, 2560×1305 dark | [Before](visual-polish-typography-2026-11-07/before-commander-2560-dark.png) | [After](visual-polish-typography-2026-11-07/after-commander-2560-dark.png) |

All fourteen retained PNGs were visually inspected. The judgment is that deck identity now leads its sections and desktop controls are easier to read alongside their context. On the deliberately long 1440px deck title, the title wraps to two full lines: its header grows from 137.2px to 143px, rather than shrinking the name to fit. Its tabs move from y=364.2px to 367px. QHD keeps that title on one line, with the same 137.2px header height. These are intentional allocations, not a claim that less height is always better.

| Measured element | Before | After |
|---|---:|---:|
| 1440px Testing title | 32px / 600 | 28px / 600 |
| 1440px task body / format choice | 16px / 13px | 14px / 14px |
| 1440px Testing scope | 12px | 13px |
| 1440px deck title / section title | 22px / 24px | 28px / 20px |
| 1440px deck Edit label / target height | 13px / 32px | 14px / 32px |
| 393px Testing body / scope | 16px / 14px | 16px / 14px |
| QHD deck title / section title | 24.75px / 27px | 31.5px / 22.5px |

The populated library's work-area cases align the same container at an 80px top clearance. Their document scroll offsets change with upstream text reflow, so compare anchored work areas rather than claiming identical document offsets. The fixture's placeholder art, sparse lists, invented results and review-only explanatory lines do not qualify real-art recognition or production result semantics. Phone full-page Testing captures retain a fixed bottom bar; the root-font editor's full-page capture can place its fixed bar mid-image. Neither is a new layout defect established by this slice.

## Verification and remaining work

Each phase completed **44/44 capture cases**, its editor interaction sequence and **40/40 composition cases**. There were no uncaught page errors or document-wide horizontal overflows. The existing disclosures, Wishlist Zoom/close retention, guide destinations, native library selection and blocked editor Save recovery completed. Saved Wishlist, deck and server-kept draft checks remained unchanged. Source fingerprints stayed stable during each run; browser closure, fixture exit and temporary-runtime removal were confirmed separately.

At 320px with explicit 200% CSS root-font stress, card identity and printing still receive the full row width in both themes. Coarse-pointer receipt recovery retains its 44px floor. These bounded checks do not constitute browser zoom, OS text scaling or physical-touch acceptance.

The harness now records bounded typography/spacing samples and repeats short-phone Testing plus QHD Commander Overview in both themes. Missing optional samples remain null, never inferred from a token. The fixture/network/write guards remain unchanged, and no final Save or simulation was activated.

The broader guarded frontend regression passed **3,125 tests in 284.880 seconds, with two skips**, across 265 UI/web/accessibility modules. Focused web, density, editor-header, harness and source-inventory checks also passed **111 tests, with one existing link-creation skip**. Ruff and the source-length guard passed. The unrelated full backend suite was not repeated; database integration and native runtime retain their separate qualification workflows.

No household records, private configuration, visibility setting or Forge game was used or changed. The normal local server was unavailable and remains stopped.

Follow-up: [narrow variant group evidence](visual-polish-variant-groups-2026-11-07.md) is implemented with paired 26-case runs. Next: its separate narrow-shell overflow, receipt filter/bulk-action hierarchy and empty Considering composition; then populated/error/busy Collection, Shopping, Tokens, accessories, Game log and Activity. Other table typography, actual browser/OS enlargement, software keyboards, varied real art, Safari, physical touch and screen-reader acceptance remain open. The new QHD Overview fixture covers its desktop composition only. Keep `E11-S30` open.
