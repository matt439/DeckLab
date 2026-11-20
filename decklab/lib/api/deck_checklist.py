"""The signed-in player's own list of physical cards to check, set aside or buy."""
from contextlib import contextmanager

from decklab.lib import permissions, state
from decklab.lib.state.upgrade_checklist import MissingSchema

from . import guard
from .common import ApiError, _keys, _parse_body, state_errors

PRIVATE = "Choose your own profile to use your deck checklist."


def require_owner(profile_id):
    if not permissions.owns_profile(guard.viewer(), profile_id):
        raise ApiError(403, PRIVATE)


@contextmanager
def _checklist_errors():
    with state_errors():
        try:
            yield
        except MissingSchema:
            raise ApiError(503, "Deck Lab needs a database update before you can use this checklist.",
                           reason="migration") from None


def view(profile_id):
    require_owner(profile_id)
    with _checklist_errors():
        return state.store().checklist(profile_id)


def save(profile_id, body):
    require_owner(profile_id)
    data = _parse_body(body)
    if data.get("profile", profile_id) != profile_id:
        raise ApiError(403, PRIVATE)
    _keys(data, ("expect", "title", "rows"), ("profile",))
    with _checklist_errors():
        return state.store().checklist_put(profile_id, data["title"], data["rows"], data["expect"])
