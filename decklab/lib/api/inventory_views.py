"""Read-only pool projections when a collection is public independently of its decks.

The raw pool and audit trail remain complete. Only answers sent to the current viewer
lose order/product identities and the titles of decks they may not see.
"""
from collections import defaultdict

from decklab.lib import spaces
from . import guard


def named_holder(deck_id, sees, records=None):
    """Product names in inventory labels stay home's even when product decks are public."""
    records = guard.sees_home_records() if records is None else records
    return sees(deck_id) and (records or not (isinstance(deck_id, str) and deck_id.startswith("product/")))


def owned(result, p):
    """Redact a fresh owned-vs-needed JSON result before it leaves the server.

    p is the compared pool, needed because its in-use ids are authoritative; the raw
    comparison names holders only by title, which need not be unique.
    """
    if p is None:
        return result
    from .library import place_words, visible_place, visible_warnings
    sees, records = guard.deck_reader(), guard.sees_home_records()
    holders = defaultdict(list)
    for holder in p.in_use:
        holders[holder.title].append(holder)

    def names(items):
        shown = {}
        for title, quantity in items:
            matches = holders.get(title, [])
            visible = matches and all(named_holder(holder.id, sees, records) for holder in matches)
            title = title if visible else guard.hidden_deck(matches[0].id) if matches else "another deck"
            shown[title] = shown.get(title, 0) + quantity
        return list(shown.items())

    home_sources = getattr(p, "space", spaces.HOME) == spaces.HOME and not records
    for row in result["rows"]:
        row["in_use_elsewhere"] = names(row.get("in_use_elsewhere", []))
        labels = row["labels"]
        labels["in_use"] = names(labels.get("in_use", []))
        if home_sources:
            # Counts remain useful; no order id, product name, status or grouping by
            # shipment survives, in either the raw comparison or its display labels.
            row["on_the_way_from"] = [(None, row["on_the_way"])] if row["on_the_way"] else []
            awaited = sum(quantity for _, quantity in labels.get("on_the_way", []))
            labels["on_the_way"] = [(None, awaited)] if awaited else []
            labels["incoming_sources"] = [{"quantity": awaited}] if awaited else []
    for conflict in result.get("conflicts", []):
        conflict["decks"] = names(conflict.get("decks", []))
    allowed = set(visible_warnings(p))
    result["warnings"] = [text for text in result.get("warnings", []) if text in allowed]
    # A place is checked by its path (visible_place), then shown in the database's words (E11-S12).
    result["unresolved"] = [(name, place_words(where)) for name, where in result.get("unresolved", [])
                            if visible_place(where, sees, records)]
    return result


def table_changes(changes, space):
    """A saved table's label differences may name old orders, even after they arrived.
    For outsiders to home show numeric changes without those free-text source labels."""
    if space != spaces.HOME or guard.sees_home_records():
        return changes
    return [dict(change, **{side: dict(change[side], labels=[]) if change.get(side) else None
                           for side in ("was", "now")}) for change in changes]
