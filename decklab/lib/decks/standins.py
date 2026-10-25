"""Saved physical markers for logical cards, separate from either playable list.

Choices are per list version. ``built`` records the markers actually sleeved;
receiving a real card never silently frees those markers. Only an explicit
packing completion replaces that installed recipe.
"""
from collections import Counter
import json

from .deckfile import HeaderField, _one_line
from .decklist import is_basic_land

STAND_INS_FIELD = "Stand-ins"
VERSIONS = ("target", "owned")
MAX_ROWS = 200


class StandInsError(ValueError):
    """A saved mapping cannot safely describe physical cards."""


def _rows(value):
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise StandInsError(f"Stand-ins must be a list of at most {MAX_ROWS} mappings")
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"for", "using", "qty"}:
            raise StandInsError("Each stand-in needs for, using and qty")
        for key in ("for", "using"):
            name = row[key]
            if key == "using" and name is None:
                continue
            if not isinstance(name, str) or not name.strip() or len(name) > 300:
                raise StandInsError("A stand-in's card names must be nonblank text")
            try:
                _one_line(name)
            except ValueError as error:
                raise StandInsError(str(error)) from None
            if name != name.strip():
                raise StandInsError("Stand-in card names must not have surrounding whitespace")
        if type(row["qty"]) is not int or not 1 <= row["qty"] <= 9999:
            raise StandInsError("Stand-in quantities must be positive whole numbers")
        found = next((old for old in result if old["for"] == row["for"] and old["using"] == row["using"]), None)
        if found:
            found["qty"] += row["qty"]
        else:
            result.append(dict(row))
    return result


def parse_stand_ins(value):
    """Read the optional JSON header; malformed installed recipes are never guessed."""
    empty = {"target": [], "owned": [], "built": None}
    if value is None or value == "":
        return empty
    try:
        raw = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise StandInsError("The saved Stand-ins header is not valid JSON") from None
    if not isinstance(raw, dict) or set(raw) - {*VERSIONS, "built"}:
        raise StandInsError("The saved Stand-ins header has unknown fields")
    result = {version: _rows(raw.get(version, [])) for version in VERSIONS}
    installed = raw.get("built")
    if installed is not None:
        if (not isinstance(installed, dict) or set(installed) != {"version", "cards"}
                or installed["version"] not in VERSIONS):
            raise StandInsError("Installed stand-ins need a list version and card mappings")
        installed = {"version": installed["version"], "cards": _rows(installed["cards"])}
    result["built"] = installed
    return result


def get_stand_ins(deck):
    return parse_stand_ins(deck.get_field(STAND_INS_FIELD))


def set_stand_ins(deck, data):
    """Change this header alone; an equal value keeps its original bytes."""
    data = parse_stand_ins(data)
    indices = [i for i, field in enumerate(deck.header) if field.key.casefold() == STAND_INS_FIELD.casefold()]
    if len(indices) == 1:
        try:
            if parse_stand_ins(deck.header[indices[0]].value) == data:
                return False
        except StandInsError:
            pass
    value = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if any(data.values()) else None
    if indices:
        first, ending = indices[0], deck.header[indices[0]].end
        deck.header[:] = [field for i, field in enumerate(deck.header) if i not in indices[1:]]
        if value is None:
            del deck.header[first]
        else:
            deck.header[first] = HeaderField(STAND_INS_FIELD, value, None, ending)
    elif value is not None:
        deck.header.append(HeaderField(STAND_INS_FIELD, value))
    else:
        return False
    return True


def choices_for(deck, version):
    if version not in VERSIONS:
        raise StandInsError("Choose the Planned or Play-now list")
    return get_stand_ins(deck)[version]


def installed_for(deck):
    return get_stand_ins(deck)["built"]


def validate_rows(rows, sections):
    """Validate logical targets and unambiguous marker meanings, without a pool read."""
    rows = _rows(rows)
    logical = Counter()
    for lines in sections.values():
        logical.update({line.name: sum(other.quantity for other in lines if other.name == line.name) for line in lines})
    used, meanings = Counter(), {}
    for row in rows:
        target, marker = row["for"], row["using"]
        used[target] += row["qty"]
        if is_basic_land(target) or used[target] > logical[target]:
            raise StandInsError(f"{target} is not in this list in that stand-in quantity")
        if marker is not None:
            if is_basic_land(marker) or marker in logical:
                raise StandInsError("Use a spare card absent from this list, or Any spare card for a plain basic")
            if marker in meanings and meanings[marker] != target:
                raise StandInsError(f"{marker} cannot stand for two different cards in one deck")
            meanings[marker] = target
    return rows


def set_choices(deck, version, rows):
    sections = deck.target if version == "target" else deck.owned
    if version not in VERSIONS or sections is None:
        raise StandInsError("That list version is not available")
    data = get_stand_ins(deck)
    data[version] = validate_rows(rows, sections)
    return set_stand_ins(deck, data)


def physical_counts(logical, rows, warnings=None, source="The built deck"):
    """A holder's real recipe; keep named markers reserved even after an invalid list edit."""
    result = Counter(logical)
    represented, markers = Counter(), Counter()
    for row in _rows(rows):
        target, marker, qty = row["for"], row["using"], row["qty"]
        represented[target] += qty
        if marker is not None and not is_basic_land(marker):
            markers[marker] += qty
    for target, qty in represented.items():
        if qty > logical[target] and warnings is not None:
            warnings.append(f"{source}: installed stand-ins no longer fit {target}; repack this deck")
        result[target] = max(0, logical[target] - qty)
    result.update(markers)
    return +result


def project(deck, version, warnings=None):
    """Raw presentation mappings for this displayed list; callers add pictures outside hashes."""
    warnings = [] if warnings is None else warnings
    try:
        data = get_stand_ins(deck)
        built = data["built"]
        rows = built["cards"] if deck.status == "built" and built and built["version"] == version else data[version]
        sections = deck.target if version == "target" else deck.owned
        rows = validate_rows(rows, sections or {})
    except (StandInsError, KeyError) as error:
        warnings.append(str(error))
        rows = []
    return {"version": version, "rows": rows, "warnings": warnings}


def install_stand_ins(deck, version, rows, choices=None):
    """Explicit packing completion: save the choices and the recipe actually installed."""
    sections = deck.target if version == "target" else deck.owned
    if version not in VERSIONS or sections is None:
        raise StandInsError("That list version is not available")
    data = get_stand_ins(deck)
    data[version] = validate_rows(rows if choices is None else choices, sections)
    rows = validate_rows(rows, sections)
    data["built"] = {"version": version, "cards": rows} if rows else None
    return set_stand_ins(deck, data)


def needs_install(deck, item):
    proposed = item.get("standins")
    if proposed is None:
        return False
    try:
        data = get_stand_ins(deck)
    except StandInsError:
        return False                 # the packing projection reports it and blocks completion
    rows, version = _rows(proposed.get("rows", [])), item["version"]
    installed = {"version": version, "cards": rows} if rows else None
    return data["built"] != installed or data[version] != _rows(proposed.get("choices", rows))
