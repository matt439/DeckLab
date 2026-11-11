"""GET /api/changes: unnamed requests get nothing; unknown freshness is explicit."""
from decklab.lib import change_signal, inventory, profiles, state
from . import guard

HEADER = "X-Deck-Lab-Changes"
WRITE_HEADER = "X-Deck-Lab-Changes-Write"


def current(snapshot=None):
    try:
        profile = guard.viewer()
        if not profile:
            return {}
        # No cached Public fallback: an old grant or a missing read is not proof.
        switches = state.store().visibility()
        listed = profiles.read()
        with inventory.pinned(snapshot):
            return change_signal.project(inventory.current(), profile, switches, listed)
    except Exception:                       # optional signals cannot replace a valid page with a failure or zero
        return {"ready": False}


def view():
    return current()
