"""Durable physical assembly, independent of mutable intended decklists.

Legacy built decks without this header hold their usual built list. Packing
installs an explicit snapshot; subsequent list edits cannot move physical cards.
"""
import hashlib
import json

from .deckfile import HeaderField
from .decklist import DeckFileError, SECTIONS, clean_sections, format_line, parse_line

FIELD = "Assembled"
GENERATION = "Assembly generation"
VERSIONS = ("target", "owned")


class AssembledError(DeckFileError):
    """Physical reservations cannot be read safely."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssembledError("The Assembled header has a duplicate field")
        result[key] = value
    return result


def _read(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 256 * 1024:
        raise AssembledError("The Assembled header is too large")
    try:
        raw = json.loads(value, object_pairs_hook=_object)
    except (ValueError, TypeError, RecursionError) as error:
        raise AssembledError(f"The Assembled header is not valid JSON: {error}") from None
    if not isinstance(raw, dict) or set(raw) != {"version", "sections"} or raw["version"] not in VERSIONS:
        raise AssembledError("Assembled needs a list version and section snapshots")
    sections = raw["sections"]
    if not isinstance(sections, dict) or not sections or set(sections) - set(SECTIONS):
        raise AssembledError("Assembled has invalid deck sections")
    result, count, copies = {}, 0, 0
    for section, lines in sections.items():
        if not isinstance(lines, list):
            raise AssembledError("Each assembled section must contain decklist lines")
        parsed = []
        for text in lines:
            if not isinstance(text, str) or len(text) > 1000 or any(c in text for c in "\r\n\0"):
                raise AssembledError("Each assembled card must be one bounded decklist line")
            try:
                line = parse_line(text)
            except DeckFileError as error:
                raise AssembledError(str(error)) from None
            if line.quantity > 9999:
                raise AssembledError("An assembled card quantity is too large")
            parsed.append(line)
            count += 1
            copies += line.quantity
        if parsed:
            result[section] = parsed
    if count > 2000 or copies > 20000 or not result.get("Deck"):
        raise AssembledError("Assembled needs a main deck within the supported card limits")
    return {"version": raw["version"], "sections": clean_sections(result)}


def get(deck):
    fields = [f for f in deck.header if f.key.casefold() == FIELD.casefold()]
    if len(fields) > 1:
        raise AssembledError("The deck has more than one Assembled header")
    result = _read(fields[0].value) if fields else None
    if result and deck.kind != "commander" and result["sections"].get("Commander"):
        raise AssembledError("A casual deck cannot assemble a Commander section")
    return result


def _value(version, sections):
    return json.dumps({"version": version, "sections": {
        key: [format_line(line) for line in lines] for key, lines in clean_sections(sections).items()}},
        ensure_ascii=False, separators=(",", ":"))


def generation(deck):
    fields = [f for f in deck.header if f.key.casefold() == GENERATION.casefold()]
    if len(fields) > 1 or (fields and (not fields[0].value.isascii() or not fields[0].value.isdigit()
                                    or len(fields[0].value) > 18)):
        raise AssembledError("Assembly generation must be one nonnegative whole number")
    return int(fields[0].value) if fields else 0


def _set_header(deck, field, value):
    indices = [i for i, f in enumerate(deck.header) if f.key.casefold() == field.casefold()]
    if indices:
        deck.header[indices[0]] = HeaderField(field, value, end=deck.header[indices[0]].end)
    else:
        deck.header.append(HeaderField(field, value))


def install(deck, version, sections, *, force=False):
    value = _value(version, sections)
    parsed = _read(value)
    if deck.kind != "commander" and parsed["sections"].get("Commander"):
        raise AssembledError("A casual deck cannot assemble a Commander section")
    if get(deck) == parsed and not force:
        return False
    _set_header(deck, GENERATION, str(generation(deck) + 1))
    _set_header(deck, FIELD, value)
    return True


def clear(deck, *, serial=None):
    """Take apart without deleting intended lists or saved stand-in choices. The packed token
    cards (tokencards.py) go back to the pile with the rest."""
    from . import standins, tokencards
    deck.header[:] = [f for f in deck.header if f.key.casefold() != FIELD.casefold()]
    tokencards.set_token_cards(deck, None)
    if serial is not None:
        _set_header(deck, GENERATION, str(serial))
    data = standins.get_stand_ins(deck)
    if data["built"] is not None:
        data["built"] = None
        standins.set_stand_ins(deck, data)


def version(deck):
    snapshot = get(deck)
    return snapshot["version"] if snapshot else "owned" if deck.owned and deck.built_version != "target" else "target"


def sections(deck):
    if deck.status != "built":
        return {}
    snapshot = get(deck)
    if snapshot:
        return snapshot["sections"]
    return deck.owned if version(deck) == "owned" else deck.target


def needs_install(deck, selected_version, selected_sections):
    # An unchanged legacy full build is already complete; install snapshots on
    # actual packing saves, without forcing a data migration on reads.
    return version(deck) != selected_version or clean_sections(sections(deck)) != clean_sections(selected_sections)


def key(deck):
    snapshot = get(deck)
    serial = generation(deck)
    if not snapshot and not serial:
        return None
    value = _value(snapshot["version"], snapshot["sections"]) if snapshot else None
    return hashlib.sha256(json.dumps([serial, value], separators=(",", ":")).encode()).hexdigest()
