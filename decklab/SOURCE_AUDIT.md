# Source-length audit - 2026-10-07

This follows Milestone 7's roughly 1,200-line review threshold. The starting
checkout was `19e27fc`. The audit includes Python, JavaScript, CSS, HTML, Java and
PowerShell, including tests, fixtures and the overnight experiment harness.
Ignored caches, downloads and collection data are outside the source inventory.

Run the same check from the repository root:

```
python scripts/audit_source_lengths.py --check
```

Without `--check`, it prints the inventory summary and longest files. With
`--check`, it also exits 1 if an owned source file exceeds 1,200 lines. Both modes
include untracked source files and respect `.gitignore`.

## Boundaries

The splits keep related functions together and preserve the existing Python
entry points, CLI commands, classic browser scripts and stylesheet ordering.
The HTTP server remains the same `decklab/server.py` script used by Task Scheduler.

| Original file | Before | Largest resulting file | Responsibilities |
|---|---:|---:|---|
| `lib/forge/cli.py` | 2,936 | 650 (`cli_checks.py`) | Entry point and compatibility facade; shared parsing, output, engine checks, ordinary commands, replay, evaluation and soak commands |
| `lib/forge/pool.py` | 1,848 | 802 (`pool_queue.py`) | Public state and sessions; job models, worker queue and local service |
| `lib/forge/runner.py` | 1,582 | 734 (`runner.py`) | Run coordination; launch/protocol helpers, cold batches and warm v2 execution |
| `lib/forge/experiment.py` | 1,671 | 1,054 (`experiment.py`) | Spec and execution; log parsing; statistics, recommendations and report formatting |
| `web/matchups.js` | 1,943 | 579 (`matchups-overview.js`) | Shared controls; overview and refresh; detail and live runs; result rendering |
| `forge-trial/overnight.py` | 2,179 | 957 (`overnight_controller.py`) | Supervisor and CLI; shared state, feature/planning checks, process lifecycle and controller |
| `forge-trial/overnight_report.py` | 1,822 | 861 (`overnight_report_gates.py`) | Report orchestration and analysis; gate calculations; Markdown rendering |
| `forge-trial/overnight_legs.py` | 1,356 | 1,077 (`overnight_legs.py`) | Leg execution; variant, ladder and experiment input preparation |
| `tests/test_forge.py` | 2,601 | 1,198 (`test_forge.py`) | Shared fixtures and CLI/status; models; execution and process safety |
| `tests/test_forge_pool.py` | 1,889 | 1,082 (`test_forge_pool.py`) | Pool scheduling and shared fixtures; service integration; run hooks |
| `tests/test_api.py` | 1,497 | 840 (`test_api.py`) | Sandbox/status/profiles; deck pages; practice, search and images |
| `tests/test_server.py` | 1,520 | 802 (`test_server.py`) | HTTP endpoints/protocol; startup, shutdown and direct-script lifecycle |
| `tests/test_editor.py` | 1,461 | 798 (`test_editor.py`) | Editing operations and fixtures; regression and contract coverage |
| `tests/test_web.py` | 1,430 | 1,122 (`test_web.py`) | Static assets and shared helpers; interactive matchup behavior |
| `tests/test_matchups_api.py` | 1,264 | 845 (`test_matchups_api.py`) | API requests/views; execution and adaptive-run integration |

Shared test fixtures stay at their established import paths. Concrete test
classes move to separate discoverable modules; they are not re-exported, so
unittest does not discover and run them twice. Module setup and cleanup follow
the moved Forge cases. Windows-only imports remain conditional.

The CLI compatibility facade forwards existing reads and patches to each name's
owner. Pool and runner implementations resolve mutable settings and existing
patch targets through their original modules. Experiment execution still owns
spec validation, result loading and its existing patch targets; fixed analysis
thresholds now live in `experiment_analysis.py`. The overnight source-feature
scanner follows the CLI's explicit ownership map and still rejects absent or
stubbed commands without importing or running them.

## Files retained

- `server.py` (1,136 lines) and `lib/cards.py` (1,032) remain below the threshold;
  neither needs another facade or state split in this pass.
- `web/style.css` (938) and `web/editor.js` (857) retain their existing
  organization. The matchup split adds no CSS changes or build step.
- The four patched upstream Java files under `lib/forge/java/forge/` retain
  their original layout. `AiController.java` (2,428 lines) and
  `AiAttackController.java` (1,870) are the only ones above the threshold.
  `Match.java` (515) and `AbstractMulligan.java` (99) are also excluded from
  the owned-source check. These copies are compared with pinned upstream source
  and bytecode; splitting them would interfere with that verification.

## Verification

- The final source inventory contains **264 owned source files**, all at or below
  1,200 lines. Fifteen original files were split: eight implementation/harness
  files and seven test modules. The four upstream copies are listed separately.
- Test discovery preserves all **2,260 original cases**, without duplicates or
  missing cases. Thirteen additional guards cover CLI forwarding, source-feature
  detection and overnight import/patch compatibility.
- Existing focused checks passed: 43 experiment tests; 157 frontend/script tests;
  363 API/editor/server/web/matchup tests; 146 extracted Forge tests; and 295 CLI,
  replay, evaluation and engine-related tests. These groups overlap and are not
  summed as a total.
- Mechanical comparisons preserved original function/class bodies, apart from
  explicit reads through the module that owns a name. All 18 Forge CLI help
  outputs and all 10 overnight CLI help outputs match their pre-split versions.
- Overnight input preparation produced 22 byte-identical synthetic artifacts;
  report data and Markdown matched baseline for empty evidence. Fake supervisor
  recovery tests passed after preserving the original checkpoint filename.
- Browser scripts execute in their explicit HTML order under Node, and existing
  DOM/rendering checks pass. No browser screenshot comparison was performed.
- The length checker was exercised against a temporary Git repository for tracked
  and untracked files, ignored caches, UTF-8 BOM input, upstream exclusions and
  the 1,200/1,201-line boundary.
- **Full integrated suite:** `python -m unittest discover -s decklab/tests -t .`
  ran **2,273 tests in 352.052 seconds: OK, 34 skipped**. The 34 skipped cases
  were not executed; no live Forge qualification is claimed.
- `git diff --check` and `python scripts/audit_source_lengths.py --check` pass.

The background server was stopped before the work. Tests use temporary data,
fake Forge processes and loopback test servers; no live Forge qualification or
overnight experiment is part of this structural refactor.

# Source-length audit - 2026-10-11

`python scripts/audit_source_lengths.py --check` failed again on `c03a3b4`: four
owned files had grown past 1,200 lines. `lib/tokens.py` (1,191) was split with
them, since it was nine lines short. The same rules as above applied: code moved
verbatim, entry points and import paths kept, each patched name with one home,
and test classes moved rather than re-exported.

| Original file | Before | Largest resulting file | Responsibilities |
|---|---:|---:|---|
| `server.py` | 1,413 | 689 (`lib/server_http.py`) | The script (arguments, `main`, the import-crash log); `lib/server_http.py`: host checks, the request handler and `make_server`; `lib/server_run.py`: startup, the tunnel listener, shutdown and the console handler |
| `lib/cards.py` | 1,290 | 874 (`cards.py`) | Downloads, lookup, prices and images; `lib/card_index.py`: building the index from the bulk files (no state or file locations), re-exported by `cards` |
| `lib/tokens.py` | 1,191 | 615 (`tokens/__init__.py`) | A package: reading the inventory, `deck_tokens`, holders, the check and CLI in `__init__`; `rows.py`, `names.py`, `details.py`, `matching.py` and `needs.py` |
| `tests/test_web.py` | 1,258 | 601 (`test_web.py`) | Static assets and shared helpers; matchup screens (`test_web_matchup_files.py`); page contracts (`test_web_pages.py`) |
| `tests/test_forge.py` | 1,206 | 814 (`test_forge.py`) | Shared fixtures and CLI/status; `cardlog-check` (`test_forge_cardlog_check.py`) |

`server.py` is still the script that `homenet start` and Task Scheduler run. It
re-exports the unpatched public names of its two modules; patched names (`log`,
`make_server` and the lifecycle helpers) live only in `server_http` or
`server_run`, and the tests patch them there. `cards` reads `_now` through
`card_index` instead of keeping a second binding. New guard tests check this:
`test_server_lifecycle.ModuleSplitTests` (three cases), and
`test_cards.TestTagMembers.test_tag_tree_readers_have_one_home` and two in
`test_tokens` for the token package.

## Verification

- Each split was made on its own branch and checked by two independent reviews:
  an AST comparison of every moved function and class body against `c03a3b4`,
  importability of every name callers use, and every test patch target.
- Test discovery keeps all 2,954 original cases, with no duplicates or import
  failures; the six new ones are the guards above. The cardlog-check cases moved
  to their own class and keep `CommandLineTests`' deck fixtures.
- `python scripts/audit_source_lengths.py --check`: 348 owned source files, none
  over 1,200 lines. The longest is now `web/accessories.js` (1,103).
- **Full suite:** `python -m unittest discover -s decklab/tests -t .` ran **2,960
  tests in 612.8 seconds, 30 skipped**, with one failure that predates the split:
  `test_editor.PersonSpaceTests.test_saving_and_refused_fields` (403, not 400, for
  a member's `sleeves` field) fails the same way on `c03a3b4`. An earlier full run
  also had two timing failures (`test_forge_pool`'s one-second readiness timeout
  and a test server's connect timeout), in code the splits don't change. They
  passed in the second full run, alone, and in five of six later runs of their
  two modules (the one failure there wasn't recorded by name); the base passed
  three runs of the same modules.

# Source-length audit - 2026-10-19

`python scripts/audit_source_lengths.py --check` failed on `51528fd`: two owned
files had grown past 1,200 lines. `lib/api/activity.py` (1,199) was split with
them, since it was one line short. The rules above applied again: code moved
verbatim, entry points and import paths kept, each patched name with one home,
and test classes moved rather than re-exported.

| Original file | Before | Largest resulting file | Responsibilities |
|---|---:|---:|---|
| `web/editor-screen.js` | 1,380 | 635 (`editor-screen.js`) | The page and head, banners, tabs, the write-up, `changed()`, the side panel, Stats and the bar; `editor-details.js`: Deck details and the Sleeves/Deck box pickers; `editor-lines.js`: the list on the Cards tab (rows, tiles, steppers, moving and removing lines) |
| `tests/test_feature_ui.py` | 1,227 | 557 (`test_feature_ui_tokens.py`) | Collection, Build decks and History, with the shared `run_js`; Sleeves & boxes (`test_feature_ui_accessories.py`); Tokens (`test_feature_ui_tokens.py`) |
| `lib/api/activity.py` | 1,199 | 473 (`activity.py`) | Entry points, the visibility rule and the patched names; `activity_summaries.py`: what each row says; `activity_headlines.py`: headlines and `describe()` |

The two new editor scripts load straight after `editor-screen.js` in `index.html`;
apart from one object literal (`KIT_PICK_WORDS`) they run nothing at load, so the
order of the other editor scripts is unchanged. `activity.py` re-exports the names
its callers import; `row_cards`, `_load_orders`, `ROW_CAP` and `OrderFacts`, which
the tests patch, live only there. New guards check this:
`test_activity_privacy.ModuleSplitTests` (two cases). The moved UI test classes
reach the shared runner through the `test_feature_ui` module, never by importing
`FeatureUiTests`, so it isn't discovered twice.

## Verification

- Each split was made on its own branch from `51528fd` and checked by two
  independent reviews: a body-by-body comparison against the original (AST for
  Python; top-level items and line runs for the script, with no line lost or
  duplicated), and every caller, test patch target, script list and `_run_page`
  file tuple.
- Test discovery keeps all 5,846 original cases, with no duplicates or import
  failures; the two new ones are the guards above.
- `python scripts/audit_source_lengths.py --check`: 690 owned source files, none
  over 1,200 lines. The longest is now `tests/test_inventory_contract.py` (1,171).
- **Full suite:** `python -m unittest discover -s decklab/tests -t .` ran **5,848
  tests in 1,149.1 seconds: OK, 34 skipped**.
