"""Where Build decks' cards are in storage (E8-S22): the plan's "storage_locations",

    {"ready": bool, "cards": {name: ["Row 2, B", "Binder"]}}

for each card the plan pulls from storage or puts back, the distinct storage locations recorded
on home's collection rows of that card (any printing: the plan allocates copies by name), in
the collection's row order. A card none of whose rows has a location isn't listed. ready is
False while the database lacks migration 0016 (the page then says locations aren't available).
The plan is home's and only home's people see it (assembly_view's guard), so these are home's
own rows. Nothing here changes the plan's counts or ticks. The lookup is storage_places.by_name,
which Where these go shares (E8-S27).

"storage_order" (E8-S25 slice 5) is how home's loose cards are ordered, from its storage setup:
the default container's (where cards with no location go)

    {"rule": "colour-type" | "set" | "name" | "none", "container": its name,
     "sleeved": bool (slice 6: Put back says "unsleeved" only when it's false),
     "sections": {group: section} (slice 7, colour-type only and only when its holds map groups:
                 the dividers then start with the section, "Row 1 · Creatures · White"),
     "printings": {name: [set, collector_number]}}       (rule "set" only)

or None when home has no default container. Build decks' second card order follows it: today's
colour-and-type dividers for colour-type, set then collector number for set, and only Name for
name and none. A set-ordered card is placed by the printing of home's copy filed there: a row whose
location is in that container, else one with no location, else its first row.
"""
from decklab.lib import spaces, storage_setting
from decklab.lib.inventory import rules
from decklab.lib.state import space_storage

from .storage_places import _named, by_name


def _printings(inv, record, ident, wanted):
    """{name: [set, number]} for the wanted names, by the preference in the module docstring."""
    found = inv.locations_of(spaces.HOME) if inv.locations_ready else {}
    best = {}
    for row in inv.collection(spaces.HOME).rows:
        try:
            key = rules.ident(row)
        except KeyError:
            continue
        written = row.text("name")
        name = written if written in wanted else _named(written)
        if name not in wanted:
            continue
        place = found.get(key, "")
        rank = 0 if place and space_storage.match(record, place) == ident else 1 if not place else 2
        if name not in best or rank < best[name][0]:
            best[name] = (rank, [key[0], key[1]])
    return {name: printing for name, (_, printing) in best.items()}


def storage_order(inv, wanted):
    """The plan's "storage_order" (the module docstring)."""
    record = storage_setting.current(spaces.HOME, seed=False)["storage"]
    box = space_storage.container(record, record.get("default"))
    if box is None:
        return None
    answer = {"rule": box["order"], "container": box["name"], "sleeved": bool(box.get("sleeved"))}
    sections = space_storage.group_sections(box)
    if sections:
        answer["sections"] = sections
    if box["order"] == "set":
        answer["printings"] = _printings(inv, record, box["id"], wanted)
    return answer


def annotate(answer, inv):
    """answer with "storage_locations" (see the module docstring)."""
    wanted = {row["name"] for row in answer.get("rows", []) if row.get("from_storage")}
    for deck in answer.get("decks", []):
        wanted.update(item["name"] for item in deck.get("returns", []))
    answer["storage_locations"] = {"ready": bool(inv.locations_ready), "cards": by_name(inv, spaces.HOME, wanted)}
    answer["storage_order"] = storage_order(inv, wanted)
    return answer
