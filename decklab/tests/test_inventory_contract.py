"""The inventory backends' contract (decklab/lib/inventory): the database backend (pg.py) gives
exactly the snapshot the files backend gives for the same data, and writes what an operation
changed as the audit trail expects. The database tests run in a throwaway database (they skip
without one: db_support.py).

- The fixture adapter (amendment Q2): adapt() turns a fixture tree's snapshot into one the
  database can hold (a record for each payload no record names, a legacy status.csv header made
  the six-column one, collections in sort order, no empty collection or tokens files, an empty
  watchlist where there's none). A scenario the adapted snapshot still can't be held for is
  "file-only": FILE_ONLY lists them, with why, and a test keeps that list honest (a scenario is
  file-only exactly when representable() finds a reason). Unknown status or intact values and
  payloads no record names are NOT file-only: the database holds any status text, and the
  adapter gives each loose payload a record, so those are compared on both backends. Areas add
  their scenarios to SCENARIOS (a builder taking a test_pool.PoolTestCase whose tree it writes)
  and, when one can only be a file, to FILE_ONLY.
- Backend equality: each scenario's adapted snapshot, written into the database (write_model,
  after the fixture profiles are synced) and loaded back by PgInventory, equals the files
  backend's, and renders to the same files byte for byte. The same holds for the real repo at
  the golden commit (gate.GOLDEN_REV), read from git's blobs: the File model equals the Pg
  model, and the Pg model renders every inventory file there byte for byte (and keeps the import
  files' bytes).
- Scenario goldens (the foundation review's item 9): what today's readers (the code at the
  phase 3 foundation, whose readers are the golden commit's) say about every scenario's tree,
  raw and adapted, and about the test Sandbox's tree, as gate.dump() records it, committed in
  fixtures/inventory_goldens/ (regenerate only for a new scenario: python -m
  decklab.tests.test_inventory_contract --write-goldens NAME). run_readers(backend, root) is the
  hook: the files backend must give every golden in full, on the raw tree and the adapted one;
  the database backend (the adapted tree imported, the inventory files then deleted from the
  tree) must give the adapted golden for every gate item in PORTED, which each area extends as
  it ports a reader. Every dump runs in fixture_world(): the fixture card index
  (fixtures/default_cards.jsonl), the fixture profiles and gate.FIXED_RATE.
- PgInventory itself: no inventory until imported, write_model's refusals, apply's row diff
  (one change set, no position churn, ids kept), expected_revision, unchanged ops, kept imports,
  the stale snapshot while the database is down, and two writers at once.

Run from the repo root: python -m unittest decklab.tests.test_inventory_contract
"""
import contextlib
import dataclasses
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

from decklab.tests import golden_dump as gate
from decklab.lib import cards, config, inventory
from decklab.lib.inventory import files, model, paths, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import Component, Order, Sheet, StatusRow
from decklab.lib.state import Actor, Conflict, Invalid, Unavailable
from decklab.tests import db_support, test_pool

CLAUDE = Actor("claude", "Claude", None, "cli")
MATT = Actor("matt", "Matt", "home")
CARD_HEADER = ",".join(rules.FIELDS) + "\n"
TOKEN_HEADER = ",".join(rules.TOKEN_FIELDS) + "\n"
STATUS_HEADER = ",".join(rules.STATUS_FIELDS) + "\n"
WATCH_HEADER = ",".join(model.QUEUE_FIELDS) + "\n"
# The fixture profiles synced into each throwaway database before an import (no foreign key
# needs them, but write_model refuses a space the database doesn't have, as the import did).
FIXTURE_PROFILES = [
    {"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user", "emails": []},
    {"id": "user1", "name": "User1", "role": "admin", "space": "home", "plays_as": "wife", "emails": []},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2", "plays_as": None, "emails": []},
    {"id": "user3", "name": "User3", "role": "member", "space": "user3", "plays_as": None, "emails": []},
    {"id": "user4", "name": "User4", "role": "member", "space": "user4", "plays_as": None, "emails": []},
]


# ------------------------------------------------------------------ the fixture adapter

def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "order"


FILLER = model.CardRow.make(name="Plains", set="fdn", collector_number="272", finish="nonfoil", quantity="1")


def adapt(inv):
    """A fixture tree's snapshot as the database can hold it, as the files backend reads it
    (amendment Q2): each payload no record names gets a record of its own (id: its file
    stem, one component named for its kind, blank seller and dates, no sources); a legacy
    four- or six-column status.csv gets the current header; collections are put in sort order; a
    collection or tokens file with no rows goes (a space with no cards has no file), except that
    an empty home collection gets one ordinary Plains (FILLER: basics count nowhere), since home
    with no file can't be read by today's pool; a missing watchlist becomes an empty one; the deck parts (phase 4) stay as read. Everything else stays as it is, so what representable()
    still finds makes the scenario file-only."""
    orders = list(inv.orders)
    named = {c.path for _, c in inv.components()}
    taken = {o.file for o in orders}
    for path in inv.payloads:
        if path in named:
            continue
        kind, status, file_name = paths.classify(path)[1]
        base = order_id = _slug(PurePosixPath(file_name).stem)
        n = 2
        while f"{order_id}.json" in taken:
            order_id, n = f"{base}-{n}", n + 1
        taken.add(f"{order_id}.json")
        orders.append(Order.build(order_id, components=[Component.build(kind, kind, file_name, status)]))
    status = inv.status
    if status.readable and status.columns in (tuple(rules.LEGACY_STATUS_FIELDS), tuple(rules.KIT_STATUS_FIELDS)):
        rows = tuple(StatusRow.make({k: row.text(k) for k in rules.STATUS_FIELDS}, line=row.line)
                     for row in status.rows)
        status = Sheet(status.path, tuple(rules.STATUS_FIELDS), rows, True)

    def kept(sheets, order=None):
        out = {}
        for space, sheet in sheets.items():
            if sheet.readable and not sheet.rows and not sheet.problems:
                continue
            if order and sheet.readable:
                try:
                    sheet = dataclasses.replace(sheet, rows=tuple(sorted(sheet.rows, key=lambda r: order(r.as_dict()))))
                except (KeyError, TypeError):
                    pass
            out[space] = sheet
        return out
    watchlist = inv.watchlist if inv.watchlist.exists else Sheet(paths.WATCHLIST, model.QUEUE_FIELDS, (), True)
    collections = kept(inv.collections, rules.sort_key)
    home = inv.collection()
    if home.readable and not home.rows and not home.problems:
        # Home with no cards would have no file, which today's pool can't read at all; one
        # ordinary basic (left out of every count) keeps the scenario about what it's about.
        collections[paths.HOME] = Sheet(home.path, tuple(rules.FIELDS), (FILLER,), True)
    adapted = inv.replace(orders=tuple(sorted(orders, key=lambda o: o.file)), status=status,
                          collections=dict(sorted(collections.items())), tokens=kept(inv.tokens),
                          watchlist=watchlist)
    return files.build(files.render(adapted)).replace(
        imports=inv.imports, decks=inv.decks, accessories=inv.accessories, accessory_images=inv.accessory_images,
        decks_revision=inv.decks_revision)


def import_contents(root):
    """{(space, file name): bytes} of every raw import file under root."""
    out = {}
    for rel, data in files.tree_files(root, import_bytes=True).items():
        what, detail = paths.classify(rel)
        if what == "import":
            out[detail] = data
    return out


# ------------------------------------------------------------------ scenarios

def _records(t, *records):
    for record in records:
        t.write(f"orders/records/{record.file}", rules.json_bytes(record.data).decode("utf-8"))


def _tokens(t, rel, *rows):
    t.write(rel, TOKEN_HEADER + "".join(",".join(row) + "\n" for row in rows))


def beginner_box(t):
    t.beginner_box()


def loose_orders(t):
    t.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
    t.cards_csv("orders/2026-09-29-singles.csv", ("Opt", "dom", "60", "nonfoil", 2))
    t.cards_csv("orders/2026-10-01-more.csv", ("Shock", "m19", "156", "nonfoil", 1),
                ("Opt", "dom", "60", "foil", 1))
    t.cards_csv("orders/received/2026-09-26-old.csv", ("Opt", "dom", "60", "nonfoil", 1))


def products_by_status(t):
    t.product("precon.csv", ("Main", "Llanowar Elves", 1), ("Main", "Forest", 9), column="section")
    t.product("alpha-team.csv", ("Elves", "Elvish Mystic", 2))
    t.product("fdn-beginner-box.csv", ("Cats", "Pick Your Poison", 1))
    t.status(("precon.csv", "preordered", ""), ("alpha-team.csv", "ordered", ""),
             ("fdn-beginner-box.csv", "owned", "yes"))


def status_without_files(t):
    t.status(("gone.csv", "owned", "no"), ("fdn-beginner-box.csv", "owned", "yes"))
    t.product("fdn-beginner-box.csv", ("Elves", "Llanowar Elves", 1))
    t.product("unlisted.csv", ("Elves", "Elvish Mystic", 1))


def odd_status_values(t):
    t.product("x.csv", ("Elves", "Llanowar Elves", 1))
    t.status(("x.csv", "preorder", "maybe"))


def odd_product_cells(t):
    t.product("words.csv", ("Elves", "Llanowar Elves", "one"), ("Elves", "", "2"))
    t.status(("words.csv", "owned", "no"))


def recorded_orders(t):
    t.cards_csv("orders/2026-10-07-shop-a.csv", ("Opt", "dom", "60", "nonfoil", 2))
    t.cards_csv("orders/received/2026-10-01-shop.csv", ("Shock", "m19", "156", "nonfoil", 1))
    t.cards_csv("orders/cancelled/2026-09-29-seller2.csv", ("Dire Moon", "xyz", "1", "nonfoil", 1))
    _tokens(t, "orders/tokens/2026-10-07-shop-a.csv", ("Dog", "Beast", "", "", "", "", "1", "", "3/3",
                                                        "single-sided verified"))
    _tokens(t, "orders/tokens/received/2026-10-01-shop.csv", ("Rabbit", "", "", "", "", "", "2", "", "",
                                                              "single-sided verified"))
    t.product("precon.csv", ("Main", "Llanowar Elves", 1), column="section")
    t.status(("precon.csv", "preordered", ""))
    _records(t, Order.build("2026-10-07-shop-a", "MTGMate", "2026-10-07", notes="two parts", components=[
        Component.build("cards", "cards", "2026-10-07-shop-a.csv", checks=["Record conditions"]),
        Component.build("tokens", "tokens", "2026-10-07-shop-a.csv")]),
        Order.build("2026-10-01-shop", "Shop", "", components=[
            Component.build("cards", "cards", "2026-10-01-shop.csv", "received", "2026-10-03"),
            Component.build("tokens", "tokens", "2026-10-01-shop.csv", "received", "2026-10-03",
                            verified_checks=["Verify the reverse"])], audit_notes="from git"),
        Order.build("2026-09-29-seller2", components=[
            Component.build("cards", "cards", "2026-09-29-seller2.csv", "cancelled")]),
        Order.build("precon", "Shop", "2026-10-02", components=[
            Component.build("precon", "product", "precon.csv")]))


def person_spaces(t):
    t.cards_csv("people/user2/collection.csv", ("Shock", "m19", "156", "nonfoil", 3))
    _tokens(t, "people/user2/tokens.csv", ("Goblin", "", "", "", "", "", "2", "1/1; red", "", ""))
    t.write("people/user2/imports/2026-10-10-precon.csv", "Name,Quantity\nShock,3\n")
    t.cards_csv("people/user4/collection.csv")                 # header only: no cards
    _tokens(t, "tokens.csv", ("Treasure", "", "tltc", "14", "", "nonfoil", "1", "", "", ""),
            ("Dog", "Beast", "", "", "", "", "1", "", "3/3", "printing unconfirmed"))


def special_basics(t):
    t.cards_csv("collection.csv", ("Plains", "sld", "1513", "foil", 1), ("Forest", "fdn", "279", "nonfoil", 2))
    t.write("watchlist.csv", WATCH_HEADER + "Opt,dom,60,nonfoil,1,Gruul,any,0.50,MTGMate,no,2026-10-05,,"
                                            "long_term,magic/decks/casual/gruul.md\n")


def malformed_rows(t):
    t.cards_csv("collection.csv", ("Opt", "dom", "60", "nonfoil", "lots"))


def undecodable_order(t):
    (t.magic / "orders/2026-09-30-broken.csv").write_bytes(b"\xff\xfe")


def missing_status(t):
    (t.magic / "products/status.csv").unlink()


ACCESSORIES_HEADER = "id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n"


def built_decks_and_kits(t):
    """Built home decks with sleeves and deck boxes, an intact product with its kit, and an
    intact product whose card list isn't there."""
    t.beginner_box()
    t.write("products/status.csv", STATUS_HEADER + "fdn-beginner-box.csv,owned,yes,black-sleeves,shared-box,,\n"
                                                   "lost-precon.csv,owned,yes,,,,\n")
    t.write("accessories.csv", ACCESSORIES_HEADER + "black-sleeves,sleeves,shared,,Matte,black,100,,,,,,\n"
                                                    "red-sleeves,sleeves,matt,,Matte,red,60,,,,,,\n"
                                                    "shared-box,deck_box,shared,,Box,grey,2,100,,,,,\n")
    t.write("decks/casual/elves.md", "# Elves\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** user\n"
                                     "- **Status:** built\n- **Sleeves:** red-sleeves\n- **Deck box:** shared-box\n\n"
                                     "## Decklist\n\n```\nDeck\n2 Llanowar Elves (FDN) 227\n1 Elvish Mystic\n"
                                     "1 Pick Your Poison\n```\n")
    t.write("decks/casual/idea.md", "# Idea\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** wife\n"
                                    "- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n```\n")


SCENARIOS = {
    "beginner box kept intact": beginner_box,
    "orders no record names": loose_orders,
    "products owned, preordered and ordered": products_by_status,
    "status rows with no file and a file with no row": status_without_files,
    "unknown status and intact values": odd_status_values,
    "product rows with words for quantities and no name": odd_product_cells,
    "recorded card, token and product orders in every state": recorded_orders,
    "person spaces with tokens and an import": person_spaces,
    "special basics and a watchlist": special_basics,
    "malformed collection rows": malformed_rows,
    "an undecodable order file": undecodable_order,
    "no status.csv": missing_status,
    "built decks, kits and an intact product with no list": built_decks_and_kits,
}
# The scenarios only the files backend can hold, and why: the contract suite compares the rest.
FILE_ONLY = {
    "malformed collection rows": "a quantity that isn't a whole number can't be a database row",
    "an undecodable order file": "a file that can't be read has no rows to keep",
    "no status.csv": "the database always has a status list, so it can't say the file is missing",
}


# ------------------------------------------------------------------ scenario goldens

GOLDENS = Path(__file__).parent / "fixtures" / "inventory_goldens"
SANDBOX = "the test sandbox"
# The gate items (gate.dump()'s top-level keys) whose readers read inventory.current(): the
# database half compares only these with the goldens, since a reader not ported yet still reads
# files, which aren't there for the database run. Each area adds its items as it ports them
# (A: "pools", "printing_counts", "read_status", "list_decks", ...; B: "tokens"; ...).
PORTED = {
    # A: the pool, the product decks, Shopping, the Forge field, the collection and other pages.
    "pools", "printing_counts", "read_status", "list_decks", "beginner_box_pairings", "load_deck",
    "owned_vs_needed", "owned_vs_needed_priced", "deck_table", "deck_table_priced", "stale_tables",
    "plan_refresh", "purchases", "field", "collection", "decks_index", "printings",
    "wishlist_view",
    # B: the token cards and the decks' token needs.
    "tokens",
    # E: the accessories' product holders; with B and E merged, the deck page and Assembly too.
    "accessories", "deck_view", "assembly",
    # Not inventory (config.json's spaces), the same from either backend.
    "spaces",
}
_index_file = None


def golden_path(name, adapted=False):
    return GOLDENS / f"{_slug(name)}{'.adapted' if adapted else ''}.json"


def load_golden(name, adapted=False):
    """A golden as recorded, normalised (as every dump compared with it is) by gate_p4.EXPECTED_P4:
    the differences phase 4 makes on purpose (no git, deck ids, hidden inventory)."""
    return expected_p4(json.loads(golden_path(name, adapted).read_text(encoding="utf-8")))


def expected_p4(dump):
    """Documented historical differences, then narrow additive packing compatibility."""
    from decklab.tests import golden_p4 as gate_p4, golden_packing
    return golden_packing.normalise(gate_p4.normalise(dump))


def _fixture_index():
    """The fixture card index (test_pool's), built once a process into a temp file."""
    global _index_file
    if _index_file is None or not _index_file.exists():
        folder = Path(tempfile.mkdtemp(prefix="decklab-contract-"))
        index = cards.build_index(test_pool.FIXTURES / "default_cards.jsonl", test_pool.FIXTURES / "oracle_tags.jsonl",
                                  {"default_cards": "2026-09-28T21:05:39+00:00"}, log=lambda *a: None)
        cards.write_index(index, folder / "index.json.gz")
        _index_file = folder / "index.json.gz"
    return _index_file


@contextlib.contextmanager
def fixture_world():
    """What every scenario dump runs with: the fixture card index, a config.json of the fixture
    profiles (so the goldens don't depend on this checkout's), no exchange-rate file (the gate
    fixes the rate)."""
    with tempfile.TemporaryDirectory(prefix="decklab-world-") as temp:
        temp = Path(temp)
        (temp / "config.json").write_text(json.dumps({"profiles": FIXTURE_PROFILES}), encoding="utf-8")
        with mock.patch.object(cards, "INDEX_FILE", _fixture_index()), mock.patch.object(cards, "_index", None), \
                mock.patch.object(cards, "FX_FILE", temp / "fx.json"), \
                mock.patch.object(config, "CONFIG_FILE", temp / "config.json"), \
                mock.patch.dict(os.environ, {config.EXTRA_ENV: ""}):
            yield


def _rewrite_adapted(case):
    """Replace the case's inventory files with the adapted snapshot's (raw imports stay)."""
    root = case.inventory.root
    adapted = adapt(case.inventory.load())
    for rel in files.tree_files(root):
        if paths.classify(rel)[0] != "import":
            (root / rel).unlink()
    for rel, data in files.render(adapted).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)


@contextlib.contextmanager
def scenario(builder, adapted=False):
    """A test_pool.PoolTestCase whose tree builder wrote (adapted: rewritten as adapt() holds
    it), inside fixture_world(); yields the case (its tree is case.inventory.root)."""
    case = test_pool.PoolTestCase()
    case.setUp()
    try:
        for folder in ("orders/records", "orders/cancelled", "orders/tokens/received", "people/user2/imports",
                       "people/user4"):
            (case.magic / folder).mkdir(parents=True, exist_ok=True)
        builder(case)
        if adapted:
            _rewrite_adapted(case)
        with fixture_world():
            yield case
    finally:
        case.doCleanups()


def run_readers(backend, root):
    """Every gate item's output over root, with backend as the inventory backend (the contract
    hook: gate.dump, whose GATE_READERS the areas keep calling their ported readers)."""
    return gate.dump(root, backend=backend)


def scenario_dump(builder, adapted=False):
    with scenario(builder, adapted) as case:
        return run_readers(FileInventory(case.inventory.root), case.inventory.root)


def sandbox_dump():
    from decklab.tests.test_api import Sandbox
    box = Sandbox().start()
    try:
        return run_readers(box.inventory, box.root)
    finally:
        box.stop()


def golden_cases():
    """(name, builder or None for the sandbox, adapted) of every golden."""
    out = []
    for name, builder in SCENARIOS.items():
        out.append((name, builder, False))
        if name not in FILE_ONLY:
            out.append((name, builder, True))
    out.append((SANDBOX, None, False))
    return out


def write_goldens(names=None):
    """Write the goldens (of the scenarios named, every one by default) from this checkout's
    readers: run it only while they are today's readers, for a new scenario."""
    GOLDENS.mkdir(parents=True, exist_ok=True)
    for name, builder, adapted in golden_cases():
        if names and name not in names:
            continue
        out = sandbox_dump() if builder is None else scenario_dump(builder, adapted)
        golden_path(name, adapted).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                              encoding="utf-8", newline="\n")
        print(f"wrote {golden_path(name, adapted).name}")


def build_tree(builder, adapted=True):
    """A PoolTestCase whose tree builder wrote (adapted: as adapt() holds it); the caller cleans
    it up (case.doCleanups)."""
    case = test_pool.PoolTestCase()
    case.setUp()
    for folder in ("orders/records", "orders/cancelled", "orders/tokens/received", "people/user2/imports",
                   "people/user4"):
        (case.magic / folder).mkdir(parents=True, exist_ok=True)
    builder(case)
    if adapted:
        _rewrite_adapted(case)
    return case


def build_scenario(builder):
    """(the files backend's snapshot of the scenario's tree, its import files)."""
    case = test_pool.PoolTestCase()
    case.setUp()
    for folder in ("orders/records", "orders/cancelled", "orders/tokens/received", "people/user2/imports",
                   "people/user4"):
        (case.magic / folder).mkdir(parents=True, exist_ok=True)
    try:
        builder(case)
        return case.inventory.load(), import_contents(case.inventory.root)
    finally:
        case.doCleanups()


class AdapterTests(unittest.TestCase):
    """The adapter and the file-only list (no database needed)."""

    def test_file_only_is_exactly_what_the_database_cant_hold(self):
        from decklab.lib.inventory import pg
        for name, builder in SCENARIOS.items():
            with self.subTest(scenario=name):
                inv, _ = build_scenario(builder)
                reasons = pg.representable(adapt(inv))
                self.assertEqual(bool(reasons), name in FILE_ONLY, reasons)

    def test_the_adapter_records_loose_payloads_and_upgrades_status(self):
        inv, _ = build_scenario(loose_orders)
        self.assertEqual(len(inv.loose_payloads), 2)
        adapted = adapt(inv)
        self.assertEqual(adapted.loose_payloads, [])
        self.assertEqual([o.id for o in adapted.orders], ["2026-09-26-old", "2026-09-29-singles", "2026-10-01-more"])
        self.assertEqual([c.path for _, c in adapted.components()],
                         ["magic/orders/received/2026-09-26-old.csv", "magic/orders/2026-09-29-singles.csv",
                          "magic/orders/2026-10-01-more.csv"])
        self.assertEqual(adapted.status.columns, tuple(rules.STATUS_FIELDS))
        self.assertEqual(adapted.payloads, inv.payloads)

    def test_the_adapter_sorts_collections_and_drops_empty_files(self):
        inv, _ = build_scenario(beginner_box)
        self.assertEqual([r.name for r in inv.collection().rows][:2], ["Aerie Mystics", "Elvish Mystic"])
        self.assertEqual([r.set for r in adapt(inv).collection().rows], ["cmm", "con", "fdn", "mkm"])
        inv, contents = build_scenario(person_spaces)
        self.assertTrue(inv.collection("user4").exists)
        adapted = adapt(inv)
        self.assertNotIn("user4", adapted.collections)
        self.assertEqual(adapted.imports, inv.imports)
        self.assertEqual(list(contents), [("user2", "2026-10-10-precon.csv")])


# ------------------------------------------------------------------ the database

def _set_quantity(inv, *, space="home", index=0, quantity="3"):
    sheet = inv.collection(space)
    rows = list(sheet.rows)
    rows[index] = rows[index].replace(quantity=quantity)
    return inv.replace(collections={**inv.collections, space: dataclasses.replace(sheet, rows=tuple(rows))}), \
        inventory.Summary("Set a quantity", {"rows": 1})


def _nothing(inv):
    return inv, inventory.Summary("Nothing")


def _edit_tokens(inv, *, add=None, at=0, edit=None, remove=None):
    """Insert a token row (cells) at index at, set notes on row index edit, remove row index remove."""
    sheet = inv.token_set()
    rows = list(sheet.rows)
    if edit is not None:
        rows[edit] = rows[edit].replace(notes="edited")
    if remove is not None:
        del rows[remove]
    if add is not None:
        rows.insert(at, model.TokenRow.make(dict(zip(rules.TOKEN_FIELDS, add))))
    return inv.replace(tokens={**inv.tokens, "home": dataclasses.replace(sheet, rows=tuple(rows))}), inventory.Summary()


def _drop_watch(inv, *, index):
    rows = list(inv.watchlist.rows)
    del rows[index]
    return inv.replace(watchlist=dataclasses.replace(inv.watchlist, rows=tuple(rows))), inventory.Summary()


def _receive(inv, *, order_id, component_id, date):
    """A receipt's shape: the component received, its payload moved to received/."""
    order = inv.order(order_id)
    data = order.record()
    payloads = dict(inv.payloads)
    for c in data["components"]:
        if c["id"] == component_id:
            old = c["path"]
            c.update(status="received", received_on=date,
                     path=paths.payload(c["kind"], "received", PurePosixPath(old).name))
            sheet = payloads.pop(old)
            payloads[c["path"]] = dataclasses.replace(sheet, path=c["path"])
    orders = tuple(Order(o.file, data) if o.file == order.file else o for o in inv.orders)
    return inv.replace(orders=orders, payloads=payloads), inventory.Summary("Received")


def _keep_import(inv, *, name, data=b"Name,Quantity\nOpt,1\n"):
    return inv, inventory.Summary("Import", extra={"imports": [("user2", name, data)]})


def _mutate_record(inv):
    """Changes a record's dict in place and returns the snapshot it was given."""
    inv.order("2026-09-29-seller2").data["notes"] = "changed in place"
    return inv, inventory.Summary("in place")


def _rows(inv, *, space="home", rows=()):
    return inv.with_collection(space, [dict(zip(rules.FIELDS, r)) for r in rows]), inventory.Summary()


def _loose_payload(inv):
    path = "magic/orders/2026-10-12-loose.csv"
    row = model.CardRow.make(name="Opt", set="dom", collector_number="60", finish="nonfoil", quantity="1")
    return inv.replace(payloads={**inv.payloads, path: Sheet(path, tuple(rules.FIELDS), (row,), True)}), \
        inventory.Summary()


def _tokens_raw(inv):
    sheet = inv.token_set()
    return inv.replace(tokens={**inv.tokens, "home": dataclasses.replace(sheet, rows=sheet.rows[1:])}), \
        inventory.Summary()


def _no_accessories(inv):
    return inv.with_accessories([]), inventory.Summary("No accessories")


OPS = {"test.no_accessories": _no_accessories, "test.set_quantity": _set_quantity, "test.nothing": _nothing, "test.edit_tokens": _edit_tokens,
       "test.drop_watch": _drop_watch, "test.receive": _receive, "test.keep_import": _keep_import,
       "test.mutate_record": _mutate_record, "test.rows": _rows, "test.loose_payload": _loose_payload,
       "test.tokens_raw": _tokens_raw}


def seed_tree(t):
    """A small tree with something in every table."""
    t.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2), ("Opt", "dom", "60", "nonfoil", 1))
    _tokens(t, "tokens.csv", ("Treasure", "", "tltc", "14", "", "nonfoil", "1", "", "", ""),
            ("Zombie", "", "tltc", "20", "", "nonfoil", "2", "", "", ""),
            ("Goblin", "", "tltc", "30", "", "nonfoil", "1", "", "", ""))
    t.write("watchlist.csv", WATCH_HEADER + "".join(
        f"{name},dom,{n},nonfoil,1,Gruul,any,,,,,,long_term,magic/decks/casual/gruul.md\n"
        for n, name in enumerate(("Opt", "Shock", "Duress", "Negate"), 1)))
    t.cards_csv("people/user2/collection.csv", ("Shock", "m19", "156", "nonfoil", 3))
    recorded_orders(t)
    t.write("products/status.csv", STATUS_HEADER + "precon.csv,preordered,,,,,\n")


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgInventoryTests(db_support.DbTestCase):
    """PgInventory and write_model in a throwaway database (the fixture profiles synced once)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.pg = pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.breaker = state_pg.Breaker()
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        for kind, fn in OPS.items():
            inventory.register(kind)(fn)
            self.addCleanup(inventory.unregister, kind)

    def trail(self):
        with self.connect() as c:
            sets = c.execute("select id, actor, source, message, reason from audit.change_set order by id").fetchall()
            rows = c.execute("select change_set_id, table_name, op, row_key, before, after from audit.row_change "
                             "order by id").fetchall()
        return [{"actor": s[1], "source": s[2], "message": s[3], "reason": s[4],
                 "rows": [r[1:] for r in rows if r[0] == s[0]]} for s in sets]

    def import_tree(self, builder):
        inv, contents = build_scenario(builder)
        adapted = adapt(inv)
        self.pg.write_model(adapted, CLAUDE, "Import the inventory", contents=contents, dbname=self.dbname,
                            decks=True)
        return adapted

    def assertSameModel(self, db_inv, file_inv):
        self.assertEqual(db_inv.backend, "db")
        self.assertEqual(db_inv.replace(revision=file_inv.revision, backend=file_inv.backend,
                                        decks_revision=file_inv.decks_revision), file_inv)
        self.assertEqual(files.render(db_inv, decks=True), files.render(file_inv, decks=True))
        # render() leaves out pictures whose bytes a loaded snapshot doesn't hold: compare their metas.
        self.assertEqual({n: (m.name, m.size, m.sha256) for n, m in db_inv.accessory_images.items()},
                         {n: (m.name, m.size, m.sha256) for n, m in file_inv.accessory_images.items()})
        self.assertEqual(db_inv.accessories.exists, file_inv.accessories.exists)

    # -------------------------------------------------------- backend equality

    def test_every_scenario_loads_back_the_same(self):
        for name, builder in SCENARIOS.items():
            if name in FILE_ONLY:
                continue
            with self.subTest(scenario=name):
                db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
                adapted = self.import_tree(builder)
                self.assertSameModel(self.backend.load(), adapted)

    def test_the_real_repo_at_the_golden_commit(self):
        if not gate.golden_rev_available():
            self.skipTest(f"the repo has no commit {gate.GOLDEN_REV[:7]} (the private repo's golden commit)")
        sha, blobs = files.git_files(gate.GOLDEN_REV)
        inv = files.build(blobs)
        self.assertEqual(self.pg.representable(inv), [])
        contents = {paths.classify(rel)[1]: data for rel, data in blobs.items() if paths.classify(rel)[0] == "import"}
        revision = self.pg.write_model(inv, CLAUDE, f"Import the inventory files at {sha[:7]}", contents=contents,
                                       dbname=self.dbname)
        self.assertEqual(revision, "1")
        loaded = self.backend.load()
        self.assertSameModel(loaded, inv)
        expected = {rel: data for rel, data in blobs.items() if paths.classify(rel)[0] != "import"}
        self.assertEqual(sorted(files.render(loaded)), sorted(expected))
        for rel, data in files.render(loaded).items():
            with self.subTest(rel=rel):
                self.assertEqual(data, expected[rel])
        with self.connect() as c:
            kept = {(r[0], r[1]): bytes(r[2]) for r in c.execute(
                "select i.space_id, i.file_name, c.content from collection_import i "
                "join collection_import_content c on c.import_id = i.id").fetchall()}
            audited = c.execute("select count(*) from audit.row_change where table_name = 'collection_import' "
                                "and after ? 'content'").fetchone()[0]
        self.assertEqual(kept, contents)
        self.assertEqual(audited, 0)

    def test_the_real_repo_deck_parts_at_the_phase_4_golden_commit(self):
        """Phase 4: every deck file, accessories.csv and picture at gate.GOLDEN_REV_P4 (git's
        blobs) imported: the File model's deck parts equal the Pg model's, and the database gives
        back every file byte for byte (the pictures raw, through image())."""
        if subprocess_rev(gate.GOLDEN_REV_P4) is None:
            self.skipTest(f"the repo has no commit {gate.GOLDEN_REV_P4[:7]}")
        self.import_tree(seed_tree)
        sha, blobs = files.git_files(gate.GOLDEN_REV_P4, decks=True)
        parts = {rel: data for rel, data in blobs.items() if paths.is_deck_part(rel)}
        inv = files.build(parts)
        self.assertEqual(self.pg.deck_tables(inv, strict=True)[1], [])
        images = {paths.classify(rel)[1]: data for rel, data in parts.items() if paths.classify(rel)[0] == "image"}
        self.pg.write_decks(inv, CLAUDE, f"Import the decks at {sha[:7]}", images=images, replace=True,
                            dbname=self.dbname)
        loaded = self.backend.load()
        self.assertEqual((len(loaded.decks), len(loaded.accessory_images)), (19, 23))
        for field in ("decks", "accessories", "accessory_images"):
            self.assertEqual(getattr(loaded, field), getattr(inv, field), field)
        rendered = {rel: data for rel, data in files.render(loaded, decks=True).items() if paths.is_deck_part(rel)}
        for rel, data in parts.items():
            with self.subTest(rel=rel):
                what, detail = paths.classify(rel)
                if what == "image":
                    self.assertEqual(self.backend.image(detail), data)
                    self.assertEqual(self.backend.image(detail, loaded.image_meta(detail).sha256), data)
                else:
                    self.assertEqual(rendered[rel], data)
        self.assertEqual(sorted(rendered), sorted(rel for rel in parts if paths.classify(rel)[0] != "image"))
        self.assertTrue(all(d.revision == 1 for d in loaded.decks.values()))
        with self.connect() as c:
            audited = c.execute("select table_name, count(*) from audit.row_change where table_name in "
                                "('deck', 'deck_text', 'deck_revision', 'deck_line', 'accessory', 'accessory_image') "
                                "group by 1 order by 1").fetchall()
        self.assertEqual(audited, [("accessory", len(inv.accessories.rows)), ("deck", 19)])

    # -------------------------------------------------------- importing

    def test_nothing_is_there_until_the_import(self):
        with self.assertRaisesRegex(self.pg.NotImported, "holds no inventory: on a new install, run python -m decklab.db setup.*restore the newest backup"):
            self.backend.load()
        with self.assertRaises(self.pg.NotImported):
            self.backend.apply(inventory.Op("test.nothing"), CLAUDE, "Nothing")
        self.assertTrue(self.backend.reachable())
        self.assertEqual(self.trail(), [])

    def test_write_model_refuses_a_second_import_unless_replacing(self):
        adapted = self.import_tree(seed_tree)
        first = self.backend.load()
        with self.assertRaisesRegex(ValueError, "replace-inventory"):
            self.pg.write_model(adapted, CLAUDE, "Again", dbname=self.dbname)
        smaller = adapted.replace(watchlist=dataclasses.replace(adapted.watchlist, rows=adapted.watchlist.rows[:1]))
        smaller = files.build(files.render(smaller)).replace(imports=adapted.imports)
        self.assertEqual(self.pg.write_model(smaller, CLAUDE, "Import again", replace=True, dbname=self.dbname), "2")
        again = self.backend.load()
        self.assertEqual(len(again.watchlist.rows), 1)
        self.assertSameModel(again, smaller)
        self.assertNotEqual(again.revision, first.revision)
        self.assertEqual([c["message"] for c in self.trail()], ["Import the inventory", "Import again"])

    def test_write_model_refusals(self):
        inv, contents = build_scenario(person_spaces)
        adapted = adapt(inv)
        with self.assertRaisesRegex(ValueError, "content wasn't given"):
            self.pg.write_model(adapted, CLAUDE, "Import", dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "line 2: quantity 'lots'"):
            self.pg.write_model(build_scenario(malformed_rows)[0], CLAUDE, "Import", dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "no order record names it"):
            self.pg.write_model(build_scenario(loose_orders)[0], CLAUDE, "Import", dbname=self.dbname)
        stranger = adapted.replace(collections={**adapted.collections, "zoe": adapted.collection("user2")})
        stranger = files.build({**files.render(stranger), "magic/people/zoe/collection.csv":
                               files.render_sheet(adapted.collection("user2"))}).replace(imports=adapted.imports)
        with self.assertRaisesRegex(ValueError, "space zoe"):
            self.pg.write_model(stranger, CLAUDE, "Import", contents=contents, dbname=self.dbname)
        self.assertEqual(self.trail(), [])

    # -------------------------------------------------------- applying

    def test_apply_writes_one_change_set_with_only_what_changed(self):
        self.import_tree(seed_tree)
        before = self.backend.load()
        after, summary = self.backend.apply(inventory.Op("test.set_quantity", {"index": 0}), MATT, "Set Opt to 3")
        self.assertEqual(summary.counts, {"rows": 1})
        self.assertEqual(int(after.revision), int(before.revision) + 1)
        self.assertEqual((after.collection().rows[0].name, after.collection().rows[0].quantity), ("Opt", "3"))
        self.assertIs(self.backend.load(), after)                 # cached by revision
        change = self.trail()[-1]
        self.assertEqual((change["actor"], change["source"], change["message"]), ("matt", "web", "Set Opt to 3"))
        self.assertEqual([(r[0], r[1]) for r in change["rows"]], [("collection_card", "UPDATE")])
        self.assertEqual(change["rows"][0][2], {"space_id": "home", "set_code": "dom", "collector_number": "60",
                                                "finish": "nonfoil"})

    def test_an_op_that_changes_nothing_writes_nothing(self):
        self.import_tree(seed_tree)
        before = self.backend.load()
        after, summary = self.backend.apply(inventory.Op("test.nothing"), MATT, "Nothing")
        self.assertEqual((after.revision, summary.text), (before.revision, "Nothing"))
        self.assertEqual(len(self.trail()), 1)

    def test_expected_revision_is_checked_only_when_given(self):
        self.import_tree(seed_tree)
        before = self.backend.load()
        self.backend.apply(inventory.Op("test.set_quantity"), MATT, "Set", expected_revision=before.revision)
        with self.assertRaisesRegex(Conflict, "changed since this was previewed"):
            self.backend.apply(inventory.Op("test.set_quantity", {"quantity": "4"}), MATT, "Set",
                               expected_revision=before.revision)
        self.assertEqual(self.backend.load().collection().rows[0].quantity, "3")

    def test_token_and_watchlist_rows_keep_their_ids_and_places(self):
        self.import_tree(seed_tree)
        before = self.backend.load()
        ids = [r.id for r in before.token_set().rows]
        self.assertTrue(all(ids) and len(set(ids)) == 3)
        after, _ = self.backend.apply(inventory.Op("test.edit_tokens", {"remove": 0}), MATT, "Remove Treasure")
        self.assertEqual([r.id for r in after.token_set().rows], ids[1:])
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("token_card", "DELETE")])
        add = ("Elf", "", "tltc", "25", "", "nonfoil", "1", "", "", "")
        after, _ = self.backend.apply(inventory.Op("test.edit_tokens", {"add": add, "at": 1, "edit": 0}), MATT,
                                      "Add an Elf")
        self.assertEqual([r.front for r in after.token_set().rows], ["Zombie", "Elf", "Goblin"])
        self.assertEqual([r.id for r in after.token_set().rows][::2], ids[1:])
        self.assertEqual(after.token_set().rows[0].notes, "edited")
        self.assertEqual(sorted((r[0], r[1]) for r in self.trail()[-1]["rows"]),
                         [("token_card", "INSERT"), ("token_card", "UPDATE")])
        watch = [r.id for r in after.watchlist.rows]
        after, _ = self.backend.apply(inventory.Op("test.drop_watch", {"index": 1}), MATT, "Ordered Shock")
        self.assertEqual([r.id for r in after.watchlist.rows], watch[:1] + watch[2:])
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("watchlist_item", "DELETE")])
        self.assertSameModel(after, files.build(files.render(after)).replace(imports=after.imports))

    def test_positions_make_room_or_start_again(self):
        positions = self.pg._positions
        self.assertEqual(positions([1, 2, 3], {1: 1024, 2: 2048, 3: 3072}), [1024, 2048, 3072])
        self.assertEqual(positions([1, 0, 3], {1: 1024, 3: 3072}), [1024, 2048, 3072])
        self.assertEqual(positions([3, 1], {1: 1024, 3: 3072}), [512, 1024])      # one moves, not both
        self.assertEqual(positions([0, 1], {1: 1}), [1024, 2048])          # no room before 1
        self.assertEqual(positions([0, 0], {}), [1024, 2048])

    def test_a_receipt_moves_the_component_without_rewriting_its_rows(self):
        self.import_tree(seed_tree)
        after, _ = self.backend.apply(inventory.Op("test.receive", {"order_id": "2026-10-07-shop-a",
                                                                    "component_id": "cards", "date": "2026-10-12"}),
                                      CLAUDE, "Receive 2026-10-07-shop-a (cards)")
        self.assertIn("magic/orders/received/2026-10-07-shop-a.csv", after.payloads)
        self.assertNotIn("magic/orders/2026-10-07-shop-a.csv", after.payloads)
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("order_component", "UPDATE")])
        self.assertSameModel(after, files.build(files.render(after)).replace(imports=after.imports))

    def test_imports_are_kept_with_their_change_and_never_twice(self):
        self.import_tree(seed_tree)
        after, _ = self.backend.apply(inventory.Op("test.keep_import", {"name": "a.csv"}), MATT, "Import a.csv")
        self.assertEqual(after.imports["user2"], (model.ImportInfo("a.csv", 20),))
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("collection_import", "INSERT")])
        self.assertNotIn("content", self.trail()[-1]["rows"][0][4])
        with self.assertRaisesRegex(ValueError, "magic/people/user2/imports/a.csv already exists"):
            self.backend.apply(inventory.Op("test.keep_import", {"name": "a.csv"}), MATT, "Import a.csv")

    def test_a_snapshot_the_database_cant_hold_is_invalid(self):
        self.import_tree(seed_tree)
        with self.assertRaisesRegex(Invalid, "can't be saved like that: magic/collection.csv line 2: .*'x'"):
            self.backend.apply(inventory.Op("test.set_quantity", {"quantity": "x"}), MATT, "Set")
        self.assertEqual(len(self.trail()), 1)

    def test_the_last_good_snapshot_is_served_while_the_database_is_down(self):
        self.import_tree(seed_tree)
        good = self.backend.load()
        self.breaker.trip("stopped")
        self.assertFalse(self.backend.reachable())
        stale = self.backend.load()
        self.assertRegex(stale.stale, r"^inventory as of \d{4}-\d\d-\d\d \d\d:\d\d: the database isn't reachable$")
        self.assertEqual(stale.replace(stale=None), good)
        with self.assertRaises(Unavailable):
            self.backend.apply(inventory.Op("test.set_quantity"), MATT, "Set")
        self.breaker.reset()
        self.assertIsNone(self.backend.load().stale)
        fresh = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        self.breaker.trip("stopped")
        with self.assertRaises(Unavailable):
            fresh.load()                                    # nothing good to fall back on
        self.breaker.reset()

    def test_two_writers_at_once_both_land(self):
        self.import_tree(seed_tree)
        errors = []

        def write(space, quantity):
            try:
                self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).apply(
                    inventory.Op("test.set_quantity", {"space": space, "quantity": quantity}), MATT, f"Set {space}")
            except Exception as e:                          # noqa: BLE001 (reported below)
                errors.append(e)
        threads = [threading.Thread(target=write, args=args) for args in (("home", "5"), ("user2", "7"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        inv = self.backend.load()
        self.assertEqual((inv.collection().rows[0].quantity, inv.collection("user2").rows[0].quantity), ("5", "7"))

    def test_the_package_api_runs_on_the_database_backend(self):
        self.import_tree(seed_tree)
        with inventory.use(self.backend):
            with inventory.pinned():
                first = inventory.current()
                after, _ = inventory.apply(inventory.Op("test.set_quantity"), MATT, "Set")
                self.assertIs(inventory.current(), after)
            self.assertNotEqual(first.revision, after.revision)
            self.assertEqual(inventory.current().revision, after.revision)

    # -------------------------------------------------------- the foundation review's fixes

    def test_an_op_changing_a_record_in_place_is_saved_and_the_cache_kept(self):
        self.import_tree(seed_tree)
        before = self.backend.load()
        after, _ = self.backend.apply(inventory.Op("test.mutate_record"), MATT, "Notes in place")
        self.assertEqual(after.order("2026-09-29-seller2").notes, "changed in place")
        self.assertEqual(before.order("2026-09-29-seller2").notes, "")       # the cached snapshot is untouched
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("purchase_order", "UPDATE")])
        fresh = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load()
        self.assertEqual(fresh.order("2026-09-29-seller2").notes, "changed in place")

    def test_both_backends_settle_and_refuse_the_same(self):
        """The same ops on the database and on the same tree as files give the same files, and
        the same refusals."""
        self.import_tree(seed_tree)
        tree = build_tree(seed_tree)
        self.addCleanup(tree.doCleanups)
        on_files = FileInventory(tree.inventory.root)
        steps = [("test.rows", {"rows": [("Shock", "m19", "156", "nonfoil", "1"), ("Opt", "dom", "60", "nonfoil", "2")]}),
                 ("test.rows", {"space": "user2", "rows": []}),
                 ("test.receive", {"order_id": "2026-10-07-shop-a", "component_id": "cards", "date": "2026-10-12"})]
        for kind, params in steps:
            with self.subTest(kind=kind, params=params):
                db_after, _ = self.backend.apply(inventory.Op(kind, params), MATT, kind)
                file_after, _ = on_files.apply(inventory.Op(kind, params), MATT, kind)
                self.assertEqual(files.render(db_after), files.render(file_after))
        self.assertNotIn("user2", db_after.collections)
        self.assertEqual([r.set for r in db_after.collection().rows], ["dom", "m19"])
        for kind, params, error in (("test.set_quantity", {"quantity": "x"}, Invalid),
                                    ("test.loose_payload", {}, Invalid),
                                    ("test.tokens_raw", {}, None)):
            with self.subTest(kind=kind):
                outcomes = []
                for backend in (self.backend, on_files):
                    try:
                        backend.apply(inventory.Op(kind, params), MATT, kind)
                        outcomes.append(None)
                    except (Invalid, Conflict) as e:
                        outcomes.append((type(e), str(e)))
                self.assertEqual(outcomes[0], outcomes[1])
                if error:
                    self.assertEqual(outcomes[0][0], error)

    def test_removing_the_last_accessory_leaves_both_backends_the_same(self):
        self.import_tree(built_decks_and_kits)
        tree = build_tree(built_decks_and_kits)
        self.addCleanup(tree.doCleanups)
        on_files = FileInventory(tree.inventory.root)
        db_after, _ = self.backend.apply(inventory.Op("test.no_accessories"), MATT, "remove every accessory")
        file_after, _ = on_files.apply(inventory.Op("test.no_accessories"), MATT, "remove every accessory")
        self.assertFalse(db_after.accessories.exists)
        self.assertFalse((tree.inventory.root / paths.ACCESSORIES).exists())
        self.assertSameModel(db_after, file_after)
        self.assertSameModel(self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load(), on_files.load())

    def test_a_large_import_is_one_quick_change(self):
        self.import_tree(seed_tree)
        rows = [(f"Card {n}", "tst", str(n), "nonfoil", "1") for n in range(1, 20001)]
        started = time.monotonic()
        after, _ = self.backend.apply(inventory.Op("test.rows", {"rows": rows}), MATT, "Import 20,000 cards")
        took = time.monotonic() - started
        self.assertEqual(len(after.collection().rows), 20000)
        self.assertEqual(len(self.trail()), 2)
        self.assertLess(took, 60, f"a 20,000-row write took {took:.1f}s")

    def test_the_database_backend_gives_the_goldens_of_ported_readers(self):
        for name, builder in SCENARIOS.items():
            if name in FILE_ONLY:
                continue
            with self.subTest(scenario=name):
                db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
                with scenario(builder, adapted=True) as case:
                    root = case.inventory.root
                    self.pg.write_model(case.inventory.load(), CLAUDE, "Import", contents=import_contents(root),
                                        dbname=self.dbname, decks=True)
                    # Nothing may read the inventory files now. The snapshot's deck parts are the
                    # database's (imported with decks=True); the files stay, the same bytes, for the
                    # readers phase 4's areas haven't ported yet (the deck page's holder sha256,
                    # lib/accessories), and go here once they're all ported.
                    for rel in files.tree_files(root):
                        (root / rel).unlink()
                    got = expected_p4(run_readers(self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker), root))
                golden = load_golden(name, adapted=True)
                self.assertEqual(set(got), set(golden))
                for key in sorted(PORTED):
                    found = gate.first_difference(golden[key], got[key], f"$[{key!r}]")
                    self.assertIsNone(found, found)

    def test_incoming_source_identity_status_and_allocation_from_database(self):
        # E6-S03's new fields have direct PostgreSQL coverage: the old reader goldens deliberately
        # ignore these additions, while continuing to compare all previous labels and counts.
        from decklab.lib import pool
        from decklab.lib.api.card_lookup import _owned_json

        def incoming(t):
            t.cards_csv("orders/parcel.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2))
            t.product("incoming-precon.csv", ("Main", "Sol Ring", 3), column="section")
            t.status(("incoming-precon.csv", "preordered", ""))
            _records(t, Order.build("2026-10-14-shop", components=[
                Component.build("cards", "cards", "parcel.csv"),
                Component.build("precon", "product", "incoming-precon.csv")]))
            t.deck("incoming", "Incoming", "building", "Deck\n4 Sol Ring\n")

        self.import_tree(incoming)
        snapshot = self.backend.load()
        self.assertEqual(snapshot.backend, "db")
        with fixture_world(), inventory.pinned(snapshot):
            answer = _owned_json(pool.owned_vs_needed("casual/incoming", prices=False))
        self.assertEqual(answer["totals"]["missing"], 0)
        self.assertEqual(answer["rows"][0]["labels"]["incoming_sources"], [
            {"source": "order 2026-10-14-shop", "quantity": 2, "order_id": "2026-10-14-shop",
             "component_id": "cards", "product_id": None, "status": "ordered"},
            {"source": "Incoming Precon", "quantity": 2, "order_id": "2026-10-14-shop",
             "component_id": "precon", "product_id": "incoming-precon", "status": "preordered"}])

    def test_reset_empties_the_inventory(self):
        self.import_tree(seed_tree)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        with self.assertRaises(self.pg.NotImported):
            self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load()
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from collection_import_content").fetchone()[0], 0)


def subprocess_rev(rev):
    """rev's commit sha in this repo, or None when the clone hasn't got it."""
    import subprocess
    done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd=config.REPO,
                          capture_output=True, text=True)
    return done.stdout.strip() or None


class GoldenNormalisationTests(unittest.TestCase):
    def test_standin_defaults_preserve_legacy_counts_and_unrelated_fields(self):
        from decklab.tests import golden_p4

        legacy = {"pools": {"home": {"owned": {"Opt": 1}, "warnings": ["Keep pool warning"],
                                      "in_use": [{"id": "casual/a", "cards": {"Shock": 2}}]}},
                  "deck_view": {"casual/a@target": {"version": "target", "owned": {"missing": 2}}},
                  "assembly": {"a": {"totals": {"need": 4, "waiting": 1, "missing": 2},
                                      "warnings": ["Keep plan warning"], "decks": [{
                                          "id": "casual/a", "version": "target", "need": {"Opt": 4},
                                          "steps": [{"name": "Opt", "need": 4, "waiting": 1, "missing": 2},
                                                    {"name": "Shock", "need": 2, "waiting": 0, "missing": 0}]}]}}}

        def with_defaults():
            answer = json.loads(json.dumps(legacy))
            answer["pools"]["home"]["in_use"][0]["standin_warnings"] = []
            answer["deck_view"]["casual/a@target"]["standins"] = {"version": "target", "rows": [], "warnings": []}
            plan = answer["assembly"]["a"]
            plan["logical_totals"] = dict(plan["totals"])
            deck = plan["decks"][0]
            deck["logical_shortages"] = [{"name": "Opt", "waiting": 1, "missing": 2}]
            deck["standins"] = {"version": "target", "rows": [], "choices": [], "retired": [], "warnings": [],
                                "needs": [{"for": "Opt", "qty": 3, "suggestion": "Shock"}],
                                "candidates": [{"name": "Shock", "free": 3}], "editable": True, "sha256": "abc"}
            return answer

        unrelated = {"standins": {"rows": []}, "logical_totals": {"missing": 9},
                     "logical_shortages": [], "standin_warnings": []}
        original = {**with_defaults(), "by_viewer": {"matt": with_defaults()}, "unrelated": unrelated}
        untouched = json.loads(json.dumps(original))
        with mock.patch.object(golden_p4, "_profiles", return_value={"matt": FIXTURE_PROFILES[0]}):
            normalised = golden_p4.normalise(original)
        self.assertEqual(original, untouched)
        self.assertEqual(normalised, {**legacy, "by_viewer": {"matt": legacy}, "unrelated": unrelated})

    def test_standin_mappings_warnings_and_logical_discrepancies_still_compare(self):
        from decklab.tests import golden_p4

        projection = {"version": "target", "rows": [], "choices": [], "retired": [], "warnings": [],
                      "needs": [], "candidates": [], "editable": True, "sha256": "abc"}
        mapping = {"for": "Opt", "using": "Shock", "qty": 2}
        for field, value in (("rows", [mapping]), ("choices", [mapping]), ("retired", [mapping]),
                             ("warnings", ["Keep stand-in warning"])):
            with self.subTest(field=field):
                evidence = {**projection, field: value}
                dump = {"assembly": {"a": {"decks": [{"version": "target", "standins": evidence}]}}}
                self.assertEqual(golden_p4.normalise(dump), dump)
        for evidence in ({"version": "target", "rows": [mapping], "warnings": []},
                         {"version": "target", "rows": [], "warnings": ["Keep page warning"]},
                         {"version": "owned", "rows": [], "warnings": []}):
            with self.subTest(page=evidence):
                dump = {"deck_view": {"casual/a@target": {"version": "target", "standins": evidence}}}
                self.assertEqual(golden_p4.normalise(dump), dump)
        dump = {"pools": {"home": {"in_use": [{"id": "casual/a", "cards": {"Shock": 2},
                                               "standin_warnings": ["Keep holder warning"]}]}},
                "assembly": {"a": {"totals": {"need": 4, "missing": 2},
                                    "logical_totals": {"need": 4, "missing": 3},
                                    "decks": [{"need": {"Opt": 4},
                                               "steps": [{"name": "Opt", "waiting": 1, "missing": 2}],
                                               "logical_shortages": [{"name": "Opt", "waiting": 1, "missing": 3}]}]}}}
        self.assertEqual(golden_p4.normalise(dump), dump)

    def test_opponent_metadata_is_ignored_only_in_the_additive_api_fields(self):
        from decklab.tests import golden_p4

        def answers():
            return {"decks_index": {"decks": [{"id": "casual/a", "missing": {"target": 2},
                                                "usual_opponents": ["casual/b"]}],
                                     "usual_opponents": {"pairing/a+b": ["casual/a"]}},
                    "deck_view": {"casual/a@target": {"summary": {"id": "casual/a", "usual_opponents": []},
                                                         "owned": {"missing": 2}, "usual_opponents": []}},
                    "assembly": {"empty": {"choices": [{"id": "casual/a", "versions": ["target"],
                                                           "usual_opponents": ["casual/b"]}],
                                            "decks": [{"id": "casual/a", "need": {"Opt": 4}}],
                                            "usual_opponents": {"pairing/a+b": ["casual/a"]}}}}

        original = {**answers(), "by_viewer": {"matt": answers()},
                    "unrelated": {"usual_opponents": ["keep this value"]}}
        untouched = json.loads(json.dumps(original))
        with mock.patch.object(golden_p4, "_profiles", return_value={"matt": FIXTURE_PROFILES[0]}):
            normalised = golden_p4.normalise(original)
        self.assertEqual(original, untouched)
        self.assertEqual(normalised["unrelated"], original["unrelated"])
        for mine in (normalised, normalised["by_viewer"]["matt"]):
            self.assertEqual(mine["decks_index"], {"decks": [{"id": "casual/a", "missing": {"target": 2}}]})
            self.assertEqual(mine["deck_view"], {"casual/a@target": {"summary": {"id": "casual/a"},
                                                                     "owned": {"missing": 2}}})
            self.assertEqual(mine["assembly"], {"empty": {
                "choices": [{"id": "casual/a", "versions": ["target"]}],
                "decks": [{"id": "casual/a", "need": {"Opt": 4}}]}})


class GoldenTests(unittest.TestCase):
    """The files backend gives today's readers' goldens for every scenario, raw and adapted, and
    for the test Sandbox (no database needed)."""

    def test_every_golden_is_there(self):
        expected = {golden_path(name, adapted).name for name, _, adapted in golden_cases()}
        self.assertEqual({p.name for p in GOLDENS.glob("*.json")}, expected)

    def test_the_files_backend_gives_every_golden(self):
        for name, builder, adapted in golden_cases():
            with self.subTest(scenario=name, adapted=adapted):
                got = expected_p4(sandbox_dump() if builder is None else scenario_dump(builder, adapted))
                found = gate.first_difference(load_golden(name, adapted), got)
                self.assertIsNone(found, found)


# ------------------------------------------------------------------ the command line's registry

class CommandRegistryTests(unittest.TestCase):

    def test_inventory_modules_are_found_and_registered(self):
        import argparse
        import sys
        import types
        from decklab.db import __main__ as cli
        seen = []
        fake = types.ModuleType("decklab.db.inv_fake")

        def check(args):
            seen.append(inventory.is_pinned())
            return 0

        def register(sub):
            sub.add_parser("fake-inventory").set_defaults(func=check)
        fake.register = register
        info = mock.Mock()
        info.name, info.ispkg = "inv_fake", False
        other = mock.Mock()
        other.name, other.ispkg = "wishlist_cli", False
        with mock.patch.object(cli.pkgutil, "iter_modules", return_value=[other, info]), \
                mock.patch.dict(sys.modules, {"decklab.db.inv_fake": fake}):
            self.assertEqual(cli.inventory_modules(), ["inv_fake"])
            self.assertEqual(cli.main(["fake-inventory"]), 0)
        self.assertEqual(seen, [True])
        broken = types.ModuleType("decklab.db.inv_broken")
        with mock.patch.dict(sys.modules, {"decklab.db.inv_broken": broken}):
            with self.assertRaisesRegex(ImportError, "register"):
                cli.register_inventory(argparse.ArgumentParser().add_subparsers(), ["inv_broken"])

    def test_no_inventory_module_has_landed_unregistered(self):
        from decklab.db import __main__ as cli
        for name in cli.inventory_modules():
            with self.subTest(module=name):
                import importlib
                self.assertTrue(callable(getattr(importlib.import_module(f"decklab.db.{name}"), "register", None)))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--write-goldens"]:
        write_goldens(sys.argv[2:] or None)
    else:
        unittest.main()
