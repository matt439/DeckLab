"""The home-only product token picker, with product and token-list receipts."""
from decklab.lib import decks, inventory, tokens
from decklab.lib.inventory import kit, ops_products

from . import guard
from .common import ApiError, _keys, _parse_body, state_errors
from .saving import apply_op
from .settings import _writer
from .token_cards import _chosen


def status_sha256(snapshot):
    """The packed projection and writer use the same canonical product-list receipt."""
    return kit.status_sha256(snapshot)


def save_product_tokens(body):
    """POST /api/product/token-cards {profile,stem,expect,tokens_sha256,cards}.

    cards uses the deck picker's {row,quantity} shape. [] clears the product's
    record, restoring its legacy too-few-token warning; it is not an explicit
    'packs none' record. This changes no inventory token quantities or kit.
    """
    data = _parse_body(body)
    profile = _writer(data)
    guard.require_sees_home_records(profile)
    guard.require(profile, "products.edit")
    _keys(data, ("profile", "stem", "expect", "tokens_sha256", "cards"))
    if not isinstance(data["expect"], str) or not ops_products.SHA.fullmatch(data["expect"]):
        raise ApiError(400, "Reload the product before changing its packed token cards.")
    token_sha = data["tokens_sha256"]
    if token_sha is not None and (not isinstance(token_sha, str) or not ops_products.SHA.fullmatch(token_sha)):
        raise ApiError(400, "Reload the token cards before choosing their rows.")
    with state_errors(), inventory.pinned():
        before = inventory.current()
        ops_products.product_row(before, data["stem"])
        inv = tokens.read()
        # Verify the receipts before interpreting row indices from an older page.
        if status_sha256(before) != data["expect"] or inv.sha256 != data["tokens_sha256"]:
            raise ApiError(409, ops_products.CHANGED, conflict=True)
        try:
            value = decks.format_token_cards(_chosen(data["cards"], inv))
        except ValueError as error:
            raise ApiError(400, str(error)) from None
        op = inventory.Op(ops_products.KIND, {"stem": data["stem"], "sha256": data["expect"],
                         "tokens_sha256": data["tokens_sha256"], "token_cards": value})
        after, summary = apply_op(op, profile, f"record packed token cards for product {data['stem']}")
        return {"saved": bool(summary.changed), "stem": data["stem"], "token_cards": value,
                "status_sha256": status_sha256(after), "tokens_sha256": inv.sha256}
