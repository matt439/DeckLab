"""Optional MTGJSON token candidates and explicit physical quantity/front choices.

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
    """Bind the file, ordered face/count offers and original public provenance."""
    value = ([candidate["source"], candidate["options"], candidate["provenance_sha256"]]
             if "options" in candidate else offered_rows(candidate))
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _declared(data, source):
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


UNCHECKED = "Token names cannot be checked against the local card data yet."
BAD_NAME = "This token entry needs one or two checked face names before its physical cards can be chosen."


def _checked_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80 or any(c in value for c in "\r\n\0"):
        raise ValueError(BAD_NAME)
    row = {key: "" for key in rules.TOKEN_FIELDS}
    row.update(front=value.strip(), quantity="1")
    row = rules.token_page_row(row)
    try:
        row, warnings = names.check_names(row)
    except cards.INDEX_ERRORS:
        raise ValueError(UNCHECKED) from None
    if warnings:
        raise ValueError(UNCHECKED)
    return row["front"]


def _fronts(item):
    """Checked front choices for ONE source entry; no reverse or quantity inference."""
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 164 or any(c in name for c in "\r\n\0"):
        raise ValueError(BAD_NAME)
    parts = name.split("//")
    if len(parts) > 2:
        raise ValueError(BAD_NAME)
    fronts = []
    for part in parts:
        exact = _checked_name(part)
        # A local canonical full name may itself name a double-faced token.
        faces = exact.split("//")
        if len(faces) > 2:
            raise ValueError(BAD_NAME)
        for face in faces:
            checked = _checked_name(face)
            if "//" in checked:
                raise ValueError(BAD_NAME)
            if checked not in fronts:
                fronts.append(checked)
    if not 1 <= len(fronts) <= 2:
        raise ValueError(BAD_NAME)
    face_name = item.get("faceName")
    if face_name not in (None, ""):
        face = _checked_name(face_name)
        if face not in fronts:
            raise ValueError(BAD_NAME)
        fronts = [face]
    return name.strip(), fronts


def candidates(data, source):
    """Legacy declared rows plus explicit physical choices for every source entry.

    Legacy rows/problems are unchanged. Missing counts and checked ambiguous fronts
    can be confirmed through options; malformed metadata or unchecked names cannot.
    An absent/empty token list keeps the original empty result (there is no offer).
    """
    result = _declared(data, source)
    raw = data.get("tokens")
    if raw is None or isinstance(raw, list) and not raw:
        return result
    options, problems = [], []
    if not isinstance(raw, list) or len(raw) > MAX_ROWS:
        problems = list(result["problems"])
    else:
        for index, item in enumerate(raw, 1):
            option = {"source_row": index, "source_name": "", "fronts": [], "quantity": None}
            options.append(option)
            if not isinstance(item, dict):
                problems.append({"line": index, "message": "This token entry is not an object."})
                continue
            option["quantity"] = precons._count(item)
            try:
                option["source_name"], option["fronts"] = _fronts(item)
            except ValueError as error:
                problems.append({"line": index, "message": str(error)})
            except cards.INDEX_ERRORS:
                problems.append({"line": index, "message": UNCHECKED})
    try:
        text = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if len(options) else ""
        provenance = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, OverflowError):
        provenance = ""
        problems.append({"line": None, "message": "The token source metadata cannot be read."})
    result.update(source=source, options=options, choices_ready=bool(options) and not problems,
                  choice_problems=problems, provenance_sha256=provenance)
    return result


def resolve(candidate, source, choices):
    """Use one explicit physical quantity/front (or zero skip) for EVERY source row.

    Returns candidate-shaped data with chosen separate rows and independent counts.
    The original source receipt stays unchanged. No duplicate entries are merged.
    """
    options = candidate.get("options", [])
    if not candidate.get("choices_ready") or candidate.get("choice_problems") or not options:
        raise ValueError("The precon's token source needs checking before physical cards can be chosen.")
    if source != candidate.get("source"):
        raise ValueError("Preview the precon's token source again before choosing its physical cards.")
    if not isinstance(choices, list) or len(choices) != len(options):
        raise ValueError("Choose a physical quantity or zero to skip every source token entry exactly once.")
    expected = {option["source_row"]: option for option in options}
    selected = {}
    for choice in choices:
        if not isinstance(choice, dict) or set(choice) != {"source_row", "front", "quantity"}:
            raise ValueError("Each token choice needs its source row, front and physical quantity.")
        index, front, quantity = choice["source_row"], choice["front"], choice["quantity"]
        if not isinstance(index, int) or isinstance(index, bool) or index not in expected or index in selected:
            raise ValueError("Choose each offered source token entry exactly once.")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or not 0 <= quantity <= precons.MAX_COUNT:
            raise ValueError(f"A physical token quantity must be a whole number from 0 to {precons.MAX_COUNT}.")
        if not isinstance(front, str) or quantity > 0 and front not in expected[index]["fronts"]:
            raise ValueError("Choose an offered front name for every physical token card being added.")
        selected[index] = (front, quantity)
    if set(selected) != set(expected):
        raise ValueError("Choose each offered source token entry exactly once.")
    rows = []
    for option in options:
        index = option["source_row"]
        front, quantity = selected[index]
        if not quantity:
            continue
        checked = _checked_name(front)
        if checked != front or "//" in checked:
            raise ValueError("Preview the checked front names again before adding physical token cards.")
        declared = (f"source-declared quantity {option['quantity']}" if option["quantity"] is not None
                    else "source physical quantity unknown")
        row = {key: "" for key in rules.TOKEN_FIELDS}
        row.update(front=front, quantity=str(quantity), notes=f"MTGJSON {source}, token entry {index}; "
                   f"user-confirmed physical quantity {quantity}; {declared}; "
                   "printing and reverse face unconfirmed; check physical pairing.")
        rows.append({"source_row": index, "row": rules.token_page_row(row)})
    if not rows:
        raise ValueError("Leave token cards unchecked to add this precon without physical token cards.")
    return {**candidate, "rows": rows, "cards": sum(int(item["row"]["quantity"]) for item in rows), "problems": []}
