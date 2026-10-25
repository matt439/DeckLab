# Forge trial: game logs and per-card stats (Milestone 0, step 7)

Written 2026-09-29 on HomePC (Ryzen 9 9950X3D, 64 GB, Windows 11), Forge 2.0.15 at `C:/Tools/forge`, JDK 26.0.1.
Source quotes are from `https://github.com/Card-Forge/forge` at tag `forge-2.0.15` (commit `4ec5f1a2c32f`, read from a sparse
clone and raw.githubusercontent.com). Paths are relative to this folder (`decklab/forge-trial/`, gitignored).
Decks: `decks/gruul-ramp-owned.dck` and `decks/izzet-prowess-owned.dck` (the owned-only lists from setup-notes.md).
All runs here used `--user-dir forge-user-logs` (my own Forge user folder, eager card loading, `LOAD_CARD_SCRIPTS_LAZILY=false`)
so they couldn't clash with other agents' runs in `forge-user/`.

> Moved in Milestone 8 (2026-10-01): the source `java/decklab/DeckLabSim.java` below is now `decklab/lib/forge/java/decklab/DeckLabSim.java`, and Deck Lab builds its jar itself (`decklab/data/forge/cardlog/decklab-sim-<Forge version>-<stamp hash>.jar`, where the hash is the first 12 hex digits of the SHA-256 of the jar's stamp: the source, Forge's jar and javac). `run_sim.py --card-log` uses the newest jar, which is the one a Deck Lab run used most recently (each run touches the jar it starts with).

## Verdict

- **Forge's own game log (sim without `-q`) is not enough for per-card stats.** It shows every land drop and every spell
  cast with the player and turn, the winner, who went first, and the number of turns. It never shows **which card was drawn**,
  **what the opening hand was** (only how many cards were kept), or **what was left in hand at the end**. No flag or preference
  changes that: `SimulateMatch` already prints every log entry type, and draws never become log entries.
- **Draws are available one level down, on the game's event bus.** A 394-line Java class (`java/decklab/DeckLabSim.java`,
  mostly comments and a copy of SimulateMatch's single-match code) that subscribes one listener to each game adds `Information: DL|...` lines for
  every card movement, the kept opening hands and the end-of-game hands. **The games are unchanged**: with the same seed the log
  is identical line for line to Forge's own sim apart from the added lines (checked on 1, 20 and 50 games). Cost: about the
  same speed (894 ms/game vs 822 and 860 ms for two plain runs), logs 34% bigger.
- **With that card log all four planned per-card stats are fully supported** (`parse_log.py`, 0 consistency problems in 220
  games). From Forge's own log only "average turn cast" is exact; "win rate when drawn" can only be approximated by "win rate
  when played", which was off by 6 points on average and by up to 30 points for expensive cards; "cast once drawn" and "stuck
  in hand" are impossible.
- **The per-card stats already found a Forge AI problem:** Gruul's **Fiery Annihilation was never cast** in 220 games. It
  reached the hand in 54 games, and at 394 turn starts (in 52 games) it was in hand with 3+ lands including a red source and an
  Izzet creature on the battlefield (section 5.4). That is exactly the kind of card-support problem Milestone 0 is meant to
  catch, and it biases every Gruul result.

## Files

| File | What it is |
|---|---|
| `parse_log.py` | prototype: log(s) -> per-game events (JSONL) and per-card stats (usage in its docstring) |
| `java/decklab/DeckLabSim.java`, `java/decklab-sim.jar` | Forge sim + card-movement listener (build commands in the file header) |
| `run_sim.py --card-log` | new option (added; default behaviour unchanged): runs DeckLabSim instead of Forge's `-jar` |
| `logs/lg-full-n1-s7.log` | **one complete game, Forge's own log** (seed 7, 359 lines, Gruul wins on turn 13 = round 7) |
| `logs/lg-cardlog-n1-s7.log` (+ `.events.jsonl`) | the same game with the card log (DeckLabSim, fixed version) |
| `logs/lg-full-n20-s1.log` / `.json` / `.stats.json` / `.events.jsonl` | 20 games, seed 1, Forge's own full log, parsed (plain mode) |
| `logs/lg-cardlog-n20-s1.*` | the same 20 games with the card log, parsed (exact mode) |
| `logs/lg-cardlog-GI-n50-s101/102.*`, `logs/lg-cardlog-IG-n50-s103/104.*` | 4 x 50 card-log games, run 4 at once; GI = Gruul is deck 1, IG = Izzet is deck 1 |
| `logs/lg-cardlog-pooled-220.stats.json` / `.events.jsonl` | the 220 card-log games above parsed together |
| `logs/lg-ab-plain-n50-s1.*`, `lg-ab-cardlog-n50-s1.*`, `lg-ab-plain2-n50-s1.*` | speed/size A/B, 50 games seed 1, run one after another |
| `logs/lg-cardlog-v1-bug-n20-s1.*` | first DeckLabSim version, kept as evidence of its bug (loser's end hand missing, section 3.3) |

## 1. The saved game

Command (from this folder): `python run_sim.py decks/gruul-ramp-owned.dck decks/izzet-prowess-owned.dck -n 1 -s 7 --user-dir forge-user-logs --log logs/lg-full-n1-s7.log --json logs/lg-full-n1-s7.json`
-> ok, start-up 9.19 s, the game took 1312 ms, Gruul won. 359 lines: 165 `Phase:`, 32 `Mana:`, 22 `Resolve Stack:`, 20 `Add To Stack:`,
15 `Damage:`, 13 `Turn:`, 10 `Combat:`, 9 `Land:`, 8 `Life:`, 5 `Zone Change:`, 4 `Replacement Effect:`, 2 `Mulligan:`, 2 `Player Control:`,
4 `Game Outcome:`, 1 `Match Result:`, 1 `Game Result:` plus start-up noise. Over the 20-game run (`lg-full-n20-s1.log`, 7,796 lines, 473 KB):
3945 Phase, 811 Mana, 527 Resolve Stack, 501 Add To Stack, 402 Damage, 310 Turn, 264 Combat, 247 Life, 241 Land, 89 Zone Change, 80 Game Outcome,
53 Replacement Effect, 51 Mulligan, 40 Player Control, 20 Match Result, 20 Game Result, 1 Discard. **No line type for draws or hands.**

The 20-game full-log run (seed 1) gave the **same 20 winners, first players and round counts** as the earlier `-q` run of seed 1
(`logs/rs-eager-q-n20-s1.json`), so `-q` doesn't change the games.

## 2. What Forge's own log shows (step 2)

| Need | In Forge's log? | Evidence |
|---|---|---|
| (a) opening hands, mulligans | **Mulligan count and kept hand size only; no card names; which cards went to the bottom isn't logged** | `Mulligan: Ai(1)-Gruul Ramp (owned) has mulliganed down to 6 cards.` / `Mulligan: Ai(1)-Gruul Ramp (owned) has mulliganed down to 5 cards.` / `Mulligan: Ai(1)-Gruul Ramp (owned) has kept a hand of 5 cards` (lg-cardlog-n20-s1.log game 11). 20 games: Gruul kept 7/6/5 in 16/3/1, Izzet 7/6 in 14/6. |
| (b) each card drawn | **No** | The draw step is empty: `Phase: Ai(1)-Gruul Ramp (owned)'s Draw step` is followed directly by `Phase: Ai(1)-Gruul Ramp (owned)'s Main phase, precombat` (lg-full-n1-s7.log lines 75-76). Card-draw effects show only as rules text: `Resolve Stack: Preordain (109) - Ai(2)-Izzet Prowess (owned) scries 2. Ai(2)-Izzet Prowess (owned) draws a card.`; scry only as counts: `Resolve Stack: Ai(2)-Izzet Prowess (owned) scried 2 card(s) to the bottom of the library`; tutors not at all: `Resolve Stack: When Fierce Empath enters, you may search your library for a creature card with mana value 6 or greater, reveal it, put it into your hand, then shuffle. [Zone Changer: Fierce Empath (8)]` (which card was found isn't said). |
| (c) lands played, spells cast, with turn and player | **Yes** (turn from the preceding `Turn:` line; the log is chronological) | `Turn: Turn 3 (Ai(1)-Gruul Ramp (owned))` ... `Land: Ai(1)-Gruul Ramp (owned) played Mountain (50)` ... `Add To Stack: Ai(1)-Gruul Ramp (owned) cast Scavenging Ooze`; `Add To Stack: Ai(2)-Izzet Prowess (owned) cast Scorching Dragonfire targeting [Scavenging Ooze (12)]`. Triggers and activations are told apart: `... triggered Swiftwater Cliffs`, `... activated Scavenging Ooze targeting [Firespitter Whelp (121)]`. **Caveats:** cast lines have **no card id** and **don't say which zone** the card was cast from, so a flashback Think Twice looks exactly like a cast from hand (`Add To Stack: Ai(2)-Izzet Prowess (owned) cast Think Twice`, lg-cardlog-n20-s1.log line 2228, where the card log shows `Graveyard|Stack`). Land lines, discards, deaths and most resolve/combat lines do carry ids. |
| (d) cards in hand at the end | **No** | The game ends `Life: Life: Ai(2)-Izzet Prowess (owned) 5 > 0` / `Player Control: ...` / `Game Outcome: ...`; nothing about hands or libraries. |
| (e) winner, first player, number of turns | **Yes** | `Turn: Turn 1 (Ai(1)-Gruul Ramp (owned))` (first player); `Game Outcome: Turn 7` (= rounds, `ceil(13 turns / 2)`); `Game Outcome: Ai(1)-Gruul Ramp (owned) has won because all opponents have lost`; `Game Outcome: Ai(2)-Izzet Prowess (owned) has lost because life total reached 0`; `Game Result: Game 1 ended in 1312 ms. Ai(1)-Gruul Ramp (owned) has won!` (timeouts misreport the winner: see setup-notes.md section 4; parse_log reuses run_sim's handling). |

Other useful facts from the log:
- Discards are logged with ids, including cleanup discards: `Discard: Ai(1)-Gruul Ramp (owned) discards Quaketusk Boar (59).` (the only one in 20 games).
- Deaths/exiles from the battlefield: `Zone Change: Scavenging Ooze (12) was put into Exile from Battlefield.`
- Multi-line entries: a `Combat:` entry with several attackers or blockers continues on lines with no caption
  (`Ai(2)-Izzet Prowess (owned) didn't block Fierce Empath (8).`); parsers must skip lines without a known caption.
- **Card ids are stable across the games of a run.** `Game.cardIdCounter` restarts at 1 for every game (`Game.nextCardId`), and
  `Match.preparePlayerZone` creates each player's cards in deck order *before* `player.shuffle(null)`, so the same copy has the same id in
  every game (e.g. `Think Twice (77)` and `(78)` recur across games; in the card log deck 1 is ids 1-60 and deck 2 is 67-126 in all 220 games).

## 3. Can Forge log more? (step 3)

### 3.1 No setting or flag (read in source)

- `SimulateMatch.simulateSingleMatch` prints `g1.getGameLog().getLogEntries(null)` without `-q`, else
  `getLogEntries(GameLogEntryType.MATCH_RESULTS)` (so `-q` keeps just `GAME_OUTCOME` and `MATCH_RESULTS`). `GameLog.getLogEntries(null)` returns
  **every entry of every type**, newest first; SimulateMatch reverses it. So sim mode already prints everything the log holds.
- `GameLogVerbosity` (LOW / MEDIUM / HIGH / CUSTOM) only filters *which stored entries are shown* (`getLogEntriesForVerbosity`), for the GUI
  log panel; SimulateMatch doesn't use it, and HIGH is simply all types. It can't add entries.
- `GameLogEntryType` has 19 types: GAME_OUTCOME, MATCH_RESULTS, TURN, MULLIGAN, ANTE, DRAFT, ZONE_CHANGE, PLAYER_CONTROL, DAMAGE, LIFE, LAND,
  DISCARD, COMBAT, INFORMATION, STACK_RESOLVE, STACK_ADD, EFFECT_REPLACED, MANA, PHASE. None of them is "draw".
- What creates entries: `GameLogFormatter` (a Guava `@Subscribe` on the game's `EventBus`, registered in the `Game` constructor) turns game
  events into entries, plus 25 direct `GameEventAddLog` call sites in forge-game (mulligan keep, discard, mill, reveal-as-cost, replacement
  effects, mana, stack adds, ante...) and 6 in the human player's controller (not used in sim). None logs a draw. For `GameEventCardChangeZone` it logs **only Battlefield -> Graveyard/Exile**: `// Only log Battlefield -> Graveyard/Exile
  to avoid duplicating entries already covered by other events (land played, spell cast, discard, etc.)` (`GameLogFormatter.visit(GameEventCardChangeZone)`).
  The mulligan keep line comes from `AbstractMulligan.afterMulligan` (hand *size* only), the mulligan line from `visit(GameEventMulligan)` (size only).
- Reveals (`GameAction.reveal`) go to each player's controller, not to the log, so "reveal it" tutors leave no trace.
- **Draws do fire an event:** `Player.doDraw` -> `game.getAction().moveTo(hand, c, ...)` -> `GameAction.changeZone` ->
  `game.fireEvent(new GameEventCardChangeZone(c, zoneFrom, zoneTo))`. The formatter just drops it.

### 3.2 Inferring draws from Forge's log alone

- **Lower bound:** every card that leaves the hand is logged (land drop with id, cast by name, discard with id), so it must have been drawn,
  kept in the opening hand, tutored or returned to hand. This is what parse_log's plain mode calls "seen".
- **Counts, not identities:** one draw per own turn except the starting player's turn 1, plus draw effects spotted in rules text
  (`... draws a card.`, `Whenever you cast a spell that targets Gnarlback Rhino, draw a card.`, kicked Into the Roil). Fragile, and tutors,
  bounces and flashback break it.
- **Impossible:** which cards stayed in hand. At the end, the unseen part of a deck is hand + library (e.g. 3 cards in hand vs 46 in the library in the
  seed-7 game) and nothing in the log separates them. So "stuck in hand" and "cast once drawn" can't be computed, and "win rate when drawn"
  becomes "win rate when played" (biased, section 5.3).

### 3.3 The card log (tested)

`java/decklab/DeckLabSim.java` = `forge.view.Main` start-up for `sim` (without the Sentry crash reporter) + `SimulateMatch.simulate` (single-match path,
same argument parsing, deck loading, AI profiles, `MyRandom.setRandom(new Random(seed))`, clock and output) + one extra line per game:
`g1.subscribeToEvents(cardLog)` between `mc.createGame()` and `mc.startGame(g1)` (`Game.subscribeToEvents` registers on the game's own `EventBus`).
The listener only reads game state and appends `INFORMATION` entries to the game's own `GameLog`, so they print in order with Forge's lines:

```
Information: DL|deck|<seat>|<id>=<name>;...                            each player's 60 cards with ids, once per game
Information: DL|zone|<turn>|<active seat>|<phase>|<from>|<to>|<owner seat>|<id>|<name>   every GameEventCardChangeZone
Information: DL|hand|1|start|<seat>|<id>=<name>;...                     kept hands, at GameEventTurnBegan for turn 1
Information: DL|hand|<turn>|end|<seat>|<id>=<name>;...                  after the game
Information: DL|library|<turn>|end|<seat>|<count>
```

Example (lg-cardlog-n1-s7.log, same game as lg-full-n1-s7.log):
```
Information: DL|zone|0|-|-|Library|Hand|1|8|Fierce Empath              <- opening 7 (turn 0 = mulligan stage)
Information: DL|hand|1|start|1|8=Fierce Empath;33=Forest;50=Mountain;57=Aggressive Mammoth;31=Surrak, the Hunt Caller;12=Scavenging Ooze;46=Rabid Gnaw
Phase: Ai(1)-Gruul Ramp (owned)'s Draw step
Information: DL|zone|3|1|DRAW|Library|Hand|1|54|Mountain              <- the draw Forge's log doesn't show
Information: DL|zone|3|1|MAIN1|Hand|Battlefield|1|50|Mountain
Land: Ai(1)-Gruul Ramp (owned) played Mountain (50)
Information: DL|zone|5|1|MAIN2|Library|Hand|1|9|Terror of Mount Velus  <- what Fierce Empath fetched
Information: DL|zone|8|2|MAIN1|Library|Library|2|98|Witness Protection <- Preordain's scry
Information: DL|zone|8|2|MAIN1|Library|Hand|2|126|Temple of Epiphany  <- Preordain's draw
Information: DL|hand|13|end|1|57=Aggressive Mammoth;9=Terror of Mount Velus;2=Gnarlback Rhino
Information: DL|hand|13|end|2|87=Heartfire Immolator;85=Counterspell;120=Firespitter Whelp
```
A London mulligan shows each 7 drawn, the cards shuffled back and the cards put on the bottom (`Hand|Library`) before each
`Mulligan: ... has mulliganed down to N cards.` line (lg-cardlog-n20-s1.log game 11).

**Build and run.** `javac -cp C:/Tools/forge/forge-gui-desktop-2.0.15-jar-with-dependencies.jar -d java/build java/decklab/DeckLabSim.java`
and `jar --create --file java/decklab-sim.jar -C java/build .` (JDK 26's javac, under a second; jar 9.5 KB). Because it starts with
`-cp <forge jar>;<decklab-sim.jar> decklab.DeckLabSim` instead of `-jar`, the jar manifest's `Add-Opens` list (20 packages) no longer
applies automatically; run_sim reads that list from the Forge jar's `META-INF/MANIFEST.MF` and passes it as `--add-opens <pkg>=ALL-UNNAMED`.
`python run_sim.py A.dck B.dck -n 20 -s 1 --card-log` does all of this (it refuses `-q`, and errors if the jar hasn't been built).

**Same games (tested).** Log with the `DL|` lines removed and times masked (`ended in N ms`, `Match Duration`), compared with `diff` against
Forge's own `-jar ... sim` log for the same seed: **identical** for seed 7 x 1 game (327 lines), seed 1 x 20 games (7,764 lines) and seed 1 x
50 games (21,071 lines; 28-22 to Gruul, the same as the setup runs of seed 1). run_sim's own summary parses the card-log output
unchanged (same winners, first players, rounds).

**Bug found and fixed:** the first version wrote end-of-game lines for `game.getPlayers()`, which drops a player as soon as they lose
(`Game.onPlayerLost` -> `ingamePlayers.remove(p)`), so the loser's end hand was missing in all 20 games (`logs/lg-cardlog-v1-bug-n20-s1.log`,
40 problems flagged by parse_log's check once it required every seat). Fixed by using `game.getRegisteredPlayers()` (`allPlayers`).
For 4-player Commander, a player who loses before the end probably has their cards removed from the game (rule 800.4a), so their "end hand" would
be empty or partial; not tested.

**Cost (tested, `logs/lg-ab-*`, 50 games seed 1, one run at a time, one other agent's Forge process running):** plain 822.3 ms/game
(41.34 s of games), card log 893.5 ms (44.92 s), plain again 859.7 ms (43.20 s): the card log is within about 4-9%, and the two plain runs already differ by 4.5%.
Start-up unchanged (10.1-10.3 s here). Log size 1,277,129 -> 1,716,287 bytes (+34%, about 34 KB per game); 20 games: 1,929 `DL` lines (about 96 per game).

**Maintenance risk:** DeckLabSim copies about 120 lines of `SimulateMatch` and the private `deckFromCommandLineParameter`, so each Forge upgrade
needs a diff of `forge-gui-desktop/src/main/java/forge/view/SimulateMatch.java` and `Main.java` between tags, and a rebuild against the new jar
(the jar name has the version in it). The event classes it uses (`GameEventCardChangeZone`, `GameEventTurnBegan`, `Game.subscribeToEvents`,
`GameLog.add`) are core API that the GUI uses too. Forge is GPL-3; the class is for personal use, not distribution.

## 4. parse_log.py (step 4)

`python parse_log.py LOG [LOG ...] [--events OUT.jsonl] [--json OUT.json] [--source auto|cardlog|plain] [--compare] [--min-games N] [--deck NAME]`
(details in its docstring). It splits the log into games at each `Game Result:` line, parses each line by its caption (`Turn`, `Mulligan`,
`Land`, `Add To Stack`, `Discard`, `Zone Change`, `Information: DL|...`), and takes results (winner, first, rounds, timeouts) from
`run_sim.parse`, so Forge's misreported timeouts are handled the same way. Decks are matched by the `Name=` in the `.dck`, so runs with the
deck order swapped pool correctly (tested: 2 GI + 2 IG runs). Per-game events go to JSONL: players, result, mulligans, kept size, and
(with a card log) the deck by id, opening hand, end hand and every card movement. Parsing the 220 card-log games (7.4 MB of logs) took 0.54 s.

With a card log it runs these consistency checks (0 problems in all 220 games after the fix):
replaying every `zone` move from "all cards in the library" gives exactly the `end` hand and `library` count of every player; the `start` hand
size equals Forge's `has kept a hand of N cards`; every Forge `Land:` line has a `Hand -> Battlefield` move of the same id on that turn; every
Forge `cast X` line has a move of an X card to the Stack on that turn. Extra check done by hand on 3,686 turns: the active player moved exactly one
card Library -> Hand in their draw step (none on turn 1) in all but 15 turns, and all 15 are legitimate: 5 games ended before the draw step,
10 had a draw during the draw step from an instant (kicked Into the Roil, Think Twice) or Gnarlback Rhino's "Whenever you cast a spell that
targets Gnarlback Rhino, draw a card." (Bite Down, Rabid Gnaw).

### Definitions used for the stats (card log)

- "Drawn" = the copy **reached the hand**: in the kept opening hand, or moved to the hand from any zone after the mulligans. This includes
  tutors (Fierce Empath) and returns (Eternal Witness); London-mulligan cards that went back aren't counted.
- "Used" = cast from the hand (a move Hand -> Stack), or played as the land drop (Forge's `Land:` line). Casts from other zones are counted
  separately (`gy` column: Think Twice flashback, 69 casts in 220 games).
- "Stuck" = in the hand when the game ended.
- "Round" = `ceil(Forge turn / 2)`, the same count as Forge's `Game Outcome: Turn N` (a player's own turn number for things cast on their own turn).
- Win rate: timeouts, errors and draws count as non-wins (none happened in these runs).

## 5. Results

### 5.1 Runs

| Run | Command (from this folder) | Result |
|---|---|---|
| 20 games, Forge log | `python run_sim.py decks/gruul-ramp-owned.dck decks/izzet-prowess-owned.dck -n 20 -s 1 --user-dir forge-user-logs --log logs/lg-full-n20-s1.log --json logs/lg-full-n20-s1.json` | Gruul 12-8; start-up 7.75 s; 924 ms/game |
| same, card log | `... -n 20 -s 1 --card-log --user-dir forge-user-logs --log logs/lg-cardlog-n20-s1.log --json logs/lg-cardlog-n20-s1.json` | identical games; 953 ms/game |
| 4 x 50, card log, 4 processes at once | seeds 101, 102 with `gruul izzet`, 103, 104 with `izzet gruul`, each `-n 50 --card-log` | all ok, 0 draws/timeouts/errors; start-up 14.19-14.52 s; 200 games in 72 s wall (1018-1137 ms/game) |
| parse 220 | `python parse_log.py logs/lg-cardlog-n20-s1.log logs/lg-cardlog-GI-n50-s101.log logs/lg-cardlog-GI-n50-s102.log logs/lg-cardlog-IG-n50-s103.log logs/lg-cardlog-IG-n50-s104.log --compare --events logs/lg-cardlog-pooled-220.events.jsonl --json logs/lg-cardlog-pooled-220.stats.json` | Gruul 105 wins, Izzet 115 (the 200 new games: 93-107); 112 mulligans in 440 player-games; 18.2 cards moved Library -> Hand per game after the mulligans |

### 5.2 Draft per-card stats, 220 games (card log, exact)

Columns: n = copies in deck; drawn G = games where a copy reached hand; WR drawn / WR not = the deck's win rate in games where it did / didn't;
copies = copies that reached hand; used / stuck = share of those copies cast-or-played / still in hand at the end; avg rnd = mean round of each
copy's first cast; gy = casts from the graveyard. The last three columns are the plain-log proxy (section 5.3). Full table: `parse_log.py ... --compare`.

Gruul Ramp (owned), 220 games, 105 wins (48%), selected rows:
```
card                              n drawn G WR drawn  WR not  diff copies   used  stuck avg rnd  gy | seen G WR seen WR unseen
Forest                            9     210      50%     10%   +40    544    97%     3%     3.9     |    210     50%       10%
Llanowar Elves                    4     146      49%     45%    +5    196    93%     7%     3.3     |    136     49%       46%
Snakeskin Veil                    2      98      54%     43%   +11    112    69%    31%     6.6     |     71     69%       38%
Terror of Mount Velus             1      86      48%     48%    -0     86    45%    52%     7.9     |     42     57%       46%
Aggressive Mammoth                1      64      50%     47%    +3     64    58%    42%     7.2     |     37     76%       42%
Quakestrider Ceratops             1      62      45%     49%    -4     62    47%    53%     7.7     |     29     69%       45%
Rampaging Baloths                 1      62      47%     48%    -1     62    37%    61%     6.3     |     24     62%       46%
Surrak, the Hunt Caller           1      58      59%     44%   +15     58    86%    21%     5.6     |     50     62%       44%
Pelakka Wurm                      1      55      40%     50%   -10     55    20%    75%     7.5     |     14     64%       47%
Fiery Annihilation                1      54      24%     55%   -31     54     0%   100%       -     |      0      -        48%
Lathliss, Dragon Queen            1      43      44%     49%    -4     43    37%    60%     6.9     |     17     53%       47%
Savage Ventmaw                    1      43      40%     50%   -10     43    42%    56%     6.7     |     19     63%       46%
```
Izzet Prowess (owned), 220 games, 115 wins (52%), selected rows:
```
Burst Lightning                   4     165      55%     45%    +9    259    93%     7%     5.1     |    157     57%       41%
Preordain                         4     149      55%     46%    +9    245    95%     5%     4.2     |    145     55%       47%
Counterspell                      2     108      55%     50%    +5    118    57%    43%     6.7     |     64     58%       50%
Think Twice                       2      88      53%     52%    +2    108    88%    12%     5.5  69 |     80     52%       52%
Essence Scatter                   1      51      51%     53%    -2     51    59%    41%     6.6     |     30     53%       52%
Bria, Riptide Rogue               1      55      64%     48%   +15     55    84%    15%     6.3     |     47     66%       49%
```
Over all cards: 6,976 copies reached hand; 86.1% were used and 14.0% were stuck (a few copies were both: cast, bounced back by Into the Roil
and held; a few were neither: discarded).

What this says, with caution: Gruul's top end (Pelakka Wurm 75% stuck, Rampaging Baloths 61%, Lathliss 60%, Savage Ventmaw 56%, Quakestrider
Ceratops 53%, Terror of Mount Velus 52%) is stuck in hand in more than half the games it's drawn: the ramp deck often doesn't reach 6-7 mana
before the game is decided. Counterspell and Essence Scatter are held about 40% of the time (reactive cards the AI keeps up).

### 5.3 How good the plain-log proxy is (same 220 games)

- In 5,286 card-games where a card was drawn, Forge's log showed it (played, cast or discarded) in 4,498 (85.1%). The other 14.9% are
  exactly the "stuck" cases, and they aren't random.
- For the 58 cards with 30+ drawn games and 10+ seen games, the proxy's "WR seen minus WR unseen" differed from the exact "WR drawn minus WR not"
  by **6.1 points on average, 30.4 at most**. Worst: Aggressive Mammoth exact +3 vs proxy +34, Quakestrider Ceratops -4 vs +24, Pelakka Wurm
  -10 vs +18, Savage Ventmaw -10 vs +17, Snakeskin Veil +11 vs +31, Rampaging Baloths -1 vs +17. Expensive and reactive cards get cast mostly in
  games that are going well, so the proxy flatters them: it would recommend exactly the cards that are actually stuck in hand.
- Plain mode also can't list a card that was never played in any game (57 of 59 names in the 20-game run; Fiery Annihilation and Lathliss were
  missing) unless it is given the deck list.

### 5.4 Fiery Annihilation is never cast by Forge's AI

In 220 games Fiery Annihilation reached Gruul's hand in 54 games and was **never cast** (0 moves Hand -> Stack; 54 of 54 copies still in hand at the end).
Counted from the event JSONL: in 52 of those games there were 394 turn starts where it was in hand, Gruul had 3+ lands on the battlefield
including a red source, and Izzet had a creature on the battlefield (first example: lg-cardlog-n20-s1.log game 8, turn 15, Gruul with
Mountain, Gruul Guildgate, Forest, Temple of Abandon, Forest, Mountain; Izzet with Firespitter Whelp and Coruscation Mage). Other removal in
the same deck is cast normally (Flame Lash 91%, Bite Down 81%, Rabid Gnaw 76% of drawn copies). Forge's script (`res/cardsfolder/cardsfolder.zip`,
`f/fiery_annihilation.txt`) has no `AI:RemoveDeck` flag; its spell is `SP$ DealDamage ... SubAbility$ DBChangeZone` with an optional second target
(`ValidTgts$ Equipment.AttachedTo ParentTarget | TargetMin$ 0 | TargetMax$ 1`). **Why the AI never casts it is not investigated yet** (the
optional Equipment target is a guess, not checked in the AI code). It is effectively a blank card in every Gruul simulation.

### 5.5 What is supported

| Stat | Forge's own log | With the card log (`--card-log`) |
|---|---|---|
| Win rate when drawn vs not drawn | **Approximate only**, as "when played/cast/discarded vs not": biased (6 pts mean, 30 max, section 5.3) | **Fully supported** |
| How often cast once drawn | **Not possible** (no draws, so no denominator); only casts per game | **Fully supported** (per copy, by id; flashback casts counted separately) |
| How often stuck in hand | **Not possible** (end hands aren't logged; hand vs library can't be told apart) | **Fully supported** (end-of-game hand by id) |
| Average turn cast | **Fully supported** for the first cast of a card name per game (cast lines + `Turn:` lines); per copy only approximately, because cast lines have no ids and don't say "from graveyard" | **Fully supported** per copy |
| Opening hands / mulligans | Mulligan count and kept size only | Full kept hand, every mulligan's 7 and the cards bottomed |
| Winner, first player, turns | Fully supported | same |

Caveats for all of them:
- **Sample size.** A 1-of is drawn in about 25% of games (43-86 of 220 here). With 55 drawn games the win-rate standard error is about 6.7 points
  (95% range about +/-13), and the drawn-vs-not difference about +/-15. A 5-point effect needs thousands of games per pairing. "Used" and "stuck"
  rates settle much faster and are the most useful stats at a few hundred games.
- **Confounding.** Win rate when drawn mixes the card's strength with game flow (e.g. Forest +40: not drawing a Forest means colour screw). Treat
  it like 17lands' "games in hand" figure: use it for comparison, not as the card's value.
- **AI quality.** A card the AI misplays (Fiery Annihilation) or holds shows up as weak; per-card stats measure the card *as Forge's AI plays it*.
- **Commander:** with 4 players the loser's cards may leave the game before the end snapshot (not tested); stats per deck across 4 seats should still work.

## 6. Suggestions for the plan

- For the "Later: per-card stats" item: build it on `run_sim.py --card-log` + `parse_log.py`, not on Forge's plain log. It needs a JDK (javac/jar are
  in the installed JDK 26) or the prebuilt 9.5 KB jar, and a re-check of `SimulateMatch.java`/`Main.java` on each Forge upgrade.
- Use the "used %" / "stuck %" columns as a **card-support check in Milestone 0 step 4**: a card that is drawn often and never cast (Fiery Annihilation)
  signals an AI problem, not a weak card. Worth running every deck once through a card-log run for this alone.
- Store parsed per-game JSON (about 23 KB per game in JSONL) or the stats, and delete raw logs (34 KB per game with the card log), or gzip them.
