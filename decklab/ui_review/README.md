# Headless UI review

Run the rendered review against disposable synthetic data, without moving the
mouse, sending desktop keystrokes or opening a visible browser window. The
command owns its fixture and browser processes and checks their cleanup.

This is development tooling. It never starts Deck Lab's normal server, connects
to the household database, reads the private configuration or runs Forge.

## Setup once

Requirements: the project's Python, Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+
with npm, and an installed
Chrome, Chromium or Edge executable. Chrome on the development PC is detected
automatically; `--browser` can name another compatible executable. No browser
download or global npm install is performed.

From the repository root:

```powershell
python scripts/ui_review.py --setup
```

This explicitly runs `npm ci --ignore-scripts` in this folder, installing the
lockfile's `playwright-core` 1.65.0, Acorn 8.19.0 and eslint-scope 9.1.2 under
the gitignored `node_modules/`. The parser/scope tools also power fixture checks
for undefined JavaScript calls and the global sheet-closer inventory. It checks
the prerequisites and exits without starting a fixture or browser. Normal review
runs never install or update dependencies.

For fixture tests alone, no browser is needed: run
`npm ci --ignore-scripts --prefix decklab/ui_review` before
`python scripts/test_fixtures.py` when Node is available. The fixture CI jobs do
this explicitly; production Deck Lab still has no npm dependency or build step.

## Repeat a review

```powershell
python scripts/ui_review.py
```

The default runs the 44-case capture matrix followed by the editor interaction
qualification. The fixture is fresh for each invocation; the editor suite does
not depend on a draft or browser left behind by an earlier review.

Output goes to a new timestamped folder under `decklab/data/ui-review/`, which is
gitignored. The command prints its location. Inspect `README.md`, `run.json` and
the `capture/` and `editor/` subfolders there. Each suite retains screenshots,
source/runtime provenance, DOM measurements, request classifications and actual
browser cleanup flags. A screenshot being captured is not an automatic visual
or accessibility pass.

Useful variations:

```powershell
python scripts/ui_review.py --check
python scripts/ui_review.py --smoke
python scripts/ui_review.py --suite capture
python scripts/ui_review.py --suite editor
python scripts/ui_review.py --suite composition
python scripts/ui_review.py --suite variant-layout
python scripts/ui_review.py --suite shell-layout
python scripts/ui_review.py --suite task-layout
python scripts/ui_review.py --suite receipt-layout
python scripts/ui_review.py --suite families
python scripts/ui_review.py --suite shopping-navigation
python scripts/ui_review.py --suite shopping-card-links
python scripts/ui_review.py --suite shopping-queue-cards
python scripts/ui_review.py --suite shopping-baskets-layout
python scripts/ui_review.py --suite zoom
python scripts/ui_review.py --suite crosscheck
python scripts/ui_review.py --suite assembly-counters
python scripts/ui_review.py --suite precon-bonus
python scripts/ui_review.py --suite life-counters
python scripts/ui_review.py --suite first-use --smoke --strict-console
python scripts/ui_review.py --suite member-tools --smoke --strict-console
python scripts/ui_review.py --suite card-viewer-details --smoke --strict-console
python scripts/ui_review.py --suite deck-cuts --strict-console
python scripts/ui_review.py --smoke --suite capture --strict-console
python scripts/ui_review.py --output C:/Temp/decklab-ui-review-01
python scripts/ui_review.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

The opt-in `precon-bonus` suite exercises six synthetic bonus-card reviews across
phone, tablet and desktop widths in both themes. Native checkbox clicks, exact
request receipts and explicit recovery from a source conflict are intercepted
without writing inventory. `assembly-counters` has 30 counter/dice and take-along
cases across the same widths/themes: ready/failed/unmigrated reminders and
ready/failed take-along lists. Optional checks use intercepted in-memory replies;
the guarded print action uses a stubbed system dialog and actual print CSS.

The opt-in `shopping-navigation` suite uses invented deliveries, queue rows and
shortfalls to check the grouped section controls at 320, 393, 430, 600, 820, 1280 and
1440px in both themes, plus 200% CSS root-font stress at 320 and 600px. It checks
native More sections disclosure keys, label/count containment and heading focus
without a route change or write. The 393px top/expanded and enlarged-text captures
are retained for visual inspection. Enlarged-text checks require navigation
containment and retain broader page overflow as a diagnostic; ordinary cases
also require no document overflow. This does not qualify Safari or physical touch.

The opt-in `shopping-card-links` suite uses invented missing-card rows with long
deck names, saved nonfoil shop evidence and an upcoming paper printing. It checks
grouped deck-link/count targets and contained source links at 320, 393, 430, 600,
820, 1280 and 1440px in both themes, plus CSS root-font stress at 320 and 600px.
Native Choose decks controls load an intercepted read-only combined answer to
check the same deck-link treatment there. Keyboard/pointer activations are
intercepted before navigation while preserving original destinations and external
target/rel attributes. No external page or app write is allowed. Phone and
enlarged-text captures require visual inspection; Safari remains separate.

The opt-in `shopping-queue-cards` suite renders four invented queue rows with
unchecked, priced, exact, deferred, unknown, partial and back-in-stock facts. It
checks the casual cards and reference/shop/action bounds at 320, 393, 430, 600,
820 and 999px, 200% CSS root-font stress at 320 and 600px, and the existing lab
tables at 1000 and 1440px, in both themes. Native Move/Escape, cancelled Details,
intercepted read-only Price history and card-viewer controls keep their original
focus targets. By state/By shop and density round trips must retain the same
viewer, reference, shop snapshots, history and write-control nodes. Lab columns
retain local horizontal scrolling. No app write or retailer fetch is allowed;
phone and enlarged-text captures still require visual inspection.

The opt-in `shopping-baskets-layout` suite checks invented Baskets/Fewest shops
at 320, 393, 430, 600, 820, 1280 and 1440px in both themes, with CSS root-font
stress at 320/600px and read-only/stale 393px states. It covers partial stock,
alternate printings, zero and unknown prices, unknown postage, add-ons, unread
shops and a recommendation differing from the cheapest-card split. Native
Other ways controls, intercepted exact clipboard contents and a cancelled order
preview retain their existing guards and price-free hand-off. Preview replies
are synthetic; no final order, queue change or retailer fetch is allowed. Phone
and enlarged-text screenshots require visual inspection.

`--check` does not start any application processes. `--smoke` captures a desktop
board in light, a narrow coarse-pointer receipt in dark and the ten Wishlist/guide
cases (12 cases total); the editor suite still runs its complete interaction
sequence. `--suite` selects one suite.
The opt-in 40-case `composition` suite adds populated Commander/casual Overview,
multi-deck library and empty/failed states at short phone, tablet, laptop and QHD
sizes in both themes. Its `--smoke` subset is 20 matched deck and library captures,
including library work areas at a consistent 80px top clearance. Top-of-page
captures retain the synthetic stale-table warning; the scrolled captures expose
the actual rows/detail instead of inferring composition from hidden content.
The complete suite also captures QHD Commander Overview in both themes, the populated Played at home line and guide
after scrolling, tests native library selection, and confirms the saved Commander
deck response is unchanged. Its fixtures use the ordinary deck, guide and Game log
readers, with invented records and placeholder art. Scores and a realistic mana
base are not being assessed. `all` retains the original capture/editor suites;
run `composition` separately when changing these page compositions.

The opt-in `crosscheck` suite exercises the new second-simulator section on the
Testing tab, in light and dark at phone, tablet and desktop widths. Ready saved
results, an unavailable engine, running and partial games, failed reads and
loading states use explicitly intercepted synthetic responses. It checks that
the collapsed section makes no request, the opponent picker remains usable and
the two scores stay separate. No engine or database write is made; these
captures qualify rendering only, not native XMage behavior or device acceptance.

The opt-in 54-case `shell-layout` suite measures header siblings, search form/input,
focus decoration, activity control and viewport bounds in both themes. Cases cover
320/393/599/600/624/625/699/700/820/999/1000/1199/1200/1440px, short landscape,
explicit root-font stress, home library/receipt headers and a synthetic active run.
The run is an invented read adapter; no Forge process is started. Ordinary keyboard
events exercise `/` search focus or sheet opening, Escape, and avatar menu opening
and closing. Scrolled title geometry is retained. Overflow and sibling overlap are
diagnostics for matched comparison, not automatic visual acceptance. The eight-case
smoke subset covers phone, tablet, desktop and enlarged tablet headers. `all` still
means capture/editor only. Additional 600px search-focus screenshots expose the
actual ring and allocation; physical software keyboards remain unqualified.

The opt-in 26-case `variant-layout` suite captures the existing popular-decks
variant adapter at 320/393/599/600/624/625/820/1440px, short 740×360 landscape,
explicit 320/600px CSS root-font stress, and failed/running 393px states, in both themes.
Complete-result captures anchor By group at an 80px top clearance, with two
supplementary 393px captures targeting By number of colours for unknown and
negative evidence (shorter pages can reach their bottom scroll limit first); failed/running
captures retain the top-of-page verdict/progress. The suite records every group
cell, bar, axis label and its text fragments, container width/font, explicit roles and a browser
accessibility snapshot. Counts exclude decorative hidden unit labels in the
comparison text while retaining raw rendered text separately. Assertions preserve
the four finished synthetic rows, counts, no-difference state, common numerical scale and
native explanation disclosure; running results retain progress and have no finished
group table. Configured Playwright viewport, layout/visual viewports and document
overflow are recorded separately, with up to fifteen visible elements that extend
past the configured width for bounded diagnosis. Layout expansion/overflow remains diagnostic in
the matched baseline, rather than being rejected as a harness viewport mismatch
or automatically labelled a group-layout defect. Its smoke
subset is eight cases. `all` continues to mean capture/editor only.

The opt-in 28-case `task-layout` suite captures receipt tools at
320/393/430/600/820/1440px and empty Considering at 320/393/820/1440px,
in both themes, plus explicit CSS root-font stress at 320/600px for each task.
The real responsive editor selects Quick or full mode. Receipt captures retain
top-of-page and 80px toolbar anchors; editor captures anchor the alternatives
section, subject to the page's scroll limit. Supplemental PNGs show Tools,
Considering help and Add. The suite checks local receipt selection, layout,
filter and note preferences, plus opening/closing Add and unchanged saved-deck
responses. Ordinary cases use pointer clicks; the eight root-font cases use
native keyboard activation. This distinction preserves baseline pointer/footer
occlusion as a separate finding, rather than calling it fixed by a keyboard
pass. Overflow is diagnostic at each retained snapshot; transitions can still
have unmeasured geometry. No fill, bulk tick, preview, arrival or Save is
invoked. Its smoke subset is eight ordinary phone/tablet cases. `all` still
means capture/editor only.

The opt-in `receipt-layout` suite qualifies ordinary pointer input, Tools layout
switches, the last card, native date input, Record's pointer hit area without
activating it, and keyboard clearance. It includes explicit CSS root-font stress,
short landscape, a 24-copy parcel and a two-part parcel with a local copy split.
Reload requires explicit Resume and must retain exactly the local checking draft;
the saved receipt response stays unchanged. No preview or arrival write is allowed.

The opt-in `families` suite covers Collection Find/Card list, Shopping, Tokens,
accessories, Game log, Activity, Settings and Wishlist in both themes at phone,
tablet and desktop widths. Its 114 cases include empty primary lists, unavailable
and pending GET responses; `--smoke` captures 40 cases. Settings additionally covers
320/375/393/430/820/1440px (320/393/1440px in smoke), with explicit 200% CSS root-font
stress at 393px in both themes. Its loaded forms include the condition/language
preferences; assertions check document width, panel/control bounds and focus without
horizontal scrolling. These are Chromium layout checks, not physical Safari acceptance.
The Activity and database-only Settings panels use invented read adapters. Tokens,
accessories, queued cards and larger parcels are seeded only in the owned temporary
inventory. A token search preference is checked through browser reload.

The opt-in `zoom` suite uses fresh owned Chrome profiles below the private runtime
to compare 100% and 200% **actual browser page zoom** at fixed physical window sizes.
It requires CDP zoom=2, a halved CSS layout viewport, doubled CSS-to-device scale
and unchanged outer window width; unsupported browser preferences fail the suite.
It uses the same origin/write guards as the other suites. All 13 task/page families
are captured in both themes; native editor Remove/Undo/More and a long blocked Save
review preserve the saved deck. This is desktop Chromium page zoom, separately
from CSS root-font stress, OS text scaling or physical Safari/touch acceptance.

Explicit output directories must be new or empty and must not pass through
symlinks/junctions. Prior evidence is never overwritten or pruned.

The equivalent module entry point is `python -m decklab.ui_review`. The wrapper
script can also be invoked by its full path from another working directory.

## What is exercised

The capture matrix uses both themes and DPR 2:

- Popular decks with complete, partial, changed-list, older-engine and unreadable
  synthetic rows at 1440px, 320px and a short 393×700 viewport.
- Failed/running variant results, a member result, and failed/stale pair results.
- Receipt Pictures at exactly 429, 430, 999 and 1000 CSS pixels, independently
  with fine and coarse pointer emulation. One local checkbox is selected to
  expose the blank-metadata recovery control; arrival is never recorded.
- A 320px editor with explicit 200% **CSS root-font stress**. This is not browser
  zoom, OS text scaling or a claim that every absolute-size control doubled.
- Wishlist local Notes/Source/printing through Zoom and Close/Escape/Back at
  390px coarse and 1440px fine, plus unknown-count sheets at 390px. Known-zero
  and positive-count tiles are checked too. Saved Wishlist digests stay unchanged;
  explicit sheet closure reopens saved values. No final Save is clicked.
- Library How to play at 1440px and copied guide destinations at 390px: Overview,
  guide focus and sticky clearance, plus desktop Back/Forward, in both themes.

Capture and composition measurements include bounded element text, typography,
spacing and board/editor row allocations. Absent samples remain null; they are
not evidence about an element's appearance. The matrices retain explicit viewport,
pointer and theme settings, including the existing QHD root enlargement.
Native board/receipt help disclosures are opened and closed through their summaries
after each PNG, retaining the local receipt selection. Coarse receipt recovery must
measure at least 44px; root-font editor identity/printing must retain at least 80%
of the row width. These bounded assertions do not qualify every page or device.

The editor suite uses ordinary Playwright clicks to remove the three fixture
rows, open the blocked empty-list Save review, return with Keep editing and
measure the live Undo/Discard state. It records whether the reviewed footer
problem reproduces; it does not require that bug to remain. Visible row Undo
restores the local list, and the seeded kept draft can be resumed. Saved deck
data and the server's kept draft must stay unchanged.

Screenshots and measurements expose the actual HTML/CSS. The only layout
injection is the explicitly labelled root-font stress. Simulation results and
member identity transport are fixtures, not measured games or authentication.

## Isolation and cleanup

- There is no existing-server URL option. The parent starts a dedicated worker
  on an ephemeral IPv4 loopback port. Readiness must match the owned worker PID,
  run token and fresh runtime marker; an HTTP identity challenge must also pass.
- Before application imports, the worker installs the fixture runtime guards.
  Its FileInventory, MemoryStore, card index and images live beneath the owned
  temporary runtime. The worker denies external Python socket/DNS operations,
  database/download/worker access and subprocess launches. These are process-local
  accident guards, not an OS sandbox or protection against malicious code.
- The worker refuses every HTTP mutation except `POST /api/deck/check`, which is
  a dry run. The browser also blocks external page requests and all other writes,
  including visits and simulation starts. Browser background networking is
  disabled; this is not an OS-wide network isolation claim.
- Each browser context has a temporary profile. The helper never attaches to the
  user's Chrome, copies cookies or changes a visible browser's settings.
- Normal completion, helper failures and Ctrl+C request cooperative browser and
  fixture shutdown. A bounded fallback targets only owned child processes, not
  every Chrome process. The parent verifies the private runtime's resolved path
  before removing it. Output evidence remains available on failure.
- `run.json` records browser closure, fixture exit and temporary-directory removal
  separately. Missing closure evidence is not called successful cleanup.

The default time limit is 180 seconds; `--timeout` can change it. Exit 0 means the
harness completed and cleanup was confirmed, **not** that the product passed a
design review. Exit 1 means a capture/assertion/cleanup/source-consistency failure;
2 means prerequisites or invocation failed; 130 means interrupted.

Do not edit application/tool source during a capture run: before/after source
fingerprints detect changes and mark the evidence incomplete. The desktop remains
available for other work throughout a headless run.

## Fixture limits

The checked-in JSON adapters are deliberately invented renderer inputs. Scores,
ordering and repeated explanatory prose are not evidence about production results.
Some board Details destinations are not seeded, pair deep detail is sparse, and a
failed variant retains illustrative result rows. These cases exercise renderer
branches; do not report those adapter choices as application defects.

The synthetic identity transport lets ordinary own-space permission checks run,
but result adapters bypass the production result-read/masking path. A temporary
home Public switch provides a read-only control; no real visibility is changed.
The fixture's images are placeholders. Offscreen lazy images and fixed bars in
full-page captures have their normal browser capture limits.

Physical Safari/iPhone/iPad, actual touch/keyboard ergonomics, screen readers,
real-art recognition, database durability and production result semantics remain
separate acceptance work. Keep fixture gaps, execution failures, observations and
confirmed UI defects distinct in the written report.

## Keeping the tool useful

`fixture.py` owns the synthetic records, read-only adapters and guarded transport;
`data/` owns the invented result payloads. `capture.js` owns matrix cases and DOM
measurements; `wishlist-checks.js` and `repair-checks.js` own local Wishlist and
guide interactions; `editor.js` owns editor sequences; `task-layout.js` owns
receipt tools and empty Considering comparisons; `common.js` owns browser
isolation, requests, cancellation and artifact sanitization. `runner.py` owns
setup, source provenance and child-process lifecycle.

Add new cases through these bounded fixtures. Do not make the tool convenient by
pointing it at a household server, loading private config, allowing arbitrary
writes or attaching a desktop browser. Default outputs stay out of git; inspect
the selected screenshots and JSON before adding dated evidence to the public
design reports.

Validate tooling changes with:

```powershell
python scripts/test_fixtures.py decklab.tests.test_ui_review
python scripts/ui_review.py --smoke
```

After a case/selector/fixture change, run the affected suite (or the full default
command) and inspect its PNGs and measurements. Browser qualification is explicit
and is not part of the default Python fixture suite or an installed schedule.
