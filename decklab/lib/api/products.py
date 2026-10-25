"""Preview and confirm an owned product's storage state through its shared operation.

GET /api/product?stem=... exposes home inventory state without needing card data.
POST /api/product/intact/preview takes {profile,stem,intact,fingerprint}; apply
takes {profile,preview}. Opaque previews bind the writer/listener and both inventory
and deck revisions. Product cards, kit removal and deck tables save atomically.
"""
from contextlib import contextmanager
import hashlib
import json
import threading
import time
import uuid

from decklab.lib import accessories, decks, inventory, spaces
from decklab.lib.inventory import orders, refresh, rules

from . import common, guard
from .carddata import _require_cards
from .common import DATABASE_DOWN, ApiError, _keys, _parse_body, _public
from .settings import _web_actor, _writer
from .shopping_orders import _tables

CHANGED = "The product, collection or decks changed. Reload the product and preview again."
KIT_PRIVATE = "Only the owner of this product's sleeves and deck box can clear them."
KIT_UNUSABLE = "This product's saved sleeves or deck box cannot be used here. Correct its kit before keeping it intact."
PREVIEW_LIFETIME = 1800
MAX_PREVIEWS = 64
_previews = {}
_preview_lock = threading.Lock()


def _fingerprint(snapshot):
    value = json.dumps([snapshot.revision, snapshot.decks_revision], separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stem(value):
    if not isinstance(value, str) or not rules.SLUG.fullmatch(value) or value == "status":
        raise ApiError(400, "Choose a valid product")
    return value


def _product(snapshot, stem):
    product = snapshot.product(stem)
    if product is None:
        raise ApiError(404, "This product is no longer available.")
    if snapshot.status.error is not None or snapshot.status.strict_error is not None:
        raise ApiError(409, "The products' status cannot be read. Correct it before changing storage.")
    rows = [row for row in snapshot.status.rows if row.text("file") == product.file]
    if len(rows) != 1:
        raise ApiError(409, "This product needs exactly one status record before its storage can change.")
    return product, rows[0]


def _intact(row):
    value = row.text("intact").strip().lower()
    return value if value in ("yes", "no") else None


def _kit(snapshot, row, owners, activating=False):
    """Old private accessory references never become readable through product metadata."""
    values = {field: row.text(field).strip() or None for field in accessories.HOLDER_FIELDS}
    if not any(values.values()):
        return values, None
    try:
        listed = accessories.from_sheet(snapshot.accessories, strict=False)
    except (OSError, accessories.AccessoriesError):
        return None, "The product's kit cannot be checked until the accessories list can be read."
    for value in values.values():
        accessory = listed.rows_by_id.get(value)
        if accessory is not None and not accessories.visible(accessory["owner"], owners):
            return None, KIT_PRIVATE
    if activating:
        for field, value in values.items():
            accessory = listed.rows_by_id.get(value)
            if accessory is not None and (accessory["kind"] != field
                                         or not accessories.usable(accessory["owner"], accessories.SHARED)):
                return values, KIT_UNUSABLE
    return values, None


def _details(snapshot, stem, profile):
    product, row = _product(snapshot, stem)
    has_decks, list_error = False, None
    try:
        if product.error is not None:
            raise inventory.Invalid("The product's card list cannot be read.")
        has_decks = orders._deck_lines(product) is not None
    except inventory.Invalid as error:
        list_error = _public(error)
    kit, kit_error = _kit(snapshot, row, guard.accessory_owners(profile), activating=_intact(row) != "yes")
    why = None
    try:
        guard.require(profile, "products.edit")
    except ApiError as error:
        why = error.message
    if why is None:
        if row.text("status") != "owned":
            why = "Only an owned product can be kept intact or broken up."
        elif kit_error:
            why = kit_error
        elif _intact(row) != "yes" and list_error:
            why = list_error
        elif _intact(row) != "yes" and not has_decks:
            why = "Only a product with deck lists can be kept intact."
    return {"stem": stem, "name": accessories._product_title(snapshot, product.file),
            "status": row.text("status").strip().lower(), "intact": _intact(row),
            "has_decks": has_decks, "fingerprint": _fingerprint(snapshot),
            "can_change": why is None, "why_not": why, "kit": kit}


@contextmanager
def _errors():
    try:
        yield
    except ApiError:
        raise
    except inventory.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except inventory.Conflict:
        raise ApiError(409, CHANGED) from None
    except (inventory.Invalid, ValueError, OSError) as error:
        raise ApiError(400, "The product storage change could not be prepared: " + _public(error)) from None


def product_state(stem=None):
    profile = guard.viewer()
    guard.require_sees_home_records(profile)
    stem = _stem(stem)
    with _errors(), inventory.pinned():
        return _details(inventory.current(), stem, profile)


def _authorize(data):
    profile = _writer(data)
    guard.require(profile, "products.edit")
    guard.require_sees_home_records(profile)
    return profile, _web_actor(profile)


class _StorageChange:
    """Check both revisions and kit ownership again inside the backend's write lock."""
    kind = "product.set_intact"

    def __init__(self, snapshot, stem, intact, owners):
        self.revision = (snapshot.revision, snapshot.decks_revision)
        self.params = {"stem": stem, "intact": intact}
        self.owners = owners

    def check(self, snapshot):
        if (snapshot.revision, snapshot.decks_revision) != self.revision:
            raise inventory.Conflict(CHANGED)
        _, row = _product(snapshot, self.params["stem"])
        if row.text("intact") != self.params["intact"]:
            _, error = _kit(snapshot, row, self.owners, activating=self.params["intact"] == "yes")
            if error:
                raise ApiError(400 if error == KIT_UNUSABLE else 403, error)

    def run(self, snapshot):
        self.check(snapshot)
        return inventory.Op(self.kind, self.params).run(snapshot)


def _prepare(before, operation):
    """Use the CLI's policy: refuse new refresh failures, report pre-existing ones."""
    after, summary = inventory.preview(operation)
    error = _tables(summary).get("error")
    if error and error != inventory.DECK_SAVES_PAUSED:
        try:
            with inventory.pinned(before):
                refresh.plan_refresh({spaces.HOME})
        except (OSError, ValueError, RuntimeError, decks.DeckFileError, inventory.StateError):
            pass
        else:
            raise ApiError(400, "After this product change the deck tables could not be refreshed: " + _public(error))
    return after, summary


def _result(before, after, summary, operation):
    stem, intact = operation.params["stem"], operation.params["intact"]
    product, was = _product(before, stem)
    _, now = _product(after, stem)
    return {"stem": stem, "name": accessories._product_title(after, product.file),
            "before": {"intact": _intact(was)}, "after": {"intact": _intact(now)},
            "kit_cleared": intact == "no" and any(was.text(field) and not now.text(field)
                                                     for field in accessories.HOLDER_FIELDS),
            "changes": inventory.changed_labels(before, after), "tables": _tables(summary),
            "warnings": common._scrub((summary.extra or {}).get("warnings", []))}


def preview_storage(body):
    data = _parse_body(body)
    profile, actor = _authorize(data)
    _keys(data, ("profile", "stem", "intact", "fingerprint"))
    stem = _stem(data["stem"])
    if data["intact"] not in ("yes", "no"):
        raise ApiError(400, "Choose Keep intact or Break up into storage.")
    if not isinstance(data["fingerprint"], str) or not common._SHA_RE.fullmatch(data["fingerprint"]):
        raise ApiError(400, "Reload the product before previewing its storage change.")
    with _errors(), inventory.pinned():
        before = inventory.current()
        if data["fingerprint"] != _fingerprint(before):
            raise ApiError(409, CHANGED)
        _, row = _product(before, stem)
        if row.text("status") != "owned":
            raise ApiError(400, "Only an owned product can be kept intact or broken up.")
        operation = _StorageChange(before, stem, data["intact"], guard.accessory_owners(profile))
        if row.text("intact") == data["intact"]:
            result = _result(before, before, inventory.Summary("Nothing to change"), operation)
            return {"ready": False, "unchanged": True, "reason": "This product already has that storage state.",
                    **result}
        operation.check(before)
        _require_cards()
        after, summary = _prepare(before, operation)
        result = _result(before, after, summary, operation)
    token, now = uuid.uuid4().hex, time.monotonic()
    with _preview_lock:
        for key, cached in list(_previews.items()):
            if not cached["busy"] and now - cached["created"] > PREVIEW_LIFETIME:
                del _previews[key]
        if len(_previews) >= MAX_PREVIEWS:
            expired = next((key for key, cached in _previews.items() if not cached["busy"]), None)
            if expired is None:
                raise ApiError(503, "Product changes are being saved. Try previewing again in a minute.")
            del _previews[expired]
        _previews[token] = {"created": now, "actor": (actor.id, actor.via), "operation": operation, "busy": False}
    return {"ready": True, "preview": token, **result}


def apply_storage(body):
    data = _parse_body(body)
    _, actor = _authorize(data)
    _keys(data, ("profile", "preview"))
    token = data["preview"]
    if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ApiError(400, "Prepare a product storage preview first.")
    with _preview_lock:
        cached = _previews.get(token)
        if (not cached or cached["actor"] != (actor.id, actor.via) or cached["busy"]
                or not 0 <= time.monotonic() - cached["created"] <= PREVIEW_LIFETIME):
            raise ApiError(409, "This product preview is unavailable, expired or belongs to another person. Preview again.")
        cached["busy"] = True
    try:
        from .saving import inventory_write_lock
        operation = cached["operation"]
        with _errors():
            before = inventory.current()
            with inventory_write_lock():
                after, summary = inventory.apply(operation, actor,
                                                  f"{'Keep intact' if operation.params['intact'] == 'yes' else 'Break up'} "
                                                  f"product {operation.params['stem']}",
                                                  expected_revision=operation.revision[0])
        result = _result(before, after, summary, operation)
        with _preview_lock:
            _previews.pop(token, None)
        return {"saved": True, "intact": result["after"]["intact"], **result}
    finally:
        with _preview_lock:
            cached["busy"] = False
