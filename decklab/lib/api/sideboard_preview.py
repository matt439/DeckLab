"""A saved plan applied to its exact, still-visible current lists without writes.

This is a list preview and a proposed fresh paired-game budget. It does not
inspect saved Forge results, engine identity, permissions to start a run or
execution readiness. The derived digest is a snapshot hash, not a saved deck
revision or a compatible simulation-result key.
"""
import contextlib
import copy
import json

from decklab.lib import cards, decks, inventory, state
from decklab.lib.forge import seqstats, variants
from decklab.lib.state import rules

from . import guard, play_records as play
from .common import ApiError, _CONTROL_RE, _SHA_RE


MAX_ROWS = 500
MAX_TOTAL_ROWS = 1200
MAX_RESPONSE = 512 * 1024
MAX_QUANTITY = 999
NO_PLAN = "That sideboard plan is not available."
PAIR_UNAVAILABLE = "This plan cannot be previewed with the current visible lists."
PLAN_CHANGED = "This sideboard plan changed. Reload it before previewing again."
LISTS_CHANGED = "A selected decklist changed. Review a new plan revision before previewing again."
INVALID_PLAN = "This saved sideboard plan cannot be previewed safely."
UNAVAILABLE = "The sideboard preview is unavailable. Try again later."
BUDGET_BASIS = ("Fresh paired-game upper bounds; saved results, engine compatibility and "
                "execution readiness were not checked.")
_SNAPSHOT_KEYS = frozenset({"id", "version", "title", "sha256", "sections"})
_LINE_KEYS = frozenset({"qty", "name", "set", "number", "finish"})
_RECORD_KEYS = frozenset({"version", "id", "kind", "revision", "created_on", "updated_on", "updated_by",
                          "notes", "deck", "opponent", "out", "in", "after"})


def _text(value, maximum, *, blank=False):
    if not isinstance(value, str) or len(value) > maximum or (not blank and not value) or _CONTROL_RE.search(value):
        raise ValueError
    value.encode("utf-8")  # a lone surrogate cannot be sent as a JSON response
    return value


def _sections(value):
    """Check shallow sizes before walking rows or hashing any captured content."""
    if not isinstance(value, dict) or len(value) > len(decks.SECTIONS) or set(value) - set(decks.SECTIONS):
        raise ValueError
    if not isinstance(value.get("Deck"), list) or not value["Deck"]:
        raise ValueError
    count = 0
    for lines in value.values():
        if not isinstance(lines, list):
            raise ValueError
        count += len(lines)
        if count > MAX_ROWS:
            raise ValueError
    for lines in value.values():
        for line in lines:
            if not isinstance(line, dict) or len(line) != len(_LINE_KEYS) or set(line) != _LINE_KEYS or type(line["qty"]) is not int \
                    or not 1 <= line["qty"] <= MAX_QUANTITY:
                raise ValueError
            _text(line["name"], 300)
            for field in ("set", "number"):
                if line[field] is not None:
                    _text(line[field], 80, blank=True)
            if line["finish"] not in ("nonfoil", "foil", "etched"):
                raise ValueError
    return count


def _snapshot_shape(value):
    if not isinstance(value, dict) or len(value) != len(_SNAPSHOT_KEYS) or set(value) != _SNAPSHOT_KEYS:
        raise ValueError
    _text(value["id"], 200)
    _text(value["title"], 500)
    if value["version"] not in ("target", "owned") or not isinstance(value["sha256"], str) \
            or not _SHA_RE.fullmatch(value["sha256"]):
        raise ValueError
    return _sections(value["sections"])


def _bounded_record(record):
    if len(record) != len(_RECORD_KEYS) or set(record) != _RECORD_KEYS:
        raise ValueError
    if type(record["version"]) is not int or record["version"] != 1 or record["kind"] != "sideboards" \
            or not isinstance(record["id"], str) or not rules.PLAY_ID.fullmatch(record["id"]):
        raise ValueError
    if type(record["revision"]) is not int or not 1 <= record["revision"] <= 999999999:
        raise ValueError
    for field in ("created_on", "updated_on", "updated_by"):
        _text(record[field], 80)
    notes = record["notes"]
    if not isinstance(notes, str) or len(notes) > 2000 or rules.NOTES_CONTROL.search(notes):
        raise ValueError
    notes.encode("utf-8")
    count = _snapshot_shape(record["deck"]) + _snapshot_shape(record["opponent"]) + _sections(record["after"])
    for direction in ("out", "in"):
        moves = record[direction]
        if not isinstance(moves, list) or len(moves) > 100:
            raise ValueError
        count += len(moves)
        if count > MAX_TOTAL_ROWS:
            raise ValueError
        for move in moves:
            if not isinstance(move, dict) or len(move) != 2 or set(move) != {"name", "qty"} or type(move["qty"]) is not int \
                    or not 1 <= move["qty"] <= 99:
                raise ValueError
            _text(move["name"], 300)


def _visible_pair(record, reads):
    """Never quote a captured hidden opponent's identifier in a refusal."""
    for key in ("deck", "opponent"):
        selected = record.get(key)
        if not isinstance(selected, dict) or rules.is_removed_deck(selected):
            return False
        ident = selected.get("id")
        if not isinstance(ident, str) or not 3 <= len(ident) <= 200 or not reads(ident):
            return False
    return True


def _current_snapshot(selected, reads):
    """Match play._snapshot's digest, with caps before per-card canonical checks."""
    summary, source = play._deck_sections(selected["id"], selected["version"])
    if not reads(summary) or play.is_half(summary):
        raise ApiError(409, PAIR_UNAVAILABLE)
    if not isinstance(source, dict) or set(source) - set(decks.SECTIONS) or \
            any(not isinstance(lines, list) for lines in source.values()) or \
            sum(map(len, source.values())) > MAX_ROWS:
        raise ApiError(409, LISTS_CHANGED)
    sections = {section: [{"qty": line.quantity, "name": line.name, "set": line.set,
                           "number": line.number, "finish": line.finish} for line in lines]
                for section, lines in source.items()}
    _sections(sections)
    for lines in sections.values():
        for line in lines:
            if not decks.is_basic_land(line["name"]) and cards.resolve(line["name"]) != line["name"]:
                raise ApiError(409, LISTS_CHANGED)
    payload = {"id": summary["id"], "version": selected["version"], "sections": sections}
    snapshot = {**payload, "title": summary["title"], "sha256": play._hash(play._bytes(payload))}
    _snapshot_shape(snapshot)
    kind = decks.engine_kind(summary) if summary.get("kind") in ("casual", "commander") else None
    return snapshot, kind


def _game_plan(base_kind, opponent_kind):
    if base_kind not in ("constructed", "commander") or opponent_kind not in ("constructed", "commander"):
        reason = "format_unknown"
    elif base_kind != opponent_kind:
        reason = "format_mismatch"
    else:
        reason = None
    if reason:
        return {"status": "unavailable", "reason": reason, "cached_work": "not_checked", "remaining_games": None,
                "execution": "not_performed", "modes": [],
                "basis": "A paired-game budget is unavailable until both selected lists have the same verified format."}
    modes = []
    for ident, targets in (("quick", (variants.QUICK_GAMES,)), ("ahead", seqstats.PAIRED_LOOKS)):
        if not isinstance(targets, tuple) or not 1 <= len(targets) <= 8 or any(
                type(target) is not int or not 1 <= target <= 100000 for target in targets) or \
                tuple(sorted(set(targets))) != targets:
            raise ValueError
        maximum = targets[-1]
        modes.append({"id": ident, "targets": list(targets), "base_games_max": maximum,
                      "post_board_games_max": maximum, "total_games_max": 2 * maximum})
    return {"status": "proposed", "cached_work": "not_checked", "remaining_games": None,
            "execution": "not_performed", "modes": modes, "basis": BUDGET_BASIS}


def preview_sideboard(id=None, sha256=None):
    """GET /api/play/sideboard-preview?id=<saved plan id>&sha256=<record hash>.

    A private/missing record is indistinguishable, including a stale caller hash.
    Visibility precedes stored-content validation and both current list readers.
    The normal request pin is reused, or one lazy inventory pin covers both lists.
    """
    if not isinstance(id, str) or not rules.PLAY_ID.fullmatch(id) or not isinstance(sha256, str) \
            or not _SHA_RE.fullmatch(sha256):
        raise ApiError(400, "Choose a saved sideboard plan and its exact record version.")
    profile, script = guard.viewer(), guard.script()
    try:
        record = state.store().play_get("sideboards", id)
    except Exception:
        raise ApiError(503, UNAVAILABLE) from None
    try:
        visible = isinstance(record, dict) and play._sees_record("sideboards", record, profile, script)
    except Exception:
        visible = False
    if not visible:
        raise ApiError(404, NO_PLAN)
    reads = guard.deck_reader(profile)
    try:
        visible_pair = _visible_pair(record, reads)
    except Exception:
        visible_pair = False
    if not visible_pair:
        raise ApiError(409, PAIR_UNAVAILABLE)
    try:
        _bounded_record(record)
        actual = play._checked("sideboards", id, record)
    except Exception:
        raise ApiError(500, INVALID_PLAN) from None
    if actual != sha256:
        raise ApiError(409, PLAN_CHANGED)
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            base, base_kind = _current_snapshot(record["deck"], reads)
            opponent, opponent_kind = _current_snapshot(record["opponent"], reads)
            if base["sha256"] != record["deck"]["sha256"] or opponent["sha256"] != record["opponent"]["sha256"]:
                raise ApiError(409, LISTS_CHANGED)
            moved = play._plan_moves(base, record["out"], record["in"])
        post = {**base, "sections": moved["after"]}
        post["sha256"] = play._hash(play._bytes({key: post[key] for key in ("id", "version", "sections")}))
        post["derived"] = True
        main = lambda snap: sum(line["qty"] for section in decks.MAIN_SECTIONS
                                for line in snap["sections"].get(section, []))
        side = lambda snap: sum(line["qty"] for line in snap["sections"].get("Sideboard", []))
        answer = {"version": 1, "plan": {"id": id, "sha256": actual, "revision": record["revision"]},
                  "base": base, "post_board": post,
                  "opponent": {key: opponent[key] for key in ("id", "version", "title", "sha256")},
                  "changes": {direction: moved[direction] for direction in ("out", "in")},
                  "counts": {"main_before": main(base), "main_after": main(post),
                             "sideboard_before": side(base), "sideboard_after": side(post)},
                  "game_plan": _game_plan(base_kind, opponent_kind)}
        if len(json.dumps(answer, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RESPONSE:
            raise ValueError
        return copy.deepcopy(answer)
    except ApiError as error:
        status = 503 if error.status >= 500 else 409
        raise ApiError(status, UNAVAILABLE if status == 503 else LISTS_CHANGED) from None
    except Exception:
        raise ApiError(503, UNAVAILABLE) from None
