"""Overnight harness source feature checks, plans, budgets and preflight preparation."""
import overnight_common as common
import overnight_processes as processes


# ============================================================ what's built (from the code)

def _is_stub(fn):
    """Is an ast FunctionDef a frozen stub: its body (after a docstring) one statement that raises
    (NotImplementedError, or a _todo(...) that makes one), or returns _not_built(...), or returns its
    parser unchanged (cli._log_args' base version)?"""
    body = list(fn.body)
    if body and isinstance(body[0], common.ast.Expr) and isinstance(getattr(body[0], "value", None), common.ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, common.ast.Raise):
        exc = stmt.exc
        name = exc.func if isinstance(exc, common.ast.Call) else exc
        name = name.id if isinstance(name, common.ast.Name) else name.attr if isinstance(name, common.ast.Attribute) else None
        return name in ("NotImplementedError", "_todo")
    if isinstance(stmt, common.ast.Return) and stmt.value is not None:
        value = stmt.value
        if isinstance(value, common.ast.Call):
            name = value.func
            name = name.id if isinstance(name, common.ast.Name) else name.attr if isinstance(name, common.ast.Attribute) else None
            if name == "_not_built":
                return True
        args = fn.args.args
        if fn.name == "_log_args" and isinstance(value, common.ast.Name) and args and value.id == args[0].arg:
            return True
    return False


def _module_ast(tree, name):
    path = common.Path(tree) / "decklab" / "lib" / "forge" / f"{name}.py"
    try:
        return common.ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None


def _functions(module):
    return {node.name: node for node in module.body if isinstance(node, common.ast.FunctionDef)} if module else {}


def _function_ast(tree, module_name, name, modules, seen=None):
    """Find a function's source, following explicit CLI ownership without importing code.

    The split CLI's _OWNERS registry names each helper's sole home. Only registered
    relative imports are followed: an unrelated file with a matching function does
    not make a missing command count as built.
    """
    seen = set() if seen is None else seen
    if module_name in seen:
        return None
    seen.add(module_name)
    if module_name not in modules:
        modules[module_name] = _module_ast(tree, module_name)
    module = modules[module_name]
    fn = _functions(module).get(name)
    if fn is not None or module is None:
        return fn
    imports = {alias.asname or alias.name: alias.name
               for node in module.body if isinstance(node, common.ast.ImportFrom) and node.level == 1
               and node.module is None for alias in node.names}
    for node in module.body:
        if not (isinstance(node, common.ast.Assign) and any(isinstance(t, common.ast.Name) and t.id == "_OWNERS"
                                                    for t in node.targets)):
            continue
        value = node.value
        if not isinstance(value, common.ast.DictComp) or len(value.generators) != 2:
            continue
        groups = value.generators[0].iter
        # The registry flattens (module, names) groups with two comprehensions.
        if not isinstance(groups, (common.ast.Tuple, common.ast.List)):
            continue
        for group in groups.elts:
            if not isinstance(group, common.ast.Tuple) or len(group.elts) != 2:
                continue
            owner, names = group.elts
            if not isinstance(owner, common.ast.Name) or owner.id not in imports:
                continue
            if isinstance(names, (common.ast.Tuple, common.ast.List)) and any(isinstance(n, common.ast.Constant) and n.value == name
                                                              for n in names.elts):
                return _function_ast(tree, imports[owner.id], name, modules, seen)
    return None


def _assigned(module, name):
    """The literal value assigned to a module-level name (frozenset(...)/set/dict/tuple), or None."""
    for node in (module.body if module else []):
        if isinstance(node, common.ast.Assign) and any(isinstance(t, common.ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if isinstance(value, common.ast.Call) and isinstance(value.func, common.ast.Name) and value.func.id in ("frozenset", "set"):
                if not value.args:
                    return set()
                value = value.args[0]
            try:
                found = common.ast.literal_eval(value)
            except ValueError:
                return "unknown"
            return found
    return None


def features(tree=common.TREE):
    """{package: {"built": bool, "why": [what's still a stub]}} for wave 3's packages, read from the
    tree's code (never a typed list): a package is built when none of its frozen stubs is left."""
    modules, out = {}, {}
    for package in common.PACKAGES:
        why = []
        for module, fn_name in common.CHECKS[package]:
            fn = _function_ast(tree, module, fn_name, modules)
            if fn is None:
                why.append(f"{module}.{fn_name} is missing")
            elif _is_stub(fn):
                why.append(f"{module}.{fn_name} is a stub")
        if package == "R":
            modules.setdefault("runner", _module_ast(tree, "runner"))
            found = _assigned(modules["runner"], "RUN_FEATURES")
            if found == "unknown":
                pass                    # computed: trust it's filled (the stub is a literal)
            elif not isinstance(found, (set, frozenset, tuple, list)) or not set(common.R_FEATURES) <= set(found):
                why.append("runner.RUN_FEATURES lacks " + ", ".join(sorted(set(common.R_FEATURES) - set(found or ()))))
        if package == "J3":
            modules.setdefault("simjar", _module_ast(tree, "simjar"))
            found = _assigned(modules["simjar"], "PILOT_SWITCHES")
            if found is not None and found != "unknown" and not found:
                why.append("simjar.PILOT_SWITCHES is empty")
        out[package] = {"built": not why, "why": why}
    return out


def leg_names():
    """The legs overnight_legs.py has built (its LEGS)."""
    module = common.ast.parse(common.LEGS.read_text(encoding="utf-8")) if common.LEGS.is_file() else None
    found = _assigned(module, "BUILT_LEGS")
    return set(found) if isinstance(found, (set, frozenset, tuple, list)) else set()


# ============================================================ the plan

def load_plan(path=common.PLAN_FILE):
    return common.json.loads(common.Path(path).read_text(encoding="utf-8"))


def _smoke_games(n):
    return max(common.SMOKE_MIN_GAMES, int(round(n / common.SMOKE_DIV)))


def resolve(plan, out, *, main, built, legs, smoke=False, only=None, inputs_dir=None):
    """The resolved plan ({"items": [...], ...}): each plan item with its estimate in seconds, and
    status "pending", or "skipped" with why: "not built tonight (package V)" when a package it
    requires isn't built (built: features()), "not built tonight (harness leg x)" for a leg the
    harness lacks, "no inputs (...)" when prepare didn't write its inputs, "not in --smoke",
    or "not in --only". D2b's ladder items become one command per rung from ladders.json."""
    inputs_dir = common.Path(inputs_dir or common.Path(out) / "inputs")
    items = []
    only = set(only or ())
    for raw in plan["items"]:
        item = {k: v for k, v in raw.items()}
        item.setdefault("requires", [])
        item["est_s"] = float(raw.get("est_min", 0)) * 60
        if smoke:
            item["est_s"] = max(15.0, item["est_s"] / common.SMOKE_DIV * 4) if item["est_s"] else 0.0
        item["status"], item["why"] = "pending", None
        missing = [p for p in item["requires"] if not built.get(p, {}).get("built")]
        if missing:
            item["status"] = "skipped"
            item["why"] = "not built tonight (package " + ", ".join(missing) + ")"
            item["not_built"] = missing
        elif item.get("leg") and item["leg"] not in legs:
            item["status"], item["why"] = "skipped", f"not built tonight (harness leg {item['leg']})"
            item["not_built"] = ["H:" + item["leg"]]
        elif smoke and raw.get("smoke") is False:
            item["status"], item["why"] = "skipped", "not in --smoke"
        elif item.get("inputs") and not all((inputs_dir / name).exists() for name in item["inputs"]):
            item["status"] = "skipped"
            item["why"] = "no inputs (" + ", ".join(n for n in item["inputs"] if not (inputs_dir / n).exists()) + ")"
        elif only and not (item["id"] in only or item["block"] in only or item.get("internal")):
            item["status"], item["why"] = "skipped", "not in --only"
        if item.get("ladders") and item["status"] == "pending":
            item["cmds"] = _ladder_cmds(inputs_dir, item["ladders"])
            if not item["cmds"]:
                item["status"], item["why"] = "skipped", "no inputs (no ladder rungs)"
        if item.get("specs") and item["status"] == "pending":
            found = [name for name in item["specs"] if (inputs_dir / name).exists()]
            item["cmds"] = [[str(inputs_dir / name) if t == "{SPEC}" else t.replace("{NAME}", common.Path(name).stem)
                             for t in item["spec_cmd"]] for name in found]
            if not found:
                item["status"] = "skipped"
                item["why"] = "no inputs (" + ", ".join(item["specs"]) + ")"
            elif len(found) < len(item["specs"]):
                item["est_s"] *= len(found) / len(item["specs"])
        items.append(item)
    return {"version": 1, "smoke": bool(smoke), "main": str(main), "tree": str(common.TREE), "out": str(out),
            "built": built, "legs": sorted(legs), "soak_min_s": (plan.get("smoke_soak_min_min", 10) * 60 if smoke
                                                                  else plan.get("soak_min_h", 3.0) * 3600),
            "end_reserve_s": plan.get("end_reserve_min", 15) * 60 if not smoke else 60,
            "rates": plan.get("rates", {}), "workloads": plan.get("workloads", {}), "items": items}


def _ladder_cmds(inputs_dir, decks):
    try:
        ladders = common.json.loads((common.Path(inputs_dir) / "ladders.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cmds = []
    for deck in decks:
        found = ladders.get(deck)
        if not found:
            continue
        for rung in found.get("rungs", []):
            cmds.append(["{F}", "variant", deck, "--list", str(common.Path(inputs_dir) / rung["file"]), "--against",
                         found["reference"], "--games", "{games:400}", "--results-dir", "{OUT}/staging/results",
                         "--logs-dir", "{OUT}/logs/ladders", "--json"])
    return cmds


def expand(cmd, ctx, scale=1.0):
    """A command template's argv and working folder: (argv, cwd). ctx: {"OUT", "MAIN", "smoke",
    "card_data_mtime", ...}. {games:N} is N times scale (rounded to 25, at least 25; in --smoke
    N / SMOKE_DIV); {workers} is "--workers 4" in --smoke, else nothing."""
    argv, cwd = [], str(common.TREE)
    for i, token in enumerate(cmd):
        if token == "{F}":
            argv += [common.PY, "-m", "decklab.lib.forge"]
        elif token == "{FM}":
            argv += [common.PY, "-m", "decklab.lib.forge"]
            cwd = ctx["MAIN"]
        elif token == "{L}":
            argv += [common.PY, str(common.LEGS)]
        elif token == "{workers}":
            if ctx.get("smoke"):
                argv += ["--workers", str(common.SMOKE_WORKERS)]
        elif common.re.fullmatch(r"\{smoke:[^|}]*\|[^}]*\}", token):
            argv += token[7:-1].split("|", 1)[0 if ctx.get("smoke") else 1].split()
        else:
            argv.append(_fill(token, ctx, scale))
    return argv, cwd


def _games(n, ctx, scale):
    if ctx.get("smoke"):
        return _smoke_games(n)
    return max(25, int(round(n * scale / 25.0)) * 25) if scale < 1 else n


def _fill(token, ctx, scale):
    def sub(m):
        name, arg = m[1], m[2]
        if name == "games":
            return str(_games(int(arg), ctx, scale))
        if name == "choice":            # wave 1's play takes only GAME_CHOICES
            if ctx.get("smoke"):
                return str(common.GAME_CHOICES[0])
            want = int(arg) * scale
            return str(max([c for c in common.GAME_CHOICES if c <= max(want, common.GAME_CHOICES[0])]))
        if name == "budget":
            return "quick" if ctx.get("smoke") else arg
        if name in ctx:
            return str(ctx[name])
        return m[0]
    return common.re.sub(r"\{(\w+)(?::([^}]*))?\}", sub, token)


# ============================================================ the time budget (section 5.5)

def item_est(item, scale=None):
    return item["est_s"] * (item.get("scale", 1.0) if scale is None else scale)


def _min_est(item):
    return item["est_s"] * (item.get("shrink_min") or 1.0)


def soak_owed(soak_min_s, soak_s, soak_server_s, planned_soak_s=0.0, planned_server_s=0.0):
    """The filler still needed for the soak minimum: D's soak time must reach soak_min_s, at least
    half of it on the test server's pool."""
    total = soak_min_s - soak_s - planned_soak_s
    server = soak_min_s / 2 - soak_server_s - planned_server_s
    return max(0.0, total, server)


def _planned_soak(items):
    total = server = 0.0
    for item in items:
        if item.get("soak") and item["status"] == "pending" and item.get("internal") != "filler":
            total += item_est(item)
            if item.get("pool") == "server":
                server += item_est(item)
    return total, server


def upfront(items, window_s, *, soak_min_s, soak_s=0.0, soak_server_s=0.0, end_reserve_s=900.0):
    """The up-front decision (section 5.5): keep pending items in priority order (P0, then P1..P3;
    plan order within one) while they fit window_s (the session's budget and deadline, whichever is
    shorter) less the end's reserve and the filler the soak minimum still needs; shrink P1 items to
    their shrink_min before dropping any P1 item. Changes items in place (scale, status "dropped",
    why); returns the filler planned, in seconds."""
    pending = [i for i in items if i["status"] == "pending" and i.get("internal") != "filler"]
    for item in pending:
        item["scale"] = 1.0

    def need():
        kept = [i for i in pending if i["status"] == "pending"]
        soak, server = _planned_soak(kept)
        filler = soak_owed(soak_min_s, soak_s, soak_server_s, soak, server)
        return sum(item_est(i) for i in kept) + filler + end_reserve_s, filler

    for priority in (3, 2):
        for item in reversed([i for i in pending if i["priority"] == priority]):
            if need()[0] <= window_s:
                break
            item["status"], item["why"] = "dropped", f"P{priority}: the night's budget doesn't fit it"
    if need()[0] > window_s:
        for item in [i for i in pending if i["priority"] == 1 and i.get("shrink_min")]:
            item["scale"] = item["shrink_min"]
    for item in reversed([i for i in pending if i["priority"] == 1]):
        if need()[0] <= window_s:
            break
        item["status"], item["why"] = "dropped", "P1: the night's budget doesn't fit it, even shrunk"
    return need()[1]


def reserve(priority, items, filler_owed_s, end_reserve_s=900.0):
    """reserve(p): the end's reserve, the filler still owed, and the estimates (at shrink_min) of
    every not-yet-run item of a higher priority than p (P0 is highest)."""
    later = sum(_min_est(i) for i in items if i["status"] == "pending" and i["priority"] < priority
                and i.get("internal") != "filler")
    return end_reserve_s + filler_owed_s + later


def fit(item, remaining_s):
    """Before an item: ("run", scale), or ("dropped", why). remaining_s is min(budget - active,
    deadline - now) - reserve(p). A P0 item always runs."""
    est = item_est(item, 1.0)
    if item["priority"] == 0 or est <= remaining_s:
        return "run", 1.0
    shrink = item.get("shrink_min")
    if shrink and est * shrink <= remaining_s and remaining_s > 0:
        return "run", max(shrink, remaining_s / est)
    return "dropped", f"P{item['priority']}: {int(est // 60)} min doesn't fit the {max(0, int(remaining_s // 60))} min left"


def deadline_epoch(hhmm, now=None):
    """--deadline HH:MM as an absolute instant: the next such local time (time.mktime with
    tm_isdst=-1, so a daylight-saving change is handled)."""
    now = common.time.time() if now is None else now
    hour, minute = (int(x) for x in hhmm.split(":"))
    lt = common.time.localtime(now)
    for days in (0, 1, 2):
        stamp = common.time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + days, hour, minute, 0, 0, 0, -1))
        if stamp > now:
            return stamp
    raise ValueError(hhmm)


# ============================================================ preflight (A1)

def preflight_checks(main, smoke=False):
    """A1's checks (section 6 A1), read-only: [{"name", "ok": True/False/None, "detail", "gate"}].
    "gate" marks MG1's checks."""
    checks = []

    def add(name, ok, detail=None, gate=True):
        checks.append({"name": name, "ok": ok, "detail": detail, "gate": gate})

    main = str(main)
    merged = common.subprocess.run(["git", "merge-base", "--is-ancestor", common._git("rev-parse", "HEAD", cwd=main) or "main",
                             "HEAD"], cwd=str(common.TREE), capture_output=True).returncode == 0
    add("main merged into HEAD", merged)
    # Since phase 4 the deck lists are in Deck Lab's database, not magic/: the identity records
    # a hash of the played lists (deck_lists), so a list changed mid-run is caught across sessions.
    lists = common.deck_lists()
    add("the database's decks can be read (deck_lists recorded)",
        bool(lists) and not str(lists).startswith("error:"), lists)
    status = common._json_cmd([common.PY, "-m", "decklab.lib.forge", "status"])
    log_ = (status or {}).get("card_log") or {}
    add("card log ready and checked", bool(log_.get("ready")), log_.get("problem"))
    ov = (status or {}).get("overrides")
    if isinstance(ov, dict):
        add("adopted override sets deployed, none stale", not ov.get("stale"), ov.get("stale") or None)
    else:
        add("adopted override sets deployed, none stale", None, "status has no overrides (E3 not built)")
    switches = (status or {}).get("pilot_switches")
    add("pilot_switches = aisim-hybrid-1, team-pump-1",
        None if switches is None else sorted(switches) == ["aisim-hybrid-1", "team-pump-1"], switches)
    if features()["E3"]["built"]:
        pilots = common.subprocess.run([common.PY, "-m", "decklab.lib.forge", "pilots", "--check"], cwd=str(common.TREE),
                                capture_output=True, text=True)
        add("pilots --check clean", pilots.returncode == 0, (pilots.stdout + pilots.stderr).strip()[-400:] or None)
    else:
        add("pilots --check clean", None, "pilots isn't built (E3)")
    java = processes.processes_named("java.exe")
    add("java.exe running before the run (foreign: reported)", None, [pid for pid, _ in java], gate=False)
    running = processes._http_ok(8642)
    held = processes.held_slots(common._json_cmd([common.PY, "-m", "decklab.lib.forge", "slots", "--json"]))
    # while the 8642 server is up its pool may hold slots; the run's A1 stops it before this check
    add("no slot held", not held, (held or None) if not (held and running) else
        "held while the 8642 server runs (A1 stops it first)", gate=not smoke and not running)
    services = common._json_cmd([common.PY, "-m", "decklab.lib.forge", "pool", "--json"])
    if isinstance(services, list):
        others = processes.foreign_services(services, processes._listener_pid(8642) if running else None, main if running else None)
        others, stale = processes.split_answering(others)
        add("no live forge-pool service file except the 8642 server's", not others,
            [f"pid {s.get('pid')} ({s.get('checkout')})" for s in others] or None, gate=not smoke)
        if stale:
            add("forge-pool service files that don't answer (reported)", None,
                [f"pid {s.get('pid')} ({s.get('checkout')}): stale file, pid reused?" for s in stale], gate=False)
    else:
        add("no live forge-pool service file except the 8642 server's", None, "pool --json gave no answer",
            gate=False)
    add("ports 8643 and 8644 free", not processes._http_ok(common.SERVER_PORT) and not processes._http_ok(common.IDLE_PORT))
    free = common.shutil.disk_usage(str(common.TREE)).free / 1e9
    add("15 GB free disk", free >= 15 or smoke, round(free, 1))
    add("the 8642 server's state", None, "running" if running else "not running", gate=False)
    return {"checks": checks, "server_running": running}


# ============================================================ prepare (section 3)

def prepare(out, main, smoke=False):
    """$OUT/inputs/ (overnight_legs prepare-inputs writes variants, ladders and the experiment
    specs from today's lists and saved card stats) and $OUT/plan.resolved.json."""
    out = common.Path(out)
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    done = common.subprocess.run([common.PY, str(common.LEGS), "prepare-inputs", "--out", str(out / "inputs"), "--results-dir",
                           str(common.Path(main) / "decklab" / "data" / "forge" / "results")], cwd=str(common.TREE),
                          capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout + done.stderr, file=common.sys.stderr)
    resolved = resolve(load_plan(), out, main=main, built=features(), legs=leg_names(), smoke=smoke)
    (out / "plan.resolved.json").write_text(common.json.dumps(resolved, indent=1), encoding="utf-8")
    return resolved


def describe_plan(resolved, budget_s, window_s, json_out=False):
    """What tonight's run will do: each item with its priority and estimate, what's skipped (not
    built tonight, no inputs) and what the up-front decision drops."""
    items = [dict(i) for i in resolved["items"]]
    filler = upfront(items, min(budget_s, window_s), soak_min_s=resolved["soak_min_s"],
                     end_reserve_s=resolved["end_reserve_s"])
    if json_out:
        return common.json.dumps({"items": [{k: i.get(k) for k in ("id", "block", "priority", "est_s", "scale", "status",
                                                             "why")} for i in items],
                           "filler_s": filler, "built": resolved["built"]}, indent=1)
    lines = ["Packages built in this tree: " + ", ".join(
        f"{p} {'yes' if v['built'] else 'NO'}" for p, v in resolved["built"].items())]
    total = 0.0
    for i in items:
        est = item_est(i) if i["status"] == "pending" else 0.0
        total += est
        mark = {"pending": "run", "skipped": "SKIP", "dropped": "DROP"}.get(i["status"], i["status"])
        scale = f" x{i.get('scale', 1.0):.2f}" if i.get("scale", 1.0) != 1.0 else ""
        lines.append(f"  {i['id']:<10} P{i['priority']} {mark:<5} {est / 60:6.1f} min{scale}"
                     + (f"  ({i['why']})" if i.get("why") else ""))
    fill = next((i for i in items if i.get("internal") == "filler"), None)
    if fill is not None and fill["status"] != "pending":
        lines.append(f"The soak filler can't run ({fill.get('why')}), so the soak gates will be not checked.")
    lines.append(f"Planned items {total / 60:.0f} min, filler for the soak minimum {filler / 60:.0f} min, "
                 f"the end's reserve {resolved['end_reserve_s'] / 60:.0f} min; budget {budget_s / 3600:.1f} h, "
                 f"window {window_s / 3600:.1f} h.")
    nb = sorted({p for i in items for p in i.get("not_built", [])})
    if nb:
        lines.append("Not built tonight: " + ", ".join(nb) + " (their items are skipped; the report marks the "
                     "gates that need them INCOMPLETE, never FAIL).")
    return "\n".join(lines)


B_ANCHORS = ("B0", "B1a", "B2", "B1b")
B_LEGS_DONE = ("done", "skipped", "dropped", "noisy")


def rerun_b_anchors(state):
    """Timing stays within a session (section 5.3): when B didn't finish in the earlier session,
    the new one runs B0, B1a and B2 again before the remaining B legs, and B1b at the end."""
    items = state["items"]
    b = {k: v for k, v in items.items() if k.startswith("B")}
    if not b or all(v.get("status") in B_LEGS_DONE for v in b.values()) and items.get("B1b", {}).get(
            "status") == "done":
        return False
    for item_id in B_ANCHORS:
        if item_id in items and items[item_id].get("status") != "skipped":
            items[item_id]["status"] = "pending"
            items[item_id]["note"] = "run again: timing stays within a session"
    return True
