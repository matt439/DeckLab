"""Synthetic card/pool experiments for E2-S33; no card downloads, database or Forge."""
import unittest

from decklab.lib.decks import DeckLine, small_swaps


def card(name, mv, kind="Sorcery", roles=(), colours=("U",), text=""):
    return {"name": name, "cmc": mv, "type_line": kind, "roles": list(roles),
            "colors": list(colours), "oracle_text": text, "mana_cost": f"{{{mv}}}", "faces": []}


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.cards = {c["name"]: c for c in (
            card("Late draw", 6, roles=("draw",)), card("Late answer", 5, roles=("removal",)),
            card("Small draw", 1, roles=("draw",)), card("Small answer", 2, roles=("removal",)),
            card("Small counter", 2, "Instant", roles=("counterspell",)), card("Small body", 1, "Creature"),
            card("Big body", 5, "Creature"), card("Red draw", 1, roles=("draw",), colours=("R",)),
            card("Island", 0, "Basic Land — Island", colours=()),
        )}
        self.source = {"Deck": [DeckLine(2, "Late draw"), DeckLine(2, "Late answer"), DeckLine(56, "Island")]}
        self.considering = [DeckLine(2, "Small draw", "abc", "1", "foil", "Draw")]

    def run_goal(self, goal="earlier", available=None, protected=()):
        return small_swaps.recommend(self.source, self.considering,
                                     available if available is not None else {"Small draw": 3},
                                     self.cards.get, goal, protected)

    def test_one_idea_can_test_one_or_two_copies_without_mutating_the_deck(self):
        out = self.run_goal()
        self.assertEqual(out[0]["cut"], "Late draw")
        self.assertEqual(out[0]["max_qty"], 2)
        self.assertEqual(out[0]["add"], DeckLine(2, "Small draw", "abc", "1", "foil", "Draw"))
        self.assertIn("mana value 1", out[0]["reason"])
        self.assertIn("late-game", out[0]["trade_off"])
        self.assertEqual(self.source["Deck"][0].quantity, 2)
        self.assertEqual(self.considering[0].quantity, 2)
        self.assertEqual(self.run_goal(available={"Small draw": 1})[0]["max_qty"], 1)

    def test_no_free_card_or_protected_cut_means_no_suggestion(self):
        self.assertEqual(self.run_goal(available={}), [])
        self.assertEqual(self.run_goal(protected=("Late draw", "Late answer")), [])
        self.assertEqual([p["cut"] for p in self.run_goal(protected=("Late draw",))], ["Late answer"])

    def test_only_considering_candidates_are_used_and_sideboard_colours_do_not_expand_main(self):
        self.considering = [DeckLine(1, "Red draw")]
        self.source["Sideboard"] = [DeckLine(1, "Red draw")]
        self.assertEqual(self.run_goal(available={"Red draw": 2, "Small draw": 9}), [])

    def test_draw_and_answers_add_a_missing_role_in_a_similar_slot(self):
        out = self.run_goal("draw")
        self.assertEqual([p["cut"] for p in out], ["Late answer"])
        self.assertIn("draw conditions", out[0]["trade_off"])
        self.considering = [DeckLine(2, "Small answer")]
        out = self.run_goal("answers", {"Small answer": 2})
        self.assertEqual([p["cut"] for p in out], ["Late draw"])
        self.assertIn("situational answer", out[0]["trade_off"])
        self.assertIn("draw role", out[0]["trade_off"])
        self.considering = [DeckLine(1, "Small counter")]
        self.assertTrue(self.run_goal("answers", {"Small counter": 1}))

    def test_four_copy_cap_counts_sideboard_and_caps_optional_second_copy(self):
        self.source["Sideboard"] = [DeckLine(3, "Small draw")]
        self.assertEqual(self.run_goal()[0]["max_qty"], 1)
        self.source["Sideboard"][0].quantity = 4
        self.assertEqual(self.run_goal(), [])

    def test_cannot_borrow_second_copy_from_another_considering_printing(self):
        self.considering = [DeckLine(1, "Small draw", "abc", "1", category="Draw"),
                            DeckLine(2, "Small draw", "def", "2", category="Other")]
        out = self.run_goal()
        self.assertEqual(out[0]["max_qty"], 1)
        self.assertEqual(out[0]["add"].set, "abc")
        self.assertEqual(len(out), 2)       # one per cut idea, not one per printing

    def test_x_spells_lands_and_multiface_cards_are_not_called_cheap(self):
        for change in ({"mana_cost": "{X}{U}"}, {"mana_cost": ""}, {"type_line": "Land"},
                       {"faces": [{"name": "front"}, {"name": "back"}]}):
            with self.subTest(change=change):
                self.cards["Small draw"].update(change)
                self.assertEqual(self.run_goal(), [])
                self.setUp()

    def test_creature_slots_are_not_silently_replaced_for_a_role_goal(self):
        self.source = {"Deck": [DeckLine(4, "Big body"), DeckLine(56, "Island")]}
        self.assertEqual(self.run_goal("draw"), [])
        self.considering = [DeckLine(1, "Small body")]
        self.assertTrue(self.run_goal(available={"Small body": 1}))

    def test_no_ban_or_format_legality_filter_and_printed_copy_exceptions(self):
        self.cards["Small draw"]["legalities"] = {"standard": "banned", "commander": "banned"}
        self.assertTrue(self.run_goal())
        self.cards["Small draw"]["oracle_text"] = "A deck can have any number of cards named Small draw."
        self.source["Sideboard"] = [DeckLine(5, "Small draw")]
        self.assertEqual(self.run_goal()[0]["max_qty"], 2)
        self.cards["Small draw"]["oracle_text"] = "A deck can have only one card named Small draw."
        self.source["Sideboard"][0].quantity = 1
        self.assertEqual(self.run_goal(), [])
