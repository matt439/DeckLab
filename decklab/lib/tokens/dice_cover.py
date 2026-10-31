"""Whether a space's owned dice and counters (E7-S24; inventory dice_rules) cover the counters and
dice a deck's cards call for (counters.deck_counters). Part of decklab.lib.tokens.

Approximate, as the needs are, and never a count of how many a game needs:
- a die the cards roll (d6, d20, ...) is covered by owned dice of that size (a spindown counts as
  a d20); a size the records don't have (d100) is never covered, and says it can't be recorded;
- a counter kind is covered first by counters recorded as that kind ("+1/+1", "poison"); every
  kind left takes one generic item each, in the needs' order, while any are left: a die (of any
  size) or a counter with no kind, which stand for any kind.

cover(counters, rows) returns a copy: each need gains "cover" {state: "named" | "generic" | "none",
words}, and the result "owned" {ready, dice, counters, generic, words}. Before the database can
record dice and counters (ready False) the needs are left as they are and owned says why.
"""
import copy

from decklab.lib.inventory.dice_rules import SIZES

STATES = ("named", "generic", "none")
NOT_READY = ("Dice and counters can't be recorded yet: the database needs its migration 0020, so whether "
             "these are covered isn't shown.")
NONE_RECORDED = "No dice or counters are recorded: add them on the Tokens page."
UNRECORDABLE = "Deck Lab doesn't record {size}s (it records d4 to d20 and spindowns)"


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _items(rows):
    out = []
    for row in rows or ():
        try:
            quantity = int(str(row.get("quantity") or "0").strip())
        except ValueError:
            continue
        if quantity > 0:
            out.append({**row, "quantity": quantity})
    return out


def cover(counters, rows, ready=True):
    """counters (deck_counters' {needs, note}) with whether rows (the space's dice and counters, as
    dicts of dice_rules.DICE_FIELDS) cover each need (see the module docstring)."""
    out = copy.deepcopy(counters) if isinstance(counters, dict) else {"needs": []}
    if not ready:
        out["owned"] = {"ready": False, "dice": 0, "counters": 0, "generic": 0, "words": NOT_READY}
        return out
    items = _items(rows)
    dice = sum(r["quantity"] for r in items if r.get("type") == "die")
    counters_owned = sum(r["quantity"] for r in items if r.get("type") == "counter")
    generic = dice + sum(r["quantity"] for r in items if r.get("type") == "counter" and not r.get("kind"))
    left = generic
    for need in out.get("needs", []):
        key = need.get("key") or ""
        if need.get("group") == "die":
            if key not in SIZES:
                need["cover"] = {"state": "none", "words": UNRECORDABLE.format(size=key)}
                continue
            sizes = {key, "spindown"} if key == "d20" else {key}
            have = sum(r["quantity"] for r in items if r.get("type") == "die" and r.get("size") in sizes)
            need["cover"] = ({"state": "named", "words": f"You have {_plural(have, key)}"} if have
                             else {"state": "none", "words": f"No {key} recorded"})
            continue
        have = sum(r["quantity"] for r in items if r.get("type") == "counter" and (r.get("kind") or "") == key)
        if have:
            need["cover"] = {"state": "named", "words": f"You have {_plural(have, f'{key} counter')}"}
        elif left > 0:
            left -= 1
            need["cover"] = {"state": "generic", "words": "A die or generic counter stands in"}
        else:
            need["cover"] = {"state": "none", "words": f"No {key} counters, and no spare die or generic counter"}
    words = (NONE_RECORDED if not items else
             f"You have {_plural(dice, 'die', 'dice')} and {_plural(counters_owned, 'counter')}; "
             f"{_plural(generic, 'stands', 'stand')} for any kind.")
    out["owned"] = {"ready": True, "dice": dice, "counters": counters_owned, "generic": generic, "words": words}
    return out
