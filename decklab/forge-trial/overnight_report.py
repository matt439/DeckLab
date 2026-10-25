"""The combined run's report (forge-trial/sim-combined-run.md sections 8 and 9; wave 3's package H):
REPORT.md, report.json and rates.json from $OUT's state and outputs.

Each merge gate (MG1-MG16) is "pass", "fail", "not checked" (with why) or "not built tonight" (an item
it needs was skipped because its wave 3 package isn't in the tree, or its harness leg isn't built).
The verdict: FAIL when a gate that ran failed; INCOMPLETE when none failed but a P0 item didn't run
or finish, or a gate that needs only P0 items is "not checked" or "not built tonight"; else PASS.
Gates that need only P1 items (MG13, MG16) don't hold up a PASS. Optional gates (OPTIONAL_GATES: M6, D4a's
4-player pods, P3) are reported only: they never hold up a PASS and never FAIL the verdict.

REPORT.md follows section 8: the verdict and gates, what ran, the B legs' timing, the gates' numbers,
then the soak, the fail-fast diagnostics (when they ran), the replay, adaptive savings, the field
view, M4 pairing, the experiments with their adoption candidates, E3's offline numbers, M6 and M7,
cleanup and the next steps. A part that can't be built is reported with its error, never a crash.
The controller writes it at E5 and again once the session has ended; the supervisor writes it last.

The original module remains the report entry point and owns orchestration, pilot analysis and
section collection. overnight_report_gates owns the acceptance checks and shared statistics;
overnight_report_render owns Markdown. Existing helper names remain available here. MG8 and
_staged_checks stay together here so staged-result validation keeps its existing patch binding.
"""
import json
import math
import statistics
import sys
import time
from pathlib import Path

# Trial scripts are also loaded by file location; resolve their adjacent helpers in that case.
_TRIAL_DIR = str(Path(__file__).resolve().parent)
if _TRIAL_DIR not in sys.path:
    sys.path.insert(0, _TRIAL_DIR)

from overnight_report_gates import (
    PASS, FAIL, NOT_CHECKED, NOT_BUILT, P1_GATES, OPTIONAL_GATES, _read, _gate, _item, _needs,
    _games_of, _results, _wilson, balanced, _norm_ppf, _beta_ppf_lower, rate_ratio_low, gate_mg1,
    gate_mg2, gate_mg3, gate_mg4, gate_mg5, _leg_rows, _outcome_same, _outcome_excused, gate_mg6,
    _sessions_d, _excused_games, gate_mg7, MG8_FAILED_ALL, MG8_FAILED_ONE, _failed_games,
    _read_json_out, _pairs, gate_mg9, _cpu_rows, _epoch, _in_d, HEAP_GROWTH_MAX, HEAP_LIMIT_GAMES,
    WORKER_MAX_GAMES, POLL_GAMES_MARGIN, _mem_rows, heap_growth, heap_limit_quits, _run_recycles,
    gate_mg10, gate_mg11, gate_mg12, MG13_Z, MG13_RHO, reference_rows, field_compare, gate_mg13,
    _games_per_min, gate_mg14, gate_mg15, _holds_adopted, gate_mg16, _pods, gate_m6, verdict,
    _ranks, spearman,
)

from overnight_report_render import (
    _pilot_markdown, _pct, _pts, _markdown, SPEARMAN_05, _m7_markdown, _cell, _pct_cell,
    _section_error, _sections_markdown, _experiment_table,
)


def _staged_checks(v2):
    """MG8's per-file checks of the staged v2 results: each passes saved._is_result for its own key
    and shows with views.view. [problem in words], or None when the tree's modules can't be loaded
    (that part is then not judged)."""
    try:
        import sys
        tree = str(Path(__file__).resolve().parents[2])
        if tree not in sys.path:
            sys.path.insert(0, tree)
        from decklab.lib.forge import saved, views
    except Exception:
        return None
    problems = []
    for result in v2:
        key = result.get("key")
        try:
            if not saved._is_result(result, key):
                problems.append(f"{str(key)[:12]} isn't a saved result")
                continue
            views.view(result, result["sides"][0]["card_sha"])
        except Exception as e:
            problems.append(f"{str(key)[:12]} doesn't show ({type(e).__name__})")
    return problems


def gate_mg8(out, state, plan):
    missing = _needs(state, plan, "D1")
    if missing:
        return missing
    for item_id in ("E1", "E2"):            # staged-move's dry run exits 1 when files are stale: still judged
        if _item(state, item_id).get("status") not in ("done", "failed") or not _item(state, item_id).get("codes"):
            return _needs(state, plan, item_id) or _gate(NOT_CHECKED, f"{item_id} didn't run")
    e1 = _read_json_out(Path(out) / "E" / "e1" / "out.txt") or {}
    e2 = _read_json_out(Path(out) / "E" / "e2" / "out.txt") or {}
    planned = len(e1.get("planned") or [])
    staged = _results(Path(out) / "staging" / "results")
    v2 = [r for r in staged if "seeds" in r and not r.get("kind")]
    games = sum(len(_games_of(r)) for r in v2)
    failed = sum(_failed_games(r) for r in v2)
    problems, not_judged = [], []
    if planned:
        problems.append(f"{planned} matchups still missing games")
    if e2.get("stale"):
        problems.append(f"{len(e2['stale'])} staged files stale")
    if failed > MG8_FAILED_ALL * (games + failed):
        problems.append(f"failed chunks hold {failed} of {games + failed} replayed games (over 0.5 %)")
    for r in v2:
        lost = _failed_games(r)
        total = len(_games_of(r)) + lost
        if lost and lost > MG8_FAILED_ONE * total:
            problems.append(f"failed chunks hold {lost} of {total} games in {str(r.get('key'))[:12]} (over 2 %)")
    d1 = _read_json_out(Path(out) / "D" / "d1" / "out.txt") or {}
    if d1.get("failed"):
        problems.append(f"{len(d1['failed'])} replayed matchups failed")
    errored = [r for r in v2 if any(isinstance(run, dict) and run.get("error") for run in r.get("runs") or [])]
    if errored:
        problems.append(f"{len(errored)} staged matchups have a run that ended with an error")
    checks = _staged_checks(v2)
    if checks is None:
        not_judged.append("_is_result and views.view over the staged files")
    else:
        problems += checks
    detail = "; ".join(problems)
    if not_judged:
        detail += ("; " if detail else "") + "not judged: " + ", ".join(not_judged)
    return _gate(FAIL if problems else PASS, detail,
                 {"v2_results": len(v2), "games": games, "failed_games": failed})


GATES = [("MG1", "Preflight", gate_mg1), ("MG2", "Parity (C1)", gate_mg2), ("MG3", "Card log on/off (C2)", gate_mg3),
         ("MG4", "Warm check (C3)", gate_mg4), ("MG5", "Deck order (C4)", gate_mg5),
         ("MG6", "Determinism (B)", gate_mg6), ("MG7", "Soak", gate_mg7), ("MG8", "Replay (E1, E2)", gate_mg8),
         ("MG9", "Recycles and limits", gate_mg9), ("MG10", "Memory", gate_mg10), ("MG11", "Drift", gate_mg11),
         ("MG12", "Clean", gate_mg12), ("MG13", "Function", gate_mg13), ("MG14", "Speed", gate_mg14),
         ("MG15", "v2 against v1", gate_mg15), ("MG16", "Idle close (D10)", gate_mg16)]


GATES.append(("M6", "4-player pods (D4a, optional)", gate_m6))


# ============================================================ pilot experiments (D2d-p2, D2e)

PILOT_EXPERIMENTS = ("exp-profiles", "exp-hybrid", "exp-hybrid-mirror")
SENSITIVITY_B, SENSITIVITY_C = "exp-sensitivity-b", "exp-sensitivity-c"
BH_Q = 0.10                 # flips: Benjamini-Hochberg discoveries at 10 % (runbook section 9.3)
RANKINGS_HOLD = 0.9         # Spearman of the ratings at or above this: "rankings hold"


def _seqstats():
    import sys
    tree = str(Path(__file__).resolve().parents[2])
    if tree not in sys.path:
        sys.path.insert(0, tree)
    from decklab.lib.forge import seqstats
    return seqstats


def _matchup(r):
    m = r.get("matchup") or {}
    return {k: m.get(k) for k in ("delta", "low", "high", "z", "clearly_negative")}


def pilot_rows(out):
    """Runbook section 8 item 11, pilots (D2d-p2): per arm of the profile and hybrid experiments,
    CONTRACT-W3.md section 12.4's recommendation and why, the mirror win rates, the reference pairs
    (paired against the control) and the speed; and what the hybrid leg played."""
    rows = []
    for name in PILOT_EXPERIMENTS:
        found = _read(Path(out) / "experiments" / name / "experiment.json")
        if not isinstance(found, dict):
            continue
        for arm, a in (found.get("arms") or {}).items():
            pairs = a.get("pairs") or []
            speed_only = name == "exp-hybrid"       # the hybrid's speed part: its mirror experiment decides
            rows.append({"experiment": name, "arm": arm, "recommendation": None if speed_only else
                         a.get("recommendation"), "why": ["The speed part: exp-hybrid-mirror's arm carries the "
                                                          "recommendation."] if speed_only else a.get("why") or [],
                         "games_per_pair": a.get("games_per_pair"),
                         "mirror": [dict(r["mirror"], pair=r["pair"], games=(r.get("games") or {}).get("arm"))
                                    for r in pairs if r.get("mirror")],
                         "references": [dict(_matchup(r), pair=r["pair"], perspective=r.get("perspective"))
                                        for r in pairs if not r.get("mirror")],
                         "slowdown": ((a.get("pooled") or {}).get("speed") or {}).get("slowdown")})
    return {"arms": rows, "hybrid": _read(Path(out) / "D" / "d2d-hybrid" / "result.json")}


def _bh(pvalues, q=BH_Q):
    """The indexes of the Benjamini-Hochberg discoveries at level q."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m, last = len(pvalues), -1
    for rank, i in enumerate(order, 1):
        if pvalues[i] <= q * rank / m:
            last = rank
    return set(order[:last]) if last > 0 else set()


def _result_sides(result, pair, shas):
    """The pair's deck ids in the result's side order (seen_as, else card_sha through shas), or None."""
    sides = result.get("sides") or []
    if len(sides) != 2:
        return None
    ids = []
    for s in sides:
        seen = {x.get("id") for x in (s.get("seen_as") or []) if isinstance(x, dict)} & set(pair)
        if len(seen) == 1:
            ids.append(next(iter(seen)))
        elif s.get("card_sha") in shas:
            ids.append(shas[s["card_sha"]])
        else:
            ids.append(None)
    if ids[0] == ids[1] or None in ids:
        return None
    return ids


def _add_cells(data, result, ids, games):
    """Bradley-Terry cells {(i, j, i_started): [i's wins, decided]} of the result's first games."""
    i, j = sorted(ids)
    me = ids.index(i)
    for g in sorted(_games_of(result), key=lambda g: g.get("g", 0))[:games]:
        if g.get("w") not in (0, 1) or g.get("first") not in (0, 1):
            continue
        cell = data.setdefault((i, j, g["first"] == me), [0, 0])
        cell[0] += g["w"] == me
        cell[1] += 1


def _sens_results(out, name):
    """{pair (sorted tuple): {"control": (result, ids), "arm": (result, ids), "p": a two-sided p or 1}}
    for an experiment's pairings: the control from staging or the experiment's own control folder,
    the arm from its folder; a pairing the arm skipped keeps its control as its arm."""
    folder = Path(out) / "experiments" / name
    found, spec = _read(folder / "experiment.json"), _read(folder / "spec.json")
    if not isinstance(found, dict):
        return None, None
    games = found.get("games") or (spec or {}).get("games") or 200
    shas, rows = {}, {}
    controls = [Path(out) / "staging" / "results", folder / "control"]
    for arm, a in (found.get("arms") or {}).items():
        for r in a.get("pairs") or []:
            ctrl = next((x for x in (_read(c / f"{r['control_key']}.json") for c in controls) if x), None)
            mine = _read(folder / arm / f"{r['key']}.json")
            for res in (ctrl, mine):
                for s in (res or {}).get("sides") or []:
                    seen = [x.get("id") for x in (s.get("seen_as") or []) if isinstance(x, dict)]
                    if len(set(seen) & set(r["pair"])) == 1:
                        shas[s.get("card_sha")] = next(iter(set(seen) & set(r["pair"])))
            z = (r.get("matchup") or {}).get("z")
            rows[tuple(sorted(r["pair"]))] = {"control": ctrl, "arm": mine, "pair": r["pair"],
                                              "p": math.erfc(abs(z) / math.sqrt(2)) if z is not None else 1.0,
                                              "matchup": _matchup(r)}
    # skipped pairings: the same games as the control, so they're found in staging by their lists
    staged = None
    for s in found.get("skipped") or []:
        key = tuple(sorted(s["pair"]))
        if key in rows:
            continue
        if staged is None:
            staged = sorted(_results(Path(out) / "staging" / "results") + _results(folder / "control"),
                            key=lambda x: x.get("updated") or "")
        hit = None
        for res in staged:
            seen = [{x.get("id") for x in (sd.get("seen_as") or []) if isinstance(x, dict)}
                    for sd in res.get("sides") or []]
            if len(seen) == 2 and ((key[0] in seen[0] and key[1] in seen[1]) or (key[1] in seen[0] and key[0] in seen[1])) \
                    and len(_games_of(res)) >= games:
                hit = res           # the latest such result
        rows[key] = {"control": hit, "arm": hit, "pair": list(key), "p": 1.0, "matchup": None, "skipped": True}
    return rows, (games, shas)


def _fit(rows, which, games, shas, seqstats):
    data = {}
    for key, row in rows.items():
        res = row.get(which)
        ids = _result_sides(res, row["pair"], shas) if res else None
        if ids:
            _add_cells(data, res, ids, games)
    fit = seqstats.bt_fit(data) if data else None
    return fit["beta"] if fit else {}


def sensitivity(out):
    """Runbook section 8 item 11 and section 9.3, pilot sensitivity (D2e): the Bradley-Terry
    ratings of the Constructed field under (a) Default (the controls), (b) every experiment
    override set and (c) (b) plus Reckless for Rabbits on its pairings; the Spearman of (a)
    against (b) ("rankings hold" at 0.9 or more); the flips (pairings whose paired difference is a
    BH-10 % discovery); and each deck's rating spread. None when D2e-b didn't run."""
    rows_b, extra = _sens_results(out, SENSITIVITY_B)
    if not rows_b:
        return None
    games, shas = extra
    seqstats = _seqstats()
    beta_a = _fit(rows_b, "control", games, shas, seqstats)
    beta_b = _fit(rows_b, "arm", games, shas, seqstats)
    found = {"pairings": len(rows_b), "ratings": {"a": beta_a, "b": beta_b}, "flips": {}, "spearman": None,
             "rankings_hold": None, "spread": {}}
    common = sorted(set(beta_a) & set(beta_b))
    if len(common) >= 2:
        rho = seqstats.spearman([beta_a[d] for d in common], [beta_b[d] for d in common])
        found["spearman"] = rho
        found["rankings_hold"] = None if rho is None else rho >= RANKINGS_HOLD
    keys = sorted(rows_b)
    hits = _bh([rows_b[k]["p"] for k in keys])
    found["flips"]["b"] = [dict(rows_b[keys[i]]["matchup"] or {}, pair=rows_b[keys[i]]["pair"]) for i in sorted(hits)]
    rows_c, extra_c = _sens_results(out, SENSITIVITY_C)
    if rows_c:
        keys_c = sorted(rows_c)
        hits_c = _bh([rows_c[k]["p"] for k in keys_c])
        found["flips"]["c"] = [dict(rows_c[keys_c[i]]["matchup"] or {}, pair=rows_c[keys_c[i]]["pair"])
                               for i in sorted(hits_c)]
        merged = {k: (dict(v, arm=rows_c[k]["arm"]) if k in rows_c and rows_c[k].get("arm") else v)
                  for k, v in rows_b.items()}
        shas_c = {**shas, **extra_c[1]}
        found["ratings"]["c"] = _fit(merged, "arm", games, shas_c, seqstats)
    for deck in sorted(set().union(*[set(r) for r in found["ratings"].values()])):
        values = [r[deck] for r in found["ratings"].values() if deck in r]
        found["spread"][deck] = max(values) - min(values) if len(values) >= 2 else None
    return found


# ============================================================ the report's sections (runbook section 8)

EXPERIMENT_ITEMS = ("D2c-p1", "D2c-p2", "D2d-p1", "D2d-p2", "D2e-b", "D2e-c")
LADDER_ITEMS = ("D2b-p1", "D2b-p2")
OPTIONAL_ITEMS = (("D4a", "m6", "M6: 4-player Commander pods"), ("D4b", "m7", "M7: real-world decks' round robin"))


def _json_lines(path):
    """Every JSON object an item's out.txt holds on a line of its own (--json answers)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        line = line.strip()
        if line.startswith("{"):
            try:
                found.append(json.loads(line))
            except ValueError:
                continue
    return found


def _status(state, item_id):
    st = _item(state, item_id)
    return {"status": st.get("status") or "not run", "note": st.get("note")}


def _r3(x):
    return None if x is None else round(x, 3)


def replay_section(out, state, gates):
    e1 = _read_json_out(Path(out) / "E" / "e1" / "out.txt") or {}
    e2 = _read_json_out(Path(out) / "E" / "e2" / "out.txt") or {}
    d1 = _read_json_out(Path(out) / "D" / "d1" / "out.txt") or {}
    dry = _read(Path(out) / "A" / "a3" / "replay-dry-run.json") or {}
    return {"d1": _status(state, "D1"), "planned_matchups": len(dry.get("planned") or []),
            "planned_games": dry.get("games"), "still_missing": len(e1.get("planned") or []),
            "failed_matchups": len(d1.get("failed") or []), "stale": len(e2.get("stale") or []),
            "mg8": gates.get("MG8", {}).get("numbers"), "v2_v1": (gates.get("MG15", {}).get("numbers") or {}).get(
                "compared") or []}


def adaptive_section(out, state):
    found = _read(Path(out) / "D" / "d3c" / "result.json") or {}
    return {"item": _status(state, "D3c"), "rows": [{k: r.get(k) for k in ("pair", "mode", "games", "outcome",
                                                                            "decision", "wall_s", "error")}
                                                    for r in found.get("rows") or []]}


def field_section(out, state, gates):
    api = _read(Path(out) / "D" / "d3a-api" / "result.json") or {}
    view = api.get("view") or {}
    games = sum(o.get("games") or 0 for o in view.get("opponents") or [])
    flags = [o.get("title") for o in view.get("opponents") or [] if (o.get("residual") or {}).get("flag")]
    d3b = _read(Path(out) / "D" / "d3b" / "result.json") or {}
    return {"ref": _status(state, "D3a-ref"), "api": _status(state, "D3a-api"), "wall_s": api.get("wall_s"),
            "games": games, "rating": view.get("rating"), "residual_flags": flags,
            "compare": (gates.get("MG13", {}).get("numbers") or {}).get("d3a"), "d3b": _status(state, "D3b"),
            "d3b_wall_s": d3b.get("wall_s")}


def _variant_digest(answer):
    rows = []
    for o in answer.get("opponents") or []:
        paired = o.get("paired") or {}
        unpaired = paired.get("unpaired") or {}
        rows.append({"opponent": o.get("title") or o.get("id"), "games": o.get("games"),
                     "delta": _r3(paired.get("delta")), "low": _r3(paired.get("low")), "high": _r3(paired.get("high")),
                     "rho": _r3(paired.get("rho")), "same": _r3(paired.get("same")),
                     "unpaired_low": _r3(unpaired.get("low")), "unpaired_high": _r3(unpaired.get("high")),
                     "saved_share": _r3(paired.get("saved_share"))})
    return {"verdict": answer.get("verdict"), "words": answer.get("words"), "opponents": rows,
            "looks": len(answer.get("looks") or ((answer.get("test") or {}).get("looks") or []))}


def m4_section(out, state):
    found = {"crn": _status(state, "D2a-crn"), "m4": _status(state, "D2a-m4"), "field": _status(state, "D2a-field")}
    found["crn_runs"] = [_variant_digest(a) for a in _json_lines(Path(out) / "D" / "d2a-crn" / "out.txt")]
    found["field_runs"] = [_variant_digest(a) for a in _json_lines(Path(out) / "D" / "d2a-field" / "out.txt")]
    found["m4_tables"] = experiment_tables(Path(out) / "D" / "d2a-m4" / "out.txt")
    return found


def experiment_tables(path):
    """The summary tables experiment.report printed into an item's out.txt: [{"experiment",
    "arms": [{"arm", "kind", "pairs", "matchup", "slowdown", "timeouts", "recommendation"}]}]."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found, current, in_table = [], None, False
    for line in lines:
        if line.startswith("# Experiment "):
            current = {"experiment": line[len("# Experiment "):].strip(), "arms": []}
            found.append(current)
            in_table = False
            continue
        if line.startswith("| Arm | Kind |"):
            in_table = current is not None
            continue
        if in_table:
            if line.startswith("|---"):
                continue
            if not line.startswith("| "):
                in_table = False
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 7:
                current["arms"].append(dict(zip(("arm", "kind", "pairs", "matchup", "slowdown", "timeouts",
                                                 "recommendation"), cells[:7])))
    return found


def experiments_section(out, state):
    found = {"ladders": [], "experiments": []}
    for item_id in LADDER_ITEMS:
        runs = [_variant_digest(a) for a in _json_lines(Path(out) / "D" / item_id.lower() / "out.txt")]
        found["ladders"].append({"id": item_id, **_status(state, item_id), "rungs": runs})
    for item_id in EXPERIMENT_ITEMS:
        tables = experiment_tables(Path(out) / "D" / item_id.lower() / "out.txt")
        found["experiments"].append({"id": item_id, **_status(state, item_id), "tables": tables})
    found["adopt"] = [{"item": e["id"], "experiment": t["experiment"], "arm": a["arm"], "matchup": a["matchup"]}
                      for e in found["experiments"] for t in e["tables"] for a in t["arms"]
                      if a.get("recommendation") == "adopt"]
    found["more_games"] = [{"item": e["id"], "experiment": t["experiment"], "arm": a["arm"]}
                           for e in found["experiments"] for t in e["tables"] for a in t["arms"]
                           if a.get("recommendation") == "more games"]
    return found


def optional_section(out, state):
    found = []
    for item_id, folder, title in OPTIONAL_ITEMS:
        result = _read(Path(out) / "D" / folder / "result.json")
        if result is None:
            result = _read(Path(out) / "D" / item_id.lower() / "result.json")
        numbers = {k: v for k, v in (result or {}).items() if isinstance(v, (int, float, str, bool)) or v is None}
        found.append({"id": item_id, "title": title, **_status(state, item_id), "numbers": numbers})
    return found


def diagnostics_section(out, state):
    diag = state.get("diagnostics")
    if not diag:
        return None
    found = dict(diag)
    c1 = _read(Path(out) / "C" / "diag" / "c1" / "result.json") or {}
    c2 = _read(Path(out) / "C" / "diag" / "c2" / "result.json") or {}
    found["c1_kinds"] = {fmt: v.get("kind") for fmt, v in (c1.get("formats") or {}).items()} or None
    found["c2_failed_chunks"] = [c.get("first") for c in c2.get("chunks") or [] if c.get("kind") == "failed"]         if c2 else None
    found["c2_unsure"] = c2.get("unsure_chunks") if c2 else None
    return found


def next_steps(found):
    """Section 8's next steps, from the verdict, the move's gates, the experiments and the rates."""
    steps = []
    gates = found["gates"]
    if found["verdict"] == "PASS":
        steps.append("Merge sim-w3 into main (section 9.1): every gate that needs only P0 items passed.")
    elif found["verdict"] == "FAIL":
        steps.append("Don't merge sim-w3: fix what failed (" + found["why"] + "), then run the checks again.")
    else:
        steps.append("Don't merge yet: the run is INCOMPLETE (" + found["why"] + "). Resume another night with "
                     "overnight.py supervise --out <this folder> --resume (section 10).")
    if found["verdict"] == "PASS" and gates.get("MG8", {}).get("status") == PASS             and gates.get("MG15", {}).get("status") == PASS:
        steps.append("Move the staged results after the merge, from main with the background server stopped "
                     "(section 9.2): staged-move --from <this folder>/staging/results (a dry run first: 0 stale).")
    else:
        steps.append("Don't move the staged results: the move needs the merge passed with MG8 and MG15 passed.")
    if (found.get("offline") or {}).get("card_data_unchanged") is False:
        steps.append("The card data changed during the run (E3): find out what changed before moving the staged "
                     "results, since card text feeds the lists the run replayed.")
    for a in (found.get("experiments") or {}).get("adopt") or []:
        steps.append(f"Adoption to consider: {a['arm']} ({a['experiment']}, pooled matchup {a['matchup']}). "
                     "Adopting it needs a targeted replay of the matchups holding its cards (CONTRACT-W3.md 0.3).")
    more = (found.get("experiments") or {}).get("more_games") or []
    if more:
        steps.append("More games asked for: " + ", ".join(f"{m['arm']} ({m['experiment']})" for m in more) + ".")
    rates = (found.get("rates") or {}).get("warm_games_per_min")
    if rates:
        steps.append("Copy the measured warm rates into Deck Lab's estimator (rates.json): "
                     + ", ".join(f"{k} {v}" for k, v in rates.items()) + " games a minute.")
    return steps


def build(out):
    out = Path(out)
    state = _read(out / "state.json") or {}
    plan = _read(out / "plan.resolved.json") or {}
    gates = {}
    for name, title, fn in GATES:
        try:
            found = fn(out, state, plan)
        except Exception as e:       # a gate that can't be judged is reported, never a crash
            found = _gate(NOT_CHECKED, f"the report couldn't judge it ({type(e).__name__}: {e})")
        gates[name] = dict(found, title=title)
    outcome, why = verdict(gates, state, plan)
    not_built = sorted({p for i in plan.get("items", []) for p in i.get("not_built", [])})
    cpu = _cpu_rows(out)
    gaps = []
    for a, b in zip(cpu, cpu[1:]):
        try:
            if float(b["unix"]) - float(a["unix"]) > 5:
                gaps.append([float(a["unix"]), round(float(b["unix"]) - float(a["unix"]), 1)])
        except (KeyError, ValueError):
            continue
    timing = []
    warm = {}
    for row in _leg_rows(out, "b2"):
        if row.get("round") in (1, 2) and row.get("games_per_min"):
            warm.setdefault(row.get("workload"), []).append(row["games_per_min"])
    warm = {k: statistics.mean(v) for k, v in warm.items()}
    for folder in sorted(p.name for p in (out / "B").iterdir()) if (out / "B").is_dir() else []:
        for row in _leg_rows(out, folder):
            ref = warm.get(row.get("workload"))
            timing.append({"leg": folder, "round": row.get("round"), "workload": row.get("workload"),
                           "games": row.get("games"), "games_per_min": row.get("games_per_min"),
                           "median_ms": row.get("median_ms"), "ai_timeout_games": row.get("ai_timeout_games"),
                           "clock_stops": row.get("clock_stops"), "recycled": row.get("recycled"),
                           "vs_b2_warm": round(row["games_per_min"] / ref, 3) if ref and row.get("games_per_min")
                           else None})
    found = {"verdict": outcome, "why": why, "gates": gates, "out": str(out), "not_built": not_built, "built": plan.get("built"),
             "smoke": plan.get("smoke"), "sessions": state.get("sessions"),
             "items": {k: {x: v.get(x) for x in ("status", "note", "attempts", "active_s", "scale")}
                       for k, v in (state.get("items") or {}).items()},
             "dropped": state.get("dropped"), "drill": state.get("drill"), "foreign_java": state.get("foreign_java"),
             "leftovers": state.get("leftovers"), "clean": state.get("clean"), "sleep_gaps": gaps,
             "timing": timing, "rates": _rates(out), "pilots": _guarded(pilot_rows, out),
             "sensitivity": _guarded(sensitivity, out), "m7": _m7_safe(out, state, plan)}
    for name, fn in (("replay", lambda: replay_section(out, state, gates)),
                     ("adaptive", lambda: adaptive_section(out, state)),
                     ("field", lambda: field_section(out, state, gates)), ("m4", lambda: m4_section(out, state)),
                     ("experiments", lambda: experiments_section(out, state)),
                     ("offline", lambda: _read(out / "E" / "e3" / "result.json")),
                     ("optional", lambda: optional_section(out, state)),
                     ("diagnostics", lambda: diagnostics_section(out, state))):
        try:
            found[name] = fn()
        except Exception as e:       # a section that can't be built is reported, never a crash
            found[name] = {"error": f"{type(e).__name__}: {e}"}
    found["next_steps"] = next_steps(found)
    return found


def _guarded(fn, out):
    """fn(out), or {"error": why} when it can't be worked out: the report never crashes on it."""
    try:
        return fn(out)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _m7_safe(out, state, plan):
    try:
        return m7_summary(out, state, plan)
    except Exception as e:      # M7 is P3: a summary that can't be made is reported, never a crash
        return {"ran": False, "why": f"the report couldn't read it ({type(e).__name__}: {e})"}


def bradley_terry(ids, results, prior=1.0):
    """Bradley-Terry strengths (log scale, mean 0) from [(a, b, a's wins, games)] by the MM iteration; each
    observed pair gets `prior` extra games split evenly, so a deck that never wins (or never loses) stays finite."""
    wins = {i: 0.0 for i in ids}
    games = {}
    for a, b, w, n in results:
        if not n or a not in wins or b not in wins:
            continue
        wins[a] += w + prior / 2
        wins[b] += n - w + prior / 2
        games[(a, b)] = games.get((a, b), 0) + n + prior
    strength = {i: 1.0 for i in ids}
    for _ in range(1000):
        new = {}
        for i in ids:
            d = sum(n / (strength[a] + strength[b]) for (a, b), n in games.items() if i in (a, b))
            new[i] = wins[i] / d if d else strength[i]
        mean_log = statistics.mean(math.log(v) for v in new.values()) if new else 0.0
        strength = {i: v / math.exp(mean_log) for i, v in new.items()}
    return {i: round(math.log(v), 4) for i, v in strength.items()}


def _m7_rate(row):
    """A Forge pair row's balanced win rate for its deck a (the mean of its play and draw rates), or None."""
    (n1, w1), (n2, w2) = row.get("play") or (0, 0), row.get("draw") or (0, 0)
    return (w1 / n1 + w2 / n2) / 2 if n1 and n2 else None


def m7_summary(out, state=None, plan=None):
    """M7's comparison, P3 and never a gate: Forge's round-robin matrix against the published human one
    (the input's cells that have a win rate), Spearman of the two Bradley-Terry deck ratings, and how
    often the favourite agrees. {"ran": False, "why": ...} when D4b left no result."""
    data = _read(Path(out) / "D" / "m7" / "result.json")
    if not data:
        st = _item(state or {}, "D4b")
        planned = next((i for i in (plan or {}).get("items", []) if i["id"] == "D4b"), {})
        why = st.get("note") or planned.get("why") or st.get("status") or "it didn't run"
        return {"ran": False, "why": why}
    human = data.get("human") or {}
    ids = [d["id"] for d in human.get("decks", [])]
    names = {d["id"]: d.get("archetype", d["id"]) for d in human.get("decks", [])}
    forge = {}
    for row in data.get("rows", []):
        rate = _m7_rate(row)
        if rate is not None:
            forge[(row["a"], row["b"])] = {"rate": rate, "games": row.get("games") or 0}

    def forge_rate(a, b):
        if (a, b) in forge:
            return forge[(a, b)]["rate"]
        if (b, a) in forge:
            return 1 - forge[(b, a)]["rate"]
        return None

    cells = []
    for c in human.get("cells", []):
        if c.get("pct") is None or c["a"] not in ids or c["b"] not in ids:
            continue
        cells.append({"a": c["a"], "b": c["b"], "human": c["pct"] / 100, "n": c["n"],
                      "forge": forge_rate(c["a"], c["b"])})
    both = [c for c in cells if c["forge"] is not None]
    decided = [c for c in both if c["human"] != 0.5 and c["forge"] != 0.5]
    agree = sum((c["human"] > 0.5) == (c["forge"] > 0.5) for c in decided)
    # each cell both ways round, so which deck a cell lists first doesn't change the correlation
    cell_rho = spearman([v for c in both for v in (c["human"], 1 - c["human"])],
                        [v for c in both for v in (c["forge"], 1 - c["forge"])])
    bt_forge = bradley_terry(ids, [(a, b, v["rate"] * v["games"], v["games"]) for (a, b), v in forge.items()])
    bt_human = bradley_terry(ids, [(c["a"], c["b"], c["human"] * c["n"], c["n"]) for c in cells])
    rated = [i for i in ids if any(i in k for k in forge)]
    deck_rho = spearman([bt_human[i] for i in rated], [bt_forge[i] for i in rated])
    sign_p = None
    if decided:     # two-sided sign test of the agreement against a coin flip
        k, n = agree, len(decided)
        sign_p = min(1.0, 2 * sum(math.comb(n, j) for j in range(max(k, n - k), n + 1)) / 2 ** n)
    return {"ran": True, "complete": data.get("complete"), "source": human.get("source"), "names": names,
            "decks": ids, "pairs_played": len(forge), "pairs": len(ids) * (len(ids) - 1) // 2,
            "games_per_pair": (data.get("args") or {}).get("games"),
            "errors": [r for r in data.get("rows", []) if r.get("error") or r.get("skipped")],
            "cells": cells, "cells_compared": len(both), "sign_agree": agree, "sign_decided": len(decided),
            "sign_p": sign_p, "cell_spearman": cell_rho, "deck_spearman": deck_rho, "decks_rated": len(rated),
            "bt_forge": bt_forge, "bt_human": bt_human,
            "forge_matrix": {f"{a}|{b}": round(v["rate"], 4) for (a, b), v in forge.items()}}


def write(out, rates_path=None):
    out = Path(out)
    found = build(out)
    (out / "report.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    (out / "REPORT.md").write_text(_markdown(found), encoding="utf-8")
    rates = _rates(out)
    (out / "rates.json").write_text(json.dumps(rates, indent=1), encoding="utf-8")
    if rates_path:
        Path(rates_path).write_text(json.dumps(rates, indent=1), encoding="utf-8")
    return found


def _rates(out):
    """Measured warm games a minute per workload (B2's rounds 1-2), for Deck Lab's estimator."""
    rows = _leg_rows(out, "b2")
    found = {}
    for wl in ("IG", "RV", "GF"):
        rates = [r["games_per_min"] for r in rows if r["workload"] == wl and r["round"] in (1, 2)
                 and r.get("games_per_min")]
        if rates:
            found[wl] = round(statistics.mean(rates), 1)
    return {"version": 1, "warm_games_per_min": found, "from": "the combined run's B2"}
