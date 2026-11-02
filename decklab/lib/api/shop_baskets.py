"""Shopping's Baskets (E5-S27, first slice): a proposed basket a shop from the daily snapshots.

Read only, from the same capture shop_prices.enrich used (lib/shops' files, never a shop):
for each snapshot shop (lib/shops.SNAPSHOT_ADAPTERS, in that order),

  - "rows": the ready queue rows the snapshot found in stock there, each with the listing it
    found (price in AUD as the shop gave it, None when it showed none) and its fetch time;
  - "add_ons": the long-term and waiting rows in stock there, marked as add-ons (no postage
    rules yet, so they are only "in stock here", never "over the free-postage threshold");
  - "total_aud" over the priced rows only, with "unpriced" counting the rest;
  - "unconfirmed": exact-printing rows whose printing the snapshot couldn't confirm there,
    "unknown": rows whose page couldn't be read, "not_checked": rows the run didn't reach,
    none of them claiming stock.

A shop without a readable snapshot is listed with read False and no rows. "unavailable" are the
ready rows no read shop has in stock, with each shop's reason. Nothing here changes the queue,
records an order or stores a price paid; Shopping's guard (home's records) already ran.

An exact row counts only a listing of its printing (set, collector number and finish, nonfoil
when blank); when the snapshot has in-stock listings it can't tell the printing of, or the row
names no printing, the printing is unconfirmed. Any other row takes lib/shops.pick's choice: the
cheapest in-stock nonfoil, else the cheapest in-stock listing.
"""
from decimal import Decimal, InvalidOperation

from decklab.lib import shops

from . import shop_prices

READY = "ready"
ADD_ON_STATES = ("long_term", "waiting_for_stock", "waiting_for_reprint")
ROW_FIELDS = ("queue_row", "name", "quantity", "state", "for", "printing", "set", "collector_number", "finish")


def _price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return price if price.is_finite() and price >= 0 else None


def _quantity(row):
    try:
        quantity = int(str(row.get("quantity") or "").strip())
    except ValueError:
        return 0
    return max(quantity, 0)


def _money(value):
    return f"{value.quantize(Decimal('0.01'))}"


def _printing_unknown(listing):
    return not str(listing.get("set") or "").strip() or not str(listing.get("number") or "").strip()


def _unconfirmed(row, entry):
    """True when an exact row's printing can't be confirmed from this shop's entry."""
    if row.get("printing") != "exact":
        return False
    if not row.get("set") or not row.get("collector_number"):
        return True
    if not isinstance(entry, dict) or entry.get("status") == "error":
        return False
    listings = [item for item in entry.get("listings") or () if isinstance(item, dict)]
    _, stocked = shops.pick(row, listings)
    if stocked:
        return False
    return any(_printing_unknown(item) and (item.get("stock") or 0) > 0 for item in listings)


def line(row, adapter, data):
    """One queue row at one shop: its status and, in stock, the listing and what it costs."""
    shown = {key: row.get(key) for key in ROW_FIELDS}
    shown["is_token"] = bool(row.get("is_token"))
    if not data:
        shown.update(status="unread", fetched_at=None)
        return shown
    entry = shops._by_name(data.get("cards"), str(row.get("name") or ""))
    if _unconfirmed(row, entry):
        shown.update(status="unconfirmed", fetched_at=(entry or {}).get("at") or data.get("fetched_at"))
        return shown
    matched = shops.match(row, data)
    shown.update(status=matched["status"], fetched_at=matched["fetched_at"], carried=matched["carried"])
    if matched["status"] != "in_stock":
        return shown
    quantity = _quantity(row)
    stock = matched.get("stock") or 0
    copies = min(quantity, stock) if adapter.counts_stock else quantity
    price = _price(matched.get("price_aud"))
    shown.update(listing={"set": matched["set"], "collector_number": matched["collector_number"],
                          "finish": matched["finish"], "price_aud": matched["price_aud"] if price is not None else None,
                          "stock": stock if adapter.counts_stock else None, "url": matched["url"]},
                 copies=copies, short=adapter.counts_stock and stock < quantity,
                 line_aud=_money(price * copies) if price is not None else None)
    return shown


def _totals(lines):
    priced = [Decimal(item["line_aud"]) for item in lines if item.get("line_aud") is not None]
    return {"total_aud": _money(sum(priced, Decimal(0))) if priced else None,
            "priced": len(priced), "unpriced": len(lines) - len(priced),
            "cards": sum(item.get("copies") or 0 for item in lines)}


def basket(adapter, data, rows):
    """One shop's basket over the queue rows (ready and add-on states only)."""
    summary = shops.summary(data) if data else None
    shown = {"key": adapter.key, "shop": adapter.name, "site": adapter.site, "read": bool(data),
             "counts_stock": adapter.counts_stock,
             "fetched_at": summary["fetched_at"] if summary else None,
             "started_at": summary["started_at"] if summary else None,
             "rows": [], "add_ons": [], "unconfirmed": [], "unknown": [], "not_checked": []}
    if not data:
        shown.update(_totals([]))
        shown["add_ons_totals"] = _totals([])
        return shown
    for row in rows:
        state = row.get("state")
        if state != READY and state not in ADD_ON_STATES:
            continue
        item = line(row, adapter, data)
        add_on = state != READY
        item["add_on"] = add_on
        if item["status"] == "in_stock":
            shown["add_ons" if add_on else "rows"].append(item)
        elif not add_on and item["status"] in ("unconfirmed", "unknown", "not_checked"):
            shown[item["status"]].append(item)
    shown.update(_totals(shown["rows"]))
    shown["add_ons_totals"] = _totals(shown["add_ons"])
    return shown


def build(rows, captured, revision=None):
    """{"queue_revision", "shops": [basket, ...], "unavailable": [...]}, or None with no snapshot at all."""
    found = shop_prices.by_shop(captured)
    if not found:
        return None
    rows = [row for row in rows or () if isinstance(row, dict)]
    baskets = [basket(adapter, found.get(adapter.key), rows) for adapter in shops.SNAPSHOT_ADAPTERS]
    unavailable = []
    for row in rows:
        if row.get("state") != READY:
            continue
        at = [line(row, adapter, found.get(adapter.key)) for adapter in shops.SNAPSHOT_ADAPTERS]
        if any(item["status"] == "in_stock" for item in at):
            continue
        shown = {key: row.get(key) for key in ROW_FIELDS}
        shown["is_token"] = bool(row.get("is_token"))
        shown["shops"] = [{"shop": adapter.name, "status": item["status"], "fetched_at": item.get("fetched_at")}
                          for adapter, item in zip(shops.SNAPSHOT_ADAPTERS, at)]
        unavailable.append(shown)
    return {"queue_revision": revision, "shops": baskets, "unavailable": unavailable}


def enrich(answer, *, data):
    """answer["baskets"] from the captured snapshots, only while some shop has one."""
    try:
        built = build(answer.get("to_buy", []), data, answer.get("queue_revision"))
    except Exception as error:  # optional evidence: Shopping still answers without it
        from . import common
        common._log(f"Shop baskets could not be worked out: {type(error).__name__}")
        return answer
    if built is not None:
        answer["baskets"] = built
    return answer
