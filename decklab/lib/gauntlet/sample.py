"""Choosing a sweep: a balanced, repeatable sample of a gauntlet catalogue (design section 5).

From code:

    from decklab.lib.gauntlet import sample
    chosen = sample.choose(catalogue["decks"], 20, tiers=["core"], seed="")
    sid = sample.sample_id(catalogue["sha"], filters, 20, "")
    sample.save_sample("commander", drawn); sample.load_sample(drawn["id"])   # drawn: forge/gauntlet.draw's

(lib/forge/gauntlet.draw chooses, names and saves a sample with the format's defaults.)

The choice is deterministic: the same decks, filters, size and seed always give the same
sample, in the same order.
1. Filter: playable decks only, then tier, colours (the identity within the filter's colours;
   colourless decks always fit) and primary style. Then one deck of each family, the most
   popular (so the version nearest the requested tiers): a Commander deck's commanders (an
   EDHREC core deck re-tiered to upgraded and the same commander's upgraded deck are one), a
   Forge duel's Title (its difficulty versions are one).
2. Colour pass: walk BUCKETS in order (each colour, the ten pairs, the five shards, the five
   wedges, four or five colours, colourless) and take one deck from each, the one adding a
   primary style the sample hasn't got yet.
3. Style pass: bring every style to at least STYLE_FLOOR decks where the candidates allow.
4. Fill to the size by popularity.
Ties go to popularity (EDHREC rank, then deck count, then tier: for Forge's decks the duels by
difficulty, then the precons), then to sha256(seed + id).

A saved sample is decklab/data/gauntlet/samples/sample-<12 hex>.json (the id's colon can't be
in a Windows file name): {"id", "format", "catalogue_sha", "filters": {"colours", "styles",
"tiers"}, "size", "seed", "decks": [ids]}, so the page and the command line play the same set.
"""
import hashlib
import json
import os
import re
import tempfile

from decklab.lib import gauntlet
from decklab.lib.gauntlet.tags import STYLES, WUBRG

DEFAULT_SIZE = {"commander": 20, "constructed": 24}
STYLE_FLOOR = 2

PAIRS = ("WU", "UB", "BR", "RG", "WG", "WB", "UR", "BG", "WR", "UG")
SHARDS = ("WUG", "WUB", "UBR", "BRG", "WRG")       # Bant, Esper, Grixis, Jund, Naya
WEDGES = ("WBG", "WUR", "UBG", "WBR", "URG")       # Abzan, Jeskai, Sultai, Mardu, Temur
FOUR_PLUS = "4+"
BUCKETS = tuple(WUBRG) + PAIRS + SHARDS + WEDGES + (FOUR_PLUS, "")

# The order popularity falls back on when a deck has no rank or deck count: the first is the
# most popular. For Forge's 60-card decks, the duels by difficulty, then the precons.
TIER_ORDER = ("core", "upgraded", "medium", "hard", "very hard", "easy", "precon")

_SAMPLE_ID = re.compile(r"sample:([0-9a-f]{12})")


def _ordered(letters):
    return "".join(c for c in WUBRG if c in (letters or ""))


def bucket(identity):
    """The colour bucket of an identity: itself in WUBRG order, FOUR_PLUS for four or five
    colours, "" for colourless."""
    letters = _ordered(identity)
    return FOUR_PLUS if len(letters) >= 4 else letters


def normalise_filters(colours=None, styles=None, tiers=None):
    """The filters as a sample saves them: colours in WUBRG order, styles and tiers sorted,
    each None when not given."""
    return {"colours": None if colours is None else _ordered(str(colours).upper()),
            "styles": None if styles is None else sorted(set(styles)),
            "tiers": None if tiers is None else sorted(set(tiers))}


def _tiebreak(seed, deck_id):
    return hashlib.sha256((seed + deck_id).encode("utf-8")).hexdigest()


def popularity(deck, seed=""):
    """A sort key, most popular first: EDHREC rank (lowest), deck count (most), TIER_ORDER, then
    sha256(seed + id)."""
    source = deck.get("source") or {}
    rank, count = source.get("rank"), source.get("decks")
    tier = deck.get("tier")
    return (rank if isinstance(rank, int) and not isinstance(rank, bool) else float("inf"),
            -count if isinstance(count, int) and not isinstance(count, bool) else 0,
            TIER_ORDER.index(tier) if tier in TIER_ORDER else len(TIER_ORDER),
            _tiebreak(seed, deck["id"]))


def _primary(deck):
    return (deck.get("style") or {}).get("primary")


def candidates(decks, colours=None, styles=None, tiers=None):
    """The decks a sample may choose from: playable ones that pass every filter given."""
    allowed = None if colours is None else set(_ordered(str(colours).upper()))
    out = []
    for deck in decks:
        if deck.get("playable") is not True:
            continue
        if tiers is not None and deck.get("tier") not in tiers:
            continue
        if allowed is not None and not set(_ordered(deck.get("identity"))) <= allowed:
            continue
        if styles is not None and _primary(deck) not in styles:
            continue
        out.append(deck)
    return out


def family(deck):
    """What makes decks near-duplicates: a Commander deck's commanders, a Forge duel's Title, else
    the deck's own id."""
    if deck.get("duel_title"):
        return "title:" + str(deck["duel_title"]).casefold()
    commanders = sorted(str(n) for _, n in ((deck.get("cards") or {}).get("Commander") or ()))
    if deck.get("kind") == "commander" and commanders:
        return "commander:" + "|".join(commanders)
    return "id:" + str(deck.get("id"))


def _one_per_family(pool):
    """pool (most popular first) with only the first deck of each family."""
    seen, out = set(), []
    for deck in pool:
        key = family(deck)
        if key not in seen:
            seen.add(key)
            out.append(deck)
    return out


def choose(decks, size, colours=None, styles=None, tiers=None, seed=""):
    """The sample: at most size decks of the candidates, chosen as the module docstring says."""
    pool = _one_per_family(sorted(candidates(decks, colours, styles, tiers), key=lambda d: popularity(d, seed)))
    chosen, taken = [], set()

    def take(deck):
        chosen.append(deck)
        taken.add(deck["id"])

    for key in BUCKETS:
        if len(chosen) >= size:
            break
        have = {_primary(d) for d in chosen}
        here = [d for d in pool if d["id"] not in taken and bucket(d.get("identity")) == key]
        if here:
            take(min(here, key=lambda d: (_primary(d) in have, popularity(d, seed))))
    for style in STYLES:
        while len(chosen) < size and sum(_primary(d) == style for d in chosen) < STYLE_FLOOR:
            more = next((d for d in pool if d["id"] not in taken and _primary(d) == style), None)
            if more is None:
                break
            take(more)
    for deck in pool:
        if len(chosen) >= size:
            break
        if deck["id"] not in taken:
            take(deck)
    return chosen


def sample_id(catalogue_sha, filters, size, seed):
    """"sample:<12 hex>", a sha256 of the catalogue's version, the filters, the size and the seed."""
    if not isinstance(filters, dict):
        filters = {}
    normal = normalise_filters(filters.get("colours"), filters.get("styles"), filters.get("tiers"))
    text = json.dumps({"catalogue_sha": catalogue_sha, "filters": normal, "size": int(size),
                       "seed": str(seed)}, sort_keys=True, separators=(",", ":"))
    return "sample:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _path(sid):
    match = _SAMPLE_ID.fullmatch(sid) if isinstance(sid, str) else None
    if match is None:
        return None
    return gauntlet.DATA / "samples" / f"sample-{match.group(1)}.json"


def save_sample(fmt, sample):
    """Write a sample (forge/gauntlet.draw's shape) to its file, replacing the file whole. Returns the path."""
    if fmt not in gauntlet.FORMATS:
        raise ValueError(f"Unknown gauntlet format {fmt!r}")
    path = _path(sample.get("id"))
    if path is None:
        raise ValueError(f"Not a sample id: {sample.get('id')!r}")
    data = dict(sample, format=fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_sample(sid):
    """The saved sample with this id, or None when there's none (or it can't be read)."""
    path = _path(sid)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") != sid or not isinstance(data.get("decks"), list):
        return None
    return data
