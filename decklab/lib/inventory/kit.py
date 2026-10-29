"""The phase 3 inventory operation that records an intact product's sleeves and deck box: the
sleeves and deck_box columns of its products/status.csv row (the phase 3 design's P4 and amendment
Q8), and the helpers phase 4's kit.set uses (status_sha256, row_index, can_hold). Since phase 4
the pages write every holder's kit, decks and products alike, with kit.set
(ops_accessories.py) in one operation; product.set-kit is kept for older callers and tests.

    from decklab.lib import inventory
    from decklab.lib.inventory import kit
    inventory.apply(inventory.Op(kit.KIND, {"sha256": sha, "changes": [
        {"stem": "challenger-2019-lightning-aggro", "field": "sleeves", "value": "dragon-shield-matte-black"}],
        "hold": "challenger-2019-lightning-aggro"}), actor, "set sleeves for Lightning Aggro")

sha256 is the sha256 of status.csv as the page loaded it, rendered from the snapshot
(status_sha256() here, which both the Accessories page and the deck page send as holder_sha256):
the operation refuses when the products list has changed since. changes are made in order;
"expect" on a change applies it only while the row still holds that value (a move takes sleeves
from a product only if it still has them). hold names the product that must be owned and kept
intact (the one given sleeves or a deck box; clearing works on any row).

The refusals are KitRefused (a state.Conflict) carrying the HTTP status today's page answers
with, so the page words them as it always has; reason "changed" is the products list changing
since the page loaded it, for which the page builds its "who changed it" answer.
"""
from decklab.lib.state import Conflict

from . import Summary, files, paths, register

KIND = "product.set-kit"
FIELDS = ("sleeves", "deck_box")
CANT_HOLD = "Only a built deck or a product kept intact has sleeves or a deck box"
# How refusals name the products' statuses (the database's product_status rows, not the old
# products/status.csv) and a product without one (by the stem product kit takes).
STATUS_WORDS = "The products' status list"


def no_status(stem):
    return f"Product {stem} has no status"


class KitRefused(Conflict):
    """The kit can't be set: code is the HTTP status the page answers with (404, 409 or 400);
    reason is "changed" when status.csv changed since the page loaded it, else None."""

    def __init__(self, message, code=409, reason=None):
        super().__init__(message)
        self.code = code
        self.reason = reason


def status_sha256(inv):
    """The sha256 of inv's products/status.csv as rendered (what the pages send back as a
    product's holder_sha256); the sha256 of no bytes when there's no file."""
    return files.rendered_sha256(inv.status)


def row_index(sheet, stem):
    """The index of the first status row for <stem>.csv (its file stripped), or None."""
    name = f"{stem}.csv"
    return next((i for i, row in enumerate(sheet.rows) if row.text("file").strip() == name), None)


def can_hold(row):
    """Whether a status row is owned and kept intact, normalised as pool.read_status reads it (so
    a hand-written " Owned ,Yes" holds too)."""
    return row.text("status").strip().lower() == "owned" and row.text("intact").strip().lower() == "yes"


@register(KIND)
def set_kit(inv, *, sha256=None, changes=(), hold=None):
    """The operation (see the module docstring). Refuses in today's order: no status.csv (404),
    one the OS wouldn't read (500), one changed since the page loaded it (409, reason
    "changed"), one a strict read refuses (409), a product it doesn't list (404), and sleeves or
    a deck box for a product that isn't owned and kept intact (400)."""
    sheet = inv.status
    name = STATUS_WORDS
    if not sheet.exists:
        raise KitRefused(f"{name} is missing", 404)
    if sheet.error is not None:
        raise KitRefused(f"{name} can't be read: {sheet.error}", 500)
    if sha256 is not None and status_sha256(inv) != sha256:
        raise KitRefused("The products list changed after you opened it.", 409, "changed")
    if sheet.strict_error is not None:
        raise KitRefused(f"{name} can't be read: {sheet.strict_error}", 409)
    rows = list(sheet.rows)
    done = []
    for change in changes:
        stem, field, value = change["stem"], change["field"], change.get("value")
        if field not in FIELDS:
            raise ValueError(f"a product's kit has no field {field!r}")
        i = row_index(sheet, stem)
        if i is None:
            raise KitRefused(no_status(stem), 404)
        if "expect" in change and rows[i].text(field).strip() != (change["expect"] or ""):
            continue
        if stem == hold and value is not None and not can_hold(rows[i]):
            raise KitRefused(CANT_HOLD, 400)
        rows[i] = rows[i].replace(**{field: value or ""})
        done.append(f"{field} of {stem}")
    if not done:
        return inv, Summary("Nothing to change")
    return inv.with_status_rows(rows), Summary(f"Set the {', '.join(done)}", {"rows": len(done)},
                                               {paths.STATUS: done})
