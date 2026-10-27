"""A built deck's Printings in box line: the record, its checks, Finish building and the pool."""
import json
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import decks, inventory, pool
from decklab.lib.api import (assembly, assembly_completion as completion, collection_edit as ce,
                             collection_sources, deck_printings, settings)
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled, printings
from decklab.lib.inventory import ops_decks
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401

PROFILES = [{"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user"}]
TABLE = "| Llanowar Elves | 1 | 0 | 1 | | | |\n"
LINE = "- **Printings in box:** "


class LineTests(unittest.TestCase):
    def test_parse_and_format_round_trip(self):
        value = "2 Llanowar Elves (FDN) 227; 1 Fire // Ice (M19) 314 foil; 1 Sol Ring (PDMU) 1★ etched"
        lines = printings.parse_printings(value)
        self.assertEqual(lines[0], printings.PrintingLine(2, "Llanowar Elves", "fdn", "227"))
        self.assertEqual((lines[1].name, lines[1].finish), ("Fire // Ice", "foil"))
        self.assertEqual(lines[2].label(), "PDMU 1★ etched")
        self.assertEqual(printings.format_printings(lines), value)
        self.assertEqual(printings.parse_printings("  "), [])

    def test_bad_parts_are_refused(self):
        for value in ("Llanowar Elves (FDN) 227", "0 Llanowar Elves (FDN) 227", "2 Llanowar Elves",
                      "2 Llanowar Elves (FDN) 227 shiny"):
            with self.subTest(value=value), self.assertRaises(decks.DeckFileError):
                printings.parse_printings(value)

    def test_trim_and_local_problems(self):
        lines = printings.parse_printings("3 Llanowar Elves (FDN) 227; 2 Llanowar Elves (M19) 314; 1 Forest (FDN) 280")
        held = Counter({"Llanowar Elves": 4})
        canon = lambda name: name   # noqa: E731
        self.assertEqual([line.text() for line in printings.trim(lines, held, canon)],
                         ["3 Llanowar Elves (FDN) 227", "1 Llanowar Elves (M19) 314"])
        problems = printings.local_problems(lines, held, canon)
        self.assertEqual(len(problems), 2)
        self.assertIn("basic lands", problems[0])
        self.assertIn("5 copies recorded", problems[1])

    def test_effective_drops_over_capacity_printing_everywhere(self):
        canon = lambda name: name   # noqa: E731
        records = {"a": printings.parse_printings("2 Llanowar Elves (FDN) 227"),
                   "b": printings.parse_printings("1 Llanowar Elves (FDN) 227; 1 Llanowar Elves (M19) 314")}
        held = {"a": Counter({"Llanowar Elves": 2}), "b": Counter({"Llanowar Elves": 2})}
        owned = {("fdn", "227", "nonfoil"): ("Llanowar Elves", 2), ("m19", "314", "nonfoil"): ("Llanowar Elves", 1)}
        kept, stale = printings.effective(records, held, owned, canon)
        self.assertEqual(kept["a"], Counter())
        self.assertEqual(kept["b"], Counter({("Llanowar Elves", "m19", "314", "nonfoil"): 1}))
        self.assertEqual(set(stale), {"a", "b"})


class PrintingsInBoxTests(PreparationCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Llanowar Elves", "m19", "314", "nonfoil", 2),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))

    def parsed(self, slug):
        return ops_decks.parsed_deck(inventory.current().deck(f"casual/{slug}"))

    def save(self, slug, edit):
        stored = inventory.current().deck(f"casual/{slug}")
        text = edit(stored.text)
        return inventory.apply(inventory.Op("deck.save", {"deck_id": stored.id, "text": text,
                                                          "base_sha256": stored.sha256}), inventory.Actor("test", "Test"), "save")

    def with_line(self, value):
        return lambda text: text.replace("- **Status:** built\n", f"- **Status:** built\n{LINE}{value}\n")

    def request(self, *selected):
        choices = [{"id": f"casual/{slug}", "version": version} for slug, version in selected]
        plan = assembly.assembly_preview(json.dumps({"profile": "matt", "decks": choices}))
        return plan, {"profile": "matt", "decks": choices, "confirmed": True,
                      "fingerprint": plan["completion"]["fingerprint"]}

    def test_push_records_and_refuses_what_the_box_or_collection_cannot_hold(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n20 Forest\n", table=TABLE)
        self.deck("b", "B", "built", "Deck\n2 Llanowar Elves\n", table=TABLE)
        self.save("a", self.with_line("2 Llanowar Elves (FDN) 227; 2 Llanowar Elves (M19) 314"))
        self.assertEqual(len(printings.printings(self.parsed("a"))), 2)
        for value, code in (("5 Llanowar Elves (FDN) 227", 400), ("1 Elvish Mystic (CMM) 648", 400),
                            ("1 Llanowar Elves (CMM) 648", 400), ("2 Forest (FDN) 280", 400),
                            ("1 Llanowar Elves (FDN) 227", 409)):
            with self.subTest(value=value), self.assertRaises(ops_decks.DeckRefused) as caught:
                self.save("b", self.with_line(value))
            self.assertEqual((caught.exception.code, caught.exception.reason), (code, "printings"))

    def test_collection_change_leaves_the_record_but_ignores_it(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n", table=TABLE)
        self.save("a", self.with_line("2 Llanowar Elves (FDN) 227; 2 Llanowar Elves (M19) 314"))
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1),
                       ("Llanowar Elves", "m19", "314", "nonfoil", 3))
        held = next(item for item in pool.load_pool().in_use if item.id == "casual/a")
        self.assertEqual(held.recorded, Counter({("Llanowar Elves", "m19", "314", "nonfoil"): 2}))
        self.assertTrue(held.recorded_stale)
        # An unrelated save of the deck still goes through.
        self.save("a", lambda text: text + "\n## Notes\n\nStill fine.\n")

    def test_take_apart_removes_the_line(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n", table=TABLE)
        self.save("a", self.with_line("2 Llanowar Elves (FDN) 227"))
        deck = self.parsed("a")
        assembled.clear(deck)
        self.assertFalse(printings.has_printings(deck))

    def test_member_deck_cannot_gain_the_line(self):
        with self.assertRaises(inventory.Invalid):
            ops_decks._parse("user2/casual/x", decks_text("Printings in box", "1 Llanowar Elves (FDN) 227"),
                             "user2", "casual", "x")

    def test_finish_building_offers_and_writes_printings(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n4 Elvish Mystic\n", table=TABLE)
        plan, body = self.request(("a", "target"))
        offered = plan["decks"][0]["printing_choices"]
        self.assertEqual([o["label"] for o in offered["Llanowar Elves"]["options"]], ["FDN 227", "M19 314"])
        self.assertIsNone(offered["Llanowar Elves"]["only"])
        self.assertEqual(offered["Elvish Mystic"]["only"]["label"], "CMM 648")
        body["printings"] = {"casual/a": [
            {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 2},
            {"name": "Elvish Mystic", "set": "cmm", "collector_number": "648", "finish": "nonfoil", "quantity": 4}]}
        completion.mark_built(json.dumps(body))
        self.assertEqual(self.parsed("a").get_field("Printings in box"),
                         "2 Llanowar Elves (FDN) 227; 4 Elvish Mystic (CMM) 648")

    def test_finish_building_refuses_a_printing_not_offered(self):
        self.deck("b", "B", "built", "Deck\n2 Llanowar Elves\n", table=TABLE)
        self.save("b", self.with_line("2 Llanowar Elves (FDN) 227"))
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves\n", table=TABLE)
        plan, body = self.request(("a", "target"))
        self.assertEqual(plan["decks"][0]["printing_choices"]["Llanowar Elves"]["only"]["label"], "M19 314")
        body["printings"] = {"casual/a": [{"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                           "finish": "nonfoil", "quantity": 2}]}
        with self.assertRaises(ApiError) as caught:
            completion.mark_built(json.dumps(body))
        self.assertEqual(caught.exception.status, 409)


    def test_deck_page_part_and_its_save(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n4 Elvish Mystic\n", table=TABLE)
        self.deck("b", "B", "built", "Deck\n1 Llanowar Elves\n", table=TABLE)
        self.save("b", self.with_line("1 Llanowar Elves (FDN) 227"))
        stored = inventory.current().deck("casual/a")
        with mock.patch.object(deck_printings.guard, "allowed", return_value=True):
            info = deck_printings.view(self.parsed("a"), stored, pool.load_pool())
        self.assertEqual(info["recorded"], [])
        elves = next(card for card in info["cards"] if card["name"] == "Llanowar Elves")
        self.assertEqual([(o["label"], o["free"]) for o in elves["options"]], [("FDN 227", 1), ("M19 314", 2)])
        body = {"profile": "matt", "id": "casual/a", "expect": info["expect"], "cards": [
            {"name": "Llanowar Elves", "set": "m19", "collector_number": "314", "finish": "nonfoil", "quantity": 2}]}
        answer = deck_printings.save_printings(json.dumps(body))
        self.assertEqual(answer["printings_in_box"], "2 Llanowar Elves (M19) 314")
        # Stale expect, then a record the collection can't hold.
        with self.assertRaises(ApiError) as caught:
            deck_printings.save_printings(json.dumps(body))
        self.assertEqual(caught.exception.status, 409)
        body = {**body, "expect": inventory.current().deck("casual/a").sha256, "cards": [
            {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": 2}]}
        with self.assertRaises(ApiError) as caught:
            deck_printings.save_printings(json.dumps(body))
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("the collection has 2", str(caught.exception))


class CollectionStorageTests(unittest.TestCase):
    def test_recorded_copies_come_first_exactly_and_replace_the_lists_hints(self):
        row = lambda s, n, q: {"name": "Llanowar Elves", "set": s, "collector_number": n,   # noqa: E731
                               "finish": "nonfoil", "quantity": q}
        rows = [row("fdn", "227", "2"), row("m19", "314", "2")]
        holder = pool.InUse("casual/a", "A", "built", Counter({"Llanowar Elves": 2}),
                            printings=Counter({("Llanowar Elves", "fdn", "227", "nonfoil"): 2}),
                            recorded=Counter({("Llanowar Elves", "m19", "314", "nonfoil"): 2}))
        fake = pool.Pool(Counter(), {}, [holder])
        with mock.patch.object(pool, "load_pool", return_value=fake), \
                mock.patch.object(ce, "_ready", return_value=True), \
                mock.patch.object(collection_sources, "named_holder", return_value=True), \
                mock.patch.object(ce.guard, "deck_reader", return_value=lambda deck_id: True), \
                mock.patch.object(ce.guard, "sees_home_records", return_value=True), \
                mock.patch.object(ce.cards, "resolve", side_effect=lambda name: name):
            storage = ce._storage("home", rows, {"rows": {}})
        self.assertNotIn("fdn|227|nonfoil", storage["rows"])
        recorded = storage["rows"]["m19|314|nonfoil"]
        self.assertEqual((recorded["held"], recorded["recorded"], recorded["guess"]), (2, 2, False))
        self.assertEqual([(h["id"], h["quantity"], h.get("recorded")) for h in recorded["listed_holders"]],
                         [("casual/a", 2, True)])


def decks_text(key, value):
    return (f"# X\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** built\n- **{key}:** {value}\n\n"
            "## Decklist\n\n```\nDeck\n4 Llanowar Elves\n```\n")


if __name__ == "__main__":
    unittest.main()
