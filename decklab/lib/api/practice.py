"""Practice hands (lib/goldfish/, imported when first needed): the runner
JOBS, GET /api/goldfish, and the saved result deck_view shows.

JOBS and GOLDFISH_SETTINGS live here only: tests patch them here, and
forge_runs.stop_jobs reads practice.JOBS.
"""
import importlib
import traceback

from decklab.lib import decks, jobs

from . import common
from .common import ApiError, _public, _scrub
from .library import _deck_sections, is_half

# Settings for goldfish.cache_key() and get_or_simulate() (games, turns): empty
# means its defaults, 100,000 games per setup of 8 turns. Tests make them small.
GOLDFISH_SETTINGS = {}
# What a failed run says on the page, under "The practice games couldn't be
# played"; the Python error and its traceback go to the server log.
RUN_FAILED = ("Something went wrong on the PC while playing them. Try again; if it keeps happening, "
              "the server window says why.")


def _job_runner():
    """The background runner for simulations: one at a time (a practice-hand
    run already uses every core, config "goldfish_workers"), at most 20
    waiting, errors logged with their traceback and reported without paths."""
    return jobs.Runner(max_running=1, max_queued=20, log=lambda text: common._log(text),
                       describe=lambda error: _public(error), name="simulation")


JOBS = _job_runner()


def _goldfish_module():
    """decklab.lib.goldfish, or ApiError 500 (the traceback goes to the log)."""
    try:
        return importlib.import_module("decklab.lib.goldfish")
    except Exception:
        common._log("The practice-hand simulation can't be loaded:\n" + traceback.format_exc())
        raise ApiError(500, "The practice-hand simulation isn't available (the server log says why)") from None


def _run_goldfish(module, sections, kind, progress):
    """What a goldfish job runs, in the runner's thread: simulate and save."""
    return module.get_or_simulate(sections, kind, progress=progress, **GOLDFISH_SETTINGS)


def _goldfish_json(result):
    """A result for the page: a copy (a job's result is shared), with no paths in its warnings."""
    out = dict(result)
    out["warnings"] = _scrub(result.get("warnings") or [])
    return out


def _practice_saved(module, sections, kind):
    """(key, answer): the list's cache key, and the /api/goldfish answer
    that needs no run: its saved result, or an error for a deck too small
    to deal from (key None). answer is None when it has to be played."""
    try:
        key = module.cache_key(sections, kind, **GOLDFISH_SETTINGS)
    except ValueError as e:         # e.g. fewer than 8 cards to draw from
        return None, {"status": "error", "error": f"This deck can't be dealt practice hands: {_public(e)}."}
    saved = module.saved_result(key)
    return key, ({"status": "done", "result": _goldfish_json(saved)} if saved is not None else None)


def _deck_practice(summary, sections):
    """deck_view's "practice": the /api/goldfish answer when it's there
    without starting a run (a saved result, a run that finished but
    couldn't be saved, or a deck too small to deal from), so the page is
    drawn whole at once; otherwise None. Never fails the deck: a problem is
    logged, and the page asks /api/goldfish, which says what's wrong."""
    if is_half(summary):
        return None
    try:
        key, answer = _practice_saved(_goldfish_module(), sections, decks.engine_kind(summary))
        if answer is None:
            job = JOBS.get(f"goldfish:{key}")
            snap = JOBS.snapshot(job) if job is not None else None
            if snap is not None and snap["status"] == jobs.DONE:
                answer = {"status": "done", "result": _goldfish_json(snap["result"])}
        return answer
    except ApiError:
        return None                 # the module can't be loaded; _goldfish_module logged why
    except Exception:
        common._log(f"The practice-hand result for {summary['id']} can't be looked up:\n" + traceback.format_exc())
        return None


def goldfish(deck_id, version="target", retry=None):
    """GET /api/goldfish?id=<deck id>&version=target|owned[&retry=1]: the
    practice-hand simulation of one list of a deck (lib/goldfish/).

    - {"status": "done", "result": {...}}: a saved result (goldfish's result,
      with "cached"), at once; or the run that just finished.
    - {"status": "running", "queued": bool, "ahead": n, "progress": {"done",
      "total"}}: the run has started (or was already going for this list,
      from this phone or another: runs are keyed by goldfish.cache_key, so
      the same cards under two ids are one run), or is waiting behind ahead
      others. total is None until it has started. The page asks again about
      once a second; the server sends this with HTTP 202.
    - {"status": "error", "error": "..."}: the deck can't be dealt a hand
      (too few cards), or the run failed (RUN_FAILED, in plain words: the
      page's box already says the games couldn't be played, and the server
      log has the Python error and its traceback). A failed run keeps
      answering this until retry=1 starts it again.

    ApiError as deck_view for the id and version, 400 for a retry other than
    1, and 503 when 20 runs are already waiting."""
    if retry not in (None, "", "1"):
        raise ApiError(400, "retry must be 1 when it's given")
    summary, sections = _deck_sections(deck_id, version)
    kind = decks.engine_kind(summary)
    module = _goldfish_module()
    key, answer = _practice_saved(module, sections, kind)
    if answer is not None:
        return answer
    try:
        job = JOBS.submit(f"goldfish:{key}", _run_goldfish, module, sections, kind, rerun=retry == "1")
    except jobs.Busy:
        raise ApiError(503, "Deck Lab is busy with other simulations. Try again in a minute.") from None
    snap = JOBS.snapshot(job)
    if snap["status"] == jobs.DONE:
        return {"status": "done", "result": _goldfish_json(snap["result"])}
    if snap["status"] == jobs.ERROR:
        # The page's box already says the games couldn't be played; the reason
        # (a Python error) is in the server log, with its traceback.
        return {"status": "error", "error": RUN_FAILED}
    return {"status": "running", "queued": snap["status"] == jobs.QUEUED, "ahead": snap["ahead"],
            "progress": snap["progress"]}
