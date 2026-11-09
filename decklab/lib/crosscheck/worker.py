"""One isolated Forge game for the cross-check subprocess watchdog.

Only the qualified seeded adapter is accepted. Nothing is saved to Forge's
results directory; its game summaries and per-card data never enter rankings.
"""
import contextlib
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from . import adapters
from .model import MAX_BYTES, SCHEMA, CrosscheckError, canonical


def _entry(deck, pilot):
    from decklab.lib.forge import lists
    listed = {"Commander": [[r["quantity"], r["name"]] for r in deck["commander"]],
              "Main": [[r["quantity"], r["name"]] for r in deck["main"]]}
    entry = lists.entry_from_cards("crosscheck/" + deck["id"], deck["id"],
                                   "commander" if deck["commander"] else "constructed", listed)
    entry["pilot"] = pilot
    return entry


def run(request_data, request_sha):
    from decklab.lib.forge import install, runner, seeds
    found = adapters.details("forge")
    if found["identity"] != request_data.get("engine_sha256"):
        raise CrosscheckError("Forge changed after this game was planned.")
    decks = request_data["decks"]
    role = decks[0]["id"]
    response = {"schema": SCHEMA, "engine": "forge", "version": found["version"],
                "engine_sha256": found["identity"], "request_sha256": request_sha,
                "format": request_data["format"], "seed": request_data["seed"],
                "reproducible": True, "coverage": [], "games": [], "status": "completed"}
    index = install.script_index()
    unsupported = False
    for deck in decks:
        missing = sorted({row["name"] for section in ("main", "commander") for row in deck[section]
                          if install._forge_card(row["name"], index) is None})
        unsupported |= bool(missing)
        response["coverage"].append({"deck_id": deck["id"], "status": "unsupported" if missing else "supported",
                                     "missing": missing})
    if unsupported:
        response["status"] = "unsupported"
        return response
    pilots = request_data.get("pilots", {})
    entries = [_entry(deck, pilots.get(deck["id"], {"profile": "Default", "switches": []})) for deck in decks]
    # Both arms use the baseline/opponent stream. Switching a card cannot silently
    # switch the random stream; engines' random schemes still differ from each other.
    stream = request_data["forge_stream"]
    ordered = sorted(entries, key=lambda e: e["card_sha"])
    flip = int(ordered[0]["card_sha"] != entries[0]["card_sha"]) ^ request_data["starting_player"]
    with tempfile.TemporaryDirectory(prefix="forge-crosscheck-") as folder:
        result = runner.run(entries[0], entries[1], 1, by="crosscheck", results_dir=folder,
                            workers=1, local=True, exact=True, save=False, numbers=[0],
                            seeds={"base": request_data["seed"], "stream": stream, "flip": flip},
                            key=request_sha, kind="experiment")
    games = [game for batch in result["batches"] for game in batch.get("games", [])]
    if len(games) != 1:
        raise CrosscheckError("Forge did not return exactly one game.")
    game = games[0]
    sides = result["sides"]
    subject_side = next(i for i, side in enumerate(sides) if side["card_sha"] == entries[0]["card_sha"])
    state = "timeout" if game["r"] == "timeout" else "failed" if game["r"] == "error" else "completed"
    winner = None
    if state == "completed":
        winner = "draw" if game["w"] is None else "subject" if game["w"] == subject_side else "opponent"
    # An AI decision timeout can change its choice despite a nominal win. Keep it
    # out of successful-game rates, alongside the game's own wall-clock timeout.
    if game.get("ai_to", 0):
        state, winner = "timeout", None
    response["games"].append({"arm": role, "number": request_data["game_number"],
                              "seed": request_data["seed"], "status": state, "winner": winner,
                              "starting_player": None if game.get("first") is None else
                                  0 if game["first"] == subject_side else 1,
                              "turns": game.get("turns")})
    response["provenance"] = {"engine": result.get("engine"),
                              "engine_seed": seeds.game_seed(request_data["seed"], int(stream, 16), 0),
                              "side_order": [side["card_sha"] for side in sides]}
    return response


def main():
    try:
        if len(sys.argv) != 2:
            raise CrosscheckError("Supply exactly one game request file.")
        path = Path(sys.argv[1])
        if path.stat().st_size > MAX_BYTES:
            raise CrosscheckError("The game request is too large.")
        raw = path.read_bytes()
        request_data = json.loads(raw)
        if canonical(request_data) != raw:
            raise CrosscheckError("The game request is not canonical JSON.")
        with contextlib.redirect_stdout(sys.stderr):
            response = run(request_data, hashlib.sha256(raw).hexdigest())
        sys.stdout.buffer.write(canonical(response))
        return 0
    except Exception:
        # No card names, file paths or traceback enter a public-facing job error.
        print("Forge could not complete this cross-check game.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
