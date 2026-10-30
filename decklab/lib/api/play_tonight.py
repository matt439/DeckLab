"""Tonight's pairs (E1-S28): GET /api/play/pairs, up to three ready pairs of home's built casual decks
for the Game log's "Tonight's pairs" card, from lib/play_pairs.py's suggest().

    pairs_view()    {"available": bool, "pairs": [suggest()'s pairs], "ready": ready decks counted,
                    "unconfirmed": built casual decks whose availability can't be confirmed (never
                    suggested), "error": a sentence or None, "forge_error": a sentence or None, "today"}

Only for home's two players (a profile of the home space), or a script naming nobody: anyone else (a
member, a request naming nobody) gets {"available": false, "pairs": []} and nothing about home's decks,
games or Forge numbers, not even a count. The decks are home's built casual decks the viewer may see
(guard.visible_decks); a deck is ready when its built list (pool._built_version) has nothing missing in
home's pool and its availability is confirmed (no unknown card, no pool warning), as the library's
readiness chip says (E1-S03). The games are the Game log's own (library_played._games: its visibility and
damage checks, renamed decks' old ids resolved, pods left out); a game with a removed side counts for
nothing. Forge's numbers are the Constructed field's saved pairs this viewer sees (library_forge.pair_rates,
cached; never a game played), each kept only when both its lists are the two decks' built lists, so a
field addition's other list never stands for the built one (the pair then goes by the real record). When the games can't be read nothing is suggested (error says so); when
Forge's numbers can't be, the pairs go by the real record only (forge_error says so).
"""
from decklab.lib import decks, permissions, play_pairs, pool, spaces

from . import guard, library_forge, library_played, play_records
from .library import _load_pool, is_half

NO_GAMES = "The Game log can't be read now, so no pairs are suggested."
NO_POOL = "Which decks are ready can't be worked out now, so no pairs are suggested."


def _home_viewer():
    """True for a home profile, or a script naming nobody."""
    viewer = guard.viewer()
    if not viewer:
        return guard.script()
    return permissions._space_of(viewer) == spaces.HOME and guard.sees_inventory(spaces.HOME)


def _ready(summary, version, p):
    """True when the built list has every card here, False when it misses some, None when that can't be
    confirmed (an unknown card, a pool warning: the library's "Availability needs checking")."""
    try:
        result = pool.owned_vs_needed(summary["id"], version, pool=p, prices=False)
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
        return None
    if result["unresolved"] or result["warnings"]:
        return None
    return result["totals"]["missing"] == 0


def _decks():
    """Home's built casual decks the viewer sees, each with "ready", or None when the pool can't be read."""
    summaries = [s for s in guard.visible_decks(decks.list_decks())
                 if not s.get("error") and not is_half(s) and s.get("space", spaces.HOME) == spaces.HOME
                 and s.get("kind") == "casual" and s.get("status") == "built"
                 and not s["id"].startswith(("product/", "pairing/"))]
    if not summaries:
        return []
    p = _load_pool([])
    if p is None:
        return None
    found = []
    for s in summaries:
        version = pool._built_version(s, [])
        found.append({"id": s["id"], "title": s.get("title") or s["id"], "player": s.get("player"),
                      "status": "built", "kind": "casual", "version": version, "ready": _ready(s, version, p)})
    return found


def _built_rates(forge, ready):
    """forge's pair rates whose two lists are the ready decks' built lists (each rate's "versions")."""
    built = {d["id"]: d["version"] for d in ready}
    return {pair: rate for pair, rate in forge.items()
            if tuple(rate.get("versions") or ()) == (built.get(pair[0]), built.get(pair[1]))}


def pairs_view():
    """GET /api/play/pairs: see the module's docstring."""
    today = play_records._play_today()
    if not _home_viewer():
        return {"available": False, "pairs": [], "ready": 0, "unconfirmed": 0, "error": None, "forge_error": None,
                "today": today}
    answer = {"available": True, "pairs": [], "ready": 0, "unconfirmed": 0, "error": None, "forge_error": None,
              "today": today}
    found = _decks()
    if found is None:
        return {**answer, "error": NO_POOL}
    ready = [d for d in found if d["ready"] is True]
    answer["ready"], answer["unconfirmed"] = len(ready), sum(1 for d in found if d["ready"] is None)
    if len(ready) < 2:
        return answer
    played = library_played._games()
    if played is None:
        return {**answer, "error": NO_GAMES}
    games = [{"date": day, "sides": [deck_id for deck_id, _ in sides], "result": result}
             for day, _ids, sides, result in played if len(sides) == 2]
    forge, answer["forge_error"] = library_forge.pair_rates()
    answer["pairs"] = play_pairs.suggest(ready, games, _built_rates(forge, ready), today)
    return answer
