"""Transient priorities for movable packing copies, never ownership or printing choices.

Keep every holder's existing copies. A preferred selected deck receives storage
and released surplus first; incoming copies retain the original selection order.
The normalized choices belong in the existing revision-bound plan receipt.
"""
from decklab.lib import cards, decks

from .common import ApiError

MAX_PREFERENCES = 1000


def normalize(selected, participants):
    """Return canonical selections and name -> selected recipient priorities.

    The caller has already resolved deck ids, versions and sideboard recipes.
    Validate all supplied names before dropping a valid choice whose recipient
    no longer needs it. Other harmless no-ops remain usable through supply changes.
    """
    by_id = {item["id"]: item for item in participants}
    output, priorities, seen, count = [], {}, set(), 0
    for choice in selected:
        result = {key: value for key, value in choice.items() if key != "prefer"}
        if "sideboard" in result:
            result["sideboard"] = dict(result["sideboard"])
        raw = choice.get("prefer", [])
        if not isinstance(raw, list):
            raise ApiError(400, "prefer must list exact card names for this selected deck.")
        count += len(raw)
        if count > MAX_PREFERENCES:
            raise ApiError(400, f"Choose at most {MAX_PREFERENCES} card priorities in one plan.")
        names = []
        for name in raw:
            if (not isinstance(name, str) or cards.resolve(name) != name
                    or decks.is_basic_land(name)):
                raise ApiError(400, "Choose exact nonbasic card names for packing priorities.")
            if name in seen:
                raise ApiError(400, "Choose only one preferred recipient for each card.")
            seen.add(name)
            participant = by_id[choice["id"]]
            if participant["need"][name] > 0:
                names.append(name)
                priorities[name] = choice["id"]
        if names:
            result["prefer"] = sorted(names)
        output.append(result)
    return output, priorities


def _marker_names(metadata):
    excluded = set()
    for meta in metadata:
        for source in ("configured", "choices", "raw", "installed", "rows"):
            for row in meta.get(source, []):
                excluded.add(row["for"])
                if row["using"] is not None:
                    excluded.add(row["using"])
    return excluded


def reject_markers(priorities, metadata):
    """The first priority control excludes every configured or installed marker name.

    Include inactive choices and installed mappings, not only mappings effective
    in this plan: a later allocation pass must not silently reassign a marker.
    """
    if not priorities:
        return
    if any(meta.get("invalid") for meta in metadata):
        raise ApiError(409, "Check the saved stand-ins before changing card priorities.")
    if _marker_names(metadata).intersection(priorities):
        raise ApiError(400, "Cards used by saved stand-ins keep their existing packing priority.")


def add_controls(plan, priorities, metadata):
    """Project safe current recipients without exposing inactive marker configuration."""
    if not plan["counts_confirmed"] or any(meta.get("invalid") for meta in metadata):
        return plan
    excluded = _marker_names(metadata)
    for row in plan["rows"]:
        if row["name"] in excluded or not row["waiting"] + row["missing"]:
            continue
        options, movable = [], 0
        for item in plan["decks"]:
            step = next((s for s in item["steps"] if s["name"] == row["name"]), None)
            if step is None:
                continue
            movable += step["storage"] + sum(t["quantity"] for t in step["transfers"])
            if step["need"] > step["keep"]:
                options.append(item["id"])
        if movable and len(options) >= 2:
            row["preference_options"] = options
            row["preferred"] = priorities.get(row["name"])
    return plan


def allocate(name, participants, storage, incoming, preferred=None):
    """Allocate one name without mutating the pool, participants or their counters.

    Steps and transfers retain original participant order, even when consumption
    of movable copies uses a preferred recipient first. Return quantities align
    with participants, including donor-only participants with no selected need.
    """
    released = [max(0, item["current"][name] - item["need"][name]) for item in participants]
    steps = []
    for item in participants:
        needed = item["need"][name]
        keep = min(needed, item["current"][name])
        steps.append({"name": name, "need": needed, "keep": keep, "storage": 0,
                      "transfers": [], "waiting": 0, "missing": needed - keep} if needed else None)
    order = sorted(range(len(participants)), key=lambda index: participants[index]["id"] != preferred)
    for index in order:
        step = steps[index]
        if step is None:
            continue
        pull = min(step["missing"], storage)
        storage -= pull
        step["storage"] = pull
        step["missing"] -= pull
        for donor_index, donor in enumerate(participants):
            moved = min(step["missing"], released[donor_index])
            if moved:
                released[donor_index] -= moved
                step["missing"] -= moved
                step["transfers"].append({"from": donor["id"], "from_title": donor["title"],
                                          "to": participants[index]["id"], "to_title": participants[index]["title"],
                                          "quantity": moved})
    for step in steps:
        if step is not None:
            wait = min(step["missing"], incoming)
            incoming -= wait
            step["waiting"] = wait
            step["missing"] -= wait
    return {"steps": steps, "returns": released,
            "transfers": [transfer for step in steps if step is not None for transfer in step["transfers"]]}
