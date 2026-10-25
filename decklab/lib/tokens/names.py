"""The card index and Scryfall's token, emblem and reminder face names:
whether the index is ready, a close name to suggest, which faces a token
printing has, and a row's names checked against them. Part of
decklab.lib.tokens (see its docstring).

Tests patch _faces_at here (tokens.names._faces_at); matching reads it as
names._faces_at, so it has this one binding and the package doesn't
re-export it. cards.* is read through the cards module, which tests patch."""
import difflib

from decklab.lib import cards

NAMES_UNCHECKED = "Names weren't checked: card data is still loading"


# ------------------------------------------------------------------ names

def _index():
    """The loaded card index, or a RuntimeError saying why there isn't one
    (an older format, still building, or no index file yet)."""
    try:
        return cards._get()
    except RuntimeError:
        raise
    except cards.INDEX_ERRORS as e:
        raise RuntimeError(str(e)) from e


def _ready():
    try:
        _index()
    except RuntimeError:
        return False
    return True


def _suggest(name):
    names = cards.token_face_names()
    folded = {cards.fold(n): n for n in names}
    match = difflib.get_close_matches(cards.fold(name), list(folded), n=1, cutoff=0.6)
    return folded[match[0]] if match else None


def _faces_at(set_code, number):
    """(oracle id, face names, full name) of a token printing, or None."""
    found = cards.token_faces_at(set_code, number)
    if found is None:
        return None
    oracle_id, faces = found
    return oracle_id, faces, " // ".join(faces)


def _printing_problem(row, side):
    """"tltr H13 is The Ring, not Ring" when the row's printing for this side
    is a token printing without that face; else None."""
    name, number = row[side], row[f"{side}_collector_number"]
    if not (row["set"] and number and name):
        return None
    found = _faces_at(row["set"], number)
    if found is None:
        return f"{row['set']} {number} isn't a token, emblem or reminder printing on Scryfall"
    _, faces, full = found
    if cards.fold(name) in {cards.fold(f) for f in (*faces, full)}:
        return None
    shown = faces[1] if side == "back" and len(faces) > 1 else faces[0]
    return f"{row['set']} {number} is {shown}, not {name}"


def check_names(row):
    """(row with exact Scryfall face names, warnings) for a validated row.

    A face name that differs only in case or accents is replaced with the
    exact one; an unknown name raises ValueError with a suggestion, and so
    does a printing (set and number) that isn't that face. When the card
    index isn't ready the row comes back unchanged with a warning."""
    if not _ready():
        return dict(row), [NAMES_UNCHECKED]
    out = dict(row)
    for side in ("front", "back"):
        name = out[side]
        if not name:
            continue
        exact = cards.token_face(name)
        if exact is None:
            hint = _suggest(name)
            raise ValueError(f"'{name}' isn't a token, emblem or reminder name on Scryfall."
                             + (f" Did you mean {hint}?" if hint else ""))
        out[side] = exact
    for side in ("front", "back"):
        problem = _printing_problem(out, side)
        if problem:
            raise ValueError(problem)
    return out, []
