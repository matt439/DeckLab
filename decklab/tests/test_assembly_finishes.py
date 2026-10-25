"""Build decks describes each selected list's finishes without allocating printings."""
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


class AssemblyFinishesTests(PreparationCase):
    def test_mixed_finishes_aggregate_each_list_without_leaking_between_decks(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 6))
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves *F*\n1 Llanowar Elves\n"
                  "2 Forest *F*\n20 Forest\nSideboard\n1 llanowar elves *F*\n")
        self.deck("b", "B", "building", "Deck\n2 Llanowar Elves *E*\n")
        result = self.preview(("a", "target"), ("b", "target"))
        first, second = result["decks"]
        self.assertEqual(first["finishes"]["Llanowar Elves"],
                         [{"finish": "foil", "quantity": 3}, {"finish": "nonfoil", "quantity": 1}])
        self.assertEqual(first["finishes"]["Forest"],
                         [{"finish": "foil", "quantity": 2}, {"finish": "nonfoil", "quantity": 20}])
        self.assertEqual(second["finishes"]["Llanowar Elves"], [{"finish": "etched", "quantity": 2}])
        self.assertNotIn("llanowar elves", first["finishes"])
        self.assertNotIn("finish", result["cards"]["Llanowar Elves"])
        # Finishes are list metadata. All six owned copies still satisfy the name-based plan.
        self.assertTrue(result["ready"])
        self.assertEqual(result["totals"]["from_storage"], 6)

    def test_selected_version_supplies_finishes_and_returns_do_not_claim_its_finish(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 3),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves *F*\n",
                  owned="Deck\n3 Llanowar Elves\n1 Elvish Mystic *E*\n", built_version="owned-only")
        target = self.preview(("a", "target"))["decks"][0]
        self.assertEqual(target["finishes"], {"Llanowar Elves": [{"finish": "foil", "quantity": 1}]})
        self.assertEqual(target["returns"], [{"name": "Elvish Mystic", "quantity": 1},
                                             {"name": "Llanowar Elves", "quantity": 2}])
        owned = self.preview(("a", "owned"))["decks"][0]
        self.assertEqual(owned["finishes"], {
            "Llanowar Elves": [{"finish": "nonfoil", "quantity": 3}],
            "Elvish Mystic": [{"finish": "etched", "quantity": 1}]})
        self.assertEqual(owned["returns"], [])
