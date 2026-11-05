"""Commanders we could build (E9-S28): the free pool's legendary creatures (and other cards that may be a
commander) ranked by how much of a Commander deck the rest of the free pool already covers in each one's
colour identity, counted by the Command Zone template's role targets (lib/stats/role_targets.py, E9-S26).

A candidate is a card with a copy free in the space (pool.free_copies: owned or on the way, less what built
decks and intact products hold) that may be a commander on its own (the rules' check, passed in as
may_lead: lib/stats/commander.py's _can_be_commander, CR 903.3) and is legal in Commander. A Background is
never one on its own; a candidate with a partner ability says so, and its pairs are rows of their own.

For each candidate, the free cards that fit its deck are the pool's other free cards whose colour identity
is within its own (colourless always fits) and that are legal in Commander (role_pool.fits). A Commander
deck plays one copy of each, so a card counts once however many copies are free. Each template category
with a Deck Lab measure is counted as the Stats tab counts it (role_targets.CATEGORIES: its roles, less
its "except" roles), from the cards' "roles" in the card index:

- ramp, card advantage (the draw role), targeted disruption (removal or counterspell, not board wipes)
  and mass disruption (board wipes) make the coverage: the sum over them of min(free cards, target),
  over the sum of their targets (40 with the template's figures). A card in two categories counts in
  both, as the template's categories overlap.
- lands are the free non-basic lands: they're shown, but don't count towards the coverage, since basic
  lands fill whatever's left and the pool never counts them.
- plan cards have no measure; the candidate's other free non-land cards are shown as "cards" instead.

Best first: coverage, then the free non-land cards that fit, then the name. Nothing here reads the
inventory or the card data: the caller passes the free copies, a card lookup and the categories, so the
rules are tested on their own.

cards_for (E9-S28's second slice) names one candidate's free cards: each category's (the lands' being the
free non-basic lands) and the other non-land cards that fit no counted category, each list most-printed first (as the
Stats tab's free cards by role rank them, role_pool.free_by_role) and at most MAX_LISTED long, with the
rest counted.

E9-S28's third slice adds two kinds of row:

- pairs (pairs()): two free cards that may be your two commanders together (pair_rule, passed in: the
  rules' check, lib/stats/commander.py's _pairing, with each half able to lead or being the Background a
  "Choose a Background" commander takes), counted over the union of their colour identities as one
  candidate is, and ranked with the singles by the same coverage figure. Pairs can explode (every
  partner with every other), so at most MAX_PAIRABLE cards are tried as halves (most-printed first) and
  at most MAX_PAIRS pairs kept (the best); the answer says how many were left out.
- held rows (held()): a card that may lead and is owned (or on the way) with no copy free, since built
  decks or intact products hold every copy. It's counted against the free pool as a candidate is; the
  caller names the decks holding it and lists these after the free rows.
"""
from .role_pool import fits

LIMIT = 50              # candidates answered by default
MAX_LISTED = 40         # cards cards_for names in one list (the rest are counted)
MAX_PAIRABLE = 200      # cards tried as one half of a pair (most-printed first); the rest aren't paired
MAX_PAIRS = 100         # pair rows kept, the best (the rest are counted)
MAX_HELD = 50           # held rows answered (the rest are counted)


def _is_land(card):
    front = (card.get("type_line") or "").split(" // ")[0].split("—")[0]
    return "Land" in front.split()


def _is_background_type(card):
    return "Background" in (card.get("type_line") or "").split(" // ")[0].split("—")[-1].split()


def _counts(category):
    return category.get("roles") or category.get("lands")


def _entry(name, card, spare):
    return {"name": name, "card": card, "identity": frozenset(card.get("color_identity") or ()),
            "roles": set(card.get("roles") or ()), "land": _is_land(card), "free": spare}


def _entries(free, card_of):
    """The free cards that are legal in Commander, each {"name", "card", "identity", "roles", "land", "free"}."""
    entries = []
    for name, spare in free.items():
        if spare <= 0:
            continue
        card = card_of(name)
        if card is None or card.get("commander_legality") != "legal":
            continue
        entries.append(_entry(name, card, spare))
    return entries


def _in_category(category, entry):
    if category.get("lands"):
        return entry["land"]
    roles, never = set(category["roles"]), set(category.get("except") or ())
    return bool(entry["roles"] & roles) and not entry["roles"] & never


def _listed(rows, limit):
    """(the rows' [{"name", "free"}] most-printed first then by name, at most limit, and how many more)."""
    rows = sorted(rows, key=lambda e: (-len(e["card"].get("printings") or ()), e["name"].casefold()))
    return [{"name": e["name"], "free": e["free"]} for e in rows[:limit]], max(len(rows) - limit, 0)


def _held_lead(name, card):
    """A lead with no copy free (a held card), or None when it isn't a legal card."""
    if card is None or card.get("commander_legality") != "legal":
        return None
    return _entry(name, card, 0)


def _leads(names, entries, card_of, held):
    """The lead entries for names (one or two), or None: each free (in entries) or, alone, in held."""
    by_name = {e["name"]: e for e in entries}
    leads = []
    for name in names:
        lead = by_name.get(name)
        if lead is None and len(names) == 1 and name in held:
            lead = _held_lead(name, card_of(name))
        if lead is None:
            return None
        leads.append(lead)
    return leads


def cards_for(name, free, card_of, may_lead, categories, limit=MAX_LISTED, pair_rule=None, held=()):
    """One candidate's free cards by name, or None when name isn't a candidate (no copy free, not legal in
    Commander, or it may not be a commander alone): {"categories": [{"category", "label", "target",
    "count", "short", "in_coverage", "cards": [{"name", "free"}], "more"}] for each category with a
    measure (the lands' are the free non-basic lands; the plan has none), "others" ({"cards", "more",
    "count"}: the free non-land cards that fit no counted category)}. The arguments are candidates'.

    name may be a list of two names, a pair (both with a copy free, and pair_rule(a, b) not None), counted
    over both colour identities; held is the names that are a candidate with no copy free (held()'s)."""
    names = [name] if isinstance(name, str) else list(name)
    if not 1 <= len(names) <= 2 or len(set(names)) != len(names):
        return None
    entries = _entries(free, card_of)
    leads = _leads(names, entries, card_of, set(held))
    if leads is None:
        return None
    if len(leads) == 1:
        if not may_lead(leads[0]["card"]):
            return None
    elif pair_rule is None or pair_rule(leads[0]["card"], leads[1]["card"]) is None:
        return None
    identity = frozenset().union(*(e["identity"] for e in leads))
    fit = [e for e in entries if all(e is not x for x in leads) and fits(e["card"], identity)]
    parts, counted = [], set()
    for c in categories:
        if not _counts(c):
            continue
        rows = [e for e in fit if _in_category(c, e)]
        if c.get("roles"):
            counted.update(e["name"] for e in rows)
        listed, more = _listed(rows, limit)
        parts.append({"category": c["category"], "label": c["label"], "target": c["target"],
                      "count": len(rows), "short": bool(c.get("roles")) and len(rows) < c["target"],
                      "in_coverage": bool(c.get("roles")), "cards": listed, "more": more})
    others = [e for e in fit if not e["land"] and e["name"] not in counted]
    listed, more = _listed(others, limit)
    return {"categories": parts, "others": {"cards": listed, "more": more, "count": len(others)}}


class _Groups:
    """The free entries grouped by colour identity (at most 32 groups), each group's per-category counts,
    non-land cards and lands added up once: a candidate's figures are then a sum over the groups within
    its identity, less its own leads, so a pair's many identities stay cheap."""

    def __init__(self, entries, categories):
        self.categories = [c for c in categories if _counts(c)]
        self.groups = {}
        for e in entries:
            group = self.groups.setdefault(e["identity"], [0] * (len(self.categories) + 2))
            for i, n in enumerate(self._marks(e)):
                group[i] += n

    def _marks(self, e):
        return [int(_in_category(c, e)) for c in self.categories] + [int(not e["land"]), int(e["land"])]

    def totals(self, identity, leads):
        """({category: count}, non-land cards, lands) of the free cards within identity, leads left out."""
        sums = [0] * (len(self.categories) + 2)
        for key, group in self.groups.items():
            if key <= identity:
                for i, n in enumerate(group):
                    sums[i] += n
        for lead in leads:
            if lead["free"] > 0:            # a held lead is in no group
                for i, n in enumerate(self._marks(lead)):
                    sums[i] -= n
        return {c["category"]: sums[i] for i, c in enumerate(self.categories)}, sums[-2], sums[-1]


def _row(leads, groups, categories, of):
    identity = frozenset().union(*(e["identity"] for e in leads))
    counts, n_cards, n_lands = groups.totals(identity, leads)
    parts, covered = [], 0
    for c in categories:
        count = counts.get(c["category"]) if _counts(c) else None
        in_coverage = bool(c.get("roles"))
        if in_coverage:
            covered += min(count, c["target"])
        parts.append({"category": c["category"], "label": c["label"], "target": c["target"],
                      "about": c.get("about", False), "count": count,
                      "short": in_coverage and count < c["target"], "in_coverage": in_coverage,
                      "measure": c.get("measure")})
    return {"name": " and ".join(e["name"] for e in leads), "names": [e["name"] for e in leads],
            "colours": [x for x in "WUBRG" if x in identity],
            "share": round(covered / of, 4) if of else None, "covered": covered, "of": of,
            "categories": parts, "short": [p["label"] for p in parts if p["short"]],
            "cards": n_cards, "lands": n_lands}


def best_first(rows):
    """rows (candidates', pairs' or held()'s) sorted best first, in place: coverage, cards, then name."""
    rows.sort(key=lambda c: (-(c["share"] or 0), -c["cards"], c["name"].casefold()))
    return rows


def _of(categories):
    return sum(c["target"] for c in categories if c.get("roles"))


def candidates(free, card_of, may_lead, categories, partners=lambda card: []):
    """[{"kind": "single", "name", "names" ([name]), "colours" (WUBRG letters), "share", "covered", "of",
    "categories": [{"category", "label", "target", "about", "count" (None: not counted), "short" (below
    the target, for a category that makes the coverage), "in_coverage", "measure"}], "short" (labels of
    the coverage categories below target), "cards" (free non-land cards that fit), "lands" (free
    non-basic lands that fit), "partner" (the candidate's partner abilities in words)}], best first.

    free is {name: copies free} (pool.free_copies), card_of(name) the card or None (skipped),
    may_lead(card) whether it may be a commander alone, categories role_targets.CATEGORIES and
    partners(card) its partner abilities in words."""
    entries = _entries(free, card_of)
    groups, of = _Groups(entries, categories), _of(categories)
    return best_first([{"kind": "single", **_row([lead], groups, categories, of),
                        "partner": list(partners(lead["card"]))}
                       for lead in entries if may_lead(lead["card"])])


def pairs(free, card_of, pairable, pair_rule, categories, max_pairable=MAX_PAIRABLE, max_pairs=MAX_PAIRS):
    """(rows, {"found", "left_out", "untried"}): the pairs of free cards that may be two commanders
    together, as candidates' rows with "kind": "pair", "names" (the two by name, a Background second) and
    "pairing" (pair_rule's words), best first and at most max_pairs. found is how many pairs there were,
    left_out how many of those aren't listed, untried how many pairable cards weren't tried as halves
    (beyond max_pairable, most-printed first). pairable(card) says whether a card may be half of a pair
    (it has a partner ability, or is a Background or a Doctor); pair_rule(a, b) the pairing's words, or
    None when the two can't be commanders together."""
    entries = _entries(free, card_of)
    halves = sorted((e for e in entries if pairable(e["card"])),
                    key=lambda e: (-len(e["card"].get("printings") or ()), e["name"].casefold()))
    tried, untried = halves[:max_pairable], max(len(halves) - max_pairable, 0)
    groups, of = _Groups(entries, categories), _of(categories)
    rows = []
    for i, a in enumerate(tried):
        for b in tried[i + 1:]:
            words = pair_rule(a["card"], b["card"])
            if words is None:
                continue
            two = sorted((a, b), key=lambda e: (_is_background_type(e["card"]), e["name"].casefold()))
            rows.append({"kind": "pair", **_row(two, groups, categories, of), "pairing": words})
    best_first(rows)
    return rows[:max_pairs], {"found": len(rows), "left_out": max(len(rows) - max_pairs, 0), "untried": untried}


def held(owned, free, card_of, may_lead, categories, partners=lambda card: []):
    """candidates' rows, with "kind": "held", of the cards that may lead and are owned (or on the way) with
    no copy free (owned {name: copies}, the pool's): built decks or intact products hold every copy. Each
    is counted against the free pool as a candidate is. Best first."""
    entries = _entries(free, card_of)
    groups, of = _Groups(entries, categories), _of(categories)
    rows = []
    for name, qty in owned.items():
        if qty <= 0 or free.get(name, 0) > 0:
            continue
        lead = _held_lead(name, card_of(name))
        if lead is None or lead["land"] or not may_lead(lead["card"]):
            continue
        rows.append({"kind": "held", **_row([lead], groups, categories, of),
                     "partner": list(partners(lead["card"]))})
    return best_first(rows)
