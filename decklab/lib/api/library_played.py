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

deck_played(deck_id) is the deck page's (deck_view's "played", the Overview's Last played
line): the same {"last", "games"} for one deck, plus "since", what its list has changed
since its last game (E1-S27 slice 3), or None when that can't be told (no games, or no
list it was played with can be found). The list a game was played with is found by the
sha256 its side recorded (a sideboard plan's game by its base_sha256, the list before the
plan's swaps): the deck's current list when it still matches, else the newest of its saved
revisions (inventory.deck_revisions_with_text, the deck's History) that does. "since" is
{"version": the list played, "changes": [{section, name, delta, printing}], "more"}, the
History's own comparison (history._list_changes) of that list and today's; no changes means
the list is as it was. Of the last day's games, a side that matches today's list wins (it
was the latest list played), else the newest matching revision. Nothing in it names the
other side of a game: only this deck's own list, which the viewer already sees.
"""
import traceback

from decklab.lib import decks, inventory, state
from decklab.lib.state import rules

from . import common, guard, play_records

MAX_REVISIONS = 100             # the History's: a list older than that reads as unknown
MAX_CHANGES = 30                # card changes sent; the rest are counted in "more"


def _legacy(record):
    """True for an original two-seat game (no pod markers), the only kind counted (playLegacyGame)."""
    return (isinstance(record, dict) and "mode" not in record and "game_version" not in record
            and isinstance(record.get("sides"), list) and len(record["sides"]) == 2)


def _games():
    """The visible two-player games as (date, deck ids, [(deck id, side)]), or None when they
    can't be read."""
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
        sides = []
        for side in record["sides"]:
            if rules.is_removed_deck(side) or not isinstance(side.get("id"), str):
                continue
            sides.append((inventory.resolve_deck_id(side["id"], snapshot) if snapshot is not None else side["id"],
                          side))
        found.append((record["date"], {deck_id for deck_id, _ in sides}, sides))
    return found


def played_extras(summaries):
    """Set each library summary's "played" (in place; the module docstring)."""
    games = _games()
    for summary in summaries:
        if games is None:
            summary["played"] = None
            continue
        dates = [day for day, ids, _ in games if summary["id"] in ids]
        summary["played"] = {"last": max(dates) if dates else None, "games": len(dates)}
    return summaries


def deck_played(deck_id):
    """One deck's {"last", "games", "since"} (the module docstring), or None when the games
    can't be read."""
    games = _games()
    if games is None:
        return None
    dates = [day for day, ids, _ in games if deck_id in ids]
    if not dates:
        return {"last": None, "games": 0, "since": None}
    last = max(dates)
    sides = [side for day, _, found in games if day == last for side_id, side in found if side_id == deck_id]
    try:
        since = _since(deck_id, sides)
    except Exception:           # optional: the Last played line stands without it
        common._log("What changed since the last game couldn't be worked out:\n" + traceback.format_exc())
        since = None
    return {"last": last, "games": len(dates), "since": since}


def _played_with(side):
    """(the id it was recorded under, its version, the sha256 of the list played before any plan's
    swaps), or None for a side that doesn't say."""
    version, sha = side.get("version"), side.get("base_sha256") or side.get("sha256")
    if version not in ("target", "owned") or not isinstance(sha, str):
        return None
    return side["id"], version, sha


def _list(deck, version):
    return (deck.target if deck.has_decklist else None) if version == "target" else deck.owned


def _since(deck_id, sides):
    played = [found for found in map(_played_with, sides) if found]
    for recorded, version, sha in played:
        try:
            now = decks.load_deck(deck_id, version)
        except (decks.DeckNotFound, decks.DeckFileError, OSError):
            continue
        if play_records.snapshot_sha(recorded, version, now) == sha:
            return {"version": version, "changes": [], "more": 0}
    try:
        space, kind, slug = decks.split_id(deck_id)
    except ValueError:
        return None             # a product's or pairing's list has no saved revisions
    from .history import _list_changes, _revision_deck
    for rev in inventory.deck_revisions_with_text(deck_id, MAX_REVISIONS):
        old = _revision_deck(rev, kind, slug, space)
        if not old:
            continue            # a deletion, or a text that can't be read
        for recorded, version, sha in played:
            then = _list(old, version)
            if then is None or play_records.snapshot_sha(recorded, version, then) != sha:
                continue
            try:
                now = decks.load_deck(deck_id, version)
            except (decks.DeckNotFound, decks.DeckFileError, OSError):
                return None     # the list it was played with is gone
            changes = [{key: change[key] for key in ("section", "name", "delta", "printing")}
                       for change in _list_changes(version, then, now, False)]
            return {"version": version, "changes": changes[:MAX_CHANGES], "more": max(0, len(changes) - MAX_CHANGES)}
    return None
