"""Read-only readiness and bounded, one-game subprocess adapters.

Forge retains its existing one-worker slot accounting. XMage claims one of the
same PC-wide slots, and fails closed when that accounting is unavailable.
"""
import hashlib
import os
import sys
import time
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path

from .model import CrosscheckError, ENGINES, SCHEMA, canonical, digest, integer, parse_json

MAX_OUTPUT = 1024 * 1024
MAX_LOG = 8 * 1024 * 1024
STARTUP_SECONDS = 60


@lru_cache(maxsize=64)
def _file_digest(path, size, stamp):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def file_digest(path):
    stat = Path(path).stat()
    return _file_digest(str(path), stat.st_size, stat.st_mtime_ns)


def _forge_details():
    from decklab.lib.forge import engine, install, runner, simjar
    setup = install._setup(remember=False)
    jar = setup["forge_dir"] / setup["jar"]
    ready = simjar.readiness(setup["java"], setup["version"], jar)
    if not ready.get("ready"):
        raise CrosscheckError("Forge's qualified seeded simulator is not ready.")
    current = engine.today(engine.KIND_DECKLAB, read_only=True)
    if not current.get("complete"):
        raise CrosscheckError("Forge's current engine identity cannot be confirmed.")
    provenance = {k: current[k] for k in engine.ENGINE_FIELDS}
    java = Path(setup["java"])
    release = java.parent.parent / "release"
    own_source = {name: file_digest(Path(__file__).parent / name)
                  for name in ("adapters.py", "model.py", "worker.py", "processes.py")}
    provenance.update(ai_sha=current.get("ai_sha"), jar_sha256=file_digest(jar),
                      bridge_source_sha256=simjar.source_sha256(), java_sha256=file_digest(java),
                      java_release_sha256=file_digest(release) if release.is_file() else None,
                      adapter_source_sha256=digest(own_source), jvm_flags=list(runner.JVM_FLAGS))
    return {"ready": True, "problem": None, "version": setup["version"],
            "identity": digest(provenance), "provenance": provenance,
            "command": [sys.executable, "-m", "decklab.lib.crosscheck.worker"]}


def _xmage_details():
    from decklab import xmage
    found = xmage.describe()
    if not found.get("ready"):
        raise CrosscheckError("XMage is not installed and explicitly built for cross-checking.")
    identity = found.get("identity_sha256")
    from .model import HASH
    if not isinstance(identity, str) or not HASH.fullmatch(identity):
        raise CrosscheckError("XMage's installation identity cannot be confirmed.")
    return {"ready": True, "problem": None, "version": found.get("version"), "identity": identity,
            "provenance": {k: found.get(k) for k in ("version", "source_revision", "engine_sha256", "identity_sha256",
                                                    "bridge_sha256", "bridge_source_sha256")},
            "command": found["command"]}


def details(name):
    if name == "forge":
        return _forge_details()
    if name == "xmage":
        return _xmage_details()
    raise CrosscheckError("Unknown cross-check simulator.")


def status():
    """Public readiness: no installation paths, commands, raw exceptions or writes."""
    engines = {}
    for name in ENGINES:
        try:
            found = details(name)
            engines[name] = {k: found.get(k) for k in ("ready", "version", "identity", "problem")}
        except (CrosscheckError, OSError, ValueError, RuntimeError, ImportError, KeyError):
            engines[name] = {"ready": False, "version": None, "identity": None,
                             "problem": f"{'Forge' if name == 'forge' else 'XMage'} is not ready for cross-checking."}
    from .model import LIMITATIONS
    return {"schema": SCHEMA, "engines": engines, "limitations": list(LIMITATIONS)}


def _terminate(process):
    from . import processes
    processes.terminate(process)


def _execute(command, request_data, folder, timeout_seconds, tick):
    """No shell, bounded output, kill descendants on timeout/cancel/raised callback."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    request_path, stdout_path, stderr_path = (folder / n for n in ("request.json", "response.json", "engine.log"))
    request_path.write_bytes(canonical(request_data))
    # A disposable cwd contains any engine-created caches. The Python Forge worker
    # still imports this exact checkout rather than depending on that cwd.
    from decklab.lib import config
    environment = dict(os.environ)
    for variable in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH"):
        environment.pop(variable, None)
    environment["PYTHONPATH"] = str(config.CHECKOUT) + os.pathsep + environment.get("PYTHONPATH", "")
    process = None
    began = time.monotonic()
    try:
        from . import processes
        with stdout_path.open("wb") as output, stderr_path.open("wb") as error:
            process = processes.spawn([*command, str(request_path.resolve())], cwd=folder, env=environment,
                                      stdout=output, stderr=error)
            while process.poll() is None:
                tick()
                if time.monotonic() - began > timeout_seconds + STARTUP_SECONDS:
                    raise CrosscheckError("process-timeout")
                if stdout_path.stat().st_size > MAX_OUTPUT or stderr_path.stat().st_size > MAX_LOG:
                    raise CrosscheckError("process-output-limit")
                time.sleep(0.1)
        if stdout_path.stat().st_size > MAX_OUTPUT or stderr_path.stat().st_size > MAX_LOG:
            raise CrosscheckError("process-output-limit")
        if process.returncode:
            raise CrosscheckError("process-failed")
        raw = stdout_path.read_bytes()
        try:
            parsed = parse_json(raw)
        except (ValueError, UnicodeError):
            raise CrosscheckError("invalid-response") from None
        return parsed, hashlib.sha256(raw).hexdigest()
    finally:
        if process is not None:
            _terminate(process)


def _slot(name, tick):
    if name == "forge":
        return nullcontext()
    from decklab.lib.forge import slots
    return slots.claim(1, waiting=tick, poll=0.2, what="XMage cross-check")


def validate_response(value, name, request_data, expected_identity, provenance=None):
    """Refuse mismatched requests, unknown outcomes and accidental extra games."""
    canonical(value)
    if (not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != SCHEMA
            or value.get("engine") != name
            or value.get("request_sha256") != digest(request_data)
            or value.get("format") != request_data["format"]
            or type(value.get("seed")) is not int or value.get("seed") != request_data["seed"]):
        raise CrosscheckError("The simulator response does not match its exact request.")
    identity_key = "identity_sha256" if name == "xmage" else "engine_sha256"
    if value.get(identity_key) != expected_identity:
        raise CrosscheckError("The simulator changed after this cross-check was planned.")
    if provenance is not None and name == "xmage":
        for key in ("engine_sha256", "bridge_sha256", "bridge_source_sha256", "source_revision", "identity_sha256"):
            if value.get(key) != provenance.get(key):
                raise CrosscheckError("The simulator did not confirm its installed engine and bridge.")
    version = value.get("version")
    if not isinstance(version, str) or not version or len(version) > 160:
        raise CrosscheckError("The simulator response has no valid engine version.")
    role = request_data["decks"][0]["id"]
    games, coverage = value.get("games"), value.get("coverage")
    early_timeout = (value.get("status") == "timeout" and coverage == [] and isinstance(games, list)
                     and len(games) == 1 and isinstance(games[0], dict) and games[0].get("status") == "timeout")
    if not isinstance(coverage, list) or (len(coverage) != 2 and not early_timeout):
        raise CrosscheckError("The simulator did not confirm both exact deck lists.")
    known = {d["id"]: {c["name"] for key in ("main", "commander") for c in d[key]}
             for d in request_data["decks"]}
    counts = {d["id"]: sum(c["quantity"] for key in ("main", "commander") for c in d[key])
              for d in request_data["decks"]}
    seen = set()
    unsupported = False
    for item in coverage:
        if not isinstance(item, dict) or item.get("deck_id") not in known or item["deck_id"] in seen:
            raise CrosscheckError("The simulator returned invalid card coverage.")
        seen.add(item["deck_id"])
        missing = item.get("missing")
        if (not isinstance(missing, list) or len(missing) > 1000
                or any(not isinstance(card, str) or card not in known[item["deck_id"]] for card in missing)
                or len(set(missing)) != len(missing) or item.get("status") not in ("supported", "unsupported", "invalid")):
            raise CrosscheckError("The simulator returned invalid card coverage.")
        if item["status"] != "invalid" and ((item["status"] == "supported") != (not missing)):
            raise CrosscheckError("The simulator returned contradictory card coverage.")
        if (name == "xmage" and item["status"] == "supported"
                and (type(item.get("cards")) is not int or item["cards"] != counts[item["deck_id"]])):
            raise CrosscheckError("The simulator did not load every requested card unchanged.")
        unsupported |= bool(missing) or item["status"] == "invalid"
    if unsupported:
        if games != []:
            # XMage retains its initialized, nonplayed game stub after preflight
            # refusal. It is evidence of no game only under this exact contract.
            if (value.get("status") not in ("unsupported", "invalid") or not isinstance(games, list)
                    or len(games) != 1 or not isinstance(games[0], dict)):
                raise CrosscheckError("A simulator played a list with unsupported cards.")
            stub = games[0]
            if (stub.get("status") not in ("unsupported", "invalid") or stub.get("winner") is not None
                    or type(stub.get("turns")) is not int or stub["turns"] != 0 or stub.get("arm") != role
                    or type(stub.get("number")) is not int or stub["number"] != request_data["game_number"]
                    or type(stub.get("seed")) is not int or stub["seed"] != request_data["seed"]
                    or type(stub.get("starting_player")) is not int
                    or stub["starting_player"] != request_data.get("starting_player")):
                raise CrosscheckError("The simulator's preflight refusal did not match its exact request.")
        return None, coverage
    if not isinstance(games, list) or len(games) != 1:
        raise CrosscheckError("The simulator must return exactly one requested game.")
    game = games[0]
    if (not isinstance(game, dict) or game.get("arm") != role
            or type(game.get("number")) is not int or game["number"] != request_data["game_number"]
            or type(game.get("seed")) is not int or game["seed"] != request_data["seed"]
            or game.get("status") not in ("completed", "timeout", "failed")):
        raise CrosscheckError("The simulator returned an unrequested or invalid game.")
    winner = game.get("winner")
    if ((game["status"] == "completed" and winner not in ("subject", "opponent", "draw"))
            or (game["status"] != "completed" and winner is not None)):
        raise CrosscheckError("A failed game cannot contribute a winner.")
    first = game.get("starting_player")
    if first is not None:
        integer(first, "The starting player", 0, 1)
    if name == "xmage" and first != request_data["starting_player"]:
        raise CrosscheckError("The simulator did not use the requested starting player.")
    turns = game.get("turns")
    if turns is not None:
        integer(turns, "The turn count", 0, 100000)
    output = {k: game.get(k) for k in ("arm", "number", "seed", "starting_player", "status", "winner", "turns")}
    output["reproducible"] = value.get("reproducible") is True
    return output, coverage


def play(name, request_data, expected_identity, folder, tick):
    found = details(name)
    if found.get("identity") != expected_identity:
        raise CrosscheckError("engine-changed")
    try:
        with _slot(name, tick):
            value, response_sha = _execute(found["command"], request_data, folder,
                                            request_data["timeout_seconds"], tick)
    except OSError:
        raise CrosscheckError("process-unavailable") from None
    game, coverage = validate_response(value, name, request_data, expected_identity, found.get("provenance"))
    if details(name).get("identity") != expected_identity:
        raise CrosscheckError("engine-changed")
    return {"game": game, "coverage": coverage, "response_sha256": response_sha,
            "version": value["version"], "provenance": found.get("provenance", {})}
