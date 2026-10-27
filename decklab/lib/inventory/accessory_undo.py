"""Guarded accessory metadata UPDATE and image-free INSERT/DELETE inverses.

Accessory image bytes are not audited. UPDATE restores recorded details/capacity/counts;
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

FIELDS = ("brand", "name", "colour", "notes", "link", "image_source", "capacity")
META = ("id", "kind", "owner", *FIELDS)
STOCK_FIELDS = (*FIELDS, "quantity")
STOCK_META = (*META, "quantity")
OWNER_FIELDS = ("owner", *FIELDS)
KIND_FIELDS = ("kind", *FIELDS)
RECORD_FIELDS = ("owner", "kind", "quantity", *FIELDS)
UPDATE_FIELDS = {"accessory_update": FIELDS, "accessory_stock_update": STOCK_FIELDS,
                 "accessory_owner_update": OWNER_FIELDS, "accessory_kind_update": KIND_FIELDS,
                 "accessory_record_update": RECORD_FIELDS, "accessory_crop_update": ("crop",)}
UPDATE_CONFIRMATIONS = {"accessory_stock_update": "stock_confirmation_required",
                        "accessory_owner_update": "owner_confirmation_required",
                        "accessory_kind_update": "kind_confirmation_required",
                        "accessory_record_update": "record_confirmation_required",
                        "accessory_crop_update": "photo_confirmation_required"}
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


def stock_meta(raw):
    return {field: raw[field] for field in STOCK_META}


def photo_envelope(value):
    """Exact current-photo identity, with the existing private image-address epoch."""
    from decklab.lib import accessory_fetch
    from .model import ImageMeta
    if not isinstance(value, dict) or set(value) != {"name", "size", "sha256", "version"} \
            or not isinstance(value["name"], str) or not accessories.IMAGE_RE.fullmatch(value["name"]) \
            or type(value["size"]) is not int or not 1 <= value["size"] <= accessory_fetch.MAX_IMAGE \
            or not isinstance(value["sha256"], str) or not SHA.fullmatch(value["sha256"]) \
            or value["version"] != accessories.image_version(ImageMeta(value["name"], value["size"], value["sha256"])):
        raise UndoUnsupported("The current accessory photo cannot be checked exactly.")
    return dict(value)


def current_photo(snapshot, row, store=None):
    """Read only this row's current bytes through the transaction-bound proof reader."""
    from decklab.lib import accessory_fetch
    from decklab.lib.api.common import ApiError
    from .model import ImageMeta
    name = row.get("image")
    meta = snapshot.image_meta(name) if isinstance(name, str) and name else None
    if not isinstance(meta, ImageMeta) or meta.name != name:
        raise UndoUnsupported("The current accessory photo cannot be checked exactly.")
    photo = photo_envelope({"name": meta.name, "size": meta.size, "sha256": meta.sha256,
                            "version": accessories.image_version(meta) if isinstance(meta.sha256, str) and SHA.fullmatch(meta.sha256) else None})
    reader = getattr(backend() if store is None else store, "accessory_undo_photo", None)
    if not callable(reader):
        raise UndoUnsupported("The current accessory photo needs its database reader.")
    data = reader(name, photo["sha256"], photo["size"])
    if not isinstance(data, bytes) or len(data) != photo["size"] or hashlib.sha256(data).hexdigest() != photo["sha256"] \
            or meta.content is not None and (not isinstance(meta.content, bytes) or len(meta.content) != photo["size"]
                or hashlib.sha256(meta.content).hexdigest() != photo["sha256"]):
        raise UndoConflict("The current accessory photo changed or could not be verified. Review it again.")
    try:
        ext, _, _ = accessory_fetch.check_image(data)
        if ext != name.rsplit(".", 1)[1]:
            raise ValueError("Photo extension")
    except (ApiError, ValueError):
        raise UndoUnsupported("The current accessory photo needs the normal photo editor.") from None
    return photo


def update_action(old, new):
    """Whole-source category cardinality, shared by the inverse and its API proof."""
    categories = [field for field in ("owner", "kind", "quantity") if old.get(field) != new.get(field)]
    if len(categories) >= 2:
        return "accessory_record_update"
    if not categories and old.get("crop") != new.get("crop"):
        return "accessory_crop_update"
    return {"owner": "accessory_owner_update", "kind": "accessory_kind_update",
            "quantity": "accessory_stock_update"}.get(categories[0] if categories else None, "accessory_update")


def owner_pair(old, new):
    """Only one configured home owner's record and Shared, even for a script."""
    pair = {old.get("owner"), new.get("owner")}
    return len(pair) == 2 and accessories.SHARED in pair \
        and pair - {accessories.SHARED} <= set(accessories.owner_ids()) - {accessories.SHARED}


def _unchanged(before, after):
    # Counters can change at save; no other source or picture metadata may change.
    if after.replace(accessories=before.accessories, revision=before.revision,
                     decks_revision=before.decks_revision) != before:
        raise UndoConflict("The accessory inverse would change other data.")


def _candidate(snapshot, source, owners):
    from . import ops_accessories
    old, new = source["before"], source["after"]
    action = update_action(old, new)
    fields = UPDATE_FIELDS[action]
    if action in ("accessory_owner_update", "accessory_kind_update", "accessory_record_update"):
        from . import accessory_undo_remove
        accessory_undo_remove.unused(snapshot, new["id"])
    current = accessories.from_sheet(snapshot.accessories, strict=True)
    after, _ = ops_accessories.edit_accessory(snapshot, id=new["id"],
        row={field: old[field] for field in fields}, sha256=accessories.view_sha256(current, owners),
        owners=owners, image="keep")
    after = changes.prepare(snapshot, after)
    _unchanged(snapshot, after)
    expected = sorted([old if row["id"] == old["id"] else row for row in raw_rows(snapshot)], key=rules.accessory_sort_key)
    if raw_rows(after) != expected:
        raise UndoConflict("The accessory inverse cannot reproduce the recorded details exactly.")
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
    action = "accessory_add" if adding else "accessory_remove" if removing else update_action(old, new)
    fields = UPDATE_FIELDS.get(action, ())
    if source.get("key") != {"id": identity["id"]} or not adding and not removing and old["id"] != new["id"]:
        raise UndoUnsupported("The accessory's original identity cannot be checked.")
    if not removing and not adding:
        if old["owner"] != new["owner"] and not owner_pair(old, new):
            raise UndoUnsupported("Undo restores sharing only between Shared and one current home owner.")
        changed = {field for field in RAW if old[field] != new[field]}
        if not changed or changed - set(fields):
            raise UndoUnsupported("Undo restores recorded accessory details and counts, keeping the current photo and kit.")
    latest = store.undo_latest("accessory", source["key"])
    if type(latest) is not int or latest != source["id"]:
        raise UndoConflict("The accessory was touched after the selected change.")
    rows = raw_rows(snapshot, allow_empty=adding)
    found = [row for row in rows if row["id"] == identity["id"]]
    if found != ([] if adding else [new]):
        raise UndoConflict("The accessory changed after the selected change.")
    photo = current_photo(snapshot, new, store) if action == "accessory_crop_update" else None
    after, expected = (_add_candidate if adding else _remove_candidate if removing else _candidate)(snapshot, source, owners)
    scope = _scope(owners)
    project = dict if photo is not None else stock_meta if action in UPDATE_CONFIRMATIONS else meta
    return {"change_id": change_id, "kind": "accessory", "action": action,
            "label": identity["name"], "current": None if adding else new if removing else project(new),
            "restored": old if adding else None if removing else project(old),
            **({"confirmation_required": True} if adding else {"reason_required": True} if removing else {"fields": [
                {"field": field, "before": new[field], "after": old[field]} for field in fields if new[field] != old[field]]}),
            **({UPDATE_CONFIRMATIONS[action]: True} if action in UPDATE_CONFIRMATIONS else {}),
            **({"photo": photo} if photo is not None else {}),
            "expect": _sha([change_id, source, scope, list_sha(rows, owners), *([photo] if photo is not None else [])]),
            "sha256": list_sha(expected, owners), "source": source, "raw_after": expected,
            "owners": scope, "row_change_id": source["id"]}, after


def verify_saved(before, after, plan, actual_rows, *, store=None):
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
    cropping = plan["action"] == "accessory_crop_update"
    if cropping and current_photo(after, actual["after"], store) != plan.get("photo"):
        raise UndoConflict("The current accessory photo could not be confirmed.")
    return {"review": plan, "restored": actual["after"] if adding or cropping else None if removing else (stock_meta if plan["action"] in UPDATE_CONFIRMATIONS else meta)(actual["after"]), "sha256": digest,
            **({"photo": dict(plan["photo"])} if cropping else {}),
            **({"added_id": source["before"]["id"]} if adding else {}),
            **({"removed_id": source["after"]["id"]} if removing else {}),
            "revision": str(actual["id"])}


class MetadataRestore:
    """Trusted operation with transaction-local verification in PgInventory.apply."""
    kind = "accessory.undo"

    def __init__(self, change_id, owners, expect, *, store=None, reason=..., confirm_restore=..., confirm_stock=..., confirm_owner=..., confirm_kind=..., confirm_record=..., confirm_photo=...):
        self.change_id, self.owners, self.expect = change_id, owners, expect
        self.store = store
        self.reason = reason
        self.confirm_restore = confirm_restore
        self.confirm_stock = confirm_stock
        self.confirm_owner = confirm_owner
        self.confirm_kind = confirm_kind
        self.confirm_record = confirm_record
        self.confirm_photo = confirm_photo
        self.params = {}
        self.plan = None

    def run(self, snapshot):
        plan, after = review(self.change_id, self.owners, snapshot, self.store)
        if not isinstance(self.expect, str) or not SHA.fullmatch(self.expect) or self.expect != plan["expect"]:
            raise UndoConflict("The accessories changed. Review this Undo again.")
        self.plan = plan
        removing = plan["action"] == "accessory_remove"
        adding = plan["action"] == "accessory_add"
        stock = plan["action"] == "accessory_stock_update"
        ownership = plan["action"] == "accessory_owner_update"
        kind_change = plan["action"] == "accessory_kind_update"
        record = plan["action"] == "accessory_record_update"
        cropping = plan["action"] == "accessory_crop_update"
        if cropping:
            if self.confirm_photo is not True:
                raise Invalid("Confirm the crop on the current accessory photo before saving it.")
        elif self.confirm_photo is not ...:
            raise Invalid("Only restoring a crop on the current photo takes photo confirmation.")
        if record:
            if self.confirm_record is not True:
                raise Invalid("Confirm the whole restored accessory record before saving it.")
        elif self.confirm_record is not ...:
            raise Invalid("Only restoring a combined accessory correction takes record confirmation.")
        if kind_change:
            if self.confirm_kind is not True:
                raise Invalid("Confirm the restored accessory kind and count units before saving it.")
        elif self.confirm_kind is not ...:
            raise Invalid("Only restoring an accessory kind takes kind confirmation.")
        if ownership:
            if self.confirm_owner is not True:
                raise Invalid("Confirm the restored accessory sharing before saving it.")
        elif self.confirm_owner is not ...:
            raise Invalid("Only restoring accessory sharing takes owner confirmation.")
        if stock:
            if self.confirm_stock is not True:
                raise Invalid("Confirm the entire restored accessory count before saving it.")
        elif self.confirm_stock is not ...:
            raise Invalid("Only restoring an accessory count takes stock confirmation.")
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
                              "restore a crop on the current accessory photo" if cropping else "restore a combined accessory correction" if record else "restore the recorded accessory kind" if kind_change else "restore recorded accessory sharing" if ownership else "restore a recorded accessory count" if stock else "restore recorded accessory details"), {"undo": 1},
                              {paths.ACCESSORIES: ["added"] if adding else ["removed"] if removing else list(UPDATE_FIELDS[plan["action"]])},
                              {"undo_of": self.change_id, **({"undo_reason": self.reason} if removing else {})})

    def verify(self, before, after, actual_rows):
        if self.plan is None:
            raise Invalid("Review the accessory Undo before saving it.")
        if self.plan["action"] == "accessory_crop_update":
            return verify_saved(before, after, self.plan, actual_rows, store=self.store)
        return verify_saved(before, after, self.plan, actual_rows)
