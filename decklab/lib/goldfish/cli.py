"""The goldfish package's command line, python -m decklab.lib.goldfish
(__main__.py runs main()); the package docstring has its usage.
"""
import argparse
import json
import sys

from decklab.lib import decks

from . import runs
from .results import headline
from .runs import DEFAULT_GAMES, DEFAULT_TURNS


def _pct(x):
    """0.8563 -> "85.6"; like the page, a chance that isn't 0 or 1 never shows
    as 0.0 or 100.0 ("<0.1", ">99.9")."""
    if x is None:
        return "-"
    if 0 < x < 0.0005:
        return "<0.1"
    if 0.9995 <= x < 1:
        return ">99.9"
    return f"{100 * x:.1f}"


def _print_summary(name, result):
    print(f"{name}: {result['games']:,} games per setup, {result['turns']} turns, seed {result['seed']}, "
          f"{result['workers']} workers, {result['seconds']} s" + (" (saved result)" if result.get("cached") else ""))
    for warning in result["warnings"]:
        print(f"  ! {warning}")
    for s in result["setups"]:
        r = result["results"][s["id"]]
        drops = " ".join(f"{d['land']}:{_pct(d['chance'])}" for d in r["land_drops"]["on_time"][1:5])
        print(f"  {s['label']}: mulligan {_pct(r['mulligans']['rate'])}%, lands on time {drops}, "
              f"stuck {_pct(r['stuck']['games'])}%, flood turns {_pct(r['flood']['turns'])}%, "
              f"colour screw {_pct(r['colours']['screw_turns'])}%, mana used "
              f"{_pct(r['mana_used']['share'])}%, 4-drop by turn 4 {_pct(r['first_big']['by_turn_4'])}%")
    if result["cards"]["unresolved"]:
        print("  Unresolved: " + ", ".join(c["name"] for c in result["cards"]["unresolved"]))


def main(argv=None):
    try:
        return _main(argv)
    except KeyboardInterrupt:
        # Ctrl+C: the workers have been stopped already (simulate), so just say so.
        print("Stopped.", file=sys.stderr)
        return 130


def _main(argv):
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.goldfish",
                                     description="Practice-hand simulation for a Deck Lab deck.")
    parser.add_argument("deck_id", nargs="?", help='e.g. casual/gruul-ramp, "pairing/cats+elves"')
    parser.add_argument("--owned", action="store_true", help="the owned-only list")
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES, help="games per setup")
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON")
    parser.add_argument("--no-cache", action="store_true", help="simulate even if a result is saved")
    parser.add_argument("--all", action="store_true", help="headline numbers for every deck")
    parser.add_argument("--halves", action="store_true", help="with --all: the Beginner Box halves too")
    parser.add_argument("--pairings", action="store_true", help="with --all: the 45 Beginner Box pairings too")
    args = parser.parse_args(argv)
    if not args.all and not args.deck_id:
        parser.error("give a deck id or --all")

    def run(summary, version):
        kind = decks.engine_kind(summary)
        sections = decks.load_deck(summary["id"], version)
        return runs.get_or_simulate(sections, kind, args.games, args.turns, args.seed, args.workers,
                                    refresh=args.no_cache)

    if args.all:
        everything = [s for s in decks.list_decks() if not s.get("error")]
        chosen = [s for s in everything if args.halves or not s["id"].startswith("product/fdn-beginner-box/")]
        if args.pairings:
            chosen += decks.beginner_box_pairings()
        print(f"{'deck':<48} {'ver':<6} {'games':<11} {'mull%':>6} {'L3@3':>6} {'L4@4':>6} {'screw':>6} "
              f"{'flood':>6} {'4d@4':>6} {'secs':>6}")
        for summary in chosen:
            for version in summary["versions"]:
                result = run(summary, version)
                h = headline(result)        # multiplayer for Commander decks, on the play for the rest
                print(f"{summary['id']:<48} {version:<6} {h['setup']:<11} {_pct(h['mulligan_rate']):>6} "
                      f"{_pct(h['land_3_by_3']):>6} {_pct(h['land_4_by_4']):>6} {_pct(h['colour_screw']):>6} "
                      f"{_pct(h['flood_turns']):>6} {_pct(h['big_by_4']):>6} {result['seconds']:>6}")
        return 0
    summary = decks.find_summary(args.deck_id)
    if summary is None or summary.get("error"):
        print(f"No deck {args.deck_id!r}", file=sys.stderr)
        return 1
    result = run(summary, "owned" if args.owned else "target")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_summary(args.deck_id, result)
    return 0
