"""Stock Commander precon opponents from the Forge-screened gauntlet catalogue."""
from copy import deepcopy
import re
import threading

from decklab.lib import precons

from . import catalogue

LINEUP = "published-precons"
TITLE = "Bracket 2 precons"
BRACKET = 2
OPPONENTS = 3
_PRECON_ID = re.compile(r"gauntlet:precon/([A-Za-z0-9_-]{1,120})\Z")
_SOURCES = {"mtgjson": "MTGJSON", "forge": "Forge bundled precon"}
_cache_lock = threading.Lock()
_cache = None


def _source(deck_id, kind):
    """Construct public provenance from a checked id, without exposing local paths."""
    match = _PRECON_ID.fullmatch(deck_id) if isinstance(deck_id, str) else None
    if not match or kind not in _SOURCES:
        return None
    stem = match[1]
    if kind == "mtgjson" and not precons.FILE_RE.fullmatch(stem):
        return None
    return {"source_name": _SOURCES[kind], "source_url": precons.DECK_URL.format(stem) if kind == "mtgjson" else None}


def public_source(side):
    kind = side.get("precon_source")
    return _source(side.get("id"), kind) if isinstance(kind, str) else None


def is_lineup(sides):
    return (len(sides) == 1 + OPPONENTS and all(isinstance(side, dict) for side in sides)
            and not public_source(sides[0]) and all(public_source(side) for side in sides[1:]))


def _candidate(deck):
    if (not isinstance(deck, dict) or deck.get("kind") != "commander" or deck.get("tier") != "precon"
            or deck.get("playable") is not True or deck.get("ai_excluded") or deck.get("fixes")):
        return None
    bracket = deck.get("bracket")
    if not isinstance(bracket, dict) or type(bracket.get("minimum")) is not int or not 1 <= bracket["minimum"] <= BRACKET:
        return None
    source = deck.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("kind"), str):
        return None
    deck_id, title, kind = deck.get("id"), deck.get("title"), source["kind"]
    if not isinstance(title, str) or not title or not _source(deck_id, kind):
        return None
    return deck


def _rank(deck):
    rank = deck["source"].get("rank")
    return (rank if type(rank) is int and rank > 0 else float("inf"), deck["id"])


def _pick(decks):
    from decklab.lib.forge.lists import ForgeError, entry_from_cards

    candidates = sorted(filter(None, (_candidate(deck) for deck in decks)), key=_rank)
    choices, fallback, ids, hashes, colours = [], [], set(), set(), set()
    for deck in candidates:
        try:
            entry = entry_from_cards(deck["id"], deck["title"], "commander", deck.get("cards"))
        except (ForgeError, AttributeError, ValueError, TypeError):
            continue
        if (entry["card_count"] != 100 or not entry["cards"]["Commander"]
                or entry["id"] in ids or entry["card_sha"] in hashes):
            continue
        entry.update(precon_source=deck["source"]["kind"], target_bracket=BRACKET)
        identity = deck["identity"] if isinstance(deck.get("identity"), str) else ""
        ids.add(entry["id"])
        hashes.add(entry["card_sha"])
        if identity not in colours:
            choices.append(entry)
            colours.add(identity)
        else:
            fallback.append(entry)
        if len(choices) == OPPONENTS:
            break
    chosen = (choices + fallback)[:OPPONENTS]
    return chosen if len(chosen) == OPPONENTS else []


def entries():
    """Choose three unchanged stock lists for the current file, preferring different colour identities."""
    global _cache
    path = catalogue.catalogue_path("commander")
    with _cache_lock:
        try:
            stat = path.stat()
        except OSError:
            _cache = None
            return []
        # The builder replaces the file atomically. Include inode so an equally sized
        # replacement with the same mtime invalidates the cached lineup on the next read.
        stamp = (path, stat.st_ino, stat.st_ctime_ns, stat.st_mtime_ns, stat.st_size)
        if _cache is None or _cache[0] != stamp:
            found = catalogue.load("commander")
            if found is None:
                _cache = None
                return []
            _cache = (stamp, _pick(found["decks"]))
        return deepcopy(_cache[1])
