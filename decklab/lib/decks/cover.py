"""A deck's cover card: the card whose art stands for the deck on the library's shelf.

By default it's chosen automatically from the Planned (target) list (auto_cover_line): the
commander (the first card of the Commander section), else the non-land with the most copies in
the Commander, Companion and Deck sections; on a tie a creature, then the first of them in list
order (so a deck of singles shows its first creature, not its first instant). A deck
text can name its own with an optional header line, which Deck Lab keeps as written (it's not
one of the fields it owns, OWNED_FIELDS); only the cover save (POST /api/deck/cover, set_cover)
rewrites it:

    - **Cover card:** Llanowar Elves
    - **Cover card:** Llanowar Elves (FDN) 227

The name is the exact Scryfall card name; the optional " (SET) 123" names a printing (the art
of that printing is shown). parse_cover reads the field's value, format_cover writes one.
Whether the name is a Scryfall card is the API's to check (lib/api/library.py deck_cover).
"""
import re

from .deckfile import HeaderField, _one_line
from .decklist import LINE_RE, SET_IN_NAME_RE

COVER_FIELD = "Cover card"
COVER_SECTIONS = ("Commander", "Companion", "Deck")     # where the automatic cover is looked for
MAX_COVER_NAME = 200


def parse_cover(value):
    """{"name", "set", "number"} from a Cover card field's value ("Llanowar Elves (FDN) 227" or
    "Llanowar Elves"; set lowercase, set and number None when not given), or None for a blank
    value or one that isn't in that form (a bare "(SET)" with no number, a finish, a garbled
    line)."""
    text = (value or "").strip()
    if not text or len(text) > MAX_COVER_NAME + 20:
        return None
    m = LINE_RE.match(f"1 {text}")
    if not m:
        return None
    _, name, set_code, number, bare_set, finish = m.groups()
    if bare_set or finish or SET_IN_NAME_RE.search(name):
        return None
    return {"name": name.strip(), "set": set_code.lower() if set_code else None, "number": number or None}


def format_cover(name, set_code=None, number=None):
    """The field's value for a cover: "Name" or "Name (SET) 123". ValueError for a value that
    wouldn't read back the same (a line break, a printing with only one of set and number, a
    name that looks like it has a printing in it)."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_COVER_NAME:
        raise ValueError(f"bad cover card name {name!r}")
    if bool(set_code) != bool(number):
        raise ValueError("a cover card's printing needs both its set and its collector number")
    text = name.strip() + (f" ({set_code.upper()}) {number}" if set_code else "")
    _one_line(text)
    back = parse_cover(text)
    if back != {"name": name.strip(), "set": set_code.lower() if set_code else None, "number": number or None}:
        raise ValueError(f"can't write {text!r} as a cover card")
    return text


def cover_field(deck):
    """The deck's Cover card as written (parse_cover of its field), or None."""
    return parse_cover(deck.get_field(COVER_FIELD))


def set_cover(deck, cover):
    """Set the deck's Cover card line: cover is {"name", "set"?, "number"?}, or None to remove the
    line (back to the automatic cover). A new line goes at the end of the header; one already
    there is rewritten in place. A line that already says the same is left as written. Only the
    header changes; render_deck_file keeps the rest of the text byte for byte."""
    index = next((i for i, f in enumerate(deck.header) if f.key.lower() == COVER_FIELD.lower()), None)
    if cover is None:
        if index is not None:
            del deck.header[index]
        return
    value = format_cover(cover["name"], cover.get("set"), cover.get("number"))
    if index is not None:
        if parse_cover(deck.header[index].value) == parse_cover(value):
            return
        old = deck.header[index]
        deck.header[index] = HeaderField(COVER_FIELD, value, None, old.end)
        return
    deck.header.append(HeaderField(COVER_FIELD, value))


def auto_cover_line(sections, is_land, is_creature=None):
    """The DeckLine the automatic cover comes from in a list's sections ({section: [DeckLine]}):
    the first Commander card; else, over COVER_SECTIONS, the name with the most copies that
    is_land(name) says isn't a land; on a tie one is_creature(name) says is a creature, then the
    first in list order (its first line, which names the printing); else the first card of the
    list; None for an empty list."""
    commanders = sections.get("Commander") or []
    if commanders:
        return commanders[0]
    copies, first = {}, {}
    for section in COVER_SECTIONS:
        for line in sections.get(section) or []:
            if line.name not in first:
                first[line.name] = line
            copies[line.name] = copies.get(line.name, 0) + line.quantity
    best, best_key = None, None
    for name, line in first.items():          # dicts keep list order
        if is_land(name):
            continue
        key = (copies[name], bool(is_creature and is_creature(name)))
        if best is None or key > best_key:
            best, best_key = line, key
    if best is not None:
        return best
    for section in (*COVER_SECTIONS, "Sideboard"):
        if sections.get(section):
            return sections[section][0]
    return None

