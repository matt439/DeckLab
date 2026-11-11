"""Optional, recorder-private facts reviewed after a local counter game ends."""
import copy

from decklab.lib import permissions
from .common import ApiError

REASONS = ("life", "poison", "commander", "conceded", "chosen")
DENIED = "Only the collection that recorded this game can change its counter details."


def normalise(value, ids):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"duration_seconds", "seats"}:
        raise ApiError(400, "Counter details need a length and the game's seats")
    seconds = value["duration_seconds"]
    if seconds is not None and (type(seconds) is not int or not 0 <= seconds <= 172800):
        raise ApiError(400, "A counter game's length is whole seconds, at most two days")
    rows = value["seats"]
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ApiError(400, "Counter details must match the game's seats")
    for row, seat_id in zip(rows, ids):
        if (not isinstance(row, dict) or set(row) != {"seat_id", "final_life", "out_reason", "out_order"}
                or row["seat_id"] != seat_id):
            raise ApiError(400, "Counter details must match the game's seats")
        life, reason, order = row["final_life"], row["out_reason"], row["out_order"]
        if life is not None and (type(life) is not int or not -999 <= life <= 999):
            raise ApiError(400, "Final life is a whole number from -999 to 999")
        if reason is not None and reason not in REASONS:
            raise ApiError(400, "Choose a known reason a player was out")
        if order is not None and (type(order) is not int or not 1 <= order <= len(ids)):
            raise ApiError(400, "Out order is a whole number within this game's players; simultaneous outs may share one")
    return copy.deepcopy(value) if seconds is not None or any(
        row[field] is not None for row in rows for field in ("final_life", "out_reason", "out_order")) else None


def apply(content, data, previous, profile, ids):
    if "counter" not in data:
        if previous and previous.get("counter") is not None:
            content["counter"] = normalise(previous["counter"], ids)
        return content
    if content.get("space") != permissions._space_of(profile):
        raise ApiError(403, DENIED)
    facts = normalise(data["counter"], ids)
    if facts is not None:
        content["counter"] = facts
    return content
