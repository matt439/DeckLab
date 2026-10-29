"""Stand-ins for missing cards (E2-S07): GET /api/deck/swaps (suggest_swaps, the deck page's) and
POST /api/deck/swaps (suggest_draft_swaps, the editor's, for the Play-now list being edited); and
free pool replacements for a card the list holds (E3-S25): GET /api/deck/replacements
(suggest_replacements, for a card Forge marks drawn and never cast). None writes anything: a
pick changes the editor's draft, which POST /api/deck/save saves.

What fits, how candidates are ranked and what a swap's note says are lib/decks/swaps.py's.
The answers count the deck's space's inventory, so only a viewer who may see it gets them
(guard.require_sees_inventory: 403 "That collection isn't public."), after the deck itself
(a deck the viewer may not see is the missing deck's 404). They name no other deck: a
candidate's copies are counted free, never by who holds the rest.
"""
from decklab.lib import cards, decks, pool, spaces
from decklab.lib.decks import swaps

from . import drafts, guard
from .card_lookup import _card_json, _default_printing, _resolve, _shown_printing
from .carddata import _require_cards
from .common import MAX_QTY, ApiError, _keys, _parse_body, _public, _scrub, _unique
from .library import _find_summary, _load_pool, check_deck_id
from .settings import _writer

VERSIONS = ("target", "owned")
MAX_LINES = 500                 # lines in one section of a sent list (drafts.MAX_LINES)
NOT_A_DECK = "Only a deck has a Play-now list: save this one as a new deck first."


def _deck(deck_id):
    """(summary, parsed deck) of a deck id the viewer may see and whose inventory it may see:
    404 for a missing or hidden deck first, then 400 for a product or pairing, then 403."""
    if deck_id is None:
        raise ApiError(400, "id is required: the deck's id")
    check_deck_id(deck_id)
    _require_cards()
    summary = _find_summary(deck_id)
    space, kind, slug = spaces.split_deck_id(summary["id"])
    if kind not in decks.KINDS:
        raise ApiError(400, NOT_A_DECK)
    guard.require_sees_inventory(space)
    try:
        deck = decks.read_deck_file(decks.find_deck_file(kind, slug, space), space=space)
    except (decks.DeckNotFound, FileNotFoundError):
        raise guard.no_deck(deck_id) from None
    except (decks.DeckFileError, OSError, ValueError) as e:
        raise ApiError(500, f"{summary['id']} can't be read: {_public(e)}") from None
    return summary, deck


def suggest_swaps(deck_id=None, version=None, card=None):
    """GET /api/deck/swaps?id=<deck id>&version=target|owned[&card=<name>]: owned cards that could
    stand in for each card missing from that saved list, counted against the Play-now list they'd
    go into (the saved one, or the Planned list while there's none: what it starts as). See
    _suggest for the answer."""
    summary, deck = _deck(deck_id)          # a hidden deck's 404 comes before any 400
    version = version or "target"
    if version not in VERSIONS:
        raise ApiError(400, f"version must be one of: {', '.join(VERSIONS)}")
    source = deck.target if version == "target" else deck.owned
    if not source:
        raise ApiError(404, f"{deck.title} has no {version} list")
    return _suggest(summary["id"], deck, version, source, deck.owned or deck.target, card)


def _read_list(raw):
    """{section: [DeckLine]} of a list the editor sent (its sendList format: {section: [{qty, name,
    ...}]}); only names and copies count here, so printings aren't read. Names are made exact;
    one that isn't a card is skipped (the editor's check says so)."""
    if not isinstance(raw, dict):
        raise ApiError(400, "list must be a JSON object: {section: [card lines]}")
    out = {}
    for section, lines in raw.items():
        if section not in decks.SECTIONS:
            raise ApiError(400, f"Unknown section {section!r}: use {', '.join(decks.SECTIONS)}")
        if not isinstance(lines, list) or len(lines) > MAX_LINES:
            raise ApiError(400, f"list.{section} must be a list of at most {MAX_LINES} card lines")
        kept = []
        for line in lines:
            name, qty = (line.get("name"), line.get("qty")) if isinstance(line, dict) else (None, None)
            if not isinstance(name, str) or isinstance(qty, bool) or not isinstance(qty, int) \
                    or not 1 <= qty <= MAX_QTY or len(name) > 200:
                raise ApiError(400, f"Each line of list.{section} needs a name and 1 to {MAX_QTY} copies")
            exact = name.strip() if decks.is_basic_land(name.strip()) else _resolve(name)
            if exact is not None:
                kept.append(decks.DeckLine(qty, exact))
        if kept:
            out[section] = kept
    return out


def suggest_draft_swaps(body):
    """POST /api/deck/swaps {"profile", "id", "list", "card"?}: suggest_swaps for the Play-now list
    being edited (list, as the editor sends it), which is both the list whose missing cards get
    stand-ins and the one they'd go into. A dry run, like POST /api/deck/check: nothing is saved
    and anyone may ask, but only of a deck and inventory they may see."""
    data = _parse_body(body)
    _writer(data)
    _keys(data, ("profile", "id", "list"), ("card",))
    summary, deck = _deck(data["id"])
    sent = _read_list(data["list"])
    return _suggest(summary["id"], deck, "owned", sent, sent, data.get("card"))


def _swappable(source):
    """{name: section} of the cards of source that may be swapped: in the Deck, else the Sideboard
    (never Commander or Companion)."""
    def exact(line):        # as pool.compare names its rows
        return cards.resolve(line.name) or line.name

    out = {}
    for section in reversed(swaps.SWAPPABLE):
        for line in source.get(section, ()):
            out[exact(line)] = section
    for section in ("Commander", "Companion"):
        for line in source.get(section, ()):
            out.pop(exact(line), None)
    return out


def _here(p, free):
    """Card name -> of the free copies (pool.free_copies), those in the space now: not on the way."""
    return {name: max(qty - sum(n for _, n in p.on_the_way.get(name, ())), 0) for name, qty in free.items()}


def _suggest(deck_id, deck, version, source, destination, wanted=None):
    """The answer: {"deck_id", "version", "kind", "colours" (the colours a stand-in may have,
    swaps.deck_colours), "cards": [{"name", "section", "missing", "aud_each", "card", "type",
    "colours", "mv", "in_list" (copies of it in the list a stand-in goes into), "list_missing"
    (copies the list a stand-in goes into is short of it: 0 when that list already covers it, with
    owned copies or something else, so the editor would have nothing to swap), "candidates":
    [{"name", "card", "default" (the printing a new line gets, the space's most-owned), "free"
    (copies free for this list: owned and on the way, less other built decks' and intact
    products' and the list's own), "here" (of those, copies not on the way), "max_qty", "note"
    (swaps.swap_note), "basic", "aud"}], "more" (candidates not listed)}], "rate", "rate_date",
    "price_date", "warnings"}.

    A basic land candidate has free and here None (plain basics aren't counted) and max_qty
    the copies missing. Cards come with no candidate first, then by their best candidate's
    severity (worst first), then by A$ missing (dearest first): the order to buy them in. wanted
    (a name) keeps only that card's entry: 400 when it isn't missing."""
    warnings = []
    p = _space_pool(deck.space, warnings)
    mine = pool.self_ids(deck_id)
    result = pool.compare(source, p, mine)
    card_of = cards.card
    kind = deck.kind
    colours = _colours(deck, source)
    in_list, free, here = _free_for(p, mine, destination)
    counts = drafts._visible_counts(deck.space)
    sections = _swappable(source)
    rows = [r for r in result["rows"] if r["missing"] > 0 and r["name"] in sections and card_of(r["name"])]
    if destination is source:
        short = {r["name"]: r["missing"] for r in rows}
    else:
        short = {r["name"]: r["missing"] for r in pool.compare(destination, p, mine, prices=False)["rows"]}
    if wanted is not None:
        name = wanted if isinstance(wanted, str) else None
        exact = name and (_resolve(name) or name)
        rows = [r for r in rows if r["name"] == exact]
        if not rows:
            raise ApiError(400, f"{str(wanted)[:100]} isn't missing from the list")
    spares = [(name, spare, card_of(name)) for name, spare in free.items() if spare > 0]
    out = []
    for row in rows:
        missing_card = card_of(row["name"])
        found = swaps.ranked(missing_card, spares, colours, kind, row["missing"], in_list, here)
        listed = [_candidate(missing_card, name, spare, here.get(name, 0), take, counts, colours)
                  for _, name, spare, take in found[:swaps.MAX_CANDIDATES]]
        listed += [_basic(missing_card, name, row["missing"], colours)
                   for name in swaps.basics_for(missing_card, colours, kind)]
        out.append({"name": row["name"], "section": sections[row["name"]], "missing": row["missing"],
                    "aud_each": row["aud_each"], "card": _card_json(missing_card, _shown_printing(missing_card)),
                    "type": swaps.primary_type(missing_card), "colours": sorted(swaps.colours_of(missing_card),
                                                                                  key=swaps.COLOURS.index),
                    "mv": missing_card.get("cmc") or 0, "in_list": in_list.get(row["name"], 0),
                    "list_missing": max(short.get(row["name"], 0), 0),
                    "candidates": listed, "more": max(len(found) - swaps.MAX_CANDIDATES, 0)})
    out.sort(key=lambda c: (bool(c["candidates"]),
                            -min((x["note"]["severity"] for x in c["candidates"]), default=0),
                            -(c["aud_each"] or 0) * c["missing"], c["name"].casefold()))
    return {"deck_id": deck_id, "version": version, "kind": kind,
            "colours": [c for c in swaps.COLOURS if c in colours], "cards": out,
            "rate": result["rate"], "rate_date": result["rate_date"], "price_date": result["price_date"],
            "warnings": _unique(_scrub(warnings))}


def _space_pool(space, warnings):
    """The deck's space's Pool (500 when its inventory can't be read)."""
    p = _load_pool(warnings, space)
    if p is None:
        raise ApiError(500, warnings[0] if warnings else "The collection couldn't be read.")
    return p


def _colours(deck, source):
    """swaps.deck_colours for the deck: a Commander deck's are its commander's (the Planned list's, else
    source's), a casual deck's its Planned list's non-land cards'."""
    planned = deck.target or {}
    wanted = source if deck.kind == "commander" and not planned.get("Commander") else planned
    return swaps.deck_colours(wanted, deck.kind, cards.card)


def _free_for(p, mine, destination):
    """(in_list, free, here) for a list candidates would go into: in_list its copies of each card (basic
    lands too), free pool.free_copies less those copies (the list's own use the pool too), here of those
    the copies not on the way."""
    in_list = pool._count_sections(destination, "list", {})
    for line in (l for lines in destination.values() for l in lines if decks.is_basic_land(l.name)):
        in_list[line.name] += line.quantity
    free = pool.free_copies(p, mine)
    here = _here(p, free)
    for name, qty in in_list.items():
        if name in free:
            here[name] = max(here.get(name, 0) - qty, 0)
            free[name] = max(free[name] - qty, 0)
    return in_list, free, here


def suggest_replacements(deck_id=None, version=None, card=None):
    """GET /api/deck/replacements?id=<deck id>&version=target|owned&card=<name>: free pool cards that
    could replace a card the saved list plays in its Deck section (E3-S25: one Forge marks drawn and
    never cast), ranked as stand-ins are (swaps.ranked: the same type, a shared colour, castable in the
    deck, mana value within 1), at most swaps.MAX_REPLACEMENTS: {"deck_id", "version", "kind", "colours",
    "card": {"name", "qty" (copies in the list), "card", "type", "colours", "mv"}, "candidates":
    [{"name", "card", "default", "free", "here", "max_qty" (copies it could replace), "note", "basic"
    (always False: plain basics aren't pool cards), "aud"}], "more", "rate", "rate_date", "price_date"
    (as GET /api/deck/swaps: the AUD estimates' USD->AUD rate, its ECB date and the date Scryfall's prices
    were pulled, None when they can't be read), "warnings"}.

    Free is owned and on the way, less what other built decks and intact products hold and the list's
    own copies, never naming who holds the rest. As GET /api/deck/swaps it reads the deck's space's
    inventory, so a hidden deck is missing (404), then a product or pairing is a 400, then a viewer who
    may not see that inventory gets 403 "That collection isn't public." A card the Deck section doesn't
    play (a commander, a sideboard card, a basic land, one not in the list) is a 400."""
    summary, deck = _deck(deck_id)          # a hidden deck's 404 comes before any 400
    version = version or "target"
    if version not in VERSIONS:
        raise ApiError(400, f"version must be one of: {', '.join(VERSIONS)}")
    source = deck.target if version == "target" else deck.owned
    if not source:
        raise ApiError(404, f"{deck.title} has no {version} list")
    exact = _resolve(card) if isinstance(card, str) and card.strip() and len(card) <= 200 else None
    if exact is None:
        raise ApiError(400, "card is required: the name of a card in the list's Deck section")
    qty = sum(line.quantity for line in source.get("Deck", ())
              if not decks.is_basic_land(line.name) and (cards.resolve(line.name) or line.name) == exact)
    slot = cards.card(exact)
    if not qty or slot is None:
        raise ApiError(400, f"{exact} isn't in the Deck section of the {version} list")
    warnings = []
    p = _space_pool(deck.space, warnings)
    mine = pool.self_ids(summary["id"])
    colours = _colours(deck, source)
    in_list, free, here = _free_for(p, mine, source)
    spares = [(name, spare, cards.card(name)) for name, spare in free.items() if spare > 0]
    found = swaps.ranked(slot, spares, colours, deck.kind, qty, in_list, here)
    counts = drafts._visible_counts(deck.space)
    listed = [_candidate(slot, name, spare, here.get(name, 0), take, counts, colours)
              for _, name, spare, take in found[:swaps.MAX_REPLACEMENTS]]
    stamp = pool.compare({}, p, mine)       # only its price stamp: the rate and dates, checked as the tables'
    return {"deck_id": summary["id"], "version": version, "kind": deck.kind,
            "colours": [c for c in swaps.COLOURS if c in colours],
            "card": {"name": exact, "qty": qty, "card": _card_json(slot, _shown_printing(slot)),
                     "type": swaps.primary_type(slot), "colours": sorted(swaps.colours_of(slot),
                                                                         key=swaps.COLOURS.index),
                     "mv": slot.get("cmc") or 0},
            "candidates": listed, "more": max(len(found) - swaps.MAX_REPLACEMENTS, 0),
            "rate": stamp["rate"], "rate_date": stamp["rate_date"], "price_date": stamp["price_date"],
            "warnings": _unique(_scrub(warnings))}


def _candidate(missing_card, name, spare, here, take, counts, colours):
    card = cards.card(name)
    chosen = _default_printing(name, counts)
    printing = cards.printing(chosen["set"], chosen["number"]) if chosen else None
    price = cards.price_aud(name)
    return {"name": name, "card": _card_json(card, printing or _shown_printing(card)), "default": chosen,
            "free": spare, "here": here, "max_qty": take, "note": swaps.swap_note(missing_card, card, colours),
            "basic": False, "aud": price.aud if price else None}


def _basic(missing_card, name, missing, colours):
    card = cards.card(name)
    return {"name": name, "card": _card_json(card, _shown_printing(card)) if card else None, "default": None,
            "free": None, "here": None, "max_qty": missing, "note": swaps.basic_note(missing_card, name, colours),
            "basic": True, "aud": None}


def view_swaps(deck_file):
    """deck_view's "swaps": the swaps a deck's saved Play-now list makes (swaps.derive_swaps),
    each name with its card ({"name", "qty", "card"}), or None for a deck with no Play-now list.
    Only the lists and the Substitutes prose: anyone who may see the deck sees these."""
    if deck_file is None or not deck_file.owned:
        return None

    def card_json(name):
        card = cards.card(name)
        return _card_json(card, _shown_printing(card)) if card else None

    derived = swaps.derive_swaps(deck_file.target, deck_file.owned, drafts.prose_of(deck_file.text)["substitutes"],
                                 lambda name: cards.resolve(name) or name)
    for swap in derived["swaps"]:
        swap["card"] = card_json(swap["for"])
        for using in swap["using"]:
            using["card"] = card_json(using["name"])
    for extra in derived["unpaired"]:
        extra["card"] = card_json(extra["name"])
    return derived
