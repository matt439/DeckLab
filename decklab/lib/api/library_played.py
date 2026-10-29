"""When each library deck was last played at home, and how many games it has (E1-S27):
library summaries' "played" for GET /api/decks.

"played" is {"last": ISO date or None, "games": N}, from the Game log's real two-player
games this request's viewer may see (play_records' _sees_record, the Game log's own filter:
a member's games with a deck of their space, or a space's games made public), each one
the Game log would show (play_records._checked). Commander pods count in no deck's 1v1
games, as the page's playLegacyGame leaves them out of its totals. A game whose other side
is a deck the viewer can't see still counts for the viewer's own deck, and nothing here
names the other side. A deck played on both sides (a mirror) counts the game once, and a
side recorded under a deck's old id (a renamed deck) counts for the deck it now is.

"played" is None for every deck when the games can't be read (the database down, a login
that isn't set up): the page then says nothing rather than "Not played at home yet".
"""
import traceback

from decklab.lib import inventory, state
from decklab.lib.state import rules

from . import common, guard, play_records


def _legacy(record):
    """True for an original two-seat game (no pod markers), the only kind counted (playLegacyGame)."""
    return (isinstance(record, dict) and "mode" not in record and "game_version" not in record
            and isinstance(record.get("sides"), list) and len(record["sides"]) == 2)


def _games():
    """The visible two-player games as (date, deck ids), or None when they can't be read."""
    try:
        viewer, script = guard.viewer(), guard.script()
        records = state.store().play_list("games")
    except (common.ApiError, state.Unavailable):
        return None
    except Exception:           # an optional read: the shelf goes on without it
        common._log("The Game log couldn't be read for the library:\n" + traceback.format_exc())
        return None
    try:
        snapshot = inventory.current()
    except Exception:           # old ids then stay as recorded
        snapshot = None
    found = []
    for record in records:
        if not _legacy(record) or not play_records._sees_record("games", record, viewer, script):
            continue
        try:
            play_records._checked("games", record.get("id"), record)
        except common.ApiError:
            continue            # the Game log warns about it; it counts nowhere
        ids = set()
        for side in record["sides"]:
            if rules.is_removed_deck(side) or not isinstance(side.get("id"), str):
                continue
            ids.add(inventory.resolve_deck_id(side["id"], snapshot) if snapshot is not None else side["id"])
        found.append((record["date"], ids))
    return found


def played_extras(summaries):
    """Set each library summary's "played" (in place; the module docstring)."""
    games = _games()
    for summary in summaries:
        if games is None:
            summary["played"] = None
            continue
        dates = [day for day, ids in games if summary["id"] in ids]
        summary["played"] = {"last": max(dates) if dates else None, "games": len(dates)}
    return summaries
