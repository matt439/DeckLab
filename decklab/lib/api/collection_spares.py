"""Conservative, price-free spare copies from one space's saved collection and plans.

Only the calling space's owners/scripts may request this calculation. Printing
tags require proven physical holds; uncertain assignments export names only.
The caller supplies snapshots; this module performs no loading, writes, price,
network or permission checks.
"""
from collections import Counter, defaultdict

from decklab.lib import cards, decks
from decklab.lib.inventory import rules

UNAVAILABLE = "Spare copies can't be confirmed while this space's collection or saved plans need checking."
PRIVATE = "Spare copies depend on private plans, so they aren't available in this view."
UNCERTAIN = "Printing allocation is unconfirmed for untagged lines. Check the physical cards before trading."
COPY_LIMIT = 20000


def unavailable(message=UNAVAILABLE):
    return {"ready": False, "message": message, "rows": {}, "copy": None}


def _name(written):
    if decks.is_basic_land(written):
        return None
    exact = cards.resolve(written)
    if not exact:
        raise ValueError("Unconfirmed protected card")
    card = cards.card(exact)
    if not card or not any(printing and not printing.get("digital") and "paper" in printing.get("games", [])
                           for printing in (cards.printing(code, number) for code, number in card.get("printings", []))):
        raise ValueError("No confirmed physical card")
    return exact


def _key(name, code, number, finish):
    if not all(isinstance(value, str) and value for value in (code, number, finish)) or finish not in rules.FINISHES:
        return None
    return name, code.lower(), number, finish


def _lines(lines, counts, hints, canonical=_name):
    for line in lines:
        name = canonical(line.name)
        if name is None:
            continue
        if type(line.quantity) is not int or line.quantity <= 0:
            raise ValueError("Unconfirmed planned quantity")
        counts[name] += line.quantity
        key = _key(name, line.set or "", line.number or "", line.finish or "nonfoil")
        if key:
            hints[key] += line.quantity


def analyze(inv, supply, space, wishlist=()):
    """Counts by name are exact for the stated protections; no incoming copies are released.

    Planned and Considering quantities add across decks. A wishlist names no
    quantity, so it protects at least one total copy, without duplicating a
    copy already protected by a holder or plan. No title, note or source leaves here.
    """
    try:
        names = {}
        def canonical(written):
            if written not in names:
                names[written] = _name(written)
            return names[written]

        if supply.space != space or supply.warnings or supply.unresolved or supply.warning_decks or any(
                holder.standin_warnings or holder.recorded_stale for holder in supply.in_use):
            return unavailable()
        owned, printings, known = Counter(), Counter(), set()
        sheet = inv.collection(space)
        if sheet.error or sheet.problems:
            return unavailable()
        for row in sheet.rows:
            name = canonical(row.text("name"))
            if name is None:
                continue
            if row.qty is None:
                return unavailable()
            owned[name] += row.qty
            key = _key(name, row.text("set"), row.text("collector_number"), row.text("finish"))
            if key is None:
                return unavailable()
            printings[key] += row.qty
            printed = cards.printing_card(key[1], key[2])
            printing = cards.printing(key[1], key[2])
            if printed and cards.resolve(printed["name"]) == name and printing and key[3] in printing.get("finishes", []):
                known.add(key)
        held, proven = Counter(), Counter()
        for holder in supply.in_use:
            current = Counter()
            for written, quantity in holder.cards.items():
                name = canonical(written)
                if name is not None:
                    if type(quantity) is not int or quantity < 0:
                        return unavailable()
                    current[name] += quantity
            held.update(current)
            evidence = holder.recorded
            if holder.why == "intact product":
                recorded_names = {key[0] for key, quantity in evidence.items() if quantity > 0}
                evidence = Counter(evidence) + Counter({key: quantity for key, quantity in holder.printings.items()
                                                       if key[0] not in recorded_names})
            named = Counter()
            for key, quantity in evidence.items():
                if not isinstance(key, tuple) or len(key) != 4 or type(quantity) is not int or quantity < 0:
                    return unavailable()
                name = canonical(key[0])
                if name is None:
                    continue
                physical = _key(name, *key[1:])
                if physical is None:
                    return unavailable()
                proven[physical] += quantity
                named[name] += quantity
            if any(quantity > current[name] for name, quantity in named.items()):
                return unavailable()
        if any(quantity > owned[name] for name, quantity in held.items()) or any(
                quantity > printings[key] for key, quantity in proven.items()):
            return unavailable()
        planned, considering, hints = Counter(), Counter(), Counter()
        for record in inv.space_decks(space):
            if record.error or record.data is None:
                return unavailable()
            parsed = decks.parse_deck(record.data, record.slug, record.kind, space=space)
            if decks.trial_of(parsed) is not None:
                continue
            if parsed.status in (None, "idea", "building"):
                if not parsed.has_decklist:
                    return unavailable()
                _lines((line for lines in parsed.target.values() for line in lines), planned, hints, canonical)
            _lines(parsed.considering or [], considering, hints, canonical)
        wishes = {canonical(row["name"]) for row in wishlist}
        wishes.discard(None)
        exact_held = Counter()
        for key, quantity in proven.items():
            exact_held[key[0]] += quantity
        rows = {}
        grouped = defaultdict(list)
        for key in printings:
            grouped[key[0]].append(key)
        for name in sorted(owned, key=str.casefold):
            wishlist_keep = int(name in wishes and held[name] + planned[name] + considering[name] == 0)
            wanted = planned[name] + considering[name] + wishlist_keep
            spare = max(owned[name] - held[name] - wanted, 0)
            if not spare:
                continue
            pieces = [f"{owned[name]} owned", f"{held[name]} in built decks or intact products",
                      f"{planned[name]} wanted by building or idea decks"]
            if considering[name]:
                pieces.append(f"{considering[name]} kept for Considering")
            if wishlist_keep:
                pieces.append("1 kept for your wishlist")
            exact = []
            unlocated = held[name] - exact_held[name]
            physical_holds = Counter(proven)
            room = [key for key in grouped[name] if printings[key] > physical_holds[key]]
            # With only one remaining printing, conservation proves its allocation.
            if unlocated and len(room) == 1:
                physical_holds[room[0]] += unlocated
                unlocated = 0
            uncertain = unlocated > 0
            if not uncertain:
                available = {key: printings[key] - physical_holds[key] for key in sorted(grouped[name])}
                left = wanted
                for key in available:
                    take = min(left, available[key], hints[key])
                    available[key] -= take
                    left -= take
                for key in available:
                    take = min(left, available[key])
                    available[key] -= take
                    left -= take
                exact = [{"set": key[1], "collector_number": key[2], "finish": key[3], "quantity": quantity}
                         for key, quantity in available.items() if quantity > 0 and key in known]
            missing = spare - sum(row["quantity"] for row in exact)
            rows[name] = {"spare": spare, "planned": planned[name], "considering": considering[name],
                          "wishlist": wishlist_keep, "reason": ", ".join(pieces) + f": {spare} spare",
                          "printings": exact, "unallocated": missing, "printing_uncertain": missing > 0}
        return {"ready": True, "message": None, "rows": rows, "copy": None}
    except Exception:
        return unavailable()       # no raw deck errors, wishlist contents or hidden identities in the result


def export(rows):
    """Every matching spare name, not just the visible page; no prices or summary totals."""
    lines, uncertain = [], False
    for row in rows:
        facts = row["spares"]
        for printing in facts["printings"]:
            finish = {"foil": " *F*", "etched": " *E*"}.get(printing["finish"], "")
            lines.append(f"{printing['quantity']} {row['name']} ({printing['set'].upper()}) {printing['collector_number']}" + finish)
        if facts["unallocated"]:
            uncertain = True
            lines.append(f"{facts['unallocated']} {row['name']}")
    if len(lines) > COPY_LIMIT:
        return None
    text = ("# " + UNCERTAIN + "\n" if uncertain else "") + "\n".join(lines) + ("\n" if lines else "")
    if len(text.encode("utf-8")) > 2 * 1024 * 1024:
        return None
    return {"text": text,
            "printing_uncertain": uncertain}
