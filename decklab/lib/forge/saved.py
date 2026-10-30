"""The saved results (data/forge/results/<key>.json): whether a file is a result
(_is_result), reading one through a cache, load(), every saved result with games in it
(_stored), what a result's batches add up to (_counted, _pooled, and the card log's
_pooled_cards, and its token peaks: _pooled_tokens) and a stored side's cards (_side_cards)."""
import json
import re
import threading
from copy import deepcopy

from .common import _results_dir
from .lists import _list_lines

READ_CACHE_MAX = 1000           # saved results kept read (then all forgotten); each is small
CARD_TALLIES = 10               # numbers per card in a batch's "cards" rows (cardlog.ROW_FIELDS' order)
SHARED_TALLIES = 8              # the first of them, which every record version keeps
ROW_SIZES = {1: SHARED_TALLIES, 2: SHARED_TALLIES, 3: CARD_TALLIES}    # record version -> numbers per card
COUNTED_VERSIONS = (2, 3)       # record versions whose tallies count (cardlog's docstring has each one)
OLD_VERSIONS = (1,)             # versions kept by an earlier card log that counted differently: "old"
EARLY_VERSION = 3               # the first version with early_games and early_wins
COMMANDER_TALLIES = 4           # numbers per commander in its "commander"
MAX_PER_GAME = 1000             # most copies of one card drawn, casts of it, or the round it's first
                                # cast in, in one game: real games are far below it, so a record
                                # whose tallies add up to more is malformed


# ============================================================ saved results

_read_cache = {}
_read_lock = threading.Lock()


GAME_KEYS = frozenset(("w", "r", "first", "rounds", "ms"))     # what view() reads of every game
# Wave 3's kinds of result besides a matchup's (no "kind"; forge-trial/sim-wave3-contract.md
# sections 8 and 14): a paired variant test's arm (in <results>/paired/) and an experiment's arm.
RESULT_KINDS = ("paired", "experiment")
KEY_RE = re.compile(r"[0-9a-f]{64}")


def _decklab(data):
    """Is data (a dict) a result of the v2 decklab engine (per-game seeds, the warm pool)?
    It has a "seeds" record, or says so (run_version 2 or more with an engine of kind
    "decklab"); a v1 result or a plain-Forge one has neither."""
    if "seeds" in data:
        return True
    eng, version = data.get("engine"), data.get("run_version")
    return (isinstance(version, int) and version >= 2 and isinstance(eng, dict)
            and eng.get("kind") == "decklab")


def _is_result(data, key):
    """Is data (any JSON) a stored result of this key, in the shape run() saves? A hand
    edit, another program's file or a future format isn't, and is left alone. A batch's
    "cards" (the card log's tallies, only in batches played with it) isn't looked at: one
    that's missing, malformed or of an older version only leaves that batch out of the
    per-card stats (_pooled_cards, which counts an older one's games as "old"), never the
    result.
    A v1 result, or a plain-Forge one, has batches and failed batches each with "n" and
    "seed"; a decklab one (_decklab; wave 2's contract "Saved result, v2") has one merged
    batch per run with "n" (the run's ordinal) and "first" (its lowest game number)
    instead, an int "g" of 0 or more in every game, failed records with "n" and "first",
    and a "seeds" record whose flip is 0 or 1, base an int of 0 or more and stream 16 hex
    digits (the next run plays on from them, and from next_game, an int of 0 or more).
    Wave 3 (sim-wave3-contract.md sections 8 and 14): a "kind" is "paired" (a decklab result
    with its "paired" block: base_key 64 hex digits, base_side and variant_side 0 or 1, and a
    "variant" dict) or "experiment" (an "experiment" block, when there is one, a dict); any
    other kind is a future format's. An "adaptive" list (the adaptive runs' summaries) holds
    dicts."""
    def dicts(items, length=None):
        return isinstance(items, list) and (length is None or len(items) == length) and \
            all(isinstance(item, dict) for item in items)

    def ints(item, *names):
        return all(isinstance(item.get(name), int) for name in names)

    def count(x):
        return type(x) is int and x >= 0

    if not (isinstance(data, dict) and data.get("key") == key and isinstance(data.get("format"), str)
            and isinstance(data.get("updated") or "", str)):
        return False
    sides, batches, failed = data.get("sides"), data.get("batches"), data.get("failed", [])
    if not (dicts(sides, 2) and dicts(batches) and dicts(failed) and dicts(data.get("runs"))):
        return False
    for side in sides:
        if not (isinstance(side.get("card_sha"), str) and isinstance(side.get("dck"), str)
                and isinstance(side.get("kind"), str) and ints(side, "card_count")
                and dicts(side.get("seen_as", [])) and isinstance(side.get("cards") or {}, dict)):
            return False
    decklab = _decklab(data)
    if not _kind_ok(data, decklab) or not dicts(data.get("adaptive", [])):
        return False
    numbered = ("n", "first") if decklab else ("n", "seed")
    if decklab:
        record = data.get("seeds")
        if not (isinstance(record, dict) and record.get("flip") in (0, 1) and type(record["flip"]) is int
                and count(record.get("base")) and isinstance(record.get("stream"), str)
                and re.fullmatch(r"[0-9a-f]{16}", record["stream"]) and count(data.get("next_game", 0))):
            return False
    for batch in batches:
        if not (ints(batch, *numbered) and dicts(batch.get("games"))
                and dicts(batch.get("casts"), 2) and dicts(batch.get("lands"), 2)):
            return False
        if not all(GAME_KEYS <= game.keys() for game in batch["games"]):
            return False
        if decklab and not all(count(game.get("g")) for game in batch["games"]):
            return False
    return all(ints(f, *numbered) for f in failed)


def _kind_ok(data, decklab):
    """Is data's "kind" (wave 3) one _is_result takes: none (a matchup), or one of RESULT_KINDS
    with its block (the docstring there)?"""
    if "kind" not in data:
        return True
    kind = data["kind"]
    if kind == "paired":
        block = data.get("paired")
        return (decklab and isinstance(block, dict) and isinstance(block.get("base_key"), str)
                and KEY_RE.fullmatch(block["base_key"]) is not None
                and all(type(block.get(side)) is int and block[side] in (0, 1) for side in ("base_side", "variant_side"))
                and isinstance(block.get("variant"), dict))
    if kind == "experiment":
        return isinstance(data.get("experiment", {}), dict)
    return False


def _read_result(path):
    """A saved result (shared: don't change it), or None when it can't be read or
    isn't one (_is_result)."""
    try:
        stat = path.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _read_lock:
        cached = _read_cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not _is_result(result, path.stem):
        result = None
    with _read_lock:
        if len(_read_cache) > READ_CACHE_MAX:
            _read_cache.clear()
        _read_cache[path] = (stamp, result)
    return result


def load(key, results_dir=None):
    """The stored result for a matchup key, or None."""
    if not re.fullmatch(r"[0-9a-f]{64}", key or ""):
        return None
    result = _read_result(_results_dir(results_dir) / f"{key}.json")
    return deepcopy(result) if result is not None else None


def _stored(results_dir):
    folder = _results_dir(results_dir)
    try:
        paths = list(folder.glob("*.json"))
    except OSError:
        return []
    out = [r for r in map(_read_result, paths) if r is not None and _counted(r)]
    return sorted(out, key=lambda r: r.get("updated") or "", reverse=True)


def _counted(result):
    return sum(len(b["games"]) for b in result.get("batches", []))


def _pooled(result, side, casts=None, lands=None):
    """(casts {card: [casts, games]}, lands {card: games}) of one side over every counted
    batch, added to casts and lands when they're given."""
    casts = {} if casts is None else casts
    lands = {} if lands is None else lands
    for b in result.get("batches", []):
        for card, (n, g) in b["casts"][side].items():
            total = casts.setdefault(card, [0, 0])
            total[0] += n
            total[1] += g
        for card, g in b["lands"][side].items():
            lands[card] = lands.get(card, 0) + g
    return casts, lands


def _side_cards(side):
    """A stored side's {"Commander": [[qty, name]], "Main": [...]} (from its .dck text
    when it has none)."""
    return side.get("cards") or {"Main": [[q, n] for q, n in _list_lines(side)]}


# ============================================================ the card log's tallies

def _count(x):
    """Is x a count: a whole number, 0 or more (not True or False)?"""
    return type(x) is int and x >= 0


def _pair(items, ok):
    """Is items a list of two things that pass ok?"""
    return isinstance(items, list) and len(items) == 2 and all(ok(item) for item in items)


def _row_fits(numbers, games, wins):
    """Do a card's tallies fit together as the card log counts them? Every game it was
    drawn in drew at least one copy (and at most MAX_PER_GAME); only drawn copies are
    cast, stuck or discarded (so no share of copies_drawn is over 1); each cast copy's
    round is at most MAX_PER_GAME, and so are its casts from anywhere but the hand in a
    game. With early_games and early_wins (version 3; games and wins are the record's,
    the side's wins): a game with a copy in hand by turn 3 is one it was drawn in, a win
    with one is such a game and a win it was drawn in, and the games without one hold the
    other wins (so neither early win rate is below 0 or above 1)."""
    drawn_games, drawn_wins, copies, used, stuck, round_sum, other_casts, discarded = numbers[:SHARED_TALLIES]
    if not (drawn_games <= copies <= drawn_games * MAX_PER_GAME and max(used, stuck, discarded) <= copies
            and round_sum <= used * MAX_PER_GAME and other_casts <= games * MAX_PER_GAME):
        return False
    if len(numbers) == SHARED_TALLIES:
        return True
    early_games, early_wins = numbers[SHARED_TALLIES:]
    return (early_games <= drawn_games and early_wins <= min(early_games, drawn_wins)
            and wins - early_wins <= games - early_games)


def _commander_fits(numbers):
    """Do a commander's tallies fit together: at least one cast (and at most
    MAX_PER_GAME) in each game it was cast in, and its first cast's round at most
    MAX_PER_GAME?"""
    cast_games, _, casts, round_sum = numbers
    return cast_games <= casts <= cast_games * MAX_PER_GAME and round_sum <= cast_games * MAX_PER_GAME


def _card_record(record, played, versions=COUNTED_VERSIONS):
    """Is a batch's "cards" record well formed: of one of versions (those counted today,
    COUNTED_VERSIONS, unless others are given), every number a count, both sides' rows
    (ROW_SIZES' numbers for its version) and commanders, its games (counted and bad) no
    more than the batch's played games, and no part of the games bigger than the games
    it's part of (so a win rate's games and wins, and those of the games without the card,
    are never below 0 or above their games)? Each card's and commander's own tallies must
    also fit together (_row_fits, _commander_fits), so a share is never over 1 and an
    average turn never too big for a float. A record without "commander" has none."""
    if not (isinstance(record, dict) and _count(record.get("v")) and record["v"] in versions):
        return False
    row_size = ROW_SIZES[record["v"]]
    games, bad, wins, first = record.get("games"), record.get("bad"), record.get("wins"), record.get("first")
    rows, commander = record.get("rows"), record.get("commander", [{}, {}])
    if not (_count(games) and _count(bad) and _pair(wins, _count) and _pair(first, _count)
            and _pair(rows, lambda r: isinstance(r, dict)) and _pair(commander, lambda c: isinstance(c, dict))):
        return False
    # Each game the batch played is counted (games) or not (bad) at most once.
    if games + bad > played or sum(wins) > games or sum(first) > games:
        return False
    for side in (0, 1):
        for tallies, size, row in ((rows[side], row_size, True), (commander[side], COMMANDER_TALLIES, False)):
            for name, numbers in tallies.items():
                if not (isinstance(name, str) and isinstance(numbers, list) and len(numbers) == size
                        and all(_count(n) for n in numbers)):
                    return False
                # The games the card was drawn (a commander cast) in, and the wins among them.
                in_games, in_wins = numbers[0], numbers[1]
                if in_games > games or in_wins > in_games or in_wins > wins[side] or \
                        wins[side] - in_wins > games - in_games:
                    return False
                if not (_row_fits(numbers, games, wins[side]) if row else _commander_fits(numbers)):
                    return False
    return True


def _older_record(record, played):
    """Is a batch's "cards" record one an earlier card log kept: of one of OLD_VERSIONS,
    and well formed for it (_card_record)? Version 1 (before 2026-10-01) counted a cast
    Forge's AI started and couldn't finish as a cast, so such a record's tallies aren't
    today's and aren't counted, but its games were still played with a card log (not
    without one). A version 2 record isn't older in this sense: its 8 numbers are counted
    (_pooled_cards), it only lacks the early ones."""
    return _card_record(record, played, OLD_VERSIONS)


def _pooled_cards(result, side, acc=None):
    """The card log's tallies of one side over every batch with a well-formed "cards"
    record of a version counted today (_card_record: versions 2 and 3; batches without
    one, or with a malformed or older one, are left out), added to acc when it's given:
    {"games" (games with card data), "bad" (games whose card log failed its checks), "old"
    (the games of batches whose record an earlier card log kept, _older_record: not
    counted, since it counted casts differently), "wins" and "first" (this side's, in the
    counted games), "batches" (batches counted, not the older ones), "early_of_games" and
    "early_of_wins" (the games and this side's wins of the version 3 batches among them:
    what early_games and early_wins are out of), "rows": {.dck name: [drawn_games,
    drawn_wins, copies_drawn, used, stuck, used_round_sum, other_casts, discarded,
    early_games, early_wins]}, "commander": {.dck name: [cast_games, cast_wins, casts,
    first_round_sum]}, "strata": {result key: Stratum}}.
    A row's first 8 numbers are every counted batch's; its last 2 only version 3 batches'
    (version 2 kept no early ones), so they're read against early_of_games and
    early_of_wins, never against games and wins.
    The strata keep each result's part of those tallies apart (_add_stratum), so a card's
    win-rate difference can be compared within each matchup before it's pooled
    (cardstats._difference): one stratum per result, both sides of a mirror in one. A
    saved result always has its key; one made by hand without it is a stratum of its own
    by the dict's identity (_stratum_key), so it must stay alive while acc is added to, as
    a list of results does."""
    if acc is None:
        acc = {"games": 0, "bad": 0, "old": 0, "wins": 0, "first": 0, "batches": 0, "early_of_games": 0,
               "early_of_wins": 0, "rows": {}, "commander": {}, "strata": {}}
    for name in ("old", "early_of_games", "early_of_wins"):
        acc.setdefault(name, 0)
    acc.setdefault("strata", {})
    for b in result.get("batches", []):
        record, played = b.get("cards"), len(b["games"])
        if record is None:
            continue
        if not _card_record(record, played):
            if _older_record(record, played):
                acc["old"] += played
            continue
        acc["batches"] += 1
        acc["games"] += record["games"]
        acc["bad"] += record["bad"]
        acc["wins"] += record["wins"][side]
        acc["first"] += record["first"][side]
        if record["v"] >= EARLY_VERSION:
            acc["early_of_games"] += record["games"]
            acc["early_of_wins"] += record["wins"][side]
        for part, size in (("rows", CARD_TALLIES), ("commander", COMMANDER_TALLIES)):
            for name, numbers in record.get(part, [{}, {}])[side].items():
                total = acc[part].setdefault(name, [0] * size)
                for i, n in enumerate(numbers):
                    total[i] += n
        _add_stratum(acc["strata"], _stratum_key(result), record, side)
    return acc


def _stratum_key(result):
    """The key of result's stratum: its key, or for a result made without one, its
    identity, so two such results aren't pooled naively into one stratum (None)."""
    key = result.get("key")
    return ("no key", id(result)) if key is None else key


def _add_stratum(strata, key, record, side):
    """Add one side of a well-formed "cards" record to its result's Stratum in strata
    (made when it's the first): {"games", "wins" (the side's, in those games),
    "early_of_games", "early_of_wins" (the same, of version 3 records only), "rows":
    {.dck name: [drawn_games, drawn_wins, early_games, early_wins]}, "commander": {.dck
    name: [cast_games, cast_wins]}}, the tallies a win-rate difference needs."""
    stratum = strata.setdefault(key, {"games": 0, "wins": 0, "early_of_games": 0, "early_of_wins": 0,
                                      "rows": {}, "commander": {}})
    stratum["games"] += record["games"]
    stratum["wins"] += record["wins"][side]
    early = record["v"] >= EARLY_VERSION
    if early:
        stratum["early_of_games"] += record["games"]
        stratum["early_of_wins"] += record["wins"][side]
    for part, size in (("rows", 4), ("commander", 2)):
        for name, numbers in record.get(part, [{}, {}])[side].items():
            total = stratum[part].setdefault(name, [0] * size)
            total[0] += numbers[0]
            total[1] += numbers[1]
            if part == "rows" and early:
                total[2] += numbers[SHARED_TALLIES]
                total[3] += numbers[SHARED_TALLIES + 1]


# ============================================================ the card log's token peaks (E7-S08)

PEAK_CAP = 30                   # cardlog.PEAK_CAP: a token's peaks list has at most this many numbers
TOKEN_NAME_MAX = 200            # a logged token name longer than this is malformed


def _token_tally(record):
    """Is a well-formed "cards" record's "tokens" (cardlog's docstring: [{logged name: [n1, n2,
    ...]}, {...}], nk the games whose peak was k) itself well formed: two dicts of names (1 to
    TOKEN_NAME_MAX characters) to 1 to PEAK_CAP counts ending with a non-zero one, each token's
    games no more than the record's games? A record without the key didn't tally tokens: False."""
    tallies = record.get("tokens")
    if not _pair(tallies, lambda t: isinstance(t, dict)):
        return False
    for side in tallies:
        for name, peaks in side.items():
            if not (isinstance(name, str) and 0 < len(name) <= TOKEN_NAME_MAX and isinstance(peaks, list)
                    and 0 < len(peaks) <= PEAK_CAP and all(_count(n) for n in peaks) and peaks[-1]
                    and sum(peaks) <= record["games"]):
                return False
    return True


def _pooled_tokens(result, side, acc=None):
    """The card log's token peaks of one side over every batch whose "cards" record is counted
    today (_card_record) and has a well-formed "tokens" (_token_tally), added to acc when it's
    given: {"games" (those batches' counted games), "batches", "untallied" (the counted games of
    card-log batches without the tally: played before 2026-10-29, with a malformed one, or with
    a record an earlier card log kept, _older_record), "tokens": {logged name: [n1, n2, ...]}
    (summed number by number; games without the token, games less their sum, peaked at 0)}.
    Batches without a card record, or with a malformed one, add nothing."""
    if acc is None:
        acc = {"games": 0, "batches": 0, "untallied": 0, "tokens": {}}
    for b in result.get("batches", []):
        record = b.get("cards")
        if record is None:
            continue
        if not _card_record(record, len(b["games"])):
            if _older_record(record, len(b["games"])):
                acc["untallied"] += record["games"]
            continue
        if not _token_tally(record):
            acc["untallied"] += record["games"]
            continue
        acc["batches"] += 1
        acc["games"] += record["games"]
        for name, peaks in record["tokens"][side].items():
            total = acc["tokens"].setdefault(name, [])
            total.extend([0] * (len(peaks) - len(total)))
            for i, n in enumerate(peaks):
                total[i] += n
    return acc
