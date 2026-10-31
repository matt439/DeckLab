"""Owned dice and counters' writes as inventory operations (E7-S24), shared by the Tokens page's
Dice and counters panel (lib/api/dice.py) and python -m decklab.db dice:

    inventory.apply(Op("dice.add", {"space": "home", "sha256": sha, "row": row}), actor, message)
    inventory.apply(Op("dice.edit", {"space": ..., "sha256": ..., "base": base, "row": row}), ...)
    inventory.apply(Op("dice.remove", {"space": ..., "sha256": ..., "base": base}), ..., reason=...)

Parameters (plain values):
- space: whose dice and counters (home, or a person's space id).
- sha256: the sha256 of the space's dice.csv as the caller saw it rendered (files.rendered_sha256;
  None before the space has any). A different one now raises Stale.
- base (edit, remove): the row's six values as the caller saw them; the row equal to it (the
  quantity compared as a number) is the one changed; none raises Stale.
- row (add, edit): the new row, every column (an edit's caller overlays its changes on base); it's
  cleaned here (dice_rules.clean_row), so nothing unchecked is saved.

Rows are never merged: an add, or an edit that makes a row the same item as another
(dice_rules.identity), raises SameItem. The space's rows are kept in dice_rules.sort_key order,
each edited row keeping its hidden id.

Refusals are state errors: Invalid for a row that breaks the rules and, before the database has
migration 0020, for any write (dice_rules.DICE_REQUIRED); Conflict for a list that can't be
rewritten (rows the rules refuse, which only the files backend can hold) and SameItem; Stale (a
Conflict) for a list that changed. Nothing here touches a decklist, the playable pool, the
watchlist or a deck table.

The Summary: text in plain words ("Added d20 (red) ×2 to the home dice and counters"), counts
{"items": quantities after}, extra {"index": the row's place in the saved list (None after a
removal)}.
"""
from decklab.lib.state import Conflict, Invalid

from . import Summary, dice_rules, files, register, rules
from .model import DiceRow

STALE = "The dice and counters changed since they were read; look at them again and retry."
KINDS = ("add", "edit", "remove")


class Stale(Conflict):
    """The space's dice.csv isn't the one the caller saw, or the base row isn't in it any more."""

    def __init__(self, inv, message=STALE):
        super().__init__(message)
        self.inv = inv


class SameItem(Conflict):
    """Another row is the same item; index is its place in the list."""

    def __init__(self, index):
        super().__init__(dice_rules.SAME)
        self.index = index


def match_key(row):
    """A row's six values, the quantity compared as a number."""
    quantity = str(row.get("quantity") if row.get("quantity") is not None else "").strip()
    return tuple(str(int(quantity)) if key == "quantity" and quantity.isdigit() else str(row.get(key) or "")
                 for key in dice_rules.DICE_FIELDS)


def whose(space):
    return "the home dice and counters" if space == "home" else f"{space}'s dice and counters"


def readable(inv, space):
    """The space's dice Sheet, refusing (Invalid / Conflict) when it can't be written."""
    if not inv.dice_ready:
        raise Invalid(dice_rules.DICE_REQUIRED)
    sheet = inv.dice_set(space)
    if sheet.error is not None or sheet.problems or sheet.strict_error:
        why = sheet.error or (sheet.problems[0] if sheet.problems else sheet.strict_error)
        raise Conflict(f"{why}{rules.UNTIL_PUT_RIGHT}")
    return sheet


def _save(inv, action, space, sha256, base=None, row=None):
    sheet = readable(inv, space)
    now = files.rendered_sha256(sheet) if sheet.exists else None
    if now != sha256:
        raise Stale(inv)
    rows = list(sheet.rows)
    dicts = [r.as_dict() for r in rows]
    at = None
    if action != "remove" and row is None:
        raise Invalid(f"dice.{action} needs the new row")
    if action != "add":
        if base is None:
            raise Invalid(f"dice.{action} needs the row's six values (base)")
        want = match_key(base)
        at = next((i for i, d in enumerate(dicts) if match_key(d) == want), None)
        if at is None:
            raise Stale(inv)
    new = None
    if action != "remove":
        try:
            new = dice_rules.clean_row(dict(row))
        except (TypeError, ValueError) as e:
            raise Invalid(f"That can't be saved: {e}") from None
        same = next((i for i, d in enumerate(dicts) if i != at and dice_rules.identity(d) == dice_rules.identity(new)),
                    None)
        if same is not None:
            raise SameItem(same)
    old = dicts[at] if at is not None else None
    if action == "add":
        rows.append(DiceRow.make(new))
    elif action == "edit":
        rows[at] = rows[at].replace(**new)          # keeps the row's hidden id
    else:
        del rows[at]
    after = inv.with_dice(space, rows)
    saved = after.dice_set(space).rows
    index = None if new is None else next(i for i, r in enumerate(saved) if r.as_dict() == new)
    shown = new or old
    words = {"add": "Added", "edit": "Changed", "remove": "Removed"}[action]
    joint = {"add": "to", "edit": "in", "remove": "from"}[action]
    text = f"{words} {dice_rules.label(shown)} ×{shown['quantity']} {joint} {whose(space)}"
    items = sum(int(r.text("quantity") or 0) for r in saved)
    return after, Summary(text=text, counts={"items": items}, extra={"index": index})


@register("dice.add")
def add(inv, space, sha256, row):
    return _save(inv, "add", space, sha256, row=row)


@register("dice.edit")
def edit(inv, space, sha256, base, row):
    return _save(inv, "edit", space, sha256, base=base, row=row)


@register("dice.remove")
def remove(inv, space, sha256, base):
    return _save(inv, "remove", space, sha256, base=base)
