"""Guarded accessory metadata UPDATE and image-free INSERT/DELETE inverses.

Accessory image bytes are not audited. This restores only recorded text/links;
an old source URL makes no claim about the retained photograph.
"""
import csv
import hashlib
import io
import json

from decklab.lib import accessories
from decklab.lib.state import Invalid

from . import Summary, backend, changes, paths, rules
from .undo import SHA, UndoConflict, UndoMissing, UndoUnsupported, _identifier, removal_reason

FIELDS = ("brand", "name", "colour", "notes", "link", "image_source")
META = ("id", "kind", "owner", *FIELDS)
RAW = frozenset(rules.ACCESSORY_FIELDS)


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _scope(owners):
    if owners is None:
        return None
    if not isinstance(owners, (set, frozenset, tuple, list)) or any(not isinstance(v, str) for v in owners):
        raise UndoMissing()
    return sorted(set(owners))


def source_record(rows, owners):
    """Complete global single-row source and writable owners, before any labels."""
    scope = _scope(owners)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise UndoMissing()
    row = rows[0]
    old, new = row.get("before"), row.get("after")
    insert = row.get("op") == "INSERT" and "before" in row and old is None and isinstance(new, dict)
    delete = row.get("op") == "DELETE" and "after" in row and new is None and isinstance(old, dict)
    if row.get("table") != "accessory" or not (insert or delete or row.get("op") == "UPDATE"
            and isinstance(old, dict) and isinstance(new, dict)) \
            or any(not isinstance(side.get("owner"), str) or scope is not None and side["owner"] not in scope
                   for side in ((new,) if insert else (old,) if delete else (old, new))):
        raise UndoMissing()
    return row


def raw_row(raw):
    """A strict SQL TEXT row whose ordinary edit/CSV roundtrip changes no cell."""
    if not isinstance(raw, dict) or set(raw) != RAW or any(not isinstance(v, str) for v in raw.values()):
        raise UndoUnsupported("The accessory's recorded row has an unsupported schema.")
    try:
        if any("\0" in value for value in raw.values()):
            raise ValueError("NUL")
        for value in raw.values():
            value.encode("utf-8", errors="strict")
        validated = accessories.validate_row(raw)
        rendered = list(csv.DictReader(io.StringIO(accessories.csv_bytes([validated]).decode("utf-8"), newline="")))
        if rendered != [raw]:
            raise ValueError("Normalized")
    except (ValueError, TypeError, UnicodeError):
        raise UndoUnsupported("The accessory facts need the normal editor before they can be restored.") from None
    return dict(raw)


def raw_rows(snapshot, *, allow_empty=False):
    sheet = snapshot.accessories
    if allow_empty and not sheet.exists:
        from .model import Sheet
        if sheet == Sheet(paths.ACCESSORIES):
            return []
    if not sheet.exists or sheet.error is not None or sheet.strict_error or sheet.problems \
            or tuple(sheet.columns or ()) != tuple(rules.ACCESSORY_FIELDS):
        raise UndoUnsupported("The accessories list cannot be checked exactly.")
    rows = []
    seen = set()
    for row in sheet.rows:
        value = row.as_dict()
        if row.overflow or set(value) != RAW or any(not isinstance(v, str) for v in value.values()) \
                or value["id"] in seen:
            raise UndoUnsupported("The accessories list cannot be checked exactly.")
        seen.add(value["id"])
        rows.append(value)
    if not rows or rows != sorted(rows, key=rules.accessory_sort_key):
        raise UndoUnsupported("The accessories list cannot be checked exactly.")
    return rows


def list_sha(rows, owners):
    scope = _scope(owners)
    return _sha([row for row in rows if scope is None or row["owner"] in scope])


def meta(raw):
    return {field: raw[field] for field in META}


def _unchanged(before, after):
    # Counters can change at save; no other source or picture metadata may change.
    if after.replace(accessories=before.accessories, revision=before.revision,
                     decks_revision=before.decks_revision) != before:
        raise UndoConflict("The accessory inverse would change other data.")


def _candidate(snapshot, source, owners):
    from . import ops_accessories
    old, new = source["before"], source["after"]
    current = accessories.from_sheet(snapshot.accessories, strict=True)
    after, _ = ops_accessories.edit_accessory(snapshot, id=new["id"],
        row={field: old[field] for field in FIELDS}, sha256=accessories.view_sha256(current, owners),
        owners=owners, image="keep")
    after = changes.prepare(snapshot, after)
    _unchanged(snapshot, after)
    expected = [old if row["id"] == old["id"] else row for row in raw_rows(snapshot)]
    if raw_rows(after) != expected:
        raise UndoConflict("The accessory inverse cannot reproduce the recorded text exactly.")
    return after, expected


def _remove_candidate(snapshot, source, owners):
    from . import accessory_undo_remove, ops_accessories
    new = source["after"]
    if new["image"] or new["crop"] or any(name.rsplit(".", 1)[0] == new["id"] for name in snapshot.accessory_images):
        raise UndoUnsupported("Use Accessories for a row with a current or orphaned picture.")
    accessory_undo_remove.unused(snapshot, new["id"])
    current = accessories.from_sheet(snapshot.accessories, strict=True)
    after, _ = ops_accessories.remove_accessory(snapshot, id=new["id"], owners=owners,
        sha256=accessories.view_sha256(current, owners))
    after = changes.prepare(snapshot, after)
    _unchanged(snapshot, after)
    expected = [row for row in raw_rows(snapshot) if row["id"] != new["id"]]
    if raw_rows(after, allow_empty=True) != expected:
        raise UndoConflict("The accessory removal cannot preserve the complete list.")
    return after, expected


def _add_candidate(snapshot, source, owners):
    from . import accessory_undo_remove, ops_accessories
    old = source["before"]
    if old["image"] or old["crop"] or any(name.rsplit(".", 1)[0] == old["id"] for name in snapshot.accessory_images):
        raise UndoUnsupported("Use Accessories for a row with a recorded or orphaned picture.")
    accessory_undo_remove.unused(snapshot, old["id"])
    listing = accessories.from_sheet(snapshot.accessories, strict=True)
    # Ordinary Add owns ID derivation. Never force an old ID or reveal the candidate
    # chosen from the complete, potentially private namespace.
    after, summary = ops_accessories.add_accessory(snapshot, row={field: old[field] for field in accessories.ROW_KEYS},
        owners=owners, image=None, sha256=accessories.view_sha256(listing, owners))
    after = changes.prepare(snapshot, after)
    _unchanged(snapshot, after)
    expected = sorted([*raw_rows(snapshot, allow_empty=True), old], key=rules.accessory_sort_key)
    if summary.extra.get("id") != old["id"] or raw_rows(after) != expected:
        raise UndoUnsupported("This recorded accessory cannot be restored exactly. Use the normal editor.")
    return after, expected


def review(change_id, owners, snapshot, store=None):
    """Called with one inventory snapshot/connection under its ordinary write lock."""
    _identifier(change_id)
    store = backend() if store is None else store
    source = source_record(store.undo_audit(change_id), owners)
    _identifier(source.get("id"))
    removing = source["op"] == "INSERT"
    adding = source["op"] == "DELETE"
    old, new = None if removing else raw_row(source["before"]), None if adding else raw_row(source["after"])
    identity = old if adding else new
    if source.get("key") != {"id": identity["id"]} or not adding and not removing and old["id"] != new["id"]:
        raise UndoUnsupported("The accessory's original identity cannot be checked.")
    if not removing and not adding:
        changed = {field for field in RAW if old[field] != new[field]}
        if not changed or changed - set(FIELDS):
            raise UndoUnsupported("Undo restores only recorded accessory text and links, keeping the current photo and kit.")
    latest = store.undo_latest("accessory", source["key"])
    if type(latest) is not int or latest != source["id"]:
        raise UndoConflict("The accessory was touched after the selected change.")
    rows = raw_rows(snapshot, allow_empty=adding)
    found = [row for row in rows if row["id"] == identity["id"]]
    if found != ([] if adding else [new]):
        raise UndoConflict("The accessory changed after the selected change.")
    after, expected = (_add_candidate if adding else _remove_candidate if removing else _candidate)(snapshot, source, owners)
    scope = _scope(owners)
    return {"change_id": change_id, "kind": "accessory", "action": "accessory_add" if adding else "accessory_remove" if removing else "accessory_update",
            "label": identity["name"], "current": None if adding else new if removing else meta(new),
            "restored": old if adding else None if removing else meta(old),
            **({"confirmation_required": True} if adding else {"reason_required": True} if removing else {"fields": [
                {"field": field, "before": new[field], "after": old[field]} for field in FIELDS if new[field] != old[field]]}),
            "expect": _sha([change_id, source, scope, list_sha(rows, owners)]),
            "sha256": list_sha(expected, owners), "source": source, "raw_after": expected,
            "owners": scope, "row_change_id": source["id"]}, after


def verify_saved(before, after, plan, actual_rows):
    """Exact actual snapshot and ONE new opposite audit row, before commit."""
    _unchanged(before, after)
    removing = plan["action"] == "accessory_remove"
    adding = plan["action"] == "accessory_add"
    if raw_rows(after, allow_empty=removing) != plan["raw_after"] or not isinstance(actual_rows, list) or len(actual_rows) != 1:
        raise UndoConflict("The accessory inverse result could not be confirmed.")
    source, actual = plan["source"], actual_rows[0]
    if not isinstance(actual, dict) or set(actual) != {"id", "table", "op", "key", "before", "after"} or type(actual.get("id")) is not int \
            or not source["id"] < actual["id"] < 2 ** 63 or actual.get("table") != "accessory" \
            or actual.get("op") != ("INSERT" if adding else "DELETE" if removing else "UPDATE") or actual.get("key") != source["key"] \
            or actual.get("before") != source["after"] or actual.get("after") != source["before"]:
        raise UndoConflict("The accessory inverse audit could not be confirmed.")
    digest = list_sha(raw_rows(after, allow_empty=removing), plan["owners"])
    if digest != plan["sha256"]:
        raise UndoConflict("The accessory inverse list could not be confirmed.")
    return {"review": plan, "restored": actual["after"] if adding else None if removing else meta(actual["after"]), "sha256": digest,
            **({"added_id": source["before"]["id"]} if adding else {}),
            **({"removed_id": source["after"]["id"]} if removing else {}),
            "revision": str(actual["id"])}


class MetadataRestore:
    """Trusted operation with transaction-local verification in PgInventory.apply."""
    kind = "accessory.undo"

    def __init__(self, change_id, owners, expect, *, store=None, reason=..., confirm_restore=...):
        self.change_id, self.owners, self.expect = change_id, owners, expect
        self.store = store
        self.reason = reason
        self.confirm_restore = confirm_restore
        self.params = {}
        self.plan = None

    def run(self, snapshot):
        plan, after = review(self.change_id, self.owners, snapshot, self.store)
        if not isinstance(self.expect, str) or not SHA.fullmatch(self.expect) or self.expect != plan["expect"]:
            raise UndoConflict("The accessories changed. Review this Undo again.")
        self.plan = plan
        removing = plan["action"] == "accessory_remove"
        adding = plan["action"] == "accessory_add"
        if adding:
            if self.confirm_restore is not True:
                raise Invalid("Confirm the entire historical accessory record before restoring it.")
        elif self.confirm_restore is not ...:
            raise Invalid("Only restoring a deleted accessory takes confirmation.")
        if removing:
            self.reason = removal_reason(None if self.reason is ... else self.reason)
        elif self.reason is not ...:
            raise Invalid("Only removing an added accessory takes a removal reason.")
        return after, Summary(f"Undo change #{self.change_id}: " + ("restore a deleted accessory record" if adding else "remove an unused added accessory" if removing else
                              "restore recorded accessory text and links"), {"undo": 1},
                              {paths.ACCESSORIES: ["added"] if adding else ["removed"] if removing else list(FIELDS)},
                              {"undo_of": self.change_id, **({"undo_reason": self.reason} if removing else {})})

    def verify(self, before, after, actual_rows):
        if self.plan is None:
            raise Invalid("Review the accessory Undo before saving it.")
        return verify_saved(before, after, self.plan, actual_rows)
