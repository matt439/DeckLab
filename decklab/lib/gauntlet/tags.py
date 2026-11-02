"""Tagging a gauntlet deck: its colours, its numbers and its style (design section 4).

From code:

    from decklab.lib.gauntlet import tags
    tags.tag("commander", {"Commander": [[1, name]], "Main": [[99, ...]]}, themes=page_themes)
    # {"identity": "BG", "colours": "BG",
    #  "style": {"primary": "midrange", "tags": ["tokens"], "themes": ["Sacrifice"]},
    #  "metrics": {...}}

Every card is looked up in the card index (cards.resolve and cards.card) for its colour
identity, mana cost, mana value, type line, rules text and roles (Scryfall's oracle tags,
card_index.ROLE_TAGS). A name the index doesn't know is counted in metrics["unknown"] and
otherwise left out. Two-card combos come from Commander Spellbook's list (combos.find), as
the Commander checks read it; without the list, metrics["two_card_combos"] is None.

The primary style is the first rule of RULES that matches, and its thresholds are
approximate: a quick reading of the list, never a claim about how the deck plays. EDHREC's
themes for the commander only add tags and stay beside the deck, so where they disagree
with the heuristic the disagreement shows.
"""
import re
from collections import Counter

from decklab.lib import cards, combos
from decklab.lib.stats import commander as stats_commander

STYLES = ("aggro", "midrange", "control", "combo", "ramp")
WUBRG = "WUBRG"

# The thresholds of each format: approximate, set by eye from the design, not measured.
# Shares are of the nonland cards (copies counted), except tribal_share, which is of the
# creatures.
RULES = {
    "commander": {
        "combo_tutors": 4,          # combo: a game-ending two-card combo, or this many tutors
        "aggro_mean_mv": 3.0,       # aggro: mean mana value at most this ...
        "aggro_creatures": 0.45,    # ... creatures at least this share ...
        "aggro_low_curve": 0.50,    # ... and mana value 2 or less at least this share
        "control_creatures": 0.25,  # control: creatures at most this share ...
        "control_interaction": 0.25,    # ... and interaction at least this share
        "ramp_cards": 10,           # ramp: this many ramp cards ...
        "ramp_mean_mv": 3.5,        # ... and mean mana value at least this
        "tribal_share": 0.35,       # tribal:<type>: the largest subtype's share of creatures ...
        "tribal_cards": 8,          # ... and at least this many of them
        "spells_share": 0.40,       # spells: instants and sorceries
        "tokens_share": 0.20,       # tokens: cards whose text creates a token
        "lifegain_share": 0.20,     # lifegain: the lifegain role
        "theme_share": 0.25,        # an EDHREC theme held by this share of the commander's decks
    },
    "constructed": {
        "combo_tutors": 4,
        "aggro_mean_mv": 2.6,
        "aggro_creatures": 0.45,
        "aggro_low_curve": 0.50,
        "control_creatures": 0.25,
        "control_interaction": 0.25,
        "ramp_cards": 6,
        "ramp_mean_mv": 3.5,
        "tribal_share": 0.35,
        "tribal_cards": 12,
        "spells_share": 0.40,
        "tokens_share": 0.20,
        "lifegain_share": 0.20,
        "theme_share": 0.25,
    },
}

# EDHREC theme names (lowercase) that become a tag. A theme naming a creature type the deck's
# creatures have ("Elves", "Dragons") becomes tribal:<type> without being listed here.
THEME_TAGS = {
    "tokens": "tokens",
    "spellslinger": "spells",
    "spells": "spells",
    "voltron": "voltron",
    "aristocrats": "aristocrats",
    "lifegain": "lifegain",
    "life gain": "lifegain",
}

INTERACTION_ROLES = ("removal", "counterspell", "board wipe")
_PIP = re.compile(r"\{([^}]*)\}")
_CREATES_TOKEN = re.compile(r"\bcreates?\b[^.]*\btokens?\b", re.IGNORECASE)
_TUTOR = re.compile(r"search(?:es)? (?:your|their) library for ([^.]*?)\bcards?\b", re.IGNORECASE)


def _ordered(letters):
    """Colour letters in WUBRG order, as one string ("GW" -> "WG")."""
    return "".join(c for c in WUBRG if c in letters)


def _lookup(name):
    """The card index entry for a name, or None when it isn't a card."""
    exact = cards.resolve(name)
    return None if exact is None else cards.card(exact)


def _front_type(card):
    return card.get("type_line", "").split(" // ")[0]


def _is_land(card):
    return "Land" in _front_type(card).split("—")[0].split()


def _is_creature(card):
    return "Creature" in _front_type(card).split("—")[0].split()


def _subtypes(card):
    """The creature types of a creature's front face."""
    head, _, tail = _front_type(card).partition("—")
    return tail.split() if "Creature" in head.split() else []


def _cost_colours(card):
    """The colour letters in a card's mana cost (every face; hybrid and Phyrexian count)."""
    found = set()
    for pip in _PIP.findall(card.get("mana_cost", "")):
        found.update(c for c in pip.upper() if c in WUBRG)
    return found


def _is_tutor(card):
    """Text that searches the library for a card that isn't a land."""
    return any("land" not in m.group(1).lower() for m in _TUTOR.finditer(card.get("oracle_text", "")))


def _entries(listed):
    """[(qty, name, card or None)] of a section's [[qty, name]] rows."""
    out = []
    for qty, name in listed or ():
        out.append((int(qty), name, _lookup(name)))
    return out


def _two_card_combos(commander, deck):
    """How many standalone game-ending two-card combos the deck holds (those that raise the
    bracket floor), or None when Spellbook's list can't be read."""
    try:
        found = combos.find([c.get("oracle_id") for c in commander], [c.get("oracle_id") for c in deck],
                            stats_commander.COMBO_FILE)
    except (combos.ComboListError, OSError):
        return None
    return sum(1 for combo in found["matches"] if combos.bracket_floor(combo) > 1)


def _share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def _metrics(kind, sections):
    """The deck's numbers (see the module docstring), from its looked-up sections."""
    known = [(q, c) for rows in sections.values() for q, _, c in rows if c is not None]
    unknown = sum(q for rows in sections.values() for q, _, c in rows if c is None)
    nonland = [(q, c) for q, c in known if not _is_land(c)]
    total = sum(q for q, _ in nonland)
    creatures = [(q, c) for q, c in nonland if _is_creature(c)]
    creature_count = sum(q for q, _ in creatures)
    subtypes = Counter()
    for q, c in creatures:
        for sub in set(_subtypes(c)):
            subtypes[sub] += q
    top_type, top_count = (subtypes.most_common(1) or [(None, 0)])[0]

    def count(test):
        return sum(q for q, c in nonland if test(c))

    def has_role(c, names):
        return bool(set(c.get("roles", ())) & set(names))

    mean_mv = sum(q * float(c.get("cmc") or 0) for q, c in nonland) / total if total else 0.0
    interaction = count(lambda c: has_role(c, INTERACTION_ROLES))
    spells = count(lambda c: {"Instant", "Sorcery"} & set(_front_type(c).split()))
    commander = [c for _, _, c in sections.get("Commander", []) if c is not None]
    deck = [c for _, _, c in sections.get("Main", []) if c is not None]
    return {
        "cards": sum(q for q, _ in known) + unknown,
        "unknown": unknown,
        "nonland": total,
        "creatures": creature_count,
        "creature_share": _share(creature_count, total),
        "mean_mv": round(mean_mv, 2),
        "low_curve_share": _share(count(lambda c: float(c.get("cmc") or 0) <= 2), total),
        "interaction": interaction,
        "interaction_share": _share(interaction, total),
        "ramp": count(lambda c: has_role(c, ("ramp",))),
        "spells": spells,
        "spells_share": _share(spells, total),
        "token_makers": count(lambda c: bool(_CREATES_TOKEN.search(c.get("oracle_text", "")))),
        "lifegain": count(lambda c: has_role(c, ("lifegain",))),
        "tutors": count(_is_tutor),
        "top_subtype": top_type,
        "top_subtype_count": top_count,
        "top_subtype_share": _share(top_count, creature_count),
        "two_card_combos": _two_card_combos(commander, deck),
    }


def primary_style(kind, metrics):
    """The first style of RULES[kind] that the metrics match; midrange when none does."""
    rule = RULES[kind]
    if (metrics["two_card_combos"] or 0) > 0 or metrics["tutors"] >= rule["combo_tutors"]:
        return "combo"
    if (metrics["mean_mv"] <= rule["aggro_mean_mv"] and metrics["creature_share"] >= rule["aggro_creatures"]
            and metrics["low_curve_share"] >= rule["aggro_low_curve"]):
        return "aggro"
    if (metrics["creature_share"] <= rule["control_creatures"]
            and metrics["interaction_share"] >= rule["control_interaction"]):
        return "control"
    if metrics["ramp"] >= rule["ramp_cards"] and metrics["mean_mv"] >= rule["ramp_mean_mv"]:
        return "ramp"
    return "midrange"


def _heuristic_tags(kind, metrics):
    rule = RULES[kind]
    out = []
    if (metrics["top_subtype"] and metrics["top_subtype_share"] >= rule["tribal_share"]
            and metrics["top_subtype_count"] >= rule["tribal_cards"]):
        out.append("tribal:" + metrics["top_subtype"].lower())
    if _share(metrics["token_makers"], metrics["nonland"]) >= rule["tokens_share"]:
        out.append("tokens")
    if metrics["spells_share"] >= rule["spells_share"]:
        out.append("spells")
    if _share(metrics["lifegain"], metrics["nonland"]) >= rule["lifegain_share"]:
        out.append("lifegain")
    return out


def _singular(word):
    """A plural creature type's singular, roughly ("Elves" -> "Elf", "Zombies" -> "Zombie")."""
    lower = word.lower()
    if lower.endswith("ves"):
        return [lower[:-3] + "f", lower[:-1]]
    if lower.endswith("ies"):
        return [lower[:-3] + "y", lower[:-1]]
    if lower.endswith("es"):
        return [lower[:-2], lower[:-1]]
    return [lower[:-1], lower] if lower.endswith("s") else [lower]


def _theme_names(kind, themes, decks):
    """The names of the themes held by at least RULES[kind]["theme_share"] of the commander's
    decks. A theme is a name (already chosen) or EDHREC's {"name", "decks"}, or with "share";
    with no deck count to compare it's kept."""
    out = []
    for theme in themes or ():
        if isinstance(theme, str):
            name, share = theme, None
        elif isinstance(theme, dict) and isinstance(theme.get("name"), str):
            name, share = theme["name"], theme.get("share")
            if share is None and decks and isinstance(theme.get("decks"), int):
                share = theme["decks"] / decks
        else:
            continue
        if name.strip() and (share is None or share >= RULES[kind]["theme_share"]) and name not in out:
            out.append(name.strip())
    return out


def _theme_tags(names, subtypes):
    """The tags EDHREC theme names add: THEME_TAGS, and tribal:<type> for a creature type the
    deck's creatures have."""
    out = []
    for name in names:
        lower = name.lower()
        if lower in THEME_TAGS:
            out.append(THEME_TAGS[lower])
            continue
        match = next((s for s in _singular(name) if s in subtypes), None)
        if match:
            out.append("tribal:" + match)
    return out


def tag(kind, cards_by_section, themes=(), decks=None):
    """The identity, colours, style and metrics of a gauntlet deck.

    kind is "commander" or "constructed"; cards_by_section is the catalogue entry's "cards"
    ({"Commander": [[qty, name]], "Main": [...]}); themes are the commander's EDHREC themes
    and decks, when given, the commander's deck count they're compared with."""
    if kind not in RULES:
        raise ValueError(f"Unknown gauntlet format {kind!r}")
    sections = {key: _entries(rows) for key, rows in (cards_by_section or {}).items()}
    known = [c for rows in sections.values() for _, _, c in rows if c is not None]
    commanders = [c for _, _, c in sections.get("Commander", []) if c is not None]
    source = commanders if kind == "commander" and commanders else known
    identity = _ordered({x for c in source for x in c.get("color_identity", ())})
    colours = _ordered({x for c in known if not _is_land(c) for x in _cost_colours(c)})
    metrics = _metrics(kind, sections)
    subtypes = {s.lower() for c in known if _is_creature(c) for s in _subtypes(c)}
    theme_names = _theme_names(kind, themes, decks)
    found = _heuristic_tags(kind, metrics) + _theme_tags(theme_names, subtypes)
    return {"identity": identity, "colours": colours,
            "style": {"primary": primary_style(kind, metrics), "tags": list(dict.fromkeys(found)),
                      "themes": theme_names},
            "metrics": metrics}
