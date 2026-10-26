"""Private Settings email replacement for existing non-home members (E10-S17)."""
from contextlib import contextmanager

from decklab.db import conn as db

from . import guard
from .common import ApiError, _load_json
from .settings import _web_actor

MAX_BODY = 4096


@contextmanager
def _errors():
    from decklab.db import profile_edits
    try:
        yield
    except profile_edits.StaleProfileEdit:
        raise ApiError(409, "Member settings changed. Reload the panel before making another change.") from None
    except profile_edits.PendingProfileEdit:
        raise ApiError(503, "A member-settings change needs local recovery before editing can continue.") from None
    except profile_edits.InvalidProfileEdit as exc:
        raise ApiError(400, str(exc)) from None
    except db.DbUnavailable:
        raise ApiError(503, "Member settings could not be confirmed. Reload before making another change.") from None
    except OSError:
        raise ApiError(503, "Member settings could not be saved or confirmed. Reload before making another change.") from None


def _admin():
    viewer = guard.viewer()
    guard.require(viewer, "members.edit")
    return viewer


def view():
    """GET/HEAD /api/settings/members: the only web reader of member email aliases."""
    from decklab.db import profile_edits
    with _errors():
        viewer = _admin()
        return profile_edits.preview(actor=_web_actor(viewer))


def change(body):
    """POST /api/settings/member-email; no other profile field can be edited here."""
    from decklab.db import profile_edits
    with _errors():
        viewer = _admin()  # Refuse hidden readers before inspecting their payload or storage.
        if isinstance(body, str):
            body = body.encode("utf-8")
        if len(body) > MAX_BODY:
            raise ApiError(413, "The member email request is too large.")
        data = _load_json(body, "The member email request")
        fields = {"profile", "member_id", "old_email", "new_email", "config_sha256", "membership_sha256"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ApiError(400, "The member email request needs exactly the reviewed member, addresses and receipts.")
        if data["profile"] != viewer["id"]:
            raise ApiError(403, "You can only make changes as yourself.")
        return profile_edits.apply(data["member_id"], data["old_email"], data["new_email"],
                                   config_sha256=data["config_sha256"], membership_sha256=data["membership_sha256"],
                                   actor=_web_actor(viewer))
