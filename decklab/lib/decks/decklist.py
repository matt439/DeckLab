"""Decklists in the Arena/MTGO export format: one "4 Card Name (SET) 123
*F*" line (parse_line, format_line), whole blocks with section headers
(parse_decklist, format_decklist), card counts and basic lands. Also the
DeckFileError and DecklistError every other part of decks raises.

A line may end with the deck builder's own category (E2-S24), Moxfield's
tag form: "1 Sol Ring (CMM) 410 #Ramp". parse_line keeps it as
DeckLine.category and format_line writes it back; it never counts as part
of the card's identity (DeckLine equality ignores it), so every reader of
names, printings and quantities reads the line as if it had none.
"""
import re
from dataclasses import dataclass, field

from decklab.lib.cards import fold

# Decklist sections, in the order they are written.
SECTIONS = ("Commander", "Companion", "Deck", "Sideboard")
MAIN_SECTIONS = ("Commander", "Deck")     # what counts towards the deck size

BASIC_LANDS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}
BASIC_LANDS |= {"Snow-Covered " + name for name in BASIC_LANDS}
_BASIC_KEYS = {fold(name) for name in BASIC_LANDS}

# One "4 Card Name (SET) 123 *F*" line. The set, number and finish are optional.
# A set with no number after it must be in capitals, as Arena and MTGO write
# it, so a name ending in a word in brackets stays a name: "1 Hazmat Suit
# (Used)" is that card, not Hazmat Suit from a set called "used". A collector
# number never starts with "(".
LINE_RE = re.compile(
    r"^(\d+)x? +(.+?)"
    r"(?: +\(([A-Za-z0-9]{2,8})\) +([^\s*(]\S*)|"      # (SET) 123, the set in any case
    r" +\(([A-Z0-9]{2,8})\))?"                          # (SET) alone, in capitals
    r"(?: +\*([FfEe])\*)?$")
# A category at the end of a line: " #Ramp", " #Win condition" (Moxfield's
# "#!Ramp" global-tag form is read too, without its "!"). One per line: letters,
# digits, spaces and a little punctuation, at most CATEGORY_MAX characters.
# No Scryfall card name has a "#" in it.
CATEGORY_MAX = 30
CATEGORY_TEXT = rf"[^\W_](?:[\w '&/+.-]{{0,{CATEGORY_MAX - 2}}}[^\W_])?"
CATEGORY_RE = re.compile(CATEGORY_TEXT)
CATEGORY_TAIL_RE = re.compile(rf"\s+#!?({CATEGORY_TEXT})\s*$")
# A "(SET)" with more text after it inside a parsed name means the rest of the
# line was garbled ("1 Opt (FDN) 512 extra").
SET_IN_NAME_RE = re.compile(r"\([A-Za-z0-9]{2,8}\) +\S")


class DeckFileError(ValueError):
    """A deck file or product CSV that can't be read safely."""


class DecklistError(DeckFileError):
    """A decklist block with a line that isn't in the Arena/MTGO format."""


@dataclass
class DeckLine:
    """One decklist line: quantity, exact card name and (optionally) printing."""
    quantity: int
    name: str
    set: str | None = None          # lowercase Scryfall set code
    number: str | None = None       # collector number, as printed ("227", "ELD-97")
    finish: str = "nonfoil"         # nonfoil | foil | etched
    # The deck builder's own category ("Ramp"), or None. Not part of the line's
    # identity: two lines differing only in it compare equal.
    category: str | None = field(default=None, compare=False)


def clean_category(text):
    """A category as a line holds it: spaces squeezed, None for a blank one.
    Raises ValueError for one a line can't hold (see CATEGORY_RE)."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise ValueError("a category must be text")
    text = " ".join(text.split()).lstrip("#")
    if not text:
        return None
    if not CATEGORY_RE.fullmatch(text):
        raise ValueError(f"a category is 1-{CATEGORY_MAX} letters, digits, spaces and - ' & / + . "
                         f"(starting and ending with a letter or digit): {text!r}")
    return text


def categories(sections):
    """{section: [category of each line]}: what DeckLine equality leaves out, so
    two lists are the same as written when they're equal and this is too."""
    return {name: [line.category for line in lines] for name, lines in sections.items()}


def is_basic_land(name):
    """True for the basic lands (Wastes and Snow-Covered ones included)."""
    return name in BASIC_LANDS


def parse_line(text):
    """Parse one '4 Card Name (SET) 123 *F* #Category' line into a DeckLine."""
    text = text.strip()
    category = None
    tail = CATEGORY_TAIL_RE.search(text)
    if tail:
        category = clean_category(tail.group(1))
        text = text[:tail.start()]
    if "#" in text:
        raise DecklistError(f"a card line takes one category at its end (\" #Ramp\"): {text!r}")
    m = LINE_RE.match(text)
    if not m:
        raise DecklistError(f"not a decklist line: {text.strip()!r}")
    qty, name, set_code, number, bare_set, finish = m.groups()
    set_code = set_code or bare_set
    if int(qty) < 1:
        raise DecklistError(f"quantity must be at least 1: {text.strip()!r}")
    if SET_IN_NAME_RE.search(name):
        raise DecklistError(f"can't tell the card name from the set and number: {text.strip()!r}")
    finish = {"f": "foil", "e": "etched"}.get((finish or "").lower(), "nonfoil")
    return DeckLine(int(qty), name.strip(), set_code.lower() if set_code else None,
                    number, finish, category)


def format_line(line, category=True):
    """The Arena/MTGO text for one DeckLine, with its category at the end
    unless category is False (a physical record such as Assembled, which
    holds cards, not the builder's notes about them).

    Raises ValueError for a line that wouldn't read back the same (a newline
    in the name, a quantity below 1, a number without a set, an unknown
    finish), so bad input from the page can't damage a deck file.
    """
    text = f"{line.quantity} {line.name}"
    if line.set:
        text += f" ({line.set.upper()})"
        if line.number:
            text += f" {line.number}"
    if line.finish == "foil":
        text += " *F*"
    elif line.finish == "etched":
        text += " *E*"
    tag = clean_category(line.category) if category else None
    if category and tag != line.category:
        raise ValueError(f"can't write {line!r} as a decklist line: its category isn't as a line holds it")
    if tag:
        text += f" #{tag}"
    try:
        back = parse_line(text) if "\n" not in text and "\r" not in text else None
    except DecklistError:
        back = None
    expected = DeckLine(line.quantity, line.name, line.set.lower() if line.set else None,
                        line.number or None, line.finish)
    if back != expected or back.category != tag:
        raise ValueError(f"can't write {line!r} as a decklist line")
    return text


def _section_name(text):
    """The canonical section name if this line is a section header, else None."""
    word = text.strip().rstrip(":").lower()
    for name in SECTIONS:
        if word == name.lower():
            return name
    return None


def section_header(text):
    """The canonical section name if a decklist line is a section header
    ("Sideboard", "sideboard:"), else None."""
    return _section_name(text)


def parse_decklist(text):
    """Parse a decklist block into {section: [DeckLine, ...]}.

    Sections come back in SECTIONS order and empty ones are dropped. Card lines
    before the first header go in "Deck". A card line straight after a blank
    line with no header is an error: some exports use that for the sideboard
    and others don't, so guessing could move cards silently.
    """
    sections = {}
    current = None
    after_blank = False
    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if not raw.strip():
            after_blank = True
            continue
        name = _section_name(raw)
        if name:
            current = name
            sections.setdefault(name, [])
        else:
            if after_blank and current is not None:
                raise DecklistError(f"line {number}: card after a blank line with no "
                                    f"section header: {raw.strip()!r}")
            try:
                line = parse_line(raw)
            except DecklistError as e:
                raise DecklistError(f"line {number}: {e}") from None
            current = current or "Deck"
            sections.setdefault(current, []).append(line)
        after_blank = False
    return {name: sections[name] for name in SECTIONS if sections.get(name)}


def format_decklist(sections, newline="\n"):
    """The text of a decklist block (ends with a newline; '' when empty).

    Sections are written in SECTIONS order with one blank line between them;
    empty sections are left out. This is the exact inverse of parse_decklist
    for every block in the repo's deck files.
    """
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise ValueError(f"unknown decklist sections {sorted(unknown)}; use {SECTIONS}")
    blocks = []
    for name in SECTIONS:
        lines = sections.get(name) or []
        if lines:
            blocks.append(newline.join([name] + [format_line(l) for l in lines]))
    return (newline * 2).join(blocks) + newline if blocks else ""


def card_count(sections, names=MAIN_SECTIONS):
    """Number of cards in the given sections (by default Commander + Deck)."""
    return sum(l.quantity for name in names for l in sections.get(name, []))


def clean_sections(sections):
    """A decklist in SECTIONS order without empty sections, as parse_decklist
    reads it back (so two lists compare equal when the file would too)."""
    unknown = set(sections) - set(SECTIONS)
    if unknown:
        raise ValueError(f"unknown decklist sections {sorted(unknown)}; use {SECTIONS}")
    return {name: list(sections[name]) for name in SECTIONS if sections.get(name)}
