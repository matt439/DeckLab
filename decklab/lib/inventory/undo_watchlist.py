"""Restore the recorded values of 1-50 purchase-queue rows one change set updated (E11-S08).

The complete source must be home's watchlist_item UPDATEs only, each keeping its row's id and
position (a watchlist set, or a shop check's watchlist apply that only changed values). Every row
must still be exactly as the change left it, untouched since, and its recorded values must be a
valid queue row now that repeats no other; nothing is selected partially. A source with any row
that can't be restored is refused whole, naming how many and why in counts and fixed words only
(undo_token_batch.Refused). The inverse replaces each row's 14 queue fields in place, by id, so
PostgreSQL writes exactly N UPDATEs with unchanged positions; before commit, PgInventory.apply
proves that from the transaction's own audit rows and the saved queue (confirm), or rolls back.
"""
import collections
import hashlib
import json

from decklab.lib import config, inventory

from . import Summary, changes, files, orders, paths
from .model import QUEUE_FIELDS
from .table_rows import WATCH_COLUMNS
from .undo import BATCH_MAX, UndoConflict, UndoMissing, UndoUnsupported, _identifier
from .undo_token_batch import Refused

ACTION = "watchlist_update"
TABLE = "watchlist_item"
KIND = "watchlist"
HOME = "home"
ROW_FIELDS = {"id", "position", *WATCH_COLUMNS}
COLUMN = dict(zip(QUEUE_FIELDS, WATCH_COLUMNS))     # queue field -> database column (set_code, for_deck)
UNCONFIRMED = "The restored purchase-queue rows could not be confirmed. Nothing was saved."
UNSAFE = "The purchase-queue rows cannot safely be restored here. Nothing was saved."

# Why a row can't be restored: fixed words, never a recorded value, note, price or source.
AUDIT = "audit record can't be checked"
MOVED = "moved in the queue"
EDITED = "edited or removed since"
INVALID = "recorded values aren't a valid queue row now"
DUPLICATE = "would repeat another queue row"


def looks_like(rows):
    """Whether undo_audit's (first) rows are purchase-queue UPDATEs, one row or more: the review
    reads the complete change set before trusting it (PgInventory's undo_audit gives two at most)."""
    return isinstance(rows, list) and len(rows) >= 1 and all(
        isinstance(row, dict) and row.get("table") == TABLE and row.get("op") == "UPDATE" for row in rows)


def _owned(raw):
    """Every row a queue UPDATE with both images, or the whole source is unavailable."""
    if any(not isinstance(row, dict) or row.get("table") != TABLE or row.get("op") != "UPDATE"
           or not isinstance(row.get("before"), dict) or not isinstance(row.get("after"), dict) for row in raw):
        raise UndoMissing()


def _complete(store, change_id, space):
    from .undo_mixed import MIXED_MAX
    if space != HOME:
        raise UndoMissing()
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        # The rows already seen are checked first, so another source never answers as unsupported.
        _owned(store.undo_audit(change_id))
        raise UndoUnsupported("Restoring purchase-queue updates needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    _owned(raw)
    if len(raw) > BATCH_MAX:
        raise Refused(f"That change updated {len(raw)} purchase-queue rows; Undo restores at most {BATCH_MAX} at once. "
                      "Nothing was restored.")
    return raw


def _refuse(why, total):
    rows = sum(1 for reasons in why if reasons)
    if not rows:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {count}" for reason, count in counts.items())
    raise Refused(f"{rows} of the {total} updated purchase-queue rows can't be restored ({parts}). "
                  "Undo restores the whole change or nothing, so nothing was restored.")


def _queue(image):
    """A database image as the queue's 14 text fields (the quantity as text), values verbatim."""
    return {field: str(image["quantity"]) if field == "quantity" else image[COLUMN[field]] for field in QUEUE_FIELDS}


def _image(image):
    """Whether one recorded image is a whole queue row the inverse can write back."""
    return isinstance(image, dict) and set(image) == ROW_FIELDS \
        and type(image["id"]) is int and 1 <= image["id"] < 10 ** 18 \
        and type(image["position"]) is int and 0 <= image["position"] < 2 ** 31 \
        and type(image["quantity"]) is int and 1 <= image["quantity"] < 2 ** 31 \
        and all(isinstance(image[column], str) for column in WATCH_COLUMNS if column != "quantity")


def _parse(record):
    """The review item of one audit row, or the fixed reason it can't be restored."""
    old, new, rid = record.get("before"), record.get("after"), record.get("id")
    if type(rid) is not int or not 1 <= rid < 10 ** 18 or not _image(old) or not _image(new) \
            or old["id"] != new["id"] or record.get("key") != {"id": new["id"]}:
        return AUDIT
    if old["position"] != new["position"]:
        return MOVED
    current, restore = _queue(new), _queue(old)
    if current == restore:
        return AUDIT
    label = restore["name"] + (f" for {restore['for']}" if restore["for"] else "")
    return {"row_change_id": rid, "watch_row_id": new["id"], "position": new["position"], "current": current,
            "restore": restore, "current_db": dict(new), "restore_db": dict(old), "label": label}


def _stock(snapshot):
    return [{"id": row.id, "row": {key: row.text(key) for key in QUEUE_FIELDS}} for row in snapshot.watchlist.rows]


def _inverse(snapshot, items):
    """Each reviewed row's 14 fields replaced in place, by id; every other row, the order and the
    rest of the inventory exactly as they are. ValueError for any other effect."""
    restores = {item["watch_row_id"]: item["restore"] for item in items}
    rows = [row.replace(**restores[row.id]) if row.id in restores else row for row in snapshot.watchlist.rows]
    settled = changes.prepare(snapshot, snapshot.with_watchlist(rows))
    if settled != snapshot.replace(watchlist=settled.watchlist):
        raise ValueError("Unexpected inventory effect")
    old, new = list(snapshot.watchlist.rows), list(settled.watchlist.rows)
    if [row.id for row in new] != [row.id for row in old] or sorted(restores) != sorted(row.id for row in old if row.id in restores):
        raise ValueError("Queue rows moved or lost their ids")
    for was, now in zip(old, new):
        if now.as_dict() != (restores[was.id] if was.id in restores else was.as_dict()):
            raise ValueError("Unexpected queue row")
    return settled


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
    if space != HOME:
        raise UndoMissing()
    raw = _complete(store, change_id, space) if rows is None else rows
    total = len(raw)
    why = [[] for _ in raw]
    items = []
    for index, record in enumerate(raw):
        found = _parse(record)
        if isinstance(found, str):
            why[index].append(found)
            items.append(None)
        else:
            items.append(found)
    present = [item for item in items if item is not None]
    if len({item["row_change_id"] for item in present}) != len(present) \
            or len({item["watch_row_id"] for item in present}) != len(present):
        raise UndoUnsupported("A purchase-queue Undo must name each updated row exactly once.")
    _refuse(why, total)
    label = f"Updates to {total} purchase-queue row{'s' if total > 1 else ''}"
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current purchase queue cannot be checked. Reload Shopping.", label)
    stock = _stock(snapshot)
    for index, item in enumerate(items):
        rid = item["watch_row_id"]
        found = [row["row"] for row in stock if row["id"] == rid]
        if store.undo_latest(TABLE, {"id": rid}) != item["row_change_id"] or found != [item["current"]]:
            why[index].append(EDITED)
    _refuse(why, total)
    repo = str(config.REPO)
    for index, item in enumerate(items):
        try:
            if orders.queue_row(dict(item["restore"]), repo, snapshot) != item["restore"]:
                why[index].append(INVALID)
        except inventory.Unavailable:
            raise
        except (inventory.Invalid, ValueError):
            why[index].append(INVALID)
    restores = {item["watch_row_id"]: item["restore"] for item in items}
    proposed = [restores.get(row["id"], row["row"]) for row in stock]
    keys = collections.Counter(orders.queue_key(row) for row in proposed)
    for index, item in enumerate(items):
        if keys[orders.queue_key(item["restore"])] > 1:
            why[index].append(DUPLICATE)
    _refuse(why, total)
    try:
        orders._no_duplicates(proposed)
        _inverse(snapshot, items)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    receipt = [change_id, raw, files.rendered_sha256(snapshot.watchlist), stock, snapshot.revision,
               snapshot.decks_revision, ACTION]
    digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    # proof stays internal: the API projects only the rows' fields, their stable ids and the count.
    proof = {"rows": [{"id": item["watch_row_id"], "position": item["position"], "current_db": item["current_db"],
                       "restore_db": item["restore_db"]} for item in items],
             "order": [row["id"] for row in stock], "stock": stock}
    plan_rows = [{"row_change_id": item["row_change_id"], "watch_row_id": item["watch_row_id"], "label": item["label"],
                  "current": item["current"], "restore": item["restore"],
                  "fields": [{"field": field, "before": item["current"][field], "after": item["restore"][field]}
                             for field in QUEUE_FIELDS if item["current"][field] != item["restore"][field]]}
                 for item in items]
    return {"change_id": change_id, "kind": KIND, "space": HOME, "action": ACTION, "row_count": total,
            "rows": plan_rows, "label": label, "expect": digest, "proof": proof}


def apply(snapshot, plan, change_id):
    """Every reviewed row's recorded values back in place; every other row exactly as it is. The
    database's own UPDATEs are proved again before commit (confirm). The summary names no value."""
    label, proof, count = plan["label"], plan["proof"], plan["row_count"]
    try:
        settled = _inverse(snapshot, plan["rows"])
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    fields = sorted({field["field"] for item in plan["rows"] for field in item["fields"]})
    return settled, Summary(f"Undo change #{change_id}: restore {label}", {"edited": count, "undo": 1},
                            {paths.WATCHLIST: fields},
                            {"undo_of": change_id, "space": HOME, "kind": KIND, "action": ACTION, "row_count": count,
                             "row_change_ids": [item["row_change_id"] for item in plan["rows"]],
                             "watch_restore": {**proof, "label": label,
                                               "restore": {item["watch_row_id"]: item["restore"] for item in plan["rows"]}}})


def restoring(summary):
    """Whether summary needs this module's transaction-local proof."""
    extra = summary.extra or {}
    return extra.get("action") == ACTION and extra.get("kind") == KIND and isinstance(extra.get("watch_restore"), dict)


# The inventory parts a queue Undo must leave exactly as they were (the audit rows prove it too).
UNTOUCHED = ("collections", "tokens", "locations", "imports", "status", "products", "orders", "payloads", "accessories")


def confirm(before, saved, summary, actual):
    """Prove the saved effect from the transaction's own audit rows and the saved queue: exactly
    one UPDATE of each reviewed row, from the image the change left to the image it replaced,
    positions included; every other queue row, the order and the rest of the inventory unchanged.
    Any difference raises, so the transaction rolls back. Returns the summary with the restored
    ids, in the plan's row order, in place of the proof."""
    extra = dict(summary.extra)
    proof = extra.pop("watch_restore")
    reviewed = {item["id"]: item for item in proof["rows"]}
    try:
        count = len(reviewed)
        if not isinstance(actual, list) or len(actual) != count or not 1 <= count <= BATCH_MAX \
                or count != len(proof["rows"]):
            raise ValueError("Not exactly the reviewed audited rows")
        seen = set()
        for row in actual:
            key = row.get("key") if isinstance(row, dict) else None
            rid = key.get("id") if isinstance(key, dict) else None
            if not isinstance(row, dict) or row.get("table") != TABLE or row.get("op") != "UPDATE" \
                    or type(rid) is not int or rid not in reviewed or rid in seen or key != {"id": rid} \
                    or row.get("before") != reviewed[rid]["current_db"] or row.get("after") != reviewed[rid]["restore_db"]:
                raise ValueError("Another row or changed facts")
            seen.add(rid)
        restore = proof["restore"]
        expected = [(item["id"], restore.get(item["id"], item["row"])) for item in proof["stock"]]
        if [(row.id, row.as_dict()) for row in saved.watchlist.rows] != expected \
                or [row.id for row in saved.watchlist.rows] != proof["order"]:
            raise ValueError("Queue rows changed")
        if any(getattr(saved, part) != getattr(before, part) for part in UNTOUCHED):
            raise ValueError("Another inventory part changed")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed,
                   {**extra, "restored_watch_row_ids": [item["id"] for item in proof["rows"]]})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook: this change set's rows, one more than the reviewed count so an
    extra row refuses, on its own cursor."""
    count = len(summary.extra["watch_restore"]["rows"])
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    return confirm(before, saved, summary, actual)
