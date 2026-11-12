"""Where Build decks' cards are in storage (E8-S22): the plan's "storage_locations",

    {"ready": bool, "cards": {name: ["Row 2, B", "Binder"]}}

for each card the plan pulls from storage or puts back, the distinct storage locations recorded
on home's collection rows of that card (any printing: the plan allocates copies by name), in
the collection's row order. A card none of whose rows has a location isn't listed. ready is
False while the database lacks migration 0016 (the page then says locations aren't available).
The plan is home's and only home's people see it (assembly_view's guard), so these are home's
own rows. Nothing here changes the plan's counts or ticks. The lookup is storage_places.by_name,
which Where these go shares (E8-S27).
"""
from decklab.lib import spaces

from .storage_places import by_name


def annotate(answer, inv):
    """answer with "storage_locations" (see the module docstring)."""
    wanted = {row["name"] for row in answer.get("rows", []) if row.get("from_storage")}
    for deck in answer.get("decks", []):
        wanted.update(item["name"] for item in deck.get("returns", []))
    answer["storage_locations"] = {"ready": bool(inv.locations_ready), "cards": by_name(inv, spaces.HOME, wanted)}
    return answer
