"""Karsten's coloured-source check: the deck's sources of each colour,
counted per requirement, against his tables. The package docstring
(decklab/lib/stats/__init__.py) describes the method and the result."""
import math
from dataclasses import dataclass

from .constants import (
    CANTRIP_MAX_COUNTED, CANTRIP_MAX_MV, CANTRIP_ROUNDING, COLOURS, COLOUR_ASSUMED_LANDS,
    COLOUR_LAND_TOLERANCE, COLOUR_MAX_TURN, COLOUR_SOURCES_COMPUTED, COLOUR_SOURCES_NEEDED,
    COLOUR_SOURCE_RULES, COLOUR_TABLES, COLOUR_X_VALUE, DORK_FIRST_TURN, DORK_WEIGHT, GOLD_EXTRA,
    LAND_KINDS, LAND_SOURCE, MANA_COLOURS, MDFC_SOURCE_WEIGHTS, MULTICOLOUR_FETCH_WEIGHT,
    RAMP2_FIRST_TURN, RAMP2_WEIGHT, RAMP3_FIRST_TURN, RAMP3_WEIGHT, REMINDER_RE, ROCK_FIRST_TURN,
    ROCK_WEIGHT, SPECIAL_SOURCE_WEIGHTS)
from .cardtext import (
    Entry, _cheap_kind, _colour_name, _faces, _parse_cost, _r, _searchable_colours, card_list,
    cast_faces, colour_label, front_text, is_land, land_face, land_search, mana_ability,
    search_cost, type_words, untapped_on_turn_one)


# ----------------------------------------------------------- colour check

@dataclass
class _Source:
    name: str
    qty: int
    kind: str               # land, fetch, mdfc, creature, rock, ramp, cantrip, special
    colours: frozenset
    weight: float           # per copy; a cantrip's depends on the colour (see _Sources.have)
    from_turn: int          # helps with requirements on this turn or later
    turn_one: bool          # counts for turn-1 requirements
    mv: float = 0
    counted: bool = True
    note: str = ""
    copies_counted: int = 0     # cantrips: copies within the first 10 draw effects
    # A land whose search costs mana (Myriad Landscape): the colours it finds,
    # the turn they start counting and their weight. colours holds only its own.
    found: frozenset = frozenset()
    found_from: int = 0
    found_weight: float = 0.0

    def amount(self, colours, turn):
        """Copies x weight towards a requirement of any of colours on turn (not for cantrips)."""
        if not self.counted or turn < self.from_turn or (turn == 1 and not self.turn_one):
            return 0.0
        if self.colours & colours:
            return self.qty * self.weight
        if self.found & colours and turn >= self.found_from:
            return self.qty * self.found_weight
        return 0.0


def _requirements(entry):
    """[(face name, turn, pips, hybrid, notes)] for each face of a card you cast."""
    out = []
    for face_name, cost in cast_faces(entry.card):
        pips, hybrid, x, mv, notes = _parse_cost(cost or "")
        if not pips and not hybrid:
            continue
        turn = max(1, mv + COLOUR_X_VALUE * x)
        if x:
            notes.append(f"X counted as {COLOUR_X_VALUE}")
        if turn > COLOUR_MAX_TURN:
            notes.append(f"cast on turn {turn}; checked as turn {COLOUR_MAX_TURN}, the last one "
                         f"Karsten's tables cover (a little stricter than needed)")
        out.append((face_name, min(turn, COLOUR_MAX_TURN), pips, hybrid, notes))
    return out


def _checks(pips, hybrid, doubt):
    """[(colour label, symbols, extra)] one requirement makes (Karsten's gold
    and hybrid rules). doubt: colours not made by every land."""
    out = []
    colours = [c for c in MANA_COLOURS if pips[c]]
    doubtful = [c for c in colours if c in doubt]
    gold = len(doubtful) >= 2
    for c in colours:
        out.append((c, pips[c], GOLD_EXTRA if gold and c in doubtful else 0))
    if gold:
        out.append((colour_label(doubtful), sum(pips[c] for c in doubtful), GOLD_EXTRA))
    for pair, n in hybrid.items():
        parts = pair.split("/")
        out.append((colour_label(parts), n + sum(pips[c] for c in parts), 0))
    return out


def _needed(table, turn, n):
    """(sources needed, published) for n symbols by turn, or (None, None)."""
    if table is None:
        return None, None
    row = COLOUR_SOURCES_NEEDED[table].get(turn, {})
    if n in row:
        return row[n], True
    if (turn, n) in COLOUR_SOURCES_COMPUTED[table]:
        return COLOUR_SOURCES_COMPUTED[table][(turn, n)], False
    return None, None


def _cost_key(turn, n):
    generic = turn - n
    return ("" if generic <= 0 else str(generic)) + "C" * n


class _Sources:
    """The deck's coloured sources, counted per requirement."""

    def __init__(self, library, deck_colours, library_size, multiplayer=False):
        self.library_size = max(library_size, 1)
        self.multiplayer = multiplayer
        self.list = []
        land_entries = [e for e in library if is_land(e.card)]
        many_colours = len(set(deck_colours) & set(COLOURS)) >= 3
        for e in library:
            card = e.card
            if is_land(card):
                self.list.append(self._land(e, land_entries, many_colours))
            elif land_face(card) is not None:
                face = land_face(card)
                untapped = untapped_on_turn_one(face.get("oracle_text", ""))
                self.list.append(_Source(
                    e.name, e.qty, "mdfc", frozenset(card.get("produced_mana", [])),
                    MDFC_SOURCE_WEIGHTS["untapped" if untapped else "tapped"], 1, untapped,
                    note="modal card: its land " + ("can enter untapped" if untapped else "enters tapped")))
        self.pure_lands = sum(e.qty for e in land_entries)
        # Nonland sources count only when the deck can cast them; that's judged
        # with the lands alone, in check_castable() once the table is known.
        self.pending = []
        for e in library:
            card = e.card
            if is_land(card) or land_face(card) is not None:
                continue
            mv = card["cmc"]
            ability = mana_ability(card)
            text = REMINDER_RE.sub("", front_text(card).lower())
            search = land_search(text)
            if ability == "creature":
                source = _Source(e.name, e.qty, "creature", frozenset(card["produced_mana"]),
                                 DORK_WEIGHT, max(DORK_FIRST_TURN, int(mv) + 1), False, mv,
                                 note="mana creature")
            elif ability == "rock":
                weight = SPECIAL_SOURCE_WEIGHTS.get(e.name, ROCK_WEIGHT)
                source = _Source(e.name, e.qty, "rock", frozenset(card["produced_mana"]), weight,
                                 max(ROCK_FIRST_TURN, int(mv) + 1), False, mv, note="mana rock")
            elif search and search[1] and mv <= 3 and "sacrifice a land" not in text:
                colours = frozenset(_searchable_colours(search[0], land_entries))
                if mv <= 2:
                    source = _Source(e.name, e.qty, "ramp", colours, RAMP2_WEIGHT, RAMP2_FIRST_TURN,
                                     False, mv, note="2-mana land ramp")
                else:
                    source = _Source(e.name, e.qty, "ramp", colours, RAMP3_WEIGHT, RAMP3_FIRST_TURN,
                                     False, mv, note="3-mana land ramp: spells of mana value 5+ only")
            elif mv <= CANTRIP_MAX_MV and _cheap_kind(card) == "draw":
                source = _Source(e.name, e.qty, "cantrip", frozenset(MANA_COLOURS), 0,
                                 int(mv) + 1, False, mv, note="cheap card draw: digs for lands")
            else:
                continue
            self.pending.append((source, e))

    def _land(self, e, land_entries, many_colours):
        card = e.card
        text = front_text(card).lower()
        produced = frozenset(card.get("produced_mana", []))
        search = land_search(REMINDER_RE.sub("", text))
        if e.name in SPECIAL_SOURCE_WEIGHTS:
            return _Source(e.name, e.qty, "special", produced, SPECIAL_SOURCE_WEIGHTS[e.name], 1,
                           untapped_on_turn_one(text), note="any colour an opponent's lands make")
        if search is not None:
            found = frozenset(_searchable_colours(search[0], land_entries))
            basic = "basic" in search[0]
            weight = MULTICOLOUR_FETCH_WEIGHT if basic and many_colours else LAND_SOURCE
            cost, symbols = search_cost(REMINDER_RE.sub("", text))
            if not cost:
                return _Source(e.name, e.qty, "fetch", produced | found, weight, 1, not search[2],
                               note="searches for a land" + (", which enters tapped" if search[2] else ""))
            # Paying for the search takes that many other lands, so it can be
            # used on turn cost + 1 at the earliest, and what it finds helps
            # from then (the turn after, if it enters tapped).
            found_from = cost + 1 + (1 if search[2] else 0)
            own = "makes " + ("".join(f"{{{c}}}" for c in colour_label(produced)) or "no mana") + " itself; "
            return _Source(e.name, e.qty, "fetch", produced, LAND_SOURCE, 1,
                           untapped_on_turn_one(text, self.multiplayer),
                           found=found - produced, found_from=found_from, found_weight=weight,
                           note=own + f"its search costs {symbols}, so the lands it finds count "
                                      f"from turn {found_from}")
        weight = LAND_SOURCE
        faces = _faces(card)
        if (card["layout"] == "modal_dfc" and len(faces) > 1 and many_colours
                and all("Land" in type_words(f.get("type_line", "")) for f in faces)):
            weight = MULTICOLOUR_FETCH_WEIGHT     # a Pathway: one colour or the other
        untapped = untapped_on_turn_one(text, self.multiplayer)
        return _Source(e.name, e.qty, "land", produced, weight, 1, untapped,
                       note="" if untapped else "can't enter untapped on turn 1")

    def lands_for(self, colours, turn=2, kinds=LAND_KINDS + ("mdfc",)):
        """Land sources (lands, fetches, modal cards) of any of colours by turn."""
        return sum(s.amount(colours, turn) for s in self.list if s.kind in kinds)

    def in_doubt(self):
        """Colours not made by every land: Karsten's gold-card +1 is only for these."""
        return {c for c in MANA_COLOURS
                if self.lands_for(frozenset(c), kinds=LAND_KINDS) < self.pure_lands}

    def check_castable(self, table, doubt):
        """Count each pending nonland source only if the lands alone cast it consistently."""
        for source, entry in self.pending:
            ok = True
            for _, turn, pips, hybrid, _ in _requirements(entry):
                for label, n, extra in _checks(pips, hybrid, doubt):
                    needed, _ = _needed(table, turn, n)
                    if needed is not None and self.lands_for(frozenset(label), turn) < needed + extra:
                        ok = False
            source.counted = ok
            if not ok:
                source.note += "; not counted: the deck can't cast it consistently"
            self.list.append(source)
        self.pending = []
        # Karsten: "count at most the first 10 card-draw effects" (cheapest first).
        left = CANTRIP_MAX_COUNTED
        for s in sorted((s for s in self.list if s.kind == "cantrip" and s.counted),
                        key=lambda s: (s.mv, s.name)):
            s.copies_counted = min(s.qty, left)
            left -= s.copies_counted
            if s.copies_counted < s.qty:
                s.note += f"; only {s.copies_counted} of {s.qty} counted (the first 10 draw effects)"

    def have(self, colours, turn):
        """Sources of any of colours for a requirement on turn."""
        total = 0.0
        dig = math.floor(CANTRIP_ROUNDING * self.lands_for(colours) / self.library_size) / CANTRIP_ROUNDING
        for s in self.list:
            if s.kind != "cantrip":
                total += s.amount(colours, turn)
            elif s.counted and turn >= s.from_turn and (turn > 1 or s.turn_one):
                total += s.copies_counted * dig
        return total

    def as_json(self):
        out = []
        for s in self.list:
            out.append({"name": s.name, "qty": s.qty, "kind": s.kind,
                        "colours": colour_label(s.colours | s.found) if s.kind != "cantrip" else "any",
                        "weight": _r(s.weight) if s.kind != "cantrip" else None,
                        "from_turn": s.from_turn, "turn_one": s.turn_one, "counted": s.counted,
                        "found_from_turn": s.found_from if s.found else None,
                        "note": s.note.lstrip("; ")})
        return sorted(out, key=lambda s: (s["kind"] not in ("land", "fetch", "special", "mdfc"), s["name"]))


def _colour_groups(entries, sources, table, doubt):
    """{(label, turn, n, extra): check} for the requirements of entries."""
    groups = {}
    for e in entries:
        requirements = _requirements(e)
        costs = dict(cast_faces(e.card))
        several = len(costs) > 1
        for face_name, turn, pips, hybrid, notes in requirements:
            for label, n, extra in _checks(pips, hybrid, doubt):
                # A gold card's colours together are shown with its printed
                # cost, so {R}{G} doesn't read as hybrid {R/G}{R/G}; cards
                # with different costs get a check each.
                together = bool(extra) and len(label) > 1
                printed = costs.get(face_name, "") if together else None
                key = (label, turn, n, extra, printed)
                group = groups.get(key)
                if group is None:
                    needed, published = _needed(table, turn, n)
                    if needed is not None:
                        needed += extra
                    have = sources.have(frozenset(label), turn)
                    cost = _cost_key(turn, n)
                    symbol = label if len(label) == 1 and label != "C" else "{" + "/".join(label) + "}"
                    group = groups[key] = {
                        "colours": label, "cost": cost,
                        "cost_in_colours": printed or cost.rstrip("C") + symbol * n,
                        "turn": turn, "pips": n, "gold": bool(extra), "needed": needed,
                        "published": published, "have": _r(have),
                        "have_lands": _r(sources.lands_for(frozenset(label), turn)),
                        "ok": None if needed is None else have >= needed,
                        "margin": None if needed is None else _r(have - needed),
                        "cards": [], "notes": [], "_entries": []}
                    if needed is None and table is not None:
                        group["notes"].append(f"Karsten's tables have no entry for {n} coloured "
                                              f"symbols by turn {turn}")
                    if published is False:
                        group["notes"].append("not in Karsten's published table: computed with his "
                                              "model by our research")
                    base = "the table's " + (str(needed - extra) if needed is not None else "number")
                    if together:
                        either = "either" if len(label) == 2 else "any"
                        group["notes"].append(
                            f"gold card: sources of {either} colour count for its {n} coloured "
                            f"symbols together, and Karsten adds {extra} to {base}")
                    elif extra:
                        group["notes"].append(f"gold card: Karsten adds {extra} to {base}")
                    elif len(label) > 1:
                        group["notes"].append("hybrid symbols: sources of either colour count")
                name = f"{e.name} ({face_name})" if several else e.name
                group["_entries"].append(Entry(e.qty, name, e.section, e.card))
                for note in notes:
                    if note not in group["notes"]:
                        group["notes"].append(note)
    for group in groups.values():
        group["cards"] = card_list(group.pop("_entries"))
    return groups


def _hardest_first(check):
    if check["margin"] is not None:
        return (0, check["margin"], -check["needed"])
    return (1, -check["pips"], check["turn"])


def _colour_check(main, library, sideboard, guidance, lands, kind):
    table = COLOUR_TABLES.get(guidance["size"])
    deck_colours = set()
    for e in main:
        for _, _, pips, hybrid, _ in _requirements(e):
            deck_colours.update(c for c in pips if pips[c])
            deck_colours.update(c for pair in hybrid for c in pair.split("/"))
    library_size = sum(e.qty for e in library)
    sources = _Sources(library, deck_colours, library_size, multiplayer=kind == "commander")
    doubt = sources.in_doubt()
    sources.check_castable(table, doubt)
    groups = _colour_groups(main, sources, table, doubt)

    by_label = {}
    for check in groups.values():
        by_label.setdefault(check["colours"], []).append(check)
    summaries = []
    for label in sorted(by_label, key=lambda l: (len(l), [MANA_COLOURS.index(c) for c in l])):
        checks = sorted(by_label[label], key=_hardest_first)
        short = [c for c in checks if c["ok"] is False]
        summaries.append({
            "colours": label, "name": _colour_name(label),
            "land_sources": _r(sources.lands_for(frozenset(label))),
            "ok": None if table is None else not short,
            "hardest": checks[0], "short": short, "checks": checks})

    assumed = COLOUR_ASSUMED_LANDS.get(table)
    deck_lands = lands["effective"]
    land_note = None
    if assumed is not None and abs(deck_lands - assumed) > COLOUR_LAND_TOLERANCE:
        land_note = (f"Karsten's {table}-card table assumes {assumed} lands and this deck has "
                     f"{deck_lands:g}. With a different land count he suggests scaling: needed x "
                     f"{deck_lands:g} / {assumed} (for example {round(18 * deck_lands / assumed, 1)} "
                     f"instead of 18). The verdicts here use his table as published.")
    if table == 99:
        land_note = ((land_note + " ") if land_note else "") + (
            "The 99-card numbers include the free first mulligan and turn-1 draw of multiplayer "
            "Commander; 1v1 games need a few more sources for 1- and 2-drops.")
    sideboard_checks = sorted(_colour_groups(sideboard, sources, table, doubt).values(), key=_hardest_first)
    return {
        "table": table,
        "definition": ("Karsten's 'consistently cast': at least an (89 + mana value)% chance to have "
                       "the coloured sources by the turn equal to the spell's mana value, on the "
                       "play, in games with enough lands."),
        "table_note": None if table is not None else (
            f"Karsten publishes no source counts below 40 cards, so a {guidance['size']}-card deck "
            f"gets its sources and requirements without a verdict. Check its 40-card pairings."),
        "assumed_lands": assumed,
        "deck_lands": deck_lands,
        "land_note": land_note,
        "colours": summaries,
        "sources": sources.as_json(),
        "rules": list(COLOUR_SOURCE_RULES),
        "ok": None if table is None else all(s["ok"] for s in summaries),
        "source": "karsten-sources",
    }, sideboard_checks
