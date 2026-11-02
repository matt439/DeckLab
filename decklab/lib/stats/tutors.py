"""A Commander deck's tutors (E9-S29), from Scryfall's oracle tags: the cards
tagged below `tutor` (Tagger's "cards that directly search for a card from
your library"), apart from searches for lands only. A card tagged only below
`tutor-land` (Rampant Growth, Evolving Wilds, the fetchlands) is ramp, as the
gauntlet's tags (decklab.lib.gauntlet.tags) also leave land searches out; a
card with another kind of tutor tag too is still a tutor. The zone tags under
`tutor-to` (to hand, to the battlefield) say where a card goes, not what it
finds, so they don't make a land search a tutor.

The count informs only: it never changes the minimum bracket, and nothing is
blocked by it."""
from decklab.lib import cards

from .cardtext import card_list

TUTOR_TAG = "tutor"
LAND_TUTOR_TAG = "tutor-land"
ZONE_TUTOR_TAG = "tutor-to"
TAG_ERRORS = (OSError, KeyError, ValueError)


def tutor_ids(path=None):
    """(tutors, land searches): frozensets of oracle ids, from the oracle_tags
    file at path (None: the downloaded one). Raises TAG_ERRORS when the file
    or its tutor tag can't be read."""
    direct, branches = cards.tag_branches(TUTOR_TAG, path)
    land = branches.get(LAND_TUTOR_TAG, frozenset())
    typed = frozenset().union(*(ids for slug, ids in branches.items()
                                if slug not in (LAND_TUTOR_TAG, ZONE_TUTOR_TAG)))
    everything = direct.union(*branches.values())
    land_only = land - typed - direct
    return everything - land_only, land_only


def tutor_check(entries, path=None, tags_date=None):
    """bracket["tutors"] for a deck's main-deck entries (Commander, Companion
    and Deck): {"checked": True, "cards": [{name, qty}], "count": distinct
    tutors, "land_searches": [...], "tags_date"} or {"checked": False,
    "reason"} when the tags can't be read."""
    try:
        tutors, land = tutor_ids(path)
    except TAG_ERRORS as error:
        return {"checked": False, "reason": f"Scryfall's tutor tags couldn't be read ({error})",
                "tags_date": tags_date}
    found = [e for e in entries if e.card["oracle_id"] in tutors]
    searches = [e for e in entries if e.card["oracle_id"] in land]
    return {"checked": True, "cards": card_list(found), "count": len({e.name for e in found}),
            "land_searches": card_list(searches), "tags_date": tags_date}
