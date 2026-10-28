"""The rules both stores keep (memory.py and pg.py), in one place so they can't drift apart:
the forms of profile ids, wishlist entries and settings, which wishlist entry a name means
(casefold, as the files did), the play records' bytes and hash, and the Activity scan's cap.

Text with a control character in it is refused here (notes may still hold line breaks and
tabs): PostgreSQL can't store a NUL at all, so without this the two stores would disagree.

Only the standard library; nothing here touches a database.
"""
import hashlib
import json
import re
from datetime import datetime

from . import Invalid
from .play import REMOVED_DECK, is_removed_deck, record_deck_ids

PROFILE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")         # migration 0003's check, as the file names were
SETTING_KEY = re.compile(r"[a-z_]{1,40}")
SET_CODE = re.compile(r"[a-z0-9]{2,8}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")               # api/common._CONTROL_RE
NOTES_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")    # the same, less tab and line breaks

MAX_ENTRIES = 1000                  # cards on one wishlist
MAX_NAME = 150                      # characters in a card name (api/common.MAX_NAME)
MAX_NOTES = 2000
MAX_SOURCE = 300
MAX_NUMBER = 16                     # characters in a collector number
MAX_SETTING = 200                   # characters in a setting's value
MAX_PACKING_TASKS = 2000
PACKING_ID = re.compile(r"[a-f0-9]{64}")
ENTRY_KEYS = ("name", "set", "number", "notes", "source")
FULL_MESSAGE = f"A wishlist can hold at most {MAX_ENTRIES} cards"

RUN_MODES = ("admins", "everyone", "paused")            # permissions.RUN_MODES, checked by the table too

PLAY_KINDS = ("games", "sideboards")
PLAY_ID = re.compile(r"[a-f0-9]{32}")
PLAY_HEADER = ("version", "id", "kind", "revision", "created_on", "updated_on", "updated_by")
MAX_UPDATED_BY = 80
CHANGED_MESSAGE = "This record changed or was removed. Reload before saving another revision."

SCAN_CAP = 2000                     # change sets one activity() call examines at most
MAX_LIMIT = 100                     # change sets one activity() call returns at most


def profile_id(value):
    """value when it's a profile id in the stores' form, else Invalid."""
    if not isinstance(value, str) or not PROFILE_ID.fullmatch(value):
        raise Invalid("Bad profile ID")
    return value


# ------------------------------------------------------------------ wishlists

def wishlist_orphan(allow, actor):
    """Explicit CLI upkeep may target an unconfigured list, never a web save."""
    if type(allow) is not bool:
        raise Invalid("allow_orphan must be true or false")
    if allow and actor.source != "cli":
        raise Invalid("Orphan wishlist upkeep is only available on the command line")
    return allow


def entry(value):
    """A wishlist entry as both stores keep it: {name, set, number, notes, source}, all text,
    "" for no printing (set and number both, or neither) and for no notes or source. notes and
    source may be left out. Invalid when it breaks a rule migration 0003's checks would."""
    if not isinstance(value, dict) or not {"name", "set", "number"} <= set(value) <= set(ENTRY_KEYS):
        raise Invalid("A wishlist entry needs name, set and number (and may have notes and source)")
    out = {"name": value["name"], "set": value["set"], "number": value["number"],
           "notes": value.get("notes", ""), "source": value.get("source", "")}
    if any(not isinstance(v, str) for v in out.values()):
        raise Invalid("A wishlist entry's fields must be text")
    name = out["name"]
    if not name or name != name.strip() or len(name) > MAX_NAME:
        raise Invalid(f"Give a card name of at most {MAX_NAME} characters, with no spaces around it")
    if bool(out["set"]) != bool(out["number"]) or out["set"] and (
            not SET_CODE.fullmatch(out["set"]) or len(out["number"]) > MAX_NUMBER):
        raise Invalid("Give both set and number for a printing, or leave both empty")
    if len(out["notes"]) > MAX_NOTES or len(out["source"]) > MAX_SOURCE:
        raise Invalid(f"Notes are limited to {MAX_NOTES} characters and source to {MAX_SOURCE}")
    if any(CONTROL.search(out[key]) for key in ("name", "set", "number", "source"))             or NOTES_CONTROL.search(out["notes"]):
        raise Invalid("A wishlist entry can't hold control characters (notes may have line breaks)")
    return out


def find(entries, name):
    """The index of the entry whose name is casefold-equal to name, or None."""
    key = name.casefold() if isinstance(name, str) else None
    return next((i for i, e in enumerate(entries) if e["name"].casefold() == key), None)


def add_plan(entries, new):
    """What adding new (a checked entry) to entries does: "exists" when a casefold-equal name is
    there already (nothing changes), "add", or Invalid(FULL_MESSAGE) when the list is full."""
    if find(entries, new["name"]) is not None:
        return "exists"
    if len(entries) >= MAX_ENTRIES:
        raise Invalid(FULL_MESSAGE)
    return "add"


def insert_slot(positions, at=None):
    """Where an entry added at index at of a list whose stored positions are positions (in list
    order) goes: (position, moves), moves being [(old, new)] positions to change first, in that
    order (each into a free slot, so the primary key is never broken on the way). None, or an at
    past the end, appends (max + 1). A removal leaves its position free, so putting a removed card
    back where it was (the page's Undo) usually moves nothing; otherwise the entries from at up to
    the next free position each move one up. Invalid for an at that isn't a whole number >= 0."""
    if at is not None and (isinstance(at, bool) or not isinstance(at, int) or at < 0):
        raise Invalid("at must be a whole number from 0")
    if at is None or at >= len(positions):
        return max(positions, default=-1) + 1, []
    below = positions[at - 1] if at else -1
    if positions[at] - below > 1:
        return positions[at] - 1, []
    end = at
    while end + 1 < len(positions) and positions[end + 1] == positions[end] + 1:
        end += 1
    return positions[at], [(p, p + 1) for p in reversed(positions[at:end + 1])]


def edited(old, notes=None, source=None, set=None, number=None):
    """old with the given fields replaced (None keeps a field; set and number go together),
    checked like a new entry."""
    if (set is None) != (number is None):
        raise Invalid("Give both set and number for a printing, or neither to keep it")
    out = dict(old)
    for key, value in (("notes", notes), ("source", source), ("set", set), ("number", number)):
        if value is not None:
            out[key] = value
    return entry(out)


# ------------------------------------------------------------------ settings

def setting_values(values):
    """values ({key: text or None}) checked: keys in SETTING_KEY's form, values text of at most
    MAX_SETTING characters, or None (remove the key). Returns them sorted by key, the order
    both stores write them in."""
    if not isinstance(values, dict):
        raise Invalid("Settings must be a mapping of names to values")
    for key, value in values.items():
        if not isinstance(key, str) or not SETTING_KEY.fullmatch(key):
            raise Invalid(f"Bad setting name {key!r}")
        if value is not None and (not isinstance(value, str) or len(value) > MAX_SETTING
                                  or CONTROL.search(value)):
            raise Invalid(f"{key} must be text of at most {MAX_SETTING} characters, with no control characters")
    return dict(sorted(values.items()))


def packing_ids(values):
    """Opaque physical-task hashes, scoped by the caller, in stable order."""
    if not isinstance(values, (list, tuple)) or len(values) > MAX_PACKING_TASKS:
        raise Invalid(f"Choose at most {MAX_PACKING_TASKS} packing tasks")
    if any(not isinstance(value, str) or not PACKING_ID.fullmatch(value) for value in values):
        raise Invalid("Each packing task needs a SHA-256 id")
    return sorted(set(values))


def packing_changes(values):
    """A checked per-task patch: absent tasks are left alone, False clears one task."""
    if not isinstance(values, dict):
        raise Invalid("Packing changes must map task ids to true or false")
    packing_ids(list(values))
    if any(not isinstance(value, bool) for value in values.values()):
        raise Invalid("Each packing tick must be true or false")
    return dict(sorted(values.items()))


def mode(value):
    if value not in RUN_MODES:
        raise Invalid(f"mode must be one of: {', '.join(RUN_MODES)}")
    return value


def by_name(value):
    """The name recorded as who set the mode: text with no control characters."""
    if not isinstance(value, str) or not value.strip() or CONTROL.search(value):
        raise Invalid("by_name must be a name (text with no control characters)")
    return value


def since(value):
    """When the mode was set, for the import from the old file: None (now), or a datetime or
    ISO text, as an aware datetime. A time without an offset is read in this PC's local time,
    by both stores (PostgreSQL would otherwise read it in its own TimeZone setting)."""
    if value is None:
        return None
    try:
        when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise Invalid("since must be an ISO date and time") from None
    return when if when.tzinfo is not None else when.astimezone()


def jsonb_time(value):
    """An aware datetime as PostgreSQL's to_jsonb writes a timestamptz (what the audit trail's
    rows hold): local time, the fraction of a second without trailing zeros, offset +hh:mm.
    This assumes the server's TimeZone is this PC's, as it is when both run here; nothing
    should rely on the exact text (compare datetime.fromisoformat of it instead)."""
    text = value.astimezone().isoformat()
    head, sep, rest = text.partition(".")
    if sep:
        fraction, offset = rest[:6].rstrip("0"), rest[6:]
        text = f"{head}.{fraction}{offset}" if fraction else head + offset
    return text


# ------------------------------------------------------------------ play records

def record_bytes(record):
    """A play record as its file was written (api/play_records._bytes): sorted keys, indent 2,
    a trailing newline, UTF-8."""
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def record_sha(record):
    """A play record's concurrency token, sha256 of record_bytes(record): what the page sends
    back as expected_sha (api/play_records._hash(_bytes(record)))."""
    return hashlib.sha256(record_bytes(record)).hexdigest()


def play_kind(kind):
    if kind not in PLAY_KINDS:
        raise Invalid(f"kind must be one of: {', '.join(PLAY_KINDS)}")
    return kind


def play_id(value):
    if not isinstance(value, str) or not PLAY_ID.fullmatch(value):
        raise Invalid("Bad play record ID")
    return value


def split_record(kind, record):
    """A record dict checked and split into (header, content, deck_ids): header the PLAY_HEADER
    fields, content the kind's own (legacy games: date, sides, result, notes;
    pods: explicit mode/game_version, seats and recording space; sideboards:
    deck, opponent, out, in, after, notes), deck_ids the actual decks it involves.
    Pod opponent labels never become deck references. The envelope stays v1.
    """
    if not isinstance(record, dict) or not set(PLAY_HEADER) <= set(record):
        raise Invalid(f"A play record needs {', '.join(PLAY_HEADER)}")
    header = {key: record[key] for key in PLAY_HEADER}
    content = {key: value for key, value in record.items() if key not in PLAY_HEADER}
    if header["version"] != 1 or type(header["version"]) is not int:
        raise Invalid("A play record's version must be 1")
    play_id(header["id"])
    if header["kind"] != kind:
        raise Invalid("The record's kind doesn't match")
    if type(header["revision"]) is not int or header["revision"] < 1:
        raise Invalid("A play record's revision must be a whole number from 1")
    for key in ("created_on", "updated_on"):
        try:
            datetime.fromisoformat(header[key])
        except (TypeError, ValueError):
            raise Invalid(f"A play record's {key} must be an ISO date and time") from None
    by = header["updated_by"]
    if not isinstance(by, str) or not 1 <= len(by) <= MAX_UPDATED_BY or CONTROL.search(by):
        raise Invalid(f"A play record's updated_by must be 1 to {MAX_UPDATED_BY} characters, "
                      "with no control characters")
    deck_ids = record_deck_ids(kind, content)
    try:
        record_bytes(content)
    except (TypeError, ValueError):
        raise Invalid("A play record must be plain JSON") from None
    _check_jsonb(content)
    return header, content, deck_ids


def _check_jsonb(value):
    """Invalid when jsonb wouldn't give value back exactly, which would change the record's
    hash after a round trip: a float (jsonb turns 1e16 into 10000000000000000 and -0.0 into 0)
    or a NUL in text (jsonb refuses it). The play records hold only whole numbers."""
    if isinstance(value, float):
        raise Invalid("A play record can't hold numbers with a fraction or exponent")
    if isinstance(value, str):
        if "\x00" in value:
            raise Invalid("A play record's text can't hold a NUL character")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_jsonb(key)
            _check_jsonb(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_jsonb(item)


def rebuild(header, content):
    """The record dict from its stored parts, as today's file holds it."""
    return {**content, **{key: header[key] for key in PLAY_HEADER}}


# ------------------------------------------------------------------ writes and the audit trail

def check_write(actor, message, reason=None):
    """The actor, message and reason of a write, as conn.change() would store them (actor id
    and message stripped, a blank reason as None). ValueError for a missing actor or message:
    that's a mistake in the calling code, not the user's."""
    from . import Actor
    if not isinstance(actor, Actor):
        raise ValueError("a write needs a state.Actor")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("a write needs a message saying what it does")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        reason = None
    return actor.id.strip(), message.strip(), reason


def page_args(before, limit):
    """activity()'s before (None, or a change set id above 0) and limit (1 to MAX_LIMIT)."""
    if before is not None and (type(before) is not int or before < 1):
        raise Invalid("before must be a change set ID (a whole number above 0)")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise Invalid(f"limit must be a whole number from 1 to {MAX_LIMIT}")
    return before, limit


def inventory_scope(spec):
    """activity()'s inventory argument checked: {"tables": the inventory's tables, "items": those
    of them whose rows are counted rather than listed, "spaces": the spaces whose rows the viewer
    may see (None: every space, orphans included), "cap": the most rows listed per change set}."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) != {"tables", "items", "spaces", "cap"}:
        raise ValueError("inventory needs exactly tables, items, spaces and cap")
    if type(spec["cap"]) is not int or spec["cap"] < 1:
        raise ValueError("the inventory's cap must be a whole number above 0")
    spaces = spec["spaces"]
    return {"tables": tuple(spec["tables"]), "items": tuple(spec["items"]),
            "spaces": None if spaces is None else tuple(spaces), "cap": spec["cap"]}


def _space(row):
    for record in (row.get("after"), row.get("before"), row.get("key")):
        if isinstance(record, dict) and isinstance(record.get("space_id"), str):
            return record["space_id"]
    return "home"


def _only_position(row):
    before, after = row.get("before"), row.get("after")
    if row.get("op") != "UPDATE" or not isinstance(before, dict) or not isinstance(after, dict):
        return False
    return {k: v for k, v in before.items() if k != "position"} == {k: v for k, v in after.items() if k != "position"}


KIT_FIELDS = ("sleeves", "deck_box")    # an intact product's accessories (api/activity.py's privacy rule)
ACCESSORY_TABLE = "accessory"           # phase 4's accessories rows: every change to one is private
DECK_TABLE = "deck"                     # phase 4's deck rows: kit_version counts their kit changes
KIT_VERSION = "kit_version"


def kit_changed(row):
    """True for a row whose change may say whose sleeves or deck boxes went where (api/activity.py's
    privacy rule): an update of a product_status row that changes its sleeves or deck box (blank
    and missing alike); any change to an accessory row (phase 4); and a deck row whose
    kit_version differs before and after (phase 4: the deck table never holds the Sleeves and Deck
    box values themselves, only this count of their changes; missing counts as 0, so a deck made
    or deleted with a kit is one too)."""
    table, op = row.get("table"), row.get("op")
    before, after = row.get("before"), row.get("after")
    before, after = (before if isinstance(before, dict) else {}), (after if isinstance(after, dict) else {})
    if table == ACCESSORY_TABLE:
        return True
    if table == DECK_TABLE:
        return (before.get(KIT_VERSION) or 0) != (after.get(KIT_VERSION) or 0)
    if table != "product_status" or op != "UPDATE":
        return False
    return any((before.get(key) or "") != (after.get(key) or "") for key in KIT_FIELDS)


def inventory_rows(change, spec):
    """change (a raw audit change set, rows oldest first) with its inventory rows as a viewer of
    spec (inventory_scope) gets them, as both stores give it (the database does this in SQL):
    rows of spec's tables in a space the viewer can't see are left out, and so are updates that
    only moved a row (its position); the item tables' rows become "groups" ([{table, op, key,
    count}], key the row key without its position, in the order each group's first row came);
    the other inventory rows are listed up to spec's cap, oldest first, and "more" counts the
    visible ones past it, "past" what they did to the quantities ({table: {"added", "removed",
    "unknown"}}: copies added and removed, and rows added or removed whose quantity can't be
    read: quantity_delta), so a headline can say how many cards changed without them. "total" is
    how many rows the change set has in all, hidden ones included, and "kit" whether any of
    them, hidden or past the cap, changed an intact product's sleeves or deck box, any accessory
    row or a deck's kit (kit_changed)."""
    tables, items, spaces, cap = spec["tables"], spec["items"], spec["spaces"], spec["cap"]
    rows, groups, listed, more, past = [], {}, 0, 0, {}
    raw = change.get("rows") or []
    for row in raw:
        if row.get("table") not in tables:
            rows.append(row)
            continue
        if _only_position(row) or (spaces is not None and _space(row) not in spaces):
            continue
        if row["table"] in items:
            key = {k: v for k, v in (row.get("key") or {}).items() if k != "position"}
            found = groups.setdefault((row["table"], row.get("op"), json.dumps(key, sort_keys=True)),
                                      {"table": row["table"], "op": row.get("op"), "key": key, "count": 0})
            found["count"] += 1
        elif listed < cap:
            rows.append(row)
            listed += 1
        else:
            more += 1
            counted = past.setdefault(row["table"], {"added": 0, "removed": 0, "unknown": 0})
            delta = quantity_delta(row)
            if delta is None:
                counted["unknown"] += row.get("op") != "UPDATE"
            elif delta > 0:
                counted["added"] += delta
            else:
                counted["removed"] -= delta
    return {**change, "rows": rows, "groups": list(groups.values()), "more": more, "past": past,
            "total": len(raw), "kit": any(kit_changed(row) for row in raw)}


_WHOLE = re.compile(r"\s*[-+]?[0-9]+\s*")


def _quantity(record):
    """A row's quantity as a whole number (a JSON number, truncated, or a string of digits), or None."""
    value = (record or {}).get("quantity") if isinstance(record, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and _WHOLE.fullmatch(value):
        return int(value)
    return None


def quantity_delta(row):
    """How many copies an inventory row's change added (negative: removed), or None when its
    quantity can't be read: an INSERT's quantity, a DELETE's taken away, an UPDATE's difference.
    The database works out the same in SQL (state/pg.py's _INVENTORY_ROWS)."""
    before, after = _quantity(row.get("before")), _quantity(row.get("after"))
    if row.get("op") == "INSERT":
        return after
    if row.get("op") == "DELETE":
        return None if before is None else -before
    return None if before is None or after is None else after - before


def activity_page(fetch, before, limit, visible=None):
    """One page of the audit trail, newest first, shared by both stores.

    fetch(cursor, n): up to n change sets (dicts) with id below cursor (None: from the newest),
    newest first. visible(change): the change as this viewer may see it, or None to leave it
    out (None: every change counts). Collects up to limit visible changes, examining at most
    SCAN_CAP change sets. Returns {"changes": [...], "next": id}, next being the last id
    examined (pass it as before for the next page), or None when the trail has no more."""
    found, examined, cursor = [], 0, before
    while examined < SCAN_CAP:
        want = limit - len(found) if visible is None else max(50, 2 * (limit - len(found)))
        want = min(want, SCAN_CAP - examined)
        batch = fetch(cursor, want + 1)
        more = len(batch) > want
        batch = batch[:want]
        for i, change in enumerate(batch):
            examined += 1
            cursor = change["id"]
            shown = change if visible is None else visible(change)
            if shown is not None:
                found.append(shown)
            if len(found) >= limit:
                last = i == len(batch) - 1 and not more
                return {"changes": found, "next": None if last else cursor}
        if not more:
            return {"changes": found, "next": None}
    return {"changes": found, "next": cursor}
