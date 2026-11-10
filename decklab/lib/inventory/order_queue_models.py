"""Canonical order/product projections for complete order-and-queue audit inverses. No I/O."""
import copy
import json

from . import files, model, paths, pg_snapshot, table_rows

ORDER = "purchase_order"
COMPONENT = "order_component"
ITEMS = ("order_card_item", "order_token_item")
PRODUCT = "product"
PRODUCT_ITEM = "product_item"
STATUS = "product_status"
TABLES = (ORDER, COMPONENT, *ITEMS, PRODUCT, PRODUCT_ITEM, STATUS)
KEYS = {ORDER: ("id",), COMPONENT: ("order_id", "id"), ITEMS[0]: ("order_id", "component_id", "position"),
        ITEMS[1]: ("order_id", "component_id", "position"), PRODUCT: ("stem",),
        PRODUCT_ITEM: ("product_stem", "position"), STATUS: ("file",)}
COLUMNS = {ORDER: ("id", *table_rows.ORDER_COLUMNS), COMPONENT: ("order_id", "id", *table_rows.COMPONENT_COLUMNS),
           ITEMS[0]: (*KEYS[ITEMS[0]], *table_rows.CARD_COLUMNS), ITEMS[1]: (*KEYS[ITEMS[1]], *table_rows.TOKEN_COLUMNS),
           PRODUCT: ("stem", "name", "format", "columns"), PRODUCT_ITEM: ("product_stem", "position", "cells"),
           STATUS: ("file", *table_rows.STATUS_COLUMNS)}


def key(table, image):
    return json.dumps({field: image[field] for field in KEYS[table]}, sort_keys=True, separators=(",", ":"))


def plain(value):
    if isinstance(value, table_rows.JsonColumn):
        return copy.deepcopy(value.value)
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


def normalized(table, image):
    """Only known additive nullable columns bridge historical schema versions."""
    if not isinstance(image, dict):
        raise ValueError("An order audit image isn't a whole recorded row")
    image = copy.deepcopy(image)
    if table == COMPONENT and "check_links" not in image:
        image["check_links"] = None
    if table == STATUS and "token_cards" not in image:
        image["token_cards"] = ""
    if set(image) != set(COLUMNS[table]):
        raise ValueError("An order audit image has an unsupported schema")
    for field, value in image.items():
        if field in ("position", "quantity"):
            if type(value) is not int or not (0 if field == "position" else 1) <= value < 2 ** 31:
                raise ValueError("A recorded order count or position isn't valid")
        elif table == PRODUCT and field in ("name", "format") or table == ORDER and field == "audit_notes" \
                or table == COMPONENT and field == "product_stem":
            if value is not None and not isinstance(value, str):
                raise ValueError("A nullable order fact isn't text")
        elif field in ("sources", "checks", "verified_checks", "columns", "cells"):
            if field == "verified_checks" and value is None:
                continue
            if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
                raise ValueError("A recorded order list isn't a list of text")
        elif field == "check_links":
            if value is not None and not isinstance(value, dict):
                raise ValueError("A recorded arrival check isn't a JSON object")
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8", errors="strict")
        elif not isinstance(value, str):
            raise ValueError("A recorded order fact isn't text")
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
            if "\0" in value:
                raise ValueError("A recorded order fact isn't database text")
    if table == COMPONENT and ((image["kind"] == "product") != bool(image["product_stem"])):
        raise ValueError("An order component's product identity cannot be checked")
    return image


def images(inv):
    """Order resources only: another member's collection/deck errors never enter this read."""
    relevant = inv.replace(collections={}, tokens={}, locations={}, loans={}, dice={}, imports={}, decks={}, deck_aliases={},
                          accessories=files.accessories_sheet(None), accessory_images={},
                          watchlist=model.Sheet(paths.WATCHLIST, tuple(model.QUEUE_FIELDS), (), True))
    source = table_rows.tables(relevant)
    out = {table: {} for table in TABLES}
    for table, columns in ((ORDER, table_rows.ORDER_COLUMNS), (COMPONENT, table_rows.COMPONENT_COLUMNS), (STATUS, table_rows.STATUS_COLUMNS)):
        for identity, values in source[table].items():
            identity = identity if isinstance(identity, tuple) else (identity,)
            image = {**dict(zip(KEYS[table], identity)), **{field: plain(value) for field, value in zip(columns, values)}}
            out[table][key(table, image)] = normalized(table, image)
    for table, columns in table_rows.ITEM_COLUMNS.items():
        for (order_id, component), rows in source[table].items():
            for position, values in enumerate(rows):
                image = {"order_id": order_id, "component_id": component, "position": position,
                         **{field: plain(value) for field, value in zip(columns, values)}}
                out[table][key(table, image)] = normalized(table, image)
    for stem, values in source[PRODUCT].items():
        image = dict(zip(COLUMNS[PRODUCT], (stem, *map(plain, values))))
        out[PRODUCT][key(PRODUCT, image)] = normalized(PRODUCT, image)
    for stem, rows in source[PRODUCT_ITEM].items():
        for position, cells in enumerate(rows):
            image = {"product_stem": stem, "position": position, "cells": plain(cells)}
            out[PRODUCT_ITEM][key(PRODUCT_ITEM, image)] = normalized(PRODUCT_ITEM, image)
    return out


def restore(inv, current, wanted):
    """Rebuild only order resources through the established database snapshot reader."""
    data = {table: [] for table in pg_snapshot.SELECTS}
    for table in TABLES:
        data[table] = [tuple(image[field] for field in COLUMNS[table]) for _, image in sorted(wanted[table].items())]
    rebuilt = pg_snapshot.snapshot(data, inv.revision)
    after = inv.replace(orders=rebuilt.orders, payloads=rebuilt.payloads)
    if current[PRODUCT] != wanted[PRODUCT] or current[PRODUCT_ITEM] != wanted[PRODUCT_ITEM]:
        after = after.replace(products=rebuilt.products)
    if current[STATUS] != wanted[STATUS]:
        after = after.replace(status=rebuilt.status)
    if images(after) != wanted:
        raise ValueError("The historical order resources cannot be put back exactly")
    return after


def audit_delta(before, after):
    """Expected ordinary writer rows, including full item-list DELETE/INSERT replacements."""
    expected = []
    for table in TABLES:
        old, new = before[table], after[table]
        if table in (*ITEMS, PRODUCT_ITEM):
            group_fields = KEYS[table][:-1]
            groups = {tuple(image[field] for field in group_fields) for image in [*old.values(), *new.values()]}
            for group in groups:
                left = {k:v for k,v in old.items() if tuple(v[f] for f in group_fields) == group}
                right = {k:v for k,v in new.items() if tuple(v[f] for f in group_fields) == group}
                if left != right:
                    expected += [(table, "DELETE", k, image, None) for k,image in left.items()]
                    expected += [(table, "INSERT", k, None, image) for k,image in right.items()]
        else:
            for identity in old.keys() | new.keys():
                was, now = old.get(identity), new.get(identity)
                if was != now:
                    expected.append((table, "INSERT" if was is None else "DELETE" if now is None else "UPDATE", identity, was, now))
    return sorted(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for row in expected)
