"""Order/queue review dependencies without other-space counters or private kit metadata."""
import copy
import hashlib
import json

from decklab.lib import change_signal

from . import files

KIT = {"sleeves", "deck_box"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def source(raw):
    rows = copy.deepcopy(raw)
    for row in rows:
        omitted = KIT if row["table"] == "product_status" else {"kit_version", "revision", "updated_at"} if row["table"] == "deck" else set()
        for side in ("before", "after"):
            if isinstance(row.get(side), dict):
                row[side] = {key: value for key, value in row[side].items() if key not in omitted}
    return rows


def order_facts(images):
    return {table: {key: {field: value for field, value in image.items() if table != "product_status" or field not in KIT}
                    for key, image in rows.items()} for table, rows in images.items()}


def context(inv):
    def sheet(value):
        return files.rendered_sha256(value) if value is not None else None
    decks = []
    for record in inv.space_decks("home"):
        try:
            # Existing privacy projection rebuilds the header without kit fields,
            # so adding/removing hidden kit never shifts the intrinsic text hash.
            value = change_signal._deck(record, own=True, readers=frozenset(), home_players={})["value"]
        except change_signal.Unverified:
            value = "unavailable"     # no raw parse error or private text fallback
        decks.append((record.id, value))
    return _digest({"collection": sheet(inv.collection("home")), "tokens": sheet(inv.token_set("home")),
                    "locations": sheet(inv.locations.get("home")), "loans": sheet(inv.loans.get("home")), "decks": decks})
