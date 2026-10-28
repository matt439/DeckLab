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

<a id="maintenance-backlog"></a>

# Maintenance backlog - 2026-10-28

This is the implementation owner for the hygiene lane requested on 2026-10-28.
[TODO.md](../TODO.md) owns readiness and order; E11-S36 to E11-S43 in
[stories.md](design/stories.md) own acceptance criteria. Each task is finite:
finish its stated scope, record the result here/HISTORY.md and remove its TODO
row. A later audit may identify another concrete task. The dated audits above
remain historical evidence, not measurements of today's checkout.

## Starting evidence

The inventory check on `c678f10` reads **1,084 owned source files**. **One exceeds
1,200 lines:** `web/tokens.js`, at **1,460**. `--check` exits **1**; this backlog
change does not fix or waive that failure. There are 29 owned source files over
1,000 lines, including tests. Being below the threshold is not proof of a good
module boundary, and being large is not by itself a reason to split a cohesive
file. No lower blanket threshold is introduced.

## Tokens and CI guard completed: E11-S36, E11-S43

Built 2026-10-28. `web/tokens.js` is now **1,093 lines**; the extracted
`web/tokens-edit.js` is **370 lines**. All 16 workflow functions, from
openTokenSheet through showTokenConflict, retain their original bodies and
global names. The original file retains its shared constants, parser and page
state; only two trailing blank lines were trimmed. Browser and shared Node
loaders register the new deferred script directly after tokens.js. The
parser-only test loader is unchanged.

The inventory now contains **1,086 owned source files**, with **none above
1,200 lines**. The existing audit implementation, threshold and exclusions are
unchanged. lint.yml runs its seven new temporary-Git regression tests and
`--check` alongside the existing Ruff command. Hosted CI has not run for this
local change.

Verification: 58 focused Tokens/UI/parser/asset checks and seven guard checks
passed without skips, both JavaScript syntax checks pass, and independent
source-body/loader/guard review is clear. The full integrated suite ran
**9,050 tests in 2,234.874 seconds: OK, 74 skipped**, including all seven guard
cases. Skips: 31 opt-in real Forge/JDK checks, 22 POSIX/Linux checks, 20 absent
private-history fixtures and one Windows symbolic-link privilege check.
Discovery preserves all 9,049 existing cases plus seven new ones, with no
duplicates or import errors; class-setup skips reduce the run count. Ruff's
real-error checks and `git diff --check` pass.
No household data or migration was changed, and no Forge games were run.

## Starting measured targets

| id | Measured target | First structural boundary |
|---|---|---|
| E11-S36 | `web/tokens.js`, 1,460 | Add/edit/conflict sheets, openTokenSheet through showTokenConflict |
| E11-S37 | `web/editor-cards.js`, 1,137 | Paste/replace and Start from, apart from search/viewport setup |
| E11-S38 | `lib/api/collection_edit.py`, 1,116 | CSV detection, conversion and upload parsing, apart from HTTP writes/previews |
| E11-S39 | `lib/inventory/pg.py`, 1,133 | Table-row snapshot conversion, apart from cache/transaction/write coordination |
| E11-S40 | `tests/test_inventory_contract.py`, 1,173; `tests/test_api_permissions.py`, 1,126 | Concrete test groups, apart from shared fixture/base support |

Other large files include `web/editor.js` (1,188), `web/deck.js` (1,179),
`lib/api/forge_runs.py` (1,163) and `web/components.css` (1,161). Review their
responsibilities when the next change needs room; they are not extra split
tasks solely to make the numbers smaller. CSS ordering includes later
coarse-pointer/forced-colors overrides. Forge-run visibility reads mutable
coordination/configuration owners, so an extraction needs an explicit patch
ownership plan rather than a generic facade.

## Split contracts

- Move coherent responsibilities; retain existing bodies unless an ownership
  reference must change. Compare every moved function/class and account for
  every removed/added top-level item. Do not compress code or raise the limit.
- Keep classic browser scripts and their initialisation order. Register new
  files in index.html, the explicit static-asset contract and all affected Node
  runner file lists. Preserve global callers, route/profile guards and listener
  lifetime; a split introduces no build step.
- Keep each mutable state value and patched name with one authoritative owner.
  Existing imports and test patches must reach that owner; copying bindings
  into another module is not compatibility. Preserve server.py's entry point.
- Source splits preserve observable behaviour, API responses, permissions,
  transaction/locking boundaries, canonical bytes and error handling. Feature
  changes belong in separate commits. Use fixtures and disposable databases;
  no household write, live migration or Forge game is part of these tasks.

### Tokens and editor workflows: E11-S36, E11-S37

The completed Tokens split extracts the contiguous sheet workflow into a
focused classic script, keeping current globals and state lookup. Parser-only
loading for test_token_details_js.py is unchanged. Token UI/conflicts, physical
row identities, details parity and asset order remain the verification contract;
the source-length check now passes.

For the editor, start with mergedLists/openPaste/mergeLines/replaceLines and
startFromPart/choiceSheet/openPreconStart/openDeckStart. Keep search and viewport
listeners in their current execution order. Verify existing paste/replace
previews, Undo, precon/deck starts and Quick edit. This creates room for E9-S07;
the extraction itself adds no EDHREC behaviour.

### Collection parsing and database snapshots: E11-S38, E11-S39

For collection imports, extract detect/_source_rows/read_upload and their
format conversion helpers. Preserve callers of collection_edit.read_upload
and match, and the behaviour of patched MAX_IMPORT_ROWS/MAX_IMPORT. Keep preview
storage, _upload_date, IMPORT_TTL/IMPORTS_DIR and locking in their existing
owner. Validate supported/malformed exports, scanner and merge consumers,
precon/trade callers and exact refusal outputs. E7-S03's grouping is separate.

For PostgreSQL snapshots, extract snapshot/_render and fixed row conversion
helpers. Leave PgInventory, _diff, _take_lock, revision/cache ownership and
transaction coordination in place. Preserve canonical rendering, hidden token
and watchlist ids, schema capability checks, locations and dual revisions.
Validate inventory contract goldens and disposable-database location, deck
persistence and rollback cases; no golden changes should be needed for a
behaviour-preserving split.

### Test support and discovery: E11-S40

Move concrete PostgreSQL contract cases first, retaining adapt, scenario/golden
helpers, CLAUDE and FIXTURE_PROFILES at established support imports. Then move
permission route groups while retaining PermissionTestCase for its consumers.
Do not re-export concrete test classes. Compare discovered cases before/after
by their class/method identity with an explicit module-move map, so a renamed
module is neither mistaken for lost coverage nor counted twice. Check the
four-shard partition, setup/cleanup lifetime and affected fixture consumers.

Run focused checks for each split, JavaScript syntax checks for changed scripts,
and the full integrated suite before closing a structural split. Report skips
separately. Fixture checks do not establish household-device acceptance or real
Forge qualification.

## Comment audit: E11-S41

Start with the module headers and surrounding storage/privacy/lifecycle
comments in these named files, checking each claim against its runtime owner:

- `lib/api/play_records.py`: the header still says decks are files.
- `lib/api/accessories.py`: the header still calls the file backend a rollback
  path; runtime rollback was retired.
- `lib/api/collection_edit.py`: the header describes runtime collection paths,
  configurable file storage and rollback rather than database-backed snapshots.
- `web/editor.js`: the claimed eight-script inventory is behind index.html.
- `web/tokens.js`: tokSpacePicker says Home and each person, while seenSpaces
  filters the visible choices.
- `web/deck.js`: its Overview description omits implemented panels.
- `tests/test_api_permissions.py`: the header overstates anonymous/local
  access, despite the current script boundary and space-specific read rules.

Record checked modules and corrections with implementation evidence. Preserve
accurate rationale for locks, permission checks, compatibility and test backends;
do not delete comments wholesale or restate every line of code. In particular,
FileInventory.from_git still exists for fixture/history helpers and must not be
described as a removed API. No substantive TODO/FIXME/HACK markers were found in
the owned Python/JavaScript scan, so a generic marker-cleanup task is not added.
Comment-only changes need diff checks and any syntax check made relevant by the
edit, without prose-only regression tests.

## Developer instruction audit: E11-S42

Compare AGENTS.md's Logging new cards and Sleeves, deck boxes and playmats
instructions, plus matching README command examples, with the current parsers:
receipt previews support receive --expect; product-kit commands exist. Correct
those contradictions and the immediate database/file/retired-rollback guidance.
CLAUDE.md includes AGENTS.md, so do not create a second instructions copy.
Preserve dated history and private-repo/tag references where they are accurate.
Check command help without an apply, migration or household read/write. Changes
to command behaviour are outside this documentation task.

## Continuous source-length guard: E11-S43

Built 2026-10-28 after E11-S36 cleared the known failure. The cheap lint workflow
runs the existing --check invocation alongside its unchanged real-error Ruff
checks. The 1,200-line threshold, ignored-cache rules, tracked/untracked inventory
and pinned-upstream exclusion policy are unchanged, with no Tokens exception.
`test_source_lengths.py` uses temporary Git fixtures for the 1,200/1,201 boundary,
UTF-8 BOM and missing final newline, tracked/untracked/current contents, ignored
caches, exact upstream directory, all six source suffixes, deleted tracked files
and report-only behaviour. The job requires no database, card cache or Forge
installation. Hosted CI results remain separate from local validation.
