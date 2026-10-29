"""Tests for phase 4's database half (migration 0006, inventory/pg_decks.py and PgInventory's decks
part; the phase 4 design's D3 with amendments R1-R6 and R10): the decks part saved and read back
apart from the inventory, deck revisions and their numbering, kit_version, the derived deck_line
rows, accessories and pictures, the decks' import (with a git history, and again with replace),
and the database before migration 0006 and before the decks' import. Every test runs in a
throwaway database (they skip without one: db_support.py).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inventory_pg_decks
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import inventory
from decklab.lib.inventory import Op, Summary, files, ops_decks, paths, pg_decks, register  # noqa: F401 (ops_decks registers)
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import ImageMeta
from decklab.lib.state import Actor, Invalid, Unavailable
from decklab.lib.state import rules as state_rules
from decklab.tests import db_support
from decklab.tests import test_pool as support
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, MATT, seed_tree

DECK = support.deck_md("Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n\nSideboard\n1 Opt\n")
OTHER = support.deck_md("Other", "building", "Deck\n4 Opt (DOM) 60\n")
KIT = DECK.replace("- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n")
ACCESSORIES = ("id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n"
               "a-sleeves,sleeves,matt,DS,Matte,red,100,,a-sleeves.jpg,,,,\n"
               "b-box,deck_box,shared,UG,Boulder,black,2,100,,,,,\n")
PICTURE = b"\x89PNG\r\n\x1a\n" + bytes(range(256))


def _mat(inv, content=b"mat\r\n"):
    rows = [r.as_dict() for r in inv.accessories.rows] + [
        {"id": "c-mat", "kind": "playmat", "owner": "user1", "name": "Mat", "quantity": "1", "image": "c-mat.png"}]
    return inv.with_accessories(rows).with_image("c-mat.png", content), Summary("add a mat")


def _unmat(inv):
    rows = [r.as_dict() for r in inv.accessories.rows if r.text("id") != "c-mat"]
    return inv.with_accessories(rows).without_image("c-mat.png"), Summary("remove the mat")


def _collection(inv):
    row = {"name": "Opt", "set": "dom", "collector_number": "60", "finish": "nonfoil", "quantity": "5"}
    return inv.with_collection("home", [row]), Summary("set the collection")


def _deck_and_cards(inv):
    deck = inv.deck("casual/test")
    inv, _ = _collection(inv.with_deck(deck.replace(text=deck.text + "\nBoth.\n")))
    return inv, Summary("both")


def _kit(inv, text=KIT, deck_id="casual/test"):
    """A deck's text set as kit.set will set it (deck.save refuses a kit change)."""
    return inv.with_deck(inv.deck(deck_id).replace(text=text)), Summary("set the kit")


def _drop(inv, deck_id="casual/test"):
    """A deck removed whatever it holds (deck.delete refuses a built deck with a kit)."""
    return inv.without_deck(deck_id), Summary("drop the deck")


def _cards_refreshing(inv):
    row = {"name": "Opt", "set": "dom", "collector_number": "60", "finish": "nonfoil", "quantity": "6"}
    return inv.with_collection("home", [row]), Summary("cards, refreshing the tables")


TEST_OPS = {"test.mat": _mat, "test.unmat": _unmat, "test.collection": _collection,
            "test.deck_and_cards": _deck_and_cards, "test.kit": _kit, "test.drop": _drop}


class _Db(db_support.DbTestCase):
    """A throwaway database with the fixture profiles, emptied before each test."""

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
        for kind, fn in TEST_OPS.items():
            register(kind)(fn)
            self.addCleanup(inventory.unregister, kind)
        register("test.cards_refreshing", refresh=True)(_cards_refreshing)
        self.addCleanup(inventory.unregister, "test.cards_refreshing")

    def tree(self):
        """A test_pool tree (seed_tree's inventory) with two decks, accessories.csv and a picture;
        the caller's cleanup removes it. Returns the PoolTestCase."""
        case = support.PoolTestCase()
        case.setUp()
        self.addCleanup(case.doCleanups)
        for folder in ("orders/records", "orders/cancelled", "orders/tokens/received", "people/user2/imports"):
            (case.magic / folder).mkdir(parents=True, exist_ok=True)
        seed_tree(case)
        case.write("decks/casual/test.md", DECK)
        case.write("decks/commander/other.md", OTHER)
        case.write("accessories.csv", ACCESSORIES)
        (case.magic / "accessories/images").mkdir(parents=True)
        (case.magic / "accessories/images/a-sleeves.jpg").write_bytes(PICTURE)
        return case

    def import_tree(self):
        """The tree imported (inventory and deck parts); returns (its snapshot, the database backend)."""
        from decklab.tests.test_inventory_contract import adapt, import_contents
        case = self.tree()
        inv = adapt(case.inventory.load())
        self.pg.write_model(inv, CLAUDE, "Import", contents=import_contents(case.inventory.root), dbname=self.dbname,
                            decks=True, images={"a-sleeves.jpg": PICTURE})
        self.case = case
        return inv, self.backend()

    def backend(self):
        return self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)

    def rows(self, query, *args):
        with self.connect() as c:
            return c.execute(query, args).fetchall()

    def apply(self, backend, op_kind, actor=MATT, message=None, **params):
        return backend.apply(Op(op_kind, params), actor, message or op_kind)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DecksPartTests(_Db):

    def test_the_import_reads_back_and_is_one_change(self):
        inv, backend = self.import_tree()
        loaded = backend.load()
        self.assertEqual(loaded.decks, inv.decks)
        self.assertEqual(loaded.accessories, inv.accessories)
        self.assertEqual(loaded.accessory_images, inv.accessory_images)
        self.assertEqual(loaded.decks_revision, "1")
        self.assertEqual(backend.image("a-sleeves.jpg"), PICTURE)                  # raw: never CRLF'd
        self.assertIsNone(backend.image("a-sleeves.jpg", "0" * 64))
        self.assertIsNone(backend.image("nothing.jpg"))
        self.assertEqual(self.rows("select deck_id, revision, op, change_set_id is not null, actor from deck_revision "
                                   "order by 1"), [("casual/test", 1, "A", True, "claude"),
                                                   ("commander/other", 1, "A", True, "claude")])
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(1,)])
        self.assertEqual(backend.decks_revision(), "1")

    def test_a_deck_save_moves_only_the_decks_part(self):
        _, backend = self.import_tree()
        before = backend.load()
        with mock.patch.object(self.pg, "_select", wraps=self.pg._select) as inventory_select:
            after, summary = self.apply(backend, "deck.save", deck_id="casual/test", text=DECK + "\nMore.\n",
                                        base_sha256=before.deck("casual/test").sha256, message="save Test")
        inventory_select.assert_not_called()                     # the inventory isn't read again
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(int(after.decks_revision), int(before.decks_revision) + 1)
        self.assertEqual((after.deck("casual/test").text, after.deck("casual/test").revision), (DECK + "\nMore.\n", 2))
        self.assertEqual(after.collections, before.collections)
        self.assertIs(backend.load(), after)                     # cached
        fresh = self.backend().load()
        self.assertEqual(fresh.deck("casual/test").revision, 2)
        self.assertEqual(fresh, after)
        revision = self.rows("select r.op, r.actor, r.message, r.text, r.at = cs.at from deck_revision r "
                             "join audit.change_set cs on cs.id = r.change_set_id where r.deck_id = 'casual/test' "
                             "and r.revision = 2")
        self.assertEqual(revision, [("M", "matt", "save Test", DECK + "\nMore.\n", True)])
        audited = self.rows("select table_name, op from audit.row_change where change_set_id = "
                            "(select max(id) from audit.change_set)")
        self.assertEqual(audited, [("deck", "UPDATE")])

    def test_an_inventory_write_doesnt_read_the_deck_texts_again(self):
        _, backend = self.import_tree()
        before = backend.load()
        with mock.patch.object(pg_decks, "select", wraps=pg_decks.select) as deck_select:
            after, _ = self.apply(backend, "test.collection")
            again = backend.load()
        deck_select.assert_not_called()
        self.assertIs(again, after)
        self.assertEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(after.decks, before.decks)
        self.assertNotEqual(after.revision, before.revision)

    def test_one_write_of_both_parts_bumps_both(self):
        _, backend = self.import_tree()
        before = backend.load()
        after, _ = self.apply(backend, "test.deck_and_cards")
        self.assertNotEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(self.rows("select count(*) from audit.change_set"), [(2,)])

    def test_delete_and_make_again_carries_on_the_numbers(self):
        _, backend = self.import_tree()
        sha = backend.load().deck("casual/test").sha256
        after, _ = self.apply(backend, "deck.delete", deck_id="casual/test", base_sha256=sha)
        self.assertIsNone(after.deck("casual/test"))
        self.assertEqual(self.rows("select count(*) from deck_line where deck_id = 'casual/test'"), [(0,)])
        after, _ = self.apply(backend, "deck.create", space="home", kind="casual", slug="test", text=OTHER)
        self.assertEqual(after.deck("casual/test").revision, 3)
        self.assertEqual(self.rows("select revision, op, text is null from deck_revision where deck_id = 'casual/test' "
                                   "order by revision"), [(1, "A", False), (2, "D", True), (3, "A", False)])

    def test_kit_changes_count_in_kit_version_and_never_show_their_values(self):
        _, backend = self.import_tree()
        sha = backend.load().deck("casual/test").sha256
        with self.assertRaises(ops_decks.DeckRefused) as refused:
            self.apply(backend, "deck.save", deck_id="casual/test", text=KIT, base_sha256=sha)
        self.assertEqual(refused.exception.reason, "kit")       # only kit.set changes the kit
        after, _ = self.apply(backend, "test.kit")
        self.assertEqual(self.rows("select kit_version, status, title, played_by from deck where id = 'casual/test'"),
                         [(1, "built", "Test", "either")])
        before_row, after_row = self.rows("select before, after from audit.row_change where table_name = 'deck' "
                                          "order by id desc limit 1")[0]
        self.assertTrue(state_rules.kit_changed({"table": "deck", "op": "UPDATE", "before": before_row,
                                                 "after": after_row}))
        self.assertNotIn("a-sleeves", repr(after_row))
        self.apply(backend, "deck.save", deck_id="casual/test", text=KIT + "\nProse.\n",
                   base_sha256=after.deck("casual/test").sha256)
        self.assertEqual(self.rows("select kit_version from deck where id = 'casual/test'"), [(1,)])

    def test_deck_line_follows_every_text(self):
        _, backend = self.import_tree()
        inv = backend.load()
        self.apply(backend, "deck.save", deck_id="casual/test", text=DECK.replace("2 Llanowar", "3 Llanowar"),
                   base_sha256=inv.deck("casual/test").sha256)
        for deck in backend.load().decks.values():
            parsed = pg_decks.parsed(deck.id, deck.text)
            with self.subTest(deck.id):
                found = self.rows("select deck_id, version, section, position, quantity, name, set_code, "
                                  "collector_number, finish from deck_line where deck_id = %s "
                                  "order by version desc, section, position", deck.id)
                self.assertEqual(sorted(found), sorted(pg_decks.lines(deck.id, parsed)))
        self.assertEqual(self.rows("select quantity, set_code from deck_line where deck_id = 'casual/test' and "
                                   "name = 'Llanowar Elves'"), [(3, "fdn")])

    def test_a_text_with_carriage_returns_is_refused(self):
        _, backend = self.import_tree()
        sha = backend.load().deck("casual/test").sha256
        with self.assertRaisesRegex(Invalid, "carriage returns"):
            self.apply(backend, "deck.save", deck_id="casual/test", text=DECK.replace("\n", "\r\n"), base_sha256=sha)
        self.assertEqual(backend.load().deck("casual/test").revision, 1)

    def test_accessories_and_pictures(self):
        _, backend = self.import_tree()
        after, _ = self.apply(backend, "test.mat", actor=Actor("user1", "User1", "home"))
        self.assertEqual([r.text("id") for r in after.accessories.rows], ["a-sleeves", "b-box", "c-mat"])
        self.assertEqual(after.image_meta("c-mat.png"), ImageMeta.of("c-mat.png", b"mat\r\n"))
        self.assertEqual(backend.image("c-mat.png"), b"mat\r\n")
        audited = self.rows("select table_name, op from audit.row_change where change_set_id = "
                            "(select max(id) from audit.change_set)")
        self.assertEqual(audited, [("accessory", "INSERT")])
        after, _ = self.apply(backend, "test.unmat")
        self.assertIsNone(after.image_meta("c-mat.png"))
        self.assertEqual(self.rows("select count(*) from accessory_image"), [(1,)])

    def test_a_changed_picture_needs_its_bytes(self):
        _, backend = self.import_tree()

        def bad(inv):
            images = dict(inv.accessory_images)
            images["x.jpg"] = ImageMeta("x.jpg", 1, "0" * 64)
            return inv.replace(accessory_images=images), Summary("bad")
        register("test.bad_picture")(bad)
        self.addCleanup(inventory.unregister, "test.bad_picture")
        with self.assertRaisesRegex(ValueError, "needs its bytes"):
            self.apply(backend, "test.bad_picture")

    def test_both_backends_save_the_same_files(self):
        _, backend = self.import_tree()
        on_files = FileInventory(self.case.inventory.root)
        steps = [("test.kit", {}), ("deck.save", {"deck_id": "casual/test", "text": KIT + "\nProse.\n"}),
                 ("deck.create", {"space": "home", "kind": "casual", "slug": "goblins", "text": OTHER}),
                 ("deck.delete", {"deck_id": "commander/other"}), ("test.mat", {})]
        for kind, params in steps:
            with self.subTest(kind):
                outs = []
                for each in (backend, on_files):
                    p = dict(params)
                    if kind in ("deck.save", "deck.delete"):
                        p["base_sha256"] = each.load().deck(p["deck_id"]).sha256
                    after, _ = each.apply(Op(kind, p), MATT, kind)
                    outs.append(after)
                rendered = [{rel: data for rel, data in files.render(out, decks=True).items() if paths.is_deck_part(rel)}
                            for out in outs]
                self.assertEqual(rendered[0], rendered[1])
                self.assertEqual(outs[0].accessory_images, outs[1].accessory_images)
                self.assertEqual(outs[0].decks, outs[1].decks)

    def test_revisions_flag_kit_changes_and_keep_their_words_for_their_actor(self):
        _, backend = self.import_tree()
        user1 = Actor("user1", "User1", "home")
        self.apply(backend, "test.kit", actor=user1, message="choose a-sleeves for Test")
        inv = backend.load()
        self.apply(backend, "deck.save", deck_id="casual/test", text=KIT + "\nProse.\n",
                   base_sha256=inv.deck("casual/test").sha256, message="prose")
        self.apply(backend, "test.drop", actor=user1, message="drop Test")
        self.assertEqual(self.rows("select revision, op, kit from deck_revision where deck_id = 'casual/test' "
                                   "order by revision"), [(1, "A", False), (2, "M", True), (3, "M", False),
                                                          (4, "D", True)])
        listed = backend.deck_revisions("casual/test")
        self.assertEqual([(r.revision, r.op, r.kit, r.actor) for r in listed],
                         [(4, "D", True, "user1"), (3, "M", False, "matt"), (2, "M", True, "user1"),
                          (1, "A", False, "claude")])
        self.assertTrue(all(r.text is None for r in listed))
        second = backend.deck_revision("casual/test", 2)
        self.assertEqual((second.text, second.message), (KIT, "choose a-sleeves for Test"))
        self.assertEqual(second.message_for("user1"), "choose a-sleeves for Test")
        self.assertIsNone(second.message_for("matt"))            # an admin's view too
        self.assertEqual(second.message_for(None, everything=True), "choose a-sleeves for Test")
        self.assertEqual(backend.deck_revision("casual/test", 3).message_for("user1"), "prose")
        self.assertIsNone(backend.deck_revision("casual/test", 9))
        self.assertEqual(backend.last_revision("casual/test").revision, 4)
        self.assertIsNone(backend.last_revision("casual/none"))
        with inventory.use(backend):
            self.assertEqual(inventory.last_revision("commander/other").op, "A")
            self.assertEqual(inventory.image("a-sleeves.jpg"), PICTURE)

    def test_the_last_good_snapshot_without_its_decks_is_refused_once_migrated(self):
        from decklab.tests.test_inventory_contract import adapt, build_scenario
        inv, contents = build_scenario(seed_tree)
        self.pg.write_model(adapt(inv), CLAUDE, "Import the inventory", contents=contents, dbname=self.dbname)
        backend = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        self.assertEqual(dict(backend.load().decks), {})                    # no decks until they're there
        self.breaker.trip("stopped")
        with self.assertRaisesRegex(Unavailable, "decks weren't loaded"):
            backend.load()
        self.breaker.reset()
        self.pg.write_decks(files.build({"magic/decks/casual/test.md": (DECK + "db\n").encode()}), CLAUDE,
                            "Import the decks", dbname=self.dbname)
        self.assertEqual(backend.load().deck("casual/test").text, DECK + "db\n")
        self.breaker.trip("stopped")
        stale = backend.load()                                              # served with its decks part
        self.assertTrue(stale.stale)
        self.assertEqual(stale.deck("casual/test").text, DECK + "db\n")
        self.breaker.reset()

    def test_the_slug_is_unique_in_a_space_and_kind_whatever_the_case(self):
        self.import_tree()
        from decklab.db import conn as db
        import psycopg
        with self.connect(autocommit=True) as c, self.assertRaises(psycopg.errors.UniqueViolation):
            with db.change("matt", "cli", "a clash", conn=c) as (cur, _):
                cur.execute("insert into deck (id, space_id, kind, slug, revision) values "
                            "('casual/Test', 'home', 'casual', 'Test', 1)")


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DeckImportTests(_Db):

    def setUp(self):
        super().setUp()
        self.import_inventory()

    def import_inventory(self):
        from decklab.tests.test_inventory_contract import adapt, build_scenario
        inv, contents = build_scenario(seed_tree)
        self.pg.write_model(adapt(inv), CLAUDE, "Import the inventory", contents=contents, dbname=self.dbname)

    def deck_parts(self, texts=None, accessories=ACCESSORIES):
        out = {f"magic/decks/{deck_id}.md": text.encode() for deck_id, text in (texts or {
            "casual/test": DECK, "commander/other": OTHER}).items()}
        if accessories is not None:
            out["magic/accessories.csv"] = accessories.encode()
        out["magic/accessories/images/a-sleeves.jpg"] = PICTURE
        inv = files.build(out)
        return inv.replace(accessory_images={"a-sleeves.jpg": ImageMeta.of("a-sleeves.jpg", PICTURE)})

    def test_until_the_decks_are_imported_the_decks_part_is_empty(self):
        backend = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        loaded = backend.load()
        self.assertEqual((dict(loaded.decks), loaded.accessories.rows, dict(loaded.accessory_images)), ({}, (), {}))
        self.assertEqual(backend.decks_revision(), loaded.decks_revision)
        self.assertEqual(backend.decks_revision(), files.build({}).decks_revision)
        self.assertIsNone(backend.image("a-sleeves.jpg"))
        with self.assertRaisesRegex(Unavailable, "the database holds no decks"):
            self.apply(backend, "deck.create", space="home", kind="casual", slug="test", text=DECK)
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import the decks", dbname=self.dbname)
        loaded = backend.load()
        self.assertEqual(sorted(loaded.decks), ["casual/test", "commander/other"])     # the database's now
        self.assertEqual(loaded.decks_revision, "1")

    def test_an_inventory_change_goes_ahead_while_deck_saves_are_paused(self):
        backend = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        self.assertFalse(backend.saves_decks())
        self.assertEqual(backend.deck_revisions("casual/test"), [])
        self.assertIsNone(backend.last_revision("casual/test"))
        with inventory.use(backend):
            after, summary = inventory.apply(Op("test.cards_refreshing"), MATT, "cards")
        self.assertEqual(summary.extra["tables"]["error"], inventory.DECK_SAVES_PAUSED)
        self.assertEqual([r.text("quantity") for r in after.collection().rows], ["6"])
        self.assertEqual(dict(after.decks), {})
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import the decks", dbname=self.dbname)
        self.assertTrue(backend.saves_decks())

    def test_kit_flags_in_an_imported_history_and_a_replacing_import(self):
        when = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
        history = [{"deck_id": "casual/test", "at": when, "actor": "matt", "message": m, "op": op,
                    "git_commit": c * 40, "text": text}
                   for m, op, c, text in (("Add", "A", "a", DECK), ("Sleeve it", "M", "b", KIT),
                                          ("Prose", "M", "c", KIT + "x\n"), ("Unsleeve", "M", "d", DECK))]
        history.append({"deck_id": "commander/other", "at": when, "actor": "matt", "message": "Add Other",
                        "op": "A", "git_commit": "a" * 40, "text": OTHER})
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import", history=history, dbname=self.dbname)
        self.assertEqual(self.rows("select revision, kit from deck_revision where deck_id = 'casual/test' "
                                   "order by revision"), [(1, False), (2, True), (3, False), (4, True)])
        self.pg.write_decks(self.deck_parts({"casual/test": KIT, "commander/other": OTHER}), CLAUDE, "Again",
                            replace=True, dbname=self.dbname)
        self.assertEqual(self.rows("select revision, op, kit from deck_revision where deck_id = 'casual/test' "
                                   "order by revision desc limit 1"), [(5, "M", True)])

    def test_refusals(self):
        with self.assertRaisesRegex(self.pg.Unrepresentable, "carriage returns"):
            self.pg.write_decks(self.deck_parts({"casual/test": DECK.replace("\n", "\r\n")}), CLAUDE, "x",
                                dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "has no rows"):
            self.pg.write_decks(self.deck_parts(accessories=ACCESSORIES.splitlines()[0] + "\n"), CLAUDE, "x",
                                dbname=self.dbname)
        inv = self.deck_parts()
        with self.assertRaisesRegex(self.pg.Unrepresentable, "content wasn't given"):
            self.pg.write_decks(inv.replace(accessory_images={"a-sleeves.jpg": ImageMeta("a-sleeves.jpg", 5, "0" * 64)}),
                                CLAUDE, "x", dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "isn't the picture"):
            self.pg.write_decks(self.deck_parts(), CLAUDE, "x", images={"a-sleeves.jpg": b"other"}, dbname=self.dbname)
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import", dbname=self.dbname)
        with self.assertRaisesRegex(ValueError, "replace-decks"):
            self.pg.write_decks(self.deck_parts(), CLAUDE, "Again", dbname=self.dbname)

    def test_a_history_from_git(self):
        when = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
        history = [
            {"deck_id": "casual/test", "at": when, "actor": "matt", "message": "Add Test\n\nbody", "op": "A",
             "git_commit": "a" * 40, "text": DECK + "old\n"},
            {"deck_id": "commander/gone", "at": when, "actor": "claude", "message": "Add Gone", "op": "A",
             "git_commit": "a" * 40, "text": OTHER},
            {"deck_id": "casual/test", "at": when, "actor": "user1", "message": "Edit Test", "op": "M",
             "git_commit": "b" * 40, "text": DECK},
            {"deck_id": "commander/gone", "at": when, "actor": "claude", "message": "Delete Gone", "op": "D",
             "git_commit": "c" * 40, "text": None},
            {"deck_id": "commander/other", "at": when, "actor": "matt", "message": "Add Other", "op": "A",
             "git_commit": "c" * 40, "text": OTHER}]
        bad = [dict(history[0], text=DECK + "not the end\n")] + history[1:]
        with self.assertRaisesRegex(ValueError, "isn't its last revision's"):
            self.pg.write_decks(self.deck_parts(), CLAUDE, "Import", history=bad[:2] + bad[3:], dbname=self.dbname)
        with self.assertRaisesRegex(ValueError, "doesn't end with its deletion"):
            self.pg.write_decks(self.deck_parts(), CLAUDE, "Import", history=history[:3] + history[4:],
                                dbname=self.dbname)
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import the decks", history=history, dbname=self.dbname)
        found = self.rows("select deck_id, revision, change_set_id, at, actor, op, git_commit from deck_revision "
                          "order by deck_id, revision")
        self.assertEqual([r[:2] + r[4:] for r in found], [
            ("casual/test", 1, "matt", "A", "a" * 40), ("casual/test", 2, "user1", "M", "b" * 40),
            ("commander/gone", 1, "claude", "A", "a" * 40), ("commander/gone", 2, "claude", "D", "c" * 40),
            ("commander/other", 1, "matt", "A", "c" * 40)])
        self.assertTrue(all(r[2] is None and r[3] == when for r in found))
        loaded = self.backend().load()
        self.assertEqual({d.id: d.revision for d in loaded.decks.values()}, {"casual/test": 2, "commander/other": 1})

    def test_replace_keeps_the_history(self):
        self.pg.write_decks(self.deck_parts(), CLAUDE, "Import", dbname=self.dbname)
        changed = self.deck_parts({"casual/test": DECK + "\nNew.\n", "casual/fresh": OTHER})
        self.pg.write_decks(changed, CLAUDE, "Import again", replace=True, dbname=self.dbname)
        self.assertEqual(self.rows("select deck_id, revision, op from deck_revision order by 1, 2"), [
            ("casual/fresh", 1, "A"), ("casual/test", 1, "A"), ("casual/test", 2, "M"),
            ("commander/other", 1, "A"), ("commander/other", 2, "D")])
        loaded = self.backend().load()
        self.assertEqual(loaded.decks_revision, "2")
        self.assertEqual(sorted(loaded.decks), ["casual/fresh", "casual/test"])


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class BeforeMigration6Tests(unittest.TestCase):
    """A database migrated only to 0005 (as production was until the phase 4 cutover): the backend
    and the nightly export work, with an empty decks part and their saves paused; once migrated
    and the decks imported, they come from the database."""

    def test_the_backend_and_the_export_until_0006_and_after(self):
        from decklab.db import conn as db, export, migrate, profiles_sync, setup
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import adapt, build_scenario
        name = db_support.create_empty_database("p4")
        self.addCleanup(db_support.drop_database, name)
        early = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, early, True)
        for f in migrate.available():
            if f["version"] <= 5:
                shutil.copy(f["path"], early / Path(f["path"]).name)
        migrate.apply(dbname=name, directory=early)
        setup.secure_database(name)
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=name)
        inv, contents = build_scenario(seed_tree)
        pg.write_model(adapt(inv), CLAUDE, "Import the inventory", contents=contents, dbname=name)
        backend = pg.PgInventory(dbname=name, breaker=state_pg.Breaker())
        self.assertEqual(dict(backend.load().decks), {})
        with self.assertRaises(Unavailable):
            backend.apply(Op("deck.create", {"space": "home", "kind": "casual", "slug": "test", "text": DECK}),
                          MATT, "create")
        with db.connect("owner", dbname=name) as c, c.transaction():
            real = pg.PgInventory
            with mock.patch.object(pg, "PgInventory", lambda **_: real(dbname=name)):
                self.assertIn("magic/collection.csv", export.inventory_files(c))
        with self.assertRaisesRegex(ValueError, "migrate first"):
            pg.write_decks(files.build({"magic/decks/casual/test.md": DECK.encode()}), CLAUDE, "Import", dbname=name)
        migrate.apply(dbname=name)
        self.assertEqual(dict(backend.load().decks), {})                        # still none
        pg.write_decks(files.build({"magic/decks/casual/test.md": (DECK + "db\n").encode()}), CLAUDE, "Import",
                       dbname=name)
        self.assertEqual(backend.load().deck("casual/test").text, DECK + "db\n")


if __name__ == "__main__":
    unittest.main()
