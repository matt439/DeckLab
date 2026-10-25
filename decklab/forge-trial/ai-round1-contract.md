# AI round 1 (ai-r1): build contract

Written 2026-10-13 by the architect, from scout.json (C2-C9 and the verifications of C2, C3 and C4, whose
corrections win where they disagree) and the owner's decisions of 2026-10-13. Revised the same day after review (section 6). Every implementer reads
section 0 and their own package; nothing here is left for an implementer to decide. If the code isn't as
this contract describes (a line moved, a method renamed), adapt the location, keep the stated behaviour,
and say so in the commit message.

SCRATCH = `C:/Users/player/AppData/Local/Temp/claude/C--VSProjects-TradingCardCollection/864ecf08-cb1a-4da1-97db-08b7f369c91c/scratchpad/ai-r1`

---------------------------------------------------------------------------------------------------------

## 0. Rules for every package

1. The HARD RULES of the task apply. In particular no agent runs Forge games through Deck Lab: no
   `python -m decklab.lib.forge play|field|experiment|variant|replay|cardlog-check|serve-check|overnight|engine-check`,
   no goldfish, and never `DECKLAB_FORGE_TESTS=1`. `engine-check` (built here) runs games: implementers
   test it with the test suite's fake Forge only. Maven unit and scenario tests in the fork are allowed.
2. Only edit the files your package owns (section 2). Need a change in another package's file? Don't make
   it: write it in your final message as "REQUEST for <package>: ...".
3. Fork code style (the convention of commits d84031a6d and af513b9fd):
   - Mark every changed line of a Forge class with a trailing `// Deck Lab: <switch or patch id>` comment.
   - Prefer editing an existing line (append to it) over adding lines, so Forge's line numbers stay.
     New logic longer than one expression goes in a new class of your package.
   - Use fully qualified names (`forge.ai.AiSwitches.on(...)`) instead of adding import lines to
     Forge's classes. New classes may import freely.
   - Append a paragraph to the Deck Lab note at the end of each Forge file you change (start one, under
     the file's licence header, if it has none; copy the shape of the note at the end of
     `AiAttackController.java`): what changed, the id, that it plays Forge's own code with the switch off,
     why, and the test that proves it.
   - Checkstyle runs in Maven's validate phase with failOnViolation: keep it clean.
4. Deck Lab style: plain short sentences in docs and docstrings, the surrounding code's comment
   density, the standard library only.
5. Commits: clear messages, each ending with
   ```
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   Claude-Session: https://claude.ai/code/session_01BGqeAeXbh7m4BLcGhZM8rD
   ```
   Never push. Never touch TradingCardCollection's `main` or the fork's `decklab` branch.
6. Maven (fork packages), from your worktree's root, in Git Bash:
   ```
   export JAVA_HOME="C:/Program Files/Java/jdk-26.0.1"
   /c/Tools/maven/bin/mvn.cmd -B -o -pl forge-gui-desktop -am test \
       -Dtest="<TestClass>[,<TestClass>]" -Dsurefire.failIfNoSpecifiedTests=false
   ```
   Drop `-o` only if a dependency is missing from `~/.m2`. Never run `mvn install` (the parallel
   worktrees share `~/.m2`). The regression set is `-Dtest="forge/ai/**/*Test*"` (every test under
   `forge-gui-desktop/src/test/java/forge/ai`). The first build of a worktree compiles every module
   (expect 5-15 minutes). No Deck Lab work has run Forge's own AI tests on `decklab` before, so FF first
   records a **baseline** (FF step 0): `$SCRATCH/fork-baseline.txt`, the regression set's failing tests on
   an unmodified `decklab`. Every fork package's "the regression set passes" means **no failures beyond
   that baseline** (compare test class and method names). A package that starts after FF reads the file;
   if it's missing, the package stops and says so.
7. Deck Lab tests, from your worktree's root (AGENTS.md: a worktree has no `.venv`):
   ```
   C:/VSProjects/TradingCardCollection/.venv/Scripts/python -m unittest decklab.tests.<module> [...]
   ```
   If a test needs `decklab/data` (gitignored), make a directory junction to the main checkout's
   `decklab/data`, and before any cleanup remove the junction first with
   `[IO.Directory]::Delete("<worktree>\decklab\data", $false)`. Never delete through a junction.

---------------------------------------------------------------------------------------------------------

## 1. Decisions made in this contract

- D1. **Engine key** (owner decision 2): the engine description's `"forge"` field becomes the *engine
  release* (`install.engine_forge`, 3.6), worked out from the install folder:
  - no `decklab-build.txt` (stock Forge): the release from Forge's jar name (`2.0.15`);
  - `decklab-build.txt` with a `res_sha256=` line (a fork build from ai-r1 on): the release from its
    `base=` line (`forge-2.0.15` gives `2.0.15`; the jar name when there's no `base=`), plus
    `+res.<first 12 hex of res_sha256>`;
  - `decklab-build.txt` without a `res_sha256=` line (a fork build from before ai-r1, such as d84031a6d,
    whose Gisa/Bontu changes are ungated and play differently even with game patches off): its full
    `build=` name, so an old fork build keeps a per-commit key and never shares one with stock Forge;
  - `decklab-build.txt` that exists but can't be read: unknown (`None`). Never guessed from the jar name.
  The fork's commit no longer enters the key of a new build. `ID_VERSION` becomes 3. Two builds with the
  same base release, the same changed `forge-gui/res` files and the same game-patch ids share keys. The
  res hash closes the one channel the game-patch list can't see (card scripts and other res files the
  fork changes, like Gisa's and Bontu's). Taking the release from `base=` means a fork rebased onto a new
  BASE_TAG but installed with an old `--release` doesn't keep the old release's key (install.py always
  copies the built jar under the release's jar name). AI profiles are already keyed by `ai_sha`.
- D2. `install.forge_version()` (the build name, `2.0.15-decklab-<commit>`) is unchanged: cardlog-check,
  `CHECKED`, `checked.json`, the card-log jar's name, `REMEMBERED` and the pool's identity stay per build.
  Each new build still needs one cardlog-check (15 games), but no replay unless its key changed.
- D3. **Rule for the fork from now on:** a change that plays differently with every switch off must be a
  listed game patch with a new id (`forge-patches.txt`), gated by `forge.game.GamePatches.on()` so that
  `-Ddecklab.gamePatches=off` plays Forge's own code. A change that is off by default is an AI switch
  (`forge.ai.AiSwitches`, listed in `ai-switches.txt`). A switch's behaviour never changes once a build with
  it has been used: a change gets a new id (`-2`). Card-script edits for experiments go in Deck Lab's
  override sets, not the fork. `engine-check` verifies each new build against the installed one.
- D4. A class file carries at most one game-patch id in `forge-patches.txt` (the list maps class to id).
  Several classes may share one id. Deck Lab and GameLoop de-duplicate the ids.
- D5. **Gisa/Bontu** (owner decision 3) is game patch `gisa-bontu-1`, on by default. With
  `-Ddecklab.gamePatches=off` its Java paths play Forge's own code, and because the branch's scripts no
  longer say `AI:RemoveDeck:All`, `ComputerUtilCard.isCardRemAIDeck` treats Ghoulcaller Gisa and
  God-Eternal Bontu as removed from AI decks (the stock scripts' hint), so plain Forge never casts them,
  as stock Forge. The Gisa `AIPreference` SVar and Bontu's `AILogic$ SacToDraw` are only read on paths
  the gate closes, so the scripts stay as they are. `isCardRemAIDeck` isn't the only reader of the hint,
  so the same one-line gate (`|| forge.game.GamePatches.removedFromAiWhenOff(<rules>.getName())`, same id)
  also goes on the direct readers: `CardPredicates.isRemAIDeck` (forge-game, used by CopyPermanentAi),
  `PlayEffect.java` about :145, `CopyPermanentEffect.java` about :175 and `PlayerControllerAi.java` about
  :154 (sideboarding). Left open, stated in the end notes and HISTORY: `Deck.UnplayableAICards`
  (forge-core, which can't see `GamePatches`; it lists cards, it doesn't play them), and Deck Lab's own
  script readers (`ai.py` about :294, `install.py` about :297), which describe the build with game patches
  on, so they don't list Gisa or Bontu as "AI never casts" when a run has them off.
- D6. **Switch API**: `forge.ai.AiSwitches.on(Player, String)`, false unless a hook says true, and always
  false when `GamePatches.on()` is false. The hook is a `java.util.function.BiPredicate<Player, String>`,
  so Deck Lab plugs `Pilots::on` in by reflection and Deck Lab's Java still compiles and runs against older
  fork builds (d84031a6d has no `AiSwitches`): `engine-check` must play the old install with the new Deck
  Lab sources. Deck Lab's Java never names `forge.ai.AiSwitches` or `forge.game.GamePatches` directly.
  Deck Lab always installs the hook, so `Pilots.on` is on the hot path (every `castSpellInMain1` and
  declare-blockers `useRemovalNow` call): it returns false on one volatile read, before parsing any seat,
  unless the current request's pilots name a fork switch (3.5). The fork's own tests name their players
  `p1`/`p2`, which `Pilots.on` can't map to a seat, so they install their own hook (`DeckLabSwitchTest`).
- D7. **Switch ids** (all pre-registered by Foundation): `removal-in-combat-1` (C5), `etb-harmless-1`
  (C4), `prowess-precombat-1` (C6). The decision log (C9) is not a switch: it only prints.
- D8. Deck Lab validates switches in two steps: `decklab/simulation.json` and experiment specs may name
  Deck Lab's own switches and the fork switches Deck Lab knows (`pilots.FORK_SWITCHES`, a constant, so
  validation never reads a jar). A run refuses a switch the installed build doesn't advertise, or any fork
  switch while game patches are off (`pilots.check_switches`, which reads "off" from the setup's
  `game_patches` knob carried on the engine as `eng["game_patches_on"]`, not from an empty patch list).
- D9. **C4** drops the `AiController` 359-361 change (verification). The ChangeZoneAi change applies to an
  `AbilitySub` with `getMinTargets() == 0`, decided on the filtered list (it widens `doWithoutTarget`,
  which line 1145 and the target loop near 1231 both read). DestroyAllAi passes only when both the
  opponent's and the AI's filtered lists are empty and the ability is a trigger or a sub. In every new
  conjunction of every switch (C4, C5, C6) `forge.ai.AiSwitches.on(...)` comes first, so the off path runs
  no new Forge code at all (C5's `==` form runs only Forge's own turn test and the switch read).
- D10. **C5** flips interrupt 2's turn test only (no mirror case).
- D11. **C6** is one rule in `ComputerUtil.castSpellInMain1`, through a new class `forge.ai.ProwessFirst`:
  on the AI's own MAIN1, a noncreature, nonland spell of mana value 3 or less whose root API is Draw,
  Dig, Scry, Surveil or DealDamage counts as "cast in main 1" when the AI controls an untapped creature
  that can attack this turn and has prowess or a SpellCast trigger the spell satisfies. It reaches DrawAi
  and the other `castSpellInMain1` gates, and `ComputerUtilCard.useRemovalNow`'s line 1241 (burn at a
  creature in main 1). Burn at the face (DamageDealAi's own timing) is out of scope.
- D12. **C9** logs only the AI's priority choices in `chooseSpellAbilityToPlayFromList` (casts and
  activations), one `DLAI|` line per evaluated ability of a named card. Names are `;`-separated in the
  property, `%XX` (UTF-8) escaped by Deck Lab; `*` logs every card. Deck Lab turns it on with a config
  knob `forge_decision_log` (a list of card names, default `[]`), for `--local` runs; it isn't in the
  engine key (it changes no game) but is in the warm pool's launch identity. The fork reads the property
  once, when `AiDecisionLog` loads, so a JVM can't change its names: a new list needs a fresh launch
  (`--local`), which the README says.
- D13. **C2** sets: `etb-tfp` (Fires of Mount Doom's narrow ChompEquip edit, Éowyn BadETB, Samwise
  OptionalDecider) and `etb-tfp-jailer` (Palace Jailer BadETB), both `experiment`. Massacre Wurm and
  Théoden stay only in `etb`.
- D14. **C8** set `cmdr-hints` holds **Primal Might only** (`AILogic$ Fight` on its Pump). Checked in the
  source: PumpAi works X out with `setMaxXValue` (PumpAi.java:284-297), refuses X = 0 (:298), and with
  AILogic Fight sends the pump to `FightAi.canFight(ai, sa, attack, defense)` (:460-461), which finds the
  `DBFight` sub (TargetMin 0) by walking the subs (FightAi.java:182-186). **Puca's Mischief is dropped**:
  its trigger's root is an effect-less `DB$ Pump` targeting its own permanent, which PumpAi's targeting
  isn't built to choose for an exchange, and `ControlExchangeAi.chkDrawback` vets only the second target,
  so without the `RemoveDeck` hint the AI would cast a 4-mana enchantment whose trigger it can't use
  well, or swap the wrong permanent.
- D15. Override sets are experiments only: nothing is adopted, `simulation.json` is unchanged.
- D16. `engine-check` reports only (exit codes, an optional `--json` summary); it gates nothing.

---------------------------------------------------------------------------------------------------------

## 2. Packages, ownership, branches and order

| Package | Repo, branch, worktree | Starts | Owns (only these files) |
|---|---|---|---|
| **FF** Fork Foundation | fork, `ai-r1-base` from `decklab`, `C:/VSProjects/forge-wt/base` | at once | `forge-game/src/main/java/forge/game/GamePatches.java` (new); `forge-ai/src/main/java/forge/ai/AiSwitches.java` (new); `forge-ai/src/main/resources/decklab/ai-switches.txt` (new); `forge-game/src/main/resources/decklab/forge-patches.txt`; the gisa-bontu-1 gates in `forge-ai/.../ComputerUtil.java`, `ComputerUtilCard.java` (only `isCardRemAIDeck`), `ability/TokenAi.java`, `PlayerControllerAi.java` (only the sideboard line), `forge-game/.../card/CardPredicates.java` (only `isRemAIDeck`), `forge-game/.../ability/effects/PlayEffect.java` and `CopyPermanentEffect.java` (one line each); `decklab/install.py`; `$SCRATCH/fork-baseline.txt`; tests `forge-gui-desktop/src/test/java/forge/ai/DeckLabSwitchTest.java` (new base), `AiSwitchesTest.java`, `GisaBontuPatchTest.java` (new) |
| **DF** Deck Lab Foundation | TCC, `ai-r1-found` from `main`, `C:/VSProjects/TCC-wt/found` | at once | `decklab/lib/forge/`: `engine.py`, `install.py`, `simjar.py`, `pilots.py`, `runner_launch.py`, `pool.py` (LAUNCH_WORDS only), `cli.py`, `cli_checks.py`, `cli_commands.py` (pilots output only), `__init__.py` (docstring), new `cli_engine.py`, new `decisionlog.py`, `logreader.py` (only if DLAI lines need ignoring), `java/decklab/Pilots.java`, `Startup.java`, `GameLoop.java`; `decklab/lib/config.py` (one default); `decklab/README.md`; tests `decklab/tests/test_forge_engine.py`, `test_forge_models.py` (the pinned `id_version`), `test_forge_simjar.py`, `test_forge_pilots.py`, `test_forge.py`, `test_forge_contract.py`, `test_forge_cardlog_check.py`, new `test_forge_engine_check.py`, new `test_forge_decisionlog.py` |
| **OV** Overrides | TCC, `ai-r1-overrides` from `main`, `C:/VSProjects/TCC-wt/overrides` | at once | `decklab/lib/forge/overrides/sets.json`, `overrides/etb-tfp/`, `overrides/etb-tfp-jailer/`, `overrides/cmdr-hints/` (new folders), `overrides/README.md`, `decklab/tests/test_forge_overrides.py` (only if a test pins the set list) |
| **C5** | fork, `ai-r1-c5` from `ai-r1-base`, `C:/VSProjects/forge-wt/c5` | after FF | `forge-ai/.../ComputerUtilCard.java` (interrupt 2 and the end note); test `RemovalInCombatSwitchTest.java` |
| **C4** | fork, `ai-r1-c4`, `C:/VSProjects/forge-wt/c4` | after FF | `forge-ai/.../ability/ChangeZoneAi.java`, `ability/DestroyAllAi.java`; test `ability/EtbHarmlessSwitchTest.java` |
| **C9** | fork, `ai-r1-c9`, `C:/VSProjects/forge-wt/c9` | after FF | `forge-ai/.../AiController.java`, new `forge-ai/.../AiDecisionLog.java`; test `AiDecisionLogTest.java` |
| **C6** | fork, `ai-r1-c6`, `C:/VSProjects/forge-wt/c6` | after FF | `forge-ai/.../ComputerUtil.java` (`castSpellInMain1` and the end note), new `forge-ai/.../ProwessFirst.java`; the `prowess-precombat-1` line of `ai-switches.txt` (appending ` forge/ai/ProwessFirst.class`); test `ProwessPrecombatSwitchTest.java` |
| **INT** Integration | fork `ai-r1` from `ai-r1-base` at `C:/VSProjects/forge-wt/ai-r1`; TCC `ai-r1` from `main` at `C:/VSProjects/TCC-wt/ai-r1` | after all | merges only, plus `decklab/HISTORY.md`, `decklab/PLAN.md`, `CLAUDE.md` (one line) in TCC; if a switch package is dropped, its line in `ai-switches.txt` and its id in `pilots.FORK_SWITCHES` (and the tests and words naming it) |

(Fork test paths are under `forge-gui-desktop/src/test/java/forge/ai/`; `forge-ai/...` is
`forge-ai/src/main/java/forge/ai`.)

**Order.** FF, DF and OV run in parallel. C5, C4, C9 and C6 start once FF's last commit is on
`ai-r1-base` (FF's final message says "FF DONE <sha>"), and run in parallel with each other (their files
are disjoint; FF has finished its edits to ComputerUtil and ComputerUtilCard before they start). INT runs
last. Each package creates its own worktree:
```
git -C C:/VSProjects/forge worktree add C:/VSProjects/forge-wt/base -b ai-r1-base decklab
git -C C:/VSProjects/forge worktree add C:/VSProjects/forge-wt/c5 -b ai-r1-c5 ai-r1-base     # c4, c9, c6 alike
git -C C:/VSProjects/TradingCardCollection worktree add C:/VSProjects/TCC-wt/found -b ai-r1-found main
git -C C:/VSProjects/TradingCardCollection worktree add C:/VSProjects/TCC-wt/overrides -b ai-r1-overrides main
```
Leave your worktree in place when done (INT and the main session read them). Don't delete others'.

---------------------------------------------------------------------------------------------------------

## 3. Interfaces

### 3.1 `forge.game.GamePatches` (FF, forge-game)

```java
package forge.game;
public final class GamePatches {
    public static final String PROPERTY = "decklab.gamePatches";       // "off": Forge's own code
    public static final String GISA_BONTU_1 = "gisa-bontu-1";
    public static boolean on();                     // forTests if set, else !"off".equals(property read once at class load)
    public static void setForTests(Boolean on);     // null: back to the property (tests only)
    public static boolean removedFromAiWhenOff(String cardName);   // !on() && name is "Ghoulcaller Gisa" or "God-Eternal Bontu"
}
```
Match.java and AiAttackController.java keep their own `DECKLAB_*` finals (untouched).

### 3.2 `forge.ai.AiSwitches` (FF, forge-ai)

```java
package forge.ai;
public final class AiSwitches {
    public static final String REMOVAL_IN_COMBAT_1 = "removal-in-combat-1";
    public static final String ETB_HARMLESS_1 = "etb-harmless-1";
    public static final String PROWESS_PRECOMBAT_1 = "prowess-precombat-1";
    public static final String LIST = "decklab/ai-switches.txt";
    public static void setHook(java.util.function.BiPredicate<Player, String> hook);   // null: none
    public static boolean on(Player player, String id);
        // false if player == null, !GamePatches.on(), or no hook; else hook.test(player, id). One volatile read, no allocation.
    public static List<String> ids();   // the ids in LIST (first token of each non-comment line), sorted, distinct,
                                        // read once from AiSwitches.class's loader; empty if unreadable
}
```

`forge-ai/src/main/resources/decklab/ai-switches.txt` (exact content once C6 is merged; on `ai-r1-base`
the last line is `prowess-precombat-1 forge/ai/ComputerUtil.class`, because `ProwessFirst.class` doesn't
exist there and `AiSwitchesTest` checks that every listed class file is a resource):
```
# Deck Lab's AI switches in this Forge build (the fork's decklab branch), read by Deck Lab
# (simjar.FORK_SWITCH_LIST) and by forge.ai.AiSwitches.ids(). One switch a line:
# <id> <class file> [<class file>...]
# Each is off unless a seat's pilot names it (Deck Lab's -dlpilot), and always off with
# -Ddecklab.gamePatches=off. An id's behaviour never changes once a build with it has been used:
# a change gets a new id.
removal-in-combat-1 forge/ai/ComputerUtilCard.class
etb-harmless-1 forge/ai/ability/ChangeZoneAi.class forge/ai/ability/DestroyAllAi.class
prowess-precombat-1 forge/ai/ComputerUtil.class forge/ai/ProwessFirst.class
```

### 3.3 `forge-patches.txt` after FF (exact lines; keep its header, adding the D3/D4 rules in one or two comment lines)
```
forge/ai/AiAttackController.class attack-requirements-in-order-1
forge/ai/AiController.class -
forge/ai/AiDecisionLog.class -
forge/ai/AiSwitches.class -
forge/ai/ComputerUtil.class gisa-bontu-1
forge/ai/ComputerUtilCard.class gisa-bontu-1
forge/ai/PlayerControllerAi.class gisa-bontu-1
forge/ai/ProwessFirst.class -
forge/ai/ability/ChangeZoneAi.class -
forge/ai/ability/DestroyAllAi.class -
forge/ai/ability/TokenAi.class gisa-bontu-1
forge/game/GamePatches.class -
forge/game/Match.class deck-order-1
forge/game/ability/effects/CopyPermanentEffect.class gisa-bontu-1
forge/game/ability/effects/PlayEffect.class gisa-bontu-1
forge/game/card/CardPredicates.class gisa-bontu-1
forge/game/mulligan/AbstractMulligan.class -
```
(`AiDecisionLog` and `ProwessFirst` don't exist on `ai-r1-base` yet; a `-` line is never loaded.)
The build's game patches are then `attack-requirements-in-order-1, deck-order-1, gisa-bontu-1`.

### 3.4 The fork's `decklab/install.py` (FF)

After working out `changes = changed_res()` (every path under `forge-gui/res/` changed since BASE_TAG,
cards included), compute
```
res_sha256 = sha256 over, for each (path, keep) in sorted(changes.items()):
    f"{path}\0{sha256(file bytes with CRLF made LF).hexdigest() if keep else '-'}\n"   (UTF-8)
```
and write `res_sha256=<hex>` into `decklab-build.txt` (after `scripts_changed=`) when `changes` isn't
empty. Nothing else changes. Update the module docstring's `decklab-build.txt` line.

### 3.5 The hook from Deck Lab (DF, Java)

- `Startup.afterInitialize`, a new step 5 (always, whatever `decklab.gamePatches` says):
  `Class.forName("forge.ai.AiSwitches")`, then `getMethod("setHook", java.util.function.BiPredicate.class)`
  invoked with `(BiPredicate<Player, String>) Pilots::on`. `ReflectiveOperationException` (an older fork
  build): do nothing. Document it in the class comment.
- `Pilots`: keep `AVAILABLE` (Deck Lab's own ids; the test holds it equal to `simjar.PILOT_SWITCHES`).
  Add `static List<String> available()`: `AVAILABLE` plus `forge.ai.AiSwitches.ids()` read by reflection
  (none when the class is missing), sorted, distinct, computed once. `parse` checks ids against
  `available()`. Add a `static volatile boolean forkSwitches`, set when a request's pilots are applied
  (true when any seat's pilot names an id not in `AVAILABLE`, false otherwise, including for a request
  with no pilots). `Pilots.on` starts with `if (!forkSwitches) return false;`, before it parses the seat
  out of the player's name, so a request without fork switches costs one volatile read per call. Update
  the header comment.
- `GameLoop.gamePatchIds()`: collect ids in a `TreeSet` (distinct, sorted).

### 3.6 Deck Lab Python (DF)

`simjar.py`
- `FORK_SWITCH_LIST = "decklab/ai-switches.txt"`; `fork_switches(forge_jar)`: the ids in it, sorted
  (`[]` for a jar without the list or one that can't be read; cached by size and mtime like
  `forge_patches`; ids must match `runner.PILOT_SWITCH`'s form `[a-z0-9][a-z0-9-]{0,39}`).
- `_stamp` adds `"fork_switches": fork_switches(forge_jar)`. `card_log()` gives
  `"pilot_switches": sorted(set(pilot_switch_ids()) | set(fork_switches))` and
  `"game_patches": sorted(set(...values()))`.

`install.py`
- `release_of(jar_name)`: `JAR_RE`'s group (`"2.0.15"`); `None` for no match.
- `build_info(forge_dir)`: `decklab-build.txt` as a dict of its `key=value` lines; `{}` when the file is
  absent (stock Forge), `None` when it exists but can't be read. Cached by mtime and size.
- `engine_forge(forge_dir, jar_name)`: D1's rule. `info = build_info(forge_dir)`; `None` when `info` is
  `None`; `release_of(jar_name)` when `info == {}`; `info["build"]` (the full build name) when `info` has
  no `res_sha256`; else `f"{release}+res.{info['res_sha256'][:12]}"`, `release` being `info["base"]`
  without its `forge-` prefix, or `release_of(jar_name)` without `base`. `None` when a needed part is
  missing (no `build` and no `res_sha256` in a file that exists, or no release).
- `_setup(forge_dir=None, remember=True)` adds `"engine_forge"` and `"decision_log"` (see 3.8).
  `forge_dir` lets `engine-check` build a setup for another install folder (default: config's
  `forge_dir`). With `remember=False` it doesn't call `_remember_version` (which writes
  `DATA_DIR/forge-version.txt`, the fallback `forge_version()` reads), so a scratch install never becomes
  the remembered version.
- `_overrides_status`: its `pilot_switches` is `simjar.PILOT_SWITCHES` united with
  `simjar.fork_switches(<the card log's jar>)`, sorted, so the status and the page show the build's fork
  switches.

`engine.py`
- `ID_VERSION = 3`. `_engine(...)` takes the engine release for `"forge"`. `current(setup, card_log,
  remember=True)` uses `setup["engine_forge"]`. When it's `None` (or a setup lacks it), it uses the
  `"engine_forge"` remembered for this version and build; when none is remembered it raises ForgeError
  "Forge's decklab-build.txt can't be read and Deck Lab doesn't remember this build's engine, so this run
  wasn't started." It never cuts the build name. It sets two non-description fields:
  `eng["switches"]` = `card_log["pilot_switches"]` for the decklab kind, `[]` for plain, and
  `eng["game_patches_on"]` = `setup.get("game_patches") is not False`. With `remember=False` (engine-check)
  it doesn't call `_remember`, so `engine.json` gets no entry for a scratch build.
  `today()` works the engine release out with `install.engine_forge(forge_dir, jar)`; `_remember` notes it
  per version and build as `"engine_forge"`, and `today()` uses the remembered one when it's `None`;
  `complete` is False when neither is known.
- `_jar_patches`: distinct ids. Update the module docstring (the "forge" field, id_version 3).

`pilots.py`
- `FORK_SWITCHES = ("etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1")`.
- `SWITCH_WORDS` gains `"removal-in-combat-1": "combat-removal fix"`, `"etb-harmless-1": "optional-target
  fix"`, `"prowess-precombat-1": "prowess-first fix (experimental)"`.
- `available()["switches"]` = own (`simjar.PILOT_SWITCHES`) plus `FORK_SWITCHES`.
- `NEEDS_GAME_PATCHES = ("team-pump-1",) + FORK_SWITCHES`.
- `check_switches(eng, pilot)`: "game patches off" is `eng["game_patches_on"] is False` when the field is
  there, else (an engine from before this change) the present test `not eng.get("game_patches")`. As now
  for `NEEDS_GAME_PATCHES`, and, when `eng` has `"switches"`, a ValueError for a switch not in it:
  `"This Forge build doesn't have the {words} ({id}), so this run wasn't started."`

`cli_commands.py` `pilots`: after the switches line, say which fork switches the installed build has
(`simjar.fork_switches` of config's jar), or that it has none.

### 3.7 `engine-check` (DF, new `cli_engine.py`, registered in `cli.py`)

```
python -m decklab.lib.forge engine-check --old DIR [--new DIR] [--games N] [--commander-games N]
       [--pair DECK DECK]... [--switch ID]... [--game-patches on|off] [--seed N] [--json FILE]
```
- `--old` (required) and `--new` (default config's `forge_dir`): two Forge install folders.
- Lists: cardlog-check's Constructed and Commander lists (`cli_checks.CHECK_DECKS`,
  `CHECK_COMMANDER_DECKS`), plus each `--pair` (deck ids, `@owned` allowed, read as `play` reads them,
  both of one format). `--games` (default 25, at most `seeds.SEAT_BLOCK`) Constructed games per pair,
  `--commander-games` (default 3, same cap) per Commander pair. `--seed` (default `CHECK_SEED`).
- For each install: a setup (`install._setup(forge_dir=..., remember=False)`, its own AI profile mirror),
  the card log built with `simjar.card_log(..., checking=True)` (refuse with exit 2 when either can't be
  built or isn't a fork build), the key worked out with `engine.current(..., remember=False)`. Nothing it
  does writes `forge-version.txt` or `engine.json`. For each pair and install: one DeckLabSim process
  playing the v2 request for games 0..n-1 of the pair's stream, card log on, game patches on (or off with
  `--game-patches off`), pilots Default with `--switch` ids on both seats (refuse, exit 2, when either
  install lacks an id, and when `--switch` is given with `--game-patches off`). Reuse
  `cli_checks._check_run` and `_play_check_runs` (add a `pilots=None` parameter to `_check_run`, passed
  to `build_command`), slots and Ctrl+C as cardlog-check.
- Compare old and new line for line with `cli_checks._games_text(output, keep_card_log=True)`: a new
  keyword that keeps the card log's `DL|` lines. `_games_text` also drops `DLAI|` lines always.
- `--old` and `--new` may name the same folder: that's the noise-floor run (does a build repeat itself
  with these pairs?), and the report says "same install" instead of a key verdict.
- Verdict per pair: identical games of n, lines compared, the first difference. A Constructed difference
  fails. A Commander game that differs only in lines with the same winner, starter and length, or a game
  that hit a time limit (`TIME_LIMITS`), is "can't tell".
- It prints both installs' build, engine release (`"forge"`) and game-patch ids, and one of: "Same engine
  key: results saved with the old build stay current." or "Different engine key (<what differs>): saved
  results will be an earlier engine." When games differ but the keys are the same, it says: "Don't install
  this build as it is: it plays differently with its switches off."
- Exit 0 all identical, 1 a difference, 2 couldn't run, 3 only "can't tell". `--json FILE` writes
  `{"old": {build, forge, game_patches}, "new": {...}, "same_key", "pairs": [{"decks", "format", "games",
  "identical", "lines", "first_difference"}], "verdict"}`.

### 3.8 The decision log (C9 in the fork, DF in Deck Lab)

Fork (C9), `forge.ai.AiDecisionLog`:
- `PROPERTY = "decklab.decisionLog"`: names separated by `;`, each `%XX`-decoded as UTF-8 (only `%`
  escapes; `+` is literal), `*` for every card. Read once at class load; empty or absent: off.
  `static void setForTests(String spec)` (null: back to the property).
- `public static void spell(Player player, SpellAbility sa, AiPlayDecision opinion)`: returns at once
  when off (one static read). Else, when the host card's `getName()` or its paper card's name is listed,
  prints with `System.out.println` exactly:
  `DLAI|1|<turn>|<active seat>|<phase>|<seat>|<decision>|<api>|<card>`
  turn = `game.getPhaseHandler().getTurn()`; seats = the N of a player name `Ai(N)-...`, else `?`;
  phase = `PhaseType.name()` or `-`; decision = `opinion.name()`; api = `sa.getApi()` name or `-`;
  card = the host's `getName()` with `|`, CR and LF made `/`. Only getters: no randomness, no state change.
- `AiController.chooseSpellAbilityToPlayFromList`: on the line
  `AiPlayDecision opinion = useLivingEnd && ... : canPlayAndPayFor(sa);` (about :1665) append
  ` AiDecisionLog.spell(player, sa, opinion); // Deck Lab: -Ddecklab.decisionLog`.

Deck Lab (DF):
- `config.py` DEFAULTS: `"forge_decision_log": []`.
- `install._setup`: `setup["decision_log"]` = the list (ForgeError "config.json's forge_decision_log must
  be a list of card names." unless every item is a non-empty string; at most 50).
- `runner_launch._java`: when the card log is ready and the list isn't empty, append
  `-Ddecklab.decisionLog=<forge_name(n) each, quoted with urllib.parse.quote(n, safe=" !'(),-./:&?")
  (so non-ASCII, `%` and `;` are escaped), joined by ";">`.
- `engine.launch_fields` gains `"decision_log": sorted(list) or None`; `pool.LAUNCH_WORDS` gains
  `"decision_log": "the decision log (forge_decision_log)"`.
- `decisionlog.py`: `parse(line)` -> dict or None; `read(lines, names=None)` -> per game (games split at
  `Game Result: Game` lines; DLAI lines before a game's result line belong to it) `{card: {"opportunities",
  "taken", "declined": {decision: n}, "by_phase": {phase: {"opportunities", "taken"}}, "by_seat": {seat:
  {"opportunities", "taken"}}}}`; `read_folder(folder, names=None, games=None)` for a tee folder
  (`<first>-<last>.log.gz`, `experiment_logs.LOG_NAME`, g = first + index). An **opportunity** is a
  distinct (turn, phase, seat, card) with at least one decision other than `CantPlaySa`, `CantAfford`,
  `CantAffordX` and `TimingRestrictions` (which `canPlaySa` gives a sorcery-speed card in every step that
  isn't a main phase, AiController.java:879-881); it's **taken** when one of its decisions is willing
  (`WillPlay`, `MandatoryPlay`, `PlayToEmptyHand`, `AddBoardPresence`, `ImpactCombat`,
  `ResponseToStackResolve`, `Removal`, `Tempo`, `CardAdvantage`), else **declined** under its last
  decision. An opportunity doesn't mean the AI could pay: `CantAfford` comes only after `canPlaySa` said
  yes (AiController.java:849-860), so a card it can't pay for usually shows its API's refusal (such as
  `CantPlayAi` or `MissingPhaseRestrictions`). Instants are evaluated in every priority window, so compare
  per phase, not only per game. The docstring and README say both.
- Known limits, in the docstring and README: a mirror (both seats one list) can't be split by card name,
  so `decisions` reports per seat and the reader must not read a side into it (E5m is judged on the
  matchup only); a `DLAI|` line is printed from the AI's evaluation thread, which keeps running after an
  AI timeout, so after a timeout a line can land in the next game (rare; counted as is).
- `python -m decklab.lib.forge decisions FOLDER [--card NAME]... [--json]` (in `cli_engine.py`): per card,
  games with an opportunity, opportunities, taken, the declined reasons, most common first, and the
  opportunities and taken per phase and per seat.
- Usage (README): a JSON file `{"forge_decision_log": ["Pearl of Wisdom"]}` named by `DECKLAB_CONFIG_EXTRA`
  for the whole command, with `--local` (the server's warm pool doesn't have the knob, and the fork reads
  the names once per JVM, so each new list needs a fresh launch).

---------------------------------------------------------------------------------------------------------

## 4. Per package

### FF (Fork Foundation)

0. **Baseline first**, in the new worktree before any edit (it's `decklab` exactly): run the regression
   set (rule 6) and write `$SCRATCH/fork-baseline.txt`: the date, the commit, the Maven command, and one
   line per failing or erroring test (`<class>#<method>`), or `none`. Commit nothing for it. If the build
   itself fails on `decklab`, stop and report (every fork package would be blocked).
1. Add `GamePatches`, `AiSwitches`, `ai-switches.txt` (with the `ai-r1-base` form of its last line, 3.2)
   and the `forge-patches.txt` lines as in 3.1-3.3.
2. Gate `gisa-bontu-1` (each a one-line edit with `// Deck Lab: gisa-bontu-1`, and end notes):
   - `TokenAi.java` (about :88): `if (amountCountsSacrificed(sa, tokenAmount))` becomes
     `if (forge.game.GamePatches.on() && amountCountsSacrificed(sa, tokenAmount))`.
   - `ComputerUtil.java` (about :839): `} else if ("SacToDraw".equals(source.getParam("AILogic")) && isOptional) {`
     gains `forge.game.GamePatches.on() &&` first.
   - `ComputerUtilCard.isCardRemAIDeck` (about :2290): `|| forge.game.GamePatches.removedFromAiWhenOff(card.getRules().getName())`
     inside the existing null guard.
   - The direct readers of D5, each one `|| forge.game.GamePatches.removedFromAiWhenOff(<the rules
     object>.getName())` appended to the existing `getRemAIDecks()` test, inside its null guard:
     `CardPredicates.isRemAIDeck` (about :270), `PlayEffect.java` (about :145), `CopyPermanentEffect.java`
     (about :175), `PlayerControllerAi.java` (about :154, `cSide.getRules()`).
   - The end notes (and GamePatches' class comment) state D5's open gap: `Deck.UnplayableAICards`.
3. `decklab/install.py`: `res_sha256` (3.4).
4. Tests (TestNG, extending `AITest` like `DestroyAiTest`):
   - `DeckLabSwitchTest` (abstract base, no tests): `switchOn(Player p, String... ids)` sets the hook to
     `(pl, id) -> pl == p && ids contains id`; `gamePatchesOff()`; `@AfterMethod` resets the hook and
     `GamePatches.setForTests(null)`. Its comment says why it installs its own hook: these tests' players
     are `p1`/`p2`, which Deck Lab's `Pilots.on` can't map to a seat.
   - `AiSwitchesTest`: off with no hook; on only for the seat and id the hook names; off for everyone when
     game patches are off even with the hook; `ids()` is exactly the three ids of D7; every class file
     listed in `ai-switches.txt` is a resource on `AiSwitches.class.getClassLoader()` (so the list can't
     advertise a switch whose class isn't in the build).
   - `GisaBontuPatchTest` (extends `DeckLabSwitchTest`), each case run with patches on and with
     `gamePatchesOff()`:
     - `isCardRemAIDeck` and `CardPredicates.isRemAIDeck()` are false for Ghoulcaller Gisa and God-Eternal
       Bontu with patches on, true with them off, and false for Grizzly Bears both ways.
     - **TokenAi gate:** Gisa on the AI's battlefield, untapped and not sick, with a Swamp untapped and
       another creature of power 2 or more (a 3/3 such as Hill Giant), the AI's MAIN1 (or the phase
       TokenAi's `checkPhaseRestrictions` wants; say which in the test). For her activated ability `sa`
       (`setActivatingPlayer(ai)`): `SpellApiToAi.Converter.get(sa).canPlayWithSubs(ai, sa).willingToPlay()`
       is true with patches on and false with them off (X works out to 0 before the cost is paid,
       TokenAi.java about :88).
     - **Cast:** Gisa in hand, enough untapped mana for her in MAIN1, nothing else castable. `aic.chooseSpellAbilityToPlay()`
       (public, AiController.java:1351; it reaches the RemAIDeck filter at :1565-1569, which
       `aic.canPlaySa` never does) returns her spell with patches on, and doesn't (null or empty) with
       them off.
     - **Bontu:** Bontu's SacToDraw choice (`ComputerUtil.choosePermanentsToSacrifice` or the method
       af513b9fd hooks, with an optional amount) keeps the lands the hand needs with patches on, and with
       them off takes Forge's default path (assert the two results differ on a board where they must).
5. Run `-Dtest="AiSwitchesTest,GisaBontuPatchTest"`, then the regression set.
6. Final message: "FF DONE <sha of ai-r1-base>", and the baseline's failures.

Acceptance: compiles; checkstyle clean; the new tests pass; the regression set has no failures beyond the
baseline; `forge-patches.txt` and `ai-switches.txt` exactly as in 3.2-3.3; `git diff decklab..ai-r1-base`
touches only FF's files.

### C5: `removal-in-combat-1`

- `ComputerUtilCard.useRemovalNow`, interrupt 2 (about :1262):
  `if (ph.is(PhaseType.COMBAT_DECLARE_BLOCKERS) && !ph.isPlayerTurn(ai)) {` becomes
  `if (ph.is(PhaseType.COMBAT_DECLARE_BLOCKERS) && ph.isPlayerTurn(ai) == forge.ai.AiSwitches.on(ai, forge.ai.AiSwitches.REMOVAL_IN_COMBAT_1)) { // Deck Lab: removal-in-combat-1 (Forge's own: !isPlayerTurn)`.
  Off, it is Forge's test exactly. On, it fires on the AI's own turn, when an opponent's blocker `c`
  would destroy the AI's attacker and removing it saves the attacker.
- `RemovalInCombatSwitchTest` (extends `DeckLabSwitchTest`): one board in COMBAT_DECLARE_BLOCKERS on the
  AI's turn: the AI's attacker blocked by an opponent's creature that kills it and that the AI's removal
  (Murder) can kill; `ComputerUtilCard.useRemovalNow(murderSa, blocker, 0, ZoneType.Graveyard)` is false
  with the switch off and true with it on. Pick the board so that off is false (the later threat
  checks multiply by 0.1 after blockers); say in the test why. Set `murderSa.setActivatingPlayer(ai)`
  (useRemovalNow reads `sa.getActivatingPlayer()` first, ComputerUtilCard.java about :1227) and put the
  combat in place with `game.getPhaseHandler().setCombat(...)`, as `CountersPutAiTest` does. A second
  case: on the opponent's turn with the switch on, the result equals the switch-off result.
- Maven: `-Dtest=RemovalInCombatSwitchTest`, then the regression set (no failures beyond the baseline).

### C4: `etb-harmless-1`

- `ChangeZoneAi.java` about :1141-1143: on the third line, insert before its closing `;`:
  ` || (forge.ai.AiSwitches.on(ai, forge.ai.AiSwitches.ETB_HARMLESS_1) && sa instanceof AbilitySub && sa.usesTargeting() && sa.getMinTargets() == 0)`
  and put ` // Deck Lab: etb-harmless-1` after the `;` (never before it: the comment would swallow the
  semicolon). AbilitySub is already imported; use the method's player variable. Line 1145's veto and the
  target loop's `doWithoutTarget` (about :1231) then pass an empty filtered list for such a sub.
- `DestroyAllAi.doMassRemovalLogic` about :76-77: inside `if (opplist.isEmpty()) {` the return becomes
  `return forge.ai.AiSwitches.on(ai, forge.ai.AiSwitches.ETB_HARMLESS_1) && ailist.isEmpty() && (sa.isTrigger() || sa instanceof forge.game.spellability.AbilitySub) ? new AiAbilityDecision(100, AiPlayDecision.WillPlay) : new AiAbilityDecision(0, AiPlayDecision.CantPlayAi); // Deck Lab: etb-harmless-1`.
- No AiController change.
- `ability/EtbHarmlessSwitchTest`: with the switch off then on, through `aic.canPlaySa` on each spell:
  - Samwise the Stouthearted in hand, nothing in the graveyard: off `BadEtbEffects`, on not `BadEtbEffects`.
  - Fiery Annihilation with an opposing creature it kills and no Equipment: off not willing, on willing.
  - Fires of Mount Doom with an opposing creature its 2 damage kills (toughness 2 or less, such as
    Grizzly Bears, so DealDamageAi accepts the root trigger) and no Equipment: off `BadEtbEffects`, on not.
  - Unchanged with the switch on: Day of Judgment with both boards empty stays not willing;
    Éowyn, Fearless Knight with no opposing creature stays `BadEtbEffects`.
- Maven: `-Dtest=EtbHarmlessSwitchTest`, then the regression set (no failures beyond the baseline).

### C9: the decision log

- `AiDecisionLog` and the AiController line as in 3.8, plus an end-note paragraph.
- `AiDecisionLogTest` (extends `AITest`): capture `System.out`; with no names nothing is printed by
  `aic.chooseSpellAbilityToPlay()` (or the public method that reaches `chooseSpellAbilityToPlayFromList`)
  in MAIN1 with Grizzly Bears and Forests; with `setForTests("Grizzly Bears")` a `DLAI|1|` line naming
  Grizzly Bears with a decision is printed; the chosen ability is the same with and without the log;
  `%C3%89owyn, Fearless Knight` decodes to `Éowyn, Fearless Knight`; `*` logs every card.
- Maven: `-Dtest=AiDecisionLogTest`, then the regression set (no failures beyond the baseline).

### C6: `prowess-precombat-1`

- New `forge.ai.ProwessFirst.castNow(Player ai, SpellAbility sa)` with D11's rule: false unless
  `AiSwitches.on(ai, PROWESS_PRECOMBAT_1)` (tested first, before any other check); host not a creature or land, `sa.isSpell()`, mana value 3 or
  less, root API in {Draw, Dig, Scry, Surveil, DealDamage}; the AI's turn and `PhaseType.MAIN1`; some
  creature of the AI's that is untapped and `CombatUtil.canAttack(c)` and either has `Keyword.PROWESS` or
  a trigger of mode `TriggerType.SpellCast` whose `ValidCard` the host is valid for.
- `ComputerUtil.castSpellInMain1` (about :1361): `if (source != null && "ALWAYS".equals(source.getSVar("PlayMain1"))) {`
  becomes `if (source != null && ("ALWAYS".equals(source.getSVar("PlayMain1")) || ProwessFirst.castNow(ai, sa))) { // Deck Lab: prowess-precombat-1`.
- `ai-switches.txt`: append ` forge/ai/ProwessFirst.class` to the `prowess-precombat-1` line (3.2's final
  form); `AiSwitchesTest` then checks the new class file too.
- `ProwessPrecombatSwitchTest`: Monastery Swiftspear untapped and not sick (set its sickness off
  explicitly), Divination in hand, lands, the
  AI's MAIN1: `ComputerUtil.castSpellInMain1` false off and true on; DrawAi's `canPlayWithSubs` on
  Divination not willing off and willing on. With the switch on: false for a tapped Swiftspear, for a
  creature spell (Grizzly Bears) and on the opponent's turn; and in the AI's MAIN2 the answer is the
  same with the switch on as off.
- Maven: `-Dtest=ProwessPrecombatSwitchTest,AiSwitchesTest`, then the regression set (no failures beyond
  the baseline).

### DF (Deck Lab Foundation)

Build 3.5-3.8. Docs (README, "Deck Lab's own Forge" and "AI fixes"): the engine release key and why
(a default-off build keeps results current), `gisa-bontu-1`, the AI switches and their words, adopting a
switch per list in `simulation.json`, the new "Changing Deck Lab's Forge" steps (commit with tests; build
into a scratch folder with `install.py --out`; `engine-check --old C:/Tools/forge-decklab --new <that>`,
with a same-install noise-floor run the first time a pair is used; merge with `--ff-only` on a clean
tree; install and confirm the build name; `cardlog-check`; the CHECKED constants), the D5 gap, the decision log with its `DECKLAB_CONFIG_EXTRA` and
`--local` usage, `decisions`, and the experiment sets `etb-tfp`, `etb-tfp-jailer` and `cmdr-hints` in the
AI-fixes list. `__init__.py`'s command list gets `engine-check` and `decisions`.

Before starting, grep every `decklab/tests/test_forge*.py` for `id_version`, `ID_VERSION` and pinned
`"forge":` values (today `test_forge_engine.py` :85 and :778-780, and `test_forge_models.py` :163, which
pins `"id_version": 2` in the description `KeyTests.test_key_is_the_contract_sha` hashes; update it to 3
and its expected SHA). `test_forge_simjar.py` and `test_forge_deckorder.py` touch the same code without
pinning the literal; if either needs a change, it's DF's to make (say so in the commit).

Tests (with the existing fakes; no real games):
- `test_forge_engine.py`: id_version 3; builds `2.0.15-decklab-aaa` and `-bbb` with the same base,
  `res_sha256` and game patches give the same key; a different `res_sha256` or game patch gives a different
  key; a stock jar (no `decklab-build.txt`) gives `"forge": "2.0.15"`; a `decklab-build.txt` without
  `res_sha256=` gives the full build name, so it never equals stock's; `base=forge-2.0.16` with a
  `2.0.15` jar name gives `2.0.16+res.…`; the engine release is remembered when `decklab-build.txt` can't
  be read, and `current()` raises ForgeError when it can't be read and nothing is remembered (never the
  cut version); `current(..., remember=False)` and `_setup(..., remember=False)` write neither
  `engine.json` nor `forge-version.txt`; `eng["game_patches_on"]` follows the setup's knob; a fork switch
  enters a side only through its pilot; the key test updates for the field.
- `test_forge_models.py`: the pinned description and SHA updated for id_version 3.
- `test_forge_simjar.py`: `fork_switches`; `card_log()`'s `pilot_switches` with and without the fork list;
  duplicate game-patch ids collapse. A test that reads `${DECKLAB_FORGE_FORK}/forge-ai/src/main/resources/decklab/ai-switches.txt`
  (skip when absent) and holds its ids equal to `pilots.FORK_SWITCHES`.
- `test_forge_simjar.py` also: `install._overrides_status` lists the fork switches of the card log's jar.
- `test_forge_pilots.py`: simulation.json accepts the fork ids; `check_switches` refuses an id the engine
  lacks and any fork switch with `game_patches_on` False, and accepts a fork switch on an engine whose
  game-patch list is empty but `game_patches_on` is True.
- `test_forge_engine_check.py`: with the fake Forge, identical outputs exit 0; a changed Constructed line
  exits 1 and names it; Commander games that differ only in lines with the same winners, starters and
  lengths, or a game that hit a time limit, exit 3; same versus different keys are reported; `--old` equal
  to `--new` reports "same install"; `--switch` an install lacks exits 2; `--switch` with
  `--game-patches off` exits 2; the run writes neither `forge-version.txt` nor `engine.json`.
- `test_forge_decisionlog.py`: `parse`; game assignment; opportunities, taken and declined;
  `TimingRestrictions`-only windows aren't opportunities; per-phase and per-seat counts; a gz tee
  folder; `_java` adds the flag only with the card log ready and names given, escaped; `launch_fields`
  carries the list; LogReader and `_games_text` ignore DLAI lines.
- Also compile Deck Lab's Java against the installed (old) fork jar, no games:
  `javac -cp "C:/Tools/forge-decklab/forge-gui-desktop-2.0.15-jar-with-dependencies.jar" -d $SCRATCH/javac-found decklab/lib/forge/java/decklab/*.java`.
- Run every `decklab.tests.test_forge*` module. `CheckedSourceTests.test_checked_source_is_the_source_in_the_repo`
  is expected to fail (the Java sources changed; the main session runs cardlog-check and updates
  `CHECKED_SOURCE`). Every other test passes.

Acceptance: the above; `python -m decklab.lib.forge pilots --check` exits 0 in the worktree (read-only);
`engine-check --help` and `decisions --help` work; no test plays real games.

### OV (Overrides)

- `sets.json`, three new `experiment` sets (`"why"` in plain words, citing scout C2/C8 and D13/D14):
  - `etb-tfp`: files `fires_of_mount_doom.txt`, `eowyn_fearless_knight.txt`,
    `samwise_the_stouthearted.txt`, each with exactly the `etb` set's edit for that file and
    `cast_target` null. The why says Samwise's OptionalDecider also makes the Ring tempt optional.
  - `etb-tfp-jailer`: `palace_jailer.txt` with the `etb` edit.
  - `cmdr-hints`: `primal_might.txt`, card `Primal Might`, edit
    `["NumDef$ +X | SubAbility$ DBFight", "NumDef$ +X | AILogic$ Fight | SubAbility$ DBFight"]`,
    `cast_target` 0.6. The why records that Puca's Mischief was checked and dropped (D14).
  - Fill `upstream_sha256` and the files with three runs, one set each (`--set` takes one name,
    cli_commands.py :317 and :337):
    `python -m decklab.lib.forge overrides make --set etb-tfp`, then `--set etb-tfp-jailer`, then
    `--set cmdr-hints` (each reads the installed Forge's `cardsfolder.zip`; nothing plays). Write the new
    entries with `"upstream_sha256": ""` first, which the loader accepts (overrides.py about :196). If
    make still refuses an entry, copy the `etb` set's SHA for the shared files and compute Primal Might's
    from `p/primal_might.txt` in `C:/Tools/forge-decklab/res/cardsfolder/cardsfolder.zip`.
- `overrides/README.md`: one short paragraph listing which sets are TFP- or Commander-scoped experiments.
- Run `python -m decklab.lib.forge overrides check` (exit 0) and `decklab.tests.test_forge_overrides`.

Acceptance: `overrides check` clean; tests pass; adopted sets and `simulation.json` unchanged.

### INT (Integration)

1. Fork: worktree `C:/VSProjects/forge-wt/ai-r1`, branch `ai-r1` from `ai-r1-base`; `git merge --no-ff`
   `ai-r1-c5`, `ai-r1-c4`, `ai-r1-c9`, `ai-r1-c6` (no conflicts expected). Merge only a package whose final
   message says its tests passed. Run all six new test classes and the regression set (no failures
   beyond the baseline). Check every id in `ai-switches.txt` is implemented: for each id,
   `git grep -n "Deck Lab: <id>"` finds it in each listed class's source, and the line's class files
   exist (AiSwitchesTest). If a package was dropped, remove its line from `ai-switches.txt` here, and its id
   from `pilots.FORK_SWITCHES`, `SWITCH_WORDS` and the tests naming it in TCC's `ai-r1` (step 2), and say so.
   Build a scratch install (allowed by this contract), in Git Bash with
   `export JAVA_HOME="C:/Program Files/Java/jdk-26.0.1"` first (install.py calls mvn without setting it):
   `python decklab/install.py --release C:/Tools/forge --out $SCRATCH/installs/ai-r1`. Check its
   `decklab-build.txt` has `res_sha256=`, and that its jar holds `decklab/ai-switches.txt` (with the ids
   kept) and lists `gisa-bontu-1` (unzip -l / read the zip; no games). Note its `build=`.
2. TCC: worktree `C:/VSProjects/TCC-wt/ai-r1`, branch `ai-r1` from `main`; merge `ai-r1-found` and
   `ai-r1-overrides`; run every `test_forge*` module with `DECKLAB_FORGE_FORK=C:/VSProjects/forge-wt/ai-r1`
   set (otherwise the test holding `pilots.FORK_SWITCHES` equal to `ai-switches.txt` reads the default
   `C:/VSProjects/forge`, which is on `decklab` and has no list, and skips silently; confirm it ran). Only
   `CheckedSourceTests` may fail. Compile Deck Lab's Java against both jars (old `C:/Tools/forge-decklab`,
   new `$SCRATCH/installs/ai-r1`) with `javac` into scratch folders.
3. Docs in TCC `ai-r1`:
   - `decklab/HISTORY.md`: a dated entry "AI fixes, round 1" (built, not yet measured): the owner's
     decisions, the engine key change and why, `gisa-bontu-1`, the three switches and the decision log
     with their tests, the three override sets (and Puca's Mischief dropped), `engine-check` and
     `decisions`, and "Known low issues, left open": burn at the face isn't sequenced by C6; the
     decision log needs `--local`; C5 has no mirror case; Massacre Wurm and Sunblast Angel aren't covered
     by C4; with game patches off, `Deck.UnplayableAICards` and Deck Lab's own script readers still see
     Gisa's and Bontu's branch scripts (D5); the decision log can't split a mirror's sides and can put a
     line in the next game after an AI timeout; the regression set's baseline failures (if any).
   - `decklab/PLAN.md` item 2 and its Details bullet: replace with the round 1 measuring queue of
     section 5 (engine-check with its noise floor, install, the real-Forge tests, cardlog-check, the field
     baseline, then E1-E5), still to run on an idle PC.
   - `CLAUDE.md`: in the Layout comment for `lib/`, one added line naming `python -m decklab.lib.forge
     engine-check --old <dir> --new <dir>` (a new fork build against the installed one).
4. Commit on both `ai-r1` branches. Final message: both branch heads, the scratch install's build name,
   and test results.

Acceptance: both integration branches build and pass their tests (bar the one expected failure); the
scratch install exists; nothing installed in `C:/Tools`.

---------------------------------------------------------------------------------------------------------

## 5. What the MAIN SESSION does afterwards (serially, idle PC for games)

1. Review INT's branches. From `C:/VSProjects/TCC-wt/ai-r1` (junction its `decklab/data` to main's first;
   engine-check writes nothing in it, 3.7). Let P = `--pair casual/izzet-prowess casual/the-free-peoples --pair commander/finneas-rabbits commander/gandalf-and-the-valley`.
   - **Noise floor first:** `engine-check --old C:/Tools/forge-decklab --new C:/Tools/forge-decklab P`
     and `engine-check --old $SCRATCH/installs/ai-r1 --new $SCRATCH/installs/ai-r1 P`: each build must
     repeat itself (exit 0, or exit 3 caused only by Commander pairs or time limits). Real decks such as
     Izzet Otters and TFP have never been checked line for line in Constructed; if a build doesn't repeat
     itself in Constructed, stop: the equivalence check can't be read for these pairs (fall back to
     cardlog-check's lists only).
   - **Then** `engine-check --old C:/Tools/forge-decklab --new $SCRATCH/installs/ai-r1 P`. Accept exit 0,
     or exit 3 caused only by Commander pairs (which plain Forge doesn't repeat line for line,
     cli_checks.py :72-79) or time limits, the same as the noise floor gave. Expect "Different engine key"
     (the old build keys by its full build name, the new one by `2.0.15+res.…`, and `gisa-bontu-1` is newly
     listed): the one-time re-key the owner accepted (every saved result is already an earlier engine).
   - Optional: the same with `--game-patches off` (identical unless a pair holds Gisa or Bontu).
2. Fork: in `C:/VSProjects/forge` (on `decklab`), `git merge --ff-only ai-r1` (never `--no-ff`: a merge
   commit is a new build name, install.py :41-44, so the installed build wouldn't be the one engine-check
   verified); `git status` must be clean (otherwise the build name gets `-dirty`). Then
   `python decklab/install.py` (installs `C:/Tools/forge-decklab`) and confirm the installed
   `decklab-build.txt`'s `build=` equals the scratch install's. TCC: merge `ai-r1` into `main`.
3. Real-Forge tests against the new install, serially, before anything else plays:
   `DECKLAB_FORGE_TESTS=1` with `decklab.tests.test_forge_aipatches`, `test_forge_deckorder`,
   `test_forge_v2loop` (they exercise deck-order-1, the in-order attack patch and `gamePatchIds` with the
   real jar, which now has `GamePatches`, `AiSwitches`, the TreeSet change and the Startup hook).
4. `python -m decklab.lib.forge cardlog-check`; then set `simjar.V` to the new build, `CHECKED_BUILDS`,
   and `CHECKED_SOURCE` to `simjar.source_sha256()`; run `test_forge_simjar`; commit on main. Restart the
   background server only if it's running (`python -m decklab.lib.homenet restart`).
5. Field baseline (scout C1 with the verification's corrections), each after `--dry-run`, serially, warm
   pool: `field casual/the-free-peoples`, `field casual/izzet-prowess` (standard budget, about 4,000 games
   each), `field commander/finneas-rabbits`, `field commander/gandalf-and-the-valley` (about 2,000 each);
   about 11,200 unique games, 65-80 idle minutes. This is for the card data and the re-keyed field only:
   it is **not** the experiments' controls (about 400 games a pair, fewer than an experiment needs, and
   not teed on every chunk, so the per-card measures would have no control logs).
6. Experiments (`python -m decklab.lib.forge experiment <spec> --dry-run`, then without), one at a time.
   Each plays its own controls into `<results>/control/` with the log tee on every chunk
   (experiment.py :28-31). Budget them (the dry-run prints the counts): E1's controls are 5,600 games
   (2 pairs × 2,800). E3 and E4 reuse E1's controls by naming them on purpose: `"control":
   {"results_dir": "<E1's results>/control", "logs_dir": "<E1's logs>/control"}` (as E1's dry-run prints
   them; a control holding games 0..2,799 covers E3's 1,600; E4's third pair, which E1 lacks, is played
   into E4's own control folder). E2 and E5 use `"control": {}`. E5 needs its controls played inside the
   experiment with the decision log on, so give E5 a fresh results folder (an existing current control
   would be reused without DLAI lines: the log isn't in the engine key).
   Specs (the named cards with `cast_target`/`turn_target` null unless said):
   - **E1 `ai-r1-etb-tfp`**, games 2,800: pairs `[casual/the-free-peoples, casual/izzet-prowess]`,
     `[casual/the-free-peoples, casual/gruul-ramp]`; arms `etb-tfp: {"overrides": ["etb-tfp"]}`,
     `etb-tfp-jailer: {"overrides": ["etb-tfp", "etb-tfp-jailer"]}`; cards Fires of Mount Doom,
     Éowyn, Fearless Knight, Samwise the Stouthearted, Palace Jailer.
   - **E2 `ai-r1-cmdr-hints`**, games 1,600: pair `[commander/finneas-rabbits, commander/gandalf-and-the-valley]`;
     arm `cmdr-hints: {"overrides": ["cmdr-hints"]}`; card Primal Might (cast_target 0.6).
   - **E3 `ai-r1-removal-in-combat`**, games 1,600: pairs as E1; arm `removal-in-combat-1: {"pilots":
     {"casual/the-free-peoples": {"profile": "Default", "switches": ["removal-in-combat-1"]}}}`; cards
     You Cannot Pass!, Swords to Plowshares, Path to Exile. Then **E3m**, games 3,200: pair
     `[casual/the-free-peoples, casual/the-free-peoples]`, the same arm with `"sides": "a"`.
   - **E4 `ai-r1-etb-harmless`**, games 2,800: pairs as E1 plus `[casual/izzet-prowess, casual/gruul-ramp]`;
     arms `etb-harmless-tfp` (pilot TFP `["etb-harmless-1"]`), `etb-harmless-ref` (pilot
     `casual/gruul-ramp` `["etb-harmless-1"]`: a reference with none of the cards, which should change
     nothing), `etb-harmless-izzet-nofiery` (pilot `casual/izzet-prowess` `["etb-harmless-1"]` with
     `"overrides": ["remove"], "replace_adopted": true`: can the switch retire the adopted `fiery` set?
     Fiery Annihilation's cast share should stay about 90%). Cards Fires of Mount Doom, Samwise the
     Stouthearted, Fiery Annihilation. Judge Samwise by cast timing too (verification C4 point 6).
   - **E5 `ai-r1-prowess`**, games 1,600: pairs `[casual/izzet-prowess, casual/the-free-peoples]`,
     `[casual/izzet-prowess, casual/gruul-ramp]`; arm `prowess-precombat-1` (pilot Izzet
     `["prowess-precombat-1"]`); cards Pearl of Wisdom, Preordain, Burst Lightning, Flame Lash. Run it with
     `DECKLAB_CONFIG_EXTRA` naming `{"forge_decision_log": ["Pearl of Wisdom", "Preordain", "Burst Lightning",
     "Flame Lash"]}` and `--local`, then `python -m decklab.lib.forge decisions <logs>/<arm>/<key>` and
     `<logs>/control/<key>` to compare the phases cast in. Then **E5m**, games 3,200: the Izzet mirror with
     `"sides": "a"`, judged on the matchup only (`decisions` can't split a mirror's sides, 3.8). The owner isn't sure Izzet Otters is prowess-first: report, don't recommend adoption
     unless the paired matchup is clearly better.
7. Report each experiment's recommendation to the owner. Adoption is the owner's call: an override set's
   status in `sets.json`, or a switch in the list's pilot in `decklab/simulation.json`. Decide adoptions
   together, then `replay --dry-run` and `replay` once for the re-keyed lists.
8. Future fork builds with only default-off changes: build into scratch with `--out`, `engine-check` against
   the installed build (expect "Same engine key" and exit 0, or 3 only from Commander pairs or time
   limits), merge with `--ff-only` on a clean tree, install, confirm `build=` matches the scratch build,
   `cardlog-check`, CHECKED constants. No replay.

---------------------------------------------------------------------------------------------------------

## 6. Review responses (2026-10-13)

Each point was checked against the code before it was taken.

Blocking, all taken:
- **test_forge_models.py pins `"id_version": 2`** (:163, `KeyTests.test_key_is_the_contract_sha`):
  confirmed. DF now owns it and greps every `test_forge*.py` first (section 4, DF).
- **`overrides make --set` takes one name** (cli_commands.py :317 `dest="set_name"`, :337
  `make([args.set_name])`): confirmed. OV runs make three times; `upstream_sha256: ""` is accepted
  (overrides.py :196).
- **GisaBontuPatchTest didn't test the gates:** confirmed. `canPlaySa` never reads `isCardRemAIDeck`; the
  filter is in `chooseSpellAbilityToPlay`'s path (AiController.java :1565-1569, public entry :1351), and
  TokenAi's gate is reached through `SpellApiToAi.Converter.get(sa).canPlayWithSubs` (SpellAbilityAi.java
  :56, as ChangeZoneAiTest uses it). The test now covers TokenAi, the cast, Bontu and the predicates.
- **No regression baseline:** taken. FF step 0 writes `$SCRATCH/fork-baseline.txt` on an unmodified
  `decklab`; every fork package's acceptance is "no failures beyond the baseline" (rule 6).

Nonblocking:
- Engine key fallback and old fork builds: taken, and merged into one rule (D1, 3.6 `engine_forge`):
  stock is the jar's release; a build with `res_sha256` is `base=`'s release plus `+res.`; a fork build
  without it keeps its full build name; an unreadable file is unknown and `current()` uses the remembered
  release or refuses. The build name is never cut. The release comes from `base=` when present.
- Gisa gate coverage: taken where it's one line in a class that can see `GamePatches`
  (`CardPredicates.isRemAIDeck`, `PlayEffect`, `CopyPermanentEffect`, `PlayerControllerAi`, all
  `gisa-bontu-1`). `Deck.UnplayableAICards` (forge-core can't see forge-game) and Deck Lab's own script
  readers are stated as open (D5, end notes, HISTORY).
- Switch first in each conjunction, and the comment after the `;`: taken (D9, C4, C6).
- Hot-path cost: taken as a volatile `Pilots.forkSwitches` flag tested before the seat is parsed (3.5,
  D6). 3.2's "one volatile read" is about `AiSwitches.on` itself and stays.
- engine-check side effects: taken (`_setup(..., remember=False)`, `current(..., remember=False)`; a test
  holds that nothing is written).
- Noise floor and exit 3: taken (section 5 step 1, `--old` equal to `--new`, a DF test for exit 3).
- `--ff-only` merge and the build name: taken (section 5 steps 2 and 8, README steps).
- The field baseline isn't the experiments' controls: taken. Each experiment plays its own; E3 and E4
  name E1's controls on purpose; E5 gets a fresh results folder; budgets stated (section 5 step 6).
- Decision-log opportunities: taken (`TimingRestrictions` excluded, per-phase and per-seat counts, the
  affordability caveat, mirrors and timeouts as known limits; E5m judged on the matchup).
- Test details for C4 (a creature the 2 damage kills), C5 (`setActivatingPlayer`, `setCombat`) and C6
  (sickness off): taken.
- ai-switches.txt advertising an unbuilt switch: taken. `AiSwitchesTest` checks every listed class file
  is a resource, so `ai-r1-base` lists `prowess-precombat-1` with `ComputerUtil.class` only and C6
  appends `ProwessFirst.class`; INT checks each id is implemented and removes a dropped package's id
  (it can't be caught by a class-file check alone, since C4's and C5's classes exist either way).
- INT environment (`DECKLAB_FORGE_FORK`, `JAVA_HOME`): taken.
- DF small gaps: taken (`_overrides_status` unions the fork switches; `--switch` with `--game-patches
  off` exits 2; `check_switches` reads `eng["game_patches_on"]` from the setup's knob, falling back to
  the old test for engines without the field).
- Real-Forge tests after installing: taken (section 5 step 3).
- Docs: taken (DeckLabSwitchTest's comment, D6; the once-per-JVM property in D12, 3.8 and the README).

