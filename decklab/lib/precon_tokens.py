"""Optional MTGJSON token candidates: declared quantities, with physical facts still unconfirmed.

The public source need not provide physical quantities. Missing counts never mean one, and
combined face names are never split into additional cards. Rows stay separate by source entry.
"""
import hashlib
import json

from decklab.lib import cards, precons
from decklab.lib.inventory import rules
from decklab.lib.state import Conflict
from decklab.lib.tokens import names

MAX_ROWS = 250                  # optional batch: no unbounded repeated token-row additions


class TokenConflict(Conflict):
    """The token part of an otherwise atomic precon add needs a fresh preview."""


def offered_rows(candidate):
    return [{"front": item["row"]["front"], "quantity": int(item["row"]["quantity"]),
             "source_row": item["source_row"], "notes": item["row"]["notes"]} for item in candidate["rows"]]


def source_sha256(candidate):
    """A review receipt for the exact public source rows offered, not a physical verification."""
    text = json.dumps(offered_rows(candidate), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidates(data, source):
    """{rows, cards, problems}; rows contain {row, source_row} in the public source's order.

    Only explicit bounded counts and checked single-face names can be offered. A problem in
    any entry blocks the whole optional batch, without blocking the ordinary playable precon.
    """
    raw = data.get("tokens")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return {"rows": [], "cards": 0, "problems": [{"line": None, "message": "MTGJSON's token cards are not a list."}]}
    if len(raw) > MAX_ROWS:
        return {"rows": [], "cards": 0, "problems": [{"line": None, "message": "The source lists too many token entries to add together."}]}
    rows, problems = [], []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            problems.append({"line": index, "message": "This token entry is not an object; its physical quantity is unknown."})
            continue
        count = precons._count(item)
        if count is None:
            problems.append({"line": index, "message": "This token's physical quantity is unknown: the source needs an explicit "
                             f"whole count from 1 to {precons.MAX_COUNT}."})
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or "//" in name:
            problems.append({"line": index, "message": "This token needs one unambiguous face name; combined names are not split into physical cards."})
            continue
        row = {key: "" for key in rules.TOKEN_FIELDS}
        row.update(front=name, quantity=str(count), notes=f"MTGJSON {source}, token entry {index}; declared quantity {count}; "
                   "printing and reverse face unconfirmed; check physical pairing.")
        try:
            row = rules.token_page_row(row)
            try:
                row, warnings = names.check_names(row)
            except cards.INDEX_ERRORS:
                # ValueError can be an index decode failure as well as an unknown face.
                # Keep that boundary static, while row-rule failures remain useful below.
                raise ValueError("Token names cannot be checked against the local card data yet.") from None
            if warnings:
                raise ValueError("Token names cannot be checked against the local card data yet.")
            if "//" in row["front"]:
                raise ValueError("Combined token names are not split into physical cards.")
            row = rules.token_page_row(row)
        except ValueError as problem:
            problems.append({"line": index, "message": str(problem)})
            continue
        except cards.INDEX_ERRORS:
            problems.append({"line": index, "message": "Token names cannot be checked against the local card data yet."})
            continue
        rows.append({"row": row, "source_row": index})
    return {"rows": rows, "cards": sum(int(item["row"]["quantity"]) for item in rows), "problems": problems}
