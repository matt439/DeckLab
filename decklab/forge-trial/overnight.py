"""The combined idle-PC run for simulation waves 2 and 3 (forge-trial/sim-combined-run.md; wave 3's
package H, sim-wave3-contract.md section 20). Standard library only, Windows.

    python decklab/forge-trial/overnight.py prepare --out OUT --main MAIN [--smoke]
    python decklab/forge-trial/overnight.py plan --out OUT [--budget-h 6] [--deadline 07:00] [--smoke] [--json]
    python decklab/forge-trial/overnight.py preflight --out OUT --main MAIN      (A1's checks, read-only)
    python decklab/forge-trial/overnight.py supervise --out OUT --budget-h 6 --deadline 07:00 --main MAIN
                                            [--smoke] [--resume] [--only C1,D1,E] [--fake]
    python decklab/forge-trial/overnight.py status --out OUT
    python decklab/forge-trial/overnight.py report --out OUT [--write-rates PATH]
    python decklab/forge-trial/overnight.py clean --out OUT
    python decklab/forge-trial/overnight.py features [--json]

- The plan (overnight-plan.json) is resolved against the code under test: an item whose wave 3
  package isn't built in this tree (features(): a stub still raising NotImplementedError, a CLI
  command still answering "isn't built yet", runner.RUN_FEATURES short of R's names) is skipped
  as "not built tonight", and its time goes to the soak filler. The report marks the gates that
  needed it INCOMPLETE ("not built tonight"), never FAIL.
- The supervisor starts the controller ("run") and starts it again after an unexpected exit, at
  most twice, in the same session. The controller runs the items one at a time in one Windows Job
  (kill on close), each child in a nested job of its own, with DECKLAB_STOP_FILE for a graceful
  stop and TerminateJobObject after STOP_GRACE_S.
- --smoke: every item at a tiny size, at most 4 workers, no idle gate, a 10-minute soak minimum,
  the 8642 server left alone, and the drill (the controller killed during the first D item and
  resumed; an item that ignores STOP ended by its job; a foreign java.exe reported, never killed).
- --fake: the same controller with every command replaced by a short fake child (tests only)."""
import types
import sys as _sys
from pathlib import Path as _Path

# Support both direct execution and spec_from_file_location callers, which do not
# automatically place this script's sibling modules on sys.path.
_TRIAL_DIR = str(_Path(__file__).resolve().parent)
if _TRIAL_DIR not in _sys.path:
    _sys.path.insert(0, _TRIAL_DIR)

import overnight_common as _common
import overnight_processes as _processes
import overnight_plan as _plan
import overnight_controller as _controller


# ============================================================ the supervisor

def supervise(args):
    """Start the controller and wait; after an unexpected exit before the deadline, start it again
    (run --continue-session), at most MAX_RESTARTS times. In --smoke it also runs the drill."""
    out = _common.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    main = args.main or str(_common.TREE)
    if args.resume:
        if (out / "STOP").exists():
            (out / "STOP").unlink()             # resuming is the owner's go-ahead again
        state = _common.load_state(out)
        if state is None:
            print("There's no run to resume in that folder.", file=_common.sys.stderr)
            return 1
        now_id = _common.identity(main) if not args.fake else state["identity"]
        differs = _common.identity_differs(state["identity"], now_id)
        if differs:
            print(_common.WRONG_IDENTITY + " (" + ", ".join(differs) + ")", file=_common.sys.stderr)
            return _common.EXIT_REFUSED
    else:
        if (out / "state.json").exists():
            print("That folder holds a run already: use --resume, or another --out.", file=_common.sys.stderr)
            return 1
        if args.fake and (out / "plan.resolved.json").exists():         # the tests' own plan
            resolved = _common.json.loads((out / "plan.resolved.json").read_text(encoding="utf-8"))
        elif not (out / "inputs").is_dir():
            resolved = _plan.prepare(out, main, smoke=args.smoke)
        else:       # inputs reviewed by day: kept; the plan is resolved again against the code as it is now
            resolved = _plan.resolve(_plan.load_plan(), out, main=main, built=_plan.features(), legs=_plan.leg_names(), smoke=args.smoke)
        if args.only:
            resolved = _plan.resolve(_plan.load_plan(), out, main=main, built=resolved["built"], legs=set(resolved["legs"]),
                               smoke=args.smoke, only=args.only.split(","))
        resolved["fake"] = bool(args.fake)
        (out / "plan.resolved.json").write_text(_common.json.dumps(resolved, indent=1), encoding="utf-8")
        state = {"run_id": _common.time.strftime("%Y%m%d-%H%M%S"),
                 "identity": _common.identity(main) if not args.fake else {"fake": True},
                 "server_was_running": None, "test_servers": {}, "sessions": [], "own_pids": [], "items": {},
                 "dropped": [], "rates": _common.json.loads(_common.PLAN_FILE.read_text(encoding="utf-8")).get("rates", {}),
                 "smoke": bool(args.smoke), "drill": {} if args.smoke else None}
    if getattr(args, "no_idle_gate", False) is True:
        state["no_idle_gate"] = True        # A2 starts at once; kept for --resume sessions too
    deadline = _plan.deadline_epoch(args.deadline) if args.deadline else _common.time.time() + args.budget_h * 3600 + 3600
    state["sessions"].append({"started": _common.time.strftime("%Y-%m-%dT%H:%M:%S"), "deadline_epoch": deadline,
                              "budget_s": args.budget_h * 3600, "active_s": 0.0, "paused_s": 0.0, "soak_s": 0.0,
                              "soak_server_s": 0.0, "b_complete": False, "needs_upfront": True, "restarts": 0})
    if args.resume:
        for item_id, st in state["items"].items():
            if st.get("status") in ("failed",) and st.get("attempts", 0) < 2:
                st["status"] = "pending"
        _plan.rerun_b_anchors(state)
    _common.save_state(out, state)
    foreign = _processes._start_foreign_java(out) if args.smoke and not args.fake else None
    gave_up = False
    try:
        restarts = 0
        while True:
            argv = [_common.PY, str(_common.Path(__file__).resolve()), "run", "--out", str(out), "--continue-session"]
            if args.fake:
                argv.append("--fake")
            proc = _common.subprocess.Popen(argv, cwd=str(_common.TREE))
            code = proc.wait()
            state = _common.load_state(out)
            if code in (_common.EXIT_STOPPED, _common.EXIT_DEADLINE, _common.EXIT_FAILFAST,
                        _common.EXIT_NEVER_IDLE, _common.EXIT_REFUSED, _common.EXIT_OWNER_STOP):
                break
            if _common.time.time() >= deadline or restarts >= _common.MAX_RESTARTS:
                _common.log(out, f"The controller ended unexpectedly (exit {code}); not restarted.")
                gave_up = True
                break
            restarts += 1
            state["sessions"][-1]["restarts"] = restarts
            _common.save_state(out, state)
            _common.log(out, f"The controller ended unexpectedly (exit {code}); starting it again ({restarts}).")
    finally:
        if foreign is not None:
            _processes._end_foreign_java(out, foreign)
    state = _common.load_state(out)
    if gave_up and (state["items"].get("E4") or {}).get("status") != "done":
        # one more controller, for the end only (D9, E4, E5): E4's cleanup, its 8642 restart and
        # MG12's record run as after any other stop
        argv = [_common.PY, str(_common.Path(__file__).resolve()), "run", "--out", str(out), "--continue-session", "--end-only"]
        if args.fake:
            argv.append("--fake")
        try:
            code = _common.subprocess.run(argv, cwd=str(_common.TREE), timeout=3600).returncode
            _common.log(out, f"The end (D9, E4, E5) ran after the controller gave up (exit {code}).")
        except (OSError, _common.subprocess.SubprocessError) as e:
            _common.log(out, f"The end couldn't run after the controller gave up: {type(e).__name__}: {e}")
        state = _common.load_state(out)
    if not args.fake and (state["items"].get("E4") or {}).get("status") != "done":
        # the controller gave up before E4's cleanup: end the run's own leftovers, and start the
        # 8642 server again if A1 stopped it
        ended = _processes.clean(out)
        if ended:
            _common.log(out, f"The supervisor ended the run's leftovers: {ended}")
        if state.get("server_was_running") and not state.get("smoke"):
            _common.subprocess.run([_common.PY, "-m", "decklab.lib.homenet", "start"], cwd=main, capture_output=True)
            _common.log(out, "The supervisor started the 8642 server again (E4 didn't run).")
    try:        # always last, so REPORT.md shows the final state (E5 done, the sessions' exits, cleanup)
        _common.sys.path.insert(0, str(_common.HERE))
        import overnight_report
        overnight_report.write(out)
    except Exception as e:
        _common.log(out, f"The report couldn't be written: {type(e).__name__}: {e}")
    return 0


# ============================================================ the command line

def main(argv=None):
    parser = _common.argparse.ArgumentParser(prog="overnight.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", required=True)
    p.add_argument("--main", default=str(_common.TREE))
    p.add_argument("--smoke", action="store_true")
    for name in ("plan", "preflight"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--main", default=str(_common.TREE))
        p.add_argument("--budget-h", type=float, default=6.0)
        p.add_argument("--deadline")
        p.add_argument("--smoke", action="store_true")
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("supervise")
    p.add_argument("--out", required=True)
    p.add_argument("--main")
    p.add_argument("--budget-h", type=float, default=6.0)
    p.add_argument("--deadline")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--no-idle-gate", action="store_true",
                   help="start without waiting for 10 idle minutes (the run still pauses while the PC is in use)")
    p.add_argument("--only")
    p.add_argument("--fake", action="store_true", help=_common.argparse.SUPPRESS)
    p = sub.add_parser("run")
    p.add_argument("--out", required=True)
    p.add_argument("--continue-session", action="store_true")
    p.add_argument("--end-only", action="store_true", help="only the end: D9, E4 and E5 (after the last crash)")
    p.add_argument("--fake", action="store_true", help=_common.argparse.SUPPRESS)
    for name in ("status", "clean"):
        sub.add_parser(name).add_argument("--out", required=True)
    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    p.add_argument("--write-rates")
    p = sub.add_parser("features")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    _common.sys.stdout.reconfigure(errors="replace")

    if args.command == "features":
        found = _plan.features()
        legs = _plan.leg_names()
        if args.json:
            print(_common.json.dumps({"packages": found, "legs": sorted(legs)}, indent=1))
        else:
            for package, v in found.items():
                print(f"{package}: {'built' if v['built'] else 'not built'}" + (
                    f" ({'; '.join(v['why'])})" if v["why"] else ""))
            print("harness legs: " + ", ".join(sorted(legs)))
        return 0
    if args.command == "prepare":
        resolved = _plan.prepare(args.out, args.main, smoke=args.smoke)
        print(f"Wrote {args.out}/inputs and plan.resolved.json ({len(resolved['items'])} items).")
        return 0
    if args.command in ("plan", "preflight"):
        out = _common.Path(args.out)
        path = out / "plan.resolved.json"
        if path.exists() and args.command == "plan":
            resolved = _common.json.loads(path.read_text(encoding="utf-8"))
            resolved = _plan.resolve(_plan.load_plan(), out, main=resolved.get("main", args.main), built=_plan.features(),
                               legs=_plan.leg_names(), smoke=args.smoke or resolved.get("smoke"))
        else:
            resolved = _plan.resolve(_plan.load_plan(), out, main=args.main, built=_plan.features(), legs=_plan.leg_names(), smoke=args.smoke)
        window = (_plan.deadline_epoch(args.deadline) - _common.time.time()) if args.deadline else args.budget_h * 3600
        dry = _common._json_cmd([_common.PY, "-m", "decklab.lib.forge", "replay", "--results-dir",
                         str(_common.Path(resolved["main"]) / "decklab" / "data" / "forge" / "results"), "--dry-run", "--json"])
        d1 = next((i for i in resolved["items"] if i["id"] == "D1"), None)
        if dry and d1 is not None and not resolved.get("smoke"):
            d1["est_s"] = max(60.0, (dry.get("estimate_s") or (dry.get("games") or 0) * 0.6) / 2.0)
            print(f"D1 would replay {dry.get('games', 0):,} games in {len(dry.get('planned') or [])} matchups "
                  f"(main's results, today's engine), about {d1['est_s'] / 60:.0f} min warm (estimate).")
        failed = []
        if args.command == "preflight":
            found = _plan.preflight_checks(args.main, smoke=args.smoke)
            for c in found["checks"]:
                mark = {True: "ok  ", False: "FAIL", None: "--  "}[c["ok"]]
                print(f"{mark} {c['name']}" + (f": {c['detail']}" if c.get("detail") not in (None, "") else ""))
            print()
            failed = [c["name"] for c in found["checks"] if c["ok"] is False and c.get("gate")]
        print(_plan.describe_plan(resolved, args.budget_h * 3600, window, json_out=args.json))
        if failed:      # exit 1, so a start command can run supervise only after a clean preflight
            print("\nPreflight FAILED (" + "; ".join(failed) + "): the run would stop at once (MG1). "
                  "Don't start it.", file=_common.sys.stderr)
            return 1
        return 0
    if args.command == "supervise":
        return supervise(args)
    if args.command == "run":
        return _controller.Controller(args.out, args).run()
    if args.command == "status":
        print(_common.status_text(args.out))
        return 0
    if args.command == "clean":
        ended = _processes.clean(args.out)
        print(f"Ended {len(ended)} leftover processes of the run" + (f": {ended}" if ended else "."))
        return 0
    if args.command == "report":
        _common.sys.path.insert(0, str(_common.HERE))
        import overnight_report
        found = overnight_report.write(_common.Path(args.out), rates_path=args.write_rates)
        print(f"{found['verdict']}: see {_common.Path(args.out) / 'REPORT.md'}")
        return 0
    return 1


# Existing imports and patches read through to one authoritative owner.
_OWNERS = {name: part for part, names in (
    (_common, (
        'argparse', 'ast', 'json', 'math', 'os', 're', 'shutil', 'subprocess', 'sys', 'threading', 'time',
        'Path', 'HERE', 'TREE', 'PLAN_FILE', 'LEGS', 'PY', 'PRIORITIES', 'GAME_CHOICES', 'SMOKE_DIV',
        'SMOKE_MIN_GAMES', 'SMOKE_WORKERS', 'STOP_GRACE_S', 'SMOKE_STOP_GRACE_S', 'DRIFT_WARM_GAMES',
        'MAX_RESTARTS', 'OVERRUN', 'SOAK_PROBE_S', 'DRIFT_PROBE_S', 'POOL_POLL_S', 'OWN_PIDS_S',
        'SMOKE_PERIODS', 'START_WAIT_S', 'FILLER_CHUNK_S', 'SERVER_PORT', 'IDLE_PORT', 'EXIT_STOPPED',
        'EXIT_DEADLINE', 'EXIT_FAILFAST', 'EXIT_NEVER_IDLE', 'EXIT_REFUSED', 'EXIT_OWNER_STOP', 'DRILL_EXIT',
        'WRONG_IDENTITY', 'PACKAGES', 'OPTIONAL', 'R_FEATURES', 'CHECKS', 'load_state', 'save_state', 'log',
        '_git', '_sha_file', '_forge_identity', 'identity', 'identity_differs', '_json_cmd', 'status_text',
    )),
    (_processes, (
        'ctypes', 'wintypes', '_k32', '_ntdll', '_BASIC_LIMIT', '_IO_COUNTERS', '_EXTENDED_LIMIT',
        'PROCESS_TERMINATE', 'PROCESS_SET_QUOTA', 'PROCESS_SUSPEND_RESUME',
        'PROCESS_QUERY_LIMITED_INFORMATION', '_SUSPENDED', '_NO_WINDOW', '_BELOW_NORMAL', '_NEW_GROUP', 'Job',
        'creation_time', 'running', '_names', 'job_leftovers', 'keep_awake', 'start_child', 'kill_pid',
        'processes_named', 'command_line', 'Lock', '_listener_pid', 'foreign_services', 'split_answering',
        '_http_ok', '_own_slots', 'held_slots', '_start_foreign_java', '_end_foreign_java', 'clean',
    )),
    (_plan, (
        '_is_stub', '_module_ast', '_functions', '_function_ast', '_assigned', 'features', 'leg_names',
        'load_plan', '_smoke_games', 'resolve', '_ladder_cmds', 'expand', '_games', '_fill', 'item_est',
        '_min_est', 'soak_owed', '_planned_soak', 'upfront', 'reserve', 'fit', 'deadline_epoch',
        'preflight_checks', 'prepare', 'describe_plan', 'B_ANCHORS', 'B_LEGS_DONE', 'rerun_b_anchors',
    )),
    (_controller, (
        'Controller', 'final_probe_outcome', 'copy_snapshot',
    )),
) for name in names if hasattr(part, name)}

__all__ = ["main", "supervise", *(name for name in _OWNERS if not name.startswith("_"))]


def __getattr__(name):
    if name in _OWNERS:
        return getattr(_OWNERS[name], name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(_OWNERS))


class _Facade(types.ModuleType):
    def __setattr__(self, name, value):
        if name in _OWNERS:
            setattr(_OWNERS[name], name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        if name in _OWNERS:
            delattr(_OWNERS[name], name)
        else:
            super().__delattr__(name)


_self_module = _common.sys.modules.get(__name__)
if _self_module is not None:
    _self_module.__class__ = _Facade


if __name__ == "__main__":
    _common.sys.exit(main())
