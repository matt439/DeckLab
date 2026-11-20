"""Search eligible listing allocations for free-postage thresholds on a saved shopping plan.

Each card name has independent stock. Its price-only flow already establishes maximum
coverage, maximum exact requests filled, minimum unknown prices, then minimum card cost.
Enumerate only allocations retaining those first three facts. Combine card choices by
each shop's subtotal capped at its free-postage threshold. For identical threshold
progress, used shops and unknown-price shops, only the cheapest card cost can win.
"""
from collections import defaultdict
from dataclasses import dataclass

from .shop_stock import money, quantity


# Shared by all subsets in a Shopping read. Large queues still get the best feasible
# allocation found and an explicit search_complete=False. Quantities travel in bulk.
MAX_STEPS = 60_000
MAX_CARD_EDGES = 80


class SearchLimit(Exception):
    pass


class Budget:
    def __init__(self):
        self.remaining = MAX_STEPS

    def step(self):
        self.remaining -= 1
        if self.remaining < 0:
            raise SearchLimit


def _cents(amount):
    if amount is None:
        return None
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise SearchLimit  # older non-cent evidence retains its original priced plan
    return int(cents)


@dataclass
class Choice:
    spend: tuple
    used: int
    unknown: int
    lines: tuple

    @property
    def cost(self):
        return sum(self.spend)


def _choice(lines, indexes):
    lines = tuple(lines)
    spend = [0] * len(indexes)
    used = unknown = 0
    for _, offer, count in lines:
        shop = indexes[offer.key[0]]
        used |= 1 << shop
        if offer.price is None:
            unknown |= 1 << shop
        else:
            spend[shop] += _cents(offer.price) * count
    return Choice(tuple(spend), used, unknown, lines)


def _card_options(group, base, indexes, allowance, budget):
    """Enumerate each row-to-listing quantity subject to shared stock and flow priorities."""
    exact = {row["queue_row"] for row, _ in group if row.get("printing") == "exact"}
    targets = [0, 0]
    unknown = 0
    for key, offer, count in base.lines:
        targets[key in exact] += count
        if offer.price is None:
            unknown += count
    # In reverse, record how much of each class can still be filled after this row,
    # and how much this row could buy from its remaining listings.
    edges, stock, later_demand = [], {}, [0, 0]
    cap_cost = base.cost + allowance
    for row, offers in reversed(group):
        key = row["queue_row"]
        kind = key in exact
        later_supply = 0
        want = quantity(row)
        for offer in reversed(offers):
            capacity = want if offer.stock is None else offer.stock
            price = _cents(offer.price)
            # A single copy more expensive than the entire allowed card cost cannot win.
            if not capacity or price is None and not unknown or price is not None and price > cap_cost:
                continue
            stock[offer.key] = sum(targets) if offer.stock is None else offer.stock
            edges.append((key, kind, want, offer, price, later_demand[kind], later_supply))
            later_supply += capacity
        later_demand[kind] += min(want, later_supply)
    if len(edges) > MAX_CARD_EDGES:
        raise SearchLimit
    edges.reverse()
    lines = []
    options = {(base.spend, base.used, base.unknown): base}

    def visit(pos, left, unpriced, cost):
        budget.step()
        if pos == len(edges):
            if not any(targets) and not unpriced:
                option = _choice(lines, indexes)
                options.setdefault((option.spend, option.used, option.unknown), option)
            return
        key, kind, want, offer, price, later_rows, later_supply = edges[pos]
        if not pos or edges[pos - 1][0] != key:
            left = want
        high = min(left, stock[offer.key], targets[kind])
        if price is None:
            high = min(high, unpriced)
        elif price:
            high = min(high, (cap_cost - cost) // price)
        low = max(0, targets[kind] - later_rows - later_supply)
        for count in range(high, low - 1, -1):
            if count:
                lines.append((key, offer, count))
            targets[kind] -= count
            stock[offer.key] -= count
            visit(pos + 1, left - count, unpriced - (count if price is None else 0),
                  cost + (price or 0) * count)
            stock[offer.key] += count
            targets[kind] += count
            if count:
                lines.pop()

    visit(0, 0, unknown, 0)
    return options.values()


def _fee(spend, used, unknown, flats, thresholds):
    amount = 0
    for i, flat in enumerate(flats):
        if not used & (1 << i) or flat == 0:
            continue
        threshold = thresholds[i]
        if threshold is not None and spend[i] >= threshold:
            continue
        if flat is None or threshold is not None and unknown & (1 << i):
            return None
        amount += flat
    return amount


def _one_discount(groups, bases, options, flats, thresholds, totals, budget):
    """When all shops are required and at most one can post free, solve each threshold
    separately. At the same extra card cost keep only the path spending most at that
    shop. A cheaper prefix with at least as much progress also dominates a dearer one.
    """
    flats = [0 if cap == 0 else flat for flat, cap in zip(flats, thresholds)]
    base_cost = sum(totals)
    current_fee = sum(flat for total, flat, cap in zip(totals, flats, thresholds) if cap is None or total < cap)
    best_total = base_cost + current_fee
    best_path = None
    try:
        for index, (cap, flat) in enumerate(zip(thresholds, flats)):
            if cap is None or not flat:
                continue
            fixed_total = base_cost + sum(flats) - flat
            if fixed_total >= best_total:
                continue
            frontier = {0: (0, None)}  # extra cents -> subtotal at this shop, changed assignments
            remaining = totals[index]
            for group, base, choices in zip(groups, bases, options):
                remaining -= base.spend[index]
                keys = tuple(row["queue_row"] for row, _ in group)
                next_layer = {}
                for choice in choices:
                    delta = choice.cost - base.cost
                    for prior, (subtotal, path) in frontier.items():
                        budget.step()
                        extra = prior + delta
                        if fixed_total + extra >= best_total:
                            continue
                        spend = subtotal + choice.spend[index]
                        if extra in next_layer and next_layer[extra][0] >= spend:
                            continue
                        tail = path if choice is base else (path, keys, choice.lines)
                        if spend + remaining >= cap:
                            best_total, best_path = fixed_total + extra, tail
                        next_layer[extra] = spend, tail
                frontier = {}
                highest = -1
                for extra in sorted(next_layer):
                    spend, path = next_layer[extra]
                    if spend > highest:
                        frontier[extra] = spend, path
                        highest = spend
    except SearchLimit:
        return best_path, False
    return best_path, True


def _apply(baseline, path):
    if path is None:
        return baseline
    result = dict(baseline)
    while path:
        path, keys, lines = path
        for key in keys:
            result.pop(key, None)
        for key, offer, count in lines:
            result.setdefault(key, []).append((offer, count))
    return result


def optimize(chosen, rows, offers, baseline, rules, paid, required, budget):
    """Return a feasible assignment and whether all potentially better choices were checked.

    Dropping a shop is already tested by plan()'s subsets. At least one threshold and
    some paid postage are necessary for a dearer listing inside this subset to help.
    """
    if not paid or not any(money(rules.get(s, {}).get("free_over_aud")) for s in chosen):
        return baseline, True
    indexes = {shop: i for i, shop in enumerate(chosen)}
    groups = defaultdict(list)
    for row in rows:
        key = row["queue_row"]
        candidates = [offer for shop in chosen for offer in offers[shop].get(key, ())]
        if candidates and quantity(row):
            groups[str(row["name"]).casefold()].append((row, candidates))
    complete = True
    best_path = None
    try:
        flats = [_cents(money(rules.get(s, {}).get("postage_aud"))) for s in chosen]
        thresholds = [_cents(money(rules.get(s, {}).get("free_over_aud"))) for s in chosen]
        allowance = _cents(paid)
        bases = [_choice(((row["queue_row"], offer, count) for row, _ in group
                          for offer, count in baseline.get(row["queue_row"], ())), indexes)
                 for group in groups.values()]
        # Unprocessed names keep their original feasible allocation at every step;
        # even an interrupted search can return an improved complete basket.
        zero = (0,) * len(chosen)
        suffix = [(zero, 0, 0)]
        for base in reversed(bases):
            spend, used, unknown = suffix[-1]
            suffix.append((tuple(a + b for a, b in zip(spend, base.spend)), used | base.used, unknown | base.unknown))
        base_cost = sum(suffix[-1][0])
        best_score = (base_cost + allowance, suffix[-1][1].bit_count())
        options = None
        if required and len(chosen) <= 2 and None not in flats and not suffix[-1][2]:
            options = [list(_card_options(group, base, indexes, allowance, budget))
                       for group, base in zip(groups.values(), bases)]
            targets = [cap for cap, flat in zip(thresholds, flats) if cap and flat]
            # Even the dearest combination of feasible choices may fall short of
            # both thresholds together. Card spend above today's best delivered
            # total also cannot improve the recommendation.
            most = min(best_score[0], sum(max(choice.cost for choice in variants) for variants in options))
            if len(targets) <= 1 or most < sum(targets):
                path, complete = _one_discount(groups.values(), bases, options, flats, thresholds, suffix[-1][0], budget)
                return _apply(baseline, path), complete
        # key: thresholds reached so far, shops used, shops with any unpriced copy.
        # value: extra card cost above the cheapest prefix and the path of changed names.
        states = {(zero, 0, 0): (0, None)}
        for i, (group, base) in enumerate(zip(groups.values(), bases)):
            suffix.pop()
            remaining, later_used, later_unknown = suffix[-1]
            choices = options[i] if options is not None else _card_options(group, base, indexes, allowance, budget)
            new = {}
            row_keys = tuple(row["queue_row"] for row, _ in group)
            for choice in choices:
                extra = choice.cost - base.cost
                for (progress, used, unknown), (previous, path) in states.items():
                    budget.step()
                    increase = previous + extra
                    if base_cost + increase > best_score[0]:
                        continue
                    spent = tuple(min(cap or 0, a + b) for cap, a, b in zip(thresholds, progress, choice.spend))
                    used_now, unknown_now = used | choice.used, unknown | choice.unknown
                    state = spent, used_now, unknown_now
                    if state in new and new[state][0] <= increase:
                        continue
                    tail = path if choice is base else (path, row_keys, choice.lines)
                    new[state] = increase, tail
                    with_rest = tuple(a + b for a, b in zip(spent, remaining))
                    all_used = used_now | later_used
                    fee = _fee(with_rest, all_used, unknown_now | later_unknown, flats, thresholds)
                    if fee is not None:
                        score = (base_cost + increase + fee, all_used.bit_count())
                        if score < best_score:
                            best_score, best_path = score, tail
            states = new
    except SearchLimit:
        complete = False
    return _apply(baseline, best_path), complete
