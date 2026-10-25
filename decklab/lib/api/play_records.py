"""Human games and opponent-specific sideboard plans, separate from Forge.

Every record is a row of the database's play_record table, kept through the
state store (decklab.lib.state: play_get, play_put, play_list). A preview
changes nothing. Saving rechecks record and deck hashes under the editor's
write lock (the decks are still files), and the store refuses the write if the
record changed meanwhile. Historical game snapshots survive later deck edits;
correcting a result never rewrites them.

A record's sha256 is the hash of its JSON as the files were written
(state.rules.record_sha): the page sends it back as the version it read.

Records that name decks of two spaces (decision G of the member template,
E10-S32 and E10-S28's independently public decks and games):
- A game is seen by the spaces of its sides, or when any side's space makes
  games public (permissions.sees_play_record); a sideboard plan only by its
  deck's space (_owner_ids). Anyone else, an admin
  included, is answered as for a missing record: 404 "No play record", on a
  save with a stale sha256 too.
- What's sent (_view, for the overview, a preview and a save's answer alike):
  a side whose deck the viewer may not see (guard.sees_deck) is only
  {"hidden": true, "title": "one of the home decks", "player", "mulligans"},
  with no id, list, hash or sideboard plan; a side of another space the
  viewer may see (a public deck) loses its plan; and a game's notes,
  its "space" and who saved it last are kept to the space that recorded it
  (_recording_space: its stored "space", or for a game saved before this
  rule a home side's, else its first side's).
- Saving: each side is changed only by its own space (its deck, player's
  name, mulligans and sideboard plan): a body sends a hidden side back as
  {"hidden": true} and any other space's side unchanged, else 403
  (SIDE_MESSAGE). The date, result and notes are the recording space's (403
  RESULT_MESSAGE otherwise; another space sends the notes back blank, as they
  were shown). Every deck a body names must be one the writer may see (404 "No
  deck X" otherwise, before a stored snapshot is reused), so nobody records a
  game against a deck that's private to them. A plan's deck must be the
  writer's own space's.
"""
import copy
import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from decklab.lib import cards, decks, inventory, permissions, spaces, state
from decklab.lib.state import rules
from .card_lookup import _line_json
from .common import ApiError, _keys, _parse_body, _public, state_errors
from .library import _deck_sections, check_deck_id, is_half
from . import guard, saving
from .settings import _writer


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _play_today():
    return datetime.now(timezone(timedelta(hours=10))).date().isoformat()


def _text(value, label, limit=2000, required=False):
    if (not isinstance(value, str) or len(value) > limit
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ApiError(400, f"{label} must be text of at most {limit} characters")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"Enter {label.lower()}")
    return value


def _integer(value, label, maximum=99):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ApiError(400, f"{label} must be a whole number from 0 to {maximum}")
    return value


def _record_id(record_id):
    if not isinstance(record_id, str) or not rules.PLAY_ID.fullmatch(record_id):
        raise ApiError(400, "Bad play record ID")
    return record_id


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("missing recorded decklist")
    check_deck_id(snapshot["id"])
    if snapshot["version"] not in ("target", "owned"):
        raise ValueError("unknown recorded list version")
    _text(snapshot["title"], "Deck title", 500, required=True)
    sections = snapshot["sections"]
    if not isinstance(sections, dict) or not sections.get("Deck"):
        raise ValueError("missing recorded main deck")
    for section, lines in sections.items():
        _text(section, "Section", 80, required=True)
        if not isinstance(lines, list):
            raise ValueError("invalid recorded deck section")
        for line in lines:
            if not isinstance(line, dict) or type(line.get("qty")) is not int or line["qty"] < 1:
                raise ValueError("invalid recorded card quantity")
            _text(line["name"], "Card name", 300, required=True)
            for key in ("set", "number"):
                if line.get(key) is not None:
                    _text(line[key], "Printing", 80)
            if line.get("finish") not in ("nonfoil", "foil", "etched"):
                raise ValueError("invalid recorded card finish")
    if snapshot["sha256"] != _hash(_bytes({k: snapshot[k] for k in ("id", "version", "sections")})):
        raise ValueError("recorded decklist hash does not match its cards")


def _read(kind, record_id):
    """(record, sha256) of the stored record, or (None, None) when there's none."""
    _record_id(record_id)
    with state_errors():
        record = state.store().play_get(kind, record_id)
    if record is None:
        return None, None
    return record, _checked(kind, record_id, record)


def _checked(kind, record_id, record):
    """The record's sha256, once it passes the checks a save makes (ApiError 500
    otherwise: a damaged record is never built on)."""
    try:
        if record["version"] != 1 or record["id"] != record_id or record["kind"] != kind:
            raise ValueError("record identity differs")
        if type(record.get("revision")) is not int or record["revision"] < 1:
            raise ValueError("missing revision")
        for field in ("created_on", "updated_on"):
            datetime.fromisoformat(record[field])
        _text(record["updated_by"], "Saved by", 80, required=True)
        _text(record["notes"], "Notes")
        if "space" in record and not isinstance(record["space"], str):
            raise ValueError("invalid recording space")
        rules.record_deck_ids(kind, record)
        if kind == "games":
            date.fromisoformat(record["date"])
            if record["result"] not in ("a", "b", "draw") or len(record["sides"]) != 2:
                raise ValueError("invalid recorded result")
            for side in record["sides"]:
                if rules.is_removed_deck(side):
                    continue
                _validate_snapshot(side)
                _text(side["player"], "Player name", 80, required=True)
                _integer(side["mulligans"], "Mulligans", 20)
        else:
            _validate_snapshot(record["deck"])
            if not rules.is_removed_deck(record["opponent"]):
                _validate_snapshot(record["opponent"])
            expected = _plan_moves(record["deck"], record["out"], record["in"])
            if any(record[key] != expected[key] for key in ("out", "in", "after")):
                raise ValueError("recorded sideboard result does not match its moves")
    except (ValueError, TypeError, KeyError, ApiError, state.Invalid) as exc:
        raise ApiError(500, f"Play record {record_id} cannot be read: {_public(exc)}") from None
    return rules.record_sha(record)


def _snapshot(deck_id, version):
    summary, source = _deck_sections(deck_id, version)
    if is_half(summary):
        raise ApiError(400, "Choose a complete deck or Beginner Box pairing")
    sections = {}
    for section, lines in source.items():
        sections[section] = []
        for line in lines:
            if not decks.is_basic_land(line.name) and cards.resolve(line.name) != line.name:
                raise ApiError(400, f"{summary['title']} has a non-canonical card name: {line.name}")
            sections[section].append({"qty": line.quantity, "name": line.name,
                                      "set": line.set, "number": line.number,
                                      "finish": line.finish})
    if not sections.get("Deck"):
        raise ApiError(400, "Choose a deck with a main deck")
    payload = {"id": summary["id"], "version": version, "sections": sections}
    return {**payload, "title": summary["title"], "sha256": _hash(_bytes(payload))}


NO_RECORD = "No play record {!r}"
SIDE_MESSAGE = ("Each side of a game is changed only by its own collection's people: you can change "
                "your own deck, name, mulligans and sideboard plan.")
RESULT_MESSAGE = "A game's date, result and notes are changed only by the collection that recorded it."
PLAN_MESSAGE = "A sideboard plan is for one of your own decks."
SOMEONE = "someone"                 # who last saved a game, to another space
REMOVED_MESSAGE = "A removed deck must stay removed; send its unchanged removal marker."


def _deck_space(deck_id):
    """A deck id's space, None when it can't be read."""
    return permissions._deck_space(deck_id) if isinstance(deck_id, str) else None


def _hidden(value):
    """True for a side (or a plan's opponent) the page sends back as it was shown hidden (_view)."""
    return isinstance(value, dict) and value.get("hidden") is True


def _recording_space(record):
    """The space that recorded a game, whose date, result and notes they are: its stored
    "space", or for a game saved before E10-S32 a home side's (games were recorded on home's
    page then), else its first side's; None when no side can be read."""
    space = record.get("space")
    if isinstance(space, str):
        return space
    found = [_deck_space(side.get("id")) for side in record.get("sides") or () if isinstance(side, dict)]
    found = [space for space in found if space]
    return permissions.HOME if permissions.HOME in found else (found[0] if found else None)


def _owner_ids(kind, record):
    """The deck ids whose spaces see a record (permissions.sees_play_record): a game's sides,
    a sideboard plan's deck only (decision G: a plan belongs to its deck's space). [] for a
    record that can't be read."""
    if kind == "sideboards":
        try:
            deck_id = record["deck"]["id"]
        except (KeyError, TypeError):
            return []
        return [deck_id] if isinstance(deck_id, str) else []
    return _readable_ids(kind, record) if isinstance(record, dict) else []


def _sees_record(kind, record, profile, script=False):
    public = guard.public_spaces("games") if kind == "games" else frozenset()
    return permissions.sees_play_record(profile, _owner_ids(kind, record), script=script, public=public)


def _view(kind, record, profile, script=False):
    """record as profile may be sent it (the module docstring): a side whose deck it may not
    see anonymised, another space's side without its plan, a game's notes, space and last
    saver only to the space that recorded it, and a plan's hidden opponent by its space's name
    only. The record itself for a script naming nobody."""
    if not profile and script:
        return record
    own = permissions._space_of(profile) if profile else None
    sees = guard.deck_reader(profile)
    out = copy.deepcopy(record)
    if kind == "games":
        for i, side in enumerate(record["sides"]):
            if rules.is_removed_deck(side):
                continue
            if not sees(side["id"]):
                out["sides"][i] = {"hidden": True, "title": guard.hidden_deck(side["id"]),
                                   "player": side.get("player"), "mulligans": side.get("mulligans")}
            elif _deck_space(side["id"]) != own:
                for key in ("plan_id", "plan_sha256"):
                    out["sides"][i].pop(key, None)
        if _recording_space(record) != own:
            out["notes"] = ""
            out.pop("space", None)
            if "updated_by" in out:
                out["updated_by"] = SOMEONE
    elif not rules.is_removed_deck(record["opponent"]) and not sees(record["opponent"]["id"]):
        out["opponent"] = {"hidden": True, "title": guard.hidden_deck(record["opponent"]["id"])}
    return out


def _writable_decks(kind, record, profile):
    """The decks of a record play.record is asked over: a game's both (one of the profile's
    makes it theirs to record), a plan's of the profile's own space only (a plan belongs to its
    deck's space, so another space's opponent never makes it writable)."""
    found = _record_decks(record)
    if kind == "games" or not profile:
        return found
    own = permissions._space_of(profile)
    return [deck for deck in found if (deck.get("space") or permissions.HOME) == own]


def _rights(kind, record, profile):
    """What profile may change of a record it sees: a game's {"sides": [bool, bool],
    "result": bool} (its own space's sides; the date, result and notes when its space recorded
    it), a plan's bool. Either needs play.record over the decks it may change."""
    may = guard.allowed(profile, "play.record", _writable_decks(kind, record, profile))
    if kind == "sideboards":
        return may
    own = permissions._space_of(profile) if profile else None
    recording = _recording_space(record)
    return {"sides": [may and not rules.is_removed_deck(side) and (not profile or _deck_space(side["id"]) == own)
                      for side in record["sides"]],
            "result": may and bool(recording) and (not profile or recording == own)}


def _selection(value, previous=None, profile=None):
    if not isinstance(value, dict):
        raise ApiError(400, "Choose a deck and list version")
    _keys(value, ("id", "version", "sha256"), ("player", "mulligans", "plan_id", "plan_sha256"))
    check_deck_id(value["id"])
    # A deck the writer may not see is a missing one, before any stored snapshot is reused (E10-S32).
    guard.require_sees_deck(value["id"], profile)
    if previous and all(value.get(k) == previous.get(k) for k in ("id", "version", "sha256")):
        return copy.deepcopy(previous)  # a recorded game's actual historical list
    snapshot = _snapshot(value["id"], value["version"])
    if snapshot["sha256"] != value["sha256"]:
        raise ApiError(409, "A selected deck changed. Reload the play page and review the current list.")
    return snapshot


def _unchanged_side(value, old):
    """True when a body's side is another space's stored side as it was shown (_view: its
    list, without its plan)."""
    player = value.get("player")
    return (value.get("id") == old["id"] and value.get("version") == old["version"]
            and value.get("sha256") in (old["sha256"], old.get("base_sha256", old["sha256"]))
            and isinstance(player, str) and player.strip() == old["player"]
            and value.get("mulligans") == old["mulligans"]
            and value.get("plan_id") in (None, old.get("plan_id")))


def _game(data, previous, profile):
    try:
        played = date.fromisoformat(data["date"])
    except (ValueError, TypeError):
        raise ApiError(400, "Enter the date played as YYYY-MM-DD") from None
    if played.isoformat() != data["date"] or data["date"] > _play_today():
        raise ApiError(400, "A played game's date cannot be in the future")
    if data["result"] not in ("a", "b", "draw"):
        raise ApiError(400, "Choose the winner or a draw")
    if not isinstance(data["sides"], list) or len(data["sides"]) != 2:
        raise ApiError(400, "A game needs exactly two players and deck lists")
    own = permissions._space_of(profile)
    recording = _recording_space(previous) if previous else own
    notes = _text(data["notes"], "Notes")
    if previous and recording != own:
        # The date, result and notes stay the recording space's; its notes were sent blank (_view).
        if (data["date"], data["result"]) != (previous["date"], previous["result"]) or notes:
            raise ApiError(403, RESULT_MESSAGE)
        notes = previous["notes"]
    sees = guard.deck_reader(profile)
    olds = previous["sides"] if previous else [None, None]

    def opponent_of(i):
        """Side i as a plan's opponent: the body's choice, or a hidden side's stored base list."""
        value, old = data["sides"][i], olds[i]
        if _hidden(value) and old:
            return {"id": old["id"], "version": old["version"], "sha256": old.get("base_sha256", old["sha256"])}
        return value if isinstance(value, dict) else {}

    sides = []
    for i, value in enumerate(data["sides"]):
        old = olds[i]
        if rules.is_removed_deck(old):
            if not rules.is_removed_deck(value):
                raise ApiError(403, REMOVED_MESSAGE)
            sides.append(copy.deepcopy(old))
            continue
        if isinstance(value, dict) and "removed" in value:
            raise ApiError(403, REMOVED_MESSAGE)
        if _hidden(value):
            # A side the writer was sent hidden: kept as it was.
            if not old or sees(old["id"]):
                raise ApiError(400, "Choose a deck and list version")
            _keys(value, ("hidden",), ("title", "player", "mulligans"))
            if any(key in value and value[key] != old[key] for key in ("player", "mulligans")):
                raise ApiError(403, SIDE_MESSAGE)
            sides.append(copy.deepcopy(old))
            continue
        if old and _deck_space(old["id"]) != own:
            # Another space's side: the writer may only send it back as it was shown.
            if not isinstance(value, dict):
                raise ApiError(400, "Choose a deck and list version")
            _keys(value, ("id", "version", "sha256"), ("player", "mulligans", "plan_id", "plan_sha256"))
            check_deck_id(value["id"])
            guard.require_sees_deck(value["id"], profile)
            if not sees(old["id"]) or not _unchanged_side(value, old):
                raise ApiError(403, SIDE_MESSAGE)
            sides.append(copy.deepcopy(old))
            continue
        snapshot = _selection(value, old, profile)
        same_old = old and snapshot["sha256"] == old["sha256"]
        plan_id = value.get("plan_id")
        if plan_id and not (same_old and plan_id == old.get("plan_id")
                            and value.get("plan_sha256") == old.get("plan_sha256")):
            plan, plan_sha = _read("sideboards", plan_id)
            if not plan or plan_sha != value.get("plan_sha256"):
                raise ApiError(409, "The sideboard plan changed. Reload and review it again.")
            if plan["deck"]["sha256"] != snapshot["sha256"]:
                raise ApiError(409, "This sideboard plan belongs to a different deck list")
            opponent = opponent_of(1 - i)
            if rules.is_removed_deck(plan["opponent"]) or rules.is_removed_deck(opponent):
                raise ApiError(403, "A plan against a removed deck cannot replace this game's recorded plan.")
            if any(plan["opponent"][k] != opponent.get(k) for k in ("id", "version", "sha256")):
                raise ApiError(400, "Choose a sideboard plan for this opponent and list version")
            snapshot["base_sha256"] = snapshot["sha256"]
            snapshot["sections"] = copy.deepcopy(plan["after"])
            snapshot["sha256"] = _hash(_bytes({k: snapshot[k] for k in ("id", "version", "sections")}))
            snapshot.update(plan_id=plan_id, plan_sha256=plan_sha)
        elif same_old and old.get("plan_id") and plan_id != old.get("plan_id"):
            raise ApiError(400, "Choose the current base list to replace this historical sideboarded list")
        snapshot["player"] = _text(value.get("player"), "Player name", 80, required=True)
        snapshot["mulligans"] = _integer(value.get("mulligans"), "Mulligans", 20)
        sides.append(snapshot)
    return {"date": data["date"], "sides": sides, "result": data["result"], "notes": notes,
            "space": recording}


def _moves(value, label, available):
    if not isinstance(value, list) or len(value) > 100:
        raise ApiError(400, f"{label} must be a list of at most 100 cards")
    result = Counter()
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, f"Bad {label.lower()} card")
        _keys(item, ("name", "qty"))
        name = item["name"]
        if not isinstance(name, str) or name not in available:
            raise ApiError(400, f"A {label.lower()} card is not in its source section")
        count = _integer(item["qty"], "Copies")
        if count < 1:
            raise ApiError(400, "Moved quantities must be positive")
        result[name] += count
        if result[name] > available[name]:
            raise ApiError(400, f"Only {available[name]} {name} available to move {label.lower()}")
    return [{"name": name, "qty": qty} for name, qty in sorted(result.items())]


def _transfer(source, target, moves):
    for move in moves:
        remaining = move["qty"]
        for line in source:
            if line["name"] == move["name"] and remaining:
                count = min(remaining, line["qty"])
                target.append({**line, "qty": count})
                line["qty"] -= count
                remaining -= count
    source[:] = [line for line in source if line["qty"]]


def _plan_moves(deck, out, into):
    counts = lambda section: Counter({name: sum(x["qty"] for x in deck["sections"].get(section, [])
                                                   if x["name"] == name)
                                      for name in {x["name"] for x in deck["sections"].get(section, [])}})
    outgoing = _moves(out, "Out", counts("Deck"))
    incoming = _moves(into, "In", counts("Sideboard"))
    total = sum(x["qty"] for x in outgoing)
    if not total or total != sum(x["qty"] for x in incoming):
        raise ApiError(400, "Move the same positive number of cards in and out")
    if {x["name"] for x in outgoing} & {x["name"] for x in incoming}:
        raise ApiError(400, "A card cannot move both in and out in the same plan")
    after = copy.deepcopy(deck["sections"])
    after.setdefault("Sideboard", [])
    _transfer(after["Deck"], after["Sideboard"], outgoing)
    _transfer(after["Sideboard"], after["Deck"], incoming)
    return {"out": outgoing, "in": incoming, "after": after}


def _sideboard(data, previous, profile):
    deck = _selection(data["deck"], None, profile)
    if _deck_space(deck["id"]) != permissions._space_of(profile):
        raise ApiError(403, PLAN_MESSAGE)         # a plan belongs to its deck's space (decision G)
    if previous and rules.is_removed_deck(previous["opponent"]):
        if not rules.is_removed_deck(data["opponent"]):
            raise ApiError(403, REMOVED_MESSAGE)
        opponent = copy.deepcopy(previous["opponent"])
    elif isinstance(data["opponent"], dict) and "removed" in data["opponent"]:
        raise ApiError(403, REMOVED_MESSAGE)
    elif _hidden(data["opponent"]):
        # An opponent the writer was sent hidden: kept as it was.
        old = previous["opponent"] if previous else None
        if not old or guard.sees_deck(old["id"], profile):
            raise ApiError(400, "Choose a deck and list version")
        _keys(data["opponent"], ("hidden",), ("title",))
        opponent = copy.deepcopy(old)
    else:
        opponent = _selection(data["opponent"], None, profile)
    return {"deck": deck, "opponent": opponent, **_plan_moves(deck, data["out"], data["in"]),
            "notes": _text(data["notes"], "Notes")}


def _message(kind, content):
    """What the audit trail says a save did, by the decks' titles."""
    if kind == "games":
        a, b = content["sides"]
        return f"Save game {a['title']} vs {b['title']}"
    return f"Save sideboard plan {content['deck']['title']} vs {content['opponent']['title']}"


def _actor(profile):
    """Who saves, for the audit trail: the writer's profile, and the listener
    the change came through."""
    return state.Actor(profile["id"], profile["name"], "home" if guard.local() else "tunnel")


def _related(kind, record):
    """The deck ids a stored game (its sides) or sideboard plan (its deck and opponent) names."""
    return rules.record_deck_ids(kind, record)


def _record_decks(record):
    """The decks a game or sideboard plan involves, as permissions takes them:
    each one's library summary ({"space", "player", ...}), or for a deck
    that's gone since, its space with no player."""
    ids = _related("games" if "sides" in record else "sideboards", record)
    return [decks.find_summary(deck_id) or {"space": spaces.space_of(deck_id), "player": None} for deck_id in ids]


def _save(kind, body):
    data = _parse_body(body)
    profile = _writer(data)
    fields = ("date", "sides", "result", "notes") if kind == "games" else ("deck", "opponent", "out", "in", "notes")
    _keys(data, ("profile", "id", "sha256", *fields, "preview"), ("review_sha256",))
    record_id = _record_id(data["id"] or uuid.uuid4().hex)
    with state_errors():
        # While the database is known to be down, refuse at once rather than
        # wait for the write lock only to fail.
        if not state.reachable():
            raise state.Unavailable("the database isn't reachable")
        # The lock keeps a deck save from landing between the snapshots and the write.
        with saving._save_lock:
            previous = state.store().play_get(kind, record_id)
            # A record the writer may not see answers as a missing one, before its hash or its
            # checks are looked at (E10-S32): 404, a stale sha256 too.
            if (previous is None and data["sha256"] is not None
                    or previous is not None and not _sees_record(kind, previous, profile)):
                raise ApiError(404, NO_RECORD.format(record_id))
            if previous is not None:
                # Public records are read-only to other spaces, before any conflict or
                # stored-content validation can return details of the unchanged game.
                guard.require(profile, "play.record", _writable_decks(kind, previous, profile))
            sha = _checked(kind, record_id, previous) if previous is not None else None
            if sha != data["sha256"]:
                raise ApiError(409, rules.CHANGED_MESSAGE)
            if type(data["preview"]) is not bool:
                raise ApiError(400, "preview must be true or false")
            content = (_game(data, previous, profile) if kind == "games"
                       else _sideboard(data, previous, profile))
            # A record involving one of the profile's decks, before and after (guard.py); a
            # plan, one of its own space's.
            guard.require(profile, "play.record", _writable_decks(kind, content, profile))
            if previous is not None:
                guard.require(profile, "play.record", _writable_decks(kind, previous, profile))
            # Bind confirmation to every semantic field, to the old record and the snapshots.
            review = _hash(_bytes({"content": content, "previous": sha, "kind": kind, "id": record_id}))
            if data["preview"]:
                return {"preview": True, "id": record_id, "record": _view(kind, content, profile),
                        "review_sha256": review}
            if data.get("review_sha256") != review:
                raise ApiError(409, "Review these exact changes before saving the record")
            now = datetime.now(timezone.utc).isoformat()
            record = {"version": 1, "id": record_id, "kind": kind,
                      "revision": previous["revision"] + 1 if previous else 1,
                      "created_on": previous["created_on"] if previous else now,
                      "updated_on": now, "updated_by": profile["name"], **content}
            # The store checks sha again in its own transaction: a Conflict is today's 409.
            stored = state.store().play_put(kind, record, sha, _actor(profile), _message(kind, content))
            return {"saved": True, "record": _view(kind, stored, profile), "sha256": rules.record_sha(stored)}


def save_game(body):
    """POST /api/play/game; preview:true before preview:false + review_sha256."""
    return _save("games", body)


def save_sideboard(body):
    """POST /api/play/sideboard; a plan never mutates a deck or the inventory."""
    return _save("sideboards", body)


def _readable_ids(kind, record):
    """_related() of a record that may be damaged: the ids it names, or [] when it can't be read."""
    try:
        return [d for d in _related(kind, record) if isinstance(d, str)]
    except (AttributeError, KeyError, TypeError, state.Invalid):
        return []


def _plan_cards(record, warnings):
    """Presentation lines for the moves, from the captured source sections.

    A move names a card rather than a printing; _transfer takes its copies
    from source lines in order. Keep that same order and clip each printing's
    quantity without changing the historical record or its concurrency hash.
    """
    result = {}
    for direction, section in (("out", "Deck"), ("in", "Sideboard")):
        remaining = Counter({move["name"]: move["qty"] for move in record[direction]})
        shown = result[direction] = []
        for source in record["deck"]["sections"].get(section, []):
            quantity = min(source["qty"], remaining[source["name"]])
            if not quantity:
                continue
            remaining[source["name"]] -= quantity
            line = decks.DeckLine(quantity, source["name"], source.get("set"), source.get("number"), source["finish"])
            try:
                shown.append(_line_json(line, section, warnings))
            except cards.INDEX_ERRORS:
                warnings.append(f"The card picture for {line.name} couldn't be shown; the recorded move is unchanged.")
                shown.append({"qty": quantity, "name": line.name, "set": line.set, "number": line.number,
                              "finish": line.finish, "card": None})
    return result


def play_overview(deck_id=None):
    """GET /api/play: current list snapshots, and the real games and plans this request's viewer
    may see (permissions.sees_play_record over _owner_ids: a script naming nobody every one;
    anyone else, an admin included, the games with a deck of their own space and the plans of
    their own space's decks), each as _view sends it (a side or opponent they may not see
    anonymised, another space's notes and plans left out); "decks" is {deck id: {"player", "status", "can_record"}} for the lists' decks, so the quick
    record can start each player on a deck of theirs (a list snapshot itself carries only what a
    record keeps). A game entry also has "can" ({"sides": [bool, bool], "result": bool}: what
    the viewer may change, _rights), a plan entry "cards" ({"out", "in"}: presentation lines
    from its historical sections) and "editable"; none is part of its stored record or sha256.
    The lists and decks are only the decks the viewer may see (guard.sees_deck: its own space's,
    filtered before any snapshot is taken, so no warning names a hidden deck), and deck_id
    matches only a record's decks the viewer sees. A record that can't be shown
    is warned about only to a viewer who may see it (a damaged one with no readable deck id:
    only to those who see every one). ApiError 403 for a tunnel login that isn't set up."""
    if deck_id:
        check_deck_id(deck_id)
        deck_id = inventory.resolve_deck_id(deck_id)
    snapshot = inventory.current() if deck_id else None
    viewer, script = guard.viewer(), guard.script()
    reads = guard.deck_reader(viewer)
    # The records first: while the database is down the page gets its 503
    # before paying for every deck's snapshots.
    with state_errors():
        stored = {kind: state.store().play_list(kind) for kind in ("games", "sideboards")}
    snapshots, warnings, about = [], [], {}
    for summary in guard.visible_decks(decks.list_decks(), viewer):     # before any snapshot (E10-S30)
        if summary.get("error") or is_half(summary):
            continue
        about[summary["id"]] = {"player": summary.get("player"), "status": summary.get("status"),
                                 "can_record": guard.allowed(viewer, "play.record", [summary])}
        for version in summary["versions"]:
            try:
                snapshots.append(_snapshot(summary["id"], version))
            except ApiError as exc:
                warnings.append(str(exc))
    answer = {"lists": snapshots, "games": [], "sideboards": [], "warnings": warnings, "today": _play_today(),
              "decks": about}
    for kind, records in stored.items():
        for record in records:
            # The deck filter matches only decks the viewer sees, so it can't tell a hidden side's deck.
            ids = [item for item in (_readable_ids(kind, record) if isinstance(record, dict) else [])
                   if reads(item)]
            if (not _sees_record(kind, record, viewer, script)
                    or (deck_id and not any(inventory.same_deck_id(deck_id, item, snapshot) for item in ids))):
                continue            # another space's record (or another deck's), not even its warning
            try:
                sha = _checked(kind, record.get("id"), record)
                entry = {"record": _view(kind, record, viewer, script), "sha256": sha}
                if kind == "sideboards":
                    entry.update(cards=_plan_cards(record, warnings), editable=_rights(kind, record, viewer))
                else:
                    entry["can"] = _rights(kind, record, viewer)
                answer[kind].append(entry)
            except (ApiError, AttributeError, KeyError, TypeError) as exc:
                warnings.append(f"A {kind} record could not be shown: {_public(exc)}")
        # Newest first; games of the same day by when they were recorded, so "each player's last deck"
        # (the quick record's start) is the last game's.
        answer[kind].sort(key=lambda entry: (entry["record"].get("date", entry["record"]["updated_on"]),
                                             entry["record"].get("created_on") or "",
                                             entry["record"].get("updated_on") or ""), reverse=True)
    return answer
