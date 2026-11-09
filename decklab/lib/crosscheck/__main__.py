"""Plan, play and inspect independent simulator receipts from the PC."""
import argparse
import json
import sys

from . import CrosscheckError, CrosscheckStopped, deck_entry, plan, prepare_forge, results_for, run, status, view


def _parser():
    parser = argparse.ArgumentParser(description="Keep Forge and XMage second opinions separate.")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("status", help="Inspect explicit local installations without downloading or building.")
    subs.add_parser("prepare", help="Explicitly prepare this checkout's Forge runtime without playing games.")
    for name in ("plan", "play"):
        sub = subs.add_parser(name)
        sub.add_argument("deck")
        sub.add_argument("opponent")
        sub.add_argument("--version", choices=("target", "owned"), default="target")
        sub.add_argument("--opponent-version", choices=("target", "owned"), default="target")
        sub.add_argument("--games", type=int, default=10, help="Games per list, separately in each simulator (1-200).")
        sub.add_argument("--seed", type=int, default=1)
        sub.add_argument("--timeout", type=int, default=120, help="Game time limit in seconds (5-600).")
        sub.add_argument("--remove", action="append", default=[], metavar='"1 Exact card name"')
        sub.add_argument("--add", action="append", default=[], metavar='"1 Exact card name"')
        sub.add_argument("--engine", choices=("forge", "xmage"), action="append",
                         help="A diagnostic subset; defaults to both engines.")
        sub.add_argument("--json", action="store_true")
    sub = subs.add_parser("view")
    sub.add_argument("receipt", nargs="?")
    sub.add_argument("--deck", help="List the latest receipts involving this deck.")
    sub.add_argument("--json", action="store_true")
    return parser


def _print(result, as_json=False):
    if as_json or "schema" in result or isinstance(result, list):
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return
    print(f"Cross-check {result['id']}")
    print("Commander one on one" if result["format"] == "commander" else "Casual one on one; no tournament bans")
    print("Played main and commander sections only; sideboards and companions are excluded.")
    for name, engine in result["engines"].items():
        print(f"\n{name.title()} {engine.get('version') or ''}: {engine['status']}")
        for role in ("baseline", "variant"):
            arm = engine.get(role)
            if arm is None:
                continue
            rate = "no completed games" if arm["win_rate"] is None else f"{arm['win_rate']:.1f}% wins"
            band = arm.get("win_rate_interval")
            if band:
                rate += f" (95% interval {band['low']:.1f}-{band['high']:.1f}%)"
            print(f"  {role}: {rate}; {arm['completed']}/{arm['asked']} completed, "
                  f"{arm['draws']} draws, {arm['timeouts']} timeouts, {arm['failed']} failed, {arm['unplayed']} unplayed")
        if engine["delta_percentage_points"] is not None:
            print(f"  Change: {engine['delta_percentage_points']:+.1f} percentage points (descriptive, not a paired estimate)")
        if engine.get("missing_cards"):
            print("  Unsupported unchanged cards: " + ", ".join(engine["missing_cards"]))
        if engine.get("problem"):
            print("  " + engine["problem"])
    print("\n" + result["agreement"]["text"])
    print("Simulator agreement does not establish rules correctness or real-table performance.")


def main(argv=None):
    from decklab.lib.inventory import entry
    with entry.command():
        return _main(argv)


def _main(argv=None):
    from decklab.lib import decks, inventory, keepawake
    from decklab.lib.forge.common import ForgeError
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            _print(status(), True)
            return 0
        if args.command == "prepare":
            prepared = prepare_forge()
            _print(prepared, True)
            return 0 if prepared.get("ready") is True else 1
        if args.command == "view":
            if bool(args.receipt) == bool(args.deck):
                raise CrosscheckError("Supply a receipt id or --deck, once each.")
            found = results_for(args.deck) if args.deck else view(args.receipt)
            if found is None:
                raise CrosscheckError("No verified cross-check receipt has that id.")
            _print(found, args.json)
            return 0
        from decklab.lib.forge import lists
        with lists.one_snapshot():
            a = deck_entry(args.deck, args.version)
            b = deck_entry(args.opponent, args.opponent_version)
            captured = plan(a, b, games=args.games, seed=args.seed, timeout_seconds=args.timeout,
                            remove=args.remove, add=args.add, engines=args.engine or ("forge", "xmage"))
        if args.command == "plan":
            _print(captured, True)
            return 0
        if any(identity is None for identity in captured["engine_identities"].values()):
            raise CrosscheckError("A selected simulator is not ready. Check crosscheck status and build the local bridge explicitly.")
        with keepawake.hold_while():
            receipt = run(captured)
        _print(view(receipt), args.json)
        return 0 if receipt["status"] == "completed" else 1
    except inventory.Unavailable:
        print("Deck Lab's database is unavailable; no cross-check was started.", file=sys.stderr)
        return 2
    except (decks.DeckNotFound, decks.DeckFileError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (CrosscheckError, ForgeError, OSError) as error:
        if isinstance(error, OSError):
            print("Deck Lab could not read or save cross-check evidence.", file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        if isinstance(error, CrosscheckStopped) and getattr(error, "receipt_id", None):
            print("Partial receipt: " + error.receipt_id, file=sys.stderr)
        return 1
    except KeyboardInterrupt as error:
        print("Cross-check stopped; completed evidence was preserved.", file=sys.stderr)
        if getattr(error, "receipt_id", None):
            print("Partial receipt: " + error.receipt_id, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
