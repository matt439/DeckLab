"""Inventory changes update quantities and receipt status without changing lists or notes: the deck
tables' refresh (decklab/lib/inventory/refresh.py), saved as `python -m decklab.db deck tables
--apply` saves it (deck.update_tables: all of the decks, or none)."""
import contextlib
import io
from unittest import mock

from decklab.db import __main__ as db_cli
from decklab.lib import decks, inventory, pool
from decklab.lib.inventory import ops_decks
from decklab.lib.inventory import orders  # noqa: F401 - registers order.add
from decklab.lib.inventory import refresh
from decklab.lib.inventory import refresh as inventory_refresh
from decklab.lib.state import Actor
from decklab.tests import test_pool as support

TESTER = Actor("test", "Tester", None, "test")

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


def apply_refresh(planned):
    """Save planned ([(path, bytes now, bytes after)], plan_refresh's) as deck tables --apply does."""
    items = [{"id": decks.deck_id_of(path), "text": out.decode("utf-8"), "base_sha256": decks.text_sha(raw)}
             for path, raw, out in planned]
    if items:
        inventory.apply(inventory.Op("deck.update_tables", {"items": items}), TESTER, "update tables")


def tables(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        return db_cli.main(["deck", "tables", *argv])


class RefreshTests(support.PoolTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.magic / "decks/casual/test.md"
        self.text = support.deck_md(
            "Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
            owned="Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
            table="| Llanowar Elves | 2 | 0 | **2** | ~$1.00 | ~$2.00 | keep this hand note |\n"
                  "| **Total** | | | **2** | | **~$2.00** | |\n",
        ) + "\n## Notes\n\nKeep this game plan.\n"
        self.write("decks/casual/test.md", self.text)

    def test_pending_then_received_updates_counts_and_preserves_both_lists(self):
        self.cards_csv("orders/test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        before = decks.read_deck_file(self.path)
        planned = refresh.plan_refresh()
        self.assertEqual(len(planned), 1)
        apply_refresh(planned)
        after = decks.read_deck_file(self.path)
        self.assertEqual(after.target, before.target)
        self.assertEqual(after.owned, before.owned)
        self.assertEqual(after.rows[0].missing, 0)
        self.assertIn("keep this hand note", after.text)
        self.assertIn("Keep this game plan.", after.text)
        self.assertIn("2 on the way (order test)", after.text)
        self.assertIn("This substitute list can include cards still on the way", after.text)
        self.assertNotIn("build this now", after.text)
        self.assertEqual(refresh.plan_refresh(), [])

        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        (self.magic / "orders/test.csv").rename(self.magic / "orders/received/test.csv")
        apply_refresh(refresh.plan_refresh())
        self.assertNotIn("2 on the way (order test)", self.path.read_text(encoding="utf-8"))
        self.assertEqual(refresh.plan_refresh(), [])

    def test_incomplete_pool_changes_no_files(self):
        self.cards_csv("orders/test.csv", ("Not a real card", "fdn", "227", "nonfoil", 2))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "incomplete card pool"):
            refresh.plan_refresh()
        self.assertEqual(tables("--apply"), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_conflict_is_detected_before_any_write(self):
        planned = refresh.plan_refresh()
        self.path.write_text(self.text + "\nA concurrent edit.\n", encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(ops_decks.DeckRefused):
            apply_refresh(planned)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_later_filename_is_rejected_before_any_write(self):
        bad = self.path.with_name("z bad.md")
        bad.write_text(self.text, encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            refresh.plan_refresh()
        self.assertEqual(tables("--apply"), 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unknown_idea_deck_names_in_either_list_block_refresh(self):
        for version in ("target", "substitute"):
            with self.subTest(version=version):
                deck = decks.parse_deck(self.text.encode(), "test", "casual")
                lines = deck.target if version == "target" else deck.owned
                lines["Deck"][0].name = "Unknown card"
                self.path.write_text(decks.render_deck_file(deck), encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, f"unknown cards in {version} list"):
                    refresh.plan_refresh()
                self.assertEqual(self.path.read_bytes(), before)

    def test_table_blockers_list_every_problem_from_the_refresh_s_own_checks(self):
        self.assertEqual(refresh.table_blockers(), {"decks": [], "spaces": []})
        self.write("decks/casual/a-no-table.md", support.deck_md("No Table", "idea", "Deck\n1 Llanowar Elves\n"))
        self.write("decks/casual/b-unknown.md", support.deck_md(
            "Unknown", "idea", "Deck\n1 Not A Card\n1 Llanowar Elves\n", owned="Deck\n2 Also Not A Card\n",
            table="| Llanowar Elves | 1 | 0 | **1** | | | |\n"))
        self.write("decks/commander/c-broken.md", "# Broken\n\n- **Status:** idea\n\nNo list.\n")
        found = refresh.table_blockers()
        self.assertEqual([(d["id"], d["reason"], d["version"], d["cards"]) for d in found["decks"]], [
            ("casual/a-no-table", "no_table", None, []),
            ("casual/b-unknown", "unknown_cards", "target", ["Not A Card"]),
            ("casual/b-unknown", "unknown_cards", "owned", ["Also Not A Card"]),
            ("commander/c-broken", "no_decklist", None, [])])
        # A deck with no decklist also leaves home's pool incomplete (the pool warns about it).
        self.assertEqual([(s["space"], s["warnings"]) for s in found["spaces"]],
                         [("home", [f"commander/c-broken can't be read: {decks.NO_DECKLIST}"])])
        self.assertEqual(found["decks"][0]["why"], "casual/a-no-table (No Table) has no owned-vs-needed table: give it "
                                                   "an '## Owned vs needed' heading with the table's header and |---| "
                                                   "lines.")
        self.assertEqual(found["decks"][1]["why"], "casual/b-unknown (Unknown) has card names Scryfall doesn't know "
                                                   "in its target list: Not A Card.")
        self.assertEqual((found["decks"][1]["title"], found["decks"][1]["space"]), ("Unknown", "home"))
        self.assertEqual(pool.table_blockers(), found)
        # The refresh refuses on the first of them, with the error that names it.
        with self.assertRaisesRegex(ValueError, "incomplete card pool"):
            refresh.plan_refresh()
        (self.magic / "decks/commander/c-broken.md").unlink()
        with self.assertRaisesRegex(decks.DeckFileError, "casual/a-no-table: the file has no owned-vs-needed table"):
            refresh.plan_refresh()
        self.assertEqual(refresh.table_blockers(only={"user2"}), {"decks": [], "spaces": []})

    def test_table_blockers_name_an_incomplete_pool(self):
        self.cards_csv("orders/test.csv", ("Not a real card", "fdn", "227", "nonfoil", 2))
        found = refresh.table_blockers()
        self.assertEqual(found["decks"], [])
        [held] = found["spaces"]
        self.assertEqual((held["space"], [u["name"] for u in held["unknown"]]), ("home", ["Not a real card"]))
        with self.assertRaises(ValueError) as caught:
            refresh.plan_refresh()
        self.assertEqual(str(caught.exception), held["why"])

    def test_table_blockers_never_raise(self):
        with mock.patch.object(refresh.cards, "info", side_effect=RuntimeError("no card index")):
            found = refresh.table_blockers()
        self.assertEqual(found["decks"], [])
        self.assertIn("no card index", found["spaces"][0]["why"])

    def test_a_later_deck_that_cant_be_saved_leaves_every_deck_alone(self):
        second = self.path.with_name("test2.md")
        second.write_text(self.text.replace("# Test", "# Test two"), encoding="utf-8")
        before = {p: p.read_bytes() for p in (self.path, second)}
        planned = refresh.plan_refresh()
        self.assertEqual(len(planned), 2)
        planned[1] = (planned[1][0], planned[1][1], b"# Test two\0\n")    # a NUL: refused
        with self.assertRaises(inventory.Invalid):
            apply_refresh(planned)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_check_is_read_only_and_reports_staleness(self):
        before = self.path.read_bytes()
        self.assertEqual(tables("--check"), 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(tables("--apply"), 0)
        self.assertEqual(tables("--check"), 0)

    def test_old_and_new_headings_both_round_trip(self):
        for heading in ("Owned-only version (build this now)", "Substitute version (owned and incoming cards)"):
            text = self.text.replace("Owned-only version", heading)
            parsed = decks.parse_deck(text.encode(), "test", "casual")
            self.assertIsNotNone(parsed.owned)
            self.assertEqual(decks.render_deck_file(parsed), text)

    def test_hand_written_heading_case_and_level_are_supported(self):
        for heading in ("## owned-only version (build this now)", "#### SUBSTITUTE VERSION"):
            with self.subTest(heading=heading):
                text = self.text.replace("# Test", "# Owned-only version of Test", 1)
                self.path.write_text(text.replace("### Owned-only version", heading), encoding="utf-8")
                before = decks.read_deck_file(self.path)
                apply_refresh(refresh.plan_refresh())
                after = decks.read_deck_file(self.path)
                self.assertEqual(after.owned, before.owned)
                self.assertEqual(after.title, before.title)
                self.assertNotIn("build this now", after.text)
                self.assertIn(refresh.AVAILABILITY_MARKER, after.text)
                self.assertEqual(refresh.plan_refresh(), [])


class RefreshInsideTheChangeTests(support.PoolTestCase):
    """The deck tables' refresh inside a change (the phase 4 design's R3): an operation kind
    registered with refresh=True (here order.add) refreshes the tables its result makes stale in
    the same change, on the files backend PoolTestCase installs (test_receipts_api runs it on the
    database too); a plan that fails leaves the decks alone and the change saved."""

    def setUp(self):
        super().setUp()
        self.path = self.magic / "decks/casual/test.md"
        self.text = support.deck_md("Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
                                    table="| Llanowar Elves | 2 | 0 | **2** | | | keep this hand note |\n"
                                          "| **Total** | | | **2** | | | |\n")
        self.write("decks/casual/test.md", self.text)

    def order(self):
        row = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
               "quantity": "2", "condition": "", "language": "", "notes": ""}
        record = {"id": "2026-10-12-shop", "seller": "Shop", "ordered_on": "2026-10-12", "sources": [], "notes": ""}
        return inventory.Op("order.add", {"record": record, "cards": {"rows": [row]}, "repo": str(self.magic.parent),
                                          "check_cards": False})

    def test_the_kind_is_registered_to_refresh(self):
        self.assertTrue(inventory.refreshes("order.add"))


    def test_the_preview_names_the_deck_and_the_apply_saves_it_with_the_order(self):
        after, summary = inventory.preview(self.order())
        self.assertIn("magic/decks/casual/test.md", inventory.changed_paths(inventory.current(), after))
        self.assertEqual(summary.extra["tables"], {"written": [{"id": "casual/test", "title": "Test"}],
                                                   "skipped": [], "error": None})
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)        # a preview writes nothing
        _, summary = inventory.apply(self.order(), TESTER, "Order from Shop")
        self.assertEqual(summary.extra["tables"]["written"], [{"id": "casual/test", "title": "Test"}])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("2 on the way (order 2026-10-12-shop)", text)
        self.assertIn("keep this hand note", text)
        self.assertTrue((self.magic / "orders/records/2026-10-12-shop.json").exists())
        self.assertEqual(pool.stale_tables(), [])

    def test_refresh_false_skips_it(self):
        _, summary = inventory.apply(self.order(), TESTER, "Order from Shop", refresh=False)
        self.assertNotIn("tables", summary.extra)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertEqual([s["id"] for s in pool.stale_tables()], ["casual/test"])

    def test_an_incomplete_pool_is_reported_and_the_change_still_saved(self):
        self.cards_csv("collection.csv", ("Not a real card", "fdn", "999", "nonfoil", 1))
        _, summary = inventory.apply(self.order(), TESTER, "Order from Shop")
        self.assertIn("incomplete card pool", summary.extra["tables"]["error"])
        self.assertEqual(summary.extra["tables"]["written"], [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertTrue((self.magic / "orders/records/2026-10-12-shop.json").exists())

    def test_a_failed_plan_never_stops_the_change(self):
        with mock.patch.object(inventory_refresh, "plan_texts", side_effect=RuntimeError("Fixture failure")):
            _, summary = inventory.apply(self.order(), TESTER, "Order from Shop")
        self.assertEqual(summary.extra["tables"]["error"], "Fixture failure")
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertTrue((self.magic / "orders/2026-10-12-shop.csv").exists())

    def test_a_deck_saved_while_the_change_is_written_refuses_the_whole_change(self):
        # The refreshed deck is one of the change's files: a save of it between the operation's
        # load and the files' write (a test editing the file holds no _save_lock) refuses the
        # order as well, with nothing written, rather than skipping it.
        from decklab.lib.inventory.files import FileInventory
        from decklab.lib.state import Conflict
        real, edited = FileInventory._write_plain, self.text + "\nSaved meanwhile.\n"

        def write(backend, *args, **kwargs):
            self.path.write_text(edited, encoding="utf-8", newline="\n")
            return real(backend, *args, **kwargs)
        collection = (self.magic / "collection.csv").read_bytes()
        with mock.patch.object(FileInventory, "_write_plain", write), self.assertRaises(Conflict) as caught:
            inventory.apply(self.order(), TESTER, "Order from Shop")
        self.assertIn("decks/casual/test.md", str(caught.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), edited)
        self.assertEqual((self.magic / "collection.csv").read_bytes(), collection)
        self.assertFalse((self.magic / "orders/2026-10-12-shop.csv").exists())
        self.assertFalse((self.magic / "orders/records/2026-10-12-shop.json").exists())

    def test_an_operation_that_changes_nothing_refreshes_nothing(self):
        inv = inventory.current()
        summary = inventory.Summary("nothing")
        with mock.patch.object(inventory_refresh, "plan_texts") as plan:
            after, out = inventory_refresh.in_op(inv, inv, summary)
        plan.assert_not_called()
        self.assertIs(after, inv)
        self.assertNotIn("tables", out.extra)
