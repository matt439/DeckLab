# Deck Lab: design model

A formal, user-centred design model of Deck Lab, first written on 2026-10-13: who it's for, what they're trying to do, what each of them needs, and how much of that is built.

- **Written:** 2026-10-13
- **Coverage updated:** the full code recheck was 2026-10-19. Targeted reviews on 2026-10-28 added five feature and eight maintenance stories and corrected stale E1-S12 and E7-S18 summaries; the counts below were recounted from all story headers. E11-S44 was added later for the fixture-only test entry point. The maintenance evidence and split boundaries are in [SOURCE_AUDIT.md](../SOURCE_AUDIT.md#maintenance-backlog). Private by default and guarded member departure are built and live since migrations 0012 and 0013 were applied on 2026-10-19. Physical-device acceptance remains E2-S22.
- **Covers:** Deck Lab, the home-network and decklab.example.com deck page, and the `python -m decklab.db` commands Claude Code works through. Magic only.
- **Doesn't replace:** [TODO.md](../../TODO.md) (the open-work index and NOW order), [PLAN.md](../PLAN.md) (the details of non-story work), [HISTORY.md](../HISTORY.md) (what shipped), [UI-KIT.md](../UI-KIT.md) and [UI-REVIEW.md](../UI-REVIEW.md) (the page's pieces and the redesign's reasons).

## The files

| File | What's in it |
|---|---|
| README.md | This page: the method, the index, how to keep it up to date |
| [personas.md](personas.md) | Who Deck Lab is for (and isn't), each with goals, facts, assumptions and a critique |
| [journeys.md](journeys.md) | Scenarios and a journey map for each epic, step by step, with the pain points |
| [stories.md](stories.md) | The user stories, by epic, each with acceptance criteria, a priority and a status |
| [visual-design.md](visual-design.md) | The look Deck Lab is moving to (Matt's pick of 2026-10-24, "P1": casual on the phone, a lab on the desktop): tokens, the density switch, components, per-page notes, open questions and the rollout slices of E11-S30 |
| [gap-analysis.md](gap-analysis.md) | What's built, partial and missing for each persona, and a roadmap from it |
| [privacy-by-default.md](privacy-by-default.md) | The design for Matt's decision of 2026-10-13 that every space's data is private unless made public (read-only, to everyone signed in; the 2026-10-18 member template renamed it): the rule and switches, every surface before and after, Forge, his decisions, and the phased stories E10-S28 to E10-S36 (see also [member-template.md](member-template.md), E10-S37 to E10-S43) |
| [member-template.md](member-template.md) | Matt's accepted member decisions of 2026-10-18 and, in §4, what shipped and in what order; all of it is built and live since 2026-10-19 except per-deck public (E10-S41, deferred). User5's invite was sent on 2026-10-18 |
| [user-testing-user2.md](user-testing-user2.md) | The prepared session checklist for E11-S28: the opening script, preparation and cleanup, goal-based tasks with success conditions, observation rules, the notes table, closing questions and the privacy rules for the notes |

## The method

1. **Evidence first.** Each epic started from what Deck Lab really does: the code (`decklab/web/`, `decklab/lib/api/`, `decklab/lib/inventory/`, `decklab/lib/permissions.py` and the rest), [PLAN.md](../PLAN.md), [HISTORY.md](../HISTORY.md), the UI documents, CLAUDE.md and the deck list. Nothing was taken from memory where a file could say it.
2. **Goal-directed personas.** Each persona has end goals, experience goals and life goals, the tasks and devices they use, and their frustrations. Every claim is marked as a **fact** (from the repo or what the user has said) or an **assumption** (a guess to check with the person). Each persona was then critiqued through three lenses: is it true to the evidence, is it respectful and private enough for the members who may read it, and is it specific enough to decide a design question with (and does the set leave anyone out).
3. **Scenarios.** Short, concrete stories of a persona using Deck Lab for a real job ("User1 picks a deck to play tonight on a phone").
4. **Journey maps, one per epic.** The steps, the page or command at each step, what the persona thinks and feels, and where it goes wrong.
5. **User stories.** "As a <persona>, I want <goal>, so that <reason>", each with Given/When/Then acceptance criteria that can be checked against the page or a command.
6. **Priorities and statuses.** Each story has a MoSCoW priority (must, should, could, won't) for its persona, and a status: **built**, **partial**, **missing** or **not wanted**. Every status was then checked adversarially against the code: a second pass tried to prove each "built" wrong and each "missing" already there, and changed the status where it could.
7. **A completeness critic.** A last pass looked for journeys with no stories, personas with no stories, and parts of Deck Lab no story covers, and filled the gaps.
8. **Gap analysis and roadmap.** The must and should stories that aren't built, by persona, ranked into a roadmap and compared with PLAN.md's "Still to do".

## The personas

Details in [personas.md](personas.md).

| Id | Persona | Kind |
|---|---|---|
| `matt` | Matt, the deck builder and buyer | Primary |
| `user1` | User1, the themed-deck player | Primary (for the phone surfaces: deck page, library, Wishlist, Packing plan, Game log) |
| `user5` | User5 (`user5`), the member: the first real member, whose setup is the template for every member | Secondary |
| `space-members` | User2, User3 and User4, the person-space members, on the same terms as User5 | Secondary |
| `commander-table` | The Commander-night table at a local game store | Supplementary (served, never uses Deck Lab) |
| `claude-code` | Claude Code, the command-line operator | Non-human actor |
| `anti-collector` | The value collector | Anti-persona |
| `anti-grinder` | The tournament grinder | Anti-persona |
| `anti-stranger` | The stranger on the internet | Anti-persona |

Matt also keeps Deck Lab running as the household's admin; those operator duties are noted separately in his persona and covered by E11.

## The epics

Each epic has a journey in [journeys.md](journeys.md) and its stories in [stories.md](stories.md).

| Epic | Title | What it covers | Built | Partial | Missing | Not wanted |
|---|---|---|---|---|---|---|
| E1 | Find, plan and choose decks | The library (`#/library`), deck ideas, cover pictures, the deck page's banner and Overview, choosing what to play | 14 | 1 | 0 | 0 |
| E2 | Build and edit a deck | New deck, the editor and the phone Quick edit, Planned and Play-now lists, owned vs needed, history; `deck pull/push/new/tables` | 17 | 1 | 1 | 1 |
| E3 | Test a deck | Stats, Practice, Forge matchups (`#/matchups`, `#/matchup`), field rank, Test this change (`#/variant`), the simulations setting | 12 | 3 | 0 | 0 |
| E4 | Get ready, play and learn | The Packing plan (`#/assembly`), tokens to grab, How to play, practice hands, the Game log (`#/play`) and sideboard plans | 17 | 3 | 1 | 1 |
| E5 | Decide what to buy | Missing cards and estimated costs, the purchase queue on `#/shopping`, AU shop checks, buylists, `watchlist` and `order add --fulfils` | 18 | 1 | 1 | 2 |
| E6 | Record orders and receive cards | `order add\|edit\|checks\|split\|cancel`, products, on the way, Receive delivery (`#/receipt`), follow-ups, keeping a product intact | 18 | 0 | 0 | 2 |
| E7 | Keep the collection accurate | The Collection page (`#/collection`), imports and Add a precon, `collection merge`, Tokens (`#/tokens`), removals, stale tables, `db check` | 24 | 0 | 4 | 0 |
| E8 | Sleeves, boxes and storage | Sleeves & boxes (`#/accessories`), Sleeves and Deck box lines, the Choose… picker, kit warnings, put-back steps, the storage box | 16 | 0 | 1 | 2 |
| E9 | Commander nights | Commander checks and the minimum bracket, multiplayer practice, Forge's Commander field, getting ready for the social Commander night | 15 | 1 | 3 | 1 |
| E10 | Members, access and privacy | Roles and spaces, the read and write rules, "Who are you?", decklab.example.com behind Cloudflare Access, Activity (`#/activity`), Visits on Settings, private by default | 31 | 1 | 1 | 2 |
| E11 | Run and trust the system | The server and tunnel, database maintenance, audit trail, typed commands, Forge upkeep, Settings, Safari regressions, visual design and code hygiene | 28 | 6 | 2 | 3 |

## Headline counts

- **9 personas:** two primary, two secondary (User5 and the space members), one supplementary, one non-human actor and three anti-personas.
- **11 epics, 255 stories:** 211 built, 16 partial, 14 missing and 14 not wanted (recounted from current story headers on 2026-10-29 after the feature, maintenance, doctor, sideboard-preview, pod-record and source-aware counter work).
- **Must and should stories:** Matt has 96 built and 3 partial; User1 has 32 built, 1 partial and 1 missing; Claude Code has 23 built and no remaining must or should gap; User5 has 4 built; the space members have 4 built; the Commander table has 1 built. The last three have no must or should gap. (Recounted from the story headers on 2026-10-28.)

Deck Lab already does most of what Matt and User1 need. Private by default and guarded member departure are built and live since 2026-10-19. The visual redesign (E11-S30) stays first, followed by the expanded reserve of deck-building, collection, buying, play and self-hosting work reviewed on 2026-10-28. [TODO.md](../../TODO.md) owns their order and readiness; each story owns its first slice and later gates. The other must and should gaps are the physical-device follow-up (E2-S22), the signed-in off-page check (E11-S02) and User2's testing session (E11-S28), which need the people involved; and User1's purchase requests (E5-S15), which are deferred. Stand-in suggestions, combo detection, official-list change detection, the Forge upgrade check, the prebuilt Forge release and Linux support are already built.

## Decisions

Matt answered the model's open questions on 2026-10-13, and accepted the member template's decisions A to K on 2026-10-18. The answers are listed, question and answer, under [Answered 2026-10-13](personas.md#answered-2026-10-13) and [Answered 2026-10-18](personas.md#answered-2026-10-18) in personas.md; each story a decision still shapes has a **Decided (Matt, date)** line in [stories.md](stories.md), and the counts above include them. The questions still open are at the end of [personas.md](personas.md#open-questions-to-validate-with-matt).

## Using and keeping it up to date

- **When a feature ships,** change its stories' status in [stories.md](stories.md) (missing to partial or built), replace the story's **Now** line (at most three lines, dated, linking its [HISTORY.md](../HISTORY.md) entry) and its **Evidence** (the files and the functions, routes or tests that meet the criteria, never line numbers), and cut its **Gap** to what's still unmet, or remove it. The story's history belongs in HISTORY.md and git, not in the story. Update the summary counts in stories.md, the epic counts here and the persona counts in [gap-analysis.md](gap-analysis.md).
- **A new request starts as a story** under a persona: "As <persona>, I want…, so that…", with Given/When/Then criteria, a priority, a size, the status `missing` and a **Gap** line. A decision that the criteria don't show goes in a **Decided (Matt, date)** line. Ids are never reused: a merged or dropped story leaves its number unused, and a split takes new numbers. If no persona fits, say so: either it's for a persona not yet written, or it's for an anti-persona and probably not wanted.
- **[TODO.md](../../TODO.md) is the index of open work,** in the order NOW gives; its rows use story ids (such as `E7-S03`) and point here for the detail. PLAN.md keeps the details of non-story work (Forge, the database move). This folder doesn't schedule work.
- **When a story ships,** flip its status here and delete its TODO.md row in the same commit.
- **HISTORY.md records what shipped,** as now. A dated line there is the evidence a story's status change points to.
- **Assumptions are to be checked.** When User1 or another member confirms or corrects something marked as an assumption in [personas.md](personas.md), change it to a fact (with the date) or fix it, and recheck the stories that rest on it.
- **Recheck statuses against the code,** not against this folder, before using them to decide anything. The statuses were last rechecked against the code on 2026-10-19.

## Out of scope

- **Pokémon.** The Pokémon side is a CSV inventory of full-art singles (`pokemon/`), not part of Deck Lab.
- **MTG Arena** and any digital play. Deck Lab is for physical cards.
- **Budgets and spending.** No spending totals, prices paid or collection value, by the household's decision. Estimated prices to buy missing cards are in scope; what was paid isn't.
- **Format legality on casual decks,** ban lists and rotation for 60-card play (the tournament grinder anti-persona). Commander's ban list and brackets are in scope.
- **An open-internet site.** Sign-up, anonymous deck pages and share links (the stranger anti-persona). An owner may make data public to everyone signed in, under the member template's accepted rules.
