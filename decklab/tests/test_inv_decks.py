"""Tests for the decks' and accessories' commands (decklab/db/inv_decks.py, inv_accessories.py; the
phase 4 design's R7): deck list, show, pull, push, new, delete, history, revision and tables, and
accessories list, show, check and their writes, through python -m decklab.db's main on the files
backend (test_pool's tree), and the revision numbers, history and kit lines on the database
backend (a throwaway database: those skip without one, db_support.py).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inv_decks
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.db import __main__ as cli
from decklab.db import inv_accessories, inv_decks
from decklab.lib import config, decks, inventory
from decklab.lib.inventory import Summary, ops_accessories, ops_decks, register
from decklab.tests import db_support
from decklab.tests import test_pool as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule

TABLE = ("| Llanowar Elves | 2 | 0 | **2** | ~$1.00 | ~$2.00 | keep this hand note |\n"
         "| **Total** | | | **2** | | **~$2.00** | |\n")
TEXT = support.deck_md("Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n", table=TABLE) \
    + "\n## Notes\n\nKeep this game plan.\n"
OTHER = support.deck_md("Other", "building", "Deck\n1 Pick Your Poison (MKM) 170\n",
                        table="| Pick Your Poison | 1 | 1 | 0 | | | |\n| **Total** | | | **0** | | | |\n")
ACCESSORIES = ("id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n"
               "a-sleeves,sleeves,matt,DS,Matte,red,100,,,,,,\n"
               "b-box,deck_box,shared,UG,Boulder,black,2,100,,,,,\n")


def run(*argv):
    """(exit code, stdout, stderr) of python -m decklab.db ARGV."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


class _Tree(support.PoolTestCase):

    def setUp(self):
        super().setUp()
        self.write("decks/casual/test.md", TEXT)
        self.write("decks/commander/other.md", OTHER)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Pick Your Poison", "mkm", "170", "nonfoil", 1))
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.temp, True))

    def text(self, rel="decks/casual/test.md"):
        return (self.magic / rel).read_bytes()

    def file(self, name, data):
        path = self.temp / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def sha(self, deck_id="casual/test"):
        return inventory.current().deck(deck_id).sha256


class DeckReadTests(_Tree):

    def test_list_shows_status_staleness_and_the_marker(self):
        self.write("decks/commander/other.md", OTHER.replace(
            "\n## Decklist", "\n*Decklist changed in Deck Lab on 2026-10-05; prose sections may be out of date.*\n\n"
                             "## Decklist", 1))
        code, out, _ = run("deck", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("2 decks.", out)
        test_line = next(line for line in out.splitlines() if "casual/test" in line)
        self.assertIn("idea", test_line)
        self.assertIn("table out of date", test_line)          # Owned 0, but 2 are owned
        other_line = next(line for line in out.splitlines() if "commander/other" in line)
        self.assertIn("decklist changed 2026-10-05", other_line)
        rows = inv_decks.deck_rows("home")
        self.assertEqual([(r["id"], r["status"], r["revision"]) for r in rows],
                         [("casual/test", "idea", None), ("commander/other", "building", None)])

    def test_show_prints_the_list(self):
        code, out, _ = run("deck", "show", "casual/test")
        self.assertEqual(code, 0)
        self.assertIn("2 Llanowar Elves (FDN) 227", out)
        code, _, err = run("deck", "show", "casual/test", "--version", "owned")
        self.assertEqual(code, 1)
        self.assertIn("no substitute list", err)
        self.assertEqual(run("deck", "show", "casual/nothing")[0], 1)

    def test_pull_writes_the_bytes_and_prints_the_tokens(self):
        target = self.temp / "out" / "test.md"
        code, out, _ = run("deck", "pull", "casual/test", "-o", target)
        self.assertEqual(code, 0)
        self.assertEqual(target.read_bytes(), self.text())
        self.assertIn("revision unknown", out)
        self.assertIn(f"sha {self.sha()}", out)

    def test_pull_all_writes_every_deck(self):
        code, out, _ = run("deck", "pull", "--all", "-o", self.temp / "all")
        self.assertEqual(code, 0, out)
        self.assertEqual((self.temp / "all/casual/test.md").read_bytes(), self.text())
        self.assertTrue((self.temp / "all/commander/other.md").is_file())
        self.assertEqual(run("deck", "pull", "--all")[0], 1)                  # needs -o

    def test_pull_refuses_the_repos_deck_folders(self):
        for rel in ("magic/decks/casual/x.md", "magic/people/user2/decks/casual/x.md"):
            with self.subTest(rel=rel):
                code, _, err = run("deck", "pull", "casual/test", "-o", Path(config.REPO) / rel)
                self.assertEqual(code, 1)
                self.assertIn("deck folders", err)
                self.assertFalse((Path(config.REPO) / rel).exists())
        for rel in ("Magic/Decks", "MAGIC/decks/casual/x.md", "magic/People/user2/DECKS"):  # any case
            with self.subTest(rel=rel):
                self.assertIn("deck folders", inv_decks.refused_output(Path(config.REPO) / rel))
        self.assertIsNone(inv_decks.refused_output(Path(config.REPO) / "magic" / "buylists" / "x.md"))

    def test_history_on_the_files_backend(self):
        code, out, _ = run("deck", "history", "casual/test")
        self.assertEqual(code, 0)
        self.assertIn("files backend keeps no history", out)
        self.assertEqual(run("deck", "history", "casual/never")[0], 1)
        self.assertEqual(run("deck", "revision", "casual/test", 1)[0], 1)


class DeckWriteTests(_Tree):

    def test_push_normalises_and_saves(self):
        new = TEXT.replace("Keep this game plan.", "A better plan.")
        path = self.file("push.md", b"\xef\xbb\xbf" + new.replace("\n", "\r\n").encode("utf-8"))
        code, out, err = run("deck", "push", "casual/test", path, "--expect", self.sha()[:12], "-m", "Rewrite the plan")
        self.assertEqual(code, 0, err)
        self.assertIn("Saved Test", out)
        self.assertEqual(self.text(), new.encode("utf-8"))                   # LF, no BOM
        self.assertIn("table is out of date", out)

    def test_push_of_the_same_text_writes_nothing(self):
        code, out, _ = run("deck", "push", "casual/test", self.file("same.md", TEXT), "--expect", self.sha(), "-m", "x")
        self.assertEqual(code, 0)
        self.assertIn("nothing to save", out)

    def test_push_refuses(self):
        sha = self.sha()
        cases = {
            "stale": ("--expect", "0" * 12, TEXT + "x\n", "saved since that pull"),
            "revision": ("--expect", "3", TEXT + "x\n", "keeps no revision numbers"),
            "no decklist": ("--expect", sha, "# Test\n\nNo list.\n", "Decklist"),
            "not utf-8": ("--expect", sha, b"# T\xff\n", "isn't UTF-8"),
            "too big": ("--expect", sha, "x" * (inv_decks.MAX_TEXT + 1), "KiB"),
        }
        for name, (flag, expect, text, words) in cases.items():
            with self.subTest(name):
                code, _, err = run("deck", "push", "casual/test", self.file(f"{name}.md", text), flag, expect, "-m", "x")
                self.assertEqual(code, 1)
                self.assertIn(words, err)
                self.assertEqual(self.text(), TEXT.encode("utf-8"))

    def test_push_of_a_persons_deck_refuses_home_only_lines(self):
        (self.magic / "people/user2/decks/casual").mkdir(parents=True)
        self.write("people/user2/decks/casual/elves.md", OTHER.replace("- **Played by:** either\n", ""))
        sha = self.sha("user2/casual/elves")
        code, _, err = run("deck", "push", "user2/casual/elves", self.file("e.md", OTHER), "--expect", sha, "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("Played by", err)

    def test_push_routes_a_kit_change_through_kit_set(self):
        seen = {}

        def fake_kit(inv, *, holders, changes, owners=frozenset()):
            seen.update(holders=holders, changes=changes, owners=owners)
            deck = inv.deck(holders[0]["id"])
            return inv.with_deck(deck.replace(text=deck.text.replace("- **Status:** idea\n",
                                                                      "- **Status:** idea\n- **Sleeves:** a-sleeves\n"))), \
                Summary("kit")
        inventory.unregister("kit.set")
        self.addCleanup(lambda: (inventory.unregister("kit.set"), register("kit.set")(ops_accessories.set_kit)))
        with mock.patch.object(ops_accessories, "set_kit", fake_kit):
            register("kit.set")(fake_kit)
            new = TEXT.replace("- **Status:** idea\n", "- **Status:** idea\n- **Sleeves:** a-sleeves\n") + "More.\n"
            code, _, err = run("deck", "push", "casual/test", self.file("kit.md", new), "--expect", self.sha(), "-m", "x")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen["changes"], [{"holder": "casual/test", "field": "sleeves", "value": "a-sleeves"}])
        self.assertIsNone(seen["owners"])
        self.assertEqual(self.text(), new.encode("utf-8"))

    def test_a_push_changing_only_the_kit_lines_says_it_saved(self):
        def fake_kit(inv, *, holders, changes, owners=frozenset()):     # writes the text as kit.set does
            deck = inv.deck(holders[0]["id"])
            return inv.with_deck(deck.replace(text=deck.text.replace("- **Status:** idea\n",
                                                                      "- **Status:** idea\n- **Sleeves:** a-sleeves\n"))), \
                Summary("kit")
        inventory.unregister("kit.set")
        self.addCleanup(lambda: (inventory.unregister("kit.set"), register("kit.set")(ops_accessories.set_kit)))
        with mock.patch.object(ops_accessories, "set_kit", fake_kit):
            register("kit.set")(fake_kit)
            new = TEXT.replace("- **Status:** idea\n", "- **Status:** idea\n- **Sleeves:** a-sleeves\n")
            code, out, err = run("deck", "push", "casual/test", self.file("kit.md", new), "--expect", self.sha(),
                                 "-m", "x")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.text(), new.encode("utf-8"))
        self.assertIn("Saved ", out)
        self.assertNotIn("Nothing to change", out)

    def test_a_push_that_builds_the_deck_saves_it_built_before_kit_set(self):
        seen = []

        def fake_kit(inv, *, holders, changes, owners=frozenset()):
            deck = inv.deck(holders[0]["id"])
            self.assertEqual(holders[0]["expected"], deck.sha256)
            seen.append(decks.parse_deck(deck.text.encode("utf-8"), "test", "casual").status)
            return inv.with_deck(deck.replace(text=deck.text.replace("- **Status:** built\n",
                                                                      "- **Status:** built\n- **Sleeves:** a-sleeves\n"))), \
                Summary("kit")
        inventory.unregister("kit.set")
        self.addCleanup(lambda: (inventory.unregister("kit.set"), register("kit.set")(ops_accessories.set_kit)))
        with mock.patch.object(ops_accessories, "set_kit", fake_kit):
            register("kit.set")(fake_kit)
            new = TEXT.replace("- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n") + "More.\n"
            code, _, err = run("deck", "push", "casual/test", self.file("kit.md", new), "--expect", self.sha(), "-m", "x")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, ["built"])            # kit.set saw the deck already built
        self.assertEqual(self.text(), new.encode("utf-8"))

    def test_push_with_a_kit_id_not_in_the_accessories_list_is_refused(self):
        new = TEXT.replace("- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n")
        code, _, err = run("deck", "push", "casual/test", self.file("kit.md", new), "--expect", self.sha(), "-m", "x")
        self.assertEqual(code, 1)
        self.assertEqual(self.text(), TEXT.encode("utf-8"))
        self.assertTrue(err.strip())

    def push_other(self):
        """Push commander/other with a new notes section: (exit code, stdout, stderr)."""
        return run("deck", "push", "commander/other", self.file("other.md", OTHER + "\n## Notes\n\nA plan.\n"),
                   "--expect", self.sha("commander/other"), "-m", "A plan")

    def test_push_names_the_other_decks_whose_tables_are_out_of_date(self):
        code, out, err = self.push_other()
        self.assertEqual(code, 0, err)
        self.assertNotIn("Its owned-vs-needed table is out of date", out)          # its own is up to date
        self.assertIn("1 other deck's owned-vs-needed table is now out of date: casual/test (Test).", out)
        self.assertIn('Update it: python -m decklab.db deck tables --apply -m "..."', out)
        # The pushed deck's own table is named once, by its own line, never as an "other" deck.
        code, out, err = run("deck", "push", "casual/test", self.file("test.md", TEXT + "x\n"),
                             "--expect", self.sha(), "-m", "x")
        self.assertEqual(code, 0, err)
        self.assertIn("Its owned-vs-needed table is out of date", out)
        self.assertNotIn("other deck", out)

    def test_push_names_what_would_stop_deck_tables(self):
        self.write("decks/casual/bad.md", support.deck_md("Bad", "idea", "Deck\n1 Not A Real Card Name (FDN) 999\n",
                                                          table="| **Total** | | | **0** | | | |\n"))
        code, out, err = self.push_other()
        self.assertEqual(code, 0, err)
        self.assertIn("casual/test (Test)", out)
        self.assertIn("deck tables --apply would refuse until this is fixed:", out)
        self.assertIn("casual/bad (Bad) has card names Scryfall doesn't know in its target list: "
                      "Not A Real Card Name.", out)
        self.assertNotIn("Update it:", out)

    def test_a_failure_to_work_out_stale_tables_is_one_quiet_line(self):
        with mock.patch("decklab.lib.pool.stale_tables", side_effect=RuntimeError("no card data")):
            code, out, err = self.push_other()
        self.assertEqual(code, 0, err)
        self.assertIn("Whether other decks' tables are out of date couldn't be worked out (no card data).", out)

    def test_new_and_its_refusals(self):
        path = self.file("new.md", support.deck_md("Fresh", "idea", "Deck\n1 Pick Your Poison (MKM) 170\n"))
        code, out, err = run("deck", "new", "commander", "fresh", "--from", path, "-m", "A new deck")
        self.assertEqual(code, 0, err)
        self.assertIn("commander/fresh", out)
        self.assertTrue((self.magic / "decks/commander/fresh.md").is_file())
        self.assertEqual(run("deck", "new", "casual", "Fresh", "--from", path, "-m", "x")[0], 1)    # bad slug
        code, _, err = run("deck", "new", "casual", "fresh", "--from", path, "-m", "x")             # taken
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(run("deck", "new", "casual", "x", "--from", path, "--space", "nobody", "-m", "x")[0], 1)

    def test_delete(self):
        code, _, err = run("deck", "delete", "commander/other", "--expect", "f" * 12, "-m", "x", "--reason", "gone")
        self.assertEqual(code, 1)
        self.assertIn("saved since", err)
        code, out, err = run("deck", "delete", "commander/other", "--expect", self.sha("commander/other"), "-m",
                             "Delete Other", "--reason", "never played")
        self.assertEqual(code, 0, err)
        self.assertFalse((self.magic / "decks/commander/other.md").exists())


class DeckTablesTests(_Tree):

    def test_check_apply_and_check_again(self):
        code, out, _ = run("deck", "tables", "--check")
        self.assertEqual(code, 1)
        self.assertIn("Out of date: casual/test", out)
        before = self.text()
        self.assertEqual(run("deck", "tables")[0], 0)                       # a preview
        self.assertEqual(self.text(), before)
        code, out, err = run("deck", "tables", "--apply")
        self.assertEqual(code, 0, err)
        self.assertIn("Updated: casual/test (Test)", out)
        after = decks.parse_deck(self.text(), "test", "casual")
        self.assertEqual(after.rows[0].missing, 0)
        self.assertIn("keep this hand note", after.text)
        self.assertEqual(run("deck", "tables", "--check")[0], 0)

    def test_named_decks_and_unknown_ones(self):
        code, out, _ = run("deck", "tables", "casual/test", "--check")
        self.assertEqual(code, 1)
        self.assertNotIn("commander/other", out)
        self.assertEqual(run("deck", "tables", "commander/other", "--apply")[0], 0)
        self.assertEqual(run("deck", "tables", "commander/other", "--check")[0], 0)
        self.assertEqual(run("deck", "tables", "casual/test", "--check")[0], 1)
        code, _, err = run("deck", "tables", "casual/nothing")
        self.assertEqual(code, 1)
        self.assertIn("no deck casual/nothing", err)

    def test_reprice_prices_the_table_again(self):
        code, out, err = run("deck", "tables", "casual/test", "--reprice", "--apply")
        self.assertEqual(code, 0, err)
        after = decks.parse_deck(self.text(), "test", "casual")
        self.assertIsNotNone(after.prices)
        self.assertEqual(after.prices.rate, support.RATE[0])

    def test_reprice_notes_unknown_cards_and_a_named_deck_without_a_table(self):
        # (The refresh's own plan refuses a pool with unknown cards, as the old script did; the repricing
        # itself notes them, as the Library does.)
        deck = inventory.current().deck("casual/test")
        text, note = inv_decks.repriced(deck.replace(text=TEXT.replace(
            "58 Forest\n", "58 Forest\n1 Not A Real Card Name (FDN) 999\n")))
        self.assertIn("cards the card data doesn't know aren't in its table: Not A Real Card Name", note)
        self.assertIn("keep this hand note", text)
        self.write("decks/commander/other.md", support.deck_md("Other", "building", "Deck\n1 Pick Your Poison (MKM) 170\n"))
        from decklab.lib.inventory import refresh
        with mock.patch.object(refresh, "plan_texts", lambda: []):     # (its plan refuses a deck without a table)
            code, out, err = run("deck", "tables", "commander/other", "--reprice")
        self.assertEqual(code, 0, err)
        self.assertIn("Not changed: commander/other (Other); it has no owned-vs-needed table", out)

    def test_accessories_problems_name_the_deck_as_a_whole_title(self):
        titles = {"Elves", "Elves II"}
        self.assertTrue(inv_decks.names_holder("Elves: its sleeves are User1's", "Elves", titles))
        self.assertFalse(inv_decks.names_holder("Elves II needs 61 sleeves", "Elves", titles))
        self.assertTrue(inv_decks.names_holder("Elves II and Elves have red sleeves", "Elves", titles))
        self.assertFalse(inv_decks.names_holder("Elvesong needs 61 sleeves", "Elves", titles))
        self.assertFalse(inv_decks.names_holder("anything", "", titles))

    def test_an_incomplete_pool_refuses(self):
        self.cards_csv("orders/test.csv", ("Not a real card", "fdn", "227", "nonfoil", 2))
        code, _, err = run("deck", "tables", "--apply")
        self.assertEqual(code, 1)
        self.assertIn("incomplete card pool", err)
        self.assertEqual(self.text(), TEXT.encode("utf-8"))

    def test_a_refusal_lists_every_problem(self):
        self.write("decks/casual/bad.md", support.deck_md("Bad", "idea", "Deck\n1 Not A Real Card Name (FDN) 999\n",
                                                          table="| **Total** | | | **0** | | | |\n"))
        self.write("decks/casual/bare.md", support.deck_md("Bare", "idea", "Deck\n1 Pick Your Poison (MKM) 170\n"))
        code, out, err = run("deck", "tables", "--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("The tables can't be worked out until this is fixed:", err)
        self.assertIn("  casual/bad (Bad) has card names Scryfall doesn't know in its target list: "
                      "Not A Real Card Name.", err)
        self.assertIn("  casual/bare (Bare) has no owned-vs-needed table", err)
        self.assertEqual(self.text(), TEXT.encode("utf-8"))
        # A deck that doesn't exist is said as before, not hidden behind the others' problems.
        code, _, err = run("deck", "tables", "casual/nothing")
        self.assertEqual(code, 1)
        self.assertIn("The tables can't be worked out: there's no deck casual/nothing", err)

    def test_a_deck_changed_meanwhile_refuses_the_lot(self):
        planned = inv_decks.plan_tables()
        self.write("decks/casual/test.md", TEXT + "\nMeanwhile.\n")
        with inventory.pinned():
            items = [{"id": i, "text": out, "base_sha256": decks.text_sha(raw)} for i, _, raw, out, _ in planned]
            with self.assertRaises(ops_decks.DeckRefused):
                inventory.apply(inventory.Op("deck.update_tables", {"items": items}), inv_decks._actor(), "x")
        self.assertIn(b"Meanwhile.", self.text())


class AccessoriesCliTests(_Tree):

    def setUp(self):
        super().setUp()
        self.write("accessories.csv", ACCESSORIES)

    def test_list_show_and_check(self):
        code, out, _ = run("accessories", "list")
        self.assertEqual(code, 0)
        self.assertIn("2 accessories.", out)
        self.assertIn("a-sleeves  DS Matte (red)", out)
        sha = inv_accessories.listed().sha256
        self.assertIn(f"sha {sha}", out)
        code, out, _ = run("accessories", "show", "b-box")
        self.assertEqual(code, 0)
        self.assertIn("held by nothing", out)
        self.assertEqual(run("accessories", "show", "nothing")[0], 1)
        self.assertIn(run("accessories", "check")[0], (0, 1))

    def test_push_dry_run_warns_and_an_unchanged_line_does_not(self):
        self.write("accessories.csv", ACCESSORIES + "s-sleeves,sleeves,shared,DS,Matte,blue,100,,,,,,\n")
        sleeved = lambda text: text.replace("- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** s-sleeves\n") \
            .replace("- **Status:** building\n", "- **Status:** built\n- **Sleeves:** s-sleeves\n")
        code, _, err = run("deck", "push", "casual/test", self.file("a.md", sleeved(TEXT)), "--expect",
                           self.sha("casual/test"), "-m", "Sleeve it")
        self.assertEqual(code, 0, err)
        before = self.sha("commander/other")
        code, out, err = run("deck", "push", "commander/other", self.file("b.md", sleeved(OTHER)), "--expect", before,
                             "-m", "Sleeve it", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("Warning: Test uses DS Matte (blue) already.", out)
        self.assertEqual(self.sha("commander/other"), before)
        # Re-pushing the first deck with its Sleeves line unchanged says nothing about sharing.
        code, out, err = run("deck", "push", "casual/test", self.file("c.md", sleeved(TEXT) + "Note.\n"), "--expect",
                             self.sha("casual/test"), "-m", "A note")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Warning:", out)

    def test_push_accepts_sleeves_another_deck_has(self):
        # E8-S20: one design may sleeve several built decks; both keep it, and check says nothing of it.
        self.write("accessories.csv", ACCESSORIES + "s-sleeves,sleeves,shared,DS,Matte,blue,100,,,,,,\n")
        # Matt, 2026-10-19: the push giving a second deck those sleeves warns, naming the first.
        warning = "Warning: Test uses DS Matte (blue) already."
        for deck_id, text, warned in (("casual/test", TEXT, False), ("commander/other", OTHER, True)):
            with self.subTest(deck=deck_id):
                new = text.replace("- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** s-sleeves\n") \
                    .replace("- **Status:** building\n", "- **Status:** built\n- **Sleeves:** s-sleeves\n")
                code, out, err = run("deck", "push", deck_id, self.file("kit.md", new), "--expect",
                                     self.sha(deck_id), "-m", "Sleeve it")
                self.assertEqual(code, 0, err)
                self.assertEqual(warning in out, warned, out)
        for deck_id in ("casual/test", "commander/other"):
            self.assertIn("- **Sleeves:** s-sleeves\n", inventory.current().deck(deck_id).text)
        code, out, _ = run("accessories", "show", "s-sleeves")
        self.assertEqual(code, 0)
        self.assertIn("held by Test", out)
        self.assertIn("held by Other", out)
        from decklab.lib import accessories
        with inventory.pinned():
            self.assertFalse([p for p in accessories.check() if "s-sleeves" in p or "Matte (blue)" in p])

    def test_add_and_edit_run_the_real_operations(self):
        code, out, err = run("accessories", "add", "--kind", "playmat", "--name", "Mat", "--brand", "UP",
                             "--expect", inv_accessories.listed().sha256[:12], "-m", "Add a mat")
        self.assertEqual(code, 0, err)
        self.assertIn("Added the playmat", out)
        self.assertIn("id: up-mat", out)                       # image put names its picture by it
        row = inv_accessories.listed().rows_by_id["up-mat"]
        self.assertEqual((row["kind"], row["owner"], row["brand"], row["name"], row["quantity"]),
                         ("playmat", "shared", "UP", "Mat", 1))
        code, out, err = run("accessories", "edit", "b-box", "--quantity", "3", "--notes", "by the door",
                             "--expect", inv_accessories.listed().sha256, "-m", "More boxes")
        self.assertEqual(code, 0, err)
        row = inv_accessories.listed().rows_by_id["b-box"]
        self.assertEqual((row["quantity"], row["notes"], row["capacity"], row["colour"]), (3, "by the door", 100,
                                                                                          "black"))

    def test_writes_go_to_the_operations(self):
        calls = []

        def fake(kind):
            def op(inv, **params):
                calls.append((kind, params))
                return inv, Summary(f"did {kind}")
            return op
        sha = inv_accessories.listed().sha256
        kinds = ("accessory.add", "accessory.edit", "accessory.remove", "image.put", "image.remove")
        for kind in kinds:
            inventory.unregister(kind)
            register(kind)(fake(kind))
        self.addCleanup(lambda: [(inventory.unregister(k), register(k)(getattr(ops_accessories, f))) for k, f in
                                 zip(kinds, ("add_accessory", "edit_accessory", "remove_accessory", "put_image",
                                             "remove_image"))])
        self.assertEqual(run("accessories", "add", "--kind", "playmat", "--name", "Mat", "--brand", "UP",
                             "--expect", sha[:12], "-m", "Add a mat")[0], 0)
        # Only the columns the operation takes: it makes the id itself.
        self.assertEqual(calls[-1][1]["row"], {"owner": "shared", "quantity": 1, "kind": "playmat", "name": "Mat",
                                               "brand": "UP"})
        self.assertIsNone(calls[-1][1]["owners"])
        self.assertEqual(run("accessories", "edit", "b-box", "--quantity", "3", "--expect", sha, "-m", "x")[0], 0)
        self.assertEqual((calls[-1][1]["id"], calls[-1][1]["row"]), ("b-box", {"quantity": 3}))
        self.assertEqual(run("accessories", "remove", "b-box", "--expect", sha, "-m", "x", "--reason", "lost")[0], 0)
        self.assertEqual(calls[-1][0], "accessory.remove")
        png = b"\x89PNG\r\n\x1a\n" + bytes(16)
        picture = self.file("p.png", png)
        self.assertEqual(run("image", "put", "b-box.png", picture, "-m", "x")[0], 0)
        self.assertEqual(calls[-1][1], {"name": "b-box.png", "content": png})
        self.assertEqual(run("image", "remove", "b-box.png", "-m", "x")[0], 1)      # no such picture
        # Refusals before any operation: a stale list, a bad row, a bad picture name.
        count = len(calls)
        self.assertEqual(run("accessories", "edit", "b-box", "--expect", "0" * 12, "-m", "x")[0], 1)
        self.assertEqual(run("accessories", "edit", "b-box", "--quantity", "x", "--expect", sha, "-m", "x")[0], 1)
        self.assertEqual(run("image", "put", "Bad Name.png", picture, "-m", "x")[0], 1)
        # A picture the page wouldn't serve: bytes that aren't its extension's, or over its size limit.
        code, _, err = run("image", "put", "b-box.jpg", picture, "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("isn't a .jpg picture (its bytes are a .png)", err)
        big = self.file("big.png", png + bytes(4 * 1024 * 1024))
        self.assertEqual(run("image", "put", "b-box.png", big, "-m", "x")[0], 1)
        self.assertEqual(len(calls), count)


# Run in a fresh interpreter, which imports only what python -m decklab.db imports: the deck, kit,
# accessory and picture operations must be registered by the commands themselves (this module
# imports ops_decks at the top, so the tests above can't see a command that forgets to).
FRESH = r"""
import sys, tempfile, unittest
from pathlib import Path
from decklab.db import __main__ as cli
from decklab.lib import inventory
from decklab.tests import test_pool as support

class Fresh(support.PoolTestCase):
    def test_writes(self):
        self.assertNotIn("deck.create", inventory.kinds())     # nothing imported ops_decks yet
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        temp = Path(tempfile.mkdtemp())
        new = temp / "new.md"
        new.write_text(support.deck_md("Fresh", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
                                       table="| **Total** | | | **0** | | | |\n"), encoding="utf-8")
        self.assertEqual(cli.main(["deck", "new", "casual", "fresh", "--from", str(new), "-m", "x"]), 0)
        self.assertEqual(cli.main(["deck", "tables", "--apply"]), 0)
        self.assertEqual(cli.main(["accessories", "add", "--kind", "playmat", "--name", "Mat", "--expect", "none",
                                   "-m", "x"]), 0)                                  # no list yet
        picture = temp / "mat.png"
        picture.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(32))
        self.assertEqual(cli.main(["image", "put", "mat.png", str(picture), "-m", "x"]), 0)
        sha = inventory.current().deck("casual/fresh").sha256
        self.assertEqual(cli.main(["deck", "delete", "casual/fresh", "--expect", sha[:12], "-m", "x",
                                   "--reason", "y"]), 0)

support.setUpModule()
try:
    result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Fresh))
finally:
    support.tearDownModule()
sys.exit(0 if result.wasSuccessful() else 1)
"""


class FreshInterpreterTests(unittest.TestCase):

    def test_the_write_commands_register_their_operations(self):
        import subprocess
        import sys
        root = Path(__file__).resolve().parents[2]
        done = subprocess.run([sys.executable, "-c", FRESH], cwd=root, capture_output=True, text=True,
                              encoding="utf-8", timeout=300)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DeckDatabaseTests(db_support.DbTestCase):
    """The commands on the database backend: revision numbers for --expect, the history and one
    revision's text."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import CLAUDE, adapt, import_contents
        from decklab.tests.test_inventory_pg_decks import _Db
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        tree = _Db.tree(self)
        inv = adapt(tree.inventory.load())
        pg.write_model(inv, CLAUDE, "Import", contents=import_contents(tree.inventory.root), dbname=self.dbname,
                       decks=True, images={"a-sleeves.jpg": (tree.magic / "accessories/images/a-sleeves.jpg").read_bytes()})
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))
        self.temp = Path(tempfile.mkdtemp())

    def test_pull_push_history_and_revision(self):
        out_file = self.temp / "test.md"
        code, out, _ = run("deck", "pull", "casual/test", "-o", out_file)
        self.assertEqual(code, 0)
        self.assertIn("revision 1", out)
        text = out_file.read_text(encoding="utf-8") + "\nA note.\n"
        out_file.write_text(text, encoding="utf-8")         # Windows text mode: CRLF on disk
        code, out, err = run("deck", "push", "casual/test", out_file, "--expect", "1", "-m", "Add a note\n\nBody line.")
        self.assertEqual(code, 0, err)
        self.assertIn("(revision 2)", out)
        self.assertEqual(run("deck", "push", "casual/test", out_file, "--expect", "1", "-m", "again")[0], 1)
        code, out, _ = run("deck", "history", "casual/test")
        self.assertEqual(code, 0)
        self.assertIn("2 revisions", out)
        self.assertIn("saved by claude", out)
        self.assertIn("Body line.", out)
        code, out, _ = run("deck", "revision", "casual/test", 2, "-o", self.temp / "r2.md")
        self.assertEqual(code, 0)
        self.assertEqual((self.temp / "r2.md").read_bytes(), text.replace("\r\n", "\n").encode("utf-8"))
        code, _, _ = run("deck", "delete", "casual/test", "--expect", "2", "-m", "Delete", "--reason", "done")
        self.assertEqual(code, 0)
        code, out, _ = run("deck", "history", "casual/test")
        self.assertIn("deleted by claude", out)
        self.assertEqual(run("deck", "revision", "casual/test", 3)[0], 1)    # a 'D' has no text


if __name__ == "__main__":
    unittest.main()
