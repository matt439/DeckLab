"""The order rows a receipt corrected, for its whole-change Undo (E11-S08; undo_mixed.py).

A receipt may correct an arriving part's rows (`receive --rows C=FILE`, the Receive delivery
page's corrections): the conditions, languages, printings or a token's real back found at the
door. The database rewrites a changed payload list whole (inventory/pg.py), so the change holds
a DELETE of every row the order had and an INSERT of every row it has now, keyed by
(order_id, component_id, position), and, when the order keeps a fulfilment ledger, one UPDATE
of purchase_order's audit_notes (order_fulfilment.edit remapping the queue intent).

Undo puts the part's rows back exactly as they were ordered, and the ledger as it was, when:
every corrected part is one this receipt marked received; each part's old and new lists are
whole (positions 0..n-1, every position once a side); the rows there now are exactly the new
list and each position's latest audit row is this change's; and only audit_notes changed on
the order. Anything else (a split, a later correction, an edited record) refuses.
"""
import json

from .table_rows import ITEM_COLUMNS

CARDS, TOKENS = "order_card_item", "order_token_item"
ITEMS = (CARDS, TOKENS)
ORDER = "purchase_order"
KEYS = {CARDS: ("order_id", "component_id", "position"), TOKENS: ("order_id", "component_id", "position"),
        ORDER: ("id",)}
KIND_OF = {CARDS: "cards", TOKENS: "tokens"}
ORDER_FIELDS = {"id", "seller", "ordered_on", "sources", "notes", "audit_notes"}
TABLES = (*ITEMS, ORDER)


class Refused(ValueError):
    """The corrected rows aren't a shape this Undo restores (undo_mixed turns it into UndoUnsupported)."""


def _item(row):
    table, op = row["table"], row["op"]
    image = row["before"] if op == "DELETE" else row["after"]
    other = row["after"] if op == "DELETE" else row["before"]
    columns = {"order_id", "component_id", "position", *ITEM_COLUMNS[table]}
    if op not in ("INSERT", "DELETE") or other is not None or not isinstance(image, dict) or set(image) != columns:
        raise Refused("Only whole corrected order lists can be put back.")
    if type(image["position"]) is not int or image["position"] < 0 or type(image["quantity"]) is not int \
            or image["quantity"] < 1 or any(not isinstance(image[c], str) for c in columns - {"position", "quantity"}):
        raise Refused("A corrected order row has an unsupported schema.")
    if row.get("key") != {field: image[field] for field in KEYS[table]}:
        raise Refused("The original row identity cannot be checked.")
    return image


def groups(raw, received):
    """({(table, order, component): {"old": [image, ...], "new": [...], "ids": {position: audit id}}},
    [purchase_order rows]) from the change's rows of TABLES, or Refused. received: {(order,
    component): kind} of the parts the receipt marked received."""
    found, orders = {}, []
    for row in raw:
        if row["table"] == ORDER:
            before, after = row["before"], row["after"]
            if row["op"] != "UPDATE" or not isinstance(before, dict) or not isinstance(after, dict) \
                    or set(before) != ORDER_FIELDS or set(after) != ORDER_FIELDS \
                    or {f for f in ORDER_FIELDS if before[f] != after[f]} != {"audit_notes"} \
                    or row.get("key") != {"id": after["id"]} \
                    or not all(isinstance(v, str) or v is None for v in (before["audit_notes"], after["audit_notes"])):
                raise Refused("Only the order's fulfilment notes may change with a corrected receipt.")
            orders.append(row)
            continue
        if row["table"] not in ITEMS:
            continue
        image = _item(row)
        part = (image["order_id"], image["component_id"])
        if received.get(part) != KIND_OF[row["table"]]:
            raise Refused("Order rows changed outside the parts this receipt marked received.")
        group = found.setdefault((row["table"], *part), {"old": {}, "new": {}, "ids": {}})
        side = group["old" if row["op"] == "DELETE" else "new"]
        if image["position"] in side:
            raise Refused("The change names one row twice.")
        side[image["position"]] = image
        # The latest audit row of a position is this change's INSERT, else its DELETE.
        if row["op"] == "INSERT" or image["position"] not in group["ids"]:
            group["ids"][image["position"]] = row["id"]
    out = {}
    for key, group in found.items():
        for side in ("old", "new"):
            if sorted(group[side]) != list(range(len(group[side]))) or not group[side]:
                raise Refused("Only whole corrected order lists can be put back.")
        out[key] = {"old": [group["old"][n] for n in range(len(group["old"]))],
                    "new": [group["new"][n] for n in range(len(group["new"]))], "ids": group["ids"]}
    if len({row["key"]["id"] for row in orders}) != len(orders) \
            or {row["key"]["id"] for row in orders} - {order for _, order, _ in out}:
        raise Refused("The order's fulfilment notes changed without a corrected part.")
    return out, orders


def latest(found, orders):
    """[(table, key, audit id expected latest)] for undo_mixed's latest-audit check."""
    keyed = []
    for (table, order, component), group in found.items():
        for position, rid in sorted(group["ids"].items()):
            keyed.append((table, {"order_id": order, "component_id": component, "position": position}, rid))
    for row in orders:
        keyed.append((ORDER, row["key"], row["id"]))
    return keyed


def label(table, key):
    if table == ORDER:
        return f"order {key['id']}"
    return f"order {key['order_id']} ({key['component_id']})"


def _cells(table, image):
    return tuple(image[column] for column in ITEM_COLUMNS[table])


def _order_values(image):
    return (image["seller"], image["ordered_on"], tuple(image["sources"]), image["notes"], image["audit_notes"])


def current(t, found, orders):
    """None when the rows there now are what the receipt left, else the label of the first that isn't."""
    for (table, order, component), group in found.items():
        if t[table].get((order, component)) != tuple(_cells(table, image) for image in group["new"]):
            return label(table, {"order_id": order, "component_id": component})
    for row in orders:
        if t[ORDER].get(row["key"]["id"]) != _order_values(row["after"]):
            return label(ORDER, row["key"])
    return None


def payload_rows(table, images):
    """Payload dicts (the model's field names, every value a string) of an order list's images."""
    from . import rules
    fields = rules.FIELDS if table == CARDS else rules.TOKEN_FIELDS
    return [{field: str(image["set_code" if field == "set" else field]) for field in fields} for image in images]


def inverse(inv, found, orders):
    """inv with each corrected part's ordered rows back and each order's fulfilment notes as they were.
    Run after the parts are back on order (their payloads are where pending parts keep them)."""
    from .model import Order
    for (table, order, component), group in found.items():
        inv = inv.set_component_rows(order, component, payload_rows(table, group["old"]))
    for row in orders:
        record = inv.order(row["key"]["id"])
        if record is None or record.error is not None:
            raise ValueError("The order record can't be read")
        data = record.record()
        if data.get("audit_notes") != row["after"]["audit_notes"]:
            raise ValueError("The order's notes changed")
        if row["before"]["audit_notes"] is None:
            data.pop("audit_notes", None)
        else:
            data["audit_notes"] = row["before"]["audit_notes"]
        inv = inv.with_order(Order(record.file, data))
    return inv


def verify(before_t, after_t, found, orders):
    """The corrected parts' lists are back as ordered, the orders' notes as they were, and no other
    order row or list changed (raises ValueError otherwise)."""
    for table in ITEMS:
        keys = set(before_t[table]) | set(after_t[table])
        for key in keys:
            group = found.get((table, *key))
            want = tuple(_cells(table, image) for image in group["old"]) if group else before_t[table].get(key)
            if after_t[table].get(key) != want:
                raise ValueError(f"{table} wasn't put back exactly")
    restored = {row["key"]["id"]: _order_values(row["before"]) for row in orders}
    for key in set(before_t[ORDER]) | set(after_t[ORDER]):
        if after_t[ORDER].get(key) != restored.get(key, before_t[ORDER].get(key)):
            raise ValueError(f"{ORDER} wasn't put back exactly")


def corrections(found):
    """{(order, component): {"ordered": rows put back, "received": rows there now}} for the preview."""
    return {(order, component): {"ordered": len(group["old"]), "received": len(group["new"])}
            for (_table, order, component), group in found.items()}


def key_json(key):
    return json.dumps(key, sort_keys=True)
