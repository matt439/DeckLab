"""The read-only Matchups rankings of current lists, grouped by comparable evidence."""
import traceback

from . import common, forge_runs, guard
from .carddata import _require_cards
from .common import ApiError


def rankings_view(format="Constructed"):
    """GET /api/rankings?format=Constructed|Commander; deck-read policy, no inventory fields."""
    from decklab.lib.forge import rankings
    if format not in rankings.FORMATS:
        raise ApiError(400, f"format must be one of: {', '.join(rankings.FORMATS)}")
    _require_cards()
    forge = forge_runs._forge_module()
    seen = forge_runs._Seen()
    try:
        # Rows and ratings worked out over the decks this viewer sees only (E10-S30).
        public = frozenset(guard.public_deck_spaces())
        options = {"space": seen.space or "home", "public": lambda space: space in public,
                   "visible": seen.deck, "product_notes": seen.everything or seen.space == "home"}
        return rankings.view(format, visible=seen.deck, keep=lambda result: seen.result(forge, result),
                             field_options=options)
    except Exception:
        common._log(f"The rankings cannot be read:\n{traceback.format_exc()}")
        return {"format": format, "rows": [], "groups": [], "notes": [],
                "error": "Saved rankings cannot be worked out on the PC now. Try again later."}
