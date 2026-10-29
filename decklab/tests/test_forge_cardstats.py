"""Tests for the per-card stats from the card log (Milestone 8): the tallies a saved
result's batches keep ("cards", saved._pooled_cards), the rows the pages get
(forge.side_cards for a matchup's side, forge.list_cards pooled over a list's saved
matchups, view()'s "cards"), their ranges, thresholds and verdicts, and the AI limits'
"drawn_games".

Every result is made by hand (test_forge.stored) with "cards" records in the contract's
shape, so no Forge or fake Forge runs. They're version 2 records (8 numbers a card, no
"in hand by turn 3"), which are still counted, so the rows here are judged on when a card
was drawn ("basis" "drawn"); test_forge_cardlog3 has version 3's early split. The
expected ranges were worked out apart from the code, with the other form of Wilson's
range, (2x + z^2 -/+ z sqrt(z^2 + 4x(n-x)/n)) / (2(n + z^2)), and Newcombe's method 10
from it; that working gives his own Table II numbers (test_newcombe_matches_the_paper). Each row's "shrunk" and "p" were worked out
the same way, from the standard error with half a win and a game added to each rate
(the working is beside EXPECTED0). How a list's matchups are pooled, shrinking and the
verdicts' false discovery rate have their own tests, in test_forge_cardpool. test_forge's
module set-up (the made-up Forge folder and the forge fixtures' card index) is reused.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_cardstats
"""
import copy
import json
import math
import unittest
from unittest import mock

from decklab.lib import forge
from decklab.tests import test_forge
from decklab.tests.test_forge import entry, sections, stored

# A list with two printings of one card (one row), an adventure and a split card (their
# .dck names are the front faces, "Murderous Rider" and "Fire"), and two kinds of land.
LIST = """Deck
2 Grizzly Bears (FDN) 1
2 Grizzly Bears (M19) 2
2 Murderous Rider // Swift End
2 Fire // Ice
1 Lightning Bolt
1 Giant Growth
20 Forest
3 Mountain
"""

# Side 0's tallies in a batch whose 100 counted games side 0 won 60 of: [drawn_games,
# drawn_wins, copies_drawn, used, stuck, used_round_sum, other_casts, discarded]. Fire and
# Mountain are left out (all zeros), as the card log may.
ROWS0 = {"Grizzly Bears": [70, 50, 110, 90, 12, 275, 0, 3],     # won more when drawn
         "Lightning Bolt": [40, 10, 40, 36, 0, 72, 0, 0],       # won less when drawn
         "Giant Growth": [50, 30, 50, 40, 5, 148, 0, 2],        # the same either way
         "Murderous Rider": [10, 4, 10, 6, 2, 30, 3, 0],        # too few drawn games to judge
         "Forest": [100, 60, 700, 600, 50, 2400, 0, 0]}         # drawn in every game
ROWS1 = {"Grizzly Bears": [30, 10, 35, 30, 1, 60, 0, 0]}


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def record(games=100, wins=(60, 40), rows=(ROWS0, ROWS1), commander=({}, {}), bad=2, first=(50, 50), v=2):
    """A batch's "cards" record, as the card log kept it in version 2 (still counted: its rows have 8
    numbers, without version 3's early_games and early_wins)."""
    return {"v": v, "games": games, "bad": bad, "wins": list(wins), "first": list(first),
            "rows": copy.deepcopy(list(rows)), "commander": copy.deepcopy(list(commander))}


# What a version 2 record's rows have where version 3's have their early numbers.
NO_EARLY = {"early_games": None, "early_share": None, "wr_early": None, "wr_not_early": None, "basis": "drawn"}


def rate(value, low, high, games, wins):
    return {"value": value, "low": low, "high": high, "games": games, "wins": wins}


def diff(value, low, high):
    return {"value": value, "low": low, "high": high}


def nothing_drawn(name, qty, land, not_drawn):
    """The row of a card no tally names."""
    return {"name": name, "qty": qty, "land": land, "drawn_games": 0, "drawn_share": 0.0, "copies_drawn": 0,
            "cast": 0, "cast_share": None, "stuck": 0, "stuck_share": None, "discarded": 0, "other_casts": 0,
            "avg_turn": None, "wr_drawn": None, "wr_not": not_drawn, "diff": None, "shrunk": None, "p": None,
            "judged": False, "discovery": None, "verdict": None, **NO_EARLY}


# Side 0's rows, nonlands then lands, each by name. The ranges (4 places) from the working
# in the module docstring: e.g. Grizzly Bears won 50 of 70 games drawn (0.714286; Wilson
# 0.599496..0.806779) and 10 of 30 not (0.333333; 0.192303..0.512203), so the difference is
# 0.380952 and Newcombe's range 0.380952 - sqrt(0.114790^2 + 0.178869^2) = 0.168418 to
# 0.380952 + sqrt(0.092493^2 + 0.141030^2) = 0.549608.
# Its standard error, from 50.5/71 and 10.5/31, is sqrt(0.711268 * 0.288732 / 70 + 0.338710 *
# 0.661290 / 30) = 0.101980, so p = 2 * Phi(-0.380952 / 0.101980) = 0.000187. The three judged
# spells (Giant Growth's se 0.098059, Lightning Bolt's 0.084487) put the spread's square at
# 0.152750 on their own, with a variance of 0.0000831 against SPREAD_DOUBT's (0.5 * 0.045^2)^2 =
# 0.00000103, so a weight of 0.0122 and a spread of sqrt(0.002025 + 0.0122 * (0.152750 -
# 0.002025)) = 0.062147; shrunk is 0.380952 * 0.062147^2 / (0.062147^2 + 0.101980^2) = 0.103160.
# Ranked by p, Lightning Bolt (5e-12 <= 0.1 / 3) and Grizzly Bears (0.000187 <= 0.2 / 3) are
# discoveries, Giant Growth (p 1) isn't.
EXPECTED0 = [
    nothing_drawn("Fire // Ice", 2, False, rate(0.6, 0.502, 0.6906, 100, 60)),
    {"name": "Giant Growth", "qty": 1, "land": False, "drawn_games": 50, "drawn_share": 0.5, "copies_drawn": 50,
     "cast": 40, "cast_share": 0.8, "stuck": 5, "stuck_share": 0.1, "discarded": 2, "other_casts": 0,
     "avg_turn": 3.7, "wr_drawn": rate(0.6, 0.4618, 0.7239, 50, 30), "wr_not": rate(0.6, 0.4618, 0.7239, 50, 30),
     "diff": diff(0.0, -0.1856, 0.1856), "shrunk": 0.0, "p": 1.0, "judged": True, "discovery": False,
     "verdict": "unclear", **NO_EARLY},
    {"name": "Grizzly Bears", "qty": 4, "land": False, "drawn_games": 70, "drawn_share": 0.7, "copies_drawn": 110,
     "cast": 90, "cast_share": 0.8182, "stuck": 12, "stuck_share": 0.1091, "discarded": 3, "other_casts": 0,
     "avg_turn": 3.1, "wr_drawn": rate(0.7143, 0.5995, 0.8068, 70, 50), "wr_not": rate(0.3333, 0.1923, 0.5122, 30, 10),
     "diff": diff(0.381, 0.1684, 0.5496), "shrunk": 0.1032, "p": 0.0002, "judged": True, "discovery": True,
     "verdict": "more", **NO_EARLY},
    {"name": "Lightning Bolt", "qty": 1, "land": False, "drawn_games": 40, "drawn_share": 0.4, "copies_drawn": 40,
     "cast": 36, "cast_share": 0.9, "stuck": 0, "stuck_share": 0.0, "discarded": 0, "other_casts": 0,
     "avg_turn": 2.0, "wr_drawn": rate(0.25, 0.1419, 0.4019, 40, 10), "wr_not": rate(0.8333, 0.7197, 0.9069, 60, 50),
     "diff": diff(-0.5833, -0.7141, -0.3936), "shrunk": -0.2048, "p": 0.0, "judged": True, "discovery": True,
     "verdict": "less", **NO_EARLY},
    {"name": "Murderous Rider // Swift End", "qty": 2, "land": False, "drawn_games": 10, "drawn_share": 0.1,
     "copies_drawn": 10, "cast": 6, "cast_share": 0.6, "stuck": 2, "stuck_share": 0.2, "discarded": 0,
     "other_casts": 3, "avg_turn": 5.0, "wr_drawn": rate(0.4, 0.1682, 0.6873, 10, 4),
     "wr_not": rate(0.6222, 0.519, 0.7154, 90, 56), "diff": diff(-0.2222, -0.4721, 0.0831), "shrunk": -0.028,
     "p": 0.1746, "judged": False, "discovery": None, "verdict": None, **NO_EARLY},
    {"name": "Forest", "qty": 20, "land": True, "drawn_games": 100, "drawn_share": 1.0, "copies_drawn": 700,
     "cast": 600, "cast_share": 0.8571, "stuck": 50, "stuck_share": 0.0714, "discarded": 0, "other_casts": 0,
     "avg_turn": 4.0, "wr_drawn": rate(0.6, 0.502, 0.6906, 100, 60), "wr_not": None, "diff": None,
     "shrunk": None, "p": None, "judged": False, "discovery": None, "verdict": None, **NO_EARLY},
    nothing_drawn("Mountain", 3, True, rate(0.6, 0.502, 0.6906, 100, 60)),
]
# Side 1 (test_forge.stored's list: 4 Grizzly Bears, 20 Forest): Grizzly Bears won 10 of 30 games
# drawn and 30 of 70 not: se 0.104723 from 10.5/31 and 30.5/71, so p = 0.3631; the one judged
# card barely moves the spread off 0.045 (weight 0.0030, spread 0.044868), which keeps
# 0.044868^2 / (0.044868^2 + 0.104723^2) = 0.1551 of its difference.
EXPECTED1 = [
    {"name": "Grizzly Bears", "qty": 4, "land": False, "drawn_games": 30, "drawn_share": 0.3, "copies_drawn": 35,
     "cast": 30, "cast_share": 0.8571, "stuck": 1, "stuck_share": 0.0286, "discarded": 0, "other_casts": 0,
     "avg_turn": 2.0, "wr_drawn": rate(0.3333, 0.1923, 0.5122, 30, 10), "wr_not": rate(0.4286, 0.3194, 0.5452, 70, 30),
     "diff": diff(-0.0952, -0.2783, 0.1143), "shrunk": -0.0148, "p": 0.3631, "judged": True, "discovery": False,
     "verdict": "unclear", **NO_EARLY},
    nothing_drawn("Forest", 20, True, rate(0.4, 0.3094, 0.498, 100, 40)),
]


def negative_zeros(data):
    """Every -0.0 in data (the page would show "-0%")."""
    if isinstance(data, dict):
        return [z for value in data.values() for z in negative_zeros(value)]
    if isinstance(data, list):
        return [z for value in data for z in negative_zeros(value)]
    return [data] if isinstance(data, float) and data == 0 and math.copysign(1, data) < 0 else []


def games(n, side0_wins):
    """n games for test_forge.stored: side 0 wins the first side0_wins, side 1 the rest."""
    return [(0 if i < side0_wins else 1, "win", i % 2) for i in range(n)]


class CardStatsCase(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.list = entry(LIST, "casual/cards")

    def result(self, *records, played=102, kinds=("constructed", "constructed"), cards_a=None, key="c", sha=None):
        """A stored result of LIST (side 0) against test_forge.stored's list (side 1): one batch of
        played games per record (None: a batch played without the card log)."""
        result = stored(games(played, 61), cards_a=cards_a or self.list["cards"], kinds=kinds)
        one = result["batches"][0]
        result["batches"] = []
        for n, rec in enumerate(records or (None,)):
            batch = dict(copy.deepcopy(one), n=n, seed=n + 1, deck1=n % 2)
            if rec is not None:
                batch["cards"] = rec
            result["batches"].append(batch)
        result["sides"][0]["card_sha"] = sha or self.list["card_sha"]
        result["key"] = key * 64
        return result

    def save(self, *results):
        """Save results as today's card-log engine played them (wave 2: the deck page's list_cards and
        list_ai pool only the sides with today's decklab-kind side id, engine.side_ids)."""
        self.results.mkdir(exist_ok=True)
        for r in results:
            for side in r["sides"]:
                side.setdefault("engine_id", forge.engine.side_ids(side["card_sha"], side["kind"])["decklab"])
            (self.results / f"{r['key']}.json").write_text(json.dumps(r), encoding="utf-8")


# ============================================================ one side of a matchup

class SideTests(CardStatsCase):

    def test_every_field_of_every_row(self):
        result = self.result(record())
        stats = forge.side_cards(result, 0)
        self.assertEqual({k: v for k, v in stats.items() if k not in ("rows", "commander")},
                         {"games": 100, "bad": 2, "old": 0, "of": 102, "matchups": 1, "enough": False,
                          "min_games": 800, "min_split": 30, "basis": "drawn", "early_of": 0, "compared": 3,
                          "fdr": 0.1, "spread": 0.0621, "spread_weight": 0.01})
        self.assertEqual(stats["commander"], [])
        for got, expected in zip(stats["rows"], EXPECTED0, strict=True):
            self.assertEqual(got, expected, expected["name"])
        self.assertEqual(forge.side_cards(result, 1)["rows"], EXPECTED1)
        json.dumps(stats, allow_nan=False)

    def test_newcombe_matches_the_paper(self):
        # Newcombe (1998), "Interval estimation for the difference between independent proportions",
        # Table II, method 10: 56/70 - 48/80 is 0.0524 to 0.3339, 9/10 - 3/10 is 0.1705 to 0.8090,
        # 6/7 - 2/7 is 0.0582 to 0.8062 (0.80625 in full), 5/56 - 0/29 is -0.0381 to 0.1926.
        for (x1, n1, x2, n2), (low, high) in (((56, 70, 48, 80), (0.0524, 0.3339)), ((9, 10, 3, 10), (0.1705, 0.8090)),
                                              ((6, 7, 2, 7), (0.0582, 0.8063)), ((5, 56, 0, 29), (-0.0381, 0.1926))):
            value, got_low, got_high = forge.cardstats.newcombe(x1, n1, x2, n2)
            self.assertAlmostEqual(value, x1 / n1 - x2 / n2)
            self.assertEqual((round(got_low, 4), round(got_high, 4)), (low, high))
        self.assertIsNone(forge.cardstats.newcombe(3, 5, 0, 0))
        self.assertIsNone(forge.cardstats.newcombe(0, 0, 3, 5))

    def test_wilson_moved_down_but_works_where_it_was(self):
        self.assertIs(forge.wilson, forge.cardstats.wilson)
        self.assertIs(forge.views.wilson, forge.cardstats.wilson)
        self.assertIs(forge._r, forge.cardstats._r)
        for name in ("_card_fields", "_is_land", "_merged_cards", "_side_cards"):
            self.assertTrue(callable(getattr(forge.ai, name)), name)
            self.assertIs(getattr(forge, name), getattr(forge.ai, name))

    def test_the_thresholds(self):
        result = self.result(record())
        with mock.patch.object(forge.cardstats, "MIN_CARD_GAMES", 101):
            stats = forge.side_cards(result, 0)
        self.assertEqual((stats["enough"], stats["min_games"]), (False, 101))
        # Grizzly Bears had 30 games without it: one short of 31, so it isn't judged; Lightning Bolt
        # (40 and 60) still is.
        with mock.patch.object(forge.cardstats, "MIN_SPLIT_GAMES", 31):
            stats = forge.side_cards(result, 0)
        rows = {row["name"]: row for row in stats["rows"]}
        self.assertEqual(stats["min_split"], 31)
        self.assertEqual((rows["Grizzly Bears"]["judged"], rows["Grizzly Bears"]["verdict"]), (False, None))
        self.assertEqual(rows["Grizzly Bears"]["diff"], EXPECTED0[2]["diff"])     # the range is still there
        self.assertEqual((rows["Lightning Bolt"]["judged"], rows["Lightning Bolt"]["verdict"]), (True, "less"))
        # Even with no threshold, a card with no games on one side has nothing to judge.
        with mock.patch.object(forge.cardstats, "MIN_SPLIT_GAMES", 0):
            rows = {row["name"]: row for row in forge.side_cards(result, 0)["rows"]}
        self.assertEqual((rows["Forest"]["judged"], rows["Fire // Ice"]["judged"]), (False, False))
        self.assertEqual(rows["Murderous Rider // Swift End"]["verdict"], "unclear")

    def test_lands_get_no_verdict(self):
        # The games without a copy of a land were mostly short of lands or of that colour, so a land's win-rate
        # difference is never judged, however many games each way. Its rates and difference are still there.
        mountain = [70, 50, 110, 90, 12, 275, 0, 0]        # Grizzly Bears' games and wins, which get "more"
        result = self.result(record(rows=(dict(ROWS0, Mountain=mountain), ROWS1)))
        rows = {row["name"]: row for row in forge.side_cards(result, 0)["rows"]}
        land, bears = rows["Mountain"], rows["Grizzly Bears"]
        self.assertEqual((land["land"], land["judged"], land["verdict"]), (True, False, None))
        self.assertEqual((bears["land"], bears["judged"], bears["verdict"]), (False, True, "more"))
        rates = ("wr_drawn", "wr_not", "diff")
        self.assertEqual([land[k] for k in rates], [bears[k] for k in rates])
        # The deck page's pooled rows are the same.
        pooled = forge.list_cards(sections(LIST), "constructed", [result])
        self.assertEqual([(row["name"], row["judged"], row["verdict"]) for row in pooled["rows"] if row["land"]],
                         [("Forest", False, None), ("Mountain", False, None)])
        # A card the card data doesn't know (land None) is judged as a nonland is.
        listed = {"Commander": [], "Main": [[2, "Totally Fake Card"], [3, "Mountain"]]}
        rec = record(rows=({"Totally Fake Card": mountain, "Mountain": mountain}, {}))
        rows = forge.side_cards(self.result(rec, cards_a=listed), 0)["rows"]
        self.assertEqual([(row["name"], row["land"], row["judged"], row["verdict"]) for row in rows],
                         [("Totally Fake Card", None, True, "more"), ("Mountain", True, False, None)])

    def test_a_batch_of_games_whose_card_log_all_failed(self):
        # The card log was on but no game passed its checks: no rates, and nothing NaN or infinite.
        result = self.result(record(games=0, wins=(0, 0), first=(0, 0), rows=({}, {}), bad=102))
        stats = forge.side_cards(result, 0)
        self.assertEqual((stats["games"], stats["bad"], stats["of"], stats["enough"]), (0, 102, 102, False))
        for row in stats["rows"]:
            self.assertEqual((row["drawn_share"], row["wr_drawn"], row["wr_not"], row["diff"], row["judged"]),
                             (None, None, None, None, False))
        json.dumps(stats, allow_nan=False)

    def test_every_game_won_or_lost(self):
        # The ranges reach 0 and 1 and stay inside them (Wilson's maths can stray by a rounding error).
        rows = {"Grizzly Bears": [40, 40, 40, 40, 0, 80, 0, 0]}
        stats = forge.side_cards(self.result(record(wins=(100, 0), rows=(rows, {}))), 0)
        bears = next(row for row in stats["rows"] if row["name"] == "Grizzly Bears")
        self.assertEqual(bears["wr_drawn"]["high"], 1.0)
        self.assertEqual(bears["wr_not"]["high"], 1.0)
        self.assertEqual(bears["diff"]["value"], 0.0)
        self.assertEqual(bears["verdict"], "unclear")
        lost = forge.side_cards(self.result(record(wins=(0, 100), rows=({}, {}))), 0)
        fire = lost["rows"][0]
        self.assertEqual((fire["wr_not"]["value"], fire["wr_not"]["low"]), (0.0, 0.0))
        json.dumps([stats, lost], allow_nan=False)
        self.assertEqual(negative_zeros([stats, lost]), [])
        # 3,333 of 10,000 drawn against 1 of 3 not: -0.0000333 rounds to 0.0, not -0.0.
        rows = {"Grizzly Bears": [10000, 3333, 10000, 9000, 0, 20000, 0, 0]}
        tiny = forge.side_cards(self.result(record(games=10003, wins=(3334, 6669), first=(5000, 5003),
                                                   rows=(rows, {}), bad=0), played=10003), 0)
        self.assertEqual(tiny["rows"][2]["diff"]["value"], 0.0)
        self.assertEqual(negative_zeros(tiny), [])

    def test_batches_without_card_data_count_only_in_of(self):
        # An old batch (before the card log), this record, and a second record: "from 120 of 306 games".
        second = record(games=20, wins=(10, 10), first=(10, 10), bad=0,
                        rows=({"Grizzly Bears": [10, 5, 12, 10, 1, 20, 0, 0], "Fire": [4, 2, 4, 4, 0, 12, 1, 0]}, {}))
        result = self.result(None, record(), second)
        stats = forge.side_cards(result, 0)
        self.assertEqual((stats["games"], stats["bad"], stats["of"]), (120, 2, 306))
        rows = {row["name"]: row for row in stats["rows"]}
        self.assertEqual((rows["Grizzly Bears"]["drawn_games"], rows["Grizzly Bears"]["copies_drawn"],
                          rows["Grizzly Bears"]["wr_drawn"]["wins"], rows["Grizzly Bears"]["wr_not"]),
                         (80, 122, 55, rate(0.375, 0.2422, 0.5297, 40, 15)))
        self.assertEqual((rows["Fire // Ice"]["drawn_games"], rows["Fire // Ice"]["other_casts"],
                          rows["Fire // Ice"]["avg_turn"]), (4, 1, 3.0))
        # A result with only old batches has no card stats at all.
        self.assertIsNone(forge.side_cards(self.result(None, None), 0))

    def test_malformed_records_are_left_out_and_the_result_still_reads(self):
        def broken(change):
            rec = record()
            change(rec)
            return rec

        bad_records = [
            "cards", [record()], {}, broken(lambda r: r.update(v=r["v"] + 1)), broken(lambda r: r.pop("v")),
            broken(lambda r: r.update(v=float(r["v"]))), broken(lambda r: r.update(v=str(r["v"]))),
            broken(lambda r: r.update(games=-1)), broken(lambda r: r.update(games=True)),
            broken(lambda r: r.update(games=100.0)), broken(lambda r: r.pop("bad")),
            broken(lambda r: r.update(wins=[60])), broken(lambda r: r.update(wins=[60, 41])),
            broken(lambda r: r.update(first=[60, 41])), broken(lambda r: r.update(rows=ROWS0)),
            broken(lambda r: r.update(rows=[ROWS0])), broken(lambda r: r.update(rows=[ROWS0, []])),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 275, 0]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 275, 0, "3"]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, -1, 275, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [101, 50, 110, 90, 12, 275, 0, 3]})),  # > games
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 71, 110, 90, 12, 275, 0, 3]})),   # > drawn
            broken(lambda r: r["rows"][1].update({"Grizzly Bears": [45, 41, 50, 40, 1, 60, 0, 0]})),      # > wins
            # 60 wins in the 30 games without it:
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 0, 110, 90, 12, 275, 0, 3]})),
            broken(lambda r: r["rows"][1].update({"Grizzly Bears": {"drawn": 3}})),
            broken(lambda r: r.update(commander=[{}])),
            broken(lambda r: r.update(commander=[{"Grizzly Bears": [1, 0, 1]}, {}])),
            # More games than the batch played (102): "from 500 of 102 games".
            broken(lambda r: r.update(games=101)),
            broken(lambda r: r.update(games=500, wins=[300, 200], first=[250, 250], bad=0)),
            # A card's own tallies that don't fit together: cast, stuck or discarded copies that
            # weren't drawn (a share over 1), fewer copies than games drawn in, copies without a game
            # drawn in, more than MAX_PER_GAME copies a game, rounds or other casts.
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 111, 12, 275, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 111, 275, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 275, 0, 111]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 69, 60, 12, 275, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Fire": [0, 0, 1, 0, 0, 0, 0, 0]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 70001, 90, 12, 275, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 90001, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 10 ** 400, 0, 3]})),
            broken(lambda r: r["rows"][0].update({"Grizzly Bears": [70, 50, 110, 90, 12, 275, 100001, 3]})),
            # A commander's: fewer casts than games cast in, or too many, or too late a first cast.
            broken(lambda r: r.update(commander=[{"Grizzly Bears": [10, 5, 9, 30]}, {}])),
            broken(lambda r: r.update(commander=[{"Grizzly Bears": [10, 5, 10001, 30]}, {}])),
            broken(lambda r: r.update(commander=[{"Grizzly Bears": [10, 5, 12, 10001]}, {}])),
        ]
        good = forge.side_cards(self.result(record()), 0)
        self.results.mkdir()
        for n, rec in enumerate(bad_records):
            with self.subTest(n=n):
                alone = self.result(rec)
                self.assertIsNone(forge.side_cards(alone, 0))
                self.assertIsNone(forge.list_cards(sections(LIST), "constructed", [alone]))
                self.assertEqual(forge.saved._pooled_cards(alone, 0)["batches"], 0)
                # Alongside a good batch it's left out: only "of" (every counted game) sees its games.
                mixed = self.result(record(), rec)
                mixed["key"] = f"{n:064x}"
                self.assertEqual(forge.side_cards(mixed, 0), dict(good, of=204))
                # The file still reads as a result, and its page still shows.
                self.save(mixed)
                loaded = forge.load(mixed["key"], self.results)
                self.assertIsNotNone(loaded)
                self.assertEqual(forge.view(loaded, mixed["sides"][0]["card_sha"])["cards"][0], dict(good, of=204))

    def test_a_version_1_record_is_left_out_and_its_games_are_old(self):
        # Version 1 records (before 2026-10-01) counted a cast Forge's AI started and couldn't finish as a
        # cast. Their tallies are left out, but their games were played with a card log, so they're counted
        # in "old" (the page says so), not with the games played without one.
        old = dict(record(), v=1)
        self.assertEqual(forge.cardlog.RECORD_VERSION, 3)
        pooled = forge.saved._pooled_cards(self.result(old), 0)
        self.assertEqual((pooled["batches"], pooled["games"], pooled["bad"], pooled["old"], pooled["rows"]),
                         (0, 0, 0, 102, {}))
        # Only older card data: stats with no counted games (not None, which means no card log at all).
        stats = forge.side_cards(self.result(old), 0)
        self.assertEqual({k: v for k, v in stats.items() if k not in ("rows", "commander")},
                         {"games": 0, "bad": 0, "old": 102, "of": 102, "matchups": 0, "enough": False,
                          "min_games": 800, "min_split": 30, "basis": "drawn", "early_of": 0, "compared": 0,
                          "fdr": 0.1, "spread": 0.045, "spread_weight": 0.0})
        self.assertEqual([(row["drawn_games"], row["wr_drawn"], row["wr_not"], row["judged"]) for row in stats["rows"]],
                         [(0, None, None, False)] * len(EXPECTED0))
        json.dumps(stats, allow_nan=False)
        # Beside a batch of today's version, only that one is counted.
        second = record(games=20, wins=(10, 10), first=(10, 10), bad=0,
                        rows=({"Grizzly Bears": [10, 5, 12, 10, 1, 20, 0, 0]}, {}))
        stats = forge.side_cards(self.result(old, second, None, played=102), 0)
        self.assertEqual((stats["games"], stats["bad"], stats["old"], stats["of"], stats["matchups"]),
                         (20, 0, 102, 306, 1))
        bears = next(row for row in stats["rows"] if row["name"] == "Grizzly Bears")
        self.assertEqual((bears["drawn_games"], bears["copies_drawn"]), (10, 12))
        # The deck page's pooled numbers count them the same way, across results.
        pooled = forge.list_cards(sections(LIST), "constructed", [self.result(old)])
        self.assertEqual((pooled["games"], pooled["old"], pooled["of"], pooled["matchups"]), (0, 102, 102, 0))
        pooled = forge.list_cards(sections(LIST), "constructed",
                                  [self.result(old, key="a"), self.result(old, second, played=102, key="b")])
        self.assertEqual((pooled["games"], pooled["old"], pooled["of"], pooled["matchups"]), (20, 204, 306, 1))
        # The view of the matchup page has them too.
        self.assertEqual(forge.view(self.result(old), self.list["card_sha"])["cards"][0]["old"], 102)
        # A version 1 record that's malformed besides isn't old: it's left out like any malformed one. So
        # is a version 0 one, a newer one than today's, and a version 3 one with version 2's 8 numbers a card.
        for rec in (dict(record(games=500, wins=(300, 200), first=(250, 250), bad=0), v=1), dict(old, rows=[ROWS0]),
                    dict(record(), v=0), dict(record(), v=4), dict(record(), v=3), dict(record(), v=True)):
            with self.subTest(rec=(rec["v"], rec["games"], len(rec["rows"]))):
                self.assertIsNone(forge.side_cards(self.result(rec), 0))
                self.assertIsNone(forge.list_cards(sections(LIST), "constructed", [self.result(rec)]))
                self.assertEqual(forge.saved._pooled_cards(self.result(rec), 0)["old"], 0)

    def test_tallies_at_their_limits_count(self):
        # The most a record can say (record()'s 100 counted and 2 bad games are all the batch's 102):
        # MAX_PER_GAME copies drawn in each game drawn in, every one cast in round MAX_PER_GAME, stuck
        # and discarded too, and MAX_PER_GAME casts from elsewhere a game. No share is over 1.
        top = forge.saved.MAX_PER_GAME
        rows = {"Grizzly Bears": [70, 50, 70 * top, 70 * top, 70 * top, 70 * top * top, 100 * top, 70 * top]}
        stats = forge.side_cards(self.result(record(rows=(rows, {}))), 0)
        bears = stats["rows"][2]
        self.assertEqual((bears["name"], bears["cast_share"], bears["stuck_share"], bears["avg_turn"],
                          bears["other_casts"]), ("Grizzly Bears", 1.0, 1.0, float(top), 100 * top))
        # One copy a game and none cast: no average turn.
        rows = {"Grizzly Bears": [70, 50, 70, 0, 0, 0, 0, 0]}
        bears = forge.side_cards(self.result(record(rows=(rows, {}))), 0)["rows"][2]
        self.assertEqual((bears["copies_drawn"], bears["cast_share"], bears["avg_turn"]), (70, 0.0, None))

    def test_a_record_without_commander_counts(self):
        rec = record()
        del rec["commander"]
        self.assertEqual(forge.side_cards(self.result(rec), 0), forge.side_cards(self.result(record()), 0))

    def test_a_card_the_card_data_doesnt_know_is_a_nonland(self):
        listed = {"Commander": [], "Main": [[2, "Totally Fake Card"], [20, "Forest"], [1, "Grizzly Bears"]]}
        stats = forge.side_cards(self.result(record(), cards_a=listed), 0)
        self.assertEqual([(row["name"], row["land"]) for row in stats["rows"]],
                         [("Grizzly Bears", False), ("Totally Fake Card", None), ("Forest", True)])

    def test_a_side_without_a_card_list_uses_its_dck(self):
        result = self.result(record())
        result["sides"][0]["cards"] = None
        result["sides"][0]["dck"] = self.list["dck"]
        rows = forge.side_cards(result, 0)["rows"]
        # Only the .dck names are known then.
        self.assertEqual([row["name"] for row in rows],
                         ["Fire", "Giant Growth", "Grizzly Bears", "Lightning Bolt", "Murderous Rider", "Forest",
                          "Mountain"])
        self.assertEqual(rows[4]["drawn_games"], 10)


# ============================================================ Commander

class CommanderTests(CardStatsCase):

    GISA = {"Commander": [[1, "Ghoulcaller Gisa"]], "Main": [[4, "Grizzly Bears"], [10, "Swamp"]]}

    def test_the_commander_has_its_own_rows(self):
        # Gisa was cast in 40 of 100 games and side 0 won 30 of those; it won 20 of the other 60: se
        # 0.092096 (from 30.5/41 and 20.5/61), p 6e-6. Only Grizzly Bears (30 of 60 against 20 of 40,
        # se 0.102062) counts toward the spread, a commander doesn't: 0.0445, so shrunk is 0.416667 *
        # 0.0445^2 / (0.0445^2 + 0.092096^2) = 0.079.
        rec = record(wins=(50, 50), rows=({"Grizzly Bears": [60, 30, 70, 60, 2, 150, 0, 0]}, {}),
                     commander=({"Ghoulcaller Gisa": [40, 30, 55, 160]}, {}))
        result = self.result(rec, cards_a=self.GISA, kinds=("commander", "commander"))
        stats = forge.side_cards(result, 0)
        self.assertEqual(stats["commander"], [
            {"name": "Ghoulcaller Gisa", "cast_games": 40, "cast_share": 0.4, "casts": 55, "avg_first_turn": 4.0,
             "wr_cast": rate(0.75, 0.5981, 0.8581, 40, 30), "wr_not_cast": rate(0.3333, 0.2273, 0.4594, 60, 20),
             "diff": diff(0.4167, 0.2192, 0.5681), "shrunk": 0.079, "p": 0.0, "judged": True, "discovery": True,
             "verdict": "more"}])
        self.assertEqual([row["name"] for row in stats["rows"]], ["Grizzly Bears", "Swamp"])
        # A commander never cast has a row of zeros.
        rec["commander"] = [{}, {}]
        never = forge.side_cards(self.result(rec, cards_a=self.GISA, kinds=("commander", "commander")), 0)
        self.assertEqual(never["commander"], [
            {"name": "Ghoulcaller Gisa", "cast_games": 0, "cast_share": 0.0, "casts": 0, "avg_first_turn": None,
             "wr_cast": None, "wr_not_cast": rate(0.5, 0.4038, 0.5962, 100, 50), "diff": None, "shrunk": None,
             "p": None, "judged": False, "discovery": None, "verdict": None}])

    def test_a_commanders_tallies_at_their_limits_count(self):
        # MAX_PER_GAME casts in each game it was cast in, the first in round MAX_PER_GAME; then one
        # cast a game.
        top = forge.saved.MAX_PER_GAME
        for numbers, casts, first_turn in (([40, 30, 40 * top, 40 * top], 40 * top, float(top)),
                                           ([40, 30, 40, 40], 40, 1.0)):
            rec = record(wins=(50, 50), rows=({}, {}), commander=({"Ghoulcaller Gisa": numbers}, {}))
            stats = forge.side_cards(self.result(rec, cards_a=self.GISA, kinds=("commander", "commander")), 0)
            self.assertEqual((stats["commander"][0]["casts"], stats["commander"][0]["avg_first_turn"]),
                             (casts, first_turn))

    def test_a_constructed_list_plays_its_commander_section_in_the_main_deck(self):
        rec = record(rows=({"Ghoulcaller Gisa": [20, 10, 20, 15, 1, 60, 0, 0]}, {}))
        stats = forge.side_cards(self.result(rec, cards_a=self.GISA), 0)
        self.assertEqual(stats["commander"], [])
        self.assertEqual([(row["name"], row["drawn_games"]) for row in stats["rows"]],
                         [("Ghoulcaller Gisa", 20), ("Grizzly Bears", 0), ("Swamp", 0)])


# ============================================================ a list over all its matchups

class ListTests(CardStatsCase):

    def test_a_list_pools_every_result_that_played_it(self):
        # This list as side 0 (102 games, 100 with card data), as side 1 of another (its tallies in
        # the record's side 1), in an old result without card data (50 games: only "of"), and
        # another list's result, which adds nothing.
        first = self.result(record())
        second = self.result(record(games=40, wins=(25, 15), first=(20, 20), bad=0,
                                    rows=({}, {"Lightning Bolt": [20, 5, 20, 18, 0, 30, 0, 0]})), key="d")
        second["sides"] = second["sides"][::-1]
        second["sides"][1]["card_sha"] = self.list["card_sha"]
        old = self.result(None, played=50, key="e")
        other = self.result(record(), key="f", sha="0" * 64)
        stats = forge.list_cards(sections(LIST), "constructed", [first, second, old, other])
        self.assertEqual((stats["games"], stats["bad"], stats["of"], stats["matchups"], stats["enough"]),
                         (140, 2, 102 + 102 + 50, 2, False))
        bolt = next(row for row in stats["rows"] if row["name"] == "Lightning Bolt")
        # 10 of 40 drawn (first) + 5 of 20 (second); the list won 60 + 15 = 75 of 140, so 60 of 80 not drawn.
        self.assertEqual((bolt["drawn_games"], bolt["wr_drawn"]["wins"], bolt["copies_drawn"], bolt["cast"]),
                         (60, 15, 60, 54))
        self.assertEqual((bolt["wr_not"]["games"], bolt["wr_not"]["wins"]), (80, 60))
        self.assertEqual(bolt["avg_turn"], round(102 / 54, 1))
        self.assertEqual([row["name"] for row in stats["rows"]], [row["name"] for row in EXPECTED0])
        self.assertEqual(stats["rows"][2]["qty"], 4)        # two printings of Grizzly Bears, one row
        # The same result alone gives side_cards' numbers, with matchups 1.
        self.assertEqual(forge.list_cards(sections(LIST), "constructed", [first]), forge.side_cards(first, 0))

    def test_a_mirror_counts_each_side_once(self):
        mirror = self.result(record(rows=(ROWS0, {"Grizzly Bears": [30, 10, 35, 30, 1, 60, 0, 0]})))
        mirror["sides"][1] = copy.deepcopy(mirror["sides"][0])
        stats = forge.list_cards(sections(LIST), "constructed", [mirror])
        # Both sides' 100 games, 60 + 40 wins; Grizzly Bears drawn in 70 + 30 games, won 50 + 10 of them.
        self.assertEqual((stats["games"], stats["bad"], stats["of"], stats["matchups"]), (200, 4, 204, 1))
        bears = stats["rows"][2]
        self.assertEqual((bears["name"], bears["drawn_games"], bears["copies_drawn"], bears["wr_drawn"]["wins"],
                          bears["wr_not"]["games"], bears["wr_not"]["wins"]),
                         ("Grizzly Bears", 100, 145, 60, 100, 40))

    def test_no_card_data_is_none(self):
        self.assertIsNone(forge.list_cards(sections(LIST), "constructed", []))
        self.assertIsNone(forge.list_cards(sections(LIST), "constructed", [self.result(None)]))
        # Card data of another list only.
        self.assertIsNone(forge.list_cards(sections(LIST), "constructed", [self.result(record(), sha="0" * 64)]))
        self.assertIsNone(forge.list_cards(sections(LIST), "constructed", results_dir=self.results))

    def test_the_saved_results(self):
        self.save(self.result(record()), self.result(None, key="d"), self.result(key="e", played=0))
        stats = forge.list_cards(sections(LIST), "constructed", results_dir=self.results)
        self.assertEqual((stats["games"], stats["of"], stats["matchups"]), (100, 204, 1))
        self.assertEqual(stats["rows"], EXPECTED0)


# ============================================================ the matchup page and the AI limits

class ViewAndAiTests(CardStatsCase):

    def test_the_matchup_page_has_each_sides_cards(self):
        result = self.result(record())
        result["runs"][0].update(card_log=True)
        result["runs"].append(dict(result["runs"][0], card_log=False, card_log_problem="Java has no javac."))
        a = forge.view(result, self.list["card_sha"])
        self.assertEqual(a["cards"], [forge.side_cards(result, 0), forge.side_cards(result, 1)])
        self.assertEqual(a["cards"][0]["rows"], EXPECTED0)
        b = forge.view(result, "b" * 64)
        self.assertEqual(b["cards"], a["cards"][::-1])
        self.assertEqual([(r["card_log"], r["card_log_problem"]) for r in a["runs"]],
                         [(True, None), (False, "Java has no javac.")])
        json.dumps([a, b], allow_nan=False)

    def test_old_results_are_shown_as_before(self):
        # Card data adds "cards" and nothing else: without it, every other number is the same.
        result = self.result(record(), None)
        old = copy.deepcopy(result)
        del old["batches"][0]["cards"]
        old_view, new_view = forge.view(old, self.list["card_sha"]), forge.view(result, self.list["card_sha"])
        self.assertEqual(old_view["cards"], [None, None])
        self.assertEqual([r["card_log"] for r in old_view["runs"]], [None])      # run before the card log
        self.assertEqual(dict(old_view, cards=None), dict(new_view, cards=None))
        # Nothing was cast (test_forge.stored's casts), so every nonland is never cast in 204 games.
        # Only 102 of them have card data, so the never-cast cards don't say how often they were drawn:
        # "drawn in 70 games" would be of 102, not of the 204 they were never cast in.
        for side in (0, 1):
            self.assertEqual(forge.side_ai(result, side), forge.side_ai(old, side))
        # When every batch has card data, it only adds how often each was drawn.
        result = self.result(record(), record())
        old = copy.deepcopy(result)
        for batch in old["batches"]:
            del batch["cards"]
        for side in (0, 1):
            new = forge.side_ai(result, side)
            self.assertTrue(new["cannot_play"])
            self.assertTrue(all("drawn_games" in c for c in new["cannot_play"]))
            before = [{k: v for k, v in c.items() if k != "drawn_games"} for c in new["cannot_play"]]
            self.assertEqual(forge.side_ai(old, side), dict(new, cannot_play=before))
        growth = next(c for c in forge.side_ai(result, 0)["cannot_play"] if c["name"] == "Giant Growth")
        self.assertEqual(growth, {"name": "Giant Growth", "qty": 1, "why": "never_cast", "drawn_games": 100})
        self.assertIsNone(forge.list_cards(sections(LIST), "constructed", [old]))

    def test_card_stats_that_fail_leave_the_rest_of_the_matchup_page(self):
        result = self.result(record())
        whole = forge.view(result, self.list["card_sha"])
        with mock.patch.object(forge.cardstats, "card_rows", side_effect=ValueError("made up")), \
                mock.patch.object(forge.common, "_log") as log:
            got = forge.view(result, self.list["card_sha"])
        self.assertEqual(got["cards"], [None, None])
        self.assertEqual(dict(got, cards=None), dict(whole, cards=None))
        self.assertEqual(log.call_count, 2)         # once for each side, with its traceback
        self.assertIn(f"side 0 of the matchup result {'c' * 12} can't be worked out", log.call_args_list[0].args[0])
        self.assertIn("ValueError: made up", log.call_args_list[0].args[0])

    AI_LIST = """Deck
4 Grizzly Bears
1 Fiery Annihilation
1 Giant Growth
20 Forest
"""

    def ai_result(self, rec, played=102, key="c"):
        """A result of AI_LIST (side 0) in which only Grizzly Bears was cast."""
        e = entry(self.AI_LIST, "casual/ai")
        result = self.result(rec, played=played, cards_a=e["cards"], key=key, sha=e["card_sha"])
        for batch in result["batches"]:
            batch["casts"] = [{"Grizzly Bears": [9, 5]}, {}]
        return result

    def test_never_cast_cards_say_how_often_they_were_drawn(self):
        # Every batch has card data: 100 counted games and 2 whose card log failed its checks (not
        # in drawn_games, but no game was played without the card log).
        rec = record(rows=({"Fiery Annihilation": [54, 30, 60, 0, 40, 0, 0, 20], "Grizzly Bears": [70, 50, 110, 90,
                                                                                                   12, 275, 0, 3]}, {}))
        limits = forge.side_ai(self.ai_result(rec), 0)
        # Giant Growth has no tallies: drawn in 0 of the card log's games (never cast either way).
        self.assertEqual(limits["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast",
                                                  "drawn_games": 54},
                                                 {"name": "Giant Growth", "qty": 1, "why": "never_cast",
                                                  "drawn_games": 0}])
        self.assertEqual(limits["games"], 102)
        # Without card data, or with none that passed its checks, the entries are as before.
        for no_data in (None, record(games=0, wins=(0, 0), first=(0, 0), rows=({}, {}), bad=102)):
            limits = forge.side_ai(self.ai_result(no_data), 0)
            self.assertEqual([set(c) for c in limits["cannot_play"]], [{"name", "qty", "why"}] * 2)
        # The rule for listing a card doesn't change: under MIN_GAMES_NEVER_CAST games, nothing.
        with mock.patch.object(forge.ai, "MIN_GAMES_NEVER_CAST", 103):
            self.assertEqual(forge.side_ai(self.ai_result(rec), 0)["cannot_play"], [])

    def test_the_deck_page_pools_drawn_games_over_the_same_results(self):
        rec = record(rows=({"Fiery Annihilation": [54, 30, 60, 0, 40, 0, 0, 20]}, {}))
        more = record(games=50, wins=(25, 25), first=(25, 25), bad=0,
                      rows=({"Fiery Annihilation": [6, 3, 6, 0, 6, 0, 0, 0]}, {}))
        results = [self.ai_result(rec), self.ai_result(more, played=50, key="d")]
        limits = forge.ai_limits(sections(self.AI_LIST), "constructed", results)
        self.assertEqual(limits["games"], 102 + 50)
        self.assertEqual([(c["name"], c.get("drawn_games")) for c in limits["cannot_play"]],
                         [("Fiery Annihilation", 60), ("Giant Growth", 0)])
        self.save(*results)
        self.assertEqual(forge.list_ai(sections(self.AI_LIST), "constructed", self.results)["cannot_play"],
                         limits["cannot_play"])
        # A result played before the card log: 60 would be of 152 of the 1,152 games, so it isn't said.
        old = self.ai_result(None, played=1000, key="e")
        limits = forge.ai_limits(sections(self.AI_LIST), "constructed", results + [old])
        self.assertEqual(limits["games"], 102 + 50 + 1000)
        self.assertEqual([set(c) for c in limits["cannot_play"]], [{"name", "qty", "why"}] * 2)
        self.save(old)
        self.assertEqual(forge.list_ai(sections(self.AI_LIST), "constructed", self.results)["cannot_play"],
                         limits["cannot_play"])
        # The same goes for a batch whose record is malformed, inside one result.
        broken = self.ai_result(rec)
        broken["batches"].append(dict(copy.deepcopy(broken["batches"][0]), n=1, seed=2,
                                      cards=record(games=103, rows=({}, {}))))
        self.assertEqual([set(c) for c in forge.side_ai(broken, 0)["cannot_play"]], [{"name", "qty", "why"}] * 2)

    def test_a_commander_never_cast_has_no_drawn_games(self):
        bears = {"Commander": [[1, "Grizzly Bears"]], "Main": [[1, "Giant Growth"], [20, "Forest"]]}
        rec = record(rows=({"Giant Growth": [12, 6, 12, 0, 12, 0, 0, 0]}, {}))
        result = self.result(rec, cards_a=bears, kinds=("commander", "commander"))
        limits = forge.side_ai(result, 0)
        self.assertEqual(limits["cannot_play"], [{"name": "Grizzly Bears", "qty": 1, "why": "never_cast"},
                                                 {"name": "Giant Growth", "qty": 1, "why": "never_cast",
                                                  "drawn_games": 12}])
        self.assertTrue(limits["commander_unplayable"])


if __name__ == "__main__":
    unittest.main()
