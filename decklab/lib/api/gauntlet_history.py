"""The popular-decks figure across a deck's saved versions (E3-S50; decklab/design/gauntlet.md
section 11): GET /api/gauntlet/history, a short timeline of the list's figure against its format's
standard sample, today's list first, then up to MAX_SHOWN earlier lists that have standard-sample
results, newest first, with each step between neighbouring lists. Read from saved games only:
nothing here plays, saves a sample or writes, and the Testing tab asks once (no timer).

    history_view(deck_id, version="target", profile=None)
        {"deck": {"id", "version"}, "format",
         "state": "no_catalogue" | "none" (no list on the timeline has results) | "listed",
         "sample": {"id", "size", "tiers"} (the standard sample) or None,
         "lists": [{"current": True for today's list, "saved": when the list was saved (the oldest
                    revision of its newest run, an ISO time) or None,
                    "state": "tested" (a figure under today's keys) | "older" (only results today's
                             keys don't find: muted, no figure) | "untested" (today's list only),
                    "rate", "low", "high" (None unless tested), "played", "of", "games",
                    "updated" (its newest game), "older": None | {"reason", "opponents", "of",
                    "updated"} (gauntlet_before._older's, without a figure)}],
         "steps": [{"added": [[copies, name]], "removed": [[copies, name]], "more_added",
                    "more_removed" (names past MAX_CHANGES), "compare": None | {"same", "before":
                    {"rate", "low", "high"}, "now": {...}, "moved"}, "uncompared": None |
                    "no_figure" (either list has no figure) | "no_shared" (no opponent both were
                    tested against)}]: steps[i] goes from lists[i + 1] (older) to lists[i],
         "complete": False when a bound stopped the search (gauntlet_before's revision walk,
                     MAX_VIEWED lists viewed, or MAX_SHOWN listed with lists still unread),
         "notes": [NOT_EVERY when not complete, gauntlet_before.NO_HISTORY when the revisions
                   can't be read], "max_lists": MAX_SHOWN}

An earlier list is on the timeline only when it has run notes in the deck's space (has_notes) and
either games under today's keys or older results (another Forge, other settings, another pilot, a
rebuilt catalogue). A step compares only the opponents both lists have rates against (g.compare,
as E3-S34's "same opponents"); cards added and taken out are the played lists' (Commander and Deck)
by name. Privacy: the deck must be visible first (404 before anything else); no revision number,
who saved a revision, message, run starter, opponent's title or other house deck is in the answer.
The earlier lists' part is kept gauntlet_before.CACHE_SECONDS.
"""
import traceback
from collections import Counter

from decklab.lib import decks
from decklab.lib.gauntlet import trial_excluded, without

from . import common, field_page, forge_runs, gauntlet_before, gauntlet_page, guard
from .common import ApiError, _public
from .library import check_deck_id

MAX_SHOWN = 8           # earlier lists on the timeline
MAX_VIEWED = 12         # earlier lists with run notes viewed (each one view, and an older read if unplayed)
MAX_CHANGES = 40        # card names a step lists on each side
NOT_EVERY = "Not every earlier list was looked at, so this isn't every list."
PLAYED = ("Commander", "Deck")


def _figure(view):
    overall = view.get("overall") or {}
    return {"rate": overall.get("rate"), "low": overall.get("low"), "high": overall.get("high")}


def _row(view, saved, current=False, older=None):
    """A timeline list from its view of the standard sample (older: _older's, for a list without games)."""
    played = int(view.get("played") or 0)
    tested = played > 0 and (view.get("overall") or {}).get("rate") is not None
    figure = _figure(view) if tested else {"rate": None, "low": None, "high": None}
    state = "tested" if tested else "older" if older else "untested"
    return {"current": current, "saved": saved.isoformat() if hasattr(saved, "isoformat") else None,
            "state": state, **figure, "played": played, "of": int(view.get("of") or 0),
            "games": int(view.get("games") or 0) if tested else 0, "updated": view.get("updated") if tested else None,
            "older": None if tested or not older else
            {k: older.get(k) for k in ("reason", "opponents", "of", "updated")}}


def _copies(sections):
    """{name: copies} of a list's played sections."""
    found = Counter()
    for section in PLAYED:
        for line in (sections or {}).get(section, []) or []:
            found[line.name] += int(line.quantity)
    return found


def _changes(newer, older):
    """The cards added and taken out going from older's list to newer's, by name, sorted."""
    now, then = _copies(newer), _copies(older)
    added = sorted([[now[n] - then[n], n] for n in now if now[n] > then[n]], key=lambda x: x[1].lower())
    removed = sorted([[then[n] - now[n], n] for n in then if then[n] > now[n]], key=lambda x: x[1].lower())
    return {"added": added[:MAX_CHANGES], "removed": removed[:MAX_CHANGES],
            "more_added": max(0, len(added) - MAX_CHANGES), "more_removed": max(0, len(removed) - MAX_CHANGES)}


def _step(g, standard, cat, newer, older):
    """The step from older (an item: {"entry", "sections", "view", "row"}) to newer."""
    out = dict(_changes(newer["sections"], older["sections"]), compare=None, uncompared=None)
    if newer["row"]["state"] != "tested" or older["row"]["state"] != "tested":
        out["uncompared"] = "no_figure"
        return out
    keep = gauntlet_page._keep
    compared = g.compare(newer["entry"], older["entry"], standard, keep_now=keep(newer["entry"]),
                         keep_before=keep(older["entry"]), cat=cat)
    if not compared or not compared.get("same"):
        out["uncompared"] = "no_shared"
        return out
    ids = set(compared.get("ids") or [])
    then = {o.get("id"): gauntlet_before._rate(o) for o in older["view"].get("opponents") or []}
    moved = sum(1 for o in newer["view"].get("opponents") or []
                if o.get("id") in ids and gauntlet_before._moved(then.get(o.get("id")), gauntlet_before._rate(o)))
    out["compare"] = {"same": compared["same"], "before": compared["before"], "now": compared["now"], "moved": moved}
    return out


def _earlier_part(forge, g, summary, entry, standard, cat):
    """(the earlier lists' items, newest first, at most MAX_SHOWN; today's list's saved time; a
    note or None; complete). The run-independent part (runs play only today's list)."""
    dates = {}
    found, note, capped = gauntlet_before._earlier(forge, summary, entry, dates)
    has_notes = getattr(g, "has_notes", None)
    space, items, viewed, complete = gauntlet_before._space(entry), [], 0, not capped

    def noted(sha):
        return has_notes is None or has_notes({"card_sha": sha, "kind": entry["kind"]}, space)

    for n, (sha, sections) in enumerate(found):
        if len(items) >= MAX_SHOWN or viewed >= MAX_VIEWED:
            # Only a list left with run notes could have been shown: one without isn't missed.
            if any(noted(rest) for rest, _ in found[n:]):
                complete = False
            break
        if not noted(sha):
            continue
        viewed += 1
        prev = forge.entry(summary["id"], entry["version"], summary["title"], decks.engine_kind(summary), sections)
        prev["source"] = None
        view = g.view(prev, standard, keep=gauntlet_page._keep(prev), cat=cat)
        older = None
        if not int(view.get("played") or 0):
            older = gauntlet_before._older(g, prev, standard, cat, view, gauntlet_page._keep)
            if not older:
                continue        # run notes of another sample only: nothing to show
        items.append({"entry": prev, "sections": sections, "view": view,
                      "row": _row(view, dates.get(sha), older=older)})
    return items, dates.get(entry["card_sha"]), note, complete


def _timeline(forge, g, summary, sections, entry, standard, cat):
    now_view = g.view(entry, standard, keep=gauntlet_page._keep(entry), cat=cat)
    key = (id(forge), id(g), summary.get("id"), summary.get("revision"), entry.get("version"),
           entry.get("card_sha"), standard.get("id"), (cat or {}).get("sha"))
    items, saved, note, complete = gauntlet_before._cached(
        ("history",) + key, lambda: _earlier_part(forge, g, summary, entry, standard, cat))
    now_older = None
    if not int(now_view.get("played") or 0):
        now_older = gauntlet_before._older(g, entry, standard, cat, now_view, gauntlet_page._keep)
    now = {"entry": entry, "sections": sections, "view": now_view,
           "row": _row(now_view, saved, current=True, older=now_older)}
    chain = [now] + list(items)
    steps = [_step(g, standard, cat, chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
    notes = ([note] if note else []) + ([] if complete else [NOT_EVERY])
    shown = any(item["row"]["state"] != "untested" for item in chain)
    return {"state": "listed" if shown else "none", "lists": [item["row"] for item in chain], "steps": steps,
            "complete": complete, "notes": notes}


def history_view(deck_id, version="target", profile=None):
    """GET /api/gauntlet/history?id=&version=[&profile=]: the module docstring's answer. ApiError 404
    first for a deck the viewer may not see (the raw id, an alias included), then deck_view's for the
    id or version, 400 for a Beginner Box half, 500 when the gauntlet can't be loaded or worked out.
    profile is accepted for the page's usual query and changes nothing."""
    if deck_id is None:
        raise ApiError(400, "The request needs id")
    check_deck_id(deck_id)
    guard.require_sees_deck(deck_id)
    forge = forge_runs._forge_module()
    summary, sections, entry = field_page._field_list(forge, deck_id, version or "target")
    g = gauntlet_page._gauntlet(forge)
    fmt = gauntlet_page._format(entry)
    out = {"deck": {"id": entry["id"], "version": entry["version"]}, "format": fmt, "state": "no_catalogue",
           "sample": None, "lists": [], "steps": [], "complete": True, "notes": [], "max_lists": MAX_SHOWN}
    try:
        cat = g.catalogue(fmt)
        standard = without(g.standard(fmt, cat=cat), trial_excluded(summary))
    except forge.ForgeError:
        return out
    out["sample"] = gauntlet_page.standard_json(standard)
    if not standard.get("decks"):
        out["state"] = "none"
        return out
    try:
        with gauntlet_page._held(forge):
            out.update(_timeline(forge, g, summary, sections, entry, standard, cat))
    except (ValueError, forge.ForgeError) as e:
        raise ApiError(400, _public(e)) from None
    except Exception:
        common._log(f"The gauntlet history of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        raise ApiError(500, gauntlet_page.NO_VIEW) from None
    return out
