"""Tests for card log version 3 (wave 2, R11 item 4): "in hand by turn 3".

cardlog.RECORD_VERSION 3 adds two numbers to each card's row, early_games and early_wins:
whether any copy was in the side's hand by the side's own 3rd turn (the kept hand, or a
move to Hand from any zone up to the turn on which that turn began; in a game that ended
before it, any drawn copy), and whether the side also won. LogReader's Turn lines set each
side's cut-off (cardlog.Game.turn), so an extra turn counts as the turn it is.
saved._pooled_cards pools version 2 and 3 records: the 8 numbers they share over both,
the early ones over version 3 batches only, out of their own games and wins
("early_of_games", "early_of_wins", kept per stratum too), with version 3's own checks.
cardstats judges "won more" or "won less" on the early split when there's version 3 data
("basis" "early"), else on the drawn one as before ("drawn"), and the CLI and the page say
"in hand by turn 3", or that a drawn verdict leans with game length.

Why: sim-investigation/w1/m8/notes.md (a card drawn at any point is drawn more in long
games, so "when drawn" leans with game length; by turn 3 it doesn't). The tests it lists
are here: the 3rd own turn counts, the opponent's next turn doesn't, a game ending before
turn 3, the kept hand against a bottomed card, an Eternal Witness-style return, a Karn
restart still failing, v2 + v3 pooling and the new bad-record checks.

Games are hand-written (test_forge_cardlog's Script), results made by hand
(test_forge_cardstats' CardStatsCase and record()), so no Forge runs. The early split of
EARLY_ROWS0 below is exactly the drawn split of test_forge_cardstats' ROWS0, whose numbers
were worked out by hand there (EXPECTED0), so the judged rows here must come out the same.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_cardlog3
"""
import json
import unittest

from decklab.lib import forge
from decklab.lib.forge import cardlog
from decklab.tests import test_forge
from decklab.tests.test_forge_cardlog import Script, dl, listed, plain_game, read
from decklab.tests.test_forge_cardstats import EXPECTED0, EXPECTED1, CardStatsCase, rate, record
from decklab.tests.test_web import NODE, _run_page

cardstats = forge.cardstats
saved = forge.saved

# Side 0's version 3 tallies in a batch of 100 counted games side 0 won 60 of: [drawn_games, drawn_wins,
# copies_drawn, used, stuck, used_round_sum, other_casts, discarded, early_games, early_wins]. The last
# two are test_forge_cardstats' ROWS0 drawn numbers (so the early split is EXPECTED0's drawn split); the
# cards were drawn at any point in more games than that, and won more of them.
EARLY_ROWS0 = {"Grizzly Bears": [90, 58, 110, 90, 12, 275, 0, 3, 70, 50],
               "Lightning Bolt": [55, 20, 55, 36, 0, 72, 0, 0, 40, 10],
               "Giant Growth": [75, 45, 75, 40, 5, 148, 0, 2, 50, 30],
               "Murderous Rider": [15, 6, 15, 6, 2, 30, 3, 0, 10, 4],
               "Forest": [100, 60, 700, 600, 50, 2400, 0, 0, 100, 60]}
EARLY_ROWS1 = {"Grizzly Bears": [30, 10, 35, 30, 1, 60, 0, 0, 30, 10]}
SPLIT = ("diff", "shrunk", "p", "judged", "discovery", "verdict")     # what the basis decides


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def record3(**kwargs):
    """A version 3 batch record (record()'s numbers, EARLY_ROWS0 and EARLY_ROWS1 unless given)."""
    kwargs.setdefault("rows", (EARLY_ROWS0, EARLY_ROWS1))
    return record(v=3, **kwargs)


def at(script, turn, seat):
    """Forge's Turn line for seat, whatever turn it is: an extra turn (Script.at gives seat 1 the odd ones)."""
    script.turn, script.active = turn, seat
    script.lines.append(f"Turn: Turn {turn} (Ai({seat})-x)")
    return script


def named(stats, name):
    return next(row for row in stats["rows"] + stats["commander"] if row["name"] == name)


# ============================================================ the tally

class TallyTests(unittest.TestCase):
    """early_games and early_wins, game by game (the last two numbers of a row)."""

    def test_the_3rd_own_turn_counts_and_the_opponents_next_doesnt(self):
        # Seat 1's own turns are 1, 3 and 5: Grizzly Bears 7, drawn on turn 5, was in hand by its 3rd turn;
        # Overrun 8, drawn on seat 2's turn 6 right after it (an instant's draw), wasn't. Seat 2's 3rd own
        # turn is 6: its Mountain 22 drawn then counts, its Lightning Bolt drawn on turn 8 doesn't.
        s = Script().keep([3], [21])
        s.at(1).land(3)
        s.at(2)
        s.at(3)
        s.at(4)
        s.at(5).draw(7)
        s.at(6).draw(22).draw(8)
        s.at(7).draw(10)                                            # a second Grizzly Bears, after
        s.at(8).draw(23)
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["v"], 3)
        self.assertEqual(r.cards["rows"][0], {
            "Forest": [1, 1, 1, 1, 0, 1, 0, 0, 1, 1],               # kept
            "Grizzly Bears": [1, 1, 2, 0, 2, 0, 0, 0, 1, 1],        # 7 by turn 5; 10 later doesn't take it back
            "Overrun": [1, 1, 1, 0, 1, 0, 0, 0, 0, 0]})             # drawn, but not by turn 3
        self.assertEqual(r.cards["rows"][1], {
            "Mountain": [1, 0, 2, 0, 2, 0, 0, 0, 1, 0],             # lost: no early win
            "Lightning Bolt": [1, 0, 1, 0, 1, 0, 0, 0, 0, 0]})

    def test_a_game_that_ends_before_the_3rd_turn_counts_every_drawn_copy(self):
        # The game ends on turn 4: seat 1 had turns 1 and 3, seat 2 turns 2 and 4. Neither 3rd turn came, so
        # every copy drawn counts (the game stays in the tally rather than leaving the denominator).
        s = Script().keep([3], [21])
        s.at(1).land(3)
        s.at(2)
        s.at(3).draw(7)
        s.at(4).draw(8).draw(22)
        r = read(s.finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])
        self.assertEqual(r.cards["rows"][0]["Overrun"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])     # drawn on turn 4
        self.assertEqual(r.cards["rows"][1]["Mountain"], [1, 1, 2, 0, 2, 0, 0, 0, 1, 1])

    def test_the_kept_hand_counts_and_a_bottomed_card_doesnt(self):
        # Seat 1 draws Forest, Giant Growth and Murderous Rider and puts the Rider on the bottom (a London
        # mulligan, at turn 0): only what it kept was in hand from the start. The Rider is drawn again on
        # turn 7, after seat 1's 3rd own turn (5): drawn, but not by turn 3.
        s = Script().keep([3, 5, 6], [21], bottom=[6])
        self.assertIn("Mulligan: Ai(1)-x has kept a hand of 2 cards", s.lines)
        s.at(1).land(3)
        for turn in range(2, 7):
            s.at(turn)
        s.at(7).draw(6)
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [1, 1, 1, 0, 1, 0, 0, 0, 1, 1])
        self.assertEqual(r.cards["rows"][0]["Murderous Rider"], [1, 1, 1, 0, 1, 0, 0, 0, 0, 0])

    def test_a_return_to_the_hand_by_turn_3_counts(self):
        # Grizzly Bears 7 and Overrun 8 are milled on turn 3; Eternal Witness returns the Bears on turn 5
        # (seat 1's 3rd own turn), and something returns Overrun on turn 7.
        s = Script().keep([3], [21])
        s.at(1).land(3)
        s.at(2)
        s.at(3).move(7, "Library", "Graveyard").move(8, "Library", "Graveyard")
        s.at(4)
        s.at(5).move(7, "Graveyard", "Hand")
        s.at(6)
        s.at(7).move(8, "Graveyard", "Hand")
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 1, 1, 0, 1, 0, 0, 0, 1, 1])
        self.assertEqual(r.cards["rows"][0]["Overrun"], [1, 1, 1, 0, 1, 0, 0, 0, 0, 0])

    def test_a_copy_cast_early_and_returned_late_still_counts(self):
        # A copy's first arrival is what counts: Grizzly Bears 7 drawn on turn 3 and cast, then bounced back
        # to the hand on turn 8, was in hand by turn 3.
        s = Script().keep([3], [21])
        s.at(1).land(3)
        s.at(2)
        s.at(3).draw(7).cast(7, to="Battlefield")
        for turn in range(4, 8):
            s.at(turn)
        s.at(8).move(7, "Battlefield", "Hand")
        r = read(s.finish(winner=2))
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 0, 1, 1, 1, 2, 0, 0, 1, 0])

    def test_an_extra_turn_is_a_turn_of_its_own(self):
        # Seat 1 takes turns 1, 3 and an extra turn 4, so its 3rd own turn began on turn 4. Grizzly Bears drawn
        # then counts; Overrun drawn on seat 2's turn 5 doesn't, though round_of(5) is round 3 (the Turn lines
        # set the cut-off, not the round). Seat 2 had only turns 2 and 5 before the game ended on turn 6.
        s = Script().keep([3], [21])
        s.at(1).land(3)
        s.at(2)
        s.at(3)
        at(s, 4, 1).draw(7)
        at(s, 5, 2).draw(22).draw(8)
        at(s, 6, 1)
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(cardlog.round_of(5), 3)
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 1, 1, 0, 1, 0, 0, 0, 1, 1])
        self.assertEqual(r.cards["rows"][0]["Overrun"], [1, 1, 1, 0, 1, 0, 0, 0, 0, 0])
        self.assertEqual(r.cards["rows"][1]["Mountain"], [1, 0, 2, 0, 2, 0, 0, 0, 1, 0])

    def test_a_restarted_game_still_fails(self):
        # Karn Liberated restarts the game after seat 1's 3rd turn: the card log doesn't follow a restart, so
        # the game's card data (early numbers included) doesn't count, as before version 3.
        s = plain_game()
        s.at(5).draw(7)
        s.at(6)
        for zone in ("Hand", "Battlefield", "Graveyard"):
            for card_id in s.ids(1, zone):
                s.move(card_id, zone, "Library")
        s.turn = 0
        s.move(8, "Library", "Hand")
        s.lines.append(dl("hand", 1, "start", 1, listed([8], s.names)))
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"], r.cards["rows"]), (0, 1, [{}, {}]))
        self.assertIn("the game was restarted", r.card_problems[0][1])

    def test_sides_timeouts_and_games_add_up(self):
        # Sides are the result's (deck1=1: Forge's seat 1 is side 1); a timeout is nobody's win, so no early
        # win either; two games add up.
        r = read(plain_game().finish(timeout=True), plain_game().finish(winner=1), deck1=1)
        self.assertEqual(r.cards["rows"][1]["Llanowar Elves"], [2, 1, 4, 4, 0, 6, 0, 0, 2, 1])
        self.assertEqual(r.cards["rows"][0]["Lightning Bolt"], [2, 0, 4, 2, 2, 2, 0, 0, 2, 0])

    def test_a_turn_line_sets_its_seats_cut_off(self):
        game = cardlog.Game()
        for turn, seat in ((1, 2), (2, 1), (3, 2), (4, 3), (5, 2), (6, 1), (7, 2), (8, 1)):
            game.turn(turn, seat)
        # Seat 2's 3rd own turn began on turn 5, seat 1's on turn 8; a seat 3 (a 4-player pod) is left alone.
        self.assertEqual(game.early_cut, {2: 5, 1: 8})
        self.assertEqual(game.own_turns, {1: 3, 2: 4})
        self.assertEqual(cardlog.EARLY_TURN, 3)
        self.assertEqual(cardlog.ROW_FIELDS[-2:], ("early_games", "early_wins"))
        self.assertEqual(cardlog.RECORD_VERSION, 3)
        self.assertEqual(len(cardlog.ROW_FIELDS), saved.CARD_TALLIES)

    def test_records_of_one_version_merge(self):
        # A run's chunks merge with cardlog.merge_record (the warm pool's): version 3 records sum all ten
        # numbers; a version 2 and a version 3 record are never one run's, and don't merge.
        a = read(plain_game().finish(winner=1)).cards
        b = read(plain_game().finish(winner=2)).cards
        merged = cardlog.merge_record(json.loads(json.dumps(a)), b)
        self.assertEqual(merged["rows"][0]["Llanowar Elves"], [2, 1, 4, 4, 0, 6, 0, 0, 2, 1])
        with self.assertRaises(ValueError):
            cardlog.merge_record(dict(a, v=2), b)


# ============================================================ saved results: versions 2 and 3

class PoolTests(CardStatsCase):

    def test_a_version_3_record_counts_its_early_numbers(self):
        pooled = saved._pooled_cards(self.result(record3()), 0)
        self.assertEqual((pooled["batches"], pooled["games"], pooled["wins"], pooled["early_of_games"],
                          pooled["early_of_wins"]), (1, 100, 60, 100, 60))
        self.assertEqual(pooled["rows"]["Grizzly Bears"], EARLY_ROWS0["Grizzly Bears"])
        stratum = pooled["strata"]["c" * 64]
        self.assertEqual((stratum["games"], stratum["wins"], stratum["early_of_games"], stratum["early_of_wins"]),
                         (100, 60, 100, 60))
        self.assertEqual(stratum["rows"]["Grizzly Bears"], [90, 58, 70, 50])

    def test_versions_2_and_3_pool_their_shared_numbers(self):
        # A version 3 batch (100 games, 60 won) beside a version 2 one (test_forge_cardstats' record(): the
        # same games and wins, Grizzly Bears drawn in 70 and won 50). The 8 shared numbers add up over both;
        # the early ones are the version 3 batch's alone, out of its games and wins.
        pooled = saved._pooled_cards(self.result(record3(), record()), 0)
        self.assertEqual((pooled["batches"], pooled["games"], pooled["wins"], pooled["early_of_games"],
                          pooled["early_of_wins"], pooled["old"]), (2, 200, 120, 100, 60, 0))
        self.assertEqual(pooled["rows"]["Grizzly Bears"], [90 + 70, 58 + 50, 110 + 110, 90 + 90, 12 + 12,
                                                           275 + 275, 0, 3 + 3, 70, 50])
        self.assertEqual(pooled["strata"]["c" * 64]["rows"]["Grizzly Bears"], [160, 108, 70, 50])
        self.assertEqual(pooled["strata"]["c" * 64]["early_of_games"], 100)
        # In either order, and over two results (each its own stratum).
        flipped = saved._pooled_cards(self.result(record(), record3()), 0)
        self.assertEqual(flipped["rows"], pooled["rows"])
        both = saved._pooled_cards(self.result(record(), key="d"), 0, saved._pooled_cards(self.result(record3()), 0))
        self.assertEqual((both["early_of_games"], both["strata"]["d" * 64]["early_of_games"]), (100, 0))
        self.assertEqual(both["strata"]["d" * 64]["rows"]["Grizzly Bears"], [70, 50, 0, 0])
        # Version 1 is still an earlier card log's: its games are "old", its tallies left out.
        with_old = saved._pooled_cards(self.result(record3(), dict(record(), v=1)), 0)
        self.assertEqual((with_old["batches"], with_old["games"], with_old["old"], with_old["early_of_games"]),
                         (1, 100, 102, 100))

    def test_version_3s_own_checks(self):
        def bears(numbers):
            return record3(rows=(dict(EARLY_ROWS0, **{"Grizzly Bears": numbers}), EARLY_ROWS1))

        bad = [
            bears([90, 58, 110, 90, 12, 275, 0, 3, 91, 50]),        # in hand by turn 3 in more games than drawn
            bears([90, 58, 110, 90, 12, 275, 0, 3, 70, 71]),        # more early wins than early games
            bears([60, 40, 110, 90, 12, 275, 0, 3, 50, 41]),        # more early wins than drawn wins
            # 50 of side 0's 60 wins without a copy by turn 3, in the 40 games without one:
            bears([90, 58, 110, 90, 12, 275, 0, 3, 60, 10]),
            bears([90, 58, 110, 90, 12, 275, 0, 3]),                # version 2's 8 numbers
            bears([90, 58, 110, 90, 12, 275, 0, 3, 70, 50, 0]),
            bears([90, 58, 110, 90, 12, 275, 0, 3, -1, 0]),
            bears([90, 58, 110, 90, 12, 275, 0, 3, 70.0, 50]),
            bears([90, 58, 110, 90, 12, 275, 0, 3, True, 0]),
            bears([90, 58, 110, 90, 12, 275, 0, 3, "70", 50]),
            record(v=2, rows=(EARLY_ROWS0, EARLY_ROWS1)),           # version 2 with version 3's 10
        ]
        for n, rec in enumerate(bad):
            with self.subTest(n=n):
                result = self.result(rec)
                self.assertIsNone(forge.side_cards(result, 0))
                self.assertEqual((saved._pooled_cards(result, 0)["batches"], saved._pooled_cards(result, 0)["old"]),
                                 (0, 0))
        # At their limits they count: in hand by turn 3 in every game drawn, every drawn win an early one,
        # and every game without a copy by turn 3 a win.
        for numbers in ([90, 58, 110, 90, 12, 275, 0, 3, 90, 58], [90, 58, 110, 90, 12, 275, 0, 3, 0, 0],
                        [90, 58, 110, 90, 12, 275, 0, 3, 50, 10]):
            with self.subTest(numbers=numbers):
                self.assertEqual(saved._pooled_cards(self.result(bears(numbers)), 0)["batches"], 1)

    def test_the_versions(self):
        self.assertEqual(saved.COUNTED_VERSIONS, (2, 3))
        self.assertIn(cardlog.RECORD_VERSION, saved.COUNTED_VERSIONS)
        self.assertEqual(saved.ROW_SIZES[cardlog.RECORD_VERSION], len(cardlog.ROW_FIELDS))
        self.assertEqual(saved.ROW_SIZES[2], saved.SHARED_TALLIES)
        self.assertEqual(saved.OLD_VERSIONS, (1,))


# ============================================================ the verdicts: on the early split

class EarlyVerdictTests(CardStatsCase):

    def assertJudgedAsExpected0(self, stats, drawn=None):
        """stats' rows are judged on the early split, which is EXPECTED0's drawn split, so each row's
        difference, best estimate, p-value and verdict are EXPECTED0's, and its early numbers are EXPECTED0's
        drawn ones; drawn: {name: (drawn_games, wr_drawn's value, wr_not's value)} to check as well."""
        for expected in EXPECTED0:
            row = named(stats, expected["name"])
            with self.subTest(card=expected["name"]):
                self.assertEqual(row["basis"], "early")
                self.assertEqual({k: row[k] for k in SPLIT}, {k: expected[k] for k in SPLIT})
                self.assertEqual((row["early_games"], row["early_share"], row["wr_early"], row["wr_not_early"]),
                                 (expected["drawn_games"], expected["drawn_share"], expected["wr_drawn"],
                                  expected["wr_not"]))
                if expected["name"] in (drawn or {}):
                    games, yes, no = drawn[expected["name"]]
                    self.assertEqual((row["drawn_games"], row["wr_drawn"]["value"], row["wr_not"]["value"]),
                                     (games, yes, no))

    def test_a_side_is_judged_on_in_hand_by_turn_3(self):
        # Grizzly Bears was drawn in 90 games (won 58: 64.4%, against 2 of 10 without it) but in hand by
        # turn 3 in 70 (won 50 of 70, 10 of the other 30): the verdict is the second's, as EXPECTED0 has it.
        stats = forge.side_cards(self.result(record3()), 0)
        self.assertEqual({k: v for k, v in stats.items() if k not in ("rows", "commander")},
                         {"games": 100, "bad": 2, "old": 0, "of": 102, "matchups": 1, "enough": False,
                          "min_games": 800, "min_split": 30, "basis": "early", "early_of": 100, "compared": 3,
                          "fdr": 0.1, "spread": 0.0621, "spread_weight": 0.01})
        self.assertJudgedAsExpected0(stats, {"Grizzly Bears": (90, 0.6444, 0.2),
                                             "Lightning Bolt": (55, round(20 / 55, 4), round(40 / 45, 4))})
        self.assertEqual(named(stats, "Grizzly Bears")["verdict"], "more")
        self.assertEqual(named(stats, "Lightning Bolt")["verdict"], "less")
        # Side 1's one card, in hand by turn 3 whenever drawn: EXPECTED1's numbers.
        bears1 = named(forge.side_cards(self.result(record3()), 1), "Grizzly Bears")
        self.assertEqual({k: bears1[k] for k in SPLIT}, {k: EXPECTED1[0][k] for k in SPLIT})
        json.dumps(stats, allow_nan=False)

    def test_beside_version_2_batches_only_version_3_games_are_judged(self):
        # 100 version 3 games and 100 version 2 ones (record(): ROWS0) in one result: the early split is out of
        # the 100 version 3 games alone, so it's judged as before; the drawn numbers count all 200.
        stats = forge.side_cards(self.result(record3(), record()), 0)
        self.assertEqual((stats["games"], stats["early_of"], stats["of"], stats["basis"]), (200, 100, 204, "early"))
        self.assertJudgedAsExpected0(stats, {"Grizzly Bears": (160, round(108 / 160, 4), round(12 / 40, 4))})

    def test_without_version_3_data_the_drawn_verdict_stays(self):
        stats = forge.side_cards(self.result(record()), 0)
        self.assertEqual((stats["basis"], stats["early_of"]), ("drawn", 0))
        for expected in EXPECTED0:
            self.assertEqual(named(stats, expected["name"]), expected)

    def test_matchup_by_matchup_on_the_early_split(self):
        # Simpson's paradox again (test_forge_cardpool), in the early numbers: the list wins 80 of 100 against an
        # easy opponent with the card in hand by turn 3 in 80 (64 won), 20 of 100 against a hard one with it in
        # 20 (4 won). Pooled naively 68% v 32%; within each matchup it's 0.
        def side(wins, drawn, drawn_wins, early, early_wins, key):
            rows = {"Grizzly Bears": [drawn, drawn_wins, drawn, drawn, 0, 2 * drawn, 0, 0, early, early_wins]}
            rec = record3(games=100, wins=(wins, 100 - wins), first=(50, 50), bad=0, rows=(rows, {}))
            return self.result(rec, played=100, key=key)

        easy, hard = side(80, 90, 72, 80, 64, "c"), side(20, 30, 6, 20, 4, "d")
        pooled = saved._pooled_cards(hard, 0, saved._pooled_cards(easy, 0))
        stats = cardstats.card_rows(saved._side_cards(easy["sides"][0]), "constructed", pooled, 200, matchups=2)
        row = named(stats, "Grizzly Bears")
        self.assertEqual((row["wr_early"]["value"], row["wr_not_early"]["value"]), (0.68, 0.32))
        self.assertEqual((row["diff"]["value"], row["verdict"], row["shrunk"]), (0.0, "unclear", 0.0))
        self.assertEqual((row["drawn_games"], row["wr_drawn"]["value"]), (120, 0.65))
        # The same two matchups' early numbers in one stratum (no strata: the totals) would say +36 points.
        flat = cardstats.card_rows(saved._side_cards(easy["sides"][0]), "constructed",
                                   {k: v for k, v in pooled.items() if k != "strata"}, 200)
        self.assertEqual(named(flat, "Grizzly Bears")["diff"]["value"], 0.36)

    def test_lands_and_commanders(self):
        # A land is never judged, on either split; a commander's row is by casts, as before, with no early
        # numbers, while the Main deck's rows of a Commander list are judged on the early split.
        mountain = [90, 58, 110, 90, 12, 275, 0, 0, 70, 50]           # Grizzly Bears' numbers, which get "more"
        stats = forge.side_cards(self.result(record3(rows=(dict(EARLY_ROWS0, Mountain=mountain), {}))), 0)
        land = named(stats, "Mountain")
        self.assertEqual((land["land"], land["basis"], land["judged"], land["verdict"], land["shrunk"]),
                         (True, "early", False, None, None))
        # Its difference stays the drawn split's (58 of 90 drawn against 2 of 10 not: +44.4 points), so the
        # command line's matches the drawn rates both it and the page show for a land; its early numbers are
        # there as a spell's are, but nothing is judged on them.
        _, low, high = cardstats.newcombe(58, 90, 2, 10)
        self.assertEqual(land["diff"], {"value": 0.4444, "low": round(low, 4), "high": round(high, 4)})
        self.assertNotEqual(land["diff"], named(stats, "Grizzly Bears")["diff"])
        self.assertEqual((land["early_games"], land["wr_early"]["value"], land["wr_not_early"]["value"]),
                         (70, round(50 / 70, 4), round(10 / 30, 4)))
        gisa = {"Commander": [[1, "Ghoulcaller Gisa"]], "Main": [[4, "Grizzly Bears"], [10, "Swamp"]]}
        rec = record3(wins=(50, 50), rows=({"Grizzly Bears": [80, 40, 90, 70, 2, 150, 0, 0, 60, 30]}, {}),
                      commander=({"Ghoulcaller Gisa": [40, 30, 55, 160]}, {}))
        stats = forge.side_cards(self.result(rec, cards_a=gisa, kinds=("commander", "commander")), 0)
        commander = stats["commander"][0]
        self.assertNotIn("basis", commander)
        self.assertNotIn("early_games", commander)
        self.assertEqual((commander["cast_games"], commander["wr_cast"]["value"]), (40, 0.75))
        self.assertEqual((named(stats, "Grizzly Bears")["basis"], named(stats, "Grizzly Bears")["early_games"]),
                         ("early", 60))

    def test_enough_counts_the_games_the_verdicts_are_on(self):
        # 800 version 3 games are enough. Beside 800 version 2 games, 100 version 3 ones aren't, though 900
        # games have card data: the verdicts on in hand by turn 3 rest on those 100. 800 version 2 games
        # alone are enough for their drawn verdicts, as before.
        enough = forge.side_cards(self.result(*[record3() for _ in range(8)]), 0)
        self.assertEqual((enough["games"], enough["early_of"], enough["basis"], enough["enough"]),
                         (800, 800, "early", True))
        mixed = forge.side_cards(self.result(record3(), *[record() for _ in range(8)]), 0)
        self.assertEqual((mixed["games"], mixed["early_of"], mixed["basis"], mixed["enough"]),
                         (900, 100, "early", False))
        drawn = forge.side_cards(self.result(*[record() for _ in range(8)]), 0)
        self.assertEqual((drawn["games"], drawn["basis"], drawn["enough"]), (800, "drawn", True))


# ============================================================ the command line

class CommandLineTests(CardStatsCase):

    def lines(self, stats):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            forge.cli._print_cards("casual/cards (target)", stats)
        return out.getvalue().splitlines()

    def test_in_hand_by_turn_3(self):
        stats = forge.side_cards(self.result(record3()), 0)
        lines = self.lines(stats)
        text = "\n".join(lines)
        self.assertIn(" by t3 ", lines[lines.index("  spells:") + 1])
        self.assertIn("won by t3 / not", text)
        self.assertIn("by turn 3 every game has\n  seen about as many cards", text)
        bears = next(line for line in lines if line.startswith("  Grizzly Bears"))
        # drawn 90%, in hand by turn 3 70%; its early rates (71% and 33%) and verdict
        self.assertRegex(bears, r"^  Grizzly Bears +4 +90% +70% +82% +11% +3\.1 +71% \(60-81\) / 33% \(19-51\) +"
                                r"\+38 \(\+17 to \+55\), best \+10, won more when in hand by turn 3$")
        bolt = next(line for line in lines if line.startswith("  Lightning Bolt"))
        self.assertTrue(bolt.endswith(", won less when in hand by turn 3"), bolt)
        self.assertNotIn("in hand by turn 3: counted in", text)
        self.assertNotIn("leans with game length", text)
        # Beside version 2 games, it says how many games counted it.
        self.assertIn("  ! early numbers: fewer than 800 games with card data", lines)
        mixed = self.lines(forge.side_cards(self.result(record3(), record()), 0))
        self.assertEqual(mixed[1], "  in hand by turn 3: counted in 100 of those games (an earlier card log kept "
                                   "the rest, and didn't count it)")
        # Early numbers by the games the verdicts are on.
        self.assertEqual(mixed[2], "  ! early numbers: fewer than 800 games counting in hand by turn 3")

    def test_a_land_shows_its_drawn_rates(self):
        # As on the page: a land is never judged, so its rates and difference are when drawn and not, under
        # either basis (cardstats keeps a land's diff on the drawn split); its share by turn 3 is still shown.
        mountain = [90, 58, 110, 90, 12, 275, 0, 0, 70, 50]
        stats = forge.side_cards(self.result(record3(rows=(dict(EARLY_ROWS0, Mountain=mountain), {}))), 0)
        lines = self.lines(stats)
        text = "\n".join(lines)
        header = lines[lines.index("  lands:") + 1]
        self.assertIn(" by t3 ", header)
        self.assertIn("won drawn / not", header)
        self.assertNotIn("won by t3", header)
        self.assertIn("won by t3 / not", lines[lines.index("  spells:") + 1])
        land = named(stats, "Mountain")
        line = next(line for line in lines if line.startswith("  Mountain"))
        self.assertIn(f"{forge.cli._range(land['wr_drawn'])} / {forge.cli._range(land['wr_not'])}", line)
        self.assertNotIn(forge.cli._range(land["wr_early"]), line)
        self.assertRegex(line, r"^  Mountain +\d+ +90% +70% .* \+44 \(\+\d+ to \+\d+\), no verdict for a land$")
        self.assertIn("  A land's win rates and difference are when drawn and when not, as on the page.", lines)
        # Older card data says nothing of it: every rate there is a drawn one.
        self.assertNotIn("A land's win rates", "\n".join(self.lines(forge.side_cards(self.result(record()), 0))))
        self.assertIn("won drawn / not", text)

    def test_older_card_data_leans_with_game_length(self):
        lines = self.lines(forge.side_cards(self.result(record()), 0))
        text = "\n".join(lines)
        self.assertIn("so the verdicts are on\n  \"drawn\", and a \"won more\" or \"won less\" leans with game length.",
                      text)
        bears = next(line for line in lines if line.startswith("  Grizzly Bears"))
        self.assertTrue(bears.endswith(", won more when drawn (leans with game length)"), bears)
        self.assertIn("won drawn / not", text)
        self.assertNotIn("by t3", text)


# ============================================================ the page's words

@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageWordsTests(CardStatsCase):

    STUB = "globalThis.cardLink = (entry) => el('span', {}, entry.name); "

    def notes(self, stats, *names):
        return _run_page([f"cardStatsNotes({json.dumps(named(stats, name))}, {json.dumps(stats)}, "
                          f"{json.dumps(named(stats, name)['land'] is True)}, false)" for name in names])

    def test_a_cards_words(self):
        stats = forge.side_cards(self.result(record3()), 0)
        bears, rider, forest = self.notes(stats, "Grizzly Bears", "Murderous Rider // Swift End", "Forest")
        self.assertEqual(bears, "Won 71.4% when in hand by turn 3, 33.3% when not: +38.1 points (+17 to +55), best "
                                "estimate +10.3. Won more when in hand by turn 3. In hand by turn 3 in 70% of games. "
                                "Drawn at any point: won 64.4%, 20.0% when not. 3 copies discarded or cycled from "
                                "hand.")
        # Out of the games that counted in hand by turn 3 (early_of), not every game.
        self.assertTrue(rider.startswith("Not enough games to tell a win-rate difference yet: in hand by turn 3 in 10, "
                                         "not in hand by turn 3 in 90 (it takes 30 of each). In hand by turn 3 in 10% "
                                         "of games. Drawn at any point: won 40.0%, 63.5% when not."), rider)
        # A land: its drawn rates, no verdict, as before.
        self.assertEqual(forest, "Drawn in every one of the 100 games, which the deck won 60.0% of. No verdict for a "
                                 "land.")
        mixed = forge.side_cards(self.result(record3(), record()), 0)
        rider = self.notes(mixed, "Murderous Rider // Swift End")[0]
        self.assertTrue(rider.startswith("Not enough games to tell a win-rate difference yet: in hand by turn 3 in 10, "
                                         "not in hand by turn 3 in 90 (it takes 30 of each)."), rider)

    def test_what_the_verdicts_are_on_is_said_once(self):
        early = forge.side_cards(self.result(record3()), 0)
        mixed = forge.side_cards(self.result(record3(), record()), 0)
        drawn = forge.side_cards(self.result(record()), 0)
        older = {k: v for k, v in drawn.items() if k not in ("basis", "early_of")}
        words = _run_page([f"cardStatsBasis({json.dumps(s)})" for s in (early, mixed, drawn)]
                          + [f"cardStatsBasis({json.dumps(older)}) === null"])
        on = ("Won more or less is judged on the games a copy was in hand by the deck's own turn 3 (the opening "
              "hand, or drawn by then) against the rest. By turn 3 every game has seen about as many cards, so "
              "this doesn't lean with game length as \"drawn at any point\" does (long games draw more cards); "
              "each card's win rates when drawn follow its verdict.")
        self.assertEqual(words[0], on)
        self.assertEqual(words[1], on + " In hand by turn 3 was counted in 100 of the 200 games: an earlier card "
                                        "log kept the rest.")
        self.assertEqual(words[2], "These games were kept before Deck Lab counted whether a copy was in hand by turn "
                                   "3, so won more or less is judged on the games a card was drawn in at any point. "
                                   "That leans with game length: long games draw more cards, so a deck that wins its "
                                   "long games has cards that look good for it.")
        self.assertEqual(words[3], "true")          # an older server's stats: nothing said
        # Both pages say it, before the key or the lead.
        result = {"games": 102, "cards": [early, None], "casts": [[], []]}
        part = _run_page([f"{self.STUB}cardStatsPart({json.dumps(result)}, {json.dumps([{'title': 'A'}, {'title': 'B'}])})"])[0]
        self.assertLess(part.index("judged on the games a copy was in hand"), part.index("Best estimate"))
        page = {"cards": early, "results": [{"sides": [{"current": True}]}]}
        deck = _run_page([f"{self.STUB}deckCardStats({json.dumps(page)}, 'list')"])[0]
        self.assertLess(deck.index("judged on the games a copy was in hand"), deck.index("Clear win-rate differences"))

    def test_the_key_holds_for_both_bases(self):
        # The key under cardStatsBasis describes the difference for either basis, and says a land's rates are
        # its drawn ones (as its row shows them).
        key = _run_page(["cardStatsKey(false)"])[0]
        self.assertIn("Won ... whenThe deck's win rate in games where a copy was in hand by its own turn 3 (the "
                      "opening hand, or drawn by then) and where none was, or, for games kept before Deck Lab counted "
                      "that, where a copy was drawn at any point and where none was; and the difference in "
                      "percentage points with its 95% range in brackets.", key)
        self.assertIn("so game length alone can make a card drawn at any point look better or worse; by turn 3 "
                      "every game has seen about as many cards.", key)
        self.assertNotIn("Won ... when drawn", key)
        self.assertIn("LandsNo win-rate verdict, only the two win rates, when a copy was drawn at any point and when "
                      "not: the games without a copy of a land", key)

    def test_early_numbers_count_the_games_the_verdicts_are_on(self):
        # Beside version 2 games, the early numbers are the version 3 games (cardstats' "enough"), and the
        # sentence says so instead of "Only 900 games so far" with 800 needed.
        mixed = forge.side_cards(self.result(record3(), *[record() for _ in range(8)]), 0)
        alone = forge.side_cards(self.result(record3()), 0)
        mixed_words, alone_words = _run_page([f"cardStatsCoverage({json.dumps(s)})" for s in (mixed, alone)])
        self.assertIn("Early numbers Only 100 of the 900 games counted in hand by turn 3, which the verdicts are on: "
                      "read these as rough until there are 800 or more (with fewer, chance alone can move a card's "
                      "win-rate difference by many points).", mixed_words)
        self.assertIn("Early numbers Only 100 games so far: read these as rough until there are 800 or more",
                      alone_words)

    def test_the_deck_pages_lead(self):
        stats = forge.side_cards(self.result(record3()), 0)
        lead = _run_page([f"{self.STUB}standOutParts({json.dumps(stats)})"])[0]
        self.assertIn("Clear win-rate differences: the deck's win rate when each was in hand by turn 3 against when "
                      "none was, in percentage points, with the 95% range; only those that stand out among the 3 "
                      "cards compared are listed. By turn 3 every game has seen about as many cards, so game length "
                      "isn't what these say.", lead)
        self.assertIn("Grizzly Bears+38.1 points (+17 to +55)", lead)          # its early rates' gap, as its row
        self.assertIn("Lightning Bolt−58.3 points (−71 to −39)", lead)
        self.assertNotIn("Long games draw more cards", lead)
        # Judged on the early split, none standing out; and too few games to judge any.
        unclear = dict(stats, rows=[dict(row, verdict="unclear", discovery=False) if row["judged"] else row
                                    for row in stats["rows"]])
        few = dict(stats, rows=[dict(row, judged=False) for row in stats["rows"]])
        none, early = _run_page([f"{self.STUB}standOutParts({json.dumps(unclear)})",
                                 f"{self.STUB}standOutParts({json.dumps(few)})"])
        self.assertIn("won clearly more or less often when in hand by turn 3", none)
        self.assertIn("a card needs 30 games in hand by turn 3 and as many not in hand by turn 3", early)


if __name__ == "__main__":
    unittest.main()
