"""Immutable, content-addressed receipts outside all Forge result readers."""
import json
import math
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .model import HASH, MAX_BYTES, SCHEMA, CrosscheckError, canonical, digest, engine_request, integer, text, validate_plan

ENGINE_STATES = ("complete", "partial", "unavailable", "unsupported", "invalid", "cancelled")
REASONS = (None, "bridge_unavailable", "engine_changed", "unsupported_cards", "invalid_list", "timeout",
           "process_failed", "invalid_response", "output_limit", "cancelled", "internal_error")


def _hash(value, optional=False):
    return (optional and value is None) or (isinstance(value, str) and HASH.fullmatch(value))


def _time(value):
    text(value, "A receipt timestamp", 80)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise CrosscheckError("The cross-check receipt has an invalid timestamp.") from None
    if parsed.tzinfo is None:
        raise CrosscheckError("Cross-check timestamps must include a timezone.")
    return parsed


def _coverage(value, plan):
    if not isinstance(value, list) or len(value) > 3:
        raise CrosscheckError("The receipt has invalid card-coverage evidence.")
    seen = set()
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("deck_id"), str):
            raise CrosscheckError("The receipt has invalid card-coverage evidence.")
        role = row["deck_id"]
        missing = row.get("missing")
        if (role not in plan["decks"] or role in seen or row.get("status") not in ("supported", "unsupported", "invalid")
                or not isinstance(missing, list) or len(missing) > 1000):
            raise CrosscheckError("The receipt has invalid card-coverage evidence.")
        seen.add(role)
        known = {n for rows in plan["decks"][role]["cards"].values() for _, n in rows}
        if any(not isinstance(n, str) or n not in known for n in missing) or len(set(missing)) != len(missing):
            raise CrosscheckError("The receipt's missing cards are not in its captured lists.")
        if row["status"] != "invalid" and ((row["status"] == "supported") != (not missing)):
            raise CrosscheckError("The receipt has contradictory card coverage.")
    return value


def folder(results_dir=None):
    from decklab.lib import config
    return Path(results_dir) if results_dir is not None else config.DATA / "crosscheck"


def validate_receipt(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != SCHEMA:
        raise CrosscheckError("This cross-check receipt has an unsupported schema.")
    result = deepcopy(value)
    found = result.pop("id", None)
    if not isinstance(found, str) or not HASH.fullmatch(found) or digest(result) != found:
        raise CrosscheckError("The cross-check receipt fingerprint does not match its contents.")
    plan = validate_plan(result.get("plan"))
    if result.get("status") not in ("completed", "partial", "cancelled", "error"):
        raise CrosscheckError("The receipt has an invalid overall status.")
    if _time(result.get("finished")) < _time(result.get("created")):
        raise CrosscheckError("The receipt finishes before it starts.")
    text(result.get("by"), "The receipt actor", 80)
    integer(result.get("run_nonce"), "The receipt run identity", 1, 1 << 80)
    engines = result.get("engines")
    if not isinstance(engines, dict) or set(engines) != set(plan["engines"]):
        raise CrosscheckError("The receipt does not cover its requested simulators.")
    arms = [r for r in ("baseline", "variant") if r in plan["decks"]]
    for name, engine in engines.items():
        if (not isinstance(engine, dict) or engine.get("identity") != plan["engine_identities"][name]
                or engine.get("status") not in ENGINE_STATES or engine.get("reason_code") not in REASONS
                or not isinstance(engine.get("games"), list) or len(engine["games"]) > plan["games"] * len(arms)):
            raise CrosscheckError("The receipt contains an invalid simulator result.")
        _coverage(engine.get("coverage"), plan)
        if engine.get("problem") is not None:
            text(engine["problem"], "The simulator explanation", 300)
        if engine["games"]:
            if not _hash(engine["identity"]):
                raise CrosscheckError("A played game must identify its simulator build.")
            text(engine.get("version"), "The simulator version", 160)
        seen = set()
        for game in engine["games"]:
            if not isinstance(game, dict):
                raise CrosscheckError("The receipt contains an invalid game.")
            role, number = game.get("arm"), game.get("number")
            if (not isinstance(role, str) or role not in arms or type(number) is not int or not 1 <= number <= plan["games"]
                    or (role, number) in seen or type(game.get("seed")) is not int
                    or game["seed"] != plan["seed"] + number - 1
                    or game.get("status") not in ("completed", "timeout", "failed")):
                raise CrosscheckError("The receipt contains a duplicate or unrequested game.")
            seen.add((role, number))
            if ((game["status"] == "completed" and game.get("winner") not in ("subject", "opponent", "draw"))
                    or (game["status"] != "completed" and game.get("winner") is not None)):
                raise CrosscheckError("An unsuccessful game cannot contribute a winner.")
            if type(game.get("reproducible")) is not bool:
                raise CrosscheckError("A game's reproducibility claim must be explicit.")
            if game.get("starting_player") is not None:
                integer(game["starting_player"], "The starting player", 0, 1)
            if game.get("turns") is not None:
                integer(game["turns"], "The turn count", 0, 100000)
            if game.get("request_sha256") != digest(engine_request(plan, name, role, number)):
                raise CrosscheckError("The receipt's game request does not match its exact lists and engine.")
            if not _hash(game.get("response_sha256"), optional=game["status"] != "completed"):
                raise CrosscheckError("A completed game's response fingerprint is required.")
            if game.get("reason_code") not in REASONS:
                raise CrosscheckError("The game has an invalid failure classification.")
        if engine["status"] == "complete" and (len(seen) != plan["games"] * len(arms)
                                                or any(g["status"] != "completed" for g in engine["games"])):
            raise CrosscheckError("An incomplete simulator result cannot be marked complete.")
    if result["status"] == "completed" and any(e["status"] != "complete" for e in engines.values()):
        raise CrosscheckError("An incomplete cross-check cannot be marked completed.")
    result["id"] = found
    return result


def save(receipt, results_dir=None):
    result = deepcopy(receipt)
    result.pop("id", None)
    result["id"] = digest(result)
    validate_receipt(result)
    target = folder(results_dir) / "results"
    target.mkdir(parents=True, exist_ok=True)
    path = target / (result["id"] + ".json")
    payload = canonical(result)
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=target)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            if path.read_bytes() != payload:
                raise CrosscheckError("An existing cross-check receipt cannot be overwritten.")
        else:
            os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
    return result


def load(receipt_id, results_dir=None):
    if not isinstance(receipt_id, str) or not HASH.fullmatch(receipt_id):
        return None
    path = folder(results_dir) / "results" / (receipt_id + ".json")
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        found = validate_receipt(json.loads(path.read_bytes()))
        return found if found["id"] == receipt_id else None
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return None


def receipts(results_dir=None):
    try:
        paths = []
        with os.scandir(folder(results_dir) / "results") as entries:
            for index, entry in enumerate(entries):
                if index == 10000:
                    break
                if entry.is_file(follow_symlinks=False) and entry.name.endswith(".json"):
                    paths.append((entry.stat().st_mtime_ns, Path(entry.path)))
        paths.sort(reverse=True)
    except OSError:
        return
    # Inspect at most 10,000 entries and read the newest 1,000 of those candidates.
    # Invalid receipts never become partial evidence.
    for _, path in paths[:1000]:
        found = load(path.stem, results_dir)
        if found is not None:
            yield found


def _arm(games, role, asked, cancelled=False):
    rows = [g for g in games if g["arm"] == role]
    completed = [g for g in rows if g["status"] == "completed"]
    wins = sum(g["winner"] == "subject" for g in completed)
    losses = sum(g["winner"] == "opponent" for g in completed)
    interval = None
    if completed:
        n, z = len(completed), 1.959963984540054
        p = wins / n
        denominator = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denominator
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
        interval = {"low": round(100 * max(0, centre - radius), 2),
                    "high": round(100 * min(1, centre + radius), 2), "confidence": 0.95}
    return {"asked": asked, "completed": len(completed), "wins": wins, "losses": losses,
            "draws": len(completed) - wins - losses, "failed": sum(g["status"] == "failed" for g in rows),
            "timeouts": sum(g["status"] == "timeout" for g in rows),
            "cancelled": asked - len(rows) if cancelled else 0,
            "unplayed": asked - len(rows),
            "win_rate": round(100 * wins / len(completed), 2) if completed else None,
            "win_rate_interval": interval}


def view(receipt, results_dir=None):
    result = load(receipt, results_dir) if isinstance(receipt, str) else validate_receipt(receipt)
    if result is None:
        return None
    plan = result["plan"]
    engines = {}
    for name, engine in result["engines"].items():
        baseline = _arm(engine["games"], "baseline", plan["games"], result["status"] == "cancelled")
        variant = (_arm(engine["games"], "variant", plan["games"], result["status"] == "cancelled")
                   if "variant" in plan["decks"] else None)
        delta = (round(variant["win_rate"] - baseline["win_rate"], 2)
                 if variant and variant["win_rate"] is not None and baseline["win_rate"] is not None else None)
        engines[name] = {"status": engine["status"], "version": engine.get("version"),
                         "identity": engine["identity"], "problem": engine.get("problem"), "baseline": baseline,
                         "variant": variant, "delta_percentage_points": delta,
                         "reason_code": engine.get("reason_code"),
                         "missing_cards": sorted({n for c in engine.get("coverage", []) for n in c.get("missing", [])}),
                         "reproducible": bool(engine["games"]) and all(g.get("reproducible") for g in engine["games"])}
    agreement = {"status": "not-compared", "text": "Separate simulator estimates; there is no combined win rate."}
    if "variant" in plan["decks"]:
        if len(engines) < 2 or any(e["status"] != "complete" for e in engines.values()):
            agreement = {"status": "incomplete", "text": "Incomplete evidence: compare each simulator's completed games separately."}
        else:
            signs = {0 if e["delta_percentage_points"] == 0 else 1 if e["delta_percentage_points"] > 0 else -1
                     for e in engines.values()}
            agrees = len(signs) == 1
            agreement = {"status": "same-direction" if agrees else "different-direction",
                         "text": "Both simulators show the same observed direction; sampling uncertainty may include no change." if agrees else
                                 "The observed directions differ; inspect each simulator's play and sampling uncertainty."}
    return {"id": result["id"], "plan_id": plan["id"], "format": plan["format"], "mode": plan["mode"],
            "games_per_arm": plan["games"], "has_variant": "variant" in plan["decks"],
            "created": result["created"], "finished": result["finished"], "status": result["status"],
            "decks": {role: {k: entry[k] for k in ("id", "title", "version", "card_sha")}
                      for role, entry in plan["decks"].items()}, "engines": engines, "agreement": agreement}
