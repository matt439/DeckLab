"""Deck lists for Forge: a list's .dck text and card_sha, entries (a list ready to play,
with where it came from: a deck's saved revision, a product, or a .dck file), matchup keys,
the batches a run of cold processes is split into (plan), and the game numbers a v2 run plays
in the warm pool (plan_v2)."""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from decklab.lib import config, decks, gitops

from . import common
from .common import AI_PROFILES, FORGE_RUN_VERSION, GAME_CHOICES, MIXED_KINDS, ForgeError, forge_name
from .install import forge_version

SEED_BASE = 1
SMALL_BATCH = 25                # the fewest games plan() gives a batch (of a run of 50 or more)
FORMATS = {"commander": "Commander", "constructed": "Constructed"}
SOURCE_TTL = 10                 # seconds a .dck file's git state is reused
SOURCE_CACHE_MAX = 500          # .dck file versions whose git state is kept (then all forgotten)


# ============================================================ deck lists

def fmt_for(kind):
    """Forge's -f for a list's kind: "Commander" for commander, else "Constructed"."""
    return FORMATS["commander"] if kind == "commander" else FORMATS["constructed"]


def _merge_lines(pairs, keep_order):
    """[(qty, forge name)] with repeated names added up; sorted by name unless keep_order."""
    merged = {}
    for qty, name in pairs:
        merged[name] = merged.get(name, 0) + qty
    names = list(merged) if keep_order else sorted(merged, key=lambda n: (n.casefold(), n))
    return [(merged[n], n) for n in names]


def _list_text(cards_by_section, kind, keep_order=False):
    """(card text, card_sha, card count) for {"Commander": [[qty, name]], "Main": [...]}.
    A Constructed list plays its Commander section's cards in the Main deck."""
    commander = [(q, forge_name(n)) for q, n in cards_by_section.get("Commander", [])]
    main = [(q, forge_name(n)) for q, n in cards_by_section.get("Main", [])]
    if kind != "commander":
        main, commander = commander + main, []
    commander, main = _merge_lines(commander, keep_order), _merge_lines(main, keep_order)
    lines = []
    if commander:
        lines += ["[Commander]"] + [f"{q} {n}" for q, n in commander]
    lines += ["[Main]"] + [f"{q} {n}" for q, n in main]
    text = "\n".join(lines) + "\n"
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest(), sum(q for q, _ in commander + main)


def _dck(card_text, card_sha):
    return f"[metadata]\nName={card_sha[:12]}\n{card_text}"


def _section_cards(sections):
    """{"Commander": [[qty, name]], "Main": [[qty, name]]} from decks.load_deck's sections
    (the sideboard and companions aren't played)."""
    return {"Commander": [[l.quantity, l.name] for l in sections.get("Commander", [])],
            "Main": [[l.quantity, l.name] for l in sections.get("Deck", [])]}


_sources = {}
_sources_lock = threading.Lock()


def _product_source(deck_id):
    """{"product": stem, "revision": the inventory's revision} for a product deck or a Beginner
    Box pairing (whose lists are the inventory's products: decklab/lib/inventory), or None when
    there's no such product, or the snapshot is a preview's (never saved, so nothing may name its
    revision)."""
    from decklab.lib import inventory
    stem = deck_id.split("/")[1] if deck_id.startswith("product/") else decks.BEGINNER_BOX
    try:
        inv = inventory.current()
    except (inventory.StateError, OSError, ValueError, RuntimeError):
        return None
    if not inv.persisted or inv.product(stem) is None:
        return None
    return {"product": stem, "revision": inv.revision}


def one_snapshot():
    """A block reading one inventory snapshot: the request's or command's when one is pinned,
    else one pinned for the block. Wrap loading a deck's list and its entry() in it, so a
    product's list and the revision its source names come from the same snapshot (and a
    background thread loads the inventory once, not once per call)."""
    import contextlib
    from decklab.lib import inventory
    return contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned()


_UNSAVED = object()     # _deck_source's answer for a preview's snapshot


def _deck_source(deck_id):
    """{"deck": id, "revision": n} for a deck whose text in the inventory's snapshot is its
    saved revision n (the database's Deck.revision: decklab/lib/inventory); _UNSAVED for a
    preview's snapshot, which is never saved, so nothing may name a revision of it; else None
    (no such deck, or the files backend, which keeps no revisions: Deck.revision 0)."""
    from decklab.lib import inventory
    try:
        inv = inventory.current()
    except (inventory.StateError, OSError, ValueError, RuntimeError):
        return None
    if not inv.persisted or inv.decks_revision.endswith(inventory.PREVIEW):
        return _UNSAVED
    deck = inv.deck(deck_id)
    if deck is None or not deck.revision:
        return None
    return {"deck": deck.id, "revision": deck.revision}


def _source(deck_id, path=None):
    """Where a list comes from (the phase 4 design's D6). For a deck id: {"deck", "revision"}
    when the snapshot names the deck's saved revision (_deck_source), {"product", "revision"}
    for a product deck or a pairing (_product_source), else None (no such deck, the files
    backend, or a preview's snapshot); git is never asked about a deck id. For a .dck file's
    path (entry_from_dck): {"file", "commit", "dirty"}, what git says about that repo file, or
    None when git can't say; kept for SOURCE_TTL seconds per file version. Load a deck's list
    and call this in one snapshot (one_snapshot()), so the list and the revision its source
    names are the same."""
    if path is None:
        if not isinstance(deck_id, str):
            return None
        if deck_id.startswith(("product/", "pairing/")):
            return _product_source(deck_id)
        found = _deck_source(deck_id)
        return None if found is _UNSAVED else found
    try:
        path = Path(path)
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with _sources_lock:
            cached = _sources.get(key)
        if cached and time.monotonic() - cached[0] < SOURCE_TTL:
            return dict(cached[1])
        rel = gitops.relative(path)
        done = gitops.run(["log", "-1", "--format=%H", "--", rel], check=False)
        commit = done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None
        source = {"file": rel, "commit": commit, "dirty": bool(gitops.status([rel]))}
    except (gitops.GitError, OSError, ValueError):
        return None
    with _sources_lock:
        if len(_sources) > SOURCE_CACHE_MAX:
            _sources.clear()
        _sources[key] = (time.monotonic(), source)
    return dict(source)


def entry(deck_id, version, title, kind, sections):
    """A deck list ready to play: {"id", "version", "title", "kind" ("commander" or
    "constructed"), "card_sha", "card_count", "dck" (the .dck text), "cards" (the
    Scryfall names played, {"Commander": [[qty, name]], "Main": [...]}), "source"
    (_source's: {"deck", "revision"}, {"product", "revision"} or None), "pilot" (wave 3: the AI pilot it plays with,
    pilots.pilot_for's {"profile", "switches"})}. sections as decks.load_deck returns them."""
    from . import pilots            # pilots.py comes after this part
    listed = _section_cards(sections)
    text, card_sha, count = _list_text(listed, kind)
    return {"id": deck_id, "version": version, "title": title, "kind": kind, "card_sha": card_sha,
            "card_count": count, "dck": _dck(text, card_sha), "cards": listed,
            "source": _source(deck_id), "pilot": pilots.pilot_for(deck_id, version)}


def card_sha(sections, kind):
    """The card_sha entry() gives a list, without the rest (no git: cheap enough for
    every list of a page)."""
    return _list_text(_section_cards(sections), kind)[1]


def entry_from_dck(path):
    """A list from a .dck file (the trial's decks), played as the file has it: its
    [Commander] and [Main] lines in their own order. Commander decks have a [Commander].
    Its pilot is the default one (pilots.default_pilot: a file isn't a list of simulation.json)."""
    from . import pilots            # pilots.py comes after this part
    path = Path(path)
    listed, section, title = {"Commander": [], "Main": []}, None, path.stem
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = {"[commander]": "Commander", "[main]": "Main"}.get(line.lower())
            continue
        if line.startswith("Name=") and section is None:
            title = line[5:].strip() or title
            continue
        m = re.match(r"^(\d+)\s+(.+?)\s*$", line)
        if section and m:
            listed[section].append([int(m[1]), m[2].split("|", 1)[0].strip()])
    kind = "commander" if listed["Commander"] else "constructed"
    text, card_sha, count = _list_text(listed, kind, keep_order=True)
    try:
        rel = path.resolve().relative_to(config.REPO).as_posix()
    except ValueError:
        rel = path.name
    return {"id": f"file:{rel}", "version": "target", "title": title, "kind": kind, "card_sha": card_sha,
            "card_count": count, "dck": _dck(text, card_sha), "cards": listed,
            "source": _source(None, path) if rel != path.name else None, "pilot": pilots.default_pilot()}


def matchup_key(entry_a, entry_b):
    """The matchup's key (64 hex): the same for (a, b) and (b, a). Raises ForgeError when
    one list is a Commander deck and the other isn't. It's the key of the engine a run
    would play now (engine.matchup_key: Forge's version is forge_version(), the one run()
    plays with); it doesn't need Java, or Forge's folder once a version has been found."""
    if entry_a["kind"] != entry_b["kind"]:
        raise ForgeError(MIXED_KINDS)
    from . import engine        # engine.py comes after this part
    return engine.matchup_key(entry_a, entry_b)


V1_RUN_VERSION = 1      # the run_version results were saved with before wave 2


def _key(entry_a, entry_b, version, clock_s):
    """The key before wave 2: run_version 1's (V1_RUN_VERSION, whatever FORGE_RUN_VERSION is
    now), which engine.key gives in the base commit. v1 results keep their keys; nothing
    finds them by it once wave 2's engine id is the key (lists and pages read every saved
    result)."""
    payload = json.dumps([sorted([entry_a["card_sha"], entry_b["card_sha"]]), fmt_for(entry_a["kind"]),
                          V1_RUN_VERSION, version, int(clock_s), list(AI_PROFILES)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _list_lines(side):
    """[(qty, .dck name)] of a side's [Commander] and [Main], from its .dck text."""
    out = []
    for line in side["dck"].splitlines():
        m = re.match(r"^(\d+) (.+)$", line)
        if m:
            out.append((int(m[1]), m[2]))
    return out


# ============================================================ batches

def plan(games, existing_result=None, workers=None, *, batch=None, seed_base=None):
    """The batches for a run of games: [{"n", "seed", "games", "deck1"}], n and seed
    going on from existing_result's (failed batches included), deck1 the side that plays
    as Forge's deck 1 (0 when n is even). The run is split as _batch_count says, among
    workers Forge processes (None: config.json's forge_workers). Raises ValueError for
    games not in GAME_CHOICES, or workers under 1. batch fixes the batch size (then games
    may be any multiple of it), and seed_base the first seed of a result that has no
    batches yet (replaying the trial)."""
    settings = common._settings()
    workers = int(workers) if workers is not None else int(settings["forge_workers"])
    size = _batch_size(games, workers, batch)
    # Partial batches (a stopped run's) count too: their seeds aren't used again.
    past = (existing_result or {}).get("batches", []) + (existing_result or {}).get("failed", [])
    first_n = max((b["n"] for b in past), default=-1) + 1
    if past:
        first_seed = max(b["seed"] for b in past) + 1
    else:
        first_seed = SEED_BASE if seed_base is None else seed_base
    return [{"n": first_n + i, "seed": first_seed + i, "games": size, "deck1": (first_n + i) % 2}
            for i in range(games // size)]


def plan_v2(games, existing_result=None, *, batch=None, exact=False):
    """The game numbers a v2 run (the decklab engine: per-game seeds, played in the warm
    pool) plays: {"first": the result's next_game (0 for a new result), "end": first +
    games, "ranges": [[start, end], ...] the range cut at every seat block (seeds.SEAT_BLOCK
    games: a chunk never spans two, wave 2's contract "Chunk policy")}. The pool cuts chunks
    of these as workers come free. ValueError as _batch_size for games that don't suit:
    without batch, games must be one of GAME_CHOICES, with it a whole number of batches
    (batch then caps a chunk's games); exact (the replay command's "the games missing")
    takes any number of games of 1 or more."""
    from . import seeds          # seeds.py imports nothing of Deck Lab's: any part may use it
    if exact:
        if not isinstance(games, int) or games < 1:
            raise ValueError("games must be a whole number of 1 or more")
    else:
        _batch_size(games, 1, batch)
    first = int((existing_result or {}).get("next_game") or 0)
    end = first + games
    ranges, start = [], first
    while start < end:
        stop = min(end, seeds.block_end(start))
        ranges.append([start, stop])
        start = stop
    return {"first": first, "end": end, "ranges": ranges}


def _batch_size(games, workers, batch):
    """Games per batch (see plan()); ValueError for games that can't be split, or no workers."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if batch is None:
        if games not in GAME_CHOICES:
            raise ValueError(f"games must be one of {', '.join(map(str, GAME_CHOICES))}")
        return games // _batch_count(games, workers)
    if batch < 1 or games < 1 or games % batch:
        raise ValueError("games must be a whole number of batches")
    return batch


def _batch_count(games, workers):
    """How many batches a run of games is split into: the largest even number, at least 2
    and at most min(workers, games // SMALL_BATCH), that divides games.

    Each batch is one Forge process, so this starts as many as can each play at least
    SMALL_BATCH games, all at once (no second wave of cold starts), and an even number
    of them, so each side is Forge's deck 1 in half the batches. With 16 workers:
    200 games are 8 x 25, 400 are 16 x 25, 800 16 x 50, 1,600 16 x 100 and 3,200
    16 x 200; with 8, 3,200 are 8 x 400; with 12, 400 are 10 x 40.

    With 1 worker, or a run under 2 x SMALL_BATCH games, it's still 2 (played one after
    the other with 1 worker); a run that 2 doesn't divide is 1 batch. workers is 1 or
    more and games 1 or more (_batch_size checks)."""
    cap = max(2, min(workers, games // SMALL_BATCH))
    for count in range(cap - cap % 2, 1, -2):
        if games % count == 0:
            return count
    return 1
