"""The simpler parts of deck_stats' result: the decklist resolved to cards,
the guidance size, the curve, the land count against Karsten's formula, and
card types, roles, tribes and keywords. The package docstring
(decklab/lib/stats/__init__.py) describes each part."""
from collections import Counter

from decklab.lib import cards, decks

from .constants import (
    CARD_TYPES, COMMANDER_LAND_FLOOR, COMMANDER_LAND_INTERCEPT, COMMANDER_LAND_PER_AMV,
    COMMANDER_LIBRARY, COMMANDER_SIZE, CONSTRUCTED_SIZES, LAND_BAND_MIN, LAND_FORMULAS,
    LAND_INTERCEPT, LAND_PER_AMV, LAND_PER_CHEAP, LAND_PER_COMPANION, LAND_RULES_OF_THUMB,
    MDFC_LAND_WEIGHTS, TRIBAL_TYPES)
from .cardtext import (
    Entry, _cheap_kind, _has_x, _r, card_list, colour_label, is_creature, is_land, land_face,
    mana_ability, subtypes, type_words, untapped_on_turn_one)


# ============================================================ deck parts

def resolve_entries(sections, warnings):
    """(entries, unresolved): resolved lines merged by section and card."""
    merged, unresolved = {}, Counter()
    for section, lines in sections.items():
        if section not in decks.SECTIONS:
            warnings.append(f"Section {section!r} isn't one Deck Lab knows, so it's left out")
            continue
        for line in lines:
            exact = cards.resolve(line.name)
            card = cards.card(exact) if exact else None
            if card is not None and line.set and line.number:
                printed = cards.printing_card(line.set, line.number)
                if printed is not None and printed["name"] == card["name"]:
                    card = printed      # an Un-set card printed in versions has its own text
            if card is None:
                unresolved[(section, line.name)] += line.quantity
                continue
            key = (section, card["name"], card["oracle_id"])
            if key in merged:
                merged[key].qty += line.quantity
            else:
                merged[key] = Entry(line.quantity, card["name"], section, card)
    entries = sorted(merged.values(), key=lambda e: (decks.SECTIONS.index(e.section), e.name))
    return entries, unresolved


def _guidance(kind, size):
    if kind == "commander":
        note = None if size == COMMANDER_SIZE else (
            f"{size} cards: using the Commander guidance, which is for 100 cards (99 plus the "
            f"commander).")
        return {"size": COMMANDER_SIZE, "deck_size": size, "library": COMMANDER_LIBRARY, "note": note}
    nearest = min(CONSTRUCTED_SIZES, key=lambda s: (abs(s - size), -s))
    note = None if size == nearest else (
        f"{size} cards: using the {nearest}-card guidance, the nearest deck size it covers "
        f"({', '.join(map(str, CONSTRUCTED_SIZES))}).")
    return {"size": nearest, "deck_size": size, "library": nearest, "note": note}


def _average_mv(library):
    """Karsten's average mana value of the library's nonland cards, unrounded (None if none)."""
    nonland = [e for e in library if not is_land(e.card)]
    copies = sum(e.qty for e in nonland)
    return sum(e.card["cmc"] * e.qty for e in nonland) / copies if copies else None


def _curve(library, outside):
    buckets = [{"mv": str(i) if i < 7 else "7+", "creatures": 0, "noncreatures": 0, "total": 0,
                "cards": []} for i in range(8)]
    members = [[] for _ in buckets]
    nonland = creatures = 0
    x_spells = []
    for e in library:
        if is_land(e.card):
            continue
        mv = e.card["cmc"]
        i = min(int(mv), 7)
        key = "creatures" if is_creature(e.card) else "noncreatures"
        buckets[i][key] += e.qty
        buckets[i]["total"] += e.qty
        members[i].append(e)
        nonland += e.qty
        creatures += e.qty if key == "creatures" else 0
        if _has_x(e.card):
            x_spells.append(e)
    for bucket, entries in zip(buckets, members):
        bucket["cards"] = card_list(entries)
    return {
        "buckets": buckets, "nonland": nonland, "creatures": creatures,
        "noncreatures": nonland - creatures,
        "average_mv": _r(_average_mv(library)),
        "average_mv_definition": (
            "Karsten's: the mana values of the library's nonland cards added up (each copy) and "
            "divided by their number. Lands are left out; a spell // land modal card counts as its "
            "front face; X counts as 0. The commander and companion are cast from outside the "
            "library, so they're left out (listed under outside)."),
        "x_spells": {"count": sum(e.qty for e in x_spells), "cards": card_list(x_spells)},
        "outside": [{"name": e.name, "qty": e.qty, "section": e.section, "mv": e.card["cmc"],
                     "creature": is_creature(e.card)} for e in outside],
    }


def _lands(library, companions, kind, guidance):
    lands = sum(e.qty for e in library if is_land(e.card))
    mdfc = {"tapped": 0, "untapped": 0, "cards": []}
    cheap = {"draw": [], "ramp": []}
    mana = {"creature": [], "rock": []}
    for e in library:
        face = land_face(e.card)
        if face is not None:
            enters = "untapped" if untapped_on_turn_one(face.get("oracle_text", "")) else "tapped"
            mdfc[enters] += e.qty
            mdfc["cards"].append({"name": e.name, "qty": e.qty, "land_enters": enters})
        kind_ = _cheap_kind(e.card)
        if kind_:
            cheap[kind_].append(e)
        ability = mana_ability(e.card)
        if ability:
            mana[ability].append({"name": e.name, "qty": e.qty, "mv": e.card["cmc"],
                                  "produces": colour_label(e.card["produced_mana"]),
                                  "cheap": kind_ is not None})
    effective = (lands + MDFC_LAND_WEIGHTS["tapped"] * mdfc["tapped"]
                 + MDFC_LAND_WEIGHTS["untapped"] * mdfc["untapped"])
    n_cheap = sum(e.qty for e in cheap["draw"] + cheap["ramp"])
    amv = _average_mv(library)
    size = guidance["size"]
    if kind == "commander":
        companion_term = COMMANDER_LIBRARY / 60 * LAND_PER_COMPANION
        text = (f"lands = {COMMANDER_LAND_INTERCEPT} + {COMMANDER_LAND_PER_AMV} x average mana value "
                f"- {LAND_PER_CHEAP} x cheap spells")
        if companions:
            text += f" + {companion_term:.2f} x companions"
        recommended = None if amv is None else (
            COMMANDER_LAND_INTERCEPT + COMMANDER_LAND_PER_AMV * amv - LAND_PER_CHEAP * n_cheap
            + companion_term * companions)
        worked = None if amv is None else (
            f"{COMMANDER_LAND_INTERCEPT} + {COMMANDER_LAND_PER_AMV} x {amv:.2f} - {LAND_PER_CHEAP} x "
            f"{n_cheap}" + (f" + {companion_term:.2f} x {companions}" if companions else "")
            + f" = {recommended:.2f}")
    else:
        scale = size / 60
        prefix = "" if size == 60 else f"({size}/60) x "
        text = (f"lands = {prefix}({LAND_INTERCEPT} + {LAND_PER_AMV} x average mana value + "
                f"{LAND_PER_COMPANION} x companions) - {LAND_PER_CHEAP} x cheap spells")
        recommended = None if amv is None else (
            scale * (LAND_INTERCEPT + LAND_PER_AMV * amv + LAND_PER_COMPANION * companions)
            - LAND_PER_CHEAP * n_cheap)
        worked = None if amv is None else (
            f"{prefix}({LAND_INTERCEPT} + {LAND_PER_AMV} x {amv:.2f} + {LAND_PER_COMPANION} x "
            f"{companions}) - {LAND_PER_CHEAP} x {n_cheap} = {recommended:.2f}")
    band = max(LAND_BAND_MIN, guidance["library"] / 60)
    verdict = verdict_text = delta = None
    if recommended is not None:
        delta = effective - recommended
        verdict, verdict_text = _land_verdict(effective, delta, band, kind == "commander")
    return {
        "lands": lands,
        "mdfc": mdfc,
        "effective": _r(effective),
        "cheap": {"count": n_cheap, "draw": card_list(cheap["draw"]), "ramp": card_list(cheap["ramp"])},
        "mana_creatures": sorted(mana["creature"], key=lambda c: c["name"]),
        "mana_rocks": sorted(mana["rock"], key=lambda c: c["name"]),
        "average_mv": _r(amv),
        "companions": companions,
        "formula": {"text": text, "worked": worked, "published": LAND_FORMULAS[size]["published"],
                    "status": LAND_FORMULAS[size]["status"], "source": "karsten-lands"},
        "recommended": _r(recommended),
        "band": _r(band),
        "delta": _r(delta),
        "verdict": verdict,
        "verdict_text": verdict_text,
        "floor": COMMANDER_LAND_FLOOR if kind == "commander" else None,
        "rule_of_thumb": {"text": LAND_RULES_OF_THUMB[size]["text"],
                          "sources": list(LAND_RULES_OF_THUMB[size]["sources"])},
    }


def _land_verdict(effective, delta, band, commander):
    distance = abs(delta)
    side = "low" if delta < 0 else "high"
    more = "fewer" if delta < 0 else "more"
    if distance <= band:
        verdict = "ok"
        text = f"Within {band:g} of the formula ({distance:.2f} {more} lands)."
    elif distance <= 2 * band:
        verdict = f"slightly {side}"
        text = f"{distance:.2f} {more} lands than the formula (ok is within {band:g}, slightly within {2 * band:g})."
    else:
        verdict = side
        text = f"{distance:.2f} {more} lands than the formula (more than {2 * band:g} off)."
    if commander and effective < COMMANDER_LAND_FLOOR and verdict != "low":
        verdict = "low"
        text += (f" Under {COMMANDER_LAND_FLOOR} lands: Karsten says medium-power Commander decks "
                 f"should try not to go below {COMMANDER_LAND_FLOOR}.")
    return verdict, text


# ------------------------------------------------ types, roles, tribes

def _types(main):
    out = []
    for name in CARD_TYPES:
        entries = [e for e in main if name.capitalize() in type_words(e.card["type_line"])]
        out.append({"type": name, "count": sum(e.qty for e in entries), "cards": card_list(entries)})
    return out


def _roles(main):
    out = []
    for role in cards.ROLES:
        entries = [e for e in main if role in e.card.get("roles", [])]
        out.append({"role": role, "count": sum(e.qty for e in entries), "cards": card_list(entries)})
    return out


def _tribes(main):
    members, changelings = {}, []
    for e in main:
        card = e.card
        if not TRIBAL_TYPES & type_words(card["type_line"].split(" // ")[0]):
            continue
        if "Changeling" in card.get("keywords", []) or "is every creature type" in card["oracle_text"].lower():
            changelings.append(e)
        for subtype in dict.fromkeys(subtypes(card["type_line"])):
            members.setdefault(subtype, []).append(e)
    types = [{"type": t, "count": sum(e.qty for e in es), "cards": card_list(es)}
             for t, es in members.items()]
    types.sort(key=lambda t: (-t["count"], t["type"]))
    return {"types": types, "changelings": {
        "count": sum(e.qty for e in changelings), "cards": card_list(changelings),
        "note": "Changelings are every creature type, so each also counts towards every tribe; "
                "they're counted above only under their printed types."}}


def _keywords(main):
    members = {}
    for e in main:
        for keyword in e.card.get("keywords", []):
            members.setdefault(keyword, []).append(e)
    out = [{"keyword": k, "count": sum(e.qty for e in es), "cards": card_list(es)}
           for k, es in members.items()]
    return sorted(out, key=lambda k: (-k["count"], k["keyword"]))
