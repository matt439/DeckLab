"""The library's popular-decks line (E3-S36, design/visual-design.md 4.1 and 4.2): GET /api/library/gauntlet,
each visible deck's Planned list against its format's standard sample of popular decks, as the Testing
page's board works it out (api/gauntlet_board.standing, sharing its row and answer caches: a library
load and a board load of the same viewer build once). Saved games only: it never plans, estimates or plays.

    library_gauntlet_view()
                        {"formats": {"commander" | "constructed": {"state": "ok" | "no_catalogue" | "error",
                                                                   "size": the standard sample's decks or None}},
                         "decks": {deck id: {"format", "state", "overall": {rate, low, high} or None, "played",
                                             "of", "games", "updated", "before": {rate, low, high, updated} or None,
                                             "older": {reason, opponents, of, overall, updated, earlier} or None,
                                             "trial": True for a trial deck (E3-S39: "Not owned")}},
                         "notes": [gauntlet_board.STILL_LOOKING?], "error": None or NO_NUMBERS}

The decks are the board's (guard.visible_decks: the viewer's own space and the public spaces, every deck for a
script naming nobody; no Beginner Box half). A board row's hardest opponent, playing state, title and notes are
left out, and there are no inventory facts, revisions or starters. A format whose numbers can't be worked out
is "error" (and the answer's error NO_NUMBERS): its decks are left out, never shown as untested.
"""
import traceback

from . import common, forge_runs, gauntlet_board, gauntlet_page

FORMATS = ("commander", "constructed")
NO_NUMBERS = "The popular-decks numbers can't be worked out on the PC now."
FIELDS = ("state", "overall", "played", "of", "games", "updated", "before", "older", "trial")


def library_gauntlet_view():
    """GET /api/library/gauntlet: see the module docstring (200 always)."""
    out = {"formats": {}, "decks": {}, "notes": [], "error": None}
    try:
        forge = forge_runs._forge_module()
        g = gauntlet_page._gauntlet(forge)
        seen = forge_runs._Seen()
    except Exception:
        common._log(f"The library's popular-decks numbers can't be worked out:\n{traceback.format_exc()}")
        out["formats"] = {fmt: {"state": "error", "size": None} for fmt in FORMATS}
        out["error"] = NO_NUMBERS
        return out
    for fmt in FORMATS:
        try:
            standard, rows, notes = gauntlet_board.standing(fmt, forge, g, seen)
        except Exception:
            common._log(f"The library's {fmt} popular-decks numbers can't be worked out:\n{traceback.format_exc()}")
            out["formats"][fmt] = {"state": "error", "size": None}
            out["error"] = NO_NUMBERS
            continue
        if standard is None:
            out["formats"][fmt] = {"state": "no_catalogue", "size": None}
            continue
        out["formats"][fmt] = {"state": "ok", "size": len(standard.get("decks") or ()) or None}
        for row in rows:
            out["decks"][row["deck"]["id"]] = {"format": fmt, **{k: row.get(k) for k in FIELDS}}
        out["notes"] += [n for n in notes if n not in out["notes"]]
    return out
