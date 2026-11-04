"""The pictures on Build decks' token tiles (assembly-tokens.js).

Tokens are always optional, so nothing here may stop a plan: a picture that can't be worked
out is simply left out, and the tile shows the token's name instead. These fields are for
showing only: they're never part of a packing tick's identity (assembly_ticks.TOKEN_TASK_FIELDS).
"""
import traceback

from . import common


def row_pictures(row):
    """{img, back_img, example_art} for one token card: the row's own printing's pictures when it
    records one, else example art of a token with each face's name (example_art True: it's never
    the card's printing), as the Tokens page's tiles show. None where there's no picture."""
    from .tokens import _face
    try:
        faces = [_face(row, side, True) for side in ("front", "back") if side == "front" or row.get(side)]
    except RuntimeError:        # the card index is missing or being rebuilt
        return {"img": None, "back_img": None, "example_art": False}
    except Exception:
        common._log("A token card's pictures couldn't be worked out:\n" + traceback.format_exc())
        return {"img": None, "back_img": None, "example_art": False}
    own = any(face["image"] for face in faces)
    pictures = [face["image"] or (None if own else face["example"]) for face in faces]
    return {"img": pictures[0], "back_img": pictures[1] if len(pictures) > 1 else None,
            "example_art": not own and any(pictures)}


def _example(need):
    from .tokens import _example_image
    try:
        return _example_image(need.get("name"), need.get("pt") or "")
    except Exception:           # an index without token pictures, or none at all
        return None


def with_pictures(result, rows):
    """result (a plan's own copy of tokens.deck_tokens's answer) with the pictures of the card each
    need's tile shows: the first card, or the first stand-in, gains row_pictures's fields, and a
    need with no "image" of its own gains an "example" (None when there isn't one)."""
    for need in result.get("needs", []) if isinstance(result, dict) else []:
        for candidate in (need.get("cards") or [])[:1] + (need.get("stand_ins") or [])[:1]:
            index = candidate.get("row")
            if isinstance(index, int) and 0 <= index < len(rows):
                candidate.update(row_pictures(rows[index]))
        if not need.get("image"):
            need["example"] = _example(need)
    return result
