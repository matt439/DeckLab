"""When Wizards last announced a Commander change, for the Commander checks
(E9-S24; design in decklab/design/commander-sources.md).

Usage (from the repo root):
    python -m decklab.lib.cards update [--force]    also checks Wizards' sitemap

`cards.update()` calls update() here as a step of its own, so it runs from the
command line and from Deck Lab's server's daily card data check. At most once a
day (or with --force) it makes a conditional, gzipped GET of Wizards' sitemap
(SITEMAP_URL, about 96 KB gzipped) and keeps the newest Commander announcement
it lists in decklab/data/scryfall/official_lists.json. A failed check keeps the
last good result, with the error beside it.

Wizards has no feed, and its terms forbid scraping the Commander format page,
so that page is never fetched (Matt, 2026-10-21). The sitemap lists every
announcement with its publish date in the URL; its lastmod is the last edit,
so it's never used. A post can announce no change at all (the 2025-12-11
Format Panel post), so a new one means "announced, may have changed", never
"changed".

From code:

    from decklab.lib import official_lists
    official_lists.read()       # {"announcement": {"date", "url"} or None, "checked_at",
                                #  "last_success_at", "error"}: what the last checks found
    official_lists.announcement_date("commander-bans-and-restrictions-april-22-2025")
                                # date(2025, 4, 22), or None for a post that doesn't count

The Commander checks (decklab/lib/stats/commander.py, _data_dates) compare the
announcement's date with the card data's (for the Game Changers and the ban
list) and with constants.BRACKET_RULES_DATE (for the bracket rules).
"""
import gzip
import io
import re
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from decklab.lib import card_index, cards
from decklab.lib.config import DATA

STATE_FILE = DATA / "scryfall" / "official_lists.json"
SITEMAP_URL = "https://magic.wizards.com/en/sitemap.xml"
FORMAT = 1                      # the state file's layout
CHECK_EVERY = timedelta(days=1)
TIMEOUT = 60                    # seconds
MAX_DOWNLOAD = 8 << 20          # bytes as sent: the sitemap is about 96 KB gzipped
MAX_SITEMAP = 64 << 20          # bytes unpacked: it's about 660 KB

ANNOUNCEMENTS = "/news/announcements/"
# A slug counts when it names Commander and one of these. The slugs are named
# inconsistently (commander-brackets-beta-update-february-9-2026,
# commander-bans-and-restrictions-april-22-2025,
# commander-banned-and-restricted-announcement-september-23-2024,
# commander-format-panel-update-december-11-2025), so the match is broad.
TOPICS = ("bracket", "banned", "bans", "format-panel", "game-changer")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")
# The publish date ends the slug: -february-9-2026, or -2019-07-08 in older ones.
_WORDS_DATE_RE = re.compile(r"-(" + "|".join(MONTHS) + r")-(\d{1,2})-(\d{4})$")
_ISO_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})$")


class SitemapError(ValueError):
    """The sitemap couldn't be read, or lists no Commander announcement."""


def _now():
    return card_index._now()


# --- Reading the sitemap -----------------------------------------------------

def announcement_date(slug):
    """The publish date of a Commander announcement's slug (the last part of
    its URL), or None when the slug isn't one or has no date at its end."""
    slug = slug.lower().strip("/")
    if "commander" not in slug or not any(topic in slug for topic in TOPICS):
        return None
    try:
        if m := _WORDS_DATE_RE.search(slug):
            return date(int(m[3]), MONTHS.index(m[1]) + 1, int(m[2]))
        if m := _ISO_DATE_RE.search(slug):
            return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:          # february-30: not a date
        return None
    return None


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def newest_announcement(xml_bytes):
    """The newest Commander announcement a sitemap lists, as {"date", "url"}.
    On one date a brackets post comes before a ban list one. Raises
    SitemapError for a sitemap that can't be read, a sitemap index, or one
    listing no Commander announcement."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise SitemapError(f"the sitemap isn't readable XML ({e})") from None
    if _local(root.tag) == "sitemapindex":
        # Not the case on 2026-10-21: then a plain sitemap listed every page.
        raise SitemapError("the sitemap is now an index of sitemaps, which Deck Lab doesn't read yet")
    if _local(root.tag) != "urlset":
        raise SitemapError(f"the sitemap's root is <{_local(root.tag)}>, not <urlset>")
    best = None
    for loc in root.iter():
        if _local(loc.tag) != "loc" or not loc.text:
            continue
        url = loc.text.strip()
        path = urlsplit(url).path
        if ANNOUNCEMENTS not in path:
            continue
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        when = announcement_date(slug)
        if when is None:
            continue
        key = (when, "bracket" in slug.lower(), url)
        if best is None or key > best[0]:
            best = (key, {"date": when.isoformat(), "url": url})
    if best is None:
        raise SitemapError("the sitemap lists no Commander announcement")
    return best[1]


def _unpack(body, encoding):
    """The response body, ungzipped when it was sent gzipped (or looks it)."""
    if "gzip" in (encoding or "").lower() or body[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as unpacked:
                body = unpacked.read(MAX_SITEMAP + 1)
        except (OSError, EOFError) as e:
            raise SitemapError(f"the sitemap's gzip is damaged ({e})") from None
    if len(body) > MAX_SITEMAP:
        raise SitemapError("the sitemap is far bigger than expected")
    return body


def _fetch(headers):
    """(status, body or None, response headers): 304 has no body."""
    try:
        with cards._open_url(SITEMAP_URL, accept="application/xml", timeout=TIMEOUT,
                             headers=headers) as response:
            got = {k.lower(): v for k, v in response.headers.items()}
            body = response.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 304:
            return 304, None, {k.lower(): v for k, v in (e.headers or {}).items()}
        raise
    if len(body) > MAX_DOWNLOAD:
        raise SitemapError("the sitemap is far bigger than expected")
    return 200, _unpack(body, got.get("content-encoding")), got


# --- The stored result -------------------------------------------------------

def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def _valid_announcement(value):
    if not isinstance(value, dict) or not isinstance(value.get("url"), str):
        return None
    try:
        when = date.fromisoformat(value.get("date"))
    except (TypeError, ValueError):
        return None
    return {"date": when.isoformat(), "url": value["url"]}


def read(path=None):
    """What the checks found, read-only: {"announcement": {"date", "url"} or
    None, "checked_at" and "last_success_at" (ISO times or None), "error" (the
    last check's, or None)}. A missing or damaged file reads as never checked."""
    data = cards._read_json(path or STATE_FILE, {})
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        data = {}
    announcement = _valid_announcement(data.get("announcement"))
    success = _parse_time(data.get("last_success_at")) if announcement else None
    checked = _parse_time(data.get("checked_at"))
    error = data.get("error")
    return {"announcement": announcement,
            "checked_at": checked.isoformat(timespec="seconds") if checked else None,
            "last_success_at": success.isoformat(timespec="seconds") if success else None,
            "error": error if isinstance(error, str) else None}


def update(force=False, log=print, path=None):
    """Check the sitemap unless it was checked in the last CHECK_EVERY (always
    with force). Returns True when a check was made and it worked. A failure
    keeps the last good result and records the error."""
    path = path or STATE_FILE
    stored = cards._read_json(path, {})
    if not isinstance(stored, dict) or stored.get("format") != FORMAT:
        stored = {}
    now = _now()
    checked = _parse_time(stored.get("checked_at"))
    if not force and checked is not None and timedelta(0) <= now - checked < CHECK_EVERY:
        found = _valid_announcement(stored.get("announcement"))
        log(f"Official lists: checked {checked.date().isoformat()}; latest Commander announcement "
            + (found["date"] if found else "unknown"))
        return False
    good = _valid_announcement(stored.get("announcement")) is not None
    headers = {"Accept-Encoding": "gzip"}
    if good and not force:
        if stored.get("etag"):
            headers["If-None-Match"] = stored["etag"]
        if stored.get("last_modified"):
            headers["If-Modified-Since"] = stored["last_modified"]
    state = {**stored, "format": FORMAT, "source": SITEMAP_URL,
             "checked_at": now.isoformat(timespec="seconds")}
    try:
        status, body, got = _fetch(headers)
        if status == 304:
            if not good:        # nothing to keep: shouldn't happen without If-None-Match
                raise SitemapError("Wizards answered Not Modified, but there's no earlier result")
            found = state["announcement"]
            log(f"Official lists: Wizards' sitemap unchanged; latest Commander announcement {found['date']}")
        else:
            found = newest_announcement(body)
            state.update(announcement=found, etag=got.get("etag"), last_modified=got.get("last-modified"))
            log(f"Official lists: latest Commander announcement {found['date']} ({found['url']})")
    except (*cards.NETWORK_ERRORS, SitemapError) as e:
        state["error"] = f"{type(e).__name__}: {e}"
        log(f"Official lists: not checked ({state['error']}); keeping the last good result"
            + (f" ({stored['announcement']['date']})." if good else " (there isn't one)."))
        cards._write_json(path, state)
        return False
    state.update(last_success_at=state["checked_at"], error=None)
    cards._write_json(path, state)
    return True
