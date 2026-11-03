# Deck Lab gauntlet: design (E3-S28 to E3-S38)

## 1. What it is

A gauntlet is a fixed, public set of sparring decks from outside Deck Lab:
- **Commander:** EDHREC's average decks for its top 100 commanders (Bracket 2 `core` and Bracket 3 `upgraded`), plus Wizards precons from MTGJSON as a Bracket 2 anchor.
- **60-card:** Forge's bundled `quest/precons` (505 decks) and `quest/duels` (1,145 decks). The duels carry `Difficulty=` easy 238, medium 358, hard 378, very hard 171, across 486 distinct `Title=` values.

You play one house deck against a balanced sample of these decks and read the results by colour and by style. The gauntlet never joins the house field, the Rankings or the Bradley-Terry ratings.

## 2. Storage: gitignored files, no database

Recommendation: keep everything under the gitignored `decklab/data/` (`.gitignore:12`).
- `data/gauntlet/sources/edhrec/`: EDHREC's raw cached fetches (MTGJSON's lists stay in `precons.py`'s own cache).
- `data/gauntlet/catalogue-<commander|constructed>.json`: the normalised, tagged decks (schema below).
- `data/gauntlet/samples/<sample-id>.json`: saved sweep definitions.
- `data/forge/gauntlet/results/`: a **separate results folder**. Today's folder is `DATA_DIR/"results"` (`forge/common.py:26,53-54`).

Why files:
- Gauntlet decks are reproducible public data, like the EDHREC cache (`edhrec.py:67,108`) and Forge results. Forge results are already outside the backups, and Matt accepted that (`journeys.md:84`).
- No deck row means the gauntlet decks never reach `deck_line`, the pool, the owned-vs-needed tables, the audit trail or the privacy switches.
- Their ids are `gauntlet:edhrec/<slug>-core`, `gauntlet:edhrec/<slug>-upgraded`, `gauntlet:precon/<MTGJSON file>`, `gauntlet:forge/duels/<stem-slug>` and `gauntlet:forge/precons/<stem-slug>`. These never parse as deck ids, so the `simulation.json` additions in `_field` find no summary and are skipped with a note (`field.py:239-247`).
- The separate results folder keeps gauntlet games out of `_bt_data`. It reads only `saved._stored(results_dir)` (`field.py:929`), and Rankings calls it with the default folder (`rankings.py:117`).
- The same separation keeps gauntlet games out of per-card stats and AI limits (`ai.py:173`). That is intended for now.
- Runner state follows the folder (`runner.py:354,544`).
- Cost: a gauntlet deck identical to a house intact product gets its games played twice. That's acceptable.

**Catalogue entry schema** (`"format": 1`):

```
{id, title, kind, card_sha,
 source: {kind: edhrec|mtgjson|forge, url|file, fetched, rank, decks},
 tier ("core"|"upgraded"|"precon" for Commander;
       "precon"|"easy"|"medium"|"hard"|"very hard" for 60-card),
 bracket: {label, minimum, game_changers: [...]},
 identity: "WU", colours: "WU",
 style: {primary, tags: [...], themes: [...]},
 metrics: {...}, fixes: [...], problems: [...], playable: bool,
 cards: {"Commander": [[1, name]], "Main": [...]}}
```

## 3. Build and refresh: `python -m decklab.lib.forge gauntlet build`

Usage: `gauntlet build [--format commander|constructed|all] [--source edhrec,precons,forge] [--top 100] [--refresh] [--dry-run]`.
- It runs only from the command line on the PC. No page request ever fetches.
- It writes a new catalogue atomically, then prints counts by tier, colour and style, plus each excluded deck with the reason.
- `--format all` builds only the formats a chosen source serves; an explicit format none of them serves is refused. A build of some of a format's sources keeps the saved catalogue's decks of the others. A source that gives no deck at all (a failed fetch with no cached copy) saves nothing, keeping the old catalogue, and exits 1.

**EDHREC**
- Fetch order: `pages/commanders/year.json`, then each commander's page (for its themes), `average-decks/<slug>/core.json` and `.../upgraded.json`.
- Add one generic `get_json(path)` to `edhrec.py`. It reuses `_get`'s User-Agent, `MIN_GAP` of 1 s, timeout and size limit (`edhrec.py:68-79,139-168`) and the 403/404 handling as `NoPage`.
- Commander pages come through the existing `edhrec.fetch()` (`edhrec.py:331`), with its 7-day cache (`edhrec.py:72`) shared with the EDHREC ideas feature.
- Average decks are cached for 30 days. They change slowly, and a stable catalogue keeps result keys stable.
- A first build makes about 300 requests at 1 s apart, so about 5 minutes. A failed fetch keeps the old copy, as edhrec.py does.
- The parser is written against fixtures captured once by hand from the two shapes already checked (the deck, its commander and its cards). The shape isn't assumed beyond that.

**Name validation**
- Every name goes through `cards.resolve` (`cards.py:461`).
- An unresolvable name makes the deck `playable: false` with a problem. Decks are never partly kept.
- Forge `.dck` names are played exactly as Forge writes them; the resolved Scryfall names are used only for tagging.

**Fixing an average deck to exactly 100**, in order. Every change is recorded in `fixes`.
1. Commander(s) from the deck's commander field.
2. Drop cards outside the colour identity or not legal in Commander. Use the card index's `color_identity` and `commander_legality` (`card_index.py` `_card_entry`, around line 188-196).
3. Reduce duplicate non-basics to 1, unless the card allows more (`stats/commander.py:101`).
4. If there are more than 100 cards: remove basics down to a 33-land floor, then cut nonlands from the end of the list (the least-included cards).
5. If there are fewer than 100: add basics split by the colour pips of the nonland cards within the identity. A colourless identity gets Wastes.

**Brackets**
- The Game Changers list comes from Scryfall's bulk-data flag (`cards.game_changers()`, `cards.py:625`; the `game_changer` field around `card_index.py:196`). The repo has no separate list, and none is needed.
- `bracket.minimum = min_bracket(...)` (`stats/commander.py:85`), using that module's mass land denial, extra turns and two-card combo checks.
- A `core` deck or precon whose minimum is above 2 is re-tiered to its measured bracket, and the reason is kept.
- The build warns when the card data is older than Wizards' last announcement, using `stats/commander.py:57` and `official_lists.py`.

**AI-unplayable screening**
- Use `ai.ai_limits(sections, kind)` (`ai.py:147`) for `cannot_play` (AI:RemoveDeck:All, `forge/__init__.py:404`), `unknown` and `pilot.poor`.
- The deck is excluded (`playable: false`) when the commander is unplayable, when any card is unknown to Forge, or when more copies are unplayable than 5% of the list (3 of 60 cards, 5 of 100). Otherwise only a problem is recorded.
- When Forge's card scripts can't be read (`ai_limits`' `screened` is false), the deck is excluded as "not screened": nothing about it could be checked.

**MTGJSON precons**
- Use `precons.deck_list()` filtered to "Commander Deck" (`precons.py:64,207`), then `precons.deck()` and `precons.cards_of()` (`precons.py:249,292`).
- The newest 60 by release date go into the anchor tier.
- Forge's own `res/quest/commanderprecons` (179 files) is an offline fallback and a test fixture source.

**Forge .dck files**
- Parse them as `lists.entry_from_dck` does (`lists.py:176-203`): only `[Commander]` and `[Main]`, with `|SET` stripped. Also read `[metadata]` `Name`, `Title`, `Difficulty` and `Set`.
- Constructed decks need a main deck of at least 60 cards.
- Keep every difficulty version, tagged with its `Title` (`duel_title`). A sample takes one version per `Title`, the one nearest the requested tiers, so variants of the same deck aren't near-duplicates (built 2026-11-02; likewise one deck per commander, so a re-tiered core deck and the same commander's upgraded deck never both go in).

**Running entries**
- Add `lists.entry_from_cards(id, title, kind, listed, source)` alongside `entry()` (`lists.py:156`). It reuses `_list_text` and `_dck` (`lists.py:41,57`).
- Every entry uses `pilots.default_pilot()` (`pilots.py:226`), as file entries already do (`lists.py:202`).

## 4. Tagging

- **Identity and colours:** from the card index. Identity is the union of the commander's (Commander) or the cards' (60-card). Colours count only nonland mana costs.
- **Metrics** (nonland unless stated), from the card index's `type_line`, `cmc`, `oracle_text` and `keywords`, and `cards.roles` (`cards.py:620`) over `ROLE_TAGS` (`card_index.py:63-71`):
  - creature share
  - mean mana value, and the share at mana value 2 or less
  - interaction: removal, counterspell and board wipe roles
  - ramp: the ramp role, lands excluded
  - instant and sorcery share
  - token makers: text that creates a token
  - the largest creature subtype's share
  - two-card combos, from the `stats/commander.py:212` check
- **Primary style:** the first rule that matches. Thresholds live in one table per format and are labelled approximate.
  - combo: a two-card combo, or 4 or more tutors
  - aggro: mean mana value ≤2.6 (60-card) / ≤3.0 (Commander), creatures ≥45%, low curve ≥50%
  - control: creatures ≤25% and interaction ≥25%
  - ramp: ramp ≥6 (60-card) / ≥10 (Commander) and mean mana value ≥3.5
  - midrange: everything else
- **Secondary tags:** `tribal:<type>` (largest subtype ≥35% of creatures, with at least 8 cards in Commander or 12 copies in 60-card), `tokens`, `spells` (instants and sorceries ≥40%), `lifegain`.
- **EDHREC themes:** `_themes()` already keeps each commander page's taglinks with deck counts (`edhrec.py:222-239`).
  - A theme held by ≥25% of the commander's decks becomes `style.themes`.
  - A small mapping turns known themes into tags: Tokens→tokens, Spellslinger→spells, Voltron, Aristocrats, tribal names→`tribal:`.
  - The heuristic decides the primary style. Themes add tags and show beside the deck, so a disagreement stays visible.

## 5. Choosing a sweep

`gauntlet sample [--format] [--size N] [--colours WUB] [--styles aggro,control] [--tier ...] [--seed S] [--json]`. The selection is deterministic:

1. **Filter:** `playable` decks only, then tier, colours (identity within the filter) and styles.
2. **Colour pass:** walk the buckets in a fixed order: W U B R G, the 10 pairs, the 5 shards, the 5 wedges, 4–5 colours, colourless. For each, pick the candidate that adds the most uncovered styles. Ties go to popularity (EDHREC rank or deck count; for Forge, difficulty, then precons), then `sha256(seed + id)`.
3. **Style pass:** bring every style to at least 2 decks where the candidates allow.
4. **Fill:** fill to N by popularity.

Defaults:
- Commander: N=20 from `core` and `upgraded` (since 2026-11-03; it was `core` only). With seed `''` this is the standard sample (section 11).
- 60-card: N=24 from medium and hard duels.
- The sample id is `sample:<12 hex>`, a sha of the catalogue version, filters, N and seed. It's saved, so the page and the command line play the same set.

## 6. Running

**Coordinator**
- Add one keyword to `run_field`: `opponent_entries=None`. When it's given, it replaces the field lookup at `field.py:852`, still minus the deck's own id (`field.py:317-320`).
- Everything else is reused unchanged: `_FieldRun`'s floor and APT plan, BUSY retry, Stop, ENGINE_CHANGED (`field.py:825-886`), the per-space note (`field.py:472-480`, under the gauntlet folder) and budgets.
- The default budget is `fixed:N` (`field.py:407-408`). There's no APT, because the goal is group averages, not a field rank.
- With no E3-S23 policy on this path, the fail-closed refusal (`field.py:342-350`) doesn't apply.

**New module `forge/gauntlet.py`:** `catalogue(fmt)`, `sample(...)`, `plan(entry, sample, budget)`, `run(entry, sample, budget, ...)` and `view(entry, sample, keep)`.
- `view` reuses `_rows` (`field.py:1010`), which reads saved results by key, so no field is involved, and `seqstats.field_average` (`seqstats.py:550`) for each group.
- There's no `_rating`, so no Bradley-Terry fit.
- **Groups:**
  - each colour (overlapping groups, labelled as such)
  - identity size (mono, two, three, four or five)
  - primary style
  - tier
- Each group shows its opponent count m, its games, the equal-weight rate with its MOVER range, and the min–max spread across opponents.
- A group with m<2 says "one opponent, not a group".
- The text says each range covers **these sampled opponents only**, not every blue deck.
- Per-opponent rows reuse `field_row` (`seqstats.py:537`), sorted by lower bound to show the hardest opponents.

**CLI:** `gauntlet build|list|show|sample|plan|play|view`.
- `play <deck-id> [--owned] [--sample ID | filters] [--budget fixed:N] [--inflight N]` and `view <deck-id> [--by colour|style|tier|opponent] [--json]`.
- Registered in `COMMANDS` (`forge/cli.py:34-55`). `list` and `show` join `_QUICK_COMMANDS` (`cli.py:77`).

**Web**
- A "Against popular decks" part on the deck page's Matchups tab, after `fieldSection` (`deck.js:221`), in a new `web/gauntlet.js` and `gauntlet.css` (script tag beside `index.html:90`). It follows `field.js`'s poll, Play and Stop pattern (`field.js:63-91,335-360`).
- Controls: sample size, colour and style filters and budget, the estimate, then **Play**.
- API:
  - `GET /api/gauntlet?id=&version=&sample=&profile=`
  - `GET /api/gauntlet/catalogue?format=`: public data, filters and counts
  - `POST /api/gauntlet/run`
  - `POST /api/gauntlet/stop`
- These are lazy routes in `feature_routes.py` (pattern at `feature_routes.py:14-29,60,110`).
- Run, like `run_field` (`field_page.py:242-290`): `guard.require_start` (`guard.py:329`), the optional `expected_card_sha` 409, the Forge-ready 503, and a `COORD_JOBS` job keyed `gauntlet:<space>:<card_sha>:<sample>`. Its `via` links to `#/deck?id=…&part=gauntlet`, which opens the Matchups tab (as `part=field` does) and scrolls to the part. A run of another sample of the same list while one waits or plays is refused (409), and Stop stops every run of the list.
- Stop uses the field's starter / own-space / admin rule (`field_page.py:292-315`).

**Fit with other work**
- **`variant --field`:** E3-S30 adds `against="gauntlet:<sample>"` to `variants._opponent_entries` (`variants.py:330`), with `FIELD_PAIRED_LOOKS` (`seqstats.py:71`) and the gauntlet results folder. It's not in the first slices.
- **E3-S19:** `opponent_entries` is exactly the chosen-group run E3-S19 lacks (`stories.md:924`). Its chosen house or public decks would run with the default results folder (they belong in the Bradley-Terry ratings) and reuse the group view.

## 7. Time estimates and defaults

| Run | Games | Dev PC (16 workers) | Live spare PC |
|---|---|---|---|
| 60-card, 24 opponents × `fixed:200` | 4,800 | about 5–6 min at 790–905 games/min | slower; untested |
| 60-card, `fixed:400` | 9,600 | about 11–12 min | slower; untested |
| Commander, 20 opponents × `fixed:100` | 2,000 | about 67 min single-threaded at 2 s/game; parallel not yet measured | slower; untested |

- At 100 games per opponent, each opponent's range is about ±10 points; a group of 5 is about ±4–5 points from game noise alone.
- `plan` prints `estimate.rates()` (`estimate.py:51`) once rates are saved, and says "not yet measured" until then.
- Recommended: Commander gauntlets on the dev PC by command line.
- The page defaults to the standard sample (section 11): 20 Commander or 24 60-card opponents × `fixed:100`, under the worker limit (`simulations.py:79`). It offers larger runs too, up to All for Commander, and says when a run is an overnight one.
- Slice C includes a one-off qualification run that measures parallel Commander throughput. It isn't a CI test.

## 8. Privacy and permissions

- Gauntlet decks and the catalogue are public data. Any signed-in viewer may read them, and the answers credit and link EDHREC, as `edhrec.py:46-47` does.
- Gauntlet results are about the house deck, so `/api/gauntlet` first runs the deck-visibility 404 (`_deck_sections`; `field_page.py:17-22`). Results are served only when the house side's `card_sha` matches the visible list.
- Jobs and notes are space-scoped. Starters from other spaces show as "someone" (`field_page.py:21`).
- Results belong to lists (`simulation_visibility.py:3-7`), and the gauntlet view never names another house deck, so nothing leaks between spaces.
- Building the catalogue is command-line only. Starting a run follows the simulations setting (`permissions.py:145`). Nothing is audited, because nothing in the database changes.
- When Claude relays results about a member's deck, the AGENTS.md limits still apply.

## 9. Documentation and stories

- **AGENTS.md:**
  - Layout lines: `lib/gauntlet/`, `data/gauntlet/`, `data/forge/gauntlet/`, and the `forge gauntlet` commands in the `lib/` comment.
  - A new "The gauntlet" subsection under Workflows: the sources, that it's never a deck or inventory, not in Rankings, built only by hand and politely, the Bracket 2 re-tiering, and that results are about the sampled opponents only.
  - In Accuracy rules: EDHREC average decks are sparring partners, not Commander advice.
- **README:** a Forge "Gauntlet" section with build and refresh, time estimates and sample defaults.
- **personas.md:** the anti-persona's "no metagame data" line (`personas.md:~661`) becomes: "no tournament metagame data: its gauntlet uses EDHREC's popular commanders and Forge's bundled decks as sparring partners, never as metagame shares or legality."
- **journeys.md:** stage 3's row (`journeys.md:90`) and the "Where it stands" line (`journeys.md:84`).
- **stories.md:** the next free E3 ids are E3-S28 onwards; the highest today is E3-S27 (`stories.md:1042`). Add four stories, all missing:
  - E3-S28: catalogue and command-line play
  - E3-S29: the deck page part
  - E3-S30: variant test against a sample
  - E3-S31: E3-S19's chosen-group run reusing `opponent_entries`
  Update `stories.md:724` and the counts paragraph (`stories.md:51`).
- **TODO.md:** a row. **HISTORY.md:** an entry once built.

## 10. Slice plan

Before the slices start, one commit adds `decklab/design/gauntlet.md` with sections 2 to 5's schema and the function signatures, so all slices build against the same contract.

| Slice | Files it owns (shared files in bold) | Tests (no network: fixtures plus a fake `urlopen` that fails if called) |
|---|---|---|
| **A. Sources and catalogue** | `lib/gauntlet/{__init__,edhrec_source,precon_source,forge_source,fixing,catalogue}.py`; **`lib/edhrec.py`** (`get_json` only) | `test_gauntlet_sources.py`: trimmed `year.json`, `core.json` and `upgraded.json`, an MTGJSON deck file and three `.dck` files under `tests/fixtures/gauntlet/`. `test_gauntlet_fixing.py`: over and under 100, duplicates, off-identity cards, colourless, Game Changer re-tiering, unknown names. AI screening against a fake script table. |
| **B. Tagging and sampling** | `lib/gauntlet/{tags,sample}.py` | `test_gauntlet_tags.py`: one fixture deck per style. `test_gauntlet_sample.py`: the same seed gives the same sample, every bucket is covered, filters work, and N is larger or smaller than the bucket count. |
| **C. Running and command line** | `forge/gauntlet.py`, `forge/cli_gauntlet.py`; **`forge/field.py`** (`opponent_entries`, about 6 lines; field.py is 1,123 lines, so it stays under the 1,200-line guard); **`forge/lists.py`** (`entry_from_cards`); **`forge/cli.py`** (registration) | `test_gauntlet_run.py`: a fake runner like the field tests use, the separate results folder, `_bt_data` and Rankings unchanged, group averages, Stop. `test_field.py` extended: `opponent_entries=None` behaves as before. |
| **D. Web** | `api/gauntlet_page.py`; **`lib/feature_routes.py`**; **`api/guard.py`** (docstring table, `guard.py:114-121`); `web/gauntlet.js`, `web/gauntlet.css`; **`web/deck.js`** (one line, :221); **`web/index.html`** (one tag) | `test_gauntlet_api.py`: 404 before 403, `require_start` modes, own-space stop, no other house deck named. A UI test in the `test_editor_retest_ui.py` style. `test_web_no_personal_data.py` still passes. |
| **E. Docs** | **AGENTS.md**, `decklab/README.md`, `design/{stories,personas,journeys}.md`, `TODO.md` | The source-length guard and ruff only. |

- A and B can be built in parallel; B's fixtures hand-write catalogue entries.
- C uses stub catalogue and sample functions until A and B merge.
- D builds against the contract's function signatures using a fake `forge.gauntlet` module.
- E lands last so the stories match what was built.
- No two slices own the same file.

## 11. The standard sample, the headline and where it shows (E3-S33 to E3-S38)

Matt decided on 2026-11-03 that Against popular decks is Deck Lab's lead feature. A deck's result is only comparable with another's, or with its own before an edit, when both faced the same opponents, so every deck of a format is scored against one **standard sample**.

**The standard sample** (`sample.STANDARD`, `sample.standard_sample`, `forge/gauntlet.standard`; E3-S33):
- Commander: 20 opponents from `core` and `upgraded`, seed `''` (Matt, 2026-11-03: not the page's earlier 12 `core`). 60-card: 24 `medium` and `hard` duels, seed `''`, as before.
- It's the format's default draw on the page, in the API and on the command line (`gauntlet play <deck-id> --standard`, which refuses `--sample`, `--size`, the filters and `--seed` beside it). The draw is deterministic for one catalogue, and `test_gauntlet_sample.py` pins its decks.
- Other samples still play and their results still show when chosen (the page keeps a saved one, one that has been played, in the address as `&gsample=<id>`, with **Back to the standard sample**; a sample only drawn from the choices isn't saved, so it isn't kept). The headline and the summary use only the standard sample.
- A new catalogue (a rebuild after EDHREC's lists move) may draw a different standard sample; its id names the catalogue version.

**The headline** (`forge/gauntlet.view`): `overall`, the equal-weight average over every opponent of the sample with its range and spread (the groups' `seqstats.field_average`); `played` of `of` opponents; `tally`, the opponents ahead, even, behind and not settled, from each opponent's `verdict`; and `updated`, the newest result's date. It's a summary of these sampled opponents, never a rating, and never joins Rankings.

**The summary** (`GET /api/gauntlet/summary?id=&version=&profile=`): the headline of the standard sample from saved games only, with up to three hardest opponents and the state (`no_catalogue`, `untested`, `partial`, `done`) and whether a run is playing. It never plans, estimates, saves a sample, plays or polls, so the Overview can read it on every visit. The deck-visibility 404 comes first; it names no house deck, file path or starter, and only an admin gets the build command (as from `GET /api/gauntlet` and `/api/gauntlet/catalogue`).

**Where it shows:**
- Built (E3-S33): first among a Commander deck's Overview strength panels (after Forge field for a 60-card deck), and first on a Commander deck's Matchups tab, its headline above the groups and the results before the play box.
- Next (E3-S34): the old figure kept, muted, as out of date when the list, Forge or the catalogue changes, and before/after on the same opponents after a re-test. Wanted before `FG#2` (mid-November), which re-keys every result.
- Then (E3-S35): Matchups renamed **Testing** and moved next to Decks (Decks, Testing, Collection, Shopping; Matt, 2026-11-03), the route staying `#/matchups`, with a **Popular decks** board beside Matchups and Rankings: one row per deck the viewer may see, each with its own Play of the standard sample, no Play all.
- Later: the library's Forge slots and a strength sort (E3-S36), an editor choice to re-test after saving (E3-S37), and Test this change against the standard sample (E3-S30).

**Larger runs** (E3-S38; Matt, 2026-11-03): Commander offers 6, 12, 20, 40 or **All**, every playable deck of the chosen tiers, colours and styles with both of a commander's decks included (about 201 in the dev PC's catalogue: 59 core, 110 upgraded, 32 precon); 60-card offers 12, 24, 36, 72 or 144 (no All: about 1,280 decks). Games an opponent stay 50, 100 or 200. The API takes 1 to 300 (`MAX_SIZE`) or `all`. An All sample hashes `every` into its id, so it never shares an id with a normal sample. The page shows the run's opponents, new games and time above Play, and over 2 hours (`OVERNIGHT_MINUTES`) says it's an overnight run and that Deck Lab keeps the PC awake while it plays: gauntlet runs are coordinator jobs, which the keep-awake provider (`server_run._forge_runs_busy`) counts as busy. Drawing and estimating All costs what a normal sample does.

**Open:** whether the nightly task should top up stale or untested built Commander decks on the standard sample (a recommendation, not decided): only once the live server has a catalogue and a measured throughput (TODO.md, `FG#4`), at most a deck or two a night, skipped when simulations are paused.
