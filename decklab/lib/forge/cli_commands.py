"""Forge CLI commands for individual matchups, saved views and engine settings."""
from . import cli_output as output
from . import cli_shared as shared


# ============================================================ the commands
# Each command is a pair: _<name>_args(sub) adds its parser, _cmd_<name>(args) runs it and
# gives the exit code (COMMANDS). Wave 2's contract says which package owns which pair.

def _status_args(sub):
    sub.add_parser("status", help="is Forge ready, and the card log")


def _cmd_status(args):
    found = shared.status()
    print(shared.json.dumps(found, indent=1))
    if found["ready"]:
        print(f"java: {shared._setup()['java']}")
        log = found["card_log"]
        print("card log: on (per-card stats)" if log["ready"] else f"card log: off. {log['problem']}")
        print(f"warm pool: {output._pool_line()}")
        for line in output._setup_lines(found):
            print(line)
    print(f"build: {_release_advice(found)}")
    return 0 if found["ready"] else 1


def _release_advice(found):
    """status's line on whether the installed Forge is the release this Deck Lab expects
    (simjar.release_check), and how to fix it when it isn't."""
    forge_jar = None
    if found["ready"]:
        try:
            setup = shared._setup()
            forge_jar = shared.Path(setup["forge_dir"]) / setup["jar"]
        except Exception:
            forge_jar = None
    return shared.simjar.release_check(forge_jar)["advice"]


def _audit_args(sub):
    audit = sub.add_parser("audit", help="cards Forge's AI can't play in one list")
    audit.add_argument("deck_id")
    audit.add_argument("--owned", action="store_true")
    audit.add_argument("--json", action="store_true")


def _cmd_audit(args):
    summary, version, kind, sections = shared._cli_list(args.deck_id, args.owned)
    limits = shared.ai_limits(sections, kind)
    if args.json:
        print(shared.json.dumps(limits, indent=1, ensure_ascii=False))
    else:
        output._print_limits(f"{summary['id']} ({version})", limits)
    return 0


def _play_args(sub):
    play = sub.add_parser("play", help="play a matchup")
    play.add_argument("a", help="deck id or .dck file")
    play.add_argument("b", help="deck id or .dck file")
    play.add_argument("--owned-a", action="store_true")
    play.add_argument("--owned-b", action="store_true")
    play.add_argument("--games", type=int, help=f"a set number of games (default {shared.DEFAULT_GAMES})")
    play.add_argument("--until", choices=("assess", "ahead"),
                      help="play in stages until the win rate is known to within ±3 points (assess), or until "
                           "one deck is clearly ahead or they're about even (ahead); not with --games")
    play.add_argument("--max", type=shared._positive,
                      help="with --until: the most games the result may reach (400 to 3,200; for ahead, rounded "
                           "down to a check: 400, 800, 1,600 or 3,200)")
    play.add_argument("--batch", type=shared._positive)
    play.add_argument("--workers", type=shared._positive)
    play.add_argument("--seed-base", type=int)
    play.add_argument("--a-first", action="store_true",
                      help="deck A is Forge's deck 1 first (a new result's first seat block; even batches without "
                           "the card log)")
    play.add_argument("--results-dir")
    play.add_argument("--no-save", action="store_true")
    play.add_argument("--json", action="store_true")
    play.add_argument("--by", default="command line")
    play.add_argument("--local", action="store_true",
                      help="play in a pool of this command's own, not the running server's")
    shared._log_args(play)


def _cmd_play(args):
    if args.until:
        return _cmd_play_until(args)
    if args.max is not None:
        raise shared._CliError("--max goes with --until.")
    if args.games is None:
        args.games = shared.DEFAULT_GAMES
    problem = shared._games_problem(args.games, args.batch)
    if problem:
        raise shared._CliError(problem)
    if args.seed_base is not None and args.seed_base < 0:
        raise shared._CliError("The seed base must be 0 or more (--seed-base).")
    a, b = shared._cli_entry(args.a, args.owned_a), shared._cli_entry(args.b, args.owned_b)
    shown = [0.0, None, None]   # when the last line was printed, its numbers, the fallback said

    def report(done, total, detail):
        if detail.get("fallback") and detail["fallback"] != shown[2]:
            shown[2] = detail["fallback"]       # the warm workers couldn't start (pool.FALLBACK)
            print(f"  {detail['fallback']}", file=shared.sys.stderr)
        numbers = (done, detail["failed_batches"], detail.get("waiting"))
        if numbers != shown[1] and (shared.time.monotonic() - shown[0] >= 2 or done == total):
            shown[:2] = [shared.time.monotonic(), numbers]
            if detail.get("waiting"):       # other runs hold every slot or worker (slots.WAITING, pool.QUEUED)
                print(f"  {detail['waiting']}", file=shared.sys.stderr)
                return
            first = 0 if a["card_sha"] <= b["card_sha"] else 1
            wa, wb = detail["wins"][first], detail["wins"][1 - first]
            rate = f", {detail['games_per_min']:.0f} games a minute" if detail["games_per_min"] else ""
            print(f"  {done}/{total} games: A {wa}, B {wb}, other {detail['other']}{rate}"
                  + (f", {detail['failed_batches']} batches failed" if detail["failed_batches"] else ""),
                  file=shared.sys.stderr)

    print(f"A: {a['title']} ({a['version']}, {a['card_count']} cards, {a['card_sha'][:12]})\n"
          f"B: {b['title']} ({b['version']}, {b['card_count']} cards, {b['card_sha'][:12]})", file=shared.sys.stderr)
    result = shared.run(a, b, args.games, by=args.by, progress=report, results_dir=args.results_dir,
                 workers=args.workers, batch=args.batch, seed_base=args.seed_base, a_first=args.a_first,
                 save=not args.no_save, local=args.local, **shared._log_options(args))
    shown_view = shared.view(result, a["card_sha"])
    if args.json:
        print(shared.json.dumps({"view": shown_view, "result": result}, ensure_ascii=False))
        return 0
    output._print_play(a, b, result, shown_view)
    return 0


def _cmd_play_until(args):
    """play --until assess|ahead: an adaptive run (adaptive.run_adaptive), printing each stage's
    plan and each look as it's made."""
    from . import adaptive, seqstats         # they come after this part
    for flag, given in (("--games", args.games is not None), ("--batch", args.batch is not None),
                        ("--workers", args.workers is not None), ("--a-first", args.a_first),
                        ("--no-save", args.no_save)):
        if given:
            raise shared._CliError(f"{flag} doesn't go with --until: an adaptive run plans its own games and saves them.")
    if args.seed_base is not None and args.seed_base < 0:
        raise shared._CliError("The seed base must be 0 or more (--seed-base).")
    most = args.max if args.max is not None else seqstats.CAP
    if not seqstats.ASSESS_PILOT <= most <= seqstats.CAP:
        raise shared._CliError(f"--max must be from {seqstats.ASSESS_PILOT:,} to {seqstats.CAP:,} games.")
    if args.until == "ahead":
        most = max(look for look in seqstats.HP_LOOKS if look <= most)
    a, b = shared._cli_entry(args.a, args.owned_a), shared._cli_entry(args.b, args.owned_b)
    first = 0 if a["card_sha"] <= b["card_sha"] else 1          # a's stored side (card_sha order)
    shown = {"at": 0.0, "numbers": None, "stage": None, "looks": 0, "played": False}

    def look_lines(looks, next_look=None, leader=""):
        for look in looks[shown["looks"]:]:
            print("  " + output._look_line(look, next_look, leader), file=shared.sys.stderr)
        shown["looks"] = len(looks)

    def report(done, total, detail):
        shown["played"] = True
        plan = detail.get("plan") or {}
        look_lines(detail.get("looks") or [], plan.get("next_look"))
        if plan.get("stage") != shown["stage"]:
            shown["stage"] = plan.get("stage")
            target = plan.get("next_look") or plan.get("planned") or 0
            print(f"  stage {plan.get('stage')}: playing to {target:,} games", file=shared.sys.stderr)
        numbers = (done, detail.get("failed_batches"), detail.get("waiting"))
        if numbers != shown["numbers"] and (shared.time.monotonic() - shown["at"] >= 2 or done == total):
            shown["at"], shown["numbers"] = shared.time.monotonic(), numbers
            if detail.get("waiting"):
                print(f"  {detail['waiting']}", file=shared.sys.stderr)
                return
            wins = detail.get("wins") or [0, 0]
            found = (detail.get("range") or [None, None])[first]
            live = f", live range {output._pct(found['low'], 0)}-{output._pct(found['high'], 0)}" if found else ""
            print(f"  {done}/{total} new games: A {wins[first]}, B {wins[1 - first]}, other {detail.get('other', 0)}"
                  f"{live}", file=shared.sys.stderr)

    print(f"A: {a['title']} ({a['version']}, {a['card_count']} cards, {a['card_sha'][:12]})\n"
          f"B: {b['title']} ({b['version']}, {b['card_count']} cards, {b['card_sha'][:12]})\n"
          f"{output._until_words(args.until, most)}", file=shared.sys.stderr)
    result = adaptive.run_adaptive(a, b, args.until, by=args.by, progress=report, results_dir=args.results_dir,
                                   local=args.local, seed_base=args.seed_base, max_games=most,
                                   **shared._log_options(args))
    shown_view = shared.view(result, a["card_sha"])
    summary = shown_view.get("adaptive_last")
    looked_only = (not shown["played"] and summary is not None and not summary.get("stages")
                   and summary.get("looks") and summary.get("games_before") == summary.get("games_after")
                   and summary.get("mode") == args.until and summary.get("max_games") == most)
    if summary is not None and (shown["played"] or looked_only):
        lead = shown_view.get("lead") or {}
        leader = (a["title"], b["title"])[lead["side"]] if lead.get("side") in (0, 1) else ""
        look_lines(summary.get("looks") or [], leader=leader)
    if args.json:
        print(shared.json.dumps({"view": shown_view, "result": result}, ensure_ascii=False))
        return 0
    if not shown["played"]:
        print(output._nothing_played_words(args.until, most, shown_view, looked_only), file=shared.sys.stderr)
    output._print_play(a, b, result, shown_view)
    return 0


def _list_args(sub):
    listing = sub.add_parser("list", help="saved results (those of another engine than today's are marked)")
    listing.add_argument("--results-dir")


def _cmd_list(args):
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    items = shared.results(args.results_dir)
    for line in output._setup_lines():         # wave 3: the overrides and the pilots, first
        print(line)
    for item in items:
        a, b = item["sides"]
        print(f"{item['updated']}  {item['games']:>5} games  {output._pct(item['winrate']['value']):>6}  "
              f"{a['id']} ({a['version']}) vs {b['id']} ({b['version']})  by {item['by']}"
              f"{output._engine_mark(item.get('engine'))}")
    if not items:
        print("No saved matchups.")
    elif any(item.get("engine") and item["engine"].get("current") is False for item in items):
        print("Results marked \"earlier engine\" were played with another engine than today's: more games of their "
              "lists start a new result (python -m decklab.lib.forge replay plays them again).")
    return 0


def _cards_args(sub):
    card_table = sub.add_parser("cards", help="how a list's cards played in its saved matchups")
    card_table.add_argument("deck_id")
    card_table.add_argument("--owned", action="store_true")
    card_table.add_argument("--results-dir")
    card_table.add_argument("--json", action="store_true")


def _cmd_cards(args):
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    summary, version, kind, sections = shared._cli_list(args.deck_id, args.owned)
    stats = shared.cardstats.list_cards(sections, kind, results_dir=args.results_dir)
    if args.json:
        print(shared.json.dumps(stats, indent=1, ensure_ascii=False))
    elif stats is None:
        print("No card data yet.")
    else:
        output._print_cards(f"{summary['id']} ({version})", stats)
    return 0


def _slots_args(sub):
    slot_list = sub.add_parser("slots", help="Forge processes running on this PC, from every Deck Lab checkout")
    slot_list.add_argument("--json", action="store_true")


def _cmd_slots(args):
    try:
        found = shared.slots.status()
    except ValueError:
        raise shared._CliError("config.json's forge_workers must be a whole number of 1 or more.") from None
    if args.json:
        print(shared.json.dumps(found, indent=1, ensure_ascii=False))
    else:
        output._print_slots(found)
    return 0


def _pool_args(sub):
    """pool: the running server's warm pool (pool.services(), pool.service_status())."""
    listing = sub.add_parser("pool", help="the running server's warm pool")
    listing.add_argument("--json", action="store_true")


NO_POOL = "No Deck Lab server is running on this PC, so there's no warm pool to show."


def _cmd_pool(args):
    found = shared.pool.services()
    states = [(service, shared.pool.service_status(service)) for service in found]
    if args.json:
        print(shared.json.dumps([{"pid": service["pid"], "port": service["port"], "checkout": service.get("checkout"),
                           "status": state} for service, state in states], indent=1, ensure_ascii=False))
        return 0
    if not states:
        print(NO_POOL)
        return 0
    for service, state in states:
        print(f"The server's warm pool (process {service['pid']}, checkout {service.get('checkout')}):")
        if state is None:
            print("  it didn't answer")
            continue
        print(f"  {output._pool_words(state)}")
        for worker in state["workers"]:
            parts = [worker["state"] + (" (one-shot)" if worker["oneshot"] else ""),
                     worker["slot"] is not None and f"slot {worker['slot']}" + (", pinned" if worker["pinned"] else ""),
                     f"{worker['games']:,} games",
                     worker["heap_mb"] is not None and f"heap {worker['heap_mb']} MB",
                     worker["idle_s"] is not None and f"idle {worker['idle_s']} s"]
            print(f"  process {worker['pid']}: " + ", ".join(part for part in parts if part))
    return 0


def _pilots_args(sub):
    found = sub.add_parser("pilots", help="each list's AI pilot, and the profiles and switches available")
    found.add_argument("--check", action="store_true", help="exit code 1 when decklab/simulation.json has a bad entry")
    found.add_argument("--json", action="store_true")


def _installed_fork_switches():
    """The fork's AI switches in the installed Forge's jar (config's forge_dir), or None when
    there's no Forge jar there."""
    try:
        forge_dir = shared.Path(shared.common._settings()["forge_dir"])
        name, _ = shared.install._find_jar(forge_dir)
    except Exception:           # a bad config.json: as if Forge weren't found
        return None
    return None if name is None else shared.simjar.fork_switches(forge_dir / name)


def _cmd_pilots(args):
    data = shared.pilots.load()
    known = shared.pilots.available()
    if args.json:
        print(shared.json.dumps({"default": data["default"], "lists": data["lists"], "available": known,
                          "problems": data["problems"]}, indent=1, ensure_ascii=False))
    else:
        print(f"default pilot: {shared.pilots.words(data['default']) or 'Forge AI with its Default profile'}")
        for name, pilot in sorted(data["lists"].items()):
            print(f"{name}: {shared.pilots.words(pilot) or 'Forge AI with its Default profile'}")
        if not data["lists"]:
            print("No list has a pilot of its own.")
        mine = set(shared.pilots.deck_lab_profiles())
        print("profiles: " + ", ".join(f"{p} (Deck Lab's)" if p in mine else p for p in known["profiles"]))
        print("switches: " + (", ".join(f"{s} ({shared.pilots.SWITCH_WORDS.get(s, s)})" for s in known["switches"])
                              or "none (the card log's jar has none)"))
        fork = _installed_fork_switches()
        print("this Forge build's AI switches: " + (", ".join(fork) if fork else "none")
              if fork is not None else "this Forge build's AI switches: can't be told (Forge isn't found)")
        for problem in data["problems"]:
            print(f"! {problem}")
    return 1 if args.check and data["problems"] else 0


OVERRIDES_ACTIONS = ("list", "check", "make", "deploy")


def _overrides_args(sub):
    found = sub.add_parser("overrides", help="Deck Lab's card-script overrides: list, check, make, deploy")
    found.add_argument("action", nargs="?", choices=OVERRIDES_ACTIONS, default="list")
    found.add_argument("--set", dest="set_name", help="make: only this set")
    found.add_argument("--user-dir", help="deploy: this Forge user folder instead of Deck Lab's own")
    found.add_argument("--sets", help="deploy: these sets (comma-separated) instead of the folder's own")
    found.add_argument("--json", action="store_true")


def _cmd_overrides(args):
    try:
        if args.action == "list":
            return _overrides_list(args)
        if args.action == "check":
            staged = getattr(args, "forge_dir", None)      # upgrade-check --dir's staged build (E11-S45)
            problems = shared.overrides.check() if staged is None else shared.overrides.check(staged)
            if args.json:
                print(shared.json.dumps({"problems": problems}, indent=1, ensure_ascii=False))
            else:
                for problem in problems:
                    print(f"! {problem}")
                if not problems:
                    print("Every override is Forge's script with its edits, made from this Forge's scripts.")
            return 1 if problems else 0
        if args.action == "make":
            made = shared.overrides.make([args.set_name] if args.set_name else None)
            if args.json:
                print(shared.json.dumps(made, indent=1, ensure_ascii=False))
            else:
                for name, files in made.items():
                    print(f"{name}: {', '.join(files)}")
            return 0
        performance_mode = shared.install._knobs(shared.common._settings())[0]
        sets = [s.strip() for s in (args.sets or "").split(",") if s.strip()]
        if sets and not args.user_dir:
            # Section 6.2: the real run folder holds only the adopted sets (a run playing there
            # would echo another overrides hash and fail its chunks), so named sets go into their
            # own experiment folder, as an override_sets run plays them.
            user_dir = shared.overrides.user_dir_for(sets, performance_mode=performance_mode)
        else:
            user_dir = shared.Path(args.user_dir) if args.user_dir else shared.install._run_user_dir(performance_mode)
        if sets and shared._same_folder(user_dir, shared.common._user_dir()):
            raise shared._CliError("Deck Lab's own user folder holds only the adopted override sets: "
                            "leave out --user-dir to deploy these sets into their own folder.")
        if sets:
            found = shared.overrides.deploy(user_dir, sets)
        else:
            found = shared.overrides.ensure_deployed(user_dir)
            found = {**shared.overrides.status(user_dir), "hash": found["hash"]}
        found = {"user_dir": str(user_dir), **found}
        if args.json:
            print(shared.json.dumps(found, indent=1, ensure_ascii=False))
        else:
            print(f"folder: {user_dir}")
            print(f"deployed: {', '.join(found['deployed']) or 'none'}")
            for card in found.get("stale") or []:
                print(f"! {card}: doesn't fit this Forge's script, so it isn't used")
            for card in found.get("unknown") or []:
                print(f"! {card}: Forge's script can't be read, so the folder was left as it was")
            print(f"hash: {found['hash']}")
        return 0
    except ValueError as e:
        raise shared._CliError(str(e)) from None


def _overrides_list(args):
    """overrides list: each set (adopted or experiment) with its cards, and what's deployed in
    Deck Lab's own user folder."""
    data = shared.overrides.load_sets()
    stale = set(shared.overrides.stale())
    real = shared.install._run_user_dir(shared.install._knobs(shared.common._settings())[0])
    shown = shared.overrides.status(real)
    if args.json:
        print(shared.json.dumps({"sets": data["sets"], "deployed": shown}, indent=1, ensure_ascii=False))
        return 0
    for name, found in data["sets"].items():
        cards = [info["card"] + (" (doesn't fit this Forge)" if found["status"] == "adopted" and info["card"] in stale
                                 else "") for info in found["files"].values()]
        print(f"{name} [{found['status']}]: {', '.join(cards) or 'no files'}")
    print(f"deployed in {real}: {', '.join(shown['deployed']) or 'none'} (hash {shown['hash']})")
    return 0
