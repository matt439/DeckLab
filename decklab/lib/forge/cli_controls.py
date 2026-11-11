"""CLI-only explicit placebo and independent-size comparisons; no page start route."""
from . import cli_shared as shared, variants, variants_gauntlet


def variant_control(args):
    from . import cli_evaluate
    placebo, size = bool(args.placebo), bool(args.size_change)
    if placebo and size:
        raise shared._CliError("Choose --placebo or --size-change, not both.")
    if args.noise_floor and not placebo:
        raise shared._CliError("--noise-floor accompanies --placebo.")
    if args.more or args.until or sum(bool(value) for value in (args.games, args.quick)) != 1:
        raise shared._CliError("A control needs one fixed final look: --games N or --quick, without --more or --until.")
    if placebo and (args.remove or args.add or args.list_file):
        raise shared._CliError("A placebo plays the unchanged list; leave out --remove, --add and --list.")
    sample = args.gauntlet
    if args.against and args.against.startswith(variants_gauntlet.PREFIX) and not sample:
        sample, args.against = args.against[len(variants_gauntlet.PREFIX):], None
    if sum(bool(value) for value in (args.field, args.against, sample)) != 1:
        raise shared._CliError("Choose exactly one of --against DECK, --field or --gauntlet SAMPLE.")
    if args.opponents and not args.field:
        raise shared._CliError("--opponents limits --field only.")
    if args.results_dir is not None and not shared.Path(args.results_dir).is_dir():
        raise shared._CliError(f"There's no folder called {args.results_dir}.")
    base = shared._cli_entry(args.deck, args.owned)
    cards = base["cards"] if placebo else cli_evaluate._variant_cards(base, args)
    if size and shared.lists._list_text(cards, base["kind"])[2] == base["card_count"]:
        args.size_change = False
        return cli_evaluate._cmd_variant(args)       # same-size swaps retain the ordinary paired path
    field_options = None
    if sample:
        against, field_options = cli_evaluate._gauntlet_against(base, sample, args.deck)
    else:
        against = "field" if args.field else shared._cli_entry(args.against, args.owned_b)
    opponents = [value.strip() for value in args.opponents.split(",") if value.strip()] if args.opponents else None
    mode = "quick" if args.quick else args.games
    options = {"by": args.by, "results_dir": args.results_dir, "local": args.local,
               "opponents": opponents, "field_options": field_options}
    if getattr(args, "logs_dir", None) is not None:
        options.update(log_dir=args.logs_dir, log_every=args.log_every)
    try:
        if placebo:
            found = variants.run_placebo(base, against, mode, noise_floor=args.noise_floor, **options)
        else:
            found = variants.run_unpaired(base, cards, against, variants.QUICK_GAMES if args.quick else mode, **options)
    except ValueError as error:
        raise shared._CliError(str(error)) from None
    if args.json:
        print(shared.json.dumps(found, ensure_ascii=False))
    elif placebo:
        print(found["control_note"])
        cli_evaluate._print_variant(found)
        for opponent in found.get("opponents") or []:
            floor = found["noise_floor"].get(opponent.get("card_sha"))
            name = opponent.get("title") or opponent.get("id")
            if floor:
                print(f"  {name}: same-install engine-check saw {floor['different_winners']} winner and "
                      f"{floor['different_outcomes']} outcome disagreements in {floor['games']} games; finite observed noise, not exact zero.")
            else:
                print(f"  {name}: exact pair/engine noise floor unknown; no equality is claimed.")
    else:
        print(found["note"])
        print(f"Separate equivalence margin: {100 * found['margin']:.1f} points.")
        for opponent in found["opponents"]:
            diff = opponent["difference"]
            result = ("Not settled yet: both going-first and going-second samples are needed." if diff["delta"] is None else
                      f"{100 * diff['delta']:+.1f} points ({100 * diff['low']:+.1f} to {100 * diff['high']:+.1f}); {opponent['verdict']}")
            print(f"  {opponent['title'] or opponent['id']}: not paired; {result}")
        print(f"  test {found['test']}")
    return 0
