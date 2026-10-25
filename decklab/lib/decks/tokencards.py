"""A built deck's packed token cards: which of its space's token cards are in its deck box.

A built deck may say which token and reminder cards it packs, and how many, with an optional
header line that Deck Lab keeps as written (it's not one of the fields it owns, OWNED_FIELDS):

    - **Token cards:** 2 Treasure (TFDN) 12; 1 Beast // Dog; 1 The Monarch

Each "; "-separated part is a count and a token card's faces as the Tokens page names them
(the front, " // " and the back of a double-sided card), with its printing (" (SET) 123", the
set and front collector number) when only that printing will do. Those cards count as in use
for every other deck of the space (lib/tokens reserve), as a built deck's playable cards do.
Only built decks reserve: taking a deck apart (assembled.clear) removes the line. Finish
building writes it for a deck that has none; the deck page's token sheet (POST
/api/deck/token-cards) and `deck push` change it.

parse_token_cards reads the field's value, format_token_cards writes one.
"""
import re
from dataclasses import dataclass

from .deckfile import HeaderField, _one_line
from .decklist import DeckFileError

TOKEN_CARDS_FIELD = "Token cards"
MAX_LINES = 200
MAX_QUANTITY = 9999
MAX_NAME = 200
_PART_RE = re.compile(r"^(\d{1,4}) +(.+?)(?: +\(([A-Za-z0-9]{1,8})\) +([A-Za-z0-9★†-]{1,12}))?$")


@dataclass(frozen=True)
class TokenCardLine:
    """quantity cards of a token card: front and back face names (back "" for a single face),
    set (lowercase) and number ("" when any printing will do)."""
    quantity: int
    front: str
    back: str = ""
    set: str = ""
    number: str = ""

    def text(self):
        faces = self.front + (f" // {self.back}" if self.back else "")
        return f"{self.quantity} {faces}" + (f" ({self.set.upper()}) {self.number}" if self.set else "")


def parse_token_cards(value):
    """[TokenCardLine] from a Token cards field's value, in its order; [] for a blank value.
    DeckFileError for a part that isn't "N Front[ // Back][ (SET) NUM]", a count of 0, too many
    parts or a name that's too long."""
    text = (value or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(";")]
    if len(parts) > MAX_LINES:
        raise DeckFileError(f"Token cards lists more than {MAX_LINES} cards")
    out = []
    for part in parts:
        if not part:
            continue
        m = _PART_RE.match(part)
        if not m:
            raise DeckFileError(f"Token cards: {part!r} isn't a count and a token card's name")
        quantity, faces, set_code, number = m.groups()
        quantity = int(quantity)
        if not 1 <= quantity <= MAX_QUANTITY:
            raise DeckFileError(f"Token cards: {part!r} needs a count from 1 to {MAX_QUANTITY}")
        front, _, back = faces.partition(" // ")
        front, back = front.strip(), back.strip()
        if not front or len(front) > MAX_NAME or len(back) > MAX_NAME or "//" in back or "//" in front:
            raise DeckFileError(f"Token cards: {part!r} isn't a token card's name")
        out.append(TokenCardLine(quantity, front, back, (set_code or "").lower(), number or ""))
    return out


def format_token_cards(lines):
    """The field's value for [TokenCardLine] (or "" for none). ValueError for one that wouldn't
    read back the same."""
    text = "; ".join(line.text() for line in lines)
    _one_line(text)
    try:
        back = parse_token_cards(text)
    except DeckFileError as e:
        raise ValueError(str(e)) from None
    if back != list(lines):
        raise ValueError(f"can't write {text!r} as token cards")
    return text


def token_cards(deck):
    """The deck's packed token cards ([TokenCardLine], [] without the line). DeckFileError for a
    line that can't be read."""
    fields = [f for f in deck.header if f.key.lower() == TOKEN_CARDS_FIELD.lower()]
    if len(fields) > 1:
        raise DeckFileError("The deck has more than one Token cards line")
    return parse_token_cards(fields[0].value) if fields else []


def has_token_cards(deck):
    """True when the deck's text has a Token cards line (even an empty one)."""
    return any(f.key.lower() == TOKEN_CARDS_FIELD.lower() for f in deck.header)


def set_token_cards(deck, lines):
    """Set the deck's Token cards line to lines ([TokenCardLine]), or None to remove it. [] keeps
    an empty line, which says the deck packs no token cards (so Finish building doesn't fill it).
    A new line goes at the end of the header; one already there is rewritten in place, and one
    that already says the same is left as written."""
    index = next((i for i, f in enumerate(deck.header) if f.key.lower() == TOKEN_CARDS_FIELD.lower()), None)
    if lines is None:
        if index is not None:
            del deck.header[index]
        return
    value = format_token_cards(lines)
    if index is not None:
        old = deck.header[index]
        try:
            if parse_token_cards(old.value) == list(lines):
                return
        except DeckFileError:
            pass
        deck.header[index] = HeaderField(TOKEN_CARDS_FIELD, value, None, old.end)
        return
    deck.header.append(HeaderField(TOKEN_CARDS_FIELD, value))
