"""Routes for collection, physical play, delivery, accessories and tokens tools, the Activity page, and visits
(the page's beacon, POST /api/visit, and the Settings page's GET /api/visits: api/visits.py).

Use the server's normal query, method and same-origin write guards. Each
part of the API is imported when first asked for. A POST takes at most
api.MAX_EDIT_BODY bytes, except routes with their explicit bound, including
pod records (play_pods.MAX_BODY), import previews (collection_edit.MAX_IMPORT_BODY)
and accessory saves with a local picture (accessories.MAX_SAVE_BODY).
"""


def _field_membership_view(**params):
    """Load Forge's membership adapter only for an allowed field request."""
    from decklab.lib.api.field_membership import membership_view
    return membership_view(**params)


def _sideboard_preview(**params):
    """Load the sideboard preview, which reads Forge's paired-game budgets, only when asked for."""
    from decklab.lib.api.sideboard_preview import preview_sideboard
    return preview_sideboard(**params)


def dispatch(handler, route, query):
    from decklab.lib.api import (accessories, accessory_undo, activity, arrivals, activity_mixed_undo, activity_undo, assembly, assembly_completion, assembly_standins, assembly_ticks, box_check, box_repair, collection, compare, considering, collection_edit, collection_locations, collection_trade, cover, deck_printings, edhrec, editor, history,
                                 library_forge, maintenance, opponents, play_pods, play_records, play_tonight, precon_coverage, precons, products, product_tokens, rankings, receipts, rename, retirement, shopping, shopping_order_changes, shopping_orders, shopping_queue, shopping_queue_missing, swaps, token_cards, token_plan, tokens, variant_queue, visits, wishlist_undo)
    from decklab.lib.api.common import MAX_BODY

    gets = {
        ("settings", "maintenance"): (maintenance.maintenance_view, ()),
        ("collection",): (collection.collection_view,
                         ("q", "color", "type", "role", "mv", "availability", "page", "limit", "space")),
        ("collection", "rows"): (collection_edit.rows_view, ("space",)),
        ("collection", "download"): (collection_edit.download_view, ("space",)),
        ("printings",): (collection_edit.printings_view, ("name",)),
        ("precons",): (precons.precons_view, ("q",)),
        ("precons", "preview"): (precons.precon_preview, ("file", "space")),
        ("precons", "coverage"): (precon_coverage.coverage_view, ("space", "format", "type", "limit")),
        ("precons", "coverage", "deck"): (precon_coverage.coverage_deck, ("file", "space")),
        ("assembly",): (assembly.assembly_view, ("deck", "version")),
        ("compare", "shared"): (compare.shared_view, ("a", "av", "b", "bv")),
        ("play",): (play_records.play_overview, ("id",)),
        ("play", "sideboard-preview"): (_sideboard_preview, ("id", "sha256")),
        ("play", "pairs"): (play_tonight.pairs_view, ()),
        ("deck", "history"): (history.deck_history, ("id",)),
        ("deck", "retire"): (retirement.retirement_view, ("id",)),
        ("deck", "rename"): (rename.rename_view, ("id",)),
        ("deck", "find"): (editor.find_cards, ("q", "scope", "colors", "type", "mv", "id", "space", "limit", "page")),
        ("deck", "revision"): (history.deck_revision, ("id", "revision", "version")),
        ("deck", "swaps"): (swaps.suggest_swaps, ("id", "version", "card")),
        ("deck", "replacements"): (swaps.suggest_replacements, ("id", "version", "card")),
        ("deck", "cards"): (cover.cover_cards, ("id",)),
        ("deck", "opponents"): (opponents.opponents_view, ("id",)),
        ("deck", "edhrec"): (edhrec.edhrec_view, ("id",)),
        ("receipt",): (receipts.receipt_view, ("order",)),
        ("arrivals",): (arrivals.arrivals_view, ()),
        ("rankings",): (rankings.rankings_view, ("format",)),
        ("field", "membership"): (_field_membership_view, ("id", "version")),
        ("library", "forge"): (library_forge.library_forge_view, ()),
        ("product",): (products.product_state, ("stem",)),
        ("accessories",): (accessories.accessories_view, ()),
        ("tokens",): (tokens.tokens_view, ("space",)),
        ("tokens", "plan"): (token_plan.plan_view, ("space",)),
        ("activity",): (activity.activity_view, ("before", "limit", "kind", "actor")),
        ("activity", "undo"): (activity_undo.undo_view, ("id",)),
        ("activity", "wishlist-undo"): (wishlist_undo.wishlist_undo_view, ("id",)),
        ("activity", "accessory-undo"): (accessory_undo.accessory_undo_view, ("id",)),
        ("activity", "mixed-undo"): (activity_mixed_undo.mixed_undo_view, ("id",)),
        ("visits",): (visits.visits_view, ("days", "who")),
    }
    posts = {
        ("activity", "undo"): activity_undo.apply_undo,
        ("activity", "wishlist-undo"): wishlist_undo.apply_wishlist_undo,
        ("activity", "accessory-undo"): accessory_undo.apply_accessory_undo,
        ("activity", "mixed-undo"): activity_mixed_undo.apply_mixed_undo,
        ("assembly", "preview"): assembly.assembly_preview,
        ("assembly", "built"): assembly_completion.mark_built,
        ("assembly", "ticks"): (assembly_ticks.packing_ticks, assembly_ticks.MAX_BODY),
        ("assembly", "standins"): assembly_standins.save_standins,
        ("play", "game"): play_records.save_game,
        ("play", "pod"): (play_pods.save_pod, play_pods.MAX_BODY),
        ("play", "sideboard"): play_records.save_sideboard,
        ("receipt", "preview"): receipts.preview_receipt,
        ("receipt", "apply"): receipts.apply_receipt,
        ("arrivals", "dismiss"): arrivals.dismiss_arrivals,
        ("product", "intact", "preview"): products.preview_storage,
        ("product", "intact", "apply"): products.apply_storage,
        ("product", "token-cards"): product_tokens.save_product_tokens,
        ("shopping", "check"): shopping.resolve_check,
        ("shopping", "queue"): shopping_queue.save_queue_state,
        ("shopping", "queue", "missing"): shopping_queue_missing.review_missing,     # a review: nothing is written
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
        ("tokens", "plan"): token_plan.apply_plan,
        ("collection", "save"): collection_edit.save_card,
        ("collection", "bulk"): (collection_edit.bulk_set, collection_edit.MAX_BULK_BODY),
        ("collection", "locations", "bulk"): (collection_locations.bulk_set, collection_edit.MAX_BULK_BODY),
        ("collection", "import", "preview"): (collection_edit.import_preview, collection_edit.MAX_IMPORT_BODY),
        ("collection", "import", "apply"): collection_edit.import_apply,
        ("collection", "trade", "preview"): (collection_trade.preview_trade, collection_trade.MAX_TRADE_BODY),
        ("collection", "trade"): (collection_trade.save_trade, collection_trade.MAX_TRADE_BODY),
        ("precons", "add"): precons.add_precon,
        ("precons", "start"): precon_coverage.start_deck,
        ("deck", "cover"): cover.save_cover,
        ("deck", "token-cards"): token_cards.save_token_cards,
        ("deck", "printings"): deck_printings.save_printings,
        ("deck", "box-check"): box_check.save_box_check,
        ("deck", "box-repair"): box_repair.repair_box,
        ("deck", "opponents"): opponents.save_opponents,
        ("deck", "considering"): considering.save_considering,
        ("deck", "swaps"): swaps.suggest_draft_swaps,      # a dry run: nothing is written
        ("deck", "retire"): retirement.retire_deck,
        ("deck", "rename", "preview"): rename.preview_rename,
        ("deck", "rename"): rename.rename_deck,
        ("deck", "restore"): retirement.restore_deck,
        ("visit",): (visits.beacon, MAX_BODY),      # not a data write: no guard rule, the requester's own visit
    }
    key = tuple(route)
    if key in gets and not (key in posts and handler.command == "POST"):
        handler._allow("GET", "HEAD")
        function, names = gets[key]
        params = handler._query(query, names)
        if "id" in names and key not in {("activity", "undo"), ("activity", "wishlist-undo"), ("activity", "accessory-undo"),
                                         ("activity", "mixed-undo"), ("play", "sideboard-preview")}:
            params["deck_id"] = handler._deck_id(params) if "id" in params else None
            params.pop("id", None)
        handler._send_json(200, function(**params))
        return True
    if key in posts:
        handler._allow("POST")
        handler._no_query(query)
        function, limit = posts[key] if isinstance(posts[key], tuple) else (posts[key], None)
        handler._send_json(200, function(handler._write_body(limit)))
        return True
    return False
