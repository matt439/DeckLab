"""In-memory accessory text/audit fixtures; no repository or database reads."""
import copy

from decklab.lib import accessories
from decklab.lib.inventory import files, model, paths, rules

CHANGE_ID = 17
ROW_ID = 101
NEW_ROW_ID = 110
OWNERS = frozenset({"matt", "shared"})
FIELDS = ("brand", "name", "colour", "notes", "link", "image_source")
META = ("id", "kind", "owner", *FIELDS)


def row(**extra):
    return {"id": "a-sleeves", "kind": "sleeves", "owner": "matt", "brand": "Fixture brand",
            "name": "Current sleeves", "colour": "red", "quantity": "100", "capacity": "",
            "image": "a-sleeves.jpg", "crop": "0.1,0.1,0.8,0.8", "link": "https://example.com/product",
            "image_source": "https://example.com/image", "notes": "Current fixture note", **extra}


def meta(value):
    return {field: value[field] for field in META}


def build_snapshot(rows=None):
    if rows is None:
        rows = [row(), row(id="b-shared", owner="shared", name="Shared sleeves", image="", crop=""),
                row(id="c-hidden", owner="user1", name="Private sleeves", image="c-hidden.jpg")]
    contents = {
        paths.ACCESSORIES: accessories.csv_bytes(rows),
        paths.image("a-sleeves.jpg"): b"synthetic fixture picture",
        paths.image("c-hidden.jpg"): b"synthetic private picture",
        paths.collection("home"): b"name,set,collector_number,finish,quantity,condition,language,notes\nOpt,dom,60,nonfoil,2,NM,en,Keep stock\n",
        paths.collection("user2"): b"name,set,collector_number,finish,quantity,condition,language,notes\nOpt,dom,60,nonfoil,1,,,Private stock\n",
        f"{paths.imports_dir()}/fixture.csv": b"opaque fixture import",
        paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n").encode("utf-8"),
        paths.WATCHLIST: (",".join(model.WatchRow.COLUMNS) + "\n").encode("utf-8"),
        paths.deck("home", "casual", "fixture"): b"# Fixture\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** user\n- **Status:** built\n- **Built version:** target\n- **Sleeves:** a-sleeves\n\n## Decklist\n\n```\n60 Forest\n```\n",
    }
    return files.build(contents, revision="inventory-1", decks_revision="decks-1", backend="accessory-undo-fixture")


snapshot = build_snapshot


class AuditAccessoryInventory:
    name = "accessory-undo-fixture"

    def __init__(self, snapshot=None):
        self._initial = build_snapshot() if snapshot is None else snapshot
        self.snapshot = self._initial
        self.audit, self.writes, self.latest = {}, [], ROW_ID
        self.seed()

    def seed(self, owner="matt"):
        current = row(owner=owner)
        restored = {**current, "brand": "Original brand", "name": "Original sleeves",
                    "colour": "blue", "notes": "Original fixture note",
                    "link": "http://example.com/original-product?fixture=1",
                    "image_source": "https://example.com/original-image.jpg#fixture"}
        rows = [current if found.accessory_id == current["id"] else found.as_dict() for found in self._initial.accessories.rows]
        if not any(found["id"] == current["id"] for found in rows):
            rows.append(current)
        self.snapshot = self._initial.with_accessories(rows)
        self.audit = {CHANGE_ID: [{"id": ROW_ID, "table": "accessory", "op": "UPDATE", "key": {"id": current["id"]},
                                  "before": copy.deepcopy(restored), "after": copy.deepcopy(current)}]}
        self.latest = ROW_ID
        self.writes.clear()
        return current, restored

    def load(self):
        return self.snapshot

    def undo_audit(self, change_id):
        return copy.deepcopy(self.audit.get(change_id, [])[:2])

    def undo_latest(self, table, key):
        return self.latest


def actual_source(plan, id=NEW_ROW_ID):
    source = plan["source"]
    return [{"id": id, "table": "accessory", "op": "UPDATE", "key": copy.deepcopy(source["key"]),
             "before": copy.deepcopy(source["after"]), "after": copy.deepcopy(source["before"])}]


def seed_insert(store, owner="matt", only=False):
    """An unused photo-free insertion; leave the UPDATE fixture's initial state intact."""
    current = row(owner=owner, image="", crop="")
    rows = [current] if only else [current if found.accessory_id == current["id"] else found.as_dict()
                                  for found in store._initial.accessories.rows]
    snapshot = store._initial.with_accessories(rows).without_image("a-sleeves.jpg")
    deck = snapshot.deck("casual/fixture")
    if deck is not None and deck.text is not None:
        from dataclasses import replace
        snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", "")))
    store.snapshot = snapshot
    store.audit = {CHANGE_ID: [{"id": ROW_ID, "table": "accessory", "op": "INSERT", "key": {"id": current["id"]},
                              "before": None, "after": copy.deepcopy(current)}]}
    store.latest = ROW_ID
    store.writes.clear()
    return current
