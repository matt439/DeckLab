"""The field view's API (simulation wave 3's R13, forge-trial/sim-wave3-contract.md section
10.5): GET /api/field, POST /api/field/run and POST /api/field/stop. A field run is a
coordinator job in api.forge_runs.COORD_JOBS (key "field:<space>:<card_sha>:<format>") that plays the
deck's matchups against the field through forge.field.run_field.

    field_view(deck_id, version, profile=None)
                        the view (forge.field.view) with "status" ("none", "queued", "running",
                        "done" or "error"), "job", "budgets", "field_lists", "default_budget",
                        "notice", "error" and "forge"; the server answers 202 while status is
                        "queued" or "running"
    run_field(body)     body {"profile", "id", "version"?, "budget"?, "expected_card_sha"?}:
                        start (or join) a field run; the answer as field_view's
    stop_field(body)    body {"profile", "id", "version"?}: Stop; the answer as field_view's

A field run's job holds a _FieldJob, whose "via" (kind, title, link) and "by" the matchup page
reads through api.forge_runs._job_for_key while one of its pairs plays.

The deck must be visible (_deck_sections: the missing-deck 404 otherwise). Home keeps its
existing field; a member's field uses their space and public spaces. Opponents, saved evidence,
ratings, notes and budgets follow the viewer's visibility. Jobs and notes are space-scoped;
legacy note paths are read only for home. Names from other spaces are "someone". Stop requires
a visible run started by the viewer or using their space's deck, or an admin (E10-S31).
"""
import traceback
from urllib.parse import quote

from decklab.lib import decks, jobs, permissions

from . import common, forge_runs
from .common import MAX_BODY, MAX_EDIT_BODY, ApiError, _keys, _parse_body, _public, _SHA_RE
from .library import _deck_sections, _half_title, check_deck_id, is_half
from . import guard
from .settings import _current_settings, _require_profile, _writer, own_settings_id

FIELD_BUSY = ("4 field runs or tests of changes are already waiting to be played. Try again when one of them "
              "has finished.")
FIELD_FAILED = ("Something went wrong on the PC while Forge was playing the field. Try again; if it keeps "
                "happening, the server window says why.")
FIELD_NO_SUMMARY = "The field view can't be worked out on the PC now (the server log says why)."


class _FieldJob:
    """What a field run's COORD_JOBS job runs (forge.field.run_field), and what the answers need
    of it while it waits or plays: the entry, the budget, who started it, and "via" for the
    matchup pages of its pairs."""

    kind = "field"

    def __init__(self, forge, entry, budget, by, options=None, by_id=None):
        self.forge, self.entry, self.budget, self.by = forge, entry, budget, by
        self.options = options or {}
        self.by_id = by_id
        version = entry["version"]
        # The deck page's address (app.js: #/deck?id=&v=), with part=field: field.js scrolls to its part.
        self.via = {"kind": "field", "title": f"Field run of {entry['title']}",
                    "link": f"#/deck?id={quote(entry['id'], safe='')}&v={version}&part=field"}

    def __call__(self, progress):
        return self.forge.field.run_field(self.entry, self.budget, by=self.by, progress=progress, **self.options)


def job_key(forge, entry):
    """The COORD_JOBS key: "field:<space>:<card_sha>:<format>"."""
    space = permissions._deck_space(entry.get("id")) or permissions.HOME
    return f"field:{space}:{entry['card_sha']}:{forge.fmt_for(entry['kind'])}"


def _field_options(forge, entry, seen):
    """A field's owner space and this viewer's immutable read rules for a run or answer."""
    public = frozenset(guard.public_deck_spaces())
    return {"space": permissions._deck_space(entry.get("id")) or permissions.HOME,
            "public": lambda space: space in public, "visible": seen.deck,
            "keep": lambda result: seen.result(forge, result),
            "product_notes": seen.everything or seen.space == permissions.HOME}


def _field_entry(forge, deck_id, version):
    """(summary, entry) of a deck's list as it is today; ApiError as deck_view for the id or
    version, and 400 for a Beginner Box half (it only plays in a pairing)."""
    version = "target" if version is None else version
    summary, sections = _deck_sections(deck_id, version)
    if is_half(summary):
        raise ApiError(400, f"{_half_title(summary)} is half of a Beginner Box deck, which is only played "
                            f"shuffled together with another half: look at a pairing of two halves.")
    try:
        entry = forge.entry(summary["id"], version, summary["title"], decks.engine_kind(summary), sections)
    except forge.ForgeError as e:
        raise ApiError(400, _public(e)) from None
    return summary, entry


def _field_budget(profile_id):
    """A profile's "field_budget" setting (ApiError 404 for an unknown profile;
    "standard" when the database can't be read: settings._current_settings)."""
    _require_profile(profile_id)
    return _current_settings(profile_id).get("field_budget") or "standard"


def _budgets(forge, entry, options=None):
    """{"quick"/"standard"/"thorough": {"games": per opponent, "new_games": what it would play now,
    "minutes": [low, high] or None}} (forge.field.plan and forge.estimate.minutes); {} when the
    plan can't be worked out (logged)."""
    out = {}
    for budget in forge.field.BUDGETS:
        try:
            planned = forge.field.plan(entry, budget, **(options or {}))
        except Exception:
            common._log(f"The field budgets of {entry['title']} can't be worked out:\n{traceback.format_exc()}")
            return {}
        minutes = None
        try:
            found = forge.estimate.minutes([(entry, p["opponent"], p["games"]) for p in planned["pairs"]
                                            if p["games"] > 0]) if planned["new_games"] else (0, 0)
            minutes = [found[0], found[1]] if found else None
        except Exception:
            common._log(f"The field run's time can't be estimated:\n{traceback.format_exc()}")
        out[budget] = {"games": planned["per_opponent"], "new_games": planned["new_games"], "minutes": minutes}
    return out


def _job_json(job, snap):
    """The "job" of a field answer: section 10.3's detail, with status, ahead, done, total, by
    and started (seconds running, None while queued)."""
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    return {**detail, "status": snap["status"], "ahead": snap["ahead"], "done": snap["progress"]["done"],
            "total": snap["progress"]["total"], "by": job.fn.by, "started": snap["seconds"]}


def _seen_field(found, fields, seen):
    """(found, fields, whole): found (forge.field.view's) and fields (its field lists) with only
    the opponents and lists seen sees (forge_runs._Seen), and whole, whether every opponent is
    seen. While any opponent is left out, the average, rating, notes and last run (all worked
    out over every opponent) are None or empty, and coverage counts the opponents shown. The
    backend normally supplies an already filtered view. This extra boundary also rejects a
    stored note whose deck was deleted outside its former owner's space."""
    opponents = [o for o in found.get("opponents") or [] if seen.deck(o.get("id"))]
    fields = [e for e in fields if seen.deck(e.get("id"))]
    last = found.get("last_run")
    if isinstance(last, dict) and not seen.historical((last.get("deck") or {}).get("id")):
        found = dict(found, last_run=None)
    if len(opponents) == len(found.get("opponents") or []):
        return found, fields, True
    from decklab.lib.forge import seqstats
    floor = getattr(seqstats, "FIELD_FLOOR", None)
    covered = sum(1 for o in opponents if floor is not None and (o.get("games") or 0) >= floor)
    return dict(found, opponents=opponents, average=None, rating=None, notes=[], last_run=None,
                coverage={"with_floor": covered, "of": len(opponents)}), fields, False


def _answer(forge, summary, entry, profile=None, seen=None):
    """field_view's answer for entry (summary its library summary), as seen (a forge_runs._Seen,
    this request's when None) may see it."""
    seen = forge_runs._Seen() if seen is None else seen
    key = job_key(forge, entry)
    job = forge_runs.COORD_JOBS.get(key)
    if job is not None and not seen.coordinator(job):
        job = None      # hidden original decks or opponents never contribute progress/error text
    snap = forge_runs.COORD_JOBS.snapshot(job) if job is not None else None
    options = _field_options(forge, entry, seen)
    try:
        found = forge.field.view(entry, **options)
    except forge.ForgeError as e:
        raise ApiError(400, _public(e)) from None
    except Exception:
        common._log(f"The field view of {summary['id']} can't be worked out:\n{traceback.format_exc()}")
        raise ApiError(500, FIELD_NO_SUMMARY) from None
    progress = notice = error = None
    if snap is not None and snap["status"] in forge_runs.MATCHUP_WAITING:
        status, progress = snap["status"], _job_json(job, snap)
        progress["may_stop"] = seen.can_stop(job)
        pairs = progress.get("pairs") or {}
        shown = {key: pair for key, pair in pairs.items() if seen.deck((pair.get("opponent") or {}).get("id"))}
        if len(shown) != len(pairs):
            progress.update(pairs=shown, done=sum(p.get("done") or 0 for p in shown.values()),
                            total=sum(p.get("total") or 0 for p in shown.values()))
    else:
        played = any(o.get("games") for o in found.get("opponents", []))
        if snap is not None and snap["status"] == jobs.ERROR:
            if snap["error"] == jobs.STOPPED:
                by = f" by {seen.name(job.cancelled_by)}" if job.cancelled_by else ""
                notice = f"The field run was stopped{by}; every game that finished is kept."
            else:
                # COORD_JOBS describes a failure as matchups do; a field run's words say "the field".
                error = FIELD_FAILED if snap["error"] == forge_runs.MATCHUP_FAILED else snap["error"]
        status = "done" if played else "error" if error else "none"
    try:
        fields = forge.field.field_lists(found["format"], **{k: v for k, v in options.items() if k != "keep"})
    except Exception:
        common._log(f"The field's lists can't be listed:\n{traceback.format_exc()}")
        fields = []
    found, fields, whole = _seen_field(found, fields, seen)
    # The budgets are planned over every opponent, so they'd tell a hidden field's size: none then.
    return {**seen.mask(found), "status": status, "job": seen.mask(progress), "notice": notice, "error": error,
            "budgets": _budgets(forge, entry, options) if whole else {},
            "default_budget": _field_budget(profile) if profile is not None else "standard",
            "field_lists": [{"id": e["id"], "version": e["version"], "title": e["title"],
                             "kind": forge.page_kind(e["id"]), "card_sha": e["card_sha"]} for e in fields],
            "forge": forge.status()}


def field_view(deck_id, version="target", profile=None):
    """GET /api/field?id=&version=[&profile=] (section 10.5): the deck's list against the field
    of its format (forge.field.view: the opponents, the field average, the rating, coverage, the
    last run's note), with status ("queued" or "running" while its field run waits or plays,
    else "done" once any opponent has games, "error" when the last run failed with nothing
    played, or "none"), job (section 10.3's detail with status, done, total, by and started),
    notice (who stopped the last run), error (why it failed), budgets, field_lists,
    default_budget (the profile's field_budget, "standard" without one) and forge (status()).
    ApiError as deck_view for the id or version, 400 for a Beginner Box half, 404 for an
    unknown profile (to a script only), 500 when the matchup code or the view can't be worked
    out. default_budget is read only from the viewer's own settings (settings.own_settings_id,
    E10-S34): a ?profile= naming anyone else answers as without one."""
    forge = forge_runs._forge_module()
    summary, entry = _field_entry(forge, deck_id, version)
    return _answer(forge, summary, entry, own_settings_id(profile) if profile is not None else None)


def run_field(body):
    """POST /api/field/run {"profile", "id", "version"?, "budget"?, "expected_card_sha"?}: play the deck's
    list against the field. budget is one of forge.field.BUDGETS (the profile's field_budget
    when it's left out). A field run of the same list that's already waiting or playing is
    joined. Returns field_view's answer. ApiError as field_view, 400 for a budget that isn't
    one or a list the field has no opponent for (forge.field.NO_OPPONENTS), 403 without a
    profile or while the simulations setting refuses (api/simulations.py), and 503 when Forge isn't ready, COORD_JOBS has 4 waiting, or the server is
    stopping. An optional expected_card_sha (64 lowercase hex characters) guards the exact
    playable saved list: 409 if it changed, before checking Forge or submitting a job. Normal
    deck visibility and version refusals still apply before that comparison."""
    data = _parse_body(body, MAX_EDIT_BODY)
    profile = _writer(data)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    _keys(data, ("profile", "id"), ("version", "budget", "expected_card_sha"))
    forge = forge_runs._forge_module()
    budget = data.get("budget") or _field_budget(profile["id"])
    if budget not in forge.field.BUDGETS:
        raise ApiError(400, f"budget must be one of: {', '.join(forge.field.BUDGETS)}")
    summary, entry = _field_entry(forge, data["id"], data.get("version"))
    if "expected_card_sha" in data:
        expected = data["expected_card_sha"]
        if not isinstance(expected, str) or not _SHA_RE.fullmatch(expected):
            raise ApiError(400, "expected_card_sha must be 64 lowercase hexadecimal characters")
        if expected != entry["card_sha"]:
            raise ApiError(409, "The saved list changed before its field run could start. "
                           "Reload the saved deck before testing it again.")
    seen = forge_runs._Seen(profile)
    options = _field_options(forge, entry, seen)
    state = forge.status()
    if not state.get("ready"):
        raise ApiError(503, state.get("problem") or "Forge isn't ready to play games on the PC.")
    try:
        opponents = forge.field.opponents(entry, **{k: v for k, v in options.items()
                                                   if k in ("space", "public", "visible")})
    except ValueError as e:
        raise ApiError(400, _public(e)) from None
    if not opponents:
        raise ApiError(400, forge.field.NO_OPPONENTS.format(fmt=forge.fmt_for(entry["kind"])))
    run = _FieldJob(forge, entry, budget, profile["name"], options, by_id=profile["id"])
    try:
        forge_runs.COORD_JOBS.submit(job_key(forge, entry), run, rerun=True)
    except jobs.Busy as e:
        raise ApiError(503, forge_runs.MATCHUP_STOPPING if e.stopping else FIELD_BUSY) from None
    return _answer(forge, summary, entry, profile["id"], seen)


def stop_field(body):
    """POST /api/field/stop {"profile", "id", "version"?} (section 10.5): Stop the list's field
    run. A waiting one is taken off the queue; a playing one stops every pair run (each keeps
    its finished games), then the coordinator (this waits up to forge_runs.STOP_WAIT seconds).
    Stopping when nothing waits or plays changes nothing. Returns field_view's answer. ApiError
    as field_view: first 404 "No deck <id>" for a deck the profile may not see (as for a missing
    one), then the run.stop rule for its starter, deck space or an admin. The key includes the
    deck's space, so another space's identical list cannot share this coordinator. An admin
    stops a hidden field from the anonymous running item through matchup/stop."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    if isinstance(data.get("id"), str):             # a hidden deck answers as a missing one, before the 403
        check_deck_id(data["id"])
        guard.require_sees_deck(data["id"], profile)
    _keys(data, ("profile", "id"), ("version",))
    forge = forge_runs._forge_module()
    summary, entry = _field_entry(forge, data["id"], data.get("version"))
    seen = forge_runs._Seen(profile)
    key = job_key(forge, entry)
    job = forge_runs.COORD_JOBS.get(key)
    if job is not None:
        seen.require_stop(job, seen.coordinator(job), forge_runs.MATCHUP_NO_KEY)
        if forge_runs.COORD_JOBS.cancel(key, by=profile["name"]):
            job.wait(forge_runs.STOP_WAIT)
    return _answer(forge, summary, entry, profile["id"], seen)
