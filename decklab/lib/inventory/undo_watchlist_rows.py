"""Remove 1-50 purchase-queue rows one change set added, or restore 1-50 it removed (E11-S08).

The value-update slice (undo_watchlist) made whole for the queue's other two row effects. The
complete source must be home's watchlist_item INSERTs only (a `watchlist set --add`, or a shop
check's `watchlist apply` that only added rows) or DELETEs only (a `watchlist remove`, or an
apply that only removed rows); anything else, an order's --fulfils or a renumbering included, is
missing to Undo. Nothing is selected partially: a source with any row that can't be undone is
refused whole, naming how many and why in counts and fixed words only (undo_token_batch.Refused).

Added rows are removed by id after one reviewed reason, as queue removals need one. The database
keeps every other row's position when rows go (pg._positions), so it writes exactly N DELETEs.

Removed rows come back as new rows under fresh ids, since the database gives every inserted row
its own id, each placed among the current rows by its recorded position, so the queue's relative
order is restored where the survivors still hold their positions. The review works out the
positions pg._positions will give them; a placement that would renumber any current row is
refused, so the database writes exactly N INSERTs. Before commit, PgInventory.apply proves
either effect from the transaction's own audit rows, the persisted positions and the saved
queue (confirm), or the whole change rolls back.
"""
import collections
import hashlib
import json

from decklab.lib import config, inventory

from . import Summary, changes, files, orders, paths
from .undo import BATCH_MAX, UndoConflict, UndoMissing, UndoUnsupported, _identifier
from .undo_token_batch import Refused
from .undo_watchlist import AUDIT, DUPLICATE, EDITED, HOME, INVALID, KIND, TABLE, UNTOUCHED, _image, _queue, _stock

REMOVE = "watchlist_remove"     # the source added rows: Undo removes them
ADD = "watchlist_add"           # the source removed rows: Undo adds them back
OPS = {"INSERT": REMOVE, "DELETE": ADD}
UNCONFIRMED = "The purchase-queue Undo could not be confirmed. Nothing was saved."
UNSAFE = "The purchase-queue rows cannot safely be changed here. Nothing was saved."


def _plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


def looks_like(rows):
    """Whether undo_audit's (first) rows are purchase-queue INSERTs, or DELETEs, only: the review
    reads the complete change set before trusting it."""
    return isinstance(rows, list) and len(rows) >= 1 and all(isinstance(row, dict) for row in rows) \
        and all(row.get("table") == TABLE for row in rows) and len({row.get("op") for row in rows}) == 1 \
        and rows[0].get("op") in OPS


def _owned(raw):
    """Every row a queue INSERT with only an after image, or every row a DELETE with only a
    before image; else the whole source is unavailable. The action it makes."""
    ops = {row.get("op") if isinstance(row, dict) else None for row in raw}
    op = ops.pop() if len(ops) == 1 else None
    if op not in OPS or any(row.get("table") != TABLE for row in raw):
        raise UndoMissing()
    image, empty = ("after", "before") if op == "INSERT" else ("before", "after")
    if any(not isinstance(row.get(image), dict) or row.get(empty) is not None for row in raw):
        raise UndoMissing()
    return OPS[op]


def _complete(store, change_id, space):
    from .undo_mixed import MIXED_MAX
    if space != HOME:
        raise UndoMissing()
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        # The rows already seen are checked first, so another source never answers as unsupported.
        _owned(store.undo_audit(change_id))
        raise UndoUnsupported("Undoing added or removed purchase-queue rows needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    action = _owned(raw)
    if len(raw) > BATCH_MAX:
        if action == REMOVE:
            raise Refused(f"That change added {len(raw)} purchase-queue rows; Undo removes at most {BATCH_MAX} at once. "
                          "Nothing was removed.")
        raise Refused(f"That change removed {len(raw)} purchase-queue rows; Undo restores at most {BATCH_MAX} at once. "
                      "Nothing was restored.")
    return raw, action


def _refuse(why, total, action):
    rows = sum(1 for reasons in why if reasons)
    if not rows:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {count}" for reason, count in counts.items())
    if action == REMOVE:
        raise Refused(f"{rows} of the {total} added purchase-queue rows can't be removed ({parts}). "
                      "Undo removes the whole change or nothing, so nothing was removed.")
    raise Refused(f"{rows} of the {total} removed purchase-queue rows can't be restored ({parts}). "
                  "Undo restores the whole change or nothing, so nothing was restored.")


def _parse(record, action):
    """The review item of one audit row, or the fixed reason it can't be undone."""
    rid = record.get("id")
    image = record.get("after" if action == REMOVE else "before")
    if type(rid) is not int or not 1 <= rid < 10 ** 18 or not _image(image) or record.get("key") != {"id": image["id"]}:
        return AUDIT
    values = _queue(image)
    label = values["name"] + (f" for {values['for']}" if values["for"] else "")
    return {"row_change_id": rid, "watch_row_id": image["id"], "position": image["position"], "row": values,
            "image": dict(image), "label": label}


def _remove(snapshot, ids):
    """The queue without the rows ids names; every other row, its id, its values, the order and
    the rest of the inventory exactly as they are. ValueError for any other effect."""
    rows = [row for row in snapshot.watchlist.rows if row.id not in ids]
    settled = changes.prepare(snapshot, snapshot.with_watchlist(rows))
    if settled != snapshot.replace(watchlist=settled.watchlist) \
            or [(row.id, row.as_dict()) for row in settled.watchlist.rows] != [(row.id, row.as_dict()) for row in rows] \
            or len(rows) != len(snapshot.watchlist.rows) - len(ids):
        raise ValueError("Unexpected queue removal effect")
    return settled


def _place(stock, layout, items):
    """Where the restored rows go: (order, positions). order lists the queue after the Undo as
    {"id": a current row} or {"restore": an item's index}, each restored row before the first
    current row whose persisted position is after its recorded one; positions are the new rows'
    persisted positions (by index), as pg._positions gives them. ValueError if any current row
    would move or the layout isn't the snapshot's."""
    from .pg import _positions
    if [item["id"] for item in layout] != [row["id"] for row in stock]:
        raise ValueError("The persisted layout isn't the queue's")
    entries = [((item["position"], 0, n), {"id": item["id"]}) for n, item in enumerate(layout)]
    entries += [((item["position"], 1, n), {"restore": n}) for n, item in enumerate(items)]
    order = [entry for _, entry in sorted(entries, key=lambda pair: pair[0])]
    stored = {item["id"]: item["position"] for item in layout}
    given = _positions([entry.get("id", 0) for entry in order], stored)
    positions = {}
    for entry, position in zip(order, given):
        if "id" in entry and position != stored[entry["id"]]:
            raise ValueError("A current row would be renumbered")
        if "restore" in entry:
            positions[entry["restore"]] = position
    return order, [positions[n] for n in range(len(items))]


def _restore(snapshot, order, wanted):
    """The queue with each restored row (a new row, id 0) where order puts it; every current row
    and the rest of the inventory exactly as they are. ValueError for any other effect."""
    current = {row.id: row for row in snapshot.watchlist.rows}
    rows = [current[entry["id"]] if "id" in entry else dict(wanted[entry["restore"]]) for entry in order]
    settled = changes.prepare(snapshot, snapshot.with_watchlist(rows))
    if settled != snapshot.replace(watchlist=settled.watchlist) or len(settled.watchlist.rows) != len(order) \
            or len(order) != len(current) + len(wanted):
        raise ValueError("Unexpected queue restore effect")
    for entry, row in zip(order, settled.watchlist.rows):
        if "id" in entry and (row.id != entry["id"] or row.as_dict() != current[entry["id"]].as_dict()) \
                or "restore" in entry and (row.id in current or row.as_dict() != wanted[entry["restore"]]):
            raise ValueError("Unexpected queue row")
    return settled


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
    if space != HOME:
        raise UndoMissing()
    if rows is None:
        raw, action = _complete(store, change_id, space)
    else:
        raw, action = rows, _owned(rows)
    total = len(raw)
    why = [[] for _ in raw]
    items = []
    for index, record in enumerate(raw):
        found = _parse(record, action)
        if isinstance(found, str):
            why[index].append(found)
            items.append(None)
        else:
            items.append(found)
    present = [item for item in items if item is not None]
    if len({item["row_change_id"] for item in present}) != len(present) \
            or len({item["watch_row_id"] for item in present}) != len(present):
        raise UndoUnsupported("A purchase-queue Undo must name each row exactly once.")
    _refuse(why, total, action)
    label = _plural(total, "added purchase-queue row" if action == REMOVE else "removed purchase-queue row")
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current purchase queue cannot be checked. Reload Shopping.", label)
    stock = _stock(snapshot)
    current = {row["id"]: row["row"] for row in stock}
    for index, item in enumerate(items):
        latest = store.undo_latest(TABLE, {"id": item["watch_row_id"]})
        if action == REMOVE and (latest != item["row_change_id"] or current.get(item["watch_row_id"]) != item["row"]):
            why[index].append(EDITED)
        elif action == ADD and (latest != item["row_change_id"] or item["watch_row_id"] in current):
            why[index].append(AUDIT)
    _refuse(why, total, action)
    if action == REMOVE:
        return _review_remove(change_id, snapshot, raw, items, stock, label)
    return _review_add(change_id, snapshot, store, raw, items, stock, label, why)


def _receipt(*parts):
    return hashlib.sha256(json.dumps(list(parts), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _review_remove(change_id, snapshot, raw, items, stock, label):
    try:
        _remove(snapshot, {item["watch_row_id"] for item in items})
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    digest = _receipt(change_id, raw, files.rendered_sha256(snapshot.watchlist), stock, snapshot.revision,
                      snapshot.decks_revision, REMOVE)
    # proof stays internal: the API projects only the rows' values, their stable ids and the count.
    proof = {"removed": [{"id": item["watch_row_id"], "image": item["image"]} for item in items], "stock": stock}
    plan_rows = [{"row_change_id": item["row_change_id"], "watch_row_id": item["watch_row_id"], "label": item["label"],
                  "current": item["row"]} for item in items]
    return {"change_id": change_id, "kind": KIND, "space": HOME, "action": REMOVE, "row_count": len(items),
            "rows": plan_rows, "label": label, "expect": digest, "reason_required": True, "proof": proof}


def _review_add(change_id, snapshot, store, raw, items, stock, label, why):
    total, repo = len(items), str(config.REPO)
    for index, item in enumerate(items):
        try:
            if orders.queue_row(dict(item["row"]), repo, snapshot) != item["row"]:
                why[index].append(INVALID)
        except inventory.Unavailable:
            raise
        except (inventory.Invalid, ValueError):
            why[index].append(INVALID)
    keys = collections.Counter(orders.queue_key(row["row"]) for row in stock)
    keys.update(orders.queue_key(item["row"]) for item in items)
    for index, item in enumerate(items):
        if keys[orders.queue_key(item["row"])] > 1:
            why[index].append(DUPLICATE)
    _refuse(why, total, ADD)
    reader = getattr(store, "undo_watchlist_positions", None)
    if not callable(reader):
        raise UndoUnsupported("Restoring removed purchase-queue rows needs the database's queue positions.")
    layout = reader()
    wanted = [item["row"] for item in items]
    try:
        order, positions = _place(stock, layout, items)
        orders._no_duplicates([row["row"] for row in stock] + wanted)
        _restore(snapshot, order, wanted)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    digest = _receipt(change_id, raw, files.rendered_sha256(snapshot.watchlist), stock, layout, snapshot.revision,
                      snapshot.decks_revision, ADD)
    proof = {"deleted_ids": [item["watch_row_id"] for item in items], "stock": stock, "layout": layout,
             "order": order, "positions": positions}
    plan_rows = [{"row_change_id": item["row_change_id"], "label": item["label"], "restore": item["row"]} for item in items]
    return {"change_id": change_id, "kind": KIND, "space": HOME, "action": ADD, "row_count": total,
            "rows": plan_rows, "label": label, "expect": digest, "proof": proof}


def apply(snapshot, plan, change_id, reason=None):
    """The reviewed rows removed by id (with the reviewed reason), or restored as new rows where the
    review placed them; every other row exactly as it is. The database's own DELETEs or INSERTs are
    proved again before commit (confirm). The summary names no value."""
    label, proof, count, action = plan["label"], plan["proof"], plan["row_count"], plan["action"]
    wanted = [item["restore"] for item in plan["rows"]] if action == ADD else None
    try:
        if action == REMOVE:
            settled = _remove(snapshot, {item["watch_row_id"] for item in plan["rows"]})
        else:
            settled = _restore(snapshot, proof["order"], wanted)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    extra = {"undo_of": change_id, "space": HOME, "kind": KIND, "action": action, "row_count": count,
             "row_change_ids": [item["row_change_id"] for item in plan["rows"]]}
    if action == REMOVE:
        return settled, Summary(f"Undo change #{change_id}: remove {label}", {"removed_rows": count, "undo": 1},
                                {paths.WATCHLIST: ["remove"]},
                                {**extra, "undo_reason": reason, "watch_rows": {**proof, "label": label}})
    return settled, Summary(f"Undo change #{change_id}: restore {label} as new rows", {"added_rows": count, "undo": 1},
                            {paths.WATCHLIST: ["add"]}, {**extra, "watch_rows": {**proof, "label": label, "restore": wanted}})


def restoring(summary):
    """Whether summary needs this module's transaction-local proof."""
    extra = summary.extra or {}
    return extra.get("action") in (REMOVE, ADD) and extra.get("kind") == KIND and isinstance(extra.get("watch_rows"), dict)


def _confirm_remove(proof, saved, actual, layout):
    removed = {item["id"]: item["image"] for item in proof["removed"]}
    if not isinstance(actual, list) or len(actual) != len(removed) or not 1 <= len(removed) <= BATCH_MAX:
        raise ValueError("Not exactly the reviewed audited rows")
    seen = set()
    for row in actual:
        old = row.get("before") if isinstance(row, dict) else None
        rid = old.get("id") if isinstance(old, dict) else None
        if not isinstance(row, dict) or row.get("table") != TABLE or row.get("op") != "DELETE" or row.get("after") is not None \
                or type(rid) is not int or rid not in removed or rid in seen or row.get("key") != {"id": rid} or old != removed[rid]:
            raise ValueError("Another row or changed facts")
        seen.add(rid)
    survivors = [row for row in proof["stock"] if row["id"] not in removed]
    if [{"id": row.id, "row": row.as_dict()} for row in saved.watchlist.rows] != survivors \
            or not isinstance(layout, list) or [item.get("id") for item in layout] != [row["id"] for row in survivors]:
        raise ValueError("Survivors changed")
    return [item["id"] for item in proof["removed"]]


def _confirm_add(proof, saved, actual, layout):
    wanted, positions = proof["restore"], proof["positions"]
    if not isinstance(actual, list) or len(actual) != len(wanted) or not 1 <= len(wanted) <= BATCH_MAX:
        raise ValueError("Not exactly the reviewed audited rows")
    known = {row["id"] for row in proof["stock"]} | set(proof["deleted_ids"])
    matched = {}
    for row in actual:
        new = row.get("after") if isinstance(row, dict) else None
        if not isinstance(row, dict) or row.get("table") != TABLE or row.get("op") != "INSERT" \
                or row.get("before") is not None or not _image(new):
            raise ValueError("Not a queue INSERT")
        rid = new["id"]
        if row.get("key") != {"id": rid} or rid in known or rid in matched.values():
            raise ValueError("Reused id")
        index = next((n for n in range(len(wanted)) if n not in matched and wanted[n] == _queue(new)), None)
        if index is None or new["position"] != positions[index]:
            raise ValueError("Changed facts or position")
        matched[index] = rid
    stock = {row["id"]: row["row"] for row in proof["stock"]}
    stored = {item["id"]: item["position"] for item in proof["layout"]}
    expected = [(entry["id"], stock[entry["id"]]) if "id" in entry else (matched[entry["restore"]], wanted[entry["restore"]])
                for entry in proof["order"]]
    places = [{"id": entry["id"], "position": stored[entry["id"]]} if "id" in entry
              else {"id": matched[entry["restore"]], "position": positions[entry["restore"]]} for entry in proof["order"]]
    if [(row.id, row.as_dict()) for row in saved.watchlist.rows] != expected or layout != places:
        raise ValueError("Queue rows or positions changed")
    return [matched[n] for n in range(len(wanted))]


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows, the persisted queue layout
    and the saved queue: exactly one DELETE of each reviewed row with the image it was added
    with, or exactly one INSERT of each restored row under a fresh id at its planned position;
    every other queue row, its position, the order and the rest of the inventory unchanged. Any
    difference raises, so the transaction rolls back. Returns the summary with the removed or new
    ids, in the plan's row order, in place of the proof."""
    extra = dict(summary.extra)
    proof = extra.pop("watch_rows")
    try:
        if extra["action"] == REMOVE:
            ids, key = _confirm_remove(proof, saved, actual, layout), "removed_watch_row_ids"
        else:
            ids, key = _confirm_add(proof, saved, actual, layout), "restored_watch_row_ids"
        if any(getattr(saved, part) != getattr(before, part) for part in UNTOUCHED):
            raise ValueError("Another inventory part changed")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed, {**extra, key: ids})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook: this change set's rows, one more than the reviewed count so an
    extra row refuses, and the queue's persisted layout, on its own cursor."""
    count = summary.extra["row_count"]
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    layout = [{"id": rid, "position": position} for rid, position in cur.execute(
        "select id,position from watchlist_item order by position,id").fetchall()]
    return confirm(before, saved, summary, actual, layout)
