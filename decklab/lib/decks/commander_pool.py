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
"""
from .role_pool import fits

LIMIT = 50              # candidates answered by default


def _is_land(card):
    front = (card.get("type_line") or "").split(" // ")[0].split("—")[0]
    return "Land" in front.split()


def _counts(category):
    return category.get("roles") or category.get("lands")


def _category_count(category, entries):
    if category.get("lands"):
        return sum(1 for e in entries if e["land"])
    roles, never = set(category["roles"]), set(category.get("except") or ())
    return sum(1 for e in entries if e["roles"] & roles and not e["roles"] & never)


def candidates(free, card_of, may_lead, categories, partners=lambda card: []):
    """[{"name", "colours" (WUBRG letters), "share", "covered", "of", "categories": [{"category", "label",
    "target", "about", "count" (None: not counted), "short" (below the target, for a category that makes
    the coverage), "in_coverage", "measure"}], "short" (labels of the coverage categories below target),
    "cards" (free non-land cards that fit), "lands" (free non-basic lands that fit), "partner" (the
    candidate's partner abilities in words)}], best first.

    free is {name: copies free} (pool.free_copies), card_of(name) the card or None (skipped),
    may_lead(card) whether it may be a commander alone, categories role_targets.CATEGORIES and
    partners(card) its partner abilities in words."""
    entries = []
    for name, spare in free.items():
        if spare <= 0:
            continue
        card = card_of(name)
        if card is None or card.get("commander_legality") != "legal":
            continue
        entries.append({"name": name, "card": card, "identity": frozenset(card.get("color_identity") or ()),
                        "roles": set(card.get("roles") or ()), "land": _is_land(card)})
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
