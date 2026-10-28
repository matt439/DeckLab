"""Reviewed Commander pod records, with private opponent labels and no 1v1 totals.

The request contains selectors, never caller-made snapshots. Historical snapshots
can be reused only in the same stable seat, after both deck identities are visible.
All seats with a Deck Lab deck belong to the recording space; external opponents
are plain private labels and carry no invented deck or card information.
"""
import copy
import uuid
from datetime import date, datetime, timezone

from decklab.lib import decks, inventory, permissions, state
from decklab.lib.state import pods, rules
from . import guard, play_records as play, saving
from .common import ApiError, _keys, _parse_body, state_errors
from .settings import _writer

MAX_BODY = 16 * 1024
MODE_MESSAGE = "A pod and a two-player game cannot replace one another."
SPACE_MESSAGE = "A pod you record uses decks from your own collection."


def checked(record):
    """Validate full captured lists after the core validates the pod's structure."""
    pods.record_deck_ids(record)
    for seat in record["seats"]:
        if seat["type"] == "deck":
            play._validate_snapshot(seat["deck"])


def view(record, profile, script=False):
    if not profile and script:
        return record
    out = copy.deepcopy(record)
    own = permissions._space_of(profile) if profile else None
    private = own == record["space"]
    reads = guard.deck_reader(profile)
    for index, seat in enumerate(record["seats"]):
        shown = out["seats"][index]
        if not private:
            shown["player"] = f"Player {index + 1}"
            if seat["type"] == "external":
                shown["commander"] = ""
        if seat["type"] == "deck" and not reads(seat["deck"]["id"]):
            shown["deck"] = {"hidden": True, "title": guard.hidden_deck(seat["deck"]["id"])}
    if not private:
        out["notes"] = ""
        out.pop("space", None)
        if "updated_by" in out:
            out["updated_by"] = play.SOMEONE
    return out


def rights(record, profile):
    own = permissions._space_of(profile) if profile else None
    return {"edit": bool(profile and own == record["space"] and guard.allowed(
        profile, "play.record", play._writable_decks("games", record, profile)))}


def choice(summary, snapshot, profile):
    """A positive own-space Commander choice, separately from ordinary 1v1 lists."""
    if not profile or decks.engine_kind(summary) != "commander":
        return None
    own = permissions._space_of(profile)
    deck_id = summary["id"]
    canonical = snapshot["id"]
    if (play._deck_space(deck_id) != own or play._deck_space(canonical) != own
            or not guard.sees_deck(deck_id, profile) or not guard.sees_deck(canonical, profile)):
        return None
    return {**copy.deepcopy(snapshot), "can_record": bool(guard.allowed(profile, "play.record", [summary]))}


def _line(value, label, limit, required=False):
    if isinstance(value, str) and any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ApiError(400, f"{label} must be on one line")
    return play._text(value, label, limit, required)


def _raw_ids(data, profile):
    """Refuse hidden raw selectors before loading even an inventory snapshot."""
    seats = data.get("seats")
    if not isinstance(seats, list) or len(seats) not in (3, 4):
        raise ApiError(400, "A pod needs three or four seats")
    own = permissions._space_of(profile)
    identities = []
    for seat in seats:
        if not isinstance(seat, dict) or seat.get("type") != "deck":
            continue
        if type(seat.get("seat_id")) is not str or seat["seat_id"] not in ("s1", "s2", "s3", "s4"):
            raise ApiError(400, "Choose a stable pod seat")
        value = seat.get("deck")
        if not isinstance(value, dict):
            raise ApiError(400, "Choose a deck and list version")
        _keys(value, ("id", "version", "sha256"))
        play.check_deck_id(value["id"])
        guard.require_sees_deck(value["id"], profile)
        if play._deck_space(value["id"]) != own:
            raise ApiError(403, SPACE_MESSAGE)
        identities.append((seat["seat_id"], value["id"]))
    return identities


def _identities(raw_ids, profile):
    """Resolve all canonical identities in the caller's one pinned snapshot."""
    own = permissions._space_of(profile)
    identities = {}
    for seat_id, deck_id in raw_ids:
        canonical = inventory.resolve_deck_id(deck_id)
        guard.require_sees_deck(canonical, profile, deck_id=deck_id)
        if play._deck_space(canonical) != own:
            raise ApiError(403, SPACE_MESSAGE)
        identities[seat_id] = canonical
    return identities


def _content(data, previous, profile, identities):
    own = permissions._space_of(profile)
    try:
        played = date.fromisoformat(data["date"])
    except (ValueError, TypeError):
        raise ApiError(400, "Enter the date played as YYYY-MM-DD") from None
    if played.isoformat() != data["date"] or data["date"] > play._play_today():
        raise ApiError(400, "A played game's date cannot be in the future")
    content = {"mode": data["mode"], "game_version": data["game_version"], "space": own,
               "date": data["date"], "result": data["result"],
               "notes": play._text(data["notes"], "Notes"), "seats": []}
    olds = {seat["seat_id"]: seat for seat in previous["seats"]} if previous else {}
    for value in data["seats"]:
        if not isinstance(value, dict):
            raise ApiError(400, "Choose a deck or external opponent for every seat")
        if value.get("type") == "deck":
            _keys(value, ("seat_id", "type", "player", "deck"))
        elif value.get("type") == "external":
            _keys(value, ("seat_id", "type", "player", "commander"))
        else:
            raise ApiError(400, "Choose a deck or external opponent for every seat")
        seat = {"seat_id": value["seat_id"], "type": value["type"],
                "player": _line(value["player"], "Player name", 80, required=True)}
        if seat["type"] == "external":
            seat["commander"] = _line(value["commander"], "Commander label", 300)
        else:
            # Validate the cheap selector shape with the core before paying for snapshots.
            seat["deck"] = copy.deepcopy(value["deck"])
        content["seats"].append(seat)
    pods.record_deck_ids(content)
    for seat in content["seats"]:
        if seat["type"] != "deck":
            continue
        selector = seat["deck"]
        old = olds.get(seat["seat_id"])
        captured = old.get("deck") if old and old["type"] == "deck" else None
        if captured and all(selector[key] == captured[key] for key in ("id", "version", "sha256")):
            seat["deck"] = copy.deepcopy(captured)
            continue
        canonical = identities[seat["seat_id"]]
        summary = decks.find_summary(canonical)
        if not summary:
            raise guard.no_deck(selector["id"])
        if decks.engine_kind(summary) != "commander":
            raise ApiError(400, "Choose a Commander deck for a pod")
        snapshot = play._snapshot(canonical, selector["version"])
        if snapshot["sha256"] != selector["sha256"]:
            raise ApiError(409, "A selected deck changed. Reload the play page and review the current list.")
        seat["deck"] = snapshot
    pods.record_deck_ids(content)
    return content


def save_pod(body):
    """POST /api/play/pod: an explicit review, followed by its exact confirmation."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "mode", "game_version", "date", "seats", "result", "notes", "preview"),
          ("review_sha256",))
    with state_errors():
        if pods.mode(data) != "pod":
            raise ApiError(400, "Choose a pod game")
        if type(data["preview"]) is not bool:
            raise ApiError(400, "preview must be true or false")
        record_id = play._record_id(uuid.uuid4().hex if data["id"] is None else data["id"])
        if data["sha256"] is not None and (not isinstance(data["sha256"], str)
                or len(data["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in data["sha256"])):
            raise ApiError(400, "A play record needs its SHA-256")
        if not state.reachable():
            raise state.Unavailable("the database isn't reachable")
        with saving._save_lock:
            raw_ids = _raw_ids(data, profile)
            with inventory.pinned(inventory.current()):
                return _save_locked(data, profile, record_id, _identities(raw_ids, profile))


def _save_locked(data, profile, record_id, identities):
    """Preview or save after both visibility passes, within the lock and snapshot."""
    previous = state.store().play_get("games", record_id)
    if (previous is None and data["sha256"] is not None
            or previous is not None and not play._sees_record("games", previous, profile)):
        raise ApiError(404, play.NO_RECORD.format(record_id))
    if previous is not None:
        guard.require(profile, "play.record", play._writable_decks("games", previous, profile))
        if pods.mode(previous) != "pod":
            raise ApiError(400, MODE_MESSAGE)
        if previous["space"] != permissions._space_of(profile):
            raise ApiError(403, SPACE_MESSAGE)
    sha = play._checked("games", record_id, previous) if previous is not None else None
    if sha != data["sha256"]:
        raise ApiError(409, rules.CHANGED_MESSAGE)
    content = _content(data, previous, profile, identities)
    guard.require(profile, "play.record", play._writable_decks("games", content, profile))
    review = play._hash(play._bytes({"content": content, "previous": sha, "kind": "games", "id": record_id}))
    if data["preview"]:
        return {"preview": True, "id": record_id, "record": view(content, profile), "review_sha256": review}
    if data.get("review_sha256") != review:
        raise ApiError(409, "Review these exact changes before saving the record")
    now = datetime.now(timezone.utc).isoformat()
    record = {"version": 1, "id": record_id, "kind": "games",
              "revision": previous["revision"] + 1 if previous else 1,
              "created_on": previous["created_on"] if previous else now,
              "updated_on": now, "updated_by": profile["name"], **content}
    stored = state.store().play_put("games", record, sha, play._actor(profile), play._message("games", content))
    return {"saved": True, "record": view(stored, profile), "sha256": rules.record_sha(stored)}
