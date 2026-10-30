# TODO: open work

An index of open work, one row per item; each row points to the doc that owns the detail. The rules for editing it are at the end, in [How to read this file](#how-to-read-this-file). A fresh thread starts here: read **NOW**, then the owner of the row it picks up.

## NOW

**The only ordering in this file.** Keep every `DECISION` row here. Keep this block to the current aim and the next few actions; results go in their owners (HISTORY.md for what shipped).

**Aim (updated 2026-10-28):** finish the visual redesign (`E11-S30`), then improve physical deck building, collection filing, buying and play while keeping the code maintainable. The feature reserve and maintenance lane below both contain ready work. The prebuilt Forge release (`E11-S32`), Linux support (`E11-S33`) and box-review work (`E7-S21`) are built. The private member model is built and live (see Activation below); household device acceptance remains.

**Ready queue:** `E11-S30`, the visual redesign Matt chose on 2026-10-24 ("P1"). Slice 14 of [visual-design.md](decklab/design/visual-design.md#7-rollout) is implemented, as are slice 13's scoped recorded packing activity, verified intact-product storage review and per-card movable-copy priorities. Exact physical printing is recorded as a built deck's Printings in box line (2026-10-27). Slice 15's empty, loading and failed states are drawn and built, dark mode was checked on full data (2026-10-27) and Matchups with saved results in dark (2026-10-29); device acceptance remains open. The approved desktop keyboard plan is built; global search has its separate decision below. Explicit original-row associations for newly added arrival checks are implemented, with component-wide verification retained; targeted backend/UI and isolated native checks passed. Casual inline verification placement is implemented for proven targets, with single canonical controls, component-wide semantics and verified fallback; final UI/native checks and caption review passed. Collection question 6 and touch/Safari acceptance remain separate gates, with Card colour matching the compatibility default.

**Ready reserve (audited 2026-10-29):** after the redesign, choose an `OPEN` row below; there is no fixed order within the reserve. The 2026-10-29 audit checked every row against the code and added fifteen stories. Matt's three requests of 2026-10-29 (`E3-S27`, `E5-S26`, `E6-S27`) and the split keeping the extra-copies mark (`E6-S25`) were built the same day, as were free pool replacements and dual lands (`E3-S25`), queueing a deck's missing cards (`E5-S25`), decks a delivery made ready (`E6-S26`), last played in the library and on the deck Overview (`E1-S27`), the warm-worker fallback sentence (`E3-S26`), How to play's departed cards (`E2-S27`), the play sheet's At the table (`E9-S27`) and tonight's pairs on the Game log (`E1-S28`) and the staged Forge build's `upgrade-check --dir` (`E11-S45`) and sideboard-plan tests (`E4-S16`) (HISTORY.md). The rest are larger: drafts across devices (`E2-S16`, kept-for-later drafts built 2026-10-29, the Quick edit's and new decks' included, with migrations 0018 and 0019 unapplied) and field-policy editing (`E3-S23`, its selection, preview/save and failing closed built 2026-10-29, migration 0017 unapplied). Every `OPEN` story names a concrete first slice in its owner. Fixture-based work needs no new Forge games, household records or physical devices; real-device acceptance, live installations/migrations, purchases and Forge runs keep their separate gates.

**Maintenance lane (updated 2026-10-29):** Tokens' workflow split and the source-length CI guard (`E11-S36`, `E11-S43`) are built. The editor workflow and collection parser splits (`E11-S37`, `E11-S38`) are built, creating room for their upcoming features. Keep structural and feature changes separate. The comment and command-document audits (`E11-S41`, `E11-S42`) are built. The fixture-only test entry point (`E11-S44`) is built. The test-group split (`E11-S40`) is built; the PostgreSQL snapshot split (`E11-S39`) is built and waits only on its separate disposable-database qualification. The editor drafts split (`E11-S46`) is built, leaving `web/editor.js` at 1,017 lines for `E2-S16`. The old-file wording in messages (`E11-S12`) is built. The [source-maintenance owner](decklab/SOURCE_AUDIT.md#maintenance-backlog) records the measured files, boundaries and validation. Length is a review trigger, not a reason to divide every large file mechanically.

**Needs Matt or another person — these don't block coding:**
- **`E11-S31`: global-search scope.** Choose the sources (visible decks, the viewer's collection and/or all Scryfall cards) and result grouping before building. Library title, colour and archetype filters (`E1-S05`) are built independently of that decision.
- **`E2-S22`: physical-device follow-up.** Confirm hardware and touch usability on the household's actual iPhones and M2 11-inch iPad after the fixes. Keep prior results in the story; the [Safari Simulator suite](decklab/safari/EVIDENCE.md) covers repeat functional regressions.
- **`E11-S02`: signed-in off-page check.** On a phone through decklab.example.com, save a deck edit, upload an accessory photo, and check the off page while Deck Lab is stopped.
- **`E11-S30`: the redesign's last gates.** Choose Collection's colour filter (card colour or colour identity, [question 6](decklab/design/visual-design.md#6-open-questions-and-risks)), then check touch and Safari on the household's iPhones and iPad.
- **`E11-S39`: database qualification of the snapshot split.** Authorize a disposable-database run of the location, deck persistence and rollback cases; the split itself passes its fixture checks.
- **`E7-S24`: owned dice and counters.** Choose what a recorded die or counter says (kind, colour or design, quantity; whether one die stands for any kind) before its migration; the read-only counter needs are built.
- **`E9-S26`: Commander role targets.** Choose the cited, dated template the Stats roles' targets come from; free pool cards for each role are built.
- **`E7-S32`: real photos for Scan cards.** Take 10 to 20 photos of cards (a few foils, a few sleeved, one old card) with Collection's **Scan cards…** on each phone, or copy them to the PC for `python -m decklab.lib.scan`; the sheet and its API are fixture-tested only.
- **`E11-S28`: User2's user-testing session.** Confirm his device, then use the prepared [checklist](decklab/design/user-testing-user2.md).

**Activation:** migrations `0012` and `0013` were applied and the server restarted on committed code on 2026-10-19, so the privacy code and guarded member removal are live. No visibility choice or real member removal has been made.

**Date and PC gates:** `FG#2` waits for Forge's next release (the existing estimate is mid-November). Forge games (`FG#2`, `FG#3`) run one at a time in the main session, on an idle PC, with Matt's OK. Their pause doesn't prevent fixture-based development above.

## Deck Lab: access and privacy

**Owner:** [design/stories.md](decklab/design/stories.md), E10; privacy rules in [design/privacy-by-default.md](decklab/design/privacy-by-default.md), implementation slices and dependencies in [design/member-template.md §4](decklab/design/member-template.md#4-what-shipped-and-the-remaining-build-order).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E10-S41` | DEFERRED | could | L | Per-deck public (decision A): only once someone wants it. |
| `E10-S18` | DEFERRED | could | M | Small person-space items (`E10-S18` first-visit landing, `E4-S19` game players): only if a member asks. Check Settings, Visits first. |

## Deck Lab: decks, kit and the table

**Owner:** [design/stories.md](decklab/design/stories.md), E1, E2, E4 and E8.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E2-S16` | OPEN | could | L | Kept-for-later drafts built in source, the Quick edit's and new decks' too (migrations 0018 and 0019 unapplied). Left: live migrations and real-device checks. |
| `E2-S22` | DECISION | must | M | Physical hardware/touch-usability follow-up on the household's iPhones and M2 11-inch iPad; the six-configuration Safari Simulator suite passes ([evidence](decklab/safari/EVIDENCE.md)). |

## Deck Lab: collection, orders and buying

**Owner:** [design/stories.md](decklab/design/stories.md), E5, E6 and E7.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E5-S15` | DEFERRED | should | M | User1 asks from the page for a card or a Forge run, Matt approves (`E3-S13`); not urgent. |
| `E5-S08` | OPEN | could | XL | MTGMate checks cover queued and saved-home missing names on Shopping and deck Prices, read through per-shop adapters (`lib/shops/`, fixture pages); next research a second Australian shop (robots, page format, a live check) and add its adapter. |
| `E7-S32` | OPEN | could | L | Scan cards sheet and `POST /api/collection/scan` built, with each pending card's printing picker and language (fixture-tested); next real phone photos on the household's phones, then token cards for the Tokens page. |
| `E7-S24` | DECISION | could | L | The deck page lists the counter kinds and dice its cards use (read-only, approximate); Matt chooses the record shape for owned dice and counters, then its migration, the Tokens page's rows and whether each need is covered. |

## Deck Lab: Commander nights

**Owner:** [design/stories.md](decklab/design/stories.md#e9-commander-nights), E9.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E9-S26` | DECISION | could | M | Free pool cards for each Stats role are built; cited role targets (how many each role should have) wait on Matt choosing a template source. |
| `E9-S11` | DEFERRED | could | L+pc | Four-player pod runs from the page (with `E9-S21` win shares and `E9-S22` why-not by Start); after `FG#2`. First `lib/forge/pods.py` from the prototype, fixtures only. |

## Deck Lab: testing and Forge

**Owner:** [design/stories.md](decklab/design/stories.md), E3 and E11; Forge's own work in [PLAN.md](decklab/PLAN.md) (Still to do, items 2 and 3) and [forge-trial/ai-round1-handoff.md](decklab/forge-trial/ai-round1-handoff.md).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E3-S23` | OPEN | could | M | Membership view, exclusion counts, policy persistence, its use in home's field selection, the home-admin preview/save with Change the field, and failing closed when saved choices can't be read built (0017 unapplied). Next: 0017's activation and PostgreSQL/browser qualification (Matt's gate). |
| `E3-S19` | DEFERRED | could | M | Group run against chosen opponents: the page/API lacks an opponents subset for field runs (`field.opponents` has it). Useful only once a member deck is Public. |
| `E11-S28` | DECISION | should | M | Run the user-testing session with User2 from the prepared [checklist](decklab/design/user-testing-user2.md) (confirm his device first), then the follow-up review and stories. |
| `FG#2` | WAITING | should | L+pc | Forge 2.0.16 (about mid-November 2026): rebase the fork, build, check the overrides, replay every matchup. The post-build checks are one command, built 2026-10-21: `python -m decklab.lib.forge upgrade-check` (`--plan forge-2.0.16` prints the rebase and build steps; `E11-S15`), and `upgrade-check --dir <scratch folder>` checks the scratch build before it's installed (`E11-S45`). |
| `FG#3` | DEFERRED | could | M+pc | More experiment games (AI profiles, team-pump fix, override sets), decided with `FG#2`'s replay; the clean `fiery` test ran 2026-10-21 (C4 does what `fiery` does). |

## Deck Lab: running it

**Owner:** [design/stories.md](decklab/design/stories.md), E11.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S30` | DECISION | should | L | Visual redesign P1 ([visual-design.md](decklab/design/visual-design.md)): every slice is built and checked in dark; Matt decides Collection's filter (question 6) and checks touch/Safari on the household's devices. |
| `E11-S31` | DECISION | could | M | Global search in the top bar ([stories.md](decklab/design/stories.md#e11-s31)): Matt chooses sources and result grouping before building. |
| `E11-S08` | OPEN | could | L | Token deletions and 2-50 added token rows undo together (2026-10-29); 1-50 purchase-queue value edits restore in place (2026-10-30). Still open: queue additions/removals, token-card edit batches, other multi-row and mixed changes, other accessory/wishlist inverses. |
| `E11-S02` | DECISION | should | S | The "Deck Lab is off" Worker is deployed (`decklab/cloudflare/`): Matt checks a signed-in save, a photo upload, and the page with Deck Lab stopped. |

## Deck Lab: code hygiene

**Owner:** [SOURCE_AUDIT.md, Maintenance backlog](decklab/SOURCE_AUDIT.md#maintenance-backlog), with acceptance criteria in [design/stories.md](decklab/design/stories.md), E11-S36 to E11-S43. These are bounded maintenance tasks; each leaves the row when its stated scope is done.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S39` | DECISION | could | M | Snapshot split built (`pg_snapshot.py`, fixture checks pass); Matt authorizes the disposable-database location, persistence and rollback qualification. |

## Areas with no open rows

A new row for one of these gets its section back.

| area | owner | a row returns with |
|---|---|---|
| Magic decks and buying | Deck Lab's deck list (`python -m decklab.db deck list`) and Shopping (`#/shopping`: deliveries, the purchase queue) | a deck or buying project that spans sessions |
| Pokémon | `pokemon/collection.csv`, `pokemon/wishlist.csv` | a change Matt asks for |
| Deck Lab's known low issues | HISTORY.md, each feature's "Known low issues" | one getting in the way |

---

## How to read this file

Rules for writing it: read them before editing a row, not before picking one.

**This file is an index, not a work order.** One row per open item: an id, a status, two grades, one clause and a pointer. Why an item matters, how to build it and its acceptance criteria belong in its owner (usually its story in [design/stories.md](decklab/design/stories.md)); a second copy here goes stale unnoticed.

1. **A row leaves this file in the same commit that finishes it.** Flip the story's status in stories.md, add the dated entry to HISTORY.md, and delete the row; no closed rows stay here. An emptied section becomes one line under "Areas with no open rows".
2. **The owner is the source of truth.** When this file and its owner disagree, this file is stale.
3. **When part of an item lands, replace the clause with what's left;** don't append to it. Keep a row under about 300 characters.
4. **New work starts as a story** under a persona in stories.md (see [design/README.md](decklab/design/README.md)), then gets a row here. Work with no story (Forge, the database move) gets an `FG#` or `DB#` id, owned by PLAN.md.
5. **NOW changes only when its items finish or Matt reorders them.**
6. **Keep a ready reserve, not invented work.** When the queue runs low, check existing stories against the code before promoting them. Give each `OPEN` item a concrete first slice in its owner, name real dependencies, and separate coding from device checks, dates and costly runs. Story coverage in the design model is broader than this scheduled queue.

**`id`:** a stable handle, not an order. A story's id where one owns the item (`E10-S03`), else `FG#n` (Forge) or `DB#n` (database); a retired id is never reused. Other ids an item covers are named in its clause.

**`status`**, a closed list:
- `OPEN`: a concrete next slice is ready to work; later dependencies and acceptance gates are in its owner.
- `DECISION`: the next step needs Matt (a call, or his presence or devices). Always listed in NOW.
- `WAITING`: waits for a date or an outside event (a release, the end of a check week).
- `BLOCKED`: can't be worked today (a busy PC, a missing prerequisite).
- `DEFERRED`: paused by priority; picked up only when NOW admits it or its condition is met.

**`pri`:** the story's MoSCoW priority for its persona: `must` · `should` · `could`. Things Matt decided against (budgets, arrival dates, offline deck lists, Forge result backups) are `not_wanted` stories and never get rows.

**`size`:** as in the design model: `S` a session or less · `M` a few sessions · `L` a week or more · `XL` several weeks. `+pc` means the real cost is idle PC time for Forge games, run serially.

**Privacy:** like the design files, this is committed to a public repo, so anyone may read it. Nothing about tuning one player's decks against another's, no prices paid, no wishlist notes.
