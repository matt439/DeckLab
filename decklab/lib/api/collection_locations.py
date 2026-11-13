"""The Collection page's storage locations (E8-S22) and the storage box's count (E8-S19), kept
apart from the rows like their prices and storage counts, in every answer that sends rows
(collection_edit._extras):

    "locations":   {"ready", "sha256", "rows": {"set|number|finish": "Row 2, B"}}
    "storage_box": {"cards", "capacity", "over", "not_counted", "elsewhere"} (home only), or None
    "storage_setup": {"source", "revision", "default", "containers", "elsewhere", "unplaced",
                      "not_counted", "suggestions"} (storage_setup(): every space, E8-S25)

locations' ready is False while the database lacks migration 0016: the page then shows locations
as unavailable and the card sheet can't set one (the rows and every other edit still work). The
rows' keys are collection_edit._picture_key's. Only the space's own people get these answers
(rows_view and every write check guard.require_sees_inventory / require_space_write first).

Both counts follow the space's storage setup (E8-S25, lib/storage_setting.py): its containers,
each row's free copies (not held by a built deck or an intact product: collection_edit._storage)
going to the container its recorded location matches (state/space_storage.match), or with none
recorded to the default container. With nothing saved, home has its built-in 4-row storage box
(capacity config.json's "storage_box_capacity", CAPACITY when it isn't set) and any other space
no containers. storage_box is home's default container's fill (E8-S19's first slice, kept for the
page's older code and the pending scenario's baseline). Basic lands aren't counted (their copies
in decks aren't tracked), and a count that can't be worked out (the pool can't be read) is None
rather than a guess.
"""
from decklab.lib import inventory, spaces, storage_setting
from decklab.lib.inventory import ops_collection as ops, rules
from decklab.lib.state import space_storage

from . import common, guard
from .common import ApiError

CAPACITY = space_storage.BUILTIN_CAPACITY      # home's built-in box when storage_box_capacity isn't set


def location_input(value):
    """A request's "location": None when it's left out, else the cleaned text ("" clears it).
    ApiError 400 for one rules.clean_location refuses, or 409 while migration 0016 is missing and
    the location isn't blank."""
    if value is None:
        return None
    try:
        text = rules.clean_location(value)
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    if text and not inventory.current().locations_ready:
        raise ApiError(409, rules.LOCATION_REQUIRED)
    return text


def locations(space, key):
    """Locations and their independent receipt; an invalid source has no writable receipt.

    Keep the page's collection rows readable, but do not describe an unreadable location
    source as an empty one: its explanation disables batch writes until it can be repaired.
    """
    inv = inventory.current()
    found = inv.locations_of(space)
    answer = {"ready": bool(inv.locations_ready),
              "rows": {key({"set": k[0], "collector_number": k[1], "finish": k[2]}): text
                       for k, text in sorted(found.items())}}
    try:
        answer["sha256"] = ops.locations_sha256_of(inv, space)
    except ops.Unreadable as e:
        answer.update(sha256=None, error=common._public(e))
    return answer


def _bulk_conflict(space, message):
    """One fresh snapshot for a refused batch's rows, locations and both review receipts."""
    from . import collection_edit as ce
    with common.state_errors():
        fresh = inventory.backend().load()
    with inventory.pinned(fresh):
        rows, sha = ce._view(fresh.collection(space))
        shown = ce._rows_json(rows)
        return ApiError(409, message, sha256=sha, rows=shown, **ce._extras(space, shown))


def bulk_set(body):
    """POST /api/collection/locations/bulk: assign or explicitly clear exact reviewed rows.

    Required: profile, keys, sha256, locations_sha256 and location (text, "" clears).
    space is optional. Both receipts and every named printing are rechecked by the one
    location-only operation under the write lock, including when nothing would change.
    """
    from . import collection_edit as ce
    from .settings import _web_actor, _writer
    data = common._parse_body(body, ce.MAX_BULK_BODY)
    profile = _writer(data)
    space = ce.space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    common._keys(data, ("profile", "sha256", "locations_sha256", "keys", "location"), ("space",))
    sha = ce._request_sha(data["sha256"])
    location_sha = data["locations_sha256"]
    if not isinstance(location_sha, str) or not common._SHA_RE.fullmatch(location_sha):
        raise ApiError(400, "locations_sha256 must be the 64-character hash the locations answer gave")
    keys = ce._bulk_keys(data["keys"])
    if not isinstance(data["location"], str):
        raise ApiError(400, "location must be text; use an empty string to clear it")
    try:
        wanted = rules.clean_location(data["location"])
    except ValueError as e:
        raise ApiError(400, str(e)) from None
    op = inventory.Op("collection.locations", {"space": space, "sha256": sha,
                      "locations_sha256": location_sha, "keys": keys, "location": wanted, "whose": ce._whose(space)})
    try:
        sheet, summary = ce._apply(space, op, _web_actor(profile),
                                   message=f"set storage locations in {ce._whose(space)}")
    except ApiError as e:
        if e.status == 409:
            raise _bulk_conflict(space, e.message) from None
        raise
    rows, now = ce._view(sheet)
    shown = ce._rows_json(rows)
    return {"ok": True, "sha256": now, "rows": shown, **ce._extras(space, shown),
            "changed": summary.counts["changed"], "stale_tables": []}


def capacity():
    """Home's built-in box's capacity: config.json's storage_box_capacity when it's a whole number
    from 1 to 100,000, else CAPACITY (only a seed until home saves its storage setup, Q6)."""
    return storage_setting.capacity_seed() or CAPACITY


def setup_view(space, *, seed=True):
    """The space's storage setup as it applies now (lib/storage_setting.current: never raises)."""
    return storage_setting.current(space, seed=seed)


def box_id(record):
    """The id of the container storage_box describes: the default one, when it has a capacity."""
    box = space_storage.container(record, (record or {}).get("default"))
    return box["id"] if box is not None and box["capacity"] is not None else None


def in_box(location, record=None):
    """Whether a recorded location puts a row in home's storage box (box_id's container of record,
    home's setup read when not given), by the setting's one rule (space_storage.match): none
    recorded, or one starting with one of its sections ("Row 2, B"). Matt, 2026-11-13 (Q3): the
    built-in box's sections are Row 1 to Row 4 only, so "Row 5" and "row3" are elsewhere."""
    if record is None:
        record = setup_view(spaces.HOME)["storage"]
    ident = box_id(record)
    return ident is not None and space_storage.match(record, location) == ident


def _counts(space, rows, storage, key, record):
    """{container id: free copies, "_elsewhere": a location matching no container, "_unplaced":
    no location and no default container, "_basic": basic lands (not counted)}; None when the
    copies in decks couldn't be worked out."""
    if storage.get("error"):
        return None
    counts = storage.get("rows") or {}
    found = inventory.current().locations_of(space)
    out = {c["id"]: 0 for c in record["containers"]}
    out.update(_elsewhere=0, _unplaced=0, _basic=0)
    for row in rows:
        held = counts.get(key(row), {})
        copies = int(row["quantity"])
        if "held" in held and held["held"] is None:          # a basic land: its copies in decks aren't known
            out["_basic"] += copies
            continue
        free = max(0, copies - (held.get("held") or 0))
        location = found.get((row["set"], row["collector_number"], row["finish"]), "")
        ident = space_storage.match(record, location)
        if ident is not None:
            out[ident] += free
        elif location.strip():
            out["_elsewhere"] += free
        else:
            out["_unplaced"] += free
    return out


def storage_setup(space, rows, storage, key, view=None):
    """The rows answers' "storage_setup" (E8-S25): the space's containers with their counts.

        {"source": "saved" | "default" | "none", "revision", "default": container id or None,
         "containers": [{id, name, kind, capacity, sleeved, cards, over}], "elsewhere",
         "unplaced", "not_counted", "suggestions": the location suggestions, in order}

    cards and the totals are None when the copies in decks can't be worked out; over is None for
    a container without a capacity. Sections go only into suggestions."""
    view = view or setup_view(space)
    record = view["storage"]
    counts = _counts(space, rows, storage, key, record)
    containers = []
    for c in record["containers"]:
        cards = None if counts is None else counts[c["id"]]
        containers.append({"id": c["id"], "name": c["name"], "kind": c["kind"], "capacity": c["capacity"],
                           "sleeved": c["sleeved"], "cards": cards,
                           "over": None if cards is None or c["capacity"] is None else cards > c["capacity"]})
    totals = {name: None if counts is None else counts[key_] for name, key_ in
              (("elsewhere", "_elsewhere"), ("unplaced", "_unplaced"), ("not_counted", "_basic"))}
    return {"source": view["source"], "revision": view["revision"], "default": record["default"],
            "containers": containers, **totals, "suggestions": space_storage.suggestions(record)}


def storage_box(space, rows, storage, key, view=None):
    """The storage box's count (see the module docstring): home's default container, when it has a
    capacity, as {cards, capacity, over, not_counted, elsewhere (every other free copy)}; None
    outside home, without such a container, or when the storage counts couldn't be worked out."""
    if space != spaces.HOME or storage.get("error"):
        return None
    record = (view or setup_view(space))["storage"]
    ident = box_id(record)
    if ident is None:
        return None
    counts = _counts(space, rows, storage, key, record)
    cards, size = counts[ident], space_storage.container(record, ident)["capacity"]
    elsewhere = sum(n for name, n in counts.items() if name not in (ident, "_basic"))
    return {"cards": cards, "capacity": size, "over": cards > size, "not_counted": counts["_basic"],
            "elsewhere": elsewhere}
