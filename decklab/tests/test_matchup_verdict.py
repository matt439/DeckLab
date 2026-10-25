"""Matchup lead wording, using real result maths and a small Node DOM stand-in.

The verdicts (2026-10-03, the simulation report's R03): ahead, about even (the range within 5
points of an even split), both ("slightly ahead"), or not settled; worded the same on the page
and on the command line (views.VERDICT_WORDS).

No Forge, simulation workers, server, network or saved-result writes.
"""
import json
import unittest

from decklab.lib.forge.views import _comparison, _lead, _winrate, verdict_words
from decklab.tests.test_web import NODE, _run_page


def games_of(on_play, on_draw, nonwins=0):
    """Games where side 0 wins on_play[0] of on_play[1] going first and on_draw[0] of on_draw[1]
    going second (side 1 wins the rest), plus nonwins games with no winner in each."""
    games = []
    for first, (wins, n) in ((0, on_play), (1, on_draw)):
        games += [{"w": 0, "first": first}] * wins + [{"w": 1, "first": first}] * (n - wins)
        games += [{"w": None, "first": first}] * nonwins
    return games


def result_of(games, side=0, muted=False):
    winrate, comparison = _winrate(games, side)["winrate"], _comparison(games, side)
    return {"winrate": winrate, "comparison": comparison, "lead": _lead(games, side, winrate, comparison),
            "not_meaningful": muted}


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupVerdictTests(unittest.TestCase):

    def words(self, games, side=0, muted=False):
        titles = ("A", "B") if side == 0 else ("B", "A")
        return _run_page([f"matchupVerdict({json.dumps(result_of(games, side, muted))}, {json.dumps(titles[0])}, "
                          f"{json.dumps(titles[1])})"])[0]

    def test_nonwins_do_not_reverse_the_lead_in_either_perspective(self):
        games = games_of((180, 300), (180, 300), nonwins=100)
        a, b = self.words(games), self.words(games, side=1)
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("A is ahead in these AI games:"), a)
        self.assertNotIn("50%", a)

    def test_small_stopped_runs_and_no_winners_are_not_settled(self):
        for games in ([{"w": 0, "first": 0}, {"w": 0, "first": 1}],
                      [{"w": None, "first": 0}] * 100 + [{"w": None, "first": 1}] * 100):
            for side in (0, 1):
                with self.subTest(side=side, games=len(games)):
                    self.assertTrue(self.words(games, side).startswith("Not settled yet:"))

    def test_an_even_matchup_with_enough_games_is_about_even(self):
        # 1,600 games at 50%: the range is about 47.6% to 52.4%, inside 45% to 55%.
        games = games_of((400, 800), (400, 800))
        for side in (0, 1):
            with self.subTest(side=side):
                self.assertTrue(self.words(games, side).startswith("About even in these AI games:"))

    def test_a_small_lead_that_is_also_about_even_is_slightly_ahead(self):
        # 3,200 games at 52.5%: the range (about 50.8% to 54.2%) leaves out 50% and stays under 55%.
        games = games_of((840, 1600), (840, 1600))
        self.assertTrue(self.words(games).startswith("A is slightly ahead (by under 5 points) in these AI games:"))
        self.assertTrue(self.words(games, side=1).startswith("A is slightly ahead (by under 5 points)"))

    def test_the_page_and_the_command_line_say_the_same(self):
        cases = {"ahead": games_of((180, 300), (180, 300), nonwins=100),
                 "slightly_ahead": games_of((840, 1600), (840, 1600)),
                 "about_even": games_of((400, 800), (400, 800)),
                 "not_settled": games_of((1, 2), (1, 2))}
        calls, expected = [], []
        for verdict, games in cases.items():
            for side in (0, 1):
                result = result_of(games, side)
                self.assertEqual(result["lead"]["verdict"], verdict)
                titles = ["A", "B"] if side == 0 else ["B", "A"]
                calls.append(f"matchupVerdict({json.dumps(result)}, {json.dumps(titles[0])}, {json.dumps(titles[1])})")
                expected.append(verdict_words(result["lead"], titles))
        self.assertEqual(_run_page(calls), expected)

    def test_empty_and_unmeaningful_results_do_not_get_a_lead(self):
        self.assertEqual(self.words([]), "No comparison is available yet.")
        self.assertEqual(self.words([], muted=True), "It doesn't say which deck is ahead: see the box above.")
        self.assertEqual(_run_page(["matchupVerdict({}, 'A', 'B')"]), ["No comparison is available yet."])

    def test_reference_mark_does_not_claim_fifty_percent_is_even(self):
        key = _run_page(["rangeKey()"])[0]
        self.assertIn("50% win rate", key)
        self.assertNotIn("even matchup", key)


if __name__ == "__main__":
    unittest.main()
