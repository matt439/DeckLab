"""Exact position-only survivor proofs for whole token-card row inverses.

Positions are internal ordering metadata, never a card/quantity edit. Source and
inverse row sets must match the ordinary writer exactly, including its allocator.
"""
import json

from . import rules
from .undo import BATCH_MAX, TOKEN_FIELDS, TOKENS, UndoConflict, UndoMissing, UndoUnsupported, _ordinary
from .undo_token_order import _image, _positions, _predicted, _stock

UNSAFE = "The token-card order cannot be checked exactly. Nothing was undone."


def looks_like(store, change_id, space, first):
    """Classify immutable complete token audit sources without trusting their first two rows."""
    if not isinstance(first, list) or len(first) < 2 or any(
            not isinstance(row, dict) or row.get("table") != TOKENS for row in first):
        return None
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        return None
    raw = reader(change_id)
    if not isinstance(raw, list) or not raw:
        raise UndoMissing()
    for row in raw:
        if not isinstance(row, dict) or row.get("table") != TOKENS:
            return None
        images = [row[key] for key in ("before", "after") if isinstance(row.get(key), dict)]
        if not images or any(image.get("space_id") != space for image in images):
            raise UndoMissing()
    if any(not isinstance(row.get("op"), str) for row in raw):
        return None
    ops = {row["op"] for row in raw}
    if ops in ({"INSERT", "UPDATE"}, {"DELETE", "UPDATE"}):
        operation = "INSERT" if "INSERT" in ops else "DELETE"
        try:
            split(raw, space, operation, bounded=False)
        except UndoUnsupported:
            return None
        return operation
    return None


def split(raw, space, operation, *, bounded=True):
    """Own complete source: target INSERTs/DELETEs plus strict position-only UPDATEs."""
    targets, moves, seen, audit_ids = [], [], set(), set()
    if not isinstance(raw, list) or not raw:
        raise UndoMissing()
    # Ownership precedes malformed-source/count explanations.
    for row in raw:
        images = [row[key] for key in ("before", "after") if isinstance(row.get(key), dict)] if isinstance(row, dict) else []
        if not isinstance(row, dict) or row.get("table") != TOKENS or not images \
                or any(image.get("space_id") != space for image in images):
            raise UndoMissing()
    if bounded and len(raw) > BATCH_MAX:
        raise UndoUnsupported(f"That change touched {len(raw)} token-card rows; Undo checks at most {BATCH_MAX} together.")
    for row in raw:
        old, new, op = row.get("before"), row.get("after"), row.get("op")
        rid = row.get("key", {}).get("id") if isinstance(row.get("key"), dict) else None
        aid = row.get("id")
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in seen or row.get("key") != {"id": rid} \
                or type(aid) is not int or not 1 <= aid < 10 ** 18 or aid in audit_ids:
            raise UndoUnsupported(UNSAFE)
        seen.add(rid)
        audit_ids.add(aid)
        for image in (old, new):
            if image is not None and (not isinstance(image, dict) or set(image) != TOKEN_FIELDS
                    or type(image["id"]) is not int or image["id"] != rid or type(image["position"]) is not int
                    or not 0 <= image["position"] < 2 ** 31):
                raise UndoUnsupported(UNSAFE)
        if op == operation and (old is None if operation == "INSERT" else new is None):
            targets.append(row)
        elif op == "UPDATE" and isinstance(old, dict) and isinstance(new, dict) \
                and old["position"] != new["position"] \
                and {key: old[key] for key in old if key != "position"} == {key: new[key] for key in new if key != "position"}:
            _ordinary(new, TOKENS)
            moves.append(row)
        else:
            raise UndoUnsupported("That token-card change includes values outside this whole-row Undo.")
    if not targets:
        raise UndoUnsupported("Only positions changed; there are no added or removed token cards to undo.")
    return targets, moves


def expected(stock, layout, restored, space):
    """Exact INSERT/DELETE/UPDATE images and persisted layout the ordinary writer predicts."""
    before, after = _stock(stock), _stock(restored)
    positions = _positions(layout, list(before))
    if sorted(after, key=lambda rid: rules.token_sort_key(after[rid])) != list(after):
        raise ValueError(UNSAFE)
    predicted = _predicted(list(after), positions)
    final_positions = {item["id"]: item["position"] for item in predicted}
    audit = []
    for rid in dict.fromkeys([*before, *after]):
        old = _image(before[rid], rid, positions[rid], space) if rid in before else None
        new = _image(after[rid], rid, final_positions[rid], space) if rid in after else None
        if old != new:
            audit.append({"table": TOKENS, "op": "DELETE" if new is None else "INSERT" if old is None else "UPDATE",
                          "key": {"id": rid}, "before": old, "after": new})
    if len(audit) > BATCH_MAX:
        raise ValueError(UNSAFE)
    return audit, predicted


def same_audit(actual, wanted):
    fields = {"table", "op", "key", "before", "after"}
    if not isinstance(actual, list) or len(actual) != len(wanted):
        return False
    def normalized(rows):
        return sorted(json.dumps({key: row[key] for key in fields}, sort_keys=True) for row in rows)
    return all(isinstance(row, dict) and fields <= set(row) <= fields | {"id"} for row in actual) \
        and normalized(actual) == normalized(wanted)


def restore_preview(stock, layout, additions, space):
    """Predict effects with absent historical ids as placeholders for equally new database ids."""
    restored = sorted([*stock, *additions], key=lambda item: rules.token_sort_key(item["row"]))
    expected(stock, layout, restored, space)


def source_proof(raw, stock, layout, space, store):
    """Reverse the immutable source, then prove its full ordinary forward effect and latest fence."""
    latest = getattr(store, "undo_token_latest", None)
    if not callable(latest) or latest(space) != max(row["id"] for row in raw):
        raise UndoConflict("The token list changed after that change. Nothing was undone.")
    current = _stock(stock)
    positions = _positions(layout, list(current))
    before, old_positions = dict(current), dict(positions)
    try:
        for row in raw:
            rid, old, new = row["key"]["id"], row["before"], row["after"]
            now = _image(current[rid], rid, positions[rid], space) if rid in current else None
            if now != new or store.undo_latest(TOKENS, row["key"]) != row["id"]:
                raise ValueError(UNSAFE)
            if old is None:
                del before[rid]
                del old_positions[rid]
            else:
                before[rid], old_positions[rid] = _ordinary(old, TOKENS), old["position"]
        ids = sorted(before, key=old_positions.get)
        historical = [{"id": rid, "row": before[rid]} for rid in ids]
        old_layout = [{"id": rid, "position": old_positions[rid]} for rid in ids]
        forward, predicted = expected(historical, old_layout, stock, space)
        if predicted != layout or not same_audit(raw, forward):
            raise ValueError(UNSAFE)
        return {"source": raw, "latest": latest(space)}
    except (KeyError, TypeError, ValueError, UndoUnsupported):
        raise UndoConflict(UNSAFE) from None
