"""Transaction-local proof of a collection-row batch Undo (E11-S08).

undo.py's batch_remove (a complete source of 2-50 own-space collection INSERTs: the rows are
removed again) and batch_add (2-50 DELETEs: the rows come back) are worked out on the snapshot
by the ordinary collection helpers. Before commit, PgInventory.apply reads the change set's
own audit rows (one more than reviewed, so an extra row refuses) and its recorded reason, and
confirm() proves exactly one DELETE of each reviewed current row or exactly one INSERT of each
recorded row (no storage location, as the ordinary Add saves it), the space's whole saved
collection as reviewed, survivors' storage locations kept, no other space, inventory part or
deck changed (deck tables are left out of date, as other collection changes leave them) and,
for a removal, the reviewed reason recorded. Any difference rolls the whole change back.

No space-level audit fence is needed here, unlike restored purchase-queue rows: a collection
row's audit key is its printing (space, set, number, finish), not a fresh id, so a printing
added or removed again after the source moves that key's latest audit row and the review's
per-key fence (undo_latest) refuses the replay.
"""
from decklab.lib import inventory

from . import Summary, changes, paths, rules
from .undo import BATCH_MAX, COLLECTION, COLLECTION_KEYS, COLLECTION_SCHEMAS, UndoConflict, _ordinary, _remaining_collection

PROOF = "collection_rows"
ACTIONS = {"batch_remove": "DELETE", "batch_add": "INSERT"}
UNCONFIRMED = "The collection Undo could not be confirmed. Nothing was saved."
UNTOUCHED = ("tokens", "imports", "status", "products", "orders", "payloads", "watchlist", "accessories",
             "accessory_images", "decks", "deck_aliases")


def proof(plan, before_rows):
    """The facts confirm() checks, kept in the Undo summary's extra until the hook pops them."""
    removing = plan["action"] == "batch_remove"
    rows = [dict(item["current"] if removing else item["restore"]) for item in plan["rows"]]
    keys = {rules.ident(row) for row in rows}
    expected = {key: row for key, row in before_rows.items() if key not in keys} if removing \
        else {**before_rows, **{rules.ident(row): row for row in rows}}
    return {"label": plan["label"], "rows": rows, "expected": expected}


def restoring(summary):
    """Whether summary needs this module's transaction-local proof."""
    extra = summary.extra or {}
    return extra.get("kind") == "collection" and extra.get("action") in ACTIONS and isinstance(extra.get(PROOF), dict)


def _image(row, op, space):
    """The recorded row an audit row of op wrote or took away, in collection columns."""
    old, new = row.get("before"), row.get("after")
    image, other = (old, new) if op == "DELETE" else (new, old)
    if row.get("table") != COLLECTION or row.get("op") != op or other is not None or not isinstance(image, dict) \
            or set(image) not in COLLECTION_SCHEMAS or image.get("space_id") != space \
            or not isinstance(row.get("key"), dict) or set(row["key"]) != COLLECTION_KEYS \
            or any(row["key"][key] != image[key] for key in COLLECTION_KEYS):
        raise ValueError("Not one of this space's collection rows")
    if op == "INSERT" and image.get("location", "") != "":
        raise ValueError("A restored row gained a location")
    return _ordinary(image, COLLECTION)


def confirm(before, saved, summary, actual, recorded_reason):
    """Prove the saved effect from the transaction's own audit rows and the saved snapshot.
    actual: this change set's audit rows (one more than reviewed); recorded_reason: its
    change set's reason. Returns the summary without the proof; any difference raises."""
    extra = dict(summary.extra)
    found = extra.pop(PROOF)
    try:
        space, op = extra["space"], ACTIONS[extra["action"]]
        wanted = {rules.ident(row): row for row in found["rows"]}
        if not isinstance(actual, list) or len(actual) != len(found["rows"]) or len(wanted) != len(found["rows"]) \
                or not 2 <= len(wanted) <= BATCH_MAX or extra.get("row_count") != len(wanted):
            raise ValueError("Not exactly the reviewed audited rows")
        seen = set()
        for row in actual:
            image = _image(row, op, space)
            key = rules.ident(image)
            if key in seen or wanted.get(key) != image:
                raise ValueError("Another row or changed facts")
            seen.add(key)
        if _remaining_collection(saved, space, found["label"]) != found["expected"]:
            raise ValueError("The saved collection isn't the reviewed one")
        allowed = {paths.collection(space), paths.locations(space)}
        if set(changes.changed(before, saved)) - allowed \
                or any(saved.collection(owner) != before.collection(owner)
                       or saved.location_sheet(owner) != before.location_sheet(owner)
                       for owner in set(before.collections) | set(saved.collections) | set(before.locations)
                       | set(saved.locations) if owner != space) \
                or any(getattr(saved, part) != getattr(before, part) for part in UNTOUCHED) \
                or saved.decks_revision != before.decks_revision:
            raise ValueError("Another part changed")
        located = {key: where for key, where in before.locations_of(space).items() if key in found["expected"]}
        if saved.locations_of(space) != located:
            raise ValueError("A storage location changed")
        if recorded_reason != (extra.get("undo_reason") if op == "DELETE" else None):
            raise ValueError("The reason wasn't recorded as reviewed")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, found.get("label") if isinstance(found, dict) else None) from None
    return Summary(summary.text, summary.counts, summary.changed, extra)


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook: this change set's rows (one more than reviewed) and reason."""
    count = summary.extra["row_count"]
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    found = cur.execute("select reason from audit.change_set where id=%s", (change_set,)).fetchone()
    return confirm(before, saved, summary, actual, found[0] if found is not None else None)
