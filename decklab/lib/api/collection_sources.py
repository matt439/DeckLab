"""Visible saved-list printing hints beside Collection storage counts.

These are ``listed_holders``, not verified physical-printing assignments. The existing
``held`` and ``guess`` allocation stays unchanged. Hidden holders, cheapest-printing
remainders, inconsistent physical demand and competing hints remain ``unattributed``.
The projection consumes the already-loaded pool, canonical rows and caller's visibility
predicate. It calls no data loaders and changes none of its inputs.
"""
from collections import Counter

from decklab.lib.state import Unavailable
from .inventory_views import named_holder


# Only the visibility read boundary is optional; malformed projection inputs still raise.
VISIBILITY_READ_ERRORS = (OSError, RuntimeError, Unavailable)


def anonymous(storage):
    """Keep allocation counts when optional source visibility cannot be established."""
    return {**storage, "rows": {key: {**value, "listed_holders": [],
        "unattributed": None if storage.get("error") else value.get("held")}
        for key, value in storage.get("rows", {}).items()}}


def _row_key(row):
    return "|".join(str(row.get(key) or "").lower() for key in ("set", "collector_number", "finish"))


def _evidence(holder):
    """A holder's valid list hints and per-name totals, before any attribution."""
    hints, totals = Counter(), Counter()
    valid = not holder.standin_warnings and holder.printing_version in ("target", "owned")
    for key, quantity in holder.printings.items():
        if not isinstance(key, tuple) or len(key) != 4 or not isinstance(quantity, int) \
                or isinstance(quantity, bool) or quantity < 0:
            valid = False
            continue
        if quantity:
            hints[key] += quantity
            totals[key[0]] += quantity
    return holder, hints, totals, valid


def annotate(storage, holders, by_name, *, sees, records):
    """Clone storage with visible uncontested list hints and an anonymous remainder.

    ``by_name`` is _storage's existing canonical-name -> rows grouping. Each output row
    retains held/guess, with listed_holders [{id, title, quantity, version}] and unattributed
    (held minus the visible listed quantities, None when allocation isn't tracked).
    No hidden identity, holder count, kind or hint provenance is exposed.

    A holder/name is ineligible when installed stand-ins affect that name, its list
    hints exceed its physical card count, or its stand-in recipe has warnings. If a
    name's physical demand exceeds ownership, or the claims for a row exceed its
    allocated/owned capacity, withhold every affected name rather
    than choose a winner. Cheapest allocations never acquire a holder's identity.
    Unavailable visibility reads discard all names while preserving the allocation.
    """
    projected = anonymous(storage)
    if storage.get("error"):
        return projected
    evidence = [_evidence(holder) for holder in holders]
    visible = {}

    def may_name(holder):
        if not isinstance(holder.id, str) or not holder.id or not isinstance(holder.title, str):
            return False
        if holder.id not in visible:
            try:
                visible[holder.id] = bool(named_holder(holder.id, sees, records))
            except VISIBILITY_READ_ERRORS:
                return None            # No names from a projection with an unavailable visibility read.
        return visible[holder.id]

    for name, rows in by_name.items():
        if sum(holder.cards.get(name, 0) for holder, _, _, _ in evidence) > sum(int(row["quantity"]) for row in rows):
            continue                   # Capped legacy counts cannot choose which holder's demand fits.
        for row in rows:
            entry = projected["rows"].get(_row_key(row))
            if entry is None or entry.get("held") is None or entry["held"] <= 0:
                continue
            key = (name, row["set"].lower(), row["collector_number"], row["finish"] or "nonfoil")
            # Ineligible hints still participate in conflict detection: ignoring one
            # must not assign its potentially competing copy to a different holder.
            claimed = sum(hints[key] for _, hints, _, _ in evidence)
            if claimed > entry["held"] or claimed > int(row["quantity"]):
                continue
            listed = []
            for holder, hints, totals, valid in evidence:
                quantity = hints[key]
                physical = holder.cards.get(name, 0)
                if not quantity or not valid or name in holder.standin_names or physical <= 0 or totals[name] > physical:
                    continue
                allowed = may_name(holder)
                if allowed is None:
                    return anonymous(storage)   # Discard any earlier names; retain every held/guess count.
                if allowed:
                    listed.append({"id": holder.id, "title": holder.title, "quantity": quantity,
                                   "version": holder.printing_version})
            listed.sort(key=lambda holder: holder["id"])
            entry["listed_holders"] = listed
            entry["unattributed"] = entry["held"] - sum(holder["quantity"] for holder in listed)
    return projected
