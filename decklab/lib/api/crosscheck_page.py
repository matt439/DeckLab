"""Two independent simulators, with private, immutable results kept outside Forge's rankings.

Reading this page never starts an engine. A run freezes both saved lists, requires the
fingerprints the page read, and uses the existing simulations and run.stop permissions.
The local runner owns at most one check at a time; its progress callback also stops native
processes when the user cancels or the server shuts down.
"""
import importlib
import math
import re

from decklab.lib import decks, jobs
from . import common, forge_runs, guard, simulations
from .common import ApiError, MAX_BODY, _keys, _parse_body, _public, _SHA_RE
from .library import _deck_sections, is_half
from .settings import _writer

ENGINES = ("forge", "xmage")
GAME_CHOICES = (10, 20, 50)
MISSING = "There is no simulator check at that link."
FAILED = "The simulator check could not finish on the server PC. See the server log."
CHANGED = "One of these saved lists changed. Refresh this check before starting it."
WAITING = (jobs.QUEUED, jobs.RUNNING)


def _core():
    return importlib.import_module("decklab.lib.crosscheck")


def _describe(error):
    return jobs.STOPPED if isinstance(error, jobs.Stopped) else FAILED


CROSSCHECK_JOBS = jobs.Runner(max_running=1, max_queued=2, name="crosscheck", describe=_describe,
                              log=lambda text: common._log(text))


def _version(value):
    value = "target" if value is None else value
    if value not in ("target", "owned"):
        raise ApiError(400, "version must be target or owned")
    return value


def _test(value):
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ApiError(400, "That link is not a simulator check's address.")
    return value


def _entry(deck_id, version):
    summary, _ = _deck_sections(deck_id, version)
    if is_half(summary):
        raise ApiError(400, "A Beginner Box half must be played in a pairing of two halves.")
    try:
        return _core().deck_entry(summary["id"], version)
    except ValueError as error:
        raise ApiError(400, _public(error)) from None


def _ref(entry):
    return {key: entry.get(key) for key in ("id", "version", "title", "card_sha")}


def _participants(record, seen):
    sides = record.get("decks") if isinstance(record, dict) else None
    return (isinstance(sides, dict) and set(sides) in ({"baseline", "opponent"}, {"baseline", "variant", "opponent"})
            and all(isinstance(side, dict) and seen.historical(side.get("id")) for side in sides.values()))


def _same_reference(side, entry):
    return side.get("id") == entry.get("id") and side.get("version") == entry.get("version")


def _choices(base, seen):
    choices = []
    for summary in [*decks.list_decks(), *decks.beginner_box_pairings()]:
        if (summary.get("error") or summary.get("id") == base["id"] or not seen.deck(summary.get("id"))
                or is_half(summary) or decks.engine_kind(summary) != base["kind"]):
            continue
        versions = summary.get("versions") or []
        version = "target" if "target" in versions else "owned" if "owned" in versions else None
        if version:
            choices.append({"id": summary["id"], "version": version, "title": summary["title"]})
    return sorted(choices, key=lambda row: (row["title"].casefold(), row["id"]))


def _engine_state():
    raw = _core().status().get("engines") or {}
    answer = {}
    for name in ENGINES:
        item = raw.get(name) or {}
        ready = item.get("ready") is True
        version = item.get("version")
        version = version if isinstance(version, str) and re.fullmatch(r"[\w .+\-]{1,120}", version) else None
        answer[name] = {"ready": ready, "version": version,
                        "problem": None if ready else ("Forge is not ready on the server PC." if name == "forge" else
                            "XMage's local bridge is not ready on the server PC. Ask the server's administrator to set it up.")}
    return answer


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _counts(raw):
    if not isinstance(raw, dict):
        return None
    out = {key: value if type(value := raw.get(key)) is int and 0 <= value <= 1_000_000 else 0
           for key in ("asked", "completed", "wins", "losses", "draws", "failed", "timeouts", "cancelled", "unplayed")}
    rate = _number(raw.get("win_rate"))
    out["win_rate"] = rate if rate is not None and 0 <= rate <= 100 else None
    interval = raw.get("win_rate_interval") or {}
    low, high = _number(interval.get("low")), _number(interval.get("high"))
    out["win_rate_interval"] = ({"low": low, "high": high, "confidence": 0.95}
        if rate is not None and low is not None and high is not None and 0 <= low <= rate <= high <= 100
        and interval.get("confidence") == 0.95 else None)
    return out


def _result(raw, baseline):
    """Only public simulation summaries leave the local result store; never raw logs or paths."""
    out = {key: raw.get(key) for key in ("id", "plan_id", "format", "mode", "games_per_arm", "has_variant",
                                        "created", "finished", "status")}
    out["decks"] = {role: _ref(side) for role, side in raw["decks"].items()}
    out["current"] = all(_current(side, baseline if role == "baseline" else None)
                         for role, side in raw["decks"].items() if role != "variant")
    out["engines"] = {}
    for name in ENGINES:
        item = (raw.get("engines") or {}).get(name) or {}
        missing = item.get("missing_cards")
        missing = [_public(card) for card in missing[:100] if isinstance(card, str) and 0 < len(card) <= 200
                   and not any(ord(character) < 32 for character in card)] if isinstance(missing, list) else []
        reason = item.get("reason_code")
        reason = reason if reason in {"unsupported_cards", "invalid_list", "timeout", "bridge_unavailable", "invalid_response",
                                      "engine_changed", "cancelled", "process_failed", "output_limit", "internal_error"} else None
        problem = ("Some cards are not supported by this simulator." if missing else
                   "Some games exceeded the time limit." if reason == "timeout" else
                   "This simulator could not complete this check." if item.get("problem") else None)
        out["engines"][name] = {"status": item.get("status"), "version": _public(item.get("version") or ""),
            "problem": problem, "reason_code": reason, "missing_cards": missing,
            "baseline": _counts(item.get("baseline")), "variant": _counts(item.get("variant")),
            "delta_percentage_points": _number(item.get("delta_percentage_points"))}
    agreement = raw.get("agreement") or {}
    out["agreement"] = {"status": agreement.get("status"), "text": _public(agreement.get("text") or "")}
    return out


def _current(side, known=None):
    try:
        current = known if known is not None else _entry(side["id"], _version(side.get("version")))
        return side.get("card_sha") == current.get("card_sha")
    except (ApiError, OSError, ValueError):
        return False


def _load_view(test):
    try:
        stored = _core().load(test)
        return _core().view(stored) if stored is not None else None
    except (OSError, ValueError):
        raise ApiError(503, "Saved simulator checks cannot be read on the server PC right now.") from None


def _history(baseline, seen, opponent=None):
    try:
        rows = _core().results_for(baseline["id"], limit=20)
    except (OSError, ValueError):
        raise ApiError(503, "Saved simulator checks cannot be read on the server PC right now.") from None
    return [row for row in rows if _participants(row, seen)
            and _same_reference(row["decks"]["baseline"], baseline)
            and (opponent is None or _same_reference(row["decks"]["opponent"], opponent))]


class _CheckRun:
    def __init__(self, planned, profile):
        self.plan = planned
        self.base, self.against = planned["decks"]["baseline"], planned["decks"]["opponent"]
        self.by, self.by_id = profile["name"], profile["id"]

    def __call__(self, progress):
        try:
            receipt = _core().run(self.plan, by=self.by, progress=progress)
        except BaseException as error:
            self.receipt_id = getattr(error, "receipt_id", None)
            raise
        return {"id": receipt["id"]}


def _job_json(job, seen):
    snap = CROSSCHECK_JOBS.snapshot(job)
    return seen.mask({"test": job.key, "status": snap["status"], "by": job.fn.by,
        "done": snap["progress"]["done"], "total": snap["progress"]["total"], "ahead": snap["ahead"],
        "may_stop": seen.can_stop(job), "error": snap["error"], "cancelled_by": job.cancelled_by})


def _answer(baseline, opponent, seen, test=None, job=None):
    raw = None
    if test is not None and job is None:
        job = CROSSCHECK_JOBS.get(test)
        if job is None:
            raw = _load_view(test)
            if raw is None or not _participants(raw, seen):
                raise ApiError(404, MISSING)
    if job is not None:
        if not _participants(job.fn.plan, seen):
            raise ApiError(404, MISSING)
        if not _same_reference(job.fn.base, baseline):
            raise ApiError(404, MISSING)
        snap = CROSSCHECK_JOBS.snapshot(job)
        result_id = (snap.get("result") or {}).get("id") or getattr(job.fn, "receipt_id", None)
        if result_id:
            raw = _load_view(result_id)
    if raw is not None:
        if not _participants(raw, seen) or not _same_reference(raw["decks"]["baseline"], baseline):
            raise ApiError(404, MISSING)
        if opponent is not None and not _same_reference(raw["decks"]["opponent"], opponent):
            raise ApiError(404, MISSING)
    history = _history(baseline, seen, opponent)
    if raw is None and history:
        raw = next((row for row in history if job is None or row.get("plan_id") == job.key), None)
    engine_state = _engine_state()
    gate = simulations.view(profile=seen.profile)
    result = _result(raw, baseline) if raw is not None else None
    if result and opponent is not None:
        result["current"] = result["current"] and raw["decks"]["opponent"].get("card_sha") == opponent.get("card_sha")
    job_json = _job_json(job, seen) if job is not None else None
    waiting = job_json is not None and job_json["status"] in WAITING
    return {"deck": _ref(baseline), "opponent": _ref(opponent) if opponent else None,
        "format": "commander" if baseline["kind"] == "commander" else "casual", "mode": "one-on-one",
        "choices": _choices(baseline, seen), "games_choices": list(GAME_CHOICES), "default_games": GAME_CHOICES[0],
        "engines": engine_state, "may_start": gate["may_start"], "why_not": gate["why_not"],
        "ready": all(row["ready"] for row in engine_state.values()),
        "test": job.key if waiting else result.get("id") if result else test,
        "status": job_json["status"] if job_json else result.get("status", "none") if result else "none",
        "job": job_json, "result": result,
        "note": "These are 1v1 games, including Commander; they do not predict a multiplayer pod."}


def check_view(deck_id, version="target", opponent=None, opponent_version="target", test=None):
    guard.require_sees_deck(deck_id)
    if opponent:
        guard.require_sees_deck(opponent)
    version, opponent_version = _version(version), _version(opponent_version)
    seen = forge_runs._Seen()
    baseline = _entry(deck_id, version)
    other = _entry(opponent, opponent_version) if opponent else None
    if other is not None and (other["kind"] != baseline["kind"] or other["id"] == baseline["id"]):
        raise ApiError(400, "Choose another deck of the same format.")
    if test is None and other is not None:
        job = next((item for item in CROSSCHECK_JOBS.active() if _participants(item.fn.plan, seen)
                    and _same_reference(item.fn.base, baseline) and _same_reference(item.fn.against, other)), None)
    else:
        job = None
    return _answer(baseline, other, seen, _test(test) if test is not None else None, job)


def run_check(body):
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    guard.require_sees_deck(data.get("id"), profile)
    guard.require_sees_deck(data.get("opponent"), profile)
    guard.require_start(profile)
    _keys(data, ("profile", "id", "opponent", "expected_card_sha", "expected_opponent_card_sha"),
          ("version", "opponent_version", "games"))
    baseline = _entry(data["id"], _version(data.get("version")))
    opponent = _entry(data["opponent"], _version(data.get("opponent_version")))
    for key, entry in (("expected_card_sha", baseline), ("expected_opponent_card_sha", opponent)):
        if not isinstance(data[key], str) or not _SHA_RE.fullmatch(data[key]):
            raise ApiError(400, f"{key} must be 64 lowercase hexadecimal characters")
        if data[key] != entry["card_sha"]:
            raise ApiError(409, CHANGED)
    games = data.get("games", GAME_CHOICES[0])
    if type(games) is not int or games not in GAME_CHOICES:
        raise ApiError(400, "games must be 10, 20 or 50 per simulator")
    if baseline["id"] == opponent["id"] or baseline["kind"] != opponent["kind"]:
        raise ApiError(400, "Choose another deck of the same format.")
    if not all(item["ready"] for item in _engine_state().values()):
        raise ApiError(503, "Both Forge and XMage must be ready on the server PC before starting this check.")
    try:
        planned = _core().plan(baseline, opponent, games=games, seed=1, timeout_seconds=120, engines=ENGINES)
        _core().assert_current(planned, baseline, opponent)
    except ValueError as error:
        raise ApiError(400, _public(error)) from None
    try:
        job = CROSSCHECK_JOBS.submit(planned["id"], _CheckRun(planned, profile), rerun=True)
    except jobs.Busy as error:
        raise ApiError(503, "Deck Lab is stopping; no new simulator check can start." if error.stopping else
                       "Two simulator checks are already waiting. Try again after one finishes.") from None
    return _answer(baseline, opponent, forge_runs._Seen(profile), job=job)


def stop_check(body):
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _keys(data, ("profile", "test"))
    test, seen = _test(data["test"]), forge_runs._Seen(profile)
    job = CROSSCHECK_JOBS.get(test)
    if job is None:
        raise ApiError(404, MISSING)
    visible = _participants(job.fn.plan, seen)
    seen.require_stop(job, visible, MISSING)
    stopped = CROSSCHECK_JOBS.cancel(test, by=profile["name"])
    if not visible:
        return {"test": test, "stopped": stopped, "hidden": True}
    return _answer(job.fn.base, job.fn.against, seen, job=job)
