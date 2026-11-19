"""Shopping's Baskets with postage (E5-S27): each shop's postage, the add-ons that reach its
free-postage threshold, and the fewest-shops plan. Pure: it reads only the baskets
shop_baskets.build made and the postage rules (lib/state/shop_postage.py), and writes nothing.

Postage of a basket (postage()): free when the priced rows reach the shop's threshold, else its
flat postage, else unknown. Rows without a price make the subtotal a lower bound ("at_least").

Add-ons that reach the threshold (reach()): of the add-ons in stock there with a price, the set
with the smallest total that lifts the basket to the threshold (an exact search over cents), or,
when even all of them fall short, none. They are rows on the queue already (long-term or waiting),
so adding them spends nothing that wasn't planned; the page says so and never adds them itself.

The plan (plan()): every combination of the shops with relevant saved stock (at most MAX_SHOPS),
with the requested rows allocated over its listing price tiers. Totals use the postage on what
each shop gets. Coverage is counted over the full ready queue, even when a check failed. Among
the plans with best coverage, prefer the lowest total with known prices and postage, then fewer
shops. When postage cannot be compared, prefer fewer shops. "by_price" uses every shop at once.
"""
from decimal import Decimal
from itertools import combinations

from . import shop_stock
from .shop_stock import CENT, money, text

MAX_SHOPS = 8                   # 255 combinations at most
MAX_ADD_ONS = 60                # the add-on search's size (cents x add-ons stays small)
MAX_CENTS = 200_000             # above A$2,000 to reach, the cheapest add-ons first instead
REQUEST_FIELDS = ("queue_row", "name", "printing", "set", "collector_number", "finish")


def postage(rules, subtotal, unpriced=0):
    """A basket's postage: {postage_aud, free_over_aud (the rules), charged_aud (None: unknown),
    free, short_by_aud (to the threshold), at_least (rows without a price, so the subtotal is
    a lower bound), known}."""
    rules = rules or {}
    flat, over = money(rules.get("postage_aud")), money(rules.get("free_over_aud"))
    subtotal = subtotal if subtotal is not None else Decimal(0)
    free = (over is not None and subtotal >= over) or flat == 0
    charged = Decimal(0) if free else flat
    short = over - subtotal if over is not None and not free else None
    return {"postage_aud": text(flat), "free_over_aud": text(over), "charged_aud": text(charged),
            "free": bool(free), "short_by_aud": text(short), "at_least": bool(unpriced),
            "known": charged is not None}


def reach(add_ons, short_by):
    """{"rows": [queue_row ids], "total_aud", "reaches"} for the add-ons that lift a basket by
    short_by at the smallest total, or None without a gap or a priced add-on."""
    short = money(short_by)
    priced = [(item, money(item.get("line_aud"))) for item in add_ons or ()]
    priced = [(item, value) for item, value in priced if value is not None and value > 0][:MAX_ADD_ONS]
    if short is None or short <= 0 or not priced:
        return None
    cents = [int((value / CENT).to_integral_value()) for _, value in priced]
    need = int((short / CENT).to_integral_value())
    everything = sum(cents)
    if everything < need:
        return {"rows": [item.get("queue_row") for item, _ in priced], "total_aud": text(everything * CENT),
                "reaches": False}
    limit = need + max(cents)
    if limit > MAX_CENTS:
        chosen, total = [], 0
        for index in sorted(range(len(cents)), key=lambda each: cents[each]):
            chosen.append(index)
            total += cents[index]
            if total >= need:
                break
        return {"rows": [priced[index][0].get("queue_row") for index in chosen], "total_aud": text(total * CENT),
                "reaches": True}
    best = {0: ()}                  # reachable total in cents -> the add-ons (indexes) that make it
    for index, value in enumerate(cents):
        for total, chosen in list(best.items()):
            new = total + value
            if new <= limit and new not in best:
                best[new] = chosen + (index,)
    total = min(each for each in best if each >= need)
    return {"rows": [priced[index][0].get("queue_row") for index in best[total]], "total_aud": text(total * CENT),
            "reaches": True}


def _uncovered(rows, assigned, active, facts, offers, reserved):
    uncovered = []
    for row in rows:
        key = row.get("queue_row")
        own = assigned.get(key, ())
        left = shop_stock.quantity(row) - sum(count for _, count in own)
        if left <= 0:
            continue
        counts = {offer.key: count for offer, count in own}
        reasons = []
        for shop, fact in facts[key].items():
            status = fact["status"]
            if status == "in_stock":
                shared = any(reserved[offer.key] > counts.get(offer.key, 0) for offer in offers[shop][key])
                status = "outside_plan" if shop not in active else "allocated" if shared else "short"
            reasons.append({**fact, "status": status})
        uncovered.append({**{field: row.get(field) for field in REQUEST_FIELDS}, "copies": left, "shops": reasons})
    return uncovered


def _shop(key, items, rules, reserved, baskets, matches, add_ons, offers):
    subtotal = sum((money(item["known_aud"]) for item in items), Decimal(0))
    missing = sum(item["line_aud"] is None for item in items)
    unknown_copies = sum(item["unpriced_copies"] for item in items)
    rule = postage(rules.get(key), subtotal, missing)
    optional = []
    if rule["short_by_aud"] is not None:
        additional = shop_stock.allocate(add_ons, [key], offers, reserved)
        optional = [shop_stock.line(matches[key][row], allocations) for row, allocations in additional.items()]
        rule["reach"] = reach(optional, rule["short_by_aud"])
    return {"key": key, "shop": baskets[key]["shop"], "rows": items, "add_ons": optional,
            "subtotal_aud": text(subtotal), "unpriced": missing, "unpriced_copies": unknown_copies,
            "cards": sum(item["copies"] for item in items), "postage": rule}


def _plan(chosen, rows, add_ons, baskets, rules, matches, offers, facts):
    assigned = shop_stock.allocate(rows, chosen, offers)
    reserved = shop_stock.used(assigned)
    bought = {key: [] for key in chosen}
    for row in rows:
        key = row.get("queue_row")
        by_shop = {}
        for offer, copies in assigned.get(key, ()):
            by_shop.setdefault(offer.key[0], []).append((offer, copies))
        for shop, allocation in by_shop.items():
            bought[shop].append(shop_stock.line(matches[shop][key], allocation))
    shops = [_shop(key, bought[key], rules, reserved, baskets, matches, add_ons, offers)
             for key in chosen if bought[key]]
    keys = [shop["key"] for shop in shops]
    cards = sum((money(shop["subtotal_aud"]) for shop in shops), Decimal(0))
    postage_total = sum((money(shop["postage"]["charged_aud"]) or 0 for shop in shops), Decimal(0))
    return {"shops": shops, "keys": keys, "cards": sum(shop["cards"] for shop in shops),
            "uncovered": _uncovered(rows, assigned, keys, facts, offers, reserved),
            "cards_aud": text(cards), "unpriced": sum(shop["unpriced"] for shop in shops),
            "unpriced_copies": sum(shop["unpriced_copies"] for shop in shops), "postage_aud": text(postage_total),
            "postage_unknown": [shop["shop"] for shop in shops if not shop["postage"]["known"]],
            "stock_unknown": [shop["shop"] for shop in shops if not baskets[shop["key"]]["counts_stock"]],
            "total_aud": text(cards + postage_total)}


def _weigh(plan):
    return (plan["unpriced_copies"], money(plan["total_aud"]), len(plan["shops"]))


def plan(baskets, rules, rows, add_ons, matches, offers, facts):
    """Build the recommendation, per-copy price comparison and other ways from full ready demand."""
    wanted = sum(shop_stock.quantity(row) for row in rows)
    if not wanted:
        return None
    rules = rules or {}
    by_key = {basket["key"]: basket for basket in baskets}
    order = [basket["key"] for basket in baskets if basket.get("rows")][:MAX_SHOPS]
    by_price = _plan(order, rows, add_ons, by_key, rules, matches, offers, facts)
    found = {}
    for size in range(1, len(order)):
        for chosen in combinations(order, size):
            made = _plan(chosen, rows, add_ons, by_key, rules, matches, offers, facts)
            found.setdefault(tuple(made["keys"]), made)
    found.setdefault(tuple(by_price["keys"]), by_price)
    options = list(found.values())
    full = [option for option in options if option["cards"] == by_price["cards"]]
    weighed = all(not option["postage_unknown"] for option in full)
    if weighed:
        recommended = min(full, key=_weigh)
    else:
        recommended = min(full, key=lambda option: (len(option["shops"]), option["unpriced_copies"], money(option["cards_aud"])))
    saves = None
    if weighed and not recommended["unpriced"] and not by_price["unpriced"] and len(recommended["shops"]) < len(by_price["shops"]):
        saves = text(money(by_price["total_aud"]) - money(recommended["total_aud"]))
    options.sort(key=lambda option: (-option["cards"], bool(option["postage_unknown"]), *_weigh(option)))
    return {"recommended": recommended, "by_price": by_price, "options": options if order else [],
            "wanted": wanted, "weighed": weighed, "saves_aud": saves}
