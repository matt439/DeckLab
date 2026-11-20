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

An exact row matches only its set, collector number and finish (nonfoil when blank).
Flexible rows retain the shop matcher's nonfoil preference. Each counted listing is allocated once
across the ready rows, and optional add-ons use the remaining supply. The plan works from the same
listing evidence and allocates it afresh for each group of shops.
"""
from decimal import Decimal

from decklab.lib import shops

from . import shop_plan, shop_prices, shop_stock

READY = "ready"
ADD_ON_STATES = ("long_term", "waiting_for_stock", "waiting_for_reprint")
ROW_FIELDS = ("queue_row", "name", "quantity", "state", "for", "printing", "set", "collector_number", "finish")


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


def _match(row, adapter, data, preference, guaranteed_only=False):
    """One shop's observed status and the available listing tiers the queue row may use."""
    shown = {key: row.get(key) for key in ROW_FIELDS}
    shown["is_token"] = bool(row.get("is_token"))
    if not data:
        shown.update(status="unread", fetched_at=None)
        return shown, []
    if shown["is_token"]:
        shown.update(status="token", fetched_at=None)
        return shown, []
    entry = shops._by_name(data.get("cards"), str(row.get("name") or ""))
    if _unconfirmed(row, entry, preference):
        shown.update(status="unconfirmed", fetched_at=(entry or {}).get("at") or data.get("fetched_at"),
                     partial=bool((entry or {}).get("partial")))
        return shown, []
    matched = shops.match(row, data, preference)
    shown.update(status=matched["status"], fetched_at=matched["fetched_at"], carried=matched["carried"],
                 partial=bool(matched.get("partial")), shop_sets=list(matched.get("shop_sets") or ()))
    for key in ("condition", "language", "skipped_cheaper", "listing_preferences"):
        if key in matched:
            shown[key] = matched[key]
    if matched["status"] != "in_stock":
        return shown, []
    name = str(row.get("name") or "").casefold()
    return shown, _offers(row, adapter, name, entry, matched, preference, guaranteed_only)


def _offers(row, adapter, name, entry, matched, preference, guaranteed_only=False):
    """All eligible printings, retaining each listing's observed availability or counted stock."""
    listings = [(index, item) for index, item in enumerate(entry.get("listings") or ())
                if isinstance(item, dict) and (item.get("stock") or 0) > 0
                and shops.listing_preferences.fits(item, preference)]
    if row.get("printing") == "exact":
        exact = {id(item) for item in shops._rows.own(row, (item for _, item in listings))}
        listings = [(index, item) for index, item in listings if id(item) in exact]
    if matched.get("finish") == "nonfoil":
        listings = [(index, item) for index, item in listings if item.get("finish") == "nonfoil"]
    offers = []
    for index, item in listings:
        price = shop_stock.money(item.get("price"))
        stock = item["stock"] if adapter.counts_stock else None
        listing = {"set": item.get("set"), "collector_number": item.get("number"), "finish": item.get("finish"),
                   "price_aud": item.get("price") if price is not None else None, "stock": stock,
                   "url": item.get("url"), **shops.listing_preferences.words(item)}
        # An available listing guarantees one even if the shop does not report its count.
        capacity = 1 if guaranteed_only and stock is None else stock
        offers.append(shop_stock.Offer((adapter.key, name, index), listing, price, capacity))
    return sorted(offers, key=lambda offer: (str(offer.listing.get("set") or ""),
                                             str(offer.listing.get("collector_number") or "")))


def _totals(lines):
    priced = sum(item["line_aud"] is not None for item in lines)
    known = sum((shop_stock.money(item["known_aud"]) for item in lines), Decimal(0))
    has_known = any(item["unpriced_copies"] < item["copies"] for item in lines)
    return {"total_aud": shop_stock.text(known) if has_known else None,
            "priced": priced, "unpriced": len(lines) - priced,
            "cards": sum(item.get("copies") or 0 for item in lines)}


def basket(adapter, data, ready, add_ons, matched, offers, rules):
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
    shop = adapter.key
    assigned = shop_stock.allocate(ready, [shop], offers)
    reserved = shop_stock.used(assigned)
    optional = shop_stock.allocate(add_ons, [shop], offers, reserved)
    for rows, allocation, prefix, other in ((ready, assigned, "rows", reserved),
                                            (add_ons, optional, "add_ons", reserved + shop_stock.used(optional))):
        for row in rows:
            key = row.get("queue_row")
            if key in allocation:
                chosen = allocation[key]
                item = shop_stock.line(matched[shop][key], chosen)
                options = offers[shop][key]
                item["stock"] = sum(offer.stock for offer, _ in chosen) if adapter.counts_stock else None
                own = {offer.key: copies for offer, copies in chosen}
                item["shared_stock"] = adapter.counts_stock and any(
                    other[offer.key] > own.get(offer.key, 0) for offer in options)
                shown[prefix].append(item)
    for row in ready:
        item = matched[shop][row.get("queue_row")]
        if item["status"] in ("unconfirmed", "unknown", "not_checked"):
            shown[item["status"]].append(item)
    shown.update(_totals(shown["rows"]))
    shown["add_ons_totals"] = _totals(shown["add_ons"])
    shown["partial"] = sum(bool(item.get("partial")) for key in ("rows", "add_ons", "unconfirmed")
                           for item in shown[key])
    total = shop_stock.money(shown["total_aud"])
    shown["postage"] = shop_plan.postage((rules or {}).get(adapter.key), total, shown["unpriced"])
    reached = shop_plan.reach(shown["add_ons"], shown["postage"]["short_by_aud"]) if shown["rows"] else None
    shown["reach"] = reached
    lifting = set(reached["rows"]) if reached and reached["reaches"] else set()
    for item in shown["add_ons"]:
        item["lifts"] = item.get("queue_row") in lifting
    return shown


def build(rows, captured, revision=None, rules=None, adapters=None, *, guaranteed_only=False):
    """{"queue_revision", "shops": [basket, ...], "unavailable": [...], "postage_read", "plan"}, or
    None with no snapshot at all. rules: shop_postage.rules() ({key: {postage_aud, free_over_aud}},
    None when it couldn't be read: every postage unknown). With guaranteed_only, each available
    listing without a quantity supplies at most the one copy the retailer confirms."""
    found = shop_prices.by_shop(captured)
    if not found:
        return None
    adapters = list(shops.enabled_adapters() if adapters is None else adapters)   # config.json's shops (E11-S53)
    ready = [row for row in rows or () if isinstance(row, dict) and row.get("state") == READY]
    add_ons = [row for row in rows or () if isinstance(row, dict) and row.get("state") in ADD_ON_STATES]
    preference = shop_prices.preference(captured)
    matches, offers = {}, {}
    for adapter in adapters:
        matches[adapter.key], offers[adapter.key] = {}, {}
        for row in ready + add_ons:
            key = row.get("queue_row")
            item, candidates = _match(row, adapter, found.get(adapter.key), preference, guaranteed_only)
            item["add_on"] = row.get("state") != READY
            matches[adapter.key][key], offers[adapter.key][key] = item, candidates
    baskets = [basket(adapter, found.get(adapter.key), ready, add_ons, matches, offers, rules) for adapter in adapters]
    facts = {row.get("queue_row"): {adapter.key: _fact(adapter, matches[adapter.key][row.get("queue_row")])
                                    for adapter in adapters} for row in ready}
    plan = shop_plan.plan(baskets, rules, ready, add_ons, matches, offers, facts)
    available_rows = {item["queue_row"] for basket in baskets for item in basket["rows"]}
    if plan:
        available_rows.update(item["queue_row"] for shop in plan["by_price"]["shops"] for item in shop["rows"])
    unavailable = [_unavailable(row, facts[row.get("queue_row")]) for row in ready
                   if row.get("queue_row") not in available_rows]
    return {"queue_revision": revision, "shops": baskets, "unavailable": unavailable,
            "postage_read": rules is not None, "plan": plan}


def _fact(adapter, item):
    return {"shop": adapter.name, "status": item["status"], "fetched_at": item.get("fetched_at"),
            "partial": bool(item.get("partial")), "shop_sets": item.get("shop_sets") or []}


def _unavailable(row, facts):
    return {**{key: row.get(key) for key in ROW_FIELDS}, "is_token": bool(row.get("is_token")),
            "shops": [{**fact, "status": "allocated" if fact["status"] == "in_stock" else fact["status"]}
                      for fact in facts.values()]}


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
