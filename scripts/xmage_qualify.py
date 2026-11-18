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

PREFLIGHT_SENTINEL = "No Such Deck Lab Preflight Opponent"
DIACRITIC_NAMES = (
    "Andúril, Flame of the West", "Éomer, Marshal of Rohan", "Éowyn, Fearless Knight", "Éowyn, Lady of Rohan",
    "Arwen Undómiel", "Círdan the Shipwright", "Galadriel of Lothlórien", "Lórien Revealed",
    "Song of Eärendil", "Soothing of Sméagol")
ADVENTURE_NAMES = (
    "Beorn, Reluctant Host // Till and Tend", "Bilbo Baggins, Burglar // Take a Glance",
    "Bilbo, Luckwearer // Burglar's Plot", "Thranduil, Sindarin Liege // Silvan Rally")
# Every selected case has an unsupported opponent, so even successful baseline admission cannot start a game.
PREFLIGHT_CASES = {
    "preflight-diacritics": (True, DIACRITIC_NAMES),
    "preflight-adventures": (True, ADVENTURE_NAMES),
    "preflight-exact-name": (True, ("Sol Ring",)),
    "preflight-double-faced": (True, ("Delver of Secrets // Insectile Aberration",)),
    "preflight-wrong-adventure-back": (False, ("Beorn, Reluctant Host // Grizzly Bears",)),
    "preflight-adventure-front-only": (False, ("Beorn, Reluctant Host",)),
    "preflight-adventure-back-only": (False, ("Till and Tend",)),
    "preflight-invented-accent": (False, ("Fórest",)),
    "preflight-unimplemented": (False, ("Galion, Elvenking's Butler",)),
}


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
    for name, (_, requested) in PREFLIGHT_CASES.items():
        cases[name] = ("casual", [_row("Forest", 60 - len(requested))] + [_row(n) for n in requested], [],
                       [_row("Forest", 59), _row(PREFLIGHT_SENTINEL)], [], "unsupported")
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


def verify_preflight(name, manifest, result):
    """Require exact coverage and a nonplayed response, rather than accepting any unsupported result."""
    supported, requested = PREFLIGHT_CASES[name]
    coverage = result.get("coverage") or []
    if len(coverage) != 2 or [row.get("deck_id") for row in coverage] != ["baseline", "opponent"]:
        raise AssertionError("Both exact preflight lists need coverage evidence.")
    baseline, opponent = coverage
    if opponent.get("status") != "unsupported" or opponent.get("missing") != [PREFLIGHT_SENTINEL]:
        raise AssertionError("The deliberate opponent sentinel was not refused.")
    if supported:
        if baseline.get("status") != "supported" or baseline.get("missing") or baseline.get("cards") != 60:
            raise AssertionError("The exact canonical list was not admitted unchanged.")
    elif baseline.get("status") != "unsupported" or baseline.get("missing") != list(requested):
        raise AssertionError("The refused exact card names were not preserved.")
    if result.get("status") != "unsupported" or any(
            g.get("status") != "unsupported" or g.get("winner") is not None or g.get("turns") != 0
            for g in result.get("games", [])):
        raise AssertionError("A coverage-only request started or credited a game.")
    if manifest["decks"][1]["main"][-1]["name"] != PREFLIGHT_SENTINEL:
        raise AssertionError("A coverage-only request lost its no-game sentinel.")


def check_name_index(installed, output):
    """Exercise the compiled pure name index and class-bound aliases without constructing an engine or game."""
    source = r'''
import java.lang.reflect.*;
public final class NameIndexChecks {
  static Class<?> index, alias;
  static Constructor<?> indexCtor, aliasCtor;
  static Method add, get, ambiguous, bind;
  static Object fresh() throws Exception { return indexCtor.newInstance(); }
  static void put(Object i, String name, String identity, Object value) throws Exception { add.invoke(i,name,identity,value); }
  static Object read(Object i, String name) throws Exception { return get.invoke(i,name); }
  static void require(boolean value) { if (!value) throw new AssertionError("Name identity check failed"); }
  public static void main(String[] args) throws Exception {
    index=Class.forName("decklab.xmage.Bridge$NameIndex"); alias=Class.forName("decklab.xmage.Bridge$NameAlias");
    indexCtor=index.getDeclaredConstructor(); aliasCtor=alias.getDeclaredConstructor(String.class,String.class,String.class);
    add=index.getDeclaredMethod("add",String.class,String.class,Object.class); get=index.getDeclaredMethod("get",String.class);
    ambiguous=index.getDeclaredMethod("ambiguous",String.class); bind=alias.getDeclaredMethod("bind",index);
    for (AccessibleObject a : new AccessibleObject[]{indexCtor,aliasCtor,add,get,ambiguous,bind}) a.setAccessible(true);
    Object first=new Object(), second=new Object(), i=fresh();
    put(i,"Forest","ForestClass",first);put(i,"Forest","ForestClass",second);
    require(read(i,"Forest")==first && read(i,"Fórest")==null);
    put(i,"Forest","AnotherClass",second);put(i,"Forest","ForestClass",first);
    require(read(i,"Forest")==null && (Boolean)ambiguous.invoke(i,"Forest"));
    Object a=aliasCtor.newInstance("Canonical É","Engine E","ExpectedClass");
    i=fresh();put(i,"Engine E","ExpectedClass",first);bind.invoke(a,i);require(read(i,"Canonical É")==first);
    i=fresh();put(i,"Engine E","WrongClass",first);bind.invoke(a,i);require(read(i,"Canonical É")==null);
    i=fresh();put(i,"Engine E","ExpectedClass",first);put(i,"Engine E","WrongClass",second);
    bind.invoke(a,i);require(read(i,"Canonical É")==null);
    i=fresh();put(i,"Engine E","ExpectedClass",first);put(i,"Canonical É","WrongClass",second);
    bind.invoke(a,i);require(read(i,"Canonical É")==null && (Boolean)ambiguous.invoke(i,"Canonical É"));
    System.out.println("{\"checks\":6,\"passed\":true,\"games_started\":0}");
  }
}
'''
    java = Path(installed["command"][0])
    compiler = java.with_name("javac.exe" if sys.platform == "win32" else "javac")
    with tempfile.TemporaryDirectory(prefix="decklab-xmage-name-index-") as temporary:
        path = Path(temporary) / "NameIndexChecks.java"
        path.write_text(source, encoding="utf-8")
        subprocess.run([str(compiler), "--release", "17", "-encoding", "UTF-8", str(path)], check=True,
                       capture_output=True, timeout=30)
        classpath = str(path.parent) + (";" if sys.platform == "win32" else ":") + installed["command"][-2]
        completed = subprocess.run([str(java), "-Xmx128m", "-cp", classpath, "NameIndexChecks"], check=True,
                                   capture_output=True, timeout=30)
    result = json.loads(completed.stdout)
    if result != {"checks": 6, "passed": True, "games_started": 0}:
        raise AssertionError("The compiled name index did not pass every no-game identity check.")
    (output / "name-index.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def qualify(home, build_dir, output, selected=None, *, name_index_check=False):
    installed = describe(home, build_dir=build_dir)
    if not installed["ready"]:
        raise ValueError(installed["problem"])
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = fixtures()
    names = selected or list(cases)
    receipt = {"schema": 1, "engine": {key: value for key, value in installed.items()
                                      if key != "command"}, "cases": []}
    if name_index_check:
        receipt["name_index"] = check_name_index(installed, output)
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
        if name in PREFLIGHT_CASES:
            verify_preflight(name, manifest, result)
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
    parser.add_argument("--name-index-check", action="store_true",
                        help="Check compiled exact-name, class mismatch and collision handling without games.")
    args = parser.parse_args()
    qualify(args.home, args.build_dir, args.output, args.case, name_index_check=args.name_index_check)


if __name__ == "__main__":
    main()
