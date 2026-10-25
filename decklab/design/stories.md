# Deck Lab user stories

Part of the design set: [README](README.md) (method and index), [personas](personas.md), [journeys](journeys.md), stories (this file) and [gap analysis](gap-analysis.md). Written 2026-10-13; every story was rechecked against the code and rewritten in the format below on 2026-10-19.

## How to read this file

Each story says who needs something, what they want and why:

> As a *persona*, I want *something*, so that *a reason*.

Its acceptance criteria use Given / When / Then: the starting state, the action, and what must then be true. They describe the behaviour wanted now, including the private-by-default rules (AGENTS.md, "Spaces"). A story counts as built only when every criterion holds in the code.

Each story's first line gives:

- **Persona**: from [personas.md](personas.md). Matt, User1, the space members (User2, User3, User4), User5 (`user5`, the first real member, whose setup is the template for every member: [member-template.md](member-template.md)), Claude Code (the command-line operator), and two outside roles: the Commander table (strangers at the shop's pods) and the tournament grinder (an anti-persona, for things deliberately not wanted).
- **Priority** (MoSCoW): `must`, `should`, `could`, or `wont` (not wanted, kept as a recorded decision).
- **Size**: `S` (a day or so), `M` (a few days), `L` (a week or more), `XL` (too big for one story; should be split).
- **Status**:
  - `built`: every acceptance criterion is met in the code.
  - `partial`: some criteria are met; the Gap says which aren't.
  - `missing`: none of the criteria is met.
  - `not_wanted`: left out by decision (always priority `wont`).

Under the criteria, each story may have:

- **Decided (Matt, date):** a decision still in force that the criteria alone don't show, such as why a story isn't wanted.
- **Now:** at most three lines on the current state, with a date and a link to its [HISTORY.md](../HISTORY.md) entry. The history of how a story got there is in HISTORY.md and git, not here.
- **Evidence:** the files and the functions, routes or tests that meet the criteria, never line numbers.
- **Gap:** for a partial or missing story, what isn't met yet.
- **Review note:** an unresolved story-quality issue, in one line.

Story numbers have gaps: ids are kept stable and never reused, and stories merged or dropped leave their numbers unused (E2-S04 was folded into E2-S22 and E5-S13 into E6-S01 on 2026-10-19). Pokémon isn't part of Deck Lab and has no stories.

## Summary

| Epic | Stories | Built | Partial | Missing | Not wanted |
|---|---:|---:|---:|---:|---:|
| [E1: Find, plan and choose decks](#e1-find-plan-and-choose-decks) | 12 | 9 | 0 | 3 | 0 |
| [E2: Build and edit a deck](#e2-build-and-edit-a-deck) | 16 | 13 | 1 | 1 | 1 |
| [E3: Test a deck](#e3-test-a-deck) | 14 | 11 | 3 | 0 | 0 |
| [E4: Get ready, play and learn](#e4-get-ready-play-and-learn) | 20 | 14 | 1 | 4 | 1 |
| [E5: Decide what to buy](#e5-decide-what-to-buy) | 22 | 15 | 0 | 5 | 2 |
| [E6: Record orders and receive cards](#e6-record-orders-and-receive-cards) | 20 | 17 | 0 | 1 | 2 |
| [E7: Keep the collection accurate](#e7-keep-the-collection-accurate) | 23 | 13 | 4 | 6 | 0 |
| [E8: Sleeves, boxes and storage](#e8-sleeves-boxes-and-storage) | 16 | 10 | 1 | 3 | 2 |
| [E9: Commander nights](#e9-commander-nights) | 19 | 13 | 0 | 5 | 1 |
| [E10: Members, access and privacy](#e10-members-access-and-privacy) | 35 | 30 | 1 | 2 | 2 |
| [E11: Run and trust the system](#e11-run-and-trust-the-system) | 25 | 15 | 6 | 1 | 3 |
| **Total** | **220** | **160** | **17** | **29** | **14** |

Counted from the story headers on 2026-10-24.

---

## E1: Find, plan and choose decks

How Matt and User1 (and, more lightly, User2, User3, User4 and User5) find a deck in the library (#/library), choose its picture, open its deck page (#/deck) to see whether it can be built and how to play it, rename or retire it, and pick what to play tonight. Each viewer's library holds their own space's decks, plus any another space has made public. A plain "Deck Lab is off" message is enough while the PC is off (E11-S02); collector-value sorting and legality badges on casual decks aren't wanted.

Open: E1-S05, E1-S12, E1-S13.

**E1-S01** · User1 · must · M · built

As a themed-deck player, I want to see every deck as a recognisable picture with its colours, status and who plays it, so that I can find my deck by eye without reading a table.

- Given the library at #/library, when it loads, then each saved deck shows its cover card's art, colour pips, a status pill (Idea, Building, Built) and one facts line (who plays it, card count + sideboard, Commander bracket); product decks sit in their own folded Products part, without a pill.
- Given the viewer's own decks and another space's public decks, when the library shows All decks, then home decks come first, then each person's space with decks the viewer may see in a part that folds away, each split into casual and Commander.
- Given a tile, when it is tapped, then the deck page opens (on its Cards tab filtered to Missing when the Planned list misses cards).
- Given no decks match the filters, when the library draws, then it offers Show every deck or New deck.

Decided (Matt, 2026-10-13): User1 uses Deck Lab on her phone, so the library on a phone is one of her main surfaces.

Evidence:
- `decklab/web/library.js`: deckCover, deckPips, deckMeta, deckCard, personGroup, productsGroup
- `decklab/lib/api/deck_page.py`: decks_index
- `decklab/lib/api/library.py`: shelf_extras, deck_cover, deck_colors
- `decklab/tests/test_library_ui.py`: test_a_tile_is_one_link_with_art_pips_status_and_one_readiness_chip, test_a_persons_own_decks_have_no_extra_heading

**E1-S02** · User1 · must · S · built

As a themed-deck player, I want to narrow the library to my own decks, so that I don't have to scroll past Matt's decks to reach mine.

- Given User1 is the visitor, when "User1's decks" is chosen, then only home decks Played by wife and 'either' decks show.
- Given User2 is the visitor and another space has public decks, when "User2's decks" is chosen, then only his own space's decks show.
- Given either choice, when the address is bookmarked, then the same view opens again (all=1 for All decks).

Evidence:
- `decklab/web/library.js`: isMyDeck, libVisibleDecks, filtersHash
- `decklab/tests/test_library_ui.py`: test_a_member_with_only_their_own_decks_is_told_nothing_else_is_public

**E1-S03** · Matt · must · M · built

As a deck builder, I want to see at a glance which decks can be put together tonight and which are waiting on cards, so that we pick something we can actually play.

- Given a deck with every Planned list card here, when its tile shows, then it has no readiness chip and Ready first puts it ahead of decks waiting on cards.
- Given a deck missing cards, when its tile shows, then the chip says '8 to get' and, where true, '3 on the way' and 'Play-now list ready'.
- Given a built deck, when the list it was built from misses copies, then the chip says how many are to get for that list.
- Given availability that can't be confirmed, when the tile shows, then it says 'Availability needs checking' instead of a count.
- Given a viewer who may not see that space's inventory, when the library loads, then no chip or token line shows for that deck.

Evidence:
- `decklab/web/library.js`: deckReadiness, sortDecks, deckTokens
- `decklab/lib/api/deck_page.py`: decks_index, _index_counts, _index_tokens
- `decklab/tests/test_library_ui.py`: test_a_tile_is_one_link_with_art_pips_status_and_one_readiness_chip, test_the_token_line_names_each_token_once

**E1-S04** · Matt · should · S · built

As a deck builder, I want to filter the library by format, status and Planned list availability and to sort it, so that I can focus on, say, Commander decks still waiting on cards.

- Given the library, when Format, Status or availability (All cards here, Cards on the way, Cards to get, Availability needs checking) is chosen, then only matching decks show.
- Given a sort of Ready first, Recently changed or Name, when it is chosen, then the tiles reorder within each group.
- Given any filter or sort, when the page reloads or the address is shared, then the same filters apply.
- Given a phone, when filters are set, then they sit behind a 'Filter (n)' sheet with Clear filters.

Evidence:
- `decklab/web/library.js`: LIB_SORTS, LIB_READINESS, libraryFilters, filtersHash, libFilterSheet
- `decklab/tests/test_library_ui.py`: test_sorts_ready_first_recently_changed_and_name, test_the_phone_filter_sheet_counts_and_applies_filters

**E1-S05** · Matt · could · S · missing

As a deck builder, I want to find a deck by typing part of its name, or by colour or archetype, so that I can reach it quickly once the shelf holds many decks and spaces.

- Given the library, when part of a title is typed, then only decks whose title matches show, across every visible group.
- Given a colour choice (for example blue and black), when it is applied, then only decks with those colours show.
- Given an archetype typed or chosen, when it is applied, then only decks whose Archetype header matches show.
- Given a search, when the address is bookmarked, then the search is kept like the other filters.

Evidence:
- `decklab/web/library.js`: libraryFilters, libVisibleDecks (no title, colour or archetype test)

Gap: The library has no text search and no colour or archetype filter.

First slice: a title search box on the library (kept in the address like the other filters), then the colour and archetype filters. It may become the deck half of E11-S31.

**E1-S07** · User1 · should · M · built

As a themed-deck player, I want to choose which card's art pictures my deck in the library, including a particular printing, so that my themed decks look the way I like on the shelf.

- Given a deck I may change, when I open More > Change library picture… (or the library's More > Choose deck pictures), then I see Automatic plus the deck's cards as art tiles, with search and 'Different printing…'.
- Given a chosen card, when I save, then only the deck's `- **Cover card:**` line is written, as one revision, with Undo in a toast.
- Given Automatic, when I save, then the line is removed and the picture follows the commander or the most-copied non-land.
- Given a product or pairing, or a deck I may not change, when I look, then no picker is offered and the server refuses a save.

Evidence:
- `decklab/web/cover.js`: openCoverPicker, drawCoverPicker, saveCover
- `decklab/web/deck.js`: deckMoreItems; `decklab/web/library.js`: libCoverEditable
- `decklab/lib/api/cover.py`: save_cover, cover_cards
- `decklab/tests/test_cover.py`: test_set_cover_rewrites_only_its_line, test_who_may_choose_a_cover, test_one_revision_and_one_change_set
- `decklab/tests/test_library_ui.py`: test_the_picker_chooses_and_saves_with_undo

**E1-S11** · User1 · must · M · built

As a beginner, I want a short overview of what my deck is trying to do and how to play and mulligan it, so that I can play it well without reading the whole list.

- Given the Overview tab, when it opens, then it shows the verdict strip (average mana value, lands, colour sources, and for Commander the rules and bracket), the commander and key cards as large pictures, and How to play.
- Given Notes with a game plan, mulligan or sideboard guide, when How to play draws, then each is a folding topic whose card names open the card viewer.
- Given a list changed after the notes were written, when How to play draws, then a warning says the guide may be out of date.
- Given a deck without Notes, when the Overview opens, then it says 'No play guide yet' and how to add one.

Decided (Matt, 2026-10-13): Deck Lab shows the hand-written Notes; it doesn't write strategy or teach the general rules (E4-S07, not wanted).

Evidence:
- `decklab/web/deck.js`: overviewParts, keyCardsPart
- `decklab/web/stats.js`: statsVerdict
- `decklab/web/guide.js`: guideSection; `decklab/web/deck-tools.js`: guideCardText
- `decklab/lib/api/guide.py`: playing_guide
- `decklab/tests/test_guide.py`: test_stale_warning_and_product_empty_state

**E1-S12** · Matt · could · S · missing

As a deck builder, I want a short summary of how strong a deck is against our other decks, where I first look at the deck, so that I can choose a deck for a tougher opponent without opening the Matchups tab.

- Given a deck with field results, when its Overview opens, then one line gives its field rank ('3rd of 10, likely 2nd-5th') with games played and a link to Against the field.
- Given a deck Forge is known to pilot poorly, when that line shows, then the caveat shows beside it.
- Given no field results, when the Overview opens, then it says none have been played, without starting a run.

Evidence:
- `decklab/web/deck.js`: overviewParts (no strength line)
- `decklab/web/field.js`: fieldSection, fvHeadline (the rank, on the Matchups tab)

Gap: The Overview shows nothing about strength. The rank and range already exist on the Matchups tab and in #/matchups Rankings (E3-S10); the work is surfacing one line on the Overview.

**E1-S13** · Matt · could · L · missing

As a deck builder, I want to compare two decks side by side (curve, colours, lands, card types, cards they both want, and how they've done against each other), so that choosing between two decks, or between two versions of an idea, doesn't mean flicking between pages.

- Given two lists chosen from the library or a deck page, when the comparison opens, then their stats verdicts and curves show side by side.
- Given cards both lists use, when the comparison opens, then they are listed with how many copies the pool can cover for both.
- Given saved Forge results or recorded games between them, when the comparison opens, then the latest result and the Head to head count are linked.

Evidence:
- `decklab/web/core.js`: ROUTES (no compare route)

Gap: There's no compare view. The pieces are separate: each deck's Stats, #/matchups, Head to head in #/play, the Packing plan, and History's revision compare.

Review note: L with three separate outcomes; could split into stats, shared cards and head to head.

**E1-S18** · User1 · could · S · built

As a themed-deck player, I want to look at the decks inside our sealed products and start my own deck from one, so that I can try a precon idea without breaking the product.

- Given the library's folded Products part, when it is opened, then each product's decks show, read only and grouped by product, and its open state is remembered on this device.
- Given a product deck's page, when Save as a new deck is used, then its list is copied into a new editable casual or Commander deck and the product stays as it is.
- Given Try a Beginner Box pairing, when two halves are picked, then the 40-card pairing opens read only.

Evidence:
- `decklab/web/library.js`: productsGroup, LIB_PRODUCTS_KEY, pairingPicker
- `decklab/web/editor-deckpage.js`: deckActions
- `decklab/tests/test_library_ui.py`: test_products_fold_and_remember_and_their_caption_fits_the_viewer

**E1-S19** · Matt · should · L · built

As a deck builder, I want to rename a deck and to retire one I no longer want, from the deck page, so that the library stays tidy as ideas change, without losing a deck's history or matchups.

- Given a deck I may change (not a product or pairing), when I rename it from More > Rename deck…, then after a reviewed preview and confirmation its title and id change within its space and format, and its revisions and matchup results come with it; the old address still opens the deck.
- Given a deck that isn't built, when I retire it from More > Retire deck… with a reason, then it leaves the library, its history stays readable and it can be restored from History.
- Given a built deck, when I look, then Retire isn't offered; the server refuses a built deck (take it apart first) or one still holding sleeves or a deck box (clear them first), and `deck delete` refuses a built deck holding kit.

Now: Retire built 2026-10-15 ([HISTORY.md, Retire and restore deck ideas](../HISTORY.md#retire-and-restore-deck-ideas-2026-10-15)); rename built 2026-10-16 ([HISTORY.md, Rename decks with retained history and links](../HISTORY.md#rename-decks-with-retained-history-and-links-2026-10-16)).

Evidence:
- `decklab/web/deck-rename.js`: canRenameDeck, openRenameDeck; `decklab/lib/api/rename.py`: preview_rename, rename_deck
- `decklab/web/deck-retirement.js`: canRetireDeck, openRetireDeck, openRestoreDeck
- `decklab/lib/api/retirement.py`: _physical, retire_deck, restore_deck
- `decklab/tests/test_deck_retirement_ui.py`: test_menu_is_only_for_editable_unbuilt_saved_decks
- `decklab/tests/test_deck_rename_ui.py`: test_menu_accepts_built_and_personal_editable_decks_but_not_products

**E1-S23** · User1 · must · M · built

As a beginner looking at cards on her phone, I want to open any card full-size over the list it's in, read its rules text, flip a double-faced card and swipe to the next one, so that I understand what a card does without leaving the deck or looking it up elsewhere.

- Given a card name or picture in a deck list, the Tokens page, Receive delivery or Activity, when it is tapped, then the card viewer opens on that card over the list, showing 'n / total'.
- Given the viewer on a phone, when User1 swipes left or right, then it moves to the next or previous card of that list without waiting for the picture.
- Given a double-faced card, when Flip is tapped, then its back's picture shows, and the Text button (or the side panel from 1,000 px) shows its rules text.
- Given the viewer is open, when the phone's Back button or Escape is used, then it closes and focus returns to what opened it.

Decided (Matt, 2026-10-13): User1 uses Deck Lab on her phone, so the phone's card viewer is one of her main surfaces.

Now: Swipes pass on the iPhone 15 Pro and in the Simulator suite (2026-10-15, [HISTORY.md, Card viewer: portrait size and swipe guidance](../HISTORY.md#card-viewer-portrait-size-and-swipe-guidance-2026-10-15)); the iPhone 17 Pro and iPad checks are in E2-S22.

Evidence:
- `decklab/web/card-viewer.js`: openCardViewer, stepViewer, flipViewer, toggleViewerText, viewerPointerUp, pushViewerEntry
- `decklab/tests/test_card_inspector.py`: test_viewer_faces_reading_errors_dismissal_focus_groups_and_swipes

---

## E2: Build and edit a deck

Covers making a deck and keeping it right: New deck and Start from, the full editor (from 600px) and the phone's Quick edit, Paste a list, the Planned and Play-now lists, owned vs needed against the space's pool and its other built decks, keeping the write-up current, history and undo, and the command-line route Claude Code uses (`deck pull`/`push`/`new`/`tables`). Drafts stay on the device they were started on, and the Play-now list's substitutes are hand-written (Packing's physical stand-ins, E4-S21, never change a list). Rename and retirement, with restore from History, are on the deck page (E1-S19). Legality badges on casual decks are deliberately not wanted.

Open: E2-S16, E2-S22.

**E2-S01** · Matt · must · L · built

As a deck builder, I want to start a new deck from a list I already have (a paste, a precon, another deck, a product or an old revision), so that I don't type a whole list by hand, and I start from cards we own.

- Given I may make a deck in my space, when I open #/new, then I can give a title and format (and, at home, who plays it: a member only herself) and choose Start from: a pasted list, a precon (only when I may see the space's inventory) or another deck.
- Given a product, Beginner Box pairing or History revision, when I choose Save as a new deck or Open as a draft, then the editor opens with that list and the original stays as it is.
- Given a new deck, when it is made, then it starts as idea, and a Commander deck with Target bracket 2.
- Given Claude at the PC, when it runs `deck new KIND SLUG --from FILE -m` and then `deck tables ID --reprice --apply`, then the deck exists with a filled, priced owned-vs-needed table.

Evidence:
- `decklab/web/editor-cards.js`: startFromPart, openPreconStart, openDeckStart
- `decklab/web/editor-deckpage.js`: deckActions (Save as a new deck)
- `decklab/web/editor.js`: newDeckSpace, newDeckPlayer, allowedPlayers
- `decklab/lib/api/drafts.py`: _new_fields; `decklab/db/inv_decks.py`: _new, _tables
- `decklab/tests/test_deck_saving_db.py`: test_a_new_deck_and_a_taken_name

**E2-S02** · Matt · must · L · built

As a deck builder, I want to find and add cards quickly, seeing which copies are free in the pool, so that I build from what we own first and buy only to fill gaps.

- Given the full editor, when I type a name and press Enter, then 1 copy is added ('Added ✓ (now n)'), Shift adds 4, and '4 bolt' adds 4.
- Given the Add finder, when I tick Free copies only or filter by colour, type or mana value, then only matching cards show, each with copies owned and an A$ estimate.
- Given My collection, when it opens, then it lists cards free for this deck in its colours, with 'Did you mean' for misspellings.
- Given a line, when I open its printing sheet, then I can pick a printing (copies owned shown), move it to another section, or remove it.

Evidence:
- `decklab/web/editor-cards.js`: parseQuery, addCard, drawSearchControls, ownedBadge, openPrintings
- `decklab/lib/api/editor.py`: find_cards (GET /api/deck/find)

**E2-S03** · Matt · should · M · built

As a deck builder, I want to bring in a list from somewhere else and see what it changes before I accept it, so that a list from Claude, a website or a precon replaces or adds to mine without surprises.

- Given Paste a list…, when I paste an Arena/MTGO list, then I choose Add or Replace and see what changes before applying it.
- Given the pasted list has unknown names, when the preview shows, then they are listed first with suggestions, and nothing unknown is applied.
- Given I apply the paste, when I look at the editor, then the change can be undone like any other edit.

Evidence:
- `decklab/web/editor-cards.js`: openPaste, mergeLines, replaceLines, afterBulkChange
- `decklab/lib/api/editor.py`: parse_list (POST /api/decklist/parse)
- `decklab/tests/test_editor_ui.py`: test_paste_adds_or_replaces_and_shows_the_difference

**E2-S05** · User1 · should · L · built

As a themed-deck player on my phone, I want to change my deck's cards, notes, header details and whole list from the phone, so that I can finish any edit on the device I started it on.

- Given a phone under 600px (or on its side), when I tap Edit on a deck I may edit, then the Quick edit opens with compact rows and steppers, and Add cards opens a search sheet that stays open for the next card.
- Given the Quick edit, when I open my deck, then I can edit its Notes and Substitutes and press Mark write-up as current.
- Given the Quick edit, when I open its details, then I can set Archetype and Built version, and for a built home deck its Sleeves and Deck box, as on the tablet.
- Given the Quick edit, when I choose Paste a list, then I get the same Add or Replace preview as the full editor.
- Given I press Save, when the save succeeds, then a toast confirms it and the change shows in History under my name.

Decided (Matt, 2026-10-13): User1 uses Deck Lab on her phone, so what the Quick edit can't do she can't do at all; raised from could to should.

Now: Built 2026-10-15 ([HISTORY.md, Complete the phone's Quick edit](../HISTORY.md#complete-the-phones-quick-edit-2026-10-15)). Physical-device checks are in E2-S22.

Evidence:
- `decklab/web/editor.js`: canBuildDecks, quickEditing
- `decklab/web/editor-screen.js`: mainTabs, notesPart; `decklab/web/editor-details.js`: detailsPart, drawDetails; `decklab/web/editor-lines.js`: stepper
- `decklab/web/editor-cards.js`: addPart, openAddSheet, openPaste
- `decklab/tests/test_quick_editor_ui.py`: test_details_edit_the_same_fields_and_preserve_member_choices, test_add_sheet_opens_one_paste_sheet_and_add_preview_preserves_other_work
- `decklab/tests/test_workspace_ui.py`: test_phones_get_the_quick_edit_for_saved_and_new_decks

**E2-S06** · Matt · must · M · built

As a deck builder, I want to keep the deck I'm aiming for apart from the deck I can put together today, so that we can play now with stand-ins while the planned version waits for cards.

- Given a deck page, when I use the Planned / Play-now switch (with its 'i' explanation), then the list, marks and banner follow that list (&v=target|owned).
- Given a deck with no Play-now list, when I edit with v=owned, then Start it begins one as a copy of the Planned list, and saving it adds the '### Substitute version (owned and incoming cards)' list.
- Given a built deck with both lists, when I set Built version, then the pool counts that list as the one in use.
- Given Copy decklist or Print play sheet, when I use it, then it uses the list shown.

Evidence:
- `decklab/web/deck-availability.js`: versionPicker, availabilityBanner
- `decklab/web/editor-lines.js`: startOwned
- `decklab/lib/pool.py`: _built_version
- `decklab/web/deck-tools.js`: copyDeck, printDeck
- `decklab/tests/test_accessories.py`: test_built_decks_hold_their_built_version

**E2-S07** · Matt · should · L · built

As a deck builder, I want to know which owned cards could stand in for each missing card, and what each swap costs the deck, so that we can play a strong-enough version tonight and buy only what matters most.

- Given a card missing from the Planned list, when I look at it, then I see free owned cards of the same card type, sharing a colour, with mana value within 1.
- Given a suggested stand-in, when I pick it, then it goes into the Play-now list in place of the missing card.
- Given a swap in the Play-now list, when I look at it, then a note says what it costs the deck in strength, and I can edit that note in Substitutes.

Evidence:
- `decklab/lib/api/drafts.py`: PROSE_SECTIONS, with_prose (Substitutes prose)
- `decklab/web/editor-cards.js`: drawSearchControls (My collection: free cards in the deck's colours, not tied to a missing card)
- `decklab/web/editor-lines.js`: startOwned (the Play-now list starts as a copy)
- `decklab/lib/decks/swaps.py`: primary_type, colours_of, castable, fits, basics_for, rank_key, swap_note, names_card, derive_swaps, _share
- `decklab/lib/api/swaps.py`: suggest_swaps (GET /api/deck/swaps), suggest_draft_swaps (POST), view_swaps (deck_view's "swaps")
- `decklab/web/editor-swaps.js`: swapsAvailableFor, openSwapSheet, applySwap, withSwapNote, swapColumns, noteNaming; `decklab/web/deck-swaps.js`: deckSwapFinder, deckSwapsSection
- `decklab/tests/test_swaps_core.py`, `test_swaps_api.py`, `test_editor_swaps_ui.py`, `test_deck_swaps_ui.py`

Decided (Matt, 2026-10-19): a stand-in "plays a similar role" when it has the same card type, shares a colour and is within 1 of the missing card's mana value.

Now: Built 2026-10-20 (HISTORY.md, "Stand-ins for missing cards"). A short Play-now line's ⋯ Stand-ins… (and the deck page's Missing filter, via #/edit?…&swap=, offered only while the Play-now list is short of the card too) lists free owned cards of the same primary type, sharing a colour, mana value within 1 and castable in the deck (a land by the mana it makes and its identity; a casual deck's land makes only the deck's colours, or every colour); Use n swaps them in and adds a strength note to Substitutes once (a table row under its headings, else a bullet), which Deck Lab never rewrites; the Play-now list's swaps show with their notes to every viewer of the deck, each stand-in's copies shared out among the swaps naming it. Suggestions only for viewers who may see the space's inventory. Distinct from Packing's physical stand-ins (E4-S21).

**E2-S08** · Matt · must · L · built

As a deck builder, I want to see for each card whether it is in storage, held by another built deck or an intact product, on the way, or still to get, so that I know whether moving sleeves, waiting or buying will finish the deck.

- Given I may see the deck's space's inventory, when I open a deck, then the banner says Ready to build, Ready once N cards arrive, or N missing (about A$X) and N held by other decks.
- Given the Cards tab, when I filter by Missing, On the way or In other decks, then each card is marked ('1 of 2 missing', '1 on the way', '1 in <deck>').
- Given copies held elsewhere, when I open the price table, then 'Cards other decks are holding' says 'N short' or 'Enough left.'.
- Given a viewer who may see the deck but not its space's inventory, when they open it, then they see the list without owned, missing or on-the-way counts.
- Given Claude, when it runs `python -m decklab.lib.pool ID [--owned]`, then the same owned, on-the-way and in-use counts print.

Evidence:
- `decklab/web/deck-availability.js`: deckAvailability, availabilityBanner
- `decklab/web/deck.js`: CARD_FILTERS, markChips
- `decklab/web/deck-prices.js`: conflictsBox
- `decklab/lib/permissions.py`: sees_inventory
- `decklab/lib/pool.py`

**E2-S10** · User1 · must · M · built

As a beginner building a deck, I want to be told when my deck breaks a deck-building rule without being stopped from saving it, so that I can save a deck that's half done and still learn what it needs.

- Given a change, when I pause briefly, then the draft is checked and warnings show: under 60 cards, more than 4 copies, and for Commander 100 cards, singleton, colour identity, banned and eligibility.
- Given only warnings, when I press Save, then the save goes through.
- Given an unknown name, gold-bordered printing or bad quantity, when I press Save, then the save is blocked and the review sheet says why.
- Given a casual 60-card deck, when it is checked, then no ban list or format legality is applied.

Evidence:
- `decklab/web/editor-save.js`: CHECK_DELAY, scheduleCheck, blocksBox
- `decklab/lib/stats/__init__.py`: deck_rules
- `decklab/lib/api/drafts.py`: _rule_warnings
- `decklab/lib/api/card_lookup.py`: _pickable

**E2-S13** · User1 · should · M · built

As a beginner who learns a deck from its notes, I want the deck's write-up and How to play guide to match the current list, so that I don't follow a plan for cards that aren't in the deck any more.

- Given a save that changed a list, when it is saved, then the text gets 'Decklist changed in Deck Lab on <date>' and the Overview's How to play warns the guide may be out of date.
- Given the Notes tab, when I update the notes and press Mark write-up as current, then the line is removed on Save.
- Given Claude, when `deck list` shows a Decklist changed date, then it can pull the deck, update the prose, remove the line and push with `--expect`.
- Given hand-written prose, when Deck Lab saves the deck, then that prose is kept byte for byte.

Evidence:
- `decklab/lib/decks/edit.py`: mark_decklist_changed, apply_edit
- `decklab/web/guide.js`: guideSection
- `decklab/web/editor-screen.js`: notesPart
- `decklab/tests/test_editor_writeup.py`: test_mark_write_up_as_current

**E2-S14** · Matt · must · M · built

As a deck builder, I want to take back a mistake and go back to an earlier version of a list, so that I can try ideas freely.

- Given the editor, when I press '−' on a single copy or Remove, then the row reads 'Removed … Undo' in place, and Ctrl/Cmd+Z undoes any change.
- Given #/history?id=, when it opens, then revisions show newest first with who, when, message and the cards changed, and runs of saves that changed neither cards nor header are folded.
- Given a revision and the right to save the deck, when I choose Open … as a draft, then the editor opens that list and saving makes a new revision.
- Given Claude, when it runs `deck history ID` or `deck revision ID N`, then the same revisions print, a deleted deck's included.

Evidence:
- `decklab/web/editor-lines.js`: removedRow, undoRemove; `decklab/web/editor.js`: undoLast
- `decklab/web/history.js`: historyDraw, historyFolded, showRevisionEditor
- `decklab/lib/api/history.py`: deck_history, deck_revision
- `decklab/db/inv_decks.py`: _history, _revision
- `decklab/tests/test_editor_ui.py`: test_ctrl_z_takes_back_each_change

**E2-S15** · User1 · must · M · built

As one of two people (plus Claude) editing the household's decks, I want my unsaved changes kept and never overwritten by someone else's save, so that no work is lost when two of us edit the same deck.

- Given unsaved changes, when I leave and come back on the same device, then the draft is kept per person, deck and list.
- Given storage is blocked, when I try to leave, then the editor warns and asks me to save or discard.
- Given someone saved the deck after I opened it, when I save, then it is refused (409) naming who and when, with 'Load the latest and re-apply my changes'.
- Given Claude, when `deck push --expect N` names an old revision, then nothing is written.

Evidence:
- `decklab/web/editor.js`: draftKey, saveDraft, confirmLeave
- `decklab/web/editor-save.js`: showConflict, reapplyLatest
- `decklab/lib/api/commits.py`: _conflict
- `decklab/db/inv_decks.py`: expected
- `decklab/tests/test_deck_saving_db.py`: test_the_409_names_who_saved_it_from_the_revisions

**E2-S16** · Matt · could · L · missing

As a multi-device deck builder, I want to pick up an unsaved edit on another device, so that I can start on the iPad and finish at the PC.

- Given an unsaved draft on one device, when I open the same deck and list on another device as the same profile, then I am offered that draft.
- Given a draft on two devices, when I open one, then I am told which is newer and can choose.
- Given a draft is saved or discarded, when I look on the other device, then it is gone there too.

Evidence:
- `decklab/web/editor.js`: draftKey, saveDraft, readDraft (drafts only in the browser's storage)

Gap: There's no server-side draft store and no drafts API; nothing is shared between devices.

**E2-S19** · User1 · could · S · built

As a home player looking at a deck Played by the other person, I want to try a change without saving it, so that I can suggest an improvement or see how it would play.

- Given a deck I may see but not edit and a screen 600px or wider, when I tap Try a change, then the editor opens without Save.
- Given changes in Try a change, when the checks run, then I see the same warnings, and owned counts show only if I may see the deck's space's inventory.
- Given a phone under 600px, when I view such a deck, then Try a change isn't offered, since testing a change against other decks needs the full editor.

Evidence:
- `decklab/web/editor-deckpage.js`: deckActions
- `decklab/lib/api/editor.py`: check_draft
- `decklab/tests/test_accounts_ui.py`: test_deck_page_offers_edit_only_on_decks_the_visitor_may_change
- `decklab/tests/test_api_permissions.py`: test_a_drafts_counts_come_only_from_a_pool_it_sees

**E2-S20** · Matt · should · M · built

As a deck builder finishing a deck, I want to set a deck's status, player, archetype, built version, sleeves and deck box while editing, so that the deck's header matches the physical deck.

- Given Deck details, when I set Status, Played by (home only), Archetype and Target bracket, then they are saved in the header lines.
- Given a built home deck, when I open the Sleeves or Deck box picker, then tiles show only accessories its player may use (their own and shared), with '75 needed · 100 owned · 25 spare', and a design other holders also use says "Also used by X" and can still be chosen.
- Given I move a deck from Built back to Building, when I save, then Built version, Sleeves and Deck box are removed.
- Given a person's deck, when it is saved with Played by, Sleeves or Deck box, then the save is refused.

Decided (Matt, 2026-10-13): one sleeve design may sleeve several decks; it's up to the players not to play two of them at once.

Evidence:
- `decklab/web/editor-details.js`: detailsPart, sleevesField, deckBoxField, kitTile
- `decklab/web/editor.js`: kitTaken
- `decklab/web/accessories.js`: accTakenWords, pickKit, kitChip
- `decklab/lib/api/drafts.py`: _read_draft (clears Built version and kit on Building; refuses a person's deck's Played by, Sleeves, Deck box)
- `decklab/tests/test_editor_contracts.py`: test_a_design_or_colour_another_holder_has_is_no_warning

**E2-S21** · Tournament grinder · wont · S · not_wanted

As a tournament grinder, I want legality and ban warnings on casual 60-card decks, so that decks stay tournament-legal.

- Given a casual 60-card deck, when it is checked, then no legality or ban badge or warning appears; only Commander decks get the ban list, colour identity and bracket checks.

Decided (Matt, 2026-09-26): casual decks ignore ban lists and format legality; any card ever printed is fine.

Evidence:
- `AGENTS.md`: How Magic gets played
- `decklab/lib/stats/__init__.py`: deck_rules

<a id="e2-s22"></a>

**E2-S22** · User1 · must · M · partial

As a themed-deck player who uses Deck Lab mostly on a phone (and Matt on a tablet), I want the pages, especially saving an edit, the Quick edit's keyboard and menus, swiping in the card viewer and Receive delivery, safe areas and Add to Home Screen, checked and passing on the real iPhone 15 Pro, iPhone 17 Pro and M2 11-inch iPad test devices, so that I can trust a save made on my phone and use Deck Lab like an app.

- Given Deck Lab added to the Home Screen on an iPhone 15 Pro and an iPhone 17 Pro, when it is opened, then it runs standalone with the top bar and tab bar clear of the notch, Dynamic Island and home indicator.
- Given a deck open in the Quick edit on a real iPhone, when a card count is changed and saved with the on-screen keyboard open, then the save button stays reachable, the save succeeds, and the change shows in the deck's History.
- Given the Quick edit on a real iPhone, when I open Add cards with the keyboard up, then its search sheet stays above the keyboard; and when I use a line's ⋯ menu, then I can change the printing, move it to another section or remove it.
- Given the card viewer or Receive delivery on a real phone or the M2 11-inch iPad, when the user swipes left and right, then it moves one card at a time without scrolling the page behind it or going back in the browser.
- Given a Commander deck's Overview on a real iPhone, when it opens, then the bracket sentence (E9-S05) shows without scrolling.
- Given the device pass is done, when its results are recorded, then each failed check is fixed or entered as a known issue.

Decided (Matt, 2026-10-13): User1 uses Deck Lab on her phone, which makes this check matter more.

Now: Passed on the iPhone 15 Pro and M2 iPad in portrait and landscape, plus the 15 Pro's quantity field, keyboard-open Save, History, viewer swipes and the Safari Share fix (2026-10-15, [HISTORY.md, Real-device acceptance: first checks](../HISTORY.md#real-device-acceptance-first-checks-2026-10-15)). The [Safari Simulator suite](../safari/EVIDENCE.md) passes all six device and orientation configurations; use it for repeat regressions.

Evidence:
- `decklab/safari/EVIDENCE.md`
- `decklab/PLAN.md`: Still to do 10, "Phones and the iPad themselves"

Gap: Still to check on the real devices: the receipt panel's navigation and Close before the image and its swipe margins, the Quick edit's Add cards sheet with the keyboard and its ⋯ menu, keyboard-open Save and Home Screen use on the iPad, the Commander bracket sentence's place on the phone (E9-S05), and everything on the iPhone 17 Pro.

---

## E3: Test a deck

How a player finds out whether a deck works before playing or buying cards: instant stats on the deck page's Stats tab, practice games on the Practice tab, Forge matchups and Rankings (#/matchups, #/matchup), the field rank on the Matchups tab, paired tests of a change from the editor (#/variant), and the simulations setting on #/settings. Matchups, fields, rankings and tests follow deck privacy: each viewer sees only results whose every side they may see, a member's field is their own space plus Public spaces, and a run may be stopped by whoever started it, anyone whose space's deck it uses, or an admin. Not yet covered: 4-player Commander pods, sideboard testing, comparing real games with Forge's predictions, and members asking for a run while only admins may start one. Forge results are files outside the database's backups by decision, since they can be replayed.

Open: E3-S13, E3-S19, E3-S23.

**E3-S01** · Matt · must · M · built

As a newer player building from the shared pool, I want to know whether a deck's land count, colour sources and curve are sound without doing the maths, so that I fix mana problems before playing or buying.

- Given a deck, when I open its Stats tab, then a verdict strip says in plain words whether the land count is low, slightly low, ok or high against Karsten's formula.
- Given a two-colour deck, when I read the colour sources, then colours stay in WUBRG order and each colour's hardest requirement is shown first with its verdict.
- Given the land-count formula, land-count rule of thumb, colour-source requirements or Commander bracket panel, when I open its source disclosure, then each cited source names its title and recorded date; an unknown date is labelled as unknown, never invented.
- Given the command line, when Claude runs `python -m decklab.lib.stats <deck-id> --json`, then it gets the same numbers.

Now: Built 2026-10-18 ([HISTORY.md, Dated Stats disclosures and guarded CLI receipts](../HISTORY.md#dated-stats-disclosures-and-guarded-cli-receipts-2026-10-18)).

Evidence:
- `decklab/web/stats.js`: statsVerdict, statsSourceCitation, sourcesPanel
- `decklab/lib/stats/colourcheck.py`: _hardest_first, _colour_check
- `decklab/lib/stats/__init__.py`: main (`--json`)
- `decklab/tests/test_stats_sources_ui.py`: test_unknown_dates_are_explicit_in_every_disclosure_and_the_source_list

**E3-S04** · Matt · should · M · built

As a deck builder, I want to know how often a deck mulligans, misses land drops or lacks a colour over many games, so that I can compare mana bases without playing hundreds of hands myself.

- Given a deck, when the Practice tab opens, then practice games report mulligan rate, land drops on time, screw and flood, colours by turn and first 4-drop, on the play and on the draw.
- Given a Commander deck, when the results show, then a multiplayer setup is included.
- Given the simulations setting is Paused, when I open the Practice tab, then practice games still run.
- Given a rule the simulated player follows, when I open its disclosure, then its source is named.

Evidence:
- `decklab/web/practice.js`: mulliganPanel, landDropPanel, stuckPanel, practiceColourPanel, firstBigPanel, practiceAbout
- `decklab/lib/api/practice.py`: goldfish (GET /api/goldfish, not gated by the simulations setting)
- `decklab/lib/goldfish/__init__.py`
- `decklab/tests/test_goldfish.py`: test_commander_free_mulligan_only_in_multiplayer, test_constructed_play_and_draw

**E3-S05** · Matt · must · L · built

As a player who plays 1v1 at home, I want to know which of two decks is stronger, without playing hundreds of games myself, so that I know what to improve before sitting down to play.

- Given two lists of the same format that I may see, when I start a run with Precise, Settle it, Quick look or a set number of games, then Forge plays them and saves the result.
- Given a run choice, when I pick it, then one rough time is shown and my choice follows me to other devices.
- Given four matchups are already playing, when I start another, then it queues.
- Given #/matchups, when I look at the matrix, then each cell shows the latest win rate, with older-list results faded.

Evidence:
- `decklab/web/matchups.js`: runModeChoice, gamesChoice, roughTimeWords, saveGames, saveMode
- `decklab/lib/api/forge_runs.py`: MATCHUPS_AT_ONCE (4, max_queued 10)
- `decklab/web/matchups-overview.js`: matrixDecks, matchupMatrix, pairsOf
- `decklab/lib/api/settings.py`: matchup_mode and matchup_games profile settings
- `python -m decklab.lib.forge play`

Review note: size L bundling run modes, synced choice, queueing and the matrix; could be split.

**E3-S06** · Matt · should · M · built

As a user on any device, I want to see from any page that Forge is playing and how far along it is, and to stop a run, so that I can carry on with other things and stop a run that isn't needed.

- Given a run I may see waits or plays, when I'm on any page, then the top bar shows the run activity icon, and its details show each run's progress, the runs waiting and Stop.
- Given a run is playing, when I open it, then I see progress, the score so far and a live range, with no verdict until the end.
- Given I started a run, or it uses a deck of my space, or I'm an admin, when I press Stop, then the run stops and every finished game is kept; anyone else isn't offered Stop.
- Given the server stops, when it starts again, then checkpointed games are kept and labelled Recovered.

Now: Stop follows deck privacy since 2026-10-18 ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)); since 2026-10-25 the floating pill is an activity icon whose details hold progress and Stop (E11-S30 slice 6, Matt's section 6 decision 3; [HISTORY.md, P1 simulation components](../HISTORY.md#p1-simulation-components-2026-10-25-e11-s30-slice-6)).

Evidence:
- `decklab/web/runs-pill.js`: drawRunsPill, runDetailsParts, openRunDetails, runEntry
- `decklab/web/matchups-detail.js`: liveBox, stopRun
- `decklab/lib/api/forge_runs.py`: _live_range, _job_json, _coord_progress (may_stop from seen.can_stop)
- `decklab/lib/forge/checkpoints.py`: INTERRUPTED
- `decklab/tests/test_matchups_api.py`: test_stopping_a_run_keeps_the_games_it_finished

**E3-S07** · Matt · must · M · built

As a newer player without statistics training, I want a result in plain words, with how far I can trust it, so that I don't misread chance or Forge's mistakes as a real difference.

- Given a finished matchup, when I open it, then it leads with a sentence such as 'wins about 9 in 10' and a bar, with at most one caveat line.
- Given a deck Forge pilots poorly, when I read 'How far to trust these numbers', then a box names the flagged cards.
- Given a Commander result, when I read it, then it says Commander results are indicative only.
- Given results from an older list or an earlier engine, when shown, then they are marked and never pooled with new games.

Decided (Matt, 2026-10-13): this story is Matt's, not User1's; he doesn't think she reads Matchups or Stats.

Evidence:
- `decklab/web/matchups-results.js`: resultPart, caveatLine, trustPart, pilotFlag, COMMANDER_WORDS
- `decklab/web/matchups.js`: plainVerdict, favouriteWords, earlierEngine
- `decklab/web/matchups-detail.js`: earlierBox
- `decklab/tests/test_matchup_verdict.py`: test_the_page_and_the_command_line_say_the_same

**E3-S09** · Matt · must · L · built

As a deck builder, I want to see how a deck does against the decks of its space as a whole and where it ranks, so that I know which deck needs work most.

- Given a deck, when I open Against the field on its Matchups tab, then it shows the win rate against an average deck of its field and a rank with its likely range.
- Given matchups that differ from what the rating predicts, when shown, then they are listed as strong or weak.
- Given I press Play the field with a budget, when it runs, then it adds games where they narrow the answer most and the budget is saved per profile.
- Given a deck of a person's space, when measured on the page, then its field is that space's decks plus Public spaces' decks, and it never joins home's field; the command line's `forge field` keeps home's field.

Now: A member's deck is measured against its own and Public spaces' decks since 2026-10-18 ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)).

Evidence:
- `decklab/web/field.js`: fvHeadline, fvRows, fvPlayBox, fvSaveBudget
- `decklab/lib/api/field_page.py`: _field_options, _field_budget, _answer
- `decklab/lib/forge/field.py`: _field, plan, _alloc_left
- `decklab/tests/test_field_privacy.py`: test_members_field_has_own_and_public_spaces_but_home_field_does_not_auto_add_them, test_cli_default_is_still_homes_field_even_for_a_members_entry
- `decklab/tests/test_field_api.py`: test_the_budget_follows_the_profile

**E3-S10** · Matt · should · M · built

As a deck builder, I want one ranking of every deck of a format, best first, with their ranges, so that I can compare all decks at a glance instead of opening each one.

- Given saved results, when I open Rankings on #/matchups, then every current list of a format that I may see is listed by rating with its likely rank range, from results whose every side I may see.
- Given a list with too few games, when listed, then it is marked unsettled.
- Given a deck left out of the field, when listed, then it says why.
- Given lists with no games connecting them, when ranked, then each connected group is ranked on its own.

Now: Filtered by privacy since 2026-10-18 ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)).

Evidence:
- `decklab/web/matchups-overview.js`: muRefreshRankings, muDrawRankings, muRankingRow
- `decklab/lib/api/rankings.py`: rankings_view (`GET /api/rankings`)
- `decklab/lib/forge/rankings.py`: view, _excluded, _seen_result
- `decklab/tests/test_matchup_rankings_ui.py`: test_every_current_list_remains_visible_with_uncertainty_reasons_and_notes, test_disconnected_groups_sort_only_within_each_group

**E3-S11** · Matt · must · L · built

As a buyer who wants the most improvement per dollar, I want to find out whether swapping a card makes a deck better before I buy or move it, so that I don't spend money or sleeves on changes that do nothing.

- Given a changed main deck of the same size in the editor of a deck of my space, when I tap Test this change, then I can test against the field or one deck, until it's clear or as a Quick look, with a time estimate.
- Given the test runs, when it finishes, then it says Better, Worse, Makes little difference or Not settled yet, with each opponent's difference.
- Given a sideboard-only or size change, when I try to test it, then it is refused with the reason.
- Given a verdict, when I press Save this change, then the editor opens with the tested list, and testing never saves on its own.

Evidence:
- `decklab/web/variant.js`: vtTestState, vtOpenTestSheet, vtVerdictPanel, vtSaveChange, VT_SIDEBOARD, VT_SIZE
- `decklab/lib/forge/variants.py`: SIZE_CHANGED, SIDEBOARD_ONLY, run_test
- `decklab/lib/api/variant_page.py` (starting a test requires the base deck's own space)
- `python -m decklab.lib.forge variant`

**E3-S13** · User1 · could · M · partial

As a member who plays her own decks, I want to start a matchup for my deck, or ask for one, from my phone, so that I can see how my deck does without waiting for Matt to be at the PC.

- Given the simulations setting is Anyone, when I press Play, then my run starts.
- Given the setting is Only admins, when I look at Play, then the reason shows beside it ('Only an admin can start simulations right now.'), naming nobody.
- Given the setting is Only admins, when I ask for a run, then the request waits for an admin to approve.
- Given Paused, when anyone looks, then saved results and stopping still work.

Decided (Matt, 2026-10-13): User1 should be able to ask for a run from the page with Matt approving, but it's wanted, not urgent.

Evidence:
- `decklab/lib/api/simulations.py`: DEFAULT_MODE ('admins'), view
- `decklab/lib/permissions.py`: RUNS_ADMINS
- `decklab/lib/api/guard.py`: require_start
- `decklab/tests/test_api_permissions.py`: test_paused_starts_nothing

Gap: there's no way to ask for a run and no admin approval queue (criterion 3). The setting is all-or-nothing by role, with no per-person grant.

**E3-S14** · Matt · must · S · built

As an admin who also uses the PC for other things, I want to choose who may start simulations and how much of the PC they use, so that the household and members can use Deck Lab without simulations hogging the PC.

- Given Settings, when I pick Only admins, Anyone or Paused, then it is saved in the database and shows in Activity with who set it.
- Given I lower the Forge workers, when runs continue, then each run's next chunk uses the new limit, command-line runs included.
- Given the database can't be read, when someone tries to start, then the last mode read applies, else admins only.
- Given a member opens #/settings, when the page loads, then it says it's for admins.

Evidence:
- `decklab/web/settings.js`: showSettings, SIM_MODE_WORDS
- `decklab/lib/api/simulations.py`: _read (last mode read, else admins), change (saved with the actor)
- `decklab/lib/forge/slots.py`: limit, set_limit
- `decklab/tests/test_activity.py`: test_user1_sees_the_home_space_her_own_wishlist_and_the_simulations_setting
- `python -m decklab.lib.forge slots`

**E3-S15** · Matt · should · M · built

As a player who wants to improve between games, I want to know which cards underperform or never get cast, so that I know what to cut or replace.

- Given saved matchups of a list, when I open the deck's Matchups tab, then 'How its cards played' leads with spells stuck in hand and cards never cast.
- Given fewer than 800 card-log games, when shown, then the numbers are marked early.
- Given a card without 30 games each way, when shown, then it gets no verdict; lands never do.
- Given the card log is off, when shown, then the page says 'Per-card stats are off'.

Evidence:
- `decklab/web/matchups-cards.js`: cardStatsCoverage, cardStatsTable, CARD_STATS_GAMES, CARD_SPLIT_GAMES
- `decklab/lib/forge/cardstats.py`: MIN_CARD_GAMES, MIN_SPLIT_GAMES
- `decklab/web/matchups-overview.js` ('Per-card stats are off')
- `python -m decklab.lib.forge cards`

**E3-S19** · Matt · could · M · partial

As a player preparing for games against a much more experienced space member, I want to test my decks against a chosen group of that space member's decks, so that I know which of my decks stands up best.

- Given a space member's deck is Public, when I start a matchup, then I can pick it as an opponent; a private one isn't offered.
- Given several chosen opponents, when I start a group run, then one view shows my deck's average against them.
- Given that space's collection is private, when I view the matchup, then only the list and results show, never its counts.

Evidence:
- `decklab/lib/permissions.py`: sees_deck (own space or Public, no admin override)
- `decklab/web/matchups-overview.js`: matrixDecks (built from the viewer's visible library)
- `decklab/lib/forge/cli_evaluate.py`: `forge field --opponents` (command line only)

Gap: there's no group run of chosen opponents or averaged view on the page (criterion 2); the command line's `forge field --opponents` only narrows a field run to lists already in the field. This needs the same chosen-field mechanism as E3-S23.

**E3-S20** · Claude Code · should · L · built

As an operator keeping Forge accurate for Matt, I want to replay stale results, check card-script overrides and run experiments without mixing them into real results, so that the numbers stay comparable after every engine change.

- Given an engine change, when I run `replay --dry-run`, then it lists matchups played on another engine with games needed and time.
- Given an experiment spec, when I run `experiment`, then its arms play on the control's games and never mix with matchups.
- Given overrides, when I run `overrides check`, then overrides that no longer match Forge's scripts are reported.
- Given runs from the page, when they play, then at most 4 matchups and 2 field or variant runs play at once, and every Forge process, command-line runs included, takes a slot under the shared worker limit.

Now: the criteria hold. Further experiment games and the next Forge upgrade with its full replay are follow-up work in PLAN.md, not unmet criteria.

Evidence:
- `decklab/lib/forge/cli_results.py`: _cmd_replay, _replay_plan
- `decklab/lib/forge/experiment.py`: load_spec, check_spec; `decklab/lib/forge/cli_evaluate.py`: _cmd_experiment
- `decklab/lib/forge/overrides.py`: check; `decklab/lib/forge/cli_commands.py`: _cmd_overrides
- `decklab/lib/api/forge_runs.py`: MATCHUPS_AT_ONCE, COORDINATORS_AT_ONCE; `decklab/lib/forge/slots.py`: limit
- `decklab/tests/test_forge_replay.py`: test_a_dry_run_lists_what_it_would_play

**E3-S23** · Matt · could · M · partial

As a deck builder who reads the field rank, I want to choose on the page which decks belong to the field for each format (for example leave out a deck Forge pilots badly), so that the average and ranking compare against the decks we actually play, without hand-editing a file.

- Given an admin on a home deck's field view, when they open 'Who's in the field', then every list the rules include or leave out is shown, with why.
- Given an admin, when they add or take out a list for Constructed or Commander, then it is saved as one change in the audit trail and the field view shows the new membership.
- Given a list taken out of the field, when a field rank is shown, then it says how many lists were left out by hand.
- Given a member, when they view their field, then they can see its membership but not change home's.

Evidence:
- `decklab/lib/forge/field.py`: _simulation_edits (reads `decklab/simulation.json`'s field add/remove)
- `decklab/lib/forge/rankings.py`: _excluded (exclusion reasons shown in Rankings)

Gap: membership changes only by hand-editing `decklab/simulation.json`; there's no 'Who's in the field' view, page control, audit entry or count of lists left out by hand. Criteria 1, 3 and 4 weren't checked beyond that, so none is claimed met.

## E4: Get ready, play and learn

This epic covers getting physical decks onto the table and learning from the games played: choosing the decks, pulling and sleeving the cards from home's shared pool on Build decks (#/assembly, the packing plan), reading a deck's How to play and practising opening hands, playing with sideboard plans, and recording the result on the Game log (#/play). Each game is seen only by the spaces whose decks it names, a side whose deck the viewer may not see shows only as words such as "one of the home decks", and each space changes only its own side (E10-S32). Teaching the rules is left to products like the Beginner Box, so Deck Lab keeps teaching minimal. User1 uses Deck Lab on her phone, so Build decks and the Game log on a phone matter most.

Open: E4-S09, E4-S13, E4-S16, E4-S18, E4-S19.

**E4-S01** · Matt · must · L · built

As a player getting ready for a game at home, I want one list of what to pull, move and put back to assemble the decks we're about to play from the shared pool, with each physical copy counted once, so that the decks can go together tonight without hunting through storage or double-booking a card.

- Given one or more home decks selected (up to 12), when the plan is worked out, then each deck shows steps for sleeves, pull from storage, move from other decks, basics, tokens, put back and pack, and no physical copy is assigned twice.
- Given a needed card held by a built deck or intact product outside the plan, then 'Copies reserved elsewhere' names the holder. A move is planned only for copies released by a donor deck whose revised saved list is also selected; selecting an unchanged donor or an intact product doesn't free its cards.
- Given the plan is opened from a home deck page's More menu, then that deck is preselected with the list shown (Planned or Play-now).
- Given a deck outside home's space, then the plan refuses it: as a missing deck when the viewer can't see it, else with the plain reason that Build decks is for home's decks. Anyone outside home gets 403 for the whole plan.

Now: Built 2026-10-15, with the reservation rule above. Physical-device testing remains with E2-S22.

Evidence:
- `decklab/web/assembly.js`: packDeck, renderAssemblyPlan ('Copies reserved elsewhere')
- `decklab/lib/api/assembly.py`: MAX_DECKS, _preview, _deck_sections, plan_counts, require_sees_home_records
- `decklab/web/deck.js`: More > Build decks with the deck and list
- `decklab/tests/test_collection_assembly.py`: AssemblyTests

**E4-S02** · User1 · should · M · built

As a player packing a deck alongside Matt, I want my progress through the packing plan to be the same on whichever device either of us is holding, so that we can split the pulling between us and not lose our place if the phone locks or we switch to the iPad.

- Given a card ticked on one device, when the same plan is opened on another device, then it shows as ticked.
- Given both people tick cards at once, then neither tick is lost.
- Given the plan changes (a deck added or removed), then ticks for tasks still in the plan are kept, and changed tasks need checking again.

Decided (Matt, 2026-10-13): User1 packs on her phone while Matt uses another device, so this is the usual case.

Now: Built 2026-10-15 ([HISTORY.md, Share Build decks progress across devices](../HISTORY.md#share-build-decks-progress-across-devices-2026-10-15)), home profiles only. Physical-device testing remains with E2-S22.

Evidence:
- `decklab/web/assembly-progress.js`: wirePackTicks, packSync, packClearTicks
- `decklab/lib/api/assembly_ticks.py`: packing_ticks
- `decklab/tests/test_assembly_ticks.py`: AssemblyTicksTests
- `decklab/tests/test_packing_state.py`: MemoryPackingTests, PgPackingTests
- `decklab/tests/test_assembly_progress_ui.py`

**E4-S03** · Matt · should · M · built

As a player who has just finished putting a deck together, I want to record from the packing plan that the deck is now physically built, with its sleeves and deck box, so that the shared pool counts its cards as in use and the library shows it as built, without a separate trip to the editor.

- Given every card check of a deck in the plan is ticked, when I choose Mark as built, then a review asks for its sleeves and deck box (its owner's or shared ones), and the deck's status becomes built in the same change.
- Given the deck has both lists, then the review asks which list was built (Built version); changing it returns to fresh card checks.
- Given the change is saved, then the affected decks' availability tables are refreshed in the same change; if a table can't be refreshed, then the result says so and links to Tables out of date.
- Given I cancel the review, then nothing is written; ticks alone never change a deck's status.

Now: Built 2026-10-15 ([HISTORY.md, Finish building and physical stand-ins](../HISTORY.md#finish-building-and-physical-stand-ins-2026-10-15)). Physical-device testing remains with E2-S22.

Evidence:
- `decklab/web/assembly.js`: packCanFinish, packMarkBuilt
- `decklab/web/assembly-sheets.js`: packReviewBuilt
- `decklab/lib/api/assembly_completion.py`: _BuildPlan
- `decklab/tests/test_assembly_completion.py`: AssemblyCompletionTests
- `decklab/tests/test_assembly_kit.py`, `decklab/tests/test_assembly_completion_ui.py`

**E4-S06** · User1 · must · M · built

As a beginner about to play a deck, I want to read how my deck is meant to win, what to look for in an opening hand and what to watch out for, in plain words with the cards' pictures a tap away, so that I can play it sensibly without asking Matt every turn.

- Given a deck whose Notes have game plan, mulligan, sideboard or watch-out topics, when I open the Overview tab, then How to play shows each as a folding topic, with card names that open the card viewer.
- Given the decklist changed after the notes were written, then a warning says the guide may be out of date.
- Given a deck with no such notes, then the page says 'No play guide yet' and what would fill it.
- Given purchase or simulation prose in the Notes, then it isn't shown in the guide.

Now: the guide is only what's written in the deck's Notes; Deck Lab doesn't write strategy itself.

Evidence:
- `decklab/lib/api/guide.py`: playing_guide
- `decklab/web/guide.js`: guideSection, guideInline
- `decklab/tests/test_guide.py`: ExtractionTests, GuideApiTests, GuideRenderingTests

**E4-S07** · User1 · wont · L · not_wanted

As a beginner who doesn't know all the rules yet, I want short explanations of the keywords, terms and turn steps that come up in my deck, so that I can learn the game while playing without looking things up elsewhere.

- Given a card in the viewer with a keyword (such as ward or flash), when I tap the keyword, then a one- or two-sentence plain explanation shows, citing its source.
- Given a deck, when I open How to play, then a 'Terms in this deck' topic lists the keywords its cards use.
- Given the explanations come from the official rules or Scryfall data, then they aren't written from memory.

Decided (Matt, 2026-10-13): teaching the rules in Deck Lab stays minimal; products like the Beginner Box do that. The in-context help that exists (How to play from the deck's Notes, including a hand-written Jargon topic, and the card viewer's rules text) stays.

Evidence:
- `decklab/lib/api/guide.py`: playing_guide (picks up a hand-written jargon topic)
- `decklab/web/card-viewer.js`: no keyword or glossary handling

**E4-S08** · User1 · must · S · built

As a beginner learning when to mulligan, I want to deal practice opening hands from my deck and take London mulligans, so that I get a feel for what this deck's hands look like before a real game.

- Given a deck page's Practice tab, when I deal a hand, then seven cards from the list shown are dealt as pictures with land and spell counts, and 'Keep or mulligan?'.
- Given I mulligan, then a new seven is dealt and I'm asked to choose cards for the bottom before keeping.
- Given a Commander deck, then I can choose to make the first mulligan free (off by default).
- Given I keep, then I can draw further cards, and nothing in the deck or inventory changes.

Evidence:
- `decklab/web/hands.js`: OpeningHand, manualHandsSection, handStatus, handCounts
- `decklab/tests/test_play_ui.py`: test_london_mulligan_draws_seven_and_bottoms_exactly_once, test_free_multiplayer_mulligan_reset_and_empty_library

**E4-S09** · User1 · could · M · missing

As a beginner practising opening hands, I want to be told after I decide whether the hand I dealt is a keep for this deck, and why, in plain words, so that I learn this deck's mulligan decisions rather than guessing.

- Given a dealt opening hand, when I choose Keep or Mulligan, then the page says what the deck's keep rule would do (for example 'Keep: 3 lands and a 2-drop'), with its source.
- Given the deck's Notes have a mulligan topic, then that advice is shown next to the hand.
- Given a hand the rule calls borderline, then it says so instead of giving a firm answer.

Decided (Matt, 2026-10-13): teaching in Deck Lab stays minimal, so this is a could.

Evidence:
- `decklab/web/hands.js`: handStatus (only 'Keep or mulligan?')
- `decklab/lib/goldfish/engine.py`: _keeps, _bottom (keep rules used only by practice-game simulation)

Gap: Deal a hand never comments on the hand and doesn't show the deck's mulligan notes beside it; the keep rules live only inside the goldfish simulation.

**E4-S11** · User1 · must · M · built

As a player who has just finished a game at home, I want to record who won in one tap, with mulligans and notes only if I want them, so that we keep a history of our games without it feeling like paperwork.

- Given the Game log (or a deck's More > Game log), when I choose both decks and tap '<name> won' or Draw, then the game is reviewed by the server, shown in a toast with Undo for 8 seconds, and saved.
- Given More details, then I can set the date (not in the future), names, mulligans, a sideboard plan and notes.
- Given a saved game, then it keeps snapshots of both lists, and Correct this game keeps a preview step and offers only what's mine to change.
- Given neither deck is one I may edit, then the save is refused with 'A game you record needs one of your decks in it.'
- Given a deck I may not see, then I can't name it in a game (it answers as a missing deck), and a recorded side I may not see shows only as its space's words.

Now: the privacy rules were built 2026-10-18 ([HISTORY.md, Mixed Game-log records](../HISTORY.md#mixed-game-log-records-2026-10-18)).

Evidence:
- `decklab/web/play.js`: playQuickRecord, playListWords
- `decklab/lib/api/play_records.py`: _game, _snapshot, _view, save_game
- `decklab/lib/permissions.py`: play.record
- `decklab/tests/test_play_ui.py`: test_quick_record_undo_saves_nothing_and_hiding_the_page_saves_at_once, test_a_hidden_side_shows_its_words_only_and_goes_back_unchanged
- `decklab/tests/test_play_records.py`: PlayMemberRulesTests

**E4-S12** · Matt · should · S · built

As a player comparing our decks, I want to see head-to-head wins and draws between two decklists, and filter games by deck, so that we can see which of our decks has been doing well in real games.

- Given recorded games, when I open the Game log, then Head to head groups games with the same two lists and counts wins and draws per side.
- Given I filter by a deck, then only games with that deck are shown (the filter offers only decks I may see).
- Given a deck's list changes, then games with the old list are kept and grouped separately.

Evidence:
- `decklab/web/play.js`: playMatchupSummaries, playSideKey
- `decklab/lib/api/play_records.py`: play_overview
- `decklab/tests/test_play_ui.py`: test_session_summary_balances_seats_and_keeps_list_revisions_separate

**E4-S13** · Matt · could · M · missing

As a player who uses Forge to judge decks, I want to see our real head-to-head record next to Forge's predicted win rate for the same two lists, so that I know how far Forge's verdicts hold up for our decks and our play.

- Given recorded games between two lists that also have a Forge result, when I open the pair's matchup page or Head to head, then both are shown side by side with the number of real games.
- Given only a few real games, then the page says the real record can't confirm or contradict Forge yet.
- Given the lists differ from Forge's (an older list), then they aren't paired.

Evidence:
- `decklab/web/play.js`, `decklab/web/deck-sideboard.js`: the only pages that read /api/play; no matchup, field or rankings page uses play records

Gap: Real games are never compared with Forge's predictions and don't feed the field rating.

First slice: the real record beside Forge's rate on the matchup page for lists that match, with "too few games" below 10 real games until Matt picks the number.

Review note: criterion 2 needs a number of games as its threshold (Matt's call).

**E4-S14** · Matt · should · M · built

As a player playing best of three, I want to write down which sideboard cards come in and out against a particular opponent deck, so that between games I swap the same cards each time instead of deciding again at the table.

- Given a list with a sideboard and an opponent list, when I make a sideboard plan, then I set equal quantities in and out, and the deck itself never changes.
- Given either list changes later, then the plan shows as stale.
- Given I record a game using the plan, then the game stores the sideboarded list.
- Given someone else saved the plan meanwhile, then my save is refused and I'm asked to review it again.
- Given a plan, then it is only its deck's space's: the deck must be one of my space's, and an opponent I may not see is kept only as its space's words.

Evidence:
- `decklab/lib/api/play_records.py`: _plan_moves, _sideboard, _save, save_sideboard
- `decklab/web/play.js`: playPlanForm
- `decklab/tests/test_play_records.py`: PlayRecordsTests, PlayMemberRulesTests
- `decklab/tests/test_play_ui.py`: test_sideboard_form_uses_finite_source_quantities_and_reviews

**E4-S15** · User1 · should · S · built

As a player between games at the table, I want to see the sideboard plan for the deck I'm facing right where my deck is, so that I can swap cards in seconds without going to another page and matching list versions.

- Given my deck's page, when I pick the opponent's deck, then the matching sideboard plan shows its ins and outs as card pictures.
- Given no plan exists for that opponent, then the deck's Sideboard notes topic shows if there is one, with a link to make a plan.
- Given the plan is stale, then it's still shown, with a plain warning.

Now: Built 2026-10-15 ([HISTORY.md, Opponent sideboard plans on the deck page](../HISTORY.md#opponent-sideboard-plans-on-the-deck-page-2026-10-15)). Physical-device testing remains with E2-S22.

Evidence:
- `decklab/web/deck-sideboard.js`: deckSideboardSection, deckSideboardPlan, deckSideboardNotes
- `decklab/lib/api/play_records.py`: play_overview, _plan_cards
- `decklab/tests/test_deck_sideboard_ui.py`: DeckSideboardUiTests

**E4-S16** · Matt · could · L · missing

As a player planning sideboards, I want to test a sideboard plan against its opponent in simulated games, so that I know the swap helps before relying on it in a real best of three.

- Given a sideboard plan, when I start a test, then Forge plays the sideboarded list against the opponent on the base list's games and gives a Better / Worse / Makes little difference verdict.
- Given the simulations setting doesn't let me start runs, then the reason shows beside Start.
- Given the plan's lists change, then the old test is marked as for an older list.

Evidence:
- `decklab/web/variant.js`: Test this change (best-of-one games only)

Gap: Plans are recorded, not simulated, and Forge games are best of one. Testing sideboard plans is on PLAN.md's Still to do list.

**E4-S17** · User1 · should · S · built

As a player taking a deck to the table, at home now and later at a Commander night, I want a printed sheet with the decklist and its play guide, so that I can check the list and the plan without a phone at the table.

- Given a deck page, when I choose More > Print play sheet, then the list shown (Planned or Play-now) and its How to play topics print.
- Given the list changed after the notes, then the sheet says the guide needs review, with the date.
- Given More > Copy decklist or Download decklist, then the list comes out in Arena/MTGO form.

Evidence:
- `decklab/web/deck-tools.js`: exportedDeck, downloadDeck, copyDeck, printDeck
- `decklab/tests/test_deck_tools.py`: test_export_preserves_selected_cards_faces_sections_and_printing

**E4-S18** · Matt · could · M · missing

As a player at a social Commander night, I want to record a multiplayer game, including opponents who have no deck in Deck Lab, so that our Commander decks' real results are kept alongside our games at home.

- Given a 3- or 4-player pod, when I record a game, then I can name each seat with one of my space's decks or a free-text opponent and choose the winner.
- Given an opponent with no Deck Lab deck, then no deck snapshot is needed for that seat.
- Given these games, then Head to head keeps them apart from 1v1 games at home.

Evidence:
- `decklab/lib/api/play_records.py`: _game ('A game needs exactly two players and deck lists')

Gap: Only 1v1 between two Deck Lab lists can be recorded; no pods and no free-text opponent seats.

**E4-S19** · Space members · could · S · partial

As a space member playing my own deck against Matt or User1, I want the game record to name both players correctly without typing, so that games between spaces show up properly in the Game log.

- Given home's decks are Public and I record a game of my deck against one, then the other side defaults to that deck's player's name, not 'Opponent'.
- Given the other player isn't a profile, then I can type a name.
- Given home's decks aren't Public, then I can't name one in a game (it answers as a missing deck; E10-S32).

Evidence:
- `decklab/web/play.js`: playPlayers (the other profile of the visitor's space, else 'Opponent'), playQuickRecord (More details name fields)
- `decklab/lib/api/play_records.py`: _game

Gap: Criterion 1 isn't met: playPlayers gives a person-space visitor 'Opponent' rather than the chosen deck's player. Home's decks can be made Public since E10-S28 (live 2026-10-19), but none is yet, so it can't be tried with real data.

**E4-S21** · User1 · should · M · built

As a player whose deck is still being built, I want to know, before tonight's game, which cards in the deck are stand-ins and what each one stands for, so that we both know what the stand-ins mean at the table.

- Given a deck with cards neither owned nor free, when the packing plan is made for it, then each such card gets a suggested stand-in (a free owned card), or 'Any spare card' if none fits.
- Given the chosen stand-ins, when Overview or Build decks is opened, then it lists 'X stands for Y' with Y's picture and rules text one tap away.
- Given the play sheet is printed, then it records the stand-in mappings alongside the unchanged logical decklist.
- Given a stand-in is chosen and saved for the deck, then it is kept for the next game until the real card arrives.
- Given the real card is received, when the deck is next packed, then the plan says which stand-in to retire, and finishing that plan records the repack.

Now: Built 2026-10-15 ([HISTORY.md, Finish building and physical stand-ins](../HISTORY.md#finish-building-and-physical-stand-ins-2026-10-15)). These are physical markers, not strategic substitutes (those are E2-S07).

Evidence:
- `decklab/lib/decks/standins.py`: set_choices, install_stand_ins, physical_counts
- `decklab/lib/api/assembly_markers.py`: plan_standins
- `decklab/lib/api/assembly_standins.py`: save_standins
- `decklab/web/deck-standins.js`: deckStandinsSection; `decklab/web/deck-tools.js`: printDeck
- `decklab/tests/test_assembly_standins.py`, `decklab/tests/test_deck_standins_ui.py`

**E4-S22** · Matt · should · S · built

As a player who plays the same opponent at home, I want each deck to say which decks it's usually played against, so that we pick a fair pair for tonight without having to remember which deck goes with which.

- Given a deck with its usual opponents recorded (one or more deck ids, in the same space), when its deck page opens, then the Overview names each one with a link to its page, and the opponent's page names this deck in return.
- Given a viewer who may not see one of the two decks, then that link isn't shown to them.
- Given Build decks or a new Forge matchup, when one deck is picked, then its usual opponents are offered first.
- Given an opponent deck is deleted, then the link is dropped and no page shows a broken one.

Now: Built 2026-10-15 ([HISTORY.md, Usual opponents on decks and pickers](../HISTORY.md#usual-opponents-on-decks-and-pickers-2026-10-15)).

Evidence:
- `decklab/lib/decks/opponents.py`: parse_usual_opponents, set_usual_opponents
- `decklab/lib/api/opponents.py`: opponents_view, save_opponents
- `decklab/web/deck-opponents.js`: deckOpponentsSection, openDeckOpponents
- `decklab/tests/test_opponents.py`, `decklab/tests/test_deck_opponents_ui.py`, `decklab/tests/test_usual_opponent_pickers_ui.py`

**E4-S23** · Matt · should · S · built

As a player who has already gathered a deck's cards, I want to confirm a clear group of packing checks in one action, so that I can finish building without ticking every card individually.

- Given the packing plan, when I choose Tick all card checks for a deck, then that deck's unchecked card checks for the displayed list and scope are marked together, and I can still change individual checks.
- Given other decks, optional kit and token checks, or a sideboard outside that scope, then their checks stay as they were.
- Given I undo it, then only that action's changes are reversed.
- Given a bulk confirmation, then progress, physical availability and the separate Mark as built review stay distinct and accurate; missing and incoming cards stay unresolved.

Now: Built 2026-10-16 ([HISTORY.md, Bulk packing card checks](../HISTORY.md#bulk-packing-card-checks-2026-10-16)).

Evidence:
- `decklab/web/assembly-progress.js`: packBulkControl, packBulkTasks
- `decklab/tests/test_assembly_bulk_ui.py`: AssemblyBulkUiTests
- `decklab/tests/test_assembly_bulk_safeguards.py`: BulkPackingSafeguardsTests

**E4-S24** · Matt · should · M · built

As a player building a deck, I want to assemble its main deck separately from its sideboard, so that a playable main deck can be ready while some or all sideboard cards remain unbuilt or missing.

- Given a deck with a sideboard, when I open its packing plan, then I can choose the main deck with no sideboard, the whole sideboard, or chosen sideboard quantities.
- Given a complete main deck and an incomplete or missing sideboard, when I finish the main-deck build, then the missing sideboard doesn't block it and its unfinished state stays clear.
- Given only some sideboard copies are physically assembled, then reservations, kit counts and progress reflect those actual cards, while the intended sideboard list remains available.
- Given a smaller sideboard than the one already packed, then the plan shows the Put back actions and the review names the removals.
- Given an omitted or missing sideboard card, then its remaining intent can still be found for that deck (E5-S23).

Now: Built 2026-10-16; the main deck is always built complete (or with the Play-now list and stand-ins), and sideboard-first or partial-main builds aren't offered ([HISTORY.md, Main-only builds, partial sideboards and retained deck intent](../HISTORY.md#main-only-builds-partial-sideboards-and-retained-deck-intent-2026-10-16)).

Evidence:
- `decklab/lib/decks/assembled.py`: install, clear
- `decklab/lib/api/assembly_sections.py`: sideboard_choices, recipe
- `decklab/web/assembly-sections.js`: packSideboardChoice, remainingIntentPart
- `decklab/tests/test_assembled_model.py`, `decklab/tests/test_assembly_sections_ui.py`, `decklab/tests/test_assembly_sections_safeguards.py`

---

## E5: Decide what to buy

How Matt, with User1's wishes and Claude's research, goes from "this deck is short" to a decided purchase. On the page: each deck's sortable Prices table of converted Scryfall estimates, and Shopping's Decks still missing cards, Missing cards across decks, To buy, By shop and Long-term plan, with queue add, edit, move and remove for admins and reprint notices from cached Scryfall data. Live Australian shop checks, dated buylists and `watchlist apply` stay with Claude on the PC; recording an order, which reduces the queue rows it fulfils (Shopping's New order or `order add --fulfils`), belongs to E6. By design there are no spending totals and no collection value.

Open: E5-S08, E5-S15, E5-S17, E5-S19, E5-S24.

**E5-S01** · Matt · must · M · built

As a deck builder, I want to see what a deck is short of and roughly what those cards would cost in AUD, so that I can tell whether finishing it is worth spending on before any research.

- Given a home deck with missing cards, when I open its Cards tab, then the Prices section's price table lists each short card with need, can use, missing and an estimated A$ for one copy, plus a total.
- Given the estimates, when I read the table, then it says they are the cheapest non-foil printing's Scryfall US price with its price date, converted at the stated ECB rate and date, and suggests checking a shop before buying.
- Given nothing is missing, when I open the tab, then it says "Nothing to buy".
- Given I may not see that deck's space's inventory, when I open the deck, then no counts or prices are shown.

Evidence:
- `decklab/web/deck-prices.js`: ownedSection, ownedTable, ownedRow
- `decklab/lib/api/deck_page.py`: deck_view
- `decklab/lib/pool.py`: compare, owned_vs_needed
- `decklab/tests/test_deck_prices_ui.py`: test_hidden_failed_and_unpriced_inventory_remain_distinct_and_sort_fetches_nothing

**E5-S03** · Matt · must · S · built

As a buyer, I want one view of which home decks are still missing cards, so that I can choose which deck to shop for next.

- Given home decks whose Planned list misses cards, when I open #/shopping, then "Decks still missing cards" lists them, built and being built before ideas, fewest missing first.
- Given a deck has cards on the way or long-term rows, when it is listed, then chips show those counts.
- Given I tap a deck, then its Cards tab opens filtered to Missing.

Evidence:
- `decklab/lib/api/shopping_missing.py`: gather
- `decklab/lib/api/shopping.py`: _overview
- `decklab/web/shopping.js`: shopDecksMissing, shopDeckMissing
- `decklab/tests/test_shopping_ui.py`: test_decks_still_missing_cards_and_the_long_term_plan

**E5-S04** · Matt · should · M · built

As a buyer, I want the missing cards of all home decks in one list without duplicates, each naming the decks that want it and whether it's already queued, so that I can spot cards that serve several decks (and later Commander) and buy them first.

- Given two home decks both miss a card, when I open Missing cards across decks on #/shopping, then the card appears once, naming both decks with each one's shortfall and the total.
- Given a card already has a queue row, then the list shows that row's purpose, copies, state and dated reference price instead of suggesting it again.
- Given a token or reminder card shares a playable card's name, then it is never counted as that card's purchase.
- Given the card data isn't ready or a deck can't be read, then the list says so (naming the deck) rather than showing an empty or falsely complete list.

Now: Built 2026-10-15 ([HISTORY.md, Combined buying views and sortable missing-card prices](../HISTORY.md#combined-buying-views-and-sortable-missing-card-prices-2026-10-15)). The totals add each deck's separate shortfall, so shared collection copies may count for more than one deck.

Evidence:
- `decklab/lib/api/shopping_missing.py`: gather, is_token, unavailable
- `decklab/web/shopping-buying.js`: shopMissingCards, shopMissingCard, shopMissingQueue
- `decklab/tests/test_shopping_missing.py`: test_canonical_aliases_share_one_row_and_every_matching_queue_purpose_and_state_is_preserved, test_missing_card_data_is_explicitly_unavailable_while_orders_and_queue_still_show
- `decklab/tests/test_shopping_buying_ui.py`: test_same_name_token_never_annotates_a_playable_shortfall_even_after_redraw

**E5-S05** · Matt · must · M · built

As a buyer, I want a purchase queue that records each card I've decided to buy: how many, for which deck, any printing or an exact one, and its state, so that decisions survive between sessions and shops and don't get lost in buylist prose.

- Given a decision to buy, when Claude runs `watchlist set --add` with a name, state, quantity, purpose and source, then one row is added as one audited change.
- Given a row whose printing is exact, when it is saved, then set, collector number and finish are required, or the row is refused.
- Given the queue, when I open #/shopping, then To buy shows each row that isn't long-term with its picture, copies, deck, printing and a chip for any state other than ready.

Evidence:
- `decklab/db/inv_orders.py`: watchlist_list, watchlist_set, watchlist_remove, watchlist_apply
- `decklab/lib/inventory/orders.py`: queue_row, set_queue, remove_queue
- `decklab/lib/purchases.py`: read_queue
- `decklab/web/shopping.js`: shopQueueRow, shopPrinting
- `decklab/tests/test_inventory_orders.py`: test_watchlist_commands

**E5-S06** · Matt · should · L · built

As a buyer, I want to change the purchase queue myself on the page, including from my phone or iPad, so that I don't need Claude at the PC for a small decision made away from the desk.

- Given I'm an admin on #/shopping, when I change a row's state, then it is saved as one audited change by me, and refused if the queue changed meanwhile.
- Given a queued card, when I edit its copies or notes, then the new values are saved without changing its printing, purpose or research details.
- Given a queued card in To buy or Long-term plan, when I use Move, then I can choose any other purchase category; the card moves once saved, keeping its quantity, printing, purpose and research details.
- Given I remove a row, then I'm asked for a reason, which goes into the audit trail.
- Given I add a card on #/shopping, when I give its name, state, copies and deck (any non-foil printing by default, or an exact one), then one row is added as one audited change by me.
- Given I'm User1, then the queue is read-only for me; a profile outside home can't open Shopping at all.

Decided (Matt, 2026-10-13): Matt changes the queue on the pages himself, not only through Claude at the PC, so this is a should rather than a could.

Now: Built 2026-10-15 ([HISTORY.md, Edit the purchase queue on Shopping](../HISTORY.md#edit-the-purchase-queue-on-shopping-2026-10-15); Move: [Move purchase-queue cards between categories](../HISTORY.md#move-purchase-queue-cards-between-categories-2026-10-15)). Checks on the real phone and iPad are E2-S22's.

Evidence:
- `decklab/lib/api/shopping_queue.py`: save_queue_state
- `decklab/web/shopping.js`: shopQueueSheet, shopRemoveQueueSheet, shopSaveQueue, shopQueueMove, shopMoveQueue
- `decklab/tests/test_shopping_queue.py`: test_new_actions_are_admin_only_and_refuse_impersonation, test_crud_records_the_actor_and_removal_reason_without_position_churn, test_stale_and_partial_revisions_are_refused_before_resolving_the_row
- `decklab/tests/test_shopping_queue_manage_ui.py`: test_remove_requires_a_reason_and_reindexes_the_remaining_rows

**E5-S07** · Matt · must · S · built

As a buyer, I want each queued card to carry the lowest Australian price seen, the shop, whether it was in stock and the date checked, so that I judge deals against Australian in-stock prices, not converted US ones.

- Given Claude has checked shops, when it runs `watchlist apply --csv` with the updated copy, then the queue matches the file in one change.
- Given a row has a reference price, then a shop and a checked date are required, or the row is refused.
- Given a queued row with a reference price, when I view it on Shopping, then it shows "Reference price A$X at <shop>, checked <date>", with "Out of stock when checked" when it was out of stock, even without a card picture.

Now: Built 2026-10-15 ([HISTORY.md, Combined buying views and sortable missing-card prices](../HISTORY.md#combined-buying-views-and-sortable-missing-card-prices-2026-10-15)). The price and stock describe the recorded check, not today's availability.

Evidence:
- `decklab/lib/inventory/orders.py`: queue_row, replace_queue
- `decklab/web/shopping-buying.js`: shopReference
- `decklab/web/shopping.js`: shopQueueRow, shopPrice
- `decklab/tests/test_shopping_buying_ui.py`: test_reference_price_and_check_date_are_visible_without_card_data_or_image
- `decklab/tests/test_purchases.py`: test_queue_has_explicit_state_and_dated_reference_price

**E5-S08** · Matt · could · XL · missing

As a buyer, I want current Australian shop prices and stock for the cards I'm considering, without asking Claude to check by hand, so that I know what a deck will really cost here today.

- Given a missing or queued card, when I view it, then I see prices from named Australian shops with stock and the time they were fetched.
- Given a shop can't be reached, then its price is marked unknown rather than replaced by a converted US price.
- Given no Australian price is known, then any converted figure is labelled an estimate with its rate date.

Evidence:
- `decklab/lib/cards.py`: cheapest_usd (Scryfall USD only)
- `decklab/web/deck-prices.js`: ownedSection (the converted-estimate note)

Gap: No retailer price source exists anywhere in `decklab/lib`; Australian prices are only the queue's manually recorded reference prices.

Review note: XL and dependent on retailers with no public API; split per shop (MTGMate first) and into fetching vs showing, and a daily snapshot may do.

**E5-S09** · Matt · should · M · built

As a buyer, I want to see, for one shop, every queue row last seen there, long-term rows included, with stock and the checked date, so that I can top up an order from that shop and share postage.

- Given queue rows with a recorded shop, when I pick that shop in By shop on #/shopping, then every row last seen there is listed, with long-term rows marked as such.
- Given a row was out of stock at its last check, then it is shown apart from in-stock rows and rows whose stock is unknown.
- Given a row has no recorded shop, then it is listed under "Not checked at any shop".

Now: Built 2026-10-15 ([HISTORY.md, Combined buying views and sortable missing-card prices](../HISTORY.md#combined-buying-views-and-sortable-missing-card-prices-2026-10-15)). Its value depends on the recorded shop checks being kept current.

Evidence:
- `decklab/web/shopping-buying.js`: shopByShop
- `decklab/web/shopping.js`: drawShopping
- `decklab/tests/test_shopping_buying_ui.py`: test_shop_groups_include_long_term_and_keep_stock_yes_no_unknown_separate, test_shop_selection_filters_recorded_research_without_writing

**E5-S10** · Matt · must · S · built

As a buyer, I want to keep a long-term plan of cards for decks I'll build later, separate from what I'm buying now, so that any shop order can be topped up from it without buying early for no reason.

- Given a card for a planned deck, when it is added with state long_term, then it stays out of To buy.
- Given long-term rows, when I open #/shopping, then "Long-term plan" groups them by deck, 12 at first then Show all, explained as add-ons to an order to share its postage.
- Given a deck becomes the next to build, when its rows are changed to ready, then they move to To buy.

Evidence:
- `decklab/web/shopping.js`: shopLongTerm, SHOP_LONG_TERM_SHOWN, drawShopping
- `decklab/tests/test_shopping_ui.py`: test_decks_still_missing_cards_and_the_long_term_plan

**E5-S11** · Matt · should · M · built

As a buyer, I want to know before buying whether a card is about to be reprinted, so that I can check whether waiting changes the buying decision.

- Given a missing or queued playable card with an earlier released paper printing and an upcoming paper printing in the cached Scryfall data, when I view its buying row, then it names the upcoming set and ISO release date, with the snapshot date and coverage limits beside it.
- Given a card is waiting for a reprint, when it is queued, then its state is waiting_for_reprint and To buy shows "Waiting for reprint"; the state changes only by an explicit queue edit.
- Given a waiting row has a usable past price-check date and a later paper reprint's release date has passed, then the row offers "Check prices again" for a manual review.
- Given the check date is missing, invalid or in the future, or the reprint data is unavailable, then a waiting row explains the uncertainty and offers a manual check without claiming an old printing is newly released.
- Given I open the manual review, then it keeps my exact-printing and finish preference and dated reference price, shows dated printing sources and Scryfall's USD price, and lets me copy the exact card name; opening or closing it changes nothing saved.

Now: Built 2026-10-16 ([HISTORY.md, Dated reprint details and manual price-review offers](../HISTORY.md#dated-reprint-details-and-manual-price-review-offers-2026-10-16)). It sees only paper printings already in the local Scryfall snapshot, not every announced set, and a passed release date proves neither stock nor a lower price.

Evidence:
- `decklab/lib/reprints.py`: for_card
- `decklab/lib/api/reprints.py`: evidence, enrich
- `decklab/web/shopping-reprints.js`: reprintInfo, openReprintPriceCheck
- `decklab/tests/test_reprints.py`: test_waiting_row_with_unknown_or_future_check_gets_manual_review_not_old_release_claim
- `decklab/tests/test_shopping_reprints_ui.py`: test_due_offer_opens_manual_sources_and_preserves_category_prices_and_exact_specification

**E5-S12** · Claude Code · must · S · built

As the command-line operator, I want to save each round of buying research as a dated record that queue rows can point to, so that later sessions and Matt can see why a card was queued and what prices and stock were seen that day.

- Given research, when I write it, then it goes to `magic/buylists/<date>-<topic>.md`, starting with the historical-research banner, and is committed.
- Given a queue row or order record, when it is saved, then its source must name an existing buylist, or a deck that exists, was renamed or was retired with its history; any other path is refused.
- Given new prices later, then a new dated buylist is written instead of editing the old one.

Evidence:
- `decklab/lib/purchases.py`: source_exists
- `decklab/lib/inventory/orders.py`: queue_row
- `decklab/tests/test_purchases.py`: test_a_source_naming_a_deck_is_looked_for_among_the_snapshots_decks
- `AGENTS.md`: "Researching what to buy"

Review note: Criteria 1 and 3 are Claude's process rules, checked against `magic/buylists/` and AGENTS.md rather than Deck Lab's code.

**E5-S14** · User1 · must · S · built

As a themed-deck player, I want a private list of cards I'd like, with the printing I like for its art, so that I remember them and can show Matt which ones I mean.

- Given I'm signed in as User1, when I add a card on #/wishlist, then it's saved at once, and its sheet lets me set notes, printing and source.
- Given Matt or anyone else asks for my wishlist, then they get 403, admin included.
- Given I remove a card, then Undo puts it back in its old place with its notes, printing and source.
- Given a card is owned or on the way in my own space's pool (home's, for User1), then the tile shows those counts.

Decided (Matt, 2026-10-13): User1 uses Deck Lab on her phone, so the wishlist on a phone is one of her main surfaces.

Evidence:
- `decklab/lib/api/wishlists.py`: get_wishlist, change_wishlist, _view
- `decklab/lib/api/guard.py`: require_sees_wishlist
- `decklab/web/wishlist.js`: drawWishlist, openWishlistSheet, wishlistAvailability
- `decklab/tests/test_wishlist_server.py`: test_only_the_owner_reads_it
- `decklab/tests/test_wishlist_ui.py`: test_remove_has_an_undo_that_puts_the_card_back_as_it_was

**E5-S15** · User1 · should · M · missing

As a themed-deck player, I want to ask for a card on my wishlist to be bought, without managing the purchase queue, so that cards for my decks get bought without me having to remember to tell Matt.

- Given a card on my wishlist, when I ask for it to be bought, then it takes 3 taps or fewer and the request names the card, my chosen printing and the deck it's for.
- Given a request, when Matt opens #/shopping, then he sees it and can turn it into a queue row or decline it, and I see which he did.
- Given my wishlist notes, then they are not copied into the request or the audit message unless I write them into the request.

Decided (Matt, 2026-10-13): User1 should be able to ask from the page, with Matt approving, though she'd probably also just say it in person; wanted but not urgent.

Evidence:
- `decklab/web/wishlist.js`: no request action
- `decklab/lib/api/shopping.py`, `shopping_queue.py`, `wishlists.py`: no request route

Gap: No request object, API or page links a wishlist card to the queue. Accepting a request could use the built queue write (E5-S06, `shopping_queue.py`).

Review note: The second criterion bundles accept, decline and the answer back to User1, and could split.

**E5-S16** · User1 · should · S · built

As a themed-deck player, I want to see what is queued and on the way for my decks, so that I know which cards are coming without asking.

- Given I'm User1, when I open #/shopping, then I see On the way, To buy, Decks still missing cards and the Long-term plan read-only, with delivery details but no edit, Receive or Done controls.
- Given a queued card's purpose or source names a home deck, then the row links to that deck's title.
- Given any profile outside home (a member such as User2 or User5), then Shopping isn't in their navigation and /api/shopping answers 403.

Now: Built 2026-10-14 ([HISTORY.md, Milestones](../HISTORY.md#milestones), "Cards on the way and links from Shopping"); home-only since E10-S29 (2026-10-18).

Evidence:
- `decklab/lib/api/shopping.py`: shopping_overview, _link_decks
- `decklab/lib/api/guard.py`: require_sees_home_records
- `decklab/web/core.js`: seesHomeInventory
- `decklab/web/shopping.js`: shopQueueRow, shopLongTerm
- `decklab/tests/test_shopping_ui.py`: test_a_member_sees_delivery_details_not_receive_or_done, test_queue_links_deck_titles_without_interfering_with_the_card_viewer

**E5-S17** · Matt · could · M · missing

As a deck builder, I want a tested swap that needs a card I don't own to show what that card costs in Australia, and let me put it in the queue, so that I can act on a "Better" verdict right away, judging improvement per dollar.

- Given a variant test of a home deck adds a card not owned, when the verdict is shown, then the card's Australian reference price, shop and checked date appear when one is recorded, else a labelled estimate.
- Given I'm an admin, when I choose to queue it, then a queue row is added for that deck with the test as its source, as one audited change.
- Given the card is already queued, then the result says so instead.

Evidence:
- `decklab/web/variant.js`: no price or queue references
- `decklab/lib/api/variant_page.py`

Gap: The variant result has no price and no queue link. It would benefit from E5-S08.

**E5-S18** · Matt · must · S · built

As a buyer, I want estimates to default to the cheapest paper printing, non-foil, any set, so that I pay for playability, not collector premiums.

- Given a card with several printings, when an estimate is worked out, then it uses the cheapest non-foil paper printing, leaving out digital, oversized and memorabilia (such as gold-bordered) printings, and falls back to foil or etched only when no non-foil printing has a price.

Now: The queue's any/exact printing rules are E5-S05's, and an exact row being fulfilled only by its printing is E6-S01's.

Evidence:
- `decklab/lib/cards.py`: cheapest_usd, UNPLAYABLE_PRICE_SET_TYPES

**E5-S19** · Matt · could · L · missing

As a buyer, I want to hear when a card waiting for stock is back in stock at an Australian shop, so that I don't miss it while it's available.

- Given a waiting_for_stock row, when a check finds it in stock, then the row shows the shop, price and date, and Shopping highlights it.
- Given no check has run, then nothing claims the card is in stock.

Evidence:
- `decklab/lib/purchases.py`: read_queue (in_stock is a recorded field only)

Gap: No scheduled stock check or alert; it needs an automated Australian stock source (E5-S08).

**E5-S20** · Matt · wont · S · not_wanted

As a buyer, I want Deck Lab never to total what I've spent, store what I paid, or ask me about it, so that buying stays about the decks, not a budget.

- Given an order is recorded, then no price or total is stored with it.
- Given any page, then no spend total, price-paid field or "you have spent" summary appears.

Decided (Matt, 2026-09-26): no budget or spending tracking; requests for spending totals or price-paid fields are declined.

Evidence:
- `AGENTS.md`: "No budget tracking"; Orders, "Never store prices or spending totals"

**E5-S21** · Matt · wont · S · not_wanted

As a buyer, I want no tracking of what my owned cards are worth or how their prices change, so that cards are judged by how they play, not as assets.

- Given owned cards, then no page shows collection value, value history or price alerts on owned cards.
- Given prices on the pages, then they appear only as dated, labelled estimates or reference prices for cards still to buy.

Decided (Matt, 2026-09-26): Magic is collected to play, so cards are judged by how they play, not by collector value.

Evidence:
- `AGENTS.md`: "What each game is for"
- `decklab/web/deck-prices.js`: ownedSection

**E5-S22** · Matt · should · S · built

As a buyer looking at a deck's missing cards, I want to sort its price table by estimated cost, name or copies missing, so that I can see the expensive gaps first when I judge improvement per dollar.

- Given a deck's price table, when I tap the ~AUD missing heading, then rows sort by estimated missing cost, highest first, and a second tap reverses it; cards with no price stay last.
- Given the table, when the Card or Missing heading is tapped, then rows sort by name or by copies missing.
- Given a sorted table, then the total row stays last and the sorted heading shows its direction to screen readers (aria-sort).
- Given a phone width, when the table is sorted, then the same sort works in the table's compact layout.

Now: Built 2026-10-15 ([HISTORY.md, Combined buying views and sortable missing-card prices](../HISTORY.md#combined-buying-views-and-sortable-missing-card-prices-2026-10-15)). Sorting is local to the shown table and fetches or saves nothing.

Evidence:
- `decklab/web/deck-prices.js`: ownedTable, ownedMissingPrice
- `decklab/tests/test_deck_prices_ui.py`: test_cost_sorts_extended_estimates_highest_first_then_reverses_with_unknown_last, test_native_header_buttons_expose_one_aria_sort_and_keep_keyboard_focus, test_compact_phone_table_uses_the_same_cost_and_missing_controls

**E5-S23** · Matt · should · M · built

As a deck builder, I want intended missing cards, including an unfinished sideboard, to remain associated with their deck, so that building what I can play now does not lose what I still want for that deck.

- Given a main deck built while sideboard cards remain missing or left out, when I open the built deck's Overview or the packing preview, then "Still intended for this deck" lists each unassembled card with its section and intended quantity, with missing and on-the-way copies shown separately.
- Given the deck is taken apart, rebuilt or its build scope changes, then its saved Planned and Play-now lists keep the intended cards, the packing preview for the next build lists them again under "Still intended for this deck", and no intended copy is counted twice.
- Given intentions are shown, then they follow the deck's existing deck and inventory permissions, and no wishlist or queue row is created or changed.

Now: Built 2026-10-16 ([HISTORY.md, Main-only builds, partial sideboards and retained deck intent](../HISTORY.md#main-only-builds-partial-sideboards-and-retained-deck-intent-2026-10-16)). The deck's saved lists are the lasting record of intent; building with an incomplete sideboard is E4-S24's.

Evidence:
- `decklab/lib/api/assembly_intent.py`: project
- `decklab/web/assembly-sections.js`: remainingIntentPart, deckAssemblySection
- `decklab/lib/api/assembly.py`: remaining_intent (packing preview)
- `decklab/tests/test_assembly_intent.py`: test_main_only_retains_owned_waiting_and_missing_sideboard_separately, test_same_name_in_main_and_sideboard_consumes_availability_only_once, test_building_preview_keeps_chosen_list_intent_and_actual_page_has_no_build, test_only_inventory_viewers_receive_actual_build_and_retained_intent

**E5-S24** · Matt · could · S · missing

As Matt, ordering singles from several shops, I want to copy one shop's list from Shopping's By shop, so that I can paste it into that shop's search or basket without retyping each card.

- Given By shop lists a shop's cards, when I choose Copy this shop's list, then the clipboard holds one line per card as `<quantity> <exact Scryfall name>`, the format shops' bulk search and deck import accept, and a toast says how many cards were copied.
- Given a row whose printing is `exact`, then its line also names the set and collector number, so the shop can find that printing.
- Given a viewer who can't see home's records, then there is no By shop and nothing to copy.

Gap: By shop has no copy action; checking shops is still done by hand (a step short of live prices, E5-S08). Raised by the 2026-10-24 usage review (Shopping is Matt's second most-opened page).

---

## E6: Record orders and receive cards

Home's buying, from placing an order to its cards sitting in the right deck or in storage: singles, token singles, sealed products, pending orders shown as on the way, correcting, splitting, cancelling and removing pending orders, the Receive delivery check-off board, arrival checks and follow-ups. Each change has a page control on Shopping or Receive delivery and a command (`order …`, `product add|edit`, `receive [--expect]`), saved as one audited change with the deck tables it refreshes. Order changes, receipts and follow-ups need a home admin; User1 sees the same pages read-only, and nobody outside home sees them at all, since person spaces have no orders, products or deliveries. Orders never store prices or spending totals, and physical-device acceptance is tracked in E2-S22.

Open: E6-S19.

**E6-S01** · Claude Code · must · L · built

As Claude Code, operating for Matt, I want to record a new order (singles, token singles and sealed products) in one audited, previewable change that also reduces the watchlist rows it fulfils, so that the record, the queue and the decks' on-the-way counts never disagree.

- Given cards, tokens and product CSVs in the scratchpad, when I run `order add ... --fulfils 'NAME@FOR=QTY' --dry-run`, then nothing is saved and the output lists the components, the watchlist reductions and the decks whose tables would change.
- Given the same command without `--dry-run`, when it succeeds, then the record, components, product, watchlist reductions and refreshed deck tables are one change set by Claude (or the `--actor`) with my `-m` message.
- Given a card name or printing the card index doesn't know, when I run it, then it is refused with exit 1 and names the row.
- Given a watchlist row whose printing is `exact`, when the order doesn't hold that printing in the quantity asked, then the whole order is refused.
- Given an order after which the deck tables couldn't be refreshed, when I run it without `--force`, then it is refused and says why.
- Given a real order for more copies of printings already owned, when I give `--extra-copies C` (or later `order extra-copies ID C`), then it saves without `--force` and the pool doesn't warn about that component.

Evidence:
- `decklab/db/inv_orders.py`: order_add, order_extra_copies, _run, _refresh_refusal
- `decklab/lib/inventory/orders.py`: add_order, _fulfil, check_printings, extra_copies
- `decklab/tests/test_inventory_orders.py`: test_adding_an_order_records_everything_in_one_change, test_dry_run_saves_nothing, test_a_change_that_would_stop_the_refresh_is_refused_unless_forced, test_an_order_added_with_extra_copies_marked
- `decklab/tests/test_shopping_orders.py`: test_fulfilment_must_be_present_in_the_order_and_match_exact_printings

**E6-S02** · Matt · should · L · built

As Matt, the buyer, I want to record an order I've just placed when I'm away from the PC, so that its cards count as on the way straight away without waiting for a session with Claude.

- Given I'm a home admin on #/shopping, when I start a new order, then I can give the seller, the date, the cards (by search or a pasted list), token cards, a product and arrival checks, and pick the watchlist rows it fulfils.
- Given the entered order, when I preview it, then it shows the same checks, watchlist reductions and deck-table changes as `order add --dry-run`, from the same operation.
- Given I confirm, when it saves, then it is one change set by me and appears under On the way; a preview made on an older inventory, or by another person, can't be saved.
- Given User1 or anyone outside home, when they open Shopping, then no order form is offered and the API refuses them.

Decided (Matt, 2026-10-14): every part of the order process (recording, changing, cancelling, removing) must be possible on the pages, not only through Claude at the PC; changing orders is E6-S24.

Now: Built 2026-10-15 ([HISTORY.md, Record placed orders on Shopping](../HISTORY.md#record-placed-orders-on-shopping-2026-10-15)).

Evidence:
- `decklab/lib/api/shopping_orders.py`: preview_order, apply_order
- `decklab/web/shopping-orders.js`: shopOrderSheet, shopOrderPreview
- `decklab/tests/test_shopping_orders.py`: test_mixed_preview_matches_cli_operation_without_writes_and_save_uses_one_operation, test_members_and_outsiders_are_refused_before_inventory_or_preview_lookup
- `decklab/tests/test_shopping_orders_ui.py`: test_order_form_needs_admin_home_permission_and_revision

**E6-S03** · User1 · must · S · built

As User1, the themed-deck player, I want to see which of my deck's missing cards are already ordered, and on which order, so that I know whether tonight's game needs stand-ins.

- Given a home deck with cards in a pending order, when I open its deck page, then the banner says how many cards are on the way (for example 'Ready once 3 cards arrive') and names the orders and products they come from.
- Given the Cards tab, when I filter to On the way, then each such card shows an 'N on the way' chip naming its order or product and whether it's ordered or preordered.
- Given the price table, when I open it, then each on-the-way card is labelled with its order or product ('1 on the way (order 2026-01-01-example)').
- Given a viewer outside home, when they see a deck in their own space, then home's orders are never counted or named.

Decided (Matt, 2026-10-13): orders don't get an expected arrival date (E6-S23), so this story only names the order.

Now: Built 2026-10-14.

Evidence:
- `decklab/lib/pool.py`: incoming_sources
- `decklab/web/deck-availability.js`: incomingBannerSources, incomingSourceChip, availabilityBanner
- `decklab/tests/test_api_incoming.py`: test_recorded_order_identity_and_only_required_copies, test_products_keep_identity_and_ordered_or_preordered_status, test_home_sources_hidden_from_other_spaces_without_loading_pool, test_personal_pool_does_not_count_home_orders

**E6-S04** · Matt · must · M · built

As Matt, the buyer, I want one shared view of every delivery still on the way, what it holds and what to check when it comes, so that User1 and I know what's coming without asking Claude.

- Given pending orders, when Matt or User1 opens #/shopping, then On the way lists each as 'seller · topic' with a picture strip, notes and arrival checks.
- Given a part already received or a preordered product, when its card shows, then it carries a Part received or Preordered chip.
- Given deliveries waiting, when a home profile has any page open, then the top bar's Shopping shows their count.
- Given anyone outside home (User2 or another member), when they request /api/shopping, then they get 403 ("The shopping list, deliveries and packing plan are private."), naming no one, and Shopping isn't in their navigation.

Evidence:
- `decklab/web/shopping.js`: shopOrderTitle, shopOrderChip, shopStrip, shopDelivery
- `decklab/web/shell.js`: loadDeliveries, showDeliveries
- `decklab/web/core.js`: seesHomeInventory
- `decklab/lib/api/shopping.py`: shopping_overview (guard.require_sees_home_records)
- `decklab/tests/test_shopping_ui.py`: test_deliveries_are_titled_by_seller_and_topic_with_pictures_checks_and_receive

**E6-S05** · Claude Code · must · M · built

As Claude Code, operating for Matt, I want to correct a pending order's rows and arrival checks, and split off rows that will come separately, before it arrives, so that the record matches what the shop actually sends.

- Given a pending cards or tokens component, when I run `order edit ID C --csv FILE`, then its rows are replaced only if the total quantity (and each name's copies, for cards) stay the same.
- Given a component, when I run `order checks ID C --add TEXT` or `--withdraw N`, then the check list changes, and a pending check can't be resolved before arrival.
- Given a pending component, when I run `order split ID C --new-id NEW --take ROW[:QTY]`, then those rows move to a new pending component and each check goes to both parts unless `--move-check` or `--keep-check` says otherwise.
- Given any of these with `--dry-run`, when I run it, then nothing is saved and the change is shown.

The same changes on Shopping are E6-S24.

Evidence:
- `decklab/db/inv_orders.py`: order_edit, order_checks, order_split, _write
- `decklab/lib/inventory/orders.py`: edit_order, order_checks, split_order
- `decklab/tests/test_inventory_orders.py`: test_editing_a_pending_component, test_checks_are_added_resolved_and_cleared, test_splitting_a_component_keeps_the_totals

**E6-S06** · Matt · should · M · built

As Matt, the buyer, I want to receive only the cards that came when a shop sends an order in several parcels, so that the cards that arrived become free to use while the rest stay on the way.

- Given an order with several components, when I tick 'This arrived' on some on #/receipt, then only those are received.
- Given part of one cards or tokens component arrived, when I tick just those rows (or use Split copies for part of a quantity), then only they are received, in one change, and the rest stays a pending component with its open checks and its share of the fulfilled queue intent.
- Given nothing ticked in a component, when I preview, then no unticked card is received; a product always arrives whole.

Now: Built 2026-10-15 ([HISTORY.md, Receive only the checked copies](../HISTORY.md#receive-only-the-checked-copies-2026-10-15)).

Evidence:
- `decklab/web/receipt-workflow.js`: rcptRequest, rcptAssignments, previewDelivery, applyDelivery
- `decklab/lib/inventory/receive_partial.py`: prepare
- `decklab/lib/api/receipts.py`: preview_receipt, apply_receipt
- `decklab/tests/test_receive_partial.py`: test_preview_and_apply_split_one_quantity_with_one_apply_and_conserve_physical_supply, test_products_always_refuse_individual_row_selection
- `decklab/tests/test_receipts_ui.py`: test_several_parts_ask_what_arrived

**E6-S07** · Matt · should · M · built

As Matt, the buyer, I want to cancel the part of an order a shop couldn't supply, with the reason recorded, so that its cards stop counting as on the way and the queue shows them as still to buy.

- Given a pending cards, tokens or product component, when I use Shopping's **Cancel part…** or Claude runs `order cancel ID C -m ... --reason ...`, then it is kept as cancelled with the reason, never counts as incoming, and the deck tables are refreshed in the same change.
- Given the order's recorded fulfilment intent, when I cancel, then Shopping offers those queue quantities back, checked by default, and previews the exact rows and warnings first; the command line restores them only with `--restore-queue`.
- Given a product list or token names corrected since the order, when it is cancelled, then the original recorded request is what's restorable, with a warning to review; no replacement intent is guessed. A quantity is never restored twice across a cancellation and a later removal.
- Given an older order without recorded fulfilment intent, when it is cancelled, then no queue rows are guessed and the preview and result say the queue needs a manual review.
- Given buylists that link the cancelled payload, when it is cancelled, then the command lists them for a hand fix.
- Given an order's components are edited or split before cancelling, then a price-free ledger in its `audit_notes` still knows which queue rows each component fulfilled; restored rows keep their existing queue details, and recreated rows have blank price, shop and date fields.

Now: Built 2026-10-15 ([HISTORY.md, Cancelling and removing orders, with queue restoration](../HISTORY.md#cancelling-and-removing-orders-with-queue-restoration-2026-10-15)).

Evidence:
- `decklab/lib/inventory/order_lifecycle.py`: cancel
- `decklab/lib/inventory/order_fulfilment.py`: record, restore
- `decklab/web/shopping-order-edit.js`: shopOrderCancelSheet, shopOrderEndSheet
- `decklab/tests/test_order_lifecycle.py`: test_tracked_split_cancel_and_remove_restore_each_copy_once, test_historical_order_never_guesses_queue_rows, test_declined_offer_is_consumed_before_later_removal
- `decklab/tests/test_order_cancel_cli.py`: test_cancel_opt_in_restores_recorded_quantities_in_the_same_apply

**E6-S08** · Matt · should · M · built

As Matt, the buyer, I want to correct or remove a sealed product I recorded wrongly while it's still pending, so that a wrong product doesn't hold cards on the way or confuse the decks' tables.

- Given a pending product, when its card list, name, format, status (ordered or preordered) or notes are wrong, then Shopping's **Correct product…** or `product edit STEM` replaces only the fields given, previewed (`--dry-run`), in one audited change that refreshes the affected deck tables.
- Given a pending product recorded by mistake, when I cancel its part or remove its mistaken order with a reason, then its cards stop counting as on the way and the deck tables refresh; queue quantities follow E6-S07's rules.
- Given a product already owned, received or cancelled, when a correction is tried, then it is refused.

Now: Built 2026-10-15 ([HISTORY.md, Correct pending products on Shopping](../HISTORY.md#correct-pending-products-on-shopping-2026-10-15)).

Evidence:
- `decklab/lib/inventory/product_ops.py`: edit_product
- `decklab/db/inv_orders.py`: product_edit
- `decklab/web/shopping-order-rows.js`: shopOrderProductSheet
- `decklab/tests/test_pending_products.py`: test_only_supplied_fields_change_and_empty_text_clears, test_cli_validation_refuses_owned_and_empty_corrections
- `decklab/tests/test_order_lifecycle.py`: test_cancel_product_retains_history_but_leaves_pool_library_and_packing

**E6-S09** · Matt · must · L · built

As Matt, the buyer, I want to check a delivery card by card against pictures, fixing printing, finish, condition and language as I go, so that the collection records the physical cards that actually arrived.

- Given a pending delivery, when I open #/receipt?order=<id>, then each part is a grid of card pictures (a dashed frame when the printing isn't recorded) with a tick, chips for attention and the decks that use it.
- Given a card's sheet, when I choose Different printing…, a finish, condition or language, or Split copies, then the row changes on the board only.
- Given the board, when I filter by Not checked or Needs attention, or use Tick all, then the grid and the sticky progress bar follow.
- Given I reload mid-check, when the inventory hasn't changed, then 'Resume your check' brings back my ticks and edits.

Evidence:
- `decklab/web/receipts.js`: rcptToolbar, rcptTools, rcptTile, rcptUnrecorded, rcptCardFields, rcptSplit
- `decklab/web/receipt-workflow.js`: rcptProgress, rcptSaveDraft, rcptOfferDraft
- `decklab/lib/api/receipts.py`: receipt_view, _deck_uses
- `decklab/tests/test_receipts_ui.py`: test_the_board_shows_pictures_chips_and_the_tiles_open_the_viewer_as_a_group, test_the_check_is_kept_and_offered_back_after_a_reload

**E6-S10** · Matt · must · M · built

As Matt, the buyer, I want to see in plain words what an arrival will change before I record it, and have it all saved together, so that a half-recorded delivery can't leave the collection and the decks out of step.

- Given every arrived card ticked, when I tap Preview, then it lists what goes into the collection and tokens, which decks' tables change, and any blockers linked to their card.
- Given the preview, when I confirm within 30 minutes and the inventory hasn't changed, then the receipt and refreshed tables save as one change by me; the preview is used once, only by the profile that made it.
- Given a Collection or Tokens save in between, when I confirm, then it asks for a new preview (409).
- Given User1, when she opens the same page, then she sees the board read-only and can't record it; anyone outside home is refused the page.

Evidence:
- `decklab/lib/api/receipts.py`: PREVIEW_LIFETIME, preview_receipt, _load_preview, apply_receipt
- `decklab/web/receipt-workflow.js`: rcptClientBlockers, previewDelivery, rcptPreviewSheet
- `decklab/web/receipts.js`: drawReceiptReadOnly
- `decklab/tests/test_receipts_api.py`: test_a_stale_form_and_a_stale_preview_are_refused, test_a_preview_is_used_once_by_the_profile_that_made_it, test_the_view_is_home_records_only
- `decklab/tests/test_receipts_ui.py`: test_a_member_sees_the_tiles_read_only

**E6-S11** · Claude Code · must · M · built

As Claude Code, operating for Matt, I want to record an arrival from the command line with the physical facts the user reported, so that a delivery Matt tells me about at the PC is saved the same way the page saves it.

- Given `receive --order ID` without `--apply`, when I run it, then it previews the selected components and their blockers, and prints a token for that preview.
- Given a cards component with checks, or any tokens component, when I apply without `--verified C`, then it is refused.
- Given corrected rows in `--rows C=FILE`, when the totals (and each name's copies) match, then the receipt uses them.
- Given a preview's token, when I apply with `--expect TOKEN` and the inventory, components, rows, date or checks have changed since, then nothing is saved; without `--expect`, apply re-checks the blockers against the inventory at that moment.
- Given the tables can't be refreshed, when it saves, then it exits 3 and says why.

The preview binding is E11-S20.

Now: `--expect` built 2026-10-18 ([HISTORY.md, Dated Stats disclosures and guarded CLI receipts](../HISTORY.md#dated-stats-disclosures-and-guarded-cli-receipts-2026-10-18)).

Evidence:
- `decklab/db/inv_receive.py`: register, run, _preview_token
- `decklab/lib/inventory/receive.py`: blockers, _edited, receive
- `decklab/tests/test_receipt_cli_preview.py`: test_any_inventory_change_refuses_before_receipt_audit_or_deck_changes, test_invalid_preview_has_no_token_and_legacy_apply_still_revalidates
- `decklab/tests/test_receipts_api.py`: test_rows_from_a_file_replace_the_recorded_ones, test_a_refresh_that_fails_after_the_receipt_exits_3

**E6-S12** · Matt · should · S · built

As Matt, the buyer, I want to know where each newly arrived card goes, so that I can sleeve cards straight into the decks waiting for them and store the rest.

- Given a recorded arrival, when the board is replaced, then 'Where these go' groups the new cards by the deck waiting for them, with its sleeves when they're the viewer's to see.
- Given cards no deck is waiting for, when it shows, then they are listed for the storage box.
- Given a product, when it shows, then a kept-intact one goes to its own decks and a broken-up one to storage.

Evidence:
- `decklab/web/receipt-workflow.js`: rcptWhereTheyGo
- `decklab/lib/api/receipts.py`: _kits
- `decklab/tests/test_receipts_ui.py`: test_success_says_where_the_cards_go_and_offers_no_second_receipt
- `decklab/tests/test_receipts_api.py`: test_sleeves_show_only_for_built_decks_whose_kit_the_viewer_sees

**E6-S14** · Matt · must · S · built

As Matt, the buyer, I want to choose, when a sealed product arrives, whether it stays as its own deck(s) or goes into storage, so that its cards are counted as held or free correctly.

- Given a product on #/receipt, when it shows, then its cards are grouped by deck and section with 'Keep it as its own deck(s)' and 'Break it up into storage'.
- Given no choice made, when I preview, then it asks me to choose.
- Given 'no', when recorded, then its cards join the pool unsleeved and its sleeves and deck box are cleared; given 'yes', its cards stay held.

Evidence:
- `decklab/web/receipts.js`: rcptIntactChoice, rcptProductGrid
- `decklab/web/receipt-workflow.js`: rcptClientBlockers
- `decklab/lib/inventory/receive.py`: receive
- `decklab/tests/test_receive_order.py`: test_a_product_needs_an_intact_choice_and_leaves_out_plain_basics, test_a_product_receipt_upgrades_a_legacy_status_and_clears_the_kit_when_broken_up
- `decklab/tests/test_receipts_ui.py`: test_a_product_needs_its_choice_and_shows_its_cards

**E6-S17** · Matt · should · M · built

As Matt, the buyer, I want token singles I order to be received with their real front and back recorded, so that the token list matches the physical cards decks can grab.

- Given a tokens component on #/receipt, when I open a token's sheet, then I can Swap front and back, rename a face or mark Back is blank.
- Given a tokens component, when I record it, then it must be verified, keep the physical pairing and have no unresolved pairing note.
- Given the receipt, when saved, then the tokens join the token cards and never change decklists, the playable pool or the watchlist.

Evidence:
- `decklab/web/receipts.js`: rcptTokenFields
- `decklab/web/receipt-workflow.js`: rcptClientBlockers
- `decklab/lib/inventory/receive.py`: _token_rows, blockers
- `decklab/tests/test_receipts_ui.py`: test_a_tokens_back_must_be_confirmed_and_can_be_swapped
- `decklab/tests/test_receipts_api.py`: test_an_unverified_or_unresolved_token_reverse_is_refused

**E6-S18** · Matt · should · S · built

As Matt, the buyer, I want to close the checks left open after a delivery (a product's tokens, a card's condition) once I've done them, so that follow-ups don't pile up and I can see what's really left to check.

- Given open checks on received components, when I open #/shopping, then Follow-ups lists each with its delivery.
- Given I tap Done as an admin, when 8 seconds pass without Undo, then it is resolved and kept as a verified check.
- Given User1, when she views Follow-ups, then she sees them without Done.
- Given the command line, when Claude runs `order checks ID C --resolve N`, then the same resolve is saved.

Evidence:
- `decklab/web/shopping.js`: shopFollowUp, shopDone
- `decklab/lib/api/shopping.py`: resolve_check
- `decklab/lib/inventory/orders.py`: order_checks
- `decklab/tests/test_shopping_ui.py`: test_done_marks_a_follow_up_after_its_undo_time, test_a_member_sees_delivery_details_not_receive_or_done
- `decklab/tests/test_shopping_checks.py`: test_a_check_is_resolved_into_verified_checks_as_one_change

**E6-S19** · User1 · could · M · missing

As User1, the themed-deck player, I want to be told when a delivery holding cards for my deck has been recorded, so that I know the deck is ready without checking the page.

- Given a receipt that frees cards for a deck Played by me, when it is recorded, then my next visit shows a notice naming the deck and how many cards arrived.
- Given I've seen the notice, when I dismiss it, then it doesn't come back for that receipt.

Gap: Deck Lab has no arrival notice; the receipt's list of changed decks (`decklab/lib/api/receipts.py`) would be its source.

**E6-S20** · Claude Code · should · S · built

As Claude Code, operating for Matt, I want a check of every order, receipt state and queue field after changing orders, so that broken records are caught before they confuse a deck's counts.

- Given orders and the watchlist, when I run `python -m decklab.lib.purchases --check`, then it reports record coverage, receipt-state and queue-field problems and exits 1 on any.
- Given the database is unreachable, when I run it, then it exits 2.
- Given the nightly `db check`, when it runs, then the orders and queue checks are part of it.

Evidence:
- `decklab/lib/purchases.py`: main, overview, _coverage
- `decklab/db/check.py`: _orders
- `decklab/tests/test_purchases.py`: test_unrecorded_delivery_fails_visibly, test_product_receipt_status_must_agree

**E6-S22** · Space members · wont · M · not_wanted

As a person-space member (like User2 or User5), I want orders and on-the-way cards in my own space, so that cards I've bought count before they arrive.

- Given a member records an order in their own space, when Deck Lab works out their decks' needs, then its cards count as on the way.

Now: person spaces have no orders, products or watchlist by design (AGENTS.md, "Spaces"); members add cards once they have them.

**E6-S23** · User1 · wont · M · not_wanted

As a themed-deck player waiting for cards, I want to see roughly when each delivery for my deck is expected to arrive, or that no date is known, so that I can tell whether the cards will be here before our next game.

- Given an order with an expected arrival date or range recorded, when User1 views a deck with cards on the way from it, then the deck page and Shopping show 'expected about <date>' next to that order.
- Given an order with no expected date, when it is shown, then it says 'Arrival date not known' and the order date, never a guessed date.
- Given an expected date that has passed and the component still pending, when it is shown, then it is marked overdue.

Decided (Matt, 2026-10-13): orders don't get an expected arrival date; naming the order a card is on the way in stays (E6-S03).

**E6-S24** · Matt · should · L · built

As Matt, the buyer, I want to change, cancel and remove orders on Shopping, not only record them, so that fixing an order never waits for Claude at the PC and never needs anyone to change the database by hand.

- Given a pending cards or tokens component, when I'm a home admin on #/shopping, then I can edit its rows (as `order edit`), add or withdraw an arrival check (as `order checks`), split off rows that will come separately (as `order split`) and cancel it with a reason (as `order cancel`), each previewed and saved as one audited change by me.
- Given a pending product, when I'm on #/shopping, then I can correct its card list, name, format, status and notes, or cancel it with a reason (E6-S08).
- Given a pending cards or product component, when I'm a home admin, then I can mark or unmark it as extra copies (as `order extra-copies`), previewed and saved as one audited change; token components are refused.
- Given an order recorded by mistake, when I remove it with a reason, then the record, its components and its product go, its cards stop counting as on the way, its recorded queue quantities come back (E6-S07's rules) and the deck tables refresh, in one audited change; removal is refused once any part has been received.
- Given an order's record fields (seller, date, notes, sources), when one is wrong, then I can change it on the page at any receipt status (as `order record`).
- Given a preview, when another device saves a change to the inventory first, then mine can't be saved and asks for a new preview.
- Given User1 or anyone outside home, when they open Shopping, then none of these controls is offered and the API refuses them.

Decided (Matt, 2026-10-14): Deck Lab must never rely on direct database changes for any part of the order process: every fix has a page control and a command.

Now: Built 2026-10-15 ([HISTORY.md, Correct order records and pending checks on Shopping](../HISTORY.md#correct-order-records-and-pending-checks-on-shopping-2026-10-15); [Correct pending order rows and additional copies](../HISTORY.md#correct-pending-order-rows-and-additional-copies-on-shopping-2026-10-15); [Split pending shipments](../HISTORY.md#split-pending-shipments-on-shopping-2026-10-15)).

Evidence:
- `decklab/web/shopping-order-edit.js`, `shopping-order-rows.js`, `shopping-order-split.js`: shopOrderEditSheet, shopOrderRowsSheet, shopOrderExtraSheet, shopOrderSplitSheet, shopOrderRemoveSheet
- `decklab/lib/api/shopping_order_changes.py`: preview_order_change, apply_order_change
- `decklab/lib/inventory/order_records.py`: record_order; `order_lifecycle.py`: remove
- `decklab/tests/test_shopping_order_changes.py`: test_stale_preview_and_transaction_race_cannot_overwrite_newer_corrections, test_members_are_refused_on_both_listeners_before_inventory_or_token_lookup
- `decklab/tests/test_order_lifecycle.py`: test_removal_refuses_any_received_part_owned_intact_or_shared_product

---

## E7: Keep the collection accurate

How the inventory stays true to the physical cards. Each space's own people add, fix and remove cards on the Collection page (single cards, an app export, Add a precon) and token cards on the Tokens page; Matt and User1 both edit home's, each member only their own, and Claude does bulk and member upkeep from the PC (`collection merge`, `collection edit` and `collection apply`, `collection add-precon --space`). Repeat imports, sales and trades, and cards held by built decks are all flagged, other decks' out-of-date tables are listed with Update all rather than refreshed automatically, and the nightly `db check` looks for drift.

Open: E7-S03, E7-S06, E7-S08, E7-S15, E7-S18, E7-S21, E7-S22, E7-S23, E7-S24, E7-S31.

**E7-S01** · Matt · must · M · built

As a deck builder sharing one pool, I want to add or fix a single card's printing, finish, quantity, condition, language and notes, so that the collection matches the cards in my hands without help from the PC.

- Given I may edit home's collection, when I add a printing already listed on the Collection page's Card list, then its quantity goes up instead of a second row appearing.
- Given a card's condition or language is unknown, when I save it, then the field stays blank (shown as '?') and is never set to NM or English.
- Given someone saved the collection after I opened it, when I save, then I get 'Load the latest and re-apply my changes', a per-field Yours/Theirs choice or 'Discard my changes', and nothing is overwritten.

Evidence:
- `decklab/web/collection.js`: drawCollectionRows, COL_CONDITIONS
- `decklab/web/collection-cards.js`: colSend, showCollectionConflict
- `decklab/lib/inventory/ops_collection.py`: add
- `decklab/lib/api/collection_edit.py`: save_card
- `decklab/tests/test_collection_ops.py`: test_add_a_listed_printing_adds_to_it_and_blanks_what_differs; `decklab/tests/test_collection_edit.py`: test_a_stale_sha_is_409_with_the_rows_now

**E7-S02** · Space members · should · L · built

As a member with my own collection, I want to bring in a collection app's export instead of typing each card, so that my space's collection is complete without hours of entry.

- Given a ManaBox, Moxfield, Deckbox or collection-columns CSV of up to 4 MB and 20,000 rows, when I preview it on my own space's Collection page, then each row is matched to a Scryfall printing and plain basics are dropped.
- Given rows with problems, when I apply, then they block the import unless I choose to leave them out.
- Given I apply, then the quantities are added in one change and the upload is kept unchanged as one of the space's raw imports.

Decided (Matt, 2026-10-13): the space members may use Deck Lab only occasionally, and mostly on phones if they do, so this is a should; the same import serves home's collection.

Evidence:
- `decklab/lib/api/collection_edit.py`: MAX_IMPORT, MAX_IMPORT_ROWS, _source_rows, read_upload, import_preview, import_apply
- `decklab/lib/inventory/ops_collection.py`: merge
- `decklab/web/collection.js`: openImportSheet, drawImportPreview
- `decklab/tests/test_collection_ops.py`: test_import_merges_and_keeps_the_raw_file; `decklab/tests/test_collection_edit.py`: test_ordinary_basics_are_not_added

**E7-S03** · Space members · could · M · partial

As an experienced player with older cards, I want import problems shown grouped by set, with a way to leave out a whole set at once, so that I can fix or skip an old set's rows quickly in a large export.

- Given an export with unmatched rows from several sets, when I preview it, then the problems are grouped under each set name with a count.
- Given a group, when I choose to leave it out, then every row in it is skipped and the rest can be applied.
- Given a 5,000-row export, when I preview it, then the preview finishes and lists the groups before anything is applied.

Evidence:
- `decklab/lib/api/collection_edit.py`: read_upload (problems as a flat list of line and message), import_apply (skip_problems)
- `decklab/web/collection.js`: drawImportPreview

Gap: problems are listed by file line with no set grouping or counts, and skip_problems leaves out every problem row or none, so one set can't be left out. Only the third criterion (a large export previews before applying) holds.

**E7-S04** · Matt · should · S · built

As a deck builder, I want to be warned when an import looks like a file already imported into this space, so that the same cards aren't counted twice.

- Given an upload whose content matches one of the space's raw imports, when I preview it, then the preview says it was already imported, on what date and by whom.
- Given that warning, when I still apply, then it's added (merges stay additive) and the change records that it was a repeat.
- Given `collection merge` of a file already imported, then it warns that the merge is an additive repeat and the change records it.

Now: built 2026-10-15 ([HISTORY.md, Collection import and reduction guards](../HISTORY.md#collection-import-and-reduction-guards-2026-10-15)).

Evidence:
- `decklab/lib/inventory/ops_collection.py`: repeat_imports, merge
- `decklab/lib/api/collection_edit.py`: import_preview, import_apply
- `decklab/web/collection-guards.js`: colRepeatImportWarning
- `decklab/tests/test_collection_edit.py`: test_repeat_preview_is_same_space_exact_bytes_and_metadata_only, test_intentional_repeat_is_additive_and_records_the_repeat_in_the_audit_message
- `decklab/tests/test_collection_ops.py`: test_repeat_imports_match_exact_content_within_one_space_and_guard_the_reviewed_set

**E7-S05** · Matt · must · L · built

As a deck builder who bought a precon at the shop, I want its cards added and its list ready as a built deck in one step, so that I can play it tonight and its cards count as in use.

- Given a paper precon on MTGJSON, when I preview it from the Collection page's More > Add a precon…, then I see its cards as tiles, an editable deck title and its token cards.
- Given I add it, then its cards go into the space's collection (plain basics left out, condition and language blank) and a built deck is made, its table worked out with those cards added, in one change.
- Given a precon with an unmatched card or a list that breaks a new-deck rule, or a title whose deck name is taken, when I preview or add it, then it's refused with the reason and nothing is saved.
- Given Claude on the PC, when it runs `collection add-precon CODE`, then the same cards and deck are made as on the page, and `--dry-run` saves nothing.

Evidence:
- `decklab/web/collection.js`: openPreconSheet, drawPreconPreview
- `decklab/lib/api/precons.py`: precon_preview, add_precon, _precon_refused
- `decklab/db/inv_collection.py`: collection add-precon
- `decklab/tests/test_precons.py`: test_adds_the_cards_and_the_deck_in_one_change, test_refusals_change_nothing
- `decklab/tests/test_precon_cli.py`: test_the_same_deck_as_the_page, test_a_dry_run_previews_the_cards_and_the_deck_and_saves_nothing

**E7-S06** · Matt · could · M · partial

As a deck builder, I want a precon's token cards offered for adding when I add the precon, so that its decks' token needs are met without typing each token.

- Given a precon preview lists token cards, when I add it, then I can add them too as token rows marked for checking (printing and back unconfirmed).
- Given I skip them, then the deck page's Tokens part still shows them as not owned.

Evidence:
- `decklab/web/collection.js`: drawPreconPreview (its token cards 'aren't added: record them on the Tokens page')

Gap: there's no option to add the precon's token cards; the preview only names them and points to the Tokens page. The second criterion holds through the deck's Tokens part.

First slice: an "Add its token cards too" choice in the precon preview, adding each as a token row with printing and back unconfirmed, in the precon's one change.

**E7-S07** · Matt · must · L · built

As a player who grabs token cards for games, I want to record each physical token or reminder card with its real front and back, details and printing when known, so that Deck Lab can tell me which decks it serves and which tokens we lack.

- Given the Tokens page, when I add a card with Scryfall face names, then unknown details and printings stay blank and the front/back pairing is kept.
- Given a card that matches an existing row, when I add it, then I'm offered 'Add N to that card', and 'Keep it as a separate card' only when either row isn't fully known.
- Given a built or building deck (or, at home, an intact product) makes a token with no owned card, then it's listed under 'Tokens your decks make that you don't have'.

Evidence:
- `decklab/web/tokens.js`: drawTokens, showTokenSameRow, tokMissingPanel
- `decklab/lib/api/tokens.py`: tokens_view
- `decklab/lib/tokens/__init__.py`: gaps
- `decklab/db/inv_tokens.py`: tokens add|edit|remove
- `decklab/tests/test_api_tokens.py`: test_the_same_card_asks_first, test_known_cards_cant_be_kept_apart

**E7-S08** · Matt · could · M · missing

As a player packing for a game, I want each token's Tokens line to suggest how many of that token a game usually needs, so that I pack enough markers.

- Given a deck with recorded Forge games, when I open its Tokens part, then each token it makes shows a suggested count: the most of that token on the battlefield at once in a typical game of those runs, labelled as an estimate from Deck Lab's simulations.
- Given a deck with no Forge games, then no count is shown and the line says why.
- Given the suggested count is more than the matching token cards owned, then the line says how many more are needed (information, not a purchase).

Evidence:
- `decklab/lib/tokens/__init__.py`: gaps (needs from Scryfall's all_parts links, with no count)
- `decklab/lib/forge/cardlog.py`: tokens are left out of the per-card log

Gap: token needs come only from Scryfall's all_parts links, which give no count, and the Forge card log doesn't record tokens, so there's no source for a count yet.

**E7-S09** · Matt · must · M · built

As someone who has just changed the collection, I want one place listing every deck whose owned-vs-needed table is now out of date, with Update all, so that deck pages and the library stop showing wrong counts without opening each deck.

- Given a Collection page save or import left tables out of date, when it finishes, then the page says how many decks are out of date and links to the Decks page's Tables out of date list.
- Given the list, when I tap Update all, then every table I may change is refreshed with today's prices in one change; decks I can't change are said to wait for whoever plays them.
- Given a deck blocks the refresh (an unknown card, no table, no decklist), then the list names that deck and why and leaves it out of Update all; a space whose pool is incomplete gets a note that its tables wait until it's fixed.
- Given Receive delivery leaves tables it couldn't update, then its note links to the same list.
- Given a space's inventory I may not see, then none of its decks are listed.

Now: built 2026-10-13. Token cards never change a table, so the Tokens page leaves nothing out of date. The list has been checked in page tests, not yet on a phone.

Evidence:
- `decklab/web/library-tables.js`: libTablesPanel, staleTablesNote, tablesLaterNote, TABLES_HREF
- `decklab/lib/api/saving.py`: stale_view, update_tables
- `decklab/lib/inventory/refresh.py`: table_blockers
- `decklab/lib/api/collection_edit.py`: _stale_tables
- `decklab/tests/test_library_ui.py`: test_the_list_names_stale_and_blocked_decks_and_updates_all_in_one_change, test_an_incomplete_collection_holds_its_space_s_tables

**E7-S11** · Matt · should · S · built

As a player who sometimes sells or trades cards, I want to record why copies left the collection, for any reduction, so that the history shows sales and trades and not just disappearing cards.

- Given I remove a whole row on the Card list, when I confirm, then I can give an optional reason (with Sold and Traded as quick picks) that goes into the audit trail.
- Given I lower a quantity, when I save, then I'm asked for the same optional reason.
- Given the save meets a conflict and is retried, then the reason is kept.

Now: built 2026-10-15 ([HISTORY.md, Collection import and reduction guards](../HISTORY.md#collection-import-and-reduction-guards-2026-10-15)).

Evidence:
- `decklab/web/collection-guards.js`: colReasonControl, askCollectionReduction, colReductionReason
- `decklab/lib/api/collection_edit.py`: save_card
- `decklab/tests/test_collection_guards_ui.py`: test_reduction_quick_pick_and_optional_blank_reason
- `decklab/tests/test_collection_reduction_api.py`: test_confirmed_quantity_reduction_keeps_its_optional_audit_reason, test_confirmed_reduction_is_one_audited_change_with_its_reason

**E7-S12** · Matt · should · S · built

As a deck builder sharing one pool, I want to be warned when a card I remove or reduce is held by a built deck or an intact product, so that I don't leave a deck's records claiming a card that's gone.

- Given copies in use in a built deck or an intact product of the same space, when I remove or reduce a card below what's in use, then the sheet names the holders and suggests taking the cards out of the deck (or breaking up the product) first, and nothing is saved until I choose to continue.
- Given I still remove it, when I refresh its table from Tables out of date, then it shows the shortage.

Now: built 2026-10-15 ([HISTORY.md, Collection import and reduction guards](../HISTORY.md#collection-import-and-reduction-guards-2026-10-15)). Collection saves still don't refresh tables themselves (E7-S09).

Evidence:
- `decklab/lib/api/collection_guards.py`: reduction_warnings
- `decklab/lib/api/collection_edit.py`: _reduction_guard, save_card
- `decklab/web/collection-guards.js`: askCollectionReduction
- `decklab/tests/test_collection_reduction_api.py`: test_reduction_warns_with_holders_and_writes_nothing
- `decklab/tests/test_collection_guards_ui.py`: test_in_use_warning_names_decks_and_requires_an_explicit_override

**E7-S13** · User1 · must · M · built

As a player who shares the pool, I want to see which cards are free in storage and which are in decks, so that I can pick cards for my decks without asking Matt.

- Given I may see home's inventory, when I open the Collection page's Find cards, then each tile reads like '3 owned · 2 free' or 'all in decks'.
- Given the availability filter 'Free now', then only cards with free copies show.
- Given I'm one of home's people, then I can also change home's collection.
- Given someone views a collection that isn't their own space's (only once its owner has made it public), then it's read-only, without edit controls; a deck they can't see that holds cards is named only as "one of the home decks", and home's orders, receipts and Build decks stay refused.

Now: User1's edit rights in home's collection built 2026-10-18 ([HISTORY.md, Collections and tokens are seen only in their own space](../HISTORY.md#collections-and-tokens-are-seen-only-in-their-own-space-2026-10-18)).

Evidence:
- `decklab/web/collection.js`: colCountWords, COL_AVAILABILITY, colHead
- `decklab/lib/api/collection.py`: editable, collection_view
- `decklab/lib/permissions.py`: sees_inventory, SPACE_ACTIONS
- `decklab/tests/test_collection_assembly.py`: test_owned_free_held_and_incoming_are_distinct, test_availability_filters
- `decklab/tests/test_public_collection_games.py`: test_public_collection_is_read_only_for_admins_and_members, test_home_public_collection_keeps_records_private_and_holders_anonymous

**E7-S15** · Matt · could · M · partial

As a person filing new cards, I want after an import or merge a list of which new cards a deck is waiting for and which go to storage, so that I sleeve them into the right deck straight away.

- Given an import or a precon added, when it's applied, then a 'Where these go' list groups the new cards by the deck waiting for them, and the rest under storage.
- Given Receive delivery, then the same grouping shows after an arrival.

Evidence:
- `decklab/web/receipt-workflow.js`: rcptWhereTheyGo
- `decklab/web/collection.js`: drawImportPreview (the result is counts only), openPreconSheet (opens the new deck page)

Gap: only Receive delivery shows 'Where these go'. Imports, precon adds, single-card adds and `collection merge` don't.

**E7-S16** · Matt · should · M · built

As an admin, I want the data checked every night for broken rules and stale tables, so that I hear about drift before it misleads a deck page.

- Given the nightly task runs, then `db check` checks, in one snapshot, the accessories, every space's tokens, the orders and queue, the deck tables (stale ones as a warning), the decks' invariants and the export's files round trip, and records the run.
- Given a sub-check failed or the last check is old, then a warning shows at the top of the page to an admin only.
- Given I run `python -m decklab.db check --history`, then I see the recent runs.

Evidence:
- `decklab/db/check.py`: run, history
- `decklab/db/nightly.py`
- `decklab/lib/dbstatus.py`: checks_warning
- `decklab/web/version.js`: databaseMessages
- `decklab/tests/test_db_check.py`: test_a_consistent_database_passes_every_sub_check, test_stale_deck_tables_are_a_warning_not_a_failure

**E7-S17** · Claude Code · must · M · built

As the command-line operator, I want to add cards from a scan, trade or gift as one checked, audited change, so that bulk entry is safe and visible on Activity.

- Given a CSV in the collection's columns, when I run `collection merge FILE [--space S] -m "..."`, then every row and name is checked first and nothing is written if one fails.
- Given it succeeds, then the quantities are added on the identity key, the file is kept as a raw import and the change shows on Activity as Claude's (or the `--actor`'s).
- Given `--dry-run`, then it prints the per-printing additions, the skipped basics and the raw import it would keep, and saves nothing.

Now: `--dry-run` built 2026-10-18 ([HISTORY.md, Non-writing CLI merge, token and deck previews](../HISTORY.md#non-writing-cli-merge-token-and-deck-previews-2026-10-18)).

Evidence:
- `decklab/db/inv_collection.py`: _check_names, read_file, _merge
- `decklab/lib/inventory/ops_collection.py`: merge
- `decklab/tests/test_collection_ops.py`: test_merge_refuses_a_name_that_isnt_scryfalls

**E7-S18** · Matt · could · S · partial

As a person filling in old entries, I want to find rows with no condition or language and set several at once, so that the details get recorded in one sitting.

- Given the Card list, when I filter to rows whose condition or language isn't recorded, then only those show.
- Given a filtered set, when I choose one condition and language for the ticked rows, then they're saved in one change.

Evidence:
- `decklab/web/collection.js`: drawCollectionRows, colUnrecorded (the 'not recorded' filter)
- `decklab/web/receipts.js`: rcptFillBlanks (bulk fill on Receive delivery only)

Gap: the Card list's rows are edited one at a time; only Receive delivery has a bulk condition and language fill.

**E7-S21** · Matt · could · L · missing

As an owner of built decks in the shared pool, I want to check a built deck's box against its recorded list and note any card that's missing or extra, so that the records stay true to the physical decks after many swaps between games.

- Given a built deck, when I start a box check, then every card of its built list (every section) is shown as a picture tile with a tick, like Build decks.
- Given the check is finished, when a card wasn't found or an extra card was found, then it lists the differences and offers to fix the list or the collection, each as its own change.
- Given a box check is saved, when the deck page is opened, then it shows the date the box was last checked.
- Given a deck not checked for a long time, when the library is shown, then it can be filtered to decks due for a check.

Evidence:
- `decklab/web/assembly.js`, `decklab/web/assembly-progress.js`: Build decks' ticks are shared across devices but never change the inventory or record a check date

Gap: there's no way to reconcile a physical deck with its record, and no record of when a box was last checked.

First slice: a box check on Build decks (picture tiles with ticks over the built list) that lists what's missing or extra and saves the date checked; the fix-the-list offers come after.

**E7-S22** · Matt · could · M · missing

As a player who sometimes trades cards, I want to record a trade as one event, with the cards that left and the cards that came in, so that the history shows what a card was traded for, not an unrelated removal and a separate addition.

- Given the Collection page, when I record a trade, then I pick the owned cards that left and enter the cards that came in, in the collection's columns.
- Given a trade is saved, when the Activity page shows it, then it is one change set naming both sides and an optional who-with note, with no prices.
- Given cards that left are in a built deck, when the trade is previewed, then it warns which decks lose them.
- Given the trade is saved, when it finishes, then the deck tables are refreshed or the Tables out of date list names each affected deck.

Evidence:
- `decklab/web/collection-guards.js`: colReasonControl (Traded as a removal reason, E7-S11)
- `decklab/lib/api/collection_edit.py`: save_card (one card per change; no trade route)

Gap: E7-S11 records the reason on the removal side only; a trade is still an unlinked removal and a separate addition.

**E7-S23** · Matt · could · M · missing

As a player, I want the tokens a deck's cards make for the opponent listed apart from its own, so that I know which markers to hand across the table.

- Given a deck with a card whose rules text gives the opponent a token, when I open its Tokens part, then that token is listed under its own heading for the opponent.
- Given a token the deck's cards can make for either player, then it's listed with the deck's own and marked as possibly the opponent's.
- Given the library's token line and Build decks' Grab ticks, then the opponent's tokens are counted separately from the deck's own.

Evidence:
- `decklab/lib/tokens/__init__.py`: the note that some listed tokens appear only for the opponent; all_parts links don't say who gets the token

Gap: Scryfall's all_parts links don't say which player gets a token, so opponent tokens aren't told apart.

**E7-S24** · Matt · could · L · missing

As a player, I want our dice and counters recorded and checked against what decks need, so that I know whether we have enough for a game.

- Given the Tokens page, when I record dice or counters (kind, colour or design, quantity), then they're kept as their own owned items, separate from token cards.
- Given a deck whose cards use counters (such as +1/+1, loyalty or poison), when I open its Tokens part, then it lists the counter kinds it needs and whether owned dice or counters cover them.
- Given dice or counters are changed, then no decklist, playable pool or owned-vs-needed table changes.

Evidence:
- `decklab/lib/tokens/__init__.py`: token cards only; no dice or counters

Gap: dice and counters aren't recorded anywhere, and decks' counter needs aren't worked out.

**E7-S25** · Claude Code · should · S · built

As Claude Code, operating for Matt, I want to change one collection row's condition, language, notes or quantity from the command line, so that a fix Matt tells me about at the PC (such as sealed cards being NM) doesn't wait for him to open the Collection page.

- Given `collection edit SET NUMBER FINISH [--space S] [--condition C] [--language L] [--notes T] [--quantity N] --expect SHA -m "..."`, when the row exists and the collection hasn't changed since the listing that printed SHA, then only the given fields change, as one audited change; `""` clears a field.
- Given the collection changed since SHA, when I run it, then nothing is saved and it says to list again.
- Given `--dry-run`, then it prints the row before and after and the decks whose tables would go out of date, and saves nothing.
- Given a quantity change to 0, or a removal, then it needs a non-blank `--reason` (AGENTS.md: ask Matt why before removing sold or traded cards).
- Given an ordinary basic land, or a condition or language the merge rules don't allow, then it's refused with the same rules as the Collection page.
- Given a row in a member's space, then it's changed only when that member asked (directly or through Matt), as for `collection merge --space`.

Evidence:
- `decklab/db/inv_collection.py`: `_edit` (collection.edit / collection.remove, the page's `_text` and `match` checks, `reduction_warnings` as the in-use refusal, `--allow-in-use`), `_list`'s sha on stderr
- `decklab/tests/test_collection_ops.py`: CollectionEditCliTests

Built 2026-10-21. Raised 2026-10-20 when ten sealed Secret Lair lands merged with blank conditions had to be fixed on the page. A reduction below what built decks or intact products hold is refused unless `--allow-in-use` (the page's review step); changing a row's printing or finish stays the page's.

**E7-S26** · Claude Code · should · S · built

As Claude Code, operating for Matt or a space's owner, I want to change or remove many collection rows in one command and one change, so that a fix covering a whole precon or product (such as its cards' condition and language) is one audited change, not one `collection edit` a row.

- Given `collection apply FILE [--space S] --expect SHA -m "..."`, with FILE an edited copy of `collection list`'s output, when the collection hasn't changed since the listing that printed SHA, then every row whose quantity, condition, language or notes differs is changed, and every row at quantity 0 is removed, all as one audited change set.
- Given FILE leaves rows out (cut off, filtered or only a header), then nothing is saved and it says how many are left out, unless `--remove-missing` makes them removals too.
- Given FILE is the listing exactly as printed (Windows line endings or a byte-order mark included), when I run it, then it says there's nothing to change and saves nothing.
- Given a changed field, then it's checked as `collection edit` checks it (the page's text, formula and card checks, NM, LP, MP, HP or DMG, Scryfall's language codes, a quantity from 0 to 9999).
- Given a row whose identity key isn't in the collection, a changed name, a key listed twice or columns that aren't the collection's, then nothing is saved and it says why, pointing new cards to `collection merge`.
- Given removals, then saving needs a non-blank `--reason`; given reductions below what built decks or intact products hold, then saving is refused, listing each, unless `--allow-in-use`.
- Given `--dry-run`, then it prints the counts changed, removed and unchanged, each change and removal, the in-use warnings and the decks whose tables would go out of date, and saves nothing.

Now: built 2026-10-21 ([HISTORY.md, Many collection rows in one change](../HISTORY.md#many-collection-rows-in-one-change-2026-10-21-e7-s26)), after 89 `collection edit`s (89 change sets) set Matt's Hatsune Miku precon cards to NM and `en` that day.

Evidence:
- `decklab/db/inv_collection.py`: `_apply`, `_read_listing`, `_plan` (with `collection edit`'s `_field`, `_matched`, `_listed` and `_save`)
- `decklab/lib/inventory/ops_collection.py`: `apply_rows` (collection.apply: the edits and removals run as collection.edit and collection.remove, in one change)
- `decklab/tests/test_collection_ops.py`: CollectionApplyCliTests, PgCollectionApplyTests

**E7-S27** · Matt · should · S · built

As Matt, who keeps every card not in a deck unsleeved in the storage box, I want to see each collection row's estimated price and sort the Card list by it, most valuable first or cheapest first, so that I can find the expensive cards worth sleeving while they're in storage.

- Given the Card list, then each row shows ~A$ each: Scryfall's USD price of that row's own printing and finish (foil and etched priced as such, not the cheapest printing) converted at the ECB rate, with a note under the list saying it's an estimate, Scryfall's price date and the rate and its date.
- Given I tap the ~A$ each heading, then rows sort most valuable first; a second tap sorts cheapest first; rows Scryfall has no price for show a dash and stay last both ways; the sort is remembered like the other columns'.
- Given a save or an import, then the prices come back with the new rows; given no rate can be had, then the rows still show and the note says why there are no prices.
- Given a phone width, then the price stays a column of the list.

Now: built 2026-10-22 ([HISTORY.md, Prices on the Card list](../HISTORY.md#prices-on-the-card-list-2026-10-22-e7-s27)), after sorting the home collection by value from the PC to choose which storage cards to sleeve. The prices are read-only estimates for a row's copies; there's no collection total (no budget tracking). Which copies are in storage is E7-S28.

Evidence:
- `decklab/lib/api/collection_edit.py`: `_prices` (in `rows_view`, `save_card` and `merge_upload`'s answers)
- `decklab/web/collection.js`: `colPrices`, `colPrice`, `colShownRows`, `colPriceCell`, `drawColPriceNote`
- `decklab/tests/test_collection_edit.py`: test_rows_come_with_prices_of_their_own_printing_and_finish, test_without_a_rate_rows_show_and_say_why_there_are_no_prices
- `decklab/tests/test_collection_prices_ui.py`: test_price_sorts_most_valuable_first_then_reverses_with_unpriced_last, test_a_save_s_prices_replace_the_old_ones, test_a_conflict_s_rows_come_with_their_prices, test_without_prices_the_note_says_why

**E7-S28** · Matt · should · S · built

As Matt, who sleeves the valuable cards in the storage box, I want the Card list to show only the rows with copies in storage, and how many of a row's copies are in decks, so that sorted by price it's the list of storage cards to sleeve.

- Given the Card list, when I tick In storage only, then rows whose every copy is held by a built deck or a product kept intact are hidden; the label counts the rows left.
- Given a row with copies in decks, then under its copies it says "1 in a deck", "2 in decks" or "all in decks", counts only, never which decks.
- Given the decks hold a card in a printing their lists don't name and more than one row could be it, then the copies go to the cheapest rows and the note ends in "?", with a title saying it's a guess to check against the decks.
- Given a basic land row, then it's always listed, since basics in decks aren't tracked, and the note under the list says so while the filter is on.
- Given the decks can't be worked out, then the filter isn't offered and the rows still show.

Now: built 2026-10-22 ([HISTORY.md, In storage only on the Card list](../HISTORY.md#in-storage-only-on-the-card-list-2026-10-22-e7-s28)). On the live home collection 341 held copies were placed, one of them as a guess.

Evidence:
- `decklab/lib/pool.py`: `InUse.printings`, `_count_printings`
- `decklab/lib/api/collection_edit.py`: `_storage`, `_extras`
- `decklab/web/collection.js`: `colStorage`, `colHeld`, `colInStorage`, `colHeldNote`, `drawColRowList`
- `decklab/tests/test_collection_edit.py`: test_storage_counts_give_held_copies_to_named_printings_then_the_cheapest
- `decklab/tests/test_collection_prices_ui.py`: test_in_storage_only_hides_rows_whose_copies_are_all_in_decks, test_in_storage_only_is_offered_only_when_the_decks_could_be_read

**E7-S29** · Matt · should · S · built

As Matt, whose Card list has 91 rows with no condition or language recorded (nearly all English), I want to set a condition and a language on every row the list shows at once, so that I don't open 91 card sheets one at a time.

- Given the Card list with a search or filters (such as Condition or language not recorded), when I choose Set condition & language…, then the sheet acts on the rows shown, and says how many of how many.
- Given I choose a condition (NM, LP, MP, HP or DMG), a language, or both, then the sheet says what Save will do before I save ("Sets language English on 91 rows and condition NM on 60 rows; 31 already have a condition"); Leave as is leaves that field alone.
- Given Only fill in blanks is ticked (it is to start), then a row that already has that field keeps it; unticked, it's overwritten.
- Given some shown rows' notes say their merged copies had differing conditions or languages, then the sheet says how many, and notes are never changed; nor are quantities or names.
- Given I save, then it's one change in Activity ("edit 91 rows in the home collection"), the list redraws with the new rows, and rows already as asked aren't touched; given the collection changed meanwhile, then nothing is saved, the latest rows show, and the summary is worked out again for them, never for more rows than it was opened on.
- Given a phone width, then the button wraps with the toolbar's filters and the sheet is the shared sheet (full width on a phone); a viewer who can't change the collection doesn't see the button.

Now: built 2026-10-22 ([HISTORY.md, Condition and language on many rows](../HISTORY.md#condition-and-language-on-many-rows-2026-10-22-e7-s29)). The page's counterpart of `collection apply` (E7-S26).

Evidence:
- `decklab/lib/api/collection_edit.py`: `bulk_set`, `_bulk_keys` (POST /api/collection/bulk, one collection.apply)
- `decklab/lib/inventory/ops_collection.py`: `message` (collection.apply's words beforehand)
- `decklab/web/collection-bulk.js`: `colBulkButton`, `colBulkSync`, `colBulkPlan`, `colBulkWords`, `colBulkCleared`, `colBulkBusy`, `openBulkSheet`, `drawBulkSheet`, `saveBulk`
- `decklab/tests/test_collection_edit.py`: BulkTests
- `decklab/tests/test_collection_bulk_ui.py`: test_it_acts_on_the_shown_rows_and_says_what_save_will_do, test_save_posts_the_rows_it_changes_and_shows_the_answer, test_a_condition_and_overwrite_post_every_shown_row_and_lock_the_sheet, test_when_nothing_is_shown_after_a_save_the_search_keeps_the_focus, test_a_refresh_that_clears_a_filter_never_widens_it, test_a_refresh_that_leaves_nothing_shown_says_so, test_a_search_narrows_it_and_read_only_has_no_button, test_a_changed_collection_shows_the_latest_and_saves_nothing
- Not checked in a browser at a phone width: the button and sheet use the shared toolbar and sheet, which wrap and fill a phone's width

**E7-S30** · User5 · should · S · built

As User5, a member with my own space, I want to download my collection from the Collection page, so that my cards are mine to take to another app or keep as a backup.

- Given my own space's Collection page, when I choose Download (in its More menu), then I get a CSV in the collection's columns (name, set, collector_number, finish, quantity, condition, language, notes), sorted by set and collector number, named after the space and the date.
- Given a viewer who may not see that space's collection, then there's no Download and the request answers as the collection page does ("That collection isn't public.").
- Given the file, when it's imported back through the Collection page's import, then it reads as the collection columns.

Now: built 2026-10-25 ([HISTORY.md, Download a collection](../HISTORY.md#download-a-collection-2026-10-25-e7-s30)). Raised by the 2026-10-24 usage review, when export was command-line only.

Evidence:
- `decklab/lib/api/collection_edit.py`: `download_view` (GET /api/collection/download, guard.require_sees_inventory)
- `decklab/web/collection.js`: `downloadCollection`, `colHead` (More's Download collection (CSV))
- `decklab/tests/test_collection_edit.py`: DownloadTests
- `decklab/tests/test_inventory_privacy.py`: test_another_spaces_collection_and_tokens_answer_as_a_missing_space
- `decklab/tests/test_accounts_ui.py`: test_download_saves_the_spaces_collection_for_whoever_sees_it
- Not checked in a browser or on a phone: saving a Blob through a link's `download` is how the deck page's Download decklist already works

**E7-S31** · Matt · could · M · missing

As Matt, who keeps some products intact in their own box, I want an intact product to say which token cards it packs, as a built deck's Token cards line does, so that other decks don't count those cards as free and the product isn't told it has none.

- Given an owned product kept intact, when I choose its packed token cards (on its deck page, or `product set-tokens` on the PC), then they're saved with its sleeves and deck box as one change, and the space's other decks count them as in use.
- Given a product with packed token cards, when it's broken up, then they're freed in the same change, as its sleeves and deck box are.
- Given the Tokens page's Plan packed token cards, then intact products are planned with the built decks, each deck of a product getting its tokens from the product's cards.
- Given a product with no packed token cards, then the too-few warning still counts it as wanting one card of each row it uses, as now.

Evidence:
- `decklab/lib/tokens/__init__.py`: intact products count as holders for the warning only
- `decklab/lib/tokens/optimise.py`: plans built decks only ("not intact products, which have no line")

Gap: everything. Raised 2026-10-25, the follow-up left by the Token cards line (E4 token work, PRs #7 to #10).

First slice: a `token_cards` field in the product's status, read and written like its `sleeves` and `deck_box`, counted as in use, and cleared by a break-up.

---

## E8: Sleeves, boxes and storage

The physical side of home's shared pool: each built deck and each product kept intact is in one sleeve design and one deck box, every other card sits unsleeved in the storage box, and moving a card between decks means changing its sleeve. Deck Lab records the sleeves, deck boxes and playmats (each Matt's, User1's or shared) on the Sleeves & boxes page, a built deck's Sleeves and Deck box lines and an intact product's kit, warns when a holder has too few sleeves or a box that is full or too small, and lets one sleeve design sleeve several holders. Choosing a deck's kit needs the right to edit that deck; an owner may make their kit public (read-only), and members never see private kit. Accessory prices are not wanted.

Open: E8-S03, E8-S14, E8-S15, E8-S19.

**E8-S01** · Matt · must · M · built

As Matt, who owns several packs of sleeves, deck boxes and a playmat, I want to record each accessory I own once, with its picture, how many sleeves or boxes I have and how many cards a box holds, so that Deck Lab can tell me whether a deck's kit is enough without me counting by hand.

- Given a shop link, when I add a row on #/accessories and press Find picture, then the picture, kind, brand, name and sleeve count are guessed and I can correct them before saving.
- Given a deck box row, when I fill in Holds (sleeved cards), then the capacity is saved; for sleeves and playmats the field isn't offered.
- Given a used-up row, when I set its quantity to 0, then it stays for history; a deck box at 0 can't be chosen, and a sleeves row at 0 is shown as 'N sleeves short' and warned about in the kit.
- Given someone else saved the list since I opened it, when I save, then I get Load the latest and re-apply my changes or Discard, not a silent overwrite.

Evidence:
- `decklab/web/accessory-pictures.js`: findPicture; `decklab/web/accessories.js`: accApplyGuess, showAccessoryConflict, accTaken, kitChip
- `decklab/lib/accessory_fetch.py`: guess; `decklab/lib/api/accessories.py`: fetch_picture, save_accessory
- `decklab/lib/inventory/ops_accessories.py`: set_kit (a deck box at quantity 0 refused)
- `decklab/tests/test_api_accessories.py`: test_a_deck_box_capacity_is_saved_and_cleared_with_its_kind, test_a_changed_list_is_409_with_the_latest_view, test_a_deck_box_with_quantity_0_is_a_clear_409
- `decklab/tests/test_accessory_fetch.py`: test_og_image_relative_url_and_guesses

**E8-S02** · User1 · should · M · built

As User1, adding sleeves from her phone, I want to add a picture of a sleeve pack from my phone's photos or camera, so that I can record sleeves bought from a shop whose site blocks downloads, or sleeves I already have at home.

- Given the Add or Edit sheet, when I choose Photo from this device and save the row, then the picture is stored with the row in one change (JPEG, PNG or WebP, at most 4 MiB).
- Given a photo that is too large, unsupported or damaged, when I save, then I'm told why and neither the row nor its stored picture changes.
- Given I cancel, navigate away or switch person before saving, then the chosen photo is discarded and nothing is written.
- Given a stored photo, when I open the row, then I can crop it as with a fetched picture.

Now: built 2026-10-15 ([HISTORY.md, Product storage and device pictures](../HISTORY.md#product-storage-and-device-pictures-2026-10-15)), tested with synthetic photos; acceptance on the physical devices is E2-S22.

Evidence:
- `decklab/web/accessory-pictures.js`: local selection, preview and crop
- `decklab/lib/accessory_upload.py`: decode
- `decklab/tests/test_accessory_upload_ui.py`, `decklab/tests/test_api_accessory_upload.py`

**E8-S03** · Matt · could · S · missing

As Matt, opening Sleeves & boxes on the phone in a shop, I want the list to load quickly, so that I can check what sleeves I have before buying more.

- Given the accessories list, when it opens on a phone, then each tile loads a small thumbnail rather than the full picture.
- Given a tile, when I open it, then the full picture is shown.

Evidence:
- `decklab/web/accessories.js`: accessoryThumb (shows the row's one stored picture)
- `decklab/lib/api/accessories.py`: image_file (serves the one stored picture, no size option)

Gap: there are no thumbnails; tiles, the picker and the deck page all load the full picture. The need has no budget (bytes or seconds on a phone) to test against.

**E8-S04** · User1 · must · M · built

As User1, who has her own sleeves and boxes, I want my accessories to be mine, seen and changed only by me, with some shared ones we both use, so that my things stay my own even though Matt is the admin.

- Given a row owned by user1 and her kit is private, when Matt opens #/accessories, then her row isn't listed.
- Given that row, when Matt asks for its picture, then he gets 404.
- Given a deck whose kit is User1's, when Matt sees anything that names it as a holder, then it is named only as 'one of User1's decks' (and Matt's to her as 'one of Matt's decks').
- Given User1 makes her kit public, when Matt opens #/accessories, then he sees her rows read-only and can't change, crop or choose them.
- Given a shared row, when either of us opens the page, then both see and may change it.
- Given a deck Played by wife, when its sleeves are chosen, then only User1's and shared rows are offered.
- Given User1 changes a row, when Activity is read, then the change is attributed to her and the row shows only to its owner.

Now: on the home network Matt and User1 are told apart by the profile picked on the page, not a login (E10-S35).

Evidence:
- `decklab/lib/permissions.py`: accessory_owners, accessory_readers
- `decklab/lib/accessories.py`: visible, usable, hidden_title
- `decklab/lib/api/accessories.py`: image_file
- `decklab/tests/test_api_accessories.py`: test_a_picture_is_its_owners, test_shared_sleeves_name_a_hidden_holder_only_as_theirs
- `decklab/tests/test_public_accessories.py`: test_read_only_rows_cannot_be_saved_assigned_or_have_pictures_staged; `decklab/tests/test_activity.py`: test_an_accessory_row_is_its_owners_only_admins_included

**E8-S05** · User1 · must · M · built

As User1, who has finished putting one of her decks together, I want to choose its sleeves and deck box from my phone, so that the deck records the kit it's actually in, without needing the iPad or the PC.

- Given a built deck I may change, when I tap Choose… under Sleeves on its Overview, then a picker shows my and shared designs with '75 needed · 100 owned · 25 spare' or 'N short'.
- Given a deck that isn't built, when I open its Overview, then it says sleeves and a box are chosen when it's marked built.
- Given I pick a deck box, when its capacity is smaller than the deck, then the tile says 'Too small: holds 80' as a warning, not a refusal.
- Given I save, then the deck text's Sleeves and Deck box lines hold accessory ids and the change is one revision.
- Given a built deck, when I set its status back to building or idea and save it on the page, then its Built version, Sleeves and Deck box lines are removed and its kit is free again.

Evidence:
- `decklab/web/deck.js`: deckKit, deckKitTile; `decklab/web/accessories.js`: kitChip, drawKitPicker
- `decklab/lib/api/accessories.py`: assign_accessory; `decklab/lib/api/drafts.py` (kit lines cleared when a deck is taken apart)
- `decklab/tests/test_deck_kit_ui.py`: test_an_unbuilt_overview_explains_when_and_where_kit_is_chosen, test_the_sleeve_picker_shows_spare_zero_and_short_after_this_decks_need
- `decklab/tests/test_assembly_sections_safeguards.py`: test_take_apart_clears_only_physical_state_and_rebuild_installs_a_new_generation

**E8-S07** · Matt · wont · S · not_wanted

As Matt, sharing a pool with User1, I want every built deck and intact product to have its own sleeve design and colour, so that cards that end up on the wrong side of the table can be sorted by their backs.

- Given a design held by another built deck, when I open the picker, then it shows 'In use: X' and can't be chosen except by moving it.
- Given two holders whose sleeves share a colour, then each shows a warning and `accessories check` reports it.

Decided (Matt, 2026-10-13): one sleeve design may sleeve several decks, and it's up to the players not to play both at once. E8-S20 replaces this story; its Used by line still leads a stray card's back to its possible decks.

**E8-S08** · Matt · could · S · built

As Matt, I want to move a sleeve design from one deck to another in one step, when I'm taking the sleeves off the other deck rather than sharing them, so that re-sleeving a deck is recorded in one change.

- Given a design held by another deck I may change, when I choose Move them here (or Take them from X when several holders could give them), then this deck gets it and the other loses it in one change.
- Given the other holder is a deck I may not change (another owner's, or an 'either' deck for User1), then no move is offered, it's named only as I may see it, and a forced request is refused with 403.
- Given the other deck no longer holds the design when I move it, then nothing is taken from it; given this deck was saved meanwhile, then the move is refused naming who changed it.

Now: since 2026-10-18 a move needs the right to edit both decks ([HISTORY.md, Choosing a deck's kit needs deck.edit](../HISTORY.md#choosing-a-decks-kit-needs-deckedit-2026-10-18)).

Evidence:
- `decklab/web/accessories.js`: pickKit
- `decklab/lib/api/accessories.py`: assign_accessory (move_from)
- `decklab/lib/inventory/ops_accessories.py`: set_kit (a change with expect applies only while the holder still holds that design)
- `decklab/tests/test_api_accessories.py`: test_move_from_clears_the_old_holder_in_the_same_change, test_a_refused_move_changes_neither_holder, test_moving_sleeves_off_a_deck_she_cant_edit_is_refused

**E8-S09** · Matt · must · S · built

As Matt, keeping a product intact, I want a product kept intact to have one sleeve design and one deck box, like a built deck, so that its cards stay out of the pool and its kit is counted like any other deck's.

- Given an owned product kept intact, when I open Products kept intact on #/accessories or the product's deck page, then I can Choose… its sleeves and deck box.
- Given its sleeves, then the need is the total of all its decks.
- Given a product that isn't owned and intact, when I try to give it sleeves, then it's refused ('Only a built deck or a product kept intact has sleeves or a deck box').
- Given an intact product, then only shared accessories are offered, and its design may also be one a built deck uses.

Evidence:
- `decklab/web/accessories.js`: accProductsPanel; `decklab/web/deck.js`: deckKitTile
- `decklab/lib/accessories.py`: _product_sections, kit
- `decklab/lib/inventory/kit.py`: can_hold; `decklab/lib/inventory/ops_accessories.py`: CANT_HOLD
- `decklab/lib/api/guard.py`: holder_owner
- `decklab/tests/test_accessories.py`: test_owned_intact_products_hold_their_columns, test_a_product_deck_counts_its_whole_product

**E8-S10** · Matt · wont · M · not_wanted

As Matt, with a product that holds several decks, I want each deck inside an intact product to have its own sleeves, so that two decks from one product can be played against each other without mixing their cards.

- Given an intact product with two decks, when I choose sleeves, then I can choose per deck.
- Given per-deck sleeves, then each deck's need is its own card count.

Decided (Matt, 2026-10-13): one sleeve design may sleeve several decks and it's up to the players not to play both at once, so one design and one deck box cover the whole product.

Evidence:
- `decklab/lib/inventory/kit.py`: FIELDS (one sleeves and one deck box per product)
- `decklab/lib/accessories.py`: _product_sections (all its decks make one need)

**E8-S11** · Matt · should · M · built

As Matt, I want to decide on the page whether an owned product stays intact or is broken up into storage, also after it arrived, so that its cards become free for other decks when I stop playing it as a product, without asking Claude.

- Given a product delivery, when I receive it on #/receipt, then I choose Keep it as its own deck(s) or Break it up into storage.
- Given an owned intact product, when I choose Break up on its deck page's Product storage panel and confirm the preview, then it becomes intact no, its sleeves and deck box are cleared and the deck tables refresh, in one change.
- Given an owned broken-up product with deck lists, when I choose Keep intact and confirm, then its existing collection copies count as in use.
- Given the inventory or decks changed after the preview, when I confirm, then I'm asked to review again.
- Given another owner's private kit on the product, then neither choice can clear or reactivate it.

Now: built 2026-10-15 ([HISTORY.md, Product storage and device pictures](../HISTORY.md#product-storage-and-device-pictures-2026-10-15)).

Evidence:
- `decklab/web/product-storage.js`: productStorageSection, openProductStorage
- `decklab/lib/api/products.py`: preview_storage, apply_storage
- `decklab/tests/test_product_storage.py`: test_break_preview_matches_shared_operation_without_writing_then_saves_once, test_keep_intact_reserves_cards_without_adding_to_collection_or_restoring_old_kit, test_private_old_kit_is_masked_and_admin_cannot_clear_it
- `decklab/tests/test_product_storage_ui.py`

**E8-S14** · Matt · could · S · missing

As Matt, taking a built deck apart, I want one list of every card to unsleeve and return to storage, with the sleeves and box to put away, so that nothing is left in the box.

- Given a built deck I'm taking apart, when I open its take-apart checklist on Build decks, then it lists every card in the deck to unsleeve and put back in storage.
- Given that checklist, then it also names the sleeves and deck box to put away.

Evidence:
- `decklab/web/assembly.js` (the Put back step covers only cards a chosen list stopped using)

Gap: there is no whole-deck take-apart checklist. Clearing the kit lines when a deck is unbuilt is in E8-S05, and `deck delete`'s refusal in E8-S18.

First slice: a Take apart checklist on Build decks for a built deck: every card in every section, then its sleeves and deck box.

**E8-S15** · Matt · could · S · partial

As Matt, I want a built deck's sleeves to follow when the deck changes hands between me and User1 (or becomes 'either'), so that the deck isn't left using sleeves its new player can't see or change.

- Given a built deck in Matt's sleeves, when Matt saves it with Played by changed and the sleeves left as they are, then nothing is saved: to 'either' it's 400 naming whose sleeves they are, and to wife it's 403, as User1's kit is hers to choose.
- Given an editor who can't see a built deck's kit, when they change its Played by, then it's 403 without naming the kit's owner.
- Given that refusal, then the same step offers to choose the new player's or shared sleeves, to clear them, or to let the sleeves' owner hand them on, so the change of player can go ahead.

Evidence:
- `decklab/lib/api/saving.py`: _require_kit_moves
- `decklab/lib/api/guard.py`: require_kit_choice
- `decklab/lib/accessories.py`: _not_theirs (the warning for kit written outside the page)

Gap: the third criterion. Nothing offers new sleeves when Played by changes; whether one editor save can already change Played by and Sleeves together, and how the page presents that, wasn't verified.

**E8-S16** · Space members · should · S · built

As User2, with his own space, I want the household's sleeves and boxes kept out of my pages, so that I see only what applies to me.

- Given User2 signed in through decklab.example.com and home's kit owners keep their kit private, when he opens #/accessories or an /accessory-img/ picture, then he gets 403 naming no one.
- Given an owner has made their kit public, then he sees it read-only and can't change or choose it.
- Given he opens any deck page, the library, the editor or history, then no Sleeves, Deck box or kit warnings appear.
- Given his own deck, when he saves it, then a Sleeves or Deck box line can't be added.
- Given a home-network request names User2 (header, ?profile=, ?viewer= or a body's profile), then it gets 403 'Sign in through decklab.example.com'.

Now: members are refused at home since 2026-10-18 ([HISTORY.md, Only scripts read everything](../HISTORY.md#only-scripts-read-everything-and-the-home-chooser-offers-home-profiles-2026-10-18)); public kit is E10-S33 ([HISTORY.md, Public readers](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)).

Evidence:
- `decklab/lib/permissions.py`: accessory_owners, sees_accessories
- `decklab/lib/api/guard.py`: require_sees_accessories, hide_kit
- `decklab/lib/server_http.py`: _home_only, _accessory_image
- `decklab/tests/test_script_rule.py`: test_a_member_named_at_home_is_sent_to_decklab_example
- `decklab/tests/test_public_accessories.py`: test_reader_helpers_do_not_widen_write_helpers_even_for_an_admin

**E8-S18** · Claude Code · should · S · built

As Claude Code, working for Matt at the PC, I want typed commands to list, check, add, edit and remove accessories and pictures, and to set any holder's kit, so that I can make kit changes safely without SQL or files.

- Given `accessories list` printed a sha, when I run `accessories edit ID --expect SHA -m`, then a list changed since is refused.
- Given a removal, when I omit `--reason`, then it's refused; a row a holder uses can't be removed.
- Given `accessories check`, when a rule is broken, then it prints each problem and exits 1.
- Given `product kit STEM` printed a sha for an owned intact product, when I run `product set-kit STEM --expect SHA` with one or both kit choices and a nonblank `-m`, then those choices save in one change, `none` clears one, an omitted one stays, and a stale sha is refused.
- Given a deck holding sleeves or a deck box, when I run `deck delete`, then it's refused until the deck is unbuilt.

Evidence:
- `decklab/db/inv_accessories.py`: _check, _write, expected
- `decklab/db/product_kit.py`: show, save
- `decklab/tests/test_inventory_accessories.py`: test_a_token_is_the_viewers_and_a_stale_one_refuses, test_a_used_row_cant_be_removed_change_kind_or_owner
- `decklab/tests/test_product_kit_cli.py`: test_set_both_then_clear_one_preserves_omitted_field_and_other_data, test_short_prefix_and_uppercase_work_but_stale_or_malformed_tokens_do_not
- `decklab/tests/test_inventory_decks.py`: test_delete_refuses_a_built_deck_with_a_kit

**E8-S19** · Matt · could · S · missing

As Matt, I want to know roughly how full the storage box is, so that I know before an order whether the unsleeved cards will still fit in the 4-row box (about 2,400 cards).

- Given home's collection and the cards in built decks and intact products, when I open the Collection page, then it shows how many cards are in storage against the box's capacity.
- Given storage is over capacity, then it says so in plain words.

Gap: nothing counts the cards in storage or records the box's capacity. Which cards count (plain basics, tokens) isn't defined yet.

**E8-S20** · Matt · must · M · built

As Matt, with more decks than sleeve designs, I want several built decks and intact products to use the same sleeves row, so that I can sleeve decks in the sleeves we have, and it's up to us not to play two decks in the same sleeves against each other.

- Given a built deck, when I open the Sleeves picker on the deck page or in the editor, then a design other holders use can be chosen as it is, and its tile names those holders ('Also used by X', or 'one of User1's decks' for a holder I can't see).
- Given I choose a design another holder already uses, on the deck page, in the editor or on Finish building, when I pick it, then I'm warned first ("Use X here too?", naming the other holders, a hidden one as "one of User1's decks") and it's saved only if I confirm; both holders then keep it in one change.
- Given `deck push`, `deck new` or `product set-kit` gives a holder a design another holder already uses, when it saves (or previews), then it's accepted and prints a warning naming the other holders.
- Given two holders in the same sleeves, or with the same sleeve colour, when `accessories check` or a deck's kit warnings run, then neither is reported as a problem, and the deck page's Sleeves tile names the other holders plainly ("Also sleeves X").
- Given a sleeves row used by several holders, when its count is checked, then each holder is checked against the row's quantity on its own, not the sum.
- Given a sleeves row on #/accessories, when I look at it, then its Used by line lists every holder, so a stray card's back still leads to its possible decks.
- Given two decks in the same sleeves are both chosen on Build decks, when the plan shows, then it notes that they share sleeves, as a note and not a block.

Decided (Matt, 2026-10-13): one sleeve design may sleeve several decks; it's up to the players not to play both at once. Deck boxes keep their quantity rule. (Matt, 2026-10-19): choosing kit already in use warns; a deck box with a spare one free doesn't.

Now: the warning when choosing shared sleeves, and the deck page's "Also sleeves" line, were added 2026-10-19 ([HISTORY.md, Warn when sleeves already in use are chosen](../HISTORY.md#warn-when-sleeves-already-in-use-are-chosen-2026-10-19)).

Evidence:
- `decklab/lib/inventory/ops_accessories.py`: set_kit
- `decklab/lib/accessories.py`: kit, check
- `decklab/web/accessories.js`: accTaken, accTakenWords, pickKit, accCard, accDetails
- `decklab/web/editor-details.js`: pickKitTile; `decklab/web/deck.js`: deckKitTile
- `decklab/db/inv_decks.py`: _sharing_warnings; `decklab/db/product_kit.py`: save (both via accessories.sharing_warning)
- `decklab/lib/api/assembly.py`: _sleeve_notes
- `decklab/tests/test_accessories.py`: test_shared_design_is_counted_per_holder, test_same_colour_different_design_is_no_warning; `decklab/tests/test_assembly_kit.py`: test_shared_sleeves_can_be_chosen_for_both_decks; `decklab/tests/test_editor_contracts.py`: test_sleeves_another_deck_uses_are_warned_about_before_they_are_chosen

---

## E9: Commander nights

Getting the household's Commander decks ready for social Commander nights at a local shop, where staff make 4-player pods and the shop publishes a bracket range. The editor checks the Commander deck rules and a minimum bracket from Game Changers, mass land denial and extra turns; a Commander deck's Overview opens with a plain bracket sentence, what opponents will face and the dates of the card data behind them, and home admins can record the usual night's aim and house rules. Practice games use the free multiplayer mulligan, and Forge plays Commander decks 1v1 only, marked indicative. Two-card combos (from Commander Spellbook) and Wizards' latest Commander announcement are checked too (2026-10-21). Still open: 4-player pods on the page, EDHREC ideas, and pod games in the Game log.

Open: E9-S07, E9-S11, E9-S16, E9-S21, E9-S22.

**E9-S02** · Matt · must · M · built

As a deck builder, I want to know straight away when my list breaks a Commander deck rule, so that the deck I bring is legal for the night.

- Given a Commander draft, when it isn't exactly 100 cards with the commander, then the Checks panel says how many it has.
- Given a second copy of a non-basic card, when the draft is checked, then it names the card, unless the card's own text allows more copies.
- Given a card outside the commander's colour identity or on the Commander ban list, when the draft is checked, then that card is named.
- Given two commanders without matching partner abilities, or a commander that can't be one, when the draft is checked, then it says why.
- Given any of these, when I save, then the save goes ahead (warnings, not blocks).

Evidence:
- `decklab/lib/stats/commander.py`: _commander_checks, _copies_allowed, _can_be_commander, _partners
- `decklab/lib/api/drafts.py`: _rule_warnings
- `decklab/lib/api/editor.py`: check_draft (POST /api/deck/check)
- `decklab/web/stats.js`: commanderPanel
- `decklab/tests/test_stats.py`: TestCommander (test_size_counts_commander_not_companion, test_singleton, test_colour_identity, test_ban_list), TestCommanderPairs

**E9-S03** · Matt · must · M · built

As a player aiming at a social bracket, I want to see the lowest bracket my list fits and what pushes it up, compared with the bracket I'm aiming at, so that I bring a deck that matches the pod's power.

- Given a Commander deck, when I open its Stats tab, then I see 'Minimum bracket' with the Game Changers, mass land denial and extra-turn cards behind it.
- Given the list's minimum bracket is above the Target bracket, when I edit it, then the Checks panel warns and names the cards involved.
- Given Scryfall's oracle tags can't be read, when the check runs, then it says mass land denial and extra turns weren't counted.
- Given the deck page head, when the deck has a target bracket, then the facts line shows 'Bracket N'.

Decided (Matt, 2026-10-13): the household aims for Bracket 2 at Commander nights, which matches the Target bracket 2 a new Commander deck starts with (E2-S01).

Evidence:
- `decklab/lib/stats/commander.py`: min_bracket, _commander_checks
- `decklab/lib/api/drafts.py`: _rule_warnings (the Target bracket warning)
- `decklab/web/stats.js`: commanderPanel
- `decklab/web/deck.js`: deckHeadMeta
- `decklab/tests/test_stats.py`: test_bracket, test_min_bracket_thresholds

**E9-S04** · Claude Code · should · S · built

As the operator recommending Commander cards, I want Deck Lab's Game Changers and ban-list checks to show the date of the card data they used and to warn when it's old, so that I know when to check the live lists before trusting them.

- Given the local card or tag data is more than 7 days old, or its date is unknown or in the future, when a Commander deck is checked, then the Overview and the Stats tab's Commander rules say the checks may be out of date and give the dates.
- Given the bracket panel, when it lists Game Changers, then it shows the date of the Scryfall card data used (which covers Game Changers and the ban list) and the date of the community effect tags.
- Given a check runs, then it uses the loaded data only, without fetching or rebuilding anything.

Decided (Matt, 2026-10-19): checking a recommended card against live Scryfall is Claude's workflow (AGENTS.md's accuracy rules), not Deck Lab's; knowing when the official lists change is E9-S24.

Now: Built 2026-10-15 ([HISTORY.md, Commander pregame summary and card-data dates](../HISTORY.md#commander-pregame-summary-and-card-data-dates-2026-10-15)).

Evidence:
- `decklab/lib/stats/commander.py`: _data_dates, _source_date
- `decklab/lib/cards.py`: MAX_BULK_AGE
- `decklab/web/commander-readiness.js`: commanderDataNote; `decklab/web/stats.js`: commanderPanel
- `decklab/tests/test_commander_readiness.py`: test_old_source_data_is_stale_even_when_the_other_source_is_fresh, test_missing_and_invalid_source_dates_are_unknown_and_stale, test_future_source_dates_are_displayed_but_not_trusted_as_fresh
- `decklab/tests/test_commander_readiness_ui.py`: test_data_freshness_and_unknown_dates_are_visible_in_both_panels

**E9-S05** · User1 · should · S · built

As a beginner bringing a Commander deck to a social night, I want my deck's bracket in one plain sentence I can say at the table, so that I can answer 'what bracket is your deck?' honestly without knowing the rules in detail.

- Given a Commander deck, when I open it, then the Overview's first section shows a sentence such as 'Aims for Bracket 2: no Game Changers, extra turns or mass land denial found.'
- Given the deck has cards that raise its bracket, when I read the sentence, then it names them and says the lowest bracket they need when that's above the aim.
- Given the card checks are incomplete (no tag data, cards without data), when I read the sentence, then it never gives an all-clear.
- Given things Deck Lab can't judge (combos, speed, intent), when I read the section, then a short note says they aren't checked and that the card checks alone don't establish a bracket.

This story covers the one-line sentence; E9-S06 covers the per-effect list.

Now: Built on the page 2026-10-15 ([HISTORY.md, Commander pregame summary and card-data dates](../HISTORY.md#commander-pregame-summary-and-card-data-dates-2026-10-15)). Whether it shows without scrolling on a real iPhone is checked with E2-S22.

Evidence:
- `decklab/web/commander-readiness.js`: commanderReadiness
- `decklab/tests/test_commander_readiness_ui.py`: test_clean_summary_is_first_and_distinguishes_aim_from_certification, test_named_raising_cards_and_effects_open_the_existing_viewer, test_missing_tags_and_unknown_names_never_get_an_all_clear_sentence, test_no_target_and_cedh_aim_are_not_invented_classifications

**E9-S06** · Commander table · should · M · built

As a player at the pod facing a stranger's deck, I want to be told before the game about anything un-fun in their deck (Game Changers, mass land denial, extra turns), so that the game is the one I expected at a social bracket.

- Given a Commander deck page, when it has Game Changers, mass land denial or extra-turn cards, then they are listed under 'What opponents will face' in plain words, and the section opens by itself.
- Given none of these is found, when the section shows, then it says none was found among the checked cards; given the effect data couldn't be read, it says that effect wasn't checked.
- Given the section, then it says what isn't checked (combos, speed, intent) and that community tags can miss or over-flag cards.

Two-card combos are E9-S23.

Now: Built 2026-10-15 ([HISTORY.md, Commander pregame summary and card-data dates](../HISTORY.md#commander-pregame-summary-and-card-data-dates-2026-10-15)).

Evidence:
- `decklab/web/commander-readiness.js`: commanderReadiness
- `decklab/lib/stats/commander.py`: _commander_checks
- `decklab/tests/test_commander_readiness.py`: test_missing_tags_never_claim_no_tagged_effects, test_known_effects_keep_existing_lists_and_minimum
- `decklab/tests/test_commander_readiness_ui.py`: test_named_raising_cards_and_effects_open_the_existing_viewer

**E9-S07** · Matt · could · L · missing

As a newer player choosing cards for a commander, I want to see what is commonly played with my commander, marked owned, free or to buy, so that I fill the 99 from proven ideas, starting with the pool I already have.

- Given a Commander deck in the editor, when I open its ideas, then I see the commander's commonly played cards from EDHREC with the date they were fetched.
- Given an idea I own a free copy of, when it's listed, then it says so and adds to the deck in one tap.
- Given EDHREC can't be reached, when I open the ideas, then the page says so and the rest of the editor works.

Evidence:
- `decklab/web/editor-cards.js`: the Add panel offers search and My collection only

Gap: there's no EDHREC fetch or ideas panel; EDHREC appears in Deck Lab only as a cited source.

**E9-S08** · Matt · must · M · built

As a deck builder working from the shared pool, I want to see the cards I own that fit my commander's colours and aren't held by another deck, so that I build from the pool first and buy only to fill gaps.

- Given a Commander deck in the editor, when I open My collection, then it lists free cards within the commander's colour identity.
- Given the finder's colour filter, when I set it, then results are cards whose colour identity is within those colours.
- Given a card held by another built deck or an intact product of the same space, when the deck page's Cards tab shows it to a viewer who may see that space's inventory, then it's marked 'in <deck>'.

Evidence:
- `decklab/web/editor-cards.js`: deckColours
- `decklab/lib/api/editor.py`: find_cards (scope owned), _fits
- `decklab/web/deck.js`: CARD_FILTERS ('held'), markChips
- `decklab/tests/test_editor_writeup.py`: test_my_collection_lists_free_copies_in_the_decks_colours

**E9-S09** · Matt · should · S · built

As a player new to multiplayer, I want to practise Commander opening hands with the free first mulligan and see how the mana holds up, so that I know when to keep a hand at the table.

- Given a Commander deck's Practice tab, when I deal a hand, then the commander stays out of the library and the first mulligan is free.
- Given practice games, when they finish, then a Multiplayer setup shows the mulligan rate, land drops and colour sources.
- Given the Stats tab, when it counts colour sources, then it uses the 99-card tables with multiplayer rules.

Evidence:
- `decklab/web/hands.js`: manualHandsSection
- `decklab/lib/goldfish/common.py`: SETUPS, SETUPS_BY_KIND
- `decklab/web/practice.js`: mulliganPanel, landDropPanel, practiceColourPanel
- `decklab/lib/stats/colourcheck.py`: _colour_check
- `decklab/tests/test_goldfish.py`: test_commander_free_mulligan_only_in_multiplayer; `decklab/tests/test_stats.py`: test_commander_uses_the_99_card_table

**E9-S10** · Matt · could · M · built

As a deck builder, I want to compare my Commander deck's strength with the household's other Commander decks in 1v1, so that I can tell whether it's roughly as strong as they are.

- Given two Commander decks, when I play a matchup, then Forge plays them as 1v1 Commander and the result says Commander results are indicative only.
- Given a home Commander deck, when I open Against the field, then it is rated against the home Commander decks.
- Given Forge's AI never casts a deck's commander, when the result shows, then it says the result means nothing for that deck.

Pods and bracket fit are E9-S11 and E9-S21.

Evidence:
- `decklab/web/matchups-results.js`: COMMANDER_WORDS, trustPart, caveatLine
- `decklab/lib/forge/field.py`: _field
- `decklab/tests/test_matchups_api.py`: test_commander_decks_play_commander_decks

**E9-S11** · Matt · could · L · missing

As a player going to 4-player pods, I want to start a run of 4-player Commander games from the page against decks of a similar bracket, so that I see how my deck keeps up at the table it will actually sit at.

- Given four Commander decks I may see (my space's, or a public space's) with similar target brackets, when I start a pod run, then Forge plays pods with the seats rotated between batches.
- Given a pod run is going, when I look at the page, then its progress shows in the Forge playing pill.

Evidence:
- `decklab/lib/forge/cardlog.py`: SEATS (only two seats are read)
- `decklab/forge-trial/overnight_pods.py`: a prototype outside the page

Gap: nothing in `decklab/lib/forge` or the pages runs pods (PLAN.md, Still to do).

**E9-S12** · Matt · should · S · built

As a buyer planning a Commander deck I'll build later, I want its cards kept as a long-term buying plan, so that any shop order can be topped up with them to share postage.

- Given Claude adds the deck's buys with `watchlist set --add --state long_term`, when I open #/shopping, then they show under Long-term plan grouped by deck.
- Given the deck becomes the next one to build, when Claude promotes its rows to ready, then they move to To buy.
- Given an order fulfils queued rows, when it's recorded with `--fulfils`, then the rows drop in the same change.

Evidence:
- `decklab/web/shopping.js`: SHOPPING_STATES, SHOP_QUEUE_STATES, shopQueueRow
- `decklab/lib/inventory/orders.py`: add_order, _fulfil
- `decklab/tests/test_shopping_ui.py`: test_decks_still_missing_cards_and_the_long_term_plan
- `decklab/tests/test_order_fulfilment.py`

**E9-S16** · User1 · could · M · missing

As a player back from a Commander night, I want to note how my deck did in each pod, against which commanders, so that we remember what worked and change the deck with the table in mind.

- Given the Game log, when I record a pod game, then I can enter up to four players, the commanders faced (opponents without a Deck Lab deck included) and who won.
- Given recorded pod games, when I open my deck's Game log, then they show apart from 1v1 games at home.
- Given a pod record, when it's saved, then it's one change set in Activity by me, seen only in my space unless the Game log is public.

Evidence:
- `decklab/lib/api/play_records.py`: _checked (a game has exactly two sides, each a Deck Lab deck)
- `decklab/web/play.js`

Gap: only 1v1 games between two Deck Lab decks can be recorded (of one space or two).

**E9-S17** · Space members · could · S · built

As an experienced space member with my own Commander deck, I want to see my deck's Commander checks and bracket, and the household's Commander decks when they're shared, so that games against home's decks and shop nights use decks of similar power.

- Given my deck in my space, when I open its Stats tab, then I see the Commander rules and the minimum bracket.
- Given home has made its decks public, when I open a home Commander deck, then I see its list, stats and bracket but not home's owned or missing counts while home's collection is private.
- Given home's decks are private (the default), when I open a home deck, then it answers as a missing deck.
- Given my deck, when a Commander matchup or field run has been played, then I can read the result; my field is my own space's decks plus public spaces' decks.

Evidence:
- `decklab/lib/permissions.py`: sees_deck, sees_inventory
- `decklab/lib/api/guard.py`: public_deck_spaces, sees_deck
- `decklab/lib/forge/field.py`: _field
- `decklab/tests/test_deck_visibility.py`: test_a_member_gets_only_his_own_decks, test_the_switches_extend_it_with_one_set
- `decklab/tests/test_field_privacy.py`: test_members_field_has_own_and_public_spaces_but_home_field_does_not_auto_add_them

**E9-S18** · Matt · wont · XL · not_wanted

As a player aiming at fun at a social table, I want a measure of whether my deck is fun to play against, so that I could tune for the table's enjoyment, not only for winning.

- Given a Commander deck, when the measure is shown, then it says what it is based on and that it's a guide, not a verdict.

Decided (Matt, 2026-10-19): not wanted: 'fun' has no testable measure, and the bracket sentence and What opponents will face (E9-S05, E9-S06) cover the pregame conversation.

**E9-S20** · Matt · could · M · built

As a player heading to a Commander night, I want to note the bracket we're aiming for at the night and any shop house rules, and see them on our Commander deck pages, so that I can compare our plans with what that table expects.

- Given a home admin, when they record the usual Commander night in Settings (a name, and optionally the venue, the household's target bracket, the published bracket range, house-rule notes and the date checked), then it's saved as one change in Activity; anything left blank stays unknown, and nothing is filled in or guessed.
- Given a home viewer on a home Commander deck page, when a night is recorded, then its aim and published range show beside the deck's own Target bracket, with any difference stated; profiles of other spaces never see it, an admin included.
- Given house-rule notes, when they show, then they're shown as written with the date checked (or 'unknown'), as notes for before the game, not as enforced rules or a claim that the deck fits.
- Given no night is recorded, then nothing extra appears; given the notes can't be read, then the page says so rather than claiming none were saved; and a recorded night's note still shows when the card checks or the deck's inventory figures are unavailable.
- Given someone else changed or cleared the notes since I opened them, when I save, then my older copy can't overwrite theirs; clearing needs a reason and a confirmation.

Decided (Matt, 2026-10-13): one usual-night note, not an events calendar or a live venue feed; venue facts are entered by hand and never seeded.

Now: Built 2026-10-16 ([HISTORY.md, Private household Commander-night notes](../HISTORY.md#private-household-commander-night-notes-2026-10-16)).

Evidence:
- `decklab/lib/state/commander_night.py`: normalize, clear_reason
- `decklab/lib/api/commander_night.py`: view, change, projection; `decklab/lib/permissions.py`: sees_commander_night
- `decklab/web/commander-night.js`: commanderNightPart, commanderNightSettings, saveCommanderNight
- `decklab/tests/test_commander_night_api.py`: test_home_admin_saves_one_change_home_member_reads_and_unknowns_stay_unknown
- `decklab/tests/test_commander_night_ui.py`: test_projection_is_quiet_when_absent_and_defends_home_boundaries, test_concurrent_save_preserves_inputs_and_requires_explicit_reload

**E9-S21** · Matt · could · M · missing

As a player reading a pod run, I want each deck's share of wins with a range, so that I don't read too much into a few pod games.

- Given a finished pod run, when I read it, then it shows each deck's share of wins with a range.
- Given pod games don't replay exactly, when I read the result, then it says they're statistics only.

Gap: there are no pod runs to show (E9-S11).

**E9-S22** · Matt · could · S · missing

As a player who may not be allowed to start simulations, I want to see why beside a pod run's Start, so that I know whom to ask rather than wondering why nothing happens.

- Given the simulations setting, when I'm not allowed to start runs, then the reason shows beside the pod run's Start, in words naming nobody.

Evidence:
- `decklab/lib/api/simulations.py`: view (why_not, used beside the other Play and Start buttons)
- `decklab/lib/permissions.py`: reason

Gap: there's no pod run's Start yet (E9-S11).

**E9-S23** · Matt · should · M · built

As a player bringing a Commander deck to a pod, I want to be told when my list holds both pieces of a known two-card combo, so that I can say so at the table and keep a deck aimed at Bracket 2 within what that bracket expects.

- Given a two-card combo whose pieces are both in the list (commander and deck), when the deck is checked, then What opponents will face names the combo, from a published combo list, with that list's date.
- Given the combo list can't be read, when the section shows, then it says combos weren't checked rather than that none were found.

Decided (Matt, 2026-10-21, every recommended answer in [commander-sources.md](commander-sources.md#matts-calls)): only standalone infinite or game-ending combos raise the minimum to Bracket 3, and a standalone one that destroys lands counts as mass land denial (Bracket 4); locks, draws, near-infinites and combos needing a payoff are listed in softer words ("needs a payoff") and raise nothing; no early-game hint (Spellbook's `bracketTag`, EDHREC's votes); no decklist is ever sent to Spellbook. The words are "holds both pieces of", never a claimed breach.

Now: Built 2026-10-21. `cards update` downloads Commander Spellbook's public export as a step of its own (conditional, kept on failure, never blocking the card index) and reduces it to its Commander-legal two-card combos, matched on the PC by oracle id (the Commander, Companion and Deck sections; a piece that must be the commander only as the commander). Combos of three or more cards, combos needing a card that isn't named, and intent stay unchecked, and the page says so.

Evidence:
- `decklab/lib/combos.py`: update, reduce_export, find, bracket_floor
- `decklab/lib/cards.py`: _update_combos
- `decklab/lib/stats/commander.py`: _combo_check, min_bracket
- `decklab/web/commander-readiness.js`: comboFindings, commanderReadiness; `decklab/web/stats.js`: commanderPanel
- `decklab/tests/test_combos.py`; `decklab/tests/test_commander_readiness.py`: TwoCardComboTests; `decklab/tests/test_commander_readiness_ui.py`: test_a_raising_combo_is_named_in_the_lead_and_listed_with_its_link, test_an_unreadable_combo_list_is_not_checked_and_incomplete

**E9-S24** · Matt · should · M · built

As a player aiming at a bracket, I want to know when the official Commander Brackets or Game Changers list changes, so that a deck checked against an older list isn't shown as fitting when it may not.

- Given the official Brackets or Game Changers list changed after the local card data's date, when a Commander deck is checked, then the checks say the list changed on that date and may be out of date, even when the data is under 7 days old.
- Given the date of the latest official change can't be read, when a deck is checked, then the page says it's unknown rather than that the list is current.

Decided (Matt, 2026-10-21, every recommended answer in [commander-sources.md](commander-sources.md#e9-s24-when-the-official-lists-change)): a daily conditional, gzipped check of Wizards' sitemap is fine; the Commander format page is never fetched (Wizards' terms); a new Commander announcement warns until the card data and the bracket rules are newer than it, even when it changed nothing; the bracket rules are marked as reviewed by setting `constants.BRACKET_RULES_DATE` to the announcement's date.

Now: Built 2026-10-21. `cards update` (so the server's daily card data check too) checks Wizards' sitemap at most once a day, as a step of its own that never fails the update, and keeps the newest Commander announcement (its date from its URL, never `lastmod`) in `decklab/data/scryfall/official_lists.json`; a failed check keeps the last good one. The Commander checks read it from the PC only: they warn while the card data is no newer than the announcement, or the bracket rules are older, and say the date is unknown when no check worked in 7 days. A new post means "announced, may have changed", never "changed".

Evidence:
- `decklab/lib/official_lists.py`: update, newest_announcement, announcement_date, read
- `decklab/lib/cards.py`: _update_official_lists
- `decklab/lib/stats/constants.py`: BRACKET_RULES_DATE
- `decklab/lib/stats/commander.py`: _official, _data_dates
- `decklab/web/commander-readiness.js`: commanderDataNote, officialNotes (also in `decklab/web/stats.js`'s commanderPanel)
- `decklab/tests/test_official_lists.py`; `decklab/tests/test_commander_readiness.py`: OfficialListTests; `decklab/tests/test_commander_readiness_ui.py`: test_wizards_latest_announcement_is_shown_and_never_called_current_unless_checked

---

## E10: Members, access and privacy

Who Deck Lab's profiles are, where each one's cards and decks live, and who may see or change what. Matt (admin) and User1 share the home space; User2, User3, User4 and User5 (`user5`, the template for every member, [member-template.md](member-template.md)) each have their own, and sign in only through decklab.example.com. Each space's collection, decks and games, and each kit owner's accessories, are private unless the owner makes them public: read-only, to everyone signed in through Cloudflare Access, with no admin override ([privacy-by-default.md](privacy-by-default.md)). The command line still reads every space, so Claude relays upkeep, not contents, and adding a person still means editing config.json and the Access policy by hand.

Open: E10-S17, E10-S18, E10-S41.

**E10-S01** · Matt · must · L · built

As Matt, the household's admin, I want each person's cards and decks kept apart from the home's shared pool and from each other, so that owned-vs-needed, in-use counts and tokens are worked out per physical collection, and nobody's cards get mixed up.

- Given User2's profile has space `user2`, when a deck is made in his space, then its id is `user2/<kind>/<slug>` and its owned-vs-needed table counts only User2's collection.
- Given a home receipt is applied, when deck tables refresh, then no deck in a person's space is rewritten.
- Given a person's space, when its pool is worked out, then nothing is ever on the way (there are no orders, products or watchlist there).
- Given a person's deck, when a save adds Played by, Sleeves or Deck box, then the save is refused.

Evidence:
- `decklab/lib/pool.py`: load_pool, _load_person_pool
- `decklab/lib/inventory/refresh.py`: spaces_of
- `decklab/lib/inventory/ops_decks.py`: HOME_ONLY
- `decklab/lib/spaces.py`: split_deck_id

**E10-S02** · User1 · must · M · built

As User1, a home member, I want to change my own decks, wishlist and settings and home's collection and tokens, while Matt's and the house's ('either') decks stay his to change, so that I can tweak my decks without worrying about breaking his.

- Given User1 saves a home deck Played by wife, then the save succeeds and Activity shows it as User1's.
- Given she opens a deck Played by user or either, then Edit is replaced by Try a change, and POST `/api/deck/save` answers 403 'You can change the home decks played by you.'
- Given she saves home's collection or tokens, then it succeeds as one change by User1 (E10-S43), while receipts, orders and products answer 403 'Only an admin can change the receipts.' (orders, products).
- Given she records a game, when one of its decks is one she may change, then it saves; otherwise it's refused with 'A game you record needs one of your decks in it.'

Evidence:
- `decklab/lib/permissions.py`: _deck_reason, reason, _ADMIN_WORDS, SPACE_ACTIONS
- `decklab/web/core.js`: canEditDeck
- `decklab/web/editor-deckpage.js`: Try a change
- `decklab/tests/test_api_permissions.py`: DeckRouteTests, AdminRouteTests

**E10-S03** · Matt · must · M · built

As Matt, the household's admin, I want whoever is picked on the home network to have the same rights as through the tunnel, so that a slip on a shared device can't change home's records or someone else's deck.

- Given User1 is picked at home, when she saves a deck Played by user or applies a receipt, then it is refused with the same reason as remotely.
- Given a home-network request names User2 or User5 (header, `?profile=`, `?viewer=` or a body's profile), then it answers 403 'Sign in through decklab.example.com' (E10-S35).
- Given a script on the PC (loopback, `X-Deck-Lab-Script: 1`, no viewer) writes, then it passes; any other request naming nobody is refused.
- Given a refused save, then the answer holds only `{"error"}`, nothing of home's.

Decided (Matt, 2026-10-13): the picked profile is trusted rather than a login, so the home network's rules stop slips, not a deliberate lie; only home profiles can be picked there.

Evidence:
- `decklab/lib/permissions.py`: reason, is_admin
- `decklab/lib/access.py`: SIGN_IN_OUTSIDE, script
- `decklab/lib/server_http.py`: _is_script
- `decklab/lib/api/settings.py`: _writer
- `decklab/tests/test_script_rule.py`: HomeListenerTests, ScriptRuleTests

**E10-S04** · User1 · must · M · built

As User1, sharing a household device with Matt, I want to say who I am quickly, and have the device ask again after it has been put down, so that my saves and game records are labelled as mine and I see my own wishlist and sleeves, not Matt's.

- Given the page is opened on the home network, when no one is chosen, then the 'Who are you?' screen lists the home profiles with the last choice first.
- Given the tab has been in the background for more than 30 minutes and 'This is my device' isn't ticked, when it comes back, then the chooser shows again.
- Given unsaved edits in the editor, when Switch person is chosen, then the page asks before switching.
- Given 'This is my device' is ticked in the avatar menu, when the tab returns after hours, then it opens as that person.

Decided (Matt, 2026-10-13): User1 mostly uses her phone, where 'This is my device' keeps her picked; the story stays written for a shared device.

Evidence:
- `decklab/web/app.js`: switchProfile, AWAY_MINUTES, backFromAway, drawWho, homeProfiles
- `decklab/web/shell.js`: isMyDevice, toggleMyDevice

**E10-S05** · User1 · must · L · built

As User1, away from home, I want to reach Deck Lab with just my email, no password to remember, so that I can check whether my cards have come or look at my deck from my phone anywhere.

- Given her email is in the Access policy and in her profile's emails, when she enters the one-time code at decklab.example.com, then Deck Lab opens as User1 with 'Signed in as User1' and no chooser.
- Given the login lasts a month, when she returns within it, then she isn't asked for a code again.
- Given she is signed in remotely, when the page loads, then nothing offers to switch to another person.

Now: the second criterion is Cloudflare's configuration, checked by hand in the Zero Trust dashboard.

Evidence:
- `decklab/lib/access.py`: me, NOT_SET_UP
- `decklab/web/app.js`: chooseProfile ('Signed in as')

**E10-S06** · Matt · must · M · built

As Matt, the household's admin, I want only people with a set-up email to get in from the internet, and anything doubtful refused, so that the household's decks, collection and wishlists aren't open to strangers.

- Given a visitor passes Cloudflare Access with an email no profile lists, when any page or API is requested, then Deck Lab answers 403 'This email isn't set up in Deck Lab'.
- Given a request carries Cloudflare headers or the public hostname, when it reaches the home listener on 8642, then it is refused with 421.
- Given the tunnel's config.yml routes anywhere but Deck Lab's tunnel listener, when the server starts, then the tunnel isn't started and `homenet status` reports it.
- Given a profile's email changes, when Activity shows it, then the row reads 'An email address changed', without the address.

Decided (Matt, 2026-10-18): members outside the household, starting with User5, get in the same way, one exact email in the Access policy and their profile, never a whole domain.

Evidence:
- `decklab/lib/access.py`: NOT_SET_UP
- `decklab/lib/server_http.py`: TUNNEL_ONLY
- `decklab/lib/tunnel.py`: ingress_problems
- `decklab/lib/homenet/commands.py`: check_tunnel
- `decklab/lib/api/activity.py`: EMAIL_CHANGED

**E10-S08** · Space members · must · M · built

As User2, User3 or User4, with my own space, I want to change my own collection, tokens, decks and wishlist and nothing of anyone else's, so that I can keep my cards up to date without any risk to the household's.

- Given User2 is signed in, when he imports a ManaBox export on `#/collection?space=user2`, then it applies to his space as one change by User2.
- Given home's decks are private, when he opens a home deck's address, then it answers as a missing deck; given they are public, then it offers Try a change, not Edit, and a save is refused with 'That's one of the home decks; you can change the decks in your own collection.'
- Given he makes a new deck, when he picks where it goes, then only his own space is offered.
- Given he asks for `#/collection?space=user3`, then the server answers 403 'That collection isn't public.', naming no one.

Now: User5's space follows this story as the space members' do.

Evidence:
- `decklab/lib/permissions.py`: _deck_reason, SPACE_ACTIONS, summary
- `decklab/lib/api/guard.py`: require_sees_inventory, COLLECTION_HIDDEN, require_sees_deck
- `decklab/web/core.js`: createTargets
- `decklab/tests/test_inventory_privacy.py`: AdminNarrowingTests

**E10-S09** · Space members · wont · M · not_wanted

As a member with my own space, I want to read the household's decklists, guides, stats and matchups without seeing the home's card counts, so that I know what I might face in games against home's decks while the household's collection stays theirs.

- Given User3 opens a home deck, when the page loads, then he sees the list, How to play, Stats, Practice and Matchups, with no availability banner, card marks, token lines or price table.
- Given he opens the library, then home decks show without readiness chips or token lines, and no sleeves or deck boxes appear anywhere.
- Given he looks for Shopping, the Packing plan or Sleeves & boxes, then they aren't in his navigation, and their APIs answer 403.

Decided (Matt, 2026-10-13): reversed by private by default: home's decklists are seen only by home unless home makes its decks public (E10-S30). Not wanted since E10-S30 shipped on 2026-10-18.

Now: hiding the counts survives, for a public deck whose space's collection is private.

Evidence:
- `decklab/lib/api/guard.py`: require_sees_inventory, hide_kit

**E10-S10** · User1 · must · S · built

As User1, a home member, I want to see Shopping, deliveries and the packing plan, even though I can't change orders or receipts, so that I know what's coming for my decks and can pack for a game, while Matt keeps receipts and orders.

- Given User1 opens `#/shopping`, then she sees deliveries, the queue, decks still missing cards and the long-term plan, with no Done buttons on follow-ups.
- Given she opens Receive delivery, then it is read-only, and POST `/api/receipt/apply` answers 403 'Only an admin can change the receipts.'
- Given she opens `#/assembly` (Build decks), then she can tick cards to pack, the ticks are shared with her other devices, and nothing in the inventory changes.

Evidence:
- `decklab/lib/permissions.py`: sees_home_records, _ADMIN_WORDS
- `decklab/web/shopping.js`: Done shown only with mayDo("orders")
- `decklab/web/receipts.js`: drawReceiptReadOnly
- `decklab/web/assembly-progress.js`: packSync
- `decklab/lib/api/guard.py`: the `/api/assembly/ticks` rule

**E10-S11** · User1 · must · S · built

As User1, I want my wishlist seen only by me, not even by the admin, so that I can note cards I like, gift ideas included, without anyone reading them.

- Given Matt (admin) is signed in, when the page asks for GET `/api/profiles/user1/wishlist`, then it answers 403 'A wishlist is private...'.
- Given User1 changes her wishlist, when anyone else opens Activity, then the row isn't shown, and the change's message and reason aren't either.
- Given a home request naming nobody that isn't a script, when it asks for any wishlist, then it is refused too.
- Given the PC's command line, when `wishlist list` is run, then it still reads every list (a documented exception).

Evidence:
- `decklab/lib/permissions.py`: sees_wishlist
- `decklab/lib/api/guard.py`: require_sees_wishlist, WISHLIST_HIDDEN
- `decklab/tests/test_activity.py`: WishlistPrivacyTests
- `decklab/db/wishlist_cli.py`

**E10-S12** · User1 · should · M · built

As User1, I want my own sleeves, deck boxes and playmats kept apart from Matt's, with shared ones we both use, so that I manage my own kit for my decks, and the members don't see the household's kit unless we make it public.

- Given User1's kit is private, when Matt opens `#/accessories`, then her rows aren't listed, and a deck holding one is named only as 'one of User1's decks'.
- Given User1 chooses sleeves for a deck Played by wife, then only her own and shared rows are offered.
- Given User2 requests `/api/accessories` or an accessory picture, then the answer is 403, unless the owner made it public (E10-S33).
- Given the home network, when the chooser names User1, then she sees her own and shared rows (the pick is trusted, not a login; see E8-S16).

Evidence:
- `decklab/lib/permissions.py`: accessory_owners, ACCESSORIES_PRIVATE
- `decklab/lib/api/guard.py`: require_kit_choice, sees_kit, accessory_readers
- `decklab/lib/accessories.py`: hidden_title
- `decklab/tests/test_api_accessories.py`: OwnerTests

**E10-S15** · Space members · could · S · built

As a member with my own space, I want Activity to show only my own space's changes, without the household's details, so that I can see what happened to my cards without seeing into anyone else's.

- Given User4 opens `#/activity`, then he sees his own collection, token and deck changes, his settings and the simulations mode changes, and no home inventory rows.
- Given a change set has no row he may see, then it isn't listed at all.
- Given a game record with one of his decks and a home deck, when he reads its headline, then the home deck isn't named beyond what he may see.

Decided (Matt, 2026-10-13): the space members will use Deck Lab rarely, mostly on phones, so this is a could.

Now: built 2026-10-18 by E10-S32 and E10-S34 ([HISTORY.md, Activity stays within its space](../HISTORY.md#activity-stays-within-its-space-2026-10-18)).

Evidence:
- `decklab/lib/permissions.py`: activity_scope, sees_play_record
- `decklab/lib/api/activity.py`: visible_change, _row
- `decklab/tests/test_activity.py`: VisibilityTests

**E10-S17** · Matt · could · L · missing

As Matt, the admin, I want to add a member or change someone's email without editing files on the PC, so that bringing someone in is quick and I can't break config.json with a typo.

- Given the Settings page, when Matt adds a person with a name, an email and 'own space', then the profile and space are made and synced to the database in one audited change.
- Given an entry is invalid (reserved id, missing plays_as for a home profile), then it is refused with the reason instead of being silently left out.
- Given a new email, then the page reminds him to add it to the Cloudflare Access policy, and `homenet status` warns about profiles whose email can't sign in.
- Given emails, then they are never sent to the page except to the admin on this panel.

Evidence:
- `decklab/lib/profiles.py`: RESERVED_IDS
- `decklab/db/profiles_sync.py`
- `decklab/web/settings.js`

Gap: Settings has no profile or email management, and `lib/profiles.py` silently drops invalid entries (reserved ids, a bad space, a missing plays_as) instead of reporting them.

First slice: report invalid profile entries (reserved id, bad space, missing plays_as) in `homenet status` and setup instead of dropping them; the Settings editor follows.

Review note: L for a could bundles a profile editor, validation, an Access reminder and a status check; the second criterion could be its own small story.

**E10-S18** · Space members · could · M · partial

As a space member visiting Deck Lab for the first time, I want to land on my own deck, with only the pages that mean something to me, so that I'm not lost among the household's tools on my first visit.

- Given User3 signs in for the first time, when the library opens, then it shows 'Mine' (his decks) by default.
- Given he has one deck, then the page leads him to it, with a short note on what he can and can't see.
- Given he has no game records, then the Game log opens with its plain note (E10-S24), and given no Activity of his own, then Activity says what will appear there once his cards change.
- Given Shopping, the Build decks page and Sleeves & boxes, then they are hidden from him.

Decided (Matt, 2026-10-13): the space members will use Deck Lab rarely, mostly on phones. User5's first visit follows this story too.

Evidence:
- `decklab/web/library.js`: filters.all (Mine unless `?all=1`)
- `decklab/web/play.js`: playNoGamesWords
- `decklab/web/activity.js`: activityNothing
- `decklab/web/core.js`: ROUTES

Gap: no first-visit note, no landing on a sole deck, and Activity's empty state says only 'Nothing you can see has changed yet.'

**E10-S19** · User1 · could · S · built

As User1, a home member, I want home's inventory to stay visible only to Matt and me, even if someone in another space were made an admin, so that giving someone extra rights over their own space doesn't open the household's cards to them.

- Given a profile with role admin and a person space, when it opens `#/shopping`, then it is refused like any other person.
- Given that profile, when it opens a home deck, then it answers as a missing deck (E10-S30), so no home count reaches it.
- Given Matt (home admin), then he sees home's inventory and no other space's (E10-S29).

Now: built 2026-10-18 with E10-S29 ([HISTORY.md, Collections and tokens are seen only in their own space](../HISTORY.md#collections-and-tokens-are-seen-only-in-their-own-space-2026-10-18)).

Evidence:
- `decklab/lib/permissions.py`: inventory_spaces, sees_home_records, activity_scope, summary
- `decklab/tests/test_permissions.py`: InventoryRuleTests, SummaryTests

**E10-S22** · Matt · wont · S · not_wanted

As Matt, I want no public pages, share links or sign-up, so that Deck Lab stays a private tool and nobody without a set-up login is ever served.

- Given any page, then nothing offers a link to a deck that works without signing in, or a sign-up.
- Given a visitor without a set-up email, then they never get past Access and Deck Lab's 403.

Decided (Matt, 2026-10-18): the privacy switches' Public means read-only to every profile signed in through Cloudflare Access, never a page on the open internet, so this story stands; members are still added by hand, one email at a time.

**E10-S23** · User1 · could · S · built

As a member who switches between a phone and a household device, I want my theme and my matchup and field run choices to follow me to whichever device I use, so that Deck Lab looks and behaves the same for me everywhere without setting it up on each device.

- Given User1 picks Dark in the avatar menu on her phone, when she opens Deck Lab as herself on another device, then it is dark there too.
- Given she changes a matchup's games or mode, when she opens a matchup on another device, then it starts with her choice.
- Given she picks a field run budget (Quick look, Settle it, Precise), when she opens a field run on another device, then that budget is preselected.
- Given a setting can't be saved, when she changes it, then a toast says so and the device keeps its local choice.

Now: built 2026-10-15 with E3-S09; checks on physical devices are E2-S22's.

Evidence:
- `decklab/lib/api/settings.py`: SETTINGS, put_settings
- `decklab/web/app.js`: changeTheme
- `decklab/web/field.js`: fvSaveBudget
- `decklab/lib/api/field_page.py`: default_budget

**E10-S24** · Matt · must · M · built

As Matt, the household's admin, I want the household's Game log kept to User1 and me, with others seeing only games that include one of their own decks or games made public, so that our games at home stay ours.

- Given User2 is the viewer, when he opens `#/play` or GET `/api/play`, then only games with a deck in his space or a space whose games are public, and only sideboard plans of his own decks, are returned, and no other game, plan or count reaches the page.
- Given Matt or User1 is the viewer, when they open the Game log, then they see every game and plan with a home deck in it.
- Given a viewer with no games, when they open the Game log, then it opens empty with a plain note.
- Given the rule, then it's one rule in `decklab/lib/permissions.py` used by both the Game log and Activity, though Activity never widens for public games.

Now: built 2026-10-13; its admin branch was removed and public games added by E10-S29, E10-S32 and E10-S28 (2026-10-18).

Evidence:
- `decklab/lib/permissions.py`: sees_play_record
- `decklab/lib/api/play_records.py`: _owner_ids, _view
- `decklab/web/play.js`: playNoGamesWords
- `decklab/tests/test_play_records.py`: PlayMemberRulesTests

**E10-S25** · Matt · should · M · built

As the household admin, I want to see whether User1 and the members use Deck Lab and which pages they open, so that I have usage evidence for deciding which features are worth building.

- Given a profile opens a page, through the tunnel (named by its Cloudflare Access login) or on the home network (named by the profile picked), when the page loads, then the day, the channel (home or remote) and the route are recorded, with the deck's id only for a deck the visitor may see.
- Given a request from a script or one naming nobody, when it's served, then nothing is recorded.
- Given the Settings page's Visits panel or `python -m decklab.db visits`, when an admin opens it, then each profile shows its first and last seen, the days it visited and the pages it opened, and profiles not seen yet are listed as such.
- Given Matt opens Visits, then another space's private deck shows as 'one of User2's decks', with no id.
- Given a viewer who isn't an admin, when they ask for GET `/api/visits`, then the answer is 403.
- Given days older than about 400, when the nightly runs, then they're deleted.

Decided (Matt, 2026-10-18): Visits stays for members too, and a member's invite tells them Matt sees which days they used Deck Lab and which pages they opened.

Evidence:
- `decklab/lib/visits.py`: CHANNELS, DECK_ROUTES
- `decklab/lib/api/visits.py`: beacon, _requester_sees
- `decklab/db/visits.py`
- `decklab/web/app.js`: noteVisit
- `decklab/tests/test_visits.py`: RecorderTests, BeaconTests, ViewTests

**E10-S28** · Matt · must · M · built

As Matt, I want one switch for each thing our space owns (collection, decks, games, and each kit owner's sleeves, boxes and playmats), all starting private, so that nothing of ours is seen outside the household until one of us chooses to make it public.

- Given the database after migration 0012, when no switch has been flipped, then `python -m decklab.db visibility list` shows every thing as Private.
- Given User1 is the viewer, when she opens Who sees what in the avatar menu, then she sees switches for home's collection, decks and games, her own kit and the shared kit, and none for Matt's kit or another space.
- Given User2 or User5 is the viewer, then he sees switches only for his own collection, decks and games.
- Given any switch, then it reads Private or Public, and the page says Public means read-only to everyone signed in to Deck Lab, members included, not anyone on the internet; the decks switch also says the Play-now list hints at what's owned.
- Given Matt makes home's decks public, then one change set by Matt is saved, and Activity shows 'Make the home decks public' to Matt and User1 only.
- Given Matt sends a flip for User2's space, then the answer is 403 'Only the owner can change who sees this.', naming no one.
- Given Claude is asked to flip a member's switch, then there is no command for it (`visibility set` takes home's switches only): the member does it on the page.
- Given GET `/api/me` on the home network with User1 picked, then its `may` is User1's, including `visibility`; and after she flips a switch the page fetches it again.
- Given the database can't be read and nothing is cached, when a rule asks for the switches, then everything counts as private.
- Given User2's profile is removed and synced, then his visibility rows are deleted in the same change set.
- Given the nightly, then the table is exported and covered by the restore check's digests, and `check` flags a row whose owner is neither a space nor matt, user1 or shared.

Decided (Matt, 2026-10-18): one switch per list (per-deck public is E10-S41); either home profile flips home's switches and the `shared` kit, and the last flip wins; Claude never flips a member's switch, even on a request Matt relays.

Now: built 2026-10-18, live since 2026-10-19 (migration 0012 applied, server restarted) ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)). Nothing has been made public yet.

Evidence:
- `decklab/lib/state/visibility.py`: switch, message
- `decklab/lib/api/visibility.py`: controls, change, OWNER_ONLY
- `decklab/lib/visibility.py`: snapshot, pinned
- `decklab/web/visibility.js`: drawVisibility
- `decklab/tests/test_visibility_api.py`: VisibilityApiTests; `decklab/tests/test_visibility_foundation.py`: VisibilityDatabaseTests

**E10-S29** · Space members · must · L · built

As User2 or User5, with my own space, I want my collection and tokens seen only by me unless I make them public, and changed only by me even then, so that the admin can't browse or edit my cards on the page.

- Given User2's collection is private, when Matt opens `#/collection?space=user2`, then the answer is 403 'That collection isn't public.', naming no one.
- Given it is public, when Matt opens it, then he sees it read-only; and POST `/api/collection/save`, `/collection/import/preview`, `/collection/import/apply`, `/api/tokens/save` and `/api/precons/add` for space user2 each answer 403 with only `{"error"}`, even with a stale sha256.
- Given Matt asks for GET `/api/precons/preview?space=user2`, then the answer is 403, so no deck id is probed.
- Given home's collection is public, when User2 or User5 opens `#/shopping`, `#/receipt` or `#/assembly`, then they aren't in his navigation and their APIs answer 403.
- Given home's collection is public, when User2 opens Collection or Tokens, then he sees no order ids, no pending token orders and no warnings about orders or products; rows on the way show only a count.
- Given home's collection is public but its decks private, when User2 opens Collection or Tokens, then decks are named only as 'one of the home decks'.
- Given User3 edits his own deck while home's collection is public, when he opens the printing picker or pastes a list, then the counts and default printings are User3's, not home's.
- Given Matt opens User5's Collection, Tokens, decks or Game log on the page before anything is public, then each answers as for a missing space, and User5's Activity rows don't reach him.
- Given the PC's command line, when `collection merge --space user2` runs, then it still works.

Decided (Matt, 2026-10-13): admin writes in other spaces are removed from the page; Matt asks Claude, who uses the command line (E10-S36). Shopping, receipts and the packing plan stay home's, whatever the switches say.

Now: built 2026-10-18 with E10-S43, live with E10-S28's switches since 2026-10-19 ([HISTORY.md, Collections and tokens are seen only in their own space](../HISTORY.md#collections-and-tokens-are-seen-only-in-their-own-space-2026-10-18)). Supersedes E10-S19.

Evidence:
- `decklab/lib/permissions.py`: sees_inventory, inventory_spaces, sees_home_records
- `decklab/lib/api/guard.py`: COLLECTION_HIDDEN, require_space_write, require_sees_home_records
- `decklab/lib/api/inventory_views.py`: on-the-way labels reduced to counts outside home
- `decklab/tests/test_inventory_privacy.py`: AdminNarrowingTests, DeckNamesTests, PoolCountsTests

**E10-S30** · Matt · must · XL · built

As Matt, I want each space's decks seen only by that space unless it makes them public, so that the household's decks and plans stay ours until we choose to show them, and a member's stay theirs.

- Given home's decks are private, when User5 asks for GET `/api/decks`, then no home deck, product deck or pairing is in it, his library says 'Nothing else is public yet.', and `halves`, `usual_opponents`, `shelf_extras`, `aliases`, `edited`, `revision` and `decks_revision` are worked out over his own decks only.
- Given he asks for `/api/deck`, `/deck/edit`, `/deck/history`, `/deck/revision`, `/deck/cards`, `/goldfish`, `/api/field`, `/api/opponents`, the cover picker, the rename or retire preview, or POST `/api/deck/check` on `casual/gruul-ramp`, or 'Save as a new deck' from `product/...`, then each answers exactly what a missing id answers (404 "No deck 'casual/gruul-ramp'").
- Given he asks for the history or a revision of a retired deck, or posts a restore, whose former space isn't his, then the answer is the same 404, checked before the revision lookup.
- Given he posts `/api/deck/save`, `/deck/cover`, `/deck/check` or `/tables/update` naming a home deck, deleted or not, then the answer is the same 404, never a 403, a 409 or a title: the deck rule comes first, then permission, then the conflict.
- Given GET `/api/play`, then `lists`, `decks` and `warnings` hold or name only decks he may see.
- Given GET `/api/rankings`, then its rows and ratings are worked out only over decks he may see.
- Given GET `/api/matchups`, `?running=1`, `/api/matchup?key=`, `/api/variant?test=` or `/api/variants?id=` for anything with a side he may not see, then nothing of it reaches him (404 for a key, test or id), and `by`, `stopped_by` and `cancelled_by` from other spaces read 'someone'.
- Given a run, when someone posts stop for a matchup, field run or variant test, then it stops only for an admin, its starter, or an owner of one of its decks (E10-S31), and an admin sees a run he may not see as an anonymous item.
- Given home's products, then product and pairing decks go only to home's profiles (owned ones also when home's decks are public), and ordered or preordered products never leave home.
- Given home's decks are public, then User2 sees them read-only, with Try a change but no Edit, and their counts only if home's collection is public too.
- Given a wishlist entry whose source is a hidden deck, then the page shows the path, not the deck.
- Given User2 opens a hidden home deck's address, then Visits records no deck id; and given Matt opens Visits, then User2's private deck shows as 'one of User2's decks'.

Decided (Matt, 2026-10-13): a public deck shows its text as written, and the admin role doesn't override.

Now: built 2026-10-18 ([HISTORY.md, Decks are seen only in their own space](../HISTORY.md#decks-are-seen-only-in-their-own-space-2026-10-18)); its deferred readers were finished by E10-S28, E10-S29, E10-S31, E10-S32 and E10-S34 the same day.

Evidence:
- `decklab/lib/permissions.py`: sees_deck, deck_spaces
- `decklab/lib/api/guard.py`: sees_deck, public_deck_spaces, no_deck, require_sees_deck, visible_decks, hidden_deck, _home_only
- `decklab/lib/api/forge_runs.py`: _Seen, HIDDEN_RUN
- `decklab/tests/test_deck_visibility.py`: LibraryTests, PageTests, PlayAndVisitsTests
- `decklab/tests/test_deck_privacy_readers.py`: ReaderTests, WriteOracleTests, ForgeFilterTests

Review note: XL; it was delivered as two halves (the library and deck pages, then the bypassing readers, writes and Forge filter).

**E10-S31** · Matt · must · L · built

As Matt, I want Forge results, runs and fields to follow the decks' visibility exactly, so that a matchup never shows a list its viewer may not see, and nobody loses results for their own list.

- Given a result whose `seen_as` names only a home deck, and User2's deck has the identical list, when User2 opens his deck, then the result shows under his deck, never under the home deck's id or title.
- Given a deck page, then its matchups, earlier results, per-card stats and "cards the AI can't play" count only results whose both sides the viewer sees.
- Given User2 runs a field run of his own deck, then its field is his space's decks plus the decks of spaces with decks public; and with nothing public the answer is 400 "There's no other deck in the <format> field for it to play."
- Given a home deck's field, then it is today's field, the existing field notes still load, and a non-home viewer's view leaves out ordered products and any member they can't see, with the rating fitted only over results they may see.
- Given the simulations mode is `everyone`, when User5 starts a matchup, field run or variant test, then every side must be his own or public, and a variant's base deck must be in his own space.
- Given User1 asks to test a change to one of User2's public decks, then `/api/variant/run` answers 403, while a matchup run against it is allowed.
- Given a run User4 can see, when he posts stop, then it stops only if he started it or one of its decks is his own; given a run he can't see, then the answer is 404; and given Matt, then the pill shows it as 'A run of one of User4's decks' with Stop.
- Given a starter from another space, then results and runs name them 'someone'.
- Given the PC's command line, when `python -m decklab.lib.forge field` runs, then it is unchanged.

Decided (Matt, 2026-10-13): results take their decks' visibility and are never made public on their own; variant tests only of a deck in the viewer's own space; an admin may stop any run, shown anonymously.

Now: built 2026-10-18 ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)); no real Forge games were run for it.

Evidence:
- `decklab/lib/api/forge_runs.py`: _Seen
- `decklab/lib/api/field_page.py`: _seen_field, stop_field
- `decklab/lib/forge/field.py`: NO_OPPONENTS
- `decklab/lib/api/variant_page.py`: _sees_test
- `decklab/tests/test_forge_privacy.py`: SavedVisibilityTests, StopIdentityTests; `decklab/tests/test_field_privacy.py`: FieldPrivacyTests

**E10-S32** · Matt · must · M · built

As Matt, I want the Game log seen only by a record's own spaces unless a space makes its games public, and each space to change only its own side of a game, so that no admin or member reads games they weren't part of, a game with someone else's deck doesn't show its list, and nobody rewrites the other side's notes.

- Given User4's games are private, when Matt opens `#/play`, then no game with only User4's decks appears.
- Given a game of User5's deck against a home deck, with home's decks private, when User5 views it, edits it or receives its saved answer, then the home side reads 'one of the home decks', with no list snapshot.
- Given that game was recorded by Matt, when User5 edits it, then he may change only his own side (his deck and his mulligans); the result and notes stay Matt's to change, and a body changing them answers 403.
- Given a sideboard plan, then only its deck's space may read or change it, even in a record that names a deck of another space, and even when that space's games are public.
- Given someone posts an edit of a record they may not see with a stale sha, then the answer is 404, not 409.
- Given Activity, when anyone reads a game's change set, then no side they may not see is named, and older 'Save game A vs B' messages show only to viewers who see both decks.
- Given User5 records a game against a deck that is neither his own nor public, then the answer is 404, so no game naming a private home deck reaches Matt's and User1's Game log.

Decided (Matt, 2026-10-18): a game's date, result and notes stay with the space that recorded it.

Now: built 2026-10-18 ([HISTORY.md, Mixed Game-log records](../HISTORY.md#mixed-game-log-records-2026-10-18)); the `games` switch came with E10-S28.

Evidence:
- `decklab/lib/api/play_records.py`: _view, _owner_ids, SIDE_MESSAGE, RESULT_MESSAGE
- `decklab/lib/permissions.py`: sees_play_record
- `decklab/lib/api/activity.py`: visible_change
- `decklab/tests/test_play_records.py`: PlayMemberRulesTests

**E10-S33** · User1 · should · M · built

As User1, I want to make my sleeves, deck boxes and playmats public while only I can change them, so that I can show them off without anyone else choosing them for decks.

- Given User1's kit is public, when Matt opens `#/accessories`, then her rows show read-only, grouped under her name, with no Edit, and their pictures load.
- Given that, when Matt chooses sleeves for a deck Played by wife, saves one of her rows or stages a picture for it, then the answer is 403.
- Given her kit is public but home's decks private, when User2 or User5 views it, then holders read 'a home deck' and no holder or product list is sent to him.
- Given she makes it private again, when Matt's browser asks for one of her pictures, then it is refused at once (pictures are sent no-cache).
- Given any accessories save by Matt, then its sha256 covers only rows he may change, so a change of User1's never makes his save conflict.

Decided (Matt, 2026-10-13): Matt flips `matt`, User1 flips `user1`, and either home profile flips `shared` (the last flip wins).

Now: built 2026-10-18 ([HISTORY.md, Public readers, owner controls and Forge privacy](../HISTORY.md#public-readers-owner-controls-and-forge-privacy-2026-10-18)).

Evidence:
- `decklab/lib/api/accessories.py`: accessories_view, _hidden_holder, _sees_holder
- `decklab/lib/api/guard.py`: accessory_readers, sees_kit
- `decklab/tests/test_api_accessories.py`: ViewTests, PictureTests, OwnerTests

**E10-S34** · Matt · should · M · built

As Matt, I want Activity, profile settings and the simulations setting to show each viewer only their own space's changes and details plus system rows, so that being admin doesn't show me the members' changes or Claude's messages about their cards, and a member doesn't learn who else uses Deck Lab.

- Given Claude merges cards into User4's collection, when Matt opens Activity, then the change isn't listed and its `-m` message never reaches him.
- Given User4's collection is public, then Matt still doesn't see its Activity rows.
- Given Matt, then he still sees profile, email and space rows and change sets with no rows.
- Given a change set with rows in two spaces, from the command line or the page (such as an Update all naming every rewritten deck's title), then its message shows only to a viewer who sees every row.
- Given User1 asks for `/api/profiles/matt/settings`, or User5 for any id but his own, then the answer is 403.
- Given User5 asks for GET `/api/simulations`, then he gets only the mode and a reason naming nobody ('Only an admin can start simulations right now. Saved results still show.'); `by`, `since` and the worker counts go only to whoever may change the setting.

Decided (Matt, 2026-10-13): making something public never widens Activity, and Claude's command-line messages about a private space reach no one outside it.

Now: built 2026-10-18 ([HISTORY.md, Activity stays within its space](../HISTORY.md#activity-stays-within-its-space-2026-10-18); [The roster, settings and simulations are seen per viewer](../HISTORY.md#the-roster-settings-and-simulations-are-seen-per-viewer-2026-10-18)).

Evidence:
- `decklab/lib/permissions.py`: activity_scope, RUNS_ADMINS
- `decklab/lib/api/activity.py`: visible_change
- `decklab/lib/api/settings.py`: own_settings_id, SETTINGS_HIDDEN
- `decklab/lib/api/simulations.py`: view
- `decklab/tests/test_roster_privacy.py`: SettingsTests, SimulationsTests

**E10-S35** · Matt · must · S · built

As Matt, I want only scripts on the PC to read everything when no profile is named, and the home network's chooser to offer only home profiles, so that neither a phone on the home Wi-Fi nor someone picking a member's name can read a private space.

- Given a request to the home listener from 127.0.0.1 or ::1 with `X-Deck-Lab-Script: 1` and no viewer, when it asks for `/api/collection?space=user2`, then it is answered in full.
- Given a request from another home-network device naming nobody, or the PC's browser before a profile is picked (no script header), when it asks for `/api/collection?space=user2`, then it is refused unless User2's collection is public.
- Given the tunnel's listener on 127.0.0.1, when a request carries the script header, then it gets nothing extra.
- Given the home network's 'Who are you?', when it lists profiles, then only Matt and User1 are offered, never User5 or a space member.
- Given a home-network request whose `X-Deck-Lab-Viewer` names User2 or User5, when it reaches any route, then the answer is 403 'Sign in through decklab.example.com'.
- Given a job thread (Forge coordinator, goldfish), when it reads decks, then it reads every space.
- Given the call sites that treat naming nobody as everything (history, commits, dbstatus, visits, simulations, editor), then each asks `guard.script()`, and `guard.local()` still means 'not through the tunnel'.

Decided (Matt, 2026-10-13): members always sign in through decklab.example.com, from the home Wi-Fi too.

Now: built 2026-10-18 ([HISTORY.md, Only scripts read everything, and the home chooser offers home profiles](../HISTORY.md#only-scripts-read-everything-and-the-home-chooser-offers-home-profiles-2026-10-18)).

Evidence:
- `decklab/lib/server_http.py`: _is_script
- `decklab/lib/access.py`: script, SIGN_IN_OUTSIDE
- `decklab/lib/api/guard.py`: script, local
- `decklab/web/app.js`: homeProfiles
- `decklab/tests/test_script_rule.py`: HomeListenerTests, ScriptRuleTests

**E10-S36** · Claude Code · must · S · built

As Claude Code, I want a command that adds a published precon to any space, so that Matt can still onboard a member's precon now that the page doesn't let him write in their space.

- Given `python -m decklab.db collection add-precon CODE --space user4 -m "..." --dry-run`, then it previews the cards to add (plain basics left out) and the deck it would make, the same as the page's Add a precon.
- Given it is run without `--dry-run`, then the cards and the built deck are saved in one change set, with the deck's table worked out after the cards are added.
- Given a title whose deck name is already taken in that space, then it is refused with the existing deck's id.
- Given it saves, then its last line gives the counts added and the deck id, so Claude can tell Matt it's done without passing on the list.

Decided (Matt, 2026-10-18): Matt passing on a member's request counts as the owner asking, for upkeep only (merges, `add-precon`, table refreshes); Claude reports counts and 'done', never the contents.

Now: built 2026-10-18 ([HISTORY.md, A precon from the command line](../HISTORY.md#a-precon-from-the-command-line-2026-10-18)).

Evidence:
- `decklab/db/inv_collection.py`: _add_precon, _precons
- `decklab/lib/api/precons.py`: plan_add, add_precon
- `decklab/tests/test_precon_cli.py`: CommandLineTests

**E10-S37** · User5 · should · S · built

As User5, looking at a deck someone made public, I want its history to show only what any outsider may read, so that I see when and how the list changed without reading the household's command-line messages or who in their space saved it.

- Given a public home deck, when User5 asks for GET `/api/deck/history`, then each revision's message follows Activity's `as_written` rule: a message he may not read shows as a plain summary, not Claude's `-m` subject or a git commit subject.
- Given a revision saved by a table refresh from an order or receipt, then it reads 'Tables refreshed', with no order id.
- Given a revision saved by a profile of another space, then its actor reads 'someone'.
- Given the page, then it shows only what the server sends; nothing is masked in the browser.
- Given a viewer in the deck's own space, then the history reads in full.

Now: built 2026-10-18 ([HISTORY.md, Public-deck history subjects stay private](../HISTORY.md#public-deck-history-subjects-stay-private-2026-10-18)).

Evidence:
- `decklab/lib/api/history.py`: SOMEONE, 'Tables refreshed'
- `decklab/lib/api/activity.py`: visible_change (as_written)
- `decklab/tests/test_history_privacy.py`: HistoryPrivacyTests

**E10-S38** · User5 · must · S · built

As User5, a member, I want to see only my own profile and those of people who made something public, so that I don't learn who else uses Deck Lab or how its household is set up, and nobody learns that I do.

- Given nothing is public, when User5 asks for GET `/api/profiles`, then the answer holds only his own profile, plus the admin's display name for 'ask Matt' wording, with no role, space or `plays_as`.
- Given User2 has made his decks public, then User2's profile is listed too, by name only.
- Given any refusal, such as a 403 from `/api/collection?space=user2` or a deck route, then its body names no space or profile the viewer can't see.
- Given Matt or User1, then the roster gives home's profiles in full, and other spaces' profiles follow the same rule.

Now: built 2026-10-18, live with E10-S28's switches since 2026-10-19 ([HISTORY.md, The roster, settings and simulations are seen per viewer](../HISTORY.md#the-roster-settings-and-simulations-are-seen-per-viewer-2026-10-18)).

Evidence:
- `decklab/lib/api/settings.py`: profiles, _public_spaces, _admin_names
- `decklab/lib/api/guard.py`: COLLECTION_HIDDEN, INVENTORY_HIDDEN, HIDDEN_SPACE
- `decklab/web/app.js`: keepRoster, adminWords
- `decklab/tests/test_roster_privacy.py`: RosterTests, RefusalWordsTests

**E10-S39** · Matt · must · S · built

As Matt, I want the page's code to hold no real names, deck titles or results, so that a member reading the JavaScript learns nothing of the household that the server wouldn't send him.

- Given `web/`, when it is read, then examples and comments use neutral names and decks, not home's deck titles, a real win rate or household names.
- Given the test suite, then a test reads every file under `web/` and fails on any configured profile's id or name or any deck title in the database's export or test fixtures.
- Given a new example is added later with a real name, then that test fails.

Now: built 2026-10-18 ([HISTORY.md, The page's code names nobody](../HISTORY.md#the-pages-code-names-nobody-2026-10-18)).

Evidence:
- `decklab/tests/test_web_no_personal_data.py`: NoPersonalDataTests
- `decklab/lib/forge/cli_output.py` (the reworded caveats)

**E10-S40** · Claude Code · should · M · built

As Claude Code, when a member stops using Deck Lab, I want one command that gives them their data and then removes their space, so that they leave with their cards and decks and nothing of theirs stays behind.

- Given `python -m decklab.db space export user5 DIR`, then it writes User5's collection, token cards, raw imports and decks (each deck's text) into a new DIR, in the old files' formats, with a manifest of their hashes.
- Given `space remove user5 --export DIR --expect SHA -m "..." --reason "..." --dry-run`, then it previews every row and file it would remove or redact: collection, tokens, raw imports, decks with their history, play records naming his decks, Forge results of only his decks, wishlist, settings and switches.
- Given it is run without `--dry-run`, then all of that is removed in one audited change set, and a removal without a matching export is refused.
- Given a play record with a deck of another space, then that space's side stays, and his side reads 'a removed deck'.
- Given an interrupted removal, then `space recover UUID` restores or finishes it from its journal.
- Given the removal, then the command reminds Matt to take User5's email out of the Access policy and his profile out of `decklab/config.json`.

Now: built 2026-10-18, live since 2026-10-19 (migration 0013 applied) ([HISTORY.md, Guarded member departure and crash recovery](../HISTORY.md#guarded-member-departure-and-crash-recovery-2026-10-18)). No member has left yet.

Evidence:
- `decklab/db/inv_space.py`: register, _reminders
- `decklab/db/space_export.py`: export_to, matching_export
- `decklab/db/space_remove.py`: preview, transformed_record
- `decklab/db/space_apply.py`: apply, recover
- `decklab/tests/test_space_apply.py`: RemovalApplyTests; `decklab/tests/test_space_export.py`: MemberExportTests

**E10-S41** · User5 · could · L · missing

As User5, I want to make one deck public without making all my decks public, so that I can show Matt the deck we'll play next week and keep the rest to myself.

- Given User5's decks switch is Private, when he makes one deck public on its page, then only that deck is readable to others, read-only.
- Given a matchup between that deck and a home deck, then it shows to a viewer only when both sides are visible to them, deck by deck.
- Given he makes his whole decks list public, then the per-deck choices no longer narrow it, and turning the list back to Private keeps them as they were.
- Given he deletes the deck, then its switch goes with it.

Decided (Matt, 2026-10-18): one switch per list for now; per-deck public is worth building only once someone actually wants it, since every Forge rule then works per deck instead of per space.

Evidence:
- `decklab/lib/api/guard.py`: sees_deck, public_deck_spaces (per space only)

Gap: switches exist only per space's list; there is no per-deck switch.

**E10-S42** · Matt · must · S · built

As Matt, I want choosing sleeves or a deck box to need the right to edit that deck, so that the API can't change a deck's kit that its page wouldn't let you change.

- Given User1 picked at home or signed in, when she posts `/api/accessories/assign` for a deck Played by user or either, then the answer is 403 'You can change the home decks played by you.', and nothing is saved.
- Given an intact product, then the assignment needs the product's kit rights (home's records to see, and the shared kit), not `products.edit`.
- Given a deck she may edit, then the assignment works as before.
- Given the Sleeves & boxes picker, then it offers to take or move sleeves only from holders the viewer may edit.

Now: built 2026-10-18 ([HISTORY.md, Choosing a deck's kit needs deck.edit](../HISTORY.md#choosing-a-decks-kit-needs-deckedit-2026-10-18)).

Evidence:
- `decklab/lib/api/accessories.py`: assign_accessory, _require_holder_rights
- `decklab/lib/inventory/ops_accessories.py`: _Holder
- `decklab/web/accessories.js`: movable
- `decklab/tests/test_api_accessories.py`: AssignTests

Review note: criterion 2 is the builder's reading of 'the product rights'; Matt hasn't confirmed it (requiring `products.edit` would take the product kit choice away from User1).

**E10-S43** · User1 · must · S · built

As User1, a home member, I want to change home's collection and tokens as Matt can, so that I can add the cards we get and fix a miscount without asking him.

- Given User1 is signed in or picked at home, when she saves home's collection, imports into it, adds a precon or saves home's tokens, then it succeeds as one change by User1.
- Given receipts, orders, products and the watchlist, then they stay a home admin's to change.
- Given a member of another space, then home's collection and tokens stay closed to them.

Now: built 2026-10-18 with E10-S29 ([HISTORY.md, Collections and tokens are seen only in their own space](../HISTORY.md#collections-and-tokens-are-seen-only-in-their-own-space-2026-10-18)).

Evidence:
- `decklab/lib/permissions.py`: SPACE_ACTIONS, ADMIN_ACTIONS
- `decklab/lib/api/collection_edit.py`, `decklab/lib/api/tokens.py`, `decklab/lib/api/precons.py`
- `decklab/tests/test_inventory_privacy.py`: HomeMemberTests

---

## E11: Run and trust the system

Keeping Deck Lab running, safe and believable, by Matt as the household's admin and by Claude Code working for him at the PC. It covers the server and its Cloudflare tunnel and "Deck Lab is off" page, the PostgreSQL database with its nightly backup, export, check and restore check, the audit trail on #/activity, the `python -m decklab.db` commands Claude works through (previews, `--expect` guards, `-m` messages, exit codes), the card data's background refresh, Forge upkeep and the Safari Simulator suite. Every write is one audited change set, Matt's own command-line writes are recorded as his, and backups are checked by restoring them.

Open: E11-S02, E11-S08, E11-S12, E11-S16, E11-S21, E11-S28, E11-S30, E11-S31, E11-S32, E11-S33.

**E11-S01** · Matt · must · M · built

As Matt, the household admin, I want to start, stop and restart Deck Lab from any window and see in one place whether it, its network and its tunnel are healthy, so that the household and members can reach it and I know what to fix when they can't.

- Given the task is installed, when I run `homenet start`, then it waits for the page to answer and prints its addresses, or shows the log lines written since this start.
- Given one server is running, when I run `start` again, then no second server starts and I'm told so.
- Given matchups are playing, when I run `homenet stop`, then they save every finished game before the server ends.
- Given the code changed since the server started, when I run `homenet status`, then it warns that the server is still running the old code and should be restarted.
- Given `homenet status` reports any PROBLEM line (server, network, firewall, tunnel), when it ends, then it exits 1.

Evidence:
- `decklab/lib/homenet/commands.py`: cmd_start, _start_task, cmd_stop, cmd_restart, cmd_status, check_tunnel
- `decklab/lib/homenet/checks.py`: check_network, check_firewall, exit_code
- `decklab/lib/server_run.py`: _stop_handler, _wait_for_matchup, FORGE_STOP_WAIT
- `scripts/decklab.cmd`; `decklab/README.md`, "Stop, start and restart"
- `decklab/tests/test_homenet.py`, `test_homenet_checks.py`

**E11-S02** · Matt · should · S · partial

As Matt, the household admin, I want members away from home to be told plainly when Deck Lab's PC is off or the server isn't started, so that they don't think it's broken.

- Given the server isn't running, when User1 opens decklab.example.com after signing in, then she sees a page saying Deck Lab is off (503, retrying by itself every 30 seconds), not a raw Cloudflare error; an `/api/` request gets a 503 JSON answer with reason `off`.
- Given the PC comes back, when she reloads (or the page retries), then the live page opens.
- Given the server answers, when any request passes through, then it reaches Deck Lab unchanged.

Decided (Matt, 2026-10-13): a friendly "Deck Lab is off" message is enough; cached last-seen deck lists are not wanted (E11-S27).

Now: the Worker was deployed on both hostnames behind Access on 2026-10-17 ([HISTORY.md, The "Deck Lab is off" Worker](../HISTORY.md#the-deck-lab-is-off-worker-and-the-user-testing-checklist-2026-10-17)).

Evidence:
- `decklab/cloudflare/worker.mjs`: handle, isOff, offResponse, OFF_STATUSES; `off-page.mjs`: offPage; `wrangler.toml`
- `decklab/lib/server_http.py`: ORIGIN_HEADER (`X-Deck-Lab-Origin` on every answer, in _send)
- `decklab/cloudflare/test/worker.test.mjs`; `decklab/tests/test_cloudflare_worker.py`: test_the_worker_tests_pass, test_the_worker_looks_for_the_servers_header
- `decklab/README.md`, "From outside the home"

Gap: checked live only without a sign-in (Access answers first). Matt still has to check, signed in on a phone, the off page with Deck Lab stopped and then started again, and a deck save and an accessory photo upload through the Worker.

**E11-S03** · Matt · must · L · built

As Matt, the household admin, I want the database backed up, copied off site and checked every night, with a restore actually tested, so that I can trust the data now that it no longer lives in git.

- Given the nightly task is installed, when 03:30 passes with me logged on, then backup, prune, the visits' prune, export and check run, and each is recorded in ops.backup_run.
- Given a night was missed because the PC was off, when it is next on, then the nightly runs as soon as possible.
- Given the last good restore check is older than `restore_check_days` (28), when nightly runs, then the newest dump is restored to a scratch database and its row counts and content digests are compared.
- Given a step failed, when I run `python -m decklab.db status`, then it shows the last dump, export, restore check and check that worked, a failed restore check or check with its detail, and a warning when the last good dump is too old; `check --history` lists each check run with its failed sub-checks, and `decklab/data/logs/db.log` names any failed step.
- Given the copy to the NAS fails, when backup runs, then the dump stays in the staging folder and the command exits 1.

Evidence:
- `decklab/db/schedule.py`: task_xml (03:30, InteractiveToken, StartWhenAvailable)
- `decklab/db/nightly.py`: run, _restore_check_if_due, restore_check_due
- `decklab/db/backup.py`: run_backup, copy_to, run_restore_check, status
- `decklab/db/check.py`: run, history
- `decklab/README.md`, "Backups", "The nightly check", "The nightly task"

**E11-S04** · Matt · should · M · built

As Matt, the household admin, I want the move to the database finished by retiring the file rollback once I'm confident in it, with a week of side-by-side checks written up, so that the old rollback tooling stops costing upkeep without risking data.

- Given the database had run cleanly for two nights, when Matt said yes on 2026-10-14, then phase 5b removed the rollback tooling and gates, after tagging the last commit that had them (`pre-phase5b`).
- Given the week of nightly checks from 2026-10-13 to 2026-10-19, when it ended, then a report in `magic/reports/` says whether every night's dump, prune, export, check and restore check worked, and names any failure.
- Given the week has ended (from 2026-10-20), when I run `python -m decklab.db status`, then it says the side-by-side checks ended on 2026-10-19.
- Given the week has ended, when the nightly decides whether a restore check is due, then it goes by the default `restore_check_days` (28), since `config.json` no longer overrides it.

Now: the week ended clean on 2026-10-19 ([HISTORY.md, The week of side-by-side checks ended](../HISTORY.md#database-the-week-of-side-by-side-checks-ended-2026-10-19-db1)).

Evidence:
- `magic/reports/2026-10-19-database-check-week.md`
- `decklab/config.json`: database.side_by_side_until
- `decklab/db/backup.py`: side_by_side_until, status
- `decklab/db/conn.py`: DEFAULTS (restore_check_days)

**E11-S05** · Matt · must · M · built

As Matt, the household admin, I want to be warned on any page, in plain words, when the server needs a restart, migrations are pending, a backup is stale or a check failed, so that I notice problems without opening a terminal.

- Given the checkout's code differs from the running server's, when anyone loads a page, then the banner asks for a reload or says the PC needs a restart.
- Given the last backup or check is older than `stale_backup_hours` (36) or a check failed, when an admin loads a page, then the banner says so, and a member doesn't see that detail.
- Given the database can't be reached, when anyone loads a page, then they're told wishlists, settings and play records can't be saved right now, and (when the inventory copy is stale) that the collection, decks, orders, products, watchlist and accessories can't be saved either; writes answer 503 quickly.
- Given a page update on an iPhone or iPad, when I use Reload page from the avatar menu or the update banner, then a fresh page and versioned scripts and styles load without clearing website data, and the current route and the editor's unsaved-changes guard are kept.

Evidence:
- `decklab/web/version.js`: versionInfo, databaseMessages, reloadDeckLab, showVersionWarning
- `decklab/web/shell.js`, `decklab/web/index.html`: `#menu-reload`
- `decklab/lib/dbstatus.py`: check, checks_warning, view; `decklab/lib/build.py` (restart_required, assets_changed)
- `decklab/lib/server_http.py` (`?v=` on every script and stylesheet URL)
- `decklab/README.md`, "The database warning banner"

**E11-S06** · Matt · must · L · built

As Matt, the household admin, I want to see who changed what, when and why, Claude's changes included, filtered to what each viewer may see, so that I can check that the work done for me matches what I asked.

- Given any database write, when it is saved, then it is one change set with an actor, a source and a non-blank message (enforced by the database).
- Given I open #/activity, when I filter by person (Claude included) or by kind, then I see plain headlines grouped by day, with messages and reasons and links to decks, cards and orders.
- Given a change touched another space, or User1's wishlist or accessories, when I view Activity, then I don't see those rows, and I see a change's message and reason only when I may see every row of it; an admin has no override.

Now: Activity has stayed within each viewer's space since 2026-10-18 ([HISTORY.md, Activity stays within its space](../HISTORY.md#activity-stays-within-its-space-2026-10-18)).

Evidence:
- `decklab/db/conn.py`: change; `decklab/db/migrations/0001_foundation.sql`, `0006_decks_accessories.sql` (`btrim(message) <> ''`)
- `decklab/lib/api/activity.py`: activity_view, visible_change
- `decklab/web/activity.js`: activityKinds, activityPeople, activityDayName, activityLink
- `decklab/tests/test_activity_privacy.py`: test_web_and_cli_mixed_messages_and_reasons_are_hidden_even_from_actor_and_admin
- `decklab/README.md`, "Activity"

**E11-S07** · Matt · should · S · built

As Matt, the household admin, I want my own command-line changes told apart from Claude's in the audit trail, so that Activity says honestly who made each change.

- Given I run a `python -m decklab.db` write myself, when I name myself with `--actor matt`, then Activity shows it as Matt's from the command line.
- Given Claude runs the same command, when no actor is given, then it shows as Claude's.
- Given an actor isn't a known profile (or is blank or reserved), when a write is attempted, then it is refused before anything is read or written.

Now: built 2026-10-15 for every audited write command; system maintenance keeps its own actors ([HISTORY.md, Name the person making command-line changes](../HISTORY.md#name-the-person-making-command-line-changes-2026-10-15)).

Evidence:
- `decklab/db/cli_actor.py`: add_argument, resolve
- `decklab/tests/test_cli_actor.py`: test_every_audited_leaf_accepts_an_actor_and_defaults_to_none, test_unknown_actor_is_refused_without_an_audited_write, test_profile_and_default_actors_reach_the_audit_trail_and_preserve_wishlist_privacy
- `decklab/README.md`, "Naming the command-line actor"

**E11-S08** · Matt · could · L · partial

As Matt, the household admin, I want to undo a wrong change from the audit trail, so that a mistaken receipt, merge or removal can be put right without asking Claude to work out the reverse.

- Given a simple change set (a collection or token edit), when I tap Undo on Activity, then an inverse change is previewed and saved as a new change set with its own message.
- Given rows have changed since, when I try to undo, then I'm told which rows conflict and nothing is written.
- Given a deck change, when I want it back, then the deck's History opens the old revision as a draft to save.

Evidence:
- `decklab/web/history.js`: historySheet, showRevisionEditor (Open as a draft)
- `decklab/web/activity.js`, `decklab/lib/api/activity.py` (read-only)

Gap: only deck revisions can be restored. Activity has no Undo, no inverse-change preview and no conflict check for inventory, token, wishlist or accessory change sets.

First slice: Undo on Activity for a single collection or token edit: an inverse change previewed, a conflict refused naming the rows, saved as a new change set.

**E11-S09** · Claude Code · must · L · built

As Claude Code, the command-line operator, I want every write command to preview, guard against concurrent edits, save one change set and return a meaningful exit code, so that I can carry out Matt's requests without clobbering User1's edits or leaving half-done changes.

- Given an order, product, watchlist, `collection merge`, `collection add-precon`, token or `deck push` write, when I pass `--dry-run`, then nothing is saved and I see what would change (for order and product writes, the decks whose tables would change); `receive` previews unless given `--apply`.
- Given a deck, token or accessory write, when the `--expect` revision or sha is stale, then nothing is written and I'm told to read it again.
- Given a write that takes `-m`, when it is blank or a removal has no `--reason`, then it is refused; `receive` and `deck tables --apply` record a default message naming what they changed.
- Given an order or receipt saved but its deck tables not refreshed, when it ends, then the exit code is 3 and stderr says why; an unreachable database exits 2.

Evidence:
- `decklab/db/inv_orders.py`: register, FOLLOW_UP_FAILED
- `decklab/db/inv_tokens.py`: _write; `decklab/db/inv_accessories.py`: expected; `decklab/db/inv_decks.py`: expected, _push
- `decklab/db/inv_receive.py`: run
- `decklab/db/conn.py`: change (blank message refused); `decklab/db/__main__.py`: main

**E11-S10** · Claude Code · should · M · built

As Claude Code, the command-line operator, I want any write that leaves other decks' owned-vs-needed tables stale to name those decks and the follow-up command, or to refresh them in the same change, so that the tables never drift out of date because a follow-up step was forgotten.

- Given `collection merge` or `collection add-precon` succeeds, when other decks' tables are now stale, then it prints them and `python -m decklab.db deck tables --apply -m "..."`, or, when that would refuse, every problem in its way.
- Given `deck push` or `deck new` of a built deck changed what is in use, when other decks of its space are affected, then it names them too, not only its own deck.
- Given order, product and receive writes, when they save, then they refresh the tables in the same change.
- Given a token card is added, edited or removed, then no table changes, so the token commands say nothing about tables.

Now: built 2026-10-13. Left open (low): "now out of date" also lists decks that were already out of date before the write.

Evidence:
- `decklab/db/inv_decks.py`: stale_notes; `decklab/db/inv_collection.py`: _merge
- `decklab/lib/pool.py`: table_blockers
- `decklab/tests/test_collection_ops.py`: test_merge_names_the_space_s_decks_whose_tables_are_now_out_of_date
- `decklab/tests/test_inv_decks.py`: test_push_names_the_other_decks_whose_tables_are_out_of_date, test_push_names_what_would_stop_deck_tables

**E11-S12** · Claude Code · could · S · partial

As Claude Code, the command-line operator, I want refusals and errors in plain words that describe the database world and say what to do next, so that I don't send Matt after files that no longer exist.

- Given a refusal or warning from a database-backed command or page, when it is shown, then it names the database record (a token row by its number in `tokens list`, a product by its name), never an old file such as `magic/tokens.csv line N` or `products/status.csv`. Names of scratch files the user handed in are kept.
- Given a stale `--expect` on a token, accessory or deck write, when it is refused, then it says what changed and which listing or pull to run again.
- Given the database is down, when any inventory command runs, then it exits 2 with one line saying so.

Evidence:
- `decklab/db/inv_tokens.py`: _write; `decklab/db/inv_accessories.py`: expected; `decklab/db/inv_decks.py`: expected
- `decklab/db/__main__.py`: main (exit 2)
- `decklab/lib/pool.py` (the `products/status.csv lists ...` warning)

Gap: criterion 1 is unverified. The token rules' old-file wording now occurs only in the files test backend, and no database-facing refusal naming an old file has been reproduced; the pool's `products/status.csv lists ..., which isn't in magic/products/` warning is the one left to check.

**E11-S13** · Matt · must · M · built

As Matt, the household admin, I want the card data (names, printings, oracle tags, Game Changers) kept fresh without me remembering to update it, so that name checks, stats and bracket checks use current Scryfall data.

- Given the server is running, when a day passes, then it checks the card data and downloads any bulk file over a week old.
- Given Scryfall can't be reached, when an update fails, then the local copy is kept and it retries in 10 minutes.
- Given I open Settings, About Deck Lab, when the page loads, then it shows the card data's state.
- Given a fresh clone, when I run `python -m decklab.lib.cards update`, then the index is built.

Evidence:
- `decklab/lib/cards.py`: update, MAX_BULK_AGE
- `decklab/lib/server_run.py`: _update_loop, UPDATE_EVERY, RETRY_AFTER
- `decklab/lib/api/carddata.py`: update_cards, status
- `decklab/web/settings.js`: showSettings (`#settings-cards`)
- `decklab/tests/test_cards.py`

**E11-S15** · Matt · should · L · built

As Matt, the household admin, I want a guided way to move Deck Lab's Forge onto a new release and check it, so that an upgrade like 2.0.16 doesn't silently break the card log, the overrides or the comparability of results.

- Given a new build is installed, when I run the post-build check, then cardlog-check, serve-check and the overrides' upstream check all run, with one summary.
- Given the engine changed, when the check ends, then it prints `replay --dry-run`'s games and rough time.
- Given the card log fails its check, when runs start, then they play plain Forge and the page says per-card stats are off.

Now: built 2026-10-21 ([HISTORY.md, A Forge upgrade check in one command](../HISTORY.md#a-forge-upgrade-check-in-one-command-2026-10-21-e11-s15)). `python -m decklab.lib.forge upgrade-check` runs cardlog-check, serve-check and `overrides check` in order, going on past a failure, with one summary (passed, failed and why, or skipped and why), then `replay --dry-run`'s matchups, games and rough time when saved results were played with another engine; it exits 0 only when all three passed. `--plan TAG` prints the rebase, build and install steps and runs nothing. The third criterion already held: a failed cardlog-check is noted (`simjar.record_failed`), runs then get no card log and play plain Forge, and the page's status note says "Per-card stats are off" with the reason. Not yet run on a real release: its first real use is the 2.0.16 upgrade (TODO.md, FG#2); the rebase and build stay manual.

Evidence:
- `decklab/lib/forge/cli_upgrade.py`: upgrade_check, _run_step, _print_replay, _plan, _cmd_upgrade_check
- `decklab/lib/forge/cli_results.py`: _print_replay_plan (replay --dry-run's lines, shared)
- `decklab/lib/forge/cli_checks.py`: _cardlog_check (record_failed on a failed check)
- `decklab/lib/forge/simjar.py`: record_failed, _checked_problem, card_log (not ready after a failed check)
- `decklab/lib/forge/runner.py`: the run's setup["card_log"] (plain Forge when it isn't ready)
- `decklab/web/matchups-overview.js`: forgeBox ("Per-card stats are off" and why)
- `decklab/tests/test_forge_upgrade_check.py`; `decklab/tests/test_forge_cardlog_check.py`: test_cardlog_check_notes_when_the_engine_plays_other_games_than_plain_forge; `decklab/tests/test_forge_simjar.py`: test_a_failed_check_turns_a_checked_version_off; `decklab/tests/test_web_matchup_files.py`: test_card_log_on_or_off_is_said
- `decklab/README.md`, "Deck Lab's own Forge" (Moving to a new Forge release)

**E11-S16** · Matt · could · L · partial

As Matt, the household admin, I want to adopt AI fixes (card-script overrides, pilots) and run experiments with clear checks, so that Forge's verdicts get more trustworthy over time without breaking results.

- Given an experiment spec, when I run `forge experiment spec.json --dry-run`, then I see the games and time it would take.
- Given an experiment finished, when I read its report, then each arm says adopt, don't adopt or more games.
- Given I adopt an override set, when its matchups are re-keyed, then `replay --dry-run` lists what needs replaying.

Evidence:
- `decklab/lib/forge/cli_evaluate.py`: _cmd_experiment, _print_experiment_plan
- `decklab/lib/forge/experiment_analysis.py`: recommend
- `decklab/lib/forge/cli_commands.py`: _cmd_overrides; `decklab/lib/forge/cli_results.py`: _cmd_replay

Gap: criterion 1 isn't met: the experiment dry run lists games per arm and in total but gives no time estimate (the field dry run does). Adopting still means editing `overrides/sets.json` or `simulation.json` by hand.

Review note: holds two needs (adopting fixes, running experiments) and overlaps E3-S20; adoption without hand edits could be its own story.

**E11-S17** · Matt · wont · M · not_wanted

As Matt, the household admin, I want simulation results protected like the rest of the data, so that a disk problem doesn't wipe weeks of Forge games.

- Given the nightly task runs, when it finishes, then the Forge results folder is copied somewhere off the PC, or status says plainly that it isn't covered.
- Given a restore, when I follow the runbook, then matchup results come back alongside the database.

Decided (Matt, 2026-10-13): Forge results don't need backing up; they can be regenerated.

**E11-S20** · Claude Code · could · S · built

As Claude Code, the command-line operator, I want a receive preview and its later `--apply` to be linked on the command line, so that a change made in between (a Tokens page save) can't slip into a receipt I previewed.

- Given I ran `receive --order ID`, when it prints a preview token, then `--apply --expect TOKEN` applies only if the inventory and the receipt's intent (order, selected components and rows, arrival date and supplied checks) match that preview.
- Given the inventory changed, when I apply with a stale token, then nothing is written and I'm told to preview again.
- Given no token, when I apply, then it re-checks its blockers at that moment.

Now: built 2026-10-18 ([HISTORY.md, Dated Stats disclosures and guarded CLI receipts](../HISTORY.md#dated-stats-disclosures-and-guarded-cli-receipts-2026-10-18)).

Evidence:
- `decklab/db/inv_receive.py`: register (`--expect TOKEN`), run, _preview_token
- `decklab/tests/test_receipt_cli_preview.py`: test_unchanged_preview_applies_once_and_refreshes_its_deck, test_any_inventory_change_refuses_before_receipt_audit_or_deck_changes, test_invalid_preview_has_no_token_and_legacy_apply_still_revalidates

**E11-S21** · Claude Code · could · S · missing

As Claude Code, the command-line operator, I want command-line reads of private data outside the requester's own space or ownership to be labelled private, so that I don't repeat it to anyone outside that space, Matt included.

- Given I run `wishlist list user1`, when it prints, then a header says the list is private to its owner, and the wishlist commands' help says audit messages never quote wishlist notes.
- Given `accessories list` prints rows, when it prints, then each row not shared is marked private to its owner.
- Given `collection list --space user2`, `tokens list --space user2` or `deck list --space user2`, when it prints, then a header says the data is private to that space unless the owner made it public.

Evidence:
- `decklab/db/wishlist_cli.py`: _list (no header; the guidance is only in the module docstring)
- `decklab/db/inv_accessories.py`: _line (shows the owner, no private mark)

Gap: no command labels private data; `accessories list` only shows each row's owner.

**E11-S23** · User5 · should · M · built

As a member who signs in through decklab.example.com (User2, User3, User4 or User5), I want Deck Lab to be running whenever I'd reasonably want it, not only when Matt has started it by hand, so that I can look at my decks without asking Matt to switch it on.

- Given Deck Lab's task is installed with start at logon, when the PC starts and Matt logs on, then Deck Lab and its tunnel start without anyone running a command.
- Given Matt wants it off, when he stops it, then it stays stopped until he starts it again or he next logs on.

Decided (Matt, 2026-10-13): Deck Lab starts at logon; starting before anyone logs on isn't wanted, since the PC stays logged on while it's on (E11-S24). Restarting after a crash is E11-S26.

Now: turned on 2026-10-13 with `homenet install --at-logon`.

Evidence:
- `decklab/lib/homenet/commands.py`: cmd_install (at_logon)
- `decklab/lib/homenet/task.py`: task_xml (LogonTrigger), parse_task_xml

**E11-S24** · Matt · wont · M · not_wanted

As the household admin, I want the nightly backup, export and check to run even on nights I'm not logged on to the PC, so that the data's safety net doesn't depend on my login.

- Given the PC is on and nobody is logged on, when the nightly time comes, then backup, prune, export and check run and are recorded in ops.backup_run.
- Given the NAS credentials, when the task runs without a logon, then it reaches the NAS without storing a password in the repo.

Decided (Matt, 2026-10-13): not wanted. The PC stays logged on while it's on; the nightly's catch-up run after the PC was off is in E11-S03, and the stale-backup warning in E11-S05.

**E11-S25** · Claude Code · could · M · built

As the command-line operator, I want `collection merge`, the `tokens add/edit/remove` commands, `deck push` and `receive` to offer the same preview and audit message as the order, product and watchlist writes, so that I can show Matt exactly what a change will do before writing, whichever command it is.

- Given `collection merge FILE --dry-run`, when it runs, then it prints the printings and quantities it would add, the basics it would skip and the raw import it would keep, and writes nothing.
- Given `tokens add`, `edit` or `remove` with `--dry-run`, when it runs, then it prints the row before and after and writes nothing.
- Given `deck push ID FILE --dry-run`, when it runs, then it prints the text diff against the current revision and its checks (table, names, tokens, sleeves and deck box) and writes nothing.
- Given `receive --apply`, when it saves, then it records a default message naming the order and the components received.
- Given any of these previews, when it runs, then it checks everything the real write checks (messages, reasons, `--expect`, kit rules).

Now: built 2026-10-18 ([HISTORY.md, Non-writing CLI merge, token and deck previews](../HISTORY.md#non-writing-cli-merge-token-and-deck-previews-2026-10-18)).

Evidence:
- `decklab/db/inv_collection.py`: register, _merge, _merge_preview
- `decklab/db/inv_tokens.py`: register, _write; `decklab/db/inv_decks.py`: register, _push
- `decklab/db/inv_receive.py`: run (default message)
- `decklab/tests/test_cli_write_previews.py`: test_merge_reports_deltas_skipped_basics_and_exact_raw_import_without_writing, test_token_previews_show_complete_before_and_after_rows, test_push_preview_shows_diff_and_checks_the_proposed_list, test_valid_and_refused_previews_leave_database_evidence_unchanged

**E11-S26** · User5 · could · S · built

As a member who signs in through decklab.example.com (User2, User3, User4 or User5), I want Deck Lab restarted if it stops unexpectedly, so that a crash doesn't leave it off until Matt notices.

- Given Deck Lab stopped unexpectedly (not by `homenet stop`), when the background task notices, then it restarts it within a few minutes.
- Given Matt stopped it on purpose, when the task checks, then it stays stopped.

Design (2026-10-20): a second task, "Deck Lab watchdog" (installed only with `install --at-logon`; plain `install` and `remove` delete it), runs `pythonw.exe -m decklab.lib.homenet ensure` every 5 minutes while Matt is logged on and starts the server through the "Deck Lab" task only when that task is there, enabled and starts at logon, nothing answers or holds the port, no live server is recorded, the logon and the last start that was asked for are both at least 2 minutes ago (so a check landing in the logon trigger's 30-second delay or in a start neither starts it early nor records a false restart), there's no stop marker (`decklab/data/stopped-<port>.json`, with the session's logon time: written by `homenet stop` and `server.py --stop` before they signal, by `install --at-logon --no-start` while Deck Lab is off, and by a server stopped on request (stop event, taskkill without /F, Ctrl+C, closing its console window); cleared by start, restart, install and by the server once it's listening, so the next logon also ends it, and ignored from an earlier logon) and it hasn't given up (3 restarts in a row that didn't stay up 10 minutes). A restart whose stop times out leaves a restart's marker instead, so the watchdog starts the server once it has stopped. A hung but live server isn't killed. A crash, a hard kill without a prior stop, or a shutdown counts as unexpected.

Now: built 2026-10-20 and turned on the same day: Matt ran `homenet install --at-logon --no-start` and `restart`, and `status` shows "OK Restart after a crash".

Evidence:
- `decklab/lib/homenet/watchdog.py`: decide (since, WATCHDOG_GRACE, a restart's marker), reset (asked_at), cmd_ensure, check_watchdog, status_lines
- `decklab/lib/homenet/task.py`: watchdog_xml, watchdog_arguments, parse_task_xml (repeats)
- `decklab/lib/homenet/commands.py`: cmd_install (_install_watchdog, _leave_off), cmd_stop, cmd_start, cmd_restart (a restart's marker), cmd_remove, main (ensure)
- `decklab/lib/control.py`: mark_stopped (restart), read_stopped, clear_stopped, logon_time; `decklab/lib/server_run.py` `_serve`, `ctrl_handler`/`_console_handler` (window closed); `decklab/server.py` `_stop`
- `decklab/tests/test_homenet_watchdog.py`, `test_control.py` (StopMarkerTests), `test_server_lifecycle.py` (CtrlCTests, MainTests)
- `decklab/README.md`, "Start it", "Stop, start and restart", "The log", "When a phone can't reach it"

Gap: not turned on yet on Matt's PC (install --at-logon --no-start, then restart).

**E11-S27** · User1 · wont · M · not_wanted

As a member away from home, I want my phone to show the last-seen state of a deck (its list and missing cards, labelled with when they were saved) while Deck Lab's PC is off, so that I can still check a deck.

- Given she visited a deck before, when the PC is off, then the phone shows the last-seen list and missing cards, labelled with when they were saved.
- Given the PC comes back, when she reloads, then the live page replaces the cached one.

Decided (Matt, 2026-10-13): when the PC is off, a friendly "Deck Lab is off" message is enough (E11-S02); cached last-seen deck lists are not wanted.

<a id="e11-s28"></a>

**E11-S28** · Matt · should · M · partial

As Matt, I want to watch User2, an experienced Magic player using Deck Lab for the first time, do everyday jobs in it, so that I can find where a first-time user needs clearer navigation, wording or feedback.

- Given the session is being prepared, when the checklist is written, then it uses User2's usual device and browser (confirmed with him, not assumed), plain goal-based prompts without click-by-click instructions, and an observable success condition for each task; tasks may assume Magic fluency.
- Given the checklist is prepared, then it covers signing in at decklab.example.com and returning later; finding one of his decks; finding a card and reading its rules; explaining owned versus missing cards; making, saving and checking a small deck change; finding a card in his collection and updating its quantity; adding a card to his wishlist; and recording a game where his space supports it. Tasks follow what he wants to do and what exists on the day, using disposable data or changes he wants to keep, with cleanup agreed before any edits.
- Given card searching and filtering are tested, then a goal such as "Find creatures with vigilance" is included, combined with a colour or mana-value limit where supported; an unsupported filter is recorded as an unmet need.
- Given User2 attempts each task, when Matt observes, then he lets User2 try first, invites him to say what he expects, makes clear the software is being tested, and records unaided completion, completion with help or non-completion, with hesitations, wrong turns, unclear wording, errors and help kept apart from User2's comments.
- Given a task has been attempted, then the notes use a repeatable row: task and success condition; outcome; observed problem and where; help needed; User2's words or a labelled paraphrase; impact (blocks the task, needs help, or minor friction); follow-up; with date, device, browser and app version recorded once.
- Given the session ends, when feedback is collected, then it asks what was confusing, what felt easy, what is missing and whether he would use it without Matt there, keeping praise and unmet needs as well as failures, without treating one participant as representative.
- Given the notes are reviewed, then problems are ranked by impact, linked to existing or new stories, and actionable work is added to TODO.md; User2's private cards, decks, games and wishlist stay out of shared notes unless anonymised or he agrees.

Now: checklist prepared 2026-10-17 ([HISTORY.md, The "Deck Lab is off" Worker, and the user-testing checklist](../HISTORY.md#the-deck-lab-is-off-worker-and-the-user-testing-checklist-2026-10-17)); recheck its "where it is" notes on the day.

Evidence:
- `decklab/design/user-testing-user2.md` (tasks T1-T11 with success conditions, T9 the vigilance goal, section 5's per-task notes block)

Gap: criteria 2, 3 and 5 are met by the checklist. Still to do: confirm his device and browser with him, run the session, collect feedback and do the follow-up review (criteria 1, 4, 6, 7).

<a id="e11-s29"></a>

**E11-S29** · Matt · should · L · built

As Matt, I want repeatable automated Safari tests across simulated iPhones and iPads on my Mac, so that checking mobile changes is faster and more reliable than repeating the same tasks by hand on every device.

- Given a fresh clone on a supported Mac, when the documented setup is followed, then it installs pinned test dependencies and identifies the required Xcode, runtimes and simulator models; a missing prerequisite gives an actionable error.
- Given setup is complete, when one documented command runs, then it starts an isolated Deck Lab test instance with disposable fixture data and runs Safari tests for iPhone 15 Pro, iPhone 17 Pro and an 11-inch iPad in portrait and landscape, recording the exact model, runtime and source revision; an unavailable configuration is reported, never counted as a pass.
- Given receipt inspection opens, then the navigation controls and swipe hint are visible without scrolling, the image has its intended size and nothing overflows sideways; a native gesture on the image or its margin advances exactly one card, and vertical scrolling neither advances cards nor navigates back.
- Given Quick edit is used with the software keyboard showing, then Save is reachable, the edit persists and History attributes it correctly; card-viewer swipes, Share and Add to Home Screen, standalone safe areas and stale-page reload are covered too, using native UI rather than direct JavaScript calls.
- Given a run completes or fails, then it returns a useful exit code and a per-device, per-orientation report with assertions, failure screenshots and logs; layout checks measure visible bounds.
- Given tests save decks or receive deliveries, then they touch only disposable test data, never the household server, the production database or private household data, and fixture setup and cleanup are repeatable.
- Given the suite passes, then its evidence is recorded as Simulator coverage linked to E2-S22, separately from physical-device acceptance.

Now: built 2026-10-15; run `20261015T051426Z-59b4e5` passed all 60 checks on clean source ([HISTORY.md, Safari Simulator regressions validated](../HISTORY.md#safari-simulator-regressions-validated-2026-10-15)).

Evidence:
- `decklab/safari/README.md`, `decklab/safari/EVIDENCE.md`
- `decklab/safari/runner.py`: run_configuration, write_reports, Recorder
- `decklab/safari/fixture.py`: FixtureServer; `decklab/safari/flows.py`: receipt_layout, receipt_swipe
- `decklab/tests/test_safari_runner.py`, `test_safari_fixture.py`

<a id="e11-s30"></a>

**E11-S30** · Matt · should · L · partial

As Matt, I want Deck Lab to look like one app with two densities, casual on the phone and a "lab" on the desktop, so that User1 and the members find it friendly on their phones while I get a dense tool for building, buying and testing decks, and the Forge results that set it apart from collection apps are visible where we already look.

- Given the phone or the iPad in portrait, when any page opens, then it uses the casual density of [visual-design.md](visual-design.md): mana-tinted deck tiles, words for counts and 44 px targets.
- Given a window 1000 px or wider (the desktop or the iPad in landscape), when the library, a deck page, Matchups, Collection or Shopping opens, then it uses the lab density: a list beside the selected item's detail, mono numerals, and keyboard hints only with a fine pointer; on a touch screen every target stays 44 px.
- Given either density, then teal is the only action and selection colour, deck colours appear only on decks, and both themes (light and dark) pass 4.5:1 text contrast.
- Given a tested casual deck, when the library or its Overview shows, then its field win rate and how long ago it was tested show without opening Matchups (this meets E1-S12 too).
- Given the fonts, then Figtree and JetBrains Mono are self-hosted; the page still loads nothing from the internet.
- Given each rollout slice in visual-design.md section 7, when it ships, then it ships alone on the existing UI kit with its tests, a device check in both themes and UI-KIT.md updated in the same commit.

Decided (Matt, 2026-10-24): "P1, split lab + mana decks", chosen from three rounds of concepts and checked on the hard screens, dark mode and the iPad; light and dark stay a user setting. Also: the same chrome on every page (the editor keeps the tab bar); a running job shows only as an animated activity icon whose details (progress, Stop) open on a tap; portrait (under 1000 px, the iPad included) uses the phone's chrome and landscape the full top bar.

Now: slice 1, the self-hosted fonts, built 2026-10-24 ([HISTORY.md, Self-hosted typefaces](../HISTORY.md#self-hosted-typefaces-2026-10-24-e11-s30-slice-1)); criterion 5 is met. Slice 2, P1's colours in both themes, built 2026-10-24 ([HISTORY.md, P1 colour tokens](../HISTORY.md#p1-colour-tokens-2026-10-24-e11-s30-slice-2)). Slice 3, the density tokens, built 2026-10-24 ([HISTORY.md, P1 density tokens](../HISTORY.md#p1-density-tokens-2026-10-24-e11-s30-slice-3)). Slice 4, the shared components restyled (buttons, segmented, toggle chips, stepper, fields, menus, notices, sheets, the action bar, `table.data`), built 2026-10-24 ([HISTORY.md, P1 components](../HISTORY.md#p1-components-2026-10-24-e11-s30-slice-4)), with section 6 question 2 decided by Matt (changed lines teal, "Part received" a neutral outline, avatars per person). Slice 5, a deck's colour pieces (pips, stripe, tint, swatch) from its colour identity in one helper, used by the library and the deck page's head, built 2026-10-25 ([HISTORY.md, P1 deck colours](../HISTORY.md#p1-deck-colours-2026-10-25-e11-s30-slice-5)). Slice 6, Forge's result pieces (win-rate figure, range bar on 20–80%, freshness badge, flags, swap-test result) used on Matchups and the deck page's Forge parts, and the run activity icon with its details in place of the floating pill (Matt's section 6 decision 3), built 2026-10-25 ([HISTORY.md, P1 simulation components](../HISTORY.md#p1-simulation-components-2026-10-25-e11-s30-slice-6)). Slice 7, the shell, built 2026-10-25 ([HISTORY.md, P1 shell](../HISTORY.md#p1-shell-2026-10-25-e11-s30-slice-7)): the phone's header and tab bar under 1000 px (the iPad in portrait included), the lab's round nav pills, and the tab bar under every page's bar; without search (E11-S31). Slice 8, the library, built 2026-10-25 ([HISTORY.md, P1 library](../HISTORY.md#p1-library-2026-10-25-e11-s30-slice-8)): casual tiles with the owned bar, the lab's rows beside the selected deck's detail pane (J/K, Enter), and each tested casual deck's field win rate and freshness from a cached field average (Matt's choice), which meets criterion 4's library half.

Evidence:
- `decklab/design/visual-design.md` (the spec, the open questions and the rollout slices)
- `decklab/web/fonts/` and `decklab/fonts-licences/` (the woff2 files, their licences and the subset command); `decklab/web/base.css` (@font-face), `decklab/web/tokens.css` (--font, --font-mono), `decklab/web/index.html` (the preload); `decklab/lib/server_http.py`: STATIC_TYPES, STATIC_FOLDERS
- `decklab/tests/test_web.py`: test_the_typefaces_are_self_hosted_and_preloaded; `decklab/tests/test_server.py`: test_the_page_files_with_their_types, test_static_files_list
- `decklab/web/tokens.css` (P1's colours and shadows, light and dark); `decklab/tests/test_web.py`: test_themes
- `decklab/web/tokens.css` (the density tokens' three levels); `decklab/tests/test_device_layout_ui.py`: DensityTokenTests
- `decklab/web/components.css`, `decklab/web/cards-ui.css`, `decklab/web/base.css` (the P1 components); `decklab/tests/test_device_layout_ui.py`: ComponentTests
- `decklab/web/ui.js`: deckColourPieces; `decklab/web/library.js`: libColours, deckCover, deckCard; `decklab/web/deck.js`: deckHeader, deckPageColours; `decklab/lib/api/library.py`: deck_colors; `decklab/tests/test_device_layout_ui.py`: DeckColourTests, DeckColourUiTests; `decklab/tests/test_cover.py`: test_the_colours_of_a_list
- `decklab/web/shell.css` (the casual header and tab bar under 1000 px, the lab's nav pills, the iPad's 640 px tabs, the Matchups tab's dot), `decklab/web/shell.js`: TAB_COUNT, drawShell; `decklab/web/runs-pill.js`: drawRunsPill; `decklab/web/tokens.css`: --bar-h; `decklab/tests/test_device_layout_ui.py`: ShellTests; `decklab/tests/test_shell_ui.py`: test_the_nav_and_tab_bar_follow_who_is_looking, test_the_matchups_tab_has_a_dot_while_forge_plays
- `decklab/web/library.js`: deckCard, deckRow, libDetail, statusRows, libKeys, deckOwned, deckForgeLine, deckRowForge, libDetailForge; `decklab/web/ui.js`: ownedBar; `decklab/lib/api/library_forge.py`: library_forge_view; `decklab/lib/forge/field.py`: averages; `decklab/tests/test_library_ui.py`: test_the_lab_has_rows_beside_the_selected_decks_detail, test_tested_decks_have_a_forge_line_tiles_rows_and_detail; `decklab/tests/test_library_forge.py`
- `decklab/web/sim-ui.js`: winRateFigure, rangeBar, freshnessBadge, forgeFlag, swapResult; `decklab/web/runs-pill.js`: drawRunsPill, openRunDetails, runDetailsParts; `decklab/web/matchups-overview.js`: resultRow; `decklab/web/matchups-results.js`: resultPart; `decklab/web/field.js`: fvHeadline, fvChips, fvRows; `decklab/web/variant.js`: vtTestItem; `decklab/tests/test_device_layout_ui.py`: SimComponentTests, SimComponentUiTests; `decklab/tests/test_forge_stop_ui.py`; `decklab/tests/test_web_matchups.py`: RunsPillTests

Slice 9's first part built 2026-10-25: the lab hero, stripe and tint metadata, narrow folded actions, Overview's saved Forge field summary and newest swap test, and the identity-coloured mana curve (`deck-overview.js`, `deck-overview.css`, `test_deck_overview_ui.py`). The saved field summary meets criterion 4's Overview half. Five existing tabs are retained; run controls remain in Field view. Chromium fixture checks cover both themes at the nine documented viewport sizes with mouse input, not touch or Safari.

Slice 9's navigation and Last changed metadata built 2026-10-25: fresh server-visible previous/next links, filters and tab/list selection preserved, disabled ends, and actual recorded edit dates in the tint band. The narrow hero reserves navigation space for maximum-length titles. `test_deck_header_ui.py` and `test_deck_changed.py` cover the UI lifecycle, races, dates and server privacy.

Slice 10's first part built 2026-10-25: one selected deck's opponents as a mouse lab table, casual cards and coarse-input lab links, the simulations-mode chip, and shared Rankings figures. The shared entry model preserves pair choice, perspective, saved links and exception/permission handling. No field summary or residual is inferred from pair data.

Slice 10's selected-list summary built 2026-10-25: exact Planned or built Play-now context, the server's field rating/flags/first-player edge and newest recorded swap. Bounded cached reads follow the selection and reject stale answers; historical tests retain their tested cards. All tests focuses its existing destination and late content keeps it visible until manual scrolling. `test_matchup_selected_summary_ui.py` covers lifecycle, failures and independent refresh; `test_deck_overview_ui.py` covers the incoming link and scroll-anchor behavior.

Slice 11's Collection metadata built 2026-10-25: explicit unknowns and density-aware details, neutral special-finish pills, missing-details notice/storage filter, visibly named all-filtered-row bulk scope, and dated per-copy estimates. `collection-rows.js` extracts presentation from the existing editing/guard flows; supported language choices match the backend. `test_collection_metadata_ui.py` covers accessibility, filters, bulk scope and dates.

Slice 11's lab table columns built 2026-10-25: card identity/type and separate finish/usage metadata, honest unknowns, container-based hiding, 36px mouse rows and a named keyboard scroll region with local sticky header. Wide table widths fit their panes; the narrow 1000px edge retains local horizontal scrolling. `test_collection_columns_ui.py` checks metadata semantics, unchanged canonical data, hiding order and density floors.

Slice 11's Collection keys built 2026-10-25: filtered J/K selection across pages, Enter into the current card's viewer with fresh visible focus return, and guarded unknown-card edit/read-only fallbacks. The hint is fine-pointer/hover lab only. `test_collection_keys_ui.py` covers page boundaries, off-page Enter, captions, stale contexts and permissions.

Slice 12's Shopping frame built 2026-10-25: 560px list pane, stacked through 1280px; retained delivery/follow-up Undo/history nodes, honest empty and last-row transitions, and focused jump destinations. Queue identity, write permissions, shortfall semantics and receipt contracts are retained. `test_shopping_layout_ui.py` covers these lifecycle and layout boundaries. Dense queue grouping/radio matching, compact delivery expanders and Receive delivery remain.

Slice 11's Collection layout built 2026-10-25: the exact printing/finish preview beside the lab table, casual rows with 24-row Show more and focus progression, sticky search/filter sheet, recorded notes and alternate-printing warnings. Shared canonical rows and filters keep editing guards and bulk scope; storage wording retains guesses and untracked basic lands. `test_collection_layout_ui.py` covers lifecycle, permissions, selection, filters and increment behavior.

Gap: slices 9 and 10's touch/Safari acceptance; slice 11's Find cards presentation and named per-printing holder source, slice 12's dense queue/delivery presentation and Receive delivery (its page frame is built), then slices 13 to 15 (criteria 1 to 3 and 6). Device checks do not block coding. Section 6's question 4 is settled (Matt, 2026-10-25: only Building and Idea tiles show a status pill). The lab top bar's search is E11-S31.

<a id="e11-s31"></a>

**E11-S31** · Matt · could · M · missing

As Matt, I want one search in the top bar that finds a deck or a card from any page, so that I don't have to open Decks or Collection first to find something.

- Given the lab top bar (1000 px and up), when I press `/` or click the search field, then I can type a deck's or a card's name and pick a result that opens its page; a page's own list search moves to `F` ([visual-design.md](visual-design.md) 3.3).
- Given the casual header, when I tap its search icon (a 300 px field on the iPad in portrait, 3.2), then the same search opens as a sheet, with 16 px text so iOS doesn't zoom.
- Given a viewer, then the results hold only the decks and collections that viewer may see (E10-S29, E10-S30), and a hidden one is never named.

Decided (Matt, 2026-10-25): left out of E11-S30's slice 7 (the shell) as its own story, since Deck Lab had no global search to restyle. Still to settle before building: what it searches (decks, the viewer's collection, every Scryfall card) and how results are grouped.

Gap: everything; nothing built.

**E11-S32** · Matt · could · M · missing

As Matt, publishing Deck Lab for others to run on their own PC, I want a ready-built copy of Deck Lab's Forge fork to download, so that a newcomer gets simulations without cloning and building Forge with Maven.

- Given a release of the fork (matt439/forge), then it holds the built install for the Forge release it's based on, with a checksum, and names that Forge version.
- Given SELF-HOSTING.md, when a newcomer reaches the Forge step, then the download is the first route and building from source is the second.
- Given a downloaded install, when `python -m decklab.lib.forge` checks it, then it says whether the install matches what this Deck Lab expects, and how to fix it if not.
- Given FG#2's rebase onto a new Forge, then making the next release is one documented step of the upgrade.

Evidence:
- `SELF-HOSTING.md`: the Forge steps (download Forge's release, clone the fork with its tags, build, `decklab/install.py`)

Gap: everything; there's no prebuilt release. Raised 2026-10-25 by the self-host check.

First slice: a script in the fork that packs the installed build as a release archive with a checksum, one release for 2.0.15, and SELF-HOSTING.md pointing to it.

**E11-S33** · Matt · could · L · missing

As Matt, publishing Deck Lab for others to run on their own PC, I want Deck Lab to run on Linux as fully as it does on Windows, so that a self-hoster on Linux doesn't hit Windows-only steps or failing tests.

- Given a Linux checkout, when the whole test suite runs, then it passes, with no test assuming Windows paths or a case-insensitive file system.
- Given Linux, when `python -m decklab.db schedule` runs, then the nightly backup, prune, export and check are set up through a systemd user timer (or cron) instead of Task Scheduler.
- Given Linux, when `python -m decklab.lib.homenet` installs or restarts the server, then it uses a systemd user service, and `status` reports it as on Windows.
- Given SELF-HOSTING.md, then the Linux route has no "a few tests fail" caveat and no hand-written service step.

Evidence:
- `decklab/db/schedule.py`: Task Scheduler XML through schtasks only
- `SELF-HOSTING.md`: Linux runs the server under the user's own service manager; a few tests fail on Linux
- The 2026-10-25 self-host check: 31 of 6188 tests failed on Linux

Gap: everything. Raised 2026-10-25 by the self-host check.

First slice: fix the 31 Linux test failures, then add a Linux CI run so they stay fixed.
