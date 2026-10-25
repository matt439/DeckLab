# Forge trial: other deck sizes and formats (Milestone 0, steps 5 and 6)

Written 2026-09-29 on HomePC (Ryzen 9 9950X3D, 16 cores / 32 threads, 64 GB, Windows 11) with Forge 2.0.15 on JDK 26.0.1,
following `setup-notes.md` (read that first: install, command line, parser caveats). Every statement is either read in Forge's
source at tag `forge-2.0.15` (`https://raw.githubusercontent.com/Card-Forge/forge/forge-2.0.15/<path>`, file named inline) or
measured here; each item says which. Paths are relative to this folder (`decklab/forge-trial/`, gitignored).

## Summary

| Question | Answer | Evidence |
|---|---|---|
| Does sim mode accept 40-card decks? | **Yes, with no flag.** Sim mode never checks deck size, copy limits or singleton; only the GUI lobby does (preference `ENFORCE_DECK_LEGALITY`). | source (1.1); 20 + 50 games of Cats+Vampires vs Goblins+Elves (1.2) |
| 20-card halves? | Also accepted and played normally; 1 of 20 games ended by decking (turn 28). | 1.3 |
| 60-card products (BLB Starter Kit, Challenger) | Load and play; no unsupported cards. The Challenger sideboard loads but is never used. | 2 |
| 1v1 Commander (`-f Commander`, 2 decks) | **Works.** 40 life, command zone, commander tax and commander damage (21) all work. **About 2 s per game** (40 games: median 1.6 s, max 14.7 s). Seeded runs replay exactly. | 3 |
| 4-player Commander (4 decks) | **Works, but slowly and not reproducibly.** 23 games: median 38 s, mean 72 s, max 216 s (1.3 s per turn; 35-91 turns). Seat 1 starts almost every game. Seeded 4-player runs diverge once Forge's 5 s AI decision limit fires. | 3.4-3.8 |
| Multiplayer winner reporting | Same lines as 2-player, one `has lost ...` per loser; winner is correct. No elimination order is printed, but it can be derived from the full log. Timeouts: every surviving player "has won" and Forge credits one seat, so the timeout check in run_sim is essential. | 3.6, 3.7 |
| Crashes / hangs | None. 0 crashes, 0 hangs, 0 timeouts at `-c 300/600`; one `-c 10` test timed out all 3 games cleanly and the process carried on. | 3.7 |
| New problem found | **Forge's AI never casts or activates cards flagged `AI:RemoveDeck:All`**, and sim mode prints no warning. Our decks contain 4 such cards, including **Ghoulcaller Gisa, the commander of 2 of the 5 Commander decks** (never cast in 52 deck-games). | 4 |
| run_sim.py | Parser fixed: decking and commander-damage losses now have a `loss_reason`, and **alternate wins were misread as draws** (fixed). Added `--mem` and a per-game `turns` field. | 5 |

## 0. How the runs were made

- Decks: `decks/formats/*.dck`, made with `to_dck.py` (name-only lines, the default) from the repo files:

  | .dck | Source | Cards |
  |---|---|---|
  | `bb-cats-vampires.dck` | `magic/products/fdn-beginner-box.csv --deck Cats --deck Vampires` | Main 40 |
  | `bb-goblins-elves.dck` | same, `--deck Goblins --deck Elves` | Main 40 |
  | `bb-cats.dck`, `bb-goblins.dck` | one 20-card half each (13 spells/lands + 7 basics) | Main 20 |
  | `blb-hare-raising.dck`, `blb-otter-limits.dck` | `magic/products/blb-starter-kit.csv --deck "Hare Raising"` / `"Otter Limits"` | Main 60 |
  | `lightning-aggro.dck` | `magic/products/challenger-2019-lightning-aggro.csv` (sections deck + sideboard) | Main 60, Sideboard 15 |
  | `gruul-ramp-owned.dck` | copy of `decks/gruul-ramp-owned.dck` | Main 60, Sideboard 6 |
  | `cmd-giada-precon.dck` | `magic/products/fdc-calling-all-angels.csv` (commander + deck sections) | Commander 1, Main 99 |
  | `cmd-gisa-precon.dck` | `magic/products/fdc-wretched-ranks.csv` | Commander 1, Main 99 |
  | `cmd-finneas-rabbits.dck` | `magic/decks/commander/finneas-rabbits.md --list target --name "Finneas Rabbits"` | Commander 1, Main 99 |
  | `cmd-giada-angels.dck` | `magic/decks/commander/giada-angels.md --list target --name "Giada Angels (upgraded)"` | Commander 1, Main 99 |
  | `cmd-gisa-zombies.dck` | `magic/decks/commander/gisa-zombies.md --list target --name "Gisa Zombies (upgraded)"` | Commander 1, Main 99 |
  | `cmdtest-zurgo.dck`, `cmdtest-emrakul.dck`, `cmdtest-felidar.dck`, `cmdtest-felidar-main.dck` | hand-written rules tests (3.5, 5) | |

  to_dck.py already handled every case (product `deck` and `section` columns, and the `Commander` header inside the deck files'
  fenced block), so it needed no changes. `--name` was used for the three deck files only to keep player names short.
- Every run: `python run_sim.py <decks> -n N -s SEED [-f Commander] -c SEC [--mem] [--xmx ...] --user-dir forge-user-formats --log logs/formats/<tag>.log --json logs/formats/<tag>.json`,
  with the full game log (no `-q`), eager card loading (Forge's default) and `-Xmx1024m` (run_sim's default) unless stated.
  A separate user folder (`forge-user-formats/`) was used because other agents were running with `forge-user/` at the same
  time, and run_sim rewrites that folder's `forge.preferences` to match `--lazy`.
- Load on the PC: `loadmon.py` (new, in this folder) sampled system CPU % (Win32 `GetSystemTimes`; 100 % = all 32 logical
  CPUs) and the number of `java.exe` processes every 2 s into `logs/formats/loadmon.csv`. Other programs used 13-22 % CPU even
  with no Java running, and other agents' Forge runs sometimes overlapped, so every timing below states the load during it
  (computed from `loadmon.csv` between each run's start, JSON mtime minus `wall_s`, and its end).
- At most 4 of my Forge processes ran at once: 4 for the A1/A2/B1/B2 smoke runs, 2 for C1+C2 and for C7b+C7c, otherwise 1.

## 1. 40-card Beginner Box pairings (Milestone 0 step 5)

### 1.1 Source: sim mode has no deck-size check

- `SimulateMatch.simulate` (forge-gui-desktop/.../view/SimulateMatch.java) loads each `-d` file with `DeckSerializer.fromFile`, wraps
  it in `new RegisteredPlayer(deck)` (or `RegisteredPlayer.forCommander(deck)` with `-f Commander`), builds `new GameRules(type)` and
  `new Match(rules, players, "Test")`, and plays. There is no legality call anywhere on that path.
- `Match.createGame` / `Match.startGame` / `Match.prepareAllZones` (forge-game/.../game/Match.java) only call `Deck.getValid()`, which
  removes cards whose rules are unsupported (forge-core/.../deck/Deck.java lines 132-144) and checks nothing else. `getMainRange()`
  is read in `Match.prepareAllZones` only to build a stand-in deck when a player's deck is null, and in `Player.java` for companion rules.
- The size and copy rules live in `DeckFormat` (forge-core/.../deck/DeckFormat.java): `Constructed(Range.of(60, MAX), sideboard 0-15, 4 copies)`,
  `Limited(Range.of(40, MAX), ...)`, `Commander(Range.is(99), sideboard 0-10, 1 copy)`. Its `getDeckConformanceProblem` is
  called only by GUI and quest classes. A byte scan of every `forge/**.class` in the jar for that method name found
  `DeckFormat`, `GameFormat`, `GameLobby`, `QuestDraftUtils`, `QuestTournamentController`, `QuestUtil` and `CSubmenuDraft/Sealed/Winston`,
  but not `SimulateMatch` or `Match`. `GameLobby.java` (forge-gui/.../gamemodes/match/) lines 428-441 and 489-493 run it only when the
  preference `ENFORCE_DECK_LEGALITY` (default `true`, ForgePreferences.java line 208) is set, and only in the GUI lobby.
- **So no flag, format option or preference is needed for 40-card (or any size) decks in sim mode.** The same holds for copy limits
  and Commander singleton: `cmdtest-felidar-main.dck` (30 copies of Felidar Sovereign in a Commander deck) loaded and played (section 5).
- The Beginner Box halves need nothing special either: the 20 cards include 7 basics plus Uncharted Haven, so a pairing is a normal
  40-card deck with 16 lands (14 basics + 2 Uncharted Haven).

### 1.2 Test: Cats+Vampires vs Goblins+Elves

| Run | Games | Result (deck 1 - deck 2) | Went first | ms/game mean (median; min-max) | Turns mean (min-max) | Start-up s | Load during run |
|---|---|---|---|---|---|---|---|
| A1 (`-s 1`) | 20 | 13-7 | 8 / 12 | 1191 (1076; 447-2769) | 17.8 (11-25) | 14.72 | 4 of my processes + up to 1 other; CPU mean 58 %, max 89 % |
| A3 (`-s 2 --mem`) | 50 | 34-16 | 16 / 34 | **920** (680; 266-4293) | 18.2 (10-31) | 9.63 | alone; CPU mean 30 % |

- All 70 games ended normally (`life total reached 0`): 0 draws, 0 timeouts, 0 exceptions, 0 unsupported cards.
- A3: 64.9 games/min in one process, peak working set 1046 MB (private 1173 MB), 159.0 CPU-s over 55.9 s wall (2.85 cores busy).
- The AI plays the 40-card decks properly: over A1 it cast 24 of the 27 distinct cards in each deck at least once, and played all 3
  land types (`castcheck.py`, see section 7).
- Same-conditions 60-card baseline (G60: Gruul Ramp owned vs Izzet Prowess owned, 50 games, `-s 2 --mem`, alone, CPU mean 27 %):
  677 ms/game (median 612; 321-2094), 88.1 games/min, turns 16.9 (11-33), peak 1055 MB, 138.5 CPU-s (3.30 cores).
  So a 40-card Beginner Box game is not faster than a 60-card game; the deck contents set the time, not the size.
  G60's 50 games were identical (winner, rounds and starting player each game) to the first 50 of `logs/rs-eager-full-n100-s2.json`,
  run earlier by another agent with a different user folder, which confirms seeded 2-player runs are reproducible.
- An overnight "all 45 Beginner Box pairings" run (plan, "Later") is cheap at this speed: 45 pairings x 200 games x 0.92 s is about
  2.3 hours in one process, or well under an hour with a few processes (throughput is being measured separately).

### 1.3 A single 20-card half vs another half (A2: Cats vs Goblins, 20 games, `-s 1`)

- Accepted without any message and played like any other deck: 13-7, went first 8/12, 1248 ms/game (median 914; 504-2879),
  17.1 turns (11-28). Load as A1.
- **1 of 20 games ended by decking**: game 3, `Ai(2)-BB Goblins has lost trying to draw cards from empty library`, on turn 28.
  Goblins was on the draw, so after its 7-card opening hand its 13 remaining cards were drawn on its turns 2-26 and the draw on turn 28
  lost. The other 19 games ended on life before either library ran out.
- The old run_sim parser gave that game no `loss_reason` (it only understood "has lost because ..."); fixed (section 5).

## 2. 60-card products (smoke test)

| Run | Decks | Games | Result | ms/game mean (min-max) | Turns mean (min-max) | Load |
|---|---|---|---|---|---|---|
| B1 (`-s 1`) | BLB Hare Raising vs BLB Otter Limits | 10 | 7-3 | 2399 (843-6653) | 17.9 (15-32) | 4 of my processes (as A1) |
| B3 (`-s 2 --mem`) | same | 20 | 13-7 | 1163 (median 891; 506-5620) | 19.1 (12-44) | alone, CPU mean 25 % |
| B2 (`-s 1`) | Challenger Lightning Aggro (60 + 15 sideboard) vs Gruul Ramp (owned) | 10 | 7-3 | 1229 (429-2699) | 14.3 (11-19) | 4 of my processes |

- All decks loaded with 0 unsupported cards, and all 40 games finished normally (0 draws, timeouts or exceptions).
- The Challenger sideboard loads (Forge puts it in the Sideboard zone) but is never used: AI sideboarding is off in sim mode
  (`GameRules.AISideboardingEnabled = false`, see setup-notes section 4).
- Cards cast at least once (B1, B2): Hare Raising 16 of 20 distinct cards (never cast: Byrke, Long Ear of the Law, a 1-of),
  Otter Limits 16 of 19, Lightning Aggro 11 of 13 (never: Banefire). The misses are 1-of cards in 10 games, not support problems.
- B3 used 51.4 games/min, peak 1028 MB, 88.4 CPU-s.

## 3. Commander (Milestone 0 step 6)

### 3.1 Conversion

All five lists converted to `[Commander]` 1 + `[Main]` 99 (table in section 0), with 0 unsupported cards in any Forge run.
The deck files' `Commander` / `Deck` headers inside the fenced block are what to_dck.py maps to `[Commander]` / `[Main]`.

### 3.2 Source: what `-f Commander` does

- `SimulateMatch`: `GameType.valueOf("Commander")`, `rules.setAppliedVariants({Commander})`, each deck registered with
  `RegisteredPlayer.forCommander(deck)`, which sets `commanders = deck.getCommanders()` (the `[Commander]` section) and
  `setStartingLife(40)` (forge-game/.../player/RegisteredPlayer.java line 137). Any number of `-d` decks is accepted; all play in
  one free-for-all game (no teams).
- `Player.initVariantsZones` (forge-game/.../player/Player.java around line 2985) puts each commander card in the Command zone and
  registers it with `addCommander`. It does **not** check that the commander is legendary, or the deck's colour identity.
- Commander damage is a state-based loss: `Player.java` line 2053, `entry.getValue() >= 21 && loseConditionMet(GameLossReason.CommanderDamage)`,
  with damage tracked per commander card (`commanderDamage` map, line 187).
- A commander put into a graveyard or exile goes back to the command zone through `GameAction.stateBasedAction_Commander`
  (GameAction.java line 1830), which asks the owner's controller `confirmAction`. The AI has no specific answer and falls back to
  the default, printing `Warning: default (ie. inherited from base class) implementation of confirmAction is used by <commander> for
  forge.ai.ability.PermanentCreatureAi` (seen 14 times for Giada and 4 for Finneas in the logs). The recasts below show it chooses to return them.
- Who goes first (GameAction.determineFirstTurnPlayer, lines 2384-2440): game 1 is a random player; after that, **the first
  player in seat order who did not win the previous game**. With 2 players that is the loser; with 4 players it is seat 1 unless seat 1
  won, then seat 2. The AI always chooses to play.

### 3.3 1v1 Commander

| Run | Decks | Games | Result | Went first | ms/game mean (median; min-max) | Turns mean (min-max) | Load |
|---|---|---|---|---|---|---|---|
| C1 (`-s 1 -c 300`) | Giada precon vs Gisa precon | 10 | 8-2 | 2 / 8 | 1655 (1794; 748-2562) | 17.2 (12-25) | 2 of my processes, CPU mean 46 % |
| C1r (replay of C1, `--mem`) | same | 10 | 8-2 | 2 / 8 | 1509 (1642; 703-2505) | 17.2 (12-25) | alone, CPU mean 29 % |
| C6 (`-s 1 -c 300 --mem`) | Finneas Rabbits vs Giada Angels (upgraded) | 20 | 3-17 | 18 / 2 | 2528 (1574; 939-14716) | 18.2 (13-32) | alone (up to 1 other), CPU mean 29 % |

- **All 40 games: about 2 s per game** (mean 2.1 s, median 1.6 s, 90th percentile 2.6 s, max 14.7 s), 116 ms per turn, 17.7 turns
  (about 9 rounds) on average. 0 draws, timeouts or exceptions.
- **Seeded 1v1 Commander runs replay exactly**: C1r had the same winner, turns, starting player and loss reason as C1 in all 10 games.
- Memory: peak working set 1041 MB (C1r) and 1078 MB (C6) at `-Xmx1024m`. CPU: 85.1 CPU-s over 29 s (2.94 cores), and 143.8 CPU-s over 59 s (C6).
- Start-up to the first game: 8.5-13.8 s (eager loading), the same as 60-card runs.
- The AI plays the Commander decks: in C6 it cast 60 of Finneas's 75 distinct cards and 58 of Giada Angels's 70, including the
  adventure half `Hare Raising` of Pollen-Shield Hare. Never cast in 20 games: Finneas: Good-Fortune Unicorn, Beast Within (see
  section 4), Rabbit Response, Hop to It; Giada: Sol Ring, Commander's Sphere, Austere Command, Youthful Valkyrie, Sunblast Angel.

### 3.4 4-player Commander pods

| Run | Seats 1-4 | Games | Wins by seat | Seat that went first | ms/game (per game) | Turns | Load |
|---|---|---|---|---|---|---|---|
| C2 (`-s 1 -c 600`) | Giada precon, Gisa precon, Finneas Rabbits, Gisa Zombies (upgraded) | 3 | 1, 0, 1, 1 | 3, 2, 1 | 31974, 14849, 40020 | 36, 35, 44 | 2 of my processes, CPU mean 31 % |
| C7 (`-s 2 -c 600 --mem`) | Giada Angels (upgraded), Gisa Zombies (upgraded), Finneas Rabbits, Giada precon | 10 | 3, 0, 1, 6 | seat 1 in 8, seat 2 in 2 | mean 65968, median 34643, 14606-210595 | 39-91 (mean 56.7) | alone except 13:07-13:08, when another agent ran 4-5 processes; CPU mean 27 %, max 92 % |
| C7b (replay of C7 games 1-5, `-Xmx4096m`) | as C7 | 5 | | | 24261, 25864, 206336, 215492, 40995 | 39, 42, 79, 78, 58 | with C7c; CPU mean 33 % |
| C7c (replay of C7 games 1-5, `-Xmx1024m`) | as C7 | 5 | | | 24298, 25791, 208886, 39334, 96942 | 39, 42, 79, 46, 69 | with C7b; CPU mean 30 % |

- **It works:** all 23 games finished with exactly one winner and three `has lost ...` lines (68 losses by life total, 1 by decking:
  seat 1, Giada Angels, in C7b game 4 after 78 turns); 0 crashes, 0 hangs, 0 timeouts at `-c 600`.
- **Time per game: median 38 s, mean 72 s** (23 games; 90th percentile 209 s, min 14.6 s, max 215.5 s); 7 of 23 games took over 60 s.
  Games lasted 35-91 turns (mean 54.5), about 1.3 s per turn, which is 11 times the 1v1 rate. C7 managed 0.9 games/min.
  Long games (C7 game 3: 79-81 turns, 206-211 s in all three runs) have big boards, and the AI's per-decision search dominates.
- **Heap is not the bottleneck:** C7b (`-Xmx4096m`) and C7c (`-Xmx1024m`) ran side by side and took the same time for the
  identical games 1-2 (24.3/25.9 s against 24.3/25.8 s) and for game 3 (206 s against 209 s). Peak working set follows `-Xmx`: 2593 MB at
  4096m, 1207 MB at 1024m (C7 at 1024m: 1274 MB, private 1357 MB). **`-Xmx1024m` is enough for 4-player pods.**
- CPU: C7 used 1178 CPU-s over 669 s (1.76 cores). C7b and C7c used 692 and 744 CPU-s. 4-player sims are mostly one AI thread.
- **Seat 1 goes first in almost every game after game 1** (C7: 8 of 10; the only exceptions follow a seat-1 win), as
  `determineFirstTurnPlayer` predicts. Rotate seat order between batches to balance it.

### 3.5 Rules checks (from the logs)

- **Starting life 40**, in 1v1 and 4-player: the first `Life:` line for every player in every game starts at 40 (for example C2 game 1:
  `Life: Life: Ai(1)-Giada precon 40 > 41`, `Ai(3)-Finneas Rabbits 40 > 30`).
- **Command zone and commander tax work.** C1 game 1: `Ai(1)-Giada precon cast Giada, Font of Hope` paid with 2 Plains ({1}{W});
  Giada died (`Zone Change: Giada, Font of Hope (100) was put into Graveyard from Battlefield.`, log line 194); on her owner's next turn
  (turn 9) she was cast again, paid with 4 Plains ({1}{W} plus {2} tax, lines 210-214). Across C1 Giada was cast 19 times in 10 games (up to 3 times in one game).
  The move from graveyard to the command zone is **not** logged as a `Zone Change` line; only the recast shows it.
  Finneas was cast up to 3 times per game in C2.
- **Commander damage works** (C3, `cmdtest-zurgo.dck`: Zurgo Helmsmasher + 99 basic lands vs `cmdtest-emrakul.dck`: Emrakul + 99 Islands,
  3 games, `-f Commander -s 1`): Zurgo was cast on turn 9 and hit for 7 on turns 9, 11 and 13 (`Life: ... 40 > 33`, `33 > 26`, `26 > 19`),
  and every game ended `Ai(2)-Test Emrakul lands has lost due to accumulation of 21 damage from generals` with the loser on **19 life**.
  In C4, Emrakul (15/15) also killed its opponent with 30 commander damage (40 > 25 > 10).
- **Free first mulligan in multiplayer only:** 4-player logs show `has mulliganed down to 7 cards` (a free mulligan), and 1v1 logs don't
  (`mulliganed down to 6 cards` on the first mulligan). That matches CR 103.5c (the free mulligan applies to multiplayer games).
- A non-legendary commander loads (sim mode doesn't check), but in C4 the AI never cast Felidar Sovereign from the command zone
  in 15 turns with 15 Plains. The cause was not investigated, and all our commanders are legendary.

### 3.6 How the winner is reported in multiplayer

At the end of each game (from the full log of C2; with `-q` these are the only lines printed per game according to setup-notes
section 5, not re-tested with 4 players):
```
Game Outcome: Match Duration 0m : 31s
Game Outcome: Turn 18
Game Outcome: Ai(1)-Giada precon has won because all opponents have lost
Game Outcome: Ai(2)-Gisa precon has lost because life total reached 0
Game Outcome: Ai(3)-Finneas Rabbits has lost because life total reached 0
Game Outcome: Ai(4)-Gisa Zombies (upgraded) has lost because life total reached 0
Match Result: Ai(1)-Giada precon: 1 Ai(2)-Gisa precon: 0 Ai(3)-Finneas Rabbits: 0 Ai(4)-Gisa Zombies (upgraded): 0

Game Result: Game 1 ended in 31974 ms. Ai(1)-Giada precon has won!
```
- One `Game Outcome` line per player in seat order, one winner. `Match Result` is cumulative per seat. The header lists all players:
  `Ai(1)-... [Default] vs Ai(2)-... vs Ai(3)-... vs Ai(4)-... - three games of Commander seed 1`. run_sim.py parses all of this
  unchanged (its winner/deck mapping already handles more than 2 decks).
- **`Game Outcome: Turn N` is `ceil(total turns / 2)` for any player count** (GameLogFormatter.java), so in 4-player it is not rounds:
  C2 game 1 printed `Turn 18` for a 36-turn game. run_sim now also reports `turns` (section 5).
- **No elimination order is printed.** It can be derived from the full log: the first `Life: ... > N` line with N at or below 0 for each
  player, or the last `Turn: Turn N (<player>)` each player took (eliminated players stop taking turns). The two agreed in all 7
  games checked (C2 games 1-3, C7 games 1-4; for example C7 game 3: seat 2 out on turn 47, seat 3 on 75, seat 1 on 81, seat 4 won).
  A loss other than life total (commander damage, decking, poison) would need the last-turn method.
- Draws in multiplayer are reported like 2-player (`Game Result: Game N ended in a Draw!`); none happened.

### 3.7 Timeouts, crashes and hangs

- No crash or hang in any of the 63 Commander deck-vs-deck games (40 1v1, 23 4-player) or the 7 rules-test games (C3, C4, C5).
- **Timeout (C8: the C2 pod with `-c 10`, 3 games):** every game hit the clock (`Stopping slow match as draw`, after 10.0 s at turns 26-29).
  Forge then printed **all four** players as `has won because all opponents have lost`, and `Game Result` plus the cumulative `Match Result`
  credited seat 3 (Finneas) in all 3 games (`Match Result: ... Ai(3)-Finneas Rabbits: 3`). run_sim.py correctly reported 3 `timeout`
  results with `forge_reported_winner: 3`. After a timeout, seat 1 started the next game: every player counts as a winner, so no
  seat qualifies and Forge falls back to `players.get(0)`. The process carried on and exited normally. So the 2-player misreport
  in setup-notes applies to multiplayer too. Never trust Forge's winner without the timeout check.
- **Forge's per-decision AI time limit:** `Game.AI_TIMEOUT = 5` seconds (Game.java line 101). `AiController.chooseSpellAbilityToPlayFromList`
  (AiController.java around lines 1682-1718) runs the AI's spell choice in a separate "Game AI Eval" thread and waits
  `future.get(game.getAITimeout(), SECONDS)`. On timeout it prints the `java.util.concurrent.TimeoutException` stack trace plus
  `AI eval thread at timeout:` and a 30-frame stack, cancels the thread, and **returns null, so the AI plays nothing at that priority**.
  The source notes that on Java 20+ (so on our Java 26) `Thread.stop()` is gone, and a stuck eval thread "will keep running".
  Seen in 4-player only: 1 time in C7, 2 in C7b, 5 in C7c; 0 in all 1v1 and 60-card runs. The game continues normally, and run_sim's
  `exception_lines` counts these traces, but the games are still correctly recorded as wins.

### 3.8 Reproducibility of 4-player runs

C7, C7b and C7c used the same decks, seed 2 and Forge version. Comparing their full game logs (ignoring warnings, stack traces and durations):
- games 1 and 2 were identical line for line in all three runs (1143 and 1165 lines); neither had an AI timeout;
- game 3 had an AI timeout in every run and **diverged late**: at turn 78 (C7 vs C7b; the Giada Angels player played War Room in one and
  Plains in the other) and turn 67 (C7 vs C7c; token IDs 495 against 494, so an object was created in one run and not the other).
  From then on each run's games differed (C7 game 5: 91 turns, 143 s; C7b 58 turns, 41 s; C7c 69 turns, 97 s).
- This fits timing-dependent AI decisions: when the 5 s limit fires, the result depends on CPU speed and load, and the leftover eval
  thread may keep running. Where the timeout fired within game 3 could not be checked, because the stack trace goes to stdout while the
  game runs but the game log is printed afterwards. **Conclusion: seeded 1v1 runs reproduce exactly; seeded 4-player runs
  reproduce only until a decision takes more than 5 s.** Treat 4-player results as statistics, not replays.

## 4. Forge's AI never plays cards flagged `AI:RemoveDeck:All`

Found because Ghoulcaller Gisa was never cast: 0 `cast Ghoulcaller Gisa` lines in 52 deck-games (C1 10, C1r 10, C2 2 decks x 3,
C7 10, C7b 5, C7c 5, C8 2 decks x 3), although the Gisa decks had the mana (5-12 land drops in 9 of 10 C1 games; Gisa costs {3}{B}{B}).
Giada and Finneas were cast and recast normally.

- Gisa's card script (`res/cardsfolder/cardsfolder.zip`, `g/ghoulcaller_gisa.txt`) contains `AI:RemoveDeck:All`.
- `AiController.getSpellAbilityToPlay` (AiController.java lines 1565-1569) removes every spell or ability whose host card has that
  flag from the list the AI chooses from ("don't include removedAI cards if somehow the AI can play the ability"). So the AI never
  casts those cards and never activates their abilities.
- `RemoveDeck:Random` and `RemoveDeck:NonCommander` only affect random deck generation. A byte scan of the jar's classes finds
  `isCardRemRandomDeck` only in ComputerUtilCard and ChangeZoneAi (one narrow case: gaining control of cards from an opponent's
  library), and `isCardRemNonCommanderDeck` only in ComputerUtilCard.
- **Sim mode prints no warning.** `Match.prepareAllZones` collects the complaints (`complainCardsCantPlayWell`) and calls
  `GameAction.revealUnplayableByAI`, which only notifies the player controllers; none of our logs contains "AI can't play these cards well".
- The cards script folder has 2,500 scripts (of 34,010) flagged `RemoveDeck:All`. A scan of all 11 deck files (target and owned lists) and the
  product decks (script in section 7) finds 4 in our lists:

  | Card | Where | Effect on sims |
  |---|---|---|
  | **Ghoulcaller Gisa** | Commander of the Gisa precon and Gisa Zombies (target and owned) | Those decks play without their commander |
  | God-Eternal Bontu | Gisa precon, Gisa Zombies (target and owned), Mono-Black Midrange (owned list) | dead card |
  | Devout Decree | Mono-White Angels (target and owned) | dead card |
  | Beast Within | Finneas Rabbits (target and owned); Selesnya Rabbits sideboard | dead card (C6: never cast in 20 games) |

- For the plan: the deck page should list a deck's `RemoveDeck:All` cards next to any Forge result, since those results understate the
  deck. The Gisa decks' Forge results are unreliable. The check is a scan of `cardsfolder.zip` for `^AI:RemoveDeck:All`, matched on
  every face name (`Name:` lines).

## 5. Changes to run_sim.py (2026-09-29)

Made on a copy, checked, and swapped in atomically with `os.replace` only after confirming the live file's MD5 still matched the copy
(another agent had just added `--card-log`; their change is kept). New MD5 `85c3d9e1a4d91467342b772e3c3bb778`.

1. **Parser fix (output changes only where the old parser was wrong).** `RE_OUTCOME` understood only `has won/lost because ...`.
   Forge's outcome strings (res/languages/en-US.properties, `#PlayerOutcome.java` block) also include `has won due to effect of '<card>'`,
   `has lost trying to draw cards from empty library`, `has lost due to accumulation of 21 damage from generals`,
   `has lost due to effect of spell '<card>'` and `has conceded`. The old parser therefore:
   - gave decking and commander-damage losses no `loss_reason`;
   - **reported alternate wins as draws.** Tested with C5 (`cmdtest-felidar-main.dck`: Isamaru, Hound of Konda as commander, 30 Felidar
     Sovereign + 69 Plains vs the Emrakul lands deck, 2 games): Forge printed `has won due to effect of 'Felidar Sovereign'` and
     `Game Result: ... Ai(1)-Test Felidar main has won!`, but run_sim gave `result: draw, winner: null` in both games.
   The new regex matches the player name lazily and accepts `won|lost|conceded`, with or without `because`. Re-parsing all 44 logs
   in `logs/` and `logs/formats/` (779 games) with both versions gave identical results except in the intended places: 1 decking
   loss (A2), 5 commander-damage losses (C3, C4) with a reason, and the 2 C5 games changed from `draw` to `win`. Wins that are not
   "all opponents have lost" now also carry `win_reason`.
2. **`turns`** per game: the last `Turn: Turn N (<player>)` number (total turns; full log only), since `rounds` is `ceil(turns / 2)`
   whatever the player count.
3. **`--mem`** (opt-in, Windows only): peak working set, peak private bytes and CPU seconds of the java process (the same Win32 calls
   as measure_run.py: a handle kept until exit plus a 0.5 s sampler). Adds `mem` and `cpu_s` to the JSON.
4. Docstring updated for all of the above.

`loadmon.py` is new (section 0); no other script was changed.

## 6. What this means for the plan

- Step 5 passes: Beginner Box pairings (and single halves, and any deck size) run in sim mode with no options.
- Step 6 passes with caveats. 1v1 Commander is fast (about 2 s per game) and reproducible. 4-player pods work but take 40-70 s per
  game (a few over 3 minutes) and don't replay exactly, so a 4-player job should be sized in tens of games per process
  (100 games = about 2 hours of one process) and treated as statistics. Use a per-game clock well above the slowest game seen
  (216 s here). `-c 600` never fired; `-c 300` would have cut nothing either.
- Always rotate seat order in multiplayer batches, because seat 1 starts almost every game after game 1.
- Flag `AI:RemoveDeck:All` cards on the matchup page, or the Gisa decks will look worse than they are.
- Always parse outcomes with the timeout check. In multiplayer a timeout makes every surviving player "win".
- `-Xmx1024m` is enough for every format tested: peak working set 1.03-1.08 GB for 40-card, 60-card and 1v1 Commander runs,
  and 1.21-1.27 GB for 4-player.

## 7. Files

| Path | What |
|---|---|
| `formats.md` | this file |
| `decks/formats/*.dck` | all decks used here (section 0) |
| `logs/formats/<tag>.log`, `<tag>.json` | Forge output and run_sim summary for every run: A1, A2, A3, B1, B2, B3, C1, C1r, C2, C3, C4, C5, C6, C7, C7b, C7c, C8, G60 |
| `logs/formats/loadmon.csv` | CPU % and java.exe count every 2 s during all runs |
| `loadmon.py` | the load sampler |
| `run_sim.py` | parser fix, `turns`, `--mem` (section 5) |
| `forge-user-formats/` | Forge user folder for these runs (its own `forge.preferences` with lazy loading off, and Forge's log archive) |

Helper scripts used for the analysis (not kept in the repo folder; they live in the session scratchpad):
`castcheck.py` (which deck cards were cast or played at least once in a run's log) and the RemoveDeck scan (reads
`C:/Tools/forge/res/cardsfolder/cardsfolder.zip`, collects the `Name:` lines of scripts with `^AI:RemoveDeck:(\w+)`, and matches them
case- and accent-insensitively against the `.dck` files made with to_dck.py from every deck's target and owned lists and the product decks).
