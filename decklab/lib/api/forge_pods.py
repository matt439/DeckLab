"""Four-player Commander simulations, separate from head-to-head results.

Every selected or saved seat must still be visible before a response describes
the run. Jobs share COORD_JOBS and its normal starter/owner/admin Stop rules.
The only files written are Forge's isolated pod cache and run-recovery journal.
"""
import importlib
import traceback

from decklab.lib import decks, jobs, permissions

from . import common, forge_runs, guard, simulations
from .common import MAX_BODY, MAX_EDIT_BODY, ApiError, _keys, _parse_body, _public, _SHA_RE
from .library import _deck_sections, check_deck_id, is_half
from .settings import _writer

GAME_CHOICES = (16, 32, 64, 128)
DEFAULT_GAMES = 16
MISSING = "There is no visible pod run at that link."
CHANGED = "The saved lists or Forge engine changed. Review this pod again before starting it."
UNKNOWN_BRACKET = "Set a target bracket on each of the four Commander decks before starting a pod."
BRACKETS_APART = "Choose decks with the same or neighbouring target brackets for this pod."
BUSY = "4 simulation runs are already waiting. Try again when one has finished."
FAILED = "The pod run could not finish on the PC. Try again; the server log says why."


def _pods(forge):
    found = getattr(forge, "pods", None)
    return found if found is not None else importlib.import_module("decklab.lib.forge.pods")


def _key(value):
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ApiError(400, "That link isn't a pod run's address.")
    return value


def _games(value):
    if value is None:
        return DEFAULT_GAMES
    return forge_runs._games(value, GAME_CHOICES)


def _selections(value):
    if not isinstance(value, list) or len(value) != 4:
        raise ApiError(400, "Choose exactly four Commander decks for a pod.")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "Each pod seat needs a deck id and a version.")
        _keys(item, ("id",), ("version",))
        check_deck_id(item["id"])
        version = item.get("version") or "target"
        if version not in ("target", "owned"):
            raise ApiError(400, "A pod list's version must be target or owned.")
        out.append((item["id"], version))
    return out


def _visible_first(selections, profile=False):
    for deck_id, _ in selections:
        guard.require_sees_deck(deck_id, profile)


def _side(entry):
    return {key: entry.get(key) for key in ("id", "version", "title", "card_sha", "kind", "target_bracket")}


def _entries(forge, selections):
    if len({deck_id for deck_id, _ in selections}) != 4:
        raise ApiError(400, "Choose four different Commander decks for a pod.")
    out = []
    brackets = []
    for deck_id, version in selections:
        summary, sections = _deck_sections(deck_id, version)
        if is_half(summary) or decks.engine_kind(summary) != "commander":
            raise ApiError(400, "Every pod seat needs a Commander deck.")
        bracket = summary.get("target_bracket")
        brackets.append(bracket)
        try:
            entry = forge.entry(summary["id"], version, summary["title"], "commander", sections)
        except forge.ForgeError as error:
            raise ApiError(400, _public(error)) from None
        out.append(dict(entry, target_bracket=bracket))
    if any(type(bracket) is not int or not 1 <= bracket <= 5 for bracket in brackets):
        raise ApiError(400, UNKNOWN_BRACKET)
    if max(brackets) - min(brackets) > 1:
        raise ApiError(400, BRACKETS_APART)
    return out


def _choices(seen):
    out = []
    for summary in decks.list_decks():
        if (not seen.deck(summary.get("id")) or summary.get("error") or is_half(summary)
                or decks.engine_kind(summary) != "commander"):
            continue
        space = permissions._deck_space(summary["id"]) or permissions.HOME
        out.append({"id": summary["id"], "version": "target", "title": summary["title"],
                    "target_bracket": summary.get("target_bracket"),
                    "public": seen.space is not None and space != seen.space})
    return sorted(out, key=lambda choice: (choice["title"].casefold(), choice["id"]))


def _visible(saved, seen):
    sides = (saved.get("sides") or saved.get("decks")) if isinstance(saved, dict) else None
    return (isinstance(sides, list) and len(sides) == 4
            and all(isinstance(side, dict) and isinstance(side.get("id"), str)
                    and seen.historical(side["id"]) for side in sides))


def _safe(saved, seen):
    """Only the backend's public view, never recipes, process commands or raw failures."""
    if not _visible(saved, seen):
        return None
    keys = ("key", "kind", "games", "planned", "completed", "remaining", "summary", "statistical_only",
            "note", "updated", "created", "by", "stopped_by", "stopped", "state", "clock_s")
    out = {key: saved[key] for key in keys if key in saved}
    out["sides"] = [_side(side) for side in saved.get("sides") or saved.get("decks")]
    # The summary is a numeric projection produced by pods; by_deck uses the
    # same visible ids as sides, and contains no recipes or process failures.
    summary = saved.get("summary")
    if isinstance(summary, dict):
        out["summary"] = {key: summary[key] for key in
                          ("pods", "counted", "wins", "draws", "clock_stops", "failed_batches", "by_deck", "by_seat",
                           "ai_timeouts", "ai_timeout_pods", "minutes_per_pod") if key in summary}
    return seen.mask(out)


def _plan(pods, entries, games):
    try:
        eng = pods.engine_identity()
        return pods.plan(entries, games, eng=eng), eng
    except ValueError as error:
        raise ApiError(400, _public(error)) from None
    except Exception:
        common._log("The pod plan could not be prepared:\n" + traceback.format_exc())
        raise ApiError(503, "The pod plan can't be prepared on the PC right now.") from None


def _load(pods, key):
    """A corrupt or unreadable guessed address discloses no more than a missing one."""
    try:
        return pods.load(key)
    except Exception:
        return None


class _PodJob:
    kind = "pods"

    def __init__(self, forge, pods, entries, games, plan, eng, profile):
        self.forge, self.pods, self.sides, self.games = forge, pods, entries, games
        self.entry, self.chosen = entries[0], entries[1:]
        self.key, self.eng = plan["key"], eng
        self.by, self.by_id = profile["name"], profile["id"]
        self.via = {"kind": "pods", "title": "Four-player Commander pod",
                    "link": "#/forge-pods?key=" + self.key}

    def __call__(self, progress):
        return self.pods.run(self.sides, self.games, by=self.by, progress=progress, eng=self.eng,
                             expected_key=self.key)


def _job(key):
    return forge_runs.COORD_JOBS.get("pods:" + key)


def _answer(forge, pods, seen, key=None, plan=None):
    answer = {"key": key, "status": "none", "sides": [], "result": None, "job": None,
              "notice": None, "error": None, "choices": _choices(seen),
              "game_choices": list(GAME_CHOICES), "default_games": DEFAULT_GAMES,
              "forge": forge.status(), "simulations": simulations.view(seen.profile)}
    if key is None:
        answer["results"] = []
        if hasattr(pods, "results"):
            answer["results"] = [safe for saved in pods.results() if (safe := _safe(saved, seen)) is not None]
        answer["running"] = [item for item in forge_runs._running_items(seen=seen)
                             if item.get("kind") == "pods" and not item.get("hidden")]
        return answer
    job = _job(key)
    if job is not None and not seen.coordinator(job):
        job = None
    saved = _load(pods, key)
    result = _safe(saved, seen) if saved is not None else None
    reviewed = _safe(plan, seen) if plan is not None else None
    if job is None and result is None and reviewed is None:
        raise ApiError(404, MISSING)
    answer["result"] = result
    answer["sides"] = (result or reviewed or {}).get("sides") or [_side(side) for side in job.fn.sides]
    if reviewed is not None:
        answer["plan"] = {**reviewed, "games": plan["games"], "remaining": plan.get("remaining"),
                          "completed": plan.get("completed")}
    if result is not None:
        tally = result.get("summary") or {}
        answer["status"] = "error" if (result.get("state") == "error"
                                        or not tally.get("pods") and tally.get("failed_batches")) else "done"
        if answer["status"] == "error":
            answer["error"] = FAILED
        if result.get("state") == "stopped":
            answer["notice"] = "The pod run was stopped; every game that finished is kept."
        elif result.get("remaining") and result.get("state") == "running" and job is None:
            answer["notice"] = "This saved pod run is incomplete; every game that finished is kept."
    if job is not None:
        snap = forge_runs.COORD_JOBS.snapshot(job)
        if snap["status"] in forge_runs.MATCHUP_WAITING:
            answer["status"] = snap["status"]
            answer["job"] = {**jobs.queue_work(snap), "done": snap["progress"]["done"],
                             "total": snap["progress"]["total"], "status": snap["status"],
                             "ahead": snap["ahead"], "seconds": snap["seconds"], "by": seen.name(job.fn.by),
                             "may_stop": seen.can_stop(job)}
        elif snap["status"] == jobs.ERROR:
            if snap["error"] == jobs.STOPPED:
                answer["notice"] = "The pod run was stopped; every game that finished is kept."
            else:
                answer["error"] = FAILED if snap["error"] == forge_runs.MATCHUP_FAILED else snap["error"]
                answer["status"] = "error"
    return seen.mask(answer)


def pods_view(key=None):
    forge = forge_runs._forge_module()
    pods, seen = _pods(forge), forge_runs._Seen()
    return _answer(forge, pods, seen, _key(key) if key else None)


def plan_pods(body):
    data = _parse_body(body, MAX_EDIT_BODY)
    selections = _selections(data.get("decks"))
    _visible_first(selections)
    _keys(data, ("decks",), ("profile", "games"))
    forge = forge_runs._forge_module()
    pods, seen = _pods(forge), forge_runs._Seen()
    entries, games = _entries(forge, selections), _games(data.get("games"))
    plan, _ = _plan(pods, entries, games)
    return _answer(forge, pods, seen, plan["key"], plan)


def run_pods(body):
    data = _parse_body(body, MAX_EDIT_BODY)
    profile = _writer(data)
    selections = _selections(data.get("decks"))
    _visible_first(selections, profile)
    guard.require_start(profile)
    _keys(data, ("profile", "decks", "expected_key"), ("games",))
    forge = forge_runs._forge_module()
    pods, seen = _pods(forge), forge_runs._Seen(profile)
    entries, games = _entries(forge, selections), _games(data.get("games"))
    plan, eng = _plan(pods, entries, games)
    if _key(data["expected_key"]) != plan["key"]:
        raise ApiError(409, CHANGED)
    readiness = forge.status()
    if not readiness.get("ready"):
        raise ApiError(503, readiness.get("problem") or "Forge isn't ready to play games on the PC.")
    run = _PodJob(forge, pods, entries, games, plan, eng, profile)
    try:
        from . import run_recovery
        run_recovery.submit(forge, "pods", run, profile, data, "pods:" + run.key, rerun=True)
    except jobs.Busy as error:
        raise ApiError(503, forge_runs.MATCHUP_STOPPING if error.stopping else BUSY) from None
    return _answer(forge, pods, seen, run.key, plan)


def stop_pods(body):
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _keys(data, ("profile", "key"))
    key = _key(data["key"])
    forge, seen = forge_runs._forge_module(), forge_runs._Seen(profile)
    pods, job = _pods(forge), _job(key)
    saved = _load(pods, key)
    visible = ((job is not None and seen.coordinator(job)) or (saved is not None and _visible(saved, seen)))
    if job is None:
        if not visible:
            raise ApiError(404, MISSING)
        return _answer(forge, pods, seen, key)
    seen.require_stop(job, visible, MISSING)
    if forge_runs.COORD_JOBS.cancel(job.key, by=profile["name"]):
        job.wait(forge_runs.STOP_WAIT)
    if not visible:
        return {"key": key, "stopped": True, "hidden": True}
    return _answer(forge, pods, seen, key)
