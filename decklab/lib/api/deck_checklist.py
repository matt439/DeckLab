"""The signed-in player's own list of physical cards to check, set aside or buy."""
from contextlib import contextmanager

from decklab.lib import decks, permissions, spaces, state
from decklab.lib.state.upgrade_checklist import MissingSchema

from . import guard
from .common import ApiError, _keys, _parse_body, state_errors
from .library import _find_summary, check_deck_id

PRIVATE = "Choose your own profile to use your deck checklist."


def require_owner(profile_id):
    viewer = guard.viewer()
    if not permissions.owns_profile(viewer, profile_id):
        raise ApiError(403, PRIVATE)
    return viewer


def _linked_deck(deck_id, viewer):
    """The canonical saved deck in this viewer's own space, even after a rename."""
    check_deck_id(deck_id)
    space, kind, _ = spaces.split_deck_id(deck_id)
    if space != permissions._space_of(viewer) or kind not in decks.KINDS:
        raise guard.no_deck(deck_id)
    guard.require_sees_deck(deck_id, viewer)
    return _find_summary(deck_id)["id"]


@contextmanager
def _checklist_errors():
    with state_errors():
        try:
            yield
        except MissingSchema:
            raise ApiError(503, "Deck Lab needs a database update before you can use this checklist.",
                           reason="migration") from None


def view(profile_id, deck_id=None):
    viewer = require_owner(profile_id)
    with _checklist_errors():
        linked = _linked_deck(deck_id, viewer) if deck_id is not None else None
        return state.store().checklist(profile_id, deck_id=linked)


def save(profile_id, body, deck_id=None):
    viewer = require_owner(profile_id)
    data = _parse_body(body)
    if data.get("profile", profile_id) != profile_id:
        raise ApiError(403, PRIVATE)
    _keys(data, ("expect", "title", "rows"), ("profile",))
    with _checklist_errors():
        linked = _linked_deck(deck_id, viewer) if deck_id is not None else None
        return state.store().checklist_put(profile_id, data["title"], data["rows"], data["expect"], deck_id=linked)
