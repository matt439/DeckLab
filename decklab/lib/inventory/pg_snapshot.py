"""The database rows as an Inventory snapshot (E11-S39): the read side of the database backend
(pg.py), split from it unchanged.

- _select(c) reads every inventory table in the caller's transaction, probing the schema as it
  goes (product_status.token_cards, migration 0014's; order_component's check links; collection
  locations, migration 0016's), and snapshot(data, revision) turns those rows into the files
  backend's Inventory: canonical CSVs (_render) read back by files.build, with the token and
  watchlist rows' hidden ids, the products' stored names and the raw imports from the database.
- _status_tables(t, columns) fits a write's product_status rows to an older schema, refusing a
  recorded packed-token value it can't hold.

pg.py keeps the cache, the revisions, the lock and every transaction, and re-exports these names
as the same objects, so pg._select, pg.snapshot and the rest stay where callers and tests find
them (pg's own calls look them up in pg, so patching pg._select still reaches its loads). This
module imports nothing from pg, so either can be imported first.
"""
import csv
import dataclasses
import io
from collections import defaultdict

from decklab.lib.state import Invalid

from . import files, paths, pg_check_links, pg_locations, rules
from .model import QUEUE_FIELDS, Component, ImportInfo, Order
from .table_rows import (CARD_COLUMNS, COMPONENT_COLUMNS, ITEM_TABLES, ORDER_COLUMNS, PAYLOAD_FIELDS,
                         STATUS_COLUMNS, TOKEN_COLUMNS, WATCH_COLUMNS)


def _render(columns, rows):
    """(bytes, [the line each row starts on]) of a CSV with this header and these rows, as the
    files backend writes it."""
    chunks, lines, line = [], [], 2
    head = io.StringIO()
    csv.writer(head, lineterminator="\n").writerow(columns)
    chunks.append(head.getvalue())
    for cells in rows:
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerow(["" if c is None else str(c) for c in cells])
        text = out.getvalue()
        lines.append(line)
        line += text.count("\n")
        chunks.append(text)
    return "".join(chunks).encode("utf-8"), lines


SELECTS = {
    "collection_card": "select space_id, set_code, collector_number, finish, name, quantity, condition, language, "
                       "notes from collection_card",
    "collection_import": "select i.space_id, i.file_name, i.size, i.sha256, i.imported_at, origin.name "
                         "from collection_import i left join lateral ("
                         "select coalesce(p.name, cs.actor) as name from audit.row_change rc "
                         "join audit.change_set cs on cs.id = rc.change_set_id "
                         "left join profile p on p.id = cs.actor "
                         "where rc.table_name = 'collection_import' and rc.op = 'INSERT' "
                         "and rc.row_key = jsonb_build_object('id', i.id) "
                         "order by rc.id limit 1) origin on true",
    "token_card": f"select id, space_id, position, {', '.join(TOKEN_COLUMNS)} from token_card",
    "watchlist_item": f"select id, position, {', '.join(WATCH_COLUMNS)} from watchlist_item",
    "product": "select stem, name, format, columns from product",
    "product_item": "select product_stem, position, cells from product_item",
    "product_status": f"select file, {', '.join(STATUS_COLUMNS)} from product_status",
    "purchase_order": f"select id, {', '.join(ORDER_COLUMNS)} from purchase_order",
    "order_component": f"select order_id, id, {', '.join(COMPONENT_COLUMNS)} from order_component",
    "order_card_item": f"select order_id, component_id, position, {', '.join(CARD_COLUMNS)} from order_card_item",
    "order_token_item": f"select order_id, component_id, position, {', '.join(TOKEN_COLUMNS)} from order_token_item",
}


def _select(c):
    columns = _status_columns(c)
    status = "select file, " + ", ".join(column if column in columns else "''::text as token_cards"
                                         for column in STATUS_COLUMNS) + " from product_status"
    component = pg_check_links.select(c)
    queries = {**SELECTS, "product_status": status, "order_component": component,
               "collection_card": pg_locations.select(c)}
    data = {table: c.execute(query).fetchall() for table, query in queries.items()}
    data["locations_ready"] = pg_locations.ready(c)
    return data


def _status_columns(c):
    """Probe the actual column, without caching absence across a later migration."""
    ready = c.execute("select exists(select 1 from pg_catalog.pg_attribute "
                      "where attrelid=to_regclass('public.product_status') and attname='token_cards' "
                      "and not attisdropped)").fetchone()[0]
    return STATUS_COLUMNS if ready else tuple(column for column in STATUS_COLUMNS if column != "token_cards")


def _status_tables(t, columns):
    """Old schemas can represent blank unknown packing, never discard a recorded value."""
    if columns == STATUS_COLUMNS:
        return t
    token_at = STATUS_COLUMNS.index("token_cards")
    if any(row[token_at] for row in t["product_status"].values()):
        raise Invalid("Product packed token cards require migration 0014. Run the database migrations first.")
    indices = [STATUS_COLUMNS.index(column) for column in columns]
    return {**t, "product_status": {key: tuple(row[index] for index in indices)
                                    for key, row in t["product_status"].items()}}


def snapshot(data, revision):
    """The Inventory the rows of every table hold (data: {table: rows} as _select reads them). A
    collection row's storage location (E8-S22) becomes its space's locations.csv."""
    out = {}
    cards = defaultdict(list)
    for space, set_code, number, finish, name, qty, condition, language, notes, *location in data["collection_card"]:
        cards[space].append({"name": name, "set": set_code, "collector_number": number, "finish": finish,
                             "quantity": str(qty), "condition": condition, "language": language, "notes": notes,
                             "location": location[0] if location else ""})
    for space, rows in cards.items():
        rows.sort(key=rules.sort_key)
        out[paths.collection(space)] = _render(rules.FIELDS, [[r[k] for k in rules.FIELDS] for r in rows])[0]
        located = [[r[k] for k in rules.LOCATION_FIELDS] for r in rows if r["location"]]
        if located:
            out[paths.locations(space)] = _render(rules.LOCATION_FIELDS, located)[0]
    token_ids = {}
    tokens = defaultdict(list)
    for row in data["token_card"]:
        tokens[row[1]].append(row)
    for space, rows in tokens.items():
        rows.sort(key=lambda r: (r[2], r[0]))
        out[paths.tokens(space)], lines = _render(rules.TOKEN_FIELDS, [r[3:] for r in rows])
        token_ids[space] = dict(zip(lines, (r[0] for r in rows)))
    watch = sorted(data["watchlist_item"], key=lambda r: (r[1], r[0]))
    out[paths.WATCHLIST], lines = _render(QUEUE_FIELDS, [r[2:] for r in watch])
    watch_ids = dict(zip(lines, (r[0] for r in watch)))
    status = sorted(data["product_status"], key=lambda r: (r[1], r[0]))
    out[paths.STATUS] = _render(rules.STATUS_FIELDS, [(r[0], *r[2:]) for r in status])[0]
    items = defaultdict(list)
    for stem, position, cells in data["product_item"]:
        items[stem].append((position, cells))
    names = {}
    for stem, name, fmt, columns in data["product"]:
        names[stem] = (name, fmt)
        out[paths.product(stem)] = _render(columns, [cells for _, cells in sorted(items[stem])])[0]
    payload_rows = defaultdict(list)
    for table in ITEM_TABLES.values():
        for row in data[table]:
            payload_rows[(row[0], row[1])].append((row[2], row[3:]))
    components = defaultdict(list)
    for row in data["order_component"]:
        components[row[0]].append(row)
    for oid, seller, ordered_on, sources, notes, audit_notes in data["purchase_order"]:
        built = []
        for row in sorted(components[oid], key=lambda r: r[2]):
            _, cid, _, kind, file_name, status_, received_on, checks, verified, _ = row[:10]
            metadata = row[10] if len(row) > 10 else None
            built.append(Component.build(cid, kind, file_name, status_, received_on, checks, verified, metadata))
            if kind != "product":
                rows = [cells for _, cells in sorted(payload_rows[(oid, cid)], key=lambda r: r[0])]
                out[paths.payload(kind, status_, file_name)] = _render(PAYLOAD_FIELDS[kind], rows)[0]
        order = Order.build(oid, seller, ordered_on, sources, notes, built, audit_notes)
        out[paths.record(oid)] = rules.json_bytes(order.data)
    inv = files.build(out, revision=str(revision), backend="db").replace(
        locations_ready=data.get("locations_ready", True))
    imports = defaultdict(list)
    for space, file_name, size, digest, at, actor in data["collection_import"]:
        imports[space].append(ImportInfo(file_name, size, digest, at.isoformat() if at else None, actor))
    return inv.replace(
        imports={space: tuple(sorted(found, key=lambda i: i.name)) for space, found in sorted(imports.items())},
        products=tuple(dataclasses.replace(p, name=names[p.stem][0], format=names[p.stem][1]) for p in inv.products),
        tokens={space: dataclasses.replace(sheet, rows=tuple(
            dataclasses.replace(row, id=token_ids.get(space, {}).get(row.line, 0)) for row in sheet.rows))
            for space, sheet in inv.tokens.items()},
        watchlist=dataclasses.replace(inv.watchlist, rows=tuple(
            dataclasses.replace(row, id=watch_ids.get(row.line, 0)) for row in inv.watchlist.rows)))
