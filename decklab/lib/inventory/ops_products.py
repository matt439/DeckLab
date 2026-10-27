"""An intact product's packed-token record, checked again under the inventory lock."""
import re

from decklab.lib import decks, spaces

from . import Conflict, Invalid, Summary, files, kit, paths, register, rules

KIND = "product.set_tokens"
CHANGED = "The product or token cards changed. Reload the product and choose again."
SHA = re.compile(r"[0-9a-f]{64}")


def product_row(inv, stem):
    """Exactly one readable status row for an actual product; no route-prefix inference."""
    if not isinstance(stem, str) or not rules.SLUG.fullmatch(stem) or stem == "status":
        raise Invalid("Choose a valid product id.")
    products = [product for product in inv.products if product.stem == stem]
    if not products:
        raise Invalid("This product is no longer available.")
    if len(products) != 1:
        raise Invalid("This product needs exactly one card-list record before its packed tokens can change.")
    product = products[0]
    sheet = inv.status
    if not sheet.exists or sheet.error is not None or sheet.strict_error is not None:
        raise Invalid("The products' status cannot be read. Correct it before changing packed tokens.")
    found = [row for row in sheet.rows if row.text("file").strip() == product.file]
    if len(found) != 1:
        raise Invalid("This product needs exactly one status record before its packed tokens can change.")
    return found[0]


def canonical(value):
    """Canonical bounded token-card syntax; blank removes the packing record."""
    if not isinstance(value, str):
        raise Invalid("Packed token cards must be text.")
    try:
        return decks.format_token_cards(decks.parse_token_cards(value))
    except (ValueError, decks.DeckFileError) as error:
        raise Invalid(f"The packed token cards cannot be written: {error}") from None


def token_sha256(inv):
    sheet = inv.token_set(spaces.HOME)
    return files.rendered_sha256(sheet) if sheet.exists else None


@register(KIND)
def set_tokens(inv, *, stem, sha256, tokens_sha256, token_cards):
    """Change only one owned intact product's record; both source hashes are receipts."""
    if not isinstance(sha256, str) or not SHA.fullmatch(sha256):
        raise Invalid("Reload the product before changing its packed token cards.")
    if tokens_sha256 is not None and (not isinstance(tokens_sha256, str) or not SHA.fullmatch(tokens_sha256)):
        raise Invalid("Reload the token cards before choosing their rows.")
    if kit.status_sha256(inv) != sha256 or token_sha256(inv) != tokens_sha256:
        raise Conflict(CHANGED)
    row = product_row(inv, stem)
    if not kit.can_hold(row):
        raise Invalid("Only an owned product kept intact can pack token cards.")
    value = canonical(token_cards)
    if row.text("token_cards") == value:
        return inv, Summary("Nothing to change")
    rows = [item.replace(token_cards=value) if item is row else item for item in inv.status.rows]
    count = sum(line.quantity for line in decks.parse_token_cards(value))
    return inv.with_status_rows(rows), Summary(f"Recorded packed token cards for {stem}", {"token_cards": count},
                                               {paths.STATUS: [f"token cards of {stem}"]})
