"""Receiving a recorded order's components: the receipt operation the Receipts page
(api/receipts.py) and `python -m decklab.db receive` (decklab/db/inv_receive.py) share.

    op = receive.op("2026-10-07-shop-a", [{"id": "cards", "verified": True}], "2026-10-09")
    found = receive.blockers(inventory.current(), op)     # what must be done first ([] when nothing)
    after, summary = inventory.preview(op)                # or inventory.apply(op, actor, message, ...)

Each component the caller says has arrived is an input {id, verified, rows?, intact?, take?}:
- id names a pending component of the order;
- verified says its physical checks were done and its rows now hold the actual received facts.
  A cards component with checks, and every tokens component, needs it;
- rows (cards and tokens only): the component's rows as received, replacing its recorded ones
  under today's rules: the same columns, the same total quantity and, for cards, the same copies
   of each name. For a partial receipt these remain the complete component's rows, with
   printing/finish checks applied to the arrived copies;
- intact (products only, required): "yes" keeps it as its decks in its own sleeves and box,
  "no" breaks it up into the shared pool (clearing its sleeves and deck box).
- take (cards/tokens only, optional): distinct {row, quantity?} selections using one-based
  indexes into the full submitted row order, or the stored rows when rows is omitted. A
  partial selection leaves the original component pending with its checks, splits out a
  collision-free received part, and receives it in this same change. No take receives all.

What the receipt does, as one change:
- a cards component's rows, and a product's playable cards, merge into home's collection
  (rules.merge_rows: quantities add on (set, collector number, finish); ordinary basic lands
  are left out; differing condition or language goes blank with a note);
- a tokens component's rows merge into home's tokens (rules.merge_tokens: only fully known equal
  cards merge), each row first passing the incoming rules (no unresolved pairing note; a blank
  reverse needs "single-sided verified");
- a product's status row becomes owned with the intact choice and "Received <date>" in its notes;
- each component becomes received on the date; a cards or tokens component's payload moves to
  received/ (its path in the record moves with it) and its checks become verified_checks; a
  product keeps its checks (its tokens are still to be recorded);
- the deck tables the new inventory makes stale are refreshed in the same change (the kind is
  registered with refresh=True: refresh.in_op, its outcome in Summary.extra["tables"]; a plan
  that fails leaves the decks as they were and the receipt goes ahead).

Refusals (state.Invalid) keep the receipt planner's words: an unknown order or component, one
that isn't pending, a date before the order's, a record or payload that breaks the records'
rules, a payload another record also names, an archive already there, rows that break the rules
above, and any blocker left (blockers() words them for the page or the command line).
"""
import csv
import copy
import io
from collections import Counter
from pathlib import PurePosixPath

from decklab.lib.state import Invalid

from . import Op, Summary, files, paths, register, rules
from .model import TokenRow

KIND = "receipt.receive"
COMPONENT_KINDS = ("cards", "tokens", "product")
STATUSES = ("pending", "received", "cancelled")
INCOMING = ("ordered", "preordered")
FIELDS = {"cards": list(rules.FIELDS), "tokens": list(rules.TOKEN_FIELDS)}


def op(order, components, received_on, wording="web"):
    """The receipt operation for order: components the arrived inputs (see the module
    docstring), received_on the actual arrival date (YYYY-MM-DD); wording "web" or "cli" for
    the blockers' words."""
    chosen = []
    for item in components:
        made = {"id": item["id"], "verified": bool(item.get("verified"))}
        if item.get("rows") is not None:
            made["rows"] = [dict(row) for row in item["rows"]]
        if item.get("intact") is not None:
            made["intact"] = item["intact"]
        if "take" in item:
            made["take"] = copy.deepcopy(item["take"])
        chosen.append(made)
    return Op(KIND, {"order": order, "components": chosen, "received_on": received_on, "wording": wording})


# ------------------------------------------------------------------ reading a record

def _text(value, where):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise Invalid(f"{where}: expected single-line text")
    return value


def _date(value, where):
    _text(value, where)
    if value:
        try:
            rules.valid_date(value)
        except ValueError:
            raise Invalid(f"{where}: expected YYYY-MM-DD") from None
    return value


def _source(value, where):
    """A source: a portable repo-relative path (purchases.repo_path's rule). Whether its file
    exists is the docs tree's business, not the inventory's (the database holds only the text):
    `python -m decklab.lib.purchases --check` reports a missing one."""
    _text(value, where)
    path = PurePosixPath(value)
    if not value.strip() or path.is_absolute() or "\\" in value or ":" in value or ".." in path.parts \
            or str(path) != value:
        raise Invalid(f"{where}: expected a relative repository path")
    return value


def record(inv, order_id):
    """The order's record (an Order whose data follows the records' rules, as purchases'
    read_records checks them, all but whether each source's file exists), state.Invalid
    otherwise. Its component files may not be named by any other record."""
    if not isinstance(order_id, str) or not rules.SLUG.fullmatch(order_id):
        raise Invalid("Order ID must contain lowercase letters, numbers and hyphens")
    order = next((o for o in inv.orders if o.file == f"{order_id}.json"), None)
    if order is None:
        raise Invalid(f"No order record for {order_id}")
    name = f"Order {order_id}"           # the database's words (E11-S12), as purchases names it
    if order.error is not None:
        raise Invalid(f"{name}: {order.error}")
    data = order.data
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise Invalid(f"{name}: expected order record version 1")
    if data.get("id") != order_id:
        raise Invalid(f"{name}: invalid order id")
    for key in ("seller", "notes"):
        _text(data.get(key), f"{name}: {key}")
    if "audit_notes" in data:
        _text(data["audit_notes"], f"{name}: audit_notes")
    ordered = _date(data.get("ordered_on"), f"{name}: ordered_on")
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise Invalid(f"{name}: sources: expected a list")
    for source in sources:
        _source(source, f"{name}: sources")
    elsewhere = {c.path for other in inv.orders if other.file != order.file for c in other.components
                 if isinstance(c.path, str)}
    items = data.get("components")
    if not isinstance(items, list) or not items:
        raise Invalid(f"{name}: order needs components")
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise Invalid(f"{name}: invalid component")
        ident = item.get("id", "")
        if not isinstance(ident, str) or not rules.SLUG.fullmatch(ident) or ident in ids:
            raise Invalid(f"{name}: invalid or repeated component id")
        ids.add(ident)
        where = f"{name}: {ident}"
        kind, status = item.get("kind"), item.get("status")
        if kind not in COMPONENT_KINDS or status not in STATUSES:
            raise Invalid(f"{where}: invalid kind or status")
        received = _date(item.get("received_on"), where)
        if received and (status != "received" or (ordered and received < ordered)):
            raise Invalid(f"{where}: receipt date conflicts with status or order date")
        for key in ("checks", "verified_checks"):
            if key in item or key == "checks":
                value = item.get(key)
                if not isinstance(value, list) or any(not isinstance(t, str) or not t.strip() for t in value):
                    raise Invalid(f"{where}: {key} must be a list of text")
        path = item.get("path")
        if not isinstance(path, str) or PurePosixPath(path).suffix != ".csv" \
                or path != paths.payload(kind, status, PurePosixPath(path).name):
            raise Invalid(f"{where}: where its contents are kept conflicts with its kind/status")
        there = inv.product(PurePosixPath(path).stem) is not None if kind == "product" else path in inv.payloads
        if path in elsewhere:
            raise Invalid(f"{where}: another order names its contents too")
        if not there:
            raise Invalid(f"{where}: its contents are missing")
    return order


def selected(inv, order_id, components):
    """(the Order, [Component] the inputs name, in the record's order). state.Invalid for an
    unknown or repeated id, an empty selection, or a component that isn't pending."""
    order = record(inv, order_id)
    known = {c.id: c for c in order.components}
    wanted = [item.get("id") for item in components]
    if not wanted or len(set(wanted)) != len(wanted) or set(wanted) - set(known):
        raise Invalid("No pending components selected, or an unknown component was named")
    chosen = [c for c in order.components if c.id in set(wanted)]
    for component in chosen:
        if component.status != "pending":
            raise Invalid(f"{component.id} is already {component.status}; it cannot be received again")
    return order, chosen


def blockers(inv, operation):
    """What must be done before the receipt can be applied, in the operation's wording ([] when
    nothing): an unverified component that needs verifying, a product with no intact choice.
    Raises state.Invalid for what can't be received at all (see selected())."""
    params = operation.params
    _, chosen = selected(inv, params["order"], params["components"])
    by_id = {item["id"]: item for item in params["components"]}
    cli = params.get("wording") == "cli"
    out = []
    for component in chosen:
        given = by_id[component.id]
        if component.kind != "product" and (component.checks or component.kind == "tokens") \
                and not given.get("verified"):
            out.append(f"{component.id}: resolve checks/edit received facts, then --verified {component.id}" if cli
                       else f"{component.id}: inspect it, record the actual received facts, then confirm you did")
        if component.kind == "product" and given.get("intact") not in ("yes", "no"):
            out.append(f"{component.id}: specify --intact yes or --intact no" if cli
                       else f"{component.id}: choose whether the product stays intact")
    return out


def payload_rows(inv, component):
    """A cards or tokens component's rows as the strict reader reads them ([{column: text}],
    exactly the payload's standard columns); state.Invalid when the payload breaks that rule."""
    sheet = inv.payloads.get(component.path)
    if sheet is None or not sheet.exists:
        raise Invalid(f"{paths.title(inv.describe(component.path))}: not in the inventory")
    if sheet.error is not None:
        raise Invalid(f"{paths.title(inv.describe(component.path))}: {sheet.error}")
    text = files.render_sheet(sheet).decode("utf-8")
    try:
        return rules.parse_csv(io.StringIO(text, newline=""), FIELDS[component.kind],
                               paths.title(inv.describe(component.path)))
    except (ValueError, csv.Error) as e:
        raise Invalid(str(e)) from None


def delivery(inv, order_id):
    """What the Receipts page shows of an order: {order, seller, ordered_on, notes, components}
    with each component's record fields plus "fields" and "rows" (a product has neither)."""
    order = record(inv, order_id)
    components = []
    for component in order.components:
        item = component.record()
        if component.kind == "product":
            item["fields"], item["rows"] = [], []
        else:
            item["fields"] = FIELDS[component.kind]
            item["rows"] = payload_rows(inv, component)
        components.append(item)
    return {"order": order_id, "seller": order.seller, "ordered_on": order.ordered_on, "notes": order.notes,
            "components": components}


# ------------------------------------------------------------------ edited rows

def _quantity(row):
    try:
        return int(row["quantity"])
    except (KeyError, TypeError, ValueError):
        raise Invalid(f"{row.get('name') or row.get('front') or 'A row'}: quantity must be a whole number") from None


def _edited(inv, component, rows, *, partial=False):
    """The rows a receipt gives a component, checked against its recorded ones (see the module
    docstring); cards sorted as collection.csv is."""
    fields = FIELDS[component.kind]
    previous = payload_rows(inv, component)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or set(row) != set(fields)
                                                     or any(not isinstance(v, str) for v in row.values())
                                                     for row in rows):
        raise Invalid("The received rows need exactly the component's CSV fields")
    if sum(_quantity(row) for row in rows) != sum(_quantity(row) for row in previous):
        if partial:
            raise Invalid("Keep the complete component's total quantity in rows; select arrived copies with take.")
        raise Invalid("Receive a whole component. Split partial arrivals into their own component first; "
                      "total quantities cannot change here.")
    if component.kind == "tokens":
        recorded = {row[side] for row in previous for side in ("front", "back")}
        return [_token_names({key: row[key] for key in fields}, recorded) for row in rows]

    def copies(items):
        found = Counter()
        for row in items:
            found[row["name"]] += _quantity(row)
        return found
    if copies(rows) != copies(previous):
        raise Invalid("Card names and total copies must match the recorded component")
    made = [{key: row[key] for key in fields} for row in rows]
    if partial:
        return made
    _check_printings(made)
    return sorted(made, key=rules.sort_key)


def _token_names(row, recorded):
    """A token row given at receipt, with the exact Scryfall name of each face it names that the
    order didn't (recorded: the order's face names, checked when it was recorded); a name that
    isn't one ("White Angel 4/4 flying": its traits go in back_details) is refused. Unchecked while
    the card index isn't ready, as order edit is."""
    if all(not row[side] or row[side] in recorded for side in ("front", "back")):
        return row
    from .orders import check_token_names
    try:
        return check_token_names([row])[0][0]
    except Invalid as e:
        raise Invalid(f"{e} Give only the token's name; its power/toughness, colour and abilities go in "
                      f"its details.") from None


def _check_printings(rows):
    """The existing edited-receipt printing checks, applied only to arrived partial rows."""
    from decklab.lib import cards
    for row in rows:
        card = cards.card(row["name"])
        printed = cards.printing_card(row["set"], row["collector_number"])
        printing = cards.printing(row["set"], row["collector_number"])
        if card is None or printed is None or printed["name"] != card["name"]:
            raise Invalid(f"{row['name']}: printing does not match the local Scryfall data; verify it or "
                          f"refresh the card cache")
        if row["finish"] not in (printing or {}).get("finishes", []):
            raise Invalid(f"{row['name']}: that finish is not available for the printing")


# ------------------------------------------------------------------ the operation

def _card_rows(where, data, existing=False, owners=None):
    """where's rows (an inventory source's path, named in its database words with each row by
    number, E11-S12; owners as for paths.describe) checked as merge_cards.read checks them."""
    try:
        return rules.parse_cards(io.StringIO(data.decode("utf-8-sig"), newline=""), paths.describe(where, owners),
                                 existing=existing, numbered=True)
    except (rules.InvalidCards, csv.Error, UnicodeDecodeError) as e:
        raise Invalid(str(e)) from None


def _token_rows(inv, component):
    """The tokens component's rows, each passing the incoming rules; a refusal names the row by
    its number in the order's token cards ("Row 2 of order x's token cards", E11-S12)."""
    rows = payload_rows(inv, component)
    owners = paths.payload_owners(inv.orders)
    for number, row in enumerate(rows, 1):
        try:
            rules.validate_token_row(row, paths.row_of(component.path, number, owners), incoming=True)
        except ValueError as e:
            raise Invalid(str(e)) from None
    return rows


@register(KIND, refresh=True)
def receive(inv, *, order, components, received_on, wording="web"):
    """The receipt (see the module docstring): inv -> (inv after, Summary). Summary.extra
    ["totals"] is [[what, counts], ...] for the playable cards and the physical tokens merged
    ({cards, added_rows, bumped_rows[, skipped_basics]})."""
    before = inv
    try:
        rules.valid_date(received_on if isinstance(received_on, str) else "")
    except ValueError as e:
        raise Invalid(str(e)) from None
    the_order, chosen = selected(inv, order, components)
    if the_order.ordered_on and received_on < the_order.ordered_on:
        raise Invalid("Receipt date cannot be before the order date")
    found = blockers(inv, Op(KIND, {"order": order, "components": components, "wording": wording}))
    if found:
        raise Invalid("Complete these first: " + "; ".join(found))
    by_id = {item["id"]: item for item in components}

    assignments, arrived, arrived_inputs = [], [], {}
    for component in chosen:
        given = by_id[component.id]
        if component.kind == "product":
            if given.get("rows") is not None:
                raise Invalid("Product reference lists cannot be edited during receipt")
            if "take" in given:
                raise Invalid("Products must be received whole; select their component instead of individual rows.")
            product = inv.product(component.product_stem)
            quantity = sum(_quantity(row.as_dict()) for row in product.items)
        else:
            previous = payload_rows(inv, component)
            rows = (_edited(inv, component, given["rows"], partial="take" in given)
                    if given.get("rows") is not None else previous)
            if given.get("rows") is not None:
                from . import order_fulfilment
                inv = inv.set_component_rows(order, component.id, rows)
                inv = inv.with_order(order_fulfilment.edit(inv.order(order), component.id, previous, rows))
            quantity = sum(_quantity(row) for row in rows)
            if "take" in given:
                from .receive_partial import prepare
                inv, actual, assignment = prepare(inv, order, component.id, rows, given["take"])
                assignments.append(assignment)
                arrived.append(actual)
                arrived_inputs[actual.id] = given
                continue
        assignments.append({"source": component.id, "received": component.id, "pending": None,
                            "received_quantity": quantity, "pending_quantity": 0})
        arrived.append(component)
        arrived_inputs[component.id] = given
    chosen, by_id = arrived, arrived_inputs

    card_inputs, token_inputs, moved, statuses = [], [], {}, None
    for component in chosen:
        if component.kind == "cards":
            rows = _card_rows(component.path, files.render_sheet(inv.payloads[component.path]),
                              owners=paths.payload_owners(inv.orders))
            if "take" in by_id[component.id]:
                _check_printings(rows)
            card_inputs.append((component.path, rows))
        elif component.kind == "tokens":
            token_inputs.extend(_token_rows(inv, component))
        else:
            product = inv.product(component.product_stem)
            if product.error is not None:
                raise Invalid(f"{paths.title(inv.describe(component.path))}: {product.error}")
            card_inputs.append((component.path, _card_rows(component.path, files.render_product(product))))
            if statuses is None:
                if not inv.status.exists:
                    raise Invalid("The products' status list is missing")
                if inv.status.error is not None:
                    raise Invalid(f"The products' status list can't be read: {inv.status.error}")
                try:
                    statuses = rules.parse_status(files.render_sheet(inv.status).decode("utf-8"),
                                                  "The products' status list")
                except (ValueError, csv.Error) as e:
                    raise Invalid(str(e)) from None
            matches = [row for row in statuses if row["file"] == component.file_name]
            if len(matches) != 1 or matches[0]["status"] not in INCOMING:
                raise Invalid(f"{component.id}: product status must be ordered or preordered")
            matches[0]["status"] = "owned"
            rules.set_intact(matches[0], by_id[component.id]["intact"])
            matches[0]["notes"] = "; ".join(filter(None, (matches[0]["notes"], f"Received {received_on}")))
        if component.kind != "product":
            archive = paths.payload(component.kind, "received", component.file_name)
            if archive in inv.payloads:     # named by what holds it, never its old file (E11-S12)
                raise Invalid(f"{paths.title(paths.component_words(order, component.id, component.kind))} can't be "
                              f"received: {inv.describe(archive)} are already kept under the same name")
            moved[component.path] = archive
        inv = inv.move_component(order, component.id, "received", received_on)
        if component.checks and component.kind != "product":
            # Keep evidence of what was checked without leaving it actionable.
            inv = inv.update_component(order, component.id, verified_checks=component.checks, checks=[], check_links=None)

    for other in inv.orders:
        if other.file != the_order.file and any(c.path in moved for c in other.components):
            # Sharing component files would make the next receipt ambiguous.
            raise Invalid(f"Another order names these contents too ({paths.describe(other.path)})")

    totals = []
    if card_inputs:
        sheet = inv.collection(paths.HOME)
        existing = _card_rows(sheet.path, files.render_sheet(sheet), existing=True) if sheet.exists else []
        try:
            rows, counts = rules.merge_rows(existing, card_inputs)
        except rules.InvalidCards as e:
            raise Invalid(str(e)) from None
        inv = inv.with_collection(paths.HOME, rows)
        totals.append(["playable cards", counts])
    if token_inputs:
        sheet = inv.token_set(paths.HOME)
        existing = [dict(row.as_dict(), _id=row.id) for row in sheet.rows]
        rows, counts = rules.merge_tokens(existing, token_inputs)
        inv = inv.with_tokens(paths.HOME, [TokenRow.make(row, id=row.get("_id") or 0) for row in rows])
        totals.append(["physical tokens", counts])
    if statuses is not None:
        inv = inv.with_status_rows(statuses)
    from .receive_partial import acknowledge_remainders
    inv, extra_copies = acknowledge_remainders(before, inv, order, assignments)
    ids = [component.id for component in chosen]
    text = f"Received order {order} ({', '.join(ids)}) on {received_on}"
    if extra_copies:
        text += f"; pending extra copies confirmed: {', '.join(extra_copies)}"
    return inv, Summary(text,
                        {"components": len(ids)}, extra={"totals": totals, "components": ids, "moved": moved,
                                                        "assignments": assignments})
