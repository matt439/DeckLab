"""Wishlists on PostgreSQL: the page's route end to end through a PgStore, and the command
line (python -m decklab.db wishlist ...), each with what it leaves in the audit trail.

Each test runs in a Sandbox (its config.json profiles and card index) with a PgStore on the
class's throwaway database installed over the Sandbox's MemoryStore.
"""
import contextlib
import io
import json

from decklab.db import __main__ as cli
from decklab.lib import access, api, state
from decklab.lib.state import pg
from decklab.tests import db_support
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_wishlists import body


class WishlistDbTestCase(db_support.DbTestCase, ApiTestCase):
    def setUp(self):
        super().setUp()
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.box.stack.callback(state.use(self.store))

    def trail(self):
        """The change sets, oldest first: (actor, source, via, message, reason)."""
        with self.connect("owner") as c:
            return c.execute("select actor, source, via, message, reason from audit.change_set "
                             "order by id").fetchall()

    def rows(self):
        with self.connect("owner") as c:
            return c.execute("select profile_id, position, name, set_code, collector_number, notes, source "
                             "from wishlist_entry order by profile_id, position").fetchall()


class WishlistRouteTests(WishlistDbTestCase):
    def test_add_and_remove_reach_the_database_with_who_from_where_and_what(self):
        answer = api.change_wishlist("user1", body(name="llanowar elves", set="fdn", number="227"))
        self.assertTrue(answer["changed"])
        self.assertEqual(self.rows(), [("user1", 0, "Llanowar Elves", "fdn", "227", "", "")])
        self.assertFalse(api.change_wishlist("user1", body(name="LLANOWAR ELVES"))["changed"])
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            api.change_wishlist("user1", body(name="Elvish Mystic"))
        with access.viewing("user1"):                  # a wishlist is its owner's only
            self.assertEqual([e["name"] for e in api.get_wishlist("user1")["entries"]],
                             ["Llanowar Elves", "Elvish Mystic"])
        removed = api.change_wishlist("user1", body("remove", name="llanowar ELVES"))
        self.assertEqual([e["name"] for e in removed["entries"]], ["Elvish Mystic"])
        self.assertFalse(api.change_wishlist("user1", body("remove", name="Not On It"))["changed"])
        self.assertEqual(self.trail(), [
            ("user1", "web", "home", "Add Llanowar Elves to User1's wishlist", None),
            ("user1", "web", "tunnel", "Add Elvish Mystic to User1's wishlist", None),
            ("user1", "web", "home", "Remove Llanowar Elves from User1's wishlist", None)])
        with self.connect("owner") as c:
            ops = c.execute("select r.op from audit.row_change r join audit.change_set s on s.id = r.change_set_id "
                            "where r.table_name = 'wishlist_entry' order by s.id").fetchall()
        self.assertEqual([op for (op,) in ops], ["INSERT", "INSERT", "DELETE"])


class WishlistCliTests(WishlistDbTestCase):
    def run_cli(self, *argv):
        """(exit code, stdout, stderr) of python -m decklab.db wishlist <argv> on this database."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["wishlist", *argv, "--dbname", self.dbname])
        return code, out.getvalue(), err.getvalue()

    def test_add_resolves_the_name_and_records_claude_from_the_command_line(self):
        code, out, err = self.run_cli("add", "user1", "llanowar elves", "--set", "fdn", "--number", "227",
                                      "--notes", "For the Elves deck.", "--source", "magic/buylists/x.md",
                                      "-m", "Add Llanowar Elves for the Elves deck")
        self.assertEqual(code, 0, err)
        self.assertIn("Added Llanowar Elves (fdn 227) to User1's wishlist", out)
        self.assertEqual(self.rows(), [("user1", 0, "Llanowar Elves", "fdn", "227", "For the Elves deck.",
                                        "magic/buylists/x.md")])
        self.assertEqual(self.trail(), [("claude", "cli", None, "Add Llanowar Elves for the Elves deck", None)])
        code, out, _ = self.run_cli("add", "user1", "LLANOWAR ELVES", "-m", "again")
        self.assertEqual(code, 0)
        self.assertIn("already on User1's wishlist", out)
        self.assertNotIn("wishlist set", out)
        code, out, _ = self.run_cli("add", "user1", "Llanowar Elves", "--notes", "New notes.", "-m", "again")
        self.assertEqual(code, 0)
        self.assertIn("nothing changed. Use wishlist set to change its notes", out)
        self.assertEqual(len(self.trail()), 1)

    def test_list_in_order_and_as_the_old_file(self):
        self.run_cli("add", "user1", "Llanowar Elves", "--notes", "Ñotes, ünicode.", "-m", "one")
        self.run_cli("add", "user1", "Elvish Mystic", "-m", "two")
        code, out, _ = self.run_cli("list", "user1")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["User1's wishlist: 2 cards.", "  Llanowar Elves",
                                            "      notes: Ñotes, ünicode.", "  Elvish Mystic"])
        code, out, _ = self.run_cli("list", "user1", "--json")
        self.assertEqual(json.loads(out), {"version": 1, "entries": self.store.wishlist("user1")})
        self.assertEqual(out, json.dumps(json.loads(out), ensure_ascii=False, indent=2) + "\n")

    def test_unknown_cards_are_refused_unless_the_check_is_skipped(self):
        code, _, err = self.run_cli("add", "user1", "Invented Card", "-m", "add it")
        self.assertEqual(code, 1)
        self.assertIn("No Scryfall card named 'Invented Card'", err)
        code, _, err = self.run_cli("add", "user1", "Llanowar Elves", "--set", "mkm", "--number", "170", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("doesn't match", err)
        self.assertEqual(self.rows(), [])
        with self.box.no_index():
            code, _, err = self.run_cli("add", "user1", "Llanowar Elves", "-m", "add it")
            self.assertEqual(code, 1)
            self.assertIn("--no-check", err)
            code, _, err = self.run_cli("add", "user1", "Invented Card", "--no-check", "-m", "add it")
            self.assertEqual(code, 0, err)
            # --no-check skips only the card: the forms are still checked.
            code, _, err = self.run_cli("add", "user1", "Other", "--set", "fdn", "--no-check", "-m", "x")
            self.assertEqual(code, 1)
            self.assertIn("both set and number", err)
        self.assertEqual([r[2] for r in self.rows()], ["Invented Card"])

    def test_set_changes_notes_source_and_printing(self):
        self.run_cli("add", "user1", "Llanowar Elves", "--set", "fdn", "--number", "227", "-m", "add")
        code, out, err = self.run_cli("set", "user1", "llanowar elves", "--notes", "Better art.",
                                      "--source", "magic/decks/casual/elves.md", "-m", "Note the art")
        self.assertEqual(code, 0, err)
        self.assertIn("Changed Llanowar Elves (fdn 227)", out)
        code, _, err = self.run_cli("set", "user1", "Llanowar Elves", "--no-printing", "-m", "Any printing")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows(), [("user1", 0, "Llanowar Elves", None, None, "Better art.",
                                        "magic/decks/casual/elves.md")])
        code, out, _ = self.run_cli("set", "user1", "Llanowar Elves", "--notes", "Better art.", "-m", "same")
        self.assertEqual(code, 0)
        self.assertIn("nothing changed", out)
        for argv, words in ((("--notes", "x"), "isn't on"), ((), "Nothing to change"),
                            (("--set", "mkm", "--number", "170"), "doesn't match"),
                            (("--no-printing", "--set", "fdn", "--number", "227"), "not both")):
            with self.subTest(argv=argv):
                name = "Not On It" if words == "isn't on" else "Llanowar Elves"
                code, _, err = self.run_cli("set", "user1", name, *argv, "-m", "x")
                self.assertEqual(code, 1)
                self.assertIn(words, err)
        self.assertEqual([r[3] for r in self.trail()], ["add", "Note the art", "Any printing"])

    def test_remove_needs_a_reason_and_records_it(self):
        self.run_cli("add", "user1", "Llanowar Elves", "-m", "add")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("remove", "user1", "Llanowar Elves", "-m", "Remove it")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("add", "user1", "Elvish Mystic")
        for argv, words in ((("-m", "Remove it", "--reason", "  "), "--reason needs"),
                            (("-m", " ", "--reason", "Bought a copy"), "-m needs")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli("remove", "user1", "Llanowar Elves", *argv)
                self.assertEqual(code, 1)
                self.assertIn(words, err)
        code, _, err = self.run_cli("add", "user1", "Elvish Mystic", "-m", "")
        self.assertEqual((code, "-m needs" in err), (1, True))
        self.assertEqual(len(self.trail()), 1)
        code, out, err = self.run_cli("remove", "user1", "LLANOWAR ELVES", "-m", "Remove Llanowar Elves",
                                      "--reason", "Bought a copy")
        self.assertEqual(code, 0, err)
        self.assertIn("Removed Llanowar Elves from User1's wishlist (0 cards left)", out)
        code, _, err = self.run_cli("remove", "user1", "Llanowar Elves", "-m", "again", "--reason", "x")
        self.assertEqual(code, 1)
        self.assertIn("isn't on User1's wishlist", err)
        self.assertEqual(self.trail()[-1], ("claude", "cli", None, "Remove Llanowar Elves", "Bought a copy"))

    def test_profiles_not_in_the_config_need_allow_orphan(self):
        code, _, err = self.run_cli("add", "nobody", "Llanowar Elves", "-m", "add")
        self.assertEqual(code, 1)
        self.assertIn("--allow-orphan", err)
        code, _, err = self.run_cli("add", "../x", "Llanowar Elves", "-m", "add", "--allow-orphan")
        self.assertEqual(code, 1)
        self.assertEqual(self.rows(), [])
        code, _, err = self.run_cli("add", "nobody", "Llanowar Elves", "-m", "add", "--allow-orphan")
        self.assertEqual(code, 0, err)
        code, out, _ = self.run_cli("list", "nobody", "--allow-orphan")
        self.assertIn("nobody's wishlist: 1 card.", out)

    def test_cli_can_edit_and_remove_an_orphan_without_recreating_its_profile(self):
        code, _, err = self.run_cli("add", "nobody", "Llanowar Elves", "-m", "add", "--allow-orphan")
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli("set", "nobody", "Llanowar Elves", "--notes", "Retained list",
                                   "-m", "Upkeep", "--allow-orphan")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows()[0][5], "Retained list")
        code, _, err = self.run_cli("remove", "nobody", "Llanowar Elves", "-m", "Upkeep",
                                   "--reason", "No longer wanted", "--allow-orphan")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.rows(), [])
        with self.connect() as c:
            self.assertIsNone(c.execute("select 1 from profile where id='nobody'").fetchone())

    def test_allow_orphan_never_recreates_a_departed_members_list(self):
        import uuid
        from decklab.db import conn as db
        with self.connect("owner") as c:
            with db.change("test", "test", "Departure fixture", conn=c) as (cur, change_id):
                cur.execute("insert into space_departure(space_id,operation,change_set_id) values(%s,%s,%s)",
                            ("nobody", uuid.uuid4(), change_id))
        code, _, err = self.run_cli("add", "nobody", "Llanowar Elves", "-m", "add", "--allow-orphan")
        self.assertEqual(code, 1)
        self.assertIn("no longer active", err)
        self.assertEqual(self.rows(), [])

    def test_a_database_that_cannot_be_reached_exits_2(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["wishlist", "list", "user1", "--dbname", db_support.PREFIX + "missing"])
        self.assertEqual(code, 2, err.getvalue())
        self.assertIn("isn't available", err.getvalue())
