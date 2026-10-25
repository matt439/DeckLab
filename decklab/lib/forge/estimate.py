"""Time estimates for Deck Lab's simulations (simulation wave 3, forge-trial/sim-wave3-contract.md
section 9.5): one server-side estimator for the matchup play box, field budgets and the variant
test sheet. Rates come from a pair's saved results when it has any, else from the speed class
of its lists, with <data>/forge/rates.json (written by the combined run's report) over wave 2's
measured defaults. Every number is a rough guide for the page ("about 2-6 minutes"), never a
promise: the combined run measures speed.

    RATES_FILE              rates.json in <data>/forge: a JSON object with any of DEFAULT_RATES'
                            keys (numbers over 0), at its top level or under "rates", and/or the
                            combined run report's "warm_games_per_min" ({"IG", "RV", "GF": games a
                            minute}, read through WORKLOAD_CLASSES; a named class wins over it);
                            other keys and bad values are ignored (the default stands), and a
                            file with no rate it reads is logged once
    DEFAULT_RATES           games a minute at 16 warm workers per speed class, and the warm
                            speed-up: wave 2's measured ones
    TAIL_ALLOWANCE          the high end's allowance for stage tails (20 %)
    rates()                 DEFAULT_RATES with rates.json's over them
    pair_rate(entry_a, entry_b, results_dir=None)
                            games a minute for this pair: from its saved v2 results (games over
                            the wall time of their pool runs), else its v1 results' median Forge
                            ms per game divided by the warm speed-up (at config forge_workers
                            workers), else the format's slow class ("board" for Constructed,
                            "commander" for Commander); None when the entries can't be read
    minutes(pairs_games, results_dir=None)
                            (low, high) minutes for [(entry_a, entry_b, games)]: the sum over
                            pairs at each pair's rate, and at the slower of its rate and its two
                            lists' rates (each list's median rate over its saved pairs, else the
                            slow class) with TAIL_ALLOWANCE; None for no pairs
    matchup(entry_a, entry_b, games, p=0, results_dir=None, choices=GAME_CHOICES)
                            the matchup page's "estimates" (section 9.3): {"fixed": {"200":
                            [low, high], ...}, "assess": [low, high], "ahead": [low, high]}
                            minutes for a result holding games (game dicts; side p entry_a's)

An entry is anything with "card_sha" and "kind" ("commander" or "constructed"): lists.entry()'s,
or the page's sides with the engine kind added.
"""
import json
import math
import statistics

from . import common, saved, seqstats
from .common import GAME_CHOICES

RATES_FILE = "rates.json"
DEFAULT_RATES = {"fast": 1400, "medium": 900, "board": 280, "commander": 200, "speed_up": 2.0}
RATE_WORKERS = 16           # the workers DEFAULT_RATES are measured at
TAIL_ALLOWANCE = 1.2
MIN_V1_GAMES = 20           # v1 games a pair needs before its median Forge time stands for it


def rates():
    """DEFAULT_RATES with <data>/forge/rates.json's numbers over them (logged when it can't be
    read; a missing file is the usual case before the combined run)."""
    out = dict(DEFAULT_RATES)
    path = common.DATA_DIR / RATES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return out
    except (OSError, ValueError) as e:
        common._log(f"Deck Lab's measured speeds ({path}) can't be read, so the usual ones are used: {e}")
        return out
    found = {}
    if isinstance(data, dict):
        found.update(_workload_rates(data.get("warm_games_per_min")))
        named = data["rates"] if isinstance(data.get("rates"), dict) else data
        for name in DEFAULT_RATES:
            value = _positive(named.get(name))
            if value is not None:
                found[name] = value
    if not found:
        said = str(path)
        if said not in _rates_said:         # once per file: the page asks every second or so
            _rates_said.add(said)
            common._log(f"Deck Lab's measured speeds ({path}) have none of the rates it reads, so the usual "
                        f"ones are used.")
    out.update(found)
    return out


_rates_said = set()         # rates.json files already logged as having no rate rates() reads

# The combined run's report (forge-trial/overnight_report.py) measures warm games a minute per
# workload (COMBINED-RUN.md's rate classes): IG (Izzet v Gruul) is a "fast" pair, RV (Rabbits v
# Vampires) a "board" one (the slow Constructed class the estimates fall back on), GF "commander".
WORKLOAD_CLASSES = {"IG": "fast", "RV": "board", "GF": "commander"}


def _positive(value):
    """value as a rate (a finite number over 0), else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return float(value)
    return None


def _workload_rates(measured):
    """{class: games a minute} from the report's "warm_games_per_min" ({workload: rate}), each
    class the slowest of its workloads' (WORKLOAD_CLASSES); {} for anything else."""
    out = {}
    if not isinstance(measured, dict):
        return out
    for workload, name in WORKLOAD_CLASSES.items():
        value = _positive(measured.get(workload))
        if value is not None:
            out[name] = min(out.get(name, value), value)
    return out


def _workers():
    """config.json's forge_workers (RATE_WORKERS when it can't be read)."""
    try:
        value = int(common._settings().get("forge_workers"))
    except Exception:
        return RATE_WORKERS
    return value if value >= 1 else RATE_WORKERS


def _slow_class(entry, table):
    """The format's slow class rate for an entry, at today's workers."""
    name = "commander" if entry.get("kind") == "commander" else "board"
    return table[name] * _workers() / RATE_WORKERS


def _pair(a, b):
    return tuple(sorted([a, b]))


_cache = {}         # results folder -> (the saved results' keys and times, the rates and workers, the answer)


def _saved_rates(results_dir, table):
    """{(sha, sha) sorted: games a minute} for every pair with saved games: v2 pool runs'
    games over their wall time, else v1's median Forge ms per game over the warm speed-up.
    Worked out again only when a saved result, the rates or the workers change (the matchup
    page asks every second or so while a run plays)."""
    stored = saved._stored(results_dir)
    stamp = (tuple(sorted((r.get("key"), r.get("updated")) for r in stored)), tuple(sorted(table.items())),
             _workers())
    folder = str(common._results_dir(results_dir))
    cached = _cache.get(folder)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    found = _work_out_rates(stored, table)
    _cache.clear()
    _cache[folder] = (stamp, found)
    return found


def _work_out_rates(stored, table):
    v2, v1 = {}, {}
    for result in stored:
        sides = result.get("sides") or []
        if len(sides) != 2:
            continue
        pair = _pair(sides[0].get("card_sha"), sides[1].get("card_sha"))
        for run in result.get("runs") or []:
            played, wall = run.get("played") or 0, run.get("wall_s") or 0
            if run.get("pool") and played > 0 and wall > 0:
                tally = v2.setdefault(pair, [0, 0.0])
                tally[0] += played
                tally[1] += wall
        if not result.get("run_version") or result.get("run_version") == 1:
            ms = [g.get("ms") for b in result.get("batches") or [] for g in b.get("games") or []
                  if isinstance(g.get("ms"), (int, float)) and g["ms"] > 0]
            if ms:
                v1.setdefault(pair, []).extend(ms)
    out = {}
    workers = _workers()
    for pair, ms in v1.items():
        if len(ms) >= MIN_V1_GAMES:
            out[pair] = workers * 60000 / (statistics.median(ms) / table["speed_up"])
    for pair, (played, wall) in v2.items():
        out[pair] = played / wall * 60
    return out


def _rate(entry_a, entry_b, known, table):
    found = known.get(_pair(entry_a["card_sha"], entry_b["card_sha"]))
    return found if found else min(_slow_class(entry_a, table), _slow_class(entry_b, table))


def _list_rate(entry, known, table):
    """A list's own rate: the median over its saved pairs, else the format's slow class."""
    mine = [rate for pair, rate in known.items() if entry["card_sha"] in pair]
    return statistics.median(mine) if mine else _slow_class(entry, table)


def pair_rate(entry_a, entry_b, results_dir=None):
    """Games a minute for this pair (section 9.5), or None when the entries can't be read."""
    try:
        table = rates()
        return _rate(entry_a, entry_b, _saved_rates(results_dir, table), table)
    except (KeyError, TypeError, AttributeError):
        return None


def _minutes(pairs_games, known, table):
    low = high = 0.0
    for a, b, games in pairs_games:
        if not games or games <= 0:
            continue
        rate = _rate(a, b, known, table)
        slow = min(rate, _list_rate(a, known, table), _list_rate(b, known, table))
        low += games / rate
        high += games / slow * TAIL_ALLOWANCE
    return round(low, 2), round(max(high, low), 2)


def minutes(pairs_games, results_dir=None):
    """(low, high) minutes to play [(entry_a, entry_b, games)] (section 9.5), or None for no
    pairs or entries that can't be read."""
    pairs_games = list(pairs_games or [])
    if not pairs_games:
        return None
    try:
        table = rates()
        return _minutes(pairs_games, _saved_rates(results_dir, table), table)
    except (KeyError, TypeError, AttributeError):
        return None


def _new_run_plan_done(planned):
    """adaptive._plan_done (a new run's plan isn't played yet); adaptive comes after this part."""
    from . import adaptive
    return adaptive._plan_done(planned)


def _ceil25(x):
    return int(math.ceil(x / 25) * 25)


def matchup(entry_a, entry_b, games, p=0, results_dir=None, choices=GAME_CHOICES):
    """The matchup page's "estimates" (section 9.3) for a result holding games (side p
    entry_a's; [] for none): each fixed count's minutes; "assess" from its 400-game pilot (or
    seqstats.assess_estimate's planned total, if more) to 30 % past that plan; "ahead" from the
    next look to the last (3,200 games). None when the entries can't be read."""
    games = list(games or [])
    n = len(games)
    try:
        table = rates()
        known = _saved_rates(results_dir, table)

        def span(low_games, high_games):
            low = _minutes([(entry_a, entry_b, max(0, low_games))], known, table)[0]
            high = _minutes([(entry_a, entry_b, max(0, high_games))], known, table)[1]
            return [low, max(low, high)]

        fixed = {str(count): list(_minutes([(entry_a, entry_b, count)], known, table)) for count in choices}
        if n < seqstats.ASSESS_PILOT:
            try:
                planned = seqstats.assess_estimate(games, p)
            except Exception:
                planned = 1100          # r5's usual plan (the page's sub-line: 700-1,100)
            planned = max(seqstats.ASSESS_PILOT, int(planned))
            assess = span(min(planned, seqstats.CAP) - n, min(seqstats.CAP, _ceil25(planned * 1.3)) - n)
        else:
            try:
                more = seqstats.assess_next(games, p, **_new_run_plan_done(False))[0]
            except Exception:
                more = seqstats.ASSESS_PILOT
            assess = span(more, min(seqstats.CAP - n, _ceil25(more * 1.3)))
        later = [look for look in seqstats.HP_LOOKS if look > n]
        ahead = span(later[0] - n, seqstats.CAP - n) if later else [0.0, 0.0]
        return {"fixed": fixed, "assess": assess, "ahead": ahead}
    except (KeyError, TypeError, AttributeError):
        return None
