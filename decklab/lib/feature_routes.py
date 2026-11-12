"""Routes for collection, physical play, delivery, accessories and tokens tools, the Activity page, and visits
(the page's beacon, POST /api/visit, and the Settings page's GET /api/visits: api/visits.py).

Use the server's normal query, method and same-origin write guards. Each
part of the API is imported when first asked for. A POST takes at most
api.MAX_EDIT_BODY bytes, except routes with their explicit bound, including
pod records (play_pods.MAX_BODY), import previews (collection_edit.MAX_IMPORT_BODY), scanned photos
(collection_scan.MAX_SCAN_BODY, for cards and token cards), scanned token lists (tokens_scan.MAX_ADD_BODY), editor drafts kept for later (deck_drafts.MAX_BODY), field choices
(field_choices.MAX_BODY), a restart (server_restart.MAX_BODY)
and accessory saves with a local picture (accessories.MAX_SAVE_BODY). The gauntlet's view, run and
stop (api/gauntlet_page.py) and the group run's (api/field_group.py, E3-S31) answer 202 while their runs
wait or play, as the field's do.
"""

# Audit metadata, not a second permission engine. Existing handlers retain all access checks.
# Every concrete method/path must be declared; adding an unclassified route fails closed and CI.
from types import MappingProxyType

ACCESS = MappingProxyType({
    ('GET', 'forge/unfinished'): 'profile',
    ('POST', 'forge/resume'): 'profile',
    ('POST', 'forge/dismiss'): 'profile',
    ('GET', 'deck/development'): 'deck',
    ('GET', 'changes'): 'viewer-filtered',
    ('GET', 'activity/product-kit-undo'): 'home-records',
    ('POST', 'activity/product-kit-undo'): 'home-records',
    ('POST', 'goldfish/what-if'): 'deck',
    ('GET', 'deck/role-ranges'): 'deck',
    ('GET', 'space/download'): 'inventory',
    ('GET', 'space/needed'): 'inventory',
    # Enum-only operational reports are an anonymous same-origin exception, never inventory authority.
    ('POST', 'errors/report'): 'open',
    ('GET', 'settings/errors'): 'home-admin',
    ('GET', 'settings/maintenance'): 'admin',
    ('GET', 'settings/reference-facts'): 'admin',
    # Public card data; the decks named are only those the viewer may see (api/official_changes.py, E9-S36).
    ('GET', 'official-changes'): 'viewer-filtered',
    ('GET', 'settings/data-sources'): 'admin',
    ('GET', 'server/restart'): 'home-admin',
    ('GET', 'collection'): 'inventory',
    ('GET', 'collection/rows'): 'inventory',
    ('GET', 'collection/download'): 'inventory',
    ('GET', 'collection/loans'): 'inventory',
    ('GET', 'printings'): 'open',
    ('GET', 'precons'): 'open',
    ('GET', 'precons/product'): 'home-admin',
    ('GET', 'precons/preview'): 'inventory-edit',
    ('GET', 'precons/coverage'): 'inventory',
    ('GET', 'precons/coverage/deck'): 'inventory',
    ('GET', 'precons/trial'): 'deck',
    ('GET', 'commanders/candidates'): 'inventory',
    ('GET', 'commanders/candidate'): 'inventory',
    ('GET', 'assembly'): 'home-records',
    ('GET', 'compare/shared'): 'deck',
    ('GET', 'compare/deck'): 'deck',
    ('GET', 'compare/precon'): 'open',
    ('GET', 'play'): 'play',
    ('GET', 'play/sideboard-preview'): 'play',
    ('GET', 'play/sideboard-tests'): 'play',
    ('GET', 'play/pairs'): 'profile',
    ('GET', 'commander-night/lineup'): 'home-records',
    ('GET', 'deck/history'): 'deck',
    ('GET', 'deck/retire'): 'deck',
    ('GET', 'deck/rename'): 'deck',
    ('GET', 'deck/find'): 'deck',
    ('GET', 'deck/revision'): 'deck',
    ('GET', 'deck/swaps'): 'deck',
    ('GET', 'deck/replacements'): 'deck',
    ('GET', 'deck/dual-lands'): 'deck',
    ('GET', 'deck/role-cards'): 'deck',
    ('GET', 'deck/cards'): 'deck',
    ('GET', 'deck/opponents'): 'deck',
    ('GET', 'deck/draft'): 'draft',
    ('GET', 'deck/new-draft'): 'draft',
    ('GET', 'deck/edhrec'): 'deck',
    ('GET', 'deck/wishlist'): 'deck',
    ('GET', 'receipt'): 'home-records',
    ('GET', 'arrivals'): 'profile',
    ('GET', 'rankings'): 'viewer-filtered',
    ('GET', 'field/membership'): 'deck',
    ('GET', 'field/group'): 'deck',
    ('GET', 'crosscheck'): 'deck',
    ('GET', 'library/forge'): 'viewer-filtered',
    ('GET', 'library/gauntlet'): 'viewer-filtered',
    ('GET', 'product'): 'home-records',
    ('GET', 'accessories'): 'accessories',
    ('GET', 'tokens'): 'inventory',
    ('GET', 'dice'): 'inventory',
    ('GET', 'tokens/plan'): 'inventory',
    ('GET', 'activity'): 'activity',
    ('GET', 'activity/undo'): 'activity',
    ('GET', 'activity/wishlist-undo'): 'activity',
    ('GET', 'activity/accessory-undo'): 'activity',
    ('GET', 'activity/mixed-undo'): 'activity',
    ('GET', 'visits'): 'admin',
    ('GET', 'search'): 'viewer-filtered',
    ('GET', 'cards/decks'): 'inventory',
    ('GET', 'cards/lookup'): 'open',
    ('GET', 'cards/combos'): 'open',
    ('GET', 'cards/copies'): 'inventory',
    ('GET', 'cards/categories'): 'inventory',
    ('GET', 'gauntlet'): 'deck',
    ('GET', 'gauntlet/summary'): 'deck',
    ('GET', 'gauntlet/history'): 'deck',
    ('GET', 'gauntlet/catalogue'): 'open',
    ('GET', 'gauntlet/board'): 'viewer-filtered',
    ('GET', 'shopping/combined'): 'home-records',
    ('GET', 'shopping/price-history'): 'home-records',
    ('POST', 'activity/undo'): 'activity',
    ('POST', 'activity/wishlist-undo'): 'activity',
    ('POST', 'activity/accessory-undo'): 'activity',
    ('POST', 'activity/mixed-undo'): 'activity',
    ('POST', 'assembly/preview'): 'home-records',
    ('POST', 'assembly/built'): 'home-records',
    ('POST', 'assembly/ticks'): 'home-records',
    ('POST', 'assembly/standins'): 'home-records',
    ('POST', 'play/game'): 'play',
    ('POST', 'play/game/delete'): 'play',
    ('POST', 'play/pod'): 'play',
    ('POST', 'play/sideboard'): 'play',
    ('POST', 'play/sideboard-test'): 'deck-run',
    ('POST', 'receipt/preview'): 'home-admin',
    ('POST', 'receipt/apply'): 'home-admin',
    ('POST', 'arrivals/dismiss'): 'profile',
    ('POST', 'product/intact/preview'): 'home-admin',
    ('POST', 'product/intact/apply'): 'home-admin',
    ('POST', 'product/token-cards'): 'home-admin',
    ('POST', 'shopping/check'): 'home-admin',
    ('POST', 'shopping/queue'): 'home-admin',
    ('POST', 'shopping/queue/missing'): 'home-admin',
    ('POST', 'shopping/queue/combined'): 'home-admin',
    ('POST', 'variant/queue/preview'): 'home-admin',
    ('POST', 'variant/queue'): 'home-admin',
    ('POST', 'shopping/order/preview'): 'home-admin',
    ('POST', 'shopping/order/apply'): 'home-admin',
    ('POST', 'shopping/order/change/preview'): 'home-admin',
    ('POST', 'shopping/order/change/apply'): 'home-admin',
    ('POST', 'accessories/fetch'): 'accessories',
    ('POST', 'accessories/save'): 'accessories',
    ('POST', 'accessories/assign'): 'accessories',
    ('POST', 'tokens/save'): 'inventory-edit',
    ('POST', 'dice/save'): 'inventory-edit',
    ('POST', 'tokens/plan'): 'inventory-edit',
    ('POST', 'tokens/scan'): 'inventory-edit',
    ('POST', 'tokens/scan/add'): 'inventory-edit',
    ('POST', 'collection/save'): 'inventory-edit',
    ('POST', 'collection/lend'): 'inventory-edit',
    ('POST', 'collection/return'): 'inventory-edit',
    ('POST', 'collection/bulk'): 'inventory-edit',
    ('POST', 'collection/locations/bulk'): 'inventory-edit',
    ('POST', 'collection/import/preview'): 'inventory-edit',
    ('POST', 'collection/import/apply'): 'inventory-edit',
    ('POST', 'collection/scan'): 'inventory-edit',
    ('POST', 'collection/trade/preview'): 'inventory-edit',
    ('POST', 'collection/trade'): 'inventory-edit',
    ('POST', 'precons/add'): 'inventory-edit',
    ('POST', 'precons/start'): 'inventory-edit',
    ('POST', 'precons/trial'): 'inventory-edit',
    ('POST', 'precons/trial/keep'): 'deck-edit',
    ('POST', 'field/policy/preview'): 'home-admin',
    ('POST', 'field/policy'): 'home-admin',
    ('POST', 'deck/cover'): 'deck-edit',
    ('POST', 'deck/token-cards'): 'deck-edit',
    ('POST', 'deck/printings'): 'deck-edit',
    ('POST', 'deck/box-check'): 'deck-edit',
    ('POST', 'deck/box-repair'): 'deck-edit',
    ('POST', 'deck/opponents'): 'deck-edit',
    ('POST', 'deck/draft'): 'draft',
    ('POST', 'deck/new-draft'): 'draft',
    ('POST', 'deck/considering'): 'deck-edit',
    ('POST', 'deck/cuts'): 'deck',
    ('POST', 'deck/bracket-replacements'): 'deck-edit',
    ('POST', 'deck/swaps'): 'deck',
    ('POST', 'deck/retire'): 'deck-edit',
    ('POST', 'deck/rename/preview'): 'deck-edit',
    ('POST', 'deck/rename'): 'deck-edit',
    ('POST', 'deck/restore'): 'deck-edit',
    ('POST', 'server/restart'): 'home-admin',
    ('POST', 'gauntlet/run'): 'deck-run',
    ('POST', 'gauntlet/stop'): 'run-stop',
    ('POST', 'field/group/run'): 'deck-run',
    ('POST', 'field/group/stop'): 'run-stop',
    ('POST', 'crosscheck/run'): 'deck-run',
    ('POST', 'crosscheck/stop'): 'run-stop',
    ('POST', 'visit'): 'open',
})

# Older routes remain in Handler._route; this reviewed inventory gives them the same audit vocabulary.
# GET includes its HEAD alias. These declarations describe policy; handlers enforce it.
LEGACY_ACCESS = MappingProxyType({
    ('GET', '/api/status'): 'open',
    ('GET', '/api/profiles'): 'viewer-filtered',
    ('GET', '/api/me'): 'open',
    ('GET', '/api/visibility'): 'profile',
    ('PUT', '/api/visibility'): 'profile',
    ('GET', '/api/visibility/preview'): 'profile',
    ('GET', '/api/simulations'): 'viewer-filtered',
    ('PUT', '/api/simulations'): 'admin',
    ('GET', '/api/shop-postage'): 'home-records',
    ('PUT', '/api/shop-postage'): 'home-admin',
    ('GET', '/api/pricing-setting'): 'home-records',
    ('PUT', '/api/pricing-setting'): 'home-admin',
    ('GET', '/api/commander-night'): 'home-records',
    ('PUT', '/api/commander-night'): 'home-admin',
    ('GET', '/api/settings/members'): 'home-admin',
    ('POST', '/api/settings/member-email'): 'home-admin',
    ('POST', '/api/settings/member'): 'home-admin',
    ('GET', '/api/profiles/{profile}/settings'): 'profile',
    ('PUT', '/api/profiles/{profile}/settings'): 'profile',
    ('GET', '/api/profiles/{profile}/wishlist'): 'profile',
    ('POST', '/api/profiles/{profile}/wishlist'): 'profile',
    ('GET', '/api/shopping'): 'home-records',
    ('GET', '/api/decks'): 'viewer-filtered',
    ('POST', '/api/decks'): 'deck-edit',
    ('GET', '/api/deck'): 'deck',
    ('GET', '/api/deck/edit'): 'deck',
    ('POST', '/api/deck/check'): 'deck-edit',
    ('POST', '/api/deck/save'): 'deck-edit',
    ('POST', '/api/decklist/parse'): 'profile',
    ('POST', '/api/tables/update'): 'deck-edit',
    ('GET', '/api/tables/stale'): 'viewer-filtered',
    ('GET', '/api/goldfish'): 'deck',
    ('GET', '/api/matchups'): 'viewer-filtered',
    ('GET', '/api/matchup'): 'deck',
    ('POST', '/api/matchup/run'): 'deck-run',
    ('POST', '/api/matchup/stop'): 'run-stop',
    ('GET', '/api/field'): 'deck',
    ('GET', '/api/variant'): 'deck',
    ('GET', '/api/variant/estimate'): 'deck',
    ('GET', '/api/variants'): 'deck',
    ('POST', '/api/field/run'): 'deck-run',
    ('POST', '/api/field/stop'): 'run-stop',
    ('POST', '/api/variant/run'): 'deck-run',
    ('POST', '/api/variant/stop'): 'run-stop',
    ('POST', '/api/variant/more'): 'deck-run',
    ('GET', '/api/cards/search'): 'open',
    ('GET', '/api/cards/printings'): 'open',
    ('GET', '/api/cards/rulings'): 'open',
    ('GET', '/img/{set}/{number}/{size}'): 'open',
    ('GET', '/symbols/{symbol}'): 'open',
    ('GET', '/accessory-img/{name}'): 'accessories',
    ('GET', '/accessory-img/staged/{token}'): 'accessories',
    ('GET', '/{static-file}'): 'open',
})


def declared_access(method, route):
    """The reviewed access class; never infer one from a prefix or handler name."""
    key = (method, "/".join(route))
    if key not in ACCESS:
        raise RuntimeError("Route has no declared access class")
    return ACCESS[key]


GAUNTLET_WAITING = ("queued", "running")       # a gauntlet answer's statuses sent with 202


def _field_membership_view(**params):
    """Load Forge's membership adapter only for an allowed field request."""
    from decklab.lib.api.field_membership import membership_view
    return membership_view(**params)


def _field_choice_preview(body):
    """Home's saved field choices (api/field_choices.py): a reviewed preview, writing nothing."""
    from decklab.lib.api.field_choices import preview
    return preview(body)


def _field_choice_save(body):
    from decklab.lib.api.field_choices import save
    return save(body)


def _price_history(**params):
    """A queued card's daily shop readings (api/shop_history.py, E5-S29); writes nothing."""
    from decklab.lib.api.shop_history import price_history_view
    return price_history_view(**params)


def _global_search(**params):
    """The top bar's global search (api/global_search.py, E11-S31): visible decks, the viewer's own
    collection and every Scryfall card; writes nothing."""
    from decklab.lib.api.global_search import search_view
    return search_view(**params)


def _card_decks(**params):
    """One card's use in a space for the card viewer (api/card_decks.py, E1-S29): inventory readers only."""
    from decklab.lib.api.card_decks import card_decks
    return card_decks(**params)


def _precon_trial(name):
    """One of api/precon_trial.py's functions (E3-S39, Try a precon), imported when first asked for."""
    from decklab.lib.api import precon_trial
    return getattr(precon_trial, name)


def _trial_view(**params):
    return _precon_trial("trial_view")(**params)


def _trial_start(body):
    return _precon_trial("start_trial")(body)


def _trial_keep(body):
    return _precon_trial("keep_trial")(body)


def _sideboard_preview(**params):
    """Load the sideboard preview, which reads Forge's paired-game budgets, only when asked for."""
    from decklab.lib.api.sideboard_preview import preview_sideboard
    return preview_sideboard(**params)


def _sideboard_tests(**params):
    """Load a sideboard plan's tests (api/sideboard_test.py, over Forge's variant tests) only when asked for."""
    from decklab.lib.api.sideboard_test import sideboard_tests
    return sideboard_tests(**params)


def _start_sideboard_test(body):
    from decklab.lib.api.sideboard_test import start_sideboard_test
    return start_sideboard_test(body)


def _shopping_combined(**params):
    """Shopping's decks built together (api/shopping_combined.py, E5-S28): read-only."""
    from decklab.lib.api.shopping_combined import combined_view
    return combined_view(**params)


def _gauntlet_view(**params):
    """The deck page's "Against popular decks" (api/gauntlet_page.py), loaded only when asked for."""
    from decklab.lib.api.gauntlet_page import gauntlet_view
    return gauntlet_view(**params)


def _gauntlet_summary(**params):
    """A deck's headline against the standard sample (api/gauntlet_page.py), saved games only."""
    from decklab.lib.api.gauntlet_page import gauntlet_summary
    return gauntlet_summary(**params)


def _gauntlet_history(**params):
    """A deck's figure across its saved lists (api/gauntlet_history.py, E3-S50), saved games only."""
    from decklab.lib.api.gauntlet_history import history_view
    return history_view(**params)


def _gauntlet_board(**params):
    """The Testing page's Popular decks board (api/gauntlet_board.py, E3-S35): saved games only."""
    from decklab.lib.api.gauntlet_board import board_view
    return board_view(**params)


def _library_gauntlet(**params):
    """The library's popular-decks line (api/library_gauntlet.py, E3-S36): the board's cached rows."""
    from decklab.lib.api.library_gauntlet import library_gauntlet_view
    return library_gauntlet_view(**params)


def _gauntlet_catalogue(**params):
    from decklab.lib.api.gauntlet_page import catalogue_view
    return catalogue_view(**params)


def _gauntlet_run(body):
    from decklab.lib.api.gauntlet_page import run_gauntlet
    return run_gauntlet(body)


def _gauntlet_stop(body):
    from decklab.lib.api.gauntlet_page import stop_gauntlet
    return stop_gauntlet(body)


def _group_view(**params):
    """The deck page's group run of chosen decks (api/field_group.py, E3-S31), loaded only when asked for."""
    from decklab.lib.api.field_group import group_view
    return group_view(**params)


def _group_run(body):
    from decklab.lib.api.field_group import run_group
    return run_group(body)


def _group_stop(body):
    from decklab.lib.api.field_group import stop_group
    return stop_group(body)


def _crosscheck_view(**params):
    from decklab.lib.api.crosscheck_page import check_view
    return check_view(**params)


def _crosscheck_run(body):
    from decklab.lib.api.crosscheck_page import run_check
    return run_check(body)


def _crosscheck_stop(body):
    from decklab.lib.api.crosscheck_page import stop_check
    return stop_check(body)


GAUNTLET_ROUTES = {("gauntlet",), ("gauntlet", "run"), ("gauntlet", "stop"),
                   ("field", "group"), ("field", "group", "run"), ("field", "group", "stop"),
                   ("crosscheck",), ("crosscheck", "run"), ("crosscheck", "stop")}


def _status(key, answer):
    """200, or 202 for a gauntlet or group answer whose run waits or plays."""
    waiting = (key in GAUNTLET_ROUTES or key == ("goldfish", "what-if")) and isinstance(answer, dict) and answer.get("status") in GAUNTLET_WAITING
    return 202 if waiting else 200


def route_tables():
    """Fresh handler bindings, so request-time patches and lazy imports retain one owner."""
    from decklab.lib.api import role_ranges
    from decklab.lib.api import space_download
    from decklab.lib.api import (accessories, accessory_undo, activity, arrivals, activity_mixed_undo, activity_undo, assembly, commander_candidates, assembly_completion, assembly_standins, assembly_ticks, box_check, box_repair, collection, compare, comparison_lists, considering, collection_edit, collection_locations, collection_scan, collection_trade, cover, deck_drafts, deck_printings, dice, edhrec, editor, history,
                                 library_forge, maintenance, opponents, play_pods, play_records, play_tonight, precon_coverage, precons, products, product_tokens, rankings, receipts, reference_facts, rename, retirement, role_cards, server_restart, shopping, shopping_order_changes, shopping_orders, shopping_queue, shopping_queue_combined, shopping_queue_missing, swaps, token_cards, token_plan, tokens, tokens_scan, variant_queue, visits, wishlist_ideas, wishlist_undo)
    from decklab.lib.api.common import MAX_BODY
    from decklab.lib.api import changes
    from decklab.lib.api import data_sources
    from decklab.lib.api import run_recovery
    from decklab.lib.api import development
    from decklab.lib.api import card_details
    from decklab.lib.api import card_combos
    from decklab.lib.api import category_suggestions
    from decklab.lib.api import deck_cuts
    from decklab.lib.api import bracket_fixes
    from decklab.lib.api import error_reports
    from decklab.lib.api import collection_loans
    from decklab.lib.api import practice
    from decklab.lib.api import product_kit_undo
    from decklab.lib.api import commander_lineup
    from decklab.lib.api import official_changes

    gets = {
        ("activity", "product-kit-undo"): (product_kit_undo.view, ("id",)),
        ("forge", "unfinished"): (run_recovery.view, ()),
        ("deck", "development"): (development.development_view, ("id", "version")),
        ("changes",): (changes.view, ()),
        ("deck", "role-ranges"): (role_ranges.ranges_view, ("id", "version")),
        ("space", "download"): (space_download.download_view, ("space",)),
        ("space", "needed"): (space_download.needed_view, ("space",)),
        ("settings", "errors"): (error_reports.view, ()),
        ("settings", "maintenance"): (maintenance.maintenance_view, ()),
        ("settings", "reference-facts"): (reference_facts.reference_facts_view, ()),
        ("official-changes",): (official_changes.view, ()),
        ("settings", "data-sources"): (data_sources.data_sources_view, ()),
        ("server", "restart"): (server_restart.view, ()),
        ("collection",): (collection.collection_view,
                         ("q", "color", "type", "role", "mv", "availability", "page", "limit", "space")),
        ("collection", "rows"): (collection_edit.rows_view, ("space",)),
        ("collection", "download"): (collection_edit.download_view, ("space",)),
        ("collection", "loans"): (collection_loans.loans_view, ("space", "before", "include_returned")),
        ("printings",): (collection_edit.printings_view, ("name",)),
        ("precons",): (precons.precons_view, ("q", "products")),
        ("precons", "product"): (precons.product_list_view, ("file", "bonus")),
        ("precons", "preview"): (precons.precon_preview, ("file", "space")),
        ("precons", "coverage"): (precon_coverage.coverage_view, ("space", "format", "type", "limit")),
        ("precons", "coverage", "deck"): (precon_coverage.coverage_deck, ("file", "space")),
        ("precons", "trial"): (_trial_view, ("file", "space")),
        ("commanders", "candidates"): (commander_candidates.candidates_view, ("space", "limit")),
        ("commanders", "candidate"): (commander_candidates.candidate_view, ("name", "space", "partner")),
        ("assembly",): (assembly.assembly_view, ("deck", "version")),
        ("compare", "shared"): (compare.shared_view, ("a", "av", "b", "bv")),
        ("compare", "deck"): (comparison_lists.current_view, ("id", "version")),
        ("compare", "precon"): (comparison_lists.precon_view, ("file",)),
        ("play",): (play_records.play_overview, ("id",)),
        ("play", "sideboard-preview"): (_sideboard_preview, ("id", "sha256")),
        ("play", "sideboard-tests"): (_sideboard_tests, ("id", "sha256")),
        ("play", "pairs"): (play_tonight.pairs_view, ()),
        ("commander-night", "lineup"): (commander_lineup.lineup_view, ()),
        ("deck", "history"): (history.deck_history, ("id",)),
        ("deck", "retire"): (retirement.retirement_view, ("id",)),
        ("deck", "rename"): (rename.rename_view, ("id",)),
        ("deck", "find"): (editor.find_cards, ("q", "scope", "colors", "type", "mv", "id", "space", "limit", "page")),
        ("deck", "revision"): (history.deck_revision, ("id", "revision", "version", "stats")),
        ("deck", "swaps"): (swaps.suggest_swaps, ("id", "version", "card")),
        ("deck", "replacements"): (swaps.suggest_replacements, ("id", "version", "card")),
        ("deck", "dual-lands"): (swaps.suggest_dual_lands, ("id", "version")),
        ("deck", "role-cards"): (role_cards.role_cards, ("id", "version")),
        ("deck", "cards"): (cover.cover_cards, ("id",)),
        ("deck", "opponents"): (opponents.opponents_view, ("id",)),
        ("deck", "draft"): (deck_drafts.draft_view, ("id", "version")),
        ("deck", "new-draft"): (deck_drafts.new_draft_view, ("space", "source")),
        ("deck", "edhrec"): (edhrec.edhrec_view, ("id", "commander", "commander2", "space", "page", "view")),
        ("deck", "wishlist"): (wishlist_ideas.wishlist_ideas_view, ("id", "commander", "commander2", "space", "kind")),
        ("receipt",): (receipts.receipt_view, ("order",)),
        ("arrivals",): (arrivals.arrivals_view, ()),
        ("rankings",): (rankings.rankings_view, ("format",)),
        ("field", "membership"): (_field_membership_view, ("id", "version")),
        ("field", "group"): (_group_view, ("id", "version", "opponents", "profile")),
        ("crosscheck",): (_crosscheck_view, ("id", "version", "opponent", "opponent_version", "test")),
        ("library", "forge"): (library_forge.library_forge_view, ()),
        ("library", "gauntlet"): (_library_gauntlet, ()),
        ("product",): (products.product_state, ("stem",)),
        ("accessories",): (accessories.accessories_view, ()),
        ("tokens",): (tokens.tokens_view, ("space",)),
        ("dice",): (dice.dice_view, ("space",)),
        ("tokens", "plan"): (token_plan.plan_view, ("space",)),
        ("activity",): (activity.activity_view, ("before", "limit", "kind", "actor")),
        ("activity", "undo"): (activity_undo.undo_view, ("id",)),
        ("activity", "wishlist-undo"): (wishlist_undo.wishlist_undo_view, ("id",)),
        ("activity", "accessory-undo"): (accessory_undo.accessory_undo_view, ("id",)),
        ("activity", "mixed-undo"): (activity_mixed_undo.mixed_undo_view, ("id",)),
        ("visits",): (visits.visits_view, ("days", "who")),
        ("search",): (_global_search, ("q", "group", "limit")),
        ("cards", "decks"): (_card_decks, ("name", "space")),
        ("cards", "lookup"): (card_details.card_view, ("name", "set", "number")),
        ("cards", "combos"): (card_combos.card_combos, ("name",)),
        ("cards", "copies"): (card_details.copies_view, ("name", "space")),
        ("cards", "categories"): (category_suggestions.choices_view, ("name", "space", "exclude")),
        ("gauntlet",): (_gauntlet_view, ("id", "version", "sample", "size", "colours", "styles", "tiers", "commander",
                                           "profile")),
        ("gauntlet", "summary"): (_gauntlet_summary, ("id", "version", "profile")),
        ("gauntlet", "history"): (_gauntlet_history, ("id", "version", "profile")),
        ("gauntlet", "catalogue"): (_gauntlet_catalogue, ("format",)),
        ("gauntlet", "board"): (_gauntlet_board, ("format", "profile")),
        ("shopping", "combined"): (_shopping_combined, ("decks",)),
        ("shopping", "price-history"): (_price_history, ("name", "row")),
    }
    posts = {
        ("activity", "product-kit-undo"): (product_kit_undo.apply, MAX_BODY),
        ("goldfish", "what-if"): (practice.what_if, MAX_BODY),
        ("activity", "undo"): activity_undo.apply_undo,
        ("activity", "wishlist-undo"): wishlist_undo.apply_wishlist_undo,
        ("activity", "accessory-undo"): accessory_undo.apply_accessory_undo,
        ("activity", "mixed-undo"): activity_mixed_undo.apply_mixed_undo,
        ("assembly", "preview"): assembly.assembly_preview,
        ("assembly", "built"): assembly_completion.mark_built,
        ("assembly", "ticks"): (assembly_ticks.packing_ticks, assembly_ticks.MAX_BODY),
        ("assembly", "standins"): assembly_standins.save_standins,
        ("play", "game"): play_records.save_game,
        ("play", "game", "delete"): play_records.delete_game,
        ("play", "pod"): (play_pods.save_pod, play_pods.MAX_BODY),
        ("play", "sideboard"): play_records.save_sideboard,
        ("play", "sideboard-test"): _start_sideboard_test,     # run.start (require_start), after the preview's checks
        ("receipt", "preview"): receipts.preview_receipt,
        ("receipt", "apply"): receipts.apply_receipt,
        ("arrivals", "dismiss"): arrivals.dismiss_arrivals,
        ("product", "intact", "preview"): products.preview_storage,
        ("product", "intact", "apply"): products.apply_storage,
        ("product", "token-cards"): product_tokens.save_product_tokens,
        ("shopping", "check"): shopping.resolve_check,
        ("shopping", "queue"): shopping_queue.save_queue_state,
        ("shopping", "queue", "missing"): shopping_queue_missing.review_missing,     # a review: nothing is written
        ("shopping", "queue", "combined"): shopping_queue_combined.review_combined,  # a review: nothing is written
        ("variant", "queue", "preview"): variant_queue.preview_queue,
        ("variant", "queue"): variant_queue.apply_queue,
        ("shopping", "order", "preview"): shopping_orders.preview_order,
        ("shopping", "order", "apply"): shopping_orders.apply_order,
        ("shopping", "order", "change", "preview"): shopping_order_changes.preview_order_change,
        ("shopping", "order", "change", "apply"): shopping_order_changes.apply_order_change,
        ("accessories", "fetch"): accessories.fetch_picture,
        ("accessories", "save"): (accessories.save_accessory, accessories.MAX_SAVE_BODY),
        ("accessories", "assign"): accessories.assign_accessory,
        ("tokens", "save"): tokens.save_token,
        ("dice", "save"): (dice.save_dice, dice.MAX_SAVE_BODY),
        ("tokens", "plan"): token_plan.apply_plan,
        ("tokens", "scan"): (tokens_scan.scan_token, collection_scan.MAX_SCAN_BODY),     # nothing is written
        ("tokens", "scan", "add"): (tokens_scan.add_scanned, tokens_scan.MAX_ADD_BODY),
        ("collection", "save"): collection_edit.save_card,
        ("collection", "lend"): collection_loans.lend,
        ("collection", "return"): collection_loans.return_loan,
        ("collection", "bulk"): (collection_edit.bulk_set, collection_edit.MAX_BULK_BODY),
        ("collection", "locations", "bulk"): (collection_locations.bulk_set, collection_edit.MAX_BULK_BODY),
        ("collection", "import", "preview"): (collection_edit.import_preview, collection_edit.MAX_IMPORT_BODY),
        ("collection", "import", "apply"): collection_edit.import_apply,
        ("collection", "scan"): (collection_scan.scan_photo, collection_scan.MAX_SCAN_BODY),     # nothing is written
        ("collection", "trade", "preview"): (collection_trade.preview_trade, collection_trade.MAX_TRADE_BODY),
        ("collection", "trade"): (collection_trade.save_trade, collection_trade.MAX_TRADE_BODY),
        ("precons", "add"): precons.add_precon,
        ("precons", "start"): precon_coverage.start_deck,
        ("precons", "trial"): _trial_start,       # deck.create, as POST /api/precons/start
        ("precons", "trial", "keep"): _trial_keep,      # deck.edit on the trial deck
        ("field", "policy", "preview"): (_field_choice_preview, 8192),     # a review: nothing is written
        ("field", "policy"): (_field_choice_save, 8192),                  # field.edit: a home admin's
        ("deck", "cover"): cover.save_cover,
        ("deck", "token-cards"): token_cards.save_token_cards,
        ("deck", "printings"): deck_printings.save_printings,
        ("deck", "box-check"): box_check.save_box_check,
        ("deck", "box-repair"): box_repair.repair_box,
        ("deck", "opponents"): opponents.save_opponents,
        ("deck", "draft"): (deck_drafts.save_draft, deck_drafts.MAX_BODY),     # the viewer's own; not audited
        ("deck", "new-draft"): (deck_drafts.save_new_draft, deck_drafts.MAX_BODY),     # the same, for a new deck
        ("deck", "considering"): considering.save_considering,
        ("deck", "cuts"): (deck_cuts.preview_cuts, deck_cuts.MAX_BODY),
        ("deck", "bracket-replacements"): (bracket_fixes.replacements, bracket_fixes.MAX_BODY),
        ("deck", "swaps"): swaps.suggest_draft_swaps,      # a dry run: nothing is written
        ("deck", "retire"): retirement.retire_deck,
        ("deck", "rename", "preview"): rename.preview_rename,
        ("deck", "rename"): rename.rename_deck,
        ("deck", "restore"): retirement.restore_deck,
        ("server", "restart"): (server_restart.restart, server_restart.MAX_BODY),     # a named home admin's
        ("gauntlet", "run"): _gauntlet_run,        # run.start (require_start), after the deck's 404
        ("gauntlet", "stop"): (_gauntlet_stop, MAX_BODY),     # run.stop: its starter, its deck's space or an admin
        ("field", "group", "run"): _group_run,       # run.start (require_start), after every deck's 404
        ("field", "group", "stop"): (_group_stop, MAX_BODY),  # run.stop, as the field's
        ("crosscheck", "run"): (_crosscheck_run, MAX_BODY),
        ("crosscheck", "stop"): (_crosscheck_stop, MAX_BODY),
        ("forge", "resume"): (run_recovery.resume, run_recovery.MAX_BODY),
        ("forge", "dismiss"): (run_recovery.dismiss, run_recovery.MAX_BODY),
        ("errors", "report"): (error_reports.report, error_reports.MAX_BODY),  # bounded operational metadata only
        ("visit",): (visits.beacon, MAX_BODY),      # not a data write: no guard rule, the requester's own visit
    }
    return gets, posts


def dispatch(handler, route, query):
    gets, posts = route_tables()
    key = tuple(route)
    if key in gets and not (key in posts and handler.command == "POST"):
        declared_access("GET", key)
        handler._allow("GET", "HEAD")
        function, names = gets[key]
        params = handler._query(query, names)
        if "id" in names and key not in {("activity", "undo"), ("activity", "wishlist-undo"), ("activity", "accessory-undo"),
                                         ("activity", "mixed-undo"), ("activity", "product-kit-undo"), ("play", "sideboard-preview"),
                                         ("play", "sideboard-tests")}:
            params["deck_id"] = handler._deck_id(params) if "id" in params else None
            params.pop("id", None)
        answer = function(**params)
        from decklab.lib.api.common import Download
        if isinstance(answer, Download):
            try:
                handler._send(200, b"", answer.content_type,
                              (("Cache-Control", "no-store, private"),
                               ("Content-Disposition", f'attachment; filename="{answer.filename}"')),
                              stream=answer.stream, length=answer.size)
            finally:
                answer.close()
            return True
        handler._send_json(_status(key, answer), answer)
        return True
    if key in posts:
        declared_access("POST", key)
        handler._allow("POST")
        handler._no_query(query)
        function, limit = posts[key] if isinstance(posts[key], tuple) else (posts[key], None)
        answer = function(handler._write_body(limit))
        handler._send_json(_status(key, answer), answer)
        return True
    return False
