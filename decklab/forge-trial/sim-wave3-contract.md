# Deck Lab simulations, wave 3: the contract

**Date:** 2026-10-03. **Status:** design for building on top of wave 2. **Revision 2:** the statistics, systems/UX and
runbook reviews are folded in; §23 says where each finding went. **Revision 3 (the base, 2026-10-03):** §2 re-checked
against `sim-w2` at `c82e714` (its re-check passed with no must-level problem; wave 2's docs commit 907444a merged in
after); §2.1 lists what differs and where this
contract changed; the frozen names the base commits are in §7.8, §8, §10.5, §11.5 and §16; this build's merge plan is
in §21.
**Base:** branch `sim-w3-base`. The wave 3 integrator cuts it from the integrated wave 2 branch (`sim-w2`), after
wave 2's step 7 and before any merge to main, and commits a copy of this file there as
`decklab/forge-trial/sim-wave3-contract.md`; code comments point at it. Package worktrees are
`C:/VSProjects/TCC-wt/w3-<package>`, and the integration worktree is `C:/VSProjects/TCC-wt/w3-int` (branch `sim-w3`).
The combined run's runbook and harness design are in `COMBINED-RUN.md` beside this file. **In the repo** this file is
`decklab/forge-trial/sim-wave3-contract.md` and `COMBINED-RUN.md` is `decklab/forge-trial/sim-combined-run.md`; the
scratchpad copies (`.../scratchpad/w3/CONTRACT-W3.md` and `COMBINED-RUN.md`) are kept identical to them.

**What wave 3 builds** (`decklab/forge-trial/sim-investigation.md` §3-§4):
- R12: adaptive stopping;
- R13: the field view;
- R15: paired deck-vs-variant tests;
- R10: card-script overrides, with Fiery Annihilation adopted (the owner's decision, §0.6);
- R16's mechanisms: per-list pilots; TeamPumpAi, the hybrid AI and hint overrides as experiment toggles; an
  experiment harness;
- the combined-run harness (item 7).

R17 is decided and not built (§13).

**Owner decisions (final, 2026-10-03):**
- Build in waves. Wave 2's own measurement is skipped, and wave 3 is built straight on `sim-w2`.
- One combined, unattended idle-PC run (overnight, ≤ ~6 h) measures waves 2 and 3 together (COMBINED-RUN.md).
- Main stays on wave 1 until that run passes. Replayed results go to a staging folder, and move to the real folder
  only after the checks pass.
- AI overrides and pilots are adopted afterwards, from the experiment data.
  - **One exception, adopted by the owner (§0.6 question 1, final):** Fiery Annihilation's override ships `adopted`,
    because the plan's R10 says to adopt it now. It's the one override already measured (cast for 0 % → 92 % of drawn
    copies), and it's the only list-level change before the run.
  - If the owner says no, the integrator sets its status to `experiment` in `overrides/sets.json` before cutting the
    base. Nothing else in this contract changes: the harness checks "the adopted sets", and D2a(2) still measures the
    pair.
  - Rolling it back later costs a targeted replay of Gruul Ramp's matchups (the only list that holds it): today about 3
    current results and 7,000 games (estimate), about 5-6 min of idle PC.
- From wave 2:
  - the warm pool is the server's, and closes after 15 min idle; the CLI submits to it;
  - Forge runs at BELOW_NORMAL;
  - "about even" means within ±5 points;
  - field averages weight opponents equally;
  - games are best of one (no sideboard simulation).

**Nine packages:**

| Package | Builds |
|---|---|
| **S** | sequential statistics |
| **J3** | Java: deck order, pilots, TeamPumpAi, start-up hooks |
| **E3** | engine id v2, pilots and overrides (Python) |
| **R** | run-loop hooks |
| **A** | adaptive runs (R12) and the time estimator |
| **F** | field view (R13) |
| **V** | paired variant tests (R15) |
| **X** | experiment harness (R16) |
| **H** | the combined-run harness |

Ownership is in §20 and the merge order in §21.

---

## 0. Read first: findings that change the plan

### 0.1 Forge ignores a .dck file's line order, so R15 needs a game patch

r5 (§3d item 3) and the report (R15) assume that Forge builds the library from the .dck lines in order before
shuffling. Writing a variant's .dck in the base's order would then keep every unchanged card in its library
position. Forge 2.0.15 doesn't work that way:
- **The library order is hash order.**
  - A deck section is a `CardPool`, which is an `ItemPool` backed by a `ConcurrentHashMap` (`forge-core
    ItemPool.java:42-44`, `CardPool.java:43-45`, `CardPool.fromCardList` at `:415`).
  - `Match.preparePlayerZone` (`forge-game Match.java:200-218`) builds the library by iterating that map. Then
    `Player.shuffle` runs `Collections.shuffle(list, MyRandom)` (`Player.java:1612-1618`).
  - So the order before the shuffle is the map's hash order of the `PaperCard` keys. `PaperCard.hashCode` hashes the
    name, edition, collector number, art, foil and flags.
  - A new card name goes in at its own hash bucket. Every card between that bucket and the removed card's bucket moves
    one place, and each group boundary that moves changes the card in that position.
  - Estimate: with about 22 distinct names, a 1-card swap changes 15-20 % of positions. The chance that none of the
    ~14 cards seen is a changed one is then a few percent, not r5's 75-78 %.
- **Loading decks draws random numbers.**
  - `CardPool.add` splits the copies of a card with several arts into random art groups, with one `MyRandom.nextInt`
    per copy (`CardPool.java:136-150`, `MyRandom.splitIntoRandomGroups` at `MyRandom.java:66-73`).
  - Wave 2 loads decks after the game's reseed (W2 §4 step 4).
  - So a variant that changes how many copies it holds of a card with several arts (usually basic lands) shifts
    every later random number of the game, and the two arms lose all coupling.

**The fix, built in wave 3 by J3:** game patch `deck-order-1` (§3.2).
- A copy of `forge.game.Match`, whose `preparePlayerZone` builds the library in the request's .dck line order (from
  `decklab.DeckOrder`).
- A separate load seed, so loading the decks draws from a stream of its own.
- It is on for every v2 game while game patches are on and the copy is in the jar, so there's one engine, and the base
  arm of a paired test can reuse the base matchup's saved games.
- With game patches off it runs Forge's own code, so parity with plain Forge is unchanged.
- **When a Forge build no longer fits** (its `Match.class` changed), the copy drops out of the jar like any game patch
  (W2 §19). `deck-order-1` then leaves the engine's `game_patches`, the load seed goes with it, the echo checks expect
  neither (§4.4), and play goes on. Only paired tests refuse to start (§11.4) until J3's copy is made again.
- It is statistically neutral: the library is shuffled uniformly either way.
- The combined run measures how much coupling it gives (COMBINED-RUN.md D2a).

### 0.2 Card-script overrides are keyed per list, not globally

- Wave 2's engine id records one `overrides` hash of everything deployed. Adopting any override set later would then
  re-key every result and need a full replay (about 45-60 min of idle PC).
- Wave 3 keys a matchup by the deployed override files whose card is in either list (§4.2), and a side by those in its
  own list. Adopting `tgt` later then re-keys only the lists that hold Stroke of Midnight or Generous Gift.
- The global hash still guards the workers, through the launch identity and the DLENGINE echo (§6.5).

### 0.3 Each adoption after the combined run needs a targeted replay

- Every adoption changes some keys:
  - an override set re-keys the matchups of the lists that hold its cards;
  - a pilot re-keys one list's matchups.
- Those results become "Earlier engine" (W2 §13) until they're replayed. `replay` already plays only what's missing,
  so the adoption decision is followed by a second, shorter idle window (estimate 10-40 min, depending on what's
  adopted).
- So batch adoptions into one decision.

### 0.4 R17: wait for Forge 2.0.16 (see §13).

### 0.5 Built now, and what stays off

| Item | Built now, on by default | Built, off until adopted | Experiment-only |
|---|---|---|---|
| R12 | "assess" and "who's ahead?" runs; the anytime-valid live range (§7.6); fixed counts kept | | |
| R13 | field view, field runs, Bradley-Terry rating, residual flags | | equal-weight per-card pooling over field opponents (not built, §7.7) |
| R15 | `deck-order-1`, the aligned writer, paired runs and analysis, the editor's "Test" | | |
| R10 | the override machinery (mirror, `ensure_deployed`, hash, upstream check); Fiery Annihilation (set `fiery`), adopted (§0.6) | | sets `etb`, `etb-flagged`, `tgt`, `tgt-gift`, `remove`, `flash`, `hints` |
| R16 | the `experiment` command | per-list pilots (`decklab/simulation.json`), Deck Lab AI profiles, the TeamPumpAi switch `team-pump-1` | the hybrid AI switch `aisim-hybrid-1`; profiles `DLAggro`, `DLTempo`, `DLControl` until adopted |
| Battery knobs | | | pin modes `ccd`, `none`, `core-wrap`; `forge_performance_mode` false; `forge_game_patches` false; jar exclusions |
| R17 | not built | | |

### 0.6 Questions for the owner: answered 2026-10-03 (final), each as the default below

1. **Adopt Fiery Annihilation's override before the combined run?** It's an exception to "overrides are adopted
   afterwards". **Default: yes.** It's measured (R10), it saves a replay of Gruul Ramp's matchups after the run, and
   rolling it back costs about 5-6 min of idle PC. If no: `sets.json` status `experiment`, set by the integrator.
2. **The "makes little difference" margin of a variant test:** ±2 points of win rate against the field, ±3 points
   against one opponent. **Default: those.** ±2 against one opponent needs about 2,400 paired games at a typical
   correlation of 0.5, past the 1,600-game check, so nearly every test of a harmless change would end "not settled"
   (§7.4).
3. **The minimum soak for a merge:** 3 h of the combined run's real-work block with the pool busy. **Default: 3 h.** A
   PASS then needs a night with about 4.5 h of active idle PC (P0 items alone); a shorter night ends INCOMPLETE
   (COMBINED-RUN.md §5.5).

---

## 1. Architecture

```
 page / CLI
   │ POST /api/matchup/run {mode}   POST /api/field/run   POST /api/variant/run (editor draft)   experiment <spec>
   ▼                                ▼                     ▼                                      ▼
 adaptive.run_adaptive (A)   field.run_field (F)    variants.run_test (V)                  experiment.run (X)
   stages of runs; looks       floor runs, then APT   base runs (normal results), then the   arms = override sets,
   by seqstats (S)             runs (S); at most      variant arm on the base's seeds        pilots or knobs;
                               `inflight` at once     (paired results, analysed by S)        control pairing on g (S)
   └─────────────┬──────────────────────┴──────────────────────┴───────────────────┬──────────┘
                 ▼                                                                    ▼
   runner.run(entry_a, entry_b, games, exact=True, pool=..., [R: numbers, seeds, key, kind, extra, override_sets,
                 │                                              log_dir])
                 │  overrides.ensure_deployed, then engine.current / key / check_echo (E3: pilots, deck-order-1,
                 │  per-list overrides of the run's user folder)
                 ▼
   W2 pool: one chunk queue; warm workers matched by launch identity (R adds overrides and the profile folder)
                 │  request: -a <each seat's pilot profile> ... -dlgame ... -dlpilot <each seat's switches>
                 ▼
   DeckLabSim / serve (J3): Startup.afterInitialize (profile folder, AI patches, overrides hash);
   GameLoop.playGames per game: reset → reseed(load) → load decks → reseed(game) → players (pilots) →
   Match copy (deck-order-1 library order) → playOne; the DLENGINE echo adds deckorder, ai, pilots, overrides
```

- The coordinators (A, F, V, X) never handle chunks. They call `runner.run` for whole runs and read saved results.
  Stopping at game boundaries comes from stages: a look happens only once every game of its stage has finished (§9.2).
- **One engine per coordinator run.** `runner.run` returns the saved result. A coordinator keeps the key its first
  `runner.run` for a pair returned, and stops with "The engine changed during this run: play it again." when a later
  stage of that pair returns another key (a git pull, a `simulation.json` or override edit, or a cardlog-check pass in
  the middle of a run). So a look never mixes engines or reads a result with fewer games.
- All the statistics are in `seqstats.py` (S), as pure functions over game dicts. The page, the CLI, the coordinators
  and the harness share one implementation.
- **Jobs:**
  - Matchup runs (fixed, assess, ahead) stay `FORGE_JOBS` jobs (`max_running` 4, from W2).
  - Field runs and variant tests are coordinator jobs in a runner of their own, `api.forge_runs.COORD_JOBS`
    (`max_running` 2, `max_queued` 4; base), with their own key namespaces (`field:...`, `variant:...`). So a
    coordinator that runs for an hour never holds one of the matchup runs' 4 slots.
  - A coordinator's pair runs are threads inside its job, sharing the server's pool with everything else.
  - `api.stop_jobs()` stops both runners (base).

---

## 2. What wave 3 relies on from wave 2 (re-checked when the base is cut)

Wave 2 is still being built. The W3 integrator cuts `sim-w3-base` from the integrated `sim-w2` and checks every row
below against the code. Any difference is fixed in the base, or in this contract, before the packages start, and
every package rebases on the base.

| W2 piece (contract §) | What W3 uses it for | Used by |
|---|---|---|
| `runner.run(..., local, pool, exact)` (§9, §10) | runs of any number of games (`exact=True`); `pool=` takes a session or the server's pool | A, F, V, X, H |
| run record keys `games_from`, `games_to`, `engine`, `pool`, `chunks`, `recycled`, `requeued` (§12) | stage ranges; soak statistics | A, H |
| result `seeds` {scheme, base, stream, seat_block, flip}, `next_game`, merged batches with `g` (§12) | paired seeds; stage numbering | V, R, S |
| `seeds.py` (§8) | `game_seed`, `deck1_side`, `stream_of`, `SEAT_BLOCK` | R, V, J3 |
| `engine.*` signatures and description (§13); EP's canonical override hash; the remembered `ai_sha` values | E3 extends them | E3 |
| `logreader.SEAT_FIELDS`, `engine_by_side`, `LogReader.engine` (§5) | new seat fields | E3 |
| `GameLoop.playGames` steps 1-7 (§4); `Request` (§3); the start-up order of `DeckLabServe.serve` and `DeckLabSim.simulate` (§2, §6) | J3 inserts steps and a start-up hook | J3 |
| `simjar` stamp, `GAME_PATCHES`, `game_patch_ids`, `GAME_PATCH_LIST` (§19) | Deck Lab's own game patches; the list of pilot switches | J3 |
| the pool's launch identity and compatibility identity (§10) | R adds fields | R |
| `cores.mask_for`, `pin` (§11) | pin modes | R |
| the `cli.COMMANDS` pattern; `replay` (§16) | new commands; log options | all |
| `api.forge_runs` `_MatchupRun`, `FORGE_JOBS`, `stop_jobs` (§10) | run modes; jobs by key; the coordinators' own runner | A, F, base |
| the rule that a stopped run's unplayed numbers are never played later (§9) | kept for matchups; R's one exception for paired and experiment results (§8) | R, V, X |
| `engine.check_echo(eng, echo)` and the chunk reader that calls it (§9, §13) | the `seat_pilots` keyword and its call site (§4.3, §8) | E3, R |
| `runner.run` returns the saved result (§9) | the coordinators' key check (§1) | A, F, V, X |
| `saved._is_result` for v2 (§12) | the paired kind; the `adaptive` list | R |
| `cardstats` v3 early fields (§14) | experiment measures | X |
| the fake Forge's v2 and serve modes (§20) | W3 extends it (§19) | every package's tests |

### 2.1 The re-check at the base (sim-w2 `c82e714`)

Every row above holds, with these differences. Each is now part of this contract (the section named changed with it).

| # | What wave 2 actually has | What changes for wave 3 | Who |
|---|---|---|---|
| 1 | **The overrides hash** (`engine._overrides`, EP): every regular file under `custom/cards` at any depth (not only `.txt`); each line `<path>\0<sha256 hex of the file's bytes with CRLF made LF>\n` (a NUL between, not a newline); sorted by the `/` path; `"none"` with no file, `"unreadable"` when the folder can't be listed or read | §6.4 now says this form (the "keep EP's" rule). `overrides.deployed_hash` in the base implements it, and a base test holds it equal to `engine._overrides`. **J3's Java start-up hash must match it exactly**, CRLF normalisation and NUL included. The file SHA in `deployed_index` and in §4.2's `relevant_hash` is the same CRLF-made-LF SHA (`engine._file_sha`) | E3, J3 |
| 2 | **`engine.side_id(eng, fmt, side)`** already exists (side = the stored triple), called by `side_fields` and `side_ids` | §4.3's new function is named **`engine.entry_side_id(entry, fmt=None, eng=None)`**; W2's `side_id` keeps its signature (E3 may change its `side` argument to a side list) | E3, F |
| 3 | **`engine.is_current(result)`** already exists and returns True, False, or **None** when it can't be told (Forge never found) | E3 extends it (§4.3); F and V treat None as "not current" | E3, F, V |
| 4 | **`engine.side_ids(card_sha, list_kind)`** gives per-card consumers (`cardstats.list_cards`, `ai.list_ai`) today's side ids, with no pilot | E3 adds `pilot=None` (None: `pilots.pilot_for`'s default pilot), so a list's per-card numbers follow its pilot | E3 |
| 5 | W2 sorts a description's sides by their canonical JSON; an entry's own profile is `entry.get("ai")` (`engine._profile`) | id_version 2 sorts with `sorted()` on the side lists (§4.1); an `ai_sha` may be None, so two sides that tie on card and profile name must not compare None with a string (E3's sort key). `_profile` reads `entry["pilot"]["profile"]` first | E3 |
| 6 | `runner.run` orders entries by `card_sha` (`ordered`), and writes `<card_sha>.dck` (`_write_decks(decks_dir, ordered)`) | R's `side_list` order equals it for any two different lists, so stored results keep their side order. A variant's `dck_file` (`sha256(text).dck`) matches the pool service's `NAME_RE` | R |
| 7 | **The chunk reader's `check_echo` call is in `pool.Pool._line`** (pool.py), not runner; requests are built in `Pool._send` (serve) and `Pool._start` (one-shot) through `runner.request_args(..., v2=...)` | R owns those call sites (§20's "if it lives here"): `seat_pilots` and each seat's `pilots=` come from `job` by `Chunk.deck1` (already `seeds.deck1_side(first, flip)`) | R |
| 8 | **The pool service's wire** (`pool._wire`, `_service_job`) carries `dck`, `names`, `base`, `stream`, `flip`, `ranges`, ...: no pilots, no dck file names beyond `NAME_RE`, no numbers lists | R adds each side's pilot to the job and the wire (and checks it in `_service_job`). `pool.identity()`'s `"engine"` is `eng` without sides, so it will hold E3's `eng["deployed"]`: R decides whether `override_sets` runs may use the server's pool (then `deployed` leaves the compatibility identity and `launch_fields` covers it) or always play in a pool of their own | R |
| 9 | `views.balanced(play_wins, play_games, draw_wins, draw_games, z=1.96)` takes **counts**, not games | §7.4's and §7.5's "`views.balanced(<games>)`" means: count the games' strata first | S |
| 10 | The result's `seeds.stream` is the **16-hex string** (`seeds.stream_hex`) | `runner.run(seeds={"base", "stream", "flip"})` takes the stream in that form. The keyword `seeds` hides the `seeds` module inside `run()` (R renames it locally) | R, V, X |
| 11 | `GameLoop.playGames` loads the decks **and** makes the players in one `lineup(req, type, played)` call; the DLENGINE line is printed at `i == 0` after it; players use `GamePlayerUtil.createAiPlayer(name, i - 1, profile)`. Unknown `-a` names are refused before anything is printed (`knownProfiles`: "Unknown AI profile - X. Available profiles: ..." and `played.problem`, so a serve request ends with status `error`) | J3 splits `lineup` into deck loading and player creation, so the game reseed (§3.2 step 5) falls between them | J3 |
| 12 | Start-up: `DeckLabServe.serve` and `DeckLabSim.simulate` both run `FModel.initialize` then `WarmState.snapshot` | `Startup.afterInitialize()` goes between them, as §3.1 says | J3 |
| 13 | `pool.launch(setup)` = `{"argv", "cwd", "user_dir", "game_patches"}` (the launch identity is its JSON); `pool.identity(setup, eng)` is the compatibility identity | R adds `engine.launch_fields(setup, eng)` to both (the base ships `launch_fields`) | R |
| 14 | `runner._prepare_user_dir(user_dir)` writes `runner.PREFERENCES` and is called from `pool.Pool._start` with `setup["user_dir"]`; `engine.PERFORMANCE_MODE` is a constant | E3's `_preferences(setup)` and manifest reading (§6.2) | E3 |
| 15 | `api.forge_runs`: `_MatchupRun`, `run_matchup(body)`, `_job_json(job, snap, flip)`, `_running_json(job, first_sha=None)`, `_matchup_json(forge, key, sides, ai_lists, default_games, stored)`; `jobs.Runner` has `submit(key, fn, *args, rerun=False)`, `get`, `snapshot`, `cancel(key, by=)`, `active`, `join`, `stop` | none | A, F |
| 16 | `cardstats` v3 fields, `saved._is_result`, `logreader.engine_fields`/`engine_by_side`, `seeds.*`, `cores.mask_for`/`pin`/`pin_setting`, `cli.COMMANDS`/`_main`, `_replay_args`/`_cmd_replay`, `_play_args`/`_cmd_play`/`_print_play`, `simjar.GAME_PATCHES`/`game_patch_ids`/`GAME_PATCH_LIST`/`SIM_CLASSES`/`fitting_patches`/`_stamp`/`card_log` | as §2 says | all |
| 17 | The fake's serve and v2 modes; an unknown `-a` in W2's fake was never checked | §19.1 now follows Java for an unknown `-a` (Forge's "Unknown AI profile" line; a serve request ends `error`); `DLSERVE\|fail` and exit 3 are for an AI profile folder that can't be read | base |

---

## 3. Java (J3)

### 3.1 Classes

| Class | What it does | Owner |
|---|---|---|
| `decklab/DeckOrder` (new) | Keeps, per seat, the request's [Main] names in .dck line order, with copies expanded. Methods: `set(seat, names)`, `clear()`, `arrange(Player, CardPool) -> List<PaperCard>` or null, and `check(seat, Deck) -> boolean`. It finds a player's seat from the name prefix `Ai(<n>)-` | J3 |
| `forge/game/Match.java` (new; a copy of Forge 2.0.15's) | `preparePlayerZone` asks `DeckOrder.arrange` first when game patches are on, and runs Forge's own code otherwise. It's in the jar only when Forge's `Match.class` fits (W2 §19); without it Forge's own Match runs and no order applies. Pinned to the SHA-256 of Forge's `forge/game/Match.class` (inner classes checked with javap). Its GPL header goes at the end, and Forge's line numbers are kept (W2 §19) | J3 |
| `decklab/Pilots` (new) | `AVAILABLE` lists the switch ids (`team-pump-1`, `aisim-hybrid-1`). `set(String[] perSeat)` is called per request, `on(Player, id)` asks about one player, and `parse(spec)` reads `-dlpilot` | J3 |
| `decklab/TeamPumpAi` (new; from `r4-ai/java/decklab/TeamPumpAi.java`) | Extends `PumpAllAi`. `checkApiLogic` runs Forge's logic unless `Pilots.on(ai, "team-pump-1")`. When on, it runs the prototype's three cases, and falls back to Forge's logic on "no" or on any RuntimeException. The prototype's `decklab.aipatches.only` property is removed | J3 |
| `decklab/AiPatches` (new; from `DeckLabAiPatches`) | Installs `TeamPumpAi` into `SpellApiToAi.apiToInstance` once per JVM when game patches are on, by reflection on the map's contents. Prints `DL-START\|aipatch\|PumpAll` on stdout (not a game line) | J3 |
| `decklab/Startup` (new) | `afterInitialize()` loads the AI profile folder, runs `AiPatches.install` and works out the overrides hash (§3.4). `DeckLabSim.simulate` and `DeckLabServe.serve` each call it between `FModel.initialize` and `WarmState.snapshot` (one line each) | J3 |
| `GameLoop` | the v2 loop's additions (§3.2, §3.3) and the DLENGINE fields (§3.5) | J3 (wave 2 EJ's code) |
| `Request` | `-dlpilot <seat 1> <seat 2>` (§3.3) | J3 |
| `Seeds` | `loadSeed(base, stream, game)` (§3.2) | base (frozen) |

### 3.2 deck-order-1: library order and load seed

**Each v2 game with game patches on and `deck-order-1` loaded** (`GameLoop.gamePatchIds()` holds it, W2 §5). Steps 3,
5 and 7 are new or changed from W2 §4:
1. Ask the Boundary.
2. `WarmState.reset()`.
3. **New:** `MyRandom.setRandom(new Random(Seeds.loadSeed(base, stream, g)))`.
4. Load both decks (as in W2), and **call `DeckOrder.set(seat, the seat's .dck [Main] names)`**.
5. **New:** `MyRandom.setRandom(new Random(Seeds.gameSeed(base, stream, g)))`.
6. A new GameRules, RegisteredPlayers and AI players (§3.3 for pilots), and a new Match.
7. `playOne`. `Match.startGame` calls `prepareAllZones`, which calls `preparePlayerZone(player, Library, section, ...)`.
   **The copy asks `DeckOrder.arrange(player, section)`:**
   - when it returns a list, the library's Cards are made from it in that order, with the same `Card.fromPaperCard`,
     foil and `setCollectible` calls per card, so the game draws as many `MyRandom` numbers as Forge would;
   - when it returns null, Forge's own loop runs.

**Other cases:**
- **Game patches off:** exactly W2's steps (reseed with the game seed, load, players, Match), and the copy runs
  Forge's loop. `deckorder=0,0`, `loadseed=0`.
- **`deck-order-1` not in the jar** (a Forge build whose `Match.class` no longer fits): exactly W2's steps, with
  Forge's own Match. `deckorder=0,0`, `loadseed=0`. The engine's `game_patches` lacks `deck-order-1`, so the echo
  checks expect this (§4.4) and play goes on.
- **v1 (`playBatch`):** never sets an order (`DeckOrder.clear()` at the start of each request), so v1 is unchanged.

**`DeckOrder.arrange`:**
- It groups the section's PaperCards by name (copies expanded; within a name, by art index then edition, so the order
  is fixed), then takes one card per name in the .dck order.
- If a name is missing, or cards are left over, it returns null for that seat. This happens when an unsupported card
  was removed by `getValid`, or Forge rewrote a name.
- `DeckOrder.check(seat, deck)` does the same comparison once per request, on the decks loaded for the DLENGINE
  line, so the echo can say whether the order applies (`deckorder=`, §3.5). Python refuses a chunk where it doesn't
  (§4.4).

**The load seed:**
- `Seeds.loadSeed(base, stream, g) = gameSeed(base, stream ^ LOAD_SALT, g)`, with
  `LOAD_SALT = 0x6c6f616473656564` ("loadseed").
- Python has `seeds.load_seed`, `seeds.LOAD_SALT` and `seeds.LOAD_TEST_VECTORS`. The base works out 4 vectors with Java
  and with Python, and `test_forge_contract` checks both.

**What stays aligned** between a base deck and a variant written by §11.2's writer (same size, each new card in a
removed copy's slot):
- both libraries' positions before the shuffle;
- the card ids (cards are made in the same order);
- the shuffle (the same size takes the same random numbers);
- the opponent's library, the coin flip and the sleeve draws.

The two games stay the same until a card in a changed slot is seen, or until a hidden-library read differs.

### 3.3 Pilots in the request

- **`-a <profile of seat 1> <profile of seat 2>`** is already Forge's option. Python now passes each seat's pilot
  profile (§5) instead of `Default Default`.
- **`-dlpilot <seat 1> <seat 2>`** (v2 only, after `-dlgame`): each is a `+`-joined list of switch ids, or `-` for none.
  `Request.parse` refuses (with an `Error:` line and null):
  - an id that isn't in `Pilots.AVAILABLE`;
  - a missing value;
  - `-dlpilot` without `-dlgame`;
  - `team-pump-1` while `decklab.gamePatches=off` ("Error: team-pump-1 needs game patches on"), since `AiPatches` isn't
    installed then. Python refuses the same before it starts a run (`pilots.check_switches(eng)`, E3), so the side is
    never keyed or echoed with a switch that does nothing. `aisim-hybrid-1` is Forge's own option and works either way.
- **As built (J3):** a lone `-` is accepted as `-dlpilot`'s value. Java echoes each seat's switches **sorted**
  (`-dlpilot team-pump-1+aisim-hybrid-1 -` echoes `pilots=aisim-hybrid-1+team-pump-1,-`), so E3 sends them sorted
  and compares the sorted form in `check_echo`; `request_args` adds `-dlpilot` only to v2 requests. One refusal the
  fake lacks: `Error: team-pump-1's AI patch wasn't installed when this Forge started` (only when Forge's
  SpellApiToAi changed).
- **Per request,** GameLoop calls `Pilots.set(...)`.
- **Per game,** it creates each AI player with `GamePlayerUtil.createAiPlayer(name, avatar, sleeve, options,
  profile)`:
  - `options = EnumSet.of(AIOption.USE_HYBRID_SIMULATION)` for a seat with `aisim-hybrid-1`, and null otherwise;
  - `sleeve` is drawn from `MyRandom` exactly as the 3-argument overload draws it (the r4 prototype's code), so a seat
    without the switch plays the same games as today.
- **`team-pump-1`** works through `TeamPumpAi`. It's installed in every JVM with game patches on, and does nothing
  different unless a seat has the switch.

### 3.4 Start-up hooks (`Startup.afterInitialize`)

1. **AI profile folder.** When `-Ddecklab.aiprofiles=<dir>` is given, it calls `AiProfileUtil.loadAllProfiles(dir)`
   (r4 §1.4 option 2).
   - The folder holds copies of Forge's own `res/ai/*.ai` plus Deck Lab's (§5.3), so every name `-a` may use is there.
   - A failure (an unreadable folder, or a profile key Forge doesn't know) prints `DLSERVE|fail|...` in serve mode and
     an `Error:` line in sim mode, and exits with code 3. So a pilot can never silently fall back to another profile.
2. **AI patches.** It calls `AiPatches.install()`, unless `decklab.gamePatches=off` or the test-only property
   `decklab.aipatches.install=false` is set (that property is for J3's neutrality check; Python never passes it).
3. **Overrides hash.** It works out the canonical hash (§6.4) of `<APPDATA>/Forge/custom/cards` as Forge loaded it at
   start-up, and keeps it for the DLENGINE line. (Custom cards load eagerly in `StaticData.loadCustomCards`, even with
   lazy loading.)

**As built (J3):** `Startup.afterInitialize(boolean serve)` takes the mode. With game patches on, the JVM prints
`DL-START|aipatch|PumpAll` once, before `Simulation mode` or `DLSERVE|ready`; LogReader and the pool ignore it,
and the fake doesn't print it.

### 3.5 DLENGINE additions (after W2's keys; readers ignore keys they don't know)

| Key | Value |
|---|---|
| `deckorder` | `<seat 1>,<seat 2>`, each `1` (the .dck order applies) or `0` (game patches off, `deck-order-1` not in the jar, v1, or `DeckOrder.check` failed). A seat field |
| `ai` | `<seat 1>,<seat 2>`: the `-a` profile names. A seat field |
| `pilots` | `<seat 1>,<seat 2>`: each seat's switches joined by `+`, or `-` for none. A seat field |
| `aiprofiles` | `forge` (res/ai) or `dl` (a `-Ddecklab.aiprofiles` folder was loaded) |
| `overrides` | `none`, or the start-up overrides hash (§6.4) |
| `loadseed` | `1` when step 3 used the load seed (v2, game patches on, `deck-order-1` loaded); else `0` |

- **Order on the line** (the fake prints it so; readers don't depend on it): after W2's `avgcmc`, then `deckorder`, `ai`,
  `pilots`, `aiprofiles`, `overrides`, `loadseed`. They're printed on every DLENGINE line, v1 included (`deckorder=0,0`,
  `pilots=-,-`, `loadseed=0` there).
- The base sets `logreader.SEAT_FIELDS` to `("autoprofile", "avgcmc", "deckorder", "ai", "pilots")`.
- No value holds `|`, `=` or `,`: switch ids match `simjar.GAME_PATCH_ID`, and E3 checks that profile names match
  `[A-Za-z0-9_-]{1,40}`.

### 3.6 simjar

- **Match:** `PATCHES["forge/game/Match.class"] = {<Forge 2.0.15's SHA-256>}` and
  `GAME_PATCHES["forge/game/Match.class"] = "deck-order-1"`.
- **`OWN_CLASSES`** (a new name, frozen; J3 fills it): Deck Lab's own classes the jar must hold beyond `SIM_CLASSES`:
  `DeckOrder`, `Pilots`, `TeamPumpAi`, `AiPatches` and `Startup`.
- **`PILOT_SWITCHES`** (a new name, frozen; J3 fills it):
  `{"team-pump-1": "decklab/TeamPumpAi.class", "aisim-hybrid-1": "decklab/GameLoop.class"}`.
  - The build writes `decklab/pilot-switches.txt`, the stamp records the ids, and `card_log()["pilot_switches"]` lists
    them, sorted.
  - A switch is available only when its class is in the jar. Deck Lab's own classes always are: either they compile or
    the build fails.
  - Java's `Pilots.AVAILABLE` must equal this list (a J3 test).
- **Battery knob** (harness only): `DECKLAB_SIMJAR_EXCLUDE` is a comma-separated list of class files of **neutral**
  patches (`PATCHES` keys not in `GAME_PATCHES`) to leave out of a build.
  - It changes the stamp, so it builds another jar file. It never changes the engine id, because neutral patches
    aren't keyed.
  - Excluding a game-changing patch is refused (ValueError).
  - As built (J3): `simjar.excluded_patches()` and `fitting_patches()` raise ValueError for a value they can't
    accept, and so does `engine._jar_patches`, outside `card_log()`'s and `readiness()`'s catch-alls. H calls
    `simjar.excluded_patches(value)` before setting the variable and refuses the run if it raises. V's §11.4
    refusal tests `"deck-order-1" in card_log()["game_patches"]`.
- **`CHECKED_SOURCE`** is set after cardlog-check passes (the W2 rule).

### 3.7 J3's checks

Kept as scripts in J3's notes, each within ≤ 400 games and ≤ 4 processes.

1. **cardlog-check v2** (W2 §18) passes on J3's tree. Parity with plain Forge (game patches off) is unchanged by
   construction, and the card log on vs off with patches on stays identical.
2. **Alignment.**
   - Setup: Gruul Ramp (target) against Izzet Prowess, 20 v2 games, with the base list and with a variant from §11.2's
     writer. Variant 1: −1 of a 4-of spell, +1 of a card already in the deck. Variant 2: −2 spells, +2 basic lands.
   - Pass: in each game, each seat's sequence of cards moved Library → Hand (DL|zone lines) is the same in both arms up
     to the first draw of the changed slot's card, and the starter is the same in 20 of 20 games.
   - **Deviation (J3, accepted at merge 2):** a library search or reveal by Gruul (Fierce Empath, Sakura-Tribe
     Elder) is a hidden-library read whose choice can change the shuffle that follows, so the strict rule doesn't
     hold for lists whose tutors' filters match a changed card. `test_forge_deckorder` counts such games as
     "searched" when they first differ before Gruul's next draw after the search, and games whose first
     difference comes at or after an AI decision timeout as "timed out" (left out of the rule that at least half
     the remaining games stay the same until the changed card moves). A misalignment first showing between a
     search and Gruul's next draw would still pass; COMBINED-RUN D2a measures the coupling.
3. **TeamPumpAi changes nothing while switched off.**
   - Setup: Selesnya Rabbits against Orzhov Vampires, 60 v2 games, once with `decklab.aipatches.install=false` and once
     installed with no seat switched on.
   - Pass: identical logs (W2 masks).
4. **TeamPumpAi switched on.** The same 60 games with Rabbits' seat switched on: no exception lines, and Overrun and
   Rabbit Response cast more often. This is a smoke check, not a measurement.
5. **Hybrid AI is deterministic.** Izzet against Gruul, 10 v2 games with seat 1 on `aisim-hybrid-1`, twice: identical.
6. **Profile folder.**
   - A folder with Forge's 4 profiles plus `DLAggro.ai`: `-a DLAggro Default` loads.
   - Default games are the same with the folder as without it (`-a Default Default`, 20 games).
7. **Every list keeps its order.** One v2 game of each current list (every deck file's target and owned-only lists,
   and every product deck) against Izzet Prowess: the echo says `deckorder=1,1`. A list that gives `0` (a name Forge
   rewrites, a double-faced card's name) is fixed in `DeckOrder`'s name matching before the merge, because §4.4 would
   refuse every chunk of it.

---

## 4. Engine id, version 2 (E3)

### 4.1 Description

```jsonc
desc = {
  "id_version": 2,                        // W3: per-list overrides, pilots in the sides
  "run_version": 2,
  "kind": "decklab" | "plain",
  "forge": "2.0.15",
  "format": "Constructed" | "Commander",
  "clock_s": 120,
  "seeds": seeds.SCHEME | "batch",
  "performance_mode": true,               // config forge_performance_mode (a harness knob; default true)
  "game_patches": ["attack-requirements-in-order-1", "deck-order-1"],   // card_log()["game_patches"]; [] with forge_game_patches false
  "overrides": "none" | "<sha256>",       // §4.2: the deployed override files that matter to these two lists
  "sides": [[card_sha, ai_name, ai_sha], [card_sha, ai_name, ai_sha, [switch, ...]]]   // sorted; switches only when there are any
}
key     = sha256(canonical(desc))                                   (W2's canonical JSON)
side id = sha256(canonical({**desc without "sides", "overrides": <its own list's overrides>, "side": side}))
```

- **A side** is `[card_sha, ai_name, ai_sha]`, with a fourth element, the sorted switch list, only when that list
  isn't empty.
- **`ai_sha`** is the SHA-256 of the profile file actually loaded. It comes either from Forge's `res/ai` (W2: its
  values are remembered per Forge version and build) or from Deck Lab's profile folder (§5.3: the repo file's bytes,
  so it's always known).
- **Sides are sorted** with Python's `sorted()` on the side lists themselves (`[card_sha, ai_name, ai_sha]`, or with
  the fourth element; when the first three are equal, the shorter list comes first), so a mirror whose two sides
  differ only in their pilot has a fixed order. `engine.side_list(entry, eng)` builds an entry's side list, and every
  place that orders sides uses it with this sort: `key`, `side_id`, and R's entry order and `_record` (§8). A test
  checks the order on a pilot mirror.
- **`kind: "plain"`** (no card log):
  - Plain Forge takes `-a` with Forge's own profiles, and nothing else.
  - Its sides record what plain Forge actually plays: the pilot's profile when it's one of Forge's, else `Default`;
    never switches.
  - So a plain-kind result never claims a pilot it didn't use.

### 4.2 The overrides component

`overrides.relevant_hash(deployed, names)` covers the deployed override files (§6) whose script's `Name:` is one of
`names`. `deployed` is the index of the run's user folder that `engine.current` captured right after
`overrides.ensure_deployed` (§6.2), never a fresh read of some other folder, so an experiment arm is keyed by its own
folder's files:
- It's the SHA-256 of `<card name>\n<sha256 hex of the file's bytes>\n` for each such file, sorted by card name; or
  `"none"` when there's none.
- **For a matchup,** `names` are the Forge names (W2 `forge_name`, front faces) of both lists' Main and Commander
  cards. **For a side id,** only its own list's.
- Tokens and cards made by effects aren't covered: no current list casts an opponent's cards (R08's scan).

### 4.3 Who works out what

| Function | Change |
|---|---|
| `engine.current(setup, card_log)` | adds `performance_mode` from `setup["performance_mode"]`; `game_patches` is [] when `setup["game_patches"] is False`; and `eng["deployed"] = {"user_dir", "index": {card name: file sha}, "hash"}`, the run's user folder (`setup["user_dir"]`) as `overrides.ensure_deployed` left it. `deployed` isn't part of the description; `key`, `side_id` and `launch_fields` read it. No sides and no overrides in the description (those are per matchup) |
| `engine.key(a, b, eng)` | sides from `side_list` (pilots from `entry["pilot"]`, §5), the per-matchup overrides from `eng["deployed"]`, id_version 2 |
| `engine.matchup_key(a, b)` | the same without Java (W2's rule: remembered values), for the real user folder after `ensure_deployed` (§6.2) |
| `engine.side_list(entry, eng)` (new) | an entry's side list (§4.1), for sorting and keys |
| `engine.entry_side_id(entry, fmt=None, eng=None)` (new; §2.1 row 2: W2's `side_id(eng, fmt, side)` keeps its name) | today's side id of a list (for per-card consumers and for the Bradley-Terry players); fmt defaults to the entry's, eng to `today()` |
| `engine.is_current(result)` (W2's, extended) | True when the result's stored description equals what `key()` gives today for its two sides' lists as stored (`sides[i]["cards"]`, with the pilots from the stored sides); None when that can't be told (W2), which F's Bradley-Terry fit and V's base check treat as not current |
| `engine.side_ids(card_sha, list_kind, pilot=None)` (W2's, extended) | the per-card consumers' side ids, with the list's pilot (§2.1 row 4) |
| `engine.side_fields(eng, side, echo)` | adds `pilot` {"profile", "switches"}, and `deckorder` from the echo |
| `engine.check_echo(eng, echo, seat_pilots=None)` | adds the checks in §4.4. `seat_pilots` is `[deck 1's pilot, deck 2's pilot]`, **in the chunk's seat order**, each `{"profile", "switches"}`. The caller (R's chunk reader, §8) takes them from the stored sides through `deck1_side(g, flip)`, so E3 and R never map seats two ways. Without it (W2 callers), the pilot checks are skipped |
| `engine.launch_fields(setup, eng)` (new) | `{"overrides": eng["deployed"]["hash"] (§6.4), "user_dir", "aiprofiles": <the profile folder's hash, or None>, "performance_mode", "game_patches"}`, for R's launch and compatibility identities |
| `pilots.check_switches(eng, pilot)` (new) | refuses (ValueError with a sentence) a switch the engine can't play: `team-pump-1` when `eng["game_patches"] == []` |

### 4.4 Echo checks added

A failing chunk fails at once (W2 §9). A decklab-kind v2 chunk is refused when its DLENGINE line says:
- `deckorder` other than `1,1` when `deck-order-1` is in `eng["game_patches"]`, or other than `0,0` when it isn't.
  (W2's check already makes the echo's `gamepatchids` equal the engine's list, so the two always agree.) The condition
  is never "game patches on": a Forge build without the copy must keep playing;
- `loadseed` other than `1` when `deck-order-1` is in `eng["game_patches"]`, or other than `0` when it isn't;
- `ai` other than `seat_pilots`' profiles, seat by seat;
- `pilots` other than `seat_pilots`' switches, seat by seat;
- `overrides` other than `eng["deployed"]["hash"]`. The failure reads "The card-script overrides changed while this
  run was playing: play it again.".

And one W2 rule changes: `gamepatches=off` is **accepted exactly when `eng["game_patches"] == []`** (the
`forge_game_patches` knob, §17), and refused otherwise, as W2 says.

A fake test (§19.1) plays with `--game-patch-ids` lacking `deck-order-1`: every chunk passes with `0,0` and `0`.

---

## 5. Pilots and `decklab/simulation.json` (E3)

### 5.1 The file

`decklab/simulation.json` is a new file, committed and owned by Deck Lab.
- It isn't `config.json`, which holds machine settings.
- It isn't a deck-file header field either: product decks have no deck file, and Deck Lab's deck rewriter would have
  to learn the field.

```jsonc
{
  "version": 1,
  "pilots": {
    "default": {"profile": "Default"},
    "lists": {
      // "<deck id>" applies to every version; "<deck id>@owned" or "@target" to one version (and wins over it)
      // e.g. "casual/selesnya-rabbits": {"profile": "Reckless", "switches": ["team-pump-1"]}
    }
  },
  "field": {"Constructed": {"add": [], "remove": []}, "Commander": {"add": [], "remove": []}}   // §10.1
}
```

It ships with empty `lists` and empty field edits: every list plays with Forge's Default profile and no switches until
a pilot is adopted.

### 5.2 Resolution and validation

- **Resolution.** `pilots.pilot_for(deck_id, version)` returns `{"profile", "switches"}`. `lists.entry(...)` puts it on
  every entry as `entry["pilot"]`, and `entry_from_dck` puts the default. A variant of a list (§11) takes the base
  list's pilot.
- **Validation.**
  - `pilots.load()` reads the file once per change of its modification time.
  - A bad entry (unknown profile, unknown switch, bad id) is left out, with one log line, and
    `python -m decklab.lib.forge pilots --check` lists it (exit code 1).
  - An entry is never applied in part.
- **What's available.**
  - Profiles: Forge's `res/ai/*.ai` names, plus Deck Lab's `decklab/lib/forge/ai-profiles/*.ai`.
  - Switches: `card_log()["pilot_switches"]` (§3.6).
  - When the card log isn't ready (plain kind), the engine records what plain Forge can play (§4.1), and the page says
    the pilot couldn't be used.
- **Labels on the page and in the CLI:**
  - `team-pump-1`: "team-pump fix";
  - `aisim-hybrid-1`: "look-ahead AI (experimental)";
  - a Deck Lab profile: "Deck Lab's <name> profile".

### 5.3 Deck Lab's AI profiles

- **The files,** in `decklab/lib/forge/ai-profiles/`. Each is a full copy of Default.ai with only the listed keys
  changed:
  - `DLAggro.ai` and `DLTempo.ai` are r4's (121 keys each);
  - `DLControl.ai` is Default plus `MIN_SPELL_CMC_TO_COUNTER=2` and the counter-chance keys of r4 §4.2: a counterspell
    profile, for the plan's open question G4 (sim-investigation.md §7).
- **The mirror.** `pilots.profile_folder(setup)` copies Forge's `res/ai/*.ai` and these files into
  `<data>/forge/ai-profiles/<sha12>/`, a folder named by the hash of its sorted file hashes and written once. It
  returns the folder's path, or None when the card log isn't ready.
- **The launch.** `install._setup` puts the path in `setup["aiprofiles"]`, and `runner._java` adds
  `-Ddecklab.aiprofiles=<path>` to DeckLabSim launches only.

### 5.4 Where it shows

- `sides[]` gain `"pilot": {"profile", "switches", "words"}` (`views._page_side`).
- The run record's `settings.ai` holds the sides' pilot profiles in side order (R's `_record`), not W2's constant
  `AI_PROFILES`, so "How these games were played" never contradicts a pilot. For v1 results it stays as stored.
- `status` and `list` in the CLI print each non-default pilot and the deployed overrides (E3's `_setup_lines(found=None)`,
  called from `_cmd_status` and `_cmd_list`; E3 owns those lines; wave 2's `_engine_lines(result, v, entries)` stays
  play's lines). The page's pump words (`matchups.js` `pumpSplit`) name the
  team-pump fix when it's on (E3).
- When a pilot isn't the default, the matchup page's side box and the deck page's header say so, for example "Forge's
  AI plays it with the Reckless profile and the team-pump fix".
- `ai._pilot` (wave 1's R19 flag): a list whose pilot has `team-pump-1` doesn't count its `team_pump` copies, and the
  flag's words add "with Deck Lab's team-pump fix".

---

## 6. Card-script overrides (R10, E3)

### 6.1 In the repo

```
decklab/lib/forge/overrides/
  sets.json
  fiery/fiery_annihilation.txt            adopted
  etb/massacre_wurm.txt, theoden_king_of_rohan.txt, samwise_the_stouthearted.txt, eowyn_fearless_knight.txt,
      palace_jailer.txt, fires_of_mount_doom.txt
                                          experiment; Fires gets only the ChompEquip sub's AILogic$ Always
  etb-flagged/sunblast_angel.txt, fires_of_mount_doom.txt
                                          experiment: r4's two flagged edits, as r4 made them
  tgt/stroke_of_midnight.txt              experiment
  tgt-gift/generous_gift.txt              experiment: the flagged AITgts removal, judged on its own
  remove/devout_decree.txt, beast_within.txt
                                          experiment; Beast Within keeps its AITgts, as in r4
  flash/gandalf_the_white.txt             experiment
  hints/valley_questcaller.txt, righteous_valkyrie.txt (SVar:PlayMain1), stormcatch_mentor.txt,
      heartfire_immolator.txt (BuffedBy)  experiment
  README.md                               where the scripts come from: Forge's GPL card scripts, edited
```

`sets.json`:
```jsonc
{"version": 1, "forge": "2.0.15",
 "sets": {
   "fiery": {"status": "adopted", "why": "r4 2.3, e4 2.4",        // "experiment" if the owner says no (§0.6)
             "files": {"fiery_annihilation.txt": {"card": "Fiery Annihilation",
                        "upstream_sha256": "<sha of Forge 2.0.15's script>",
                        "edits": [["SVar:DBChangeZone:DB$ ChangeZone | Origin$ Battlefield | Destination$ Exile | ValidTgts$ Equipment.AttachedTo ParentTarget | TargetMin$ 0 | TargetMax$ 1",
                                   "SVar:DBChangeZone:DB$ ChangeZoneAll | ChangeType$ Equipment.AttachedTo Targeted | Origin$ Battlefield | Destination$ Exile"]],
                        "cast_target": 0.8}}},
   "etb": {"status": "experiment", ...}, ...}}
```

- Each file is Forge's script for that card with its `edits` applied: exact string replacements, as r4's
  `make_overrides.py` does.
- `python -m decklab.lib.forge overrides make [--set S]` makes them again from the installed Forge's `cardsfolder.zip`.
  It fails loudly (exit code 1, naming the card) when an edit's old text isn't found exactly once.
- For the hints set, E3 confirms the exact SVar text in Forge 2.0.15's source (`ComputerUtil.castPermanentInMain1` for
  PlayMain1, and the code that reads BuffedBy) and records it in `sets.json`.

### 6.2 Deploying

- **`overrides.deploy(user_dir, sets=None)`** copies the files of `sets` (default: every `adopted` set) into
  `<user_dir>/Forge/custom/cards/`.
  - It **deletes any other file there**: the folder is Deck Lab's (W2 §13).
  - A file is written only when it differs.
  - When a card is in two of the given sets, the later set in the list wins (experiments list their sets after the
    adopted ones). The result names the file chosen.
- **Upstream check.**
  - A file whose `upstream_sha256` isn't the installed Forge's script for that card isn't deployed. This happens when a
    Forge upgrade changed the script.
  - There's one log line, `forge.status()["overrides"]["stale"]` names the card, and the page's Forge box says, for
    example, "Deck Lab's fix for Fiery Annihilation doesn't fit this Forge version yet".
  - So an override never hides an upstream fix.
  - The upstream hashes are cached per Forge version and build in `<data>/forge/overrides-upstream.json` (card → SHA-256
    of Forge's script), read from `cardsfolder.zip` only when the build changes. While Forge's folder can't be read,
    the remembered values are used (W2's rule for `ai_sha`), so keys don't change.

**The deploy rule (frozen): `overrides.ensure_deployed(user_dir) -> {"index", "hash"}`.**
- It makes the folder hold exactly its intended files, under a cross-process lock (`<data>/forge/overrides.lock`, an
  OS lock like the slots'), and returns the deployed index (card name → file SHA-256) and its hash (§6.4).
- **The intended files:**
  - a folder made by `user_dir_for` has a manifest, `decklab-manifest.json` in its root, with its sets; it gets
    exactly those sets;
  - the real user folder (`common._user_dir()`, no manifest) gets every `adopted` set;
  - always after the upstream check.
- It writes only what differs, so it's cheap to call often.
- **Who calls it,** so that keys, side ids and launch hashes are always worked out from what a new worker will load:
  - `runner.run`, before `engine.current` (R);
  - `runner._prepare_user_dir`, at every worker start (E3);
  - the server, at start-up (base: one call in `server.py`'s start-up);
  - `install.status()`, so page keys from `matchup_key` follow a `sets.json` change at once (E3). `matchup_key` itself
    reads the real folder's index (cached by the folder's modification time) and never deploys;
  - `staged-move` and `soak-probe`, before they work out keys (H). W2's `replay` gets it through `install.status()`,
    which it already calls before planning (W2 §16, case 1), and again through `runner.run`.
- `overrides deploy --sets X` (CLI, E3) never deploys into the real run folder: without `--user-dir` the sets go into
  their own experiment folder (`user_dir_for(X, performance_mode=<knob>)`, printed as `folder:`), and `--user-dir
  <the real folder> --sets ...` is refused. Without `--sets` it is `ensure_deployed`.
- So the first run after an adoption, a Forge upgrade that makes a file stale, or a fresh clone is keyed and launched
  with the hash its workers echo, and has no failed chunks. A test (E3 and R): change `sets.json`, then the next run
  plays with no failed chunk and under the new key.
- A deploy while a run is playing (a `sets.json` edit mid-run) makes that run's new workers echo another hash; its
  chunks then fail with the overrides sentence (§4.4). That's rare and safe.

**Other user folders: `overrides.user_dir_for(sets, *, performance_mode=True) -> path`.**
- `<data>/forge/users/exp-<12 hex of canonical({"sets", "performance_mode"})>/`, with its manifest written once.
- Used by experiment arms (`runner.run(..., override_sets=...)`, §8) and by the PERFORMANCE_MODE knob:
  `install._setup` (E3) picks `user_dir_for(<adopted sets>, performance_mode=False)` when `forge_performance_mode` is
  false. So a knob never rewrites the real folder's `forge.preferences`, which other launches' workers read when they
  start. (The `forge_game_patches` knob needs no folder of its own: it's a JVM flag, and its launch identity already
  differs.)
- `runner._prepare_user_dir(user_dir)` (E3) writes `forge.preferences` with the manifest's `PERFORMANCE_MODE` (the
  config's for the real folder) and calls `ensure_deployed(user_dir)`. A pool worker started for an `exp-` folder
  therefore keeps that folder's files (an R and E3 test).

### 6.3 Where the overrides count

- **ai.py reads deployed scripts in place of Forge's.**
  - `overrides.overlay_index(index)` replaces the `install.script_index()` entries of deployed cards.
  - `weak_cards()` and `_cannot_play` use the overlay, so adopting `remove` would clear Devout Decree's "never cast"
    flag.
- **Engine id:** §4.2.
- **Per-card stats:** Fiery Annihilation's old results, where it was never cast, never pool with new ones (other side
  ids).

### 6.4 The canonical hash (the same in Python and Java)

Wave 2's EP defined it (`engine._overrides`), so the base keeps EP's form (§2.1 row 1), and J3 matches it.
`overrides.deployed_hash(user_dir)`, `engine._overrides(user_dir)` and Java's start-up hash all take:
- **every regular file** under `custom/cards`, at any depth (not only `.txt`; Deck Lab's folder holds only `.txt`);
- each one's path relative to `custom/cards`, written with `/`;
- sorted by those paths (Python's string order, which is the UTF-8 bytes' order);
- and hash, with SHA-256 over UTF-8, the concatenation of `<path>` + NUL (`\0`) + `<sha256 hex of the file's bytes with
  every CRLF made LF>` + `\n`, one per file.

It's `"none"` when there's no file, and (Python only) `"unreadable"` when the folder can't be listed or a file read.
The file SHA in the deployed index and in §4.2 is the same CRLF-made-LF SHA (`engine._file_sha`).

### 6.5 Workers and changes

- Custom cards load when the JVM starts (§3.4), so a worker keeps the set it started with.
- R adds `engine.launch_fields(setup, eng)` (the user folder and its deployed hash) to the launch identity (W2 §10) and
  to the server's compatibility identity. After a deploy, new chunks go to new workers, and idle old workers retire.
- The DLENGINE `overrides` echo (§4.4) catches a worker that started after a change in the middle of a run.

---

## 7. Sequential statistics (S: `decklab/lib/forge/seqstats.py`)

Pure functions over game dicts (`{"g", "w": winning side or None, "first": starting side or None, ...}`), standard
library only. Side `p` is the deck the question is about. The strata are p on the play (`first == p`) and p on the
draw.

### 7.1 Constants (frozen names)

| Name | Value | Name | Value |
|---|---|---|---|
| `Z95` | 1.959964 | `FIELD_FLOOR` | 200 |
| `HP_LOOKS` | (400, 800, 1600, 3200) | `FIELD_STEP` | 100 |
| `HP_INTERIM` | 3.0 | `FIELD_CAP` | 1600 |
| `HP_FINAL` | 2.008 | `APT_EPS` | 0.05 |
| `ASSESS_PILOT` | 400 | `RESIDUAL_FDR` | 0.10 |
| `ASSESS_HALF_WIDTH` | 0.03 | `RESIDUAL_POINTS` | 0.05 |
| `ASSESS_MARGIN` | 1.03 | `BT_PRIOR_SD` | 4.0 |
| `CAP` | 3200 | `BT_DRAWS` | 4000 |
| `ASSESS_TOPUPS` | 1 | `AV_RHO` | 50.4 |
| `EQUIV` | `views.ABOUT_EVEN` (0.05) | `AV_ALPHA` | 0.05 |
| `VARIANT_EQUIV_FIELD` | config `forge_variant_margin` (0.02) | `PAIRED_LOOKS` | `HP_LOOKS` |
| `VARIANT_EQUIV_ONE` | config `forge_variant_margin_one` (0.03) | `FIELD_PAIRED_LOOKS` | (200, 400, 800, 1600), per opponent |

**The HP boundaries.**
- 3.0 at every interim look, and 2.008 at the **last look the run can reach**: the last `HP_LOOKS` entry that is
  ≤ the run's `max_games` (default `CAP`).
- r5 (`sim_seq-out.txt` §2, 100,000 Brownian paths) and the statistics review (400,000 paths) give an overall α of
  5.0 % for looks at information fractions 1/8, 1/4, 1/2 and 1.
- The exact final bounds are 1.997 for 4 looks, 1.986 for 3 and 1.968 for 2. So 2.008 is conservative for every subset
  of those looks: a result that starts between looks, `--max 1600`, and the field-paired looks all reuse it.
- An extra interim look at 3.0 (a Stop between looks, or "Play more" on a variant test) costs at most 0.27 % of α.

**APT_EPS.** r5's `sim_alloc` numbers (wrong side 0.12 % with ε 0.05, against 0.40 % with 0.02) are for 1,600 games
**in total** over 10 opponents with no floor, which isn't this design (a 200-game floor, then up to 400·m). ε = 0.05 is
chosen instead to match the ±5-point "about even" zone: once an opponent is clearly more than 5 points from even, it
stops drawing extra games. S may re-run `sim_alloc` with the floor and this budget and record the numbers in its
notes; that's not a gate.

### 7.2 Assess (precision planning): r5 §3a, mode 1

**Inputs.**
- For each stratum s ∈ {play, draw}: `n_s` games and `w_s` wins of p (non-wins count as losses, as in the headline).
- `hw`, the half-width the stopping rule judges: the larger side of `views.balanced`'s MOVER-Wilson range at n games,
  `max(value − low, high − value)`.

**The plan comes from the range actually judged.** A range's width shrinks like 1/sqrt(n), so n·(hw/h)² is the count
at which today's range would be h wide:
```
N_total = ceil25( max(n + 100, n · (hw/h)² · ASSESS_MARGIN) ), clamped to CAP
```
h is `ASSESS_HALF_WIDTH`, ceil25 rounds up to a multiple of 25, and the 3 % margin covers MOVER-Wilson's longer side in
lopsided matchups. The same formula serves the plan and the top-up, so a top-up always plays at least 100 games and is
never a no-op.

**The page's estimate before the pilot** (fewer than 400 games):
- `assess_estimate(games, p)`: `ceil25(Z95² · v / h²)`, with `v = (p̃_play q̃_play / f + p̃_draw q̃_draw / (1 − f)) / 4`,
  the shrunk rates `p̃_s = (w_s + 1)/(n_s + 2)`, and `f = clamp(n_play/n, 0.2, 0.8)` (0.5 with no games).
- It's for the time shown on the page only. It never decides when to stop.

**`assess_next(games, p, h=0.03, cap=CAP, topups_done=0, *, plan_done=None) -> (more_games, reason)`:**
- n < 400: (400 − n, "pilot");
- hw ≤ h: (0, "precise");
- n ≥ cap: (0, "capped");
- the first call after the pilot: (N_total − n, "plan"). The caller says which call this is with `plan_done` (False until
  the planned stage has played, then True); None infers it as `n > 400 or topups_done > 0`, wrong for a run that
  starts from a result with more than 400 games;
- after the planned stage, once more if hw > h + 0.002 and `topups_done < ASSESS_TOPUPS`: (N_total − n, "top-up");
- otherwise: (0, "capped at plan").

r5 §3a: this rule's coverage at stopping is 94.1-94.9 % with no correction, because it depends on the data only
through p(1 − p). For the same reason the plain lead verdict after an assess run needs no correction: the rule never
looks at which deck is ahead.

### 7.3 Who's ahead (verdict): r5 §3a mode 2, §1.4, §1.5

**The decided-share statistic** (r5 §1.4). In each stratum, `a_s` is p's wins, `b_s` the other deck's,
`d_s = a_s + b_s` and `π_s = a_s/d_s`.
```
π̂    = (π_play + π_draw)/2                                   (the estimate)
π̃_s  = (a_s + 0.5)/(d_s + 1)                                 (for the SE only)
SE   = sqrt(π̃_play(1 − π̃_play)/d_play + π̃_draw(1 − π̃_draw)/d_draw) / 2
z    = (π̂ − 0.5)/SE
```
- The half-count SE is `cardstats._difference`'s rule, so a deck that wins every decided game still gets a finite z
  (200-0 in both strata: SE ≈ 0.0025, z ≈ 200.7) and a verdict.
- z is undefined only when a stratum has `d_s = 0`. The look then continues, or gives `not_settled` at the last look.

**`look(games, p, n_total, *, max_games=CAP, stopped=False) -> {"look", "z", "bound", "low", "high", "decision",
"side", "basis"}`.** `ahead_next` plans the stage up to the next look.
- **The bound:**
  - `HP_FINAL` when this is the last look the run can reach (n_total ≥ the last `HP_LOOKS` entry ≤ max_games);
  - `HP_INTERIM` at other planned looks;
  - `HP_INTERIM` for a look made because the run was **stopped between planned looks** (`stopped=True`).
- **The lead** is `views._lead(games, p, ...)` as the page works it out (95 % ranges; Bonferroni 97.5 % on the
  comparison basis).
- **Decisions:**
  - `ahead`: |z| ≥ the bound **and** `_lead`'s side is z's sign; `side` is z's sign. So the outcome never contradicts
    the range the page shows: at 3,200 games with 2.008 ≤ |z| but `_lead` not settled (many draws or timeouts), the
    decision is `not_settled`.
  - `about_even`: at a planned look, `_lead`'s range lies within ±EQUIV (its verdict is `about_even` or
    `slightly_ahead`). For a stopped look, the 99.73 % decided-share range π̂ ± 3.0·SE must lie within 0.5 ± EQUIV.
  - `slightly_ahead`: both of those hold.
  - otherwise `continue`; `not_settled` at the last look; for a stopped look `not_settled_stopped` ("not settled:
    stopped between checks").

**The verdict shown while a summary applies.** While `adaptive_last` applies (§9.3), the page's lead word is the
summary's decision, not the plain `_lead` (base wires `adaptive.lead_from_summary` into `views.view`). A stopped run
therefore never shows the plain 95 % verdict at a stopping time chosen while watching the bar, which r5 measured at a
29.5 % false-lead rate.

**A result that already has games** starts at the first `HP_LOOKS` entry > n (a result already on an entry makes
that look first with `look()`), so a 1,000-game result looks at 1,600 (3.0) and 3,200 (2.008). At n ≥ 3,200 there's
no look ("already played 3,200 games"), and the plain verdict stands.

**Expected games** (r5 §3a's table), without the "about even" exit: about 468 at a true 60 %, 1,432 at 55 %, 2,636 at
53 % and 3,184 at 50 %. With the exit, an even matchup stops "about even" at 1,600 games when |π̂ − 50| ≤ ~2.5 points.
The bias at stopping is under 1 point, so the plain estimate is reported, with "the run stopped early".

### 7.4 Paired differences (variant against base): r5 §3d item 4

**The paired games.** The game numbers g that are in both arms (the base result's games and the paired result's
games) **and whose starter is the same in both arms**:
- y_B,g = 1 when the base deck won game g; y_V,g = 1 when the variant won (non-wins count 0);
- the stratum is whether the variant's side started g (the same as the base's side, for these games).
- **Starter mismatches** (games in both arms with different starters) are counted, reported and left out. When they
  are more than 1 % of the common games, the test warns "The two versions didn't get the same games; the comparison is
  weaker than it should be". Coupled arms give 0.

**The estimate** uses Agresti-Min's (2005) adjusted Wald interval for matched proportions, per stratum. With `b` the
games the variant won and the base didn't, `c` the reverse, and `n` the paired games:
```
b' = b + 0.5   c' = c + 0.5   n' = n + 2
Δ'_s   = (b' − c')/n'
Var'_s = ((b' + c') − (b' − c')²/n') / n'²
Δ      = ((b_play − c_play)/n_play + (b_draw − c_draw)/n_draw)/2          (the estimate reported)
range  = (Δ'_play + Δ'_draw)/2 ± Z95 · sqrt(Var'_play + Var'_draw)/2
z      = ((Δ'_play + Δ'_draw)/2) / (sqrt(Var'_play + Var'_draw)/2)
```
Pairing stays valid however much the games diverge: divergence only lowers the correlation, and the variance formula
holds for any correlation.

**Also reported, all over the same paired games:**
- ρ: the Pearson correlation of y_V and y_B; `None` when either arm is constant;
- `same`: the share of paired games whose winner, starter, rounds, turns and result are equal in both arms (the change
  never mattered);
- **the unpaired difference** (MOVER, the structure of Newcombe's method 10), with
  `(v_V, l_V, u_V) = views.balanced(<the variant arm's paired games>)` and likewise `(v_B, l_B, u_B)` for the base arm:
  ```
  d    = v_V − v_B
  low  = d − sqrt((v_V − l_V)² + (u_B − v_B)²)
  high = d + sqrt((u_V − v_V)² + (v_B − l_B)²)
  ```
- "pairing saved X % of the games": X = 1 − (paired width / unpaired width)², which is about ρ. `None` when ρ is
  `None`.

**Verdicts,** with the margin m = `VARIANT_EQUIV_ONE` (±3 points) against one opponent and `VARIANT_EQUIV_FIELD`
(±2 points) against the field:
- `better` when low > 0, and `worse` when high < 0;
- `little_difference` when the range lies within ±m;
- `slightly_better` (or `slightly_worse`) when `better` (or `worse`) also lies within ±m;
- `not_settled` otherwise.

**Why two margins.** The paired games per opponent needed for "little difference" at a true difference Δ are about
`n = Z95² · 0.5 · (1 − ρ) / (m − |Δ|)²`. Against one opponent at ρ = 0.5 and Δ = 0, ±2 points needs about 2,400 games
(past the 1,600 look, so nearly every test of a harmless change would end "not settled"), and ±3 points about 1,070.
Against the field the variance divides by the number of opponents k: 9 opponents × 1,600 games give a half-width of
about 0.8 points, so ±2 is reachable. The margins are an owner question (§0.6).

**Adaptive.** `paired_look` applies §7.3's bounds to this z: `HP_INTERIM` at interim looks, `HP_FINAL` at the last
reachable look, and `HP_INTERIM` for a stopped look and for every look made before "Play more" extended a test
(§11.4). The "little difference" exit is at ±m.

**Against the field.** Δ_F is the mean over opponents of Δ'_j, and SE_F = sqrt(Σ Var_j)/k, where Var_j is the
stratum-combined variance above. The opponents are independent because each pair has its own stream.
- The verdicts are the same, with HP looks at `FIELD_PAIRED_LOOKS` games per opponent.
- **A field look happens only when every remaining opponent has finished the stage.**
- An opponent dropped after a look (a ForgeError) is removed from every look's recomputation, so Δ_F keeps one
  meaning, and the test's summary names it.

### 7.5 Field numbers: r5 §3b

**The row.** For each opponent j: the headline balanced rate `v_j` (`views.balanced`) with its range `(l_j, u_j)`; the
decided share `π̂_j` and its SE (§7.3); `d_j`.

**The field average** (equal weights, the owner's decision), over the m opponents with games in both strata:
- `FA = (1/m) Σ v_j`;
- the range is MOVER over the equal-weight sum, like every other range on the page:
  `low = FA − sqrt(Σ (v_j − l_j)²)/m` and `high = FA + sqrt(Σ (u_j − v_j)²)/m`;
- it's marked "partial" when m is less than the field's size;
- the Wald `SE_FA = sqrt(Σ SE_j²)/m` (independent pairs, per-pair streams) is kept for the harness only.

**Bradley-Terry with a starter term** (r5's `bt.py`):
- **Data:** `{(i, j, i_started): [i's wins, decided games]}` over every current-engine, decklab-kind result of the
  format (§10.4). The players are side ids.
- **Model:** `logit P(i beats j | i starts) = β_i − β_j + h`.
- **Fit:** penalised Newton-Raphson maximising `LL(β, h) − Σ_i β_i²/(2·BT_PRIOR_SD²)`, with h unpenalised and **no β
  fixed**. The penalised Hessian is positive definite, and because the likelihood's gradient in β sums to 0, the
  maximum has Σβ = 0 whatever the players' order. At most 60 iterations, stopping when the largest step is under
  1e-10.
- **Scope:** only the connected component that holds the assessed list. Players outside it are "not rated: no games
  link them".
- **Covariance:** Σ = the inverse of the full penalised information (all β and h).
- **Dispersion:** `φ = max(1, X²/df)`, with X² Pearson's over the (i, j, starter) cells that have decided games, and
  `df = cells − (players − 1) − 1` (at least 1). r5 found G² = 169.9 on 14 df (φ about 12): matchups aren't
  transitive, so a binomial-only range would be far too narrow.

**Rating:**
- Centred on the field: `c_i = β_i − mean(β over the field lists in the component)`, with
  `SE(c_i) = sqrt(aᵀ Σ a)`, `a = e_i − (1/m_F)·1_F` over the m_F field lists F in the component.
- Shown as the win chance against an average field deck, `R_i = ½[σ(c_i + h) + σ(c_i − h)]`. Its range is
  `c_i ± Z95·sqrt(φ)·SE(c_i)` through the same increasing map.
- **Rank** among the field lists in the component, by c. **Its range:** `BT_DRAWS` draws of β from
  N(β̂, φΣ) (a Cholesky factor, `random.Random(1)`), ranking the field lists by c in each draw; the 2.5 % and 97.5 %
  percentiles of the assessed list's rank. The page shows "3rd of 10 (likely 2nd-5th)".
- The starter term is shown as "going first is worth X points of win rate in these games", with X = 100·(σ(h) − ½).

**Prediction:** `pred_ij = ½[σ(β_i − β_j + h) + σ(β_i − β_j − h)]`.

**Residual flags** (r5's leave-one-pairing-out residual):
- Refit without pairing (i, j), warm-started from the full fit (a few Newton steps). Then `r_j = π̂_j − pred_ij(−ij)`.
- `Var_j = SE_obs_j² + gᵀ Σ_(−ij) g`, with g the gradient of `pred_ij` in (β_i, β_j, h) at the refit, and SE_obs from
  §7.3. No φ scaling here: the matchup-specific part is what the flag looks for.
- When removing the pairing splits the component (the pairing is a bridge), there's no flag for it.
- `z_j = r_j/sqrt(Var_j)` and a two-sided p_j. The flags are the Benjamini-Hochberg discoveries at `RESIDUAL_FDR`
  (10 %) among the assessed list's m p-values (`cardstats._discoveries`' procedure), that also have
  |r_j| ≥ `RESIDUAL_POINTS`: "strong against" when r_j > 0, "weak against" when r_j < 0.
- The page keeps the caveat that a rating predicts a pairing it hasn't seen only to about ±8 points (r5's
  leave-one-out RMSE was 7.7).

**APT pick:** `apt_pick(rows, k)` returns, among the eligible rows (n_j < FIELD_CAP, not in flight, meaningful), the k
smallest `sqrt(n_j)·(|π̂_j − 0.5| + APT_EPS)`. Ties go to fewer games, then to the opponent id.

**`spearman(xs, ys)`,** with average ranks for ties, for the harness.

**Per-card numbers from field runs** (said in F's and `field.view`'s docstrings): a field run's games are ordinary
matchup results, so `cardstats.list_cards` pools them with Mantel-Haenszel weights n_in·n_out/N per stratum. APT gives
close matchups more games, so the deck page's per-card difference leans toward close opponents. That's valid per
stratum, but it isn't the field average's equal-weight estimand.

### 7.6 The anytime-valid range (built now)

`anytime_range(games, p) -> (value, low, high)`, on the raw share x̄ = p's wins / n (non-wins count as losses).
- Each game's starter is a fair coin flip, so x̄ is an unbiased estimate of the balanced rate from i.i.d. games. (Seats
  alternate every 25 games; stages and looks end on block boundaries.)
- r5's normal-mixture confidence sequence, tuned for 1,600 games:
  ```
  V = n/4
  half = sqrt((V + AV_RHO) · ln((V + AV_RHO) / (AV_RHO · AV_ALPHA²))) / n
  ```
- Half-widths: 8.2, 5.5, 3.8 and 2.7 points at 400, 800, 1,600 and 3,200 games, about 1.55-1.67 times the fixed range.
- It holds at every n at once. So it's the range the live box shows while a run plays (§9.4), and the range a run
  stopped between looks reports (§14.1).

### 7.7 Not built

- Equal-weight per-card pooling over field opponents (`RD = (1/k) Σ d_k`, `Var = Σ Var_k/k²`). Documented as the
  alternative in F's docstring (§7.5); the deck page keeps wave 1's Mantel-Haenszel pooling.

### 7.8 The frozen names (the base's `seqstats.py`)

The base commits every name below with its docstring and a `NotImplementedError` body; S fills them and may add private
helpers. A, F, V, X and H call only these. The constants are §7.1's, plus `DECISIONS` (`continue`, `ahead`,
`slightly_ahead`, `about_even`, `not_settled`, `not_settled_stopped`) and `PAIRED_VERDICTS` (`better`, `worse`,
`slightly_better`, `slightly_worse`, `little_difference`, `not_settled`). `VARIANT_EQUIV_FIELD`/`_ONE` hold the config
defaults; V reads the config for the margin it passes.

| Function | Returns |
|---|---|
| `assess_estimate(games, p)` | int: the page's planned total before the pilot (§7.2) |
| `assess_next(games, p, h=ASSESS_HALF_WIDTH, cap=CAP, topups_done=0, *, plan_done=None)` | `(more, reason)`; reason `pilot`, `precise`, `capped`, `plan`, `top-up`, `capped at plan` |
| `decided_share(games, p)` | `{"pi", "se", "z", "a": [play, draw], "b": [...], "d": [...]}` (None values when undefined) |
| `last_look(max_games=CAP, looks=HP_LOOKS)` | the last entry of looks ≤ max_games, or None |
| `look(games, p, n_total, *, max_games=CAP, stopped=False)` | `{"look", "z", "bound", "low", "high", "decision", "side", "basis"}`; side 0 is p; basis `decided`, `comparison`, `decided_share` or None |
| `ahead_next(games, p, *, max_games=CAP)` | `(more, next_look)`; `(0, None)` when no look is left |
| `anytime_range(games, p)` | `(value, low, high)` or None |
| `paired_games(base_games, paired_games_, base_side, variant_side)` | `{"pairs": [{"g", "y_base", "y_variant", "variant_first", "same"}], "common", "starter_mismatch"}` |
| `paired_diff(base_games, paired_games_, base_side, variant_side)` | `{"delta", "low", "high", "z", "var", "n", "rho", "same", "unpaired": {"delta", "low", "high"}, "saved_share", "starter_mismatch": {"games", "of"}, "strata": {"play": {"b", "c", "n"}, "draw": {...}}}` |
| `paired_field(diffs)` | `{"delta", "low", "high", "z", "se", "k"}` or None |
| `paired_verdict(low, high, margin)` | one of `PAIRED_VERDICTS` |
| `paired_look(diff, games_per_opponent, *, looks=PAIRED_LOOKS, max_games=None, margin=VARIANT_EQUIV_ONE, stopped=False, interim=False)` | `{"games_per_opponent", "delta", "low", "high", "z", "bound", "interim", "stopped", "decision"}` (§14.3's look) |
| `field_row(games, p)` | `{"n", "value", "low", "high", "pi", "se", "d"}` |
| `field_average(rows, of=None)` | `{"value", "low", "high", "counted", "of", "partial", "se_wald"}` or None |
| `bt_component(data, player)` | set of players |
| `bt_fit(data, *, prior_sd=BT_PRIOR_SD)` | `{"players", "beta", "h", "cov", "phi", "x2", "df", "iterations", "converged"}`; data `{(i, j, i_started): [i's wins, decided]}` |
| `bt_predict(fit, i, j)` | float |
| `bt_rating(fit, player, field_players)` | `{"value", "low", "high", "c", "se", "rank", "rank_low", "rank_high", "of", "h_points"}` |
| `residual_flags(data, fit, player, observed)` | `[{"opponent", "r", "z", "p", "flag": "strong" / "weak" / None}]`; observed `{opponent: (π̂, SE_obs)}` |
| `apt_pick(rows, k)` | list of ids; rows `{"id", "n", "pi", "inflight", "meaningful"}` |
| `spearman(xs, ys)` | float or None |

---

## 8. Run-loop hooks (R)

`runner.run` gains keywords. The base freezes the signature, R implements it, and W2's behaviour holds when they're
absent:
```
run(entry_a, entry_b, games, *, by, progress=None, results_dir=None, workers=None, batch=None, seed_base=None,
    a_first=False, save=True, local=False, pool=None, exact=False,
    numbers=None, seeds=None, key=None, kind=None, extra=None, override_sets=None, log_dir=None, log_every=1)
```
It returns the saved result (W2), whose `"key"` the coordinators check (§1).

**`runner.RUN_FEATURES`** (a frozenset; the base ships it empty, R fills it with `"numbers"`, `"seeds"`, `"key"`,
`"kind"`, `"extra"`, `"override_sets"` and `"log_dir"`). V's and X's tests that need R skip until it's filled (§21).
The base's `run` takes every keyword and raises `NotImplementedError` when one not in `RUN_FEATURES` is passed (not
None); `log_every` alone does nothing. `request_args(..., pilots=None)` is in the base with the same rule (E3 builds
it). `seeds=`'s stream is the result's 16-hex string, and the keyword hides the `seeds` module inside `run` (§2.1 row
10). The chunk reader and request builders R changes are `pool.Pool._line`, `Pool._send`, `Pool._start`, and the pool
service's `_wire`/`_service_job` (§2.1 rows 7-8).

**The new keywords:**
- **`numbers`:** a sorted list of distinct game numbers ≥ 0 to play, instead of `[next_game, next_game + games)`.
  - `games` must equal `len(numbers)`.
  - Chunks are cut at seat blocks and at gaps, since a request covers consecutive numbers.
  - `next_game` becomes `max(next_game, max(numbers) + 1)`.
  - **Holes below `next_game` (the one exception to W2 §9):** W2 never plays a stopped run's unplayed numbers later.
    `numbers` may name numbers below `next_game` that the result doesn't hold **only when `kind` is `"paired"` or
    `"experiment"`**: results whose games are chosen to match another result's g. A paired arm that was stopped, or had
    a failed chunk, can then still be filled to its base's numbers.
  - Refused (ValueError): numbers the result already holds; and, for a matchup (`kind` None), any number below
    `next_game`.
- **`seeds`:** `{"base", "stream", "flip"}` for a new result (a paired result, an experiment arm, or a harness run
  with a shared stream).
  - For an existing result they must equal the stored ones (ValueError).
  - Without it, W2's rules apply: base `seed_base`, else `DECKLAB_SEED_BASE` (below), else 1; stream `stream_of`;
    flip from `a_first`.
- **`key`:** the result's key (default `engine.key(a, b, eng)`). Experiment arms and harness scratch runs pass their
  own, so their results never share a key with a matchup.
- **`kind`:**
  - None: a matchup.
  - `"paired"`: saved as `<results_dir>/paired/<key>.json`, so matchup listings, which read only the top level, never
    see it.
  - `"experiment"`: saved as `<results_dir>/<key>.json` with `"kind": "experiment"`. Experiment results live only in
    experiment and probe folders; `replay` and `staged-move` skip any file of this kind.
- **`extra`:** a dict merged into the top level of a new result (the `paired` block, §14.2). It may not name a result's own
  fields (`RESULT_FIELDS`), `paired_version` or any `engine.result_fields(eng)` key: ValueError before anything is
  claimed.
- **`override_sets`:** a list of override set names. The run plays in `overrides.user_dir_for(override_sets,
  performance_mode=<config>)` (`setup["user_dir"]`, `setup["override_sets"]`) instead of the real user folder.
  `ensure_deployed` and `engine.current` then work on that folder (§6.2), so the key, the side ids and the launch
  identity are the arm's, and its workers keep its files. None: the real user folder (W2).
- **`log_dir`, `log_every`:** the request output (between `begin` and `end`, with the DLSERVE lines dropped) of
  every chunk in a **seat block (25 games) whose block number is a multiple of `log_every`** (games 0-24, then
  25N to 25N+24, ...; not every Nth chunk, since the pool cuts chunks by queue size) is written gzip-compressed to
  `<log_dir>/<key>/<first g>-<last g>.log.gz`, so every result tees the same game numbers. One-shot fallback
  chunks are written the same way. The files are written by short-lived `pool-log-tee` threads, off the pool's
  lock; a run's "done" waits for them, so they all exist once `run()` returns (after a Stop, one may land just
  after). Off by default. (About 25-34 KB a game before compression; the combined run tees
  every chunk of its replay, about 150 MB compressed.)

**Other changes:**
- **`ensure_deployed` first:** `run` calls `overrides.ensure_deployed(setup["user_dir"])` before `engine.current`
  (§6.2).
- **Side order and pilots:** entries are ordered by `engine.side_list(entry, eng)` with Python's sort (§4.1), the same
  order as the key's sides, so a pilot mirror has one order.
  - Stored side i always holds that side's pilot.
  - The chunk planner takes each seat's `-a` profile and `-dlpilot` switches from the stored side that
    `deck1_side(g, flip)` puts in the seat, never from the order the caller passed.
  - `pilots.check_switches(eng, pilot)` runs for both sides before anything plays.
  - A test plays a pilot mirror twice with the entries swapped: one result, and the pilots never swap seats.
- **The echo check's call site:** the chunk reader (W2 PP's code in `runner`/`pool`, now R's) calls
  `engine.check_echo(eng, echo, seat_pilots=[deck 1's pilot, deck 2's pilot])` in the chunk's seat order.
- **`settings.ai`:** `_record` writes the sides' pilot profiles in side order (§5.4).
- **`dck_file`:** an entry may carry a file name for its .dck (default `<card_sha>.dck`) along with its own `dck`
  text. `_write_decks` writes that name (named by the text's sha), so an aligned variant never overwrites the list's
  sorted .dck. It must be `sha256(the dck text as UTF-8)` + `.dck`, or `run()` raises ValueError.
- **`runner.update_result(key, results_dir, fn, paired=False)`:** claims the matchup lock (W2's `_claim`; on BUSY it
  waits up to 30 s), loads the result, applies `fn(result)`, writes it atomically and releases the lock. A uses it for
  adaptive summaries, and F for field-run notes.
- **`saved._is_result`:** accepts `kind: "paired"` with its `paired` block (§14.2), `kind: "experiment"`, and a
  top-level `adaptive` list (§14.1), and keeps every W2 rule.
- **Pool:** the launch identity and the compatibility identity gain `engine.launch_fields(setup, eng)` (§4.3). The
  CLI's stderr line names the field that differs.
- **`cores`:** `DECKLAB_PIN_MODE` (harness only) is one of:
  - `core`: the default, as in W2;
  - `none`;
  - `ccd`: the mask of every logical CPU sharing the slot's core's L3;
  - `core-wrap`: slot k → core k mod the number of cores, for K > 16.
- **`config.load()`:** merges the JSON file named by `DECKLAB_CONFIG_EXTRA` over `config.json` (harness only; one log
  line names the file).
- **`DECKLAB_SEED_BASE`** (harness only): a new result's base when `seed_base` isn't passed. It only affects runs
  planned in that process. The combined run sets it on a test server so the page's API field run starts at base 2,
  independent of staging's base-1 results (COMBINED-RUN.md D3a), and on its filler replay (base 5).
- **Stop file:** when the environment variable `DECKLAB_STOP_FILE` names a file that exists, every `runner.run` in that
  process stops as the page's Stop stops it (finished games saved, W2 §9). It checks at each progress tick, about once
  a second. The harness uses this to stop a child gracefully (COMBINED-RUN.md §5.1). Coordinators stop because their
  runs raise `common.Stopped`.
  A run started while the file exists raises `common.Stopped` (`saved_games` 0) before it claims, sends or saves
  anything. A stopped run stops the whole `replay` command: no other matchup starts, and it prints "Stopped..." and
  **exits 130**, as Ctrl+C does. For the harness (H), a 130 exit after it wrote the STOP file is the expected end of a
  preempted item, not a failure.
- **CLI:** `_log_args(parser)` adds `--logs-dir` and `--log-every` to `play`, `replay`, `field`, `variant` and
  `experiment`. The base ships it as a stub that adds nothing, so A, F, V and X can call it before R merges.

---

## 9. R12 adaptive runs (A: `decklab/lib/forge/adaptive.py`)

### 9.1 Modes

- **`fixed`:** today's runs of 200, 400, 800, 1,600 or 3,200 games, kept on the page and in the CLI. Their lead word is
  the plain one, as in wave 1.
- **`assess`** (the default for a new run, the owner's decision): §7.2. A 400-game pilot (or what the result already
  has), then the planned rest in one stage, then at most one top-up. It stops at a half-width of 3 points or less, or
  at 3,200 games.
- **`ahead`:** §7.3. Stages up to each look at 400, 800, 1,600 and 3,200 games (or up to `max_games`). It stops at an
  HP boundary, or at the "about even" exit.

### 9.2 Stages

`run_adaptive(entry_a, entry_b, mode, *, by, progress=None, results_dir=None, pool=None, local=False, seed_base=None,
max_games=3200, log_dir=None, log_every=1)`:
1. Load the current-engine result: n games, with side p entry_a's.
2. Loop:
   - `more = assess_next(...)` or `ahead_next(...)`; 0 stops the loop;
   - otherwise `res = runner.run(entry_a, entry_b, more, exact=True, pool=pool or the session, ...)`;
   - **the first stage's `res["key"]` is the run's key**; a later stage that returns another key stops the run with
     "The engine changed during this run: play it again." (§1);
   - the stage ends only when every one of its games has finished (W2's run returns after its last chunk), so a look
     never sees a subset biased toward short games (r5 §1.7);
   - then load the result and look at all its games.
3. **At the end,** `runner.update_result` appends the summary (§14.1) to the result's `adaptive` list.
   - **A Stop** (W2's Stop: finished games are kept) makes one more look on the games played, with `stopped=True`
     (§7.3: "ahead" only at |z| ≥ 3.0, "about even" only on the 99.73 % range). It's recorded as the summary's last
     look, with `"outcome": "stopped"`, its `decision` and the anytime-valid range (§7.6). Then the Stop is raised
     again.
   - An error records `"error"`, and is raised again.
4. **Progress:** `progress(done, total, detail)`, where `total` is the end of the current plan (it grows at each
   stage). `detail` is W2's plus `plan`: `{"mode", "stage", "next_look", "max", "planned", "games_before"}`, and
   `range`: the anytime-valid range of the result's games so far.

Workers idle at a stage's tail take other queued runs' chunks (W2's single queue). A matchup playing alone loses about
10 s at most per stage boundary (W2's CHUNK_MIN of 5 at tails).

### 9.3 API and CLI

- **`POST /api/matchup/run`:** the body gains `"mode": "fixed" | "assess" | "ahead"`. The default is the profile's
  `matchup_mode`, else `assess`. `"games"` is read only with `fixed`. A bad mode is a 400.
  - **Joining:** when a run of the same key is already queued or playing, W2 joins it. The answer then says so, with
    the mode it plays: `"joined": {"mode": "assess", "by": "..."}`. The page says "Joined the run already playing
    (until the win rate is within ±3 points)", never silently ignoring the mode asked for.
- **`_MatchupRun`** calls `adaptive.run_adaptive` for `assess` and `ahead`. The job snapshot's detail carries `plan`
  and `range`.
- **`GET /api/matchup`:**
  - `job.plan` and `job.range` (above);
  - `result.adaptive_last`: the result's last adaptive summary, while the result's game count is still that run's
    `games_to`; else null, because later games make the plain view the one that counts;
  - **the lead word:** while `adaptive_last` applies, `views.view` sets `result.lead` from
    `adaptive.lead_from_summary(adaptive_last)` (the base's wiring; A's function): the summary's decision in `_lead`'s
    shape, `{"verdict", "side", "basis": "adaptive"}`. So the headline word never contradicts the run's outcome, and a
    stopped run shows "not settled" unless it passed 3.0;
  - `estimates`: `{"fixed": {"200": [low, high], ...}, "assess": [low, high], "ahead": [low, high]}` minutes, from
    `estimate.py` (§9.5).
- **Profile setting** `matchup_mode` (`assess` | `ahead` | `fixed`; default `assess`), saved like `matchup_games`.
- **CLI:** `play A B --until assess|ahead [--max N]`. `--games` is refused with `--until`. For `ahead`, N is rounded
  down to an `HP_LOOKS` entry, and the look at N uses `HP_FINAL` (§7.1). It prints each look, for example "Look at 800
  games: z = 2.41 < 3.00, going on to 1,600".

### 9.4 Page (matchups.js)

- **Play box:** a radio group, "What do you want to know?":
  1. "How well does this deck do here?", with the sub-line "Plays until the win rate is known to within ±3 points of
     win rate: 400 games first, then as many as needed (usually 700-1,100, at most 3,200)".
  2. "Which deck wins?", with the sub-line "Plays until one deck is clearly ahead, or they're about even (within 5
     points of win rate). Checks at 400, 800, 1,600 and 3,200 games".
  3. "A set number of games", which shows the existing 200 to 3,200 segmented control.
  - Each shows a rough time from `estimates` ("about 2-6 minutes").
  - The button reads "Play".
- **Live box:**
  - the progress bar runs to the current plan ("400 of up to 3,200");
  - the live win bar is dashed and shows `job.range` (the anytime-valid range), labelled "Live range: wider while
    games are still being played";
  - a line says "Next check at 800 games" (ahead) or "Planned: 1,100 games for ±3 points" (assess);
  - no verdict words appear while the run plays;
  - Stop keeps the games and says "Stopped early: the result shows the games played so far."
  - **When a field run or a variant test is playing this matchup** (`job.via`, §10.5): the box shows that job's
    progress for this pair and, in place of Stop, "Part of a field run of Mono-White Angels: open it to stop or follow
    it", with a link (A's `liveBox`).
- **Result:** when `adaptive_last` is present, the "How these games were played" part (`howPart`) adds one of:
  - "This run stopped at a planned check after 1,600 games: Izzet Prowess is clearly ahead.";
  - "...the win rate is known to within ±2.8 points of win rate.";
  - "...the decks are about even (within 5 points of win rate).";
  - "...it reached 3,200 games without a clear leader.";
  - "Stopped early after 650 games, between checks. A range that allows for stopping at any time: 49-62 %. Not
    settled." (or "...Izzet Prowess is clearly ahead even so." when |z| ≥ 3.0).
  - The z numbers go in a small details line ("z = 3.4; needed 3.0").
- **Devices** (`devices.css` breakpoints, 700 and 1,600 px):
  - phone (below 700 px): the radios stacked full width, with the segmented control below;
  - iPad (700-1,599 px): the same, in the right column of the matchup page's grid;
  - QHD (1,600 px and up): the radios as one row of three cards.

### 9.5 Time estimates (A: `decklab/lib/forge/estimate.py`, new)

One estimator, server-side, for the matchup play box (A), field budgets (F) and the test sheet (V):
- `estimate.pair_rate(entry_a, entry_b, results_dir=None) -> games a minute`:
  - from the pair's saved v2 results (games ÷ wall time of their pool runs), when there are any;
  - else from its v1 results' median Forge ms per game, divided by the warm speed-up;
  - else the format's slow class (Constructed `board`, Commander `commander`).
- `estimate.minutes(pairs_games) -> (low, high)`: the sum over pairs, with the high end assuming the slower rate of the
  two sides' classes and a 20 % allowance for stage tails.
- **The rates** (games a minute at 16 warm workers, per class, and the warm speed-up) live in
  `<data>/forge/rates.json`. The combined run's report writes it (`overnight.py report --write-rates`); a post-run step
  copies it to main (COMBINED-RUN.md §10). Until then the defaults are W2's measured ones: fast 1,400, medium 900,
  board 280, Commander 200, speed-up 2.0.
- The page's wave 1 constants (`batchPlan`, `PROCESS_GAMES_PER_MIN`) stay only as the fallback when the server sends
  no estimate.

---

## 10. R13 field view (F: `decklab/lib/forge/field.py`)

### 10.1 The field: the current decks of a format

`field.field_lists(fmt) -> [entry]` is worked out again for every request (it's cheap and uses `decks.list_decks()`).

**What's in it:**
1. **Every deck file of the format,** with one list each: the Built version when the deck is `built` and has that
   line, else the target list.
   - `magic/decks/casual/*.md` are Constructed, and `commander/*.md` are Commander.
   - Owned-only lists aren't separate members: near-duplicates would double a deck's weight in an equal-weight average.
2. **Product decks of the format** whose `products/status.csv` row is `owned`, `preordered` or `ordered`, and whose
   `intact` is `yes`.
   - A blank `intact` means "not decided yet" (AGENTS.md: blank until it arrives), so such a product is left out until
     the owner sets it. `field.<fmt>.add` can still put it in.
   - Today that's Lightning Aggro. The two FDC precons are preordered with a blank `intact`, so they're out.
   - When a precon is kept whole and a house deck was also built from it (Calling All Angels and Giada, for example),
     name one of them in `field.Commander.remove`, so a near-duplicate doesn't count twice.

**What's left out:**
- Beginner Box halves and pairings, and broken-up products (BLB Hare Raising, Otter Limits), unless `simulation.json`'s
  `field.<fmt>.add` names them (`"<deck id>[@version]"`). `remove` takes a list out.
- A deck file with errors, with a note.

**Opponents.** The opponents of an assessed list D are the field minus every list with D's deck id. D can be any list:
a field list, an owned-only list or a product deck.
- Today the Constructed field has 10 lists (9 casual decks + Lightning Aggro), so a casual deck has 9 opponents.
- The Commander field has 3 lists today: Giada, Finneas and Gisa.
- Results flagged "not meaningful" (wave 1: a commander the AI never casts, such as Gisa's) are listed but left out of
  the average and the Bradley-Terry fit.
- `--opponents a,b,...` (CLI) and `opponents=` (API of `run_field`) limit the field to those lists, for checks and
  the harness.

### 10.2 Reusing saved results; per-pair seeds

- A field run is a set of ordinary matchup runs. Each pair (D, O_j) plays under that pair's own key, stream (W2's
  per-pair `stream_of`, so no correlation across opponents) and base.
- Its games stay that matchup's results.
- Existing current-engine games count toward the floor and the allocation.

### 10.3 The field run (a coordinator)

`run_field(entry, budget="standard", *, by, progress=None, results_dir=None, pool=None, local=False, seed_base=None,
log_dir=None, log_every=1, inflight=None, opponents=None)`.

**Budgets:**

| Budget | What it plays |
|---|---|
| `quick` | the floor only: 200 games per opponent |
| `standard` | the floor, then APT allocation until Σ min(n_j, 1,600) = 400·m |
| `thorough` | the floor, then APT until that sum = 800·m |
| `fixed:N` | every opponent topped up to N games, without APT (the harness's reference) |
| an int | the total per opponent, with APT (CLI and harness) |

**Order of play:**
1. **Floor:** for each j with n_j < 200, `runner.run(D, O_j, 200 − n_j, exact=True, ...)`.
2. **Rounds:**
   - `apt_pick` with k = the free run slots; each pick plays `FIELD_STEP`, 100 games;
   - at most `inflight` pair runs at once (config `forge_field_inflight`, 4: 4 × 100 games keeps 16 workers busy);
   - each pair run on its own thread, in one pool session (the server's pool, in the server);
   - each finished run triggers a new pick.
3. **One engine:** the first run of each pair fixes that pair's key; a later run returning another key stops the field
   run with the sentence of §1.

**Failures and stopping:**
- A pair whose run raises BUSY (the page is playing it) is tried again once, after the others.
- A ForgeError (unknown cards, say) marks that opponent "couldn't be played: <sentence>", and drops it.
- **Stop** (the field page's Stop, or Ctrl+C) stops every pair run (W2's Stop: finished games are saved), then the
  coordinator.

**Progress:** `done` is the new games, and `total` the plan's new games (floor plus allocation). The detail is frozen
(A's `_job_json` and F's `_job_for_key` both read it):
```jsonc
{"budget": "standard", "phase": "floor" | "allocate", "deck": {"id", "version", "title"},
 "pairs": {"<matchup key>": {"opponent": {"id", "version", "title"}, "done": 140, "total": 200,
                             "wins": 77, "other": 3, "playing": true}}}       // wins and other from D's side
```

**Notes:** after the run, a note is appended to `<results_dir>/field/<entry card_sha>-<fmt>.json`, in the way
`runner.update_result` writes: `{"runs": [{"when", "by", "budget", "planned", "played", "wall_s", "stopped",
"per_opponent": {key: games}}]}`.

### 10.4 The view

`field.view(entry, results_dir=None) -> dict` (§15) holds:
- the row, the average, the Bradley-Terry fit, the rating and its rank range, and the residual flags;
- coverage (`"7 of 9 opponents with 200+ games"`);
- the last field run's note.

The Bradley-Terry data:
- every saved result of the format in the results folder for which `engine.is_current(result)` is true, and of
  decklab kind (never paired or experiment results). That's all lists, current or not, because more lists connect more
  pairings;
- decided games only;
- the players are side ids, and the assessed list's id is `engine.side_id(entry)`.

### 10.5 API and CLI

- **`GET /api/field?id=<deck id>&version=target|owned[&profile=]`** returns the view, plus:
  - `status`: "none", "queued", "running" or "done";
  - `job`: the progress (§10.3's detail), with `by` and `started`;
  - `budgets`: `{"quick": {"games", "minutes": [low, high]}, ...}`, from `estimate.py`;
  - `field_lists`.
- **`POST /api/field/run {"profile", "id", "version"?, "budget"?}`:** the budget defaults to the profile's
  `field_budget` (`standard`). A `COORD_JOBS` job, key `field:<card_sha>:<fmt>`; the 503 rules are `run_matchup`'s,
  applied to `COORD_JOBS`.
- **`POST /api/field/stop {"profile", "id", "version"?}`.**
- **The base's names** (`api/field_page.py`, re-exported by `api`): `field_view(deck_id, version="target",
  profile=None)`, `run_field(body)`, `stop_field(body)`; each answers ApiError 501 until F builds it. The server answers
  202 when the answer's `status` is `queued` or `running` (GET and both POSTs), else 200. `/api/field/run`'s body may
  be up to the editor's limit; `/stop`'s is `MAX_BODY`.
- **`GET /api/matchup` for a key that a field (or variant) job is playing** (`api.forge_runs._job_for_key`, F):
  - `status` "running";
  - `job`: that pair's record from the owning job's `pairs` (done, total, wins, other), so the page's bars move;
  - `job.via`: `{"kind": "field" | "variant", "job": <the job's key>, "title": "Field run of Mono-White Angels",
    "link": "#/deck/<id>?version=<v>#field" | "#/variant?test=<id>", "by"}`.
  - The matchup page's Stop is replaced by the link (§9.4). `POST /api/matchup/stop` for such a key answers 409 with
    "This matchup is playing as part of <title>: stop it there."
- **Running jobs on lists:** `_running_json` (A) lists `COORD_JOBS` jobs as well as matchup runs:
  `{"key", "kind": "matchup" | "field" | "variant", "title", "by", "done", "total", "link"}`. The matchups list's
  "Running" group and the deck page show them with links.
- **CLI:** `field <deck> [--owned] [--budget quick|standard|thorough|N] [--fixed N] [--opponents a,b,...] [--show]
  [--dry-run] [--json] [--local] [--results-dir D] [--seed-base N] [--logs-dir L] [--log-every K]`.
  - `--show` prints the view without playing;
  - `--dry-run` prints the plan and its time.

### 10.6 Page: the deck page's "Against the field" section

New files `web/field.js` and `web/field.css`. **Every class in them starts with `fv-`**: the editor already uses
`.field`, `.field-grid`, `.field-wide`, `.field-hint`, `.field-note`, `.field-problem` and `.field-fixed`, and
`devices.css` styles `.field-grid`. The section comes after Matchups on the deck page, with "Field" in the section nav.
- **Headline:**
  - "Against an average house deck: 54 % (51-57)", with a win bar;
  - "Rating: 3rd of 10 (likely 2nd-5th)";
  - "Going first is worth about 3 points of win rate in these games", in small text;
  - with partial coverage: "Based on 6 of 9 decks; play the field to fill it in".
- **Strong and weak chips:** for example "Strong against Lightning Aggro: wins 12 points of win rate more than its
  rating predicts" (the residual flags), each linking to that matchup.
- **The row:** one line per opponent, sorted by win rate:
  - the opponent's name, as a link;
  - a win bar with a tick at the rating's prediction;
  - the games;
  - the lead verdict's word (wave 1's `_lead`);
  - not-meaningful rows are greyed, with the reason.
- **Play box:** "Play the field", with a segmented control **Quick / Standard / Thorough** and, under it, a sub-line
  for the chosen budget: "about 400 games a deck · about 25-40 minutes" (from `budgets`). Play and Stop.
  - While it plays: overall progress, "Playing: Izzet, Gruul (2 waiting)", a mini bar per opponent that fills up, and
    "Started by <profile>".
- **Trust note** (in wave 1's R19 style): "A rating predicts a matchup it hasn't seen only to about ±8 points of win
  rate: the row is the real answer."
- **Devices:**
  - phone (below 700 px): one column, with rows like the deck page's result rows;
  - iPad (700-1,599 px): rows in two columns from 900 px;
  - QHD (1,600 px and up, the whole-width layout): a table (opponent, win bar with tick, games, verdict, residual)
    beside the headline tiles.

---

## 11. R15 paired variant tests (V: `decklab/lib/forge/variants.py`)

### 11.1 What a test is

- **A base list B:** a deck id and version, as the list is today.
- **A variant V:** B with some cards changed in Main or Commander. It keeps the same Main count, and for Commander the
  same count in the Commander section. Sideboard changes aren't tested (best of one, the owner's decision).
- **Opponents:** one list, or the field (§10.1, minus B's deck id), optionally limited with `--opponents`.

### 11.2 The aligned .dck writer

`variants.aligned_dck(base_entry, variant_cards) -> (dck_text, changes)`:
1. Start from the base's canonical lines (W2's `_list_text`: merged, sorted by name, with the Commander section first
   for Commander decks).
2. Take removed = B − V and added = V − B, as multisets of Forge names. Refuse unequal totals ("A tested change must
   keep the deck's size: N cards out, M in").
3. Pair the removed copies with the added copies in a fixed order: removed copies in base line order, taking each
   line's copies from its last; added copies sorted by name; then zip them.
4. Write each base line L with `qty_L − removed_L` copies (dropped at 0). Right after it, write one line per added name
   assigned to L's removed copies, in assignment order.
   - A name that's already elsewhere in the deck still gets its own line here. DeckOrder expands lines, so duplicates
     are allowed; Forge's loader merges them in the pool, which does no harm.
   - The Commander section follows the same rule.
5. Write `Name=` as the variant's canonical card_sha[:12].
6. Return the text, and `changes`: `{"remove": [[qty, name]], "add": [[qty, name]]}`.

**The variant entry:**
```jsonc
{"id": "variant:" + base id, "version": base version, "title": base title + " (your change)", "kind",
 "card_sha": the variant's canonical card_sha (W2's _list_text of V), "card_count", "cards": V's sections,
 "dck": the aligned text, "dck_file": sha256(aligned text) + ".dck", "pilot": the base's pilot,
 "aligned_to": the base's card_sha, "source": None}
```

### 11.3 Seeds and seats

**The base result.** For an opponent O, the base result R_B is the current-engine result of (B, O)
(`engine.is_current`). When there's none, or it's from an earlier engine, the test first plays the base: an ordinary
run, saved with the matchup's results. From R_B the test takes its `seeds` {base, stream, flip f_B}, and β, B's side
index in R_B.

**The paired result** R_P (key in §14.2) has its sides sorted as §4.1 says (the variant's side list and O's), and ν is
the variant's index. So that the variant takes the base's seat in every game:
```
f_P = (f_B + β + ν) mod 2              (the variant is deck 1 in game g  ⟺  the base was deck 1 in g)
```
The same formula pairs any two results whose side orders differ (experiment arms, §12.2; the harness's shared-seed arm).

**Stream, base and game numbers:**
- R_P's stream and base are R_B's. W2 §8 already allows a result's stream not to be `stream_of` its own sides.
- The variant plays the game numbers R_B holds, in order, up to the stage's target (`numbers=`, with R's exception for
  holes, §8). If R_P lacks some of them after a Stop or a failed chunk, the next stage fills them.
- Base games missing for a target are played first, as an ordinary base run.
- When the base result is a mirror (one list on both sides), the variant is paired with side 0.

### 11.4 Running a test

`run_test(base_entry, variant_cards, against, mode="ahead"|"quick"|int, *, by, progress=None, results_dir=None,
pool=None, local=False, log_dir=None, log_every=1, opponents=None, extend=None) -> test`:
- **It refuses** with "Tests of changes need Deck Lab's deck-order patch, which doesn't fit this Forge version yet."
  when the current engine's `game_patches` lacks `deck-order-1`: without it the two versions don't get the same games.
- **`against`:** an entry, or `"field"`.
- **`mode`:**
  - `quick`: 200 paired games per opponent;
  - `ahead` (the editor's default when it fits, §11.6): stages to `PAIRED_LOOKS` (one opponent) or
    `FIELD_PAIRED_LOOKS` (the field), with looks by §7.4;
  - an int: that many games per opponent.
- **"Play more"** (`extend=<test id>`): turns any test into `ahead` mode, playing to the next look. The looks already
  made (a quick test's 200, an int test's N, an earlier stopped look) count as interim looks at `HP_INTERIM`.
- **Per opponent, per stage:**
  1. a base top-up run, if one is needed (normal results);
  2. then `runner.run(variant_entry, O, len(nums), numbers=nums, seeds={"base", "stream", "flip": f_P}, key=vkey,
     kind="paired", extra={"paired": {...}}, exact=True, ...)`.
  - Up to `forge_field_inflight` runs play at once, across opponents.
  - The first runs fix the base key and the paired key of each opponent; another key later stops the test (§1).
  - A field look waits until every remaining opponent has finished its stage (§7.4).
- **The test** is one `COORD_JOBS` job, key `variant:<test id>`. Its progress detail has §10.3's `pairs` record, keyed
  by the paired key (and the base key while a base top-up plays), plus `{"stage", "next_look", "games_per_opponent"}`.
- **The test summary** (§14.3) is written to `<results_dir>/paired/tests/<test id>.json` after each stage.

### 11.5 API and CLI

- **`POST /api/variant/run {"profile", "id", "version", "list", "against", "mode"?}`:**
  - `list`: the edited version's sections, as the editor sends them to `/api/deck/check`;
  - `against`: `{"id", "version"}` or `"field"`;
  - `mode`: `"ahead"` or `"quick"`.
  - The draft is read with `drafts._read_draft`, so the editor's own checks apply (unknown cards, sizes). It's a 400,
    with the editor's words, when the draft doesn't pass, its size differs, or only the sideboard changed.
  - It returns the test view (§15).
- **`GET /api/variant?test=<id>`.**
- **`GET /api/variant/estimate?id=&version=&against=`:** `{"quick": [low, high], "ahead": [low, high]}` minutes, the
  high end being the worst case (every opponent to 1,600 games a deck, base top-ups included), from `estimate.py`.
- **`GET /api/variants?id=&version=`:** the tests of that deck's lists, newest first, running ones included.
- **`POST /api/variant/stop {"profile", "test"}`.**
- **`POST /api/variant/more {"profile", "test"}`:** "Play more".
- **The base's names** (`api/variant_page.py`, re-exported by `api`): `variant_view(test)`, `variant_estimate(deck_id,
  version="target", against=None, against_version=None)` (the query is `?id=&version=&against=<deck id or field>&av=`),
  `variant_tests(deck_id, version="target")`, `run_variant(body)` (body up to the editor's limit), `stop_variant(body)`,
  `more_variant(body)`; each answers 501 until V builds it. `GET /api/variant` and the three POSTs answer 202 when the
  answer's `status` is `queued` or `running`.
- **CLI:** `variant <deck> [--owned] (--remove "N Name")... (--add "N Name")... | --list <decklist file> (--against
  <deck> [--owned-b] | --field [--opponents a,b,...]) [--until ahead | --games N] [--json] [--local] [--results-dir D]
  [--logs-dir L] [--log-every K]`.

### 11.6 Page

- **Editor:**
  - **When "Test" applies:** while Main or Commander differs from the saved list and the sizes are equal.
    - Different sizes: disabled, "Keep the same number of cards to test a change".
    - Only the sideboard changed: disabled, "Sideboard changes aren't tested (games are best of one)".
  - **Where it goes:**
    - below 700 px, the bottom bar's count, checks and Save already fill the 358 px between the gutters, so the bar
      gains a second row above them, holding a full-width "Test this change" button (at least 44 px high), shown only
      while Test applies or is disabled with a reason;
    - from 700 px it sits inline before Save.
  - **Tapping it opens a sheet:**
    - the change as chips (−1 Fiery Annihilation, +1 Rabid Gnaw);
    - "Test against": "The field (9 decks)" (the default), or a deck picker;
    - "How long": "Until it's clear (up to 1,600 games a deck)" or "Quick look (200 games a deck)", each with its time
      from `/api/variant/estimate`, the first as a worst case ("up to about 1 h 50 min");
    - the default is "Until it's clear", except "Quick look" for Commander lists or when the worst case passes 30
      minutes;
    - Start.
  - The draft stays in the editor. The sheet can be closed, and the test goes on.
- **Test page** `#/variant?test=<id>` (new `web/variant.js` and `web/variant.css`; every class starts with `vt-`,
  including the editor bar's Test row):
  - the title, "Your change to Gruul Ramp (target list)", with the change chips, and "Started by <profile>, 21:04";
  - **while it plays:**
    - an overall progress bar ("1,800 of up to 14,400 games");
    - "Next check at 400 games a deck";
    - a mini bar per opponent;
    - the time left;
    - the live difference range, dashed, labelled "Live range: wider while games are still being played";
    - Stop;
    - no verdict words.
  - **the verdict sentence,** one of:
    - "Better against the field: +2.4 points of win rate (+0.6 to +4.2)";
    - "Makes little difference: within 2 points of win rate" (within 3 against one deck);
    - "Worse ...";
    - "Not settled yet after 400 games a deck";
    - "Stopped early: the result shows the games played so far".
  - per-opponent rows: a difference bar centred on 0 with its range, the paired games, and "played out the same in
    64 % of games";
  - "How this test works":
    - both versions get the same shuffles (deck-order-1), so only games where the change mattered differ;
    - whether the test stopped at a planned check, at the cap, or was stopped;
    - how much pairing saved (X % of the games), or nothing when it can't be told;
    - a warning when the starters didn't match in more than 1 % of games (§7.4);
  - actions:
    - "Play more" (to the next check; from then on it judges at each check like "Until it's clear");
    - "Back to the editor" (while the draft is still open);
    - "Save this change": opens the editor with the variant's list. When the editor already holds another unsaved draft
      for that deck, it asks first: "Replace your unsaved changes to Gruul Ramp with this tested change?".
- **Deck page:** a "Tests of changes" list under "Against the field".
  - Newest first, each like "−1 X, +1 Y: +2.4 points, not settled (field, 400 a deck)", linking to its page.
  - Running tests show as "Testing: −1 X, +1 Y (40 %)".
  - Marked "saved" when the list today equals the variant.
- **Devices:**
  - phone (below 700 px): the sheet is full screen, and the test page is one column;
  - iPad (700-1,599 px): a side sheet;
  - QHD (1,600 px and up): the test page puts the per-opponent rows beside the verdict panel.

---

## 12. R16 experiment harness (X: `decklab/lib/forge/experiment.py`)

### 12.1 Spec (JSON)

```jsonc
{"name": "etb", "games": 800,
 "pairs": [["casual/mono-black-midrange", "product/challenger-2019-lightning-aggro"], ["casual/the-free-peoples", "casual/izzet-prowess"]],
 "control": {"results_dir": "<a results folder to reuse when its engine matches>", "logs_dir": "<its tee'd logs>"},   // optional; otherwise the control is played
 "arms": {
   "etb":   {"overrides": ["etb"]},                                      // added to the adopted sets
   "none":  {"overrides": [], "replace_adopted": true},                  // no overrides at all (the Fiery pair)
   "pump":  {"pilots": {"casual/selesnya-rabbits": {"profile": "Default", "switches": ["team-pump-1"]}}},
   "reck":  {"pilots": {"casual/selesnya-rabbits": {"profile": "Reckless"}}, "sides": "a"},   // mirrors: side a's list only
   "shared":{"seeds": {"stream_from": ["casual/izzet-prowess", "casual/gruul-ramp"], "seat_of": "casual/izzet-prowess"}},  // M4
   "perf":  {"config": {"forge_performance_mode": false}}                                     // knobs (battery)
 },
 "cards": {"Massacre Wurm": {"cast_target": 0.6, "turn_target": 8.5}, "Devout Decree": {"cast_target": 0.5}},
 "measures": ["cast", "turn", "win_early", "win_drawn", "own_lost", "matchup", "speed"]}
```

### 12.2 Running

- **Arms.** Each arm plays runs of every pair with the arm's change applied:
  - override sets: `runner.run(..., override_sets=<adopted + the arm's sets>)`, or only the arm's sets with
    `replace_adopted`. The arm plays in its own user folder (§6.2), whose workers keep its files;
  - pilots go on the entries' `pilot` (checked with `pilots.check_switches`);
  - seeds go to R's `seeds` hook;
  - config knobs run in a child process with `DECKLAB_CONFIG_EXTRA`, whose `install._setup` picks a knob user folder
    when the knob is PERFORMANCE_MODE (§6.2).
- **Pairing.** Every arm's pair plays **the control result's game numbers** (`numbers=`, with R's exception for holes)
  with **`seeds={"base", "stream", "flip"}` taken from the control result**. When the arm's side order differs from
  the control's (a pilot arm on a mirror, the shared-seed arm), the flip uses §11.3's formula, so each list keeps its
  seat in game g. The shared-seed arm takes the stream, base and game numbers of the `stream_from` pair, and its flip
  puts `seat_of`'s list in the seat it has in that pair.
- **Keys and kinds.** Each arm result has key `sha256(canonical({"experiment": name, "arm": arm, "control_key":
  <the control's key>}))` and `kind: "experiment"` (§8). So arms never share a key with a matchup, and `replay` and
  `staged-move` skip them.
- **The control:** the pair's result in `control.results_dir` when `engine.is_current` and it holds the games;
  otherwise played into `<results>/control/` (ordinary results, logs at `log_every` 1). Its logs come from
  `control.logs_dir` (the combined run tees every chunk of its replay) or from X's own control runs.
- **Order:** one launch identity (user folder) at a time, its pairs at once up to `forge_field_inflight`. Arms on the
  same folder (pilot arms on the real folder) are grouped. So workers don't churn between launches.
- **One engine:** each arm's first run per pair fixes its key; another key later stops the experiment (§1).
- **Outputs:**
  - results in `<results>/<arm>/`, never in the real or staging folder. The default `--results-dir` is
    `<data>/forge/experiments/<name>/`;
  - logs in `<logs>/<arm>/`, with `log_every` 1 for arms with named cards or `own_lost` (else 10).
- **Idempotent:** running it again plays only the missing games, extending each arm's result for each pair to `games`.

### 12.3 Measures per arm, against the control

Per-game card numbers come from the tee'd logs (DL|zone and Resolve Stack lines). A game counts for a card measure only
when both the arm and the control have its log; the report gives how many games that is. The matchup win rate and speed
use the results themselves, over every paired game.

| Measure | From | Comparison |
|---|---|---|
| cast % of drawn copies, per named card | per game: copies drawn and copies cast | the arm's rate as a ratio estimator (Σ cast / Σ drawn) with a cluster SE over games, set against `cast_target`. Arm against control: per game g where the card was drawn in both arms, "cast at least once", paired by g (§7.4's Agresti-Min per pair, pooled as the mean of pairs) |
| average cast turn | per game: the turns of its casts | the difference of means, with cluster SEs over games |
| win rate when in hand by turn 3 (and when drawn) | per game: in hand by its side's 3rd own turn (the v3 rule, W2 §14), and drawn | paired: over the games g where the card was in hand early (or drawn) in **both** arms, y_arm,g − y_control,g, Agresti-Min per pair, pooled as the equal-weight mean of pairs |
| own permanents lost per cast | after each `Resolve Stack: <card> (...)` line of a named card (its spell, or a trigger naming it), the caster's own permanents moving Battlefield → Graveyard or Exile in DL\|zone lines, up to the next `Resolve Stack:`, `Turn:` or phase line | the mean per cast; the difference, with cluster SEs |
| matchup win rate | paired (§7.4), per pair, and pooled as the mean of pairs (SE sqrt(Σ Var)/k) | the paired range |
| speed | games a minute and the median Forge ms per game | the ratio |
| AI timeouts and clock stops | per 1,000 games | the rate-ratio test of COMBINED-RUN.md §9.1 MG9, arm against control |

### 12.4 Recommendations (the report says; the owner adopts)

k is the number of pairs; "clearly negative for a pair" means the pair's paired matchup z < −Φ⁻¹(1 − 0.025/k)
(Bonferroni over the pairs: 2.24 for k = 2, 2.64 for k = 6).

- **An override set gets "adopt"** when all of these hold:
  - every named card reaches its `cast_target` (point estimate), or its paired "cast at least once" rise is 20 points
    or more;
  - its win rate when in hand early is **non-inferior**: the low end of the paired difference's range is ≥ −0.03;
  - own permanents lost per cast rise by 0.25 or less;
  - no pair is clearly negative, and the pooled paired matchup difference isn't (its high end ≥ 0);
  - no new Forge script errors or "unsupported card" lines;
  - the AI-timeout rate-ratio test doesn't flag the arm.
- **It gets "don't adopt"** when any of these holds: the early-in-hand difference's high end < 0; a pair is clearly
  negative; the pooled high end < 0; a named card's cast rate's high end is under its target and its rise's high end is
  under 20 points; new script errors; the AI-timeout test flags it.
- **"More games"** otherwise, with the games per pair that would settle it.
- **A pilot gets "adopt"** when all of these hold, "don't" when one clearly fails, and "more games" otherwise:
  - the mirror test (the arm's side against the control's side in the same games) is above 50 %, with its 95 % range
    clear of 50 % (clearly fails: the high end < 50 %);
  - no reference pair is clearly negative (paired against the control);
  - its speed is at least 1/1.5 of the control's (the hybrid AI: at least 1/3).
- **Output:** `<results>/experiment.json` and `report.md`: tables per arm and per card, the recommendation, and why.

### 12.5 CLI

`experiment <spec.json> [--results-dir D] [--logs-dir L] [--control-dir C] [--control-logs-dir CL] [--only ARM,...]
[--games N] [--dry-run] [--json] [--local] [--report out.md]`.
- `--results-dir` defaults to `<data>/forge/experiments/<name>/`.
- `--dry-run` lists, per arm and pair, the games to play, and the control games that `--control-dir` doesn't hold
  (the harness counts both in its estimates).

---

## 13. R17: decided to wait for Forge 2.0.16

Not built, for these reasons:
1. **A side build is a new engine.** It means building Forge with Maven plus three unmerged PRs (#11314, #11981,
   #11366). They may conflict with each other and may change AI decisions, so the result is a new `forge` build that
   needs the full set of checks.
2. **Deck Lab's patches wouldn't fit it.** Its copies of Forge classes (AbstractMulligan, AiController,
   AiAttackController, Match) are pinned by SHA-256. A rebuilt Forge changes those class files, so the copies drop out,
   and an A/B would compare the patched engine with an unpatched side build. That isn't like with like unless every
   copy is made again for the side build.
3. **The gain is where wave 2 already helped.** The PRs speed up wide token boards (Rabbits v Vampires, Commander),
   the matchups the warm pool already helped most (no tails). And the combined run's idle budget is full.
4. **2.0.16 brings it for free.** Forge 2.0.16 (about mid-November 2026, estimate) brings whatever of these PRs is
   merged, with no fork to keep up. A Forge upgrade already means re-checking the card log, re-making the copies and a
   replay.

**Revisit** if 2.0.16 isn't out by 2026-12-15, or leaves out #11314 and #11981. Then run a one-off side-build A/B
(Rabbits v Vampires 800 and Giada v Finneas 400, for speed and winners) in an idle window, prepared outside the repo.

---

## 14. Saved data formats

### 14.1 Matchup result additions (`<results>/<key>.json`)

```jsonc
"adaptive": [{"mode": "assess" | "ahead", "key": "<the run's key>", "when": "...", "by": "...",
              "games_before": 0, "games_after": 1125, "max_games": 3200,
              "stages": [{"run": 3, "games": 400, "reason": "pilot"}, {"run": 4, "games": 725, "reason": "plan"}],
              "looks": [{"games": 400, "z": 1.82, "bound": 3.0, "low": 0.512, "high": 0.611, "decision": "continue",
                         "stopped": false}],
              "outcome": "precise" | "capped" | "capped_at_plan" | "ahead" | "slightly_ahead" | "about_even"
                         | "not_settled" | "stopped" | "error",
              "decision": "ahead" | "slightly_ahead" | "about_even" | "not_settled" | "not_settled_stopped" | null,
              "side": 0 | 1 | null, "half_width": 0.029,
              "range": {"value": 0.56, "low": 0.49, "high": 0.62} | null}]       // the anytime-valid range, for "stopped"
```
- `decision` is what `lead_from_summary` shows: an `ahead` run's last look; for `stopped`, the stopped look's (§7.3);
  for an `assess` run, null (the plain lead stands, §7.2).
- `side` is the result's **stored** side index (0 or 1) that is ahead, and `lead_from_summary` returns it as stored. The
  base's wiring (`views._adaptive_view`) maps it to the page's point of view (0: the perspective's side).

### 14.2 Paired result (`<results>/paired/<vkey>.json`)

W2's v2 result shape (§12), with:
- `"kind": "paired"` and `"paired_version": 1`;
- `seeds`: the base result's base and stream, with `flip` = f_P;
- and:

```jsonc
"paired": {"base_key": "<64 hex>", "base_side": 0, "variant_side": 1,
           "variant": {"card_sha", "dck_sha", "aligned_to": "<base card_sha>",
                       "changes": {"remove": [[1, "Fiery Annihilation"]], "add": [[1, "Rabid Gnaw"]]}}}
vkey = sha256(canonical({"paired_version": 1, "base_key", "base_side", "variant": [card_sha, dck_sha]}))
```

The base key already carries the engine, both lists and their pilots.

**Experiment results** (`kind: "experiment"`, §8, §12.2) have W2's v2 shape plus `"experiment": {"name", "arm",
"control_key"}`.

### 14.3 Test summary (`<results>/paired/tests/<test id>.json`)

```jsonc
{"test": "<64 hex>", "version": 1, "base": {"id", "version", "card_sha", "title"},
 "variant": {"card_sha", "dck_sha", "changes"},
 "against": "field:Constructed" | {"id", "version", "card_sha"}, "mode": "ahead" | "quick" | 400,
 "margin": 0.02,
 "opponents": [{"id", "version", "card_sha", "base_key", "paired_key", "dropped": null | "<sentence>"}],
 "looks": [{"games_per_opponent": 200, "delta": 0.018, "low": -0.004, "high": 0.04, "z": 1.6, "bound": 3.0,
            "interim": true, "stopped": false, "decision": "continue"}],
 "starter_mismatch": {"games": 0, "of": 1800},
 "outcome": "...", "created", "updated", "by"}
test id = sha256(canonical({"test_version": 1, "base": [id, version, card_sha], "variant": [card_sha, dck_sha],
                            "against": <...>, "mode"}))
```
"Play more" keeps the test id and changes `mode` to `"ahead"` in the summary (the id is worked out from the mode the
test was created with).

### 14.4 Field notes (`<results>/field/<card_sha>-<format>.json`): see §10.3.

### 14.5 Experiment output: see §12.2-12.4.

---

## 15. API JSON fields

| Where | Field | Owner |
|---|---|---|
| `POST /api/matchup/run` body | `mode` | A |
| `POST /api/matchup/run` answer | `joined` {mode, by} when it joined a run already queued or playing | A |
| `GET /api/matchup` `job` | `plan` {mode, stage, next_look, max, planned, games_before}; `range` {value, low, high} (anytime-valid) | A |
| `GET /api/matchup` | `estimates` {fixed: {games: [low, high]}, assess: [low, high], ahead: [low, high]} (minutes) | A |
| `GET /api/matchup` `result` | `adaptive_last` (an item of §14.1, or null); `lead` from the summary while it applies (base wiring, A's `lead_from_summary`) | A, base |
| `GET /api/matchup` `status` and `job` | "running" while a field or variant job plays the key; the pair's record (done, total, wins, other); `via` {kind, job, title, link, by} | F |
| `/api/matchups`, the deck page | `running[]` {key, kind: matchup / field / variant, title, by, done, total, link} | A |
| `sides[]` | `pilot` {profile, switches, words} | E3 |
| `forge` (status) | `overrides` {deployed: [cards], stale: [cards], hash}; `pilot_switches` | E3 |
| `GET /api/field` | `deck`, `format`; `opponents[]` {id, version, title, kind, card_sha, key, games, rate {value, low, high}, lead, pred, residual {r, z, p, flag}, not_meaningful, problem}; `average` {value, low, high, counted, of}; `rating` {value, low, high, rank, rank_low, rank_high, of, h_points, connected, dispersion}; `coverage` {with_floor, of}; `last_run`, `status`, `job` (§10.3's detail, by, started), `budgets` {quick/standard/thorough: {games, minutes}}, `field_lists`, `notes` | F |
| `GET /api/variant` | `test` (§14.3); `opponents[]` with paired {delta, low, high, n, rho, same, starter_mismatch, unpaired {delta, low, high}, saved_share}; `field` {delta, low, high} or null; `margin`; `verdict`, `words`, `status`, `job` {done, total, stage, next_look, games_per_opponent, pairs, by, started, range} | V |
| `GET /api/variant/estimate` | {quick: [low, high], ahead: [low, high]} (minutes; ahead's high end is the worst case) | V |
| `GET /api/variants` | `tests[]` {test, changes, against, verdict, words, games_per_opponent, saved, running, done, total, when} | V |
| profile settings | `matchup_mode`, `field_budget` | A, F |

---

## 16. Command line (`python -m decklab.lib.forge ...`)

| Command | Behaviour | Owner |
|---|---|---|
| `play A B --until assess\|ahead [--max N]` | §9.3; fixed counts as before | A |
| `field <deck> ...` | §10.5 (with `--opponents`) | F |
| `variant <deck> ...` | §11.5 (with `--opponents`) | V |
| `experiment <spec> ...` | §12.5 | X |
| `pilots [--check] [--json]` | each list's pilot, and the profiles and switches available; `--check` exits 1 on a bad entry | E3 |
| `overrides [list\|check\|make [--set S]\|deploy [--user-dir D] [--sets a,b]] [--json]` | §6. `deploy` without options runs `ensure_deployed` on the real user folder and prints the deployed hash | E3 |
| `staged-move --from <dir> [--to <dir>] [--dry-run] [--json]` | moves staged v2 results into the real results folder (COMBINED-RUN.md §9.2). It calls `ensure_deployed` first and works out keys with today's engine. **Moves** top-level v2 matchup results (`kind` absent) and `field/` notes. **Never moves** v1 files, `paired/`, `kind: "experiment"` files, or anything outside `--from`'s top level and `field/`. A **stale** file (its key isn't the one today's engine gives its lists and pilots) stays, with the description field that differs (`overrides`, `sides[1].ai_sha`, `game_patches`, ...). A **conflict** (a real file with the same key) is skipped and listed. `--hold <keys file>` leaves listed keys behind (a missing file holds nothing). `--dry-run` lists exactly what the real move does | H |
| `soak-probe --results-dir D --logs-dir L --server-port P --constructed N --commander M [--out F] [--json]` | fresh-against-warm replays of sampled games (COMBINED-RUN.md §7.1). It **refuses** (exit 1, "no live server pool on port P") rather than falling back to a local pool | H |
| `--logs-dir`, `--log-every` on `play`, `replay`, `field`, `variant`, `experiment` | §8 | R |
| `status`, `list` | add pilot and override lines (E3's `_setup_lines(found=None)`, called from `_cmd_status` and `_cmd_list`) | E3 |

`cli.COMMANDS` and `_main` stay frozen. The base adds the entries (after W2's, in this order: `field`, `variant`,
`experiment`, `pilots`, `overrides`, `staged-move`, `soak-probe`); each owner fills its `_<name>_args` and
`_cmd_<name>` (the base's parsers take the command alone, and its `_cmd_` prints "isn't built yet" and exits 1).
`_staged_move_args`/`_cmd_staged_move` and `_soak_probe_args`/`_cmd_soak_probe` are the function names for the
hyphenated commands.

---

## 17. Config settings

| Setting | Default | Meaning | Owner |
|---|---|---|---|
| `forge_field_inflight` | 4 | the pair runs a field run or a variant test plays at once | F (reads it); base (the default) |
| `forge_variant_margin` | 0.02 | a field variant test's "makes little difference" margin (§0.6) | V |
| `forge_variant_margin_one` | 0.03 | the same against one opponent (§0.6, §7.4) | V |
| `forge_performance_mode` | true | PERFORMANCE_MODE in Forge's preferences, and in the engine id; false is a battery knob with its own user folder (§6.2) | E3 |
| `forge_game_patches` | true | false plays every game-changing copy's Forge code (an engine of its own, `game_patches` []; a battery knob) | E3 |
| env `DECKLAB_CONFIG_EXTRA` | — | a JSON file merged over config.json (harness) | R |
| env `DECKLAB_PIN_MODE` | core | `core`, `none`, `ccd` or `core-wrap` (harness) | R |
| env `DECKLAB_SEED_BASE` | — | a new result's base when no `seed_base` is passed (harness, §8) | R |
| env `DECKLAB_SIMJAR_EXCLUDE` | — | neutral patch class files to leave out of the jar (harness) | J3 |
| env `DECKLAB_STOP_FILE` | — | a file whose existence stops every run in the process (harness, §8) | R |

They're validated as in W2 §10: a bad value falls back to the default, with one log line. The profile settings
`matchup_mode` (`assess`, `ahead` or `fixed`) and `field_budget` (`standard`, `quick` or `thorough`) go into
`api/settings.SETTINGS` (base). `COORD_JOBS`' limits (2 running, 4 queued) are constants in `api/forge_runs.py`
(base).

---

## 18. Page UX by device (summary)

The existing conventions hold: touch targets of at least 44 px, light and dark themes, plain HTML/CSS/JS, and
`devices.css`'s breakpoints (700 px and 1,600 px; 2,200 px for the widest layout). New classes are prefixed `fv-`
(field view) and `vt-` (variant tests).

| Screen | Phone (below 700 px) | iPad (700-1,599 px, touch) | QHD desktop (1,600 px and up) |
|---|---|---|---|
| Matchup play box | "What do you want to know?" radios stacked; the segmented control under "A set number"; one Play button | the same, in the right column | the radios as three cards in a row |
| Matchup live box | progress to the plan; a dashed live range; the next-check line; a link instead of Stop when a field run or test plays it | the same | the same, with a wider bar |
| Deck page "Against the field" | headline tile, chips, rows in one column, play box (Quick / Standard / Thorough, the sub-line under it) at the end | rows in 2 columns from 900 px | a table beside the headline tiles; the peek column unchanged |
| Field run, while it plays | one progress bar, "Playing: ...", "Started by ..." | plus mini bars per opponent | plus per-opponent bars in the table |
| Editor "Test" | a second bar row with a full-width "Test this change"; a full-screen sheet | inline before Save; a side sheet | inline; a side panel |
| Variant test page | one column; live progress, next check, mini bars, Stop | the verdict panel on top, the rows below | the rows beside the verdict panel |
| Running jobs | a "Running" group on the matchups list; running tests on the deck page | the same | the same |
| Deck page "Tests of changes" | a list of rows | the same | the same, beside "Against the field" when there's room |

---

## 19. Tests and fakes

### 19.1 Fake Forge (the base extends `tests/fixtures/fake_forge.py`; frozen)

- **Pilots:** it accepts `-dlpilot a b`, and refuses ids not in `--pilot-switches=`, and `team-pump-1` while
  `-Ddecklab.gamePatches=off`.
- **Echo:** it prints `ai=`, `pilots=`, `deckorder=`, `aiprofiles=`, `overrides=` and `loadseed=`:
  - `deckorder=1,1` and `loadseed=1` only with game patches on, v2, and `deck-order-1` in `--game-patch-ids`; else
    `0,0` and `0` (and the library is then the fake's W2 order);
  - `overrides=` is the §6.4 hash of the worker's `Forge/custom/cards` **as it was when the process started** (serve
    mode keeps it), so "a worker keeps its set" and the echo mismatch can be tested;
  - `aiprofiles=dl` only with `-Ddecklab.aiprofiles=<dir>`.
- **AI profiles:** the Deck Lab names (`DLAggro`, `DLTempo`, `DLControl`) are known only with
  `-Ddecklab.aiprofiles=<dir>` holding them (the folder's `*.ai` names, with Forge's four). **As built (§2.1 row 17,
  following Java):** an unknown `-a` name prints Forge's `Unknown AI profile - <name>. Available profiles: ...` line
  before anything else and plays nothing (serve: the request ends `error`, detail `Unknown AI profile - <name>`); a
  profile folder that can't be read fails the start (serve: `DLSERVE|fail|...` and exit 3; sim: an `Error:` line and
  exit 3).
- **Flags** (as the real launch has them): `-Ddecklab.gamePatches=off` works like `--game-patches-off`;
  `-Ddecklab.aiprofiles=<dir>`; `--pilot-switches=<ids>`. `test_forge.fake_command` and `fake_serve_command` pass
  `--pilot-switches=` from `card_log["pilot_switches"]` and `-Ddecklab.aiprofiles=` from `setup["aiprofiles"]`
  (`test_forge._wave3_flags`).
- **`-dlpilot` refusals** print an `Error: ...` line and play nothing (serve: status `error`, "the request's arguments
  can't be read", as `Request.parse` giving null): `Error: -dlpilot: no switch called <id>`, `Error: team-pump-1 needs
  game patches on`, `Error: -dlpilot needs -dlgame`, and a missing value.
- **Library order:** a seat's [Main] is expanded in .dck line order and shuffled with the game's RNG, as Forge with
  deck-order-1 does. So an aligned variant draws the same cards until its changed slot.
- **`FAKE_FORGE` additions:**
  - `cardwins=<name>`: a seat with that card in its kept hand or among its first three draws (its library's first 10
    cards) wins the game, unless both seats have it, so paired tests and experiments have a real effect to find;
  - `slowcard=<name>@<ms>`: adds that much time (a sleep, and the `Game Result` line's ms) to each game in which a
    seat's list holds the card (for speed measures);
  - both apply to every process (no `@seed` or `#game`).
- **Card log:** `fake_command` and `fake_serve_command` pass `--pilot-switches=` from the card log.

### 19.2 Per package

Unit tests need no Java. Tests with the real Forge stay behind `DECKLAB_FORGE_TESTS=1`. Monte Carlo tests use fixed
seeds and thresholds a correct implementation passes for nearly every seed.

| Package | Tests |
|---|---|
| S | `test_forge_seqstats.py`: the formulas on hand-worked cases (half-count z at 200-0; the plan formula's floor of n + 100; MOVER field average; unpaired MOVER on the paired g set and ρ None for a constant arm; starter mismatches left out); seeded Monte Carlo checks (≤ 5 s each): HP α of 5 ± 1.5 % over 4,000 paths at p = 0.5; assess coverage ≥ 92.5 % over 2,000 simulations at p ∈ {0.5, 0.65, 0.8}; the anytime-valid range covering at all four looks at once in ≥ 95 % of 2,000 paths; paired Agresti-Min coverage ≥ 93.5 % over 2,000 simulations with ρ ∈ {0, 0.6}; Bradley-Terry: ≥ 90 % of known β within 2 SE and all within 3.5 SE, the same ratings (to 1e-9) under any order of the players, φ ≈ 1 on transitive data; the rank range on a separated toy; leave-one-out residuals flagging a planted pairing and BH; APT picking the opponent closest to 50 %; Spearman with ties |
| J3 | `test_forge_simjar.py` (the Match pin, own classes, the switch list, exclusions refused for game patches); the load-seed vectors in `test_forge_contract.py` (base); gated `test_forge_deckorder.py` (§3.7 checks 2, 3, 6 and 7, at small sizes) |
| E3 | additions to `test_forge_engine.py` (id_version 2; pilots in sides and the `sorted()` order on a pilot mirror; per-list overrides from `eng["deployed"]`; plain-kind sides; echo checks with `seat_pilots`; `deckorder`/`loadseed` with and without `deck-order-1` in the engine; `gamepatches=off` accepted only with `game_patches` []); new `test_forge_pilots.py` (`check_switches`) and `test_forge_overrides.py` (sets; `make` with a fixture zip; deploy deleting extras; `ensure_deployed` with the lock, a manifest folder and the real folder; the upstream cache; the hash equal to the fake's; knob user folders); overlay cases in `test_forge.py` `AiLimitsTests` |
| R | additions to `test_forge_pool.py` (numbers with gaps; numbers below `next_game`: allowed for paired and experiment results, refused for a matchup and for numbers already held; seeds override; the paired and experiment kinds; dck_file; the log tee; launch identity fields; pin modes; a pilot mirror played twice with the entries swapped; an `override_sets` run whose pool worker keeps its folder's files; a `sets.json` change followed by a run with no failed chunk under the new key; `settings.ai` from the pilots; `DECKLAB_SEED_BASE`); `test_forge_runhooks.py` (`update_result`; `_is_result` for paired, experiment and adaptive); the extra file in `test_config.py` |
| A | `test_forge_adaptive.py` (stages with the fake: `cardwins` makes a lopsided pair stop at 400, and an even pair reaches "about even" or 3,200 through a stub run; a case with draws and timeouts where z ≥ 2.008 at 3,200 but `_lead` isn't settled gives `not_settled`; Stop between looks judged at 3.0; a key change between stages stops the run; summaries; `lead_from_summary`); `test_forge_estimate.py`; `test_matchups_api.py` `AdaptiveRunTests` (modes, `joined`, `estimates`, the lead while a summary applies); the play box's modes and the via link in `test_web.py` |
| F | `test_forge_field.py` (membership from fixture decks, products and status.csv, a blank `intact` left out; `--opponents`; reuse; the floor; APT order; the BUSY retry; a key change; the view's numbers; the progress detail's shape); `test_field_api.py` (COORD_JOBS, `_job_for_key` and `via`, the 409 on a matchup Stop); the field section in `test_web.py` (`fv-` classes only) |
| V | `test_forge_variants.py` (writer cases: in place, duplicate names, land swaps, Commander; the flip formula across side orders; base top-ups; paired numbers and filling holes; the refusal without `deck-order-1`; "Play more" making earlier looks interim; the margins; analysis with `cardwins`); `test_variant_api.py`; the editor's Test row (below and above 700 px, sideboard-only disabled), the test page's live state and "Save this change" asking first, in `test_web.py`. Tests that need R's hooks skip with `skipUnless(runner.RUN_FEATURES >= {"numbers", "seeds", "kind"})` |
| X | `test_forge_experiment.py` (arms with the fake: override user folders, pilots, control reuse with its logs, the flip copied with §11.3's formula, arm keys and the experiment kind, own-lost attribution on fixture log lines, paired per-game measures, the §12.4 rules on synthetic numbers, the report). R-dependent tests skip as V's do |
| H | `test_overnight.py` (plan resolution and estimates; priorities, the up-front drop decision and the reserve; the soak minimum and filler; checkpoint and resume with identity checks; the supervisor; the monitor's process classes and input presence; cleanup touching only run-owned processes; the report's PASS/FAIL/INCOMPLETE logic on synthetic outputs; a `--fake` end-to-end run with tiny counts); **`test_forge_staged_move.py`** (a stale key, with the field that differs; a conflict skipped and listed; `paired/`, `kind: "experiment"` and v1 files never moved; `field/` notes moved; `--hold`; `ensure_deployed` called first; the dry run listing exactly what the real move does) |

---

## 20. Ownership (function level)

"base" means the W3 integrator's base commit owns it: change it only by handoff (§21). Every name not listed stays as
wave 2 left it (its W2 owner's code, now frozen for W3).

| File | Owner and what |
|---|---|
| `java/decklab/DeckOrder.java`, `Pilots.java`, `TeamPumpAi.java`, `AiPatches.java`, `Startup.java` (new) | J3: all |
| `java/forge/game/Match.java` (new copy) | J3 |
| `java/decklab/GameLoop.java` | J3: `playGames` (steps 3-6 of §3.2, gated on `deck-order-1`, and the pilots), `engineLine` (the new fields), player creation |
| `java/decklab/Request.java` | J3: `parse` (`-dlpilot`, and `team-pump-1` refused with game patches off) and the new field `pilots` |
| `java/decklab/DeckLabSim.java`, `DeckLabServe.java` | J3: the one `Startup.afterInitialize()` line in each; the rest frozen |
| `java/decklab/Seeds.java`, `seeds.py` | base: `loadSeed` / `load_seed`, `LOAD_SALT`, the vectors |
| `simjar.py` | J3: `PATCHES`, `GAME_PATCHES`, `OWN_CLASSES`, `PILOT_SWITCHES`, `SIM_CLASSES`, `game_patch_ids`, `_build` (`pilot-switches.txt`), `_stamp`, `card_log` (`pilot_switches`), the `DECKLAB_SIMJAR_EXCLUDE` handling (`fitting_patches`), `CHECKED_SOURCE`¹ |
| `logreader.py` | base: `SEAT_FIELDS` |
| `engine.py` | E3: all (including `side_list`, `check_echo`'s `seat_pilots`, `launch_fields`) |
| `pilots.py`, `overrides.py` (new) | E3: all (including `check_switches`, `ensure_deployed`, `user_dir_for`) |
| `install.py` | E3: `_setup` (`aiprofiles`, `performance_mode`, `game_patches` from config, the knob user folder, `overrides`) and `status` (the `overrides`/`pilot_switches` keys and its `ensure_deployed` call) |
| `lists.py` | E3: `entry`, `entry_from_dck` (the pilot) |
| `runner.py` | E3: `request_args` (pilots; the signature is the base's), `_java` (the aiprofiles flag), `PREFERENCES` → `_preferences(setup)`, `_prepare_user_dir` (preferences from the manifest; `ensure_deployed`). R: `run` (the new keywords, `ensure_deployed` first, side order), `_run`, `_record` (side pilots, `settings.ai`), `_write_decks`, the new `update_result`, `RUN_FEATURES`, `DECKLAB_SEED_BASE`, the chunk planner for `numbers` and seat pilots, the chunk reader's `check_echo` call and the log tee (W2 PP's functions, names re-checked at the base) |
| `pool.py` | R: the launch identity, the compatibility identity, chunking `numbers`, the chunk reader's `check_echo` call if it lives here, the log tee (W2 PP's names re-checked at the base) |
| `cores.py` | R: pin modes in `core_masks` and `mask_for` |
| `config.py` | R: `load` (the extra file). base: the `DEFAULTS` additions |
| `saved.py` | R: `_is_result` |
| `views.py` | E3: `_page_side`. base: the wiring of `adaptive_last` and of `adaptive.lead_from_summary` into `view` |
| `ai.py` | E3: `weak_cards`, `_build_weak`, `_cannot_play`, `_limits`, `_pilot` |
| `seqstats.py` (new) | S: all |
| `adaptive.py` (new) | A: all (the base ships `last_summary` and `lead_from_summary` stubs returning None) |
| `estimate.py` (new) | A: all (the base ships a stub returning None; F and V call it) |
| `field.py` (new) | F: all |
| `variants.py` (new) | V: all |
| `experiment.py` (new) | X: all |
| `cli.py` | A: `_play_args`, `_cmd_play`, `_print_play`. F: `_field_args`, `_cmd_field`. V: `_variant_args`, `_cmd_variant`. X: `_experiment_args`, `_cmd_experiment`. E3: `_pilots_args`, `_cmd_pilots`, `_overrides_args`, `_cmd_overrides`, `_setup_lines`, `_same_folder`, and the call to `_setup_lines` in `_cmd_status` and `_cmd_list`. R: `_log_args` (the base ships a stub), and the log options in `_replay_args`/`_cmd_replay`. H: `_staged_move_args`, `_cmd_staged_move`, `_soak_probe_args`, `_cmd_soak_probe`. base: `COMMANDS`, `_main` |
| `api/forge_runs.py` | base: `COORD_JOBS`, and `stop_jobs` stopping it too. A: `_MatchupRun`, `run_matchup` (`joined`), `_job_json` (rendering `via` and the pair record), `_running_json` (both runners), `estimates` in `_matchup_json`'s answer. F: the new `_job_for_key`, its call in `matchup` and `_matchup_json`, and the 409 in `stop_matchup` for a key a coordinator plays |
| `api/field_page.py` (new) | F: all (the base ships stubs answering 501) |
| `api/variant_page.py` (new) | V: all (the base ships stubs answering 501) |
| `api/settings.py`, `api/__init__.py`, `server.py` (routes; the start-up `ensure_deployed` call) | base |
| `web/matchups.js` | A: `gamesChoice`, `playBox`, `play`, `liveBox` (the live range and the via link), `howPart`, and the new `runModeChoice` and `adaptiveWords`; the "Running" group's rows. E3: `sideBox`, `pilotFlag`, `pilotReason`, `pumpSplit` |
| `web/field.js`, `web/field.css` (new; `fv-` classes) | F |
| `web/variant.js`, `web/variant.css` (new; `vt-` classes) | V |
| `web/editor-screen.js` | V: `drawBar` (the Test row) |
| `web/deck.js`, `web/app.js`, `web/index.html` | base: the call sites, the route, and the script and link tags |
| `decklab/simulation.json` | E3 (the file and the pilots section). F: the field section's meaning (changes to the content go by handoff) |
| `decklab/lib/forge/overrides/**`, `decklab/lib/forge/ai-profiles/**` | E3 |
| `decklab/forge-trial/overnight.py`, `overnight_legs.py`, `overnight_monitor.py`, `overnight_report.py`, `overnight-plan.json` | H |
| `tests/fixtures/fake_forge.py`, `test_forge_contract.py` | base |
| tests | as in §19.2, each package its own (H: `test_overnight.py`, `test_forge_staged_move.py`); the later-package rule (§21) for assertions another package's change implies |

¹ `CHECKED_SOURCE` is one line every Java change must set. At each merge, a conflict there is resolved by running
`cardlog-check` on the merged tree and writing its `source_sha256()` (the W2 rule).

**Not touched by any package** (the integrator does them after the merges): `decklab/PLAN.md`, `decklab/README.md`,
the docstrings and imports of `decklab/lib/forge/__init__.py`, and `CLAUDE.md`. New names are reached through their
modules (`forge.seqstats.X`, `forge.field.X`...) until the integrator re-exports any that should be `forge.X`.

---

## 21. Handoffs, merge order and re-checks

**The handoff rule** is W2 §21's:
- write `HANDOFF-<package>.md` in the worktree's root (untracked);
- code against it behind `getattr` or a local adapter, so the branch passes its tests without it;
- the owner, or the integrator at merge, applies it.

Contract changes (anything the base owns) go to the integrator, who updates this file and tells every package.

**The base (the integrator, before the packages start):**
1. Cut `sim-w3-base` from the integrated `sim-w2`, and re-check §2.
2. Set Fiery's `status` in `overrides/sets.json` from the owner's answer to §0.6 question 1: `adopted` (done).
3. Commit this contract as `decklab/forge-trial/sim-wave3-contract.md`.
4. Commit frozen stubs:
   - the `seqstats` names and constants, with NotImplementedError bodies;
   - the `adaptive` (with `last_summary` and `lead_from_summary` returning None), `estimate` (returning None),
     `field`, `variants`, `experiment`, `pilots` and `overrides` modules, as stubs with docstrings (`ensure_deployed`
     returning the folder's current index without writing; `user_dir_for` returning the real folder);
   - `runner.run`'s new keywords (accepted; NotImplementedError when used) and `runner.RUN_FEATURES = frozenset()`;
   - `engine.check_echo(eng, echo, seat_pilots=None)` and `engine.launch_fields(setup, eng)` signatures;
   - the `request_args(..., pilots=None)` signature (W2's behaviour when None);
   - `seeds.load_seed` with its vectors, and `Seeds.loadSeed`;
   - `logreader.SEAT_FIELDS` and the `config.DEFAULTS` additions;
   - `api.forge_runs.COORD_JOBS` and `stop_jobs` stopping it; the `api/field_page.py` and `api/variant_page.py` stubs
     (ApiError 501), the server routes, the server's start-up `ensure_deployed` call and the `api/__init__` re-exports;
   - the `views.view` wiring of `adaptive_last` and `lead_from_summary` (no change while the stubs return None);
   - the settings keys, the `cli.COMMANDS` entries with `_args`/`_cmd` stubs, and `cli._log_args` as a stub that adds
     nothing;
   - the `index.html` tags, and the `web/field.js` and `variant.js` stubs (`fieldSection` returns null; `showVariant`
     shows a "not built" panel), with their call sites in deck.js and app.js;
   - the fake Forge's extensions (§19.1);
   - an empty `decklab/simulation.json`, and the skeleton of `overrides/sets.json`.

**What the base also committed** (beyond the list above; all base-owned):
- `simjar.OWN_CLASSES = ()` and `simjar.PILOT_SWITCHES = {}` (J3 fills them; `card_log()["pilot_switches"]` is J3's);
- `overrides.deployed_hash`/`deployed_index` (EP's form, §6.4) and `ensure_deployed` returning them without writing;
  `pilots.pilot_for` giving the default pilot and `check_switches` refusing nothing; `adaptive.MODES`;
  `field.BUDGETS`; `variants.NO_DECK_ORDER`/`SIZE_CHANGED`; the other functions raise NotImplementedError with their
  docstrings;
- the new modules imported in `forge/__init__.py` in this order: `... lists, overrides, pilots, engine, ... views,
  seqstats, estimate, adaptive, field, variants, experiment, cli` (so `overrides` and `pilots` must not import
  `engine` at module level; `views` imports `adaptive` inside `_adaptive_view`);
- `views._adaptive_view(result, p)` (the `adaptive_last` key on every `view()` answer, and the lead from the summary);
- server: the routes of §10.5 and §11.5, `COORD_WAITING`, `_join_runs` (a stopping server waits for both runners), and
  the start-up `ensure_deployed` in `_start_pool`;
- web: `variantTestsSection(data)` in `variant.js` (null until V builds it) called by `deck.js` after `fieldSection`;
  the deck page's "Field" nav button appears only when `fieldSection` returns a part;
- tests: `test_forge._wave3_flags`, and `test_forge_contract`'s `FakeWave3Tests` and `Wave3BaseTests`, plus
  `W3_SETTINGS` in `test_api` (the new settings' defaults in the expected answers);
- `Seeds.java` changed, so the base ran cardlog-check (passed) and set `CHECKED_SOURCE`.

**Packages that need R.** V's and X's tests that play paired or experiment runs need R's hooks. They're written now
and skip with `skipUnless(runner.RUN_FEATURES >= {...})` until R merges (merge 4); after that they run in the full
suite at every later merge. Everything else in V and X (the writer, the analysis on game dicts, the page) is tested
from the start.

**Merge order.** Each merge: rebase on `sim-w3`, run the full suite, run cardlog-check when Java changed, update
`CHECKED_SOURCE`, and run the small real check named:

| # | Package | Check at the merge |
|---|---|---|
| 1 | S | pure Python; the suite only |
| 2 | J3 | cardlog-check on the merged tree; §3.7 checks 2-7 run again (≤ 200 games, plus one game per list for check 7) |
| 3 | E3 | `overrides check` and `pilots --check`; one real 100-game run of Gruul v Izzet in which the echo checks pass (deckorder, ai, pilots, overrides); then with the adopted sets deployed by `ensure_deployed`: the overrides hash matches the echo, and (when Fiery is adopted) Fiery is cast in the log |
| 4 | R | integration with the fake; one real paired run (`numbers`/`seeds`) of 50 games, and a log tee; one real 25-game `override_sets` run in an `exp-` folder whose echo shows that folder's hash |
| 5 | A | one real `--until ahead` on a lopsided pair (≤ 800 games) |
| 6 | F | one real `field --budget 50 --opponents <3 lists>` (≤ 300 games) |
| 7 | V | one real `variant --games 100` against one opponent, and the alignment check (§3.7 check 2) through the real writer |
| 8 | X | one real experiment: the Fiery pair (with and without `fiery`) on Gruul v Izzet, 100 games per arm |
| 9 | H | the harness's daytime smoke run (`overnight.py supervise --smoke`, ≤ 4 workers, about 20 min, with the crash-and-resume drill, COMBINED-RUN.md §3) |
| 10 | Integrator | the PLAN.md wave 3 entry, README, the `__init__` docstrings, one cardlog-check and one full suite. `sim-w3` is then ready for the combined run (COMBINED-RUN.md), and it is never merged to main before that run passes |

**This build's merge plan (2026-10-03; it replaces the table's order for A to H tonight):**
- **S → J3 → E3 → R, strictly in that order**, each rebased on `sim-w3` and merged with the table's check.
- **Then A, F, V, X and H, each as soon as it is reviewed** (and only after R has merged), in whatever order they're
  ready. Each rebases on the `sim-w3` of that moment, runs the full suite (cardlog-check when Java changed) and its
  table check, and merges.
- **Cut-offs (home time, `date +%H:%M`):** an optional package (A, F, V, X) doesn't merge if its merge would start
  after **20:45**; it then stays on its branch for a later build. **H must merge tonight.** Final checks and fixes end by
  21:30; the start instructions for the 22:00 combined run are ready by 21:45.
- Must-have packages for tonight: S, J3, E3, R and H. **H's plan resolution must drop, up front, the items of an
  optional package that didn't merge** (COMBINED-RUN.md), telling it from the code it runs (a stub still raising
  NotImplementedError, or a CLI command that answers "isn't built yet"), never from a list typed in by hand.
- Docs (PLAN.md, README, the `__init__` docstrings) wait until after the combined run: packages leave them alone and
  put notes in their summaries.
- Wave 2's docs step (907444a: PLAN.md, README, docstrings) landed on `sim-w2` after the base was cut; the base merged
  it (`sim-w3-base` is the merge, 4a8739e and after), so every package starts with it. Should `sim-w2` move again, the
  integrator merges it into `sim-w3` before the combined run.

**Dependencies on wave 2 code that may still shift:** J3 (EJ's `playGames`, PJ's start-up), R (PP's run loop, chunk
reader and pool internals), E3 (EP's engine and override hash), A and F (`_MatchupRun`, FORGE_JOBS and `stop_jobs`),
and H (the replay and serve-check commands). Each of these packages re-reads the integrated `sim-w2` code before it
starts, and records any difference from §2 in its handoff.

**The later-package rule** is W2's: a breaking change to another package's tests that this contract already implies is
fixed by the later package in the merge order, limited to the assertion lines, and listed in its handoff note.

---

## 22. Resource rules while building

As W2 §21 says:
- at most 4 Forge processes or pool workers, and about 400 games a run at most;
- BELOW_NORMAL priority, and slots respected;
- never write the main checkout's `decklab/data/forge/results`; use a scratch `--results-dir`;
- never use the 8642 server; test servers run on 127.0.0.1 from port 8643 with `--no-update`, and are stopped
  afterwards;
- after any Forge run, list java.exe with `Get-CimInstance Win32_Process -Filter "Name='java.exe'"`, and end only your
  own leftovers (by PID, from your own run) with `taskkill /PID <pid> /T /F`;
- no timing claims: the combined run measures speed (COMBINED-RUN.md).

---

## 23. Review fixes (revision 2): where each finding went

Three reviews of revision 1: statistics (S-), systems and UX (U-), and the runbook (B-). "Must" and "should" items are
all fixed; nits are fixed unless the last column says why not. Runbook items are in COMBINED-RUN.md (its §12 lists
them in detail).

| # | Finding | Fix |
|---|---|---|
| S-must | G9's per-matchup AI-timeout rule fails by chance | COMBINED-RUN §9.1 MG9: conditional-binomial rate-ratio test, Clopper-Pearson at 1 − 0.05/m, FAIL only at r_L > 3 and x2 ≥ 3; a pooled test; the absolute rule kept |
| S-should | G7's Commander comparison of two point estimates | MG7: paired Agresti-Min on a_g − b_g; FAIL when low > 0 and the estimate > 0.05; 150 Commander games |
| S-should | G13 compares star ratings with full-graph ratings, and sides of 50 without noise | MG13: Spearman of the two rows; per opponent, a difference z at 2.77 (Bonferroni over 9) or both ranges excluding 50 % on opposite sides |
| S-should | the plain verdict after Stop is peeking; lead word vs `adaptive_last` at 3,200 | §7.3 (stopped looks at 3.0, 99.73 % "about even", `not_settled_stopped`), §7.6 (the anytime-valid range, built), §9.2-9.4 (the lead from the summary), §11.4 ("Play more" makes earlier looks interim) |
| S-should | assess top-up mostly adds 0 games | §7.2: N_total = ceil25(max(n + 100, n·(hw/h)²·1.03)) for plan and top-up; Z²v/h² only for the page's estimate |
| S-should | z undefined at 100 % strata | §7.3: half-count SE; z undefined only at d_s = 0 |
| S-should | BT: β fixed with a ridge makes ratings depend on order | §7.5: no β fixed; Σβ = 0 at the maximum; an order-invariance test (§19.2) |
| S-should | BT ranges ignore dispersion; rank range undefined | §7.5: φ = max(1, X²/df) scales the rating range; rank range from 4,000 draws of N(β̂, φΣ) |
| S-should | residual flags in-sample, no multiplicity | §7.5: leave-one-pairing-out residuals, no flag on a bridge, BH at 10 % with the 5-point floor |
| S-should | unpaired comparison on other games; Newcombe on balanced values | §7.4: MOVER over the same paired g; ρ None for a constant arm |
| S-should | ±2 points unreachable for one opponent | §7.4: ±3 for one opponent, ±2 for the field, the formula; §0.6 question 2; §17 `forge_variant_margin_one` |
| S-should | adoption rules: multiplicity, non-inferiority, pairing | §12.4: Bonferroni per pair, pooled 95 %, early-in-hand low ≥ −0.03; §12.3: paired per-game measures from logs |
| S-should | D2a(3) too small, seats differ, SE vs variance inflation | COMBINED-RUN D2a(3): 800 games, Izzet's seat matched by §11.3's formula, Fisher-z range, both inflations |
| S-should | ladder monotonicity by point estimates; pilot-sensitivity flips | COMBINED-RUN §9.3: per-game paired slope; a reversal only at z > 2 per step; flips as BH-10 % discoveries |
| S-nit | `--max N` bound | §7.1, §9.3: the last reachable look uses 2.008 |
| S-nit | starter mismatches | §7.4: paired only on equal starters; reported; a warning above 1 % |
| S-nit | field look with a dropped opponent | §7.4: looks wait for every remaining opponent; dropped ones removed from every look |
| S-nit | Wald field-average range | §7.5: MOVER; Wald SE kept for the harness |
| S-nit | arms don't copy the control's flip | §12.2: seeds incl. flip from the control, §11.3's formula when the side order differs |
| S-nit | cast % treats copies as independent | §12.3: ratio estimator with a cluster SE; paired game-level comparison |
| S-nit | Monte Carlo thresholds | §19.2: assess ≥ 92.5 % at 2,000; BT ≥ 90 % within 2 SE and all within 3.5 SE |
| S-nit | APT_EPS citation; per-card pooling from field runs | §7.1 re-cited; §7.5 documents the pooling; equal-weight pooling not built (§7.7): the deck page keeps wave 1's pooling, and the field average already answers the equal-weight question |
| S-nit | drift probes confounded by load | COMBINED-RUN §7.2: exclusive drift probes between items |
| U-must | experiment arms can't use their own user folder | §8 `override_sets`; §6.2 `user_dir_for` manifests, `_prepare_user_dir` deploying the manifest; §4.3 `eng["deployed"]`; R/E3 tests |
| U-must | deploy timing vs keys and launch hashes | §6.2: `ensure_deployed` (one rule, cross-process lock) before `engine.current` and in every key-making entry point; a test |
| U-must | deckorder/loadseed echo would stop v2 play after a Forge upgrade | §3.2, §3.5, §4.4: gated on `deck-order-1` in the engine; §11.4 refusal; a fake test; and §3.7 check 7, so no current list trips the strict check by name matching |
| U-should | pilot-mirror side order | §4.1 `sorted()` on side lists; §8 seat pilots from stored sides; an R test with swapped entries |
| U-should | `check_echo` seat mapping and call site | §4.3 `seat_pilots` in seat order; §8 and §20: R owns the call site |
| U-should | knob arms share `forge.preferences`; `gamepatches=off` rejected; switches with patches off | §6.2 knob folder; §4.4 `gamepatches=off` when `game_patches` []; §3.3 and `pilots.check_switches` |
| U-should | `numbers=` below `next_game` undefined | §8: allowed only for paired and experiment results; tests |
| U-should | coordinators don't check the key | §1, §9.2, §10.3, §11.4, §12.2: the key check and its sentence |
| U-should | final-look "ahead" vs `_lead` | §7.3: "ahead" needs `_lead`'s agreement; the page's lead from the summary; an A test with draws and timeouts |
| U-should | Stop does nothing on a pair a coordinator plays; coordinators take matchup slots | §1 and §10.5: `COORD_JOBS`; the frozen `pairs` record; `via`; a link instead of Stop; a 409 |
| U-should | Fiery adopted before the run against the owner's decision | the header's owner decisions and §0.6 question 1: an explicit exception pending the owner's OK, with the rollback cost; `experiment` if no |
| U-should | Test button overflows 390 px; sideboard-only changes | §11.6: a second bar row below 700 px; Test only for Main/Commander changes |
| U-should | test page while running; no list of running jobs | §11.6 live state; §10.5 `_running_json`, §10.6, §11.6 deck page |
| U-should | hours-long defaults; cold-batch estimates | §11.6 worst-case time, Quick by default for Commander or over 30 min; §9.5 one server-side estimator calibrated by the combined run |
| U-should | rank range undefined | §7.5 |
| U-should | `.field*` class collision | §10.6 `fv-`, §11.6 `vt-` |
| U-should | V and X fake tests before R; missing base stubs | §21: `skipUnless(RUN_FEATURES ...)`; `_log_args`, `last_summary`, `lead_from_summary`, `estimate` stubs |
| U-should | fake lacks aiprofiles, start-up hash, no-deck-order paths | §19.1 |
| U-should | staged-move untested | §19.2 `test_forge_staged_move.py` (H) |
| U-nit | `settings.ai` | §5.4, §8 |
| U-nit | `_cmd_status` and `pumpSplit` unowned | §5.4, §20: E3 |
| U-nit | exact side sort | §4.1 |
| U-nit | phone breakpoint | §9.4, §10.6, §11.6, §18: 700 px |
| U-nit | field play box segments | §10.6: Quick / Standard / Thorough with a sub-line |
| U-nit | copy for new players | §9.4, §10.6, §11.6: questions, "points of win rate", "Stopped early..." |
| U-nit | blank `intact` precons in the Commander field | §10.1: left out until set; `field.Commander.remove` for near-duplicates |
| U-nit | "Save this change" over another draft | §11.6: asks first |
| U-nit | experiment results folder; arms at once | §12.2, §12.5: a default folder; one launch identity at a time |
| U-nit | rerun join ignores the mode | §9.3 `joined` and the page's sentence |
| B-* | the runbook review | COMBINED-RUN.md, every must and should; its §13 maps them |
