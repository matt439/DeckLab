"""A deck's optional Usual opponents header, preserved by every other kind of save.

    - **Usual opponents:** casual/elves, commander/angels

Only the dedicated metadata save rewrites this line. The API resolves the ids
against existing visible decks; deleting a deck never rewrites its counterparts.
"""
from .deckfile import HeaderField, _one_line

USUAL_OPPONENTS_FIELD = "Usual opponents"


def parse_usual_opponents(value):
    """Ordered distinct ids from the comma-separated header value; no existence claims."""
    return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


def set_usual_opponents(deck, opponents):
    """Replace this header alone, or remove it for an empty list; keep a no-op verbatim."""
    if not isinstance(opponents, (list, tuple)) or any(not isinstance(item, str) or not item.strip()
                                                    or "," in item for item in opponents):
        raise ValueError("Usual opponents must be a list of deck ids")
    value = ", ".join(dict.fromkeys(item.strip() for item in opponents))
    _one_line(value)
    indices = [index for index, field in enumerate(deck.header)
               if field.key.casefold() == USUAL_OPPONENTS_FIELD.casefold()]
    if value and len(indices) == 1 and parse_usual_opponents(deck.header[indices[0]].value) == parse_usual_opponents(value):
        return
    if indices:
        first = indices[0]
        ending = deck.header[first].end
        deck.header[:] = [field for index, field in enumerate(deck.header) if index not in indices[1:]]
        if value:
            deck.header[first] = HeaderField(USUAL_OPPONENTS_FIELD, value, None, ending)
        else:
            del deck.header[first]
    elif value:
        deck.header.append(HeaderField(USUAL_OPPONENTS_FIELD, value))
