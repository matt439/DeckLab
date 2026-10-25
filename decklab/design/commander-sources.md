# Sources for combo detection and official list changes

- **Researched:** 2026-10-21, live (each finding fetched, then re-checked by a second pass).
- **For:** [E9-S23](stories.md) (two-card combos) and [E9-S24](stories.md) (when the official Brackets or Game Changers list changes).
- **Status:** built 2026-10-21, after Matt accepted every recommended answer below ([HISTORY.md](../HISTORY.md#two-card-combos-and-wizards-latest-commander-announcement-2026-10-21-e9-s23-e9-s24)).

## E9-S23: two-card combos

### Source: Commander Spellbook's bulk export

`https://json.commanderspellbook.com/variants.json.gz`:
- **Size:** 30.7 MB gzipped, 694 MB unpacked.
- **Freshness:** rebuilt every 2 hours. The backend's docs say to use this file, not the HTTP API, for the whole dataset.
- **Date:** a top-level `timestamp` (2026-10-21T01:15Z when fetched) and `version` (7.3.0). The `timestamp` is the list's date to show.
- **Contents:** 115,642 combos, each with:
  - `uses[]`: the card pieces, each with `card.oracleId`, the `Front // Back` name, `quantity`, `zoneLocations` and `mustBeCommander`.
  - `requires[]`: template pieces, such as "a permanent castable with {C}".
  - `produces[]`: results, each with a feature name and status. Standalone results need nothing more; Helper results need a payoff.
  - `legalities`, `bracketTag`, `popularity` and `notablePrerequisites`.
- **Two-card combos:** 3,927 are Commander-legal with two `uses` and no `requires`. The live API's `cards=2 templates=0 legal:commander` count agrees. Of these:
  - 2,736 have a Standalone result, and 1,191 only a Helper one (such as Gravecrawler + Phyrexian Altar);
  - 137 need a piece to be the commander;
  - by result: about 2,850 are infinite, and the rest are locks (307), wins or losses, draws (97), mass land denial (71) or near-infinite;
  - 7 more are one named card plus one template piece. They're effectively two-card combos but fall outside the filter.
- **Terms:** the code is MIT. The data has no stated licence. The API guidelines ask for credit and a link back, and the site is fan content under Wizards' Fan Content Policy. Personal home use with credit fits.
- **Privacy:** Spellbook also has `/find-my-combos` and `/estimate-bracket`, which take a decklist. Don't use them: decks are private to their space (AGENTS.md), and Spellbook's privacy policy says nothing about what happens to submitted lists. Downloading the public list and matching locally sends nothing.

### Rejected sources

- **EDHREC's "Early/Late Game 2-Card Combos":** the top 100 of each only, with no date or terms, and built on Spellbook's data. Each entry does carry a community bracket vote (`comboVote.bracket`, `voteCount`, `controversial`). That could be a dated hint for the Bracket 3 early/late question, but its coverage and terms are unconfirmed.
- **Scryfall:** has no combo data. Its `all_parts` `combo_piece` marks related objects, not combos.

### How Deck Lab would use it

1. **Fetch:** `python -m decklab.lib.cards update` downloads the gz as a separate step:
   - it isn't one of `BULK_TYPES`, so a failure never blocks the card index;
   - it sends the Deck Lab User-Agent with If-None-Match and If-Modified-Since (the file has an ETag and a Last-Modified date);
   - it uses the same 7-day age as the Scryfall files;
   - after a failed download the old file stays.
2. **Reduce:** a stdlib-only `decklab/lib/combos.py` reduces the file once to `decklab/data/combos/two_card.json`, about 0.9 MB.
   - Each combo keeps its oracle ids, names, the must-be-commander flag, its result class, Standalone or Helper, `bracketTag` and its Spellbook link.
   - The list keeps its `timestamp` and `version`.
   - Loading the whole file took 2.6 s and about 2.1 GB of memory at its peak, which is fine on this PC.
3. **Match:** in `stats/commander.py`, look up the oracle ids of the Commander, Companion and Deck sections (not the Sideboard).
   - A combo matches when both of its pieces are there.
   - A must-be-commander piece counts only in the Commander section.
   - The answer is `{checked, list_date, version, combos[]}`, or `{checked: false}` when the file can't be read.
4. **Show:** add a "Two-card combos" group to What opponents will face:
   - each combo is named and linked to Spellbook;
   - when none match: "none found in Commander Spellbook's two-card combos (list of <date>)";
   - when the file can't be read: "not checked";
   - the list's date goes in the data note, and Spellbook gets a sources entry with credit;
   - the "combos aren't checked" sentence changes to say that combos of three or more cards and intent still aren't checked.
5. **The bracket rule:** Wizards' wording is "no intentional two-card infinite combos" for Brackets 1 and 2, and only "early-game" ones are barred in Bracket 3. The October 2025 update adds "no game-ending combos at the lower brackets".
   - So only Standalone infinite and win/lose results should raise the "at least Bracket 3" floor.
   - Mass land denial combos fall under the mass land denial rule.
   - Locks, draws, near-infinites and Helper-only combos are listed in softer words and raise nothing.
   - The words are always "holds both pieces of …", never a claimed breach, since intent isn't checked.
6. **Tests:**
   - a small fixture export: two-card, template, three-card and commander-only combos;
   - a commander piece in the 99 and in the Commander section;
   - a combo whose piece is only in the Sideboard;
   - an unreadable file.

### Matt's calls

1. **Which matches raise "at least Bracket 3" for a Bracket 2 deck?**
   - Recommended: only Standalone infinite or game-ending combos.
   - Alternatively, every match, or none (list them only).
2. **Are Helper-only combos shown?**
   - Recommended: yes, with a "needs a payoff" note.
3. **Is a hint for Bracket 3's early-game line shown?** It would be Spellbook's `bracketTag` or EDHREC's vote, labelled and dated.
   - Recommended: leave it out at first.
4. **Never send decklists to Spellbook, home's included?**
   - Recommended: yes, never.

## E9-S24: when the official lists change

### What's true today

- **Latest official change:** the latest change to the Brackets or the Game Changers was the Commander Brackets Beta Update of 2026-02-09, which added Farewell and Biorhythm.
- **Since then:** the five Banned and Restricted posts of 2026 (03-23, 05-18, 06-29, 08-10 and 10-12) made no paper Commander change; 10-12's changed only Arena's Competitive Brawl. The next post is due 2026-11-30.
- **Game Changers:** Wizards' format page lists 53. That's the same set as Scryfall's `is:gamechanger` search, which is what Deck Lab's card data uses.
- **Deck Lab's constants:** they say `brackets-2026-02`.
- **So:** everything agrees, and no warning should show today.

### Sources and how far each can be trusted

- **Wizards' sitemap**, `https://magic.wizards.com/en/sitemap.xml`:
  - 662 KB, 96 KB gzipped, with an ETag; `robots.txt` advertises it and has no Disallow.
  - Every announcement is listed, with its publish date in the URL.
  - Its `lastmod` is the last edit, not the publish date.
  - The URLs are named inconsistently: `commander-brackets-beta-update-february-9-2026`, `commander-bans-and-restrictions-april-22-2025`, `commander-banned-and-restricted-announcement-september-23-2024`, and `introducing-commander-brackets-beta` with no date.
  - So the match must be broad: "commander" plus "bracket", "banned", "bans" or "format-panel", ending in a date.
  - A post can announce no change at all, such as the 2025-12-11 Format Panel post. A new post therefore means "announced, may have changed", never "changed".
- **Wizards' Commander format page**, `https://magic.wizards.com/en/formats/commander`:
  - Its server-rendered payload holds the full Game Changers list and the bracket texts, with the edit time of each entry.
  - It's an internal page structure, not an API.
  - Wizards' Terms of Use (§2.2, read through a summary) forbid scraping and scripts without authorization.
  - Use it only if Matt accepts that. It would add a cross-check of Wizards' names against Scryfall's flags.
- **Scryfall's `game_changer` flags:** already local, and the basis of Deck Lab's count. After the 2026-02-09 announcement they were updated within 9 days, which is one observation (from Internet Archive snapshots).
  - Comparing them with the previous card data shows only that the local data changed, not that the official list did.
  - So they can't answer this story alone.
- **MTGJSON:** has `isGameChanger`, but no date for when a flag changes.
- **Feeds:** Wizards has no RSS or Atom feed.

### How Deck Lab would use it

1. **Check once a day:** Deck Lab's server already makes a daily check. The new check runs then, and in `cards update`.
   - It makes a conditional, gzipped GET of the sitemap.
   - A new stdlib-only `decklab/lib/official_lists.py` stores the newest matching Commander announcement (date and URL) and the check's time in `decklab/data/scryfall/official_lists.json`.
   - A failure keeps the last good check.
2. **Compare it with two things:**
   - **Game Changers:** the card data's date. Warn while the card data is older than the announcement: "Wizards announced a Commander change on <date>, after this card data (<date>); update the card data".
   - **The bracket rules:** the date of Deck Lab's hand-written bracket rules (`constants.BRACKETS`'s newest source, 2026-02-09). Warn while the rules are older than the announcement: "Deck Lab's bracket rules are older than the <date> announcement". That one is fixed in code, not by updating the card data.
3. **When it's unknown:** with no good check in the last 7 days, the page says "the date of the latest official change is unknown (last checked <date>)", never that the lists are current.
4. **Tests:**
   - a sitemap fixture with each URL style above and a generic `banned-and-restricted-*` post;
   - the warning shown while the card data is fresh;
   - unknown after a failed check.

### Matt's calls

1. **Is a daily check of Wizards' sitemap acceptable?**
   - Recommended: yes. It's 96 KB, and conditional.
2. **Is parsing the Commander format page's payload acceptable, given Wizards' terms?**
   - Recommended: no. Use the sitemap and Scryfall only.
3. **Should a new announcement warn until the card data and rules are newer, even when it changed nothing?**
   - Recommended: yes. Claude or Matt then marks the bracket rules as reviewed by updating `constants.BRACKETS`' source date.
