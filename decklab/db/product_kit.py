"""Typed CLI choices for an intact product's kit, using the pages' shared kit.set operation.

product kit STEM prints its current fields and the products status-list sha. set-kit needs
that sha (at least 12 hex characters), a nonblank message and one or both kit flags. An omitted
field stays as it is; ``none`` clears one. New values are accessory ids, never legacy free text.
The CLI sees every owner, as the other accessory commands do; a shared product still uses only
shared accessories. The actor affects attribution only. No card data or table refresh is needed.
"""
import json
import re
from dataclasses import dataclass

from decklab.lib import accessories, inventory
from decklab.lib.inventory import kit, rules

MIN_EXPECT = 12


def _row(inv, stem):
    if not isinstance(stem, str) or not rules.SLUG.fullmatch(stem) or stem == "status":
        raise ValueError(f"{stem!r} isn't a product id (lower-case letters, digits and hyphens)")
    sheet = inv.status
    if not sheet.exists:
        raise ValueError("The products list is missing.")
    if sheet.error is not None or sheet.strict_error is not None:
        raise ValueError(f"The products list can't be read: {sheet.error or sheet.strict_error}")
    index = kit.row_index(sheet, stem)
    if index is None:
        raise ValueError(f"There's no product {stem!r} in the products list.")
    return sheet.rows[index]


def show(args):
    """Print the product's kit and the concurrency token set-kit needs."""
    inv = inventory.current()
    row = _row(inv, args.stem)
    data = {"id": f"product/{args.stem}", "stem": args.stem,
            "name": accessories._product_title(inv, f"{args.stem}.csv"),
            **{key: row.text(key).strip() for key in ("status", "intact", "sleeves", "deck_box")},
            "sha256": kit.status_sha256(inv)}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"{data['id']}: {data['name']}")
        print(f"  status {data['status'] or '(unknown)'}, intact {data['intact'] or '(unknown)'}")
        print(f"  sleeves: {data['sleeves'] or 'none'}")
        print(f"  deck box: {data['deck_box'] or 'none'}")
        print(f"sha {data['sha256']} (give it to set-kit as --expect)")
    return 0


def _expected(inv, value):
    value = (value or "").strip().lower()
    if not re.fullmatch(f"[0-9a-f]{{{MIN_EXPECT},64}}", value):
        raise ValueError(f"--expect needs the sha product kit printed (at least its first {MIN_EXPECT} characters).")
    sha = kit.status_sha256(inv)
    if not sha.startswith(value):
        raise inventory.Conflict("The products list changed since that reading; run product kit again and retry.")
    return sha


def _choice(value):
    if value == "none":
        return None
    if not accessories.valid_id(value):
        raise ValueError(f"{value!r} isn't an accessory id; choose an id from accessories list, or none to clear it.")
    return value


@dataclass(frozen=True)
class _SetKit:
    """Require an owned intact product inside the same lock as the shared kit operation.

    kit.set permits clearing an old field on a holder that is no longer intact. This typed
    command deliberately handles intact products only, including when its requested change
    clears a field; rechecking here also covers a product broken up after the CLI's first read.
    """
    stem: str
    params: dict
    kind: str = "kit.set"

    def run(self, inv):
        row = _row(inv, self.stem)
        if not kit.can_hold(row):
            raise inventory.Invalid("Only an owned product kept intact can have its kit changed here.")
        return inventory.Op(self.kind, self.params).run(inv)


def save(args):
    """Preview or save strict accessory choices as one audited kit.set change."""
    from decklab.db import inv_orders
    from decklab.lib.inventory import ops_accessories  # noqa: F401 (registers kit.set)
    if not args.message.strip():
        raise ValueError("-m needs a message saying what this change does.")
    given = {field: getattr(args, field) for field in kit.FIELDS if getattr(args, field) is not None}
    if not given:
        raise ValueError("Give --sleeves, --deck-box, or both (none clears a field).")
    inv = inventory.current()
    _row(inv, args.stem)
    sha = _expected(inv, args.expect)
    holder = f"product/{args.stem}"
    sleeves = given.get("sleeves")
    sharing = accessories.sharing_warning(holder, _choice(sleeves)) if sleeves else None
    op = _SetKit(args.stem, {"holders": [{"id": holder, "expected": sha}], "owners": None,
                           "changes": [{"holder": holder, "field": field, "value": _choice(value)}
                                       for field, value in given.items()]})
    code = inv_orders._run(args, op)
    if sharing and code == 0:
        print(sharing)
    return code
