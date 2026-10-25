"""POST /api/deck/cover (save_cover): choosing the card whose art stands for a deck in the library;
GET /api/deck/cards (cover_cards): what the picture picker (web/cover.js) shows, without the rest of
the deck page.

The cover is the deck text's optional "Cover card" header line (lib/decks/cover.py), a field Deck
Lab otherwise keeps as written; this route is the only thing that rewrites it. A save changes that
line alone (decks.set_cover, then render_deck_file, which copies everything else byte for byte) and
is one inventory operation, deck.save, as the editor's saves are (saving.apply_op): one change set
in the audit trail and one revision in the deck's history, by the profile asking. Nothing is
committed to git.
"""
import re
import urllib.parse

from decklab.lib import cards, decks, inventory

from . import guard
from .carddata import _require_cards
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import NUMBER_RE, SET_RE, ApiError, _keys, _parse_body, _public
from .card_lookup import _lines_json
from .library import _deck_sections, auto_cover, deck_cover
from .saving import _deck_refused, apply_op
from .settings import _writer

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMG_RE = re.compile(r"^/img/([^/]+)/([^/]+)/normal$")
PICKER_SECTIONS = ("Commander", "Companion", "Deck", "Sideboard")
MAX_EXPECT = 10 ** 9


def _expected(stored, expect):
    """True when expect names the stored deck: its revision (a whole number; 0 means "unknown",
    which the files backend's decks always are) or the sha256 of its text. ApiError 400 for an
    expect that's neither."""
    if isinstance(expect, bool) or not isinstance(expect, (int, str)):
        raise ApiError(400, "expect must be the deck's revision (a whole number) or the sha256 of its text")
    if isinstance(expect, int):
        if not 0 <= expect <= MAX_EXPECT:
            raise ApiError(400, "expect must be the deck's revision (a whole number from 0)")
        return expect == stored.revision
    if not _SHA_RE.fullmatch(expect):
        raise ApiError(400, "expect must be the deck's revision (a whole number) or the sha256 of its text")
    return expect == stored.sha256


def _cover(value):
    """The request's cover as {"name": exact Scryfall name, "set", "number"} (set and number
    None, or both given and a printing of that card), or None (automatic). ApiError 400 otherwise."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError(400, "cover must be {name, set?, number?} or null")
    _keys(value, ("name",), ("set", "number"))
    name, set_code, number = value["name"], value.get("set"), value.get("number")
    if not isinstance(name, str) or not name.strip() or len(name) > decks.cover.MAX_COVER_NAME:
        raise ApiError(400, "cover.name must be a card's name")
    exact = cards.resolve(name.strip())
    if exact is None:
        raise ApiError(400, f"{name.strip()} isn't a Scryfall card name")
    if set_code in (None, "") and number in (None, ""):
        return {"name": exact, "set": None, "number": None}
    if not (isinstance(set_code, str) and SET_RE.fullmatch(set_code.lower())
            and isinstance(number, str) and NUMBER_RE.fullmatch(number)):
        raise ApiError(400, "A cover's printing needs both its set code and its collector number")
    set_code = set_code.lower()
    printed = cards.printing_card(set_code, number) if cards.printing(set_code, number) else None
    if printed is None or printed["name"] != exact:
        raise ApiError(400, f"{set_code.upper()} {number} isn't a printing of {exact}")
    return {"name": exact, "set": set_code, "number": number}


def save_cover(body):
    """POST /api/deck/cover {"profile", "id", "expect", "cover": {"name", "set"?, "number"?} | null}.

    Sets the deck's Cover card line to that card (a printing when set and number are given), or
    removes it (null: back to the automatic cover). The deck must be one Deck Lab can save (a deck
    text at home or in a person's space; 400 for a product deck or pairing) and the profile may
    change it as it may save its text (guard deck.edit, 403 otherwise). expect is the revision the
    page read (the library's and deck page's summary "revision"), or the sha256 of the text:
    409 with "conflict" (commits._conflict) when the deck changed since, 404 when there's no such
    deck. The cover's name must be a Scryfall card (its exact name is written) and its printing one
    of that card (400 otherwise).

    Returns {"saved": whether the text changed, "id", "title", "cover": the deck's cover now
    (library.deck_cover), "revision": the text's revision now (0 when unknown)}."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "expect"), ("cover",))
    kind, slug, path = _deck_file(data["id"])
    deck_id = data["id"]
    _require_cards()
    stored = _stored(deck_id, viewer=profile)
    deck = _parse_file(stored.data, kind, slug, path, deck_id)
    guard.require(profile, "deck.edit", deck)
    if not _expected(stored, data["expect"]):
        raise _conflict(deck_id, deck.title, viewer=profile)
    chosen = _cover(data.get("cover"))
    try:
        decks.set_cover(deck, chosen)
        out = decks.render_deck_file(deck)
    except (decks.DeckFileError, ValueError) as e:
        raise ApiError(400, f"The cover card can't be written: {_public(e)}") from None
    revision = stored.revision
    if out != stored.text:
        what = (f"choose the cover card of {deck.title}: {decks.format_cover(chosen['name'], chosen['set'], chosen['number'])}"
                if chosen else f"set the cover card of {deck.title} back to automatic")
        op = inventory.Op("deck.save", {"deck_id": deck_id, "text": out, "base_sha256": stored.sha256})
        after, _ = apply_op(op, profile, what, _deck_refused(deck_id, deck.title, profile))
        held = after.deck(deck_id)
        revision = held.revision if held is not None else 0
    summary = {"id": deck_id, "cover_card": deck.get_field(decks.COVER_FIELD)}
    try:
        sections = decks.parse_deck(out.encode("utf-8"), slug, kind, path, deck.space).target
    except decks.DeckFileError:
        sections = deck.target
    return {"saved": out != stored.text, "id": deck_id, "title": deck.title,
            "cover": deck_cover(summary, sections), "revision": revision}


def _shown(card):
    """(set, number) of the printing a card's JSON shows (its "img" address), or (None, None)."""
    m = _IMG_RE.match(card.get("img") or "")
    return (m.group(1), urllib.parse.unquote(m.group(2))) if m else (None, None)


def cover_cards(deck_id=None):
    """GET /api/deck/cards?id=<deck id>: the picture picker's cards, a light read of the deck's
    Planned list (none of the deck page's stats, owned-vs-needed table, tokens or matchups).

    Returns {"summary": {"id", "title", "revision", "cover"} (as GET /api/deck's summary has
    them), "auto": the automatic cover (library.auto_cover, whether or not the deck has a Cover
    card line; None for a list with no Scryfall card), "cards": [{"name": exact Scryfall name,
    "set", "number": the printing the deck page shows for it (the list's own when that is the
    card's, else the one shown instead), "card": the card's data as GET /api/deck's lines have
    it}]}: each card of the Commander, Companion, Deck and Sideboard sections once, in list
    order (a name that isn't a Scryfall card left out). Errors as GET /api/deck's: 400 for a bad
    id, 404 for a deck that doesn't exist, 500 for one that can't be read, 503 until the card
    data is ready. Anyone may read it, as anyone may read a deck's list."""
    summary, sections = _deck_sections(deck_id, "target")
    present = {name: sections[name] for name in PICKER_SECTIONS if sections.get(name)}
    lines = _lines_json(present, [])
    seen, out = set(), []
    for section in PICKER_SECTIONS:
        for line in lines.get(section) or []:
            card = line["card"]
            if card is None or card["name"] in seen:
                continue
            seen.add(card["name"])
            set_code, number = _shown(card)
            out.append({"name": card["name"], "set": set_code, "number": number, "card": card})
    return {"summary": {key: summary.get(key) for key in ("id", "title", "revision", "cover")},
            "auto": auto_cover(sections), "cards": out}
