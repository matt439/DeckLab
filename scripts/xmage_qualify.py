"""Explicit disposable XMage qualification. No household config, database or server is used."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decklab.xmage import describe


def _row(name, quantity=1):
    return {"name": name, "quantity": quantity}


def _deck(identity, main, commander=()):
    return {"id": identity, "main": main, "commander": list(commander)}


def fixtures():
    """Synthetic lists; no saved deck, collection or member data is read."""
    green = [_row("Forest", 24)] + [_row(name, 4) for name in (
        "Grizzly Bears", "Runeclaw Bear", "Llanowar Elves", "Elvish Mystic", "Giant Growth",
        "Craw Wurm", "Centaur Courser", "Garruk's Companion", "Nessian Courser")]
    sol_ring = [row for row in green if row["name"] != "Runeclaw Bear"] + [_row("Sol Ring", 4)]
    commander = [_row("Thrun, Breaker of Silence")]
    partners = [_row("Rograkh, Son of Rohgahh"), _row("Dargo, the Shipwrecker")]
    cases = {
        "casual-sol-ring": ("casual", sol_ring, [], green, [], "completed"),
        "commander-single": ("commander", [_row("Forest", 99)], commander,
                             [_row("Forest", 99)], commander, "completed"),
        "commander-partners": ("commander", [_row("Mountain", 98)], partners,
                               [_row("Mountain", 98)], partners, "completed"),
        "double-faced": ("casual", [_row("Island", 56),
                                   _row("Delver of Secrets // Insectile Aberration", 4)], [],
                         green, [], "completed"),
        "missing-card": ("casual", [_row("Forest", 56), _row("No Such Deck Lab Fixture Card", 4)],
                         [], green, [], "unsupported"),
        "invalid-partners": ("commander", [_row("Forest", 98)],
                             commander + [_row("Goreclaw, Terror of Qal Sisma")],
                             [_row("Forest", 99)], commander, "unsupported"),
        "invalid-colour": ("commander", [_row("Island", 99)], commander,
                           [_row("Forest", 99)], commander, "unsupported"),
        "wrong-dfc-back": ("casual", [_row("Island", 56),
                                     _row("Delver of Secrets // Grizzly Bears", 4)], [],
                           green, [], "unsupported"),
        "timeout": ("commander", [_row("Forest", 99)], commander,
                    [_row("Forest", 99)], commander, "timeout"),
    }
    result = {}
    for name, (format_, main, leaders, opponent, other_leaders, expected) in cases.items():
        result[name] = ({"schema": 1, "format": format_, "seed": 1501, "games": 1,
                         "game_number": 2, "starting_player": 1,
                         "timeout_seconds": 1 if name == "timeout" else 90,
                         "decks": [_deck("baseline", main, leaders),
                                   _deck("opponent", opponent, other_leaders)]}, expected)
    for name, field, value in (("unknown-field", "unexpected", True),
                               ("boolean-schema", "schema", True),
                               ("fractional-schema", "schema", 1.0),
                               ("modern-refused", "format", "modern")):
        manifest = json.loads(json.dumps(result["casual-sol-ring"][0]))
        manifest[field] = value
        result[name] = manifest, "invalid"
    manifest = json.loads(json.dumps(result["casual-sol-ring"][0]))
    manifest["decks"][0]["main"][0]["quantity"] = 0
    result["zero-quantity"] = manifest, "invalid"
    result["duplicate-key"] = result["casual-sol-ring"][0], "invalid"
    return result


def qualify(home, build_dir, output, selected=None):
    installed = describe(home, build_dir=build_dir)
    if not installed["ready"]:
        raise ValueError(installed["problem"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = fixtures()
    names = selected or list(cases)
    receipt = {"schema": 1, "engine": {key: value for key, value in installed.items()
                                      if key != "command"}, "cases": []}
    for name in names:
        manifest, expected = cases[name]
        request = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if name == "duplicate-key":
            request = request.replace(b'"schema":1', b'"schema":1,"schema":1', 1)
        request_path = output / f"{name}.request.json"
        request_path.write_bytes(request)
        began = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="decklab-xmage-game-") as temporary:
            process = subprocess.run([*installed["command"], str(request_path)], cwd=temporary,
                                     capture_output=True, timeout=manifest["timeout_seconds"] + 15)
        (output / f"{name}.stderr.txt").write_bytes(process.stderr)
        result = json.loads(process.stdout.decode("utf-8"))
        (output / f"{name}.result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if process.returncode != 0 or result.get("status") != expected:
            raise AssertionError(f"{name}: wanted {expected}, got {result.get('status')}; see {output}")
        if result.get("request_sha256") != hashlib.sha256(request).hexdigest():
            raise AssertionError("The result did not bind the exact request bytes.")
        for field in ("identity_sha256", "engine_sha256", "bridge_sha256", "bridge_source_sha256", "source_revision"):
            if result.get(field) != installed[field]:
                raise AssertionError(f"The result did not bind {field}.")
        if expected in {"invalid", "unsupported", "timeout"}:
            if any(game.get("winner") is not None for game in result.get("games", [])):
                raise AssertionError("An incomplete or unsupported request acquired a winner.")
        if name in {"invalid-partners", "invalid-colour"}:
            if result["coverage"][0]["status"] != "invalid" or not result["coverage"][0]["errors"]:
                raise AssertionError("Illegal Commander rules were not refused in preflight.")
        if name in {"missing-card", "wrong-dfc-back"}:
            if not result["coverage"][0]["missing"]:
                raise AssertionError("An unsupported name was not preserved in preflight.")
        if expected == "completed":
            game = result["games"][0]
            if (game["starting_player"] != 1 or game["number"] != 2 or game["errors"] != 0
                    or game["winner"] not in {"subject", "opponent", "draw"}
                    or game["starting_life"] != (40 if manifest["format"] == "commander" else 20)):
                raise AssertionError("Finished game's seats, rules or result were inconsistent.")
            if manifest["format"] == "commander":
                expected_commanders = [len(deck["commander"]) for deck in manifest["decks"]]
                if game["commanders"] != expected_commanders:
                    raise AssertionError("Not every requested commander entered the commander rules.")
            if result["reproducible"] is not False:
                raise AssertionError("Seeded replay has not been established.")
        entry = {"name": name, "status": result["status"],
                 "seconds": round(time.monotonic() - began, 3),
                 "request_sha256": result["request_sha256"], "games": result.get("games", [])}
        receipt["cases"].append(entry)
        (output / "qualification.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(entry), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-real-xmage", action="store_true", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--build-dir")
    parser.add_argument("--output", required=True)
    parser.add_argument("--case", action="append", choices=sorted(fixtures()))
    args = parser.parse_args()
    qualify(args.home, args.build_dir, args.output, args.case)


if __name__ == "__main__":
    main()
