"""Forge CLI field runs, paired deck variants and controlled experiments."""
from . import cli_output as output
from . import cli_results as results
from . import cli_shared as shared


FIELD_REPORT_S = 5              # seconds between a field run's progress lines


def _field_budget(text):
    """argparse's type for field --budget: quick, standard, thorough or a number of games per
    opponent (1 or more)."""
    from . import field         # wave 3's part (forge-trial/sim-wave3-contract.md section 10)
    if text in field.BUDGETS:
        return text
    if text.isascii() and text.isdigit() and int(text) >= 1:
        return int(text)
    raise shared.argparse.ArgumentTypeError(f"must be {', '.join(field.BUDGETS)} or a number of games, not {text!r}")


def _field_args(sub):
    """field (contract section 10.5): a deck against the current decks of its format."""
    play = sub.add_parser("field", help="a deck against the field: the current decks of its format (wave 3)")
    play.add_argument("deck", help="deck id")
    play.add_argument("--owned", action="store_true", help="the deck's owned-only list")
    size = play.add_mutually_exclusive_group()
    size.add_argument("--budget", type=_field_budget, default="standard",
                      help="quick (200 games a deck), standard (about 400), thorough (about 800) or a number of "
                           "games a deck (default standard)")
    size.add_argument("--fixed", type=shared._positive, help="top every opponent up to N games, without APT (not with "
                                                      "--budget)")
    play.add_argument("--opponents", help="only these field lists: deck ids, comma-separated, each with an "
                                          "optional @target or @owned")
    play.add_argument("--show", action="store_true", help="print the field view and play nothing")
    play.add_argument("--dry-run", action="store_true", help="print the plan and its time, and play nothing")
    play.add_argument("--json", action="store_true")
    play.add_argument("--local", action="store_true",
                      help="play in a pool of this command's own, not the running server's")
    play.add_argument("--results-dir")
    play.add_argument("--seed-base", type=int)
    play.add_argument("--inflight", type=shared._positive, help="pair runs at once (config forge_field_inflight)")
    play.add_argument("--by", default="command line")
    shared._log_args(play)


def _field_rate(rate):
    return f"{output._pct(rate['value'])} ({output._pct(rate['low'], 0)}-{output._pct(rate['high'], 0)})" if rate else "-"


def _field_verdict(lead):
    """A field row's lead verdict in a word or two, from the deck's point of view (side 0 is the
    deck, 1 the opponent), as the page's fvVerdict says it."""
    if lead.get("side") == 1:
        return "slightly behind" if lead["verdict"] == "slightly_ahead" else "behind"
    return lead["verdict"].replace("_", " ")


def _print_field(found):
    """field --show's lines (field.view's answer)."""
    deck = found["deck"]
    cover = found["coverage"]
    print(f"{deck['title']} ({deck['version']}) against the {found['format']} field: "
          f"{cover['with_floor']} of {cover['of']} opponents with 200+ games")
    average = found.get("average")
    if average:
        partial = f", based on {average['counted']} of {average['of']} decks" if average.get("partial") else ""
        print(f"  against an average house deck: {_field_rate(average)}{partial}")
    rating = found.get("rating")
    if rating:
        print(f"  rating: {output._pct(rating['value'])} against an average field deck; rank {rating['rank']} of "
              f"{rating['of']} (likely {rating['rank_low']}-{rating['rank_high']}); going first is worth about "
              f"{rating['h_points']:.1f} points here")
    for o in found["opponents"]:
        flag = (o.get("residual") or {}).get("flag")
        extra = [f"{o['games']:,} games"]
        if o.get("pred") is not None:
            extra.append(f"rating predicts {output._pct(o['pred'], 0)}")
        if flag:
            extra.append(f"{flag} against")
        if o.get("lead"):
            extra.append(_field_verdict(o["lead"]))
        if o.get("not_meaningful"):
            extra.append("not meaningful")
        if o.get("problem"):
            extra.append(o["problem"])
        print(f"  {o['title']} ({o['version']}): {_field_rate(o['rate'])}; " + "; ".join(extra))
    for line in found.get("notes") or []:
        print(f"  ! {line}")
    print("  ! A rating predicts a matchup it hasn't seen only to about +-8 points of win rate: the rows are the "
          "real answer.")


def _field_minutes(estimate, pairs_games, results_dir):
    """estimate.minutes for a field plan, with the pair rates of results_dir when it takes one
    (package A's minutes(pairs_games, results_dir=None); the base's takes only the pairs)."""
    import inspect
    if results_dir is not None:
        try:
            takes = "results_dir" in inspect.signature(estimate.minutes).parameters
        except (TypeError, ValueError):
            takes = False
        if takes:
            return estimate.minutes(pairs_games, results_dir=results_dir)
    return estimate.minutes(pairs_games)


def _cmd_field(args):
    """field (contract section 10.5): --show prints the field view, --dry-run the plan and its time;
    otherwise it plays the field run (field.run_field) and prints the view after it. Ctrl+C stops
    every pair run, each keeping its finished games. Exit code 1 when an opponent couldn't be
    played."""
    from . import estimate, field       # wave 3's parts
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    if args.seed_base is not None and args.seed_base < 0:
        raise shared._CliError("The seed base must be 0 or more (--seed-base).")
    if args.deck.lower().endswith(".dck"):
        raise shared._CliError("field plays a deck of the library: give its deck id.")
    a = shared._cli_entry(args.deck, args.owned)
    budget = f"fixed:{args.fixed}" if args.fixed else args.budget
    names = [n.strip() for n in args.opponents.split(",") if n.strip()] if args.opponents else None
    try:
        if args.show:
            found = field.view(a, results_dir=args.results_dir)
            if names is not None:
                keep = {(o["id"], o["version"]) for o in field.opponents(a, names)}
                found["opponents"] = [o for o in found["opponents"] if (o["id"], o["version"]) in keep]
            if args.json:
                print(shared.json.dumps(found, ensure_ascii=False))
            else:
                _print_field(found)
            return 0
        planned = field.plan(a, budget, results_dir=args.results_dir, opponents=names)
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    if not planned["pairs"]:
        raise shared._CliError(field.NO_OPPONENTS.format(fmt=shared.lists.fmt_for(a["kind"])))
    minutes = _field_minutes(estimate, [(a, p["opponent"], p["games"]) for p in planned["pairs"] if p["games"] > 0],
                             args.results_dir)
    if args.dry_run:
        if args.json:
            print(shared.json.dumps({"budget": planned["budget"], "per_opponent": planned["per_opponent"],
                              "new_games": planned["new_games"], "allocate": planned["allocate"],
                              "minutes": list(minutes) if minutes else None,
                              "pairs": [{"id": p["opponent"]["id"], "version": p["opponent"]["version"],
                                         "title": p["opponent"]["title"], "key": p["key"], "have": p["have"],
                                         "floor": p["floor"], "games": p["games"]} for p in planned["pairs"]]},
                             ensure_ascii=False))
            return 0
        for p in planned["pairs"]:
            print(f"{p['opponent']['title']} ({p['opponent']['version']}): has {p['have']:,} games; floor "
                  f"{p['floor']:,}, about {p['games']:,} in all")
        print(f"{len(planned['pairs'])} opponents, about {planned['new_games']:,} new games "
              f"({planned['allocate']:,} of them shared out by APT as the games come in)"
              + (f", about {minutes[0]:.0f}-{minutes[1]:.0f} minutes" if minutes else "") + ".")
        return 0
    shown = [0.0]

    def report(done, total, detail):
        now = shared.time.monotonic()
        if now - shown[0] >= FIELD_REPORT_S or (total and done == total):
            shown[0] = now
            playing = [p["opponent"]["title"] for p in detail["pairs"].values() if p.get("playing")]
            print(f"  {done:,} of {total:,} games ({detail['phase']})"
                  + (f"; playing {', '.join(playing)}" if playing else ""), file=shared.sys.stderr)

    print(f"Playing {a['title']} ({a['version']}) against {len(planned['pairs'])} decks of the "
          f"{shared.lists.fmt_for(a['kind'])} field, budget {budget}...", file=shared.sys.stderr)
    log = {"log_dir": args.logs_dir, "log_every": args.log_every} if getattr(args, "logs_dir", None) else {}
    try:
        note = field.run_field(a, budget, by=args.by, progress=report, results_dir=args.results_dir,
                               local=args.local, seed_base=args.seed_base, inflight=args.inflight,
                               opponents=names, **log)
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    found = field.view(a, results_dir=args.results_dir)
    if args.json:
        print(shared.json.dumps({"note": note, "view": found}, ensure_ascii=False))
    else:
        print(f"Played {note['played']:,} games in {note['wall_s']:.0f} s.")
        for key, why in (note.get("dropped") or {}).items():
            print(f"  ! {why} ({key[:12]})")
        _print_field(found)
    return 1 if note.get("dropped") else 0


def _variant_args(sub):
    variant = sub.add_parser("variant", help="test a change to a deck on its own games (wave 3)")
    variant.add_argument("deck", help="the deck id whose list is changed")
    variant.add_argument("--owned", action="store_true", help="change the owned-only list")
    variant.add_argument("--remove", action="append", default=[], metavar='"N Name"',
                         help="copies to take out of the deck (repeat it)")
    variant.add_argument("--add", action="append", default=[], metavar='"N Name"',
                         help="copies to put in (repeat it)")
    variant.add_argument("--list", dest="list_file", metavar="FILE",
                         help="the changed list as a decklist file (instead of --remove and --add)")
    variant.add_argument("--against", metavar="DECK", help="the deck to test against")
    variant.add_argument("--owned-b", action="store_true", help="the --against deck's owned-only list")
    variant.add_argument("--field", action="store_true", help="test against the field of the deck's format")
    variant.add_argument("--opponents", help="limit the field to these decks: deck ids (id@version), with commas")
    variant.add_argument("--until", choices=("ahead",), help="play until the difference is clear (the default)")
    variant.add_argument("--games", type=shared._positive, help="play this many games a deck, with one look at the end")
    variant.add_argument("--quick", action="store_true", help="a quick look: 200 games a deck")
    variant.add_argument("--more", metavar="TEST", help="play more of this test (its id): to the next look, then on")
    variant.add_argument("--json", action="store_true",
                         help="print the test's view (variants.view: the summary and each opponent's paired numbers)")
    variant.add_argument("--local", action="store_true",
                         help="play in a pool of this command's own, not the running server's")
    variant.add_argument("--results-dir")
    variant.add_argument("--by", default="command line")
    shared._log_args(variant)


def _variant_cards(base, args):
    """The changed list's {"Commander", "Main"} from --list, or the base's with --remove and --add."""
    if args.list_file:
        if args.remove or args.add:
            raise shared._CliError("Give the change as --list or as --remove and --add, not both.")
        try:
            text = shared.Path(args.list_file).read_text(encoding="utf-8")
        except OSError as e:
            raise shared._CliError(f"The list file {args.list_file} can't be read ({shared._os_reason(e)}).") from None
        try:
            sections = shared.decks.parse_decklist(text)
        except shared.decks.DeckFileError as e:
            raise shared._CliError(f"The list file {args.list_file} can't be read: {e}") from None
        return shared.lists._section_cards(sections)
    if not args.remove and not args.add:
        raise shared._CliError('Say what changes: --remove "N Name" and --add "N Name", or --list FILE.')
    cards_ = {"Commander": [list(x) for x in base["cards"].get("Commander", [])],
              "Main": [list(x) for x in base["cards"].get("Main", [])]}

    def parsed(text):
        m = shared.re.fullmatch(r"\s*(\d+)\s+(.+?)\s*", text)
        if not m or int(m[1]) < 1:
            raise shared._CliError(f'{text!r} isn\'t "N Name" (copies, then the card\'s name).')
        return int(m[1]), m[2]

    for text in args.remove:
        qty, name = parsed(text)
        lines_ = [line for line in cards_["Main"] if line[1].casefold() == name.casefold()]
        have = sum(line[0] for line in lines_)
        if have < qty:
            raise shared._CliError(f"The deck has {have} {name}, so {qty} can't come out.")
        for line in lines_:
            take = min(qty, line[0])
            line[0] -= take
            qty -= take
        cards_["Main"] = [line for line in cards_["Main"] if line[0] > 0]
    for text in args.add:
        qty, name = parsed(text)
        cards_["Main"].append([qty, name])
    return cards_


def _cmd_variant(args):
    from . import deck_identity, variants
    if args.field and args.against:
        raise shared._CliError("Test against one deck (--against) or the field (--field), not both.")
    if args.more is None and not args.field and not args.against:
        raise shared._CliError("Say what to test against: --against DECK or --field.")
    if args.opponents and not args.field:
        raise shared._CliError("--opponents limits the field: use it with --field.")
    if sum(bool(x) for x in (args.until, args.games, args.quick)) > 1:
        raise shared._CliError("Choose one of --until ahead, --games N and --quick.")
    mode = "quick" if args.quick else args.games if args.games else "ahead"
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    base = shared._cli_entry(args.deck, args.owned)
    extend = None
    if args.more:
        summary = variants.load_summary(args.more, args.results_dir)
        if summary is None:
            raise shared._CliError(f"There's no test {args.more} in the results folder.")
        if not deck_identity.same(summary["base"]["id"], base["id"]) or \
                summary["base"]["version"] != base["version"]:
            raise shared._CliError(f"Test {args.more[:12]} isn't of {args.deck}'s {base['version']} list.")
        cards_ = summary["variant"].get("cards")
        against = summary["against"]
        against = "field" if isinstance(against, str) else shared._cli_entry(against["id"], against["version"] == "owned")
        extend, mode = args.more, summary.get("mode")
        opponents = summary.get("limited")
    else:
        cards_ = _variant_cards(base, args)
        against = "field" if args.field else shared._cli_entry(args.against, args.owned_b)
        opponents = [o.strip() for o in args.opponents.split(",") if o.strip()] if args.opponents else None
    try:
        variant = variants.variant_entry(base, cards_)
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    words = ", ".join([f"-{q} {n}" for q, n in variant["changes"]["remove"]]
                      + [f"+{q} {n}" for q, n in variant["changes"]["add"]])
    print(f"Testing {words} in {base['title']} ({base['version']}) against "
          f"{'the field' if against == 'field' else against['title']}", file=shared.sys.stderr)
    shown = [0.0, None]

    def report(done, total, detail):
        detail = detail or {}
        if done != shown[1] and (shared.time.monotonic() - shown[0] >= 2 or done == total):
            shown[:] = [shared.time.monotonic(), done]
            look = f", next look at {detail['next_look']:,} games a deck" if detail.get("next_look") else ""
            print(f"  {done:,} of up to {total:,} games{look}", file=shared.sys.stderr)

    log = {}
    if getattr(args, "logs_dir", None) is not None:
        log = {"log_dir": args.logs_dir, "log_every": getattr(args, "log_every", None) or 1}
    try:
        summary = variants.run_test(base, cards_, against, mode, by=args.by, progress=report,
                                    results_dir=args.results_dir, local=args.local, opponents=opponents,
                                    extend=extend, **log)
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    found = variants.view(summary["test"], args.results_dir) or {"test": summary}
    if args.json:
        print(shared.json.dumps(found, ensure_ascii=False))
        return 0
    _print_variant(found)
    return 0


def _print_variant(found):
    """variant's lines for a finished test: the verdict, each opponent's paired numbers, its looks and
    the test's id."""
    summary = found["test"]
    print(found.get("words") or "No verdict yet.")
    for row in found.get("opponents") or []:
        paired = row.get("paired") or {}
        name = row.get("title") or row.get("id")
        if row.get("dropped"):
            print(f"  {name}: {row['dropped']}")
            continue
        if paired.get("delta") is None:
            print(f"  {name}: {row.get('games', 0):,} paired games, no difference yet")
            continue
        same = f", played out the same in {output._pct(paired['same'], 0)}" if paired.get("same") is not None else ""
        rho = f", correlation {paired['rho']:.2f}" if paired.get("rho") is not None else ""
        print(f"  {name}: {100 * paired['delta']:+.1f} points ({100 * paired['low']:+.1f} to "
              f"{100 * paired['high']:+.1f}) over {paired.get('n', 0):,} paired games{same}{rho}")
    for look in summary.get("looks") or []:
        state = "stopped" if look.get("stopped") else "interim" if look.get("interim") else "look"
        print(f"  {state} at {look['games_per_opponent']:,} games a deck: {look.get('decision')}"
              + (f" (z {look['z']:.2f}, bound {look['bound']})" if look.get("z") is not None else ""))
    mismatch = summary.get("starter_mismatch") or {}
    if mismatch.get("of") and mismatch.get("games", 0) > 0.01 * mismatch["of"]:
        print("  ! The two versions didn't get the same games; the comparison is weaker than it should be "
              f"({mismatch['games']} of {mismatch['of']} games had another starter).")
    print(f"  test {summary['test']}")


def _experiment_args(sub):
    exp = sub.add_parser("experiment", help="play an experiment's arms against its control (wave 3)")
    exp.add_argument("spec", help="the experiment's spec, a JSON file (sim-wave3-contract.md section 12.1)")
    exp.add_argument("--results-dir", help="where its results go (default <data>/forge/experiments/<name>/)")
    exp.add_argument("--control-dir", help="a results folder whose current results are the controls")
    exp.add_argument("--control-logs-dir", help="the tee'd logs of --control-dir's results")
    exp.add_argument("--only", help="the arms to play, comma-separated")
    exp.add_argument("--games", type=shared._positive, help="games a pair (default: the spec's)")
    exp.add_argument("--dry-run", action="store_true", help="list the games each arm and control would play")
    exp.add_argument("--json", action="store_true")
    exp.add_argument("--local", action="store_true",
                     help="play in pools of this command's own, not the running server's")
    exp.add_argument("--report", help="also write report.md's text to this file")
    exp.add_argument("--by", default="command line")
    shared._log_args(exp)
    # --logs-dir and --log-every are the log tee's (R's _log_args); until it adds them, here.
    known = {option for action in exp._actions for option in action.option_strings}
    if "--logs-dir" not in known:
        exp.add_argument("--logs-dir", help="where the tee'd logs go (default <results-dir>/logs)")
    if "--log-every" not in known:
        exp.add_argument("--log-every", type=shared._positive)
    exp.set_defaults(log_every=None)        # none given: section 12.2's rule (experiment._log_every)


def _cmd_experiment(args):
    """experiment (contract section 12.5): play an experiment's missing games (its controls,
    then its arms), then print its measures and recommendations (experiment.py). --dry-run
    lists the games each arm and control would play and plays nothing. Exit code 1 when a
    run failed (the others went on) or the spec can't be used."""
    from . import experiment
    only = [a.strip() for a in args.only.split(",") if a.strip()] if args.only else None
    try:
        spec = experiment.load_spec(args.spec)
        if args.dry_run:
            found = experiment.plan(spec, results_dir=args.results_dir, control_dir=args.control_dir, only=only,
                                    games=args.games, logs_dir=args.logs_dir, control_logs_dir=args.control_logs_dir)
            if args.json:
                print(shared.json.dumps(found, ensure_ascii=False))
            else:
                _print_experiment_plan(found)
            return 0
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    shown = [0.0]

    def report(done, total, detail):
        if shared.time.monotonic() - shown[0] >= results.REPLAY_REPORT_S or done == total:
            shown[0] = shared.time.monotonic()
            print(f"  {done:,} of {total:,} games (playing {detail['playing']})", file=shared.sys.stderr)

    try:
        found = experiment.run(spec, by=args.by, progress=report, results_dir=args.results_dir,
                               logs_dir=args.logs_dir, control_dir=args.control_dir,
                               control_logs_dir=args.control_logs_dir, only=only, games=args.games, local=args.local,
                               log_every=getattr(args, "log_every", None))
    except ValueError as e:
        raise shared._CliError(str(e)) from None
    text = experiment.report(found)
    if args.report:
        try:
            shared.Path(args.report).write_text(text, encoding="utf-8")
        except OSError as e:
            raise shared._CliError(f"The report can't be written as {args.report} ({shared._os_reason(e)}).") from None
    if args.json:
        print(shared.json.dumps(found, ensure_ascii=False))
    else:
        print(text)
    for failure in found["failed"]:
        print(f"Failed: {failure['arm']}, {failure['pair'][0]} v {failure['pair'][1]}: {failure['error']}",
              file=shared.sys.stderr)
    return 1 if found["failed"] else 0


def _print_experiment_plan(found):
    """The dry run's lines (experiment.plan's answer)."""
    print(f"Experiment {found['experiment']}: {found['games']:,} games a pair, results in {found['results_dir']}")
    for c in found["controls"]:
        where = "the control folder holds it" if c["source"] == "control_dir" else f"{c['have']:,} played"
        print(f"  control {c['pair'][0]} v {c['pair'][1]}: {where}, {c['missing']:,} to play")
    for a in found["arms"]:
        if a["skipped"]:
            print(f"  {a['arm']}, {a['pair'][0]} v {a['pair'][1]}: skipped ({a['skipped']})")
        else:
            print(f"  {a['arm']}, {a['pair'][0]} v {a['pair'][1]}: {a['have']:,} played, {a['missing']:,} to play")
    t = found["totals"]
    print(f"In all: {t['games']:,} games ({t['control_games']:,} for controls, {t['arm_games']:,} for arms).")
