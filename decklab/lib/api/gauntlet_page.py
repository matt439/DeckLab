"""The deck page's "Against popular decks" API (decklab/design/gauntlet.md sections 6 and 8):
GET /api/gauntlet, GET /api/gauntlet/catalogue, POST /api/gauntlet/run and POST /api/gauntlet/stop.
Imported when first asked for, by feature_routes.dispatch.

A gauntlet run is a coordinator job in api.forge_runs.COORD_JOBS (key
"gauntlet:<space>:<card_sha>:<sample id>") that plays the deck's list against a saved sample of
outside sparring decks through forge.gauntlet.run (a field run over the sample, in the gauntlet's
own results folder, so Rankings and the ratings never see its games).

    gauntlet_view(deck_id, version, sample=None, size=None, colours=None, styles=None, tiers=None,
                  profile=None)
                        the deck against a sample (a saved one by id, else one drawn now with these
                        filters and not saved): forge.gauntlet.view's opponents and groups with
                        "status" ("none", "queued", "running", "done" or "error"), "job", "notice",
                        "error", "catalogue" (None until one is built: "build_command" says how),
                        "sample", "options", "budgets", "default_budget", "default_size" and "forge"
    catalogue_view(format)
                        a catalogue's public counts and credit, or "built": None
    run_gauntlet(body)  body {"profile", "id", "version"?, "budget"?, "expected_card_sha"?, "sample"?,
                        "size"?, "colours"?, "styles"?, "tiers"?}: start (or join) a run; the answer
                        as gauntlet_view's
    stop_gauntlet(body) body {"profile", "id", "version"?, "sample"?}: Stop; the answer as gauntlet_view's

Privacy (section 8): the deck must be visible first (the missing-deck 404 before any 403, 409 or
503). The gauntlet decks and the catalogue are public data; results are about the house list only,
and no answer names another house deck. Jobs are space-scoped; a starter or stopper from another
space is "someone" (forge_runs._Seen.mask). Stop follows the field's run.stop rule (its starter,
its deck's space, or an admin). Nothing here writes the database, so nothing is audited.
"""
import importlib
import re
import traceback
from urllib.parse import quote

from decklab.lib import jobs, permissions

from . import common, field_page, forge_runs, guard
from .common import MAX_BODY, MAX_EDIT_BODY, ApiError, _keys, _parse_body, _public, _SHA_RE
from .library import check_deck_id
from .settings import _writer

BUDGETS = ("fixed:50", "fixed:100", "fixed:200")
DEFAULT_BUDGET = "fixed:100"
SIZES = {"commander": (6, 12, 20), "constructed": (12, 24, 36)}
DEFAULT_SIZE = {"commander": 12, "constructed": 24}      # the page's (design section 7)
MAX_SIZE = 60
STYLES = ("aggro", "midrange", "control", "combo", "ramp")
TIERS = {"commander": ("core", "upgraded", "precon"),
         "constructed": ("precon", "easy", "medium", "hard", "very hard")}
BUILD = "python -m decklab.lib.forge gauntlet build --format {fmt}"
CREDIT = ("Average decks from EDHREC (edhrec.com), Commander precons from MTGJSON, and 60-card decks "
          "bundled with Forge.")
SAMPLE_RE = re.compile(r"sample:[0-9a-f]{12}")
GAUNTLET_BUSY = ("4 field runs, gauntlet runs or tests of changes are already waiting to be played. Try again "
                 "when one of them has finished.")
GAUNTLET_FAILED = ("Something went wrong on the PC while Forge was playing the gauntlet. Try again; if it keeps "
                   "happening, the server window says why.")
NO_VIEW = "The gauntlet's results can't be worked out on the PC now (the server log says why)."
NO_DECKS = "No popular deck matches those choices: choose fewer filters."
CHANGED = "The saved list changed before its gauntlet run could start. Reload the saved deck before testing it again."


def _gauntlet(forge):
    """forge.gauntlet (the tests give the stand-in forge one), or ApiError 500."""
    found = getattr(forge, "gauntlet", None)
    if found is not None:
        return found
    try:
        return importlib.import_module("decklab.lib.forge.gauntlet")
    except Exception:
        common._log("The gauntlet can't be loaded:\n" + traceback.format_exc())
        raise ApiError(500, "The gauntlet isn't available (the server log says why)") from None


def _format(entry):
    return "commander" if entry.get("kind") == "commander" else "constructed"


def _space(entry):
    return permissions._deck_space(entry.get("id")) or permissions.HOME


def _prefix(entry):
    return f"gauntlet:{_space(entry)}:{entry['card_sha']}:"


def job_key(entry, sample_id):
    """The COORD_JOBS key: "gauntlet:<space>:<card_sha>:<sample id>"."""
    return _prefix(entry) + sample_id


# ============================================================ the request's choices

def _words(value, allowed, what):
    """A comma-separated choice (or a list of them) as a sorted tuple within allowed, or None."""
    if value is None or value == "" or value == []:
        return None
    items = value if isinstance(value, list) else value.split(",") if isinstance(value, str) else None
    if items is None or not all(isinstance(item, str) for item in items):
        raise ApiError(400, f"{what} must be a comma-separated list")
    found = sorted({item.strip().lower() for item in items if item.strip()})
    wrong = [item for item in found if item not in allowed]
    if wrong:
        raise ApiError(400, f"{what} must be among: {', '.join(allowed)}")
    return tuple(found) or None


def _choices(fmt, sample=None, size=None, colours=None, styles=None, tiers=None):
    """The request's sample choices, checked: {"sample", "size", "colours", "styles", "tiers"}."""
    if sample is not None and (not isinstance(sample, str) or not SAMPLE_RE.fullmatch(sample)):
        raise ApiError(400, "sample must be a saved sample's id (sample: and 12 hexadecimal characters)")
    if size is None or size == "":
        size = DEFAULT_SIZE[fmt]
    elif isinstance(size, str) and size.isascii() and size.isdigit():
        size = int(size)
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_SIZE:
        raise ApiError(400, f"size must be a number of opponents from 1 to {MAX_SIZE}")
    if colours is not None and not isinstance(colours, str):
        raise ApiError(400, "colours must be colour letters, such as WU")
    letters = (colours or "").upper()
    if any(letter not in "WUBRG" for letter in letters):
        raise ApiError(400, "colours must be colour letters, such as WU")
    return {"sample": sample, "size": size, "colours": "".join(c for c in "WUBRG" if c in letters) or None,
            "styles": _words(styles, STYLES, "styles"), "tiers": _words(tiers, TIERS[fmt], "tiers")}


def _draw(g, fmt, choices, save):
    """The sample the choices name (a saved one, or one drawn now); ApiError 404 for a sample id
    that isn't saved, 400 for one of the other format; forge's ForgeError when there's no catalogue."""
    if choices["sample"]:
        try:
            found = g.sample(choices["sample"])
        except ValueError:
            raise ApiError(404, "There's no saved gauntlet sample with that id.") from None
        if found.get("format") != fmt:
            raise ApiError(400, f"That sample is of {found.get('format')} decks, but this deck plays {fmt}.")
        return found
    return g.draw(fmt, size=choices["size"], colours=choices["colours"], styles=choices["styles"],
                  tiers=choices["tiers"], save=save)


def _catalogue_json(cat):
    """A catalogue's public counts: {"built", "card_data", "decks", "playable", "tiers", "colours",
    "styles", "credit"}."""
    playable = [d for d in cat.get("decks") or [] if d.get("playable")]
    counts = {"tiers": {}, "colours": {}, "styles": {}}
    for deck in playable:
        for name, key in (("tiers", deck.get("tier")), ("colours", deck.get("identity") or "C"),
                          ("styles", (deck.get("style") or {}).get("primary"))):
            if isinstance(key, str):
                counts[name][key] = counts[name].get(key, 0) + 1
    return {"built": cat.get("built"), "card_data": cat.get("card_data"), "decks": len(cat.get("decks") or []),
            "playable": len(playable), **counts, "credit": CREDIT}


def catalogue_view(format="commander"):
    """GET /api/gauntlet/catalogue?format=: the format's catalogue counts (public data: no deck is
    involved), or {"built": None, "build_command"} before one is built. 400 for another format."""
    if format not in TIERS:
        raise ApiError(400, "format must be commander or constructed")
    forge = forge_runs._forge_module()
    g = _gauntlet(forge)
    out = {"format": format, "build_command": BUILD.format(fmt=format), "credit": CREDIT}
    try:
        cat = g.catalogue(format)
    except forge.ForgeError:
        return {**out, "built": None}
    return {**out, **_catalogue_json(cat)}


# ============================================================ the answer

def _keep(entry):
    """Saved results the view may use: this list's games against a gauntlet deck (by card_sha, so no
    house deck's id or title is ever read from them)."""
    sha = entry["card_sha"]

    def keep(result):
        sides = [s for s in result.get("sides") or [] if isinstance(s, dict)]
        if len(sides) != 2:
            return False
        mine = [s for s in sides if s.get("card_sha") == sha]
        other = [s for s in sides if s.get("card_sha") != sha]
        return bool(mine) and len(other) <= 1 and all(str(s.get("id") or "").startswith("gauntlet:") for s in other)
    return keep


def _sees_job(seen, job):
    """True when the viewer sees a gauntlet job: the house deck that started it (its opponents are
    public gauntlet decks)."""
    entry = getattr(job.fn, "entry", None)
    return isinstance(entry, dict) and (seen.everything or seen.historical(entry.get("id")))


def _find_job(entry, sample_id, seen):
    """(job, snapshot) of this list's gauntlet run: one waiting or playing (any sample) first, else
    the last one of sample_id; (None, None) when there's none the viewer sees."""
    prefix = _prefix(entry)
    job = next((j for j in forge_runs.COORD_JOBS.active() if j.key.startswith(prefix)), None)
    if job is None and sample_id:
        job = forge_runs.COORD_JOBS.get(prefix + sample_id)
    if job is None or not _sees_job(seen, job):
        return None, None
    return job, forge_runs.COORD_JOBS.snapshot(job)


def _source(src):
    """A gauntlet deck's source, as the page shows it: its kind, an https link (EDHREC's or
    MTGJSON's), EDHREC's rank and deck count, and when it was fetched."""
    src = src if isinstance(src, dict) else {}
    url = src.get("url") if isinstance(src.get("url"), str) else None
    if url and not url.startswith(("https://edhrec.com/", "https://mtgjson.com/")):
        url = None
    return {"kind": src.get("kind"), "url": url, "rank": src.get("rank"), "decks": src.get("decks"),
            "fetched": src.get("fetched")}


def _budgets(forge, g, entry, chosen):
    """{budget: {"games", "new_games", "minutes": [low, high] or None}}; {} when no plan can be
    worked out (logged)."""
    out = {}
    for budget in BUDGETS:
        try:
            planned = g.plan(entry, chosen, budget)
        except Exception:
            common._log(f"The gauntlet budgets of {entry['title']} can't be worked out:\n{traceback.format_exc()}")
            return {}
        minutes = None
        pairs = [(entry, p["opponent"], p["games"]) for p in planned.get("pairs") or [] if p.get("games")]
        try:
            found = forge.estimate.minutes(pairs, results_dir=g.results_dir()) if pairs else (0, 0)
            minutes = [found[0], found[1]] if found else None
        except Exception:
            common._log(f"The gauntlet run's time can't be estimated:\n{traceback.format_exc()}")
        out[budget] = {"games": planned.get("per_opponent"), "new_games": planned.get("new_games"),
                       "minutes": minutes}
    return out


def _progress(job, snap, seen):
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    out = {**detail, "status": snap["status"], "ahead": snap["ahead"], "done": snap["progress"]["done"],
           "total": snap["progress"]["total"], "by": job.fn.by, "started": snap["seconds"],
           "sample": job.fn.sample["id"], "budget": job.fn.budget}
    out.pop("deck", None)       # the house deck that started it: this page names its own
    out["may_stop"] = seen.can_stop(job)
    return out


def _base(forge, entry, fmt):
    return {"deck": {k: entry[k] for k in ("id", "version", "title", "card_sha")}, "format": fmt,
            "build_command": BUILD.format(fmt=fmt), "credit": CREDIT,
            "options": {"sizes": list(SIZES[fmt]), "colours": "WUBRG", "styles": list(STYLES),
                        "tiers": list(TIERS[fmt]), "budgets": list(BUDGETS)},
            "default_budget": DEFAULT_BUDGET, "default_size": DEFAULT_SIZE[fmt], "forge": forge.status(),
            "catalogue": None, "sample": None, "opponents": [], "groups": {}, "games": 0, "note": None,
            "notes": [], "status": "none", "job": None, "notice": None, "error": None, "budgets": {}}


def _answer(forge, g, entry, choices, seen):
    """gauntlet_view's answer for entry and the request's choices, as seen may see it."""
    fmt = _format(entry)
    out = _base(forge, entry, fmt)
    job, snap = _find_job(entry, choices["sample"], seen)
    playing = snap is not None and snap["status"] in forge_runs.MATCHUP_WAITING
    try:
        cat = g.catalogue(fmt)
        chosen = job.fn.sample if playing else _draw(g, fmt, choices, save=False)
    except forge.ForgeError:
        return out                      # no catalogue yet: the page shows build_command
    if not playing and job is None:
        job, snap = _find_job(entry, chosen["id"], seen)
    out["catalogue"] = _catalogue_json(cat)
    out["sample"] = {"id": chosen["id"], "size": chosen.get("size"), "filters": chosen.get("filters"),
                     "decks": len(chosen.get("decks") or [])}
    if chosen.get("decks"):
        try:
            found = g.view(entry, chosen, keep=_keep(entry))
        except (ValueError, forge.ForgeError) as e:
            raise ApiError(400, _public(e)) from None
        except Exception:
            common._log(f"The gauntlet view of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
            raise ApiError(500, NO_VIEW) from None
        out.update(opponents=[dict(o, source=_source(o.get("source"))) for o in found.get("opponents") or []],
                   groups=found.get("groups") or {}, games=found.get("games") or 0, note=found.get("note"),
                   notes=list(found.get("notes") or []))
    if playing:
        out.update(status=snap["status"], job=seen.mask(_progress(job, snap, seen)))
        return out
    if snap is not None and snap["status"] == jobs.ERROR:
        if snap["error"] == jobs.STOPPED:
            by = f" by {seen.name(job.cancelled_by)}" if job.cancelled_by else ""
            out["notice"] = f"The gauntlet run was stopped{by}; every game that finished is kept."
        else:
            out["error"] = GAUNTLET_FAILED if snap["error"] == forge_runs.MATCHUP_FAILED else snap["error"]
    out["status"] = "done" if out["games"] else "error" if out["error"] else "none"
    out["budgets"] = _budgets(forge, g, entry, chosen) if chosen.get("decks") else {}
    return out


def gauntlet_view(deck_id, version="target", sample=None, size=None, colours=None, styles=None, tiers=None,
                  profile=None):
    """GET /api/gauntlet?id=&version=[&sample=|&size=&colours=&styles=&tiers=][&profile=]: the list
    against a sample of popular decks (the module docstring). A sample drawn from the filters isn't
    saved until it's played. ApiError as deck_view for the id or version (404 first for a deck the
    viewer may not see), 400 for a Beginner Box half or a choice that isn't one, 404 for a sample id
    that isn't saved, 500 when the gauntlet can't be loaded or worked out. profile is accepted for
    the page's usual query and changes nothing."""
    if deck_id is None:
        raise ApiError(400, "The request needs id")
    forge = forge_runs._forge_module()
    summary, entry = field_page._field_entry(forge, deck_id, version or "target")
    g = _gauntlet(forge)
    choices = _choices(_format(entry), sample, size, colours, styles, tiers)
    return _answer(forge, g, entry, choices, forge_runs._Seen())


# ============================================================ run and stop

class _GauntletJob:
    """What a gauntlet run's COORD_JOBS job runs (forge.gauntlet.run), and what the answers need of
    it: the entry, the sample, the budget, who started it, and "via" for its pairs' matchup pages."""

    kind = "gauntlet"

    def __init__(self, g, entry, sample, budget, by, by_id):
        self.g, self.entry, self.sample, self.budget, self.by, self.by_id = g, entry, sample, budget, by, by_id
        self.space = _space(entry)
        self.via = {"kind": "gauntlet", "title": f"Gauntlet run of {entry['title']}",
                    "link": f"#/deck?id={quote(entry['id'], safe='')}&v={entry['version']}&part=gauntlet"}

    def __call__(self, progress):
        return self.g.run(self.entry, self.sample, self.budget, progress=progress, by=self.by, space=self.space)


def _visible_first(data, profile):
    """The missing-deck 404 for a deck the profile may not see, before any other refusal."""
    if isinstance(data.get("id"), str):
        check_deck_id(data["id"])
        guard.require_sees_deck(data["id"], profile)


def run_gauntlet(body):
    """POST /api/gauntlet/run: play the deck's list against the sample (the saved one named, else one
    drawn and saved now from the filters) with budget (fixed:N, one of BUDGETS). A run of the same
    list and sample already waiting or playing is joined. Returns gauntlet_view's answer. ApiError
    404 for a deck the profile may not see (before anything else), 403 without a profile or while
    the simulations setting refuses (guard.require_start), 400 for a choice that isn't one or a
    sample with no decks, 409 when expected_card_sha (64 lowercase hex characters) isn't the saved
    list's, and 503 when there's no catalogue, Forge isn't ready, COORD_JOBS has 4 waiting or the
    server is stopping."""
    data = _parse_body(body, MAX_EDIT_BODY)
    profile = _writer(data)
    _visible_first(data, profile)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    _keys(data, ("profile", "id"), ("version", "budget", "expected_card_sha", "sample", "size", "colours",
                                    "styles", "tiers"))
    budget = data.get("budget") or DEFAULT_BUDGET
    if budget not in BUDGETS:
        raise ApiError(400, f"budget must be one of: {', '.join(BUDGETS)}")
    forge = forge_runs._forge_module()
    summary, entry = field_page._field_entry(forge, data["id"], data.get("version"))
    fmt = _format(entry)
    choices = _choices(fmt, data.get("sample"), data.get("size"), data.get("colours"), data.get("styles"),
                       data.get("tiers"))
    if "expected_card_sha" in data:
        expected = data["expected_card_sha"]
        if not isinstance(expected, str) or not _SHA_RE.fullmatch(expected):
            raise ApiError(400, "expected_card_sha must be 64 lowercase hexadecimal characters")
        if expected != entry["card_sha"]:
            raise ApiError(409, CHANGED)
    g = _gauntlet(forge)
    try:
        g.catalogue(fmt)
    except forge.ForgeError as e:
        raise ApiError(503, _public(e)) from None
    state = forge.status()
    if not state.get("ready"):
        raise ApiError(503, state.get("problem") or "Forge isn't ready to play games on the PC.")
    try:
        chosen = _draw(g, fmt, choices, save=True)
        if not chosen.get("decks"):
            raise ApiError(400, NO_DECKS)
        g.entries(fmt, chosen["decks"])         # every deck still playable in today's catalogue
    except (ValueError, forge.ForgeError) as e:
        raise ApiError(400, _public(e)) from None
    seen = forge_runs._Seen(profile)
    run = _GauntletJob(g, entry, chosen, budget, profile["name"], profile["id"])
    try:
        forge_runs.COORD_JOBS.submit(job_key(entry, chosen["id"]), run, rerun=True)
    except jobs.Busy as e:
        raise ApiError(503, forge_runs.MATCHUP_STOPPING if e.stopping else GAUNTLET_BUSY) from None
    return _answer(forge, g, entry, dict(choices, sample=chosen["id"]), seen)


def stop_gauntlet(body):
    """POST /api/gauntlet/stop {"profile", "id", "version"?, "sample"?}: Stop the list's gauntlet run
    waiting or playing (any sample; every game that finished is kept). Stopping when nothing waits or
    plays changes nothing. Returns gauntlet_view's answer. ApiError 404 first for a deck the profile
    may not see, then run.stop's 403 (its starter, its deck's space or an admin)."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _visible_first(data, profile)
    _keys(data, ("profile", "id"), ("version", "sample"))
    forge = forge_runs._forge_module()
    summary, entry = field_page._field_entry(forge, data["id"], data.get("version"))
    g = _gauntlet(forge)
    choices = _choices(_format(entry), data.get("sample"))
    seen = forge_runs._Seen(profile)
    job = next((j for j in forge_runs.COORD_JOBS.active() if j.key.startswith(_prefix(entry))), None)
    if job is not None:
        seen.require_stop(job, _sees_job(seen, job), forge_runs.MATCHUP_NO_KEY)
        if forge_runs.COORD_JOBS.cancel(job.key, by=profile["name"]):
            job.wait(forge_runs.STOP_WAIT)
        choices["sample"] = job.fn.sample["id"]
    return _answer(forge, g, entry, choices, seen)
