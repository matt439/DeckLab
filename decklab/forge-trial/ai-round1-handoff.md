# Forge AI round 1: handoff (2026-10-13)

> **Steps 0-6 ran on 2026-10-20/21:** the builds are merged and installed, and the experiments' results and recommendations are in [ai-round1-results.md](ai-round1-results.md). Step 7 (`etb-harmless-1` adopted for TFP, then the replay) and step 8 (clean-up) followed on 2026-10-21: round 1 is finished.

The Forge AI changes for round 1 are built, reviewed and tested on branches. Nothing is merged, nothing is installed, and no Forge games have been played. The rest needs Forge games, which wait until the PC is free (the owner said 2026-10-13: not for many days). Start a fresh thread from this file.

Files beside this one:
- [ai-round1-contract.md](ai-round1-contract.md): the build contract. It holds every interface and decision. §5 is the main-session runbook this file follows, and §6 the review responses.
- [ai-round1-specs.json](ai-round1-specs.json): the 7 experiment specs and the E5 decision-log config, one entry per file name. Write them out before use (step 0).
- [ai-round1-scout.json](ai-round1-scout.json): the scout's ranked candidates C1-C12 and the adversarial checks of C1-C4.

## Owner decisions (2026-10-13)

- Java AI fixes ship **off by default**, as per-id switches in the fork. A switch is turned on per deck list through its pilot in `decklab/simulation.json`, after a paired A/B test. Override sets are adopted in `overrides/sets.json` as before.
- Round 1 scope: C2 and C8 (override sets), C4, C5 and C6 (Java switches), and C9 (decision log).
- C6 (prowess first) is the lowest priority. The owner isn't sure Izzet Otters is meant to play prowess-first, so report its result but don't recommend adopting it unless the paired matchup is clearly better.
- C5 might be offered upstream to Card-Forge as a PR. **Ask Matt first**, once it has proved out.
- The Gisa/Bontu fix becomes a listed game patch (`gisa-bontu-1`): on by default, and off with `-Ddecklab.gamePatches=off`.
- The one-time engine re-key is accepted. Every saved result is already marked as an earlier engine, so it costs no extra replay.
- Forge games only when the PC is free, one run at a time in the main session. "Idle" matters for accuracy only loosely: the AI's 5-second decision limit can change a few games under heavy load. It matters for timing measurements, none of which happen here.

## What's built

**Fork: branch `ai-r1` at 52387e83f** (worktree `C:/VSProjects/forge-wt/ai-r1`; built on `ai-r1-base` with branches `ai-r1-c4`, `-c5`, `-c6` and `-c9`)

| Id | What it does with the switch on |
|---|---|
| `removal-in-combat-1` (C5) | Fixes Forge's inverted "remove a blocker to save my attacker" check (`ComputerUtilCard.useRemovalNow`), so removal is used after blocks on the AI's own turn. |
| `etb-harmless-1` (C4) | An optional ("up to one") target with nothing to aim at no longer stops the card being cast (`ChangeZoneAi`), and an untargeted DestroyAll rider with nothing to destroy no longer either (`DestroyAllAi`). Affects Fires of Mount Doom, Samwise the Stouthearted and Fiery Annihilation. |
| `prowess-precombat-1` (C6) | Casts cheap noncreature spells in main phase 1 when a creature that can attack has prowess or a "whenever you cast a noncreature spell" trigger. |
| `gisa-bontu-1` (game patch) | The old Gisa/Bontu fix, now gated: on by default, off with game patches off. |
| `-Ddecklab.decisionLog=<names>` (C9) | One `DLAI` line per AI decision about those cards: the card, turn, phase, decision and reason. |

- New classes: `GamePatches`, `AiSwitches`, `ProwessFirst` and `AiDecisionLog`. The jar lists its switches in `decklab/ai-switches.txt` and its game patches in `forge-patches.txt`.
- `install.py` now writes `res_sha256=`.
- Maven: 391 AI tests, 0 failures. That's 36 new ones; the baseline was 355.

**Deck Lab: branch `ai-r1` at 7f981f1** (worktree `C:/VSProjects/TCC-wt/ai-r1`; made from `ai-r1-found` and `ai-r1-overrides`)

- The engine key is now the release, the res hash and the game-patch ids (for example `2.0.15+res.1c22bab4dca8`). A fork commit whose new code is all off-by-default switches keeps the same engine, so it needs no replay.
- Switches are checked against what each build advertises (`pilots --check`). `Startup` installs `Pilots.forkOn` as the AI switches' hook.
- New commands:
  - `forge engine-check --old DIR --new DIR --pair A B ...` checks whether two installs play the same seeded games, line for line.
  - `forge decisions <logs>` reads the DLAI lines.
- New override sets (experiment status, not adopted):
  - `etb-tfp`: Fires, Éowyn, Samwise.
  - `etb-tfp-jailer`: Palace Jailer.
  - `cmdr-hints`: Primal Might, with `AILogic$ Fight` on the pump and `AILogic$ Always` on its fight. Puca's Mischief was dropped because the AI can't handle it safely.
- Docs: HISTORY ("AI fixes, round 1"), PLAN item 2, and an `engine-check` line in CLAUDE.md and AGENTS.md.
- Full suite: 3,966 tests. 9 failures and 2 errors, none from round 1:
  - 1 expected until `cardlog-check` runs (`CheckedSourceTests`).
  - 3 already failing on main.
  - The rest come from the worktree (the .venv launcher, a file in use, CRLF on `0001_foundation.sql`).

**Known caveats:**
- Samwise's `OptionalDecider$ You` override also makes the Ring's tempt optional, which isn't the real rules. Note this when reading E1.
- The experiments' evidence comes from old lists. TFP was at revision 2 then and is at revision 15 now.
- Most decks in the field are still idea decks. Check that the named cards are still in the lists before each experiment (`deck_line`).

## Steps for the next thread (in order, serially, PC free)

0. **Check the state.**
   - Both `ai-r1` branches are unchanged since the commits above: `git log -1 ai-r1` in both repos.
   - `main` and the fork's `decklab` haven't moved in conflicting ways. If they have, rebase or merge and rerun the tests.
   - Rebuild the scratch install, since the old one was in a session scratchpad:
     ```
     cd C:/VSProjects/forge-wt/ai-r1
     JAVA_HOME="C:/Program Files/Java/jdk-26.0.1" python decklab/install.py --out <scratch>/installs/ai-r1
     ```
     Expect `build=2.0.15-decklab-52387e83f` and `res_sha256=1c22bab4…`.
   - Write the specs out:
     ```
     python -c "import json;[open('<scratch>/specs/'+k,'w',encoding='utf-8').write(json.dumps(v,indent=2,ensure_ascii=False)) for k,v in json.load(open('decklab/forge-trial/ai-round1-specs.json',encoding='utf-8')).items()]"
     ```
   - `C:/VSProjects/TCC-wt/ai-r1/decklab/data` is a **junction** to main's data. Never delete through it: unlink it with `[IO.Directory]::Delete(path,$false)` before removing the worktree.
1. **Engine check**, from the TCC `ai-r1` worktree, with P = `--pair casual/izzet-prowess casual/the-free-peoples --pair commander/finneas-rabbits commander/gandalf-and-the-valley`. Contract §5.1 has the details.
   - **Noise floor first.** Each build must repeat its own games:
     - `engine-check --old C:/Tools/forge-decklab --new C:/Tools/forge-decklab P`
     - `engine-check --old <scratch install> --new <scratch install> P`
     - Accept exit 0, or exit 3 caused only by the Commander pair or time limits.
     - If a build doesn't repeat itself in Constructed, stop and rely on `cardlog-check`'s lists instead.
   - **Then** `engine-check --old C:/Tools/forge-decklab --new <scratch install> P`.
     - Expect "Different engine key", which is the accepted re-key.
     - Accept the same exits the noise floor gave.
     - Optionally repeat it with `--game-patches off`.
2. **Merge and install.** The TCC merge must come first: only it removes the duplicate `gisa-bontu-1` ids.
   - Throw away any stray edits in the main checkout, then merge TCC `ai-r1` into `main`.
   - In `C:/VSProjects/forge`, on `decklab` with a clean tree: `git merge --ff-only ai-r1`. Use `--ff-only` because a merge commit makes a new build name.
   - Run `python decklab/install.py`. Check that `C:/Tools/forge-decklab/decklab-build.txt` has the same `build=` as the scratch install.
   - Push the fork only if Matt asks.
3. **Real-Forge tests:** `DECKLAB_FORGE_TESTS=1 python -m unittest decklab.tests.test_forge_aipatches decklab.tests.test_forge_deckorder decklab.tests.test_forge_v2loop`.
   - `test_a_fork_switch_reaches_the_seat` is the only end-to-end check of the switch hook.
4. **Card-log check:** `python -m decklab.lib.forge cardlog-check`.
   - Then set `simjar.V` and `CHECKED_BUILDS` to the new build, and `CHECKED_SOURCE` to `simjar.source_sha256()`.
   - Run `test_forge_simjar` and commit on main.
   - Restart the server only if it's running.
5. **Baseline:** run each `field` with `--dry-run` first: `field casual/the-free-peoples`, `field casual/izzet-prowess`, `field commander/finneas-rabbits`, `field commander/gandalf-and-the-valley`.
   - About 11,200 games, 65-80 minutes.
   - This gives card data and the re-keyed field. It doesn't serve as the experiments' controls.
6. **Experiments**, one at a time, `--dry-run` first each time: `python -m decklab.lib.forge experiment <scratch>/specs/<file>`.

   | Spec | Tests | Games a pair |
   |---|---|---|
   | e1-ai-r1-etb-tfp | `etb-tfp`, `etb-tfp-jailer` on TFP vs Izzet and vs Gruul | 2,800 (controls 5,600) |
   | e2-ai-r1-cmdr-hints | `cmdr-hints`, Finneas vs Gandalf | 1,600 |
   | e3-ai-r1-removal-in-combat | `removal-in-combat-1` on TFP; reuses E1's controls | 1,600 |
   | e3m-…-mirror | the TFP mirror, side a | 3,200 |
   | e4-ai-r1-etb-harmless | `etb-harmless-1` on TFP, Gruul (a reference that should change nothing), and Izzet without the `fiery` override; reuses E1's controls | 2,800 |
   | e5-ai-r1-prowess | `prowess-precombat-1` on Izzet | 1,600 |
   | e5m-…-mirror | the Izzet mirror, side a | 3,200 |

   - E3 and E4 name E1's control folders, so E1 must run first. Check that E1's dry run prints the same paths.
   - E5 needs the decision log on:
     - Run it as `DECKLAB_CONFIG_EXTRA=<scratch>/specs/decision-log-e5.json python -m decklab.lib.forge experiment <scratch>/specs/e5-ai-r1-prowess.json --local`, in a fresh results folder.
     - Then run `forge decisions` on the arm's logs and on the control's.
   - Altogether that's several hours, which suits an overnight run.
7. **Report and adopt.** Report each experiment's recommendation to Matt. Adoption is his call: an override set's status in `sets.json`, or a switch in the list's pilot in `simulation.json`. Then run `replay --dry-run` and `replay` once.
   - If C4 wins, consider retiring the `fiery` and `etb` overrides it covers.
   - Ask about the upstream PR for C5.
8. **Clean up.**
   - Remove the worktrees `forge-wt/{base,c4,c5,c6,c9,ai-r1}` and `TCC-wt/{ai-r1-found,ai-r1-overrides,ai-r1}`. Unlink junctions first.
   - Delete the merged `ai-r1*` branches.
   - Update the `forge-ai-round1` memory.

Future fork builds whose changes are all off by default: build into scratch with `--out`, then `engine-check` against the installed build. Expect "Same engine key" and exit 0. Then `--ff-only` merge, install, `cardlog-check`, update the CHECKED constants. No replay (contract §5.8).

Not in round 1: C7 (flash), C10 (team pump in the fork), C11 (go-wide attacks) and C12 (upstream cherry-picks, deferred to the 2.0.16 rebase). The scout file ranks them.
