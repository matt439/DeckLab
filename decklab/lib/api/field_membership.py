"""The read-only, base-deck-bound Who's in the field view."""
import traceback

from decklab.lib.forge import field_membership as membership, lists

from . import common, field_choices, forge_runs, guard
from .common import ApiError
from .field_page import _field_entry, _field_options


def membership_view(deck_id=None, version="target"):
    """GET /api/field/membership?id=&version=target|owned, with normal deck privacy.

    Reject hidden supplied IDs before resolving aliases. The existing field entry
    helper then checks the canonical deck and list. Diagnostics never enter this
    response, and a membership failure cannot look like a complete empty field.
    can_edit says whether the viewer may change home's saved choices (api/field_choices.py).
    """
    with lists.one_snapshot():
        guard.require_sees_deck(deck_id)
        forge = forge_runs._forge_module()
        try:
            _summary, entry = _field_entry(forge, deck_id, version)
        except ApiError as error:
            if error.status >= 500:
                raise ApiError(error.status, membership.UNAVAILABLE) from None
            raise
        seen = forge_runs._Seen()
        options = _field_options(forge, entry, seen)
        options.pop("keep")  # membership never reads saved simulation evidence
        try:
            answer = membership.view(entry, **options)
        except Exception:
            common._log("Current field membership could not be read:\n" + traceback.format_exc())
            answer = membership.unavailable(entry)
        # Whether the viewer may change home's saved field choices (E3-S23): a named home admin
        # on a home field only; members and requests naming nobody never get the controls.
        return {**answer, "can_edit": field_choices.editable(options["space"])}
