"""Blank legacy product metadata must not invent a failed explicit token reservation."""
from decklab.lib import inventory, tokens
from decklab.lib.inventory import files, rules
from decklab.lib.tokens import optimise, products
from decklab.tests import household_config
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


STEM = "fixture-legacy-box"
HOLDER = "product/" + STEM


class ProductTokenLegacyTests(PreparationCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.product(STEM + ".csv", ("deck", "Llanowar Elves", 1), ("deck", "Forest", 20), column="section")
        self.write("tokens.csv", ",".join(rules.TOKEN_FIELDS) + "\nZombie,Zombie Knight,,,,,3,,,\n")

    def status_rows(self, *rows):
        self.write("products/status.csv", rules.csv_bytes(rows, rules.STATUS_FIELDS).decode())

    def test_blank_unknown_or_ambiguous_legacy_status_never_adds_a_failed_record(self):
        for state, intact, duplicate in (("", "", False), ("unknown", "unknown", False), ("owned", "", False),
                                         ("owned", "yes", True)):
            row = {"file": STEM + ".csv", "status": state, "intact": intact, "notes": "Legacy fixture note"}
            self.status_rows(row, *([dict(row)] if duplicate else []))
            warnings = []
            records = products.records(warnings)
            self.assertNotIn(products.FAILED, warnings)
            self.assertFalse(any(record.get("error") for record in records.values()))
            self.assertEqual(tokens.reserve.holds(tokens.read()), {})
            self.assertEqual(optimise.plan(tokens.read(), [])["decks"], [])
        self.status_rows({"file": STEM + ".csv", "status": "owned", "intact": "yes"},
                         {"file": "unrelated.csv", "status": "old-status", "intact": "unknown", "token_cards": ""})
        warnings = []
        self.assertFalse(products.records(warnings)[HOLDER]["written"])
        self.assertNotIn(products.FAILED, warnings)

    def test_the_same_unknown_duplicate_or_orphan_nonempty_record_blocks_planning_without_writes(self):
        cases = [
            [{"file": STEM + ".csv", "status": "unknown", "intact": "unknown", "token_cards": "2 Zombie // Zombie Knight"}],
            [{"file": STEM + ".csv", "status": "owned", "intact": "no", "token_cards": "2 Zombie // Zombie Knight"}],
            [{"file": STEM + ".csv", "status": "owned", "intact": "yes", "token_cards": "2 Zombie // Zombie Knight"},
             {"file": STEM + ".csv", "status": "owned", "intact": "yes", "token_cards": ""}],
            [{"file": "missing-source.csv", "status": "owned", "intact": "yes", "token_cards": "2 Zombie // Zombie Knight"}],
        ]
        for rows in cases:
            self.status_rows(*rows)
            before = files.render(inventory.current())
            warnings = []
            holds = tokens.reserve.holds(tokens.read(), warnings=warnings)
            self.assertIn(products.FAILED, warnings)
            self.assertTrue(any(hold.get("error") for hold in holds.values()))
            with self.assertRaisesRegex(RuntimeError, "packed token record cannot be read"):
                optimise.plan(tokens.read(), [])
            self.assertEqual(files.render(inventory.current()), before)
