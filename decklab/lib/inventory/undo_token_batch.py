"""Restore 2-50 deleted token-card rows of one change set, each under a fresh id (E11-S08).

The single-row restore (undo_token_delete) made whole: the complete source must be own-space
token-card DELETEs only, every row must pass that restore's checks, and nothing is selected
partially. A batch with any row that can't be restored is refused whole, naming how many and
why in counts and fixed words only. Restoration is ordinary Add of every row after one
whole-count confirmation; before commit, PgInventory.apply proves exactly N own-space INSERTs
with fresh ids and the reviewed facts, every survivor and the packing unchanged (confirm), or
the whole change rolls back.
"""
import collections
import hashlib
import json

from decklab.lib import inventory, tokens

from . import Summary, changes, files, rules
from . import undo_token_delete as single
from .undo import BATCH_MAX, TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _cells, _identifier, _ordinary
from .undo_tokens import _packing, ordered_rows

ACTION = "token_batch_add"
IDENTITY_POLICY = single.IDENTITY_POLICY
UNCONFIRMED = "The restored token-card rows could not be confirmed. Nothing was saved."

# Why a row can't be restored: fixed words, never a historical fact or another space's detail.
AUDIT = "audit record can't be checked"
UNVERIFIED = "printing or physical pairing not verified"
CARD_DATA = "printing can't be checked with the current card data"
TWIN = "may be the same physical card as another row of the change"
RECORDED = "may already be recorded as a remaining token card"
PACKED = "may be claimed by a packed deck or product line"


class Refused(UndoUnsupported):
    """A whole-batch refusal naming only counts and fixed reasons: safe to show the space's own
    people, since it's raised only after the complete source was proved to be their space's."""


def looks_like(rows):
    """Whether undo_audit's (first) rows are token-card DELETEs of more than one row: the
    review reads the complete change set before trusting it."""
    return isinstance(rows, list) and len(rows) >= 2 and all(
        isinstance(row, dict) and row.get("table") == TOKENS and row.get("op") == "DELETE" for row in rows)


def _complete(store, change_id, space):
    from .undo_mixed import MIXED_MAX
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        raise UndoUnsupported("Restoring deleted token cards together needs the complete database audit trail.")
    raw = reader(change_id)
    if not isinstance(raw, list) or not 2 <= len(raw) <= MIXED_MAX:
        raise UndoMissing()
    # Ownership is its own first pass: a hidden or other row makes the whole source unavailable.
    if any(not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "DELETE"
           or not isinstance(row.get("before"), dict) or row["before"].get("space_id") != space
           or row.get("after") is not None for row in raw):
        raise UndoMissing()
    if len(raw) > BATCH_MAX:
        raise Refused(f"That change deleted {len(raw)} token-card rows; Undo restores at most {BATCH_MAX} at once. "
                      "Nothing was restored.")
    return raw


def _refuse(why, total):
    rows = sum(1 for reasons in why if reasons)
    if not rows:
        return
    counts = collections.Counter(reason for reasons in why for reason in dict.fromkeys(reasons))
    parts = "; ".join(f"{reason}: {count}" for reason, count in counts.items())
    raise Refused(f"{rows} of the {total} deleted token-card rows can't be restored ({parts}). "
                  "Undo restores the whole change or nothing, so nothing was restored.")


def review(change_id, space, snapshot, store, rows=None):
    _identifier(change_id)
    raw = _complete(store, change_id, space) if rows is None else rows
    total = len(raw)
    why = [[] for _ in raw]
    items = []
    for index, record in enumerate(raw):
        try:
            source, restored = single.source_record([record], space)
        except UndoMissing:
            raise
        except UndoUnsupported as error:
            why[index].append(UNVERIFIED if "printing" in str(error) else AUDIT)
            items.append(None)
            continue
        items.append({"source": source, "restore": restored, "label": rules.token_label(restored)})
    found = [item for item in items if item is not None]
    if len({item["source"]["id"] for item in found}) != len(found) \
            or len({item["source"]["before"]["id"] for item in found}) != len(found):
        raise UndoUnsupported("A token batch must name each deleted row exactly once.")
    for i, item in enumerate(items):
        for j in range(i + 1, len(items)):
            other = items[j]
            if item is not None and other is not None and single.same_card(item["restore"], other["restore"]):
                why[i].append(TWIN)
                why[j].append(TWIN)
    _refuse(why, total)
    label = f"{total} deleted token-card rows"
    if snapshot.stale or not snapshot.persisted or not isinstance(snapshot.revision, str) or not snapshot.revision \
            or not isinstance(snapshot.decks_revision, str) or not snapshot.decks_revision:
        raise UndoConflict("The current token cards cannot be checked. Reload Tokens.", label)
    latest_reader = getattr(store, "undo_token_latest", None)
    if not callable(latest_reader):
        raise UndoUnsupported("This token review needs a complete current token audit fence.")
    latest = latest_reader(space)
    if type(latest) is not int or latest != max(item["source"]["id"] for item in items) \
            or any(store.undo_latest(TOKENS, item["source"]["key"]) != item["source"]["id"] for item in items):
        raise UndoConflict("The token cards were touched after that removal. Nothing was restored.", label)
    for index, item in enumerate(items):
        try:
            single._verified_printing(item["restore"])
        except UndoUnsupported:
            why[index].append(CARD_DATA)
    _refuse(why, total)
    try:
        stock, layout = single.settled_stock(snapshot, store, space)
        lines = single.packed_lines(snapshot, space)
        if len(lines) * max(len(stock), len(items)) > single.MAX_MATCHES:
            raise ValueError("Too many packed lines to match")
        with inventory.pinned(snapshot):
            for index, item in enumerate(items):
                if single.collides(stock, item["source"]["before"]["id"], item["restore"]):
                    why[index].append(RECORDED)
                cells = _cells(item["restore"])
                if any(tokens.reserve.matches(line, cells) for line in lines):
                    why[index].append(PACKED)
            allocations, capacities, held = _packing(snapshot, space, stock) if not any(why) else (None, None, None)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The removed token records cannot safely be reviewed here. Check their identities and "
                           "packed cards in Tokens.", label) from None
    _refuse(why, total)
    sources = [item["source"] for item in items]
    receipt = [change_id, sources, latest, files.rendered_sha256(snapshot.token_set(space)), stock, layout,
               allocations, capacities, held, snapshot.revision, snapshot.decks_revision, IDENTITY_POLICY, ACTION]
    digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    rows = [{"row_change_id": item["source"]["id"], "label": item["label"], "restore": item["restore"]} for item in items]
    # proof stays internal: the API projects only the historical facts and the fixed policy.
    proof = {"deleted_ids": [item["source"]["before"]["id"] for item in items], "stock": stock, "layout": layout,
             "allocations": allocations, "capacities": capacities}
    return {"change_id": change_id, "kind": "tokens", "space": space, "action": ACTION, "row_count": total,
            "rows": rows, "label": label, "cards": sum(item["restore"]["quantity"] for item in items), "expect": digest,
            "identity_policy": IDENTITY_POLICY, "physical_confirmation_required": True, "packing_restored": False,
            "proof": proof}


def _facts(row):
    values = row.as_dict()
    return {**values, "quantity": int(values["quantity"])}


def apply(snapshot, plan, change_id, space):
    """Ordinary Add of every reviewed row; each survivor keeps its id, facts and order. The new
    rows get their ids from the database, and the proof runs again before commit (confirm)."""
    label, proof = plan["label"], plan["proof"]
    wanted = [item["restore"] for item in plan["rows"]]
    try:
        stock = ordered_rows(snapshot.token_set(space))
        if stock != proof["stock"]:
            raise ValueError("Token stock changed after the review")
        after, summary = snapshot, None
        for row in wanted:
            sheet = after.token_set(space)
            after, summary = tokens.ops.add(after, space=space, row=_cells(row),
                                            sha256=files.rendered_sha256(sheet) if sheet.exists else None)
            if (summary.extra or {}).get("resorted") is not False:
                raise ValueError("Unexpected ordering")
        settled = changes.prepare(snapshot, after)
        rows = settled.token_set(space).rows
        # Their snapshot ids (0, or line numbers in a list that had none) are not the database's.
        known = {item["id"] for item in stock}
        fresh = [_facts(row) for row in rows if row.id not in known]
        kept = [{"id": row.id, "row": _facts(row)} for row in rows if row.id in known]
        key = lambda row: json.dumps(row, sort_keys=True)  # noqa: E731
        if len(rows) != len(stock) + len(wanted) or kept != stock \
                or collections.Counter(map(key, fresh)) != collections.Counter(map(key, wanted)):
            raise ValueError("Unexpected token addition effect")
        if settled != snapshot.replace(tokens=settled.tokens) or set(settled.tokens) != set(snapshot.tokens) | {space}:
            raise ValueError("Unexpected source change")
        single._other_tokens(snapshot, settled, space)
        # The space's physical total after the save (tokens.ops.add's count); the message names only the restored ones.
        restored = sum(row["quantity"] for row in wanted)
        cards = sum(item["row"]["quantity"] for item in stock) + restored
        counts = summary.counts or {}
        if type(counts.get("cards")) is not int or counts["cards"] != cards:
            raise ValueError("Unexpected physical total")
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The deleted token rows cannot safely be restored here. Check their physical pairing and "
                           "packed cards in Tokens.", label) from None
    count = len(wanted)
    return settled, Summary(f"Undo change #{change_id}: restore {count} deleted token-card rows ({restored} physical cards) as new rows",
                            {"cards": cards, "restored_cards": restored, "added_rows": count, "undo": 1}, {settled.token_set(space).path: ["add"]},
                            {"undo_of": change_id, "space": space, "kind": "tokens", "action": ACTION, "row_count": count,
                             "row_change_ids": [item["row_change_id"] for item in plan["rows"]], "confirmed_owned": True,
                             "token_restore": {**proof, "restore": wanted, "label": label}})


def confirm(before, saved, summary, actual, layout):
    """Prove the saved effect from the transaction's own audit rows and token layout (as
    undo_token_delete.confirm, for every row). Any difference raises, so the transaction rolls
    back. Returns the summary with the new ids, in the plan's row order, in place of the proof."""
    extra = dict(summary.extra)
    proof, space = extra.pop("token_restore"), extra["space"]
    wanted = proof["restore"]
    try:
        if not isinstance(actual, list) or len(actual) != len(wanted) or not 2 <= len(wanted) <= BATCH_MAX:
            raise ValueError("Not exactly the reviewed audited rows")
        deleted, survivors = set(proof["deleted_ids"]), {item["id"] for item in proof["stock"]}
        matched, positions, open_rows = {}, {}, list(range(len(wanted)))
        for row in actual:
            new = row.get("after")
            if not isinstance(row, dict) or row.get("table") != TOKENS or row.get("op") != "INSERT" \
                    or row.get("before") is not None or not isinstance(new, dict) or set(new) != TOKEN_FIELDS \
                    or new["space_id"] != space:
                raise ValueError("Not an own-space token INSERT")
            rid = new["id"]
            if type(rid) is not int or not 1 <= rid < 10 ** 18 or row.get("key") != {"id": rid} \
                    or rid in deleted or rid in survivors or rid in matched:
                raise ValueError("Reused id")
            facts = _ordinary(new, TOKENS)
            index = next((i for i in open_rows if wanted[i] == facts), None)
            if index is None:
                raise ValueError("Changed facts")
            open_rows.remove(index)
            matched[rid], positions[rid] = index, new["position"]
        stock = ordered_rows(saved.token_set(space))
        if [item for item in stock if item["id"] not in matched] != proof["stock"] \
                or sorted(item["id"] for item in stock if item["id"] in matched) != sorted(matched) \
                or any(item["row"] != wanted[matched[item["id"]]] for item in stock if item["id"] in matched):
            raise ValueError("Survivors or the restored rows changed")
        if not isinstance(layout, list) or [item.get("id") for item in layout] != [item["id"] for item in stock] \
                or [item for item in layout if item.get("id") not in matched] != proof["layout"] \
                or any(item.get("position") != positions[item["id"]] for item in layout if item.get("id") in matched):
            raise ValueError("Persisted positions moved")
        allocations, capacities, held = _packing(saved, space, stock)
        if allocations != proof["allocations"] or any(held.get(rid) != 0 for rid in matched) \
                or {key: value for key, value in capacities.items() if key not in matched} != proof["capacities"]:
            raise ValueError("Packed cards would move")
        single._other_tokens(before, saved, space)
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict(UNCONFIRMED, proof.get("label")) from None
    ids = [rid for rid, _ in sorted(matched.items(), key=lambda pair: pair[1])]
    return Summary(summary.text, summary.counts, summary.changed, {**extra, "added_token_row_ids": ids})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    """PgInventory.apply's hook (through undo_token_delete's): this change set's rows, one more
    than the batch so an extra row refuses, and the space's layout, on its own cursor."""
    count = len(summary.extra["token_restore"]["restore"])
    actual = [{"id": rid, "table": table, "op": op, "key": key, "before": old, "after": new}
              for rid, table, op, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change "
                  "where change_set_id=%s order by id limit %s", (change_set, count + 1)).fetchall()]
    layout = [{"id": rid, "position": position} for rid, position in cur.execute(
        "select id,position from token_card where space_id=%s order by position,id",
        (summary.extra["space"],)).fetchall()]
    return confirm(before, saved, summary, actual, layout)
