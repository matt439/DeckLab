"""Tests for python -m decklab.db collection add-precon and collection precons (E10-S36,
decklab/db/inv_collection.py): the Collection page's Add a precon (lib/api/precons.py's
plan_add) from the command line, which writes every space. Run through decklab.db's main(), so
the exit codes are the command's, in test_precons' sandbox (MTGJSON never reached, the
sandbox's files as the inventory; never the real database).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_precon_cli
"""
import contextlib
import io
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import precons as api
from decklab.tests.test_precons import PreconTestCase


class CommandLineTests(PreconTestCase):

    def run_cli(self, *argv):
        from decklab.db.__main__ import main
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["collection", *argv])
        return code, out.getvalue(), err.getvalue()

    def deck_text(self, space, kind, slug):
        folder = self.box.magic if space == "home" else self.box.magic / "people" / space
        return (folder / "decks" / kind / f"{slug}.md").read_text(encoding="utf-8")

    def test_a_dry_run_previews_the_cards_and_the_deck_and_saves_nothing(self):
        before, rows = self.writes_made(), self.rows("user2")["rows"]
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "User2's precon",
                                      "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Would add the Test Dinos precon (Test Commander, Commander Deck) to User2's collection: "
                      "5 cards in 4 rows.", out)
        self.assertIn("  1 Ghalta, Primal Hunger (rix 130 foil)", out)
        self.assertIn("  2 Llanowar Elves (fdn 227 nonfoil)", out)
        self.assertNotIn("Forest (", out)                                   # plain basics left out
        self.assertIn("Left out: 20 ordinary basic lands, 1 display commander.", out)
        self.assertIn("Would make user2/commander/ghalta-test-dinos (Ghalta: Test Dinos), a built commander deck: "
                      "Commander 1, Deck 24.", out)
        self.assertIn("4 Dinosaur", out)
        self.assertTrue(out.rstrip().endswith("Nothing saved (--dry-run)."))
        self.assertEqual((self.writes_made(), self.rows("user2")["rows"]), (before, rows))

    def test_adds_the_cards_and_the_built_deck_in_one_change(self):
        before = self.writes_made()
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2",
                                      "-m", "Add User2's Test Dinos precon, as he asked", "--actor", "matt")
        self.assertEqual((code, err), (0, ""), out)
        self.assertEqual(self.writes_made(), before + 1)                    # precon.add: one change
        self.assertEqual(self.last_write(), ("Add User2's Test Dinos precon, as he asked", "Matt"))
        # The last line: counts and the deck's id only, so it can be relayed without the list.
        self.assertEqual(out.strip().splitlines()[-1],
                         "Added 5 cards (3 new rows) to User2's collection and made "
                         "user2/commander/ghalta-test-dinos.")
        rows = {(r["set"], r["collector_number"], r["finish"]): r for r in self.rows("user2")["rows"]}
        self.assertEqual(rows[("fdn", "227", "nonfoil")]["quantity"], "4")     # 2 owned + 2
        self.assertNotIn(("fdn", "280", "nonfoil"), rows)
        text = self.deck_text("user2", "commander", "ghalta-test-dinos")
        self.assertIn("- **Status:** built", text)
        self.assertNotIn("Played by", text)
        self.assertIn("Added in Deck Lab on 2026-10-10 by Matt from the Test Dinos precon", text)
        # Worked out with the cards the same change adds.
        self.assertIn("| Sol Ring | 1 | 1 | 0 |", text)
        self.assertIn("| **Total to buy** | | | **0** |", text)
        self.assertTrue((self.box.magic / "people" / "user2" / "imports" / "2026-10-10-tst-test-dinos.csv").exists())

    def test_the_same_deck_as_the_page(self):
        # The page's add by User2 in his space, and the command's in User3's (named as User2):
        # the same deck text, table included.
        with self.as_("user2"):
            self.add(profile="user2")
        code, _, _ = self.run_cli("add-precon", "TestDinos_TST", "--space", "user3", "-m", "User3's precon",
                                  "--actor", "user2")
        self.assertEqual(code, 0)
        self.assertEqual(self.deck_text("user2", "commander", "ghalta-test-dinos"),
                         self.deck_text("user3", "commander", "ghalta-test-dinos"))

    def test_without_an_actor_it_is_claudes(self):
        code, _, _ = self.run_cli("add-precon", "ElfTheme_TST", "--space", "user3", "-m", "User3's elves")
        self.assertEqual(code, 0)
        self.assertEqual(self.last_write(), ("User3's elves", "Claude"))
        self.assertIn("by Claude from the Elf Theme precon", self.deck_text("user3", "casual", "elf-theme"))

    def test_a_taken_name_is_refused_with_the_existing_id(self):
        self.assertEqual(self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "first")[0], 0)
        before, rows = self.writes_made(), self.rows("user2")["rows"]
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra):
                code, _, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "again",
                                            *extra)
                self.assertEqual(code, 1)
                self.assertIn("user2/commander/ghalta-test-dinos", err)
                self.assertIn("--title", err)
        self.assertEqual((self.writes_made(), self.rows("user2")["rows"]), (before, rows))
        # Another title makes a second deck (and adds the cards again: a second copy of the precon).
        code, out, _ = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "--title", "Dinos Two",
                                    "-m", "a second copy")
        self.assertEqual(code, 0)
        self.assertIn("made user2/commander/dinos-two.", out)

    def test_a_name_taken_in_the_change_adds_no_cards(self):
        self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "first")
        before, rows = self.writes_made(), self.rows("user2")["rows"]
        with mock.patch.object(api.saving.decks, "existing_deck_id", return_value=None):
            code, _, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "again")
        self.assertEqual(code, 1)
        self.assertIn("user2/commander/ghalta-test-dinos", err)
        self.assertEqual((self.writes_made(), self.rows("user2")["rows"]), (before, rows))

    def test_home_takes_who_plays_it(self):
        code, _, _ = self.run_cli("add-precon", "ElfTheme_TST", "--title", "Her Elves", "--played-by", "wife",
                                  "-m", "User1's elves")
        self.assertEqual(code, 0)
        self.assertIn("- **Played by:** wife", self.deck_text("home", "casual", "her-elves"))
        # By default the --actor's plays_as; with no actor, no Played by line.
        self.run_cli("add-precon", "ElfTheme_TST", "--title", "His Elves", "-m", "Matt's elves", "--actor", "matt")
        self.assertIn("- **Played by:** user", self.deck_text("home", "casual", "his-elves"))
        self.run_cli("add-precon", "ElfTheme_TST", "--title", "Our Elves", "-m", "elves")
        self.assertNotIn("Played by", self.deck_text("home", "casual", "our-elves"))

    def test_refusals_change_nothing(self):
        before = self.writes_made()
        code, _, err = self.run_cli("add-precon", "Unfinished_TST", "--space", "user2", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("can't be added yet", err)
        self.assertIn("Some New Card", err)
        code, _, err = self.run_cli("add-precon", "NoSuchDeck_TST", "--space", "user2", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("MTGJSON lists no paper deck called NoSuchDeck_TST", err)
        self.assertEqual(self.run_cli("add-precon", "ElfTheme_TST", "--space", "nobody", "-m", "x")[0], 1)
        code, _, err = self.run_cli("add-precon", "ElfTheme_TST", "--space", "user2", "--played-by", "user",
                                    "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("--played-by is for a home deck", err)
        self.assertEqual(self.run_cli("add-precon", "ElfTheme_TST", "--space", "user2", "-m", "  ")[0], 1)
        self.assertEqual(self.run_cli("add-precon", "ElfTheme_TST", "-m", "x", "--actor", "nobody")[0], 1)
        self.assertEqual(self.writes_made(), before)

    def test_an_unreachable_database_is_exit_2(self):
        with mock.patch.object(self.backend, "apply", side_effect=inventory.Unavailable("down")):
            code, _, err = self.run_cli("add-precon", "ElfTheme_TST", "--space", "user2", "-m", "x")
        self.assertEqual(code, 2)
        self.assertIn("isn't available", err)

    def test_precons_lists_codes(self):
        code, out, _ = self.run_cli("precons", "dinos")
        self.assertEqual(code, 0)
        self.assertIn("TestDinos_TST\tTest Dinos\tTest Commander\tCommander Deck\t2026-10-02", out)
        self.assertNotIn("ElfTheme_TST", out)


if __name__ == "__main__":
    import unittest
    unittest.main()
