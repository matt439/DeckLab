"""Pure, heuristic time estimates for an experiment plan's remaining work.

``estimate_plan(plan, samples=None, rates=None, workers=None)`` reads only its
arguments. ``samples`` maps each planned result key to that result's already-read
snapshot; callers choose the correct control/arm folder. No directories, settings,
engine, deployment or saved records are read here. The existing plan remains the
authority for missing games, cached controls, skipped arms and extra seed controls.

V2 pool timings are weighted aggregate throughput, never per-worker rates. A
known worker mismatch rejects that observation. Unknown worker context is explicit.
An arm hash does not prove its recipe: its old speed is an arm proxy. Arbitrary
config arms have no supported prediction, so unfinished ones make the whole time
unknown rather than presenting the other rows' time as the complete experiment.
"""
import math
import statistics

from . import estimate as pair_estimate


BASE_ASSUMPTIONS = (
    "The range is a heuristic with a 20% tail allowance, not a confidence interval.",
    "No allowance is added for queue wait, cold startup, deployment or changes in shared PC load.",
    "Remaining counts follow the cache plan; arm-folder/spec compatibility and run readiness are not verified.",
)
UNKNOWN_WORKERS = "Planning workers are unknown; v1 and format fallbacks assume 16 workers."
POOL_UNKNOWN = "The saved pool timing has unknown worker context; it is not confirmed to match the next run."
POOL_PLANNING_UNKNOWN = "Planning workers are unknown; saved pool throughput is an unscaled observation."
POOL_MISMATCH = "Saved pool workers differ from planning workers; that timing is not reused."
POOL_AGGREGATE = "Pool speed is observed aggregate throughput and is not divided or scaled by workers."
ARM_PROXY = "A saved arm key does not prove the current recipe; its prior speed is only a proxy."
CONTROL_PROXY = "The control's speed is a proxy for the changed arm, whose speed may differ."
FORMAT_FALLBACK = "The format's slow-class rate is a fallback, scaled linearly from its 16-worker reference."
V1_RATE = "Legacy per-game timings use the warm speed-up and a linear planning-worker assumption."
CONFIG_UNKNOWN = "Arbitrary configuration arms have no supported timing assumption or verified recipe."
UNAVAILABLE = "A finite estimate could not be calculated for all remaining work."


def _positive(value):
    """Reuse the field estimator's finite-positive rule, including oversized integer inputs."""
    try:
        return pair_estimate._positive(value)
    except (OverflowError, ValueError, TypeError):
        return None


def _worker_count(value):
    return value if type(value) is int and _positive(value) is not None else None


def _pair(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(
            isinstance(item, str) and item for item in value):
        return None
    return tuple(sorted(value))


def _table(given):
    table = dict(pair_estimate.DEFAULT_RATES)
    if isinstance(given, dict):
        for name in table:
            value = _positive(given.get(name))
            if value is not None:
                table[name] = value
    return table


def _sample(row, samples, workers, table):
    """A matching saved observation, never another arm with identical card hashes."""
    if not isinstance(samples, dict) or not isinstance(row.get("key"), str):
        return None
    result = samples.get(row["key"])
    if not isinstance(result, dict) or result.get("key") != row["key"]:
        return None
    sides = result.get("sides")
    wanted = _pair(row.get("card_shas"))
    if wanted is None or not isinstance(sides, list) or len(sides) != 2 or not all(
            isinstance(side, dict) for side in sides) or _pair([side.get("card_sha") for side in sides]) != wanted:
        return None
    runs = result.get("runs")
    valid = []
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict) or not isinstance(run.get("pool"), str) or not run["pool"].strip() or \
                type(run.get("played")) is not int:
            continue
        played, wall = _positive(run["played"]), _positive(run.get("wall_s"))
        if played is not None and wall is not None:
            valid.append((played, wall, _worker_count(run.get("workers"))))
    if valid:
        recorded = sorted({count for _, _, count in valid if count is not None})
        unknown = any(count is None for _, _, count in valid)
        context = "unknown" if unknown else "mixed" if len(recorded) > 1 else "known"
        metadata = {"timing": "v2", "sample_workers": recorded or None, "worker_context": context}
        if workers is not None and any(count != workers for count in recorded):
            return dict(metadata, rate=None, mismatch=True)
        try:
            rate = _positive(math.fsum(item[0] for item in valid) / math.fsum(item[1] for item in valid) * 60)
        except (OverflowError, ZeroDivisionError):
            rate = None
        if rate is not None:
            return dict(metadata, rate=rate, mismatch=False)
    version = result.get("run_version")
    if version is not None and (type(version) is not int or version != 1):
        return None
    milliseconds = []
    batches = result.get("batches")
    for batch in batches if isinstance(batches, list) else []:
        games = batch.get("games") if isinstance(batch, dict) else None
        for game in games if isinstance(games, list) else []:
            value = _positive(game.get("ms")) if isinstance(game, dict) else None
            if value is not None:
                milliseconds.append(value)
    if len(milliseconds) < pair_estimate.MIN_V1_GAMES:
        return None
    try:
        rate = _positive((workers or pair_estimate.RATE_WORKERS) * 60000 /
                         (statistics.median(milliseconds) / table["speed_up"]))
    except (OverflowError, ZeroDivisionError):
        rate = None
    return ({"rate": rate, "timing": "v1", "sample_workers": None, "worker_context": "per_game",
             "mismatch": False} if rate is not None else None)


def _span(games, rate):
    try:
        low = games / rate
        high = low * pair_estimate.TAIL_ALLOWANCE
    except (OverflowError, ZeroDivisionError):
        return None
    return (low, high) if math.isfinite(low) and math.isfinite(high) and low > 0 and high > 0 else None


def _fallback(row, workers, table):
    kind = row.get("kind")
    name = "commander" if kind == "commander" else "board" if kind == "constructed" else None
    if name is None:
        return None
    try:
        return _positive(table[name] * ((workers or pair_estimate.RATE_WORKERS) / pair_estimate.RATE_WORKERS))
    except OverflowError:
        return None


def _row(row, arm=False):
    missing = 0 if arm and row.get("skipped") else row.get("missing")
    if type(missing) is not int or missing < 0:
        missing = None
    return {"key": row.get("key"), **({"arm": row.get("arm")} if arm else {}),
            "remaining_games": missing, "minutes": [0.0, 0.0] if missing == 0 else None,
            "basis": "none" if missing == 0 else "unavailable", "games_per_min": None,
            "timing": None, "sample_key": None, "sample_workers": None, "worker_context": None,
            "rejected_sample": None,
            "assumptions": [], "_span": (0.0, 0.0) if missing == 0 else None}


def _estimate_row(row, detail, controls, samples, workers, table, arm):
    if not detail["remaining_games"]:
        return
    notes = detail["assumptions"]
    if arm and row.get("config"):
        detail["basis"] = "unsupported_config"
        notes.append(CONFIG_UNKNOWN)
        return
    chosen = _sample(row, samples, workers, table)
    sample_key = row.get("key") if chosen else None
    basis = "arm_proxy" if arm else "measured"
    mismatch = bool(chosen and chosen["mismatch"])
    if chosen is None and arm:
        for control in controls:
            if _pair(control.get("pair")) == _pair(row.get("pair")) and _pair(control.get("card_shas")) == _pair(
                    row.get("card_shas")):
                chosen = _sample(control, samples, workers, table)
                if chosen is not None:
                    sample_key, basis = control.get("key"), "control_proxy"
                    mismatch = chosen["mismatch"]
                    break
    if chosen and not mismatch:
        rate = chosen["rate"]
        detail.update(timing=chosen["timing"], sample_key=sample_key, sample_workers=chosen["sample_workers"],
                      worker_context=chosen["worker_context"])
        if basis == "arm_proxy":
            notes.append(ARM_PROXY)
        elif basis == "control_proxy":
            notes.append(CONTROL_PROXY)
        if chosen["timing"] == "v2":
            notes.append(POOL_AGGREGATE)
            if chosen["worker_context"] == "unknown":
                notes.append(POOL_UNKNOWN)
            if workers is None:
                notes.append(POOL_PLANNING_UNKNOWN)
        else:
            notes.append(V1_RATE)
            if workers is None:
                notes.append(UNKNOWN_WORKERS)
    else:
        rate, basis = _fallback(row, workers, table), "fallback"
        if mismatch:
            notes.append(POOL_MISMATCH)
            detail["rejected_sample"] = {"key": sample_key, "timing": chosen["timing"],
                                         "sample_workers": chosen["sample_workers"],
                                         "worker_context": chosen["worker_context"]}
        if rate is not None:
            notes.append(FORMAT_FALLBACK)
            if workers is None:
                notes.append(UNKNOWN_WORKERS)
    detail["games_per_min"] = rate
    span = _span(detail["remaining_games"], rate) if rate is not None else None
    if span is None:
        detail["basis"] = "unavailable"
        notes.append(UNAVAILABLE)
        return
    detail.update(basis=basis, minutes=list(span), _span=span)


def estimate_plan(plan, *, samples=None, rates=None, workers=None):
    """JSON-friendly estimate from explicit snapshots; no input is mutated or resolved.

    Return ``minutes=None, complete=False`` if any unfinished row is unsupported;
    row estimates never masquerade as a complete total. Numeric spans stay
    unrounded; exact zero is reserved for no remaining work. ``workers=None`` means
    unknown context. Only v1 reconstruction and class fallbacks assume 16 then;
    aggregate v2 timings are never silently assigned or divided by that count.
    """
    controls = plan.get("controls") or []
    arms = plan.get("arms") or []
    out_controls = [_row(row) for row in controls]
    out_arms = [_row(row, True) for row in arms]
    all_rows = out_controls + out_arms
    known_counts = all(row["remaining_games"] is not None for row in all_rows)
    remaining = sum(row["remaining_games"] for row in all_rows) if known_counts else None
    planned_workers = _worker_count(workers)
    assumptions = list(BASE_ASSUMPTIONS)
    # In particular, do not touch timing/rate mappings when cached/skipped work is all that's left.
    if remaining != 0:
        table = _table(rates)
        for row, detail in zip(controls, out_controls):
            _estimate_row(row, detail, controls, samples, planned_workers, table, False)
        for row, detail in zip(arms, out_arms):
            _estimate_row(row, detail, controls, samples, planned_workers, table, True)
    complete = known_counts and all(row["_span"] is not None for row in all_rows)
    minutes = None
    if complete:
        try:
            total = [math.fsum(row["_span"][side] for row in all_rows) for side in (0, 1)]
            if all(math.isfinite(value) for value in total) and (remaining == 0 or all(value > 0 for value in total)):
                minutes = total
        except OverflowError:
            pass
        complete = minutes is not None
    bases = {row["basis"] for row in all_rows if row["remaining_games"]}
    basis = ("unavailable" if not complete else "none" if not bases else
             next(iter(bases)) if len(bases) == 1 else "mixed")
    for row in all_rows:
        row.pop("_span")
        for note in row["assumptions"]:
            if note not in assumptions:
                assumptions.append(note)
    if not complete and UNAVAILABLE not in assumptions:
        assumptions.append(UNAVAILABLE)
    return {"remaining_games": remaining, "minutes": minutes, "complete": complete, "basis": basis,
            "workers": planned_workers,
            "assumed_workers": pair_estimate.RATE_WORKERS if UNKNOWN_WORKERS in assumptions else None,
            "assumptions": assumptions, "controls": out_controls, "arms": out_arms}
