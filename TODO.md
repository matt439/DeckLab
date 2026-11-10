# TODO: open work

An index of open work, one row per item; each row points to the doc that owns the detail. The rules for editing it are at the end, in [How to read this file](#how-to-read-this-file). A fresh thread starts here: read **NOW**, then the owner of the row it picks up.

## NOW

**The only ordering in this file.** Keep every `DECISION` row here. Keep this block to the current aim and the next few actions; results go in their owners (HISTORY.md for what shipped).

**Aim (updated 2026-10-28):** finish the visual redesign (`E11-S30`), then improve physical deck building, collection filing, buying and play while keeping the code maintainable. The feature reserve and maintenance lane below both contain ready work. The prebuilt Forge release (`E11-S32`), Linux support (`E11-S33`) and box-review work (`E7-S21`) are built. The private member model is built and live (see Activation below); household device acceptance remains.

**Lead feature (Matt, 2026-11-03):** Against popular decks, the gauntlet, is Deck Lab's lead feature. Its standard sample, headline and Overview panel (`E3-S33`), larger runs up to All overnight (`E3-S38`), results kept through a change, with before/after on the same opponents (`E3-S34`, ahead of `FG#2`), Testing next to Decks with the Popular decks board (`E3-S35`), the figure in the library with a strength sort (`E3-S36`) and an editor choice to test against popular decks after saving (`E3-S37`) are built: the lead's planned slices are done. Trying a precon before buying it, as a trial deck tested against our decks and popular decks (`E3-S39`, Matt 2026-11-03), is built too. A run against a chosen group of decks (`E3-S31`, finishing `E3-S19`) and testing a change against popular decks (`E3-S30`: `forge variant --gauntlet` and the editor's Test this change, with its by-group table) were built 2026-11-05. Left: `FG#4` to build the catalogue on the live spare PC, and the device checks of the new views with `E11-S30`'s.

**Ready queue:** `E11-S30`, the visual redesign Matt chose on 2026-10-24 ("P1"). Slice 14 of [visual-design.md](decklab/design/visual-design.md#7-rollout) is implemented, as are slice 13's scoped recorded packing activity, verified intact-product storage review and per-card movable-copy priorities. Exact physical printing is recorded as a built deck's Printings in box line (2026-10-27). Slice 15's empty, loading and failed states are drawn and built, dark mode was checked on full data (2026-10-27) and Matchups with saved results in dark (2026-10-29); device acceptance remains open. The approved desktop keyboard plan is built; global search has its separate decision below. Explicit original-row associations for newly added arrival checks are implemented, with component-wide verification retained; targeted backend/UI and isolated native checks passed. Casual inline verification placement is implemented for proven targets, with single canonical controls, component-wide semantics and verified fallback; final UI/native checks and caption review passed. Collection question 6 is decided and built (Find cards' colour filter matches colour identity, 2026-10-31); touch/Safari acceptance remains.

**Rendered UI work (2026-11-07):** The implementation lane is complete: shared/task repairs, deck/library composition, typography, constrained layouts, receipt pointer/footer recovery and remaining page/state families. The [final review](decklab/design/visual-polish-completion-2026-11-07.md) retains paired comparisons, 106 page/state, 104 actual Chromium zoom and 24 receipt/persistence cases, plus existing matrices. Household Safari/touch/software-keyboard, screen-reader, real-art and production durability acceptance remain; `E11-S30` stays partial. Repeat checks through the [repo headless workflow](decklab/ui_review/README.md).

**Ready reserve (audited 2026-10-29):** after the redesign, choose an `OPEN` row below; there is no fixed order within the reserve. The 2026-10-29 audit checked every row against the code and added fifteen stories. Matt's three requests of 2026-10-29 (`E3-S27`, `E5-S26`, `E6-S27`) and the split keeping the extra-copies mark (`E6-S25`) were built the same day, as were free pool replacements and dual lands (`E3-S25`), queueing a deck's missing cards (`E5-S25`), decks a delivery made ready (`E6-S26`), last played in the library and on the deck Overview (`E1-S27`), the warm-worker fallback sentence (`E3-S26`), How to play's departed cards (`E2-S27`), the play sheet's At the table (`E9-S27`) and tonight's pairs on the Game log (`E1-S28`) and the staged Forge build's `upgrade-check --dir` (`E11-S45`) and sideboard-plan tests (`E4-S16`) (HISTORY.md). The rest are larger: drafts across devices (`E2-S16`, kept-for-later drafts built 2026-10-29, the Quick edit's and new decks' included, with migrations 0018 and 0019 applied) and field-policy editing (`E3-S23`, its selection, preview/save and failing closed built 2026-10-29, migration 0017 applied). Every `OPEN` story names a concrete first slice in its owner. Fixture-based work needs no new Forge games, household records or physical devices; real-device acceptance, live installations/migrations, purchases and Forge runs keep their separate gates. The expansion review of 2026-10-31 added twelve stories for work no story covered (`E1-S29`, `E4-S27`, `E5-S27` to `E5-S30`, `E9-S28`, `E9-S29`, `E11-S54` to `E11-S57`); its OPEN rows below each name a first slice; of its three DECISION rows, Matt decided `E5-S29` (wanted), `E11-S54` and `E4-S27` (not wanted) on 2026-11-03.

**Product review (2026-11-10):** a comparison with similar tools, each proposal checked against the code and this backlog, added 53 stories for the parts no story covered (`E1-S30`, `E1-S31`, `E2-S28` to `E2-S32`, `E3-S41` to `E3-S48`, `E4-S29` to `E4-S34`, `E5-S32` to `E5-S35`, `E6-S28`, `E7-S34` to `E7-S38`, `E9-S30` to `E9-S33`, `E10-S44`, `E10-S45`, `E11-S62` to `E11-S77`). Their rows below join the reserve with no order among them, and Matt hasn't decided any of them wanted. `E11-S62`'s leak guard is built (2026-11-10); its history-rewrite decision is listed below. Pokémon and Build decks for a member's space were proposed too and left out, as recorded non-goals.

**First-run review (2026-11-10):** a review of installing and using Deck Lab as a newcomer ([first-run-review-2026-11-10.md](decklab/design/first-run-review-2026-11-10.md)) verified 76 findings and added seven self-hoster stories (`E11-S78` to `E11-S84`) that cover them all; their rows below join the reserve with no order among them. The biggest obstacle is PostgreSQL's failures all reading the same (`E11-S78`); `E11-S84`'s gitignore of update's config.json copy guards this public repo.

**Maintenance lane (updated 2026-10-29):** Tokens' workflow split and the source-length CI guard (`E11-S36`, `E11-S43`) are built. The editor workflow and collection parser splits (`E11-S37`, `E11-S38`) are built, creating room for their upcoming features. Keep structural and feature changes separate. The comment and command-document audits (`E11-S41`, `E11-S42`) are built. The fixture-only test entry point (`E11-S44`) is built. The test-group split (`E11-S40`) is built; the PostgreSQL snapshot split (`E11-S39`) is built and qualified on throwaway databases (2026-10-31). The editor drafts split (`E11-S46`) is built, leaving `web/editor.js` at 1,017 lines for `E2-S16`. The old-file wording in messages (`E11-S12`) is built. The [source-maintenance owner](decklab/SOURCE_AUDIT.md#maintenance-backlog) records the measured files, boundaries and validation. Length is a review trigger, not a reason to divide every large file mechanically. The accessibility pass (`E11-S55`) is built bar a real screen-reader check (in NOW). The long-file audit of 2026-11-05 split `web/collection.js` (Add a precon, into `web/precon-add.js`) and `web/components.css` (Forge results, into `web/sim-ui.css`), and recorded a seam for each of the other 34 files over 1,000 lines for when a change needs the room.

**Needs Matt or another person — these don't block coding:**
- **`E11-S31`: global search's device check.** Built 2026-10-31, `/` decided (the Editor keeps its own; global search everywhere else); check the iPad field and phone sheet with `E11-S30`'s device check.
- **`E2-S22`: physical-device follow-up.** Confirm hardware and touch usability on the household's actual iPhones and M2 11-inch iPad after the fixes. Keep prior results in the story; the [Safari Simulator suite](decklab/safari/EVIDENCE.md) covers repeat functional regressions.
- **`E11-S02`: signed-in off-page check.** On a phone through decklab.example.com, save a deck edit, upload an accessory photo, and check the off page while Deck Lab is stopped.
- **`E11-S30`: the redesign's last gate.** Collection's colour filter is decided and built (colour identity, 2026-10-31); Matt checks touch and Safari on the household's iPhones and iPad (MacBook connected, from 2026-10-31); the Safari Simulator suite passes 60/60 on the redesign (2026-11-05, [evidence](decklab/safari/EVIDENCE.md)).
- **`E11-S58`: the Linux server PC's own checks.** WSL already qualified the database, backups, the services, `systemd-inhibit` under polkit and real Forge games (2026-11-02). After the move (SELF-HOSTING.md, "From a Windows server to a Linux one"), run `python -m decklab.smoke` there, try it from the phones, scan a few real card photos with Tesseract, and let the PC sleep and wake through the gate and the wake timer.
- **`E7-S32`: real photos for Scan cards.** Take 10 to 20 photos of cards (a few foils, a few sleeved, one old card) with Collection's **Scan cards…** on each phone, plus a few token cards with Tokens' **Scan token cards…**, or copy them to the PC for `python -m decklab.lib.scan` (`--tokens` for token cards); the sheets and their APIs are fixture-tested only.
- **`FG#4`: the gauntlet on the live server.** With Matt's OK, build the catalogues on the Linux spare PC, measure its Commander throughput and play a first standard run per Commander deck (PLAN.md, Still to do, item 12).
- **`E3-S43`: the popular decks list's export and import.** The built line and `gauntlet build`'s difference are built (2026-11-10). Decide with `FG#4` whether the server gets a copy of the development PC's catalogue (then `gauntlet export`/`import` is built) or builds its own.
- **`E11-S59`: wake-on-request, set up for real.** Built in code (2026-11-01): put the wake gate and its tunnel on the NAS, make the Access service token, deploy the Worker with its secrets, set the server PC's BIOS and adapter to wake, then time a real wake (decklab/README.md, "Sleeping and waking on request").
- **`E8-S25`: the storage setting's questions.** Answer part 4 of [storage-setting.md](decklab/design/storage-setting.md) (containers, where it's kept, home's default) before slice 2 is built.
- **`E11-S61`: the More menus.** Decide on [more-menus-review.md](decklab/design/more-menus-review.md)'s recommended moves; then they're made.
- **`E11-S49`: the first release.** Tag a version on main to publish the first release zip; Settings' newer-release line is built.
- **`E11-S55`: a real screen reader.** The audits and fixes are done; try VoiceOver on an iPhone or the iPad over the library, a deck page and the Game log.
- **`E4-S33`: a solo practice board.** Decide whether playing a kept practice hand out by hand, with no rules engine, is practice for the physical deck or the digital play Deck Lab doesn't do; it isn't built without a yes.
- **`E11-S62`: a history rewrite, or not.** The leak guard is built and in CI's lint; a search of every commit for `config.json`'s values (emails, the domain, the Access team address, the AUD tag) found none, so no rewrite looks needed. Decide, and try the README's `--config wrangler.local.toml` deploy at the next Worker deploy.
- **`E11-S63`: the content policy in real browsers.** Built and tested (2026-11-10). After the server is updated, open Deck Lab in Safari on the iPad and a phone and on a desktop, scan a card (`E7-S32`), watch the console for "Refused to..." lines, and confirm wake-on-request still opens the gate from a home page.
- **`E11-S64`: the load, timed on devices.** Built and tested (2026-11-10). Time a phone's and the iPad's page load on the live server before and after the update that brings the cached, compressed scripts and stylesheets.
- **`E11-S84`: a stable update channel.** Config/update safety and local simulation settings are built; Matt decides the stable channel, its changelog and updates-available line before those are implemented.
- **`E11-S28`: User2's user-testing session.** Confirm his device, then use the prepared [checklist](decklab/design/user-testing-user2.md).

**Activation:** migrations `0012` and `0013` were applied and the server restarted on committed code on 2026-10-19, so the privacy code and guarded member removal are live. No visibility choice or real member removal has been made.

**Date and PC gates:** `FG#2` waits for Forge's next release (the existing estimate is mid-November). Forge games (`FG#2`, `FG#3`) run one at a time in the main session, on an idle PC, with Matt's OK. Their pause doesn't prevent fixture-based development above.

## Deck Lab: access and privacy

**Owner:** [design/stories.md](decklab/design/stories.md), E10; privacy rules in [design/privacy-by-default.md](decklab/design/privacy-by-default.md), implementation slices and dependencies in [design/member-template.md §4](decklab/design/member-template.md#4-what-shipped-and-the-remaining-build-order).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E10-S41` | DEFERRED | could | L | Per-deck public (decision A): only once someone wants it. |
| `E10-S18` | DEFERRED | could | M | Small person-space items (`E10-S18` first-visit landing, `E4-S19` game players): only if a member asks. Check Settings, Visits first. |
| `E10-S44` | OPEN | could | M | Member self-service: Download my space (zip) and a stateless Cards to get list for a member's own decks (needs Matt's decision beside E6-S22); first slice: a new lib/api/space_download.py streaming space_export.py's snapshot files, with a More item in collection.js. |
| `E10-S45` | OPEN | could | M | Harden member-reachable routes: pin the picture fetch to its checked address, bound fetches and staged pictures, lower the scan photo limit (needs Matt's decision on the accepted risk); first slice: pinned connect in lib/accessory_fetch.py with a changing-resolver test. |

## Deck Lab: decks, kit and the table

**Owner:** [design/stories.md](decklab/design/stories.md), E1, E2, E4 and E8.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E2-S16` | OPEN | could | L | Kept-for-later drafts built, the Quick edit's and new decks' too (migrations 0018 and 0019 applied by 2026-10-30). Left: real-device checks. |
| `E2-S22` | DECISION | must | M | Physical hardware/touch-usability follow-up on the household's iPhones and M2 11-inch iPad; the six-configuration Safari Simulator suite passes, on the P1 redesign since 2026-11-05 ([evidence](decklab/safari/EVIDENCE.md)). |
| `E8-S25` | DECISION | should | M | A setting for what a space's storage is like. The inventory and proposal are written ([storage-setting.md](decklab/design/storage-setting.md), 2026-11-05): Matt answers its part 4, then slice 2 (the record and its reader). |
| `E1-S30` | OPEN | could | M | Compare a deck with one of its History revisions or its published precon, with stat deltas and no extra deck; first slice: a same-deck revision side in web/compare.js, opt-in stats on the revision read in lib/api/history.py, and a link from History. |
| `E1-S31` | OPEN | could | M | Card viewer: outbound Scryfall and EDHREC links, a Your copies part by printing and location, and a card deep link, instead of a new card page; first slice: the Scryfall link in web/card-viewer.js with a server-built URL from lib/api/card_lookup.py. |
| `E2-S28` | OPEN | could | M | Commander Cuts view: the deck's own cards with countable cut reasons (EDHREC inclusion, roles above target, Forge never cast); first slice a read-only Cuts filter in See EDHREC ideas (lib/edhrec.py cuts(), deck-edhrec.js), no new fetch or migration. |
| `E2-S29` | OPEN | could | M | Suggested categories for untagged deck lines from the roles Deck Lab already derives, then categories remembered from the space's other decks and a deck_line category column; first slice a Suggest categories review sheet (lib/stats/category_suggest.py, deck-categories.js). |
| `E2-S31` | OPEN | could | M | Pool-checked bulk add: tick cards from another deck or a pasted list with free, in use, on the way and to buy marks and an identity filter; first slice Add cards from another deck in editor-import.js with no new storage; saved packages need Matt's decision. |
| `E2-S32` | OPEN | could | M | Lossless deck export (finishes and #categories) and more collection import formats (Archidekt, Dragon Shield, Delver Lens, TCGplayer, plain text lists); first slice offline only in deck-tools.js and collection_import.py; link import and location columns need Matt's decision. |
| `E4-S29` | OPEN | could | M | Merged counter/dice reminders and plan-wide coverage built. Left: an optional tickable/printable take-along list for selected physical built decks, with visible kit, packed tokens and own/shared playmats. |
| `E4-S30` | OPEN | could | S | Download a deck's play sheet as one text-only HTML file (needs Matt's decision, as he declined offline lists in E11-S27); first slice: split printDeck in web/deck-tools.js into a playSheet builder and add downloadPlaySheet beside Print play sheet in web/deck.js. |
| `E4-S31` | OPEN | could | M | Delete a saved game or pod record with a reason, then carry the counter's length and elimination facts into the result form; first slice: delete only, play_delete in lib/state/pg.py and memory.py, delete_game in lib/api/play_records.py, the action in web/play.js. |
| `E4-S32` | OPEN | could | M | Life counters: a screen wake lock for the pod counter, a note when the screen may sleep, then deeper Undo and deck-aware markers; first slice: wake request and release in web/pod-life-counter.js and the note in both counters, with fake wake lock tests. |
| `E4-S33` | DECISION | could | L | Play a kept practice hand out on a manual board (battlefield, graveyard, command zone, turns, Undo; needs Matt's decision on digital play); first slice: a board class beside OpeningHand in web/hands.js with model tests in tests/test_play_ui.py, nothing saved. |
| `E4-S34` | OPEN | could | M | Per-deck roll-up of recorded pod games (won W of N against the fair share, with a range and a minimum sample); first slice: a pure roll-up over visible pod records returned by lib/api/play_pods.py and one line in web/play-pods.js, no schema change. |

## Deck Lab: collection, orders and buying

**Owner:** [design/stories.md](decklab/design/stories.md), E5, E6 and E7.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E5-S15` | DEFERRED | should | M | User1 asks from the page for a card or a Forge run, Matt approves (`E3-S13`); not urgent. |
| `E7-S32` | OPEN | could | L | Scan cards sheet and `POST /api/collection/scan` built, with each pending card's printing picker and language, and Tokens' Scan token cards (`POST /api/tokens/scan`, one-change add) (fixture-tested); next real phone photos of cards and token cards on the household's phones. |
| `E5-S34` | OPEN | should | M | Condition and language in shop matching: show what the chosen listing is, then a home-admin preference applied in pick(); first slice display only, language as its own listing field and match() returning condition and language to the Shopping line. |
| `E5-S35` | OPEN | could | M | Record a shop snapshot reading as a queue row's reference from Shopping, then a 90-day-low mark and optional buy-under targets; first slice a previewed, home-admin reference action in shopping_queue.py. Needs Matt's decision on page overwrites. |
| `E6-S28` | OPEN | could | S | Record this order from a basket or plan shop: opens the existing Record an order sheet prefilled with seller, cards, snapshot printings and fulfils ticks; first slice client only, a seed for shopOrderSheet and a Baskets and plan button. Needs Matt's decision. |
| `E7-S34` | OPEN | could | M | Mana value ranges (mv<=2) and one shared o:/t: term parser for the editor's finder and the Collection page's search; first slice: new lib/api/card_terms.py moved out of editor.py, used by collection.py, hint and message text only in collection.js. |
| `E7-S35` | OPEN | could | M | Scan cards: Keep for the next cards (condition, language, finish) and a Check these list so an unsure scan isn't lost at the next photo; first slice: session defaults and an unsure list in web/collection-scan.js, no server change. |
| `E7-S36` | OPEN | could | M | A Spares list on the Collection page: copies no built deck holds and no building or idea deck still wants, with a reason and a price-free Copy list; first slice: availability=spare in lib/api/collection.py and a Spare choice in web/collection.js. |
| `E7-S37` | OPEN | could | L | Loans of loose cards: lend and return as audited changes, lent copies not free in the pool and tables ("1 lent out"); needs Matt's say that the household lends; first slice: card_loan migration, new lib/inventory/ops_loans.py, collection lend/return/loans, pool.py. |
| `E7-S40` | OPEN | could | M | Secret Lair drops in Add a precon as cards only, no deck, with their bonus card. After E7-S39; first slice: offer precons.PRODUCT_TYPES in Add a precon and a no-deck branch in plan_add. |
| `E5-S36` | OPEN | could | S | Warn (never refuse) when queuing or ordering a printing that's the bonus card of a pending product. First slice: one helper over pending products' extras rows (rules.extras_row) in the order and watchlist previews, and a line in pool.py's guard. |
| `E7-S38` | OPEN | could | L | Merged copies of one printing keep a counted note ("Copies: 2 NM, 1 LP", "1 signed") instead of a general one; sub-rows need Matt's decision; first slice: rules.merge_rows and collection_import.py, the Misprint/Altered/Signed columns, collection-bulk.js. |

## Deck Lab: Commander nights

**Owner:** [design/stories.md](decklab/design/stories.md#e9-commander-nights), E9.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E9-S11` | DEFERRED | could | L+pc | Four-player pod runs from the page (with `E9-S21` win shares and `E9-S22` why-not by Start); after `FG#2`. First `lib/forge/pods.py` from the prototype, fixtures only. |
| `E9-S31` | OPEN | could | M | A To fit Bracket N list of the fewest cuts when a Commander deck's minimum bracket is above its target, with E3-S25's free replacements and Test this swap; first slice: a pure bracket_fixes in lib/stats/commander.py and the list in stats.js and commander-readiness.js. |
| `E9-S32` | OPEN | could | M | Goldfish for Commander: commander cast by turn N, the skipped mana source classes one at a time, and a category milestone rate; first slice: record the cast turn in lib/goldfish/engine.py, report it from results.py with a new cache version, a panel in practice.js. |
| `E9-S33` | OPEN | could | M | Three-card combos a Commander deck fully holds, under their own heading and never raising the bracket (no early flag, per the 2026-10-21 decision); first slice: lib/combos.py reduces three pieces into a separate file, three_card_combos in lib/stats/commander.py, the heading on the pages. |

## Deck Lab: testing and Forge

**Owner:** [design/stories.md](decklab/design/stories.md), E3 and E11; Forge's own work in [PLAN.md](decklab/PLAN.md) (Still to do, items 2 and 3) and [forge-trial/ai-round1-handoff.md](decklab/forge-trial/ai-round1-handoff.md).

| id | status | pri | size | item |
|---|---|---|---|---|
| `E3-S23` | OPEN | could | M | Membership view, exclusion counts, policy persistence, its use in home's field selection, the home-admin preview/save with Change the field, and failing closed when saved choices can't be read built (0017 applied by 2026-10-30). Next: browser use of a saved field choice in a real run. |
| `FG#4` | DECISION | should | M+pc | The gauntlet on the Linux spare PC: build both catalogues, measure parallel Commander throughput (dev PC: about 40 games a minute, 4 opponents), a first standard run per Commander deck; with Matt's OK. |
| `E11-S28` | DECISION | should | M | Run the user-testing session with User2 from the prepared [checklist](decklab/design/user-testing-user2.md) (confirm his device first), then the follow-up review and stories. |
| `FG#2` | WAITING | should | L+pc | Forge 2.0.16 (about mid-November 2026): rebase the fork, build, check the overrides, replay every matchup. The post-build checks are one command, built 2026-10-21: `python -m decklab.lib.forge upgrade-check` (`--plan forge-2.0.16` prints the rebase and build steps; `E11-S15`), and `upgrade-check --dir <scratch folder>` checks the scratch build before it's installed (`E11-S45`). |
| `FG#3` | DEFERRED | could | M+pc | More experiment games (AI profiles, team-pump fix, override sets), decided with `FG#2`'s replay; the clean `fiery` test ran 2026-10-21 (C4 does what `fiery` does). |
| `E3-S41` | OPEN | could | M | Practice games name the spells the mana fails and try same-seed one-land swaps. First the per-spell castability counters in `lib/goldfish/engine.py` and `results.py`, drawn in `web/practice.js`; the what-if runs follow. |
| `E3-S42` | OPEN | could | M | Free cards by role for 60-card decks, and a comparable-decks range beside Commander role targets (needs Matt's decision on using the gauntlet catalogue). First the casual branch in `lib/decks/role_pool.py` and `lib/api/role_cards.py`, shown in `web/stats.js`. |
| `E3-S43` | DECISION | could | S | Left: `gauntlet export FILE` / `gauntlet import FILE` (catalogues and saved samples with a verified sha, playable decks screened again, no house deck's results). Waits for Matt's decision on `FG#4`: copy the development PC's catalogue to the server, or build its own there. |
| `E3-S44` | OPEN | could | M | Read one saved Forge game turn by turn, replayed from its seed. First the command line only: `forge game A B --game N` or `--pick loss/longest/timeout`, with a new `lib/forge/transcript.py` and the one-game replay shared with `cli_soak.py`; the page sheet later. |
| `E3-S45` | OPEN | could | M | Per-round development (lands in play, cards drawn) from Forge games on the Testing tab, plus a command-line placebo arm for variant tests; first slice: an optional development tally in lib/forge/cardlog.py pooled like token peaks. |
| `E3-S46` | OPEN | could | M | Honest simulation figures: a caution when stalled games (time limits, draws, errors) pass a stated share, floors on gauntlet group rows and token-peak suggestions, the gauntlet's excluded decks; first slice: a stalled share in lib/forge/views.py and one matchup caution line. |
| `E3-S47` | OPEN | could | M | Remember a field, gauntlet or variant run cut short by a restart and offer its starter Play the rest (never automatic); first slice: python -m decklab.update refuses to restart while runs are playing or queued unless --force. |
| `E3-S48` | OPEN | could | L | Size-changing variant tests (one more land, a cut with no replacement) as an explicitly unpaired comparison saved apart from paired results; needs Matt's decision; first slice: command-line only run_unpaired in lib/forge/variants.py and unpaired_diff in seqstats.py. |

## Deck Lab: running it

**Owner:** [design/stories.md](decklab/design/stories.md), E11.

| id | status | pri | size | item |
|---|---|---|---|---|
| `E11-S30` | DECISION | should | L | [UI implementation and Chromium review](decklab/design/visual-polish-completion-2026-11-07.md) complete; household Safari/touch, software keyboards, screen reader and real-art acceptance remain. |
| `E11-S31` | DECISION | could | M | Global search in the top bar ([stories.md](decklab/design/stories.md#e11-s31)) is built and its `/` decided (2026-10-31): Matt checks the iPad field and phone sheet on devices. |
| `E11-S58` | DECISION | should | L | Live server on Linux ([stories.md](decklab/design/stories.md#e11-s58)) is built and fixture-tested (2026-11-01): WSL qualified the database, backups, the services, `systemd-inhibit` under polkit and real Forge games (2026-11-02); still to qualify on the real Linux PC: suspend and wake, phones, and Tesseract on real card photos. |
| `E11-S08` | OPEN | could | L | Row, batch and mixed inverses built, including token edits that reorder rows (2026-11-06). Left: queue changes with orders, token additions/removals that renumber rows, other accessory inverses. |
| `E11-S49` | DECISION | could | M | Release zips, installs without git and Settings' newer-release line (2026-11-05) are built; left: Matt publishes the first release. The update command is `E11-S51`. |
| `E11-S50` | DEFERRED | could | L | One Windows installer (winget Python and PostgreSQL, release zip, generated postgres password, config questions, services, one firewall prompt, phone address); after `E11-S49`. |
| `E11-S51` | DEFERRED | could | M | Update command for release installs (backup, replace, migrate, restart); after `E11-S49`. |
| `E11-S52` | DEFERRED | could | L | First-run setup page on the PC (home profiles, optional Enable simulations); after `E11-S50`. |
| `E11-S59` | DECISION | could | L | Wake-on-request built in code (2026-11-01): Matt sets up the NAS gate, the service token, the Worker's secrets and the PC's wake settings, then times a real wake. |
| `E11-S02` | DECISION | should | S | The "Deck Lab is off" Worker is deployed (`decklab/cloudflare/`): Matt checks a signed-in save, a photo upload, and the page with Deck Lab stopped. |
| `E11-S55` | DECISION | could | M | Accessibility audits and fixes of every page, both densities, done (2026-11-04); left: a check with a real screen reader (VoiceOver on the household's devices). |
| `E11-S61` | DECISION | could | S | Review done ([more-menus-review.md](decklab/design/more-menus-review.md), 2026-11-05): Matt decides the recommended moves (Build decks as a lab pill from 1000 px, a Game log link on the Overview, Build decks out of Collection's More). |
| `E11-S57` | DEFERRED | could | L | A Linux install route (a script or container); after `E11-S50` (Windows first, Matt, 2026-10-31) and `E11-S49`. |
| `E11-S62` | DECISION | should | S | Matt's decision on a history rewrite: a pickaxe over all commits for config.json's values (emails, domain, Access team, AUD tag) found none, so none looks needed. Covers only config.json's values; README's wrangler --config deploy steps weren't run against wrangler. |
| `E11-S63` | DECISION | could | S | Built and tested (headers, policies, HSTS on the tunnel; the home page may also read the wake gate's origin). Left: Matt's real-browser check (Safari, iPad, phone, card scanning) for "Refused to..." console lines, and that wake-on-request still opens the gate. |
| `E11-S64` | DECISION | could | S | Built and tested (in-memory copies, gzip, immutable for a current `?v=`). Left: Matt times a phone's and the iPad's load before and after on the live server; the gain is unmeasured on a device. |
| `E11-S65` | OPEN | could | M | Declared access class per route with a table-driven probe test and a SECURITY.md. First slice: an ACCESS entry per row in feature_routes.py, tests/test_route_access.py, stale security docstrings fixed. Matt decides on /img needing a viewer. |
| `E11-S68` | OPEN | could | M | Operator observability: rotate db.log, warn when a shop is unreadable for 3 nights, error references instead of raw page errors, an optional heartbeat ping. First slice: rotation in db/conn.py and shop health in dbstatus's warning. Matt decides on the ping (near E11-S54). |
| `E11-S69` | OPEN | should | M | Limit what leaves the server each night: an opt-in home-only scope for the pushed export repo, then optional public-key encryption of the NAS dump copies. First slice: per-table scope in db/export.py from database.export_remote_scope. Matt decides if access controls suffice. |
| `E11-S73` | OPEN | could | S | One definition each for the Beginner Box stem and the page's locale, with a guard test; the locale default needs Matt's decision. First slice: decks.BEGINNER_BOX in space_forge.py and goldfish/cli.py, LOCALE in core.js, test_no_household_literals.py. |
| `E11-S74` | OPEN | could | M | JavaScript safety nets: one closeAllSheets() in the router, a fixture test for calls to undefined globals, and a non-required Chrome smoke job in CI. First slice: extract closeAllSheets() in web/app.js with a test in test_web.py that every sheet closer is called. |
| `E11-S75` | OPEN | could | M | Wake gate hardening before its real setup: a connection timeout and cap, a non-root read-only container; later an optional script secret off Linux. First slice: wakegate.py timeout and bounded server with test_wakegate.py cases, and compose.yaml's settings. |
| `E11-S76` | OPEN | could | M | Database test coverage for every inventory operation, and file-era docstrings rewritten; typed order ids need Matt's decision. First slice: test_inventory_backend_coverage.py with a shrinking gap list, one files-only suite run on the database too, the docstring sweep. |
| `E11-S77` | OPEN | could | L | A per-viewer change signal so open pages notice a save from another device and the library cache is dropped centrally; needs Matt's decision on appetite. First slice: guarded GET /api/changes polled by runs-pill.js, noteRevisions() in core.js, a Reload line; no stream. |
| `E11-S84` | DECISION | should | S | Config backup safety, release cleanliness, release-update guidance and local simulation settings built. Left: Matt's stable-channel, changelog and updates-available decision. |
| `E11-S79` | OPEN | should | S | BOM and sanitized JSON line/column diagnostics built. Left: missing-file startup/status/chooser guidance and unknown-role/no-admin warnings; timezone default needs Matt's decision. |
| `E11-S78` | OPEN | should | M | Setup failures say their cause and next step: no answer at host:port vs can't sign in, the Windows postgres password reset, a PostgreSQL 16 check, Python version, port in use. First slice: split database_unavailable in preflight_local.py, widen troubleshooting. |
| `E11-S80` | OPEN | should | M | SELF-HOSTING.md for newcomers: Before you start, contents, a Windows quick start (PowerShell, PATH, doctor each step), --at-logon, restore, more troubleshooting; README.md's Linux line. First slice: the top boxes, step 1 and 9 fixes, README.md. Docs only. |
| `E11-S81` | OPEN | could | M | SELF-HOSTING.md step 10 as a numbered Cloudflare Tunnel and Access how-to with an example config.yml. First slice: the how-to, checked against homenet's tunnel start. Docs only. |
| `E11-S82` | OPEN | could | M | macOS: the smoke test's false nightly-backup PASS, then stop/restart/update, Homebrew's superuser, a launchd plist, Java discovery, or docs narrowed to terminal-only (Matt's decision). First slice: schedule status unsupported off Windows and Linux, smoke WARN. |
| `E11-S83` | OPEN | could | M | First use on the page: no raw "wife" or Played by for one player, hints for Status and Planned/Play-now, plain-text collection import, the start box on an empty Collection, Forge optional wording. First slice: Played by from the profiles, the two hints. |

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
