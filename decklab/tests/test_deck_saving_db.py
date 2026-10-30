"""The editor's deck saves (api/saving.py) and the precon add (api/precons.py) with the decks in a
throwaway database (the phase 4 design's R4; area B): each save is one inventory operation and
one deck revision, a 409 names who saved the deck since from its revisions (by, when, the
message's first line, and nothing about git), a deleted deck's 409 names it
by its last title, a deck that never existed is 404, update_tables is one change, and a precon's
cards and deck are one change. The sandbox's deck files are deleted after the import, so every
deck read or written here is the database's.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_deck_saving_db
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import shutil
import unittest

from decklab.lib import api, inventory
from decklab.lib.inventory import Op
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor
from decklab.tests import db_support
from decklab.tests.test_editor import TABLE_DECK, EditorTestCase
from decklab.tests.test_precons import PreconTestCase
from decklab.tests.test_pool import deck_md

USER1 = Actor("user1", "User1", "home")


def into_database(case):
    """Import case's sandbox (inventory and deck parts) into case.dbname, delete its deck files and
    install the database backend for the test; returns it."""
    from decklab.lib.inventory import pg
    from decklab.lib.state import pg as state_pg
    from decklab.tests.test_inventory_contract import CLAUDE, adapt, import_contents
    db_support.reset(case.dbname, db_support.INVENTORY_TABLES)
    root = case.box.root
    pictures = root / "magic" / "accessories" / "images"
    images = {p.name: p.read_bytes() for p in pictures.iterdir()} if pictures.is_dir() else {}
    pg.write_model(adapt(FileInventory(root).load()), CLAUDE, "Import", contents=import_contents(root),
                   dbname=case.dbname, decks=True, images=images)
    shutil.rmtree(root / "magic" / "decks")
    for person in (root / "magic" / "people").glob("*/decks"):
        shutil.rmtree(person)
    backend = pg.PgInventory(dbname=case.dbname, breaker=state_pg.Breaker())
    case.addCleanup(inventory.use(backend))
    return backend


class _Profiles(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def sql(self, query, *args):
        with self.connect() as c:
            return c.execute(query, args).fetchall()


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseAssemblyCompletionTests(EditorTestCase, _Profiles):
    def setUp(self):
        super().setUp()
        for slug, title in (("table-test", "Builder A"), ("build-two", "Builder B")):
            self.path("casual/" + slug).write_text(deck_md(title, "building", "Deck\n60 Forest\n"),
                                                  encoding="utf-8", newline="\n")
        self.path("casual/broken").write_text(deck_md("Unselected", "idea", "Deck\n60 Forest\n"),
                                             encoding="utf-8", newline="\n")
        self.backend = into_database(self)

    def test_two_built_decks_share_one_audit_change_and_keep_inventory_unchanged(self):
        from decklab.lib.api import assembly, assembly_completion
        choices = [{"id": "casual/table-test", "version": "target"},
                   {"id": "casual/build-two", "version": "target"}]
        plan = assembly.assembly_preview(self.body(decks=choices))
        self.assertTrue(plan["ready"], plan["warnings"])
        before = inventory.current()
        changes = self.sql("select count(*) from audit.change_set")[0][0]
        answer = assembly_completion.mark_built(self.body(decks=choices, confirmed=True,
                                                         fingerprint=plan["completion"]["fingerprint"]))
        after = inventory.current()
        self.assertTrue(answer["saved"])
        self.assertEqual(before.revision, after.revision)
        self.assertNotEqual(before.decks_revision, after.decks_revision)
        self.assertEqual(self.sql("select count(*) from audit.change_set")[0][0], changes + 1)
        latest = self.sql("select deck_id, actor, message, change_set_id from deck_revision "
                          "where revision = 2 order by deck_id")
        self.assertEqual([r[0] for r in latest], ["casual/build-two", "casual/table-test"])
        self.assertEqual({r[1] for r in latest}, {"matt"})
        self.assertEqual(len({r[3] for r in latest}), 1)
        self.assertTrue(all(r[2] == "mark built: Builder A, Builder B" for r in latest))
        self.assertFalse((self.box.magic / "decks").exists())


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseSaveTests(EditorTestCase, _Profiles):

    def setUp(self):
        super().setUp()
        self.backend = into_database(self)

    def sha(self, deck_id):
        return inventory.current().deck(deck_id).sha256

    def text(self, deck_id):
        return inventory.current().deck(deck_id).text

    def revisions(self, deck_id):
        return self.sql("select revision, op, actor, message, change_set_id is not null from deck_revision "
                         "where deck_id = %s order by revision", deck_id)

    def test_a_save_is_one_revision_in_the_database(self):
        before = self.text("casual/table-test")
        answer = self.save("casual/table-test", fields={"status": "built"}, profile="user1")
        self.assertFalse((self.box.magic / "decks").exists())               # nothing written to files
        self.assertEqual((answer["changed"], answer["sha256"]), (True, self.sha("casual/table-test")))
        self.assertNotIn("commit", answer)
        self.assertIn("- **Status:** built", self.text("casual/table-test"))
        self.assertNotEqual(self.text("casual/table-test"), before)
        self.assertEqual(self.revisions("casual/table-test"),
                         [(1, "A", "claude", "Import", True), (2, "M", "user1", "save Table Test", True)])
        self.assertEqual(answer["deck"]["sha256"], answer["sha256"])
        # A save that changes nothing saves no revision.
        again = self.save("casual/table-test", fields={"status": "built"})
        self.assertEqual(again["changed"], False)
        self.assertEqual(len(self.revisions("casual/table-test")), 2)

    def test_the_409_names_who_saved_it_from_the_revisions(self):
        view = api.edit_view("casual/table-test")
        self.save("casual/table-test", fields={"status": "built"}, profile="user1")
        error = self.assertApiError(409, api.save_deck, self.body(
            id="casual/table-test", sha256=view["sha256"], fields={"status": "idea"}))
        self.assertRegex(error.message, r"^Table Test changed after you opened it: User1 saved it in Deck Lab at "
                                        r"\d{1,2}:\d\d [ap]m today\. Your changes weren't saved\.$")
        conflict = error.extra["conflict"]
        self.assertEqual({k: v for k, v in conflict.items() if k != "when"},
                         {"reason": "changed", "by": "User1", "deck_lab": True, "subject": "save Table Test"})
        self.assertTrue(conflict["when"])
        # The check of a draft from the old view says it changed too.
        self.assertTrue(api.check_draft(self.body(id="casual/table-test", sha256=view["sha256"]))["file_changed"])

    def test_a_command_line_save_isnt_called_a_deck_lab_save(self):
        view = api.edit_view("casual/table-test")
        deck = inventory.current().deck("casual/table-test")
        inventory.apply(Op("deck.save", {"deck_id": deck.id, "text": deck.text + "\nA pushed note.\n",
                                         "base_sha256": deck.sha256}), Actor("claude", "Claude", source="cli"),
                        "push a note")
        error = self.assertApiError(409, api.save_deck, self.body(
            id="casual/table-test", sha256=view["sha256"], fields={"status": "idea"}))
        self.assertEqual((error.extra["conflict"]["by"], error.extra["conflict"]["deck_lab"]), ("Claude", False))
        self.assertIn('Claude changed it at ', error.message)
        self.assertIn('("push a note")', error.message)

    def test_a_kit_revisions_message_is_its_actors_alone(self):
        # A revision that changed the deck's sleeves (kit) names accessories: only its actor sees its message.
        deck = inventory.current().deck("casual/table-test")
        kit = deck.text.replace("- **Status:** building\n", "- **Status:** built\n- **Sleeves:** red\n")
        inventory.register("test.kit")(lambda inv: (inv.with_deck(inv.deck("casual/table-test").replace(text=kit)),
                                                    inventory.Summary("set red sleeves")))
        self.addCleanup(inventory.unregister, "test.kit")
        inventory.apply(Op("test.kit"), USER1, "set red sleeves on Table Test")
        for viewer, subject in (("user1", "set red sleeves on Table Test"), ("matt", None)):
            with self.subTest(viewer=viewer):
                error = api.commits._conflict("casual/table-test", "Table Test",
                                              viewer={"id": viewer, "name": viewer.title()})
                self.assertEqual(error.extra["conflict"]["subject"], subject)
                self.assertEqual(error.extra["conflict"]["by"], "User1")

    def test_a_deleted_deck_is_named_by_its_last_title(self):
        view = api.edit_view("casual/table-test")
        inventory.apply(Op("deck.delete", {"deck_id": "casual/table-test", "base_sha256": view["sha256"]}), USER1,
                        "delete Table Test")
        for call in (api.save_deck, api.check_draft):
            with self.subTest(call=call.__name__):
                error = self.assertApiError(409, call, self.body(id="casual/table-test", sha256=view["sha256"]))
                self.assertRegex(error.message, r"^Table Test was deleted after you opened it: User1 deleted it at ")
                conflict = error.extra["conflict"]
                self.assertEqual((conflict["reason"], conflict["by"]), ("deleted", "User1"))
                self.assertFalse({"moved_to", "commit", "committed"} & conflict.keys())
        self.assertApiError(404, api.save_deck, self.body(id="casual/never-was", sha256="0" * 64),
                            contains="No deck 'casual/never-was'")

    def test_a_new_deck_and_a_taken_name(self):
        created = api.create_deck(self.body("user1", title="Lórien Elves", kind="casual"))
        self.assertEqual(created["id"], "casual/lorien-elves")
        self.assertEqual(created["sha256"], self.sha("casual/lorien-elves"))
        self.assertEqual(self.revisions("casual/lorien-elves"), [(1, "A", "user1", "new deck Lórien Elves", True)])
        error = self.assertApiError(409, api.create_deck, self.body(title="Lorien Elves", kind="commander"))
        self.assertEqual(error.extra["conflict"], {"reason": "exists", "id": "casual/lorien-elves"})
        self.assertFalse((self.box.magic / "decks").exists())

    def test_update_tables_is_one_change(self):
        two = TABLE_DECK.replace("# Table Test", "# Table Two")
        inventory.register("test.add_two")(lambda inv: (inv.with_deck(inv.deck("casual/table-test").replace(
            slug="table-two", text=two)), inventory.Summary("add Table Two")))
        self.addCleanup(inventory.unregister, "test.add_two")
        inventory.apply(Op("test.add_two"), USER1, "add Table Two")
        stale = api.stale_view()["stale"]
        self.assertEqual([s["id"] for s in stale], ["casual/table-test", "casual/table-two"])
        sets = self.sql("select count(*) from audit.change_set")[0][0]
        answer = api.update_tables(self.body(decks=[{"id": s["id"], "sha256": s["sha256"]} for s in stale]))
        self.assertEqual([u["id"] for u in answer["updated"]], ["casual/table-test", "casual/table-two"])
        self.assertEqual(self.sql("select count(*) from audit.change_set")[0][0], sets + 1)
        self.assertEqual(self.sql("select message from audit.change_set order by id desc limit 1"),
                         [("update the owned-vs-needed tables of Table Test and Table Two",)])
        self.assertEqual(api.stale_view()["stale"], [])
        self.assertEqual([u["sha256"] for u in answer["updated"]],
                         [self.sha("casual/table-test"), self.sha("casual/table-two")])


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabasePreconTests(PreconTestCase, _Profiles):

    def setUp(self):
        super().setUp()
        self.backend = into_database(self)

    def test_the_cards_and_the_deck_are_one_change(self):
        sets = self.sql("select count(*) from audit.change_set")[0][0]
        with self.as_("user2"):
            answer = self.add(profile="user2")
        self.assertEqual(answer["collection"]["added"], {"rows": 3, "cards": 5})
        self.assertEqual(answer["deck"]["id"], "user2/commander/ghalta-test-dinos")
        self.assertEqual(self.sql("select count(*) from audit.change_set")[0][0], sets + 1)
        self.assertEqual(self.sql("select actor, message from audit.change_set order by id desc limit 1"),
                         [("user2", "import 5 cards into User2's collection from the Test Dinos precon; "
                                      "new deck Ghalta: Test Dinos")])
        deck = inventory.current().deck("user2/commander/ghalta-test-dinos")
        self.assertIn("- **Status:** built", deck.text)
        self.assertEqual(answer["deck"]["sha256"], deck.sha256)
        self.assertEqual(answer["collection"]["sha256"], self.rows_sha("user2"))

    def rows_sha(self, space):
        return api.collection_edit.rows_view(space)["sha256"]

    def test_a_refusal_saves_neither(self):
        self.add()
        before = self.sql("select count(*) from audit.change_set")[0][0]
        self.assertApiError(409, self.add)                                      # the deck's name is taken
        self.assertApiError(409, self.add, sha256="0" * 64)                     # the collection changed
        self.assertEqual(self.sql("select count(*) from audit.change_set")[0][0], before)


if __name__ == "__main__":
    unittest.main()
