"""One complete inverse of an unreceived order lifecycle and its fulfilled queue intent.

The authoritative unfiltered audit source must contain one order add/remove or
pending/cancelled transition together with queue rows. Derived deck audit rows
are acknowledged, never restored; the ordinary refresh uses the current texts.
"""
import copy
import hashlib
import json

from . import Summary, backend, changes, files, paths, orders, register
from . import order_queue_models as models, undo_queue_schema
from . import undo_order_scope as scope
from . import undo_watchlist as updates, undo_watchlist_rows as presence, undo_watchlist_mixed as mixed
from .undo import UndoConflict, UndoMissing, UndoUnsupported, _identifier, removal_reason
from .undo_mixed import MIXED_MAX

ACTION = "order_queue_restore"
KIND = "order_queue"
CHANGED = "The order or purchase queue changed after this source. Nothing was undone."
UNCONFIRMED = "The complete order and queue inverse could not be confirmed. Nothing was saved."
UNTOUCHED = ("collections", "tokens", "locations", "imports", "accessories", "accessory_images", "dice", "loans", "deck_aliases")


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def looks_like(store, change_id, space, first):
    if space != "home" or not isinstance(first, list) or not first:
        return False
    if any(not isinstance(row, dict) or row.get("table") not in {*models.TABLES, updates.TABLE, "deck"} for row in first):
        return False
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        return False
    raw = reader(change_id)
    return isinstance(raw, list) and any(row.get("table") == updates.TABLE for row in raw if isinstance(row, dict)) \
        and any(row.get("table") == models.ORDER for row in raw if isinstance(row, dict))


def _deck_source(row):
    before, after = row.get("before"), row.get("after")
    if row.get("op") != "UPDATE" or not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after) \
            or before.get("space_id") != "home" or after.get("space_id") != "home" \
            or not isinstance(after.get("id"), str) or not after["id"] or row.get("key") != {"id": after.get("id")} \
            or type(before.get("revision")) is not int or after.get("revision") != before["revision"] + 1 \
            or {field for field in before if before[field] != after[field]} - {"revision", "updated_at"}:
        raise UndoUnsupported("Only derived home deck-table updates may accompany this order change.")


def _source(raw, space):
    if space != "home" or not isinstance(raw, list) or not raw:
        raise UndoMissing()
    # Resolve every private/out-of-scope record before diagnosing values or labels.
    for row in raw:
        if not isinstance(row, dict):
            raise UndoMissing()
        image = row.get("after") if isinstance(row.get("after"), dict) else row.get("before")
        if row.get("table") not in {*models.TABLES, updates.TABLE, "deck"}:
            raise UndoMissing()
        if row.get("table") == "deck" and (not isinstance(image, dict) or image.get("space_id") != "home"):
            raise UndoMissing()
    if len(raw) > MIXED_MAX:
        raise UndoMissing()        # a capped source never proves the complete change's ownership
    orders, ids, chains, queue = set(), set(), {}, []
    for row in sorted(raw, key=lambda item: item.get("id") if type(item.get("id")) is int else -1):
        _identifier(row.get("id"))
        if row["id"] in ids:
            raise UndoUnsupported("The complete audit source repeats a row.")
        ids.add(row["id"])
        table = row["table"]
        if table == "deck":
            _deck_source(row)
            continue
        if table == updates.TABLE:
            queue.append(row)
            continue
        operation, old, new = row.get("op"), row.get("before"), row.get("after")
        if operation not in ("INSERT", "UPDATE", "DELETE") or (old is None) != (operation == "INSERT") \
                or (new is None) != (operation == "DELETE"):
            raise UndoUnsupported("The order audit source is not a complete recorded transition.")
        try:
            old = models.normalized(table, old) if old is not None else None
            new = models.normalized(table, new) if new is not None else None
            image = new if new is not None else old
            identity = models.key(table, image)
            if row.get("key") != {field: image[field] for field in models.KEYS[table]} \
                    or old is not None and models.key(table, old) != identity:
                raise ValueError("Changed primary identity")
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise UndoUnsupported("The complete order audit schema cannot be checked.") from None
        group = chains.setdefault((table, identity), {"before": old, "after": old, "ids": []})
        if group["after"] != old:
            raise UndoUnsupported("The recorded order transitions do not form one complete source.")
        group.update(after=new)
        group["ids"].append(row["id"])
        if table == models.ORDER:
            orders.add(image["id"])
        elif table in (models.COMPONENT, *models.ITEMS):
            orders.add(image["order_id"])
    if len(orders) != 1 or not queue or len(queue) > updates.BATCH_MAX:
        raise UndoUnsupported("Review one complete order lifecycle with 1-50 purchase-queue rows.")
    oid = next(iter(orders))
    parent = chains.get((models.ORDER, models.key(models.ORDER, {"id": oid})))
    if parent is None or len(parent["ids"]) != 1:
        raise UndoUnsupported("The source must contain the order's complete lifecycle record.")
    mode = "added" if parent["before"] is None else "removed" if parent["after"] is None else "state"
    components = [group for (table, _), group in chains.items() if table == models.COMPONENT]
    if not components:
        raise UndoUnsupported("The source has no recorded order components.")
    for group in components:
        old, new = group["before"], group["after"]
        for image in (old, new):
            if image is not None and (image["status"] not in ("pending", "cancelled") or image["received_on"]):
                raise UndoUnsupported("Received order parts use the separate receipt Undo.")
        if mode == "added" and old is not None or mode == "removed" and new is not None:
            raise UndoUnsupported("The source does not contain one whole added or removed order.")
        if mode == "state" and (old is None or new is None or old["status"] == new["status"]
                or {field for field in old if old[field] != new[field]} != {"status"}):
            raise UndoUnsupported("Only the recorded pending/cancelled component state may change here.")
    if mode == "state":
        if len(components) != 1 or {field for field in parent["before"] if parent["before"][field] != parent["after"][field]} != {"audit_notes"} \
                or any(table in (*models.ITEMS, models.PRODUCT, models.PRODUCT_ITEM) for table, _ in chains):
            raise UndoUnsupported("The cancelled-order source changed facts outside its state and queue intent.")
    for (table, _), group in chains.items():
        if table == models.ORDER or table == models.COMPONENT:
            continue
        if mode == "added" and group["before"] is not None and table != models.STATUS \
                or mode == "removed" and group["after"] is not None and table != models.STATUS:
            raise UndoUnsupported("The order source contains a partial payload or product change.")
        if table == models.STATUS:
            old, new = group["before"], group["after"]
            position_only = old is not None and new is not None and {field for field in old if old[field] != new[field]} <= {"position"}
            if not position_only and any(image is not None and (image["status"] not in ("ordered", "preordered", "cancelled")
                                                               or image["intact"] or image["sleeves"] or image["deck_box"])
                                         for image in (old, new)):
                raise UndoUnsupported("Only unreceived products can be reversed with an order.")
    related = {image["product_stem"] for group in components for image in (group["before"], group["after"])
               if image is not None and image["kind"] == "product"}
    for group in components:
        image = group["after"] if group["after"] is not None else group["before"]
        if mode in ("added", "removed") and image["kind"] in ("cards", "tokens"):
            table = models.ITEMS[0] if image["kind"] == "cards" else models.ITEMS[1]
            rows = [item for (kind, _), item in chains.items() if kind == table
                    and (item["after"] or item["before"])["component_id"] == image["id"]]
            if not rows:
                raise UndoUnsupported("The original order payload is not a complete recorded list.")
    for stem in related:
        status = chains.get((models.STATUS, models.key(models.STATUS, {"file": stem + ".csv"})))
        if mode in ("added", "removed"):
            product = chains.get((models.PRODUCT, models.key(models.PRODUCT, {"stem": stem})))
            rows = [group for (table, _), group in chains.items() if table == models.PRODUCT_ITEM
                    and (group["after"] or group["before"])["product_stem"] == stem]
            if product is None or status is None or not rows \
                    or mode == "added" and (product["before"] is not None or status["before"] is not None) \
                    or mode == "removed" and (product["after"] is not None or status["after"] is not None):
                raise UndoUnsupported("The original order product is not a complete recorded list and status.")
        elif status is None or status["before"] is None or status["after"] is None \
                or {field for field in status["before"] if status["before"][field] != status["after"][field]} != {"status"}:
            raise UndoUnsupported("A cancelled product needs its complete recorded status transition.")
    for (table, _), group in chains.items():
        image = group["after"] if group["after"] is not None else group["before"]
        if table == models.PRODUCT and image["stem"] not in related \
                or table == models.PRODUCT_ITEM and image["product_stem"] not in related:
            raise UndoUnsupported("The source changed a product outside the recorded order.")
        if table == models.STATUS and image["file"].removesuffix(".csv") not in related:
            old, new = group["before"], group["after"]
            if old is None or new is None or {field for field in old if old[field] != new[field]} - {"position"}:
                raise UndoUnsupported("Only recorded position shifts may involve another product.")
    return oid, mode, chains, queue


def _queue_plan(change_id, snapshot, store, raw):
    if len({row.get("op") for row in raw}) > 1:
        return mixed, mixed.review(change_id, "home", snapshot, store, raw)
    if all(row.get("op") == "UPDATE" for row in raw):
        return updates, updates.review(change_id, "home", snapshot, store, raw)
    return presence, presence.review(change_id, "home", snapshot, store, raw)


def _products(chains, snapshot=None, oid=None):
    stems = set()
    for (table, _), group in chains.items():
        for image in (group["before"], group["after"]):
            if image is None:
                continue
            if table == models.PRODUCT:
                stems.add(image["stem"])
            elif table == models.PRODUCT_ITEM or table == models.COMPONENT and image.get("product_stem"):
                stems.add(image["product_stem"])
            elif table == models.STATUS:
                stems.add(image["file"].removesuffix(".csv"))
    current = snapshot.order(oid) if snapshot is not None and oid is not None else None
    if current is not None:
        stems.update(part.product_stem for part in current.components if part.kind == "product")
    return sorted(stems)


def _order_view(inv, oid):
    order = inv.order(oid)
    if order is None:
        return None
    from . import order_fulfilment
    notes = order.audit_notes or ""
    span = order_fulfilment.audit_span(notes)
    if span:
        notes = (notes[:span[0]] + notes[span[1]:]).strip()
    components = []
    for part in order.components:
        shown = {"id": part.id, "kind": part.kind, "status": part.status, "received_on": part.received_on,
                 "checks": list(part.checks), "verified_checks": list(part.verified_checks or [])}
        if part.kind == "product":
            product = inv.product(part.product_stem)
            if product is None:
                raise ValueError("The order product cannot be read")
            statuses = [row.text("status") for row in inv.status.rows if row.text("file") == product.file]
            if len(statuses) != 1:
                raise ValueError("The product status cannot be checked")
            shown.update(product=product.stem, name=product.name, format=product.format, product_status=statuses[0],
                         rows=[item.as_dict() for item in product.items])
        else:
            shown["rows"] = [row.as_dict() for row in inv.payloads[part.path].rows]
        components.append(shown)
    return {"id": oid, "seller": order.seller, "ordered_on": order.ordered_on, "sources": list(order.sources), "notes": order.notes,
            "audit_notes": notes, "components": components}


def _validate_pending(inv, oid, chains):
    order = inv.order(oid)
    if order is None:
        return
    targets = {image["id"] for (table, _), group in chains.items() if table == models.COMPONENT
               for image in (group["before"], group["after"]) if image is not None}
    for part in order.components:
        if part.id not in targets:
            continue
        if part.status not in ("pending", "cancelled") or part.received_on:
            raise ValueError("A received part cannot be reversed here")
        if part.kind == "product":
            product = inv.product(part.product_stem)
            rows = [item.as_dict() for item in product.items] if product is not None else []
            if not rows:
                raise ValueError("An order product needs its recorded rows")
            orders.check_card_rows(rows, names_only=True)
        else:
            rows = [item.as_dict() for item in inv.payloads[part.path].rows]
            if not rows:
                raise ValueError("An order part needs its recorded rows")
            if part.kind == "cards":
                if orders.card_rows(rows, part.path) != rows:
                    raise ValueError("The recorded card facts no longer validate verbatim")
                orders.check_card_rows(rows)
            elif part.kind == "tokens":
                if orders.check_token_names(orders.token_rows(rows, part.path))[0] != rows:
                    raise ValueError("The recorded token facts no longer validate verbatim")
            else:
                raise ValueError("Unknown component kind")


def _plan(change_id, space, snapshot, store):
    _identifier(change_id)
    if space != "home":
        raise UndoMissing()
    reader = getattr(store, "undo_audit_rows", None)
    if not callable(reader):
        raise UndoUnsupported("Order Undo needs the complete database audit trail.")
    raw = reader(change_id)
    oid, mode, chains, queue_raw = _source(raw, space)
    if snapshot.stale or not snapshot.persisted or not snapshot.decks_revision:
        raise UndoConflict("The current inventory and decks cannot be checked. Reload Activity.")
    try:
        current = models.images(snapshot)
    except (ValueError, TypeError, KeyError):
        raise UndoConflict("The current recorded orders cannot be checked. Reload Shopping.") from None
    wanted = copy.deepcopy(current)
    for (table, identity), group in chains.items():
        found, expected, restored = current[table].get(identity), group["after"], group["before"]
        position_only = table == models.STATUS and restored is not None and expected is not None \
            and {field for field in restored if restored[field] != expected[field]} <= {"position"}
        if position_only and found is not None:
            # Kit is independent current owner data, never a historical restore.
            expected = {**expected, **{field: found[field] for field in scope.KIT}}
            restored = {**restored, **{field: found[field] for field in scope.KIT}}
        if found != expected:
            raise UndoConflict(CHANGED, "recorded order and queue")
        if restored is None:
            wanted[table].pop(identity, None)
        else:
            wanted[table][identity] = restored
    fence = getattr(store, "undo_order_queue_latest", None)
    expected = max(rid for group in chains.values() for rid in group["ids"])
    if not callable(fence):
        raise UndoUnsupported("Order Undo needs a current order audit fence.")
    if fence(oid, _products(chains, snapshot, oid)) != expected:
        raise UndoConflict(CHANGED, "recorded order and queue")
    queue_module, queue_plan = _queue_plan(change_id, snapshot, store, queue_raw)
    queued, queue_summary = queue_module.apply(snapshot, queue_plan, change_id, reason="Reviewed order and queue inverse") \
        if queue_module is not updates else queue_module.apply(snapshot, queue_plan, change_id)
    try:
        after = changes.prepare(snapshot, models.restore(queued, current, wanted))
        orders.keep_pairing(snapshot, after)
        _validate_pending(after, oid, chains)
        if after.decks != snapshot.decks or any(getattr(after, field) != getattr(snapshot, field) for field in UNTOUCHED):
            raise ValueError("An unrelated part changed")
        before_view, after_view = _order_view(snapshot, oid), _order_view(after, oid)
    except Exception:
        raise UndoConflict(UNCONFIRMED, "recorded order and queue") from None
    digest = hashlib.sha256(_encode([change_id, scope.source(raw), scope.context(snapshot), expected,
                                     queue_plan["expect"], scope.order_facts(current)]).encode("utf-8")).hexdigest()
    label = "recorded order and its purchase-queue intent"
    plan = {"change_id": change_id, "space": "home", "kind": KIND, "action": ACTION, "expect": digest,
            "label": label, "order_id": oid, "source_action": mode, "row_count": len(raw), "queue_count": len(queue_raw),
            "current": before_view, "restore": after_view, "queue": queue_plan, "reason_required": True,
            "proof": {"source_ids": [row["id"] for row in raw], "order_before": current, "order_after": wanted,
                      "queue_summary": queue_summary, "queue_module": queue_module.__name__, "base_snapshot": snapshot}}
    return plan, after


def review(change_id, space, snapshot, store):
    return _plan(change_id, space, snapshot, store)[0]


@register("inventory.undo_order_queue", refresh=True)
def apply(snapshot, *, change_id, space, expect, reason):
    reason = removal_reason(reason)
    plan, after = _plan(change_id, space, snapshot, backend())
    if expect != plan["expect"]:
        raise UndoConflict("The order, queue or decks changed after this review. Review Activity again.")
    return after, Summary(f"Undo change #{change_id}: restore the recorded order and its purchase-queue intent",
        {"undo": 1, "order": 1, "queue_rows": plan["queue_count"]},
        {paths.WATCHLIST: ["undo"], paths.record(plan["order_id"]): ["undo"]},
        {"undo_of": change_id, "kind": KIND, "space": "home", "action": ACTION, "undo_reason": reason,
         "order_queue": {**plan["proof"], "plan": plan}})
