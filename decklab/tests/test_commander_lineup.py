"""A Commander night line-up (E9-S34): lib/commander_lineup.py's lineup() over plain deck summaries (each
group, the limit from the aim and the range, the deciding cards, every unknown case, trials and retired decks
left out, the ordering, and what each row carries).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_commander_lineup
"""
import unittest

from decklab.lib import commander_lineup as lineup_module
from decklab.lib.commander_lineup import lineup

TODAY = "2026-11-12"
NIGHT = {"name": "Fixture night", "venue": "Fictional venue", "target_bracket": 2,
         "published_min": 1, "published_max": 3, "house_rules": "", "checked_on": ""}


def bracket(minimum, gc=(), mld=(), turns=(), combos=(), unknown=(), tags=True, combos_read=True):
    return {"minimum": minimum, "game_changers": [{"name": n} for n in gc],
            "mass_land_denial": [{"name": n} for n in mld] if tags else None,
            "extra_turns": [{"name": n} for n in turns] if tags else None,
            "combos": {"checked": combos_read, "matches": [{"names": list(names), "floor": floor}
                                                          for names, floor in combos]} if combos_read
            else {"checked": False, "reason": "No list"},
            "unknown_cards": list(unknown)}


def entry(deck_id, title, minimum=1, status="built", **extra):
    found = {"id": deck_id, "title": title, "status": status, "version": "target", "trial": None,
             "target_bracket": 2, "bracket": bracket(minimum) if minimum is not None else None, "unknown": None,
             "last_played": None, "played_known": True}
    found.update(extra)
    return found


def ids(answer, group):
    return [row["id"] for row in answer["groups"][group]]


class LineupTests(unittest.TestCase):
    def test_decks_sort_into_fits_above_and_unknown_against_the_aim(self):
        answer = lineup([entry("commander/a", "Alpha", 2),
                         entry("commander/b", "Beta", 3, bracket=bracket(3, gc=["Sol Ring", "Mana Crypt"])),
                         entry("commander/c", "Gamma", None)], NIGHT, TODAY)
        self.assertEqual(answer["limit"], 2)
        self.assertEqual(answer["basis"], "The household aims for Bracket 2 at this night.")
        self.assertEqual((ids(answer, "fits"), ids(answer, "above"), ids(answer, "unknown")),
                         (["commander/a"], ["commander/b"], ["commander/c"]))
        self.assertEqual(answer["counts"], {"fits": 1, "above": 1, "unknown": 1})
        above = answer["groups"]["above"][0]
        self.assertEqual(above["minimum"], 3)
        self.assertEqual(above["deciding"], [{"reason": "2 Game Changers (none in Brackets 1-2)",
                                              "cards": ["Mana Crypt", "Sol Ring"]}])
        self.assertEqual(answer["groups"]["unknown"][0]["unknown_reason"], lineup_module.NO_BRACKET)
        self.assertEqual(answer["night"]["name"], "Fixture night")

    def test_the_limit_is_the_lower_of_the_aim_and_the_published_top_else_whichever_is_recorded(self):
        for night, limit in (({"target_bracket": 3, "published_min": 1, "published_max": 2}, 2),
                             ({"target_bracket": 2, "published_min": 1, "published_max": 4}, 2),
                             ({"target_bracket": None, "published_min": 2, "published_max": 3}, 3),
                             ({"target_bracket": 4, "published_min": None, "published_max": None}, 4)):
            with self.subTest(night=night):
                answer = lineup([entry("commander/a", "Alpha", 3)], {"name": "N", **night}, TODAY)
                self.assertEqual(answer["limit"], limit)
                self.assertEqual(ids(answer, "fits" if 3 <= limit else "above"), ["commander/a"])
        self.assertIn("below the household's Bracket 3 aim",
                      lineup([], {"name": "N", "target_bracket": 3, "published_min": 1, "published_max": 2}, TODAY)["basis"])

    def test_no_night_or_a_night_without_an_aim_or_range_leaves_every_deck_unknown(self):
        for night, reason in ((None, lineup_module.NO_NIGHT),
                              ({"name": "N", "target_bracket": None, "published_min": None, "published_max": None},
                               lineup_module.NO_AIM)):
            with self.subTest(night=night):
                answer = lineup([entry("commander/a", "Alpha", 1)], night, TODAY)
                self.assertEqual((answer["limit"], ids(answer, "fits"), ids(answer, "unknown")),
                                 (None, [], ["commander/a"]))
                self.assertEqual(answer["groups"]["unknown"][0]["unknown_reason"], reason)
                self.assertEqual(answer["basis"], reason)
        answer = lineup([entry("commander/a", "Alpha", 1)], NIGHT, TODAY, night_unavailable="The night can't be read.")
        self.assertEqual((answer["night"], answer["basis"], ids(answer, "unknown")),
                         (None, "The night can't be read.", ["commander/a"]))

    def test_unread_card_data_tags_or_combos_are_unknown_never_fitting(self):
        cases = (("unknown cards", bracket(1, unknown=["Notacard"]), "1 card name isn't in the card data"),
                 ("tags", bracket(1, tags=False), lineup_module.NO_TAGS),
                 ("combos", bracket(1, combos_read=False), lineup_module.NO_COMBOS))
        for name, found, words in cases:
            with self.subTest(name):
                answer = lineup([entry("commander/a", "Alpha", bracket=found)], NIGHT, TODAY)
                self.assertEqual(ids(answer, "unknown"), ["commander/a"])
                row = answer["groups"]["unknown"][0]
                self.assertIn(words, row["unknown_reason"])
                self.assertEqual((row["minimum"], row["minimum_so_far"]), (None, 1))
        many = bracket(1, unknown=[f"Card {n}" for n in range(7)])
        row = lineup([entry("commander/a", "Alpha", bracket=many)], NIGHT, TODAY)["groups"]["unknown"][0]
        self.assertIn("7 card names aren't in the card data", row["unknown_reason"])
        self.assertTrue(row["unknown_reason"].endswith("Card 4…."))

    def test_a_deck_whose_checks_did_not_finish_is_unknown(self):
        answer = lineup([entry("commander/a", "Alpha", None, unknown="Its checks didn't finish in time.")], NIGHT, TODAY)
        self.assertEqual(ids(answer, "unknown"), ["commander/a"])
        self.assertEqual(answer["groups"]["unknown"][0]["unknown_reason"], "Its checks didn't finish in time.")
        # The reason wins even beside a worked-out bracket.
        answer = lineup([entry("commander/a", "Alpha", 1, unknown="Timed out.")], NIGHT, TODAY)
        self.assertEqual(ids(answer, "unknown"), ["commander/a"])

    def test_trials_retired_decks_and_other_kinds_take_no_part(self):
        answer = lineup([entry("commander/a", "Alpha", 1, trial="SomePrecon_ABC"),
                         entry("commander/b", "Beta", 1, retired=True),
                         entry("casual/c", "Gamma", 1, kind="casual"),
                         {"title": "No id"}, "junk",
                         entry("commander/d", "Delta", 1)], NIGHT, TODAY)
        self.assertEqual(ids(answer, "fits"), ["commander/d"])
        self.assertEqual(sum(answer["counts"].values()), 1)

    def test_the_cards_that_decide_the_minimum_are_named_against_the_limit(self):
        found = bracket(4, gc=["A", "B", "C", "D"], mld=["Armageddon"], turns=["Time Warp"],
                        combos=((("X", "Y"), 3), (("Land", "Breaker"), 4)))
        decide = lambda limit: {g["reason"]: g["cards"] for g in lineup_module.deciding(found, limit)}
        self.assertEqual(decide(1), {
            "Extra turns (none in Bracket 1)": ["Time Warp"],
            "4 Game Changers (none in Brackets 1-2)": ["A", "B", "C", "D"],
            "Two-card combos that go infinite or end the game (none in Brackets 1-2)": ["X + Y"],
            "Mass land denial (not allowed in Brackets 1-3)": ["Armageddon"],
            "Two-card combos that destroy lands (not allowed in Brackets 1-3)": ["Land + Breaker"]})
        self.assertEqual(list(decide(3)), ["4 Game Changers (Bracket 3 allows up to 3)",
                                           "Mass land denial (not allowed in Brackets 1-3)",
                                           "Two-card combos that destroy lands (not allowed in Brackets 1-3)"])
        three = bracket(3, gc=["A", "B", "C"])
        self.assertEqual(lineup_module.deciding(three, 3), [])
        self.assertEqual(decide(4), {})
        row = lineup([entry("commander/a", "Alpha", bracket=found)], NIGHT, TODAY)["groups"]["above"][0]
        self.assertEqual(len(row["deciding"]), 4)       # extra turns fit the Bracket 2 aim

    def test_rows_order_built_first_closest_to_the_limit_and_carry_their_facts(self):
        answer = lineup([entry("commander/z", "Zeta", 1, status="idea", last_played="2026-11-02"),
                         entry("commander/y", "Yew", 1),
                         entry("commander/x", "Xi", 2, stand_ins=[{"for": "Sol Ring", "using": None, "qty": 1}],
                               box_checked_on="2026-11-01", last_played=TODAY),
                         entry("commander/w", "Wren", 4, bracket=bracket(4, mld=["Armageddon"])),
                         entry("commander/v", "Vale", 3, bracket=bracket(3, gc=["Sol Ring"])),
                         entry("commander/u", "Umber", None, status="idea"),
                         entry("commander/t", "Tarn", None)], NIGHT, TODAY)
        self.assertEqual(ids(answer, "fits"), ["commander/x", "commander/y", "commander/z"])
        self.assertEqual(ids(answer, "above"), ["commander/v", "commander/w"])
        self.assertEqual(ids(answer, "unknown"), ["commander/t", "commander/u"])
        x, y, z = answer["groups"]["fits"]
        self.assertEqual((x["built"], x["stand_ins"], x["box_checked_on"], x["days_since_played"]),
                         (True, [{"for": "Sol Ring", "using": None, "qty": 1}], "2026-11-01", 0))
        self.assertEqual((z["built"], z["days_since_played"], z["last_played"]), (False, 10, "2026-11-02"))
        # A viewer who may not see them gets no stand-ins or box date keys at all.
        self.assertNotIn("stand_ins", y)
        self.assertNotIn("box_checked_on", y)

    def test_a_minimum_under_the_published_range_still_fits_with_a_note(self):
        night = {**NIGHT, "target_bracket": 3, "published_min": 2, "published_max": 4}
        answer = lineup([entry("commander/a", "Alpha", 1), entry("commander/b", "Beta", 2)], night, TODAY)
        self.assertEqual(ids(answer, "fits"), ["commander/b", "commander/a"])
        self.assertEqual([row["below_range"] for row in answer["groups"]["fits"]], [False, True])

    def test_a_game_log_that_can_t_be_read_claims_no_date(self):
        row = lineup([entry("commander/a", "Alpha", 1, played_known=False)], NIGHT, TODAY)["groups"]["fits"][0]
        self.assertEqual((row["played_known"], row["last_played"]), (False, None))


if __name__ == "__main__":
    unittest.main()
