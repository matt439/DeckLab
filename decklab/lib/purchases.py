"""Current shopping state, read from the queue and per-order records.

No card cache, network request, inventory mutation or price refresh is needed.
Personal wishlists and dated buying research are deliberately not purchase orders.
Run ``python -m decklab.lib.purchases --check`` to validate the records and queue.

Everything comes from one inventory snapshot (decklab/lib/inventory: inventory.current()),
whichever backend holds it. The paths in records and messages (a component's "path",
"watchlist.csv:3: wrong number of columns") are where each piece is as a file, worked out from
what it is, so both backends say the same. The buylist files a record or the watchlist names as
its source are still checked on disk; a deck file's path there is checked against the
snapshot's decks, or a retired deck's durable saved history (source_exists: the phase 4
design's R9). Retirement never discards recorded purchasing intent.
"""
import argparse
import contextlib
import csv
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from decklab.lib import config, inventory
from decklab.lib.inventory import entry, paths, unreadable
from decklab.lib.inventory.model import Product, name_order

STATES = ("ready", "waiting_for_stock", "waiting_for_reprint", "deferred", "long_term")
STATUSES = ("pending", "received", "cancelled")
QUEUE_FIELDS = ("name", "set", "collector_number", "finish", "quantity", "for",
                "printing", "listed_aud", "listed_at", "in_stock", "checked", "notes",
                "state", "source")
ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _text(value, where, *, blank=True):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError(f"{where}: expected single-line text")
    if not blank and not value.strip():
        raise ValueError(f"{where}: must not be blank")
    return value


def _date(value, where):
    _text(value, where)
    if value:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError(f"{where}: expected YYYY-MM-DD") from None
    return value


def repo_path(root, value, where="path"):
    """Resolve only portable, canonical paths within this repository."""
    _text(value, where, blank=False)
    path = PurePosixPath(value)
    if (path.is_absolute() or "\\" in value or ":" in value or ".." in path.parts
            or str(path) != value):
        raise ValueError(f"{where}: expected a relative repository path")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{where}: path leaves the repository")
    return resolved


def _retired_source(deck_id, checked=None):
    """Whether a missing deck has a saved text immediately before its latest deletion.

    At most two bounded history reads, with no text returned to a page. checked is one
    validation pass's memo, never a process cache: a later request must read history again.
    Unavailable history stays an error rather than turning a source into an absent file.
    """
    if checked is not None and deck_id in checked:
        return checked[deck_id]
    latest = inventory.last_revision(deck_id)
    retired = False
    if latest is not None and latest.op == "D" and latest.revision > 1:
        before = inventory.deck_revision(deck_id, latest.revision - 1)
        retired = before is not None and before.op != "D" and before.text is not None
    if checked is not None:
        checked[deck_id] = retired
    return retired


def source_exists(root, value, where="path", inv=None, *, retired=None):
    """Whether the research or deck file a watchlist row's or an order record's source names is
    there (ValueError for a path that isn't a portable one in the repository, as repo_path). A
    deck file's path (magic/decks/<kind>/<slug>.md, magic/people/<id>/decks/...) is looked for
    among the decks of inv (inventory.current() by default), whichever backend holds them, so a
    source keeps naming the deck as its file did (the phase 4 design's R9: the string is never
    rewritten). When the deck is retired, its last deletion and preceding saved text keep the
    source valid; an arbitrary missing id or one without durable history does not. retired is
    an optional memo shared only within one validation pass. Any other path is looked for on
    disk under root, or under config.json's records_repo when root is this checkout
    (config.records_dir)."""
    resolved = repo_path(root, value, where)
    found = paths.classify(value)
    if found is not None and found[0] == "deck":
        space, kind, slug = found[1]
        deck_id = f"{kind}/{slug}" if space == paths.HOME else f"{space}/{kind}/{slug}"
        current = inventory.current() if inv is None else inv
        deck_id = inventory.resolve_deck_id(deck_id, current)
        return current.deck(deck_id) is not None or (
            current.backend == "db" and _retired_source(deck_id, retired))
    records = config.records_dir(root)
    if Path(records).resolve() != Path(root).resolve():
        return repo_path(records, value, where).is_file()
    return resolved.is_file()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strings(value, where):
    if not isinstance(value, list):
        raise ValueError(f"{where}: expected a list")
    return [_text(item, where, blank=False) for item in value]


def _source(inv, path):
    """The inventory source whose file is path (repo-relative): the watchlist, the status list, an
    order payload or a product; None when the snapshot has none there."""
    if path == paths.WATCHLIST:
        return inv.watchlist
    if path == paths.STATUS:
        return inv.status
    if path in inv.payloads:
        return inv.payloads[path]
    found = paths.classify(path)
    if found is not None and found[0] == "product":
        return inv.product(found[1])
    return None


def _end_line(row):
    """The line a row ends on, as csv's line_num says after reading it (a quoted value can hold
    line breaks)."""
    breaks = sum(len(re.findall(r"\r\n|\r|\n", value)) for _, value in row.values if value)
    return row.line + breaks


def _csv(path, required, inv=None):
    """The rows of the inventory source at path (repo-relative) as dicts, read strictly as
    csv.DictReader(strict=True) reads its file: every required column, no repeated one, and
    every row exactly as long as the header. Raises what reading the file raised (FileNotFoundError
    when it isn't there, csv.Error for one that can't be parsed) and ValueError for the rest.
    inv: the snapshot to read (inventory.current() by default)."""
    source = _source(inventory.current() if inv is None else inv, path)
    name = PurePosixPath(path).name
    if source is None:
        raise unreadable.missing(path)
    unreadable.check(source)
    if source.csv_error is not None:
        raise csv.Error(source.csv_error)
    fields = list(source.columns or ())
    if len(fields) != len(set(fields)) or not set(required) <= set(fields):
        raise ValueError(f"{name}: missing or duplicate columns")
    rows = []
    for row in (source.items if isinstance(source, Product) else source.rows):
        found = row.as_dict()
        if None in found or None in found.values():
            raise ValueError(f"{name}:{_end_line(row)}: wrong number of columns")
        rows.append(found)
    return rows


def _quantity(value, where):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value) or int(value) < 1:
        raise ValueError(f"{where}: quantity must be a positive integer")
    return int(value)


def read_queue():
    """The watchlist's rows (magic/watchlist.csv), checked, as dicts in its order (quantity an
    int); ValueError naming the first problem."""
    root = Path(config.REPO)
    inv = inventory.current()           # the rows and the decks their sources name: one snapshot
    rows = _csv(paths.WATCHLIST, QUEUE_FIELDS, inv)
    seen, retired = set(), {}
    for row in rows:
        where = f"watchlist: {row['name']}"
        for value in row.values():
            _text(value, where)
        _text(row["name"], where, blank=False)
        row["quantity"] = _quantity(row["quantity"], where)
        if row["state"] not in STATES:
            raise ValueError(f"{where}: invalid purchase state")
        if row["printing"] not in ("any", "exact"):
            raise ValueError(f"{where}: printing must be any or exact")
        if row["finish"] not in ("", "nonfoil", "foil", "etched"):
            raise ValueError(f"{where}: invalid finish")
        if row["printing"] == "exact" and not all(row[k] for k in ("set", "collector_number", "finish")):
            raise ValueError(f"{where}: exact printing needs set, collector number and finish")
        if row["in_stock"] not in ("", "yes", "no"):
            raise ValueError(f"{where}: stock must be yes, no or blank")
        _date(row["checked"], where)
        if row["listed_aud"]:
            try:
                price = Decimal(row["listed_aud"])
                if not price.is_finite() or price < 0:
                    raise InvalidOperation()
            except InvalidOperation:
                raise ValueError(f"{where}: invalid AUD reference price") from None
            if not row["checked"] or not row["listed_at"]:
                raise ValueError(f"{where}: reference price needs retailer and checked date")
        if row["source"] and not source_exists(root, row["source"], inv=inv, retired=retired):
            raise ValueError(f"{where}: source file does not exist")
        key = tuple(row[k] for k in ("name", "printing", "set", "collector_number", "finish", "for"))
        if key in seen:
            raise ValueError(f"{where}: duplicate purchase request")
        seen.add(key)
    return rows


def order_status(components):
    statuses = {c["status"] for c in components}
    if statuses == {"cancelled"}:
        return "cancelled"
    if "pending" in statuses:
        return "partial" if "received" in statuses else "pending"
    return "received"


def _exists(inv, value):
    """Whether the inventory has the file a component's path names (its payload or product)."""
    return isinstance(_source(inv, value), Product) or (value in inv.payloads and inv.payloads[value].exists)


def read_records(root=None):
    """The order records (magic/orders/records/*.json) checked, as dicts in file-name order;
    ValueError naming the first problem. Each component's file must be where its kind and
    status put it (the paths pool.py and the Shopping page name).

    root: another tree to read (a test's): its inventory files are read as they are, and the
    records' sources are looked for there. The repo itself (config.REPO, the default) reads the
    inventory as any reader does."""
    if root is not None and Path(root).resolve() != Path(config.REPO).resolve():
        from decklab.lib.inventory.files import FileInventory
        with inventory.pinned(FileInventory(root).load()):
            return _read_records(Path(root))
    return _read_records(Path(config.REPO))


def _read_records(root):
    inv = inventory.current()
    records, seen, retired = [], set(), {}
    for order in inv.orders:
        name = order.file
        if order.error is not None:     # an OSError or UnicodeDecodeError again, else json's ValueError
            error = unreadable.again(order.error)
            raise ValueError(order.error) if isinstance(error, csv.Error) else error
        record = order.record()
        if not isinstance(record, dict) or type(record.get("version")) is not int or record["version"] != 1:
            raise ValueError(f"{name}: expected order record version 1")
        stem = PurePosixPath(name).stem
        if record.get("id") != stem or not ID_RE.fullmatch(stem):
            raise ValueError(f"{name}: invalid order id")
        for key in ("seller", "notes"):
            _text(record.get(key), f"{name}: {key}")
        if "audit_notes" in record:
            _text(record["audit_notes"], f"{name}: audit_notes")
        ordered = _date(record.get("ordered_on"), f"{name}: ordered_on")
        for source in _strings(record.get("sources"), f"{name}: sources"):
            if not source_exists(root, source, inv=inv, retired=retired):
                raise ValueError(f"{name}: source {source} does not exist")
        components = record.get("components")
        if not isinstance(components, list) or not components:
            raise ValueError(f"{name}: order needs components")
        ids = set()
        for component in components:
            if not isinstance(component, dict):
                raise ValueError(f"{name}: invalid component")
            ident = component.get("id", "")
            if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or ident in ids:
                raise ValueError(f"{name}: invalid or repeated component id")
            ids.add(ident)
            where = f"{name}: {ident}"
            kind, status = component.get("kind"), component.get("status")
            if kind not in ("cards", "tokens", "product") or status not in STATUSES:
                raise ValueError(f"{where}: invalid kind or status")
            received = _date(component.get("received_on"), where)
            if received and (status != "received" or (ordered and received < ordered)):
                raise ValueError(f"{where}: receipt date conflicts with status or order date")
            _strings(component.get("checks"), where)
            if "verified_checks" in component:
                _strings(component["verified_checks"], where)
            value = component.get("path")
            repo_path(root, value, where)
            prefix = "magic/products" if kind == "product" else "magic/orders" + ("/tokens" if kind == "tokens" else "")
            if kind != "product" and status != "pending":
                prefix += "/" + status
            if PurePosixPath(value).parent.as_posix() != prefix or PurePosixPath(value).suffix != ".csv":
                raise ValueError(f"{where}: file location conflicts with kind/status")
            if value in seen:
                raise ValueError(f"{where}: component file occurs in more than one order")
            seen.add(value)
            if not _exists(inv, value):
                raise ValueError(f"{where}: component file does not exist")
        records.append(record)
    return records


def _contents(component):
    required = ("front", "back", "quantity") if component["kind"] == "tokens" else ("name", "quantity")
    rows = _csv(component["path"], required)
    items = []
    for row in rows:
        name = " // ".join(filter(None, (row["front"], row["back"]))) if component["kind"] == "tokens" else row["name"]
        _text(name, component["path"], blank=False)
        items.append({"name": name, "quantity": _quantity(row["quantity"], component["path"])})
    label = "Playable cards" if component["kind"] == "cards" else "Tokens and reminders"
    if component["kind"] == "product":
        stem = PurePosixPath(component["path"]).stem
        label = (inventory.current().product(stem) or Product(stem)).label("shopping")
    return {**component, "label": label, "rows": len(items),
            "quantity": sum(item["quantity"] for item in items), "items": items}


def _coverage(records):
    """Missing metadata is an explicit validation problem, never a hidden delivery."""
    inv = inventory.current()
    covered = {c["path"]: c for record in records for c in record["components"]}
    warnings = []
    for folder in paths.PAYLOAD_FOLDERS:
        listed = [p for p in inv.payloads if PurePosixPath(p).parent.as_posix() == folder]
        for path in sorted(listed, key=lambda p: name_order(PurePosixPath(p).name)):
            if path not in covered:
                warnings.append(f"{path}: missing order record")
    statuses = _csv(paths.STATUS, ("file", "status", "intact", "notes"))
    seen = set()
    for row in statuses:
        value = "magic/products/" + row["file"]
        if value in seen or row["status"] not in ("owned", "ordered", "preordered", "cancelled"):
            raise ValueError(f"{value}: duplicate product or invalid status")
        seen.add(value)
        component = covered.get(value)
        if component is None:
            warnings.append(f"{value}: missing order record")
        elif component["status"] != ("received" if row["status"] == "owned" else
                                     "cancelled" if row["status"] == "cancelled" else "pending"):
            warnings.append(f"{value}: product and order receipt statuses disagree")
    for value, component in covered.items():
        if component["kind"] == "product" and value not in seen:
            warnings.append(f"{value}: missing product status")
    return warnings


def overview():
    """The Shopping page's data: {"to_buy": the watchlist (read_queue), "orders": every order
    record with its status and each component's contents, newest first, "checks": the open
    physical checks of components that aren't cancelled, "warnings": []}, from one inventory
    snapshot. ValueError (or OSError, csv.Error) when the records or the watchlist need
    attention."""
    with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
        records = read_records()
        warnings = _coverage(records)
        if warnings:
            raise ValueError("Shopping records need attention: " + "; ".join(warnings))
        orders, checks = [], []
        for record in records:
            components = [_contents(c) for c in record["components"]]
            orders.append({**record, "status": order_status(components), "components": components})
            for component in components:
                if component["status"] != "cancelled":
                    checks.extend({"order_id": record["id"], "component_id": component["id"],
                                   "seller": record["seller"], "status": component["status"], "text": check}
                                  for check in component["checks"])
        orders.sort(key=lambda order: (order["ordered_on"], order["id"]), reverse=True)
        return {"to_buy": read_queue(), "orders": orders, "checks": checks, "warnings": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args(argv)
    with entry.command():           # the venv, and one inventory snapshot for the command
        try:
            data = overview()
        except inventory.Unavailable as error:
            print(f"Shopping validation failed: {error}")
            return 2
        except (OSError, ValueError, csv.Error) as error:
            print(f"Shopping validation failed: {error}")
            return 1
    if args.check:
        print(f"Shopping records valid: {len(data['orders'])} orders, {len(data['to_buy'])} queued purchases.")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
