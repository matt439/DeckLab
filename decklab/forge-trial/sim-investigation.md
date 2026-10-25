# Deck Lab simulations: final report on speed, accuracy and what to change

**Date:** 2026-10-03.
**Status:** final. It applies the skeptic checks (`v-r01` to `v-r10`) and the completeness critique (`c1`) to the
phase-1 work. The raw data, scripts and prototypes are in `sim-investigation/` beside this file (gitignored, so
they stay on this PC).

**Where things stand (2026-10-04): all three waves are built, measured and merged to main.** `decklab/HISTORY.md`'s
"Simulation speed and accuracy" wave 1, 2 and 3 entries have the details and every number; the wave 1 and wave 2
notes below are as written on 2026-10-03, and the rest of this report still describes the code before wave 1.
- **Built:** wave 1 (R02, R01a, R03, R19, R04, R11 items 1-3, R18); wave 2 (R05, R01b, the v2 engine with R06,
  R09, R08 and R14b, R14a, R11 item 4, `replay`); wave 3 (R12, R13, R15, R10, R16's pilots and experiment harness,
  and the overnight harness). R17 wasn't built: it waits for Forge 2.0.16 (`sim-wave3-contract.md` §13).
- **Measured:** waves 2 and 3 together, in one unattended run on the night of 3-4 October
  (`sim-combined-run.md`). The first run's verdict was FAIL on MG11 (drift) alone: three of its five drift probes
  timed workers the pool had just started. The probe was fixed, and a targeted re-check passed MG11 (medians
  347-386.5 ms a game). Every other merge gate passed on the first run.
- **Key results** (the run's REPORT.md files, in `C:/VSProjects/TCC-wt/w3-run/decklab/data/forge/overnight/`
  `2026-10-03/` and `2026-10-04-recheck/`):
  - **Speed:** warm, 16 workers: 1,426.3 games a minute on Izzet v Gruul, 157.3 on Rabbits v Vampires and 232.6 on
    Giada v Finneas (Commander): 1.93x, 1.17x and 3.39x wave 1's cold batches. A fresh pool is 1.41x on Izzet v
    Gruul.
  - **Correctness:** warm workers played the same games as fresh processes (490 Constructed games probed over 3.23
    h, 0 failed, 0 unsure); 27,998 of 28,000 games identical across timing legs (the other 2 had a clock stop or
    AI timeout); in the replay of 22 matchups (26,094 games), no matchup's old and new 95 % ranges excluded 50 % on
    opposite sides.
  - **The new tools:** pairing a variant with its base saved 72-92 % of the games an unpaired test needs (G6, G7);
    an adaptive field run of Mono-White Angels matched a 1,600-game reference (Spearman 0.967; G8); ladders of
    removed key cards cost Izzet, Angels and Mono-Black Midrange 10-14 points at 6 copies, while Rabbits' and
    Gruul's didn't settle at 400 games a rung (G2); deck rankings held under every experiment override set
    (Spearman 0.988, no flips; G3).
  - **AI fixes (G4, G5):** the `remove` override set (Devout Decree, Beast Within) gained +2.4 points (+1.1 to
    +3.7) and was adopted on 2026-10-04; the team-pump fix (+4.1 for Rabbits against Vampires), the AI-profile arms
    and the other override sets want more games.
  - **Outside Forge (M7, G2):** against published human Pauper matchups, Spearman 0.64 over 7 decks: too few human
    matches to confirm or rule out Forge's rankings.
- **Still open:** G13 (EcoQoS under `pythonw.exe`: the harness didn't check it), G14 and G9 (the pinning and
  worker-count legs mixed warm-up with what they changed, so the defaults stay), and the run's recount of the
  turn-3 numbers from its logs (not built in the harness yet). The next step is a session of more experiment games
  on an idle PC (PLAN.md's Later list).

**How it was built**
- Phase 1 produced four sets of idle-gated measurements (`e1` to `e4`), six research notes (`r1` to `r6`) and a
  synthesis (`s1`).
- The phase-1 draft of this report was never saved (critique G1). It was rebuilt from `s1-synthesis/notes.md`
  and the phase notes, then corrected.
- The finalisation pass (`f1-final/`) ran no Forge. It added two read-only checks on saved logs, documented in
  `f1-final/notes.md`.

**Labels used throughout**
- **Measured:** from an idle-gated run, with the run named.
- **Derived:** computed from measured data, for example per-game timestamps.
- **Estimate:** reasoning or a model, not measured.

**Ground rules kept**
- No tracked repo file was edited and nothing was committed.
- `decklab/data/forge/results` was only read.
- The Deck Lab server stayed stopped.

**Setup**
- **PC:** Ryzen 9 9950X3D, 16 cores / 32 threads.
  - CCD0 = logical CPUs 0-15, with 96 MB of 3D V-Cache.
  - CCD1 = logical CPUs 16-31, with 32 MB.
- **Software:** Forge 2.0.15 on JDK 26.0.1, run through DeckLabSim with the card log.
- **Repo:** HEAD `40f683a`.

**Wave 1 status (2026-10-03): built and measured.** The rest of this report is unchanged and still describes the
code as it was before wave 1.
- **Built:** R02 + R01a (batch plan, `-XX:ActiveProcessorCount=2`), R03 + R19 (lead verdicts, starter tile, trust
  labels), R04 (the mulligan sleep, removed through a copy of Forge's class in the card-log jar), R11 items 1-3
  (per-card pooling by matchup, shrinkage, Benjamini-Hochberg, "early" below 800 games) and R18 (machine-wide slots,
  BELOW_NORMAL). R14a is a prototype only. No game changed for a given seed, so there was no key or
  `FORGE_RUN_VERSION` change. `decklab/HISTORY.md`'s "Simulation speed and accuracy, wave 1" has the details.
- **Measured (M1, Izzet v Gruul, Deck Lab's real seeds, two runs each):**

  | Games | Before | After | Speed-up |
  |---|---|---|---|
  | 200 | 2 x 100, 56.1 s | 8 x 25, 30.7 s | 1.83x |
  | 800 | 8 x 100, 82.4 s | 16 x 50, 66.5 s | 1.24x |
  | 1,600 | 16 x 100, 118.1 s | 16 x 100, 108.7 s | 1.09x |
  | 3,200 | 16 x 200, 202.1 s | 16 x 200, 186.6 s | 1.08x |

  - These match §1.3's estimates.
  - Games were identical where the shape didn't change (1,600 and 3,200).
  - Rabbits v Vampires (16 x 50 in both): 752 of 800 games were identical. All 48 that differed are in one batch,
    starting at a game that hit the 120 s clock in one run and not the other.
- **Corrections to this report:**
  - **R04 gain:** not measurable at 16 processes (M2, within about ±3 %). One process alone was 5.6 % faster,
    so §1.3's +4-9.5 % doesn't show on today's cold path.
  - **R14a (M2):** 6-7 % faster at 16 processes and 9 % with one, on identical Izzet v Gruul games.
  - **R04's "Tied to the card log" risk:** resolved by pinning the copy to the SHA-256 of Forge's class file and
    naming the copies that fit in the jar's stamp.
  - **G18 (M8):** the round-3 exposure removes the game-length skew, and it is specified for wave 2
    (RECORD_VERSION 3).
  - **G17:** Forge's colour screw matches goldfish for Gruul, Izzet and Rabbits. Orzhov Vampires is +2.7 points
    worse (turn-1 land sequencing).
- **Still open:**
  - M3, BELOW_NORMAL under load.
  - APC=2 at 8 processes on its own.
  - Waves 2 (R05, R01b, the v2 bump with R06, R09, R08 and R14b, R11's exposure) and 3 (R12, R13, R15, R10, R16
    and R17).
- **Evidence:** `sim-investigation/w1/` (`meas/notes.md` for M1-M2, `m8/notes.md`, `r14a/README.md`).

**Wave 2 status (2026-10-03): built, not yet measured.** Built on branch `sim-w2` to the contract in
`sim-wave2-contract.md` (beside this file). `decklab/HISTORY.md`'s "Simulation speed and accuracy, wave 2" has the
details.
- **Built:**
  - R05 + R01b: the warm pool, one shared chunk queue, one physical core per worker (CCD0 first).
  - The v2 engine (`FORGE_RUN_VERSION` 2): R06's engine id, R09's per-game seeds (a coin flip and Forge's
    auto-profile every game), R08 (PERFORMANCE_MODE) and R14b (forced attackers in attacker order: a game patch,
    in the id).
  - R14a, adopted (AI eval on a virtual thread; same games, not in the id).
  - R11 item 4 (card-log record version 3, in hand by the side's own turn 3).
  - The `replay` command for earlier engines' results.
- **Checked (games, not time):**
  - v2 games equal plain Forge's one-game processes line for line (12 of 12 Constructed; 3 of 3 Commander by
    outcome), and chunking doesn't change them.
  - A warm worker plays the same games as fresh processes (21 of 21, v2 and v1, pinned).
  - R14a: 100 of 100 identical logs. R14b: 40 of 40 repeats on a must-attack deck, against 16 of 40 with Forge's
    thread pool.
  - The turn-3 tally matches M8's shares and moves Gruul's verdicts as M8 predicted.
- **Not measured yet:** no speed claim is made for wave 2. The PC was in use while it was built, so every run was
  small. M3 (the pool against wave 1's cold batches, pinned against unpinned, R14a and R08 in the pool, below-normal
  priority under load) is measured on an idle PC before merging to main. Then the saved matchups are replayed with
  the v2 engine (`replay --dry-run` listed 22 matchups and 26,094 games on a copy of the results).
- **Additions to R14 (§4):**
  - **Its risks** are answered as R04's was: each copy is pinned to the SHA-256 of Forge's class and drops out by
    itself after an upgrade that changes it. The copies keep Forge's line numbers, and a test pins Forge's other
    lines.
  - **R14a** uses a platform thread, as Forge does, while an earlier eval that timed out is still running, so a stuck
    eval can't hold one of the 2 carrier threads. Virtual threads make the card log need JDK 21 or later.
  - **R14b** passes over an attacker whose check throws an exception or overflows its stack, as Forge's
    `invokeAll` did.
- **Wave 3** (R12, R13, R15, R10, R16 and R17) is next. The per-pair seed streams and chunked runs it needs are in
  place.

---

## 1. Short answers

### 1.1 Why Deck Lab doesn't use the whole CPU

1. **The batch plan starts too few processes for the common sizes.**
   - `lists._batch_size` (`decklab/lib/forge/lists.py:201-211`, rule at `:208`) uses 100-game batches unless
     the run reaches 3,200 games.
   - So 200 / 400 / 800 / 1,600 / 3,200 games start 2 / 4 / 8 / 16 / 16 Forge processes (measured, e1).
   - The default 800-game run uses 8 processes. Windows packs those 8 onto the hyper-thread pairs of about 7
     cores, mostly on CCD1, and about 6.5 physical cores sit idle.
   - Average CPU is 14 % at 200 games and 43 % at 800 (measured, e1).
2. **Forge plays one game on one thread per process, by design.**
   - Sixteen busy processes show about 55-70 % on Task Manager even when every physical core is working.
   - Measured (e4): the warm pool averaged 59.6 % CPU while all 16 physical cores were at least 75 % busy in
     94.9 % of seconds.
   - So 100 % in Task Manager isn't the right target. The second hardware thread of a core adds only about
     +17 % per core (estimate from e2's medians), and two processes per core lost overall when cold
     (1,006 vs 1,211 games/min, e2).
3. **Every batch pays a cold start.**
   - JVM start-up plus JIT warm-up costs 10-26 s per process (e1).
   - When 16 start together, the PC is saturated for about 30 s. Each JVM sizes itself for 32 CPUs, with 15 JIT
     and 23 GC threads at high priority (measured, r3).
4. **Uneven endings ("tails") waste process time.**
   - Fixed batches finish at different times: 8-17 % of the run for typical decks.
   - For board-heavy and Commander matchups it is 32-39 %, where a single game can run 78 s (e1, e3).
5. **Nothing shares workers.**
   - The server runs one matchup at a time (`api/forge_runs.py:48-53`), so one matchup's tail can't be filled
     by the next.
   - There is no limit across CLI runs, so parallel runs can oversubscribe the PC (r1 §3).

**Not the cause**
- The Python parent: 1-2.5 % of one core (r1, e3).
- Logging: 3 % at most (e3).
- Memory: 9-16 GB of 64 (e1-e4).

### 1.2 Is Forge's simulation any good?

**What holds up (measured)**
- **Deterministic per seed.**
  - The same seed gives the same games: 200/200 identical in a saved re-run (r5).
  - 90/90 full logs were identical between warm and fresh processes (e3).
  - Winners were identical across every JVM flag and affinity setting tried (e2, e3).
- **The estimator is unbiased.**
  - Mirrors come out balanced: Izzet 49.4 % (47.0-51.9), Gruul 48.4 % (45.9-50.8) (e4).
  - Games are independent once you know who started: dispersion 1.046, lag-1 residual -0.0004 (r5).
- **It sees quality differences.** Izzet beats a copy with 4 key spells swapped for lands **59.2 %**
  (56.7-61.6), about 7 standard errors (e4).
- **Going first matters about as in real Magic.**
  - Across 33 saved Constructed results it is worth +6.7 points (SE 0.5), so an even matchup is 53 % on the
    play (r5).
  - In the Gruul mirror the starter wins 54.7 %.
- **Mulligans and land drops are sane** (new this pass, `f1-final` 2a).
  - Forge's mulligan rates match Deck Lab's own goldfish simulator to within about 1-2 points for Izzet,
    Gruul, Rabbits and Vampires (for example Izzet 22.0 % vs 22.2-22.4 %).
  - Land drops match too, except Izzet, which is ahead by 4-9 points; it runs Preordain, which goldfish
    doesn't model.

**What doesn't (measured and from the source)**
- **The AI pilots some archetypes badly** (r4):
  - Team pumps are judged one creature at a time: Overrun and Rabbit Response are cast for 37-55 % of drawn
    copies.
  - Default attacks too little. Milestone 0 put Rabbits 12-15 points low.
  - Creatures whose "when this enters" clause is useless right now are held back. Massacre Wurm comes down
    around turn 10-11 vs 7.5-7.9 for Grave Titan.
  - Counterspells get no mana held for them.
  - Some cards are never cast: Devout Decree 0 of 1,326 drawn copies; Fiery Annihilation 0 % until it was
    overridden.
  - By contrast, removal, burn and creatures on curve are played well: 85-99 % cast.
- **Its tempo play is passive.** The Izzet mirror lasts 11.8 rounds and shows no play/draw advantage (50.2 %),
  so Forge likely understates tempo (e4).
- **No outside validation exists.** Nobody (developers, community or papers) has validated Forge against human
  results (r6). A Forge win rate measures the deck plus Forge's pilot.
- **Matchups are intransitive.** A single strength rating (Bradley-Terry) explains 98.4 % of the spread, but
  predicts an unplayed pairing only to about ±7.7 points (r5). The per-opponent matrix is the real answer.
- **Resolution is limited.** A 95 % range is about ±3.5 / 2.4 / 1.7 points at 800 / 1,600 / 3,200 games. AI
  profile changes moved results only 0-3 points (e4).

**So:**
- Trust Forge for **relative** comparisons, best of all between variants of the same deck.
- Flag the decks it pilots badly: Rabbits, The Free Peoples, Finneas, Gisa.
- Treat differences under about 3-4 points at 1,600 games as noise.

### 1.3 Biggest wins (after corrections)

| What | Gain | Effort | Recs |
|---|---|---|---|
| **Quick wins**: new batch plan + `-XX:ActiveProcessorCount=2` | 200 games 57 → ~28 s; 400 games ~75 → ~40 s; 800 games about +20-27 % (~64 s); 1,600 about +10 % (derived/estimate) | small | R02, R01a |
| **Statistics fixes** | Correct starter tile. Lead verdicts with ~23 % fewer games (measured on saved results). Per-card verdicts no longer skewed by game length (up to ±6-9 points) or naive pooling (48 of 407 verdicts change) | small to medium | R03, R11 |
| **Warm worker pool** + one queue shared across matchups + a machine-wide worker budget + per-core pinning | 1.7-1.9x over the quick wins once warm (measured 1,375-1,465 g/min vs 793), almost no tail. A deck-design session of 7,200 games would drop from 17.1 to ~5.5-7 min, **if the pool stays alive between runs** (estimate) | large | R05, R18, R01b |
| **One "v2" engine change** bundling every game-changing item under one run-version bump | PERFORMANCE_MODE +5-12 % (warm, measured). Per-game seeds: ~6 % fewer games for a typical matchup, and they make paired deck-vs-variant tests possible (up to 2.5-4x fewer games, an upper bound) | medium | R06, R09, R08, R15 |
| **Remove Forge's 100 ms sleep per mulligan** | +4-9.5 % for Izzet/Gruul-type decks, ~2 % board-heavy (estimate; the sleep's share is measured) | small-medium | R04 |
| **Adaptive stopping and a field view** | 2-7x fewer games on lopsided matchups (simulation) | medium | R12, R13 |

**Dropped or cut back after checking**
- Raising Forge's 5 s AI timeout (**R07, dropped**): no measured effect, and it would probably turn stalled games
  into clock-stop non-wins.
- The card-script override set (**R10**): cut back to the one fix that was measured, Fiery Annihilation.

---

## 2. Reference numbers

### 2.1 Speed today (measured, e1; Izzet Prowess vs Gruul Ramp unless noted)

| Run | Processes x games | Wall | Games/min | Average CPU | Tail |
|---|---|---|---|---|---|
| 200 | 2 x 100 | 56.8 s | 211 | 13.7 % | 17 % |
| 400 | 4 x 100 | ~72-77 s | ~313-336 | n/a | n/a |
| 800 (default) | 8 x 100 | 78.8-81.3 s | 590-609 | 43 % | 12 % |
| 1,600 | 16 x 100 | 113.9 s | 843 | 76 % | 9.5 % |
| 3,200 | 16 x 200 | 201.3 s | 954 | 70 % | 8 % |
| Rabbits v Vampires, 800 | 8 x 100 | 362.6 s | 132 | 26.5 % | **39 %** |
| Giada v Finneas (Commander), 800 | 8 x 100 | 353.2 s | 136 | 29.8 % | **32 %** |

- The 400 row is r1's model plus Deck Lab's saved-run median, not an e1 run.
- Saved Deck Lab runs at 800 games have a median of 573 g/min (r1).

### 2.2 Shapes tried (Izzet v Gruul; derived from e2/e3 per-game timestamps, `v-r02/proxy-out.txt`)

| Shape | Current flags, unpinned | APC=2, unpinned | APC=2, one core per process |
|---|---|---|---|
| 8 x 25 (200 games) | 27.2 / 28.7 s | not run | not run |
| 16 x 25 (400 games) | 46.4 s (517 g/min) | **37.6 s (639)** | 40.2-43.4 s (553-597) |
| 16 x 50 (800 games) | 67.0 s (717) | **58.1 s (826)** | 55.9-60.9 s (789-859) |
| 16 x 100 (1,600 games) | 105.5 s (910) | 96.2 s (998) | 94.3 s (1,018) |
| 16 x 150, whole run (e2, measured) | 1,011 g/min | 1,086 | **1,211** |

- e2's rows ran the same seed in every process; e3's ran varied seeds.
- **Reading:**
  - On short cold batches, almost all of the gain comes from `ActiveProcessorCount=2`.
  - Pinning each process to a core adds little or nothing there, because the CCD1 slots are slower and an even
    static split waits for them.
  - Pinning pays in the warm phase, and with a shared queue that absorbs the CCD difference: e2's warm rate went
    from 1,276 to 1,626 g/min (+27 %).
  - This is why R01 is split into R01a and R01b.

### 2.3 Warm pool (measured, e3/e4; 16 pinned APC=2 workers, DeckLabServe prototype)

**Speed**
- Izzet v Gruul, 800 games per round:
  - round 0, including start-up: 784 g/min;
  - rounds 1-2: 1,375-1,465 g/min;
  - with PERFORMANCE_MODE: 1,543 g/min.
- Rabbits v Vampires, 400 games per round: 222 g/min in round 0, 257 warm.
- e4's mixed queue (656 jobs, 12,800 games): 876 g/min overall, 1,263 for the Izzet/Gruul-type part. Workers
  were busy 98.7 % of the time, and memory peaked at 16.1 GB.

**CCD0 vs CCD1 (new this pass)**
- In e4's shared queue, CCD0 workers finished 7,005 games and CCD1 workers 5,795 in equal busy time. So the
  V-Cache CCD is about 21 % faster per worker for Forge.
- CCD1 workers also used more CPU per game. That suggests the slowdown comes from the cache, not from waiting
  (an inference; `f1-final/ccd_split-out.txt`).

### 2.4 Accuracy checks (measured, e4/r5)

| Check | Result |
|---|---|
| Mirrors, balanced | Izzet 49.4 % (47.0-51.9); Gruul 48.4 % (45.9-50.8) |
| Starter wins, mirrors | Gruul 54.7 %; Izzet 50.2 % (passive mirror) |
| Known ordering (-2 Bolt, -2 Sprite Dragon, +4 lands) | full deck 59.2 % (56.7-61.6) |
| AI profile changes | Izzet/Gruul ±0-0.3 points. Rabbits on Reckless +2.5 (-2.0 to +7.0) pooled, +3.6 in Milestone 0 |
| Fiery Annihilation override | Used for 0 % → 92.1 % of drawn copies. Gruul's win rate when drawn 44.7 → 54.4 %. Matchup -0.1 (-3.5 to +3.3); pooled with Milestone 0, about +0.8 (-1.2 to +2.7) |
| Saved results: play vs draw | +6.7 points (SE 0.5); an even matchup is 53.0 % on the play |
| Forge mulligans vs goldfish (new) | Within about 1-2 points for 4 decks. Land drops match, except Izzet (+4-9 points; Preordain) |

---

## 3. Ranked plan

- Ordered by value per effort, with dependencies respected.
- "Checked" says what the skeptic pass found.
- IDs R11-R19 weren't separately skeptic-checked. Their gains come from the phase notes and are marked as
  estimates.

| # | ID | Change | Kind | Gain (label) | Effort | Needs | Checked |
|---|---|---|---|---|---|---|---|
| 1 | R02 | Batch plan: at least 25 games per batch, up to `workers` batches | speed | 200: ~1.9x faster; 400: ~1.6-1.9x; 800: about +20-27 % with R01a (derived/estimate) | small | ships with R01a | holds, corrected |
| 2 | R01a | `-XX:ActiveProcessorCount=2` | speed | +10-15 % on 16-process cold runs; start-up 5.2 → 3.4 s (measured/derived) | trivial | none | holds, split from R01 |
| 3 | R03 | Starter tile, lead verdict, "about even" verdict | stats | Tile correct (13-29 % → 48-54 %); lead needs ~23 % fewer games (measured on saved results) | small | none | **corrected** (was holds = false) |
| 4 | R19 | Trust labels on deck and matchup pages | accuracy | Better reading of results; no speed change | small | none | not separately checked |
| 5 | R04 | Remove the 100 ms sleep per mulligan | speed | +4-9.5 % IG-type, ~2 % board-heavy (estimate) | small-medium | none | holds, gain unmeasured |
| 6 | R11 | Per-card statistics: stratified pooling, shrinkage, "early" label, round-3 exposure | stats | Removes skews of up to -6.4 to +9.4 points; 48 of 407 verdicts change (measured on saved data) | medium | none (the exposure needs a new tally) | not separately checked |
| 7 | R18 | Machine-wide worker budget + BELOW_NORMAL priority | speed | Prevents 32-48-JVM pile-ups (K=32 measured 17 % slower than K=16); keeps the PC responsive (unmeasured) | medium | none | split from R05 (raised by v-r01/v-r02) |
| 8 | R05 | Warm worker pool + one shared chunk queue | speed | 1.7-1.9x over the quick wins once warm; ~1.0x for a freshly started pool (measured) | large | R18; simjar multi-file build (R04) | holds, re-attributed |
| 9 | R01b | One core per worker, CCD0 first (with R05) | speed | Warm steady state +15-27 % over unpinned (estimate from e2's +27 %); ~0-2 % on cold short batches (derived) | medium | R18, R05 | split from R01 |
| 10 | R06 | v2 engine id: key, per-side ids, filtering, fallback keyed as its own engine | accuracy | Correctness safeguard; replay ~26-34 min warm (estimate) | medium | R04's build; ideally R05 | holds, corrected |
| 11 | R09 | Per-game seeds, coin flip every game, auto-profile every game (v2) | stats | ~6 % fewer games typically; makes R15 possible (measured design effect) | medium | R06 | holds in part |
| 12 | R08 | PERFORMANCE_MODE (v2) | speed | +5-12 % warm IG-type, +4-5 % board-heavy (measured warm) | small | R06 | holds |
| 13 | R14 | AI hand-off patch: eval on a virtual thread; attack checks as a loop (v2) | speed | 5-11 % of a warm game (estimate) | small-medium | R04's build; part (b) needs R06 | not separately checked |
| 14 | R12 | Adaptive stopping | stats | 2-7x fewer games on lopsided matchups (simulation) | medium | R05 (chunks), R03 | not separately checked |
| 15 | R13 | Field view: one deck vs 8-12 opponents | feature | Faster, more targeted strengths and weaknesses (estimate) | medium-large | R05, R12; per-pair seeds (R09) | not separately checked |
| 16 | R15 | Paired deck-vs-variant tests | stats | Up to 2.5-4x fewer games for 1-2 card swaps (upper bound) | medium | R09 | not separately checked |
| 17 | R10 | Fiery Annihilation override now; other overrides as gated experiments | accuracy | Gruul per-card verdicts fixed; matchup ~+1 point (unresolved) | small | R06 filtering | **corrected** (was holds = false) |
| 18 | R16 | Pilot experiments: profiles, TeamPumpAi, AI hints, hybrid AI | accuracy | Potentially the largest accuracy lever for Rabbits and Free Peoples (estimate) | medium | M5 runs | not separately checked |
| 19 | R17 | Side build with Forge's open speed PRs | speed | Up to 1.3-2.35x on wide token boards (PR authors' numbers) | medium-high | M-run A/B | not separately checked |
| — | R07 | Raise the 5 s AI timeout | accuracy | ~0 measured; probably negative | — | — | **dropped** |

---

## 4. Recommendations in detail

### R02: Batch plan (stopgap until the warm pool)

- **What to change.** Pick the number of batches as the largest **even** number that is at most
  `min(workers, games // 25)`, divides `games`, and is at least 2.
  - With 16 workers: 200 → 8 x 25; 400 → 16 x 25; 800 → 16 x 50; 1,600 → 16 x 100 and 3,200 → 16 x 200
    (both unchanged).
  - With 8 workers, 3,200 becomes one wave of 8 x 400 rather than two waves of cold processes.
  - With 12 workers ("PC in use"), 400 becomes 10 x 40.
- **The page has to match.** `web/matchups.js` must copy the rule: `roughMinutes` at `:255-256`, the header at
  `:41-42` and the constants at `:60-62`.
- **Ship with R01a.** Sixteen cold processes only pay with APC=2.
- **Evidence.**
  - e1 measured 200 games at 56.8 s, and 16 x 50 at 652 g/min against 590-609 for 8 x 100 (+10 %, current
    flags).
  - Per-game timestamps (§2.2) give 27-29 s for 200 games as 8 x 25, and 37.6 s for 400 games as 16 x 25 with
    APC=2.
  - At 800 games, APC=2 adds +15 % to the 16 x 50 shape (717 → 826, same seed).
- **Gain.**
  - 200 games: ~57 → ~27-30 s.
  - 400 games: ~72-77 → ~38-46 s.
  - 800 games: ~73-81 → ~64 s, about +20-27 % (estimate: e1's 652 g/min x 1.15).
  - 1,600 and 3,200 games: no change from R02 itself.
- **Effort.** Small.
- **Risks.**
  - **Parallel CLI runs** now start twice as many JVMs: 32-48 when agents run 2-3 at once. R18 fixes this.
  - **CPU load:** 800-game runs go from 43 % to about 80 % at normal priority. R18 adds BELOW_NORMAL.
  - **Memory:** 16 APC=2 JVMs peak at 11.7-13.6 GB.
  - **Game 1 gets more weight.** Its share of games goes from 1 % to 4 %. Game 1 has a seeded coin flip and
    Forge's game-1 auto-profile.
    - No current deck triggers the auto-profile: truncated average mana value is 2-3 everywhere, and Gruul
      Ramp's 3.89 is the highest (v-r09). So nothing changes today.
    - r5's independence test used 100-game batches, so 25-game batches are an extrapolation.
  - **Saved results stay valid.** Batch size isn't in the key (`lists.py:162-165`) and seeds continue, so new
    games pool correctly with old ones.
- **Files.**
  - `decklab/lib/forge/lists.py:201-211`
  - `decklab/web/matchups.js:41-42, 60-62, 255-256`
  - `decklab/lib/forge/__init__.py:82-88` (docstring)
  - tests: `decklab/tests/test_forge.py:359-366, 369-372, 374-377, 886`; `test_web.py:766-773`; possibly
    `test_matchups_api.py:936-945`
- **Corrections applied (v-r02).**
  - The gain is at 200 and 400 games, not mainly 800.
  - The old title ("give every run all 16 workers") didn't match the plan.
  - Added a rule that works for any worker count.
  - Completed the file list.

### R01a: `-XX:ActiveProcessorCount=2`

- **What to change.** Add the flag to `runner.JVM_FLAGS` (`decklab/lib/forge/runner.py:25`).
- **Evidence.** Measured in e2 (16 x 150, the same seed in every process):
  - throughput 1,011 → 1,086 g/min;
  - start-up 5.15 → 3.38 s;
  - games/min at game 100: 910 → 998;
  - warm rate unchanged (1,260 → 1,275).

  The flag cuts each JVM's JIT and GC threads from 15/23 to 2/2. Per-game timestamps (§2.2) show +24 % at
  16 x 25, +15 % at 16 x 50 and +10 % at 16 x 100.
- **Gain.** +10-15 % on 16-process cold runs. 1,600 games ~114 → ~104 s; 3,200 games ~201 → ~187 s
  (estimates from the measured ratios).
- **Effort.** Trivial: one line plus a test.
- **Risks.**
  - **Determinism** was checked on Izzet v Gruul only: 2,400 same-seed games plus 400 paired varied-seed games,
    with identical winners.
  - **Forge's per-attack thread pool** shrinks from 32 to 2 threads. The order of forced attackers already
    depends on thread timing (rare).
  - **Memory:** peak goes from 9.9 to 13.6 GB at 16 JVMs.
  - **Not measured:** the effect at 8 processes (the 200-game shape).
  - **JDK upgrades:** re-check the ergonomics after one.
  - **No key change** is needed, because the games are the same.
- **Correction.** R01 ("pin each process to a core + APC=2") was split. Pinning adds about 0-2 % at Deck Lab's
  cold shapes (§2.2), so it moves to R01b alongside the warm pool, where it pays.

### R03: Page statistics (corrected)

**(a) Starter tile**
- Show `(p_A on the play + p_B on the play) / 2` with its MOVER-Wilson range, using `views.balanced()` on the two
  decks' on-play records.
- Always show the range.
- If a deck never went first, fall back to the raw share with a note.

**(b) Lead verdict**
- **When a result has no non-wins** (33,289 of 33,294 saved games are wins), judge the lead on the balanced share
  of decided games. This equals "the headline range excludes 50 %".
- **Otherwise keep `_comparison`** (`views.py:35-57`). This keeps the 2026-10-01 non-win fix (commit `0a2197e`,
  `PLAN.md:17`) and its regression test (`test_forge.py:645-651`).
- An alternative is to weight the two starter strata by their decided rate.

**(c) Three verdicts**
- "ahead" when the range excludes 50 %;
- "about even" when the range lies inside 45-55 % (the margin is the owner's choice);
- "not settled" otherwise.
- **Precedence:** when "ahead" and "about even" are both true, say "X is slightly ahead (by under 5 points)".

**Evidence** (v-r03, measured on 36 saved results)
- **The tile reproduces.** Fellowship v Angels shows 13.8 %; balanced it is 50.3 % [45.6, 52.6]. Giada v Finneas
  shows 28.6 %; balanced it is 52.4 % [48.8, 55.1].
- **The lead range narrows.** Width ratio, current vs proposed: median 1.142 (1.128-1.235).
- **Simulated power rises.** A true 55 % matchup at 800 games: 75 % → 80 %. A true 53 % at 1,600 games:
  62 % → 72 %.
- **No saved verdict flips.**
- **"About even" behaves.** It fires in 62 % / 96 % of runs at a true 50 %, at 800 / 1,600 games (simulation).

**Gain:** a correct starter tile, and lead verdicts with about 23 % fewer games.

**Effort:** small, but it isn't only a view change.

**Risks**
- "Ahead" and "about even" overlap at 3,200 games: both hold in 20-55 % of runs at a true 51-54 %. The precedence
  rule handles it.
- The tile spans about ±5 points at 400 games.

**Files**
- `decklab/lib/forge/views.py:17-57, 182`
- `decklab/web/matchups.js:1126-1133, 1158-1160, 1208`
- `decklab/lib/forge/cli.py:644`
- tests: `decklab/tests/test_forge.py:579, 599, 617-651`; `test_matchup_verdict.py`; `test_web.py:552`
- `decklab/PLAN.md:17`

**Corrections applied**
- "29 % fewer games" was measured against a rejected (Wald) method and was also inverted. The real figure is about
  23 %.
- The decided-games rule as written reversed a deliberate fix.
- The overlap rule was missing.

### R19: Trust labels on pages (not separately checked)

**What to show**
1. "Differences under about 3-4 points at 1,600 games per side are noise."
2. Per deck, "Forge pilots this deck poorly" when it holds cards in the AI-weak classes confirmed in Forge's
   source (r4 §2):
   - team pumps (PumpAll);
   - "when this enters" clauses that veto casting;
   - strict `AITgts`;
   - `AI:RemoveDeck:All`;
   - flash creatures without an enters effect;
   - counterspells.

   Compute this from the card scripts, extending `ai.py`'s never-cast list.
3. "Forge likely understates going first in tempo and counterspell mirrors." In the Izzet mirror the starter wins
   50.2 %, against 54.7 % in the Gruul mirror.
4. "Commander results are indicative only," until the Commander questions in §7 are answered.

**Gain:** better reading of results; no speed change.

**Effort:** small.

**Risk:** over-flagging. Keep to the classes confirmed in Forge's source.

**Files:** `decklab/lib/forge/ai.py`, the deck and matchup views, `decklab/web/*`.

### R04: Remove Forge's 100 ms sleep per mulligan

**What to change**
- Ship a copy of `forge.game.mulligan.AbstractMulligan` without `Thread.sleep(100)` (`AbstractMulligan.java:39-43`;
  javap confirmed the same call in the installed jar's bytecode).
- Put Deck Lab's jar first on `-cp`. Today Forge's jar comes first (`runner.py:55-56`).

**Evidence.** v-r04 re-counted e4's 12,800 logs. The sleep's share of mean game time (measured):

| Matchup | Sleep share |
|---|---|
| Izzet v Gruul | 8.7 % |
| Izzet mirrors | 7.0-7.5 % |
| Izzet v weakened Izzet | 5.2 % |
| Gruul mirror | 4.2 % |
| Rabbits v Vampires | 1.7 % |

**Gain** (estimate; no A/B run yet)

| Setting | Izzet/Gruul-type | Board-heavy |
|---|---|---|
| Warm pool | +4-9.5 % throughput | ~+2 % |
| Today's cold path | +4.5-7 % | ~1.5 % |

Commander: ~1-2 %.

**Effort:** small-medium.
- The class copy itself is small.
- `simjar` needs a multi-file build.
- `CHECKED_SOURCE` changes, so the card log stays off until `cardlog-check` passes again.

**Risks**
- **Silent loss:** a jar built without the class still passes the check. Add it to `simjar.CLASSES`
  (`simjar.py:66`).
- **Tied to the card log:**
  - A failed build turns the card log off.
  - A copy that no longer fits a new Forge gives `NoSuchMethodError`.
  - Fix: build the patch as its own class-path entry, or list it in the check.
- **The check must mulligan:** confirm `cardlog-check`'s decks mulligan at least once. One check deck is 64 Plains
  plus singletons.
- **Licence:** the copied class needs a GPL-3 header.
- **Same JDK:** compile with the javac beside the runtime JDK.
- **Games stay identical,** except those ending within 0.1-0.3 s of the 120 s clock or after a stray AI thread.
  Both are already timing-dependent.

**Files**
- new `decklab/lib/forge/java/forge/game/mulligan/AbstractMulligan.java`
- `decklab/lib/forge/simjar.py:1-40, 63-66, 374-416`
- `decklab/lib/forge/runner.py:48-61`
- `decklab/tests/test_forge_simjar*`

### R11: Per-card statistics (not separately checked)

**What to change**
1. **Stratify pooling across matchups** (Mantel-Haenszel) on deck pages: `cardstats.list_cards`
   (`cardstats.py:225-244`) and `saved._pooled_cards` (`saved.py:209-240`).
2. **Shrink each card's difference** (tau ≈ 4.5 points). Say "won more/less when drawn" only for
   Benjamini-Hochberg 10 % discoveries.
3. **Call numbers "early" below ~800 games.** Today `MIN_CARD_GAMES = 100` counts as settled, though a card's range
   at 100 games is about ±20-28 points.
4. **Change the exposure measure.** Replace "drawn at any point" with "a copy in hand by the side's own round 3".
   This needs a new card-log tally and a RECORD_VERSION bump, so validate it on e4's logs first (M8).

**Evidence** (r5, measured on saved data)
- **Game length skews verdicts.** A card with no effect would show -6.4 to +9.4 points from game length alone.
  Correcting for it leaves 301 of 361 nonland verdicts.
- **Pooling across matchups skews them too.** Stratifying changes 48 of 407 verdicts (gaps up to 10.4 points).
- **Many verdicts are chance.** 311 pass |z| > 1.96 where 73 are expected by chance; 152 survive BH-10 %.

**Gain:** fewer misleading per-card verdicts, which are half of a deck's "strengths and weaknesses".

**Effort:** medium.

**Risks**
- The game-length baseline is a model.
- The new exposure measure only covers new runs.

**Files:** `decklab/lib/forge/cardstats.py`, `saved.py`, `cardlog.py`, `logreader.py`, and the deck page's
per-card view.

### R18: Machine-wide worker budget and lower priority (split out of R05)

**What to change**
- **One pool of `forge_workers` slots for the whole machine.** Each slot is an OS-held lock, released when its
  process dies (for example one lock file per slot, opened with an exclusive lock). Marker files won't do.
- **Every Forge start claims slots:** server runs, CLI `play` and gauntlet runs, and `forge check` (`cli.py:412`).
- **Goldfish practice workers count against the budget** (`server.py:126-129`).
- **When no slot is free,** wait, or run fewer processes.
- **Lower priority.** Start Forge JVMs at the BELOW_NORMAL priority class (`processes.py:158-196`). Today they
  inherit normal priority (the scheduled task runs at priority 5, which is normal).

**Evidence**
- Nothing limits parallel CLI runs today: three 1,600-game runs would start 48 JVMs (r1 §3).
- e2 measured 32 JVMs at 1,006 g/min against 1,211 for 16, with an 18.6 s median start-up (max 35.4 s).
- The 2026-10-02 deck-design session ran two CLI runs at once.
- R02 doubles the JVMs per run, and R01b needs slot numbers that are unique across the machine.

**Gain**
- Prevents 17 %+ losses and memory pile-ups from overlapping runs (derived from the K=32 run).
- Keeps the PC usable (unmeasured).

**Effort:** medium, Python only.

**Risk:** BELOW_NORMAL should cost nothing on an idle PC (unmeasured; checked in M3).

**Files**
- `decklab/lib/forge/processes.py`, `runner.py` (`_play`), `cli.py`, `api/forge_runs.py`
- a new `slots` module
- `decklab/lib/goldfish/workers.py`

### R05: Warm worker pool with one shared chunk queue

**What to change**
- **Persistent workers.** Add a serve mode to DeckLabSim that shares its `simulate()`; the prototype copied it.
  - `FModel.initialize` runs once per worker.
  - Each request restores the 7 static id counters, clears `AiCache` and `ChangeZoneAi`'s list, reseeds, and plays
    in a new Match.
- **One queue** of chunks from every queued matchup.
- **Recycle** a worker after a 120 s clock stop or an AI timeout. This replaces R07.
- **Stop at game boundaries,** using a per-request cancel flag.
- **Merge per-chunk tallies** per run before saving.
- **Lifetime.** The server owns the pool, and CLI runs **submit to a running server** (or to a small standalone pool
  daemon). Shut the pool down after it has been idle for a while.

**Evidence** (measured, e3/e4)
- **Speed.** Warm rounds run at 1,375-1,465 g/min, against 793 for the best cold setup with the same flags: 1.73-1.85x
  once warm.
- **A fresh pool gains nothing yet.** Its round 0 ran at 784, about 1.0x.
- **Rabbits v Vampires:** warmth adds +16 % (222 → 257).
- **No tail.** In the mixed queue, workers were 98.7 % busy.
- **Determinism.** 90/90 full logs were identical between warm and fresh workers, with and without the counter reset.
  32/32 and 40/40 jobs had identical winners across rounds.

**Gain**
- 1.7-1.9x over the quick wins for repeated or gauntlet work once warm; ~1.0x for one run on a cold pool.
- A deck-design session of 18 x 400 games (17.1 min measured) would take ~5.5-7 min, **only if the pool persists
  across the session's separate runs** (estimate). With the quick wins alone it would take ~12-15 min (estimate).
- A warm 200-game run would take ~10-18 s (estimate).

**Effort:** large.

**Risks** (v-r05)
- **The reset list is incomplete.** `Card.cp2card` / `getCardForUi` (`Card.java:7474-7484`) persists across requests.
  - Make the fresh-vs-warm log-equivalence test a per-Forge-version gate, like `cardlog-check`.
  - Run `cardlog-check` on the serve jar.
- **Memory:** 13-16 GB is held while idle.
- **Locks** must be OS-held.
- **Recycling** costs about 1-3 % (estimate).
- **Untested:** Commander, decks heavy in static or replacement effects, and soak runs (more than 5 requests per
  worker).
- **Game-1 effects repeat in every chunk.**
  - The auto-profile affects no current deck. Until v2, refuse or flag chunked runs for any deck whose truncated
    average mana value reaches 4.
  - The per-chunk coin flip is handled by the balanced estimator.

**Files**
- `decklab/lib/forge/java/decklab/DeckLabSim.java` (serve mode)
- new `decklab/lib/forge/pool.py`
- `runner.py`, `processes.py`, `api/forge_runs.py:48-53`, `decklab/server.py`, `cli.py` (gauntlet and submit)
- `simjar.py` (multi-file build), `saved.py`

**Correction:** "2.1-2.4x vs today" combined this change with the quick wins and PERFORMANCE_MODE. R05's own share is
1.7-1.9x, and only once warm.

### R01b: One core per warm worker, CCD0 first

**What to change**
- Pin each worker to both hardware threads of one physical core.
- Work out the masks from `GetLogicalProcessorInformationEx` (as `tools/cpusampler.py topology` does), and find the
  V-Cache CCD by its L3 size.
- Take slot numbers from R18.
- If `SetProcessAffinityMask` fails, run unpinned and log it once.
- Keep APC=2 explicit.

**Evidence**
- **Warm rate (e2):** 1,276 → 1,626 g/min, and the share of time with all 16 cores busy rose from 31 % to 78 %.
- **Paired games (e3, varied seeds):** 16 pinned processes play at the per-game speed of 8 unpinned ones (603 vs
  612.5 ms). Unpinned, going from 8 to 16 costs 46 %.
- **The mask alone sizes the JVM.** A 0x3 mask makes JDK 26 size itself for 2 CPUs (v-r01).
- **CCD0 is faster:** its workers played 21 % more games in e4's shared queue (new this pass).

**Gain**
- In the warm pool: +15-27 % steady state over an unpinned warm pool (estimate; an unpinned warm pool was never
  measured).
- On cold batches of 100 games or fewer: ~0-2 % (derived), so not worth shipping before R05.

**Effort:** medium, about 150-250 lines including topology detection, slot claims, the fallback and the test mocks
(`test_forge.py:971, 1272`).

**Risks**
- Slots collide without R18.
- A hard-coded topology gives invalid masks with SMT off.
- Pinned workers can't move away from goldfish workers or foreground apps (checked in M3).
- The 3D V-Cache driver may park CCD1 in Game Mode (unverified, r3).
- Softer options (per-CCD masks, CPU sets) are untested.

**Files:** `decklab/lib/forge/processes.py:158-196`, the pool module, tests.

### R06: v2 engine id (key, per-side ids, filtering)

**What to change**
- **One version bump.** Raise `FORGE_RUN_VERSION` (`common.py:20`) **once**, carrying every game-changing item together:
  R09, R08 and R14b.
- **An engine id.** Canonical JSON (`sort_keys`) of the **semantic** settings, not source hashes.
  - Per side: `card_sha` paired with the AI profile's *content* hash.
  - A hash of the override files actually deployed.
- **Stored on each result and on each side.**
- **Filtered or labelled in every consumer:**
  - `saved._stored` (`saved.py:98-105`)
  - `cardstats.list_cards` (`cardstats.py:225-244`)
  - `ai.list_ai` / `ai_limits` (`ai.py:101-128`)
  - `views.results_for` / `list_item` (`views.py:218-227`)
  - `api/forge_runs.py` (`_TodaysLists`)
  - `web/matchups.js`
- **The plain-Forge fallback is keyed as its own engine,** not refused. Refusing would block every simulation after a
  Forge upgrade until `cardlog-check` passes.
- **v2 checks:**
  - the card log on vs off on the same seeds, with identical logs;
  - v2 game *g* vs plain Forge `sim -n 1 -s s_g`.
- **"Play more" on a v1 result** says it starts a v2 result.

**Evidence**
- A census of the saved results (37 results, 33,294 games): all run version 1, Forge 2.0.15, identical settings.
  **Nothing is pooled silently today** (v-r06).
- Three consumers pool by `card_sha` regardless of key, so changing the key alone wouldn't stop mixing.

**Gain:** preventive correctness.
- Re-playing the 26,094 games whose lists are still current: ~26-34 min on the warm pool, ~60-90 min cold (estimate).
- The other 7,200 saved games involve lists that no deck uses any more.

**Effort:** medium.

**Risks**
- **Over-keying.** Keep game-neutral settings out: lazy loading, warm vs fresh, APC, affinity, the mulligan sleep.
- **Unkeyed inputs:**
  - edits inside `C:/Tools/forge/res`;
  - stray files in `custom/cards` (mirror that folder, deleting extras);
  - the JDK version (untested).
- **Old v1 files** are never cleaned up (small).

**Files**
- `common.py`, `lists.py:162-165`, new `engine.py`, `saved.py`, `cardstats.py`, `ai.py`, `views.py`
- `api/forge_runs.py`, `web/matchups.js`
- `runner.py:84-103` (mirror `custom/cards`), `simjar.py`, `cli.py` (cardlog-check)
- `__init__.py:77-79`

### R09: Per-game seeds, a coin flip every game, auto-profile every game (inside v2)

**What to change**
- **A new Match per game.** This uses public API only and gives both the coin flip and a consistent auto-profile.
  Nulling `lastOutcome` gives only the coin flip.
- **A new seed per game.** Reseed MyRandom each game with SplitMix64(base, **pair key**, *g*). Share a seed stream
  across opponents only in paired variant tests (R15).
- **Auto-profile every game,** with the resulting flag shown per deck.
- **Recycle after a clock stop.**

**Evidence**
- **Design effect** of today's loser-goes-first rule: median 1.06 over 33 Constructed results, max 4.14.
  - In theory it is 1.19 at 70 % and 1.56 at 80 % matchups.
  - The Commander median is 1.20, from 3 results.
- **Paired arms barely line up today.** In e4 they replayed only 19 % of games identically.
- **No current list triggers the auto-profile:** no deck, product deck or substitute list. Truncated averages are
  2-3; Gruul Ramp is 3.89 (v-r09).

**Gain**
- About 6 % fewer games for a typical matchup. Only lopsided matchups gain much more, and they are already cheap.
- Chunk size and boundaries stop mattering, and any single game can be replayed.
- It is a **prerequisite for R15**. R12 and R13 benefit but don't need it.

**Effort:** medium.

**Risks**
- **The plain-Forge fallback** plays v1-style games. Key it (R06) or refuse it.
- **Seeds shared across opponents** would correlate a deck's results across a gauntlet: a field average over 8
  opponents would be ~1.7-2.4x noisier (estimate, ρ 0.1-0.2). Hence per-pair seeds.
- **Auto-profile cliff** at an average of 4.0: Gruul Ramp is one distinct 7-drop away.
- **Clock stops:** the old thread draws from the next game's RNG, so recycle the worker.
- **AI timeouts** stay load-dependent.

**Files**
- `DeckLabSim.java:158-162, 222-234, 239-284`
- `runner.build_command`
- `lists.plan` (`lists.py:180-198`, with the partial-batch rule at `:186-191`)
- `saved.py`, `common.py`, `simjar.py`, `cli.py`
- tests: `test_forge.py`, `test_forge_cardlog.py`, `test_api.py`, `test_matchups_api.py`

**Owner decision:** auto-profile "every game" (recommended: free, consistent, and shown per deck) or "never" (needs
reflection on a private field).

### R08: PERFORMANCE_MODE (inside v2)

**What to change**
- Add `PERFORMANCE_MODE=true` to `runner.PREFERENCES` (`runner.py:26`).
- Print `Spell.isPerformanceMode()` in DeckLabSim's header, to prove the preferences route works.
- Add a card scan when a deck is saved, to catch future decks that cast opponents' cards (Gonti-style).

**Evidence** (measured, warm prototype)
- **Izzet v Gruul:** -10.1 to -11.7 % Forge time; paired, -11 to -12 % (CI about -9 to -15 %).
- **Rabbits v Vampires:** -3.6 to -4.0 %; paired, -4.8 to -5.1 %.
- **Pool round 1 vs round 1:** +12 % g/min (unpaired; +5 % conservative).
- **1,050 distinct games unchanged,** with identical full logs where compared.
- **Static scans:**
  - no Forge replacement effect in the affected class works from outside the battlefield or command zone;
  - none of the 377 deck card names casts opponents' cards.

**Gain**
- Warm: +5-12 % for Izzet/Gruul-type decks, +4-5 % for board-heavy ones.
- Today's cold path: 3-9 % (estimate).
- Commander: untested, possibly more.

**Effort:** small, with R06.

**Risks**
- It must be part of the engine id.
- Its scope grew upstream (#11160, #11328), so re-run a fixed-seed identical-log A/B on every Forge upgrade.

**Files:** `runner.py:26`, `DeckLabSim.java`, `test_forge.py:1135`.

### R14: AI hand-off patch (not separately checked)

**What to change**
- **(a)** Run "Game AI Eval" on a virtual thread instead of a new platform thread (`AiController.java:1682-1686`).
  This keeps the `future.get(AI_TIMEOUT)` behaviour, so games don't change, and it can ship in R04's jar.
- **(b)** Run the attack-requirement checks as a plain loop (`AiAttackController.java:883-961`). This removes the
  thread-order dependence of forced attackers. It can change games, so it goes in v2.

**Evidence**
- 308 hand-offs per game plus ~18 attack-pool threads (e3 JFR, measured).
- Each hand-off costs 112-185 µs on a platform thread against 9-24 µs on a virtual thread (r2 bench, measured).
- Eval threads hold 48.8 % of Java samples.

**Gain:** 5-9 % (virtual thread) to 7-11 % (inline) of a warm game (estimate); possibly more under load.

**Effort:** small-medium.

**Risks**
- Shadowing a large Forge class makes upgrades fragile.
- The copies must be listed in `simjar.CLASSES` and covered by the check.

**Files:** `decklab/lib/forge/java/forge/ai/*.java` (new), `simjar.py`.

### R12: Adaptive stopping (not separately checked)

**What to change**
- **Default "assess" run:** a 400-game pilot, then plan the rest at once. Stop at a balanced-range half-width of
  3 points, or at 3,200 games.
- **"Who's ahead?" run:** Haybittle-Peto looks.
  - At 400 / 800 / 1,600 games: stop if |z| ≥ 3.0.
  - At 3,200 games: |z| ≥ 2.008.
  - Plus an "about even" exit.
- **Stop at game boundaries.** Show the live range as provisional, or as an anytime-valid range.

**Evidence** (simulation, r5)
- Peeking at a fixed 95 % range every 100 games gives false leads 29.5 % of the time.
- Haybittle-Peto stops at about 468 games for a true 60 % and 1,432 for 55 %, with bias under 1 point.
- Precision mode keeps coverage at 94.1-94.9 % and averages 731-1,100 games.

**Gain:** 2-7x fewer games on lopsided matchups.

**Effort:** medium. Needs chunked runs (R05); per-game seeds are only a convenience.

**Risk:** the page's Stop button is itself peeking. Show the "provisional" label.

### R13: Field view, one deck against 8-12 opponents (not separately checked)

**What to change**
- At least 200 games per opponent, then APT allocation.
- Show:
  - the matrix row;
  - a Bradley-Terry rating with a starter term;
  - a weighted field average;
  - residual flags (|z| > 2) as strengths and weaknesses.

**Evidence** (r5)
- The rating explains 98.4 % of the spread, but leave-one-out error is 7.7 points.
- Simulated APT allocation cuts the "wrong side of 50 %" error from 3.62 % to 0.12-0.40 % at 1,600 games.

**Effort:** medium-large. Needs R05 and R12, with per-pair seeds.

**Not measured end to end** (§7).

### R15: Paired deck-vs-variant tests (not separately checked)

**What to change**
- Run base and variant on the same per-game seeds.
- Write the variant's `.dck` in the base's order, with each replacement in the replaced card's slot.
- Keep the deck size the same.
- Analyse the games as pairs.

**Evidence**
- Today's paired outcome correlation is only -0.03 to +0.10.
- Unpaired, detecting +3 points needs 4,361 games per arm.
- For 1-2 card swaps, 56-78 % of games would couple (upper bound, from game lengths).

**Gain:** up to 2.5-4x fewer games (upper bound; the M4 measurement gates it).

**Effort:** medium. Needs R09.

### R10: Card-script overrides (corrected)

**What to change**
- **Adopt only the Fiery Annihilation override now,** and only after R06's per-side filtering. Otherwise Gruul's old
  0 %-used results pool with the new ones.
- **Ship the override folder in the repo.**
  - Mirror it into the user dir's `custom/cards`, deleting extras.
  - Hash what is actually deployed.
  - Restart the warm pool when the overrides change.
- **Treat the other sets as gated experiments (M5):** etb, tgt, remove, flash, and r6's PlayMain1/BuffedBy hints.
  Judge each against a control on four measures:
  - cast %;
  - cast turn;
  - win rate when drawn;
  - own permanents lost to the card.
- **Reconsider three edits:**
  - Sunblast Angel's `AILogic$ Always` can wipe its own tapped creatures.
  - Removing `AITgts` from Generous Gift is inconsistent with keeping it on Beast Within.
  - Fires of Mount Doom's Always casts it into an empty board.

**Evidence**
- **Card level:** Fiery Annihilation went from 0 % used (360 drawn copies) to 92.1 % (355). Gruul's win rate when
  it's drawn rose from 44.7 % to 54.4 % (+9.7, about +2 to +17).
- **Matchup level:** -0.1 in e4; pooled with Milestone 0, about +0.8 (-1.2 to +2.7).

**Gain**
- More accurate per-card verdicts for Gruul.
- Matchups about +1 point (unresolved).
- About 1-4 points at stake for The Free Peoples (estimate: 5 affected copies, partly offset because opponents' cards
  get fixed too).

**Effort:** small, after R06.

**Files:** a new override folder, `runner.py:84-103`, `ai.py`.

### R16: Pilot experiments (not separately checked)

**Experiments**
- A per-deck AI profile chosen by mirror match (X5).
- TeamPumpAi (X6; compiled, never run).
- The hybrid simulation AI (X7).
- AI-hint overrides: PlayMain1 for Valley Questcaller and Righteous Valkyrie; BuffedBy for Stormcatch Mentor and
  Heartfire Immolator.
- An Izzet counterspell profile.

**Evidence**
- Reckless for Rabbits: +2.5 pooled, +3.6 in Milestone 0.
- Other profile shifts: 0-3 points.
- Milestone 0 put Rabbits 12-15 points low.

**Gain:** possibly the largest accuracy lever for Rabbits, The Free Peoples and Finneas (estimate).

**Effort:** medium. Run the experiments first (M5); adopt only what they show.

### R17: Forge speed PRs in a side build (not separately checked)

**Candidates** (their authors' figures)
- #11314: 2.35x on wide token boards.
- #11981: -26 to -45 % on wide boards.
- #11366: 1.09-1.24x.

**Test:** A/B Rabbits v Vampires for speed and identical winners. The alternative is to wait for Forge 2.0.16 (around
mid-November 2026, estimate).

**Effort:** medium-high: a Maven build and a fork to maintain.

### R07: Raise the 5 s AI timeout (dropped)

**Why dropped**
- Only 10 of 33,294 saved games had an AI timeout.
- Milestone 0's replays gave the same winners in all 108 games, and the affected games were identical move for move.
- Timeouts happen in big-board stalls that are already near the 120 s clock: 3 of the 10 ended as clock stops.
  Longer decisions would turn some of these into clock-stop non-wins, which count against both decks.
- Forge 2.0.15 already cancels cooperatively (`AiController.java:1603, 1700-1703`).

**Instead**
- Recycling after a clock stop or AI timeout moves into R05.
- Revisit only if a K>16 test (X8) shows timeouts rising and changing winners.

---

## 5. Parallel work packages

- **Code packages** can run in parallel, with a worktree per package and a merge queue.
- **Measurement packages** need the whole, idle PC, so they run **one at a time**, each behind the idle gate
  (`tools/cpusampler.py idlecheck`).

### 5.1 Code packages

| WP | Recs | Owns (main files) | Can start | Gate before merge |
|---|---|---|---|---|
| A | R02, R01a | `lists.py` (`_batch_size`), `runner.py` (`JVM_FLAGS` only), `forge/__init__.py` docstring, `matchups.js` lines 41-62 and 255-256, plan tests | now | M1 |
| B | R03, R19 | `views.py`, `cli.py:644`, `matchups.js` lines 1126-1209, `ai.py` (trust flags), verdict tests, `PLAN.md:17` | now | unit tests; saved-result replay of verdicts |
| C | R04, R14a | new `java/forge/...` patch classes, `simjar.py` (multi-file build, CLASSES, CHECKED_SOURCE), `runner.build_command` (-cp order) | now | M2, then `cardlog-check` |
| D | R11 | `cardstats.py`, `saved._pooled_cards`, `cardlog.py`/`logreader.py` (new tally), deck page per-card view | now (pooling, shrinkage); exposure after M8 | M8 |
| E1 | R18 | new `slots` module, `processes.py` (priority, slot), `runner._play` slot claim, `cli.py`, `api/forge_runs.py`, goldfish worker budget | now | unit tests; M3 (priority) |
| E2 | R05, R01b | DeckLabSim serve mode, new `pool.py`, `runner._play` rewrite, `processes.py` (affinity), `server.py`, `cli.py` gauntlet/submit | after C (multi-file build) and E1 | M3 |
| F | R06, R09, R08, R14b | `common.py`, `lists._key`/`plan`, new `engine.py`, `saved._stored`, `cardstats.list_cards`, `ai.py`, `views.results_for`, `api/forge_runs.py` labels, `DeckLabSim.java`, `runner.py` (PREFERENCES, `_prepare_user_dir`), `cli.py` cardlog-check | after C; replay best after E2 | M4, v2 parity checks |
| G | R12, R13 | new stats modules (sequential tests, BT, APT), pool scheduler hooks, matchup and deck pages | after E2 (R13 also after F) | simulation tests; an end-to-end gauntlet (M3/M4) |
| H | R15 | aligned `.dck` writer (`lists._dck`), paired analysis, variant UI | after F | M4 |
| I | R10, R16, R17 | scratch experiments first, then the override folder, `runner._prepare_user_dir` mirror, `ai.py` override flags | experiments any time the CPU allows; code after F | M5 |

**Shared files.** Several packages touch the same files, in different functions or regions. Merge them in the order
A → B → C → D → E1 → E2 → F → G → H → I.

| File | Packages and what each touches |
|---|---|
| `runner.py` | A: JVM_FLAGS; C: build_command; E: `_play`; F: PREFERENCES and `_prepare_user_dir` |
| `matchups.js` | A: header and time; B: verdict and tile; F: labels; G: field view |
| `views.py` | B, F |
| `cardstats.py`, `saved.py` | D, F |
| `simjar.py` | C, E2, F |
| `ai.py` | B, F, I |
| `cli.py` | B, E, F |

**After a Deck Lab code change** (AGENTS.md): restart the background server only if it is running. A test server
uses `--host 127.0.0.1 --port 8643`.

### 5.2 Measurement packages (serial, idle-gated; durations are estimates)

| M | What | About | Feeds |
|---|---|---|---|
| M1 | Real-seed quick wins, each twice with Deck Lab's real seeds: 800 as 16 x 50 with APC=2 unpinned vs today's 8 x 100; 1,600 with and without APC=2; 3,200 once; 200 as 8 x 25 with APC=2; plus a winners comparison on Rabbits v Vampires | 15 min | WP-A; G16 |
| M2 | Mulligan patch and virtual-thread A/B: ig800 and rv800, same seeds, full log diff | 10 min | WP-C; G11 |
| M3 | Warm-pool battery: unpinned vs per-core vs per-CCD masks; K = 1/4/8 per CCD; K = 20/24/32; BELOW_NORMAL under a 4-thread background load and a browser video; Game Mode parking; a `pythonw.exe` launch with EcoQoS queried; Commander (Giada v Finneas, 800 games); a 2-3 h soak with fresh-vs-warm log diffs on sampled saved seeds; idle footprint and re-warm | 4-5 h | WP-E; G9, G10, G13, G14, G15, G12(1) |
| M4 | v2 prototype: 2 x 400 base vs a position-aligned 1-card variant (CRN correlation); rerun the Fiery pair; per-pair vs shared seeds across 2 opponents; v2 vs plain Forge `-n 1 -s s_g` on 20 games; card log on/off parity | 30 min | WP-F/H; G6, G7 |
| M5 | Accuracy experiments on the warm pool: a known-ordering ladder for 4-5 archetypes (-2/-4/-6 key spells); X2-X4 and the hint overrides, judged by cast %, cast turn, win when drawn and own-permanent losses; TeamPumpAi, the hybrid AI (speed first) and X8 with timeout counts; pilot sensitivity across the 14-list connected group under Default, then with overrides, then also Reckless | 2-3 h | WP-I; G2(1), G3, G4, G5 |
| M6 | Commander: about 200 four-player pods (minutes per pod, timeouts, clock stops, win rate by seat); one pod with a precon and an upgraded copy | 1-2 h | G12 |
| M7 | External check: a round robin of 6-8 current decks with published human win rates; Spearman rank correlation; check card coverage first | 1 h plus research | G2(2) |
| M8 | Light Python on e4's logs: the round-3 exposure vs current verdicts and r5's blank-card baseline; colour-screw comparison with goldfish | minutes, no idle gate | WP-D; G18, rest of G17 |

---

## 6. Not recommended

| Option | Why not |
|---|---|
| Several games per JVM on threads | One static RNG and non-atomic static id counters. Needs 6-10 patched classes, for only a few % over the warm pool (r2, e3). |
| AOT cache (Leyden) | +1-2 % (within noise), and a rebuilt jar silently serves stale classes (e2, r3). |
| More than 16 processes with fixed batches | e2: 1,006 vs 1,211 g/min, with an 18.6 s start-up. Revisit only warm (M3). |
| APC=1 | Serial GC and a 1-thread attack pool; -8 % warm (e2). |
| Experimental AI profile | Nothing measurable (e4). |
| XMage, Magarena or LLM pilots | 10-30x slower, dead, or $0.07-65 per game (r6). XMage only as a one-off second opinion. |
| Cutting the logging | It costs 3 % at most, and the card log needs it (e3). |
| Upgrading Forge now | Nothing relevant since 2.0.15. Watch 2.0.16 and the open PRs (r6). |
| Shortening the 120 s clock | More clock-stop non-wins, in exactly the slow matchups. |
| Raising the AI timeout (R07) | See R07. |

---

## 7. Still unknown, and how to find out

| Question | Why it matters | How to find out |
|---|---|---|
| How big are APC=2 and the new batch plan with real seeds, at 200, 800, 1,600 and 3,200 games? (G16) | These ship first. Today's numbers are partly same-seed proxies. | M1, twice each |
| Does the warm pool need hard pinning, or does a per-CCD mask or CPU sets do as well? Does pinning hurt when the PC is in use? (G14, v-r01) | R01b's design and its risk | M3: unpinned vs per-core vs per-CCD, idle and loaded |
| Do 20-32 warm workers beat 16? (G9) | The only route to higher CPU use. Also tells the owner whether Task Manager % matters. | M3: K = 20/24/32 pinned; track g/min, per-game ms, AI timeouts and memory |
| Why does per-game time rise under load (385-398 ms alone vs 492-544 at 16), and why is CCD1 slower? (G10) | Where to place workers when fewer than 16 run, and whether the V-Cache helps | M3: K=1/4/8 per CCD, logging `% Processor Performance` and frequency; optionally AMD uProf for L3 misses. *Partly answered:* CCD0 workers finish ~21 % more games (§2.3) |
| What do the mulligan patch, virtual-thread eval and Forge's speed PRs really gain? (G11) | Sizing R04, R14 and R17 | M2; a side build for R17 |
| What does PERFORMANCE_MODE gain on the cold path and through the preferences file, and in Commander? (v-r08) | Sizing R08 | A 50-game A/B in M1 or M2; print `Spell.isPerformanceMode()` |
| How strongly do games correlate with per-game seeds and aligned variants? Does the variant workflow work end to end? (G6, G7) | R15's 2.5-4x is an upper bound | M4, then one real decision, e.g. Gruul-24 vs Gruul against 3-4 opponents |
| Does a shared seed base correlate results across opponents? (v-r09) | Field-average error could grow 1.7-2.4x | M4: same deck vs 2 opponents, shared vs per-pair seeds |
| How does the whole "assess a deck against the field" flow perform? (G8) | It is the user's real use case | After WP-G: one deck vs 8-12 opponents, adaptive, against a fixed reference of 1,600 games per opponent |
| Do Forge's rankings hold up outside Forge? (G2) | "Is Forge any good?" beyond self-consistency | The M5 ladder; the M7 round robin; a household log of real 1v1 results by deck pair |
| Do rankings survive a change of pilot? (G3) | Whether pages should show bands instead of single numbers | The M5 pilot-sensitivity replay |
| Do the untested AI fixes work, and do they over-correct? (G4, G5) | Whether to adopt R10 and R16 | M5 |
| Commander: warm-pool speed and determinism, 4-player pods, power level (G12) | The owner's next format | M3 (Giada v Finneas), M6 |
| Does Windows throttle (EcoQoS) Forge processes started by the server under `pythonw.exe`? (G13) | Measured gains might not show up from the page | M3: run from `pythonw.exe` and query `GetProcessInformation(ProcessPowerThrottling)`. *Partly answered:* same spawn flags, normal priority, interactive session (`f1-final` 2e) |
| Can the warm pool live in the server long term: soak, memory growth, idle cost, re-warm, cardlog-check on the serve jar? (G15) | R05's lifetime and idle policy | The M3 soak |
| Does a timed-out AI eval thread outlive its `join(2000)`? (v-r07) | The recycling rules | Log `t.isAlive()` after the join in the patch jar; count over M3/M5 |
| Do `cardlog-check`'s decks ever mulligan? (v-r04) | R04's safety check depends on it | Read the check decks and run `cardlog-check` once after WP-C |
| Is APC=2 deterministic on Rabbits v Vampires and Commander? (v-r01) | R01a's safety | Winners comparison inside M1 and M3 |
| Does the "in hand by round 3" per-card measure work on real logs? (G18) | R11's exposure change | M8 |
| Does throughput drift over 30+ minutes of sustained load? (c1) | Long replays (v2) | Track g/min drift during the M3 soak |
| Are games at home best of one or best of three? (G19) | Sideboards aren't simulated | Ask the owner (§9) |

---

## 8. Resolved in this pass

- **G1 (no report on disk).**
  - This report is rebuilt in full and corrected.
  - The finalising subagent's file write was refused, so the text is returned to be saved as `decklab/forge-trial/sim-investigation.md`.
- **G17 (Forge mulligans and land drops vs Deck Lab's goldfish).** Read-only over e4's 12,800 logs and the saved
  goldfish results (`f1-final/forge_mulligans.py`).
  - Mulligan rates match:

    | Deck | Forge | Goldfish |
    |---|---|---|
    | Izzet | 22.0 % | 22.2-22.4 % |
    | Gruul | 19.9 % | 19.7 % |
    | Rabbits | 21.3 % | 19.6-19.7 % |
    | Vampires | 16.6 % | 17.4-17.6 % |

  - Kept-hand sizes match to about 1 point.
  - Third and fourth land drops on time match for Gruul, Rabbits and Vampires. Izzet is ahead by 4-9 points: it
    runs 4 Preordain, and goldfish models no card draw.
  - **No mulligan or land-play misjudgement found.** Colour screw and Commander are not compared yet (M8).
- **G10, partly (which CCD is faster).** From `f1-final/ccd_split.py`:
  - In e4's shared queue, CCD0 workers played 21 % more games in equal busy time (7,005 vs 5,795).
  - CCD1's per-config medians are 4-47 % higher.
  - CCD1 workers used more CPU per game, which points at cache rather than clock speed (inference).
  - This agrees with e2 and e10. The cause is still unmeasured.
- **G13, partly (the production launch path).**
  - Production starts JVMs with the same `CREATE_NO_WINDOW` + suspended + job flags as the measured CLI runs.
  - The scheduled task runs in the interactive session (`InteractiveToken`) at priority 5 (normal).
  - Only EcoQoS for children of `pythonw.exe` is unchecked.
- **G16, partly (noise on the quick wins).**
  - The 800-game R01+R02 shape has three independent readings: 789 / 794 / 859 g/min (±4 %).
  - The per-timestamp re-split (§2.2) shows pinning adds ~0-2 % on cold short batches. That changed the plan:
    R01a now, R01b with R05.

---

## 9. Questions for the owner

1. **Best of one or best of three at home?** If best of three, simulate post-sideboard lists as separate variants per
   opponent (after R15) rather than using Forge's sideboarding, which is off.
2. **The "about even" margin and field weights.** Is ±5 points the right margin? Should the field average weight the
   house decks you actually face, or weight all decks equally?
3. **Auto-profile in v2:** "every game" (recommended, shown per deck) or "never"?
4. **Warm pool lifetime.** May the server keep a warm pool (13-16 GB) while idle, with an idle shutdown after, say,
   10-30 min? Should agent CLI runs submit to a running server, so a session reuses one warm pool?
5. **Lower priority.** Is it OK to run Forge at BELOW_NORMAL priority so the PC stays responsive? Runs slow down only
   when you are using the PC.
6. **After the one-time v2 bump,** should all still-current matchups be replayed (~30 min warm, ~60-90 min cold), or
   only on demand?

---

## 10. Corrections applied (phase-1 recommendations vs now)

| Rec | Phase-1 claim | After checking |
|---|---|---|
| R01 | Pinning + APC=2: +20 % (+29 % warm); start-up 5.2 → 3.4 s; fill CCD0 first | **Split.** APC=2 ships now: +10-15 % cold, and the start-up drop is APC=2's (3.4 s; 3.6 s with pinning). Pinning moves to the warm pool: ~0-2 % on cold short batches, +15-27 % warm (estimate). Missing risks added: collisions, topology, fallback, goldfish, Game Mode, effort 150-250 lines. No key change needed. |
| R02 | Every run gets all 16 workers; +31 % at 800 | The gain is mostly at 200 (~1.9x) and 400 (~1.6-1.9x) games. At 800: +10 % alone, +20-27 % with APC=2; the +31 % was a joint figure and the top of a 21-31 % range. Added a formula for any worker count, the full test list, and the parallel-CLI, CPU and memory risks (→ R18). |
| R03 | Lead verdict on decided games; ~29 % fewer games | Decided share only when there are no non-wins; otherwise keep `_comparison`. ~23 % fewer games. Added the precedence rule and the full file list. |
| R04 | +4-9 % | Throughput +4-9.5 % warm, +4.5-7 % cold for Izzet/Gruul-type decks; still unmeasured. Added the jar-check, coupling and check-deck risks. |
| R05 | 2.1-2.4x vs today; gauntlet 5-6 min | 1.73-1.85x over the quick wins once warm, ~1.0x fresh; RvV warmth +16 %. Gauntlet 5.5-7 min only with a persistent pool. Added the reset gaps, upgrade gate, stop flag, locks, memory and storage risks. The budget is split out as R18. |
| R06 | Key + one bump; small-medium effort; ~35 min replay | Medium effort. Per-side ids and consumer filtering; the fallback is keyed, not refused; v2 parity check; semantic hashing; 26-34 min warm / 60-90 min cold. |
| R07 | Raise the AI timeout to 30-60 s | **Dropped.** Recycling moves into R05. |
| R08 | +4-12 % | Warm only (+5-12 % IG, +4-5 % RvV); cold 3-9 % (estimate). Added the preferences-route check, the future-deck scan and the upgrade re-check. |
| R09 | Per-game seeds; R12/R13 need it | ~6 % fewer games typically. A new Match per game; per-pair seeds; key or refuse the fallback; recycle after clock stops. R12/R13 don't need it; R15 does. No current deck is affected by the auto-profile. |
| R10 | Override set; +2 points for Gruul; 3-8 points for Free Peoples | Fiery Annihilation only, after filtering: ~+1 point (unresolved). Free Peoples ~1-4 (estimate). The other sets are gated experiments, and 3 edits are flagged. |

---

## 11. Where the evidence is

All paths are under `decklab/forge-trial/sim-investigation/` (gitignored like the trial's other subfolders, so the data stays on
this PC).

**Measurements**
- `e1-baseline/`: the real CLI path at every size, Rabbits v Vampires, Commander, CCD/SMT packing.
- `e2-jvm/`: APC, AOT, affinity, K=32.
- `e3-profile/`: the warm pool, determinism, JFR, logging, PERFORMANCE_MODE.
- `e4-accuracy/`: mirrors, known ordering, profiles, the override, the mixed queue.

**Research**
- `r1-pipeline/`: pipeline, cold curve, tails, gauntlets.
- `r2-engine/`: threads, statics, the mulligan sleep, accuracy hazards.
- `r3-jvm/`: ergonomics, AOT, OS.
- `r4-ai/`: AI weak spots, overrides, prototypes.
- `r5-stats/`: statistics audit and designs.
- `r6-external/`: outside research.

**Synthesis and checks**
- `s1-synthesis/`: the synthesis and the mulligan-sleep count.
- `v-r01/` to `v-r10/`: skeptic checks.
- `c1-completeness/`: the gap list.
- `f1-final/`: this pass (`notes.md`, `forge_mulligans.py`, `ccd_split.py` and their outputs).

**Tools**
- `tools/cpusampler.py` (idle gate, sampler, topology) and `tools/batchtimes.py`.
