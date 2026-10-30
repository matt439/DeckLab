"""A list's token peaks pooled over its saved results (E7-S08): the card log's per-game
tallies (cardlog.py's "tokens", saved._pooled_tokens) of every side that played the list with
today's card-log engine, as list_cards (cardstats.py) pools the per-card rows. The deck page's
Tokens part matches the logged names to the deck's token needs (decklab/lib/tokens/peaks.py).

    list_token_peaks(sections, kind, keep=...)
        {"games", "batches", "matchups", "untallied", "tokens": {logged name: [n1, n2, ...]},
         "other_engine_games" (from the saved results only)}
        or None when no saved result played the list
"""
from .lists import _list_text, _section_cards
from .saved import _counted, _pooled_tokens, _stored


def _wanted(sha, kind):
    """The list's side id with today's decklab-kind engine (engine.side_ids): per-game data only
    ever comes from the card log. Tests patch it here."""
    from . import engine        # engine.py comes before this part; only this function uses it
    return engine.side_ids(sha, kind)[engine.KIND_DECKLAB]


def list_token_peaks(sections, kind, results=None, results_dir=None, *, keep=None):
    """The token peaks of a list (sections as decks.load_deck gives them) pooled over every saved
    result that played it with today's card-log engine (each side with its card_sha and today's
    decklab-kind side id; both sides of a mirror, each once): saved._pooled_tokens' {"games",
    "batches", "untallied", "tokens"} plus "matchups" (results with a tally) and, from the saved
    results, "other_engine_games": the counted games of the sides that played the list with
    another engine, left out (as list_cards counts them), so the page says they need playing
    again rather than that there are no games; with only those, games 0. With results (as load()
    gives them), those are pooled as they are (the caller picked them; no "other_engine_games").
    keep(result), when given, leaves out a result before anything of it is counted (a viewer's
    hidden decks). None when no result kept played the list: the page says there are no games.
    The engine's side id is worked out only once a result has the list's card_sha."""
    sha = _list_text(_section_cards(sections), kind)[1]
    found = [r for r in (_stored(results_dir) if results is None else results)
             if any(s.get("card_sha") == sha for s in r["sides"]) and (keep is None or keep(r))]
    if not found:
        return None
    wanted = _wanted(sha, kind) if results is None else None
    pooled, matchups, played, other = None, 0, False, 0
    for result in found:
        before = pooled["batches"] if pooled else 0
        for side, s in enumerate(result["sides"]):
            if s["card_sha"] != sha:
                continue
            if wanted is not None and s.get("engine_id") != wanted:
                other += _counted(result)
                continue
            played = played or _counted(result) > 0
            pooled = _pooled_tokens(result, side, pooled)
        matchups += bool(pooled and pooled["batches"] > before)
    if not played:
        if not other:
            return None
        pooled = _pooled_tokens({}, 0)          # only other engines' games: none of today's
    out = dict(pooled, matchups=matchups)
    if wanted is not None:
        out["other_engine_games"] = other
    return out
