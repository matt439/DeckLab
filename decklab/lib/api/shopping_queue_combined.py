"""Queue these (E5-S28): put the combined shortfall of decks built together on the purchase queue
in one reviewed change.

POST /api/shopping/queue/combined (review_combined) writes nothing: for 2 to 12 chosen home decks it
works out what to buy to build them all at once (shopping_combined's count: each free copy counted
once), then, for each card, takes off the copies already queued for any chosen deck in any state (a
row whose source is one of them, under any of its ids, whose "for" is one's title, or whose "for" is
a decks-together label naming one), with the inventory revision it read.
POST /api/shopping/queue with action "add_combined" (shopping_queue.save_queue_state, which checks
the revision first) saves the reviewed cards as one audited watchlist.add_many change: any nonfoil
printing, the chosen state (To buy or Long-term), "for" naming the decks (their titles, sorted, joined
by " + ") and no source, since a row names one source and these copies are for several decks; the
notes name the deck ids. A card whose identical request is already queued (any nonfoil printing,
the same "for") raises that row instead, which keeps its own state: the review names it as "joins".
The cards are worked out again inside the change; when anything differs from the review nothing is
saved and a new review is asked for.

Only a home admin (orders.edit, and home's records) may do either, as for one deck's Queue missing
cards… (shopping_queue_missing.py). Token and reminder cards are never queued here.
"""
import contextlib

from decklab.lib import config, inventory
from decklab.lib.inventory import paths

from . import shopping_combined
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body, _public
from .saving import inventory_write_lock
from .settings import _web_actor
from .shopping_missing import is_token
from .shopping_queue_missing import SEPARATOR, STATES, _authorized, _canonical, _reviewed, names_title

CHANGED = "The decks, the collection or the purchase queue changed since this review. Review what to buy again."


def label(titles):
    """The "for" of a decks-together row: the chosen decks' titles, sorted, joined by " + "."""
    return SEPARATOR.join(sorted(titles, key=lambda title: (title.casefold(), title)))


def _ids(value):
    if (not isinstance(value, list) or not all(isinstance(item, str) and "," not in item for item in value)):
        raise ApiError(400, f"decks must list {shopping_combined.MIN_DECKS} to {shopping_combined.MAX_DECKS} deck ids")
    return shopping_combined._chosen(",".join(value))


def _queued_for(inv, chosen):
    """{casefolded card name: copies} the queue already holds for any chosen deck, in every state.
    Each row counts once, however many chosen decks it names."""
    ids = {deck["id"] for deck in chosen}
    queued = {}
    for row in inv.watchlist.rows:
        item = {key: row.text(key) for key in ("name", "set", "collector_number", "source", "for")}
        if is_token(item):
            continue
        mine = any(names_title(item["for"], deck["title"]) for deck in chosen)
        found = paths.classify(item["source"]) if item["source"] and not mine else None
        if found is not None and found[0] == "deck":
            space, kind, slug = found[1]
            source_id = f"{kind}/{slug}" if space == paths.HOME else f"{space}/{kind}/{slug}"
            mine = inventory.resolve_deck_id(source_id, inv) in ids
        if mine:
            key = _canonical(item["name"]).casefold()
            queued[key] = queued.get(key, 0) + int(row.text("quantity") or 0)
    return queued


def _joins(inv, for_label):
    joins = {}
    for row in inv.watchlist.rows:
        if (row.text("printing"), row.text("set"), row.text("collector_number"), row.text("finish"),
                row.text("for")) == ("any", "", "", "nonfoil", for_label):
            joins[row.text("name")] = row.text("state")
    return joins


def _reason(answer):
    parts = [error.get("title", "") + (": " if error.get("title") else "") + error["message"]
             for error in answer.get("errors", [])]
    return " ".join([*parts, *answer.get("warnings", [])]).strip() or "These decks could not be counted together."


def _proposal(ids):
    """The review from the pinned snapshot: {ready, decks, for, rows, totals, revision} or
    {ready: False, decks, reason}."""
    inv = inventory.current()
    if inv.stale:
        raise ApiError(409, "Current inventory is unavailable. Reload and review when it is available.")
    answer = shopping_combined._combined(ids)
    chosen = [{"id": deck["id"], "title": deck["title"]} for deck in answer["decks"]]
    if not answer["ready"]:
        return {"ready": False, "decks": chosen, "reason": _reason(answer)}
    for_label = label([deck["title"] for deck in chosen])
    queued = _queued_for(inv, chosen)
    joins = _joins(inv, for_label)
    rows = []
    for card in answer["rows"]:
        if is_token({"name": card["name"]}):
            continue
        already = queued.get(card["name"].casefold(), 0)
        copies = max(card["missing"] - already, 0)
        rows.append({"name": card["name"], "missing": card["missing"], "queued": already, "copies": copies,
                     "joins": (joins.get(card["name"]) or None) if copies else None,
                     "decks": [deck["title"] for deck in card["decks"]]})
    rows.sort(key=lambda row: (row["copies"] == 0, row["name"].casefold()))
    adding = [row for row in rows if row["copies"]]
    return {"ready": True, "decks": chosen, "for": for_label, "rows": rows, "revision": inv.revision,
            "totals": {"cards": len(adding), "copies": sum(row["copies"] for row in adding)}}


def _values(row, review, state):
    ids = ", ".join(deck["id"] for deck in review["decks"])
    return {"name": row["name"], "quantity": str(row["copies"]), "state": state, "for": review["for"],
            "source": "", "printing": "any", "set": "", "collector_number": "", "finish": "nonfoil",
            "notes": f"Decks built together: {ids}"}


def review_combined(body):
    """POST /api/shopping/queue/combined {profile, decks}: the review, nothing written."""
    data = _parse_body(body)
    _keys(data, ("profile", "decks"))
    _authorized(data)
    ids = _ids(data["decks"])
    _require_cards()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            review = _proposal(ids)
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except (inventory.StateError, ValueError, OSError) as error:
        raise ApiError(400, "What to buy could not be reviewed: " + _public(error)) from None
    if review["ready"]:
        from .shopping import _card_for
        cache = {}
        for row in review["rows"]:
            row["card"] = _card_for(row["name"], cache=cache)
        review["states"] = list(STATES)
    return review


class _CombinedQueue:
    """The reviewed cards, checked again from the snapshot the change is made on."""
    kind = "watchlist.add_many"

    def __init__(self, ids, state, reviewed):
        self.ids, self.state, self.reviewed = ids, state, reviewed
        self.params = {"decks": list(ids), "state": state, "cards": [list(card) for card in reviewed]}
        self.rows = self.review = None

    def run(self, inv):
        if inv.stale:
            raise inventory.Conflict(CHANGED)
        with inventory.pinned(inv):
            try:
                review = _proposal(self.ids)
            except ApiError:
                raise inventory.Conflict(CHANGED) from None
        if not review["ready"]:
            raise inventory.Conflict(CHANGED)
        adding = [row for row in review["rows"] if row["copies"]]
        found = sorted(((row["name"], row["copies"], row["joins"]) for row in adding), key=lambda card: card[0].casefold())
        if found != self.reviewed:
            raise inventory.Conflict(CHANGED)
        self.rows, self.review = adding, review
        values = [_values(row, review, self.state) for row in adding]
        return inventory.Op("watchlist.add_many", {"rows": values, "repo": str(config.REPO)}).run(inv)


def add_combined(profile, data, expect):
    """save_queue_state's add_combined, after its authorization and revision-shape checks."""
    state = data["state"]
    if not isinstance(state, str) or state not in STATES:
        raise ApiError(400, "state must be ready (To buy) or long_term (Long-term)")
    ids = _ids(data["decks"])
    reviewed = _reviewed(data["cards"])
    _require_cards()
    operation = _CombinedQueue(ids, state, reviewed)
    try:
        inv = inventory.current()
        if inv.revision != expect:
            raise ApiError(409, CHANGED)
        with inventory_write_lock():
            after, _ = inventory.apply(operation, _web_actor(profile), "Queue what to buy to build decks together",
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
    return {"saved": True, "action": "add_combined", "revision": after.revision, "state": state,
            "decks": [deck["id"] for deck in operation.review["decks"]], "for": operation.review["for"],
            "cards": len(rows), "copies": sum(row["copies"] for row in rows)}
