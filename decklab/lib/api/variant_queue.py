"""Review one saved test's missing card, then add exactly that intent as one change.

The queue source is the current deck's supported path; the saved test link is a
note, never an invented source kind. A process-local, short-lived review binds
the actor, saved recipe, inventory/deck revisions and exact proposed queue row.
"""
import contextlib
from copy import deepcopy
import hashlib
import json
import re
import secrets
import threading
import time

from decklab.lib import cards, config, decks, inventory

from . import forge_runs, guard, shopping_queue, variant_buying, variant_page
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body, _public
from .saving import inventory_write_lock
from .settings import _web_actor, _writer

PREVIEW_TTL = 600
MAX_PREVIEWS = 64
CHANGED = "The test, deck, collection or queue changed. Review this card again before saving."
EXPIRED = "That queue review has expired or is unavailable. Review the card again."
_reviews = {}
_review_lock = threading.Lock()


def _authorized(data):
    profile = _writer(data)
    guard.require(profile, "orders.edit")
    guard.require_sees_home_records(profile)
    return profile


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _choice(value):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ApiError(400, "choice must give the printing and finish to request")
    _keys(value, (), ("printing", "set", "collector_number", "finish"))
    result = {"printing": "any", "set": "", "collector_number": "", "finish": "nonfoil", **value}
    if any(not isinstance(item, str) for item in result.values()):
        raise ApiError(400, "Printing and finish must be text")
    if result["printing"] not in ("any", "exact") or result["finish"] not in ("nonfoil", "foil", "etched"):
        raise ApiError(400, "Choose any or exact printing and a nonfoil, foil or etched finish")
    if result["printing"] == "any" and (result["set"] or result["collector_number"]):
        raise ApiError(400, "An any-printing request must leave set and collector number empty")
    if result["printing"] == "exact" and not (result["set"] and result["collector_number"]):
        raise ApiError(400, "An exact request needs its set, collector number and finish")
    return result


def _saved(test_id, profile):
    """Existing visibility semantics, without engine discovery or playing anything."""
    forge = variant_page._forge()
    seen = forge_runs._Seen(profile)
    saved = forge.variants.load_summary(test_id)
    if saved is None or not variant_page._sees_test(saved, seen):
        raise ApiError(404, variant_page.TEST_NONE)
    job = forge_runs.COORD_JOBS.get(variant_page._job_key(test_id))
    if job is not None:
        snapshot = forge_runs.COORD_JOBS.snapshot(job)
        if snapshot["status"] in variant_page.WAITING:
            raise ApiError(409, "Wait for this test to finish before reviewing a queue request.")
    if not saved.get("looks") and saved.get("outcome") is None:
        raise ApiError(409, "This test has no finished result to review.")
    if not variant_buying.HOME_DECK.fullmatch(str((saved.get("base") or {}).get("id", ""))):
        raise ApiError(400, "Only a saved home deck's test can add a home queue request.")
    return saved


def _stamp(inv, deck_id):
    deck = inv.deck(deck_id)
    if deck is None:
        raise ApiError(409, CHANGED)
    return {"revision": inv.revision, "decks_revision": inv.decks_revision,
            "deck_id": deck_id, "deck_sha256": deck.sha256}


def _proposal(test_id, name, choice, profile):
    inv = inventory.current()
    if inv.stale or not inv.persisted:
        raise ApiError(409, "Current inventory is unavailable. Reload and review the card when it is available.")
    saved = _saved(test_id, profile)
    buying = variant_buying.build(saved)
    if not buying["ready"]:
        raise ApiError(409, buying.get("reason") or "Buying information is unavailable. Review it again when ready.")
    exact = cards.resolve(name)
    row = next((row for row in buying["rows"] if row["name"] == exact), None)
    if row is None:
        raise ApiError(400, "Choose a card addition shown by this saved test.")
    # All states, purposes and finishes remain explicit decisions. This bounded
    # action cannot silently top up or create a second request for the same card.
    selected = {"name": row["name"], "queued": [], "references": []}
    omitted = {"queued": 0, "references": 0}
    problem = variant_buying._queue([selected], omitted)
    if problem:
        raise ApiError(409, problem)
    if selected["queued"] or omitted["queued"]:
        return {"ready": False, "reason": "This card already has purchase requests. Review them in Shopping first.",
                "existing": selected["queued"], "omitted": omitted["queued"], "name": row["name"]}
    quantity = row["missing_added"]
    if type(quantity) is not int or quantity < 1 or quantity > row["added"]:
        raise ApiError(409, "No confirmed missing added copies remain to queue.")
    deck_id = inventory.resolve_deck_id(saved["base"]["id"], inv)
    summary = decks.find_summary(deck_id)
    if summary is None:
        raise ApiError(409, CHANGED)
    title = summary["title"]
    values = shopping_queue._values({"name": row["name"], "quantity": quantity, "state": "ready",
                                     "for": title, "source": f"magic/decks/{deck_id}.md",
                                     "notes": f"Saved test #/variant?test={test_id}", **choice})
    values = shopping_queue._card_values(values)
    if values["name"] != row["name"]:
        raise ApiError(400, "Choose a playable printing of this test's added card.")
    if choice["printing"] == "exact":
        printed = cards.printing_card(values["set"], values["collector_number"])
        if printed is None or printed["name"] != row["name"]:
            raise ApiError(400, "Choose a playable printing of this test's added card.")
    # The existing validator checks supported sources and every queue column.
    # Missing retailer fields stay blank; an estimate is never a shop observation.
    operation = inventory.Op("watchlist.set", {"add": True, "values": values, "repo": str(config.REPO)})
    operation.run(inv)
    # A later completed look may change the verdict without changing its cards.
    # Review is tied to the entire saved evidence as well as its recipe.
    return {"ready": True, "proposal": values, "stamp": _stamp(inv, deck_id), "recipe": _digest(saved),
            "test": test_id, "name": row["name"], "choice": choice,
            "deck": {"id": deck_id, "title": title, "version": saved["base"]["version"]},
            "added": row["added"], "missing_added": quantity, "basis": buying["basis"]}


def _keep(record, profile):
    now = time.monotonic()
    actor = _web_actor(profile)
    with _review_lock:
        expired = [key for key, value in _reviews.items() if not value["busy"] and now - value["created"] > PREVIEW_TTL]
        for key in expired:
            del _reviews[key]
        while len(_reviews) >= MAX_PREVIEWS:
            available = [key for key, value in _reviews.items() if not value["busy"]]
            if not available:
                raise ApiError(503, "Queue requests are being saved. Try preparing this review again in a minute.")
            del _reviews[min(available, key=lambda key: _reviews[key]["created"])]
        token = secrets.token_hex(16)
        kept = {**deepcopy(record), "_created": now}
        _reviews[token] = {"created": now, "actor": (actor.id, actor.via), "record": kept, "busy": False}
    return token


def _review(token, profile):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ApiError(400, "Prepare a queue review first")
    actor = _web_actor(profile)
    with _review_lock:
        kept = _reviews.get(token)
        if kept is None or kept["actor"] != (actor.id, actor.via) or not 0 <= time.monotonic() - kept["created"] <= PREVIEW_TTL:
            raise ApiError(409, EXPIRED)
        if kept["busy"]:
            raise ApiError(409, "This queue request is already being saved.")
        kept["busy"] = True
        return deepcopy(kept["record"])


def _problem(error):
    if isinstance(error, ApiError):
        return error
    if isinstance(error, inventory.Unavailable):
        return ApiError(503, DATABASE_DOWN, reason="database")
    if isinstance(error, inventory.Conflict):
        return ApiError(409, CHANGED)
    return ApiError(400, "The purchase request could not be prepared: " + _public(error))


def preview_queue(body):
    """POST /api/variant/queue/preview: one card's server-calculated missing copies."""
    data = _parse_body(body)
    profile = _authorized(data)
    _keys(data, ("profile", "test", "name"), ("choice",))
    test_id = variant_page._test_id(data["test"])
    name = data["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > variant_buying.MAX_TEXT:
        raise ApiError(400, "Give a card addition from this saved test")
    choice = _choice(data.get("choice"))
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            record = _proposal(test_id, name, choice, profile)
            if not record["ready"]:
                return record
            token = _keep(record, profile)
    except (ApiError, inventory.StateError, ValueError, OSError) as error:
        raise _problem(error) from None
    return {key: deepcopy(record[key]) for key in ("ready", "proposal", "test", "name", "deck", "added", "missing_added", "basis")} | {
        "preview": token, "expires_in": PREVIEW_TTL}


class _ReviewedQueue:
    kind = "watchlist.set"

    def __init__(self, record, profile):
        self.record, self.profile = record, profile
        self.params = {"add": True, "values": record["proposal"], "test": record["test"]}

    def run(self, inv):
        record = self.record
        if not 0 <= time.monotonic() - record["_created"] <= PREVIEW_TTL:
            raise inventory.Conflict(EXPIRED)
        if inv.stale or _stamp(inv, record["stamp"]["deck_id"]) != record["stamp"]:
            raise inventory.Conflict(CHANGED)
        with inventory.pinned(inv):
            checked = _proposal(record["test"], record["name"], record["choice"], self.profile)
        if not checked["ready"] or checked["recipe"] != record["recipe"] or checked["proposal"] != record["proposal"]:
            raise inventory.Conflict(CHANGED)
        return inventory.Op("watchlist.set", {"add": True, "values": record["proposal"], "repo": str(config.REPO)}).run(inv)


def apply_queue(body):
    """POST /api/variant/queue: apply only an unchanged reviewed proposal, as one audit."""
    data = _parse_body(body)
    profile = _authorized(data)
    _keys(data, ("profile", "preview"))
    record = _review(data["preview"], profile)
    try:
        with inventory_write_lock():
            after, _ = inventory.apply(_ReviewedQueue(record, profile), _web_actor(profile),
                                       "Queue a missing card from a saved test", expected_revision=record["stamp"]["revision"])
    except (ApiError, inventory.StateError, ValueError, OSError) as error:
        raise _problem(error) from None
    else:
        with _review_lock:
            _reviews.pop(data["preview"], None)
    finally:
        with _review_lock:
            if data["preview"] in _reviews:
                _reviews[data["preview"]]["busy"] = False
    return {"saved": True, "test": record["test"], "name": record["name"],
            "quantity": int(record["proposal"]["quantity"]), "revision": after.revision}
