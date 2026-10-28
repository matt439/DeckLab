"""Informational destinations for actually added CSV-import or precon physical copies.

The locked additive operation supplies JSON-only printing deltas. The caller supplies its
exact saved snapshot, never a later load. An import changes no holds, decks or incoming stock,
so one saved pool also describes prior physical stock after subtracting those deltas. Prior
free copies are consumed globally before any new copy is suggested for a waiting deck.
A precon additionally proves its newly created deck, reserving its physical recipe first.
This never assigns cards, changes a deck or reads/writes a notice or kit.
"""
from collections import Counter, defaultdict

from decklab.lib import cards, decks, inventory, pool
from decklab.lib.inventory import rules

from . import guard

MAX_ADDED_ROWS = 20000
MAX_DECKS = 200
MAX_WORK = 200000
MAX_DESTINATIONS = 20000
UNKNOWN = "Destination unknown. The import was saved; check where these copies belong."
PRECON_UNKNOWN = "Destination unknown. The precon was saved; check where these copies belong."
ROW_FIELDS = ("name", "set", "collector_number", "finish")


def _public_added(facts):
    """Bounded JSON-only printing rows, without the operation's before/after proof fields."""
    if not isinstance(facts, list) or len(facts) > MAX_ADDED_ROWS:
        return []
    if any(not isinstance(row, dict) or any(not isinstance(row.get(key), str) for key in ROW_FIELDS)
           or type(row.get("quantity")) is not int or row["quantity"] <= 0 for row in facts):
        return []
    return [{**{key: row[key] for key in ROW_FIELDS}, "quantity": row["quantity"]} for row in facts]


def unknown(space, profile, facts, total):
    """A safe successful-save fallback: never infer that unchecked copies go to storage."""
    added = _public_added(facts)
    destinations = ([{"kind": "unknown", "row": i, "quantity": row["quantity"]}
                     for i, row in enumerate(added)] if len(added) <= MAX_DESTINATIONS else [])
    return {"space": space, "profile": profile["id"], "status": "unknown", "cards": total,
            "added": added, "destinations": destinations, "message": UNKNOWN}


def _validated_added(after, space, facts, total):
    added = _public_added(facts)
    if not added or len(added) != len(facts) or type(total) is not int \
            or sum(row["quantity"] for row in added) != total:
        raise ValueError("Unconfirmed additions")
    current = {rules.ident(row): row for row in after.collection(space).rows}
    seen = set()
    for row, fact in zip(added, facts):
        key = rules.ident(row)
        saved = current.get(key)
        before, now = fact.get("before_quantity"), fact.get("after_quantity")
        if key in seen or saved is None or saved.name != row["name"] or type(before) is not int \
                or type(now) is not int or before < 0 or now - before != row["quantity"] or saved.qty != now:
            raise ValueError("Unconfirmed printing delta")
        seen.add(key)
    return added


def _candidate_decks(after, space, profile, work):
    records = after.space_decks(space)
    if len(records) > MAX_DECKS:
        raise ValueError("Too many candidate decks")
    sees = guard.deck_reader(profile)
    candidates = []
    for record in records:
        if record.kind not in ("casual", "commander"):
            continue
        if record.error is not None or record.data is None or not sees(record.id):
            raise ValueError("A candidate deck is unavailable")
        work[0] += record.text.count("\n") + 1
        if work[0] > MAX_WORK:
            raise ValueError("Too much filing work")
        parsed = decks.parse_deck(record.data, record.slug, record.kind, space=space)
        if not parsed.has_decklist:
            raise ValueError("A candidate has no Planned list")
        work[0] += sum(len(lines) for lines in parsed.target.values())
        if work[0] > MAX_WORK:
            raise ValueError("Too much filing work")
        candidates.append(({"id": record.id, "title": parsed.title, "status": parsed.status or "idea"}, parsed.target))
    rank = {"built": 0, "building": 1}
    return sorted(candidates, key=lambda item: (rank.get(item[0]["status"], 2), item[0]["id"]))


def _created_deck(after, space, profile, proof):
    """The actual newly created deck; planned identities and other spaces aren't evidence."""
    if not isinstance(proof, dict) or proof.get("was_absent") is not True or proof.get("space") != space:
        raise ValueError("Unconfirmed new deck")
    record = after.deck(proof.get("id"))
    if record is None or record.space != space or record.kind not in ("casual", "commander") \
            or record.error is not None or not record.sha256 or record.sha256 != proof.get("sha256") \
            or not guard.sees_deck(record.id, profile):
        raise ValueError("The new deck could not be confirmed")
    parsed = decks.parse_deck(record.data, record.slug, record.kind, space=space)
    if not parsed.has_decklist:
        raise ValueError("The new deck has no Planned list")
    return {"id": record.id, "title": parsed.title, "status": parsed.status or "idea"}


def _allocate(after, space, profile, added, created=None):
    """Allocate names globally, then spend each exact printing's quantity only once."""
    work = [len(added) + len(after.collection(space).rows)]
    if work[0] > MAX_WORK:
        raise ValueError("Too much filing work")
    candidates = _candidate_decks(after, space, profile, work)
    found = pool.load_pool(space)
    if found.space != space or found.warnings or found.unresolved:
        raise ValueError("Incomplete physical pool")
    if created is not None and created["status"] == "built":
        holders = [holder for holder in found.in_use if holder.id == created["id"]]
        if len(holders) != 1 or holders[0].why != "built":
            raise ValueError("The new built deck's physical recipe is unavailable")
    added_by_name = Counter()
    indices = defaultdict(list)
    for i, row in enumerate(added):
        if decks.is_basic_land(row["name"]) or cards.resolve(row["name"]) != row["name"]:
            raise ValueError("Physical destinations aren't tracked for this name")
        added_by_name[row["name"]] += row["quantity"]
        indices[row["name"]].append(i)
    held = Counter()
    own = defaultdict(Counter)
    for holder in found.in_use:
        for name, quantity in holder.cards.items():
            work[0] += 1
            if type(quantity) is not int or quantity < 0 or work[0] > MAX_WORK:
                raise ValueError("Unconfirmed physical holdings")
            held[name] += quantity
            own[holder.id][name] += quantity
    if created is not None and created["status"] != "built" and any(own[created["id"]].values()):
        raise ValueError("An unbuilt new deck unexpectedly holds cards")
    def physical_stock(name):
        incoming_rows = found.on_the_way.get(name, ())
        if any(type(quantity) is not int or quantity < 0 for _, quantity in incoming_rows):
            raise ValueError("Unconfirmed incoming copies")
        owned = found.owned.get(name, 0)
        if type(owned) is not int or owned < 0:
            raise ValueError("Unconfirmed owned copies")
        return owned - sum(quantity for _, quantity in incoming_rows)

    if created is not None:
        for name in own[created["id"]]:
            if name not in added_by_name and physical_stock(name) < held[name]:
                raise ValueError("The new deck's other physical cards are not all present")
    prior, reserved = {}, {}
    for name, added_quantity in added_by_name.items():
        physical = physical_stock(name)
        before = physical - added_quantity
        new_hold = own[created["id"]][name] if created is not None and created["status"] == "built" else 0
        reserved[name] = min(new_hold, added_quantity)
        # Source additions go with the newly created built precon first. Any part of its
        # physical recipe they cannot supply consumes prior free stock; older holds stay fixed.
        prior_required = held[name] - new_hold + (new_hold - reserved[name])
        if before < prior_required:
            raise ValueError("Physical stock does not cover its recorded holdings")
        prior[name] = before - prior_required
    remaining = [row["quantity"] for row in added]
    heads = defaultdict(int)
    out = []

    def spend(name, quantity, destination):
        choices = indices[name]
        while quantity:
            work[0] += 1
            if work[0] > MAX_WORK or len(out) >= MAX_DESTINATIONS:
                raise ValueError("Filing result is too large")
            index = choices[heads[name]]
            give = min(quantity, remaining[index])
            if give:
                out.append({**destination, "row": index, "quantity": give})
                remaining[index] -= give
                quantity -= give
            if not remaining[index]:
                heads[name] += 1

    new_left = Counter(added_by_name)
    if created is not None:
        for name, quantity in reserved.items():
            if quantity:
                spend(name, quantity, {"kind": "deck", "deck": created})
                new_left[name] -= quantity
    for deck, sections in candidates:
        result = pool.compare(sections, found, pool.self_ids(deck["id"]), prices=False)
        if result["unresolved"] or result["warnings"]:
            raise ValueError("A candidate's needs are incomplete")
        work[0] += len(result["rows"])
        if work[0] > MAX_WORK:
            raise ValueError("Too much filing work")
        for row in result["rows"]:
            name = row["name"]
            if name not in added_by_name:
                continue
            if type(row["need"]) is not int or row["need"] < 0:
                raise ValueError("Unconfirmed deck demand")
            need = max(row["need"] - own[deck["id"]][name], 0)
            existing = min(need, prior[name])
            prior[name] -= existing
            give = min(need - existing, new_left[name])
            if give:
                spend(name, give, {"kind": "deck", "deck": deck})
                new_left[name] -= give
    for name, quantity in new_left.items():
        if quantity:
            spend(name, quantity, {"kind": "storage"})
    if any(remaining):
        raise ValueError("Unaccounted additions")
    return out


def after_import(after, space, profile, facts, total):
    """Never raise for optional advice after a committed import; only its exact snapshot is read."""
    authorized = False
    try:
        with inventory.pinned(after):
            if not guard.sees_inventory(space, profile):
                return unknown(space, profile, None, 0)
            authorized = True
            added = _validated_added(after, space, facts, total)
            destinations = _allocate(after, space, profile, added)
        return {"space": space, "profile": profile["id"], "status": "ready", "cards": total,
                "added": added, "destinations": destinations}
    except Exception:           # advice is optional; saved cards and raw imports remain saved
        return unknown(space, profile, facts if authorized else None, total if authorized else 0)


def after_precon(after, space, profile, facts, total, proof):
    """A saved precon also created a holder; only its exact locked proof relaxes prior holds."""
    authorized = False
    try:
        with inventory.pinned(after):
            if not guard.sees_inventory(space, profile):
                return unknown(space, profile, None, 0)
            authorized = True
            added = _validated_added(after, space, facts, total)
            created = _created_deck(after, space, profile, proof)
            destinations = _allocate(after, space, profile, added, created)
        return {"space": space, "profile": profile["id"], "status": "ready", "cards": total,
                "added": added, "destinations": destinations}
    except Exception:
        answer = unknown(space, profile, facts if authorized else None, total if authorized else 0)
        answer["message"] = PRECON_UNKNOWN
        return answer
