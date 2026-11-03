"""Popular-decks results kept through a change (E3-S34; decklab/design/gauntlet.md section 11):
the list's previous figure against the standard sample, the two lists over the same opponents,
and saved results that today's keys no longer find (an older Forge, other settings, another AI
pilot, or an opponent's list changed when the catalogue was rebuilt). Nothing is deleted, and
nothing here plays, saves or writes.

    fields(forge, g, summary, entry, standard, cat, now, keep)
        {"before", "compare", "older", "notes", "rows"} for gauntlet_page's answers (their
        docstrings give the shapes); "rows" is {opponent id: {"before", "moved"}} for the view's
        opponent rows.

The previous list is the most recent earlier saved revision whose playable list (forge.card_sha's
sections) differs from today's and has standard games. Revisions are read newest first, PAGE at a
time, at most MAX_REVISIONS of them and MAX_LISTS distinct earlier lists; a revision whose fenced
lists and headings match the newer one's (a table refresh, a reprice, a kit or prose save) isn't
parsed again, and when a bound ends the search before a figure is found, "The list's older
versions weren't all looked at." says so. The history stops at a deletion unless the revision
after it restores exactly the deleted text (a retired deck restored): a deck later made under the
same id is another deck. Only lists with run notes in the deck's space are viewed, at most
MAX_VIEWS of them. An earlier list whose games are all under an older engine (another Forge,
other settings, another pilot) has no figure under today's key; its older results are given
instead (older's "earlier": true) while today's list has no games and no older results. A row is "moved" and
counted only where both lists have meaningful rates (as compare). The run-independent parts are
kept CACHE_SECONDS, since a Matchups page polls while a run plays. The callers have checked the
deck is visible before anything here runs, and nothing returned names a revision, who saved it,
another house deck or who started a run.
"""
import re
import threading
import time
import traceback

from decklab.lib import decks, inventory, permissions

from . import common

MAX_REVISIONS = 200
MAX_LISTS = 20
PAGE = 25
MAX_VIEWS = 3
MAX_OLDER = 300                 # gauntlet_page.MAX_SIZE: older results looked at, newest runs first
CACHE_SECONDS = 60
CACHE_SIZE = 64
NO_HISTORY = "The list's earlier versions can't be read now."
NOT_ALL = "The list's older versions weren't all looked at."
_LISTS = re.compile(r"^```[^\n]*\n.*?^```|^#[^\n]*", re.S | re.M)

_cache, _cache_lock = {}, threading.Lock()


def clear_cache():
    """Forget the kept parts (tests)."""
    with _cache_lock:
        _cache.clear()


def _cached(key, work):
    """work()'s value, kept CACHE_SECONDS under key (at most CACHE_SIZE kept, the oldest dropped)."""
    with _cache_lock:
        found = _cache.get(key)
        if found is not None and time.monotonic() - found[0] < CACHE_SECONDS:
            return found[1]
    value = work()
    with _cache_lock:
        while len(_cache) >= CACHE_SIZE:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (time.monotonic(), value)
    return value


def _space(entry):
    return permissions._deck_space(entry.get("id")) or permissions.HOME


def _sections(rev, kind, slug, space, version):
    """A revision's sections of version, or None (unreadable text, no such list)."""
    if rev.text is None:
        return None
    try:
        parsed = decks.parse_deck(rev.text.encode("utf-8"), slug, kind, None, space)
    except (decks.DeckFileError, ValueError):
        return None
    if version == "owned":
        return parsed.owned or None
    return parsed.target if parsed.has_decklist and parsed.target else None


def _revisions(deck_id):
    """The deck's revisions newest first, PAGE at a time, at most MAX_REVISIONS; then True when
    more were left unread."""
    read, before = 0, None
    while read < MAX_REVISIONS:
        want = min(PAGE, MAX_REVISIONS - read)
        page = list(inventory.deck_revisions_with_text(deck_id, want, before))
        yield from page
        read += len(page)
        if len(page) < want:
            return
        before = page[-1].revision
    if inventory.deck_revisions_with_text(deck_id, 1, before):
        yield True


def _lists_of(text):
    """A revision's fenced lists and headings: equal for revisions that differ only elsewhere."""
    return None if text is None else "\n".join(m.group(0) for m in _LISTS.finditer(text))


def _earlier(forge, summary, entry):
    """([(card_sha, sections)] of the deck's earlier lists, newest first, each sha once and never
    today's; a note or None; True when a bound ended the search)."""
    try:
        space, kind, slug = decks.split_id(summary["id"])
    except ValueError:
        return [], None, False  # a product's or pairing's list has no saved revisions
    engine_kind = decks.engine_kind(summary)
    seen, out, newer, last, deleted = {entry["card_sha"]}, [], None, None, False
    try:
        for rev in _revisions(summary["id"]):
            if rev is True:
                return out, None, True
            if deleted:                 # the revision before a deletion: only a restore of it goes on
                if newer is None or newer.op != "A" or newer.text is None or newer.text != rev.text:
                    return out, None, False
                deleted = False
            if rev.op == "D":
                deleted = True
                continue
            newer = rev
            lists = _lists_of(rev.text)
            if lists is not None and lists == last:
                continue                # the newer revision's lists: the same sha
            last = lists
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
                if len(out) >= MAX_LISTS:
                    return out, None, True
    except (inventory.StateError, inventory.Unavailable):
        return out, NO_HISTORY, False
    return out, None, False


def previous(forge, g, summary, entry, standard, cat, keep):
    """(the previous list's entry, its view against the standard sample, a note or None, [(entry,
    view) of earlier lists viewed with run notes but no games under today's keys, newest first]);
    the first two are None when no earlier list has standard games."""
    found, note, capped = _earlier(forge, summary, entry)
    has_notes = getattr(g, "has_notes", None)
    space, views, unplayed = _space(entry), 0, []
    for sha, sections in found:
        if has_notes is not None and not has_notes({"card_sha": sha, "kind": entry["kind"]}, space):
            continue
        if views >= MAX_VIEWS:
            capped = True
            break
        views += 1
        prev = forge.entry(summary["id"], entry["version"], summary["title"], decks.engine_kind(summary), sections)
        prev["source"] = None
        seen = g.view(prev, standard, keep=keep(prev), cat=cat)
        if int(seen.get("played") or 0) > 0:
            return prev, seen, note, unplayed
        unplayed.append((prev, seen))
    return None, None, note or (NOT_ALL if capped else None), unplayed


def _rate(o):
    """An opponent row's {"rate", "low", "high"}, or None (no rate, or not meaningful: as compare)."""
    rate = o.get("rate") if isinstance(o, dict) and not o.get("not_meaningful") else None
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


def _older(g, entry, standard, cat, view, keep, played=()):
    """older's fields for entry (view: its view of the standard sample; played: the opponents it
    has games against under today's keys), or None."""
    find = getattr(g, "older", None)
    if find is None:
        return None
    today_keys = [o.get("key") for o in view.get("opponents") or [] if o.get("key")]
    try:
        found = find(entry, standard, keep=keep(entry), cat=cat, today_keys=today_keys, space=_space(entry),
                     limit=MAX_OLDER, played=tuple(played))
    except Exception:           # optional: the figure stands without it
        common._log(f"The older gauntlet results of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        return None
    if not found:
        return None
    return {k: found.get(k) for k in ("reason", "opponents", "of", "updated", "overall")}


def _kept(forge, g, summary, entry, standard, cat, keep):
    """The run-independent part: previous()'s first three, and when no earlier list has a figure
    under today's keys, the newest viewed one's older results (marked "earlier"), or None."""
    try:
        prev, seen, note, unplayed = previous(forge, g, summary, entry, standard, cat, keep)
    except Exception:           # optional: the figure stands without it
        common._log(f"The previous gauntlet list of {entry['id']} can't be worked out:\n{traceback.format_exc()}")
        return None, None, None, None
    earlier = None
    if seen is None:
        for list_entry, list_view in unplayed:
            earlier = _older(g, list_entry, standard, cat, list_view, keep)
            if earlier:
                earlier["earlier"] = True
                break
    return prev, seen, note, earlier


def fields(forge, g, summary, entry, standard, cat, now, keep):
    """The answers' E3-S34 fields (the module docstring) for entry against the standard sample,
    now being its view."""
    out = {"before": None, "compare": None, "older": None, "notes": [], "rows": {}}
    key = (id(forge), id(g), summary.get("id"), summary.get("revision"), entry.get("version"),
           entry.get("card_sha"), standard.get("id"), (cat or {}).get("sha"))
    prev, seen, note, earlier = _cached(("previous",) + key,
                                        lambda: _kept(forge, g, summary, entry, standard, cat, keep))
    if note:
        out["notes"].append(note)
    opponents = now.get("opponents") or []
    played = tuple(sorted(o.get("id") for o in opponents if int(o.get("games") or 0) > 0))
    if seen is not None:
        out["before"] = _before(seen)
        before_rows = {o.get("id"): _rate(o) for o in seen.get("opponents") or []}
        for o in opponents:
            then = before_rows.get(o.get("id"))
            out["rows"][o.get("id")] = {"before": then, "moved": _moved(then, _rate(o))}
        if played:
            games = tuple((o.get("id"), int(o.get("games") or 0)) for o in opponents)
            compared = _cached(("compare", games) + key, lambda: g.compare(
                entry, prev, standard, keep_now=keep(entry), keep_before=keep(prev), cat=cat))
            if compared and compared.get("same"):
                ids = set(compared.get("ids") or [])
                out["compare"] = {"same": compared["same"], "before": compared["before"], "now": compared["now"],
                                  "moved": sum(1 for i, row in out["rows"].items() if i in ids and row["moved"])}
    older = _cached(("older", played) + key, lambda: _older(g, entry, standard, cat, now, keep, played))
    if older is None and earlier is not None and not played:
        older = earlier
    out["older"] = dict(older) if older else None
    return out
