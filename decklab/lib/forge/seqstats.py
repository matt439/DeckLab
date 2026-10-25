"""Sequential statistics for Deck Lab's simulations (simulation wave 3, the report's R12, R13
and R15): when an adaptive run stops, paired differences between a deck and a changed version
of it, the field average, a Bradley-Terry rating with a starter term, residual flags, and how a
field run spends its games. forge-trial/sim-wave3-contract.md section 7 is the specification:
every formula and constant here is that section's.

Every function is pure: it works on game dicts as results store them ({"g", "w": the winning
side or None, "first": the starting side or None, "r", "rounds", "turns", "ms", ...}), and side
p is the deck the question is about. The strata are p on the play (first == p) and p on the
draw; a game whose starter isn't known is in neither. A non-win (draw, timeout, error) counts as
a loss for p, as the headline win rate does. Standard library only. The page, the command
line, the coordinators (adaptive.py, field.py, variants.py, experiment.py) and the combined
run's harness share this one implementation. The numbers aren't rounded here (the ranges that
come from views are, as the page shows them); callers round what they show.

    assess_estimate(games, p)       the page's planned games before the pilot (section 7.2)
    assess_next(games, p, h, cap, topups_done, *, plan_done)
                                    (more games, reason) of an "assess" run (section 7.2)
    decided_share(games, p)         the decided-share statistic: estimate, SE, z (section 7.3)
    look(games, p, n_total, *, max_games, stopped)
                                    one look of a "who's ahead" run (section 7.3)
    ahead_next(games, p, *, max_games)
                                    (more games, the next look) of a "who's ahead" run
    last_look(max_games, looks)     the last look a run can reach (HP_FINAL's)
    anytime_range(games, p)         the anytime-valid range (section 7.6)
    anytime_counts(wins, games)    the same range from live win/game counts
    paired_games(base_games, paired_games_, base_side, variant_side)
                                    the games of both arms, matched by g (section 7.4)
    paired_diff(base_games, paired_games_, base_side, variant_side)
                                    the paired difference of one opponent (section 7.4)
    paired_field(diffs)             the field's paired difference over opponents (section 7.4)
    paired_verdict(low, high, margin)
                                    better / worse / little_difference / ... (section 7.4)
    paired_look(diff, games_per_opponent, *, looks, max_games, margin, stopped, interim)
                                    one look of an adaptive variant test (section 7.4)
    field_row(games, p)             one opponent's numbers for the field view (section 7.5)
    field_average(rows, of=None)    the equal-weight field average with its MOVER range
    bt_fit(data, *, prior_sd)       the Bradley-Terry fit with a starter term (section 7.5)
    bt_component(data, player)      the players connected to player by games
    bt_predict(fit, i, j)           i's predicted win chance against j, starter-balanced
    bt_rating(fit, player, field_players)
                                    the rating against an average field deck, and its rank
    residual_flags(data, fit, player, observed)
                                    leave-one-pairing-out residual flags, BH at RESIDUAL_FDR
    apt_pick(rows, k)               the k opponents a field run plays next (APT)
    spearman(xs, ys)                Spearman's rank correlation, average ranks for ties
"""
import math
import random

from decklab.lib import live_ranges
from decklab.lib.live_ranges import AV_RHO, AV_ALPHA
from . import views
from .cardstats import _discoveries, wilson

# ============================================================ constants (frozen names; section 7.1)

Z95 = 1.959964
HP_LOOKS = (400, 800, 1600, 3200)       # the looks of a "who's ahead" run, in games
HP_INTERIM = 3.0                        # the Haybittle-Peto bound at an interim look (and a stopped one)
HP_FINAL = 2.008                        # ... and at the last look the run can reach
ASSESS_PILOT = 400                      # an "assess" run's first stage
ASSESS_HALF_WIDTH = 0.03                # the half-width it plays to
ASSESS_MARGIN = 1.03                    # the plan's allowance for MOVER-Wilson's longer side
CAP = 3200                              # the most games an adaptive run plays
ASSESS_TOPUPS = 1                       # top-ups after the planned stage
EQUIV = 0.05                            # "about even": views.ABOUT_EVEN (checked by S's tests)
VARIANT_EQUIV_FIELD = 0.02              # config forge_variant_margin's default: against the field
VARIANT_EQUIV_ONE = 0.03                # config forge_variant_margin_one's default: against one deck
PAIRED_LOOKS = HP_LOOKS                 # a variant test's looks against one opponent
FIELD_PAIRED_LOOKS = (200, 400, 800, 1600)      # ... and against the field, per opponent
FIELD_FLOOR = 200                       # a field run's games per opponent before APT
FIELD_STEP = 100                        # games an APT pick plays
FIELD_CAP = 1600                        # no opponent gets more than this from APT
APT_EPS = 0.05                          # APT's epsilon (section 7.1)
RESIDUAL_FDR = 0.10                     # Benjamini-Hochberg's rate for the residual flags
RESIDUAL_POINTS = 0.05                  # ... and the smallest residual flagged
BT_PRIOR_SD = 4.0                       # the Bradley-Terry ratings' prior SD (logits)
BT_DRAWS = 4000                         # draws for the rank range

# The decisions of look() and paired_look(), and their outcomes as summaries store them
# (section 14.1).
DECISIONS = ("continue", "ahead", "slightly_ahead", "about_even", "not_settled", "not_settled_stopped")
PAIRED_VERDICTS = ("better", "worse", "slightly_better", "slightly_worse", "little_difference", "not_settled")

TOPUP_SLACK = 0.002                     # an assess top-up plays only when the half-width is this much over h
STARTER_MISMATCH_WARN = 0.01            # a variant test warns when more of its common games than this differ in starter
BT_ITERATIONS = 60                      # the Bradley-Terry fit's Newton-Raphson steps at most
BT_TOLERANCE = 1e-10                    # ... stopping once the largest step is under this
_EPS = 1e-9                             # slack for "within the margin" (as views._lead's)


# ============================================================ counting

def _strata(games, p):
    """[(games, p's wins, the other side's wins)] for p on the play, then p on the draw."""
    counts = [[0, 0, 0], [0, 0, 0]]
    for g in games:
        first = g.get("first")
        if first is None:
            continue
        s = 0 if first == p else 1
        counts[s][0] += 1
        if g.get("w") == p:
            counts[s][1] += 1
        elif g.get("w") is not None:
            counts[s][2] += 1
    return [tuple(c) for c in counts]


def _ceil25(x):
    """x rounded up to a multiple of 25 (an int)."""
    return int(math.ceil(x / 25 - 1e-9)) * 25


def _half_width(play_games, play_wins, draw_games, draw_wins, games=None, wins=None):
    """The larger side of views.balanced's range (the headline's), or of the raw share's Wilson
    range when p never went first or never went second (as the page falls back to it); None
    without games."""
    both = views.balanced(play_wins, play_games, draw_wins, draw_games)
    if both:
        value, low, high = both
    else:
        games = play_games + draw_games if games is None else games
        wins = play_wins + draw_wins if wins is None else wins
        if not games:
            return None
        value = wins / games
        low, high = wilson(wins, games)
    return max(value - low, high - value)


# ============================================================ assess (section 7.2)

def assess_estimate(games, p):
    """The page's estimate of an "assess" run's total games before its pilot is played:
    ceil25(Z95² · v / h²) with section 7.2's shrunk rates, h = ASSESS_HALF_WIDTH, and f the share
    of p's games on the play kept within 0.2-0.8 (0.5 with no games); kept within ASSESS_PILOT
    and CAP, because a run always plays its pilot and never more than CAP. For the time shown
    only, never for stopping. An int: 1,075 for a result with no games."""
    (n1, w1, _), (n2, w2, _) = _strata(games, p)
    n = n1 + n2
    f = min(0.8, max(0.2, n1 / n)) if n else 0.5
    p1, p2 = (w1 + 1) / (n1 + 2), (w2 + 1) / (n2 + 2)
    v = (p1 * (1 - p1) / f + p2 * (1 - p2) / (1 - f)) / 4
    return max(ASSESS_PILOT, min(CAP, _ceil25(Z95 ** 2 * v / ASSESS_HALF_WIDTH ** 2)))


def _assess(n, hw, h=ASSESS_HALF_WIDTH, cap=CAP, topups_done=0, plan_done=None):
    """assess_next's rule on n games whose range has half-width hw."""
    pilot = min(ASSESS_PILOT, cap)
    if n < pilot:
        return pilot - n, "pilot"
    if hw is not None and hw <= h:
        return 0, "precise"
    if n >= cap or hw is None:
        return 0, "capped"
    total = min(cap, _ceil25(max(n + 100, n * (hw / h) ** 2 * ASSESS_MARGIN)))
    if plan_done is None:
        plan_done = n > ASSESS_PILOT or topups_done > 0
    if not plan_done:
        return total - n, "plan"
    if hw > h + TOPUP_SLACK and topups_done < ASSESS_TOPUPS:
        return total - n, "top-up"
    return 0, "capped at plan"


def assess_next(games, p, h=ASSESS_HALF_WIDTH, cap=CAP, topups_done=0, *, plan_done=None):
    """(more games, reason) for an "assess" run with these games so far (section 7.2); more is 0
    when the run stops. In order:
    - fewer than ASSESS_PILOT games (or cap, when that's less): the rest of the pilot, "pilot";
    - the headline range's half-width hw (views.balanced's longer side) at most h: 0, "precise";
    - cap games or more: 0, "capped";
    - the plan not played yet: N_total − n, "plan", with N_total = ceil25(max(n + 100,
      n · (hw/h)² · ASSESS_MARGIN)) kept to cap;
    - after the plan, while hw > h + TOPUP_SLACK and topups_done < ASSESS_TOPUPS: N_total − n
      again, "top-up";
    - otherwise 0, "capped at plan".
    plan_done says whether the run has played the stage a "plan" answer asked for. A run that
    starts from a result already holding more than ASSESS_PILOT games should pass
    plan_done=False for its first call after the pilot, and True after its plan stage. Left as
    None it's worked out as (n > ASSESS_PILOT or topups_done > 0), which is right for a run that
    started with ASSESS_PILOT games or fewer."""
    (n1, w1, _), (n2, w2, _) = _strata(games, p)
    n = len(games)
    wins = sum(1 for g in games if g.get("w") == p)
    return _assess(n, _half_width(n1, w1, n2, w2, n, wins), h, cap, topups_done, plan_done)


# ============================================================ who's ahead (section 7.3)

def _decided(a, b):
    """(π̂, SE, z) of the decided-share statistic from p's wins a = [play, draw] and the other
    side's b; (None, None, None) when a stratum has no decided game."""
    d = (a[0] + b[0], a[1] + b[1])
    if not d[0] or not d[1]:
        return None, None, None
    pi = (a[0] / d[0] + a[1] / d[1]) / 2
    t = [(a[s] + 0.5) / (d[s] + 1) for s in (0, 1)]
    se = math.sqrt(t[0] * (1 - t[0]) / d[0] + t[1] * (1 - t[1]) / d[1]) / 2
    return pi, se, (pi - 0.5) / se


def decided_share(games, p):
    """The decided-share statistic of section 7.3: {"pi": π̂ (or None), "se": SE (or None),
    "z": z (or None: a stratum with no decided games), "a": [a_play, a_draw], "b": [b_play,
    b_draw], "d": [d_play, d_draw]}. a is p's wins, b the other side's; draws, timeouts and
    errors are in neither. The SE gives each stratum half a win and a decided game
    (cardstats._difference's rule), so 200-0 in both strata still has a finite z."""
    (_, a1, b1), (_, a2, b2) = _strata(games, p)
    pi, se, z = _decided((a1, a2), (b1, b2))
    return {"pi": pi, "se": se, "z": z, "a": [a1, a2], "b": [b1, b2], "d": [a1 + b1, a2 + b2]}


def last_look(max_games=CAP, looks=HP_LOOKS):
    """The last look a run of at most max_games can reach: the last entry of looks that is
    ≤ max_games (None when there's none; max_games None: looks' last)."""
    if max_games is None:
        return looks[-1] if looks else None
    reachable = [n for n in looks if n <= max_games]
    return reachable[-1] if reachable else None


def _is_final(n, max_games, looks):
    """Whether a look at n games is the last one the run can reach (every look is, when no
    entry of looks is reachable)."""
    last = last_look(max_games, looks)
    return last is None or n >= last


def _decide(z, bound, lead_side, even, final, stopped):
    """(decision, side) of a "who's ahead" look: section 7.3's rules on z, the bound, the side
    the page's lead puts ahead (0: p, or None) and whether the range judged lies within ±EQUIV.
    Without a z (a stratum with no decided game) the look can only go on."""
    if z is None:
        ahead, even, z_side = False, False, None
    else:
        z_side = 0 if z > 0 else 1
        ahead = abs(z) >= bound and lead_side == z_side
    if ahead:
        return ("slightly_ahead" if even else "ahead"), z_side
    if even:
        return "about_even", None
    return ("not_settled_stopped" if stopped else "not_settled" if final else "continue"), None


def look(games, p, n_total, *, max_games=CAP, stopped=False):
    """One look at games (n_total of them) for side p (section 7.3): {"look": n_total, "z",
    "bound", "low", "high", "decision", "side"}.
    - bound: HP_FINAL at the last look max_games reaches (n_total ≥ last_look(max_games)),
      HP_INTERIM at other looks and at a stopped one (stopped: the run was stopped between
      planned looks).
    - decision, one of DECISIONS: "ahead" when |z| ≥ bound and the page's lead (views._lead)
      puts the same side ahead; "about_even" when the range judged lies within ±EQUIV
      (planned look: the page's lead says about_even or slightly_ahead; stopped look: π̂ ±
      HP_INTERIM·SE lies within 0.5 ± EQUIV); "slightly_ahead" when both hold; otherwise
      "continue", "not_settled" at the last look, or "not_settled_stopped" for a stopped look.
      Without a z (a stratum with no decided game) the look continues or isn't settled.
    - side: the side ahead (0: p) for ahead and slightly_ahead, else None.
    - low and high: the range the decision was judged on: the headline range of p's win rate
      (rounded, as the page shows it) at a planned look; π̂ ± HP_INTERIM·SE, kept within 0-1, at
      a stopped one (None without a z).
    - basis: what the decision's range was: "decided" or "comparison" at a planned look (the
      page's lead's basis; with draws, timeouts or errors it's "comparison", judged on
      views._comparison's range, so low and high, which stay the headline rate, can sit below
      50% beside "ahead"), "decided_share" at a stopped look, None without a lead."""
    (n1, w1, o1), (n2, w2, o2) = _strata(games, p)
    pi, se, z = _decided((w1, w2), (o1, o2))
    final = _is_final(n_total, max_games, HP_LOOKS)
    bound = HP_INTERIM if stopped or not final else HP_FINAL
    rates = views._winrate(games, p)
    lead = views._lead(games, p, rates["winrate"], views._comparison(games, p))
    lead_side = lead["side"] if lead else None
    if stopped:
        low, high = (None, None) if pi is None else (pi - HP_INTERIM * se, pi + HP_INTERIM * se)
        even = low is not None and low >= 0.5 - EQUIV - _EPS and high <= 0.5 + EQUIV + _EPS
        basis = "decided_share"
        if low is not None:
            low, high = max(0.0, low), min(1.0, high)
    else:
        low, high = rates["winrate"].get("low"), rates["winrate"].get("high")
        even = bool(lead) and lead["verdict"] in ("about_even", "slightly_ahead")
        basis = lead.get("basis") if lead else None
    decision, side = _decide(z, bound, lead_side, even, final, stopped)
    return {"look": n_total, "z": z, "bound": bound, "low": low, "high": high, "decision": decision,
            "side": side, "basis": basis}


def ahead_next(games, p, *, max_games=CAP):
    """(more games, the next look) of a "who's ahead" run whose result has these games: the
    games up to the first entry of HP_LOOKS that is > the games played and ≤ max_games, or
    (0, None) when there's no look left (a result with 3,200 games or more). So a result that
    already has 1,000 games looks at 1,600 and 3,200. Strictly greater, so a run calling it after
    each look moves on; a run starting from a result that has exactly an HP_LOOKS count (400,
    800, ...) and wants that look calls look() first."""
    n = len(games)
    for nxt in HP_LOOKS:
        if nxt > n and (max_games is None or nxt <= max_games):
            return nxt - n, nxt
    return 0, None


# ============================================================ anytime-valid range (section 7.6)

def _anytime(wins, n):
    """(value, low, high) of section 7.6's confidence sequence for wins of n; None without games."""
    return live_ranges.anytime_counts(wins, n, rho=AV_RHO, alpha=AV_ALPHA)


def anytime_range(games, p):
    """(value, low, high): p's raw share of wins with the normal-mixture confidence sequence of
    section 7.6 (AV_RHO, AV_ALPHA), valid at every n at once; None without games. Each game's
    starter is a fair coin flip, so the raw share estimates the balanced rate. Half-widths are
    about 8.2, 5.5, 3.8 and 2.7 points at 400, 800, 1,600 and 3,200 games."""
    return anytime_counts(sum(1 for g in games if g.get("w") == p), len(games))


def anytime_counts(wins, games):
    """anytime_range from counts: non-wins stay in games, including draws and errors.

    Progress reports already have these counts, so no game list needs to be kept
    or reconstructed merely to show the live range. None before the first game.
    """
    return _anytime(wins, games)


# ============================================================ paired differences (section 7.4)

def _role(w, side):
    """Who won, from side's point of view: True (side), False (the other) or None (no winner)."""
    return None if w is None else w == side


def paired_games(base_games, paired_games_, base_side, variant_side):
    """The games of a base result and a paired result matched by g (section 7.4):
    {"pairs": [{"g", "y_base": 1 or 0, "y_variant": 1 or 0, "variant_first": bool, "same": bool}],
    "common": games in both arms, "starter_mismatch": common games with different starters (left
    out of pairs)}. base_side is the base deck's side in the base result, variant_side the
    variant's in the paired result; "same" is whether winner, starter, rounds, turns and result
    are equal in both arms. A common game whose starter isn't known in either arm counts as a
    mismatch. Pairs are in g order."""
    base = {g["g"]: g for g in base_games if g.get("g") is not None}
    variant = {g["g"]: g for g in paired_games_ if g.get("g") is not None}
    common = sorted(set(base) & set(variant))
    pairs, mismatch = [], 0
    for num in common:
        b, v = base[num], variant[num]
        if b.get("first") is None or v.get("first") is None \
                or (b["first"] == base_side) != (v["first"] == variant_side):
            mismatch += 1
            continue
        same = (_role(b.get("w"), base_side) == _role(v.get("w"), variant_side)
                and b.get("rounds") == v.get("rounds") and b.get("turns") == v.get("turns")
                and b.get("r") == v.get("r"))
        pairs.append({"g": num, "y_base": 1 if b.get("w") == base_side else 0,
                      "y_variant": 1 if v.get("w") == variant_side else 0,
                      "variant_first": v["first"] == variant_side, "same": same})
    return {"pairs": pairs, "common": len(common), "starter_mismatch": mismatch}


def _agresti_min(play, draw):
    """(center, var): Agresti-Min's adjusted difference of section 7.4 combined over the two
    strata, play and draw each (b, c, n); var is the stratum-combined variance (Var'_play +
    Var'_draw)/4. None unless both strata have pairs."""
    if not play[2] or not draw[2]:
        return None
    parts = []
    for b, c, n in (play, draw):
        b1, c1, n1 = b + 0.5, c + 0.5, n + 2
        parts.append(((b1 - c1) / n1, ((b1 + c1) - (b1 - c1) ** 2 / n1) / n1 ** 2))
    return (parts[0][0] + parts[1][0]) / 2, (parts[0][1] + parts[1][1]) / 4


def _pearson(xs, ys):
    """Pearson's correlation; None when either is constant or there are fewer than 2."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def paired_diff(base_games, paired_games_, base_side, variant_side):
    """One opponent's paired difference (variant minus base), section 7.4's Agresti-Min per
    stratum: {"delta", "low", "high", "z", "var", "n", "rho", "same", "unpaired": {"delta",
    "low", "high"}, "saved_share", "starter_mismatch": {"games", "of", "warn"}, "strata":
    {"play": {"b", "c", "n"}, "draw": {...}}, "center", "se"}.
    - delta is the plain estimate; low and high are the adjusted center ± Z95·se; z is
      center/se; var = se² is the stratum-combined variance paired_field sums. None without
      paired games in both strata.
    - The strata are whether the variant's side started (the same as the base's side, for the
      paired games). b counts the games the variant won and the base didn't, c the reverse.
    - rho: Pearson's correlation of the two arms' wins; None when either arm is constant.
    - same: the share of paired games equal in both arms (paired_games' "same"); None without.
    - unpaired: MOVER on views.balanced of each arm's paired games (section 7.4); None without
      both strata.
    - saved_share: 1 − (paired width / unpaired width)², about rho; None when rho is.
    - starter_mismatch: games in both arms with different starters (left out), of the common
      games; "warn" when more than STARTER_MISMATCH_WARN of them."""
    matched = paired_games(base_games, paired_games_, base_side, variant_side)
    pairs = matched["pairs"]
    strata, arms = {}, {}
    for name, first in (("play", True), ("draw", False)):
        part = [q for q in pairs if q["variant_first"] == first]
        strata[name] = {"b": sum(1 for q in part if q["y_variant"] and not q["y_base"]),
                        "c": sum(1 for q in part if q["y_base"] and not q["y_variant"]), "n": len(part)}
        arms[name] = (sum(q["y_variant"] for q in part), sum(q["y_base"] for q in part))
    mismatch = matched["starter_mismatch"]
    out = {"delta": None, "low": None, "high": None, "z": None, "var": None, "center": None, "se": None,
           "n": len(pairs), "rho": _pearson([q["y_variant"] for q in pairs], [q["y_base"] for q in pairs]),
           "same": sum(q["same"] for q in pairs) / len(pairs) if pairs else None,
           "unpaired": None, "saved_share": None,
           "starter_mismatch": {"games": mismatch, "of": matched["common"],
                                "warn": mismatch > STARTER_MISMATCH_WARN * matched["common"]},
           "strata": strata}
    play, draw = strata["play"], strata["draw"]
    combined = _agresti_min((play["b"], play["c"], play["n"]), (draw["b"], draw["c"], draw["n"]))
    if combined is None:
        return out
    center, var = combined
    se = math.sqrt(var)
    out.update(delta=((play["b"] - play["c"]) / play["n"] + (draw["b"] - draw["c"]) / draw["n"]) / 2,
               low=center - Z95 * se, high=center + Z95 * se, z=center / se, var=var, center=center, se=se)
    v_rate = views.balanced(arms["play"][0], play["n"], arms["draw"][0], draw["n"])
    b_rate = views.balanced(arms["play"][1], play["n"], arms["draw"][1], draw["n"])
    (v_v, l_v, u_v), (v_b, l_b, u_b) = v_rate, b_rate
    d = v_v - v_b
    unpaired = {"delta": d, "low": d - math.hypot(v_v - l_v, u_b - v_b),
                "high": d + math.hypot(u_v - v_v, v_b - l_b)}
    out["unpaired"] = unpaired
    width = unpaired["high"] - unpaired["low"]
    if out["rho"] is not None and width > 0:
        out["saved_share"] = 1 - ((out["high"] - out["low"]) / width) ** 2
    return out


def _center_var(diff):
    """(center, var) of a paired_diff() or paired_field() answer: its own when it has them, else
    worked out from its strata, else from z and var; None when it has no difference."""
    if not diff:
        return None
    if diff.get("center") is not None and diff.get("var") is not None:
        return diff["center"], diff["var"]
    strata = diff.get("strata")
    if strata and "play" in strata and "draw" in strata:
        play, draw = strata["play"], strata["draw"]
        combined = _agresti_min((play["b"], play["c"], play["n"]), (draw["b"], draw["c"], draw["n"]))
        if combined is not None:
            return combined
    if diff.get("z") is not None and diff.get("var"):
        return diff["z"] * math.sqrt(diff["var"]), diff["var"]
    if diff.get("delta") is not None and diff.get("se"):
        return diff["delta"], diff["se"] ** 2
    return None


def paired_field(diffs):
    """The field's paired difference over opponents (section 7.4): diffs are paired_diff()
    answers, one per opponent still in the test. {"delta": the mean of the opponents' adjusted
    centers Δ'_j, "low", "high" (delta ± Z95·se), "z", "se": sqrt(Σ var_j)/k, "k", "center",
    "var"}; None when no opponent has a delta. Opponents without one (no paired games in both
    strata yet) are left out of k."""
    parts = [cv for cv in (_center_var(d) for d in diffs) if cv is not None]
    if not parts:
        return None
    k = len(parts)
    delta = sum(c for c, _ in parts) / k
    se = math.sqrt(sum(v for _, v in parts)) / k
    return {"delta": delta, "low": delta - Z95 * se, "high": delta + Z95 * se, "z": delta / se, "se": se,
            "k": k, "center": delta, "var": se * se}


def paired_verdict(low, high, margin):
    """The verdict of a range of the difference (section 7.4): one of PAIRED_VERDICTS.
    "better" when low > 0, "worse" when high < 0, "little_difference" when the range lies within
    ±margin, "slightly_better" or "slightly_worse" when both hold, "not_settled" otherwise (and
    without a range)."""
    if low is None or high is None:
        return "not_settled"
    within = low >= -margin - _EPS and high <= margin + _EPS
    if low > 0:
        return "slightly_better" if within else "better"
    if high < 0:
        return "slightly_worse" if within else "worse"
    return "little_difference" if within else "not_settled"


def paired_look(diff, games_per_opponent, *, looks=PAIRED_LOOKS, max_games=None, margin=VARIANT_EQUIV_ONE,
                stopped=False, interim=False):
    """One look of an adaptive variant test (section 7.4): diff is paired_diff()'s or
    paired_field()'s answer at games_per_opponent. {"games_per_opponent", "delta", "low",
    "high", "z", "bound", "interim", "stopped", "decision"}:
    - bound: HP_FINAL at the last look of looks that max_games reaches (max_games None: looks'
      last), HP_INTERIM otherwise, and HP_INTERIM when stopped or interim is set (a look made
      before "Play more" extended the test); "interim" says whether the bound was HP_INTERIM;
    - decision: "better" or "worse" (the "slightly_" form when the range also lies within
      ±margin) when |z| ≥ bound; else "little_difference" when the range lies within ±margin;
      else "continue", or "not_settled" at the last look and for a stopped look. Without a z
      the look continues or isn't settled;
    - low and high: the range judged: the diff's 95 % range at a planned look, center ±
      HP_INTERIM·se at a stopped look (as section 7.3's stopped look)."""
    final = not stopped and not interim and _is_final(
        games_per_opponent, looks[-1] if max_games is None else max_games, looks)
    bound = HP_FINAL if final else HP_INTERIM
    cv = _center_var(diff)
    delta = diff.get("delta") if diff else None
    low = diff.get("low") if diff else None
    high = diff.get("high") if diff else None
    z = None
    if cv is not None and cv[1] > 0:
        center, se = cv[0], math.sqrt(cv[1])
        z = center / se
        if stopped:
            low, high = center - HP_INTERIM * se, center + HP_INTERIM * se
    elif diff and diff.get("z") is not None:
        z = diff["z"]
    if z is None:
        decision = "not_settled" if final or stopped else "continue"
    else:
        within = low is not None and high is not None and low >= -margin - _EPS and high <= margin + _EPS
        if abs(z) >= bound:
            decision = ("slightly_" if within else "") + ("better" if z > 0 else "worse")
        elif within:
            decision = "little_difference"
        else:
            decision = "not_settled" if final or stopped else "continue"
    return {"games_per_opponent": games_per_opponent, "delta": delta, "low": low, "high": high, "z": z,
            "bound": bound, "interim": bound == HP_INTERIM, "stopped": stopped, "decision": decision}


# ============================================================ the field (section 7.5)

def field_row(games, p):
    """One opponent's numbers for the field view (section 7.5): {"n": games, "value", "low",
    "high" (views.balanced's headline rate and range, None without both strata), "pi", "se"
    (decided_share's π̂ and SE, None without decided games in both strata), "d": the decided
    games (an int)}."""
    (n1, w1, o1), (n2, w2, o2) = _strata(games, p)
    both = views.balanced(w1, n1, w2, n2)
    pi, se, _ = _decided((w1, w2), (o1, o2))
    value, low, high = both if both else (None, None, None)
    return {"n": len(games), "value": value, "low": low, "high": high, "pi": pi, "se": se,
            "d": w1 + o1 + w2 + o2}


def field_average(rows, of=None):
    """The equal-weight field average over rows (field_row() answers; those without a value are
    left out): {"value", "low", "high" (MOVER over the equal-weight sum), "counted": m, "of": of
    or len(rows), "partial": m < of, "se_wald": sqrt(Σ se_j²)/m (the harness's; None when a
    counted row has no se)}; None when no row counts."""
    counted = [r for r in rows if r.get("value") is not None]
    if not counted:
        return None
    m = len(counted)
    of = len(rows) if of is None else of
    value = sum(r["value"] for r in counted) / m
    low = value - math.sqrt(sum((r["value"] - r["low"]) ** 2 for r in counted)) / m
    high = value + math.sqrt(sum((r["high"] - r["value"]) ** 2 for r in counted)) / m
    ses = [r.get("se") for r in counted]
    se_wald = None if any(s is None for s in ses) else math.sqrt(sum(s * s for s in ses)) / m
    return {"value": value, "low": low, "high": high, "counted": m, "of": of, "partial": m < of,
            "se_wald": se_wald}


# ------------------------------------------------------------ Bradley-Terry

def _sorted_ids(ids):
    try:
        return sorted(ids)
    except TypeError:
        return sorted(ids, key=repr)


def _cells(data):
    """data's cells with decided games, in a fixed order: [(i, j, i_started, wins, decided)]."""
    cells = [(i, j, bool(st), w, n) for (i, j, st), (w, n) in data.items() if n]
    cells.sort(key=lambda c: (repr(c[0]), repr(c[1]), c[2]))
    return cells


def _component(cells, player):
    """The players connected to player through cells."""
    links = {}
    for i, j, _, _, _ in cells:
        links.setdefault(i, set()).add(j)
        links.setdefault(j, set()).add(i)
    seen, todo = {player}, [player]
    while todo:
        for other in links.get(todo.pop(), ()):
            if other not in seen:
                seen.add(other)
                todo.append(other)
    return seen


def bt_component(data, player):
    """The players connected to player through data's pairings (a set; {player} alone when it
    has no games). data is bt_fit()'s; a pairing with no decided game links nobody."""
    return _component(_cells(data), player)


def _sigmoid(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def _log1pexp(x):
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


def _objective(cells, idx, theta, prior_sd):
    """The penalised log-likelihood LL(β, h) − Σ β²/(2·prior_sd²)."""
    k = len(idx)
    total = 0.0
    for i, j, st, w, n in cells:
        eta = theta[idx[i]] - theta[idx[j]] + (theta[k] if st else -theta[k])
        total += w * eta - n * _log1pexp(eta)
    return total - sum(b * b for b in theta[:k]) / (2 * prior_sd ** 2)


def _gradient_information(cells, idx, theta, prior_sd):
    """(gradient, penalised information) of the objective at theta (β in idx's order, then h)."""
    k = len(idx)
    grad = [0.0] * (k + 1)
    info = [[0.0] * (k + 1) for _ in range(k + 1)]
    for i, j, st, w, n in cells:
        a, b, s = idx[i], idx[j], 1.0 if st else -1.0
        pr = _sigmoid(theta[a] - theta[b] + s * theta[k])
        resid, weight = w - n * pr, n * pr * (1 - pr)
        x = {}
        for u, xu in ((a, 1.0), (b, -1.0), (k, s)):
            x[u] = x.get(u, 0.0) + xu
        for u, xu in x.items():
            if not xu:
                continue
            grad[u] += xu * resid
            for v, xv in x.items():
                if xv:
                    info[u][v] += xu * xv * weight
    for u in range(k):
        grad[u] -= theta[u] / prior_sd ** 2
        info[u][u] += 1 / prior_sd ** 2
    return grad, info


def _inverse(a):
    """The inverse of the square matrix a (Gauss-Jordan with partial pivoting); None when it's
    singular."""
    n = len(a)
    m = [list(row) + [1.0 if c == r else 0.0 for c in range(n)] for r, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-300:
            return None
        m[c], m[piv] = m[piv], m[c]
        f = m[c][c]
        m[c] = [x / f for x in m[c]]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c]
                row_c = m[c]
                m[r] = [x - f * y for x, y in zip(m[r], row_c)]
    inv = [row[n:] for row in m]
    return [[(inv[r][c] + inv[c][r]) / 2 for c in range(n)] for r in range(n)]


def _newton(cells, players, prior_sd, start=None, max_iter=BT_ITERATIONS):
    """(theta, information, iterations, converged): penalised Newton-Raphson from start (zeros by
    default), halving a step that would lower the objective, stopping once the largest full
    Newton step is under BT_TOLERANCE. When halving can't find a step that keeps the objective
    (below t = 1e-8), the fit stays where it is and stops, converged only if that full step was
    already under BT_TOLERANCE."""
    idx = {q: k for k, q in enumerate(players)}
    theta = list(start) if start else [0.0] * (len(players) + 1)
    obj = _objective(cells, idx, theta, prior_sd)
    converged, iterations = False, 0
    for iterations in range(1, max_iter + 1):
        grad, info = _gradient_information(cells, idx, theta, prior_sd)
        inv = _inverse(info)
        if inv is None:
            break
        step = [sum(r * g for r, g in zip(row, grad)) for row in inv]
        size = max(abs(d) for d in step)
        t, accepted = 1.0, False
        while t >= 1e-8:
            new = [x + t * d for x, d in zip(theta, step)]
            new_obj = _objective(cells, idx, new, prior_sd)
            if new_obj >= obj - 1e-9 * (1 + abs(obj)):
                accepted = True
                break
            t /= 2
        if not accepted:
            converged = size < BT_TOLERANCE
            break
        theta, obj = new, new_obj
        if size < BT_TOLERANCE:
            converged = True
            break
    _, info = _gradient_information(cells, idx, theta, prior_sd)
    return theta, info, iterations, converged


def bt_fit(data, *, prior_sd=BT_PRIOR_SD):
    """The Bradley-Terry fit with a starter term (section 7.5) of data: {(i, j, i_started):
    [i's wins, decided games]} over one connected component. logit P(i beats j | i starts) =
    β_i − β_j + h, fitted by penalised Newton-Raphson (prior N(0, prior_sd²) on each β, h
    unpenalised, no β fixed, so Σβ = 0 at the maximum in each component, whatever the players'
    order). {"players": [ids, sorted], "beta": {id: β}, "h", "cov": the inverse penalised
    information as a list of rows in "players" order then h, "phi": max(1, X²/df), "x2":
    Pearson's X² over the cells with decided games, "df": cells − (players − 1) − 1 (at least 1),
    "iterations", "converged", "prior_sd"}; None when no cell has a decided game."""
    cells = _cells(data)
    if not cells:
        return None
    players = _sorted_ids({c[0] for c in cells} | {c[1] for c in cells})
    theta, info, iterations, converged = _newton(cells, players, prior_sd)
    cov = _inverse(info)
    k = len(players)
    idx = {q: n for n, q in enumerate(players)}
    x2 = 0.0
    for i, j, st, w, n in cells:
        pr = _sigmoid(theta[idx[i]] - theta[idx[j]] + (theta[k] if st else -theta[k]))
        var = n * pr * (1 - pr)
        if var > 0:
            x2 += (w - n * pr) ** 2 / var
    df = max(1, len(cells) - (k - 1) - 1)
    return {"players": players, "beta": {q: theta[n] for n, q in enumerate(players)}, "h": theta[k],
            "cov": cov, "phi": max(1.0, x2 / df), "x2": x2, "df": df, "iterations": iterations,
            "converged": converged, "prior_sd": prior_sd}


def _predict(beta_i, beta_j, h):
    return (_sigmoid(beta_i - beta_j + h) + _sigmoid(beta_i - beta_j - h)) / 2


def bt_predict(fit, i, j):
    """i's predicted win chance against j, balanced for the starter: ½[σ(β_i − β_j + h) +
    σ(β_i − β_j − h)]."""
    return _predict(fit["beta"][i], fit["beta"][j], fit["h"])


def _cholesky(a):
    """The lower Cholesky factor of a symmetric positive (semi-)definite matrix; a pivot that
    rounding makes ≤ 0 is taken as 0."""
    n = len(a)
    low = [[0.0] * n for _ in range(n)]
    for r in range(n):
        for c in range(r + 1):
            s = a[r][c] - sum(low[r][k] * low[c][k] for k in range(c))
            if r == c:
                low[r][c] = math.sqrt(s) if s > 0 else 0.0
            else:
                low[r][c] = s / low[c][c] if low[c][c] else 0.0
    return low


def _rank(values, me):
    """1 + how many of values are greater than values[me]."""
    mine = values[me]
    return 1 + sum(1 for r, x in enumerate(values) if r != me and x > mine)


def bt_rating(fit, player, field_players):
    """player's rating against an average deck of field_players (those in the fit), section
    7.5: {"value": R, "low", "high" (c ± Z95·sqrt(φ)·SE through the same map), "c", "se",
    "rank", "rank_low", "rank_high" (the 2.5 % and 97.5 % points of player's rank over BT_DRAWS
    draws of β from N(β̂, φΣ), random.Random(1)), "of": the lists ranked (the field lists, and
    player when it isn't one), "h_points": 100·(σ(h) − ½)}. c = β_player − the field lists'
    mean β, R = ½[σ(c + h) + σ(c − h)]. None when player isn't in the fit or no field list is."""
    if not fit or player not in fit["beta"]:
        return None
    players = fit["players"]
    idx = {q: n for n, q in enumerate(players)}
    wanted = set(field_players)
    field = [q for q in players if q in wanted]
    if not field:
        return None
    beta, h, cov, phi = fit["beta"], fit["h"], fit["cov"], fit["phi"]
    m = len(field)
    c = beta[player] - sum(beta[q] for q in field) / m
    a = [0.0] * (len(players) + 1)
    a[idx[player]] += 1.0
    for q in field:
        a[idx[q]] -= 1.0 / m
    nz = [u for u, x in enumerate(a) if x]
    se = math.sqrt(max(0.0, sum(a[u] * cov[u][v] * a[v] for u in nz for v in nz)))
    half = Z95 * math.sqrt(phi) * se
    ranked = field if player in wanted else [q for q in players if q in wanted or q == player]
    me = ranked.index(player)
    sub = [[phi * cov[idx[u]][idx[v]] for v in ranked] for u in ranked]
    chol = _cholesky(sub)
    mean = [beta[u] for u in ranked]
    rng = random.Random(1)
    n = len(ranked)
    ranks = []
    for _ in range(BT_DRAWS):
        zs = [rng.gauss(0.0, 1.0) for _ in range(n)]
        draw = [mean[r] + sum(chol[r][k] * zs[k] for k in range(r + 1)) for r in range(n)]
        ranks.append(_rank(draw, me))
    ranks.sort()
    return {"value": _predict(c, 0.0, h), "low": _predict(c - half, 0.0, h), "high": _predict(c + half, 0.0, h),
            "c": c, "se": se, "rank": _rank(mean, me),
            "rank_low": ranks[math.ceil(0.025 * BT_DRAWS) - 1], "rank_high": ranks[math.ceil(0.975 * BT_DRAWS) - 1],
            "of": n, "h_points": 100 * (_sigmoid(h) - 0.5)}


def residual_flags(data, fit, player, observed):
    """Leave-one-pairing-out residual flags of player's pairings (section 7.5). observed is
    {opponent: (π̂_j, SE_obs_j)} (decided_share's, from player's side). For each opponent j
    that player has decided games with and observed has numbers for: refit without the pairing
    (warm-started from fit), r_j = π̂_j − the refit's bt_predict(player, j), Var_j = SE_obs_j² +
    gᵀ Σ_(−ij) g (g the prediction's gradient in β_player, β_j and h; no φ), z_j and a
    two-sided p_j. The flags are the Benjamini-Hochberg discoveries at RESIDUAL_FDR among these
    p-values that also have |r_j| ≥ RESIDUAL_POINTS: "strong" (r_j > 0: player does better
    against j than its rating says) or "weak". [{"opponent", "r", "z", "p", "flag": "strong" |
    "weak" | None}] in opponent order, with no entry for a pairing that is a bridge (removing it
    splits player's component)."""
    if not fit or player not in fit["beta"]:
        return []
    cells = _cells(data)
    players = fit["players"]
    idx = {q: n for n, q in enumerate(players)}
    k = len(players)
    start = [fit["beta"][q] for q in players] + [fit["h"]]
    prior_sd = fit.get("prior_sd", BT_PRIOR_SD)
    whole = _component(cells, player)
    opponents = _sorted_ids({c[1] if c[0] == player else c[0] for c in cells
                             if player in (c[0], c[1]) and c[0] != c[1]})
    out = []
    for j in opponents:
        seen = observed.get(j)
        if j not in idx or not seen or seen[0] is None or seen[1] is None:
            continue
        rest = [c for c in cells if {c[0], c[1]} != {player, j}]
        if _component(rest, player) != whole:
            continue
        theta, info, _, _ = _newton(rest, players, prior_sd, start=start)
        cov = _inverse(info)
        if cov is None:
            continue
        a, b = idx[player], idx[j]
        diff, h = theta[a] - theta[b], theta[k]
        s1, s2 = _sigmoid(diff + h), _sigmoid(diff - h)
        q1, q2 = s1 * (1 - s1), s2 * (1 - s2)
        grad = {a: (q1 + q2) / 2, b: -(q1 + q2) / 2, k: (q1 - q2) / 2}
        var = seen[1] ** 2 + sum(gu * cov[u][v] * gv for u, gu in grad.items() for v, gv in grad.items())
        r = seen[0] - (s1 + s2) / 2
        z = r / math.sqrt(var) if var > 0 else 0.0
        out.append({"opponent": j, "r": r, "z": z, "p": math.erfc(abs(z) / math.sqrt(2)), "flag": None})
    found = _discoveries([row["p"] for row in out], RESIDUAL_FDR) if out else set()
    for n, row in enumerate(out):
        if n in found and abs(row["r"]) >= RESIDUAL_POINTS:
            row["flag"] = "strong" if row["r"] > 0 else "weak"
    return out


def apt_pick(rows, k):
    """The k opponents to play next (section 7.5): rows are {"id", "n", "pi" (π̂ or None),
    "inflight": bool, "meaningful": bool}; among the eligible ones (n < FIELD_CAP, not in
    flight, meaningful), the k smallest sqrt(n)·(|π̂ − 0.5| + APT_EPS), ties to fewer games then
    the id. A row with no π̂ yet counts as even (|π̂ − 0.5| = 0). A list of ids."""
    eligible = [r for r in rows if r["n"] < FIELD_CAP and not r.get("inflight") and r.get("meaningful", True)]

    def score(r):           # rounded, so scores equal but for float noise tie
        gap = 0.0 if r.get("pi") is None else abs(r["pi"] - 0.5)
        return round(math.sqrt(r["n"]) * (gap + APT_EPS), 12), r["n"], repr(r["id"])
    return [r["id"] for r in sorted(eligible, key=score)[:max(0, k)]]


def _average_ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and xs[order[end + 1]] == xs[order[start]]:
            end += 1
        for pos in range(start, end + 1):
            ranks[order[pos]] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(xs, ys):
    """Spearman's rank correlation of two equal-length sequences, average ranks for ties; None
    when either is constant or shorter than 2 (or their lengths differ)."""
    xs, ys = list(xs), list(ys)
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return _pearson(_average_ranks(xs), _average_ranks(ys))
