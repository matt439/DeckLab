# TODO: open work

An index of open work, one row per item; each row points to the doc that owns the detail. The rules for editing it are at the end, in [How to read this file](#how-to-read-this-file). A fresh thread starts here: read **NOW**, then the owner of the row it picks up.

## NOW

**The only ordering in this file.** Keep every `DECISION` row here. Keep this block to the current aim and the next few actions; results go in their owners (HISTORY.md for what shipped).

**Ready work (2026-11-20).** All 12 rows from the 2026-11-20 audit are complete. Against popular decks remains the lead feature. The redesign is at household device acceptance.

**Sessions and decisions.** Pick these up when the named people, devices or systems are available. Each row below points to the owner and records the remaining check.

- **Household phones and iPad.** Use the [20 November walkthrough](decklab/design/ui-ux-review-2026-11-20.md#verification-and-the-next-household-session) for building from the collection, taking shortages to a shop, scanning a small batch and starting a pod. Resume drafts across devices (`E2-S16`), check touch and layout (`E2-S22`, `E11-S30`), global search (`E11-S31`), pod controls and results (`E9-S11`), VoiceOver (`E11-S55`), real card and token photos from each phone (`E7-S32`), and cold/repeat load timings (`E11-S64`). The [Safari Simulator evidence](decklab/safari/EVIDENCE.md) covers repeat functional checks.
- **Signed-in browser and wake.** Check the off page, deck save and photo upload (`E11-S02`), browser policy and camera (`E11-S63`), and real phone access, scanning and timed wake on the Linux installation (`E11-S58`). The wake-on-request check (`E11-S59`) follows the owner-authenticated NAS update (`E11-S75`, deferred). Time a real request through the hardened gate.
- **Forge and XMage.** Exercise the saved field choice in a browser and a real run, then restore the policy (`E3-S23`). Qualify Syr Elenora's engine behavior (`FG#4`), the corrected XMage bridge on the installed server (`E3-S40`), and the separate Forge side-build speed/winner comparison (`FG#2`). Real Forge runs need Matt's OK and run one workflow at a time on an idle PC. The completed replay and pod games are recorded in [PLAN.md](decklab/PLAN.md#details).
- **People.** Matt reviews and publishes the draft release (`E11-S49`). Arrange User2's device and [testing session](decklab/design/user-testing-user2.md) (`E11-S28`).
- **Waiting for data.** The earlier-lists browser check (`E3-S50`) needs a deck with several genuinely tested lists. The last server review found none.

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
| `E2-S16` | DECISION | could | L | Implementation built, including Quick edit and new-deck drafts. Left: same-profile resume, competing drafts and save/discard across the household's real devices; fixtures cannot qualify touch/Safari or device durability. |
| `E2-S22` | DECISION | must | M | Physical hardware/touch-usability follow-up on the household's iPhones and M2 11-inch iPad; the six-configuration Safari Simulator suite passes, on the P1 redesign since 2026-11-05 ([evidence](decklab/safari/EVIDENCE.md)). |

## Deck Lab: collection, orders and buying

**Owner:** [design/stories.md](decklab/design/stories.md), E5, E6 and E7. [Design discussion on building decks with a partially recorded collection](decklab/design/playing-with-a-partial-collection.md).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E5-S15` | DEFERRED | should | M | User1 asks from the page for a card or a Forge run, Matt approves (`E3-S13`); not urgent. |
| `E7-S32` | DECISION | could | L | Card/token scanning and reviewed one-change import built. Left: 10–20 real photos on each household phone, including foils, sleeves, old cards and token cards; actual photos/devices are needed. |

## Deck Lab: Commander nights

**Owner:** [design/stories.md](decklab/design/stories.md#e9-commander-nights), E9.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E9-S11` | DECISION | could | L | Real 16-game rotated pod, statistics and Stop/resume passed 2026-11-18 after the replay gate. Left: chooser, progress pill and result acceptance on the actual phone/iPad. |

## Deck Lab: testing and Forge

**Owner:** [design/stories.md](decklab/design/stories.md), E3 and E11. [PLAN.md, Still to do](decklab/PLAN.md#still-to-do) owns `FG#4`. Its [Forge experiment details](decklab/PLAN.md#details) cover `FG#2` and `FG#3`.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E3-S50` | WAITING | could | M | Check Show earlier lists in a browser once several tested lists exist for a deck. The 2026-11-18 scan found none. |
| `E3-S23` | DECISION | could | M | Temporary exclusion/run/restoration authorised 2026-11-18; browser controls unavailable, live policy untouched. Left: real-browser preview/save, real policy-backed run and restoration. |
| `FG#4` | DECISION | should | M+pc | Ordinary pilot's cast veto traced. Run the [two-game Syr Elenora / Lu Meng control](decklab/forge-trial/syr-elenora-pilot.md) in an approved idle window, then review both cast observers. |
| `E11-S28` | DECISION | should | M | Run the user-testing session with User2 from the prepared [checklist](decklab/design/user-testing-user2.md) (confirm his device first), then the follow-up review and stories. |
| `FG#2` | DECISION | should | L+pc | Agree an idle window for the [side-build speed and winner comparison](decklab/PLAN.md#details). The 2.0.16 replay was complete at the 2026-11-18 review. |
| `FG#3` | DEFERRED | could | M+pc | More experiment games (AI profiles, team-pump fix, override sets), decided with `FG#2`'s replay; the clean `fiery` test ran 2026-10-21 (C4 does what `fiery` does). |
| `E3-S40` | DECISION | should | L+pc | Corrected isolated bridge passed 8 positive games and independent identity/outcome checks. Left: deploy and qualify it live; earlier negative receipts remain, with genuine unsupported identities explicit. |

## Deck Lab: running it

**Owner:** [design/stories.md](decklab/design/stories.md), E11.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S30` | DECISION | should | L | [UI implementation and Chromium review](decklab/design/visual-polish-completion-2026-11-07.md) complete; household Safari/touch, software keyboards, screen reader and real-art acceptance remain. |
| `E11-S31` | DECISION | could | M | Global search in the top bar ([stories.md](decklab/design/stories.md#e11-s31)) is built and its `/` decided (2026-10-31): Matt checks the iPad field and phone sheet on devices. |
| `E11-S58` | DECISION | should | L | Full live smoke passed 16/16 with no warnings/failures/skips and a clean idle build (2026-11-18). Left: actual phones/card photographs and timed hardened-gate wake. |
| `E11-S49` | DECISION | could | M | Release zips, installs without git, the newer-release line and release notes are built; `v0.1.0` tagged 2026-11-14 and its draft release made; left: Matt publishes the draft. |
| `E11-S50` | DEFERRED | could | L | One Windows installer (winget Python and PostgreSQL, release zip, generated postgres password, config questions, services, one firewall prompt, phone address); after `E11-S49`. |
| `E11-S51` | DEFERRED | could | M | Update command for release installs (backup, replace, migrate, restart); after `E11-S49`. |
| `E11-S52` | DEFERRED | could | L | First-run setup page on the PC (home profiles, optional Enable simulations); after `E11-S50`. |
| `E11-S59` | DECISION | could | L | Installed gate/tunnel/Worker/Access and nightly timer reviewed 2026-11-18; timer wake observed in journal. Left: hardened gate deployment and timed real request wake with `E11-S75`. |
| `E11-S02` | DECISION | should | S | The "Deck Lab is off" Worker is deployed (`decklab/cloudflare/`): Matt checks a signed-in save, a photo upload, and the page with Deck Lab stopped. |
| `E11-S55` | DECISION | could | M | Accessibility audits and fixes of every page, both densities, done (2026-11-04); left: a check with a real screen reader (VoiceOver on the household's devices). |
| `E11-S57` | DEFERRED | could | L | A Linux install route (a script or container); after `E11-S50` (Windows first, Matt, 2026-10-31) and `E11-S49`. |
| `E11-S63` | DECISION | could | S | Live HTTP policy headers verified directly/through gate 2026-11-18. Left: real Safari/device scanning, browser-console and home-page wake checks; desktop automation unavailable. |
| `E11-S64` | DECISION | could | S | Live gzip/immutable versioned assets verified directly/through gate 2026-11-18. Left: phone/iPad cold/repeat timings; pre-change device baseline unavailable, no measured gain. |
| `E11-S75` | DEFERRED | could | M | Earlier NAS gate source/stack remains deployed. Authenticated HomeOps deployment is prepared and deferred until the owner is home to authenticate; hardening/bounds and real WOL checks follow. |

## Areas with no open rows

A new row for one of these gets its section back.

| area | owner | a row returns with |
|---|---|---|
| Magic decks and buying | Deck Lab's deck list (`python -m decklab.db deck list`) and Shopping (`#/shopping`: deliveries, the purchase queue) | a deck or buying project that spans sessions |
| Pokémon | `pokemon/collection.csv`, `pokemon/wishlist.csv` | a change Matt asks for |
| Deck Lab's known low issues | HISTORY.md, each feature's "Known low issues" | one getting in the way |
| Deck Lab: code hygiene | [SOURCE_AUDIT.md, Maintenance backlog](decklab/SOURCE_AUDIT.md#maintenance-backlog), E11-S36 to E11-S43 in [design/stories.md](decklab/design/stories.md) | a bounded maintenance task |

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
