"""EDHREC's commonly played cards for a commander (E9-S07), marked in the deck's own space.

Usage (from the repo root):
    python -m decklab.lib.edhrec <deck-id> [--refresh] [--no-prices] [--all]

EDHREC publishes each commander's page as JSON at
https://json.edhrec.com/pages/commanders/<slug>.json (checked 2026-10-28; a
commander it has no page for answers 403). The slug is the commander's name
as EDHREC writes it in its addresses (commander_slug): the front face of a
two-faced card, accents dropped, lowercase, apostrophes and commas removed and
every other run of non-letters a hyphen; two commanders (partners, a
Background) are both slugs joined, in alphabetical order first and, when
EDHREC has no page for that, the other order. For a pair, the order EDHREC
doesn't use answers 200 with only {"redirect": "/commanders/<its slug>"}
(checked 2026-10-28 with Thrasios and Tymna, and Wilson and Raised by
Giants): that's kept like a page (redirect_slug) and its slug followed.

fetch() keeps each page, reduced to its card lists, in decklab/data/edhrec/
<slug>.json with the time it was fetched, and fetches again only when that
copy is more than MAX_AGE old (or with refresh=True, which still waits
MIN_REFRESH since the last fetch). Every request waits MIN_GAP after the one
before, sends Deck Lab's User-Agent and gives up after TIMEOUT. A failed fetch
keeps the older copy (the answer says it's out of date and why), isn't tried
again for RETRY_AFTER, and with no copy raises EdhrecError, which the page
shows as a plain message: nothing else on the page depends on it. No decklist
is ever sent: only the commander's name is in the address.

ideas() marks each card for the deck's space: in the deck already (its
Planned list), on its Considering list, free (a copy no built deck or intact
product holds, beyond what the Planned list needs), in use (owned, but every
copy is held: the decks holding it are never named), or to buy, with its AUD
estimate (pool.compare's price: the cheapest non-foil paper printing). EDHREC
lists only cards within the commander's colour identity and legal in
Commander; ideas() checks both again against Scryfall's data and leaves out
anything that isn't, so a stale or odd page never suggests one. Basic lands
are left out (every deck has plenty).

EDHREC's data is its own: the answer credits it and links to the commander's
page (AGENTS.md: "Commander deck ideas: EDHREC").
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

from decklab.lib import cards, config, decks, pool, spaces

CACHE = None                        # the cache folder; None: config.DATA / "edhrec" (tests point it elsewhere)
PAGE_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
SITE_URL = "https://edhrec.com/commanders/{slug}"
USER_AGENT = config.USER_AGENT + " EDHREC ideas"
FORMAT = 1                          # the cached file's layout; another one is fetched again
MAX_AGE = timedelta(days=7)         # a copy older than this is fetched again
NO_PAGE_AGE = timedelta(days=1)     # how long "EDHREC has no page" is believed
MIN_REFRESH = timedelta(hours=1)    # refresh=True doesn't fetch a copy younger than this
RETRY_AFTER = 300                   # seconds: a failed fetch isn't tried again sooner
MIN_GAP = 1.0                       # seconds between two requests to EDHREC
TIMEOUT = 20                        # seconds
MAX_BYTES = 8 << 20                 # a page bigger than this is refused
MAX_CARDS = 600                     # cards kept from one page

_lock = threading.Lock()            # one fetch at a time: a second asker waits and reads the copy it made
_failed = {}                        # slug -> time.monotonic() of its last failed fetch
_last_request = 0.0


class EdhrecError(RuntimeError):
    """EDHREC couldn't be reached (or sent something unreadable) and nothing is cached."""


class NoPage(EdhrecError):
    """EDHREC has no page for this commander (or pair)."""


class NotCommander(ValueError):
    """The deck isn't a Commander deck with a commander."""


def _cache_dir():
    return CACHE if CACHE is not None else config.DATA / "edhrec"


def _now():
    return datetime.now(timezone.utc)


# --- Slugs -------------------------------------------------------------------

def name_slug(name):
    """EDHREC's slug of one card name: "Atraxa, Praetors' Voice" -> "atraxa-praetors-voice"."""
    front = str(name).split(" // ")[0]
    plain = unicodedata.normalize("NFKD", front).encode("ascii", "ignore").decode("ascii").lower()
    plain = re.sub(r"['’,.]", "", plain)
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def commander_slugs(names):
    """The slugs to try for one or two commanders, the likeliest first."""
    parts = [name_slug(name) for name in names if name_slug(name)]
    if not parts:
        return []
    if len(parts) == 1:
        return parts
    ordered = sorted(parts)
    return list(dict.fromkeys(["-".join(ordered), "-".join(reversed(ordered))]))


# --- Fetching and the cache ---------------------------------------------------

def _get(slug):
    """EDHREC's page for slug as parsed JSON. NoPage for a commander it has no page for (403, 404);
    EdhrecError for anything else that goes wrong."""
    global _last_request
    wait = _last_request + MIN_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    request = urllib.request.Request(PAGE_URL.format(slug=slug),
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (403, 404):
            raise NoPage(f"EDHREC has no page for {slug}") from None
        raise EdhrecError(f"EDHREC answered {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise EdhrecError(f"EDHREC couldn't be reached ({reason})") from None
    if len(data) > MAX_BYTES:
        raise EdhrecError("EDHREC's page was too big to read")
    try:
        return json.loads(data)
    except ValueError:
        raise EdhrecError("EDHREC sent a page Deck Lab can't read") from None


_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def redirect_slug(page):
    """The commander slug EDHREC's {"redirect": "/commanders/<slug>"} page points to, None for any other
    page, or "" for a redirect Deck Lab can't follow (treated as no page)."""
    if not isinstance(page, dict) or "redirect" not in page:
        return None
    match = re.fullmatch(r"/?commanders/([^/?#]+)/?", page["redirect"]) if isinstance(page["redirect"], str) else None
    slug = match.group(1) if match else ""
    return slug if _SLUG.fullmatch(slug) and len(slug) <= 200 else ""


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def reduce_page(page, slug, fetched):
    """The parts of EDHREC's page Deck Lab keeps: {"format", "slug", "url", "commander", "decks",
    "fetched", "lists": [{"header", "cards": [{"name", "decks", "of", "synergy"}]}]}. EdhrecError
    for a page without the card lists."""
    try:
        body = page["container"]["json_dict"]
        lists = body["cardlists"]
        if not isinstance(lists, list):
            raise TypeError
    except (KeyError, TypeError):
        raise EdhrecError("EDHREC's page has no card lists Deck Lab can read") from None
    card = body.get("card") if isinstance(body.get("card"), dict) else {}
    header = page.get("header") if isinstance(page.get("header"), str) else ""
    out, kept = [], 0
    for group in lists:
        if not isinstance(group, dict) or not isinstance(group.get("cardviews"), list):
            continue
        rows = []
        for view in group["cardviews"]:
            name = view.get("name") if isinstance(view, dict) else None
            if not isinstance(name, str) or not name.strip() or kept >= MAX_CARDS:
                continue
            decks_with, of = _number(view.get("num_decks")), _number(view.get("potential_decks"))
            rows.append({"name": name.strip()[:200], "decks": decks_with, "of": of,
                         "synergy": round(view["synergy"], 4) if _number(view.get("synergy")) is not None else None})
            kept += 1
        if rows:
            title = group.get("header") if isinstance(group.get("header"), str) else "Cards"
            out.append({"header": title.strip()[:80] or "Cards", "cards": rows})
    if not out:
        raise EdhrecError("EDHREC's page lists no cards")
    return {"format": FORMAT, "slug": slug, "url": SITE_URL.format(slug=slug),
            "commander": re.sub(r"\s*\(Commander\)\s*$", "", header)[:200] or None,
            "decks": _number(card.get("num_decks")), "fetched": fetched.isoformat(timespec="seconds"),
            "lists": out}


def _path(slug):
    return _cache_dir() / f"{slug}.json"


def _read(slug):
    """The cached copy for slug, or None."""
    try:
        kept = json.loads(_path(slug).read_text(encoding="utf-8"))
        if kept.get("format") != FORMAT or kept.get("slug") != slug:
            return None
        datetime.fromisoformat(kept["fetched"])
        return kept
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _write(slug, kept):
    folder = _cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=slug + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False)
        os.replace(tmp, _path(slug))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _age(kept):
    return _now() - datetime.fromisoformat(kept["fetched"])


def _one(slug, refresh):
    """(copy, note) for one slug: the cached copy while it's young enough, else a new fetch, else the
    older copy with a note saying why it wasn't refreshed. Callers hold _lock."""
    kept = _read(slug)
    if kept is not None:
        limit = (NO_PAGE_AGE if kept.get("missing") else MAX_AGE) if not refresh else MIN_REFRESH
        if _age(kept) < limit:
            return kept, None
    failed = _failed.get(slug)
    if failed is not None and time.monotonic() - failed < RETRY_AFTER:
        if kept is not None:
            return kept, "EDHREC couldn't be reached a few minutes ago, so this is the copy from before."
        raise EdhrecError("EDHREC couldn't be reached a few minutes ago; try again later.")
    fetched = _now()
    try:
        page = _get(slug)
        target = redirect_slug(page)
        if target == "":
            raise NoPage(f"EDHREC sent {slug} somewhere Deck Lab can't follow")
        if target:
            made = {"format": FORMAT, "slug": slug, "redirect": target, "fetched": fetched.isoformat(timespec="seconds")}
        else:
            made = reduce_page(page, slug, fetched)
    except NoPage:
        _failed.pop(slug, None)
        made = {"format": FORMAT, "slug": slug, "missing": True, "fetched": fetched.isoformat(timespec="seconds")}
    except EdhrecError as e:
        _failed[slug] = time.monotonic()
        if kept is not None and not kept.get("missing"):
            return kept, f"{e}, so this is the copy from before."
        raise
    else:
        _failed.pop(slug, None)
    try:
        _write(slug, made)
    except OSError:
        pass                        # not kept: it's fetched again next time
    return made, None


def fetch(commanders, refresh=False):
    """EDHREC's lists for the commander names (one, or two together): reduce_page's dict plus
    "stale" (None, or why it's an older copy). NoPage when EDHREC has no page for them;
    EdhrecError when it can't be reached and nothing is cached."""
    slugs = commander_slugs(commanders)
    if not slugs:
        raise NoPage("The commander has no name EDHREC could know it by")
    tried = set()
    with _lock:
        for slug in slugs:
            hops = 0
            while slug not in tried and hops < 3:     # a redirect is followed, but never round in circles
                tried.add(slug)
                kept, note = _one(slug, refresh)
                if kept.get("redirect"):
                    slug, hops = kept["redirect"], hops + 1
                    continue
                if not kept.get("missing"):
                    return dict(kept, stale=note)
                break
    raise NoPage(f"EDHREC has no page for {' and '.join(commanders)}")


# --- Marking the ideas ---------------------------------------------------------

def _deck(deck_id):
    """(the deck file, its commanders' exact names) of a Commander deck. NotCommander otherwise."""
    space, kind, slug = spaces.split_deck_id(deck_id)
    if kind != "commander":
        raise NotCommander("EDHREC ideas are for Commander decks.")
    deck = decks.read_deck_file(decks.find_deck_file(kind, slug, space), space=space)
    names = [cards.resolve(line.name) or line.name for line in deck.target.get("Commander", [])]
    if not names:
        raise NotCommander(f"{deck.title} has no commander yet: add one to its Commander section first.")
    return deck, names


def _counts(lines):
    out = Counter()
    for line in lines:
        out[cards.resolve(line.name) or line.name] += line.quantity
    return out


def ideas(deck_id, p=None, prices=True, refresh=False):
    """EDHREC's cards for a Commander deck: {"deck_id", "commanders", "identity", "source" (fetch()'s
    commander, decks, url, fetched and stale), "groups": [{"header", "cards": [{"name", "inclusion"
    (0-100, None when EDHREC gives no count), "decks", "of", "synergy", "in_deck", "considering",
    and with a pool p: "status" (in_deck, free, in_use or to_buy), "free", "on_the_way", "aud_each",
    "priced_printing"}]}], "left_out" (cards outside the identity, not legal or not known: [{"name",
    "why"}]), "rate", "rate_date", "price_date", "price_error", "deck" (the parsed deck file)}. p is
    the deck's space's pool, or None for a viewer who mayn't see it: then nothing says what's owned.
    Raises NotCommander, NoPage or EdhrecError."""
    deck, commanders = _deck(deck_id)
    source = fetch(commanders, refresh)
    identity = set()
    for name in commanders:
        identity.update((cards.card(name) or {}).get("color_identity", []))
    planned = _counts(line for section in deck.target.values() for line in section)
    considered = _counts(deck.considering or [])
    free = pool.free_copies(p, pool.self_ids(deck_id)) if p is not None else None
    result = {"deck_id": deck_id, "deck": deck, "commanders": commanders, "identity": "".join(c for c in "WUBRG" if c in identity),
              "source": {key: source.get(key) for key in ("commander", "decks", "url", "fetched", "stale")},
              "groups": [], "left_out": [], "rate": None, "rate_date": None, "price_date": None, "price_error": None}
    if p is not None and prices:
        try:
            result["rate"], result["rate_date"] = cards.usd_to_aud()
            result["price_date"] = cards.price_date()
        except RuntimeError as e:
            result["price_error"] = str(e)
            prices = False
    left_out = {}
    for group in source["lists"]:
        rows = []
        for item in group["cards"]:
            if decks.is_basic_land(item["name"]):
                continue
            exact = cards.resolve(item["name"])
            card = cards.card(exact) if exact else None
            if card is None:
                left_out.setdefault(item["name"], "not a card Deck Lab knows")
                continue
            if exact in commanders:
                continue
            if set(card.get("color_identity", [])) - identity:
                left_out.setdefault(exact, "outside the commander's colour identity")
                continue
            if card.get("commander_legality") in ("banned", "not_legal"):
                left_out.setdefault(exact, "not legal in Commander")
                continue
            share = (round(100 * item["decks"] / item["of"]) if item.get("decks") is not None and item.get("of")
                     else None)
            row = {"name": exact, "inclusion": share, "decks": item.get("decks"), "of": item.get("of"),
                   "synergy": item.get("synergy"), "in_deck": planned.get(exact, 0) > 0,
                   "considering": considered.get(exact, 0) > 0}
            if free is not None:
                spare = max(free.get(exact, 0) - planned.get(exact, 0), 0)
                row["free"] = spare
                row["on_the_way"] = sum(qty for _, qty in p.on_the_way.get(exact, []))
                row["status"] = ("in_deck" if row["in_deck"] else "free" if spare else
                                 "in_use" if p.owned.get(exact, 0) else "to_buy")
                price = cards.price_aud(exact) if prices and row["status"] == "to_buy" else None
                row["aud_each"] = price.aud if price else None
                row["priced_printing"] = pool._printing_label(price)
            rows.append(row)
        if rows:
            result["groups"].append({"header": group["header"], "cards": rows})
    result["left_out"] = [{"name": name, "why": why} for name, why in sorted(left_out.items())]
    return result


# --- Command line --------------------------------------------------------------

STATUS_WORDS = {"in_deck": "in the deck", "free": "free", "in_use": "in use (every copy in another deck)",
                "to_buy": "to buy"}


def _print(result, show_all):
    source = result["source"]
    fetched = source["fetched"][:10] if source.get("fetched") else "?"
    print(f"EDHREC ideas for {' & '.join(result['commanders'])} ({result['identity'] or 'colourless'}): "
          f"{source['url']}, fetched {fetched}"
          + (f", from {source['decks']:,} decks" if isinstance(source.get("decks"), int) else ""))
    if source.get("stale"):
        print(f"Note: {source['stale']}")
    if result["price_error"]:
        print(f"No prices: {result['price_error']}")
    elif result["rate"] is not None:
        print(f"Prices: ~AUD, cheapest non-foil printing, 1 USD = {result['rate']} AUD "
              f"(ECB rate of {result['rate_date']}), pulled {result['price_date']}")
    seen = {}                       # a card EDHREC lists in two categories is counted once
    for group in result["groups"]:
        shown = [c for c in group["cards"] if show_all or not c["in_deck"]]
        if not shown:
            continue
        print(f"\n{group['header']}")
        for c in shown:
            share = f"{c['inclusion']:3d}%" if c["inclusion"] is not None else "   ?"
            status = c.get("status")
            seen.setdefault(c["name"], status)
            words = STATUS_WORDS.get(status, "")
            if status == "free" and c["free"] > 1:
                words = f"free ({c['free']})"
            if status == "to_buy" and result["rate"] is not None:
                words += f", ~A${c['aud_each']:.2f}" if c.get("aud_each") is not None else ", no price"
            if c.get("on_the_way"):
                words += f", {c['on_the_way']} on the way"
            if c["considering"]:
                words += ", considering"
            print(f"  {share}  {c['name']}" + (f"  [{words}]" if words else ""))
    tally = Counter(seen.values())
    if tally:
        print("\n" + ", ".join(f"{n} {STATUS_WORDS[s].split(' (')[0]}" for s, n in tally.items() if s in STATUS_WORDS))
    if result["left_out"]:
        print(f"Left out: {len(result['left_out'])} card(s) outside the colour identity, not legal, or unknown.")


def main(argv=None):
    from decklab.lib import inventory
    from decklab.lib.inventory import entry
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.edhrec",
                                     description="EDHREC's commonly played cards for a Commander deck's "
                                                 "commander, marked owned, free or to buy in the deck's space.")
    parser.add_argument("deck", help="a Commander deck's id, e.g. commander/giada-angels or user2/commander/<slug>")
    parser.add_argument("--refresh", action="store_true",
                        help=f"fetch again when the copy is over {int(MIN_REFRESH.total_seconds() // 3600)} hour old")
    parser.add_argument("--no-prices", action="store_true", help="skip the AUD estimates")
    parser.add_argument("--all", action="store_true", help="also list the cards already in the deck")
    args = parser.parse_args(argv)
    with entry.command():
        try:
            p = pool.load_pool(spaces.space_of(args.deck))
            result = ideas(args.deck, p, prices=not args.no_prices, refresh=args.refresh)
        except (decks.DeckNotFound, spaces.SpaceNotFound, NotCommander, ValueError) as e:
            print(e, file=sys.stderr)
            return 1
        except inventory.Unavailable as e:
            print(e, file=sys.stderr)
            return 2
        except EdhrecError as e:
            print(f"{e}. Nothing else is affected.", file=sys.stderr)
            return 3
        _print(result, args.all)
        return 0


if __name__ == "__main__":
    sys.exit(main())
