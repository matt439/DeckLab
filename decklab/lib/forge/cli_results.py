"""Forge CLI workflows for replaying and promoting saved matchup results."""
from contextlib import ExitStack

from . import cli_shared as shared
from . import lifecycle


REPLAY_MATCHUPS = 4             # matchups replay plays at once (--matchups)
REPLAY_BY = "replay"            # a replay run's "by": low priority in the server's pool (contract section 9)
REPLAY_REPORT_S = 10            # seconds between a replay run's progress lines
REPLAY_NOT_READY = "Replay plays only with the card log's engine, and the card log can't be used now."
REPLAY_STILL_STOPPING = "Still stopping: each matchup saves its games once Forge has stopped them..."


class _ReplayLists:
    """Today's lists, by the deck id and version a saved side was last played as (entry(); a
    trial's .dck file by its "file:" id, entry_from_dck()), each read once: None when that id and
    version is gone or can't be read."""

    def __init__(self):
        self._summaries, self._entries = {}, {}

    def entry(self, seen):
        found = (seen.get("id"), seen.get("version"))
        if found not in self._entries:
            self._entries[found] = self._read(*found)
        return self._entries[found]

    def _summary(self, deck_id):
        if deck_id not in self._summaries:
            self._summaries[deck_id] = shared.decks.find_summary(deck_id)
        return self._summaries[deck_id]

    def _read(self, deck_id, version):
        if not isinstance(deck_id, str) or version not in ("target", "owned"):
            return None
        try:
            with shared.lists.one_snapshot():
                return self._read_list(deck_id, version)
        except (shared.decks.DeckNotFound, shared.decks.DeckFileError, OSError, ValueError, shared.ForgeError):
            return None

    def _read_list(self, deck_id, version):
        if deck_id.startswith("file:"):
            path = shared.config.REPO / deck_id[len("file:"):]
            return shared.entry_from_dck(path) if version == "target" and path.is_file() else None
        summary = self._summary(deck_id)
        if summary is None or summary.get("error") or version not in summary["versions"]:
            return None
        return shared.entry(summary["id"], version, summary["title"], shared.decks.engine_kind(summary),
                            shared.decks.load_deck(summary["id"], version))


def _replay_speed(result):
    """(seconds, games): what a Forge process took to play result's games, from its batches'
    wall_s (a cold process's start-up included; a warm pool's batch: its chunks' time), over
    the games of the batches that have one."""
    seconds = games = 0
    for batch in result.get("batches") or []:
        wall, played = batch.get("wall_s"), len(batch.get("games") or [])
        if isinstance(wall, (int, float)) and wall > 0 and played:
            seconds += wall
            games += played
    return seconds, games


def _replay_plan(results_dir, eng):
    """What replay plays with eng (the card log's engine): [{"a", "b" (today's entries of the two
    lists, side 0's first), "format", "key" (eng's result of them), "target" (the most counted
    games of any of their results of other engines), "have" (eng's result's counted games),
    "games" (target - have, 1 or more), "earlier" (those results' keys, newest first),
    "per_game_s" (a Forge process's seconds a game over every saved game of the pair in that
    format, eng's too: _replay_speed; None when none says)}], newest
    group first. A saved result is one of them when both lists are still what its sides were
    last played as (each side's last seen_as id and version gives today's card_sha), and its
    key isn't eng's for today's two lists: their pilots today, so a result a pilot change has
    re-keyed (simulation.json) is replayed too. One pair of lists in one format is one group, whatever
    its earlier results were played with (before wave 2 at any clock, plain Forge, an earlier
    v2 engine)."""
    today = _ReplayLists()
    groups = {}
    for result in shared.saved._stored(results_dir):          # newest first, each with counted games
        sides = result["sides"]
        if result.get("kind") is not None:
            continue                                    # an experiment's arm (wave 3): never replayed
        found = [today.entry(side["seen_as"][-1]) if side.get("seen_as") else None for side in sides]
        if any(e is None or e["card_sha"] != side["card_sha"] for e, side in zip(found, sides)):
            continue                                    # a list that has changed since, or gone
        if shared.engine.key(found[0], found[1], eng) == result["key"]:
            continue                                    # eng's own result, with today's pilots
        if found[0]["kind"] != found[1]["kind"] or shared.lists.fmt_for(found[0]["kind"]) != result["format"]:
            continue
        group = groups.setdefault((tuple(sorted(side["card_sha"] for side in sides)), result["format"]),
                                  {"a": found[0], "b": found[1], "format": result["format"], "earlier": [],
                                   "target": 0, "speed": (0, 0)})
        group["earlier"].append(result["key"])
        group["target"] = max(group["target"], shared.saved._counted(result))
        group["speed"] = tuple(x + y for x, y in zip(group["speed"], _replay_speed(result)))
    plan = []
    for group in groups.values():
        key = shared.engine.key(group["a"], group["b"], eng)
        today = shared.saved.load(key, results_dir) or {}
        have = shared.saved._counted(today)
        seconds, games = (x + y for x, y in zip(group.pop("speed"), _replay_speed(today)))
        if group["target"] > have:
            plan.append(dict(group, key=key, have=have, games=group["target"] - have,
                             per_game_s=round(seconds / games, 3) if games else None))
    return plan


def _replay_estimate(plan, workers):
    """About how long plan's games take to play, in seconds (None for an empty plan, or when
    no saved game of a format in it says how long it took): each matchup's games at its
    per_game_s (one without: its format's average over the plan), workers (forge_workers:
    the pool's) at once. It's the speed the saved games were played at, whatever else the
    PC was doing then, so it's a rough guide."""
    by_format = {}
    for item in plan:
        if item["per_game_s"] is not None:
            total = by_format.setdefault(item["format"], [0.0, 0])
            total[0] += item["per_game_s"] * item["games"]
            total[1] += item["games"]
    seconds = 0.0
    for item in plan:
        rate = item["per_game_s"]
        if rate is None:
            total = by_format.get(item["format"])
            if not total:
                return None
            rate = total[0] / total[1]
        seconds += rate * item["games"]
    return round(seconds / max(1, int(workers))) if plan else None


def _about(seconds):
    """seconds in rough words: "about 40 minutes", "about 3 hours 20 minutes" (to 10 minutes
    from 90 minutes up)."""
    minutes = max(1, round(seconds / 60))
    if minutes < 90:
        return f"about {minutes} minute{'' if minutes == 1 else 's'}"
    hours, rest = divmod(10 * round(minutes / 10), 60)
    return f"about {hours} hour{'' if hours == 1 else 's'}" + (f" {rest} minutes" if rest else "")


def _replay_name(item):
    """A replayed matchup in words: "Gruul Ramp (target) vs Izzet Prowess (owned)", ", Commander"
    after a Commander one."""
    a, b = item["a"], item["b"]
    return (f"{a['title']} ({a['version']}) vs {b['title']} ({b['version']})"
            + (", Commander" if item["format"] == "Commander" else ""))


def _replay_json(item):
    return {"a": {k: item["a"][k] for k in ("id", "version", "title", "card_sha")},
            "b": {k: item["b"][k] for k in ("id", "version", "title", "card_sha")},
            "format": item["format"], "key": item["key"], "games": item["games"], "target": item["target"],
            "have": item["have"], "earlier": item["earlier"], "per_game_s": item["per_game_s"]}


def _replay_time(estimate, workers):
    """The dry run's estimate (_replay_estimate) in a sentence."""
    if estimate is None:
        return "No saved game of these says how long it took, so there's no time estimate."
    return (f"That's {_about(estimate)} with {workers} games at once (forge_workers), going by how long these "
            "matchups' saved games took a Forge process each. It's a rough guide: those runs mostly had fewer games "
            "going at once, and other work on the PC or the server makes it longer.")


def _print_replay_plan(plan, workers):
    """replay --dry-run's lines (upgrade-check prints them too): each matchup and its games, their
    total, and about how long they'd take (_replay_time)."""
    total = sum(item["games"] for item in plan)
    for item in plan:
        print(f"{_replay_name(item)}: {item['games']:,} games (the most with an earlier engine "
              f"{item['target']:,}, with today's {item['have']:,})")
    print(f"{len(plan)} matchup{'' if len(plan) == 1 else 's'} to replay, {total:,} games."
          if plan else "Nothing to replay: every current matchup has as many games with today's engine.")
    if plan:
        print(_replay_time(_replay_estimate(plan, workers), workers))


def _replay(plan, results_dir, local, at_once, log_dir=None, log_every=1):
    """Play plan's games (_replay_plan), at_once matchups at a time, every run in one
    pool.session(local=local) (the server's pool when it's up: replay runs, by REPLAY_BY, are
    low priority there, so the page's runs never wait behind them). Each is
    runner.run(..., exact=True): the games missing, whatever their number. A run of a matchup
    being played already (runner.BUSY) is skipped, never tried again here. Ctrl+C stops every
    run at its next progress call (each raises common.Stopped, and stops as the page's Stop
    does: its finished games are saved), waits for them all, and is raised again, with
    saved_games. Returns {"played": [(item, result)], "busy": [item], "failed": [(item, why)]}.
    log_dir and log_every (wave 3, --logs-dir and --log-every): runner.run's log tee. A run
    stopped otherwise (wave 3: the harness's DECKLAB_STOP_FILE) stops the replay as Ctrl+C
    does: no other matchup starts, and KeyboardInterrupt is raised with saved_games."""
    todo, out = list(plan), {"played": [], "busy": [], "failed": []}
    lock, stopping = shared.threading.Lock(), shared.threading.Event()
    saved_games = [0]
    run_stopped = [False]

    def progress_for(item):
        shown = [shared.time.monotonic()]

        def progress(done, total, detail):
            if stopping.is_set():
                raise shared.common.Stopped("Stopped by Ctrl+C")
            now = shared.time.monotonic()
            if now - shown[0] >= REPLAY_REPORT_S or (done == total and total):
                shown[0] = now
                print(f"  {_replay_name(item)}: {done:,} of {total:,} games", file=shared.sys.stderr)
        return progress

    def worker(session):
        while True:
            with lock:
                if stopping.is_set() or not todo:
                    return
                item = todo.pop(0)
            try:
                result = shared.runner.run(item["a"], item["b"], item["games"], by=REPLAY_BY, progress=progress_for(item),
                                    results_dir=results_dir, pool=session, exact=True, log_dir=log_dir,
                                    log_every=log_every)
            except shared.ForgeError as e:
                with lock:
                    if str(e) == shared.runner.BUSY:
                        out["busy"].append(item)
                    else:
                        out["failed"].append((item, str(e)))
                continue
            except shared.common.STOPS as e:
                with lock:
                    saved_games[0] += getattr(e, "saved_games", None) or 0
                    if not stopping.is_set():       # wave 3: the harness's stop file stopped it
                        run_stopped[0] = True
                        stopping.set()              # so no other matchup starts
                continue
            except Exception as e:      # a bug: logged, and the other matchups go on
                shared.common._log(f"Replaying {_replay_name(item)} failed:\n{shared.traceback.format_exc()}")
                with lock:
                    out["failed"].append((item, f"an error in Deck Lab ({type(e).__name__})"))
                continue
            with lock:
                if result["key"] != item["key"]:
                    out["failed"].append((item, "its games were saved with another engine than the card log's "
                                                "(the card log may have stopped being usable)"))
                else:
                    out["played"].append((item, result))
                saved_games[0] += result["runs"][-1]["played"]

    interrupted = False
    with shared.pool.session(local=local) as session:
        threads = []
        try:
            for i in range(min(at_once, len(plan))):
                threads.append(shared.threading.Thread(target=worker, args=(session,), daemon=True, name=f"replay-{i}"))
                threads[-1].start()
            for thread in threads:
                while thread.is_alive():
                    thread.join(0.2)        # short waits, so Ctrl+C is noticed
        except KeyboardInterrupt:
            interrupted = True
            stopping.set()
            print("\nStopping: each matchup saves the games it finished...", file=shared.sys.stderr)
            # The runs save; another Ctrl+C can't stop that, and says so.
            with shared.common._interrupts_held(note=lambda: print(REPLAY_STILL_STOPPING, file=shared.sys.stderr)):
                for thread in threads:
                    while thread.is_alive():
                        thread.join(0.2)
    if interrupted or run_stopped[0]:
        stop = KeyboardInterrupt()
        stop.saved_games = saved_games[0]
        raise stop
    return out


def _replay_args(sub):
    replay = sub.add_parser("replay", help="play again, with today's engine, every saved matchup whose lists are "
                                           "current")
    replay.add_argument("--results-dir")
    replay.add_argument("--dry-run", action="store_true", help="list the matchups and games, and play nothing")
    replay.add_argument("--local", action="store_true",
                        help="play in a pool of this command's own, not the running server's")
    replay.add_argument("--matchups", type=shared._positive, default=REPLAY_MATCHUPS,
                        help=f"matchups played at once ({REPLAY_MATCHUPS})")
    replay.add_argument("--json", action="store_true")
    shared._log_args(replay)


def _cmd_replay(args):
    """replay (contract section 16): every saved matchup played with another engine than
    today's, whose two lists are both still current, plays with today's engine the games its
    result is short of (_replay_plan: the most any earlier result of the two lists has, less
    today's result's). Run again, it plays only what's still missing. It refuses (exit 1) unless
    runs can use the card log now, so it never fills the plain engine's results. --dry-run
    lists the matchups and games without Java (against the card log's engine as it would be
    built now), with about how long they'd take (_replay_estimate), and plays nothing. Exit
    code 1 when a matchup failed; one playing already is left for next time (listed)."""
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    if args.dry_run:
        plan = _replay_plan(args.results_dir, shared.engine.today(shared.engine.KIND_DECKLAB))
        log = shared.status()["card_log"]
        if not log["ready"]:
            print(f"(The card log can't be used now, so replay would refuse to play: {log['problem']})",
                  file=shared.sys.stderr)
    else:
        setup = shared._setup()
        log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
        eng = shared.engine.current(setup, log)
        if eng["kind"] != shared.engine.KIND_DECKLAB:
            raise shared._CliError(" ".join(filter(None, [REPLAY_NOT_READY, log.get("problem")])))
        plan = _replay_plan(args.results_dir, eng)
    total = sum(item["games"] for item in plan)
    workers = shared.pool._workers_setting()       # the pool's: as many games at once
    estimate = _replay_estimate(plan, workers)
    if args.dry_run or not plan:
        if args.json:
            print(shared.json.dumps({"planned": [_replay_json(item) for item in plan], "games": total,
                              "estimate_s": estimate, "workers": workers}, ensure_ascii=False))
            return 0
        _print_replay_plan(plan, workers)
        return 0
    print(f"Replaying {len(plan)} matchup{'' if len(plan) == 1 else 's'}, {total:,} games, "
          f"{min(args.matchups, len(plan))} at once"
          + (f", {_about(estimate)} at the saved games' speed" if estimate is not None else "") + "...",
          file=shared.sys.stderr)
    out = _replay(plan, args.results_dir, args.local, args.matchups, **shared._log_kwargs(args))
    played = sum(result["runs"][-1]["played"] for _, result in out["played"])
    if args.json:
        print(shared.json.dumps({"planned": [_replay_json(item) for item in plan],
                          "played": [{"key": item["key"], "games": result["runs"][-1]["played"]}
                                     for item, result in out["played"]],
                          "busy": [item["key"] for item in out["busy"]],
                          "failed": [{"key": item["key"], "why": why} for item, why in out["failed"]]},
                         ensure_ascii=False))
    else:
        print(f"Replayed {len(out['played'])} of {len(plan)} matchups: {played:,} games.")
        for item, why in out["failed"]:
            print(f"  failed: {_replay_name(item)}: {why}")
        if out["busy"]:
            print("Still playing, so not replayed now (run replay again once they're done): "
                  + "; ".join(_replay_name(item) for item in out["busy"]) + ".")
    return 1 if out["failed"] else 0


# staged-move and soak-probe: wave 3's package H (sim-wave3-contract.md section 16; the combined
# run's runbook, forge-trial/sim-combined-run.md sections 7.1 and 9.2). The _staged_* and _soak_*
# helpers are H's too.

STAGED_SERVER_UP = ("A Deck Lab server's warm pool is running for this checkout. Stop the server first "
                    "(python -m decklab.lib.homenet stop), then move the staged results.")


def _staged_move_args(sub):
    move = sub.add_parser("staged-move", help="move staged results into the results folder (wave 3, the combined run)")
    move.add_argument("--from", dest="source", required=True, help="the staged results folder")
    move.add_argument("--to", help="the results folder to move them into (the real one by default)")
    move.add_argument("--hold", help="a file of keys (one a line) to leave behind; a missing file holds nothing")
    move.add_argument("--dry-run", action="store_true", help="list what the move would do, and move nothing")
    move.add_argument("--json", action="store_true")


def _staged_held(path):
    """The keys a --hold file lists (one a line; blank lines and # comments skipped), or an
    empty set when there's no such file."""
    if not path:
        return set()
    try:
        text = shared.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    except OSError as e:
        raise shared._CliError(f"The hold file {path} can't be read ({shared._os_reason(e)}).") from None
    return {line.split("#", 1)[0].strip() for line in text.splitlines()} - {""}


class _StagedGone(Exception):
    """A staged result's side whose deck (the id it was last played as) has no pilot today: the
    deck was removed since the run. Rename aliases still identify it. args[0] is the side's index."""


def _staged_today_sides(result):
    """result's two sides with today's pilots (pilots.pilot_for of the deck id and version each was
    last played as) when the stored sides carry one, so a pilot changed since the run makes the
    key stale. Raises _StagedGone when a side's deck can't be found today."""
    from . import pilots
    out = []
    for side in result["sides"]:
        side = dict(side)
        seen = (side.get("seen_as") or [{}])[-1]
        if "pilot" in side and isinstance(seen.get("id"), str):
            try:
                side["pilot"] = pilots.pilot_for(seen["id"], seen.get("version") or "target")
            except NotImplementedError:
                pass
            except (KeyError, ValueError):      # the deck is gone: the file is stale
                raise _StagedGone(len(out)) from None
        out.append(side)
    return out


def _staged_differs(result, eng, sides):
    """The description fields that differ between a stored result and eng with sides (names like
    "overrides", "game_patches", "sides[1].ai_sha"); ["key"] when none can be named."""
    then = result.get("engine") or {}
    now = dict(shared.engine._fields(eng), overrides=shared.engine._matchup_overrides(eng, sides))   # the matchup's, as stored
    found = [field for field in now if then.get(field) != now[field]]
    for i, (old, new) in enumerate(zip(result["sides"], sides)):
        name = shared.engine._profile(new)
        if old.get("ai_sha") is not None and name in eng["ai_sha"] and old.get("ai_sha") != eng["ai_sha"][name]:
            found.append(f"sides[{i}].ai_sha")
        if old.get("pilot") != new.get("pilot"):
            found.append(f"sides[{i}].pilot")
    return found or ["key"]


def _staged_plan(source, target, held, eng):
    """What a move does, file by file: {"move": [{"file", "key"}], "notes": [{"file"}],
    "stale": [{"file", "key", "differs"}], "conflict": [{"file", "key"}], "held": [{"file", "key"}],
    "skipped": [{"file", "why"}]}. Only source's top-level v2 matchup results (no "kind") and its
    field/ notes are ever moved; v1 files, paired/, experiment results and anything else stay."""
    plan = {"move": [], "notes": [], "stale": [], "conflict": [], "held": [], "skipped": []}
    for path in sorted(source.glob("*.json")):
        try:
            data = shared.json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            plan["skipped"].append({"file": path.name, "why": "not readable"})
            continue
        if not shared.saved._is_result(data, path.stem):
            plan["skipped"].append({"file": path.name, "why": "not a saved result"})
        elif data.get("kind") is not None:
            plan["skipped"].append({"file": path.name, "why": f"kind {data['kind']} (never moved)"})
        elif not shared.saved._decklab(data) or shared.engine.kind_of(data) != shared.engine.KIND_DECKLAB:
            plan["skipped"].append({"file": path.name, "why": "v1 or plain Forge (never moved)"})
        elif path.stem in held:
            plan["held"].append({"file": path.name, "key": path.stem})
        else:
            try:
                sides = _staged_today_sides(data)
            except _StagedGone as gone:
                plan["stale"].append({"file": path.name, "key": path.stem, "differs": [f"sides[{gone.args[0]}].pilot"]})
                continue
            today = shared.engine.key(sides[0], sides[1], eng)
            if today != path.stem:
                plan["stale"].append({"file": path.name, "key": path.stem,
                                      "differs": _staged_differs(data, eng, sides)})
            elif (target / path.name).exists():
                plan["conflict"].append({"file": path.name, "key": path.stem})
            else:
                plan["move"].append({"file": path.name, "key": path.stem})
    notes = source / "field"
    if notes.is_dir():
        for path in sorted(notes.glob("*.json")):
            name = f"field/{path.name}"
            if (target / "field" / path.name).exists():
                plan["conflict"].append({"file": name, "key": None})
            else:
                plan["notes"].append({"file": name})
    return plan


def _staged_move_file(source, target, name):
    """Move source/name to target/name: a copy written beside the target and renamed into place,
    then the source removed (so a crash leaves a whole file in one place or the other)."""
    src, dst = source / name, target / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".moving")
    shared.shutil.copyfile(src, tmp)
    tmp.replace(dst)
    src.unlink()


def _cmd_staged_move(args):
    """staged-move (sim-wave3-contract.md section 16; sim-combined-run.md section 9.2): move the
    combined run's staged v2 matchup results and field notes into the real results folder. It
    calls overrides.ensure_deployed first, so keys are worked out with today's engine as runs would
    make it. A stale file (its key isn't today's) stays, named with the field that differs; a
    conflict (a real file with that key) is skipped and listed; --hold's keys stay. --dry-run
    lists exactly what the move does. Exit code 1 when anything was stale or in conflict."""
    source = shared.Path(args.source)
    if not source.is_dir():
        raise shared._CliError(f"There's no folder called {args.source}.")
    target = shared.Path(args.to) if args.to else shared.common._results_dir()
    if source.resolve() == target.resolve():
        raise shared._CliError("The staged folder and the results folder are the same folder.")
    if args.dry_run:
        return _staged_move_claimed(args, source, target)
    with ExitStack() as claims:
        for root in sorted({lifecycle.root_path(source), lifecycle.root_path(target)}, key=str):
            claims.enter_context(lifecycle.maintenance(root))
            claims.enter_context(lifecycle.writer(root))
        return _staged_move_claimed(args, source, target)


def _staged_move_claimed(args, source, target):
    from . import overrides
    overrides.ensure_deployed(shared.common._user_dir())
    eng = shared.engine.today(shared.engine.KIND_DECKLAB)
    plan = _staged_plan(source, target, _staged_held(args.hold), eng)
    if not args.dry_run:
        if any(service.get("checkout") == str(shared.config.REPO) for service in shared.pool.services()):
            raise shared._CliError(STAGED_SERVER_UP)
        # Validate the complete batch before moving its first file. A queued
        # staged import must never restore a removed space's own-only results.
        with lifecycle.writer(target) as claim:
            for item in plan["move"] + plan["notes"]:
                try:
                    data = shared.json.loads((source / item["file"]).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise lifecycle.LifecycleError(
                        "The staged Forge files could not be checked; no files were moved.") from None
                lifecycle.check_decks(claim, lifecycle.references(data))
        target.mkdir(parents=True, exist_ok=True)
        for item in plan["move"] + plan["notes"]:
            _staged_move_file(source, target, item["file"])
    if args.json:
        print(shared.json.dumps(dict(plan, dry_run=bool(args.dry_run), source=str(source), target=str(target)),
                         ensure_ascii=False))
    else:
        verb = "Would move" if args.dry_run else "Moved"
        print(f"{verb} {len(plan['move'])} matchup result{'' if len(plan['move']) == 1 else 's'} and "
              f"{len(plan['notes'])} field note{'' if len(plan['notes']) == 1 else 's'} into {target}.")
        for item in plan["stale"]:
            print(f"  stale, left: {item['file']} ({', '.join(item['differs'])} differs from today's engine)")
        for item in plan["conflict"]:
            print(f"  conflict, left: {item['file']} (the results folder has one already)")
        for item in plan["held"]:
            print(f"  held, left: {item['file']}")
        if plan["skipped"]:
            print(f"  {len(plan['skipped'])} other file{'' if len(plan['skipped']) == 1 else 's'} never moved "
                  "(v1 copies, experiment results, or not results)")
    return 1 if plan["stale"] or plan["conflict"] else 0
