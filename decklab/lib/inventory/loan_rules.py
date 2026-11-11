"""Loose-card loans: exact owned printings held outside the collection's storage.

These records never move ownership to a borrower or another space. Borrower and
notes are private space records; availability calculations use counts only.
"""
import re
from collections import Counter
from datetime import date

from . import rules

FIELDS = ("id", "name", "set", "collector_number", "finish", "quantity", "borrower", "lent_on", "returned_on", "notes")
BORROWER_MAX = 80
NOTES_MAX = 500
QUANTITY_MAX = 9999
REQUIRED = ("Card loans need the database's migration 0024 (python -m decklab.db migrate on the PC); "
            "until then they can't be recorded.")
UNCONFIRMED = "Free copies of that printing can't be confirmed. Check the collection and physical deck printings first."
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _line(value, label, maximum, required=False, formula_ok=False):
    if not isinstance(value, str) or _CONTROL.search(value):
        raise ValueError(f"{label} must be one line of text")
    value = value.strip()
    if len(value) > maximum or required and not value:
        raise ValueError(f"{label} must be {'1 to ' if required else 'at most '}{maximum} characters")
    if not formula_ok and value.startswith(("=", "+", "-", "@")):
        raise ValueError(f"{label} can't start with = + - or @")
    return value


def clean_date(value, label="Date"):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must be a real calendar date") from None
    return value


def clean_row(row):
    """A normalized complete record, including a stable non-personal ID."""
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise ValueError("A loan needs exactly its recorded fields")
    if not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["id"]):
        raise ValueError("The loan ID must be 32 lowercase hexadecimal characters")
    key = (row["set"], row["collector_number"], row["finish"])
    if (not all(isinstance(value, str) for value in key)
            or not re.fullmatch(r"[a-z0-9]{2,8}", key[0])
            or not re.fullmatch(r"[\w★†-]{1,16}", key[1]) or key[2] not in rules.FINISHES):
        raise ValueError("A loan needs an exact set, collector number and finish")
    qty = row["quantity"]
    if isinstance(qty, bool) or not isinstance(qty, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,3}", str(qty)):
        raise ValueError(f"Loan quantity must be a whole number from 1 to {QUANTITY_MAX}")
    lent = clean_date(row["lent_on"], "Lent date")
    returned = clean_date(row["returned_on"], "Return date") if row["returned_on"] else ""
    if returned and returned < lent:
        raise ValueError("Return date cannot be before the lent date")
    return {"id": row["id"], "name": _line(row["name"], "Card name", 200, True, formula_ok=True),
            "set": key[0], "collector_number": key[1], "finish": key[2], "quantity": str(qty),
            "borrower": _line(row["borrower"], "Borrower", BORROWER_MAX, True), "lent_on": lent,
            "returned_on": returned, "notes": _line(row["notes"], "Notes", NOTES_MAX)}


def sort_key(row):
    return row.get("lent_on", ""), row.get("id", "")


def problems(rows, where):
    out, seen = [], set()
    for number, row in enumerate(rows, 1):
        try:
            made = clean_row({key: row.get(key) for key in FIELDS})
            if made != {key: row.get(key) for key in FIELDS}:
                raise ValueError("the loan isn't written as Deck Lab keeps it")
            if made["id"] in seen:
                raise ValueError("the loan ID is repeated")
            seen.add(made["id"])
        except ValueError as error:
            out.append(f"{where(number)}: {error}")
    return out


def open_rows(rows):
    return [row for row in rows if not row.get("returned_on")]


def counts(rows):
    """Exact printing counts, with no borrower, note, date or loan identifier."""
    result = Counter()
    for row in open_rows(rows):
        result[(row["name"], *rules.ident(row))] += int(row["quantity"])
    return result


def physical_free(collection, holders, loans, key):
    """A lower bound on copies certainly loose, without guessing unlocated printings.

    Every unlocated physical holder may use the requested printing. Recorded
    Printings in box and intact product lists are authoritative; logical deck
    printing hints alone are not evidence of a physical allocation.
    """
    owned = Counter({})
    for row in collection:
        owned[(row["name"], *rules.ident(row))] += int(row["quantity"])
    name = key[0]
    held, proven = 0, Counter()
    for holder in holders:
        if holder.recorded_stale or holder.standin_warnings:
            raise ValueError(UNCONFIRMED)
        current = holder.cards.get(name, 0)
        if type(current) is not int or current < 0:
            raise ValueError(UNCONFIRMED)
        held += current
        evidence = Counter(holder.recorded)
        if holder.why == "intact product" and not any(physical[0] == name for physical in evidence):
            evidence.update({physical: quantity for physical, quantity in holder.printings.items() if physical[0] == name})
        for physical, quantity in evidence.items():
            if physical[0] == name:
                if type(quantity) is not int or quantity < 0:
                    raise ValueError(UNCONFIRMED)
                proven[physical] += quantity
    located = sum(quantity for physical, quantity in proven.items() if physical[0] == name)
    if located > held or any(quantity > owned[physical] for physical, quantity in proven.items()):
        raise ValueError(UNCONFIRMED)
    borrowed = counts(loans)
    total_owned = sum(quantity for physical, quantity in owned.items() if physical[0] == name)
    total_lent = sum(quantity for physical, quantity in borrowed.items() if physical[0] == name)
    unlocated = held - located
    return max(0, min(total_owned - held - total_lent, owned[key] - proven[key] - borrowed[key] - unlocated))
