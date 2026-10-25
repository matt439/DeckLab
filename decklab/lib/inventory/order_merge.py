"""Orders that came in one shipment combined into one record, registered by inventory.orders.

A shop can merge separate orders into one parcel (combined postage), and the cards then arrive
mixed together. order.merge moves every component of the other orders into the order they're
merged into, so the delivery is received once on one page. Nothing about the cards changes: each
component keeps its status, checks and payload (its file name too), and only its id changes when
asked (a second `cards`, say, as `additions`). The fulfilment ledgers are combined with the
components' new ids, so cancelling or removing a merged component still restores what it fulfilled;
an extra-copies acknowledgement follows its component; anything else in a merged order's
audit_notes is kept after a sentence naming that order. The deck tables aren't refreshed: their
"on the way (order ...)" labels name a payload's file, which a merge keeps (as a split part's label
names its own file).
"""
from decklab.lib.state import Invalid

from . import Summary, register, rules
from .model import Order
from .orders import _component_id, _done, _order, _plural, _record_fields


def _prose(notes):
    """audit_notes without its fulfilment ledger and extra-copies acknowledgement: the words a
    person wrote (a cancellation's reason, an import note), or ""."""
    from .order_fulfilment import audit_span
    if not isinstance(notes, str):
        return ""
    span = audit_span(notes)
    if span is not None:
        notes = (notes[:span[0]] + notes[span[1]:]).strip()
    return (rules.with_extra_copies(notes, []) or "").strip()


@register("order.merge")
def merge_orders(inv, *, order, others, renames=(), notes=None, repo="."):
    """Every component of each order in others moved into order, in the order given, then those
    orders' records removed, in one change. renames: [{order, component, id}] giving a moved
    component a new id (needed when its id is taken; a product's component keeps its stem). The
    orders must have the same seller and no received component (a receipt's date is checked
    against its own order's date). sources are combined; notes are joined unless notes replaces
    them. Refused when some orders have fulfilment history and others don't, since a merged record
    can't say which parts are unknown."""
    from . import order_fulfilment
    before = inv
    target = _order(inv, order)
    if not isinstance(others, (list, tuple)) or not others:
        raise Invalid("Name the orders to merge into this one")
    if len(set(others)) != len(others) or order in others:
        raise Invalid("Name each order to merge once, and not the order they're merged into")
    merged = [_order(inv, oid) for oid in others]
    everything = [target, *merged]
    for o in everything:
        if (o.seller or "").strip() != (target.seller or "").strip():
            raise Invalid(f"Order {o.id} is from {o.seller or 'an unknown seller'!r}, not {target.seller!r}; "
                          "only one seller's orders can share a shipment")
        if any(c.status == "received" or c.received_on for c in o.components):
            raise Invalid(f"Order {o.id} has a received component; merge orders before receiving them")
    ledgers = [order_fulfilment.read(o) for o in everything]
    if len({ledger is None for ledger in ledgers}) > 1:
        raise Invalid("Some of these orders have recorded fulfilment history and some don't; "
                      "they can't be combined without losing which is which")
    wanted = {}
    for item in renames or ():
        key = (item.get("order"), item.get("component")) if isinstance(item, dict) else None
        if key is None or key[0] not in others or key in wanted:
            raise Invalid(f"A rename must name a component of an order being merged, once: {item!r}")
        wanted[key] = item.get("id")
    record = target.record()
    taken = {c.id for c in target.components}
    sentences, extra = [], list(rules.extra_copies(target.audit_notes))
    ledger = ledgers[0]
    for o, theirs in zip(merged, ledgers[1:]):
        ids = {}
        for c in o.components:
            new_id = wanted.pop((o.id, c.id), c.id)
            if c.kind == "product" and new_id != c.id:
                raise Invalid(f"{c.id} is a product's component; it keeps its product's name")
            if new_id in taken:
                raise Invalid(f"Order {order} already has a component {new_id!r}; give order {o.id}'s "
                              f"{c.id} a new id (--rename {o.id}:{c.id}=NEW)")
            ids[c.id] = _component_id(new_id, taken, f"{order}.json")
            item = c.record()
            item["id"] = ids[c.id]
            record["components"].append(item)
        extra += [ids[cid] for cid in rules.extra_copies(o.audit_notes) if cid in ids]
        if theirs is not None:
            for claim in theirs["claims"]:
                ledger["claims"].append({**claim, "component": ids[claim["component"]]})
            ledger["consumed"] += [ids[cid] for cid in theirs["consumed"]]
            ledger["warnings"] += theirs["warnings"]
        renamed = [f"{old} as {new}" for old, new in ids.items() if old != new]
        said = (f"Merged in order {o.id} (ordered {o.ordered_on or 'on an unknown date'})"
                + (f", its {', '.join(renamed)}" if renamed else "") + ".")
        prose = _prose(o.audit_notes)
        sentences.append(said + (f" Its audit notes: {prose}" if prose else ""))
        record["sources"] = list(dict.fromkeys([*record.get("sources", []), *(o.sources or [])]))
    if wanted:
        (oid, cid), _ = next(iter(wanted.items()))
        raise Invalid(f"Order {oid} has no component {cid!r}")
    if notes is None:
        notes = " ".join(dict.fromkeys(n.strip() for n in (o.notes or "" for o in everything) if n.strip()))
    record["notes"] = notes
    record.update(_record_fields(record, repo, inv))
    text = " ".join(part for part in (record.get("audit_notes") or "", *sentences) if part)
    text = rules.with_extra_copies(text, extra) if extra else text
    if text:
        record["audit_notes"] = text
    else:
        record.pop("audit_notes", None)
    made = Order(target.file, record)
    if ledger is not None:
        made = order_fulfilment.write(made, ledger)
    for o in merged:
        inv = inv.without_order(o.id)
    inv = inv.with_order(made)
    moved = sum(len(o.components) for o in merged)
    return _done(before, inv, Summary(f"Merged {_plural(len(merged), 'order')} ({', '.join(others)}) into order "
                                      f"{order}: {_plural(moved, 'component')} moved",
                                      {"orders": len(merged), "components": moved}))
