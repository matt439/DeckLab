# TODO: open work

An index of open work, one row per item; each row points to the doc that owns the detail. The rules for editing it are at the end, in [How to read this file](#how-to-read-this-file). A fresh thread starts here: read **NOW**, then the owner of the row it picks up.

## NOW

**The only ordering in this file.** Keep every `DECISION` row here. Keep this block to the current aim and the next few actions; results go in their owners (HISTORY.md for what shipped).

**Aim (updated 2026-10-26):** finish the visual redesign (`E11-S30`), then work through the remaining rows Matt added on 2026-10-25: making Deck Lab easy to self-host for people outside the household (`E11-S32`, `E11-S33`) and finishing the token and kit work (`E7-S21`). The private member model is built and live (see Activation below); household device acceptance remains.

**Ready queue:** `E11-S30`, the visual redesign Matt chose on 2026-10-24 ("P1"). Slice 14 of [visual-design.md](decklab/design/visual-design.md#7-rollout) is implemented, as are slice 13's scoped recorded packing activity, verified intact-product storage review and per-card movable-copy priorities. Exact physical printing still needs a confirmed-printing model; independent ready reserve work can continue while it is designed. Slice 15's empty, loading and failed states are drawn and built, and dark mode was checked on full data (2026-10-27); Matchups with saved results in dark and device acceptance remain open. The approved desktop keyboard plan is built; global search has its separate decision below. Explicit original-row associations for newly added arrival checks are implemented, with component-wide verification retained; targeted backend/UI and isolated native checks passed. Casual inline verification placement is implemented for proven targets, with single canonical controls, component-wide semantics and verified fallback; final UI/native checks and caption review passed. Collection question 6 and touch/Safari acceptance remain separate gates, with Card colour matching the compatibility default.

**Ready reserve:** after the redesign, the `OPEN` rows Matt added on 2026-10-25 have concrete first slices in their stories, in no fixed order unless Matt picks one. `E11-S08` retains broader recovery work beyond its implemented single-row Undo review. The 2026-10-26 audit checked the reserve against the code: no extra stories need promoting. Release publication, Linux service/timer installation, device checks and Forge games retain their separate gates.

**Needs Matt or another person — these don't block coding:**
- **`E11-S31`: global-search scope.** Choose the sources (visible decks, the viewer's collection and/or all Scryfall cards) and result grouping before building. Library title, colour and archetype filters (`E1-S05`) are built independently of that decision.
- **`E2-S22`: physical-device follow-up.** Confirm hardware and touch usability on the household's actual iPhones and M2 11-inch iPad after the fixes. Keep prior results in the story; the [Safari Simulator suite](decklab/safari/EVIDENCE.md) covers repeat functional regressions.
- **`E11-S02`: signed-in off-page check.** On a phone through decklab.example.com, save a deck edit, upload an accessory photo, and check the off page while Deck Lab is stopped.
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
| `E2-S22` | DECISION | must | M | Physical hardware/touch-usability follow-up on the household's iPhones and M2 11-inch iPad; the six-configuration Safari Simulator suite passes ([evidence](decklab/safari/EVIDENCE.md)). |

## Deck Lab: collection, orders and buying

**Owner:** [design/stories.md](decklab/design/stories.md), E5, E6 and E7.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E7-S21` | OPEN | could | L | Box reviews, dates, Library filters and Collection/intended-list review offers are built. Physical-list repair remains. |
| `E5-S15` | DEFERRED | should | M | User1 asks from the page for a card or a Forge run, Matt approves (`E3-S13`); not urgent. |
| `E5-S24` | DEFERRED | could | S | Copy one shop's list from Shopping's By shop, for pasting into the shop's search. |

## Deck Lab: testing and Forge

**Owner:** [design/stories.md](decklab/design/stories.md), E3 and E11; Forge's own work in [PLAN.md](decklab/PLAN.md) (Still to do, items 2 and 3) and [forge-trial/ai-round1-handoff.md](decklab/forge-trial/ai-round1-handoff.md).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S28` | DECISION | should | M | Run the user-testing session with User2 from the prepared [checklist](decklab/design/user-testing-user2.md) (confirm his device first), then the follow-up review and stories. |
| `FG#2` | WAITING | should | L+pc | Forge 2.0.16 (about mid-November 2026): rebase the fork, build, check the overrides, replay every matchup. The post-build checks are one command, built 2026-10-21: `python -m decklab.lib.forge upgrade-check` (`--plan forge-2.0.16` prints the rebase and build steps; `E11-S15`). |
| `FG#3` | DEFERRED | could | M+pc | More experiment games (AI profiles, team-pump fix, override sets), decided with `FG#2`'s replay; the clean `fiery` test ran 2026-10-21 (C4 does what `fiery` does). |

## Deck Lab: running it

**Owner:** [design/stories.md](decklab/design/stories.md), E11.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S30` | OPEN | should | L | Visual redesign P1 ([visual-design.md](decklab/design/visual-design.md)): slice 13's confirmed-printing model, slice 15's dark Matchups with saved results, and Collection's filter decision. Empty/loading/failed states are built. Touch/Safari acceptance stays open. |
| `E11-S31` | DECISION | could | M | Global search in the top bar ([stories.md](decklab/design/stories.md#e11-s31)): Matt chooses sources and result grouping before building. |
| `E11-S32` | OPEN | could | M | A prebuilt release of the Forge fork, with a checksum, as SELF-HOSTING.md's first Forge route. |
| `E11-S33` | OPEN | could | L | Interpreter paths and nightly systemd unit previews have isolated checks. Real Linux 3.14/full suite, CI, service/timer integration and host acceptance remain. |
| `E11-S08` | OPEN | could | L | Narrow inventory, wishlist and accessory recovery is built. Mixed receipts/imports and broader recovery remain. |
| `E11-S02` | DECISION | should | S | The "Deck Lab is off" Worker is deployed (`decklab/cloudflare/`): Matt checks a signed-in save, a photo upload, and the page with Deck Lab stopped. |

## Areas with no open rows

A new row for one of these gets its section back.

| area | owner | a row returns with |
|---|---|---|
| Magic decks and buying | Deck Lab's deck list (`python -m decklab.db deck list`) and Shopping (`#/shopping`: deliveries, the purchase queue) | a deck or buying project that spans sessions |
| Deck Lab: Commander nights | [design/stories.md](decklab/design/stories.md#e9-commander-nights), E9 | a Commander story promoted from its Open list |
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
