"""Shopping's Baskets (E5-S27, first slice): a proposed basket a shop from the daily snapshots.

Read only, from the same capture shop_prices.enrich used (lib/shops' files, never a shop):
for each snapshot shop config.json checks (lib/shops.enabled_adapters(), in that order),

  - "rows": the ready queue rows the snapshot found in stock there, each with the listing it
    found (price in AUD as the shop gave it, None when it showed none) and its fetch time;
  - "add_ons": the long-term and waiting rows in stock there, marked as add-ons, those that reach
    the shop's free-postage threshold at the smallest total marked "lifts" ("reach");
  - "postage": the basket's postage from the shop's rules (shop_plan.postage, E5-S27's second
    slice: a flat postage and a free-postage threshold, Settings; unknown when not set);
  - "total_aud" over the priced rows only, with "unpriced" counting the rest;
  - "unconfirmed": exact-printing rows whose printing the snapshot couldn't confirm there,
    "unknown": rows whose page couldn't be read, "not_checked": rows the run didn't reach,
    none of them claiming stock.

Every line carries "partial" (E5-S33): the shop's page was only part of its results (Games Portal's
first page of a search with more), so the page says "first page only, more results not read" beside
it, and a basket's "partial" counts its lines read that way. A token or reminder row's status is
"token" at every shop (never looked up, so no stock is claimed), and an exact row the shop lists only
in other printings is "not_matched" with the shop's "shop_sets".

A shop without a readable snapshot is listed with read False and no rows. "unavailable" are the
ready rows no read shop has in stock, with each shop's reason, and "plan" the fewest-shops plan
(shop_plan.plan: every combination of read shops, weighed by cards and postage). Nothing here changes the queue,
records an order or stores a price paid; Shopping's guard (home's records) already ran.

An exact row counts only a listing of its printing (set, collector number and finish, nonfoil
when blank); when the snapshot has in-stock listings it can't tell the printing of, or the row
names no printing, the printing is unconfirmed. Any other row takes lib/shops.pick's choice: the
cheapest in-stock nonfoil, else the cheapest in-stock listing; at a shop that counts its stock,
when that listing has too few copies, the next cheapest in-stock listings of the same scope (nonfoil
when the choice is) fill the rest ("more", each with the copies taken), and "line_aud" adds them up
(None when one of them shows no price). "short" says the whole scope still has too few.
"""
from decimal import Decimal, InvalidOperation

from decklab.lib import shops

from . import shop_plan, shop_prices

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


def _unconfirmed(row, entry, preference=shops._UNSET_PREFERENCE):
    """True when an exact row's printing can't be confirmed from this shop's entry."""
    if row.get("printing") != "exact":
        return False
    if not row.get("set") or not row.get("collector_number"):
        return True
    if not isinstance(entry, dict) or entry.get("status") == "error":
        return False
    listings = [item for item in entry.get("listings") or () if isinstance(item, dict)]
    _, stocked = shops.pick(row, listings, preference)
    if stocked:
        return False
    return any(_printing_unknown(item) and (item.get("stock") or 0) > 0 for item in listings)


def line(row, adapter, data, preference=shops._UNSET_PREFERENCE):
    """One queue row at one shop: its status and, in stock, the listing and what it costs."""
    shown = {key: row.get(key) for key in ROW_FIELDS}
    shown["is_token"] = bool(row.get("is_token"))
    if not data:
        shown.update(status="unread", fetched_at=None)
        return shown
    if shown["is_token"]:
        shown.update(status="token", fetched_at=None)
        return shown
    preference = shops.listing_preference() if preference is shops._UNSET_PREFERENCE else preference
    entry = shops._by_name(data.get("cards"), str(row.get("name") or ""))
    if _unconfirmed(row, entry, preference):
        shown.update(status="unconfirmed", fetched_at=(entry or {}).get("at") or data.get("fetched_at"),
                     partial=bool((entry or {}).get("partial")))
        return shown
    matched = shops.match(row, data, preference)
    shown.update(status=matched["status"], fetched_at=matched["fetched_at"], carried=matched["carried"],
                 partial=bool(matched.get("partial")), shop_sets=list(matched.get("shop_sets") or ()))
    for key in ("condition", "language", "skipped_cheaper", "listing_preferences"):
        if key in matched:
            shown[key] = matched[key]
    if matched["status"] != "in_stock":
        return shown
    quantity = _quantity(row)
    stock = matched.get("stock") or 0
    price = _price(matched.get("price_aud"))
    first = {"set": matched["set"], "collector_number": matched["collector_number"], "finish": matched["finish"],
             "price_aud": matched["price_aud"] if price is not None else None,
             "stock": stock if adapter.counts_stock else None, "url": matched["url"],
             "condition": matched.get("condition"), "language": matched.get("language")}
    if not adapter.counts_stock:
        shown.update(listing=first, more=[], stock=None, copies=quantity, short=False,
                     line_aud=_money(price * quantity) if price is not None else None)
        return shown
    used = [(first, price, min(quantity, stock))]
    left = quantity - used[0][2]
    for extra in _more_listings(row, entry, matched, preference) if left > 0 else ():
        take = min(left, extra.get("stock") or 0)
        extra_price = _price(extra.get("price"))
        used.append(({"set": extra.get("set"), "collector_number": extra.get("number"), "finish": extra.get("finish"),
                      "price_aud": extra.get("price") if extra_price is not None else None,
                      "stock": extra.get("stock") or 0, "url": extra.get("url"),
                      **shops.listing_preferences.words(extra)}, extra_price, take))
        left -= take
        if left <= 0:
            break
    copies = sum(taken for _, _, taken in used)
    for listing, _, taken in used:
        listing["copies"] = taken
    priced = all(each is not None for _, each, _ in used)
    shown.update(listing=first, more=[listing for listing, _, _ in used[1:]],
                 stock=sum(listing["stock"] for listing, _, _ in used), copies=copies, short=copies < quantity,
                 line_aud=_money(sum((each * taken for _, each, taken in used), Decimal(0))) if priced else None)
    return shown


def _more_listings(row, entry, chosen, preference=shops._UNSET_PREFERENCE):
    """Other eligible in-stock variants, cheapest first. Exact rows keep their
    printing/finish; any-printing rows keep the existing nonfoil preference."""
    if not isinstance(entry, dict):
        return []
    preference = shops.listing_preference() if preference is shops._UNSET_PREFERENCE else preference
    listings = [item for item in entry.get("listings") or () if isinstance(item, dict) and (item.get("stock") or 0) > 0]
    listings = shops.listing_preferences.filter_listings(listings, preference)
    if row.get("printing") == "exact":
        listings = shops._rows.own(row, listings)
    if chosen.get("finish") == "nonfoil":
        listings = [item for item in listings if item.get("finish") == "nonfoil"]
    same = (chosen.get("set"), str(chosen.get("collector_number") or ""), chosen.get("finish"), chosen.get("url"),
            chosen.get("condition"), chosen.get("language"), chosen.get("price_aud"))
    rest = [item for item in listings if (item.get("set"), str(item.get("number") or ""), item.get("finish"), item.get("url"),
                                        *shops.listing_preferences.words(item).values(), item.get("price")) != same]
    return sorted(rest, key=lambda item: (_price(item.get("price")) is None, _price(item.get("price")) or 0,
                                          str(item.get("set") or ""), str(item.get("number") or "")))


def _totals(lines):
    priced = [Decimal(item["line_aud"]) for item in lines if item.get("line_aud") is not None]
    return {"total_aud": _money(sum(priced, Decimal(0))) if priced else None,
            "priced": len(priced), "unpriced": len(lines) - len(priced),
            "cards": sum(item.get("copies") or 0 for item in lines)}


def basket(adapter, data, rows, rules=None, preference=shops._UNSET_PREFERENCE):
    """One shop's basket over the queue rows (ready and add-on states only), with its postage
    (shop_plan.postage) and the add-ons that reach its free-postage threshold, each marked "lifts"."""
    summary = shops.summary(data) if data else None
    shown = {"key": adapter.key, "shop": adapter.name, "site": adapter.site, "read": bool(data),
             "counts_stock": adapter.counts_stock,
             "fetched_at": summary["fetched_at"] if summary else None,
             "started_at": summary["started_at"] if summary else None,
             "rows": [], "add_ons": [], "unconfirmed": [], "unknown": [], "not_checked": []}
    if not data:
        shown.update(_totals([]))
        shown.update(add_ons_totals=_totals([]), postage=None, reach=None, partial=0)
        return shown
    for row in rows:
        state = row.get("state")
        if state != READY and state not in ADD_ON_STATES:
            continue
        item = line(row, adapter, data, preference)
        add_on = state != READY
        item["add_on"] = add_on
        if item["status"] == "in_stock":
            shown["add_ons" if add_on else "rows"].append(item)
        elif not add_on and item["status"] in ("unconfirmed", "unknown", "not_checked"):
            shown[item["status"]].append(item)
    shown.update(_totals(shown["rows"]))
    shown["add_ons_totals"] = _totals(shown["add_ons"])
    shown["partial"] = sum(bool(item.get("partial")) for key in ("rows", "add_ons", "unconfirmed")
                           for item in shown[key])
    total = shop_plan.money(shown["total_aud"])
    shown["postage"] = shop_plan.postage((rules or {}).get(adapter.key), total, shown["unpriced"])
    reached = shop_plan.reach(shown["add_ons"], shown["postage"]["short_by_aud"]) if shown["rows"] else None
    shown["reach"] = reached
    lifting = set(reached["rows"]) if reached and reached["reaches"] else set()
    for item in shown["add_ons"]:
        item["lifts"] = item.get("queue_row") in lifting
    return shown


def build(rows, captured, revision=None, rules=None, adapters=None):
    """{"queue_revision", "shops": [basket, ...], "unavailable": [...], "postage_read", "plan"}, or
    None with no snapshot at all. rules: shop_postage.rules() ({key: {postage_aud, free_over_aud}},
    None when it couldn't be read: every postage unknown)."""
    found = shop_prices.by_shop(captured)
    if not found:
        return None
    adapters = list(shops.enabled_adapters() if adapters is None else adapters)   # config.json's shops (E11-S53)
    rows = [row for row in rows or () if isinstance(row, dict)]
    preference = shop_prices.preference(captured)
    baskets = [basket(adapter, found.get(adapter.key), rows, rules, preference) for adapter in adapters]
    unavailable = []
    for row in rows:
        if row.get("state") != READY:
            continue
        at = [line(row, adapter, found.get(adapter.key), preference) for adapter in adapters]
        if any(item["status"] == "in_stock" for item in at):
            continue
        shown = {key: row.get(key) for key in ROW_FIELDS}
        shown["is_token"] = bool(row.get("is_token"))
        shown["shops"] = [{"shop": adapter.name, "status": item["status"], "fetched_at": item.get("fetched_at"),
                           "partial": bool(item.get("partial")), "shop_sets": item.get("shop_sets") or []}
                          for adapter, item in zip(adapters, at)]
        unavailable.append(shown)
    return {"queue_revision": revision, "shops": baskets, "unavailable": unavailable,
            "postage_read": rules is not None, "plan": shop_plan.plan(baskets, rules)}


def enrich(answer, *, data):
    """answer["baskets"] from the captured snapshots, only while some shop has one."""
    try:
        from . import shop_postage
        rules = shop_postage.rules() if shop_prices.by_shop(data) else None
        built = build(answer.get("to_buy", []), data, answer.get("queue_revision"), rules)
    except Exception as error:  # optional evidence: Shopping still answers without it
        from . import common
        common._log(f"Shop baskets could not be worked out: {type(error).__name__}: {error}")
        return answer
    if built is not None:
        answer["baskets"] = built
    return answer
