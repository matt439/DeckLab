"""The Testing page's "Popular decks" board (E3-S35): GET /api/gauntlet/board, every deck the viewer
may see, each its standing against its format's standard sample of popular decks, as
gauntlet_page.gauntlet_summary works it out (E3-S33's headline, E3-S34's out-of-date states).
Imported when first asked for, by feature_routes.dispatch.

    board_view(format="commander", profile=None)
                        {"format", "state": "ok" | "no_catalogue", "build_command" (an admin's, else
                         None), "sample": {"id", "size", "tiers"} or None, "default_budget", "note",
                         "notes", "rows": [row, ...]}, each row
                        {"deck": {"id", "title", "kind", "version": "target", "card_sha"},
                         "state": "untested" | "partial" | "done" | "stale_list" | "stale_older" |
                                  "unreadable",
                         "problem": None or why an unreadable row has no figure,
                         "overall": {"rate", "low", "high"} or None, "played", "of", "games", "updated",
                         "hardest": {"title", "tier", "style", "rate", "low", "high", "verdict",
                                     "source"} or None (a gauntlet deck: public data),
                         "before": {"rate", "low", "high", "updated"} or None,
                         "older": {"reason", "opponents", "of", "overall", "updated", "earlier"} or None,
                         "notes": [why the list's earlier versions weren't (all) looked at, ...],
                         "playing": None or {"status", "done", "total", "standard"}}

Which decks: guard.visible_decks over the library (the viewer's own space and the public spaces;
every deck for a script naming nobody), the format's decks only, no Beginner Box half (one plays
only in a pairing) and none that can't be read. A deck the viewer may not see is never counted or
named; it is read only in a space the viewer sees part of (a public space's product decks), and only
to tell which noted lists are some deck's today (_orphans), so the walks don't depend on the viewer. Each row is the Planned list's (the summary's and the Overview's). Nothing
inventory-derived (owned, missing, status, versions) is in the answer, nor any revision, Rankings or
field number, starter's name or other house deck (hardest is a gauntlet deck).

The rows are sorted here: rows with a figure first, highest rate, then highest low, then title; then
the out-of-date rows; then the untested; then the unreadable; each by title.

It never plays, plans, estimates or saves a sample. Its work is cached at two levels:
- a row, ROW_CACHE of them across viewers (a row depends on its list, space and sample only), while
  its stamps (forge.gauntlet.stamps: each opponent's saved result and the list's run notes) are
  unchanged, so only a row whose games moved is worked out again;
- the answer, per (format, viewer's space, script, public spaces), while its fingerprint (the
  visible decks' texts, the catalogue, the standard sample and the results folder's stamp) is
  unchanged, at most CACHE_S; two reads of one key build it once.
A row's "playing" (COORD_JOBS, never who started it) and the build command are never cached.

E3-S34's history walk (gauntlet_before.fields) is done only for a list with no games under today's
keys while the space has run notes of a list no deck of the space has today (its own notes alone
don't skip it: a run stopped or failed before its first game leaves a note too); at most MAX_WALKS a
request. A row past the bound shows as untested (or with its own older results), isn't cached, and
the answer says STILL_LOOKING; a later read fills it in. A row whose history couldn't be read
(gauntlet_before.NO_HISTORY: the database) says so in its notes, and neither it nor the answer is
cached. A list whose earlier version is exactly another deck's list today isn't walked (the deck's
Testing tab still walks it): telling that apart needs every deck's history read on each build.
"""
import threading
import time
import traceback
from collections import OrderedDict

from decklab.lib import decks, inventory, permissions

from . import common, forge_runs, gauntlet_page, guard
from .common import ApiError
from .library import is_half, viewer_decks_revision
from .library_forge import _stamp

MAX_WALKS = 8
ROW_CACHE = 256
CACHE_S = 600
UNREADABLE = "Forge can't read this list."
NO_ROW = "Its results can't be worked out on the PC now."
STILL_LOOKING = "Some lists' earlier results are still being looked at."
HISTORY_NOTES = (gauntlet_page.gauntlet_before.NO_HISTORY, gauntlet_page.gauntlet_before.NOT_ALL)

_rows = OrderedDict()               # row key -> (fingerprint, time, row)
_answers = {}                       # answer key -> (fingerprint, time, (rows, notes))
_flights = {}                       # answer key -> its build's lock
_lock = threading.Lock()


def clear_cache():
    """Forget every kept row and answer (tests)."""
    with _lock:
        _rows.clear()
        _answers.clear()
        _flights.clear()


# ============================================================ the rows

def _usable(summary, fmt):
    """True for a library summary the board lists: readable, a Planned list, this format, no half."""
    if summary.get("error") or "target" not in (summary.get("versions") or ()) or is_half(summary):
        return False
    return gauntlet_page._format({"kind": decks.engine_kind(summary)}) == fmt


def _deck(summary, entry):
    return {"id": summary["id"], "title": summary.get("title"), "kind": summary.get("kind"), "version": "target",
            "card_sha": entry["card_sha"] if entry else None}


def _blank(summary, entry, state="untested", problem=None):
    return {"deck": _deck(summary, entry), "state": state, "problem": problem, "overall": None, "played": 0,
            "of": 0, "games": 0, "updated": None, "hardest": None, "before": None, "older": None, "notes": [],
            "playing": None}


def _figure(found, *extra):
    if not isinstance(found, dict):
        return None
    return {k: found.get(k) for k in ("rate", "low", "high", *extra)}


def _row_of(summary, entry, fields):
    """A board row from _summary_of's fields."""
    older = fields.get("older")
    notes = [n for n in fields.get("notes") or () if n in HISTORY_NOTES]
    return dict(_blank(summary, entry), state=fields["state"], overall=_figure(fields.get("overall")),
                played=fields["played"], of=fields["of"], games=fields["games"], updated=fields.get("updated"),
                hardest=(fields.get("hardest") or [None])[0], before=_figure(fields.get("before"), "updated"),
                older=None if not older else {"reason": older.get("reason"), "opponents": older.get("opponents"),
                                              "of": older.get("of"), "overall": _figure(older.get("overall")),
                                              "updated": older.get("updated"), "earlier": bool(older.get("earlier"))},
                notes=notes)


def _space(summary):
    return permissions._deck_space(summary.get("id")) or summary.get("space") or permissions.HOME


def _entries(forge, visible):
    """[(summary, Forge entry or None)] of the visible decks' Planned lists."""
    out = []
    for summary in visible:
        try:
            sections = decks.load_deck(summary["id"], "target")
            entry = forge.entry(summary["id"], "target", summary["title"], decks.engine_kind(summary), sections)
        except Exception:
            common._log(f"The board can't read {summary['id']}:\n{traceback.format_exc()}")
            entry = None
        out.append((summary, entry))
    return out


def _orphans(g, fmt, made, others=()):
    """{space: stamps of the run notes of lists no deck of the space has today} for the spaces in made;
    others: [(summary, entry)] of the spaces' decks the viewer doesn't see (only their lists are used)."""
    noted = getattr(g, "noted", None)
    out = {}
    for space in {_space(s) for s, _ in made}:
        if noted is None:
            out[space] = ()
            continue
        try:
            found = noted(fmt, space)
        except Exception:
            common._log(f"The gauntlet's run notes can't be listed:\n{traceback.format_exc()}")
            found = {}
        today = {e["card_sha"] for s, e in (*made, *others) if e and _space(s) == space}
        out[space] = tuple(sorted((sha, stat) for sha, stat in found.items() if sha not in today))
    return out


def _stamps(g, entry, standard, cat, space):
    """forge.gauntlet.stamps for the row, or None (no stamps: the row isn't kept)."""
    stamps = getattr(g, "stamps", None)
    if stamps is None:
        return None
    try:
        return stamps(entry, standard, cat, space)
    except Exception:
        common._log(f"The gauntlet stamps of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        return None


def _work_row(forge, g, summary, entry, cat, standard, space, walk):
    """(row, what) of one list: what is "walked" when its history was looked at, "later" when it
    would have been but the bound is used up (walk "later": the row shows as untested), else None.
    walk is "yes", "no" or "later"."""
    has_notes = getattr(g, "has_notes", None)
    what = []

    def before(played):
        if played:
            return False
        own = "older" if has_notes is not None and has_notes(entry, space) else False
        if walk == "no":
            return own
        what.append("walked" if walk == "yes" else "later")
        return True if walk == "yes" else own
    try:
        fields = gauntlet_page._summary_of(forge, g, summary, entry, cat, standard, before=before)
    except Exception:
        common._log(f"The board row of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        return _blank(summary, entry, "unreadable", NO_ROW), None
    return _row_of(summary, entry, fields), (what or [None])[0]


def _rows_of(forge, g, fmt, cat, standard, made, snapshot, others=()):
    """(rows, notes, keep) of the visible lists, rows sorted, as the module docstring says (keep: False
    when the answer mustn't be cached); inside _held."""
    orphans = _orphans(g, fmt, made, others)
    rows, walks, later, unread = [], 0, False, False
    for summary, entry in made:
        if entry is None:
            rows.append(_blank(summary, None, "unreadable", UNREADABLE))
            continue
        space = _space(summary)
        stored = _stored(snapshot, summary["id"])
        walkable = bool(orphans.get(space))
        key = (summary["id"], space, entry["card_sha"], stored, (cat or {}).get("sha"), standard["id"], walkable)
        stamps = _stamps(g, entry, standard, cat, space)
        fingerprint = None if stamps is None else (stamps, orphans.get(space) if walkable else None)
        hit = _row_hit(key, fingerprint)
        if hit is not None:
            rows.append(dict(hit, deck=_deck(summary, entry)))
            continue
        walk = "no" if not walkable else "yes" if walks < MAX_WALKS else "later"
        row, what = _work_row(forge, g, summary, entry, cat, standard, space, walk)
        walks += what == "walked"
        if what == "later":
            later = True            # not kept: a later read looks at its history
        elif gauntlet_page.gauntlet_before.NO_HISTORY in row["notes"]:
            unread = True           # not kept: the database may be back on the next read
        elif fingerprint is not None and row["state"] != "unreadable":
            _keep_row(key, fingerprint, row)
        rows.append(row)
    rows.sort(key=_order)
    return rows, [STILL_LOOKING] if later else [], not (later or unread)


def _stored(snapshot, deck_id):
    """(revision, text sha256) of a deck text, or None (a product deck, or the snapshot can't say)."""
    try:
        found = snapshot.deck(deck_id) if snapshot is not None else None
    except Exception:
        return None
    return None if found is None else (getattr(found, "revision", None), getattr(found, "sha256", None))


def _row_hit(key, fingerprint):
    if fingerprint is None:
        return None
    with _lock:
        hit = _rows.get(key)
        if hit is None or hit[0] != fingerprint or time.monotonic() - hit[1] >= CACHE_S:
            return None
        _rows.move_to_end(key)
        return hit[2]


def _keep_row(key, fingerprint, row):
    with _lock:
        _rows[key] = (fingerprint, time.monotonic(), dict(row, playing=None))
        _rows.move_to_end(key)
        while len(_rows) > ROW_CACHE:
            _rows.popitem(last=False)


GROUPS = {"stale_list": 1, "stale_older": 1, "untested": 2, "unreadable": 3}


def _order(row):
    """The board's order: a figure first (highest rate, then highest low), then out of date,
    untested and unreadable, each by title."""
    deck = row["deck"]
    title = (deck.get("title") or deck["id"]).casefold()
    rate = (row.get("overall") or {}).get("rate")
    if row["state"] in ("done", "partial") and rate is not None:
        return 0, -rate, -(row["overall"].get("low") or 0), title, deck["id"]
    return GROUPS.get(row["state"], 2), 0, 0, title, deck["id"]


# ============================================================ the answer

def _visible(fmt):
    """(the viewer's visible decks of the format, the same spaces' decks of it the viewer doesn't see)."""
    every = [s for s in decks.list_decks() if _usable(s, fmt)]
    visible = guard.visible_decks(every)
    shown, spaces = {s["id"] for s in visible}, {_space(s) for s in visible}
    return visible, [s for s in every if s["id"] not in shown and _space(s) in spaces]


def _built(forge, g, fmt, cat, standard, seen, visible, hidden=()):
    """(rows, notes) for the viewer's visible decks, kept as the module docstring says; hidden: the
    same spaces' decks the viewer doesn't see (for _orphans only)."""
    try:
        snapshot = inventory.current()
    except Exception:
        snapshot = None
    public = frozenset(guard.public_deck_spaces())
    key = (fmt, seen.space, seen.everything, public)
    revision = viewer_decks_revision([*visible, *hidden], snapshot) if snapshot is not None else None
    fingerprint = None if revision is None else (revision, (cat or {}).get("sha"), standard["id"],
                                                 _stamp(g.results_dir()))
    with _lock:
        flight = _flights.setdefault(key, threading.Lock())
    with flight:
        with _lock:
            hit = _answers.get(key)
        if fingerprint is not None and hit and hit[0] == fingerprint and time.monotonic() - hit[1] < CACHE_S:
            return hit[2]
        with gauntlet_page._held(forge):
            made = _entries(forge, visible)
            others = _entries(forge, hidden)
            rows, notes, keep = _rows_of(forge, g, fmt, cat, standard, made, snapshot, others)
        if fingerprint is not None and keep:
            with _lock:
                _answers[key] = (fingerprint, time.monotonic(), (rows, notes))
        return rows, notes


def board_view(format="commander", profile=None):
    """GET /api/gauntlet/board?format=commander|constructed[&profile=]: the module docstring's
    answer (200 always, but 400 for another format). profile is accepted for the page's usual query
    and changes nothing: the viewer is the request's."""
    fmt = format or "commander"
    if fmt not in gauntlet_page.TIERS:
        raise ApiError(400, "format must be commander or constructed")
    forge = forge_runs._forge_module()
    g = gauntlet_page._gauntlet(forge)
    seen = forge_runs._Seen()
    out = {"format": fmt, "state": "no_catalogue", "build_command": gauntlet_page._build_command(fmt, seen),
           "sample": None, "default_budget": gauntlet_page.DEFAULT_BUDGET, "note": None, "notes": [], "rows": []}
    try:
        cat = g.catalogue(fmt)
        standard = g.standard(fmt, cat=cat)
    except forge.ForgeError:
        return out
    out.update(state="ok", sample=gauntlet_page.standard_json(standard))
    if not standard.get("decks"):
        return out
    out["note"] = (f"Each figure is the list's average win rate against these {len(standard['decks'])} popular "
                   "decks only: not a rating, and apart from Rankings.")
    rows, notes = _built(forge, g, fmt, cat, standard, seen, *_visible(fmt))
    out["notes"] = list(notes)
    out["rows"] = [dict(row, playing=gauntlet_page._playing(row["deck"], standard["id"], seen)
                        if row["deck"]["card_sha"] else None) for row in rows]
    return out

