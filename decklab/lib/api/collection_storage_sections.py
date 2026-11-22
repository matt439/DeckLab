"""Expected physical sections for a Collection storage map, from one pinned inventory."""
from collections import Counter
from hashlib import sha256
import json
import math
import re

from decklab.lib import cards, inventory, tokens
from decklab.lib.inventory import rules
from decklab.lib.state import collection_audits, space_storage

from . import collection_edit as collection, collection_locations
from .common import ApiError

COLOURS = ("White", "Blue", "Black", "Red", "Green", "Multicolour", "Colourless")
DIVIDERS = tuple((f"{colour} {group}", group, colour.lower())
                 for group in ("creatures", "spells", "lands") for colour in COLOURS)
DIVIDERS = (*DIVIDERS[:7], ("Artifact creatures", "creatures", "artifact"),
            *DIVIDERS[7:14], ("Artifacts", "spells", "artifact"), *DIVIDERS[14:],
            ("Token cards", "tokens", None), ("Other cards", None, None))
TOKENS, OTHER = 23, 24


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _colour(values):
    colours = [value for value in values or () if value in ("W", "U", "B", "R", "G")]
    return 5 if len(colours) > 1 else "WUBRG".index(colours[0]) if colours else 6


def _divider(card):
    # Match the filing order in web/storage-order.js, including front faces, artifact lands and coloured artifacts.
    card = card or {}
    face = (card.get("faces") or [card])[0]
    type_line = face.get("type_line") or card.get("type_line") or ""
    types = re.split(r"\s[—–-]\s", type_line.split(" // ")[0], maxsplit=1)[0].split()
    if not types:
        return OTHER
    if "Land" in types:
        mana = card.get("produced_mana") or ()
        return 16 + _colour(mana if set(mana).intersection("WUBRG") else card.get("color_identity"))
    offset = 0 if "Creature" in types else 8
    if "Artifact" in types:
        return offset + 7
    colours = face.get("colors")
    return offset + _colour(card.get("colors") if colours is None else colours)


def _section(container, place, divider):
    if container is None:
        label = "Other recorded locations" if place else "No storage location"
        return {"id": digest([None, place]), "label": label, "container": None, "place": None,
                "colour": None, "auditable": False, "rows": []}
    name = container["name"]
    label, _, colour = DIVIDERS[divider] if divider is not None else (place or name, None, None)
    return {"id": digest([container["id"], place, divider]), "label": label, "container": name, "place": place,
            "colour": colour, "auditable": True, "rows": []}


def _rank(container, place, divider):
    sections = container["sections"] if container else []
    return (sections.index(place) if place in sections else len(sections), -1 if divider is None else divider)


def _filing(record, seen):
    containers = {c["id"]: c for c in record["containers"]}
    by_container = {ident: {} for ident in (*containers, None)}
    groups = {ident: space_storage.group_sections(c) for ident, c in containers.items()}

    def section(ident, place, divider):
        bucket = by_container[ident]
        key = (place, divider)
        if key not in bucket:
            bucket[key] = _section(containers.get(ident), place, divider)
        return bucket[key]

    for ident, c in containers.items():
        if c["order"] != "colour-type":
            for place in c["sections"] or [None]:
                section(ident, place, None)
            if c["sections"] and _section(c, None, None)["id"] in seen:
                section(ident, None, None)
            continue
        for divider, (_, group, _) in enumerate(DIVIDERS):
            usual = groups[ident].get(group)
            if divider != OTHER:
                section(ident, usual, divider)
            # Retain a previous audit when a manually placed divider now has zero cards.
            for place in (*c["sections"], None):
                if place != usual and _section(c, place, divider)["id"] in seen:
                    section(ident, place, divider)
            if divider == OTHER and _section(c, usual, divider)["id"] in seen:
                section(ident, usual, divider)

    def destination(location, divider):
        ident, place = space_storage.match_section(record, location)
        if ident is None:
            return section(None, "recorded" if location else None, None)
        if containers[ident]["order"] == "colour-type":
            place = place or groups[ident].get(DIVIDERS[divider][1])
            return section(ident, place, divider)
        return section(ident, place, None)

    def ordered():
        for ident, bucket in by_container.items():
            for (place, divider), entry in sorted(bucket.items(), key=lambda item: _rank(containers.get(ident), *item[0])):
                yield entry, containers[ident]["order"] if ident else "none"

    return destination, ordered


def _storage_rows(space, rows):
    # The Card list allocates recorded printings, list printing hints and then the cheapest
    # copies. Use the stored USD prices for the last step, keeping exchange-rate I/O out of the audit.
    prices = {}
    for row in rows:
        price = cards.printing_usd(row["set"], row["collector_number"], row["finish"])
        if price is not None:
            prices[collection._picture_key(row)] = {"aud": price}
    storage = collection._storage(space, rows, {"rows": prices}, sources=False)
    if storage["error"]:
        raise ApiError(409, "The loose card counts couldn't be worked out. Check the collection and card data.")
    return storage


def _token_scan_label(row):
    faces = []
    for side in ("front", "back"):
        if row[side]:
            number = row[f"{side}_collector_number"]
            faces.append(" · ".join(filter(None, (row[side], f"#{number}" if number else "", row[f"{side}_details"]))))
    return " · ".join(filter(None, (" / ".join(faces), row["set"].upper(), row["finish"])))


def _token_rows(space):
    token_list = tokens.read(space=space)
    warnings = list(token_list.problems)
    holds = tokens.reserve.holds(token_list, space, warnings) if token_list.rows and not warnings else {}
    if warnings or any(hold.get("error") for hold in holds.values()):
        return None
    packed = Counter()
    for hold in holds.values():
        packed.update(hold["rows"])
    packed_names = {(row["front"], row["back"]) for index, row in enumerate(token_list.rows) if packed[index]}
    by_key = {}
    for index, row in enumerate(token_list.rows):
        quantity = max(0, int(row["quantity"]) - packed[index])
        if quantity:
            key = collection_audits.token_key(row)
            entry = by_key.setdefault(key, {"key": key, "name": rules.token_label(row), "set": row["set"],
                                            "collector_number": row["front_collector_number"], "finish": row["finish"],
                                            "manualLabel": _token_scan_label(row),
                                            "token": {field: row[field] for field in rules.TOKEN_ID_FIELDS},
                                            "description": " / ".join(filter(None, (row["front_details"], row["back_details"]))),
                                            "estimated": (row["front"], row["back"]) in packed_names, "quantity": 0})
            entry["quantity"] += quantity
    return by_key.values()


def build(space, setup, saved):
    """Partition expected loose copies without order, holder, or private note details."""
    snapshot = inventory.current()
    rows, _ = collection._view(snapshot.collection(space))
    rows = collection._rows_json(rows)
    locations = collection_locations.locations(space, collection._picture_key)
    if not locations["ready"] or locations.get("error"):
        raise ApiError(409, "Storage locations couldn't be read. Check the storage setup and try again.")
    if rows and not collection._ready():
        raise ApiError(409, "The card data isn't ready yet. Try again when it has loaded.")
    try:
        storage = _storage_rows(space, rows)
        return _map(space, setup["storage"], rows, locations["rows"], storage, saved)
    except (RuntimeError, ValueError, OSError) as exc:
        raise ApiError(409, "The loose card counts couldn't be worked out. Check the collection and card data.") from exc


def _map(space, record, rows, locations, storage, saved):
    destination, ordered = _filing(record, saved)
    allocations = storage["rows"]
    names = {name: cards.resolve(name) or name for name in {row["name"] for row in rows}}
    estimated = {names[row["name"]] for row in rows if allocations.get(collection._picture_key(row), {}).get("guess")}
    excluded, basics = [], 0
    for row in rows:
        key = collection._picture_key(row)
        qty = int(row["quantity"])
        usage = allocations.get(key, {})
        held = usage.get("held", 0)
        if held is None:
            basics += qty
            continue
        free = max(0, qty - held - usage.get("lent", 0))
        if free:
            location = locations.get(key, "")
            name = names[row["name"]]
            card = cards.card(name)
            entry = {field: row[field] for field in ("name", "set", "collector_number", "finish")}
            entry.update(key=key, quantity=free, location=location, mana_value=(card or {}).get("cmc"),
                         estimated=bool(storage.get("estimate")) or name in estimated)
            destination(location, _divider(card))["rows"].append(entry)
    if basics:
        excluded.append({"label": "Recorded basic lands with unknown loose counts", "quantity": basics})
    token_rows = _token_rows(space)
    if token_rows is None:
        excluded.append({"label": "Token cards with unavailable loose counts", "quantity": None})
        if record["default"] is not None:
            token_section = destination("", TOKENS)
            token_section.update(auditable=False, message="Loose token card counts are unavailable. Check the Tokens page before auditing this section.")
    else:
        for row in token_rows:
            destination("", TOKENS)["rows"].append(row)
    sections = []
    for section, order in ordered():
        section["rows"].sort(key=lambda row: _row_rank(row, order))
        for row in section["rows"]:
            row.pop("mana_value", None)
        section["quantity"] = sum(row["quantity"] for row in section["rows"])
        sections.append(section)
    return sections, excluded


def _row_rank(row, order):
    words = (row["name"].casefold(), row["key"])
    if order == "set":
        return (not row["set"], *rules.sort_key(row), *words)
    if order == "colour-type":
        mana = row.get("mana_value")
        return (mana if isinstance(mana, (int, float)) and math.isfinite(mana) else math.inf, *words)
    return words
