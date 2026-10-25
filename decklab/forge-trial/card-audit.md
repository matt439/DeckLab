# Forge trial: card support audit (Milestone 0, step 4)

Written 2026-09-29 on HomePC. Forge 2.0.15 at `C:/Tools/forge` on JDK 26.0.1, set up as in `setup-notes.md`.
Paths are relative to this folder (`decklab/forge-trial/`, gitignored), unless they start with `magic/`.
Every claim below was either read in Forge's source at tag `forge-2.0.15` (commit `4ec5f1a2c32fa90ecb983a72b9eb47aa5c5d7676`,
sparse clone of `forge-core`, `forge-game`, `forge-ai`, `forge-gui` and `forge-gui-desktop` `src/main/java`, files named inline) or
measured here. Each item says which.

## Verdict

- **Unsupported cards: none.** All **612** unique card names have a working Forge card script. That covers:
  - 351 from the 11 deck files (target list, owned-only list and sideboards, plus commanders);
  - 513 from the 6 product lists;
  - 443 from `magic/collection.csv` and the order files.
  595 of the names are in a deck or product; 17 more appear only in the collection or orders.
- **The static check and the load check agree exactly.**
  - Written as `to_dck.py` writes them, 0 names were unsupported in both checks.
  - Written as Scryfall's `A // B`, both checks found the same 2 unsupported names (the positive control).
  - Eager and lazy card loading gave the same result.
- **Naming conventions.** Only 2 of our names differ from Forge's card name:
  - Both are adventure cards: `Murderous Rider // Swift End` and `Pollen-Shield Hare // Hare Raising`.
  - Forge names them by the front face only. `to_dck.py` already writes the front face.
  - None of our cards are split cards (the only layout Forge names `A // B`), and no names differ in case or accents.
  - 6 of our names (Lightning Bolt, Swords to Plowshares and 4 more) are also the back face of Secrets of Strixhaven "Prepare" cards. Forge still picks the real card (source and test).
- **6 cards are supported but the AI will never cast them: `AI:RemoveDeck:All`.**
  - In our decks:
    - **Ghoulcaller Gisa** (the commander of `gisa-zombies` and of the Wretched Ranks precon);
    - **God-Eternal Bontu**;
    - **Devout Decree**;
    - **Beast Within**.
  - In the Starter Collection card list only: **Bolt Bend** and **Demonic Pact**.
  - Evidence from Forge's source: `AiController.getSpellAbilityToPlay` drops them.
  - Evidence from play:
    - Over 10 test games, the 5 cards tested were cast 0 times and discarded from hand 37 times. Same-cost unflagged cards in the same decks were cast 14-28 times.
    - Over 4 Commander games, Gisa was cast 0 times from the command zone. The opposing AI cast Giada 10 times.
- **31 more flagged cards in our decks or products (23 `RemoveDeck:Random`, 8 `RemoveDeck:NonCommander`, no overlap) don't change play in sim mode** (source). A spot check showed several of them being cast normally.
- **No card of ours has an ability type the AI has no logic for** (`CannotPlayAi`): 0 of 612. Across Forge's whole card pool it's 182 of 33,980 scripts.
- **What this means for Deck Lab:**
  - Forge results for **Ghoulcaller Gisa: Wretched Ranks** mean nothing as things stand: the AI never casts its commander.
  - Every other deck has at most one flagged card (a single copy in the main deck or sideboard), which is a dead card in the AI's hand.
  - A workaround was tested and works: put a copy of the script, minus the `AI:` line, in the run's `custom/cards` folder. The AI then casts the card, but plays some of them badly (details below).

## 1. What was collected

Tool: `card_audit.py scan`. It reuses `to_dck.py`'s `fenced_block_after` and `parse_decklist`, so it reads exactly the lists `to_dck.py` converts.

| Source | What was read | Rows / lists | Unique names |
|---|---|---|---|
| `magic/decks/casual/*.md` (8), `magic/decks/commander/*.md` (3) | the fenced block under `## Decklist` (target) and the one under `### Owned-only version`, every section (`Commander`, `Deck`, `Sideboard`) | 22 lists | 351 |
| `magic/products/*.csv` except `status.csv` | every row: `blb-starter-kit` (39, `deck` column), `challenger-2019-lightning-aggro` (17, `section`), `fdc-calling-all-angels` (69), `fdc-wretched-ranks` (68), `fdn-beginner-box` (138, `deck`), `fdn-starter-collection` (268, a card list rather than a deck; included because it's product contents) | 599 rows | 513 |
| pool (bonus): `magic/collection.csv`, `magic/orders/*.csv`, `magic/orders/received/*.csv` | every row | 444 + 16 + 25 | 443 |
| **all** | | | **612** (595 in a deck or product, 17 pool-only) |

Where each name is used (deck, list, section, quantity; product and part; pool file) is kept in `audit/audit.json` under `cards[].uses`.
The "Used in" columns below and the appendix come from it. 46 names are only in deck files (not yet owned, and in no product),
30 are only in products, and 139 deck-file names aren't in the collection or orders yet.

The 17 pool-only names are: Adventuring Gear, Aegis Turtle, Courageous Goblin, Fake Your Own Death, Goblin Surprise, Goldvein Pick,
Inspiration from Beyond, Involuntary Employment, Lightshell Duo, Mossborn Hydra, Nessian Hornbeetle, Scourge of Nel Toth,
Soul-Shackled Zombie, Spitfire Lagac, Sure Strike, Tragic Slip and Zulaport Cutthroat. All are supported, and none is flagged.

## 2. Static check against Forge's card scripts

**Script store:** `C:/Tools/forge/res/cardsfolder/cardsfolder.zip` holds 34,010 entries.
- 33,980 of them are `.txt` card scripts: 33,404 in the `a/`-`z/` folders, 346 in `upcoming/` and 230 in `rebalanced/`.
- There is no loose `.txt` folder.
- Forge's own lazy loader reports the same count (`Lazy card database: indexed 35240 card names from 33980 files`).
- No two scripts share a card name.

**How Forge reads and names cards (source):**
- `CardRules.Reader.parseLine` (`forge-core/.../card/CardRules.java`):
  - `Name:` starts a face.
  - `ALTERNATE` switches to face 2, and `SPECIALIZE:<colour>` to faces 3-7.
  - Lines that are empty or start with `#` are skipped.
  - `AlternateMode:` sets the layout (`CardSplitType`).
- `CardRules.getName()`: only `Split` (aggregation method `COMBINE`) is named `A // B`. Every other layout (Transform, Modal, Adventure, Flip, Meld, Omen, Prepare, Specialize) is named after its front face.
- `CardDb` indexes every face name too (`addFaceToDbNames`, `addCard`). Lookups are case-insensitive (`String.CASE_INSENSITIVE_ORDER` maps), with accent-stripped aliases (`StringUtils.stripAccents`).
- Eager loading reads every `.txt` in the zip, including `upcoming/` and `rebalanced/` (`CardStorageReader.getZipEntries`). The "skip `upcoming/`" rule applies only to loose folders (`collectCardFiles`).
- A name-only request tries exact primary names first (`CardDb.tryToGetCardFromEditions` -> `getAllCardsNoAlt`, with the source comment *"'Ancestral Recall' won't return Emeritus of Ideation"*). Only if that fails does it fall back to face names.
- Names still not found become `CardRules.getUnsupportedCardNamed`, which `Deck.getValid` removes before play (see `setup-notes.md`).

**What `card_audit.py` does:**
- It parses every script the same way and builds a name index and a face index (normalised: accents stripped, lower case).
- It resolves each Scryfall name: first as an exact card name; for `A // B`, then by its front face (also checking that the back face belongs to the same script); otherwise as a face name.
- It checks that `to_dck.forge_name(name)` resolves to the same script.
- Run time: 0.97 s wall for all 33,980 scripts (Python 3.14, timed with `time.perf_counter` around `python card_audit.py scan`).

**Results (static):**

| Group | Names | Unsupported | `RemoveDeck:All` | `RemoveDeck:Random` | `CannotPlayAi` ability |
|---|---|---|---|---|---|
| deck files | 351 | 0 | 4 | 13 | 0 |
| product lists | 513 | 0 | 5 | 17 | 0 |
| collection + orders | 443 | 0 | 4 | 11 | 0 |
| all | 612 | **0** | 6 | 23 | 0 |

(A card can be in several groups. `RemoveDeck:NonCommander` is 8, all in decks and products.)

**Resolution details:**
- 610 names match a Forge card name exactly, character for character.
- 2 resolve by their front face. Both are adventure cards (`AlternateMode:Adventure`); see "Naming differences" in the lists.
- No split cards, no case or accent differences, and no ante cards.
  - Match.java removes ante cards when ante is off: `getRemovedAnteCards`, keyword "Remove CARDNAME from your deck before playing if you're not playing for ante."
- None of our cards has a `Variant:` or `DeckRule:` line.
- **Token scripts:** the 70 of our cards that make tokens reference 29 distinct token scripts. All 29 exist in `C:/Tools/forge/res/tokenscripts/` (854 files).
- **Face-name collisions:** 6 of our names are also the back face of a Secrets of Strixhaven card (`AlternateMode:Prepare`), e.g. `Emeritus of Conflict` / `Lightning Bolt`.
  - Forge's lookup prefers the exact primary name (above).
  - **Test:** two copies of a deck with 5 each of the six names (`decks/ai-hint-test/face-collision*.dck`) played 3+3+4 games:
    - `logs/face-collision-lazy-n3-s1.*`, `face-collision-eager-n3-s1.*` and `face-collision2-eager-n4-s2.*`;
    - the second version adds 8 Llanowar Elves so Swords to Plowshares has targets.
  - **Result:** the cast lines show Lightning Bolt (13, 21), Swords to Plowshares (22), Rampant Growth (9, 18), Sign in Blood (9, 12) and Exsanguinate (7).
    - None of the five back-face names (Emeritus of Conflict, Emeritus of Truce, Studious First-Year, Scheming Silvertongue, Stensian Sanguinist) appears anywhere in those logs or the load-test logs.
    - Secret Rendezvous was never cast (the AI chose not to), but it shows up as `Secret Rendezvous` in the log.

## 3. Load check (Forge actually loading every name)

**Decks** (`card_audit.py decks`, written to `decks/audit/`):
- `all-01.dck` to `all-04.dck`: 153 names each, 1 copy each, every one of the 612 names in the form `to_dck.py` writes (front face of `A // B`), alphabetical.
- `scryfall-dfc.dck`: the 2 `A // B` names exactly as Scryfall spells them, plus 30 Swamp. This is the positive control.

**Commands**, from this folder with my own user folder so the `--lazy` preference didn't touch other agents' `forge-user/`:
```
python run_sim.py decks/audit/all-01.dck decks/audit/all-02.dck -n 1 -s 1 -c 60 --user-dir forge-user-audit --log logs/audit-eager-01-02.log --json logs/audit-eager-01-02.json
python run_sim.py decks/audit/all-03.dck decks/audit/all-04.dck -n 1 -s 1 -c 60 --user-dir forge-user-audit ...                    (audit-eager-03-04)
python run_sim.py decks/audit/scryfall-dfc.dck decks/audit/all-01.dck -n 1 -s 1 -c 60 --user-dir forge-user-audit ...             (audit-eager-dfc)
  ... and the same three with --lazy (audit-lazy-01-02, audit-lazy-03-04, audit-lazy-dfc-01)
python card_audit.py compare --load logs/audit-eager-01-02.json logs/audit-eager-03-04.json logs/audit-eager-dfc.json   (and the lazy three)
```

**Why a 1-game sim is a full load test** (source): `Match.prepareAllZones` -> `preparePlayerZone` calls `Card.fromPaperCard` for every card
in each library. So each game built all 153 cards per deck, abilities included, after `Deck.getValid` had removed any unsupported ones.
Any script error would have thrown there, and the run would have shown an error game.

| Run | Loading | Start-up s | Game | Unsupported reported | Exceptions / "No AI assigned" |
|---|---|---|---|---|---|
| all-01 vs all-02 | eager | 9.05 | 4,821 ms, 26 rounds, deck 2 won | none | 0 / 0 |
| all-03 vs all-04 | eager | 12.25 (another agent's Forge process was running) | 1,859 ms, 7 rounds, deck 2 won | none | 0 / 0 |
| scryfall-dfc vs all-01 | eager | 9.26 | 1,705 ms, 13 rounds | `Murderous Rider // Swift End`, `Pollen-Shield Hare // Hare Raising` (stderr, 4 times each) | 0 / 0 |
| all-01 vs all-02 | lazy | 1.32 | 3,498 ms, 26 rounds, deck 2 won | none | 0 / 0 |
| all-03 vs all-04 | lazy | 1.45 | 1,549 ms, 7 rounds, deck 2 won | none | 0 / 0 |
| scryfall-dfc vs all-01 | lazy | 1.45 | 1,854 ms, 13 rounds | the same 2 | 0 / 0 |

- **`compare` output (eager and lazy the same):**
  - expected unsupported in `to_dck.py` form: `[]`;
  - expected in Scryfall form: the 2 adventure names;
  - Forge reported: the same 2;
  - "match: True", "only in Forge: []", "only static: []".
- The only other warnings in these logs are the Guava `sun.misc.Unsafe` warning, the `Upcoming set Star Trek (TRK)` line, and 19 `The card X was not assigned to any set` lines (5 plain names, 14 `A-` Alchemy names). **None of those 19 is one of our cards** (checked against `audit/audit.json`).
- Eager and lazy loading played the same games from the same seed (same winner and round count).
- I ran no separate per-deck loads. The previous step already loaded all 11 deck files and the product decks with zero unsupported cards (`setup-notes.md` section 6), and the 4 audit decks cover every name.

## 4. AI hints in the card scripts

**Which `AI:` lines exist.** Across all 33,980 scripts:

| `AI:` line | Scripts |
|---|---|
| `AI:RemoveDeck:All` | 2,501 |
| `AI:RemoveDeck:Random` | 2,383 |
| `AI:RemoveDeck:NonCommander` | 70 |
| `AI:Remove:Random` | 1 (a typo in one script; ignored by the parser, which only knows `RemoveDeck`) |

None of our cards has an `AI:` line other than `RemoveDeck:*`.

**What each flag does in a sim game (source).** Flags are read in `CardRules.Reader.parseLine` into `CardAiHints` (`getRemAIDecks`, `getRemRandomDecks`, `getRemNonCommanderDecks`). I checked every caller.

- **`RemoveDeck:All`**:
  - `AiController.getSpellAbilityToPlay` runs `saList.removeIf(... ComputerUtilCard.isCardRemAIDeck(hostCard))` (comment: *"don't include removedAI cards if somehow the AI can play the ability"*). This is the AI's normal choice of what to cast or activate. So the AI **never casts the card, and never activates its abilities**.
    - Lands are still played, because land drops go through a separate path.
    - Static and triggered abilities still work.
    - The only way around it is full simulation (`usesFullSimulation()`). Sim mode never turns that on: `SimulateMatch` -> `GamePlayerUtil.createAiPlayer(name, i-1, profile)` passes no `AIOption`, so `LobbyPlayerAi.option` is null. All four AI profiles use this same path: `AiProps.java` and `res/ai/*.ai` have no simulation setting.
  - The flag is also used here:
    - `ComputerUtilAbility.saEvaluator`: -10 priority;
    - `PlayEffect` and `CopyPermanentEffect`: the AI won't pick such cards to cast or copy for free;
    - `ControlGainAi`, `ControlExchangeAi` and `CopySpellAbilityAi`: won't target them;
    - `PlayerControllerAi.sideboard`: won't sideboard them in;
    - deck generators.
  - `Match.prepareAllZones` collects these cards per player (`complainCardsCantPlayWell`) and passes the list to `revealAISkipCards`. The AI controller's version is empty (*"Ai won't understand that anyway"*), so **sim output never lists them**. Deck Lab has to work this out itself (`card_audit.py` does).
- **`RemoveDeck:Random`** has two uses:
  - it keeps cards out of generated random decks (`CardRulesPredicates.IS_KEPT_IN_RANDOM_DECKS`, `LimitedDeckBuilder`, `CardThemedDeckBuilder`, `VLobby`);
  - `ChangeZoneAi` won't choose such a card when it steals a card onto the battlefield with `GainControl` (none of our cards do that).
  - **No effect on how the AI plays our decks.**
- **`RemoveDeck:NonCommander`**: only deck generation (`DeckGeneratorBase`, `IS_KEPT_IN_AI_LIMITED_DECKS`). `ComputerUtilCard.isCardRemNonCommanderDeck` has no callers. **No effect in play.**
- **Ability types with no AI.**
  - `SpellApiToAi` maps each `ApiType` to its AI class.
    - Mapped to `CannotPlayAi`: ControlPlayer, ControlSpell, ExchangeControlVariant, GainOwnership, GameDrawn, ManaReflected, MultiplePiles, PlayLandVariant, RemoveCounterAll, InternalIgnoreEffect.
    - Not mapped at all, so they fall back to `CannotPlayAi` and print `No AI assigned for API: X`: Block, ChangeText, ChangeZoneResolve, Empower, ExchangeTextBox, Incubate, Intensify, LookAt, Recruit, SwitchBlock.
  - A spell or ability whose chain (`SP$`/`AB$` plus `SubAbility$` `DB$`...) contains one is never played (`SpellAbilityAi.canPlayWithSubs` -> `chkDrawbackWithSubs`). Optional triggers using one are declined (`doTriggerNoCost`).
  - `card_audit.py` follows those chains (and trigger `Execute$` chains): 0 of our cards, 182 of all scripts. The "No AI assigned" line appeared in none of our logs.
- **Script comments** on our cards:
  - Exsanguinate and Gray Merchant: `# AFLifeLost will be set by LoseLife` (harmless).
  - **Mystical Teachings** (Starter Collection card list): `# TODO: The AI will currently search for the most expensive valid card in the library ...`, meaning the AI tutors badly.

### 4a. In-game test of `RemoveDeck:All` (measured)

Sim mode doesn't check deck size or copy limits (`setup-notes.md`), so each test deck is mostly flagged cards, with unflagged cards at the same mana cost as controls:
- `decks/ai-hint-test/removedeck-black.dck`: 24 Swamp, 9 Ghoulcaller Gisa, 9 God-Eternal Bontu, 9 Demonic Pact, 5 Gray Merchant of Asphodel, 4 Liliana's Reaver.
- `decks/ai-hint-test/removedeck-gw.dck`: 12 Forest, 12 Plains, 9 Beast Within, 9 Devout Decree, 9 Fateful Absence, 9 Beast-Kin Ranger.

Command:
```
python run_sim.py decks/ai-hint-test/removedeck-black.dck decks/ai-hint-test/removedeck-gw.dck -n 10 -s 1 -c 120 --user-dir forge-user-audit --lazy --log logs/ai-hint-removedeck-n10-s1.log --json logs/ai-hint-removedeck-n10-s1.json
```
The log lines were counted with Python:
- casts: `Add To Stack: <player> cast <Name>`;
- activations: `... activated <Name>`;
- held in hand: `Discard: <player> discards <Name> (` at cleanup.

Result: 10 games, black 2 - GW 8.

| Card | Flag | Cost | Cast | Games cast in | Activated | Discarded from hand (games) |
|---|---|---|---|---|---|---|
| Ghoulcaller Gisa | All | 3BB | **0** | 0 | 0 | 7 (4) |
| God-Eternal Bontu | All | 3BB | **0** | 0 | 0 | 2 (2) |
| Demonic Pact | All | 2BB | **0** | 0 | - | 16 (5) |
| Beast Within | All | 2G | **0** | 0 | - | 1 (1) |
| Devout Decree | All | 1W | **0** | 0 | - | 11 (5) |
| Gray Merchant of Asphodel | - | 3BB | 17 | 9 | - | 0 |
| Liliana's Reaver | - | 2BB | 14 | 6 | - | 0 |
| Fateful Absence | - | 1W | 18 | 8 | - | 7 (2) |
| Beast-Kin Ranger | - | 2G | 28 | 10 | - | 0 |

Bolt Bend (red, only in the Starter Collection card list) wasn't played in any test. It goes through the same code path.

**Commander test:** the two owned Commander lists (`to_dck.py ... --list owned` for `gisa-zombies` and `giada-angels`), 4 games:
```
python run_sim.py decks/ai-hint-test/gisa-zombies-owned.dck decks/ai-hint-test/giada-angels-owned.dck -f Commander -n 4 -s 1 -c 120 --user-dir forge-user-audit --lazy --log logs/ai-hint-gisa-commander-n4-s1.log --json ...
```
- Gisa 1 - Giada 3, with 7-11 rounds per game.
- **`cast Ghoulcaller Gisa`: 0**, while the opposing AI cast `Giada, Font of Hope` 10 times. The AI never casts its own flagged commander from the command zone.
- **Spot check of other flags in the same log:**
  - `Random` cards cast: Undead Warchief 2, Ayara 1, Metropolis Reformer 1.
  - `NonCommander` cards: Arcane Signet cast 1; War Room played as a land 1.
  - Several others weren't drawn or cast in 4 games, which is too small a sample to show anything.

### 4b. Can the flag be overridden without changing the Forge install? Yes (tested)

**Source:** Forge always loads `<user dir>/custom/cards/*.txt` (`FModel`: `customReader = new CardStorageReader(ForgeConstants.USER_CUSTOM_CARDS_DIR, ...)`, with no preference switch).
- `StaticData.loadCustomCards` puts those into the same name-keyed `regularRules` map after the built-in scripts, so a custom script with the same `Name:` replaces the built-in one.
- run_sim's `--user-dir X` makes that folder `X/Forge/custom/cards/`.

**Test:** copies of the 5 scripts with only the line `AI:RemoveDeck:All` removed, put in `forge-user-override/Forge/custom/cards/`. The same black-vs-GW command was run with `--user-dir forge-user-override`, lazy and then eager (`logs/ai-hint-override-{lazy,eager}-n10-s1.*`).
- Lazy and eager produced **identical** results, so the override works in both loading modes.

| Card | Cast (was 0) | Activated | Discarded |
|---|---|---|---|
| Ghoulcaller Gisa | 2 | 0 | 31 |
| God-Eternal Bontu | 12 | - | 14 |
| Demonic Pact | 13 | - | 1 |
| Beast Within | 13 | - | 1 |
| Devout Decree | 2 | - | 2 |
| Gray Merchant of Asphodel (control) | 0 (now crowded out by Bontu) | - | 13 |

**What changed:**
- Black went from 2-8 to **0-10**.
- In game 6, Forge printed `Ai(1)-RemoveDeck Black has lost due to effect of spell 'Demonic Pact'`: the AI lost to its own Pact. That shows why the flag exists.
- In Commander with the override (`logs/ai-hint-override-gisa-commander-n4-s1.*`):
  - the AI cast Gisa 3 times in 4 games;
  - her sacrifice ability was **activated 0 times** in all 14 override games;
  - the match score was the same as without the override (Gisa 1 - Giada 3; small sample).

**Conclusion:** removing the flag makes the card castable, but it doesn't make the AI play it well. Demonic Pact is actively harmful. For Gisa and Bontu, the AI gets the body without the payoff.

## 5. What this means for Deck Lab

**Commander.** `gisa-zombies` as it is can't be simulated meaningfully: its commander is never cast.

Options:
- (a) Show "not simulated" for this deck.
- (b) Override Gisa and Bontu as in 4b and say on the page that Gisa's ability isn't used.
- (c) Ask Forge to add AI logic.

Giada and Finneas have no `All`-flagged commander. Finneas's list has 1 Beast Within.

**60-card decks.** Each of these has one flagged card that the AI treats as dead:

| Deck | Flagged card | Lists |
|---|---|---|
| mono-white-angels | 1 Devout Decree | owned and target |
| mono-black-midrange | 1 God-Eternal Bontu | owned list only |
| selesnya-rabbits | 1 Beast Within | sideboard only, which sim mode never uses (no AI sideboarding) |

The bias against these decks is small (one card in 60).

Gruul Ramp, Izzet Prowess, Mono-Black Zombies, Orzhov Removal and Orzhov Vampires have no `All`-flagged card, and neither does any Beginner Box half, the BLB Starter Kit or the Challenger deck.

**The matchup page should list, for each deck, the cards the AI can't play**, computed with the same rules as `card_audit.py` (`RemoveDeck:All` plus `CannotPlayAi` chains), because Forge never prints them in sim mode.

**Keep `to_dck.py`'s front-face rule.** Scryfall's `A // B` would drop both adventure cards.

## 6. Incidental findings

- **`run_sim.py` misses one loss wording.** Its `loss_reason` regex (`RE_OUTCOME`, "has (won|lost) because ...") doesn't match Forge's `has lost due to effect of spell 'X'` (the Demonic Pact loss). That game's `loss_reason` is missing from the JSON.
  - The winner was still counted correctly, because exactly one player "has won".
  - I left `run_sim.py` unchanged because other agents use it. The fix is to also accept `due to`.
- The load-test and hint-test runs used their own user folders (`forge-user-audit/`, `forge-user-override/`), which hold their own `forge.*.log` files.
  - Nothing was written to `%APPDATA%\Forge`: last modified 12:48, before my first run at 13:01.
  - Nothing was written to the shared `forge-user/`.
- One other Forge process (another agent's) was running during some of these runs. That explains the 11-12 s eager start-ups; the uncontended ones were 8.3-9.3 s.

## Files

| File | What it is |
|---|---|
| `card_audit.py` | the audit tool (`scan`, `decks`, `compare`, `report`; usage and the Forge rules it mirrors are in its docstring) |
| `audit/audit.json` | every name with its uses, status, Forge name, script path, flags and `CannotPlayAi` findings |
| `audit/lists.md`, `audit/all-names.md` | generated lists (copied below) |
| `decks/audit/*.dck` | load-test decks |
| `decks/ai-hint-test/*.dck` | the RemoveDeck test decks, the two owned Commander lists and the face-collision decks |
| `logs/audit-*.{log,json}`, `logs/ai-hint-*.{log,json}`, `logs/face-collision*.{log,json}` | raw output of every run quoted here |
| `forge-user-override/Forge/custom/cards/*.txt` | the 5 flag-free script copies used in 4b |

## Full lists (generated by `python card_audit.py report`)

In the "Used in" column, deck uses come first, then products, then pool files, separated by ` / `. `(owned+target)` means the card is in both lists of that deck.

- deck files: 351 names
- product lists: 513 names
- collection + orders: 443 names

### Unsupported (decks + products) (0)

None.

### Unsupported (collection/orders only) (0)

None.

### Naming differences (Scryfall name is not Forge's card name) (2)

| Scryfall name | Forge name | Layout | How it resolves | to_dck writes | Used in |
|---|---|---|---|---|---|
| Murderous Rider // Swift End | Murderous Rider | Adventure | front face (Scryfall 'A // B' is not a Forge card name) | Murderous Rider | mono-black-midrange (target); orzhov-removal (target); gisa-zombies (target) / orders/2026-09-29-shop-e.csv |
| Pollen-Shield Hare // Hare Raising | Pollen-Shield Hare | Adventure | front face (Scryfall 'A // B' is not a Forge card name) | Pollen-Shield Hare | finneas-rabbits (target) |

### Split cards: full 'A // B' is Forge's name (0)

None.

### AI:RemoveDeck:All: the AI never casts or activates these (decks + products) (6)

| Name | Script | Used in |
|---|---|---|
| Beast Within | b/beast_within.txt | selesnya-rabbits (owned+target; Sideboard); finneas-rabbits (owned+target) / collection.csv; orders/received/2026-09-26-shop-h.csv |
| Bolt Bend | b/bolt_bend.txt | fdn-starter-collection / collection.csv |
| Demonic Pact | d/demonic_pact.txt | fdn-starter-collection / collection.csv |
| Devout Decree | d/devout_decree.txt | mono-white-angels (owned+target) / fdn-starter-collection / collection.csv |
| Ghoulcaller Gisa | g/ghoulcaller_gisa.txt | gisa-zombies (owned+target; Commander) / fdc-wretched-ranks [Commander] |
| God-Eternal Bontu | g/god_eternal_bontu.txt | mono-black-midrange (owned); gisa-zombies (owned+target) / fdc-wretched-ranks |

### AI:RemoveDeck:All: the AI never casts or activates these (collection/orders only) (0)

None.

### AI:RemoveDeck:Random: only kept out of random decks (decks + products) (23)

| Name | Script | Used in |
|---|---|---|
| Angelic Accord | a/angelic_accord.txt | giada-angels (target) |
| Ayara, First of Locthwain | a/ayara_first_of_locthwain.txt | mono-black-midrange (owned); gisa-zombies (owned+target) / fdc-wretched-ranks |
| Circuitous Route | c/circuitous_route.txt | fdn-starter-collection / collection.csv |
| Cryptbreaker | c/cryptbreaker.txt | mono-black-zombies (owned+target); gisa-zombies (owned+target) / fdc-wretched-ranks |
| Cut a Deal | c/cut_a_deal.txt | fdc-calling-all-angels |
| Demolition Field | d/demolition_field.txt | fdn-starter-collection / collection.csv |
| Endless Ranks of the Dead | e/endless_ranks_of_the_dead.txt | gisa-zombies (owned+target) / fdc-wretched-ranks |
| Farseek | f/farseek.txt | finneas-rabbits (target) |
| Feldon's Cane | f/feldons_cane.txt | fdn-starter-collection / collection.csv |
| Gnarlback Rhino | g/gnarlback_rhino.txt | gruul-ramp (owned+target) / fdn-starter-collection / collection.csv |
| Goblin Smuggler | g/goblin_smuggler.txt | fdn-beginner-box: Goblins / collection.csv |
| Harmless Offering | h/harmless_offering.txt | fdn-starter-collection / collection.csv |
| Inspiring Call | i/inspiring_call.txt | finneas-rabbits (target) |
| Intangible Virtue | i/intangible_virtue.txt | finneas-rabbits (target) |
| Maze's End | m/mazes_end.txt | fdn-starter-collection / collection.csv |
| Metropolis Reformer | m/metropolis_reformer.txt | mono-white-angels (owned); giada-angels (owned+target) / fdc-calling-all-angels |
| Micromancer | m/micromancer.txt | fdn-starter-collection / collection.csv |
| Mystical Teachings | m/mystical_teachings.txt | fdn-starter-collection / collection.csv |
| Soulless One | s/soulless_one.txt | gisa-zombies (owned+target) / fdc-wretched-ranks |
| Temple of the False God | t/temple_of_the_false_god.txt | fdc-calling-all-angels |
| Unbreathing Horde | u/unbreathing_horde.txt | gisa-zombies (target) / orders/2026-09-29-shop-e.csv |
| Undead Warchief | u/undead_warchief.txt | mono-black-zombies (owned+target); gisa-zombies (owned+target) / fdc-wretched-ranks |
| Well of Lost Dreams | w/well_of_lost_dreams.txt | giada-angels (target) / orders/2026-09-29-shop-e.csv |

### AI:RemoveDeck:Random: only kept out of random decks (collection/orders only) (0)

None.

### AI:RemoveDeck:NonCommander (decks + products) (8)

| Name | Script | Used in |
|---|---|---|
| Angelic Field Marshal | a/angelic_field_marshal.txt | giada-angels (owned+target) / fdc-calling-all-angels |
| Arcane Signet | a/arcane_signet.txt | finneas-rabbits (owned+target); giada-angels (owned+target); gisa-zombies (owned+target) / fdc-calling-all-angels; fdc-wretched-ranks; fdn-starter-collection / collection.csv |
| Command Tower | c/command_tower.txt | finneas-rabbits (owned+target) / fdn-starter-collection / collection.csv |
| Commander's Sphere | c/commanders_sphere.txt | finneas-rabbits (owned+target); giada-angels (owned+target) / fdc-calling-all-angels; fdc-wretched-ranks |
| Folk Hero | f/folk_hero.txt | giada-angels (target) |
| Norn's Choirmaster | n/norns_choirmaster.txt | mono-white-angels (owned); giada-angels (owned+target) / fdc-calling-all-angels |
| Tome of Legends | t/tome_of_legends.txt | giada-angels (owned) / fdc-calling-all-angels |
| War Room | w/war_room.txt | giada-angels (owned+target) / fdc-calling-all-angels |

### AI:RemoveDeck:NonCommander (collection/orders only) (0)

None.

### Flagged cards per deck (quantities as listed) (19)

| Deck (list) | RemoveDeck:All | RemoveDeck:Random | RemoveDeck:NonCommander |
|---|---|---|---|
| casual/gruul-ramp (owned) | - | 1 Gnarlback Rhino | - |
| casual/gruul-ramp (target) | - | 1 Gnarlback Rhino | - |
| casual/mono-black-midrange (owned) | 1 God-Eternal Bontu | 1 Ayara, First of Locthwain | - |
| casual/mono-black-zombies (owned) | - | 1 Cryptbreaker; 1 Undead Warchief | - |
| casual/mono-black-zombies (target) | - | 1 Cryptbreaker; 1 Undead Warchief | - |
| casual/mono-white-angels (owned) | 1 Devout Decree | 1 Metropolis Reformer | 1 Norn's Choirmaster |
| casual/mono-white-angels (target) | 1 Devout Decree | - | - |
| casual/selesnya-rabbits (owned) | 1 Beast Within [Sideboard] | - | - |
| casual/selesnya-rabbits (target) | 1 Beast Within [Sideboard] | - | - |
| commander/finneas-rabbits (owned) | 1 Beast Within | - | 1 Arcane Signet; 1 Command Tower; 1 Commander's Sphere |
| commander/finneas-rabbits (target) | 1 Beast Within | 1 Farseek; 1 Inspiring Call; 1 Intangible Virtue | 1 Arcane Signet; 1 Command Tower; 1 Commander's Sphere |
| commander/giada-angels (owned) | - | 1 Metropolis Reformer | 1 Angelic Field Marshal; 1 Arcane Signet; 1 Commander's Sphere; 1 Norn's Choirmaster; 1 Tome of Legends; 1 War Room |
| commander/giada-angels (target) | - | 1 Angelic Accord; 1 Metropolis Reformer; 1 Well of Lost Dreams | 1 Angelic Field Marshal; 1 Arcane Signet; 1 Commander's Sphere; 1 Folk Hero; 1 Norn's Choirmaster; 1 War Room |
| commander/gisa-zombies (owned) | 1 Ghoulcaller Gisa [Commander]; 1 God-Eternal Bontu | 1 Ayara, First of Locthwain; 1 Cryptbreaker; 1 Endless Ranks of the Dead; 1 Soulless One; 1 Undead Warchief | 1 Arcane Signet |
| commander/gisa-zombies (target) | 1 Ghoulcaller Gisa [Commander]; 1 God-Eternal Bontu | 1 Ayara, First of Locthwain; 1 Cryptbreaker; 1 Endless Ranks of the Dead; 1 Soulless One; 1 Unbreathing Horde; 1 Undead Warchief | 1 Arcane Signet |
| product fdc-calling-all-angels | - | 1 Cut a Deal; 1 Metropolis Reformer; 1 Temple of the False God | 1 Angelic Field Marshal; 1 Arcane Signet; 1 Commander's Sphere; 1 Norn's Choirmaster; 1 Tome of Legends; 1 War Room |
| product fdc-wretched-ranks | 1 Ghoulcaller Gisa [Commander]; 1 God-Eternal Bontu | 1 Ayara, First of Locthwain; 1 Cryptbreaker; 1 Endless Ranks of the Dead; 1 Soulless One; 1 Undead Warchief | 1 Arcane Signet; 1 Commander's Sphere |
| product fdn-beginner-box: Goblins | - | 1 Goblin Smuggler | - |
| product fdn-starter-collection | 1 Bolt Bend; 1 Demonic Pact; 1 Devout Decree | 2 Circuitous Route; 1 Demolition Field; 1 Feldon's Cane; 1 Gnarlback Rhino; 1 Harmless Offering; 1 Maze's End; 1 Micromancer; 1 Mystical Teachings | 1 Arcane Signet; 1 Command Tower |

### Abilities using an ApiType with no AI (CannotPlayAi) (0)

None.

### Other AI: lines (ignored by Forge's parser) (0)

None.

### Scripts with comment lines (3)

| Name | Comments |
|---|---|
| Exsanguinate | # AFLifeLost will be set by LoseLife |
| Gray Merchant of Asphodel | # AFLifeLost will be set by LoseLife |
| Mystical Teachings | # TODO: The AI will currently search for the most expensive valid card in the library. This can be used to the AI's advantage with careful deck design (which is why this card only works in properly de |

### Names that are also another card's back face (Forge picks the real card; tested) (6)

| Name | Also a face of | Used in |
|---|---|---|
| Exsanguinate | Stensian Sanguinist | orzhov-vampires (owned+target) / fdn-starter-collection / collection.csv |
| Lightning Bolt | Emeritus of Conflict | izzet-prowess (owned+target) / collection.csv; orders/received/2026-09-26-shop-h.csv |
| Rampant Growth | Studious First-Year | finneas-rabbits (target) / orders/2026-09-29-shop-e.csv |
| Secret Rendezvous | Joined Researchers | fdc-calling-all-angels |
| Sign in Blood | Scheming Silvertongue | mono-black-midrange (owned); gisa-zombies (owned) / fdc-wretched-ranks |
| Swords to Plowshares | Emeritus of Truce | mono-white-angels (owned+target); orzhov-removal (owned+target); selesnya-rabbits (owned+target; Sideboard); finneas-rabbits (owned+target); giada-angels (owned+target) / fdc-calling-all-angels / collection.csv; orders/received/2026-09-26-shop-h.csv |

### Names with more than one script (0)

None.

### Scripts outside the main folders (upcoming/, rebalanced/) (0)

None.


## Appendix: all 612 names

`In`: deck = a deck file, product = a product list, pool = collection.csv or an order file.

| # | Scryfall name | Forge script | In | AI flags |
|---|---|---|---|---|
| 1 | Abrade | a/abrade.txt | deck+pool+product |  |
| 2 | Abzan Falconer | a/abzan_falconer.txt | deck |  |
| 3 | Adamant Will | a/adamant_will.txt | deck+pool+product |  |
| 4 | Adaptive Automaton | a/adaptive_automaton.txt | deck+pool+product |  |
| 5 | Adventuring Gear | a/adventuring_gear.txt | pool |  |
| 6 | Aegis Turtle | a/aegis_turtle.txt | pool |  |
| 7 | Aggressive Mammoth | a/aggressive_mammoth.txt | deck+pool+product |  |
| 8 | Ajani's Pridemate | a/ajanis_pridemate.txt | deck+pool+product |  |
| 9 | Alania's Pathmaker | a/alanias_pathmaker.txt | pool+product |  |
| 10 | Alania, Divergent Storm | a/alania_divergent_storm.txt | pool+product |  |
| 11 | Always Watching | a/always_watching.txt | deck+product |  |
| 12 | Ambition's Cost | a/ambitions_cost.txt | product |  |
| 13 | Ancestor Dragon | a/ancestor_dragon.txt | pool+product |  |
| 14 | Angel of Finality | a/angel_of_finality.txt | deck+pool+product |  |
| 15 | Angel of Invention | a/angel_of_invention.txt | deck+pool |  |
| 16 | Angel of Sanctions | a/angel_of_sanctions.txt | deck+pool |  |
| 17 | Angel of the Ruins | a/angel_of_the_ruins.txt | deck+product |  |
| 18 | Angel of Vitality | a/angel_of_vitality.txt | deck+pool+product |  |
| 19 | Angelic Accord | a/angelic_accord.txt | deck | RemoveDeck:Random |
| 20 | Angelic Destiny | a/angelic_destiny.txt | deck+pool+product |  |
| 21 | Angelic Edict | a/angelic_edict.txt | pool+product |  |
| 22 | Angelic Field Marshal | a/angelic_field_marshal.txt | deck+product | RemoveDeck:NonCommander |
| 23 | Angelic Sleuth | a/angelic_sleuth.txt | deck+product |  |
| 24 | Arbiter of Woe | a/arbiter_of_woe.txt | pool+product |  |
| 25 | Arcane Epiphany | a/arcane_epiphany.txt | pool+product |  |
| 26 | Arcane Signet | a/arcane_signet.txt | deck+pool+product | RemoveDeck:NonCommander |
| 27 | Arcanis the Omnipotent | a/arcanis_the_omnipotent.txt | pool+product |  |
| 28 | Archangel of Tithes | a/archangel_of_tithes.txt | deck+product |  |
| 29 | Archghoul of Thraben | a/archghoul_of_thraben.txt | deck |  |
| 30 | Archway Angel | a/archway_angel.txt | pool+product |  |
| 31 | Army of the Damned | a/army_of_the_damned.txt | deck+product |  |
| 32 | Aurelia, the Warleader | a/aurelia_the_warleader.txt | pool+product |  |
| 33 | Austere Command | a/austere_command.txt | deck+product |  |
| 34 | Ayara, First of Locthwain | a/ayara_first_of_locthwain.txt | deck+product | RemoveDeck:Random |
| 35 | Ayli, Eternal Pilgrim | a/ayli_eternal_pilgrim.txt | deck+pool+product |  |
| 36 | Azorius Guildgate | a/azorius_guildgate.txt | pool+product |  |
| 37 | Bad Moon | b/bad_moon.txt | deck+product |  |
| 38 | Ball Lightning | b/ball_lightning.txt | pool+product |  |
| 39 | Ballyrush Banneret | b/ballyrush_banneret.txt | pool+product |  |
| 40 | Banefire | b/banefire.txt | product |  |
| 41 | Barren Moor | b/barren_moor.txt | deck+product |  |
| 42 | Basilisk Collar | b/basilisk_collar.txt | pool+product |  |
| 43 | Battle-Rattle Shaman | b/battle_rattle_shaman.txt | pool+product |  |
| 44 | Bear Cub | b/bear_cub.txt | pool+product |  |
| 45 | Beast Within | b/beast_within.txt | deck+pool | RemoveDeck:All |
| 46 | Beast-Kin Ranger | b/beast_kin_ranger.txt | pool+product |  |
| 47 | Bellowing Crier | b/bellowing_crier.txt | pool+product |  |
| 48 | Bigfin Bouncer | b/bigfin_bouncer.txt | pool+product |  |
| 49 | Biogenic Upgrade | b/biogenic_upgrade.txt | pool+product |  |
| 50 | Bishop of Wings | b/bishop_of_wings.txt | deck+product |  |
| 51 | Bishop's Soldier | b/bishops_soldier.txt | pool+product |  |
| 52 | Bite Down | b/bite_down.txt | deck+pool+product |  |
| 53 | Blasphemous Act | b/blasphemous_act.txt | deck+pool |  |
| 54 | Bloodfell Caves | b/bloodfell_caves.txt | pool+product |  |
| 55 | Bloodtithe Collector | b/bloodtithe_collector.txt | deck+pool+product |  |
| 56 | Blossoming Sands | b/blossoming_sands.txt | deck+pool+product |  |
| 57 | Bojuka Bog | b/bojuka_bog.txt | deck+product |  |
| 58 | Bolt Bend | b/bolt_bend.txt | pool+product | RemoveDeck:All |
| 59 | Bonders' Enclave | b/bonders_enclave.txt | deck+product |  |
| 60 | Bontu's Monument | b/bontus_monument.txt | deck+product |  |
| 61 | Boros Charm | b/boros_charm.txt | pool+product |  |
| 62 | Boros Guildgate | b/boros_guildgate.txt | pool+product |  |
| 63 | Bria, Riptide Rogue | b/bria_riptide_rogue.txt | deck+pool+product |  |
| 64 | Brineborn Cutthroat | b/brineborn_cutthroat.txt | pool+product |  |
| 65 | Broken Wings | b/broken_wings.txt | deck+pool+product |  |
| 66 | Burnished Hart | b/burnished_hart.txt | deck+pool+product |  |
| 67 | Burrog Befuddler | b/burrog_befuddler.txt | pool+product |  |
| 68 | Burrowguard Mentor | b/burrowguard_mentor.txt | deck+pool+product |  |
| 69 | Burst Lightning | b/burst_lightning.txt | deck+pool+product |  |
| 70 | Bushwhack | b/bushwhack.txt | pool+product |  |
| 71 | Byrke, Long Ear of the Law | b/byrke_long_ear_of_the_law.txt | deck+pool+product |  |
| 72 | Cadira, Caller of the Small | c/cadira_caller_of_the_small.txt | deck |  |
| 73 | Cancel | c/cancel.txt | pool+product |  |
| 74 | Canopy Vista | c/canopy_vista.txt | deck |  |
| 75 | Carnelian Orb of Dragonkind | c/carnelian_orb_of_dragonkind.txt | pool+product |  |
| 76 | Carrion Feeder | c/carrion_feeder.txt | deck+product |  |
| 77 | Carrot Cake | c/carrot_cake.txt | deck+pool+product |  |
| 78 | Castle Locthwain | c/castle_locthwain.txt | deck+product |  |
| 79 | Cat Collector | c/cat_collector.txt | deck+pool+product |  |
| 80 | Cathar Commando | c/cathar_commando.txt | deck+pool |  |
| 81 | Caves of Koilos | c/caves_of_koilos.txt | deck |  |
| 82 | Cemetery Reaper | c/cemetery_reaper.txt | deck+product |  |
| 83 | Cemetery Recruitment | c/cemetery_recruitment.txt | deck+pool+product |  |
| 84 | Champion of the Perished | c/champion_of_the_perished.txt | deck+product |  |
| 85 | Chaos Warp | c/chaos_warp.txt | deck+pool |  |
| 86 | Charcoal Diamond | c/charcoal_diamond.txt | deck+product |  |
| 87 | Charmed Sleep | c/charmed_sleep.txt | deck+pool+product |  |
| 88 | Charming Prince | c/charming_prince.txt | deck+pool+product |  |
| 89 | Chart a Course | c/chart_a_course.txt | pool+product |  |
| 90 | Cinder Glade | c/cinder_glade.txt | deck |  |
| 91 | Circuitous Route | c/circuitous_route.txt | pool+product | RemoveDeck:Random |
| 92 | Claim Jumper | c/claim_jumper.txt | deck |  |
| 93 | Cleansing Nova | c/cleansing_nova.txt | deck+product |  |
| 94 | Clifftop Lookout | c/clifftop_lookout.txt | deck+pool+product |  |
| 95 | Clinquant Skymage | c/clinquant_skymage.txt | pool+product |  |
| 96 | Cloudblazer | c/cloudblazer.txt | pool+product |  |
| 97 | Colossification | c/colossification.txt | pool+product |  |
| 98 | Command Tower | c/command_tower.txt | deck+pool+product | RemoveDeck:NonCommander |
| 99 | Commander's Sphere | c/commanders_sphere.txt | deck+product | RemoveDeck:NonCommander |
| 100 | Conclave Tribunal | c/conclave_tribunal.txt | deck |  |
| 101 | Confiscate | c/confiscate.txt | pool+product |  |
| 102 | Consumed by Greed | c/consumed_by_greed.txt | deck+product |  |
| 103 | Consuming Aberration | c/consuming_aberration.txt | pool+product |  |
| 104 | Consuming Corruption | c/consuming_corruption.txt | deck+product |  |
| 105 | Corsair Captain | c/corsair_captain.txt | pool+product |  |
| 106 | Coruscation Mage | c/coruscation_mage.txt | deck+pool+product |  |
| 107 | Counterspell | c/counterspell.txt | deck+pool |  |
| 108 | Courageous Goblin | c/courageous_goblin.txt | pool |  |
| 109 | Court of Grace | c/court_of_grace.txt | deck+product |  |
| 110 | Crackling Cyclops | c/crackling_cyclops.txt | pool+product |  |
| 111 | Crash Through | c/crash_through.txt | pool+product |  |
| 112 | Crawling Barrens | c/crawling_barrens.txt | deck+pool+product |  |
| 113 | Crippling Fear | c/crippling_fear.txt | deck |  |
| 114 | Crossway Troublemakers | c/crossway_troublemakers.txt | deck+pool+product |  |
| 115 | Crow of Dark Tidings | c/crow_of_dark_tidings.txt | pool+product |  |
| 116 | Crusader of Odric | c/crusader_of_odric.txt | deck+pool+product |  |
| 117 | Cryptbreaker | c/cryptbreaker.txt | deck+product | RemoveDeck:Random |
| 118 | Cryptic Caves | c/cryptic_caves.txt | pool+product |  |
| 119 | Cultivate | c/cultivate.txt | deck+pool |  |
| 120 | Cultivator's Caravan | c/cultivators_caravan.txt | pool+product |  |
| 121 | Cut a Deal | c/cut_a_deal.txt | product | RemoveDeck:Random |
| 122 | Darksteel Colossus | d/darksteel_colossus.txt | pool+product |  |
| 123 | Dawnwing Marshal | d/dawnwing_marshal.txt | deck+pool+product |  |
| 124 | Day of Judgment | d/day_of_judgment.txt | product |  |
| 125 | Dazzling Angel | d/dazzling_angel.txt | deck+pool+product |  |
| 126 | Deadly Brew | d/deadly_brew.txt | pool+product |  |
| 127 | Deadly Dispute | d/deadly_dispute.txt | deck+pool |  |
| 128 | Deadly Plot | d/deadly_plot.txt | deck+pool+product |  |
| 129 | Deadly Riposte | d/deadly_riposte.txt | pool+product |  |
| 130 | Death Baron | d/death_baron.txt | deck+pool+product |  |
| 131 | Deathmark | d/deathmark.txt | deck+pool+product |  |
| 132 | Defy Death | d/defy_death.txt | product |  |
| 133 | Demolition Field | d/demolition_field.txt | pool+product | RemoveDeck:Random |
| 134 | Demonic Pact | d/demonic_pact.txt | pool+product | RemoveDeck:All |
| 135 | Desecration Demon | d/desecration_demon.txt | deck+pool+product |  |
| 136 | Destroy Evil | d/destroy_evil.txt | product |  |
| 137 | Devout Decree | d/devout_decree.txt | deck+pool+product | RemoveDeck:All |
| 138 | Diamond Mare | d/diamond_mare.txt | pool+product |  |
| 139 | Dictate of Kruphix | d/dictate_of_kruphix.txt | pool+product |  |
| 140 | Dimir Guildgate | d/dimir_guildgate.txt | pool+product |  |
| 141 | Diregraf Colossus | d/diregraf_colossus.txt | deck+product |  |
| 142 | Diregraf Ghoul | d/diregraf_ghoul.txt | deck+pool+product |  |
| 143 | Disenchant | d/disenchant.txt | deck+pool+product |  |
| 144 | Dismal Backwater | d/dismal_backwater.txt | pool+product |  |
| 145 | Dive Down | d/dive_down.txt | pool+product |  |
| 146 | Divine Resilience | d/divine_resilience.txt | deck+pool+product |  |
| 147 | Dragon Fodder | d/dragon_fodder.txt | pool+product |  |
| 148 | Dragon Mage | d/dragon_mage.txt | pool+product |  |
| 149 | Dragonlord's Servant | d/dragonlords_servant.txt | pool+product |  |
| 150 | Dragonmaster Outcast | d/dragonmaster_outcast.txt | pool+product |  |
| 151 | Dread Summons | d/dread_summons.txt | pool+product |  |
| 152 | Dreadwing Scavenger | d/dreadwing_scavenger.txt | pool+product |  |
| 153 | Driver of the Dead | d/driver_of_the_dead.txt | pool+product |  |
| 154 | Drogskol Reaver | d/drogskol_reaver.txt | pool+product |  |
| 155 | Dropkick Bomber | d/dropkick_bomber.txt | pool+product |  |
| 156 | Druid of the Cowl | d/druid_of_the_cowl.txt | deck+pool+product |  |
| 157 | Druid of the Spade | d/druid_of_the_spade.txt | deck+pool+product |  |
| 158 | Dryad Militant | d/dryad_militant.txt | deck+pool+product |  |
| 159 | Duress | d/duress.txt | deck+pool+product |  |
| 160 | Dwynen's Elite | d/dwynens_elite.txt | pool+product |  |
| 161 | Eaten Alive | e/eaten_alive.txt | deck+pool+product |  |
| 162 | Eaten by Piranhas | e/eaten_by_piranhas.txt | pool+product |  |
| 163 | Electrolyze | e/electrolyze.txt | deck |  |
| 164 | Elspeth's Smite | e/elspeths_smite.txt | pool+product |  |
| 165 | Elspeth, Sun's Champion | e/elspeth_suns_champion.txt | deck |  |
| 166 | Elvish Archdruid | e/elvish_archdruid.txt | pool+product |  |
| 167 | Elvish Regrower | e/elvish_regrower.txt | deck+pool+product |  |
| 168 | Emeria Shepherd | e/emeria_shepherd.txt | deck+product |  |
| 169 | Empyrean Eagle | e/empyrean_eagle.txt | pool+product |  |
| 170 | Endless Atlas | e/endless_atlas.txt | deck+product |  |
| 171 | Endless Ranks of the Dead | e/endless_ranks_of_the_dead.txt | deck+product | RemoveDeck:Random |
| 172 | Enigma Drake | e/enigma_drake.txt | deck+pool+product |  |
| 173 | Erudite Wizard | e/erudite_wizard.txt | pool+product |  |
| 174 | Essence Scatter | e/essence_scatter.txt | deck+pool+product |  |
| 175 | Eternal Taskmaster | e/eternal_taskmaster.txt | product |  |
| 176 | Eternal Witness | e/eternal_witness.txt | deck+pool |  |
| 177 | Evolving Wilds | e/evolving_wilds.txt | deck+pool+product |  |
| 178 | Exclusion Mage | e/exclusion_mage.txt | pool+product |  |
| 179 | Exemplar of Light | e/exemplar_of_light.txt | deck+product |  |
| 180 | Exorcise | e/exorcise.txt | deck+product |  |
| 181 | Expedition Map | e/expedition_map.txt | pool+product |  |
| 182 | Experimental Frenzy | e/experimental_frenzy.txt | product |  |
| 183 | Exsanguinate | e/exsanguinate.txt | deck+pool+product |  |
| 184 | Faebloom Trick | f/faebloom_trick.txt | pool+product |  |
| 185 | Fake Your Own Death | f/fake_your_own_death.txt | pool |  |
| 186 | Fanatical Firebrand | f/fanatical_firebrand.txt | pool+product |  |
| 187 | Farseek | f/farseek.txt | deck | RemoveDeck:Random |
| 188 | Fateful Absence | f/fateful_absence.txt | deck+product |  |
| 189 | Fecund Greenshell | f/fecund_greenshell.txt | pool+product |  |
| 190 | Feed the Swarm | f/feed_the_swarm.txt | deck+pool+product |  |
| 191 | Feldon's Cane | f/feldons_cane.txt | pool+product | RemoveDeck:Random |
| 192 | Felidar Cub | f/felidar_cub.txt | pool+product |  |
| 193 | Felidar Retreat | f/felidar_retreat.txt | deck+pool+product |  |
| 194 | Felidar Savior | f/felidar_savior.txt | deck+pool+product |  |
| 195 | Felling Blow | f/felling_blow.txt | deck+pool+product |  |
| 196 | Fiendish Panda | f/fiendish_panda.txt | deck+pool+product |  |
| 197 | Fierce Empath | f/fierce_empath.txt | deck+pool+product |  |
| 198 | Fiery Annihilation | f/fiery_annihilation.txt | deck+pool+product |  |
| 199 | Fiery Cannonade | f/fiery_cannonade.txt | product |  |
| 200 | Fight with Fire | f/fight_with_fire.txt | product |  |
| 201 | Finale of Revelation | f/finale_of_revelation.txt | pool+product |  |
| 202 | Finneas, Ace Archer | f/finneas_ace_archer.txt | deck+pool+product |  |
| 203 | Fire Elemental | f/fire_elemental.txt | pool+product |  |
| 204 | Firemane Commando | f/firemane_commando.txt | deck+product |  |
| 205 | Fireshrieker | f/fireshrieker.txt | pool+product |  |
| 206 | Firespitter Whelp | f/firespitter_whelp.txt | deck+pool+product |  |
| 207 | Flame Lash | f/flame_lash.txt | deck+pool+product |  |
| 208 | Flashfreeze | f/flashfreeze.txt | pool+product |  |
| 209 | Fleeting Distraction | f/fleeting_distraction.txt | pool+product |  |
| 210 | Fleshbag Marauder | f/fleshbag_marauder.txt | deck+product |  |
| 211 | Fog Bank | f/fog_bank.txt | pool+product |  |
| 212 | Folk Hero | f/folk_hero.txt | deck | RemoveDeck:NonCommander |
| 213 | Forest | f/forest.txt | deck+pool+product |  |
| 214 | Fortified Village | f/fortified_village.txt | deck |  |
| 215 | Frenzied Goblin | f/frenzied_goblin.txt | pool+product |  |
| 216 | Fumigate | f/fumigate.txt | deck+pool+product |  |
| 217 | Fynn, the Fangbearer | f/fynn_the_fangbearer.txt | pool+product |  |
| 218 | Garna, Bloodfist of Keld | g/garna_bloodfist_of_keld.txt | pool+product |  |
| 219 | Garruk's Uprising | g/garruks_uprising.txt | deck+pool+product |  |
| 220 | Gate Colossus | g/gate_colossus.txt | pool+product |  |
| 221 | Gatekeeper of Malakir | g/gatekeeper_of_malakir.txt | deck+pool+product |  |
| 222 | Gateway Sneak | g/gateway_sneak.txt | pool+product |  |
| 223 | Geier Reach Sanitarium | g/geier_reach_sanitarium.txt | product |  |
| 224 | Generous Gift | g/generous_gift.txt | deck+pool |  |
| 225 | Ghitu Lavarunner | g/ghitu_lavarunner.txt | pool+product |  |
| 226 | Ghoulcaller Gisa | g/ghoulcaller_gisa.txt | deck+product | RemoveDeck:All |
| 227 | Giada, Font of Hope | g/giada_font_of_hope.txt | deck+pool+product |  |
| 228 | Giant Cindermaw | g/giant_cindermaw.txt | pool+product |  |
| 229 | Giant Growth | g/giant_growth.txt | pool+product |  |
| 230 | Gideon, Ally of Zendikar | g/gideon_ally_of_zendikar.txt | deck |  |
| 231 | Gifted Aetherborn | g/gifted_aetherborn.txt | deck+pool |  |
| 232 | Gigantosaurus | g/gigantosaurus.txt | pool+product |  |
| 233 | Gilded Lotus | g/gilded_lotus.txt | pool+product |  |
| 234 | Glorybringer | g/glorybringer.txt | deck |  |
| 235 | Gnarlback Rhino | g/gnarlback_rhino.txt | deck+pool+product | RemoveDeck:Random |
| 236 | Go for the Throat | g/go_for_the_throat.txt | deck+pool+product |  |
| 237 | Goblin Chainwhirler | g/goblin_chainwhirler.txt | product |  |
| 238 | Goblin Firebomb | g/goblin_firebomb.txt | pool+product |  |
| 239 | Goblin Negotiation | g/goblin_negotiation.txt | pool+product |  |
| 240 | Goblin Oriflamme | g/goblin_oriflamme.txt | pool+product |  |
| 241 | Goblin Smuggler | g/goblin_smuggler.txt | pool+product | RemoveDeck:Random |
| 242 | Goblin Surprise | g/goblin_surprise.txt | pool |  |
| 243 | God-Eternal Bontu | g/god_eternal_bontu.txt | deck+product | RemoveDeck:All |
| 244 | Goldvein Pick | g/goldvein_pick.txt | pool |  |
| 245 | Golgari Guildgate | g/golgari_guildgate.txt | pool+product |  |
| 246 | Good-Fortune Unicorn | g/good_fortune_unicorn.txt | deck |  |
| 247 | Graf Harvest | g/graf_harvest.txt | deck |  |
| 248 | Grasp of Fate | g/grasp_of_fate.txt | deck+product |  |
| 249 | Gratuitous Violence | g/gratuitous_violence.txt | pool+product |  |
| 250 | Grave Titan | g/grave_titan.txt | deck+product |  |
| 251 | Graveborn Muse | g/graveborn_muse.txt | deck+product |  |
| 252 | Gravecrawler | g/gravecrawler.txt | deck+product |  |
| 253 | Graveyard Marshal | g/graveyard_marshal.txt | deck+pool |  |
| 254 | Gray Merchant of Asphodel | g/gray_merchant_of_asphodel.txt | deck+product |  |
| 255 | Grow from the Ashes | g/grow_from_the_ashes.txt | deck+pool |  |
| 256 | Gruul Guildgate | g/gruul_guildgate.txt | deck+pool+product |  |
| 257 | Guttersnipe | g/guttersnipe.txt | deck+pool+product |  |
| 258 | Halana and Alena, Partners | h/halana_and_alena_partners.txt | deck+pool+product |  |
| 259 | Harbinger of the Tides | h/harbinger_of_the_tides.txt | pool+product |  |
| 260 | Harmless Offering | h/harmless_offering.txt | pool+product | RemoveDeck:Random |
| 261 | Harmonize | h/harmonize.txt | deck+pool |  |
| 262 | Harvestrite Host | h/harvestrite_host.txt | deck |  |
| 263 | Head of the Homestead | h/head_of_the_homestead.txt | deck |  |
| 264 | Headless Rider | h/headless_rider.txt | deck+product |  |
| 265 | Heartfire Immolator | h/heartfire_immolator.txt | deck+pool+product |  |
| 266 | Hedron Archive | h/hedron_archive.txt | pool+product |  |
| 267 | Helpful Hunter | h/helpful_hunter.txt | deck+pool+product |  |
| 268 | Herald of Eternal Dawn | h/herald_of_eternal_dawn.txt | deck+product |  |
| 269 | Herald of Faith | h/herald_of_faith.txt | pool+product |  |
| 270 | Herald of War | h/herald_of_war.txt | deck+product |  |
| 271 | Herald's Horn | h/heralds_horn.txt | deck |  |
| 272 | Heraldic Banner | h/heraldic_banner.txt | deck+pool+product |  |
| 273 | Hero's Downfall | h/heros_downfall.txt | deck+pool+product |  |
| 274 | Heroes' Bane | h/heroes_bane.txt | pool+product |  |
| 275 | Heroic Reinforcements | h/heroic_reinforcements.txt | pool+product |  |
| 276 | Hidetsugu's Second Rite | h/hidetsugus_second_rite.txt | pool+product |  |
| 277 | Highborn Vampire | h/highborn_vampire.txt | pool+product |  |
| 278 | Hinterland Sanctifier | h/hinterland_sanctifier.txt | deck+pool+product |  |
| 279 | Hoarding Dragon | h/hoarding_dragon.txt | pool+product |  |
| 280 | Hop to It | h/hop_to_it.txt | deck+pool+product |  |
| 281 | Hungry Ghoul | h/hungry_ghoul.txt | pool+product |  |
| 282 | Icewind Elemental | i/icewind_elemental.txt | pool+product |  |
| 283 | Immersturm Predator | i/immersturm_predator.txt | pool+product |  |
| 284 | Impact Tremors | i/impact_tremors.txt | pool+product |  |
| 285 | Imperious Perfect | i/imperious_perfect.txt | deck+pool+product |  |
| 286 | Incinerating Blast | i/incinerating_blast.txt | deck+pool+product |  |
| 287 | Infernal Grasp | i/infernal_grasp.txt | deck |  |
| 288 | Infernal Idol | i/infernal_idol.txt | deck+product |  |
| 289 | Infestation Sage | i/infestation_sage.txt | pool+product |  |
| 290 | Ingenious Leonin | i/ingenious_leonin.txt | pool+product |  |
| 291 | Inspiration from Beyond | i/inspiration_from_beyond.txt | pool |  |
| 292 | Inspiring Call | i/inspiring_call.txt | deck | RemoveDeck:Random |
| 293 | Inspiring Overseer | i/inspiring_overseer.txt | deck+pool+product |  |
| 294 | Intangible Virtue | i/intangible_virtue.txt | deck | RemoveDeck:Random |
| 295 | Into the Roil | i/into_the_roil.txt | deck+pool+product |  |
| 296 | Invoke the Divine | i/invoke_the_divine.txt | deck+product |  |
| 297 | Involuntary Employment | i/involuntary_employment.txt | pool |  |
| 298 | Island | i/island.txt | deck+pool+product |  |
| 299 | Isolated Chapel | i/isolated_chapel.txt | deck |  |
| 300 | Izzet Guildgate | i/izzet_guildgate.txt | pool+product |  |
| 301 | Jazal Goldmane | j/jazal_goldmane.txt | deck+pool+product |  |
| 302 | Joraga Invocation | j/joraga_invocation.txt | pool+product |  |
| 303 | Josu Vess, Lich Knight | j/josu_vess_lich_knight.txt | deck+product |  |
| 304 | Journey to Nowhere | j/journey_to_nowhere.txt | deck |  |
| 305 | Joust Through | j/joust_through.txt | pool+product |  |
| 306 | Jungle Hollow | j/jungle_hollow.txt | pool+product |  |
| 307 | Kalastria Highborn | k/kalastria_highborn.txt | deck+pool+product |  |
| 308 | Kalitas, Traitor of Ghet | k/kalitas_traitor_of_ghet.txt | deck+product |  |
| 309 | Kargan Dragonrider | k/kargan_dragonrider.txt | pool+product |  |
| 310 | Karplusan Forest | k/karplusan_forest.txt | deck+pool |  |
| 311 | Kindled Fury | k/kindled_fury.txt | pool+product |  |
| 312 | Kitesail Corsair | k/kitesail_corsair.txt | pool+product |  |
| 313 | Knight of Grace | k/knight_of_grace.txt | deck+pool+product |  |
| 314 | Knight of Malice | k/knight_of_malice.txt | deck+pool+product |  |
| 315 | Lathliss, Dragon Queen | l/lathliss_dragon_queen.txt | deck+pool+product |  |
| 316 | Lava Coil | l/lava_coil.txt | product |  |
| 317 | Leonin Skyhunter | l/leonin_skyhunter.txt | pool+product |  |
| 318 | Leonin Vanguard | l/leonin_vanguard.txt | pool+product |  |
| 319 | Lightning Bolt | l/lightning_bolt.txt | deck+pool |  |
| 320 | Lightning Mare | l/lightning_mare.txt | product |  |
| 321 | Lightning Strike | l/lightning_strike.txt | product |  |
| 322 | Lightshell Duo | l/lightshell_duo.txt | pool |  |
| 323 | Liliana's Mastery | l/lilianas_mastery.txt | deck+product |  |
| 324 | Liliana's Reaver | l/lilianas_reaver.txt | deck+product |  |
| 325 | Liliana, Death's Majesty | l/liliana_deaths_majesty.txt | deck |  |
| 326 | Linden, the Steadfast Queen | l/linden_the_steadfast_queen.txt | deck+pool+product |  |
| 327 | Linvala, the Preserver | l/linvala_the_preserver.txt | deck+product |  |
| 328 | Llanowar Elves | l/llanowar_elves.txt | deck+pool+product |  |
| 329 | Lord of the Accursed | l/lord_of_the_accursed.txt | deck+product |  |
| 330 | Lord of the Undead | l/lord_of_the_undead.txt | deck+product |  |
| 331 | Luminarch Aspirant | l/luminarch_aspirant.txt | deck |  |
| 332 | Lyra Dawnbringer | l/lyra_dawnbringer.txt | deck+pool+product |  |
| 333 | Maalfeld Twins | m/maalfeld_twins.txt | pool+product |  |
| 334 | Maelstrom Pulse | m/maelstrom_pulse.txt | pool+product |  |
| 335 | Magnigoth Sentry | m/magnigoth_sentry.txt | pool+product |  |
| 336 | Make a Stand | m/make_a_stand.txt | deck+pool+product |  |
| 337 | Make Your Move | m/make_your_move.txt | deck+pool |  |
| 338 | Marauding Blight-Priest | m/marauding_blight_priest.txt | deck+pool+product |  |
| 339 | Marble Diamond | m/marble_diamond.txt | deck+product |  |
| 340 | Marchesa's Decree | m/marchesas_decree.txt | product |  |
| 341 | Massacre Wurm | m/massacre_wurm.txt | deck+pool+product |  |
| 342 | Maze's End | m/mazes_end.txt | pool+product | RemoveDeck:Random |
| 343 | Mazemind Tome | m/mazemind_tome.txt | deck+pool+product |  |
| 344 | Memorial to Folly | m/memorial_to_folly.txt | deck+product |  |
| 345 | Mentor of the Meek | m/mentor_of_the_meek.txt | deck+pool+product |  |
| 346 | Merchant of Truth | m/merchant_of_truth.txt | deck+product |  |
| 347 | Metallic Mimic | m/metallic_mimic.txt | deck+product |  |
| 348 | Meteor Golem | m/meteor_golem.txt | pool+product |  |
| 349 | Metropolis Reformer | m/metropolis_reformer.txt | deck+product | RemoveDeck:Random |
| 350 | Micromancer | m/micromancer.txt | pool+product | RemoveDeck:Random |
| 351 | Midnight Reaper | m/midnight_reaper.txt | deck+pool+product |  |
| 352 | Midnight Snack | m/midnight_snack.txt | pool+product |  |
| 353 | Mild-Mannered Librarian | m/mild_mannered_librarian.txt | pool+product |  |
| 354 | Mind Spring | m/mind_spring.txt | pool+product |  |
| 355 | Mind Stone | m/mind_stone.txt | deck+product |  |
| 356 | Mindsparker | m/mindsparker.txt | pool+product |  |
| 357 | Mire Triton | m/mire_triton.txt | deck+product |  |
| 358 | Mirkwood Bats | m/mirkwood_bats.txt | deck |  |
| 359 | Mischievous Mystic | m/mischievous_mystic.txt | deck+pool+product |  |
| 360 | Moan of the Unhallowed | m/moan_of_the_unhallowed.txt | deck+product |  |
| 361 | Mocking Sprite | m/mocking_sprite.txt | pool+product |  |
| 362 | Mockingbird | m/mockingbird.txt | pool+product |  |
| 363 | Mold Adder | m/mold_adder.txt | pool+product |  |
| 364 | Moment of Craving | m/moment_of_craving.txt | deck+pool+product |  |
| 365 | Moment of Triumph | m/moment_of_triumph.txt | pool+product |  |
| 366 | Mortify | m/mortify.txt | deck+pool+product |  |
| 367 | Mossborn Hydra | m/mossborn_hydra.txt | pool |  |
| 368 | Mountain | m/mountain.txt | deck+pool+product |  |
| 369 | Murderous Rider // Swift End | m/murderous_rider_swift_end.txt (as Murderous Rider) | deck+pool |  |
| 370 | Mutilate | m/mutilate.txt | deck+product |  |
| 371 | Myojin of Night's Reach | m/myojin_of_nights_reach.txt | pool+product |  |
| 372 | Myriad Landscape | m/myriad_landscape.txt | deck |  |
| 373 | Mystic Archaeologist | m/mystic_archaeologist.txt | pool+product |  |
| 374 | Mystical Teachings | m/mystical_teachings.txt | pool+product | RemoveDeck:Random |
| 375 | Necrotic Hex | n/necrotic_hex.txt | deck+product |  |
| 376 | Negate | n/negate.txt | deck+pool+product |  |
| 377 | Nessian Hornbeetle | n/nessian_hornbeetle.txt | pool |  |
| 378 | New Horizons | n/new_horizons.txt | pool+product |  |
| 379 | Night's Whisper | n/nights_whisper.txt | deck+pool+product |  |
| 380 | Norn's Choirmaster | n/norns_choirmaster.txt | deck+product | RemoveDeck:NonCommander |
| 381 | Noxious Ghoul | n/noxious_ghoul.txt | deck+product |  |
| 382 | Nullpriest of Oblivion | n/nullpriest_of_oblivion.txt | deck+pool+product |  |
| 383 | Ob Nixilis Reignited | o/ob_nixilis_reignited.txt | deck |  |
| 384 | Obliterating Bolt | o/obliterating_bolt.txt | deck+pool+product |  |
| 385 | Offer Immortality | o/offer_immortality.txt | pool+product |  |
| 386 | Open the Graves | o/open_the_graves.txt | deck+product |  |
| 387 | Opt | o/opt.txt | pool+product |  |
| 388 | Ordeal of Nylea | o/ordeal_of_nylea.txt | pool+product |  |
| 389 | Orzhov Guildgate | o/orzhov_guildgate.txt | deck+pool+product |  |
| 390 | Overrun | o/overrun.txt | deck+pool+product |  |
| 391 | Oversold Cemetery | o/oversold_cemetery.txt | product |  |
| 392 | Ovika, Enigma Goliath | o/ovika_enigma_goliath.txt | pool+product |  |
| 393 | Pacifism | p/pacifism.txt | deck+pool+product |  |
| 394 | Patchwork Banner | p/patchwork_banner.txt | deck+product |  |
| 395 | Path to Exile | p/path_to_exile.txt | deck+pool |  |
| 396 | Pearl of Wisdom | p/pearl_of_wisdom.txt | pool+product |  |
| 397 | Pelakka Wurm | p/pelakka_wurm.txt | deck+pool+product |  |
| 398 | Perforating Artist | p/perforating_artist.txt | pool+product |  |
| 399 | Phyrexian Arena | p/phyrexian_arena.txt | deck+product |  |
| 400 | Pileated Provisioner | p/pileated_provisioner.txt | pool+product |  |
| 401 | Pirate's Cutlass | p/pirates_cutlass.txt | pool+product |  |
| 402 | Plague Belcher | p/plague_belcher.txt | deck+pool |  |
| 403 | Plains | p/plains.txt | deck+pool+product |  |
| 404 | Pollen-Shield Hare // Hare Raising | p/pollen_shield_hare_hare_raising.txt (as Pollen-Shield Hare) | deck |  |
| 405 | Prayer of Binding | p/prayer_of_binding.txt | deck+pool+product |  |
| 406 | Predator Ooze | p/predator_ooze.txt | pool+product |  |
| 407 | Preordain | p/preordain.txt | deck+pool |  |
| 408 | Prideful Parent | p/prideful_parent.txt | deck+pool+product |  |
| 409 | Primal Might | p/primal_might.txt | deck+pool+product |  |
| 410 | Prime Speaker Zegana | p/prime_speaker_zegana.txt | pool+product |  |
| 411 | Primeval Bounty | p/primeval_bounty.txt | deck+pool+product |  |
| 412 | Pulse Tracker | p/pulse_tracker.txt | pool+product |  |
| 413 | Pyromancer's Goggles | p/pyromancers_goggles.txt | pool+product |  |
| 414 | Quakestrider Ceratops | q/quakestrider_ceratops.txt | deck+pool+product |  |
| 415 | Quaketusk Boar | q/quaketusk_boar.txt | deck+pool+product |  |
| 416 | Quick Study | q/quick_study.txt | pool+product |  |
| 417 | Quick-Draw Katana | q/quick_draw_katana.txt | pool+product |  |
| 418 | Rabbit Response | r/rabbit_response.txt | deck+pool+product |  |
| 419 | Rabid Bite | r/rabid_bite.txt | deck+pool+product |  |
| 420 | Rabid Gnaw | r/rabid_gnaw.txt | deck+pool+product |  |
| 421 | Radiant Fountain | r/radiant_fountain.txt | product |  |
| 422 | Raging Redcap | r/raging_redcap.txt | pool+product |  |
| 423 | Rakdos Guildgate | r/rakdos_guildgate.txt | pool+product |  |
| 424 | Ramos, Dragon Engine | r/ramos_dragon_engine.txt | pool+product |  |
| 425 | Rampaging Baloths | r/rampaging_baloths.txt | deck+pool+product |  |
| 426 | Rampant Growth | r/rampant_growth.txt | deck+pool |  |
| 427 | Rapacious Dragon | r/rapacious_dragon.txt | pool+product |  |
| 428 | Ravenous Amulet | r/ravenous_amulet.txt | pool+product |  |
| 429 | Ravenous Chupacabra | r/ravenous_chupacabra.txt | deck |  |
| 430 | Ravenous Giant | r/ravenous_giant.txt | deck+pool+product |  |
| 431 | Ravenous Rotbelly | r/ravenous_rotbelly.txt | deck |  |
| 432 | Razorlash Transmogrant | r/razorlash_transmogrant.txt | product |  |
| 433 | Reassembling Skeleton | r/reassembling_skeleton.txt | deck+pool+product |  |
| 434 | Reclamation Sage | r/reclamation_sage.txt | deck+pool+product |  |
| 435 | Redcap Gutter-Dweller | r/redcap_gutter_dweller.txt | pool+product |  |
| 436 | Refute | r/refute.txt | pool+product |  |
| 437 | Regal Caracal | r/regal_caracal.txt | deck+pool+product |  |
| 438 | Rekindling Phoenix | r/rekindling_phoenix.txt | product |  |
| 439 | Release the Dogs | r/release_the_dogs.txt | deck+pool+product |  |
| 440 | Repel Calamity | r/repel_calamity.txt | deck+pool+product |  |
| 441 | Resolute Reinforcements | r/resolute_reinforcements.txt | deck+pool+product |  |
| 442 | Reya Dawnbringer | r/reya_dawnbringer.txt | product |  |
| 443 | Righteous Valkyrie | r/righteous_valkyrie.txt | deck+product |  |
| 444 | Rite of Replication | r/rite_of_replication.txt | pool+product |  |
| 445 | River's Rebuke | r/rivers_rebuke.txt | pool+product |  |
| 446 | Rogue's Passage | r/rogues_passage.txt | deck+pool+product |  |
| 447 | Rootborn Defenses | r/rootborn_defenses.txt | deck |  |
| 448 | Rootbound Crag | r/rootbound_crag.txt | deck+pool |  |
| 449 | Rotting Regisaur | r/rotting_regisaur.txt | deck |  |
| 450 | Ruby, Daring Tracker | r/ruby_daring_tracker.txt | deck+pool+product |  |
| 451 | Rugged Highlands | r/rugged_highlands.txt | deck+pool+product |  |
| 452 | Runaway Steam-Kin | r/runaway_steam_kin.txt | product |  |
| 453 | Sakura-Tribe Elder | s/sakura_tribe_elder.txt | deck+pool |  |
| 454 | Sanguine Indulgence | s/sanguine_indulgence.txt | pool+product |  |
| 455 | Savage Ventmaw | s/savage_ventmaw.txt | deck+pool+product |  |
| 456 | Savannah Lions | s/savannah_lions.txt | deck+pool+product |  |
| 457 | Scavenging Ooze | s/scavenging_ooze.txt | deck+pool |  |
| 458 | Scorching Dragonfire | s/scorching_dragonfire.txt | deck+pool+product |  |
| 459 | Scoured Barrens | s/scoured_barrens.txt | deck+pool+product |  |
| 460 | Scourge of Nel Toth | s/scourge_of_nel_toth.txt | pool |  |
| 461 | Search the Premises | s/search_the_premises.txt | product |  |
| 462 | Secluded Steppe | s/secluded_steppe.txt | deck+product |  |
| 463 | Secret Rendezvous | s/secret_rendezvous.txt | product |  |
| 464 | Seeker's Folly | s/seekers_folly.txt | deck+pool+product |  |
| 465 | Segovian Angel | s/segovian_angel.txt | product |  |
| 466 | Seismic Rupture | s/seismic_rupture.txt | pool+product |  |
| 467 | Seize the Spoils | s/seize_the_spoils.txt | pool+product |  |
| 468 | Selesnya Guildgate | s/selesnya_guildgate.txt | deck+pool+product |  |
| 469 | Sephara, Sky's Blade | s/sephara_skys_blade.txt | deck+product |  |
| 470 | Seraph of the Sword | s/seraph_of_the_sword.txt | deck+product |  |
| 471 | Seraph Sanctuary | s/seraph_sanctuary.txt | deck+product |  |
| 472 | Serra Avenger | s/serra_avenger.txt | deck+product |  |
| 473 | Serra Redeemer | s/serra_redeemer.txt | deck+pool+product |  |
| 474 | Shineshadow Snarl | s/shineshadow_snarl.txt | deck |  |
| 475 | Shipwreck Dowser | s/shipwreck_dowser.txt | pool+product |  |
| 476 | Shivan Reef | s/shivan_reef.txt | deck+pool |  |
| 477 | Shock | s/shock.txt | product |  |
| 478 | Sigarda's Vanguard | s/sigardas_vanguard.txt | deck |  |
| 479 | Sign in Blood | s/sign_in_blood.txt | deck+product |  |
| 480 | Simic Guildgate | s/simic_guildgate.txt | pool+product |  |
| 481 | Skeleton Archer | s/skeleton_archer.txt | pool+product |  |
| 482 | Skyraker Giant | s/skyraker_giant.txt | deck+pool+product |  |
| 483 | Skyship Buccaneer | s/skyship_buccaneer.txt | pool+product |  |
| 484 | Snakeskin Veil | s/snakeskin_veil.txt | deck+pool+product |  |
| 485 | Sol Ring | s/sol_ring.txt | deck+pool+product |  |
| 486 | Sorcerous Spyglass | s/sorcerous_spyglass.txt | deck+pool+product |  |
| 487 | Sorin the Mirthless | s/sorin_the_mirthless.txt | deck |  |
| 488 | Soul-Guide Lantern | s/soul_guide_lantern.txt | deck+pool+product |  |
| 489 | Soul-Shackled Zombie | s/soul_shackled_zombie.txt | pool |  |
| 490 | Soulless One | s/soulless_one.txt | deck+product | RemoveDeck:Random |
| 491 | Speaker of the Heavens | s/speaker_of_the_heavens.txt | product |  |
| 492 | Spectral Sailor | s/spectral_sailor.txt | pool+product |  |
| 493 | Spell Pierce | s/spell_pierce.txt | deck+pool |  |
| 494 | Sphinx of the Final Word | s/sphinx_of_the_final_word.txt | pool+product |  |
| 495 | Spitfire Lagac | s/spitfire_lagac.txt | pool |  |
| 496 | Springbloom Druid | s/springbloom_druid.txt | deck+pool+product |  |
| 497 | Sprite Dragon | s/sprite_dragon.txt | deck |  |
| 498 | Stab | s/stab.txt | deck+pool |  |
| 499 | Starlight Snare | s/starlight_snare.txt | pool+product |  |
| 500 | Starnheim Aspirant | s/starnheim_aspirant.txt | deck+product |  |
| 501 | Stasis Snare | s/stasis_snare.txt | deck+pool+product |  |
| 502 | Steel Hellkite | s/steel_hellkite.txt | pool+product |  |
| 503 | Storm Fleet Spy | s/storm_fleet_spy.txt | pool+product |  |
| 504 | Stormcatch Mentor | s/stormcatch_mentor.txt | deck+pool+product |  |
| 505 | Stroke of Midnight | s/stroke_of_midnight.txt | deck+pool+product |  |
| 506 | Stromkirk Bloodthief | s/stromkirk_bloodthief.txt | pool+product |  |
| 507 | Stromkirk Noble | s/stromkirk_noble.txt | pool+product |  |
| 508 | Strongbox Raider | s/strongbox_raider.txt | pool+product |  |
| 509 | Sulfur Falls | s/sulfur_falls.txt | deck |  |
| 510 | Sun-Blessed Healer | s/sun_blessed_healer.txt | deck+pool |  |
| 511 | Sunblast Angel | s/sunblast_angel.txt | deck+product |  |
| 512 | Sunpetal Grove | s/sunpetal_grove.txt | deck |  |
| 513 | Sure Strike | s/sure_strike.txt | pool |  |
| 514 | Surrak, the Hunt Caller | s/surrak_the_hunt_caller.txt | deck+pool+product |  |
| 515 | Suspicious Shambler | s/suspicious_shambler.txt | pool+product |  |
| 516 | Swab Goblin | s/swab_goblin.txt | pool+product |  |
| 517 | Swamp | s/swamp.txt | deck+pool+product |  |
| 518 | Swiftfoot Boots | s/swiftfoot_boots.txt | deck+pool+product |  |
| 519 | Swiftwater Cliffs | s/swiftwater_cliffs.txt | deck+pool+product |  |
| 520 | Sword of Vengeance | s/sword_of_vengeance.txt | pool+product |  |
| 521 | Swords to Plowshares | s/swords_to_plowshares.txt | deck+pool+product |  |
| 522 | Sylvan Scavenging | s/sylvan_scavenging.txt | deck+pool |  |
| 523 | Syphon Flesh | s/syphon_flesh.txt | product |  |
| 524 | Syr Alin, the Lion's Claw | s/syr_alin_the_lions_claw.txt | deck+pool+product |  |
| 525 | Tajuru Pathwarden | t/tajuru_pathwarden.txt | deck+pool+product |  |
| 526 | Tatyova, Benthic Druid | t/tatyova_benthic_druid.txt | pool+product |  |
| 527 | Taurean Mauler | t/taurean_mauler.txt | pool+product |  |
| 528 | Teach by Example | t/teach_by_example.txt | pool+product |  |
| 529 | Tempest Djinn | t/tempest_djinn.txt | pool+product |  |
| 530 | Temple of Abandon | t/temple_of_abandon.txt | deck+pool+product |  |
| 531 | Temple of Deceit | t/temple_of_deceit.txt | pool+product |  |
| 532 | Temple of Enlightenment | t/temple_of_enlightenment.txt | pool+product |  |
| 533 | Temple of Epiphany | t/temple_of_epiphany.txt | deck+pool+product |  |
| 534 | Temple of Malady | t/temple_of_malady.txt | pool+product |  |
| 535 | Temple of Malice | t/temple_of_malice.txt | pool+product |  |
| 536 | Temple of Mystery | t/temple_of_mystery.txt | pool+product |  |
| 537 | Temple of Plenty | t/temple_of_plenty.txt | deck+pool+product |  |
| 538 | Temple of Silence | t/temple_of_silence.txt | deck+pool+product |  |
| 539 | Temple of the False God | t/temple_of_the_false_god.txt | product | RemoveDeck:Random |
| 540 | Temple of Triumph | t/temple_of_triumph.txt | pool+product |  |
| 541 | Tendrils of Corruption | t/tendrils_of_corruption.txt | deck+product |  |
| 542 | Terror of Mount Velus | t/terror_of_mount_velus.txt | deck+pool+product |  |
| 543 | Thieving Otter | t/thieving_otter.txt | pool+product |  |
| 544 | Think Twice | t/think_twice.txt | deck+pool+product |  |
| 545 | Thornweald Archer | t/thornweald_archer.txt | pool+product |  |
| 546 | Thornwood Falls | t/thornwood_falls.txt | pool+product |  |
| 547 | Thraben Watcher | t/thraben_watcher.txt | deck+product |  |
| 548 | Thragtusk | t/thragtusk.txt | deck+pool |  |
| 549 | Thrashing Brontodon | t/thrashing_brontodon.txt | pool+product |  |
| 550 | Three Tree Mascot | t/three_tree_mascot.txt | deck+pool+product |  |
| 551 | Thrill of Possibility | t/thrill_of_possibility.txt | pool+product |  |
| 552 | Tolarian Terror | t/tolarian_terror.txt | deck+pool+product |  |
| 553 | Tome of Legends | t/tome_of_legends.txt | deck+product | RemoveDeck:NonCommander |
| 554 | Tragic Slip | t/tragic_slip.txt | pool |  |
| 555 | Tranquil Cove | t/tranquil_cove.txt | pool+product |  |
| 556 | Treeguard Duo | t/treeguard_duo.txt | deck+pool+product |  |
| 557 | Tribute to Hunger | t/tribute_to_hunger.txt | deck+pool+product |  |
| 558 | Trygon Predator | t/trygon_predator.txt | pool+product |  |
| 559 | Twinblade Blessing | t/twinblade_blessing.txt | pool+product |  |
| 560 | Twinblade Paladin | t/twinblade_paladin.txt | deck+pool+product |  |
| 561 | Unbreathing Horde | u/unbreathing_horde.txt | deck+pool | RemoveDeck:Random |
| 562 | Uncharted Haven | u/uncharted_haven.txt | pool+product |  |
| 563 | Undead Augur | u/undead_augur.txt | deck+product |  |
| 564 | Undead Butler | u/undead_butler.txt | deck+product |  |
| 565 | Undead Warchief | u/undead_warchief.txt | deck+product | RemoveDeck:Random |
| 566 | Undying Malice | u/undying_malice.txt | pool+product |  |
| 567 | Unflinching Courage | u/unflinching_courage.txt | pool+product |  |
| 568 | Unsummon | u/unsummon.txt | pool+product |  |
| 569 | Untamed Hunger | u/untamed_hunger.txt | pool+product |  |
| 570 | Valkyrie Harbinger | v/valkyrie_harbinger.txt | deck |  |
| 571 | Valley Questcaller | v/valley_questcaller.txt | deck |  |
| 572 | Valorous Stance | v/valorous_stance.txt | deck+pool+product |  |
| 573 | Vampire Interloper | v/vampire_interloper.txt | pool+product |  |
| 574 | Vampire Neonate | v/vampire_neonate.txt | deck+pool+product |  |
| 575 | Vampire Nighthawk | v/vampire_nighthawk.txt | deck+pool+product |  |
| 576 | Vampire of the Dire Moon | v/vampire_of_the_dire_moon.txt | deck |  |
| 577 | Vampire Spawn | v/vampire_spawn.txt | deck+pool+product |  |
| 578 | Vampiric Rites | v/vampiric_rites.txt | deck+pool+product |  |
| 579 | Vanguard Seraph | v/vanguard_seraph.txt | deck+product |  |
| 580 | Vanquisher's Banner | v/vanquishers_banner.txt | deck+product |  |
| 581 | Vengeful Bloodwitch | v/vengeful_bloodwitch.txt | deck+pool+product |  |
| 582 | Vengeful Dead | v/vengeful_dead.txt | deck+product |  |
| 583 | Venom Connoisseur | v/venom_connoisseur.txt | pool+product |  |
| 584 | Viashino Pyromancer | v/viashino_pyromancer.txt | pool+product |  |
| 585 | Victimize | v/victimize.txt | deck+pool |  |
| 586 | Vile Entomber | v/vile_entomber.txt | pool+product |  |
| 587 | Vizier of the Menagerie | v/vizier_of_the_menagerie.txt | deck+pool+product |  |
| 588 | Volley Veteran | v/volley_veteran.txt | pool+product |  |
| 589 | Voracious Greatshark | v/voracious_greatshark.txt | deck+pool+product |  |
| 590 | War Room | w/war_room.txt | deck+product | RemoveDeck:NonCommander |
| 591 | Wardens of the Cycle | w/wardens_of_the_cycle.txt | pool+product |  |
| 592 | Warren Elder | w/warren_elder.txt | deck+pool+product |  |
| 593 | Waterspout Warden | w/waterspout_warden.txt | pool+product |  |
| 594 | Wayfarer's Bauble | w/wayfarers_bauble.txt | deck+pool |  |
| 595 | Well of Lost Dreams | w/well_of_lost_dreams.txt | deck+pool | RemoveDeck:Random |
| 596 | Wight of Precinct Six | w/wight_of_precinct_six.txt | deck+product |  |
| 597 | Wildborn Preserver | w/wildborn_preserver.txt | pool+product |  |
| 598 | Wildheart Invoker | w/wildheart_invoker.txt | deck+pool+product |  |
| 599 | Wildwood Scourge | w/wildwood_scourge.txt | deck+pool+product |  |
| 600 | Wilt-Leaf Liege | w/wilt_leaf_liege.txt | deck+pool+product |  |
| 601 | Wind-Scarred Crag | w/wind_scarred_crag.txt | pool+product |  |
| 602 | Wishclaw Talisman | w/wishclaw_talisman.txt | pool+product |  |
| 603 | Witch's Cottage | w/witchs_cottage.txt | deck+product |  |
| 604 | Withering Torment | w/withering_torment.txt | deck+product |  |
| 605 | Witness Protection | w/witness_protection.txt | deck+pool+product |  |
| 606 | Wizard's Lightning | w/wizards_lightning.txt | product |  |
| 607 | Wojek Investigator | w/wojek_investigator.txt | deck+product |  |
| 608 | Youthful Valkyrie | y/youthful_valkyrie.txt | deck+pool+product |  |
| 609 | Zetalpa, Primal Dawn | z/zetalpa_primal_dawn.txt | pool+product |  |
| 610 | Zombify | z/zombify.txt | pool+product |  |
| 611 | Zul Ashur, Lich Lord | z/zul_ashur_lich_lord.txt | deck+product |  |
| 612 | Zulaport Cutthroat | z/zulaport_cutthroat.txt | pool |  |
