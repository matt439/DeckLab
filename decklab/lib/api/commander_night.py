"""The home collection's optional dated Commander-night notes; no enforced house rules."""
from datetime import date

from decklab.lib import permissions, state
from decklab.lib.state import commander_night as notes

from . import guard
from .common import ApiError, _load_json, state_errors
from .settings import _web_actor

MAX_BODY = 8192             # complete Unicode notes and labels fit within their character limits


def _sees():
    return permissions.sees_commander_night(guard.viewer(), script=guard.script())


def _answer(snapshot):
    return {**snapshot, "can_edit": guard.allowed(guard.viewer(), "commander_night.edit")}


def view():
    """GET /api/commander-night, refused before storage for anyone outside home."""
    if not _sees():
        raise ApiError(403, permissions.COMMANDER_NIGHT_PRIVATE)
    with state_errors():
        return _answer(state.store().commander_night())


def change(body):
    """PUT /api/commander-night: replace or intentionally clear one reviewed revision."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, f"The Commander-night notes are limited to {MAX_BODY} bytes")
    data = _load_json(body, "The Commander-night notes")
    if not isinstance(data, dict):
        raise ApiError(400, "The Commander-night notes must be a JSON object")
    profile = guard.writer(data, "commander_night.edit")
    if not _sees():
        raise ApiError(403, permissions.COMMANDER_NIGHT_PRIVATE)
    if set(data) - {"profile", "expect", "night", "reason"}:
        raise ApiError(400, "The Commander-night request has unknown fields")
    if "night" not in data:
        raise ApiError(400, "The Commander-night request must include night")
    with state_errors():
        expect = notes.expectation(data.get("expect"))
        night = notes.normalize(data["night"], today=date.today())
        reason = notes.clear_reason(data.get("reason")) if night is None else None
        message = "Clear the household's Commander-night notes" if night is None else "Save the household's Commander-night notes"
        saved = state.store().commander_night_put(night, expect, _web_actor(profile), message, reason=reason)
        return _answer(saved)


def projection():
    """Eligible home Commander pages' note, quietly absent until recorded.

    A database or pending-schema failure costs only the optional panel; it never claims
    no notes were saved and never stops the deck page itself from opening.
    """
    if not _sees():
        return None
    try:
        saved = state.store().commander_night()
        return _answer(saved) if saved["night"] is not None else None
    except state.StateError:
        return {"unavailable": True}
