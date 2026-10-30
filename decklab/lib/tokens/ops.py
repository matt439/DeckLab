"""The token cards' writes as inventory operations (decklab.lib.inventory), shared by the
Tokens page (lib/api/tokens.py) and python -m decklab.db tokens. Part of decklab.lib.tokens
(see its docstring).

    inventory.apply(Op("tokens.add", {"space": "home", "sha256": sha, "row": row}), actor, message)
    inventory.apply(Op("tokens.edit", {"space": ..., "sha256": ..., "base": base, "row": row}), ...)
    inventory.apply(Op("tokens.remove", {"space": ..., "sha256": ..., "base": base}), ..., reason=...)
    inventory.apply(Op("tokens.add_many", {"space": ..., "sha256": ..., "rows": [row, ...]}), ...)

Parameters (plain values):
- space: whose token cards (home, or a person's space id).
- sha256: the sha256 of the space's tokens.csv as the caller saw it rendered (tokens.read()'s
  sha256; None before the space has any token cards). A different one now raises Stale.
- base (edit, remove): the row's ten values as the caller saw them. The first row equal to it
  (quantity compared as a number, so a hand-written "02" matches 2) is the one changed; none
  raises Stale.
- row (add, edit): the new row, every column (the caller overlays its changes on base and checks
  the names against the card index first: names.check_names needs the index, which an operation
  doesn't read). It's cleaned again here (rules.token_page_row), so nothing unchecked is saved.
- separate (add, edit): keep it apart from a row naming the same card.

Rows are never merged here. An add, an edit that changes which card a row names, or one that
makes a row fully known (rules.token_known), raises SameRow when another row names that card
(rules.token_identity), unless separate asks to keep them apart; keeping them apart is allowed
only when the new row, or every other row naming that card, isn't fully known (receipts merge
two known rows). The space's rows are then kept in rules.token_sort_key order, ties in their
order (Inventory.with_tokens), each edited row keeping its hidden id.

Refusals are state errors: Stale and SameRow (state.Conflict, with what the page's 409 needs),
state.Conflict for token cards that can't be rewritten (rows a strict read refuses; today's
"..." and rules.UNTIL_PUT_RIGHT words), state.Invalid for a row that breaks the rules, and Broken (a
state.StateError) when the rows made don't come back as the rows read plus the new one, which
would be a bug here, so nothing is saved.

The Summary: text in plain words for the audit trail ("Added Rabbit / Rabbit ×2 to the home
token cards"), counts {"cards": physical cards after}, and extra {"index": the new row's place
in the saved list (None after a removal), "resorted": whether the rows weren't in the standard
order, "body": lines that say more about the change (RESORTED)}.
"""
import collections
import csv
import io

from decklab.lib.inventory import Summary, files, register, rules
from decklab.lib.inventory.model import TokenRow, refuse_unreadable_tokens
from decklab.lib.state import Conflict, Invalid, StateError

RESORTED = "Also sorted the token cards into the standard order (no other row changed)"
STALE = "The token cards changed since they were read; look at them again and retry."
SAME = "Those are the same card; change its quantity instead."
KINDS = ("add", "edit", "remove")
MAX_BATCH = 50          # rows tokens.add_many adds at once (Activity's undo removes 2 to 50 added rows together)


class Stale(Conflict):
    """The space's tokens.csv isn't the one the caller saw (sha256), or the base row isn't in it
    any more. inv: the snapshot the operation saw (the page's 409 shows that list)."""

    def __init__(self, inv, message=STALE):
        super().__init__(message)
        self.inv = inv


class SameRow(Conflict):
    """Another row names the same card. same_row: {index, row (quantity an int),
    separate_allowed}, as the page's 409 has it."""

    def __init__(self, message, same_row):
        super().__init__(message)
        self.same_row = same_row


class Broken(StateError):
    """The rows made don't match the rows read plus the new one; nothing was saved."""


def match_key(row):
    """A row's ten values, the quantity compared as a number (a page sends it as an int, so a
    hand-written "02" comes back as "2")."""
    quantity = (row.get("quantity") or "").strip()
    return tuple((str(int(quantity)) if key == "quantity" and quantity.isdigit() else (row.get(key) or ""))
                 for key in rules.TOKEN_FIELDS)


def _key(row):
    return tuple(row[k] for k in rules.TOKEN_FIELDS)


def same_rows(rows, new, skip=None):
    """[(index, row)] of every row (dicts) other than rows[skip] naming the same card as new."""
    identity = rules.token_identity(new)
    return [(i, row) for i, row in enumerate(rows) if i != skip and rules.token_identity(row) == identity]


def _whose(space):
    return "the home token cards" if space == "home" else f"{space}'s token cards"


def _guard(rows, untouched, new):
    """Broken unless rows render and read back as exactly the untouched rows plus new."""
    data = rules.tokens_csv_bytes(rows)
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""), strict=True)
    if next(reader, None) != list(rules.TOKEN_FIELDS):
        raise Broken("The tokens list Deck Lab made has the wrong columns; nothing was saved")
    written = collections.Counter(tuple(values) for values in reader if values)
    expected = collections.Counter(_key(row) for row in untouched)
    if new is not None:
        expected[_key(new)] += 1
    if written != expected:
        raise Broken("The tokens list Deck Lab made doesn't match the rows it read; nothing was saved")


def _never_merge(action, rows, old, new, at, separate):
    """SameRow / Conflict(SAME) by the never-merge rule (see the module docstring)."""
    if not (old is None or rules.token_identity(old) != rules.token_identity(new)
            or not rules.token_known(old) and rules.token_known(new)):
        return
    same = same_rows(rows, new, at)
    if not same:
        return
    known = [(i, row) for i, row in same if rules.token_known(row)]
    allowed = not rules.token_known(new) or not known
    index, other = known[0] if known and not allowed else same[0]
    if not separate:
        # Only an add has an "Add to that card" button to answer the question.
        ask = " Add to its quantity instead?" if action == "add" else ""
        raise SameRow(f"That card is already listed ({rules.token_label(other)} ×{other['quantity']}).{ask}",
                      {"index": index, "row": {**other, "quantity": int(other["quantity"])},
                       "separate_allowed": allowed})
    if not allowed:
        raise Conflict(SAME)


def _save(inv, action, space, sha256, base=None, row=None, separate=False):
    sheet = inv.token_set(space)
    refuse_unreadable_tokens(sheet)
    now = files.rendered_sha256(sheet) if sheet.exists else None
    if now != sha256:
        raise Stale(inv)
    rows = list(sheet.rows)
    dicts = [r.as_dict() for r in rows]
    at = None
    if action != "add":
        if base is None:
            raise Invalid(f"tokens.{action} needs the row's ten values (base)")
        want = match_key(base)
        at = next((i for i, d in enumerate(dicts) if match_key(d) == want), None)
        if at is None:
            raise Stale(inv)
    old = dicts[at] if at is not None else None
    new = None
    if action != "remove":
        if row is None:
            raise Invalid(f"tokens.{action} needs the new row")
        try:
            new = rules.token_page_row(row)
        except ValueError as e:
            raise Invalid(f"The token card can't be saved: {e}") from None
        _never_merge(action, dicts, old, new, at, bool(separate))
    untouched = [d for i, d in enumerate(dicts) if i != at]
    if action == "add":
        rows.append(TokenRow.make(new))
    elif action == "edit":
        rows[at] = rows[at].replace(**new)          # keeps the row's hidden id
    else:
        del rows[at]
    _guard([r.as_dict() for r in rows], untouched, new)
    after = inv.with_tokens(space, rows)
    index = None
    if new is not None:
        index = next(i for i, r in enumerate(after.token_set(space).rows) if _key(r.as_dict()) == _key(new))
    shown = new or old
    words = {"add": "Added", "edit": "Changed", "remove": "Removed"}[action]
    text = (f"{words} {rules.token_label(shown)} ×{shown['quantity']} "
            f"{'from' if action == 'remove' else 'in' if action == 'edit' else 'to'} {_whose(space)}")
    cards = sum(r.qty or 0 for r in after.token_set(space).rows)
    return after, Summary(text=text, counts={"cards": cards},
                          extra={"index": index, "resorted": not sheet.sorted,
                                 "body": [] if sheet.sorted else [RESORTED]})


@register("tokens.add")
def add(inv, space, sha256, row, separate=False):
    return _save(inv, "add", space, sha256, row=row, separate=separate)


@register("tokens.add_many")
def add_many(inv, space, sha256, rows):
    """Each of rows (1 to MAX_BATCH) added as tokens.add adds one, kept apart from any row naming
    the same card (separate: never merged), on one snapshot: one change. sha256 is the space's
    token list as the caller saw it; each later row is added against the list the one before it
    left. A row two fully known rows would share is refused (Conflict, naming its place in rows),
    as a single add's is; so is any other refusal, and nothing is saved."""
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= MAX_BATCH:
        raise Invalid(f"tokens.add_many needs 1 to {MAX_BATCH} rows")
    sheet = inv.token_set(space)
    before = sum(r.qty or 0 for r in sheet.rows) if sheet.exists else 0
    after, expected = inv, sha256
    for at, row in enumerate(rows, 1):
        try:
            after, _ = _save(after, "add", space, expected, row=row, separate=True)
        except Stale:
            raise
        except Conflict as e:
            raise Conflict(f"Token card {at}: {e}") from None
        except Invalid as e:
            raise Invalid(f"Token card {at}: {e}") from None
        now = after.token_set(space)
        expected = files.rendered_sha256(now)
    cards = sum(r.qty or 0 for r in after.token_set(space).rows)
    added = cards - before
    text = f"Added {added} token card{'' if added == 1 else 's'} in {len(rows)} rows to {_whose(space)}"
    return after, Summary(text=text, counts={"cards": cards, "added_cards": added, "added_rows": len(rows)},
                          extra={"resorted": sheet.exists and not sheet.sorted,
                                 "body": [RESORTED] if sheet.exists and not sheet.sorted else []})


@register("tokens.edit")
def edit(inv, space, sha256, base, row, separate=False):
    return _save(inv, "edit", space, sha256, base=base, row=row, separate=separate)


@register("tokens.remove")
def remove(inv, space, sha256, base):
    return _save(inv, "remove", space, sha256, base=base)
