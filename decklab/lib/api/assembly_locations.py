"""Where Build decks' cards are in storage (E8-S22): the plan's "storage_locations",

    {"ready": bool, "cards": {name: ["Row 2, B", "Binder"]}}

for each card the plan pulls from storage or puts back, including basic lands, the distinct
storage locations on home's collection rows of that card (any printing: the plan allocates copies by name), in
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
     "section_order": [section, ...] (the container's sections in physical order),
     "filed_sections": {name: section} (only for explicitly matched sections),
     "printings": {name: [set, collector_number]}}       (rule "set" only)

or None when home has no containers. Within each container the plan visits its sections in
physical order. A recorded section takes precedence over the section mapped to a card's type.
Within each section, colour-type uses colour/type dividers, set uses set then collector number,
and name and none use alphabetical order. With no sections or further containers to distinguish,
name and none offer only Name. A set-ordered card uses the printing filed in its container:
a row whose location is in that container, else one with no location, else its first row.

When home's setup has two or more containers, has no default, or some cards are filed elsewhere,
it also says which container each card is in,
so Build decks groups its tiles by container first and then by that container's own rule:

    {..., "containers": [{"id", "name", "order", "sleeved"}, ...],    (the setup's order)
          "placed": {name: container id, or None for "somewhere else"}}

A card is placed by its recorded locations (storage_places.by_name, in collection row
order): the container of the first one that belongs to a container (space_storage.match), so a card
whose copies are in two containers goes under the first in collection row order; else None when it
has locations but none belongs to a container; else, with none recorded, the default container.
"printings" then covers each card placed in a set-ordered container, by its copy filed in that
container. With every card placed in the sole default container neither field is needed.
"""
from decklab.lib import spaces, storage_setting
from decklab.lib.inventory import rules
from decklab.lib.state import space_storage

from .storage_places import _named, by_name


def _printings(inv, record, filed):
    """{name: [set, number]}, preferring the copy in the card's chosen set-ordered container."""
    found = inv.locations_of(spaces.HOME) if inv.locations_ready else {}
    best = {}
    for row in inv.collection(spaces.HOME).rows:
        try:
            key = rules.ident(row)
        except KeyError:
            continue
        written = row.text("name")
        name = written if written in filed else _named(written)
        if name not in filed:
            continue
        place = found.get(key, "")
        rank = 0 if place and space_storage.match(record, place) == filed[name] else 1 if not place else 2
        if name not in best or rank < best[name][0]:
            best[name] = (rank, [key[0], key[1]])
    return {name: printing for name, (_, printing) in best.items()}


def _container(container):
    """One container in storage_order's "containers": its id, name, order and sleeved, and its
    sections ({group: section}) when its rule maps groups (slice 7)."""
    entry = {"id": container["id"], "name": container["name"], "order": container["order"],
             "sleeved": bool(container.get("sleeved"))}
    sections = space_storage.group_sections(container)
    if container.get("sections"):
        entry["section_order"] = container["sections"]
    if sections:
        entry["sections"] = sections
    return entry


def storage_order(inv, wanted, places=None):
    """The plan's "storage_order" (the module docstring). places is by_name's answer for wanted,
    when the caller has it already."""
    record = storage_setting.current(spaces.HOME, seed=False)["storage"]
    containers = [_container(c) for c in record["containers"]]
    if not containers:
        return None
    default = record["default"]
    box = next((c for c in containers if c["id"] == default), None)
    answer = {"rule": "none", "container": None, "sleeved": False}
    if box is not None:
        answer.update(rule=box["order"], container=box["name"], sleeved=box["sleeved"])
        answer.update({k: box[k] for k in ("sections", "section_order") if k in box})
    if places is None:
        places = by_name(inv, spaces.HOME, wanted) if inv.locations_ready else {}
    placements = {name: space_storage.placed_section(record, places.get(name)) for name in sorted(wanted)}
    placed = {name: ident for name, (ident, _) in placements.items()}
    sections = {name: section for name, (_, section) in placements.items() if section is not None}
    if sections:
        answer["filed_sections"] = sections
    if len(containers) > 1 or box is None or any(ident != default for ident in placed.values()):
        answer["containers"] = containers
        answer["placed"] = placed
    by_set = {c["id"] for c in containers if c["order"] == "set"}
    filed = {name: ident for name, ident in placed.items() if ident in by_set}
    if filed:
        answer["printings"] = _printings(inv, record, filed)
    elif answer["rule"] == "set":
        answer["printings"] = {}
    return answer


def annotate(answer, inv):
    """answer with "storage_locations" (see the module docstring)."""
    wanted = {row["name"] for row in answer.get("rows", []) if row.get("from_storage")}
    for deck in answer.get("decks", []):
        wanted.update(item["name"] for item in deck.get("returns", []))
        wanted.update(item["name"] for item in deck.get("basics", []))
    places = by_name(inv, spaces.HOME, wanted)
    answer["storage_locations"] = {"ready": bool(inv.locations_ready), "cards": places}
    answer["storage_order"] = storage_order(inv, wanted, places)
    return answer
