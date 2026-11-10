"""Visible saved-game development facts; no new run, inventory, setting or source fetch."""
import traceback

from . import common
from .forge_runs import _Seen, _forge_module
from .library import _deck_sections
from decklab.lib import decks


def development_view(deck_id=None, version="target"):
    summary, sections = _deck_sections(deck_id, version)
    try:
        forge = _forge_module()
        seen = _Seen()
        with forge.engine.held():
            return forge.development.list_development(sections, decks.engine_kind(summary),
                                                       keep=lambda result: seen.result(forge, result),
                                                       pilot=forge.pilots.pilot_for(summary["id"], version))
    except Exception:
        common._log("Saved-game development could not be read safely:\n" + traceback.format_exc())
        return {"games": 0, "rounds": [], "why": "Saved-game development isn't available right now."}
