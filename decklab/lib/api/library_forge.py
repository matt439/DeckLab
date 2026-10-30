"""The library's Forge line (E11-S30 slice 8, design/visual-design.md 4.1 and 4.2): GET /api/library/forge, each
visible casual list's field average and when it was tested, worked out from the saved games (nothing plays).

    library_forge_view()
                        {"decks": {deck id: {"version", "card_sha", "rate" {value, low, high} or None, "partial",
                        "counted", "of", "games", "tested"}}, "error"}

The field and its numbers are the field view's (forge.field.averages), over the decks this viewer sees, as
rankings_view works them out: a member's field is their space and the public spaces. Only the Constructed
field: a Commander deck's cell stays blank (4.2). The answer is cached per viewer space until a saved
result, a field run's note or a field list changes (or CACHE_S passes), since working the field out reads
every pair's saved games.
"""
import threading
import time
import traceback

from . import common, forge_runs, guard

FORMAT = "Constructed"
CACHE_S = 600
NO_NUMBERS = "The Forge numbers can't be worked out on the PC now."
_cache = {}
_lock = threading.Lock()


def _stamp(folder):
    """(count, newest mtime, total size) of the saved results and field notes: changes when a game is saved."""
    count = newest = size = 0
    for pattern in ("*.json", "field/*.json"):
        try:
            paths = list(folder.glob(pattern))
        except OSError:
            continue
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            count, newest, size = count + 1, max(newest, stat.st_mtime_ns), size + stat.st_size
    return count, newest, size


def _options(seen):
    public = frozenset(guard.public_deck_spaces())
    return public, {"space": seen.space or "home", "public": lambda space: space in public, "visible": seen.deck,
                    "product_notes": seen.everything or seen.space == "home"}


def _cached(name, seen, forge, work):
    """work(forge, options) for this viewer's field, cached as the module docstring says (name: which answer)."""
    public, options = _options(seen)
    lists = forge.field.field_lists(FORMAT, **options)
    fingerprint = (tuple((e["id"], e["version"], e["card_sha"]) for e in lists),
                   _stamp(forge.common._results_dir(None)))
    key = (name, seen.space, seen.everything, public)
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] == fingerprint and time.monotonic() - hit[1] < CACHE_S:
        return hit[2]
    found = work(forge, {**options, "keep": lambda result: seen.result(forge, result)})
    with _lock:
        _cache[key] = (fingerprint, time.monotonic(), found)
    return found


def pair_rates():
    """({(deck id, deck id): {"value", "games", "versions"}}, None) of the Constructed field's saved pairs this viewer
    sees (forge.field.pair_rates, cached), for tonight's pairs (E1-S28); ({}, NO_NUMBERS) when they can't
    be worked out."""
    try:
        forge = forge_runs._forge_module()
        seen = forge_runs._Seen()
        found = _cached("pairs", seen, forge, lambda forge, options: forge.field.pair_rates(FORMAT, **options))
    except Exception:
        common._log(f"The Forge pair numbers can't be worked out:\n{traceback.format_exc()}")
        return {}, NO_NUMBERS
    return {pair: rate for pair, rate in found.items() if seen.deck(pair[0]) and seen.deck(pair[1])}, None


def library_forge_view():
    """GET /api/library/forge: see the module's docstring. The deck-read policy applies: only decks the viewer
    sees, over a field of decks they see; error is NO_NUMBERS (and decks {}) when they can't be worked out."""
    forge = forge_runs._forge_module()
    seen = forge_runs._Seen()
    try:
        found = _cached("averages", seen, forge, lambda forge, options: forge.field.averages(FORMAT, **options))
    except Exception:
        common._log(f"The library's Forge numbers can't be worked out:\n{traceback.format_exc()}")
        return {"decks": {}, "error": NO_NUMBERS}
    out = {}
    for deck_id, numbers in found.items():
        if not seen.deck(deck_id):
            continue
        average = numbers.get("average") or {}
        rate = None
        if average.get("value") is not None:
            rate = {k: average.get(k) for k in ("value", "low", "high")}
        out[deck_id] = {"version": numbers["version"], "card_sha": numbers["card_sha"],
                        "rate": rate, "partial": bool(average.get("partial")),
                        "counted": average.get("counted"), "of": average.get("of"), "games": numbers["games"],
                        "tested": numbers["tested"]}
    return {"decks": out, "error": None}
