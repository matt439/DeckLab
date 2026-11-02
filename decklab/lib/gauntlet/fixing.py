"""Making a gauntlet deck playable and measuring it (design section 3): names checked against
Scryfall's, an average deck fixed to exactly 100 singleton cards, its Commander Bracket, and
whether Forge's AI can play it.

Fixing an average Commander deck, in order, every change recorded in "fixes":
    1. the commander(s) from the deck's commander field (a copy among the 99 goes);
    2. cards outside the commander's colour identity, or not legal in Commander, dropped;
    3. duplicate non-basics reduced to 1, unless the card's text allows more;
    4. over 100: basics removed down to a LAND_FLOOR-land floor, then nonlands cut from the end
       of the list (the least-included cards; EDHREC lists them in its own order);
    5. under 100: basics added, split by the colour pips of the nonland cards within the
       identity (Wastes for a colourless identity).

The Bracket is stats.deck_rules' minimum (Game Changers from Scryfall's flag, mass land denial,
extra turns and Commander Spellbook's two-card combos, through stats/commander.min_bracket). A
core deck or precon measured above Bracket 2 is re-tiered to "upgraded" (its bracket says which).

AI screening (forge/ai.ai_limits): a deck is excluded when its commander is unplayable, any card
is unknown to Forge, or more than MAX_UNPLAYABLE copies are unplayable; otherwise only a
problem is noted.
"""
import re
from collections import Counter

from decklab.lib import cards

SIZE = 100
LAND_FLOOR = 33
MAX_UNPLAYABLE = 3
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest", "C": "Wastes"}
WUBRG = "WUBRG"
SYMBOL_RE = re.compile(r"\{([^}]+)\}")
TIER_FOR_BRACKET = {3: "upgraded", 4: "upgraded"}     # the highest Commander tier is upgraded


# ------------------------------------------------------------ names

def resolve(lines):
    """([[qty, exact Scryfall name]], [names that aren't Scryfall cards]) of [[qty, name]]."""
    found, unknown = [], []
    for qty, name in lines:
        exact = cards.resolve(name)
        if exact is None:
            unknown.append(name)
        else:
            found.append([qty, exact])
    return found, unknown


def _card(name):
    return cards.card(name) or {}


def _type_words(card):
    return set(card.get("type_line", "").split(" — ")[0].split())


def is_basic(card):
    return {"Basic", "Land"} <= _type_words(card)


def is_land(card):
    return "Land" in _type_words(card)


def identity_of(names):
    """The colour identity of the commanders, as a set of letters."""
    out = set()
    for name in names:
        out.update(_card(name).get("color_identity", []))
    return out


# ------------------------------------------------------------ fixing to 100

def _copies_allowed(card):
    """How many copies the card's text allows (None: any number), else 1."""
    from decklab.lib.stats.commander import _copies_allowed
    return _copies_allowed({"oracle_text": card.get("oracle_text", "")})


def _merge(lines):
    """[[qty, name]] with repeated names added up where each first appears."""
    merged = {}
    for qty, name in lines:
        if name in merged:
            merged[name][0] += qty
        else:
            merged[name] = [qty, name]
    return list(merged.values())


def _drop_illegal(main, identity, fixes):
    kept = []
    for qty, name in main:
        card = _card(name)
        outside = set(card.get("color_identity", [])) - identity
        legality = card.get("commander_legality", "not_legal")
        if outside:
            fixes.append(f"Dropped {qty} {name}: outside the commander's colour identity.")
        elif legality != "legal":
            fixes.append(f"Dropped {qty} {name}: {legality.replace('_', ' ')} in Commander.")
        else:
            kept.append([qty, name])
    return kept


def _singleton(main, fixes):
    for line in main:
        qty, name = line
        card = _card(name)
        if qty < 2 or is_basic(card):
            continue
        limit = _copies_allowed(card)
        if limit is not None and qty > limit:
            fixes.append(f"{name}: {qty} copies reduced to {limit}.")
            line[0] = limit
    return main


def _total(commanders, main):
    return len(commanders) + sum(q for q, _ in main)


def _cut(commanders, main, fixes):
    """Over SIZE: basics down to the land floor, then nonlands from the end, then anything."""
    over = _total(commanders, main) - SIZE
    lands = sum(q for q, n in main if is_land(_card(n))) + sum(1 for n in commanders if is_land(_card(n)))
    removed = Counter()
    while over > 0 and lands > LAND_FLOOR:
        basics = [line for line in main if line[0] > 0 and is_basic(_card(line[1]))]
        if not basics:
            break
        line = max(basics, key=lambda x: x[0])
        line[0] -= 1
        removed[line[1]] += 1
        over, lands = over - 1, lands - 1
    for name, n in removed.items():
        fixes.append(f"Removed {n} {name} (over 100 cards; {LAND_FLOOR} lands kept at least).")
    for nonland_only in (True, False):
        for line in reversed(main):
            if over <= 0:
                break
            if line[0] > 0 and (not nonland_only or not is_land(_card(line[1]))):
                n = min(line[0], over)
                fixes.append(f"Cut {n} {line[1]} (over 100 cards; from the end of the list).")
                over -= n
                line[0] -= n
    main[:] = [line for line in main if line[0] > 0]


def _pips(main, identity):
    """Colour pips of the nonland cards' mana costs, by colour within the identity."""
    pips = Counter()
    for qty, name in main:
        card = _card(name)
        if is_land(card):
            continue
        for symbol in SYMBOL_RE.findall(card.get("mana_cost", "")):
            for letter in set(symbol.upper()) & identity & set(WUBRG):
                pips[letter] += qty
    return pips


def _split(n, weights):
    """n divided among weights' keys by their weights (largest remainder, WUBRG order on a tie)."""
    total = sum(weights.values())
    shares = {c: n * w / total for c, w in weights.items()}
    out = {c: int(s) for c, s in shares.items()}
    left = n - sum(out.values())
    for c in sorted(shares, key=lambda c: (-(shares[c] - out[c]), WUBRG.find(c)))[:left]:
        out[c] += 1
    return out


def _fill(commanders, main, fixes):
    """Under SIZE: basics added by the nonland pips (evenly with none; Wastes when colourless)."""
    need = SIZE - _total(commanders, main)
    if need <= 0:
        return
    identity = identity_of(commanders) & set(WUBRG)
    if not identity:
        split = {"C": need}
    else:
        pips = _pips(main, identity)
        split = _split(need, {c: pips[c] for c in identity if pips[c]} or {c: 1 for c in identity})
    by_name = {line[1]: line for line in main}
    for colour in sorted(split, key=lambda c: "WUBRGC".find(c)):
        n, name = split[colour], BASICS[colour]
        if not n:
            continue
        if name in by_name:
            by_name[name][0] += n
        else:
            by_name[name] = [n, name]
            main.append(by_name[name])
        fixes.append(f"Added {n} {name} (under 100 cards).")


def fix_commander(commanders, main):
    """An average deck or precon made a legal 100-card Commander list. commanders and main are
    exact Scryfall names ([names], [[qty, name]]). Returns {"cards": {"Commander": [[1, name]],
    "Main": [[qty, name]]}, "fixes": [str], "problems": [str], "playable": bool}."""
    fixes, problems = [], []
    commanders = list(dict.fromkeys(commanders))
    for name in commanders:
        legality = _card(name).get("commander_legality", "not_legal")
        if legality != "legal":
            problems.append(f"The commander {name} is {legality.replace('_', ' ')} in Commander.")
    main = _merge(main)
    in_main = [line for line in main if line[1] in commanders]
    for line in in_main:
        fixes.append(f"Dropped {line[0]} {line[1]} from the 99: it's the commander.")
    main = [line for line in main if line[1] not in commanders]
    identity = identity_of(commanders)
    main = _singleton(_drop_illegal(main, identity, fixes), fixes)
    if _total(commanders, main) > SIZE:
        _cut(commanders, main, fixes)
    _fill(commanders, main, fixes)
    listed = {"Commander": [[1, n] for n in commanders], "Main": [list(line) for line in main]}
    return {"cards": listed, "fixes": fixes, "problems": problems,
            "playable": not problems and _total(commanders, main) == SIZE}


# ------------------------------------------------------------ brackets

def _sections(listed):
    """decks.load_deck-style sections of {"Commander": [[qty, name]], "Main": [...]}."""
    from decklab.lib import decks
    return {"Commander": [decks.DeckLine(q, n) for q, n in listed.get("Commander", [])],
            "Deck": [decks.DeckLine(q, n) for q, n in listed.get("Main", [])]}


def bracket(listed):
    """({"label", "minimum", "game_changers": [names]}, [reasons], [warnings]) of a Commander list:
    stats.deck_rules' minimum bracket."""
    from decklab.lib import stats
    rules = stats.deck_rules(_sections(listed), "commander")
    found = rules["commander"]["bracket"]
    return ({"label": found["label"], "minimum": found["minimum"],
             "game_changers": [c["name"] for c in found["game_changers"]]},
            list(found["reasons"]), list(rules["warnings"]))


def retier(tier, measured):
    """(tier, fix or None): a core deck or precon whose minimum bracket is above 2 moves to the
    tier of its measured bracket (upgraded, the highest; its bracket still says 4), with the reason."""
    minimum = measured["minimum"]
    if tier in ("core", "precon") and minimum > 2:
        new = TIER_FOR_BRACKET[minimum]
        return new, f"Re-tiered from {tier} to {new}: its minimum bracket is {minimum} ({measured['label']})."
    return tier, None


# ------------------------------------------------------------ AI screening

def _forge_limits(sections, kind):
    """forge.ai.ai_limits, with "screened" False when Forge's card scripts can't be read: ai_limits
    then leaves "cannot_play" and "unknown" empty for want of them, saying so only in "problem"."""
    from decklab.lib.forge import ai, install
    from decklab.lib.forge.common import ForgeError
    found = dict(ai.ai_limits(sections, kind))
    try:
        install.script_index()
    except ForgeError:
        found["screened"] = False
    return found


def screen(listed, kind, limits=None):
    """(excluded reason or None, [problems]) of Forge's AI limits on a list. limits stands in for
    _forge_limits (the tests' fake script table). A list that couldn't be screened (no card
    scripts) is excluded: whether Forge knows its cards isn't known."""
    if limits is None:
        limits = _forge_limits
    found = limits(_sections(listed), kind)
    problems = []
    if found.get("problem"):
        problems.append(f"AI screening: {found['problem']}")
    if found.get("screened") is False:
        return "Not screened: Forge's card scripts couldn't be read, so whether its AI can play it isn't known.",             problems
    if found.get("commander_unplayable"):
        return "Forge's AI can't play its commander.", problems
    unknown = found.get("unknown") or []
    if unknown:
        names = ", ".join(sorted({u["name"] for u in unknown}))
        return f"Forge doesn't know {len(unknown)} of its cards: {names}.", problems
    cannot = found.get("cannot_play") or []
    copies = sum(c.get("qty", 1) for c in cannot)
    if copies > MAX_UNPLAYABLE:
        return f"Forge's AI can't play {copies} of its cards (more than {MAX_UNPLAYABLE}).", problems
    if cannot:
        problems.append("Forge's AI can't play " + ", ".join(sorted({c["name"] for c in cannot})) + ".")
    pilot = found.get("pilot") or {}
    if pilot.get("poor"):
        problems.append(f"Forge pilots it poorly ({pilot.get('why')}).")
    return None, problems
