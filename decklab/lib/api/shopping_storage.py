"""Shopping's storage fill (E8-S25 slice 7): how full each of home's containers with a capacity is
now, and how full it would be once the pending orders arrive, for a note under On the way.

GET /api/shopping's answer gets "storage_fill":

    {"status": "ready" | "partial",
     "containers": [{"id", "name", "kind", "capacity", "now", "incoming", "after", "over_now", "over_after"}],
     "default": the name of the container cards with no location go to, or None,
     "unknown_sources": pending sources whose contents couldn't be verified (not counted),
     "pending_products": pending products (not counted: intact or broken up is chosen at receipt),
     "tokens_excluded": whether pending token cards were left out}

Nothing here is worked out again: "now" is the Card list's own count (collection_locations.storage_setup
over collection_edit's rows, prices and copies in decks), and "incoming" the Card list's pending-delivery
scenario's routing (collection_forecast.build's by_container: each known loose card copy goes to the
container its printing's recorded location matches, else the default one; basic lands, products and
token cards excluded). It's an estimate, never a placement, a reservation or a write.

Only for home-record readers (Shopping's guard already refused anyone else; this checks again, and
collection_forecast.build checks once more), and only home's containers, never another space's. It's
left out when home has no container with a capacity, nothing is pending, the copies in decks or the
routing can't be worked out (an unreadable location source, an unverified order record, the work
limit), or the snapshot is stale: an optional note never fails Shopping.
"""
from decklab.lib import spaces

from . import common, guard


def gather():
    """The storage_fill answer (the module docstring), or None."""
    from . import collection_edit as ce
    from . import collection_forecast
    from . import collection_locations as places
    view = places.setup_view(spaces.HOME)
    record = view["storage"]
    if not any(c["capacity"] is not None for c in record["containers"]):
        return None
    rows, _sha = ce._read(spaces.HOME)
    shown = ce._rows_json(rows)
    storage = ce._storage(spaces.HOME, shown, ce._prices(shown))
    setup = places.storage_setup(spaces.HOME, shown, storage, ce._picture_key, view)
    box = places.storage_box(spaces.HOME, shown, storage, ce._picture_key, view)
    forecast = collection_forecast.build(spaces.HOME, shown, box, record)
    if not forecast or forecast.get("status") not in ("ready", "partial") or forecast.get("stale") \
            or forecast.get("box_candidates") is None or not isinstance(forecast.get("by_container"), dict):
        return None
    if not forecast["sources"] and not forecast["omitted_sources"]:
        return None                     # nothing on the way
    incoming = forecast["by_container"]
    containers = []
    for c in setup["containers"]:
        if c["capacity"] is None or c["cards"] is None:
            continue
        coming = incoming.get(c["id"], 0)
        after = c["cards"] + coming
        containers.append({"id": c["id"], "name": c["name"], "kind": c["kind"], "capacity": c["capacity"],
                           "now": c["cards"], "incoming": coming, "after": after,
                           "over_now": c["cards"] > c["capacity"], "over_after": after > c["capacity"]})
    if not containers:
        return None
    default = next((c["name"] for c in record["containers"] if c["id"] == record.get("default")), None)
    tokens = forecast["tokens_excluded"]
    return {"status": forecast["status"], "containers": containers, "default": default,
            "unknown_sources": forecast["unknown_sources"],
            "pending_products": forecast["pending_products"]["count"],
            "tokens_excluded": bool(tokens["known_cards"] or tokens["unknown_components"])}


def enrich(answer):
    """answer["storage_fill"] for home-record readers only; left out otherwise or on any failure."""
    try:
        if not guard.sees_home_records() or not guard.sees_inventory(spaces.HOME):
            return answer
        fill = gather()
    except Exception as error:      # noqa: BLE001 - optional evidence: Shopping still answers without it
        common._log(f"Shopping's storage fill could not be worked out: {type(error).__name__}")
        return answer
    if fill is not None:
        answer["storage_fill"] = fill
    return answer
