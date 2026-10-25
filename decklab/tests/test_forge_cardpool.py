"""Tests for how the per-card win-rate differences are judged (recommendation R11 of the
2026-10-03 simulation report, items 1-3): a list's matchups pooled matchup by matchup
(Mantel-Haenszel, with saved._pooled_cards' strata), each difference pulled toward 0
(normal-normal empirical Bayes, cardstats._spread and _shrunk), "won more/less" only for
Benjamini-Hochberg discoveries among the cards compared (_discoveries), numbers called
early below MIN_CARD_GAMES = 800 games, and the page's words for each (under Node.js,
as test_web's PageScriptTests).

The results are made by hand as in test_forge_cardstats (its CardStatsCase and record(),
version 2 records: their rows are judged on when a card was drawn, and the page says such
a verdict leans with game length; test_forge_cardlog3 has version 3's), so no Forge runs.
The expected numbers were worked out apart from the code, in the comments beside them;
Newcombe's range itself is checked against his paper there.

Run from the repo root: python -m unittest decklab.tests.test_forge_cardpool
"""
import json
import math
import unittest

from decklab.lib import forge
from decklab.tests import test_forge
from decklab.tests.test_forge import entry, sections
from decklab.tests.test_forge_cardstats import LIST, CardStatsCase, record
from decklab.tests.test_web import NODE, _run_page

cardstats = forge.cardstats


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def bears(drawn, drawn_wins):
    """A batch's tallies of Grizzly Bears, drawn in drawn games (one copy each, all cast)."""
    return {"Grizzly Bears": [drawn, drawn_wins, drawn, drawn, 0, 2 * drawn, 0, 0]}


def matchup(case, wins, drawn, drawn_wins, key):
    """A result of LIST (side 0) with one batch of 100 counted games, side 0 winning wins of
    them, Grizzly Bears drawn in drawn of them and winning drawn_wins."""
    rec = record(games=100, wins=(wins, 100 - wins), first=(50, 50), bad=0, rows=(bears(drawn, drawn_wins), {}))
    return case.result(rec, played=100, key=key)


def named(stats, name):
    return next(row for row in stats["rows"] + stats["commander"] if row["name"] == name)


def hand_pooled(rows, games=1000, wins=500):
    """Pooled tallies made by hand (no strata: the totals are the one stratum), for card_rows."""
    return {"games": games, "bad": 0, "old": 0, "wins": wins, "first": games // 2, "batches": 1,
            "rows": {name: [g, w, g, g, 0, 2 * g, 0, 0] for name, (g, w) in rows.items()}, "commander": {}}


def listed(names):
    """A list of 1-ofs the card data doesn't know (so each is judged as a nonland)."""
    return {"Commander": [], "Main": [[1, name] for name in names]}


# ============================================================ pooling matchup by matchup

class StrataTests(CardStatsCase):

    def test_each_result_is_a_stratum(self):
        # Two batches of one result add up in one stratum, a second result is a stratum of its own, and
        # the totals are as before.
        first = self.result(record(), record(games=20, wins=(10, 10), first=(10, 10), bad=0,
                                             rows=(bears(10, 5), {})))
        pooled = forge.saved._pooled_cards(first, 0)
        # Version 2 records: no games of version 3, so nothing in hand by turn 3 (the last two numbers).
        self.assertEqual(pooled["strata"], {"c" * 64: {"games": 120, "wins": 70, "early_of_games": 0,
                                                       "early_of_wins": 0,
                                                       "rows": {"Grizzly Bears": [80, 55, 0, 0],
                                                                "Lightning Bolt": [40, 10, 0, 0],
                                                                "Giant Growth": [50, 30, 0, 0],
                                                                "Murderous Rider": [10, 4, 0, 0],
                                                                "Forest": [100, 60, 0, 0]},
                                                       "commander": {}}})
        second = matchup(self, 50, 30, 15, "d")
        forge.saved._pooled_cards(second, 0, pooled)
        self.assertEqual(list(pooled["strata"]), ["c" * 64, "d" * 64])
        self.assertEqual(pooled["strata"]["d" * 64]["rows"], {"Grizzly Bears": [30, 15, 0, 0]})
        self.assertEqual((pooled["games"], pooled["wins"], pooled["rows"]["Grizzly Bears"][:2]), (220, 120, [110, 70]))
        # Batches without a record, or with an older or malformed one, aren't in any stratum.
        old = self.result(None, dict(record(), v=1), record(games=500), key="e")
        self.assertEqual(forge.saved._pooled_cards(old, 0)["strata"], {})
        # A mirror's two sides are one stratum (the same opponent result).
        mirror = self.result(record(rows=(bears(70, 50), bears(30, 10))))
        acc = forge.saved._pooled_cards(mirror, 1, forge.saved._pooled_cards(mirror, 0))
        self.assertEqual(acc["strata"], {"c" * 64: {"games": 200, "wins": 100, "early_of_games": 0,
                                                    "early_of_wins": 0, "rows": {"Grizzly Bears": [100, 60, 0, 0]},
                                                    "commander": {}}})
        # An accumulator from before the strata (made by hand) gets them.
        hand = {"games": 0, "bad": 0, "old": 0, "wins": 0, "first": 0, "batches": 0, "rows": {}, "commander": {}}
        self.assertEqual(list(forge.saved._pooled_cards(first, 0, hand)["strata"]), ["c" * 64])

    def test_a_card_drawn_more_in_an_easy_matchup_isnt_given_its_wins(self):
        # Simpson's paradox. The list wins 80 of 100 against an easy opponent and draws Grizzly Bears in 80
        # of them, and 20 of 100 against a hard one, drawing it in 20; in each matchup it wins as often with
        # the card as without (64/80 v 16/20, 4/20 v 16/80). Pooled naively, it "won" 68% when drawn and 32%
        # when not (+36 points, which the deck page called "won more when drawn"); matchup by matchup it's 0.
        easy, hard = matchup(self, 80, 80, 64, "c"), matchup(self, 20, 20, 4, "d")
        stats = forge.list_cards(sections(LIST), "constructed", [easy, hard])
        row = named(stats, "Grizzly Bears")
        self.assertEqual((row["wr_drawn"]["value"], row["wr_not"]["value"]), (0.68, 0.32))     # the raw rates stay
        self.assertEqual(row["diff"]["value"], 0.0)
        self.assertEqual((row["judged"], row["verdict"], row["shrunk"]), (True, "unclear", 0.0))
        self.assertGreater(row["p"], 0.99)
        # Equal weights (80 * 20 / 100 = 16 each), so the range is MOVER's from each one's Newcombe range:
        # half the root of the sum of their squared half-widths.
        a, b = cardstats.newcombe(64, 80, 16, 20), cardstats.newcombe(4, 20, 16, 80)
        low = -0.5 * math.hypot(a[0] - a[1], b[0] - b[1])
        high = 0.5 * math.hypot(a[2] - a[0], b[2] - b[0])
        self.assertEqual((row["diff"]["low"], row["diff"]["high"]), (round(low, 4), round(high, 4)))
        # Each matchup alone says the same as its stratum.
        for result in (easy, hard):
            self.assertEqual(forge.side_cards(result, 0)["rows"][2]["diff"]["value"], 0.0)

    def test_results_without_a_key_are_strata_of_their_own(self):
        # Saved results always have a key; two made by hand without one are still two strata (by identity),
        # not pooled naively into one: the easy and hard matchups again come out at 0, not +36 points.
        easy, hard = matchup(self, 80, 80, 64, "c"), matchup(self, 20, 20, 4, "d")
        del easy["key"], hard["key"]
        pooled = forge.saved._pooled_cards(hard, 0, forge.saved._pooled_cards(easy, 0))
        self.assertEqual(sorted(s["games"] for s in pooled["strata"].values()), [100, 100])
        self.assertNotIn(None, pooled["strata"])
        stats = forge.list_cards(sections(LIST), "constructed", [easy, hard])
        self.assertEqual(named(stats, "Grizzly Bears")["diff"]["value"], 0.0)
        # A mirror without a key: both sides of the one result are still one stratum.
        mirror = self.result(record(rows=(bears(70, 50), bears(30, 10))))
        del mirror["key"]
        acc = forge.saved._pooled_cards(mirror, 1, forge.saved._pooled_cards(mirror, 0))
        self.assertEqual(list(acc["strata"].values()), [{"games": 200, "wins": 100, "early_of_games": 0,
                                                         "early_of_wins": 0, "rows": {"Grizzly Bears": [100, 60, 0, 0]},
                                                         "commander": {}}])

    def test_a_card_that_helps_in_every_matchup_isnt_hidden_by_pooling(self):
        # The other way round: +25 points within each matchup (18/20 v 52/80 against the easy opponent,
        # 28/80 v 2/20 against the hard one), but drawn mostly in the hard one, so pooled it's 46% v 54%.
        # Matchup by matchup it's +25: (16 * 0.25 + 16 * 0.25) / 32.
        stats = forge.list_cards(sections(LIST), "constructed",
                                 [matchup(self, 70, 20, 18, "c"), matchup(self, 30, 80, 28, "d")])
        row = named(stats, "Grizzly Bears")
        self.assertEqual((row["wr_drawn"]["value"], row["wr_not"]["value"]), (0.46, 0.54))
        self.assertEqual(row["diff"]["value"], 0.25)
        self.assertGreater(row["diff"]["low"], 0)
        self.assertEqual((row["discovery"], row["verdict"]), (True, "more"))
        # Its se: each stratum's from (x + 0.5) / (n + 1), weighted by 1/2 each.
        def variance(x1, n1, x0, n0):
            p1, p0 = (x1 + 0.5) / (n1 + 1), (x0 + 0.5) / (n0 + 1)
            return p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0
        se = 0.5 * math.sqrt(variance(18, 20, 52, 80) + variance(28, 80, 2, 20))
        self.assertEqual(row["p"], round(2 * (1 - 0.5 * (1 + math.erf(0.25 / se / math.sqrt(2)))), 4))

    def test_unequal_weights(self):
        # Weights n1 * n0 / n: 50 * 50 / 100 = 25 (+10 points: 30/50 v 25/50) and 10 * 90 / 100 = 9 (-10 points:
        # 4/10 v 45/90), so the difference is (25 * 0.1 - 9 * 0.1) / 34 = 0.047059.
        stats = forge.list_cards(sections(LIST), "constructed",
                                 [matchup(self, 55, 50, 30, "c"), matchup(self, 49, 10, 4, "d")])
        row = named(stats, "Grizzly Bears")
        self.assertEqual(row["diff"]["value"], 0.0471)
        d = 1.6 / 34
        a, b = cardstats.newcombe(30, 50, 25, 50), cardstats.newcombe(4, 10, 45, 90)
        ca, cb = 25 / 34, 9 / 34
        self.assertEqual(row["diff"]["low"], round(d - math.hypot(ca * (a[0] - a[1]), cb * (b[0] - b[1])), 4))
        self.assertEqual(row["diff"]["high"], round(d + math.hypot(ca * (a[2] - a[0]), cb * (b[2] - b[0])), 4))

    def test_a_matchup_with_nothing_to_compare_has_no_weight(self):
        # Drawn in every game of one matchup (no game without it there): only the other compares, so the
        # difference is that one's, Newcombe's range and all, while the rates count every game.
        every, some = matchup(self, 60, 100, 60, "c"), matchup(self, 50, 50, 30, "d")
        stats = forge.list_cards(sections(LIST), "constructed", [every, some])
        row = named(stats, "Grizzly Bears")
        alone = forge.side_cards(some, 0)["rows"][2]
        self.assertEqual(row["diff"], alone["diff"])
        self.assertEqual((row["wr_drawn"]["games"], row["wr_not"]["games"]), (150, 50))
        # Never drawn anywhere: no difference at all.
        stats = forge.list_cards(sections(LIST), "constructed", [matchup(self, 60, 100, 60, "c")])
        self.assertIsNone(named(stats, "Grizzly Bears")["wr_not"])
        self.assertEqual((named(stats, "Grizzly Bears")["diff"], named(stats, "Grizzly Bears")["shrunk"]), (None, None))

    def test_one_matchup_is_newcombes_range_as_before(self):
        # One result, or one side's stats: the plain difference with Newcombe's range, unchanged.
        result = self.result(record())
        stats = forge.list_cards(sections(LIST), "constructed", [result])
        self.assertEqual(stats, forge.side_cards(result, 0))
        self.assertEqual(named(stats, "Grizzly Bears")["diff"], {"value": 0.381, "low": 0.1684, "high": 0.5496})
        # Tallies made by hand without strata: their totals are the one stratum.
        pooled = forge.saved._pooled_cards(result, 0)
        hand = {k: v for k, v in pooled.items() if k != "strata"}
        listed_ = forge.saved._side_cards(result["sides"][0])
        self.assertEqual(cardstats.card_rows(listed_, "constructed", hand, 102),
                         cardstats.card_rows(listed_, "constructed", pooled, 102))

    GISA = "Commander\n1 Ghoulcaller Gisa\n\nDeck\n4 Grizzly Bears\n10 Swamp\n"

    def test_a_commander_is_compared_matchup_by_matchup_too(self):
        # The easy and hard matchups again, by casts: 64 of 80 v 16 of 20, then 4 of 20 v 16 of 80.
        gisa = entry(self.GISA, "commander/gisa", kind="commander")
        results = []
        for key, wins, cast, cast_wins in (("c", 80, 80, 64), ("d", 20, 20, 4)):
            rec = record(games=100, wins=(wins, 100 - wins), first=(50, 50), bad=0, rows=({}, {}),
                         commander=({"Ghoulcaller Gisa": [cast, cast_wins, cast, 4 * cast]}, {}))
            results.append(self.result(rec, played=100, cards_a=gisa["cards"], kinds=("commander", "commander"),
                                       key=key, sha=gisa["card_sha"]))
        stats = forge.list_cards(sections(self.GISA), "commander", results)
        row = named(stats, "Ghoulcaller Gisa")
        self.assertEqual((row["wr_cast"]["value"], row["wr_not_cast"]["value"]), (0.68, 0.32))
        self.assertEqual((row["diff"]["value"], row["verdict"]), (0.0, "unclear"))


# ============================================================ shrinking toward 0

class ShrinkTests(unittest.TestCase):

    def test_shrunk(self):
        # value * spread^2 / (spread^2 + se^2): half of it when se is the spread, nearly all with a tiny se,
        # little with a big one, and the sign is kept.
        self.assertAlmostEqual(cardstats._shrunk(0.1, 0.045, 0.045), 0.05)
        self.assertAlmostEqual(cardstats._shrunk(-0.1, 0.045, 0.045), -0.05)
        self.assertAlmostEqual(cardstats._shrunk(0.1, 0.001, 0.045), 0.1 * 0.045 ** 2 / (0.045 ** 2 + 1e-6))
        self.assertLess(abs(cardstats._shrunk(0.3, 0.2, 0.045)), 0.02)
        self.assertEqual(cardstats._shrunk(0.1, 0.05, 0.0), 0.0)
        # At 800 games a card drawn in half of them (se 0.0354) keeps about 62% (r5); at 100 games under 20%.
        se800 = math.sqrt(0.25 / 400 + 0.25 / 400)
        se100 = math.sqrt(0.25 / 50 + 0.25 / 50)
        self.assertEqual(round(cardstats._shrunk(1, se800, cardstats.CARD_SPREAD), 2), 0.62)
        self.assertLess(cardstats._shrunk(1, se100, cardstats.CARD_SPREAD), 0.2)

    def test_the_spread_with_no_cards_or_little_to_go_on_is_r5s(self):
        self.assertEqual(cardstats._spread([]), (0.045, 0.0))
        # One card with se 0.1: a variance of 2 * (0.045^2 + 0.1^2)^2 = 0.000289 against 0.00000103, so a
        # weight of 0.0035, and the spread moves from 0.045 only to 0.048.
        spread, weight = cardstats._spread([(0.3, 0.1)])
        self.assertLess(weight, 0.01)
        self.assertAlmostEqual(spread, 0.048, places=4)

    def test_many_precise_cards_measure_their_own(self):
        # 200 cards with se 0.01 and differences of +-0.03: their own spread is sqrt(0.03^2 - 0.01^2) =
        # 0.028284, with a variance of 2 * 200 * (0.045^2 + 0.01^2)^2 / 200^2 = 4.5156e-8 against SPREAD_DOUBT's
        # (0.5 * 0.045^2)^2 = 1.0252e-6, so a weight of 0.9578 and a spread of sqrt(0.002025 + 0.9578 *
        # (0.0008 - 0.002025)) = 0.029184.
        found = [(0.03 if i % 2 else -0.03, 0.01) for i in range(200)]
        spread, weight = cardstats._spread(found)
        self.assertAlmostEqual(weight, 0.9578, places=4)
        self.assertAlmostEqual(spread, 0.029184, places=5)

    def test_half_its_own_at_21_cards_and_800_games(self):
        # As _spread's docstring says: about 21 cards at 800 games, 14 at 1,600, 40 at 400 (a card drawn in
        # half the games of an even matchup).
        for games, cards in ((800, 21), (1600, 14), (400, 40)):
            se = math.sqrt(0.25 / (games / 2) * 2)
            with self.subTest(games=games):
                self.assertAlmostEqual(cardstats._spread([(0.0, se)] * cards)[1], 0.5, delta=0.02)

    def test_the_spread_is_never_below_0(self):
        # 1,000 precise cards that all show nothing: their own square is -se^2, weighted 0.99, so the mix
        # is below 0 and the spread is 0 (and every difference is pulled all the way).
        spread, weight = cardstats._spread([(0.0, 0.01)] * 1000)
        self.assertEqual(spread, 0.0)
        self.assertGreater(weight, 0.99)

    def test_a_commander_doesnt_count_toward_the_spread(self):
        # A commander's cast-or-not difference is mostly how the game went: a big one would make every
        # spell's difference look more believable. The spells alone set the spread.
        spells = {f"Card {i}": (500, 250) for i in range(20)}
        names = list(spells)
        plain = cardstats.card_rows(listed(names), "constructed", hand_pooled(spells), 1000)
        with_commander = dict(hand_pooled(spells), commander={"Card C": [500, 450, 600, 2000]})
        commander_list = {"Commander": [[1, "Card C"]], "Main": [[1, n] for n in names]}
        stats = cardstats.card_rows(commander_list, "commander", with_commander, 1000)
        self.assertEqual((stats["spread"], stats["spread_weight"]), (plain["spread"], plain["spread_weight"]))
        self.assertEqual((stats["compared"], plain["compared"]), (21, 20))
        self.assertEqual(named(stats, "Card C")["verdict"], "more")


# ============================================================ verdicts: Benjamini-Hochberg

class DiscoveryTests(unittest.TestCase):

    def test_the_papers_example(self):
        # Benjamini and Hochberg (1995), section 4: 15 p-values, of which 4 are discoveries at a false
        # discovery rate of 0.05 (Bonferroni finds 3); at 0.1, the first 9 (0.0459 <= 0.1 * 9 / 15).
        ps = [0.0201, 0.7590, 0.0001, 0.0004, 0.0019, 0.0095, 0.0278, 0.0298, 0.0344, 0.0459, 0.3240, 0.4262,
              0.5719, 0.6528, 1.0]
        self.assertEqual(cardstats._discoveries(ps, 0.05), {2, 3, 4, 5})
        self.assertEqual(cardstats._discoveries(ps), {0, 2, 3, 4, 5, 6, 7, 8, 9})
        self.assertEqual(cardstats._discoveries([]), set())
        # Step-up: 0.06 is over rank 1's bar (0.1 * 1 / 2 = 0.05), but 0.07 is under rank 2's (0.1), and that
        # takes every p-value below it too.
        self.assertEqual(cardstats._discoveries([0.06, 0.07]), {0, 1})
        self.assertEqual(cardstats._discoveries([0.06, 0.2]), set())
        # Ties are both in or both out.
        self.assertEqual(cardstats._discoveries([0.01, 0.01, 0.9]), {0, 1})

    def test_a_range_clear_of_0_can_be_chance_among_many_cards(self):
        # Card 0 won 267 of the 500 games it was drawn in and 233 of the 500 without it: +6.8 points, a
        # range just clear of 0 (the old verdict "won more"), p = 0.0311. Alone it's a discovery
        # (0.0311 <= 0.1); among 19 cards that did nothing (250 of 500 each way) it isn't (0.0311 > 0.1 / 20),
        # so it's "unclear", and the page says why.
        spells = {"Card 0": (500, 267), **{f"Card {i}": (500, 250) for i in range(1, 20)}}
        stats = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        row = named(stats, "Card 0")
        self.assertGreater(row["diff"]["low"], 0)
        self.assertEqual(row["p"], 0.0311)
        self.assertEqual((row["judged"], row["discovery"], row["verdict"]), (True, False, "unclear"))
        self.assertEqual(stats["compared"], 20)
        self.assertEqual(stats["fdr"], 0.1)
        alone = cardstats.card_rows(listed(["Card 0"]), "constructed", hand_pooled({"Card 0": (500, 267)}), 1000)
        self.assertEqual((named(alone, "Card 0")["discovery"], named(alone, "Card 0")["verdict"]), (True, "more"))

    def test_a_discovery_whose_range_takes_in_0_has_no_verdict(self):
        # Ten cards that clearly did something (300 of 500 drawn, 200 of 500 not) lift Benjamini-Hochberg's
        # bar for the eleventh to 0.1 * 11 / 11: Card X (264 v 236, p 0.077) is a discovery, but its 95% range
        # takes in 0, so it gets no verdict: the page never says "won more" beside a range through 0.
        spells = {**{f"Card {i}": (500, 300) for i in range(10)}, "Card X": (500, 264)}
        stats = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        row = named(stats, "Card X")
        self.assertLess(row["diff"]["low"], 0)
        self.assertEqual((row["discovery"], row["verdict"]), (True, "unclear"))
        self.assertEqual(named(stats, "Card 0")["verdict"], "more")

    def test_lands_and_unjudged_cards_arent_compared(self):
        # Forest (a land) and a card drawn in 20 games (under MIN_SPLIT_GAMES) aren't in the family:
        # Card 0 (p 0.0311) is a discovery among the two judged cards (0.0311 <= 0.1 * 1 / 2).
        spells = {"Card 0": (500, 267), "Card 1": (500, 250), "Forest": (500, 300), "Card 2": (20, 15)}
        stats = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        self.assertEqual(stats["compared"], 2)
        self.assertEqual(named(stats, "Card 0")["verdict"], "more")
        forest, few = named(stats, "Forest"), named(stats, "Card 2")
        self.assertEqual((forest["land"], forest["judged"], forest["discovery"], forest["shrunk"], forest["p"]),
                         (True, False, None, None, None))
        self.assertIsNotNone(forest["diff"])        # its rates and difference are still there
        self.assertEqual((few["judged"], few["discovery"], few["verdict"]), (False, None, None))
        self.assertIsNotNone(few["shrunk"])
        json.dumps(stats, allow_nan=False)


# ============================================================ early numbers

class EarlyTests(unittest.TestCase):

    def test_early_below_800_games(self):
        # At 800 games a card drawn in half of them has a range of about +-7 points (+-6.9), and a 1-of
        # (drawn in about 23%) +-8.2; at 100 games +-20 or more. Numbers from fewer games are still shown.
        self.assertEqual(cardstats.MIN_CARD_GAMES, 800)
        for games, enough in ((799, False), (800, True), (100, False)):
            stats = cardstats.card_rows(listed(["Card 0"]), "constructed",
                                        hand_pooled({"Card 0": (games // 2, games // 4)}, games, games // 2), games)
            with self.subTest(games=games):
                self.assertEqual((stats["enough"], stats["min_games"]), (enough, 800))
                self.assertIsNotNone(stats["rows"][0]["diff"])
        half = 1.96 * 0.5 * math.sqrt(1 / 400 + 1 / 400)
        one_of = 1.96 * 0.5 * math.sqrt(1 / (0.23 * 800) + 1 / (0.77 * 800))
        self.assertEqual((round(100 * half, 1), round(100 * one_of, 1)), (6.9, 8.2))


# ============================================================ the page's words

@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageWordsTests(CardStatsCase):

    @staticmethod
    def call(row, stats):
        return f"winSplitWords({json.dumps(row)}, {json.dumps(stats)}, 'drawn', {json.dumps(row['wr_drawn'])}, " \
               f"{json.dumps(row['wr_not'])}, {row['drawn_games']})"

    def test_one_matchup_shows_its_best_estimate(self):
        # Version 2 records (games kept before in hand by turn 3 was counted): a "won more" says it leans with
        # game length.
        stats = forge.side_cards(self.result(record()), 0)
        self.assertEqual(_run_page([self.call(named(stats, "Grizzly Bears"), stats),
                                    self.call(named(stats, "Giant Growth"), stats)]),
                         ["Won 71.4% when drawn, 33.3% when not: +38.1 points (+17 to +55), best estimate +10.3. "
                          "Won more when drawn (leans with game length).",
                          "Won 60.0% when drawn, 60.0% when not: 0.0 points (−19 to +19), best estimate 0.0. "
                          "No clear difference."])

    def test_several_matchups_show_the_difference_matchup_by_matchup(self):
        stats = forge.list_cards(sections(LIST), "constructed",
                                 [matchup(self, 80, 80, 64, "c"), matchup(self, 20, 20, 4, "d")])
        words = _run_page([self.call(named(stats, "Grizzly Bears"), stats)])[0]
        self.assertTrue(words.startswith("Won 68.0% when drawn, 32.0% when not; matchup by matchup, 0.0 points (−"),
                        words)
        self.assertTrue(words.endswith(", best estimate 0.0. No clear difference."), words)
        self.assertNotIn("36", words)

    def test_a_range_clear_of_0_by_chance_says_so(self):
        spells = {"Card 0": (500, 267), **{f"Card {i}": (500, 250) for i in range(1, 20)}}
        stats = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        words = _run_page([self.call(named(stats, "Card 0"), stats)])[0]
        self.assertEqual(words, "Won 53.4% when drawn, 46.6% when not: +6.8 points (+1 to +13), best estimate "
                                f"+{100 * named(stats, 'Card 0')['shrunk']:.1f}. No clear difference: among 20 cards "
                                "compared, a range this far from 0 can turn up by chance.")

    def test_one_card_compared_isnt_said_to_be_within_chance(self):
        # Its p-value comes from a plain (Wald) se and its range from Newcombe's, so a lone card compared
        # can have a range clear of 0 and still not be a discovery. "Among 1 card compared ... by chance"
        # says nothing, so it's plain "No clear difference."
        stats = cardstats.card_rows(listed(["Card 0"]), "constructed", hand_pooled({"Card 0": (500, 267)}), 1000)
        row = dict(named(stats, "Card 0"), discovery=False, verdict="unclear")      # as such a card comes out
        self.assertEqual(stats["compared"], 1)
        self.assertGreater(row["diff"]["low"], 0)
        words = _run_page([self.call(row, stats)])[0]
        self.assertTrue(words.endswith(". No clear difference."), words)
        stub = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "
        lone = dict(stats, rows=[row])
        lead = _run_page([f"{stub}standOutParts({json.dumps(lone)})"])[0]
        self.assertIn("none of the 1 card with the games to tell won clearly more or less often when drawn.", lead)
        self.assertNotIn("chance", lead)

    def test_the_deck_pages_lead(self):
        stub = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "
        # A discovery over several matchups: the difference worked out matchup by matchup, as its row says.
        stats = forge.list_cards(sections(LIST), "constructed",
                                 [matchup(self, 70, 20, 18, "c"), matchup(self, 30, 80, 28, "d")])
        lead = _run_page([f"{stub}standOutParts({json.dumps(stats)})"])[0]
        self.assertIn("with the 95% range, worked out matchup by matchup. These games were kept before in hand by "
                      "turn 3 was counted: long games draw more cards", lead)     # one card compared
        self.assertIn("Grizzly Bears+25.0 points (+", lead)
        self.assertNotIn("−8.0 points", lead)          # not the gap between the pooled rates (46% v 54%)
        # One matchup and 20 cards compared, one of which stands out.
        spells = {"Card 0": (500, 300), **{f"Card {i}": (500, 250) for i in range(1, 20)}}
        clear = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        lead = _run_page([f"{stub}standOutParts({json.dumps(clear)})"])[0]
        self.assertIn("with the 95% range; only those that stand out among the 20 cards compared are listed. These ",
                      lead)
        self.assertIn("Card 0+20.0 points (+14 to +26)", lead)
        # None stands out, one by chance: said with the count.
        spells = {"Card 0": (500, 267), **{f"Card {i}": (500, 250) for i in range(1, 20)}}
        chance = cardstats.card_rows(listed(list(spells)), "constructed", hand_pooled(spells), 1000)
        lead = _run_page([f"{stub}standOutParts({json.dumps(chance)})"])[0]
        self.assertIn("No clear win-rate difference: none of the 20 cards with the games to tell won clearly more or "
                      "less often when drawn: 1 had a range clear of 0, which chance alone can do among that many "
                      "cards.", lead)

    def test_the_key_and_early_numbers(self):
        key, early = _run_page(["cardStatsKey(false)",
                                "cardStatsCoverage({games: 400, bad: 0, old: 0, of: 400, enough: false, "
                                "min_games: 800})"])
        self.assertIn("Best estimateThe difference pulled toward 0", key)
        self.assertIn("worked out matchup by matchup", key)
        self.assertIn("at most 1 in 10 verdicts is chance", key)
        self.assertIn("Only 400 games so far: read these as rough until there are 800 or more (with fewer, chance "
                      "alone can move a card's win-rate difference by many points).", early)
        self.assertNotRegex(early, r"\d+ points")         # no number that could go stale beside min_games


if __name__ == "__main__":
    unittest.main()
