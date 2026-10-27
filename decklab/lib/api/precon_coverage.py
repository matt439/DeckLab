"""The Collection page's "Precons we could build" (E1-S24): MTGJSON's published
precons ranked by how much of each one the space's free pool covers
(lib/precon_coverage.py), one precon's missing cards with their estimated AUD
cost, and a new idea deck started from its list. Imported when first needed,
by feature_routes.dispatch.

    GET  /api/precons/coverage?space=<id>&format=<f>&type=<t>&limit=<n>   coverage_view(): the ranking
    GET  /api/precons/coverage/deck?file=<f>&space=<id>                    coverage_deck(): one precon's missing cards
    POST /api/precons/start                                                start_deck(body): a new idea deck from its list

Both reads are the space's inventory's (guard.require_sees_inventory: the
Collection page's 403, "That collection isn't public.", for a space the
viewer may not see or that doesn't exist). Free copies are pool.free_copies':
owned or on the way, less what built decks and intact products hold; no
answer names the decks holding them. The missing cards are priced as a deck's
owned-vs-needed table prices them (pool.compare: the cheapest non-foil paper
printing's USD price at the ECB rate, with the rate and dates).

Starting a deck is POST /api/decks's path (saving.plan_new_deck and
write_new_deck: deck.create on the space, a free name, a list every new deck
may have), with status idea and the precon's list as Add a precon would make
it (api/precons._build); nothing goes into the collection.
"""
import csv

from decklab.lib import cards, decks, pool, precon_coverage, precons, spaces

from . import guard, saving
from . import precons as add
from .carddata import _require_cards
from .collection import _integer, space_param
from .common import ApiError, _keys, _parse_body, _public
from .settings import _writer

LIMIT = 60
MAX_LIMIT = 200


def _pool(space):
    """The space's pool, or 409 as the Collection page answers an unreadable one."""
    try:
        return pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
    except (ValueError, OSError, csv.Error) as error:
        if space == spaces.HOME and not guard.sees_home_records():
            raise ApiError(409, "The collection couldn't be read.") from None
        raise ApiError(409, f"The collection couldn't be read: {_public(error)}") from None


def _may_start(space):
    profile = guard.viewer()
    return guard.sees_deck({"space": space}, profile) and \
        guard.allowed(profile, "deck.create", {"space": space, "player": None})


def coverage_view(space=None, format=None, type=None, limit=None):
    """GET /api/precons/coverage: {"space", "date" (MTGJSON's build), "decks" (the best covered
    first, at most limit: precon_coverage.rank's), "total" (how many matched), "types" (the deck
    types of that format, for the filter), "status" (rank's: how many lists are read, whether
    more are being read, the last problem), "may_start" (whether this viewer may start a deck
    in the space)}. format: commander or casual (blank: both); type: one of MTGJSON's paper
    deck types. 403 as the Collection page for a space the viewer may not see; 502 when
    MTGJSON's list can't be had and nothing is cached."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    kind = format or None
    if kind not in (None, *precon_coverage.FORMATS):
        raise ApiError(400, "format must be commander or casual")
    deck_type = type or None
    if deck_type is not None and deck_type not in precons.TYPES:
        raise ApiError(400, "type must be one of MTGJSON's paper deck types")
    limit = _integer(limit, "limit", LIMIT, MAX_LIMIT)
    _require_cards()
    p = _pool(space)
    try:
        ranked = precon_coverage.rank(p, kind, deck_type)
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    return {"space": space, "date": ranked["date"], "decks": ranked["decks"][:limit],
            "total": len(ranked["decks"]), "types": ranked["types"], "status": ranked["status"],
            "may_start": _may_start(space)}


def _sections(read, kind):
    """{section: [DeckLine]} of a precon's readable lines (a casual deck's commander is in its Deck)."""
    sections = {}
    for line in read["lines"]:
        section = line["section"] if kind == "commander" or line["section"] != "Commander" else "Deck"
        sections.setdefault(section, []).append(decks.DeckLine(line["count"], line["name"]))
    return sections


def _card(name):
    from .card_lookup import _card_json, _shown_printing
    exact = cards.resolve(name)
    card = cards.card(exact) if exact else None
    return _card_json(card, _shown_printing(card)) if card else None


def coverage_deck(file=None, space=None):
    """GET /api/precons/coverage/deck: {"deck" (its /api/precons entry), "kind", "title" (a
    suggested deck title), "cards", "covered", "share" (as the ranking counts them), "missing"
    ([{"name", "need", "free", "missing", "aud_each", "aud_missing", "priced_printing", "card"}],
    the dearest first, unpriced last), "totals" ({"missing", "aud_missing", "unpriced"}),
    "rate", "rate_date", "price_date", "price_error" (pool.compare's), "problems" (cards of
    MTGJSON's list that can't be read), "may_start"}. 403 as coverage_view; 404 for a deck
    MTGJSON doesn't list; 502 when its list can't be had."""
    space = space_param(space)
    guard.require_sees_inventory(space)
    entry = add._entry(file)
    _require_cards()
    try:
        read = precons.cards_of(precons.deck(entry["file"]))
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    except LookupError:
        raise ApiError(404, f"MTGJSON lists no paper deck called {entry['file']}") from None
    has_commander = any(line["section"] == "Commander" for line in read["lines"])
    kind = "commander" if entry["type"] == "Commander Deck" and has_commander else "casual"
    sections = _sections(read, kind)
    result = pool.compare(sections, _pool(space), prices=True)
    total = sum(r["need"] for r in result["rows"])
    covered = sum(min(r["need"], r["available"]) for r in result["rows"])
    missing = [{"name": r["name"], "need": r["need"], "free": r["available"], "missing": r["missing"],
                "aud_each": r["aud_each"], "aud_missing": r["aud_missing"], "priced_printing": r["priced_printing"],
                "card": _card(r["name"])} for r in result["rows"] if r["missing"]]
    missing.sort(key=lambda r: (r["aud_missing"] is None, -(r["aud_missing"] or 0), r["name"]))
    commanders = [line.name for line in sections.get("Commander", [])]
    title = f"{' & '.join(add._short(n) for n in commanders)}: {entry['name']}" if commanders else entry["name"]
    return {"deck": entry, "kind": kind, "title": title[:saving.MAX_TITLE], "cards": total, "covered": covered,
            "share": round(covered / total, 4) if total else None, "missing": missing,
            "totals": {k: result["totals"][k] for k in ("missing", "aud_missing", "unpriced")},
            "rate": result["rate"], "rate_date": result["rate_date"], "price_date": result["price_date"],
            "price_error": result["price_error"], "problems": read["problems"], "may_start": _may_start(space)}


def _notes(entry, author):
    released = f", released {entry['released']}" if entry["released"] else ""
    source = entry["source"]
    return (f"Started in Deck Lab on {add._added_on()} by {author} from the {entry['name']} precon's list "
            f"({entry['set_name'] or entry['code'].upper()}, {entry['type']}{released}), to build from the "
            "collection; none of its cards were added to the collection. The list is MTGJSON's"
            + ((f", from Wizards' published list: {source}" if precons.from_wizards(source) else f", from {source}")
               if source else "") + ".")


def start_deck(body):
    """POST /api/precons/start {"profile", "file", "title", "space"?}: a new idea deck in the space
    with the precon's list (as Add a precon makes it: its own printings, plain basics as "20
    Forest"), through POST /api/decks's path (deck.create: 403; a taken name: 409 with
    "conflict"; a list a new deck can't have: 400 with "problems"). Returns POST /api/decks's
    answer. Nothing goes into the collection."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "file", "title"), ("space",))
    space = space_param(data.get("space"))
    # The rules plan_new_deck asks again, first: nothing of the space is read for someone who can't.
    saving.require_sees_space(space, profile)
    guard.require(profile, "deck.create", {"space": space, "player": None})
    built = add._build(add._entry(data["file"]), space)
    name = built["entry"]["name"]
    if built["problems"]:
        raise ApiError(400, f"A deck can't be started from {name} yet: Deck Lab can't match "
                            f"{len(built['problems'])} of its cards to Scryfall's data.", problems=built["problems"])
    if built["deck_problems"]:
        raise ApiError(400, f"A deck can't be started from {name}: its list can't be made into a deck "
                            f"({built['deck_problems'][0]['message']}).", problems=built["deck_problems"])
    request = {"title": data["title"], "kind": built["kind"], "space": space, "fields": {"status": "idea"},
               "lists": {"target": built["sections"]}}
    plan = saving.plan_new_deck(request, profile, notes=_notes(built["entry"], profile["name"]))
    return saving.write_new_deck(plan)
