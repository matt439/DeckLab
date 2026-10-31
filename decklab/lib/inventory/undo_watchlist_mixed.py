"""Undo a purchase-queue change that mixed updated, added and removed rows (1-50 rows; E11-S08).

The update slice (undo_watchlist) and the added/removed slice (undo_watchlist_rows) made whole
for a change that did more than one of those things: a shop check's `watchlist apply` that
edited some rows and added or removed others, or a `watchlist.add_many` that both added rows and
raised identical requests' quantities. The complete source must be home's watchlist_item rows
only, with at least two kinds of effect; an order's --fulfils, a cancellation or anything with
another row stays missing to Undo. One inverse puts every updated row's recorded values back in
place, removes every added row by id and brings every removed row back as a new row where it
was, all or nothing, after one reviewed reason when it removes any row.

Each row is checked as its own slice checks it (the same parsers, latest-audit and current-value
checks, validity, repeats and placement), and a removed row is restored only while the change is
still the queue's latest audited change (undo_watchlist_latest), so a second Undo never puts
rows back twice. The database writes exactly the reviewed UPDATEs, DELETEs and INSERTs; before
commit, PgInventory.apply proves that from the transaction's own audit rows, the persisted
layout and the saved queue (confirm), or the whole change rolls back.
"""
import collections

from decklab.lib import config, inventory

from . import Summary, changes, files, orders, paths
from .model import QUEUE_FIELDS
from .undo import BATCH_MAX, UndoConflict, UndoMissing, UndoUnsupported, _identifier
from .undo_token_batch import Refused
from .undo_watchlist import AUDIT, DUPLICATE, EDITED, HOME, INVALID, KIND, TABLE, UNTOUCHED, _image, _queue, _stock
from . import undo_watchlist as updates, undo_watchlist_rows as rows

ACTION = "watchlist_mixed"
OPS = ("UPDATE", "INSERT", "DELETE")
CHANGE = {"UPDATE": "updated", "INSERT": "added", "DELETE": "removed"}   # what the source did to each row
UNCONFIRMED = "The purchase-queue Undo could not be confirmed. Nothing was saved."
UNSAFE = "The purchase-queue changes cannot safely be undone here. Nothing was saved."
CHANGED = "The purchase queue changed after that change. Nothing was undone."


def _plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


def queue_rows(rows):
    """Whether undo_audit's (first) rows are all purchase-queue rows, whatever their ops."""
    return isinstance(rows, list) and len(rows) >= 1 and all(
        isinstance(row, dict) and row.get("table") == TABLE and row.get("op") in OPS for row in rows)


def _mixed(raw):
    return queue_rows(raw) and len({row["op"] for row in raw}) >= 2


def looks_like(store, change_id, first):
    """Whether the change is a mixed queue change: its first rows already mix ops, or its complete
    rows (an append-only record, so reading them here is safe) are queue rows of two kinds or more.
    Call only after a member's space has been answered as missing."""
    if not queue_rows(first):
        return False
    if _mixed(first):
        return True
    reader = getattr(store, "undo_audit_rows", None)
    return callable(reader) and _mixed(reader(change_id))


def _owned(raw):
    """Every row a queue UPDATE with both images, an INSERT with only an after image or a DELETE
    with only a before image, of two kinds or more; else the whole source is unavailable."""
    if not _mixed(raw):
        raise UndoMissing()
    for row in raw:
        op = row["op"]
        before, after = row.get("before"), row.get("after")
        if (op == "UPDATE" and not (isinstance(before, dict) and isinstance(after, dict))) \
                or (op == "INSERT" and not (before is None and isinstance(after, dict))) \
                or (op == "DELETE" and not (isinstance(before, dict) and after is None)):
            raise UndoMissing()


def _complete(store, change_id):
    from .undo_mixed import MIXED_MAX
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        _owned(store.undo_audit(change_id))
        raise UndoUnsupported("Undoing a mixed purchase-queue change needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    _owned(raw)
    if len(raw) > BATCH_MAX:
        raise Refused(f"That change touched {len(raw)} purchase-queue rows; Undo reverses at most {BATCH_MAX} at once. "
                      "Nothing was changed.")
    return raw


def _refuse(why, total):
    count = sum(1 for reasons in why if reasons)
    if not count:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {number}" for reason, number in counts.items())
    raise Refused(f"{count} of the {total} purchase-queue rows that change touched can't be undone ({parts}). "
                  "Undo reverses the whole change or nothing, so nothing was changed.")


def _parse(record):
    """(change, item) of one audit row, or (change, the fixed reason it can't be undone): each
    kind read by its own slice's parser."""
    change = CHANGE[record["op"]]
    if change == "updated":
        found = updates._parse(record)
    else:
        found = rows._parse(record, rows.REMOVE if change == "added" else rows.ADD)
    if not isinstance(found, str):
        found["change"] = change
    return change, found


def _counts(items):
    found = collections.Counter(item["change"] for item in items)
    return {change: found[change] for change in ("updated", "added", "removed")}


def describe(counts):
    """The parts of the Undo in words: "2 restored in place, 1 removed, 1 restored as a new row"."""
    parts = []
    if counts["updated"]:
        parts.append(f"{counts['updated']} restored in place")
    if counts["added"]:
        parts.append(f"{counts['added']} removed")
    if counts["removed"]:
        parts.append(f"{counts['removed']} restored as {'a new row' if counts['removed'] == 1 else 'new rows'}")
    return ", ".join(parts)


def _inverse(snapshot, order, restores, wanted, removed):
    """The queue after the Undo: order lists it as {"id": a current row} (its recorded values back
    when restores names it) or {"restore": a restored row's index} (a new row, id 0); every other
    row and the rest of the inventory exactly as they are. ValueError for any other effect."""
    current = {row.id: row for row in snapshot.watchlist.rows}
    if {entry["id"] for entry in order if "id" in entry} != set(current) - removed or not removed <= set(current):
        raise ValueError("Not exactly the surviving rows")
    made = [(current[entry["id"]].replace(**restores[entry["id"]]) if entry["id"] in restores else current[entry["id"]])
            if "id" in entry else dict(wanted[entry["restore"]]) for entry in order]
    settled = changes.prepare(snapshot, snapshot.with_watchlist(made))
    if settled != snapshot.replace(watchlist=settled.watchlist) or len(settled.watchlist.rows) != len(order) \
            or len(order) != len(current) - len(removed) + len(wanted):
        raise ValueError("Unexpected queue effect")
    for entry, row in zip(order, settled.watchlist.rows):
        if "id" in entry:
            rid = entry["id"]
            if row.id != rid or row.as_dict() != restores.get(rid, current[rid].as_dict()):
                raise ValueError("Unexpected queue row")
        elif row.id in current or row.as_dict() != wanted[entry["restore"]]:
            raise ValueError("Unexpected restored row")
    return settled


def review(change_id, space, snapshot, store, raw=None):
    _identifier(change_id)
    if space != HOME:
        raise UndoMissing()
    if raw is None:
        raw = _complete(store, change_id)
    else:
        _owned(raw)
    total = len(raw)
    why, items = [[] for _ in raw], []
    for index, record in enumerate(raw):
        _, found = _parse(record)
        if isinstance(found, str):
            why[index].append(found)
            items.append(None)
        else:
            items.append(found)
    present = [item for item in items if item is not None]
    if len({item["row_change_id"] for item in present}) != len(present) \
            or len({item["watch_row_id"] for item in present}) != len(present):
        raise UndoUnsupported("A purchase-queue Undo must name each row exactly once.")
    _refuse(why, total)
    label = f"Changes to {_plural(total, 'purchase-queue row')}"
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current purchase queue cannot be checked. Reload Shopping.", label)
    stock = _stock(snapshot)
    current = {row["id"]: row["row"] for row in stock}
    for index, item in enumerate(items):
        rid = item["watch_row_id"]
        latest = store.undo_latest(TABLE, {"id": rid})
        if item["change"] == "removed":
            if latest != item["row_change_id"] or rid in current:
                why[index].append(AUDIT)
        elif latest != item["row_change_id"] or current.get(rid) != item["current" if item["change"] == "updated" else "row"]:
            why[index].append(EDITED)
    _refuse(why, total)
    restoring = [item for item in items if item["change"] == "removed"]
    fence = None
    if restoring:
        # As the removed-rows slice: the whole queue's latest audit row must still be this change's.
        reader = getattr(store, "undo_watchlist_latest", None)
        if not callable(reader):
            raise UndoUnsupported("Restoring removed purchase-queue rows needs the queue's complete audit fence.")
        fence = reader()
        if type(fence) is not int or fence != max(item["row_change_id"] for item in items):
            raise UndoConflict(CHANGED, label)
    repo = str(config.REPO)
    restores = {item["watch_row_id"]: item["restore"] for item in items if item["change"] == "updated"}
    removed = {item["watch_row_id"] for item in items if item["change"] == "added"}
    for index, item in enumerate(items):
        if item["change"] == "added":
            continue
        values = item["restore" if item["change"] == "updated" else "row"]
        try:
            if orders.queue_row(dict(values), repo, snapshot) != values:
                why[index].append(INVALID)
        except inventory.Unavailable:
            raise
        except (inventory.Invalid, ValueError):
            why[index].append(INVALID)
    wanted = [item["row"] for item in restoring]
    proposed = [restores.get(row["id"], row["row"]) for row in stock if row["id"] not in removed] + wanted
    keys = collections.Counter(orders.queue_key(row) for row in proposed)
    for index, item in enumerate(items):
        if item["change"] != "added" and keys[orders.queue_key(item["restore" if item["change"] == "updated" else "row"])] > 1:
            why[index].append(DUPLICATE)
    _refuse(why, total)
    reader = getattr(store, "undo_watchlist_positions", None)
    if not callable(reader):
        raise UndoUnsupported("Undoing a mixed purchase-queue change needs the database's queue positions.")
    layout = reader()
    try:
        survivors = [row for row in stock if row["id"] not in removed]
        kept = [place for place in layout if place.get("id") not in removed]
        if [place.get("id") for place in layout] != [row["id"] for row in stock]:
            raise ValueError("The persisted layout isn't the queue's")
        order, positions = rows._place(survivors, kept, restoring) if restoring \
            else ([{"id": row["id"]} for row in survivors], [])
        orders._no_duplicates(proposed)
        _inverse(snapshot, order, restores, wanted, removed)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    digest = rows._receipt(change_id, raw, files.rendered_sha256(snapshot.watchlist), stock, layout, snapshot.revision,
                           snapshot.decks_revision, ACTION, fence)
    ordered = [item for change in ("updated", "added", "removed") for item in items if item["change"] == change]
    counts = _counts(items)
    # proof stays internal: the API projects only the rows' values, their stable ids and the counts.
    proof = {"updated": [{"id": item["watch_row_id"], "current_db": item["current_db"], "restore_db": item["restore_db"]}
                         for item in ordered if item["change"] == "updated"],
             "removed": [{"id": item["watch_row_id"], "image": item["image"]} for item in ordered if item["change"] == "added"],
             "deleted_ids": [item["watch_row_id"] for item in restoring], "stock": stock, "layout": layout,
             "order": order, "positions": positions}
    plan_rows = []
    for item in ordered:
        out = {"change": item["change"], "row_change_id": item["row_change_id"], "label": item["label"]}
        if item["change"] == "updated":
            out.update(watch_row_id=item["watch_row_id"], current=item["current"], restore=item["restore"],
                       fields=[{"field": field, "before": item["current"][field], "after": item["restore"][field]}
                               for field in QUEUE_FIELDS if item["current"][field] != item["restore"][field]])
        elif item["change"] == "added":
            out.update(watch_row_id=item["watch_row_id"], current=item["row"])
        else:
            out["restore"] = item["row"]
        plan_rows.append(out)
    return {"change_id": change_id, "kind": KIND, "space": HOME, "action": ACTION, "row_count": total, "counts": counts,
            "rows": plan_rows, "label": label, "expect": digest, "proof": proof,
            **({"reason_required": True} if counts["added"] else {})}


def summary_counts(counts):
    """The saved change's counts: only the effects it has."""
    out = {key: counts[change] for key, change in (("edited", "updated"), ("removed_rows", "added"), ("added_rows", "removed"))
           if counts[change]}
    return {**out, "undo": 1}


def apply(snapshot, plan, change_id, reason=None):
    """Every reviewed effect reversed together; every other row exactly as it is. The database's own
    UPDATEs, DELETEs and INSERTs are proved again before commit (confirm). The summary names no value."""
    label, proof, counts = plan["label"], plan["proof"], plan["counts"]
    restores = {item["watch_row_id"]: item["restore"] for item in plan["rows"] if item["change"] == "updated"}
    removed = {item["watch_row_id"] for item in plan["rows"] if item["change"] == "added"}
    wanted = [item["restore"] for item in plan["rows"] if item["change"] == "removed"]
    try:
        settled = _inverse(snapshot, proof["order"], restores, wanted, removed)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    fields = sorted({field["field"] for item in plan["rows"] if item["change"] == "updated" for field in item["fields"]})
    fields += ["remove"] * bool(removed) + ["add"] * bool(wanted)
    extra = {"undo_of": change_id, "space": HOME, "kind": KIND, "action": ACTION, "row_count": plan["row_count"],
             "row_change_ids": [item["row_change_id"] for item in plan["rows"]],
             "watch_mixed": {**proof, "label": label, "restore": restores, "wanted": wanted}}
    if removed:
        extra["undo_reason"] = reason
    return settled, Summary(f"Undo change #{change_id}: undo {label} ({describe(counts)})", summary_counts(counts),
                            {paths.WATCHLIST: fields}, extra)


def restoring(summary):
    """Whether summary needs this module's transaction-local proof."""
    extra = summary.extra or {}
    return extra.get("action") == ACTION and extra.get("kind") == KIND and isinstance(extra.get("watch_mixed"), dict)


def _confirm(proof, saved, actual, layout):
    updated = {item["id"]: item for item in proof["updated"]}
    removed = {item["id"]: item["image"] for item in proof["removed"]}
    wanted, positions = proof["wanted"], proof["positions"]
    total = len(updated) + len(removed) + len(wanted)
    if not isinstance(actual, list) or len(actual) != total or not 2 <= total <= BATCH_MAX:
        raise ValueError("Not exactly the reviewed audited rows")
    known = {row["id"] for row in proof["stock"]} | set(proof["deleted_ids"])
    seen, matched = set(), {}
    for row in actual:
        if not isinstance(row, dict) or row.get("table") != TABLE:
            raise ValueError("Another table")
        op, old, new, key = row.get("op"), row.get("before"), row.get("after"), row.get("key")
        if op == "UPDATE":
            rid = key.get("id") if isinstance(key, dict) else None
            if type(rid) is not int or rid not in updated or rid in seen or key != {"id": rid} \
                    or old != updated[rid]["current_db"] or new != updated[rid]["restore_db"]:
                raise ValueError("Another update")
            seen.add(rid)
        elif op == "DELETE":
            rid = old.get("id") if isinstance(old, dict) else None
            if new is not None or type(rid) is not int or rid not in removed or rid in seen or key != {"id": rid} or old != removed[rid]:
                raise ValueError("Another removal")
            seen.add(rid)
        elif op == "INSERT":
            if old is not None or not _image(new) or key != {"id": new["id"]} or new["id"] in known \
                    or new["id"] in matched.values():
                raise ValueError("Not a fresh queue INSERT")
            index = next((n for n in range(len(wanted)) if n not in matched and wanted[n] == _queue(new)), None)
            if index is None or new["position"] != positions[index]:
                raise ValueError("Changed facts or position")
            matched[index] = new["id"]
        else:
            raise ValueError("Another effect")
    if seen != set(updated) | set(removed) or len(matched) != len(wanted):
        raise ValueError("Not every reviewed row")
    stock = {row["id"]: row["row"] for row in proof["stock"]}
    stored = {item["id"]: item["position"] for item in proof["layout"]}
    restore = proof["restore"]
    expected = [(entry["id"], restore.get(entry["id"], stock[entry["id"]])) if "id" in entry
                else (matched[entry["restore"]], wanted[entry["restore"]]) for entry in proof["order"]]
    places = [{"id": entry["id"], "position": stored[entry["id"]]} if "id" in entry
              else {"id": matched[entry["restore"]], "position": positions[entry["restore"]]} for entry in proof["order"]]
    if [(row.id, row.as_dict()) for row in saved.watchlist.rows] != expected or layout != places:
        raise ValueError("Queue rows or positions changed")
    return [item["id"] for item in proof["updated"]], [item["id"] for item in proof["removed"]], \
        [matched[n] for n in range(len(wanted))]


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows, the persisted queue layout and
    the saved queue: exactly one UPDATE of each reviewed updated row back to the image it replaced,
    one DELETE of each added row with the image it was added with and one INSERT of each removed row
    under a fresh id at its planned position; every other queue row, its position, the order and the
    rest of the inventory unchanged. Any difference raises, so the transaction rolls back. Returns
    the summary with the restored, removed and new ids in place of the proof."""
    extra = dict(summary.extra)
    proof = extra.pop("watch_mixed")
    try:
        restored, removed, added = _confirm(proof, saved, actual, layout)
        if any(getattr(saved, part) != getattr(before, part) for part in UNTOUCHED):
            raise ValueError("Another inventory part changed")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed,
                   {**extra, "restored_watch_row_ids": restored, "removed_watch_row_ids": removed, "added_watch_row_ids": added})


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
