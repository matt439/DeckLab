"""Pick and replay one saved seeded game, retaining a readable transcript outside result stores."""
import re

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 50000
TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)")


def pick(result, perspective=0, number=None, choice="loss"):
    found = [game for batch in result.get("batches", []) for game in batch.get("games", [])]
    numbered = [game for game in found if type(game.get("g")) is int and game["g"] >= 0]
    if number is not None:
        wanted = [game for game in numbered if game["g"] == number]
    elif choice == "loss":
        wanted = [game for game in numbered if game.get("w") in (0, 1) and game["w"] != perspective]
    elif choice == "timeout":
        wanted = [game for game in numbered if game.get("r") == "timeout" or game.get("ai_to")]
    elif choice == "longest":
        wanted = sorted(numbered, key=lambda game: (-(game.get("turns") or 0), -(game.get("ms") or 0), game["g"]))
    else:
        raise ValueError("Choose loss, longest or timeout")
    if not wanted:
        raise ValueError("No saved numbered game matches that selection")
    if number is not None and len(wanted) != 1:
        raise ValueError("That saved game number is ambiguous")
    return wanted[0] if choice == "longest" else min(wanted, key=lambda game: game["g"])


def replay(setup, folder, result, g):
    """The soak probe's exact one-shot replay; scratch deck files, saved seeds/lists/pilots, no result writer."""
    from . import cli_shared as shared
    record = result["seeds"]
    names = []
    for side in result["sides"]:
        name = f"{side['card_sha']}.dck"
        (folder / name).write_text(side["dck"], encoding="utf-8")
        names.append(name)
    deck1 = shared.seeds.deck1_side(g, record["flip"])
    order = [deck1, 1-deck1]
    seat_pilots = [result["sides"][i].get("pilot") for i in order]
    launch = dict(setup, decks_dir=folder)
    v2 = {"stream": record["stream"], "first": g}
    if all(seat_pilots) and any(p.get("profile", "Default") != "Default" or p.get("switches") for p in seat_pilots):
        argv = shared.runner._java(launch) + shared.runner._class_path_launch(launch) + shared.runner.request_args(
            launch, result["format"], names[order[0]], names[order[1]], 1, record["base"], v2=v2, pilots=seat_pilots)
    else:
        argv = shared.runner.build_command(launch, result["format"], names[order[0]], names[order[1]], 1, record["base"], v2)
    env = shared._prepare_user_dir(setup["user_dir"])
    proc = shared.processes.start_process(argv, cwd=str(setup["forge_dir"]), env=env)
    try:
        out, _ = proc.communicate(timeout=max(600, 4*setup["clock_s"]))
    except Exception:
        shared._end_process(proc)
        raise
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else (out or "")


def events(text):
    """Keep Forge's readable turn log; translate hand packets rather than exposing DL transport noise."""
    if len(text.encode("utf-8")) > MAX_LOG_BYTES:
        raise ValueError("That replay log is too large to display safely")
    turn, active, found = 0, None, []
    lines = text.splitlines()
    header = max((index for index, line in enumerate(lines) if " - 1 game of " in line), default=-1)
    for raw in lines[header+1:]:
        line = "".join(ch for ch in raw if ord(ch) >= 32 or ch == "\t").strip()
        if not line:
            continue
        if line.startswith("Information: DL|") or line.startswith("DL|"):
            parts = line.removeprefix("Information: ").split("|")
            if len(parts) >= 6 and parts[1] == "hand" and parts[3] in ("start", "end"):
                try:
                    hand_turn, seat = int(parts[2]), int(parts[4])
                except ValueError:
                    continue
                cards = [card.partition("=")[2] for card in "|".join(parts[5:]).split(";") if "=" in card]
                found.append({"turn": hand_turn, "seat": seat, "kind": "hand_"+parts[3], "cards": cards,
                              "text": f"{'Kept hand' if parts[3] == 'start' else 'Hand at end'}, seat {seat}: " + (", ".join(cards) or "empty")})
                if len(found) > MAX_EVENTS:
                    raise ValueError("That replay has too many events to display safely")
            continue
        if line.startswith("DLENGINE|") or " - 1 game of " in line:
            continue
        match = TURN.match(line)
        if match:
            turn, active = int(match[1]), int(match[2])
        lower = line.lower()
        kind = ("turn" if match else "failed_cast" if "couldn't add to stack" in lower or "could not add to stack" in lower
                else "land" if line.startswith("Land:") else "cast" if line.startswith("Add To Stack:")
                else "combat" if any(word in lower for word in ("attack", "block", "combat"))
                else "life" if any(word in lower for word in ("life", "damage"))
                else "outcome" if line.startswith("Game Result:") else "log")
        found.append({"turn": turn, "seat": active, "kind": kind, "text": line})
        if len(found) > MAX_EVENTS:
            raise ValueError("That replay has too many events to display safely")
        if kind == "outcome":
            break
    captured = {event["seat"] for event in found if event["kind"] == "hand_end"}
    for seat in (1, 2):
        if seat not in captured:
            found.append({"turn": turn, "seat": seat, "kind": "hand_unavailable", "text": f"Hand at end, seat {seat}: not captured"})
    if len(found) > MAX_EVENTS:
        raise ValueError("That replay has too many events to display safely")
    return found


def render(found):
    lines, previous = [], None
    for event in found:
        if event["turn"] != previous:
            previous = event["turn"]
            lines.append(f"\nTurn {previous}" if previous else "\nBefore the first turn")
        lines.append(event["text"])
    return "\n".join(lines)
