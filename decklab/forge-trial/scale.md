# Forge trial: parallel processes and win-rate check (Milestone 0, steps 3 and 8)

Written 2026-09-29 on HomePC (Ryzen 9 9950X3D, 16 cores / 32 threads, 64 GB RAM, Windows 11 Pro 10.0.26200), Forge 2.0.15 at
`C:/Tools/forge`, JDK 26.0.1 (`C:/Program Files/Java/jdk-26.0.1/bin/java.exe`, called directly as in `setup-notes.md`).
Source quotes are from `https://github.com/Card-Forge/forge` at tag `forge-2.0.15` (commit `4ec5f1a2c32f`), read in the sparse
clone at `<scratchpad>/forge-src`. Paths are relative to this folder (`decklab/forge-trial/`, gitignored) unless they start
with `magic/`. No tracked repo file was changed.

## Summary

**Step 3, processes at once.**
- **Use 16 Forge processes**, one per physical core.
  - Throughput stops improving at 16: 539-575 games/min with 50-game batches, against 570 at 20 and 521 at 24.
  - 12 processes give about 90 % of that and leave about 4 cores for other work.
- **Settings:** `--lazy --jvm=-XX:+DisableExplicitGC`, `-Xmx1024m`.
  - Start-up is 5-7 s instead of 44 s at 16 processes.
  - Each process uses about 0.75 GB, about 9.5 GB in total.
  - Throughput is 28-37 % higher than Forge's defaults.
- **Batch size: 200 games per process** (at least 100).
  - Each process spends about 55 s (about 55 games' worth) on start-up and JIT compilation when 16 start together.
  - 50-game batches waste about half of the run.
  - Measured with 16 x 200-game batches on the six matchups: **790-905 games/min** for most decks, including start-up.
  - Rabbits vs Vampires ran at 230 games/min: its huge token boards make the AI's combat evaluation slow.
- **Determinism held under load.**
  - The same seed gave the same winners at 1, 16 and 24 processes, with lazy or eager loading, and with or without the card log.
  - Forge's AI has a 5 s limit per decision. It was hit in 0.3 % of Rabbits vs Vampires games (huge-board stalls only), and single-process replays of three of those games were identical move for move.

**Step 8, win rates vs the 2026-09-28 report** (3,200-6,400 games per matchup, 22,400 in all, balanced for play/draw):
- **Angels vs Zombies agrees:** 52.4 % Angels with the owned lists, 52.8 % with buys; the report says 51-53 %.
- **Izzet vs Gruul disagrees mildly:** Forge has Izzet at 55.1 % (owned) and 56.1 % (with buys); the report says 49-53 %.
  - About 1 point of that comes from Forge never casting Gruul's Fiery Annihilation (an AI bug found in the source and measured).
  - I believe "close, slight Izzet edge".
- **Rabbits vs Vampires disagrees strongly:** Forge has Rabbits at 38.1 % (owned) and 36.0 % (with buys); the report says 51-52 %.
  - Forge's AI holds Rabbits' team pumps (about half of the drawn copies of Overrun and Rabbit Response are still in hand when the game ends; `PumpAllAi` evaluates them one creature at a time).
  - It also attacks less with the aggro deck. A more aggressive AI profile gained 3.6 points.
  - What the report's simulator left out doesn't explain the gap: Rabbits made more double blocks than Vampires, and Vampires rarely cast removal on Rabbits' turn.
  - I trust the report more here (my estimate: Rabbits 45-51 %). Forge's number isn't usable for go-wide pump decks.


## Files

| File | What it is |
|---|---|
| `scale_run.py` | new: starts K Forge processes at once (same command as `run_sim.py`, which it imports read-only), timestamps every output line, samples system CPU and memory every second, writes `results/scale/<tag>.json` + `.timeline.csv` |
| `scale_table.py` | new: turns `results/scale/<tag>.json` files into the Markdown tables below |
| `run_matchup.py` | new: one matchup as parallel `run_sim.py` batches (distinct seed per batch, deck order swapped in every other batch), pooled into `results/matchups/<tag>/summary.json` |
| `matchup_table.py` | new: compares pooled matchups with the report's numbers (table in part B) |
| `cast_counts.py` | new: per-card cast counts from a matchup's plain Forge logs |
| `decks/compare/*.dck` | the 12 decks of part B (`to_dck.py --list owned|target --no-sideboard`), from the deck files at commit `3e6155d` |
| `results/scale/` | raw JSON + CPU/memory timelines of every scaling run |
| `results/matchups/<tag>/` | `batch-NNN.json` (run_sim's JSON, every game) and `summary.json` per matchup |
| `logs/scale/*.log.gz`, `logs/matchups/<tag>/` | raw Forge output of every process (the scaling logs gzipped afterwards, 388 MB -> 23 MB; the matchup logs are plain text because `cast_counts.py`, `attack_stats.py`, `ai_timeouts.py` and `parse_log.py` read them) |
| `forge-user-scale/`, `forge-user-scale-lazy/`, `forge-user-match/` | Forge user folders for these runs (the shared `forge-user/` and `%APPDATA%/Forge` were not used) |

## A. How many Forge processes at once (Milestone 0 step 3)

### A.1 Method

- `python scale_run.py --k K --games 50 --tag TAG [--lazy] [--jvm=...]`: K processes started within 0.1 s of each other (launch spread 0.01-0.10 s),
  each playing **Gruul Ramp (owned) vs Izzet Prowess (owned)** (`decks/gruul-ramp-owned.dck`, `decks/izzet-prowess-owned.dck`)
  with **the same seed (1)**, full game log (no `-q`, as part B needs), `-Xmx1024m`, `-c 120`, `-a Default Default`.
  Same seed = the same 50 games in every process (Forge replays seeded games exactly), so every process has exactly the work of the
  K=1 run and the per-game times are directly comparable; the winners double as a determinism check under load.
- Measured: start-up = launch -> the `Ai(1)-... vs ...` header; each game's finish time (timestamp of its `Game Result:` line);
  Forge's own `ended in N ms`; per process at exit: peak working set, peak private bytes, CPU seconds (Win32, the `run_sim.ProcStats`
  code); every second: system CPU busy (`GetSystemTimes`, 100 % = 32 logical CPUs), physical memory in use (`GlobalMemoryStatusEx`)
  and the sum of the K working sets.
- Throughput:
  - **steady g/min** = games finished while all K processes were playing (last header -> first process's last game) per minute:
    start-up excluded;
  - **incl g/min** = K x games / (launch -> last exit): start-up included, for the batch size used.
- **Background load.** The PC was in normal use: two other Claude Code sessions (about 1 core each; one ran a long recursive
  `grep -rl` during several runs), Firefox, VS Code, a compiler (`cl.exe`, `dotnet`). 3 s before each run the system CPU was
  6-26 % busy (one reading of 78 %, run `lz-deg-k1`, repeated as `lz-deg-k1b`), and 23.6-29.6 GB of the 63.6 GB RAM was free; no other
  `java.exe` was running before any run. So "proc cores" (each process's own CPU counters) is more reliable than the system CPU %.
  Run-to-run noise: two identical k=16 runs gave 539 and 575 g/min (7 %).
- A guard in `scale_run.py` kills the run if free RAM drops below 3 GB; it never triggered (peak in-use memory was 53.2 GB).

Columns: `start s` = start-up mean (max); `ms/game` = mean of Forge's per-game ms; `slow` = ms/game / the first row's;
`CPU %` = system CPU busy during the steady window; `bg %` = before the run; `proc cores` = the processes' CPU seconds / their
lifetimes (cores each process kept busy); `CPU s/game` = all CPU seconds (start-up included) / games; `WS MB/proc` = peak working
set per process, mean (max); `sum WS GB` = the largest sum of the K working sets at one moment; `same` = every process produced the
same 50 winners. (`scale_table.py` also prints a `cores/proc` column from system CPU minus background; it's noisy and not used here.)

### A.2 Forge's default settings (run_sim.py defaults: eager card loading, G1 GC with Forge's per-game `System.gc()`)

`python scale_run.py --k K --games 50 --tag def-kK`

| tag | K | start s | ms/game | slow | steady g/min | incl g/min | CPU % | bg % | proc cores | CPU s/game | WS MB/proc | sum WS GB | same |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| def-k1 | 1 | 9.5 (9.5) | 837 | 1.00 | 71 | 58 | 32 | 18 | 2.96 | 3.05 | 1052 (1052) | 1.0 | yes |
| def-k4 | 4 | 16.0 (16.2) | 1030 | 1.23 | 232 | 176 | 60 | 21 | 2.67 | 3.62 | 1033 (1040) | 3.6 | yes |
| def-k8 | 8 | 23.5 (24.0) | 1411 | 1.69 | 335 | 251 | 82 | 14 | 2.16 | 4.08 | 1024 (1030) | 7.5 | yes |
| def-k12 | 12 | 33.6 (34.3) | 1797 | 2.15 | 394 | 287 | 92 | 19 | 1.75 | 4.34 | 1011 (1022) | 10.6 | yes |
| def-k16 | 16 | 43.6 (44.5) | 2259 | 2.70 | 420 | 303 | 96 | 17 | 1.47 | 4.60 | 1006 (1016) | 14.0 | yes |

- The CPU is saturated at 16 (96 %); 12 -> 16 added only 7 %. **k=24 was not run with these settings**: it would need about
  24 GB with 24-29 GB free (the user's other programs), and the tuned settings below, which use less CPU per process, already got
  no faster from 16 to 24.
- Eager start-up gets much slower with K (9.5 s -> 44 s): every process parses all 33,980 card scripts (about 18 CPU-seconds each).
  During that phase the CPU was only 63-74 % busy at K=16 (timeline), so it is partly limited by something other than CPU.

### A.3 Tuned settings: lazy card loading + `-XX:+DisableExplicitGC`

`python scale_run.py --k K --games 50 --tag lz-deg-kK --lazy --jvm=-XX:+DisableExplicitGC`

| tag | K | start s | ms/game | slow | steady g/min | incl g/min | CPU % | bg % | proc cores | CPU s/game | WS MB/proc | sum WS GB | same |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lz-deg-k1b | 1 | 1.3 (1.3) | 687 | 1.00 | 87 | 84 | 22 | 10 | 2.27 | 1.63 | 742 (742) | 0.7 | yes |
| lz-deg-k1 (busy PC) | 1 | 2.1 (2.1) | 771 | 1.12 | 78 | 74 | 52 | 78 | 2.38 | 1.95 | 704 (704) | 0.7 | yes |
| lz-deg-k4 | 4 | 1.7 (1.7) | 868 | 1.26 | 275 | 264 | 44 | 10 | 2.24 | 2.03 | 776 (852) | 2.8 | yes |
| lz-deg-k8 | 8 | 3.2 (3.6) | 1092 | 1.59 | 435 | 408 | 72 | 20 | 1.99 | 2.31 | 716 (841) | 4.9 | yes |
| lz-deg-k12 | 12 | 4.1 (4.9) | 1425 | 2.07 | 500 | 471 | 85 | 11 | 1.77 | 2.68 | 716 (818) | 7.2 | yes |
| lz-deg-k16 | 16 | 5.7 (6.8) | 1772 | 2.58 | 539 | 503 | 95 | 15 | 1.51 | 2.85 | 699 (810) | 9.4 | yes |
| lz-deg-k16b (repeat) | 16 | 5.3 (6.3) | 1658 | 2.41 | 575 | 538 | 90 | 9 | 1.59 | 2.82 | 702 (805) | 9.3 | yes |
| lz-deg-k20 | 20 | 6.5 (8.2) | 2074 | 3.02 | 570 | 534 | 97 | 8 | 1.37 | 3.02 | 668 (768) | 11.6 | yes |
| lz-deg-k24 | 24 | 8.5 (10.7) | 2736 | 3.98 | 521 | 489 | 100 | 16 | 1.06 | 3.10 | 696 (791) | 13.6 | yes |

- **Throughput stops improving at 16 processes** (539-575 g/min; 20: 570; 24: 521) and the CPU is saturated from 16 on.
  16 is the number of physical cores: each process's game runs on one thread at a time, and a second thread on the same core (SMT)
  adds little.
- Compared with the defaults, the tuned settings give **28-37 % more games per minute at K=16** (539-575 vs 420 steady; 503-538
  vs 303 including start-up), start-up 5-7 s instead of 44 s, and 0.7 GB instead of 1.0 GB per process.
- **Quiet mode costs nothing measurable**: `lz-deg-k16-q` (`--quiet`, Forge `-q`) 559 g/min vs 539/575 with the full log.
- **Serial GC** (`--jvm=-XX:+UseSerialGC --jvm=-XX:+DisableExplicitGC`, tags `lz-ser-kK`): k=1 776 ms/game, k=8 382, k=16 519,
  k=24 551 g/min steady; within the run-to-run noise of G1. Not worth changing.

### A.4 Batch size: JIT warm-up matters more than start-up

`--games 150` runs (tags `lz-deg-k1-n150`, `lz-deg-k16-n150`, `lz-deg-k24-n150`, tuned settings, seed 1 in every process):

| tag | K | start s | ms/game | steady g/min | incl g/min | CPU % | proc cores | CPU s/game | WS MB/proc | sum WS GB | same |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lz-deg-k1-n150 | 1 | 1.2 | 554 | 108 | 106 | 12 | 1.64 | 0.93 | 908 | 0.9 | yes |
| lz-deg-k16-n150 | 16 | 6.7 (7.3) | 1338 | 710 | 685 | 82 | 1.30 | 1.80 | 761 (833) | 9.6 | yes |
| lz-deg-k24-n150 | 24 | 8.2 (10.2) | 1963 | 727 | 706 | 98 | 1.10 | 2.23 | 756 (803) | 14.5 | yes |

Per-game time by position in the batch (the same 150 games at every K, so the ratio to K=1 is pure contention):

| games | K=1 ms | K=16 ms | K=16 / K=1 | K=16 rate (g/min) | K=24 / K=1 | K=24 rate |
|---|---|---|---|---|---|---|
| 1-10 | 731 | 3693 | 5.05 | 260 | 6.42 | 307 |
| 11-25 | 613 | 1595 | 2.60 | 602 | 3.47 | 677 |
| 26-50 | 608 | 1355 | 2.23 | 709 | 3.28 | 722 |
| 51-100 | 543 | 1112 | 2.05 | 863 | 3.16 | 840 |
| 101-150 | 485 | 1006 | 2.08 | 954 | 3.30 | 900 |

- **The first 25-50 games of every process are slow when many processes start together.** Each JVM spends that time compiling
  Forge's code (a `jcmd <pid> Thread.print` of a single process 35 s in showed the C2 compiler thread with 13.5 s of CPU, more than
  any other live thread; `results/scale/threads-probe.jcmd.txt`), and 16 JVMs compiling at once saturate the CPU. Once warm, K=16
  runs about **900-950 games/min at 63-83 % CPU** (timeline, system-wide, including 6-26 % from other programs), and each game takes about 2x as long as with one process.
- A 50-game batch therefore averages only about 500-575 g/min at K=16, while 150-game batches averaged 685 including start-up.
  Fitting `time(n) = overhead + n x warm time` to the K=16 run gives an overhead of about **55 s per process (about 55 warm games)**.
  Estimated throughput at K=16 by batch size: 50 games 470 g/min, 100 about 610, 150 about 690 (measured 685), 200 about 740,
  300 about 800, 500 about 855 (the last three extrapolated; games 101-150 of seed 1 are shorter than average, so these are a little
  optimistic).
- K=24 with long batches is no better than K=16 (706 vs 685 including start-up; 864 vs 901 g/min once warm).

### A.5 Where the CPU goes (source, `forge-ai` at tag forge-2.0.15)

- `AiController` (line 1682) evaluates each spell choice in a **new thread** (`new Thread(future, "Game AI Eval")`) and waits for it
  with `future.get(game.getAITimeout(), TimeUnit.SECONDS)`; `Game.AI_TIMEOUT = 5` (sim mode never changes it; only `HostedMatch`
  copies the `MATCH_AI_TIMEOUT` preference, default 5). **If a decision takes more than 5 s the AI plays nothing at that priority**,
  and Forge prints `AI eval thread at timeout:` plus a stack trace.
- `AiAttackController` (line 883) creates a `newFixedThreadPool(availableProcessors())` for every attack declaration
  (the `pool-1649-thread-1` threads in the jcmd dump).
- So results could in principle depend on machine load. **They didn't here:** all 22 scaling runs (249 processes, 16,550 games, up to 24
  processes at once, games up to 6x slower, every setting above) produced the same winner sequence as the single-process run with the
  same seed (all 50-game runs identical; the three 150-game runs identical, and their first 50 games identical to the 50-game runs), and none
  of the 250 scaling logs contains `AI eval thread at timeout` or `Exception`. Part B found the timeout in huge-board games (B.4).
  Deck Lab should count that line (and keep K at or below 16).

### A.6 Memory

- Tuned settings: **about 0.7-0.8 GB working set per process** (peak 0.67-0.91 GB; private bytes about 0.8 GB), whatever K is.
  Default settings: about 1.0 GB (peak follows `-Xmx1024m`).
- **Total at K=16: about 9.5 GB** (largest simultaneous sum of working sets 9.3-9.6 GB tuned, 14.0 GB default); at K=24 13.6-14.5 GB.
  Physical memory in use never went above 53.2 of 63.6 GB, with the user's other programs taking 34-40 GB.

### A.7 Recommendation

- **Workers: 16** Forge processes (= physical cores). More gives nothing (20: same, 24: 3-10 % less) and 12 gives about 90 % of the
  throughput while leaving about 4 cores for the PC's other work; use 12 when the PC is in use and 16 for overnight runs.
- **JVM settings: `--lazy --jvm=-XX:+DisableExplicitGC`, `-Xmx1024m`** (run_sim's default heap). Lazy loading turns a 44 s
  start-up at K=16 into 5-7 s and saves 0.3 GB per process; both options gave identical games in every test.
- **Batch size: 200 games per process** (at least 100). The fixed cost per process under full load is about 55 s (start-up plus JIT
  warm-up), about 55 games' worth, so 50-game batches waste about half the time and 200-game batches about a fifth. For a job
  smaller than 16 x 100 games, use fewer workers rather than smaller batches: roughly `workers = min(16, games / 100)`.
  (Plan section 6's "each process plays many games" is right, and "many" means hundreds, not dozens.)
- Speed: this model predicts about 740 games/min for 16 x 200-game batches. **Part B measured 790-905 games/min** on four real matchups
  (different decks and seeds), and **about 230 games/min** on the board-heavy Rabbits vs Vampires pair (B.5). A 400-game matchup as
  4 x 100 should take about 1.5 min (estimate, not measured).
- **Before starting parallel workers on a new Forge user folder, run one Forge process first** (or create its folders): 16 processes
  starting on a fresh folder raced and one crashed (B.6). For slow (board-heavy) matchups, use batches of about 100 so the last
  batches don't leave most workers idle.
- Possible later speed-up, not tested: JDK 26 supports an AOT cache (`-XX:AOTCacheOutput=` in a training run, then `-XX:AOTCache=`;
  flags present in `java -XX:+PrintFlagsFinal`), which stores loaded classes and method profiles and could shorten the warm-up.

## B. Forge vs the 2026-09-28 report (Milestone 0 step 8)

### B.1 Method

- **Decks:** `decks/compare/<slug>-owned.dck` and `<slug>-target.dck` for the six paired decks, made with
  `python to_dck.py magic/decks/casual/<slug>.md --list owned|target --no-sideboard -o ...` from the deck files at commit `3e6155d`
  (clean; each `summary.json` records the commit and a SHA-256 of each `.dck`). Main decks only (60 cards each), because sim mode never
  sideboards and the report's numbers are main deck vs main deck. The Gruul and Izzet owned lists are identical to the trial decks.
- **Report numbers** (deck A's win %): section 1 table of `magic/reports/2026-09-28-best-decks.md` and the "Head-to-head ... (tested)"
  table in each deck file (original simulator / re-checked simulator rows). Their simulators alternated who went first, so the Forge
  figure compared with them is the **play/draw-balanced** win rate (mean of A's win rate on the play and on the draw). Forge lets the
  previous game's loser start (setup-notes section 4), so starts are not balanced within a batch. "Agrees" = the report's range
  overlaps Forge's 95 % interval.
- **Runs:** `results/matchups/run_all.sh`, i.e. for each pair
  `python run_matchup.py --a decks/compare/A.dck --b decks/compare/B.dck --src-a ... --src-b ... --games G --batch 200 --workers 16 --seed-base S --tag T --lazy --jvm=-XX:+DisableExplicitGC`
  (the settings recommended in A.7). Each 200-game batch is one `run_sim.py` process with its own seed (S, S+1, ...); even batches play
  A vs B, odd batches B vs A; full game logs (so the starting player is known for every game); `-c 120`; AI profile Default for both;
  Forge user folder `forge-user-match/` (lazy loading). 3,200 games per matchup (16 batches), 6,400 for Izzet vs Gruul owned (32 batches).
  Seeds: Angels/Zombies owned 110000-110015, with buys 120000-120015; Izzet/Gruul owned 210000-210031, with buys 220000-220015;
  Rabbits/Vampires owned 310000-310015, with buys 320000-320015. Run 2026-09-29 14:25-15:13.
- Wins exclude draws and timeouts (counted as non-wins for both decks). 95 % intervals are Wilson for the raw rate and normal
  (from the two halves) for the balanced rate. Tables: `python matchup_table.py <tags>` (JSON: `results/matchups/comparison.json`).

### B.2 Results

| Matchup (A vs B) | Games | A-B wins | Draws / timeouts | A win % (Wilson 95 %) | A balanced % (95 %) | Report, A win % | Agrees |
|---|---|---|---|---|---|---|---|
| Angels vs Zombies, owned | 3,200 | 1670-1530 | 0 / 0 | 52.2 (50.5-53.9) | 52.4 (50.7-54.1) | 51-53 (table); original 50-52, re-checked 52-54 | yes |
| Angels vs Zombies, with buys | 3,200 | 1681-1519 | 0 / 0 | 52.5 (50.8-54.3) | 52.8 (51.0-54.5) | 51 (table); original 51, re-checked 51-52 | yes |
| Izzet vs Gruul, owned | 6,400 | 3509-2891 | 0 / 0 | 54.8 (53.6-56.0) | 55.1 (53.9-56.3) | 49-51 (table); original 51-53, re-checked 51 (49 beginner Izzet) | **no** (+2 to +6) |
| Izzet vs Gruul, with buys | 3,200 | 1782-1418 | 0 / 0 | 55.7 (54.0-57.4) | 56.1 (54.4-57.8) | 49-51 (table); original 51-53, re-checked 51 | **no** (+3 to +7) |
| Rabbits vs Vampires, owned | 3,200 | 1241-1952 | 0 / 7 | 38.8 (37.1-40.5) | 38.1 (36.4-39.9) | 51 (table); original 50-51, re-checked 52 | **no** (-10 to -15) |
| Rabbits vs Vampires, with buys | 3,200 | 1171-2021 | 0 / 8 | 36.6 (34.9-38.3) | 36.0 (34.3-37.7) | 51-52 (table); original 51, re-checked 51-52 | **no** (-13 to -17) |

On the play vs on the draw (each deck's own win %; "starter" = the player who went first):

| Matchup | A on the play | A on the draw | B on the play | B on the draw | Starter wins | Report |
|---|---|---|---|---|---|---|
| Angels vs Zombies, owned | 57.3 (878/1533) | 47.5 (792/1667) | 52.5 (875/1667) | 42.7 (655/1533) | 54.8 % | starter about 52 % (Angels 53 % of their starts, Zombies 51 %) |
| Angels vs Zombies, with buys | 57.2 (869/1518) | 48.3 (812/1682) | 51.7 (870/1682) | 42.8 (649/1518) | 54.3 % | same |
| Izzet vs Gruul, owned | 57.7 (1672/2896) | 52.4 (1837/3504) | 47.6 (1667/3504) | 42.3 (1224/2896) | 52.2 % | Izzet 55 % on the play, 47 % on the draw |
| Izzet vs Gruul, with buys | 59.8 (848/1418) | 52.4 (934/1782) | 47.6 (848/1782) | 40.2 (570/1418) | 53.0 % | same |
| Rabbits vs Vampires, owned | 41.1 (802/1952) | 35.2 (439/1248) | 64.6 (806/1248) | 58.7 (1146/1952) | 50.2 % | starter 53-54 % |
| Rabbits vs Vampires, with buys | 38.3 (774/2021) | 33.7 (397/1179) | 65.9 (777/1179) | 61.6 (1244/2021) | 48.5 % | same |

- Deck order didn't matter: A's win rate as deck 1 vs deck 2 differed by 0.0-1.4 points in every matchup (`a_as_deck1` / `a_as_deck2`).
- Mean game length 8.2-9.5 rounds. Timeouts: only the Rabbits pair (7 and 8 games of 3,200 hit the 120 s clock under load; B.4).

### B.3 Why Forge and the report disagree

**Angels vs Zombies: they agree** (52-53 % Angels in both). Forge's Angels never cast Devout Decree (0 casts in 6,400 games,
`cast_counts.py`; the `AI:RemoveDeck:All` flag from `card-audit.md`), so Forge's Angels play with 59 live cards and still match the report.

**Izzet vs Gruul: Forge has Izzet 3-5 points better than the report.**
- *Fiery Annihilation is a blank card for the AI* (0 casts in 9,600 games; 94 of 94 drawn copies still in hand at the end of the
  400 card-log games). Source: its script ends with `SubAbility$ DBChangeZone`, "exile up to one target Equipment attached to that creature"
  (`ValidTgts$ Equipment.AttachedTo ParentTarget | TargetMin$ 0`). The AI checks every sub-ability before casting
  (`SpellAbilityAi.chkDrawbackWithSubs`, line 269) -> `ChangeZoneAi.knownOriginPlayDrawbackAI` (line 851) -> `isPreferredTarget`, which
  returns false when there is nothing to target (line 1145, `if (list.isEmpty() && !doWithoutTarget) return false;`; `doWithoutTarget` is only
  for planeswalker abilities). There is never an Equipment on the battlefield in these decks, so the whole spell is always rejected.
  **Measured effect (run E1):** the same 3,200 games (seeds 210000-210015) with a user-folder copy of the script minus that sub-ability
  (`forge-user-fa/Forge/custom/cards/fiery_annihilation.txt`; the card was then cast in 695 of 3,200 games): Izzet 53.5 % (51.7-55.2), balanced
  53.8 % (52.1-55.5), against 54.6 % / 55.0 % on the same 16 seeds without it: **about 1 point** (-1.1 +/- 2.4). The same seeds replay
  identically only until the card first matters (game 4-10 of each batch), so this is effectively an unpaired comparison. That matches
  the report's own estimate for this card (Fiery Annihilation -> Beast-Kin Ranger is worth 0.3-0.7 points). One E1 batch failed on a first-run
  race and was rerun with `--only 10` (B.6).
- *Gruul's top end is mostly stuck in hand* (card-log replay of batches 0-1, 400 games, `run_matchup.py ... --card-log`, then
  `parse_log.py`; `results/matchups/izzet-gruul-owned-cardlog/card_stats.json`): Savage Ventmaw 68 %, Pelakka Wurm 66 %, Lathliss 63 %,
  Rampaging Baloths 60 %, Terror of Mount Velus 58 %, Quakestrider Ceratops 48 % of drawn copies were still in hand when the game ended; games
  last 8.6 rounds. Gruul's lands and mana creatures are used normally (Llanowar Elves 91 %, lands 96-100 %).
- *The report's mechanism shows up in Forge too:* when Gruul's turn-1/2 mana creature (Llanowar Elves, Druid of the Cowl) survived to Gruul's
  next turn, Gruul won 58.5 % (1,494 games); when it was killed, 42.2 % (1,308); with no early mana creature, 40.7 % (3,598 games, 56 %).
- *Play/draw:* Forge's Izzet is much better on the draw than the report's (52.4 % vs 47 %); on the play it is 57.7-59.8 % vs 55 %.
- **What I believe:** "close, with a small Izzet edge". Fiery Annihilation explains about 1 of the 3-5 points. The rest can't be pinned
  on a single Forge bug. It is the kind of gap two different AIs produce: Forge's AI plays burn-and-fly decks well, as the plan's caveat
  says, and the report notes that Izzet's result depends most on how well it's played. Neither number is precise to 3 points for two
  beginners. If Izzet wins clearly in real games, the report's lever (Gruul's Wildheart Invoker -> Obliterating Bolt, -2 to -3 for Izzet)
  is the right size.

**Rabbits vs Vampires: Forge has Rabbits 12-15 points worse. I trust the report more for this pair.**
Forge's AI can't play Rabbits' plan:
- *It holds the team pumps.* Card-log replay of batches 0-1 (400 games; `results/matchups/rabbits-vampires-owned-cardlog/card_stats.json`):
  **Rabbit Response was used for 46 % of drawn copies (53 % still in hand at the end), Overrun 44 % (52 % in hand)**, Byrke 52 %, while every other
  Rabbits spell was used 75-98 % of the time. Over all 3,200 games Overrun was cast in 10 % of games and Rabbit Response in 22 %. When
  Overrun was cast, Rabbits won 70 %. Source: `PumpAllAi.checkApiLogic` (line 132) casts a team-wide pump only if pumping *some single creature*
  passes the single-creature test (`ComputerUtilCard.shouldPumpCard`). It never adds up the extra damage across a wide board, which is
  exactly the alpha strike this deck is built for.
- *It attacks less with the aggro deck* (`attack_stats.py`): Rabbits attacked on 38.8 % of their own turns, Vampires on 48.9 %.
  **Run E2:** Rabbits on Forge's `Reckless` profile (`PLAY_AGGRO=true`, always attacks into trades; `res/ai/Reckless.ai`), Vampires on
  Default, 1,600 games (seeds 330000-330015, batches of 100): Rabbits attacked on 49.4 % of turns and won **42.4 % (40.0-44.8)**, +3.6 points.
  Team pumps were still held (Overrun cast in 11 % of games).
- *AI decision timeouts* (B.4) affected 0.3 % of Rabbits games and didn't change them.
- Vampires' engine is easy for the AI: Ajani's Pridemate (win rate +21 points when drawn) and Hinterland Sanctifier (+18) are cast
  in about 70 % of games.

The report's simulator left out two things that Forge plays, and neither explains the gap:
- **Double blocks** (the report: "no double blocks ... which understates Rabbits"). In Forge, Rabbits made more of them: 18.9 % of the
  9,410 attackers Rabbits blocked got 2+ blockers, against 12.1 % of the 5,654 attackers Vampires blocked (with buys: 18.6 % vs 8.6 %).
  Counted from every `assigned ... to block` line, including the continuation lines of a multi-line `Combat:` entry, with blockers counted
  by their card ids. So Forge plays the thing the report said it was missing in Rabbits' favour, and Rabbits still lose.
- **Instant-speed removal for Vampires** hardly matters in Forge: only 4 % of Vampires' 5,734 removal spells were cast on Rabbits' turn,
  0.4 % after attackers were declared.

So most of the gap looks like Forge's AI failing at go-wide pump turns. The AI-style change alone (E2) recovered 3.6 of the 12-13 points,
and it didn't fix the held pumps, whose cost can't be measured without a better AI. **My estimate: Rabbits somewhere between 45 % and 51 %,
i.e. roughly even to slightly Vampires-favoured, not 38 %.** This is a judgement, not a measurement. Log real games; if Vampires wins clearly, the report's lever (Rabbits' Rabid Bite -> Swords to Plowshares from the
sideboard, about +3) is the first step. **Don't trust Forge's number for go-wide pump decks** (Deck Lab should flag decks whose plan is mass pumps).

### B.4 Load, seeds and loading mode don't change results

- **Card-log replays** (run E3, 4 workers instead of 16, `DeckLabSim` via `run_sim.py --card-log`, same seeds and orders): all 800 games of
  batches 0-1 of Rabbits/Vampires owned and Izzet/Gruul owned had the **same winners** as the main runs.
- **AI eval timeouts:** in the Rabbits pair, 11 of 3,200 games (owned) and 11 of 3,200 (with buys) printed `AI eval thread at timeout`
  (56 and 58 times), all in huge-board stalls of 49-120 s (`ai_timeouts.py`); 7 and 8 games hit the 120 s clock (`Stopping slow match as draw`,
  counted as timeouts). No other matchup had any. **Single-process replays** of three affected games (`results/matchups/run_replays.sh`:
  seed 320009 games 1-7, seed 310013 games 1-53, seed 310015 games 1-48; about 2x faster than under load) had 0, 2 and 0 timeouts instead
  of 4, 2 and 1, and **all 108 games had the same winners; the three affected games were identical move for move** (all 321-355 action lines).
- **Eager vs lazy card loading:** Angels/Zombies owned seed 110000, 100 games, eager loading, one process
  (`results/replays/azo-s110000-n100-eager.json`): the same 100 winners as the lazy 16-process batch.
- So in every check so far, Forge's results depend only on decks, seed and Forge version. Keep watching for `AI eval thread at timeout`
  (Deck Lab should count it per job), and for the per-game clock in slow matchups.

### B.5 Speed of the real runs

16 workers x 200-game batches, lazy + DisableExplicitGC (from `summary.json`: `wall_s`, `games_per_min_incl_startup`, `startup_s`):

| Matchup | Games | Wall | Games/min (start-up incl.) | Start-up mean (max) | ms/game mean (max) |
|---|---|---|---|---|---|
| Izzet vs Gruul, owned | 6,400 | 8 min 6 s | 789 | 4.2 s (7.1) | 1,170 (15,803) |
| Angels vs Zombies, owned | 3,200 | 3 min 57 s | 811 | 5.8 s (6.8) | 1,108 (11,366) |
| Izzet vs Gruul, with buys | 3,200 | 3 min 32 s | 905 | 6.0 s (6.4) | 1,004 (9,632) |
| Angels vs Zombies, with buys | 3,200 | 3 min 43 s | 860 | 6.0 s (6.8) | 1,054 (15,165) |
| Rabbits vs Vampires, owned | 3,200 | 13 min 58 s | 229 | 6.3 s (7.3) | 3,353 (120,003) |
| Rabbits vs Vampires, with buys | 3,200 | 13 min 56 s | 230 | 7.1 s (7.8) | 3,411 (120,002) |

- Most matchups ran at **790-905 games/min**, better than the 740 estimated in A.4 (different decks and seeds, and games 1-50 of seed 1 are long).
- **Board-heavy matchups are 3-4x slower** (Rabbits' tokens: combat evaluation grows with the number of creatures), and their batches
  finished unevenly (524-831 s), so the last minutes ran on fewer workers. The queue should use smaller batches (100) for such decks, or
  hand out work in smaller chunks near the end.
- A 400-game request therefore takes well under a minute for most pairs and about 2 minutes for Rabbits vs Vampires, and the 6,400-game
  check took 8 minutes: **a few hundred games finish in minutes, not hours** (the plan's go/no-go test).

### B.6 Problems found (for Deck Lab)

1. **First-run race in a new Forge user folder:** in E1 one of 16 processes started at once failed with
   `java.lang.RuntimeException: cannot create profile directory: ...\forge-user-fa\Forge\gauntlet\` (exit code 1, 0 games;
   `logs/matchups/izzet-gruul-owned-fa/b010-s210010-failed.log`). Forge creates its profile folders on start-up and fails if another process
   creates one first. Fix: start one Forge process (or create the folders) before starting parallel workers, and retry a batch that exits
   with 0 games. `run_matchup.py --only` reruns chosen batches.
2. **Forge's AI has a 5 s limit per decision** (`Game.AI_TIMEOUT`, A.5) and a 120 s per-game clock (`-c`); both are hit only in huge-board
   games. Count `AI eval thread at timeout` and timeouts per job and show them.
3. **Cards the AI never casts even without an `AI:RemoveDeck` flag** (Fiery Annihilation: an optional "up to one target" sub-ability
   with no legal target vetoes the spell). `card_audit.py` could look for `SubAbility` chains with `TargetMin$ 0` targets that are usually
   absent; the card-log "used %" column finds them empirically (0 % used).
4. **Team pumps (`PumpAll`) are under-used**, so go-wide decks are rated too low (B.3).
5. Deck order within a batch doesn't matter, but **who starts does** (the starter won 48.5-54.8 %). Report the balanced win rate.

### B.7 Files for part B

| Path | What |
|---|---|
| `results/matchups/<tag>/summary.json`, `batch-NNN.json` | tags `angels-zombies-{owned,target}`, `izzet-gruul-{owned,target}`, `rabbits-vampires-{owned,target}` (main runs); `izzet-gruul-owned-fa` (E1; `summary-first-pass.json` and `batch-010-failed.json` are from before the rerun), `rabbits-vampires-owned-reckless` (E2), `*-cardlog` (E3, with `card_stats.json` and `events.jsonl`) |
| `results/matchups/<tag>/cast_counts.json` | per-card cast counts (`cast_counts.py`) |
| `results/matchups/comparison.json`, `comparison-diagnostics.json` | the tables above (`matchup_table.py`) |
| `results/matchups/run_all.sh`, `run_diag.sh`, `run_replays.sh` | the exact commands; `progress*.txt` hold their start and end times |
| `results/replays/` | single-process replays (B.4) |
| `ai_timeouts.py`, `attack_stats.py` | AI-timeout and attack counts per matchup |
| `forge-user-fa/Forge/custom/cards/fiery_annihilation.txt` | the E1 script override |
