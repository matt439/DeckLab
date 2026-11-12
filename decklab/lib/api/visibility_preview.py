"""What a Public switch would show, for its owner only (E10-S46).

GET /api/visibility/preview?owner=&thing= checks ownership exactly as PUT /api/visibility does
(permissions.visibility_controls over the request's viewer, no admin override) before anything is
read, and refuses everyone else with the same fixed words for hidden and absent owners. The answer
holds counts from the owner's own space (or kit) only, and for decks the owner's decks whose
write-ups mention orders or purchases. When the counts can't be worked out the answer says so
("available": false) and the page still offers Confirm. Nothing here writes or flips a switch.
"""
import re

from decklab.lib import inventory, permissions, state, visibility
from decklab.lib.state import visibility as values

from . import guard
from .common import ApiError
from .visibility import NOT_READY, OWNER_ONLY

UNAVAILABLE = "Deck Lab couldn't work out what this would show just now. You can still make it Public."
MENTION_LIMIT = 50
_FENCE = re.compile(r"^```.*?^```[^\n]*$", re.M | re.S)
_SECTION = re.compile(r"^(#{2,3})\s+(.*)$")
# Words a write-up uses for cards on order or bought; "in order to" and "order of" aren't orders.
_MENTION = re.compile(r"\b(?:pre-?order\w*|orders?|ordered|purchas\w*|bought|buy(?:ing|s)?|on the way|shop(?:s|ping)?)\b",
                      re.I)
_NOT_ORDERS = re.compile(r"\b(?:in order to|in order|order of|turn order|play order|the order)\b", re.I)


def _owned(profile, owner, thing):
    """True when profile owns this switch (any category, ready or not), as change() checks it."""
    if not isinstance(owner, str) or not isinstance(thing, str):
        return False
    rows = permissions.visibility_controls(profile, ready=values.THINGS)
    return (owner, thing) in {(r["owner"], r["thing"]) for r in rows}


def _prose(text):
    """A deck text without its card lists (fenced blocks) and its owned-vs-needed table, which a
    Public deck's readers don't get from the inventory unless the collection is Public too."""
    kept, skipping = [], False
    for line in _FENCE.sub("", text).splitlines():
        heading = _SECTION.match(line)
        if heading:
            skipping = heading.group(2).strip().lower().startswith("owned vs needed")
            if skipping:
                continue
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def mentions_purchases(text):
    """True when a deck's write-up (outside its lists and table) mentions orders or purchases."""
    if not isinstance(text, str):
        return False
    return bool(_MENTION.search(_NOT_ORDERS.sub(" ", _prose(text))))


def _title(deck):
    for line in (deck.text or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip() or deck.id
    return deck.id


def _decks(snapshot, space):
    own = sorted((d for d in snapshot.decks.values() if d.space == space), key=lambda d: d.id)
    mentioning = [{"id": d.id, "title": _title(d)} for d in own if mentions_purchases(d.text)]
    return {"decks": len(own), "unreadable_decks": sum(1 for d in own if d.text is None)}, mentioning


def _quantity(row):
    qty = row.qty if hasattr(row, "qty") else None
    return qty if isinstance(qty, int) else 0


def _collection(snapshot, space):
    cards = snapshot.collections.get(space)
    tokens = snapshot.tokens.get(space)
    card_rows = list(cards.rows) if cards is not None else []
    token_rows = list(tokens.rows) if tokens is not None else []
    return {"collection_rows": len(card_rows), "collection_cards": sum(_quantity(r) for r in card_rows),
            "token_rows": len(token_rows), "token_cards": sum(_quantity(r) for r in token_rows)}


def _games(space):
    from .play_records import _readable_ids
    records = state.store().play_list("games")
    return {"games": sum(1 for record in records if isinstance(record, dict) and any(
        permissions._deck_space(deck_id) == space for deck_id in _readable_ids("games", record)))}


def _kit(snapshot, owner):
    rows = [row for row in snapshot.accessories.rows if (row.owner or "").strip() == owner]
    return {"kit_rows": len(rows), "kit_pictures": sum(1 for row in rows if (row.image or "").strip())}


def _counts(owner, thing):
    if thing == "games":
        return _games(owner), []
    snapshot = inventory.current()
    if snapshot.stale:
        raise RuntimeError("stale")         # an outage's last snapshot isn't what Public would show now
    if thing == "decks":
        return _decks(snapshot, owner)
    if thing == "collection":
        return _collection(snapshot, owner), []
    return _kit(snapshot, owner), []


def preview(owner, thing):
    """GET /api/visibility/preview: {"owner", "thing", "public", "available", "counts",
    "mentions" (decks only, at most MENTION_LIMIT), "more_mentions", "message"}."""
    profile = guard.viewer()
    # Ownership before validation, readiness or any read: the same refusal for everyone else.
    if not _owned(profile, owner, thing):
        raise ApiError(403, OWNER_ONLY)
    if thing not in visibility.READY_THINGS:
        raise ApiError(409, NOT_READY)
    answer = {"owner": owner, "thing": thing, "public": (owner, thing) in guard.visibility(),
              "available": True, "counts": {}, "mentions": [], "more_mentions": 0, "message": None}
    try:
        counts, mentions = _counts(owner, thing)
    except Exception:           # noqa: BLE001 - any failure is reported as "can't work it out", never raw
        return {**answer, "available": False, "message": UNAVAILABLE}
    answer.update(counts=counts, mentions=mentions[:MENTION_LIMIT],
                  more_mentions=max(0, len(mentions) - MENTION_LIMIT))
    return answer
