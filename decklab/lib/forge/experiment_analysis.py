"""Statistics, adoption recommendations and reports for saved experiments.

These calculations consume result dictionaries; spec validation, result loading and
execution remain in experiment.py.
"""
import math
import re
import statistics
from statistics import NormalDist

from . import seqstats

# Section 12.4's thresholds.
NONINFERIOR = -0.03                 # the low end of "win when in hand early" an adopted set must keep
CAST_RISE = 0.20                    # a "cast at least once" rise that makes up for a missed cast_target
OWN_LOST_RISE = 0.25                # own permanents lost per cast may rise by this much
PILOT_SLOWDOWN = 1.5                # a pilot may make games this much slower (median Forge ms)
HYBRID = "aisim-hybrid-1"
HYBRID_SLOWDOWN = 3.0               # ... the hybrid AI this much
TIMEOUT_RATIO = 3.0                 # MG9: the rate ratio's lower bound that flags
TIMEOUT_MIN = 3                     # MG9: arm games with an AI timeout a pair needs to be flagged
SETTLE_CAP = 3200                   # "more games" never asks for more than this a pair

_Z = NormalDist()

def _pair_words(pair):
    return f"{pair[0]} v {pair[1]}"


# ============================================================ the measures' statistics

def _ratio(units):
    """A ratio estimator sum(y)/sum(x) over clusters [(y, x)], with its cluster SE:
    sqrt(n/(n-1) * sum((y - R x)^2)) / sum(x). None when sum(x) is 0."""
    units = [(y, x) for y, x in units if x]
    total_x = sum(x for _, x in units)
    if not total_x:
        return None
    r = sum(y for y, _ in units) / total_x
    n = len(units)
    se = math.sqrt(n / (n - 1) * sum((y - r * x) ** 2 for y, x in units)) / total_x if n > 1 else None
    return {"value": r, "se": se, "n": n, "y": sum(y for y, _ in units), "x": total_x}


def _difference(arm, control):
    """Arm minus control of two _ratio answers, with SE sqrt(se_a^2 + se_c^2) and a 95 % range."""
    if not arm or not control:
        return None
    d = arm["value"] - control["value"]
    if arm["se"] is None or control["se"] is None:
        return {"delta": d, "se": None, "low": None, "high": None}
    se = math.hypot(arm["se"], control["se"])
    return {"delta": d, "se": se, "low": d - seqstats.Z95 * se, "high": d + seqstats.Z95 * se}


def _bound(k):
    """The z below which a pair is clearly negative: Phi^-1(1 - 0.025/k) (Bonferroni over k pairs)."""
    return _Z.inv_cdf(1 - 0.025 / max(1, k))


def _binom_sf(x, n, p):
    """P(X >= x) for X ~ Bin(n, p)."""
    if x <= 0:
        return 1.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    total = 0.0
    for k in range(x, n + 1):
        total += math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                          + k * math.log(p) + (n - k) * math.log1p(-p))
    return min(1.0, total)


def _cp_lower(x, n, level):
    """The one-sided Clopper-Pearson lower bound of a binomial share at level (x of n)."""
    if x <= 0:
        return 0.0
    alpha = 1 - level
    low, high = 0.0, x / n
    for _ in range(80):
        mid = (low + high) / 2
        if _binom_sf(x, n, mid) < alpha:
            low = mid
        else:
            high = mid
    return low


def rate_ratio(x1, n1, x2, n2, level):
    """MG9's lower bound of the rate ratio (arm x2 of n2 games against control x1 of n1): given
    t = x1 + x2, X2 ~ Bin(t, theta); r_L = theta_L / (1 - theta_L) * n1 / n2 with theta_L the
    one-sided Clopper-Pearson bound at level. None without events or games."""
    t = x1 + x2
    if not t or not n1 or not n2:
        return None
    theta = _cp_lower(x2, t, level)
    if theta >= 1:
        return math.inf
    return theta / (1 - theta) * n1 / n2


def _timeouts(games):
    n = len(games)
    ai = sum(1 for g in games if g.get("ai_to"))
    clock = sum(1 for g in games if g.get("r") == "timeout")
    return {"games": n, "ai_timeout_games": ai, "clock_stops": clock,
            "ai_per_1000": 1000 * ai / n if n else None, "clock_per_1000": 1000 * clock / n if n else None}


def _speed(result, games):
    ms = [g["ms"] for g in games if isinstance(g.get("ms"), (int, float))]
    runs = (result or {}).get("runs") or []
    played = sum(r.get("played") or 0 for r in runs)
    wall = sum(r.get("wall_s") or 0 for r in runs)
    return {"median_ms": statistics.median(ms) if ms else None,
            "games_per_min": 60 * played / wall if wall else None, "games": len(ms)}


def _syn(game, y, side):
    """A game dict for seqstats.paired_diff whose "win" is a per-game yes/no (y) of side."""
    return {"g": game["g"], "w": side if y else None, "first": game["first"], "r": "win" if y else "draw",
            "rounds": None, "turns": None}


def _paired(control_games, arm_games, control_side, arm_side):
    """seqstats.paired_diff of the arm (variant) against the control (base), or None when it
    can't be told (no games)."""
    if not control_games or not arm_games:
        return None
    return seqstats.paired_diff(control_games, arm_games, control_side, arm_side)


def _field(diffs):
    diffs = [d for d in diffs if d and d.get("delta") is not None]
    return seqstats.paired_field(diffs) if diffs else None


SCRIPT_ERROR = re.compile(r"script|pars(?:e|ing)|cardsfolder|\.txt\b|AbilityFactory|CardFactory|CardRules",
                          re.IGNORECASE)


def _blocking_error(text, cards=()):
    """Whether a new error line is one section 12.4 refuses an override set for: an "unsupported
    card" line, or a script error (a line about a card script or its parsing, or naming one of
    the arm's cards). Other exceptions (a rare AI one, say) are reported but don't decide."""
    if text.startswith("unsupported card: ") or SCRIPT_ERROR.search(text):
        return True
    low = text.lower()
    return any(card.lower() in low for card in cards)


def _strata(games, side):
    play = [g for g in games if g["first"] == side]
    draw = [g for g in games if g["first"] == 1 - side]
    return (sum(g["w"] == side for g in play), len(play), sum(g["w"] == side for g in draw), len(draw))


# The card log's numbers (cardlog.ROW_FIELDS): their places in a row.
DRAWN, COPIES, USED, ROUND_SUM, EARLY = 0, 2, 3, 5, 8


def _card_measures(units, target):
    """One card's measures pooled over every pair element that holds it (units)."""
    arm_cast, control_cast, arm_turn, control_turn, arm_lost, control_lost = [], [], [], [], [], []
    rises, early, drawn = [], [], []
    logged = 0
    for unit in units:
        cast_c, cast_a, early_c, early_a, drawn_c, drawn_a = [], [], [], [], [], []
        for game in unit["games"]:
            logged += 1
            a, c = game["arm"], game["control"]
            arm_cast.append((a[USED], a[COPIES]))
            control_cast.append((c[USED], c[COPIES]))
            arm_turn.append((a[ROUND_SUM], a[USED]))
            control_turn.append((c[ROUND_SUM], c[USED]))
            arm_lost.append((game["arm_lost"][1], game["arm_lost"][0]))
            control_lost.append((game["control_lost"][1], game["control_lost"][0]))
            if a[COPIES] and c[COPIES]:
                cast_c.append(_syn(game["control_game"], c[USED] > 0, unit["control_side"]))
                cast_a.append(_syn(game["arm_game"], a[USED] > 0, unit["arm_side"]))
            if a[EARLY] and c[EARLY]:
                early_c.append(game["control_game"])
                early_a.append(game["arm_game"])
            if a[DRAWN] and c[DRAWN]:
                drawn_c.append(game["control_game"])
                drawn_a.append(game["arm_game"])
        rises.append(_paired(cast_c, cast_a, unit["control_side"], unit["arm_side"]))
        early.append(_paired(early_c, early_a, unit["control_side"], unit["arm_side"]))
        drawn.append(_paired(drawn_c, drawn_a, unit["control_side"], unit["arm_side"]))
    cast = {"arm": _ratio(arm_cast), "control": _ratio(control_cast)}
    if cast["arm"] and cast["arm"]["se"] is not None:
        se = cast["arm"]["se"]
        cast["arm"]["low"] = max(0.0, cast["arm"]["value"] - seqstats.Z95 * se)
        cast["arm"]["high"] = min(1.0, cast["arm"]["value"] + seqstats.Z95 * se)
    cast["rise"] = _field(rises)
    turn = {"arm": _ratio(arm_turn), "control": _ratio(control_turn)}
    turn["difference"] = _difference(turn["arm"], turn["control"])
    lost = {"arm": _ratio(arm_lost), "control": _ratio(control_lost)}
    lost["difference"] = _difference(lost["arm"], lost["control"])
    return {"logged_games": logged, "elements": len(units), "cast_target": target.get("cast_target"),
            "turn_target": target.get("turn_target"), "cast": cast, "turn": turn,
            "win_early": _field(early), "win_drawn": _field(drawn), "own_lost": lost}


def _arm_measures(how, pairs, cards, targets):
    kind = "override" if how["overrides"] is not None and not how["pilots"] and how["seeds"] is None \
        and how["config"] is None else "pilot" if how["pilots"] and how["overrides"] is None \
        and how["seeds"] is None and how["config"] is None else "other"
    k = len(pairs)
    bound = _bound(k)
    for row in pairs:
        diff = row["matchup"]
        if diff is not None:
            diff["clearly_negative"] = diff.get("z") is not None and diff["z"] < -bound
    pooled_matchup = _field([r["matchup"] for r in pairs])
    a_games = [r["speed"]["arm"]["median_ms"] for r in pairs if r["speed"] and r["speed"]["arm"]["median_ms"]]
    c_games = [r["speed"]["control"]["median_ms"] for r in pairs if r["speed"] and r["speed"]["control"]["median_ms"]]
    speed = {"arm_median_ms": statistics.median(a_games) if a_games else None,
             "control_median_ms": statistics.median(c_games) if c_games else None}
    speed["slowdown"] = (speed["arm_median_ms"] / speed["control_median_ms"]
                         if speed["arm_median_ms"] and speed["control_median_ms"] else None)
    timeouts = _timeout_test(pairs)
    errors = sorted({e for r in pairs if r["errors"] for e in r["errors"]["new_blocking"]})
    others = {}         # the other new exceptions, with the arm games they turned up in
    for r in pairs:
        if r["errors"]:
            for e in r["errors"]["new"]:
                if e not in errors:
                    others[e] = others.get(e, 0) + r["errors"]["new_games"].get(e, 0)
    card_rows = {}
    for card in cards:
        units = [u for r in pairs for u in r["cards"].get(card, [])]
        if units:
            card_rows[card] = _card_measures(units, targets.get(card) or {})
    for r in pairs:         # the per-game numbers stay out of experiment.json: the logs hold them
        r["cards"] = {card: len(units) for card, units in r["cards"].items()}
    found = {"kind": kind, "how": how, "pairs": pairs, "k": k, "bound": bound,
             "pooled": {"matchup": pooled_matchup, "speed": speed, "timeouts": timeouts, "new_errors": errors,
                        "new_exceptions": dict(sorted(others.items()))},
             "cards": card_rows}
    found.update(recommend(found))
    return found


def _timeout_test(pairs):
    """MG9's rate-ratio test of the arm's AI-timeout games against the control's: per pair at
    1 - 0.05/m (flagged when r_L > 3 and 3 or more arm games had one), and pooled at 0.95."""
    m = sum(1 for r in pairs if r["timeouts"])
    rows, x1s, n1s, x2s, n2s = [], 0, 0, 0, 0
    for r in pairs:
        if not r["timeouts"]:
            continue
        c, a = r["timeouts"]["control"], r["timeouts"]["arm"]
        x1, n1, x2, n2 = c["ai_timeout_games"], c["games"], a["ai_timeout_games"], a["games"]
        x1s, n1s, x2s, n2s = x1s + x1, n1s + n1, x2s + x2, n2s + n2
        r_low = rate_ratio(x1, n1, x2, n2, 1 - 0.05 / max(1, m))
        flag = r_low is not None and r_low > TIMEOUT_RATIO and x2 >= TIMEOUT_MIN
        r["timeouts"]["r_low"], r["timeouts"]["flag"] = r_low, flag
        rows.append(flag)
    pooled = rate_ratio(x1s, n1s, x2s, n2s, 0.95)
    return {"control": [x1s, n1s], "arm": [x2s, n2s], "r_low": pooled,
            "flag": any(rows) or (pooled is not None and pooled > TIMEOUT_RATIO)}


# ============================================================ recommendations (section 12.4)

def _settle(n, diff, margin):
    """Games a pair that would bring a range's low end to margin at today's estimate (None when
    the estimate is at or below it)."""
    if not diff or diff.get("delta") is None or diff.get("low") is None or not n:
        return None
    half = diff["delta"] - diff["low"]
    gap = diff["delta"] - margin
    if gap <= 0 or half <= 0:
        return None
    return min(SETTLE_CAP, int(math.ceil(n * (half / gap) ** 2 / 100.0)) * 100)


def recommend(found):
    """Section 12.4's recommendation of one arm's measures (_arm_measures' answer, "kind",
    "pairs", "pooled", "cards", "bound"): {"recommendation": "adopt", "dont_adopt",
    "more_games" or None (no rule for this kind of arm), "why": [sentences], "games_per_pair":
    the games a pair that would settle it, or None}."""
    if found["kind"] == "override":
        return _recommend_override(found)
    if found["kind"] == "pilot":
        return _recommend_pilot(found)
    return {"recommendation": None, "why": ["No adoption rule for this kind of arm: its numbers are evidence only."],
            "games_per_pair": None}


def _pairs_negative(found):
    out = []
    for r in found["pairs"]:
        if r["matchup"] and r["matchup"].get("clearly_negative"):
            out.append(f"{_pair_words(r['pair'])} is clearly worse for {r['perspective']} (z "
                       f"{r['matchup']['z']:.2f} below -{found['bound']:.2f}).")
    return out


def _exception_notes(pooled):
    others = pooled.get("new_exceptions") or {}
    if not others:
        return []
    return ["Note: new exceptions the control's logs don't have (not script errors, so they don't decide): "
            + "; ".join(f"{e} ({n} game{'s' if n != 1 else ''})" for e, n in list(others.items())[:5]) + "."]


def _common_checks(found, bad, unsure):
    pooled = found["pooled"]
    bad += _pairs_negative(found)
    m = pooled["matchup"]
    if m is None or m.get("high") is None:
        unsure.append("There's no paired matchup difference yet.")
    elif m["high"] < 0:
        bad.append(f"The pooled matchup difference is clearly negative ({_pts(m['delta'])}, high end "
                   f"{_pts(m['high'])}).")
    if pooled["new_errors"]:
        bad.append("New Forge script errors or unsupported cards: " + "; ".join(pooled["new_errors"][:5]) + ".")
    if pooled["timeouts"]["flag"]:
        bad.append("The AI-timeout rate-ratio test flags the arm.")


def _recommend_override(found):
    bad, unsure, settle = [], [], []
    n = max([r["games"]["paired"] for r in found["pairs"]] or [0])
    _common_checks(found, bad, unsure)
    if not found["cards"]:
        unsure.append("No named card was logged in both arms.")
    for card, row in found["cards"].items():
        cast, rise, target = row["cast"]["arm"], row["cast"]["rise"], row["cast_target"]
        reached = target is not None and cast is not None and cast["value"] >= target
        rose = rise is not None and rise.get("delta") is not None and rise["delta"] >= CAST_RISE
        if target is not None and not (reached or rose):        # a card without a target has no cast rule
            high_cast = cast.get("high") if cast else None
            high_rise = rise.get("high") if rise else None
            if high_cast is not None and high_cast < target and high_rise is not None and high_rise < CAST_RISE:
                bad.append(f"{card} isn't cast enough: {_pct(cast and cast['value'])} of drawn copies"
                           + (f" (target {_pct(target)})" if target is not None else "")
                           + f", a rise of {_pts(rise and rise['delta'])}.")
            else:
                unsure.append(f"{card}'s cast share or its rise isn't settled.")
        early = row["win_early"]
        if early is None or early.get("low") is None:
            unsure.append(f"{card}: no paired win rate when in hand early yet.")
        elif early["high"] < 0:
            bad.append(f"{card} wins less when in hand early ({_pts(early['delta'])}, high end {_pts(early['high'])}).")
        elif early["low"] < NONINFERIOR:
            unsure.append(f"{card}'s win rate when in hand early may be lower (low end {_pts(early['low'])}).")
            settle.append(_settle(n, early, NONINFERIOR))
        lost = row["own_lost"]["difference"]
        if lost is not None and lost["delta"] > OWN_LOST_RISE:     # not in section 12.4's "don't" list
            unsure.append(f"{card} loses more of its own permanents per cast (+{lost['delta']:.2f}, at most "
                          f"+{OWN_LOST_RISE:g}).")
    return _verdict(bad, unsure, settle, _exception_notes(found["pooled"]))


def _recommend_pilot(found):
    bad, unsure, settle = [], [], []
    mirrors = [r for r in found["pairs"] if r["mirror"]]
    if not mirrors:
        unsure.append("There's no mirror pair, so the mirror test can't be judged.")
    for r in mirrors:
        rate = r["mirror"]
        if rate["high"] < 0.5:
            bad.append(f"The mirror test loses: {_pct(rate['value'])} (high end {_pct(rate['high'])}).")
        elif rate["low"] <= 0.5:
            unsure.append(f"The mirror test isn't clear of 50 % ({_pct(rate['value'])}, low end {_pct(rate['low'])}).")
            settle.append(_settle(r["games"]["arm"], {"delta": rate["value"], "low": rate["low"]}, 0.5))
    bad += _pairs_negative({"pairs": [r for r in found["pairs"] if not r["mirror"]], "bound": found["bound"]})
    pooled = found["pooled"]
    notes = []          # reported, but not one of a pilot's three rules (section 12.4)
    if pooled["new_errors"]:
        notes.append("Note: new Forge script errors or unsupported cards: " + "; ".join(pooled["new_errors"][:5])
                     + ".")
    notes += _exception_notes(pooled)
    if pooled["timeouts"]["flag"]:
        notes.append("Note: the AI-timeout rate-ratio test flags the arm.")
    hybrid = any(HYBRID in (p.get("switches") or []) for p in found["how"]["pilots"].values())
    limit = HYBRID_SLOWDOWN if hybrid else PILOT_SLOWDOWN
    slowdown = pooled["speed"]["slowdown"]
    if slowdown is None:
        unsure.append("The speed can't be told yet.")
    elif slowdown > limit:
        bad.append(f"Games are {slowdown:.2f} times as slow (at most {limit:g} times).")
    return _verdict(bad, unsure, settle, notes)


def _verdict(bad, unsure, settle, notes=()):
    if bad:
        return {"recommendation": "dont_adopt", "why": bad + list(notes), "games_per_pair": None}
    if unsure:
        found = [s for s in settle if s]
        return {"recommendation": "more_games", "why": unsure + list(notes),
                "games_per_pair": max(found) if found else None}
    return {"recommendation": "adopt", "why": ["Every rule of section 12.4 holds."] + list(notes),
            "games_per_pair": None}


# ============================================================ report.md

WORDS = {"adopt": "adopt", "dont_adopt": "don't adopt", "more_games": "more games", None: "evidence only"}


def _pct(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def _pts(x):
    return "-" if x is None else f"{100 * x:+.1f} pts"


def _range(d):
    if not d or d.get("delta") is None:
        return "-"
    if d.get("low") is None:
        return _pts(d["delta"])
    return f"{_pts(d['delta'])} [{100 * d['low']:+.1f}, {100 * d['high']:+.1f}]"


def report(found):
    """report.md's text for measures()' answer: per arm its recommendation and why, its pairs
    and its cards."""
    out = [f"# Experiment {found['experiment']}", "",
           f"{found['games']} games a pair. Each arm is compared with its control on the same game numbers and "
           "seeds; ranges are 95 %. The owner decides what's adopted.", ""]
    if found.get("failed"):
        out += ["**Runs that failed:**", ""] + [f"- {f['arm']}, {_pair_words(f['pair'])}: {f['error']}"
                                                 for f in found["failed"]] + [""]
    out += ["| Arm | Kind | Pairs | Matchup (pooled) | Slowdown | AI timeouts arm / control | Recommendation |",
            "|---|---|---|---|---|---|---|"]
    for arm, row in found["arms"].items():
        pooled = row["pooled"]
        t = pooled["timeouts"]
        slow = pooled["speed"]["slowdown"]
        out.append(f"| {arm} | {row['kind']} | {row['k']} | {_range(pooled['matchup'])} | "
                   f"{'-' if slow is None else f'{slow:.2f}x'} | {t['arm'][0]}/{t['arm'][1]} v "
                   f"{t['control'][0]}/{t['control'][1]} | {WORDS[row['recommendation']]} |")
    for arm, row in found["arms"].items():
        out += ["", f"## {arm}: {WORDS[row['recommendation']]}", ""]
        out += [f"- {why}" for why in row["why"]]
        if row.get("games_per_pair"):
            out.append(f"- About {row['games_per_pair']:,} games a pair would settle it.")
        out += ["", "| Pair | For | Games (paired, logged) | Matchup | Mirror | Median ms arm / control |",
                "|---|---|---|---|---|---|"]
        for r in row["pairs"]:
            speed = r["speed"]
            ms = "-" if not speed else f"{_ms(speed['arm']['median_ms'])} / {_ms(speed['control']['median_ms'])}"
            mirror = _pct(r["mirror"]["value"]) if r["mirror"] else "-"
            out.append(f"| {_pair_words(r['pair'])} | {r['perspective']} | {r['games']['paired']}, "
                       f"{r['games']['logged']} | {_range(r['matchup'])} | {mirror} | {ms} |")
        if row["cards"]:
            out += ["", "| Card | Cast arm (control) | Target | Rise (cast at least once) | Turn diff | "
                        "Win in hand early | Win when drawn | Own lost per cast diff |",
                    "|---|---|---|---|---|---|---|---|"]
            for card, c in row["cards"].items():
                arm_cast, control_cast = c["cast"]["arm"], c["cast"]["control"]
                cast = f"{_pct(arm_cast and arm_cast['value'])} ({_pct(control_cast and control_cast['value'])})"
                out.append(f"| {card} | {cast} | {_pct(c['cast_target'])} | {_range(c['cast']['rise'])} | "
                           f"{_signed(c['turn']['difference'])} | {_range(c['win_early'])} | "
                           f"{_range(c['win_drawn'])} | {_signed(c['own_lost']['difference'])} |")
    if found.get("skipped"):
        out += ["", "Skipped (the arm changes nothing there): "
                + "; ".join(f"{s['arm']} on {_pair_words(s['pair'])}" for s in found["skipped"]) + "."]
    return "\n".join(out) + "\n"


def _ms(x):
    return "-" if x is None else f"{x:,.0f}"


def _signed(d):
    return "-" if not d or d.get("delta") is None else f"{d['delta']:+.2f}"
