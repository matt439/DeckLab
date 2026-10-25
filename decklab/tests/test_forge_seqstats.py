"""Tests for the sequential statistics of simulation wave 3 (forge.seqstats,
forge-trial/sim-wave3-contract.md section 7): when an "assess" or "who's ahead" run stops, the
anytime-valid range, paired differences between a deck and a changed version of it, the field
average, the Bradley-Terry rating with its residual flags, APT and Spearman.

The formulas are checked on hand-worked cases: each expected number is worked out in the test
from the contract's formula, written out again, not by calling the function under test. The
Monte Carlo checks are seeded, so they give the same answer every run, and each takes a few
seconds at most; they simulate counts rather than game dicts, through the module's private
counting helpers (_decided, _assess, _half_width, _anytime, _agresti_min), which the public
functions call once they've counted the games.

No Forge or fake Forge runs. Run from the repo root: python -m unittest decklab.tests.test_forge_seqstats
"""
import math
import random
import unittest

from decklab.lib import config, forge

S = forge.seqstats


def games_of(play, draw, p=0):
    """Game dicts for side p: play and draw are (p's wins, the other's wins, draws) when p went
    first and when the other side did. Numbered from 0 in that order."""
    out = []
    for first, (wins, losses, draws) in ((p, play), (1 - p, draw)):
        for w, r, k in ((p, "win", wins), (1 - p, "win", losses), (None, "draw", draws)):
            out += [{"w": w, "first": first, "r": r, "rounds": 8, "turns": 15, "ms": 100} for _ in range(k)]
    for g, game in enumerate(out):
        game["g"] = g
    return out


def wilson(wins, n, z=1.96):
    """Wilson's range, worked out in its other form: (2x + z² ∓ z·sqrt(z² + 4x(n − x)/n)) / (2(n + z²))."""
    root = z * math.sqrt(z * z + 4 * wins * (n - wins) / n)
    return (2 * wins + z * z - root) / (2 * (n + z * z)), (2 * wins + z * z + root) / (2 * (n + z * z))


def balanced(w1, n1, w2, n2):
    """views.balanced worked out again: the mean of the two rates, MOVER over the Wilson ranges."""
    p1, p2 = w1 / n1, w2 / n2
    (l1, u1), (l2, u2) = wilson(w1, n1), wilson(w2, n2)
    v = (p1 + p2) / 2
    return v, max(0.0, v - 0.5 * math.hypot(p1 - l1, p2 - l2)), min(1.0, v + 0.5 * math.hypot(u1 - p1, u2 - p2))


class ConstantsTests(unittest.TestCase):
    def test_the_margins_match_the_page_and_the_config(self):
        self.assertEqual(S.EQUIV, forge.views.ABOUT_EVEN)
        self.assertEqual(S.VARIANT_EQUIV_FIELD, config.DEFAULTS["forge_variant_margin"])
        self.assertEqual(S.VARIANT_EQUIV_ONE, config.DEFAULTS["forge_variant_margin_one"])
        self.assertEqual(S.PAIRED_LOOKS, S.HP_LOOKS)
        self.assertEqual(S.CAP, S.HP_LOOKS[-1])


class AssessTests(unittest.TestCase):
    def test_estimate_before_any_game(self):
        # p̃ = 1/2 in both strata and f = 1/2: v = (0.25/0.5 + 0.25/0.5)/4 = 0.25, and
        # 1.959964² · 0.25 / 0.03² = 1067.07, rounded up to a multiple of 25.
        self.assertEqual(S.assess_estimate([], 0), 1075)

    def test_estimate_uses_the_shrunk_rates_and_stays_within_the_pilot_and_the_cap(self):
        games = games_of((60, 40, 0), (40, 60, 0))        # 0.6 on the play, 0.4 on the draw
        p1, p2 = 61 / 102, 41 / 102
        v = (p1 * (1 - p1) / 0.5 + p2 * (1 - p2) / 0.5) / 4
        self.assertEqual(S.assess_estimate(games, 0), math.ceil(1.959964 ** 2 * v / 0.03 ** 2 / 25) * 25)
        # f is kept within 0.2-0.8 however lopsided the starters were.
        lopsided = games_of((90, 90, 0), (5, 5, 0))
        p1, p2 = 91 / 182, 6 / 12
        v = (p1 * (1 - p1) / 0.8 + p2 * (1 - p2) / 0.2) / 4
        self.assertEqual(S.assess_estimate(lopsided, 0), math.ceil(1.959964 ** 2 * v / 0.03 ** 2 / 25) * 25)
        self.assertEqual(S.assess_estimate(games_of((200, 0, 0), (200, 0, 0)), 0), S.ASSESS_PILOT)

    def test_pilot(self):
        self.assertEqual(S.assess_next([], 0), (400, "pilot"))
        self.assertEqual(S.assess_next(games_of((75, 75, 0), (0, 0, 0)), 0), (250, "pilot"))
        self.assertEqual(S.assess_next([], 0, cap=300), (300, "pilot"))

    def test_plan_from_the_range_actually_judged(self):
        games = games_of((110, 90, 0), (95, 105, 0))       # 400 games
        v, low, high = balanced(110, 200, 95, 200)
        hw = max(v - low, high - v)
        total = math.ceil(400 * (hw / 0.03) ** 2 * 1.03 / 25) * 25
        self.assertEqual(S.assess_next(games, 0), (total - 400, "plan"))
        self.assertEqual(S.assess_next(games, 1)[1], "plan")

    def test_the_plan_plays_at_least_100_more_games(self):
        # 1,050 even games: the half-width is just over 3 points, so n·(hw/h)²·1.03 is under n + 100.
        games = games_of((263, 262, 0), (262, 263, 0))
        v, low, high = balanced(263, 525, 262, 525)
        hw = max(v - low, high - v)
        self.assertGreater(hw, 0.03)
        self.assertLess(1050 * (hw / 0.03) ** 2 * 1.03, 1150)
        self.assertEqual(S.assess_next(games, 0, plan_done=False), (100, "plan"))
        # After the plan, hw is within h + 0.002: no top-up.
        self.assertEqual(S.assess_next(games, 0, plan_done=True), (0, "capped at plan"))
        self.assertEqual(S.assess_next(games, 0), (0, "capped at plan"))      # more than the pilot: plan played

    def test_top_up_once(self):
        games = games_of((234, 216, 0), (216, 234, 0))     # 900 games, hw about 3.3 points
        v, low, high = balanced(234, 450, 216, 450)
        hw = max(v - low, high - v)
        self.assertGreater(hw, 0.032)
        total = max(1000, math.ceil(900 * (hw / 0.03) ** 2 * 1.03 / 25) * 25)
        self.assertEqual(S.assess_next(games, 0, plan_done=True), (total - 900, "top-up"))
        self.assertEqual(S.assess_next(games, 0), (total - 900, "top-up"))     # more than the pilot: plan played
        self.assertEqual(S.assess_next(games, 0, topups_done=1), (0, "capped at plan"))
        self.assertEqual(S.assess_next(games, 0, plan_done=False), (total - 900, "plan"))

    def test_precise_and_capped(self):
        self.assertEqual(S.assess_next(games_of((800, 800, 0), (800, 800, 0)), 0), (0, "precise"))
        self.assertEqual(S.assess_next(games_of((200, 100, 0), (100, 200, 0)), 0, cap=600), (0, "capped"))
        # The plan never goes past the cap.
        games = games_of((110, 90, 0), (95, 105, 0))
        self.assertEqual(S.assess_next(games, 0, cap=700), (300, "plan"))

    def test_a_side_that_never_went_first_is_judged_on_its_raw_share(self):
        games = games_of((0, 0, 0), (200, 200, 0))
        low, high = wilson(200, 400)
        hw = max(0.5 - low, high - 0.5)
        total = math.ceil(400 * (hw / 0.03) ** 2 * 1.03 / 25) * 25
        self.assertEqual(S.assess_next(games, 0), (total - 400, "plan"))


class DecidedShareTests(unittest.TestCase):
    def test_200_0_in_both_strata_has_a_finite_z(self):
        share = S.decided_share(games_of((200, 0, 0), (200, 0, 0)), 0)
        t = 200.5 / 201
        se = math.sqrt(2 * t * (1 - t) / 200) / 2
        self.assertEqual((share["pi"], share["a"], share["b"], share["d"]), (1.0, [200, 200], [0, 0], [200, 200]))
        self.assertAlmostEqual(share["se"], se, places=12)
        self.assertAlmostEqual(share["z"], 0.5 / se, places=8)
        self.assertTrue(math.isfinite(share["z"]))

    def test_draws_are_left_out_and_each_side_is_its_own_point_of_view(self):
        games = games_of((30, 10, 5), (20, 25, 10))
        share = S.decided_share(games, 0)
        pi = (30 / 40 + 20 / 45) / 2
        t1, t2 = 30.5 / 41, 20.5 / 46
        se = math.sqrt(t1 * (1 - t1) / 40 + t2 * (1 - t2) / 45) / 2
        self.assertAlmostEqual(share["pi"], pi, places=12)
        self.assertAlmostEqual(share["se"], se, places=12)
        self.assertAlmostEqual(share["z"], (pi - 0.5) / se, places=10)
        other = S.decided_share(games, 1)
        self.assertEqual((other["a"], other["b"]), ([25, 10], [20, 30]))      # side 1's play stratum first
        self.assertAlmostEqual(other["pi"], (25 / 45 + 10 / 40) / 2, places=12)

    def test_undefined_without_decided_games_in_a_stratum(self):
        share = S.decided_share(games_of((10, 5, 0), (0, 0, 7)), 0)
        self.assertEqual((share["pi"], share["se"], share["z"]), (None, None, None))
        self.assertEqual(share["d"], [15, 0])
        games = games_of((10, 5, 0), (6, 4, 0)) + [{"g": 99, "w": 0, "first": None, "r": "win"}]
        self.assertEqual(S.decided_share(games, 0)["a"], [10, 6])           # an unknown starter is in neither


class LookTests(unittest.TestCase):
    def test_last_look(self):
        self.assertEqual(S.last_look(), 3200)
        self.assertEqual(S.last_look(1600), 1600)
        self.assertEqual(S.last_look(1000), 800)
        self.assertIsNone(S.last_look(300))
        self.assertEqual(S.last_look(None), 3200)
        self.assertEqual(S.last_look(500, S.FIELD_PAIRED_LOOKS), 400)

    def test_a_lopsided_pair_is_ahead_at_400(self):
        result = S.look(games_of((200, 0, 0), (200, 0, 0)), 0, 400)
        self.assertEqual((result["look"], result["bound"], result["decision"], result["side"]),
                         (400, S.HP_INTERIM, "ahead", 0))
        result = S.look(games_of((0, 200, 0), (0, 200, 0)), 0, 400)
        self.assertEqual((result["decision"], result["side"]), ("ahead", 1))

    def test_the_bounds(self):
        games = games_of((110, 90, 0), (100, 100, 0))
        self.assertEqual(S.look(games, 0, 400)["bound"], S.HP_INTERIM)
        self.assertEqual(S.look(games, 0, 3200)["bound"], S.HP_FINAL)
        self.assertEqual(S.look(games, 0, 1600, max_games=1600)["bound"], S.HP_FINAL)
        self.assertEqual(S.look(games, 0, 1600, max_games=2000)["bound"], S.HP_FINAL)
        self.assertEqual(S.look(games, 0, 800, max_games=1600)["bound"], S.HP_INTERIM)
        self.assertEqual(S.look(games, 0, 3200, stopped=True)["bound"], S.HP_INTERIM)

    def test_continue_then_not_settled_at_the_last_look(self):
        games = games_of((110, 90, 0), (100, 100, 0))       # z about 1
        result = S.look(games, 0, 400)
        self.assertEqual((result["decision"], result["side"]), ("continue", None))
        rates = forge.views._winrate(games, 0)["winrate"]
        self.assertEqual((result["low"], result["high"]), (rates["low"], rates["high"]))
        self.assertEqual(result["basis"], "decided")
        self.assertEqual(S.look(games, 0, 400, max_games=400)["decision"], "not_settled")
        self.assertEqual(S.look(games, 0, 400, stopped=True)["decision"], "not_settled_stopped")

    def test_about_even_and_slightly_ahead(self):
        even = S.look(games_of((400, 400, 0), (400, 400, 0)), 0, 1600)
        self.assertEqual((even["decision"], even["side"]), ("about_even", None))
        # 53 % of 3,200 decided games: the range (51.3-54.7 %) leaves out 50 % and stays within 5
        # points of it.
        slight = S.look(games_of((848, 752, 0), (848, 752, 0)), 0, 3200)
        self.assertGreaterEqual(slight["z"], S.HP_FINAL)
        self.assertEqual((slight["decision"], slight["side"]), ("slightly_ahead", 0))

    def test_z_over_the_bound_with_the_page_not_settled_is_not_settled(self):
        # Half the games drawn: z on the decided games passes 2.008 at 3,200, but the page's lead
        # (the comparison range, draws counted against both) doesn't leave out 0.
        games = games_of((421, 379, 800), (421, 379, 800))
        lead = forge.views._lead(games, 0, forge.views._winrate(games, 0)["winrate"],
                                 forge.views._comparison(games, 0))
        self.assertEqual(lead["verdict"], "not_settled")
        result = S.look(games, 0, 3200)
        self.assertGreaterEqual(result["z"], S.HP_FINAL)
        self.assertEqual((result["decision"], result["side"]), ("not_settled", None))
        self.assertEqual(result["basis"], "comparison")                 # judged on the comparison range

    def test_a_stopped_look_needs_3_and_the_99_73_range(self):
        # z about 2.8: past the final bound, short of 3.0.
        games = games_of((180, 145, 0), (180, 145, 0))
        share = S.decided_share(games, 0)
        self.assertTrue(S.HP_FINAL < share["z"] < S.HP_INTERIM)
        result = S.look(games, 0, 650, stopped=True)
        self.assertEqual((result["decision"], result["side"], result["bound"]), ("not_settled_stopped", None, 3.0))
        self.assertEqual(result["basis"], "decided_share")
        self.assertAlmostEqual(result["low"], share["pi"] - 3.0 * share["se"], places=12)
        self.assertAlmostEqual(result["high"], share["pi"] + 3.0 * share["se"], places=12)
        self.assertEqual(S.look(games_of((300, 200, 0), (300, 200, 0)), 0, 1000, stopped=True)["decision"], "ahead")
        # About even only when π̂ ± 3·SE stays within 45-55 %: 2,400 even games do (3·SE = 3.1
        # points), 600 don't (6.1 points).
        self.assertEqual(S.look(games_of((600, 600, 0), (600, 600, 0)), 0, 2400, stopped=True)["decision"],
                         "about_even")
        self.assertEqual(S.look(games_of((150, 150, 0), (150, 150, 0)), 0, 600, stopped=True)["decision"],
                         "not_settled_stopped")

    def test_no_z_means_no_exit(self):
        games = games_of((10, 5, 0), (0, 0, 385))
        self.assertEqual(S.look(games, 0, 400)["decision"], "continue")
        self.assertEqual(S.look(games, 0, 3200)["decision"], "not_settled")
        self.assertIsNone(S.look(games, 0, 400, stopped=True)["low"])

    def test_ahead_next(self):
        self.assertEqual(S.ahead_next([], 0), (400, 400))
        self.assertEqual(S.ahead_next(games_of((200, 200, 0), (200, 200, 0)), 0), (800, 1600))   # 800 played
        self.assertEqual(S.ahead_next(games_of((100, 100, 0), (100, 100, 0)), 0), (400, 800))
        self.assertEqual(S.ahead_next(games_of((250, 250, 0), (250, 250, 0)), 0), (600, 1600))
        self.assertEqual(S.ahead_next(games_of((100, 100, 0), (100, 100, 0)), 0, max_games=400), (0, None))
        self.assertEqual(S.ahead_next(games_of((800, 800, 0), (800, 800, 0)), 0), (0, None))
        self.assertEqual(S.ahead_next(games_of((10, 10, 0), (10, 10, 0)), 0, max_games=1000), (360, 400))


class AnytimeTests(unittest.TestCase):
    def test_live_counts_include_non_wins(self):
        self.assertIsNone(S.anytime_counts(0, 0))
        games = games_of((150, 50, 10), (120, 70, 0))
        for side, wins in ((0, 270), (1, 120)):
            with self.subTest(side=side):
                self.assertEqual(S.anytime_counts(wins, 400), S.anytime_range(games, side))
                self.assertAlmostEqual(S.anytime_counts(wins, 400)[0], wins / 400)

    def test_half_widths(self):
        for n, points in ((400, 8.2), (800, 5.5), (1600, 3.8), (3200, 2.7)):
            value, low, high = S.anytime_range(games_of((n // 4, n // 4, 0), (n // 4, n // 4, 0)), 0)
            v = n / 4
            half = math.sqrt((v + 50.4) * math.log((v + 50.4) / (50.4 * 0.05 ** 2))) / n
            self.assertEqual(value, 0.5)
            self.assertAlmostEqual(high - value, half, places=12)
            self.assertAlmostEqual(100 * half, points, delta=0.05)

    def test_raw_share_and_limits(self):
        self.assertIsNone(S.anytime_range([], 0))
        value, low, high = S.anytime_range(games_of((150, 50, 10), (120, 70, 0)), 0)
        self.assertAlmostEqual(value, 270 / 400)
        value, low, high = S.anytime_range(games_of((200, 0, 0), (200, 0, 0)), 0)
        self.assertEqual((value, high), (1.0, 1.0))


def arms(rows):
    """(base games, variant games) from rows (g, base first, base winner, variant first, variant
    winner), the base deck on side 0 of its result and the variant on side 1 of its own."""
    base, variant = [], []
    for g, bf, bw, vf, vw in rows:
        base.append({"g": g, "first": bf, "w": bw, "r": "win" if bw is not None else "draw", "rounds": 7,
                     "turns": 13})
        variant.append({"g": g, "first": vf, "w": vw, "r": "win" if vw is not None else "draw", "rounds": 7,
                        "turns": 13})
    return base, variant


def strata_rows(play, draw, start=0):
    """Paired rows whose counts are play and draw, each {(y_variant, y_base): games}, with the base
    on side 0 and the variant on side 1 (each deck starting in the play stratum)."""
    rows, g = [], start
    for started, cells in ((True, play), (False, draw)):
        for (yv, yb), k in sorted(cells.items()):
            for _ in range(k):
                rows.append((g, 0 if started else 1, 0 if yb else 1, 1 if started else 0, 1 if yv else 0))
                g += 1
    return rows


class PairedTests(unittest.TestCase):
    def test_paired_games_match_by_g_and_leave_out_starter_mismatches(self):
        base, variant = arms([(0, 0, 0, 1, 1), (1, 1, 1, 0, 0), (2, 0, 0, 0, 1), (3, 0, None, 1, 1)])
        base.append({"g": 7, "first": 0, "w": 0})
        variant.append({"g": 8, "first": 1, "w": 1})
        variant[1]["turns"] = 14
        matched = S.paired_games(base, variant, 0, 1)
        self.assertEqual((matched["common"], matched["starter_mismatch"]), (4, 1))
        self.assertEqual([(q["g"], q["y_base"], q["y_variant"], q["variant_first"], q["same"])
                          for q in matched["pairs"]],
                         [(0, 1, 1, True, True), (1, 0, 0, False, False), (3, 0, 1, True, False)])

    def test_the_agresti_min_difference_worked_by_hand(self):
        # play: 10 pairs, b = 3 (the variant won, the base didn't), c = 1; draw: 10 pairs, b = 2, c = 2.
        play = {(1, 0): 3, (0, 1): 1, (1, 1): 4, (0, 0): 2}
        draw = {(1, 0): 2, (0, 1): 2, (1, 1): 1, (0, 0): 5}
        diff = S.paired_diff(*arms(strata_rows(play, draw)), 0, 1)
        d_play, v_play = (3.5 - 1.5) / 12, ((3.5 + 1.5) - 2.0 ** 2 / 12) / 12 ** 2
        d_draw, v_draw = 0.0, (2.5 + 2.5) / 12 ** 2
        center, se = (d_play + d_draw) / 2, math.sqrt(v_play + v_draw) / 2
        self.assertAlmostEqual(diff["delta"], ((3 - 1) / 10 + 0) / 2, places=12)
        self.assertAlmostEqual(diff["low"], center - 1.959964 * se, places=12)
        self.assertAlmostEqual(diff["high"], center + 1.959964 * se, places=12)
        self.assertAlmostEqual(diff["z"], center / se, places=12)
        self.assertAlmostEqual(diff["var"], se * se, places=14)
        self.assertEqual(diff["n"], 20)
        self.assertEqual(diff["strata"], {"play": {"b": 3, "c": 1, "n": 10}, "draw": {"b": 2, "c": 2, "n": 10}})
        self.assertEqual(diff["starter_mismatch"], {"games": 0, "of": 20, "warn": False})
        # rho: Pearson of the two arms' wins over the 20 pairs.
        pairs = [(yv, yb) for cells in (play, draw) for (yv, yb), k in cells.items() for _ in range(k)]
        mv, mb = sum(p[0] for p in pairs) / 20, sum(p[1] for p in pairs) / 20
        cov = sum((p[0] - mv) * (p[1] - mb) for p in pairs)
        rho = cov / math.sqrt(sum((p[0] - mv) ** 2 for p in pairs) * sum((p[1] - mb) ** 2 for p in pairs))
        self.assertAlmostEqual(diff["rho"], rho, places=12)
        self.assertEqual(diff["same"], 12 / 20)

    def test_unpaired_mover_uses_only_the_paired_games(self):
        play = {(1, 0): 6, (0, 1): 2, (1, 1): 20, (0, 0): 12}
        draw = {(1, 0): 4, (0, 1): 3, (1, 1): 10, (0, 0): 23}
        base, variant = arms(strata_rows(play, draw))
        # Games in one arm only, and one whose starter differs, change nothing paired.
        base.append({"g": 500, "first": 0, "w": 0})
        variant.append({"g": 501, "first": 1, "w": 1})
        b, v = arms([(502, 0, 1, 0, 1)])
        diff = S.paired_diff(base + b, variant + v, 0, 1)
        self.assertEqual(diff["starter_mismatch"], {"games": 1, "of": 81, "warn": True})
        self.assertEqual(diff["n"], 80)
        v_v, l_v, u_v = balanced(26, 40, 14, 40)          # the variant's wins: b + both, per stratum
        v_b, l_b, u_b = balanced(22, 40, 13, 40)          # the base's: c + both
        d = v_v - v_b
        self.assertAlmostEqual(diff["unpaired"]["delta"], d, places=12)
        self.assertAlmostEqual(diff["unpaired"]["low"], d - math.sqrt((v_v - l_v) ** 2 + (u_b - v_b) ** 2), places=12)
        self.assertAlmostEqual(diff["unpaired"]["high"], d + math.sqrt((u_v - v_v) ** 2 + (v_b - l_b) ** 2), places=12)
        width = diff["unpaired"]["high"] - diff["unpaired"]["low"]
        self.assertAlmostEqual(diff["saved_share"], 1 - ((diff["high"] - diff["low"]) / width) ** 2, places=12)
        self.assertGreater(diff["saved_share"], 0)

    def test_rho_is_none_for_a_constant_arm(self):
        play = {(1, 0): 6, (1, 1): 14}
        draw = {(1, 0): 9, (1, 1): 11}
        diff = S.paired_diff(*arms(strata_rows(play, draw)), 0, 1)
        self.assertIsNone(diff["rho"])
        self.assertIsNone(diff["saved_share"])
        self.assertIsNotNone(diff["delta"])
        self.assertIsNotNone(diff["unpaired"])

    def test_no_difference_without_both_strata(self):
        diff = S.paired_diff(*arms(strata_rows({(1, 0): 3, (0, 0): 2}, {})), 0, 1)
        self.assertEqual((diff["delta"], diff["low"], diff["high"], diff["z"], diff["var"]), (None,) * 5)
        self.assertEqual(diff["n"], 5)
        empty = S.paired_diff([], [], 0, 1)
        self.assertEqual((empty["n"], empty["same"], empty["rho"]), (0, None, None))
        self.assertEqual(empty["starter_mismatch"], {"games": 0, "of": 0, "warn": False})

    def test_paired_field(self):
        one = S.paired_diff(*arms(strata_rows({(1, 0): 3, (0, 1): 1, (0, 0): 6}, {(1, 0): 2, (0, 1): 2, (1, 1): 6})),
                            0, 1)
        two = S.paired_diff(*arms(strata_rows({(1, 0): 1, (0, 1): 4, (1, 1): 15}, {(0, 1): 2, (0, 0): 18})), 0, 1)
        none = S.paired_diff([], [], 0, 1)
        field = S.paired_field([one, two, none])
        c1, c2 = one["z"] * math.sqrt(one["var"]), two["z"] * math.sqrt(two["var"])
        se = math.sqrt(one["var"] + two["var"]) / 2
        self.assertEqual(field["k"], 2)
        self.assertAlmostEqual(field["delta"], (c1 + c2) / 2, places=12)
        self.assertAlmostEqual(field["se"], se, places=12)
        self.assertAlmostEqual(field["low"], (c1 + c2) / 2 - 1.959964 * se, places=12)
        self.assertAlmostEqual(field["z"], (c1 + c2) / 2 / se, places=12)
        self.assertIsNone(S.paired_field([none]))
        self.assertIsNone(S.paired_field([]))
        # Only the frozen fields: worked out again from the strata.
        bare = {key: one[key] for key in ("delta", "low", "high", "z", "var", "n", "strata")}
        self.assertAlmostEqual(S.paired_field([bare, two])["delta"], field["delta"], places=12)

    def test_paired_verdict(self):
        self.assertEqual(S.paired_verdict(0.01, 0.08, 0.03), "better")
        self.assertEqual(S.paired_verdict(0.005, 0.025, 0.03), "slightly_better")
        self.assertEqual(S.paired_verdict(-0.08, -0.01, 0.03), "worse")
        self.assertEqual(S.paired_verdict(-0.029, -0.002, 0.03), "slightly_worse")
        self.assertEqual(S.paired_verdict(-0.02, 0.025, 0.03), "little_difference")
        self.assertEqual(S.paired_verdict(-0.02, 0.025, 0.02), "not_settled")
        self.assertEqual(S.paired_verdict(None, None, 0.03), "not_settled")
        self.assertEqual(set(S.PAIRED_VERDICTS), {"better", "worse", "slightly_better", "slightly_worse",
                                                  "little_difference", "not_settled"})

    def test_paired_look(self):
        def diff(center, se):
            return {"delta": center, "low": center - 1.959964 * se, "high": center + 1.959964 * se,
                    "z": center / se, "var": se * se, "center": center, "se": se}
        look = S.paired_look(diff(0.05, 0.02), 400)
        self.assertEqual((look["bound"], look["interim"], look["decision"]), (3.0, True, "continue"))
        look = S.paired_look(diff(0.05, 0.02), 3200)
        self.assertEqual((look["bound"], look["interim"], look["decision"]), (S.HP_FINAL, False, "better"))
        self.assertEqual(S.paired_look(diff(0.05, 0.02), 1600, max_games=1600)["decision"], "better")
        self.assertEqual(S.paired_look(diff(0.05, 0.02), 1600, max_games=1600, interim=True)["decision"], "continue")
        self.assertEqual(S.paired_look(diff(-0.08, 0.02), 400)["decision"], "worse")
        self.assertEqual(S.paired_look(diff(0.012, 0.0035), 800, margin=0.02)["decision"], "slightly_better")
        self.assertEqual(S.paired_look(diff(0.002, 0.012), 800)["decision"], "little_difference")
        self.assertEqual(S.paired_look(diff(0.002, 0.016), 800)["decision"], "continue")
        self.assertEqual(S.paired_look(diff(0.002, 0.016), 3200)["decision"], "not_settled")
        # The field's looks are per opponent: the last is 1,600.
        self.assertEqual(S.paired_look(diff(0.045, 0.02), 1600, looks=S.FIELD_PAIRED_LOOKS)["bound"], S.HP_FINAL)
        # A stopped look: 3.0, and the little-difference range is center ± 3·se.
        look = S.paired_look(diff(0.002, 0.012), 1000, stopped=True)
        self.assertEqual((look["bound"], look["stopped"], look["decision"]), (3.0, True, "not_settled"))
        self.assertAlmostEqual(look["low"], 0.002 - 0.036)
        self.assertEqual(S.paired_look(diff(0.002, 0.005), 1000, stopped=True)["decision"], "little_difference")
        self.assertEqual(S.paired_look({"delta": None, "low": None, "high": None, "z": None, "var": None}, 400)
                         ["decision"], "continue")


class FieldTests(unittest.TestCase):
    def test_field_row(self):
        games = games_of((60, 35, 5), (45, 55, 0))
        row = S.field_row(games, 0)
        v, low, high = balanced(60, 100, 45, 100)
        self.assertEqual((row["n"], row["d"]), (200, 195))
        self.assertAlmostEqual(row["value"], v, places=12)
        self.assertAlmostEqual(row["low"], low, places=12)
        self.assertAlmostEqual(row["high"], high, places=12)
        self.assertAlmostEqual(row["pi"], (60 / 95 + 45 / 100) / 2, places=12)
        self.assertEqual(S.field_row(games_of((5, 5, 0), (0, 0, 0)), 0)["value"], None)

    def test_field_average_is_mover_over_the_equal_weight_sum(self):
        rows = [{"value": 0.6, "low": 0.55, "high": 0.64, "se": 0.02},
                {"value": 0.4, "low": 0.33, "high": 0.46, "se": 0.03},
                {"value": None, "low": None, "high": None, "se": None}]
        avg = S.field_average(rows)
        self.assertAlmostEqual(avg["value"], 0.5)
        self.assertAlmostEqual(avg["low"], 0.5 - math.sqrt(0.05 ** 2 + 0.07 ** 2) / 2)
        self.assertAlmostEqual(avg["high"], 0.5 + math.sqrt(0.04 ** 2 + 0.06 ** 2) / 2)
        self.assertAlmostEqual(avg["se_wald"], math.sqrt(0.02 ** 2 + 0.03 ** 2) / 2)
        self.assertEqual((avg["counted"], avg["of"], avg["partial"]), (2, 3, True))
        self.assertEqual(S.field_average(rows[:2], of=2)["partial"], False)
        self.assertEqual(S.field_average(rows[:2], of=9)["of"], 9)
        self.assertIsNone(S.field_average(rows[2:]))

    def test_apt_picks_the_closest_to_even(self):
        rows = [{"id": "a", "n": 200, "pi": 0.70, "inflight": False, "meaningful": True},
                {"id": "b", "n": 200, "pi": 0.52, "inflight": False, "meaningful": True},
                {"id": "c", "n": 400, "pi": 0.51, "inflight": False, "meaningful": True},
                {"id": "d", "n": 200, "pi": 0.50, "inflight": True, "meaningful": True},
                {"id": "e", "n": 200, "pi": 0.50, "inflight": False, "meaningful": False},
                {"id": "f", "n": 1600, "pi": 0.50, "inflight": False, "meaningful": True},
                {"id": "g", "n": 200, "pi": 0.48, "inflight": False, "meaningful": True}]
        # sqrt(n)·(|π̂ − 0.5| + 0.05): b and g 0.990 (b first: same games, then the id), c 1.2, a 3.54.
        self.assertEqual(S.apt_pick(rows, 1), ["b"])
        self.assertEqual(S.apt_pick(rows, 3), ["b", "g", "c"])
        self.assertEqual(S.apt_pick(rows, 10), ["b", "g", "c", "a"])
        self.assertEqual(S.apt_pick(rows, 0), [])
        # Ties go to fewer games first.
        tie = [{"id": "x", "n": 400, "pi": 0.5, "inflight": False, "meaningful": True},
               {"id": "y", "n": 100, "pi": 0.55, "inflight": False, "meaningful": True}]
        self.assertAlmostEqual(math.sqrt(400) * 0.05, math.sqrt(100) * 0.10)
        self.assertEqual(S.apt_pick(tie, 1), ["y"])

    def test_spearman_with_ties(self):
        # Average ranks x = [1, 2.5, 2.5, 4], y = [1, 3, 2, 4]: Σdxdy = 4.5, Σdx² = 4.5, Σdy² = 5.
        self.assertAlmostEqual(S.spearman([1, 2, 2, 3], [1, 3, 2, 4]), 4.5 / math.sqrt(4.5 * 5), places=12)
        self.assertAlmostEqual(S.spearman([3, 1, 2], [30, 10, 20]), 1.0)
        self.assertAlmostEqual(S.spearman([1, 2, 3], [3, 2, 1]), -1.0)
        self.assertIsNone(S.spearman([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(S.spearman([1], [1]))
        self.assertIsNone(S.spearman([1, 2], [1, 2, 3]))


def bt_data(beta, h, games, rng, pairs=None):
    """{(i, j, i_started): [i's wins, games]} drawn from the Bradley-Terry model."""
    names = sorted(beta)
    pairs = pairs or [(i, j) for x, i in enumerate(names) for j in names[x + 1:]]
    data = {}
    for i, j in pairs:
        for st in (True, False):
            eta = beta[i] - beta[j] + (h if st else -h)
            data[(i, j, st)] = [rng.binomialvariate(games, 1 / (1 + math.exp(-eta))), games]
    return data


class BradleyTerryTests(unittest.TestCase):
    BETA = {"A": -1.0, "B": -0.6, "C": -0.25, "D": 0.0, "E": 0.15, "F": 0.35, "G": 0.55, "H": 0.8}

    def test_known_betas_within_their_standard_errors(self):
        rng = random.Random(11)
        errors = []
        for _ in range(5):
            fit = S.bt_fit(bt_data(self.BETA, 0.2, 120, rng))
            self.assertTrue(fit["converged"])
            self.assertAlmostEqual(sum(fit["beta"].values()), 0.0, places=9)
            players = fit["players"]
            for n, name in enumerate(players):
                errors.append(abs(fit["beta"][name] - self.BETA[name]) / math.sqrt(fit["cov"][n][n]))
            self.assertAlmostEqual(fit["h"], 0.2, delta=3.5 * math.sqrt(fit["cov"][-1][-1]))
        self.assertGreaterEqual(sum(e <= 2 for e in errors) / len(errors), 0.90)
        self.assertLessEqual(max(errors), 3.5)

    def test_the_same_ratings_under_any_order_of_the_players(self):
        rng = random.Random(5)
        data = bt_data(self.BETA, 0.3, 60, rng)
        fit = S.bt_fit(data)
        # The same games, every pairing turned round (j's wins when j started is i's losses when i
        # didn't), the dict in another order, and the players renamed so they sort the other way.
        rename = {name: f"z{9 - n}" for n, name in enumerate(sorted(self.BETA))}
        turned = {(rename[j], rename[i], not st): [n - w, n] for (i, j, st), (w, n) in reversed(list(data.items()))}
        other = S.bt_fit(turned)
        self.assertNotEqual(other["players"], [rename[q] for q in fit["players"]])
        for name in self.BETA:
            self.assertAlmostEqual(fit["beta"][name], other["beta"][rename[name]], delta=1e-9)
        self.assertAlmostEqual(fit["h"], other["h"], delta=1e-9)
        self.assertAlmostEqual(fit["phi"], other["phi"], delta=1e-9)
        field = sorted(self.BETA)
        one = S.bt_rating(fit, "C", field)
        two = S.bt_rating(other, rename["C"], [rename[q] for q in reversed(field)])
        for key in ("value", "low", "high", "c", "se", "h_points"):
            self.assertAlmostEqual(one[key], two[key], delta=1e-9)
        self.assertEqual((one["rank"], one["of"]), (two["rank"], two["of"]))
        self.assertAlmostEqual(S.bt_predict(fit, "A", "H"), S.bt_predict(other, rename["A"], rename["H"]), delta=1e-9)
        # Only the order of data changed: identical answers, the rank range too.
        again = S.bt_fit(dict(reversed(list(data.items()))))
        self.assertEqual(S.bt_rating(again, "C", field), one)

    def test_dispersion(self):
        fit = S.bt_fit(bt_data(self.BETA, 0.2, 100, random.Random(3)))
        self.assertGreaterEqual(fit["phi"], 1.0)
        self.assertLess(fit["phi"], 1.5)
        self.assertEqual(fit["df"], 56 - 7 - 1)
        # Rock, paper, scissors: no rating explains it.
        cyclic = {}
        for i, j in (("R", "S"), ("S", "P"), ("P", "R")):
            for st in (True, False):
                cyclic[(i, j, st)] = [160, 200]
        fit = S.bt_fit(cyclic)
        self.assertGreater(fit["phi"], 5)
        self.assertAlmostEqual(sum(fit["beta"].values()), 0.0, places=9)

    def test_predict_and_rating_formulas(self):
        fit = {"players": ["a", "b"], "beta": {"a": 0.4, "b": -0.4}, "h": 0.3, "phi": 2.0,
               "cov": [[0.01, -0.005, 0.0], [-0.005, 0.01, 0.0], [0.0, 0.0, 0.001]]}
        sig = lambda x: 1 / (1 + math.exp(-x))
        self.assertAlmostEqual(S.bt_predict(fit, "a", "b"), (sig(0.8 + 0.3) + sig(0.8 - 0.3)) / 2)
        rating = S.bt_rating(fit, "a", ["a", "b"])
        c = 0.4 - 0.0
        # a = (1 − ½, −½): aᵀΣa = 0.25·0.01 + 0.25·0.01 + 2·(½)(−½)(−0.005) = 0.0075.
        se = math.sqrt(0.0075)
        self.assertAlmostEqual(rating["c"], c)
        self.assertAlmostEqual(rating["se"], se)
        self.assertAlmostEqual(rating["value"], (sig(c + 0.3) + sig(c - 0.3)) / 2)
        half = 1.959964 * math.sqrt(2.0) * se
        self.assertAlmostEqual(rating["low"], (sig(c - half + 0.3) + sig(c - half - 0.3)) / 2)
        self.assertAlmostEqual(rating["high"], (sig(c + half + 0.3) + sig(c + half - 0.3)) / 2)
        self.assertAlmostEqual(rating["h_points"], 100 * (sig(0.3) - 0.5))
        self.assertEqual((rating["rank"], rating["of"]), (1, 2))
        self.assertIsNone(S.bt_rating(fit, "q", ["a"]))
        self.assertIsNone(S.bt_rating(fit, "a", ["q"]))
        # A list that isn't a field list is ranked among them.
        self.assertEqual(S.bt_rating(fit, "a", ["b"])["of"], 2)

    def test_the_rank_range(self):
        beta = {"w": -1.5, "x": -0.5, "y": 0.5, "z": 1.5}
        fit = S.bt_fit(bt_data(beta, 0.0, 400, random.Random(8)))
        rating = S.bt_rating(fit, "z", sorted(beta))
        self.assertEqual((rating["rank"], rating["rank_low"], rating["rank_high"], rating["of"]), (1, 1, 1, 4))
        rating = S.bt_rating(fit, "w", sorted(beta))
        self.assertEqual((rating["rank"], rating["rank_low"], rating["rank_high"]), (4, 4, 4))
        # Two lists hardly apart, on few games: either could be first.
        close = S.bt_fit(bt_data({"p": 0.02, "q": 0.0, "r": -2.0}, 0.0, 30, random.Random(2)))
        rating = S.bt_rating(close, "p", ["p", "q", "r"])
        self.assertEqual((rating["rank_low"], rating["rank_high"]), (1, 2))

    def test_components(self):
        data = {("a", "b", True): [3, 5], ("b", "c", False): [2, 4], ("d", "e", True): [1, 2],
                ("a", "f", True): [0, 0]}
        self.assertEqual(S.bt_component(data, "a"), {"a", "b", "c"})
        self.assertEqual(S.bt_component(data, "e"), {"d", "e"})
        self.assertEqual(S.bt_component(data, "f"), {"f"})
        self.assertIsNone(S.bt_fit({}))

    def test_residual_flags_find_a_planted_pairing(self):
        beta = {"A": 0.0, "B": 0.3, "C": -0.3, "D": 0.6, "E": -0.6, "F": 0.1, "G": -0.15, "H": 0.45, "I": -0.45,
                "J": 0.2}
        rng = random.Random(23)
        data = bt_data(beta, 0.2, 200, rng)
        # A beats D far more often than the ratings say (55 % against BT's 36 %), and Z only ever
        # played A. (A planted pairing also pulls A's rating up in every other refit, so with
        # other draws a pairing or two can come out "weak"; this draw is a fixed one.)
        for st in (True, False):
            data[("A", "D", st)] = [rng.binomialvariate(200, 0.55), 200]
        data[("A", "Z", True)] = [50, 100]
        data[("Z", "A", True)] = [40, 100]
        fit = S.bt_fit(data)
        observed = {}
        for j in sorted(set(beta) - {"A"}) + ["Z"]:
            games = []
            for (i, k, st), (w, n) in data.items():
                if {i, k} == {"A", j}:
                    a_started = st if i == "A" else not st
                    a_wins = w if i == "A" else n - w
                    first = 0 if a_started else 1
                    games += [{"w": 0, "first": first}] * a_wins + [{"w": 1, "first": first}] * (n - a_wins)
            share = S.decided_share(games, 0)
            observed[j] = (share["pi"], share["se"])
        flags = S.residual_flags(data, fit, "A", observed)
        self.assertEqual([row["opponent"] for row in flags], list("BCDEFGHIJ"))     # Z is a bridge
        by = {row["opponent"]: row for row in flags}
        self.assertEqual(by["D"]["flag"], "strong")
        self.assertGreater(by["D"]["r"], 0.15)
        self.assertEqual([row["opponent"] for row in flags if row["flag"]], ["D"])
        # The flags are the Benjamini-Hochberg discoveries at 10 % with |r| ≥ 5 points.
        ps = sorted(row["p"] for row in flags)
        cut = max([rank for rank, p in enumerate(ps, 1) if p <= 0.10 * rank / len(ps)], default=0)
        top = ps[cut - 1] if cut else -1
        expected = {row["opponent"] for row in flags if row["p"] <= top and abs(row["r"]) >= 0.05}
        self.assertEqual({row["opponent"] for row in flags if row["flag"]}, expected)
        # D's observed share is unchanged; the refit without A-D predicts it lower than the full fit does.
        self.assertLess(observed["D"][0] - by["D"]["r"], S.bt_predict(fit, "A", "D"))

    def test_a_residual_under_five_points_is_not_flagged(self):
        fit = S.bt_fit(bt_data(self.BETA, 0.0, 2000, random.Random(4)))
        observed = {j: (S.bt_predict(fit, "D", j) + 0.04, 0.005) for j in self.BETA if j != "D"}
        flags = S.residual_flags(bt_data(self.BETA, 0.0, 2000, random.Random(4)), fit, "D", observed)
        self.assertTrue(all(row["p"] < 0.01 for row in flags))
        self.assertTrue(all(row["flag"] is None for row in flags))


class NewtonTests(unittest.TestCase):
    def test_a_stalled_step_is_not_taken_or_called_converged(self):
        # An objective that every move lowers: step-halving gives up, so the fit stays at its
        # start and isn't reported as converged.
        data = bt_data({"p": 0.5, "q": 0.0, "r": -0.5}, 0.1, 50, random.Random(5))
        cells = S._cells(data)
        real = S._objective
        S._objective = lambda cells, idx, theta, prior_sd: -sum(abs(x) for x in theta)
        try:
            theta, _, iterations, converged = S._newton(cells, ["p", "q", "r"], S.BT_PRIOR_SD)
        finally:
            S._objective = real
        self.assertFalse(converged)
        self.assertEqual((theta, iterations), ([0.0] * 4, 1))

    def test_a_normal_fit_converges_on_a_full_step(self):
        data = bt_data({"p": 0.5, "q": 0.0, "r": -0.5}, 0.1, 50, random.Random(5))
        theta, _, iterations, converged = S._newton(S._cells(data), ["p", "q", "r"], S.BT_PRIOR_SD)
        self.assertTrue(converged)
        self.assertLess(iterations, S.BT_ITERATIONS)


class MonteCarloTests(unittest.TestCase):
    """Seeded simulations of the rules' error rates and coverage (section 19.2)."""

    def test_haybittle_peto_alpha_is_5_percent(self):
        rng = random.Random(20261003)
        paths, hits = 4000, 0
        for _ in range(paths):
            a, b, n = [0, 0], [0, 0], 0
            for nxt in S.HP_LOOKS:
                more = nxt - n
                on_play = rng.binomialvariate(more, 0.5)
                for s, k, p in ((0, on_play, 0.55), (1, more - on_play, 0.45)):    # balanced rate 50 %
                    wins = rng.binomialvariate(k, p)
                    a[s] += wins
                    b[s] += k - wins
                n = nxt
                _, _, z = S._decided(a, b)
                bound = S.HP_FINAL if S._is_final(n, S.CAP, S.HP_LOOKS) else S.HP_INTERIM
                if abs(z) >= bound:
                    hits += 1
                    break
        self.assertGreaterEqual(hits / paths, 0.035)
        self.assertLessEqual(hits / paths, 0.065)

    def test_assess_coverage(self):
        rng = random.Random(7)
        for truth in (0.5, 0.65, 0.8):
            sims, covered = 2000, 0
            for _ in range(sims):
                n1 = w1 = n2 = w2 = 0
                topups = 0
                while True:
                    n = n1 + n2
                    hw = S._half_width(n1, w1, n2, w2) if n else None
                    more, reason = S._assess(n, hw, topups_done=topups)
                    if not more:
                        break
                    topups += reason == "top-up"
                    on_play = rng.binomialvariate(more, 0.5)
                    n1, w1 = n1 + on_play, w1 + rng.binomialvariate(on_play, truth + 0.04)
                    n2, w2 = n2 + more - on_play, w2 + rng.binomialvariate(more - on_play, truth - 0.04)
                _, low, high = forge.views.balanced(w1, n1, w2, n2)
                covered += low <= truth <= high
            self.assertGreaterEqual(covered / sims, 0.925, truth)

    def test_the_anytime_range_covers_every_look_at_once(self):
        rng = random.Random(13)
        for truth in (0.5, 0.7):
            paths, covered = 2000, 0
            for _ in range(paths):
                wins = n = 0
                ok = True
                for nxt in S.HP_LOOKS:
                    on_play = rng.binomialvariate(nxt - n, 0.5)
                    wins += rng.binomialvariate(on_play, truth + 0.05) + \
                        rng.binomialvariate(nxt - n - on_play, truth - 0.05)
                    n = nxt
                    _, low, high = S._anytime(wins, n)
                    ok = ok and low <= truth <= high
                covered += ok
            self.assertGreaterEqual(covered / paths, 0.95, truth)

    def test_paired_agresti_min_coverage(self):
        rng = random.Random(17)
        strata = ((0.55, 0.60), (0.45, 0.48))         # (base, variant) win chances on the play, on the draw
        truth = ((0.60 - 0.55) + (0.48 - 0.45)) / 2
        for rho in (0.0, 0.6):
            cells = []
            for pb, pv in strata:
                both = pb * pv + rho * math.sqrt(pb * (1 - pb) * pv * (1 - pv))
                cells.append((pv - both, pb - both, both))    # (variant only, base only, both)
            sims, covered = 2000, 0
            for _ in range(sims):
                counts = []
                for p10, p01, p11 in cells:
                    n = 200
                    b = rng.binomialvariate(n, p10)
                    c = rng.binomialvariate(n - b, p01 / (1 - p10))
                    counts.append((b, c, n))
                center, var = S._agresti_min(*counts)
                covered += abs(center - truth) <= 1.959964 * math.sqrt(var)
            self.assertGreaterEqual(covered / sims, 0.935, rho)


if __name__ == "__main__":
    unittest.main()
