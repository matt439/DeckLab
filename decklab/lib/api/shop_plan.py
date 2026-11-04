"""Shopping's Baskets with postage (E5-S27): each shop's postage, the add-ons that reach its
free-postage threshold, and the fewest-shops plan. Pure: it reads only the baskets
shop_baskets.build made and the postage rules (lib/state/shop_postage.py), and writes nothing.

Postage of a basket (postage()): free when the priced rows reach the shop's threshold, else its
flat postage, else unknown. Rows without a price make the subtotal a lower bound ("at_least").

Add-ons that reach the threshold (reach()): of the add-ons in stock there with a price, the set
with the smallest total that lifts the basket to the threshold (an exact search over cents), or,
when even all of them fall short, none. They are rows on the queue already (long-term or waiting),
so adding them spends nothing that wasn't planned; the page says so and never adds them itself.

The plan (plan()): every combination of the shops that were read (at most MAX_SHOPS), each ready
row's copies bought at the cheapest of the combination's shops that has them (a short shop's
copies first, the rest at the next), then each shop's postage on what it got. A plan covering
fewer copies than the best coverage is never recommended. Among the rest, the lowest total of
cards and postage wins, then fewer shops; a plan with a shop whose postage is unknown can't be
weighed, so then the fewest shops are recommended and the answer says postage wasn't counted.
"by_price" is every shop at once (each card where it's cheapest), so the page shows both ways.
"""
from decimal import Decimal, InvalidOperation
from itertools import combinations

CENT = Decimal("0.01")
MAX_SHOPS = 8                   # 255 combinations at most
MAX_ADD_ONS = 60                # the add-on search's size (cents x add-ons stays small)
MAX_CENTS = 200_000             # above A$2,000 to reach, the cheapest add-ons first instead
ROW_FIELDS = ("queue_row", "name", "quantity", "state", "for", "printing", "set", "collector_number", "finish")


def money(value):
    """Decimal, or None for anything that isn't a non-negative amount."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def text(value):
    return None if value is None else f"{value.quantize(CENT)}"


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


def _ladder(item):
    """A basket line's copies as [(price each or None, copies)], cheapest listing first."""
    listing = item.get("listing") or {}
    more = [each for each in item.get("more") or () if isinstance(each, dict)]
    if not more:
        return [(money(listing.get("price_aud")), item.get("copies") or 0)]
    first = listing.get("copies") if isinstance(listing.get("copies"), int) else (item.get("copies") or 0)
    return [(money(listing.get("price_aud")), first)] + [(money(each.get("price_aud")), each.get("copies") or 0) for each in more]


def _unit(item):
    """Sort key: a line's cheapest price each, unknown prices last."""
    first = _ladder(item)[0][0]
    return (first is None, first or Decimal(0))


def _cost(item, copies):
    """(cost of the line's first copies, priced): None cost when any copy taken has no price."""
    total, left = Decimal(0), copies
    for price, have in _ladder(item):
        take = min(left, have)
        if take <= 0:
            continue
        if price is None:
            return None
        total += price * take
        left -= take
        if left <= 0:
            break
    return total


def _assign(rows, chosen, lines):
    """Each ready row's copies bought across the chosen shops, cheapest first:
    {shop key: [plan line]}, and the copies left uncovered by row."""
    bought, uncovered = {key: [] for key in chosen}, {}
    for row in rows:
        want = row["quantity"]
        options = sorted(((lines[key][row["queue_row"]], order, key) for order, key in enumerate(chosen)
                          if row["queue_row"] in lines[key]), key=lambda each: (_unit(each[0]), each[1]))
        for item, _, key in options:
            if want <= 0:
                break
            take = min(want, item.get("copies") or 0)
            if take <= 0:
                continue
            cost = _cost(item, take)
            bought[key].append({**{field: row["row"].get(field) for field in ROW_FIELDS}, "copies": take,
                                "line_aud": text(cost) if cost is not None else None})
            want -= take
        if want > 0:
            uncovered[row["queue_row"]] = want
    return bought, uncovered


def _plan(chosen, rows, lines, baskets, rules):
    bought, uncovered = _assign(rows, chosen, lines)
    shops, cards, unpriced, postage_total, unknown = [], Decimal(0), 0, Decimal(0), []
    for key in chosen:
        items = bought[key]
        if not items:
            continue
        priced = [money(item["line_aud"]) for item in items if item["line_aud"] is not None]
        subtotal = sum(priced, Decimal(0))
        missing = len(items) - len(priced)
        basket = baskets[key]
        rule = postage(rules.get(key), subtotal, missing)
        if rule["short_by_aud"] is not None:
            rule["reach"] = reach(basket.get("add_ons"), rule["short_by_aud"])
        shops.append({"key": key, "shop": basket["shop"], "rows": items, "subtotal_aud": text(subtotal),
                      "unpriced": missing, "cards": sum(item["copies"] for item in items), "postage": rule})
        cards += subtotal
        unpriced += missing
        if rule["charged_aud"] is None:
            unknown.append(basket["shop"])
        else:
            postage_total += money(rule["charged_aud"])
    covered = sum(row["quantity"] for row in rows) - sum(uncovered.values())
    return {"shops": shops, "keys": [shop["key"] for shop in shops], "cards": covered,
            "uncovered": [{"queue_row": key, "name": next(row["row"].get("name") for row in rows if row["queue_row"] == key),
                           "copies": copies} for key, copies in uncovered.items()],
            "cards_aud": text(cards), "unpriced": unpriced, "postage_aud": text(postage_total),
            "postage_unknown": unknown, "total_aud": text(cards + postage_total)}


def _weigh(plan):
    return (-plan["cards"], money(plan["total_aud"]), len(plan["shops"]))


def plan(baskets, rules):
    """{"recommended", "by_price", "options", "wanted": copies, "weighed": bool, "saves_aud"} over
    the read shops' baskets, or None when no read shop has a ready row in stock."""
    read = [basket for basket in baskets if basket.get("read") and basket.get("rows")][:MAX_SHOPS]
    if not read:
        return None
    rules = rules or {}
    by_key = {basket["key"]: basket for basket in read}
    lines = {basket["key"]: {item.get("queue_row"): item for item in basket["rows"]} for basket in read}
    seen, rows = set(), []
    for basket in read:
        for item in basket["rows"]:
            key = item.get("queue_row")
            if key in seen:
                continue
            seen.add(key)
            try:
                quantity = max(int(str(item.get("quantity") or "0")), 0)
            except ValueError:
                quantity = 0
            rows.append({"queue_row": key, "quantity": quantity, "row": item})
    order = [basket["key"] for basket in read]
    found = {}
    for size in range(1, len(order) + 1):
        for chosen in combinations(order, size):
            made = _plan(list(chosen), rows, lines, by_key, rules)
            found.setdefault(tuple(made["keys"]), made)
    options = list(found.values())
    by_price = _plan(order, rows, lines, by_key, rules)
    best = max(option["cards"] for option in options)
    full = [option for option in options if option["cards"] == best]
    weighable = [option for option in full if not option["postage_unknown"]]
    weighed = bool(weighable) and len(weighable) == len(full)
    if weighed:
        recommended = min(full, key=_weigh)
    else:
        recommended = min(full, key=lambda option: (len(option["shops"]), money(option["cards_aud"])))
    saves = None
    if weighed and not by_price["postage_unknown"] and len(recommended["shops"]) < len(by_price["shops"]):
        saves = text(money(by_price["total_aud"]) - money(recommended["total_aud"]))
    options.sort(key=lambda option: (-option["cards"], bool(option["postage_unknown"]), money(option["total_aud"]),
                                     len(option["shops"])))
    return {"recommended": recommended, "by_price": by_price, "options": options,
            "wanted": sum(row["quantity"] for row in rows), "weighed": weighed, "saves_aud": saves}
