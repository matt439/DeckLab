# Syr Elenora's commander cast in Forge (FG#4)

The [FG#4 owner](../PLAN.md) records zero commander casts across the completed budget. Source inspection on 2026-11-20 identifies a specific veto in the ordinary native pilot. The aggregate cannot establish which games reached a payable main phase or emitted complete commander events.

## From script to spell selection

The inspected fork was `029c9518f02848683f82b6a96a49e5fae4c56b3f`. The local installation's `decklab-build.txt` names `2.0.16-decklab-029c9518f` and base `forge-2.0.16`. The tag and fork both contain `AI:RemoveDeck:All` in `forge-gui/res/cardsfolder/s/syr_elenora_the_discerning.txt`. The installed `res/cardsfolder/cardsfolder.zip` member `s/syr_elenora_the_discerning.txt` matches the fork line for line (member SHA-256 `4a37a4339506202563d7410487664b86f44caeb024fc1296837e6c8987f82342`). This fingerprint identifies a public stock resource on the development PC. A future native receipt needs its own build, effective overrides, runner and pilot identity.

1. `CardRules.Reader` parses `RemoveDeck:All` into `removedFromAIDecks`. `CardAiHints.isRemovedFromAiDecks` serves deck selection. A prewritten Commander list can still register the card. The per-game `DL|commander` roster establishes whether the game actually did.
2. In `forge-ai`, `ComputerUtilAbility.getAvailableCards` includes the player's command zone. After land plays, `AiController.chooseSpellAbilityToPlayImpl` ordinarily calls `getSpellAbilityToPlay`, which gathers spell abilities and removes each marked host when `ComputerUtilCard.isCardRemAIDeck(h) && !flatMc`. The ordinary picker therefore drops Syr's creature spell before heuristic approval, even if all five mana are available. The card needs no target to cast. Its power-setting ability, enter-and-draw trigger and surcharge on opponents' targeting spells do not provide a separate casting restriction.
3. Deck Lab's [GameLoop](../lib/forge/java/decklab/GameLoop.java) creates the game. Forge's `Game.AI_FLAT_MONTE_CARLO` starts false. The wrapper's `aisim-hybrid-1` selects hybrid simulation. Only full simulation takes the early `simPicker` return in this method. The desktop simulator's separate Flat Monte Carlo switches do not establish the historical gauntlet pilot.
4. With Flat Monte Carlo active, the first filter admits marked hosts. For an ordinary marked card outside the combo/tutor exceptions, `AiController.isFlatMcOnlyPlay` still bypasses heuristic approval. Main-phase discovery must be enabled with extra candidates, `isLegalDiscovery` must accept the spell, and the picker must choose it. Changing a profile name alone does not demonstrate any of those steps.

## What a zero counts

[CardLog](../lib/forge/cardlog.py) identifies commanders by their initial roster IDs, counts transitions to Stack from any zone, and reverses a failed cast. The named ordinary spell-cast line provides a second observation. A commander that resolves and then draws a card provides another check on this particular script. A countered spell can still be a successful cast. An absent commander entry can display as zero through [cardstats](../lib/forge/cardstats.py). A good-game count alone does not show that the observer received the roster or the relevant transitions.

The [observer regression](../tests/test_forge_commander_observers.py) replays the exact comma-bearing name in both seats. Dropping only cast text preserves the ID tally. Dropping only the commander roster or its zone transitions preserves the text tally while leaving the commander tally empty, even in a game accepted by the parser. A failed attempt yields zero successful casts in both observers.

Deck Lab's [playability check](../lib/forge/ai.py) also inspects the effective script. Its `_cannot_play` records a commander with the removal hint before checking cast counts. The 20 excluded matchups therefore do not provide 20 independent confirmations of the cause.

## Small native check, pending execution

Use two disposable public lists. Give Syr Elenora, the Discerning and Lu Meng, Wu General 99 basic Islands apiece and place each legend in its Commander section. Lu Meng is also a legendary creature costing exactly `3 U U`. Its public script has horsemanship and no removal hint. Each list has one possible nonland play and the mana to make it. Use the normal Commander wrapper, Default profiles, empty seat switches, stock scripts and a scratch output directory.

Play exactly one game per seat assignment, swapping the two lists and reusing the same explicit stream and game index. Preserve per-game seat and starter, both deck hashes, engine echo, raw logs and completion status. In each game check:

- Both roster entries have their expected names and seat-local IDs. Identify each side's first own main-phase opportunity with five usable Islands, its commander still in Command and no prior cast. In these lists the land plays, turn boundaries and absence of competing spells make the opportunity independently checkable.
- Reconcile each legend's named successful casts and failed attempts with that ID's moves to Stack, origin and first-cast turn, then compare with parsed `casts` and `cast_games`. If Syr resolves, check the draw separately.
- Require a completed, accepted game and a positive Lu Meng cast in each seat. Stop on invalid setup, incomplete logs, an absent payable opportunity, missing control cast or disagreement between observers. A confirmed Syr cast under the pinned baseline contradicts an unconditional veto in the actual path. Preserve that game for inspection.

Two qualified control casts with two payable, uncast Syr opportunities support the predicted baseline behavior on these lists. These games cannot measure household matchup strength. Further causal isolation could use a separate scratch copy with a single, explicitly reviewed change and paired replay of the same two games. Any candidate fix still needs qualification for correct powered creature behavior and enter-and-draw resolution before broader matchup work.

When a native session is approved, save the lists as `syr.dck` and `lu-meng.dck` in the same scratch deck folder. Use `[Commander]` with one copy of the named commander and `[Main]` with `99 Island`. The following are the two argument lists produced by Deck Lab's [request builder](../lib/forge/runner_launch.py) for the normal DeckLabSim wrapper. Substitute the scratch deck folder before launch. Keep card logging enabled.

```text
sim -D SCRATCH_DECKS -d syr.dck lu-meng.dck -n 1 -s 1 -f Commander -c 60 -a Default Default -dlgame 0000000000000001 0
sim -D SCRATCH_DECKS -d lu-meng.dck syr.dck -n 1 -s 1 -f Commander -c 60 -a Default Default -dlgame 0000000000000001 0
```
