# The combined idle-PC run for waves 2 and 3: runbook and harness design

**Date:** 2026-10-03. **Status:** design, revision 2 (the three reviews are folded in; §12 says where each runbook
finding went). Wave 3's H package builds the harness. It runs once both waves are integrated on `sim-w3`
(CONTRACT-W3.md §21 step 10). **Revision 3 (the base, 2026-10-03):** the owner's answers are final (Fiery adopted;
±2/±3 margins; the 3-hour soak minimum); the start is 22:00 home time tonight; an optional package (A, F, V, X)
that misses the 20:45 merge cut-off isn't in `sim-w3`, and the harness drops its items up front (CONTRACT-W3.md §21,
"This build's merge plan"). In the repo this file is `decklab/forge-trial/sim-combined-run.md`, and CONTRACT-W3.md is
`decklab/forge-trial/sim-wave3-contract.md`.

**Owner decisions behind it:**
- Idle PC time is the scarce resource. So wave 2 isn't measured on its own: one unattended run (overnight,
  target ≤ ~6 h) measures waves 2 and 3 together.
- The run's shape:
  1. about 1 h of clean timing battery;
  2. about 4-5 h of real work that doubles as the warm pool's soak: replaying every current matchup into a staging
     folder, wave 3's AI experiments, and a full field-view run, with periodic fresh-against-warm log diffs and
     throughput and memory tracking;
  3. optional 4-player Commander pods (M6) and the external check against human win rates (M7) last, and the first
     to go.
- Main stays on wave 1 until the run passes.
- Staged results move into the real results folder only after the checks pass.
- AI overrides and pilots are adopted afterwards, from the experiment data. Fiery Annihilation is the one exception,
  adopted before the run (the owner's decision, CONTRACT-W3.md §0.6 question 1); the run would work either way.

**Names.** The merge gates are **MG1-MG16** (§9.1). Plain G-numbers (G2, G8, G13...) are the plan's open questions
(`sim-investigation.md` §7), which some items answer.

## 1. What the run decides

1. **Merge `sim-w3` (waves 2 and 3) into main:** PASS, FAIL or INCOMPLETE (§9.1).
2. **Move the staged replay results into the real results folder** (§9.2).
3. **Evidence for later adoptions** of override sets and pilots (§9.3). This is evidence, not a gate.
4. **Numbers for the plan:**
   - speed: warm vs cold pool vs wave 1 main; pinning (none, per core, per CCD), idle and under load; K = 16/20/24/32
     warm; PERFORMANCE_MODE (Constructed and Commander); R14a and R14b; R04 warm; Commander warm; the server path and
     EcoQoS;
   - the pool's life: soak, memory, drift, the 15-minute idle close, the idle footprint and re-warm;
   - stopping and coverage: how many games adaptive stopping saves; how long a field run takes;
   - accuracy: the CRN coupling deck-order-1 buys; shared vs per-pair seeds; known-ordering ladders; pilot
     sensitivity; the v3 "in hand by turn 3" numbers against the logs;
   - the rates for Deck Lab's time estimates (`rates.json`, CONTRACT-W3.md §9.5).

## 2. Where it runs

| What | Where |
|---|---|
| Code under test | the worktree `C:/VSProjects/TCC-wt/w3-run`, detached at the `sim-w3` commit under test, with main merged in. The harness records `git rev-parse HEAD` |
| Wave 1 baseline | the main checkout `C:/VSProjects/TradingCardCollection`, read-only: its CLI with `--results-dir` under OUT. Its card-log jar and checks are its own |
| Python | since phase 5a of the database move (2026-10-12), A1 reads the decks from Deck Lab's database, which needs psycopg, and a worktree has no `.venv`. Run `overnight.py` with the main repo's `C:/VSProjects/TradingCardCollection/.venv/Scripts/python` (or give w3-run its own `.venv`) where §3 and §4 say `python`; otherwise A1 fails with `deck_lists` = `error: Unavailable` |
| Data | `w3-run/decklab/data/`: its own Forge user folder, card-log jar, `checked.json`, card data, and its own (empty) results folder, which only the API field run (D3a) writes |
| Output, `$OUT` | `w3-run/decklab/data/forge/overnight/<YYYY-MM-DD of the evening it starts>/` (gitignored) |
| Monitor | H's `decklab/forge-trial/overnight_monitor.py`: CPU by process class (the run's own, system, other), input presence, java count and working set. It reuses `sim-investigation/tools/cpusampler.py`'s code by import |
| Test servers | 127.0.0.1:8643 (D) and 127.0.0.1:8644 (the idle-close leg), always started with `--no-update` |
| Slots | the machine-wide budget (`%LOCALAPPDATA%/DeckLab/forge-slots`), as every run uses |

`$OUT` holds:
- `plan.resolved.json`, `state.json`, `log.txt`, `cpu.csv` (and its `.meta.json`), `mem.csv`;
- `inputs/` (from `prepare`);
- `staging/results/`: the copy of the real results, the replayed results, the field reference, and the variant tests'
  `paired/` folder;
- `B/`, `C/`, `D/`, `E/`: one folder per item;
- `experiments/`, `probes/`, `logs/` (the tee'd chunk logs, gzip);
- `REPORT.md`, `report.json` and `rates.json`.

## 3. Daytime preparation (no idle PC needed; small Forge runs allowed)

PowerShell. `$NIGHT` is the date of the evening the run starts.
```powershell
# 1. sim-w3 complete (CONTRACT-W3.md §21 step 10), with main merged in, and the suite green
git -C C:/VSProjects/TCC-wt/w3-int merge main
cd C:/VSProjects/TCC-wt/w3-int; python -m unittest discover -s decklab/tests -t .
# 2. the worktree for the run, at that commit
git -C C:/VSProjects/TradingCardCollection worktree add --detach C:/VSProjects/TCC-wt/w3-run sim-w3
# 3. card data for the worktree (copy main's; or: python -m decklab.lib.cards update)
robocopy C:/VSProjects/TradingCardCollection/decklab/data/scryfall C:/VSProjects/TCC-wt/w3-run/decklab/data/scryfall /E
# 4. the card log and its v2 check in the run's own data folder (≤ 4 processes, about 5-10 min)
cd C:/VSProjects/TCC-wt/w3-run
python -m decklab.lib.forge status
python -m decklab.lib.forge cardlog-check
python -m decklab.lib.forge overrides deploy
python -m decklab.lib.forge overrides check
python -m decklab.lib.forge pilots --check
# 5. resolve the plan against today's lists, then review its inputs and estimates
$NIGHT = "YYYY-MM-DD"
$OUT = "C:/VSProjects/TCC-wt/w3-run/decklab/data/forge/overnight/$NIGHT"
python decklab/forge-trial/overnight.py prepare --out $OUT --main C:/VSProjects/TradingCardCollection
python decklab/forge-trial/overnight.py plan --out $OUT --budget-h 6
# 6. smoke: every item at a tiny size, ≤ 4 workers, no idle gate, with the crash drill (about 20 min)
python decklab/forge-trial/overnight.py supervise --out "$OUT-smoke" --smoke --main C:/VSProjects/TradingCardCollection
```

**What `prepare` writes to `$OUT/inputs/`**, for review before the night:
- **`variants.json`:** the M4 variants of Gruul Ramp's target list.
  - The 1-card variant takes 1 copy away from the deck's most-played nonland card with 2 or more copies, and adds 1
    more of another nonland card already in the deck.
  - The 2-card variant takes 2 nonland copies away and adds 2 of the deck's most common basic land.
  - Each variant is also written as a full decklist, `variant-1.txt` and `variant-2.txt`, for `variant --list`.
- **`ladders.json`:** for Izzet Prowess, Selesnya Rabbits, Mono-White Angels, Gruul Ramp and Mono-Black Midrange.
  - Each deck's 6 "key" nonland copies, in pairs: the copies with the best "won more when drawn" estimate in its saved
    card stats (`cards <deck> --json`).
  - Lands are added in the deck's basic-land proportions.
  - Each ladder has a reference opponent: Izzet ↔ Gruul, Rabbits ↔ Vampires, Angels ↔ Zombies, and MBM ↔ Lightning
    Aggro.
  - Each rung is written as a full decklist, `ladders/<deck slug>-<2|4|6>.txt`.
- **`exp-*.json`:** the experiment specs, each set resolved to the field lists that hold its cards, each played
  against that list's reference opponent. The Fiery pair's arm is whichever of "with `fiery`" and "without" isn't
  today's adopted state.
- **`estimates.json`:** each item's games and minutes:
  - each matchup from its own v1 median Forge ms per game divided by the warm speed-up (2.0 until B2 measures it),
    falling back to the `board` class for a pair without saved games (The Free Peoples' new pairs, product decks);
  - each experiment from `experiment --dry-run` against the staging the replay will leave (today's game counts),
    **including the control games staging won't hold** (profile mirrors, the Rabbits mirror, most of D2e's pairings);
  - the D items' soak time, and the filler needed to reach the soak minimum (§5.5).
- **`m7/`:** M7's decks and human win rates, copied from `forge-trial/m7/` (the daytime research of 2026-10-03:
  7 Pauper decks, their lists from July-October 2026 events, and MagicMeta's published human matchup matrix,
  every card name checked against Forge 2.0.15). Without them, M7 is skipped. An `$OUT/inputs` prepared before
  they were merged lacks them: copy `forge-trial/m7` to `$OUT/inputs/m7` by hand.

`plan` prints each item's priority, its estimate, the total against the budget, and the up-front drop decision
(§5.5). Fix the inputs, or the plan's `--budget-h`, until the P0 and P1 items fit.

**The smoke run** (`--smoke`): every item at a tiny size, ≤ 4 workers, no idle gate, a 10-minute soak minimum, and it
never stops the 8642 server (it only records its state). It also runs **the drill**:
- the harness kills its own controller during the first D item; the supervisor must resume it, the item must finish,
  and cleanup must find no run-owned leftovers;
- one item that ignores its STOP file must be ended by `TerminateJobObject` on its job;
- a dummy foreign `java.exe` (started outside the run's job) must be reported, never killed.

## 4. The night: starting it

1. **The PC:**
   - Close apps. Pause Windows Update for a week (Settings → Windows Update), so no reboot happens at night.
   - Move Windows' Automatic Maintenance to a daytime hour (Control Panel → Security and Maintenance → Automatic
     Maintenance → Change maintenance settings, for example 12:00), or untick "Allow scheduled maintenance to wake up
     my computer" and make sure it won't run in the window.
   - Optional, the owner's call: a Microsoft Defender exclusion for `$OUT`. Without it, Defender scanning the new log
     files is counted as "system" CPU (§5.2): it doesn't pause the run, but it can mark a timing leg noisy.
   - The controller keeps the PC awake for the whole run (§5.1); no power-setting change is needed.
2. **Leave the background Deck Lab server (8642) as it is.** The controller records whether it was running, stops it
   at A1, and starts it again at the end if it was running.
3. **Daylight saving:** if the PC's time zone observes it (NSW, Victoria, ACT, Tasmania, SA), it starts at 02:00 on
   Sunday 2026-10-04, when clocks jump to 03:00. A run on the night of 3-4 October has an hour less before a 07:00
   deadline. The harness handles the jump (§5.3), but prefer another night, or set `--deadline 08:00`.
4. In a console window, minimised and left open (closing it ends the run and everything it started):
   ```powershell
   cd C:/VSProjects/TCC-wt/w3-run
   $NIGHT = "YYYY-MM-DD"
   $OUT = "C:/VSProjects/TCC-wt/w3-run/decklab/data/forge/overnight/$NIGHT"
   python decklab/forge-trial/overnight.py supervise --out $OUT --budget-h 6 --deadline 07:00 --main C:/VSProjects/TradingCardCollection
   ```
5. The harness waits for the idle gate (§5.2), then runs on its own.

Other commands:
- `overnight.py status --out $OUT`: where the run is, its active time, the soak time so far, and what has been
  dropped.
- `overnight.py supervise --out $OUT --resume --budget-h H --deadline HH:MM`: continue in a new session after an
  interruption (§5.3).
- `overnight.py report --out $OUT [--write-rates <path>]`: write the report again from the outputs, and optionally the
  measured rates for Deck Lab's estimator.
- `overnight.py clean --out $OUT`: end the run's own leftovers (never another process's).

## 5. Harness design (H: `decklab/forge-trial/overnight.py`, `overnight_legs.py`, `overnight_monitor.py`, `overnight_report.py`, `overnight-plan.json`)

### 5.1 Process model

- **The supervisor** (`overnight.py supervise`) starts the controller and waits for it. After an unexpected exit
  (a Python exception, a crash; not a STOP, not a fail-fast stop, not the deadline) before the deadline, it starts
  `run --continue-session` again, at most twice. That continues the same session: the same deadline and budget.
- **The controller** (`overnight.py run`, standard library only) reads `plan.resolved.json` and `state.json`, and runs
  the items in plan order, one at a time. Periodic probes (§7) are its own items, scheduled between or beside them.
  - It calls `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` at start, so the PC doesn't sleep while it
    runs (sleeping would fire Forge's wall-clock game clocks and AI timeouts on resume).
  - Each item is one or more child processes: a Deck Lab CLI command, or an `overnight_legs.py <leg>` (legs use the
    Python API in-process, for example several timing rounds in one pool session).
  - The controller creates one Windows Job object for the run with `KILL_ON_JOB_CLOSE`, and one nested job per item.
    So if the controller dies, everything it started dies. Forge's JVMs sit in W2's own jobs, nested inside these.
  - Each child's stdout and stderr go to `<item dir>/out.txt`, and its environment carries `DECKLAB_STOP_FILE=<item
    dir>/STOP`.
- **Graceful stop:** the controller creates `STOP`. The child's runs stop as the page's Stop does, keeping their
  finished games (CONTRACT-W3.md §8). After 60 s the controller ends the item with `TerminateJobObject` on the item's
  own job (not `taskkill /T`, which misses re-parented processes).
- **The test server for D:** at D0 the controller starts `python decklab/server.py --host 127.0.0.1 --port 8643
  --no-update` as a child, with `DECKLAB_SEED_BASE=2` in its environment (only runs planned in the server, the API
  field run of D3a, use it; CLI runs plan their own seeds).
  - The CLI items of D submit to its pool: the production path (a pool owned by the server, CLI submits, heartbeats,
    recycling at `WORKER_MAX_GAMES`).
  - Items with other launch identities (experiment user folders, knobs) play in local pools, as W2 says. The server's
    live-JVM cap retires its idle workers meanwhile.
  - At D9: `python decklab/server.py --stop --port 8643`, then `TerminateJobObject` on its item job after 30 s.
- `--no-update` on every test server: otherwise `server.py`'s start-up thread runs `cards.update()`, which can download
  and parse Scryfall's bulk files (the robocopied data may be over a week old) and checks again daily. A1 records the
  card data's age; the report checks it didn't change.

### 5.2 Idle gate and monitor

**What the monitor records** (`overnight_monitor.py`, a thread of the controller, every second, into `cpu.csv`):
- CPU by process class:
  - **own**: every process in the run's job (IsProcessInJob, which covers nested jobs): the controller's children, the
    CLI and leg Pythons, soak-probe, the test servers, every JVM, gzip;
  - **system**: Defender (`MsMpEng.exe`, `MpDefenderCoreService.exe`), Windows Update and maintenance (`TiWorker.exe`,
    `TrustedInstaller.exe`, `MoUsoCoreWorker.exe`), `SearchIndexer.exe`, `CompatTelRunner.exe`;
  - **other**: the rest, as a share of all logical CPUs (`other_pct`);
- **input presence:** seconds since the last keyboard or mouse input (`GetLastInputInfo`);
- `java_n`, `java_ws_mb` (the run's JVMs), and slots held by processes outside the run;
- a gap of more than 5 s in the `unix` column is flagged as a sleep or suspension in the report.

The monitor runs until the deadline plus 30 min. If it stops, the controller restarts it and logs the gap.

**At the start:** no input for 10 min, and `other_pct` under 5 % for 60 s. Otherwise it checks again every minute, for
up to `--start-wait` (60 min); then it ends with "the PC was never idle" (INCOMPLETE).

**Timing legs (B, C1-C3, drift probes):**
- Before each: no input for 2 min, and `other_pct` under 5 % for 10 s.
- A leg is **noisy** when, during it, there was any input, `other_pct + system_pct` averaged more than 3 %, any 30-s
  window was over 10 %, or a slot was held outside the run.
- A noisy leg is queued once more at the end of its block if there's time. A leg noisy twice stays noisy: the gates
  that need it are "not checked" (§9.1), and a P0 gate "not checked" makes the run INCOMPLETE, never FAIL.
- Noisy drift probes and soak timings are dropped from MG11; soak verdicts (outputs, not times) still count.

**In use (pause):** any input in the last 60 s, or `other_pct` (system excluded) above 15 % for 120 s.
- No new item starts.
- A timing leg that's running finishes, marked noisy.
- A D item that's running goes on (Forge runs at BELOW_NORMAL), unless input continues for 5 min or `other_pct` stays
  over 30 % for 5 min. Then it's stopped gracefully and queued again; D items are idempotent.
- The run resumes after 5 min with no input and `other_pct` under 5 %.
- Paused time doesn't count against the active budget, but it does count against the deadline.

### 5.3 Checkpoints, sessions and resume

- **`state.json`**, written atomically after every change:
  ```jsonc
  {"run_id", "identity": {"commit", "jar_stamp", "forge_version", "forge_build", "simulation_sha", "sets_sha",
                          "deployed_hash", "deck_lists", "main_commit", "card_data_mtime"},
   "server_was_running": true, "test_servers": {"8643": {"pid"}},
   "sessions": [{"started", "deadline_epoch", "budget_s", "active_s", "paused_s", "soak_s", "soak_server_s",
                 "b_complete": false}],
   "own_pids": [[pid, creation_time]],
   "items": {"<id>": {"status": "pending|running|done|failed|dropped|cut|skipped|noisy", "attempts", "session",
                      "started", "ended", "active_s", "outputs": [...], "note"}},
   "dropped": [{"id", "why"}], "rates": {"fast": 1400, "board": 280, "commander": 200, "medium": 900}}
  ```
- Each item writes `<item dir>/done.json`, listing its outputs, when it completes.
- **Time:** the deadline is an absolute instant: `--deadline HH:MM` is turned into epoch seconds with the operating
  system's local-time rules (`time.mktime` with `tm_isdst=-1`), so a daylight-saving change is handled. Every interval
  (probe schedules, "since the last probe", overruns, active time) uses `time.monotonic()`.
- **`--resume` starts a new session.** It needs a new `--deadline` and `--budget-h`; the budget is per session.
  - It refuses ("The code, the jar, Forge, the overrides or the deck lists changed since this run started: start a new
    run.") when any `identity` field differs from the run's.
  - **The deck lists (since phase 5a of the database move, 2026-10-12):** the decks are in Deck Lab's database, not
    `magic/`, so `identity` records `deck_lists` (`overnight_common.deck_lists()`) instead of `magic_tree` (git's tree
    of `magic/`). It's a sha256 of every deck's id with its target and substitute lists, parsed and written back as
    Deck Lab writes them, so a table refresh after an order or a receipt doesn't stop a resume, and a changed list
    does. A deck whose text can't be parsed counts by its error. When the decks can't be read at all (no `.venv`,
    the database down) the value is `error: <type>`, and `--resume` always counts that as a difference
    (`ALWAYS_DIFFER_ON_ERROR`), even when both sessions recorded the same error. A run folder recorded before has
    `magic_tree`, so its `--resume` refuses.
  - It skips `done` items, cleans up `running` and `failed` items and runs them again. An item fails for good on its
    second failure, and the run goes on.
  - **Timing stays within a session:** if B didn't finish in the earlier session, the new session runs B0, B1a and B2
    again before the remaining B legs, and B1b at the end. Legs are compared only with B1 and B2 of their own session.
  - **Soak gates are judged per session:** MG7, MG10 and MG11 use one session's D. If no session met the soak minimum
    (§5.5), they're "not checked" and the run is INCOMPLETE.
  - It starts the monitor and the test server again.
- **What resumes how:** D's items continue where they stopped (replay, field, variant and experiment play only what's
  missing); timing legs start again from scratch (their result folders are emptied first).
- A single-instance lock, `$OUT/.lock` (an OS lock), stops a second controller.
- **A reboot or power cut:** the morning `status` shows what's missing. Run `supervise --resume` in the next idle
  window. The report counts only finished items.

### 5.4 Cleanup

- **Only the run's own processes are ever ended.** A process is the run's when it's in the run's job (IsProcessInJob),
  or its (pid, creation time) is in `own_pids` (the controller records the job's process list,
  `QueryInformationJobObject(JobObjectBasicProcessIdList)`, every 30 s). A `java.exe` that isn't the run's is
  **foreign**: it's reported with its command line, never killed. So the owner's own Deck Lab runs, and another
  session's CLI, are never touched, by day or by night.
- **After every item:** the run's processes that belong to no live item are leftovers: `TerminateJobObject` on their
  item's job, else `taskkill /PID <pid> /T /F` per recorded pid. Then `python -m decklab.lib.forge slots --json`: a
  slot held by a dead process or a run leftover is an error; one held by a foreign live process is reported (it lowers
  the run's workers, and marks a running timing leg noisy).
- **At the end (E4):**
  - stop the test servers;
  - stop the monitor (before MG12's check);
  - delete `forge*.log` only in w3-run's user folders (never main's);
  - keep experiment user folders and tee'd logs, for diagnosis;
  - start the 8642 server again (`python -m decklab.lib.homenet start`) if `server_was_running`.
- MG12 (§9.1) counts the run's own leftovers found **at the end**. Leftovers found during the run are reported but
  don't fail the run on their own.

### 5.5 Time budget control

- **Each plan item has:** `id`, `block`, `priority` (P0-P3), `depends`, an estimate (from `estimates.json`), `shrink_min`
  (the smallest scale factor, or none), `exclusive` (true for speed-sensitive items: nothing else runs during them, and
  soak probes are suspended), `preemptible` (true for D1, D3a-ref and the filler: the controller may stop one for a due
  drift probe and run the same command again; it plays only what's missing), and `pool` (`server` or `local`).
- **Rate classes** (warm, 16 workers, games a minute; e3/e4 estimates until B2 measures them):

  | Class | Games a minute | Pairs |
  |---|---|---|
  | `fast` | 1,400 | pairs of Izzet, Gruul, Angels, Zombies, MBM, Orzhov Removal, Lightning Aggro |
  | `medium` | 900 | The Free Peoples |
  | `board` | 280 | any pair with Rabbits or Vampires; any pair with no saved games |
  | `commander` | 200 | Commander pairs |

  A pair without its own v1 speed takes its slower deck's class. After B2 the classes are rescaled by the measured
  warm rates (IG, RV, GF).
- **The soak minimum (P0):** D must hold `SOAK_MIN` = 3 h of soak time (owner question, CONTRACT-W3.md §0.6): active D
  time with the run's Forge workers busy (from the 5-min pool polls and `java_n`), at least half of it on the test
  server's pool. When the planned D items can't fill it, the controller adds **filler**: the replay set again at seed
  base 5 (`DECKLAB_SEED_BASE`) into `$OUT/D/filler/` (server pool, preemptible, `--log-every 10`), as long as needed. The filler's win rates
  against D1's (base 1) are reported, not gated.
- **The up-front decision** (after A3, and at each session's start): forecast every item. Keep items in priority order
  (P0, then P1, P2, P3; plan order within a priority) while the total fits the session's budget and deadline minus
  E's 15 min and the filler the soak minimum still needs. Shrink P1 items to `shrink_min` before dropping any P1 item.
  The rest is dropped, with the reason.
- **Before each item** of priority p: `remaining = min(budget − active, deadline − now) − reserve(p)`, where
  `reserve(p)` = E's 15 min + the filler still owed + the estimates (at `shrink_min`) of every not-yet-run item with a
  **higher** priority than p (P0 is highest). So an early P2 timing leg never pushes out a later P1 item.
  - It fits: run it.
  - It doesn't fit, but its estimate × `shrink_min` does: scale its games down by remaining/estimate (≥ `shrink_min`).
    `cut` items keep what they played.
  - Otherwise drop it, with the reason.
  - A P0 item always runs. If a P0 item can't fit, every remaining P1-P3 item is dropped. At the deadline the run stops
    gracefully and is INCOMPLETE.
- **Drop order when behind:**
  1. P3: M7, M6, pilot sensitivity (c).
  2. P2: K = 20 and 32, per-CCD pinning, the R04-off and game-patches-off jars, ladders 4-5, the `hints`,
     `etb-flagged` and `tgt-gift` sets, profile mirrors, the hybrid AI, pilot sensitivity (b), the Commander field.
  3. Shrinking P1 items: the field reference from 1,600 to 800 a deck; experiments from 800 to 400 games a pair;
     adaptive savings without ZL's "ahead" run; D2a(4) to `--games 400`.
  4. Dropping P1 items, last in plan order first.
- **Overrun:** a P1-P3 item past 2× its estimate is stopped gracefully, keeps its data and is marked `cut`. A P0 item
  goes on.
- **Fail-fast** (§6 C): after C, a failed MG1-MG5 changes the plan.

### 5.6 The plan file

`decklab/forge-trial/overnight-plan.json` is tracked: the items of §6, with their command templates, priorities,
estimates and default parameters (decks, seed bases, sizes). `prepare` resolves it into `$OUT/plan.resolved.json`:
concrete card names, pairs, game counts and estimates. The report quotes the resolved plan.

## 6. Blocks in order

Budgets are active time. Commands are run from `C:/VSProjects/TCC-wt/w3-run` unless they say otherwise. `L =
python decklab/forge-trial/overnight_legs.py`, and `F = python -m decklab.lib.forge`.

**Workload codes** (target lists): `IG` = `casual/izzet-prowess` v `casual/gruul-ramp`; `RV` = `casual/selesnya-rabbits`
v `casual/orzhov-vampires`; `GF` = `commander/giada-angels` v `commander/finneas-rabbits`; `AL` = `casual/mono-white-angels` v
`product/challenger-2019-lightning-aggro`; `ZL` = `casual/mono-black-zombies` v `product/challenger-2019-lightning-aggro`;
`IA` = `casual/izzet-prowess` v `casual/mono-white-angels`.

### A. Preflight (P0, 10 min; the PC is busy about 3 min)

| Id | What | Command or check |
|---|---|---|
| A1 | the environment | `git merge-base --is-ancestor main HEAD` (main merged in); the database's decks can be read, `deck_lists` recorded (since phase 5a, 2026-10-12, which needs psycopg: run the harness with main's `.venv` python, §2, or this fails with `deck_lists` = `error: Unavailable`; it replaced `git diff --quiet main HEAD -- magic/` and `git -C <main> status --porcelain magic/`, as the decks left `magic/` in phase 4); the `identity` of §5.3 recorded; `F status --json`: card log ready and checked for this Forge build and source, the adopted sets deployed (`ensure_deployed`) and none stale, `pilot_switches` = [aisim-hybrid-1, team-pump-1]; `F pilots --check`; no run-owned java.exe (foreign ones reported); `F slots --json`: no slot held; no live `forge-pool-*.json` service file except the 8642 server's; ports 8643 and 8644 free; ≥ 15 GB free disk; card data age recorded; `python -m decklab.lib.homenet status`: the 8642 server's state recorded as `server_was_running`, then `homenet stop` if it's running (not in `--smoke`) |
| A2 | the idle gate | §5.2 |
| A3 | the staging snapshot | copy `C:/VSProjects/TradingCardCollection/decklab/data/forge/results/*.json` to `$OUT/staging/results/`; `F replay --results-dir $OUT/staging/results --dry-run --json` gives D1's games, which refine the estimates; the up-front drop decision (§5.5) |
| A4 | the monitor and keep-awake | §5.1, §5.2 |

### B. Timing battery (P0 23 min, P1 27, P2 20; capped at 80; every leg behind the idle gate, `exclusive`)

The legs use seed base 900001, so legs with the same engine play the same games. The order is A-B-B-A: B1 runs once
after a warm-up and once at the end, and the speed gates use the mean.

| Id | Pri | What it measures | Command | Est. |
|---|---|---|---|---|
| B0 | P0 | CPU warm-up (untimed) | from main: `F play casual/izzet-prowess casual/gruul-ramp --games 800 --seed-base 900001 --results-dir $OUT/B/b0` | 1.5 min |
| B1a | P0 | **wave 1 main, cold** (today's 16 × 50 / 16 × 25 batches); records whether main's card log is on (about 3 % of speed) | from `C:/VSProjects/TradingCardCollection`: `F play casual/izzet-prowess casual/gruul-ramp --games 800 --seed-base 900001 --results-dir $OUT/B/b1a/ig --json`; the same with RV `--games 400`; GF `--games 200` twice (two readings, into `gf1` and `gf2`) | 5 min |
| B2 | P0 | **waves 2 and 3, default** (K 16, pinned per core, PERF on, patches on). Round 0 is a fresh pool (start-up included); rounds 1 and 2 are warm | `L rounds --out $OUT/B/b2 --rounds IG800x3,RV400x3,GF200x3 --seed-base 900001` (one local pool session; each round into a fresh results folder, so every round plays games 0..N-1) | 11 min |
| B3 | P1 | **the server path:** CLI → a server pool started by `pythonw.exe` (plan G13), and EcoQoS on each JVM (`GetProcessInformation(ProcessPowerThrottling)`) | `L server-path --out $OUT/B/b3 --port 8643 --pythonw --no-update --rounds IG800x2` | 4 min |
| B4 | P1 / P2 | **pinning, idle:** none (P1); per CCD (P2) | `L rounds --out $OUT/B/b4-none --pin none --rounds IG800x3,RV400x1`; the same with `--pin ccd` | 4 + 4 min |
| B5 | P1 / P2 | **K warm:** 24 (P1); 20 and 32 (P2); core-wrap pinning; AI timeouts and memory (numbers only) | `L rounds --out $OUT/B/b5-k24 --workers 24 --pin core-wrap --rounds IG800x3,RV400x1` (likewise 20, 32) | 4 min each |
| B6 | P1 | **PERFORMANCE_MODE off** (another engine and its own user folder, so other games; speed only), Constructed and Commander; round 0 gives the cold path (v-r08) | `L rounds --out $OUT/B/b6 --perf off --rounds IG800x3,RV400x1,GF200x2` | 5 min |
| B7 | P1 / P2 | **patches warm:** R14a off (P1; neutral, so the same games); R04 off (P2; neutral); all game patches off (P2: R14b, deck-order-1 and TeamPumpAi installation; other games) | `L rounds --out $OUT/B/b7-r14a --exclude-patch forge/ai/AiController.class --rounds IG800x3,RV400x1`; `--exclude-patch forge/game/mulligan/AbstractMulligan.class`; `--game-patches off` | 4 min each |
| B9 | P1 | **pinning under load** (plan G14): a synthetic 4-thread CPU load at NORMAL priority (`L burn --threads 4`, started in the run's job and counted as "load", not "other"), then IG800x2 per-core pinned, and IG800x2 unpinned | `L rounds --out $OUT/B/b9-core --load 4 --rounds IG800x2`; the same with `--pin none` | 6 min |
| B1b | P0 | **wave 1 main, cold, again** (the A-B-B-A close) | as B1a, into `$OUT/B/b1b/...` | 5 min |

Each leg records: wall time, games a minute, the median and mean Forge ms per game, the start-up time, CPU (the
monitor's summary for the leg's window: own, system and other averages, all-cores-busy %, CCD split), the peak java
working set, the heap_mb of each worker, AI timeouts, clock stops, recycles by reason, and a per-game outcome table
(for MG6). B8 of revision 1 (adaptive savings) moved to D3c: its numbers are games, not wall time.

### C. Checks of the v2 engine (P0, 12 min; behind the idle gate)

| Id | What it checks | Command | Est. |
|---|---|---|---|
| C1 | **v2 against plain Forge** (M4): 20 Constructed games (IG) and 5 Commander (GF); DeckLabSim with game patches off against plain Forge `sim -n 1 -s game_seed(...)`, masked (W2 §4); differences replayed (§9.1's replay rule) | `L parity --out $OUT/C/c1 --constructed 20 --commander 5 --replay-differences` | 3 min |
| C2 | **card log on vs off** (M4): 200 IG games, 8 × 25 one-shot pairs; differences replayed | `L cardlog-onoff --out $OUT/C/c2 --games 200 --replay-differences` | 2 min |
| C3 | **warm equivalence** at a larger size | `F serve-check --games 40` (output in `$OUT/C/c3/`) | 3 min |
| C4 | **deck-order alignment:** CONTRACT-W3.md §3.7 check 2, through V's real writer; 20 games for each of the 2 variants | `L deck-order --out $OUT/C/c4 --games 20 --variants $OUT/inputs/variants.json` | 1 min |

**Fail-fast after C:**
- **MG1 failed** (judged at A1): the run stops at once, cleans up and reports FAIL.
- **MG2-MG5 failed:** the merge can't pass, and a fix will change engine keys, so D1 and every staged item are
  skipped. The controller spends up to 45 min on diagnostics: C1 at 100 Constructed games, C2 at 400, `serve-check
  --games 120`, and the experiments that don't depend on the failed part (into `$OUT/experiments/`, never staging).
  Then E, and FAIL.

### D. The soak: real work (the test server on 8643 is up from D0 to D9)

Every D item has `--logs-dir` (D1 every chunk; arms of experiments with named cards every chunk; everything else every
10th chunk). Periodic items (§7): a soak probe every 15 min of D or every 4,000 games, whichever comes first; a drift
probe every 30-40 min as an exclusive item at an item boundary (preempting a preemptible item); a pool and memory poll
every 5 min.

| Id | Pri | What | Command | Est. |
|---|---|---|---|---|
| D0 | P0 | start the test server | §5.1 | 1 min |
| D1 | P0 | **replay every current matchup into staging** (W2 §16): the main soak load. Preemptible | `F replay --results-dir $OUT/staging/results --matchups 4 --logs-dir $OUT/logs/replay --log-every 1 --json` | 45 min (≈ 26.8k fast, 5.3k board, 1.2k Commander games) |
| D2a | P1 | **M4 pairing** (plan G6, G7, v-r09): (1) CRN coupling: Gruul's 1-card and 2-card variants against Izzet, 800 paired games each (base games from staging); (2) the Fiery pair: with and without `fiery`, Gruul v Izzet, 800; (3) shared against per-pair seeds: IA on IG's stream, base and game numbers, with the flip set so Izzet holds the seat it has in IG's game g (`flip_shared = (flip_IG + side_IG(Izzet) + side_IA(Izzet)) mod 2`, CONTRACT-W3.md §11.3), 800 games, against IA's own per-pair control, 800; (4) the variant workflow end to end: variant 1 against three opponents with field looks | (1) `F variant casual/gruul-ramp --list $OUT/inputs/variant-1.txt --against casual/izzet-prowess --games 800 --results-dir $OUT/staging/results --logs-dir $OUT/logs/crn --json`, and the same with `variant-2.txt`; (2)+(3) `F experiment $OUT/inputs/exp-m4.json --results-dir $OUT/experiments/m4 --control-dir $OUT/staging/results --control-logs-dir $OUT/logs/replay --logs-dir $OUT/logs/m4`; (4) `F variant casual/gruul-ramp --list $OUT/inputs/variant-1.txt --field --opponents casual/izzet-prowess,product/challenger-2019-lightning-aggro,casual/mono-white-angels --until ahead --results-dir $OUT/staging/results --logs-dir $OUT/logs/crn --json` (shrinks to `--games 400`) | 12 min |
| D2b | P1 / P2 | **known-ordering ladders** (plan G2): rungs −2/−4/−6 key copies → lands, each a paired variant test against the reference opponent, 400 games a rung, all on the same game numbers. Izzet, Rabbits, Angels (P1); Gruul, MBM (P2) | `F variant <deck> --list $OUT/inputs/ladders/<deck>-<k>.txt --against <ref> --games 400 --results-dir $OUT/staging/results --logs-dir $OUT/logs/ladders --json` per rung | 6 + 2 min |
| D2c | P1 / P2 | **override experiments** (plan G4, G5): `etb`, `tgt`, `remove`, `flash` (P1); `etb-flagged`, `tgt-gift`, `hints` (P2); 800 games a pair (Commander 400), paired with staging's control and its logs. Local pools (own user folders) | `F experiment $OUT/inputs/exp-overrides.json --results-dir $OUT/experiments/overrides --control-dir $OUT/staging/results --control-logs-dir $OUT/logs/replay --logs-dir $OUT/logs/overrides` | 18 + 7 min |
| D2d | P1 / P2 | **pilot experiments:** TeamPumpAi (P1): RV 800 with Rabbits switched on, the Rabbits mirror (side a switched on) 800 with its control, and Finneas switched on v Giada 400; profiles (P2): mirrors at 800 with controls for Rabbits (Reckless, DLAggro), Gruul (Reckless), Angels (Reckless), Izzet (DLControl), MBM (Cautious), plus Rabbits on Reckless v Vampires 800; the hybrid AI (P2, `exclusive` for its speed part): IG 100 plain against 100 hybrid, then the MBM mirror with side a hybrid at 400 if hybrid costs ≤ 3× | `F experiment $OUT/inputs/exp-pump.json ...` (D2d-p1); `F experiment $OUT/inputs/exp-profiles.json ...` (D2d-p2: each profile arm plays side a of its deck's mirror, and Rabbits' arms also Rabbits v Vampires, so a pilot has a reference pair: 11,200 games with the mirrors' controls); `L hybrid` (D2d-p2h, `exclusive`: exp-hybrid.json with its control played in the item, so both sides of the speed ratio ran under the same load, then exp-hybrid-mirror.json only when hybrid games cost ≤ 3× plain ones) | 11 + 26 + 6 min |
| D2e | P2 / P3 | **pilot sensitivity** (plan G3): every pairing of the Constructed field (10 lists, 45 pairings) at 200 games under (b) every experiment override set (P2), and (c) (b) plus Reckless for Rabbits, on Rabbits' 9 pairings (P3); (a) is staging, plus control games for the pairings staging lacks | `F experiment $OUT/inputs/exp-sensitivity-b.json --games 200 ...` (D2e-b) and `exp-sensitivity-c.json` (D2e-c); prepare-inputs writes them from the Constructed field and the experiment sets (every set not adopted; a set sharing a card script with one already taken, etb-flagged after etb, stays out). A pairing no set changes is skipped (its (b) is its (a)). Dry run against tonight's lists: (b) 7,800 arm games, (c) 1,800, plus the controls staging lacks (at most 9,000 and 1,800) | 25 + 7 min |
| D3a-ref | P1 | **field view, Constructed, the reference** (plan G8): every opponent of Mono-White Angels topped up to 1,600 games (shrinks to 800) in staging, base 1. Preemptible | `F field casual/mono-white-angels --fixed 1600 --results-dir $OUT/staging/results --logs-dir $OUT/logs/field --log-every 10` | 18 min |
| D3a-api | P1 | **field view, Constructed, through the page's path:** an adaptive `standard` field run submitted to the 8643 server's API (`POST /api/field/run`, the first profile it lists), so the server's in-process path, `COORD_JOBS` and its pool are exercised. It plays into the server's own results folder (w3-run's, empty), at base 2 from `DECKLAB_SEED_BASE`, so it's independent of the reference. `exclusive`, so its wall time is the field-run time | `L api-field --port 8643 --deck casual/mono-white-angels --budget standard --out $OUT/D/d3a-api` (polls `GET /api/field` until done; records wall time and the view) | 8 min |
| D3b | P2 | **field view, Commander:** Giada against the Commander field (3 lists today); reference `--fixed 800` in staging; then an adaptive `standard` run through the API, as D3a-api | as D3a with `commander/giada-angels` | 8 min |
| D3c | P1 | **adaptive savings** (B8 of revision 1): games used for assess and ahead on AL, IG and ZL against the fixed counts, and the verdicts against the staged references (MG13). Wall time from the measured rates | `L adaptive --out $OUT/D/d3c --pairs AL,IG,ZL --modes assess,ahead --seed-base 3 --logs-dir $OUT/logs/adaptive` (shrinks by dropping ZL-ahead) | 9 min |
| D4a | P2 | **M6** (`overnight_pods.py`): 200 4-player Commander pods of the three house decks and the Wretched Ranks precon, plus a compare series of 100 pods with Giada Angels and its precon, Calling All Angels, in the same pods (with Finneas and Gisa). Plain Forge `-jar` cold, batches of 5 pods, at most 12 processes, each in a slot of the PC's budget; the seat order rotates one place each batch; a batch that ends without a game is played once more. Minutes per pod, AI timeouts, clock stops, win rate by seat and by deck with 95 % ranges (statistics only: 4-player pods don't replay exactly), and the upgraded deck against its precon. Gate M6 is optional: reported, never FAIL, never holds up PASS | `L m6 --out $OUT/D/m6 --pods 200 --decks commander/giada-angels,commander/finneas-rabbits,commander/gisa-zombies,product/fdc-wretched-ranks --compare commander/giada-angels,product/fdc-calling-all-angels,commander/finneas-rabbits,commander/gisa-zombies --compare-pods 100 --per-batch 5 --procs 12` | 45 min |
| D4b | P3 | **M7:** a round robin of the prepared external decks at 400 games a pair (21 pairs, game 1 only, in a pool of its own); Spearman of Forge's Bradley-Terry ratings against the human ones, and how often the favourite agrees. Never a gate: its section of REPORT.md says what it found | `L m7 --out $OUT/D/m7 --inputs $OUT/inputs/m7 --games 400 --max-min 45` (skipped without inputs; no new pair after 45 min, inside the runner's 2 x est_min cut) | 30 min |
| D-fill | P0 | **filler** to reach the soak minimum (§5.5), as needed. Preemptible | over a copy of A3's v1 snapshot in `$OUT/D/filler/results`: `F replay --results-dir $OUT/D/filler/results --matchups 4 --logs-dir $OUT/logs/filler --log-every 10`, with `DECKLAB_SEED_BASE=5` in the child's environment (W2's `replay` has no seed option; the CLI plans its own seeds, so the variable applies) | as needed |
| D8 | P0 | **the final soak probe** (E1 of revision 1), while the test server's warm pool is still up: it tops up the Commander quota (150) and the Constructed count (≥ 300) | `F soak-probe --server-port 8643 --results-dir $OUT/staging/results --logs-dir $OUT/logs --constructed 35 --commander <the rest of the quota> --out $OUT/probes/final.json` | 6 min |
| D9 | P0 | stop the test server | §5.1 | 1 min |
| D10 | P1 | **the idle close, the idle footprint and re-warm** (plan G15): a second test server on 8644 (`--no-update`, `forge_pool_idle_s` 120 through `DECKLAB_CONFIG_EXTRA`); IG 200 to warm it; then 150 s with nothing to play, recording `java_n`, working set and idle CPU every second; the workers must quit by 120 + 30 s; then a timed IG 200 re-warm. The mechanism is the same at 900 s; 120 s keeps the leg short. `exclusive`, after D9 so no other pool holds slots | `L idle-close --port 8644 --idle-s 120 --out $OUT/D/d10` | 6 min |

### E. The end (P0, 15 min)

| Id | What | Command |
|---|---|---|
| E1 | the replay is complete | `F replay --results-dir $OUT/staging/results --dry-run --json` (expect 0 matchups missing) |
| E2 | the staged results are valid | `F staged-move --from $OUT/staging/results --dry-run --json`, from w3-run (the code under test); the real move happens in the morning from main (§10) |
| E3 | offline checks (CPU only) | `L offline --out $OUT/E/e3`: (1) the v3 "in hand by turn 3" numbers (`early_games`, `early_wins`) recomputed from D1's tee'd logs for every replayed result and compared with the saved card records (plan G18); (2) recycles because an AI evaluation thread was still alive after a game (`Signals.LIVE_EVALS`, DeckLabServe's recycle reason) and AI-timeout games, per 1,000 games (v-r07); (3) the card data unchanged since A1 |
| E4 | cleanup | §5.4 |
| E5 | the report | `overnight.py report --out $OUT` → `REPORT.md`, `report.json` and `rates.json` |

## 7. Soak checks during D

### 7.1 Fresh against warm (`soak-probe`; H)

1. **Sample games** from **all** chunk logs tee'd so far by server-pool items (D1, D2a, D2b, D3, filler), not only those
   since the last probe. Games not probed before, spread across matchups, workers and time, with half from the last
   15 min.
   - Constructed: 35 per probe.
   - Commander: a quota of 150 over the run, from D1's Commander logs (about 1,200 games) and D3b's, spread over the
     probes as the logs allow; the final probe (D8) takes what's left.
2. **Play each one fresh:** a one-shot DeckLabSim v2 request with the chunk's exact arguments (decks in that chunk's
   seat order, `-n 1`, first = g, the same base, stream, pilots, user folder and jar). Four at once, each in a slot.
3. **Compare:**
   - Constructed: line for line with W2's masks (timings, the ordinal, stack frames, `WARNING:` lines and attacker
     order), with DL| lines kept;
   - Commander: by **outcome**, which is (winner, starter, turns, result).
4. **A Constructed difference** is played again warm, alone: `runner.run(..., numbers=[g], seeds=<the result's>,
   key=<a scratch key>, kind="experiment", results_dir=$OUT/probes/warm, log_dir=...)` on the 8643 server's pool.
   - When the warm copy equals the fresh one, the difference didn't come back: **unsure** (the identity-hash residual,
     W2 §4).
   - When it differs again: **failed**.
   - `soak-probe` refuses (exit 1, "no live server pool on port 8643") when that server isn't up; it never falls back
     to a local pool, which would turn a real warm-state difference into "unsure".
5. **Commander baseline:** each sampled Commander game is played fresh a second time (fresh2), for the paired
   fresh-against-fresh comparison of MG7.

Probes are suspended during exclusive items. **Output:** `$OUT/probes/<n>.json`, with each game's verdict and the
diff's first lines.

### 7.2 Drift (exclusive probes between items)

- Every 30-40 min of D, at the next item boundary (or by preempting a preemptible item), the controller runs
  `L drift-probe --port 8643 --out $OUT/probes/drift-<n> --seed-base 7` **alone**: IG 100 untimed to bring the pool to
  16 warm workers, then IG 200 timed, into a fresh scratch result, so every probe plays the same games. About 1.5 min.
- It records the median Forge ms per game and the wall time. Because nothing else runs, probes compare like with like
  (e3 measured 25-40 % swings in ms per game with load).
- Noisy probes (§5.2) are dropped. MG11 needs at least 4 clean probes spanning 2 h.

### 7.3 Memory and the pool

- `F pool --json` every 5 min: the test server's workers, their games and their latest heap_mb, into `mem.csv`.
- `cpu.csv` holds `java_n` and `java_ws_mb` every second.
- The report gives:
  - the 10-s smoothed peak and 99th percentile of the total working set in D, and the instantaneous peak;
  - the per-worker heap_mb against the games each worker has played;
  - recycles by reason (from the run records and the pool's status);
  - K = 24 and 32 memory from B5, as numbers only.

### 7.4 Recycles, time limits and failures

From the staged run records (`recycled`, `requeued`, `failed`) and the games (`r == "timeout"`, `ai_to`), per matchup.
Matchups with v1 results are set against their v1 rates (MG9).

## 8. Outputs and the final report

`REPORT.md` (and `report.json`, the same numbers), in this order:
1. **The verdict:** PASS, FAIL or INCOMPLETE for the merge, with every gate (§9.1), its number and "not checked"
   reasons; then the staged move's readiness (§9.2), with any matchups held back.
2. **What ran:** the items, done, cut, noisy or dropped (and why); sessions; active time, paused time, soak time, and
   the deadline; sleep gaps; foreign processes seen.
3. **Timing:**
   - one table: each B leg's games a minute, ms per game, start-up, CPU (own, system, other), memory, AI timeouts,
     against B1 (wave 1 main, the mean of B1a and B1b) and B2 (default);
   - the cold (round 0) against warm ratio;
   - pinning: none, core and CCD, idle and under load (B9);
   - K = 16/20/24/32;
   - PERFORMANCE_MODE, Constructed and Commander, warm and round 0;
   - R14a, R04 and game patches;
   - the server path, and EcoQoS on each JVM.
4. **Determinism:** the identical-game shares across B legs (MG6), with Commander's same-outcome share beside the
   fresh-against-fresh baseline.
5. **v2 checks:** C1-C4, with any unsure games.
6. **Soak:** the probes (compared, unsure, failed; the Commander paired test), drift, memory, recycles and time
   limits, and the idle close (D10).
7. **Replay:** matchups and games planned and played, failed chunks, the time per matchup class, the staged results'
   validity, and v2 against v1 per matchup (MG15).
8. **Adaptive savings** (D3c): games and minutes against the fixed counts, and the verdicts against the references.
9. **Field view** (D3): wall time, games used, the adaptive rows against the reference rows (per-opponent z, sides of
   50, Spearman of the rows), the residual flags, the rating and its rank range.
10. **M4 pairing** (D2a):
    - the correlation ρ and `same` for the 1-card and 2-card variants;
    - the paired range against the unpaired one ("pairing saved X % of games");
    - the Fiery pair's identical share and its card and matchup numbers;
    - shared against per-pair seeds: ρ̂ for each, with a Fisher-z 95 % range, and for a field of k = 9 the implied
      inflation, "variance × (1 + (k − 1)ρ), SE × sqrt(1 + (k − 1)ρ)";
    - the three-opponent variant test (D2a(4)): its looks and outcome.
11. **Experiments** (D2b-D2e), each with its recommendation (§9.3):
    - ladders: the paired slope per rung and its range, and any clear reversal;
    - per override set and per card: cast %, cast turn, win when in hand early and when drawn, own permanents lost,
      the matchup Δ (paired, per pair and pooled), and AI timeouts;
    - pilots: the mirror win rates, the reference pairs, and speed;
    - pilot sensitivity: the ratings' Spearman, the pairings whose paired difference is a BH-10 % discovery, and each
      deck's rating spread.
12. **Offline checks** (E3): the v3 early numbers against the logs; live-eval recycles and AI timeouts.
13. **Optional:** M6 and M7, when they ran.
14. **Cleanup:** leftovers, slots, servers, the monitor.
15. **Next steps,** worked out from the above: merge or not, move or not (and the held matchups), the adoptions to
    consider with the targeted replay each would need (CONTRACT-W3.md §0.3), and the rates to copy for Deck Lab's
    estimator.

## 9. PASS and FAIL

### 9.1 Merging `sim-w3` into main

**The outcome:**
- **FAIL** when any gate that ran fails.
- **INCOMPLETE** when no gate failed, and a P0 item didn't run or didn't finish (the deadline, a reboot, the PC never
  idle), or a gate that needs only P0 items is "not checked" (noisy twice, too few probes, the soak minimum not met in
  one session). Resume another night (§10).
- **PASS** when every gate that needs only P0 items passes. Gates that need dropped P1/P2 items are "not checked", with
  a note: MG13, MG16, B3's part of MG14, and the B3-B9 parts of MG6. They're new features off the default path's
  correctness, or extra measurements.

**The replay rule** (W2 §4's identity-hash residual), used by MG2, MG3, MG6 and MG7: a Constructed difference is
played again (fresh, in each of the two configurations compared). A difference that doesn't come back is **unsure**;
only one that comes back **fails**.

| Gate | Pass when |
|---|---|
| MG1 Preflight | A1's checks: the card log ready and checked for this commit and Forge build; the adopted sets deployed and none stale; `pilots --check` clean; main merged into HEAD; the database's decks can be read (`deck_lists` recorded; since phase 5a this replaced the check that the deck lists equal main's) |
| MG2 Parity (C1) | the 20 Constructed games are identical (W2 masks) under the replay rule, with at most 1 unsure; the 5 Commander games have the same outcome, or the difference doesn't come back |
| MG3 Card log on/off (C2) | the 200 games are identical under the replay rule, with at most 2 unsure |
| MG4 Warm check (C3) | `serve-check` says nothing, or "unsure" (never "failed") |
| MG5 Deck order (C4) | both variants are aligned in 20 of 20 games, with the same starters |
| MG6 Determinism (B) | across legs with the same engine and seeds (B2's rounds, B3, B4, B5, B7's R14a and R04 legs, B9): Constructed ≥ 99.5 % identical (winner, starter, rounds, turns, result), and every difference either in a game with a clock stop or AI timeout, or unsure under the replay rule. Commander: reported only (the same-outcome share beside the fresh-against-fresh baseline); MG7 gates it |
| MG7 Soak (§7.1) | **Constructed:** ≥ 300 games probed in ≥ 10 probes over ≥ 2.5 h of one session's D: 0 failed and ≤ 2 % unsure. **Commander:** ≥ 150 games; per game g, a_g = 1[warm ≠ fresh1] and b_g = 1[fresh2 ≠ fresh1] (outcomes); the paired range for mean(a − b) by Agresti-Min (b = games with a=1, b=0; c = games with a=0, b=1; n' = n + 2; Var = ((b' + c') − (b' − c')²/n')/n'², with b' = b + 0.5, c' = c + 0.5). FAIL only when the range's low end is > 0 **and** the point estimate is > 0.05 |
| MG8 Replay (E1, E2) | 0 matchups missing games; failed chunks ≤ 0.5 % of the replayed games and ≤ 2 % in any matchup; no run ended with an error; every staged v2 file passes `_is_result`, shows with `views.view`, and works out to its own key |
| MG9 Recycles and limits | over all replayed games: crash recycles ≤ 1 per 10,000 games; games with an AI timeout ≤ 1.0 per 1,000; clock stops ≤ 0.5 per 1,000. **The AI-timeout rate against v1, per matchup** with v1 games (m matchups tested): x1 of n1 v1 games and x2 of n2 v2 games had one; t = x1 + x2. Given t, X2 ~ Bin(t, θ) with θ = n2·r/(n2·r + n1) at rate ratio r. Take the one-sided Clopper-Pearson lower bound θ_L at level 1 − 0.05/m, and r_L = θ_L/(1 − θ_L) · n1/n2. A matchup fails only when r_L > 3 **and** x2 ≥ 3. The same test on the pooled totals at level 0.95 fails when r_L > 3. (v1 had about 0.3 AI-timeout games per 1,000, but Rabbits v Vampires 4.4.) Per-matchup rates are listed in the report, not gated |
| MG10 Memory | in one session's D at the default K = 16: the 10-s smoothed 99th percentile of the total java working set ≤ 24 GB (the instantaneous peak is reported, not gated); recycles at the heap limit ≤ 1 per 5,000 games; each worker's median heap_mb in D's last hour ≤ 1.2 × its first hour's. B5's K = 24 and 32 memory are numbers only |
| MG11 Drift | ≥ 4 clean drift probes spanning ≥ 2 h of one session: the last one's median ms per game ≤ 1.10 × the first's, and no rise of ≥ 10 % held over 3 or more probes in a row |
| MG12 Clean | at the end, after the monitor stops: 0 run-owned java.exe, 0 slots held by the run, the test servers stopped, no run-owned process alive except the controller |
| MG13 Function | D3c's runs each ended with a verdict, and none says "ahead" for the side opposite to its pair's staged reference when that reference's range excludes 50 % by more than 5 points. D2a's, D3a's and D10's runs finished without errors. **D3a, adaptive against reference:** the Spearman of the two rows (each opponent's balanced rate in the adaptive run against the reference's) is ≥ 0.8; and no opponent has \|v_ad − v_ref\| / sqrt(SE_ad² + SE_ref²) > 2.77 (Bonferroni over 9 opponents at a 5 % family rate; the samples are independent, base 2 against base 1), or both 95 % ranges excluding 50 % on opposite sides |
| MG14 Speed (no regressions) | with B1 = the mean of B1a and B1b: warm IG800 (the mean of B2's rounds 1-2) ≥ 1.25 × B1's IG800 games a minute; warm RV400 (rounds 1-2) ≥ 1.0 × B1's; warm GF200 (rounds 1-2) ≥ 0.9 × B1's (two readings each); cold IG800 (B2 round 0) ≥ 0.9 × B1's; B3's IG800 ≥ 0.95 × B2's warm IG800; EcoQoS off on every JVM in B3. A noisy leg makes its part "not checked" |
| MG15 v2 against v1 (E1, E2) | catches side, seat and flip bugs in saving, which the other gates can't see. Over the replayed matchups (m of them): (1) **starter share:** each matchup's share of games started by side 0 has \|z\| ≤ Φ⁻¹(1 − 0.025/m) against 50 % (per-game coin flips); (2) **win rates:** for each matchup with ≥ 400 v1 games whose lists hold no adopted override's card, the balanced rates agree: \|v2 − v1\| / sqrt(SE1² + SE2²) ≤ 4.5 (wide on purpose: wave 2's small game-changing parts, R14b and PERFORMANCE_MODE, may move a matchup a little); matchups holding an adopted override's card (Gruul Ramp's, with Fiery) are reported only; (3) **no swap:** no matchup, reported ones included, whose v1 and v2 95 % ranges both exclude 50 % on opposite sides |
| MG16 Idle close (D10) | the workers quit within idle_s + 30 s; no JVM of that server is left; the re-warm completes. The idle footprint and the re-warm time are reported. "Not checked" when D10 was dropped |

### 9.2 Moving the staged results into the real folder

All of these must hold:
1. **The merge passed** (§9.1), with MG8 and MG15 passed.
2. **Nothing changed the engine since the run.** At move time, in the merged main checkout,
   `F staged-move --from $OUT/staging/results --dry-run` reports 0 **stale** files. It calls `ensure_deployed` first,
   so main's user folder holds the adopted sets before keys are worked out. Each stale file names the description
   field that differs. So since the run there must have been no adoption, no pilot change, no Forge upgrade or rebuild,
   and no change to `CHECKED_SOURCE` or `simulation.json`.
   - Stale files aren't moved; `replay` plays them again later.
3. **No conflicts.** A real v2 file with the same key isn't overwritten: the staged file is skipped and listed. There
   should be none, because main has played no v2 games before the merge.
4. **The background server is stopped** while moving (§10).

What moves:
- **Moved:** the staged v2 matchup results (top level, no `kind`) and `field/` notes.
- **Held:** nothing, unless the report lists matchups for the owner to look at; `--hold $OUT/held.txt` leaves them.
- **Never moved:**
  - the v1 copies (the real v1 files stay as they are);
  - `paired/` (the harness's own variant tests);
  - files of `kind: "experiment"`, `$OUT/experiments/`, `$OUT/probes/`, `$OUT/D/filler/`;
  - the API field runs' results (they're in w3-run's own results folder, not staging).

### 9.3 Experiment recommendations (evidence, not a gate)

- **The rules** are CONTRACT-W3.md §12.4's: "adopt", "don't adopt" or "more games" (Bonferroni per pair,
  non-inferiority at −0.03, paired measures).
- **Ladders** (all rungs of a ladder share the same game numbers):
  - per game g and rung k ∈ {2, 4, 6}, d_k,g = y_k,g − y_full,g; the per-game least-squares slope
    s_g = Σ k·d_k,g / Σ k²; the slope is the stratum-balanced mean of s_g, and its SE comes from the s_g's spread
    (games are independent);
  - a ladder **passes** when the slope's 95 % high end is < 0;
  - it's **non-monotone** only when a step reverses clearly: for adjacent rungs, e_g = y_k+2,g − y_k,g has a mean with
    z > 2 (removing more key cards wins more);
  - the −4 and −6 rungs' paired ranges against the full deck (high < 0) are reported.
- **Pilot sensitivity:**
  - "rankings hold" when the Spearman of the Bradley-Terry ratings between (a) and (b) is ≥ 0.9;
  - a **flip** is a pairing whose paired arm-minus-control difference (by g) is a BH-10 % discovery among the 45
    pairings; the report lists them;
  - otherwise, or with flips, the report recommends showing bands (plan G3).
- **Adoption is the owner's.** It then needs a targeted replay (CONTRACT-W3.md §0.3): the report lists, for each
  candidate, the matchups it would re-key and the estimated idle minutes.

## 10. The morning after

1. `overnight.py status --out $OUT`, then read `$OUT/REPORT.md`: the verdict is at the top. The run has already
   restarted the 8642 server if it was running.
2. **PASS:**
   ```powershell
   python -m decklab.lib.homenet stop                         # if the 8642 server is running
   git -C C:/VSProjects/TradingCardCollection merge --no-ff sim-w3
   cd C:/VSProjects/TradingCardCollection
   python -m unittest discover -s decklab/tests -t .
   python -m decklab.lib.forge cardlog-check                  # main's own data folder needs its own check record
   python -m decklab.lib.forge overrides deploy               # primes main's user folder (staged-move does it too)
   python -m decklab.lib.forge status                         # card log ready, the adopted sets deployed
   $STAGED = "C:/VSProjects/TCC-wt/w3-run/decklab/data/forge/overnight/$NIGHT/staging/results"
   python -m decklab.lib.forge staged-move --from $STAGED --hold "$STAGED/../../held.txt" --dry-run
   python -m decklab.lib.forge staged-move --from $STAGED --hold "$STAGED/../../held.txt"
   python decklab/forge-trial/overnight.py report --out "C:/VSProjects/TCC-wt/w3-run/decklab/data/forge/overnight/$NIGHT" --write-rates C:/VSProjects/TradingCardCollection/decklab/data/forge/rates.json
   python -m decklab.lib.homenet start                        # only if it was running before
   ```
   - If the dry run reports stale files, it names the field that differs. The usual causes are an adoption or a
     `simulation.json` change since the run, or a card log that isn't ready. Fix the cause or let `replay` play them
     later; don't force them.
   - The merge commit is the only commit: results are data, and gitignored. Keep `$OUT` until the moved results have
     been looked at on the page.
3. **FAIL:** don't merge.
   - The report names the failing gates and points at their evidence (probe diffs, logs).
   - Fix the cause on `sim-w3`.
   - When the fix can't change what other items measured, re-run only what's needed:
     `overnight.py supervise --out <new> --only <items>` (for example `C1,D1,E`).
   - Otherwise, a full P0 run on another night.
4. **INCOMPLETE:** `overnight.py supervise --out $OUT --resume --budget-h H --deadline HH:MM` in the next idle window.
   It runs only what's missing, in a new session (§5.3).
5. **Adoption (after a PASS and the move):**
   - Decide from §8 item 11.
   - Edit `decklab/lib/forge/overrides/sets.json` (`status: adopted`) and `decklab/simulation.json` (pilots), and
     commit.
   - In an idle window: `python -m decklab.lib.forge replay`. It plays only the re-keyed matchups.

## 11. Budget and idle hours

| Block | Active minutes (estimate) | Priority |
|---|---|---|
| A Preflight | 10 | P0 |
| B Timing battery | 70 (P0 23: B0, B1a, B2, B1b; P1 27: B3, B4-none, B5-K24, B6, B7-R14a, B9; P2 20: B4-ccd, B5-K20, B5-K32, B7-R04, B7-off) | P0-P2 |
| C v2 checks | 12 | P0 |
| D0, D8, D9 (server, final probe) | 8 | P0 |
| D1 Replay into staging | 45 | P0 |
| Drift probes (about 6) | 9 | P0 |
| D2a M4 pairing | 12 | P1 |
| D2b Ladders | 6 + 2 | P1, P2 |
| D2c Override experiments (controls included) | 18 + 7 | P1, P2 |
| D2d Pilot experiments (controls included) | 11 + 26 + 6 | P1, P2 |
| D2e Pilot sensitivity (controls included) | 25 + 7 | P2, P3 |
| D3a-ref, D3a-api, D3c | 18 + 8 + 9 | P1 |
| D3b Commander field | 8 | P2 |
| Filler to reach the 3 h soak | 0-120 (none when P2 runs; about 40 min with P0+P1; about 2 h with P0 alone) | P0 |
| D4 M6 and M7 (optional) | 45 + 20 | P2 (M6), P3 (M7) |
| D10 Idle close | 6 | P1 |
| E The end | 15 | P0 |
| Overheads (worker start-ups per launch identity, idle checks, stage tails, about 10 %) | 15-30 | — |
| **Total** | **≈ 5.8 h for P0-P2** (P0 + P1 ≈ 5.0 h; P0 alone ≈ 4.3 h, most of it the soak); P3 adds about 40 min if time remains | |

- **Target:** ≤ 6 h of active idle PC, in one night (for example from 22:30, with the deadline at 07:00), plus the
  start wait and any pauses.
- A PASS needs at least the P0 items, about 4.3 h, because the soak gates need 3 h of D (owner question 3,
  CONTRACT-W3.md §0.6). A shorter night ends INCOMPLETE.
- When the night is shorter than the plan, the budget control drops P3, then P2, then shrinks P1 (§5.5).
- **After the adoption decision:** one more, shorter idle window for the targeted replay (estimate 10-40 min).

## 12. Review fixes (revision 2): the runbook

The statistics review's runbook items (S-) and the runbook review (B-). "Must" and "should" items are all fixed; nits
are fixed. The findings quote revision 1's gate names: G1-G14 are now MG1-MG14. CONTRACT-W3.md §23 maps the
contract's items.

| Finding | Fix |
|---|---|
| B-must: E1 (the last soak probe) ran after D9 stopped the server | D8 is the final probe, before D9; `soak-probe` refuses without a live server pool (§7.1) |
| B-must: the soak gates need hours of D, but D shrinks with drops; G7's numbers; Commander quota; items without logs | the 3 h soak minimum is P0, with filler (§5.5); probes by time or games, sampling all logs so far, 35 Constructed a probe, a 150-game Commander quota from D1's logs (§7.1); every D item has `--logs-dir`; §11 corrected |
| B-must: the reserve counted only P0, so P2 legs could push out P1 items | the up-front decision and `reserve(p)` over every higher-priority item (§5.5) |
| B-must: cleanup killed JVMs by command line | only run-owned processes (job membership, recorded pid and creation time); foreign ones reported (§5.4); the smoke drill checks it |
| B-must: G10's 24 GB had no scope | MG10: D at K = 16, the 10-s smoothed p99; K = 24/32 numbers only |
| B-must: test servers without `--no-update` | every test server, the smoke run included (§2, §5.1); A1 and E3 check the card data didn't change |
| B-must: the owner stopped 8642 by hand, so it was never restarted | A1 records and stops it; E4 restarts it; the manual step is gone (§4, §6 A1) |
| B-must: `--resume` inherited the old deadline and didn't re-check identity | new session with its own `--deadline` and `--budget-h`; identity checks; B re-anchored per session; soak gates per session (§5.3) |
| B-must: no gate compared v2 with v1 | MG15: starter share, win rates at 4.5 SE with adopted-override lists reported only, and the swap check |
| B-should: no "unsure" escape in G2, G3, G6; Commander sample sizes and baselines | the replay rule for MG2, MG3, MG6, MG7; MG6's Commander part reported against the baseline; MG7's paired test on 150 games |
| B-should: idle detection | `GetLastInputInfo`; own = the run's job; a "system" class for Defender and maintenance; strict noisy rule for timing legs; noisy / not checked / INCOMPLETE spelled out; the maintenance window and the optional Defender exclusion in §4 |
| B-should: sleep, and the sampler ending early | `SetThreadExecutionState`; sleep gaps flagged; the monitor runs to the deadline and is restarted if it stops (§5.1, §5.2) |
| B-should: drift probes under changing load | exclusive drift probes between items, with a short warm-up (§7.2) |
| B-should: estimates leave out control games | `prepare` counts them through `experiment --dry-run`, and estimates matchups from their own v1 speed (§3) |
| B-should: §7 questions with no block | B9 (pinning under load), D10 (idle close, footprint, re-warm), GF in B6, E3 (LIVE_EVALS recycles, v3 early numbers against logs), D2a(4) (three opponents with field looks), D3a-api (the page's in-process path) |
| B-should: fail-fast | §6 C: stop on MG1; skip D1 and staged items on MG2-MG5, diagnostics, then FAIL |
| B-should: speed gates on single readings; B1 always first | A-B-B-A with a warm-up; two readings for GF; Commander floor 0.9; B3's server path and EcoQoS in MG14 |
| B-should: controller robustness | the supervisor (at most two restarts); `TerminateJobObject` for forced stops; the smoke drill (§3, §5.1) |
| B-should: daylight saving on 2026-10-04 | absolute deadline from the OS's local-time rules, monotonic intervals, and a note (§4, §5.3) |
| B-should: the morning move and A1 | `overrides deploy` and `status` before the dry run; `staged-move` calls `ensure_deployed`; A1 checks main's and w3-run's `magic/` (§6 A1, §10) |
| B-nit: B2 rounds and §11's split | rounds 0 (fresh), 1-2 (warm) everywhere; §11 recomputed |
| B-nit: sampler alive at G12; slots and pool files at A1; log deletion; B1's card log | §5.4 E4 order; A1 checks; deletion limited to w3-run; B1 records main's card-log state |
| S-must: G9 | MG9's rate-ratio test |
| S-should: G7's Commander part; G13 | MG7's paired Agresti-Min; MG13's rows and per-opponent z |
| S-should: D2a(3) | 800 games, Izzet's seat matched by the flip formula, a Fisher-z range, both inflations (§6 D2a, §8 item 10) |
| S-should: ladders and pilot-sensitivity flips | per-game paired slope; reversals at z > 2; flips as BH-10 % discoveries (§9.3) |
| S-nit: drift-probe confounding | §7.2 |
| U-should: Fiery adopted before the run | owner question 1 in CONTRACT-W3.md §0.6; A1, MG1 and D2a(2) check "the adopted sets", so the run works either way |
