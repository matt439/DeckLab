"""Whole own-space collection identity/mixed inverses from complete immutable audit rows.

No operation name or displayed Activity row is write authority. Ordinary collection
helpers reproduce the source and inverse; the database proves the actual inverse
row set before commit. Historical storage locations are not restored.
"""
import hashlib
import json

from decklab.lib import inventory

from . import Summary, backend, changes, files, ops_collection, paths, rules
from .undo import (
    BATCH_MAX,
    COLLECTION,
    COLLECTION_KEYS,
    COLLECTION_SCHEMAS,
    UndoConflict,
    UndoMissing,
    UndoUnsupported,
    _cells,
    _deleted_row,
    _identifier,
    _label,
    _ordinary,
    _remaining_collection,
    removal_reason,
)

ACTION = "collection_change_restore"
PROOF = "collection_change"
UNCONFIRMED = "The complete collection Undo could not be confirmed. Nothing was saved."
UNSAFE = "The complete collection change cannot be restored exactly. Use the Collection editor."


class Refused(UndoUnsupported):
    """Fixed explanatory wording, raised only after complete-source ownership is proved."""


def handles(raw):
    if not isinstance(raw, list) or not raw or any(not isinstance(row, dict) or row.get("table") != COLLECTION
                                                 or not isinstance(row.get("op"), str) for row in raw):
        return False
    operations = {row["op"] for row in raw}
    fields = ["set_code" if field == "set" else field for field in rules.FIELDS]
    return len(operations) > 1 or operations == {"UPDATE"} and any(
        isinstance(row.get("before"), dict) and isinstance(row.get("after"), dict)
        and (row["before"].get("name") != row["after"].get("name")
             or row["before"].get("location", "") != row["after"].get("location", "")
             and any(row["before"].get(field) != row["after"].get(field) for field in fields)) for row in raw)


def classify(store, change_id, first):
    if not isinstance(first, list) or not first or any(not isinstance(row, dict) or row.get("table") != COLLECTION for row in first):
        return False
    reader = getattr(store, "undo_audit_rows", None)
    return callable(reader) and handles(reader(change_id))


def _row(image, space):
    if not isinstance(image, dict) or set(image) not in COLLECTION_SCHEMAS or image.get("space_id") != space:
        raise UndoUnsupported(UNSAFE)
    ordinary = _ordinary(image, COLLECTION)
    try:
        for value in ordinary.values():
            if isinstance(value, str):
                value.encode("utf-8", errors="strict")
        location = image.get("location", "")
        if not isinstance(location, str) or rules.clean_location(location) != location:
            raise ValueError(UNSAFE)
    except (UnicodeError, ValueError):
        raise UndoUnsupported(UNSAFE) from None
    return ordinary


def _source(raw, space):
    if not isinstance(raw, list) or not raw:
        raise UndoMissing()
    from .undo_mixed import MIXED_MAX
    if len(raw) > MIXED_MAX:    # reader cap reached: the complete source's ownership is unknown
        raise UndoMissing()
    # Ownership precedes counts, schemas, card data, labels and current-stock reads.
    for record in raw:
        images = [record[key] for key in ("before", "after") if isinstance(record.get(key), dict)] if isinstance(record, dict) else []
        if not isinstance(record, dict) or record.get("table") != COLLECTION or not images \
                or any(image.get("space_id") != space for image in images):
            raise UndoMissing()
    if len(raw) > BATCH_MAX:
        raise Refused(f"That complete change touched {len(raw)} collection rows; Undo checks at most {BATCH_MAX} together.")
    rows, seen, audit_ids = [], set(), set()
    for record in raw:
        old, new, operation = record.get("before"), record.get("after"), record.get("op")
        _identifier(record.get("id"))
        key = record.get("key")
        if not isinstance(key, dict) or set(key) != COLLECTION_KEYS or record["id"] in audit_ids:
            raise UndoUnsupported(UNSAFE)
        if operation == "INSERT" and old is None and isinstance(new, dict):
            current, restored = _row(new, space), None
        elif operation == "DELETE" and new is None and isinstance(old, dict):
            current, restored = None, _row(old, space)
        elif operation == "UPDATE" and isinstance(old, dict) and isinstance(new, dict):
            current, restored = _row(new, space), _row(old, space)
            if current == restored:    # location-only changes keep their separate tool
                raise Refused("A location-only row cannot be selected out of a complete collection Undo.")
        else:
            raise UndoUnsupported(UNSAFE)
        for image in (old, new):
            if image is not None and any(key[field] != image.get(field) for field in COLLECTION_KEYS):
                raise UndoUnsupported("This change needs a primary-key rewrite outside normal collection operations.")
        identity = rules.ident(current or restored)
        if identity in seen:
            raise UndoUnsupported("The complete source touches a collection identity more than once.")
        seen.add(identity)
        audit_ids.add(record["id"])
        rows.append({"row_change_id": record["id"], "key": dict(key), "current": current, "restore": restored,
                     "label": _label(COLLECTION, current or restored)})
    return rows


def _dbrow(row, space, location=""):
    return {"set_code" if key == "set" else key: value for key, value in row.items()} | {"space_id": space, "location": location}


def _audit(before, after, space):
    left, right = _remaining_collection(before, space, "Collection change"), _remaining_collection(after, space, "Collection change")
    old_locations, new_locations = before.locations_of(space), after.locations_of(space)
    result = []
    for key in sorted(set(left) | set(right)):
        old = _dbrow(left[key], space, old_locations.get(key, "")) if key in left else None
        new = _dbrow(right[key], space, new_locations.get(key, "")) if key in right else None
        if old != new:
            result.append({"table": COLLECTION, "op": "DELETE" if new is None else "INSERT" if old is None else "UPDATE",
                           "key": {"space_id": space, "set_code": key[0], "collector_number": key[1], "finish": key[2]},
                           "before": old, "after": new})
    return result


def _same_audit(actual, wanted):
    if not isinstance(actual, list) or len(actual) != len(wanted):
        return False
    def canonical(rows):
        out = []
        for row in rows:
            fields = {"table", "op", "key", "before", "after"}
            if not isinstance(row, dict) or not fields <= set(row) <= fields | {"id"}:
                return None
            value = {key: row[key] for key in ("table", "op", "key", "before", "after")}
            for side in ("before", "after"):
                if value[side] is not None:
                    if set(value[side]) not in COLLECTION_SCHEMAS:
                        return None
                    value[side] = {**value[side], "location": value[side].get("location", "")}
            out.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return sorted(out)
    left, right = canonical(actual), canonical(wanted)
    return left is not None and left == right


def _ordinary_change(snapshot, rows, space, *, backwards=True, raw=None):
    after = snapshot
    raw_by_key = {tuple(record["key"][field] for field in ("set_code", "collector_number", "finish")): record for record in raw or ()}
    added = [item for item in rows if item["current"] is not None and item["restore"] is None]
    deleted = [item for item in rows if item["current"] is None and item["restore"] is not None]
    paired = added + deleted if len(added) == len(deleted) == 1 else []
    if paired:
        current, restored = (added[0]["current"], deleted[0]["restore"]) if backwards else (deleted[0]["restore"], added[0]["current"])
        location = None if backwards else raw_by_key[rules.ident(restored)]["after"].get("location", "")
        after, _ = ops_collection.edit(after, space, list(rules.ident(current)), _cells(restored),
                                       sha256=files.rendered_sha256(after.collection(space)),
                                       expect_decks_revision=snapshot.decks_revision,
                                       **({"location": location} if location is not None else {}))
    def fields(item):
        return (item["current"], item["restore"]) if backwards else (item["restore"], item["current"])
    for item in rows:
        if item in paired:
            continue
        current, restored = fields(item)
        if current is not None and restored is None:
            after, _ = ops_collection.remove(after, space, list(rules.ident(current)),
                                             sha256=files.rendered_sha256(after.collection(space)),
                                             expect_decks_revision=snapshot.decks_revision)
    for item in rows:
        if item in paired:
            continue
        current, restored = fields(item)
        if restored is None:
            continue
        location = None if backwards else (raw_by_key[rules.ident(restored)]["after"] or {}).get("location", "")
        if current is None:
            after, _ = ops_collection.add(after, space, _cells(restored), sha256=files.rendered_sha256(after.collection(space)),
                                          **({"location": location} if location is not None else {}))
        else:
            after, _ = ops_collection.edit(after, space, list(rules.ident(current)), _cells(restored),
                                           sha256=files.rendered_sha256(after.collection(space)),
                                           expect_decks_revision=snapshot.decks_revision,
                                           **({"location": location} if location is not None else {}))
    return changes.prepare(snapshot, after)


def _source_proof(snapshot, raw, rows, space):
    before_rows = _remaining_collection(snapshot, space, "Collection change")
    locations = dict(snapshot.locations_of(space))
    for record, item in zip(raw, rows):
        key = rules.ident(item["current"] or item["restore"])
        if item["restore"] is None:
            before_rows.pop(key, None)
            locations.pop(key, None)
        else:
            before_rows[key] = item["restore"]
            location = record["before"].get("location", "")
            if location:
                locations[key] = location
            else:
                locations.pop(key, None)
    historical = snapshot.with_collection(space, [_cells(row) for row in before_rows.values()]).with_locations(space, locations)
    forward = _ordinary_change(historical, rows, space, backwards=False, raw=raw)
    if not _same_audit(raw, _audit(historical, forward, space)):
        raise UndoUnsupported("The complete source cannot be reproduced by ordinary collection operations.")


def _unchanged(before, after, space):
    if set(changes.changed(before, after)) - {paths.collection(space), paths.locations(space)} \
            or after.replace(collections=before.collections, locations=before.locations, revision=before.revision,
                             decks_revision=before.decks_revision) != before \
            or any(after.collection(owner) != before.collection(owner) or after.location_sheet(owner) != before.location_sheet(owner)
                   for owner in set(before.collections) | set(after.collections) | set(before.locations) | set(after.locations) if owner != space):
        raise UndoConflict(UNSAFE)


def review(change_id, space, snapshot, store=None):
    _identifier(change_id)
    store = backend() if store is None else store
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader) or not callable(getattr(store, "undo_latest", None)):
        raise UndoUnsupported("This Undo needs the complete database audit trail.")
    raw = reader(change_id)
    rows = _source(raw, space)
    if snapshot.stale or not snapshot.persisted:
        raise UndoConflict("The current collection cannot be checked. Reload Collection.")
    current = _remaining_collection(snapshot, space, "Collection change")
    ops_collection.locations_sha256_of(snapshot, space)
    latest = []
    for item in rows:
        touch = store.undo_latest(COLLECTION, item["key"])
        if touch != item["row_change_id"] or current.get(rules.ident(item["current"] or item["restore"])) != item["current"]:
            raise UndoConflict("This row changed after the selected change. Nothing was undone.", item["label"])
        latest.append(touch)
        if item["restore"] is not None and (item["current"] is None or item["restore"]["name"] != item["current"]["name"]):
            _deleted_row(item["restore"])
    added = [item for item in rows if item["current"] is not None and item["restore"] is None]
    deleted = [item for item in rows if item["current"] is None and item["restore"] is not None]
    locations = snapshot.locations_of(space)
    transfer = None
    if len(added) == len(deleted) == 1:
        transfer = {"from": added[0]["key"], "to": deleted[0]["key"], "location": locations.get(rules.ident(added[0]["current"]), "")}
    elif added and deleted and any(locations.get(rules.ident(item["current"])) for item in added):
        raise Refused("The complete change has ambiguous current storage locations. Use the Collection editor; no location was erased or guessed.")
    try:
        _source_proof(snapshot, raw, rows, space)
        after = _ordinary_change(snapshot, rows, space)
        _unchanged(snapshot, after, space)
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError, KeyError, UnicodeError):
        raise UndoConflict(UNSAFE) from None
    from . import undo_mixed
    reductions = []
    for record, item in zip(raw, rows):
        old, restored = item["current"], item["restore"]
        if old is not None and (restored is None or old["name"] != restored["name"] or old["quantity"] > restored["quantity"]):
            reductions.append({**record, "op": "INSERT" if restored is None or old["name"] != restored["name"] else "UPDATE"})
    if reductions:
        undo_mixed._collection_proof(snapshot, after, space, reductions, "Complete collection change")
    reason = any(item["current"] is not None and (item["restore"] is None or item["current"]["name"] != item["restore"]["name"]) for item in rows)
    confirm = any(item["restore"] is not None and (item["current"] is None or item["current"]["name"] != item["restore"]["name"]) for item in rows)
    expected = _audit(snapshot, after, space)
    if len(expected) != len(rows):
        raise UndoUnsupported("The complete source does not have an exact whole-row inverse.")
    receipt = [change_id, raw, latest, sorted(current.items()), sorted(locations.items()), expected]
    digest = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"change_id": change_id, "kind": "collection", "space": space, "action": ACTION, "label": f"Complete collection change ({len(rows)} row{'s' if len(rows) != 1 else ''})",
            "row_count": len(rows), "rows": rows, "expect": digest, "reason_required": reason, "physical_confirmation_required": confirm,
            "location_transfer": transfer,
            "proof": {"expected": expected, "collection": _remaining_collection(after, space, "Collection change"), "locations": after.locations_of(space)}}


def apply(snapshot, plan, change_id, space, reason=None):
    if plan["reason_required"]:
        reason = removal_reason(reason)
    elif reason is not None:
        raise inventory.Invalid("This complete collection Undo removes no row or identity, so it takes no reason.")
    after = _ordinary_change(snapshot, plan["rows"], space)
    _unchanged(snapshot, after, space)
    if not _same_audit(_audit(snapshot, after, space), plan["proof"]["expected"]):
        raise UndoConflict(UNSAFE)
    return after, Summary(f"Undo change #{change_id}: restore the complete collection change ({plan['row_count']} row{'s' if plan['row_count'] != 1 else ''})",
                          {"rows": plan["row_count"], "undo": 1}, changes.changed(snapshot, after),
                          {"undo_of": change_id, "kind": "collection", "space": space, "action": ACTION,
                           "row_count": plan["row_count"], "row_change_ids": [item["row_change_id"] for item in plan["rows"]],
                           "expect": plan["expect"], "undo_reason": reason,
                           "confirmed_owned": plan["physical_confirmation_required"], PROOF: plan["proof"]})


def restoring(summary):
    return (summary.extra or {}).get("action") == ACTION and isinstance((summary.extra or {}).get(PROOF), dict)


def confirm(before, saved, summary, actual, recorded_reason):
    extra = dict(summary.extra)
    proof, space = extra.pop(PROOF), extra["space"]
    try:
        source_ids = extra.get("row_change_ids")
        if not isinstance(source_ids, list) or len(source_ids) != extra.get("row_count") \
                or any(type(rid) is not int or not 0 < rid < 10 ** 18 for rid in source_ids) \
                or len(set(source_ids)) != len(source_ids) or not source_ids or not isinstance(actual, list):
            raise ValueError(UNCONFIRMED)
        actual_ids = [row.get("id") if isinstance(row, dict) else None for row in actual]
        if any(type(rid) is not int or not max(source_ids) < rid < 2 ** 63 for rid in actual_ids) \
                or len(set(actual_ids)) != len(actual_ids):
            raise ValueError(UNCONFIRMED)
        if not _same_audit(actual, proof["expected"]) or recorded_reason != extra["undo_reason"] \
                or _remaining_collection(saved, space, "Collection change") != proof["collection"] \
                or saved.locations_of(space) != proof["locations"]:
            raise ValueError(UNCONFIRMED)
        _unchanged(before, saved, space)
    except (inventory.Invalid, inventory.Conflict, ValueError, TypeError, KeyError):
        raise UndoConflict(UNCONFIRMED) from None
    return Summary(summary.text, summary.counts, summary.changed, {**extra, "collection_confirmed": True})


def confirm_in_transaction(cur, change_set, before, saved, summary):
    actual = [{"id": rid, "table": table, "op": operation, "key": key, "before": old, "after": new}
              for rid, table, operation, key, old, new in cur.execute(
                  "select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s order by id limit %s",
                  (change_set, summary.extra["row_count"] + 1)).fetchall()]
    reason = cur.execute("select reason from audit.change_set where id=%s", (change_set,)).fetchone()
    return confirm(before, saved, summary, actual, reason[0] if reason else None)
