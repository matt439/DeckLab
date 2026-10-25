# Deck Lab: history

What each milestone and feature built, the decisions made along the way, and the known low issues left open. These are dated records: the code and [README.md](README.md) say how things work now, and [PLAN.md](PLAN.md) says what's still to do.

## P1 Matchups views and Rankings figures (2026-10-25; E11-S30 slice 10, first part)

Matchups now shows one selected deck's saved opponents: a real six-column table with mouse input from 1000 px, cards at casual widths, and whole-row links for coarse input in the lab. One shared entry model preserves the best saved pair, exact perspective and destinations, old-list/engine wording, meaningless-result flags and the permission gate for unplayed matches. Uninformative figures fade and retain their words. The old matrix is removed.

A neutral lock chip beside the title shows only the current known simulations mode and updates when settings load. It adds no setting control or identity disclosure. Rankings retain connected-group boundaries, exclusions, uncertainty and refresh behavior, now with the shared win-rate figure and mono numerals. Casual ranking rows stack so the percent sign stays beside its number.

Validation: 164 targeted UI/source tests; synthetic Chromium checks for Matchups and Rankings at all nine documented viewport sizes in light and dark (36 combinations), with no page overflow or figures outside their rows. The browser uses mouse input/default DPR; coarse input, Safari and physical devices remain unverified. No live records or simulations were used. Source-length audit still flags only the pre-existing 1,516-line `tokens.js`; changed sources are below 1,200.

Slice 10 remains partial: the selected list's field average, first-player edge/residual flags and latest swap need their own server answers with exact list context. Pair win rates are not averaged into a field rating or used to invent flags.

## P1 deck navigation and Last changed (2026-10-25; E11-S30 slice 9)

The deck header now has previous/next links through a fresh server-visible library, retaining its filters/sort where the current deck belongs and otherwise using all visible ordinary decks. It keeps the selected tab, Cards filter and Play-now list when the next deck has one, disables either end, and remembers the selected deck for returning to the library. Late reads check the route, screen, person, connection and retry sequence. Narrow lab widths place 44 px white circles over the art, with enough reserved space for maximum-length titles.

`GET /api/deck` now includes the same actual last-recorded edit date as the library, looked up after the visibility check without rereading decklists or history. The tint band shows Last changed as the device's local date, with a full date/time in the time element's title. Unknown dates stay unlabelled and a metadata read failure leaves the deck usable without exposing diagnostics.

Validation: 251 targeted Python/Node and fixture HTTP tests; Chromium synthetic-data checks at all nine documented viewport sizes plus the 1000/1280 boundaries in both themes, including maximum-length titles and an actual navigation preserving Stats. No overflow or control/title overlap remained. This browser uses mouse input and its default DPR; some phone widths round up one pixel. Real-device, true touch and Safari acceptance remain open. No live records or simulations were changed. The source audit still fails only on untouched `web/tokens.js` (1,516 lines at baseline); every changed source is below 1,200.

## P1 deck page, first part (2026-10-25; E11-S30 slice 9)

The deck page now has a lab art hero with its identity stripe and tint metadata, a folded toolbar at narrow lab widths, and saved Forge results on Overview. The existing five tabs, editing rights and More actions stay intact. Image failure falls back to a readable title; casual widths keep the compact head.

- `deck-overview.js` reads the displayed list's field once, with its figure, range, freshness, rank, flags and first-player edge, and its newest swap test. Field view and All tests lead to the existing Matchups controls. No simulations start, and there is no new polling. The mana curve has an identity gradient and a spoken count at each mana value.
- Late reads check the original route, person, screen and attachment. The summaries use no inventory. Member deck ids now reach their All tests list too.
- Validation: 214 targeted Python/Node/HTTP-fixture tests and the existing web scale/name contracts; screenshots and overflow checks at the nine documented viewport sizes in light and dark using invented data. The browser retains mouse input and default DPR (some phone widths round up one pixel); true touch/Safari and real-device acceptance remain. No live records or Forge games were used.
- The source-length audit still reports the pre-existing 1,516-line `web/tokens.js`; changed source files stay below the 1,200-line threshold. Deck-to-deck navigation and Last changed metadata remain in slice 9, so the story stays partial.

## Plan packed token cards (2026-10-25)

Matt asked for a tool that optimises the token cards across every built deck. The Tokens page's More now has **Plan packed token cards…**. It shows each built deck's Token cards line as it is and as planned, with the card each token gets, the faces used ("can be sleeved"), the spares it got and the tokens left short. **Apply** then saves them all as one change (`deck.token_cards`, all or none).

- **The plan** (`lib/tokens/optimise.py`): a minimum-cost maximum flow over every built deck's needs (`deck_tokens` with every row free) and the space's rows. As many tokens as possible get a card. Ties go first to the better match (exact or agrees, then check, then a stand-in that differs), then to the card the deck already packs, then to a single-sided card, which leaves double-sided cards for the decks that use both faces.
- **The spares** (Matt's choice: one each, then share spares): each row's leftover cards are dealt one at a time, in id order, round the decks given that row. A row nobody was given goes round the decks it would serve.
- **The API:** `GET /api/tokens/plan[?space=]` and `POST /api/tokens/plan {sha256}` (`lib/api/token_plan.py`). The apply works the plan out again and refuses (409) unless it matches the preview. It needs `deck.edit` on every deck it changes.
- **Not done:** intact products still pack no token cards. The plan can't be tuned per deck: change a count on the deck page afterwards (a later plan resets it). Not checked in a browser.
- **Tests:** `PlanTests` in `test_token_reservation`, plus a UI test in `test_feature_ui_tokens`.

## One side or both of a token card (2026-10-25)

Matt sleeves a double-sided token card when a deck needs only one of its faces, and leaves it bare when both are needed. The pages now say which (`tokens.js` `tokFacesUsed` and `tokSides`, worked out on the page from the deck's `deck_tokens` needs, so the server's answers are unchanged):

- **Deck page:** each packed card ("Packed: 2 Zombie // Zombie Knight (Zombie side only, can be sleeved)") and each card to grab ("Zombie side (both sides used)").
- **Packing plan:** the grab and stand-in ticks ("(Zombie side only, can be sleeved)", "(Zombie side; both sides used)").
- A face counts as used when the deck grabs the card for a token it makes, or uses it as the stand-in for one that differs. Rabbit / Rabbit is one face. Single-sided cards say nothing. Not checked in a browser.

## Token cards reserved by built decks (2026-10-25)

Built decks hold token cards now, as they hold playable cards. Until now one token row counted as owned for every deck that made that token.

- **The warning (PR #7):** a token row that built decks (and intact products) want more cards of than it has gets a warning. It shows on the Tokens page ("Too few for N built decks", in To check and the row's sheet), beside the card in a deck page's Tokens part, and in `tokens check`. Decks still being built don't count.
- **The Token cards line:** a built deck's `- **Token cards:** 2 Treasure (TFDN) 12; 1 Beast // Dog` header line (`lib/decks/tokencards.py`) names the cards in its box. `lib/tokens/reserve.py` shares each line out over the space's rows, deck by deck in id order. `deck_tokens(..., held)` leaves the other decks' cards out: a row fully packed elsewhere goes in the need's `in_use` ("All yours are packed in A Deck"), and a partly packed row offers what's left.
- **Where it's written:** Finish building fills the line for a deck without one, with one free card for each token the deck has. The deck page's Tokens part shows what's packed and offers **Change packed token cards…** (POST `/api/deck/token-cards`, one `deck.save`). Taking a deck apart (`assembled.clear`) removes it. `deck push` writes it as given.
- **Elsewhere:** the Tokens page's rows list the decks they're packed in (`packed`), and a deck that would use a row packed elsewhere shows it as "Packed in other decks". The warning counts each line's cards, and one card for each row a deck without a line uses. The Packing plan and the library's token lines see the reservations too.
- **Not done:** intact products don't reserve token cards yet, and Finish building can't choose counts (change them on the deck page afterwards). Not checked in a browser.
- **Tests:** `test_token_reservation`, plus additions to `test_tokens`, `test_api_tokens` and `test_collection_assembly`.

## P1 library (2026-10-25, E11-S30 slice 8)

The eighth slice of the P1 visual redesign: the library's casual tiles and the lab's list beside a detail pane ([design/visual-design.md](design/visual-design.md) 4.1, 4.2, 4.4, 4.6, 4.10 and section 5, Library), with the Forge line Matt chose: each casual deck's field average, worked out on the PC and cached.

- **Casual tiles (under 1000 px):** borderless with a 1 px ring and `--shadow-1`, `--r-panel`; the art 112 px wide (88 for the Beginner Box's small tiles) with 20 px pips over its bottom-left; the body on the deck's tint (135deg). A status pill only on Building and Idea tiles (Matt, 2026-10-25), so a Built tile has none. The owned bar (`ui.js` `ownedBar`, 4 px, `--accent` owned and a hatched part on the way) with "51 owned · 1 on the way · 8 to get"; the readiness chip only for what the bar can't say ("Play-now list ready"). Two across from 600 px, 320 px tiles from 1000 px.
- **The lab (1000 px and up):** the decks as 54 px rows in a list pane on `--surface`, under Built, Building and Ideas headings with mono counts (and no pills), beside the selected deck's detail pane (46 / 54, a 720 px list from 1,281 px; the pane sticky under the top bar). A row has a 56 × 38 thumbnail with a 3 px stripe, the title with 16 px pips, the meta line, the owned bar with mono words ("48 +4 · 8 to get") and the Forge field column. A click selects a row (the address keeps it as `deck=`, so "← Decks" comes back to it); Enter or a click with a modifier opens the deck; J and K move the selection and the focus (not while typing). The detail pane has the art, colours, status pill, who plays it, the owned bar, tokens, kit, the Forge summary and Edit deck (its one primary, for a deck the viewer may change) beside Open deck. Crossing 1000 px redraws the shelf.
- **The Forge line:** `GET /api/library/forge` (`api/library_forge.py`) gives each visible casual list's field average and when it was last tested, from `forge.field.averages` (the field view's own rows and average, without the rating, worked out once per field), cached per space until a saved result, a field run's note or a field list changes, or ten minutes pass. A tested tile shows "58% Forge field" and its freshness badge; a lab row its inline figure, a compact range bar (from 1,281 px) and the freshness, `—` when a casual deck has no field result and nothing for a Commander deck; the detail pane the hero figure, the range bar with its axis, how much of the field it has played and "Field view". The numbers come after the shelf is drawn; until then, or when the PC can't work them out, no Forge line shows (never `—`). They follow the deck-read rules: the viewer's space's field, only decks they see.
- **Also:** the library's More menu opens under its button; `forge.field.view` now builds on `_rows` and `_average`, which `averages` shares.
- **Differences from the plan:** see [visual-design.md](design/visual-design.md#7-rollout), slice 8: the numbers' separate request, "to get" for "to buy", no bar for a built Play-now list, the narrower columns up to 1,280 px, the detail's Forge summary without flags or the first-player edge (slice 9), and `--seg-track` and `--shadow-1` left as they were.
- **Checked** in Chromium (Playwright, the API stubbed) at the iPhone 15 Pro upright and on its side, the iPad Air both ways and the MacBook, in light and dark. Still to check on the real iPhone and iPad.
- **Tests:** `test_library_ui` (tiles' owned words and bars, the lab's rows, headings, selection, keys and detail pane, the Forge line on tiles, rows and the detail pane, another profile's numbers never shown, nothing when they can't be worked out); `test_library_forge` (`forge.field.averages` against the field view's averages and dates, a hidden deck left out of the field; the API's visibility, cache and failure; the route); `test_device_layout_ui` (pips over the art, 16 px row pips). The rest of the suite fails the same tests with and without this change on Linux (database, Forge and Windows-only tests).

## P1 shell (2026-10-25, E11-S30 slice 7)

The seventh slice of the P1 visual redesign: the shell's two chromes ([design/visual-design.md](design/visual-design.md) 3.1, 3.2, 4.8 and section 6 decisions 1, 3 and 5). Under 1000 px, the iPad in portrait included, Deck Lab has the phone's header and tab bar; from 1000 px (and on a phone on its side) the lab top bar. No page's own layout changes.

- **Casual (under 1000 px):** the 56 px header (the way back or the logo, the page's title once its heading has scrolled away, the run activity, the avatar) and the tab bar at the bottom, now Decks, Collection, Shopping, Matchups and More (`shell.js` `TAB_COUNT`; Matchups was in More). The iPad in portrait gets the tab bar instead of the top bar, its tabs in the middle 640 px. A page's own crumb is hidden there, as the header has the way back.
- **Lab (1000 px and up):** the nav is round pills, the page's section in `--accent-strong` on `--accent-soft` instead of an accent underline; hover only with a mouse. The run activity icon sits in both chromes as slice 6 left it.
- **One bar order:** the tab bar no longer hides for the editor's bar or Receive delivery's Record bar; they sit on it. Only the on-screen keyboard over the editor's search puts it away (`keyboard-up`), and the editor's bar sits on the higher of the tab bar and the keyboard. A page's bar is at least `--bar-h` (72 px casual, 60 in the lab), and a toast and the Undo toast sit above it at either density.
- **The Matchups tab's dot:** 8 px of `--accent` while a run plays or waits (`runs-pill.js` `drawRunsPill`); the header's icon has the words.
- **Differences from the plan:** no global search and so no `kbd` in the top bar (Matt, 2026-10-25: its own story, E11-S31); a phone on its side keeps the lab top bar and no tab bar; the header is 56 px, not 60, and the tab bar keeps its 56 px plus the safe area.
- **Checked** in Chromium (Playwright, the API stubbed) at the iPhone 15 Pro upright and on its side, the iPad Air both ways and the MacBook, in light and dark: the tab bar, a page's bar on it, the activity icon and the Matchups dot. Still to check on the real iPhone and iPad.
- **Tests:** `test_device_layout_ui` ShellTests; `test_shell_ui` (four tabs, the Matchups dot). The rest of the suite fails the same tests with and without this change on Linux (database, Forge and Windows-only tests).

## Download a collection (2026-10-25, E7-S30)

The Collection page's More has **Download collection (CSV)**, so a member (User5 first) can take their own cards to another app or keep a backup without the PC:

- **Server:** `GET /api/collection/download?space=` (`collection_edit.download_view`) answers `{space, filename, csv}`: the collection rendered by the inventory's own writer (`rules.collection_csv_bytes`: the eight columns, sorted by set and collector number, LF, no BOM; the header alone for an empty collection), named `<space>-collection-<YYYY-MM-DD>.csv`. It follows the rows' read rule (`guard.require_sees_inventory`), so another space, or one that doesn't exist, gets "That collection isn't public." with nothing else. It stays JSON, like every other answer, so the page's viewer header goes with it.
- **Page:** the item shows wherever the page itself loads (read only too, so a public collection's readers can save it once one is public); the file is saved through a Blob link as the deck page's Download decklist is. A refusal is said in the page's message.
- **Tests:** `test_collection_edit` DownloadTests (home's bytes and name, a member's own space and the 403s, and the file read back by Import cards as the collection's columns with no problems), `test_inventory_privacy` (an admin can't download another space), `test_accounts_ui` (the menu item, the request, the file's name and type, a refusal).

## P1 simulation components (2026-10-25, E11-S30 slice 6)

The sixth slice of the P1 visual redesign: the shared pieces Forge's results are drawn with ([design/visual-design.md](design/visual-design.md) 4.9, 2.3's mono rules and section 6 decision 3), and Matchups and the deck page's Forge parts using them in place of their own markup. Page layouts don't change; the floating "Forge playing" pill is gone.

- **The pieces** (`sim-ui.js`, loaded first of the matchup scripts; styled in `components.css`): `winRateFigure` (inline "61% 59–63", a tile with "Forge field", or a hero with its range and games under it; mono, in ink, never coloured; its words spelt out on a `role="img"`), `rangeBar` (a fixed 20–80% scale, `left = (value − 20) / 60`, a dashed 50% tick, the 95% band and a 3 px ink mark; 12 px casual, 10 in the lab, 6 compact; an optional 20 / 50 / 80 axis; a value outside clamps to the end and the spoken words give the real one; a live run's band dashed; `decorative` beside a figure, which then says it once, with `barred` adding the clamped value's words) with `rangeKey`, `freshnessBadge` (fresh up to 7 days, aging to 30, stale after or once the list has changed since, "for the saved list" for the editor later; the same badge for any dated check, "pulled 24 Oct", "checked 3 days ago", "check again"; only when there's a date or the list has changed since, the real date in its spoken words), `forgeFlag` (strong or weak against, chevron, name, mono win rate) and `swapResult` (the swap, the difference in points, a verdict pill, `.swap-verdict`, worked out from the range, the range and games).
- **The run activity** (`runs-pill.js`): the pill in `#shell-status` is now one 44 px button with a slowly turning teal ring ("Forge is playing: show progress"; "A Forge run is waiting: …" while only waiting; still, with a dot, under reduced motion), and nothing while nothing runs. It opens the details: a popover under it from 1000 px (Escape, a click elsewhere or a new page closes it, a click in Stop's question doesn't) or a sheet below. Each run playing has a `role="status"` line, a `role="progressbar"` ring, "game 37 of 200", about how long is left (the server's estimate, now in the running list as `eta_s`), "Open it" unless it's of a space the viewer can't see, and Stop named "Stop the Forge run" when the server's `may_stop` lets the viewer; then the runs waiting and "Every run on Matchups". Stop goes through the existing `stopListedRun` (asks first, by the run's key, rechecks rights, person and page after the answer); the details don't redraw while its question is open, and the popover leaves the Escape that closes that question alone. A redraw on each ask gives the focus back to the link or button that had it (or the first one, once it's gone). The simulations setting and its wording aren't touched.
- **Matchups:** each result row has a compact range bar and the inline figure instead of the diverging green and red bar and its percentage, and how long ago it was played as a row badge (plain words while fresh) instead of the date; on the Matchups list a changed list's row says "retest: changed since" in place of the "Older list" tag (a deck's own rows stay faded with their key line). The pair page's verdict has the first deck's hero figure, a freshness badge and the range bar with its axis in place of the big diverging bar and its "X wins more" ends; "Why we're confident" keys the range bar. A live run's range is a range bar with a dashed band. The matrix keeps its diverging cells (the only use of `--win` and `--loss` left).
- **The deck page's Forge parts:** the field's average is a hero figure with the games it counts, how long ago the field was last played (the last field run's note) and its range bar; its "does better or worse than expected" links lead with a strong or weak flag; each opponent's row has a compact range bar and the inline figure, and a flag beside a flagged opponent. The Tests of changes list shows each finished test as a swap-test result with how long ago it played (`/api/variants` now sends each test's range, `low` and `high`); the test page's change chips, difference bars and axis words take Forge's strong and weak colours (they had `--win`/`--loss` and `--good`/`--crit`).
- **Removed:** matchups.js `winBar`, `drawWinBar`, `winBarKey`, `dayWords` and `VALUE_LABEL_HALF`, field.js `fvRate`, and the pill's and the bars' CSS.
- **Also:** JetBrains Mono is preloaded beside Figtree, as Matchups' first view now has mono numbers. The figure columns in Matchups and field rows are at least 5.5em wide, so a list's bars line up.
- **Differences from the plan:** a swap's card names stay in the body font (only the quantities are mono: words are never mono, 2.3); the range axis is 11 px in the lab (14 casual), not 10.5, since nothing people read goes under 11 px; the verdict pill comes from the range, so "probably better, not proven" covers what the server calls not settled or slightly better without a clear range; the details are a centred dialog from 600 to 999 px, as every sheet is there.
- **Left for later slices:** the icon's place in the new top bar and casual header, and the Matchups tab's dot (slice 7); the tiles' and rows' Forge line (slice 8); the deck Overview's Forge panel and latest swap test (slice 9); the Matchups table and phone cards, the Rankings view's figures and the simulations chip (slice 10); dated prices as badges (slices 11 and 12); the editor's unsaved badge (slice 14).
- **Review fixes before commit** (a review workflow: reviewers by lens, each finding checked by a sceptic; 16 confirmed, all fixed): the verdict pill was `.verdict`, which the deck page's stats tiles already use (stats.css), so each took the other's styles (now `.swap-verdict`); the test page's difference bars and axis words still used `--win`/`--loss` and `--good`/`--crit`, where the docs said the matrix was the last use; Escape on Stop's question in the lab popover closed the popover under it and kept the question open, after which "Stop it" did nothing; each ask rebuilt the details and dropped a keyboard user's focus; a row link and the pair page and field headline read the win rate twice (figure and bar), so a bar beside a figure is now `decorative`; a result without a readable date lost its only "list changed since" sign (the badge now shows without a date); a fresh row badge lost its pill at casual density too (now only in the lab, from 1000 px); the tile's caption was 14 px, not 13 (`--fs-wr-caption`); in forced colours the turning ring looked still and the amber badge icon and a muted point kept their theme colours; the activity button had no touch `:active`; `/api/variants`' new `low` and `high`, and the details' sheet below 1000 px, had no tests; and README, PLAN.md, E3-S06 and a UI-KIT.md sentence still described the pill or read wrongly. One part was left: the per-run `role="status"` line stays, as the spec asks, since a live region inserted with its words already in it isn't announced again.
- **Tests:** `test_device_layout_ui` SimComponentTests (the pieces mono and in ink, flags and verdicts in Forge's colours, `--win`/`--loss` only in the matrix, `.verdict` left to the stats tiles, the badge's states and the lab-only plain fresh row, the caption's token, the run activity's CSS with its forced colours and `:active`, the pill gone) and SimComponentUiTests (`sim-ui.js` under Node: the figure's sizes and words, the range bar's positions and clamping and its decorative form, the badge's ages and dated-check words and a changed list without a date, flags, the swap test's verdicts and the Tests of changes item), with the new tokens in DensityTokenTests; `test_web_matchups` (the activity icon and its details, rows' and the field's figures); `test_forge_stop_ui` (Stop in the details' sheet and popover, the sheet below 1000 px, the popover's closing but not on Stop's question's Escape, the focus kept across a redraw, a refresh while Stop asks); `test_variant_api` (each test's `low` and `high`); `test_web_matchup_files`, `test_deck_page_ui`, `test_matchup_verdict`, `test_web_pages`, `test_web_variant`, `test_web` (the load order and preloads) and `test_matchups_api` (the running item's `eta_s`) updated. Checked in headless Chrome at 1470 px, a 393 px phone (DevTools device metrics) and 1180 × 820 in both themes, plus a page of every piece with mock numbers and the details open. Not checked on the real devices yet.

## P1 deck colours (2026-10-25, E11-S30 slice 5)

The fifth slice of the P1 visual redesign: one helper draws a deck's colour pieces from its colour identity ([design/visual-design.md](design/visual-design.md) 4.3 and 2.2), and the library and the deck page's head use it in place of their own pip and wash code. Page layouts don't change.

- **The helper:** `deckColourPieces(identity)` in `ui.js` takes the deck's colour identity (the server's `colors` in `/api/decks`, or `deck.js` `deckPageColours`: the commander's, else the Deck and Companion cards'; never typed) and returns its pieces: `pips(size, {overArt, cls})`, a `role="img"` group named "Colours: blue, red" (or "Colourless") at 16, 20, 22 or 24 px, WUBRG, with the white ring over a picture; `stripe(thin)` and `swatch()`, `aria-hidden` equal hard segments of `--stripe-*` (5 px, 3 px thin); `tint(angle)`, the background gradient (one colour's tint to its deeper stop, two tints, three at 0/55/100%, the neutral `--tint-multi` for four or five, translucent in dark over `--surface`); `art`, the picture placeholder; and `vars(angle)` for a style attribute. `[]` is a colourless deck (one C); `null` (no card could be read) draws nothing.
- **Components:** `.id-pips`/`.id-pip` (CSS circles in `--mana-*` with the letter in Figtree 800 and the `--mana-ring`; `.pip` was taken by `deck.js`'s lettered stand-in for cost symbols), `.deck-stripe`, `.deck-swatch` and `.deck-tint` in `components.css`, kept in forced colours.
- **Tokens:** the one-colour tints' deep stops `--tint-*-deep` (light; dark the dark stripe at 24%), `--art-multi`, `--pip-sm/md/lg/xl` with their letters `--fs-pip-*`, `--shadow-pip-art`, `--stripe-h`, `--stripe-h-thin`, `--swatch-w`, `--swatch-h` (12 px on a phone) and `--r-swatch`.
- **Library:** 20 px pips by the title (P1 pips instead of Scryfall's symbols), a 5 px stripe across the tile's top, the cover on the deck's art placeholder while its art loads and the deck's tint (135deg) when there's none or it fails, instead of the old two-colour `--mana-*` wash. A colourless deck now shows its C; a deck with no cards or an unreadable list shows no colours. `/api/decks`' `colors` (`library.py` `deck_colors`) is `null` when no card in the list could be read (unknown names, no card data yet, or working the cover out failed), and a commander that can't be read gives way to the Deck and Companion cards, as on the deck page.
- **Deck page head:** 22 px pips beside the title instead of the symbols. `deckPageColours` returns `null` when no card in the shown lists could be read.
- **Values the spec left open:** the deep stops other than white's (`#f8efd8`) take the same lightness step (U `#ddebf5`, B `#e9e5e3`, R `#f9e4e3`, G `#dcede4`, C `#e8e6e3`); three or more colours share a neutral placeholder (light `#e6e4de`, dark the drawings' `#26272c`); the swatch is 14 × 8 px (12 px tall on a phone) with 2 px corners; a 24 px pip's letter is 12 px.
- **Review fixes before commit** (a review workflow: reviewers by lens, each finding checked by a sceptic; 4 confirmed, all fixed, two of them the same defect): the library called a deck whose cards couldn't be read "Colourless" with a C, a grey stripe and the C tint, since the server sent `[]` for both, and disagreed with the deck page for a commander it couldn't read (the server now sends `null` and falls back to the Deck cards); the cover's fall-back to the tint when its art fails, and the library rules that lay the stripe over the tile and paint the placeholder, now have tests.
- **Left for later slices:** pips over the art, the tinted tile body and 16 px lab-row pips (slice 8); the deck hero's stripe and tint band with 20 px pips (slice 9); the swatch beside deck names on Collection, Shopping, Receive delivery and the Packing plan (slices 11 to 13); stats' colour-source pips stay cost symbols, since they're mana, not identity.
- **Tests:** `test_device_layout_ui` DeckColourTests (every colour's stripe, tint, deep stop and placeholder in both themes, the size tokens, the components, and the library and deck head using the helper with no `--mana-` wash or symbols) and DeckColourUiTests (the helper under Node: two, one, three, four and five colours, colourless and unknown); `test_library_ui` and `test_deck_page_ui` (the pips' names and sizes, the stripe, the cover's placeholder, its tint with no art or failed art, and no colours for a list the server couldn't read); `test_cover` (`deck_colors`: colourless, unreadable and an unreadable commander). Checked in headless Chrome at 1470 px, a 393 px phone and 1180 × 820 in both themes, plus a page of every colour count's pieces in both themes. Not checked on the real devices yet.

## P1 components (2026-10-24, E11-S30 slice 4)

The fourth slice of the P1 visual redesign and the first that changes every page: the shared components in `components.css`, `cards-ui.css` and (for fields) `base.css` take P1's look from [design/visual-design.md](design/visual-design.md) 4.4, 4.5, 4.7 and 4.8, reading slice 3's density tokens. Pages keep their layouts.

- **Decided:** section 6 question 2 (Matt, 2026-10-24): a line changed and not saved stays teal (`.stepper.is-changed` or `data-changed="true"`), "Part received" is a neutral outline pill (`status("outline", …)`, a half-filled circle), and the presence avatars keep their per-person colours.
- **Buttons:** round, 700, `--btn-h` tall. The secondary is a 1.5 px teal outline with `--accent-strong` words (white fill in light, none in dark); the primary a teal fill with `--shadow-primary`; `.btn-quiet` the teal tertiary; `.btn-danger` red words with no box (the red fill only for a confirm sheet's last step, its words `--on-crit`); a new `.btn-discard` in `--ink-2` for every "Discard my changes" (sheetActions kind `"discard"`). A primary that can't act yet is `aria-disabled="true"`: `--track` and `--ink-3`, still focusable. A button that opened a menu shows it's open. A `.kbd` hint shows only with a mouse from 1000 px.
- **Small controls:** the segmented control is a round track with the chosen segment filled teal (words inside it take its ink); filter chips are `--btn-h` pills, and the on state of a toggle chip is `--accent-soft` with a teal edge and a ✓ (it also works as a `<label>` round a hidden checkbox); the stepper is a round group with teal − and +, its typed number in a sunken well, Figtree casual and mono in the lab; fields are `--input-h` with `--r-field` corners, a teal edge and a 3 px halo on focus; ticks are `--check-size`.
- **Notices:** every `.box`/`.note` notice is `--warn-soft` with an inset `--warn-line` and a stroke icon in `--warn-icon` for its kind: an info circle (`.box-info`, a plain `.note`), a refresh (the new `-stale`, now on the library's and the editor's "Tables out of date" panels) or a triangle (`-warn`). Crit and good keep their fills. `--info-*` is left to the info pills.
- **Menus, sheets, bars:** menus have `--r-row` corners and `--btn-h` items at 600, `--hover` under the pointer or the arrow keys; sheets `--r-panel` corners and, on a phone, a 40×5 grabber; the action bar `--bar-bg` with a top border. A `menuButton` menu is kept inside the window (core.js `keepInWindow`) and a page head's More opens under its button, right-aligned.
- **Tables:** `table.data` rows are `--row-h` with `--divider` lines; a 30 px mono uppercase header on `--surface-2`; mono numbers from 1000 px; the row states the page slices will set (`tr[data-selected]`, `tr[data-match]` with `.cell-match`, `tr.group-row`, `.cell-unknown`). Card rows get `--divider` lines, thumbnails `--shadow-img-sm`, and a missing picture a framed card glyph.
- **Touch and hover:** one `@media (pointer: coarse)` block holds every control at 44 px (six page rules that did it themselves were removed); every component hover is under `(hover: hover) and (pointer: fine)`. `--r-sm` is 4 px. The Shopping badge is `aria-hidden` and its count is in the link's name.
- **Review fixes before commit** (a review workflow: reviewers by lens, each finding checked by a sceptic; 17 confirmed, all fixed): info notices amber as 4.5 says, not blue; the secondary's fill none in dark; the segmented track 44 px on touch rather than 50, and corners that don't clip a track wrapped to two rows (`--r-seg`); a 1 px open-menu ring rather than 2.5 px; the missing picture's card glyph; the card viewer's hovers gated; a page's grey words unreadable inside the chosen segment (a deck filter's count, a practice setup's sub-line); a card's label row stretched to a full row and pushed away from its card; Collection import's problem rows losing their amber on hover; Collection's quantity size overridden at lab width; Receipts' read-only split count drawn as a typeable well; a stepper's number 14 px on the iPad in landscape, so iOS zoomed (`--fs-qty-input`); the toast's Undo focus ring under 3:1; the lab's segmented track invisible on the page in light (kept `--track` until slice 8); number and words columns running together; a page head's More running off the window.
- **Left for later slices:** the docked sheet (slice 14); the action bar's height and toast offsets (slice 7); `--shadow-1`'s ring, panel and tile radii, the lab `--surface-chip` track and the library's ⋯ menu placement (slice 8); the new row states' producers, toggle-chip labels, `.is-changed` and the can't-act-yet primaries' focus-to-blocker click (slices 11 to 14); clashing page rules (Receipts' 36 px phone fields, `stats.css`'s 52 px setup segments, the editor's amber Save dot, `deck.css`'s row states, `variant.css`'s sheet radius); the tabs' ungated hover.
- **Tests:** `test_device_layout_ui` ComponentTests (the one touch floor and no page touch heights, the components reading the tokens, teal for selected and changed but not Part received, hovers only with a mouse, every notice amber, the 44 px track and 16 px stepper number on touch, the page's row states winning) and the new tokens at every level in DensityTokenTests; `test_shell_ui` (the badge's words in the link's name); `test_web_matchup_files` (the info box's icon). Checked in headless Chrome at 1470 px, a 393 px phone and the iPad in landscape in both themes, before the review fixes; the fixes on a static page of the components at 1470 px in both themes. Not checked on the real devices yet.

## P1 density tokens (2026-10-24, E11-S30 slice 3)

The third slice of the P1 visual redesign: the type, radius and size tokens of [design/visual-design.md](design/visual-design.md) 2.3–2.5, each with one name and a value per density level. Nothing reads them yet, so no page changes; slice 4's components are the first.

- **Levels:** casual in `:root` (under 1000 px: phones and the iPad in portrait); the touch lab from 1000 px (the iPad in landscape: lab type and radii, but 14 px body, table numbers and inline win rates, 15 px buttons, 16 px fields so iOS doesn't zoom, 44 px controls and rows); the dense lab from 1000 px with a fine pointer (13 px body, 28–32 px controls). Sizes shrink only under `(pointer: fine)`, which is the spec's 44 px touch floor in token form; a narrow window with a mouse keeps today's 36–38 px.
- **Tokens:** `--fs-h1`, `--fs-hero`, `--fs-eyebrow`, `--fs-group`, `--fs-body`, `--fs-row`, `--fs-meta`, `--fs-btn`, `--fs-input`, `--fs-th`, `--fs-kbd`, `--fs-cell-num`, the `--fs-fig*` family, `--fw-medium`, `--fw-heavy`, `--ls-*`, `--lh-copy`, `--r-panel`, `--r-row`, `--r-field`, `--btn-h`, `--seg-h`, `--input-h`, `--stepper-h`, `--check-size`, `--row-h`, `--list-row-h`, `--tile-min`, `--tile-min-forge`, `--flag-h`, `--gutter-list`.
- **Kept as they are:** the older `--fs-*`, `--r-sm`, `--r-md`, `--r-lg`, `--ctl-h` and `--field-h`, so today's pages don't shrink before their components are restyled; `--r-sm`'s move to 4 px waits for slice 4.
- **Review fixes before commit** (a review workflow: three reviewers, each finding checked by a sceptic; 8 of 15 confirmed, all small): the touch lab's inline win rate raised to 14 px so it isn't smaller than the text beside it; three comments corrected; the test made table-driven over every token at every level (it had missed about 50 single-value changes), with the iPad in portrait, a phone on its side, QHD and the 999/1000 px edge added, and its media-query reader failing loudly on a query shape it can't read; UI-KIT.md's tokens table and a Density levels paragraph.
- **Tests:** `test_device_layout_ui` DensityTokenTests works out each device's computed tokens from `tokens.css`'s media blocks. Nothing visible to check on the devices yet.

## P1 colour tokens (2026-10-24, E11-S30 slice 2)

The second slice of the P1 visual redesign: every colour and shadow in `tokens.css` takes P1's value, in both themes ([design/visual-design.md](design/visual-design.md) 2.1, 2.2 and 2.6). Page layouts don't change.

- **Re-valued:** the inks (`--ink-3` darkens to 5.9:1 on the page and is now fine for text), solid borders instead of translucent black or white, `--link` dark teal (light teal in dark; only info boxes stay blue), a darker `--warn-ink` for text on amber, the shadows, and the dark theme's greenish page and surfaces with near-black text on teal.
- **Added:** `--surface-chip`, `--track`, `--hover`, `--ink-4`, `--divider`, `--rule`, the teal family (`--accent-strong`, `--accent-line`, `--accent-track`, `--ring-track`), the amber family (`--warn-ink-sm`, `--warn-line`, `--warn-icon`, `--building-ink`), `--missing`, Forge's `--strong-*` and `--weak-*` and range-bar tokens, `--shadow-img-sm`, `--shadow-primary`, `--mana-ring`, and the deck colours `--stripe-*`, `--tint-*` (dark: the dark stripe at 16% over the surface) and `--art-*`. Later slices use most of them.
- **Review fixes before commit:** a review workflow (four reviewers, each finding checked again by a sceptic; 31 findings, 10 confirmed) found where pages leant on what a token used to mean. Fixed: amber warning words on a plain surface (thirteen rules) now use a new `--warn-text`, since the new `--warn-ink` was nearly the body text colour there; hovers moved from `--surface-2` to `--hover` (`--surface-2` is now darker than `--surface` in dark, so hovers sank); meter and colour-bar tracks to `--surface-3`; the avatar's menu-open gap to `--surface` (the translucent dark `--accent-soft` let the teal ring fill it); the even matchup cell's edge to `--ink-4`; the library's pip ring to `--mana-ring`; the dark browser `theme-color` to the new surface; `--shadow-1` keeps its P1 ring back until tiles and panels lose their borders, or they'd draw a double edge.
- **Known and left to later slices, as the spec chose:** input and button borders (`--border-strong #d8d6ce`) are fainter than before (about 1.5:1 on white, from 1.8:1); dark `--surface-2` wells sit barely apart from the page; `--grid`, `--baseline`, `--band-ok` and `--series-muted` keep their old values, which the spec doesn't cover. Look at the field borders on the MacBook (section 6, question 11).
- **Checked:** the web and page UI tests; screenshots of the library, a deck page, Collection and Matchups at 1470 px in both themes on a test server (headless Chrome). Not checked on the phones or the iPad yet.

## Self-hosted typefaces (2026-10-24, E11-S30 slice 1)

The first slice of the P1 visual redesign ([design/visual-design.md](design/visual-design.md)): the page's text is now Figtree and its code and copy boxes JetBrains Mono, served by Deck Lab itself.

- **Files:** `web/fonts/figtree.woff2`, `figtree-italic.woff2` and `jetbrains-mono.woff2`, Google Fonts' variable files (Figtree 2.002, JetBrains Mono 2.211) subset with fontTools to Latin, Latin-1 and Deck Lab's punctuation: 18, 19 and 38 KB. Their OFL licences, sources and the subset command are in `decklab/fonts-licences/`; each file keeps its name table, licence included.
- **Page:** `base.css` declares the three faces (`font-display: swap`, the weight ranges of the variable axes); `tokens.css` puts them first in `--font` and `--font-mono`, before the system fonts used until now; `index.html` preloads Figtree's upright face only.
- **Server:** `.woff2` is served as `font/woff2` from the new `web/fonts/` folder, with no-cache and an ETag like the scripts, but without the `?v=` stamp, so the preload and the `@font-face` URL stay the same file.
- **Review fixes before commit:** an italic face instead of a faked slant; the licence kept in each file's name table; † and ‡ added to the subset; JetBrains Mono not preloaded until a page's first view uses it (only code and copy boxes do today); the README says which characters the families lack (Figtree has no ▲ ▼ ′ ″ ≈; neither has the menu and mark symbols), which fall back to the system font as before.
- **Tests:** `test_web` test_the_typefaces_are_self_hosted_and_preloaded (the faces, their URLs and files, the one preload, the token order, the licences); `test_server` serves a woff2 with its type. Not checked in a browser or on the devices yet: text widths change with the typeface, so a page may wrap differently.

## Condition and language on many rows (2026-10-22, E7-S29)

The Card list's **Set condition & language…**, asked for when 91 rows had no condition or language recorded and the card sheet set them one at a time:

- **Page** (`collection-bulk.js`): a button on the Card list toolbar's filter line (before the count), only where the visitor may change the collection, acts on the rows the search and filters show (so ticking "Condition or language not recorded" first gives exactly those). Its sheet has Condition (Leave as is, NM, LP, MP, HP, DMG), Language (Leave as is, then the card sheet's languages), and Only fill in blanks, ticked to start. A live summary says what Save does ("Sets language English on 91 rows and condition NM on 60 rows; 31 already have a condition"), and a note counts shown rows whose notes say their merged copies didn't agree. Save sends only the rows it changes; the answer redraws the list and its message as a single save's does. A 409 shows the latest rows and works the summary out again, with nothing saved.
- **Review fixes before commit:** a language or condition that isn't text is a 400, not a 500, and a key that isn't an object says "Each key", not "original"; after a 409 that turns a filter off (nothing is unrecorded any more, say), Save still covers only the rows the sheet was opened on, and says so, rather than every row; a 409 that leaves no rows says so with only Close; the choices are locked while a save is on its way; when a save leaves nothing shown (so the button hides), the search keeps the focus; the button sits with the filters, not alone under the count. The page wasn't checked in a browser at a phone width: it uses the shared toolbar and sheet.
- **Server:** `POST /api/collection/bulk` (`collection_edit.bulk_set`) takes the rows' keys, a condition and/or language and `only_blank`, checks them as the card sheet's values (`CONDITIONS`, Scryfall's codes), the sha256 (409 with the rows) and that each key is listed (409 as a save), and builds the edits itself, changing only those fields. They're one `collection.apply` (E7-S26's operation), so one change set: "edit 91 rows in the home collection" (`ops_collection.message` now words it beforehand). With nothing to change it writes nothing and answers `changed: 0`. Quantities don't change, so there's no in-use warning or reason to ask for.
- **Tests:** `test_collection_edit` BulkTests (blanks only by default, overwrite, only the named rows, nothing to change, stale sha, an unknown key, who may, bad requests, too many keys or too big a body), new `test_collection_bulk_ui` (the shown rows, the summary, the posted body with a condition and overwrite, the locked sheet, the out-of-date tables note, the focus, a search, read only, a conflict, a conflict that clears a filter or leaves no rows), `test_collection_ops` (the message beforehand).

## In storage only on the Card list (2026-10-22, E7-S28)

The Card list's **In storage only** filter, asked for right after its prices (E7-S27), so that sorted by price it lists the storage cards worth sleeving:

- **Which copies are in decks:** the pool counts held copies by name (built decks, with stand-ins, and products kept intact). `pool.InUse.printings` now also keeps the printings their lists name, and `collection_edit._storage` gives each name's held copies first to the rows of those printings, then to its cheapest rows (`_prices`), marking `guess` on a row that got one when another row could have. Basic lands get `held: null`: their copies in decks aren't tracked. On the live home collection all 341 held copies were placed, one as a guess.
- **Answers:** `storage` (`rows` keyed as the prices are, with `held` and `guess`, and `error`) goes with the prices (`_extras`) in the rows view, a save, an import and a changed collection's 409. Counts only, never deck names, to viewers who may already see the space's inventory. If the pool can't be read, there are no counts and the page doesn't offer the filter.
- **Page:** the filter's label counts the rows it leaves; under a row's copies, "1 in a deck", "2 in decks" or "all in decks", with "?" and a title for a guess; while it's on, the note under the list says basic lands are always listed.
- **Review fixes before commit:** no counts (and so no filter) while the card data isn't ready, rather than every row "in storage"; unpriced rows after priced ones in the cheapest-first pass; a guess only when there's a choice (fewer copies left than room), so rows certainly all in decks aren't marked "?"; the note wraps in the narrow Copies column; and what a "?" means, or why the filter isn't offered, is said in the note under the list, since a title can't be read on a phone.
- **Tests:** `test_collection_edit` (named printings first, the cheapest for the rest and the guess, unpriced rows last, no guess without a choice, card data not ready, basics, an unreadable pool, the sandbox's built decks through the rows view), `test_collection_prices_ui` (the filter, the notes, a save bringing a row back, no filter without counts).

## Prices on the Card list (2026-10-22, E7-S27)

The Collection page's Card list has a **~A$ each** column, built after Matt asked which storage cards were worth sleeving (a one-off sort of the home collection from the PC found 25 cards at A$10 or more):

- **What's priced:** each row's own printing and finish (`usd`, `usd_foil` or `usd_etched` of that set and collector number, `cards.PRICE_FINISHES`) at the ECB rate, unlike the deck tables, which price a card's cheapest printing. A row with no printing recorded, or no Scryfall price in its finish, shows a dash.
- **Server:** `collection_edit._prices` adds `prices` (`rows` keyed as the pictures are, `"set|number|finish"`, with `usd` and `aud`, and `rate`, `rate_date`, `price_date`, `price_error`) to `GET /api/collection/rows`, a save's answer, an import's and the 409 a changed collection answers (review found a conflict's new rows shown unpriced; the page now takes both, `colTakeRows`). Kept apart from the rows, which stay the eight columns the sha256 covers. No rate (offline, nothing cached): no prices, and `price_error` says why.
- **Page:** the column sorts like the others; its first tap is most valuable first, the second cheapest first, and unpriced rows stay last both ways. A note under the list gives the price date and the rate. It shows at every width, beside Copies.
- **Not done:** no collection total (AGENTS.md: no budget tracking). The "in storage only" filter followed the same day (E7-S28).
- **Tests:** `test_collection_edit` (prices by printing and finish, a foil add's answer, no rate), new `test_collection_prices_ui` (the sort both ways with unpriced last, a save's prices, a conflict's, the note without prices and from an older server).

## Many collection rows in one change (2026-10-21, E7-S26)

`python -m decklab.db collection apply FILE [--space S] --expect SHA -m MSG [--reason R] [--allow-in-use] [--remove-missing] [--dry-run] [--actor P]` (`inv_collection._apply`), built after setting Matt's Hatsune Miku precon cards to NM and `en` took 89 `collection edit`s, and so 89 change sets:

- **What it does:** FILE is an edited copy of `collection list`'s output. Its rows are matched on (set, collector_number, finish); each row whose quantity, condition, language or notes differs becomes an edit, and each row at quantity 0 a removal, which needs `--reason`. They're saved as one change set by the new operation `collection.apply` (`ops_collection.apply_rows`), which runs them as `collection.edit` and `collection.remove` would, so a refusal of one refuses them all.
- **The same checks as `collection edit`:** a changed field goes through edit's checks, now shared as `_field` (the page's `_text` and formula rules, the conditions, Scryfall's language codes), `_quantity` (0 to 9999) and `_matched` (the page's `match`). `--expect`, the in-use refusal, `--allow-in-use` and the dry run are edit's too, now shared as `_expected`, `_listed` and `_save`; `collection edit` behaves and prints as before. A field FILE leaves as it was isn't checked again, so the listing as printed always comes back with nothing to change.
- **Rows left out of FILE are refused, not removed:** review found that a cut-off, filtered or header-only copy of the listing would have removed every row it lacked with only `--reason` in the way (a dry run against the live home collection with its first four rows printed "861 removed"). A row left out is now refused, dry run or not, naming how many are left out and how many FILE lists, unless `--remove-missing` makes them removals too; the `--reason` refusal counts the rows at quantity 0 and those left out separately. The same dry run now refuses: "861 rows of the home collection are left out of part.csv (it lists 4 rows)".
- **Refused, with nothing saved:** a key the collection doesn't have (new cards come through `collection merge`, a receipt or `add-precon`), a changed name, a key listed twice, a header that isn't the collection's columns (they may come in any order), a row with the wrong number of columns, and any field edit's checks refuse. A byte-order mark is dropped and Windows line endings are read as plain ones.
- **Output:** the counts changed, removed and unchanged; with `--dry-run` also each change (`Would change <row>: condition (blank) -> NM, ...`) and removal, the in-use warnings and the decks whose tables it would leave out of date. A dry run with removals and no `--reason` says the save would need one, rather than refusing. After a save it names the out-of-date tables as edit does. `collection list`'s stderr hint now names apply too.
- **`collection list` redirected to a file is UTF-8:** it wrote through the console's code page (cp1252, with `?` for what it can't show), so a name such as Ōkami came back changed and apply refused it; it now writes the collection's UTF-8 bytes when stdout isn't a console, as `deck pull` does.
- **Tests:** `test_collection_ops.CollectionApplyCliTests` (the unchanged round trip, a redirected listing's UTF-8, several rows in one write, removals and their reason, cut-off, header-only and filtered files refused, `--remove-missing`, reordered columns, the card check's refusal, Windows line endings and a byte-order mark, refusals, a stale listing, the dry run, in-use, registration), `PgCollectionApplyTests` (one audit change set with the message and reason on the database) and `FileOpsTests`/`PgOpsTests` for `collection.apply` itself (one change, and one refused row refusing them all).
- **Known low issues:** like edit, it can't move a row to another printing or finish. A dry run against the live home collection with the listing as printed said there was nothing to change.

## A Forge upgrade check in one command (2026-10-21, E11-S15)

`python -m decklab.lib.forge upgrade-check` (`lib/forge/cli_upgrade.py`) is the post-build check of a new Deck Lab Forge, built ahead of Forge 2.0.16 (about mid-November 2026, an estimate), which will be its first real use:

- **The steps:** `cardlog-check`, `serve-check` and the card-script overrides' upstream check (`overrides check`), in that order, each through its own command with its own defaults, printing as usual under its name. A step that fails, or ends with an error (a bug or a full disk included, its traceback logged), doesn't stop the others. Both game checks are skipped when Forge can't be started, and `serve-check` is skipped only when `cardlog-check` couldn't build the card log, which `serve-check` needs too (`cli_checks._CardLogUnavailable`), not when it failed after building it. The overrides check always runs.
- **The summary:** one line a step, passed, failed with its first printed line (an error's sentence, or for the overrides the first problem and how many more) or skipped with why. Exit 0 only when all three passed, else 1.
- **Replaying:** when saved matchups were played with another engine than today's (replay's own plan, against the card log's engine as it would be built now), it prints `replay --dry-run`'s matchups, games and rough time (`cli_results._print_replay_plan`, now shared with `replay --dry-run`), and, as the dry run does, says `replay` refuses (and why) when the card log can't be used now (`install.status`), whatever this run's `cardlog-check` did.
- **What it writes:** only what its steps write (`cardlog-check` notes a pass or a failure in `checked.json`, as on its own). It never runs `overrides make` or `replay`, and plays no matchup.
- **`--plan TAG`** prints the README's manual steps for a release tag (rebase the fork's `decklab` branch, `BASE_TAG`, the scratch build, `engine-check`, the fast-forward merge and install, `upgrade-check`, `simjar.CHECKED`, `replay`) and runs nothing. Its `engine-check` step, like the README's, says a new release's expected result is exit 1 with "Different engine key" and no "Don't install this build as it is" line.
- **Acceptance 3 was already built:** a failed `cardlog-check` is noted (`simjar.record_failed`), so runs get no card log and play plain Forge, and the Matchups page's status note says "Per-card stats are off" with the reason.
- **Tests:** `test_forge_upgrade_check` (each step's pass, fail, error and skip, the summary, the exit code, the replay part against fakes and against `replay --dry-run`'s own output from saved results, `--plan`, registration); `test_forge_contract`'s command list. No Forge process starts in them.
- **Known low issues:** it checks the installed build (`config.json`'s `forge_dir`) only, with no `--dir`. The step's reason is its first printed line, so a `cardlog-check` with several problems names only the first (the rest are above it).

## Two-card combos and Wizards' latest Commander announcement (2026-10-21, E9-S23, E9-S24)

The sources were researched live first ([design/commander-sources.md](design/commander-sources.md)), and Matt accepted every recommended answer there.

- **Combos (E9-S23):** `cards update` downloads Commander Spellbook's public export (`json.commanderspellbook.com/variants.json.gz`, about 31 MB) as a step of its own. It's conditional on the ETag, refreshed after 7 days, kept when a download fails, and runs after the card index is built, so it never holds the index up or fails the update. `lib/combos.py` reduces the export to its Commander-legal two-card combos with no template piece: 3,917 on 2026-10-21, 2,734 of them standalone. They go in `data/combos/two_card.json`. The Commander checks match them on the PC by oracle id over the Commander, Companion and Deck sections; a piece that must be the commander counts only there. No decklist leaves the PC: Spellbook's decklist endpoints are never used.
- **What raises the minimum:** only standalone infinite or game-ending combos raise it, to Bracket 3. A combo that destroys lands counts as mass land denial (Bracket 4) whatever its status. Locks, draws, near-infinites and combos needing a payoff are listed and raise nothing. The page names each combo with its pieces and a Spellbook link, and gives the list's date. A combo's floor is worded "a two-card combo it holds puts it at Bracket N or higher, unless the combo isn't intended", kept apart from the cards' own floor (`bracket.cards_minimum`). An unreadable list says "not checked" and marks the checks incomplete. There's no early-game hint.
- **Official lists (E9-S24):** `lib/official_lists.py` checks Wizards' sitemap at most once a day, also from `cards update` and so from the server's daily check. The request is conditional and gzipped, and the Commander format page itself is never fetched (Wizards' terms). The newest Commander announcement goes in `data/scryfall/official_lists.json`: 2026-02-09's Brackets update today. Its date comes from the post's URL, never `lastmod`, and a failed check keeps the last good one. The checks warn while the card data is no newer than it, or while the bracket rules (`constants.BRACKET_RULES_DATE`, 2026-02-09) are older. They say the date is unknown when no check worked in 7 days. A new post means "announced, may have changed": once the rules are reviewed against it, set `BRACKET_RULES_DATE` to its date.
- **Tests:** `test_combos` and `test_official_lists`, plus new cases in `test_cards`, `test_stats`, `test_commander_readiness` and `test_commander_readiness_ui`.
- **Known low issues:**
  - Spellbook's results are classed by their names, so a few game-ending combos worded unusually may class as "other" and raise nothing. One example is "put all creature cards from your library onto the battlefield", 10 combos.
  - A sitemap that turns into a sitemap index fails the check, and the last good result is kept.

## A collection edit command (2026-10-21, E7-S25)

`python -m decklab.db collection edit SET NUMBER FINISH [--space S] [--quantity N] [--condition C] [--language L] [--notes T] --expect SHA -m MSG [--reason R] [--allow-in-use] [--dry-run]` (`inv_collection._edit`), so a fix Matt names at the PC doesn't wait for the Collection page:

- **The page's operations and checks:** `collection.edit` with the row's other fields kept (notes replaced, not merged; `""` clears a field), or `collection.remove` for `--quantity 0`, which needs `--reason`. Text fields pass the page's `_text` and formula rules, the card the page's `match` when the card data is there; condition must be NM, LP, MP, HP or DMG and language one of Scryfall's codes, or blank. Moving a row to another printing or finish stays the page's.
- **`--expect`:** `collection list` now prints the collection's sha on stderr (the CSV on stdout is unchanged); at least its first 12 characters are checked here, and the full sha, the inventory revision and the decks revision again under the write lock.
- **In use:** a reduction the page would warn about (`collection_guards.reduction_warnings`: fewer copies left than built decks or intact products hold) is refused, naming the holders, unless `--allow-in-use`. `--dry-run` prints the change, those warnings and the decks whose tables it would leave out of date (the preview's pool against today's), and saves nothing. After a save it names the out-of-date tables as `collection merge` does.
- **Tests:** `test_collection_ops.CollectionEditCliTests` (fields, removal and reason, dry run, refusals, in-use, registration).

## Stand-ins for missing cards (2026-10-20)

E2-S07 built. Matt's rule (2026-10-19) is a stand-in with the same card type, a shared colour and a mana value within 1; `lib/decks/swaps.py` settles the rest:

- **Type** is one primary type per card, from its front face, in the order land, creature, planeswalker, battle, instant, sorcery, artifact, enchantment (an Artifact Creature is a creature, Dryad Arbor a land); instants and sorceries stay apart.
- **Colour** is the card's colours: colourless matches only colourless, and a stand-in must also be castable in the deck (a casual deck's spell colours; a Commander deck's identity).
- **Lands** match only lands, by the mana they make and their colour identity (Command Tower and City of Brass are all five colours, not colourless), with the deck's basics always offered. In a casual deck a stand-in land makes only the deck's colours, or every colour. Commander and Companion lines are never swapped; casual lists keep the 4-copy cap, Commander decks one copy.
- **Free** copies are pool.py's (owned and on the way, less other built decks and intact products, this deck's own copies free; `pool.free_copies`, now shared with My collection), less the copies already in the Play-now list; copies here rank before on-the-way ones.
- **In the editor** a short Play-now line's ⋯ menu has Stand-ins… (`POST /api/deck/swaps`, a dry run); Use n swaps the cards and adds a factual strength note ("A little weaker: costs 1 more (6 vs 5); loses haste") to Substitutes once: a row of its table placed by the table's headings (Buy, Stand-in or Play now, the note last), else a bullet. Lost colours count only the deck's, and mechanics such as Transform, Treasure and Food are never a loss or a gain. Deck Lab never writes that prose again, so an edited note survives every save. The deck page's Missing filter lists "Owned stand-ins" (`GET /api/deck/swaps`, five rows then Show all) and links into the editor only while the Play-now list is short of the card too (`list_missing`).
- **Swaps aren't stored:** they're the difference between the two lists, paired with the Substitutes line naming the missing card (a longer card name of either list, such as Anger of the Gods, doesn't name Anger), so existing hand-written tables pair too. A stand-in's surplus is shared out among the swaps naming it, the copies a line states first, never counted twice; the Play-now list's Overview and Cards tab show them ("Swaps from the Planned list").
- **Privacy:** suggestions show only to viewers who may see the space's inventory (403 otherwise, after the deck's own 404) and never name a holder deck; the swaps and notes show to anyone who may see the deck.

Kept apart from the Packing plan's physical stand-ins (E4-S21), which never change a list. Tests: `test_swaps_core`, `test_swaps_api`, `test_editor_swaps_ui`, `test_deck_swaps_ui`; the goldens drop only the new `swaps` key (`golden_p4.swap_defaults`).

## Restart after a crash (2026-10-20, E11-S26)

Task Scheduler's restart-on-failure only covers a task that fails to launch, and a repetition trigger on the "Deck Lab" task would rerun the server itself, so `install --at-logon` now also registers a second task, "Deck Lab watchdog" (plain `install` and `remove` delete it). Every 5 minutes while Matt is logged on it runs `pythonw.exe -m decklab.lib.homenet ensure`, which starts the server through the "Deck Lab" task (its IgnoreNew setting and the server's exclusive port keep two starts from racing) only when that task is there, enabled and starts at logon, nothing answers or holds the port, no live server is recorded, the logon and the last start that was asked for are both at least 2 minutes ago, and there's no stop marker. The 2-minute wait (`WATCHDOG_GRACE`: the logon trigger's 30 seconds, a start's 20 and slack; a start's time is the record's `asked_at`, written by start, restart and install) keeps a check that lands in a logon or a start from starting the task early or recording a restart that didn't happen. The marker (`decklab/data/stopped-<port>.json`, with the session's logon time) is written by `homenet stop` and `server.py --stop` before they signal, by `install --at-logon --no-start` while Deck Lab is off (so the new watchdog doesn't start it), and by a server stopped on request (stop event, taskkill without /F, Ctrl+C, closing its console window), and cleared by start, restart, install and the server once it's listening, so a stop holds until Matt starts it again or next logs on (E11-S23); a marker from an earlier logon doesn't count. A restart whose stop times out leaves a restart's marker instead, so the watchdog starts the server once it has stopped. A crash, a hard kill without a prior stop, or a shutdown counts as unexpected. After 3 restarts that don't stay up 10 minutes the watchdog gives up until a manual start or the next logon; a Deck Lab that answers and has stayed up clears that, and a hung but live server is never killed. It logs only changes and restarts, to `decklab/data/logs/watchdog.log`, and keeps its restarts in `decklab/data/watchdog-<port>.json`. `status` gains a "Restart after a crash" section: a WARN when a start-at-logon install has no watchdog (fix: `install --at-logon --no-start`) or one whose settings were changed, a WARN for a restart in the last 24 hours, and a PROBLEM when it gave up. No page or API change. Review fixes (2026-10-20): the `--no-start` marker, the 2-minute wait after a logon or start, the window-closed marker and the restart's marker. Tests: `test_homenet_watchdog`, `test_control` (StopMarkerTests), `test_server_lifecycle`, `test_homenet`, `test_homenet_gather`. Nothing was written to the database. Turned on the same day: Matt ran `homenet install --at-logon --no-start`, then `restart`, and `status` shows "OK Restart after a crash".

## Warn when sleeves already in use are chosen (2026-10-19)

Matt's answer to the design model's open question on shared sleeves (E8-S20): warn when kit already in use is chosen. Sharing one sleeve design between decks stays allowed. Now every place that chooses sleeves warns first when another built deck or intact product already has that design:

- **The kit picker** (deck page, Packing plan, Sleeves & boxes' products panel) always asks "Use X here too?", naming the other holders (a hidden one as "one of User1's decks"). Before, it chose such sleeves silently when no other holder could be moved. **Move them here** is still offered only for holders the viewer can change.
- **The editor's Deck details** asks the same before picking the tile (`pickKitTile`). Arrow keys only move the focus onto such a tile; Enter or Space picks it, after the question.
- **The Packing plan's Finish building sheet** asks "Use … too?" before Mark as built when a deck is given sleeves another deck has, or that another deck in the same sheet is given too, and its sleeves options say "Also used by X".
- **`deck push`, `deck new` and `product set-kit`** save as before and print "Warning: X uses Y already…" (`accessories.sharing_warning`, read before the change; `deck push --dry-run` prints it too).
- **The deck page's Sleeves tile** says "Also sleeves X" in plain text, not as a warning. `accessories check` and the kit warnings still don't report sharing.

Deck boxes keep their rule: once every box of a kind is in use they can't be chosen except by moving one, and a row with a spare box free doesn't warn (Matt, 2026-10-19). Tests: `test_feature_ui`, `test_editor_contracts`, `test_deck_kit_ui`, `test_assembly_sheets_ui`, `test_accessories`, `test_inv_decks`, `test_product_kit_cli`.

## Database: the week of side-by-side checks ended (2026-10-19, `DB#1`)

The week of nightly checks after the move to PostgreSQL (2026-10-13 to 2026-10-19) ended clean: every night's dump, prune, export and check worked, `ops.backup_run` has no failed run, and six of the seven nights ran a restore check that matched row counts and content digests (2026-10-13's wasn't due, six hours after the cutover's at 21:27 the night before). The report is [magic/reports/2026-10-19-database-check-week.md](../magic/reports/2026-10-19-database-check-week.md). `config.json`'s temporary `restore_check_days` (0.5) came out, so restore checks are back to every 28 days; `side_by_side_until` stays, and from 2026-10-20 `status` says the checks ended. The rollback tooling stays retired (phase 5b, 2026-10-14). Also noted: migrations `0012` and `0013` were applied and the server restarted on committed code on 2026-10-19 at 07:44, so the privacy and member-departure code is live.

## TODO run: final verification (2026-10-18)

Started from clean `main` at `51e1938c58bc0a26ebf697769e9fd8fd9c63b1da`.
Completed the nine actionable queue items: E3-S01, E10-S28, E10-S31, E10-S33,
E10-S34, E10-S37, E10-S40, E11-S20 and E11-S25. TODO now has no OPEN rows;
the remaining rows retain their people, date, release, priority or authorization
gates. Changes are local commits on the existing main branch.

Final code snapshot `d3f8e90`: `python -u -m unittest discover -s decklab/tests -t . -v`
ran **5,840 tests in 1,076.580 seconds**, with **34 skips** and no failures or
errors. The skips are 30 opt-in real Forge/JDK checks, one invalid-collection case
that PostgreSQL cannot represent, two POSIX-only journal boundaries, and one
symlink test requiring unavailable Windows privilege. All disposable-database
classes ran. Real Forge was explicitly disabled.

The first broad run had 24 failures across 5,734 tests; stale API/golden assertions
and scratch cleanup were corrected. The next run covered 5,836 tests and exposed
the lifecycle diagnostic/fixture-log issues recorded below. Their bounded
follow-ups and the final full run pass. Logs remain in the task's temporary
folder as `tcc-full-suite-20261018.log`, `tcc-full-final-20261018.log` and
`tcc-full-verified-20261018.log`.

`git diff --check` passes. The source-length check still exits 1 for two files
already over 1,200 lines at baseline: editor-screen.js (1,359 then and now) and
test_feature_ui.py (1,217 then, 1,219 now). There are no newly oversized files.
Trusted instruction files were not changed. Disk capacity stayed above 1 TB free
during final validation; validation had no approval or resource blocker.

No push, deployment, live migration, service restart, visibility flip, actual
member export/removal or existing artifact cleanup was performed. Activation
needs migrations 0012/0013 and a committed-code restart when authorized. Physical
devices, the signed-in off-page check, User2's review, the final October 19
nightly report and gated real Forge work remain. Stop early: there is no next
actionable coding batch under this run's constraints.

## Forge validation follow-ups (2026-10-18)

The broad run found two fixture issues. Lifecycle preflight now refuses an unsafe
results root before the old per-run check, so its fixture expects that message;
private path diagnostics remain in the server window. Fake Forge's Windows
startup-log appends are serialized, and its reader waits for complete records,
ignores blank rows and still rejects malformed completed rows. Concurrent-append
coverage also checks that the lock adds no file padding. Production slot logic
and timing thresholds are unchanged.

Validation: 39 slot/log tests and 81 lifecycle/fake-execution tests passed, with
no skips. No real Forge games, database writes or service changes were involved.

## Guarded member departure and crash recovery (2026-10-18)

E10-S40 is built in code. Apply rechecks the exact exported database/Forge snapshot
under exclusive lifecycle and database claims, stages only own-only Forge files
in same-volume quarantine, and removes/redacts the member's data in one audited
change. Mixed games and plans retain the other space's side with "a removed deck"
in place of the departing side; surviving sides remain editable.

A durable journal precedes file moves. Recovery checks the exact immutable audit
and departure identity, restoring files after rollback or finishing committed
cleanup. Unknown outcomes preserve everything for recovery; different files are
never overwritten. Forge writers hold shared claims from their first saved read
through their final checkpoint, notes and summaries. Pending journals block
writers, and departed spaces cannot start new ones. A read-only runtime gate
refuses old/dirty servers and unaccounted interpreters instead of stopping them.

Prepared migration 0013 stores a minimal audited departure marker. Shared
transaction admission keeps inventory, state, profile sync and buffered visits
from recreating removed data, including queued requests. Explicit CLI
`--allow-orphan` wishlist upkeep is preserved for non-departed identities; web
requests and missing actors cannot use that exception. Maintenance exports,
backup digests and data checks include the marker.

Validation: all 13 apply/recovery tests, 107 state/wishlist tests, 6 departure
maintenance tests and 157 Forge lifecycle/writer regressions passed in their
bounded runs. Journal fixtures have three platform skips on this Windows host
(two POSIX-only paths and unavailable symlink privilege); native moves and
process-crash recovery passed. Runtime unit and temporary HTTP checks passed.
The guarantee covers application/process crashes, not a hardware or power-loss
transaction across PostgreSQL and the filesystem.

Migration 0013, committed-code service adoption and deliberate member departure
remain operational gates. Config/Cloudflare Access removal reminders are printed
after commit. No live migration, restart, real member export/removal, Access or
config edit, or existing artifact move/delete was performed.

## Restore-check cleanup guards (2026-10-18)

The broader test run exposed an intermittent scratch cleanup failure that hid a
deliberately detected digest mismatch. Restore checks now drop only their exact
configured scratch database, reject PostgreSQL's 63-byte identifier truncation
boundary before connecting, and use ordinary DROP without terminating sessions.
An occupied scratch database fails safely for follow-up.

Validation: all 14 backup/restore tests and 2 target/SQL boundary tests passed.
The active-session test confirms that the session survives refusal and role
privileges remain unchanged. The original isolated test also passed before the
fix, so the exact transient backend was not identified. No live role, database or
service was changed.

## Public readers, owner controls and Forge privacy (2026-10-18)

E10-S28, E10-S31 and E10-S33 are built in code. **Who sees what** offers each
owner their collection, decks, games and kit switches; absent rows remain Private.
One request pins its visibility snapshot. Public collection/game readers redact
private holders, home records and hidden game sides. Public never grants writes
or broadens Activity. Home-only CLI flips use fixed audit messages and retain the
supplied rationale as the reason; members use their own page controls.

Public accessories are read-only, grouped by owner. Writable hashes, kit choices
and photo staging follow ownership; hidden holders use plain words. Picture
authorization runs before conditional responses, addresses change with images,
and private/no-cache responses support revocation without serving a stale image.

Forge readers filter both sides' aliases and hash evidence, including AI/card
summaries, earlier results and ratings. Fields use the viewer's own and public
spaces, with scoped progress notes. Variants require an own-space base. Stop
rights belong to admins, the recorded starter id or an owner of a participating
deck; anonymous admin controls reveal no hidden run details. The browser checks
per-run rights and discards responses after profile or route changes.

Validation: 102 focused visibility, public-reader, export and picture integration
tests passed, including disposable PostgreSQL and temporary HTTP servers. A
further 90 permission, coordinator and rankings regressions passed after updating
their assertions for the new stop policy and reader filters. The source audit has
only its two pre-existing over-limit files (editor-screen.js and
test_feature_ui.py). Migration 0012, a committed-code restart and actual visibility
choices remain activation work; no live migration, restart or flip was performed.

## Exact member-removal preview and full scoped manifest (2026-10-18)

E10-S40's preview slice is built. Manifest v2 binds the member's database state
(including profile/email/visits and derived deck lines) and own-only Forge hashes.
Mixed/unknown provenance and other spaces' current identical-list consumers
preserve shared results; raw Forge JSON never enters the member export.

`space remove SPACE --export DIR --expect SHA -m ... --reason ... --dry-run`
verifies the artifact and fresh snapshot, then lists exact delete/redact row keys
and own-only file hashes, without surviving mixed-record contents. Pure
transformations retain another space's side and replace removed decks with a
tombstone; removing a final remaining side drops the game. Config/Access reminders
are included. Apply explicitly refuses until lifecycle claims, durable recovery
and tombstone readers are implemented together.

Validation: 28 disposable database/fixture tests passed. No real member export,
removal, artifact move/delete, Access change or config edit was performed.

## Non-writing CLI merge, token and deck previews (2026-10-18)

E11-S25 is complete. `collection merge --dry-run` shows per-printing additions,
skipped basics and the exact raw imports it would retain. Token add/edit/remove
previews show the complete affected row before and after. `deck push --dry-run`
shows the proposed text diff and table, card-name, token and accessory checks
against the preview snapshot. Apply and preview share their operations and
validation; messages, reasons, quotas and concurrency checks remain required.
The receipt audit message already names its selected components.

Validation: 9 new file-store tests, 29 related regressions and 1 disposable-DB
test passed. Seven valid/refused previews leave inventory/deck revisions, raw
imports, deck history and audit tables unchanged. No live write was performed.

## Member-only export and matching manifest (2026-10-18)

E10-S40 is partial. `space export SPACE DIR` reads one repeatable-read, read-only
database snapshot and writes only the member's cards, tokens, raw imports and
current/retired deck texts into a new folder outside the source repo. Manifest
file hashes and a space-scoped snapshot SHA detect tampering and later member
saves without exporting mixed-game or other-space contents. Existing artifacts
are never overwritten.

Validation: 12 tests passed on disposable PostgreSQL databases and temporary
folders. Audited removal, mixed-record retention, Forge filesystem coverage and
config/Access reminders remain; no real member export or removal was performed.

## Visibility storage and maintenance foundation (2026-10-18)

E10-S28 is partial: migration 0012 stores opt-in Public rows with audited actor
and time; absent rows are Private. MemoryStore and PgStore share validation and
no-op behavior, with generation-safe cached snapshots and a 60-second maximum
fallback for Public grants. Batch rollback never publishes a grant.

Read-only `visibility list` includes every Private default. Nightly exports and
restore digests include the table; check validates owners; profile sync removes
dropped-space switches in the same audited change. Disposable state, maintenance
and database fixtures cover those paths. The maintenance expectation was updated
for its new visibility subcheck. Public readers and controls remain separate work.
No migration ran against the live database and no switch was flipped.

## Activity stays within its space (2026-10-18)

E10-S34 is complete. Activity gives every named viewer their own space's changes,
with system rows and truly empty change sets for admins. Public readers never
widen Activity. Both web and CLI messages and reasons require every underlying
row to be readable, including grouped/capped rows, mixed-space Update all
changes and changes made by the viewer. Kit and mixed-game restrictions remain.
Visibility flips stay in their space (kit flips at home).

Validation: 112 focused tests passed, with 2 database class skips under sandbox
network limits; integration will exercise the disposable database cases. Unchanged
count helpers moved into activity_counts.py to keep the module within 1,200 lines.

## Public-deck history subjects stay private (2026-10-18)

E10-S37 is built: history lists and single-revision metadata send outsiders plain
summaries and "someone" for other-space profile actors. Generated table and
substitute-availability changes read "Tables refreshed", without order ids or
custom command-line subjects. Current, retired and migrated git revisions follow
the same rule; own-space and script readers keep their prior messages and kit
restrictions. The browser no longer masks subjects itself.

Validation: 132 fixture/UI tests passed (2 database skips), plus 9 isolated
home-listener tests. No deck was published; controls remain gated by their readers.

## Dated Stats disclosures and guarded CLI receipts (2026-10-18)

E3-S01 is built: the land formula, rule of thumb, colour requirements and Commander
bracket disclosures show each source's recorded date, or "date unknown". The bottom
source list, shared title-only links and per-colour hardest-first summaries are retained.
109 Stats, UI and web tests passed.

E11-S20 is built: a valid `receive` preview prints a token binding the inventory
revision and receipt intent. `--apply --expect TOKEN` refuses changed inventory,
components, supplied rows, date or checks; the backend checks the revision again
under its write lock. Omitting the token retains existing revalidation. E11-S25's
receipt audit-message slice also names selected components. Disposable fixtures
cover no-write previews/refusals, unchanged apply, repeated apply and an intervening
write during apply. No real receipt, migration or service restart was performed.

## Mixed Game-log records (2026-10-18)

E10-S32's member rules (decision G of the member template) are built: phase 4
of private by default, before User5's invite, without the `games` switch (it
comes with E10-S28's switches, so for now no game is public).

**Who sees a record.** A game is seen by the spaces of its two sides, a
sideboard plan only by its deck's space (`play_records._owner_ids`;
`sees_play_record` had already lost its admin branch with E10-S29). A plan
of User2's deck against a home deck is User2's alone, and home's plan
against his deck is home's alone.

**What's sent** (`play_records._view`, the same for `GET /api/play`, every
preview and every save's answer): a side whose deck the viewer may not see
is `{"hidden": true, "title": "one of the home decks", "player",
"mulligans"}`, with no id, list, hash or sideboard plan; another space's side
the viewer may see (a public deck, later) has no plan; and a game's notes,
its `space` and who saved it last ("someone") show only to the space that
recorded it. A plan's hidden opponent is `{"hidden": true, "title"}`. The deck
filter (`?id=`) matches only decks the viewer sees, so it can't tell which
hidden deck a game was against. Each game entry carries `can` (`sides`,
`result`): what the viewer may change.

**Saving** (`_game`, `_sideboard`, `_save`):
- A game stores the space that recorded it (`space`). One saved before this
  rule counts as its home side's (games were recorded on home's page then),
  else its first side's.
- Each side is changed only by its own space: a hidden side goes back as
  `{"hidden": true}` and is kept as stored; another space's side may only be
  sent back unchanged. Anything else is 403 (`SIDE_MESSAGE`).
- The date, result and notes are the recording space's: another space sends
  them back as shown (the notes blank), else 403 (`RESULT_MESSAGE`).
- A plan's deck must be the writer's own space's (403 otherwise); a hidden
  opponent is kept when the plan is revised. play.record is asked over a
  plan's own-space decks only, so another space's opponent never makes it
  writable.
- Every deck a body names is checked with `guard.require_sees_deck` for the
  writer before a stored snapshot is reused, so naming a deck the writer may
  not see answers 404 "No deck X" and nobody records a game or plan against
  a private deck.
- A record the writer may not see, or a missing one given a sha256, answers
  404 "No play record" before its hash or checks are looked at.

**Activity.** A play_record row names a deck the viewer may not see only by
its space ("one of User2's decks"), a plan's row is its deck's space's only,
and the change set's message ("Save game A vs B", which names both decks)
shows only to viewers who see every deck the record names, its own saver
included (`activity._play_owners`, `_hidden_title`, the row's `_masked`). Who
saved a game is named only to the space that recorded it (and to the saver),
as the Game log's "someone": anyone else gets `actor` null and "someone"
(`_play_recorder`, the row's `_anonymous`).

**The page** (`web/play.js`): a hidden side shows its words and its
player's mulligans with no recorded list; **Correct this game** shows only
when something is the viewer's to change, and its form offers only the
viewer's own side (the other as text, sent back as shown) and locks the date,
result and notes unless their space recorded the game; a plan against a
hidden opponent keeps it when revised. The deck page's Sideboard plan
(`web/deck-sideboard.js`) offers each plan against a hidden opponent as its
own choice ("one of User2's decks (private deck; plan saved <date>)"),
since such opponents have no id or version to tell apart, and checks only the
deck's own list for a changed-list warning, as the Game log does.

Tests: `test_play_records.py` (`PlayMemberRulesTests`; `PlayViewerTests`
now puts its mixed records straight into the store, since nobody can record
them through the page any more), `test_activity.py`, `test_play_ui.py`, `test_deck_sideboard_ui.py` and
`test_deck_alias_reads.py`.

## The roster, settings and simulations are seen per viewer (2026-10-18)

E10-S38 and E10-S34's settings GET and simulations wording are built together:
part of phase 4 of private by default (the member template's order, decisions
C and F), without the switches yet, so nothing is public.

**The roster (E10-S38).** `GET /api/profiles` (`settings.profiles`) was every
profile's id, name, role, space and `plays_as`, to anyone. Now:
- a named viewer gets their own space's profiles in full (Matt and User1
  home's two, as before; User5 only himself), then each profile of a space with
  something public by `{id, name}` only (`settings._public_spaces`, E10-S28's
  `guard.public_deck_spaces()` hook: none yet);
- `"admins"` holds the admins' display names only, the one name a member is
  told, for "ask Matt" wording (empty in an older config where everyone is an
  admin); the page keeps it (`keepRoster`, `adminWords()` in `web/core.js`),
  and the login-without-a-profile notice asks by it instead of a hard-coded
  "Matt";
- a script naming nobody gets everyone, the home page before **Who are you?**
  the home profiles its chooser offers, a login that isn't set up nobody; the
  page asks again after each pick at home, now that the header names them.

The page's other readers of the roster (the space names, who plays a deck, the
Game log's second player, the avatar's colour) only ever needed the viewer's
own space's profiles.

**Refusals name no space or person (E10-S38, with E10-S29's wording).**
- Home's collection and tokens answer "That collection isn't public." as any
  space's do (`guard.inventory_hidden`); home's records "The shopping list,
  deliveries and packing plan are private." (`guard.INVENTORY_HIDDEN`); the
  accessories "The sleeves, deck boxes and playmats are private."
  (`permissions.ACCESSORIES_PRIVATE`, `guard.ACCESSORIES_HIDDEN`, and the
  page's notices for Sleeves & boxes and Shopping); Commander-night notes
  "Commander-night notes are private."; a member's new deck at home "You can
  only add decks to your own collection."
- A new deck, or a draft check of one, in a space whose decks the viewer can't
  see and in one that doesn't exist answer the same 403
  (`drafts._new_space`, `guard.HIDDEN_SPACE`), so "Try a change" no longer
  works a draft in another space (it never had that space's pool).
- A deck id in a space that doesn't exist answers the missing deck's 404, "No
  deck '…'" (`library.check_deck_id`); the 400 naming the space goes only to
  a script naming nobody.
- Another profile's wishlist or settings and a profile that doesn't exist
  answer alike: each asks its permission before looking the id up.

**Settings (E10-S34).** `GET /api/profiles/<id>/settings` answers only the
viewer's own id, with no admin override (Matt is refused User1's), and any for
a script naming nobody (`settings.own_settings_id`): 403 "You can only see your
own settings." (`SETTINGS_HIDDEN`) otherwise. The matchup and field pages'
defaults (`?profile=`) are read only from the viewer's own settings. PUT keeps
its rule (an admin may change his own space's profiles' settings), but its
answer to anyone `own_settings_id` refuses is only the keys sent, as saved (an
empty PUT `{}`), so a write that changes nothing reads no one's settings.

**Simulations (E10-S34, decision F).** `GET /api/simulations` gives a member
only `mode`, `may_start`, `why_not` and `may_edit`; `by`, `since`, `workers`
and `max_workers` go only to whoever may change it (an admin, a script). The
reason names nobody: "Only an admin can start simulations right now. Saved
results still show." (`RUNS_ADMINS_NAMED` and `_admins_words` are gone).

Covered by `test_roster_privacy.py` and the updated `test_api_permissions.py`,
`test_server_access.py`, `test_wishlist_server.py`, `test_accounts_ui.py`,
`test_editor.py` and `test_api.py`. Left over: on the home network a header or
`?profile=` naming a person's profile gets "Sign in through decklab.example.com"
while a name config.json doesn't list is left to the route (E10-S35's rule:
only the home Wi-Fi can tell the two apart; refusing both would change the
400s and messages a malformed or unknown name gets, so it was kept); the rest of E10-S34 (Activity)
after the invite.

## The page's code names nobody (2026-10-18)

E10-S39, part of phase 4 of private by default (the member template's
order). Anyone signed in can read the page's JavaScript, so it now holds no
household name, home deck title, real order or real result:
- Examples and comments in `web/` use neutral names (Alex and Sam at home,
  Jordan in a space of his own), decks (Boros Burn, Dimir Control, "Krenko,
  Mob Boss: Goblin Horde"), orders (Example Games, `2026-01-05-examplegames`)
  and precons ("e.g. Goblins").
- Words a reader sees: the unknown-login page asks by `adminWords()` (the
  admins' names E10-S38's roster sends) instead of a hard-coded Matt; the Commander night settings say "Everyone at home sees
  these notes"; the tempo caveat and the team pump measurement name no deck
  and no win rate ("going first helped much less in a tempo mirror than in a
  ramp mirror"; "put a go-wide deck 12 to 15 points too low"), changed in
  `lib/forge/cli_output.py` too, since `test_forge_trust` keeps the page and
  the command line word for word. The pilot box's special case for the
  measured deck went with its name: every deck's box says the same sentence.
- `tests/test_web_no_personal_data.py` reads every file the server serves
  from `web/` (`server_http.static_files`, the icons as bytes too) and fails
  on any configured profile's id, name, display name, space or email and on
  the household's deck titles, whole words in any case; its allowlist is
  empty. The titles are every deck text's in the test fixtures, every deck
  file's in the `pre-db-decks` tag, every deck's in a database export when
  `DECKLAB_DECK_EXPORT` names one (a `deck pull --all -o DIR` folder), and a
  list in the test for the rest (every title the decks' history has held),
  each Commander deck's commander and theme alone too.
- Kept as logic: `"user"` / `"wife"` (Played by values), the Beginner Box's
  `product/fdn-beginner-box/` ids, and `decklab.example.com` in comments.
- Checked: the served files hold no email address, the icons no text chunks,
  and `index.html` and the manifest only Deck Lab's own name.

## Collections and tokens are seen only in their own space (2026-10-18)

E10-S29 and E10-S43 are built together: phase 3 of private by default (the
member template's order, after E10-S36's `collection add-precon --space`),
without the switches yet. Both change `lib/permissions.py`'s rules.

**The admin narrowing (E10-S29).** The admin role opens nothing in another
space, for reading or writing, on the page and through the API:
- `permissions.sees_inventory` / `inventory_spaces` lost their admin branch:
  a space's collection and tokens are seen only by its own profiles (home's
  by Matt and User1, User2's only by User2), a script naming nobody
  every space's. Home's records (orders, products, watchlist, checks,
  receipts, the packing plan) are a rule of their own,
  `permissions.sees_home_records` (`guard.require_sees_home_records`, `"may"`'s
  `see_home_records`): the home profiles only, never shareable, so they stay
  home's once E10-S28 lets home's collection be public. Shopping, receipts,
  products, the packing plan, the product kit and the order and queue
  writes ask it.
- `permissions.reason`: an admin passes only in his own space: every deck
  there (any Played by), new decks there, its collection and tokens, its
  tables, games with one of its decks, and (a home admin) the receipts,
  orders and products. Wishlists and settings are each profile's own, and an
  admin's also those of his own space's profiles (User1's, as before), none
  of another space's (`permissions._profile_space`). A script naming nobody
  still passes everything.
- `sees_play_record` lost its admin branch, so the Game log keeps Matt to
  games with a home deck, and Activity's settings and play-record rows keep
  a named admin to his own space (`activity._named_space`); its inventory
  and deck rows already followed `inventory_spaces`. A change set whose
  every row the database left out for him (another space's, `raw == []`
  with a `total` above 0) is hidden whole, and a change set reaching beyond
  the rows he sees shows its message and reason only when they're his own
  words (`activity.visible_change`). The rest of Activity's "all" scope for
  an admin (system tables, change sets with no rows at all) stays for E10-S34.
- `/api/deck/find` with a space named outright needs that space's inventory
  (`guard.require_sees_inventory`), so a hidden space answers as a missing
  one does instead of a 200 with no counts.
- `summary()` (`GET /api/me`): an admin's `spaces`, `deck_spaces` and `create`
  are his own space only; `web/core.js`'s `deriveMay`, `inventorySpacesAs`,
  `canEditSpace`, `canEditDeck` and `canEditDeckId` lost their admin "yes",
  and the Shopping, Receive delivery and Build decks routes ask
  `see_home_records`.

**Refusals name no space.** A person's space the viewer can't see, one
config.json doesn't list and one that doesn't exist all get the same 403,
"That collection isn't public." (`guard.COLLECTION_HIDDEN`; home's keeps its
words), with only `{"error"}`: `collection.space_param` answers a missing
space so to anyone named (only a script naming nobody gets 404 "No space").
The collection, import, tokens and precon writes ask the read rule first
(`guard.require_space_write`), so a write to a hidden space answers that 403
before its sha256 is looked at, a stale one included. `GET
/api/precons/preview` needs `collection.edit` there too, so Matt is refused
User2's before any deck id is probed.

**Inside the answers (the phase-2 deferrals).** A deck is named only to a
viewer who may see it (the sixth rule), else "one of the home decks" with no
id or link, hidden ones merged so their number isn't told either: the
Collection page's holders (`collection._holders`), the Tokens page's `uses`
and `missing` decks (`tokens._seen_use`, `_seen_gap`), and a held space's
warnings and unknown cards on the Tables out of date list
(`saving._seen_warning`, `library.visible_unresolved`). The pool now says
which deck each warning is about (`pool.Pool.warning_decks`, filled by
`_built_in_use`), so `library._load_pool` and the Collection page pass on a
deck's warning only to whoever sees that deck, and home's warnings about its
orders, products and status lines only to whoever sees home's records
(`library.visible_warnings`); an unknown card is named only with a place the
viewer may be told (`library.visible_place`). The Tokens page's pending
token orders and their problems go only to home's records' viewers. The
card finder (`/api/deck/find`) treats a hidden deck's `id` as none, so
`pool.self_ids` isn't read for it, and the printing picker, card search and
"Paste a list" count the viewer's own space's pool, never another's
(`card_lookup._pool_counts`). Without switches a viewer who sees a
collection is in its space and sees its decks, so these matter once E10-S28
makes a collection public while its decks aren't; the tests patch the deck
rule to check them now.

**Home members (E10-S43).** `collection.edit` and `tokens.edit` pass for any
profile in the space, so User1 changes home's collection and tokens as Matt
can: single cards, imports, Add a precon (its deck Played by her) and the
Tokens page, each one change by User1. Receipts, orders, products and the
watchlist stay a home admin's; another space's member stays out. The
Collection and Tokens pages' read-only notes for home now say "the people of
the home collection".

**Tests.** `test_inventory_privacy.py` covers each criterion (the hidden and
missing space's one 403, every write refused with only the error, a stale
sha256 too, User1's saves, imports and tokens, the deck names inside the
answers, the pool warnings and unknown cards, the held spaces, the finder,
the picker's counts and a member's Activity rows). Tests that assumed the
admin override now expect the new rule: `test_permissions.py`,
`test_api_permissions.py`, `test_collection_edit.py` (a member's imports are
the member's), `test_precons.py`, `test_activity.py`, `test_inventory_ops.py`,
`test_script_rule.py`, `test_server_access.py`, `test_access.py`, `test_play_records.py`,
`test_deck_readers_p4.py`, `test_collection_ops.py`, `test_receipts_api.py`, `test_reprints_api.py`,
`test_api_accessories.py` and the UI fixtures (`test_accounts_ui.py`, `test_deck_rename_ui.py`,
`test_deck_retirement_ui.py`, `test_deck_kit_ui.py`); the goldens skip `Pool.warning_decks`.

**Left for later phases.** The deck page's `on_the_way` labels still name
the order or product to whoever sees the deck's space's inventory (only home
profiles, until a collection can be public): E10-S28 with the switches.
Activity's remaining admin scope (system rows, change sets with no rows):
E10-S34. The Game log's member
rules for mixed records: E10-S32. E10-S29's "phase 4 gates before 5b"
criterion no longer applies (5b retired the gates on 2026-10-14);
`sees_inventory` keeps its name as the one collection rule.

## A precon from the command line (2026-10-18)

E10-S36 is built: the first story of phase 3 of private by default (the member
template's order), so that once the page lets nobody write in another's space
(E10-S29) a member's precon is still upkeep Claude can do when asked (decision
D: counts and "done" passed on, never the list).

**The command.** `python -m decklab.db collection add-precon CODE [--space S]
[--title T] [--played-by user|wife|either] -m "..." [--dry-run] [--actor P]`
(`db/inv_collection.py`), and `collection precons [WORDS]` to find a CODE
(MTGJSON's file name, as the page's search lists them).

**One path with the page.** `lib/api/precons.py`'s `add_precon` was split:
`plan_add(space, file, title, fields, profile, author, sha=None)` does every
check and works out everything that's saved (the precon's rows, the deck's text
with its table worked out against the collection as the import leaves it, the
`precon.add` operation and the page's message) and writes nothing. The page asks
its permissions, then saves the plan through `saving.apply_op`; the command
passes no profile (a script naming nobody: the command line writes every space)
and saves it with `inventory.apply` under its `-m` message, as one change set by
Claude or the `--actor`, whose name goes in the deck's Notes ("Added in Deck Lab
on ... by Matt"). `drafts._new_fields` takes a missing profile (no `plays_as`).
So the cards, the deck text, the table and the refusals are the page's word for
word (a test compares the deck the page makes with the one the command makes).

**What it says.** `--dry-run` prints the cards to add (plain basics left out),
what's left out (basics, a display commander), the deck it would make (id,
title, kind, section counts) and its token cards, and saves nothing. A title
whose deck name is taken in that space is refused, at the dry run too, naming
the existing deck and suggesting `--title`; one taken during the change refuses
it whole (no cards added). At home `--played-by` sets Played by, else the
`--actor`'s `plays_as`, else none; in a person's space `--played-by` is refused.
After a save it names other decks whose tables are now out of date (as
`collection merge` does), and its last line is "Added 5 cards (3 new rows) to
User2's collection and made user2/commander/ghalta-test-dinos." Exit codes
0 done or previewed, 1 refused, 2 the database can't be reached.

Covered by `test_precon_cli.py`; `test_precons.py` still covers the page.

## Decks are seen only in their own space (2026-10-18)

E10-S30 is built: phase 2 of private by default (the member template's order),
decks private to their space without the switches yet. It was built in two
halves in parallel (the library and deck pages; the other readers, the writes
and Forge) and merged the same day into one design.

**The rule.** `permissions.sees_deck(profile, space, *, script, public,
home_only)` and `permissions.deck_spaces(profile, ...)`, asked through
`guard.sees_deck(target, profile)` (target a deck id, a library summary or a
DeckFile; profile left out means the viewer, or the writer for a write).
A deck is seen in its own space only: home's decks, product decks and Beginner
Box pairings by Matt and User1, a person's by that person. The admin role opens
nothing, so Matt no longer sees User2's or User5's decks on the page. A script
naming nobody sees every deck; any other request naming nobody, and a login that
isn't set up, none. E10-S28's switches extend it with one lookup,
`guard.public_deck_spaces()` (empty until then), and an ordered or preordered
product's decks never leave home even then (`guard._home_only`, read only when
it could matter). One set of guard helpers: `guard.no_deck(id)` (the 404),
`require_sees_deck(target, profile, deck_id=)`, `deck_reader(profile)` (the rule
for one viewer, worked out once, for a list) and `visible_decks(items)` over it,
and `hidden_deck(target)` ("one of User2's decks").

**A hidden deck answers exactly as a missing one**, 404 "No deck
'casual/gruul-ramp'" with nothing else (`guard.no_deck`): one body for a deck
that never existed, one retired from another space (history's "No retired deck"
became it), one in a space that doesn't exist (the old "there's no space"
wording is gone) and one that's hidden. It's asked before anything of the deck
is read and before any 403 or 409:
- `library._find_summary`, so `GET /api/deck` (its stats, guide and usual
  opponents), `/api/deck/edit`, `/api/deck/cards` (the cover picker),
  `/api/deck/opponents`, `/api/goldfish` and every reader built on it or on
  `_deck_sections` (the field, a deck's matchups);
- the readers that bypass it: the history and revisions
  (`deck_aliases.canonical_id`, by the id, so a retired deck by its former
  space, before any revision lookup), the opponents view, the rename and retire
  previews, the editor's snapshot, rankings rows (worked out over the viewer's
  decks only) and the variant tests list;
- every write, before the permission and the conflict: `commits._stored` and
  `_conflict` (save, cover, check, tables/update, stand-ins, opponents) and
  `deck_aliases.reject_alias` (rename, retire, restore), so a 403, a 409 or who
  changed a deck never reaches someone outside its space. `retirement._current`
  validates the id first, so a malformed one is still 400.

**The lists.** `GET /api/decks` filters the library first, so `halves`,
`usual_opponents`, `aliases`, `edited`, `revision` and the counts are worked out
over visible decks only; its `decks_revision` is the viewer's own
(`library.viewer_decks_revision`, a sha256 over the visible decks' ids, titles
and text hashes), and `GET /api/matchups` gives the same value, so the Matchups
page's comparison still holds and a save of a deck you can't see doesn't move
yours. `GET /api/play`'s `lists` and `decks` are filtered before any snapshot is
taken, so no warning names a hidden deck. The Tables out of date list
(`/api/tables/stale`'s `stale` and `blocked`) and a save's `stale_tables`
(`commits._stale_list`, the Collection page's list included) keep only decks the
viewer sees as well as the inventory rule: Matt was listed User2's stale decks
(seeing his collection as the admin), may_update true, and Update all then
failed whole on their 404. Visits keeps no deck id from a beacon for a deck its
requester may not see, and the panel shows a deck the viewer may not see as "one
of User2's decks" with no id. A member's library adds "Nothing else is public
yet." when nothing outside their space is listed; a deep link to a hidden deck
shows the existing "No deck" error page.

**Forge, coarsely** (`forge_runs._Seen`, until E10-S31 follows the rule
exactly): `/api/matchups`, `?running=1`, `/api/matchup` (by decks; by key, 404
"There's no saved matchup at that link") and the deck page's matchups keep only
results and runs whose every side is seen (a side by where it was last played);
`/api/variant` and `/api/variants` only tests whose deck and every named
opponent are; `/api/field` only the opponents and field lists seen, with its
average, rating, notes and budgets left out while any is hidden (planned over
the whole field, the budgets told its size), and a field with hidden decks isn't
played or tested against. A field run's job and saved last-run note are kept by
the list's card_sha, so another space's deck with the same list (a copy of a
home precon) was shown the home run: `/api/field` shows a job only when
`_Seen.coordinator` sees it and a last run only when its deck is seen, and a
matchup a hidden field run or test is playing doesn't name it
(`_coord_progress(shown=False)`). `by`, `stopped_by`, `cancelled_by` and the stop
notices name a profile of another space as "someone". Interim rule until
E10-S31: only an admin stops a run (`run.stop`). An admin's running list shows
runs he may not see as "A run of a deck you can't see" (no decks, no names), and
stopping one answers only `{"key", "stopped", "hidden"}`; `POST /api/field/stop`
by a deck id answers 404 for a deck he may not see (before the 403) and stops
only a run of that deck, never another space's run of the same list. The page
shows Stop (matchup, field run, test of a change) only to an admin
(`mayStopRuns()` in `web/core.js`).

**Tests.** Those that read another space's deck now expect the 404, or make that
space's decks public with `guard.public_deck_spaces` patched (the R6d tests: a
public deck whose collection isn't, where R6d still applies).
`test_deck_visibility.py` covers the rule, the library, the pages' 404s, the
Game log's decks and Visits; `test_deck_privacy_readers.py` the bypass readers,
the write order, the Forge filter, run.stop and the field stop.

**Review fixes (the same day).** A new deck is made only in a space whose decks
its maker sees (`saving.require_sees_space`, 403 before `deck.create` and the
name lookup): Matt could create one in User2's space, which then answered 404,
and its 409 told him whether User2 had a deck of that name. The precon add
goes the same way, and its preview's `exists` and `editable` follow the rule.
Rankings now fit, rank and count games only over saved results whose every side
(its id and `seen_as` aliases) the viewer sees (`rankings._seen_result`, passed
to `field._bt_data(keep=)`), not only the rows. Visits merges a space's hidden
decks into one row per route (opens summed, newest time kept), so it doesn't
tell how many were opened.

**Left for later phases.** The Collection page's holders, the tokens' `uses`
and `missing.decks`, the card finder's `self_ids` and the pool warnings in a
blocked space's held note (`stale_view`'s `held`) still name decks to whoever
sees that collection: E10-S29 (phase 3) gives them the deck rule. The Activity
page's deck rows: E10-S34. The Game log's records (an admin reads every game
and sideboard plan, a member a record's other-space side, with each side's
stored list snapshot, and an edit keeping a side reuses it unchecked): E10-S32's
member rules, which also drop the admin branch. Forge following the rule exactly (a starter stopping
their own run, fields of the decks one sees): E10-S31.

## Only scripts read everything, and the home chooser offers home profiles (2026-10-18)

E10-S35 is built, the first story of private by default's phase 1. "Naming
nobody sees everything" now holds only for a script: code outside any request
(job threads such as the Forge coordinator and goldfish, tests) or a request
on the home listener from this PC's loopback (`127.0.0.1`, `::1`) that sends
`X-Deck-Lab-Script: 1` and names no viewer (`access.script()`, set by
`server_http` around each request; `guard.script()`). The tunnel's listener
is on `127.0.0.1` too, so the header gets nothing there. Any other request
naming nobody, a phone on the Wi-Fi or the PC's browser before a profile is
picked, is refused every write and sees nothing private: no collection,
tokens, wishlist, accessories, Shopping, receipts, packing plan, Visits or
Activity rows, and `/api/me`'s `"may"` is nobody's. Decks stay open until
E10-S30. `permissions.py`'s `local=` keyword is now `script=`, and every call
site that meant "naming nobody" (history, commits, dbstatus, visits,
simulations, the editor, Activity, opponents, rename, retirement,
Commander-night notes, the Game log) asks `guard.script()`; `guard.local()`
still means only "not through the tunnel" (`viewer()`, the audit's "via").

"Who are you?" lists only the home's profiles (`homeProfiles()` in
`web/app.js`; `?profile=` and a remembered profile pick only those). On the
home listener a request naming a profile outside the home, by
`X-Deck-Lab-Viewer`, `?profile=`, an accessory picture's `?viewer=` or a
write body's `"profile"`, gets 403 "Sign in through decklab.example.com" on
every route, so nobody at home can read a member's space by picking their
name. The other members sign in through decklab.example.com, from the home Wi-Fi
too: check each one's email is in the Access policy. The refusal is JSON under
`/api/`, and a short page for a page address (an old `/?profile=user2`
bookmark). While `config.json` can't be read nobody named can be told apart, so
every route but `/api/status` answers its 500.

`GET /api/me` answers at home for the profile the viewer header names, with
that profile's own `"may"`, as it does for the login through the tunnel; the
page asks for it again on every pick, and `deriveMay` in `web/core.js` is only
its fallback for an older server (with nobody chosen it now gives nothing,
matching the server). `forge-trial/overnight_legs.py`
sends the script header; `homenet status` and the tunnel probe need nothing
(`/api/status` still answers everyone). The tests' HTTP helpers send it by
default (`test_server.py`), and `test_script_rule.py` covers each criterion.

## Choosing a deck's kit needs deck.edit (2026-10-18)

E10-S42 is built. `POST /api/accessories/assign` checked only `accessories.edit`
and the kit's owner, so User1 could set, clear or move the sleeves and deck box
of an `either` deck through the API, though the page hides that. It now needs
`deck.edit` on the holder deck and on the deck a move takes them from (403 with
permissions' words, "You can change the home decks played by you."), checked
before anything is worked out and again inside `kit.set` under the inventory's
lock, for the `editor` the route passes, since a move's source has no sha
check. A product kept intact keeps the rights its kit had (either home profile,
the shared kit, home's inventory to see): the story's "the product rights" was
read as those, not the admin-only `products.edit`, which would take away the
product kit choice the page gives User1; that reading awaits Matt's
confirmation. The editor save, a new deck and
assembly completion already needed `deck.edit` or `deck.create`. The kit
picker (`pickKit` in `web/accessories.js`) offers a move only from a holder the
viewer may change (`canEditDeckId`, the library loaded if it isn't yet), so
User1 shares an `either` deck's sleeves rather than being offered a move that
would end in the 403.

## The "Deck Lab is off" Worker, and the user-testing checklist (2026-10-17)

E11-S02 is built and deployed (partial until a signed-in check). A Cloudflare Worker in
`decklab/cloudflare/` sits on both hostnames' routes behind Access and passes
every request to the PC unchanged (headers, the Access login, the body;
redirects not followed). When Cloudflare answers for the PC (530, 502-504,
520-523) without Deck Lab's new `X-Deck-Lab-Origin` header, it answers a plain
"Deck Lab is off" page instead (503, no-store, retrying every 30 seconds), or a
503 JSON with reason `off` under `/api/`. The page's loader waits on that
reason under "Deck Lab is off". Deck Lab's own 502s and 503s (the database
down, the card data loading) carry the header and pass through. It was
deployed on 2026-10-17 through Cloudflare's API: the committed files, checked
by hash, with both routes set to fail open and no workers.dev or preview
address. Access still answers first, a forged login cookie included. Still to
check, signed in on a phone: a deck save, a photo upload, and the off page
with Deck Lab stopped. It's a
Worker because Cloudflare's Custom Errors need a paid plan (and whether they
cover 1033 is unconfirmed), and a static page couldn't answer `/api/` or reopen
Deck Lab by itself.

E11-S28's session checklist is prepared in
[design/user-testing-user2.md](design/user-testing-user2.md). The session
itself and its follow-up review are still to do.

## Main-only builds, partial sideboards and retained deck intent (2026-10-16)

E4-S24 and E5-S23 are built. Build decks always includes the complete selected
main deck, with **Main deck only**, **Main deck + whole sideboard**, or **Choose
sideboard cards** for explicit quantities. Commander and Companion sections
remain included. Missing omitted sideboard copies do not block a usable main
build. These are desired final recipes: reducing an already assembled sideboard
requires checked Put back actions and a final review naming the removals. Basic
lands and anonymous spare stand-ins have return tasks too. Adding sideboard
copies later keeps unchanged main cards rather than pulling them again.

The physical recipe is a protected `Assembled` JSON header in the deck's existing
database text: its selected version and exact logical section lines. Installed
stand-ins determine the named physical cards it reserves; spare markers count
toward kit capacity without becoming owned inventory. The intended Planned and
Play-now lists stay intact. The pool, accessory holders, sleeve warnings, editor
kit count and built token summaries use the actual snapshot. Opening a deck or
receiving a real card never changes its assembled cards.

Every actual packing save records a snapshot. Older built decks still infer
their complete built list; an ordinary edit to that active list first freezes
the previous physical recipe. Once a snapshot exists, a generic text save
cannot drop or replace it, change its built version, overwrite its installed
markers or reset its physical generation. The existing take-apart flow clears
installed assembly and markers while preserving intended lists and saved marker
choices. A retained `Assembly generation` counter invalidates shared checks
across take-apart/rebuild and marker changes, including a return to the same
recipe. Participant and donor task identities include the chosen recipe;
sorting the same plan keeps checks and Undo.

**Still intended for this deck** names sections, cards, intended quantities,
real assembled copies and remaining real copies. Missing and incoming quantities
are separate; owned-but-omitted cards do not become purchases. Real cards
represented by stand-ins retain their intent. Unknown availability stays
unknown. Packing and a built deck's Overview show the details, and the library
shows physical main/sideboard counts, with the existing inventory privacy rule.
The full intended lists still drive Cards, Prices and Shopping. No new wishlist
structure or automatic purchase-queue changes were needed.

Selection quantities enter the plan fingerprint. Permission, exact-deck hashes,
inventory/deck revisions and final combined allocations are checked in the same
atomic build transaction. Old requests cannot silently broaden a partial build.
Stand-in choices outside the selected recipe remain saved without duplicating
copies; selected mappings retire on explicit replacement as before. Invalid
snapshot metadata makes reservations unconfirmed rather than falling back to a
guessed full list. Bulk confirmation names the physical recipe and leaves the
separate build review intact. Products remain complete and read-only. A partial
main deck or sideboard-first build is not offered.

Verification uses temporary FileInventory/MemoryStore data and browser fixtures,
with no live builds. The 56 new feature tests cover parsing, physical/desired separation,
same-name main/sideboard copies, quantities, explicit returns, marker conservation,
scope/fingerprint tampering, concurrent writes, raw-save protection, privacy,
legacy edits, take-apart/rebuild and the UI. An 80-test focused group passes in
23.369 seconds; independent 440- and 156-test regression groups and 129 UI/web
checks pass. The 13 new golden-normalizer boundary tests keep partial scopes,
snapshot generations, retained intent, actual allocations and privacy leaks
observable; 19 compatibility checks, including the original file and PostgreSQL
reader goldens, pass in 10.045 seconds. Original golden fixtures stay unchanged.
The first full run executes 5,415 tests in 1,007.835 seconds with 31 skips and
33 failed golden subtests in two test methods, from the additive API metadata.
The narrow normalization above resolves those comparisons without masking
allocation changes. The final full run executes 5,431 tests in 1,119.444 seconds:
5,400 pass and 31 skip, with no failures or errors. Evidence is in the scratchpad's
`decklab-sections-full-final.log`, `decklab-sections-new-focused-verified.log`,
`decklab-sections-goldens-final.log` and `decklab-sections-lengths-final.log`.
The older backup-cleanup permission failures recorded below remain historical
observations; this batch does not claim to fix them. Story counts and the exact
TODO delta reconcile. The source audit
covers 632 owned files with the same two unchanged files over 1,200 lines. No live
database migration or data write, server restart, push or deployment was performed.
Physical-device, User2, date and real Forge gates remain open.

## Bulk packing card checks (2026-10-16)

E4-S23 is built. Each displayed deck in Build decks offers **Tick all card
checks**, naming its Planned or Play-now list, check/copy counts and **All
listed sections, including any sideboard** scope. It checks that deck's
unchecked card actions: pulls, transfers, basics, spare stand-ins and returns.
Other decks, optional sleeves/box checks, tokens and untickable missing/waiting
rows stay unchanged. Individual checks remain available. Undo changes only
this action's additions, preserving earlier checks and later individual edits on this device;
changing card order keeps Undo usable for the same plan.

The action uses one deduplicated patch through the existing shared-progress
endpoint. Per-task local edit generations protect Undo from newer local edits;
same-task changes across devices retain the existing last-write behavior.
Bulk confirmation waits for shared progress to load and save and is disabled
during a poll, error, new preview, build review or build save. Detached controls,
changed plans, viewer changes and navigation cannot apply an old action. Undo
can queue behind its own in-flight save without a stale acknowledgement
checking the cards again.

Checking progress does not build a deck or make missing cards available. The
separate final review, edit permissions, plan fingerprint and atomic physical
availability checks remain. Main-deck/sideboard independence and retained
missing-card intent stay open as E4-S24/E5-S23; their design choices are unchanged.
No backend, endpoint, schema or migration change was needed.

Verification uses isolated inventories, MemoryStore and browser interaction
fixtures, with no live builds or inventory changes. The 12 new UI scenarios and
three new build-safeguard tests pass. Independent review passes 65 focused UI
tests; the complete packing/permissions/web group passes 261 tests in 38.102
seconds. Whitespace, story counts and the exact TODO delta pass. The source
audit covers 623 owned files with the same two unchanged files above 1,200
lines. Full discovery ran **5,362 tests in 1,060.351 seconds: 5,331 passed and
31 skipped**, with no failures or errors. Logs are
`Temp/decklab-packing-bulk-focused.log`, `Temp/decklab-packing-bulk-full.log`
and `Temp/decklab-packing-bulk-lengths.log`. The earlier forced scratch-database
cleanup permission failures remain recorded in the Commander-night and rename
entries below; this passing run does not establish a fix. No backup code,
database privileges or unrelated processes were changed. No live migration,
server restart, push or deployment was performed; physical-device acceptance
remains E2-S22/E2-S04.

## Private household Commander-night notes (2026-10-16)

E9-S20 is built. A home admin records one usual Commander night in Settings:
its name, optional venue, household target bracket, published venue range,
house-rule notes and the date checked. Unknown brackets, ranges and dates stay
unknown; no venue facts or checked date are seeded. A home Commander deck page
shows this record beside its own declared aim, including when card checks or
inventory calculations are unavailable. Notes do not alter decklists, rule
checks or simulations, and a matching number is not a power-level assessment.
The notes are plain text for the pregame conversation, with their checked date
or an explicit unknown. With no record the panel is absent; a storage failure
is shown as unavailable rather than claiming nothing was saved.

Migration `0011_commander_night.sql` adds a dedicated audited singleton, rather
than repurposing a person's settings or saved games. Each complete-record save
checks its expected revision under the transaction lock. An unchanged save adds
no audit change. Removal requires a reason and explicit UI confirmation, and
keeps the row's revision so a stale editor cannot overwrite a clear/recreate
cycle, even when identical notes are entered again. Memory and PostgreSQL stores
share validation and rollback semantics. Unicode limits and the endpoint's
8 KiB body limit cover full-length supplementary characters.

Only home viewers read the record, and only home admins edit it; an admin in
another space does not override that privacy. Non-home deck pages receive no
household projection. Activity shows home viewers a generic update/clear summary,
without raw note content. Mixed changes containing hidden notes also hide their
message and reason, including when a later kit-actor rule would otherwise allow
the words. The same composition fix protects mixed private-wishlist changes.
Settings ignores stale load/save responses after route, viewer or form changes;
a conflict preserves the input until an explicit reload.

Exports retain the content and clear tombstones, backup row counts and content
digests discover the table, and nightly checks validate it in their existing
snapshot. Before migration, exports preserve earlier note exports and the
optional panel reports unavailable. A catalog precheck keeps a missing notes
table from tripping the shared database breaker or disabling older settings.

Verification uses fictional venue notes in temporary repositories, MemoryStore,
disposable PostgreSQL databases, loopback HTTP and browser interaction fixtures.
The 59 new feature tests and the focused state, UI, maintenance, permission,
Activity and HTTP regression groups pass. The first full discovery ran **5,347
tests in 1,063.958 seconds: 5,315 passed, 31 skipped and one failed**, with no
errors. The unchanged `test_backup_and_restore_check_round_trip` reported the
previously documented `permission denied to terminate process` during forced
scratch-database cleanup. Its log is `Temp/decklab-commander-full.log`; no backup
code, live permissions or process privileges were changed in response.
Final full discovery against the frozen compatibility fix ran **5,347 tests in
992.543 seconds: 5,315 passed, 31 skipped and one failed**, with no errors.
`test_a_restore_that_differs_fails` hit the same cleanup permission error;
the final full suite is not green. The whole unchanged backup group then ran
13 tests in 8.990 seconds: 10 passed and three failed with that same error
(`test_a_dump_recorded_without_digests_is_checked_by_its_counts`,
`test_a_restore_whose_contents_differ_fails`, and
`test_backup_and_restore_check_round_trip`). Logs are
`Temp/decklab-commander-full-final.log` and
`Temp/decklab-commander-backup-isolated.log`. Earlier runs and their failures
remain recorded; no cleanup fix is claimed.
The feature's 59 tests pass. Independent review and the 138-test integration
group pass; state/API, UI and maintenance regression groups pass too. The real
pre-migration read/write test confirms that older settings remain usable.
Whitespace and design-count checks pass. The source audit covers 621 owned
files with the same two unchanged files above 1,200 lines. Only E9-S20's story
status and TODO row changed; the emptied TODO section became an owner mapping.
No live note, collection mutation, production migration, server restart,
notification, external message,
venue publication, real Forge run, push or deployment was performed. Device,
User2-testing, October 19 and real-Forge gates remain incomplete.

## Dated reprint details and manual price-review offers (2026-10-16)

E5-S11 is built. Shopping's purchase queue and combined missing-card rows, and a
deck's inventory-visible missing-price rows, show upcoming paper reprints from
the existing cached Scryfall index. Each notice gives the set and listed release
date, the card-data date (or an explicit unknown), the comparison date and the
cache's incomplete announcement coverage. An earlier released physical printing
must establish that the card is a reprint. Digital-only, oversized and
memorabilia printings are excluded; casual format legality is not a filter.
Alternate arts share one set/date group. Upcoming groups show soonest first;
released groups show newest first, with eight of each and explicit overflow.

A Waiting for reprint row offers **Check prices again** when a listed release
date has passed since its saved price-check date. Blank, invalid or future check
dates offer a manual review with their uncertainty retained, without claiming an
old printing is newly released. Unavailable card data also offers a manual
review. The sheet preserves the previous dated shop reference and exact
printing/finish preference, links to paper printings on Scryfall (labelled USD
prices), and copies the card name for looking up current shop listings. Listed
release dates may change: passing one does not prove current shop stock or a
lower price. Opening this offer never fetches prices, changes a queue category,
stamps a check date or creates a notification.

The enrichment is read-only and follows existing inventory visibility. Queue
saves return refreshed optional evidence, including explicit clearing, while a
failure to prepare that evidence cannot misreport an already-saved change as
failed. Refused and stale saves do not prepare it. Sources use fixed Scryfall
hosts and escaped paths/text, and route/profile changes close the review sheets.

Verification covers isolated fictional printing dates, cache failures, release
boundaries, grouping/overflow, canonical card identity, unchanged observations,
permissions, successful and refused saves, and browser interaction fixtures.
The 43 new reprint tests pass (20 catalogue, 11 API and 12 UI), along with the
110-test existing API regression group. Final full discovery ran **5,288 tests
in 1,017.550 seconds: 5,257 passed and 31 skipped, with no failures or errors**.
Its log is `Temp/decklab-reprints-full.log` in Matt's Windows temporary folder.
The earlier rename run's four intermittent scratch-database cleanup failures
remain recorded below; this passing run is not a fix for that problem. Read-only
diagnosis confirmed the failing forced-drop command but did not identify the
backend behind the permission error, so no code or role changes were justified.
The source audit checks 612 owned files, with the same two unchanged files above
1,200 lines; whitespace and design-count checks pass. Only E5-S11's story status
and TODO row changed. No live inventory change, card-data refresh, shop research,
scheduled task, migration, server restart, push or deployment was performed.
Physical-device acceptance remains E2-S22/E2-S04.

## Rename decks with retained history and links (2026-10-16)

E1-S19 is built. A saved deck's **More > Rename deck…** reads its current
title, text SHA and revision. Preview shows the old/new titles and derived ids
within the same space and format. Confirmation checks those values and the
library revision, then repeats permissions and collision checks under the
database lock. A changed preview must be reviewed again. Product decks, pairings,
invalid titles and ids already belonging to another deck or its history refuse
the change. Built saved decks can be renamed because their cards and kit stay
unchanged.

Migration `0010_deck_aliases.sql` adds audited aliases and a per-deck rename
counter. One current deck-row update cascades the id to its text and derived
lines, keeps `kit_version`, and adds one numbered `M` revision. Earlier revisions
retain their ids, text, timestamps, actors, messages and imported git commits.
History reads combine the lineage; retirement/restoration keep it too. Former
ids remain reserved, aliases stay flat, and renaming back to one's own earlier
id is allowed without merging unrelated retired histories. Exports and backups
keep the alias metadata; nightly checks validate its shape and history, and
reconstruct it from exported CSV during the round trip. A schema without this
migration still supports existing reads/saves and explains why rename is
unavailable.

Old deck/history/editor links resolve to the current id, preserving their query
parameters. Purchase sources, private wishlist sources, usual-opponent text and
captured human games keep their original bytes and gain current links or
alias-aware filtering. Saved Forge matchup and variant evidence, hashes and
keys stay unchanged; current links, field membership, variant continuation and
pilot lookup follow aliases. Version-specific pilot settings take precedence;
equally specific canonical-id settings take precedence over former-id settings,
and conflicting settings are reported rather than depending on map order.
An open Matchups page refreshes its library when the deck revision changes,
applies coherent library/result snapshots together, and resolves old selected
deck preferences and Play links through visible aliases.
Inventory and kit visibility, per-revision kit/message redactions and write
permissions continue to apply before conflict/link details are disclosed.

Forms still naming a former id are refused with a current-page link. The editor
keeps their draft and offers explicit recovery; it never silently merges or
discards an old-address draft. A rename confirmation also checks revisions if a
deck is renamed away and back with identical text. Ordinary edits keep their
existing SHA contract: if that exact id and every saved byte have returned, an
old matching SHA may still save, with permissions checked. This does not bypass
the stronger revision guard on rename itself.

Packing task identities include the participant's rename counter, and a
transfer task also includes its donor's counter. A rename requires those checks
to be confirmed again, including title-only changes and A→B→A reversals;
ordinary saves do not reset them. The preview states this. Existing zero-counter
task ids stay compatible. The old hashed ticks are retained as inert progress.
Restoring or recreating a retired identity receives a fresh counter from its
new revision, so the lifecycle cannot revive checks from before a rename.

Verification uses temporary files, mocked browser/server interactions and
disposable PostgreSQL databases, including rollback, rename-back, history,
permissions, private kit, source and immutable-result checks. No live data,
production migration, Forge run, server restart or deployment was performed.
The first full run identified CLI/Shopping helpers without an explicit test
inventory and the newly added default metadata in reader snapshots. The helpers
now use isolated inventories. Golden normalization removes only the library
revision token and matching zero-valued rename metadata; nonzero counters,
aliases, mismatches, allocation counts and privacy fields remain compared.
No saved golden files were rewritten. The fixture corrections passed focused
CLI, Shopping and file/PostgreSQL golden checks.
Final full discovery ran **5,245 tests in 1,029.979 seconds: 5,210 passed,
31 skipped and four failed**, with no errors. All four failures were the
unchanged backup/restore tests reporting `permission denied to terminate
process` during forced scratch-database cleanup. The same whole 13-test backup
group passed separately in 10.139 seconds; it also passed in the first full run.
No roles or process permissions were changed. This existing intermittent
cleanup problem remains outside the rename batch. The full and isolated logs
are `Temp/decklab-rename-full-final.log` and
`Temp/decklab-rename-backup-isolated.log` in Matt's Windows temporary folder.
The source audit checks 606 owned files: no new over-limit files; the unchanged
`editor-screen.js` (1,359) and `test_feature_ui.py` (1,217) remain above 1,200
lines. Physical-device acceptance remains E2-S22/E2-S04.

## Record build-workflow follow-ups (2026-10-16)

Matt's three requested outcomes are now open TODO rows and missing stories:
E4-S23 (bulk packing confirmation), E4-S24 (independent main-deck/sideboard
assembly with an incomplete sideboard), and E5-S23 (deck-associated missing-card
intent retained through partial builds). The stories distinguish physical
completion from retained intent and leave wishlist/build-workflow alternatives
open. Existing progress, completion, sideboarding, personal-wishlist and purchase
request stories were checked for overlap. No implementation or completion is
claimed. The design counts now cover 206 stories: 123 built, 29 partial,
42 missing and 12 not wanted. Existing TODO entries and NOW ordering are retained.

## Retire and restore deck ideas (2026-10-15)

An editable unbuilt saved deck now has **More > Retire deck…**. Its sheet reads
current eligibility, requires a reason and explicit confirmation, then records
one audited deletion. Built decks and decks still holding sleeves or a deck box
are refused with the action needed first. Both the text SHA and saved revision
must still match, including when an id was deleted and recreated with identical
text. The files test backend without durable revisions refuses retirement.

Retired decks leave the library while their History pages, historical lists and
captured matchup results remain readable. History uses the last saved title and
preserves existing per-revision kit and message redactions. Retired revisions
have no current editor state or list-as-draft action. Activity's deletion links
open retained History instead of the missing deck page.

An authorised editor can **Restore deck** from History. Explicit confirmation
restores the exact last saved text under the same id as a new revision, retaining
the earlier deletion. It checks the latest deletion and both snapshot revisions
under the writer lock, refuses an occupied id, rechecks permissions and kit, and
never overwrites a newer deck. Historical built or kit-holding states must be
resolved separately. Existing queue and order sources continue to recognise a
retired deck's durable history; their purchase intent is retained.

The sheets close on navigation, profile changes and the away lock. Late replies
cannot draw into another person's page; successful writes invalidate the library
cache. Verification uses temporary fixtures and disposable PostgreSQL databases,
with no real deck retirement, live data changes, real Forge runs, device
acceptance, deployment or server restart.

E1-S19 is partial: retirement and restoration are built; renaming an id while
carrying its history, source references and matchup links remains in TODO.

Focused verification passes 114 backend/history/source/HTTP checks, 59 UI checks
and 60 web/shell/HTTP checks. The saved-matchup regression retires and restores a
fixture through the real database operations, reads its saved key and captured
sides through the API, and confirms its result bytes are unchanged. The source
audit scans 585 owned files and reports only the two unchanged existing length
violations: `editor-screen.js` (1,359 lines) and `test_feature_ui.py` (1,217).
No changed source exceeds 1,200 lines; `git diff --check` passes.

The final full suite passes **5,101 tests in 937.830 seconds: 5,070 passed,
31 skipped, no failures or errors**. The skips are 30 opt-in real Forge checks
and one malformed file-only fixture that the database cannot store.

## Saved field rankings on Matchups (2026-10-15)

Matchups now offers **Matchups / Rankings** for 60-card and Commander lists.
Rankings shows every current list with its version, the field's selected lists
best first, and reasons for lists outside the field or without a usable rating.
Field membership follows the existing Built-version/Planned choice, intact-product
rules and configured additions or exclusions. Identical Planned and Play now
simulation lists share a row; identical identities across different decks share
their rating without increasing the comparison population.

Each connected group reuses the field's Bradley–Terry model and saved current-engine
games, fitted once for the group. Ratings are estimated win percentages against
an average current field list in that group, balanced for who starts, with 95%
rating and likely rank ranges. Disconnected groups have separate ranks and cannot
be compared. Historical list nodes may connect current lists, as in the existing
field model, but only current field identities count in the rank population.
Changed lists, pilots or engines cannot inherit an old rating. Low direct-game
coverage, uncertain rank ranges and groups containing only one current list remain
unsettled; missing evidence or an unstable fit leaves the list unrated.

The dedicated `GET /api/rankings?format=Constructed|Commander` reads one inventory
snapshot and applies the existing deck-read policy, without returning inventory
counts or kit. Its engine check reads existing files and confirms intended versus
deployed overrides without deployment, folder creation, Java execution or persistent
cache writes. Unknown engine identity stays explicit. Existing callers retain their
normal engine and override behavior.

Ranking reads run only while that view is selected, through the existing foreground
refresh cycle. A changed saved result refreshes promptly; unchanged results are
checked at most every 15 seconds. Reads are single flight, cancel on page or person
changes, and have a 12-second timeout even when a transport ignores cancellation.
Unchanged displays retain focused links and open details; failures remain visible.

Verification uses synthetic saved games, the real statistics code, temporary file
inventories and DOM/HTTP fixtures. No real Forge games, live collection or result
changes, server restart, deployment or observed-device acceptance were performed.

E3-S10 is built and its completed TODO row is removed. The final focused backend
and API batch passes 142 tests; the UI/HTTP/web batch passes 116. The full suite
passes **5,030 tests in 911.884 seconds: 4,999 passed, 31 skipped, no failures or
errors**. The skips are 30 opt-in real Forge checks and one malformed file-only
fixture the database cannot store. `git diff --check` passes. The source-length
audit scans 577 owned files and still reports two unchanged existing violations:
`editor-screen.js` (1,359 lines) and `test_feature_ui.py` (1,217). No changed source
exceeds 1,200 lines.

Known low issue: Outside field includes all 45 theoretical Beginner Box pairings,
even those without saved games. Unselected pairings have no rating and do not
count in the comparison population.

## Receive only the checked copies (2026-10-15)

Receive delivery now records only the ticked rows of each selected cards or tokens
component. **Split copies** separates an arrived quantity from copies still on
the way; the preview names the received and pending components and their counts.
The original component keeps the unticked remainder and its arrival checks. The
arrived copies get a separate received component, with their completed checks
retained as evidence. Products still arrive whole. **Continue pending delivery**
loads the saved remainder afresh, and **Where these go** uses the checked rows
frozen at preview time.

The shared receipt operation partitions the complete edited rows before sorting,
preserves card-name totals and physical token pairing, and validates printing,
finish and token facts for the arrived copies. Unarrived facts can remain
unverified. The split, collection or token merge, fulfilment allocations and deck
table refresh save together. Matching fulfilled purchase intent follows arrived
copies first, so cancelling the remainder restores only unmet quantities; an
ordinary explicit shipment split retains its prior allocation behavior.
When the arrived printings cause the pending remainder to resemble an accidental
duplicate import, matching receipt provenance adds its additional-copy marker.
An order already ambiguous before the receipt retains that warning, as does a
remainder the arrived printings cannot explain.

The API retains profile-bound, expiring, single-use previews and exact inventory
revision checks. A temporary database outage leaves the reviewed token available
for retry; a stale preview requires a reload. Receipt dialogs now close when the
page, person or away state changes, and detached controls cannot submit changes.
The workflow was extracted into `receipt-workflow.js`, bringing `receipts.js`
below the source-length limit.

E6-S06 is built. Verification uses disposable file trees, throwaway PostgreSQL databases and DOM
fixtures. No live delivery was received, no server was restarted, and physical
device acceptance remains incomplete.

Focused checks pass 20 shared partial-receipt tests (including PostgreSQL audit
and rollback), 20 new API scenarios, 48 receipt UI/page checks (14 new scenarios)
and 107 existing receipt, order and fulfilment regressions. The final full suite
passes **4,958 tests in 1,004.979 seconds: 4,927 passed, 31 skipped, no failures or
errors**. The skips are 30 opt-in real Forge checks and one malformed file-only
fixture the database cannot store. `git diff --check` passes. The source-length
audit scans 570 owned files and still reports two unchanged existing violations:
`editor-screen.js` (1,359 lines) and `test_feature_ui.py` (1,217); the former
receipt-file violation is resolved.

## Combined buying views and sortable missing-card prices (2026-10-15)

Shopping's **Missing cards across decks** gathers each canonical playable card
once, with the missing copies and links to every Planned home deck that wants it.
The total adds those decks' individual shortfalls against the shared pool; it is
not a simultaneous packing allocation. Existing queue rows, all states included,
show their quantities, purpose, printing and dated reference prices without
adding purchase decisions or subtracting queued intent from missing copies.
The service uses one inventory snapshot and one home pool, with no price fetch.
Unavailable card data, pool problems and unreadable decks remain explicit; a
partially counted list retains its successful rows and names the missing counts.

The folded **By shop** view includes every queue row last seen at a chosen shop,
including long-term plans. In-stock, out-of-stock and unknown-stock rows are
separate, and rows without a shop have their own group. Reference-price wording
and the checked date now appear directly below every priced queue card, even
without card data or an image. Stock and prices remain dated research, with no
claim of live availability. The shop selection and open/closed state survive
saved queue changes; annotations are rebuilt from the saved current queue.
The new views add no write controls. Shop filters, fold state and the count-refresh
action ignore events from a detached view, another route or another person.

Known token and reminder printings are excluded when matching purchase intent
to a playable shortfall, including same-name collisions. Queue answers mark only
positively identified token rows. Metadata edits retain that evidence while the
card cache is unavailable; an identity correction clears an obsolete marker.
Home inventory permissions remain the boundary for the complete answer.

The deck's price table sorts by Card, Missing or **~AUD missing**, with native
buttons, focus restoration and `aria-sort`. Missing cost uses the API's extended
estimate, unknown estimates stay last in either direction and zero remains valid.
Each card's labels move with its row group and the total stays last. The unit
estimate sits under the card name, retaining five columns in the compact layout.
Sorting is local and survives the Cards tab's filters and view switches.

E5-S04, E5-S07, E5-S09 and E5-S22 are built. E5-S11 remains partial: announced
reprints and released-reprint price-check follow-ups still need their own work.
Physical-device and observed-user acceptance, the October 19 gates and real Forge
checks remain incomplete. No purchases, seller contact, live inventory changes,
Cloudflare provisioning or server restart were used for verification.

Focused verification passes 136 Shopping/UI/web regressions and all 20 new
buying-view scenarios; the sortable price table passes 80 focused checks,
including nine new interaction cases. Early compatibility runs exposed stale
expectations about page-wide row counts, folds, script order and the unavailable
answer's new field; the expectations were narrowed to the relevant view and
updated for the additive contract, then passed.

Backend verification passes 22 new buying-view tests over file fixtures,
disposable PostgreSQL databases and HTTP, plus 114 Shopping/queue/permission
compatibility checks. The production path has one gathered counter; the obsolete
private per-deck counter was removed and its legacy ordering test now exercises
the gathered result. The source-length audit still flags only the same three
unchanged files: `receipts.js`, `editor-screen.js` and `test_feature_ui.py`.

The final full suite ran 4,902 tests in 858.128 seconds: 4,871 passed, 31 skipped,
with no failures or errors. Thirty opt-in real Forge checks stayed disabled; the
other skip is an invalid file-only collection case the database cannot store.
The staged whitespace check passed and both epic summaries and persona counts
were independently reconciled to all 203 story headers.

## Cancelling and removing orders, with queue restoration (2026-10-15)

Shopping's Edit order sheet can cancel a pending cards, tokens or product part
with a reason and an explicit choice to return recorded fulfilled quantities
to To buy. Removing a mistaken order always restores its remaining recorded
intent and is refused once any part has been received. Each change is previewed
before one audited save; the final result retains queue warnings and the
Tables out of date follow-up until dismissed. The API binds both inventory and
deck revisions and rechecks private legacy product-kit references under the
write lock. No admin override was added for another owner's kit.

The same `order.cancel` and `order.remove` inventory operations serve the CLI.
`order cancel --restore-queue` accepts the queue offer; omitting the flag declines
it, preserving the old command's default. `order remove` restores recorded intent
and deletes the unreceived record, components and their exclusive products and
payloads. Cancellation retains its history; a cancelled product keeps its fixed
reference list with status cancelled, contributes no incoming cards and is left
out of the deck library. Both changes refresh the home deck tables atomically.

New orders record price-free fulfilment allocations in a versioned part of the
existing audited provenance field. Exact requests reserve physical copies first;
token aliases share one physical capacity. Splits conserve allocations and card
corrections preserve name totals. Corrected product lists retain their original
recorded purchase intent; corrected token names remap that intent to the remaining
physical copies. Both warn that restoration may differ from the corrected contents.
Returned or explicitly declined claims
cannot return again. Existing queue rows keep their current metadata; recreated
rows have blank market references, and a missing old source is cleared with a
warning. Older orders without this evidence require a manual queue review;
quantities are never inferred from card names or current shortages. Verification
used isolated fixtures, with no schema migration, live inventory change or seller
contact.

E6-S24, E6-S07 and E6-S08 are built. Receiving only the ticked rows of a component
remains E6-S06. Physical-device/observed-user acceptance, the October 19 gates
and real Forge waits remain incomplete.

Focused verification passes 97 API tests and 71 UI/web tests. Backend verification
passes 40 lifecycle/ledger tests (including eight disposable PostgreSQL cases),
162 order/receipt compatibility checks and 40 product checks. The new API's
PostgreSQL cases also cover reason attribution and rollback of order, queue and
deck changes together. No real orders or seller accounts were used.

The first full-suite run exposed three contract-golden failures: the accepted
product-status warning now includes cancelled. Only that diagnostic was updated
in the two expected-output files; the unknown-status fixture and its behaviour
are unchanged. All 34 inventory-contract tests then passed.

The final full suite ran 4,851 tests in 929.426 seconds: 4,820 passed, 31 skipped,
with no failures or errors. Thirty opt-in real Forge checks stayed disabled; the
other skip is an invalid file-only collection case the database cannot store.
The staged whitespace check passed.

The source-length audit still fails only on the same three unchanged existing
files: `receipts.js`, `editor-screen.js` and `test_feature_ui.py`; none of this
batch's source exceeds 1,200 lines.

## Product storage and device pictures (2026-10-15)

A recorded product's deck Overview shows its physical storage state to home
inventory viewers. An admin can preview Keep intact or Break up into storage,
review the table changes and confirm. The existing product operation saves
status, cleared kit and refreshed home deck tables together. A preview binds
the viewer/listener and both revision counters, expires after 30 minutes and
cannot be reused after saving. Private legacy kit references stay masked and
do not gain an admin override: neither storage transition can clear or
reactivate another owner's kit, and keeping intact refuses known nonshared
or wrong-kind references. Unknown storage is shown as unknown; products
not owned or without usable deck lists explain why a choice is unavailable.

The accessory Add/Edit sheet accepts a JPG, PNG or WebP photo up to 4 MiB.
Selection, preview and crop stay local until explicit Save sends the bytes to
Deck Lab, where format, dimensions, bounded container and size are checked.
The standard accessory add/edit operation stores the row and picture together;
canceling creates no staged picture or database write. Failed saves keep the
draft and photo. The old picture survives a refusal or concurrent edit.
Navigation, switching people and the away lock close the whole accessory
dialog flow, including parent pickers and nested confirmations, and discard
unsaved photo data; delayed work cannot notify another viewer or assign kit.

`product kit STEM [--json]` reads the kit and status-list SHA. The typed
`product set-kit` command takes `--expect`, one or both `--sleeves` and
`--deck-box`, and a nonblank `-m`; `none` clears a field, and omitted fields
stay unchanged. It uses strict `kit.set`, rechecks owned/intact state inside
the write lock, supports dry runs and actor attribution, and saves one audit
entry. Products use shared accessory ids. No card download or table refresh
is needed for kit-only changes.

Verification uses isolated fixtures, synthetic local pictures and disposable
PostgreSQL databases. No personal file, live inventory change, external
upload, server restart or deployment was involved. Physical-device and
observed-user acceptance, the dated privacy gates and Forge waits remain open.

E8-S11, E8-S02 and E8-S18 are built; their completed TODO row is removed.
The source-length check still reports three unchanged existing files over
1,200 lines (`receipts.js`, `editor-screen.js`, `test_feature_ui.py`). No changed
source crosses that limit; splitting the picture helpers reduces
`accessories.js` from 1,135 to 987 lines.

The final focused API/CLI batch passes 56 tests, including six disposable
PostgreSQL checks. The related UI batch passes 100 tests. The new upload tests
include decodable synthetic PNG, progressive JPEG and extended WebP bytes;
the PostgreSQL upload case verifies picture bytes, crop and one audit change,
then confirms a refused replacement preserves them.

The initial full run completed 4,750 tests in 801.332 seconds with two failures,
one error and 31 skips. Both failures were old fixtures loading/inspecting only
`accessories.js` after the picture helpers moved; the corrected editor-contract
module passes 44 tests and the page-source module passes 10. The unrelated
`WarmLegTests.test_the_worker_is_pinned_to_its_slots_core` cleanup hit an
`IndexError` parsing a blank fake-worker log line; its immediate isolated rerun
passes. That existing harness was left unchanged, and no actual Forge games
were run. Pinning in the intermittent check was mocked; the suite's separate
affinity tests act only on their own disposable child process.

The final full run (`python -m unittest discover -s decklab/tests -t . -v`)
passes: 4,750 tests in 795.841 seconds, 4,719 passed and 31 skipped, with no
failures or errors. The skips are 30 opt-in real Forge/JDK checks and one
file-only invalid-inventory case PostgreSQL cannot hold. The previously
intermittent fake-worker cleanup and the backup tests pass in this run.

## Finish building and physical stand-ins (2026-10-15)

Packing's final review asks which saved list was assembled and offers its
owner's sleeves and deck box. Changing the list returns to fresh card checks.
Status, built version, kit, installed stand-ins and final-pool availability
tables save in one revision-checked change. Cancellation writes nothing;
failures retain the checklist. Any table refresh problem links to the Decks
page's Tables out of date list. The unbuilt Overview explains when kit is
chosen, and sleeve choices show the need, owned count and spare or short.

Choose stand-ins saves a per-list physical mapping: an owned free marker X
represents logical card Y, or Any spare card uses an untracked basic. Real
cards are allocated first across all selected decks, then saved markers;
suggestions alone never make a plan ready. Named markers are counted once,
and anonymous markers need a physical checklist tick. Overview and Packing
name the mapping and open Y's picture and rules; Print play sheet records the
mapping on paper. The story clarifies that distinction between media. Logical
lists, exports, shopping shortages, game snapshots and Forge remain Y.

Planned choices reserve nothing. Marking built records the installed recipe;
receiving Y leaves a still-sleeved X reserved until explicit repacking returns
it. Removing a represented target or changing the built list version can be
repaired by selecting the affected holder; malformed or unselected reservations
keep the plan blocked. Stand-ins stay
outside generic header-history projection and are shown only to viewers of
that space's inventory. Sheets and late responses check the original person,
route and plan; person switches, navigation and the away lock close them.

E4-S01, E4-S03, E4-S21 and E8-S05 are built; the E4-S03 TODO row is removed.
Physical-device checks, User2's observed testing and dated waits remain open.

Known low issue: editing a built list to include its own named marker as a real
card can leave an ambiguous old recipe whose physical count exceeds ownership.
The plan refuses that count rather than inventing returned copies. Take the deck
apart and set it back to Building, then choose its new markers and rebuild through
Packing. Direct repair of that collision is not implemented.

Validation: the final full run completed 4,667 tests in 947.027 seconds:
4,636 passed and 31 skipped. The latest 20-case core stand-in suite, including
the collision/rebuild recovery, passes separately. Final packing/web checks
(69), the legacy feature UI module (31) and inventory contract checks (34) pass.
Five isolated PostgreSQL kit checks cover transfer/swap revisions, one audit,
rollback and concurrent changes. The first full run's only failure was an old
unbuilt-kit assertion, corrected to expect the new hint; no golden fixtures
were rewritten. The source audit covers 541 owned files and reports the same
three existing files over 1,200 lines, with no new over-limit file.

The separate bounded backup investigation identified the prior disposable
restore-check cleanup failure: a short-lived autovacuum worker was active
after the verifier client had already closed. No client leak or test-order
contamination was demonstrated. The worker exited naturally shortly after
the refused DROP DATABASE termination. Backup behavior and PostgreSQL roles
and privileges remain unchanged; this intermittent cleanup race is unresolved.

## Usual opponents on decks and pickers (2026-10-15)

The deck Overview names its usual opponents with links in both directions.
Choose usual opponents saves an optional comma-separated Usual opponents header
on that deck alone, through the existing deck save and audit operation. The
reverse links are derived when reading. Generic editor and table saves preserve
the line; deleted or unreadable decks produce no link. Existing declarations
that the viewer cannot see survive a visible-choice edit without being exposed.

Packing offers the selected decks' usual opponents in a leading group, without
duplicating choices. New Forge matchups offer compatible usual opponents first,
while retaining an explicit opponent and its list version. Product decks and
Beginner Box pairings can receive reciprocal links without gaining editable
metadata or changing the matchup matrix's deck list.

The choice sheet checks the deck's text hash. A conflict requires reloading
choices; failed saves retain selections. Navigation, profile changes and the
away lock close the sheet, and delayed work cannot update or notify another
viewer. No household data, live Forge run, server restart or deployment was
involved in verification.

E4-S22 is built and its TODO row is removed. Physical-device checks, User2's
observed testing and the dated privacy and Forge waits remain incomplete.

Validation: 175 focused tests pass, including 19 new sheet/picker scenarios;
44 deck-API and isolated backup checks pass, and four golden-compatibility
checks pass across raw/adapted file fixtures and disposable PostgreSQL readers.
The fresh full suite ran 4,579 tests: 4,547 passed, 31 skipped and one failed.
The remaining failure is the unchanged
`test_db_ops.BackupTests.test_backup_and_restore_check_round_trip`: PostgreSQL
refuses a termination during `DROP DATABASE ... WITH (FORCE)` on the disposable
restore-check database. It also reproduces in the complete 13-test backup class
(12 pass, one fails), while the case alone passes. Backup code and database
roles/permissions were not changed; this remains a verification limitation.
The first full run's outdated additive API expectations were corrected without
rewriting golden JSON. `git diff --check` passes; the source audit reports the
same three existing files over 1,200 lines, with no new over-limit file.

## Collection import and reduction guards (2026-10-15)

An import preview now warns when the exact upload content is already in that
space's raw imports, even under another filename, showing its recorded date
and original importer or explicitly unknown provenance. Applying still merges
additively and records the intentional repeat in the actual audit message.
A changed set of matching imports requires a fresh preview. The command-line
merge also warns, including repeated content within one batch. Raw import
contents and purchase fields are not exposed by the warning.

A removal or reduction warns before leaving fewer physical copies than built
decks and owned-intact products hold. Totals span printings and finishes within
the same space; incoming copies do not cover the shortage. The sheet names the
held decks and suggests taking the cards out first, with an explicit option to
proceed. Unknown demand is an acknowledgeable warning. Review tokens bind the
viewer, exact change and both inventory/deck revisions; both counters are
checked under the existing write lock, including a concurrent deck-only save.

Optional reasons with Sold/Traded quick picks cover whole rows and quantity
reductions and survive conflict retries. The existing Tables out of date /
Update all workflow remains. Collection sheets close on navigation, switching
people and the away lock; late work cannot reopen the old viewer's prompt.
Import apply captures the reviewed file and disables selection while waiting.
Row editing was split into collection-cards.js, reducing collection.js below
the 1,200-line review threshold.

E7-S04, E7-S11 and E7-S12 are built; their combined TODO row is removed.
Physical-device checks and observed user testing remain incomplete. All writes
in verification use synthetic fixtures or disposable PostgreSQL databases;
no real collection, deck or order was changed, and no live Forge run, server
restart or deployment was involved.

Validation: the combined focused run passed 297 tests with one expected skip
(298 total); 92 final UI/web checks pass, including all 15 guard-UI scenarios.
The fresh full suite ran 4,531 tests: 4,500 passed, 31 skipped, with no failures
or errors. `git diff --check` passes; the source-length audit reports three
unchanged files over 1,200 lines and no new over-limit file.

## Opponent sideboard plans on the deck page (2026-10-15)

The deck Overview now shows the saved sideboard plan for a chosen opponent
and list. In/out card pictures use the plan's captured printings and quantities,
including mixed-printing moves and cards removed from today's list. A plan
matching both current list hashes takes precedence; otherwise the newest plan
for those deck ids and list versions remains visible with a plain warning.
With no matching plan, the deck's Sideboard notes show if present.

Make or Revise opens the existing preview-and-confirm sheet with both lists
selected. A save refreshes the section while retaining the opponent choice.
Read visibility comes from the existing Game log filter; write controls use
record permissions independently. Presentation fields stay outside stored
records and concurrency hashes. Failed loads retain the notes and offer Retry;
late replies after navigation, profile changes or replacement are ignored.

E4-S15 is built and its TODO row is removed. Story and persona totals have
been reconciled against the story headers, including prior Test tab changes.
Physical-device E2-S22/E2-S04 and User2's observed testing remain incomplete.
No household data, live Forge run, server restart or deployment was involved.

Validation: 108 focused API and UI/web checks pass. The standard full suite
ran 4,464 tests: 4,433 passed, 31 skipped, with no failures or errors. The
previous batch's unchanged `test_forge_servecheck` cleanup test passed in this
run; its earlier error remains documented below. Independent review's saved
mirror-plan edge case is fixed and covered. `git diff --check` passes; the
source-length audit reports the same four existing files over 1,200 lines,
with no new over-limit file.

## Complete Test tab preferences and live ranges (2026-10-15)

Choosing Quick look, Settle it or Precise for the field now saves that profile's
usual field budget. Rapid choices save in order across deck navigation; switching
people prevents queued writes under another viewer. A failed save says so and
keeps the current choice visible.

Every running matchup now shows an anytime-valid live range after games finish,
including fixed-length runs and matchups inside field or variant runs. The API
and Forge share one calculation without loading Forge just to read progress.
Draws and timeouts count as non-wins for each side; existing adaptive ranges
retain their saved games. Variant top-ups now include saved wins in the live
score, reverse correctly when viewed from the opponent's side, and link back to
their test. Draft paired keys remain separate from saved-deck matchups.

A normal land count now says **Ok** in plain hint text, keeping chips for
exceptions. E3-S09, E3-S06 and E10-S23 are built; the E3-S09 TODO row is removed.
E3-S01 remains partial for source dates in disclosures and its colour-ordering
ambiguity. Physical-device checks remain E2-S22/E2-S04; no hardware or touch
verification is claimed. Tests use synthetic fixtures, disposable databases and
fake Forge; no household data changed.

Validation: 290 focused regressions and 78 API checks pass. The standard full
suite ran 4,450 tests: 4,418 passed, 31 skipped and one cleanup error in
`test_forge_servecheck.WarmLegTests.test_a_v2_request_goes_on_in_a_new_worker`.
Its `all_dead` cleanup read a blank process-log line and raised `IndexError`;
the test passes alone and its complete 28-test module passes on rerun. That
fixture is unchanged. Independent review found no remaining production issue.
`git diff --check` passes. The source-length audit still reports four existing
files over 1,200 lines; none was changed by this batch.

## Split pending shipments on Shopping (2026-10-15)

Shopping's **Edit order… > Split shipment…** moves selected physical copies
from a pending cards or tokens part into a new part of the same order. Each
arrival check applies to both parts by default, or can stay only with the
original or new part. The preview shows both complete resulting lists and
their checks, with affected deck tables, before one audited save by Matt.
Printing details, unknown condition/language, notes and token face pairings
stay as recorded; each part must retain at least one physical copy.

The page uses the existing `order.split` operation and revision-bound,
writer-bound preview tokens. A concurrent save requires a fresh preview.
Products and received or cancelled parts cannot be split. As on the command
line, an additional-copies mark stays on the original part; the new part
needs its own confirmation, and a split introducing a table-refresh blocker
is refused.

E6-S24 remains partial: cancellation (including products), removing mistaken
orders and returning fulfilled queue copies remain in TODO.md. Physical-device
testing was skipped at Matt's request; E2-S22 remains open. Tests use synthetic
fixtures and disposable databases; no household data changed.

Validation: 21 new API tests and seven runtime UI tests cover exact rows and
check routing, permissions, stale replies and revisions, real pool blockers,
and PostgreSQL rollback/audit behavior. The adjacent API regressions pass
(83 tests), as do the UI/web checks (50 tests). Independent review found no
remaining actionable issues. `git diff --check` passes. The source-length
audit reports the same four existing files above 1,200 lines, with no new
over-limit files. The final full suite ran 4,443 tests with no failures
(31 skipped).

## Share Build decks progress across devices (2026-10-15)

Build decks checkmarks now follow Matt and User1 between devices. Each save
patches individual tasks, so simultaneous checks on different cards are kept.
Adding or removing decks, changing the display order, or saving unrelated deck
prose preserves unchanged tasks. Changed quantities, source decks, list versions,
finishes, sleeves, boxes or token variants need a fresh check. Clear and Undo
affect only the displayed checklist. Open pages refresh every three seconds
while visible and on return from the background.

Pending checks remain visible during a failed save, with a plain status and
Retry. Late responses cannot overwrite newer local changes, another selection
or another profile. Mark as built waits for shared ticks to load and save.
Older browser-only ticks do not overwrite shared progress.

`POST /api/assembly/ticks` reads only the supplied tasks and atomically patches
changed ones. Migration `0009_packing_ticks.sql` adds shared audited storage;
task descriptions are hashed before storage and audit, keeping kit labels out
of shared state. Both home players may use it; other spaces are refused.
Activity groups a change into one home-only packing-progress summary. Backups
and exports include the checks. Token tasks have compact server-generated keys
even when many long-detail variants match. The planned visibility migration is
now 0010.

E4-S02 is built and its TODO row removed. Physical-device testing was skipped
at Matt's request; E2-S22 remains open. Tests used memory and disposable
PostgreSQL databases; no household cards, decks or kit changed.

Validation: the full suite ran 4,406 tests with no failures (31 skipped). It
started before the final compact token identities and failed-preview guard were
finalized; subsequent focused runs pass all 67 frontend tests, the token/API/
assembly checks, and historical reader comparisons on both file fixtures and
PostgreSQL. Independent review found no remaining actionable issues.
`git diff --check` passes. The source-length audit reports four existing files
above 1,200 lines, with no new over-limit files; Activity is now within the cap.

## Complete the phone's Quick edit (2026-10-15)

The phone's Quick edit now includes the full editor's Notes, Substitutes and
**Mark write-up as current**, plus folded **Deck details** with Archetype,
Played by, Built version, Commander Target bracket and a built home deck's
sleeves and box. Status stays visible above the fold. The same player and
accessory permissions apply, including the absence of home-only fields in a
person's space.

**Add cards > Paste a list…** uses the existing Add/Replace preview and Undo.
It waits for the search sheet's native close before opening Paste, so Back
returns directly to the editor. Prose and details use the existing drafts and
save checks. Conflict reapplication now preserves Notes, Substitutes and the
current-write-up choice; previously that shared path could silently drop them.

E2-S05 is built. TODO.md retains E4-S02 for packing ticks shared across devices.
Physical-device testing was skipped at Matt's request; E2-S22 and E2-S04 retain
their physical acceptance work. No household data changed.

Validation: 119 focused editor and web checks pass, including eight new runtime
regressions for details, prose/drafts, conflict recovery, paste previews,
permissions and asynchronous sheet/history transitions. Independent review
found no remaining actionable issues. `git diff --check` passes. The
source-length audit still reports the same five existing files above 1,200
lines, with no new over-limit files.

The full suite started while the new test module was being finalized and ran
4,362 tests (31 skipped), with four failures: three assertions from that
unfinished module and the unchanged backup round-trip's intermittent
PostgreSQL restore-cleanup permission error. The final 119 focused checks pass;
the backup case and all eight final Quick edit tests also pass together on a
targeted rerun (9 tests). The full suite was not repeated after those fixes.

## Correct pending products on Shopping (2026-10-15)

Shopping's **Edit order… > Correct product…** now corrects a pending product's
name, format, ordered/preordered status, notes and complete published card list.
The form retains its optional section/deck columns and exact recorded fields;
an untouched list is omitted from metadata-only changes, even when the browser
normalizes textarea newlines. The confirmation shows the full resulting product,
arrival checks, warnings and affected deck tables before saving.

`product.edit` and `python -m decklab.db product edit STEM` provide the same
correction, with `--dry-run` on the command line. The product's stem, order
component, receipt facts, checks and additional-copy acknowledgement stay fixed.
Owned, received and cancelled products are refused. Expiring previews belong to
their writer and listener and recheck the exact inventory revision inside the
save transaction. Product metadata, list, status and affected deck tables save
in one audited change; failures roll back together. Product display metadata
now counts as a change even though it is stored outside the list's CSV, so a
name-only correction also refreshes product labels in saved deck tables.

E6-S08 and E6-S24 remain partial: splitting, cancellation (including products),
mistaken-order removal and returning fulfilled queue copies remain in TODO.md.
No household data changed. Physical-device testing was skipped at Matt's
request; E2-S22 stays open.

Validation: all 45 new product operation, API and runtime UI tests pass,
including file fixtures and disposable PostgreSQL audit/rollback checks. The
existing Shopping and inventory regressions pass; 43 UI/web checks pass.
Independent review found no remaining actionable issues after the name-only
refresh fix. `git diff --check` passes. The source-length audit retains the
same five existing files above 1,200 lines, with no new over-limit files.

The full suite ran 4,356 tests (31 skipped), with one failure in unchanged
`test_forge_execution.RunTests.test_a_run_plays_parallel_batches_and_saves_them`:
it observed 15 unique worker process ids rather than 16. That test and all
45 new product tests passed together on an isolated rerun (46 tests). The full
suite was not repeated after that rerun; no Forge implementation was changed.

## Correct pending order rows and additional copies on Shopping (2026-10-15)

Shopping's **Edit order…** now offers corrections to pending card and token
parts. The form retains complete stored rows, including unknown condition and
language, notes, token front/back pairings and both faces' details. Playable cards
keep the same copies of each name; copies can be split between printing rows.
Token corrections keep the same number of physical cards. The confirmation
shows the validated resulting rows and the deck tables affected before saving.

Pending cards and products also offer marking or unmarking additional copies.
The form explains that this acknowledges extra cards beyond those already in
the collection. Each correction uses the existing `order.edit` or
`order.extra_copies` operation, with an opaque preview bound to the writer,
listener and exact inventory revision. The payload and affected deck tables
save in one audited change. A newly introduced table-refresh failure is refused;
an existing blocker is reported. Failed saves retain the draft, and a changed
profile or page cannot reuse it. Record/check corrections still work without
the card cache.

E6-S24 remains partial: pending-product corrections, splitting, cancellation,
mistaken-order removal and returning fulfilled queue copies remain in TODO.md.
No household data changed. Physical-device testing was skipped at Matt's
request; E2-S22 stays open.

Validation: 100 focused backend tests and 48 focused UI/web tests pass, including
file and disposable PostgreSQL coverage of row fidelity, permissions, concurrent
saves, refresh blockers, atomic audit/rollback and additional-copy changes. UI
tests cover printing splits, retained drafts and pickers, and simulate native
textarea newline normalization to check untouched metadata stays exact.
Independent review found no remaining actionable issues; `git diff --check`
passes, and the source-length audit retains the same five existing files above
1,200 lines with no new over-limit files.

The full suite ran 4,311 tests (31 skipped), with three failures in unchanged
backup/restore checks: PostgreSQL refused process termination during restore
cleanup. All 78 database core/operations tests, including those three, pass on
an isolated rerun. No database privileges were changed. The full suite was not
repeated after that rerun.

## Correct order records and pending checks on Shopping (2026-10-15)

Shopping's **Edit order…** on deliveries and history corrects seller, order date,
delivery notes and sources at any receipt status. Pending parts offer **Add
check…** and **Withdraw…**, one check at a time; withdrawal removes an inspection
request entered by mistake without verifying it. **Preview change** shows the
result before **Save change** records one audited change by the viewer. A draft
of record details must be saved or undone before changing its checks, so a check
save cannot discard unfinished details.

Both writes share inventory operations with the command line: the new
`order record` corrects only supplied fields and existing `order checks` handles
checks. Metadata keeps components, card rows, receipt states and provenance;
blank values clear unknown fields, sources use the existing repository/deck
rules, and an order date after an existing receipt is refused. These changes
need neither card data nor deck-table refresh. Preview tokens expire after
thirty minutes, belong to their writer and listener, and check the exact
inventory revision again in the save transaction. Editing inputs or leaving
the profile/page invalidates the UI preview. Failed saves keep the draft.

E6-S24 is partial. Editing rows and pending products, splitting, cancellation,
extra-copy changes, mistaken-order removal and returning fulfilled queue copies
remain in TODO.md. User1 sees orders read-only and person-space profiles are
refused home's Shopping. No household data changed. Physical-device testing
was skipped at Matt's request; E2-S22 stays open.

Validation: all 4,274 tests in the final full suite report OK (31 skipped),
including the new operation, CLI, file-backend, disposable PostgreSQL, API,
permission, HTTP-route and runtime UI regressions. The focused order/CLI run
passes 83 tests, the corrections API run 33 and the Shopping/UI/web run 49.
Independent review found no remaining actionable issues after the draft-loss
fix. `git diff --check` passes; the source-length audit retains the same five
existing files above 1,200 lines, with no new over-limit files.

## Record placed orders on Shopping (2026-10-15)

Shopping's **New order** lets Matt record a purchase already placed: seller and
date, searched or pasted playable cards with their ordered printing, token
singles with their physical face pairing, a product and its list, arrival
checks, additional-copy acknowledgements and the purchase-queue rows it fulfils.
Unknown condition, language and token characteristics stay blank. The preview
shows the entered contents, checks, queue reductions and affected deck tables
before **Save order** records everything as one audited change by Matt.

The page shares `order.add` and its atomic table refresh with the command line.
An opaque, expiring preview belongs to its profile and listener, and its exact
inventory revision is checked again in the save transaction. A changed page or
profile cannot reuse the old preview. User1 sees orders read-only; person-space
profiles cannot access home's Shopping. Changing, cancelling and removing orders
remain E6-S24. E6-S02 is built and leaves TODO.md. No household data changed.
Physical-device testing was skipped at Matt's request; E2-S22 remains open.

Validation: 171 focused order, Shopping, queue, permission, route and web tests
pass, including 31 API checks on files and disposable PostgreSQL and nine new
runtime UI scenarios. The database audit test verifies the order, fulfilled queue
rows and deck-table refresh share one change set. Independent review completed;
`git diff --check` passes. The source-length audit retains the same five existing
files above 1,200 lines, with no new over-limit files.
The full run exercised 4,199 tests (31 skipped). It started while the new test
fixtures were still being finalised and loaded their earlier versions: four
failures and two errors there were corrected, and the final 171-test focused run
passes. The other two failures are unchanged backup/restore checks. On isolated
rerun, the content-mismatch check passes; the old-dump/counts check still fails
because PostgreSQL refuses process termination without the required role
privilege. No database privileges were changed, and the full suite was not
repeated after the fixture corrections.

## Edit the purchase queue on Shopping (2026-10-15)

E5-S06 is built: Matt can use **Add card** on Shopping with its copies, category
and home deck, open a row's **Details…** to change Copies and Notes, or use
**Remove…** with a required reason. New cards default to any non-foil printing;
an exact printing can be chosen when that matters. The existing Move menu still changes categories.
Saving updates the queue sections and counts while preserving expanded long-term
groups and pending delivery follow-up Undo.

Each change uses the existing inventory operation, Matt's audit identity and the
exact revision Shopping displayed. Stale changes are refused before a row number
can select a different card. User1's queue stays read-only, and person-space
profiles cannot access home's Shopping. Recording and changing orders remain
separate work. No household data changed. Physical-device testing was skipped at
Matt's request; E2-S22 stays open.

Validation: 175 focused Shopping, queue, permission, route, web-contract and
disposable PostgreSQL tests pass, including 16 new runtime UI scenarios. Another
41 workspace, wishlist and page checks pass. Independent review found and
verified fixes for nested-dialog refresh and late-response races. The full run
exercised 4,168 tests (31 skipped), with two failures outside the changed code:
the restore-contents check hit a PostgreSQL session-termination permission error,
and the Forge worker-budget fixture recorded seven starts instead of eight.
Both pass on isolated rerun; the full suite was not repeated. `git diff --check`
passes; the source-length audit reports the same five pre-existing files above
1,200 lines. No browser or physical-device acceptance was performed.

## Commander pregame summary and card-data dates (2026-10-15)

Commander Overview starts with **At the Commander table**: the declared bracket
aim, any higher detected minimum and the cards responsible, with names opening
the existing viewer. **What opponents will face** lists Game Changers, mass land
denial and extra turns, opening when any are found. The summary explains that
combos, chained turns, speed and intent are unchecked; Bracket 2 guidance allows
a few extra-turn cards without claiming that the deck fits the bracket.

Overview and the Stats panel show the actual Scryfall card and community-tag
source dates from the loaded index. Missing, invalid, future or over-seven-day-old
dates get an age warning, without a network request. Missing tags say not checked
instead of falsely saying no effects, and unresolved non-sideboard names make the
check incomplete. It describes the displayed Planned or Play-now list and uses no
inventory counts. No household data changed.

E9-S05 is built and leaves TODO.md. E9-S06's opponent-facing list and E9-S04's
dates/age warning are built; sourced combo detection and an automatic feed for
the latest official list-change date remain in their stories for later, as the
roadmap intended. The official Commander format page and October 2025/February
2026 updates were checked on 2026-10-15. Physical-device testing was skipped at
Matt's request; E2-S22 stays open.

Validation: 238 focused readiness, stats, page, API, editor-contract and inventory
tests pass, including the 17 new acceptance tests. Independent review found no
actionable issues. The full run exercised 4,134 tests (31 skips) and reported 16
failures: 15 golden comparisons saw an unnecessary historical source-citation
date edit loaded at startup; that edit was reverted and all 31 inventory contract
tests pass on rerun. One restore-check test hit a PostgreSQL session-termination
permission error and passes on its isolated rerun. The full suite was not repeated.
`git diff --check` passes, and the source-length audit still reports the same five
pre-existing files above 1,200 lines. No browser or physical-device acceptance
was performed for this change.

## Name the person making command-line changes (2026-10-15)

E11-S07 is built: all 28 audited data-write commands accept `--actor PROFILE`.
Matt can add `--actor matt` to his own commands so Activity names him, from the
command line. Omitting the option keeps Claude's existing identity. The shared
resolver checks the configured profiles before a command reads files or data;
unknown, blank and reserved ids are refused with exit 1. Collections, tokens,
orders, products, the purchase queue, receipts, decks and table refreshes,
accessories, pictures and wishlists all pass that actor to the existing audit
operation. Previews save nothing; maintenance retains its system actors.

Attribution leaves PC access and Activity's privacy rules as they were. The
README and agent guidance explain the option; the story, plan and gap analysis
record completion, and its row leaves TODO.md. Physical-device checks remain
the current NOW item.

Validation: 232 command-line tests pass together (one intentional skip), including
the seven new acceptance tests and real PostgreSQL audit/Activity checks in a
disposable database. They cover every write parser, actor forwarding through real
isolated operations across all command families, default Claude, early invalid-actor
refusal and wishlist privacy. Independent code review found no issues.

The full run exercised 4,117 tests (31 optional skips). It loaded two new test
fixtures before their corrections and exposed 35 pre-existing subtest failures:
the guide test required "mulligan" in titles already called "Opening hand", and
the historical inventory snapshots predated the builder's completion and finish
fields. The guide assertion accepts either heading; the golden normaliser lists
the intentional builder additions, leaving the committed snapshots untouched and
all prior allocations compared. Dedicated assembly tests cover those additions.
The corrected actor cases, eight guide tests and all 31 inventory contract tests
pass on their focused reruns. The full suite isn't repeated after these fixture-only
corrections. The source-length audit reports the same five pre-existing files over
1,200 lines. No household data changed during testing.

## Move purchase-queue cards between categories (2026-10-15)

Shopping gives Matt a **Move** menu beside each queued card, in both **To buy** and
**Long-term plan**. It uses the existing categories: Ready to buy, Waiting for stock,
Waiting for reprint, Deferred and Long-term plan. A move saves immediately and updates
the sections and counts, keeping the card's other details, expanded long-term groups,
delivery controls, history and pending follow-up Undo. User1's view remains read-only.

`POST /api/shopping/queue` changes only the existing watchlist row's state through
`watchlist.set`, as one audited change by the viewer. The exact inventory revision
protects the row number against stale pages and simultaneous writes. Failures leave
the card in its original category, with an inline message and focused **Refresh
Shopping** button; a conflict prevents further moves until refresh. E5-S06 is partial:
adding/removing queue rows and changing quantities still need the command line.

Validation: 159 focused UI, web, device-layout, HTTP, API and permission tests pass,
including nine tests against disposable PostgreSQL databases. Coverage includes moves
both ways, printing variants, preserved details, audit actors, no-op saves, stale and
concurrent writes, error recovery and late responses after navigation. `git diff
--check` passes. The source-length audit still reports the same five pre-existing
oversized files. Browser connections were unavailable, so this change has no visual
browser or physical-device acceptance. No household data changed during testing.

## Windows-to-Mac Safari workflow documented (2026-10-15)

The [operator guide](safari/MAC-WORKFLOW.md) records the prepared SSH connection,
private Mac launcher, committed-source transfer with Git bundles, preflight and
full-run commands, report retrieval, cancellation and the setup failures observed
during E11-S29. The runner and main README link to it. The guide distinguishes
readiness checks, native Simulator acceptance and physical-device follow-up.

## Safari Simulator regressions validated (2026-10-15)

E11-S29 is built: the [Mac setup and one-command runner](safari/README.md)
passes all 60 checks across iPhone 15 Pro, iPhone 17 Pro and iPad Air 11-inch
(M2), each in portrait and landscape. The [acceptance evidence](safari/EVIDENCE.md)
records clean source `62c0dbd8fd21670db2e91645670088da669a0c27`, exact tooling and
runtime, all per-case results, the raw report hash and independently verified
cleanup. The complete run on Xcode 27.0 / iOS 27.0 exits 0 with no unavailable
configurations or cleanup errors. E2-S22 remains partial for physical hardware
and touch-usability observations.

Each configuration creates its own Simulator and serves the actual web/API code
over synthetic cards and fixture-only in-memory history. Native UIKit/XCUITest
input exercises receipt layout and gestures, viewer swipes, software-keyboard
Save and History, Share/Add to Home Screen, actual icon launch, standalone safe
areas and stale-page reload. A visit verifies a fresh visible document; the
independent version case starts a fresh Safari process before its real version
poll and native Reload. Reports retain measured bounds, native input diagnostics,
logs and failure artifacts. Existing family data and personal Simulators are
outside the fixture.

The Mac uses private Python 3.14.8 and Node 24.14.0 tooling through
`~/DeckLabSafari/run-safari`, with locked Appium 3.4.2 / XCUITest 10.43.0.
The runner preboots its own devices and uses the driver's headless mode for
Xcode 27's Device Hub. Native control selection handles Share's compact and
scrolling layouts, delayed geometry, and rotated Home Screen accessibility
frames. Interruptions retain an unfinished report and clean up owned resources.

The native pass also found two application layout faults. Safari could pan the
quantity field without resizing its visible viewport, leaving Save beneath its
input accessory row. The editor now recomputes the remaining keyboard bottom
inset on viewport resize and scroll, keeping the sticky bar reachable. Centered
sheets now limit their height with dynamic viewport units, retaining a `vh`
fallback, so the receipt heading and Close remain within Safari's usable area.
The receipt navigation's literal question marks were corrected to arrows and a
separator. All six configurations pass the relevant native checks.

Validation: 246 focused Windows tests pass, and the 100-test Safari harness
subset passes on the Mac. The accepted native run verifies all six disposable
devices deleted, all fixture/Appium listeners closed and no owned test processes
remaining. The source-length audit still flags five pre-existing files above
1,200 lines; this work adds no new oversized file or increase to those counts.
Earlier guest PosterBoard and MobileCal startup diagnostics are recorded with
the Simulator evidence, separately from the successful Safari run.

## Receive delivery: navigation before the image (2026-10-15)

Matt confirms on the iPhone 15 Pro that the Safari Share error is fixed and the receipt inspection image is bigger, but the swipe guidance needs scrolling to reach. Previous/Next, the position count and the swipe/enlarge hint now appear above the image, keeping navigation ahead of the tall picture when the panel opens.

Validation: 64 focused receipt, inspector, device layout and web tests pass, including navigation order, boundary buttons and swipes from beside the image. The updated placement still needs a real-device recheck. No live data changed.

## Safari Share menu: opaque error reports (2026-10-15)

Matt reports a Deck Lab error panel saying Script error when opening Safari's native Share menu to add the site to the Home Screen. The global handler previously put every window error report in that panel, including masked reports with no filename, line, column or exception. Such reports do not identify a failing Deck Lab script. Only a bare Script error (optional trailing full stop) with none of those details now stays in the browser console instead of claiming the page failed. Detailed errors and unhandled promise rejections still show in the panel.

Validation: 52 focused workspace, web and version tests pass, including both generic message forms and retained reporting for source-bearing errors, exception-bearing errors, other messages and rejected operations. The source of the original Safari report is not confirmed, and opening Share/Add to Home Screen still needs a real-device recheck. No live data changed.

## Receive delivery: inspection panel size and navigation (2026-10-15)

The initial portrait/swipe fix changed the shared full-screen viewer, which also opens from Shopping's gallery above Receive delivery. Matt clarified that the problem was the separate inspection panel opened by tapping a card on Receive delivery. That panel now shows a card up to 320px wide on phones, replacing the previous 128px thumbnail. The full-width picture area, including the space beside the card, accepts horizontal swipes. Previous/Next buttons, a position count and a swipe/enlarge hint make navigation visible. Fields continue below the larger image and may require scrolling; tapping the image opens the full-screen viewer. Browsing does not tick or receive cards.

Validation: 64 focused receipt, inspector, device layout and web tests pass, including swipes starting on the surrounding area, navigation boundaries/buttons, cancellation and vertical scrolling. Awaiting the iPhone portrait recheck. No live data changed.

## Page updates on iPhone and iPad (2026-10-15)

The served HTML now gives each JavaScript and CSS URL a web-revision token. Changed assets therefore have new addresses, while static responses retain their existing no-cache/ETag revalidation. Every profile?s avatar menu offers **Reload page**; the update banner uses the same action. It adds a fresh page query token, preserves the current route and other options, and uses the editor?s normal unsaved-changes guard. Browser drafts, profile choices and preferences are kept. Older open pages can get the action by opening the site with a fresh `?v=` value before the route?s `#`.

Validation: focused HTTP and UI checks cover changed asset URLs/HTML ETags, member access to Reload page, route/options preservation, and the real editor?s beforeunload guard. Real iPhone/iPad cache behaviour still needs the device check. No live data changed.

## Card viewer: portrait size and swipe guidance (2026-10-15)

Matt reports that Receive delivery?s viewer swipes work on the iPhone 15 Pro in portrait, but the picture has too much empty space on either side, swipes seem confined to the image, and the gesture is not obvious. Each new viewer opening now starts with Text closed. Opening Text in portrait overlays the rules instead of reducing the card?s size. The viewer uses explicit viewport dimensions, captures touch on the whole dialog, and shows ?Swipe left or right? beneath the count on touch screens. Previous/Next, vertical text scrolling and pinch zoom remain available.

Validation: 63 focused inspector, device layout, receipts and web tests pass. Isolated Chrome device emulation checks portrait/landscape phone and iPad layouts and QHD, with Text both closed and open: the 393px portrait image stays 369px wide. Browser touch injection timed out, so gesture verification is covered by the interaction tests and awaits the real iPhone recheck with the layout and hint. No live data changed. The source-length audit reports the same five existing files over 1,200 lines.

## Real-device acceptance: first checks (2026-10-15)

Matt reports portrait and landscape checks passing on the iPhone 15 Pro and M2 11-inch iPad, following the Home Screen/layout check. No issues reported. E2-S22 remains partial: keyboard/save/History, card-viewer and Receive delivery swipes, and the iPhone 17 Pro still need explicit results. No code or live collection/deck data changed.

Follow-up: Matt could edit fine, but didn't recognise the quantity number as a text field. The shared stepper's editable count now has a visible border, surface and rounded corners; Quick edit keeps its field at a full touch target rather than 32px. The appearance needs a device recheck. Validation: 82 web and editor UI/contract tests pass; no live deck data changed.

Follow-up acceptance (Matt, 2026-10-15): on the iPhone 15 Pro, the updated quantity field is recognisable, Save stays reachable with the keyboard open and succeeds, History shows the change under the correct name, the original count is restored, and left/right card-viewer swipes advance one card without background scrolling or browser navigation. E2-S22 remains partial pending Receive delivery swipes, iPad interaction checks and the iPhone 17 Pro. These are user-reported device results; this documentation update makes no live-data changes.

## Build decks: mark the assembled lists built (2026-10-14)

The builder's bottom bar now offers **Mark as built**, or **Mark N decks built** for a shared plan, after all card tasks are checked. Optional token, sleeve and packing ticks do not block it. The action saves each selected Planned or Play-now list as the built version without leaving the builder, retains the checked cards and shows a built confirmation. Already-built lists need no save; products and pairings stay read-only. Selection changes and saves in flight disable the action, and an error keeps the checklist with Refresh plan.

`POST /api/assembly/built` checks permissions for every changed deck, current physical availability and a fingerprint of the selections plus both inventory and deck revisions. The same revisions are checked under the write lock. All changed decks and their availability tables save together in one audited change, including plans with transfers in both directions. A failed table refresh is reported separately from a successful built save. Saved ticks use the exact plan fingerprint, so an edited list cannot inherit completed checks for older quantities.

Validation: 202 focused assembly, permissions, route, UI and database tests pass, including a PostgreSQL check of one audit change for two built decks. Isolated Chrome tests cover success, multiple decks and error/refresh at 393, 820 and 2560px. The source-length audit still reports the same five existing files over 1,200 lines.

## Build decks: storage verification (2026-10-14)

Storage groups now sort by ascending mana value, then name, with unknown costs last. Card-step headings and each colour/type group show the total physical copies, so a pile can be checked against its heading. Totals stay fixed while cards are ticked off. Each deck's selected list supplies its own foil and etched markers; a mixed-finish card shows the list's quantities. These labels don't change allocation, which still counts by name, and returns don't inherit target-list finishes.

Checked-card borders now stay visible on hover: hover elevation changes independently of the checked ring. Keyboard focus and foil effects remain separate.

Validation: 145 focused assembly, card, receipt, deck, shell and web tests pass, including mana ordering, zero and unknown costs, physical-copy totals, per-deck mixed finishes, sorting with saved ticks and Clear/Undo. An isolated headless Chrome check reproduced the old hover bug and verified the fix across 192 checked states at 393, 820, 1470 and 2560px, both themes, mouse hover, keyboard focus and forced colours. The assembly layout was also checked at 393 and 2560px: six green creature copies, mana order, uniform and mixed finish chips, and no horizontal overflow. The source-length audit still flags the same five files already over 1,200 lines before this change.

## Build decks: storage order (2026-10-14)

The Packing plan is now **Build decks**, including its navigation and deck-page link. Card ticks sit at the picture's bottom-left, clear of mana costs. **Card order** offers Name or Storage order, remembered for each person in this browser. Storage order follows four rows: creatures by white, blue, black, red, green and multicolour, then artifact creatures; spells in those colours, then artifacts; lands (including basics) by white, blue, black, red, green, multicolour and colourless; tokens last. Lands use the mana colours they produce, falling back to colour identity when they produce no coloured mana. Colourless non-artifacts follow multicolour in their section; cards without type data appear last. Each group is alphabetical, and double-faced cards use their front's type and colours. Changing order keeps existing ticks, progress and Clear/Undo, including when browser storage is blocked, and needs no server request.

Validation: focused DOM tests cover section order, colour and type edge cases, basic lands, tick preservation, viewer order, preference isolation, blocked browser storage and failed previews. Browser visual QA was unavailable in this session.


## Milestones

Each milestone ends with a commit.

**0. Forge trial run (go/no-go, before any web page).** **Done 2026-09-29: go, with conditions.** See "Milestone 0 results" below.
1. Download the portable Forge build and run it on Java 26. If Forge doesn't support Java 26, install a Java 21 runtime just for Forge.
2. Convert Gruul Ramp and Izzet Prowess to `.dck` files by hand and run 100 games.
3. Measure:
   - how long a Forge process takes to start;
   - time per game;
   - memory per process;
   - how many processes the PC runs well at once.
4. List every card in the 11 decks and the product decks that Forge doesn't support.
5. Check that a 40-card Beginner Box pairing runs; Forge might insist on 60 cards.
6. Check a 4-player Commander game using the precon lists.
7. Save one full game log and check whether per-card stats are possible.
8. Compare the win rates with the report's heuristic simulations; each pair tested at about 50/50 there. If they disagree badly, find out why before trusting either.

Go ahead only if Forge runs, supports nearly all the cards, and a few hundred games finish in minutes rather than hours. Write the results into this file.

**1. Card data and deck files**
- Scryfall bulk download and lookup.
- Reading and writing deck files, with the round-trip test passing for all 11 decks.
- Loading product decks and Beginner Box pairings.
- Owned vs needed, plus `magic/products/status.csv`.

**Done 2026-09-29.** `lib/cards.py`, `lib/decks.py` and `lib/pool.py`, with 223 tests (`python -m unittest discover -s decklab/tests -t .`, run from the repo root; they need no network). Each module's docstring explains how to use it. Reviewers then tried to break the code in two rounds, and their findings were fixed.
- **Card data:** `python -m decklab.lib.cards update` downloads Scryfall's bulk files when they're over a week old and builds a small index in `data/scryfall/` (it loads in under a second). Role counts match the ones above.
- **Deck files:** all 11 files round-trip byte for byte, with every part the page owns rebuilt from the parsed deck. A part that didn't change keeps its exact bytes, line endings included. A file with no `## Decklist` block is listed with an error instead of reading as an empty deck. The tests use frozen copies of the files, so editing the real decks doesn't break them.
- **Decisions made while building:**
  - Prices skip gold-bordered, collector-edition and oversized printings. A card with no non-foil price uses its cheapest foil or etched price, marked as such.
  - Autocomplete leaves out digital-only cards, since Magic here is paper only.
  - A new optional header field, `Built version` (`target` or `owned-only`), says which list of a built deck is physically put together. Without it, or with any other value, a built deck holds its owned-only list, with a warning.
  - The table always describes the target list. `set_table` refuses rows whose Need doesn't match it, so an owned-only list, or a list read from disk before an edit, can't replace the table. `pool.deck_table(deck)` works the table out from the list being edited.
  - In a rewritten table, **Owned** means copies this deck can use: owned plus on the way, minus copies other built or intact decks hold, capped at Need. The Notes cell starts with Deck Lab's labels, one per source or deck: "1 on the way (order 2026-09-29-shop-a)" for copies it counts on that haven't arrived, and "2 in use in Gruul Ramp" for a card other decks leave it short of. Hand-written notes after them, and on the total row, are kept.
  - The rate line above the table is updated to match the prices, and only in its exact wording. A rate worded differently blocks repricing rather than leaving two rates. A table rewritten without prices (no rate yet, or an index without a price date) keeps the old price cells that still match the old rate, and blanks the rest.
  - A bad row in an order file or an incoming product only leaves that row out, with a warning. A bad row in `collection.csv` still stops the count.
- **What it shows on 2026-09-29:** with the Beginner Box kept intact, every deck's owned-only list is 1-8 cards short, and every one of those cards is held by a Beginner Box half.

**2. Server and read-only pages:** the "Who are you?" screen, library and deck view with stats, reachable from a phone.

**Done 2026-09-29.** `server.py`, `lib/api.py` (one function per endpoint), `lib/stats.py` and the page in `web/`, with 373 tests in all. [README.md](README.md) says how to start it and the one-time Windows setup phones need.
- **Research first:** the stats use published guidance, looked up on 2026-09-29. Each figure is a named constant in `lib/stats.py` (since Milestone 7, `lib/stats/constants.py`) with its source, and the page lists the sources.
  - **Land count:** Karsten's 2022 formula. It's published for 60 cards (19.59 + 1.90 × average mana value − 0.28 × cheap draw/ramp spells) and 99-card Commander (31.42 + 3.13 × average mana value − 0.28 × cheap). The 40- and 20-card versions scale it the way he scales his 80-card one. They're our extrapolation and labelled as such, but they match Wizards' own Beginner Box and Jumpstart lists to within about 1 land.
  - **Colour sources:** Karsten's 2022 tables for 40, 60 and 99 cards. There's no published table for 20-card halves, so those get counts but no verdict.
  - **Commander:** the current Brackets and Game Changers, Scryfall's ban list and colour identity, and the minimum bracket that can be worked out from the list. Combos can't be judged automatically, and the page says so.
- **What the stats show:** by Karsten's formula, Gruul, Zombies, Angels and Rabbits are "low" by about 2-3 lands, and Finneas and Giada are low for Commander. That's within the formula's typical error of 2.75 lands, and his data came from competitive decks, so the page shows the verdict with that caveat.
- **Server:**
  - It answers only to the PC's name, `localhost` and IP addresses; other names can be added as `allowed_hosts` in `config.json`.
  - The image cache is capped at 1 GB.
  - Errors never show file paths.
  - Deck pages load in about 30 ms, and a new deck's card images take about 5 s the first time (Scryfall's rate limit).
- **Checking it on a phone:** headless Chrome won't lay a page out narrower than 500 px, so phone screenshots need Chrome's device emulation (the DevTools protocol) rather than `--window-size`.

**3. Practice-hand simulation** on the deck page.

**Done 2026-09-30.** The work is `lib/goldfish.py` (the simulation), `lib/jobs.py` (a small background-job runner that Milestone 5 can reuse), `GET /api/goldfish` and a "Practice hands" part on the deck page. It was committed on 2026-09-29 before its final check; the check and its fixes followed on 2026-09-30. 518 tests pass.
- **Review:** four reviewers checked it for exact maths, rules edge cases, speed/caching/jobs and phone screens. They found 18 problems (1 high, 4 medium, 13 low), and a fix pass fixed them.
- **Final check (2026-09-30):** five independent checkers re-ran every finding's reproduction, tried nearby variants, stopped the server six ways and took fresh phone screenshots.
  - 16 of the 18 fixes held. Two were only partly fixed and are now fixed: mana rocks with a cost, and the section nav's "Owned" link (Owned vs needed was still pushed down when a run finished while Practice's running box was on screen).
  - The checkers also found 20 new problems (4 medium). Two fix-and-recheck rounds fixed all the medium ones and most of the low ones, each re-checked by a separate agent:
    - A hard kill of the server (Task Manager, `taskkill /F`) during a run left its 16 workers running; they now exit by themselves.
    - Mana sources: Lotus Petal-style one-shot mana, Ordeal of Nylea, Cryptic Caves, Pathways (both faces), Uncharted Haven's chosen colour, Heraldic Banner and fetch lands that find a tapped land.
    - Mulligan bottoming keeps the only source of a colour the deck needs.
    - The page: Commander decks lead with "Kept fewer than 7" instead of the free-mulligan rate, and the chosen setup is easier to see in dark mode.
    - The CLI: shows ">99.9%" instead of 100.0, accepts pairings in either order, and exits cleanly on Ctrl+C.
  - `GOLDFISH_VERSION` is now 4, so older saved results are recomputed.
  - **Stopping:** no Python worker is left after Ctrl+C during a run, during worker start-up, with runs queued, or when idle; after closing the server's window; after a hard kill of the server; or after Ctrl+C on the CLI.
  - **Screenshots:** 390 px phone, light and dark, running and finished, for Gruul Ramp, Giada and Cats + Vampires, a Beginner Box half, and Giada at iPad width. Nothing overflowed and every one was looked at.
- **Known low issues, left open:** none touches a card in the collection, the decks or the products.
  - Payment is chosen greedily after a rock that makes mana at once, so very rarely a turn casts a little less than it could (it never happened in 3.2 million payment plans on the real decks).
  - Murmuring Bosk loses the {G} of its Forest type.
  - Mana abilities with a mill cost (Millikin), and creatures that grant themselves a mana ability (Citanul Hierophants, Manaweft Sliver), make no mana.
  - Utopia Sprawl, rituals and mana abilities without {T} (Wall of Roots, Lion's Eye Diamond) are ignored without a "What isn't counted" note.
  - On an exact tie the land drop plays a Pathway before a basic.
  - The CLI's `--all` table still shows the free-mulligan rate (about 50%) in the mull% column for Commander decks.
  - A few wording slips in the special-cards list (Polluted Delta's note, Guardian Sunmare, Desert searches).
- **What it shows on 2026-09-30** (target lists, on the play; Commander decks in multiplayer):

  | Deck | Mulligan | 3rd land on turn 3 | 4th land on turn 4 | Colour screw | Flood | 4-drop by turn 4 |
  |---|---|---|---|---|---|---|
  | Gruul Ramp | 19.7% | 85.3% | 63.6% | 6.3% | 6.6% | 69.3% |
  | Izzet Prowess | 22.2% | 83.6% | 59.9% | 10.7% | 11.7% | 7.0% |
  | Mono-Black Midrange | 15.5% | 89.3% | 71.6% | 0% | 6.8% | 37.7% |
  | Mono-Black Zombies | 22.2% | 83.5% | 59.8% | 0% | 9.9% | 14.1% |
  | Mono-White Angels | 19.7% | 85.6% | 64.1% | 0.3% | 9.2% | 43.6% |
  | Orzhov Removal | 14.0% | 90.8% | 74.7% | 9.0% | 8.3% | 40.9% |
  | Orzhov Vampires | 17.6% | 87.3% | 67.4% | 13.9% | 10.4% | 14.2% |
  | Selesnya Rabbits | 19.7% | 85.6% | 63.7% | 5.4% | 5.6% | 31.9% |
  | Finneas (Commander) | 50.7% free | 95.3% | 82.9% | 9.0% | 7.0% | 63.9% |
  | Giada (Commander) | 48.5% free | 95.9% | 83.8% | 0.9% | 7.8% | 86.4% |
  | Gisa (Commander) | 48.5% free | 96.0% | 83.8% | 0.2% | 4.7% | 70.5% |

  Colour screw is the share of turns with enough mana for a spell in hand but not the right colours; flood is the share of turns 4-8 with nothing to spend mana on. The Commander decks' mulligan figure is the free first mulligan; the page shows about 10% keeping fewer than 7. Orzhov Vampires and Izzet Prowess have the most colour trouble, and Izzet and Zombies miss their 4th land most often.

**4. Editor and saving:** autocomplete, the conflict check, auto-commit, and recalculated owned-vs-needed tables.

**Done 2026-09-30.** New files `lib/gitops.py` and `web/editor.js`; saving code in `lib/decks.py`, `pool.py`, `stats.py`, `cards.py` and `api.py`. 695 tests pass. [README.md](README.md) says how editing and saving work.
- **What it does:**
  - **Ways in:** an Edit button on a deck's page (target or owned-only list), New deck in the library, and Save as a new deck on product decks, Beginner Box halves and pairings.
  - **Adding cards:** autocomplete from the local card data, which also matches word starts ("llan elv") and offers "Did you mean" for typos, plus Paste a list in Arena/MTGO format. A new line gets a printing the pool owns, else the cheapest non-foil paper one; a per-line picker changes it.
  - **Checks:** deck rules show as warnings that mark the rows they're about (60 cards and 4 copies; Commander 100, singleton, colour identity, partners and Backgrounds, the ban list, Game Changers and bracket). Only unknown names, quantities outside 1-99 and a Commander section in a casual deck block a save.
  - **Saving:** Save shows what changes, the warnings and the commit message first. Then it writes only Deck Lab's parts of the file, adds the "Decklist changed in Deck Lab" line when a list changed, rewrites the owned-vs-needed table, and commits that one file alone (`git commit --only`) as "Deck Lab: save <Title> (edited by <name>)" or "Deck Lab: new deck <Title> (by <name>)".
  - **Other decks' tables:** a save lists other deck files whose tables no longer match the pool, and **Update their tables** rewrites them in one commit.
  - **Conflicts:** the page sends the file's sha256 as it loaded it. If the file changed since, the save is refused, with who changed it and when, and the page offers to re-apply your changes onto the latest version or discard them. A deck renamed since offers to open it.
  - **Drafts:** unsaved edits survive a reload or a phone going to sleep (kept per deck, list and profile), and leaving with unsaved changes asks first.
  - **Writes are protected from other web pages:** they need JSON, an `X-Deck-Lab: 1` header and a matching Origin, which covers the profile settings too.
- **Decisions made while building:**
  - **When a commit fails** (a hook, `index.lock`, a detached HEAD, a timeout), the file stays saved, the page says why in plain words, and the deck page offers **Commit now**. Deck Lab records the failure in `data/uncommitted-saves.json`, so the next save or Commit now commits it with the right message. A new deck whose first commit failed stays untracked (so `git stash` still works) and is committed as "new deck ... (by <creator>)".
  - **Changes made outside Deck Lab** (a hand edit, or Claude Code partway through a task) are shown on the deck page and in the editor before saving. A save of that file commits them, with a warning and a line in the commit message. **Update their tables** leaves such files out unless the user chooses Include them anyway.
  - **An empty target list** on a deck that had cards needs an extra confirmation.
  - **A rate above the table in any other wording** (another currency, a factor, "per USD", a second rate beside the stamp) blocks repricing. The note quotes what it found and says how to let Deck Lab reprice. When unsure, it blocks rather than add a second rate.
  - **File names from titles** drop apostrophes ("Ajani's Pride" gives `ajanis-pride` on any keyboard).
  - **Git runs** with a 30 s timeout that stops the whole process tree, never prompts, and never pushes.
- **How it was checked:**
  - Two builders, then 10 reviewers in parallel: six on the save side (file bytes, git, security, concurrency, deck rules, owned vs needed) and three phone reviewers of the editor.
  - They found 56 problems (no high, 22 medium). Fixers working on separate files fixed them, each round re-checked by separate agents.
  - A final round: two fixers and three verifiers (the save side with the test suite run twice; the whole editor at 390 and 820 px in light and dark as Matt and User1; repo safety).
  - Every save test ran in a throwaway clone. The real repo got no Deck Lab commits.
- **First real save:** on 2026-09-30 every deck file's table is already out of date, because orders were placed after the tables were written. The first save will list about 10 decks under "Update their tables", and that one commit reprices them all.
- **After the user's two steps (2026-10-01):** the user ran `network-setup.ps1 -PythonPrivateOnly` as administrator and reserved 192.0.2.10 in the router. `status` then gave 0 problems and 0 warnings, with exactly two Deck Lab rules left ("Deck Lab (TCP 8642)" and "Deck Lab (pythonw)", both Private and `LocalSubnet`). A phone on the home Wi-Fi (192.0.2.20) opened the page and loaded the library.
- **Known low issues, left open:**
  - A new deck whose first commit failed can get its first commit from Update their tables, under the tables message rather than "new deck".
  - Commit now after someone else's failed save is committed under the name of whoever clicks; the person who made the edit is named only in the commit message body.
  - Another built deck missing its Built version shows a technical pool warning (a file path and a field name) in every deck's checks.
  - Small wording slips: the Commander bracket box can say "No Game Changers" twice and has a double parenthesis; the renamed-deck message gives the new deck's id rather than its title.
  - A server killed mid-save can leave a `.<deck>.md.<pid>.tmp` file in `magic/decks/` (never committed).
  - The rate check blocks a few innocent numbers near a price word (by design) and misses a rate stated in cents.
  - A git hook's child programs can outlive a timeout (they hold no lock and don't delay the save).

**5. Forge matchups:** job queue, parallel workers, progress, and saved results, using the settings and checks in "Milestone 0 results", with each deck's AI-limited cards shown beside its results. Start from the trial's prototype scripts in `decklab/forge-trial/` (`to_dck.py`, `run_sim.py`, `run_matchup.py`, `card_audit.py`, and the card-log class in `java/`), and move what's kept into `lib/forge.py`.

**Done 2026-10-01.** New files `lib/forge.py` and `web/matchups.js`; matchup code in `lib/jobs.py`, `api.py`, `server.py` and `web/app.js`. 888 tests pass, plus real-Forge tests that run with `DECKLAB_FORGE_TESTS=1`. [README.md](README.md) says how to use it.
- **What it does:**
  - **Play a matchup** (the library's Matchups button, or a deck page's Matchups part): pick two lists of the same kind (a casual deck, product deck or Beginner Box pairing against another; a Commander deck against another Commander deck, played as 1v1 Commander) and 200 to 3,200 games, each with a rough time. A single Beginner Box half can't play, as with practice hands. A deck against itself can.
  - **While it plays:** a progress bar, the live score, games a minute, time left, who started it, and **Stop** (it asks first). Both phones see the same run. One matchup plays at a time, separately from practice hands, so those never wait behind it.
  - **The result:** the first deck's win rate, balanced for going first and second, with its 95% range as a bar; on the play and on the draw; draws and timeouts; game length; speed. Each deck's cards Forge's AI can't play, a team-pump flag, and the standing caveat. Also a "What each deck cast" table, **Play N more games** (adds to the same result), **Swap sides**, and "How these games were played" (Forge version, runs, who, when).
  - **Deck page:** the list's AI limits even before any game, its saved results against other decks (and its earlier lists', marked), and runs going now.
  - **Command line:** `python -m decklab.lib.forge status | audit <deck> | play <a> <b> | list`.
- **Decisions made while building:**
  - **Results are keyed by content:** the .dck holds only the Commander and Main cards, name-only and sorted (the sideboard is never used). The key covers both lists, the format, Forge's version, the per-game clock and the AI profiles. A vs B is B vs A, the same list under two names shares results, and an edited list gets a new key. A result for an older list is shown as "Older list", never mixed in.
  - **Card order matters to Forge:** with the same seed, the same cards in another order play different games (Forge builds the library in file order before shuffling). Sorting makes the games depend only on the cards, so a first run of two lists always replays the same games.
  - **Batches:** 100 games per Forge process, or 200 once every worker gets a batch (3,200 games on 16 workers), always an even number of batches with the decks' seats swapped in every other one. Seeds carry on from the last run, so "Play more games" adds new games. (Changed 2026-10-03 in simulation wave 1: at least 25 games per process and up to one process per worker, all started at once, so 200 games are 8 × 25 and 800 are 16 × 50; still an even number of batches, with the same seeds and seat swaps.)
  - **Stopping keeps every finished game:** a batch cut short is kept as a partial batch, and only the game in progress is lost. Stop, Ctrl+C, Ctrl+Break and closing the server's window all do this (closing waits at most 4 s, since Windows ends the process about 5 s after). Batches Forge failed (an unknown card, a deck that wouldn't load, a crash, a hang) never count.
  - **Process safety:** every Forge process sits in a Windows Job Object that kills it when Deck Lab ends, however it ends (checked with `taskkill /F`). Each also has a job of its own, so a stop kills its whole process tree. A watchdog kills a process that prints nothing for 3 minutes at start-up, or finishes no game for the per-game clock plus 90 s.
  - **"Never cast" comes from Forge's own log:** a nonland card cast 0 times once 100 or more games are counted is listed with the cards the AI can't play. It can't tell "never drawn" from "drawn but held" from Forge's log alone (Milestone 8's card log can: a never-cast card then says how many games it was drawn in), but a card in a 60-card deck is drawn in about a quarter of games, so 100 games is enough to notice. It found Fiery Annihilation in Gruul Ramp, as Milestone 0 did. A matchup's page judges from that matchup's games; a deck page adds up the list's games across all its saved matchups, and until they reach 100 it says only the card scripts were checked.
  - **Team pump flag:** 3 or more copies of instants and sorceries with Scryfall's `power-boost-to-all` or `overrun` oracle tags. It flags Selesnya Rabbits (both lists) and also **Finneas Rabbits' target list** (Hare Raising, Rabbit Response, Overrun). (Since 2026-10-03 the page and the audit use the wider "Forge pilots this deck poorly" flag from Forge's card scripts instead, and show this one only when those scripts can't be read; see the wave 1 entry.)
  - **Not meaningful:** a Commander deck whose commander the AI never casts (the Gisa decks, and the Wretched Ranks precon) gets its results marked as meaningless.
  - **Results stay out of git** (open question 1), in `data/forge/results/`, one file per matchup with every game's outcome. A results folder that can't be written stops a run before it starts. A lock stops two runs of one matchup at once (for example the page and the command line). A Forge upgrade starts new results.
- **How it was checked:**
  - Built by three agents in parallel (Forge core, API, page) against a written contract, then integrated and run end to end on the real server with real Forge.
  - Six reviewers in all: two on the Forge core while the rest was still being built, then four more (the API, the page on phones, the numbers end to end, and code quality). They found 46 problems (1 high, 9 medium). Fixers working on separate files fixed 45, each re-checked by a separate agent. The 46th, moving shared helpers into `decks.py`, was left for Milestone 7 (done there). The high one was that closing the server's window lost the playing matchup's games.
  - **Milestone 0's games replay exactly** through Deck Lab's command line: 400 of 400 games had the same winner and starting player (Izzet vs Gruul, seeds 210000-210001; and Angels vs Zombies, seeds 110000-110001).
  - **An independent check of the numbers:** a separate script recomputed every figure from the stored games of 4 real results, and found no differences. The trial's `run_sim.py` replayed two stored batches game for game (200 games: winners, starting players, turns and casts).
  - **Older lists:** in a throwaway clone, editing one card of a played deck gave it a new key, and marked the old result "Older list" on that side only.
- **Speed:** 823 games a minute for 3,200 games of Angels vs Zombies on 16 workers (Milestone 0: 790-905), with about 10 GB of memory. 1v1 Commander is slower: about 23-35 games a minute per process (200 games in 3-4.5 minutes).
- **What it shows on 2026-10-01** (balanced win rate of the first deck):

  | Matchup | Lists | Games | First deck wins |
  |---|---|---|---|
  | Mono-White Angels vs Mono-Black Zombies | owned | 3,200 | 52.5% (50.7-54.2), as in Milestone 0 |
  | Mono-White Angels vs Mono-Black Zombies | target | 800 | 55.6% |
  | Izzet Prowess vs Gruul Ramp | owned | 1,600 | 56.8% (54.4-59.3); Milestone 0 had 55.1 (53.9-56.3) with the same cards |
  | Selesnya Rabbits vs Orzhov Vampires | target | 200 | 36.7%, as in Milestone 0 (team pump flagged) |
  | Cats + Vampires vs Goblins + Elves | Beginner Box | 200 | 67.8% |
  | Giada vs Finneas | Commander, target | 200 | 85.6% |
  | Giada vs Gisa | Commander, target | 200 | 90.4%, not meaningful |

  Some of these were played in scratch folders, so the page doesn't list them all. The page's own results were played by the agents testing it, under the Matt and User1 profiles.
- **Known low issues, left open:**
  - On the command line, a second Ctrl+C while a run is stopping can record a batch that had just finished as failed, losing its games.
  - The deck-id helpers (finding a deck or pairing by id, and its kind) are copied in `api.py`, `forge.py`, `goldfish.py` and `stats.py`. They belong in `decks.py` (Milestone 7). Done: `decks.find_summary` and `decks.engine_kind`.
  - The deck page's Matchups part doesn't refresh by itself; its "Playing now" rows link to the live page.
  - On a phone, the runs table's time wraps onto two lines.
  - At 320 px, the deck page's "Matchups" and "Owned" nav buttons nearly touch (fine at 375 px and up).
  - A Commander run in "Playing now" isn't marked not meaningful until it has finished.

**6. Home-network setup:** firewall rule, reserved IP address, start at logon, and a README.

**Done 2026-10-01.** New files `lib/control.py`, `lib/homenet.py` and `network-setup.ps1`; the server's side in `server.py`. 1,089 tests pass. [README.md](README.md) says how to set it up and use it, and what to do when a phone can't reach it.
- **What it does:**
  - **Start at logon:** `python -m decklab.lib.homenet install` registers a Task Scheduler task, "Deck Lab", for the current user only (no administrator). At each logon, after 30 seconds, it runs `server.py` with `pythonw.exe` (no window) from the repo folder. `remove` stops the server and deletes the task. (Later on 2026-10-01 the logon trigger became off by default, at the user's request: `install --at-logon` turns it on; see part 8.)
  - **Stop, start and restart without a window:** `homenet stop` (or `server.py --stop`, or `taskkill /PID` without `/F`) asks the server to stop the way Ctrl+C does, so a playing matchup saves its games. `start` goes through the task, waits up to 20 s for the page to answer and prints the addresses, or, if it doesn't answer, what the server wrote to its log since that start. `restart` is for after changing Deck Lab's code or a git pull. Both first check that the task's `pythonw.exe` and `server.py` are still there, and stop nothing if they aren't. Neither `install` nor `start` starts a second server.
  - **The log:** a server with no window logs to `data/logs/server.log`, rotated at 2 MB with 3 old files kept; `--log FILE` picks another file, with or without a window. Crashes at start-up, in `main()` and in any thread land there too.
  - **Finding the running server:** `data/server.json` records its process, address, port, start time, Python, log and whether it has a window. It's written once the server listens and can be stopped, and removed when it exits. The server takes its port for exclusive use, so a second server can't share it, even on another address; it says which Deck Lab is running and how to stop it.
  - **Logging off or shutting down:** a hidden window hears of it, and the server stops as it does when its console window closes (at most 4 s for a matchup to save).
  - **status:** a checklist of the server, the task, the network, the firewall, the addresses for phones and the sleep setting, in about 2 seconds. Each line is OK, WARN or PROBLEM with a fix, and the exit code is 1 when anything is a PROBLEM. It's read-only and needs no administrator.
  - **The administrator step:** `network-setup.ps1`, run once from an administrator PowerShell after `install` (see part 8). `-DryRun` shows what it would do without administrator, and a second run changes nothing.
  - **The router:** the address reservation stays a manual step; the README and `status` give the MAC address and a typical router menu path.
- **Decisions made while building:**
  - **One stop event per port:** a named Windows event for this logon session only, `Local\DeckLab-stop-<port>`, so a test server on another port never touches the real one. The stopper waits up to 30 s for the process `server.json` names to end (the server waits up to 15 s for a matchup to save).
  - **The port is the server's alone:** even without address reuse, Windows let a second server listen on 127.0.0.1:8642 while the first had 0.0.0.0:8642, and both then ran, so a stop could reach the wrong one. The server now binds with `SO_EXCLUSIVEADDRUSE`, so the second one is refused. A restart still gets the port straight back.
  - **Start-up order:** the stop event and the hidden window are made once the port is bound and before `server.json` names the server, so anything that reads the file can stop it. Before, a stop during start-up was lost about 1 time in 8.
  - **A leftover `server.json` is ignored, never deleted:** after a hard kill or a power cut the file stays, and reads as "not running" when its process has ended or its process id now belongs to a newer process (Windows reuses them quickly). A second server never replaces the file while it names another live server; `--stop` still reaches the second one through its event.
  - **Session end needs a hidden top-level window.** A message-only window never hears that the session is ending, and a console program's logoff and shutdown events only reach services.
  - **`taskkill` without `/F` stops it properly:** it asks the hidden window to close. Windows' default would destroy the window and leave the server running, no longer hearing about logoff. Instead the window stays and the server stops as for a stop request ("Asked to close (taskkill): stopping." in the log). The window's own close uses a message of its own.
  - **The task's settings:** a 30 s delay after logon, which lets DHCP finish and keeps the server out of the desktop's way while it loads (the first card-data check needs the network, and a failed one waits 10 minutes). No time limit, since Task Scheduler's default of 72 hours would stop the server after three days. Normal priority (5), since the default (7) is below normal and would slow Forge and the page. Batteries don't matter, and a second start while it runs is ignored. The task is read back as XML, never as schtasks' translated text. `status` warns when any of these was changed in Task Scheduler.
  - **`start` always goes through Task Scheduler,** never starting `pythonw` itself: a process started from a tool's own shell can be killed when that shell's job ends. If nothing answers after 5 s, it asks Task Scheduler once more, since a run that had only just ended can still count as running, and the task then ignores the new start.
  - **Firewall rules are read through the firewall's COM object:** without administrator, `Get-NetFirewallPortFilter` stops partway with "Access is denied" (it returned 586 of 703 filters and missed both Deck Lab rules). The COM object returns all of them in about 40 ms. `network-setup.ps1` runs as administrator, so it uses the normal firewall cmdlets.
  - **The mDNS check asks for a direct answer:** Windows' own responder didn't answer a plain query sent from an ordinary port. Asked for a direct (unicast) answer, the PC answers `homepc.local` with 192.0.2.10.
  - **Which rules count and which warn:** a rule only counts as letting phones in when its addresses and kinds of connection take in the whole home network; one that may leave phones out is a WARN. Python's allow rules from Windows' prompt get a WARN only when they apply to Public networks, since `-PythonPrivateOnly` takes Public off and nothing more. A port rule (such as Deck Lab's own) also warns when it's open to any address: Deck Lab's own rules get "run network-setup.ps1" as the fix, any other rule a fix by hand. A block rule is a PROBLEM on Private networks and a WARN elsewhere.
  - **The home network** is the physical adapter (cable or Wi-Fi) that's up and has the internet route, never a VPN, even one with a lower metric. `status` and `network-setup.ps1` use the same test.
  - **More checks than planned:** `status` also warns when Deck Lab's code changed after the server started (restart), and when `pythonw.exe` has no firewall rule and no other rule lets the port in on Private networks (Windows may then show its prompt; a port rule is enough to stop it, as seen on 2026-10-01). It's a PROBLEM when the server listens on 127.0.0.1 only, when something has the port open but doesn't answer, or when "Block all incoming connections" is on for Private networks.
  - **`network-setup.ps1` changes only what it made:** it keeps a Deck Lab rule that's already exactly right, adds missing rules before removing anything, and removes only inbound allow rules with its two names or its own description. Other "Deck Lab (" rules (block rules, hand-made ones) are listed and left alone. So a second run says "Already right" and changes nothing. The port rule is named after the configured port.
  - **`network-setup.ps1` never runs Python:** it runs as administrator, so a `python` found on the PATH would run with administrator rights. It takes `pythonw.exe` only from the task or `-Pythonw`; without either it skips the pythonw rule and Python's rules. So `install` comes first.
  - **`network-setup.ps1` asks before making a network Private,** naming it, since that tells Windows to trust it. `-Yes` skips the question for a PowerShell that can't ask. `-PythonPrivateOnly` takes only Public off a rule (Any becomes Domain and Private), and turns off a rule that was for Public networks only. Without administrator, its message repeats the options given in the command to run.
  - **Times in the log:** the start-up line and the server's own messages now start with the date and time, since a log file has no other way to show when. A background server's start-up line says how to stop it instead of "Ctrl+C stops it".
  - **A broken `config.json` is logged:** `--host` and `--port` are filled in from `config.json` after the arguments are read, so under `pythonw` the error lands in the log rather than crashing before the log exists. `server.py --port N --stop`, and `homenet stop`, `status` and `remove` with `--port`, don't need `config.json`, so a broken one can't keep the server from being stopped. The other commands say it can't be read, with no traceback.
  - **Log rotation never loses a file to a held log:** the live log moves aside first and the old files shift only once it has, so a `server.log` another program holds open keeps `.1` to `.3`. A log write made from inside another one in the same thread (a warning Python prints, say) waits its turn instead of hanging every thread that logs.
  - **For tests only:** `DECKLAB_STATE_FILE` moves `server.json`, so the tests' real `pythonw` servers never touch the real one. `homenet --task NAME --port N` (and `install --host`, `--log`) run a throwaway task on another port. Test servers listen on 127.0.0.1, so Windows never asks about their firewall access.
- **What `status` found on 2026-10-01, before the network setup script was run:** the network was already Private (192.0.2.10/24 from DHCP), TCP 8642 was let in on Private networks, `homepc.local` answered and the PC never sleeps on mains power. But there were two "Deck Lab (TCP 8642)" rules, one of them open on every kind of network to any address, and `python.exe` had rules from Windows' prompt for every port on Private and Public networks. `pythonw.exe` had no rule until 11:42, when a test server on 0.0.0.0 on a port no rule covered made Windows ask about it; that left `pythonw.exe` rules just like `python.exe`'s. After the final restart, `status` gave 0 problems and 5 warnings: the wide Deck Lab rule, and `python.exe` and `pythonw.exe` (TCP and UDP) open on Public networks. A dry run of `network-setup.ps1 -PythonPrivateOnly` showed the 6 changes that clear them.
- **How it was checked:**
  - Built by two agents in parallel (the server side: `server.py` and `lib/control.py`; the task, status and setup script: `lib/homenet.py` and `network-setup.ps1`) against a written contract, with a docs writer.
  - Two early reviewers, one on the Windows process lifecycle and one on the task, firewall and status, found 22 problems (3 medium, 18 low, 1 observation). The medium ones: a second server could share the port on another address, so a stop could reach the wrong one; `taskkill` without `/F` destroyed the hidden window and left the server running, no longer hearing about logoff; and `start` and `restart` didn't check that the task's `pythonw.exe` and `server.py` were still there, so a restart could stop a working server and then fail to start it.
  - **A real run on this PC:** `install` registered the task, and the server started under `pythonw.exe` from Task Scheduler (its parent was the Schedule service), answering on 127.0.0.1, 192.0.2.10 and `homepc.local`. The suite passed with the real server running, and left it alone. No process in the server's tree showed a window, across 3,200-game matchups on 16 Forge workers and a deck save committed to git by a server in a throwaway clone. `homenet stop` during a matchup stopped it in 1.3 s and kept the 375 games it had finished. A simulated logoff (the two session-end messages sent to the hidden window) stopped it during another matchup within a second, keeping 112 games. `status` described the PC correctly.
  - Fixers working on separate files (the server side, and the task, status and script side) fixed every finding but the observation, each round re-checked by a separate verifier. A second round on the task side fixed what its verifier found: the network change now asks first, and five smaller edge cases.
  - **The final run (2026-10-01):** the suite (1,089 tests) passed with the real server running, which it left untouched. `homenet restart` put the final code on the real server through Task Scheduler in 2.5 s, and `status` gave 0 problems and 5 warnings. A real 400-game matchup stopped by `homenet stop` after 49 games kept all 49, left no Forge process behind, and `start` brought the server back in 1.7 s. On a throwaway server, `taskkill` without `/F` stopped it cleanly in about 1 s, and a second server on the same port with `--host 0.0.0.0` or `localhost` was refused. `network-setup.ps1 -DryRun -PythonPrivateOnly` showed exactly the right 6 changes, and a real run without administrator changed nothing (the same 705 firewall rules before and after). One last fix: the "needs administrator" message now keeps the options given (it used to drop `-PythonPrivateOnly`).
- **Known low issues, left open:**
  - Exclusive use of the port only stops other Deck Lab servers: Windows still lets another program bind the port on 0.0.0.0 beside a Deck Lab server on one address (127.0.0.1, say). The logon server, on 0.0.0.0, blocks every later bind of its port.
  - If another program holds `server.log.1` open (not `server.log`), a rotation that fails can still drop `server.log.3` and leave no `.2` until the next one. Notepad and VS Code don't hold the file open.
  - `status` and `network-setup.ps1` can pick different networks when the internet route is on a connection Windows doesn't list as an adapter, such as Windows' own built-in VPN connections: `status` then judges the VPN, and the script says the home network is already right.
  - After the network question is answered no (or PowerShell can't ask), the script still ends "Everything was already right: nothing changed." when nothing else needed changing.
  - Without the task or `-Pythonw`, the script leaves alone any rule it made that names a program, even a "Deck Lab (TCP 8642)" rule for another program. It takes a hand-edited rule to matter.
  - `status` says the script replaces a rule with the script's own description but another name, and the script never looks at it. The script only makes rules with its two names.
  - `start`'s phone address and `status`'s `homepc.local` check use the connection Windows routes through, so with a full-tunnel VPN up they would use the VPN's address.
  - `status`'s check of a rule's scope looks at its kinds of connection, not at a list of named connections.
  - Not tested yet: a real logoff, shutdown or logon (so the logon trigger and its 30 s delay, now off unless `install --at-logon`), and whether `homepc.local` works from a phone (the log doesn't show which address the phone used).

**7. Split up long source files** (added 2026-09-30, not a priority): no source file over about 1,200 lines, so files are easier to read and review, and parallel agents can each own separate files (in Milestone 4 only one agent at a time could edit `api.py`). Move code without changing behaviour, keep each module's public names working, keep the full suite passing, and do one file per commit.

**Follow-up audit, 2026-10-07:** the Forge runtime and command line, matchup page,
overnight harness and large test modules have grown since this milestone. Their
new boundaries, validation and the repeatable length check are recorded in
[SOURCE_AUDIT.md](SOURCE_AUDIT.md). The original completion record below is historical.

**Done 2026-10-01.** Six lib modules became packages and three web files became several, one commit each. Every function, statement and CSS rule moved with its text unchanged, apart from a few calls that now go through the part that owns a name (`common._log(...)`, below). 1,103 tests pass: the 1,089 from before, 5 added by the prep commits, and 9 guard tests. Three prep commits came first: the code-change check counts lib packages, one copy of the deck-id helpers (below), and test_web.py reading every file.
- **What went where:**

  | Before | Lines | After |
  |---|---|---|
  | `lib/api.py` | 3,383 | `lib/api/`: 12 parts (common, carddata, settings, library, card_lookup, deck_page, practice, forge_runs, drafts, commits, editor, saving), largest 546 |
  | `web/editor.js` | 2,972 | `editor.js` (state, models, drafts, entering and leaving, sheets) plus `editor-screen.js`, `editor-cards.js`, `editor-save.js` and `editor-deckpage.js`, largest 792 |
  | `lib/goldfish.py` | 2,429 | `lib/goldfish/`: common, model, engine, workers, results, runs, cli, largest 819 (the game loop) |
  | `web/app.js` | 2,363 | `core.js` (shared helpers and state), `library.js`, `deck.js`, `stats.js`, `practice.js`, and `app.js` (the shell, loaded last), largest 605 |
  | `lib/forge.py` | 2,322 | `lib/forge/`: common, install, lists, processes, logreader, saved, runner, ai, views, cli, largest 533 |
  | `lib/stats.py` | 1,916 | `lib/stats/`: constants (every figure and its source), cardtext, deckparts, colourcheck, commander; deck_stats and the command line stay in `__init__.py` (484) |
  | `lib/homenet.py` | 1,872 | `lib/homenet/`: common, task, commands, gather, mdns, checks, largest 791 |
  | `lib/decks.py` | 1,821 | `lib/decks/`: decklist, deckfile, edit, render; the library, products and file writing stay in `__init__.py` (567) |
  | `web/style.css` | 1,403 | `style.css` (theme tokens and the shared rules, 926), `matchups.css`, `editor.css`, `devices.css` |

  The tests followed the code: `test_decks.py` became four files, `test_goldfish.py` two, and `test_homenet.py` four plus a shared `homenet_support.py`. The other test files kept their names; only their patch targets changed.
- **Left as they were:** `matchups.js` (1,186 lines; Milestone 8 grew it and moved its per-card part to `matchups-cards.js`), `cards.py` (1,026), `server.py` (1,003), `control.py` (757) and `pool.py` (738). The audit found no seam worth the extra files and moved patch targets. `server.py` must stay the script Task Scheduler runs.
- **Decisions:**
  - **A package keeps the old name working.** `decklab.lib.api` is now the package; its `__init__.py` keeps the module's docstring (the contract other docs point to), lists the parts, and re-exports the old names, so `api.deck_view(...)` and every other caller are unchanged. Commands like `python -m decklab.lib.forge play ...` work through each package's `__main__.py`, with the same help text and exit codes.
  - **One home for every name a test patches.** A test's `mock.patch.object(api, "_log")` only changes `api`'s own binding, so after a split it can silently stop reaching the code. Each name that tests patch or reset, or that's rebound while running, now has exactly one binding, in the part that reads it (or read through it, as in `common._log(...)`). The tests patch that part, and a patch left on the package fails loudly: api, homenet and stats leave those names off the package, while goldfish and forge refuse to have them set on it. A guard test in each package checks this. decks keeps every patched name in its `__init__.py`, beside the code that reads it.
  - **Run-time names outside a package read the part:** `server.py` reads `api.carddata.UPDATE` and `api.forge_runs.FORGE_JOBS`.
  - **Web files stay flat in `web/`** (the server only serves `web/` and `web/icons/`), each script with its own `"use strict"`. The scripts load in this order: `editor.js`, `editor-screen.js`, `editor-cards.js`, `editor-save.js`, `editor-deckpage.js`, `matchups.js`, `core.js`, `library.js`, `deck.js`, `stats.js`, `practice.js`, `app.js` (Milestone 8 added `matchups-cards.js` after `matchups.js`). The stylesheets keep the old file's rule order (`style.css`, `matchups.css`, `editor.css`, `devices.css`), since the cascade depends on it.
  - **test_web.py reads every file:** its checks search every script the page loads, every stylesheet and a whole lib package, so moving a function between files needs no test edited and no check reads less. It also checks that every `.js` and `.css` file in `web/` is loaded, and in the right order.
  - **The deck-id helpers have one copy:** `decks.find_summary(deck_id)` (a pairing's halves in either order; `None` when there's no such deck) and `decks.engine_kind(summary)`. api, forge, goldfish, stats and pool use them, and each caller still treats "no deck" as it did. One change for the better: `python -m decklab.lib.stats` now finds a pairing given in either order.
  - **The code-change check counts packages:** `homenet status` looks at every `.py` file under `lib/`, so it still says when the background server needs a restart.
- **How it was checked:**
  - **The audit:** 14 agents read every file over about 800 lines and listed its jobs (with every name), shared state, callers, every test patch aimed at it, and a proposed split. A cross-cutting one listed what depends on the layout, and the deck-id helpers' exact behaviours.
  - **The splits:** 9 agents, each in its own git worktree, split one file each at the same time. Each split was checked by a separate agent that re-ran every check and fixed what it found (some header comments that misdescribed their file, an unused import). Then the splits were merged onto one branch, one at a time, with the full suite after each merge.
  - **Mechanical checks, run on each split and again at the end:**
    - every top-level unit of the old file is in exactly one new file with the same text, apart from the listed `common._log`-style edits;
    - every old name is still on the package;
    - the same tests exist;
    - the suite leaves the repo untouched (so no patch let a test write to a real path);
    - an instrumented run records whether every patch's mock was still called (none stopped);
    - 14 screens rendered in headless Chrome had the same page and pixel-identical screenshots at 390 px and 1,280 px.
  - **End to end on the real data:** the merged code and the code before the split gave identical answers to 175 API questions (every deck page, editor view, practice result, saved matchup, search and error answer, plus two draft checks), identical pages and screenshots on all 14 screens, and identical output from 22 command lines (apart from timings). The goldfish split also gave byte-identical simulation results, run with real worker processes.
- **Known low issues, left open:**
  - Git sees each package as a new file, since its `__init__.py` is too unlike the old module to count as a rename. So `git log --follow decklab/lib/api/__init__.py` stops at the split; `git log -- decklab/lib/api.py` shows the history before it.
  - Each package keeps patch targets in one place, but by its own means (described in its `__init__.py`): decks keeps them in `__init__.py`, api, homenet and stats leave them off the package, and goldfish and forge refuse to have them set on it.
  - `test_forge.py` (1,685 lines), `test_api.py` (1,428), `test_editor.py` (1,403) and `test_server.py` (1,368) are still long. Tests weren't part of this milestone; the forge audit sketched a fixtures split.
  - `python -m decklab.lib.stats <pairing> --owned` still ends with a DeckNotFound traceback rather than a sentence, as it did before.
  - A git worktree's checked-out files can have other line endings than the main checkout's (Deck Lab writes deck files with LF, git checks them out with CRLF), so their sha256 differs. That matters only when comparing two checkouts, as this milestone's end-to-end check did.

**8. Per-card stats from the card log** (from the Later list, 2026-10-01): run every matchup through the card log, so each card's numbers come from Forge's games: how often it's drawn, cast once drawn, stuck in hand, the turn it's cast, and the win rate when it's drawn and when it isn't.

**Done 2026-10-01.** New files `lib/forge/simjar.py` (building the card-log jar and deciding when it can be used), `lib/forge/cardlog.py` (reading its lines, checking each game, a batch's tallies), `lib/forge/cardstats.py` (the numbers the page shows) and `web/matchups-cards.js`; DeckLabSim's source moved from `forge-trial/java/` to `lib/forge/java/decklab/DeckLabSim.java`; changes in `runner.py`, `logreader.py`, `saved.py`, `ai.py`, `views.py`, `install.py`, `cli.py`, `api/forge_runs.py` and `web/matchups.js`. 1,278 tests pass. [README.md](README.md) says how to read the numbers and what to do after a Forge upgrade.
- **What it does:**
  - **The matchup page** has "How each deck's cards played" (when a side has card data; otherwise "What each deck cast" as before): one panel per side, the commander first, then spells, then lands. Each card: drawn (share of games), cast once drawn (a land: played), stuck in hand at the end, average turn, and under it the win rates when drawn and when not, to one decimal, with the difference and its range, and a verdict ("Won more when drawn", "Won less", "No clear difference") only once the card has 30 games each way. (Since 2026-10-03 a "more" or "less" verdict also needs a Benjamini-Hochberg 10% discovery among the deck's cards, and each card shows a best estimate; see the wave 1 entry.)
  - **The deck page's Matchups part** has "How its cards played", pooled over every saved matchup of the list. It leads with what stands out, counted: the commander's casts, the spells most often stuck in hand (20 or more copies drawn, 20% or more stuck), cards drawn and never cast, and the clearest win-rate differences (three each way, never lands). The full tables sit in a collapsed "Every card's numbers".
  - **Coverage is always said:** "From 1,600 of the 4,636 games", with why the rest have no numbers (played before the card log, or while it was off; logged by an earlier version of it; or a card log that failed its checks). Numbers from fewer than 100 games with the card log are marked early (800 since 2026-10-03).
  - **AI limits:** a never-cast card says "drawn in N games, never cast" when card data covers all the games.
  - **Status:** `forge status`, the page's Forge box and "How these games were played" say whether runs keep the card log, and why not.
  - **Command line:** `python -m decklab.lib.forge cards <deck> [--owned] [--json]` prints the pooled table; `cardlog-check [--games N]` checks the card log after a Forge upgrade.
- **Decisions made while building:**
  - **Always on when it can be:** the card log plays the same games as plain Forge, so the matchup key doesn't change (FORGE_RUN_VERSION stays 1) and results mix batches with card data and older ones without. When it can't be used, runs play plain Forge, keep no card data, and say why.
  - **When it can be used:** the JDK's javac and jar sit beside java.exe; the jar builds; and this Forge was checked with it: its version (`simjar.CHECKED`), its build (the jar manifest's Implementation-Version, `CHECKED_BUILDS`; snapshots keep the release's name) and DeckLabSim's source (`CHECKED_SOURCE`, its SHA-256 with line endings made LF; a test fails when the Java changes, until `cardlog-check` is run and the constant updated). Since 2026-10-03 that source also covers Deck Lab's copies of Forge's classes and the SHA-256s they're pinned to (`simjar.PATCHES`). `cardlog-check` records other versions in `data/forge/cardlog/checked.json`. A failed check turns the card log off for that Forge; one that can't tell (a time limit, or Commander games that differ the way plain Forge's own do) changes nothing.
  - **Deck Lab builds the jar** at the start of a run, never in `status()`, under an OS lock, into `data/forge/cardlog/decklab-sim-<version>-<stamp hash>.jar`, with a stamp beside it (source, Forge jar, javac; since 2026-10-03 also the copies of Forge's classes that fit that Forge jar, so the jar's name says what it holds). It's named by its stamp, so a rebuild never replaces a jar a running batch uses. A build that fails is remembered, so `status()` says why until it builds.
  - **The dump point:** DeckLabSim writes each seat's deck on Forge's GameEventGameStarted (every library filled and shuffled, commanders in the command zone, nothing drawn yet), plus a `DL|commander` line in Commander and a `DL|log|1` line first in every game.
  - **Only per-batch tallies are stored** ("cards" in each batch: per side and card, drawn games and wins, copies drawn, cast, stuck, discarded, the rounds first cast, casts from anywhere but the hand; per commander, its casts). No per-game events or raw logs: a result grew 12% (101,819 bytes against 90,553 for 800 games).
  - **A game counts only when its card log passes five checks:** a known format; both seats' deck, kept hand, end hand and library size; every move replayed adds up to the end hands and libraries; the kept hand matches Forge's own count; every land play has its move. Otherwise it counts as "bad" for both sides, and the runner logs why.
  - **Definitions** (the docstrings of `cardlog.py` and `cardstats.py` have them in full): drawn = reached the hand (the kept hand, a draw, a tutor or a return); cast = moved from the hand to the stack or the battlefield; a cast the AI starts and can't finish (Forge's "Couldn't add to stack, failed to target") doesn't count; stuck = in the hand at the end (a copy can be both cast and stuck); turn = each player's own turn number.
  - **Win rates are raw,** not balanced for play and draw (that moves a card's rate about a point). Ranges: Wilson's for each rate and Newcombe's for the difference. Long games draw more cards, so a difference says what happened, not why; the page says so once.
  - **Lands get no verdict:** the games without a copy of a land were mostly short of lands or of its colour (Milestone 8's first numbers had Plains "+43 points" in Orzhov Removal).
  - **Record version 2:** records made before the failed-cast fix are version 1. They're left out of the numbers and counted as "old" games, which the page names.
  - **The per-card part of the page is its own file,** `web/matchups-cards.js` (374 lines), moved with its text unchanged and checked unit by unit and by pixel-identical screenshots, so `matchups.js` stays near Milestone 7's 1,200 lines (1,250).
- **How it was checked:**
  - **The build:** four agents in parallel against a written contract (launch and Java, the parser, the numbers and API, the page), each reviewed as soon as it finished and fixed by an agent owning the same files. Those reviews found 15 problems (no high, 4 medium).
  - **Two more reviews:** code quality and docs; and the Java against Forge 2.0.15's own `SimulateMatch.java` and `Main.java`, fetched from GitHub and diffed line by line (they match apart from the documented hook), plus the upgrade path. They found 15 more (5 medium): a check wasn't tied to the Java source, `cardlog-check` played Constructed only, and why a game's card log failed was thrown away, among others.
  - **Five verifiers on real Forge and real data,** in a git worktree frozen at the built commit while fixers worked in the main checkout:
    - Milestone 0's games replay exactly with the card log on: 1,200 of 1,200 (Izzet vs Gruul, Angels vs Zombies), every batch's card log passing.
    - Plain Forge against the card log through Deck Lab: 800 of 800 Constructed games and 100 of 100 Commander games the same (winner, starter, turns, rounds, result), and every batch's casts and land plays.
    - Speed: 800 games with and without the card log side by side, on the same seeds: 292.8 s against 291.9 s (+0.3%).
    - An independent recount with Milestone 0's own parser (`parse_log.py`): every per-card number of 10 batches matched, and the commander tallies too.
    - Every number the page, the API and `cards` give, recomputed by a script that imports nothing from Deck Lab: all matched.
    - Stopping (Ctrl+C, the page's Stop), a Forge process killed hard, a missing JDK, a jar that won't build, two runs building at once, and phone screens at 390 and 1,280 px in light and dark.
  - **What they found:** a failed cast counted as cast (Felling Blow showed 90% cast against Forge's 60%), lands topping the "clear differences", a win-rate sentence that could contradict its own rounded numbers, `status()` saying "ready" after a failed build, and a rebuild that could replace a jar in use. Three fix rounds fixed them, each re-checked by a separate agent.
  - **Plain Forge doesn't replay Commander games line for line:** two plain runs on the same seed listed attackers in another order and blocked differently, with the same winners, starters and turns. So `cardlog-check` compares Commander games by outcome. (Milestone 0's "seeded runs replay exactly" compared winners, turns, starters and loss reasons, `forge-trial/formats.md`.)
  - **The real results were played twice** (2026-10-01, by "Claude (Milestone 8 check)", 6,000 games each time): once before the failed-cast fix (now "old") and once after. Every card log of both passed its checks.
- **What it shows on 2026-10-01** (as Forge's AI plays the decks; target lists for Rabbits, Vampires and the Commander decks, owned-only for the rest; 400-2,400 card-log games each):

  | Deck | Most often stuck in hand (of copies drawn) | Drawn, never cast | Won most more when drawn |
  |---|---|---|---|
  | Gruul Ramp | Pelakka Wurm 65%, Terror of Mount Velus 62%, Savage Ventmaw 60%, Rampaging Baloths 57%, Lathliss 51% | Fiery Annihilation (397 games) | Clifftop Lookout +12.9, Surrak +10.4, Rabid Gnaw +9.7 |
  | Izzet Prowess | Counterspell 39%, Essence Scatter 34% | none | none clear; Stormcatch Mentor and Scorching Dragonfire won less (-7) |
  | Orzhov Removal | Massacre Wurm 56%, Stroke of Midnight 40% | none | Inspiring Overseer +16.8, Court of Grace +14.7, Go for the Throat +13.4 |
  | Mono-Black Midrange | Massacre Wurm 43%, Eaten Alive 33% | God-Eternal Bontu (303 games) | Massacre Wurm +11.8, Grave Titan +11.4 |
  | Mono-White Angels | Linvala 46%, Court of Grace 40% | Devout Decree (447 games) | Giada +14.5, Lyra Dawnbringer +13.8, Inspiring Overseer +13.5 |
  | Mono-Black Zombies | Grave Titan 54%, Moan of the Unhallowed 49% | none | Deathmark +14.6, Go for the Throat +12.2; Lord of the Accursed won less (-10.6) |
  | Selesnya Rabbits | Rabbit Response 55%, Overrun 54%, Byrke 39% | none | Valley Questcaller +14.2, Burrowguard Mentor +10.9 |
  | Orzhov Vampires | Crossway Troublemakers 34% | none | Vampire of the Dire Moon +14.8, Ajani's Pridemate +14.0 |
  | Giada (Commander) | Sunblast Angel 84%, Austere Command 74% | none | Giada cast in every game, first on turn 2.4 on average |
  | Finneas (Commander) | Rabbit Response 67%, Overrun 65%, Primal Might 62% | Beast Within (57 games) | Swords to Plowshares +19.4, Valorous Stance +17.4 |

  Gruul's top end is stuck in hand in more than half the games it's drawn, as Milestone 0 found on 220 games. Rabbits' and Finneas's team pumps are held about 55-67% of the time: the team pump flag, now measured. The never-cast cards are the ones Milestone 0 found the AI can't play. Differences are in percentage points, from Newcombe's ranges that exclude 0.
- **Known low issues, left open:**
  - A card Gemstone Caverns exiles from the opening hand counts as drawn but not cast. None of the decks has one.
  - The fake Forge the tests use doesn't model failed casts (a real fixture game does).
  - The recount couldn't replay a batch with a clock timeout (it depends on the wall clock), so reading moves logged after the end of a timed-out game is only checked by unit tests. The three timeouts in the real results passed their checks.
  - A build failure is remembered per process: a server's status clears when the jar it would build exists, or at its next run.
  - A Forge build is told apart by its manifest's Implementation-Version (snapshots give only a month and day), not by the jar's own hash.
  - The deck page can't tell "the per-card numbers failed" from "no card data" (both come as None), so after a failure it says none of the list's games kept the card log.
  - When a result's only card data is old, the coverage line names the old games but not the others played without the card log.
  - Each record's "first" counts (games each side went first) aren't used yet; they would allow per-card rates balanced for play and draw.
  - Spells drawn in nearly every game can still get verdicts, from the few short games without them.
  - `test_forge.py` is 2,165 lines. Tests weren't held to Milestone 7's limit.
  - Under heavy load a test can fail once: `test_the_first_use_of_the_user_folder_starts_one_process_alone` did (an empty row in the fake's start log), and one full run of the final suite had one failure that wasn't captured; it passed alone 8 times and in 3 more full runs.

**Desktop layout** (2026-10-01, asked for by the user for the PC's QHD screen, used maximised): `devices.css` has two new blocks.
- **From 1,600 px** (a 1080p window gets it too; an iPad in landscape, at 1,366 px or less, doesn't): the page widens to 2,560 px, the grids take more columns (library, matchups, stats panels, with the curve and the sources two columns wide), and long notes, boxes and the owned table keep to 1,280-1,400 px. The decklist turns into a grid of card pictures about 200 px wide, the copies on a badge on the art and the name under it; the editor's pictures go from 40 to 64 px. From 2,200 px the pictures and the peek get bigger.
- **The card peek** (`deck.js` peekLayout, peekable, setUpPeek), from 1,600 px with a mouse (`hover: hover` and `pointer: fine`): a column on the right of the deck page and the editor showing the card last pointed at or focused, 488 px wide on the QHD screen (the normal image's own size). It follows the decklist, card names in the stats, practice and owned-vs-needed parts, the editor's rows and its search suggestions (the arrow keys too). The small picture fills in while the big one loads, so a name never shows under another card's picture. It's `aria-hidden`, since the overlay already gives screen readers the card. The matchup pages don't have it.
- **Images:** thumbnails have a `srcset` of the small (146 px) and normal (488 px) images, with `sizes` saying how wide the layout shows them, so phones keep the small image and only the wide layout fetches the normal one. The peek's image is lazy and `display: none` elsewhere, so a phone never fetches it.
- **Checked** with screenshots through Chrome's DevTools protocol at 2,545 x 1,270 (light and dark), 1,905 x 950, 1,700 x 1,000, 820 px (iPad) and 390 px (phone): the deck page, a Commander deck, the editor with search open, the library, the matchups page and one matchup. Phones and the iPad are unchanged. `test_web.py` checks the blocks, the `srcset` and the peek's set-up; all 1,279 tests pass.

**Review repairs** (2026-10-01; moved here from PLAN.md's "Goal" on 2026-10-12, as written then. Since then `scripts/refresh_deck_tables.py` became `python -m decklab.db deck tables` (phase 4), and the inventory and the decks moved into the database, so "publish atomically" and "every file" describe the files of the time; PLAN.md's note on the R03 lead verdicts builds on the lead comparison below.)
- inventory imports validate quantities and publish atomically; ordinary basics in product lists are excluded before identity matching. `scripts/refresh_deck_tables.py` keeps saved availability and substitute-list arrival notes current after stock changes. The editor rejects newly added digital-only cards and reports failed browser draft storage before allowing navigation away. Practice-hand cache version 5 corrects land subtypes used by fetch/check/return logic. Forge's balanced win-rate ranges now retain uncertainty at all-win/all-loss boundaries, and its lead comparison includes both decks' wins and nonwins. Existing Forge game records remain usable; derived ranges and comparisons are recalculated when read.
- Validated with 1,380 tests (two opt-in real-Forge checks skipped), plus isolated browser-storage, inventory write-failure and availability-refresh regressions. All 11 saved deck tables match the pool, and both decklists in every file remain unchanged. Inventory, pending orders and product receipt statuses were not changed. Visual browser checks were unavailable in this session.

**Simulation speed and accuracy, wave 1** (from the Later list, 2026-10-03): the first of three waves of the plan in [forge-trial/sim-investigation.md](forge-trial/sim-investigation.md) (its §3-§5). Wave 1 is the quick wins and statistics fixes that don't change the games Forge plays for a seed, so the matchup key and `FORGE_RUN_VERSION` stay the same and every saved result stays valid.

**Done 2026-10-03.** Five packages, each built in its own git worktree, reviewed, fixed and re-checked, then merged one at a time with the full suite after each merge. New files `lib/forge/slots.py` and `lib/forge/java/forge/game/mulligan/AbstractMulligan.java`; changes in `lists.py`, `runner.py`, `processes.py`, `install.py`, `simjar.py`, `views.py`, `ai.py`, `cardstats.py`, `saved.py`, `cli.py`, `config.py`, `api/forge_runs.py`, `web/matchups.js`, `matchups-cards.js`, `deck.js` and `matchups.css`. 1,560 tests (3 skipped), all passing apart from one failure that predates wave 1 (`test_guide` on The Free Peoples' deck file).
- **What changed:**
  - **Batches (R02):** a run is split into the largest even number of batches, at least 2 and at most `min(forge_workers, games ÷ 25)`, that divides the games, so every batch starts at once. With 16 workers: 200 games are 8 × 25 (was 2 × 100), 400 are 16 × 25 (was 4 × 100), 800 are 16 × 50 (was 8 × 100); 1,600 and 3,200 are unchanged. With 8 workers 3,200 games are 8 × 400; with 12, 400 are 10 × 40. `forge_batch_games` no longer changes anything and is no longer checked; it stays in `config.json`'s defaults so older files load. The page's rough time follows the same rule.
  - **`-XX:ActiveProcessorCount=2` (R01a):** each Java process sizes its compiler and garbage-collector threads for 2 CPUs instead of 32 (see "Installing and running Forge").
  - **No 100 ms pause per mulligan (R04):** the card-log jar holds a copy of Forge 2.0.15's `AbstractMulligan` without the pause and goes first on the class path. The copy is pinned to the SHA-256 of the Forge class it replaces (`simjar.PATCHES`); with any other Forge the jar is built without it and Forge's own class plays. Plain Forge (card log off) keeps the pause.
  - **A budget for the whole PC (R18):** `forge_workers` is shared by every run on the PC, the server's and every command line's, in every checkout. Each Forge process holds a slot, an OS lock on a file in `%LOCALAPPDATA%\DeckLab\forge-slots` that goes with the process however it ends. A run starts as many processes as it gets slots for and the rest as slots come free; with none free it waits, and the page, the running list and `play` say "Waiting for other Forge runs on this PC to finish." `python -m decklab.lib.forge slots` shows who holds them. Run records gain `waited_s` and `most_running`. `cardlog-check` takes slots too.
  - **Below-normal priority (R18):** on Windows, Forge's processes start at `BELOW_NORMAL_PRIORITY_CLASS`, so the PC's other programs and practice hands come first.
  - **Lead verdicts and the starting player (R03):** see the note under "Goal". On the 36 saved results, the 32 "ahead" verdicts are unchanged and no lead flipped; the 4 old "No clear lead" results became 2 "about even" (Zombies vs Lightning Aggro; Mono-Black Midrange vs Orzhov Removal, owned lists) and 2 "not settled". Every starter tile moved to 46.8-56.4% (Fellowship vs Angels was 13.8%, now 50.3%).
  - **Trust labels (R19):** "How far to trust these numbers" on the matchup page and the pilot box on the deck page (see the caveat in part 6). Flagged: Selesnya Rabbits (6 team pump copies in the target list, 7 in the owned list), The Free Peoples (5 weak copies of 4 needed), Finneas (4 and 5 team pumps), Gisa and the Wretched Ranks precon (the commander), and Hare Raising. Not flagged: Gruul, Izzet, Angels, Mono-Black Midrange (3 of 4), Orzhov Removal, Giada (5 and 6 of 6.67), Calling All Angels, Zombies, Vampires, Lightning Aggro and Otter Limits. The audit gives one team pump count, from Forge's scripts, split into spells and permanents' abilities.
  - **Per-card statistics (R11 items 1-3):** pooled matchup by matchup, a best estimate for each card, Benjamini-Hochberg 10% before "won more/less when drawn", and early below 800 games (see "Per-card stats" in part 6). The `cards` command prints the best estimates and says when a range clear of 0 is within chance. Item 4 (the "in hand by turn 3" tally) needs a new card-log record version, so it's in wave 2 (done there).
- **Decisions made while building:**
  - **Practice hands take no slots.** A practice run lasts about 1-1.5 s and a Forge process takes 10-26 s just to start, so holding Forge back for practice workers would cost the Forge run more than it gave practice. Priority sorts them out instead.
  - **Priority is lowered on Windows only;** elsewhere Forge keeps normal niceness.
  - **The mulligan copy is pinned by SHA-256** and named in the card-log jar's stamp, rather than built as a separate class-path entry. That answers the report's "tied to the card log" risk: after a Forge upgrade the copy drops out by itself, and the card log still builds.
  - **The per-card spread** is r5's 4.5 points averaged with each list's own estimate by precision (`SPREAD_DOUBT`), not a hard switch between them, which gave some lists a spread of 0 and pulled every card to 0. On the real data it gives 2.5-9.2 points.
  - **Commanders are in the Benjamini-Hochberg family**, so on a Commander deck's matchup page (about 62 cards compared) a card needs a stronger result at 200-400 games.
  - **"About even" is ±5 points**, the owner's choice.
- **How it was checked:**
  - Each package had a builder, a reviewer, a fixer and a re-check. Every merge ran the full suite.
  - `cardlog-check` passed with the new jar (20 Constructed and 4 Commander games the same as plain Forge), and 200 seeded Izzet vs Gruul games were identical line for line with and without the mulligan copy.
  - The verdict changes were replayed over all 36 saved results, read only. The per-card changes reproduce r5's 48 of 407 changed verdicts exactly (43 with the range used here); 49 of 666 deck-page verdicts and 130 of 1,712 matchup-page verdicts change.
- **Measured after the merge** (2026-10-03, idle-gated, background CPU 0.7-3.8% before each run; before = main at `b44a78f`, after = wave 1, both with the card log; Izzet Prowess vs Gruul Ramp with Deck Lab's real seeds, two runs each):

  | Games | Before | After | Games a minute | CPU average | Peak memory (Forge) |
  |---|---|---|---|---|---|
  | 200 | 2 × 100, 56.1 s | 8 × 25, 30.7 s | 214 → 391 (1.83x) | 13 → 47% | 1.4 → 5.5 GB |
  | 800 | 8 × 100, 82.4 s | 16 × 50, 66.5 s | 583 → 722 (1.24x) | 47 → 82% | 4.6 → 11.7 GB |
  | 1,600 | 16 × 100, 118.1 s | 16 × 100, 108.7 s | 813 → 884 (1.09x) | 76 → 79% | 9.6 → 11.7 GB |
  | 3,200 | 16 × 200, 202.1 s | 16 × 200, 186.6 s | 950 → 1,029 (1.08x) | 71 → 72% | 9.2 → 11.7 GB |

  - All four match the plan's estimates. Slowest start-up went from 5.7-6.1 s to 3.8-4.1 s at 16 processes. 400 games wasn't timed.
  - **Same games:** at 1,600 and 3,200 games, where the batch shape didn't change, every game and every card-log tally was identical before and after, in both pairs of runs.
  - **Rabbits vs Vampires,** 800 games as 16 × 50 in both: 242.1 → 229.1 s, and 752 of 800 games the same. The other 48 are all in one batch, from a game that ran into the 120 s clock before (120.2 s, a timeout) and finished at 114.8 s after (a win). Games that close to a time limit can go either way between any two runs.
  - **Commander,** Giada vs Finneas, 400 games (after only): 128.5 s, 187 games a minute, no AI timeouts.
  - **The mulligan copy (M2):** the same games, but no gain measurable at 16 processes (within about ±3%); a lone process was 5.6% faster, half of what the pauses take. So the 200- and 800-game gains come from the batches and the flag.
  - **R14a, the AI's decision thread as a Java virtual thread (prototype only, not shipped):** 6-7% faster at 16 processes and 9% with one process on Izzet vs Gruul, with identical games; Rabbits vs Vampires about 2.6% (one run, within noise). Its steps for adoption are in `forge-trial/sim-investigation/w1/r14a/README.md`; it's for wave 2 (adopted there).
  - **Priority and slots:** every Forge process ran below normal while Python stayed normal. Two 400-game command-line runs started 1.5 s apart never had more than 16 Forge processes between them (the second waited 37 s, recorded as `waited_s`). A run killed with `taskkill /T /F` left no slot held and no Forge process.
  - **M8, for wave 2** (read only, on the investigation's 12,800 logged games): counting a card as drawn only when it was in hand by the side's own turn 3 removes the game-length skew (a card with no effect reads -0.5 to +0.1 points on the saved results, against -6.4 to +9.4 today), and it calls Fiery Annihilation, which Forge never casts, "won less" (today "unclear"). Expensive cards move down under it. Forge's colour screw matches the practice-hand simulation for Gruul, Izzet and Rabbits to within half a point; Orzhov Vampires is about 2.7 points worse in Forge, mainly because its AI never plays Evolving Wilds on turn 1, so tapped lands come down when the mana is needed (a candidate for R16's pilot experiments).
- **Known low issues, left open:**
  - The page's rough time leaves out each process's start-up, so 200, 400 and 800 games all say "under a minute" (measured: 31 s and 67 s for 200 and 800).
  - Bigger batches lose more games when a batch fails: 2 × 1,600 with 1 worker, 8 × 400 with 8. A stopped run still keeps its partial batches.
  - The "waiting" message shows about a second late, since progress is throttled. Two runs waiting for slots are served first come, first served, with no stricter fairness.
  - A Forge upgrade that drops the mulligan copy says so only in a log line (and in a test that runs with `DECKLAB_FORGE_TESTS=1`); the page and `status` don't show it. The `cardlog-check` Commander games had no mulligans, so only its Constructed games exercise the copy.
  - The pilot flag's thresholds are a judgement: the old Riders of Rohan prototype sits at exactly 4 of 4 and is flagged, Giada's owned list is just under (6 of 6.67), and one card can flip either. The tempo caveat only fires when both decks hold counterspells, and no saved result triggers it.
  - The noise figure is smaller for lopsided matchups (0.2 points when one deck wins nearly every game); R19's "3-4 points" holds near an even split.
  - Per-card differences still lean with game length (some lists' spread is 7-9 points; Orzhov Removal's target list 9.2), until wave 2's turn-3 tally (built in wave 2). The fake per-card results in four test files still use the old 100-game threshold.
  - The page changes were checked by the tests and by rendering them in Node, not with browser screenshots.
  - Not measured yet (M3): below-normal priority on a busy PC, including whether it makes Forge's clock or the watchdog stop more games.
- **Next:** wave 2 (the warm worker pool, R05 and R01b, and the one-time "v2" engine change, R06, R09, R08 and R14b, with R11's turn-3 tally; built 2026-10-03, see the next entry), then wave 3 (R12 adaptive stopping, R13 the field view, R15 paired variant tests, and R10/R16/R17).

**Simulation speed and accuracy, wave 2** (2026-10-03): the second of three waves of the plan in [forge-trial/sim-investigation.md](forge-trial/sim-investigation.md) (its §3-§5). Wave 2 is the warm worker pool (R05, with R01b's one core per worker) and the one-time "v2" engine change (R06's engine id, with R09's per-game seeds, R08's PERFORMANCE_MODE and R14b's forced attackers in order), plus R14a (the AI's decisions on a virtual thread) and R11 item 4 (the "in hand by turn 3" tally). The v2 engine plays different games for a seed than before, so `FORGE_RUN_VERSION` is now 2 and every matchup's key changes: results saved before are kept as they are, labelled, and never pooled with new games, and a new `replay` command plays their matchups again with today's engine.

**Built 2026-10-03.** First a base commit with the written contract ([forge-trial/sim-wave2-contract.md](forge-trial/sim-wave2-contract.md)), the shared pieces (`seeds.py` and `Seeds.java`) and stubs. Then six packages, each built in its own git worktree, reviewed, fixed and re-checked, and merged one at a time (J, EJ, C, PJ, EP, PP), with the full suite and the real-Forge checks each merge called for after every merge. Then four functional checks on real Forge, and one commit fixing what they found. New files `lib/forge/pool.py`, `cores.py`, `engine.py`, `seeds.py` and `servecheck.py`; in `lib/forge/java/decklab/`, `DeckLabServe.java`, `GameLoop.java`, `Request.java`, `Seeds.java`, `Signals.java` and `WarmState.java`; and Deck Lab's copies of Forge 2.0.15's `AiController` and `AiAttackController` in `lib/forge/java/forge/ai/`. Changes in `DeckLabSim.java`, `runner.py`, `cli.py`, `simjar.py`, `slots.py`, `processes.py`, `lists.py`, `logreader.py`, `saved.py`, `cardlog.py`, `cardstats.py`, `ai.py`, `views.py`, `install.py`, `config.py`, `server.py`, `api/forge_runs.py`, `web/matchups.js`, `matchups-cards.js` and `matchups.css`. 1,817 tests (26 skipped: the real-Java and real-Forge ones, which run with `DECKLAB_FORGE_TESTS=1`), all passing.
- **Speed hasn't been measured.** The PC was in use while wave 2 was built, so every Forge run was small (at most 4 processes and about 400 games, below normal priority) and no timing was taken. It's measured on an idle PC before merging to main (see "Still to measure" below).
- **What changed:**
  - **The warm pool (R05):** with the card log, a run no longer starts a cold Forge process for each batch. Forge workers started once (`DeckLabSim serve`, `DeckLabServe.java`) take "play" requests, each a chunk of games, from one queue shared by every matchup waiting (`pool.py`).
    - **The server owns the pool.** It starts with the server (its workers with the first games), and the page now plays up to 4 matchups at once (was 1), all sharing its queue. Each worker quits after `forge_pool_idle_s` (900 s, 15 minutes) with nothing to play, and the pool starts workers again when games come.
    - **The queue:** oldest run first, and `replay`'s runs only once no other run has games queued. A chunk is min(the rest of its seat block, 25, the run's `--batch`, max(5, ⌈queued games ÷ (2 × workers)⌉)) games, so a big queue gets 25-game chunks and a run's last games spread over several workers.
    - **Slots:** a worker computes only while it holds a slot of the PC's budget; it gives the slot up at each chunk's end, so an idle worker holds none. The pool keeps no more workers alive than `forge_workers` less the slots other processes hold, so idle warm JVMs don't sit beside another run's computing ones.
    - **Recycling:** a game that hits the clock or an AI timeout, or a worker that crashes or dies, ends that worker. The chunk's later games go back to the front of the queue under the same numbers, at most twice each (`MAX_REQUEUE`); the third time they fail. A worker also quits after 2,000 games, or when its heap after a GC passes 75% of `-Xmx`. A worker only plays chunks of the launch it was started with (its command line, folders and game patches), so a Forge upgrade or a new card-log jar never has old workers playing a new engine's games.
    - **Warm state (`WarmState.java`):** before every v2 game, warm or one-shot, Forge's 7 static id counters are reset, `Card.cp2card` is taken back to the keys it had at start-up (not cleared), `ChangeZoneAi.multipleCardsToChoose` is emptied and `AiCache.clear()` is called. A reset that fails ends the request with an error line, and no further game starts.
    - **Fallback:** when serve can't start, the run's chunks play as one-shot DeckLabSim processes (the same games); the run record has `fallback`, and `play` says "cold processes".
    - **The command line:** `play` and `replay` submit to the running server's pool, through its pool service (127.0.0.1 only, a random port and token, its address in `forge-pool-<pid>.json` in the slots folder), when the server plays the same engine. Otherwise, or with `--local`, the run gets a pool of its own, closed when it ends. Each side sends a heartbeat every 5 s, and 20 s of silence counts as a lost connection: the server stops that run's chunks, and the command line plays its remaining games in a pool of its own. A Stop on the command line waits up to 1 s for the games the server read before it.
    - **Stopping the server:** its matchups stop and save first, then the workers are told to quit and killed after 3 s; closing the window or logging off kills them at once, after the matchups have saved.
  - **One core per worker (R01b, `cores.py`):** slot k is physical core k, the V-Cache CCD's eight cores (logical CPUs 0-15) first, each core with both of its logical CPUs. A computing worker is pinned to its slot's core and takes back the slot it had last. `forge_pin: false` in `config.json` leaves Windows to place them (for comparing the two). `-XX:ActiveProcessorCount=2` stays, so pinning doesn't change how Java sizes itself.
  - **Sharing slots with a busy pool** (found by the functional checks): a process waiting for a slot holds a "want" (a locked `want-<pid>-<n>.lock` in the slots folder, gone with the process), and a pool that frees a slot while someone wants one leaves it free for 1.5 s (`pool.HANDOFF_S`). Before, a busy pool kept every slot until its whole queue was empty.
  - **The v2 game loop (R09):** `DeckLabSim -dlgame <stream> <first>`, with `-s` as the result's seed base. Before each game g, Forge's state is reset, its random numbers are reseeded with SplitMix64(base, stream, g) (`seeds.game_seed`, the same in `Seeds.java`), the decks are loaded with new rules and AI players, and the game is played as a match of its own. So:
    - a coin flip decides who starts every game (no more "the loser starts the next game");
    - Forge's auto-profile (play a deck as a slower, non-aggro deck when its name holds "Control" or its nonland cards average 4 mana or more, counting each different card once and rounding down) applies in every game, not only a batch's first;
    - game g plays the same whatever came before it, in any chunk or worker, and the same as plain Forge's `sim -n 1 -s <game_seed>` with that game's deck order.

    The stream is the pair's (from both lists' card_shas), the decks swap seats every 25 games and a chunk never spans two seat blocks, and a result's game numbers carry on across runs (`next_game`). Each request prints a `DLENGINE|v=2|seeds=game|base=...|stream=...|first=...` line with what it played (the auto-profile flags and average mana values, `perf`, the card log, the game patches). A malformed `-dlgame` request is refused with an `Error: -dlgame...` line.
  - **The engine id (R06, `engine.py`):** a matchup's key is the SHA-256 of a canonical JSON description: id and run version, kind (`decklab`: DeckLabSim with the card log; `plain`: Forge's own sim, when the card log can't be used), Forge's version, the format, the clock, the seed scheme (`batch` for plain), PERFORMANCE_MODE, the game patches built into the jar, card-script overrides, and the two sides' [card_sha, AI profile, the profile file's SHA-256], sorted. A side has an id of its own (the same with that side alone).
    - Results keep `engine`; each side keeps `engine_id`, `ai`, `ai_sha` and `auto_profile` {flag, avg_cmc}. What was read from Forge's folder is remembered per Forge version and build in `data/forge/engine.json`, so keys hold while the folder can't be read; nothing that couldn't be read is remembered.
    - Not in the id, because they were measured not to change games: lazy card loading, warm or fresh workers, `-XX:ActiveProcessorCount=2`, pinning, the mulligan copy, R14a, priority, chunk sizes and which worker played a game.
    - **Which kind is today's** follows the card log's readiness. While it's off, plain Forge's results are today's (so a Forge upgrade never stops runs), and card-log results show "Earlier engine" until it's back. Per-card numbers always use today's decklab-kind side id.
  - **Earlier results:** results saved before wave 2 (run version 1) and those of another engine stay as they are. `list` marks them `[earlier engine]`, `[earlier engine: v1]` or `[earlier engine: plain Forge]` (and today's results `[plain Forge]` while the card log is off); the matchup page shows an "Earlier engine" chip, a "Played with an earlier engine" box and "Play N games with today's engine", which starts a new result; a page with no result of today's engine links the earlier ones. The deck page's per-card numbers and never-cast list count only today's engine, and say how many of the list's games were left out (`other_engine_games`).
  - **`replay`** plays every saved matchup of another engine whose two lists are still current with today's engine, up to the most games any earlier result of the pair has, less what today's result has (by "replay", low priority in the server's pool, 4 matchups at once). It refuses unless the card log is ready, skips matchups that are playing, Ctrl+C stops and saves, and run again it plays only what's missing. `--dry-run` lists the matchups, the games and a rough time from the saved runs' speed.
  - **PERFORMANCE_MODE (R08):** `runner.PREFERENCES` turns on Forge's PERFORMANCE_MODE in its user folder. Every DLENGINE line says `perf=true`, and it's in the engine id.
  - **The AI's decisions on a virtual thread (R14a):** Deck Lab's copy of `AiController` runs each AI decision's "Game AI Eval" on a Java virtual thread instead of a new platform thread. If an earlier eval is still running (one that timed out and can't be stopped), it uses a platform thread, as Forge does, so a stuck eval can't hold one of the 2 carrier threads. The task counts itself (`Signals.LIVE_EVALS`, `AI_TIMEOUTS`) so a warm worker can recycle after a timeout. It plays the same games (100 of 100 identical full logs with and without it), so it isn't in the engine id.
  - **Forced attackers in order (R14b):** Deck Lab's copy of `AiAttackController` runs the checks for creatures that must attack one after another, in attacker order, on the game thread; Forge makes a new thread pool for each attack declaration. A check that throws an exception or overflows its stack passes that attacker over, as Forge's pool did; any other error ends the game as a crash. With two or more must-attack creatures Forge's order varies, so the copy changes games: it's in the engine id as `attack-requirements-in-order-1` (`simjar.GAME_PATCHES`). With it, the same seed repeats on a must-attack deck (40 of 40 identical, against 16 of 40 with Forge's pool). `-Ddecklab.gamePatches=off` plays Forge's own code (the card-log check's parity leg uses it).
    - Both AI copies are pinned to Forge's class SHA-256s, keep Forge's line numbers, and end with a note on what changed. The card log now needs JDK 21 or later, for virtual threads.
  - **Card log version 3 (R11 item 4):** a record also has `early_games` and `early_wins` per card: a copy was in the side's hand by its own 3rd turn (in the kept hand, or moved to the hand by the turn its 3rd Turn line began; in a game that ended sooner, any drawn copy).
    - Saved results read records of versions 2 and 3. The 8 numbers they share pool over both; the early ones over version 3 only, out of their own games and wins.
    - "Won more/less" is judged on "in hand by turn 3" whenever a list has such games (CardStats `basis` "early"); otherwise the drawn verdict stays, marked "(leans with game length)". "Early numbers" counts the games the verdicts rest on.
    - Lands are never judged, and always show their drawn win rates. The `cards` command has a "by t3" column.
  - **Command line:** `play --local`; `play` prints engine lines (plain Forge's reason, and each deck Forge's AI plays as a slower, non-aggro deck, with Forge's average for it) and its summary says "warm workers", "slowest start-up N s" or "cold processes"; `status` has a warm pool line; new `pool` (the server's warm pool), `replay` and `serve-check`; `cardlog-check` is now v2 (below).
  - **Checks:**
    - **`cardlog-check`** plays each game four ways (plain Forge, one game per process from its game seed; DeckLabSim with game patches off and on; DeckLabSim without the card log), then the warm leg. Defaults: 12 Constructed and 3 Commander games (at most 25 each). Ctrl+C kills its Forge processes and starts no more.
    - **`serve-check`** checks that a warm worker, pinned as the pool pins, plays the same games as fresh one-shot processes: 12 Constructed and 3 Commander games, plus half as many (6) of lists that fill Forge's card caches (double-faced, adventure, flip and clone cards) when R14b plays, each matchup cut into chunks across a seat-block boundary. `--v1` checks v1 batches instead.
  - **Config:** `forge_pool_idle_s` (900) and `forge_pin` (true); a bad value falls back to the default with one log line.
- **Decisions made** (the owner's, final):
  - The warm pool is the server's, and its workers quit after 15 minutes idle. Command-line runs submit to the running server's pool.
  - Forge stays below normal priority (wave 1).
  - After the v2 change the current matchups are replayed with today's engine, later, on an idle PC (the `replay` command, built and tested but not run on the real results).
  - "About even" is ±5 points; games are best of one; a field average (wave 3) weights opponents equally.
- **Decisions made while building:**
  - **Plain Forge is its own engine.** When the card log can't be used, runs play plain Forge's cold batches as before, keyed with `kind: "plain"`, so its games never pool with the card log's and a Forge upgrade never stops runs.
  - **One merged batch record per run:** a v2 run's chunks are merged as they come into one batch (`cardlog.merge_record`), and each game keeps its number, so a stopped run saves exactly the games it read.
  - **R14b's catch** is `Exception | StackOverflowError`, not the contract's `RuntimeException` (which can't compile around `Callable.call()`), so it passes over what Forge's thread pool passed over.
  - **serve-check plays its cache-filling lists only when R14b plays:** without it, Forge's 2-thread attack checks make some of their games differ even between two fresh processes (2 of 8 in 3 fresh runs).
  - **The auto-profile flag stored per side** is the one game `first`'s decks gave; it was the same over 20 seeds for all 41 Deck Lab decks.
- **How it was checked** (games compared, not timed):
  - **Per package:** a builder, a reviewer, a fixer and a re-check. Each merge ran the full suite, and each Java merge `cardlog-check` (`simjar.CHECKED_SOURCE` updated).
  - **The v2 loop (on the merged tree, with R14b):** 12 of 12 Constructed v2 games equal plain Forge's one-game processes line for line, and 3 of 3 Commander games with the same outcomes; games [0, 10) in one request equal [0, 4) plus [4, 10), and game 6 alone; the card log on and off play the same games; the DLENGINE auto-profile flags matched Forge's own answer in every game.
  - **Warm equals fresh:** `serve-check` passed 21 of 21 games, v2 and v1, with the cache-filling lists, and again with the worker pinned to core 0. Earlier, 22 of 22 Constructed and 4 of 4 Commander games with `-XX:ActiveProcessorCount=1`. The `cp2card` reset made no difference in 31 games; it's kept as a safeguard.
  - **The v2 `cardlog-check`** passed on the combined code (12 Constructed and 3 Commander games, all four ways and the warm leg).
  - **Four functional checks on real Forge** (the integration branch, scratch copies of the results, test servers on 127.0.0.1):
    - **The pool:** two matchups queued through the API shared one queue, the second taking chunks as the first's queue emptied; Stop saved every finished game; 53 Constructed and 12 Commander pool games replayed with one-shot DeckLabSim matched on winner, starter, turns, result and loss reason; with a 4 s clock, every game that hit it recycled its worker and re-queued that chunk's later games under the same numbers, with no duplicates; idle workers quit; a killed command line's run was dropped by the server; the slot budget was never passed; each worker's affinity matched its slot's core; 200 Commander games played through the pool; the server's `--stop` mid-run saved the run and left no worker.
    - **The engine:** game g played alone, in a 10-game chunk and in a serve worker (requests out of order, one repeated) was the same line for line, card-log lines included, for 10 games; `seeds.py`, `Seeds.java` and an independent SplitMix64 agree; the key and side ids of 5 new results match the contract's formula; on a copy of the 37 saved results every consumer (list, per-card stats, never-cast lists, matchup lists, the API, Play more on a v1 page) kept the engines apart and left the v1 files unchanged; a deck averaging 5 mana got the auto-profile flag; a real replay of one 80-game result played games 0-79, and run again played nothing.
    - **Card log v3,** 400 Gruul Ramp v Izzet Prowess games: shares in hand by turn 3 match M8 (1-ofs 10-18%, 2-ofs 25-32%, Llanowar Elves 49%). The v1 result of the same lists (1,600 games, judged on drawn) gave Gruul 5 "won more" verdicts, all positive; on turn 3 the only verdict is Fiery Annihilation "won less" (-20.8 points, range -32 to -8; M8's answer was -8.0). The late expensive cards come out negative but unclear (Rampaging Baloths -14.3, Pelakka Wurm -7.5, Lathliss -7.5), as M8 predicted. The pages at 1,905 × 950 and 390 px have no sideways scroll.
    - **Fixed after the checks:** the slot handoff above (re-checked on real Forge with a budget of 2: a waiting claim got a slot while a busy 400-game pool was at 45 of 400, against only after all 400 without the handoff); `replay --dry-run`'s rough time; a list whose only games were another engine's got no per-card stats and a page saying none of its games kept the card log (now games 0 and how many were left out); and `other_engine_games` shown on the deck page, in `cards` and in the never-cast note.
- **Still to measure (M3, on an idle PC, before merging to main):** (the combined run measured these with wave 3 on 2026-10-03; the wave 3 entry has the numbers)
  - the warm pool's games a minute against wave 1's cold batches, at 200 to 3,200 games, Constructed and Commander, and from a cold server;
  - pinned against unpinned (`forge_pin: false`);
  - R14a and R08 inside the pool (wave 1's M2 measured R14a's prototype at +6-7% with 16 processes; R14a has no switch, so its A/B needs a jar built without the `AiController` copy);
  - below-normal priority while the PC is busy, and the memory the warm workers hold.
- **Then, on the idle PC:** `python -m decklab.lib.forge replay --dry-run`, then `python -m decklab.lib.forge replay`. On 2026-10-03 a dry run on a copy of the results listed 22 matchups and 26,094 games; it leaves out results whose lists aren't current or aren't in the repo any more. (Done: the combined run replayed them into a staging folder, and they were moved into the results folder on 2026-10-04.)
- **Known low issues, left open:**
  - Some differences don't repeat even between two fresh processes (Forge's own thread pool without R14b, and the identity-hash order of cards, which a warm worker's other threads can shift). `serve-check` calls such a difference "unsure" where it can, and fails a Constructed outcome difference at once, so it could fail with nothing wrong in the worker; none has been seen.
  - A stack overflow R14b passes over doesn't make a warm worker recycle, so a Forge cache it half filled would stay in that worker; Forge's own thread pool has the same exposure, and none has been seen.
  - Comparing plain Forge (or game patches off) with the card log line for line can differ on decks with two or more must-attack creatures, even masked, since "didn't block" lines follow attacker order. The check decks have none; keep it that way.
  - The page doesn't show a run's `fallback` yet, and its notice calls v2 chunks "batches". The warm leg says "Waiting for other Forge runs on this PC to finish." when it only waits for its own fresh process's slot.
  - A Forge build that can't be read once (`simjar.forge_build` remembers the failure) keeps the card log off until the jar changes or the server restarts. `engine.today()` counts an AI profile it has never read and can't read now as known.
  - The slot handoff's unit tests catch a regression only about half the time; the real-Forge A/B above is the check. Gated real-Forge tests other than `test_forge_v2loop` still take slots in the test run's own folder, not the PC's.
  - Turn-3 shrinkage uses r5's spread, worked out on the drawn split. In Commander a 1-of is in hand by turn 3 in only about 10% of games, so per-card Commander verdicts need many games.
  - `servecheck._start` still carries its own copy of `processes.start_process`'s Windows start, for a `start_process` without a `stdin` option. That copy no longer runs and can go (with its test).
- **Next:** M3 and the replay on an idle PC, the merge to main, then wave 3 (R12 adaptive stopping, R13 the field view, R15 paired variant tests, and R10/R16/R17). All done by 2026-10-04: see the next entry.

**Simulation speed and accuracy, wave 3** (2026-10-03): the last of three waves of the plan in [forge-trial/sim-investigation.md](forge-trial/sim-investigation.md) (its §3-§5). Wave 3 is R12 (adaptive runs), R13 (the field view), R15 (paired tests of a change), R10 (card-script overrides) and R16's mechanisms (per-list pilots, Deck Lab's AI profiles and switches, and an experiment harness), plus the harness for one unattended idle-PC run that measured waves 2 and 3 together. R17, a Forge build with three unmerged speed PRs, was decided against: Forge 2.0.16 should bring them (see the Later list).

**Built 2026-10-03, measured that night, merged to main 2026-10-04.** First a base commit with the written contract ([forge-trial/sim-wave3-contract.md](forge-trial/sim-wave3-contract.md)), frozen stubs and the fake Forge's additions, cut from wave 2's integrated branch. Then nine packages, each built in its own git worktree, reviewed, fixed and re-checked, and merged one at a time with the full suite after each: S (statistics), J3 (Java), E3 (the engine id with pilots and overrides), R (run-loop hooks), F (the field view), V (tests of a change), A (adaptive runs and the time estimator), X (experiments) and H (the overnight harness). Then the night's additions (the pilot experiments, M6's 4-player pods, M7's check against human results, the report's remaining sections) and the fixes the run's preparation found. New files `lib/forge/seqstats.py`, `estimate.py`, `adaptive.py`, `field.py`, `variants.py`, `experiment.py`, `overrides.py` (the sets in `overrides/`), `pilots.py` (Deck Lab's AI profiles in `ai-profiles/`), `api/field_page.py`, `api/variant_page.py`, `web/field.js`, `field.css`, `variant.js`, `variant.css` and `decklab/simulation.json`; in `lib/forge/java/`, `decklab/DeckOrder.java`, `Pilots.java`, `TeamPumpAi.java`, `AiPatches.java` and `Startup.java`, and a copy of Forge 2.0.15's `forge/game/Match.java`; and the harness in `forge-trial/` (`overnight.py`, `overnight_legs.py`, `overnight_monitor.py`, `overnight_report.py`, `overnight_pods.py`, `overnight-plan.json`, and M7's decks and human win rates in `m7/`). The runbook is [forge-trial/sim-combined-run.md](forge-trial/sim-combined-run.md). On main at `3233d80` there are 2,260 tests (34 skipped), and all pass (twice in a row in the final check).
- **What changed:**
  - **Adaptive runs (R12, `adaptive.py`, with the statistics in `seqstats.py`):** the matchup page's play box asks "What do you want to know?":
    - "How well does this deck do here?" (`assess`, the default): a 400-game pilot, then the games planned for a range of ±3 points, then at most one top-up, 3,200 games at most;
    - "Which deck wins?" (`ahead`): checks at 400, 800, 1,600 and 3,200 games, stopping at a Haybittle-Peto boundary or when the decks are about even;
    - "A set number of games" (`fixed`), as before.

    A check happens only once every game of its stage has finished, so it never sees a subset biased toward short games. While a run plays, its live bar shows a range that allows for stopping at any time, and no verdict; a Stop makes one last check, which says "ahead" only at |z| ≥ 3. The result keeps each run's summary, and the page's lead word follows it while no games have been added since. On the command line, `play A B --until assess|ahead [--max N]`.
  - **Time estimates (`estimate.py`):** one server-side estimator for the play box, field runs and tests: a pair's own speed from its saved runs, else its lists' speed class, at the rates in `data/forge/rates.json` (the combined run's measured ones since 2026-10-04).
  - **The field view (R13, `field.py`):** the deck page's "Against the field" part. The field is the current decks of the list's format: each deck file's list (the built version of a built deck, else the target list) and the products kept intact, today 10 Constructed lists and 3 Commander ones; `decklab/simulation.json`'s "field" section adds or removes lists. It shows the field average (opponents weighted equally), a Bradley-Terry rating with a term for going first (the list's chance against an average field deck, and its rank with a likely range), residual flags for matchups well off the rating's prediction, and one row per opponent. "Play the field" plays a floor of 200 games against each opponent, then spreads the rest where they narrow the answer most (APT): about 400 games a deck (Standard), 200 (Quick) or 800 (Thorough). Its games are ordinary matchup results. On the command line, `field <deck>`. Field runs and tests play as jobs of their own (2 at once), beside the 4 matchups.
  - **Tests of a change (R15, `variants.py`):** the editor's "Test this change" plays a changed list of the same size on its base list's own games (the same seeds and seats), against one deck or the field, so only the games where the change mattered differ. It says "Better", "Worse", "Makes little difference" (within 2 points against the field, 3 against one deck) or "Not settled yet", checking at planned points up to 1,600 games a deck ("Until it's clear"), or after 200 ("Quick look"). Tests are listed under "Tests of changes" on the deck page, with "Play more" and "Save this change". On the command line, `variant <deck> --remove "1 A" --add "1 B" (--against <deck> | --field)`.
    - It needs a new game patch, `deck-order-1`: a copy of Forge's `Match` that builds each library in the .dck's line order, with the decks loaded from a seed of their own. Forge 2.0.15 builds a library in hash order, so one changed card moved many others, and a card with several arts drew extra random numbers. The variant's .dck is written aligned to the base's, line by line. When a Forge upgrade drops the copy, tests refuse to start and everything else plays on.
  - **Card-script overrides (R10, `overrides.py`, `lib/forge/overrides/`):** Forge's own card scripts with small AI edits (exact text replacements, listed in `overrides/sets.json`), copied into Forge's user folder before a run (`ensure_deployed`); Forge loads them over its own. A set is `adopted` or `experiment`, and experiment sets play only in user folders of their own. A file is used only while the installed Forge's script is the one it was made from. Matchup keys cover only the deployed files whose card is in the two lists. `fiery` (Fiery Annihilation) shipped adopted; `remove` was adopted on 2026-10-04 (below); `etb`, `etb-flagged`, `tgt`, `tgt-gift`, `flash` and `hints` are experiments. `overrides list | check | make | deploy` on the command line.
  - **Pilots (R16, `pilots.py`, `decklab/simulation.json`):** each list can have its own AI profile (Forge's, or Deck Lab's DLAggro, DLTempo and DLControl in `ai-profiles/`) and switches: `team-pump-1` (TeamPumpAi, which judges a team pump as a whole) and `aisim-hybrid-1` (a look-ahead AI, experimental). Every list plays Forge's Default profile with no switches until a pilot is adopted; none is yet. `pilots` lists them, and the page names a list's pilot.
  - **The experiment harness (R16, `experiment.py`):** `experiment <spec.json>` plays arms (override sets, pilots, seeds or config knobs) on a control result's own game numbers and seeds, and compares each with the control: each named card's cast rate, cast turn, win rate when in hand by turn 3 and when drawn, and own permanents lost per cast (from the games' logs), the paired matchup difference, speed and AI timeouts. Override and pilot arms get "adopt", "don't adopt" or "more games" by fixed rules (the contract's §12.4); adoption is the owner's. Arm results are of kind "experiment", keyed apart from matchups, in `data/forge/experiments/`.
  - **The engine id, version 2 (E3):** see "Results" in part 6. Every key changed, which cost nothing: main had played no v2 games yet.
  - **Run-loop hooks (R):** runs can play given game numbers on given seeds (tests and experiments), tee Forge's output (`--logs-dir`, `--log-every` on `play`, `replay`, `field`, `variant` and `experiment`), and stop when a file named in `DECKLAB_STOP_FILE` appears.
  - **The overnight harness (H, `forge-trial/overnight*.py`):** one unattended run on an idle PC, in its own worktree and data folder: a preflight, a timing battery (B), checks of the v2 engine (C), a soak of real work (D: the replay into a staging folder, the experiments, the field views) with fresh-against-warm probes, drift probes and memory polls, and an end (E) that checks the staged results and writes `REPORT.md` with merge gates MG1-MG16. It pauses while the PC is in use, can be resumed, and only ever ends its own processes. The forge commands `staged-move` and `soak-probe` are its.
- **Decisions** (the owner's, final): build wave 3 on wave 2 and measure both in one overnight run, instead of measuring wave 2 alone; main stays on wave 1 until that run passes; replayed results go to a staging folder and move into the real one only after the checks; overrides and pilots are adopted afterwards from the experiment data, except Fiery Annihilation's, adopted before the run; "makes little difference" is ±2 points against the field and ±3 against one deck; a merge needs a 3-hour soak; R17 waits for Forge 2.0.16. On the night, the idle wait at the start was skipped (`supervise --no-idle-gate`).
- **The combined run** (the night of 3-4 October, in the `C:/VSProjects/TCC-wt/w3-run` worktree; its reports are `decklab/data/forge/overnight/2026-10-03/REPORT.md` and `2026-10-04-recheck/REPORT.md` there):
  - **The first run** (22:33 to 03:26, 293 active minutes, 181 of them soak): every item ran but one timing leg. **Verdict: FAIL, on MG11 (drift) alone.** Its five drift probes' medians were 346, 687, 736.5, 728 and 337 ms a game: the middle three timed workers the pool had just started after an experiment's other launch (a 100-game warm-up gave 16 new workers about 6 games each), and the last matched the first. `b91ecb5` fixed the probe: an 800-game warm-up, and a probe whose workers were cold doesn't count. The leg that failed, B7-off (every game patch off), failed because the echo check refused its chunks; `6d80219` fixed that.
  - **The re-check** (03:37 to 07:21; `supervise --only` with the preflight, the B0-B2, B7-off and B1b timing legs, the replay, filler soak, the final probe, the idle close and the end; C1-C4 left out on purpose, so its verdict is INCOMPLETE by design): **MG11 passed** (medians 357, 350.5, 386.5, 376 and 347 ms a game), B7-off ran, and every gate it checked passed. MG7 wasn't judged: 455 Constructed games in 13 probes over 2.82 hours, 0 failed, but 149 of the 150 Commander games it needs.
  - **The merge gates** (the first run's numbers unless marked):

    | Gate | Result | Measured |
    |---|---|---|
    | MG1 preflight | pass | the card log ready and checked, the adopted sets deployed, `pilots --check` clean, main merged in, the deck lists main's |
    | MG2-MG5 (C1-C4) | pass | v2 games against plain Forge (20 Constructed, 5 Commander), the card log on against off (200 games), a warm worker against fresh ones (`serve-check --games 40`), and deck order (both test variants aligned in 20 of 20 games, the same starters) |
    | MG6 determinism | pass | 27,998 of 28,000 games identical across timing legs with the same engine and seeds; the other 2 had a clock stop or AI timeout (re-check: 3,600 of 3,600) |
    | MG7 soak | pass | 490 Constructed games played fresh against the warm pool's in 14 probes over 3.23 hours: 0 failed, 0 unsure; 150 Commander games, paired estimate 0.0 (low end −1.3 points) |
    | MG8 replay | pass | 29 staged results with 38,694 games, none in failed chunks; the replay itself 22 matchups and 26,094 games, none missing (re-check: the same 22 and 26,094) |
    | MG9 limits | pass | in those 38,694 games, 12 with an AI timeout (0.31 per 1,000) and 6 clock stops; 14 recycles |
    | MG10 memory | pass | Java's total working set during the soak: 19,762 MB at the smoothed 99th percentile (limit 24 GB), 25,733 MB at its peak; the worst worker's median heap in the last hour 0.76 of its first hour's (limit 1.2) |
    | MG11 drift | fail, then pass on the re-check | above |
    | MG12 clean | pass | no leftover process, slot or test server |
    | MG13 function | pass | the adaptive runs' verdicts agree with the references; a field run through the page's API against a reference of every opponent at 1,600 games: Spearman 0.967, every opponent within z 1.38 (limit 2.77) |
    | MG14 speed | pass | below |
    | MG15 v2 against v1 | pass | 22 matchups: each one's starters balanced; the win rates agree, within the gate's deliberately wide limit, where the old result had 400 games or more and no adopted override's card (Gruul Ramp's, with Fiery Annihilation, are reported only); no matchup's old and new 95% ranges excluded 50% on opposite sides. The largest move, 9.1 points, was on a result of 80 old games |
    | MG16 idle close | pass | idle workers quit after 120.8 s (limit 120 + 30 s), re-warm 20.3 s |

  - **Speed** (B legs, the same seeds in every leg; "warm" is the mean of rounds 1-2 of one pool, round 0 being a fresh pool; wave 1 is main's cold batches, the mean of B1a and B1b, run before and after the battery):

    | Workload | Warm pool, games a minute | Against wave 1 | Re-check |
    |---|---|---|---|
    | Izzet Prowess vs Gruul Ramp, 800 | 1,426.3 | 1.93x | 1.99x |
    | Selesnya Rabbits vs Orzhov Vampires, 400 | 157.3 | 1.17x | 1.19x |
    | Giada vs Finneas (1v1 Commander), 200 | 232.6 | 3.39x | 3.47x |
    | Izzet Prowess vs Gruul Ramp, 800, a fresh pool | 1,041.0 | 1.41x | 1.41x |

    - The other legs (pinning off and per CCD, 20, 24 and 32 workers, PERFORMANCE_MODE off, R14a and R04 off, pinning under a 4-thread load, the server path) are in the first report's timing table. Each leg's last Izzet round ran at 1.02-1.35x B2's warm rate and its earlier rounds at 0.48-0.90x, so they mix warm-up with what each leg changes, and no default was changed on their account.
    - With every game patch off (B7-off, re-check), Rabbits vs Vampires ran at 236.9 games a minute in its one round, 1.49x B2's warm rate. Those are other games (an engine of its own), and B2's RV rounds each had a clock stop while B7-off's had none, so this isn't a measured patch cost, but it's worth a look, since R14b and `deck-order-1` are on in every run.
  - **What the new tools found:**
    - **Adaptive runs (D3c):** "assess" stopped at 950 games (Mono-White Angels vs Lightning Aggro) and 1,100 (Izzet vs Gruul, Mono-Black Zombies vs Lightning Aggro), all precise to ±3 points; "ahead" called Angels ahead at 400 games and the other two about even at 800.
    - **The field view (D3):** a Standard field run of Mono-White Angels through the page's API played 3,600 games against its 9 opponents in 303.6 s. Its rows matched the reference (MG13). Angels' rating: 72.5% (69.0-75.7) against an average Constructed field deck, 1st of 10 (likely 1st-3rd).
    - **Pairing (D2a):** a 1-card change to Gruul Ramp, tested against Izzet on the same 800 games: −1.7 points (−3.1 to −0.4) paired, against −6.6 to +3.2 unpaired; 86% of the games played out the same, and pairing saved 92% of the games. A 2-card change (2 spells for 2 lands): −0.1 points (−2.7 to +2.5), 59% the same, 72% saved. The 1-card change against three opponents: "Makes little difference: within 2 points" after 3 checks. Without Fiery Annihilation's override, Gruul Ramp did 3.2 points worse against Izzet (−4.7 to −1.6), so it stays adopted.
    - **Ladders (D2b):** 2, 4 and 6 of a deck's key copies swapped for lands, 400 games a rung, against a reference opponent: Izzet Prowess −0.1, −6.9 and −13.5 points against Gruul; Mono-White Angels −3.2, −6.2 and −10.1 against Zombies; Mono-Black Midrange −4.2, −9.0 and −12.7 against Lightning Aggro. Selesnya Rabbits (−2.1, −2.5, −3.6 against Vampires) and Gruul Ramp (+2.8, +0.7, +0.9 against Izzet) didn't settle.
    - **Override sets (D2c, 800 games a pair against the replay's own games):** `remove` +2.4 points pooled (+1.1 to +3.7, Angels vs Zombies), with Devout Decree cast for 72.5% of drawn copies (0.0% before): "adopt". `etb` +3.0 (+1.6 to +4.3, 2 pairs) and `hints` +0.9 (+0.0 to +1.7, 3 pairs); `tgt`, `flash` and `tgt-gift` −0.5, `etb-flagged` +0.3: all "more games".
    - **Pilots (D2d):** the team-pump fix +4.1 points for Rabbits against Vampires (part 6). Each AI-profile arm's mirror came out 48.8-53.1%, none clear of 50%: "more games". The look-ahead AI cost 3.58 times the plain AI's time, over the 3x limit, so its mirror wasn't played (evidence only).
    - **Pilot sensitivity (D2e):** the 10 Constructed lists' Bradley-Terry ratings under every experiment override set kept their order (Spearman 0.988 against today's), and no pairing flipped (Benjamini-Hochberg 10%), nor with Rabbits on Reckless as well. So the rankings don't hang on these AI fixes.
    - **4-player Commander pods (M6, optional, plain Forge):** 200 pods of Giada, Finneas, Gisa and the Wretched Ranks precon took 0.41 minutes a pod on average (12 processes), with no clock stops; seats won 22-28%, and Giada 50% (43-56). In 100 pods beside its precon, Calling All Angels: Giada 50% (40-60) against 39% (30-49), a difference of 11 points (−7 to +29).
    - **Against human results (M7, never a gate):** 7 Pauper decks, 21 pairs at 400 games, against MagicMeta's published human matchups (fetched 2026-10-03): Spearman 0.64 for deck strength (0.786 needed for p < 0.05 with 7 decks), and the favourite agreed in 10 of 16 matchups. The human numbers come from 5-23 matches a cell, so this neither confirms nor rules out Forge's rankings.
  - **On main, the morning of 2026-10-04:**
    - main was fast-forwarded to `sim-w3` (`b91ecb5`); `cardlog-check` and `serve-check` passed on main;
    - `staged-move` moved the first run's staged results into the real results folder: 29 matchup results and 2 field notes. The 37 earlier results stay, marked "Earlier engine", and a copy of the folder from before the move is in `data/forge/results-backup-2026-10-04/`;
    - the measured warm rates went into `data/forge/rates.json` (1,426.3, 157.3 and 232.6 games a minute);
    - the owner adopted `remove` (`b70506e`), so Forge's AI now casts Devout Decree and Beast Within, and a `replay` of the 13 matchups whose lists hold them (20,000 games) finished at 08:12; `replay --dry-run` now has nothing left to play.
  - **Decided after the run** (the owner): more experiment games (per-deck AI profiles, the team-pump fix, the other override sets) wait for a separate session on an idle PC, still to be planned (the Later list).
- **Known low issues, left open:**
  - The harness doesn't check MG14's server-path part (B3, and EcoQoS on each JVM) or recount E3's early numbers yet.
  - MG10 can't judge recycles at the heap limit: the pool doesn't record why a busy worker went (at most 108 in 64,788 games, an upper bound).
  - Per-card numbers pooled over a field run's opponents lean toward close opponents (APT gives them more games); equal-weight per-card pooling isn't built.
  - The 15 tests that failed on `b70506e` because they assumed only `fiery` was adopted now read a pinned copy of the override sets (`05d1d0d`, `5d22ec8`), so adopting a set no longer breaks them; `test_the_repos_sets` still checks the real `sets.json`. The slot-handoff tests and `test_cardlog_check_runs_each_process_in_a_slot` are deterministic now (`b26eb73`, `3233d80`). Separately, `test_a_run_takes_slots_other_runs_give_up` is timing-sensitive and can fail under heavy load; rerun it alone before believing a failure.
  - Open, low: the time estimator doesn't scale a pair's own saved speed by `forge_workers` (only the speed-class fallback is scaled), so with fewer than 16 workers its estimates run short; and `forge list` can show a replayed result with its sides swapped from the one it replaced (the deck page always shows the deck's own side).
- **Next:** the experiment session, then something else from the Later list.

**Feature review implementation** (2026-10-08; moved here from PLAN.md's "Goal" on 2026-10-12, as written then. The receipt's commit retry went in phase 4 and the transaction's journal in phase 5a: a receipt is now one change in the database.) Collection discovery and shared assembly planning now have dedicated pages, with physical/incoming/held counts, sleeves and paired-token packing. The library filters target readiness. The play journal saves actual games and opponent-specific sideboard plans with exact list snapshots; interactive opening hands supplement aggregate practice statistics. Deck revision history restores through editor drafts, and selected lists can be copied, downloaded or printed with their guide. Shopping offers guarded receipt preview/apply/commit retry through the existing transaction. Known guide and Shopping card names open the inspector. Forge v2 checkpoints validated chunks and preserves numbered-game reservations after interruption. See README for the workflows and their limits. This does not adopt further AI experiments or add automatic sideboarding to Forge.

**Accessories** (2026-10-08, asked for by the user): an inventory of sleeves, deck boxes and playmats, so each built deck's sleeves and box are recorded as real things with pictures and counts rather than a colour word. The user decided that one sleeve design and one deck box cover a whole product kept intact (not one per deck), that a deck's sleeves and box can be chosen from the deck page on any device, and that a shop which blocks downloads gets "paste the picture's own address" rather than an upload.

**Built 2026-10-08,** in parallel chunks with one owner per file, from a written plan and contract:
- **Data:** `magic/accessories.csv` (`id,kind,brand,name,colour,quantity,image,link,image_source,notes`; CLAUDE.md has the rules) and committed pictures in `magic/accessories/images/<id>.<ext>`, marked binary in a new `.gitattributes`. Deck files gain a `Deck box` header line beside `Sleeves`, both holding an accessory id (older free text is still read and shown as written, never matched by name). `magic/products/status.csv` gains `sleeves` and `deck_box` columns after `intact` (`file,status,intact,sleeves,deck_box,notes`); `scripts/receive_order.py` reads the old 4-column header too, always writes six, and a receipt with `--intact no` clears both.
- **`lib/accessories.py`** (read only): `read()` (lenient for display, strict for writes), `resolve()` (an id of the right kind is linked, of another kind a warning, anything else free text), `holders()` (built deck files, their built version, and owned intact products), and `kit()`, the one place the enough-sleeves rule and its wording live. A holder needs one sleeve per card of its built list, every section and basics included; an intact product needs its decks' total. Warnings, never blocks: too few sleeves, a design or colour used by two holders, a deck box used more times than its quantity, an id of the wrong kind, an intact product with no sleeves. Free text gets a separate `info` line, not a warning, so the older Sleeves warnings stay word for word. `python -m decklab.lib.accessories --check` reports these and orphan or missing pictures, and exits 1.
- **`lib/accessory_fetch.py`:** "Find picture" (part 8 has the rules). It stages the picture in `data/accessories/staged/` and guesses the kind, brand, name and sleeve count from the page.
- **`lib/api/accessories.py`** (imported when first needed): `GET /api/accessories` and `POST /api/accessories/fetch|save|assign|commit`, plus the server's `/accessory-img/` route. Writes take the deck-save lock, then the receipts' inventory lock, and refuse while a receipt's recovery journal is waiting. A save must carry the list's sha256 (409 with the latest list otherwise), and files with changes Deck Lab didn't make are refused rather than committed ("commit them first"). Each change is one commit, `Deck Lab: <add|edit|remove|set|clear|move> ... (by <Name>)`. A failed commit is recorded in its own `data/accessories-pending.json`, never in `uncommitted-saves.json` (whose keys are deck ids), and retried with the next change or by `/commit`. `assign` writes only the deck's header line, or the product's `status.csv` row, and `move_from` clears the other holder in the same commit. A row a holder uses can't be removed or change kind. `commits._file_conflict` names who last changed a non-deck file.
- **Pages:** the Accessories page (`#/accessories`, works on phones: filter, cards with "Used by", add/edit sheet with the fetched preview, a products-kept-intact panel, conflict re-apply field by field, commit retry). The deck page's Sleeves and Deck box tiles with **Choose…**, which opens the picker on any device; the library's per-deck kit line; the editor's Sleeves and Deck box tile pickers (desktop), which can add a new row in place but no longer take typed free text; and the packing plan's kit row with "Get out N X sleeves" and "Pack into Y" ticks (its new key is `sleeves_need`, since `need` already meant card counts).
- **Tests:** new `test_accessories.py` (36), `test_accessory_fetch.py` (52, with mocked DNS and HTTP), `test_api_accessories.py` (33, a sandbox repo with real git), plus additions to the status.csv, deck-file, editor, deck-page, assembly, server, route and web tests.
- **Known low issue, left open:** the deck page of a product asks `/api/accessories` once more to learn whether the product can hold sleeves (a `can_hold` flag on its kit would save that request).

**Tokens** (2026-10-09, asked for by the user): which tokens, emblems and reminders each deck's cards make, which owned token cards fit, and a page to keep `magic/tokens.csv` up to date. Missing or different tokens aren't errors (a stand-in is fine at home), and Deck Lab never claims how many a game needs, because Scryfall doesn't say.

**Built 2026-10-09,** in parallel packages with one owner per file, from a written plan:
- **Data:** no new columns; `tokens.csv` keeps receipts' ten. A row is named by its ten values plus the file's sha256. The page and receipts share one validator, one sort key and one "same card" test, moved out of `scripts/receive_order.py` into named helpers (`validate_token_row`, `token_sort_key`, `token_identity`, `token_known`, `token_uncertain`); errors now give the line a row starts on. Only the details fields count when matching (`1/1; green; flying, deathtouch`, `no lifelink`, `colour unconfirmed`); notes never lower a match.
- **Card index format 4** (`lib/cards.py`): a `tokens` table keyed by oracle id (998 entries on 2026-10-07's bulk: 870 tokens, 89 emblems, 34 reminders and 5 helper cards such as On an Adventure, which are kept so an owned one is recognised but never listed as a need). Each card gets the oracle ids of what it makes, unioned across its printings and linked by printing id, else by name and full type line when exactly one token fits. Token objects, checklists and memorabilia typed just "Card" are no longer game cards (only "Wicked // Cursed" left the name list). New lookups `token()`, `tokens_for()`, `token_face()`, `token_face_names()` and `token_faces_at()`; `cards show` prints a "Makes:" line. The index rebuilds from the cached bulk files on the next `cards update` or server restart (about 4 s; 13.5 MB gzipped, against 13.3 MB).
- **`lib/tokens.py`** (read only): `read()` (lenient for display, strict for writes; the old 6-column header is read with a problem), `parse_details()`, `match_face()` (exact, agrees, check or differs, with the reasons), `deck_tokens()` (each need's state: ready, check, differs, incoming or none, with the cards to grab, stand-ins, cards on the way and its words), `gaps()` and `row_uses()` for the Tokens page, a small cache keyed by the list's own lines, and `python -m decklab.lib.tokens <deck-id> [--owned]` and `--check`.
- **`lib/api/tokens.py`** (imported when first needed): `GET /api/tokens` and `POST /api/tokens/save|commit`, with the accessories' locks, sha256 check, outside-change refusal and failed-commit record (`data/tokens-pending.json`), now shared through `lib/api/tracked.py`. The page never merges rows: an add, an edit that turns a row into another card, or an edit that makes a row fully known while another row names that card, answers 409 with the same card, and "keep it separate" is allowed only when the row, or every other row naming that card, isn't fully known. Only an add is offered "Add N to that card". Each change is one commit, `Deck Lab: <add|edit|remove> token <Front> // <Back> (by <Name>)`, with an optional reason.
- **Pages:** the Tokens page (`#/tokens`, works on phones: search and filter, cards with "Used for", a "Your decks need, none owned" panel, a read-only "On the way" panel, add/edit sheet with Scryfall name suggestions and "Single-sided (checked)", same-card and conflict handling as on the Accessories page). The deck page's Tokens part (right after Cards) and its header chip; the library's chip, shown only when a token is missing, different or on the way; and the packing plan's "Grab" and "Stand-in" ticks, pending lines for tokens not owned or on the way, and a "Shared tokens" panel for cards two selected decks would both grab. Bad `tokens.csv` rows show as info on the deck page and as `token_problems` in the packing plan, which no longer refuses to plan.
- **Tests:** new `test_tokens.py` (57) and `test_api_tokens.py` (32, a sandbox repo with real git), and a token fixture of 56 trimmed real Scryfall objects (`fixtures/tokens_cards.jsonl`), plus additions to the card-index (17), receipt (6), deck-page (12), packing-plan (5), shared-sandbox (2), web and UI tests.
- **Review:** five reviewers checked it for the index and matching, the writes, the page/server contract, the page and the tests and docs. They found 13 problems (1 high, 5 medium, 7 low), and a fix pass fixed them: a recorded two-token printing (such as Vampire // Treasure) is now matched on the face it names; a conflict on a row someone else changed rebases onto that row instead of offering "Add it again" or saying "Already removed" (the 409 now says whether the row is unchanged, changed or deleted); a quantity written like `02` can be edited and removed; a save that succeeded is never reported as failed; the same-card check looks at every matching row; links to an intact product with several decks open the products list; unticking "Single-sided" removes `single-sided verified`; focus after a save follows the card; the shared test sandbox no longer reads the real `tokens.csv` and order records; and the docs now say what an edit onto a listed card offers and what the pages show before the index is rebuilt.
- **Known limits:**
  - Tokens a card makes only through its rules text, and most token copies of other cards, aren't linked by Scryfall. The deck page lists cards that may make copies, or things Scryfall doesn't link, folded away and worded "may".
  - Some links are for certain modes or for the opponent; Deck Lab can't tell them apart.
  - A card linked to a token with its own name is kept only when its text or keywords make tokens. This rule is approximate, a safeguard that drops nothing today.
  - Two links stay unresolved, because several tokens share the name and type: Kaya the Inexorable's Spirit and Sarkhan the Masterless's Dragon. They're shown by name.
  - Reading details is approximate: words it doesn't know are kept and shown, never compared.
  - No counts: there's no "you need 6 Zombies", and two decks sharing a token card are flagged, not solved.

**Accounts and member collections** (2026-10-10, asked for by the user): Deck Lab has been open at https://decklab.example.com since 2026-10-10, behind Cloudflare Access's email code. The user added three more members (User2, User3 and User4) to the Access policy and wants each person logged into their own Deck Lab profile, with edits limited to what's theirs. The user decided:
- Cloudflare stays the login; Deck Lab has no passwords. Over the tunnel the email Cloudflare signed for picks the profile automatically (no "Who are you?" screen). On the home network (localhost, IP address, PC name) nothing changes: the profile chooser stays and every profile edits everything.
- **Matt** edits everything. **User1** edits the home decks Played by her (not `either`, which counts as Matt's), her wishlist and her settings; the shared collection, tokens, accessories, receipts and orders stay Matt's. **User2, User3 and User4** each get their own collection, tokens, decks, wishlist and settings, and edit only those.
- Everyone views everything, and anyone can run matchups, field runs and tests of a change, between any decks.
- Members enter cards by importing a CSV from a scanner or collection app (ManaBox, Moxfield and the like) and on a page that adds, edits and removes single cards.

**Plan:**
- **Config** (`decklab/config.json`, private repo): each profile gains `role` (`admin` or `member`), `space` (`home` for Matt and User1, the profile id for each member) and `emails` (lowercase). A top-level `access` block holds the Zero Trust team (`your-team`), the application's AUD tag and the tunnel port (8644). `plays_as` stays for home profiles only.
- **Spaces.** `home` is today's files, unchanged: `magic/collection.csv`, `magic/tokens.csv`, `magic/decks/<kind>/`, products, orders, accessories and the watchlist. A person's space is `magic/people/<id>/` with `collection.csv`, `tokens.csv`, `decks/<casual|commander>/` and `imports/` (raw uploads, never hand-edited), created when first needed. Person deck ids are `<id>/<kind>/<slug>`; home ids stay `<kind>/<slug>`, so saved results, play records and links keep working. Owned vs needed, cards in use in other built decks, and tokens are worked out within the deck's own space. Products, orders, receipts, accessories and the watchlist stay home-only. A person's wishlist stays at `magic/wishlists/<id>.json` and is checked against their own space.
- **Who's asking.** The server opens a second listener on `127.0.0.1:<access.port>` for the tunnel only, and `~/.cloudflared/config.yml` sends both hostnames there. Every request on it must carry `Cf-Access-Jwt-Assertion` (or the `CF_Authorization` cookie). Deck Lab verifies it itself, with the standard library: RS256 against the team's published keys (cached, fetched again for an unknown key id, at most once a minute), `aud` containing the AUD tag, the team issuer, and `exp`/`nbf` with a minute's leeway. Its `email` must match exactly one profile; anything else gets 403. The home listener refuses requests for the tunnel hostnames or carrying Cloudflare's headers (421), so a tunnel pointed back at it fails closed rather than handing out full editing. `homenet status`' Tunnel line reports both.
- **Permissions**, in one module, checked by the server on every write route; the page only hides what the server would refuse. A remote request's profile is its identity's, whatever the body says. Local requests act as `admin` under the chosen profile (for attribution). For a `member`: decks in their own space, or home decks whose Played by matches their `plays_as` (new decks are created as theirs); collection and tokens of their own space only; their own wishlist and settings; play records that involve one of their decks; table refreshes only of decks they can edit. Accessories, receipts, products and orders: `admin` only. Runs (matchup, field, variant, goldfish): everyone. `GET /api/me` returns the profile, whether the request is remote, and what it may edit, so the page can hide controls.
- **Collection editing** (new `lib/api/collection_edit.py`): add, edit and remove single rows of a space's `collection.csv`, with the tokens page's sha256 check, locks, outside-change refusal, failed-commit record and one commit per change (`Deck Lab: add card <Name> (<SET> <num>) to User2's collection (by User2)`). Import: upload a CSV (ManaBox, Moxfield, Deckbox, or collection.csv columns), saved unchanged under the space's `imports/`, previewed (rows matched to Scryfall printings, problems listed, basics dropped by `merge_cards.py`'s rules), then merged additively in one commit. The home collection can be edited this way only by an admin; receipts remain the route for orders.
- **Pages:** remote visitors go straight to their profile, with a small "Signed in as …" line. The library groups decks by person and offers "New deck" in the space the visitor may edit. The Collection page gains a space picker (Home, User2, User3, User4) and, where allowed, an Add card sheet, row edit/remove and an Import panel. Editing controls the visitor can't use are hidden; read-only views stay.
- **Docs and tests:** CLAUDE.md (layout, spaces, roles), README ("From outside the home") and the server's docstring; tests for the JWT check (a test key pair), the two listeners, every write route's permission, spaces in decks/pool/tokens, collection edits and imports.
- **Built 2026-10-10** in four packages (spaces and permissions; identity; server routes and collection editing; pages), merged with all tests passing, then reviewed for security. The editor's `editable` stays about the file; `may_save`/`why_not_save` say whether the visitor may save, so "Try a change" opens the editor without Save. Live the same day: `~/.cloudflared/config.yml` now sends both hostnames to `127.0.0.1:8644` (the old file is kept as `config.yml.bak-2026-10-10`), and `homenet status` reports the tunnel, its routing and the listener's refusal as OK. The home listener answers 421 to the tunnel's hostname and to Cloudflare's headers.
- **Security review (2026-10-10), fixed:** an import is capped at 20,000 rows and 4 MB (a ManaBox row is about 120-180 bytes, so 20,000 rows are about 3 MB), one preview is kept per profile (a new one replaces the last), previews are read one at a time (a second one meanwhile gets 429, "another import is being checked"), the preview keeps only what the apply needs, and an apply is refused when the space's `imports/` folder would pass 50 MB; imported cells with control characters, unknown languages (blanked) and notes starting with `=` `+` `-` `@` (spreadsheet formulas) are caught, as are formula-like condition, language and notes on the Add card sheet; a member's deck save or create can't change Sleeves or Deck box (accessories.edit; taking a deck apart still frees them); with an `access` block a profile without a role is a member, and no one signs in through the tunnel while no profile has a role; tokens with NaN, Infinity or non-finite `exp`/`nbf`/`iat` are refused; known keys are used without waiting for a keys fetch (one fetch shared by the requests that need it); emails are ASCII only, compared ASCII-lowercased; `ingress_problems` flags a rule to the home port at any address of this PC (its names, loopback, its own IPv4 and IPv6 addresses); and the home listener refuses the tunnel's host names even when `access` is missing or wrong.
- **Known limits:** anyone may stop any run (matchup, field, variant), not only whoever started it, as decided above (runs are everyone's); and `GET /api/goldfish?...&retry=1` starts a practice-hand run again from a GET, which a link could trigger, but it writes nothing a person keeps and only costs a few seconds of CPU. Both are left as they are.

**Accessories only for the home** (2026-10-10, asked for by the user): the sleeves, deck boxes and playmats are Matt and User1's, so the profiles with their own space (User2, User3, User4) must not see them anywhere. This is the first rule about seeing rather than changing; everything else stays open to view.
- **Rule:** `permissions.sees_accessories(profile, local=)`: a local request, an admin, or a profile whose space is home. `GET /api/me`'s `"may"` says it as `see_accessories`.
- **Server** (`lib/api/guard.py`: `sees_accessories()`, `require_sees_accessories()`, `hide_kit()`): through the tunnel such a visitor gets 403 with the reason from `GET /api/accessories` and `/accessory-img/` (saved and staged pictures, whatever the name), and every other answer leaves them out: the library and deck page (`sleeves`, `deck_box`, `kit`, `holder_sha256` None; no kit warnings or info), the editor (Sleeves and Deck box fields and their `field_text` None, not in `editable_fields`, no `other_sleeves` or picker rows, also in a save's or create's `deck`), a history revision's fields, "Try a change" (no sleeve warnings) and the packing plan (`sleeves`, `kit`, `sleeves_need` None). The editor sends only changed fields, so a save from such a visitor never clears a line it couldn't see (tested with a hand-written line in User2's own deck).
- **Page:** `mayDo("see_accessories")` hides the Accessories buttons and page (`#/accessories` says why instead), the library's kit line, the deck page's Sleeves fact, kit tiles and kit warnings, the editor's Sleeves and Deck box fields, hints and review lines, and the packing plan's kit row and ticks. An admin's `"may"` doesn't override it. On the home network the server answers as an admin with no identity, so the page sets it from the profile chosen: a person-space profile there doesn't see them either, though the answers still carry them (a hiding of the page, not a lock).
- **Tests:** `test_permissions.py` (1), `test_api_permissions.py` (6, each GET answer as Matt, User1, User2 and the home network), `test_server_access.py` (1, the 403s through the tunnel) and `test_accounts_ui.py` (1, the page as each profile, remote and local).

**Deck box capacity** (2026-10-10, asked for by the user): `accessories.csv` has a `capacity` column after `quantity`: how many sleeved cards one deck box holds, blank when not known, and only for deck boxes.
- **Rule:** a holder whose built list (every section, the same count as its sleeves) is bigger than its deck box's capacity gets a warning from `kit()` ("Too big for its deck box: ...") and a line from `--check`. A blank capacity checks nothing. Never a block.
- **File:** the older 10-column header is still read (capacity blank), strictly too; the next save writes the new header. A save that changes a row to another kind without saying a capacity clears it.
- **Page:** the add/edit sheet's **Holds (sleeved cards)** field, shown only for deck boxes; the card's "1 box · holds 100 cards" with each user's card count and "Too many to fit"; the deck box chip, the kit picker's and the editor's deck box tiles say "Holds 100" or "Too small: holds 80, 100 cards here".
- **Tests:** `test_accessories.py` (4) and `test_api_accessories.py` (1).

**Cropping accessory pictures** (2026-10-10, asked for by the user): the user chose to save the crop area rather than replace the picture file, so nothing is uploaded from the device (as decided for Accessories) and a crop can be changed or undone.
- **File:** `accessories.csv` has a `crop` column after `image`: blank, or `x,y,w,h` as fractions of the picture (0-1, at most 4 decimals, at least 0.02 wide and high, inside the picture), only with a picture. Both older headers (without `crop`, and without `capacity` too) are still read.
- **Server:** `image_url()` ends `#crop=x,y,w,h` for a cropped row, so every answer that carries a picture (items, Refs, the deck page's brief kit, the editor's rows) carries its crop with no other change, and the browser never sends that part. A save with a new or removed picture clears the crop unless the row gives one for it.
- **Page:** `accessoryThumb()` shows only the crop: a frame of the crop's shape (sized from the picture once it loads), the picture scaled and moved inside. The add/edit sheet's **Crop…** / **Change crop** opens the cropper in place: the whole picture shaded outside a box with four corner handles (28 px on touch screens), pointer events for mouse and touch, arrow keys to move and Shift with arrows to resize, **Square**, **Whole picture**, **Done** and **Cancel**. After a conflict, a crop goes with its picture: mine with a picture I chose, theirs when they replaced the picture.
- **Tests:** `test_accessories.py` (2), `test_api_accessories.py` (1) and `test_editor_contracts.py` (1).

**Adding a precon** (2026-10-10, asked for by the user): the Collection page's **Add a precon** adds a published precon's cards to a space's collection and makes its built deck in one go, which had been done by hand that day for Reign of Dragons (User2), Tramplesaurus Rex (User3) and Keen Engineering (User4).
- **Decided while building** (the plan's open points): a person's space still gets no products, so a precon there is cards plus a deck; home works the same way (a product bought through a recorded order still arrives on the Receipts page). Only decks MTGJSON lists are offered, and of those only paper deck types (Commander, Theme, Starter Kit, Jumpstart, Challenger and the like; no Secret Lair drops, MTGO or Arena decks, land packs or Brawl and Horde decks). A deck with a card the local Scryfall data can't match (a set too new, or a list MTGJSON hasn't finished) is shown but can't be added. Star Trek Commander (out 2026-11-13) had no list on MTGJSON on 2026-10-10, so it isn't offered yet. The precon's token cards are listed in the preview and the deck's Notes, never added to `tokens.csv`.
- **Data** (`lib/precons.py`): MTGJSON's `DeckList.json`, `SetList.json` (set names, for searching) and `decks/<fileName>.json`, cached in `data/mtgjson/` (the lists for a day, a deck for a week; an old copy is used when MTGJSON is down). Only listed file names are ever fetched, with size caps, and every card field is checked before use. Display commanders (oversized on older decks), planes and schemes are counted but not added.
- **Server** (`lib/api/precons.py`): `GET /api/precons?q=` searches name, set code, set name and type; `GET /api/precons/preview?file=&space=` matches the cards with the import's rules (`collection_edit.read_upload`: printing and finish from the list, condition and language blank, plain basics left out unless MTGJSON says they're full art) and gives the suggested title (`Sai: Keen Engineering` for a Commander deck), the list, counts, tokens and problems; `POST /api/precons/add` needs `collection.edit` and `deck.create`, checks the collection's sha256, the title's file and the deck draft before writing anything, then makes two commits: the import (`collection_edit.merge_upload`, the generated rows saved as `imports/<date>-<set>-<name>.csv`) and the new deck (`saving.write_new_deck`, status built, plain basics as `34 Island`). `create_deck` is split into `plan_new_deck` and `write_new_deck` for this, and the plan now builds and parses the file's text too, so a bad Notes or list is refused before a caller writes anything else.
- **Checked against the hand-made precons:** Keen Engineering's preview gives the same 66 cards in 66 rows, 34 Islands left out, and the same title as the hand-made import and deck.
- **Tests:** `test_precons.py` (15) and `test_web.py` (1, extended).
- **Known low issues, left open:** if the deck's write still fails after the cards went in (a title taken in between, say), the cards stay and the answer says so; the deck is then made by hand. The suggested title uses the commander's name before its comma, which reads oddly for a few commanders.
- **Review fixes** (2026-10-10, the same day, from a review of the commit):
  - *Adding twice:* any failure after the cards went in, not only a refusal, now answers with `collection` (and `deck_id` when the deck file was written after all), so the page never offers Add again; with no answer of Deck Lab's own (no connection, a proxy's error page) the page says the cards may be in and offers only Close.
  - *Lists that can't become decks:* the preview runs the checks every new deck's list gets (`drafts._read_draft`), so `ready` is false, with the reason in `deck_problems`, for a list `plan_new_deck` would refuse (gold-bordered printings, more than 99 copies on a line). World Championship and Pro Tour decks, all gold-bordered, are no longer listed. The page shows a refusal's `blocks` too.
  - *The deck page after an add:* it opens with the box a new deck gets in the editor (`state.saved`), so its warnings (no sleeves yet at home, the deck rules) and the other decks' stale tables show, plus a line about the cards that went in.
  - *Search:* picking a deck cancels a search still waiting to run, and closing the sheet cancels it too.
  - *Display commanders:* checked against 36 Commander precons from 2019 to 2026. From 2022 to mid-2024 the display commander is a foil-etched copy of the commander in the set itself, a real card: it now goes into the collection (noted `display commander`), not the deck. Oversized (2019-2020) and thick-stock (2021) ones are still only counted; most later decks have none.
  - *MTGJSON:* a failed fetch isn't tried again for 10 minutes (an old copy is used meanwhile, else the error comes at once); a dropped download (`IncompleteRead`) and a cache file that can't be saved no longer give a 500; `SetList.json` (11.7 MB) has its own 64 MB cap; a deck's file is kept a day, like the lists, so one MTGJSON hadn't finished is put right by its next build; the lists' readings are kept in memory until their files change (here a repeat search took 1 ms, against about 0.1 s for the first one after a new build); odd values in the planes, schemes, tokens and display boards are skipped, not a 500.
  - *Wording:* the deck's Notes and the preview's link credit Wizards only when the list's source is a Wizards page (414 of the listed decks cite other sites).
  - *Less work:* `plan_new_deck` hands its parsed file to `write_new_deck`, which no longer builds and parses it again.
  - **Tests:** `test_precons.py` (23) and `test_web.py` (1, extended again).

**Accessories by owner** (2026-10-11, asked for by the user): Matt's and User1's sleeves, deck boxes and playmats are separate, and only the owner sees and changes them. The user decided: strictly owner-only (Matt's admin role doesn't see User1's), a third owner `shared` that both see and change (for "either" decks, intact products and bulk sleeves), the 23 existing rows assigned by the user (7 User1's, 4 shared, the rest Matt's), and a deck's Sleeves and Deck box hidden from whoever doesn't own them.
- **File:** `accessories.csv` has an `owner` column after `kind`: a home profile's id or `shared`, required. The older headers are still read, with every row `shared`.
- **Rule:** `permissions.accessory_owners(profile, local=)`: a home profile's id and `shared`, whatever its role; nothing for a person-space profile; everything for a local request naming nobody. `accessories.edit` is no longer admin-only: any home profile, on its own and shared rows. A holder's owner (`accessories.player_owner`, `guard.holder_owner`) is the home profile whose `plays_as` is its Played by, else `shared` (`either` decks, products, pairings), and it takes only its owner's or shared rows (`accessories.usable`).
- **Server:** the home network names the viewer in `X-Deck-Lab-Viewer` (`access.viewing`, set by server.py only for home-network requests; the tunnel's login decides there). `GET /api/accessories` lists only visible rows, holders and products, with `owners` for the form; another's holder in `used_by` or a "taken" 409 is `{"holder": null, "title": "one of User1's decks"}`. Save: another's row is 404, giving a row to another owner 403, an owner change a holder couldn't use 409. Assign: another's holder 403, a row the holder can't take 400. A deck save that changes Sleeves or Deck box goes through `guard.require_kit_choice` (the same rules). The library, deck page, editor, draft check, history and packing plan show a deck's kit only to whoever sees its owner (`guard.sees_kit`); kit warnings name other owners' decks only as "one of User1's decks". Pictures of another's row are 404. `--check` reports unknown owners and a holder using another owner's row.
- **Page:** every API call sends `X-Deck-Lab-Viewer`; switching profile drops the cached library. The Accessories page's **Whose** field, a **Shared** chip, used-by lines without a link for another's deck; the kit picker and the editor's tiles offer only rows the deck may take, and "+ Add" starts with the deck's owner; a design used only by another's deck says so instead of offering a move.
- **Tests:** `test_accessories.py`, `test_api_accessories.py`, `test_permissions.py`, `test_api_permissions.py` and `test_server.py` (owners read and checked, the view per viewer with hidden holders anonymised, save/assign/deck-save refusals, the viewer header through the real server); the older tests give their rows owners and write their own `config.json`.
- **Known limits:** on the home network the viewer header is trusted, as everything there is (a hiding, not a lock); a picture loaded by an `<img>` tag carries no header, so on the home network any picture whose name is known still loads. `accessories.csv` is one file in git, so anyone reading the repo sees every row. Changing a built deck's Played by doesn't move its sleeves; `kit()` and `--check` then flag them as another owner's.

**Deck Lab's own Forge** (2026-10-11, asked for by the user): Forge is forked at [matt439/forge](https://github.com/matt439/forge), cloned at `C:\VSProjects\forge`, and Deck Lab now runs its own build of it. The user decided that the fork's `decklab` branch is the product, aiming to play better than stock Forge, with pull requests to Card-Forge only when cheap and approved by the user each time; and that Deck Lab runs only the fork's build (no fallback copies for stock Forge), so every change to Forge lives in one place.
- **The branch** starts from tag `forge-2.0.15` (the build Deck Lab ran, `2.0.15-SNAPSHOT-09.28`):
  - `af513b9fd`: Ghoulcaller Gisa and God-Eternal Bontu played by the AI. Both were `AI:RemoveDeck:All`, which Forge's `AiController` turns into "never cast". Gisa's ability never worked out X (the sacrificed creature's power) before the cost was paid, so it got 0 and never activated; `TokenAi` now works X out from the creature the AI would sacrifice and activates only when the tokens are worth more than that creature (or it's about to die), and the card gets an `AIPreference`. For Bontu's "sacrifice any number of other permanents", the AI's default sacrificed every one of them, lands included; a new `AILogic$ SacToDraw` sacrifices only what's worth less than a card, keeps the lands the hand needs and the commander, and never draws the library out. 100 games of the Wretched Ranks precon against Calling All Angels (seed 7): stock Forge cast Gisa 0 times and Bontu 0 times, the fork 89 and 17 times, with Gisa's ability used 42 times; Gisa's deck won 11 of 100 both ways, as the matchup is lopsided. A known weakness: Gisa may sacrifice a Zombie lord for two tokens, as Forge's creature score barely counts its anthem.
  - `d84031a6d`: Deck Lab's four patched classes moved in from the card log's jar (`AbstractMulligan`, `AiController`, `AiAttackController`, `Match`), with two hooks in their place of Deck Lab's own classes: `forge.ai.AiSignals` (was `decklab.Signals`) and `forge.game.LibraryOrder`, which `Startup` plugs `DeckOrder.entries` into. forge-game's resource `decklab/forge-patches.txt` lists the changes and the game-patch ids. The build targets Java 21 (upstream 17) for the virtual threads. `decklab/install.py` builds the jar named after its commit and installs it in `C:\Tools\forge-decklab`, with the branch's card scripts swapped into the release's `cardsfolder.zip`; Maven 3.9.16 is at `C:\Tools\maven`.
- **Deck Lab:** `simjar` reads Forge's list (`forge_patches()`) instead of pinning class SHA-256s; the card log's jar holds only Deck Lab's own classes and its source hash only their sources; `DECKLAB_SIMJAR_EXCLUDE` and the overnight harness's `--exclude-patch` are gone (the changes are in Forge's jar, so there's nothing to leave out); a Forge jar without the list gets no card log ("This Forge isn't Deck Lab's own build"). A fork build's version is its build name (`install._find_jar`), so each commit is an engine and a card-log check of its own. Every plain-Forge launch now passes `-Ddecklab.gamePatches=off`, so plain Forge plays the fork's game-changing changes as Forge's own code, matching its engine's empty game-patch list. `forge_dir` defaults to `C:\Tools\forge-decklab`; the release stays in `C:\Tools\forge`.
- **Checked:** `cardlog-check` passed with `2.0.15-decklab-d84031a6d` (12 Constructed and 3 Commander games, the warm worker included). The move itself changes no game: 30 seeded v1 games and 25 seeded v2 games of Izzet vs Gruul played identically, line for line (13,734 and 11,008 lines of game and card log), on stock 2.0.15 with the old jar's copies and on the fork's build, both with `gamepatchids=attack-requirements-in-order-1,deck-order-1` and `deckorder=1,1`. Results saved before are an earlier engine (the version changed), so `replay` plays them again.
- **Tests:** `test_forge_patches.py` removed (all about the copies); `test_forge_aipatches.py` keeps its real-game tests, now against the fork's build and making its throwing class from the fork's source (`DECKLAB_FORGE_FORK`, default `C:\VSProjects\forge`); `test_forge_simjar.py` has `ForgePatchesTests`; the made-up Forge jars carry a list; `test_forge`'s `setUpModule` pins its own checked version, so the tests don't change with the fork's build.

**Simulations setting** (2026-10-11, asked for by the user): so members can use Deck Lab without starting Forge runs while the PC is busy. The user had asked about hosting the page elsewhere and keeping simulations on the PC; this setting was chosen instead, as the smaller change that keeps one machine. Forge's processes already ran below normal priority.
- **Who may start runs:** `GET/PUT /api/simulations` (`lib/api/simulations.py`), with the mode in `data/simulations.json`: admins only (the default, the user's choice), everyone, or paused. Starting a matchup, a field run, a variant test or its "Play more" is `permissions`' `run.start` (`guard.require_start`). It goes by the profile's role even on the home network, where every request otherwise acts as an admin, so "admins only" also holds for User1 at home; a local request naming nobody (a script) passes. Stopping any run, practice hands and the packing plan stay open, and runs already waiting or playing carry on. Changing the setting is `simulations.edit`: an admin's, by role. Through the tunnel the login decides who that is. On the home network the chooser names the profile, so it's a courtesy there, not a lock.
- **Forge workers:** an admin can lower how many Forge workers the PC uses at once (`forge/slots.py`'s `limit.json` in the slots folder, so it holds for the command line and every checkout too). `claim()` reads it on each try, and the warm pool also starts and keeps alive no more workers than it allows, so a change takes effect from each run's next chunk. Fewer workers were chosen over a Windows CPU-rate cap: games still play at full speed, so `forge_clock_s` means the same.
- **Page:** the footer has the admin's two controls (Simulations: anyone / only admins / paused; Forge workers: all 16 down to 1). Anyone who can't start runs sees a notice at the top saying why, and an admin sees one while they're paused. The run buttons stay, and the server's refusal shows as a toast.
- **Tests:** `test_permissions.py` (5), `test_api_permissions.py` (5) and `test_forge_slots.py` (2).

**Database, phase 1: the foundation** (2026-10-11, asked for by the user): the first of five phases moving Deck Lab's data from git-tracked files to PostgreSQL ([PLAN.md](PLAN.md), "Moving storage to a database"). The user decided the engine (PostgreSQL 18 through psycopg 3, the one exception to the standard-library rule, since the standard library has no Postgres client; SQLite was weighed and dropped because a later move would cost 7-12 days and a hosted SQLite file couldn't be opened by the PC's tools), the native Windows service listening only on localhost, nightly backups to the home NAS plus an export to a private GitHub repo (both mandatory), and keeping Forge results as files. Nothing on the page changed: the server didn't use the database yet.
- **`decklab/db/`** (run then with `.venv\Scripts\python -m decklab.db`): `conn.py` (settings from an optional `"database"` block in `config.json`, the three roles `decklab_owner`, `decklab_app` and `decklab_ro`, `connect()`, `change()` as one transaction per change set, `pg_bin()`, `db.log`); `setup` (the roles with passwords only in `pgpass.conf`, sent as SCRAM verifiers, the database, migrations and profile sync; safe to run again), `migrate` (refuses a changed migration), `status`, `sync-profiles` and a read-only `sql`.
- **Migrations:** `0001_foundation.sql` holds `space`, `profile`, `profile_email`, `audit.change_set` and `audit.row_change` with one trigger that refuses any write outside a change set (so even `psql` has to say who and why), `ops.backup_run` and the grants; `0002_audit_hardening.sql` fixes the audit function's `search_path`, stops the app role backdating a change set or making temporary objects, and refuses `TRUNCATE`.
- **Backups:** `backup` (a `pg_dump` staged in `decklab/data/backups/`, then copied to `\\NAS\Backups\DeckLab\`), `prune` (14 daily and 8 weekly, never the last good ones), `restore-check` (into a scratch database, row counts compared), `export` (each table as CSV into `C:\VSProjects\DeckLabData`, committed and pushed only when something changed, refusing a folder inside this repo), `nightly` and `schedule` (the Task Scheduler task "Deck Lab database backup" at 03:30, as Matt, so it reaches the NAS).
- **Tests:** `test_db_core.py` and `test_db_ops.py`, 71 tests on a template database per checkout and a throwaway copy per class, never the real database, the NAS, the real export repo or Task Scheduler; they skipped under the system `python` then.
- **Known low issue, left open:** `test_db_core.MigrateTests.test_a_changed_migration_is_refused` turns the migration's `\n` into `\r\n` to change it, so in a checkout whose files are already CRLF (some worktrees) it makes `\r\r\n` and the checksum differs for the wrong reason, and the test fails there.

**Database, phase 2: wishlists, settings, the simulations mode, play records and the Activity page** (2026-10-12, asked for by the user as the next phase): the first data moves into the database. Wishlists, each profile's settings, the simulations mode and the played games and sideboard plans are rows now, not files; the wishlist's delayed-commit thread and every git commit and retry of these are gone; and the first Activity page lists the audit trail. Built from a written design and its review's amendments: the foundation first, then five areas in parallel worktrees (wishlists, settings and simulations, play records, the server runtime with status, export and import, and Activity), each reviewed and fixed, merged, then a final review of the whole whose six findings were fixed too.
- **How the server gets psycopg** (`lib/venv.py`): the plan had the scheduled task registered again from `.venv\Scripts\pythonw.exe`, but on Windows that's a launcher that starts the base interpreter as a child, which breaks `server.json`'s pid, `/F` kills, the Forge slots' pid checks and the program-scoped firewall rule. So everything stays on the system Python, and `activate()`, called first by `server.py`, `python -m decklab.db` and the test package, puts `.venv\Lib\site-packages` on `sys.path` just before the system site-packages when `pyvenv.cfg`'s `home` and version match this Python. It never raises; why it didn't activate goes to the server log and, for an admin, the database warning at the top of the page (paths cut). `homenet`, the task and the firewall are unchanged.
- **Migration `0003_personal_state.sql`:** `audit.change_set.via` (`home` or `tunnel`); `wishlist_entry` (profile, position, name, printing, notes, source; Python decides case-insensitive uniqueness under a per-profile advisory lock, and a `lower(name)` index is only a backstop); `profile_setting`; `simulation_mode` (one row, with who set it and when); and `play_record`, one table for both kinds (the exact timestamp strings, the deck ids in an array with a GIN index, the record's own fields as jsonb), rather than the three tables first planned, because records are read and written whole and their hash must come back byte for byte (it's always worked out in Python). No foreign key to `profile`, since the profile sync deletes profiles, so a removed profile's rows stay as orphans, as orphan files did. `profiles` and the sync refuse the reserved ids `claude`, `system`, `test` and `home`, and an empty profile list never removes everyone.
- **The state store** (`lib/state/`): `store()` gives a `PgStore` (one connection per call, a 2-second connect, 2-second lock and 5-second statement timeouts, a 30-second circuit breaker after the database stops answering, and a write-through cache of settings and the mode, read again once a minute) or, in tests, a `MemoryStore` with the same rules (`rules.py` is shared); a contract suite runs the same tests on both. Every write takes an `Actor` (id, name, via, source) and a message, and is one change set: the tunnel's login, else at home the profile the page names, else `home` ("someone at home"); `claude` from the command line; `system` for the import. `api.common.state_errors()` turns the store's errors into 503 (`"reason": "database"`), 400 and 409 with today's texts, and `core.js`'s `load()` shows a 503 with that reason as an error with Try again, never the card-data wait.
- **Wishlists:** same routes and answers, minus the git fields and the `retry` action ("action must be add or remove"); `wishlist_history.py` and its worker deleted. `validated_entry()` is shared by the page and the new `python -m decklab.db wishlist list|add|set|remove` (actor Claude; `-m` required and non-blank, a removal's `--reason` too; `--no-check`, `--allow-orphan`; an add of a listed card changes nothing and points at `set` when its flags differ).
- **Settings and the simulations mode:** `PUT` passes every key sent and the store writes only what differs. The matchup and field defaults and `simulations.mode()` never fail: on any error they use the last value read, else the defaults ("admins" for the mode, since "paused" would block the admin too). Changing the mode writes it first, so a 503 comes before the worker limit is touched. The Matchups page reads the settings on its own, so it still works while the database is down. Pilots and field edits stay in `simulation.json`, and the worker limit stays a file, read by the Forge command line too.
- **Play records:** the same API and hashes; the editor's write lock still covers the snapshot and the write while decks are files, and `state.reachable()` is checked first, so a down database answers at once. `play_overview` reads the records before snapshotting any deck.
- **Activity** (`GET /api/activity`, `web/activity.js`, a button in the library for everyone): newest first by day, with who, when, from where, message, reason and plain-words row summaries, and Load older. What each viewer sees is `permissions.activity_scope` plus per-table rules with field allow-lists (README, "Activity"): admins everything but email addresses; others their own space's wishlist, settings and play-record rows and the simulations setting; a command line's or import's message and reason only to admins and the actor (else None, the rows' summaries saying what changed). Decided in review: play records whose deck ids can't be read are admins' only, and a viewer header naming a profile `config.json` no longer lists counts as naming nobody (everything, at home), since a home request can leave the header out anyway.
- **Server runtime:** `server_run._database_check` starts after the URL line: `lib/dbstatus.py` checks once a minute with one app-role connection (pending migrations, whether phase 2's tables can be read, the last good dump), opens and closes the breaker, and answers `/api/status`'s `"database"` block from that snapshot (`{"ok"}` for most, the details for admins); only the background server syncs profiles, with the request timeouts. The warning banner at the top of the page warns everyone when the stores can't be used, and admins also about pending migrations, a failed check, psycopg and a stale backup. `decklab/db/*.py` now counts as server code for "Restart needed"; migration files don't.
- **Import and export:** `import-files [--apply]`, the one-time import of `magic/wishlists/*.json`, `decklab/data/profiles/*.json`, `decklab/data/simulations.json` and `magic/play/**` in one change set, idempotent, refusing while `magic/wishlists` is dirty or the old commit queue holds an edit. The export adds the four tables and `wishlists/<profile>.json` in the old file format, skips the new tables before migration 0003, and keeps `audit.row_change` out. The cutover (stop the server, migrate, import, compare `wishlist list` with the files exactly, then delete `magic/wishlists/*.json` and the gitignored settings file) follows the build.
- **Final review fixes:** `localhost` connects to 127.0.0.1 only, so a stopped PostgreSQL fails in 2 seconds rather than about 4 (libpq tried `::1` too, each with the full timeout); the start-up profile sync has the request timeouts; the settings and mode cache is read again once a minute, so another process's write shows; the status block's venv reason has no absolute paths; the Matchups page shows its loading box at once; and Activity's Load older moves keyboard focus to the first card it added (or the note) when it hides itself.
- **Tests:** new `test_state_contract.py`, `test_db_phase2.py`, `test_db_runtime.py`, `test_db_settings.py`, `test_wishlist_db.py`, `test_activity.py` and `test_activity_ui.py`, and the existing tests moved onto a `MemoryStore` (the Sandbox installs one; `test_wishlist_history.py` and the git, retry and damaged-file cases deleted). The test package sets `DECKLAB_DB_NAME` to a database that doesn't exist and makes `state.store()` refuse unless a test installed one, and the database tests now run in the normal suite when PostgreSQL answers (a 1-second port probe first). On 2026-10-12 the whole suite ran 3,210 tests in about 8½ minutes, 30 skipped, with 3 failures that also fail on main and have nothing to do with phase 2: `test_guide`'s mulligan section check on the `vader-and-ani` and `yoshimaru-dogs` deck files, and `test_editor`'s `PersonSpaceTests.test_saving_and_refused_fields` (a 403 about home's accessories where 400 is expected).
- **Known low issues, left open:**
  - A web or command-line removal reads the list once to spell its message, then removes in a second call: if the list changes between them only the message's spelling can differ.
  - Any change to `decklab/db/*.py` asks for a restart, even a module only the command line uses (`export`, `import_files` and the like), as the design chose.
  - A play record's audit message names both decks, so a viewer with either deck in their space sees the other's title on the Activity page; `/api/play` already shows every space's lists to everyone.
  - While the database is down, the requests waiting when the breaker's 30 seconds end each try once (about 2 seconds) before it opens again: the plain breaker the design asked for.
  - `import-files` treats a profile's whole file as already imported once the database holds any row for it; the cutover order (import before anyone can edit) makes this the intended idempotence.
  - `MemoryStore` writes the mode's time as `to_jsonb` would only while PostgreSQL's TimeZone is the PC's (UTC+10), so compare those times parsed, never as text.
  - The notice telling a non-admin that the mode is a fallback has no JS test (the test runner's `$()` returns null).
  - Under `.venv\Scripts\python` three `test_server_lifecycle.BackgroundServerTests` fail (the launcher's child process, as above); they pass under the system `python`, which is how the suite runs.
  - Looked at and found not to be problems: the `lower()` backstop can't refuse a name Python's casefold allows (every code point checked against the live database's collation), and `db_support.reset()` can't reach the real database (the test package names a database that doesn't exist before any test module loads).

**Wishlists made private** (2026-10-12, a follow-up to phase 2 the user decided: "Wishlists should be private"): a wishlist is its owner's only, like each person's accessories, so not even an admin sees another's. `permissions.sees_wishlist(profile, owner_id)` is true only for the owner; a home request naming nobody (the page before a profile is chosen, or a script calling the web API) isn't one, since the page always sends `X-Deck-Lab-Viewer` once a profile is chosen, and through the tunnel the login's profile is the viewer. `GET /api/profiles/<id>/wishlist` answers 403 "A wishlist is private" to anyone else (`guard.require_sees_wishlist`, after the 404 for an unknown profile); writes already needed the owner. On the Activity page a `wishlist_entry` row shows only to its owner, never through the admins' and scripts' see-everything scope (an orphan's to nobody); a change set whose rows are all hidden is left out, and one with a wishlist row shows its message and reason only when the viewer sees every one of its rows and may see the words by the old rule, so "Add Island to User1's wishlist" reaches only User1 and a command line message about her list reaches nobody on the page. The page already opened only the chosen profile's own list (`#/wishlist`, no other person's), and no other answer (library, deck pages, shopping, `/api/me`, the profile chooser) carries wishlist contents; the Activity page's intro now says admins see every change except other people's wishlists. The PC's command line (`python -m decklab.db wishlist`, `sql`) and the private export repo still read every list. Tests: an owner, other home member, admin, person, home-naming-nobody and tunnel-login matrix for the GET (`test_wishlists`, `test_api_permissions`, `test_wishlist_server`, `test_server_access`) and for Activity (`test_activity`), and the tests that read a list now name its owner as the viewer.

**Database, phase 3: the inventory** (2026-10-12, asked for by the user as the next phase): every space's collection, token cards and raw imports, the orders, the products and the watchlist move into the database together, since a receipt touches them all. Built from a written design and its review's nine amendments: a foundation first (the model, both backends, the migration, the test harness and golden dumps of today's readers), then seven areas in parallel worktrees (readers; collection; tokens; accessories; orders, products and the watchlist; receipts; import, export, gate and Activity), each reviewed and fixed, merged into `db-phase3` with a follow-up commit, then a final review whose findings were fixed too, and read privacy for the inventory, which the user decided during the build. The code ran on the files backend until the cutover, which follows the build: stop the server, migrate, import, a live gate, tag the last commit with the files `pre-db-inventory`, switch the backend to `db`, and remove the inventory files from the tree. These docs already describe the state after it.
- **Decided differently from the plan** (PLAN.md, phase 3, has the list): a backend switch (`config.json`'s `inventory.backend`, `files` by default, `db` after the cutover), so the ported code ran in production on the files before anything moved and a rollback is one switch; one immutable in-memory snapshot of the whole inventory instead of SQL per reader; a gate against the old code's golden dumps rather than one codebase on two backends; blank text as `""`, surrogate ids for token and queue rows, arrays for checks and sources, and `product_status` as its own table; and the journal, inventory lock and pending-commit record kept for the files backend until phase 5.
- **`lib/inventory/`:** `model.py` (frozen rows that keep the files' strings, "raw first", with typed accessors; per-source problems carrying today's exact messages and line numbers; derived paths such as `magic/orders/received/<file>` for messages), `files.py` (`FileInventory`: today's files parsed without ever raising, and rendered back byte for byte; its revision a sha256 over the inventory files; in git mode it writes through the journal and commits as before), `pg.py` (`PgInventory`: a handful of selects in one repeatable-read transaction, sorted in Python, never by SQL collation; a row diff applied under `pg_advisory_xact_lock(hashtext('inventory'))`, checking and bumping `inventory_revision`; the snapshot cached by revision; while the database is down, the last snapshot served marked stale, "inventory as of <time>: the database isn't reachable", and writes refused with 503), `rules.py` (every pure helper moved out of `scripts/`), `changes.py` (the one place both backends and previews normalise and check a result), and `__init__.py`: `current()`, `pinned()` (one snapshot per HTTP request and per command, so a page's reads see one revision), `preview(op)`, `apply(op, actor, message, reason, expected_revision)`, `use()` for the tests and `invalidate()`. The operations are registered by kind: `collection.*` (`ops_collection.py`), `tokens.*` (`lib/tokens/ops.py`), `order.*`, `product.*`, `watchlist.*` (`orders.py`), `receipt.receive` (`receive.py`) and `product.set-kit` (`kit.py`); `refresh.py` refreshes and commits the deck tables after a write.
- **Migration `0004_inventory.sql`:** `inventory_revision` (no row until the import, so an empty database is never taken for an empty inventory), `collection_card`, `collection_import` and the unaudited `collection_import_content`, `token_card`, `product`, `product_item`, `product_status`, `purchase_order`, `order_component`, `order_card_item`, `order_token_item` and `watchlist_item`, each audited and refusing `TRUNCATE`; no foreign key to `space`. `0005_gate_runs.sql` lets `ops.backup_run` record live gate runs.
- **Readers ported:** `pool` (every `where`, warning and label string kept), the product decks (`PRODUCT_INFO` and `NOT_DECKS` only for the files backend), `purchases`, `tokens`, Collection, Shopping, Assembly, the deck page and library, accessories' holders, the editor, card lookup, wishlists' counts, and the Forge field and lists (a product's or pairing's provenance is now `{"product", "revision"}`, not a git commit). A grep guard in `test_inventory_reads` fails on any new path to an inventory file outside a short allow-list of messages.
- **Writers ported:** the Collection page's edits and imports (raw uploads kept as `collection_import` rows), Add a precon (the cards in one change, then the deck file committed; a failed deck write leaves the cards and says so), the Tokens page, the Receipts page and an intact product's sleeves and deck box (a deck-to-product move writes the deck file first, then the database, and puts the deck file back only if it still holds what that save wrote, keeping it when the database change did land). Each is one change set by the profile with its old commit subject as the message. Pages send the sha256 of the rows as the old file would hold them, so the JavaScript is unchanged; a receipt's preview runs on the snapshot in memory and its apply refuses when the revision moved.
- **The command line** (`python -m decklab.db`, actor Claude, `-m` required, `--reason` on removals, exit 3 when a follow-up fails): `collection list|merge` (replacing `scripts/merge_cards.py`), `tokens list|check|add|edit|remove` (edits and removals need `--expect` with the listing's sha), `order list|show|add|edit|checks|split|cancel` (`order add` records the order, its payloads, a product and the watchlist rows it fulfils in one change), `product add|set-intact`, `watchlist list|set|remove|apply`, `receive` (replacing `scripts/receive_order.py`; `scripts/receipt_transaction.py` became `lib/inventory/journal.py`), `inventory export|restore-files|backend` and `gate-inventory`. `scripts/refresh_deck_tables.py` stays, reading the snapshot.
- **Import, export, gate:** `import-files` imports the inventory from git's blobs at HEAD in one change set, refusing dirty files, unfinished receipts, failed commits and waiting import previews, and anything the database couldn't hold exactly; `--replace-inventory` redoes it (with `--force` once the backend is `db`). The export repo gains the inventory's tables and a `magic/` folder rendered byte for byte. `gate-inventory` runs the golden commit's code over the files and this checkout's readers on the database (with the inventory files deleted) and compares every item, plus the export against the files; `inventory backend db` requires a live gate passed within a few hours on the revision the database still has.
- **Activity and status:** inventory rows follow the read rule below, at most 50 listed per change, with plain-words summaries ("Added 2 × Llanowar Elves (FDN 227) to the home collection", "Added the order 2026-10-08-shop-a from MTGMate"); a change's `kit` flag works out the sleeves-and-deck-box message rule over every row, hidden ones included. `python -m decklab.db status` prints an "Inventory:" line, and the admin's database warning says when the inventory shown is a stale copy or nothing has been imported.
- **Read privacy for the inventory** (decided by the user during the build): `permissions.sees_inventory` / `inventory_spaces` (Activity's rule already) is now every inventory read's: home's collection, tokens, orders, products, watchlist, checks and receipts only Matt and User1, a person's own collection and tokens only that person and an admin, a home request naming nobody everything, and a tunnel login that isn't set up nothing; on the home network reads follow the profile picked in the chooser. `guard.py` gained `inventory_spaces`, `sees_inventory`, `require_sees_inventory` and `inventory_hidden`. `/api/shopping`, `/api/receipt` (and its preview and apply, checked for the body's profile), `/api/assembly` (and its preview), and `/api/collection`, `/api/collection/rows`, `/api/tokens` and `/api/precons/preview` for a space the viewer may not see answer 403; `/api/collection`'s `spaces` lists only those it may; the printing picker's counts, search's `have` and Paste a list's default printing use home's pool for whoever sees it and the viewer's own space otherwise (they used to be home's for everyone); `/api/deck/check` leaves out the pool of a space the viewer may not see. `GET /api/me`'s `"may"` gained `"see_inventory"` (the spaces, or null for all), and the page (`core.js`'s `inventorySpacesAs`, `seesInventory`, `seenSpaces`; on the home network worked out from the profile picked) shows a notice on #/shopping, #/receipt and #/assembly, hides Shopping and Plan decks in the library and the Assembly checklist on decks that aren't home's, and offers only the spaces it may see on the Collection and Tokens pages.
- **Final review fixes:** reads during a files-backend write answer 409 (`journal.Busy`, a `Conflict` and a `ValueError`) instead of 500, and the library still loads without product decks meanwhile; a product-only accessory assign no longer holds `_save_lock` on the database; Paste a list and `/api/deck/check` stopped using another space's pool; a token save's 409 no longer turned into a 403 for a writer who can't read the view; `product.add` and `order.add` check a product list as the product decks read it (`magic/products/x.csv: line 2: unknown section 'maindeck'`); a tokens order counts toward exact-printing watchlist rows; `product set-intact yes` is refused for a product with no deck lists; the order commands plan the deck-table refresh on a preview first and refuse a change that would break it (`--force` saves it, and a change made while the refresh already fails is allowed); and `inventory restore-files` only lists until `--apply`, refusing on the files backend or with anything waiting unless `--force`.
- **Tests:** new `test_inventory_contract.py` (24 scenario goldens through both backends), `test_inventory_files.py`, `test_inventory_reads.py`, `test_inventory_orders.py`, `test_inventory_ops.py`, `test_inventory_kit.py`, `test_token_ops.py`, `test_collection_ops.py`, `test_db_gate.py`, and an `InventoryReadTests` matrix in `test_api_permissions.py` (each route as Matt, User1 and User2 through the tunnel, a login that isn't set up, and the home network naming nobody, User1 or User2). The Sandbox and `PoolTestCase` install a `FileInventory` over their own trees, so the existing assertions run unchanged; `test_inventory_state.py` moved into `test_inventory_files.py`, and `test_merge_cards.py` and `test_receive_order.py` now test `collection merge`, the receipt operation and `rules.py`'s helpers. `python -m decklab.db.gate check --data decklab/data/gate/dc258a6` says "The dumps match." The whole suite on 2026-10-12 (under `.venv`) ran 3,523 tests, 31 skipped, with 7 failures and errors that also fail before phase 3 (`test_guide`'s two deck files, one `test_forge_slots`, one `test_overnight`, and the three `.venv`-only `test_server_lifecycle` tests) and one database test that hit a Postgres permission error in the full run and passed alone.
- **Known low issues and open items, left open:**
  - Open questions for the user (PLAN.md, "Still to do"): deck pages and the library still show another space's pool counts to anyone who may see the deck; a person picked on the home network can still write home's collection and tokens (and the save's answer carries home's rows); a person-space admin would see home; and there's no operation to edit or remove a pending product with the database.
  - Neither a receipt nor a cancellation rewrites buylist links to the payload's old path (a cancel lists the Markdown files that link to it); old links resolve in `pre-db-inventory`.
  - The pool warning about a payload already merged still says "already in collection.csv … move the order file to orders/received/", since the gate compares reader output; the order commands now refuse a change that would trigger it. A real one-copy order of a printing already owned needs `order add --force`, and receipts stay blocked until it arrives, as before.
  - `pairing_problems` still lives in `orders.py`, and the receipt and kit operations don't call it.
  - The precon add holds `_save_lock` across the database apply (so the title check, the cards and the deck file stay one step), and so does a deck-to-product sleeves move: the two documented exceptions to "no inventory write waits on the database while holding `_save_lock`".
  - `/api/shopping` still answers 500, not 409, for a read error during a files-backend write.
  - `forge-trial/card_audit.py` and `autoprofile_more.py` still read the old files; ported at the cutover or when next used.
  - Files backend only: the Accessories page doesn't list failed `status.csv` commits from `inventory-pending.json` (the next inventory change commits them); a member's view checks that a failed commit is their own just before `Tracked.retry` takes its locks; and old per-person pending records keep their files but lose their subject lines.
  - The collection's import size cap ignores subfolders of a space's `imports/` (none exist).
  - The gate prints a run of "isn't inside the repo" log lines about deck files from its temporary tree before "The dumps match."

**Database, phase 4: decks and accessories** (2026-10-12, asked for by the user as the next phase): every space's decks, with their history, and the accessories with their pictures move into the database, so the last data Deck Lab saved as git commits is gone from the tree. Built on branch `db-phase4` while production ran main's pre-phase-4 code on the live database: a written design and its review's eleven amendments (R1-R11), a golden harness first (stage 0: dumps of the pre-phase-4 readers over the real decks and a fixture tree), then a foundation (the snapshot's deck parts, migration 0006, the operations' parameters, the refresh wrapper, Activity's privacy rules), then six areas in parallel worktrees (readers and views; deck writers; accessories; the refresh's users and sources; history; the command line, import, export and gate), each reviewed and fixed, merged with follow-up commits settling where they met (the editor's kit changes through `kit.set`, a 409's "in Deck Lab" only for the pages' saves, the per-viewer accessories token in the gate), then a cleanup of the dead git-commit UI and endpoints and a final review whose ten findings were fixed too. The cutover follows the build: stop the server, migrate 0006, import the decks from main, `gate-decks --live` and `history-gate`, tag the last commit with the deck files `pre-db-decks`, merge `db-phase4` into main, remove the deck files, `accessories.csv` and its pictures from the tree, start the server, export, and purge Cloudflare's cache of `/accessory-img/*`. These docs already describe the state after it.
- **Decided differently from the plan** (PLAN.md, phase 4, has the list): no decks switch (R1: the decks are an ordinary part of the snapshot in both backends, production stays on main until a merge, and the files backend's git mode and every commit, pending-commit, Commit now, Retry and outside-edit path were deleted now rather than in phase 5); two revisions in one snapshot (R2); the deck-table refresh inside the change (R3); operations that take the final text (R4), with `kit.set` and `precon.add` each one change; the git history imported without backdated change sets (R5); deck-page privacy (R6d, the user's decision); the accessories' per-viewer token and private pictures (R6b, R6c); no `deck_field` table; and the decks imported from main.
- **Migration `0006_decks_accessories.sql`:** `decks_revision` (one row; none until the import), `deck` (audited: id, space, kind, slug, the title, status and Played by worked out from the text, a `kit_version` and the revision; never the Sleeves or Deck box values; unique per space on `lower(kind || '/' || slug)`), `deck_text` (LF only), `deck_revision` (append-only for the app role: revision, change set or null, time, actor, message, op `A`/`M`/`D`, `kit`, git commit, text), `deck_line` (derived, for SQL only), `accessory` (audited) and `accessory_image` (bytes, size and sha256 checked), no foreign key to `space`, texts and bytes unaudited.
- **`lib/inventory/`:** the snapshot gains `decks` (`Deck`: space, kind, slug, the exact text, revision; parsed by each reader with `parse_deck`, never cached parsed), `accessories` (a sheet like phase 3's) and `accessory_images` (`ImageMeta`: name, size, sha256; bytes only through `inventory.image(name, sha256)`), with `decks_revision` beside `revision`. The files backend reads and writes `magic/decks/**`, people's decks, `accessories.csv` and the pictures (bytes kept as written: a CRLF deck's sha256 is the disk's), under the inventory lock and the journal, never committing. `pg.py` and `pg_decks.py` cache the decks part apart under `decks_revision`, refuse deck saves until the decks are imported (`DECK_SAVES_PAUSED`, while serving the files), and raise `Unavailable` rather than read files once 0006's tables exist. New operations: `deck.save`, `deck.create`, `deck.update_tables`, `deck.delete` (`ops_decks.py`), `kit.set`, `accessory.add|edit|remove`, `image.put|remove` (`ops_accessories.py`), `precon.add`; `deck.save` refuses a change to the kit lines, a person's deck gaining home-only fields, over 1 MiB, a NUL or (database) a carriage return. `refresh.in_op` plans the deck tables under `pinned(after)` for kinds registered with `refresh=True` (receipt, order add/edit/split/cancel, product add/set-intact) and only for the spaces the change touches; `Summary.extra["tables"]` says what was written or skipped and why. `refresh_tables`, `RETRY_TABLES`, `planned_paths` and the post-commit refresh are gone.
- **Readers ported** (area A): the library, deck page, editor, drafts, assembly, guide, practice, stats, goldfish, wishlists' view, the Forge lists, field, variants, experiments and replay, and `forge-trial/card_audit.py`, all from one pinned snapshot; Forge provenance is `{"deck", "revision"}` (None for a preview or unsaved draft). The page's `source` fields are deck ids. Deck-page privacy (R6d): `/api/deck`'s `owned`, `table` and `tokens`, the library's counts and token chips, the editor's `table`, the stale-tables list and home's pool warnings only for viewers who see the space's inventory; a person's space's tokens are read only when one of its decks is shown.
- **Writers ported** (area B): save, create, Update their tables and Add a precon through the operations (the precon's table worked out against the collection as the import leaves it); the 409 names who changed the deck from its last revision (`audit.change_source`: "in Deck Lab" only for a page's save); someone who may not edit a deck gets 403 before any sha check; a deck deleted during Update their tables is a "deleted" entry; a save changing Played by on a built deck holding a kit is an accessories change (403 unless the profile sees the stored owner's kit). The JavaScript says "Saved in Deck Lab", names decks by id, and lost Commit now, Retry, Include them anyway and the outside-edit boxes.
- **Accessories** (area C): every write one operation (a row and its picture together; every sleeve and deck-box move between decks and products one `kit.set`, so phase 3's put-back is gone), a per-viewer list token (null when the viewer sees no rows; a stale edit of another owner's row answers "deleted", as for a missing one), `/accessory-img/` with `v` required (the picture's sha256's first 8 hex) and `Cache-Control: private, max-age=604800`, and the Activity rule for `accessory` rows. The editor's Sleeves and Deck box fields stay loose (older free text kept, sleeves another deck has only a warning); the picker and `deck push` keep `kit.set`'s strict checks.
- **Refresh users and sources** (area D): the receipt and order commands and the Receipts page use the in-op refresh (exit 3 now only means the tables couldn't be refreshed; `--force` skips it and says so; previews say when deck saves are paused or the refresh would fail); watchlist, wishlist and order `source` paths naming a deck validate against the snapshot's decks.
- **History** (area E): `GET /api/deck/history` and `/api/deck/revision` read `deck_revision` (integer revisions; an imported revision's git sha still opens it; an unknown actor shows as "someone"; a kit revision's message only to its actor). `deck_history.py` imports main's history (`git log --full-history`, refusing a rev not on main and a merge resolved by hand in a deck file; actor from the subject's "(by Name)", else Claude for a Claude co-author, else Matt): 40 commits, 117 revisions, 20 decks with aragorn-heroes' deletion. `history-preview` and `history-gate` check it.
- **Command line, import, export, gate** (area F): `python -m decklab.db deck list|show|pull|push|new|delete|history|revision|tables` (replacing `scripts/refresh_deck_tables.py`, deleted), `accessories list|show|check|add|edit|remove` and `image put|remove`; `import-files` imports the decks from main's blobs with their history (`--replace-decks`, refusing while the server runs or the branch has deck commits main lacks); the export writes the deck files, `accessories.csv` and pictures into the export repo's `magic/` and `deck`, `accessory` and `decks_revision` as CSVs; `inventory restore-files --part inventory|decks|all`; `inventory backend files` refused without `--force`; `gate-decks [--live] [--fixture]`; `status` prints a "Decks:" line.
- **Cleanup:** the Tokens and Collection pages' commit routes (`/api/tokens/commit`, `/api/collection/commit`), their `uncommitted`/`commit_pending`/`commit` fields, the Retry boxes and the receipts' "Git commit failed" box went, and `api/commits.py` and `api/tracked.py` kept only what saving still needs.
- **Final review fixes:** the precon add priced its deck before its cards were added; `accessories add|edit` on the command line always failed (now only the given columns are sent; `--image` gone, `image put` sets a picture); `deck push` said "Nothing to change" after a kit-only change; a draft check changing Played by exposed another owner's sleeves; a draft check's default printing showed which printing a hidden space owns; `update_tables` returned home's pool warnings to User2; the import would have missed saves committed to the checked-out branch; two tests would have crashed once the deck files were removed (`RealDeckFileTests` now reads the `pre-db-decks` tag); the rollback would have left a false migrations warning (keep 0006's file); and `card_audit.py` would have found no decks.
- **Gate:** `gate check --phase 4` and `--phase 4 --fixture` compare this checkout's readers with goldens recorded by main's code at 83d61e6 (`decklab/data/gate/83d61e6/`), normalised by `gate_p4.EXPECTED_P4`'s four entries (`no-git`, `deck-ids`, `hidden-inventory`, `per-viewer-accessory-token`); `gate-decks` adds the database run with every deck file deleted, the export's bytes and the history against `git log`. All four gates (`gate check`, `--phase 4`, `--phase 4 --fixture`, `gate-decks`) pass.
- **Tests:** new `test_inventory_decks`, `test_inventory_pg_decks`, `test_inventory_accessories`, `test_deck_readers_p4`, `test_deck_saving_db`, `test_import_decks`, `test_inv_decks` and `test_card_audit`, `test_deck_history` rewritten for integer revisions and the import, contract scenarios for decks and accessories on both backends, and tests that read the real decks through `pre_db.decks_inventory()` (the `pre-db-decks` tag). The final passes ran the affected modules (about 950 tests across 35 modules, the database tests included) and the gates, not the whole suite.
- **Known low issues and open items, left open:**
  - Open questions for the user (PLAN.md, "Still to do"), plus renaming a deck: not supported (a new deck and a deletion start a new history).
  - Before the cutover the live server must run main's code: a server running from a `db-phase4` checkout commits its saves to that branch, which the import refuses (by naming those commits) rather than drop.
  - The two decks with CRLF line endings in the working tree are stored LF, so their sha256 changes once at the cutover: an editor open across it gets one 409.
  - Error messages still name a deck by its old file (`casual/broken.md can't be read`): the gates' goldens pin them, and `deck-ids` only rewrites `source` fields.
  - The 409 answers for decks and tokens still carry `"committed"` and `"commit": None` (the design's shape).
  - An accessory id made from brand, name and colour avoids other owners' rows, so a `-2` suffix shows someone else has the same one (accepted: ids are unique across owners).
  - Deck-path sources are matched by exact case.
  - `deck tables`, like every refresh, refuses a whole space when one deck has no owned-vs-needed table or an unknown card.
  - `accessories --check` problems are matched to a deck by title, so two decks with exactly the same title both get them in `deck push`'s notes.
  - A killed `gate-decks` run leaves its scratch database (`<name>_gate_decks_<pid>`) behind; phase 3's `<name>_gate` is still shared between concurrent runs.
  - A replacing decks import resets `kit_version`, so Activity shows each kit-holding deck as a kit change.
  - The files backend keeps no deck history (its History is empty); only the tests use it.
  - `receive --recover`, the journal and the inventory lock remain for the files backend (tests); phase 5 removes what's left. (Note of 2026-10-12: phase 5a deleted the journal and `receive --recover`, and moved the lock to `decklab/db/filelock.py`, where only the rollback's one-off commands take it until phase 5b.)

**Database, phase 5a: cleanup and a nightly check** (2026-10-12, asked for by the user as the next phase): the user split phase 5 in two. 5a deletes the dead code the files left behind, fixes the wording that still spoke of files and commits, and adds a nightly check of the data; then come a week of side-by-side checks (2026-10-13 to 2026-10-19) and a report in `magic/reports/`; then 5b, after a clean week and the user's say-so, retires the rollback (PLAN.md, phase 5). Built on branch `db-phase5` in five packages in parallel worktrees (the files backend and the lock; git and the Forge-trial scripts; the API's 409s, the receipt preview and the page's wording; messages naming decks by id and the goldens' normaliser; the nightly check, backups and export), each reviewed and fixed, merged, then an integration review whose findings were fixed too. The cutover follows the build: merge into main, `python -m decklab.db migrate` (0007), register the nightly task again from the system python (`python -m decklab.db schedule install`), set the week's `restore_check_days` (0.5, so it runs every night: with 1 a night is skipped whenever the earlier steps finish sooner than the night before) and `side_by_side_until` (`2026-10-19`) in `config.json`'s `database` block, and restart the server. These docs already describe the state after it.
- **Decided differently from the plan** (PLAN.md, phase 5, has the list): split into 5a and 5b, so the rollback stays possible through the week; no deep check of the old code against the new (the user's choice); the inventory lock moved, not deleted; `files.py` stays, with `PRODUCT_INFO` frozen in it; the export gains `deck_revision` but not `audit.row_change`; the old row locators kept; the dump digests in their own column; and accessory rule breaks only a warning in the check.
- **Deleted:** `lib/inventory/journal.py` and `receive --recover`; `rules.encode`/`decode`/`checked_path`; `FileInventory`'s consistent-read wrapper, process lock and `deck_parts`; the busy fallbacks in `lib/decks` and `api/tokens.py`; `api/tracked.py` and the `BUSY` aliases; `gitops`' commit helpers (`commit_files`, `last_change`, `changes` and the lock, hook and trace helpers: `gitops.py` is now a read-only helper of about 200 lines that only `forge/lists.py` uses, for a `.dck` file's `{file, commit, dirty}`; `deck_lab_author` moved to `db/deck_history.py`); `NOT_DECKS`; `inv_orders._product_name_check`; `PgInventory`'s files overlay for a database without decks (it serves an empty decks part and refuses deck, accessory and picture saves with `DECK_SAVES_PAUSED`, which now says to restore the newest `decklab-*.dump` with `pg_restore`); the 409 answers' `"committed"`, `"commit"` and `"moved_to"` (`api/commits.py`, `saving.py`, `tokens.py`); and the editor's renamed-deck branch (a deck that's gone offers only Discard). `FileInventory` (the tests' backend) now writes plain atomic files under the caller's lock and refuses with `state.Conflict` when a file changed since its load. `write_deck_file` and its errors moved to the tests' `tests/deck_files.py`.
- **The lock** (`decklab/db/filelock.py`): `inventory_lock(repo, interrupted=False)` on `decklab/data/receipts/inventory.lock`, taken by `import-files` (and its decks import), `inventory restore-files` (which also refuses an `active.json`, even with `--force`) and `inventory backend`. An `active.json` can now only be left by the `pre-db-decks` code's receipt, and the refusal says that code's `receive --recover` clears it.
- **Wording:** `lib/decks`' `list_decks` gives a deck's id as its `source`, so the pool's, accessories', tokens', library's and editor's messages name decks by id, and so do the deck-table refresh's refusals and `ops_decks`' and `ops_accessories`'. "fix it by hand" became `rules.UNTIL_PUT_RIGHT` ("; it can't be changed until that's put right"), since Deck Lab itself refuses to save such a row. The pool's advice for an order whose cards are already in the collection is `pool.RECEIVE_IT` (receive it, on the Receipts page or with `python -m decklab.db receive --order <id>`, and take out the copies added for it on the Collection page), not "move the order file" or "set its status to owned in products/status.csv". A product component's cancel says there's no command yet to change or remove a pending product. The command lines' help describes columns and ids, not files; `accessories check` prints "Accessories: no problems" and `tokens check` "Token cards (<space>): no problems". `/api/deck/history` refuses a product deck or pairing by its id. The page's banners and messages say "deck" rather than "file"; the not-imported banner says to restore the newest backup and check `python -m decklab.db status`.
- **The receipt preview in plain labels** (`lib/inventory/changes.py`'s `changed_labels`): the Receipts page's "What this changes (N)" (was "N files will change"), `receive`'s preview and the order and product commands' `--dry-run` list labels such as "Home's collection", "Order <id>" (its record and payloads as one), "Product <name>", "The products' status", "The purchase queue", "Deck <title> (<id>)" and "The accessories", each once, instead of `magic/` paths. `changed_paths` still feeds the refresh.
- **The nightly check** (`decklab/db/check.py`, `python -m decklab.db check [--history] [--limit N]`): one read-only, repeatable-read connection as `decklab_ro`, with the inventory loaded on it and pinned, so every sub-check sees one snapshot. The sub-checks: accessories (a warning), tokens for every space in `config.json`, orders and queue (`purchases`' checks), deck tables (stale or unworkable tables a warning, saying why), deck revisions, deck texts, deck lines and deck headers (each deck's revision is its newest `deck_revision`, its `deck_text` that revision's text, its `deck_line` rows and header columns what the text parses to), revision rows (one row each in `inventory_revision` and `decks_revision`), the audit trail (every row change has its change set), and a files round trip (the export's files, built with `files.build`, give the database's snapshot; product names the files can't carry only warn). Each run is one `ops.backup_run` row of kind `check` (migration `0007_check_runs.sql`, which also adds a `digests` column) with the revisions and each sub-check's `{name, ok, warning, detail, seconds}`, and one `db.log` line per sub-check. Exit 0 passed (warnings allowed), 1 a sub-check failed or the run couldn't be recorded, 2 the database can't be reached.
- **Nightly, backups, status and the footer:** `nightly` runs backup, prune, export, check, then the restore check when due. A dump records `digest_rows` (an md5 over each public and audit table's rows as text, sorted bytewise, under fixed session settings) in the same snapshot as its row counts, in `ops.backup_run.digests`; the restore check compares the digests as well as the counts, and a dump without digests (from before 5a) by counts only, with a note. The dump's `detail` stays "rows: " and the counts' JSON, so a rollback's code still reads it. `status` shows "last check: <date>, passed | passed (N warnings) | FAILED: <sub-check> (<detail>)", a failed restore check with the last one that worked, "Side-by-side checks: until|ended <date>" when `database.side_by_side_until` is set, and a warning when the last check failed. `lib/dbstatus.py`'s `checks_warning` gives an admin's footer a warning when no check has run, the newest failed (naming the sub-check), it's older than `stale_backup_hours`, or the newest restore check failed.
- **Export, logs and schedule:** the export gains `tables/public.deck_revision.csv` (every deck's history, texts included); `audit.row_change` stays out of it, as before (the dumps hold it). `conn.LOG_FILE` comes from `DECKLAB_DB_LOG` when it's set, and the test package sets it to a temporary file, so no test (nor a test server or subprocess) writes the live `db.log`. `schedule status` warns when the task runs a program inside `.venv` (its `pythonw.exe` is a launcher that starts a second process), and `schedule install`'s refusal without psycopg says to install the `.venv` packages and run it with the system python.
- **The goldens** weren't recorded again: `gate_p4.EXPECTED_P5` (`deck-id-messages`, `phase-5-wording`), applied after `EXPECTED_P4`, maps the old goldens' deck paths in messages to ids and the old advice and wording to the new. `gate.pointed()` no longer patches path constants that no longer exist.
- **Forge-trial:** the overnight harness's identity records `deck_lists` (a sha256 of every deck's id with its target and substitute lists, re-rendered) instead of `magic_tree`, so an order's or receipt's table refresh doesn't block `--resume` but a changed list does, and a value that couldn't be read always counts as changed; its preflight checks that the decks can be read instead of comparing `magic/` with main's ([forge-trial/sim-combined-run.md](forge-trial/sim-combined-run.md), A1 and §5.3). `card_audit.py`'s docstring says the decks come from the database; `to_dck.py` and `run_matchup.py` note that the deck files are gone and what replaces them.
- **Tests:** new `test_db_check.py` (11), `FileLockTests` and a write-refusal test in `test_inventory_files.py`, `ChangedLabelsTests`, `test_db_gate`'s `test_phase_5_messages`, `DeckLabAuthorTests` in `test_deck_history.py`, and tests in `test_db_ops.py` for the digests, a restore whose contents differ, the counts-only fallback, the status lines, `side_by_side_until` and the `.venv` warning. Deleted with their code: `JournalTests`, `ConsistentReadTests`, the busy and journal 409 tests, the `--recover` tests, `SharedReplaceTests` and the two renamed-deck tests; the sandboxes no longer make git repositories. The whole suite run on this PC has 10 failures, all of which also fail on main: `test_db_core`'s `MigrateTests.test_a_changed_migration_is_refused` (the CRLF check, phase 1's known issue), `test_overnight`'s `test_item_job_leftovers`, one `test_forge_slots` test, `test_guide` on the `vader-and-ani` and `yoshimaru-dogs` decks, `test_inventory_decks`' two `RefreshInOpTests` (in a worktree without the card index), and three `test_server_lifecycle` tests.
- **It closes** phase 4's open items about decks named by their files in messages and the 409s' `"committed"` and `"commit"`.
- **Known low issues, left open:**
  - `api/saving.py`'s and `api/receipts.py`'s docstrings still describe the deleted cross-process lock ("finding the inventory lock taken (BUSY)", the lock order), and two test comments mention BUSY.
  - Some comments in `editor.js` and `editor-screen.js` still say "the file" (rebase, undo placement, `FILE_FIELDS`); none is shown.
  - The receipt preview's `changes` now holds labels, not paths; nothing outside the tests reads them. A raw import's label shows its stored name, an accessory picture's its file name, and a path the labels don't know falls back to the path (the database backend doesn't produce one).
  - `pool.RECEIVE_IT` also shows for a real order of more copies of a printing already owned, where taking copies out would be wrong; "or its cards count twice" covers both cases.
  - Messages still point at rows by their old files (`magic/tokens.csv line N`, `status.csv line N`, `magic/products/<stem>.csv`, `kit.py`'s "isn't in products/status.csv", `forge/field.py`'s "products/status.csv can't be read"), pinned by the goldens. A deck-table refusal naming a bare `<slug>.md` can't be normalised (no golden holds one).
  - An overnight run folder recorded before 5a has `magic_tree` in its identity, so its `--resume` refuses (those runs are finished). In a worktree with no `.venv` the system python can't read the decks, so the harness's A1 fails there.
  - Migration 0007 changed during the build (the `digests` column); that was safe only because no database had applied it.
  - `gitops` stays only for the Forge-trial `.dck` provenance; it can go if that flow is retired.

**UI redesign** (2026-10-13, asked for by the user after the UI/UX and design review of 2026-10-12, [UI-REVIEW.md](UI-REVIEW.md): "fix all"): the page felt clunky and ugly (no app shell, no shared components or scale, text where card pictures belong, pages that dumped data instead of answering, everything at the same weight), so every page was rebuilt on one set of shared pieces. Built on branch `ui-found` in three stages: stage 1 the foundations (UI-REVIEW.md's WP1-WP5: design tokens, base and components, the app shell and Settings, the card tile and row, Scryfall's symbols and the swipe card viewer); stage 2 the pages, in seven packages in parallel worktrees (Receive delivery; the deck page; Collection, Tokens, Sleeves & boxes and Wishlist; Shopping, the Packing plan and the Game log; the editor; Matchups; Activity and History), each reviewed and fixed, then merged with the fixes the full suite asked for; stage 3 a cleanup, two rounds of review from screenshots at phone, tablet, desktop and QHD widths in both themes, with their fixes, and these docs. [UI-KIT.md](UI-KIT.md) is the guide the page packages followed, and the reference for new pages.
- **The owner's decisions:** "fix all" (every finding of UI-REVIEW.md's sections 3 and 4); the editor fully on the iPad and a Quick edit on the iPhone (undoing `cd354e2`'s desktop-only editor); "Planned list" and "Play-now list" as the page's names for the two lists (the deck text's headings, the `Built version` values and the version keys unchanged); a teal accent (links and information stay blue); the library picture automatic and changeable through a new optional `- **Cover card:** Name [(SET) 123]` header line; and a large card viewer with swipe between cards on phones for every card list.
- **Decided along the way:** a run control that can't be used stays the page's own button, disabled, with the reason on the line under it naming who can start runs ("Only Matt can start simulations right now"), instead of WP2's "Ask Matt to play this" button; chips only for exceptions (so no "Ready to play" or "Not in use" chip); red only for what stops a deck being played, advice amber; one dark-theme block (`:root[data-theme="dark"]`), with `app.js` always setting `data-theme` (Auto resolved with `matchMedia`); the Game log's quick record saves after an 8-second Undo with the review token the server gave; the Wishlist's Undo puts a card back at its old place (`at`, `rules.insert_slot`); Receive delivery's preview and apply contract unchanged (the view's new fields sit beside the rows, never in them, since a receipt's `_edited` compares the rows' keys); `UI-KIT.md` beside `UI-REVIEW.md` rather than in `web/`, which may only hold files the server serves.
- **Foundations:** `tokens.css` (the type scale, a 4 px spacing grid, radii, elevation, the colours with their dark pairs, control sizes with a denser step for a mouse, and the breakpoints: phone under 600 px, portrait tablet to 999, desktop or landscape iPad to 1,599, QHD above), `base.css` (one rule for every field, 16 px so iOS doesn't zoom) and `components.css` (buttons, toolbars, fields, segmented controls, chips, notes, tabs, sheets that are bottom sheets on a phone, dialogs on a desktop and side panels from 1,280 px, menus, the action bar, toasts with Undo, data tables); every page stylesheet only lays these out, and a test fails on a literal size, radius, shadow or colour in one. `style.css`, `devices.css` and `card-dialog.css` are gone. `cards-ui.js` (`cardTile`, `cardRow`, `tokenTile`, `pickPrinting`), `symbols.js` with `/sym/<code>.svg` (`lib/api/symbols.py`, Scryfall's SVGs cached in `decklab/data/symbols/`), and `card-viewer.js`, which every card list opens over its own cards, swipeable on a phone, with the arrow keys from 1,000 px, and a history entry so Back closes it. `/img/` gained `large` and `art_crop` (and `-back`).
- **The shell:** core.js's routes table gives each page its one name, place and visibility; `shell.js` draws the top bar (Decks, Collection, Shopping with a deliveries count, Matchups, More), the phone's tab bar and More sheet, crumbs on child pages, the avatar menu (Theme, Switch person, "This is my device", and an admin's Settings and About), and the "Forge playing" pill (`runs-pill.js`, `GET /api/matchups?running=1`). `settings.js` (`#/settings`) took the simulations setting, the Forge workers, the version and Check for updates out of every page's footer, which is now one line (the prices' date and rate). The library's row of nine buttons is gone.
- **The pages:** the library as a shelf of tiles with each deck's cover art (`lib/decks/cover.py`, `lib/api/cover.py`, `cover.js`: `GET /api/deck/cards`, `POST /api/deck/cover`), one readiness chip in words, Ready first / Recently changed / Name, and filters behind a sheet on a phone; the deck page as a head, an availability banner and five tabs (Overview, Cards, Stats, Practice, Matchups) in the address, each drawn when it first opens (`GET /api/deck?omit=matchups` until Matchups does); the editor in two columns with Add (a finder, `GET /api/deck/find`, that adds on a click), Stats and Checks, dense rows or picture stacks, save in place with Ctrl/Cmd+S, Ctrl+Z, Paste with a diff, a Notes tab for the write-up, new decks from a paste, a precon or another deck, and the Quick edit on phones; Receive delivery as a check-off board of pictures (PLAN.md's item 9) with a sheet per card, splits, a sticky bar, a plain-words preview, a "Where these go" view and the check kept in the browser; Shopping's deliveries with picture strips, Follow-ups with **Done** (`POST /api/shopping/check`, the inventory's `order.checks` resolve), the decks still missing cards and the long-term plan; the Packing plan as a deck checklist and steps of picture tiles with saved ticks; the Game log's one-tap record; Collection's Find cards tiles and a sortable, paged Card list; Tokens as tiles with labelled example art for rows with no printing; Sleeves & boxes with click to edit and a "Built decks without sleeves" panel; the Wishlist as tiles with an edit sheet (`"action": "set"`); Activity in plain headlines with filters by kind and person (`kind=`, `actor=`); History with each revision against the one before it and its cards' pictures; and the Matchups home as a matrix of every deck against every other, a verdict-first pair page and one run vocabulary (Quick look, Settle it, Precise).
- **Server, besides the routes above:** `GET /api/decks` and `/api/deck` give each deck's cover, colours and revision (and the library an `edited` time, from `inventory.deck_edited`, which counts only real edits); `/api/cards/printings` each printing's set name and picture; the receipt view `today`, each row's picture and decks, a product's items and the token face names; Shopping the cards' pictures, the decks still missing cards and the checks; history the change against the revision before; the wishlist a deck source's title; Activity a headline per change, worded from the rows the viewer sees, with exact counts past the row cap. The pool's, the editor's and the table refresh's warnings and errors name the Planned and Play-now lists. The inventory goldens weren't recorded again: `gate_p4`'s `ui-additions` lists the answer fields the redesign added as an expected difference.
- **Tests:** new `test_shell_ui`, `test_symbols`, `test_cover`, `test_library_ui`, `test_deck_page_ui`, `test_editor_ui`, `test_editor_writeup` and `test_shopping_checks`, the viewer's Node tests in `test_card_inspector`, and much larger page tests (`test_receipts_ui`, `test_feature_ui`, `test_play_ui`, `test_wishlist_ui`, `test_activity_ui`, `test_web_matchups`, `test_web_pages`, whose source test fails if "owned-only", "target list" or "substitute list" come back into the page's words). The whole suite run in the worktree on 2026-10-13 ran 3,916 tests in about 12 minutes (32 skipped), with 10 failures, all known outside the redesign: `test_db_core`'s changed-migration check (the CRLF check), `test_overnight`'s `test_item_job_leftovers`, one `test_forge_slots` test, `test_guide` on the `vader-and-ani` and `yoshimaru-dogs` decks (also on main: live deck data), three `test_server_lifecycle` tests, `test_db_ops`' export-folder test (a worktree isn't the repo it guards), and one `test_db_ops` backup test that passed when run again alone (load).
- **Known low issues, left open** (PLAN.md's item 10 has the larger ones):
  - ~~No page lists every out-of-date owned-vs-needed table: each deck page says its own (Update the table, on its Cards tab), and the editor lists others after a save. Receive delivery's note after a failed refresh still says the tables stay on "the Decks page's list of stale tables", which doesn't exist (it said the Library's before, equally wrong).~~ Fixed 2026-10-13: the Decks page has that list now, and the note links to it ("Tables out of date", below).
  - Checked in headless Chrome with device emulation and touch events, not yet on the real iPhone and iPad.
  - The Quick edit has no Notes, Paste a list, picture look, Played by, Archetype, Built version, Sleeves or Deck box, and Try a change needs a tablet.
  - Only the Collection's Card list sorts its columns; the deck page's price table doesn't.
  - Comments: `editor.js`'s header says new decks start from 600 px (the Quick edit makes them on phones too), and `app.js`'s header lists the scripts in their old order.
  - The "Forge playing" pill has no room between 600 and 720 px and doesn't show there.
  - A first visit while Scryfall can't be reached draws lettered circles for the symbols (`/sym/` answers 503 for five minutes, then tries again).
  - A Cover card line Deck Lab can't use stays in the text until the picker's Automatic removes it, and the picker offers no Undo over it.
- **Device pass (2026-10-13):** checked on the user's own devices (iPhone 15 Pro and 17 Pro in both orientations, iPad Air 11 in both, MacBook Air 13 at default and More Space scaling, and a maximised Chrome on the QHD monitor; UI-KIT.md's "Test devices"), every page in both themes, then fixed in branch `ui-devices`: the avatar back at the top bar's right; a phone on its side gets a static top bar, the Quick edit and a card viewer with the words beside the card; safe-area padding on the sticky bars; the iPad editor's search kept above the keyboard with wrapped names; the card peek and Matchups' side list from 1400px for the MacBook; panels that stack without holes from 1000px; a two-column deck Overview, four packing columns and capped forms and search boxes at QHD; Shopping's picture strips kept inside their cards; the viewer's light-theme counts and buttons; swipes from beside the card; menus that open above a bottom bar; one-row History strips; the touch edit sheet on Sleeves & boxes opening at its picture; and a listen backlog of 128 so several devices loading at once aren't refused stylesheets.

**AI fixes, round 1** (2026-10-13; built; merged, installed and measured 2026-10-20/21, `etb-harmless-1` adopted for The Free Peoples, replayed and cleaned up 2026-10-21: [forge-trial/ai-round1-results.md](forge-trial/ai-round1-results.md)): the first round of fixes to how Forge's AI plays Deck Lab's lists, from a scout of where the AI misplays them (twelve ranked candidates, each checked by a second reviewer, whose corrections won). Built from a written contract in packages, each in its own worktree with one owner per file, reviewed and fixed, then merged into branch `ai-r1` of the fork (`C:\VSProjects\forge-wt\ai-r1`) and of this repo (`C:\VSProjects\TCC-wt\ai-r1`). Both were merged and installed on 2026-10-20 (Forge `2.0.15-decklab-52387e83f`) and measured overnight: the optional-target fix (`etb-harmless-1`) was the one clear win, for The Free Peoples, and is adopted in its pilot; nothing else is (PLAN.md's item 2).
- **The owner's decisions:** AI fixes in the fork are off by default, each behind a switch id, turned on per deck list through the existing pilot switches (`decklab/simulation.json`, `-dlpilot`), and adopted only after a paired A/B. So that a default-off build doesn't force a replay, the engine key no longer follows the fork's commit. The Gisa/Bontu fix (`af513b9fd`) becomes a listed game patch, on by default. Override sets for single cards are experiments, not adopted.
- **The engine key:** the engine's `"forge"` field is now the engine release (`install.engine_forge`, `id_version` 3): stock Forge's release (`2.0.15`); for a fork build from this round on, the `base=` release plus `+res.` and the first 12 hex of `res_sha256`, a hash of every file under `forge-gui/res` the fork changes (the fork's `install.py` always writes it now); for an older fork build without that line, its full build name; unknown when `decklab-build.txt` can't be read (then the remembered release, else the run is refused). Two builds with the same base release, the same changed res files and the same game-patch ids share a key, so a build that only adds default-off switches keeps every saved result current. The build name (`forge_version()`) still keys cardlog-check, `CHECKED` and the card-log jar. The one-time re-key costs nothing: every saved result is already an earlier engine.
- **Game patch `gisa-bontu-1`:** the Gisa/Bontu fix's Java paths (`TokenAi`'s X, `ComputerUtil`'s `SacToDraw`) are gated by `forge.game.GamePatches.on()`. With `-Ddecklab.gamePatches=off`, Ghoulcaller Gisa and God-Eternal Bontu count as removed from AI decks again (`GamePatches.remAIDecks`, read by `isCardRemAIDeck`, `CardPredicates.isRemAIDeck`, `PlayEffect`, `CopyPermanentEffect` and the AI's sideboarding), so plain Forge plays as stock. `forge-patches.txt` lists it on seven classes; Deck Lab and `GameLoop` de-duplicate the ids.
- **AI switches** (`forge.ai.AiSwitches`, listed in forge-ai's `decklab/ai-switches.txt`). Each is off unless a seat's pilot names it, and always off with game patches off. Deck Lab plugs `Pilots.forkOn` in as the hook by reflection at start-up, and `-dlpilot` refuses a fork switch when that failed.
  - `removal-in-combat-1` ("combat-removal fix"): `ComputerUtilCard.useRemovalNow`'s "remove a blocker to save my attacker" test ran on the opponent's turn, the wrong way round. On, it runs on the AI's own turn. It never retargets: it helps only when the chosen target is already the blocker, so cards like You Cannot Pass! gain most.
  - `etb-harmless-1` ("optional-target fix"): an "up to one target" ChangeZone sub or trigger with nothing to hit no longer vetoes the card (`ChangeZoneAi`), and an untargeted DestroyAll trigger or sub with both lists empty is harmless (`DestroyAllAi`). It covers Samwise the Stouthearted, Fires of Mount Doom and Fiery Annihilation. The broad `AiController` change the scout proposed was dropped on review.
  - `prowess-precombat-1` ("prowess-first fix (experimental)"): with an untapped creature that can attack and has prowess or a matching SpellCast trigger, a cheap (mana value 3 or less) noncreature Draw, Dig, Scry, Surveil or DealDamage spell is cast in main 1 (`ComputerUtil.castSpellInMain1` through `ProwessFirst`). Kept small: the owner isn't sure Izzet Otters is prowess-first.
  - Each has a TestNG test in the fork showing Forge's own result with the switch off and the intended one with it on (`RemovalInCombatSwitchTest`, `EtbHarmlessSwitchTest`, `ProwessPrecombatSwitchTest`), and the foundation has `AiSwitchesTest` and `GisaBontuPatchTest`.
- **The decision log** (not a switch: it only prints): `-Ddecklab.decisionLog=<names>` makes `AiController.chooseSpellAbilityToPlayFromList` print one `DLAI|` line per evaluated ability of a named card (turn, phase, seat, decision, API). Deck Lab sends it from `config.json`'s `forge_decision_log` (with `--local`, since a JVM reads the names once), and `python -m decklab.lib.forge decisions <folder>` counts opportunities, taken and declined, per phase and per seat (`decisionlog.py`). `AiDecisionLogTest` checks the AI's choice is the same with the log on.
- **Experiment override sets** (`overrides/sets.json`, status `experiment`): `etb-tfp` (Fires of Mount Doom's narrow ChompEquip edit, Éowyn, Fearless Knight's BadETB, Samwise's OptionalDecider), `etb-tfp-jailer` (Palace Jailer's BadETB) and `cmdr-hints` (Primal Might: `AILogic$ Fight` on its pump and `AILogic$ Always` on its fight, so FightAi keeps the target it chose from the pumped values). Puca's Mischief was checked and dropped: Forge's AI can't choose its exchange well.
- **Tools:** `python -m decklab.lib.forge engine-check --old DIR [--new DIR]` plays the same seeded games with two installs (cardlog-check's lists and any `--pair`) and compares them line for line, with the two engine keys; `--old` equal to `--new` is the noise floor. It only reports, and writes no results, `forge-version.txt` or `engine.json`. `pilots` lists the installed build's fork switches.
- **Tests:** the fork's AI tests (`forge/ai/**/*Test*`, Maven) ran 391 with no failures on `ai-r1` (355 before the round, none failing then). This repo's whole suite on `ai-r1` (the main checkout's `.venv` python, `DECKLAB_FORGE_FORK` naming the fork's `ai-r1`) ran 3,966 tests (33 skipped). Besides the expected one below, the failures were `test_forge_contract`'s pinned set list (fixed at the merge), three that fail on `main` too (`test_db_ops`'s export-in-repo test and `test_guide`'s mulligan check for vader-and-ani and yoshimaru-dogs), and six that come from the worktree (the `.venv` launcher's second process in `test_server_lifecycle` and `test_forge_slots`, a temporary file in `test_overnight`, and the CRLF checkout of a migration in `test_db_core`), which pass with the system python or on `main`. `CheckedSourceTests` fails until `cardlog-check` runs with the new Java sources, as expected.
- **Known low issues, left open:**
  - C6 doesn't sequence burn at the face, and leaves out Adventure and MDFC spell halves on creature cards; X burn always passes the mana value cap; a SpellCast trigger for an opponent's spells still counts. With it on, cheap burn at a creature in main 1 skips `useRemovalNow`'s later checks: watch for burn spent on small creatures in E5.
  - C5 has no mirror case and never retargets. With it on, Forge's opponent's-turn reading is gone, which matters only in multiplayer (a third player's blocker).
  - C4 doesn't cover Massacre Wurm or Sunblast Angel. It covers every creature whose enters or attack trigger is an "up to one target" ChangeZone, so the AI may now spend a card whose value is its trigger on an empty board: watch for it in E4.
  - With game patches off, `Deck.UnplayableAICards` (forge-core, which only lists cards) and Deck Lab's own script readers (`ai.py`, `install.py`) still see Gisa's and Bontu's branch scripts. `ComputerUtilCard.AI_KNOWS_HOW_TO_PLAY_ALL_CARDS` has no gate, as nothing calls it.
  - The decision log needs `--local`; it can't split a mirror's sides; after an AI timeout a line can land in the next game; counterspells in the normal priority lookup, Storm spells below the minimum and Living End's skipped cascade spells never get a line; a face-down host is logged under its paper card's name.
  - Samwise's OptionalDecider also makes the Ring's tempt optional, which the real rules don't.
  - The switch hook's wiring is tested end to end only by the real-Forge test `test_a_fork_switch_reaches_the_seat` (passed against the install on 2026-10-20).
  - `replay` didn't pick up results re-keyed by a pilot change: it judged a saved result "today's" with the pilots its sides were played with, not today's (`cli_results._replay_plan`). After `etb-harmless-1` went into TFP's pilot its dry run listed none of TFP's matchups, so TFP's and Izzet's fields were played with `field`. Fixed the same day (today's pilots decide; test `test_a_result_re_keyed_by_a_pilot_change_is_replayed`), and the fixed `replay` then topped up three TFP matchups whose earlier results had more games than the field's budget (400 games). The rankings and the field view already judged by today's pilots.
- **Finished 2026-10-21:** one `replay` (20 matchups, 23,280 games, 49 minutes), then `field` for The Free Peoples (45.1 % against an average house deck, rank 7 of 11), Izzet Otters and Gandalf's 11 missing games; `replay --dry-run` now finds nothing to replay. The worktrees (`forge-wt/{base,c4,c5,c6,c9,ai-r1}`, `TCC-wt/ai-r1`) and the merged `ai-r1*` branches in both repos are removed.

**Visits** (2026-10-13, asked for by the user: to see whether User1, User2, User3 and User4 actually use Deck Lab and what they look at, as informal user-testing feedback): the server records who visits and which pages they open, and an admin reads it in a new **Visits** part of the Settings page or with `python -m decklab.db visits [--days N] [--profile P]`. README.md's "Visits" (under Database) says how it works.
- **Who and what:** only a profile `config.json` lists, and only the requester: the tunnel login's (`remote`) or the profile the home page's chooser names (`home`); a request naming nobody is never recorded. Per profile, day and channel the first and last time and the API requests; and the pages, from a beacon in the page's router (`noteVisit` in app.js, `POST /api/visit` through `apiWrite`): the route's path and, on a deck's pages, the deck's id, nothing else of the address. The beacon isn't a data write (no change set, no permission rule), and a `profile` in its body must be the requester's own.
- **Storage:** migration `0008_visits.sql`: `ops.visit_day` (one row per profile, day and channel: `first_at`, `last_at`, `requests`) and `ops.visit_page` (its pages: route, deck id, opens, last time), beside `ops.backup_run`: not audited, not exported, outside the dumps' content digests; `decklab_app` may add and update but not delete, and the nightly task's new `visits` step (after `prune`) deletes days older than 400.
- **Cheap:** `lib/visits.py`'s Recorder gathers in memory under a lock and a timer thread writes once a minute in one transaction (and when the server stops); a failed write is logged once and kept for the next try, up to 5,000 rows. `GET /api/visits` writes what's waiting first, then reads as `decklab_app` with the request timeouts; it answers admins by role and a home request naming nobody, 403 to anyone else.
- **After review (the same day):** the page's own polling (`/api/status` every 30 seconds, the runs pill) made a tab left open count as seen all day, so only the beacon now makes a day and moves its times; requests are just a count, added to a day a page was opened on (a requests-only row in `write()` is an update, dropped when there's no day). The beacon keeps a deck id only for a deck that exists (`deck_exists()`, the library's ids cached for a minute, 10 seconds for a miss), and the recorder keeps at most 200 different pages per profile, day and channel across writes, so one signed-in visitor can't flood the tables with made-up deck ids and crowd out everyone else's visits. `request()` says when it had no room. Writes connect with a 2-second timeout and lock and statement timeouts; `GET /api/visits`' write waits at most a second for one under way and is skipped while writes fail, and so is the last one at the server's stop. The summary's pages come back in a fixed order (ties by route and deck), and the `visits` command lists every profile (unseen ones as not seen yet), names decks by title and caps `--days` at 366.
- **Tests:** new `test_visits.py`: the recorder (gathering, unknown profiles and routes, deck ids kept only on a deck's pages, requests that never make a visit, the per-day page cap, a failing write, a request's and close's write not waiting on a failing database, the memory cap, eight threads at once, the timer and close), `deck_exists()`' cache, the beacon's rules (tunnel, home, nobody, another's profile, bad bodies), the admins-only view, the home listener counting requests and refusing a beacon without the write header, the tables on a throwaway database (sums, the summary, the app can't delete, the owner's prune cascading, no change set, out of the digests and the export, the checks), and the page's beacon and Visits part under Node. `test_db_ops`' nightly order gained the `visits` step, and `test_activity_ui` and `test_wishlist_ui`, which list every API read a route makes, stub the beacon. The whole suite on 2026-10-13 ran 3,961 tests in about 13½ minutes (31 skipped); the failures left are known and outside this change: `test_guide` on the `vader-and-ani` and `yoshimaru-dogs` decks, and `test_db_ops`' export-folder test (a `decklab/data/never-made-export` folder left by an earlier run). The migration isn't applied to the live database yet (`python -m decklab.db migrate`, then restart the server).

**Home-network writes and the Game log** (2026-10-13, Matt's decisions of 2026-10-13: writes on the home network follow the picked profile's permissions, with scripts naming nobody still passing, and the other members don't see the household's Game log; design stories E10-S03, E10-S24 and the picture half of E8-S16): until now a request on the home network acted as an admin whoever the "Who are you?" screen named, so the read rules there hid things but didn't lock them, and `GET /api/play` sent every space's games to anyone.
- **Writes follow the picked profile:** `permissions.is_admin` gives a local request admin rights only when it names nobody; a named profile has the same rights at home as through the tunnel. So User1 picked at home can't change home's collection, tokens, receipts, orders or products, or Matt's and the 'either' decks, and User2 can change only his own space. On the home network, when the `X-Deck-Lab-Viewer` header names a profile and the body names another, `settings._writer` answers 403 "You can only make changes as yourself"; the settings PUT checks `guard.viewer()`; the editor's and History's `may_save`, the Collection's `editable` and a precon's may-add follow the viewer. A refused write answers only `{"error"}`. On the page, `deriveMay` gives admin by role once a profile is chosen, and `chooseProfile` uses it at home.
- **Accessory pictures name their viewer:** an `<img>` sends no header, so on the home network the page adds `&viewer=<id>` to `/accessory-img/` addresses (`accImgSrc`), and the server answers for that profile when no header is sent (the header wins; through the tunnel the login decides and the parameter is ignored). User2 picked at home gets 403 for every picture, and User1 only her own and the shared ones; an address per viewer also keeps a shared iPad's browser cache apart.
- **The Game log is kept to each deck's own people:** `permissions.sees_play_record(profile, deck_ids, local, space_of)`: an admin by role and a home request naming nobody see every game and plan; nobody through the tunnel without a profile sees any; anyone else those with a deck of their own space (a game's two sides, a plan's deck and opponent; a deck id that can't be read counts only for admins). `GET /api/play` filters games, sideboard plans and their warnings by it, and the Activity page's play_record rows ask the same rule. The deck lists stay in the answer, so a member may still record a game of their deck against a home deck.
- **Decided along the way:** a write always names its profile in its body, as before, so "naming nobody" means a request whose body and header name no profile; a script naming matt (an admin) still passes everything. The body must match the header rather than the header replacing the body, so a page that names the wrong profile is refused instead of acting as someone else. The Game log stays in everyone's navigation (the story's second choice): a member with no games of their own sees "No games with your decks have been recorded yet."
- **Tests:** `test_permissions` (is_admin for named and unnamed requests at home, `sees_play_record`, and User2 picked at home can't record a game of two home decks), `test_api_permissions` (User1 picked at home refused as through the tunnel, User2 picked at home refused home's writes with nothing of home's in the answer, home writes follow the profile picked), `test_play_records` (a member sees only their own decks' games and plans, User1 every game with a home deck, admins and nobody at home everything, a login not set up refused, a damaged record warned about only to those who may see it), `test_activity` (play records ask the Game log's rule), `test_server` and `test_server_access` (the header and the picture address's viewer), `test_accounts_ui` (the profile chosen at home has its own rights) and `test_play_ui`; the tests left on the old home-admin rule were fixed.
- **Known low issues, left open:**
  - `GET /api/me` at home still answers as for nobody (an admin's "may"); the page doesn't use it once someone is chosen.
  - The header and `?viewer=` are trusted: they say who's looking, not a login, so someone on the home network who deliberately names another profile isn't stopped. The rules stop slips on a shared device, not a lie.
  - A malformed `/accessory-img/` query is now answered 400 before the 403 a viewer who may not see the accessories would get.

**Shared sleeves** (2026-10-13, Matt's decision of 2026-10-13: one sleeve design may sleeve several built decks and intact products, and it's up to the players not to play two of them against each other; design story E8-S20, which also completes E2-S20 and changes E8-S08's picker): until now a sleeves row belonged to one holder and no two built decks could share a colour, so the picker, the editor and `deck push` refused sleeves another holder had unless they were moved, and `accessories check` reported shared designs and colours. There are more decks than sleeve designs, so that rule made decks wait for sleeves.
- **Choosing:** `kit.set` (`lib/inventory/ops_accessories.py`, behind the picker, the editor and `deck push`) no longer refuses sleeves another holder has; both keep them in one change. Deck boxes keep their rule: one box per holder, up to the row's quantity, else 409 with `taken_by` unless moved. The picker's tile says "Also used by X" (a holder the viewer can't see as "one of User1's decks"), and choosing it asks "Use them here too?" with Use them here too, Move them here (Take them from X when there are several) and Cancel; the move is offered only for holders the viewer can see, so a hidden owner's deck can only be shared with. The editor's sleeves tiles are enabled and say "Also used by …".
- **Checking:** `accessories.kit()` and `check()` no longer report a shared design or a shared colour. Each holder's need is checked against the row's quantity on its own, not the sum, so the only sleeves warning left is one deck or product needing more than the row has. `kit()` returns `shared_with`, the other holders' titles. The editor's "no sleeves" warning no longer says no two built decks share a colour.
- **The Packing plan** (`_sleeve_notes` in `lib/api/assembly.py`) notes two or more chosen holders in one design ("… are both in X sleeves: their cards look the same from the back, so keep each deck's cards together"), a note and never a block. A holder counts once, so an intact product's own decks, which share its one design anyway, never make a note on their own (found in review).
- **Decided along the way:** no warning beyond a single holder's count and the packing note (the design model's open question 1, answered by the story's criteria); `db/gate_p4.py` gained a "shared-sleeves" expected difference (`shared_sleeves()`), since the phase 4 goldens were recorded under the old rule; CLAUDE.md's "Sleeves and storage" and "Accessories" and README.md state the new rule.
- **Tests:** `test_accessories` (kit and check with shared designs and colours, each holder's count on its own), `test_inventory_accessories` and `test_api_accessories` (sharing accepted, both keep the row, a full deck box still refused), `test_inv_decks` (`deck push` with another holder's sleeves), `test_collection_assembly` (the packing note, an intact product counted once), `test_editor_contracts` and `test_feature_ui` (the picker's and editor's words and choices) and `test_db_gate` (the expected difference).
- **Known low issues, left open:**
  - `kit()`'s `shared_with` isn't shown on the deck page yet: the deck's own kit tile doesn't say which other decks share its sleeves (the picker and Sleeves & boxes' Used by do).
  - E8-S08's third criterion is still met only by value: a move takes sleeves from the other holder only while it still has them, without checking that holder's text wasn't saved meanwhile.

**Extra copies of owned printings** (2026-10-13, found in use the same day): the pool warns when every card of a pending order component or incoming product is already in the collection, since that usually means it was merged without a receipt and would count twice; the warning makes the pool incomplete, which stops every deck-table refresh and receipt. It couldn't tell that from a real order for a second copy of a printing already owned. That happened today: Matt opened the Stardew Valley Secret Lair drops and found Krobus (Academy Manufactor, SLD 7188), Junimo Farmhands (Sylvan Caryatid, SLD 7189) and Big Score (SLD 7190) as bonus cards, added with `collection merge`. The two pending eBay orders for second copies of Krobus and Junimo Farmhands then looked merged, and every table refresh was blocked.
- **The mark:** `python -m decklab.db order extra-copies ID COMPONENT -m "..." [--undo] [--dry-run] [--force]`, and `order add --extra-copies COMPONENT` (repeatable) in the same change as the order, mark a pending cards or product component as extra copies of owned printings. It's kept as one sentence in the order record's `audit_notes` ("Extra copies of owned printings: cards."), written and read only by `inventory.rules` (`extra_copies`, `with_extra_copies`), so no migration. The write is one change with the deck tables refreshed; received, cancelled and tokens components are refused. `pool.py` skips the "already in the collection" warning for a marked pending component.
- **Used live:** both eBay orders were marked, which unblocked the table refresh. The three Stardew token cards (Food SLD 2808, Ooze SLD 2819 and Treasure SLD 2820, single-sided) were recorded with `tokens add`, and the products' token checks resolved.
- **Tests:** `test_inventory_orders` (marking and unmarking, `order add` with the mark, refusals, the command) and `test_pool` (a marked component isn't warned about).
- **Known low issues, left open:**
  - `order split` doesn't carry the mark: the new part of a split marked component isn't marked, so it can bring the warning back until it's marked too.

**Tables out of date** (2026-10-13; design stories E7-S09 and E11-S10, PLAN.md's item 10): after a receipt, an import, a Collection page edit, a `collection merge` or a `deck push`, other decks' owned-vs-needed tables could be out of date with nothing listing them. Each deck page said its own and the editor listed others after a save, but `collection merge` said nothing, `deck push` named only its own deck, and Receive delivery's note pointed at a list on the Decks page that didn't exist. Token cards never change a table (the pool doesn't read them), so the Tokens page and `tokens add|edit|remove` needed nothing.
- **What blocks a refresh:** `table_blockers()` (`lib/inventory/refresh.py`, also `pool.table_blockers()`) lists, without ever raising, every problem that would stop `deck tables --apply`, across every space in library order: decks whose text can't be read, with no decklist, with no owned-vs-needed table, or with card names Scryfall doesn't know in the target or substitute list, and spaces whose pool is incomplete or won't load. The refresh's own plan (`_plan`) uses the same checks (`_read_deck`, `_list_problems`, `_pool_problem`), so the two can't drift; it still stops at the first. A deck with no table is now refused by id before rendering. `pool.stale_tables()` gained `only` and skips a space whose pool won't load instead of raising.
- **The list:** a "Tables out of date" panel on the Decks page (`library-tables.js`, between the warnings and the filters), filled from `GET /api/tables/stale` after the shelf draws and hidden when there's nothing to show or the request fails. It lists the out-of-date decks with **Update all**, which posts every deck the viewer may change in one `POST /api/tables/update`, so one change with today's prices (`MAX_TABLE_DECKS` went from 50 to 200 for it); decks the viewer can't change are said to wait for whoever plays them. Under it, the decks the refresh can't update, grouped by deck with each reason in plain words (left out of Update all), and a note for each space whose pool is incomplete: Update all skips that space's decks (as `deck tables --apply`, receipts and orders refuse them) until it's fixed. `#/library?tables=1` scrolls to it once. The editor's "Update their tables" after a save is the same code (`staleTablesPart` with options), still filtered to the decks the viewer may change.
- **The server:** `GET /api/tables/stale` answers `blocked` and `held` beside `stale`, each kept to the spaces whose inventory the viewer may see and without paths in its words; a deck in `blocked` is left out of `stale`. Every `stale_tables` list the API returns (a deck save, a new deck or precon, an update, the list) gives each entry `may_update`, from the guard's `tables.update` rule for the viewer. The Collection page's save and import answers carry `stale_tables` for the edited space.
- **The notes:** the Collection page's message after a save or import says how many decks' tables are now out of date, with "See them on Decks". Receive delivery's note about tables it didn't update links to the list ("They're on the Decks page's Tables out of date list, where Update all refreshes them").
- **The commands:** `collection merge` prints the space's out-of-date decks and `python -m decklab.db deck tables --apply -m "..."`; `deck push` and `deck new` keep the line about the deck's own table and name the other out-of-date decks of its space (`inv_decks.stale_notes`). When `deck tables --apply` would refuse, they say so and print each problem instead. The notes never change an exit code, and a failure to work them out is one quiet line. `deck tables`'s refusal lists every problem, not only the first. The order, product and receipt follow-up lines for decks they leave name the Decks page's list.
- **Tests:** `test_refresh_deck_tables` and `test_pool` (the blockers, the refresh's shared checks, a pool that won't load), `test_editor`, `test_deck_readers_p4` and `test_api_permissions` (the list's `blocked`, `held` and `may_update`, per viewer, through the tunnel and at home), `test_collection_edit` (`stale_tables` after a save and an import), `test_inv_decks`, `test_collection_ops` and `test_inventory_orders` (the commands' notes and wording), `test_library_ui` (the panel, Update all, a 409, `?tables=1`, the Collection note), `test_receipts_ui` (the link) and `test_web` (the script order).
- **Known low issues, left open:**
  - The panel has been checked only in the page tests, not yet in a browser or on a phone.
  - "Now out of date" (the commands and the Collection note) also counts decks that were out of date before the change.
  - `GET /api/tables/stale` loads each space's pool twice, once for the blockers and once for the list; fine at today's 19 decks.
  - The Collection page's link reads "See them on Decks" even when one deck is out of date.

**Database, phase 5b: the rollback retired** (2026-10-14, asked for by the user: "decklab seems to be working fine. do phase 5b now?", five days into the week of side-by-side checks, after two clean nights; design story E11-S04): the way back to the files is gone. Tagged `pre-phase5b` first (the last commit with the tooling), then built on branch `db-phase5b`. The week's nightly checks and restore checks go on to 2026-10-19, and its report still follows.
- **Matt's decision:** the export keeps its `magic/` folder and the nightly check its files round trip, since he wants two backup places (the NAS dumps and the GitHub export). So `files.py` stays as the tests' backend, the export's renderer and the check's reader; only its rollback role went.
- **Deleted** (about 4,500 lines with their tests): `inventory restore-files` and `inventory backend` (`inventory export` stays), `ROLLBACK_MIGRATION`, `set_backend` and `files_difference` in `db/inv_inventory.py`; `import-files` (`db/import_files.py`, `db/import_decks.py`); the gates (`db/gate_inventory.py`, `db/gate_decks.py`, `gate-inventory`, `gate-decks`, `python -m decklab.db.gate`); `history-preview` and `history-gate` (`db/inv_history.py`, `db/deck_history.py`); the OS inventory lock (`db/filelock.py`); `.gitattributes` (its one line was for `magic/accessories/images/`); `test_db_gate.py`, `test_import_decks.py`, and the import, backend, gate, lock and git-history tests in `test_inventory_ops.py`, `test_db_runtime.py`, `test_inventory_files.py` and `test_deck_history.py`.
- **The backend switch:** `config.json`'s `"inventory": {"backend": "db"}` is gone, and with it `inventory.configured()`, `BACKENDS` and `FILES_REFUSED`: `inventory.backend()` is the one a test installed, else the database. `dbstatus.inventory_view` no longer has a `backend` key, and a database that can't be reached always counts the inventory as stale; `status`'s line reads "Inventory: the database holds revision N, imported ...".
- **Moved:** `inventory_held` and `decks_held` (for `status`) into `db/inv_inventory.py`. The gate's reader dump and compare into `tests/golden_dump.py` and its phase 4 and 5 normaliser into `tests/golden_p4.py` (the contract tests still compare every reader with the committed goldens through them), without the command lines, recording, live runs and fixture tree. The frozen product names (`files.PRE_DB_PRODUCT_NAMES`) into `tests/pre_db.py`'s `PRODUCT_NAMES`: `files.PRODUCT_NAMES` is empty in Deck Lab and the test package fills it in.
- **The check's round trip** takes the products' names from the database's snapshot before comparing, since the files never carry them now; it no longer warns about them.
- **Kept:** `pg.write_model` and `pg.write_decks` with their `history` argument (the tests' fixture loaders); `test_deck_history`'s database tests now build a small history by hand instead of reading one from git. Migrations 0005 to 0008 and the `gate` rows in `ops.backup_run` stay.
- **Known low issues, left open:**
  - Older docs (HISTORY's phase 3 to 5a entries, the design's notes) still describe the rollback as it was; they're history.
  - `files.py` still reads git blobs (`git_files`, `from_git`), now only for the tests.

**Cards on the way and links from Shopping** (2026-10-14; design stories E6-S03 and E5-S16): a deck's Cards tab used to say only how many copies were on the way, and its price table disappeared when no further cards needed buying. The banner, card marks and price table now name each order or product and whether it is ordered or preordered. Shopping's To buy rows link to the home deck they are for.
- **Sources:** the pool keeps the actual order record id, component id, product id and ordered/preordered status in `incoming_sources`, alongside the existing availability counts. `_owned_json` clips source quantities to the incoming copies that deck needs; received and cancelled components do not contribute. The source details use the same pinned inventory snapshot and remain inside the deck's inventory-visible answer.
- **The page:** `deck-availability.js` holds the banner and shared source labels. The banner groups the awaited copies by source; the Cards tab and card viewer show the source and status for each awaited card, with counts once when a name has several printing lines. The folded price table stays available for incoming-only decks. No arrival dates were added.
- **Shopping:** `shopQueueRow` uses the already-resolved home deck's title, including a source-only match or missing card data. The deck link is separate from the card-viewer button and wraps on narrow screens; unmatched purposes remain plain text. The existing home-only read and write rules are unchanged.
- **Validation:** targeted backend, deck UI, Shopping UI/server, permission, shell and adjacent regression suites passed. They cover order record identity, required quantities, products, the pinned snapshot, privacy, deck banner/cards/table rendering, and Shopping navigation without breaking the viewer. The source-length audit reports the same five unchanged files over the limit as before this change; every touched source is below its limit. Browser inspection could not run because CUA exposed no browsers or apps; the real-device acceptance pass remains E2-S22.

**Done or dropped from the Later list:**
- ~~per-card stats from the card log~~ done in Milestone 8;
- ~~ranking all 45 Beginner Box pairings~~ dropped 2026-10-01: the Beginner Box has been broken up into the pool, so its pairings are no longer played as decks;
- ~~simulation speed and accuracy~~: investigated 2026-10-03 with idle-gated measurements. [forge-trial/sim-investigation.md](forge-trial/sim-investigation.md) explains why runs left the CPU idle and how far Forge's numbers can be trusted, and gives a ranked plan (its §3) split into parallel work packages (§5), built in three waves. All three built 2026-10-03, measured together that night and merged to main 2026-10-04 (see the wave 1, 2 and 3 entries above);

## Milestone 0 results (2026-09-29)

All eight steps were done on 2026-09-29 on this PC, with more than 40,000 simulated games. Every number here was measured, or read in Forge's source code at tag `forge-2.0.15`, unless it's marked as an estimate or a judgement. The notes and prototype scripts are in `decklab/forge-trial/` (the card-log Java source moved to `decklab/lib/forge/java/` in Milestone 8) (its raw logs, results and generated decks stay local and are gitignored): `setup-notes.md` (install, command, speed), `card-audit.md`, `formats.md` (40-card, 20-card and Commander), `logs.md` (per-card stats) and `scale.md` (parallel processes and the win-rate check).

### Verdict: go, with conditions

| Criterion | Result | Met? |
|---|---|---|
| Forge runs | Forge 2.0.15 plays full games with no window on the installed Java 26. | Yes |
| It supports nearly all the cards | All 612 card names in our decks, products and collection load; none is unsupported. The AI never casts 5 of the cards in our decks (see "Card support"). | Yes |
| A few hundred games finish in minutes, not hours | 16 workers played 3,200 games in 3.5-4 minutes for most pairs (790-905 games a minute) and in 14 minutes for the slowest pair. Only 4-player Commander is slow, at about a minute per game. | Yes |

Conditions, which Deck Lab has to meet or its results will mislead:
1. **Check Forge's output itself.** Forge names a winner even when a game timed out or crashed, silently drops card names it doesn't know, and exits with code 0 even when a deck fails to load.
2. **Show the cards the AI can't play** beside each deck's results, and mark the Gisa decks' results as not meaningful.
3. **Flag go-wide pump decks.** Forge rates Selesnya Rabbits 12-15 points below the report, mainly because its AI holds Overrun-style spells and attacks too little.
4. **Report the win rate balanced for play and draw,** because Forge lets each game's loser start the next.
5. **Per-card stats need the card log** (a small Java add-on), because Forge's own log never shows draws.
6. **Treat 4-player Commander results as statistics:** pods are slow and don't replay exactly.

### Installing and running Forge

- **Install:** the portable build `forge-installer-2.0.15.tar.bz2` (297 MB download), extracted to `C:\Tools\forge` (423 MB in 21,480 files).
- **Java:** the installed Oracle JDK 26.0.1 works, so no Java 21 was needed. Call `C:\Program Files\Java\jdk-26.0.1\bin\java.exe` directly: the `java.exe` on the PATH is a small launcher that starts the real one as a second process, so timing or stopping it misses the real one.
- **Command**, run from `C:\Tools\forge` (Forge finds its card files relative to the current folder):

  ```
  "C:/Program Files/Java/jdk-26.0.1/bin/java.exe" -Xmx1024m -XX:+DisableExplicitGC
      -Dio.netty.tryReflectionSetAccessible=true -Dfile.encoding=UTF-8
      -jar forge-gui-desktop-2.0.15-jar-with-dependencies.jar
      sim -D <deck folder> -d gruul-ramp.dck izzet-prowess.dck -n 200 -s <seed> -c 120 -a Default Default
  ```

  - `-D` is the deck folder and `-d` the file names in it; absolute paths after `-d` don't work. `-n` is the number of games, `-s` the random seed, `-c` a time limit per game in seconds, and `-a` the AI style for each deck. `-q` prints only the results.
  - `-Xmx1024m` caps the memory Java keeps for Forge's game data (its heap) at 1 GB. A whole process peaked at 0.7-1.3 GB, and this was enough for every format. `-XX:+DisableExplicitGC` stops Forge forcing a full memory clean-up after every game; games got about 14% faster with identical results.
  - **Added 2026-10-03 (simulation wave 1, R01a): `-XX:ActiveProcessorCount=2`.** Each Java process otherwise sizes its compiler and garbage-collector threads for all 32 logical CPUs (15 and 23 threads), so 16 processes starting together fight over the cores. With the flag each gets 2 and 2: the investigation measured 1,011 → 1,086 games a minute and start-up 5.2 → 3.4 s on 16 processes, with the same winners (checked on Izzet vs Gruul). Forge's per-attack thread pool also drops from 32 threads to 2. Re-check it after a JDK upgrade. With the card log on, the card-log jar now also comes first on the class path (`-cp <card-log jar>;<Forge jar>`), since it holds Deck Lab's copy of Forge's `AbstractMulligan` without its 100 ms pause per mulligan.
  - Point `APPDATA` and `LOCALAPPDATA` for the Forge process at a folder in the cache. Forge keeps its user folder there; otherwise every process leaves a full copy of its output in `%APPDATA%\Forge`, and nothing deletes them.
  - In that folder, `Forge\preferences\forge.preferences` holds `LOAD_CARD_SCRIPTS_LAZILY=true`, so at start-up Forge only builds an index of card names (about half a second) and loads each card fully when it's first needed. Start-up drops from about 9 s to about 1.3 s, with the same games.
  - Forge's own `forge.cmd` doesn't pass its arguments on, so it can't be used.
- **Same seed, same games.** Seeded 1v1 runs replayed exactly with every memory and loading setting, under full load, and with the card log.
- **Who goes first:** game 1 is random. After that, the loser of the previous game starts, since the AI always chooses to play first.
- **Forge's output can't be taken at face value:**
  - A game that hits the `-c` limit prints `Stopping slow match as draw`, but is then reported as a win for an arbitrary player, and so is a game that crashes. Count a win only when exactly one player "has won" and no timeout line appeared.
  - A card name Forge doesn't know is removed from the deck with only a warning on stderr, and the game runs anyway.
  - Forge exits with code 0 even when a deck fails to load (`Could not load deck`).
- **Deck files (`.dck`):**
  - `[metadata]` with `Name=`, then `[Commander]`, `[Main]` and `[Sideboard]`.
  - One line per card, name only (`4 Llanowar Elves`), with repeated printings merged. The printing doesn't matter to a simulation, and an unknown set code silently falls back to any printing anyway.
  - Double-faced cards go in by their **front face**. Forge knows `A // B` only for split cards like `Fire // Ice`; adventure, transform, modal and flip cards written that way are dropped. In our decks this affects Murderous Rider and Pollen-Shield Hare.
  - Sim mode doesn't check deck size, copy limits or singleton, and never sideboards (the sideboard is loaded but unused).

### Speed and memory

One Forge process, Gruul Ramp vs Izzet Prowess (owned lists), 50 games:

| Settings | Start-up | Time per game | Peak memory | Cores busy |
|---|---|---|---|---|
| Forge's defaults, `-Xmx1024m` | 8.6 s | 0.81 s | 1.0 GB | about 3 |
| Recommended (lazy loading, `-XX:+DisableExplicitGC`) | 1.3 s | 0.69 s | 0.74 GB | about 2.3 |

- Games took 0.2-2.7 s each. The step 2 run of 100 games took 74 s after a 9 s start-up.
- Memory follows `-Xmx` (2.1 GB with Forge's own 4 GB setting), and speed was the same from 512 MB up.
- A game runs on one thread, but Java's memory clean-up and compiler keep 2-3 cores busy per process.

**Many processes at once** (Gruul vs Izzet, recommended settings, all started together, 50 games each; games per minute while all were playing):

| Processes | 1 | 4 | 8 | 12 | 16 | 20 | 24 |
|---|---|---|---|---|---|---|---|
| Games per minute | 87 | 275 | 435 | 500 | 539-575 | 570 | 521 |
| CPU busy | 22% | 44% | 72% | 85% | 90-95% | 97% | 100% |
| Total memory | 0.7 GB | 2.8 GB | 4.9 GB | 7.2 GB | 9.4 GB | 11.6 GB | 13.6 GB |

- Throughput stops rising at **16 processes**, one per physical core. Forge's default settings reached only 420 a minute at 16, with 44 s start-ups.
- **Batch size matters most.** When 16 processes start together, each loses about 55 s (about 55 games' worth) to start-up and to Java compiling Forge's code as it warms up.
  - A process's first 10 games are 5 times slower than a lone process's; from about game 50 on, twice as slow.
  - So 50-game batches waste about half the run. 150-game batches averaged 685 games a minute, and warm processes run 900-950.
- **Recommendation for `config.json`:** 16 workers (12 while the PC is used for other things), 200 games per batch, `-Xmx1024m`, lazy loading and `-XX:+DisableExplicitGC`. That's about 9.5 GB of memory in all.
  - Use at least 100 games per batch, and 100 for slow, board-heavy matchups so the last batches don't leave most workers idle.
  - For jobs under 1,600 games, use about one worker per 100 games rather than smaller batches.
  - Start one Forge process on its own the first time a Forge user folder is used: 16 starting together raced to create its folders, and one crashed.
  - **Superseded 2026-10-03 (simulation wave 1, R02 with R01a).** The batch advice above was measured without `-XX:ActiveProcessorCount=2`. With it, 16 short cold batches pay (the investigation's e2 and e3 measurements), so Deck Lab now uses batches of at least 25 games and up to one per worker, all started at once. Measured with Deck Lab's real seeds on Izzet vs Gruul (two runs each): 200 games 56.1 → 30.7 s, 800 games 82.4 → 66.5 s, 1,600 games 118.1 → 108.7 s, 3,200 games 202.1 → 186.6 s. The 1,600- and 3,200-game shapes didn't change, so their gain is the flag's (the mulligan copy added nothing measurable at 16 processes). 400 games wasn't timed (estimated ~75 → ~40 s). See the wave 1 entry.
- **Real matchups at those settings:** 790-905 games a minute for Angels vs Zombies and Izzet vs Gruul; 230 a minute for Rabbits vs Vampires, whose big token boards slow the AI down.

### Card support

- **Unsupported cards: none.** All 612 card names (351 in the 11 deck files, 513 in the 6 product lists, 443 in the collection and orders) have a working Forge card script. Two checks agreed: reading Forge's 33,980 card scripts the way Forge does, and loading every name in real games.
- **Names:** only the 2 adventure cards above differ from Scryfall's names. Six of our cards (Lightning Bolt, Swords to Plowshares and four more) share a name with the back face of a newer card; Forge still picks the right one (tested).
- **Cards the AI never plays.** Forge marks about 2,500 card scripts `AI:RemoveDeck:All`, meaning its AI can't use them well. In a simulation the AI then never casts them or activates their abilities, and Forge doesn't say so. Separately, it never casts Fiery Annihilation (0 casts in 9,600 games): its optional "exile up to one Equipment" part has nothing to target in our games, and that makes the AI reject the whole spell.

  | Deck | Cards the AI never plays | Effect on results |
  |---|---|---|
  | Gisa Zombies (Commander) and the Wretched Ranks precon | Ghoulcaller Gisa (the commander), God-Eternal Bontu | Plays without its commander, so results mean nothing |
  | Gruul Ramp | Fiery Annihilation | 1 dead card; worth about 1 point against Izzet (tested with a fixed copy) |
  | Mono-White Angels | Devout Decree | 1 dead card |
  | Mono-Black Midrange (owned list) | God-Eternal Bontu | 1 dead card |
  | Finneas Rabbits (Commander) | Beast Within | 1 dead card |
  | Selesnya Rabbits | Beast Within, sideboard only | None: simulations never sideboard |

  Bolt Bend and Demonic Pact are flagged too, but they're only in the Starter Collection card list. In a test, the flagged cards were cast 0 times in 10 games while unflagged cards of the same cost were cast 14-28 times; Gisa was never cast in 52 deck-games.
- **Removing the flag isn't a fix.** A copy of a script without the flag, placed in Forge's user folder, makes the AI cast the card, but it then plays some of them badly: it lost a game to its own Demonic Pact and never used Gisa's sacrifice ability in 14 games.
- The other 31 flagged cards in our lists (`RemoveDeck:Random` and `RemoveDeck:NonCommander`) only affect Forge's random deck building, not play. No card of ours uses an ability type Forge's AI has no logic for.

### Other deck sizes and formats

| Test | Result |
|---|---|
| 40-card Beginner Box pairing (Cats+Vampires vs Goblins+Elves) | Works with no flag. 50 games: 34-16, 0.92 s per game (a 60-card pair took 0.68 s under the same conditions), 1.05 GB peak. In a separate 20-game run, the AI cast 24 of each deck's 27 different cards. |
| One 20-card half vs another (Cats vs Goblins) | Also works. 20 games: 13-7, 1.25 s per game; 1 game ended with a player unable to draw, on turn 28. |
| 60-card products (Bloomburrow Starter Kit decks, Challenger Lightning Aggro) | Load and play, with no unsupported cards. |
| 1v1 Commander (`-f Commander`, 2 decks) | Works: 40 life, the command zone, commander tax and 21 commander damage all checked in the logs. 40 games: about 2 s per game (median 1.6 s, longest 14.7 s), 1.0-1.1 GB. Replays exactly. |
| 4-player Commander (4 decks; the 5 Commander lists in two pods) | Works, but slowly. 23 games: median 38 s, mean 72 s, longest 3.6 minutes, 35-91 turns; 0.9 games a minute per process, so 100 games take about 2 hours of one process. 1.2-1.3 GB. |

About the 4-player pods:
- **They don't replay exactly.** Forge gives the AI 5 seconds per decision and skips the play if time runs out. That happened up to 5 times per pod run, depends on how busy the CPU is, and after it the seeded games went different ways. In 1v1 it happened only in huge-board games (0.3% of Rabbits vs Vampires games), and those still replayed exactly.
- **Seat 1 starts almost every game** after game 1 (the first seat that didn't win goes first), so rotate seats between batches.
- Forge doesn't check colour identity or that the commander is legendary; Deck Lab's own Commander checks cover that.

### Game logs and per-card stats

- **Saved game:** `logs/lg-full-n1-s7.log` in the trial folder is one complete game in Forge's own log (359 lines).
- **Forge's own log** (sim mode without `-q`, about 400 lines a game) shows every land played and spell cast with player and turn, the number of mulligans and the kept hand size, who went first, the winner and the number of turns. It **never shows which card was drawn, what the opening hand was, or what was left in hand at the end**, and no setting changes that.
- **The card log fills the gap.** `DeckLabSim` (394 lines of Java, compiled against the Forge jar with the JDK's `javac`) runs Forge's sim code with one event listener added, which logs every card move, the kept opening hands and the end-of-game hands.
  - The games are unchanged: logs were identical apart from the added lines (checked on 1, 20 and 50 games). Speed was the same within noise, and logs are 34% bigger.
  - `run_sim.py --card-log` runs it, and `parse_log.py` turns logs into per-card stats, with 0 consistency errors in 220 games.
  - It copies about 120 lines of Forge's sim code, so it has to be checked and rebuilt on every Forge upgrade.

| Stat | Forge's own log | With the card log |
|---|---|---|
| Win rate when drawn vs not drawn | Only roughly, as "when played": off by 6 points on average and up to 30, flattering expensive cards | Yes |
| How often cast once drawn | No | Yes |
| How often stuck in hand | No | Yes |
| Average turn cast | Yes (first cast each game) | Yes, per copy |

- **Sample size:** a 1-of is drawn in about a quarter of games, so after 220 games its drawn-vs-not win-rate difference is only good to about ±15 points, and a 5-point effect needs thousands of games. "Cast once drawn" and "stuck in hand" are useful after a few hundred. For example, Gruul's seven 6- and 7-mana creatures were still in hand at the end in 42-75% of the games they were drawn (six of them in more than half).

### Win rates compared with the 2026-09-28 report

- **Method:** 16 × 200-game batches per matchup, a different seed per batch, and the deck order swapped in every other batch: 3,200 games per matchup (6,400 for Izzet vs Gruul owned), 22,400 in all. Main decks only.
- The report's simulators alternated who went first, so the Forge figure is the **play/draw-balanced win rate**: the average of the deck's win rate on the play and on the draw.
- The 95% range is how far the true figure could plausibly be from it by chance. "Agrees" means that range overlaps the report's.

| Matchup | Lists | Forge: first deck's win % (95% range) | Report (table and both simulators) | Agrees? |
|---|---|---|---|---|
| Angels vs Zombies | owned | 52.4 (50.7-54.1) | 50-54 | Yes |
| Angels vs Zombies | with buys | 52.8 (51.0-54.5) | 51-52 | Yes |
| Izzet vs Gruul | owned | 55.1 (53.9-56.3) | 49-53 | No |
| Izzet vs Gruul | with buys | 56.1 (54.4-57.8) | 49-53 | No |
| Rabbits vs Vampires | owned | 38.1 (36.4-39.8) | 50-52 | No, badly |
| Rabbits vs Vampires | with buys | 36.0 (34.3-37.7) | 51-52 | No, badly |

- **Angels vs Zombies agree,** even though Forge's Angels never cast Devout Decree.
- **Izzet vs Gruul: Forge has Izzet 3-5 points higher than the report.**
  - About 1 point is Fiery Annihilation: with a fixed copy of the card, Izzet's balanced win rate fell from 55.0% to 53.8% on the same seeds. That's a rough figure: the difference itself is uncertain by about 2.4 points either way.
  - The rest isn't one bug. It's the kind of gap two different AIs give, and the report says Izzet's result depends most on how well it's played.
  - Forge does show the report's main point: Gruul won 58.5% when its turn-1 or turn-2 mana creature survived, and 42% when it was killed.
  - **Best estimate: close, with a slight Izzet edge.**
- **Rabbits vs Vampires: Forge has Rabbits 12-15 points lower, and the report is more believable here.**
  - Forge's AI holds the team pumps. About half the drawn copies of Overrun and Rabbit Response were still in hand when the game ended, while Rabbits' other spells, apart from the 6-mana Byrke (52%), were used 75-98% of the time. Forge judges a team-wide pump one creature at a time, so it never sees the big attack the deck is built for.
  - It also attacked on fewer of Rabbits' turns (39%, against 49% for Vampires). Giving Rabbits Forge's more aggressive "Reckless" AI style gained 3.6 points.
  - The two things the report's simulator left out don't explain the gap: in Forge, Rabbits double-blocked more often than Vampires, and Vampires cast only 4% of their removal on Rabbits' turn.
  - **Best estimate: Rabbits 45-51%, a judgement rather than a measurement.** Forge's numbers aren't usable for decks built around mass pump spells.
- Deck order made no difference (0-1.4 points). The starting player won 48.5-54.8% of games.
