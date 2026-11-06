"""Pure layout proofs for edited token-card rows restored in ordinary sorted order.

Stored position numbers are implementation details. Undo predicts the normal writer's
positions and exact UPDATEs; it does not promise to recover historical position numbers.
"""
from . import rules

INVALID = "The token-card order could not be confirmed."


def _stock(stock):
    if not isinstance(stock, list):
        raise ValueError(INVALID)
    found = {}
    for item in stock:
        if not isinstance(item, dict) or set(item) != {"id", "row"}:
            raise ValueError(INVALID)
        rid, row = item["id"], item["row"]
        if type(rid) is not int or not 1 <= rid < 10 ** 18 or rid in found \
                or not isinstance(row, dict) or set(row) != set(rules.TOKEN_FIELDS) \
                or type(row["quantity"]) is not int or not 1 <= row["quantity"] <= 9999 \
                or any(not isinstance(value, str) for key, value in row.items() if key != "quantity"):
            raise ValueError(INVALID)
        found[rid] = dict(row)
    return found


def _positions(layout, ids):
    if not isinstance(layout, list) or len(layout) != len(ids):
        raise ValueError(INVALID)
    found, previous = {}, -1
    for item, rid in zip(layout, ids):
        if not isinstance(item, dict) or set(item) != {"id", "position"} \
                or type(item["id"]) is not int or item["id"] != rid \
                or type(item["position"]) is not int or not previous < item["position"] < 2 ** 31:
            raise ValueError(INVALID)
        previous = found[rid] = item["position"]
    return found


def _predicted(ids, positions):
    from .pg import _positions as ordinary_positions
    made = [{"id": rid, "position": position}
            for rid, position in zip(ids, ordinary_positions(ids, positions))]
    _positions(made, ids)
    return made


def _image(row, rid, position, space):
    return {"set_code" if key == "set" else key: value for key, value in row.items()} | \
        {"id": rid, "position": position, "space_id": space}


def historical(items, stock, layout):
    """Validate the reconstructed sorted source-before stock and the ordinary forward layout.

    Every audited item, including position-only survivors, contributes its historical facts
    and position. Return the historical stock/layout without changing any input.
    """
    try:
        current = _stock(stock)
        positions = _positions(layout, list(current))
        old, before_positions, seen = dict(current), dict(positions), set()
        for item in items:
            rid = item["token_row_id"]
            if type(rid) is not int or rid not in current or rid in seen:
                raise ValueError(INVALID)
            seen.add(rid)
            source, restored = item["current_db"], item["restore_db"]
            space = source["space_id"]
            if item["current"] != current[rid] \
                    or source != _image(current[rid], rid, positions[rid], space) \
                    or restored != _image(item["restore"], rid, restored["position"], space):
                raise ValueError(INVALID)
            old[rid], before_positions[rid] = dict(item["restore"]), restored["position"]
        if any(type(position) is not int or not 0 <= position < 2 ** 31
               for position in before_positions.values()) or len(set(before_positions.values())) != len(old):
            raise ValueError(INVALID)
        ids = sorted(old, key=before_positions.get)
        historical_stock = [{"id": rid, "row": old[rid]} for rid in ids]
        _stock(historical_stock)
        if sorted(ids, key=lambda rid: rules.token_sort_key(old[rid])) != ids \
                or _predicted(list(current), before_positions) != layout:
            raise ValueError(INVALID)
        return historical_stock, [{"id": rid, "position": before_positions[rid]} for rid in ids]
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise ValueError(INVALID) from None


def expected(stock, layout, restored, space):
    """Return exactly the normal writer's UPDATE images and resulting persisted layout."""
    try:
        current, after = _stock(stock), _stock(restored)
        positions = _positions(layout, list(current))
        if set(current) != set(after) \
                or sorted(after, key=lambda rid: rules.token_sort_key(after[rid])) != list(after):
            raise ValueError(INVALID)
        predicted = _predicted(list(after), positions)
        audit = []
        for item in predicted:
            rid = item["id"]
            before = _image(current[rid], rid, positions[rid], space)
            saved = _image(after[rid], rid, item["position"], space)
            if before != saved:
                audit.append({"table": "token_card", "op": "UPDATE", "key": {"id": rid},
                              "before": before, "after": saved})
        return audit, predicted
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        raise ValueError(INVALID) from None
