"""Choosing a sweep: a balanced, repeatable sample of a gauntlet catalogue (design section 5).

From code:

    from decklab.lib.gauntlet import sample
    chosen = sample.choose(catalogue["decks"], 20, tiers=["core"], seed="")
    sid = sample.sample_id(catalogue["sha"], filters, 20, "")
    sample.save_sample("commander", drawn); sample.load_sample(drawn["id"])   # drawn: forge/gauntlet.draw's
    sample.standard_sample(catalogue, "commander")      # the standard sample (STANDARD), not saved
    sample.every(catalogue["decks"], tiers=["core"])    # "All": every playable deck of the filters
    sample.same_commander(catalogue["decks"], ["Ghalta, Primal Hunger"])   # E3-S49: every deck of a commander

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
"All" (every(), E3-S38) is no sample: every playable deck the filters allow, near-duplicates
included (a commander's core and upgraded decks are both played), most popular first. Its id
says so (sample_id's every), so it never shares an id with a balanced sample of the same size.
"Same commander" (same_commander(), E3-S49) is no sample either: every playable Commander deck whose
commanders are the house deck's (a partner pair in either order; commander_key), core, upgraded and
precon alike, most popular first, with no tier, colour, style or size filter. Its id hashes the
commander key (sample_id's commander), so it never shares an id with a balanced or All sample, and
the saved sample keeps the commanders' names ("commander"). These decks are sparring partners for a
head-to-head, never advice on what to play.
Ties go to popularity (EDHREC rank, then deck count, then tier: for Forge's decks the duels by
difficulty, then the precons), then to sha256(seed + id).

A saved sample is decklab/data/gauntlet/samples/sample-<12 hex>.json (the id's colon can't be
in a Windows file name): {"id", "format", "catalogue_sha", "filters": {"colours", "styles",
"tiers"}, "size", "seed", "decks": [ids]} (and "commander": [names] for a same-commander one), so the page and the command line play the same set.
"""
import hashlib
import json
import os
import re
import tempfile

from decklab.lib import gauntlet
from decklab.lib.gauntlet.tags import STYLES, WUBRG

DEFAULT_SIZE = {"commander": 20, "constructed": 24}
# The standard sample (E3-S33, Matt 2026-11-03): every deck's headline figure is against this one, so
# figures compare across decks and before and after an edit. It's the default draw: DEFAULT_SIZE,
# these tiers (forge/gauntlet's DEFAULT_TIERS), no colour or style filter, seed "".
STANDARD = {"commander": {"size": 20, "tiers": ("core", "upgraded")},
            "constructed": {"size": 24, "tiers": ("hard", "medium")}}
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


def every(decks, colours=None, styles=None, tiers=None, seed=""):
    """"All": every playable deck that passes the filters, near-duplicates included, most popular
    first."""
    return sorted(candidates(decks, colours, styles, tiers), key=lambda d: popularity(d, seed))


def _front(name):
    """A card name's front face, folded for matching ("Esika, God of the Tree // The Prismatic Bridge"
    and "Esika, God of the Tree" are one commander)."""
    return str(name).split(" // ", 1)[0].strip().casefold()


def commander_key(names):
    """The commanders as one key: their front faces folded and sorted, joined by "|" (a partner pair
    in either order is one key); "" for none."""
    return "|".join(sorted(_front(n) for n in names or () if str(n).strip()))


def commanders_of(deck):
    """A catalogue deck's (or a Forge entry's) commander names, from its "cards" Commander section."""
    return [str(n) for _, n in ((deck.get("cards") or {}).get("Commander") or ())]


def is_own_sample(found, commanders):
    """False when found, a saved sample, is a Same commander one (its "commander") of commanders other
    than commanders, the asking deck's (by commander_key); True for any other sample."""
    named = found.get("commander") if isinstance(found, dict) else None
    return not named or commander_key(named) == commander_key(commanders)


def same_commander(decks, commanders, seed=""):
    """"Same commander" (E3-S49): every playable Commander deck whose commanders are commanders (by
    commander_key), whatever its tier, most popular first; [] when commanders is empty or no deck has
    them."""
    key = commander_key(commanders)
    if not key:
        return []
    found = [d for d in candidates(decks) if d.get("kind") == "commander" and commander_key(commanders_of(d)) == key]
    return sorted(found, key=lambda d: popularity(d, seed))


def standard_sample(catalogue, fmt):
    """The format's standard sample of a catalogue (STANDARD), as forge/gauntlet.draw makes it:
    {"id", "format", "catalogue_sha", "filters", "size", "seed": "", "decks": [ids]}. Not saved
    (a sample is saved only when it's played)."""
    if fmt not in STANDARD:
        raise ValueError(f"Unknown gauntlet format {fmt!r}")
    size = STANDARD[fmt]["size"]
    filters = normalise_filters(tiers=STANDARD[fmt]["tiers"])
    chosen = choose((catalogue or {}).get("decks") or [], size, seed="", **filters)
    return {"id": sample_id((catalogue or {}).get("sha"), filters, size, ""), "format": fmt,
            "catalogue_sha": (catalogue or {}).get("sha"), "filters": filters, "size": size, "seed": "",
            "decks": [d["id"] for d in chosen]}


def sample_id(catalogue_sha, filters, size, seed, every=False, commander=None):
    """"sample:<12 hex>", a sha256 of the catalogue's version, the filters, the size and the seed
    (and, for "All", every: True; for "Same commander", commander: its commander_key; a balanced
    sample's id is as it always was)."""
    if not isinstance(filters, dict):
        filters = {}
    normal = normalise_filters(filters.get("colours"), filters.get("styles"), filters.get("tiers"))
    named = {"catalogue_sha": catalogue_sha, "filters": normal, "size": int(size), "seed": str(seed)}
    if every:
        named["every"] = True
    if commander:
        named["commander"] = str(commander)
    text = json.dumps(named, sort_keys=True, separators=(",", ":"))
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
