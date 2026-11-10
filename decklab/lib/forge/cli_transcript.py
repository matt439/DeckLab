"""A one-game seeded debug replay; stdout only, never a matchup/field/statistics writer."""
from . import cli_checks as checks
from . import cli_shared as shared
from . import transcript


def add_parser(sub):
    parser = sub.add_parser("game", help="Read one saved game by replaying its exact lists, pilots and seed.")
    parser.add_argument("a")
    parser.add_argument("b")
    pick = parser.add_mutually_exclusive_group()
    pick.add_argument("--game", type=int, help="the saved zero-based game number")
    pick.add_argument("--pick", choices=("loss", "longest", "timeout"), default="loss")
    parser.add_argument("--key", help="a specific saved matchup key, including an earlier list")
    parser.add_argument("--results-dir")
    parser.add_argument("--json", action="store_true")


def select_result(a, b, key=None, results_dir=None):
    if key is not None and not shared.re.fullmatch(r"[0-9a-f]{64}", key):
        raise shared._CliError("Use a full saved matchup key")
    candidates = [shared.saved.load(key, results_dir)] if key else shared.saved._stored(results_dir)
    for result in candidates:
        if not result or result.get("kind") is not None:
            continue
        seen = [{row.get("id") for row in side.get("seen_as", [])} for side in result.get("sides", [])]
        if len(seen) == 2 and ((a in seen[0] and b in seen[1]) or (a in seen[1] and b in seen[0])):
            return result, 0 if a in seen[0] else 1
    raise shared._CliError("No saved matchup of those deck IDs was found; use IDs from forge list")


def command(args):
    if args.game is not None and args.game < 0:
        raise shared._CliError("The saved game number is zero or more")
    result, perspective = select_result(args.a, args.b, args.key, args.results_dir)
    if shared.engine.kind_of(result) != shared.engine.KIND_DECKLAB or not isinstance(result.get("seeds"), dict):
        raise shared._CliError("This game needs a saved seeded card-log engine; that earlier result cannot be replayed one game at a time")
    current = shared.engine.is_current(result)
    if current is not True:
        reason = shared.engine.words(result, False) if current is False else "The saved engine and overrides cannot be verified on this PC."
        raise shared._CliError("Replay refused: " + (reason or "The saved engine or overrides differ from this installation."))
    try:
        game = transcript.pick(result, perspective, args.game, args.pick)
    except ValueError as error:
        raise shared._CliError(str(error)) from None
    setup = shared._setup()
    log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
    if not log["ready"]:
        raise shared._CliError(log["problem"])
    setup = dict(setup, card_log=log)
    with shared.tempfile.TemporaryDirectory(prefix="decklab-one-game-") as folder:
        with shared.slots.claim(1, what="one-game transcript"):
            text = transcript.replay(setup, shared.Path(folder), result, game["g"])
    outcomes = checks._outcomes(text)
    if len(outcomes) != 1:
        raise shared._CliError("The replay did not produce exactly one complete game outcome")
    status, winner, first, turns = outcomes[0]
    deck1 = shared.seeds.deck1_side(game["g"], result["seeds"]["flip"])
    order = [deck1, 1-deck1]
    replayed = {"r": status, "w": order[winner] if winner in (0, 1) else None,
                "first": order[first] if first in (0, 1) else None, "turns": turns}
    recorded = {key: game.get(key) for key in ("r", "w", "first", "turns")}
    labels = {"r": "result", "w": "winner", "first": "starter", "turns": "turns"}
    differences = [labels[key] for key in recorded if recorded[key] != replayed[key]]
    try:
        events = transcript.events(text)
    except ValueError as error:
        raise shared._CliError(str(error)) from None
    note = ("Commander replay is compared by outcome only, not line for line. " if result["format"] == "Commander" else "")
    note += ("Differs from the saved record: " + ", ".join(differences) + "." if differences else "Outcome, starter and turns match the saved record.")
    seats = [{"seat": seat+1, "saved_side": side,
              "title": ((result["sides"][side].get("seen_as") or [{}])[-1].get("title") or f"saved side {side+1}")}
             for seat, side in enumerate(order)]
    answer = {"key": result["key"], "game": game["g"], "format": result["format"], "saved": recorded,
              "replayed": replayed, "differences": differences, "note": note, "events": events,
              "seats": seats, "seed": shared.seeds.game_seed(result["seeds"]["base"], shared.seeds.parse_stream(result["seeds"]["stream"]), game["g"]),
              "statistics_written": False}
    if args.json:
        print(shared.json.dumps(answer, ensure_ascii=False))
    else:
        print(f"Saved matchup {result['key'][:12]}, game {game['g']} (zero-based).")
        print(note)
        for seat in seats:
            print(f"Seat {seat['seat']}: {seat['title']} (saved side {seat['saved_side']+1})")
        print("Debug replay only; no matchup, field, Rankings or per-card figures were saved.")
        print(transcript.render(events))
    return 0
