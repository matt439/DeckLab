"""Where Build decks' cards are in storage (E8-S22): the plan's "storage_locations",

    {"ready": bool, "cards": {name: ["Row 2, B", "Binder"]}}

for each card the plan pulls from storage or puts back, the distinct storage locations recorded
on home's collection rows of that card (any printing: the plan allocates copies by name), in
the collection's row order. A card none of whose rows has a location isn't listed. ready is
False while the database lacks migration 0016 (the page then says locations aren't available).
The plan is home's and only home's people see it (assembly_view's guard), so these are home's
own rows. Nothing here changes the plan's counts or ticks.
"""
from decklab.lib import cards, spaces
from decklab.lib.inventory import rules


def _named(name):
    try:
        return cards.resolve(name) or name
    except RuntimeError:            # the card index went away meanwhile: the name as written
        return name


def annotate(answer, inv):
    """answer with "storage_locations" (see the module docstring)."""
    wanted = {row["name"] for row in answer.get("rows", []) if row.get("from_storage")}
    for deck in answer.get("decks", []):
        wanted.update(item["name"] for item in deck.get("returns", []))
    found = inv.locations_of(spaces.HOME)
    by_name = {}
    if wanted and found:
        for row in inv.collection(spaces.HOME).rows:
            try:
                key = rules.ident(row)
            except KeyError:
                continue
            place = found.get(key)
            name = _named(row.text("name"))
            if place and name in wanted and place not in by_name.setdefault(name, []):
                by_name[name].append(place)
    answer["storage_locations"] = {"ready": bool(inv.locations_ready), "cards": by_name}
    return answer
