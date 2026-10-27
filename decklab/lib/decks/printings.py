"""A built deck's printings in its box: which physical printing of its cards went in.

Deck Lab counts a deck's cards by name (any printing plays the same), so the box's printings are
a record kept beside the list, in an optional header line Deck Lab keeps as written:

    - **Printings in box:** 2 Llanowar Elves (FDN) 227; 2 Llanowar Elves (M19) 314 foil

Each "; "-separated part is a count, the card's exact name and a printing of it in the space's
collection (" (SET) number", then " foil" or " etched" for those finishes). It may be partial: a
card the line doesn't name, or copies beyond its count, aren't recorded. Basic lands aren't
recorded. Only built home decks have the line: taking a deck apart (assembled.clear) removes it.
Finish building writes it from the packing plan's "Which printing?" choices; the deck page's
Printings in box sheet (POST /api/deck/printings) and `deck push` change it. Nothing reserves by
printing: allocation stays by name.

A save that records more copies of a printing, across the space's built decks, than the
collection has is refused (inventory/ops_decks.py). A record a later collection edit or repack
makes impossible stays as written, and its impossible part is ignored (effective) until fixed:
the deck page says "Printings in box out of date" and `db check` reports it.
"""
import re
from collections import Counter
from dataclasses import dataclass

from .deckfile import HeaderField, _one_line
from .decklist import DeckFileError, is_basic_land

PRINTINGS_FIELD = "Printings in box"
MAX_LINES = 400
MAX_QUANTITY = 9999
MAX_NAME = 200
FINISHES = ("nonfoil", "foil", "etched")
_PART_RE = re.compile(r"^(\d{1,4}) +(.+?) +\(([A-Za-z0-9]{1,8})\) +([A-Za-z0-9★†-]{1,12})(?: +(foil|etched))?$")


@dataclass(frozen=True)
class PrintingLine:
    """quantity copies of name in the printing (set lowercase, number, finish) in the box."""
    quantity: int
    name: str
    set: str
    number: str
    finish: str = "nonfoil"

    @property
    def key(self):
        """The collection's identity key: (set, collector_number, finish)."""
        return (self.set, self.number, self.finish)

    def text(self):
        finish = f" {self.finish}" if self.finish != "nonfoil" else ""
        return f"{self.quantity} {self.name} ({self.set.upper()}) {self.number}{finish}"

    def label(self):
        """The printing alone, as the pages show it: "FDN 227", "M19 314 foil"."""
        return f"{self.set.upper()} {self.number}" + (f" {self.finish}" if self.finish != "nonfoil" else "")


def parse_printings(value):
    """[PrintingLine] from a Printings in box value, in its order; [] for a blank value.
    DeckFileError for a part that isn't "N Name (SET) NUM[ foil|etched]", a count of 0 or too
    many parts."""
    text = (value or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(";")]
    if len(parts) > MAX_LINES:
        raise DeckFileError(f"Printings in box lists more than {MAX_LINES} printings")
    out = []
    for part in parts:
        if not part:
            continue
        m = _PART_RE.match(part)
        if not m:
            raise DeckFileError(f"Printings in box: {part!r} isn't a count, a card's name and its printing "
                                "(such as 2 Llanowar Elves (FDN) 227)")
        quantity, name, set_code, number, finish = m.groups()
        quantity, name = int(quantity), name.strip()
        if not 1 <= quantity <= MAX_QUANTITY:
            raise DeckFileError(f"Printings in box: {part!r} needs a count from 1 to {MAX_QUANTITY}")
        if not name or len(name) > MAX_NAME:
            raise DeckFileError(f"Printings in box: {part!r} isn't a card's name")
        out.append(PrintingLine(quantity, name, set_code.lower(), number, finish or "nonfoil"))
    return out


def format_printings(lines):
    """The field's value for [PrintingLine] (or "" for none). ValueError for one that wouldn't
    read back the same."""
    text = "; ".join(line.text() for line in lines)
    _one_line(text)
    try:
        back = parse_printings(text)
    except DeckFileError as e:
        raise ValueError(str(e)) from None
    if back != list(lines):
        raise ValueError(f"can't write {text!r} as printings in box")
    return text


def _fields(deck):
    return [f for f in deck.header if f.key.lower() == PRINTINGS_FIELD.lower()]


def printings(deck):
    """The deck's recorded printings ([PrintingLine], [] without the line). DeckFileError for a
    line that can't be read."""
    fields = _fields(deck)
    if len(fields) > 1:
        raise DeckFileError("The deck has more than one Printings in box line")
    return parse_printings(fields[0].value) if fields else []


def has_printings(deck):
    """True when the deck's text has a Printings in box line."""
    return bool(_fields(deck))


def set_printings(deck, lines):
    """Set the deck's Printings in box line to lines ([PrintingLine]); None or [] removes it (an
    empty record says nothing). A new line goes at the end of the header; one already there is
    rewritten in place, and one that already says the same is left as written."""
    index = next((i for i, f in enumerate(deck.header) if f.key.lower() == PRINTINGS_FIELD.lower()), None)
    if not lines:
        if index is not None:
            del deck.header[index]
        return
    value = format_printings(lines)
    if index is not None:
        old = deck.header[index]
        try:
            if parse_printings(old.value) == list(lines):
                return
        except DeckFileError:
            pass
        deck.header[index] = HeaderField(PRINTINGS_FIELD, value, None, old.end)
        return
    deck.header.append(HeaderField(PRINTINGS_FIELD, value))


def merged(lines):
    """lines with repeated (name, printing) parts added together, in first-seen order."""
    out = {}
    for line in lines:
        key = (line.name, line.key)
        if key in out:
            line = PrintingLine(out[key].quantity + line.quantity, line.name, line.set, line.number, line.finish)
        out[key] = line
    return list(out.values())


def canonical(name):
    """The exact Scryfall name for name, or name itself while the card index can't say."""
    if is_basic_land(name):
        return name
    try:
        from decklab.lib import cards
        return cards.resolve(name) or name
    except Exception:           # no card index (a fresh clone, a test): compare names as written
        return name


def held_counts(deck, canon=canonical):
    """{canonical name: copies} of the non-basic cards a built deck physically holds: its
    assembled list (every section) with installed stand-ins swapped in. Empty for a deck that
    isn't built or whose build can't be read."""
    from . import assembled, standins
    try:
        sections = assembled.sections(deck)
        held = Counter()
        for lines in sections.values():
            for line in lines:
                name = canon(line.name)
                if not is_basic_land(name):
                    held[name] += line.quantity
        installed = standins.installed_for(deck)
        if installed:
            rows = [{**row, "for": canon(row["for"]), "using": canon(row["using"]) if row["using"] else None}
                    for row in installed["cards"]]
            held = standins.physical_counts(held, rows)
        return held
    except (DeckFileError, standins.StandInsError, KeyError, TypeError):
        return Counter()


def local_problems(lines, held, canon=canonical):
    """Why lines can't describe a box holding held ({name: copies}): basic lands, cards it doesn't
    hold, or more copies of a card than it holds. [] when they can."""
    problems, recorded = [], Counter()
    for line in lines:
        name = canon(line.name)
        if is_basic_land(name):
            problems.append(f"{line.name}: basic lands aren't recorded by printing")
        elif not held.get(name):
            problems.append(f"{line.name} isn't in this deck's box")
        recorded[name] += line.quantity
    for name, quantity in recorded.items():
        if held.get(name) and quantity > held[name]:
            problems.append(f"{name}: {quantity} copies recorded, but the box holds {held[name]}")
    return problems


def trim(lines, held, canon=canonical):
    """lines without what a box holding held can't have: basic lands, cards it doesn't hold, and
    copies beyond what it holds (the later parts go first)."""
    left, out = Counter(held), []
    for line in lines:
        name = canon(line.name)
        take = 0 if is_basic_land(name) else min(line.quantity, left.get(name, 0))
        if take:
            left[name] -= take
            out.append(PrintingLine(take, line.name, line.set, line.number, line.finish))
    return out


def capacity(rows, canon=canonical):
    """{(set, collector_number, finish): (canonical name, copies)} of a collection's rows."""
    out = {}
    for row in rows:
        try:
            quantity = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        key = ((row.get("set") or "").strip().lower(), (row.get("collector_number") or "").strip(),
               (row.get("finish") or "nonfoil").strip().lower())
        if quantity > 0 and key[0]:
            name, copies = out.get(key, (canon((row.get("name") or "").strip()), 0))
            out[key] = (name, copies + quantity)
    return out


def totals(records):
    """{(set, number, finish): copies} recorded across records ({holder: [PrintingLine]})."""
    out = Counter()
    for lines in records.values():
        for line in lines:
            out[line.key] += line.quantity
    return out


def problems_against(lines, owned, canon=canonical):
    """Parts of lines naming a printing the collection (owned: capacity()) doesn't have of that card."""
    out = []
    for line in lines:
        have = owned.get(line.key)
        if have is None:
            out.append(f"{line.text()}: the collection has no {line.label()}")
        elif have[0] != canon(line.name):
            out.append(f"{line.text()}: {line.label()} is {have[0]}, not {line.name}")
    return out


def effective(records, held, owned, canon=canonical):
    """What each holder's record says that still can be true.

    records: {holder: [PrintingLine]}; held: {holder: {canonical name: copies}}; owned: capacity().
    Returns ({holder: Counter{(name, set, number, finish): copies}}, {holder: [why parts are
    ignored]}). A holder's parts beyond what its box holds are dropped (trim), a part naming a
    printing the collection doesn't have of that card is dropped, and a printing recorded more
    times across the holders than the collection has is dropped from every holder naming it
    (there's no telling whose record is wrong)."""
    kept, stale = {}, {}
    for holder, lines in records.items():
        why = local_problems(lines, held.get(holder, Counter()), canon)
        why += problems_against(lines, owned, canon)
        lines = [line for line in trim(lines, held.get(holder, Counter()), canon)
                 if not problems_against([line], owned, canon)]
        kept[holder] = lines
        if why:
            stale[holder] = why
    over = {key for key, copies in totals(kept).items() if copies > owned.get(key, ("", 0))[1]}
    out = {}
    for holder, lines in kept.items():
        counts = Counter()
        for line in lines:
            if line.key in over:
                stale.setdefault(holder, []).append(
                    f"{line.text()}: built decks record more {line.label()} copies than the collection has")
                continue
            counts[(canon(line.name),) + line.key] += line.quantity
        out[holder] = counts
    return out, stale
