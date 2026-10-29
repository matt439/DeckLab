"""Several purchase queue rows added as one change, registered by inventory.orders (E5-S25).

watchlist.add_many takes rows as watchlist.set's add takes one: each a dict of the columns it
sets, checked as read_queue checks a row. A row whose identity (orders.queue_key: name,
printing, set, number, finish and for) is already queued raises that row's quantity instead of
adding a second one, keeping its state and every other detail, so the result never holds a
duplicate purchase request. Nothing else in the inventory changes and no deck table refreshes:
queued copies are intent, never on the way.
"""
from decklab.lib.state import Invalid

from . import Summary, register
from .model import QUEUE_FIELDS
from .orders import _done, _no_duplicates, _plural, _queue_dicts, _with_queue, queue_key, queue_row

MAX_ROWS = 500


@register("watchlist.add_many")
def add_queue_rows(inv, *, rows, repo="."):
    before = inv
    if not isinstance(rows, (list, tuple)) or not rows or len(rows) > MAX_ROWS:
        raise Invalid(f"Give 1 to {MAX_ROWS} watchlist rows to add")
    current = _queue_dicts(inv)
    for i, row in enumerate(current):
        row["_row"] = inv.watchlist.rows[i]
    by_key = {queue_key(row): row for row in current}
    added = raised = copies = 0
    for values in rows:
        if not isinstance(values, dict) or not values or not set(values) <= set(QUEUE_FIELDS):
            raise Invalid(f"Set one or more of the watchlist's columns: {', '.join(QUEUE_FIELDS)}")
        new = {k: "" for k in QUEUE_FIELDS}
        new.update({"printing": "any", "quantity": "1"})
        new.update(values)
        row = queue_row(new, repo, inv)
        copies += int(row["quantity"])
        same = by_key.get(queue_key(row))
        if same is None:
            current.append(row)
            by_key[queue_key(row)] = row
            added += 1
            continue
        merged = queue_row({**{k: same[k] for k in QUEUE_FIELDS},
                            "quantity": str(int(same["quantity"]) + int(row["quantity"]))}, repo, inv)
        source = same.pop("_row", None)
        same.clear()
        same.update(merged)
        if source is not None:
            same["_row"] = source
        raised += 1
    _no_duplicates(current)
    text = f"Added {copies} {'copy' if copies == 1 else 'copies'} to the watchlist: {_plural(added, 'new row')}"
    if raised:
        text += f", {_plural(raised, 'row')} raised"
    return _done(before, _with_queue(inv, current), Summary(text, {"rows": len(current)}))
