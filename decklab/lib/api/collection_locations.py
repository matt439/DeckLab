"""The Collection page's storage locations (E8-S22) and the storage box's count (E8-S19), kept
apart from the rows like their prices and storage counts, in every answer that sends rows
(collection_edit._extras):

    "locations":   {"ready", "rows": {"set|number|finish": "Row 2, B"}}
    "storage_box": {"cards", "capacity", "over", "not_counted", "elsewhere"} (home only), or None

locations' ready is False while the database lacks migration 0016: the page then shows locations
as unavailable and the card sheet can't set one (the rows and every other edit still work). The
rows' keys are collection_edit._picture_key's. Only the space's own people get these answers
(rows_view and every write check guard.require_sees_inventory / require_space_write first).

storage_box is the 4-row storage box's fill (E8-S19's first slice): home's copies not held by a
built deck or an intact product (the storage counts: collection_edit._storage), against
config.json's "storage_box_capacity" (CAPACITY, about 2,400 unsleeved cards, when it isn't set).
Basic lands aren't counted (their copies in decks aren't tracked), nor (as "elsewhere") a row's
free copies whose recorded location isn't one of the box's rows ("Binder": in_box), and a count
that can't be worked out (the pool can't be read) is None rather than a guess.
"""
import re

from decklab.lib import config, inventory, spaces
from decklab.lib.inventory import rules

from .common import ApiError

CAPACITY = 2400
BOX_ROW = re.compile(r"row\s*\d", re.IGNORECASE)   # "Row 2, B", "row3": a place in the storage box


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
    """{"ready", "rows"} of a space's storage locations (see the module docstring); key words a
    row's identity key as the page does."""
    inv = inventory.current()
    found = inv.locations_of(space)
    return {"ready": bool(inv.locations_ready),
            "rows": {key({"set": k[0], "collector_number": k[1], "finish": k[2]}): text
                     for k, text in sorted(found.items())}}


def capacity():
    """config.json's storage_box_capacity when it's a whole number from 1 to 100,000, else CAPACITY."""
    value = config.load().get("storage_box_capacity")
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100_000:
        return value
    return CAPACITY


def in_box(location):
    """Whether a row's recorded location puts it in the storage box: none recorded (the box is
    where unsleeved cards go), or one starting with a box row ("Row 2, B")."""
    return not location or BOX_ROW.match(location) is not None


def storage_box(space, rows, storage, key):
    """The storage box's count (see the module docstring), or None outside home or when the
    storage counts couldn't be worked out."""
    if space != spaces.HOME or storage.get("error"):
        return None
    counts = storage.get("rows") or {}
    found = inventory.current().locations_of(space)
    cards = not_counted = elsewhere = 0
    for row in rows:
        held = counts.get(key(row), {})
        copies = int(row["quantity"])
        if "held" in held and held["held"] is None:          # a basic land: its copies in decks aren't known
            not_counted += copies
            continue
        free = max(0, copies - (held.get("held") or 0))
        if in_box(found.get((row["set"], row["collector_number"], row["finish"]), "")):
            cards += free
        else:
            elsewhere += free
    size = capacity()
    return {"cards": cards, "capacity": size, "over": cards > size, "not_counted": not_counted, "elsewhere": elsewhere}
