"""The Tokens page's "Plan packed token cards": built decks and intact product boxes worked out at once
(lib/tokens/optimise.py), previewed, then saved as one change.

    GET  /api/tokens/plan[?space=]   plan_view(): each built deck's line as it is and as planned
    POST /api/tokens/plan            apply_plan(body): save every changed line, all or none

Both need the space's inventory and tokens.edit; a public collection does not publish private
whole-space packing recipes. The apply also needs
deck.edit on every deck whose line changes (403 naming the first it may not change, before anything is
written) and the plan's sha256 from the preview: the plan is worked out again and must come out the
same (the decks' texts, the token cards and the planned lines), else 409 "Something changed since the
preview". Every changed product also needs products.edit. The save is one tokens.plan operation:
one change set covering product status records and each changed deck's history. Original inventory,
deck and source-list receipts are checked under its write lock. Nothing is committed to git.
"""
from decklab.lib import decks, inventory, tokens
from decklab.lib.inventory import ops_token_plan

from . import guard
from .collection import space_param as _space
from .common import ApiError, _keys, _parse_body, _public
from .saving import apply_op
from .settings import _writer

CHANGED = "Something changed since the preview. Look at the new plan and apply it again."


def _plan(space):
    warnings = []
    try:
        result = tokens.plan_token_cards(space, warnings)
    except RuntimeError as e:          # the card index is missing or being rebuilt
        raise ApiError(503, _public(e)) from None
    return result, warnings


def _deck_json(item, profile):
    return {key: item[key] for key in ("id", "title", "before", "after", "lines", "changed", "short", "spares")} | {
        "packs": [{k: p[k] for k in ("token", "card", "side", "verdict")} for p in item["packs"]],
        "editable": guard.allowed(profile, "deck.edit", item["parsed"])}


def _product_json(item, profile):
    out = {key: item[key] for key in ("stem", "holder", "title", "link", "before", "after", "lines", "changed")}
    out["decks"] = [{key: deck[key] for key in ("id", "title", "short", "spares")} | {
        "packs": [{key: pack[key] for key in ("token", "card", "side", "verdict")} for pack in deck["packs"]]}
        for deck in item["decks"]]
    out["editable"] = guard.allowed(profile, "products.edit")
    return out


def plan_view(space=None):
    """GET /api/tokens/plan: {"space", "sha256", "tokens_sha256", "decks": [{id, title, before, after,
    lines, changed, packs, short, spares, editable}], "changes": decks whose line would change,
    "products": [{stem,holder,title,link,before,after,lines,changed,decks,editable}],
    "product_changes", "warnings"}."""
    space = _space(space)
    guard.require_sees_inventory(space)
    profile = guard.viewer()
    # A public token collection does not publish private deck packing recipes.
    guard.require_space_write(profile, "tokens.edit", space)
    result, warnings = _plan(space)
    out = [_deck_json(item, profile) for item in result["decks"]]
    products = [_product_json(item, profile) for item in result.get("products", [])]
    return {"space": space, "sha256": result["sha256"], "tokens_sha256": result["tokens_sha256"], "decks": out,
            "changes": sum(1 for d in out if d["changed"]), "products": products,
            "product_changes": sum(1 for item in products if item["changed"]), "warnings": warnings}


def apply_plan(body):
    """POST /api/tokens/plan {"profile", "space", "sha256"}: the previewed plan saved. Returns
    {"saved": decks changed, "decks": [id]}; when products change, also
    {"saved_products": count, "products": [stem]}."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "sha256"), ("space",))
    space = _space(data.get("space"))
    guard.require_sees_inventory(space)
    guard.require_space_write(profile, "tokens.edit", space)
    result, _ = _plan(space)
    if data["sha256"] != result["sha256"]:
        raise ApiError(409, CHANGED, conflict=True)
    changed = [item for item in result["decks"] if item["changed"]]
    changed_products = [item for item in result.get("products", []) if item["changed"]]
    for item in changed:
        if not guard.allowed(profile, "deck.edit", item["parsed"]):
            raise ApiError(403, f"You can't change {item['title']}'s token cards.")
    for product in changed_products:
        guard.require(profile, "products.edit")
    if not changed and not changed_products:
        return {"saved": 0, "decks": []}
    items = []
    for item in changed:
        parsed = item["parsed"]
        try:
            decks.set_token_cards(parsed, decks.parse_token_cards(item["after"]))
            text = decks.render_deck_file(parsed)
        except (decks.DeckFileError, ValueError) as e:
            raise ApiError(400, f"{item['title']}'s token cards can't be written: {_public(e)}") from None
        items.append({"id": item["id"], "text": text, "base_sha256": item["sha256"]})
    what = f"plan packed token cards for {len(items)} built deck{'s' if len(items) != 1 else ''}"
    if changed_products:
        what += f" and {len(changed_products)} intact product{'s' if len(changed_products) != 1 else ''}"

    def refused(e):
        return ApiError(409, CHANGED, conflict=True) if getattr(e, "reason", None) == "changed" else None
    _, summary = apply_op(inventory.Op(ops_token_plan.KIND, {"space": space, "items": items,
             "products": [{"stem": item["stem"], "token_cards": item["after"]} for item in changed_products],
             "expected_inventory_revision": result["inventory_revision"],
             "expected_decks_revision": result["decks_revision"],
             "expected_status_sha256": result.get("status_sha256"),
             "tokens_sha256": result["tokens_sha256"]}), profile, what, refused)
    answer = {"saved": summary.counts.get("decks", 0), "decks": list(summary.extra.get("decks", []))}
    if changed_products:
        answer.update(saved_products=summary.counts.get("products", 0), products=list(summary.extra.get("products", [])))
    return answer
