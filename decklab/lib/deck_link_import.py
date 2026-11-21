"""Read public provider decklists as text for the editor's ordinary import review."""
import http.client
import json
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from decklab.lib import accessory_fetch, config, decks
from decklab.lib.api.common import MAX_QTY, ApiError


MAX_LINK = 500
MAX_RESPONSE = 4 * 1024 * 1024
MAX_ROWS = 800
FETCH_SECONDS = 10
_slots = threading.BoundedSemaphore(3)
_moxfield_path = re.compile(r"/decks/([A-Za-z0-9_-]{1,60})(?:/primer)?/?")
_archidekt_path = re.compile(r"/decks/([0-9]{1,12})(?:/[^/]+)?/?")
_control = re.compile(r"[\x00-\x1f\x7f]")
_set = re.compile(r"[A-Za-z0-9]{2,8}")
_number = re.compile(r"[^\s*#(][^\s*#]{0,29}")
_boards = {"commanders": "Commander", "companions": "Companion", "mainboard": "Deck", "sideboard": "Sideboard"}

_unsupported = "Paste the address of a public Moxfield or Archidekt deck."
_private = "That deck isn't public or couldn't be found."
_unavailable = "The deck provider couldn't supply this list. Try again or paste its text export."


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _source(link):
    if not isinstance(link, str) or len(link) > MAX_LINK or _control.search(link):
        raise ApiError(400, _unsupported)
    try:
        parts = urlsplit(link.strip())
    except ValueError:
        raise ApiError(400, _unsupported) from None
    if parts.scheme == "https":
        host = parts.netloc.lower()
        if host in {"moxfield.com", "www.moxfield.com"} and (match := _moxfield_path.fullmatch(parts.path)):
            return "Moxfield", f"https://api2.moxfield.com/v3/decks/all/{match[1]}"
        if host in {"archidekt.com", "www.archidekt.com"} and (match := _archidekt_path.fullmatch(parts.path)):
            return "Archidekt", f"https://archidekt.com/api/decks/{match[1]}/"
    raise ApiError(400, _unsupported)


def _download(endpoint):
    """Fetch only the reconstructed endpoint, using checked sockets with a total deadline."""
    if not _slots.acquire(blocking=False):
        raise ApiError(503, "Deck Lab is already reading other deck links. Try again in a moment.")
    watch = accessory_fetch._Watch(time.monotonic() + FETCH_SECONDS)
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirects(), accessory_fetch._WatchedHttps(watch))
        request = Request(endpoint, headers={"Accept": "application/json", "User-Agent": config.USER_AGENT})
        with opener.open(request, timeout=watch.socket_timeout()) as response:
            length = response.headers.get("Content-Length", "")
            if length.isascii() and length.isdecimal() and (len(length) > 10 or int(length) > MAX_RESPONSE):
                raise ApiError(502, _unavailable)
            raw = response.read(MAX_RESPONSE + 1)
            if watch.expired or len(raw) > MAX_RESPONSE:
                raise ApiError(502, _unavailable)
        data = json.loads(raw)
    except HTTPError as error:
        error.close()
        if error.code in (401, 403, 404):
            raise ApiError(404, _private) from None
        raise ApiError(502, _unavailable) from None
    except (ApiError, URLError, OSError, http.client.HTTPException, ValueError, RecursionError):
        raise ApiError(502, _unavailable) from None
    finally:
        watch.stop()
        _slots.release()
    if not isinstance(data, dict):
        raise ApiError(502, _unavailable)
    return data


def _category(tags, notes):
    first = None
    for value in tags:
        try:
            tag = decks.clean_category(value)
        except ValueError:
            notes.add("Some source categories use names Deck Lab can't keep.")
            continue
        if tag and not first:
            first = tag
        elif tag and tag != first:
            notes.add("When a card has several categories, its first supported category is kept.")
            break
    return first


def _line(name, qty, set_code, number, finish, category, notes):
    if not isinstance(name, str) or not 1 <= len(name) <= 160 or _control.search(name) or "#" in name:
        return None
    if type(qty) is not int or not 1 <= qty <= MAX_QTY:
        return None
    if not isinstance(set_code, str) or not _set.fullmatch(set_code):
        set_code = None
    if not set_code or not isinstance(number, str) or _control.search(number) or not _number.fullmatch(number):
        number = None
    marker = "".join(ch for ch in str(finish).lower() if ch.isascii() and ch.isalpha())
    finish = {"foil": "foil", "etched": "etched", "etchedfoil": "etched", "foiletched": "etched"}.get(marker, "nonfoil")
    try:
        return decks.format_line(decks.DeckLine(qty, name, set_code, number, finish, category))
    except ValueError:
        notes.add("Some source rows couldn't be represented as decklist text.")
        return None


def _entries(value, container):
    if not isinstance(value, container) or len(value) > MAX_ROWS:
        raise ApiError(502, _unavailable)
    return value


def _moxfield(data, notes):
    if "visibility" not in data:
        raise ApiError(502, _unavailable)
    if data["visibility"] != "public":
        raise ApiError(404, _private)
    boards = _entries(data.get("boards"), dict)
    author_tags = data.get("authorTags")
    author_tags = author_tags if isinstance(author_tags, dict) else {}
    for board, definition in boards.items():
        if not isinstance(definition, dict):
            continue
        raw = definition.get("cards")
        if not raw:
            continue
        section = _boards.get(board)
        if not section:
            notes.add("Extra boards such as tokens and maybeboard are left out.")
            continue
        for key, row in _entries(raw, dict).items():
            if not isinstance(row, dict) or not isinstance(row.get("card"), dict):
                yield section, None
                continue
            card = row["card"]
            category = _category(_moxfield_tags(author_tags, key, row), notes)
            parts = row.get("printingData")
            if not parts:
                parts = [{**card, "quantity": row.get("quantity"), "finish": row.get("finish"),
                          "isFoil": row.get("isFoil")}]
            for part in _entries(parts, list):
                if not isinstance(part, dict):
                    yield section, None
                    continue
                finish = part.get("finish") or ("foil" if part.get("isFoil") else "nonfoil")
                yield section, _line(card.get("name"), part.get("quantity"), part.get("set"), part.get("cn"),
                                     finish, category, notes)


def _moxfield_tags(author_tags, key, row):
    """Moxfield groups tags by card identity; use any inline tag list first."""
    tags = row.get("tags")
    if isinstance(tags, list):
        return tags
    for ident in (key, row["card"].get("uniqueCardId"), row["card"].get("id"), row["card"].get("scryfall_id")):
        tags = author_tags.get(ident) if isinstance(ident, str) else None
        if isinstance(tags, list):
            return tags
    return []


def _archidekt(data, notes):
    if "private" not in data or "unlisted" not in data:
        raise ApiError(502, _unavailable)
    if data["private"] is not False or data["unlisted"] is not False:
        raise ApiError(404, _private)
    categories = {row["name"]: row for row in _entries(data.get("categories"), list) if isinstance(row, dict)
                  and isinstance(row.get("name"), str)}
    for row in _entries(data.get("cards"), list):
        if not isinstance(row, dict) or not isinstance(row.get("card"), dict):
            yield "Deck", None
            continue
        tags = row.get("categories")
        tags = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
        primary = categories.get(tags[0], {}) if tags else {}
        # Command-zone and sideboard memberships identify a section even when
        # an ordinary category appears first. For other non-deck categories,
        # keep only rows whose main category is included in the deck.
        if row.get("companion") is True:
            section = "Companion"
        elif any(categories.get(tag, {}).get("isPremier") is True for tag in tags):
            section = "Commander"
        elif any(tag.lower() == "sideboard" for tag in tags):
            section = "Sideboard"
        elif primary.get("includedInDeck") is False:
            notes.add("Extra boards such as tokens and maybeboard are left out.")
            continue
        else:
            section = "Deck"
        labels = [tag for tag in tags if tag.lower() not in {"commander", "companion", "sideboard", "maybeboard"}
                  and not categories.get(tag, {}).get("isPremier")
                  and categories.get(tag, {}).get("includedInDeck") is not False]
        card = row["card"]
        oracle, edition = card.get("oracleCard"), card.get("edition")
        name = oracle.get("name") if isinstance(oracle, dict) else None
        set_code = edition.get("editioncode") if isinstance(edition, dict) else None
        yield section, _line(name, row.get("quantity"), set_code, card.get("collectorNumber"),
                             row.get("modifier"), _category(labels, notes), notes)


def fetch(link):
    """Return plain decklist text and notes, discarding other provider data."""
    provider, endpoint = _source(link)
    data = _download(endpoint)
    notes = set()
    rows = _moxfield(data, notes) if provider == "Moxfield" else _archidekt(data, notes)
    sections = {}
    skipped = 0
    for count, (section, line) in enumerate(rows, 1):
        if count > MAX_ROWS:
            raise ApiError(413, "That deck has too many rows to import from a link.")
        if line is None:
            skipped += 1
        else:
            sections.setdefault(section, []).append(line)
    if not sections:
        raise ApiError(422, "That deck didn't contain any readable cards. Try a text export.")
    if skipped:
        notes.add(f"Deck Lab couldn't read {skipped} source card row(s).")
    groups = ["\n".join([section, *sections[section]]) for section in decks.SECTIONS if section in sections]
    return "\n\n".join(groups) + "\n", sorted(notes)
