# Deck Lab simulations, wave 2: the contract

**Date:** 2026-10-03. **Base:** branch `sim-w2-base` (worktree `C:/VSProjects/TCC-wt/w2-base`), two commits on
main `9e4cb68`: "Deck Lab sim W2-contract: shared pieces and stubs" and "Deck Lab sim W2-contract fixes: the
reviewers' musts and shoulds". A copy of this file is committed there as `decklab/forge-trial/sim-wave2-contract.md`;
code comments point at it.

**Revision 2 (same day), after a Java-side and a Python-side review.** What changed, by section: the warm check
compares Commander by outcome and has an "unsure" for Constructed differences that don't come back (identity-hash
order can't be reset: §4, §6.6, §7, §18); the engine id names only the game patches built into the jar, and the
DLENGINE line names the ones loaded (`gamepatchids`, §5, §13, §19); R14b's loop swallows a task's exception as
`invokeAll` did, and R14a falls back to a platform thread while an earlier eval still runs (§19); the checks also
mask the Game Result ordinal and stack-trace frames (§4, §18); a frozen Java hook for AI timeouts (`decklab.Signals`,
`GameRecord.aiTimeouts`, `Played.last`) and serve recycles on `clock`, `ai_timeout` or `crash` (§2, §6); serve no
longer tees into `forge<N>.log` and reports its heap (§6); every v2 game loads its decks after the reseed (§4);
malformed requests end with `error` and the worker plays on (§3, §6); Stop saves at once and the pool closes after
the runs (§9, §10); one pool-service file per server, launch identities per chunk, CLI disconnects, retries, the
first-use gate, the serve-failure fallback, a live-JVM cap (§9-§11); the seat flip is stored (§8, §12); per-card
stats pool by the decklab kind's id (§13); replay's open cases (§16); config validation (§17); merge-time checks and
ownership gaps (§20, §21). Base code carries the frozen parts (see "What base ships", §6.6).

**What wave 2 builds** (`decklab/forge-trial/sim-investigation.md` §3-§4): R05 warm pool with one chunk queue across
matchups, R01b one physical core per worker (CCD0 first), R06 v2 engine id, R09 per-game seeds / a Match per game /
auto-profile every game, R08 PERFORMANCE_MODE, R14a AI eval on a virtual thread, R14b attack-requirement checks as a
loop, R11 item 4 (card log RECORD_VERSION 3, "in hand by turn 3"). Not wave 2: R12, R13, R15, R10, R16, R17. Don't
block them: per-pair seed streams, game numbers, chunked runs.

**Owner decisions (final):** the server owns the warm pool, which closes after 15 minutes idle; CLI runs submit to the
running server's pool; Forge runs at BELOW_NORMAL; after the v2 bump current matchups are replayed (a command, run
later on an idle PC; never on real data now); "about even" = ±5 points; field averages weight opponents equally;
best of one.

**Six packages:** **J** Java AI patches, **EJ** the v2 game loop (Java), **PJ** serve mode (Java) and the warm check,
**EP** the engine id and everything that reads results by engine (Python), **PP** the pool and the run loop
(Python), **C** card log v3.

---

## 1. Architecture: the life of a run

```
page (POST /api/matchup/run) ─┐                                     ┌─ CLI play / replay
                              ▼                                     ▼
              api.forge_runs FORGE_JOBS (max_running 4)      cli._cmd_play / _cmd_replay
                              │  forge.run(a, b, games, pool=...)   │
                              ▼                                     ▼
 runner.run: setup, names checked, .dck written, simjar.card_log(), eng = engine.current(setup, card_log),
             key = engine.key(a, b, eng), matchup lock (_claim)
                              │
           ┌──────────────────┴──────────────────────────┐
  eng["kind"] == "decklab" (the card log's jar ready)    eng["kind"] == "plain" (fallback)
           │                                             │
  plan v2 chunks (§9): game numbers [next_game,          today's cold batches: lists.plan, runner._play,
  next_game + games), seat blocks of 25, base, stream,   one plain Forge process per batch, in a slot each,
  flip; each chunk carries the run's launch identity     v1-style games (one seed a batch, loser starts next)
           │                                             — keyed as its own engine (§13), never pooled with
  submit to a pool (§10): the server's (in the server;   decklab results
  the CLI's via the server's pool service), or a local
  pool for the run / session
           │
  pool: ONE queue of chunks from every queued run (FIFO by run within a priority, §9), a worker of the chunk's
  launch identity takes it when it gets a slot (§11), is pinned to that slot's core, sends "play" (§6), its reader
  thread feeds the chunk's LogReader and watches DLSERVE| lines; cancel at game boundaries; recycle after a clock
  stop / AI timeout / crash (§6.5)
           │
  chunk result (games with their numbers "g", casts, lands, card record, engine echo) → back to the run
           │
  run: merges its chunks (cardlog.merge_record, casts/lands summed), engine.check_echo per chunk,
       progress(done, total, detail) as today
           │
  runner._record: ONE merged batch record per run (§12), run record, engine fields (engine.result_fields,
                  engine.side_fields), next_game; written whole; lock released
```

- **Fallback:** when `simjar.card_log()` isn't ready (no JDK, unchecked Forge, failed check, a build failure), the
  run plays plain Forge cold batches exactly as today (`runner._play`), keyed with `kind: "plain"`, so it never
  pools with decklab results and never blocks after a Forge upgrade.
- **One-shot DeckLabSim (`sim`)** stays: the checks use it (§18), and any single v2 game can be replayed with it.
- **Plain Forge** plays game g of a v2 Constructed result as `sim -d <deck 1 of g> <deck 2 of g> -n 1 -s
  <seeds.game_seed(base, stream, g)>` (with game-changing patches off on our side, §19), deck 1 of g being side
  `seeds.deck1_side(g, flip)` with the result's stored `seeds.flip` (§8, §12).

---

## 2. Java: classes, build, ownership

All in `decklab/lib/forge/java/decklab/`, package `decklab`, one jar (`simjar`), built from **every `.java` file in
that folder** (`simjar.deck_lab_sources()`: DeckLabSim's first, then the rest by name) plus the patches that fit.
Adding a file needs no simjar change; it changes `source_sha256()`.

| Class | What | Owner |
|---|---|---|
| `DeckLabSim` | `main`: start-up (Forge's `Main` "sim" branch), dispatch: `serve` → `DeckLabServe.serve()`; `-t` → Forge's SimulateMatch; else `simulate(args)` = `FModel.initialize`, `WarmState.snapshot()`, "Simulation mode", `Request.parse`, `GameLoop.play(req, null)`. Holds `CardLog` (the listener, DL format 1, unchanged). | frozen (base) |
| `Request` | parsed arguments (§3); `parse(String[])` returns null after printing Forge's error, as SimulateMatch does | EJ |
| `GameLoop` | `play(req, boundary)` → `playBatch` (v1, base) or `playGames` (v2: EJ); `playOne(mc, ordinal, number, gameLog, cardLog)` one game, prints its log and "Game Result"; `engineLine(...)` the DLENGINE line; `Boundary`, `GameRecord`, `Played` | EJ |
| `Seeds` | `mix`, `gameSeed(base, stream, game)`, `parseStream` (strict: `[0-9a-f]{16}`, as `seeds.parse_stream`); `main` prints vectors for the tests | frozen (base) |
| `Signals` | `AI_TIMEOUTS`, `LIVE_EVALS` (public static final `AtomicInteger`s): J's AiController copy updates them, GameLoop and serve read them (§6.5, §19) | frozen (base) |
| `WarmState` | `snapshot()`, `reset()`, `problem()`, `counters()` (§7) | PJ |
| `DeckLabServe` | serve mode, the protocol (§6) | PJ |
| `forge/ai/AiController.java`, `forge/ai/AiAttackController.java` (new, shadow classes) | R14a, R14b (§19) | J |
| `forge/game/mulligan/AbstractMulligan.java` | wave 1's R04 copy | frozen |

**Frozen Java API** (PJ and EJ code against it; changing it needs a handoff, §21):
- `GameLoop.play(Request, Boundary) -> Played`; `Boundary.another(GameRecord last) -> boolean` asked before every
  game but the first; `GameRecord{ordinal, number, clockStop, crashed, aiTimeouts}` (`aiTimeouts`: the rise of
  `Signals.AI_TIMEOUTS` over the game, filled by `playOne`); `Played{games, clockStop, stoppedEarly, problem,
  last}` (`last`: the last game's record, or null); `GameLoop.ENGINE_PREFIX = "DLENGINE|"`; `GameLoop.playOne`'s
  signature, and its guarded log read (after a clock stop the abandoned game thread may still add entries: the read
  is tried 3 times, then the game's lines are left out and its Game Result line still prints);
  `GameLoop.GAME_PATCH_LIST` and `gamePatchIds()` (§5).
- `Request.parse(String[] args)` (args[0] is "sim"); fields `dlGame`, `stream`, `firstGame`, `cardLog`, `games`,
  `seed`. With `-dlgame` it validates everything itself (§3) and returns null after an `Error:` line; without it,
  a bad number throws as in SimulateMatch (serve catches it, §6.2).
- `WarmState.snapshot()`, `reset()` (throws `IllegalStateException(problem)` when snapshot failed), `problem()`,
  `counters()`.
- `Signals.AI_TIMEOUTS`, `Signals.LIVE_EVALS`.
- `DeckLabServe.recycleReason(GameRecord) -> "clock" | "ai_timeout" | "crash" | null` (PJ may add reasons; Python's
  `runner.RECYCLE_REASONS` must then grow by handoff).

---

## 3. The request (sim's arguments; the same in `sim` and in serve's `play`)

```
sim -D <deck folder> -d <deck 1>.dck <deck 2>.dck -n <games> -s <seed> -f Constructed|Commander -c <clock s>
    -a <AI profile 1> <AI profile 2> [-q] [-m <games per match>]
    [-dlgame <stream: 16 lower-case hex digits> <first game number>]    v2 (EJ)
    [-dlnocardlog]                                                     no card-log listener (checks only)
JVM flag (before -cp):  -Ddecklab.gamePatches=off                       game-changing patches play Forge's code
```

- Built only by `runner.request_args(setup, fmt, deck1, deck2, games, seed, v2=None)` (frozen), with `v2 =
  {"stream": "<16 hex>", "first": int, "card_log": False?}`; `runner.build_command(..., v2=None)` (one-shot) and
  `runner.request_line(id, args)` (serve). `setup["game_patches"] is False` adds `simjar.GAME_PATCHES_OFF` (frozen,
  `runner._java`). Plain Forge (`-jar`) never gets `-dlgame` (`build_command` raises ValueError).
- With `-dlgame`, `-s` is the result's **base** (0 or more: Forge's parser reads `-s -5` as an option "-5";
  `request_args` raises ValueError for a negative v2 base). `Request.parse` refuses, with an `Error:` line and
  null, a `-dlgame` request whose stream isn't 16 lower-case hex digits, whose first game is below 0, whose `-s` is
  missing, empty or below 0, whose `-n` isn't a number of 1 or more, or that has `-m` (v2 plays single games).
- Deck order in a request = seat order for **every** game of the request (Python puts the deck of
  `seeds.deck1_side(first, flip)` first, flip the result's; a request never spans a seat block, §9).
- A field never holds a tab, CR or LF (`request_line` raises ValueError).

---

## 4. The v2 game loop (EJ: `GameLoop.playGames`)

For game i = 0 .. n-1 of the request (result game number g = first + i):
1. Ask the Boundary (i > 0); stop when it says no (`Played.stoppedEarly`).
2. `WarmState.reset()` (so game g is the same after any games in the same JVM). An `IllegalStateException` from it
   (snapshot failed) ends the request with `Played.problem` = its message (no game starts; serve answers `error`),
   never an uncaught exception.
3. `MyRandom.setRandom(new Random(Seeds.gameSeed(base, stream, g)))`.
4. Load both decks, make a **new** `GameRules` (Forge's is mutable, and plain Forge makes one per process), the
   RegisteredPlayers and AI players exactly as `playBatch` does (same order, same calls) — **every game, game 0
   included**. Deck Lab's .dck lines carry no set or art, so `CardPool.add` can draw from MyRandom
   (`splitIntoRandomGroups`, forge-core CardPool.java:144) and a deck's pre-shuffle order depends on the RNG state:
   decks loaded for the DLENGINE line or the header (before game 0's reseed) are thrown away, never reused.
5. A **new Match** for this one game (public API): game 1 of its Match, so a coin flip picks the starter and Forge's
   auto-profile runs (`setupAutoProfile`), every game.
6. `playOne(mc, i, g, ...)`: prints the game's log and `Game Result: Game <i+1> ...` (the ordinal in the request, as
   today; Python maps it to g = first + i; the checks mask it).
7. A clock stop sets `GameRecord.clockStop`; an AI timeout shows in `GameRecord.aiTimeouts` (with J's copy), a crash
   in `crashed`. The old game thread or eval thread may still run and draw from MyRandom or touch the counters
   `reset()` puts back: serve stops the request and recycles (§6.5); one-shot `sim` goes on, and the checks treat
   **every later game of that process** as unsure, in both formats (§18).

Before the header line, print the DLENGINE line (§5) once with `v=2|seeds=game|base=<s>|stream=<hex>|first=<g>` as
its first fields. The header line stays Forge's: `Ai(1)-<deck> [Default] vs Ai(2)-<deck> [Default] - N games of
<format> seed <base>`.

**Requirement (checked, §18):** game g of a Constructed request with game patches off equals plain Forge `sim -n 1
-s gameSeed(base, stream, g)` with the same deck order, line for line, with the **comparison masks**: timings
(`RE_TIMING`) and the Game Result ordinal (`RE_ORDINAL`: "Game <n>" → "Game ?") masked, attackers sorted, stack-trace
frames dropped (lines starting tab + `at ` or tab + `... N more`: `RE_FRAME`; the exception's own line is kept), and
`WARNING:`, DL| and DLENGINE| lines dropped. Base's `cli._games_text` applies all but `WARNING:` (serve output only).
Commander games are compared by winner, starter and length. Steps 2-5 exist to make that true; EJ verifies it before
merging (small: ≤ 20 games). A difference only in games after the first of a JVM is warm state: PJ's (`WarmState`),
by handoff, not EJ's to patch. Base's `WarmState.reset()` already works, so EJ can call it from day one.

**Known residual (can't be reset):** Card, GameEntity and GameObject don't override `hashCode` (only CardView and
TrackableObject do), so the order of a HashSet or HashMap of Cards or Players follows HotSpot's per-thread identity
hash state, seeded when the thread is created; a warm worker's game threads are created at other points than a fresh
JVM's. Plain Forge's own Commander games already don't repeat line for line (cli.py's `LINE_FOR_LINE` comment). For
Constructed, e3's 90/90 and v-r08's 400/400 identical games show it's rare, not impossible. So the checks never fail on
a Constructed line difference that doesn't come back when the game is replayed (§18's "unsure"), and nobody chases
such a difference with reset items.

---

## 5. The DLENGINE line (printed by DeckLabSim, read by `LogReader`)

`DLENGINE|<key>=<value>|<key>=<value>...` — one line per request (one-shot run or serve request), before Forge's
header line, so game readers never see it. Values hold no `|` or `=`. Readers ignore unknown keys.

| Key | Value | Since |
|---|---|---|
| `v` | 1 (playBatch) or 2 (playGames) | base |
| `seeds` | `batch` or `game` | base |
| `base`, `stream`, `first` | v2 only: `-s`, `-dlgame`'s stream (16 hex) and first game number | EJ |
| `perf` | `true`/`false`: `Spell.isPerformanceMode()` (did PERFORMANCE_MODE take?) | base |
| `cardlog` | `on`/`off` (`-dlnocardlog`) | base |
| `gamepatches` | `on`/`off` (`-Ddecklab.gamePatches`) | base |
| `gamepatchids` | the ids (`simjar.GAME_PATCHES`) of the game-changing copies **loaded** in this JVM, sorted, joined by `,`; empty for none. `GameLoop.gamePatchIds()`: the jar's build lists the copies it built in (`decklab/game-patches.txt`, `simjar.GAME_PATCH_LIST`, "<class file> <id>" a line); a listed class counts only when it was loaded from the card-log jar (its code source is GameLoop's), checked with `Class.forName(name, false, ...)` (no initialisation). Listed with `gamepatches=off` too (the copies are in play, playing Forge's code). | base |
| `autoprofile` | `<seat 1>,<seat 2>`, each `1`/`0`: Forge's rule, name holds "Control" or `Deck.getAverageCMC() > 3` — Deck Lab's re-derivation on the loaded deck, not an observation (EJ's check compares it once with Forge's own answer, §18) | base |
| `avgcmc` | `<seat 1>,<seat 2>`: `Deck.getAverageCMC()` (truncated) | base |

Python: `logreader.ENGINE_PREFIX`, `engine_fields(line)`, `LogReader.engine` (dict), `LogReader.engine_by_side()`
(`SEAT_FIELDS` = autoprofile, avgcmc mapped from seats to sides with the reader's deck1) — all frozen. Ids match
`simjar.GAME_PATCH_ID` (`[a-z0-9][a-z0-9.-]{0,63}`), so they never hold `|`, `=` or `,`.

---

## 6. Serve protocol (PJ implements in Java; PP drives it; base has a working version 1 + the fake)

Start: `runner.serve_command(setup)` = java, `-Xmx`, JVM_FLAGS (APC=2), [game patches off], `--add-opens...`, `-cp
<card-log jar>;<Forge jar>`, `decklab.DeckLabSim serve`; cwd `setup["forge_dir"]`, env from
`runner._prepare_user_dir`. stdin a pipe (UTF-8), stdout+stderr one pipe. `-Ddecklab.gamePatches` is read once per
JVM, so a patches-off request needs a worker started with it (the launch identity, §10).

Once `ready`, serve points System.out and System.err straight at the process's stdout and stderr again
(`DeckLabServe.untee`, base): Forge's ExceptionHandler tees all output into `<user dir>/.../forge<N>.log` for the
JVM's life (25-34 KB a game), into a file `_tidy_user_dir` deletes while it's open, so it grew unseen. The new
streams use `Charset.defaultCharset()` (UTF-8 with `-Dfile.encoding=UTF-8`), as ExceptionHandler's do, so a request's
bytes are a one-shot sim's (measured in base: the log stays at its start-up size; warm games equal one-shot ones).

### 6.1 Commands (stdin, one a line, fields separated by TAB, line ends LF)
| Command | Meaning |
|---|---|
| `play<TAB><id><TAB>sim<TAB><arg>...` | a request; the args are `request_args()`'s, one per field |
| `cancel<TAB><id>` | stop request `<id>` at its next game boundary (unknown or finished id: ignored) |
| `quit` | exit; a request playing stops at its next game boundary first |
| end of stdin | as quit ("eof") |

`<id>` matches `[A-Za-z0-9._-]{1,64}` (`runner.REQUEST_ID`), unique per worker. **Python sends one request at a time
per worker** and the next only after its `end`.

### 6.2 Responses (stdout, among Forge's own lines)
| Line | When |
|---|---|
| `DLSERVE|ready|<protocol>|<pid>|<id counters>` | once, after `FModel.initialize` and `WarmState.snapshot()` |
| `DLSERVE|begin|<id>` | a request starts |
| (request output) | exactly what `sim` prints for those args after start-up: `Simulation mode`, the DLENGINE line, the header, each game's log and `Game Result` line |
| `DLSERVE|end|<id>|<status>|<games>|<ms>|<detail>` | it ended. `<games>` = its `Game Result` lines; `<ms>` wall; `<detail>` last field, may hold `|`: `heap_mb=<n>` for done and cancelled (`runner.SERVE_HEAP`: heap in use after the latest GC, from the heap pools' `getCollectionUsage()`, no forced GC), a recycle reason, or an error's text |
| `DLSERVE|bye|<why>` | it exits next: `quit`, `eof`, `recycle` (exit code 0) or `error` (a Throwable escaped: exit code 1) |
| `DLSERVE|bad|<text>` | a command it didn't understand (ignored, worker goes on) |
| `DLSERVE|fail|<why>` | it can't serve at all (WarmState.snapshot failed); exit code 3 |

Statuses: `done` (every game played); `cancelled` (stopped at a game boundary by cancel, quit or eof);
`recycle` (a game left something behind: `detail` one of `runner.RECYCLE_REASONS` = `clock` (its clock stopped it),
`ai_timeout` (`GameRecord.aiTimeouts > 0` or `Signals.LIVE_EVALS > 0` at the boundary: an eval timed out, or one is
still running), `crash` (an exception or StackOverflowError ended the game: Forge's unsynchronised static lazy maps,
e.g. `Keyword.cardKeywordSetLookup`, may be half updated). The Boundary stops at the next game boundary, and the same
check runs on the request's last game; the worker prints `bye|recycle` and exits 0); `error` (no game could start:
arguments it can't read — `Request.parse`'s null, or a RuntimeException from it such as a NumberFormatException for
`-n x`, caught by serve, which prints `Error: <exception>` and **plays on** — "Could not load deck - x", "Unknown AI
profile - x"; or a Throwable escaped from a game: then `bye|error` and exit 1).

Python parses every protocol line with **`runner.serve_event(line)`** (frozen; ValueError for a malformed `DLSERVE|`
line; `runner.SERVE_PROTOCOL = 1`, `SERVE_STATUSES`, `RECYCLE_REASONS`, `SERVE_HEAP`).

### 6.3 Mapping to today's readers
- A chunk's output = the lines between `begin` and `end`. PP feeds them to a **new `LogReader(deck1, names,
  card_log=True)` per chunk** (deck1 = `seeds.deck1_side(first, flip)`); `LogReader` passes over `Simulation mode`,
  keeps the DLENGINE fields, reads games as from a batch. Never feed `DLSERVE|` lines to a LogReader.
- Game i of the chunk is the result's game `first + i`: PP adds `"g"` to each game dict when merging.
- `reader.failure(games, None)` rules apply per chunk (unsupported card / load errors fail the chunk; a chunk with
  fewer games than asked is fine when the end status explains it).
- JVM noise: `WARNING: A terminally deprecated method in sun.misc.Unsafe...` prints once per JVM, inside the first
  game that triggers it (measured in base). Any comparison of serve output with one-shot output must drop lines
  starting `WARNING:` (e3's compare.py did).

### 6.4 Exits Python must handle
Worker exits with no `end` (crash, `kill`): the chunk's finished games count (each game stands alone in v2), the
rest are re-queued under §9's retry rule. No `ready` within `runner.HEADER_TIMEOUT` (180 s), or no `Game Result` for
`clock_s + GAME_GRACE` while a request plays: Python kills it (process job) and treats it as a crash. `end|error`
fails the rest of the chunk at once, never retried (§9; games it finished before a Java error, if any, count);
`bye|error` after it means the worker exits (start another when needed).

### 6.5 Recycling (who decides)
- **Java** (base's `DeckLabServe`, the Boundary and the last-game check) ends a request with `recycle` after a game
  that hit its clock, had an AI timeout or a live eval thread (`Signals`, which J's AiController copy updates, §19),
  or crashed, and exits. With J's copy in the jar the next game never starts after an AI timeout.
- **Python** taints a worker when a game it reads has `r == "timeout"` or `ai_to > 0` (the fallback when J's copy
  doesn't fit this Forge build and the `Signals` stay 0, and a second line of defence otherwise): it immediately
  `reader.close()`s that chunk's LogReader (so no later game of the chunk counts) and **kills the worker at once**
  (`processes.kill_process`; no cancel/quit dance: the game after the tainted one may already be running on a
  corrupted RNG, and nothing it prints is kept). The slot is released at its death; a fresh worker starts when
  needed. The chunk's games after the tainted one (and its unplayed ones) are re-queued with the same numbers. The
  tainted game itself counts (as today).
- Reason: a timed-out eval thread or a clock-stopped game thread can keep drawing from MyRandom, which per-game
  reseeding hands to the next game; a crash can leave static maps half changed.
- **Safety net (PP):** a worker quits (`quit` after its `end`) once it has played `WORKER_MAX_GAMES` (2,000) games, or
  when an end line's `heap_mb` passes 75 % of its `-Xmx`; a fresh one replaces it when needed. `pool.status()` shows
  each worker's games and last `heap_mb`.

### 6.6 What base ships
`DeckLabServe` (protocol, cancel, recycle on clock stop, AI timeout and crash, argument errors without exiting, the
heap report, no forge.log tee) from the e3 prototype, `Signals`, `GameRecord.aiTimeouts`/`Played.last`, the DLENGINE
`gamepatchids` field, the guarded log read, `Request.parse`'s v2 validation, strict `Seeds.parseStream`, and
`WarmState` with the prototype's reset. Measured in base (2026-10-03, 1 worker, v1 requests): requests reproduce
one-shot games (cold first request and warm repeat, `WARNING:` masked), cancel stopped at a boundary, quit exits 0,
malformed requests (`-n x`, `-s` with no value, `-dlgame` without `-s`, with `-m`, with upper-case hex) end with
`error` and the worker plays on, forge.log doesn't grow; cardlog-check passed on the base source (20 Constructed and
4 Commander games). PJ owns `DeckLabServe` and `WarmState` from here. The byte-identity claim is "same games as a
fresh process, with the §4 masks, except the identity-hash residual" (§4).

---

## 7. Warm state (PJ: `WarmState`)

- `snapshot()` once after `FModel.initialize` (sim and serve both call it); never throws, notes `problem()`.
- `reset()` before **every serve request** (DeckLabServe) and before **every v2 game** (EJ's playGames, sim and serve).
- Base resets: the 7 static id counters (SpellAbility, StaticAbility, ReplacementEffect, SpellAbilityStackInstance,
  Game, Trigger `maxId`; CombatView `nextId`), `AiCache.clear()`, `ChangeZoneAi.multipleCardsToChoose` emptied.
- PJ adds what's needed for identical replays: `Card.cp2card` / `getCardForUi` (v-r05) — **not** a plain clear:
  `snapshot()` records cp2card's key set right after `FModel.initialize`, and `reset()` removes every other key (in
  the game path it's filled only by CardView merged-card views, `CardView.java:1052`, and `getBackup`, each fill
  allocating SpellAbility ids from a Card with no game); and anything the warm-equivalence check finds; keeps
  reflection names in one place (`COUNTERS` and its neighbours); must stay cheap per game (it runs every game).
- **Not WarmState's:** a crashed game (exception or StackOverflowError in `startGame`) may leave Forge's
  unsynchronised static lazy maps half updated (r2: `Keyword.cardKeywordSetLookup`, `TrackableTypes.enumTypes`,
  `SpellApiToAi.apiToInstance`); serve recycles after it (`crash`, §6.2) rather than repairing them. The identity-hash
  order of Cards and Players (§4's residual) can't be reset at all.

---

## 8. Per-game seeds (frozen: `seeds.py`, `Seeds.java`)

```
mix(x)            = SplitMix64 output: z = x + 0x9E3779B97F4A7C15; z = (z ^ z>>>30) * 0xBF58476D1CE4E5B9;
                    z = (z ^ z>>>27) * 0x94D049BB133111EB; z ^ z>>>31      (64-bit wrap)
game_seed(b,s,g)  = mix(mix(mix(b) ^ s) ^ g) & 0x7FFFFFFFFFFFFFFF          (a long of 0 or more)
stream_of(a, b)   = first 8 bytes (big-endian) of SHA-256("decklab-seed-stream-1\n" + sorted card_shas joined by "\n")
deck1_side(g,flip)= (g // 25 + flip) % 2      side 0 = the smaller card_sha; flip = the result's seeds.flip (§12)
SCHEME            = "splitmix64(base,stream,game);seat-block-25"            (goes in the engine id)
```

**The flip belongs to the result**, not the run: the run that creates a decklab-kind result sets `seeds.flip` (0, or
1 when `--a-first` asks for entry_a as deck 1 in block 0 and entry_a is side 1), and every later run of that result
plays with the stored flip, so 25-game seat blocks alternate over the whole result (which R15's pairing relies on)
and any game's deck order can be worked out from the result alone. A later run whose `a_first` would want the other
flip plays with the stored one and says so once (CLI: one stderr line; the page never sets it). PP stores it and
passes it to `deck1_side`; v1 and plain-kind results have no `seeds` record and keep `a_first` per run as today.

**Test vectors** (`seeds.TEST_VECTORS`; Java and Python checked equal by `test_forge_contract`):

| base | stream | game | seed |
|---|---|---|---|
| 0 | 0x0000000000000000 | 0 | 2558736989570252433 |
| 1 | 0x0000000000000000 | 0 | 3569668903477806787 |
| 1 | 0x0000000000000000 | 1 | 7806873273932414515 |
| 1 | 0x0123456789abcdef | 0 | 2291207570733865206 |
| 1 | 0x0123456789abcdef | 799 | 751406823689115176 |
| -5 | 0xffffffffffffffff | 12345 | 6576315120302096085 |
| 1 | 0xfedcba9876543210 | 2^40 | 1845434521246174757 |

`mix(0) = 0xE220A8397B1DCDAF` (SplitMix64's published first output). Streams are stored as `stream_hex()` (16
lower-case hex); `parse_stream` is strict. A result's base: `SEED_BASE` (1) or `--seed-base` (must be ≥ 0; PP
rejects negatives). R15 (wave 3) will pass a variant the base deck's stream; nothing in wave 2 may assume the stream
is `stream_of` the result's own sides — read it from the result.

---

## 9. Chunk policy (PP)

- A run plays game numbers `[next_game, next_game + games)` of its result (`next_game` 0 for a new result, §12).
- **Seat blocks:** cut that range at multiples of `seeds.SEAT_BLOCK` (25). A chunk never spans a block; its deck order
  is `deck1_side(first, flip)`.
- **Dispatch:** one queue for the whole pool, FIFO by run submission **within a priority**: runs with
  `by="replay"` (§16) are low priority and get a chunk only when no other run has queued games, so the page's and
  the command line's runs never wait behind a replay. A free worker (with a slot, §11, and the chunk's launch
  identity, §10) takes the oldest run that has queued games and cuts the next chunk from its first queued block, of
  size `min(block remainder, CHUNK_MAX = 25, run's batch cap, max(CHUNK_MIN = 5, ceil(Q / (2 * W))))`, Q = games
  queued over all runs, W = the pool's worker limit. So big queues get 25-game chunks and a run's last games spread
  across workers (and other runs' chunks fill one run's tail).
- **Re-queue (the one rule; §6.4 points here):** only after a taint, a recycle or a worker that died (no `end`, a
  watchdog kill): the chunk's games after the last one kept go back at the **front** of their run's queue with the
  same numbers. Each game number may be re-queued at most `MAX_REQUEUE = 2` times; a game that would go back a third
  time becomes, with the rest of its range, a failed chunk (§12 `failed`), its games unplayed.
- **Fail at once, never retried:** a chunk whose request ends `error` (arguments, "Could not load deck", "Unknown AI
  profile", a Java error), or whose reader says `reader.failure(...)` (unsupported cards, load errors, every game a
  crash), or whose DLENGINE line fails `engine.check_echo`, is a failed chunk at once; the run's other queued chunks
  are dropped and its playing ones cancelled, as these repeat for every chunk; the run's `failure` is that sentence
  (the same as v1's for a failed batch).
- **Stop** (the page's Stop, `stop_matchup`, `api.stop_jobs()`, Ctrl+C): the run drops its queued chunks, and for
  each playing chunk **`reader.close()`s it at once** and sends `cancel`; the run then saves its finished games
  straight away (within about a second, as v1 does after killing its processes), without waiting for any `end`. A
  cancelled worker keeps its slot until its `end` (or its death) and is idle after it. Unplayed numbers of a stopped
  run are never played later (the next run starts at `next_game` = the end of the last planned range), as v1 never
  reuses a seed.
- `run(..., workers=k)`: at most k chunks of this run playing at once (default `forge_workers`). `run(..., batch=n)`:
  chunk cap n (≤ 25); games may then be any multiple of n. Without batch, games must be in GAME_CHOICES (as today),
  **except** `run(..., games=n, exact=True)` (replay), which accepts any n ≥ 1 (the keyword is in base's signature;
  base ignores it).
- Per-run progress: `progress(done, total, detail)` as today (`wins`, `other`, `games_per_min`, `eta_s`,
  `failed_batches` = failed chunks, `waiting` = `slots.WAITING` or a pool sentence while none of its chunks play),
  after **every game** (not every chunk), remote runs included (the pool service streams per-game events, §10).

---

## 10. Where a run plays, and the pool's lifetime (PP)

API (stubbed in base `pool.py`):
- `Pool(setup, *, name, idle_s=None, workers=None)`, `pool.close(wait=None)`, `pool.status()`.
- `session(*, local=False)` context manager; `run(..., pool=session_value)`.
- `server_pool()`, `start_server_pool()`, `stop_server_pool(wait=None)`, `status()`.
- `run(..., local=False, pool=None)` (signature already in base; ignored there):
  - `pool` given → that one; in the server → `server_pool()`;
  - CLI, `local=False` → the running server's pool service if it is up **and** compatible, else a local pool for the
    run; `local=True` → always a local pool (closed when the run ends).
  - The server going away mid-run: the CLI run finishes its remaining chunks in a local pool (or stops and saves —
    PP's choice; say which in the docstring).

**Launch identity (every chunk carries its run's).** A run works out, when it starts, `launch = {"argv":
serve_command(setup), "cwd": setup["forge_dir"], "user_dir": setup["user_dir"], "game_patches": setup.get(
"game_patches") is not False}` from its own fresh `_setup()` and `simjar.card_log()`. A worker remembers the launch
it was started with and only ever plays chunks of that launch; an idle worker whose launch no queued chunk wants is
retired (`quit`), and a new one is started when needed. So a Forge upgrade, a new card-log jar (cardlog-check passed,
a source edit), another `java`, `xmx` or user folder mid-life never has old workers playing a new engine's games.

**Compatibility (CLI → the server's pool).** The service advertises, **worked out per request** (not at server
start), the identity it would start workers with now: `simjar.source_sha256()`, the card-log jar's stamp hash, Forge
version **and build**, the fitting game patches, `engine.current(...)` minus sides (EP's), `java`, `xmx` and
`forge_pin`. The CLI works out the same from its own checkout; any difference → a local pool, with one stderr line
saying which setting differs (so M3's pinned-vs-unpinned comparison, `forge_pin: false`, never lands in the server's
pinned pool). The run record's `settings.xmx` is the xmx the games were played with (the server's when remote).

**Pool service (CLI → server).** 127.0.0.1 only, random port, a random token. State file
**`forge-pool-<pid>.json` inside `slots.folder()`** (not its parent: `tests/__init__.py` points `DECKLAB_FORGE_SLOTS`
at a fresh `mkdtemp()` per suite, so parallel suites and test servers never meet; `slots.status()` only globs
`slot-*.lock`), written atomically (`common._write_atomic`), holding pid, port, token, checkout (repo root), protocol
and the identity's static part; only the pid that wrote it deletes it (at stop; a dead pid's file is skipped and
may be deleted by the next server). The CLI reads every `forge-pool-*.json`, skips files whose pid is dead or whose
port refuses the token, prefers a server of its own checkout, and otherwise takes any compatible one. JSON lines.
The CLI keeps planning, merging, locking and saving; the service only plays chunks and streams back **per-game
events** (each game as it's read: `{"g", game dict, casts, lands, cards delta}`, then the chunk's end with its
engine echo) so the CLI's progress and ETA stay live. Decks are passed by absolute .dck path (any checkout on the
PC). **When the connection closes, or misses its heartbeat** (the CLI sends one every 5 s; 20 s without one), the
service drops that connection's queued chunks and cancels its playing ones (`reader.close()` + `cancel`, as Stop).

**Starting workers.** While `runner._first_use_marker(user_dir, version)` is missing (a fresh user folder or Forge
version), the pool starts **one** worker alone and waits for its `ready` before starting any other, as `runner._play`
does for cold batches; it touches the marker after that `ready`. **When serve can't start** (`DLSERVE|fail`, exit 3,
no `ready` within `HEADER_TIMEOUT`, or two workers of one launch dying before `ready`), the pool falls back to
playing that launch's chunks as one-shot DeckLabSim v2 processes (`runner.build_command(..., v2=...)`, the same
games), each in its slot; it says so once in the log and in the run's progress (`waiting`/detail sentence), and the
run record gets `"fallback": "<why>"`. It tries serve again for the next run.

**Server.** Starts the pool and its service at start-up (workers start lazily with the first chunk). `FORGE_JOBS`
becomes `max_running=4` (several matchups at once share the queue); `max_queued` stays 10. Stopping, in this order:
1. `_serve`'s finally: `api.stop_jobs()` (every run stops: Stop's rule, §9: readers closed, finished games saved at
   once), then `_wait_for_matchup()` (runs save), **then** `stop_server_pool(wait=FORGE_STOP_WAIT)`, which sends
   `cancel`/`quit`, waits a few seconds at most, and kills what's left (process job). The pool never closes before
   its runs have saved.
2. `_console_handler` / `_session_end_handler` (window closed, logoff; Windows ends the process about 5 s later):
   stop the jobs, `FORGE_JOBS.join(CLOSE_WAIT)`, then kill the pool's workers at once (no waiting for `end`).
3. The page's Stop (`api.forge_runs.stop_matchup`, which waits `STOP_WAIT` = 10 s for the run to save) answers
   well within it, because a stopped run saves without waiting for workers; `server.py`'s `FORGE_STOP_WAIT` (15 s)
   and `CLOSE_WAIT` (4 s) stay as they are.
PP's tests, with the fake's `delay=S`: Stop saves in under 2 s while a game is still "playing"; server stop leaves no
fake worker alive (`test_forge.alive`).

**Idle and memory.** The server's workers quit after `forge_pool_idle_s` (900) with nothing to play; the Pool object
stays and restarts workers on demand. A local pool's workers quit after `LOCAL_IDLE_S = 30` s idle. A **live-JVM cap**
keeps memory bounded while the owner uses the PC: the server keeps at most `forge_workers − (slots held by other
processes)` workers alive (it checks `slots.status()` when a worker goes idle and every 10 s while it has idle
workers, and quits its longest-idle ones beyond that), so idle warm JVMs never sit beside another process's computing
ones; live Forge JVMs on the PC stay at about `forge_workers` (each up to `-Xmx` plus ~0.3 GB).

**No orphan JVMs:** every worker is started through `processes.start_process` (process-wide KILL_ON_JOB_CLOSE job,
BELOW_NORMAL, own nested job), with a stdin pipe (PP adds the option). The server's crash or kill takes every
worker with it.

**Config validation (PP):** `pool.py` reads `forge_pool_idle_s` (an int of 0 or more) and `forge_pin` (a real
bool: `"false"` is not false) the way `install._setup` reads `forge_workers`; a bad value falls back to
`config.DEFAULTS` with one log line. Tests cover both.

---

## 11. Slots and pinning (PP)

- **A worker computes only while it holds a slot.** It claims one (`slots.claim(1, wait=False)`) before it starts its
  JVM (start-up computes) and before each chunk, and releases it at the chunk's `end` (or its death). An idle warm
  worker holds no slot, so cold fallback runs, cardlog-check and other pools get the CPU budget.
- At most `forge_workers` workers alive per pool (more could never compute at once), and the live-JVM cap of §10.
  Machine-wide, at most `forge_workers` Forge processes compute at once (wave 1's budget, unchanged).
- **Slot k ↔ core k:** cores ordered V-Cache CCD first (largest L3 first, then by first logical CPU), from
  `GetLogicalProcessorInformationEx` (RelationProcessorCore + RelationCache L3), in `cores.py` (PP; base ships a stub
  with the frozen API `core_masks()`, `mask_for(slot)`, `pin(pid, slot) -> bool`, which pins nothing, so PJ's
  serve-check can call it before PP lands). Slot k pins to core k's mask (both hyper-threads: CPUs 2k, 2k+1 on this
  PC) with `SetProcessAffinityMask` before the request is sent (and at JVM start). Lowest slot ids are taken first,
  so CCD0 fills first.
- Pinning doesn't change the JVM's sizing: `-XX:ActiveProcessorCount=2` fixes `availableProcessors()` (ForkJoin,
  virtual-thread carriers, GC threads) whatever the affinity. The warm check pins its worker anyway (§18), so
  "pinning plays the same games" is checked per Forge version, not assumed.
- A worker re-claiming prefers the slot it held last (PP may add `slots.claim(..., prefer=id)`).
- Fallback: topology unreadable, odd (SMT off, more cores than slots...), or `SetProcessAffinityMask` fails → run
  unpinned, log once. `forge_pin: false` → unpinned (for M3's comparison).
- APC=2 stays explicit (`runner.JVM_FLAGS`); BELOW_NORMAL stays (`processes._SPAWN_FLAGS`).
- Cold fallback batches may be pinned the same way (PP's choice; same mapping).

---

## 12. Saved result, v2 (PP writes the shape; EP's and C's fields inside)

```jsonc
{
  "key": "<64 hex: the engine id, §13>", "format": "Constructed", "forge_version": "2.0.15",
  "run_version": 2,                                   // common.FORGE_RUN_VERSION (EP bumps 1 -> 2)
  "engine": { ...engine.result_fields(eng): the canonical description, §13 },   // EP
  "settings": {"clock_s": 120, "ai": ["Default", "Default"], "xmx": "1024m"},   // xmx: the one games played with
  "seeds": {"scheme": "<seeds.SCHEME>", "base": 1, "stream": "<16 hex>", "seat_block": 25, "flip": 0},  // decklab only
  "next_game": 800,                                   // decklab kind only: the next game number a run plans
  "sides": [{"card_sha", "dck", "card_count", "kind", "cards", "seen_as",
             ...engine.side_fields(eng, side, echo): "engine_id", "ai", "ai_sha", "auto_profile": {"flag": bool,
             "avg_cmc": int} }, ...],              // EP
  "runs": [ run record ],
  "batches": [ one MERGED record per run (decklab kind) | today's per-batch records (plain kind) ],
  "failed": [ ... ],
  "created", "updated"
}
```

**Merged batch record (decklab):** `{"n": <run ordinal>, "first": <lowest g>, "games": [game dicts + "g", sorted by
g], "casts": [{}, {}], "lands": [{}, {}], "cards": <merged card record, if any>, "chunks": <count>, "wall_s": <sum of
chunk walls>}` — no `"seed"`, no `"deck1"`. Consumers (`views`, `saved._pooled`, `_pooled_cards`, `ai`) read
`games`/`casts`/`lands`/`cards` exactly as before. Cards merge with `cardlog.merge_record` (frozen; sums any record
length, so C's v3 needs nothing from PP).

**Failed (decklab):** `{"n": <run ordinal>, "first": g0, "games": count, "error": "<plain sentence>"}`.

**Run record (decklab):** today's keys with these meanings — `batches` = chunks planned, `played_batches` = chunks
with games kept, `partial` = chunks cut short, `batch_games` = largest chunk, `seeds` = `[first g, last g]` played,
`workers` = most chunks playing at once, `most_running` = same, `startup_s` = worker start-ups waited for (None when
all warm), `waited_s`, `wall_s`, `stopped`, `stopped_by`, `failed`, `failure`, `error`, `card_log` (true) — plus new
keys `pool` (`"server"`, `"local"`, `"remote"`), `chunks`, `recycled`, `requeued`, `games_from`, `games_to`,
`engine` (the engine id), and `fallback` (the sentence, only when serve couldn't start and chunks played as one-shot
processes, §10). `views.view` already passes `pool`, `chunks`, `recycled`, `requeued` (base). `pool` is `"server"`,
`"local"` or `"remote"` (a CLI run in the server's pool).

**`saved._is_result` (PP):** accepts v1 files unchanged; for `run_version >= 2` decklab results requires `n` and
`first` ints in batches and failed instead of `seed`, an int `g` (0 or more) in every game, and `seeds.flip` 0 or 1;
plain-kind v2 results keep the v1 batch shape.

**v1 files** (`run_version` 1, no `engine`): never rewritten, never pooled with v2, read and shown with the label
"v1" (EP). Their keys differ from every v2 key, so "Play more" from a v1 result's page posts the decks and starts the
v2 result (the page says so first, EP).

**Plain-kind results:** today's shape + `engine`/`run_version` 2/side fields; `kind: "plain"` in the engine.

---

## 13. Engine id (EP: `engine.py`)

Canonical JSON = `json.dumps(desc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`; id = SHA-256 hex.

```jsonc
desc = {
  "id_version": 1,                       // this description's own format
  "run_version": 2,
  "kind": "decklab" | "plain",
  "forge": "2.0.15",                     // install.forge_version(); NOT the build (cardlog-check gates builds)
  "format": "Constructed" | "Commander",
  "clock_s": 120,
  "seeds": seeds.SCHEME | "batch",       // decklab | plain
  "performance_mode": true,              // runner.PREFERENCES' value (EP adds PERFORMANCE_MODE=true)
  "game_patches": ["<semantic id>", ...],// card_log["game_patches"]: those BUILT INTO the jar (decklab); [] for plain
  "overrides": "none" | "<sha256>",      // what's deployed in <user dir>/Forge/custom/cards (none today)
  "sides": [[card_sha, ai_name, ai_sha], [card_sha, ai_name, ai_sha]]   // pairs, sorted (A-Reckless/B-Default
}                                                                      // != A-Default/B-Reckless)
key        = sha256(canonical(desc))
side id    = sha256(canonical({**desc without "sides", "side": [card_sha, ai_name, ai_sha]}))
```
- `game_patches` = `simjar.card_log()["game_patches"]` (base): the ids of `GAME_PATCHES` whose copy **fits** Forge's
  jar and so was built in (`simjar.game_patch_ids(fitting_patches)`; the jar's stamp names them, so new ids are a new
  jar). Never "every declared patch": a reinstalled Forge build whose class SHA no longer fits builds a jar without
  that copy, and its games must not pool under the copy's id. The DLENGINE echo (`gamepatchids`, §5) names the ones
  actually loaded; `check_echo` compares them.
- `ai_sha` = SHA-256 of `<forge_dir>/res/ai/<name>.ai` bytes. **Keys must not change while Forge's folder is
  unreachable** (the page lists results then): remember what was read **per Forge version and build** in the data
  folder — `ai_sha`s, and the last `card_log()`'s `game_patches` — as `install._remember_version` does for the
  version, and use the remembered values when the folder (or Forge's jar) can't be read.
- **As built (EP, recorded at its merge)**, three details the description above leaves open: `ai_sha` hashes the
  `.ai` file **with CRLF made LF** (`engine._file_sha`), so a reinstall's line endings don't change keys;
  `overrides` may also be `"unreadable"` (`engine.UNREADABLE_OVERRIDES`: the folder is there but can't be listed or
  read); and the two `sides` triples are sorted **by their canonical JSON** (`engine.describe`). Remembered values
  are kept per value: one that can't be read for a moment (an `.ai` file, the jar) uses the remembered one for that
  build, nothing unread is remembered, and nothing at all for a jar whose build can't be read.
- `kind` for `matchup_key(a, b)` (no Java, page loads): from `install.status()["card_log"]["ready"]` (cheap, cached);
  EP documents the edge (card log off → the page shows the plain engine's result).
- **Two ids per side for consumers:** "the current side id" depends on the kind, which flips whenever the card log
  becomes unready (no JDK, a check pending, a build problem). Per-card data only ever comes from the decklab kind, so
  per-card consumers use **today's decklab-kind side id** (EP computes it without Java, from today's settings and
  the remembered patches) whatever the card log's readiness; only win-rate consumers follow the current kind.
- **Not keyed** (measured neutral): lazy loading, warm vs fresh, APC, affinity, the mulligan copy, R14a, BELOW_NORMAL,
  chunk sizes, which worker played.
- `engine.current(setup, card_log)`, `key(a, b, eng)`, `matchup_key(a, b)`, `result_fields(eng)`, `side_fields(eng,
  side, echo)`, `check_echo(eng, echo)` keep their base signatures (callers in `runner`, `lists`). `check_echo`
  must reject a chunk whose DLENGINE says `perf` other than the engine's, `seeds` other than `game`, `gamepatches=off`,
  `gamepatchids` other than the engine's `game_patches` joined by `,`, or `cardlog=off` (PP fails such a chunk at once
  with the sentence, §9).
- **Consumers (EP), filter or label every one that pools by card_sha:**
  - `cardstats.list_cards`, `ai.ai_limits(results=...)` (its card data and never-cast numbers) / `ai.list_ai`: pool
    only sides whose `engine_id` is **today's decklab-kind side id** of that list, whatever the card log's readiness
    (casts from plain-kind results may still be pooled by their own id, as the current kind's); CardStats gains
    `"other_engine_games"` (counted games left out).
  - `views.results` / `results_for`: every result, each with `"engine"` (`views._engine_view`).
  - `views.view` / `list_item`: `"engine": {"kind": "decklab"|"plain"|"v1", "run_version": int, "current": bool |
    None, "words": "<plain sentence>" | None}` (`current`: a new run of these two lists would add to this result;
    None when that can't be told). When the kind flips (card log off ↔ on), results of the other kind are labelled
    "Earlier engine" until it flips back; EP's docstring says so.
  - `views._page_side`: maps the stored `auto_profile` dict (`{"flag", "avg_cmc"}`) to the page's `auto_profile`
    (the flag: bool, or None when unknown).
  - `saved._stored`: EP may add an engine filter argument; default stays "every result".
  - `api.forge_runs`: `_TodaysLists`/`_item_json`/`_deck_matchups` carry the label; the deck page's per-card and
    never-cast numbers use the decklab-kind ids above; `side["auto_profile"]` on the page's sides;
    `_matchup_json` for a matchup opened by its decks adds `"earlier": [keys]` (other-engine results with the same
    sorted card_sha pair and format, newest first) so the page can link to them when today's engine has none.
  - `web/matchups.js`: an "Earlier engine" chip on results not of the current engine; on such a result's page the
    play box says "Playing more starts a new result with today's engine"; each deck's auto-profile flag ("Forge's
    AI plays this deck as a slower, non-aggro deck in every game") where it's on; "How these games were played"
    worded by engine kind (v1 and plain: today's batch wording; decklab: "each game has its own seed and a coin flip
    for who starts; the decks swap seats every 25 games", with the game count, not `view["seeds"]`, which counts v1
    batches and is frozen); after any run answer (`POST /api/matchup/run`), the page **follows the answer's `key`**
    (polling, Stop and the URL), as "Play more" on a v1 or earlier-engine result starts a new key; a "not played yet"
    matchup with `earlier` keys links to them.
- `runner.PREFERENCES` gains `PERFORMANCE_MODE=true` and `_prepare_user_dir` keeps `custom/cards` as Deck Lab's
  (EP: hash what's there; mirroring a repo override folder is wave 3's R10).

---

## 14. Card log RECORD_VERSION 3 (C)

Exactly `sim-investigation/w1/m8/notes.md` §2:
- `cardlog.ROW_FIELDS += ("early_games", "early_wins")`, `RECORD_VERSION = 3`, `saved.CARD_TALLIES = 10`. DL format
  stays 1 (no Java change).
- `early_games` = 1 when any copy was in the side's hand by the side's own 3rd turn: in the kept hand (the same kept
  set as "drawn"), or moved to Hand (any zone) at a global turn from 1 up to the turn on which that side's 3rd own
  turn began (inclusive); when that turn never came, any drawn copy. `early_wins` = early_games × won.
- Turns: `Game.turn(turn, seat)` (hook in base, LogReader calls it on every `Turn:` line; C fills the body). Use the
  Turn lines, not `round_of()`.
- `saved.py`: well-formed records of v2 (8 numbers) **and** v3 (10) both count; v1 stays "old". The 8 shared tallies
  pool over v2+v3; `early_*` over v3 batches only, with their own denominators (v3 games and wins, kept in the
  pooled dict and per stratum). v3 checks: `early_games ≤ drawn_games`, `early_wins ≤ min(early_games, drawn_wins)`,
  `wins − early_wins ≤ games − early_games` (v3 games).
- `cardstats.py`: with v3 data, judge "more"/"less" on the early split (Mantel-Haenszel, shrinkage, BH as wave 1);
  Row gains early numbers and `"basis": "early" | "drawn"`; without v3 data the drawn verdict stays, labelled as
  leaning with game length. Commander rows unchanged; lands unjudged.
- Page and CLI wording: "won more when in hand by turn 3" / "won less when in hand by turn 3" (`cli._print_cards`,
  `matchups-cards.js`, `deck.js`).
- The tests m8 lists (3rd own turn counts; the opponent's next turn doesn't; a game ending before turn 3; kept hand
  vs bottomed; an Eternal Witness return; Karn restart still fails; v2+v3 pooling; the new bad-record checks).
- Only decklab runs keep card records (plain Forge has no card log). A run's merged batch (PP) holds one record of
  one version; `merge_record` refuses to mix versions (a run never does).

---

## 15. API JSON fields

| Where | Field | Owner |
|---|---|---|
| `GET /api/matchup` `result` (view) | `engine` (§13); runs gain `pool`, `chunks`, `recycled`, `requeued` | EP / base |
| `GET /api/matchup` (by decks) | `earlier`: keys of other-engine results of the same pair and format | EP |
| `POST /api/matchup/run` answer | `key` (the result the run adds to: the page follows it) — already there; the page now always uses it | EP |
| `result.cards` (CardStats) | v3 early fields, `basis`, `other_engine_games` | C / EP |
| `sides[]` | `auto_profile` (bool or None: `_page_side` maps the stored dict to its flag) | EP |
| list items (`/api/matchups`, deck page) | `engine` | EP |
| `forge` (`status()`) | `"pool": pool.status()` (None outside the server) | PP |
| `job` | `waiting` may also be the pool's sentence ("Waiting for other matchups ahead in the queue.") | PP |

---

## 16. Command line

| Command | Behaviour | Owner |
|---|---|---|
| `play ... [--local]` | as today; plays in the server's pool when one is up and compatible, else a local pool for the run (one stderr line says why); `--local` forces local; `--batch` caps chunks, `--seed-base` sets a new result's base (≥ 0), `--a-first` sets a **new** result's seat flip (§8; on an existing result it's ignored with one stderr line); prints the engine lines (`_engine_lines`, EP) after the trust lines; `_print_play` says "warm workers" instead of "slowest start-up None s" when `startup_s` is None | PP (`_play_args`, `_cmd_play`, `_print_play`), EP (`_engine_lines`) |
| `list` | marks results of another engine | EP |
| `cards` | v3 wording | C |
| `cardlog-check` | v2 legs (§18) | EP |
| `replay [--results-dir D] [--dry-run] [--local] [--matchups N] [--json]` | every saved result not of the current engine whose two lists are both still current (each side's last `seen_as` id+version gives today's card_sha), and whose current-engine result has fewer games: plays the difference (`by="replay"`), N matchups at once (default 4) in **one** `pool.session(local=...)` (the server's pool when up; replay runs are low priority there, §9). Idempotent: run again, it plays only what's missing. `--dry-run` lists matchups and total games. **Build and test it; don't run it on real data in wave 2.** The cases: **(1)** it refuses (exit 1, one sentence) unless today's kind is decklab (the card log ready), so it never replays into the plain engine; **(2)** old results are grouped by (sorted card_sha pair, format); the target is the **largest** counted-games total among a group's old results (v1 at different clocks, plain, earlier v2 engines), and the difference is target − the current-engine result's games (none when ≤ 0); **(3)** a matchup whose run raises BUSY (the page or another process is playing that key) is skipped and listed at the end ("still playing: ..."), never retried in the same call; **(4)** Ctrl+C: the main thread catches KeyboardInterrupt, stops every run through its progress callback (each callback raises `common.Stopped`, one of `common.STOPS`, at its next call, and the run stops as §9's Stop says) and joins all threads, so each saves its finished games; `_interrupts_held` is only used in the main thread; **(5)** in the server's pool its runs are `by="replay"`, low priority (§9), so the user's page runs never wait behind them. EP tests it against a stand-in session passed as `run(pool=...)` (PP adds one integration test with the real `pool.session` after its merge, §20). | EP |
| `pool [--json]` | the server pool's status | PP |
| `serve-check [--games N]` | the warm-equivalence check alone (§18) | PJ |
| `status`, `slots`, `audit` | unchanged (status prints the pool line, PP) | PP / frozen |

`cli.COMMANDS` and `_main` are frozen; each owner fills its `_<name>_args` / `_cmd_<name>` pair.

---

## 17. Config settings (`decklab/lib/config.py`, frozen in base)

| Setting | Default | Meaning |
|---|---|---|
| `forge_workers` | 16 | the PC's budget (wave 1) and a pool's worker limit |
| `forge_pool_idle_s` | 900 | the server's warm workers quit after this long with nothing to play (an int of 0 or more; else the default, logged once: PP validates, §10) |
| `forge_pin` | true | pin a computing worker to its slot's core (a real bool; `"false"` or any other non-bool → the default, logged once) |

---

## 18. Checks

**cardlog-check v2 (EP rewrites `cli._cardlog_check` and its helpers; records with `simjar.record_checked` /
`record_failed` as today, per Forge version + build + source).** Legs, each Constructed (line for line) and
Commander (outcomes), on the check decks, seed base `CHECK_SEED`, stream `stream_of` the two check decks:
1. **Parity with plain Forge:** one DeckLabSim `sim -n K -dlgame <stream> 0` with game patches **off**, vs K plain
   Forge `-jar sim -n 1 -s game_seed(base, stream, g)` processes (deck order of each game's block), compared game by
   game with §4's masks (`_games_text`: timings, the Game Result ordinal, stack-trace frames, attackers sorted, DL|
   lines dropped). Slots for every process (`_check_slot`), K small (Constructed 12, Commander 3 — EP's numbers).
2. **Card log on vs off:** `sim -n K -dlgame ...` with and without `-dlnocardlog`, game patches **on**, identical
   (DL| lines dropped, the same masks).
3. **Warm equivalence:** `servecheck.warm_leg(setup, folder, env, card_log, requests)` (PJ; frozen signature) —
   returns None or `("failed" | "unsure", [lines])`.
4. Card logs pass their checks; Commander games name both commanders (as today).

**Time limits:** a game that hit one of Forge's time limits makes the leg "unsure" (nothing recorded), as today, and
in v2 so does **every later game of the same DeckLabSim JVM, in both formats**: a clock-stopped game's thread or a
timed-out eval can draw from the next game's Random and touch the counters `WarmState.reset()` just put back. So on
the DeckLabSim side `_time_limit_game(..., earlier=True)` for Constructed as well as Commander; the plain side plays
each game in its own process, so only that game. Until EP lands, base's v1 check runs the card-log leg with game
patches off (`cli._check_run`), so J's game-changing patch can't fail it; base's `_games_text` already applies the
ordinal and frame masks, so R14a's frames (VirtualThread, shifted line numbers) can't fail it either once J merges.

**Warm-equivalence check (PJ, `servecheck.py`, `serve-check`):** one serve worker, **pinned** the way the pool pins
(`cores.pin(pid, slot)` for the slot it holds, when `forge_pin` is on; a no-op until PP's `cores.py` lands), plays a
set of v2 requests (Constructed and Commander; the same matchup split into chunks of different sizes, in an order of
its own, with another matchup's request between, and a repeat), each compared game by game with a fresh, unpinned
one-shot `sim` of the same arguments:
- **Constructed** line for line with §4's masks and `WARNING:` lines dropped, **DL| lines kept**. A game whose lines
  differ is played warm once more, alone (a one-game request for that game number), on the same worker: equal to the
  fresh game → **unsure** (the difference didn't come back: §4's identity-hash residual); different again →
  **failed**. Also **failed**: a different winner, starter or length; DL| lines that differ while Forge's lines are
  the same; a card log failing its checks.
- **Commander** by winner, starter and length (as cardlog-check), a difference → **unsure**; card-log problems and
  missing DL|commander lines → **failed**.
- Time limits: as above (that game and every later game of the same JVM, either copy) → **unsure**.
A per-Forge-version gate: it's a leg of cardlog-check, so the card log (and with it the pool) is used only when it
passes ("unsure" records nothing, as today).

**J's own check:** R14a identical logs (≥ 60 games): the comparison is the **jar built without the AiController
copy** (or plain Forge) against the jar with it, game patches off, with §4's masks (the copy has no off switch: it's
neutral); R14b determinism (same seed twice identical, patches on); no new exceptions; AI timeouts not up; R14a's
fallback to a platform thread exercised once (a test that holds `Signals.LIVE_EVALS` above 0, §19). ≤ 400 games,
≤ 4 processes.

**EJ's own check:** v2 parity (§4) on ≤ 20 Constructed games; v2 chunk independence (games [0,10) in one request vs
[0,4)+[4,10)) identical with §4's masks; and once, the DLENGINE `autoprofile` flags compared with Forge's own answer,
`((PlayerControllerAi) p.getController()).pilotsNonAggroDeck()` read after `prepareAllZones` (a throwaway debug
print or test hook, not shipped), on the check decks plus one deck named "... Control" and one averaging over 3 —
so a Forge upgrade that changes the rule (`PlayerControllerAi.java:1447`'s TODO) is noticed. EJ keeps the
check as a script in its notes, so it can be rerun at merges (§21).

**PP's own check:** a real run through a 2-4 worker local pool (≤ 400 games) with `--results-dir` in scratch, pinned
(`forge_pin` true): games identical to one-shot v2 for the same numbers (§4's masks; a residual difference that
doesn't come back on replay is noted, not a failure); Stop saves within about a second; a test server on 127.0.0.1
(8643 up) with a CLI run submitted to it and the CLI killed part way (its chunks cancelled); no java.exe left
(Get-CimInstance). Then `serve-check` with pinning live (§21).

**Unit tests** need no Java (the fake); real-Forge tests stay behind `DECKLAB_FORGE_TESTS=1` (the seeds vector
test runs whenever a JDK is found: one source-mode `java` run, under a second).

---

## 19. Game-changing patches (J)

- `simjar.PATCHES[class file] = frozenset(SHA-256s of Forge's class files it may stand in for)` (wave 1 mechanism).
- `simjar.GAME_PATCHES[class file] = "<semantic id>"` (`simjar.GAME_PATCH_ID`) for a patch that changes games for a
  seed; a new id for any change to what it plays. Only the ones that **fit** are built in: `simjar._build` writes
  their list into the jar (`decklab/game-patches.txt`), the stamp names them (`stamp["game_patches"]`), and
  `card_log()["game_patches"]` gives their ids, which EP puts into the engine id (§13).
- A game-changing patch must play **Forge's own code** when `System.getProperty("decklab.gamePatches")` is `"off"`
  (read once, static final). Neutral patches ignore the property.
- **Keep Forge's line numbers** where practical: put each copy's Deck Lab header note at the **end** of the file (not
  above `package`), and the changes on as few lines as Forge's code had, so stack traces line up with Forge's (the
  checks drop frames anyway, §4, but logs stay readable).
- **R14a** (neutral): `forge/ai/AiController.java` from `sim-investigation/w1/r14a/src` (virtual "Game AI Eval"
  thread, name kept, no `t.stop()`), pinned to `334523f76b7aa3f00bfd38f2746f5bf64aecdb67b8bdae78284f4befa0759e72`; its
  `$1` inner class comes along. Same members as Forge's (javap). Plus the **Signals hook** (§2, frozen in base):
  - the eval task's body starts with `Signals.LIVE_EVALS.incrementAndGet()` and ends with a `finally` that
    decrements it (inside the task, so it's down before the future completes);
  - the `TimeoutException` branch (where Forge prints "AI eval thread at timeout") does
    `Signals.AI_TIMEOUTS.incrementAndGet()`;
  - **a virtual thread only when `Signals.LIVE_EVALS.get() == 0`** as the eval starts; otherwise (an earlier eval
    is still running: one that timed out and can't be stopped) a platform thread, as Forge does. Reason: virtual
    threads run on `ActiveProcessorCount` = 2 carriers, and a CPU-bound virtual thread never gives its carrier up;
    two stuck evals would block every later eval in that JVM (each decision timing out after 5 s) until the clock
    stops the game. Serve recycles after the first timeout anyway; this protects one-shot v2 `sim -n K` (the checks,
    the serve-failure fallback). `JVM_FLAGS` stay as they are.
- **R14b** (game-changing, id e.g. `"attack-requirements-in-order-1"`): `forge/ai/AiAttackController.java` — the
  forced-attacker tasks (`AiAttackController.java:883-961` at forge-2.0.15) run as a plain loop **in attacker order
  (`this.attackers`)**, no executor and no timeout, **each task's body wrapped in `try { ... } catch
  (RuntimeException e) { }` and the loop going on**: `invokeAll` stores a task's exception in its Future and ignores
  it, so that attacker simply isn't forced; a bare loop would let it escape `declareAttackers` and crash games Forge
  itself finishes. Keep `synchronized (combat) { combat.addAttacker(...) }`, `attackersLeft.remove` and the
  `numForcedAttackers` count as they are. With the property off, Forge's executor path unchanged. Pinned SHA of
  Forge's class; inner classes checked with javap. J's tests (or check notes) show one task throwing leaves the
  other attackers forced and the game going on.
- J updates `PATCHES`, `GAME_PATCHES`, the patch sources and their GPL headers, `CHECKED_SOURCE` (after
  cardlog-check), and `test_forge_patches.py` / `test_forge_simjar.py`.

---

## 20. Ownership (function level)

"frozen" = base owns it; change only by handoff (§21). Every name not listed is frozen.

| File | J | EJ | PJ | EP | PP | C |
|---|---|---|---|---|---|---|
| `java/decklab/Request.java`, `GameLoop.java` | | all | | | | |
| `java/decklab/WarmState.java`, `DeckLabServe.java` | | | all | | | |
| `java/decklab/DeckLabSim.java`, `Seeds.java`, `Signals.java` | | | | | | |
| `java/forge/ai/*.java` (new) | all | | | | | |
| `common.py` | | | | `FORGE_RUN_VERSION` | | |
| `seeds.py` | | | | | | |
| `simjar.py` | `PATCHES`, `GAME_PATCHES`, `CHECKED_SOURCE`¹ | `CHECKED_SOURCE`¹ | `CHECKED_SOURCE`¹ | `_checks`, `record_checked`, `record_failed`, `_record`, `checked_versions`, `readiness`, `card_log`² | | |
| `install.py` | | | | | `status`, `_with_card_log` | |
| `lists.py` | | | | | `plan`, `_batch_size`, `_batch_count` (+ new v2 planner) | |
| `engine.py` | | | | all | | |
| `processes.py` | | | | | all | |
| `slots.py` | | | | | all | |
| `cores.py` (base stub; `core_masks`, `mask_for`, `pin(pid, slot)` signatures frozen) | | | | | all | |
| `cardlog.py` | | | | | | all but `merge_record` |
| `logreader.py` | | | | | | all but `ENGINE_PREFIX`, `SEAT_FIELDS`, `engine_fields`, `engine_by_side`, the DLENGINE branch and the `turn` call in `_feed` |
| `saved.py` | | | | `_stored` | `_is_result` | `CARD_TALLIES`, `COMMANDER_TALLIES`, `MAX_PER_GAME`, `_count`, `_pair`, `_row_fits`, `_commander_fits`, `_card_record`, `_older_record`, `_pooled_cards`, `_stratum_key`, `_add_stratum` |
| `cardstats.py` | | | | `list_cards` | | all else |
| `runner.py` | | | | `PREFERENCES`, `_prepare_user_dir` | `run`, `_run`, `_record`, `_play`, `_Batch`, `_read`, `_slot`, `_kill`, `_save_failure_log`, `_log_card_problems`, `_first_use_marker`, `_tidy_user_dir`, `_claim`, `_release`, `_side`, `_seen`, `_check_names`, `_write_decks`, constants of the run loop | |
| `pool.py` | | | | | all | |
| `servecheck.py` | | | all | | | |
| `ai.py` | | | | `ai_limits`, `list_ai` | | |
| `views.py` | | | | `_engine_view`, `_page_side`, `results`, `results_for` | | |
| `cli.py` | | | `_serve_check_args`, `_cmd_serve_check` | `_cardlog_check` and every `_check*`/`CHECK_*`/`_leg_problem`/`_compare*`/`_split_games`/`_games_text` (keeping base's `RE_ORDINAL` and `RE_FRAME` masks)/`_time_limit_game`/`_card_log_problems`/`_names_both_commanders`, `_cardlog_check_args`, `_cmd_cardlog_check`, `_replay_args`, `_cmd_replay`, `_engine_lines`, `_list_args`, `_cmd_list` | `_status_args`, `_cmd_status`, `_play_args`, `_cmd_play`, `_print_play`, `_slots_args`, `_cmd_slots`, `_pool_args`, `_cmd_pool` | `_cards_args`, `_cmd_cards`, `_print_cards`, `_diff`, `VERDICTS` |
| `__init__.py` | | | | | | |
| `api/forge_runs.py` | | | | `_TodaysLists`, `_item_json`, `_matchup_json`, `_matchup_by_key`, `matchups`, `matchup`, `_deck_matchups`, `_matchup_notice` | `_forge_runner`, `FORGE_JOBS`, `stop_jobs`, `_MatchupRun`, `run_matchup`, `stop_matchup`, `_job_json`, `_running_json`, `_batching` | |
| `server.py` | | | | | all | |
| `web/matchups.js` | | | | all | | |
| `web/matchups-cards.js`, `web/deck.js` (per-card view) | | | | | | all |
| `web/matchups.css` | | | | engine rules | | card rules |
| **tests** | `test_forge_patches.py`, `test_forge_simjar.py`, new `test_forge_aipatches.py` | new `test_forge_v2loop.py` (real-Java, gated) | new `test_forge_serve.py` (real-Java, gated), new `test_forge_servecheck.py` | new `test_forge_engine.py`, `test_forge_replay.py`; `test_forge.py` `KeyTests`, `ViewTests`, `AiLimitsTests`, `CommandLineTests.test_cardlog_check_*`/`test_the_cardlog_check_*`/`test_list`; `test_matchups_api.py` `NotPlayedTests`, `KeyTests`, `ListTests`, `DeckViewTests`; `test_api.py` `FakeForge` (all but `status` and `run`) | new `test_forge_pool.py`, `test_forge_cores.py`; `test_forge.py` `PlanTests`, `RunTests`, `StatusTests`, `JobObjectTests`, `HousekeepingTests`, `RealForgeTests`, `CommandLineTests.test_status`/`test_play*`/`test_workers_*`/`test_ctrl_c_*`; `test_forge_slots.py`; `test_forge_batchplan.py`; `test_matchups_api.py` `RunTests`, `StopTests`, `RunnerTests`, `RealForgeTests`; `test_server.py`; `test_api.py` `FakeForge.status` and `FakeForge.run` (`status()["pool"]`, run's `pool`/`local` keywords as `_MatchupRun` calls it) | `test_forge_cardlog.py`, `test_forge_cardstats.py`, `test_forge_cardpool.py`, new `test_forge_cardlog3.py`; `test_forge.py` `LogReaderTests`, `CommandLineTests.test_cards_*` |

¹ `CHECKED_SOURCE` is one line every Java package must set (after `cardlog-check` passes in its worktree). At each
merge a conflict there is resolved by running `cardlog-check` on the merged tree and writing its `source_sha256()`.
² Only if the v2 check records more than today (e.g. `"warm": true`); keep `card_log()`'s contract.

Frozen and shared by everyone (base): `seeds.py`, `Seeds.java`, `Signals.java`, `DeckLabSim.java`,
`runner.request_args`, `_java`, `_class_path_launch`, `build_command`, `serve_command`, `REQUEST_ID`, `request_line`,
`SERVE_*` (`SERVE_HEAP` included), `RECYCLE_REASONS`, `serve_event`, `JVM_FLAGS`; `lists._key` (the v1 key, with
`V1_RUN_VERSION`), `lists.matchup_key` (delegates); `cardlog.merge_record`, `cardlog.Game.turn`'s signature;
`logreader` engine pieces; `simjar.deck_lab_sources`, `_source_bytes`, `_build`, `_stamp`, `game_patch_ids`,
`SIM_CLASSES`, `GAME_PATCHES_OFF`, `GAME_PATCH_ID`, `GAME_PATCH_LIST`, and `card_log()`'s `"game_patches"` key;
`cli.RE_ORDINAL`, `RE_FRAME`; `views.view`/`list_item` (wired to `_engine_view`); `cli.COMMANDS`/`_main`;
`config.DEFAULTS`; `tests/fixtures/fake_forge.py`; `test_forge.py`'s module helpers (everything before `class
DckTests`: imports, constants, `_real_build_command`, `_real_serve_command`, `setUpModule`, `make_forge`,
`fake_command`, `fake_serve_command`, `CARD_LOG`, `sections`, `entry`, `alive`, `wait_dead`, `ForgeCase`; and the
helpers `read_log`, `stored`, `load_json` further down); `test_forge_contract.py`; `test_forge.py` `DckTests`,
`MathsTests`, `PackageTests`; `test_config.py`.

The fake (base) covers what the packages need to test without Java: v2 games, serve mode, `throw#G` (a Java error
escaping: `end|error`, `bye|error`, exit 1), `aitimeout#G` (serve recycles, `ai_timeout`) and `aitimeoutunseen#G`
(Python's taint only), `exception#G` (serve recycles, `crash`), `badargs` (`end|error`, the worker plays on),
`avgcmc=a,b` and a deck name holding "Control" (auto-profile by Forge's rule), `--game-patch-ids=` (the DLENGINE
`gamepatchids`; `fake_command`/`fake_serve_command` pass the card log's `game_patches`), `heap_mb` in end lines.

**New names and the package's re-exports.** No package edits `decklab/lib/forge/__init__.py` or
`decklab/lib/api/__init__.py`. New names are reached on their part (`forge.engine.X`, `forge.pool.X`,
`forge.cores.X`, `forge.servecheck.X`, `forge.runner.X`) until the integrator re-exports any that should be
`forge.X` (step 7). The API layer reaches them the same way.

**Cross-package tests:** EP tests `replay` against a stand-in session passed as `run(pool=...)` (a context manager
whose value `run` accepts, faked in EP's tests); after PP's merge, PP adds one integration test of `replay` with the
real `pool.session()` and the fake's serve mode (the "later package" rule, §21).

Not touched by any package (integrator after the merges): `decklab/PLAN.md`, `decklab/README.md`,
`decklab/lib/forge/__init__.py`'s docstring and imports, `CLAUDE.md`.

---

## 21. Cross-owner requests and merge order

**Handoff rule.** Never edit a function, class or test you don't own. When you need a change there:
1. write `HANDOFF-<package>.md` in your worktree's root (untracked; not committed) with: file, function, the exact
   change (a diff or the new code), why, and what breaks without it;
2. code against the change in your own files (e.g. call the new name behind `getattr`, or keep a local adapter) so
   your branch passes its tests without it;
3. the owner (or the integrator at merge) applies it. Contract changes (anything frozen) go to the integrator, who
   updates this file on `sim-w2-base`'s successor branch and tells every package.
- Behaviour every package can rely on is the contract's; if you find the contract wrong, say so in your handoff
  instead of working around it silently.
- A breaking change to another package's tests that the contract already implies (e.g. `run_version` 2 in a
  `RunTests` assertion after EP's bump) is fixed by the **later** package in the merge order, limited to the
  assertion lines, listed in its handoff note.

**Merge order** (each: rebase on the integration branch, full suite, `cardlog-check` when Java changed, update
`CHECKED_SOURCE`, merge):
1. **C** — Python only, independent.
2. **J** — the patches; base's check runs game patches off, so it can't fail on R14b, and masks frames, so R14a's
   stack traces can't fail it.
3. **EJ** — the v2 loop; v1 path unchanged (the check still passes line for line). **At this merge (after J), rerun
   EJ's parity and chunk-independence script on the merged tree**: EJ's branch checked them without J's R14a.
4. **PJ** — serve and the warm check (v2 requests now possible). **At this merge, run `serve-check` with v2 requests
   in both formats on the merged tree**: PJ's branch could only send v1 requests, and cardlog-check is still base's
   v1 check until EP lands.
5. **EP** — engine id, `FORGE_RUN_VERSION = 2`, PERFORMANCE_MODE, consumers, v2 cardlog-check (needs EJ, PJ, J),
   replay command. At this merge the full v2 cardlog-check (parity with J's patches off, card log on/off with them
   on, warm leg) runs for the first time on the combined code; its pass sets `CHECKED_SOURCE`.
6. **PP** — pool, run loop, server, CLI submit (integrates everything; real small runs). At this merge: `serve-check`
   again with pinning live (PP's `cores.py` replaces the stub), PP's integration test of `replay` with the real
   session, and the later-package fixes in `test_api.py` `FakeForge` if EP's members need PP's shape.
7. **Integrator:** docs (`PLAN.md` wave 2 entry, `__init__.py` docstring, README), one cardlog-check, one full suite,
   then main. The integration branch is never merged to main before step 7, since steps 3-6 change games before
   the bump lands.

**Resource rules (the PC is in use):** at most 4 Forge processes / pool workers, ≤ ~400 games a run; BELOW_NORMAL;
slots respected; never write `C:/VSProjects/TradingCardCollection/decklab/data/forge/results` (use `--results-dir`
in scratch or your worktree's data); never the background server on 8642 (test servers `--host 127.0.0.1` from 8643,
stopped after); after any Forge run check `Get-CimInstance Win32_Process` for java.exe you started and `taskkill /PID
<pid> /T /F` leftovers; no timing claims (M3 measures speed later on an idle PC).

---

## 22. Review fixes (revision 2): where each finding went

| Finding (reviewer, weight) | Fixed in |
|---|---|
| Warm check: Commander doesn't repeat line for line; identity-hash order can't be reset (Java, must) | §4 residual, §6.6, §7, §18 (Commander by outcome; Constructed replay → unsure); `servecheck.py` docstring |
| Engine id lists declared, not built-in, game patches; DLENGINE can't tell (both, must/should) | base: `simjar` stamp + jar list + `card_log()["game_patches"]`, `GameLoop.gamePatchIds()` (`gamepatchids`); §5, §13, §19 |
| R14b loop must swallow per-task exceptions like `invokeAll` (Java, must) | §19 |
| Masks miss the Game Result ordinal and stack frames (Java, should) | base: `cli.RE_ORDINAL`, `RE_FRAME` in `_games_text` (v1 check too); §4, §18, §19 (notes at the end of copies) |
| AI-timeout taint is Python-only; no Java hook (Java, should) | base: `Signals`, `GameRecord.aiTimeouts`, `Played.last`, serve recycles `ai_timeout`; §2, §6.5, §19; Python taint kills at once |
| Stuck virtual evals starve APC=2 carriers (Java, should) | §19: virtual thread only while `LIVE_EVALS == 0` |
| forge.log tee grows unseen; no cap or heap report (Java, should) | base: `DeckLabServe.untee`, `heap_mb` in end lines (`runner.SERVE_HEAP`); §6, §6.5 (`WORKER_MAX_GAMES`, heap limit) |
| Game 0's decks must load after reset + reseed; fresh GameRules (Java, should) | §4 step 4 |
| cp2card clear; crash leaves static maps half updated (Java, should) | §7 (snapshot key set); base: serve recycles `crash` |
| Later games after a time-limit game in one-shot v2 (Java, should) | §4 step 7, §18 (`earlier=True` both formats on the DeckLabSim side) |
| Three checks never run on combined code (Java, should) | §21 steps 3-6 |
| Malformed requests kill the worker; -dlgame rules (Java, should) | base: serve catches parse errors (`end|error`, plays on), `Request.parse` v2 validation, `WarmState.reset` failure → `problem` (§4); §3, §6.2 |
| `Seeds.parseStream` laxer than Python (Java, nit) | base |
| autoprofile is a re-derivation (Java, nit) | §5, §18 (EJ compares once with `pilotsNonAggroDeck()`) |
| R14a "on vs off" has no switch (Java, nit) | §18 (J's check) |
| Clock-stop log read can throw (Java, nit) | base: `GameLoop.logEntries` (tried 3 times) |
| Stop waits for game boundaries; pool closes before runs save (Python, must) | §9 Stop, §10 Server (order, handlers, tests) |
| One shared `forge-pool.json` (Python, must) | §10 (`forge-pool-<pid>.json` in `slots.folder()`) |
| Server pool keeps its start-up setup (Python, must) | §10 launch identity per chunk; compatibility per request |
| `--a-first` flip stored nowhere (Python, should) | §8, §12 (`seeds.flip`, per result), §16 |
| Retries "once" vs "twice"; repeating failures retried (Python, should) | §6.4, §9 (one rule, `MAX_REQUEUE = 2`; fail at once) |
| First-use gate; no fallback when serve can't start (Python, should) | §10 Starting workers (one alone; one-shot v2 fallback, `fallback` in the run record) |
| CLI disconnects leave chunks playing (Python, should) | §10 (heartbeat; cancel on close) |
| Per-card stats vanish when the card log is unready (Python, should) | §13 (decklab-kind side id for per-card consumers) |
| Page: wording, batch count, follow the new key, earlier results (Python, should) | §13 consumers, §15 |
| Replay's open cases (Python, should) | §16 (refuse unless decklab; largest target; BUSY skipped; Ctrl+C; low priority) |
| forge_pin and xmx not in compatibility (Python, should) | §10 compatibility; §12 settings.xmx |
| Warm check unpinned (Python, should) | base: `cores.py` stub; §11, §18, §21 |
| No cap on idle JVMs (Python, should) | §10 Idle and memory (live-JVM cap; local idle 30 s) |
| Ownership gaps: FakeForge, re-exports, replay vs session (Python, should) | §20 |
| Fake can't throw in serve or auto-profile (Python, should) | base: fake `throw#G`, `avgcmc=a,b`, "Control" names, `aitimeoutunseen`, `badargs`, `--game-patch-ids` |
| Config values unvalidated (Python, nit) | §10, §17 |
| `lists._key` docstring vs `FORGE_RUN_VERSION` (Python, nit) | base: `V1_RUN_VERSION` |
| `_is_result` `g`; `_page_side` mapping (Python, nit) | §12, §13 |
| "slowest start-up None s"; progress once per chunk (Python, nit) | §16, §9 / §10 (per-game events) |
