"""One revision-bound token plan across ordinary decks and intact products.

All receipts refer to the original snapshot. The existing operations compose on
immutable snapshots; neither a helper nor this operation invokes apply itself.
The backend therefore persists every changed deck/status row in one audit set.
"""
from decklab.lib import spaces

from . import Conflict, Invalid, Summary, files, kit, ops_decks, ops_products, register, rules

KIND = "tokens.plan"
CHANGED = "Something changed since the preview. Look at the new plan and apply it again."


class PlanChanged(Conflict):
    reason = "changed"


def _items(inv, space, items):
    if not isinstance(items, list):
        raise Invalid("A token plan needs a list of deck changes.")
    ids = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "text", "base_sha256"}:
            raise Invalid("Each token-plan deck needs its id, text and source hash.")
        deck_id = item["id"]
        if not isinstance(deck_id, str) or deck_id in ids:
            raise Invalid("Change each token-plan deck only once.")
        ids.add(deck_id)
        stored = inv.deck(deck_id)
        if stored is None or stored.sha256 != item["base_sha256"]:
            raise PlanChanged(CHANGED)
        if stored.space != space:
            raise Invalid("A token plan changes only decks of its own space.")


def _products(inv, space, products):
    if not isinstance(products, list):
        raise Invalid("A token plan needs a list of product changes.")
    if space != spaces.HOME and products:
        raise Invalid("A person's token plan cannot change products.")
    stems, made = set(), []
    for product in products:
        if not isinstance(product, dict) or set(product) != {"stem", "token_cards"}:
            raise Invalid("Each planned product needs its id and packed-token record.")
        stem = product["stem"]
        if not isinstance(stem, str) or stem in stems:
            raise Invalid("Change each token-plan product only once.")
        stems.add(stem)
        row = ops_products.product_row(inv, stem)
        if not kit.can_hold(row):
            raise Invalid("Only an owned product kept intact can pack token cards.")
        made.append({"stem": stem, "token_cards": ops_products.canonical(product["token_cards"])})
    return made


@register(KIND)
def apply_plan(inv, *, space, items, products, expected_inventory_revision,
               expected_decks_revision, expected_status_sha256, tokens_sha256):
    if not isinstance(space, str) or not rules.SLUG.fullmatch(space):
        raise Invalid("Choose a valid space for the token plan.")
    if inv.revision != expected_inventory_revision or inv.decks_revision != expected_decks_revision:
        raise PlanChanged(CHANGED)
    sheet = inv.token_set(space)
    token_sha = files.rendered_sha256(sheet) if sheet.exists else None
    if token_sha != tokens_sha256:
        raise PlanChanged(CHANGED)
    if space == spaces.HOME:
        if kit.status_sha256(inv) != expected_status_sha256:
            raise PlanChanged(CHANGED)
    elif expected_status_sha256 is not None:
        raise Invalid("A person's token plan has no product-status receipt.")
    # Validate every original source and every product before staging the first change.
    _items(inv, space, items)
    proposed = _products(inv, space, products)
    out, deck_summary = ops_decks.token_cards(inv, items=items,
        expected_inventory_revision=expected_inventory_revision, expected_decks_revision=expected_decks_revision)
    changed = {path: list(fields) for path, fields in deck_summary.changed.items()}
    deck_ids = [item["id"] for item in items if inv.deck(item["id"]).path in changed]
    product_ids = []
    for product in proposed:
        # Original whole-plan hashes were checked above. Only the status hash evolves
        # while composing these validated product updates in the same snapshot.
        out, summary = ops_products.set_tokens(out, stem=product["stem"], token_cards=product["token_cards"],
            sha256=kit.status_sha256(out), tokens_sha256=tokens_sha256)
        if summary.changed:
            product_ids.append(product["stem"])
        for path, fields in summary.changed.items():
            changed.setdefault(path, []).extend(field for field in fields if field not in changed.get(path, []))
    if not changed:
        return inv, Summary("Nothing to change")
    return out, Summary(f"Planned packed token cards in {len(deck_ids)} decks and {len(product_ids)} products",
                        {"decks": len(deck_ids), "products": len(product_ids)}, changed,
                        {"decks": deck_ids, "products": product_ids})
