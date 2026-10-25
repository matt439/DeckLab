"""Owner-only Public/Private controls. Readiness matches the page's offered switches."""
from decklab.lib import permissions, state, visibility
from decklab.lib.state import visibility as values

from . import common, guard, settings
from .common import ApiError

OWNER_ONLY = "Only the owner can change who sees this."
NOT_READY = "This Public switch isn't available yet."


def controls(profile, snapshot=None):
    return permissions.visibility_controls(profile, vis=guard.visibility() if snapshot is None else snapshot,
                                           ready=visibility.READY_THINGS)


def view():
    """GET /api/visibility: just this viewer's ready switches, never another owner's."""
    return {"switches": controls(guard.viewer())}


def _message(owner, thing, public):
    return values.message(owner, thing, public)


def change(body):
    """PUT /api/visibility: one owner-authorised flip, one change set, no member CLI."""
    data = common._parse_body(body, limit=common.MAX_BODY)
    common._keys(data, {"profile", "owner", "thing", "public"})
    profile = settings._writer(data)
    owner, thing, public = data.get("owner"), data.get("thing"), data.get("public")
    # Ownership comes before validation/readiness: a forged owner gets the same
    # refusal for hidden and absent owners, naming neither a space nor a person.
    owned = {(r["owner"], r["thing"]) for r in permissions.visibility_controls(profile, ready=values.THINGS)}
    if not isinstance(owner, str) or not isinstance(thing, str) or (owner, thing) not in owned:
        raise ApiError(403, OWNER_ONLY)
    if thing not in visibility.READY_THINGS:
        raise ApiError(409, NOT_READY)
    with common.state_errors():
        values.switch(owner, thing, public)
        snapshot = state.store().visibility_set(owner, thing, public, settings._web_actor(profile),
                                                _message(owner, thing, public))
    visibility.replace(snapshot)
    return {"switches": controls(profile, snapshot)}
