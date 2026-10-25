"""How Deck Lab reads a card: its types and subtypes, the faces you cast,
mana costs, Karsten's cheap card draw and ramp, mana abilities, land searches
and colour names. The goldfish package (its model.py) reads cards through
these too (as stats.<name>), so the stats and the practice-hand simulation
read a card the same way."""
from collections import Counter
from dataclasses import dataclass

from .constants import (
    ABILITY_WORD_RE, CAST_EVERY_FACE, CHEAP_DRAW_CREATURE_WORDS, CHEAP_DRAW_NOT, CHEAP_DRAW_WORDS,
    CHEAP_LOOK_NOT, CHEAP_LOOK_WORDS, CHEAP_MAX_MV, CHEAP_RAMP_AURA, CHEAP_RAMP_CHEAT,
    CHEAP_RAMP_CREATURE_NOT, CHEAP_RAMP_NOT, COLOUR_NAMES, CYCLING_RE, ENTERS_TAPPED_RE, LAND_TYPES,
    MANA_COLOURS, MANA_COST_PART_RE, MULTIPLAYER_UNTAPPED_RE, MULTIWORD_SUBTYPES, REMINDER_RE,
    SEARCH_RE, SYMBOL_RE, TAP_ADD_RE, UNTAPPED_OPTION_RE)


# ================================================================ helpers
# The helpers without a leading underscore are shared with goldfish/model.py
# (the practice-hand simulation), so both read a card the same way.

@dataclass
class Entry:
    qty: int
    name: str           # exact Scryfall name
    section: str
    card: dict


def _r(x):
    return None if x is None else round(float(x), 2)


def card_list(entries):
    """[{"name", "qty"}] with repeated names added up, sorted by name."""
    counts = Counter()
    for e in entries:
        counts[e.name] += e.qty
    return [{"name": name, "qty": qty} for name, qty in sorted(counts.items())]


def type_words(type_line):
    """The card types and supertypes on a type line (both halves of a split card's)."""
    words = set()
    for part in type_line.split(" // "):
        words.update(part.split(" — ")[0].split())
    return words


def subtypes(type_line):
    """The subtypes after the dash on a (front face's) type line."""
    parts = type_line.split(" // ")[0].split(" — ", 1)
    if len(parts) < 2:
        return []
    text, out = parts[1], []
    for name in MULTIWORD_SUBTYPES:
        if name in text:
            out.append(name)
            text = text.replace(name, " ")
    return out + text.split()


def is_land(card):
    return "Land" in type_words(card["type_line"])


def is_creature(card):
    return "Creature" in type_words(card["type_line"])


def _faces(card):
    return card.get("faces") or []


def front_text(card):
    faces = _faces(card)
    if faces and card["layout"] != "split":
        return faces[0].get("oracle_text", "")
    return card["oracle_text"]


def land_face(card):
    """The land face of a spell // land modal card, else None."""
    if card["layout"] != "modal_dfc" or is_land(card):
        return None
    for face in _faces(card)[1:]:
        if "Land" in type_words(face.get("type_line", "")):
            return face
    return None


def cast_faces(card):
    """[(face name, mana cost)] of the parts of a card you cast as spells."""
    if is_land(card):
        return []
    faces = _faces(card)
    if not faces:
        return [(card["name"], card["mana_cost"])]
    if card["layout"] in CAST_EVERY_FACE:
        return [(f["name"], f.get("mana_cost", "")) for f in faces
                if "Land" not in type_words(f.get("type_line", ""))]
    return [(faces[0]["name"], faces[0].get("mana_cost", card["mana_cost"]))]


def _spell_text(card):
    """Oracle text of the faces you cast (Karsten's rules read this)."""
    faces = _faces(card)
    if not faces:
        return card["oracle_text"]
    if card["layout"] in CAST_EVERY_FACE:
        return "\n".join(f.get("oracle_text", "") for f in faces
                         if "Land" not in type_words(f.get("type_line", "")))
    return faces[0].get("oracle_text", "")


def _has_x(card):
    return any("{X}" in cost for _, cost in cast_faces(card))


def untapped_on_turn_one(text, multiplayer=False):
    """Can a land with this text be played untapped on turn 1?"""
    text = text.lower()
    return (ENTERS_TAPPED_RE.search(text) is None or UNTAPPED_OPTION_RE.search(text) is not None
            or (multiplayer and MULTIPLAYER_UNTAPPED_RE.search(text) is not None))


def _parse_cost(cost):
    """(pips, hybrid, x, mana value, notes) of a mana cost: pips {colour: n}
    for W, U, B, R, G and {C}; hybrid {"G/W": n}; x the number of X symbols."""
    pips, hybrid, notes = Counter(), Counter(), []
    x = mv = 0
    for symbol in SYMBOL_RE.findall(cost.upper()):
        parts = symbol.split("/")
        if symbol.isdigit():
            mv += int(symbol)
        elif symbol in ("X", "Y", "Z"):
            x += 1
        elif symbol in MANA_COLOURS:
            pips[symbol] += 1
            mv += 1
        elif "P" in parts:
            mv += 1
            notes.append(f"{{{symbol}}} can be paid with 2 life, so it isn't a colour requirement")
        elif len(parts) == 2 and parts[0].isdigit():
            mv += int(parts[0])
            notes.append(f"{{{symbol}}} can be paid with generic mana, so it isn't a colour requirement")
        elif len(parts) >= 2 and all(p in MANA_COLOURS for p in parts):
            hybrid["/".join(sorted(parts, key=MANA_COLOURS.index))] += 1
            mv += 1
        elif symbol == "S":
            mv += 1
            notes.append("{S} (snow) isn't checked")
        elif symbol.startswith("H"):
            notes.append(f"{{{symbol}}} (half mana) isn't checked")
    return pips, hybrid, x, mv, notes


def _cycles_for_one(text):
    """Karsten: "any spell that cycles for one mana" (lowercased text)."""
    for match in CYCLING_RE.finditer(text):
        symbols = SYMBOL_RE.findall(match.group(1))
        if len(symbols) == 1 and symbols[0] not in ("x", "0") and (symbols[0] == "1" or not symbols[0].isdigit()):
            return True
    return False


def _cheap_kind(card):
    """"draw", "ramp" or None: Karsten's cheap card draw / mana ramp rules."""
    if is_land(card) or land_face(card) is not None:
        return None     # modal spell // land cards count as part of a land instead
    text = _spell_text(card).lower()
    creature = is_creature(card)
    cheap = card["cmc"] <= CHEAP_MAX_MV
    if cheap:
        if (any(w in text for w in CHEAP_DRAW_WORDS) and not any(w in text for w in CHEAP_DRAW_NOT)
                and (not creature or all(w in text for w in CHEAP_DRAW_CREATURE_WORDS))):
            return "draw"
        if (not creature and all(w in text for w in CHEAP_LOOK_WORDS)
                and not any(w in text for w in CHEAP_LOOK_NOT)):
            return "draw"
    if _cycles_for_one(text):
        return "draw"
    if not cheap:
        return None
    if ("add " in text and not any(w in text for w in CHEAP_RAMP_NOT)
            and not (creature and any(w in text for w in CHEAP_RAMP_CREATURE_NOT))):
        return "ramp"
    if ("search" in text and "your library" in text and ("land" in text or "basic" in text)
            and "sacrifice" not in text):
        return "ramp"
    if all(w in text for w in CHEAP_RAMP_AURA) or all(w in text for w in CHEAP_RAMP_CHEAT):
        return "ramp"
    return None


def mana_abilities(text):
    """[(cost, clause, trouble, ability)] for each "{T}: Add" ability of a
    card's own (text lowercased, reminder text left out): cost is what comes
    before the colon on its line ("{1}, {t}"), clause what it adds, up to the
    full stop ("{w}{b}"), and ability the rest of its line from {T} ("{t}:
    add {c}{c}. activate only if ..."). trouble is None when the cost is only
    {T}, mana and life, else the parts that aren't ("sacrifice this
    artifact"): such an ability can't be used every turn for free.
    Abilities the card gives to other permanents, in quotes (Goldspan
    Dragon's Treasures), aren't its own and are left out."""
    out = []
    for m in TAP_ADD_RE.finditer(text):
        if text.count('"', 0, m.start()) % 2:
            continue
        start = text.rfind("\n", 0, m.start()) + 1
        colon = text.index(":", m.start())
        end = text.find(".", m.end())
        end = end if end >= 0 else len(text)
        line_end = text.find("\n", m.end())
        cost = ABILITY_WORD_RE.sub("", text[start:colon].strip())
        trouble = [p.strip() for p in cost.split(",") if not MANA_COST_PART_RE.fullmatch(p.strip())]
        out.append((cost, text[m.end():end].strip(), ", ".join(trouble) or None,
                    text[m.start():line_end if line_end >= 0 else len(text)]))
    return out


def mana_ability(card):
    """"creature", "rock" or None: a nonland card with a "{T}: Add" ability
    of its own that it can use every turn (reminder text left out, so a
    Treasure maker isn't one; nor is Lotus Petal, which is sacrificed)."""
    if is_land(card) or land_face(card) is not None or not card.get("produced_mana"):
        return None
    text = REMINDER_RE.sub("", front_text(card).lower())
    if not any(trouble is None for _, _, trouble, _ in mana_abilities(text)):
        return None
    return mana_kind(card)


def mana_kind(card):
    """"creature" or "rock" (an artifact) for a card whose "{T}: Add" ability
    would make it a mana creature or rock, else None."""
    words = type_words(card["type_line"])
    if "Creature" in words:
        return "creature"
    if "Artifact" in words:
        return "rock"
    return None


def land_search(text):
    """(what it searches for, puts it onto the battlefield, tapped) for a
    card's own "search your library for ... card" (lowercased), else None."""
    m = SEARCH_RE.search(text)
    if m is None:
        return None
    end = text.find(".", m.end())
    sentence = text[m.start(): end if end >= 0 else len(text)]
    target = m.group(1)
    if "land" not in target and not any(t in target for t in LAND_TYPES):
        return None
    return target, "onto the battlefield" in sentence, "onto the battlefield tapped" in sentence


def search_cost(text):
    """(mana, "{2}") the ability with a card's own land search costs to use
    (lowercased text): 0 and "" for a free one (Evolving Wilds: "{T},
    Sacrifice this land:") or one that isn't an activated ability."""
    m = SEARCH_RE.search(text)
    if m is None:
        return 0, ""
    line = text[:m.start()].rsplit("\n", 1)[-1]
    if ":" not in line:
        return 0, ""
    cost = line.rsplit(":", 1)[0]
    _, _, x, mv, _ = _parse_cost(cost)
    symbols = "".join(f"{{{s.upper()}}}" for s in SYMBOL_RE.findall(cost) if s not in ("t", "q"))
    return mv + x, symbols


def _searchable_colours(target, lands):
    """Colours of the deck's lands a land search can find."""
    colours = set()
    types = [t for t in LAND_TYPES if t in target]
    for e in lands:
        words = type_words(e.card["type_line"])
        found_types = {s.lower() for s in subtypes(e.card["type_line"])}
        if "basic" in target:
            found = "Basic" in words
        elif types:
            found = bool(found_types & set(types))
        else:
            found = True        # "a land card"
        if found:
            colours.update(e.card.get("produced_mana", []))
    return colours


def colour_label(colours):
    return "".join(sorted(colours, key=MANA_COLOURS.index))


def colour_words(colours):
    """Colours spelled out, in WUBRG order, for a new player: "white and
    black", "white, blue and black"; no colours is "colourless"."""
    names = [COLOUR_NAMES[c] for c in colour_label(colours)]
    if not names:
        return "colourless"
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _colour_name(label):
    return " or ".join(COLOUR_NAMES[c] for c in label)
