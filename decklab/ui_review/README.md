# Headless UI review

Run the rendered review against disposable synthetic data, without moving the
mouse, sending desktop keystrokes or opening a visible browser window. The
command owns its fixture and browser processes and checks their cleanup.

This is development tooling. It never starts Deck Lab's normal server, connects
to the household database, reads the private configuration or runs Forge.

## Setup once

Requirements: the project's Python, Node.js 20 or later with npm, and an installed
Chrome, Chromium or Edge executable. Chrome on the development PC is detected
automatically; `--browser` can name another compatible executable. No browser
download or global npm install is performed.

From the repository root:

```powershell
python scripts/ui_review.py --setup
```

This explicitly runs `npm ci --ignore-scripts` in this folder, installing the
lockfile's `playwright-core` 1.65.0 under the gitignored `node_modules/`. It checks
the prerequisites and exits without starting a fixture or browser. Normal review
runs never install or update dependencies.

## Repeat a review

```powershell
python scripts/ui_review.py
```

The default runs the 42-case capture matrix followed by the editor interaction
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
python scripts/ui_review.py --output C:/Temp/decklab-ui-review-01
python scripts/ui_review.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"
```

`--check` does not start any application processes. `--smoke` captures a desktop
board in light, a narrow coarse-pointer receipt in dark and the ten Wishlist/guide
cases (12 cases total); the editor suite still runs its complete interaction
sequence. `--suite` selects one suite.
The opt-in `composition` suite adds populated Commander/casual Overview,
multi-deck library and empty/failed states at short phone, tablet, laptop and QHD
sizes in both themes. Its `--smoke` subset is 20 matched deck and library captures,
including library work areas at a consistent 80px top clearance. Top-of-page
captures retain the synthetic stale-table warning; the scrolled captures expose
the actual rows/detail instead of inferring composition from hidden content.
The complete suite also captures the populated Played at home line and guide
after scrolling, tests native library selection, and confirms the saved Commander
deck response is unchanged. Its fixtures use the ordinary deck, guide and Game log
readers, with invented records and placeholder art. Scores and a realistic mana
base are not being assessed. `all` retains the original capture/editor suites;
run `composition` separately when changing these page compositions.

Explicit output directories must be new or empty and must not pass through
symlinks/junctions. Prior evidence is never overwritten or pruned.

The equivalent module entry point is `python -m decklab.ui_review`. The wrapper
script can also be invoked by its full path from another working directory.

## What is exercised

The capture matrix uses both themes and DPR 2:

- Popular decks with complete, partial, changed-list, older-engine and unreadable
  synthetic rows at 1440px and 320px.
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

Capture measurements include element typography and board/editor row allocations.
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
guide interactions; `editor.js` owns editor sequences; `common.js` owns browser
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
