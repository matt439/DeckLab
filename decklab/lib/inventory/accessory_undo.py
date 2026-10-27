"""One audited accessory text/link UPDATE inverse, preserving current photos and kit.

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
from .undo import SHA, UndoConflict, UndoMissing, UndoUnsupported, _identifier

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
    if row.get("table") != "accessory" or row.get("op") != "UPDATE" \
            or not isinstance(old, dict) or not isinstance(new, dict) \
            or any(not isinstance(side.get("owner"), str) or scope is not None and side["owner"] not in scope
                   for side in (old, new)):
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


def raw_rows(snapshot):
    sheet = snapshot.accessories
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


def review(change_id, owners, snapshot, store=None):
    """Called with one inventory snapshot/connection under its ordinary write lock."""
    _identifier(change_id)
    store = backend() if store is None else store
    source = source_record(store.undo_audit(change_id), owners)
    _identifier(source.get("id"))
    old, new = raw_row(source["before"]), raw_row(source["after"])
    if source.get("key") != {"id": new["id"]} or old["id"] != new["id"]:
        raise UndoUnsupported("The accessory's original identity cannot be checked.")
    changed = {field for field in RAW if old[field] != new[field]}
    if not changed or changed - set(FIELDS):
        raise UndoUnsupported("Undo restores only recorded accessory text and links, keeping the current photo and kit.")
    latest = store.undo_latest("accessory", source["key"])
    if type(latest) is not int or latest != source["id"]:
        raise UndoConflict("The accessory was touched after the selected change.")
    rows = raw_rows(snapshot)
    found = [row for row in rows if row["id"] == new["id"]]
    if found != [new]:
        raise UndoConflict("The accessory changed after the selected change.")
    after, expected = _candidate(snapshot, source, owners)
    scope = _scope(owners)
    return {"change_id": change_id, "kind": "accessory", "action": "accessory_update",
            "label": new["name"], "current": meta(new), "restored": meta(old),
            "fields": [{"field": field, "before": new[field], "after": old[field]} for field in FIELDS
                       if new[field] != old[field]],
            "expect": _sha([change_id, source, scope, list_sha(rows, owners)]),
            "sha256": list_sha(expected, owners), "source": source, "raw_after": expected,
            "owners": scope, "row_change_id": source["id"]}, after


def verify_saved(before, after, plan, actual_rows):
    """Exact actual snapshot and ONE new opposite audit row, before commit."""
    _unchanged(before, after)
    if raw_rows(after) != plan["raw_after"] or not isinstance(actual_rows, list) or len(actual_rows) != 1:
        raise UndoConflict("The accessory inverse result could not be confirmed.")
    source, actual = plan["source"], actual_rows[0]
    if not isinstance(actual, dict) or type(actual.get("id")) is not int \
            or not source["id"] < actual["id"] < 2 ** 63 or actual.get("table") != "accessory" \
            or actual.get("op") != "UPDATE" or actual.get("key") != source["key"] \
            or actual.get("before") != source["after"] or actual.get("after") != source["before"]:
        raise UndoConflict("The accessory inverse audit could not be confirmed.")
    digest = list_sha(raw_rows(after), plan["owners"])
    if digest != plan["sha256"]:
        raise UndoConflict("The accessory inverse list could not be confirmed.")
    return {"review": plan, "restored": meta(actual["after"]), "sha256": digest,
            "revision": str(actual["id"])}


class MetadataRestore:
    """Trusted operation with transaction-local verification in PgInventory.apply."""
    kind = "accessory.undo"

    def __init__(self, change_id, owners, expect, *, store=None):
        self.change_id, self.owners, self.expect = change_id, owners, expect
        self.store = store
        self.params = {}
        self.plan = None

    def run(self, snapshot):
        plan, after = review(self.change_id, self.owners, snapshot, self.store)
        if not isinstance(self.expect, str) or not SHA.fullmatch(self.expect) or self.expect != plan["expect"]:
            raise UndoConflict("The accessories changed. Review this Undo again.")
        self.plan = plan
        return after, Summary(f"Undo change #{self.change_id}: restore recorded accessory text and links", {"undo": 1},
                              {paths.ACCESSORIES: list(FIELDS)}, {"undo_of": self.change_id})

    def verify(self, before, after, actual_rows):
        if self.plan is None:
            raise Invalid("Review the accessory Undo before saving it.")
        return verify_saved(before, after, self.plan, actual_rows)
