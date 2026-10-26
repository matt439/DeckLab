"""Date-only box-check history and read-only comparisons of physical card counts.

Observations never repair a list or inventory. Expected rows are the authoritative
physical recipe, including named/anonymous markers; identity includes its section
and role, so an unexpected real card cannot silently replace a missing marker.
"""
from datetime import date
import re

from .deckfile import HeaderField
from .decklist import SECTIONS

FIELD = "Box checked"
MAX_QUANTITY = 9999
MAX_ROWS = 2000
MAX_EXTRAS = 200


class BoxCheckError(ValueError):
    """A date or incomplete/ambiguous observation cannot record a box check."""


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise BoxCheckError("Box checked must be a date in YYYY-MM-DD form.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise BoxCheckError("Box checked must be a valid calendar date.") from None
    return value


def checked_on(deck):
    """One valid date or None; malformed or duplicate headers assert no date."""
    fields = [field for field in deck.header if field.key.casefold() == FIELD.casefold()]
    if len(fields) != 1:
        return None
    try:
        return _date(fields[0].value)
    except BoxCheckError:
        return None


def record_date(deck, value):
    """Set only this date, replacing a raw header so render writes its new value.

    A single malformed date may be replaced; duplicate headers refuse before any
    mutation. Other headers, physical/intended lists and prose remain untouched.
    """
    value = _date(value)
    indices = [index for index, field in enumerate(deck.header) if field.key.casefold() == FIELD.casefold()]
    if len(indices) > 1:
        raise BoxCheckError("The deck has more than one Box checked header. Correct it before recording a check.")
    if indices:
        index = indices[0]
        if deck.header[index].value == value:
            return False
        deck.header[index] = HeaderField(FIELD, value, raw=None, end=deck.header[index].end)
    else:
        deck.header.append(HeaderField(FIELD, value))
    return True


def _quantity(value, *, zero=False):
    return isinstance(value, int) and not isinstance(value, bool) and (0 if zero else 1) <= value <= MAX_QUANTITY


def _name(value):
    return (isinstance(value, str) and bool(value) and value == value.strip() and len(value) <= 200
            and not any(character in value for character in "\r\n\0"))


def _expected(sections):
    if not isinstance(sections, dict) or set(sections) - set(SECTIONS) or not sections.get("Deck"):
        raise BoxCheckError("The physical recipe needs its recorded main deck and valid sections.")
    found = {}
    for section in SECTIONS:
        rows = sections.get(section, [])
        if not isinstance(rows, list) or len(found) + len(rows) > MAX_ROWS:
            raise BoxCheckError("The physical recipe has too many or invalid rows.")
        identities = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not {"kind", "name", "for", "quantity"} <= set(row):
                raise BoxCheckError("Each physical recipe row needs its role, names and quantity.")
            kind, name, target = row["kind"], row["name"], row["for"]
            if kind not in ("card", "marker") or not _quantity(row["quantity"]):
                raise BoxCheckError("The physical recipe has an invalid role or quantity.")
            if kind == "card" and (not _name(name) or target is not None) \
                    or kind == "marker" and (name is not None and not _name(name) or not _name(target)):
                raise BoxCheckError("The physical recipe has invalid card or marker names.")
            identity = kind, name, target
            if identity in identities:
                raise BoxCheckError("The physical recipe has duplicate rows in one section.")
            identities.add(identity)
            found[section, index] = {"section": section, "kind": kind, "name": name, "for": target,
                                     "quantity": row["quantity"]}
    return found


def compare(sections, rows, extras, *, canonical_name):
    """Compare every expected row once with independent, canonical extra cards.

    rows are {section,row,quantity}, with a zero-based per-section row and an
    explicit integer 0..9999. extras are {section,name,quantity}, positive and
    unique by canonical name within a section. Overfound expected rows and
    explicit extras stay separate; no cross-section, role or name netting occurs.
    """
    expected = _expected(sections)
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise BoxCheckError("Review every physical recipe row once, using 0 when none were found.")
    observations = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"section", "row", "quantity"}:
            raise BoxCheckError("Each reviewed row needs its section, row number and found quantity.")
        section, index = row["section"], row["row"]
        if not isinstance(section, str) or not isinstance(index, int) or isinstance(index, bool) \
                or (section, index) not in expected or (section, index) in observations:
            raise BoxCheckError("Review each offered physical row exactly once in its recorded section.")
        if not _quantity(row["quantity"], zero=True):
            raise BoxCheckError("A found quantity must be a whole number from 0 to 9999.")
        observations[section, index] = row["quantity"]
    if not isinstance(extras, list) or len(extras) > MAX_EXTRAS:
        raise BoxCheckError(f"Extra cards must be a list of at most {MAX_EXTRAS} rows.")
    additional, seen = [], set()
    for row in extras:
        if not isinstance(row, dict) or set(row) != {"section", "name", "quantity"}:
            raise BoxCheckError("Each extra card needs its section, name and physical quantity.")
        if row["section"] not in SECTIONS or not _name(row["name"]) or not _quantity(row["quantity"]):
            raise BoxCheckError("Extra cards need a valid section, name and positive quantity up to 9999.")
        try:
            name = canonical_name(row["name"])
        except ValueError:
            raise BoxCheckError("An extra card name cannot be checked; use the exact full card name.") from None
        if not _name(name):
            raise BoxCheckError("An extra card name cannot be checked; use the exact full card name.")
        identity = row["section"], name
        if identity in seen:
            raise BoxCheckError("List an extra card only once in each section.")
        seen.add(identity)
        additional.append({"section": row["section"], "kind": "card", "name": name, "for": None,
                           "quantity": row["quantity"]})
    missing, extra = [], []
    for identity, row in expected.items():
        delta = observations[identity] - row["quantity"]
        if delta:
            (extra if delta > 0 else missing).append({**row, "quantity": abs(delta)})
    additional.sort(key=lambda row: (SECTIONS.index(row["section"]), row["name"].casefold(), row["name"]))
    extra.extend(additional)
    return {"expected_cards": sum(row["quantity"] for row in expected.values()),
            "found_cards": sum(observations.values()) + sum(row["quantity"] for row in additional),
            "missing": missing, "extra": extra}
