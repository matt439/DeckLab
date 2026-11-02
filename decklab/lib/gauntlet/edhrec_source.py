"""The gauntlet's EDHREC source (design section 3): its top commanders and each one's average
decks, Bracket 2 ("core") and Bracket 3 ("upgraded").

Fetch order: pages/commanders/year.json (the top commanders of the past two years, 100 a page,
"more" naming the next page), then for each commander its page for its themes (edhrec.fetch,
with the 7-day cache it shares with the EDHREC ideas feature) and average-decks/<slug>/core.json
and .../upgraded.json. Every request goes through edhrec.get_json (EDHREC's User-Agent, one second
apart). The raw pages are cached in sources/edhrec/ (lib/gauntlet DATA): the top list for
TOP_MAX_AGE, an average deck for AVERAGE_MAX_AGE (they change slowly, and a stable catalogue keeps
result keys stable). A failed fetch keeps the older copy; with none, that deck is left out and the
build says why.

The pages were read against copies captured once by hand (2026-11-02, decklab/tests/fixtures/
gauntlet/): an average deck's "deck" holds "commander" (its commander's names) and "cards" ({card
type: [[name, quantity]]}); "container" -> "json_dict" -> "card" -> "num_decks" the decks it
averages; "panels" -> "taglinks" its themes with counts. Nothing else is assumed: anything else
that's missing or odd makes that deck a problem, never a guess.

offline=True (the build's dry run) reads only the cached copies and fetches nothing.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from decklab.lib import edhrec

from . import sources_dir

TOP_PATH = "commanders/year.json"
AVERAGE_PATH = "average-decks/{slug}/{tier}.json"
AVERAGE_SITE = "https://edhrec.com/average-decks/{slug}/{tier}"
TIERS = ("core", "upgraded")
TOP_MAX_AGE = timedelta(days=7)
AVERAGE_MAX_AGE = timedelta(days=30)
MIN_REFRESH = timedelta(hours=1)    # refresh=True doesn't fetch a copy younger than this
THEME_SHARE = 0.25                  # a theme held by this share of the commander's decks is kept
MAX_LINES = 250                     # card lines read from one average deck
MAX_TOP_PAGES = 10                  # "more" pages followed for a large top


def _now():
    return datetime.now(timezone.utc)


def _cache_path(path):
    return sources_dir("edhrec") / path.replace("/", "--")


def _read_cache(path):
    """(fetched datetime, page) of a cached raw page, or None."""
    try:
        kept = json.loads(_cache_path(path).read_text(encoding="utf-8"))
        return datetime.fromisoformat(kept["fetched"]), kept["page"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache(path, fetched, page):
    target = _cache_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"fetched": fetched.isoformat(timespec="seconds"), "page": page}, f, ensure_ascii=False)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cached_page(path, max_age, refresh=False, offline=False):
    """(page, fetched ISO time, note) for one EDHREC JSON path: the cached copy while it's younger
    than max_age (MIN_REFRESH with refresh), else a new fetch, else the older copy with a note
    saying why. edhrec.NoPage or edhrec.EdhrecError when there's no copy to fall back on."""
    kept = _read_cache(path)
    limit = MIN_REFRESH if refresh else max_age
    if kept is not None and (offline or _now() - kept[0] < limit):
        return kept[1], kept[0].isoformat(timespec="seconds"), None
    if offline:
        raise edhrec.EdhrecError(f"No cached copy of EDHREC's {path} (a dry run fetches nothing)")
    fetched = _now()
    try:
        page = edhrec.get_json(path)
    except edhrec.EdhrecError as e:
        if kept is None:
            raise
        return kept[1], kept[0].isoformat(timespec="seconds"), f"{e}, so the copy from before is used."
    try:
        _write_cache(path, fetched, page)
    except OSError:
        pass                        # used now, fetched again next time
    return page, fetched.isoformat(timespec="seconds"), None


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_top(page):
    """The commanders of a top-commanders page, in its order: [{"name", "slug", "rank", "decks"}],
    and the path of its next page ("more") or None."""
    try:
        group = page["container"]["json_dict"]["cardlists"][0]
        views = group["cardviews"]
        if not isinstance(views, list):
            raise TypeError
    except (KeyError, IndexError, TypeError):
        raise edhrec.EdhrecError("EDHREC's top commanders page has no list Deck Lab can read") from None
    out = []
    for view in views:
        if not isinstance(view, dict):
            continue
        name, slug = view.get("name"), view.get("sanitized") or view.get("slug")
        if not (isinstance(name, str) and name.strip() and isinstance(slug, str)
                and edhrec._SLUG.fullmatch(slug) and len(slug) <= 200):
            continue
        out.append({"name": name.strip()[:200], "slug": slug, "rank": _number(view.get("rank")),
                    "decks": _number(view.get("num_decks"))})
    more = group.get("more") if isinstance(group.get("more"), str) else None
    return out, more


def top_commanders(top=100, refresh=False, offline=False, log=print):
    """The top commanders (parse_top's rows), at most top, following "more" pages as needed."""
    found, path, pages, seen = [], TOP_PATH, 0, set()
    while path and len(found) < top and pages < MAX_TOP_PAGES:
        page, _, note = cached_page(path, TOP_MAX_AGE, refresh, offline)
        if note:
            log(f"EDHREC top commanders: {note}")
        rows, path = parse_top(page)
        for row in rows:
            if row["slug"] not in seen:
                seen.add(row["slug"])
                found.append(row)
        pages += 1
    return found[:top]


def _line(raw):
    """[qty, name] of one [name, quantity] pair, or None."""
    if not (isinstance(raw, list) and len(raw) == 2):
        return None
    name, qty = raw
    if isinstance(name, str) and name.strip() and len(name) <= 200 and _number(qty) and 1 <= qty <= 99:
        return [qty, name.strip()]
    return None


def _themes(page):
    """[{"slug", "name", "decks"}] of a page's "panels" -> "taglinks" (edhrec._themes's reading)."""
    return edhrec._themes(page) if isinstance(page, dict) else []


def parse_average(page):
    """An average deck page, read: {"commanders": [names], "cards": [[qty, name]] (the 99, in the
    page's order), "decks" (the decks it averages, or None), "themes" (its taglinks), "header"}.
    EdhrecError when its deck or commander can't be read."""
    deck = page.get("deck") if isinstance(page, dict) else None
    if not isinstance(deck, dict) or not isinstance(deck.get("cards"), dict):
        raise edhrec.EdhrecError("EDHREC's average deck has no card list Deck Lab can read")
    commanders = [n.strip() for n in deck.get("commander") or [] if isinstance(n, str) and n.strip()]
    if not 1 <= len(commanders) <= 2:
        raise edhrec.EdhrecError("EDHREC's average deck doesn't name its commander")
    lines, bad = [], 0
    for group in deck["cards"].values():
        for raw in group if isinstance(group, list) else []:
            line = _line(raw)
            if line is None:
                bad += 1
            elif len(lines) < MAX_LINES:
                lines.append(line)
    if bad:
        raise edhrec.EdhrecError(f"{bad} of the average deck's card lines can't be read")
    if not lines:
        raise edhrec.EdhrecError("EDHREC's average deck lists no cards")
    body = page.get("container", {}).get("json_dict", {}) if isinstance(page.get("container"), dict) else {}
    card = body.get("card") if isinstance(body, dict) and isinstance(body.get("card"), dict) else {}
    header = page.get("header") if isinstance(page.get("header"), str) else ""
    return {"commanders": commanders, "cards": lines, "decks": _number(card.get("num_decks")),
            "themes": _themes(page), "header": header[:200]}


def kept_themes(themes, decks):
    """The names of the themes at least THEME_SHARE of the commander's decks hold."""
    if not decks:
        return []
    return [t["name"] for t in themes or [] if isinstance(t.get("decks"), int) and t["decks"] >= THEME_SHARE * decks]


def commander_themes(names, average, refresh=False, offline=False):
    """(theme names, note) for a commander: from its EDHREC page (edhrec.fetch) and, when that
    can't be had (or offline), the average deck's own taglinks."""
    if not offline:
        try:
            page = edhrec.fetch(names, refresh)
            return kept_themes(page.get("themes"), page.get("decks")), page.get("stale")
        except edhrec.EdhrecError as e:
            note = f"its commander page couldn't be had ({e}); the average deck's themes are used"
            return kept_themes(average["themes"], average["decks"]), note
    return kept_themes(average["themes"], average["decks"]), None


def record(commander, tier, average, fetched, themes):
    """The raw source record of one average deck (catalogue.build normalises it)."""
    slug = commander["slug"]
    return {"id": f"gauntlet:edhrec/{slug}-{tier}", "title": f"{' + '.join(average['commanders'])} ({tier})",
            "kind": "commander", "tier": tier,
            "source": {"kind": "edhrec", "url": AVERAGE_SITE.format(slug=slug, tier=tier), "fetched": fetched,
                       "rank": commander.get("rank"), "decks": average.get("decks") or commander.get("decks")},
            "commanders": average["commanders"], "cards": average["cards"], "themes": themes, "problems": []}


def decks(top=100, refresh=False, offline=False, log=print):
    """(records, excluded): the average decks of the top commanders, both tiers, and
    [(id, reason)] of those that couldn't be had."""
    records, excluded = [], []
    try:
        commanders = top_commanders(top, refresh, offline, log)
    except edhrec.EdhrecError as e:
        return [], [("gauntlet:edhrec", f"EDHREC's top commanders couldn't be had: {e}")]
    log(f"EDHREC: {len(commanders)} top commanders")
    for commander in commanders:
        themes = None
        for tier in TIERS:
            deck_id = f"gauntlet:edhrec/{commander['slug']}-{tier}"
            try:
                page, fetched, note = cached_page(AVERAGE_PATH.format(slug=commander["slug"], tier=tier),
                                                  AVERAGE_MAX_AGE, refresh, offline)
                average = parse_average(page)
            except edhrec.EdhrecError as e:
                excluded.append((deck_id, str(e)))
                continue
            if note:
                log(f"{deck_id}: {note}")
            if themes is None:
                themes, theme_note = commander_themes(average["commanders"], average, refresh, offline)
                if theme_note:
                    log(f"{commander['name']}: {theme_note}")
            records.append(record(commander, tier, average, fetched, themes))
    return records, excluded
