# Forge AI round 1: results (2026-10-21)

The measuring half of round 1 ([ai-round1-handoff.md](ai-round1-handoff.md) steps 0-6), run overnight on 2026-10-20/21. Every experiment's full report is in `decklab/data/forge/experiments/<name>/report.md` (gitignored). **Adopted 2026-10-21 (the owner's call):** `etb-harmless-1` in The Free Peoples' pilot (`decklab/simulation.json`), without the optional mirror run; nothing else. Then one `replay` (20 matchups, 23,280 games), plus `field` for TFP and Izzet, since `replay` didn't then pick up results re-keyed by a pilot change (fixed the same day, and 400 more games replayed); every current matchup is on today's engine since 2026-10-21, and the clean-up is done. Two reviewers checked this write-up against the raw reports, logs and specs; their corrections are in.

## What ran

| Step | Result |
|---|---|
| 0. State | Both `ai-r1` branches unchanged since 2026-10-13. Deck Lab's `ai-r1` was 180 commits behind `main`: merged in (conflicts only in AGENTS.md, CLAUDE.md and HISTORY.md, both sides kept). Scratch install `2.0.15-decklab-52387e83f`, `res_sha256=1c22bab4…`, as expected. The cards each experiment names are all still in today's lists, but not always in the same place: Fiery Annihilation is now in Gruul's main deck and only in Izzet's sideboard (see E4). |
| 1. Engine check | Noise floor: the installed build and the new one each repeat their own games (56 games, 4 pairs: cardlog-check's lists, Izzet Otters v The Free Peoples, Finneas v Gandalf). Then old against new: all 56 identical, "Different engine key" (`2.0.15-decklab-d84031a6d` to `2.0.15+res.1c22bab4dca8`, game patch `gisa-bontu-1` added), the accepted one-time re-key. |
| 2. Merge and install | `main` fast-forwarded to `ai-r1`; the fork's `decklab` fast-forwarded to `ai-r1` (52387e83f) and installed in `C:/Tools/forge-decklab`, same `build=` as the scratch install. |
| 3. Real-Forge tests | 23 pass, after three test-only fixes, none from round 1: `test_forge_v2loop`'s engine line didn't have wave 3's fields; `test_forge_deckorder` read the decks from files, so it couldn't run since the decks moved to the database (it now reads the `pre-db-decks` tag, like the other real-deck tests) and assumed Gruul had a 4-of. `test_a_fork_switch_reaches_the_seat` passes: a pilot's switch reaches its seat. |
| 4. Card-log check | Passed with `2.0.15-decklab-52387e83f`; `simjar.V` and `CHECKED_SOURCE` updated (696de78). |
| 5. Field baseline | The four fields, about 15,000 games (the fields have grown since the handoff's 11,200). The two Constructed fields took under 10 minutes each, the two Commander fields about 1.5 and 1.75 hours (their dry runs said 17-21 minutes). The first attempt was stopped at 687 games when the PC ran out of memory (another job held 30 GB); the rerun played only what was missing. Three Commander games' card logs failed their checks and carry no card data (Finneas game 466; Gandalf games 201 and 275, library counts off by one). |
| 6. Experiments | All seven, 00:34 to 02:50. E3 and E4 reused E1's controls, as planned. E2's first run stopped about 1,594 games into its control (reported as a failed run: the control wasn't played in full); a second run played the last 6 control games and the arm, in a pool of its own (it noted the server's pool plays with other settings). The arm has 1,587 paired games of 1,600, with no failed run reported for the 13 missing. |

**Bug found and fixed:** `experiment` saved its results in `decklab/data/forge/forge/experiments/<name>/` when no `--results-dir` was given, not the `decklab/data/forge/experiments/<name>/` its help, README.md and the wave 3 contract give. The round's specs name the documented folder for E1's controls, so every experiment was run with `--results-dir` there; the default is fixed, with a test.

## The results

Matchup differences are paired (the same game numbers and seeds as the control), for the list the arm changes, with 95 % ranges. "Cast" is the share of drawn copies cast; the "rise" is how much more often the card is cast at least once in a game.

| Exp | Arm (what it is) | Games a pair | Matchup (pooled) | Speed | Harness says | Recommendation |
|---|---|---|---|---|---|---|
| E1 | `etb-tfp` (C2: override set for Fires of Mount Doom, Éowyn, Samwise) | 2 × 2,800 | +0.6 [-0.3, +1.5]: v Izzet **+3.0**, v Gruul **-1.8** | 1.09x slower | don't adopt | **Don't adopt.** C4 below gets Fires and Samwise cast without the set, and without the loss against Gruul. The Samwise edit (`OptionalDecider$ You`) also makes the Ring's tempt optional, which isn't the real rules, so E1's Samwise numbers don't compare with C4's. The loss against Gruul is more likely Éowyn's edit (her win when held early -1.7 [-3.9, +0.5]) or Samwise's than Fires'. |
| E1 | `etb-tfp-jailer` (C2 plus Palace Jailer) | 2 × 2,800 | +0.7 [-0.3, +1.6]: v Izzet **+3.2**, v Gruul **-1.9** | 1.02x | don't adopt | **Don't adopt** (as above; Jailer itself moves little: cast 84 % to 90 % of drawn copies). |
| E2 | `cmdr-hints` (C8: Primal Might hints, Finneas) | 1,587 (of 1,600) | +0.3 [-0.4, +1.1] | 0.85x (faster) | more games | **Not yet.** Primal Might is cast far more (51 % to 90 % of drawn copies, its target 60 %), but the matchup doesn't move, and its win rate when held early may be lower (low end -10 pts). Worth more games only if Finneas's lists are settled. |
| E3 | `removal-in-combat-1` (C5, on TFP) | 2 × 1,600 | +0.0 [-0.1, +0.2] | 1.08x | more games | **Don't adopt; no upstream PR yet.** It almost never fires with these lists: Swords to Plowshares and Path to Exile are cast exactly as often as in the control, You Cannot Pass! 11.8 % against 11.9 %. |
| E3m | the same, TFP mirror | 3,200 | +0.0 [-0.1, +0.1]; mirror 50.3 % | 1.07x | more games | (as E3) |
| E4 | `etb-harmless-tfp` (switch `etb-harmless-1`, C4, on TFP) | 2 × 2,800 | **+2.1 [+1.4, +2.8]**: v Izzet **+2.7**, v Gruul **+1.5** | 0.87x (faster) | more games (no mirror pair) | **Adopt for TFP**, the round's one clear win, though against the harness's rule (see "To decide"). Fires is cast for 46 % of drawn copies (from 0 %), Samwise 99 % (from 40 %). Samwise is cast about 3.6 turns earlier, often as a bare body (the scout's worry), yet its win rates rise (+6.9 pts when held early, +4.5 when drawn), so the earlier casting doesn't seem to hurt. |
| E4 | `etb-harmless-ref` (C4, on Gruul) | 2 × 2,800 | +0.0 [-0.1, +0.1] | 0.96x | more games | The reference: Gruul's games don't change. |
| E4 | `etb-harmless-izzet-nofiery` (C4 on Izzet, the adopted `fiery` set dropped for everyone) | 3 × 2,800 | +0.5 [+0.2, +0.9] | 1.16x | evidence only | **Inconclusive: keep `fiery`, untested rather than disproved.** The arm meant to test whether C4 replaces `fiery` on Izzet, but Fiery Annihilation is now only in Izzet's sideboard and in Gruul's main deck. So the 33 % (from 94.5 %) it reports is Gruul's Fiery Annihilation with C4 off and no `fiery` edit, and Izzet v Gruul's +2.6 points for Izzet is Gruul getting weaker, not C4 helping Izzet. The clean test would be C4 on Gruul's pilot with `fiery` dropped (`replace_adopted`, keeping `remove`). |
| E5 | `prowess-precombat-1` (C6, on Izzet) | 2 × 1,600 | +0.3 [-0.4, +1.0] | 0.95x | more games | **Don't adopt** (the owner's rule for C6: only if clearly better). The decision log shows what it changes: about half of Pearl of Wisdom's casts move to the first main phase (437 of 879 and 496 of 860 precombat, from 109 and 120); Preordain was already always cast precombat; the burn spells barely change (Burst Lightning's precombat casts 149 and 115 to 168 and 125, its cast share the same), since C6 doesn't sequence burn (a known gap). |
| E5m | the same, Izzet mirror | 3,200 | +0.1 [-0.6, +0.8]; mirror 50.8 % | 0.83x | more games | (as E5) |

No experiment had AI timeouts in Constructed; E2 had 36 in its 1,587 arm games and 42 in its 1,600 control games (Commander's usual few).

## To decide

1. **Adopt C4 (`etb-harmless-1`) for The Free Peoples?** (Recommended.) It goes in TFP's pilot in `decklab/simulation.json`. The harness says "adopt" for a pilot arm only when a mirror pair's low end is above 50 %, and this round had no TFP mirror for C4. A TFP mirror (3,200 games a pair, 6,400 with its control, about 10 minutes) may not settle it either: the two 3,200-game mirrors this round had ranges of about ±1.7 points, so C4 would need about that edge in the mirror, and against other decks it gave +1.5 to +2.7. So it's either adopting on the paired matchups against the harness's rule, or a mirror run first that may still say "more games".
2. **Nothing to retire.** The handoff's step 7 suggests retiring the `fiery` and `etb` overrides if C4 wins, but `etb` was never adopted (it's an experiment set, like `etb-tfp`; only `fiery` and `remove` are adopted), and E4 couldn't test `fiery` (above), so it stays. With C4, Fires of Mount Doom and Samwise no longer need their overrides. Éowyn's and Palace Jailer's edits were only tested together with those in E1, where the set lost against Gruul, so they'd need an arm of their own, on top of C4, if they're wanted.
3. **C5 upstream PR:** not recommended yet. It had no measurable effect here, so there's no evidence to offer.
4. Then one `replay` (`python -m decklab.lib.forge replay --dry-run` first): today 20 matchups, 23,280 games, about 28 minutes, plus the TFP matchups re-keyed by an adoption.

For `FG#3` (the earlier backlog: team-pump fix, AI-profile arms, other override sets; PLAN.md) add, if wanted, Éowyn's and Jailer's edits on top of C4.

## Follow-up: the clean `fiery` test (2026-10-21, `FG#3`)

Gruul Ramp's two matchups (v The Free Peoples, v Izzet Otters), 2,800 games a pair against a fresh control (today's adopted pilots and overrides), 16,800 games in all, spec [fg3-gruul-nofiery-spec.json](fg3-gruul-nofiery-spec.json). No AI timeouts.

| Arm | Matchup for Gruul (pooled) | Fiery Annihilation cast (control 94.8 %) | Slowdown | Reading |
|---|---|---|---|---|
| `c4-nofiery`: `etb-harmless-1` on Gruul's pilot, the `fiery` override dropped (`replace_adopted`, keeping `remove`) | +0.0 [-0.1, +0.1] (+0.1 and +0.0 by pair) | 94.8 % | 0.92x | **C4 does what `fiery` does.** Every figure matches the control: the switch alone gets Fiery Annihilation cast as the edited script did. |
| `nofiery`: no switch, `fiery` dropped | **-1.4 [-2.0, -0.9]** (v Izzet -2.6, v TFP -0.3) | 33.3 % | 0.98x | Without either, the card is mostly left in hand again, and it wins 6.2 points less when held early. `fiery` is still needed while a pilot doesn't have C4. |

So the `fiery` override could be retired if every list holding Fiery Annihilation (Gruul's main deck, Izzet's sideboard) played with `etb-harmless-1`, but nothing would change in the games: it would only tidy the override list, and adopting C4 on those pilots re-keys their matchups, which then need a `replay`. Recommended: keep `fiery` as it is, and retire it only alongside another adoption that needs the same replay. **Decided (Matt, 2026-10-21): keep `fiery`.**

