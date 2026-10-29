"""Queue a home deck's missing Planned cards in one reviewed change (E5-S25).

POST /api/shopping/queue/missing (review_missing) writes nothing: for one ordinary home deck it
lists each card its Planned list is missing (pool.owned_vs_needed, on-the-way copies already
counted), less the copies already queued for that deck in any state (a row whose source is the
deck, under any of its ids, or whose "for" is its title), with the inventory revision it read.
POST /api/shopping/queue with action "add_many" (shopping_queue.save_queue_state, which checks
the revision first) saves the reviewed cards as one audited watchlist.add_many change: any
nonfoil printing, the chosen state (To buy or Long-term), the deck as source and title as "for".
The cards are worked out again inside the change; when anything differs from the review (the
deck, the pool or the queue moved on) nothing is saved and a new review is asked for.

Only a home admin (orders.edit, and home's records) may do either: User1 and members never see
the action. Token and reminder cards are never queued here: a decklist's missing cards are
playable ones, and token rows already queued don't count against them.
"""
import contextlib

from decklab.lib import buying_needs, cards, config, decks, inventory, spaces
from decklab.lib.inventory import paths

from . import guard
from .carddata import _require_cards
from .common import DATABASE_DOWN, MAX_NAME, ApiError, _keys, _log, _parse_body, _public
from .library import _find_summary, check_deck_id
from .saving import inventory_write_lock
from .settings import _web_actor, _writer
from .shopping_missing import is_token

STATES = ("ready", "long_term")
MAX_CARDS = 500
CHANGED = "The deck, the collection or the purchase queue changed since this review. Review the missing cards again."
NOT_HOME = "Only a home deck's missing cards can be queued from here."


def _authorized(data):
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    return profile


def _deck_id(value):
    if not isinstance(value, str):
        raise ApiError(400, "deck must be the deck's id")
    check_deck_id(value)
    return value


def _summary(deck_id):
    """The home deck's summary: a hidden or missing deck's 404 first, then a product, pairing or
    person's deck's 400."""
    summary = _find_summary(deck_id)
    space, kind, _ = spaces.split_deck_id(summary["id"])
    if space != spaces.HOME or kind not in decks.KINDS:
        raise ApiError(400, NOT_HOME)
    return summary


def _canonical(name):
    return cards.resolve(name) or name


def _queued_for(inv, deck_id, title):
    """{casefolded card name: copies} the queue already holds for this deck, in every state."""
    queued = {}
    for row in inv.watchlist.rows:
        item = {key: row.text(key) for key in ("name", "set", "collector_number", "source", "for")}
        if is_token(item):
            continue
        mine = bool(title) and item["for"].strip().casefold() == title.strip().casefold()
        found = paths.classify(item["source"]) if item["source"] else None
        if not mine and found is not None and found[0] == "deck":
            space, kind, slug = found[1]
            source_id = f"{kind}/{slug}" if space == paths.HOME else f"{space}/{kind}/{slug}"
            mine = inventory.resolve_deck_id(source_id, inv) == deck_id
        if mine:
            key = _canonical(item["name"]).casefold()
            queued[key] = queued.get(key, 0) + int(row.text("quantity") or 0)
    return queued


def _proposal(deck_id):
    """The review from the pinned snapshot: {ready, deck, rows, totals} or {ready: False, reason}.
    rows holds every missing card with what's queued and the copies to add (0: none)."""
    inv = inventory.current()
    if inv.stale:
        raise ApiError(409, "Current inventory is unavailable. Reload and review when it is available.")
    summary = _summary(deck_id)
    deck_id, title = summary["id"], summary["title"]
    deck = {"id": deck_id, "title": title}
    counted = buying_needs.count([summary], canonical=_canonical, public=_public, log=_log)
    if counted.phase == "no_targets":
        return {"ready": False, "deck": deck, "reason": "This deck has no Planned list to count."}
    if counted.phase == "unavailable" or counted.errors:
        reason = " ".join([counted.message or "", *counted.warnings,
                           *(error["message"] for error in counted.errors)]).strip()
        return {"ready": False, "deck": deck, "reason": reason or "The missing cards could not be counted."}
    queued = _queued_for(inv, deck_id, title)
    rows = []
    for card in counted.rows:
        if is_token({"name": card["name"]}):
            continue
        already = queued.get(card["name"].casefold(), 0)
        rows.append({"name": card["name"], "missing": card["missing"], "queued": already,
                     "copies": max(card["missing"] - already, 0)})
    rows.sort(key=lambda row: (row["copies"] == 0, row["name"].casefold()))
    adding = [row for row in rows if row["copies"]]
    return {"ready": True, "deck": deck, "rows": rows, "revision": inv.revision,
            "totals": {"cards": len(adding), "copies": sum(row["copies"] for row in adding)}}


def _values(row, deck, state):
    return {"name": row["name"], "quantity": str(row["copies"]), "state": state, "for": deck["title"],
            "source": f"magic/decks/{deck['id']}.md", "printing": "any", "set": "", "collector_number": "",
            "finish": "nonfoil"}


def review_missing(body):
    """POST /api/shopping/queue/missing {profile, deck}: the review, nothing written."""
    data = _parse_body(body)
    _keys(data, ("profile", "deck"))
    _authorized(data)
    deck_id = _deck_id(data["deck"])
    _require_cards()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            review = _proposal(deck_id)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (inventory.StateError, ValueError, OSError) as error:
        raise ApiError(400, "The missing cards could not be reviewed: " + _public(error)) from None
    if review["ready"]:
        from .shopping import _card_for
        cache = {}
        for row in review["rows"]:
            row["card"] = _card_for(row["name"], cache=cache)
        review["states"] = list(STATES)
    return review


def _reviewed(value):
    """The [(name, copies)] the viewer reviewed, each card once."""
    if not isinstance(value, list) or not value or len(value) > MAX_CARDS:
        raise ApiError(400, f"cards must list 1 to {MAX_CARDS} reviewed cards")
    seen, result = set(), []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "copies"}:
            raise ApiError(400, "Each reviewed card needs exactly its name and copies")
        name, copies = item["name"], item["copies"]
        if not isinstance(name, str) or not name or len(name) > MAX_NAME:
            raise ApiError(400, f"Give each card's name, of at most {MAX_NAME} characters")
        if isinstance(copies, bool) or not isinstance(copies, int) or not 1 <= copies <= 999:
            raise ApiError(400, "Each card's copies must be a whole number from 1 to 999")
        if name.casefold() in seen:
            raise ApiError(400, f"{name} is listed twice")
        seen.add(name.casefold())
        result.append((name, copies))
    return sorted(result, key=lambda pair: pair[0].casefold())


class _MissingQueue:
    """The reviewed cards, checked again from the snapshot the change is made on."""
    kind = "watchlist.add_many"

    def __init__(self, deck_id, state, reviewed):
        self.deck_id, self.state, self.reviewed = deck_id, state, reviewed
        self.params = {"deck": deck_id, "state": state, "cards": [list(pair) for pair in reviewed]}
        self.rows = None

    def run(self, inv):
        if inv.stale:
            raise inventory.Conflict(CHANGED)
        with inventory.pinned(inv):
            review = _proposal(self.deck_id)
        if not review["ready"]:
            raise inventory.Conflict(CHANGED)
        adding = [row for row in review["rows"] if row["copies"]]
        if sorted(((row["name"], row["copies"]) for row in adding), key=lambda pair: pair[0].casefold()) != self.reviewed:
            raise inventory.Conflict(CHANGED)
        self.rows = adding
        values = [_values(row, review["deck"], self.state) for row in adding]
        return inventory.Op("watchlist.add_many", {"rows": values, "repo": str(config.REPO)}).run(inv)


def add_many(profile, data, expect):
    """save_queue_state's add_many, after its authorization and revision-shape checks."""
    state = data["state"]
    if not isinstance(state, str) or state not in STATES:
        raise ApiError(400, "state must be ready (To buy) or long_term (Long-term)")
    deck_id = _deck_id(data["deck"])
    reviewed = _reviewed(data["cards"])
    _require_cards()
    operation = _MissingQueue(deck_id, state, reviewed)
    try:
        inv = inventory.current()
        if inv.revision != expect:
            raise ApiError(409, CHANGED)
        with inventory_write_lock():
            after, _ = inventory.apply(operation, _web_actor(profile), "Queue a deck's missing cards",
                                       expected_revision=expect)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError) as error:
        raise ApiError(400, f"The purchase queue couldn't be changed: {_public(error)}") from None
    rows = operation.rows or []
    return {"saved": True, "action": "add_many", "revision": after.revision, "state": state,
            "deck": deck_id, "cards": len(rows), "copies": sum(row["copies"] for row in rows)}
