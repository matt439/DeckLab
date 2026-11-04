"""Commanders we could build (E9-S28): the free pool's legendary creatures (and other cards that may be a
commander) ranked by how much of a Commander deck the rest of the free pool already covers in each one's
colour identity, counted by the Command Zone template's role targets (lib/stats/role_targets.py, E9-S26).

A candidate is a card with a copy free in the space (pool.free_copies: owned or on the way, less what built
decks and intact products hold) that may be a commander on its own (the rules' check, passed in as
may_lead: lib/stats/commander.py's _can_be_commander, CR 903.3) and is legal in Commander. A Background is
never one on its own; a candidate with a partner ability says so, but its partner isn't counted.

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
"""
from .role_pool import fits

LIMIT = 50              # candidates answered by default
MAX_LISTED = 40         # cards cards_for names in one list (the rest are counted)


def _is_land(card):
    front = (card.get("type_line") or "").split(" // ")[0].split("—")[0]
    return "Land" in front.split()


def _counts(category):
    return category.get("roles") or category.get("lands")


def _category_count(category, entries):
    return sum(1 for e in entries if _in_category(category, e))


def _entries(free, card_of):
    """The free cards that are legal in Commander, each {"name", "card", "identity", "roles", "land", "free"}."""
    entries = []
    for name, spare in free.items():
        if spare <= 0:
            continue
        card = card_of(name)
        if card is None or card.get("commander_legality") != "legal":
            continue
        entries.append({"name": name, "card": card, "identity": frozenset(card.get("color_identity") or ()),
                        "roles": set(card.get("roles") or ()), "land": _is_land(card), "free": spare})
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


def cards_for(name, free, card_of, may_lead, categories, limit=MAX_LISTED):
    """One candidate's free cards by name, or None when name isn't a candidate (no copy free, not legal in
    Commander, or it may not be a commander alone): {"categories": [{"category", "label", "target",
    "count", "short", "in_coverage", "cards": [{"name", "free"}], "more"}] for each category with a
    measure (the lands' are the free non-basic lands; the plan has none), "others" ({"cards", "more",
    "count"}: the free non-land cards that fit no counted category)}. The arguments are candidates'."""
    entries = _entries(free, card_of)
    lead = next((e for e in entries if e["name"] == name), None)
    if lead is None or not may_lead(lead["card"]):
        return None
    fit = [e for e in entries if e is not lead and fits(e["card"], lead["identity"])]
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


def candidates(free, card_of, may_lead, categories, partners=lambda card: []):
    """[{"name", "colours" (WUBRG letters), "share", "covered", "of", "categories": [{"category", "label",
    "target", "about", "count" (None: not counted), "short" (below the target, for a category that makes
    the coverage), "in_coverage", "measure"}], "short" (labels of the coverage categories below target),
    "cards" (free non-land cards that fit), "lands" (free non-basic lands that fit), "partner" (the
    candidate's partner abilities in words)}], best first.

    free is {name: copies free} (pool.free_copies), card_of(name) the card or None (skipped),
    may_lead(card) whether it may be a commander alone, categories role_targets.CATEGORIES and
    partners(card) its partner abilities in words."""
    entries = _entries(free, card_of)
    counted = [c for c in categories if c.get("roles")]
    of = sum(c["target"] for c in counted)
    out = []
    for lead in entries:
        if not may_lead(lead["card"]):
            continue
        identity = lead["identity"]
        fit = [e for e in entries if e is not lead and fits(e["card"], identity)]
        parts, covered = [], 0
        for c in categories:
            count = _category_count(c, fit) if _counts(c) else None
            in_coverage = bool(c.get("roles"))
            if in_coverage:
                covered += min(count, c["target"])
            parts.append({"category": c["category"], "label": c["label"], "target": c["target"],
                          "about": c.get("about", False), "count": count,
                          "short": in_coverage and count < c["target"], "in_coverage": in_coverage,
                          "measure": c.get("measure")})
        out.append({"name": lead["name"], "colours": [x for x in "WUBRG" if x in identity],
                    "share": round(covered / of, 4) if of else None, "covered": covered, "of": of,
                    "categories": parts, "short": [p["label"] for p in parts if p["short"]],
                    "cards": sum(1 for e in fit if not e["land"]), "lands": sum(1 for e in fit if e["land"]),
                    "partner": list(partners(lead["card"]))})
    out.sort(key=lambda c: (-(c["share"] or 0), -c["cards"], c["name"].casefold()))
    return out
