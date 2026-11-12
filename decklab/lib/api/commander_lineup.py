"""A Commander night line-up (E9-S34): GET /api/commander-night/lineup, home's Commander decks sorted
against the recorded Commander night by lib/commander_lineup.py's lineup().

    lineup_view()   {"available": true, "night", "limit", "basis", "groups": {"fits", "above", "unknown"},
                    "counts", "night_error": a sentence or None, "played_error": a sentence or None,
                    "timed_out": decks not checked in time, "today"}

Only for home's profiles or a script naming nobody (permissions.sees_commander_night, as the night's own
notes): anyone else gets 403 "Commander-night notes are private." before anything is read. The decks are
home's saved Commander decks the viewer may see (guard.visible_decks; never a trial, a product or pairing
deck, or a retired deck, which isn't listed at all). A built deck is judged on its built list
(pool._built_version), any other on its Planned list, by the stats' counted minimum (stats.deck_rules,
lib/stats/commander.py), worked out on this PC from its card data, oracle tags and combo list: nothing
is fetched. The checks share TIME_BUDGET seconds: a deck whose check would start after it is listed as
unknown, never as fitting, and so is a deck whose check fails. The stand-ins (the installed recipe of a
built deck, else its Planned list's chosen stand-ins) go only to viewers who may see home's inventory,
and the box-checked date only to home's record readers, as on the deck page. When it was last played
comes from the Game log's games and Commander pods this viewer may see (a renamed deck's old id counts
for the deck it is now); when the Game log can't be read, played_error says so and no date is claimed.
"""
import time
import traceback

from decklab.lib import commander_lineup, decks, inventory, permissions, pool, spaces, state
from decklab.lib.state import rules

from . import common, guard, play_records
from .common import ApiError

TIME_BUDGET = 20.0              # seconds for every deck's checks together
NOT_IN_TIME = "Its checks didn't finish in time; open its page to see its minimum bracket."
NO_CARDS = "The card data couldn't be read, so its minimum bracket isn't known."
NO_FILE = "Its deck text couldn't be read."
NO_NIGHT = "The recorded Commander night couldn't be loaded, so no deck is judged against it."
NO_GAMES = "The Game log can't be read now, so when each deck was last played isn't shown."


def _sees():
    return permissions.sees_commander_night(guard.viewer(), script=guard.script())


def _night():
    """(the recorded night or None, an error sentence or None)."""
    try:
        return state.store().commander_night()["night"], None
    except state.StateError:
        return None, NO_NIGHT


def _summaries():
    """Home's saved Commander decks this viewer sees, without trials."""
    return [s for s in guard.visible_decks(decks.list_decks())
            if s.get("space", spaces.HOME) == spaces.HOME and s.get("kind") == "commander"
            and not s.get("trial") and not s["id"].startswith(("product/", "pairing/"))]


def _last_played():
    """{deck id: the last date it was played} from the visible games and pods, or None when unreadable."""
    try:
        viewer, script = guard.viewer(), guard.script()
        records = state.store().play_list("games")
    except (ApiError, state.StateError):
        return None
    except Exception:           # optional: the line-up goes on without it
        common._log("The Game log couldn't be read for the Commander line-up:\n" + traceback.format_exc())
        return None
    try:
        snapshot = inventory.current()
    except Exception:           # old ids then stay as recorded
        snapshot = None
    last = {}
    for record in records:
        if not isinstance(record, dict) or not play_records._sees_record("games", record, viewer, script):
            continue
        try:
            play_records._checked("games", record.get("id"), record)
            ids = rules.record_deck_ids("games", record)
        except (ApiError, ValueError, KeyError, TypeError):
            continue            # the Game log warns about it; it counts nowhere
        day = record.get("date")
        if not isinstance(day, str):
            continue
        for deck_id in ids:
            if not isinstance(deck_id, str):
                continue
            if snapshot is not None:
                deck_id = inventory.resolve_deck_id(deck_id, snapshot)
            last[deck_id] = max(last.get(deck_id, day), day)
    return last


def _bracket(sections):
    """The stats' commander bracket of a list (stats.deck_rules); tests patch this."""
    from decklab.lib import stats
    rules_found = stats.deck_rules(sections, "commander")
    commander = rules_found.get("commander") or {}
    return commander.get("bracket")


def _entry(summary, deadline, shows_standins, shows_box):
    """One deck's summary for lineup()."""
    deck_id = summary["id"]
    built = summary.get("status") == "built"
    version = pool._built_version(summary, []) if built else "target"
    entry = {"id": deck_id, "title": summary.get("title") or deck_id, "kind": "commander",
             "status": summary.get("status"), "version": version, "trial": bool(summary.get("trial")),
             "target_bracket": summary.get("target_bracket"), "bracket": None, "unknown": None}
    deck_file = None
    try:
        _space, kind, slug = spaces.split_deck_id(deck_id)
        deck_file = decks.read_deck_file(decks.find_deck_file(kind, slug, spaces.HOME), space=spaces.HOME)
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
        entry["unknown"] = NO_FILE
    if deck_file is not None:
        if shows_box:
            from decklab.lib.decks import boxcheck
            entry["box_checked_on"] = boxcheck.checked_on(deck_file)
        if shows_standins:
            from decklab.lib.decks import standins
            found = standins.project(deck_file, version)
            entry["stand_ins"] = [{"for": row["for"], "using": row["using"], "qty": row["qty"]}
                                  for row in found["rows"]]
    if entry["unknown"] is None:
        sections = deck_file.target if version == "target" else deck_file.owned
        if not sections:
            entry["unknown"] = NO_FILE
        elif time.monotonic() > deadline:
            entry["unknown"] = NOT_IN_TIME
        else:
            try:
                entry["bracket"] = _bracket(sections)
            except Exception:       # cards.INDEX_ERRORS and any other: unknown, never fitting
                common._log(f"The Commander line-up couldn't check {deck_id}:\n" + traceback.format_exc())
                entry["unknown"] = NO_CARDS
    return entry


def lineup_view():
    """GET /api/commander-night/lineup: see the module's docstring."""
    if not _sees():
        raise ApiError(403, permissions.COMMANDER_NIGHT_PRIVATE)
    today = play_records._play_today()
    night, night_error = _night()
    shows_standins = guard.sees_inventory(spaces.HOME)
    shows_box = guard.sees_home_records()
    played = _last_played()
    deadline = time.monotonic() + TIME_BUDGET
    entries = []
    for summary in _summaries():
        if summary.get("error"):
            entries.append({"id": summary["id"], "title": summary.get("title") or summary["id"], "kind": "commander",
                            "status": summary.get("status"), "version": "target", "bracket": None,
                            "unknown": NO_FILE})
        else:
            entries.append(_entry(summary, deadline, shows_standins, shows_box))
    for entry in entries:
        entry["played_known"] = played is not None
        entry["last_played"] = (played or {}).get(entry["id"])
    answer = commander_lineup.lineup(entries, night, today, night_unavailable=night_error)
    return {"available": True, **answer, "night_error": night_error,
            "played_error": None if played is not None else NO_GAMES,
            "timed_out": sum(1 for e in entries if e.get("unknown") == NOT_IN_TIME), "today": today}
