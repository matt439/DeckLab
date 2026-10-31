"""Restore the recorded values of 1-50 token-card rows one change set edited, in place (E11-S08).

The complete source must be own-space token_card UPDATEs only, each keeping its row's id and
position: a `tokens edit` (or a Tokens-page edit) that changed more than a quantity or notes, or a
change that edited several rows. A single row that changed only its quantity or notes keeps the
older single-row Undo (undo.py). Every row must still be exactly as the change left it, untouched
since, and its recorded values must be a token row the Tokens page's edit would accept now: the
row rules, Scryfall face names and printings for a row whose faces or printing change, and the
never-merge rule (a row naming the same card as another stays apart only when one of them isn't
fully known, as `tokens edit --separate`). Restoring must keep the list's order, and when the
restore changes more than notes or raises a quantity, every packed deck or product Token cards
line must hold exactly the cards it holds now. Nothing is selected partially: a source with any
row that can't be restored is refused whole, naming how many and why in counts and fixed words
only (undo_token_batch.Refused). The inverse replaces each row's ten values in place, by id, so
PostgreSQL writes exactly N UPDATEs with unchanged positions; before commit, PgInventory.apply
proves that from the transaction's own audit rows, the saved stock, its layout and the packing
(confirm), or rolls back.
"""
import collections
import hashlib
import json

from decklab.lib import inventory
from decklab.lib.tokens import names

from . import Summary, changes, files, rules
from . import undo_token_delete as single
from .undo import BATCH_MAX, TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _cells, _identifier, \
    _ordinary
from .undo_token_batch import Refused
from .undo_tokens import _packing, ordered_rows

ACTION = "token_batch_update"
KIND = "tokens"
NARROW = {"quantity", "notes"}          # a single row changing only these keeps undo.py's own inverse
FACES = ("front", "back", "set", "front_collector_number", "back_collector_number")
UNCONFIRMED = "The restored token-card rows could not be confirmed. Nothing was saved."
UNSAFE = "The edited token-card rows cannot safely be restored here. Check them in Tokens."

# Why a row can't be restored: fixed words, never a recorded fact, note or another space's detail.
AUDIT = "audit record can't be checked"
MOVED = "moved in the list"
EDITED = "edited or removed since"
INVALID = "recorded values aren't a valid token row now"
CARD_DATA = "names or printing can't be checked with the current card data"
DUPLICATE = "would name the same card as another fully known row"
ORDER = "would move in the list"
PACKED = "would change or exceed packed token cards"


def _narrow(row):
    old, new = row.get("before"), row.get("after")
    if not isinstance(old, dict) or not isinstance(new, dict) or set(old) != set(new):
        return False
    changed = {key for key in old if old[key] != new[key]}
    return bool(changed) and changed <= NARROW


def looks_like(rows):
    """Whether undo_audit's (first, at most two) rows are token-card UPDATEs this module reviews:
    more than one row, or one that changed more than its quantity or notes. The review reads the
    complete change set before trusting it."""
    return isinstance(rows, list) and len(rows) >= 1 and all(
        isinstance(row, dict) and row.get("table") == TOKENS and row.get("op") == "UPDATE" for row in rows) \
        and not (len(rows) == 1 and _narrow(rows[0]))


def _owned(raw, space):
    """Ownership is its own first pass: a hidden or other row makes the whole source unavailable."""
    if any(not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "UPDATE"
           or not isinstance(row.get("before"), dict) or not isinstance(row.get("after"), dict)
           or row["before"].get("space_id") != space or row["after"].get("space_id") != space for row in raw):
        raise UndoMissing()


def _complete(store, change_id, space):
    from .undo_mixed import MIXED_MAX
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        # The rows already seen are checked first, so a hidden source never answers as unsupported.
        _owned(store.undo_audit(change_id), space)
        raise UndoUnsupported("Restoring edited token cards needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 1 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    _owned(raw, space)
    if len(raw) > BATCH_MAX:
        raise Refused(f"That change updated {len(raw)} token-card rows; Undo restores at most {BATCH_MAX} at once. "
                      "Nothing was restored.")
    return raw


def _refuse(why, total):
    rows = sum(1 for reasons in why if reasons)
    if not rows:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {count}" for reason, count in counts.items())
    raise Refused(f"{rows} of the {total} updated token-card row{'s' if total > 1 else ''} can't be restored ({parts}). "
                  "Undo restores the whole change or nothing, so nothing was restored.")


def _image(image):
    return isinstance(image, dict) and set(image) == TOKEN_FIELDS \
        and type(image["id"]) is int and 1 <= image["id"] < 10 ** 18 \
        and type(image["position"]) is int and 0 <= image["position"] < 2 ** 31


def _parse(record):
    """The review item of one audit row, or the fixed reason it can't be restored."""
    old, new, rid = record.get("before"), record.get("after"), record.get("id")
    if type(rid) is not int or not 1 <= rid < 10 ** 18 or not _image(old) or not _image(new) \
            or old["id"] != new["id"] or record.get("key") != {"id": new["id"]}:
        return AUDIT
    if old["position"] != new["position"]:
        return MOVED
    try:
        current = _ordinary(new, TOKENS)
    except UndoUnsupported:
        return AUDIT
    try:
        restore = _ordinary(old, TOKENS)
    except UndoUnsupported:
        return INVALID
    if current == restore:
        return AUDIT
    return {"row_change_id": rid, "token_row_id": new["id"], "position": new["position"], "current": current,
            "restore": restore, "current_db": dict(new), "restore_db": dict(old), "label": rules.token_label(current)}


def _valid(item):
    """None when the recorded values are a row the Tokens page's edit would save now, else the reason."""
    cells = _cells(item["restore"])
    try:
        rules.validate_token_row(cells, "Token Undo")
        rules.token_extra(cells, "Token Undo")
        for value in cells.values():
            value.encode("utf-8", errors="strict")
    except (ValueError, UnicodeError):
        return INVALID
    if all(item["restore"][key] == item["current"][key] for key in FACES):
        return None     # The faces and printing it names now stay; the edit already checked them.
    try:
        checked, warnings = names.check_names(cells)
    except ValueError:
        return INVALID
    except Exception:
        return CARD_DATA
    if warnings:
        return CARD_DATA
    return None if checked == cells else INVALID


def _merges(old, new, others):
    """Whether tokens edit --separate would refuse new beside others (ops._never_merge's rule)."""
    if not (rules.token_identity(old) != rules.token_identity(new) or not rules.token_known(old) and rules.token_known(new)):
        return False
    same = [row for row in others if rules.token_identity(row) == rules.token_identity(new)]
    return bool(same) and rules.token_known(new) and any(rules.token_known(row) for row in same)


def _packs(item):
    """Whether restoring this row could change what a packed line holds (not a notes edit or a raise)."""
    changed = {key for key in item["current"] if item["current"][key] != item["restore"][key]}
    return bool(changed - NARROW) or item["restore"]["quantity"] < item["current"]["quantity"]


def _inverse(snapshot, space, items, stock):
    """Each reviewed row's ten values replaced in place, by id; every other row, the order, the
    other spaces and the rest of the inventory exactly as they are. ValueError for any other effect."""
    restores = {item["token_row_id"]: item["restore"] for item in items}
    rows = [row.replace(**_cells(restores[row.id])) if row.id in restores else row
            for row in snapshot.token_set(space).rows]
    settled = changes.prepare(snapshot, snapshot.with_tokens(space, rows))
    if settled != snapshot.replace(tokens=settled.tokens) or set(settled.tokens) != set(snapshot.tokens):
        raise ValueError("Unexpected inventory effect")
    single._other_tokens(snapshot, settled, space)
    expected = [{"id": row["id"], "row": restores.get(row["id"], row["row"])} for row in stock]
    if ordered_rows(settled.token_set(space)) != expected:
        raise ValueError("Token rows moved or changed")
    return settled


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
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
            or len({item["token_row_id"] for item in present}) != len(present):
        raise UndoUnsupported("A token-card Undo must name each updated row exactly once.")
    _refuse(why, total)
    label = f"Updates to {total} token-card row{'s' if total > 1 else ''}"
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current token cards cannot be checked. Reload Tokens.", label)
    try:
        stock, layout = single.settled_stock(snapshot, store, space)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    current = {row["id"]: row["row"] for row in stock}
    positions = {row["id"]: row["position"] for row in layout}
    for index, item in enumerate(items):
        rid = item["token_row_id"]
        if store.undo_latest(TOKENS, {"id": rid}) != item["row_change_id"] or current.get(rid) != item["current"] \
                or positions.get(rid) != item["position"]:
            why[index].append(EDITED)
    _refuse(why, total)
    for index, item in enumerate(items):
        reason = _valid(item)
        if reason:
            why[index].append(reason)
    restores = {item["token_row_id"]: item["restore"] for item in items}
    proposed = [{"id": row["id"], "row": restores.get(row["id"], row["row"])} for row in stock]
    for index, item in enumerate(items):
        others = [row["row"] for row in proposed if row["id"] != item["token_row_id"]]
        if _merges(item["current"], item["restore"], others):
            why[index].append(DUPLICATE)
    order = [row["id"] for row in sorted(proposed, key=lambda row: rules.token_sort_key(row["row"]))]
    ids = [row["id"] for row in stock]
    for index, item in enumerate(items):
        if order.index(item["token_row_id"]) != ids.index(item["token_row_id"]):
            why[index].append(ORDER)
    _refuse(why, total)
    try:
        settled = _inverse(snapshot, space, items, stock)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    packing = None
    if any(_packs(item) for item in items):
        try:
            allocations, capacities, held = _packing(snapshot, space, stock)
        except inventory.Unavailable:
            raise
        except Exception:
            raise UndoConflict("The packed token cards cannot be checked. Check them in Tokens.", label) from None
        try:
            after = _packing(settled, space, ordered_rows(settled.token_set(space)))
        except inventory.Unavailable:
            raise
        except Exception:
            after = None
        if after is None or after[0] != allocations:
            held_after = after[2] if after is not None else {}
            flagged = [index for index, item in enumerate(items) if _packs(item)
                       and (held.get(item["token_row_id"]) or held_after.get(item["token_row_id"]))]
            for index in flagged or [index for index, item in enumerate(items) if _packs(item)]:
                why[index].append(PACKED)
            _refuse(why, total)
        packing = {"allocations": allocations, "capacities": after[1]}
    receipt = [change_id, raw, files.rendered_sha256(snapshot.token_set(space)), stock, layout, packing,
               snapshot.revision, snapshot.decks_revision, ACTION]
    digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    # proof stays internal: the API projects only the rows' fields, their stable ids and the count.
    proof = {"rows": [{"id": item["token_row_id"], "current_db": item["current_db"], "restore_db": item["restore_db"]}
                      for item in items],
             "stock": stock, "layout": layout, "packing": packing}
    plan_rows = [{"row_change_id": item["row_change_id"], "token_row_id": item["token_row_id"], "label": item["label"],
                  "current": item["current"], "restore": item["restore"],
                  "fields": [{"field": field, "before": item["current"][field], "after": item["restore"][field]}
                             for field in rules.TOKEN_FIELDS if item["current"][field] != item["restore"][field]]}
                 for item in items]
    return {"change_id": change_id, "kind": KIND, "space": space, "action": ACTION, "row_count": total,
            "rows": plan_rows, "label": label, "expect": digest, "proof": proof}


def apply(snapshot, plan, change_id, space):
    """Every reviewed row's recorded values back in place; every other row exactly as it is. The
    database's own UPDATEs are proved again before commit (confirm). The summary names no value."""
    label, proof, count = plan["label"], plan["proof"], plan["row_count"]
    try:
        settled = _inverse(snapshot, space, plan["rows"], proof["stock"])
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNSAFE, label) from None
    fields = sorted({field["field"] for item in plan["rows"] for field in item["fields"]})
    cards = sum(row.qty or 0 for row in settled.token_set(space).rows)
    return settled, Summary(f"Undo change #{change_id}: restore {label}", {"edited": count, "cards": cards, "undo": 1},
                            {settled.token_set(space).path: fields},
                            {"undo_of": change_id, "space": space, "kind": KIND, "action": ACTION, "row_count": count,
                             "row_change_ids": [item["row_change_id"] for item in plan["rows"]],
                             "token_edit": {**proof, "label": label,
                                            "restore": {item["token_row_id"]: item["restore"] for item in plan["rows"]}}})


def restoring(summary):
    """Whether summary needs this module's transaction-local proof."""
    extra = summary.extra or {}
    return extra.get("action") == ACTION and extra.get("kind") == KIND and isinstance(extra.get("token_edit"), dict)


# The inventory parts a token-card Undo must leave exactly as they were (the audit rows prove it too).
UNTOUCHED = ("collections", "locations", "imports", "status", "products", "orders", "payloads", "watchlist", "accessories")


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows and token layout: exactly one
    UPDATE of each reviewed row, from the image the change left to the image it replaced, positions
    included; every other row, every position, the packing, the other spaces and the rest of the
    inventory unchanged. Any difference raises, so the transaction rolls back. Returns the summary
    with the restored ids, in the plan's row order, in place of the proof."""
    extra = dict(summary.extra)
    proof, space = extra.pop("token_edit"), extra["space"]
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
            if not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "UPDATE" \
                    or type(rid) is not int or rid not in reviewed or rid in seen or key != {"id": rid} \
                    or row.get("before") != reviewed[rid]["current_db"] or row.get("after") != reviewed[rid]["restore_db"]:
                raise ValueError("Another row or changed facts")
            seen.add(rid)
        restore = proof["restore"]
        stock = ordered_rows(saved.token_set(space))
        if stock != [{"id": item["id"], "row": restore.get(item["id"], item["row"])} for item in proof["stock"]]:
            raise ValueError("Token rows changed")
        if not isinstance(layout, list) or layout != proof["layout"]:
            raise ValueError("Persisted positions moved")
        if proof["packing"] is not None:
            allocations, capacities, _ = _packing(saved, space, stock)
            if allocations != proof["packing"]["allocations"] or capacities != proof["packing"]["capacities"]:
                raise ValueError("Packed cards would move")
        single._other_tokens(before, saved, space)
        if any(getattr(saved, part) != getattr(before, part) for part in UNTOUCHED):
            raise ValueError("Another inventory part changed")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed,
                   {**extra, "restored_token_row_ids": [item["id"] for item in proof["rows"]]})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook: this change set's rows, one more than the reviewed count so an
    extra row refuses, and the space's layout, on its own cursor."""
    count = len(summary.extra["token_edit"]["rows"])
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    layout = [{"id": rid, "position": position} for rid, position in cur.execute(
        "select id,position from token_card where space_id=%s order by position,id",
        (summary.extra["space"],)).fetchall()]
    return confirm(before, saved, summary, actual, layout)
