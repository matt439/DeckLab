"""Deal a hand's keep rule (E4-S09): the practice-hand simulation's keep rule,
sent read-only with the deck page so the Practice tab can say after Keep or
Mulligan what the rule would do, without a second copy of its numbers.

view() gives the land ranges from decklab/lib/goldfish/common.py (Frank
Karsten's rule, as the simulated games use it) with their sources; keep_land()
says whether the rule counts a card as a land, as goldfish/model.py does (a
land, or a spell // land modal card). Nothing here reads a deck, a space or
the inventory, so every viewer of a deck gets the same answer.
"""
import importlib
import traceback

from decklab.lib.stats.cardtext import is_land, land_face

from . import common


def keep_land(card):
    """True when the keep rule counts card (cards.card's data) as a land."""
    try:
        return bool(is_land(card) or land_face(card) is not None)
    except (KeyError, TypeError, AttributeError):
        return False


def _source(sources, key):
    s = sources.get(key) or {}
    return {"title": s.get("title", ""), "url": s.get("url", ""), "date": s.get("date", "")}


def view():
    """{"sizes": {"7": [fewest, most], "6": ..., "5": ...}, "free": [fewest, most] (the free first
    seven of a multiplayer game), "always_keep": n (this many cards or fewer: keep),
    "bottom_lands_above": n (bottoming puts a land on the bottom while there are more), "source"
    and "free_source": {title, url, date}}, or None (logged) when the goldfish rules can't be loaded."""
    try:
        rules = importlib.import_module("decklab.lib.goldfish.common")
        return {
            "sizes": {str(size): [low, high] for size, (low, high) in sorted(rules.KEEP_LANDS.items(), reverse=True)},
            "free": list(rules.FREE_KEEP_LANDS),
            "always_keep": rules.ALWAYS_KEEP,
            "bottom_lands_above": rules.BOTTOM_LANDS_ABOVE,
            "source": _source(rules.SOURCES, "karsten-code"),
            "free_source": _source(rules.SOURCES, "karsten-commander"),
        }
    except Exception:
        common._log("The practice-hand keep rule can't be loaded:\n" + traceback.format_exc())
        return None
