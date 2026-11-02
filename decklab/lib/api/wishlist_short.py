"""Which of a wishlist owner's decks are short of each wished card (E5-S30's first slice).

A wished card is "short" in a deck when the deck's Planned (target) list needs more copies
than the deck's own space can give it: owned, on the way included, less the copies other
built decks and intact products hold. That's the deck page's owned-vs-needed "missing"
(pool.owned_vs_needed), each deck counted on its own against the one pool the wishlist view
already loaded, as Shopping's missing cards are (lib/buying_needs.py): not a simultaneous
allocation across decks.

Only the owner's own space's decks count, only those the owner may see (guard.sees_deck),
and only when the owner may see that space's inventory (guard.sees_inventory): otherwise
nothing is said. The answer is worked out for the wishlist's owner, never for whoever else
the request might stand for, and never names another space's deck.
"""
from decklab.lib import cards, decks, inventory, pool, spaces

from . import common, guard

# Shown once in the wishlist's warnings when the decks can't be counted.
UNCOUNTED = "Which of your decks are short of these cards can't be worked out right now."
INCOMPLETE = ("Which of your decks are short of these cards can't be worked out until the card pool's "
              "problems are fixed.")


def _own_decks(space, profile):
    """The library summaries of space's own decks (no products or pairings) with a Planned list,
    that profile may see."""
    out = []
    for summary in decks.list_decks():
        if summary.get("error") or "target" not in summary.get("versions", []):
            continue
        try:
            deck_space, kind, _ = spaces.split_deck_id(summary.get("id"))
        except ValueError:
            continue
        if deck_space != space or summary.get("space", space) != space or kind not in decks.KINDS:
            continue
        if guard.sees_deck(summary, profile):
            out.append(summary)
    return out


def short_decks(profile, names, supply, warnings):
    """{exact card name: [{id, title, missing}]} for the wished names (exact Scryfall names), every
    name with a list (empty when no deck is short of it); None when nothing may be said (the owner
    can't see the space's inventory) or it can't be worked out (supply None, an incomplete pool,
    the decks unreadable: then a warning says so). Each card's decks come most copies short first,
    then by title."""
    if not profile or not names:
        return None
    space = profile.get("space") or spaces.HOME
    if not guard.sees_inventory(space, profile):
        return None
    if supply is None or getattr(supply, "space", spaces.HOME) != space:
        return None
    if supply.unresolved or supply.warnings:
        warnings.append(INCOMPLETE)
        return None
    wanted = set(names)
    found = {name: [] for name in wanted}
    try:
        summaries = _own_decks(space, profile)
    except inventory.Unavailable:
        raise
    except Exception as error:  # noqa: BLE001 - the list itself stays available
        common._log(f"Wishlist: the decks couldn't be listed: {error}")
        warnings.append(UNCOUNTED)
        return None
    for summary in summaries:
        try:
            result = pool.owned_vs_needed(summary["id"], "target", pool=supply, prices=False)
        except inventory.Unavailable:
            raise
        except Exception as error:  # noqa: BLE001 - one unreadable deck leaves the others counted
            common._log(f"Wishlist: {summary['id']} couldn't be counted: {error}")
            continue
        for row in result["rows"]:
            if row["missing"] <= 0:
                continue
            name = cards.resolve(row["name"]) or row["name"]
            if name in wanted:
                found[name].append({"id": summary["id"], "title": summary.get("title") or summary["id"],
                                    "missing": row["missing"]})
    for listed in found.values():
        listed.sort(key=lambda deck: (-deck["missing"], deck["title"].casefold(), deck["id"]))
    return found
