"""The server side of the pickers' Game Changer chip (E9-S30): the shared card JSON carries Scryfall's
game_changer flag wherever a picker lists a card (the name search, the editor's finder, a deck's lines and
its Considering list), and a Commander draft's checked bracket says what its minimum would be with one more
Game Changer. Fixture cards only (Rhystic Study is the fixture's Game Changer).
"""
import unittest

from decklab.lib import api, cards, stats
from decklab.lib.api import card_lookup
from decklab.tests.test_editor import EditorTestCase

GHALTA = {"qty": 1, "name": "Ghalta, Primal Hunger"}


class CardJsonTests(EditorTestCase):

    def test_the_card_json_carries_scryfalls_flag_as_a_boolean(self):
        study, elves = cards.card("Rhystic Study"), cards.card("Llanowar Elves")
        self.assertIs(card_lookup._card_json(study, None)["game_changer"], True)
        self.assertIs(card_lookup._card_json(elves, None)["game_changer"], False)
        # A card dict without the field (an older index, a hand-made one) is simply not one.
        bare = {key: value for key, value in elves.items() if key != "game_changer"}
        self.assertIs(card_lookup._card_json(bare, None)["game_changer"], False)

    def test_the_name_search_and_the_finder_mark_it(self):
        found = {c["name"]: c["game_changer"] for c in api.search("rhystic", "8", "1")["cards"]}
        self.assertEqual(found, {"Rhystic Study": True})
        found = {c["name"]: c["game_changer"] for c in api.search("llan", "8", "1")["cards"]}
        self.assertEqual(found, {"Llanowar Elves": False})
        finder = api.find_cards("rhystic", deck_id="commander/elf-commander")["cards"]
        self.assertEqual([(c["name"], c["game_changer"]) for c in finder], [("Rhystic Study", True)])
        # A 60-card deck's finder carries the same card data: the page shows no chip there (E2-S21).
        casual = api.find_cards("rhystic", deck_id="casual/table-test")["cards"]
        self.assertEqual([(c["name"], c["game_changer"]) for c in casual], [("Rhystic Study", True)])

    def test_a_checked_drafts_lines_and_considering_carry_it(self):
        view = api.edit_view("commander/elf-commander")
        lists = self.edit_lists(view)
        lists["target"]["Deck"] += [{"qty": 1, "name": "Rhystic Study"}]
        lists["considering"] = [{"qty": 1, "name": "Rhystic Study"}, {"qty": 1, "name": "Llanowar Elves"}]
        answer = api.check_draft(self.body(id="commander/elf-commander", lists=lists))
        self.assertEqual([(line["name"], line["card"]["game_changer"]) for line in answer["lists"]["considering"]],
                         [("Rhystic Study", True), ("Llanowar Elves", False)])
        deck = {line["name"]: line["card"]["game_changer"] for line in answer["lists"]["target"]["Deck"]}
        self.assertIs(deck["Rhystic Study"], True)


class BracketWithOneMoreTests(EditorTestCase):

    def check(self, *deck, **fields):
        lists = {"target": {"Commander": [dict(GHALTA)], "Deck": [{"qty": 1, "name": name} for name in deck]}}
        return api.check_draft(self.body(kind="commander", lists=lists, fields=fields))["bracket"]

    def test_the_first_game_changer_would_leave_brackets_one_and_two(self):
        bracket = self.check("Sol Ring")
        self.assertEqual((bracket["minimum"], bracket["game_changers"]), (1, []))
        self.assertEqual(bracket["with_game_changer"], 3)
        self.assertEqual(bracket["target"], 2)

    def test_a_deck_already_holding_some_stays_in_bracket_three(self):
        bracket = self.check("Sol Ring", "Rhystic Study")
        self.assertEqual([g["name"] for g in bracket["game_changers"]], ["Rhystic Study"])
        self.assertEqual((bracket["minimum"], bracket["with_game_changer"]), (3, 3))

    def test_it_follows_min_bracket_at_bracket_threes_limit(self):
        limit = stats.UPGRADED_MAX_GAME_CHANGERS
        self.assertEqual(stats.min_bracket(limit, 0, 0), 3)
        self.assertEqual(stats.min_bracket(limit + 1, 0, 0), 4)
        rules = stats.deck_rules(self.sections("Sol Ring", "Rhystic Study"), "commander")["commander"]["bracket"]
        self.assertEqual(rules["minimum_with_game_changer"], stats.min_bracket(2, 0, 0))

    def sections(self, *deck):
        from decklab.lib import decks
        text = "Commander\n1 Ghalta, Primal Hunger\n\nDeck\n" + "".join(f"1 {name}\n" for name in deck)
        return decks.parse_decklist(text)

    def test_a_casual_deck_has_no_bracket(self):
        lists = {"target": {"Deck": [{"qty": 4, "name": "Llanowar Elves"}]}}
        self.assertIsNone(api.check_draft(self.body(kind="casual", lists=lists))["bracket"])


if __name__ == "__main__":
    unittest.main()
