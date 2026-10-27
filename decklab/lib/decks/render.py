"""Writing a DeckFile back as text: render_deck_file() rebuilds only the
parts Deck Lab owns and copies everything else from the text as read, and
an owned part that didn't change is copied too. other_rate() says what
stops a table being repriced, and new_deck_text() is a new file's text.
"""
import re
from dataclasses import astuple

from .deckfile import (DATE_RE, FIELD_RE, KINDS, MARKER, OWNED_FIELDS, PRICE_NOTE, PRICE_STAMP,
                       PRICE_STAMP_RE, TABLE_HEADER, TABLE_RULE, _QUOTE_CUT_RE, PriceStamp, _lines, considering_insert,
                       _one_line, _parse_row, _rate_in, _without_stamp)
from . import considering
from .decklist import DeckFileError, DecklistError, format_decklist, parse_decklist
from .edit import _merge_notes


def format_field(key, value):
    """One header line: '- **Key:** value'."""
    _one_line(key, value)
    if not key.strip() or "*" in key or ":" in key:
        raise ValueError(f"bad header field name {key!r}")
    return f"- **{key}:** {value}" if value else f"- **{key}:**"


def _cell(text):
    return f" {text} " if text else " "


def _row(cells, notes_cell):
    _one_line(notes_cell, *cells)
    if any("|" in c for c in cells):
        raise ValueError(f"'|' isn't allowed in a table cell: {cells!r}")
    return "|" + "|".join(_cell(c) for c in cells) + "|" + notes_cell + "|"


def format_table_row(row):
    """One owned-vs-needed row; a non-zero Missing is bold."""
    if not row.card.strip() or min(row.need, row.owned, row.missing) < 0:
        raise ValueError(f"bad table row {row!r}")
    missing = f"**{row.missing}**" if row.missing else "0"
    notes = row.notes_cell if row.notes_cell is not None else _merge_notes(None, row.labels or ())
    return _row([row.card, str(row.need), str(row.owned), missing, row.aud_each or "", row.aud_missing or ""],
                notes)


def format_total_row(total):
    aud = f"**{total.aud_missing}**" if total.aud_missing else ""
    notes = total.notes_cell if total.notes_cell is not None else _merge_notes(None, total.labels or (), " ")
    return _row([f"**{total.label}**", "", "", f"**{total.missing}**", "", aud], notes)


def _lead(before, nl):
    """The line breaks that put a blank line between `before` and new text."""
    if not before or before.endswith(nl + nl):
        return ""
    return nl if before.endswith(nl) else nl * 2


def _header_line(f):
    """A header line: as it was read, unless it's an owned field whose value
    changed (or a new one), which format_field rebuilds."""
    if f.raw is not None:
        owned = any(f.key.lower() == k.lower() for k in OWNED_FIELDS)
        m = FIELD_RE.match(f.raw)
        if not owned or (m and (m.group(1).strip(), m.group(2)) == (f.key, f.value)):
            return f.raw
    return format_field(f.key, f.value)


def _with_endings(lines, nl, last_needs_break=False):
    """Join (text, ending) pairs. Each line keeps its own ending (None for a
    new line means nl); one that had none, at the end of the file, gets nl
    when a line now follows it."""
    out = []
    for i, (text, end) in enumerate(lines):
        if end is None or (not end.endswith("\n") and (i < len(lines) - 1 or last_needs_break)):
            end = nl
        out.append(text + end)
    return "".join(out)


def _render_header(deck, nl, marker=""):
    """The header lines, then `marker` (the 'Decklist changed' line and the
    blank line before it) when that goes straight after them."""
    text = _with_endings([(_header_line(f), f.end) for f in deck.header], nl, bool(marker)) + marker
    start, end = deck.spans["header"]
    after = deck.text[end:]
    if text and start == end:
        # A new header: blank lines between it and the title and prose.
        text = _lead(deck.text[:start], nl) + text + (nl if after and not after.startswith(nl) else "")
    elif marker and after and not after.startswith(("\n", "\r\n")):
        text += nl          # prose straight under the header: a blank line after the marker too
    return text


def _marker_text(deck, nl):
    """The 'Decklist changed' line where the file had one: as it was read
    (with whatever blank lines were before it) while its date is the same,
    else one blank line and the line with the new date, or nothing."""
    start, end = deck.spans["marker"]
    original = deck.text[start:end]
    if not deck.changed_on:
        return ""
    if DATE_RE.search(original).group() == deck.changed_on:
        return original
    after = deck.text[end:]
    tail = nl if after and not after.startswith(("\n", "\r\n")) else ""
    return nl + MARKER.format(date=deck.changed_on) + nl + tail


def _block_text(deck, key, sections, nl):
    """A decklist block: as it was read if it still reads as `sections`
    (keeping hand formatting such as an empty Sideboard header), else rebuilt."""
    if key in deck.spans:
        original = deck.text[slice(*deck.spans[key])]
        try:
            # parse_decklist drops empty sections, so an empty one in the
            # model ("Sideboard": []) is the same list.
            if parse_decklist(original) == {name: lines for name, lines in sections.items() if lines}:
                return original
        except DecklistError:
            pass
    return format_decklist(sections, nl)


def _considering_edits(deck, nl):
    """The Considering block (considering.py): as it was read while it still reads as
    deck.considering, else rebuilt; a block under a heading that had none, or a whole new section
    after the Decklist for a deck with none (and nothing for an empty list there)."""
    spans, lines = deck.spans, deck.considering or []
    if "considering" in spans:
        original = deck.text[slice(*spans["considering"])]
        try:
            if considering.parse_considering(original) == lines:
                return [(*spans["considering"], original)]
        except DecklistError:
            pass
        return [(*spans["considering"], considering.format_considering(lines, nl))]
    if not lines:
        return []
    if "considering_block" in spans:
        pos = spans["considering_block"][0]
        return [(pos, pos, f"{nl}```{nl}{considering.format_considering(lines, nl)}```{nl}")]
    pos = considering_insert(deck.text)
    block = _lead(deck.text[:pos], nl) + considering.section_text(lines, nl)
    if pos < len(deck.text):
        block += nl         # blank line before the heading that follows
    return [(pos, pos, block)]


def _read_rows(text):
    """{row values: (line text, line ending)} for the table rows in text, so a
    row that didn't change is written back exactly as it was read."""
    found = {}
    for n, line in enumerate(_lines(text), 1):
        try:
            row = _parse_row(line.text, n)
        except DeckFileError:
            continue
        found.setdefault(astuple(row), (line.text, text[line.start + len(line.text):line.end]))
    return found


def _read_stamp(deck):
    """The PriceStamp the file has above its table as read, or None."""
    if "prices" not in deck.spans:
        return None
    m = PRICE_STAMP_RE.fullmatch(deck.text[slice(*deck.spans["prices"])])
    return PriceStamp(float(m.group(1)), m.group(2), m.group(3)) if m else None


def _price_text(deck):
    """The price stamp: as it was read if its values didn't change, else rebuilt."""
    if _read_stamp(deck) == deck.prices:
        return deck.text[slice(*deck.spans["prices"])]
    return deck.prices.text()


def _plain(text):
    """text on one line, without Markdown bold or code marks, for a message."""
    return " ".join(text.replace("**", "").replace("`", "").split())


def other_rate(deck):
    """What stops the table being repriced, for a message: None when nothing
    does, else {"paragraph": the first words of the paragraph above the table
    that states an exchange rate in its own words (ending "..." when cut),
    "found": the words taken as that rate ("converted from Scryfall at
    1.4224", "USD 1 = AUD 1.4224"), "where": "alone" (the file has no
    PRICE_STAMP above the table), "beside_stamp" (the paragraph has the
    stamp as well: this is a second rate) or "other_paragraph" (the stamp is
    in another paragraph), "stamp": the stamp as the file has it, or None}.
    Rewording the rate as PRICE_STAMP, or taking the extra rate out, lets
    Deck Lab reprice the table."""
    if "prices_other" not in deck.spans:
        return None
    span, stamp = deck.spans["prices_other"], deck.spans.get("prices")
    para = _without_stamp(deck.text, span, stamp)
    start, end = _rate_in(para) or (0, 0)
    before = para[:start]
    cuts = list(_QUOTE_CUT_RE.finditer(before))
    words = before[cuts[-1].end() if cuts else 0:].split()[-3:]
    while words and not any(ch.isalnum() for ch in words[0]):
        words.pop(0)
    tail = re.match(r"[^\s\0]*", para[end:]).group().rstrip(".,;:!?)]\"'*")
    found = _plain(" ".join(words + [para[start:end] + tail]))
    first = _plain(deck.text[slice(*span)])
    if len(first) > 60:
        cut = first.rfind(" ", 20, 61)
        first = first[:cut if cut > 0 else 60].rstrip(",;:") + "..."
    where = ("alone" if stamp is None else
             "beside_stamp" if span[0] <= stamp[0] and stamp[1] <= span[1] else "other_paragraph")
    return {"paragraph": first, "found": found, "where": where,
            "stamp": deck.text[slice(*stamp)] if stamp else None}


def render_deck_file(deck):
    """The deck file's text with the owned parts rebuilt from `deck`.

    Everything outside the owned parts is copied from deck.text unchanged, and
    so is each owned part whose value didn't change. The result keeps the
    file's line endings; save it with the inventory's deck.save operation.
    """
    nl = deck.newline
    spans = deck.spans
    edits = []

    marker = nl + MARKER.format(date=deck.changed_on) + nl if deck.changed_on else ""
    if "marker" in spans:
        edits.append((*spans["header"], _render_header(deck, nl)))
        edits.append((*spans["marker"], _marker_text(deck, nl)))
    else:
        if marker and not deck.header:
            raise DeckFileError("the file has no header fields to put the "
                                "'Decklist changed' line under")
        edits.append((*spans["header"], _render_header(deck, nl, marker)))

    if "target" in spans:
        edits.append((*spans["target"], _block_text(deck, "target", deck.target, nl)))
    elif deck.target:
        raise DeckFileError("the file has no '## Decklist' block to write the list into")

    if "owned" in spans:
        if deck.owned is None:
            raise DeckFileError("removing the Play-now list isn't supported")
        edits.append((*spans["owned"], _block_text(deck, "owned", deck.owned, nl)))
    elif deck.owned:
        pos = spans["owned_insert"][0]
        block = (f"{_lead(deck.text[:pos], nl)}### Substitute version (owned and incoming cards){nl}{nl}```{nl}"
                 f"{format_decklist(deck.owned, nl)}```{nl}")
        if pos < len(deck.text):
            block += nl         # blank line before the heading that follows
        edits.append((pos, pos, block))

    edits.extend(_considering_edits(deck, nl))

    if "prices_other" in spans and deck.prices is not None and deck.prices != _read_stamp(deck):
        other = other_rate(deck)
        fix = (f"reword it as {PRICE_STAMP!r}" if other["where"] == "alone"
               else f"take it out, leaving only the stamp {PRICE_STAMP!r}")
        raise DeckFileError(
            f"the text above the owned-vs-needed table gives an exchange rate in other words "
            f"({other['found']!r}, in the paragraph that starts {other['paragraph']!r}), so new prices "
            f"can't be stamped there without contradicting it; {fix}")
    if "prices" in spans and deck.prices is not None:
        edits.append((*spans["prices"], _price_text(deck)))
    elif "prices_insert" in spans and deck.prices is not None:
        pos = spans["prices_insert"][0]
        note = PRICE_NOTE.format(stamp=deck.prices.text())
        edits.append((pos, pos, _lead(deck.text[:pos], nl) + note + nl + nl))

    if "table" in spans:
        start, end = spans["table"]
        kept = _read_rows(deck.text[start:end])
        lines = [kept.get(astuple(r)) or (format_table_row(r), None) for r in deck.rows or []]
        if deck.total is not None:
            lines.append(kept.get(astuple(deck.total)) or (format_total_row(deck.total), None))
        text = _with_endings(lines, nl)
        if text and start == end and not deck.text[:start].endswith("\n"):
            text = nl + text        # the |---| line ends the file with no line break
        edits.append((start, end, text))
    elif deck.rows or deck.total:
        raise DeckFileError("the file has no owned-vs-needed table to write rows into")

    out, pos = [], 0
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1])):
        if start < pos:
            raise DeckFileError("overlapping owned parts")   # can't happen for parsed files
        out.append(deck.text[pos:start])
        out.append(new)
        pos = end
    out.append(deck.text[pos:])
    return "".join(out)


def new_deck_text(title, kind, fields, sections, rows=(), total=None, price_note="",
                  newline="\n", notes=""):
    """The text of a new deck file, in the same layout as the existing ones.

    fields is a list of (key, value) header fields, e.g.
    [("Format", "Casual 60-card, 1v1"), ("Played by", "either"), ("Status", "idea")].
    rows/total fill the owned-vs-needed table (or fill it later with
    set_table), and price_note is the paragraph above the table that states the
    exchange rate and date. The Substitutes section starts empty, and so does
    Notes unless notes (one paragraph) is given.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    if not title.strip() or "\n" in title or "\r" in title:
        raise ValueError(f"bad title {title!r}")
    nl = newline
    parts = [f"# {title}", ""]
    if fields:
        parts += [format_field(k, v) for k, v in fields] + [""]
    parts += ["## Decklist", "", "```"]
    text = nl.join(parts) + nl + format_decklist(sections, nl)
    parts = ["```", "", "## Owned vs needed", ""]
    if price_note:
        parts += [price_note, ""]
    parts += [TABLE_HEADER, TABLE_RULE] + [format_table_row(r) for r in rows]
    if total is not None:
        parts.append(format_total_row(total))
    parts += ["", "## Substitutes", "", "## Notes"]
    if notes:
        _one_line(notes)
        parts += ["", notes]
    return text + nl.join(parts) + nl
