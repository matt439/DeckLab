# Check a result with another simulator

Owner of E3-S40 (Matt, 2026-11-09). This is an independent check of a matchup or a card change, not another source of games for the existing Forge ratings.

## What the result means

Forge and XMage have different card implementations and AI decisions. Agreement on the direction of a change provides extra evidence; disagreement identifies a deck or interaction to inspect. Neither agreement nor additional simulated games establishes how people will play a deck. Two-player Commander results do not describe multiplayer politics or a four-player pod.

Keep results separate by engine, exact build, AI configuration, format and frozen lists. A change is compared with its baseline inside each engine. Never average the engines' win rates or call matching random seed numbers matching games across different engines. Only claim paired/reproducible games where the runner has actually established that property.

Missing cards, failed imports, unsupported formats, engine errors, timeouts, turn limits and user cancellation are distinct from completed games. None becomes a loss. Never remove a card or substitute an approximate card to make a list run. A partly completed comparison stays visibly partial.

## Initial workflow

The deck's Testing tab offers an explicit check against one visible saved opponent of the same format. The command line also accepts a bounded card swap. Freeze the baseline, optional changed list and opponent before queuing. Require both current saved-list fingerprints when starting from the page; changed lists need a fresh deliberate request. All engine work is local and starts only after an explicit action.

The existing deck visibility, simulations mode and stop permissions apply. Every participant must still be visible when reading a job or saved receipt. A private deck is answered exactly like a missing deck, before engine readiness or detailed run errors. No inventory, kit or other private-derived information belongs in a receipt's web answer. A public deck does not grant the right to save a change to it.

Cross-check results live under the gitignored `decklab/data/crosscheck/`, outside Forge's ordinary matchups, field, gauntlet, rankings and card statistics. Reading or installing this feature does not rewrite existing results or database records.

## Engine boundary

Forge uses Deck Lab's existing runner with an isolated results directory. XMage uses a small locally compiled bridge over an explicit local release. Setup is deliberate; page reads and runs do not download engines, install software or start a network server. The bridge checks exact card names and Commander sections before playing. The Python supervisor bounds game time, output and memory and cleans up its own child process.

Record protocol/schema version, input digest, exact list digests, engine release/build identity, AI choice, seat, game number, requested seed, whether seed reproducibility is supported, completion status and result. Reject malformed or mismatched output rather than retaining it as evidence. Reusing a cache requires the same identity, not merely the same deck title or requested engine name.

## Qualification and remaining work

Implemented and qualified on the development PC on 2026-11-09:

- Guarded focused checks: 119 tests passed across the core, process ownership,
  recorded native protocol, API/UI, build identity, restart and source inventory;
  six additional CLI boundary tests passed. A broader existing integration run
  completed 175 tests with six expected native/database qualification skips.
  The existing gauntlet, page asset/script-order and matchup-layout contracts
  passed all 74 tests after including the new section and deferred script.
- The pinned XMage bridge passed 15 native cases: four completed synthetic games,
  four unsupported/invalid-list refusals, one timeout and six strict-JSON refusals.
  Cases include casual Sol Ring without tournament filtering, exact double-faced
  names, single and partner commanders, invalid colors and invalid partners.
  The core independently parsed all 15 actual outputs; four public synthetic
  request/result pairs now have 14 offline regression tests.
- Final full-path validation completed eight games: baseline and changed lists
  against an opponent, separately in Forge and XMage, for casual and Commander.
  Both engines reported complete evidence in both formats. The immutable receipt
  ids are `d6955988287617a3ef264b39346036ece5bc2999bb66e5dc1a6f8d97fe19f5b5`
  (casual) and `ce5b774f703b625d6b9cf8b413af248afffccdd1e27585938aa30e942c26e426`
  (Commander). These are synthetic integration proofs, not deck-strength samples.
- Two native Windows ownership probes confirmed that a child is stopped both
  after its parent exits and on cancellation, with separate stdout/stderr.
  POSIX ownership and Forge group inheritance are fixture-tested; real Linux
  process/runtime qualification remains separate.
- The rendered review passed 20 cases in light/dark at 320, 393, 820 and 1440px,
  with saved, unavailable, playing, partial, failed and loading states and an
  intercepted explicit start/Stop. Manual inspection found and repaired a sticky
  table heading covering the first engine's row; element-from-point assertions
  now verify both engine names remain unoccluded. Full final evidence is under
  `decklab/data/ui-review/20261109T130344Z-2b3c8496/` (ignored). A final eight-case
  smoke after the CLI boundary changes also passed, under
  `decklab/data/ui-review/20261109T130725Z-4f7af33b/`. Cleanup completed.

Native XMage evidence is in the separate scratch release's `qualification-final/`;
full-path receipts and plans are under the worktree's ignored
`decklab/data/crosscheck/`. No household/member records, visibility settings,
installed services or live server configuration were changed. No simulator JVM
was left running after qualification.

Fixtures never establish actual XMage support or throughput. A game with synthetic
cards never establishes all household cards work. The first UI checks saved
matchups; testing changes is available through the CLI. Installation and acceptance
on the live Linux server, household Safari/touch, broader Commander coverage,
four-player pods, automatic engine selection and comparisons against a whole
gauntlet remain outside this initial slice. Sideboards and companions are excluded
equally from both engines. XMage seeded replay is explicitly unproven.

## Setup and use

An existing qualified Deck Lab Forge installation and a full JDK are required.
XMage is optional and disabled when `xmage_dir` is unset. Nothing below changes
the household database or installs services.

1. Download the official [XMage 1.4.63 release archive](https://github.com/magefree/mage/releases/download/xmage_1.4.63V1/mage-full_1.4.63-dev_2026-10-31_09-42.zip).
   Its SHA-256 is `f48e69a2583720800ab6a447458ede73bded5cb21905b0d9658a6052ab43908a`.
   The pinned source revision is `79aec614fc29d0c3eebd10fff0d5c1b40852bd52`.
   Extract it to a separate tools directory, for example `C:/Tools/xmage` on
   Windows or `~/tools/xmage` on Linux. Do not start an XMage server.
2. Set `"xmage_dir"` in the private `decklab/config.json` to that extracted
   directory. Use an absolute path on the server PC. Existing Forge/JDK settings
   continue to apply; no cloud service or account is needed.
3. Explicitly compile the small bridge and prepare this checkout's Forge runtime:

```powershell
python -m decklab.xmage build --home C:/Tools/xmage
python -m decklab.lib.crosscheck prepare
python -m decklab.lib.crosscheck status
```

On Linux, replace the `--home` path with the extracted local release path. Build
does not change upstream files. Status checks the pinned installation and bridge
without compiling, playing or downloading anything. A changed engine, bridge or
AI configuration needs a new plan; old receipts retain their original identity.

The web page offers 10, 20 or 50 games per engine against one visible opponent,
following the simulations setting. Start explicitly; Stop keeps completed
evidence. Restart Deck Lab's busy warning includes these checks.

The command line can preview a comparison or test a card swap without saving it:

```powershell
python -m decklab.lib.crosscheck plan casual/example casual/opponent --games 10
python -m decklab.lib.crosscheck play casual/example casual/opponent --games 10
python -m decklab.lib.crosscheck play casual/example casual/opponent --remove "1 Shock" --add "1 Lightning Bolt" --games 20
python -m decklab.lib.crosscheck view --deck casual/example
python -m decklab.lib.crosscheck view <receipt-id>
```

Replace the example deck ids and cards with the exact saved ids and intended
swap. Use `--version owned` or `--opponent-version owned` for a Play-now list.
The CLI allows a diagnostic `--engine forge` or `--engine xmage`; a single-engine
run is never described as agreement between simulators. `plan` prints frozen
input and readiness identities without starting games. `play` returns a nonzero
exit code for incomplete evidence. A receipt id is the complete 64-character
hash printed with the result.

The initial runner uses one engine worker at a time, claims the existing PC-wide
worker budget and caps XMage's heap at 1 GiB. It has per-game deadlines and bounded
output; it does not leave a persistent XMage server or warm worker running.
Random seed numbers do not mean matching games across engines. XMage explicitly
reports that reproducible seeded replay has not been established.

For explicit disposable native XMage qualification, use
`python scripts/xmage_qualify.py --help`. This is separate from guarded fixture
tests and needs the pinned local release and compiled bridge. It uses invented
lists, never saved household or member decks. Keep its output under the ignored
data directory or a new scratch folder.

## Upstream references

- [XMage](https://github.com/magefree/mage): independent rules engine and computer opponents.
- [XMage load tests](https://github.com/magefree/mage/blob/master/Mage.Tests/src/test/java/org/mage/test/load/LoadTest.java): repeated AI-versus-AI games are developer tooling, not an installed Deck Lab backend.
- [XMage AI discussion](https://github.com/magefree/mage/issues/10154): AI and card-support limitations, including runaway calculations.
- [Magarena command line](https://github.com/magarena/magarena/wiki/Command-line-arguments): a possible later supported-list 1v1 experiment, not the first Commander engine.
