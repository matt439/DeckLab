"""A trial deck's header line (E3-S39): a published precon the space doesn't own,
saved as an idea deck so it can be tested in Forge before it's bought.

    - **Trial:** precon KeenEngineering_FDC

The value is "precon" and MTGJSON's deck file name (precons.FILE_RE). Every save
keeps the line as written, except that a status other than idea removes it
(edit.set_status: someone is building the deck now, so it's no longer a trial).
A deck is a trial deck only while the line parses and its status is idea (or
blank): trial_of(). Nothing else checks it; deck push and deck new accept it.
"""
from decklab.lib.precons import FILE_RE

from .deckfile import HeaderField

TRIAL_FIELD = "Trial"
PREFIX = "precon"


def parse_trial(value):
    """The precon file a Trial value names ("precon <FILE>"), or None for anything else."""
    parts = (value or "").split()
    if len(parts) != 2 or parts[0].casefold() != PREFIX or not FILE_RE.fullmatch(parts[1]):
        return None
    return parts[1]


def format_trial(file):
    """The Trial line's value for a precon file; ValueError for a name that isn't one."""
    if not isinstance(file, str) or not FILE_RE.fullmatch(file):
        raise ValueError("A trial names an MTGJSON deck file")
    return f"{PREFIX} {file}"


def _indices(deck):
    return [index for index, field in enumerate(deck.header)
            if field.key.casefold() == TRIAL_FIELD.casefold()]


def set_trial(deck, file):
    """Write the Trial line for file (replacing any), or remove it for None; a no-op keeps it verbatim."""
    value = None if file is None else format_trial(file)
    indices = _indices(deck)
    if value and len(indices) == 1 and parse_trial(deck.header[indices[0]].value) == file:
        return
    if indices:
        first = indices[0]
        ending = deck.header[first].end
        deck.header[:] = [field for index, field in enumerate(deck.header) if index not in indices[1:]]
        if value:
            deck.header[first] = HeaderField(TRIAL_FIELD, value, None, ending)
        else:
            del deck.header[first]
    elif value:
        deck.header.append(HeaderField(TRIAL_FIELD, value))


def trial_field(deck):
    """The precon file the deck's Trial line names, whatever its status (None without one)."""
    return parse_trial(deck.get_field(TRIAL_FIELD))


def trial_of(deck):
    """The precon file of a trial deck: the Trial line's, while the deck's status is idea or blank."""
    file = trial_field(deck)
    return file if file is not None and deck.status in (None, "idea") else None
