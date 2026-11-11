"""Shared typed card searches for the editor and Collection, without pool or permission reads."""
import math
import operator
import re

from decklab.lib import cards
from .common import ApiError

ALIASES = {"o": "o", "oracle": "o", "t": "t", "type": "t"}
COMPARISONS = {"<=": operator.le, ">=": operator.ge, "=": operator.eq, "<": operator.lt, ">": operator.gt}
_TERM_RE = re.compile(r'(?<!\S)(-?)([A-Za-z]+)(:|<=|>=|=|<|>)("[^"]*"?|\S*)')
_CURLY_DOUBLE = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"'})
KNOWN_TERMS = ('It knows o: for rules text, t: for the type line, -o: and -t: to leave matches out, '
               'and mv<=2, mv>=5 or mv=3 for mana value.')


def parse(query):
    """Return (untyped text, [(key, value)]), preserving the old o:/t: representation.

    Quoted phrases, phone quotes, aliases, open quotes and empty terms retain the
    editor's behavior. A colon in a real card name remains ordinary name text.
    The caller retains its own untyped search scope (editor names, Collection names/rules).
    """
    query = query.translate(_CURLY_DOUBLE)
    terms, rest, unknown, last = [], [], None, 0
    for match in _TERM_RE.finditer(query):
        negative, written, comparison, raw = match.groups()
        alias = ALIASES.get(written.lower()) if comparison == ":" else None
        numeric = written.lower() == "mv" and comparison in COMPARISONS and not negative
        if alias is None and not numeric:
            unknown = unknown or match.group(0)
            continue
        rest.append(query[last:match.start()])
        last = match.end()
        value = cards.fold(raw.strip('"'))
        if not value:
            continue
        if numeric:
            try:
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= 1000:
                    raise ValueError
            except ValueError:
                raise ApiError(400, "A mana value comparison needs a number from 0 to 1000, such as mv<=2. " + KNOWN_TERMS,
                               reason="term", term=match.group(0)) from None
            terms.append(("mv" + comparison, value))
        else:
            terms.append((negative + alias, value))
    rest.append(query[last:])
    name = " ".join("".join(rest).split())
    if unknown and not cards.search_names(name, 1):
        raise ApiError(400, f"The search doesn't know the term {unknown}. " + KNOWN_TERMS,
                       reason="term", term=unknown)
    return name, terms


def matches(card, terms):
    """Every typed term must match; a negative term excludes its match.

    Rules and types cover both faces, and ~ refers to each face's own name as
    in the editor's original parser. Unknown cards cannot prove typed matches.
    """
    if not terms:
        return True
    if card is None:
        return False
    faces = card.get("faces") or []
    types = cards.fold(" // ".join(face.get("type_line", "") for face in faces) if faces else card["type_line"])
    text = cards.fold(card.get("oracle_text") or "")
    named = None
    for written, value in terms:
        if written.startswith("mv"):
            mana = card.get("cmc")
            if not isinstance(mana, (int, float)) or isinstance(mana, bool) or not math.isfinite(mana) \
                    or not COMPARISONS[written[2:]](mana, float(value)):
                return False
            continue
        key = written.removeprefix("-")
        if key == "t":
            found = value in types
        elif "~" in value:
            if named is None:
                named = text
                for own in sorted({card["name"], *(face.get("name", "") for face in faces)} - {""}, key=len, reverse=True):
                    named = named.replace(cards.fold(own), "~")
            found = value in named
        else:
            found = value in text
        if found == written.startswith("-"):
            return False
    return True
