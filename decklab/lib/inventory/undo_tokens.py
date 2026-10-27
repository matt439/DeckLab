"""Prove an unused audited token insertion can be removed without reallocating cards.

All token identities are stable database ids. Packing is read as recorded; this
module never plans needs, chooses pairings or makes a missing record mean zero.
"""
from decklab.lib import decks, inventory, tokens
from decklab.lib.tokens import products

from . import changes, files, rules
from .model import refuse_unreadable_tokens


def ordered_rows(sheet):
    """Explicit identities and values: Row equality deliberately omits its id."""
    refuse_unreadable_tokens(sheet)
    if sheet.error is not None or sheet.strict_error is not None or sheet.csv_error is not None \
            or sheet.problems or not sheet.exists and sheet.rows:
        raise ValueError("Unreadable token stock")
    found, ids = [], set()
    for row in sheet.rows:
        if type(row.id) is not int or not 1 <= row.id < 10 ** 18 or row.id in ids:
            raise ValueError("Ambiguous token identity")
        ids.add(row.id)
        values = row.as_dict()
        cleaned = rules.token_page_row(values)
        if set(values) != set(rules.TOKEN_FIELDS) or cleaned != values:
            raise ValueError("Unsupported token stock")
        found.append({"id": row.id, "row": {**values, "quantity": int(values["quantity"])}})
    return found


def _layout(snapshot, space, source, stock):
    from . import backend
    reader = getattr(backend(), "undo_token_positions", None)
    layout = reader(space) if callable(reader) else None
    if not isinstance(layout, list) or len(layout) != len(stock):
        raise ValueError("Token positions cannot be checked")
    previous = -1
    for item, row in zip(layout, stock):
        if not isinstance(item, dict) or set(item) != {"id", "position"} or item["id"] != row["id"] \
                or type(item["id"]) is not int or type(item["position"]) is not int or item["position"] <= previous:
            raise ValueError("Ambiguous token positions")
        previous = item["position"]
    target = next((row for row in layout if row["id"] == source["after"]["id"]), None)
    if target is None or target["position"] != source["after"]["position"]:
        raise ValueError("The token row moved")
    sheet = snapshot.token_set(space)
    sorted_ids = [row.id for row in sorted(sheet.rows, key=rules.token_sort_key)]
    if not sheet.sorted or sorted_ids != [row["id"] for row in stock]:
        raise ValueError("Removing the row would reorder stock")
    return layout


def _packing(snapshot, space, stock):
    from .undo import _home_products, _known_decks
    expected = set()
    with inventory.pinned(snapshot):
        for deck in _known_decks(snapshot, space):
            if deck.status == "built":
                if not decks.has_token_cards(deck):
                    raise ValueError("Unknown deck packing")
                decks.token_cards(deck)  # Includes duplicate-header and syntax refusals.
                expected.add(deck.deck_id)
        intact = _home_products(snapshot, space)
        warnings = []
        if space == "home":
            records = products.records(warnings, snapshot)
            if set(records) != {f"product/{stem}" for stem in intact}:
                raise ValueError("Unknown product packing")
            for holder, record in records.items():
                product = record.get("product")
                if not record.get("written") or record.get("error") or product is None \
                        or product.error is not None or product.strict_error is not None or product.csv_error is not None:
                    raise ValueError("Unknown product packing")
                expected.add(holder)
        read = tokens.read(strict=True, space=space)
        if read.problems or len(read.rows) != len(stock) or any(
                {**row, "quantity": int(row["quantity"])} != saved["row"] for row, saved in zip(read.rows, stock)):
            raise ValueError("Token rows and positions disagree")
        holds = tokens.reserve.holds(read, space=space, warnings=warnings)
    if warnings or not isinstance(holds, dict) or set(holds) != expected:
        raise ValueError("Incomplete physical participants")
    allocation, totals = {}, {row["id"]: 0 for row in stock}
    quantities = {row["id"]: row["row"]["quantity"] for row in stock}
    for holder, record in holds.items():
        if not isinstance(record, dict) or record.get("error") or not isinstance(record.get("unmatched"), list) \
                or record["unmatched"] or not isinstance(record.get("rows"), dict):
            raise ValueError("Unknown packed token cards")
        by_id = {}
        for index, quantity in record["rows"].items():
            if type(index) is not int or not 0 <= index < len(stock) or type(quantity) is not int or quantity <= 0:
                raise ValueError("Invalid physical allocation")
            rid = stock[index]["id"]
            by_id[rid] = quantity
            totals[rid] += quantity
        allocation[holder] = by_id
    if any(total > quantities[rid] for rid, total in totals.items()):
        raise ValueError("Packed token cards exceed stock")
    return allocation, {rid: quantity - totals[rid] for rid, quantity in quantities.items()}, totals


def remove(snapshot, source, wanted, space, label):
    """Run the ordinary removal and prove its settled physical and identity effects."""
    from .undo import UndoConflict
    try:
        sheet = snapshot.token_set(space)
        stock = ordered_rows(sheet)
        target = source["after"]["id"]
        _layout(snapshot, space, source, stock)
        identity = rules.token_identity(wanted)
        if sum(rules.token_identity(row["row"]) == identity for row in stock) != 1:
            raise ValueError("Ambiguous physical token identity")
        allocations, capacities, held = _packing(snapshot, space, stock)
        if held.get(target) != 0:
            raise ValueError("The inserted card is packed")
        after, summary = tokens.ops.remove(snapshot, space=space, base={**wanted, "quantity": str(wanted["quantity"])},
                                          sha256=files.rendered_sha256(sheet))
        settled = changes.prepare(snapshot, after)
        remaining = ordered_rows(settled.token_set(space))
        expected = [row for row in stock if row["id"] != target]
        if remaining != expected or settled != snapshot.replace(tokens=settled.tokens):
            raise ValueError("Unexpected token removal effect")
        expected_spaces = set(snapshot.tokens) - ({space} if not expected else set())
        if set(settled.tokens) != expected_spaces:
            raise ValueError("Unexpected token source change")
        for owner in snapshot.tokens:
            if owner != space:
                old, new = snapshot.token_set(owner), settled.token_set(owner)
                if old != new or [(row.id, row.as_dict()) for row in old.rows] != [(row.id, row.as_dict()) for row in new.rows]:
                    raise ValueError("Other token stock changed")
        new_allocations, new_capacities, _ = _packing(settled, space, remaining)
        if new_allocations != allocations or new_capacities != {rid: free for rid, free in capacities.items() if rid != target}:
            raise ValueError("Packed cards would move between physical rows")
        cards = sum(row["row"]["quantity"] for row in stock) - wanted["quantity"]
        counts, extra = summary.counts or {}, summary.extra or {}
        if cards != sum(row["row"]["quantity"] for row in remaining) or type(counts.get("cards")) is not int \
                or counts["cards"] != cards or extra.get("index") is not None or extra.get("resorted") is not False:
            raise ValueError("Unexpected physical total or ordering")
        return settled, summary
    except inventory.Unavailable:
        raise
    except Exception:
        raise UndoConflict("The added token row cannot safely be removed here. Check its physical pairing and packed cards in Tokens.", label) from None
