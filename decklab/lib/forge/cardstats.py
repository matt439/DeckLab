"""Per-card stats from the card log (Milestone 8): what each card of a list did in Forge's
games, counted from the tallies runs keep in each batch ("cards", saved._pooled_cards),
for one side of a matchup (side_cards, the matchup page's) or pooled over every saved
matchup of a list (list_cards, the deck page's). With the helpers ai.py and views.py
share, which sit here because this part comes before both: a list's cards by .dck name
(_merged_cards), whether a card is a land (_is_land), the Wilson range and rounding.

A CardStats dict:
    {"games": games with card data (G), "bad": games whose card log failed its checks
     (not counted), "old": games an earlier card log kept tallies for (version 1, which
     counted a cast the AI couldn't finish: not counted either), "of": every counted game
     of the results used (so "from G of of games": batches played before the card log,
     or while it was off, have none), "matchups": results with card data of a version
     counted today (side_cards: 1, or 0 when it has only older card data), "basis"
     ("early" when any of G was kept by a version 3 card log, which counts "in hand by
     turn 3", else "drawn": what the rows' verdicts are on), "early_of" (those version 3
     games, E: what a row's early numbers are out of), "enough": the games the verdicts
     are on (E with basis "early", else G) >= MIN_CARD_GAMES (below it the numbers are
     shown, but called early), "min_games", "min_split", "rows": [Row], "commander":
     [CommanderRow]}
A Row is one .dck name of the list's Main (repeated printings and both faces of a card
are one row), nonlands (and cards the card data doesn't know) first, then lands, each
by name:
    {"name" (Scryfall's), "qty", "land" (True, False, or None when the card data doesn't
     know it), "drawn_games" (games any copy reached the hand: the kept hand or drawn,
     tutored or returned later), "drawn_share" (of G), "copies_drawn" (copies, over all
     games), "cast" (copies drawn that were cast or, for a land, played: "used"),
     "cast_share" and "stuck_share" (of copies_drawn), "stuck" (copies in hand when the
     game ended; a copy cast, bounced and held is both cast and stuck), "discarded"
     (copies that went from hand to the graveyard: discarded, cycled...), "other_casts"
     (casts from anywhere but the hand: flashback, an adventure's creature from exile...),
     "avg_turn" (on average, the round a cast copy was first cast or played in: round 1
     is each player's first turn, so it means the same on the play and on the draw),
     "wr_drawn" and "wr_not" (win rate in the games it was drawn in and in the rest:
     {"value", "low", "high", "games", "wins"}, the range Wilson's 95%), "early_games"
     (games of E a copy was in hand by the side's own turn 3: kept, or drawn by then),
     "early_share" (of E), "wr_early" and "wr_not_early" (win rate in those games and in
     the rest of E), "basis" (the CardStats dict's), "diff" (the win rate in the basis's
     games minus in the rest: when in hand by turn 3 minus when not ("early"), or when
     drawn minus when not ("drawn", and a land's whatever the basis), compared within
     each matchup (_difference): {"value", "low", "high"}; for one matchup it's the two
     rates' difference with Newcombe's range), "shrunk" (diff's value pulled toward 0,
     the best estimate of what the card did: _shrunk), "p" (how often chance alone would
     give a difference at least this far from 0), "judged" (both have MIN_SPLIT_GAMES
     games, and the card isn't a land), "discovery" (once judged: whether it stands out
     among the judged rows, a Benjamini-Hochberg discovery at FALSE_DISCOVERIES),
     "verdict" ("more", "less" or "unclear" once judged: "more" or "less" only for a
     discovery whose range is above or below 0)}
Without version 3 data (E 0) the early numbers are None and the basis is "drawn".
A land is never judged, though its win rates and diff are there (no "shrunk" or "p"):
the games without a copy of a land were mostly games short of lands, or of that colour,
so its difference says how those games went, not what the land did. With nothing to
judge, its diff stays the drawn split's under either basis, so the command line's
difference matches the drawn rates both it and the page show for a land; its early
numbers are there as a spell's are.
A CommanderRow is the same for a commander, by casts instead of draws (no early numbers:
a commander is always there to cast):
    {"name", "cast_games" (games it was cast in), "cast_share" (of G), "casts" (all
     its casts, recasts from the command zone included), "avg_first_turn" (the round of
     its first cast, on average), "wr_cast", "wr_not_cast", "diff", "shrunk", "p",
     "judged", "discovery", "verdict"}
The CardStats dict also says how its differences were judged: "compared" (the judged
rows, commanders too: the verdicts' Benjamini-Hochberg family), "fdr"
(FALSE_DISCOVERIES), "spread" (how far real card effects spread from 0, as a share:
what "shrunk" pulls toward 0 by, _spread) and "spread_weight" (0 to 1: how much of it
is this list's own cards' estimate rather than CARD_SPREAD).
Win rates are raw (wins over games; draws, timeouts and errors aren't wins), not
balanced for who went first as the matchup's headline is: that moves a card's rate by
about a point, well inside its range. Pooled over a list's matchups (list_cards), the
win rates are every game's, but diff compares like with like: a card drawn more often
against an easy opponent (where games run longer, say) would otherwise look better for
it. A share or rate with nothing to divide by is None, so there's never a NaN or an
infinity. Numbers are rounded to 4 places, turns to 1.

Why "in hand by turn 3" (sim-investigation/w1/m8/notes.md, on e4's 12,800 games): a card
drawn at any point is drawn more in long games, so "when drawn" leans with game length:
a card with no effect at all scores -6 to +9 points across the saved results and e4's
games, and a deck that wins the long games has cards that look good for it. By its own
turn 3 a side has seen 9 or 10 cards (fewer after a mulligan) whatever the game's
length, so the same blank card scores -0.5 to +1.5 points, and expensive cards'
differences come down to what a length-free measure gives. The price is fewer games
with the card (a 1-of is in hand by turn 3 in about 15% of games, against 26% drawn at
all), so ranges are a little wider for 1-ofs and 2-ofs and narrower for 4-ofs. Results
kept before version 3 have only the drawn split: their verdicts stay, and the pages say
they lean with game length.

Why these thresholds (from the 2026-10-02 statistics audit, sim-investigation r5):
- At MIN_CARD_GAMES = 800 games a card drawn in half of them has a 95% range of about
  +-7 points (a 1-of, drawn in about a quarter, +-8), and shrinking keeps about 60% of
  its measured difference. At 100 games (the old threshold) the range is +-20 to +-28
  points and shrinking keeps under 20%: numbers from fewer games are shown, but early.
- Most cards' real effect on the win rate is small: across the saved results the true
  spread was about 4.5 points (CARD_SPREAD) against about 4 points of noise, so a big
  difference from few games is mostly chance ("shrunk").
- A deck has 20 to 35 cards judged at once, so at a 95% range one or two "clear"
  differences turn up by chance alone: of 1,464 saved spell rows (allowing for game
  length), 311 had a range clear of 0 where 73 would by chance, and 152 survive
  Benjamini-Hochberg at 10%. Only such discoveries get "won more/less".
- Pooling a list's matchups naively moved verdicts too: comparing within each matchup
  changed 48 of 407 (r5's count, with a plain range; 43 with the range used here).
"""
import math
from statistics import NormalDist

from decklab.lib import cards

from .common import forge_name
from .lists import _list_text, _section_cards
from .saved import (CARD_TALLIES, COMMANDER_TALLIES, SHARED_TALLIES, _counted, _pooled_cards, _side_cards,
                    _stored)

MIN_CARD_GAMES = 800            # games the verdicts are on before a list's or side's numbers stop being early
MIN_SPLIT_GAMES = 30            # drawn and not-drawn games each, before a win-rate difference gets a verdict
CARD_SPREAD = 0.045             # how far real card effects spread from 0 (SD, a share): r5's, when a list can't say
SPREAD_DOUBT = 0.5              # how far one list's spread (squared) may be from CARD_SPREAD's, as a share of it
FALSE_DISCOVERIES = 0.10        # Benjamini-Hochberg's false discovery rate for "won more/less"


# ============================================================ shared with ai.py and views.py

def wilson(wins, games, z=1.96):
    """The Wilson 95% range of wins in games, or (None, None) for no games."""
    if not games:
        return None, None
    p = wins / games
    d = 1 + z * z / games
    centre = (p + z * z / (2 * games)) / d
    half = z * math.sqrt(p * (1 - p) / games + z * z / (4 * games * games)) / d
    return centre - half, centre + half


def _r(x, digits=4):
    return None if x is None else round(x, digits)


def _card_fields(name):
    """The Scryfall card for a name (any form cards.resolve takes), or None."""
    try:
        exact = cards.resolve(name)
        return cards.card(exact) if exact else None
    except cards.INDEX_ERRORS:
        return None


def _is_land(name):
    """True for a land (its front face), None when the card data doesn't know it."""
    card = _card_fields(name)
    if card is None:
        return None
    return "Land" in (card.get("type_line") or "")


def _merged_cards(listed, kind):
    """[(Scryfall name, .dck name, qty, section)] of a side's Commander + Main, one per .dck name."""
    sections = ("Commander", "Main") if kind == "commander" else ("Main",)
    rows, where = [], {}
    order = [("Commander", q, n) for q, n in listed.get("Commander", [])] + \
            [("Main", q, n) for q, n in listed.get("Main", [])]
    for section, qty, name in order:
        if section not in sections:
            section = "Main"
        key = forge_name(name)
        if key in where:
            rows[where[key]][2] += qty
        else:
            where[key] = len(rows)
            rows.append([name, key, qty, section])
    return [tuple(r) for r in rows]


# ============================================================ numbers

def newcombe(wins1, games1, wins2, games2, z=1.96):
    """(difference, low, high): wins1/games1 minus wins2/games2 with Newcombe's hybrid
    score 95% range (his method 10, 1998), made from the two Wilson ranges; None when
    either has no games."""
    if not games1 or not games2:
        return None
    p1, p2 = wins1 / games1, wins2 / games2
    low1, high1 = wilson(wins1, games1, z)
    low2, high2 = wilson(wins2, games2, z)
    diff = p1 - p2
    return (diff, diff - math.sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2),
            diff + math.sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2))


def _share(part, whole):
    return _r(part / whole) if whole else None


def _mean_turn(total, times):
    return round(total / times, 1) if times else None


def _rate(wins, games):
    """{"value", "low", "high", "games", "wins"}: wins of games with its Wilson range
    (held to 0..1: the maths can stray past by a rounding error), or None for no games."""
    if not games:
        return None
    low, high = wilson(wins, games)
    return {"value": _r(wins / games), "low": _r(max(0.0, low)), "high": _r(min(1.0, high)),
            "games": games, "wins": wins}


def _difference(strata):
    """(difference, low, high, se) of the win rate in the games a card was drawn (or a
    commander cast) in minus the rate in the rest, from strata [(in_games, in_wins, games,
    wins)], one per matchup; None when no stratum has games both ways.
    The difference is Mantel-Haenszel's: each stratum's own difference, weighted by
    in_games * out_games / games, so a card drawn more often in one matchup than another
    doesn't take that matchup's win rate for its own. A stratum with no games one way has
    nothing to compare and no weight. The range is Newcombe's within each stratum, put
    together for the weighted sum as Zou and Donner's MOVER does (2008): with one stratum
    it's that stratum's Newcombe range. se is the plain (Wald) standard error of the same
    weighted sum, each rate given half a win and a game so it's never 0; the p-value and
    shrinking use it."""
    parts = []
    for in_games, in_wins, games, wins in strata:
        out_games, out_wins = games - in_games, wins - in_wins
        both = newcombe(in_wins, in_games, out_wins, out_games)
        if both is None:
            continue
        p_in, p_out = (in_wins + 0.5) / (in_games + 1), (out_wins + 0.5) / (out_games + 1)
        variance = p_in * (1 - p_in) / in_games + p_out * (1 - p_out) / out_games
        parts.append((in_games * out_games / games, both, variance))
    if not parts:
        return None
    if len(parts) == 1:
        _, (diff, low, high), variance = parts[0]
        return diff, low, high, math.sqrt(variance)
    total = sum(weight for weight, _, _ in parts)
    shares = [(weight / total, both, variance) for weight, both, variance in parts]
    diff = sum(c * both[0] for c, both, _ in shares)
    low = diff - math.sqrt(sum((c * (both[0] - both[1])) ** 2 for c, both, _ in shares))
    high = diff + math.sqrt(sum((c * (both[2] - both[0])) ** 2 for c, both, _ in shares))
    return diff, low, high, math.sqrt(sum(c * c * variance for c, _, variance in shares))


def _split(in_games, in_wins, games, wins, strata=None):
    """(rate in, rate out, diff, judged, exact) for the games a card was drawn in (or in
    hand by turn 3, or a commander cast in) against the rest, out of games with wins; diff
    compared within each of strata (_difference; None: the totals are the one stratum),
    and exact its (unrounded value, se), or None with no diff. The verdict comes later
    (_judge), once every row's is known."""
    out_games, out_wins = games - in_games, wins - in_wins
    both = _difference(strata if strata is not None else [(in_games, in_wins, games, wins)])
    diff, exact = None, None
    if both is not None:
        # + 0.0: a difference that rounds to nothing is 0.0, not -0.0.
        diff = {"value": _r(both[0]) + 0.0, "low": _r(max(-1.0, both[1])) + 0.0,
                "high": _r(min(1.0, both[2])) + 0.0}
        exact = both[0], both[3]
    judged = diff is not None and in_games >= MIN_SPLIT_GAMES and out_games >= MIN_SPLIT_GAMES
    return _rate(in_wins, in_games), _rate(out_wins, out_games), diff, judged, exact


def _row(name, qty, numbers, games, wins, strata=None, early=None):
    """(Row, exact) of one card from its pooled tallies (saved._pooled_cards' row) out of
    games with wins, compared within strata (_split). early: (early_of_games, early_of_wins,
    early strata) when there's version 3 data, so the difference, its verdict and the rest
    are the early split's ("basis" "early"), the drawn rates staying as they are; None
    without it ("basis" "drawn", the early numbers None). A land keeps the drawn split's
    difference either way (the module docstring says why)."""
    drawn_games, drawn_wins, copies, used, stuck, round_sum, other_casts, discarded = numbers[:SHARED_TALLIES]
    drawn, not_drawn, diff, judged, exact = _split(drawn_games, drawn_wins, games, wins, strata)
    land = _is_land(name)
    early_games = early_share = in_hand = not_in_hand = None
    if early is not None:
        of_games, of_wins, early_strata = early
        early_games, early_wins = numbers[SHARED_TALLIES:CARD_TALLIES]
        early_share = _share(early_games, of_games)
        in_hand, not_in_hand, early_diff, early_judged, early_exact = _split(early_games, early_wins, of_games,
                                                                             of_wins, early_strata)
        if land is not True:
            diff, judged, exact = early_diff, early_judged, early_exact
    if land is True:        # never judged (the module docstring says why); its rates and drawn diff stay
        judged, exact = False, None
    return {"name": name, "qty": qty, "land": land,
            "drawn_games": drawn_games, "drawn_share": _share(drawn_games, games),
            "copies_drawn": copies, "cast": used, "cast_share": _share(used, copies),
            "stuck": stuck, "stuck_share": _share(stuck, copies), "discarded": discarded,
            "other_casts": other_casts, "avg_turn": _mean_turn(round_sum, used),
            "wr_drawn": drawn, "wr_not": not_drawn,
            "early_games": early_games, "early_share": early_share, "wr_early": in_hand, "wr_not_early": not_in_hand,
            "basis": "drawn" if early is None else "early",
            "diff": diff, "shrunk": None, "p": None, "judged": judged, "discovery": None, "verdict": None}, exact


def _commander_row(name, numbers, games, wins, strata=None):
    cast_games, cast_wins, casts, round_sum = numbers
    cast, not_cast, diff, judged, exact = _split(cast_games, cast_wins, games, wins, strata)
    return {"name": name, "cast_games": cast_games, "cast_share": _share(cast_games, games), "casts": casts,
            "avg_first_turn": _mean_turn(round_sum, cast_games),
            "wr_cast": cast, "wr_not_cast": not_cast, "diff": diff, "shrunk": None, "p": None, "judged": judged,
            "discovery": None, "verdict": None}, exact


def _p_value(value, se):
    """Two-sided: how often chance alone would put a difference at least this far from 0."""
    return 2 * NormalDist().cdf(-abs(value) / se)


def _spread(found):
    """(spread, weight): how far real card effects spread from 0 (their SD, as a share),
    from found [(difference, se)], the judged spells' (not lands' or commanders': a
    commander cast or not mostly says how the game went), and the weight their own
    estimate got. Each difference's square is, on average, the spread's square plus its
    se's, so the cards' own estimate of that square is the mean of difference^2 - se^2
    (method of moments: by chance it can come out below 0). Its standard error is
    sqrt(2 * sum((CARD_SPREAD^2 + se^2)^2)) / n, worked out at CARD_SPREAD so it doesn't
    depend on itself. It's averaged with CARD_SPREAD^2 (r5's, over every saved card,
    which any one list's may be off by SPREAD_DOUBT of itself) by precision: with few
    cards, or few games each, the spread stays near CARD_SPREAD; with many it's the
    list's own. Its own gets half the weight at about 21 cards and 800 games (14 at
    1,600, 40 at 400), and the spread is never below 0."""
    prior = CARD_SPREAD ** 2
    if not found:
        return CARD_SPREAD, 0.0
    n = len(found)
    own = sum(d * d - se * se for d, se in found) / n
    error = 2 * sum((prior + se * se) ** 2 for _, se in found) / (n * n)        # its variance
    doubt = (SPREAD_DOUBT * prior) ** 2
    weight = doubt / (doubt + error)
    return math.sqrt(max(0.0, prior + weight * (own - prior))), weight


def _shrunk(value, se, spread):
    """A difference pulled toward 0 by how noisy it is (normal-normal empirical Bayes):
    value * spread^2 / (spread^2 + se^2). Real card effects spread about 0 by spread, and
    chance by se, so the more of a difference chance could explain, the less of it is
    kept: at 800 games about 60%, at 100 under 20%."""
    return value * spread * spread / (spread * spread + se * se)


def _discoveries(ps, rate=FALSE_DISCOVERIES):
    """The indexes of ps (p-values) that are Benjamini-Hochberg discoveries at a false
    discovery rate of rate: ranked from the smallest, every one up to the last whose p
    is at most rate * rank / len(ps). At most that share of the discoveries are chance,
    on average, however many rows were compared."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    last = 0
    for rank, i in enumerate(order, 1):
        if ps[i] <= rate * rank / len(ps):
            last = rank
    return set(order[:last])


def _judge(scored):
    """Give scored [(Row or CommanderRow, exact, spell)] their "shrunk", "p", "discovery"
    and "verdict" (exact: _split's (value, se), or None; spell: a row of the deck's
    cards, not a commander's, so it counts toward the spread). Returns (spread, the
    weight the list's own cards got in it, rows compared). A judged row is a discovery
    among every judged row (_discoveries), and gets "more" or "less" only when it is one
    and its range, rounded as the page shows it, is above or below 0; any other judged
    row is "unclear". So a range that misses 0 by chance among many cards says
    "unclear", and the page can say why."""
    judged = [(row, exact) for row, exact, _ in scored if row["judged"]]
    spread, weight = _spread([exact for row, exact, spell in scored if row["judged"] and spell])
    for row, exact, _ in scored:
        if exact is not None:
            row["shrunk"] = _r(_shrunk(*exact, spread)) + 0.0
            row["p"] = _r(_p_value(*exact))
    found = _discoveries([_p_value(*exact) for _, exact in judged])
    for i, (row, _) in enumerate(judged):
        row["discovery"] = i in found
        clear = "more" if row["diff"]["low"] > 0 else "less" if row["diff"]["high"] < 0 else None
        row["verdict"] = clear if clear and row["discovery"] else "unclear"
    return spread, weight, len(judged)


def _by_name(row):
    return row["name"].casefold(), row["name"]


# ============================================================ what the page gets

def _strata(pooled, part, dck_name, early=False):
    """[(in_games, in_wins, games, wins)] of a card (part "rows") or commander ("commander")
    in each of pooled's strata (saved._pooled_cards' "strata"), or None when pooled has
    none (made by hand: its totals are then the one stratum). early: a card's games in
    hand by turn 3 out of each stratum's version 3 games (a stratum without any has no
    games, so it has no weight) instead of its games drawn out of all of them."""
    strata = pooled.get("strata")
    if strata is None:
        return None
    if early:
        return [(*(s["rows"].get(dck_name) or (0, 0, 0, 0))[2:4], s.get("early_of_games", 0),
                 s.get("early_of_wins", 0)) for s in strata.values()]
    return [(*(s[part].get(dck_name) or (0, 0))[:2], s["games"], s["wins"]) for s in strata.values()]


def card_rows(listed, kind, pooled, of, *, matchups=1):
    """A CardStats dict for a list ({"Commander": [[qty, name]], "Main": [...]}, kind
    "commander" or "constructed") from pooled tallies (saved._pooled_cards, summed over
    every side that played it, with each result's part kept as a stratum), out of of
    counted games, from matchups results. Every card of the list has a row, with zeros
    for one the tallies don't name; the tallies' names are .dck names (front faces), as
    _merged_cards gives them. Each difference is compared within each stratum, then the
    rows are judged together (_judge). With version 3 data (pooled's early_of_games), the
    rows are judged on the early split ("basis" "early"), else on the drawn one ("drawn").
    "enough" counts the games the verdicts are on: beside version 2 batches, only the
    version 3 ones (a commander's, from all of them, is called early with the rest)."""
    games, wins = pooled["games"], pooled["wins"]
    early_of = pooled.get("early_of_games", 0)
    basis = "early" if early_of else "drawn"
    rows, commander, scored = [], [], []
    for name, dck_name, qty, section in _merged_cards(listed or {}, kind):
        if section == "Commander":
            numbers = pooled["commander"].get(dck_name) or [0] * COMMANDER_TALLIES
            row, exact = _commander_row(name, numbers, games, wins, _strata(pooled, "commander", dck_name))
            commander.append(row)
        else:
            numbers = pooled["rows"].get(dck_name) or [0] * CARD_TALLIES
            early = None if basis == "drawn" else (
                early_of, pooled.get("early_of_wins", 0), _strata(pooled, "rows", dck_name, early=True))
            row, exact = _row(name, qty, numbers, games, wins, _strata(pooled, "rows", dck_name), early)
            rows.append(row)
        scored.append((row, exact, section != "Commander"))
    spread, weight, compared = _judge(scored)
    rows.sort(key=lambda row: (row["land"] is True, *_by_name(row)))
    return {"games": games, "bad": pooled["bad"], "old": pooled.get("old", 0), "of": of, "matchups": matchups,
            "enough": (early_of if basis == "early" else games) >= MIN_CARD_GAMES, "min_games": MIN_CARD_GAMES,
            "min_split": MIN_SPLIT_GAMES, "basis": basis, "early_of": early_of,
            "compared": compared, "fdr": FALSE_DISCOVERIES, "spread": _r(spread), "spread_weight": round(weight, 2),
            "rows": rows, "commander": sorted(commander, key=_by_name)}


def side_cards(result, side):
    """CardStats for side 0 or 1 of a stored result ("of": all its counted games), or
    None when none of its batches has card data of a version counted today or an older
    one (it was played before the card log, or without it). A result whose only card data
    is older (_pooled_cards' "old") gets stats with games 0 and its old games, and
    "matchups" 0."""
    pooled = _pooled_cards(result, side)
    if not pooled["batches"] and not pooled["old"]:
        return None
    s = result["sides"][side]
    return card_rows(_side_cards(s), s["kind"], pooled, _counted(result), matchups=int(pooled["batches"] > 0))


def list_cards(sections, kind, results=None, results_dir=None, *, keep=None):
    """CardStats for a list (sections as decks.load_deck gives them) pooled over every
    saved result that played it with today's engine of the card log's kind: each side with
    its card_sha and today's decklab-kind side id (engine.side_ids, whatever the card log's
    state now: per-card data only ever comes from the card log; both sides of a mirror, each
    once) adds its tallies and its counted games ("of", with or without card data). The
    sides of this list played with another engine (before wave 2, plain Forge, another Forge
    version or setting) are left out, and their counted games are "other_engine_games". With
    results (as load() gives them), those are pooled as they are: the caller picked them (and
    there's no "other_engine_games"). Each result's tallies are also kept apart, so a card's
    win-rate difference is compared matchup by matchup (card_rows, _difference), while its
    two win rates are every game's. When all their card data is older, the stats have games
    0, its games in "old" and "matchups" 0; when this list was played only with other engines
    (as every list is after the engine changes, until replay plays them again), games 0 and
    those games in "other_engine_games", so the page says why there are no numbers, and how
    to get them (not that no game was played with the card log: those games may well have
    been). None when no saved result played this list at all, or none has card data of
    today's version or an older one (with results given). keep(result), when supplied, excludes
    private evidence before any tallies, games or earlier-engine totals are counted."""
    from . import engine        # engine.py comes before this part; only this function uses it
    listed = _section_cards(sections)
    sha = _list_text(listed, kind)[1]
    wanted = engine.side_ids(sha, kind)[engine.KIND_DECKLAB] if results is None else None
    pooled, of, matchups, other = None, 0, 0, 0
    for result in _stored(results_dir) if results is None else results:
        if keep is not None and not keep(result):
            continue
        before = pooled["batches"] if pooled else 0
        for side, s in enumerate(result["sides"]):
            if s["card_sha"] != sha:
                continue
            if wanted is not None and s.get("engine_id") != wanted:
                other += _counted(result)
                continue
            pooled = _pooled_cards(result, side, pooled)
            of += _counted(result)
        matchups += bool(pooled and pooled["batches"] > before)
    if not matchups and not (pooled and pooled["old"]) and not other:
        return None
    if pooled is None:
        pooled = _pooled_cards({}, 0)           # only other engines' games: none of today's
    stats = card_rows(listed, kind, pooled, of, matchups=matchups)
    if wanted is not None:
        stats["other_engine_games"] = other
    return stats
