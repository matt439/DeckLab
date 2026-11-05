"""A Commander deck's tutors (E9-S29), from Scryfall's oracle tags: the cards
tagged below `tutor` (Tagger's "cards that directly search for a card from
your library"), apart from searches for lands only. A card tagged only below
`tutor-land` (Rampant Growth, Evolving Wilds, the fetchlands) is ramp, as the
gauntlet's tags (decklab.lib.gauntlet.tags) also leave land searches out; a
card with another kind of tutor tag too is still a tutor. The zone tags under
`tutor-to` (to hand, to the battlefield) say where a card goes, not what it
finds, so they don't make a land search a tutor.

The count informs only: it never changes the minimum bracket, and nothing is
blocked by it. tutor_rules says what Wizards' official bracket text says
about tutors, from the wording constants.BRACKET_TUTORS keeps."""
from decklab.lib import cards

from .cardtext import card_list
from .constants import BRACKET_TUTORS, SOURCES

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


def tutor_rules(data, kept=None):
    """bracket["tutor_rules"]: what Wizards' official bracket text says about
    tutors, from the wording Deck Lab keeps (constants.BRACKET_TUTORS, quoted
    from the announcement; never fetched), checked against Wizards' latest
    Commander announcement in data (_data_dates: official_announcement,
    official_unknown). {"known": True, "source", "title", "url", "date",
    "read_on", "reviewed_through", "says", "brackets": [{number, says, limit}],
    "limit_set"} or {"known": False, "reason", "read_on", "reviewed_through"}
    when an announcement newer than the kept wording, or none known, may have
    changed it. A limit is a number of tutors the text allows; none is set
    today, so nothing warns about a count."""
    kept = BRACKET_TUTORS if kept is None else kept
    dates = {"read_on": kept["read_on"], "reviewed_through": kept["reviewed_through"]}
    announcement = data.get("official_announcement")
    if data.get("official_unknown") or not announcement:
        return {"known": False, **dates, "reason": "the date of Wizards' latest Commander announcement is "
                "unknown, so the kept wording may be out of date"}
    if announcement["date"] > kept["reviewed_through"]:
        return {"known": False, **dates, "reason": f"Wizards announced a Commander change on "
                f"{announcement['date']}, after the wording Deck Lab keeps was checked "
                f"({kept['reviewed_through']})"}
    source = SOURCES[kept["source"]]
    brackets = [{"number": n, "says": says, "limit": limit}
                for n, (says, limit) in sorted(kept["brackets"].items())]
    return {"known": True, **dates, "source": kept["source"], "title": source["title"],
            "url": source["url"], "date": source["date"], "says": kept["says"], "brackets": brackets,
            "limit_set": any(b["limit"] is not None for b in brackets)}
