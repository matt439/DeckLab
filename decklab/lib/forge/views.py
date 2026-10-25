"""What the page gets: the win-rate maths, a saved result as a row of a list
(list_item), every number the matchup page shows (view), and the saved results as
rows (results, results_for). wilson() and _r() moved down to cardstats.py in
Milestone 8 (the per-card stats use them too); views.wilson still works."""
import math
import traceback
from statistics import NormalDist

from . import common, engine, pilots
from .ai import _commander_unplayable
from .cardstats import _is_land, _merged_cards, _r, side_cards, wilson
from .saved import _pooled, _side_cards, _stored


# ============================================================ numbers

def balanced(play_wins, play_games, draw_wins, draw_games, z=1.96):
    """(value, low, high): the mean of the win rates on the play and on the draw, with a
    Wilson-based MOVER range (approximately 95% at the default z); None when either
    has no games. Recover each stratum's lower/upper variance from its score interval,
    then combine with equal weights: Zou, Huang & Zhang (2009), section 2,
    https://doi.org/10.1016/j.csda.2008.09.033. Unlike the Wald interval, a stratum with
    only wins or only losses still contributes uncertainty."""
    if not play_games or not draw_games:
        return None
    p1, p2 = play_wins / play_games, draw_wins / draw_games
    value = (p1 + p2) / 2
    low1, high1 = wilson(play_wins, play_games, z)
    low2, high2 = wilson(draw_wins, draw_games, z)
    low = value - 0.5 * math.hypot(p1 - low1, p2 - low2)
    high = value + 0.5 * math.hypot(high1 - p1, high2 - p2)
    return value, max(0.0, low), min(1.0, high)


def _comparison(games, p):
    """A minus B's win rate, with a conservative approximate 95% range. Nonwins count
    against both sides, so 50% of all games is not the threshold for being ahead.
    Both marginal rates use 97.5% intervals (Bonferroni); subtract opposite endpoints
    rather than treating the two mutually exclusive outcomes as independent. Balance
    for the starter when both strata exist, otherwise compare the raw shares."""
    if not games:
        return None
    play = [g for g in games if g["first"] == p]
    draw = [g for g in games if g["first"] == 1 - p]
    z = NormalDist().inv_cdf(1 - 0.05 / 4)
    rates = []
    for side in (p, 1 - p):
        if play and draw:
            rate = balanced(sum(g["w"] == side for g in play), len(play),
                            sum(g["w"] == side for g in draw), len(draw), z)
        else:
            wins = sum(g["w"] == side for g in games)
            rate = (wins / len(games), *wilson(wins, len(games), z))
        rates.append(rate)
    a, b = rates
    return {"value": _r(a[0] - b[0]), "low": _r(max(-1.0, a[1] - b[2])),
            "high": _r(min(1.0, a[2] - b[1])), "balanced": bool(play and draw)}


ABOUT_EVEN = 0.05      # "about even": the lead's range stays within 5 points of an even split (owner, 2026-10-03)

# The lead's verdicts (_lead), worded the same on the page (matchups.js matchupVerdict) and on the
# command line; {leader} is the deck that's ahead.
VERDICT_WORDS = {
    "ahead": "{leader} is ahead in these AI games: its win rate is higher after allowing for uncertainty.",
    "slightly_ahead": "{leader} is slightly ahead (by under 5 points) in these AI games: its win rate is higher "
                      "after allowing for uncertainty, and within 5 points of an even split.",
    "about_even": "About even in these AI games: after allowing for uncertainty, the two win rates are within "
                  "5 points of an even split.",
    "not_settled": "Not settled yet: the range still allows either deck to be ahead, perhaps by more than "
                   "5 points. More games would narrow it.",
}


def _lead(games, p, winrate, comparison):
    """Which deck is ahead in these games, from side p's point of view: {"verdict", "side",
    "basis"}, or None without games. verdict (VERDICT_WORDS' keys):
    - "ahead" when the lead's range leaves out an even split, "side" saying which (0: p, 1:
      the other side);
    - "about_even" when the range stays within ABOUT_EVEN of it ("side" None);
    - "slightly_ahead" when both hold, as more games make likely for a near-even matchup;
    - "not_settled" otherwise.
    When every game has a winner (basis "decided"), the range is the headline's (winrate:
    p's share of the games, balanced for the starter when both decks went first): a deck
    is ahead when it leaves out 50%, about even inside 45% to 55%. With draws, timeouts or
    errors (basis "comparison"), which count against both decks, it's _comparison's range of
    p's win rate minus the other's, so a stratum's nonwins aren't thrown away (the
    2026-10-01 review); about even is then within 2 x ABOUT_EVEN of the share of games
    decided (balanced the same way), the same split of the decided games. The rounded
    numbers are used, so a verdict never disagrees with the range the page shows."""
    if not games or comparison is None or winrate.get("low") is None:
        return None
    if all(g["w"] is not None for g in games):
        basis, low, high, margin = "decided", winrate["low"] - 0.5, winrate["high"] - 0.5, ABOUT_EVEN
    else:
        play = [g for g in games if g["first"] == p]
        draw = [g for g in games if g["first"] == 1 - p]
        if play and draw:
            decided = (sum(g["w"] is not None for g in play) / len(play)
                       + sum(g["w"] is not None for g in draw) / len(draw)) / 2
        else:
            decided = sum(g["w"] is not None for g in games) / len(games)
        basis, low, high, margin = "comparison", comparison["low"], comparison["high"], 2 * ABOUT_EVEN * decided
    side = 0 if low > 0 else 1 if high < 0 else None
    even = margin > 0 and low >= -margin - 1e-9 and high <= margin + 1e-9
    verdict = ("slightly_ahead" if side is not None and even else "ahead" if side is not None
               else "about_even" if even else "not_settled")
    return {"verdict": verdict, "side": side, "basis": basis}


def verdict_words(lead, leader_titles):
    """The lead's verdict in words (VERDICT_WORDS), the deck ahead named from leader_titles
    ([p's title, the other's]); None without a lead."""
    if not lead:
        return None
    leader = leader_titles[lead["side"]] if lead["side"] is not None else ""
    return VERDICT_WORDS[lead["verdict"]].format(leader=leader)


def _starter(games):
    """The starting player's chance of winning: the mean of both decks' win rates on the play,
    with balanced()'s range ({"value", "low", "high", "balanced": True}), as if each deck went
    first in half the games. (The share of games the starter won says little: in a v1 or
    plain-Forge result the loser of each game goes first in the next, so in a lopsided
    matchup the weaker deck starts most of them; the v2 engine's coin flip every game only
    evens that out on average.) When a deck never went first, that share with its Wilson
    range ("balanced" False); None without a game whose starter is known. Either deck's
    point of view gives the same."""
    first = [[g for g in games if g["first"] == side] for side in (0, 1)]
    both = balanced(sum(g["w"] == 0 for g in first[0]), len(first[0]), sum(g["w"] == 1 for g in first[1]),
                    len(first[1]))
    if both:
        return {"value": _r(both[0]), "low": _r(both[1]), "high": _r(both[2]), "balanced": True}
    known = first[0] + first[1]
    if not known:
        return None
    wins = sum(g["w"] == g["first"] for g in known)
    low, high = wilson(wins, len(known))
    return {"value": _r(wins / len(known)), "low": _r(low), "high": _r(high), "balanced": False}


def _noise_points(winrate):
    """How far apart, in points, two results of this many games of these decks can come out by
    chance alone (about 95% of the time): the headline range's half-width times the square
    root of 2, as for the difference of two independent results. About 3.5 at 1,600 games of
    a near-even matchup (r5-stats: +-2.4 each). None without a range."""
    if winrate.get("low") is None or winrate.get("high") is None:
        return None
    return round(100 * (winrate["high"] - winrate["low"]) / math.sqrt(2), 1)


def _games(result):
    return [g for b in result.get("batches", []) for g in b["games"]]


def _perspective(result, perspective_sha):
    """0 or 1: the side the numbers are for (side 0 when perspective_sha is neither)."""
    sides = result["sides"]
    return 1 if sides[0]["card_sha"] != perspective_sha and sides[1]["card_sha"] == perspective_sha else 0


def _winrate(games, p):
    """{"winrate", "raw", "on_play", "on_draw"} for side p."""
    n = len(games)
    wins = sum(1 for g in games if g["w"] == p)
    play = [g for g in games if g["first"] == p]
    draw = [g for g in games if g["first"] == 1 - p]
    play_wins = sum(1 for g in play if g["w"] == p)
    draw_wins = sum(1 for g in draw if g["w"] == p)
    low, high = wilson(wins, n)
    raw = {"value": _r(wins / n) if n else None, "low": _r(low), "high": _r(high)}
    both = balanced(play_wins, len(play), draw_wins, len(draw))
    if both:
        winrate = {"value": _r(both[0]), "low": _r(both[1]), "high": _r(both[2]), "balanced": True}
    else:
        winrate = dict(raw, balanced=False)
    return {
        "winrate": winrate, "raw": raw,
        "on_play": {"games": len(play), "wins": play_wins, "value": _r(play_wins / len(play)) if play else None},
        "on_draw": {"games": len(draw), "wins": draw_wins, "value": _r(draw_wins / len(draw)) if draw else None},
    }


# ============================================================ what the page gets

def page_kind(deck_id):
    """The page's kind for a deck id: casual, commander, product or pairing (a
    person's "<space>/<kind>/<slug>" is its kind; casual for anything else,
    such as a .dck file's "file:" id)."""
    from decklab.lib import spaces
    try:
        return spaces.split_deck_id(deck_id or "")[1]
    except ValueError:
        return "casual"


def _page_side(side):
    """A stored side for the page: where it was last played (id, version, title), its kind,
    card_sha and card_count, "current" left for the api to fill, and "auto_profile": whether
    Forge's AI played it as a slower, non-aggro deck in every game (its auto-profile, as the
    run's DLENGINE line said: engine.side_fields' "auto_profile" flag), None when unknown (plain
    Forge doesn't say, nor did runs before wave 2: engine.auto_profile_flag), and "pilot" (wave
    3): {"profile", "switches", "words"}, the AI pilot it was played with (its stored "pilot",
    else its "ai" profile), words None for Forge's Default profile with no switches."""
    seen = side["seen_as"][-1] if side.get("seen_as") else {}
    return {"id": seen.get("id"), "version": seen.get("version"), "title": seen.get("title"),
            "kind": page_kind(seen.get("id")), "card_sha": side["card_sha"],
            "card_count": side["card_count"], "current": None,
            "auto_profile": engine.auto_profile_flag(side), "pilot": _page_pilot(side)}


def _page_pilot(side):
    """A stored side's pilot for the page: {"profile", "switches", "words"} (pilots.words)."""
    found = side.get("pilot") if isinstance(side.get("pilot"), dict) else {}
    pilot = {"profile": found.get("profile") or side.get("ai") or pilots.DEFAULT_PROFILE,
             "switches": sorted(found.get("switches") or [])}
    return {**pilot, "words": pilots.words(pilot)}


def _not_meaningful(result):
    return any(_commander_unplayable(result, s) for s in (0, 1))


def _engine_view(result):
    """What the page is told of the engine a result was played with (engine.py): {"kind":
    "decklab", "plain" or "v1" (saved before wave 2), "run_version", "current": whether a run of
    its two lists now would add to it (engine.is_current: always False for v1; None when that
    can't be told, as when Forge has never been found), "words": why it isn't today's engine in
    a sentence, or None}. Which kind runs play follows the card log's readiness, so while the
    card log is off (no JDK, a check pending, a build problem) the decklab kind's results are
    "current": False, labelled "Earlier engine" on the page, and the plain kind's are today's,
    until the card log can be used again. A result whose engine can't be worked out (a
    settings file that can't be read) is told as None, and logged: the page still shows."""
    kind = engine.kind_of(result)
    try:
        current = engine.is_current(result)
        words = engine.words(result, current)
    except Exception as e:
        common._log(f"The engine of the matchup result {result.get('key', '?')[:12]} can't be worked out "
                    f"({type(e).__name__}: {e}).")
        current = words = None
    return {"kind": kind, "run_version": result.get("run_version") or 1, "current": current, "words": words}


def list_item(result, perspective_sha=None):
    """A stored result as a row of a list: key, format, both sides (the perspective's
    first; without one, the list the last run was asked for first; id/version/title
    from where each was last played, "current" left for the api to fill), games, the
    perspective's win rate, updated, by, not_meaningful and engine (_engine_view)."""
    runs = result.get("runs") or [{}]
    p = _perspective(result, perspective_sha or runs[-1].get("a"))
    games = _games(result)
    return {"key": result["key"], "format": result["format"],
            "sides": [_page_side(result["sides"][p]), _page_side(result["sides"][1 - p])],
            "games": len(games), "winrate": _winrate(games, p)["winrate"],
            "updated": result.get("updated"), "by": runs[-1].get("by"),
            "not_meaningful": _not_meaningful(result), "engine": _engine_view(result)}


def _side_cards_or_none(result, side):
    """side_cards(result, side), or None (logged) when they can't be worked out: the
    per-card stats are extra, and never stop the rest of the matchup page showing."""
    try:
        return side_cards(result, side)
    except Exception:
        common._log(f"The card stats of side {side} of the matchup result {result['key'][:12]} can't be "
                    f"worked out:\n" + traceback.format_exc())
        return None


def view(result, perspective_sha):
    """Every number the matchup page shows, from perspective_sha's side (index 0 of
    wins, casts...): see the contract's "Result". A result with no counted games has
    games 0 and no win rate. Partial batches (a stopped run's) count like whole ones.
    "cards" is each side's per-card stats from the card log (cardstats.side_cards; None
    for a side with no card record at all, or whose stats fail, which is logged; games 0
    and its games in "old" when its only records are an earlier card log's).
    "comparison" is the perspective's win rate minus the opponent's, with a conservative
    uncertainty range and whether it was balanced for the starter; None without games.
    "lead" is _lead()'s verdict on which deck is ahead (side 0 is the perspective's), "starter"
    the starting player's chance of winning (_starter) and "noise_points" how far two results
    of this many games can differ by chance (_noise_points); each None without games.
    "engine" is _engine_view's (the engine the games were played with)."""
    p = _perspective(result, perspective_sha)
    games = _games(result)
    n = len(games)
    rates = _winrate(games, p)
    comparison = _comparison(games, p)
    rounds = [g["rounds"] for g in games if g["rounds"]]
    ms = [g["ms"] for g in games]
    reasons = {}
    for g in games:
        if g.get("loss"):
            reasons[g["loss"]] = reasons.get(g["loss"], 0) + 1
    runs = result.get("runs", [])
    wall = sum(r.get("wall_s") or 0 for r in runs)
    played = sum(r.get("played") or 0 for r in runs)
    casts = []
    for s in (p, 1 - p):
        side = result["sides"][s]
        pooled, lands = _pooled(result, s)
        rows = []
        for name, dck_name, qty, _ in _merged_cards(_side_cards(side), side["kind"]):
            land = _is_land(name)
            c, g = pooled.get(dck_name, [0, 0])
            if land or (land is None and lands.get(dck_name) and not c):
                continue
            rows.append({"name": name, "qty": qty, "casts": c, "games": g})
        casts.append(sorted(rows, key=lambda row: (row["name"].casefold(), row["name"])))
    return {
        "key": result["key"], "format": result["format"], "forge_version": result.get("forge_version"),
        "games": n,
        "wins": [sum(1 for g in games if g["w"] == p), sum(1 for g in games if g["w"] == 1 - p)],
        "draws": sum(1 for g in games if g["r"] == "draw"),
        "timeouts": sum(1 for g in games if g["r"] == "timeout"),
        "errors": sum(1 for g in games if g["r"] == "error"),
        **rates,
        "comparison": comparison,
        "lead": _lead(games, p, rates["winrate"], comparison),
        "starter": _starter(games),
        "noise_points": _noise_points(rates["winrate"]) if n else None,
        "rounds": {"mean": round(sum(rounds) / len(rounds), 1), "min": min(rounds), "max": max(rounds)}
        if rounds else None,
        "game_ms": {"mean": round(sum(ms) / len(ms)), "max": max(ms)} if ms else None,
        "speed": {"games_per_min": round(played / wall * 60, 1) if wall and played else None,
                  "wall_s": round(wall, 1)},
        "ai_timeouts": sum(g.get("ai_to") or 0 for g in games),
        "loss_reasons": [{"reason": k, "games": v} for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))],
        "casts": casts,
        "cards": [_side_cards_or_none(result, p), _side_cards_or_none(result, 1 - p)],
        "runs": [{"when": r.get("when"), "by": r.get("by"), "asked": r.get("asked"), "played": r.get("played"),
                  "stopped": r.get("stopped", False), "stopped_by": r.get("stopped_by"),
                  "checkpoint": r.get("checkpoint", False), "recovered": r.get("recovered", False),
                  "recovery_note": r.get("recovery_note"),
                  "batches": r.get("batches"), "played_batches": r.get("played_batches"),
                  "partial": r.get("partial", 0), "seeds": r.get("seeds"),
                  "failed": r.get("failed", 0), "failure": r.get("failure"), "error": r.get("error"),
                  # Whether the card log was on (None: run before Milestone 8), and why not.
                  "card_log": r.get("card_log"), "card_log_problem": r.get("card_log_problem"),
                  # Wave 2's warm pool (None for a run of cold batches): where it played ("server",
                  # "local" or "remote"), its chunks, the workers recycled and the games played
                  # again after a recycle or a worker that failed.
                  "pool": r.get("pool"), "chunks": r.get("chunks"), "recycled": r.get("recycled", 0),
                  "requeued": r.get("requeued", 0)}
                 for r in runs],
        "failed_batches": len(result.get("failed", [])),
        "not_meaningful": _not_meaningful(result),
        "settings": dict(result.get("settings") or {}),
        "seeds": len(result.get("batches", [])) + len(result.get("failed", [])),
        "updated": result.get("updated"),
        "engine": _engine_view(result),
        **_adaptive_view(result, p),
    }


def _adaptive_view(result, p):
    """{"adaptive_last": the result's last adaptive summary while it applies (adaptive.last_summary,
    wave 3's R12), or None}, and with it "lead": the summary's decision (adaptive.lead_from_summary)
    in place of the plain one, so the headline word never contradicts the run's outcome
    (forge-trial/sim-wave3-contract.md section 7.3). The summary's "side" is the result's stored
    side; the lead's is p's point of view (0: p)."""
    from . import adaptive          # it comes after this part
    last = adaptive.last_summary(result)
    out = {"adaptive_last": last}
    lead = adaptive.lead_from_summary(last) if last is not None else None
    if lead is not None:
        side = lead.get("side")
        out["lead"] = dict(lead, side=None if side is None else (0 if side == p else 1))
    return out


def _items(stored, perspective_sha=None):
    """list_item() of each stored result; one that still can't be shown (a shape
    _is_result doesn't catch) is left out and logged, so it can't hide the rest."""
    out = []
    for result in stored:
        try:
            out.append(list_item(result, perspective_sha))
        except Exception as e:
            common._log(f"The matchup result {result['key'][:12]} can't be listed ({type(e).__name__}: {e}).")
    return out


def results(results_dir=None):
    """list_item() of every stored result with games in it, newest first, whatever its engine:
    each item's "engine" says which, and whether it's today's (_engine_view; today's engine is
    worked out once for the list, engine.held)."""
    with engine.held():
        return _items(_stored(results_dir))


def results_for(card_sha, results_dir=None):
    """list_item() from this list's side of every stored result it played in, newest first,
    whatever its engine (as results())."""
    with engine.held():
        return _items([r for r in _stored(results_dir) if card_sha in (s["card_sha"] for s in r["sides"])],
                      card_sha)
