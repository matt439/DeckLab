"""POST /api/deck/token-cards (save_token_cards): which token cards a built deck packs.

They're the deck text's optional "Token cards" header line (lib/decks/tokencards.py), which other
decks of its space then count as in use (lib/tokens/reserve.py). A save changes that line alone
(decks.set_token_cards, then render_deck_file, which copies everything else byte for byte) and is
one inventory operation, deck.save, as the cover save is (cover.py): one change set in the audit
trail and one revision in the deck's history, by the profile asking. Nothing is committed to git.
"""
from decklab.lib import decks, inventory, spaces, tokens

from . import guard
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public
from .cover import _expected
from .saving import _deck_refused, apply_op
from .settings import _writer

MAX_CARDS = decks.tokencards.MAX_LINES


def _chosen(value, inv):
    """[TokenCardLine] for the request's cards ([{row, quantity}], row an index into the space's
    token cards as the deck page read them), one line per row's faces and printing, quantities
    added. ApiError 400 for anything else."""
    if not isinstance(value, list) or len(value) > MAX_CARDS:
        raise ApiError(400, f"cards must be a list of at most {MAX_CARDS} {{row, quantity}}")
    lines = {}
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "Each card must be {row, quantity}")
        _keys(item, ("row", "quantity"))
        row, qty = item["row"], item["quantity"]
        if isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < len(inv.rows):
            raise ApiError(400, "A card's row must be one of the space's token cards")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= decks.tokencards.MAX_QUANTITY:
            raise ApiError(400, f"A card's quantity must be a whole number from 0 to {decks.tokencards.MAX_QUANTITY}")
        if not qty:
            continue
        line = tokens.reserve.line_for(inv.rows[row], qty)
        key = (line.front, line.back, line.set, line.number)
        if key in lines:
            qty += lines[key].quantity
            line = decks.TokenCardLine(qty, line.front, line.back, line.set, line.number)
        lines[key] = line
    return list(lines.values())


def save_token_cards(body):
    """POST /api/deck/token-cards {"profile", "id", "expect", "tokens_sha256", "cards": [{row, quantity}]}.

    Sets a built deck's Token cards line to those cards (rows of its space's token cards, as the
    deck page's Tokens part lists them; [] keeps an empty line: it packs none). The deck must be a
    built deck text (400 otherwise), the profile may change it as it may save its text (guard
    deck.edit, 403 otherwise) and see its space's token cards (require_sees_inventory). expect is
    the deck's revision or text sha256 (409 with "conflict" when it changed since), tokens_sha256
    the token cards' list the rows index (409 when it changed: read the deck again).

    Returns {"saved": whether the text changed, "id", "title", "revision", "token_cards": the
    line as written}."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expect", "tokens_sha256", "cards"))
    kind, slug, path = _deck_file(data["id"])
    deck_id = data["id"]
    stored = _stored(deck_id, viewer=profile)
    deck = _parse_file(stored.data, kind, slug, path, deck_id)
    guard.require(profile, "deck.edit", deck)
    space = spaces.space_of(deck_id)
    guard.require_sees_inventory(space)
    if not _expected(stored, data["expect"]):
        raise _conflict(deck_id, deck.title, viewer=profile)
    if deck.status != "built":
        raise ApiError(400, "Only a built deck packs token cards: mark it built first")
    inv = tokens.read(space=space)
    if data["tokens_sha256"] != inv.sha256:
        raise ApiError(409, "The token cards changed since this page was read. Reload it and choose again.")
    chosen = _chosen(data["cards"], inv)
    try:
        decks.set_token_cards(deck, chosen)
        out = decks.render_deck_file(deck)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(400, f"The token cards can't be written: {_public(e)}") from None
    revision = stored.revision
    if out != stored.text:
        what = (f"pack token cards in {deck.title}: {decks.format_token_cards(chosen)}" if chosen
                else f"pack no token cards in {deck.title}")
        op = inventory.Op("deck.save", {"deck_id": deck_id, "text": out, "base_sha256": stored.sha256})
        after, _ = apply_op(op, profile, what, _deck_refused(deck_id, deck.title, profile))
        held = after.deck(deck_id)
        revision = held.revision if held is not None else 0
    return {"saved": out != stored.text, "id": deck_id, "title": deck.title, "revision": revision,
            "token_cards": deck.get_field(decks.TOKEN_CARDS_FIELD)}
