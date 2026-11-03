"""Popular-decks results kept through a change (E3-S34; decklab/design/gauntlet.md section 11):
the list's previous figure against the standard sample, the two lists over the same opponents,
and saved results that today's keys no longer find (an older Forge, other settings, another AI
pilot, or an opponent's list changed when the catalogue was rebuilt). Nothing is deleted, and
nothing here plays, saves or writes.

    fields(forge, g, summary, entry, standard, cat, now, keep)
        {"before", "compare", "older", "notes", "rows"} for gauntlet_page's answers (their
        docstrings give the shapes); "rows" is {opponent id: {"before", "moved"}} for the view's
        opponent rows.

The previous list is the most recent earlier saved revision (at most MAX_REVISIONS read, in one
query) whose playable list (forge.card_sha's sections) differs from today's and has standard
games; only lists with run notes in the deck's space are viewed, at most MAX_VIEWS of them. The
callers have checked the deck is visible before anything here runs, and nothing returned names a
revision, who saved it, another house deck or who started a run. A previous list played under
an earlier pilot isn't found by today's key; the current list's such results are "older".
"""
import traceback

from decklab.lib import decks, inventory, permissions

from . import common

MAX_REVISIONS = 20
MAX_VIEWS = 3
MAX_OLDER = 300                 # gauntlet_page.MAX_SIZE: older results looked at, newest runs first
NO_HISTORY = "The list's earlier versions can't be read now."


def _space(entry):
    return permissions._deck_space(entry.get("id")) or permissions.HOME


def _sections(rev, kind, slug, space, version):
    """A revision's sections of version, or None (a deletion, unreadable text, no such list)."""
    if rev.op == "D" or rev.text is None:
        return None
    try:
        parsed = decks.parse_deck(rev.text.encode("utf-8"), slug, kind, None, space)
    except (decks.DeckFileError, ValueError):
        return None
    if version == "owned":
        return parsed.owned or None
    return parsed.target if parsed.has_decklist and parsed.target else None


def _earlier(forge, summary, entry):
    """[(card_sha, sections)] of the deck's earlier lists, newest first, each sha once and never
    today's; ([], note) when the revisions can't be read."""
    try:
        space, kind, slug = decks.split_id(summary["id"])
    except ValueError:
        return [], None         # a product's or pairing's list has no saved revisions
    try:
        revisions = inventory.deck_revisions_with_text(summary["id"], MAX_REVISIONS + 1)
    except (inventory.StateError, inventory.Unavailable):
        return [], NO_HISTORY
    engine_kind = decks.engine_kind(summary)
    seen, out = {entry["card_sha"]}, []
    for rev in list(revisions)[:MAX_REVISIONS + 1]:
        sections = _sections(rev, kind, slug, space, entry["version"])
        if sections is None:
            continue
        try:
            sha = forge.card_sha(sections, engine_kind)
        except Exception:
            continue
        if sha not in seen:
            seen.add(sha)
            out.append((sha, sections))
    return out, None


def previous(forge, g, summary, entry, standard, cat, keep):
    """(the previous list's entry, its view against the standard sample, a note or None); the first
    two are None when no earlier list has standard games."""
    found, note = _earlier(forge, summary, entry)
    has_notes = getattr(g, "has_notes", None)
    space, views = _space(entry), 0
    for sha, sections in found:
        if has_notes is not None and not has_notes({"card_sha": sha, "kind": entry["kind"]}, space):
            continue
        if views >= MAX_VIEWS:
            break
        views += 1
        prev = forge.entry(summary["id"], entry["version"], summary["title"], decks.engine_kind(summary), sections)
        prev["source"] = None
        seen = g.view(prev, standard, keep=keep(prev), cat=cat)
        if int(seen.get("played") or 0) > 0:
            return prev, seen, note
    return None, None, note


def _rate(o):
    rate = o.get("rate") if isinstance(o, dict) else None
    if not rate or rate.get("value") is None:
        return None
    return {"rate": rate["value"], "low": rate.get("low"), "high": rate.get("high")}


def _moved(before, now):
    """True when two ranges don't overlap (both known)."""
    if not before or not now or None in (before["low"], before["high"], now["low"], now["high"]):
        return False
    return before["high"] < now["low"] or now["high"] < before["low"]


def _before(seen):
    overall = seen.get("overall") or {}
    return {"rate": overall.get("rate"), "low": overall.get("low"), "high": overall.get("high"),
            "played": int(seen.get("played") or 0), "of": int(seen.get("of") or 0),
            "games": int(seen.get("games") or 0), "updated": seen.get("updated")}


def _older(forge, g, entry, standard, cat, now, keep):
    find = getattr(g, "older", None)
    if find is None:
        return None
    today_keys = [o.get("key") for o in now.get("opponents") or [] if o.get("key")]
    try:
        found = find(entry, standard, keep=keep(entry), cat=cat, today_keys=today_keys, space=_space(entry),
                     limit=MAX_OLDER)
    except Exception:           # optional: the figure stands without it
        common._log(f"The older gauntlet results of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        return None
    if not found:
        return None
    return {k: found.get(k) for k in ("reason", "opponents", "of", "updated", "overall")}


def fields(forge, g, summary, entry, standard, cat, now, keep):
    """The answers' E3-S34 fields (the module docstring) for entry against the standard sample,
    now being its view."""
    out = {"before": None, "compare": None, "older": None, "notes": [], "rows": {}}
    try:
        prev, seen, note = previous(forge, g, summary, entry, standard, cat, keep)
    except Exception:           # optional: the figure stands without it
        common._log(f"The previous gauntlet list of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        prev = seen = note = None
    if note:
        out["notes"].append(note)
    if seen is not None:
        out["before"] = _before(seen)
        before_rows = {o.get("id"): _rate(o) for o in seen.get("opponents") or []}
        for o in now.get("opponents") or []:
            then = before_rows.get(o.get("id"))
            out["rows"][o.get("id")] = {"before": then, "moved": _moved(then, _rate(o))}
        if int(now.get("played") or 0) > 0:
            compared = g.compare(entry, prev, standard, keep_now=keep(entry), keep_before=keep(prev), cat=cat)
            if compared and compared.get("same"):
                ids = set(compared.get("ids") or [])
                out["compare"] = {"same": compared["same"], "before": compared["before"], "now": compared["now"],
                                  "moved": sum(1 for i, row in out["rows"].items() if i in ids and row["moved"])}
    out["older"] = _older(forge, g, entry, standard, cat, now, keep)
    return out
