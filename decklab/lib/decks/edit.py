"""Editing a parsed DeckFile: the header fields Deck Lab owns (set_field,
set_status and the rest), the editor's apply_edit(), the "Decklist changed"
date, Deck Lab's Notes labels, and the owned-vs-needed rows (set_table,
table_changes). render.py then writes the edited model back.
"""
import re
from collections import Counter

from decklab.lib.cards import fold

from .deckfile import (BUILT_VERSIONS, OWNED_FIELDS, PLAYERS, STATUSES, HeaderField, TableRow, TotalRow,
                       _leading_word, _one_line)
from .decklist import _BASIC_KEYS, categories, clean_sections

# The header fields the editor changes (apply_edit), by the name the page uses.
EDIT_FIELDS = {"status": "Status", "player": "Played by", "archetype": "Archetype",
               "built_version": "Built version", "target_bracket": "Target bracket", "sleeves": "Sleeves",
               "deck_box": "Deck box"}
BRACKET_NUMBERS = range(1, 6)               # Commander Brackets 1-5
# The Notes-cell labels Deck Lab writes (pool.table_rows makes them), each a
# whole "; "-separated part: copies on the way, copies other decks hold, the
# cards the total leaves out, and the older precon labels written by hand
# before Deck Lab, which it replaces. Only a run of these at the start of a
# cell is Deck Lab's; set_table replaces that run and keeps the rest.
LABEL_RE = re.compile(r"\d+ on the way \([^;|]+\)|\d+ in use in [^;|]+|not counted, no price: [^;|]+"
                      r"|on the way \([^;|,()]+ precon\)")


def _owned_key(key):
    for name in OWNED_FIELDS:
        if name.lower() == key.lower():
            return name
    raise ValueError(f"Deck Lab doesn't own the header field {key!r}")


def set_field(deck, key, value):
    """Set an owned header field. A value of None removes it.

    A missing field is added in OWNED_FIELDS order after the fields before it.
    """
    key = _owned_key(key)
    for i, f in enumerate(deck.header):
        if f.key.lower() == key.lower():
            if value is None:
                del deck.header[i]
            else:
                f.value = value
            return
    if value is None:
        return
    rank = OWNED_FIELDS.index(key)
    at = 0
    for i, f in enumerate(deck.header):
        other = next((n for n in OWNED_FIELDS if n.lower() == f.key.lower()), None)
        if other and OWNED_FIELDS.index(other) < rank:
            at = i + 1
    deck.header.insert(at, HeaderField(key, value))


def _set_leading_word(deck, key, word, words):
    if word not in words:
        raise ValueError(f"{key} must be one of {words}, not {word!r}")
    value = deck.get_field(key)
    if value and _leading_word(value, words):
        value = re.sub(r"^([\s`*_\"']*)[A-Za-z]+", lambda m: m.group(1) + word, value, count=1)
    else:
        value = word
    set_field(deck, key, value)


def set_status(deck, status):
    """Set Status to idea / building / built, keeping any text after the word."""
    _set_leading_word(deck, "Status", status, STATUSES)
    if status != "built":
        from . import assembled
        assembled.clear(deck)


def set_player(deck, player):
    """Set Played by to user / wife / either, keeping any text after the word."""
    _set_leading_word(deck, "Played by", player, PLAYERS)


def set_built_version(deck, version):
    """Say which list a built deck holds: "target" or "owned" (written
    "owned-only"), or None to remove the field. pool.py counts that list's
    cards as in use."""
    if version is not None and version not in BUILT_VERSIONS:
        raise ValueError(f"Built version must be one of {BUILT_VERSIONS}, not {version!r}")
    set_field(deck, "Built version", {"target": "target", "owned": "owned-only"}.get(version))


def _set_built_line(deck, key, value):
    """Set one of a built deck's accessory lines (Sleeves or Deck box) to one
    line of text, trimmed: an accessory id or free text. None removes the
    field. A field that already says that value is left as written."""
    if value is None:
        set_field(deck, key, None)
        return
    value = value.strip()
    _one_line(value)
    if not value:
        raise ValueError(f"{key} needs a value (or None to remove the field)")
    if (deck.get_field(key) or "").strip() != value:
        set_field(deck, key, value)


def set_sleeves(deck, sleeves):
    """Set a built deck's sleeves (an accessory id, or a colour as free text),
    or None to remove the field."""
    _set_built_line(deck, "Sleeves", sleeves)


def set_deck_box(deck, box):
    """Set a built deck's deck box (an accessory id, or free text), or None to
    remove the field."""
    _set_built_line(deck, "Deck box", box)


def set_target_bracket(deck, number, name=None):
    """Set a Commander deck's Target bracket to number (1-5), written
    "3 (Upgraded)" when the bracket's name is given; None removes the field.
    A field that already starts with that number is left as written."""
    if number is None:
        set_field(deck, "Target bracket", None)
        return
    if isinstance(number, bool) or not isinstance(number, int) or number not in BRACKET_NUMBERS:
        raise ValueError(f"Target bracket must be a whole number from 1 to 5, not {number!r}")
    if deck.target_bracket != number:
        set_field(deck, "Target bracket", f"{number} ({name})" if name else str(number))


def mark_decklist_changed(deck, date):
    """Add (or update) the 'Decklist changed in Deck Lab on DATE' line."""
    date = str(date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise ValueError(f"date must be YYYY-MM-DD, not {date!r}")
    deck.changed_on = date


def apply_edit(deck, target=None, owned=None, fields=None, date=None, bracket_names=None, considering=None):
    """Apply an edit from the editor to a parsed deck file (PLAN.md part 2).

    target and owned are the lists {section: [DeckLine]} as they should be
    (None leaves a list as it is). An owned list for a file without one
    starts its owned-only version; an owned-only version can't be emptied.
    fields maps EDIT_FIELDS keys to the new values: status, player and
    archetype (None leaves them), built_version ("target", "owned" or None
    for no field), target_bracket (1-5 or None; bracket_names {number:
    name} writes "2 (Core)"), sleeves and deck_box (an accessory id or free
    text, or None for no field).
    A value equal to what the file says now changes nothing, so the words
    after "either" in "Played by: either. Suits whoever..." stay. When either list changes and date is given, the
    'Decklist changed' line gets that date; header-only edits don't add it.

    considering is the Considering list as it should be ([DeckLine]; None
    leaves it). It is no decklist: a change to it alone doesn't add the
    'Decklist changed' line or change the table, and a card moved into the
    Planned list leaves it in the same save.

    Returns {"decklist": bool, "fields": [the keys that changed]}, and
    "considering": bool when considering was given, with "categories": True
    when a list changed only in its lines' categories (E2-S24; "decklist"
    stays False). Raises
    ValueError for anything the file can't take (a Commander section in a
    casual deck, an unknown field, a value with a line break); the deck may
    then be half-edited, so read it again rather than render it.
    """
    changes = {"decklist": False, "fields": []}
    if considering is not None:
        was = deck.considering or []
        # DeckLine equality leaves categories out (E2-S24): a change of one alone is still a change.
        changes["considering"] = (list(considering) != was
                                  or categories({"": list(considering)}) != categories({"": was}))
        if changes["considering"]:
            deck.considering = list(considering)
    for version, sections in (("target", target), ("owned", owned)):
        if sections is None:
            continue
        sections = clean_sections(sections)
        if deck.kind != "commander" and "Commander" in sections:
            raise ValueError("a casual deck can't have a Commander section")
        current = getattr(deck, version)
        if version == "owned" and not sections:
            if current:
                raise ValueError("the Play-now list can't be emptied or removed here")
            continue
        if current is None or clean_sections(current) != sections:
            setattr(deck, version, sections)
            changes["decklist"] = True
        elif categories(clean_sections(current)) != categories(sections):
            # Only the builder's own categories (E2-S24): the same cards, so no
            # "Decklist changed" line and no table to work out again.
            setattr(deck, version, sections)
            changes["categories"] = True

    for key, value in (fields or {}).items():
        if key not in EDIT_FIELDS:
            raise ValueError(f"unknown field {key!r}; the editor changes {', '.join(EDIT_FIELDS)}")
        if key == "status":
            if value is not None and deck.status != value:
                set_status(deck, value)
                changes["fields"].append(key)
        elif key == "player":
            if value is not None and deck.player != value:
                set_player(deck, value)
                changes["fields"].append(key)
        elif key == "archetype":
            if value is not None:
                value = value.strip()
                _one_line(value)
                if (deck.get_field("Archetype") or "").strip() != value or deck.get_field("Archetype") is None:
                    set_field(deck, "Archetype", value)
                    changes["fields"].append(key)
        elif key == "built_version":
            if deck.built_version != value:
                set_built_version(deck, value)
                changes["fields"].append(key)
        elif key in ("sleeves", "deck_box"):
            name = EDIT_FIELDS[key]
            if value is None:
                if deck.get_field(name) is not None:
                    _set_built_line(deck, name, None)
                    changes["fields"].append(key)
            elif (deck.get_field(name) or "").strip() != value.strip():
                _set_built_line(deck, name, value)
                changes["fields"].append(key)
        elif key == "target_bracket":
            if deck.kind != "commander" and value is not None:
                raise ValueError("only Commander decks have a Target bracket")
            if deck.target_bracket != value:
                set_target_bracket(deck, value, (bracket_names or {}).get(value))
                changes["fields"].append(key)
    if changes["decklist"] and date is not None:
        mark_decklist_changed(deck, date)
    return changes


def clean_label(text):
    """A Notes label as Deck Lab writes it: ';' (which separates the parts of
    a cell) becomes ',', '|' (which ends the cell) becomes '/', and line
    breaks become spaces. Raises ValueError if the result isn't in one of
    LABEL_RE's forms, since it couldn't be recognised on the next save."""
    cleaned = " ".join(str(text).replace(";", ",").replace("|", "/").split())
    if not LABEL_RE.fullmatch(cleaned):
        raise ValueError(f"not a Notes label Deck Lab can read back: {text!r}")
    return cleaned


def _split_notes(cell):
    """(labels, rest): the parts at the start of a Notes cell that are Deck
    Lab's labels, and the rest of the cell exactly as written."""
    labels, pos = [], 0
    while True:
        cut = cell.find(";", pos)
        part = (cell[pos:] if cut == -1 else cell[pos:cut]).strip()
        if not LABEL_RE.fullmatch(part):
            return labels, cell[pos:]
        labels.append(part)
        if cut == -1:
            return labels, ""
        pos = cut + 1


def _merge_notes(old_cell, labels, empty="  "):
    """The notes cell with Deck Lab's labels in place of the old ones.

    The rest of old_cell (hand-written notes) is kept after the labels, byte
    for byte apart from the spaces around it. A cell whose labels haven't
    changed (or labels None) is returned untouched; `empty` is the cell for
    nothing at all."""
    if labels is None:
        return empty if old_cell is None else old_cell
    labels = [clean_label(label) for label in labels]
    old_labels, rest = _split_notes(old_cell or "")
    if old_cell is not None and old_labels == labels:
        return old_cell
    parts = labels + ([rest.strip()] if rest.strip() else [])
    return f" {'; '.join(parts)} " if parts else empty


def _card_key(name):
    """A loose key for matching a card across the decklist and the table:
    the front face, folded (case, accents, quotes), without a trailing
    "(set)" that a decklist line may have kept in the name. pool.py resolves
    names to exact Scryfall names; this matches those to the names as written."""
    front = name.split("//")[0].strip()
    return fold(re.sub(r"\s+\([A-Za-z0-9]{2,8}\)$", "", front))


def _check_rows_match_target(deck, rows):
    """Raise ValueError unless each card's Need is its count across every
    section of deck.target (basic lands left out), as pool.py works it out."""
    shown, need, table = {}, Counter(), Counter()
    for lines in deck.target.values():
        for line in lines:
            key = _card_key(line.name)
            if key not in _BASIC_KEYS:
                need[key] += line.quantity
                shown.setdefault(key, line.name)
    for row in rows:
        key = _card_key(row.card)
        table[key] += row.need
        shown.setdefault(key, row.card)
    wrong = sorted((k for k in need.keys() | table.keys() if need[k] != table[k]), key=shown.get)
    if wrong:
        listed = ", ".join(f"{shown[k]} (list {need[k]}, table {table[k]})" for k in wrong[:5])
        more = f" and {len(wrong) - 5} more" if len(wrong) > 5 else ""
        raise ValueError(f"the owned-vs-needed table must describe the Planned list as it is now, "
                         f"but its Need doesn't match for {listed}{more}")


def set_table(deck, rows, total, prices=None):
    """Replace the owned-vs-needed rows and total, keeping each card's notes.

    The table always describes the target list: rows must come from
    deck.target as it is now (pool.deck_table(deck) works them out), and a
    Need that doesn't match it raises ValueError, so an owned-only list or a
    list read before an edit can't replace the table.

    Rows are written in the order given (sort_table_rows gives the files'
    order). A row whose notes_cell is None takes the notes of the old row for
    the same card (matched by exact name, else by front face, so "Murderous
    Rider" finds "Murderous Rider // Swift End"), or an empty cell for a new
    card, with the row's labels replacing the labels Deck Lab wrote at the
    start of the cell before. The total row's notes are carried over the
    same way. prices is the PriceStamp the rows' prices were worked out with;
    it replaces the stamp above the table (or adds a PRICE_NOTE paragraph
    there), so the prices are never labelled with an old rate. With no
    prices (None), the stamp stays, and rows without prices (aud_each None)
    keep only the price cells that still match it (see TableRow).
    """
    _check_rows_match_target(deck, rows)
    old_rows = deck.rows or []
    exact = {r.card: r for r in old_rows}
    loose = {}
    for r in old_rows:
        loose.setdefault(_card_key(r.card), r)
    new_rows, all_kept = [], True
    for row in rows:
        old = exact.get(row.card) or loose.get(_card_key(row.card))
        notes = row.notes_cell
        if notes is None:
            notes = _merge_notes(old.notes_cell if old else None, row.labels)
        each, missing = row.aud_each, row.aud_missing
        if each is None or missing is None:
            same = old is not None and (old.need, old.owned, old.missing) == (row.need, row.owned, row.missing)
            each, missing = (old.aud_each, old.aud_missing) if same else ("", "")
            all_kept = all_kept and (same or not row.missing)
        new_rows.append(TableRow(row.card, row.need, row.owned, row.missing, each, missing, notes))
    deck.rows = new_rows
    if total is not None:
        old = deck.total
        notes = total.notes_cell
        if notes is None:
            notes = _merge_notes(old.notes_cell if old else None, total.labels, empty=" ")
        aud = total.aud_missing
        if aud is None:
            aud = old.aud_missing if all_kept and old is not None and old.missing == total.missing else ""
        total = TotalRow(total.missing, aud, total.label, notes)
    deck.total = total
    if prices is not None:
        deck.prices = prices


def sort_table_rows(rows):
    """The deck files' row order: cards with something missing first, then the
    rest, each group by plain (case-sensitive) string order of the card name."""
    return sorted(rows, key=lambda r: (r.missing == 0, r.card))


def table_changes(deck, rows):
    """How the deck's owned-vs-needed rows differ from rows (TableRows as
    pool.deck_table works them out now): [{"card", "was", "now"}], each side
    {"need", "owned", "missing", "labels": [Deck Lab's labels]}, or None for a
    card only on the other side. Only those count: prices, the rate and
    hand-written notes don't, so a table that is only out of date on price
    isn't listed. [] when they match, or when the file has no table."""
    if deck.rows is None:
        return []

    def state(row, labels):
        return {"need": row.need, "owned": row.owned, "missing": row.missing, "labels": list(labels)}

    old, new = {}, {}
    for row in deck.rows:
        old.setdefault(_card_key(row.card), (row.card, state(row, _split_notes(row.notes_cell or "")[0])))
    for row in rows:
        labels = ([clean_label(label) for label in row.labels] if row.labels is not None
                  else _split_notes(row.notes_cell or "")[0])
        new.setdefault(_card_key(row.card), (row.card, state(row, labels)))
    out = []
    for key in sorted(old.keys() | new.keys(), key=lambda k: (new.get(k) or old[k])[0]):
        was, now = old.get(key), new.get(key)
        if (was and was[1]) != (now and now[1]):
            out.append({"card": (now or was)[0], "was": was[1] if was else None, "now": now[1] if now else None})
    return out


def format_aud(amount):
    """'~$0.40' for a price estimate in AUD (the table's cell format)."""
    return f"~${amount:,.2f}"
