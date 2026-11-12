"""The deck page's "Against popular decks" API (decklab/design/gauntlet.md sections 6 and 8):
GET /api/gauntlet, GET /api/gauntlet/summary, GET /api/gauntlet/catalogue, POST /api/gauntlet/run and
POST /api/gauntlet/stop. Imported when first asked for, by feature_routes.dispatch.

A gauntlet run is a coordinator job in api.forge_runs.COORD_JOBS (key
"gauntlet:<space>:<card_sha>:<sample id>") that plays the deck's list against a saved sample of
outside sparring decks through forge.gauntlet.run (a field run over the sample, in the gauntlet's
own results folder, so Rankings and the ratings never see its games).

    gauntlet_view(deck_id, version, sample=None, size=None, colours=None, styles=None, tiers=None,
                  commander=None, profile=None)
                        the deck against a sample (a saved one by id, else one drawn now with these
                        filters and not saved): forge.gauntlet.view's opponents and groups with
                        "status" ("none", "queued", "running", "done" or "error"), "job", "notice",
                        "error", "catalogue" (None until one is built: "build_command" says how),
                        "sample", "standard" (the standard sample: {"id", "size", "tiers"}),
                        "is_standard", "options", "budgets", "default_budget", "default_size" and
                        "forge". With no choices it's the standard sample (E3-S33). For the standard
                        sample, "before", "compare" and "older" (E3-S34, gauntlet_summary's) and each
                        opponent's "before" and "moved"; None and False for any other sample.
                        commander="same" (E3-S49, Commander decks only): every playable catalogue
                        deck with the deck's own commanders instead of a sample (options'
                        "same_commander" says how many there are; the sample's "commander" names them)
    gauntlet_summary(deck_id, version="target", profile=None)
                        the deck's headline against the standard sample, from saved games only (no
                        estimate, no sample saved, nothing played; its docstring has the answer);
                        _summary_of is its work, which the board (api/gauntlet_board.py) shares
    catalogue_view(format)
                        a catalogue's public counts and credit, or "built": None
    run_gauntlet(body)  body {"profile", "id", "version"?, "budget"?, "expected_card_sha"?, "sample"?,
                        "size"?, "colours"?, "styles"?, "tiers"?, "commander"?}: start (or join) a run; the answer
                        as gauntlet_view's
    stop_gauntlet(body) body {"profile", "id", "version"?, "sample"?}: Stop; the answer as gauntlet_view's

Privacy (section 8): the deck must be visible first (the missing-deck 404 before any 403, 409 or
503). The gauntlet decks and the catalogue are public data; results are about the house list only,
and no answer names another house deck. Jobs are space-scoped; a starter or stopper from another
space is "someone" (forge_runs._Seen.mask). Stop follows the field's run.stop rule (its starter,
its deck's space, or an admin). Nothing here writes the database, so nothing is audited.
"""
import contextlib
import importlib
import re
import threading
import traceback
from datetime import datetime, timezone
from urllib.parse import quote

from decklab.lib import jobs, permissions
from decklab.lib.gauntlet import is_gauntlet_id, trial_excluded, without
from decklab.lib.gauntlet.sample import STANDARD, is_own_sample

from . import common, field_page, forge_runs, gauntlet_before, guard
from .common import MAX_BODY, MAX_EDIT_BODY, ApiError, _keys, _parse_body, _public, _SHA_RE
from .library import check_deck_id
from .settings import _writer

BUDGETS = ("fixed:50", "fixed:100", "fixed:200")
DEFAULT_BUDGET = "fixed:100"
# The page's sizes (E3-S38, Matt 2026-11-03): up to every playable deck of the chosen tiers for
# Commander ("all"), run overnight; 60-card's catalogue is too big for "all".
ALL = "all"
SIZES = {"commander": (6, 12, 20, 40, ALL), "constructed": (12, 24, 36, 72, 144)}
DEFAULT_SIZE = {"commander": 20, "constructed": 24}      # the standard sample's (lib/gauntlet/sample.STANDARD)
MAX_SIZE = 300
OVERNIGHT_MINUTES = 120         # a run whose high estimate is longer is an overnight run
STYLES = ("aggro", "midrange", "control", "combo", "ramp")
TIERS = {"commander": ("core", "upgraded", "precon"),
         "constructed": ("precon", "easy", "medium", "hard", "very hard")}
BUILD = "python -m decklab.lib.forge gauntlet build --format {fmt}"
CREDIT = ("Average decks from EDHREC (edhrec.com), Commander precons from MTGJSON, and 60-card decks "
          "bundled with Forge.")
SHORT_SHA = 8                   # the characters of the catalogue's sha the pages show (E3-S43)
OLD_DAYS = 90                   # from this age the "Popular decks list built" line adds how old it is
SAMPLE_RE = re.compile(r"sample:[0-9a-f]{12}")
GAUNTLET_BUSY = ("4 field runs, gauntlet runs or tests of changes are already waiting to be played. Try again "
                 "when one of them has finished.")
ALREADY_PLAYING = "A gauntlet run of this list is already playing (another sample): stop it first."
_SUBMIT_LOCK = threading.Lock()     # the check for another sample's run and the submit, as one step
GAUNTLET_FAILED = ("Something went wrong on the PC while Forge was playing the gauntlet. Try again; if it keeps "
                   "happening, the server window says why.")
NO_VIEW = "The gauntlet's results can't be worked out on the PC now (the server log says why)."
NO_DECKS = "No popular deck matches those choices: choose fewer filters."
# E3-S49's "Same commander": the commanders always come from the deck itself, never the request.
SAME = "same"
NOT_COMMANDER = "Same commander is only for Commander decks."
NO_COMMANDER = "This deck has no commander yet, so there's no commander to match."
SAME_ALONE = ("Same commander plays every popular deck with this deck's commander: it takes no size, colours, "
              "styles, tiers or saved sample.")
NO_SAME_COMMANDER = "The popular decks list has no other deck with this deck's commander."
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


def job_key(entry, sample_id, exclude=()):
    """The COORD_JOBS key: "gauntlet:<space>:<card_sha>:<sample id>", plus "|x=<ids>" for a trial
    deck's run (exclude: the catalogue ids it leaves out, gauntlet.trial_excluded), so a deck of
    the same list (the bought precon) never joins a run that leaves one of its opponents out."""
    return _prefix(entry) + sample_id + ("|x=" + ",".join(sorted(exclude)) if exclude else "")


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


def _same(fmt, commander, sample, size, colours, styles, tiers):
    """True when the request asks for "Same commander" (commander="same", E3-S49); ApiError 400 for
    another value, a deck that isn't a Commander deck or another choice given with it."""
    if commander is None or commander == "" or commander is False:
        return False
    if not isinstance(commander, str) or commander.strip().lower() != SAME:
        raise ApiError(400, f"commander must be {SAME}")
    if fmt != "commander":
        raise ApiError(400, NOT_COMMANDER)
    if any(value not in (None, "", []) for value in (sample, size, colours, styles, tiers)):
        raise ApiError(400, SAME_ALONE)
    return True


def _choices(fmt, sample=None, size=None, colours=None, styles=None, tiers=None, commander=None):
    """The request's sample choices, checked: {"sample", "size", "colours", "styles", "tiers",
    "commander" (True for E3-S49's Same commander, whose "commanders" the caller fills in from the
    deck: _with_commanders), "commanders"}."""
    if _same(fmt, commander, sample, size, colours, styles, tiers):
        return {"sample": None, "size": None, "colours": None, "styles": None, "tiers": None, "commander": True,
                "commanders": None}
    if sample is not None and (not isinstance(sample, str) or not SAMPLE_RE.fullmatch(sample)):
        raise ApiError(400, "sample must be a saved sample's id (sample: and 12 hexadecimal characters)")
    every = ALL in SIZES[fmt]
    if size is None or size == "":
        size = DEFAULT_SIZE[fmt]
    elif isinstance(size, str) and size.strip().lower() == ALL:
        size = ALL
    elif isinstance(size, str) and size.isascii() and size.isdigit():
        size = int(size)
    if (size != ALL or not every) and (isinstance(size, bool) or not isinstance(size, int)
                                       or not 1 <= size <= MAX_SIZE):
        raise ApiError(400, f"size must be a number of opponents from 1 to {MAX_SIZE}"
                       + (", or all" if every else ""))
    if colours is not None and not isinstance(colours, str):
        raise ApiError(400, "colours must be colour letters, such as WU")
    letters = (colours or "").upper()
    if any(letter not in "WUBRG" for letter in letters):
        raise ApiError(400, "colours must be colour letters, such as WU")
    return {"sample": sample, "size": size, "colours": "".join(c for c in "WUBRG" if c in letters) or None,
            "styles": _words(styles, STYLES, "styles"), "tiers": _words(tiers, TIERS[fmt], "tiers"),
            "commander": False, "commanders": None}


def _commanders(sections):
    """The deck's own commander names (its Commander section), never the request's."""
    return sorted({line.name for line in (sections or {}).get("Commander") or () if getattr(line, "name", "")})


def _with_commanders(choices, sections):
    """choices with "commanders" from the deck when it asks for Same commander; ApiError 400 for a
    Commander deck without one."""
    if not choices.get("commander"):
        return choices
    names = _commanders(sections)
    if not names:
        raise ApiError(400, NO_COMMANDER)
    return dict(choices, commanders=names)


def _same_count(fmt, cat, commanders, exclude):
    """options' "same_commander" (E3-S49): {"commanders": the deck's names, "decks": how many playable
    catalogue decks share them, a trial's own precon left out}; None for a 60-card deck or one
    without a commander."""
    if fmt != "commander" or not commanders:
        return None
    from decklab.lib.gauntlet.sample import same_commander
    left = [d for d in same_commander((cat or {}).get("decks") or [], commanders) if d.get("id") not in set(exclude)]
    return {"commanders": list(commanders), "decks": len(left)}


NOT_SAVED = "There's no saved gauntlet sample with that id."


def _draw(g, fmt, choices, save, cat=None, own=()):
    """The sample the choices name (a saved one, or one drawn now from cat, the catalogue already
    loaded, when given); ApiError 404 for a sample id that isn't saved, 400 for one of the other
    format; forge's ForgeError when there's no catalogue. own: the asking deck's commanders
    (_commanders). A saved Same commander sample (E3-S49) of other commanders answers exactly as an
    unsaved one, before any other check, so its id never tells whether a deck (perhaps one of a
    hidden space's) played that commander."""
    if choices.get("commander"):
        return g.same_commander(fmt, choices["commanders"], save=save, cat=cat)
    if choices["sample"]:
        try:
            found = g.sample(choices["sample"])
        except ValueError:
            raise ApiError(404, NOT_SAVED) from None
        if not is_own_sample(found, own):
            raise ApiError(404, NOT_SAVED)
        if found.get("format") != fmt:
            raise ApiError(400, f"That sample is of {found.get('format')} decks, but this deck plays {fmt}.")
        return found
    return g.draw(fmt, size=choices["size"], colours=choices["colours"], styles=choices["styles"],
                  tiers=choices["tiers"], save=save, cat=cat)


def _is_standard_draw(fmt, choices):
    """True when the choices draw the standard sample (lib/gauntlet/sample.STANDARD: its size and
    tiers, no colour, style or saved sample), so the answer needn't draw it twice."""
    std = STANDARD[fmt]
    return (not choices.get("commander") and not choices["sample"] and choices["size"] == std["size"] and not choices["colours"]
            and not choices["styles"] and sorted(choices["tiers"] or std["tiers"]) == sorted(std["tiers"]))


def _standard(g, fmt, cat, chosen, choices, playing):
    """The format's standard sample: chosen when the choices drew it, else drawn from cat (no
    second read of the catalogue)."""
    if not playing and _is_standard_draw(fmt, choices):
        return chosen
    return g.standard(fmt, cat=cat)


def _is_saved(g, sample_id):
    """True when the sample is saved on the PC (a run saves its sample; a draw for the view doesn't)."""
    try:
        g.sample(sample_id)
    except ValueError:
        return False
    return True


def catalogue_stamp(cat, now=None):
    """When a catalogue was built and which one it is (E3-S43; public data, no deck involved):
    {"built": its build time as saved, "sha": the first SHORT_SHA characters of its sha or None,
    "age_days": whole days since it was built (None when "built" isn't a time), "old": True from
    OLD_DAYS days on, when the pages add a plain note of its age}. It never asks for a rebuild."""
    built, sha = cat.get("built"), cat.get("sha")
    try:
        when = datetime.fromisoformat(built)
    except (TypeError, ValueError):
        when = None
    age = None
    if when is not None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = max(0, ((now or datetime.now(timezone.utc)) - when).days)
    return {"built": built, "sha": sha[:SHORT_SHA] if isinstance(sha, str) and sha else None,
            "age_days": age, "old": age is not None and age >= OLD_DAYS}


def _catalogue_json(cat):
    """A catalogue's public counts: {"built", "sha", "age_days", "old" (catalogue_stamp), "card_data",
    "decks", "playable", "tiers", "colours", "styles", "credit"}."""
    from decklab.lib.gauntlet.screening import summary
    playable = [d for d in cat.get("decks") or [] if d.get("playable")]
    counts = {"tiers": {}, "colours": {}, "styles": {}}
    for deck in playable:
        for name, key in (("tiers", deck.get("tier")), ("colours", deck.get("identity") or "C"),
                          ("styles", (deck.get("style") or {}).get("primary"))):
            if isinstance(key, str):
                counts[name][key] = counts[name].get(key, 0) + 1
    return {**catalogue_stamp(cat), "card_data": cat.get("card_data"), "decks": len(cat.get("decks") or []),
            "playable": len(playable), **counts, "screening": summary(cat), "credit": CREDIT}


def _build_command(fmt, seen):
    """The catalogue's build command, for an admin only (it's run on the PC): None for anyone else."""
    return BUILD.format(fmt=fmt) if seen.admin else None


def catalogue_view(format="commander"):
    """GET /api/gauntlet/catalogue?format=: the format's catalogue counts (public data: no deck is
    involved) and its standard sample ({"id", "size", "tiers", "opponents"}, drawn but never saved;
    None when it can't be drawn), or {"built": None, "build_command"} before one is built (the command
    for an admin, None for anyone else). 400 for another format."""
    if format not in TIERS:
        raise ApiError(400, "format must be commander or constructed")
    forge = forge_runs._forge_module()
    g = _gauntlet(forge)
    out = {"format": format, "build_command": _build_command(format, forge_runs._Seen()), "credit": CREDIT}
    try:
        cat = g.catalogue(format)
    except forge.ForgeError:
        return {**out, "built": None}
    try:
        standard = g.standard(format, cat=cat)
        found = {**standard_json(standard), "opponents": len(standard.get("decks") or [])}
    except (forge.ForgeError, ValueError):
        found = None
    return {**out, **_catalogue_json(cat), "standard": found}


# ============================================================ the answer

def _side_ids(side):
    """The deck ids a stored side was played as: its own "id" (a test's) and its seen_as ids (the
    runner's, runner._seen)."""
    ids = {side.get("id")} | {s.get("id") for s in side.get("seen_as") or [] if isinstance(s, dict)}
    return {i for i in ids if i is not None}


def _keep(entry):
    """Saved results the view may use: this list's games against a gauntlet deck (by card_sha, so no
    house deck's title is ever read from them). The other side's ids must all be gauntlet ids, and
    there must be one (E3-S34 fixed this: real sides keep their ids under seen_as only), with a
    list of its own: an exact mirror (both sides this list) is never one (E3-S39)."""
    sha = entry["card_sha"]

    def keep(result):
        sides = [s for s in result.get("sides") or [] if isinstance(s, dict)]
        if len(sides) != 2:
            return False
        mine = [s for s in sides if s.get("card_sha") == sha]
        other = [s for s in sides if s.get("card_sha") != sha]
        if not mine or len(other) != 1:
            return False
        return all(bool(ids) and all(is_gauntlet_id(i) for i in ids) for ids in map(_side_ids, other))
    return keep


def _held(forge):
    """forge.engine.held(): today's engine worked out once for the request (a stand-in without it: none)."""
    held = getattr(getattr(forge, "engine", None), "held", None)
    return held() if held is not None else contextlib.nullcontext()


def _kept(forge, g, summary, entry, standard, cat, found):
    """gauntlet_before.fields for the standard sample's view found."""
    return gauntlet_before.fields(forge, g, summary, entry, standard, cat, found, _keep)


def _full(job):
    """A gauntlet job's sample before any trial exclusion (_GauntletJob.full)."""
    return getattr(job.fn, "full", None) or job.fn.sample


def _sees_job(seen, job):
    """True when the viewer sees a gauntlet job: the house deck that started it (its opponents are
    public gauntlet decks)."""
    entry = getattr(job.fn, "entry", None)
    return isinstance(entry, dict) and (seen.everything or seen.historical(entry.get("id")))


def _active(entry):
    """The list's gauntlet jobs waiting or playing, any sample."""
    prefix = _prefix(entry)
    return [j for j in forge_runs.COORD_JOBS.active() if j.key.startswith(prefix)]


def _find_job(entry, sample_id, seen, exclude=()):
    """(job, snapshot) of this list's gauntlet run: one waiting or playing (any sample) first, else
    the last one of sample_id (exclude: job_key's); (None, None) when there's none the viewer sees."""
    job = next(iter(_active(entry)), None)
    if job is None and sample_id:
        job = forge_runs.COORD_JOBS.get(job_key(entry, sample_id, exclude))
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
    """{budget: {"games", "new_games", "minutes": [low, high] or None, "overnight"}}; {} when no
    plan can be worked out (logged). One plan, at the largest budget: a fixed:N budget tops every
    opponent up to N, so each budget's games follow from what each opponent has (an "all" sample
    reads its saved games once, not once a budget). "overnight" is True when the high estimate is
    over OVERNIGHT_MINUTES: the page says it's an overnight run and that the PC is kept awake."""
    try:
        planned = g.plan(entry, chosen, BUDGETS[-1])
    except Exception:
        common._log(f"The gauntlet budgets of {entry['title']} can't be worked out:\n{traceback.format_exc()}")
        return {}
    have = [(p["opponent"], int(p.get("have") or 0)) for p in planned.get("pairs") or []]
    out = {}
    for budget in BUDGETS:
        per = int(budget.split(":", 1)[1])
        pairs = [(entry, opponent, per - n) for opponent, n in have if per > n]
        minutes = None
        try:
            found = forge.estimate.minutes(pairs, results_dir=g.results_dir()) if pairs else (0, 0)
            minutes = [found[0], found[1]] if found else None
        except Exception:
            common._log(f"The gauntlet run's time can't be estimated:\n{traceback.format_exc()}")
        out[budget] = {"games": per, "new_games": sum(games for _, _, games in pairs), "minutes": minutes,
                       "overnight": bool(minutes) and minutes[1] > OVERNIGHT_MINUTES}
    return out


def _progress(job, snap, seen):
    detail = snap["detail"] if isinstance(snap["detail"], dict) else {}
    out = {**detail, **jobs.queue_work(snap), "status": snap["status"], "ahead": snap["ahead"], "done": snap["progress"]["done"],
           "total": snap["progress"]["total"], "by": job.fn.by, "started": snap["seconds"],
           "sample": job.fn.sample["id"], "budget": job.fn.budget}
    out.pop("deck", None)       # the house deck that started it: this page names its own
    out["may_stop"] = seen.can_stop(job)
    return out


def _base(forge, entry, fmt, seen):
    return {"deck": {k: entry[k] for k in ("id", "version", "title", "card_sha")}, "format": fmt,
            "build_command": _build_command(fmt, seen), "credit": CREDIT,
            "options": {"sizes": list(SIZES[fmt]), "colours": "WUBRG", "styles": list(STYLES),
                        "tiers": list(TIERS[fmt]), "budgets": list(BUDGETS),
                        "overnight_minutes": OVERNIGHT_MINUTES, "same_commander": None},
            "default_budget": DEFAULT_BUDGET, "default_size": DEFAULT_SIZE[fmt], "forge": forge.status(),
            "catalogue": None, "sample": None, "standard": None, "is_standard": False, "opponents": [], "groups": {},
            "games": 0, "note": None, "notes": [], "status": "none", "job": None, "notice": None, "error": None,
            "budgets": {}, "overall": None, "played": 0, "of": 0,
            "tally": {"ahead": 0, "even": 0, "behind": 0, "unsettled": 0}, "updated": None,
            "before": None, "compare": None, "older": None}


def _answer(forge, g, entry, choices, seen, summary=None, commanders=()):
    """gauntlet_view's answer for entry and the request's choices, as seen may see it (summary,
    the deck's library summary, for the standard sample's before-figure: none without it). A trial
    deck's samples leave out its own precon (gauntlet.trial_excluded: "of" counts the rest).
    commanders: the deck's own (_commanders), for options' "same_commander"."""
    fmt = _format(entry)
    exclude = trial_excluded(summary)
    out = _base(forge, entry, fmt, seen)
    job, snap = _find_job(entry, choices["sample"], seen, exclude)
    playing = snap is not None and snap["status"] in forge_runs.MATCHUP_WAITING
    try:
        cat = g.catalogue(fmt)
        # A run's whole sample (a trial's run plays it without its precon): this deck's own exclusion.
        chosen = without(_full(job) if playing else _draw(g, fmt, choices, save=False, cat=cat, own=commanders), exclude)
        standard = without(_standard(g, fmt, cat, chosen, choices, playing), exclude)
    except forge.ForgeError:
        return out                      # no catalogue yet: the page shows build_command (to an admin)
    if not playing and job is None:
        job, snap = _find_job(entry, chosen["id"], seen, exclude)
    out["catalogue"] = _catalogue_json(cat)
    out["options"]["same_commander"] = _same_count(fmt, cat, commanders, exclude)
    # saved: the sample comes back by its id (the page's address keeps only such a one).
    out["sample"] = {"id": chosen["id"], "size": chosen.get("size"), "filters": chosen.get("filters"),
                     "decks": len(chosen.get("decks") or []), "all": bool(chosen.get("all")),
                     "commander": list(chosen.get("commander") or []) or None,
                     "saved": bool(choices["sample"]) or job is not None or _is_saved(g, chosen["id"])}
    out.update(standard=standard_json(standard), is_standard=chosen["id"] == standard["id"])
    if chosen.get("decks"):
        kept = None
        try:
            with _held(forge):
                found = g.view(entry, chosen, keep=_keep(entry), cat=cat)
                if out["is_standard"] and summary is not None:
                    kept = _kept(forge, g, summary, entry, standard, cat, found)
        except (ValueError, forge.ForgeError) as e:
            raise ApiError(400, _public(e)) from None
        except Exception:
            common._log(f"The gauntlet view of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
            raise ApiError(500, NO_VIEW) from None
        rows = (kept or {}).get("rows") or {}
        out.update(opponents=[dict(o, source=_source(o.get("source")),
                                   before=(rows.get(o.get("id")) or {}).get("before"),
                                   moved=bool((rows.get(o.get("id")) or {}).get("moved")))
                              for o in found.get("opponents") or []],
                   groups=found.get("groups") or {}, games=found.get("games") or 0, note=found.get("note"),
                   notes=list(found.get("notes") or []) + list((kept or {}).get("notes") or []))
        if kept:
            out.update(before=kept["before"], compare=kept["compare"], older=kept["older"])
        played = int(found.get("played") or 0)      # the headline's (E3-S33), as the summary gives it
        out.update(overall=found.get("overall") if played else None, played=played, of=int(found.get("of") or 0),
                   tally=found.get("tally") or out["tally"], updated=found.get("updated"))
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


def standard_json(standard):
    """A standard sample as the answers give it: {"id", "size", "tiers"}."""
    return {"id": standard["id"], "size": standard.get("size"),
            "tiers": list((standard.get("filters") or {}).get("tiers") or [])}


def gauntlet_view(deck_id, version="target", sample=None, size=None, colours=None, styles=None, tiers=None,
                  commander=None, profile=None):
    """GET /api/gauntlet?id=&version=[&sample=|&size=&colours=&styles=&tiers=][&profile=]: the list
    against a sample of popular decks (the module docstring). A sample drawn from the filters isn't
    saved until it's played. ApiError as deck_view for the id or version (404 first for a deck the
    viewer may not see), 400 for a Beginner Box half or a choice that isn't one, 404 for a sample id
    that isn't saved, 500 when the gauntlet can't be loaded or worked out. profile is accepted for
    the page's usual query and changes nothing. With no choices, the sample is the standard one
    (forge.gauntlet.standard: the default draw). commander="same" (E3-S49): every catalogue deck
    with the deck's own commanders (400 for a 60-card deck, a deck without a commander or another
    choice beside it); none there is an answer with no opponents, never a run."""
    if deck_id is None:
        raise ApiError(400, "The request needs id")
    forge = forge_runs._forge_module()
    summary, sections, entry = field_page._field_list(forge, deck_id, version or "target")
    g = _gauntlet(forge)
    choices = _with_commanders(_choices(_format(entry), sample, size, colours, styles, tiers, commander), sections)
    return _answer(forge, g, entry, choices, forge_runs._Seen(), summary, _commanders(sections))


# ============================================================ the summary (E3-S33)

HARDEST = 3


def _hardest(opponents):
    """The first HARDEST opponents with a rate (the view lists them hardest first), as the summary
    gives them."""
    out = []
    for o in opponents:
        rate = o.get("rate")
        if not rate or rate.get("value") is None:
            continue
        out.append({"title": o.get("title"), "tier": o.get("tier"), "style": o.get("style"), "rate": rate["value"],
                    "low": rate.get("low"), "high": rate.get("high"), "verdict": o.get("verdict"),
                    "source": _source(o.get("source"))})
        if len(out) == HARDEST:
            break
    return out


def _playing(entry, standard_id, seen):
    """None, or {"status", "done", "total", "standard"} of the list's gauntlet run waiting or playing
    (any sample) that the viewer sees: never who started it."""
    job = next((j for j in _active(entry) if _sees_job(seen, j)), None)
    if job is None:
        return None
    snap = forge_runs.COORD_JOBS.snapshot(job)
    if snap["status"] not in forge_runs.MATCHUP_WAITING:
        return None
    return {"status": snap["status"], "done": snap["progress"]["done"], "total": snap["progress"]["total"],
            "standard": job.fn.sample.get("id") == standard_id}


def gauntlet_summary(deck_id, version="target", profile=None):
    """GET /api/gauntlet/summary?id=&version=[&profile=]: the list's headline against its format's
    standard sample, read from saved games only (it never plays, saves a sample, plans or
    estimates; the page asks once, without a timer):

        {"deck": {"id", "version"}, "format",
         "state": "no_catalogue" | "untested" (no opponent has games) | "partial" | "done" (every
                  opponent has games) | "stale_list" (no games for this list, but an earlier saved
                  list has standard games: "before") | "stale_older" (no games under today's keys,
                  but older-engine, other-pilot or rebuilt-catalogue results exist: "older"),
         "playing": None | {"status": "queued"|"running", "done", "total", "standard": bool},
         "overall": None | forge.gauntlet.view's "overall" ({"rate", "low", "high", "spread",
                    "note", "opponents", "games", ...}),
         "played", "of", "games", "tally": {"ahead", "even", "behind", "unsettled"},
         "hardest": [up to 3 {"title", "tier", "style", "rate", "low", "high", "verdict", "source"}],
         "updated": the newest result's time or None, "sample": {"id", "size", "tiers"} or None,
         "note": the view's caveat (these sampled opponents only) or None,
         "notes": the view's notes, "build_command": the catalogue's build command for an admin
                  (None for anyone else),
         E3-S34 (gauntlet_before):
         "before": None | {"rate", "low", "high", "played", "of", "games", "updated"}: the previous
                   saved list's figure with today's engine (its most recent earlier revision whose
                   playable list has standard games),
         "compare": None | {"same": N, "before": {"rate", "low", "high"}, "now": {...}, "moved"}:
                    both lists over the N opponents both have rates against ("moved": how many of
                    them have ranges that don't overlap); only when N >= 1,
         "older": None | {"reason": "forge" | "settings" | "pilot" | "catalogue" | "unknown",
                  "opponents", "of", "updated", "overall": {"rate", "low", "high"} | None}: the
                  list's results today's keys don't find, the newest single-engine group}

    No revision number, who saved a revision, message, run starter or other house deck is in it.

    ApiError 404 first for a deck the viewer may not see (the raw id, an alias included, before it's
    resolved), then deck_view's for the id or version, 400 for a Beginner Box half, 500 when the
    gauntlet can't be loaded or worked out. profile is accepted for the page's usual query and
    changes nothing."""
    if deck_id is None:
        raise ApiError(400, "The request needs id")
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id)
    forge = forge_runs._forge_module()
    summary, entry = field_page._field_entry(forge, deck_id, version or "target")
    g = _gauntlet(forge)
    fmt = _format(entry)
    seen = forge_runs._Seen()
    out = {"deck": {"id": entry["id"], "version": entry["version"]}, "format": fmt, "state": "no_catalogue",
           "playing": None, "overall": None, "played": 0, "of": 0, "games": 0,
           "tally": {"ahead": 0, "even": 0, "behind": 0, "unsettled": 0}, "hardest": [], "updated": None,
           "sample": None, "note": None, "notes": [],
           "build_command": _build_command(fmt, seen), "before": None, "compare": None, "older": None}
    try:
        cat = g.catalogue(fmt)
        standard = without(g.standard(fmt, cat=cat), trial_excluded(summary))
    except forge.ForgeError:
        return out
    out["sample"] = standard_json(standard)
    out["playing"] = _playing(entry, standard["id"], seen)
    if not standard.get("decks"):
        out["state"] = "untested"
        return out
    try:
        with _held(forge):
            out.update(_summary_of(forge, g, summary, entry, cat, standard))
    except (ValueError, forge.ForgeError) as e:
        raise ApiError(400, _public(e)) from None
    except Exception:
        common._log(f"The gauntlet summary of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        raise ApiError(500, NO_VIEW) from None
    return out


NO_KEPT = {"before": None, "compare": None, "older": None, "notes": []}


def _summary_of(forge, g, summary, entry, cat, standard, before=True):
    """The summary's fields worked out from the list's view of the standard sample ("state",
    "overall", "played", "of", "games", "tally", "hardest", "updated", "note", "notes", "before",
    "compare", "older"), inside _held. before says which of E3-S34's fields to look for: True for
    all of them (gauntlet_before.fields: the history walk), "older" for the list's own older
    results only, False for none; or a function of the opponents played that gives one of those
    (the board's: GET /api/gauntlet/board). ValueError or ForgeError as g.view's."""
    found = g.view(entry, standard, keep=_keep(entry), cat=cat)
    played, of = int(found.get("played") or 0), int(found.get("of") or 0)
    mode = before(played) if callable(before) else before
    if mode is True:
        kept = _kept(forge, g, summary, entry, standard, cat, found)
    elif mode == "older" and not played:
        kept = dict(NO_KEPT, older=gauntlet_before._older(g, entry, standard, cat, found, _keep))
    else:
        kept = NO_KEPT
    state = "partial" if played and played < of else "done" if played else "untested"
    if not played and kept["before"]:
        state = "stale_list"
    elif not played and kept["older"]:
        state = "stale_older"
    return {"overall": found.get("overall") if played else None, "played": played, "of": of,
            "games": found.get("games") or 0, "tally": found.get("tally") or {"ahead": 0, "even": 0, "behind": 0,
                                                                              "unsettled": 0},
            "hardest": _hardest(found.get("opponents") or []), "updated": found.get("updated"),
            "note": found.get("note"), "notes": list(found.get("notes") or []) + kept["notes"], "state": state,
            "before": kept["before"], "compare": kept["compare"], "older": kept["older"]}


# ============================================================ run and stop

class _GauntletJob:
    """What a gauntlet run's COORD_JOBS job runs (forge.gauntlet.run), and what the answers need of
    it: the entry, the sample, the budget, who started it, and "via" for its pairs' matchup pages."""

    kind = "gauntlet"

    def __init__(self, g, entry, sample, budget, by, by_id, full=None):
        self.g, self.entry, self.sample, self.budget, self.by, self.by_id = g, entry, sample, budget, by, by_id
        self.full = sample if full is None else full        # the sample before a trial's exclusion
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
    list and sample already waiting or playing is joined; one of another sample is a 409. Returns gauntlet_view's answer. ApiError
    404 for a deck the profile may not see (before anything else), 403 without a profile or while
    the simulations setting refuses (guard.require_start), 400 for a choice that isn't one or a
    sample with no decks, 409 when a run of the list against another sample is waiting or playing
    or when expected_card_sha (64 lowercase hex characters) isn't the saved
    list's, and 503 when there's no catalogue, Forge isn't ready, COORD_JOBS has 4 waiting or the
    server is stopping."""
    data = _parse_body(body, MAX_EDIT_BODY)
    profile = _writer(data)
    _visible_first(data, profile)
    guard.require_start(profile)        # the simulations setting (api/simulations.py)
    _keys(data, ("profile", "id"), ("version", "budget", "expected_card_sha", "sample", "size", "colours",
                                    "styles", "tiers", "commander"))
    budget = data.get("budget") or DEFAULT_BUDGET
    if budget not in BUDGETS:
        raise ApiError(400, f"budget must be one of: {', '.join(BUDGETS)}")
    forge = forge_runs._forge_module()
    summary, sections, entry = field_page._field_list(forge, data["id"], data.get("version"))
    fmt = _format(entry)
    choices = _with_commanders(_choices(fmt, data.get("sample"), data.get("size"), data.get("colours"),
                                        data.get("styles"), data.get("tiers"), data.get("commander")), sections)
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
        drawn = _draw(g, fmt, choices, save=True, own=_commanders(sections))
        exclude = trial_excluded(summary)
        chosen = without(drawn, exclude)
        if not chosen.get("decks"):
            raise ApiError(400, NO_SAME_COMMANDER if choices["commander"] else NO_DECKS)
        g.entries(fmt, chosen["decks"])         # every deck still playable in today's catalogue
    except (ValueError, forge.ForgeError) as e:
        raise ApiError(400, _public(e)) from None
    seen = forge_runs._Seen(profile)
    run = _GauntletJob(g, entry, chosen, budget, profile["name"], profile["id"], full=drawn)
    key = job_key(entry, chosen["id"], exclude)
    with _SUBMIT_LOCK:
        # One gauntlet run of a list at a time: another sample's would play beside it into the same
        # results folder, and the page (and Stop) would see only the first.
        if any(j.key != key for j in _active(entry)):
            raise ApiError(409, ALREADY_PLAYING)
        try:
            from . import run_recovery
            run_recovery.submit(forge, "gauntlet", run, profile, data, key, rerun=True)
        except jobs.Busy as e:
            raise ApiError(503, forge_runs.MATCHUP_STOPPING if e.stopping else GAUNTLET_BUSY) from None
    return _answer(forge, g, entry, dict(choices, sample=chosen["id"], commander=False), seen, summary,
                   _commanders(sections))


def stop_gauntlet(body):
    """POST /api/gauntlet/stop {"profile", "id", "version"?, "sample"?}: Stop the list's gauntlet runs
    waiting or playing (any sample; every game that finished is kept). Stopping when nothing waits or
    plays changes nothing. Returns gauntlet_view's answer. ApiError 404 first for a deck the profile
    may not see, then run.stop's 403 (its starter, its deck's space or an admin)."""
    data = _parse_body(body, MAX_BODY)
    profile = _writer(data)
    _visible_first(data, profile)
    _keys(data, ("profile", "id"), ("version", "sample"))
    forge = forge_runs._forge_module()
    summary, sections, entry = field_page._field_list(forge, data["id"], data.get("version"))
    g = _gauntlet(forge)
    choices = _choices(_format(entry), data.get("sample"))
    seen = forge_runs._Seen(profile)
    playing = _active(entry)
    for job in playing:
        seen.require_stop(job, _sees_job(seen, job), forge_runs.MATCHUP_NO_KEY)
    for job in playing:          # every run of the list (normally one: run_gauntlet refuses a second)
        if forge_runs.COORD_JOBS.cancel(job.key, by=profile["name"]):
            job.wait(forge_runs.STOP_WAIT)
    if playing:
        choices["sample"] = playing[0].fn.sample["id"]
    return _answer(forge, g, entry, choices, seen, summary, _commanders(sections))
