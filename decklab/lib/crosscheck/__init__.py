"""Independent Magic simulator second opinions, with separate immutable evidence.

The web layer owns visibility, simulation permission and jobs. Callers freeze both
lists in one inventory snapshot and pass this package only those visible lists.
No cross-check result is read by Forge's rankings, card statistics or gauntlet.
"""
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from . import adapters, model, store
from .model import CrosscheckError, ENGINES, MAX_GAMES, MAX_SEED, SCHEMA
from .store import load, view

status = adapters.status


class CrosscheckStopped(CrosscheckError):
    """A stop preserves the completed evidence before control returns to jobs."""


def prepare_forge():
    """Explicitly prepare this checkout's Forge runtime; no games or downloads."""
    from decklab.lib.forge import install, runner
    setup = install._setup(remember=False)
    runner._prepare_user_dir(setup["user_dir"])
    return status()["engines"]["forge"]


def deck_entry(deck_id, version="target"):
    """Existing Forge entry for one saved list; use lists.one_snapshot around a pair."""
    from decklab.lib import decks
    from decklab.lib.forge import lists
    with lists.one_snapshot():
        summary = decks.find_summary(deck_id)
        if summary is None:
            raise decks.DeckNotFound(f"No deck {deck_id!r}")
        sections = decks.load_deck(summary["id"], version)
        return lists.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)


def plan(entry_a, entry_b, *, games=10, seed=1, timeout_seconds=120, remove=(), add=(),
         engines=ENGINES):
    baseline, opponent = model.snapshot(entry_a), model.snapshot(entry_b)
    if baseline["kind"] != opponent["kind"]:
        raise CrosscheckError("Both cross-check lists must use the same format.")
    if baseline["id"] == opponent["id"] and baseline["card_sha"] == opponent["card_sha"]:
        raise CrosscheckError("Choose a different opponent for the cross-check.")
    if isinstance(engines, str) or not isinstance(engines, (tuple, list)):
        raise CrosscheckError("Choose the simulators as a list.")
    if (not engines or len(engines) > 2 or any(not isinstance(e, str) or e not in ENGINES for e in engines)
            or len(set(engines)) != len(engines)):
        raise CrosscheckError("Choose Forge, XMage, or both once each.")
    model.integer(games, "Games per list", 1, MAX_GAMES)
    model.integer(seed, "The seed", 0, MAX_SEED)
    model.integer(timeout_seconds, "The game time limit", 5, 600)
    decks = {"baseline": baseline, "opponent": opponent}
    if remove or add:
        decks["variant"] = model.variant(baseline, remove, add)
    ready = status()["engines"]
    result = {"schema": SCHEMA, "format": "commander" if baseline["kind"] == "commander" else "casual",
              "mode": "one-on-one", "games": games, "seed": seed, "timeout_seconds": timeout_seconds,
              "engines": list(engines), "decks": decks,
              "engine_identities": {e: ready[e].get("identity") for e in engines}}
    result["id"] = model.digest(result)
    return model.validate_plan(result)


def assert_current(captured, entry_a, entry_b):
    """Fail closed if either current list/revision differs from a queued plan."""
    captured = model.validate_plan(captured)
    for role, entry in (("baseline", entry_a), ("opponent", entry_b)):
        if model.snapshot(entry) != captured["decks"][role]:
            raise CrosscheckError("A deck changed after this cross-check was planned. Refresh and plan it again.")
    return captured


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


_PROBLEMS = {
    "bridge_unavailable": "This simulator is not ready; no games were started for it.",
    "engine_changed": "The simulator changed after planning; plan the cross-check again.",
    "unsupported_cards": "The simulator cannot play the unchanged lists because some cards are unsupported.",
    "invalid_list": "The simulator refused the unchanged deck list.",
    "timeout": "Some games exceeded the time limit and are excluded from win rates.",
    "process_failed": "The simulator could not complete a game; it is excluded from win rates.",
    "invalid_response": "The simulator response could not be verified; it is excluded from win rates.",
    "output_limit": "The simulator exceeded the output limit; the game is excluded from win rates.",
    "cancelled": "The cross-check was stopped; completed games have been preserved.",
    "internal_error": "The cross-check could not finish; completed evidence has been preserved.",
}


def _failure(error):
    return {"engine-changed": "engine_changed", "process-timeout": "timeout",
            "process-failed": "process_failed", "process-unavailable": "bridge_unavailable",
            "process-output-limit": "output_limit"}.get(str(error), "invalid_response")


def run(captured, *, by="crosscheck", progress=None, stop=None, results_dir=None):
    """Run sequential one-game workers and persist a separate immutable receipt.

    Progress has the usual (done,total,detail) form and is called during process
    waits. A callback exception or stop kills descendants, saves partial evidence,
    then propagates with receipt_id. Frozen lists are never reread or rewritten.
    """
    captured = model.validate_plan(captured)
    model.text(by, "The run's actor", 80)
    arms = [arm for arm in ("baseline", "variant") if arm in captured["decks"]]
    total = len(captured["engines"]) * len(arms) * captured["games"]
    receipt = {"schema": SCHEMA, "plan": deepcopy(captured), "created": _now(), "finished": None,
               "run_nonce": time.time_ns(), "by": by, "status": "partial", "engines": {}}
    for name in captured["engines"]:
        receipt["engines"][name] = {"status": "unavailable", "version": None,
                                     "identity": captured["engine_identities"][name], "games": [],
                                     "coverage": [], "reason_code": "bridge_unavailable",
                                     "problem": _PROBLEMS["bridge_unavailable"]}
    done, current = 0, {}

    def tick():
        if stop is not None and (stop() if callable(stop) else stop.is_set()):
            raise CrosscheckStopped("The cross-check was stopped.")
        if progress is not None:
            progress(done, total, dict(current))

    raised = None
    work = store.folder(results_dir) / "work"
    work.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="run-", dir=work) as workspace:
            for name in captured["engines"]:
                engine = receipt["engines"][name]
                current = {"engine": name, "phase": "starting"}
                tick()
                try:
                    found = adapters.details(name)
                except (CrosscheckError, OSError, ValueError, RuntimeError, ImportError, KeyError):
                    continue
                engine["version"] = found.get("version")
                if not engine["identity"] or found.get("identity") != engine["identity"]:
                    engine.update(reason_code="engine_changed", problem=_PROBLEMS["engine_changed"])
                    continue
                engine.update(status="partial", reason_code=None, problem=None)
                halted = False
                for number in range(1, captured["games"] + 1):
                    for arm in arms:
                        current = {"engine": name, "arm": arm, "number": number, "phase": "playing"}
                        tick()
                        request = model.engine_request(captured, name, arm, number)
                        game_folder = Path(workspace) / f"{name}-{arm}-{number}"
                        try:
                            played = adapters.play(name, request, engine["identity"], game_folder, tick)
                            engine["coverage"] = played["coverage"]
                            engine["provenance"] = played["provenance"]
                            game = played["game"]
                            if game is None:
                                invalid = any(c["status"] == "invalid" for c in played["coverage"])
                                code = "invalid_list" if invalid else "unsupported_cards"
                                engine.update(status="invalid" if invalid else "unsupported", reason_code=code,
                                              problem=_PROBLEMS[code])
                                halted = True
                                break
                            game["request_sha256"] = model.digest(request)
                            game["response_sha256"] = played["response_sha256"]
                        except CrosscheckStopped:
                            raise
                        except CrosscheckError as error:
                            code = _failure(error)
                            game = {"arm": arm, "number": number, "seed": request["seed"],
                                    "starting_player": None, "status": "timeout" if code == "timeout" else "failed",
                                    "winner": None, "turns": None, "reproducible": False,
                                    "request_sha256": model.digest(request), "reason_code": code}
                            halted = code != "timeout"
                            engine.update(reason_code=code, problem=_PROBLEMS[code])
                        engine["games"].append(game)
                        done += 1
                        if game["status"] != "completed" and not engine.get("reason_code"):
                            code = "timeout" if game["status"] == "timeout" else "process_failed"
                            engine.update(reason_code=code, problem=_PROBLEMS[code])
                        tick()
                        if halted:
                            break
                    if halted:
                        break
                if (len(engine["games"]) == captured["games"] * len(arms)
                        and all(g["status"] == "completed" for g in engine["games"])):
                    engine.update(status="complete", reason_code=None, problem=None)
    except BaseException as error:
        from decklab.lib import jobs
        raised = error
        cancelled = isinstance(error, (KeyboardInterrupt, CrosscheckStopped, jobs.Stopped))
        receipt["status"] = "cancelled" if cancelled else "error"
        code = "cancelled" if cancelled else "internal_error"
        for engine in receipt["engines"].values():
            if engine["status"] not in ("complete", "unsupported", "invalid"):
                engine.update(status="cancelled" if cancelled else "partial", reason_code=code, problem=_PROBLEMS[code])
    receipt["finished"] = _now()
    if raised is None:
        receipt["status"] = "completed" if all(e["status"] == "complete" for e in receipt["engines"].values()) else "partial"
    saved = store.save(receipt, results_dir)
    if raised is not None:
        try:
            raised.receipt_id = saved["id"]
        except (AttributeError, TypeError):
            pass
        raise raised
    return saved


def results_for(deck_id, *, limit=20, results_dir=None):
    model.integer(limit, "The result limit", 1, 100)
    found = []
    for receipt in store.receipts(results_dir):
        if any(e["id"] == deck_id for e in receipt["plan"]["decks"].values()):
            found.append(view(receipt))
            if len(found) == limit:
                break
    return found


__all__ = ["CrosscheckError", "CrosscheckStopped", "status", "prepare_forge", "deck_entry", "plan", "assert_current",
           "run", "load", "view", "results_for"]
