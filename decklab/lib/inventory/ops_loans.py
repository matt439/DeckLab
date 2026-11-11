"""Audited exact-printing loose-card loans; no ownership transfer or borrower messages."""
import uuid
from collections import Counter

from decklab.lib import cards, decks, inventory, pool
from decklab.lib.state import Conflict, Invalid

from . import Op, Summary, loan_rules, register, rules

MISSING = "That open loan wasn't found. Refresh the loan list."


def rows_of(inv, space):
    sheet = inv.loan_set(space)
    if sheet.error or sheet.strict_error or sheet.problems:
        raise Invalid("The card loan records need checking before they can be changed.")
    return [row.as_dict() for row in sheet.rows]


def lent_counts(inv, space):
    return loan_rules.counts(rows_of(inv, space))


def holder(inv, space):
    counts = lent_counts(inv, space)
    if not counts:
        return []
    names = Counter()
    for physical, quantity in counts.items():
        names[physical[0]] += quantity
    return [pool.InUse(f"loans/{space}", "lent out", "lent out", names, recorded=counts)]


@register("collection.lend")
def lend(inv, *, space, row, sha256=None, loan_id=None):
    from .ops_collection import _rows, collection_name
    if not inv.loans_ready:
        raise Invalid(loan_rules.REQUIRED)
    existing = _rows(inv, space, sha256, collection_name(space))
    if not isinstance(row, dict) or set(row) != set(loan_rules.FIELDS) - {"id", "returned_on"}:
        raise Invalid("Give the loan's printing, quantity, borrower, lent date and notes")
    try:
        made = loan_rules.clean_row({**row, "id": uuid.uuid4().hex if loan_id is None else loan_id, "returned_on": ""})
    except (ValueError, TypeError) as error:
        raise Invalid(str(error)) from None
    if made["returned_on"]:
        raise Invalid("A new loan cannot already be returned")
    current = rows_of(inv, space)
    if any(item["id"] == made["id"] for item in current):
        raise Conflict("That loan ID already exists")
    physical = next((item for item in existing if rules.ident(item) == rules.ident(made)), None)
    if physical is None or physical["name"] != made["name"]:
        raise Invalid("Lend an exact printing already recorded in this collection")
    if decks.is_basic_land(made["name"]):
        raise Invalid("Basic-land allocations aren't tracked, so their free loose copies can't be confirmed")
    printed = cards.printing_card(made["set"], made["collector_number"])
    printing = cards.printing(made["set"], made["collector_number"])
    if not printed or printed["name"] != made["name"] or not printing or printing.get("digital") \
            or "paper" not in printing.get("games", []) or made["finish"] not in printing.get("finishes", []):
        raise Invalid("The loan's exact physical printing must be confirmed in the card index")
    with inventory.pinned(inv):
        supply = pool.for_space(space)
    if supply.warnings or supply.unresolved:
        raise Invalid(loan_rules.UNCONFIRMED)
    try:
        free = loan_rules.physical_free(existing, [item for item in supply.in_use if item.why != "lent out"],
                                        current, (made["name"], *rules.ident(made)))
    except ValueError:
        raise Invalid(loan_rules.UNCONFIRMED) from None
    if int(made["quantity"]) > free:
        raise Invalid(f"Only {free} copies of that printing are confirmed free; lend no more than that")
    after = inv.with_loans(space, [*current, made])
    return after, Summary(f"Lent {made['quantity']} {made['name']} ({made['set'].upper()} {made['collector_number']})",
                          {"cards": int(made["quantity"])}, extra={"loan": made})


@register("collection.return")
def return_loan(inv, *, space, loan_id, returned_on):
    if not inv.loans_ready:
        raise Invalid(loan_rules.REQUIRED)
    rows = rows_of(inv, space)
    found = next((row for row in rows if row["id"] == loan_id and not row["returned_on"]), None)
    if found is None:
        raise Conflict(MISSING)
    try:
        made = loan_rules.clean_row({**found, "returned_on": loan_rules.clean_date(returned_on, "Return date")})
    except ValueError as error:
        raise Invalid(str(error)) from None
    after = inv.with_loans(space, [made if row["id"] == loan_id else row for row in rows])
    return after, Summary(f"Returned {made['quantity']} {made['name']} ({made['set'].upper()} {made['collector_number']})",
                          {"cards": int(made["quantity"])}, extra={"loan": made})


def check_invariants(inv, only=None):
    """No collection writer may remove an owned printing that is still lent out."""
    for space in inv.loans:
        if only is not None and space not in only:
            continue
        counts = lent_counts(inv, space)
        sheet = inv.collection(space)
        if counts and (sheet.error or sheet.strict_error or sheet.problems):
            raise Invalid("The collection must be readable while cards are lent out")
        owned = Counter({(row.text("name"), *rules.ident(row)): row.qty for row in sheet.rows})
        if any(owned[key] is None or quantity > owned[key] for key, quantity in counts.items()):
            raise Invalid("This change would remove copies still lent out. Record their return first")


def check_holders(inv, only=None):
    """A newly built/recorded physical holder cannot consume copies that are away."""
    for space in inv.loans:
        if only is not None and space not in only:
            continue
        lent = lent_counts(inv, space)
        if not lent:
            continue
        with inventory.pinned(inv):
            supply = pool.for_space(space)
        if supply.warnings or supply.unresolved:
            raise Invalid("Physical card availability must be confirmed while cards are lent out")
        owned = Counter({(row.text("name"), *rules.ident(row)): row.qty for row in inv.collection(space).rows})
        owned_names, held, proven = Counter(), Counter(), Counter()
        for key, quantity in owned.items():
            owned_names[key[0]] += quantity
        for item in supply.in_use:
            if item.why == "lent out":
                continue
            if item.recorded_stale or item.standin_warnings:
                raise Invalid("Check the physical deck printings before changing holders while cards are lent out")
            held.update(item.cards)
            evidence = Counter(item.recorded)
            if item.why == "intact product":
                recorded_names = {key[0] for key in evidence}
                evidence.update({key: quantity for key, quantity in item.printings.items() if key[0] not in recorded_names})
            proven.update(evidence)
        lent_names = Counter()
        for key, quantity in lent.items():
            lent_names[key[0]] += quantity
        if any(held[name] + quantity > owned_names[name] for name, quantity in lent_names.items()) or any(
                proven[key] + quantity > owned[key] for key, quantity in lent.items()):
            raise Invalid("This holder would use copies still lent out. Record their return or choose other physical copies first")


def op(kind, **params):
    return Op("collection." + kind, params)
