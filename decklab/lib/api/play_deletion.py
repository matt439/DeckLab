"""Explicit, reasoned removal of a game by its recording space; no inventory changes."""
from decklab.lib import permissions, state
from decklab.lib.state import rules
from . import guard, play_records as play, saving
from .common import ApiError, _keys, _parse_body, state_errors
from .settings import _writer

DENIED = "Only the collection that recorded this game can delete it."


def may_delete(record, profile):
    recording = play._recording_space(record)
    return bool(profile and recording and recording == permissions._space_of(profile)
                and guard.allowed(profile, "play.record", [{"space": recording}]))


def delete_game(body):
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "sha256", "reason", "confirmed"))
    record_id = play._record_id(data["id"])
    with state_errors(), saving._save_lock:
        previous = state.store().play_get("games", record_id)
        if previous is None or not play._sees_record("games", previous, profile):
            raise ApiError(404, play.NO_RECORD.format(record_id))
        if not may_delete(previous, profile):
            raise ApiError(403, DENIED)
        sha = play._checked("games", record_id, previous)
        if data["sha256"] != sha:
            raise ApiError(409, rules.CHANGED_MESSAGE)
        if data["confirmed"] is not True:
            raise ApiError(400, "Confirm deleting this game")
        reason = rules.play_delete_reason(data["reason"])
        state.store().play_delete("games", record_id, sha, play._actor(profile), "Delete a played game", reason)
    return {"deleted": True, "id": record_id}
