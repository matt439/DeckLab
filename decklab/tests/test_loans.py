"""Loose-card loan operations, availability, exact-printing guards and private export parity."""
from decklab.lib import inventory, pool
from decklab.lib.inventory import Op, files, loan_rules, ops_collection, ops_loans, rules, table_rows
from decklab.lib.state import Actor, Conflict, Invalid
from decklab.tests import test_pool as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule
ACTOR = Actor("matt", "Matt", "home", "test")


def facts(**changes):
    return {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": "1",
            "borrower": "User1", "lent_on": "2026-11-11", "notes": "PRIVATE LOAN NOTE", **changes}


class FileLoanTests(support.PoolTestCase):
    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Llanowar Elves", "m19", "314", "nonfoil", 2))

    def lend(self, **changes):
        return inventory.apply(ops_loans.op("lend", space="home", row=facts(**changes), loan_id="a" * 32), ACTOR, "Lend fixture copies")

    def test_lend_and_whole_return_change_no_ownership_and_pool_uses_only_safe_counts(self):
        before = self.inventory.load()
        after, summary = self.lend(quantity="2")
        self.assertEqual(files.render_sheet(after.collection()), files.render_sheet(before.collection()))
        self.assertEqual(len(after.loan_set().rows), 1)
        self.assertNotIn("User1", summary.text)
        self.assertNotIn("PRIVATE", summary.text)
        supply = pool.load_pool()
        self.assertEqual(pool.free_copies(supply)["Llanowar Elves"], 4)
        self.assertEqual(supply.in_use[-1].title, "lent out")
        self.assertNotIn("User1", repr(supply))
        self.assertNotIn("PRIVATE", repr(supply))
        result = pool.compare({"Deck": [support.decks.parse_line("6 Llanowar Elves")]}, supply, prices=False)
        self.assertEqual((result["rows"][0]["available"], result["rows"][0]["missing"]), (4, 2))
        self.assertIn("2 lent out", pool._labels(result["rows"][0]))
        from decklab.lib import arrivals
        self.assertEqual(arrivals._here(result["rows"][0]), 4)
        after, _ = inventory.apply(ops_loans.op("return", space="home", loan_id="a" * 32, returned_on="2026-11-12"),
                                    ACTOR, "Return fixture copies")
        self.assertEqual(pool.free_copies(pool.load_pool())["Llanowar Elves"], 6)
        self.assertEqual(after.loan_set().rows[0].get("returned_on"), "2026-11-12")
        with self.assertRaisesRegex(Conflict, "open loan wasn't found"):
            inventory.apply(ops_loans.op("return", space="home", loan_id="a" * 32, returned_on="2026-11-12"), ACTOR, "Duplicate return")

    def test_exact_printing_capacity_excludes_unlocated_built_holds_and_never_counts_incoming(self):
        self.deck("held", "Held", "built", "Deck\n3 Llanowar Elves (M19) 314\n57 Forest\n")
        before = files.render(self.inventory.load(), decks=True)
        with self.assertRaisesRegex(Invalid, "Only 1 copies"):
            self.lend(quantity="2")
        self.assertEqual(files.render(self.inventory.load(), decks=True), before)
        self.lend(quantity="1")
        with self.assertRaisesRegex(Conflict, "already exists"):
            self.lend(quantity="1")

    def test_collection_reduction_or_printing_rekey_cannot_remove_a_lent_copy(self):
        self.lend(quantity="3")
        before = self.inventory.load()
        source = ops_collection.rows_of(before.collection())[0]
        for operation in (Op("collection.remove", {"space": "home", "original": ["fdn", "227", "nonfoil"]}),
                          Op("collection.edit", {"space": "home", "original": ["fdn", "227", "nonfoil"],
                                                 "row": dict(source, quantity="2")}),
                          Op("collection.trade", {"space": "home", "gave": [["fdn", "227", "nonfoil", 2]],
                                                  "got": [dict(zip(rules.FIELDS, ["Llanowar Elves", "m19", "314", "nonfoil", "1", "NM", "en", ""]))]})):
            with self.subTest(kind=operation.kind), self.assertRaisesRegex(Invalid, "still lent out"):
                inventory.apply(operation, ACTOR, "Refuse lent reduction")
            self.assertEqual(files.render(self.inventory.load()), files.render(before))

    def test_stale_collection_and_invalid_return_refuse_without_writes(self):
        before = self.inventory.load()
        with self.assertRaises(ops_collection.Stale):
            inventory.apply(ops_loans.op("lend", space="home", row=facts(), sha256="0" * 64), ACTOR, "Refuse stale loan")
        self.assertEqual(files.render(self.inventory.load()), files.render(before))
        self.lend()
        before = self.inventory.load()
        with self.assertRaisesRegex(Invalid, "before the lent date"):
            inventory.apply(ops_loans.op("return", space="home", loan_id="a" * 32, returned_on="2026-11-10"), ACTOR, "Refuse early return")
        self.assertEqual(files.render(self.inventory.load()), files.render(before))

    def test_snapshot_export_and_table_rows_roundtrip_keep_private_loan_record_only_in_private_source(self):
        after, _ = self.lend(quantity="2")
        encoded = files.render(after)
        self.assertEqual(set(encoded) - set(files.render(after.replace(loans={}))), {"magic/loans.csv"})
        again = files.build(encoded)
        self.assertEqual(again.loans, after.loans)
        self.assertEqual(table_rows.tables(again)["card_loan"][("home", "a" * 32)],
                         ("Llanowar Elves", "fdn", "227", "nonfoil", 2, "User1", "2026-11-11", None, "PRIVATE LOAN NOTE"))
        self.assertEqual(loan_rules.problems([row.as_dict() for row in again.loan_set().rows], lambda n: f"row {n}"), [])

    def test_older_schema_refuses_new_loan_before_writes(self):
        before = self.inventory.load()
        with self.assertRaisesRegex(Invalid, "migration 0024"):
            ops_loans.op("lend", space="home", row=facts()).run(before.replace(loans_ready=False))
        self.assertFalse((self.magic / "loans.csv").exists())

    def test_new_built_holder_cannot_take_lent_supply_even_through_the_low_level_deck_operation(self):
        from decklab.lib.inventory import ops_decks
        self.deck("candidate", "Candidate", "building", "Deck\n3 Llanowar Elves\n57 Forest\n")
        self.lend(quantity="4")
        before = self.inventory.load()
        deck = before.deck("casual/candidate")
        operation = Op("deck.save", {"deck_id": deck.id, "text": deck.text.replace("**Status:** building", "**Status:** built"),
                                     "base_sha256": deck.sha256, "allow_assembled": True})
        self.assertTrue(callable(ops_decks.save))
        with self.assertRaisesRegex(Invalid, "holder would use copies still lent out"):
            inventory.apply(operation, ACTOR, "Refuse taking lent cards")
        self.assertEqual(files.render(self.inventory.load(), decks=True), files.render(before, decks=True))

    def test_recording_a_loaned_printing_in_a_box_is_refused_even_when_total_names_fit(self):
        from decklab.lib.inventory import ops_decks
        self.deck("held", "Held", "built", "Deck\n1 Llanowar Elves\n59 Forest\n")
        text = (self.magic / "decks/casual/held.md").read_text()
        self.write("decks/casual/held.md", text.replace("**Status:** built", "**Status:** built\n- **Printings in box:** 1 Llanowar Elves (M19) 314"))
        self.lend(quantity="4")
        before = self.inventory.load()
        deck = before.deck("casual/held")
        operation = Op("deck.save", {"deck_id": deck.id, "text": deck.text.replace("(M19) 314", "(FDN) 227"),
                                     "base_sha256": deck.sha256})
        self.assertTrue(callable(ops_decks.save))
        with self.assertRaisesRegex(Invalid, "holder would use copies still lent out"):
            inventory.apply(operation, ACTOR, "Refuse recording lent printing")
        self.assertEqual(files.render(self.inventory.load(), decks=True), files.render(before, decks=True))

    def test_spares_withholds_lent_exact_printings_and_names_only_the_safe_reason(self):
        from decklab.lib.api import collection_spares
        self.lend(quantity="2")
        current = self.inventory.load()
        with inventory.pinned(current):
            spare = collection_spares.analyze(current, pool.load_pool(), "home")
        self.assertTrue(spare["ready"])
        cards = spare["rows"]["Llanowar Elves"]
        self.assertEqual(cards["spare"], 4)
        self.assertIn("2 lent out", cards["reason"])
        self.assertEqual({(row["set"], row["quantity"]) for row in cards["printings"]}, {("fdn", 2), ("m19", 2)})
        self.assertNotIn("PRIVATE", str(spare))
        self.assertNotIn("User1", str(spare))

    def test_table_labels_and_stale_deck_names_follow_lend_and_return_without_losing_hand_notes(self):
        from decklab.lib import decks
        self.deck("target", "Target", "idea", "Deck\n6 Llanowar Elves\n54 Forest\n",
                  table="| Llanowar Elves | 6 | 6 | 0 | | | keep hand note |\n| **Total** | | | 0 | | | |\n")
        self.assertEqual(pool.stale_tables(), [])
        self.lend(quantity="2")
        self.assertIn("casual/target", {item["id"] for item in pool.stale_tables()})
        path = self.magic / "decks/casual/target.md"
        parsed = decks.read_deck_file(path)
        decks.set_table(parsed, *pool.deck_table(parsed, prices=False))
        self.write("decks/casual/target.md", decks.render_deck_file(parsed))
        self.assertIn("2 lent out", path.read_text())
        self.assertIn("keep hand note", path.read_text())
        inventory.apply(ops_loans.op("return", space="home", loan_id="a" * 32, returned_on="2026-11-12"), ACTOR, "Return fixture cards")
        self.assertIn("casual/target", {item["id"] for item in pool.stale_tables()})
        parsed = decks.read_deck_file(path)
        decks.set_table(parsed, *pool.deck_table(parsed, prices=False))
        rendered = decks.render_deck_file(parsed)
        self.assertNotIn("lent out", rendered)
        self.assertIn("keep hand note", rendered)

    def test_collection_decrease_keeps_enough_other_physical_copies_for_built_holders_while_lent(self):
        self.deck("held", "Held", "built", "Deck\n1 Llanowar Elves\n59 Forest\n")
        text = (self.magic / "decks/casual/held.md").read_text()
        self.write("decks/casual/held.md", text.replace("**Status:** built", "**Status:** built\n- **Printings in box:** 1 Llanowar Elves (M19) 314"))
        self.lend(quantity="4")
        original = next(row.as_dict() for row in self.inventory.load().collection().rows if row.text("set") == "m19")
        inventory.apply(Op("collection.edit", {"space": "home", "original": ["m19", "314", "nonfoil"],
                                               "row": dict(original, quantity="1")}), ACTOR, "Remove only the genuinely loose surplus")
        before = self.inventory.load()
        with self.assertRaisesRegex(Invalid, "lent out"):
            inventory.apply(Op("collection.remove", {"space": "home", "original": ["m19", "314", "nonfoil"]}), ACTOR, "Refuse taking held supply")
        self.assertEqual(files.render(self.inventory.load(), decks=True), files.render(before, decks=True))

    def test_another_spaces_damaged_private_loan_never_blocks_or_describes_itself_in_home_changes(self):
        self.lend()
        foreign = self.magic / "people/user2/loans.csv"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("id,name,set,collector_number,finish,quantity,borrower,lent_on,returned_on,notes\n"
                           + "b" * 32 + ",Llanowar Elves,fdn,227,nonfoil,0,PRIVATE BORROWER,2026-11-11,,PRIVATE NOTE\n")
        original = foreign.read_bytes()
        row = next(row.as_dict() for row in self.inventory.load().collection().rows if row.text("set") == "m19")
        _, summary = inventory.apply(Op("collection.add", {"space": "home", "row": row}), ACTOR, "Add loose fixture copies")
        self.assertEqual(foreign.read_bytes(), original)
        self.assertNotIn("PRIVATE", str(summary))
