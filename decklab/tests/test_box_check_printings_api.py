"""Check box's "Which printing?": offers for cards with several owned printings, saved with the date."""
from decklab.lib import inventory
from decklab.lib.api.box_check import save_box_check  # noqa: F401  (the route these tests drive)
from decklab.lib.decks import printings
from decklab.tests import test_box_check_api as base

# The fixture card index and state store, as test_box_check_api's module installs them.
setUpModule = base.setUpModule
tearDownModule = base.tearDownModule

ELF, MYSTIC = base.ELF, base.MYSTIC
FIELD = "Printings in box"


class BoxCheckPrintingsTests(base.BoxCheckCase):
    def setUp(self):
        super().setUp()
        # Two printings of Llanowar Elves, one of Elvish Mystic.
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 4), (ELF, "m19", "314", "nonfoil", 4),
                       (MYSTIC, "cmm", "648", "nonfoil", 8))

    def offers(self):
        return self.offer()["box_check"]["printings"]

    def line(self):
        return self.parsed().get_field(FIELD)

    def test_offers_only_cards_with_two_or_more_owned_printings(self):
        offers = self.offers()
        self.assertEqual(list(offers), [ELF])
        elf = offers[ELF]
        self.assertEqual((elf["held"], elf["recorded"]), (4, 0))
        self.assertEqual([(o["label"], o["free"], o["recorded"]) for o in elf["options"]],
                         [("FDN 227", 4, 0), ("M19 314", 4, 0)])
        self.assertTrue(all(isinstance(o["set_name"], str) for o in elf["options"]))

    def test_printings_save_with_the_date_in_one_save(self):
        before = self.record().sha256
        answer = self.save(printings={ELF: [
            {"set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 3},
            {"set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": 1}]})
        self.assertTrue(answer["saved"])
        self.assertTrue(answer["printings_changed"])
        self.assertEqual(answer["sha256"], self.record().sha256)
        self.assertNotEqual(answer["sha256"], before)
        self.assertEqual(self.line(), f"3 {ELF} (FDN) 227; 1 {ELF} (M19) 314")
        self.assertEqual(self.parsed().get_field("Box checked"), base.WHEN)
        recorded = self.offers()[ELF]
        self.assertEqual([o["recorded"] for o in recorded["options"]], [3, 1])
        self.assertEqual(recorded["recorded"], 4)

    def test_same_day_recheck_saves_a_printing_change_and_reports_it(self):
        self.save()
        self.assertEqual(self.parsed().get_field("Box checked"), base.WHEN)
        answer = self.save(printings={ELF: [{"set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": 2}]})
        self.assertTrue(answer["saved"])
        self.assertTrue(answer["printings_changed"])
        self.assertEqual(self.line(), f"2 {ELF} (M19) 314")

    def test_without_printings_nothing_else_changes_and_none_is_reported(self):
        answer = self.save()
        self.assertFalse(answer["printings_changed"])
        self.assertIsNone(self.line())

    def test_a_card_not_named_keeps_its_record_and_an_empty_list_clears_one(self):
        deck = self.parsed()
        printings.set_printings(deck, [printings.PrintingLine(1, MYSTIC, "cmm", "648"),
                                       printings.PrintingLine(2, ELF, "fdn", "227")])
        self.write_parsed(deck)
        self.save(printings={ELF: []})
        self.assertEqual(self.line(), f"1 {MYSTIC} (CMM) 648")

    def test_impossible_records_are_refused_without_writing(self):
        before = self.record().sha256
        for picks, status in (
                ({ELF: [{"set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 5}]}, 400),
                ({ELF: [{"set": "cmm", "collector_number": "648", "finish": "nonfoil", "quantity": 1}]}, 400),
                ({"Forest": [{"set": "fdn", "collector_number": "280", "finish": "nonfoil", "quantity": 1}]}, 400),
                ({"llanowar elves": []}, 400),
                ({ELF: [{"set": "fdn", "collector_number": "227", "finish": "shiny", "quantity": 1}]}, 400),
                ({ELF: [{"set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 1, "x": 1}]}, 400),
                ([], 400)):
            with self.subTest(picks=picks):
                self.refused(status, printings=picks)
                self.assertEqual(self.record().sha256, before)

    def test_more_copies_than_the_collection_across_built_decks_is_a_conflict(self):
        self.deck("b", "B", "built", f"Deck\n4 {ELF}\n20 Forest\n")
        other = inventory.current().deck("casual/b")
        parsed = base.ops_decks.parsed_deck(other)
        printings.set_printings(parsed, [printings.PrintingLine(4, ELF, "m19", "314")])
        self.write("decks/casual/b.md", base.decks.render_deck_file(parsed))
        self.assertEqual([o["free"] for o in self.offers()[ELF]["options"]], [4, 0])
        before = self.record().sha256
        self.refused(409, printings={ELF: [{"set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": 1}]})
        self.assertEqual(self.record().sha256, before)

    def test_an_out_of_date_part_of_another_card_is_dropped_not_refused(self):
        deck = self.parsed()
        printings.set_printings(deck, [printings.PrintingLine(1, MYSTIC, "cmm", "648"),
                                       printings.PrintingLine(2, ELF, "fdn", "227")])
        self.write_parsed(deck)
        # The CMM Elvish Mystic leaves the collection: that part is now out of date.
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 4), (ELF, "m19", "314", "nonfoil", 4),
                       (MYSTIC, "dom", "164", "nonfoil", 8))
        answer = self.save(printings={ELF: [{"set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": 1}]})
        self.assertTrue(answer["printings_changed"])
        self.assertEqual(self.line(), f"1 {ELF} (M19) 314")
        self.assertEqual(self.parsed().get_field("Box checked"), base.WHEN)
