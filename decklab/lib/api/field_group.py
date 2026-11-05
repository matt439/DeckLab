"""The deck page's group run API (E3-S31, closing E3-S19's criterion 2): GET /api/field/group,
POST /api/field/group/run and POST /api/field/group/stop. Imported when first asked for, by
feature_routes.dispatch.

A group run plays the deck's list against a chosen group of house decks the viewer may see (their
own space's, or a space's whose decks are Public: guard.public_deck_spaces) through
forge.group.run, a field run (run_field) over the chosen decks' opponent_entries into the ordinary
results folder, so its games count in Rankings and the ratings like a field run's. It's a
coordinator job in api.forge_runs.COORD_JOBS under the key
"field:<space>:<card_sha>:<format>:group:<12 hex of the chosen lists>", so the Running list,
matchup pages' "via" and an admin's anonymous Stop treat it as a field run, titled "Group run of".

    group_view(deck_id, version="target", opponents=None, profile=None)
                        the deck against the group (forge.group.view: one row per chosen deck and
                        the group's average), with "status" ("none", "queued", "running", "done" or
                        "error"), "job", "notice", "error", "chosen", "choices" (the decks the viewer
                        may put in a group: same format, visible, never a trial or a Beginner Box
                        half), "budgets", "default_budget", "max_opponents" and "forge". With no
                        opponents it's the list's group run waiting or playing, if any, else just
                        the choices
    run_group(body)     body {"profile", "id", "version"?, "opponents": ["<deck id>[@version]", ...],
                        "budget"?, "expected_card_sha"?}: start (or join) a group run
    stop_group(body)    body {"profile", "id", "version"?}: Stop the list's group runs

Privacy: the deck and every chosen deck must be visible first; a hidden one answers exactly as a
missing deck (404 "No deck <id>", before any 403, 409 or 503), so no answer names a deck the
viewer can't see. Only lists and results show, never a space's counts. Starters and stoppers from
another space are "someone" (forge_runs._Seen.mask); Stop follows the field's run.stop rule (its
starter, its deck's space, or an admin). Nothing here writes the database.
"""
import hashlib
import importlib
import traceback
from urllib.parse import quote

from decklab.lib import decks, jobs, permissions

from . import common, field_page, forge_runs, guard
from .common import MAX_BODY, MAX_EDIT_BODY, ApiError, _keys, _parse_body, _public, _SHA_RE
from .library import _find_summary, check_deck_id, is_half
from .settings import _writer, own_settings_id

GROUP_BUSY = ("4 field runs, group runs or tests of changes are already waiting to be played. Try again when "
              "one of them has finished.")
GROUP_FAILED = ("Something went wrong on the PC while Forge was playing the group. Try again; if it keeps "
                "happening, the server window says why.")
NO_VIEW = "The group's results can't be worked out on the PC now (the server log says why)."
ALREADY_PLAYING = "A field or group run of this list is already playing: stop it first."
CHANGED = "The saved list changed before its group run could start. Reload the saved deck before testing it again."
TRIAL = "{title} is a trial of a precon, so it isn't an opponent."
VERSIONS = ("target", "owned")


def _group(forge):
    """forge.group (the tests give the stand-in forge one), or ApiError 500."""
    found = getattr(forge, "group", None)
    if found is not None:
        return found
    try:
        return importlib.import_module("decklab.lib.forge.group")
    except Exception:
        common._log("The group run isn't available:\n" + traceback.format_exc())
        raise ApiError(500, "Group runs aren't available (the server log says why)") from None


def _max(g):
    return int(getattr(g, "MAX_OPPONENTS", 12))


def _house_version(summary):
    """The list the field plays of a deck (forge.field._house_version's rule)."""
    built = summary.get("built_version")
    if summary.get("status") == "built" and built in summary.get("versions", []):
        return built
    return "target"


def _names(value, g):
    """The opponents a request gives (a list, or a comma-separated string) as ["<id>[@version]"];
    ApiError 400 for anything else or too many."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ApiError(400, "opponents must be a list of deck ids")
    value = [v.strip() for v in value if v.strip()]
    if len(value) > _max(g):
        raise ApiError(400, f"A group has at most {_max(g)} decks.")
    return value


def _split(name):
    deck_id, _, version = name.partition("@")
    deck_id, version = deck_id.strip(), version.strip() or None
    check_deck_id(deck_id)
    if version is not None and version not in VERSIONS:
        raise ApiError(400, f"version must be one of: {', '.join(VERSIONS)}")
    return deck_id, version


def _visible_first(deck_id, names, profile=False):
    """The missing-deck 404 for the deck or a chosen deck the viewer may not see, before any other
    refusal (profile False: the request's viewer)."""
    if isinstance(deck_id, str):
        check_deck_id(deck_id)
        guard.require_sees_deck(deck_id, profile)
    for name in names:
        guard.require_sees_deck(_split(name)[0], profile)


def _entries(forge, names):
    """The chosen decks' Forge entries in order (each one's version, else the list the field plays).
    ApiError as deck_view for one (404 for a hidden or missing deck), 400 for a trial or a half."""
    out = []
    for name in names:
        deck_id, version = _split(name)
        summary = _find_summary(deck_id)
        if summary.get("trial"):
            raise ApiError(400, TRIAL.format(title=summary["title"]))
        out.append(field_page._field_list(forge, summary["id"], version or _house_version(summary))[2])
    return out


def _space(entry):
    return permissions._deck_space(entry.get("id")) or permissions.HOME


def _list_prefix(forge, entry):
    """Every field and group job key of this list starts with this."""
    return field_page.job_key(forge, entry)


def job_key(forge, entry, chosen):
    """The COORD_JOBS key of a group run: the field run's key with ":group:<12 hex>" of the chosen lists."""
    names = sorted(f"{o['id']}@{o['version']}:{o.get('card_sha')}" for o in chosen)
    digest = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:12]
    return f"{_list_prefix(forge, entry)}:group:{digest}"


def _active(forge, entry):
    """The list's field and group jobs waiting or playing."""
    prefix = _list_prefix(forge, entry)
    return [j for j in forge_runs.COORD_JOBS.active() if j.key == prefix or j.key.startswith(prefix + ":group:")]


def _group_jobs(forge, entry):
    return [j for j in _active(forge, entry) if getattr(j.fn, "kind", None) == "group"]


def _shown_chosen(jobs_, seen):
    """The chosen decks of the first of jobs_ the viewer sees whole (seen.coordinator: its deck and
    every chosen deck, even before the run's first report), else []: never a hidden deck's id."""
    for job in jobs_:
        if seen.coordinator(job) and all(seen.deck(o.get("id")) for o in job.fn.chosen):
            return list(job.fn.chosen)
    return []


class _GroupJob(field_page._FieldJob):
    """What a group run's COORD_JOBS job runs (forge.group.run): a field job with the chosen decks."""

    kind = "group"

    def __init__(self, forge, g, entry, chosen, budget, by, options, by_id=None):
        super().__init__(forge, entry, budget, by, options, by_id=by_id)
        self.g, self.chosen = g, chosen
        self.via = {"kind": "field", "title": f"Group run of {entry['title']}",
                    "link": f"#/deck?id={quote(entry['id'], safe='')}&v={entry['version']}&part=group"}

    def __call__(self, progress):
        return self.g.run(self.entry, self.chosen, self.budget, by=self.by, progress=progress, **self.options)


def _choices(forge, entry, seen):
    """The decks the viewer (seen) may put in this list's group: visible, the same format, never the
    deck itself, a trial, a Beginner Box half or a deck that can't be read; {"id", "version", "title",
    "kind", "public"} (public: another space's, seen because its decks are Public), by title."""
    fmt = forge.fmt_for(entry["kind"])
    out = []
    for summary in decks.list_decks():
        if not seen.deck(summary["id"]) or summary.get("error") or summary.get("trial") or is_half(summary)                 or summary["id"] == entry["id"] or forge.fmt_for(decks.engine_kind(summary)) != fmt:
            continue
        space = permissions._deck_space(summary["id"]) or permissions.HOME
        out.append({"id": summary["id"], "version": _house_version(summary), "title": summary["title"],
                    "kind": forge.page_kind(summary["id"]),
                    "public": seen.space is not None and space != seen.space})
    out.sort(key=lambda c: (c["title"].casefold(), c["id"]))
    return out


def _progress(job, snap, seen):
    found = field_page._job_json(job, snap)
    found["may_stop"] = seen.can_stop(job)
    pairs = found.get("pairs") or {}
    shown = {key: pair for key, pair in pairs.items() if seen.deck((pair.get("opponent") or {}).get("id"))}
    if len(shown) != len(pairs):
        found.update(pairs=shown, done=sum(p.get("done") or 0 for p in shown.values()),
                     total=sum(p.get("total") or 0 for p in shown.values()))
    return found


def _answer(forge, g, entry, chosen, seen, profile_id=None):
    """group_view's answer for entry against chosen (Forge entries, all visible to seen)."""
    options = field_page._field_options(forge, entry, seen)
    job = forge_runs.COORD_JOBS.get(job_key(forge, entry, chosen)) if chosen else None
    if job is not None and not seen.coordinator(job):
        job = None
    snap = forge_runs.COORD_JOBS.snapshot(job) if job is not None else None
    found = {"opponents": [], "overall": None, "played": 0, "of": 0, "tally": None, "updated": None, "games": 0,
             "note": None}
    if chosen:
        try:
            found = g.view(entry, chosen, keep=options["keep"])
        except ValueError as e:
            raise ApiError(400, _public(e)) from None
        except forge.ForgeError as e:
            raise ApiError(400, _public(e)) from None
        except Exception:
            common._log(f"The group view of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
            raise ApiError(500, NO_VIEW) from None
    progress = notice = error = None
    if snap is not None and snap["status"] in forge_runs.MATCHUP_WAITING:
        status, progress = snap["status"], _progress(job, snap, seen)
    else:
        played = any(o.get("games") for o in found.get("opponents") or [])
        if snap is not None and snap["status"] == jobs.ERROR:
            if snap["error"] == jobs.STOPPED:
                by = f" by {seen.name(job.cancelled_by)}" if job.cancelled_by else ""
                notice = f"The group run was stopped{by}; every game that finished is kept."
            else:
                error = GROUP_FAILED if snap["error"] == forge_runs.MATCHUP_FAILED else snap["error"]
        status = "done" if played else "error" if error else "none"
    budgets = field_page._budgets(forge, entry, {"opponent_entries": chosen, "keep": options["keep"]}) if chosen else {}
    return {**seen.mask(found), "deck": {k: entry.get(k) for k in ("id", "version", "title", "card_sha")},
            "format": forge.fmt_for(entry["kind"]), "status": status, "job": seen.mask(progress),
            "notice": notice, "error": error, "chosen": [{"id": o["id"], "version": o["version"]} for o in chosen],
            "choices": _choices(forge, entry, seen),
            "budgets": budgets,
            "default_budget": field_page._field_budget(profile_id) if profile_id is not None else "standard",
            "max_opponents": _max(g), "forge": forge.status()}


def group_view(deck_id, version="target", opponents=None, profile=None):
    """GET /api/field/group?id=&version=&opponents=a,b[&profile=]: the deck's list against the chosen
    decks (comma-separated "<deck id>[@version]"; without them, the list's group run waiting or
    playing, else none). ApiError 404 for the deck or a chosen deck the viewer may not see (as for a
    missing one, first), as field_view for the id or version, 400 for a choice that isn't one (too
    many, twice, the deck itself or its very list, another format, a trial or a half), 500 when the
    view can't be worked out. default_budget is the viewer's own field_budget only."""
    forge = forge_runs._forge_module()
    g = _group(forge)
    names = _names(opponents, g)
    _visible_first(deck_id, names)
    summary, entry = field_page._field_entry(forge, deck_id, version)
    seen = forge_runs._Seen()
    if names:
        try:
            chosen = g.check(entry, _entries(forge, names))
        except ValueError as e:
            raise ApiError(400, _public(e)) from None
    else:
        chosen = _shown_chosen(_group_jobs(forge, entry), seen)
    return _answer(forge, g, entry, chosen, seen, own_settings_id(profile) if profile is not None else None)


def run_group(body):
    """POST /api/field/group/run: play the deck's list against the chosen decks with budget (one of
    forge.field.BUDGETS; the profile's field_budget when left out). A run of the same list and group
    already waiting or playing is joined. Returns group_view's answer. ApiError 404 first for the
    deck or a chosen deck the profile may not see, 403 without a profile or while the simulations
    setting refuses (guard.require_start), 400 for a budget or choice that isn't one, 409 while a
    field run or another group run of the list waits or plays, or when expected_card_sha (64
    lowercase hex characters) isn't the saved list's, and 503 when Forge isn't ready, COORD_JOBS has
    4 waiting or the server is stopping."""
    data = _parse_body(body, MAX_EDIT_BODY)
    profile = _writer(data)
    forge = forge_runs._forge_module()
    g = _group(forge)
    names = _names(data.get("opponents"), g)
    _visible_first(data.get("id"), names, profile)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    _keys(data, ("profile", "id", "opponents"), ("version", "budget", "expected_card_sha"))
    budget = data.get("budget") or field_page._field_budget(profile["id"])
    if budget not in forge.field.BUDGETS:
        raise ApiError(400, f"budget must be one of: {', '.join(forge.field.BUDGETS)}")
    if not names:
        raise ApiError(400, "Choose at least one deck for the group.")
    summary, entry = field_page._field_entry(forge, data["id"], data.get("version"))
    chosen = _entries(forge, names)
    try:
        chosen = g.check(entry, chosen)
    except ValueError as e:
        raise ApiError(400, _public(e)) from None
    if "expected_card_sha" in data:
        expected = data["expected_card_sha"]
        if not isinstance(expected, str) or not _SHA_RE.fullmatch(expected):
            raise ApiError(400, "expected_card_sha must be 64 lowercase hexadecimal characters")
        if expected != entry["card_sha"]:
            raise ApiError(409, CHANGED)
    state = forge.status()
    if not state.get("ready"):
        raise ApiError(503, state.get("problem") or "Forge isn't ready to play games on the PC.")
    seen = forge_runs._Seen(profile)
    options = field_page._field_options(forge, entry, seen)
    run = _GroupJob(forge, g, entry, chosen, budget, profile["name"],
                    {"space": options["space"], "keep": options["keep"]}, by_id=profile["id"])
    key = job_key(forge, entry, chosen)
    with field_page.SUBMIT_LOCK:
        # One run of a list at a time: a field run or another group would play the same pairs beside it.
        if any(j.key != key for j in _active(forge, entry)):
            raise ApiError(409, ALREADY_PLAYING)
        try:
            forge_runs.COORD_JOBS.submit(key, run, rerun=True)
        except jobs.Busy as e:
            raise ApiError(503, forge_runs.MATCHUP_STOPPING if e.stopping else GROUP_BUSY) from None
    return _answer(forge, g, entry, chosen, seen, profile["id"])


def stop_group(body):
    """POST /api/field/group/stop {"profile", "id", "version"?}: Stop the list's group runs waiting or
    playing (every game that finished is kept). Stopping when nothing waits or plays changes nothing.
    Returns group_view's answer for the group stopped. ApiError 404 first for a deck the profile may
    not see, then run.stop's 403 (its starter, its deck's space or an admin)."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _visible_first(data.get("id"), [], profile)
    _keys(data, ("profile", "id"), ("version",))
    forge = forge_runs._forge_module()
    g = _group(forge)
    summary, entry = field_page._field_entry(forge, data["id"], data.get("version"))
    seen = forge_runs._Seen(profile)
    playing = _group_jobs(forge, entry)
    for job in playing:
        seen.require_stop(job, seen.coordinator(job), forge_runs.MATCHUP_NO_KEY)
    for job in playing:
        if forge_runs.COORD_JOBS.cancel(job.key, by=profile["name"]):
            job.wait(forge_runs.STOP_WAIT)
    chosen = _shown_chosen(playing, seen)     # an admin's anonymous Stop names no hidden deck
    return _answer(forge, g, entry, chosen, seen, profile["id"])
