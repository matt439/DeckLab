"""The Collection page's Record a trade (E7-S22): the copies that left and the cards that came in,
as one change (the inventory's collection.trade, as `python -m decklab.db collection trade` saves
it). Imported when first needed, by feature_routes.dispatch.

    POST /api/collection/trade/preview   preview_trade(body): what the trade would do; nothing is written
    POST /api/collection/trade           save_trade(body): the trade saved, one change set

Both take {"profile", "space"?, "sha256" (the rows' as the page loaded them), "gave": [{"set",
"collector_number", "finish", "quantity" (the copies given)}], "got": [rows in the collection's
columns, as the add-card sheet sends them], "with"? (who it was with, one line of at most
MAX_WITH characters), "message"? (one line of at most MAX_MESSAGE)}, and the save
"confirm_in_use"? too. Each needs collection.edit on the space (guard.require_space_write, as
the page's other edits: only the space's own people). A card got is checked as the add-card
sheet's card is (its exact Scryfall name and a paper printing in that finish, while the card
index is ready); an ordinary basic land got isn't tracked unless that printing already is.

The preview answers {ok, sha256, gave: [{name, set, collector_number, finish, quantity (given),
before, after}], got (the rows kept, as checked), skipped_basics, in_use (the built decks and
intact products that would hold more copies than are left: collection_guards.reduction_warnings,
as a reduction's), confirm_in_use (the review token a save with in_use needs; null without),
stale_tables ([{id, title}] of the decks it would leave out of date, the ones this visitor may
see; null when that can't be worked out), message (the change set's) and reason}.

The save refuses held copies (409 {in_use, confirm_in_use, sha256, rows}) unless confirm_in_use
is the token for this exact trade, profile and inventory (as save_card's _reduction_guard binds
it). Its change set's message is the message given, then both sides ("Trade with User3: gave 2
Llanowar Elves (FDN 227); got 1 Sol Ring (C21 263)"), its reason "Traded" (or "Traded with T"),
and it keeps no raw import; no prices anywhere. It answers as save_card does: {ok, sha256, rows,
prices, storage, stale_tables (the space's decks now out of date: the trade doesn't refresh
their tables, as no collection edit does), gave (copies), got (cards)}. A collection changed
since sha256 answers 409 with its rows now, as save_card's.
"""
import hashlib
import json

from decklab.lib import inventory, pool
from decklab.lib.inventory import ops_collection as ops
from decklab.lib.inventory import rules

from . import collection_edit as ce
from . import common, guard
from .collection import space_param
from .common import NUMBER_RE, SET_RE, ApiError, _keys, _parse_body, _public
from .settings import _web_actor, _writer

MAX_TRADE_BODY = 256 * 1024         # bytes of a request (a few hundred rows)
MAX_TRADE_ROWS = 200                # rows each side
MAX_WITH = 80                       # characters of the who-with note (as the command line's --with)
MAX_MESSAGE = 200                   # characters of the message


def _gave_input(value):
    """The request's gave as [[set, collector_number, finish, quantity]], each printing once."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TRADE_ROWS:
        raise ApiError(400, f"gave must list 1 to {MAX_TRADE_ROWS} rows the trade gave")
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ApiError(400, "Each row given must be {\"set\", \"collector_number\", \"finish\", \"quantity\"}")
        _keys(item, ("set", "collector_number", "finish", "quantity"))
        if not all(isinstance(item[k], str) for k in ("set", "collector_number", "finish")):
            raise ApiError(400, "Each row given must name its set, collector number and finish as text")
        key = (item["set"].strip().lower(), item["collector_number"].strip(), item["finish"])
        if not SET_RE.fullmatch(key[0]) or key[1] and not NUMBER_RE.fullmatch(key[1]) or key[2] not in ce.FINISHES:
            raise ApiError(400, "Each row given must be a row's set code, collector number and finish")
        if key in seen:
            raise ApiError(400, f"{key[0].upper()} {key[1]} {key[2]} is given twice; give each printing once")
        seen.add(key)
        out.append([*key, int(ce._quantity(item["quantity"]))])
    return out


def _got_input(value):
    """The request's got as rows in the collection's columns, each matched as save_card matches a card."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TRADE_ROWS:
        raise ApiError(400, f"got must list 1 to {MAX_TRADE_ROWS} cards the trade brought in")
    out = []
    for item in value:
        row = ce._row_input(item)
        if ce._ready() and not rules.ordinary_basic(row):
            row, problem = ce.match(row)
            if problem:
                raise ApiError(400, f"{row['name']} can't be added: {problem}")
        out.append(row)
    return out


def _request(body, save):
    """(profile, space, op, who, message, confirmation) of a request, checked."""
    data = _parse_body(body, MAX_TRADE_BODY)
    profile = _writer(data)
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    _keys(data, ("profile", "sha256", "gave", "got"),
          ("space", "with", "message", *(("confirm_in_use",) if save else ())))
    sha = ce._request_sha(data["sha256"])
    who = ce._text(data.get("with"), "with", limit=MAX_WITH)
    message = ce._text(data.get("message"), "message", limit=MAX_MESSAGE)
    confirmation = data.get("confirm_in_use")
    if confirmation is not None and (not isinstance(confirmation, str) or not common._SHA_RE.fullmatch(confirmation)):
        raise ApiError(400, "confirm_in_use must be the warning's 64-character review token")
    op = inventory.Op("collection.trade", {"space": space, "gave": _gave_input(data["gave"]),
                                           "got": _got_input(data["got"]), "sha256": sha, "whose": ce._whose(space)})
    return profile, space, op, who, message, confirmation


def _review(op, profile):
    """(before, after, summary, warnings, token): op previewed on the inventory now, the held
    copies it would leave short and the token that binds a confirmation to this exact trade,
    profile and both inventory revisions (None without warnings)."""
    from .collection_guards import ReductionCheckError, reduction_warnings
    space = op.params["space"]
    with common.state_errors():
        before = inventory.current()
        try:
            after, summary = inventory.preview(op, refresh=False)
        except ops.Stale:
            raise ce._stale(space) from None
        except ops.Missing as e:
            rows, now = ce._read(space, fresh=True)
            raise ApiError(409, str(e), sha256=now, rows=ce._rows_json(rows)) from None
        except inventory.Invalid as e:
            raise ApiError(400, _public(e)) from None
        try:
            warnings = reduction_warnings(before, after, space)
        except ReductionCheckError as e:
            warnings = [{"message": str(e)}]
    token = None
    if warnings:
        content = {"profile": profile["id"], "kind": op.kind, "params": op.params,
                   "revision": before.revision, "decks_revision": before.decks_revision, "warnings": warnings}
        token = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return before, after, summary, warnings, token


def _left_stale(before, after, space):
    """[{id, title}] of the space's decks (those this visitor may see) whose tables after would
    leave out of date that before didn't; None when that can't be worked out."""
    try:
        found = []
        for snapshot in (before, after):
            with inventory.pinned(snapshot):
                found.append({e["id"]: e["title"] for e in pool.stale_tables(pool.for_space(space), only={space})})
        sees = guard.deck_reader()
    except Exception as e:      # noqa: BLE001 - a preview's note only
        common._log(f"A trade preview's out-of-date tables can't be worked out: {type(e).__name__}: {e}")
        return None
    return [{"id": i, "title": t} for i, t in found[1].items() if i not in found[0] and sees(i)]


def _words(before, op, summary, who, message):
    """(gave as [(row, copies)], the rows got that are kept, the change set's message, its reason)."""
    space = op.params["space"]
    rows = ops.rows_of(before.collection(space))
    gave = summary.extra["gave"]
    tracked = ops.trade_tracked(summary.extra["got"], rows)
    return gave, tracked, ops.trade_message(message, gave, tracked, who), f"Traded{' with ' + who if who else ''}"


def preview_trade(body):
    """POST /api/collection/trade/preview: see the module docstring. Nothing is written."""
    profile, space, op, who, message, _ = _request(body, save=False)
    before, after, summary, warnings, token = _review(op, profile)
    gave, tracked, words, reason = _words(before, op, summary, who, message)
    return {"ok": True, "sha256": ops.sha256_of(before.collection(space)),
            "gave": [{**{k: row[k] for k in ("name", "set", "collector_number", "finish")}, "quantity": n,
                      "before": int(row["quantity"]), "after": int(row["quantity"]) - n} for row, n in gave],
            "got": ce._rows_json(tracked), "skipped_basics": summary.counts.get("skipped_basics", 0),
            "in_use": warnings, "confirm_in_use": token, "stale_tables": _left_stale(before, after, space),
            "message": words, "reason": reason}


def save_trade(body):
    """POST /api/collection/trade: see the module docstring."""
    profile, space, op, who, message, confirmation = _request(body, save=True)
    before, _, summary, warnings, token = _review(op, profile)
    if warnings and confirmation != token:
        rows, now = ce._view(before.collection(space))
        raise ApiError(409, "These copies may be in use. Review the warning before saving.",
                       in_use=warnings, confirm_in_use=token, sha256=now, rows=ce._rows_json(rows))
    _, tracked, words, reason = _words(before, op, summary, who, message)
    op = inventory.Op(op.kind, {**op.params, "expect_decks_revision": before.decks_revision})
    sheet, summary = ce._apply(space, op, _web_actor(profile), reason, expected_revision=before.revision,
                               message=words)
    rows, now = ce._view(sheet)
    shown = ce._rows_json(rows)
    return {"ok": True, "sha256": now, "rows": shown, **ce._extras(space, shown),
            "gave": summary.counts["gave"], "got": summary.counts["cards"], "stale_tables": ce._stale_tables(space)}
