"""Build a reviewable Commander list from this evening's pool (E9-S39)."""
from collections import Counter

from .commander_draft_plan import spell_reasons
from .commander_pool import _entry, _in_category
from .role_pool import fits

# Household supplies plain basics outside the collection ledger.
PLAIN = dict(zip("WUBRG", ("Plains", "Island", "Swamp", "Mountain", "Forest")))


def _tribes(card):
    front = (card.get("type_line") or "").split(" // ")[0]
    kinds, _, types = front.partition("—")
    return set(types.split()) if "Creature" in kinds.split() else set()


def known_identity(card):
    if not card:
        return False
    colours = card.get("color_identity")
    return isinstance(colours, (list, tuple)) and all(isinstance(c, str) and c in PLAIN for c in colours)


def build(names, locked, free, card_of, rules, mass_land_denial=None, affinity_of=None):
    """Select a singleton core, preserve theme locks, then apportion ordinary basics."""
    leads = [card_of(name) for name in names]
    if not 1 <= len(names) <= 2 or len(set(names)) != len(names) or any(
            free.get(n, 0) < 1 or not known_identity(c) or c.get("commander_legality") != "legal"
            for n, c in zip(names, leads)):
        raise ValueError("Each commander needs a distinct, legal copy free tonight.")
    if not (rules.may_lead(leads[0]) if len(names) == 1 else rules.pair_rule(*leads)):
        raise ValueError("Choose a card that can lead or two commanders that can lead together.")
    identity = set().union(*(c["color_identity"] for c in leads))
    colours = [c for c in "WUBRG" if c in identity]
    mana_types = [*colours, "C"]
    target = 100 - len(names)
    if len(locked) > target or len(locked) != len(set(locked)):
        raise ValueError(f"Lock at most {target} distinct cards outside the command zone.")
    cats = [c for c in rules.categories if c.get("lands") or c.get("roles")]
    land_goal = next(c["target"] for c in cats if c.get("lands"))
    counts, sources, demand = Counter(), Counter(), Counter()
    warnings = []
    if mass_land_denial is None:
        warnings.append("Mass land denial tags are unavailable for this draft.")

    def bracket_flags(card):
        flags = []
        if card.get("game_changer"):
            flags.append("Game Changer")
        if mass_land_denial and card.get("oracle_id") in mass_land_denial:
            flags.append("mass land denial")
        return flags

    picks = []
    entries = {}
    for name, qty in free.items():
        card = card_of(name)
        if qty > 0 and name not in names and known_identity(card) and fits(card, identity):
            entries[name] = _entry(name, card, qty)
    basics = {}
    basic_names = {c: PLAIN[c] for c in colours}
    basic_names["C"] = "Wastes"
    for colour, name in basic_names.items():
        card = card_of(name)
        if known_identity(card) and fits(card, identity):
            basics[colour] = name
            entries[name] = _entry(name, card, target)
    for name in locked:
        if name not in entries:
            raise ValueError(f"{name} needs a free, legal copy in the commanders' colours outside the command zone.")
    for card in leads + [entries[n]["card"] for n in locked]:
        flags = bracket_flags(card)
        if flags:
            warnings.append(f"{card['name']} is a chosen card flagged for {', '.join(flags)}. Review the bracket before play.")
    entries = {n: e for n, e in entries.items() if n in locked or not bracket_flags(e["card"])}
    theme = set().union(*(_tribes(card) for card in leads + [entries[n]["card"] for n in locked]))

    source, affinity = affinity_of(names) if affinity_of else (None, {})
    curve = Counter()

    def mana_band(card):
        value = card.get("cmc")
        if value is None:
            return "unknown"
        if value <= 2:
            return "0-2"
        return "3-4" if value <= 4 else "5+"

    supplied_mana = {name: colour for colour, name in basics.items()}

    def produces(entry):
        plain = supplied_mana.get(entry["name"])
        return (plain,) if plain else (entry["card"].get("produced_mana") or ())

    def count(entry, qty):
        for cat in cats:
            if _in_category(cat, entry):
                counts[cat["category"]] += qty
        card = entry["card"]
        if not entry["land"]:
            curve[mana_band(card)] += qty
        for colour in mana_types:
            if entry["land"] and colour in produces(entry):
                sources[colour] += qty
            if not entry["land"]:
                demand[colour] += qty * (card.get("mana_cost") or "").count(colour)

    def pick(entry, why, lock=False):
        name = entry["name"]
        picks.append({"name": name, "quantity": 1, "reason": why, "locked": lock,
                      "land": entry["land"], "assumed_basic": name in basics.values()})
        count(entry, 1)

    for name, card in zip(names, leads):
        count(_entry(name, card, 1), 1)
    locked_entries = [entries.pop(n) for n in locked]
    for entry in locked_entries:
        pick(entry, "Locked theme card.", True)
    lands = sum(p["land"] for p in picks)
    # Reserve the template's mana slots even if the pool is short of lands.
    spell_slots = min(target - len(picks), max(0, target - land_goal - (len(picks) - lands)))
    spells = [e for e in entries.values() if not e["land"]]
    role_cats = [c for c in cats if c.get("roles")]
    matches = {e["name"]: [c for c in role_cats if _in_category(c, e)] for e in spells}
    tribes = {e["name"]: sorted(theme & _tribes(e["card"])) for e in spells}
    plans, drawbacks, cheap_cyclers = spell_reasons(leads, spells)
    bands = {e["name"]: mana_band(e["card"]) for e in spells}
    weights = {"0-2": 2, "3-4": 2, "5+": 1}

    def rank(e):
        short = [c for c in matches[e["name"]] if counts[c["category"]] < c["target"]]
        shared = tribes[e["name"]]
        # Give low and mid-curve spells twice the share of expensive spells as a starting mix.
        band = bands[e["name"]]
        pressure = curve[band] / weights.get(band, 1)
        share = affinity.get(e["name"])
        # Within the same role coverage, leave room for cheaper plays when the top end is full.
        full = band == "unknown" or (band == "5+" and e["name"] not in cheap_cyclers
                                     and curve[band] * 5 >= target - land_goal + len(names))
        score = (e["name"] in drawbacks, -len(short), full, -(share or 0), e["name"] not in plans,
                 band == "unknown", pressure, -len(shared),
                 e["card"].get("cmc") or 0, e["name"].casefold())
        return score, short, shared

    distinct_slots = min(spell_slots, len(spells))
    for _ in range(distinct_slots):
        e = min(spells, key=lambda row: rank(row)[0])
        _, short, shared = rank(e)
        reasons = []
        if short:
            reasons.append("Fills " + ", ".join(c["label"] for c in short) + ".")
        if e["name"] in plans:
            reasons.append(plans[e["name"]])
        if shared:
            reasons.append("Shares a creature type: " + ", ".join(shared) + ".")
        if affinity.get(e["name"]):
            reasons.append(f"Included in {affinity[e['name']]:g}% of decks in the cached EDHREC sample for these commanders.")
        if not reasons:
            reasons.append(f"Fills a spell slot in the {mana_band(e['card'])} mana-value group.")
        if e["name"] in drawbacks:
            reasons.append(drawbacks[e["name"]])
        pick(e, " ".join(reasons))
        spells.remove(e)
    if spell_slots > distinct_slots:
        chosen = {p["name"]: p for p in picks if not p["land"]}
        remaining = spell_slots - distinct_slots
        for entry in [*locked_entries, *sorted(entries.values(), key=lambda e: e["name"].casefold())]:
            row = chosen.get(entry["name"])
            if not remaining:
                break
            if not row:
                continue
            limit = rules.commander._copies_allowed(entry["card"])
            copies = min(entry["free"], limit if limit is not None else entry["free"])
            extra = min(remaining, copies - row["quantity"])
            if extra > 0:
                row["quantity"] += extra
                row["reason"] += " Its rules allow these extra free copies."
                count(entry, extra)
                remaining -= extra
    land_slots = min(target - sum(p["quantity"] for p in picks), max(0, land_goal - lands))
    land_choices = [e for e in entries.values() if e["land"]]
    land_choices.extend(entry for entry in locked_entries if entry["name"] in basics.values())
    if identity and not demand["C"]:
        land_choices = [e for e in land_choices if e["name"] != "Wastes"]
    basic_rows = {p["name"]: p for p in picks if p["assumed_basic"]}

    needed = [c for c in mana_types if c in identity or demand[c] or not identity]

    def land_rank(entry):
        produced = set(produces(entry)) & set(needed)
        # Establish several sources of every commander colour before weighting spell pips.
        return (-sum(sources[c] < 3 for c in produced), -sum((1 + demand[c]) / (1 + sources[c]) for c in produced),
                entry["name"] in basics.values(), entry["name"].casefold())

    for _ in range(land_slots):
        if not land_choices:
            break
        entry = min(land_choices, key=land_rank)
        name = entry["name"]
        if name in basic_rows:
            basic_rows[name]["quantity"] += 1
            count(entry, 1)
        elif name in basics.values():
            pick(entry, "Balances mana colours using the assumed ordinary basic-land supply.")
            basic_rows[name] = picks[-1]
        else:
            pick(entry, "Fills a land slot from the free collection.")
            land_choices.remove(entry)
        land_slots -= 1
    picked = sum(p["quantity"] for p in picks)
    for colour in needed:
        if not sources[colour]:
            label = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green", "C": "colourless"}[colour]
            warnings.append(f"No selected land is known to produce {label} mana.")
    return {"affinity_source": source, "names": names, "colours": colours, "target": target, "picked": picked,
            "open_slots": target - picked, "open_lands": land_slots, "open_spells": target - picked - land_slots,
            "warnings": warnings, "picks": picks, "roles": [{"label": c["label"], "target": c["target"],
                                       "count": counts[c["category"]]} for c in cats],
            "mana_sources": [{"colour": c, "count": sources[c]} for c in needed]}
