# Forge trial: setup notes (Milestone 0, steps 1-3)

Written 2026-09-29 on HomePC (Ryzen 9 9950X3D, 16 cores / 32 threads, 64 GB RAM, Windows 11 Pro 10.0.26200).
Every statement below was either read in Forge's source at tag `forge-2.0.15`
(`https://raw.githubusercontent.com/Card-Forge/forge/forge-2.0.15/<path>`, files named inline) or
measured on this PC; each item says which. Paths are relative to this folder
(`decklab/forge-trial/`, gitignored).

| File | What it is |
|---|---|
| `to_dck.py` | our deck `.md` / product `.csv` -> Forge `.dck` (usage in its docstring) |
| `run_sim.py` | runs one Forge sim process, saves the log, prints a JSON summary (usage in its docstring) |
| `measure_run.py` | harness used for the timing and memory numbers (per-line timestamps, Win32 memory and CPU counters) |
| `decks/gruul-ramp-owned.dck`, `decks/izzet-prowess-owned.dck` | the two trial decks (owned-only lists) |
| `decks/probe.dck`, `decks/probe2.dck`, `decks/forms/` | name-resolution tests |
| `logs/` | raw stdout/stderr and JSON of every run quoted here (`m*` = measure_run, `rs-*` = run_sim) |
| `forge-user/` | Forge's user-data folder for run_sim runs (see "Forge's user folder") |

**Verdict: Forge 2.0.15 runs headless on Java 26 and plays full games between our decks.** No Java 21 was needed.

## 1. Install

- Release `forge-2.0.15` ("Reality Fracture Release", published 2026-09-28T22:37Z) has 4 assets: `build.txt`, `version.txt`,
  `forge-installer-2.0.15.jar` (309,541,008 bytes, an installer) and `forge-installer-2.0.15.tar.bz2` (297,081,149 bytes, the portable build).
- Downloaded the `.tar.bz2` with curl to `C:/Tools/` (size matched; SHA-256 `4468f182b60f6ca62d89697baa208981085af744f116781af751c611826db600`),
  extracted into `C:/Tools/forge` with Git Bash `tar -xjf` (1 min 29 s), then deleted the archive.
- Result: 453 MB, 21,480 files. Top level: `forge-gui-desktop-2.0.15-jar-with-dependencies.jar` (31.5 MB, the one we run), `forge.exe` / `forge.cmd` / `forge.sh`,
  the mobile/adventure jars, `res/` (card scripts in `res/cardsfolder/cardsfolder.zip`, 34,010 scripts; 681 edition files in `res/editions/`), `docs/`. `build.txt` = `2026-09-28 22:22:04`.

## 2. Java

- **Java 26 works** (tested). The installed JDK is `C:/Program Files/Java/jdk-26.0.1` (`java version "26.0.1" 2026-04-21`). Forge logs `Java: 26.0.1 (Oracle Corporation)`, `RAM: <Xmx> max, 32 CPUs`.
  The only Java-26-specific output is a harmless `WARNING: A terminally deprecated method in sun.misc.Unsafe has been called` block from Guava on stderr.
  The jar was built with `Build-Jdk-Spec: 17`; `forge-gui-desktop/pom.xml` sets the launcher's `<minVersion>17</minVersion>`.
- **Use the real `java.exe`, not the one on PATH.** `where java` gives `C:\Program Files\Common Files\Oracle\Java\javapath\java.exe`, a
  703,632-byte stub (same size as the `javac.exe`/`javaw.exe` next to it). Tested: launching Forge through it gave two processes,
  the stub (PID 54704) and its child `C:\Program Files\Java\jdk-26.0.1\bin\java.exe` (PID 53168, parent 54704). Measuring or killing the
  stub's PID would miss the real JVM, so the scripts call `C:/Program Files/Java/jdk-26.0.1/bin/java.exe` directly.
- **JVM flags Forge's own launchers use** (read from `forge.sh`, `forge.cmd`, the string table of `forge.exe` and `pom.xml`
  `mandatory.java.args`/`addopen.java.args`): `-Xmx4096m -Dio.netty.tryReflectionSetAccessible=true -Dfile.encoding=UTF-8`, plus
  (in `forge.exe` only) 20 `--add-opens ...=ALL-UNNAMED` flags. The jar's `MANIFEST.MF` has the same list as an `Add-Opens:` attribute,
  which Java applies when started with `-jar`, so the `--add-opens` flags are not needed on the command line (all our runs omit them).
- `forge.cmd` does **not** pass its arguments on to Java (`java ... -jar forge-gui-desktop-2.0.15-jar-with-dependencies.jar` with no `%*`), so it can't run sim mode. `forge.sh` does (`"$@"`).
- **Working directory must be `C:/Tools/forge`**: `GuiDesktop.getAssetsDir()` returns `""` for release builds, so `res/` and `forge.profile.properties` are found relative to the current directory.

## 3. Command that works

```
cwd: C:/Tools/forge
"C:/Program Files/Java/jdk-26.0.1/bin/java.exe" -Xmx1024m -Dio.netty.tryReflectionSetAccessible=true -Dfile.encoding=UTF-8
    -jar forge-gui-desktop-2.0.15-jar-with-dependencies.jar sim
    -D C:/VSProjects/TradingCardCollection/decklab/forge-trial/decks
    -d gruul-ramp-owned.dck izzet-prowess-owned.dck -n 50 -s 1 -c 120 -a Default Default [-q]
```

Or `python run_sim.py decks/gruul-ramp-owned.dck decks/izzet-prowess-owned.dck -n 50 -s 1 [-q] [--lazy]` from this folder.

## 4. Sim mode, from the source

`forge-gui-desktop/src/main/java/forge/view/Main.java`: if `args[0]` is `sim` (also `parse`, `server`), it sets `java.awt.headless=true`
(unless given), initialises the GUI interface and error handler, calls `SimulateMatch.simulate(args)`, then `System.exit(0)`.
**The exit code is 0 even when a deck fails to load** (tested), so callers must read the output.

`forge-gui-desktop/src/main/java/forge/view/SimulateMatch.java`: `FModel.initialize` (loads all card scripts), prints `Simulation mode`;
fewer than 4 arguments prints the help text. Each `-x` starts a new option; the following words are its values.

| Flag | What it does (SimulateMatch.java) |
|---|---|
| `-d <deck> ...` | one or more decks. A value is treated as a **file** only if a `.` sits exactly 4 characters from the end (`x.dck`); the file is `new File(baseDir + name)` where `baseDir` is `-D`, or else `<userDir>/decks/constructed/` (`decks/commander/` with `-f Commander`). Anything else is looked up **by deck name** in Forge's saved constructed/commander decks. |
| `-D <dir>` | base folder for `-d` files. In tournament mode (`-t`) it instead **adds every `*.dck` in that folder** as a player, and `-d` files are then resolved against the default folders, not `-D`. |
| `-n <N>` | number of games (default 1). All N games are one Forge `Match` in one process. Ignored if `-m` is given. |
| `-m <M>` | play a best-of-M match instead (`gamesPerMatch = M`, `gamesToWinMatch = M/2 + 1`, from `GameRules.java`); stops when someone reaches that many wins. |
| `-f <Format>` | `GameType.valueOf(capitalize(value))`, default `Constructed`; `Commander` makes each player `RegisteredPlayer.forCommander(deck)`. `rules.setAppliedVariants({type})`. |
| `-s <seed>` | `MyRandom.setRandom(new Random(seed))`. The header line then ends `seed <S>`. |
| `-c <sec>` | per-game clock (`rules.setSimTimeout`, default 120 s in `GameRules.java`). Only applied in the non-tournament path. |
| `-q` | quiet: print only each game's outcome lines (log entries of type up to `MATCH_RESULTS`) instead of the whole game log. |
| `-t <Bracket\|RoundRobin\|Swiss>` | tournament across all given decks (each pairing is a Match, using the default best-of-3); `-c`, `-a`, `-n` are not used there. |
| `-p <N>` | players per match in a tournament (default 2). |
| `-a <profile> ...` | AI profile per player in deck order. Checked against `AiProfileUtil.getProfilesDisplayList()`: `Random (Every Match)`, `Random (Every Game)`, `Cautious`, `Default`, `Experimental`, `Reckless` (files in `res/ai/`). Unknown name prints `Unknown AI profile - X. Available profiles: ...` and stops. Without `-a` the profile comes from the user preference `UI_CURRENT_AI_PROFILE` (default `Default`, `ForgePreferences.java`); run_sim always passes `-a` so results don't depend on preferences. |

Other behaviour read in the source and confirmed by test:

- **Absolute `-d` paths fail** (tested): `-d C:/.../gruul-ramp-owned.dck` without `-D` prints
  `No deck found in C:\Users\player\AppData\Roaming\Forge\decks\constructed\` and `Could not load deck - ..., match cannot start`; with `-D` it
  concatenates the two paths and fails the same way. Relative sub-paths work (`-D .../forge-trial -d decks/gruul-ramp-owned.dck` played).
- **Who goes first** (`GameAction.determineFirstTurnPlayer`, `PlayerControllerAi.chooseStartingPlayer`): game 1 of a process is a random player
  (`Aggregates.random`, seeded by `-s`); every later game, the first player in seat order who did not win the previous game goes first
  (so the loser; after a draw/timeout, deck 1). The AI always chooses to play first (`return this.player; // AI is brave`). Confirmed in the
  seed-12345 log (`logs/seed-a.out`): the previous game's loser started games 2-5. Over the 100-game seed-2 run, Gruul started 58, Izzet 42 (the loser-starts rule
  gives the losing deck more starts), and the starting player won exactly 50 of 100.
- **No sideboarding between games in sim mode**: `SimulateMatch` builds `new GameRules(type)` whose `AISideboardingEnabled` is `false`
  (`GameRules.java`), so `PlayerControllerAi.sideboard` returns immediately. A `[Sideboard]` section is loaded but never used (except by
  effects that fetch from outside the game).
- **The game runs in a single worker thread** (`TimeLimitedCodeBlock.runWithTimeout`, a single-thread executor); `Match.startGame` ends with `System.gc()`.
- **Timeouts are NOT reported as draws (Forge bug, tested with `-c 1`, `logs/rs-timeout-c1.log`).** When the clock runs out, Forge prints
  `Stopping slow match as draw`, interrupts the game (an `InterruptedException` stack trace follows), and calls `setGameOver(Draw)`. But
  `Player.onGameOver` gives every player who hasn't lost a "win", so the log shows *both* `... has won because all opponents have lost`
  lines and the `Game Result` line names whichever player `GameOutcome`'s `HashMap` (identity-hashed `RegisteredPlayer`) returns first:
  2 of 4 games timed out in that test and both were printed as `Ai(2)-Izzet Prowess (owned) has won!`. A game that throws an exception
  goes through the same `finally` and is misreported the same way. The cumulative `Match Result:` line also counts them as wins.
  **run_sim.py counts a win only when exactly one player "has won"** and no `Stopping slow match` line appeared; otherwise it reports
  `timeout` / `error` / `draw` and keeps Forge's claim as `forge_reported_winner`. After a timeout, deck 1 starts the next game.
  None of the 100-, 50- and 20-game runs with the default 120 s clock hit a timeout (longest game 2.7 s).

## 5. What it prints (for parsing)

Header (after card loading; the count is spelled out, sometimes with a double space):
```
Ai(1)-Gruul Ramp (owned) vs Ai(2)-Izzet Prowess (owned) - fifty  games of Constructed seed 1
Ai(1)-Gruul Ramp (owned) [Default] vs Ai(2)-Izzet Prowess (owned) [Default] - 100 games of Constructed seed 2
```
Player names are `Ai(<seat>)-<Name= from the .dck>`, plus ` [profile]` in the header when `-a` is given.

Per game with `-q` (and at the end of each game's log without `-q`):
```
Game Outcome: Match Duration 0m : 00s
Game Outcome: Turn 9
Game Outcome: Ai(1)-Gruul Ramp (owned) has won because all opponents have lost
Game Outcome: Ai(2)-Izzet Prowess (owned) has lost because life total reached 0
Match Result: Ai(1)-Gruul Ramp (owned): 2 Ai(2)-Izzet Prowess (owned): 0

Game Result: Game 2 ended in 1065 ms. Ai(1)-Gruul Ramp (owned) has won!
```
- `Game Outcome: Turn N` is `ceil(total turns / 2)` (`GameLogFormatter.java`), i.e. rounds.
- `Match Result:` is cumulative over the whole process.
- `ended in N ms` is a stopwatch around `createGame` + `startGame` (includes the `System.gc()`), not including printing.
- A draw prints `Game Result: Game N ended in a Draw! Took N ms.`
- Noise that can be ignored: `Forest Did not have activator set in SpellAbilityRestriction.canPlay()` lines, and on stderr at start-up
  19 `The card ... was not assigned to any set` lines and `Upcoming set Star Trek (TRK) dated in the future...`.

Without `-q`, the full log comes first (about 400 lines per game: `logs/rs-eager-full-n100-s2.log` is 40,163 lines / 2.4 MB for 100 games),
chronological, with line types `Mulligan:`, `Turn: Turn 1 (Ai(2)-Izzet Prowess (owned))`, `Phase:`, `Land: ... played X (id)`,
`Add To Stack: ... cast X`, `Resolve Stack:`, `Mana:`, `Combat:`, `Damage:`, `Life: Life: P 20 > 21`, `Zone Change:`, `Replacement Effect:`.
Card draws are not logged (hidden information), which matters for Milestone 0 step 7.

## 6. Deck files (.dck) and card names

Format read from `forge-core/.../deck/io/DeckSerializer.java` and `CardPool.java`: `[metadata]` with `Name=`, then sections
`[Main]`, `[Sideboard]`, `[Commander]`; card lines `<count> <request>` where a request is `Name`, `Name|SET`, `Name|SET|<artIndex>`
(a 1-2 digit number is an **art index**, not a collector number) or `Name|SET|[<collector number>]` (`CardDb.CardRequest.fromString`).
Lookup (`CardDb.tryGetCard`): try the set if given; if that fails, fall back to any printing of the name; names are case-insensitive
and accent-insensitive. A name that still isn't found prints on **stderr**
```
An unsupported card was requested: "Totally Fake Card" from "null".
Forge could not find this card in the Database. Any chance you might have mistyped the card name?
```
(each deck is parsed a few times, so each message repeats), and the card is **silently removed from the deck** before play
(`Deck.getValid`); the game still runs with fewer cards (tested with `decks/probe.dck`, 60 lines incl. 6 bad ones).

Tests (`logs/probe*.err`, `logs/form-*.err`, `logs/allcards-*.err`):

| Line form | Result |
|---|---|
| `4 Llanowar Elves` (name only) | resolves; also lower case and `Lim-Dul's Vault` for `Lim-Dûl's Vault` |
| `1 Lightning Bolt\|ZZZ` (unknown set) | resolves (falls back to another printing), no warning |
| `4 Name\|SET`, `4 Name\|SET\|1`, `4 Name\|SET\|[227]` | all resolve for our cards |
| `1 Fire // Ice` (split card, full name) | resolves |
| `1 Murderous Rider // Swift End` (adventure), `Pollen-Shield Hare // Hare Raising` (adventure), `Delver of Secrets // Insectile Aberration` (transform), `Emeria's Call // Emeria, Shattered Skyclave` (MDFC), `Bushi Tenderfoot // Kenzo the Hardhearted` (flip) | **unsupported, dropped from the deck** |
| `Murderous Rider`, `Swift End`, `Delver of Secrets`, `Insectile Aberration`, `Emeria's Call`, `Pollen-Shield Hare`, `Fire`, `Ice`, `Ticket Booth // Tunnel of Hate` | all resolve (`CardDb.addCard` indexes every face name of multi-face cards) |

All 375 distinct printings / 351 distinct names in the 11 deck files (target + owned lists) resolved with **zero** warnings in each of
the forms name, `|SET`, `|SET|1` and `|SET|[num]` once `A // B` was reduced to the front face; written as Scryfall's full `A // B`, the two
adventure cards (Murderous Rider, Pollen-Shield Hare) were dropped. All 45 set codes in the deck files' decklists exist as a `Code=`
or `ScryfallCode=` in `res/editions/` (FDC, TDC, BLC, LCC, NCC, SCD, WHO, M3C, J25, FRC, MSC, BRR, DRC, CMM, PLST, SOS, SOA, ...), as do
the product lists' codes (fdn, fdc, blb, m19, grn, rix, dom, rna, xln).

Product lists also convert and load (smoke test, `logs/rs-products-*.log`, 2 games each, lazy loading): Challenger Lightning Aggro
(60 + 15 sideboard) vs BLB Starter Kit "Hare Raising" (60), and the Beginner Box pairing Cats + Vampires (40 cards) vs the Calling All
Angels precon (Commander 1 + 99, played as Constructed): no unsupported cards, all games finished. Sim mode does not check deck size.

**Rule adopted in to_dck.py:** write `<count> <name>` only, with `Front // Back` reduced to `Front`, and merge lines of the same card.
Printing doesn't matter to the simulation and an unknown set code only falls back anyway, so the set adds nothing but risk.
The deck's `Name=` is the deck's `# ` title (plus ` (owned)` for the owned list) unless `--name` is given.

## 7. Measurements (Gruul Ramp owned vs Izzet Prowess owned)

How: `measure_run.py` starts the real `java.exe` with `cwd C:/Tools/forge`, timestamps every stdout line (seconds since launch), and
samples the process every 0.2 s with Win32 `GetProcessMemoryInfo` (working set, private bytes), reading the final
`PeakWorkingSetSize` / `PeakPagefileUsage` and `GetProcessTimes` (user + kernel CPU) from the kept process handle after exit.
"Start-up" = launch to the `Ai(1)-... vs Ai(2)-...` header, which is printed after all cards and both decks are loaded, right before game 1.
"Games wall" = header to the last `Game Result`. Per-game times are Forge's own `ended in N ms`.
Each run: 50 games, `-s 1 -q`, one process at a time, nothing else of mine running (`logs/m*.json`).

| Run | -Xmx | Other | Start-up s | Games wall s | ms/game mean (min-max) | Peak working set MB | Peak private MB | CPU s |
|---|---|---|---|---|---|---|---|---|
| m1 | 4096m | Forge's launcher flags | 9.35 | 40.73 | 813 (358-1907) | 2075 | 2414 | 159.5 |
| m2 | none (JVM default) | | 8.99 | 40.79 | 815 (301-1946) | 2202 | 3017 | 142.2 |
| m2 | 2048m | | 8.97 | 40.02 | 799 (322-1977) | 1457 | 1606 | 151.2 |
| m2 | 1024m | | 8.64 | 40.32 | 805 (355-1844) | 1030 | 1154 | 148.5 |
| m2 | 512m | | 9.19 | 39.50 | 789 (314-1875) | 752 | 849 | 152.2 |
| m2 | 256m | | 10.30 | 46.35 | 926 (283-2562) | 514 | 604 | 222.9 |
| m3 | 1024m | `-XX:+DisableExplicitGC` | 9.07 | 34.55 | 690 (223-1864) | 824 | 919 | 104.9 |
| m3 | 1024m | `-XX:+UseSerialGC` | 9.32 | 48.18 | 962 (413-2584) | 792 | 846 | 102.7 |
| m3 | 1024m | SerialGC + DisableExplicitGC | 9.12 | 38.56 | 770 (263-2418) | 861 | 851 | 95.6 |
| m4 | 1024m | lazy card loading (see 8) | **1.24** | 36.86 | 736 (272-1748) | 763 | 878 | 95.7 |
| m5 | 1024m | start-up only (`sim` with no decks) | 8.84 to exit | - | - | 588 | - | 17.9 |

- **Start-up: about 9 s** (8.6-9.4 s across 9 runs) with Forge's default eager loading, of which about 18 CPU-seconds (card loading uses a thread pool).
  With 4 processes starting at once (`logs/dbg-*.json`) the header came at 13.3-13.5 s.
- **Time per game: about 0.8 s** (mean 789-815 ms for -Xmx 512m to 4 GB; min about 0.3 s, max about 2 s); 50 games in about 40 s, i.e. about 75 games/min per process.
  The 100-game run with run_sim defaults (`logs/rs-eager-full-n100-s2.json`, full log, -Xmx1024m): start-up 9.06 s, 100 games in 73.75 s,
  mean 734 ms (283-2736), 81.4 games/min; games lasted 6-17 rounds (mean 8.4).
- **Memory: one process peaks at about 1.0 GB working set with -Xmx1024m**; the peak follows -Xmx (2.1 GB at Forge's 4096m, 0.75 GB at 512m).
- **-Xmx matters for memory, not speed, down to 512m**: 512m-4096m all ran at 789-815 ms/game; 256m was 15% slower with 50% more CPU
  (GC pressure). run_sim defaults to 1024m (not tested yet with 100-card Commander decks or 4 players).
- **CPU: one process uses more than one core**: about 130 CPU-s during 40 s of games (about 3.3 cores busy) with Forge's per-game
  `System.gc()`; 87 CPU-s / 34.5 s (2.5 cores) with `-XX:+DisableExplicitGC`. The game itself is one thread; the rest is GC and JIT threads.
  This matters for how many processes fit on 16 cores (next step); `-XX:+DisableExplicitGC` or `-XX:+UseSerialGC` cut CPU per process by about a third.
- **Determinism: the same seed replays the same games.** Winner sequences of all 10 seed-1 runs above (every -Xmx, GC and lazy variant)
  were identical (28-22 to Gruul), and the full game logs of two seed-12345 runs (`logs/seed-a.out`, `seed-b.out`, run at the same time) were
  identical line for line apart from timings. run_sim runs with `-a Default Default` and an isolated user folder reproduced the same sequence too.
  Different seeds give different games (seed 999 vs 12345).

## 8. Forge's user folder, logs and lazy loading

- On Windows Forge's user folder is `%APPDATA%\Forge` and its cache `%LOCALAPPDATA%\Forge\Cache`, taken from those environment variables
  (`ForgeProfileProperties.getDefaultDirs`) unless `C:/Tools/forge/forge.profile.properties` overrides them. The first runs today created
  `C:\Users\player\AppData\Roaming\Forge` (empty `preferences/`, `decks/`, logs) and `...\Local\Forge\Cache`.
- **Every process writes a copy of all its stdout and stderr to `<userDir>/forge.log`** (`forgeN.log` when several run at once); the next
  start renames finished ones to `forge.<yyyyMMdd-HHmmss>.log` (`ExceptionHandler.registerErrorHandling`), and sim mode never prunes them.
  A 100-game full-log run leaves a 2.4 MB file. run_sim therefore points `APPDATA`/`LOCALAPPDATA` of the child process at `forge-user/`
  (tested: Forge then used `forge-user/Forge/`) and deletes all but the newest 20 archived logs there before each run.
- **Lazy card loading** (preference `LOAD_CARD_SCRIPTS_LAZILY`, default `false`; `FModel.java` passes it to `CardStorageReader`):
  with `LOAD_CARD_SCRIPTS_LAZILY=true` in `forge.preferences`, start-up printed
  `Lazy card database: indexed 35240 card names from 33980 files in 520 ms` and the header came at **1.24 s instead of about 9 s**, with lower
  peak memory (763 MB) and CPU (95.7 s), and the **same 50 winners** as eager loading. Tested once by writing
  `%APPDATA%\Forge\preferences\forge.preferences` and deleting it again afterwards (the folder is back to empty), then via run_sim `--lazy`
  (writes `forge-user/Forge/preferences/forge.preferences`): 1.19 s start-up, same 20 winners. Kept opt-in because it is not Forge's default;
  cards that pick random cards from the whole card pool could behave differently.
- Other preferences that affect games (defaults apply because no preferences file exists): `MULLIGAN_RULE`, `FILTERED_HANDS`,
  `UI_ENABLE_AI_CHEATS` (`false`), `UI_CURRENT_AI_PROFILE` (`Default`).

## 9. Problems and caveats found

1. Timeouts and in-game exceptions are misreported as wins for an arbitrary player (section 4). Handled in run_sim.py; any other parser must do the same.
2. Unknown card names are dropped from the deck with only a stderr message; the game still runs. run_sim returns `ok: false` and lists them.
3. `Front // Back` names only work for split cards; to_dck.py writes the front face.
4. `-d` can't take absolute paths; use `-D <folder>` plus relative names (run_sim does this).
5. Forge exits 0 even when a deck fails to load; check for `Could not load deck -`.
6. The PATH `java.exe` is a stub that spawns the real JVM as a child; call the JDK's `java.exe` directly.
7. `forge.cmd` drops its arguments, so it can't be used for sim mode.
8. Each process leaves a log file (full stdout) in Forge's user folder; run_sim isolates and prunes them.
9. The loser of each game starts the next one, so play/draw is not balanced within a process; the plan's "half the games with the deck order swapped" doesn't fix that by itself. Game 1's starter is random.
10. Not tested here (later Milestone 0 steps): 40-card Beginner Box decks, `-f Commander` with 4 decks, several processes at once, the other 9 decks' card support in actual play (their names all resolve).
