"""Combined-run acceptance gates and their numerical helpers.

The report facade owns the gate registry, staged-result validation (MG8), and output collection.
These checks only inspect saved evidence; they do not run Forge or modify the overnight outputs.
"""
import json
import math
import statistics
import time
from pathlib import Path

PASS, FAIL, NOT_CHECKED, NOT_BUILT = "pass", "fail", "not checked", "not built tonight"
P1_GATES = ("MG13", "MG16")
OPTIONAL_GATES = ("M6",)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _gate(status, detail="", numbers=None):
    return {"status": status, "detail": detail, "numbers": numbers or {}}


def _item(state, item_id):
    return (state.get("items") or {}).get(item_id) or {}


def _needs(state, plan, *item_ids):
    """None when every item ran (done/cut/noisy), else a gate for why not: not built tonight when the
    plan skipped it for a missing package or leg, else not checked."""
    for item_id in item_ids:
        st = _item(state, item_id)
        planned = next((i for i in plan.get("items", []) if i["id"] == item_id), {})
        if planned.get("not_built") or st.get("not_built"):
            return _gate(NOT_BUILT, f"{item_id}: {planned.get('why') or st.get('note')}")
        if st.get("status") not in ("done", "cut", "noisy"):
            return _gate(NOT_CHECKED, f"{item_id} {st.get('status') or 'didn\'t run'}"
                         + (f" ({st.get('note')})" if st.get("note") else ""))
    return None


def _games_of(result):
    return [g for b in (result or {}).get("batches", []) for g in b.get("games", [])]


def _results(folder):
    out = []
    for path in sorted(Path(folder).glob("*.json")):
        data = _read(path)
        if isinstance(data, dict) and "batches" in data and "sides" in data:
            out.append(data)
    return out


def _wilson(k, n, z=1.96):
    if not n:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def balanced(games, side=0):
    """Side's balanced win rate (the mean of its rates on the play and on the draw) with a MOVER range
    and a standard error: {"value", "low", "high", "se"}, or None without games in both strata."""
    play = [g for g in games if g.get("first") == side]
    draw = [g for g in games if g.get("first") == 1 - side]
    if not play or not draw:
        return None
    pw, dw = sum(g.get("w") == side for g in play), sum(g.get("w") == side for g in draw)
    p1, p2 = pw / len(play), dw / len(draw)
    l1, h1 = _wilson(pw, len(play))
    l2, h2 = _wilson(dw, len(draw))
    value = (p1 + p2) / 2
    se = 0.5 * math.sqrt(p1 * (1 - p1) / len(play) + p2 * (1 - p2) / len(draw))
    return {"value": value, "low": value - 0.5 * math.hypot(p1 - l1, p2 - l2),
            "high": value + 0.5 * math.hypot(h1 - p1, h2 - p2), "se": se}


def _norm_ppf(p):
    """The standard normal quantile (Acklam's approximation; ample for gate thresholds)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - 0.02425:
        return -_norm_ppf(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def _beta_ppf_lower(x, n, level):
    """The one-sided Clopper-Pearson lower bound for x of n at level (bisection on the binomial tail)."""
    if x <= 0:
        return 0.0

    def tail(p):        # P(X >= x | n, p)
        return 1 - sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(x))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if tail(mid) < 1 - level:
            lo = mid
        else:
            hi = mid
    return lo


def rate_ratio_low(x1, n1, x2, n2, level):
    """MG9's r_L: given t = x1 + x2, X2 ~ Bin(t, θ); θ_L the one-sided Clopper-Pearson lower bound at
    level; r_L = θ_L / (1 - θ_L) · n1 / n2."""
    t = x1 + x2
    if t == 0 or n1 == 0 or n2 == 0:
        return 0.0
    theta = _beta_ppf_lower(x2, t, level)
    return theta / (1 - theta) * n1 / n2 if theta < 1 else math.inf


# ============================================================ the gates

def gate_mg1(out, state, plan):
    st = _item(state, "A1")
    found = _read(Path(out) / "A" / "a1" / "preflight.json")
    if st.get("status") != "done" or not found:
        return _gate(NOT_CHECKED, "A1 didn't run")
    failed = [c["name"] for c in found["checks"] if c.get("gate") and c["ok"] is False]
    unknown = [c["name"] for c in found["checks"] if c.get("gate") and c["ok"] is None]
    if failed:
        return _gate(FAIL, "; ".join(failed))
    if unknown:
        return _gate(NOT_BUILT, "not checked: " + "; ".join(unknown))
    return _gate(PASS)


def gate_mg2(out, state, plan):
    missing = _needs(state, plan, "C1")
    if missing:
        return missing
    found = _read(Path(out) / "C" / "c1" / "result.json") or {}
    kinds = {fmt: v.get("kind") for fmt, v in (found.get("formats") or {}).items()}
    if not kinds:
        return _gate(NOT_CHECKED, "C1 wrote no result")
    if any(k == "failed" for k in kinds.values()):
        return _gate(FAIL, f"{kinds}")
    unsure = sum(1 for k in kinds.values() if k == "unsure")
    return _gate(PASS if unsure <= 1 else FAIL, f"{kinds}")


def gate_mg3(out, state, plan):
    missing = _needs(state, plan, "C2")
    if missing:
        return missing
    found = _read(Path(out) / "C" / "c2" / "result.json") or {}
    chunks = found.get("chunks") or []
    if not chunks:
        return _gate(NOT_CHECKED, "C2 wrote no result")
    failed = [c["first"] for c in chunks if c["kind"] == "failed"]
    unsure = found.get("unsure_chunks", 0)
    return _gate(FAIL if failed or unsure > 2 else PASS, f"failed chunks {failed}, unsure {unsure}")


def gate_mg4(out, state, plan):
    st = _item(state, "C3")
    missing = _needs(state, plan, "C3")
    if missing and not (st.get("status") == "failed" and st.get("codes")):     # serve-check exits 1 when unsure
        return missing
    text = ""
    try:
        text = (Path(out) / "C" / "c3" / "out.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    if (st.get("codes") or [1])[-1] == 0:
        return _gate(PASS)
    if "would play other games" in text:
        return _gate(FAIL, "serve-check failed")
    if "Traceback" in text or "Checking a warm worker" not in text or (st.get("codes") or [0])[-1] not in (0, 1):
        return _gate(NOT_CHECKED, "serve-check couldn't run")
    return _gate(PASS, "serve-check said unsure")


def gate_mg5(out, state, plan):
    missing = _needs(state, plan, "C4")
    if missing:
        return missing
    found = _read(Path(out) / "C" / "c4" / "result.json") or {}
    if "pass" not in found:
        return _gate(NOT_CHECKED, "C4 wrote no result")
    return _gate(PASS if found["pass"] else FAIL, json.dumps(found.get("variants")))


def _leg_rows(out, folder):
    found = _read(Path(out) / "B" / folder / "result.json") or {}
    return found.get("rows") or []


def _outcome_same(a, b):
    """Two B-leg outcomes ([g, w, first, rounds, r, ai_to, turns]) of one game agree: winner,
    starter, rounds, result and turns (the AI-timeout count is timing, not the game)."""
    return a[1:5] == b[1:5] and a[6:7] == b[6:7]


def _outcome_excused(o):
    """A game with a clock stop or an AI timeout, whose difference the runbook excuses."""
    return o[4] == "timeout" or (len(o) > 5 and bool(o[5]))


def gate_mg6(out, state, plan):
    """Constructed games >= 99.5 % identical across the B legs, and every difference in a game with
    a clock stop or AI timeout. The replay rule isn't built in the harness, so a difference with
    neither leaves the gate not checked (with the count) rather than passed."""
    missing = _needs(state, plan, "B2")
    if missing:
        return missing
    rows = _leg_rows(out, "b2")
    reference = {r["workload"]: r for r in rows if r["round"] == 1}
    compared = same = excused = 0
    for folder in ("b2", "b3", "b4-none", "b4-ccd", "b5-k24", "b5-k20", "b5-k32", "b7-r14a", "b7-r04", "b9-core",
                   "b9-none"):
        for row in _leg_rows(out, folder):
            ref = reference.get(row["workload"])
            if ref is None or row is ref or row["workload"] == "GF":
                continue
            a = {o[0]: o for o in ref["outcomes"]}
            for o in row["outcomes"]:
                if o[0] in a:
                    compared += 1
                    if _outcome_same(o, a[o[0]]):
                        same += 1
                    elif _outcome_excused(o) or _outcome_excused(a[o[0]]):
                        excused += 1
    if not compared:
        return _gate(NOT_CHECKED, "no B legs to compare")
    unexplained = compared - same - excused
    detail = (f"{same} of {compared} identical, {excused} different with a clock stop or AI timeout, "
              f"{unexplained} different with neither")
    numbers = {"identical_share": round(same / compared, 4), "compared": compared, "excused": excused,
               "unexplained": unexplained}
    if same / compared < 0.995:
        return _gate(FAIL, detail, numbers)
    if unexplained:
        return _gate(NOT_CHECKED, detail + " (the replay rule that would call them unsure or failed isn't built "
                     "in the harness)", numbers)
    return _gate(PASS, detail, numbers)


def _sessions_d(state):
    return {n + 1: s for n, s in enumerate(state.get("sessions") or [])}


def _excused_games(out):
    """{(key, g)} of the saved games with an AI timeout or a clock stop, over the folders soak
    probes sample (staging, the filler): a fresh-against-warm difference in one is excused (as
    MG6 excuses them: the timeout depends on the load, not the engine)."""
    found = set()
    for folder in (Path(out) / "staging" / "results", Path(out) / "D" / "filler" / "results"):
        for result in _results(folder):
            for game in _games_of(result):
                if game.get("ai_to") or game.get("r") == "timeout":
                    found.add((result.get("key"), game.get("g")))
    return found


def gate_mg7(out, state, plan):
    missing = _needs(state, plan, "D1")
    if missing:
        return missing
    excused = None
    probes = state.get("probes") or []
    by_session = {}
    for p in probes:
        found = _read(Path(out) / "probes" / p["file"])
        if found:
            by_session.setdefault(p.get("session", 1), []).append((p, found))
    best = None
    for session, rows in by_session.items():
        games = [g for _, f in rows for g in f.get("games", [])]
        if any(g.get("verdict") in ("failed", "unsure") for g in games):
            if excused is None:
                excused = _excused_games(out)
            games = [dict(g, verdict="excused") if g.get("verdict") in ("failed", "unsure")
                     and (g.get("key"), g.get("g")) in excused else g for g in games]
        con = [g for g in games if g["format"] != "Commander" and g["verdict"] in ("same", "unsure", "failed")]
        com = [g for g in games if g["format"] == "Commander" and g["verdict"] in ("same", "differs")]
        stamps = sorted(p["started"] for p, _ in rows)
        span_h = 0.0
        if len(stamps) >= 2:
            import datetime
            t = [datetime.datetime.fromisoformat(s) for s in stamps]
            span_h = (t[-1] - t[0]).total_seconds() / 3600
        found = {"session": session, "constructed": len(con), "probes": len(rows), "span_h": round(span_h, 2),
                 "failed": sum(g["verdict"] == "failed" for g in con),
                 "unsure": sum(g["verdict"] == "unsure" for g in con), "commander": len(com),
                 "excused": sum(g["verdict"] == "excused" for g in games)}
        a = [1 if g["verdict"] == "differs" else 0 for g in com]
        b_ = [1 if g.get("fresh2_differs") else 0 for g in com]
        b = sum(1 for x, y in zip(a, b_) if x == 1 and y == 0) + 0.5
        c = sum(1 for x, y in zip(a, b_) if x == 0 and y == 1) + 0.5
        n2 = len(com) + 2
        est = (b - c) / n2
        var = ((b + c) - (b - c) ** 2 / n2) / n2 ** 2
        found["commander_low"] = round(est - 1.96 * math.sqrt(max(var, 0)), 4)
        found["commander_est"] = round(est, 4)
        if best is None or found["constructed"] > best["constructed"]:
            best = found
    soak_min = plan.get("soak_min_s", 10800)
    need_h = 2.5 if soak_min >= 3 * 3600 else soak_min / 3600 * 0.8
    need_games, need_probes, need_com = (300, 10, 150) if soak_min >= 3 * 3600 else (3, 1, 1)
    if best is None:
        return _gate(NOT_CHECKED, "no soak probe wrote a result")
    if best["failed"]:
        return _gate(FAIL, f"{best['failed']} probed games failed", best)
    if best["constructed"] and best["unsure"] / best["constructed"] > 0.02:
        return _gate(FAIL, "more than 2 % unsure", best)
    if best["commander"] >= need_com and best["commander_low"] > 0 and best["commander_est"] > 0.05:
        return _gate(FAIL, "Commander: warm differs from fresh more than fresh from fresh", best)
    if best["constructed"] < need_games or best["probes"] < need_probes or best["span_h"] < need_h \
            or best["commander"] < need_com:
        return _gate(NOT_CHECKED, "too few probes or games in one session", best)
    return _gate(PASS, "", best)


MG8_FAILED_ALL = 0.005         # failed chunks' games, of the replayed games (played + failed)
MG8_FAILED_ONE = 0.02          # the same in any one matchup


def _failed_games(result):
    """The games in a v2 result's failed chunks (each record {first, games, error})."""
    return sum(f.get("games", 25) if isinstance(f, dict) else 25 for f in result.get("failed") or [])


def _read_json_out(path):
    """The last JSON line of an item's out.txt (a command's --json answer)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def _pairs(out):
    """[(v1 result, v2 result)] in staging, matched by their two card_shas and format."""
    staged = _results(Path(out) / "staging" / "results")
    v1, v2 = {}, {}
    for r in staged:
        if r.get("kind"):
            continue
        key = (tuple(sorted(s["card_sha"] for s in r["sides"])), r.get("format"))
        (v2 if "seeds" in r else v1)[key] = r
    return [(v1[k], v2[k]) for k in v2 if k in v1], v2


def gate_mg9(out, state, plan):
    missing = _needs(state, plan, "D1")
    if missing:
        return missing
    pairs, v2 = _pairs(out)
    games = [g for r in v2.values() for g in _games_of(r)]
    if not games:
        return _gate(NOT_CHECKED, "no replayed games")
    n = len(games)
    ai = sum(1 for g in games if g.get("ai_to"))
    clock = sum(1 for g in games if g.get("r") == "timeout")
    problems = []
    if ai / n * 1000 > 1.0:
        problems.append(f"AI timeouts {ai / n * 1000:.2f} per 1,000")
    if clock / n * 1000 > 0.5:
        problems.append(f"clock stops {clock / n * 1000:.2f} per 1,000")
    m = max(1, len(pairs))
    x1t = n1t = x2t = n2t = 0
    for old, new in pairs:
        g1, g2 = _games_of(old), _games_of(new)
        x1, x2 = sum(1 for g in g1 if g.get("ai_to")), sum(1 for g in g2 if g.get("ai_to"))
        x1t, n1t, x2t, n2t = x1t + x1, n1t + len(g1), x2t + x2, n2t + len(g2)
        if x2 >= 3 and rate_ratio_low(x1, len(g1), x2, len(g2), 1 - 0.05 / m) > 3:
            problems.append(f"AI-timeout rate up in {new['key'][:8]}")
    if x2t and rate_ratio_low(x1t, n1t, x2t, n2t, 0.95) > 3:
        problems.append("pooled AI-timeout rate up")
    return _gate(FAIL if problems else PASS, "; ".join(problems),
                 {"games": n, "ai_timeout_games": ai, "clock_stops": clock})


def _cpu_rows(out):
    import csv
    try:
        with open(Path(out) / "cpu.csv", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _epoch(stamp):
    """A state stamp (local time, "%Y-%m-%dT%H:%M:%S") as epoch seconds, or None."""
    import datetime
    try:
        return time.mktime(datetime.datetime.fromisoformat(stamp).timetuple())
    except (TypeError, ValueError):
        return None


def _in_d(row, state):
    """Whether a cpu.csv row falls in D: from D0's start to D9's end (to the last row while D9
    hasn't ended), so B5's K = 24 and 32 legs and D10's second server are left out of MG10."""
    start = _epoch(_item(state, "D0").get("started"))
    end = _epoch(_item(state, "D9").get("ended"))
    try:
        unix = float(row["unix"])
    except (KeyError, TypeError, ValueError):
        return False
    return start is not None and unix >= start and (end is None or unix <= end)


HEAP_GROWTH_MAX = 1.2          # MG10: a worker's median heap_mb in D's last hour against its first hour's
HEAP_LIMIT_GAMES = 5000        # MG10: at most 1 recycle at the heap limit per this many games
WORKER_MAX_GAMES = 2000        # pool.WORKER_MAX_GAMES: a worker quits after this many games
POLL_GAMES_MARGIN = 500        # games a busy worker may play between two 5-min polls


def _mem_rows(out, state):
    """mem.csv's rows in D (the pool polls: unix, service_pid, worker_pid, state, games, heap_mb),
    with numbers parsed ("None" heap_mb as None)."""
    import csv
    try:
        with open(Path(out) / "mem.csv", encoding="utf-8") as f:
            raw = list(csv.DictReader(f))
    except OSError:
        return []
    rows = []
    for r in raw:
        if not _in_d(r, state):
            continue
        try:
            heap = float(r["heap_mb"]) if r.get("heap_mb") not in (None, "", "None") else None
            games = int(r["games"]) if r.get("games") not in (None, "", "None") else 0
            rows.append({"unix": float(r["unix"]), "service": r.get("service_pid"), "worker": r.get("worker_pid"),
                         "state": r.get("state"), "games": games, "heap_mb": heap})
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def heap_growth(rows):
    """MG10's heap part: each worker's median heap_mb in D's last hour against its first hour's,
    over the workers polled at least twice in each. {"judged", "why" or "workers", "worst",
    "over": [worker pids past HEAP_GROWTH_MAX]}."""
    rows = [r for r in rows if r["heap_mb"] is not None]
    if not rows:
        return {"judged": False, "why": "no heap readings from the pool polls"}
    t0, t1 = min(r["unix"] for r in rows), max(r["unix"] for r in rows)
    if t1 - t0 < 2 * 3600:
        return {"judged": False, "why": f"D's pool polls span {(t1 - t0) / 3600:.1f} h (2 h needed)"}
    first, last = {}, {}
    for r in rows:
        if r["unix"] <= t0 + 3600:
            first.setdefault(r["worker"], []).append(r["heap_mb"])
        if r["unix"] >= t1 - 3600:
            last.setdefault(r["worker"], []).append(r["heap_mb"])
    ratios = {w: statistics.median(last[w]) / statistics.median(first[w]) for w in first
              if w in last and len(first[w]) >= 2 and len(last[w]) >= 2 and statistics.median(first[w]) > 0}
    if not ratios:
        pool_first = statistics.median([h for v in first.values() for h in v])
        pool_last = statistics.median([h for v in last.values() for h in v]) if last else None
        return {"judged": False, "why": "no worker lived through both D's first and last hour (recycled)",
                "pool_first_mb": round(pool_first), "pool_last_mb": None if pool_last is None else round(pool_last)}
    worst = max(ratios.values())
    return {"judged": True, "workers": len(ratios), "worst": round(worst, 3),
            "over": sorted(w for w, x in ratios.items() if x > HEAP_GROWTH_MAX)}


def heap_limit_quits(rows, taint_recycles):
    """MG10's recycle part, an upper bound from the 5-min pool polls (the pool doesn't record why a
    worker quit): workers busy at one poll and gone at the next while their service still answered,
    short of WORKER_MAX_GAMES, less the recycles the runs recorded (clock, AI timeout, crash)."""
    polls = {}
    for r in rows:
        polls.setdefault(r["unix"], []).append(r)
    stamps = sorted(polls)
    gone = 0
    for a, b in zip(stamps, stamps[1:]):
        later = {(r["service"], r["worker"]) for r in polls[b]}
        services = {r["service"] for r in polls[b]}
        for r in polls[a]:
            if r["state"] == "busy" and r["service"] in services and (r["service"], r["worker"]) not in later \
                    and r["games"] < WORKER_MAX_GAMES - POLL_GAMES_MARGIN:
                gone += 1
    return {"busy_workers_gone": gone, "run_recycles": taint_recycles,
            "heap_limit_at_most": max(0, gone - taint_recycles), "polls": len(stamps)}


def _run_recycles(results):
    total = 0
    for r in results:
        for run in r.get("runs") or []:
            found = run.get("recycled") if isinstance(run, dict) else None
            if isinstance(found, int):
                total += found
            elif isinstance(found, dict):
                total += sum(n for n in found.values() if isinstance(n, int))
    return total


def gate_mg10(out, state, plan):
    missing = _needs(state, plan, "D1")
    if missing:
        return missing
    rows = [float(r["java_ws_mb"] or 0) for r in _cpu_rows(out) if _in_d(r, state)]
    if len(rows) < 60:
        return _gate(NOT_CHECKED, "too few monitor samples")
    smooth = [sum(rows[i:i + 10]) / 10 for i in range(0, len(rows) - 9)]
    p99 = sorted(smooth)[int(0.99 * (len(smooth) - 1))]
    numbers = {"ws_p99_mb": round(p99), "ws_peak_mb": round(max(rows))}
    problems, not_judged = [], []
    if p99 > 24 * 1024:
        problems.append(f"the working set's smoothed p99 {p99 / 1024:.1f} GB (over 24 GB)")
    mem = _mem_rows(out, state)
    growth = heap_growth(mem)
    numbers["heap_growth"] = growth
    if growth["judged"]:
        if growth["over"]:
            problems.append(f"heap grew past {HEAP_GROWTH_MAX} x in workers {growth['over']}")
    else:
        not_judged.append(f"heap growth ({growth['why']})")
    v2 = [r for folder in (Path(out) / "staging" / "results", Path(out) / "D" / "filler" / "results")
          for r in _results(folder) if "seeds" in r and not r.get("kind")]
    games = sum(len(_games_of(r)) for r in v2)
    quits = heap_limit_quits(mem, _run_recycles(v2))
    quits["games"] = games
    numbers["heap_limit"] = quits
    allowed = games / HEAP_LIMIT_GAMES
    if not quits["polls"] or not games:
        not_judged.append("heap-limit recycles (no pool polls or no games in D)")
    elif quits["heap_limit_at_most"] > max(1.0, allowed):
        not_judged.append(f"heap-limit recycles (up to {quits['heap_limit_at_most']} workers left busy in "
                          f"{games:,} games; the pool doesn't record why, so this upper bound isn't a failure)")
    detail = "; ".join(problems)
    if not_judged:
        detail += ("; " if detail else "") + "not judged: " + ", ".join(not_judged)
    return _gate(FAIL if problems else PASS, detail, numbers)


def gate_mg11(out, state, plan):
    missing = _needs(state, plan, "D1")
    if missing:
        return missing
    by_session = {}
    for d in state.get("drift") or []:
        if d.get("noisy") or d.get("code") != 0:
            continue
        found = _read(Path(out) / "probes" / d["folder"] / "result.json")
        if found and found.get("cold"):
            continue                # its pool started workers for it: warm-up, not drift (leg_drift_probe)
        if found and found.get("median_ms"):
            by_session.setdefault(d.get("session", 1), []).append((d["at_s"], found["median_ms"]))
    smoke = plan.get("smoke")
    for session, rows in by_session.items():
        rows.sort()
        span = rows[-1][0] - rows[0][0] if rows else 0
        if len(rows) >= (2 if smoke else 4) and span >= (0 if smoke else 7200):
            first = rows[0][1]
            ms = [r[1] for r in rows]
            run = 0
            for x in ms:
                run = run + 1 if x >= 1.10 * first else 0
                if run >= 3:
                    return _gate(FAIL, "a rise of 10 % held over 3 probes", {"medians": ms})
            return _gate(PASS if ms[-1] <= 1.10 * first else FAIL, "", {"medians": ms})
    return _gate(NOT_CHECKED, "fewer than 4 clean drift probes over 2 h in one session")


def gate_mg12(out, state, plan):
    clean = state.get("clean")
    if clean is None:
        return _gate(NOT_CHECKED, "E4 didn't run")
    problems = []
    if clean.get("own_java"):
        problems.append(f"run-owned java.exe {clean['own_java']}")
    if clean.get("own_slots"):
        problems.append("slots held by the run")
    if clean.get("test_servers"):
        problems.append("a test server still recorded")
    if clean.get("leftovers"):
        problems.append(f"leftovers {clean['leftovers']}")
    return _gate(FAIL if problems else PASS, "; ".join(problems))


MG13_Z = 2.77                  # Bonferroni over 9 opponents at a 5 % family rate
MG13_RHO = 0.8


def reference_rows(out, deck_sha):
    """D3a's reference: deck_sha's balanced rate against each opponent in staging's v2 results
    ({opponent card_sha: balanced()})."""
    found = {}
    for r in _results(Path(out) / "staging" / "results"):
        if "seeds" not in r or r.get("kind"):
            continue
        shas = [s.get("card_sha") for s in r["sides"]]
        if deck_sha not in shas or len(shas) != 2:
            continue
        side = shas.index(deck_sha)
        b = balanced(_games_of(r), side)
        if b:
            found[shas[1 - side]] = b
    return found


def field_compare(view, reference):
    """MG13's D3a part: the adaptive view's rows (field.view: opponents' rate {value, low, high})
    against the reference's, per opponent card_sha. {"rows", "spearman", "problems"}."""
    rows, problems = [], []
    for o in (view or {}).get("opponents") or []:
        rate, ref = o.get("rate"), reference.get(o.get("card_sha"))
        if not rate or rate.get("value") is None or not ref:
            continue
        low, high = rate.get("low"), rate.get("high")
        se_ad = (high - low) / (2 * 1.96) if low is not None and high is not None else 0.0
        z = abs(rate["value"] - ref["value"]) / math.sqrt(se_ad ** 2 + ref["se"] ** 2 or 1e-12)
        row = {"opponent": o.get("title") or o.get("id"), "adaptive": round(rate["value"], 3),
               "reference": round(ref["value"], 3), "games": o.get("games"), "z": round(z, 2)}
        rows.append(row)
        if z > MG13_Z:
            problems.append(f"{row['opponent']}: z {z:.2f} (over {MG13_Z})")
        if low is not None and high is not None and ((low > 0.5 and ref["high"] < 0.5)
                                                     or (high < 0.5 and ref["low"] > 0.5)):
            problems.append(f"{row['opponent']}: the ranges exclude 50 % on opposite sides")
    rho = spearman([r["adaptive"] for r in rows], [r["reference"] for r in rows])
    if rho is not None and rho < MG13_RHO:
        problems.append(f"Spearman {rho:.2f} (under {MG13_RHO})")
    return {"rows": rows, "spearman": None if rho is None else round(rho, 3), "problems": problems}


def gate_mg13(out, state, plan):
    missing = _needs(state, plan, "D3c")
    if missing:
        return missing
    found = _read(Path(out) / "D" / "d3c" / "result.json") or {}
    rows = found.get("rows") or []
    errors = [r for r in rows if r.get("error")]
    if errors or not rows:
        return _gate(FAIL if errors else NOT_CHECKED, "D3c runs ended with an error" if errors else "no D3c rows")
    problems, notes, numbers = [], [], {}
    no_verdict = [f"{r.get('pair')}-{r.get('mode')}" for r in rows if r.get("outcome") is None]
    if no_verdict:
        problems.append("D3c runs without a verdict: " + ", ".join(no_verdict))
    failed = [i for i in ("D2a-crn", "D2a-m4", "D2a-field", "D3a-ref", "D3a-api", "D10")
              if _item(state, i).get("status") == "failed"]
    if failed:
        problems.append("ended with errors: " + ", ".join(failed))
    d3a = _needs(state, plan, "D3a-ref", "D3a-api")
    if d3a:
        notes.append(f"D3a's adaptive-against-reference part not checked ({d3a['detail']})")
    else:
        api = _read(Path(out) / "D" / "d3a-api" / "result.json") or {}
        view = api.get("view")
        deck = ((view or {}).get("deck") or {}).get("card_sha")
        if not view or not deck:
            notes.append("D3a's adaptive-against-reference part not checked (D3a-api has no view)")
        else:
            compared = field_compare(view, reference_rows(out, deck))
            numbers["d3a"] = compared
            if len(compared["rows"]) < 3:
                notes.append(f"D3a's part not checked ({len(compared['rows'])} opponents in both rows)")
            problems += ["D3a " + p for p in compared["problems"]]
    detail = "; ".join(problems + notes)
    if problems:
        return _gate(FAIL, detail, numbers)
    return _gate(NOT_CHECKED if notes else PASS, detail, numbers)


def _games_per_min(out, folder):
    results = _results(Path(out) / "B" / folder)
    return results


def gate_mg14(out, state, plan):
    missing = _needs(state, plan, "B1a", "B2", "B1b")
    if missing:
        return missing
    if plan.get("smoke"):
        return _gate(NOT_CHECKED, "speed isn't judged in --smoke (tiny sizes, wave 1 at 200 games, the PC in use)")
    numbers = {}
    for wl, sub, walls_at in (("IG", "ig", 0), ("RV", "rv", 1), ("GF", "gf1", 2)):
        rates = []
        for item in ("B1a", "B1b"):
            walls = _item(state, item).get("walls") or []
            results = _results(Path(out) / "B" / item.lower() / sub)
            if results and len(walls) > walls_at:
                rates.append(len(_games_of(results[0])) / walls[walls_at] * 60)
        if wl == "GF":
            for item in ("B1a", "B1b"):
                walls = _item(state, item).get("walls") or []
                results = _results(Path(out) / "B" / item.lower() / "gf2")
                if results and len(walls) > 3:
                    rates.append(len(_games_of(results[0])) / walls[3] * 60)
        numbers[wl] = statistics.mean(rates) if rates else None
    rows = _leg_rows(out, "b2")
    warm = {wl: [r["games_per_min"] for r in rows if r["workload"] == wl and r["round"] in (1, 2)
                 and r.get("games_per_min")] for wl in ("IG", "RV", "GF")}
    cold = [r["games_per_min"] for r in rows if r["workload"] == "IG" and r["round"] == 0 and r.get("games_per_min")]
    need = {"IG": 1.25, "RV": 1.0, "GF": 0.9}
    problems, checked = [], {}
    for wl, factor in need.items():
        if numbers.get(wl) and warm[wl]:
            ratio = statistics.mean(warm[wl]) / numbers[wl]
            checked[wl] = round(ratio, 3)
            if ratio < factor:
                problems.append(f"warm {wl} {ratio:.2f} x wave 1 (needs {factor})")
    if numbers.get("IG") and cold:
        ratio = cold[0] / numbers["IG"]
        checked["IG_cold"] = round(ratio, 3)
        if ratio < 0.9:
            problems.append(f"cold IG {ratio:.2f} x wave 1 (needs 0.9)")
    if not checked:
        return _gate(NOT_CHECKED, "no speed numbers")
    if any(_item(state, i).get("status") == "noisy" for i in ("B1a", "B2", "B1b")):
        return _gate(NOT_CHECKED, "a timing leg was noisy", checked)
    return _gate(FAIL if problems else PASS, "; ".join(problems) + ("; B3's part not checked by the harness yet"),
                 checked)


def gate_mg15(out, state, plan):
    missing = _needs(state, plan, "D1", "E1")
    if missing:
        return missing
    pairs, v2 = _pairs(out)
    m = max(1, len(v2))
    zcrit = _norm_ppf(1 - 0.025 / m)
    problems, rows = [], []
    for r in v2.values():
        games = _games_of(r)
        if not games:
            continue
        share = sum(1 for g in games if g.get("first") == 0) / len(games)
        z = (share - 0.5) / math.sqrt(0.25 / len(games))
        if abs(z) > zcrit:
            problems.append(f"starter share {share:.3f} in {r['key'][:8]}")
    for old, new in pairs:
        side_new = 0
        sha0 = new["sides"][0]["card_sha"]
        side_old = [s["card_sha"] for s in old["sides"]].index(sha0)
        a, b = balanced(_games_of(old), side_old), balanced(_games_of(new), side_new)
        if not a or not b:
            continue
        rows.append({"key": new["key"][:12], "v1": round(a["value"], 3), "v2": round(b["value"], 3)})
        if len(_games_of(old)) >= 400 and not _holds_adopted(new):
            z = abs(b["value"] - a["value"]) / math.sqrt(a["se"] ** 2 + b["se"] ** 2 or 1e-12)
            if z > 4.5:
                problems.append(f"win rate moved {z:.1f} SE in {new['key'][:8]}")
        if (a["low"] > 0.5 and b["high"] < 0.5) or (a["high"] < 0.5 and b["low"] > 0.5):
            problems.append(f"a swap in {new['key'][:8]}")
    if not v2:
        return _gate(NOT_CHECKED, "no replayed results")
    return _gate(FAIL if problems else PASS, "; ".join(problems), {"matchups": len(v2), "compared": rows[:50]})


def _holds_adopted(result):
    """Does either list hold an adopted override's card? (Fiery Annihilation, today.)"""
    try:
        sets = json.loads((Path(__file__).resolve().parents[1] / "lib" / "forge" / "overrides" / "sets.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    names = set()
    for found in (sets.get("sets") or {}).values():
        if isinstance(found, dict) and found.get("status") == "adopted":
            names |= {f.get("card") for f in (found.get("files") or {}).values() if isinstance(f, dict)}
    for side in result["sides"]:
        if any(name and name in side.get("dck", "") for name in names):
            return True
    return False


def gate_mg16(out, state, plan):
    missing = _needs(state, plan, "D10")
    if missing:
        return missing
    found = _read(Path(out) / "D" / "d10" / "result.json") or {}
    if "pass" not in found:
        return _gate(NOT_CHECKED, "D10 wrote no result")
    return _gate(PASS if found["pass"] else FAIL, f"quit after {found.get('quit_after_s')} s, re-warm "
                 f"{found.get('rewarm_s')} s")


def _pods():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import overnight_pods
    return overnight_pods


def gate_m6(out, state, plan):
    """D4a's 4-player pods (optional, P3): overnight_pods.gate."""
    return _pods().gate(out, state, plan, _needs, _gate)


def verdict(gates, state, plan):
    """FAIL, INCOMPLETE or PASS (section 9.1), and why."""
    failed = [g for g, v in gates.items() if v["status"] == FAIL and g not in OPTIONAL_GATES]
    if failed:
        return "FAIL", "failed: " + ", ".join(failed)
    why = []
    for g, v in gates.items():
        if g in P1_GATES or g in OPTIONAL_GATES:
            continue
        if v["status"] in (NOT_CHECKED, NOT_BUILT):
            why.append(f"{g} {v['status']}")
    p0 = [i["id"] for i in plan.get("items", []) if i["priority"] == 0 and i["id"] not in ("E4", "E5")]
    unfinished = [i for i in p0 if _item(state, i).get("status") not in ("done", "cut", "noisy")
                  and not (i == "D-fill" and _item(state, i).get("status") in ("skipped",))]
    if unfinished:
        why.append("P0 items not finished: " + ", ".join(unfinished))
    if why:
        return "INCOMPLETE", "; ".join(why)
    return "PASS", ""


def _ranks(values):
    """Ranks from 1, ties sharing their mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    """Spearman's rank correlation of two equal-length lists, or None under 3 values or without spread."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None
