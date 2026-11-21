"""Allocate physical Commander stand-ins across the full list."""
from collections import Counter
from dataclasses import replace

from . import swaps
from .decklist import DeckLine, is_basic_land

PACKING_ORDER = ("Commander", "Companion", "Deck", "Sideboard")


def _allocate(options):
    """Match singleton candidates to missing copies, using another fit when it saves a swap.

    Each option list is in the existing stand-in ranking order. Try unassigned names first so an
    unrelated later suggestion doesn't displace an earlier one. If all are taken, look for an
    alternate for one of their slots. Every successful reassignment leaves that slot filled.
    """
    taken = {}

    def assign(slot, seen):
        for name in options[slot]:
            if name not in taken:
                taken[name] = slot
                return True
        for name in options[slot]:
            if name not in seen:
                seen.add(name)
                if assign(taken[name], seen):
                    taken[name] = slot
                    return True
        return False

    for slot in options:
        assign(slot, set())
    return {slot: name for name, slot in taken.items()}


def propose(sections, physical, card_of, locked, paper):
    """Return the shortage rows and the proposed sections, preserving each retained printing.

    Treat plain basics as available under the usual untracked supply convention. Extra basics
    don't enter the candidate pool because there is no confirmed free stock for them.
    """
    physical = Counter(physical)
    demand = Counter()
    for lines in sections.values():
        for line in lines:
            demand[line.name] += line.quantity
    spares = [(name, physical[name], card) for name in physical if name not in demand
              and (card := card_of(name)) is not None and card.get("commander_legality") == "legal"]
    colours = swaps.deck_colours(sections, "commander", card_of)
    shortages, ranked = [], {}
    for section in PACKING_ORDER:
        for index, line in enumerate(sections.get(section, ())):
            if is_basic_land(line.name):
                continue
            present = min(line.quantity, physical[line.name])
            physical[line.name] -= present
            missing = line.quantity - present
            if not missing:
                continue
            replaceable = section in swaps.SWAPPABLE
            if replaceable and line.name not in locked and line.name not in ranked:
                choices = swaps.ranked(card_of(line.name), spares, colours, "commander", 1, demand, physical)
                ranked[line.name] = [name for _, name, _, _ in choices if paper(name) is not None]
            shortages.append({"section": section, "index": index, "name": line.name, "missing": missing,
                              "replaceable": replaceable, "locked": line.name in locked, "adds": []})

    def options_at(row):
        if row["locked"] or not row["replaceable"]:
            return ()
        return ranked[row["name"]]

    # Finish fitting main-deck cards before optional sideboard cards. Within each section, handle
    # scarce fits first and keep the saved order for equally constrained cards.
    ordered = sorted(shortages, key=lambda row: (PACKING_ORDER.index(row["section"]), len(options_at(row))))
    options = {(row["section"], row["index"], copy): options_at(row) for row in ordered
               if options_at(row) for copy in range(row["missing"])}
    matches = _allocate(options)
    rows_by_position = {(row["section"], row["index"]): row for row in shortages}
    proposed = {}
    for section, lines in sections.items():
        proposed[section] = chosen = []
        for index, line in enumerate(lines):
            row = rows_by_position.get((section, index))
            if not row:
                chosen.append(line)
                continue
            for copy in range(row["missing"]):
                name = matches.get((section, index, copy))
                if name is None:
                    continue
                printing = paper(name)
                added = DeckLine(1, name, printing["set"], printing["number"], printing["finish"], line.category)
                row["adds"].append((added, swaps.swap_note(card_of(line.name), card_of(name), colours)["text"]))
            if remaining := line.quantity - len(row["adds"]):
                chosen.append(replace(line, quantity=remaining))
            chosen.extend(added for added, _ in row["adds"])
    return shortages, proposed
