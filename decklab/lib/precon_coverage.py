"""Precon coverage (E1-S24): the published precons ranked by how much of
each one a space's free pool already covers, so the next deck to put
together is the one needing the fewest purchases.

    python -m decklab.lib.precons fetch [--format commander|casual]
    python -m decklab.lib.precons coverage [--space S] [--format F] [--limit N] [--json]

`coverage` is read-only and never reaches MTGJSON: it reads the lists
lib/precons.py keeps in its cache (DeckList.json and decks/<file>.json),
and ranks only the precons whose card list is cached. `fetch` fills that
cache, one deck file at a time (lib/precons.deck), for the listed paper
decks it doesn't have yet; it writes nothing but the gitignored cache.

A precon's cards are its Commander, Deck and Sideboard lines (not the
display commander), counted by exact Scryfall name, with basic lands left
out. A card is covered as far as the pool has copies free for a new idea
deck: owned (on the way included) less what built decks and intact
products hold (lib/pool.free_copies). The share is covered cards over the
precon's cards, best first.

A deck file's lines are kept in a summary (SUMMARY, beside the deck files)
keyed on each file's time and size, so a ranking of two thousand precons
doesn't parse two thousand big JSON files every time.
"""
import argparse
import json
import sys
import time
from collections import Counter

from decklab.lib import precons

FORMATS = ("commander", "casual")
SUMMARY = "coverage-summary.json"   # in the cache, beside decks/
SUMMARY_VERSION = 1
FETCH_PAUSE = 0.2                   # seconds between deck files fetched, to go easy on MTGJSON
FETCH_COMMAND = "python -m decklab.lib.precons fetch"


class NotCached(Exception):
    """Nothing to rank: MTGJSON's deck list (or every listed deck's file) isn't cached."""


def _format_of(entry_type, has_commander=True):
    """commander or casual, as Add a precon makes the deck (lib/api/precons._build)."""
    return "commander" if entry_type == "Commander Deck" and has_commander else "casual"


def _of_format(entry, fmt):
    """Whether a listed deck is of fmt (None: any), by its type: only a Commander Deck is commander."""
    return fmt is None or (entry["type"] == "Commander Deck") == (fmt == "commander")


def cached_list():
    """deck_list() from the cache alone (NotCached when it has none): {"date", "decks"}."""
    cache = precons._cache_dir()
    try:
        listed = precons._copy(cache / "DeckList.json", precons._read_deck_list)
    except (OSError, ValueError):
        raise NotCached(f"MTGJSON's precon lists aren't cached yet. Fetch them with: {FETCH_COMMAND}") from None
    try:
        names = precons._copy(cache / "SetList.json", precons._read_set_names)
    except (OSError, ValueError):
        names = {}
    return {"date": listed["date"],
            "decks": [dict(d, set_name=names.get(d["code"], "")) for d in listed["decks"]]}


def _read_summary(path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != SUMMARY_VERSION or not isinstance(raw.get("decks"), dict):
        return {}
    return raw["decks"]


def _cached_lines(files):
    """{file: {"lines": [[section, name, set, number, count]], "commander": bool}} for each of
    files whose deck file is cached and readable. Updates SUMMARY when anything was read anew."""
    cache = precons._cache_dir()
    path = cache / SUMMARY
    kept = _read_summary(path)
    out, changed = {}, False
    for file in files:
        deck_path = cache / "decks" / f"{file}.json"
        try:
            stat = deck_path.stat()
        except OSError:
            continue
        key = [stat.st_mtime_ns, stat.st_size]
        entry = kept.get(file)
        if not (isinstance(entry, dict) and entry.get("key") == key):
            try:
                data = json.loads(deck_path.read_text(encoding="utf-8")).get("data")
            except (OSError, ValueError, AttributeError):
                continue
            if not isinstance(data, dict):
                continue
            read = precons.cards_of(data)["lines"]
            entry = {"key": key, "commander": any(line["section"] == "Commander" for line in read),
                     "lines": [[line["section"], line["name"], line["set"], line["number"], line["count"]]
                               for line in read]}
            kept[file], changed = entry, True
        out[file] = entry
    if changed:
        try:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps({"version": SUMMARY_VERSION, "decks": kept}), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass                    # read again next time
    return out


def card_name(name, set_code, number):
    """A precon line's exact Scryfall name: its printing's, else its own resolved, else as written."""
    from decklab.lib import cards
    p = cards.printing(set_code, number)
    return (cards.resolve(p["name"]) if p else None) or cards.resolve(name) or name


def score(lines, free, resolve=None):
    """{"total", "have", "missing": Counter} of a precon's lines against free (card name -> copies
    free for a new deck). Basic lands are left out."""
    from decklab.lib import decks
    resolve = resolve or card_name
    need = Counter()
    for _section, name, set_code, number, count in lines:
        exact = resolve(name, set_code, number)
        if not decks.is_basic_land(exact):
            need[exact] += count
    have = sum(min(n, free.get(name, 0)) for name, n in need.items())
    return {"total": sum(need.values()), "have": have,
            "missing": Counter({name: n - min(n, free.get(name, 0)) for name, n in need.items()
                                if n > free.get(name, 0)})}


def rank(free, fmt=None, limit=20, resolve=None):
    """The ranking: {"date", "listed", "cached", "precons": [{"file", "name", "code", "set_name",
    "type", "released", "format", "have", "total", "share", "missing"}]}, best first (share, then
    cards covered, then newest), at most limit (None: all). listed counts the paper decks of the
    format MTGJSON lists (by type: only a Commander Deck is commander), cached those whose cards
    could be read from the cache. NotCached when there's nothing to rank."""
    listed = cached_list()
    entries = [d for d in listed["decks"] if _of_format(d, fmt)]
    found = _cached_lines([d["file"] for d in entries])
    if not found:
        raise NotCached(f"No precon's card list is cached yet. Fetch them with: {FETCH_COMMAND}"
                        + (f" --format {fmt}" if fmt else ""))
    ranked = []
    for d in entries:
        got = found.get(d["file"])
        if got is None:
            continue
        s = score(got["lines"], free, resolve)
        if not s["total"]:
            continue
        ranked.append(dict(d, format=_format_of(d["type"], got["commander"]), have=s["have"], total=s["total"],
                           share=s["have"] / s["total"], missing=sum(s["missing"].values())))
    ranked.sort(key=lambda r: (-r["share"], -r["have"], -int(r["released"].replace("-", "") or 0), r["name"]))
    return {"date": listed["date"], "listed": len(entries), "cached": len(found),
            "precons": ranked if limit is None else ranked[:limit]}


def fetch(fmt=None, out=None, pause=FETCH_PAUSE):
    """Fetch the deck files of the listed paper decks (of fmt) the cache doesn't have yet.
    (fetched, failed, how many weren't cached); PreconError when the list itself can't be had."""
    out = out or sys.stdout
    listed = precons.deck_list()
    decks_dir = precons._cache_dir() / "decks"
    todo = [d for d in listed["decks"] if not (decks_dir / f"{d['file']}.json").exists()
            and _of_format(d, fmt)]
    fetched = failed = 0
    for i, d in enumerate(todo, 1):
        try:
            precons.deck(d["file"])
            fetched += 1
        except (precons.PreconError, LookupError) as e:
            failed += 1
            print(f"{d['file']}: {e}", file=sys.stderr)
            if failed >= 5 and not fetched:
                break                   # MTGJSON is down: one message is enough
        if i % 50 == 0:
            print(f"{i} of {len(todo)} fetched", file=out, flush=True)
        if pause and i < len(todo):
            time.sleep(pause)
    return fetched, failed, len(todo)


def _print_ranking(result, space, fmt, out=None):
    out = out or sys.stdout
    what = f"{fmt} precons" if fmt else "Precons"
    print(f"{what} by how much of each the {space} pool has free for a new deck "
          f"(basic lands left out; MTGJSON's lists of {result['date'] or 'an unknown date'}).", file=out)
    width = len(str(len(result["precons"])))
    for i, r in enumerate(result["precons"], 1):
        released = f", {r['released']}" if r["released"] else ""
        print(f"{i:>{width}}. {r['share']:4.0%}  {r['have']}/{r['total']}  {r['name']} "
              f"({r['set_name'] or r['code'].upper()}, {r['type']}{released})  {r['file']}", file=out)
    if not result["precons"]:
        print("No cached precon has any cards to count.", file=out)
    if result["cached"] < result["listed"]:
        print(f"Only {result['cached']} of the {result['listed']} listed precons are cached; the rest aren't "
              f"ranked. Fetch them with: {FETCH_COMMAND}" + (f" --format {fmt}" if fmt else ""), file=out)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.precons",
                                     description="Published precons (MTGJSON's lists) and how much of each "
                                                 "a space's free pool covers.")
    sub = parser.add_subparsers(dest="command", required=True)
    cov = sub.add_parser("coverage", help="rank the cached precons by free-pool coverage (read-only)")
    cov.add_argument("--space", default="home", help="whose pool: home (default) or a person's space")
    cov.add_argument("--format", choices=FORMATS, help="only Commander or only casual (60-card) precons")
    cov.add_argument("--limit", type=int, default=20, help="how many to list (default 20; 0 lists all)")
    cov.add_argument("--json", action="store_true", help="print the ranking as JSON")
    get = sub.add_parser("fetch", help="fetch the listed precons' card lists the cache doesn't have yet")
    get.add_argument("--format", choices=FORMATS, help="only Commander or only casual precons")
    args = parser.parse_args(argv)

    if args.command == "fetch":
        try:
            fetched, failed, todo = fetch(args.format)
        except precons.PreconError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"Fetched {fetched} of {todo} precon lists not cached before"
              + (f"; {failed} couldn't be fetched" if failed else "") + ".")
        return 1 if failed else 0

    if args.limit < 0:
        parser.error("--limit can't be negative")
    from decklab.lib import inventory, pool, spaces
    from decklab.lib.inventory import entry
    try:
        cached_list()               # before the pool, so a new install hears what to fetch first
    except NotCached as e:
        print(e, file=sys.stderr)
        return 1
    with entry.command():
        try:
            p = pool.load_pool(args.space)
            result = rank(pool.free_copies(p), args.format, args.limit or None)
        except NotCached as e:
            print(e, file=sys.stderr)
            return 1
        except spaces.SpaceNotFound as e:
            print(e, file=sys.stderr)
            return 1
        except inventory.Unavailable as e:
            print(e, file=sys.stderr)
            return 2
        except (FileNotFoundError, RuntimeError) as e:     # no card index yet, or an old one
            print(e, file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        _print_ranking(result, args.space, args.format)
    return 0
