"""Correct a built deck's recorded physical build from a reviewed box check.

The box check's observed rows become the deck's Assembled snapshot and installed
stand-ins, so the deck reserves what its box really holds. Intended lists, the stand-in
choices for each list, packed token cards and the kit stay as written. A card found
in a section keeps the printings its recorded lines named, up to their copies; any
further copies are written without a printing, since a count never establishes one.
"""
from collections import Counter
from dataclasses import replace

from . import assembled, standins
from .decklist import SECTIONS, DeckLine


class BoxRepairError(ValueError):
    """The observed box can't be recorded as a physical build exactly."""


def observed(sections, rows, extras):
    """{section: Counter((kind, name, for) -> found)} from compare()-checked rows and extras.

    sections are the physical rows the check offered; rows and extras are already
    validated by boxcheck.compare (extras with canonical names)."""
    found = {section: Counter() for section in SECTIONS}
    for row in rows:
        expected = sections[row["section"]][row["row"]]
        if row["quantity"]:
            found[row["section"]][expected["kind"], expected["name"], expected["for"]] += row["quantity"]
    for row in extras:
        if row["quantity"]:
            found[row["section"]]["card", row["name"], None] += row["quantity"]
    return {section: counts for section, counts in found.items() if counts}


def _logical(found):
    """Section -> Counter(name) of the playable cards each box section stands for."""
    logical = {}
    for section, counts in found.items():
        names = Counter()
        for (kind, name, target), quantity in counts.items():
            names[name if kind == "card" else target] += quantity
        logical[section] = names
    return logical


def _lines(original, names, canonical):
    """New lines for one section: the recorded lines' printings first, in order, then the rest unprinted."""
    left, lines = Counter(names), []
    for line in original:
        name = canonical(line.name)
        take = min(line.quantity, left[name])
        if take:
            lines.append(replace(line, name=name, quantity=take))
            left[name] -= take
    order = [canonical(line.name) for line in original]
    for name in sorted(left, key=lambda n: (order.index(n) if n in order else len(order), n.casefold(), n)):
        if left[name]:
            lines.append(DeckLine(left[name], name))
    return lines


def repair(deck, sections, rows, extras, *, canonical, rederive):
    """Rewrite deck's Assembled snapshot and installed stand-ins to the observed box; True when changed.

    sections are the physical rows the check offered (assembly_takeapart._physical_rows);
    canonical(name) gives a recorded name's exact form; rederive(deck) reads the new
    physical rows back, which must match what was observed, section by section, so no
    marker silently moves between sections or roles. BoxRepairError before any change
    is kept when the observation can't be recorded exactly."""
    found = observed(sections, rows, extras)
    if not found.get("Deck"):
        raise BoxRepairError("No main deck cards were found. If the box is empty, take the deck apart instead.")
    if deck.kind != "commander" and found.get("Commander"):
        raise BoxRepairError("A casual deck has no Commander section; count those cards in another section.")
    version = assembled.version(deck)
    recorded = assembled.sections(deck)
    new = {}
    for section, names in _logical(found).items():
        lines = _lines(recorded.get(section, []), names, canonical)
        if lines:
            new[section] = lines
    markers = Counter()
    for counts in found.values():
        for (kind, name, target), quantity in counts.items():
            if kind == "marker":
                markers[target, name] += quantity
    order = [(row["for"], row["using"]) for row in (standins.installed_for(deck) or {}).get("cards", [])]
    mappings = [{"for": target, "using": using, "qty": markers[target, using]}
                for target, using in sorted(markers, key=lambda key: (
                    order.index(key) if key in order else len(order), key[0], key[1] or ""))]
    try:
        mappings = standins.validate_rows(mappings, new)
    except standins.StandInsError as error:
        raise BoxRepairError(f"The stand-ins found can't be recorded with these cards: {error}.") from None
    data = standins.get_stand_ins(deck)
    data["built"] = {"version": version, "cards": mappings} if mappings else None
    header = list(deck.header)
    changed = assembled.install(deck, version, new)
    changed = standins.set_stand_ins(deck, data) or changed
    if not changed:
        return False
    again = rederive(deck)
    if observed(again, [{"section": section, "row": index, "quantity": row["quantity"]}
                        for section, rows_ in again.items() for index, row in enumerate(rows_)], []) != found:
        deck.header[:] = header
        raise BoxRepairError("These counts put a stand-in in a section the deck can't record exactly. "
                             "Count the stand-in where its card is recorded, or repack the deck.")
    return True


def reservations(before, after):
    """(freed, held): Counter(name) of real cards a repair frees for other decks and newly holds.

    before and after are physical rows; a marker holds its physical card (a named one) only."""
    def real(sections):
        counts = Counter()
        for rows in sections.values():
            for row in rows:
                name = row["name"]
                if name is not None and not row.get("basic"):
                    counts[name] += row["quantity"]
        return counts
    old, new = real(before), real(after)
    return old - new, new - old
