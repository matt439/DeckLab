"""GET /api/deck/compare (E1-S13's first slice): two lists' stats side by side, read only.

Each side is a deck the viewer may see (library._deck_sections: guard.sees_deck, so a hidden deck
answers exactly as a missing one, 404 "No deck <id>") and one of its lists, and its stats are
deck_page._deck_stats's, the same the deck page's Stats tab shows. Both sides are checked before
either's stats are worked out, so a refusal never follows work on the other deck. Nothing of the
space's inventory is read: owned, missing and on-the-way counts aren't part of the comparison.
"""
from decklab.lib import decks

from .common import ApiError, _scrub
from .deck_page import _deck_stats
from .library import _deck_sections

# The library summary's fields a side carries: what names and describes the deck, never its kit.
SUMMARY_FIELDS = ("id", "space", "title", "kind", "format", "player", "status", "card_count", "sideboard_count",
                  "versions", "target_bracket", "cover", "colors")


def _pair_id(deck_id):
    # A "+" in a pairing's id typed into the address bar arrives as a space (server_http's _pair_id).
    if isinstance(deck_id, str) and deck_id.startswith("pairing/"):
        return deck_id.replace(" ", "+")
    return deck_id


def compare_view(a=None, b=None, av="target", bv="target"):
    """GET /api/deck/compare?a=<deck id>&b=<deck id>[&av=target|owned&bv=target|owned]: {"decks":
    [side a, side b]}, each {"summary" (SUMMARY_FIELDS of the library summary, its id the library's),
    "version", "stats" (lib/stats' deck_stats as on the deck page, None when they couldn't be worked
    out) and "warnings"}. The same deck may be on both sides, with its two lists. ApiError 400 without
    a or b or for a bad version, else _deck_sections' refusals (404 for a missing or hidden deck or a
    list it doesn't have, 503 until the card data is ready)."""
    if not a or not b:
        raise ApiError(400, "Name two decks: a and b")
    picked = [_deck_sections(_pair_id(a), av or "target"), _deck_sections(_pair_id(b), bv or "target")]
    sides = []
    for (summary, sections), version in zip(picked, (av or "target", bv or "target")):
        warnings = []
        stats = _deck_stats(sections, decks.engine_kind(summary), warnings)
        if stats and isinstance(stats.get("warnings"), list):
            stats["warnings"] = _scrub(stats["warnings"])
        sides.append({"summary": {key: summary[key] for key in SUMMARY_FIELDS if key in summary},
                      "version": version, "stats": stats, "warnings": _scrub(warnings)})
    return {"decks": sides}
