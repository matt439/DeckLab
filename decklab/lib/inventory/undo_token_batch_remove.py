"""Remove 2-50 added token-card rows of one change set together (E11-S08).

The single unused-insert removal (undo_tokens.remove) made whole: the complete source must be
own-space token-card INSERTs only, every row must still be exactly as it was added and unpacked,
and nothing is selected partially. A batch with any row that can't be removed is refused whole,
naming how many and why in counts and fixed words only (undo_token_batch.Refused). Removal is
ordinary Remove of every row after one required reason; before commit, PgInventory.apply proves
exactly N own-space DELETEs of the reviewed ids and facts, every survivor and the packing
unchanged (confirm), or the whole change rolls back.
"""
import collections
import hashlib
import json

from decklab.lib import inventory, tokens

from . import Summary, changes, files, rules
from . import undo_token_delete as single
from .undo import BATCH_MAX, TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _identifier, \
    _ordinary, _source
from .undo_token_batch import Refused
from .undo_tokens import _packing, ordered_rows

ACTION = "token_batch_remove"
UNCONFIRMED = "The removed token-card rows could not be confirmed. Nothing was saved."

# Why a row can't be removed: fixed words, never a historical fact or another space's detail.
AUDIT = "audit record can't be checked"
UNVERIFIED = "physical pairing not verified"
EDITED = "edited or removed since"
AMBIGUOUS = "may be the same physical card as another recorded row"
PACKED = "packed in a deck or product line"


def looks_like(rows):
    """Whether undo_audit's (first) rows are token-card INSERTs of more than one row: the
    review reads the complete change set before trusting it."""
    return isinstance(rows, list) and len(rows) >= 2 and all(
        isinstance(row, dict) and row.get("table") == TOKENS and row.get("op") == "INSERT" for row in rows)


def _owned(raw, space):
    """Ownership is its own first pass: a hidden or other row makes the whole source unavailable."""
    if any(not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "INSERT"
           or row.get("before") is not None or not isinstance(row.get("after"), dict)
           or row["after"].get("space_id") != space for row in raw):
        raise UndoMissing()


def _complete(store, change_id, space):
    from .undo_mixed import MIXED_MAX
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        # The rows already seen are checked first, so a hidden source never answers as unsupported.
        _owned(store.undo_audit(change_id), space)
        raise UndoUnsupported("Removing added token cards together needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 2 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    _owned(raw, space)
    if len(raw) > BATCH_MAX:
        raise Refused(f"That change added {len(raw)} token-card rows; Undo removes at most {BATCH_MAX} at once. "
                      "Nothing was removed.")
    return raw


def _refuse(why, total):
    rows = sum(1 for reasons in why if reasons)
    if not rows:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {count}" for reason, count in counts.items())
    raise Refused(f"{rows} of the {total} added token-card rows can't be removed ({parts}). "
                  "Undo removes the whole change or nothing, so nothing was removed.")


def _remove(snapshot, items, space, stock, allocations, capacities):
    """Ordinary Remove of every row, proved as undo_tokens.remove proves one: (settled, summary)."""
    targets = {item["token_row_id"] for item in items}
    after, summary = snapshot, None
    for item in items:
        sheet = after.token_set(space)
        after, summary = tokens.ops.remove(after, space=space, base={**item["current"], "quantity": str(item["current"]["quantity"])},
                                           sha256=files.rendered_sha256(sheet))
    settled = changes.prepare(snapshot, after)
    expected = [row for row in stock if row["id"] not in targets]
    if ordered_rows(settled.token_set(space)) != expected or settled != snapshot.replace(tokens=settled.tokens):
        raise ValueError("Unexpected token removal effect")
    if set(settled.tokens) != set(snapshot.tokens) - ({space} if not expected else set()):
        raise ValueError("Unexpected token source change")
    single._other_tokens(snapshot, settled, space)
    new_allocations, new_capacities, _ = _packing(settled, space, expected)
    if new_allocations != allocations or new_capacities != {rid: free for rid, free in capacities.items() if rid not in targets}:
        raise ValueError("Packed cards would move between physical rows")
    counts, extra = summary.counts or {}, summary.extra or {}
    remaining = sum(row["row"]["quantity"] for row in expected)
    if type(counts.get("cards")) is not int or counts["cards"] != remaining or extra.get("index") is not None \
            or extra.get("resorted") is not False:
        raise ValueError("Unexpected physical total or ordering")
    return settled, remaining


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
    raw = _complete(store, change_id, space) if rows is None else rows
    total = len(raw)
    why = [[] for _ in raw]
    items = []
    for index, record in enumerate(raw):
        try:
            source, wanted, _ = _source([record], space)
        except UndoMissing:
            raise
        except UndoUnsupported as error:
            why[index].append(UNVERIFIED if "pairing" in str(error) else AUDIT)
            items.append(None)
            continue
        items.append({"source": source, "row_change_id": source["id"], "token_row_id": source["after"]["id"],
                      "position": source["after"]["position"], "current": wanted, "label": rules.token_label(wanted)})
    found = [item for item in items if item is not None]
    if len({item["row_change_id"] for item in found}) != len(found) or len({item["token_row_id"] for item in found}) != len(found):
        raise UndoUnsupported("A token batch must name each added row exactly once.")
    _refuse(why, total)
    label = f"{total} added token-card rows"
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current token cards cannot be checked. Reload Tokens.", label)
    for index, item in enumerate(items):
        if store.undo_latest(TOKENS, item["source"]["key"]) != item["row_change_id"]:
            why[index].append(EDITED)
    try:
        stock, layout = single.settled_stock(snapshot, store, space)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The added token rows cannot safely be reviewed here. Check their physical pairing and "
                           "packed cards in Tokens.", label) from None
    current = {row["id"]: row["row"] for row in stock}
    positions = {row["id"]: row["position"] for row in layout}
    for index, item in enumerate(items):
        rid = item["token_row_id"]
        if current.get(rid) != item["current"] or positions.get(rid) != item["position"]:
            why[index].append(EDITED)
        elif sum(rules.token_identity(row) == rules.token_identity(item["current"]) for row in current.values()) != 1:
            why[index].append(AMBIGUOUS)
    _refuse(why, total)
    try:
        allocations, capacities, held = _packing(snapshot, space, stock)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The added token rows' packed cards cannot be checked. Check them in Tokens.", label) from None
    for index, item in enumerate(items):
        if held.get(item["token_row_id"]) != 0:
            why[index].append(PACKED)
    _refuse(why, total)
    try:
        _, remaining = _remove(snapshot, items, space, stock, allocations, capacities)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The added token rows cannot safely be removed here. Check their physical pairing and "
                           "packed cards in Tokens.", label) from None
    sources = [item["source"] for item in items]
    receipt = [change_id, sources, files.rendered_sha256(snapshot.token_set(space)), stock, layout, allocations,
               capacities, held, snapshot.revision, snapshot.decks_revision, ACTION]
    digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    # proof stays internal: the API projects only the current facts, the stable ids and the count.
    proof = {"removed": [{"id": item["token_row_id"], "position": item["position"], "row": item["current"]} for item in items],
             "stock": stock, "layout": layout, "allocations": allocations, "capacities": capacities, "remaining": remaining}
    plan_rows = [{"row_change_id": item["row_change_id"], "token_row_id": item["token_row_id"], "label": item["label"],
                  "current": item["current"]} for item in items]
    return {"change_id": change_id, "kind": "tokens", "space": space, "action": ACTION, "row_count": total,
            "rows": plan_rows, "label": label, "cards": sum(item["current"]["quantity"] for item in items),
            "expect": digest, "reason_required": True, "proof": proof}


def apply(snapshot, plan, change_id, space, reason):
    """Ordinary Remove of every reviewed row; each survivor keeps its id, facts, order and packing.
    The database's own DELETEs are proved again before commit (confirm)."""
    label, proof = plan["label"], plan["proof"]
    try:
        settled, remaining = _remove(snapshot, plan["rows"], space, proof["stock"], proof["allocations"], proof["capacities"])
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The added token rows cannot safely be removed here. Check their physical pairing and "
                           "packed cards in Tokens.", label) from None
    count, removed = len(plan["rows"]), plan["cards"]
    return settled, Summary(f"Undo change #{change_id}: remove {count} added token-card rows ({removed} physical cards)",
                            {"cards": remaining, "removed_cards": removed, "removed_rows": count, "undo": 1},
                            {settled.token_set(space).path: ["remove"]},
                            {"undo_of": change_id, "space": space, "kind": "tokens", "action": ACTION, "row_count": count,
                             "row_change_ids": [item["row_change_id"] for item in plan["rows"]], "undo_reason": reason,
                             "token_remove": {**proof, "label": label}})


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows and token layout: exactly the
    reviewed rows deleted, every survivor's id, facts, position and packing unchanged, no other
    space touched. Any difference raises, so the transaction rolls back. Returns the summary with
    the removed ids, in the plan's row order, in place of the proof."""
    extra = dict(summary.extra)
    proof, space = extra.pop("token_remove"), extra["space"]
    removed = {item["id"]: item for item in proof["removed"]}
    survivors = [row for row in proof["stock"] if row["id"] not in removed]
    try:
        if not isinstance(actual, list) or len(actual) != len(removed) or not 2 <= len(removed) <= BATCH_MAX:
            raise ValueError("Not exactly the reviewed audited rows")
        seen = set()
        for row in actual:
            old = row.get("before") if isinstance(row, dict) else None
            if not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "DELETE" \
                    or row.get("after") is not None or not isinstance(old, dict) or set(old) != TOKEN_FIELDS \
                    or old["space_id"] != space:
                raise ValueError("Not an own-space token DELETE")
            rid = old["id"]
            if type(rid) is not int or rid not in removed or rid in seen or row.get("key") != {"id": rid} \
                    or old["position"] != removed[rid]["position"] or _ordinary(old, TOKENS) != removed[rid]["row"]:
                raise ValueError("Another row or changed facts")
            seen.add(rid)
        stock = ordered_rows(saved.token_set(space))
        if stock != survivors:
            raise ValueError("Survivors changed")
        if not isinstance(layout, list) or layout != [row for row in proof["layout"] if row["id"] not in removed]:
            raise ValueError("Persisted positions moved")
        allocations, capacities, _ = _packing(saved, space, stock)
        if allocations != proof["allocations"]                 or capacities != {rid: free for rid, free in proof["capacities"].items() if rid not in removed}:
            raise ValueError("Packed cards would move")
        single._other_tokens(before, saved, space)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    return Summary(summary.text, summary.counts, summary.changed,
                   {**extra, "removed_token_row_ids": [item["id"] for item in proof["removed"]]})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook (through undo_token_delete's): this change set's rows, one more
    than the batch so an extra row refuses, and the space's layout, on its own cursor."""
    count = len(summary.extra["token_remove"]["removed"])
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    layout = [{"id": rid, "position": position} for rid, position in cur.execute(
        "select id,position from token_card where space_id=%s order by position,id",
        (summary.extra["space"],)).fetchall()]
    return confirm(before, saved, summary, actual, layout)
