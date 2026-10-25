"""Card reading for the goldfish package: each Scryfall card, read through
the stats package's helpers (lib/stats/cardtext.py), becomes plain data the
game loop (engine.py) plays with: how a land enters, the mana it and the
deck's mana sources make, cost options (hybrid, {2/W}, Phyrexian, X), land
searches, ramp, and the special-rule and not-modelled notes. compile_deck()
builds the whole deck's model.
"""
import itertools
import re
from collections import Counter

from decklab.lib import stats

from .common import (ANY_MANA, BITS, IF_BASICS, IF_EARLY, IF_FEW, IF_MANY, IF_MANY_TYPE, IF_MULTIPLAYER, IF_REVEAL,
                     IF_TYPE, LAND_TYPE_BITS, LAND_TYPE_RE, POP, TAPPED, UNTAPPED, _colour_bits, _colours_text, _mask)

KINDS = stats.KINDS
MIN_LIBRARY = 8             # a hand of 7 and a card to draw

# Card text that decides how a land enters and what a card does.
PAY_LIFE_RE = re.compile(r"you may pay \d+ life")
CHECK_RE = re.compile(rf"unless you control an? {LAND_TYPE_RE}(?:,? or an? {LAND_TYPE_RE})?")
BASICS_RE = re.compile(r"unless you control (\w+) or more basic lands")
FEW_LANDS_RE = re.compile(r"unless you control (\w+) or fewer other lands")
MANY_LANDS_RE = re.compile(r"unless you control (\w+) or more other lands")
MANY_TYPE_RE = re.compile(rf"unless you control (\w+) or more other {LAND_TYPE_RE}s")
REVEAL_RE = re.compile(rf"you may reveal an? {LAND_TYPE_RE}(?:,? or {LAND_TYPE_RE})? card from your hand")
EARLY_RE = re.compile(r"unless it's your first, second, or third turn")
MIN_LANDS_RE = re.compile(r"activate only if you control (\w+) or more lands")
AURA_RAMP_RE = re.compile(r"enchanted land has \"\{t\}: add|whenever enchanted land is tapped for mana, "
                          r"its controller adds an additional")
X_NEEDS_ONE_RE = re.compile(r"deals x damage|loses x life|gains? x life|draws? x cards|x \+1/\+1 counters"
                            r"|create x |x target|mill x|return x ")
OPPONENT_SEARCH_RE = re.compile(r"if an opponent controls more lands|an opponent controls more lands")
COST_REDUCTION_RE = re.compile(r"costs? \{[^}]+\} less|costs? \{x\} less|costs? x less")
TREASURE_RE = re.compile(r"create[^.]*\btreasure token")
SPEND_LIMIT_RE = re.compile(r"spend this mana only")
NO_UNTAP_RE = re.compile(r"doesn't untap during your untap step")
# River of Tears: "{T}: Add {U}. If you played a land this turn, add {B} instead."
PLAYED_LAND_INSTEAD_RE = re.compile(r"if you played a land this turn, add ([^.]*) instead")
# Fabled Passage: the land it finds enters tapped, then untaps with enough lands.
UNTAP_FOUND_RE = re.compile(r"then if you control (\w+) or more lands, untap that land")
# Bounce lands (Azorius Chancery; Coral Atoll returns an untapped Island) and
# Lotus Field, which sacrifices two lands, when they enter.
RETURN_LAND_RE = re.compile(rf"when this land enters, (?:sacrifice it unless you )?return an? (untapped )?"
                            rf"(land|{LAND_TYPE_RE[1:-1]}) you control to its owner's hand")
SACRIFICE_LANDS_RE = re.compile(r"when this land enters, sacrifice (\w+) (?:untapped )?lands")
RETURN_OWN_LANDS_RE = re.compile(r"return (?:\w+ )?lands? you control to (?:its|their) owner's hand")    # Khalni Gem
# A triggered ability at the start of a line, after any ability word ("Landfall — "):
# (when / whenever / at, its condition).
TRIGGER_RE = re.compile(r"(?:[^—\n:]*— )?(when|whenever|at) ([^,\n]*),")
# Ways of paying for a spell that aren't modelled (the full mana cost is paid), by Scryfall keyword.
COST_KEYWORDS = ("Affinity", "Convoke", "Delve", "Emerge", "Improvise")
FROM_TOP_RE = re.compile(r"(?:cast|play) [^.]*from the top of your library")


# ============================================================ reading cards

def _number(word):
    return int(word) if word.isdigit() else stats.NUMBER_WORDS.get(word, 1)


def _type_bits(words):
    """The mask of basic land types among words ("forest", "Plains", "swamps")."""
    m = 0
    for w in words:
        w = (w or "").lower()
        m |= LAND_TYPE_BITS.get(w, 0) or LAND_TYPE_BITS.get(w[:-1], 0)
    return m


def _enter_rule(text):
    """[code, a, b]: how a land with this text enters (the codes in common.py)."""
    t = stats.REMINDER_RE.sub("", text.lower())
    if not stats.ENTERS_TAPPED_RE.search(t):
        return [UNTAPPED, 0, 0]
    if PAY_LIFE_RE.search(t):
        return [UNTAPPED, 0, 0]         # a shock land: pay 2 life
    m = CHECK_RE.search(t)
    if m:
        return [IF_TYPE, _type_bits(m.groups()), 0]
    m = BASICS_RE.search(t)
    if m:
        return [IF_BASICS, _number(m.group(1)), 0]
    m = FEW_LANDS_RE.search(t)
    if m:
        return [IF_FEW, _number(m.group(1)), 0]
    m = MANY_TYPE_RE.search(t)
    if m:
        return [IF_MANY_TYPE, _number(m.group(1)), _type_bits([m.group(2)])]
    m = MANY_LANDS_RE.search(t)
    if m:
        return [IF_MANY, _number(m.group(1)), 0]
    m = REVEAL_RE.search(t)
    if m:
        return [IF_REVEAL, _type_bits(m.groups()), 0]
    if EARLY_RE.search(t):
        return [IF_EARLY, 3, 0]
    if stats.MULTIPLAYER_UNTAPPED_RE.search(t):
        return [IF_MULTIPLAYER, 0, 0]
    return [UNTAPPED if stats.untapped_on_turn_one(text) else TAPPED, 0, 0]


def _enter_text(rule):
    code, a, b = rule
    types = " or ".join(t.capitalize() for t, bit in LAND_TYPE_BITS.items() if a & bit)
    return {
        UNTAPPED: None,
        TAPPED: "always enters tapped",
        IF_TYPE: f"enters tapped unless you control a {types}",
        IF_BASICS: f"enters tapped unless you control {a} or more basic lands",
        IF_FEW: f"enters tapped unless you control {a} or fewer other lands",
        IF_MANY: f"enters tapped unless you control {a} or more other lands",
        IF_MANY_TYPE: f"enters tapped unless you control {a} or more other "
                      + " or ".join(t.capitalize() + "s" for t, bit in LAND_TYPE_BITS.items() if b & bit),
        IF_REVEAL: f"enters tapped unless you have a {types} card in hand to reveal",
        IF_EARLY: "enters untapped on your first three turns",
        IF_MULTIPLAYER: "enters untapped only in multiplayer games",
    }[code]


def _clause_colours(clause, produced, identity):
    """(mask, chosen) for what one "Add ..." clause makes: mask every colour
    it can make; chosen the ones of which it makes just one, chosen as the
    card enters ("one mana of the chosen color"), or 0. produced is the
    card's produced_mana as a mask."""
    mask = 0
    for s in stats.SYMBOL_RE.findall(clause):
        mask |= BITS.get(s.upper(), 0)
    chosen = 0
    if "commander's color identity" in clause:
        mask |= produced & identity
    elif "chosen color" in clause:
        chosen = produced & ~mask
        if identity and chosen & identity:
            chosen &= identity          # a Commander deck names a colour it can use
        mask |= chosen
    elif not mask or ("any" in clause and "combination of {" not in clause) or "that color" in clause:
        mask |= produced
    if POP[chosen] == 1:
        chosen = 0                      # only one colour to choose: it simply makes that one
    return mask, chosen


def _mana_output(text, produced, identity, card=None):
    """(mask, amount, cost, symbols, notes, chosen, line) for a card's own
    "{T}: Add" abilities in text (lowercased, reminder text removed;
    stats.mana_abilities). One whose cost asks for more than {T}, mana and
    life (Lotus Petal's sacrifice, a counter to remove) isn't used. mask is
    the colours the used ones make and chosen those of which one is chosen
    as the card enters (Heraldic Banner), or 0; River of Tears' "if you
    played a land this turn, add {B} instead" puts {B} in mask too (either
    colour, with a note). amount, cost (the mana its
    cost asks for besides {T}: a Signet's "{1}, {T}: Add {W}{B}" is 2 mana
    for a cost of 1), symbols ("{1}") and line (the ability, for "Activate
    only if") are the first used ability's. card (a nonland card) gives its
    power, for "X mana, where X is the greatest power among creatures you
    control", and its colours, for "For each color among permanents you
    control, add one mana of that color" (itself among them)."""
    notes = []
    mask = chosen = 0
    first = None
    abilities = stats.mana_abilities(text)
    produced = _mask(produced)
    if not abilities:
        # A basic land or a dual whose mana ability is only reminder text ("({T}: Add {R} or {G}.)").
        return produced, 1 if produced else 0, 0, "", notes, 0, ""
    for cost_text, clause, trouble, ability in abilities:
        if trouble:
            continue
        m, c = _clause_colours(clause, produced, identity)
        if "for each color among permanents" in ability and card and _mask(card.get("colors")) & m:
            m &= _mask(card.get("colors"))
        instead = PLAYED_LAND_INSTEAD_RE.search(ability)
        if instead:
            other = _clause_colours(instead.group(1), produced, identity)[0]
            if other & ~m:
                m |= other
                notes.append("which colour it makes depends on whether you played a land that turn, which isn't "
                             "modelled: it counts as either")
        mask |= m
        chosen |= c
        if first is None:
            first = (cost_text, clause, ability)
    troubles = [trouble for _, _, trouble, _ in abilities if trouble]
    if troubles:
        notes.append(f"its mana ability that also costs \"{troubles[0]}\" isn't modelled"
                     + ("" if first else ", so it makes no mana"))
    if first is None:
        return 0, 0, 0, "", notes, 0, ""
    cost_text, clause, line = first
    amount = 1
    cost = min(o[3] for o in _cost_options(cost_text, 0))
    symbols = "".join(f"{{{s.upper()}}}" for s in stats.SYMBOL_RE.findall(cost_text) if s not in ("t", "q"))
    if "commander's color identity" in clause and not identity:
        notes.append("makes no mana: there's no commander, so no colour identity")
    if "charge counter" in clause:
        amount = 0
        notes.append("its mana needs charge counters, which aren't modelled, so it makes none")
    elif "for each" in line:
        notes.append("its 'for each' mana counts as one mana")
    elif "where x is the greatest power among creatures you control" in clause and card \
            and (card.get("power") or "").isdigit() and int(card["power"]) > 1:
        amount = int(card["power"])
        notes.append(f"its X mana counts as {amount}, its own power")
    elif "where x is" in clause:
        notes.append("its X mana counts as one mana")
    elif clause.startswith(("two mana", "three mana")):
        amount = 2 if clause.startswith("two") else 3
    elif " or " not in clause and "mana of" not in clause:
        amount = max(1, len(stats.SYMBOL_RE.findall(clause)))
    if not mask:
        amount = 0
    return mask, amount, cost, symbols, notes, chosen, line


def _chosen_text(mask, chosen):
    """How a source whose colour is chosen as it enters says what it makes."""
    fixed = mask & ~chosen
    made = "".join("{" + c + "}" for c in _colours_text(fixed))
    return (f"{made} or one other colour" if fixed else "one colour") + ", chosen as it enters: the one you need most"


def _x_minimum(card):
    text = card["oracle_text"].lower()
    if X_NEEDS_ONE_RE.search(text) or (stats.is_creature(card) and card.get("toughness") == "0"):
        return 1
    return 0


def _cost_options(cost, x_min):
    """[[mana value, generic, pips, mana paid]]: the ways to pay a mana cost,
    cheapest first. pips is a sorted list of colour masks, one per coloured
    symbol (a hybrid symbol's mask has both colours)."""
    generic = mv = x = 0
    pips, monos = [], []
    for symbol in stats.SYMBOL_RE.findall((cost or "").upper()):
        parts = symbol.split("/")
        if symbol.isdigit():
            generic += int(symbol)
            mv += int(symbol)
        elif symbol in ("X", "Y", "Z"):
            x += 1
        elif symbol in BITS:
            pips.append(BITS[symbol])
            mv += 1
        elif "P" in parts:
            mv += 1                         # Phyrexian: paid with 2 life
        elif len(parts) == 2 and parts[0].isdigit() and parts[1] in BITS:
            monos.append((int(parts[0]), BITS[parts[1]]))
            mv += int(parts[0])
        elif len(parts) >= 2 and all(p in BITS for p in parts):
            pips.append(_mask(parts))
            mv += 1
        elif symbol == "S":
            generic += 1                    # snow: paid as generic
            mv += 1
    generic += x * x_min
    mv += x * x_min
    options = []
    for choice in itertools.product((True, False), repeat=len(monos)):
        g, p = generic, list(pips)
        for (n, bit), colour in zip(monos, choice):
            if colour:
                p.append(bit)
            else:
                g += n
        options.append([mv, g, sorted(p), g + len(p)])
    options.sort(key=lambda o: o[3])
    return options


def _search_spec(target):
    """[count, basic only, land type mask] for a search's target text."""
    count = 2 if re.search(r"\btwo\b", target) else 1
    return [count, "basic" in target, _type_bits(re.findall(LAND_TYPE_RE, target))]


def _type_names(types):
    return " or ".join(t.capitalize() for t, bit in LAND_TYPE_BITS.items() if types & bit)


def _found_text(basic, types):
    """What a land search finds, in words: "a basic land", "an Island or Swamp card"."""
    if types:
        names = _type_names(types)
        return ("a basic " if basic else "an " if names[0] in "AEIOU" else "a ") + names + " card"
    return "a basic land" if basic else "a land"


def _land_model(card, text, identity, special, notes):
    """The "land" part of a card model, for a land or a spell // land card's land face."""
    produced = card.get("produced_mana", [])
    body = stats.REMINDER_RE.sub("", text.lower())
    mask, amount, cost, symbols, mana_notes, chosen, line = _mana_output(body, produced, identity)
    notes.extend(mana_notes)
    land_types = _type_bits(stats.subtypes(card["type_line"]))
    if land_types & ~mask:
        # CR 305.6: a land with a basic land type taps for that type's colour, which Murmuring Bosk (a
        # Forest that also taps for {W} or {B}) has only as reminder text.
        mask |= land_types
        amount = max(amount, 1)
    if cost and amount:
        amount = max(0, amount - cost)
        special.append(f"its mana ability costs {symbols}, so it's counted as {amount} mana")
    if chosen and amount:
        special.append("makes " + _chosen_text(mask, chosen))
    m = MIN_LANDS_RE.search(line)          # the mana ability's own limit (not Cryptic Caves' draw's)
    min_lands = _number(m.group(1)) if m else 0
    if min_lands:
        special.append(f"makes its mana only with {min_lands} or more lands")
    rule = _enter_rule(text)
    fetch = None
    search = stats.land_search(body)
    if search is not None and search[1]:
        search_cost, search_symbols = stats.search_cost(body)
        if search_cost:
            notes.append(f"its search costs {search_symbols}, so it isn't used")
        else:
            # [count, basic only, land types, enters tapped, untaps with this many lands]
            count, basic, types = _search_spec(search[0])
            m = UNTAP_FOUND_RE.search(body)
            untap_at = _number(m.group(1)) if search[2] and m else 0
            fetch = [count, basic, types, search[2], untap_at]
            how = ("enters untapped" if not search[2] else
                   f"enters tapped unless you then control {untap_at} or more lands" if untap_at else "enters tapped")
            special.append(f"sacrificed at once for {_found_text(basic, types)}, which {how}")
    if rule[0] != UNTAPPED and fetch is None:
        special.append(_enter_text(rule))
    # [what, how many, land types, untapped only]: a land that returns
    # ("return") or sacrifices ("sacrifice") other lands when it enters. It's
    # played only with enough other lands, and those go after their mana is
    # used that turn, unless it must return an untapped one (Coral Atoll):
    # that land's mana can't be used first.
    enter = None
    m = RETURN_LAND_RE.search(body)
    if m:
        types = _type_bits([m.group(2)])
        untapped_only = bool(m.group(1))
        enter = ["return", 1, types, untapped_only]
        names = ("untapped " if untapped_only else "") + (_type_names(types) if types else "land")
        which = ("an " if names[0] in "AEIOUu" else "a ") + names
        special.append(f"returns {which} you control to your hand when it enters (your least useful one, "
                       + ("so that land's mana isn't used that turn" if untapped_only else
                          "after using its mana that turn") + "), so it's only played when you have one")
    else:
        m = SACRIFICE_LANDS_RE.search(body)
        if m:
            n = _number(m.group(1))
            enter = ["sacrifice", n, 0, False]
            special.append(f"sacrifices {n} other land{'s' if n != 1 else ''} when it enters (your least useful, "
                           f"after using their mana that turn), so it's only played when you have {n}")
    words = stats.type_words(card["type_line"])
    return [mask, amount, min_lands, rule, land_types, "Basic" in words, stats.untapped_on_turn_one(text), fetch, enter,
            chosen]


def _effect(card, identity, special, notes):
    """What casting a nonland card does to your mana, or None."""
    text = stats.REMINDER_RE.sub("", stats.front_text(card).lower())
    # A mana creature or rock: one with a "{T}: Add" ability of its own (Lotus Petal's, which
    # sacrifices it, is read and noted but makes no mana).
    ability = stats.mana_kind(card) if card.get("produced_mana") and stats.mana_abilities(text) else None
    if ability:
        mask, amount, cost, symbols, mana_notes, chosen, _ = _mana_output(
            text, card.get("produced_mana"), identity, card)
        notes.extend(mana_notes)
        if NO_UNTAP_RE.search(text):
            notes.append("it doesn't untap by itself, so its mana isn't counted")
            return None
        if not amount:
            return None
        if SPEND_LIMIT_RE.search(text):
            notes.append("what its mana can be spent on isn't checked")
        if RETURN_OWN_LANDS_RE.search(text):
            notes.append("the lands it returns to your hand when it enters aren't modelled")
        made = (_chosen_text(mask, chosen) if chosen else
                "".join("{" + c + "}" for c in _colours_text(mask)) or "no mana")
        if cost:
            # A Signet: pay {1} to get {W}{B}, so it's one more mana (either colour) than without it.
            if amount <= cost:
                notes.append(f"its mana ability costs {symbols}, as much as it makes, so it adds no mana")
                return None
            amount -= cost
            made += (f") whose ability costs {symbols}: counted as {amount} more mana"
                     + (" of either colour" if POP[mask] == 2 else " of any of those colours" if POP[mask] > 2 else "")
                     + ", which")
        else:
            made += "):"
        if ability == "creature":
            haste = "Haste" in card.get("keywords", [])
            special.append(f"mana creature ({made} " + ("makes mana at once (haste)" if haste
                                                         else "makes mana from the turn after it's cast"))
            return ["dork", mask, amount, haste, cost, chosen]
        tapped = bool(stats.ENTERS_TAPPED_RE.search(text))
        special.append(f"mana rock ({made} makes mana from " + (
            "the turn after it's cast (enters tapped)" if tapped else
            "the turn it's cast if there's mana to spare" if cost else "the turn it's cast"))
        return ["rock", mask, amount, tapped, cost, chosen]
    if AURA_RAMP_RE.search(text):
        special.append("mana aura: one more mana of any colour from the next turn")
        return ["aura", 31, 1]
    if not TREASURE_RE.search(text) and any(text.count('"', 0, m.start()) % 2
                                            for m in stats.TAP_ADD_RE.finditer(text)):
        notes.append("the mana ability it gives other permanents isn't modelled")
    match = stats.SEARCH_RE.search(text)
    if match is None:
        return None
    search = stats.land_search(text)
    if search is None:
        notes.append("its library search (for a card that isn't a land) isn't modelled")
        return None
    end = text.find(".", match.end())
    sentence = text[match.start(): end if end >= 0 else len(text)]
    if not search[1]:
        if "into your hand" in sentence:
            notes.append("its land search puts the land in your hand, which isn't modelled")
        return None
    trigger = TRIGGER_RE.match(text, text.rfind("\n", 0, match.start()) + 1)
    if trigger and trigger.end() <= match.start() and not _as_it_arrives(trigger.group(2), card["name"]):
        # Ordeal of Nylea: "When you sacrifice this Aura, search ...", which never happens here.
        notes.append(f"its land search happens only {trigger.group(1)} {trigger.group(2)}, which isn't "
                     "modelled, so it's never used")
        return None
    if OPPONENT_SEARCH_RE.search(text):
        notes.append("its land search needs an opponent with more lands, so it never happens")
        return None
    count, basic, types = _search_spec(search[0])
    to_hand = count - 1 if "into your hand" in sentence else 0
    spec = [basic, types]
    sac_land = "sacrifice a land" in text
    line = text[:match.start()].rsplit("\n", 1)[-1]
    what = (f"land ramp: puts {count - to_hand} land{'s' if count - to_hand > 1 else ''} onto the "
            f"battlefield tapped" + (" and one in your hand" if to_hand else "")
            + (", sacrificing your least useful land" if sac_land else ""))
    if ":" in line:
        cost, symbols = stats.search_cost(text)
        tap = "{t}" in line.rsplit(":", 1)[0]
        wait = tap and stats.is_creature(card)          # a creature's {T} waits a turn
        if cost or wait:
            special.append(what + f", by an ability costing {symbols or 'no mana'}, used "
                                  f"{'from the next turn ' if wait else ''}when there's mana to spare")
            return ["ability", cost, 1 if wait else 0, count - to_hand, to_hand, spec, sac_land]
        special.append(what + ", sacrificed at once")
    else:
        special.append(what)
    return ["ramp", count - to_hand, to_hand, spec, sac_land]


def _as_it_arrives(condition, name):
    """Does a trigger's condition ("this creature enters or attacks", "you
    sacrifice this aura") happen as the card is cast or enters?"""
    own = ("this ", name.lower() + " ", name.split(",")[0].lower() + " ")
    return condition.startswith("you cast this") or (condition.startswith(own) and " enters" in condition)


def _either_face(card, land, identity, special):
    """A land with a land on both faces (a Pathway: Brightclimb Pathway //
    Grimclimb Pathway) is played as either face. Its faces differ only in
    the colour they make, so land (its front face's) becomes a land whose
    colour is chosen as it enters, from the faces' colours (compile_deck)."""
    faces = card.get("faces") or []
    if card["layout"] != "modal_dfc" or len(faces) != 2 or land[9] \
            or "Land" not in stats.type_words(faces[1].get("type_line", "")):
        return
    back = _land_model(card, faces[1].get("oracle_text", ""), identity, [], [])
    if back[1:9] != land[1:9] or POP[land[0]] != 1 or POP[back[0]] != 1 or back[0] == land[0]:
        return
    land[0] |= back[0]
    land[9] = land[0]
    made = " or ".join("{" + c + "}" for c in _colours_text(land[0]))
    special.append(f"played as either face, making {made}: the one you need most")


def _card_model(card, identity):
    """(model, special rules, not-modelled notes) for one card: plain data
    the worker processes turn into lookup tables."""
    special, notes = [], []
    land = None
    if stats.is_land(card):
        kind = "land"
        land = _land_model(card, stats.front_text(card), identity, special, notes)
        _either_face(card, land, identity, special)
        options, effect = [], None
    else:
        face = stats.land_face(card)
        kind = "spell"
        if face is not None:
            kind = "mdfc"
            land = _land_model(card, face.get("oracle_text", ""), identity, special, notes)
            special.insert(0, "spell // land: played as a land only when there's no other land in hand")
        faces = stats.cast_faces(card)
        if card["layout"] in ("adventure", "prepare"):
            faces = faces[:1]
            special.append("cast as its creature; the adventure spell isn't used")
        elif len(faces) > 1:
            special.append("either half can be cast")
        x_min = _x_minimum(card)
        options = []
        for _, cost in faces:
            if cost:
                options.extend(_cost_options(cost, x_min))
        if any("{X}" in cost for _, cost in faces):
            special.append(f"X spell: X is {x_min}")
        if not options:
            notes.append("has no mana cost, so it's never cast")
        options.sort(key=lambda o: (-o[0], o[3]))       # most expensive face first, cheapest payment
        effect = _effect(card, identity, special, notes) if kind == "spell" else None
    text = card["oracle_text"].lower()
    if kind != "land":
        if "draw" in card.get("roles", []):
            notes.append("card draw isn't modelled")
        if COST_REDUCTION_RE.search(text):
            notes.append("cost reduction isn't modelled")
        keywords = card.get("keywords", [])
        for word in COST_KEYWORDS:
            if word in keywords:
                notes.append(f"{word.lower()} isn't modelled: the full mana cost is paid")
        if any(k.lower().endswith("cycling") for k in keywords):
            notes.append("cycling isn't modelled")
        if FROM_TOP_RE.search(text):
            notes.append("casting cards from the top of your library isn't modelled")
    if TREASURE_RE.search(text):
        notes.append("Treasure isn't used as mana")
    need = 0
    for o in options:
        for p in o[2]:
            need |= p
    model = {"name": card["name"], "kind": kind, "land": land, "options": options, "effect": effect,
             "need": need}
    return model, special, notes


def compile_deck(sections, kind):
    """(model, info): the deck as plain data for the simulation, and what the
    result reports about its cards (special rules, not modelled, unresolved,
    warnings). Raises ValueError for a library too small to deal from."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    warnings = []
    entries, unresolved = stats.resolve_entries(sections, warnings)
    commanders = [e for e in entries if e.section == "Commander"]
    library = [e for e in entries if e.section == "Deck"]
    identity = 0
    if kind == "commander":
        for e in commanders:
            identity |= _mask(e.card.get("color_identity"))
    models, ids = [], {}
    special, not_modelled = Counter(), Counter()
    deck, commander_ids = [], []
    for e in commanders + library:
        key = e.card["name"]
        if key not in ids:
            model, rules, notes = _card_model(e.card, identity)
            ids[key] = len(models)
            models.append(model)
            model["_rules"], model["_notes"] = rules, notes
        cid = ids[key]
        if e.section == "Commander":
            commander_ids.extend([cid] * e.qty)
            special[(e.name, "commander: starts in the command zone and is cast when it fits")] += e.qty
        else:
            deck.extend([cid] * e.qty)
        for rule in models[cid]["_rules"]:
            special[(e.name, rule)] += e.qty
        for note in models[cid]["_notes"]:
            not_modelled[(e.name, note)] += e.qty
    blank_rows = []
    for (section, name), qty in sorted(unresolved.items()):
        blank_rows.append({"name": name, "qty": qty, "section": section})
        if section == "Deck":
            if "?" not in ids:
                ids["?"] = len(models)
                models.append({"name": "?", "kind": "none", "land": None, "options": [], "effect": None,
                               "need": 0})
            deck.extend([ids["?"]] * qty)
    in_library = sum(q for (section, _), q in unresolved.items() if section == "Deck")
    if in_library:
        warnings.append((f"{in_library} cards with names that aren't Scryfall cards take" if in_library != 1 else
                         "1 card with a name that isn't a Scryfall card takes")
                        + " a place in the library but can't be played: "
                        + ", ".join(sorted({n for s, n in unresolved if s == "Deck"})))
    lost_commanders = sorted({n for s, n in unresolved if s == "Commander"})
    if kind == "commander" and lost_commanders:
        names = " and ".join(lost_commanders)
        warnings.append(f"The commander {names} isn't a Scryfall card name, so it's never cast."
                        if len(lost_commanders) == 1 else
                        f"The commanders {names} aren't Scryfall card names, so they're never cast.")
    elif kind == "commander" and not commander_ids:
        warnings.append("This Commander deck has no Commander section, so no commander is cast.")
    if any(e.section == "Companion" for e in entries):
        warnings.append("The companion isn't used: the simulation plays the Commander and Deck sections.")
    if len(deck) < MIN_LIBRARY:
        raise ValueError(f"the deck has {len(deck)} cards to draw from; the simulation needs at least "
                         f"{MIN_LIBRARY}")
    # The colours the deck can make at all: its lands and mana sources.
    makes = 0
    for cid in set(deck + commander_ids):
        land, effect = models[cid]["land"], models[cid]["effect"]
        if land:
            makes |= land[0]
        if effect and effect[0] in ("dork", "rock", "aura"):
            makes |= effect[1]
    colours = _needed_colours(models, deck + commander_ids, makes)
    basics = 0
    for cid in deck:
        land = models[cid]["land"]
        if models[cid]["kind"] == "land" and land[5]:
            basics |= land[0]
    for m in models:
        m.pop("_rules", None)
        m.pop("_notes", None)
    # A land whose colour is chosen as it enters (Uncharted Haven; a Pathway's face) gets a copy for each
    # colour it can choose ("choices"; each copy has "variant_of", and the same name); the engine puts the
    # copy making the colour you need most onto the battlefield. The copies come after every card in the
    # deck.
    for cid in sorted(set(deck)):
        land = models[cid]["land"]
        if models[cid]["kind"] == "land" and land[9]:
            models[cid]["choices"] = []
            for bit in _colour_bits(land[9]):
                models[cid]["choices"].append(len(models))
                models.append(dict(models[cid], land=[land[0] & ~land[9] | bit] + land[1:9] + [0], choices=None,
                                   variant_of=cid))
    model = {"cards": models, "deck": deck, "commanders": commander_ids, "colours": _colour_bits(colours),
             "basic_mask": basics, "makes": makes}
    lands = sum(1 for cid in deck if models[cid]["kind"] == "land")
    spell_lands = sum(1 for cid in deck if models[cid]["kind"] == "mdfc")
    lost = sum(q for (section, _), q in unresolved.items() if section == "Commander")
    info = {
        "deck": {"cards": len(deck) + len(commander_ids) + lost, "lands": lands, "spell_lands": spell_lands,
                 "commanders": [e.name for e in commanders]},
        "special": [{"name": n, "qty": q, "rule": r} for (n, r), q in sorted(special.items())],
        "not_modelled": [{"name": n, "qty": q, "what": w} for (n, w), q in sorted(not_modelled.items())],
        "unresolved": blank_rows,
        "warnings": warnings,
    }
    return model, info


def _needed_colours(models, cids, makes):
    """The mask of colours the deck's costs need: every single-colour symbol
    a card can't be cast without, then all the colours of a card (a hybrid
    symbol's, a split card's halves') only when no way of paying it uses just
    colours needed already. So a {G/W} card in a green deck needs no white.
    {2/W} (payable with generic mana) needs white only when the deck makes
    white (makes: the colours its lands and mana sources make), since {W} is
    then the cheapest way to pay it and colour screw counts it."""
    firm = 0
    costs = [models[cid]["options"] for cid in set(cids) if models[cid]["options"]]
    for options in costs:
        common = ANY_MANA
        for o in options:
            common &= sum(p for p in set(o[2]) if POP[p] == 1)
        firm |= common
    need = firm
    for options in costs:
        if not any(all(p & firm for p in o[2]) for o in options):
            for o in options:
                for p in o[2]:
                    need |= p
    for options in costs:
        fits = [o for o in options if all(p & makes for p in o[2])]
        if fits:
            cheapest = min(o[3] for o in fits)
            common = ANY_MANA
            for o in fits:
                if o[3] == cheapest:
                    common &= sum(p for p in set(o[2]) if POP[p] == 1)
            need |= common
    return need
