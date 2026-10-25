# Deck Lab: plan

A web page for building and testing Magic decks, hosted on the home PC and used from phones and the iPad on the home network, and from anywhere at https://decklab.example.com.

- **Status:** Milestones 0-8 are built, and so are the features added since: simulation speed and accuracy (waves 1-3), accessories, tokens, accounts with member collections, adding a precon, the UI redesign (2026-10-13), and the move to a database, phases 1-5 (5a, the cleanup, on 2026-10-12; 5b, retiring the rollback, on 2026-10-14; the week of side-by-side checks ended clean on 2026-10-19, with its report). What each one did, its decisions and its known low issues are in [HISTORY.md](HISTORY.md). What's left is under "Still to do" below.
- **Written:** 2026-09-29
- **Design model:** personas, journeys, user stories with their status and a gap analysis (2026-10-13) are in [design/](design/README.md); [design/gap-analysis.md](design/gap-analysis.md) compares this list with the stories.
- **Who uses it:** the two home players (Matt and User1), who share the card pool, and (since 2026-10-10) User2, User3 and User4, each with their own collection and decks

## Still to do

The index of open work, with its order (NOW), is [TODO.md](../TODO.md) at the repo's root; this list keeps the details of the items it points to.

The database move is finished: phase 5b is built, and the week of side-by-side checks ended clean on 2026-10-19 (`DB#1`, its report in [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md)). This section owns details, while TODO.md owns the order.

1. **Moving storage to a database** (decided 2026-10-11): PostgreSQL on the PC instead of git-tracked files. The design is under "Moving storage to a database" below. Phase 1 (the foundation), phase 2 (wishlists, settings, the simulations mode, play records and the Activity page), phase 3 (the inventory), phase 4 (decks and accessories), phase 5a (the cleanup and a nightly check of the data, 2026-10-12) and phase 5b (retiring the rollback, 2026-10-14, at Matt's say-so after two clean nights) are built. The week of side-by-side checks ended clean on 2026-10-19; its report is [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md). Open questions left by phases 3 and 4, for the user (details under "Phases"):
   - (Settled and built 2026-10-13: writes by a person picked on the home network now follow the picked profile's permissions, as through the tunnel, so User2 picked at home can't change home's collection or tokens, and a refused write's answer carries only its reason; a request naming nobody (a script) still passes. Design story E10-S03; HISTORY.md, "Home-network writes and the Game log".)
   - (Settled and built 2026-10-18 with E10-S29: no admin sees or changes another space's collection, tokens, decks or games on the page, and home's records are home's only, so a person-space admin wouldn't see home; E10-S19 built with it. HISTORY.md, "Collections and tokens are seen only in their own space".)
   - **Pending-product correction, cancellation and mistaken-order removal are built** (2026-10-15, E6-S08/E6-S24): Shopping and the command line preview each change with its affected deck tables. Cancellation retains the product as history, excluded from incoming supply and the library; removal refuses any received part. Recorded fulfilled queue quantities can return with cancellation and always return with removal. Older orders without fulfilment provenance warn for manual queue review rather than guessing. Product and token corrections preserve the original recorded purchase intent, with warnings when it may differ from the corrected contents.
   - **Deck rename, retirement and restoration are built** (E1-S19, completed 2026-10-16). More > Rename deck reviews the title and derived id, keeps immutable history and resolves reserved earlier addresses for sources, games and matchups. Cards, build status and kit stay unchanged; packing checks require reconfirmation. Rename needs migration 0010; older schemas retain existing reads and saves. An editable unbuilt deck can be retired with a reason and restored from History under its current id, retaining its earlier addresses.
   - (Settled in phase 4: deck pages and the library now hide another space's counts, token chips and table from viewers who can't see that space's inventory.)
2. **AI fixes, round 1** (merged, installed and measured 2026-10-20/21; [forge-trial/ai-round1-results.md](forge-trial/ai-round1-results.md)): `etb-harmless-1` adopted in The Free Peoples' pilot on 2026-10-21, the others not. Replayed and cleaned up the same day; done. The earlier backlog (AI profiles, the team-pump fix and the other override sets) follows as `FG#3`.
3. **Forge 2.0.16** (about mid-November 2026): move Deck Lab's fork of Forge onto it, check the overrides, and replay every matchup. The post-build checks are one command since 2026-10-21 (`upgrade-check`, E11-S15).
4. ~~**Round-robin rankings** of all decks.~~ **Done 2026-10-15** (E3-S10): Matchups has a Rankings view for each format, with ratings, likely rank ranges, unsettled lists and exclusion reasons. Disconnected groups have separate ranks; current lists outside the field remain visible.
5. **4-player Commander pods** on the page.
6. **Testing sideboard plans.**
7. **Tokens extras**: how many of each a game needs, tokens made for the opponent, and dice and counters. (Rows with no printing show labelled example art since the UI redesign.)
8. **Accessories extras**: thumbnails in lists. Device picture upload is built (2026-10-15, E8-S02), with product storage controls and a product kit command (E8-S11/E8-S18; HISTORY.md). Separate sleeves per deck within a product is dropped: superseded by item 11.
9. ~~**Card pictures on the Receipts page**~~ (asked for 2026-10-12): **done 2026-10-13** in the UI redesign: Receive delivery is a check-off board of every row's picture (HISTORY.md, "UI redesign").
10. **UI redesign follow-ups** (the redesign of [UI-REVIEW.md](UI-REVIEW.md) is built; these were left open by its reviews):
    - ~~**No page lists every out-of-date table.**~~ **Done 2026-10-13** (design stories E7-S09 and E11-S10): the Decks page has a "Tables out of date" list with Update all (one change) and the decks it can't update and why; the Collection page's saves and Receive delivery's note link to it, and `collection merge`, `deck push` and `deck new` name the decks they leave out of date (HISTORY.md, "Tables out of date").
    - **Phones and the iPad themselves:** Matt reports portrait and landscape checks passing on the real iPhone 15 Pro and M2 11-inch iPad (2026-10-15, following the Home Screen/layout check). The iPhone 15 Pro quantity-field appearance, keyboard-open save and History attribution, count restoration, card-viewer swipes, Safari Share error fix and larger receipt image also pass. The [Safari Simulator suite](safari/EVIDENCE.md) now passes all six configurations, including receipt controls and gestures, keyboard-open Save/History and native Home Screen use. E2-S22 remains partial for physical hardware and touch usability after the fixes: receipt controls/swipe margins and keyboard/native-browser behavior on the actual household devices, including the remaining iPad and iPhone 17 Pro observations. The physical iPad's exact model remains unconfirmed; the selected iPad Air 11-inch (M2) Simulator is not a hardware match claim. Detailed device results remain in E2-S22 in design/stories.md; repeat functional regressions with the suite.
    - **The Quick edit** (phones) now has Notes, Substitutes, Mark write-up as current, Deck details and Paste a list (E2-S05, built 2026-10-15). The picture look, side panel and Try a change still need a larger screen. Physical-device acceptance remains above.
    - ~~**Sortable tables.**~~ **Done 2026-10-15** (E5-S22): the deck price table has native Card, Missing and ~AUD missing header buttons, local sorting with unknown prices last, and a compact unit estimate beneath each card name. No new fetch or write is needed.

11. **Owner decisions of 2026-10-13** (answers to [design/gap-analysis.md](design/gap-analysis.md)'s questions; the stories are in [design/stories.md](design/stories.md)):
    - **Sleeves may be shared.** One sleeves row can be used by several built decks and intact products; it's up to the players not to play two of them at once. This reverses "a design belongs to one holder" and "no two built decks share a colour". **Built 2026-10-13** (E8-S20): the picker, the editor and `deck push` accept sleeves another holder has ("Also used by X", with Use them here too or Move them here), `accessories check` no longer reports shared designs or colours, each holder's sleeve count is checked on its own, the Packing plan notes two chosen holders in one design, and AGENTS.md states the new rule (HISTORY.md, "Shared sleeves").
    - **The Game log is private to home:** User2, User3 and User4 shouldn't see the household's games on `#/play` or its API. **Built 2026-10-13** (E10-S24): each viewer sees only the games and plans with a deck of their own space (HISTORY.md, "Home-network writes and the Game log").
    - **Matt's own command-line writes** show as his on the Activity page, apart from Claude's (built 2026-10-15, E11-S07: `--actor matt`; omit it for Claude).
    - **The purchase queue and orders on the pages:** queue editing and recording orders are built (2026-10-15, E5-S06/E6-S02). Order corrections, pending arrival checks, card/token details, pending products, additional-copy marks and shipment splits are built too. E6-S24, E6-S07 and E6-S08 are built: pending cards, tokens or products can be cancelled with a reason and a reviewed queue-restoration offer; an unreceived mistaken order can be removed with its known fulfilled quantities returned. Each is one audited change with deck-table refresh, using the same command-line operation. Historical orders without provenance need manual queue review. Product-list and token-name corrections preserve the original recorded intent with review warnings; ticked-row receipt selection is built too (E6-S06, 2026-10-15): the preview identifies arrived/pending parts and one audited save receives only selected cards/tokens while preserving remainder checks and recorded fulfilment attribution. Products remain whole. Physical-device acceptance remains E2-S22. Buying views are built too (E5-S04/E5-S07/E5-S09/E5-S22): combined individual home-deck shortfalls, dated reference prices, By shop and sortable deck prices. Reprint follow-ups are built (E5-S11, 2026-10-16): cached paper-printing set/date evidence with snapshot coverage, and manual price-review offers for Waiting for reprint. Unknown check dates and missing data stay explicit; opening the review changes no queue state, prices, dates or scheduled work.
    - **User1 can ask from the page** for a card to be bought or a Forge run (Matt approves); low priority, as she'll often just say so.
    - **Not wanted:** expected arrival dates on orders, phones keeping last-seen deck lists while the PC is off (an "off" message is enough), backing up Forge results (they can be replayed), and more than minimal rules teaching.
    - **Done:** Deck Lab starts at logon (`homenet install --at-logon`, 2026-10-13). Running with nobody logged on isn't needed (Matt, 2026-10-13: he's the PC's only user and never logs off, so it's either logged on or off); the backup's catch-up run after the PC was off covers the rest.
    - **Commander nights:** the household aims for Bracket 2 (Matt, 2026-10-13). Recording the usual night's expectations is built (E9-S20, 2026-10-16): one audited home-only note, edited by home admins in Settings and shown on home Commander pages. Name is required; venue, household target, published range, house rules and checked date remain optional and unknown until entered. It seeds no current venue facts and enforces no house rules; migration 0011 stores the revision and clear tombstone.
    - **Private by default:** phases 1–4 of [design/member-template.md §4](design/member-template.md#4-what-shipped-and-the-remaining-build-order) are built and Matt confirms User5's invite was sent (2026-10-18). Visibility storage, public readers/owner controls, Activity, history, Forge privacy and public kit are built in code (2026-10-18). Member export, exact preview, guarded audited apply, durable recovery and departure admission are built in code. Migrations 0012 and 0013 were applied and the server restarted on committed code on 2026-10-19, so privacy and guarded member departure are live; nothing is switched Public yet and no member has been removed. Public means read-only to everyone signed in, and only the owner can change visibility; no live switches are flipped as part of building this. Each control waits for its reader checks, not the check week's end. E10-S41 (per-deck public) stays deferred until requested. The template owns the slices and dependencies; TODO.md owns their order. Decisions A–K remain settled.
Each finished feature in [HISTORY.md](HISTORY.md) also lists its "known low issues, left open". None of them is planned; fix one when it gets in the way.

### Details

- ~~round-robin rankings of all decks~~: done 2026-10-15 (E3-S10). The read-only Rankings view on `#/matchups` uses current saved results and exact current field membership, separates disconnected rating groups and shows unrated or excluded lists with reasons. It starts no Forge games;
- 4-player Commander pods on the page (they work; the combined run's M6 played 300 with plain Forge, 0.41 minutes a pod on average in its main series of 200, as statistics only, since they don't replay exactly);
- testing sideboard plans;
- tokens: how many of each a game needs (counted from game logs, perhaps), telling tokens made for the opponent apart, and dice and counters as a second kind of inventory (an owned row with no printing recorded shows example art of a token with that name, labelled, since 2026-10-13);
- accessories: small thumbnails rather than full pictures in lists. Device picture upload, product keep-intact/break-up controls and the product kit command are built (2026-10-15, E8-S02/E8-S11/E8-S18). Separate sleeves per deck within a product was dropped on 2026-10-13: sleeves may now be shared, item 11;
- ~~card pictures on the Receipts page~~: done 2026-10-13 in the UI redesign (UI-REVIEW.md WP6): each pending part is a grid of its rows' pictures with a tick each (the recorded printing, else the card's default picture in a dashed frame that says so), tokens with their front and back, a product's cards by deck and section, 3 a row on a phone; a tap opens the row's sheet;
- **AI fixes, round 1:** measured 2026-10-20/21, `etb-harmless-1` adopted for TFP, replayed 2026-10-21 (item 2 above; [forge-trial/ai-round1-results.md](forge-trial/ai-round1-results.md)).
- **more experiment games, on an idle PC** (`FG#3`): the team-pump fix (`team-pump-1`: Rabbits +4.1 points against Vampires, still without its mirror test), the six AI-profile arms (Rabbits on Reckless and on DLAggro, Gruul and Angels on Reckless, Izzet on DLControl, Mono-Black Midrange on Cautious: about 1,100 to 3,200 games a pair where the report gives a number), and the override sets `etb`, `hints`, `tgt`, `flash`, `etb-flagged` and `tgt-gift`. About 2-4 hours of idle PC (an estimate). Also worth a look then: Rabbits vs Vampires ran 1.49x faster with every game patch off (B7-off; one fresh-pool round against B2's warm ones, which each had a clock stop while B7-off's had none). The runs go through `experiment` (the combined run's specs are in its `inputs/exp-*.json`). Adopting anything afterwards re-keys the matchups of the lists it touches, which then need a `replay`, so adoptions are best decided together;
- **Forge 2.0.16** (expected about mid-November 2026, an estimate): it should bring the speed PRs R17 would have built in a side build (#11314, #11981 and #11366). The upgrade: rebase the fork's `decklab` branch (`C:\VSProjects\forge`, which since 2026-10-11 holds Deck Lab's changes to `AbstractMulligan`, `AiController`, `AiAttackController` and `Match`, and its AI fixes) onto the 2.0.16 tag, resolve conflicts, build and install it with its `decklab/install.py` (README.md, "Deck Lab's own Forge", has the steps; `python -m decklab.lib.forge upgrade-check --plan forge-2.0.16` prints them), then `python -m decklab.lib.forge upgrade-check` (built 2026-10-21, E11-S15): `cardlog-check`, `serve-check` and the card-script overrides' upstream check (`overrides check`; `overrides make` when one no longer fits, since an override isn't used while Forge's script differs from the one it was made from), with one summary and `replay --dry-run`'s games and rough time; and a `replay` of every matchup, since the engine changes. If 2.0.16 isn't out by 2026-12-15, or leaves out #11314 and #11981, run the one-off side-build A/B in [forge-trial/sim-wave3-contract.md](forge-trial/sim-wave3-contract.md) §13.

## Design

### Goal

From 2026-10-03 (simulation wave 1, R03) the lead is judged on the headline range when every game
has a winner; with draws, timeouts or errors it uses the both-sides comparison of the 2026-10-01
review repairs (HISTORY.md, "Review repairs"), unchanged. There are three verdicts: ahead (the
range leaves out an even split), about even (the range stays within 5 points of it, 45-55%) and
not settled. When ahead and about even both hold, the page says
"<deck> is slightly ahead (by under 5 points)"; the page and `forge play` use the same words. The
"Starting player" tile is now the average of both decks' win rates going first, with its 95% range,
or the plain share, labelled as such, when one deck never went first. The plain share misled,
because the loser goes first in the next game. Results need no migration: all of this is worked
out when a result is read.

Enter or load a deck, then see how good it is, with the answers coming from **real simulated games** rather than opinion:

- **Mana:** curve, land count, and whether the deck has enough sources of each colour.
- **Consistency:** how often the deck mulligans, gets stuck on too few lands, or has nothing to play.
- **Matchups:** win rates against the other decks, from full games that follow the rules.
- **Strengths and weaknesses:** which cards win games and which get stuck in hand, measured from those games.
- **Buying:** what's owned, what's missing and what it would cost (the existing owned-vs-needed workflow).

Decisions already made:

- **No AI-written evaluations.** Every judgement the page shows comes from counting or simulating.
- **Forge runs the matchup simulations.** Nothing gets hand-written per matchup (see "What changes from the 2026-09-28 report").
- **Decks save to the normal deck files** in `magic/decks/`, and each save is committed to git automatically. (Since phase 4 of the database move, 2026-10-12, the decks are in the database and each save is a revision in the deck's history; nothing is committed.)
- **Wishlists autosave each change immediately.** Their Git commits are grouped after three minutes
  without edits to that person's list. A durable queue resumes pending history after a server restart;
  closing the browser needs no Save action. Deck saves and inventory/order task commits keep their
  existing boundaries. (Since phase 2 of the database move, 2026-10-12, each change is a row in the
  database and a change set in the audit trail; nothing is committed, and the grouping and the queue are gone.)
- **Product decks load without typing**, including the ten 20-card Beginner Box halves.

### What changes from the 2026-09-28 report

[The best-decks report](../magic/reports/2026-09-28-best-decks.md) got its win rates from **a separate throwaway simulator written for each pair of decks**, each with heuristic players and only the cards in those two decks coded. That doesn't scale to new decks.

Forge replaces this with **one rules engine that already supports nearly every card**, so any deck can play any other with no new code. The report's numbers are still useful, as a check on Forge (see Milestone 0).

### How it fits together

```
 Phone / iPad (browser)
        │  http://<PC's IP>:8642   (home network only)
        ▼
 Python server on the PC  ─────────────►  git (commits each deck save)
   │     │     │
   │     │     └─► Forge, running with no window: N worker processes spread across the 16 cores
   │     │           plays full games, returns wins, losses and game logs
   │     │
   │     └─► Repo files: magic/decks/*.md, magic/collection.csv,
   │                     magic/orders/*.csv, magic/products/*.csv
   │
   └─► Local data cache (not in git): Scryfall bulk card data, oracle tags,
                                      card images, simulation results
```

**Hardware (checked 2026-09-29):** Ryzen 9 9950X3D (16 cores), 64 GB RAM, RTX 5080. The GPU isn't used, since there's no AI model. Python 3.14 (with numpy) and Java 26 are installed. The PC's name is `HomePC`.

### Parts

#### 1. Card data (Scryfall)

- **Download Scryfall's bulk files weekly** into the cache, instead of calling the API card by card:
  - `default_cards` (every printing; 79 MB compressed as of 2026-09-28): names, mana costs, types, oracle text, colours, colour identity, legalities, `game_changer`, USD prices, image links. Lines like `(FDN) 227` are looked up by set and collector number.
  - `oracle_tags` (6 MB compressed): Scryfall's community function tags, used to count card roles.
    - The tags form a tree. `removal`, `ramp` and `draw` have no cards directly and hold everything through their child tags, so roles must include child tags. Counted that way on 2026-09-29: removal covers 6,738 cards, draw 4,540, burn 3,210, ramp 2,455 and counterspell 563.
- **Card name autocomplete** comes from the local data, so a misspelled name can't get into a deck file.
- **Card images:** download each image the first time it's needed (Scryfall's small or normal size), keep it in the cache, and serve it from the PC. Only a few hundred cards are ever needed, and it keeps the phone fast.
- **Tokens** (2026-10-09): the index also holds Scryfall's tokens, emblems and reminder cards (such as The Monarch), keyed by oracle id, and each card's links to the ones it makes, from `all_parts`. Index format 4; see "Tokens" in the milestones.
- **Game Changers:** read Scryfall's `game_changer` field; the data has it (53 cards on 2026-09-29), so no hand-kept list is needed.
- **Prices:** the cheapest non-foil paper printing's USD price × the USD→AUD rate from the Frankfurter API (`api.frankfurter.dev/v1/latest?from=USD&to=AUD`, ECB data; 1.4237 on 2026-09-28). Always show the rate, the date, and that it's an estimate, as AGENTS.md requires.

#### 2. Deck library

The page lists every deck from:

| Source | Editable? | Notes |
|---|---|---|
| `magic/decks/casual/*.md`, `magic/decks/commander/*.md` | Yes | The 11 existing decks. Each file can hold two lists: the **target** list and the **owned-only version**. The page shows both as versions of the same deck. |
| `magic/products/*.csv` | No (read-only) | Beginner Box halves, the Bloomburrow Starter Kit decks, Lightning Aggro, and the two Commander precons. Changing one saves it as a **new** deck file. |
| Beginner Box pairings | No | Pick any two of the 10 twenty-card halves to get a 40-card deck (45 possible pairings). |

**Reading and writing deck files** is the most fragile part, because these files are also written by hand and by Claude. Rules:

- **The page only rewrites what it owns:**
  - the header fields (Format, Archetype, Played by, Status, Built version, Target bracket);
  - the fenced decklist blocks (the target list under `## Decklist`, and the owned-only version);
  - the rows and total row of the owned-vs-needed table (cards, Need, Owned, Missing, prices). The table always describes the target list;
  - Deck Lab's own labels at the start of each Notes cell (`1 on the way (order ...)`, `2 in use in <deck>`, and `not counted, no price: ...` on the total row);
  - the `1 USD = X AUD (ECB rate of D), pulled D` rate in the paragraph above the table, which is added if the paragraph has no rate.

  It keeps the rest of each Notes cell and every prose section (Why these buys, Substitutes, Shared-pool conflicts, Notes) exactly as they were. AGENTS.md lists the exact forms, so files written by hand or by Claude use them. A rate above the table in any other wording makes the page refuse to reprice the table, rather than add a second, contradicting rate.
- When the decklist changes, add a line under the header: *"Decklist changed in Deck Lab on 2026-10-05; prose sections may be out of date."* This tells a later Claude session to refresh the write-up.
- **New decks** start from a template: header, decklist, table, and empty Substitutes and Notes sections.
- **Round-trip test:** reading and then writing each of the 11 existing files without changes must produce byte-identical files. That test has to pass before saving is switched on.
- **Handling saves:**
  - **Conflicts:** if the file changed since the page loaded it, refuse the save and show a conflict message, so one person's save never silently overwrites the other's.
  - **Commits:** each save commits only that file (`git commit -- <path>`), with a message like `Deck Lab: save Gruul Ramp (edited by <name>)`, where the name is the profile chosen on the start screen (see part 7).
- **Parsing the decklist lines:**
  - `4 Card Name (SET) 123` is the standard line;
  - a trailing `*F*` means foil;
  - basics can have no set (`9 Forest`);
  - Commander decks have a `Commander` section.

#### 3. Owned vs needed (shared pool)

This implements the AGENTS.md workflow in code:

- **Owned** means `collection.csv` plus `magic/orders/*.csv` (not `received/`) and the card lists of products that are preordered or ordered. The cards that haven't arrived are labelled "on the way", with how many copies and from where.
- **In use** means cards in decks with status `built` (the list their `Built version` names), and cards in product decks that are still kept intact. Subtract these, and list the conflicts with deck names.
- **Needs a new file:** the app can't read Claude's memory notes, so it has no way to know which products are preordered or kept intact. Add `magic/products/status.csv` (added 2026-09-29; AGENTS.md describes it):

  ```
  file,status,intact,notes
  fdn-beginner-box.csv,owned,yes,kept as its 10 Jumpstart decks
  blb-starter-kit.csv,owned,no,"both decks (Hare Raising, Otter Limits) broken up into the pool"
  fdn-starter-collection.csv,owned,no,sorted into the binder
  fdc-calling-all-angels.csv,preordered,,due 2026-10-02
  ...
  ```

  This changes a repo convention, so AGENTS.md needs updating when it's added.

#### 4. Deck stats (instant)

These are computed straight from the list:

- **Curve:** cards at each mana value, split into creatures and non-creatures, plus the average mana value.
- **Land count:** the lands and mana creatures compared with published land-count guidance for the deck size (20, 40, 60 or 100). **Look the guidance up when building this; don't write numbers from memory.**
- **Colour check:** coloured mana symbols needed at each turn, compared with sources of each colour, using Frank Karsten's published colour-source tables (also looked up when implementing).
- **Types and roles:** creature, instant, sorcery and so on, plus role counts from oracle tags (removal, ramp, card draw, counterspells, board wipes, burn, lifegain).
- **Tribes and keywords:** creature types (for example "12 Rabbits") and keywords like flying and lifelink.
- **Commander checks:** 100 cards, one copy of each, colour identity, the Commander ban list, and a Game Changers count with the resulting minimum bracket.

#### 5. Practice-hand simulation (seconds; own Python code, no opponent)

Deal about 100,000 games per deck and play them out for the first 6–8 turns with simple rules:

- **Mulligans:** London mulligan with simple keep rules (keep 2–5 lands; change these later if needed).
- **Each turn:** play a land if you have one, then cast the most expensive spell you can afford.
- **Mana creatures:** count as mana from the turn after they're cast.

Results:
- mulligan rate;
- the chance of hitting your 2nd, 3rd, 4th and 5th land on time;
- turns stuck with too few lands or too many (drawing only lands);
- the chance of missing a colour you need;
- the share of turns where you used all your mana, and the turn your first 4-drop comes down.

This uses only the standard library. Switch to numpy only if it's too slow; numpy is already installed.

#### 6. Matchups (Forge)

**What Forge is:** a free, open-source Magic rules engine with computer players, maintained by volunteers ([github.com/Card-Forge/forge](https://github.com/Card-Forge/forge); version 2.0.15 released 2026-09-28; 2.0.16 is watched for, see the Later list). It isn't connected to Wizards of the Coast.

**How the server uses it:** Forge has a mode that plays games with no window (checked in its source code on 2026-09-29):

```
forge sim -d <deck1.dck> <deck2.dck> -n <games> [-s <seed>] [-f Commander] [-c <timeout s>] [-q]
          -t RoundRobin|Bracket|Swiss   (tournament across several decks)
          -a <AI profile per player>
```

In practice, `forge` here means the JDK's own `java.exe -jar forge-gui-desktop-2.0.15-jar-with-dependencies.jar sim`, run from the Forge folder, and `-d` takes file names inside a `-D <deck folder>`. The exact command and its pitfalls are in "Milestone 0 results".

- **Deck conversion:** convert each deck to Forge's `.dck` format, with `[metadata]` / `Name=`, then `[Main]`, `[Sideboard]` and `[Commander]` sections. Write name-only lines (`4 Llanowar Elves`), use the front face of `Front // Back` cards, and merge repeated printings (tested in Milestone 0).
- **Workers:** a job queue splits a request (for example 400 games of Gruul vs Izzet) into batches across several Forge processes. Each process takes time to load all the cards when it starts, so each one plays many games rather than one.
  - Milestone 0 measured the numbers: **16 workers** (12 while the PC is in use), with lazy card loading, `-XX:+DisableExplicitGC` and `-Xmx1024m`. It also recommended 200 games per batch (at least 100), and fewer workers rather than smaller batches for small jobs.
  - **Changed 2026-10-03 (simulation wave 1, R02 with R01a):** batches of at least 25 games and up to one per worker, all started at once. A run is split into the largest even number of batches, at least 2 and at most `min(forge_workers, games ÷ 25)`, that divides the games: with 16 workers, 200 games are 8 × 25, 400 are 16 × 25, 800 are 16 × 50, 1,600 are 16 × 100 and 3,200 are 16 × 200. This only pays together with `-XX:ActiveProcessorCount=2`, which makes 16 cold processes start faster. `forge_batch_games` no longer changes anything.
  - **A budget for the whole PC (R18, 2026-10-03):** `forge_workers` is the most Forge processes running at once on the PC, shared by the server and every command-line run in every checkout. Each process holds a slot (an OS lock in `%LOCALAPPDATA%\DeckLab\forge-slots`); a run with no free slot waits and says so. Forge runs below normal priority, so the PC and practice hands come first.
  - Start one Forge process on its own the first time a Forge user folder is used; 16 starting together can crash.
  - **Changed in wave 2 (2026-10-03, R05 and R01b): a warm pool.** With the card log, runs no longer start a cold Forge process per batch. The server keeps warm Forge workers that play chunks of games from one queue shared by every matchup waiting, up to 4 matchups at once; each worker computes only while it holds a slot, pinned to one physical core (the V-Cache cores, logical CPUs 0-15, first), and quits after 15 minutes with nothing to play. Command-line runs play in the server's pool when it's up. The batches above remain for plain Forge (when the card log is off). See the wave 2 entry.
  - **Measured in the combined run (2026-10-03, the wave 3 entry):** warm, with 16 workers, the pool plays 1,426.3 games a minute on Izzet Prowess vs Gruul Ramp, 157.3 on Selesnya Rabbits vs Orzhov Vampires and 232.6 on Giada vs Finneas (1v1 Commander): 1.93x, 1.17x and 3.39x wave 1's cold batches. A fresh pool (start-up included) is 1.41x on Izzet vs Gruul. These rates are in `data/forge/rates.json`, which the page's rough times use.
- **Fairness:** play half the games with the deck order swapped, and give each batch its own seed so results can be repeated. Forge lets the loser of each game start the next one, so swapping decks doesn't balance who goes first: keep the full log (it shows who started) and report the win rate balanced for play and draw.
  - **Changed in wave 2 (R09):** each game has a seed of its own, worked out from the result's seed base, the pair's seed stream and the game's number, and is a Forge match of its own, so a coin flip decides who starts every game. The decks swap seats every 25 games, and game g of a result is the same game whichever worker or chunk plays it. Plain Forge (card log off) still plays batches as above. The balanced win rate stays the headline.
- **Results:** games, wins for each side, draws (timeouts), the win rate with a confidence range, and games per minute. Save them as JSON in the cache, with deck versions (the git commit of each deck file) and the Forge version, so old results are never mixed up with changed decks.
  - **Since wave 2 (R06):** a result's key is its engine id, a hash of everything that decides the games Forge plays for a seed (the run version, the kind of engine, Forge's version, the format, the clock, the seed scheme, Forge's PERFORMANCE_MODE, the game-changing patches, card-script overrides, and each side's list and AI profile). Results of another engine (those saved before wave 2, or played with plain Forge while the card log was off) are kept and labelled "Earlier engine", and never pooled with today's.
  - **Since wave 3 (engine id version 2):** a side also holds its pilot (AI profile and switches), the overrides part covers only the card-script overrides whose card is in the two lists, and the game patches include `deck-order-1`. So adopting an override set re-keys only the matchups that hold its cards, and `replay` plays just those again.
  - Don't trust Forge's winner line: it names a winner even for games that timed out or crashed. Count a win only when exactly one player "has won" and no timeout line appeared.
  - Also count the AI's 5-second decision timeouts (`AI eval thread at timeout`) per job, and show them.
  - **Since 2026-10-03:** a lead verdict (ahead, about even within ±5 points, or not settled), the starting player's chance of winning balanced across both decks, and how far two results of that many games can differ by chance (see the note under "Goal" and the wave 1 entry).
- **Cards the AI can't play:** next to every Forge result, list the deck's cards Forge's AI never casts (see "Milestone 0 results" in [HISTORY.md](HISTORY.md)): cards whose script has `AI:RemoveDeck:All`, found by scanning Forge's card scripts because sim mode doesn't report them, and cards a card-log run (see "Per-card stats" below) shows are drawn but never used. Mark results for the Gisa decks as not meaningful, since the AI never casts Ghoulcaller Gisa.
  - **Since wave 3:** Deck Lab's card-script overrides (R10) fix some of these: Forge loads an edited copy of the card's script over its own. Adopted: Fiery Annihilation (2026-10-03: cast for 0% of drawn copies before, 92% with it), Devout Decree and Beast Within (2026-10-04: their `AI:RemoveDeck:All` is gone, so the AI now casts them). The AI limits read the deployed scripts, so those cards are no longer listed. Experiment sets are only played in experiments (see the wave 3 entry).
- **Commander:** tested in Milestone 0.
  - 1v1 Commander (`-f Commander` with 2 decks) takes about 2 s per game and replays exactly.
  - 4-player pods work but take about a minute per game (median 38 s, some over 3 minutes) and don't replay exactly. Size pod jobs in tens of games per worker, rotate seats between batches, and treat the results as statistics. (The combined run's M6, 2026-10-03, with 12 plain Forge processes, 200 pods: 0.41 minutes a pod on average, median 0.34, longest 1.81; not on the page yet.)

**Per-card stats (Milestone 8):** the page reports:
- the win rate when a card was drawn compared with when it wasn't;
- how often it was cast once drawn;
- how often it was stuck in hand;
- the average turn it was cast.

That becomes the "strengths and weaknesses" view. Milestone 0 found that Forge's own game log isn't enough: it shows casts and land drops but never draws or what's in hand. A small Java class that runs Forge's sim with one event listener added (the "card log") records every card move without changing the games, and with it all four stats work. It has to be checked on each Forge upgrade (`cardlog-check`); Deck Lab rebuilds it itself. A 1-of needs thousands of games for a reliable win-rate difference; "cast once drawn" and "stuck in hand" are useful after a few hundred. Built in Milestone 8: the matchup page's "How each deck's cards played" and the deck page's "How its cards played" (see the milestone below).

**Since 2026-10-03 (simulation wave 1, R11 items 1-3):** the deck page works out each card's drawn-vs-not difference matchup by matchup (Mantel-Haenszel), so a card isn't credited for which opponents its deck played most; every difference has a best estimate pulled toward 0; "won more/less when drawn" needs a Benjamini-Hochberg 10% discovery among the deck's judged cards as well as a range clear of 0; and numbers are early below 800 games with card data (was 100). Long games still draw more cards, which can move a card's difference by -6 to +9 points with no effect from the card at all; wave 2's "in hand by the side's own turn 3" tally removes that.

**Since wave 2 (R11 item 4, done 2026-10-03):** card log records of version 3 also count whether a copy was in the side's hand by its own turn 3, and "won more/less" is judged on that whenever a list has such games, so game length no longer leans the verdicts. Each card's drawn win rates are still shown, and lands always show them (see the wave 2 entry).

**Caveat, shown on the matchup page:** Forge's computer players are weaker than people and handle some decks better than others (straightforward attacking decks are easiest for it). Treat win rates as a comparison between decks, not a prediction of real games. Milestone 0 found one clear exception to "attacking decks are easiest": Forge's AI holds team-wide pump spells like Overrun, so it rates go-wide pump decks far too low (Selesnya Rabbits by 12-15 points). Flag decks built around mass pump spells.
- **Built 2026-10-03 (simulation wave 1, R19) as trust labels:** the matchup page's "How far to trust these numbers" holds how far two results of that many games can differ by chance, a "Forge pilots <deck> poorly" box for each flagged deck listing its cards and why, a tempo caveat when both decks hold counterspells, and "Commander results are indicative only" on Commander matchups. The deck page's Matchups part shows the same pilot box. The flag comes from the cards' Forge scripts, using only the kinds of card Forge's source shows its AI misplays: a deck is flagged when its commander is never cast or held back, when it has 3 or more team pump copies (spells, or permanents' abilities), or when its weak copies reach 4 per 60 cards (counterspells count half).
- **Since wave 3:** a switch that has Forge's AI judge team pumps as a whole (`team-pump-1`, TeamPumpAi) is built as a pilot for experiments. In the combined run it gave Selesnya Rabbits +4.1 points against Orzhov Vampires (+2.5 to +5.7, 800 paired games); the report asks for more games before it can be adopted, since a pilot also needs a mirror test, which wasn't played.

**Since wave 3 (2026-10-03), more ways to ask** (the wave 3 entry has the details):
- **Adaptive runs (R12):** a matchup can play "until the win rate is known to within ±3 points" (the page's default) or "until one deck is clearly ahead, or they're about even", instead of a set number of games.
- **The field view (R13):** a deck page's "Against the field" part: the list against every current deck of its format, as an average, a Bradley-Terry rating and rank, and one row per opponent.
- **Tests of a change (R15):** the editor's "Test this change" plays a changed list on its base list's own games, so a change of a card or two needs far fewer games to judge (92% fewer for a 1-card change in the combined run).
- **Pilots and card-script overrides (R10, R16):** a list can have its own AI profile and switches (`decklab/simulation.json`), and Forge's card scripts can carry small AI edits (`lib/forge/overrides/`). Both are adopted by the owner from experiment results; every list plays Forge's Default profile today.

#### 7. Web page

- **No build step:** plain HTML, CSS and JavaScript with no framework, served by the Python server.
- **Designed for phones first,** with light and dark themes. It can be added to the home screen on the iPad or phone.
- **Desktop layout** (added 2026-10-01) for a browser on the PC, whose QHD screen gives a maximised window about 2,545 px wide: from 1,600 px the page uses the whole width, the decklist is a grid of card pictures, and with a mouse a card peek column shows the card last pointed at, full size. See the entry after Milestone 8.
- **Charts** are hand-made SVG (a curve bar chart, colour-source bars and win-rate bars), so nothing is loaded from the internet.
- **UI redesign** (built 2026-10-13, from [UI-REVIEW.md](UI-REVIEW.md); the shared pieces in [UI-KIT.md](UI-KIT.md); HISTORY.md has what was built): design tokens with a teal accent and one dark block, shared components, an app shell (a top bar with Decks, Collection, Shopping, Matchups and More; a tab bar on phones; an avatar menu; a Settings page for admins, which took the footer's version and simulations controls), card tiles and rows, Scryfall's symbols, and a swipe card viewer over every card list. Every page was rebuilt on them: the library as a shelf of tiles with each deck's picture (automatic, or the deck text's optional `Cover card` line), the deck page in five tabs, the editor on every device (the full editor from 600 px, a Quick edit on phones), Receive delivery as a check-off board of pictures, Shopping, the Packing plan, the Game log's one-tap record, Collection, Tokens, Sleeves & boxes, Wishlist, Activity, History and the Matchups matrix. The page calls the two lists the Planned list and the Play-now list.

**Profiles** (decided 2026-09-29): the page starts on a **"Who are you?"** screen.
- It shows one button per person: the two home players. There's no password, since the page stays on the home network (part 8).
- The screen shows at the start of each visit: when the page is opened fresh, and again after it has been in the background for 30 minutes. The last choice is listed first, so it takes one tap. A "Switch" button in the menu goes back to it. The iPad is shared, so asking at the start avoids saving under the wrong name.
- The profiles are listed in `config.json`, each with a display name and its **Played by** value (`user` or `wife`).
- What the profile changes:
  - The Library opens on that person's decks (Played by them or `either`), with a switch to show every deck.
  - Saves and matchup runs record who made them, and the save's commit message names them.
  - Settings such as theme and the usual number of games belong to the profile, so they follow the person between phone and iPad. They're kept in `data/profiles/` on the PC, not in git (since phase 2 of the database move, 2026-10-12, in the database's `profile_setting` table).

Screens:
0. **Who are you?:** pick a profile (see above).
1. **Library:** every deck, filterable by format, player and status.
2. **Deck:** decklist with card images, stats, practice-hand results, owned vs needed, and past matchups.
3. **Editor:** add cards with autocomplete, set quantities, choose the version (target or owned-only), and save.
4. **Matchups:** choose decks and a number of games, start the run, watch progress, and see results; switch to Rankings for the selected format's current lists, comparable rating groups and exclusion reasons.
5. **Beginner Box:** choose two halves to analyse or play against another pairing.
6. **Accessories** (2026-10-08): the sleeves, deck boxes and playmats, with pictures fetched from a shop link, which deck or product uses each, and the sleeves and box of each product kept intact. The deck page, library, editor and packing plan show each deck's kit.
7. **Tokens** (2026-10-09): the token and reminder cards owned, which decks each one serves, the tokens decks need that nobody owns, and incoming token orders. The deck page has a Tokens part, the library a chip when something is wrong, and the packing plan "Grab" ticks and the cards two decks share.

#### 8. Running it on the home network

- **Server:** Python standard library (`http.server.ThreadingHTTPServer`), listening on port 8642 on all network interfaces. With no window, it logs to `data/logs/server.log` (rotated at 2 MB, 3 old files kept), and while it runs it records itself in `data/server.json` (its process, address, port and start time), which is how other commands find it (Milestone 6).
- **Windows Firewall:** a one-time rule allowing port 8642 on the **Private** network profile only. This needs admin, so the user runs it. Also check that the home network is set to Private.
  - **Built as a script** (Milestone 6), `network-setup.ps1`, run once from an administrator PowerShell after `homenet install` (it reads the task to find `pythonw.exe`, and never runs Python itself). If the home network is Public, it names it and asks before setting it to Private. It makes sure of two Deck Lab rules, both for Private networks and the local subnet only: one for the port, and one for the task's `pythonw.exe`, so Windows never shows its "allow this app" prompt for it (that prompt's Cancel adds a block rule). Then it removes the other allow rules it made, and leaves every other rule alone. It also removes block rules the prompt made for that Python, and with `-PythonPrivateOnly` takes Public networks off Python's own allow rules. Without admin it changes nothing.
- **Address:** `http://<PC's IP>:8642`. Reserve the PC's IP address in the router so it doesn't change. Phones may not resolve `HomePC` by name.
  - The reservation stays a manual step in the router's own page; the README gives the PC's MAC address and a typical router menu path.
  - The PC does answer mDNS for `homepc.local` (checked from the PC on 2026-10-01), which iPhones and iPads use, so `http://homepc.local:8642` may work there.
- **Start-up:** a Task Scheduler task starts the server (with `pythonw`) at logon. The PC has to be on for the page to work.
  - **Changed 2026-10-01: manual by default.** The user wants to start it by hand, so `install` now registers the task with its logon trigger off: the server starts only with `homenet start`. `install --at-logon` turns the trigger on, and `status` treats either as fine.
  - **As built:** the task, "Deck Lab", is for the current user only and needs no admin. It starts `server.py` with `pythonw` when `homenet start` runs it (and 30 seconds after logon, if installed with `--at-logon`), with no time limit and normal priority. `python -m decklab.lib.homenet install | remove | start | stop | restart` manages it, and start always goes through the task.
  - **Stopping without a window:** the server listens for a named Windows event, one per port, and stops the way Ctrl+C stops it, so a matchup saves its games. `taskkill /PID` without `/F` asks the server's hidden window to close, which does the same. Logging off or shutting down is heard by that hidden window and handled like closing the server's console window.
- **Checking it:** `python -m decklab.lib.homenet status` (added in Milestone 6) checks the server, the task, the network category, the firewall rules, the addresses for phones and the sleep setting. It's read-only and gives a fix for each problem, but it runs on the PC, so it can't prove a phone gets through.
- **Security:** there's no login, and the server writes files, runs git and runs Forge. Keep it on the home network and never forward the port to the internet. Since 2026-10-10 it's also reachable at https://decklab.example.com, but only through a Cloudflare Tunnel behind Cloudflare Access (named emails, one-time code), with `cloudflared` also requiring that login (`originRequest.access`). The server starts the tunnel itself (`lib/tunnel.py`), and `homenet status` checks that the public address shows the login (README, "From outside the home"). Clean up every file name that comes from the page (deck slugs only, so it can't write outside `magic/decks/`). The task and the server run without admin.
  - **Accessory pictures (2026-10-08; since phase 4 from the database):** `/accessory-img/<id>.<jpg|png|webp>?v=<hash>` serves only a picture that a row of the accessories list the viewer may see names, and only when its first bytes match its extension (never SVG); `v` is required and must be the first 8 hex digits of the picture's sha256, and the answer is cached for a week, privately (`Cache-Control: private`, so no shared cache answers for the owner check). `/accessory-img/staged/<32 hex>.<ext>` serves a fetched picture not saved yet, under an hour old, with `no-store`.
  - **Fetching from a link (2026-10-08):** "Find picture" is the only place the server reaches out to an address a person typed (`lib/accessory_fetch.py`). Only http and https, at most 500 characters, no user name or password, port 80, 443 or none. The host is resolved first and every address must be a global internet address (no private, loopback, link-local, multicast, reserved or unspecified ones), checked again on every redirect (at most 5, never ftp). No proxies, 10 s per socket operation and 20 s in all, pages up to 2 MB and pictures up to 4 MB, at most two downloads (the page and the picture it names), and only JPEG, PNG and WebP of 16-6,000 px a side, recognised by their bytes. Accepted risk: urllib resolves the host again when it connects, so DNS rebinding could still point a fetch at the home network; for a home-network page used by two people that window is accepted rather than pinning addresses. A shop that blocks the download gets a message to paste the picture's own address instead; there's no upload from the device.
  - **Tokens page (2026-10-09):** one new write route, `POST /api/tokens/save`, with the accessories' guards: it writes only `magic/tokens.csv` (and `data/tokens-pending.json`), takes the deck-save lock and then the receipts' inventory lock, refuses while a receipt's recovery journal is waiting or the file has changes Deck Lab didn't make, needs the file's sha256, caps the body at 16 KiB and every field's length, and checks that the new file reads back as the old rows plus the one change before writing it. It fetches nothing from the internet; token pictures come through the existing `/img/` route. (Since phase 3 the token cards are rows in the database: a save is one inventory operation (`tokens.add`, `tokens.edit` or `tokens.remove`), still checked against the sha256 of the rows as the page loaded them, under the inventory's advisory lock; there's no pending file, no recovery journal (deleted in phase 5a) and no outside edit to refuse.)

### Code layout

```
decklab/
  PLAN.md               # this file
  README.md             # how to set it up, start and stop it, open it, and what to do when a phone can't reach it
  server.py             # starts the server (--log, --stop); its HTTP handler is lib/server_http.py, startup and shutdown lib/server_run.py
  network-setup.ps1     # the one admin step: network category and firewall rules (run once as administrator)
  lib/
    cards.py            # Scryfall bulk download, lookup, oracle-tag roles, prices, image cache
    card_index.py       # building the card index from the bulk files (no state, no files); re-exported by cards
    decks/              # read/write deck .md files (decklist, deckfile, edit, render), product CSVs,
                        #   Beginner Box pairings, finding a deck by id (find_summary, engine_kind), and since
                        #   2026-10-13 the Cover card line and the automatic cover (cover.py)
    pool.py             # owned vs needed, shared-pool conflicts
    accessories.py      # the accessories (read only, from the inventory since phase 4): ids, holders, the enough-sleeves rule and its wording, --check
    accessory_fetch.py  # fetching a picture from a shop link, safely (address checks, limits, staging)
    tokens/             # the token cards (from the inventory; their writes are the operations in ops.py), parsing details, matching owned token cards to a deck's tokens, --check
    precons.py          # MTGJSON's published precon lists (cached in data/mtgjson/), for "Add a precon"
    stats/              # curve, lands, colour sources, roles, Commander checks (constants.py: every figure)
    goldfish/           # practice-hand simulation: card reading, game loop, workers, runs and saved results
    forge/              # .dck export, running Forge, parsing its output, saved results, AI limits,
                        #   the card log (java/DeckLabSim.java, simjar.py, cardlog.py) and per-card stats (cardstats.py),
                        #   the PC's budget of Forge processes (slots.py); Deck Lab's changes to Forge's classes are in its fork of Forge;
                        #   since wave 2 the warm pool (pool.py, cores.py, java/decklab/DeckLabServe.java and WarmState.java),
                        #   the engine id (engine.py), per-game seeds (seeds.py, Seeds.java), the v2 game loop
                        #   (GameLoop.java, Request.java) and the warm-equivalence check (servecheck.py);
                        #   since wave 3 the statistics (seqstats.py), time estimates (estimate.py), adaptive runs
                        #   (adaptive.py), the field view (field.py), tests of a change (variants.py), experiments
                        #   (experiment.py), card-script overrides (overrides.py, overrides/ with sets.json), pilots
                        #   (pilots.py, ai-profiles/), and in Java the deck order (DeckOrder.java, a copy of Match),
                        #   pilots (Pilots.java, TeamPumpAi.java, AiPatches.java) and start-up hooks (Startup.java)
    jobs.py             # background jobs the page polls (practice hands, matchups)
    api/                # the JSON answers behind the page (its __init__.py lists the parts); since 2026-10-13 cover.py
                        #   (the picture picker's cards and POST /api/deck/cover) and symbols.py (/sym/, Scryfall's symbols)
    inventory/          # the inventory, decks and accessories: snapshot, backends (files.py, pg.py), operations (since phase 3 and 4)
    gitops.py           # read-only git queries (a path and its status), for a .dck file's provenance in forge/lists.py; nothing commits (since phase 5a)
    control.py          # finding and stopping the running server, its state file and its log file
    homenet/            # start at logon (Task Scheduler), stop, start, restart, status
                        # (a package's __init__.py keeps the old module's docstring and names;
                        #  python -m decklab.lib.<name> still works)
  web/                  # index.html; scripts editor.js and editor-*.js, matchups.js, matchups-cards.js, core.js, library.js,
                        #   deck.js, stats.js, practice.js, app.js (loaded last); since wave 3 field.js and field.css
                        #   ("Against the field"), variant.js and variant.css (tests of a change); since 2026-10-08
                        #   accessories.js and accessories.css (the Accessories page and the picker the deck page and
                        #   editor use); since 2026-10-09 tokens.js and tokens-page.css (the Tokens page)
                        #   stylesheets since 2026-10-12 (UI-REVIEW.md WP3): tokens.css (the design tokens, the one
                        #   dark block), base.css, components.css, then shell, library, deck, stats and each page's
                        #   own file, which only lays components out (style.css and devices.css are gone);
                        #   WP5's shared card pieces (UI-KIT.md): cards-ui.css after components.css, and ui.js
                        #   (menu, Undo toast, action bar), symbols.js (Scryfall's symbols from /sym/), cards-ui.js
                        #   (card tile and row, token tile, printing picker) and card-viewer.js (the swipe card
                        #   viewer behind openCard; card-dialog.css is gone) after core.js
                        #   the app shell since 2026-10-12 (UI-REVIEW.md WP4): core.js's ROUTES (each page's one name,
                        #   nav place and who sees it), shell.js (top bar nav, avatar menu, the phone's tab bar and More
                        #   sheet) and settings.js (#/settings: simulations, Forge workers, version), before app.js
                        #   since 2026-10-13 (the UI redesign's pages): cover.js (the deck picture picker), runs-pill.js
                        #   (the top bar's run activity icon and its details), assembly.css and history.css; each page's script is
                        #   described in its header comment, and decklab/UI-KIT.md lists the shared pieces and rules
  tests/                # unittest, one or more test_<module>*.py per module, fixtures/
  forge-trial/          # Milestone 0's prototypes and notes, the simulation plan (sim-investigation.md), the wave
                        #   contracts, and the overnight harness (overnight*.py, sim-combined-run.md)
  config.json           # Forge install path, port, worker count, profiles
  simulation.json       # each list's AI pilot, and lists added to or removed from a format's field (wave 3)
  data/                 # gitignored: Scryfall bulk, tags, images, sim results
    logs/               # server.log (the background server's log) and server.log.1 to .3
    server.json         # the running server: process, address, port, start time (gone when it stops)
    forge/              # results/ (one file per matchup and engine; field/ notes and paired/ tests since wave 3),
                        #   rates.json (the measured speeds the time estimates use), experiments/, overnight/
```

- Forge is installed **outside the repo** (Deck Lab's build of its fork at `C:\Tools\forge-decklab\` since 2026-10-11); its path goes in `config.json` (`forge_dir`).
- Use only the Python standard library, following AGENTS.md. The move to a database adds one exception, psycopg, in `.venv`, which the system Python uses through `lib/venv.py` (see "Moving storage to a database").
- When code arrives, add `decklab/` to the AGENTS.md layout.

## Moving storage to a database

Decided 2026-10-11: Deck Lab's data moves from git-tracked CSV, JSON and Markdown files to **PostgreSQL**, whether Deck Lab keeps running on the PC or later moves to a hosted server (hosting is undecided). The reasons: a real database instead of git as one, and experience with running a database server. Forge stays on the PC either way. Phase 1 is built (2026-10-11), phase 2 (2026-10-12): the server keeps wishlists, profile settings, the simulations mode and play records in the database, phase 3 (2026-10-12): the inventory (every space's collection, token cards and raw imports, the orders, the products and the watchlist) is in the database too, and its files are gone from the tree (tag `pre-db-inventory`), and phase 4 (2026-10-12): every space's decks with their history and the accessories with their pictures are in the database, and their files are gone from the tree (tag `pre-db-decks`). Phase 5a (2026-10-12) deleted the dead code the files left and added a nightly check of the data; phase 5b (2026-10-14) retired the rollback to the files, and the week of side-by-side checks ended clean on 2026-10-19. How to run it is in [README.md](README.md), "Database".

### Decisions

Settled 2026-10-11:

1. **Engine: PostgreSQL 18** on the PC, reached through **psycopg 3** (pinned, binary wheel for Python 3.14) in a new `.venv`. It is the one exception to the standard-library-only rule, since the standard library has no Postgres client. SQLite was considered: it stays standard-library-only, but a later move to Postgres was re-estimated at 7-12 days, and if Deck Lab is hosted, the PC's tools (Forge, receipts, Claude sessions) couldn't open a SQLite file on the server.
2. **How it runs:** the native Windows installer, as a service that starts automatically and listens only on localhost.
3. **Old history:** tag the last file-based commit `pre-db` and keep it. Import only the deck revisions (about 39 commits) into the database.
4. **Backups:** a nightly `pg_dump` to the **home NAS** (details under "Risks of the move") (14 daily and 8 weekly copies kept), plus a nightly export in today's CSV, JSON and Markdown formats to a separate **private** GitHub repo, which replaces the off-PC copy this repo's history gives today. Both are mandatory.
5. **Forge results** stay as files on the PC for now and are added to the nightly backup. They move into the database only if Deck Lab is hosted.

Proposed defaults, not yet confirmed:

6. **Profiles** stay authoritative in `config.json` and are synced into the database at startup. If the database is down or the table is empty, login is refused; it never falls back to "everyone is admin".
7. **Buylist and report links:** the standard banner points at Deck Lab pages; old links to `watchlist.csv`, `orders/` and deck files resolve in the `pre-db` tag. (Phase 3 did this for the inventory: the banner links only Shopping, and the inventory's old links resolve in the `pre-db-inventory` tag; phase 4 for the decks: old deck links resolve in `pre-db-decks`, and new buylists link a deck's page.)
8. **Claude's write path:** typed commands (`python -m decklab.db ...`), with `deck pull` / `deck push` for deck prose. No two-way "edit an exported file, then apply" flow. (Built for the inventory in phase 3; the one bulk path is `watchlist apply --csv`, whose file is a copy `watchlist list --csv` printed. Built for the decks in phase 4: `deck pull` / `deck push --expect N`, with `deck new`, `delete`, `history`, `revision` and `tables`, and `accessories` / `image` commands.)
9. **Hosting:** deferred. If it happens, Postgres stays private on the host and the PC's Forge talks to Deck Lab's HTTP API with a Cloudflare Access service token.

### What moves and what stays

| Moves into Postgres | Stays as files |
|---|---|
| Collections of every space, and raw imports (stored as file contents) | Code, AGENTS.md, PLAN, HISTORY and README (git) |
| Tokens; accessories and their pictures (stored as file contents) | `magic/buylists/` and `magic/reports/` (git) |
| Orders: records, components, payload rows, checks | Machine settings in `config.json` (port, Access, tunnel, Forge paths) |
| Products, their card lists and status (replacing `status.csv` and the hard-coded `PRODUCT_INFO` / `NOT_DECKS`) | Card-data caches (Scryfall, MTGJSON, images), `fx.json`, logs, goldfish cache |
| The watchlist | Forge results, until hosting (backed up) |
| Decks: the whole Markdown text, plus card lines and header fields worked out from it | `simulation.json` (can move later) |
| Wishlists, play records, settings, simulations mode (moved in phase 2) | Pilots and field edits (`simulation.json`) and the Forge worker limit (`limit.json`, read by the command line too), for now |

Deleted rather than moved: the pending-commit files, the wishlist delayed-commit thread, the receipt journal (`active.json`), the revision file and `inventory.lock`. (Phase 5a deleted the journal, and phase 5b `inventory.lock` with the rollback's one-off commands, the only ones that took it.)

### Schema outline

- **Identity:** `space`, `profile`, `profile_email`, synced from `config.json`.
- **Inventory:** `collection_card` (primary key `(space, set, collector_number, finish)`, with checks on finish, quantity, condition and language; a blank stays NULL, never assumed NM or English), `collection_import`, `token_card` (surrogate id: rows with the same faces stay legal, and the "known rows don't duplicate" rule stays in Python).
- **Accessories:** `accessory`, `accessory_image`.
- **Orders:** `purchase_order`, `order_source`, `order_component` (its status replaces the `received/` and `cancelled/` folders; it keeps the payload's file name), `order_card_item`, `order_token_item`, `component_check`.
- **Products and queue:** `product`, `product_item` (one schema for all four CSV header styles), `watchlist_item` (unique on its six-column key).
- **Decks:** `deck` keeps the whole Markdown text, because prose sits between the lists and the table and the table's prices are dated snapshots, and keeps today's splice renderer, plus a `row_version`. `deck_line` and `deck_field` are rebuilt from the text in the same transaction as each save. `deck_revision` holds every saved version.
- **Other:** `wishlist_entry`, `play_record` (one table for games and sideboard plans: each record's own fields in jsonb, its deck ids in an array; hashes are worked out in Python, never from the jsonb text), `profile_setting`, `simulation_mode`. Built in phase 2 (migration `0003_personal_state.sql`).
- **Audit:** `audit.change_set` (who, from where, message, reason) and `audit.row_change` (each row's before and after, as jsonb), written by one trigger that refuses any write without a change set, so a plain `psql` write has to say who and why. `inventory_revision` is a counter that replaces the receipt preview's fingerprint.

### What replaces git

- **History:** every save is one transaction recording who, why and the rows before and after. A new Activity page lists changes. A deck's History reads `deck_revision`, and opening an old version as a draft still works. No general revert button at first.
- **Saving at the same time:** `row_version` replaces the file's sha256. A receipt runs as one transaction under `pg_advisory_xact_lock(hashtext('inventory'))`, so it can't be half-applied and `--recover` goes away.
- **Backups:** as decided above, plus a scripted monthly restore check, and a footer warning when the last backup is too old.
- **Commands for Claude sessions and scripts:** `python -m decklab.db` replaces hand edits. Reading: `sql` (read-only role) and `export` (to a gitignored folder, never back to `magic/`). Writing: `order add`, `order split`, `receive` (today's flags), `collection merge`, `product add`, `product set-intact`, `watchlist set`, `tokens ...`, and `deck pull` / `deck push` (which refuses if the deck changed since the pull). Every write needs `-m`, and a removal `--reason`. AGENTS.md is rewritten at each cutover, and its "commit hand edits promptly" rules go. Everything runs from the system `python`, which puts the `.venv`'s packages on `sys.path` itself (`lib/venv.py`, decided in phase 2: see below).

### Phases

Deck Lab stays usable after each one. About **32-41 days** of focused work in all, roughly 30% of it in the tests.

1. **Foundation (4-5 days):** the venv, the Postgres 18 service, three roles (owner, app, read-only) with `pgpass`, `conn.py`, schema migrations, the audit trigger, a test template database for each worktree, profile sync, the nightly backups to the NAS and the export repo. Nothing visible changes. **Built 2026-10-11** as `decklab/db/` (the first migration holds the identity and audit tables and `ops.backup_run`, and the second hardens the audit trigger and the app role's grants; the export repo holds only those tables until later phases add theirs).
2. **Low-risk state (3-4 days):** wishlists, settings, simulations mode and play records move; the wishlist commit thread goes; the first Activity page. **Built 2026-10-12** (HISTORY.md has the details): migration `0003_personal_state.sql`, the state store `lib/state/` (PostgreSQL in the server, an in-memory store with the same rules in the tests), the wishlist command line (`python -m decklab.db wishlist`), the one-time `import-files`, the footer's database warning and the Activity page. Decided differently from the plan above:
   - **The venv's packages, not its python.exe.** The plan had the server's scheduled task registered again from `.venv\Scripts\pythonw.exe`. On Windows that's a launcher that starts the base interpreter as a child process, which would break the pid in `server.json`, `/F` kills, the Forge slots' pid checks and the firewall rule (it names the program). So the task and every script stay on the system Python, and `lib/venv.py` puts `.venv`'s site-packages on `sys.path` when the venv was made from that same Python. `homenet` and the firewall are unchanged.
   - **Play records as one `play_record` table** (kind, id, revision, the exact timestamp strings, deck ids and the record's own fields as jsonb), not `play_game` / `play_side` / `sideboard_plan`: the records are read and written whole, and a record's hash must come back byte for byte.
   - **Pilots and field edits stay in `simulation.json`**, and the Forge worker limit stays a file, since the Forge command line reads it from other processes.
   - **Activity is filtered for each viewer** (`permissions.activity_scope`): admins see every change except email addresses; others see their own space's wishlist, settings and play-record rows and the simulations setting, each through an allow-list of fields, and a command line's message only when they made the change.
3. **Inventory, in one step (11-14 days):** collection, tokens, orders, products, watchlist and receipts together, since a receipt touches them all. Port the readers in `pool`, `purchases`, `collection_edit`, `tokens` and `precons`, and the product-deck and Forge field and lists readers. Delete the journal, lock and fingerprint code. Deck tables are refreshed after the transaction commits (they're derived, so a failed refresh can be retried). Gate: `overview()` and every deck's pool output are identical from files and from the database. **Built 2026-10-12** (HISTORY.md has the details): migration `0004_inventory.sql` (and `0005_gate_runs.sql`), the package `lib/inventory/`, every reader and writer ported, the inventory's command line (`python -m decklab.db collection|tokens|order|product|watchlist|receive|inventory|gate-inventory`; `scripts/merge_cards.py`, `receive_order.py` and `receipt_transaction.py` deleted), the import, the export's `magic/`, the gate, Activity's inventory rows, and read privacy for the inventory. Then the cutover: imported, gated live, tagged `pre-db-inventory`, the backend switched to `db` and the inventory files removed from the tree. Decided differently from the plan above:
   - **A backend switch, not a one-way port.** `config.json`'s `inventory.backend` picks `files` (the code's default: the old files, read and written as before) or `db`. So all the ported code merged and ran on the files first, the cutover is one switch after a passing live gate, and a rollback is `inventory restore-files` then switching back. The files backend stays for the tests and the rollback, so the journal, inventory lock and pending-commit record weren't deleted: they're the files backend's, and go in phase 5.
   - **One in-memory snapshot of the whole inventory**, not SQL per reader: the data is small (about 700 collection rows), so every reader works from an immutable snapshot pinned once per request or command, and every write is one pure operation on it, saved as a row diff under the advisory lock `inventory` with a revision check. Both backends produce the same snapshot ("raw first": rows keep the files' strings, and each reader re-derives its own errors), so a preview runs the readers on the result in memory, and the receipt preview still lists the deck tables it changes.
   - **The gate compares with the old code, not the same code on two backends.** Golden dumps of every reader's output were taken from the last commit before porting (`gate.GOLDEN_REV`), and the new readers on the database (with the inventory files deleted) must match them item by item, with the database's export byte for byte equal to the files. 24 scenario goldens run the same way on both backends in the tests.
   - **Schema details:** blank text is stored as `""` (not NULL as the outline said), so everything round-trips exactly; `token_card` and `watchlist_item` have surrogate ids and a plain position (the watchlist isn't unique on its six columns); checks and sources are arrays, not `component_check` / `order_source` tables; a product's status is its own table, `product_status`, since a status row and a card list can each exist alone; a raw import's text lives in an unaudited `collection_import_content`; and no foreign key refers to `space`, as in phase 2.
   - **Read privacy for the inventory**, not planned: home's inventory is readable only by Matt and User1, a person's only by them and admins (README, "People's own collections"), with Activity's inventory rows on the same rule.
   - **The order, product and receipt writes refresh the deck tables after they commit** (`collection merge`, the Collection page and the token writes don't), through one helper (`lib/inventory/refresh.py`), and the order commands refuse a change after which the tables couldn't be refreshed (`--force` overrides).
4. **Decks and accessories (10-13 days):** accessories wait until now because their Sleeves and Deck box references live in deck headers. Add `deck pull` / `deck push`. Forge's provenance becomes deck id plus revision. Gate: all 18 deck files come back byte for byte. **Built 2026-10-12** on branch `db-phase4` (HISTORY.md has the details): migration `0006_decks_accessories.sql`, the decks, accessories and pictures as parts of the inventory's snapshot in both backends, every deck and accessory writer as an inventory operation (`ops_decks.py`, `ops_accessories.py`), the deck history from the database (the git history imported: 40 commits on main, 117 revisions, one deleted deck), the decks' and accessories' command line (`python -m decklab.db deck|accessories|image|gate-decks|history-preview|history-gate`; `scripts/refresh_deck_tables.py` deleted), the import, the export's decks, the gate (all **19** deck files, `accessories.csv` and its 23 pictures come back byte for byte), Activity's deck and accessory rows, and read privacy on the deck pages. The cutover follows the build: stop the server, migrate, import from main, gate live, tag `pre-db-decks`, merge `db-phase4` into main, remove the deck files, `accessories.csv` and the pictures from the tree. Decided differently from the plan above:
   - **No decks switch.** The design first had a second `config.json` switch (`inventory.decks`) so the ported code could run on the files first, as phase 3 did. The review chose otherwise: the decks are an ordinary part of the snapshot in both backends (the files backend reads and writes deck files for the tests), production stays on main's pre-phase-4 code until the cutover, and the cutover is a merge. So the files backend's git mode and every commit, pending-commit, Commit now, Retry and outside-edit path for decks, accessories, collection and tokens were deleted in phase 4, not phase 5, and the rollback checks out the `pre-db-decks` tag's code after `restore-files --part decks --apply` (`inventory backend files` is refused).
   - **Two revisions in one snapshot:** `revision` (the inventory, which receipt previews check) and `decks_revision` (decks, accessories and pictures), so a deck prose save never makes a receipt ask for a new preview; each part is cached and re-read on its own counter.
   - **The deck-table refresh runs inside the change** (`refresh.in_op`, for the kinds registered with `refresh=True`), not after a commit: a receipt or order change and the decks it makes stale are saved together, a preview lists them, only the touched spaces' decks are planned, and a plan that fails leaves the decks alone and the change saved.
   - **Operations take the final text:** the page (and `deck push`) works out the text first; the operation only checks the sha256 and stores it. `kit.set` makes every sleeve and deck-box move between decks and products one change (phase 3's write-the-deck-then-the-database-and-put-it-back is gone); `precon.add` makes the collection's import and the deck one change.
   - **History imported without backdated change sets:** `deck_revision` has its own time, actor and message columns, so imported revisions have no change set (Activity doesn't list 40 change sets dated in the past) and the import stays one change set. Revisions are integers per deck; old links naming a git commit still resolve.
   - **Deck-page privacy, decided by the user during the design review:** deck pages and the library hide a space's counts, token chips, substitute availability and table from viewers who can't see that space's inventory (the open question phase 3 left).
   - **Accessories' per-viewer token and private pictures:** the Accessories list's sha256 is worked out over only the rows each viewer sees, and `/accessory-img/` needs the picture's real `v` and is cached privately.
   - **No `deck_field` table** (the outline's): `deck` carries the title, status and Played by for SQL and Activity, and `deck_line` the lists; the kit values stay only in the text.
   - **The decks are imported from main,** not from the checked-out branch, since the build ran on `db-phase4` while production saved to main; the import refuses while the server runs or the branch has deck commits main lacks.
5. **Cleanup and side-by-side checks (4-5 days), split in two by the user on 2026-10-12:** 5a (the cleanup and a nightly check), a week of side-by-side checks, then 5b (retiring the rollback).
   - **5a, built 2026-10-12** on branch `db-phase5` (HISTORY.md has the details). Deleted: the files backend's recovery journal (`lib/inventory/journal.py`) and `receive --recover`, `api/tracked.py` and the busy and consistent-read paths, `gitops`' commit helpers (`gitops.py` now only asks git about a `.dck` file given to the Forge command line), `NOT_DECKS`, `PgInventory`'s files overlay for a database without decks (it now serves no decks and refuses deck saves), the 409 answers' `"committed"`, `"commit"` and `"moved_to"`, and the editor's renamed-deck branch. Reworded: every message names a deck by its id; "fix it by hand" became "it can't be changed until that's put right"; the pool's advice for an order already in the collection says to receive it; and the receipt preview and the order and product `--dry-run`s list what they change in plain labels ("Home's collection", "Order <id>", "Deck <title> (<id>)") instead of `magic/` paths. The inventory lock moved to `decklab/db/filelock.py`. Added: `python -m decklab.db check [--history] [--limit N]`, the nightly check of the data in one snapshot (the accessories, every space's token cards, the orders and queue, the deck tables, the decks' own invariants, the revision rows, the audit trail, and the export's files read back against the database's snapshot), recorded in `ops.backup_run` as kind `check` (migration `0007_check_runs.sql`), run by `nightly` after the export; each dump records a content digest of every public and audit table, which the restore check compares as well as the row counts; `status` shows the last check, and the footer warns an admin when it failed, is old or never ran, or the last restore check failed; the export gains `public.deck_revision`; no test writes the live `db.log` any more (`DECKLAB_DB_LOG`); and `schedule status` warns when the nightly task runs the `.venv`'s `pythonw.exe`. The cutover: merge into main, `migrate` (0007), register the nightly task again from the system python (`python -m decklab.db schedule install`), and set the week's two settings below.
   - **The week of side-by-side checks, 2026-10-13 to 2026-10-19:** `config.json`'s `database` block set `restore_check_days` to 0.5 (a restore check every night, instead of every 28 days; 1 would skip a night whenever the steps before it finish sooner than the night before, since the restore check is due only when the last one started at least that many days ago) and `side_by_side_until` to `2026-10-19`, so each night ran the backup, prune, export, check and a restore check. `status` printed "Side-by-side checks: until 2026-10-19", and `python -m decklab.db check --history` lists each night's result. **`DB#1`, done 2026-10-19:** every night ran and passed, with a restore check comparing counts and contents on six of the seven (2026-10-13's wasn't due, six hours after the cutover's); the report is [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md), and `restore_check_days` came out of `config.json` (back to 28 days). The task as set: after the final 2026-10-19 nightly has completed, review `db status`, `check --history` and the recorded restore-check results; write a dated report in `magic/reports/` with run coverage, failures or missed nights, invariant checks and the restore row-count/content-digest evidence. Report operational summaries without any space's card, deck or wishlist contents. If a required night or restore check failed or is missing, record the unresolved follow-up rather than calling the week clean. Once the week's evidence is accounted for, remove the temporary `database.restore_check_days` override so the default 28-day interval resumes. Leave rollback tooling retired. This is independent of privacy development; no extra restore or backup run is required merely to prepare the report.
   - **5b, built 2026-10-14** on branch `db-phase5b`, five days into the week of checks (two clean nights) at Matt's say-so: tag the last commit that has the cutover tooling `pre-phase5b`, then retire the rollback: `inventory restore-files`, `import-files` (and its decks import, `import_decks.py`), the gates (`python -m decklab.db.gate`, `gate-inventory` and `gate-decks`), `history-preview` and `history-gate`, the `inventory backend` switch, the `.gitattributes` entry for `magic/accessories/images/`, the frozen product names in `files.py`, and `files.py`'s rollback role (5b also decides whether the export keeps its `magic/` folder and the check its files round trip, which both use `files.py`). Until then the rollback runbook still works, but the `pre-db-decks` checkout must keep migrations 0006 and 0007 (`inv_inventory.ROLLBACK_MIGRATION` says so), since that code refuses a recorded migration whose file it lacks. Done as planned: tagged `pre-phase5b`; deleted `inventory restore-files` and `inventory backend` (`inventory export` stays), `import-files` (`import_files.py`, `import_decks.py`), the gates (`gate.py`, `gate_inventory.py`, `gate_decks.py`, `gate_p4.py`), `history-preview` and `history-gate` (`inv_history.py`, `deck_history.py`), `filelock.py`, `ROLLBACK_MIGRATION` and `.gitattributes`; `config.json`'s `"inventory": {"backend": ...}` and `inventory.configured()` went too, so Deck Lab reads only the database (the tests still install a `FileInventory`). HISTORY.md has the details.

   Decided differently from the plan above:
   - **Split into 5a and 5b**, so the rollback stays possible through the week of checks, and is retired only once the week is clean.
   - **No deep check of the old code against the new**, by the user's choice: running the `pre-db-decks` code's readers over the database every night wasn't built. The nightly check reads the export's files back with this code instead (the files round trip), and the gates' `--live` modes stay until 5b.
   - **The inventory lock moved, not deleted**, to `decklab/db/filelock.py`, since `import-files`, `inventory restore-files` and `inventory backend` still take it, and so does a rollback's `pre-db-decks` code.
   - **`files.py` stays:** it's the tests' backend, the export's renderer and the check's round trip, and what a rollback reads. `PRODUCT_INFO` is frozen in it as `PRE_DB_PRODUCT_NAMES`, since the files can't carry a product's name.
   - **The export gains `deck_revision` but not `audit.row_change`:** the deck history is in the off-PC copy, and the row changes stay in the dumps only.
   - **Some old locators kept:** messages that point at a row by its old file (`magic/tokens.csv line N`, `status.csv line N`, a product's `magic/products/<stem>.csv`) stay as they are, pinned by the gates' goldens. The goldens weren't recorded again: `gate_p4.EXPECTED_P5` maps the old messages (decks named by their files, the old advice and wording) to the new.
   - **Content digests in their own column** (`ops.backup_run.digests`), not in the dump's `detail`, so a rollback's code still reads the row counts of a dump this code made.
   - **Accessory rule breaks are a warning in the check**, as Deck Lab warns about them rather than blocking, and so are stale deck tables and tables that can't be worked out (saying why); the decks' own invariants fail.
   - **5b before the week ended** (Matt, 2026-10-14): two nights had passed cleanly, and the privacy phases waited on it. The week's nightly checks and restore checks went on to 2026-10-19 as planned, and its report followed (`DB#1`).
   - **The export keeps its `magic/` folder and the check its files round trip** (Matt's decision, 2026-10-14): he wants two backup places, the NAS dumps and the GitHub export, so `files.py` stays as the export's renderer and the check's reader, and only its rollback role went. Since the files can't carry a product's name, the round trip takes the names from the database's snapshot before comparing, rather than warning about them every night.
   - **The gates' harness moved into the tests**, not deleted: the contract tests compare every reader with the committed goldens through the gate's reader dump, so `gate.py`'s dump and compare are `tests/golden_dump.py` and `gate_p4.py`'s normaliser is `tests/golden_p4.py`, without their command lines, recording and live runs. The frozen product names moved to `tests/pre_db.py` (`files.PRODUCT_NAMES` is empty in Deck Lab; the test package fills it in).
   - **`write_model` and `write_decks` stay** (`lib/inventory/pg.py`), with their `history` argument: the tests load their fixtures with them, and a history of earlier revisions is still how a test puts revisions in place. Only the git-history reader that fed them (`deck_history.git_history`) went.

### Risks of the move

- **Claude sessions using stale CSVs or raw SQL.** Delete the files at the cutover, give `sql` a read-only role, and rewrite AGENTS.md in the same commit. (Done for the inventory in phase 3.)
- **The tests:** about 120 test files patch path constants or build git repos, and the suite will need a running Postgres.
- **Files and database mixed** between phases 3 and 4: deck holds and accessory references still live in files, so keep that gap short. (Since phase 3: a sleeves move between a deck and a product writes the deck file, then the database, and puts the deck file back if the database write fails; each inventory write's deck-table refresh is a git commit after the database's. Closed by phase 4: both are now one change in the database.)
- **Broken links:** about 18 buylists and reports link to `../watchlist.csv`, `orders/` or deck files (decision 7).
- **The PC is the only live copy.** A backup that fails silently is worse than git, so the restore check and the stale-backup warning must really run.
- **Privacy:** read-only SQL sees every owner's accessories and notes. Keep it to the admin on the PC; row-level security for accessory owners is a cheap extra.
- **Versions:** psycopg's wheels follow Python releases; pin both.
- **Two details to get right:** the audit trigger must treat an empty `current_setting('decklab.change_set', true)` as missing, and the deck tables' prices stay dated snapshots.

**The NAS:** a NAS at `\\NAS`, with two 8 TB drives in RAID 1. The dumps go to a new `DeckLab` folder in its existing `Backups` share (`\\NAS\Backups\DeckLab\`). The PC signs in as the NAS user `decklab-backup`, whose password is saved in Windows Credential Manager for Matt's Windows account, so the backup task must run as that account (not SYSTEM) to reach the share. RAID 1 protects against a failed drive, not against deletion or a fault copied to both drives; the private GitHub export is the copy kept outside the home.

## Risks

| Risk | What happens | Mitigation |
|---|---|---|
| Forge's computer players misplay some decks | Win rates are biased toward decks that are easy to play | Show the caveat; compare with the report's simulations; use results to compare decks, not as exact odds. **Milestone 0 confirmed this:** Forge matched the report for Angels vs Zombies, had Izzet 3-5 points higher, and had Selesnya Rabbits 12-15 points lower, mainly because it holds team pumps and attacks too little. It never casts 5 cards in our decks, including the commander Ghoulcaller Gisa. List these per deck and flag go-wide pump decks. |
| Some cards aren't supported in Forge yet (for example newly printed ones) | That deck can't be simulated | Milestone 0 lists them; the page flags them; test a stand-in card. **Milestone 0:** all 612 names in our decks, products and collection are supported; only the 2 adventure cards need their front-face name. |
| Slow games or high memory use | Big runs take too long | Measure in Milestone 0; batch games per process; run big jobs overnight. **Milestone 0:** not a problem for 1v1: about 800 games a minute on 16 workers (230 for board-heavy matchups like Rabbits vs Vampires), using about 9.5 GB. 4-player Commander is slow (about a minute per game). |
| Forge doesn't work on Java 26 | It won't start | **Settled in Milestone 0:** Forge 2.0.15 runs on the installed Java 26.0.1, so no Java 21 is needed. |
| A Forge upgrade changes results or breaks the card log | Old and new results don't compare; per-card stats stop working | Save the Forge version with every result. On an upgrade, re-run the card audit and `python -m decklab.lib.forge cardlog-check` (Milestone 8): until it passes, matchups play without the card log, and the page says why. Deck Lab rebuilds the card-log jar itself. Its changes to Forge's classes (`AbstractMulligan` since wave 1, `AiController` and `AiAttackController` since wave 2, `Match` since wave 3) live in its fork of Forge since 2026-10-11, so an upgrade means moving the fork's `decklab` branch onto the new release ([README.md](README.md) has the steps). Card-script overrides (wave 3) aren't used while Forge's script differs from the one they were made from. Every result's engine changes with the version, so `replay` plays the current matchups again (the Later list has the 2.0.16 steps). |
| Deck-file edits damage hand-written sections | Lost notes | Only rewrite the parts the page owns; round-trip test; each save is its own git commit (since phase 4, its own revision in the deck's history), so any save can be undone |
| Both people save the same deck at once | One loses their changes | Detect the changed file and refuse the save |

## Open questions

1. **Simulation results in git?** Default: no, keep them in the local cache. Worthwhile results get written up in `magic/reports/` as now.
2. ~~**Who's editing:** is a one-time "who are you?" picker on each device enough, or should the page skip it?~~ Settled 2026-09-29: profiles, chosen on a "Who are you?" screen at the start (part 7).
3. ~~**`magic/products/status.csv`:** OK to add this file, and the CLAUDE.md change that goes with it?~~ Settled 2026-09-29: added, and CLAUDE.md updated.
