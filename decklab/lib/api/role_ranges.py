"""Dated public catalogue ranges for a visible Commander deck, with no inventory lookup/fetch."""
from decklab.lib import cards
from decklab.lib.gauntlet import catalogue, role_ranges
from .common import ApiError
from .library import _deck_sections
from .role_cards import _tag_counts


def ranges_view(deck_id=None, version="target"):
    summary, _ = _deck_sections(deck_id, version)
    if summary["kind"] != "commander":
        raise ApiError(400, "Comparable role ranges are for Commander decks.")
    if not any(_tag_counts().values()):
        return {"ready": False, "roles": [], "decks": 0, "reason": "Role tags are unavailable, so no comparable range can be verified."}
    return role_ranges.view(catalogue.load("commander"), summary.get("target_bracket"), cards.ROLES, cards.card)
