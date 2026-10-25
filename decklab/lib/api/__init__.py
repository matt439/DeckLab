"""The JSON answers behind Deck Lab's web page, as plain functions.

server.py maps each URL to one of these and sends the result as JSON; keeping
them free of HTTP means the tests can call them directly.

Usage:

    from decklab.lib import api
    api.status()                          # GET /api/status
    api.profiles()                        # GET /api/profiles
    api.get_settings("matt")              # GET /api/profiles/matt/settings
    api.put_settings("matt", b'{"theme": "dark"}')    # PUT, the request body as bytes
    api.commander_night_view()             # GET /api/commander-night: private home notes
    api.change_commander_night(body)       # PUT: home admin, expected complete revision
    api.get_wishlist("matt")              # GET /api/profiles/matt/wishlist
    api.change_wishlist("matt", body)      # POST one add/remove operation
    api.decks_index()                     # GET /api/decks
    api.deck_view("casual/gruul-ramp", "owned")       # GET /api/deck?id=...&version=...
    api.goldfish("casual/gruul-ramp", "target")       # GET /api/goldfish?id=...&version=...[&retry=1]
    api.search("llan", "10")              # GET /api/cards/search?q=llan&limit=10
    api.search("llan", "8", "1")          # ...&detail=1: each card's type, cost, default printing, copies
    api.image_file("fdn", "227", "small") # GET /img/fdn/227/small: the local JPEG
    api.update_cards()                    # what the server runs in the background at start

    # The editor (Milestone 4); each POST takes the request body as bytes.
    api.edit_view("casual/gruul-ramp")    # GET /api/deck/edit?id=...: lists, fields, sha256
    api.printings("Llanowar Elves")       # GET /api/cards/printings?name=...: the printing picker
    api.parse_list(body)                  # POST /api/decklist/parse: "Paste a list"
    api.check_draft(body)                 # POST /api/deck/check: blocks, warnings, preview
    api.find_cards("bolt", "all")         # GET /api/deck/find?q=bolt: the editor's Add panel (owned first, filters)
    api.swaps.suggest_swaps("casual/gruul-ramp")  # GET /api/deck/swaps?id=...: owned stand-ins per missing card
    api.swaps.suggest_draft_swaps(body)   # POST /api/deck/swaps: the same for the editor's Play-now list
    api.save_deck(body)                   # POST /api/deck/save: the new text and table, one change
    api.create_deck(body)                 # POST /api/decks: a new deck, one change (201)
    api.stale_view()                      # GET /api/tables/stale
    api.update_tables(body)               # POST /api/tables/update: "Update their tables"

    # Forge matchups (Milestone 5).
    api.matchups()                        # GET /api/matchups: saved results, runs going, Forge's state
    api.rankings_view(format="Constructed") # GET /api/rankings: current field lists' ratings and uncertainty
    api.library_forge_view()                # GET /api/library/forge: each casual list's field average (cached)
    api.matchup(a="casual/gruul-ramp", av="owned", b="casual/izzet-prowess", bv="target")
                                          # GET /api/matchup?a=...&av=...&b=...&bv=...[&profile=matt]
    api.matchup(key="<64 hex>")           # GET /api/matchup?key=...: a saved result by its key
    api.run_matchup(body)                 # POST /api/matchup/run: start (or join) a run
    api.stop_matchup(body)                # POST /api/matchup/stop: Stop
    api.stop_jobs()                       # the server is stopping: both job runners stop

Each raises ApiError(status, message) for a request it can't answer; the
server sends that as {"error": message} with the status, plus the error's
extra keys ("blocks" for a draft that can't be saved yet, "conflict" for a
409). Every value that comes from a request is checked here (deck ids,
profile ids, set codes and collector numbers, versions, search text and
limits, and every part of a draft), and decks are only ever read through
decks.load_deck() and decks.find_deck_file() (the inventory's snapshot), or
saved through the inventory's deck operations (lib/inventory/ops_decks.py),
which check every id.

Saving (PLAN.md part 2 and phase 4; the full contract is in the Milestone 4
notes): every write names a profile from config.json, who the change is
saved as. A save works out the new text from the deck as the page loaded it
(decks.apply_edit: only Deck Lab's parts change, and a decklist change adds
the "Decklist changed" line; the owned-vs-needed table rewritten from the
target list with the current pool, prices and rate, without repricing when
the rate above the table is worded some other way), then saves it with one
inventory operation, which checks the deck's sha256 is still the one the
page loaded (409 with who changed it and when, from the deck's saved
revisions, when it differs). Deck-building rules (stats.deck_rules) are
warnings; only things that would put a wrong card or line in the deck block
a save.

Every device on the home network can read the answers, so no absolute path
(which would show the Windows user name) goes into one: error messages and
warnings give paths relative to the repo, or just a file name, and the server
log gets the full text.

Until the card index exists (the first start downloads Scryfall's bulk data,
which takes a few minutes), everything that needs card data raises ApiError
503 with a plain sentence saying so, and status() reports "updating".

deck_view() asks decklab.lib.stats.deck_stats(sections, kind) for the stats,
passing the decklist as decks.load_deck() returns it ({section: [DeckLine]})
and kind "commander" or "constructed". It's imported when first needed, and if
it's missing or fails, the deck still shows, with "stats": null and a warning
(the traceback goes to the server log). The same goes for the owned-vs-needed
part when the card pool can't be read (a bad inventory row, or the
database unreachable: lib/inventory/). For a visitor who may not
see the deck's space's inventory (guard.sees_inventory; the phase 4 design's
R6d) deck_view() leaves out "owned", "table" and "tokens" altogether, and
decks_index() the library's counts and token chips; the list, guide,
stats, practice and matchups stay.

goldfish() is the practice-hand simulation (lib/goldfish/, imported when
first needed like stats). A saved result answers at once; otherwise the run
goes to JOBS, a jobs.Runner that runs one simulation at a time (each already
uses every core), and the page polls until it's done. The same list asked for
twice, from any phone, is one run. deck_view() includes a saved result too
("practice"), so a deck page is drawn whole; it never starts a run. A
Beginner Box half (is_half) gets none: it's only played in a pairing.

Matchups (PLAN.md part 6) play two lists against each other in Forge
(lib/forge/, imported when first needed like goldfish; the full contract is
in the Milestone 5 notes). A matchup is keyed by forge.matchup_key: the two
lists' cards (not their ids) and the engine that plays them (forge/engine.py),
so A vs B and B vs A, or the same cards under two ids, are one result that
each run adds games to, until the engine changes. Runs go to FORGE_JOBS, a
runner of their own (up to 4 at once, sharing the server's warm pool of Forge
workers; at most 10 waiting), so practice hands never wait behind a matchup.
Asking for a matchup that's already waiting or playing joins that run. Stop
takes a waiting run off the queue, or stops a playing one within about a
second, which keeps every game it finished (a plain-Forge batch cut short is
kept as a partial batch); the answer then says who stopped it. Answers are
from the point of view of the deck asked for as "a" (sides[0]; forge.view flips the saved
result), and each side says whether it's still that deck's list today
("current"). Casual decks only play casual decks, and Commander decks only
Commander decks (1v1); a Beginner Box half only plays in a pairing, as with
practice hands. forge.ForgeError messages are plain sentences and are shown
as they are; any other failure is logged with its traceback and shown as
MATCHUP_FAILED. deck_view() includes the list's matchups ("matchups": what
Forge's AI can't play in it, its saved results, those of its earlier lists,
runs going, and what each card did in its card-log games); like "practice", it never starts a run and never fails the
deck page.

Where things are: Milestone 7 made this module a package, imported and
called as before (from decklab.lib import api; api.<name>). Each part:

    common.py        ApiError, the server log (_log), no paths in answers, request bodies,
                     state_errors() (the state store's errors as 503/400/409)
    carddata.py      the background card update (UPDATE), the 503 until it's done, status()
    settings.py      profiles and their settings (the state store; _current_settings never
                     fails, for the matchup and field defaults), _writer, _web_actor
    library.py       deck ids, library summaries, the pool with a warning, _deck_sections
    card_lookup.py   card and line JSON, which printing, search(), printings(), image_file();
                     _pool_counts, the copies the viewer may see (home's, or their own space's)
    deck_page.py     decks_index(), deck_view() (the space's inventory only for those who may
                     see it)
    practice.py      practice hands: JOBS, goldfish()
    forge_runs.py    Forge matchups: FORGE_JOBS, matchups(), matchup(), run_matchup(),
                     stop_matchup(), stop_jobs(); COORD_JOBS (wave 3's coordinators)
    field_page.py    the field view (wave 3): field_view(), run_field(), stop_field()
    library_forge.py the library's Forge line: library_forge_view(), each casual list's cached field average
    variant_page.py  paired variant tests (wave 3): variant_view(), variant_estimate(),
                     variant_tests(), run_variant(), stop_variant(), more_variant()
    drafts.py        reading and checking an editor draft, the deck rules, brackets
    commits.py       the decks that can be saved, 409 conflicts, owned-vs-needed tables
    editor.py        edit_view(), parse_list(), check_draft()
    swaps.py         stand-ins for missing cards (E2-S07): suggest_swaps(), suggest_draft_swaps(),
                     view_swaps() (deck_view's "swaps"); the rules in lib/decks/swaps.py
    saving.py        save_deck(), create_deck(), stale_view(), update_tables(); _save_lock and
                     inventory_write_lock() (the lock order for inventory writes)
    history.py       a deck's saved revisions (read-only): deck_history(), deck_revision(), from
                     the inventory's deck_revision rows, numbered per deck
    guide.py         the playing guide read from a deck's Notes (read-only)
    wishlists.py     get_wishlist(), change_wishlist() (the state store), validated_entry()
                     (shared with python -m decklab.db wishlist)
    accessories.py   the Accessories page: accessories_view(), fetch_picture(), save_accessory(),
                     assign_accessory() (inventory operations), and the pictures behind
                     /accessory-img/ (image_file(), staged_image()). Not imported here:
                     feature_routes.dispatch and the server import it when first asked,
                     since lib/accessory_fetch.py imports this package's common.py
    tokens.py        the Tokens page: tokens_view(), save_token(). Not imported
                     here either: feature_routes.dispatch imports it when first asked
    collection.py    collection_view(): browsing one space's pool (read-only)
    collection_edit.py   the Collection page's edits and imports: rows_view(), save_card(),
                     import_preview(), import_apply(), printings_view(),
                     each write one inventory.apply. Imported when first asked, as tokens.py
    precons.py       the Collection page's "Add a precon": precons_view(), precon_preview(),
                     add_precon() (the cards and the deck in one inventory change)
    cover.py         GET /api/deck/cards: cover_cards(), the picture picker's cards; POST
                     /api/deck/cover: save_cover() sets or clears a deck's Cover card line (one
                     deck.save). Imported when first asked (feature_routes.dispatch)
    token_cards.py   POST /api/deck/token-cards: save_token_cards() sets a built deck's Token
                     cards line, the token cards it packs (one deck.save). Imported when first asked
    shopping.py      shopping_overview(): the purchase queue, orders and checks (home's), and
                     resolve_check() (POST /api/shopping/check: a received delivery's check marked done)
    shopping_queue.py POST /api/shopping/queue: save_queue_state(), moving one queued card
                     between the existing purchase categories, with an expected inventory revision
    receipts.py      the Receipts page: receipt_view(), preview_receipt(), apply_receipt(), on
                     lib/inventory/receive.py (shared with python -m decklab.db receive)
    assembly.py      the packing plan (Plan decks): assembly_view(), assembly_preview(), over
                     home's pool, with each deck's tokens
    guard.py         the permission check every write route makes, and the reading rules for
                     accessories, wishlists, the inventory, the Activity page and the Game log
                     (lib/permissions.py's rules)
    simulations.py   who may start Forge runs (the mode, in the state store) and the worker limit
    play_records.py  played games and sideboard plans (the state store): play_overview(),
                     save_game(), save_sideboard(). Imported when first asked, as tokens.py
    activity.py      the Activity page: activity_view(), the audit trail filtered for each
                     viewer (visible_change). Imported when first asked, as tokens.py. Its rows'
                     words are activity_summaries.py's, its headlines activity_headlines.py's
    visits.py        visits (lib/visits.py): beacon() (POST /api/visit, the page's route, never a
                     data write) and visits_view() (GET /api/visits, admins'). Imported when first
                     asked, as tokens.py

The package offers every name the old module had, except the ones code
outside it reads or patches where they live, so that a patch can't land on
a copy nobody reads: UPDATE (carddata),
JOBS and GOLDFISH_SETTINGS (practice), FORGE_JOBS,
COORD_JOBS and STOP_WAIT (forge_runs), _log (common), _read_draft (drafts), and _today
and _stale_after (saving). Patch decklab.lib.api.<part>.<name>.
"""
# As before, cards, config, decks, jobs and pool are reachable as api.<module>
# (the tests use api.jobs).
from decklab.lib import cards, config, decks, jobs, pool

from . import (card_lookup, carddata, commits, common, deck_page, drafts, editor, field_page, forge_runs, library,
               practice, saving, settings, variant_page, wishlists)
from .card_lookup import (DID_YOU_MEAN, MAX_PRINTINGS, MAX_SEARCH, REGULAR_SET_TYPES, SEARCH_LIMIT, _PRICE_KEYS,
                          _card_json, _card_printings, _default_printing, _line_json, _lines_json, _newest_nonfoil,
                          _not_paper, _number_key, _owned_json, _pickable, _resolve, _showable, _shown_printing,
                          image_file, image_url, printings, search)
from .carddata import (_INDEX_ERRORS, _cached_rate, _index_info, _last_index_error, _require_cards, _update_lock,
                       status, update_cards)
from .commits import (_conflict, _deck_file, _parse_file, _rewrite_table, _source, _stale_list, _stored,
                      _table_json, _title_of, _when, _without_own_built_warning)
from .common import (LINE_FINISHES, MAX_BODY, MAX_EDIT_BODY, MAX_NAME, MAX_QTY, NUMBER_RE, SET_RE, _ABS_PATH_RE,
                     _CONTROL_RE, _POSIX_PATH_RE, _SHA_RE, ApiError, _flag, _jsonable, _keys, _lazy, _load_json,
                     _no_constants, _parse_body, _public, _scrub, _sha, _strip_paths, _unique, _unique_keys)
from .deck_page import _deck_stats, deck_view, decks_index
from .drafts import (MAX_ARCHETYPE, MAX_LINES, MAX_SUGGESTED, _Draft, _blocks_error, _bracket_names, _brackets,
                     _checked_line, _counts, _final, _known, _new_fields, _read_fields, _read_line, _read_sections,
                     _rule_warnings, _warnings_json)
from .editor import (EDITOR_SECTIONS, MAX_PASTE, _ARENA_ABOUT_RE, _file_edit_json, _new_source, _new_title,
                     _offered_sections, _paste_line, check_draft, edit_view, find_cards, parse_list)
from .forge_runs import (MATCHUP_BAD_KEY, MATCHUP_BUSY, MATCHUP_FAILED, MATCHUP_NO_KEY, MATCHUP_STOPPING,
                         MATCHUP_WAITING, _MatchupRun, _TodaysLists, _asked, _batching, _deck_matchups, _forge_module,
                         _forge_runner, _games, _item_json, _job_json, _matchup_by_key, _matchup_error, _matchup_games,
                         _matchup_json, _matchup_key, _matchup_lists, _matchup_notice, _running_json, matchup, matchups,
                         run_matchup, stop_jobs, stop_matchup)
from .field_page import field_view, run_field, stop_field
from .rankings import rankings_view
from .library_forge import library_forge_view
from .library import (DECK_KINDS, VERSIONS, _deck_sections, _find_summary, _half_title, _load_pool, _scrub_summary,
                      _sort_halves, check_deck_id, is_half)
from .practice import (RUN_FAILED, _deck_practice, _goldfish_json, _goldfish_module, _job_runner, _practice_saved,
                       _run_goldfish, goldfish)
from .saving import (MAX_TABLE_DECKS, MAX_TITLE, _and, _save_lock, _tables_conflict, create_deck, save_deck,
                     stale_view, update_tables)
from .settings import (DEFAULT_SETTINGS, SETTINGS, _config_profiles, _current_settings, _parse_settings,
                       _require_profile, _valid_profile_id, _writer, get_settings, profiles, put_settings)
from .variant_page import more_variant, run_variant, stop_variant, variant_estimate, variant_tests, variant_view
from .wishlists import change_wishlist, get_wishlist
from .shopping import shopping_overview
from .simulations import change as change_simulations, view as simulations_view
from .commander_night import (MAX_BODY as MAX_COMMANDER_NIGHT_BODY,
                             change as change_commander_night, view as commander_night_view)
from .retirement import retirement_view, retire_deck, restore_deck
