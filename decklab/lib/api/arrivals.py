"""Arrival notices (E6-S19, lib/arrivals.py): the decks a recorded delivery brought cards for,
shown to their home player on the next visit until dismissed.

    GET  /api/arrivals              {"notices": [{id, order, received_on, cards, more,
                                    decks: [{id, title, cards}]}]}: the viewer's own, newest first
    POST /api/arrivals/dismiss      {profile, ids: [notice id]} -> {"notices": [...]}: the ones left
                                    ([] and "unshown": true when the decks can't be read just then:
                                    the dismissal is saved all the same)

Only the viewer's own notices, and only for a home profile (the notices are kept with a home
player's settings; anyone else, a request naming nobody and a script get none). A deck the
viewer may not see (guard.deck_reader), or one deleted since, is left out, and a notice left
with no deck at all (and nothing left out for length) isn't shown; a renamed deck is found by
its alias. Dismissing is the viewer's own settings.edit; ids no longer there change nothing.
"""
from decklab.lib import arrivals, inventory, permissions

from . import guard
from .common import ApiError, _keys, _parse_body, state_errors
from .settings import _web_actor, _writer

MAX_IDS = arrivals.MAX_NOTICES


def _home_viewer():
    """The viewer when it's a home profile (the notices' only readers), else None."""
    if guard.script():
        return None
    try:
        viewer = guard.viewer()
    except ApiError:
        return None
    if viewer is None or (viewer.get("space") or permissions.HOME) != permissions.HOME:
        return None
    return viewer


def _shown(found, viewer):
    """The notices as the page shows them: each deck by its current title, only those the
    viewer may see."""
    from decklab.lib import decks
    sees = guard.deck_reader(viewer)
    with inventory.pinned() as current:
        inv = current()
        summaries = {s["id"]: s for s in decks.list_decks() if not s.get("error")}
        out = []
        for notice in found:
            shown = []
            for deck_id, cards in notice["decks"]:
                summary = summaries.get(inventory.resolve_deck_id(deck_id, inv))
                if summary is not None and sees(summary):
                    shown.append({"id": summary["id"], "title": summary["title"], "cards": cards})
            if shown or notice["more"]:
                out.append({"id": notice["id"], "order": notice["order"], "received_on": notice["received_on"],
                            "cards": sum(item["cards"] for item in shown), "more": notice["more"],
                            "decks": shown})
    return out


def arrivals_view():
    """GET /api/arrivals: the viewer's arrival notices (see the module docstring)."""
    viewer = _home_viewer()
    if viewer is None:
        return {"notices": []}
    with state_errors():
        found = arrivals.notices(viewer["id"])
    if not found:
        return {"notices": []}
    try:
        return {"notices": _shown(found, viewer)}
    except inventory.Unavailable:
        from .common import DATABASE_DOWN
        raise ApiError(503, DATABASE_DOWN, reason="database") from None


def dismiss_arrivals(body):
    """POST /api/arrivals/dismiss {"profile", "ids"}: the writer's own notices with those ids go."""
    data = _parse_body(body)
    _keys(data, ("profile", "ids"))
    profile = _writer(data)
    guard.require(profile, "settings.edit", profile["id"])
    ids = data["ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IDS or any(
            not isinstance(item, str) or len(item) > 80 for item in ids):
        raise ApiError(400, f"Name 1 to {MAX_IDS} notices to dismiss")
    if (profile.get("space") or permissions.HOME) != permissions.HOME:
        return {"notices": []}
    with state_errors():
        left = arrivals.dismiss(profile["id"], ids, _web_actor(profile), profile["name"])
    try:
        return {"notices": _shown(left, profile) if left else []}
    except inventory.Unavailable:
        # The dismissal is saved: say so, with the rest left for the next visit's GET.
        return {"notices": [], "unshown": True}
