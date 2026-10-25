"""Stored play-record identity, including strict irreversible-removal markers."""
from . import Invalid

REMOVED_DECK = {"removed": True, "title": "a removed deck"}


def is_removed_deck(value):
    """Only the exact marker, with a JSON boolean (never the Python-equal number 1)."""
    return isinstance(value, dict) and value.get("removed") is True and value == REMOVED_DECK


def record_deck_ids(kind, content):
    """Surviving ids; removed sides carry no old id, list, name or plan.

    Plans always retain their own deck. A retained game with a removed side has
    exactly two sides and at least one survivor. The blank recorder belongs to
    no real space and can retain no notes from the removed recording space.
    """
    if not isinstance(content, dict):
        raise Invalid("A play record must name its decks")
    try:
        sides = content["sides"] if kind == "games" else [content["deck"], content["opponent"]]
        removed = [is_removed_deck(side) for side in sides]
        if any(isinstance(side, dict) and "removed" in side and not gone for side, gone in zip(sides, removed)):
            raise Invalid("A removed deck must use the exact removal marker")
        if any(removed) and (len(sides) != 2 or all(removed) or kind == "sideboards" and removed[0]):
            raise Invalid("A retained play record needs its surviving deck")
        if kind == "games" and content.get("space") == "" and (not any(removed) or content.get("notes") != ""):
            raise Invalid("A removed recording space needs a removed side and no notes")
        ids = [side["id"] for side, gone in zip(sides, removed) if not gone]
    except (KeyError, TypeError):
        raise Invalid("A play record must name its decks") from None
    if any(not isinstance(deck_id, str) for deck_id in ids):
        raise Invalid("A play record must name its decks")
    return ids
