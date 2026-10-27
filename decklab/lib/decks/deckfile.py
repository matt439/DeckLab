"""The deck file model (DeckFile, with its HeaderField, TableRow, TotalRow
and PriceStamp parts) and the parser that reads one: parse_deck() and
read_deck_file() find each part Deck Lab owns and remember where it is in
the text (DeckFile.spans), so render.py can rewrite just those parts. The
exchange-rate check (RATE_FORMS, _rate_in) that spots a rate above the
table worded some other way than PRICE_STAMP is here too.
"""
import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .decklist import DeckFileError, DecklistError, parse_decklist

KINDS = ("casual", "commander")
PLAYERS = ("user", "wife", "either")
STATUSES = ("idea", "building", "built")
BUILT_VERSIONS = ("target", "owned")        # "Built version: target" / "owned-only"
OWNED_FIELDS = ("Format", "Archetype", "Played by", "Status", "Built version", "Target bracket", "Sleeves",
                "Deck box")
FORMATS = {"casual": "Casual 60-card, 1v1", "commander": "Commander (100 cards)"}   # new decks' Format

TABLE_COLUMNS = ["Card", "Need", "Owned", "Missing", "~AUD each", "~AUD missing", "Notes"]
TABLE_HEADER = "| " + " | ".join(TABLE_COLUMNS) + " |"
TABLE_RULE = "|" + "---|" * len(TABLE_COLUMNS)
MARKER = "*Decklist changed in Deck Lab on {date}; prose sections may be out of date.*"

# The rate and dates the table's prices were worked out with, inside the
# paragraph above the table. A file without one gets PRICE_NOTE there.
PRICE_STAMP = "1 USD = {rate} AUD (ECB rate of {rate_date}), pulled {price_date}"
PRICE_STAMP_RE = re.compile(r"1 USD = (\d+(?:\.\d+)?) AUD \(ECB rate of (\d{4}-\d{2}-\d{2})\), "
                            r"pulled (\d{4}-\d{2}-\d{2})")
PRICE_NOTE = ("Prices are **estimates in AUD**: Scryfall's cheapest paper non-foil printing (USD), "
              "converted at {stamp}.")
# An exchange rate stated some other way above the table (see _rate_in): a
# conversion factor, in one of RATE_FORMS, that isn't PRICE_STAMP itself.
# Ordinary amounts ("A$45", "45.50 AUD", "cards under 1 USD") and prose that
# only names currencies ("Scryfall lists USD; this table shows AUD") aren't.
# The paragraph is text anyone can put in a deck file, so every pattern takes
# time in proportion to its length: runs of spaces and digits are matched
# possessively (*+, ++: never given back and tried again shorter), and a
# number can't start straight after a digit ((?<!\d)), so no pattern tries
# every position of a long run of digits or spaces against the rest of it.
_CUR = (r"(?:\b(?:usd|aud|eur)\b|\b(?:us|au|a|aud)\s?\$|\$|€"                 # USD, US$, A$, AU$, $, €
        r"|\b(?:(?:us|u\.s\.|american|australian|aussie)\s++)?dollars?\b|\beuros?\b)")
_NUM = r"(?<!\d)\d++(?:\.\d++)?+"
_ABOUT = r"(?:\s*+(?:about|around|roughly|approximately|approx\.?|nearly|almost|~))?"
_ONE = rf"(?:\b(?:1|one)(?:\.0++)?\s*+{_CUR}|{_CUR}\s*+1(?:\.0++)?(?!\.?\d))"      # "1 USD", "USD 1", "us$1"
# (form, regex, whether it needs a currency or rate word near it), tried in this order.
RATE_FORMS = [(form, re.compile(rx, re.IGNORECASE), near) for form, rx, near in (
    # "1 USD = 1.42 AUD", "USD 1 = AUD 1.4224", "US$1 ≈ A$1.42", "1 EUR is about 1.65 AUD"
    ("equation", rf"{_ONE}\s*+(?:=|≈|≃|~|:|→|->|=>|\bis\b|\bequals?\b|\bbuys?\b|\bgets?\b){_ABOUT}"
                 rf"\s*+(?:{_CUR}\s*+)?{_NUM}(?:\s*+{_CUR})?", False),
    # "1.4224 AUD per USD", "A$1.42 for each US dollar", "1.42 AUD to the US dollar"
    ("per", rf"(?:{_CUR}\s*+)?{_NUM}\s*+(?:{_CUR}\s*+)?(?:\bper\b|/|\bfor\s++(?:each|every|one|a|1)\b"
            rf"|\bto\s++(?:the|a|one|1|each)\b)\s*+(?:(?:1|one)\s*+)?{_CUR}", False),
    # "USD→AUD 1.4224", "USD/AUD 1.42", "USD to AUD at 1.42"
    ("pair", rf"{_CUR}\s*+(?:/|→|->|=>|\bto\b|\binto\b)\s*+{_CUR}\s*+(?:\brates?\b\s*+)?"
             rf"(?:=|:|≈|\bat\b|\bof\b|\bis\b)?{_ABOUT}\s*+(?:{_CUR}\s*+)?{_NUM}", False),
    # "Scryfall price × 1.4224", "price * 1.42", "x1.42", "a multiplier of 1.4224" (not **bold**)
    ("multiply", rf"(?:×|\s\*\s|\bx|\btimes\b)\s*+\d++\.\d++"
                 rf"|\bmultipl(?:ier|ied|y|ying)\b(?:\s++(?:of|by|is|was|about|around|roughly))*+"
                 rf"\s*+(?:[=:]\s*+)?{_NUM}", True),
    # "an exchange rate of 1.4224", "converted at 1.4224", "converted at A$1.42", "(ECB 2026-09-25)"
    ("rate", rf"\b(?:rates?|exchange|convert(?:ed|s|ing)?|conversion|ecb|fx|forex)\b"
             rf"(?:\s++(?:of|at|is|was|about|around|roughly|approximately|by|using|with|set\s++at))*+"
             rf"\s*+(?:[=:≈~]\s*+)?(?:{_CUR}\s*+)?{_NUM}", False),
    # A number with 2+ decimals ("at 1.4224"), unless it's an amount of money (see _rate_in).
    ("number", r"(?<![\d.,])\d++\.\d{2,}+(?!\.?\d|\s*+%)", True),
)]
RATE_NEAR = 60      # characters either side of a factor that must hold a currency or rate word
RATE_CONTEXT_RE = re.compile(rf"{_CUR}|\b(?:rates?|exchange|convert\w*|conversion|ecb|fx|forex|pric(?:e|es|ed|ing)"
                             rf"|scryfall|multipl\w*)\b", re.IGNORECASE)
# Every match of RATE_CONTEXT_RE starts with one of these, so a window with
# none of them has no context word: a quick test before the long pattern.
_CONTEXT_START_RE = re.compile(r"[uaedrcfpsm$€]", re.IGNORECASE)
_AMOUNT_BEFORE_RE = re.compile(rf"{_CUR}[\s*_~]*+$", re.IGNORECASE)       # "A$45.50", "~$0.40", "A$ **45.50"
_AMOUNT_AFTER_RE = re.compile(rf"[\s*_]*+{_CUR}", re.IGNORECASE)           # "45.50 AUD", "**45.50** AUD"
_QUOTE_CUT_RE = re.compile(r"[.,;:!?](?:\s|$)|[()\[\]\0]")     # where a quoted rate's words start
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# "- **Key:** value", or "- **Key**: value" with the colon outside the bold.
FIELD_RE = re.compile(r"^- \*\*([^*]+?)(?::\*\*|\*\*:) ?(.*)$")
HEADING_RE = re.compile(r"^(#{1,6}) +(.*?)\s*$")
MARKER_RE = re.compile(r"^\*Decklist changed in Deck Lab on (\d{4}-\d{2}-\d{2}); "
                       r"prose sections may be out of date\.\*$")
TOTAL_RE = re.compile(r"^\*\*(Total[^*]*)\*\*$")
COUNT_RE = re.compile(r"^(?:\*\*(\d+)\*\*|(\d+))$")


@dataclass
class HeaderField:
    key: str
    value: str
    raw: str | None = None      # the original line (kept verbatim if not owned)
    end: str | None = None      # its original line ending ("" at the end of the file)


@dataclass
class TableRow:
    """One row of the owned-vs-needed table, as pool.py computed it.

    aud_each / aud_missing are finished strings such as "~$0.40" (see
    format_aud), or "" for a blank cell. None (both) means no price was worked
    out: set_table then keeps the old row's price cells if its Need, Owned and
    Missing didn't change, so they still match the rate stamp, and leaves them
    blank otherwise. notes_cell is the raw text between the last two pipes,
    spaces included, so hand-written notes survive byte for byte; leave it
    None to carry the notes over from the row for the same card. labels are
    Deck Lab's own notes (LABEL_RE, see pool.table_rows): when given (even
    empty), set_table puts them at the start of the carried-over notes in
    place of the old ones; None leaves the notes as they were.
    """
    card: str
    need: int
    owned: int
    missing: int
    aud_each: str | None = ""
    aud_missing: str | None = ""
    notes_cell: str | None = None
    labels: tuple | None = None

    @property
    def notes(self):
        return (self.notes_cell or "").strip()


@dataclass
class TotalRow:
    """The '| **Total to buy** | | | **8** | | **~$3.32** | |' row.

    aud_missing, notes_cell and labels work as in TableRow: None for
    aud_missing keeps the old total's AUD only if every row with something
    missing kept its prices, and a None notes_cell carries the old total's
    notes over, with labels in place of Deck Lab's old ones.
    """
    missing: int
    aud_missing: str | None = ""
    label: str = "Total to buy"
    notes_cell: str | None = None
    labels: tuple | None = None


@dataclass
class PriceStamp:
    """The rate and dates the table's AUD prices were worked out with."""
    rate: float             # AUD per USD
    rate_date: str          # ECB reference date of the rate (YYYY-MM-DD)
    price_date: str         # date Scryfall's USD prices were pulled (YYYY-MM-DD)

    def text(self):
        """The stamp as written in the file. Raises ValueError for values
        PRICE_STAMP_RE couldn't read back (a rate that isn't a positive
        number, a date that isn't YYYY-MM-DD), so a save never writes a stamp
        the next read wouldn't find."""
        ok = (isinstance(self.rate, (int, float)) and math.isfinite(self.rate) and self.rate > 0
              and all(isinstance(d, str) and DATE_RE.fullmatch(d) for d in (self.rate_date, self.price_date)))
        text = PRICE_STAMP.format(rate=self.rate, rate_date=self.rate_date, price_date=self.price_date)
        if not ok or not PRICE_STAMP_RE.fullmatch(text):
            raise ValueError(f"can't write this price stamp: {self!r}")
        return text


@dataclass
class DeckFile:
    """A parsed deck file. Edit the fields, then render_deck_file()."""
    path: Path | None
    slug: str
    kind: str
    title: str
    header: list                    # [HeaderField]
    target: dict                    # {section: [DeckLine]}
    owned: dict | None              # the owned-only list, if the file has one
    rows: list | None               # [TableRow], None if the file has no table
    total: TotalRow | None
    changed_on: str | None          # date in the "Decklist changed" line
    sha256: str
    text: str                       # the file as read (for render_deck_file)
    newline: str = "\n"
    prices: PriceStamp | None = None    # the stamp above the table, if it has one
    spans: dict = field(default_factory=dict, repr=False)
    space: str = "home"             # lib/spaces.py: "home", or the person whose deck folder holds it
    considering: list | None = None     # [DeckLine] under "## Considering" (E2-S23), None without that block

    @property
    def deck_id(self):
        """The library's id: "<kind>/<slug>" at home, "<space>/<kind>/<slug>" in a person's space."""
        return f"{self.kind}/{self.slug}" if self.space == "home" else f"{self.space}/{self.kind}/{self.slug}"

    @property
    def fields(self):
        """Every header field as an ordered list of (key, value)."""
        return [(f.key, f.value) for f in self.header]

    def get_field(self, key):
        """A header field's value (case-insensitive key), or None."""
        for f in self.header:
            if f.key.lower() == key.lower():
                return f.value
        return None

    @property
    def format(self):
        return self.get_field("Format")

    @property
    def player(self):
        return _leading_word(self.get_field("Played by"), PLAYERS)

    @property
    def status(self):
        return _leading_word(self.get_field("Status"), STATUSES)

    @property
    def built_version(self):
        """"target" or "owned" from the Built version field, else None."""
        return _leading_word(self.get_field("Built version"), BUILT_VERSIONS)

    @property
    def sleeves(self):
        """A built deck's sleeves as written (the Sleeves field, trimmed), else
        None: an accessory id from magic/accessories.csv, or older free text
        such as a colour."""
        value = (self.get_field("Sleeves") or "").strip()
        return value or None

    @property
    def deck_box(self):
        """A built deck's deck box as written (the Deck box field, trimmed),
        else None: an accessory id, or free text."""
        value = (self.get_field("Deck box") or "").strip()
        return value or None

    @property
    def target_bracket(self):
        m = re.match(r"\s*(\d+)", self.get_field("Target bracket") or "")
        return int(m.group(1)) if m else None

    @property
    def has_decklist(self):
        """True if the file has a fenced block under "## Decklist" (which may
        be empty), so its target list can be read and written."""
        return "target" in self.spans


def _leading_word(value, words):
    """The value's first word in lower case (after any Markdown backticks,
    asterisks or quotes) if it's one of words, else None."""
    m = re.match(r"[\s`*_\"']*([A-Za-z]+)", value or "")
    word = m.group(1).lower() if m else None
    return word if word in words else None


@dataclass
class _Line:
    start: int      # offset of the first character
    end: int        # offset just past the line ending
    text: str       # the line without its ending


def _lines(text):
    """Split on "\n" only (str.splitlines also breaks on rarer characters)."""
    lines, pos = [], 0
    while pos < len(text):
        cut = text.find("\n", pos)
        end = len(text) if cut == -1 else cut + 1
        lines.append(_Line(pos, end, text[pos:end].removesuffix("\n").removesuffix("\r")))
        pos = end
    return lines


def _headings(lines):
    """[(index, level, text)] for headings outside fenced blocks."""
    found, in_fence = [], False
    for i, line in enumerate(lines):
        if line.text.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = None if in_fence else HEADING_RE.match(line.text)
        if m:
            found.append((i, len(m.group(1)), m.group(2)))
    return found


def _paragraphs(lines):
    """The runs of non-blank lines in lines, each a list of _Line."""
    out, run = [], []
    for line in lines:
        if line.text.strip():
            run.append(line)
        elif run:
            out.append(run)
            run = []
    return out + ([run] if run else [])


def _section_end(lines, headings, index, level):
    """Index of the next heading at `level` or above after line `index`."""
    for i, lvl, _ in headings:
        if i > index and lvl <= level:
            return i
    return len(lines)


def _find_block(lines, begin, end, what):
    """(open, close) line indexes of the first fenced block in lines[begin:end]."""
    for i in range(begin, end):
        if lines[i].text.lstrip().startswith("```"):
            for j in range(i + 1, len(lines)):
                if lines[j].text.strip().startswith("```"):
                    return i, j
            raise DeckFileError(f"{what}: the fenced block is never closed")
    return None


def _count(cell, what):
    m = COUNT_RE.match(cell)
    if not m:
        raise DeckFileError(f"owned-vs-needed table: {what} is not a number: {cell!r}")
    return int(m.group(1) or m.group(2))


def _parse_row(text, number):
    parts = text.rstrip().split("|", 7)
    if len(parts) < 8 or parts[0].strip() or not parts[7].endswith("|"):
        raise DeckFileError(f"owned-vs-needed table, line {number}: expected "
                            f"{len(TABLE_COLUMNS)} cells: {text!r}")
    cells = [p.strip() for p in parts[1:7]]
    notes_cell = parts[7][:-1]
    m = TOTAL_RE.match(cells[0])
    if m:
        return TotalRow(_count(cells[3], "Missing"), _unbold(cells[5]), m.group(1), notes_cell)
    return TableRow(cells[0], _count(cells[1], "Need"), _count(cells[2], "Owned"),
                    _count(cells[3], "Missing"), cells[4], cells[5], notes_cell)


def _unbold(cell):
    return cell[2:-2] if len(cell) >= 4 and cell.startswith("**") and cell.endswith("**") else cell


def _without_stamp(text, span, stamp):
    """The paragraph text[span[0]:span[1]] with Deck Lab's stamp (the span
    stamp, when it lies inside) blanked out with NULs, which no rate form
    matches across."""
    start, end = span
    para = text[start:end]
    if stamp and start <= stamp[0] and stamp[1] <= end:
        a, b = stamp[0] - start, stamp[1] - start
        para = para[:a] + "\0" * (b - a) + para[b:]
    return para


def _rate_in(para):
    """(start, end) of the first exchange rate that para (a paragraph with
    the stamp blanked out) states, or None: a conversion factor in one of
    RATE_FORMS, those marked so only with a currency or rate word within
    RATE_NEAR characters. A number with two decimals written as money
    ("A$45.50", "45.50 AUD") is an amount, not a factor. Anything that
    looks like a factor counts: a wrong guess only stops repricing, with a
    note saying what was found, where a missed rate would leave two."""
    for form, regex, near in RATE_FORMS:
        for m in regex.finditer(para):
            if form == "number" and len(m.group().partition(".")[2]) == 2 and (
                    _AMOUNT_BEFORE_RE.search(para, max(0, m.start() - 12), m.start())
                    or _AMOUNT_AFTER_RE.match(para, m.end())):
                continue
            window = (max(0, m.start() - RATE_NEAR), m.end() + RATE_NEAR)
            if near and not (_CONTEXT_START_RE.search(para, *window) and RATE_CONTEXT_RE.search(para, *window)):
                continue
            return m.start(), m.end()
    return None


def parse_deck(data, slug, kind, path=None, space=None):
    """Parse deck-file bytes into a DeckFile. Raises DeckFileError.

    space is the space the file belongs to (lib/spaces.py); by default the
    one whose deck folder holds path, else home."""
    if kind not in KINDS:
        raise DeckFileError(f"kind must be one of {KINDS}, not {kind!r}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise DeckFileError(f"not UTF-8: {e}") from None
    # Generated lines use the file's usual line ending.
    newline = "\r\n" if text.count("\r\n") * 2 > text.count("\n") else "\n"
    lines = _lines(text)
    headings = _headings(lines)
    spans = {}

    # Title: the first line.
    first = lines[0].text.lstrip("\ufeff") if lines else ""
    if not first.startswith("# "):
        raise DeckFileError("the first line must be the '# Title' heading")
    title = first[2:].strip()

    # Header bullets: consecutive '- **Key:** value' lines after the title.
    i = 1
    while i < len(lines) and not lines[i].text.strip():
        i += 1
    header, start = [], i
    while i < len(lines) and FIELD_RE.match(lines[i].text):
        key, value = FIELD_RE.match(lines[i].text).groups()
        line = lines[i]
        header.append(HeaderField(key.strip(), value, line.text, text[line.start + len(line.text):line.end]))
        i += 1
    pos = lines[start].start if start < len(lines) else len(text)
    spans["header"] = (pos, lines[i - 1].end if header else pos)

    # The "Decklist changed" line under the header, after any blank lines
    # (usually one). Markers straight after it (an older Deck Lab could add a
    # second one) are part of it too; the first has the date.
    changed_on = None
    j = i
    while header and j < len(lines):
        if MARKER_RE.match(lines[j].text.strip()):
            changed_on = changed_on or MARKER_RE.match(lines[j].text.strip()).group(1)
            spans["marker"] = (spans["header"][1], lines[j].end)
        elif lines[j].text.strip():
            break
        j += 1

    def heading(match, level=None):
        # The title (the first line) is never one of the headings looked for,
        # so a deck titled "Owned-only version of Elves" still reads its list.
        for idx, lvl, htext in headings:
            if idx > 0 and match(htext.lower()) and (level is None or lvl == level):
                return idx, lvl
        return None

    # Target list: the first fenced block under "## Decklist", before any
    # "Owned-only version" heading inside that section (a Decklist section
    # with no list of its own mustn't take the owned-only list as its target).
    target = {}
    found = heading(lambda h: h.startswith("decklist"), 2)
    owned_heading = heading(lambda h: h.startswith(("owned-only version", "substitute version")))
    if found:
        end = _section_end(lines, headings, found[0], 2)
        if owned_heading and found[0] < owned_heading[0] < end:
            end = owned_heading[0]
        block = _find_block(lines, found[0] + 1, end, "decklist")
        if block:
            spans["target"] = (lines[block[0]].end, lines[block[1]].start)
            try:
                target = parse_decklist(text[slice(*spans["target"])])
            except DecklistError as e:
                raise DecklistError(f"decklist: {e}") from None

    # Considering list (E2-S23): the first fenced block under "## Considering", card lines only.
    # Cards that might go in the deck: kept with it but counted nowhere. Only DeckFile.considering
    # holds them, so no table, pool, packing, token, stats, Forge or sleeve reader (which all read
    # target and owned) sees them, and render_deck_file copies the block as written.
    considering = None
    found = heading(lambda h: h == "considering", 2)
    if found:
        block = _find_block(lines, found[0] + 1, _section_end(lines, headings, found[0], 2), "considering")
        if block:
            spans["considering"] = (lines[block[0]].end, lines[block[1]].start)
            try:
                listed = parse_decklist(text[slice(*spans["considering"])])
            except DecklistError as e:
                raise DecklistError(f"Considering list: {e}") from None
            if set(listed) - {"Deck"}:
                raise DecklistError("Considering list: card lines only, with no section headers "
                                    f"({', '.join(sorted(set(listed) - {'Deck'}))})")
            considering = listed.get("Deck", [])

    # Owned-only list: the first fenced block under "### Owned-only version".
    owned = None
    found = owned_heading
    if found:
        block = _find_block(lines, found[0] + 1, _section_end(lines, headings, found[0], 6),
                            "owned-only version")
        if block:
            spans["owned"] = (lines[block[0]].end, lines[block[1]].start)
            try:
                owned = parse_decklist(text[slice(*spans["owned"])])
            except DecklistError as e:
                raise DecklistError(f"Play-now list: {e}") from None
    if "owned" not in spans:
        # Where a new owned-only list goes: the end of "## Substitutes", else
        # before "## Notes", else the end of the file.
        subs = heading(lambda h: h == "substitutes", 2)
        notes = heading(lambda h: h == "notes", 2)
        if subs:
            end = _section_end(lines, headings, subs[0], 2)
        elif notes:
            end = notes[0]
        else:
            end = len(lines)
        pos = lines[end].start if end < len(lines) else len(text)
        spans["owned_insert"] = (pos, pos)

    # Owned-vs-needed table: rows after the header and |---| lines.
    rows, total, prices = None, None, None
    found = heading(lambda h: h.startswith("owned vs"), 2)
    if found:
        end = _section_end(lines, headings, found[0], 6)
        for j in range(found[0] + 1, end - 1):
            cells = [c.strip() for c in lines[j].text.strip().strip("|").split("|")]
            if lines[j].text.startswith("|") and cells == TABLE_COLUMNS:
                if not re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", lines[j + 1].text):
                    raise DeckFileError("owned-vs-needed table: no |---| line under the header")
                # The price stamp in the text between the heading and the table.
                # An exchange rate stated some other way there (in any
                # paragraph, the stamp's own included) is remembered, since
                # new prices can't be stamped without contradicting it.
                other = None
                for para in _paragraphs(lines[found[0] + 1:j]):
                    for line in para:
                        m = PRICE_STAMP_RE.search(line.text)
                        if m and prices is None:
                            prices = PriceStamp(float(m.group(1)), m.group(2), m.group(3))
                            spans["prices"] = (line.start + m.start(), line.start + m.end())
                    span = (para[0].start, para[-1].start + len(para[-1].text))
                    if other is None and _rate_in(_without_stamp(text, span, spans.get("prices"))):
                        other = span
                if other:
                    spans["prices_other"] = other
                elif prices is None:
                    spans["prices_insert"] = (lines[j].start, lines[j].start)
                k = first_row = j + 2
                rows = []
                while k < len(lines) and lines[k].text.startswith("|"):
                    row = _parse_row(lines[k].text, k + 1)
                    if isinstance(row, TotalRow):
                        if total is not None:
                            raise DeckFileError("owned-vs-needed table: two total rows")
                        total = row
                    elif total is not None:
                        raise DeckFileError("owned-vs-needed table: rows after the total row")
                    else:
                        rows.append(row)
                    k += 1
                row_start = lines[first_row].start if first_row < len(lines) else len(text)
                spans["table"] = (row_start, lines[k - 1].end if k > first_row else row_start)
                break

    return DeckFile(
        path=Path(path) if path else None, slug=slug, kind=kind, title=title,
        header=header, target=target, owned=owned, rows=rows, total=total,
        changed_on=changed_on, sha256=hashlib.sha256(data).hexdigest(),
        text=text, newline=newline, prices=prices, spans=spans, space=space or _space_of(path),
        considering=considering)


def _space_of(path):
    if not path:
        return "home"
    from decklab.lib import spaces
    return spaces.space_of_path(path) or "home"


def read_deck_file(path, kind=None, space=None):
    """Read and parse one deck file. The kind comes from its folder by
    default, and the space from where that folder is (see parse_deck)."""
    path = Path(path)
    kind = kind or path.parent.name
    return parse_deck(path.read_bytes(), path.stem, kind, path, space)


# Used by edit.py and render.py: text that must stay on one line.
def _one_line(*texts):
    for text in texts:
        if "\n" in text or "\r" in text:
            raise ValueError(f"line breaks aren't allowed here: {text!r}")
