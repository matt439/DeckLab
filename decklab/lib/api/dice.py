"""The Tokens page's Dice and counters panel (E7-S24): a space's owned dice and counters, kept
apart from its token cards (inventory dice_rules; dice.csv / the database's dice_counter table,
migration 0020). Imported when first needed, by feature_routes.dispatch.

    GET  /api/dice[?space=]   dice_view(): {space, ready, sha256, rows, items, problems, types, sizes}
    POST /api/dice/save       save_dice(body): add, edit or remove one row

Privacy as the token cards: reading needs the space's inventory (guard.require_sees_inventory:
its own people only, no admin override), writing tokens.edit on the space (guard.py: home's Matt
and User1, a member's own space). ready is False while the database lacks migration 0020: the
panel then says dice and counters can't be recorded yet, every write answers 409 with
dice_rules.DICE_REQUIRED, and the rest of the Tokens page works as before.

Each write is one inventory operation (lib/inventory/ops_dice.py: dice.add, dice.edit,
dice.remove) through inventory.apply, one change set in the audit trail ("add dice d20 (red)",
by the profile, with a removal's reason). A row is named by its six values as the page loaded
them ("base"), and the space's list must still have the sha256 the page loaded (409 with
"latest", the list as it is now, otherwise). Nothing here changes a decklist, the playable pool,
the watchlist or a deck table.
"""
from decklab.lib import decks, inventory, spaces
from decklab.lib.inventory import Op, dice_rules, files as inventory_files, ops_dice

from . import common, guard, saving
from .collection import space_param as _space
from .common import ApiError, _keys, _parse_body
from .settings import _web_actor, _writer

MAX_SAVE_BODY = 8 * 1024
MAX_REASON = 200


def _row_json(i, row):
    return {"key": f"d{i}", "index": i, **{k: row.text(k) for k in dice_rules.DICE_FIELDS},
            "quantity": int(row.text("quantity") or 0) if row.text("quantity").isdigit() else 0,
            "label": dice_rules.label(row.as_dict())}


def _view(space):
    """dice_view(space) without the read check (a write that passed tokens.edit sees its list)."""
    with common.state_errors():
        inv = inventory.current()
    sheet = inv.dice_set(space)
    problems = [] if sheet.error is None else [f"The dice and counters can't be read: {common._public(sheet.error)}"]
    problems += [common._public(p) for p in sheet.problems]
    rows = [] if sheet.error is not None else [_row_json(i, row) for i, row in enumerate(sheet.rows)]
    return {"space": space, "ready": bool(inv.dice_ready),
            "sha256": inventory_files.rendered_sha256(sheet) if sheet.exists and sheet.error is None else None,
            "rows": rows, "items": sum(r["quantity"] for r in rows), "problems": problems,
            "types": list(dice_rules.TYPES), "sizes": list(dice_rules.SIZES),
            "note": None if inv.dice_ready else dice_rules.DICE_REQUIRED}


def dice_view(space=None):
    """GET /api/dice[?space=<id>]: one space's dice and counters (home's by default): {space, ready
    (False before migration 0020), sha256 (None before the space has any), rows [{key "d<i>",
    index, type, size, kind, design, quantity (an int), notes, label}], items (their quantities in
    all), problems (rows that can't be read), types, sizes, note}. 403 for a space whose
    inventory the visitor may not see."""
    space = _space(space)
    guard.require_sees_inventory(space)
    return _view(space)


def _row_input(value, what):
    if not isinstance(value, dict):
        raise ApiError(400, f"{what} must be an object")
    unknown = sorted(set(value) - set(dice_rules.DICE_FIELDS))
    if unknown:
        raise ApiError(400, f"Unknown {what} key {unknown[0]!r}; a {what} takes: {', '.join(dice_rules.DICE_FIELDS)}")
    for key, item in value.items():
        if key == "quantity":
            if isinstance(item, bool) or not isinstance(item, (int, str)):
                raise ApiError(400, "quantity must be a whole number")
        elif not isinstance(item, str):
            raise ApiError(400, f"{key} must be text")
    return value


def _base_input(value):
    _row_input(value, "base")
    missing = [key for key in dice_rules.DICE_FIELDS if key not in value]
    if missing:
        raise ApiError(400, f"base needs every column; it lacks {missing[0]}")
    return {key: str(value[key]) for key in dice_rules.DICE_FIELDS}


def save_dice(body):
    """POST /api/dice/save {"profile", "space"? (home by default), "action": "add" | "edit" |
    "remove", "sha256" (the list's, null before it has rows), "base"? (edit, remove: the row's six
    values as loaded), "row"? (add, edit: the columns; an edit keeps those left out), "reason"?
    (remove: up to 200 characters)}. Returns {saved, index (the row's place in the new list; None
    after a remove), data (dice_view of that space)}. Needs tokens.edit on the space."""
    data = _parse_body(body, MAX_SAVE_BODY)
    profile = _writer(data)
    space = _space(data.get("space"))
    guard.require_space_write(profile, "tokens.edit", space)
    action = data.get("action")
    if action not in ops_dice.KINDS:
        raise ApiError(400, "action must be add, edit or remove")
    required = {"add": ("row",), "edit": ("base", "row"), "remove": ("base",)}[action]
    optional = ("reason",) if action == "remove" else ()
    _keys(data, ("profile", "action", "sha256", *required), (*optional, "space"))
    sha = data["sha256"]
    if not (sha is None or isinstance(sha, str) and common._SHA_RE.fullmatch(sha)):
        raise ApiError(400, "sha256 must be the 64-character hash /api/dice gave (null before the list has rows)")
    base = _base_input(data["base"]) if "base" in data else None
    row = _row_input(data["row"], "row") if "row" in data else None
    reason = data.get("reason", "")
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise ApiError(400, f"reason must be text of at most {MAX_REASON} characters")
    reason = decks.clean_title(reason)
    params = {"space": space, "sha256": sha}
    if base is not None:
        params["base"] = base
    if row is not None:
        fields = {key: "" for key in dice_rules.DICE_FIELDS}
        fields.update(base or {})
        fields.update({k: str(v) if k == "quantity" else v for k, v in row.items()})
        try:
            params["row"] = dice_rules.clean_row(fields)
        except ValueError as e:
            raise ApiError(400, f"That can't be saved: {e}") from None
    shown = params.get("row") or base
    whose = "" if space == spaces.HOME else f" ({spaces.get(space).name}'s dice and counters)"
    message = f"{action} dice {dice_rules.label(shown)}{whose}"
    try:
        with saving.inventory_write_lock():
            _, summary = inventory.apply(Op(f"dice.{action}", params), _web_actor(profile), message,
                                         reason=reason or None)
    except ops_dice.SameItem as e:
        raise ApiError(409, str(e), same_index=e.index, latest=_view(space)) from None
    except ops_dice.Stale as e:
        raise ApiError(409, str(e), latest=_view(space)) from None
    except inventory.Unavailable:
        raise ApiError(503, common.DATABASE_DOWN, reason="database") from None
    except inventory.Invalid as e:
        if str(e) == dice_rules.DICE_REQUIRED:
            raise ApiError(409, str(e), reason="migration") from None
        raise ApiError(400, str(e)) from None
    except inventory.Conflict as e:
        raise ApiError(409, str(e), latest=_view(space)) from None
    return {"saved": True, "index": (summary.extra or {}).get("index"), "text": summary.text, "data": _view(space)}
