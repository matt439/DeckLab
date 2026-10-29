"""Tests for the experiment harness (decklab/lib/forge/experiment.py; forge-trial/sim-wave3-contract.md
section 12): the spec, seats and flips, the own-lost attribution and the per-game numbers of the tee'd
logs, the arms' runs, the measures and section 12.4's rules, the report and the command line.

Most runs are a stand-in for forge.runner.run that plays R's keywords (numbers, seeds, key, kind,
extra, override_sets, log_dir; section 8) the way the contract says, with E3's engine.side_list order
(sides sorted by [card_sha, profile, ...]), so the harness's orchestration is tested before R merges.
Each stand-in game is a function of its seats: seat 1 starts in game g when g's hash is even, and the
winner's seat is another hash of g, unless the test gives an arm an effect. So an arm whose flip keeps
each list in its control seat plays the control's games exactly. Until package S merges,
seqstats.paired_diff and paired_field are a reference of section 7.4 here (_ReferenceSeqstats), so the
measures can be checked; once S is built, its functions are used.

The tests that play the fake Forge through the real runner.run need R's hooks and skip until
runner.RUN_FEATURES has them (section 21). They share test_forge.py's setUpModule and tearDownModule.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_experiment
"""
import gzip
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import decks, forge
from decklab.lib.forge import experiment, seeds, seqstats
from decklab.tests import test_forge
from decklab.tests.test_forge import CARD_LOG, FAKE, GREEN, RED, entry, sections

BLUE = """Deck
4 Counterspell
4 Divination
12 Island
"""

R_FEATURES = {"numbers", "seeds", "key", "kind", "extra", "override_sets", "log_dir"}


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def _seqstats_built():
    try:
        seqstats.paired_field([])
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


class _ReferenceSeqstats:
    """Section 7.4's paired difference (Agresti-Min per stratum) and field pooling, for the tests
    only until package S's seqstats is built."""

    @staticmethod
    def paired_diff(base_games, paired_games_, base_side, variant_side):
        base = {g["g"]: g for g in base_games}
        strata = {"play": {"b": 0, "c": 0, "n": 0}, "draw": {"b": 0, "c": 0, "n": 0}}
        common = mismatch = same = 0
        ys = []
        for g in paired_games_:
            b = base.get(g["g"])
            if b is None:
                continue
            common += 1
            if (b["first"] == base_side) != (g["first"] == variant_side):
                mismatch += 1
                continue
            yb, yv = int(b["w"] == base_side), int(g["w"] == variant_side)
            ys.append((yb, yv))
            same += yb == yv and b.get("rounds") == g.get("rounds")
            s = strata["play" if g["first"] == variant_side else "draw"]
            s["b"] += yv and not yb
            s["c"] += yb and not yv
            s["n"] += 1
        out = {"n": len(ys), "same": same / len(ys) if ys else None, "starter_mismatch": {"games": mismatch,
                                                                                         "of": common},
               "strata": strata, "rho": None, "unpaired": None, "saved_share": None,
               "delta": None, "low": None, "high": None, "z": None, "var": None}
        if not strata["play"]["n"] or not strata["draw"]["n"]:
            return out
        dp, vp = [], []
        for s in strata.values():
            b, c, n = s["b"] + 0.5, s["c"] + 0.5, s["n"] + 2
            dp.append((b - c) / n)
            vp.append(((b + c) - (b - c) ** 2 / n) / n ** 2)
        delta = sum((s["b"] - s["c"]) / s["n"] for s in strata.values()) / 2
        centre, se = sum(dp) / 2, math.sqrt(sum(vp)) / 2
        out.update(delta=delta, low=centre - seqstats.Z95 * se, high=centre + seqstats.Z95 * se, z=centre / se,
                   var=sum(vp) / 4)
        return out

    @staticmethod
    def paired_field(diffs):
        diffs = [d for d in diffs if d.get("delta") is not None]
        if not diffs:
            return None
        k = len(diffs)
        centre = sum((d["low"] + d["high"]) / 2 for d in diffs) / k
        se = math.sqrt(sum(d["var"] for d in diffs)) / k
        return {"delta": sum(d["delta"] for d in diffs) / k, "low": centre - seqstats.Z95 * se,
                "high": centre + seqstats.Z95 * se, "z": centre / se, "se": se, "k": k}


def _with_seqstats(case):
    """Use the reference for seqstats' paired functions while S's raise NotImplementedError."""
    if _seqstats_built():
        return
    for name in ("paired_diff", "paired_field"):
        p = mock.patch.object(seqstats, name, getattr(_ReferenceSeqstats, name))
        p.start()
        case.addCleanup(p.stop)


def _mix(*numbers):
    return seeds.game_seed(numbers[0], numbers[1] if len(numbers) > 1 else 0, numbers[-1])


def side_list(e, eng=None):
    """E3's engine.side_list as the stand-in plays it: [card_sha, profile, sha, (switches)]."""
    pilot = e.get("pilot") or {"profile": "Default", "switches": []}
    out = [e["card_sha"], pilot["profile"], "sha-" + pilot["profile"]]
    return out + ([sorted(pilot["switches"])] if pilot.get("switches") else [])


SPEC = {"name": "t1", "games": 50,
        "pairs": [["casual/green", "casual/red"], ["casual/green", "casual/blue"]],
        "arms": {"reck": {"pilots": {"casual/green": {"profile": "Reckless"}}}},
        "measures": ["matchup", "speed"]}


# ============================================================ the spec

class SpecTests(unittest.TestCase):

    def test_the_contracts_example_is_read_and_filled_in(self):
        spec = experiment.check_spec({
            "name": "etb", "games": 800,
            "pairs": [["casual/mono-black-midrange", "product/challenger-2019-lightning-aggro"]],
            "control": {"results_dir": "C:/x", "logs_dir": "C:/y"},
            "arms": {"etb": {"overrides": ["etb"]}, "none": {"overrides": [], "replace_adopted": True},
                     "pump": {"pilots": {"casual/selesnya-rabbits": {"profile": "Default",
                                                                     "switches": ["team-pump-1"]}}},
                     "reck": {"pilots": {"casual/selesnya-rabbits": {"profile": "Reckless"}}, "sides": "a"},
                     "shared": {"seeds": {"stream_from": ["casual/izzet-prowess", "casual/gruul-ramp"],
                                          "seat_of": "casual/izzet-prowess"}},
                     "perf": {"config": {"forge_performance_mode": False}}},
            "cards": {"Massacre Wurm": {"cast_target": 0.6, "turn_target": 8.5}},
            "measures": ["cast", "turn", "win_early", "win_drawn", "own_lost", "matchup", "speed"]})
        self.assertEqual(spec["arms"]["none"], {"overrides": [], "replace_adopted": True, "pilots": {}, "sides": None,
                                                "seeds": None, "config": None})
        self.assertEqual(spec["arms"]["reck"]["pilots"]["casual/selesnya-rabbits"],
                         {"profile": "Reckless", "switches": []})
        self.assertEqual(spec["arms"]["reck"]["sides"], "a")
        self.assertEqual(spec["arms"]["shared"]["seeds"]["seat_of"], "casual/izzet-prowess")
        self.assertEqual(spec["cards"]["Massacre Wurm"], {"cast_target": 0.6, "turn_target": 8.5})
        self.assertEqual(spec["control"], {"results_dir": "C:/x", "logs_dir": "C:/y"})

    def test_the_default_results_folder_is_the_documented_one(self):
        """<data>/forge/experiments/<name>/ (README.md, the contract, --help): DATA_DIR is already
        <data>/forge, so not <data>/forge/forge/experiments/ (AI round 1's specs name that folder)."""
        spec = experiment.check_spec(dict(SPEC, control={"results_dir": None, "logs_dir": None}))
        results, logs, _, _ = experiment._canonical_dirs(spec, None, None, None, None)
        self.assertEqual(results, forge.common.DATA_DIR / "experiments" / "t1")
        self.assertEqual(logs, results / experiment.LOGS)

    def test_bad_specs_are_refused_with_a_sentence(self):
        good = {"name": "x", "games": 10, "pairs": [["a/b", "c/d"]], "arms": {"r": {"overrides": ["etb"]}}}
        for change, words in (
                ({"name": "bad name!"}, "name"),
                ({"games": 0}, "games"),
                ({"games": True}, "games"),
                ({"pairs": [["a/b"]]}, "pair"),
                ({"pairs": [["a/b", "c/d"], ["a/b", "c/d"]]}, "twice"),
                ({"pairs": [["a/b", "c/d"], ["c/d", "a/b"]]}, "twice"),      # either order is one control
                ({"arms": {}}, "arms"),
                ({"arms": {"control": {"overrides": []}}}, "control"),
                ({"arms": {"logs": {"overrides": []}}}, "logs"),
                ({"arms": {"report.md": {"overrides": []}}}, "report.md"),
                ({"arms": {"experiment.json": {"overrides": []}}}, "experiment.json"),
                ({"arms": {"spec.json": {"overrides": []}}}, "spec.json"),
                ({"arms": {"r": {"overrides": ["nope"]}}}, "nope"),
                ({"arms": {"r": {"colour": 1}}}, "colour"),
                ({"arms": {"r": {"replace_adopted": True}}}, "changes nothing"),
                ({"arms": {"r": {"pilots": {"a/b": {"profile": "Reckless"}}, "sides": "c"}}}, "sides"),
                ({"arms": {"r": {"seeds": {"stream_from": ["a/b", "c/d"], "seat_of": "e/f"}}}}, "seeds"),
                ({"cards": {"X": {"cast_target": 2}}}, "cast_target"),
                ({"measures": ["luck"]}, "measures"),
                ({"extra": 1}, "extra")):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, words):
                    experiment.check_spec({**good, **change})

    def test_load_spec_reads_a_file_and_says_what_is_wrong(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        (folder / "s.json").write_text(json.dumps(SPEC), encoding="utf-8")
        self.assertEqual(experiment.load_spec(folder / "s.json")["name"], "t1")
        (folder / "bad.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "isn't JSON"):
            experiment.load_spec(folder / "bad.json")
        with self.assertRaisesRegex(ValueError, "can't be read"):
            experiment.load_spec(folder / "missing.json")


# ============================================================ seats and flips

class SeatTests(unittest.TestCase):

    def test_the_flip_keeps_each_list_in_its_control_seat(self):
        for control_flip in (0, 1):
            for beta in (0, 1):
                for nu in (0, 1):
                    flip = experiment._flip(control_flip, beta, nu)
                    for g in range(0, 200, 7):
                        self.assertEqual(seeds.deck1_side(g, flip) == nu, seeds.deck1_side(g, control_flip) == beta)
                    self.assertEqual(experiment._seat_side(nu, flip, control_flip), beta)

    def test_arm_sides_follow_side_list_and_keep_a_tie_in_order(self):
        reck = {"card_sha": "a" * 64, "pilot": {"profile": "Reckless", "switches": []}}
        default = {"card_sha": "a" * 64, "pilot": {"profile": "Default", "switches": []}}
        pump = {"card_sha": "a" * 64, "pilot": {"profile": "Default", "switches": ["team-pump-1"]}}
        with mock.patch.object(forge.engine, "side_list", side_list, create=True):
            self.assertEqual(experiment._arm_sides([reck, default], {}), [1, 0])
            self.assertEqual(experiment._arm_sides([pump, default], {}), [1, 0])     # the shorter list first
            self.assertEqual(experiment._arm_sides([default, dict(default)], {}), [0, 1])
        other = {"card_sha": "0" * 64}
        with mock.patch.object(forge.engine, "side_list", None, create=True):
            self.assertEqual(experiment._arm_sides([reck, other], {}), [1, 0])        # by card_sha first
            # R's stand-in side list: the profile, then its SHA-256 (None as ""), then the switches.
            self.assertEqual(experiment._arm_sides([reck, default], {"ai_sha": {"Default": None}}), [1, 0])
            self.assertEqual(experiment._arm_sides([pump, default], {}), [1, 0])

    def test_runners_own_order_wins_when_it_has_one(self):
        a, b = {"card_sha": "a" * 64}, {"card_sha": "b" * 64}
        with mock.patch.object(forge.runner, "_ordered", lambda x, y, eng: [y, x], create=True):
            self.assertEqual(experiment._arm_sides([a, b], {}), [1, 0])

    def test_a_mirror_arms_stored_side_is_found_by_its_pilot(self):
        result = {"sides": [{"card_sha": "a", "pilot": {"profile": "Default", "switches": []}},
                            {"card_sha": "a", "pilot": {"profile": "Reckless", "switches": []}}]}
        reck = {"card_sha": "a", "pilot": {"profile": "Reckless", "switches": []}}
        self.assertEqual(experiment._stored_side(result, reck, 0, guess=0), 1)
        result["sides"][0].pop("pilot")
        self.assertEqual(experiment._stored_side(result, reck, 0, guess=0), 0)       # can't tell: the guess


# ============================================================ the logs

LOG = """Information: DL|log|1
Information: DL|deck|1|11=Massacre Wurm;12=Grizzly Bears;13=Swamp
Information: DL|deck|2|21=Llanowar Elves;22=Forest
Turn: Turn 1 (Ai(1)-aaaa)
Add To Stack: Ai(1)-aaaa cast Massacre Wurm
Resolve Stack: Massacre Wurm (11) - Creature 6 / 5
Information: DL|zone|1|1|MAIN1|Battlefield|Graveyard|2|21|Llanowar Elves
Information: DL|zone|1|1|MAIN1|Battlefield|Graveyard|1|12|Grizzly Bears
Information: DL|zone|1|1|MAIN1|Battlefield|Exile|1|13|Swamp
Phase: Ai(1)-aaaa's Combat step
Information: DL|zone|1|1|COMBAT|Battlefield|Graveyard|1|12|Grizzly Bears
Resolve Stack: When Massacre Wurm enters, creatures your opponents control get -2/-2. [Card: Massacre Wurm]
Information: DL|zone|1|1|MAIN1|Battlefield|Graveyard|1|12|Grizzly Bears
Resolve Stack: Llanowar Elves - Creature 1 / 1
Information: DL|zone|1|1|MAIN1|Battlefield|Graveyard|1|13|Swamp
"""


class LostTests(unittest.TestCase):

    def test_own_permanents_lost_after_a_named_card_resolves(self):
        lost = experiment._Lost(["Massacre Wurm"])
        for line in LOG.splitlines():
            lost.line(line)
        # The spell: its caster's (seat 1) two own permanents up to the Phase line, not the opponent's
        # elf, nor the bears after it; the trigger names it (by its last caster): one more.
        self.assertEqual(lost.tally, {(1, "massacre wurm"): [1, 3]})
        lost.new_game()
        self.assertEqual(lost.tally, {})

    def test_the_caster_is_the_only_seat_holding_the_card_without_an_id_or_a_cast(self):
        lost = experiment._Lost(["Llanowar Elves"])
        for line in ("Information: DL|deck|1|11=Massacre Wurm", "Information: DL|deck|2|21=Llanowar Elves",
                     "Resolve Stack: Llanowar Elves - Creature 1 / 1",
                     "Information: DL|zone|1|2|MAIN1|Battlefield|Graveyard|2|22|Forest",
                     "Information: DL|zone|1|2|MAIN1|Battlefield|Graveyard|1|11|Massacre Wurm",
                     "Turn: Turn 2 (Ai(2)-bbbb)",
                     "Information: DL|zone|2|2|MAIN1|Battlefield|Graveyard|2|21|Llanowar Elves"):
            lost.line(line)
        self.assertEqual(lost.tally, {(2, "llanowar elves"): [0, 1]})

    def test_names_match_whole_words_only(self):
        lost = experiment._Lost(["Fire"])
        lost.line("Information: DL|deck|1|11=Fire Elemental")
        lost.line("Resolve Stack: Fire Elemental (11) - Creature 5 / 4")
        self.assertIsNone(lost.window)


def _fake_log(folder, key, first, games, flip, deck_a, deck_b, base=1, stream="0123456789abcdef"):
    """The fake Forge's DeckLabSim output for games [first, first + games) of a result (its deck 1 the
    side seeds.deck1_side gives), tee'd as runner.run's log_dir writes it."""
    d1, d2 = (deck_a, deck_b) if seeds.deck1_side(first, flip) == 0 else (deck_b, deck_a)
    out = subprocess.run([sys.executable, str(FAKE), "sim", "-D", str(folder), "-d", d1, d2, "-n", str(games),
                          "-s", str(base), "-f", "Constructed", "-c", "120", "-a", "Default", "Default", "--card-log",
                          "-dlgame", stream, str(first)],
                         capture_output=True, text=True, encoding="utf-8", check=True,
                         env={k: v for k, v in os.environ.items() if k != "FAKE_FORGE"})
    path = folder / "logs" / key / f"{first}-{first + games - 1}.log.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(out.stdout)
    return out.stdout


class ReadLogsTests(unittest.TestCase):

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        for name, text in (("a.dck", GREEN), ("b.dck", RED)):
            e = entry(text, f"casual/{name[0]}")
            (self.folder / name).write_text(e["dck"], encoding="utf-8")

    def test_each_game_of_each_file_is_its_game_number_with_its_sides(self):
        _fake_log(self.folder, "k", 0, 5, 0, "a.dck", "b.dck")
        _fake_log(self.folder, "k", 25, 3, 0, "a.dck", "b.dck")      # the next seat block: b is deck 1
        _fake_log(self.folder, "k", 2, 2, 0, "a.dck", "b.dck")       # a chunk played again: the first file wins
        found = experiment.read_logs(self.folder / "logs" / "k", 0, ["Grizzly Bears", "Lightning Bolt"])
        self.assertEqual(sorted(found), [0, 1, 2, 3, 4, 25, 26, 27])
        for g, game in found.items():
            self.assertIn(game["w"], (0, 1))
            self.assertIsNotNone(game["cards"])
            # Green's cards are always side 0's (a), Red's side 1's, whichever seat they sat in.
            self.assertFalse(set(game["cards"][0]) & {"lightning bolt", "mountain"})
            self.assertFalse(set(game["cards"][1]) & {"grizzly bears", "forest"})
            for numbers in game["cards"][0].values():
                self.assertLessEqual(numbers[experiment.USED], numbers[experiment.COPIES])
            for side in (0, 1):
                for card, (casts, lost) in game["lost"][side].items():
                    self.assertGreaterEqual(casts, 0)
            self.assertEqual(game["errors"], [])
        # Only the named cards: Green's bears are drawn in some games, Red's bolts in others.
        self.assertTrue(any("grizzly bears" in game["cards"][0] for game in found.values()))
        self.assertTrue(any("lightning bolt" in game["cards"][1] for game in found.values()))
        self.assertFalse(any("forest" in game["cards"][0] for game in found.values()))

    def test_only_the_files_of_the_games_asked_for_are_read(self):
        _fake_log(self.folder, "k", 0, 5, 0, "a.dck", "b.dck")
        _fake_log(self.folder, "k", 25, 3, 0, "a.dck", "b.dck")
        found = experiment.read_logs(self.folder / "logs" / "k", 0, ["Grizzly Bears"], games=(0, 4))
        self.assertEqual(sorted(found), [0, 1, 2, 3, 4])
        found = experiment.read_logs(self.folder / "logs" / "k", 0, ["Grizzly Bears"], games=(26, 99))
        self.assertEqual(sorted(found), [25, 26, 27])

    def test_a_file_holding_other_games_than_its_name_says_is_left_out(self):
        _fake_log(self.folder, "k", 0, 5, 0, "a.dck", "b.dck")
        _fake_log(self.folder, "k", 25, 3, 0, "a.dck", "b.dck")
        logs = self.folder / "logs" / "k"
        (logs / "25-27.log.gz").rename(logs / "25-28.log.gz")     # a game short: its numbering can't be trusted
        with mock.patch.object(forge.common, "_log") as log:
            found = experiment.read_logs(logs, 0, ["Grizzly Bears"])
        self.assertEqual(sorted(found), [0, 1, 2, 3, 4])
        self.assertIn("holds 3 finished games, not the 4", log.call_args[0][0])

    def test_a_missing_folder_reads_as_no_games(self):
        self.assertEqual(experiment.read_logs(self.folder / "nowhere", 0), {})


# ============================================================ statistics and rules

class RateRatioTests(unittest.TestCase):

    def test_the_clopper_pearson_bound_matches_its_closed_form(self):
        # Every event in the arm: theta_L = alpha^(1/t), so r_L = theta/(1 - theta) * n1/n2.
        theta = 0.05 ** (1 / 10)
        self.assertAlmostEqual(experiment.rate_ratio(0, 1000, 10, 1000, 0.95), theta / (1 - theta), places=6)
        self.assertEqual(experiment.rate_ratio(5, 1000, 0, 1000, 0.95), 0.0)
        self.assertIsNone(experiment.rate_ratio(0, 1000, 0, 1000, 0.95))

    def test_the_timeout_test_flags_a_pair_with_three_or_more_arm_games_only(self):
        def pair(x1, x2):
            return {"timeouts": {"control": {"ai_timeout_games": x1, "games": 1000},
                                 "arm": {"ai_timeout_games": x2, "games": 1000}}}
        self.assertTrue(experiment._timeout_test([pair(0, 12)])["flag"])
        self.assertFalse(experiment._timeout_test([pair(0, 2), pair(0, 0)])["flag"])
        self.assertFalse(experiment._timeout_test([pair(4, 5)])["flag"])

    def test_the_ratio_estimators_cluster_se(self):
        found = experiment._ratio([(1, 2), (0, 1), (2, 2), (0, 0)])
        self.assertAlmostEqual(found["value"], 3 / 5)
        r = 0.6
        se = math.sqrt(3 / 2 * ((1 - r * 2) ** 2 + (0 - r) ** 2 + (2 - r * 2) ** 2)) / 5
        self.assertAlmostEqual(found["se"], se)
        self.assertIsNone(experiment._ratio([(0, 0)]))


def _diff(delta, half, z=None):
    se = half / 1.96
    return {"delta": delta, "low": delta - half, "high": delta + half, "z": z if z is not None else delta / se,
            "var": se ** 2}


def _arm(kind="override", pairs=None, cards=None, matchup=None, slowdown=1.0, errors=(), timeouts=False,
         pilots_=None):
    pairs = pairs if pairs is not None else [{"pair": ["x/a", "x/b"], "perspective": "x/a", "matchup": _diff(0.0, 0.03),
                                              "mirror": None, "games": {"paired": 800, "arm": 800}}]
    for p in pairs:
        p["matchup"]["clearly_negative"] = p["matchup"]["z"] < -experiment._bound(len(pairs))
    return {"kind": kind, "pairs": pairs, "bound": experiment._bound(len(pairs)),
            "how": {"pilots": pilots_ or {}},
            "pooled": {"matchup": matchup or _diff(0.0, 0.02), "new_errors": list(errors),
                       "timeouts": {"flag": timeouts}, "speed": {"slowdown": slowdown}},
            "cards": cards if cards is not None else {"Massacre Wurm": _card()}}


def _card(cast=0.7, target=0.6, rise=None, early=None, lost=0.1):
    return {"cast_target": target, "cast": {"arm": {"value": cast, "low": cast - 0.05, "high": cast + 0.05},
                                            "rise": rise or _diff(0.25, 0.05)},
            "win_early": early or _diff(0.01, 0.02), "own_lost": {"difference": {"delta": lost}}}


class RuleTests(unittest.TestCase):

    def test_an_override_set_is_adopted_when_every_rule_holds(self):
        found = experiment.recommend(_arm())
        self.assertEqual(found["recommendation"], "adopt", found["why"])

    def test_what_makes_an_override_set_not_adopted(self):
        negative = {"pair": ["x/a", "x/b"], "perspective": "x/a", "matchup": _diff(-0.1, 0.03), "mirror": None,
                    "games": {"paired": 800}}
        for arm, words in (
                (_arm(pairs=[negative]), "clearly worse"),
                (_arm(matchup=_diff(-0.05, 0.02)), "pooled matchup"),
                (_arm(cards={"Wurm": _card(early=_diff(-0.06, 0.02))}), "wins less"),
                (_arm(cards={"Wurm": _card(cast=0.2, rise=_diff(0.05, 0.05))}), "isn't cast enough"),
                (_arm(errors=["unsupported card: X"]), "New Forge script errors"),
                (_arm(timeouts=True), "AI-timeout")):
            with self.subTest(words=words):
                found = experiment.recommend(arm)
                self.assertEqual(found["recommendation"], "dont_adopt")
                self.assertTrue(any(words in why for why in found["why"]), found["why"])

    def test_an_unsettled_override_set_needs_more_games_and_says_how_many(self):
        found = experiment.recommend(_arm(cards={"Wurm": _card(early=_diff(0.0, 0.05))}))
        self.assertEqual(found["recommendation"], "more_games")
        # The low end -0.05 would reach -0.03 at 800 * (0.05 / 0.03)^2 = 2,222 games: 2,300 a pair.
        self.assertEqual(found["games_per_pair"], 2300)

    def test_more_own_permanents_lost_asks_for_more_games(self):
        found = experiment.recommend(_arm(cards={"Wurm": _card(lost=0.4)}))
        self.assertEqual(found["recommendation"], "more_games")
        self.assertTrue(any("own permanents" in why for why in found["why"]), found["why"])

    def test_a_card_without_a_cast_target_has_no_cast_rule(self):
        found = experiment.recommend(_arm(cards={"Wurm": _card(cast=0.1, target=None, rise=_diff(0.0, 0.02))}))
        self.assertEqual(found["recommendation"], "adopt", found["why"])

    def test_pilot_rules(self):
        def mirror(value, half):
            return {"pair": ["x/a", "x/a"], "perspective": "x/a", "matchup": _diff(0.0, 0.03),
                    "mirror": {"value": value, "low": value - half, "high": value + half},
                    "games": {"paired": 800, "arm": 800}}
        reference = {"pair": ["x/a", "x/b"], "perspective": "x/a", "matchup": _diff(0.0, 0.03), "mirror": None,
                     "games": {"paired": 800, "arm": 800}}
        pilot = {"x/a": {"profile": "Reckless", "switches": []}}
        hybrid = {"x/a": {"profile": "Default", "switches": ["aisim-hybrid-1"]}}
        cases = ((_arm("pilot", [mirror(0.56, 0.03), reference], pilots_=pilot), "adopt"),
                 (_arm("pilot", [mirror(0.44, 0.03), reference], pilots_=pilot), "dont_adopt"),
                 (_arm("pilot", [mirror(0.52, 0.03), reference], pilots_=pilot), "more_games"),
                 (_arm("pilot", [reference], pilots_=pilot), "more_games"),
                 (_arm("pilot", [mirror(0.56, 0.03), reference], pilots_=pilot, slowdown=1.8), "dont_adopt"),
                 (_arm("pilot", [mirror(0.56, 0.03), reference], pilots_=hybrid, slowdown=2.5), "adopt"),
                 # Errors and AI timeouts are noted, not one of a pilot's rules.
                 (_arm("pilot", [mirror(0.56, 0.03), reference], pilots_=pilot, timeouts=True), "adopt"))
        for arm, expected in cases:
            with self.subTest(expected=expected):
                found = experiment.recommend(arm)
                self.assertEqual(found["recommendation"], expected, found["why"])

    def test_only_script_errors_and_unsupported_cards_decide(self):
        self.assertTrue(experiment._blocking_error("unsupported card: X"))
        self.assertTrue(experiment._blocking_error("java.lang.RuntimeException: Error parsing card script f/x.txt"))
        self.assertTrue(experiment._blocking_error("java.lang.IllegalStateException: Massacre Wurm", ["Massacre Wurm"]))
        self.assertFalse(experiment._blocking_error("java.lang.NullPointerException", ["Massacre Wurm"]))
        arm = _arm()
        arm["pooled"]["new_exceptions"] = {"java.lang.NullPointerException": 1}
        found = experiment.recommend(arm)
        self.assertEqual(found["recommendation"], "adopt", found["why"])
        self.assertTrue(any("NullPointerException (1 game)" in why for why in found["why"]), found["why"])

    def test_other_arms_are_evidence_only(self):
        self.assertIsNone(experiment.recommend(_arm("other"))["recommendation"])


# ============================================================ running arms (a stand-in runner.run)

class ArmBase(test_forge.ForgeCase):
    """Decks from self.lists, the stand-in runner.run and pool.session, and E3's side order."""

    def setUp(self):
        super().setUp()
        _with_seqstats(self)
        self.lists = {"casual/green": GREEN, "casual/red": RED, "casual/blue": BLUE}
        summaries = {deck_id: {"id": deck_id, "title": deck_id.split("/")[1].title(), "kind": "casual",
                               "versions": ["target"]} for deck_id in self.lists}
        self.calls, self.effects = [], {}
        self.session = object()
        for p in (mock.patch.object(decks, "find_summary", side_effect=summaries.get),
                  mock.patch.object(decks, "load_deck",
                                    side_effect=lambda deck_id, version: sections(self.lists[deck_id])),
                  mock.patch.object(decks, "engine_kind", return_value="constructed"),
                  mock.patch.object(experiment, "_plan_timing_metadata", side_effect=lambda: ({}, self.settings["forge_workers"])),
                  mock.patch.object(forge.pool, "session", self.stand_in_session),
                  mock.patch.object(forge.runner, "run", self.stand_in_run),
                  mock.patch.object(forge.engine, "side_list", side_list, create=True),
                  mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG))):
            p.start()
            self.addCleanup(p.stop)
        self.out = self.tmp / "exp"
        self.control_dir = self.tmp / "staging"

    def stand_in_session(self, *, local=False):
        case = self

        class Session:
            def __enter__(self):
                return case.session

            def __exit__(self, *exc):
                return False
        return Session()

    def entry(self, deck_id):
        return entry(self.lists[deck_id], deck_id, title=deck_id.split("/")[1].title())

    def eng(self):
        """The engine runner.run plays with the card log (engine.current)."""
        return forge.engine.current(forge.install._setup(), dict(CARD_LOG))

    def key(self, a, b):
        """Today's key of two entries with that engine (a control's key)."""
        return forge.engine.key(a, b, self.eng())

    def game(self, g, flip, ordered):
        """Game g of a stand-in result: seat 1 starts when g's hash is even, the winner's seat is another
        hash, and an effect may hand a list's side the game."""
        deck1 = seeds.deck1_side(g, flip)
        first_seat = 1 if _mix(7, g) % 2 == 0 else 2
        win_seat = 1 if _mix(11, g) % 3 else 2
        side = {1: deck1, 2: 1 - deck1}
        winner = side[win_seat]
        for i, e in enumerate(ordered):
            effect = self.effects.get(((e.get("pilot") or {}).get("profile"), e["id"]))
            if effect and effect(g):
                winner = i
        return {"g": g, "w": winner, "r": "win", "first": side[first_seat], "rounds": 5 + g % 3, "turns": 10,
                "ms": 900 + g % 7, "loss": None, "ai_to": 0}

    def stand_in_run(self, a, b, games, *, by, progress=None, results_dir=None, pool=None, local=False, exact=False,
                     numbers=None, seeds=None, key=None, kind=None, extra=None, override_sets=None, log_dir=None,
                     log_every=1, **kwargs):
        """runner.run as R builds it (section 8), saving a v2 result of stand-in games."""
        self.calls.append({"a": a, "b": b, "games": games, "numbers": numbers, "seeds": seeds, "key": key,
                           "kind": kind, "extra": extra, "override_sets": override_sets, "log_dir": log_dir,
                           "log_every": log_every, "results_dir": results_dir, "pool": pool, "exact": exact})
        eng = self.eng()
        ordered = sorted([a, b], key=side_list)
        key = key or forge.engine.key(a, b, eng)
        folder = Path(results_dir)
        folder.mkdir(parents=True, exist_ok=True)
        existing = forge.saved.load(key, folder)
        if existing is not None:
            stored = existing["seeds"]
            if seeds is not None and seeds != {k: stored[k] for k in ("base", "stream", "flip")}:
                raise ValueError("other seeds")
            base, stream, flip = stored["base"], stored["stream"], stored["flip"]
        elif seeds is not None:
            base, stream, flip = seeds["base"], seeds["stream"], seeds["flip"]
        else:
            base, stream, flip = 1, forge.seeds.stream_hex(forge.seeds.stream_of(a["card_sha"], b["card_sha"])), 0
        start = existing["next_game"] if existing else 0
        numbers = list(numbers) if numbers is not None else list(range(start, start + games))
        assert len(numbers) == games
        played = [self.game(g, flip, ordered) for g in numbers]
        result = existing or {
            "key": key, "format": "Constructed", "forge_version": "2.0.15", "run_version": 2,
            "settings": {"clock_s": 120, "ai": ["Default", "Default"], "xmx": "1024m"},
            "seeds": {"scheme": forge.seeds.SCHEME, "base": base, "stream": stream, "seat_block": 25, "flip": flip},
            "next_game": 0, "sides": [{"card_sha": e["card_sha"], "dck": e["dck"], "card_count": e["card_count"],
                                       "kind": e["kind"], "cards": e["cards"], "seen_as": [],
                                       "pilot": e.get("pilot") or {"profile": "Default", "switches": []}}
                                      for e in ordered],
            "runs": [], "batches": [], "failed": [], "created": "2026-10-03T10:00:00",
            **forge.engine.result_fields(eng)}
        if kind and existing is None:
            result["kind"] = kind
            result.update(extra or {})
        result["runs"].append({"played": games, "wall_s": games / 10, "games_from": min(numbers),
                               "games_to": max(numbers) + 1})
        result["batches"].append({"n": len(result["runs"]) - 1, "first": min(numbers), "games": played,
                                  "casts": [{}, {}], "lands": [{}, {}]})
        result["next_game"] = max(result["next_game"], max(numbers) + 1)
        result["updated"] = "2026-10-03T10:00:01"
        (folder / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")
        forge.saved._read_cache.clear()
        if progress:
            progress(games, games, {})
        return result

    def run_spec(self, spec=SPEC, **kwargs):
        return experiment.run(spec, by="test", results_dir=self.out, **kwargs)


class ArmTests(ArmBase):

    def test_controls_then_arms_on_the_controls_numbers_and_seeds(self):
        found = self.run_spec()
        controls = [c for c in self.calls if c["kind"] is None]
        arms = [c for c in self.calls if c["kind"] == "experiment"]
        self.assertEqual(len(controls), 2)
        self.assertEqual(len(arms), 2)
        for call in controls:
            self.assertEqual(call["games"], 50)
            self.assertEqual(Path(call["results_dir"]), self.out / "control")
            self.assertEqual(Path(call["log_dir"]), self.out / "logs" / "control")
            self.assertEqual(call["log_every"], 1)
            self.assertTrue(call["exact"])
            self.assertIs(call["pool"], self.session)
        for call in arms:
            control = forge.saved.load(self.key(self.entry(call["a"]["id"]), self.entry(call["b"]["id"])),
                                       self.out / "control")
            self.assertEqual(call["numbers"], list(range(50)))
            self.assertEqual({k: call["seeds"][k] for k in ("base", "stream")},
                             {k: control["seeds"][k] for k in ("base", "stream")})
            self.assertEqual(call["a"]["pilot"], {"profile": "Reckless", "switches": []})
            self.assertEqual((call["b"].get("pilot") or {}).get("profile", "Default"), "Default")
            self.assertIsNone(call["override_sets"])
            self.assertEqual(Path(call["log_dir"]), self.out / "logs" / "reck")
            self.assertEqual(call["log_every"], experiment.LOG_EVERY_OTHER)
            self.assertEqual(call["key"], forge.engine._sha({"experiment": "t1", "arm": "reck",
                                                             "control_key": control["key"]}))
            self.assertEqual(call["extra"], {"experiment": {"name": "t1", "arm": "reck",
                                                            "control_key": control["key"],
                                                            "engine_key": self.key(call["a"], call["b"])}})
            saved = json.loads((self.out / "reck" / f"{call['key']}.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["kind"], "experiment")
        # Every list kept its control seat, so the arm played the control's games exactly.
        for row in found["arms"]["reck"]["pairs"]:
            self.assertEqual(row["games"]["paired"], 50)
            self.assertEqual(row["matchup"]["delta"], 0)
            self.assertEqual(row["matchup"]["starter_mismatch"]["games"], 0)
        self.assertTrue((self.out / "experiment.json").exists())
        self.assertIn("## reck", (self.out / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(found["played"], 200)
        self.assertEqual(found["failed"], [])

    def test_running_again_plays_only_whats_missing(self):
        self.run_spec()
        self.calls.clear()
        found = self.run_spec()
        self.assertEqual(self.calls, [])
        self.assertEqual(found["played"], 0)
        self.calls.clear()
        self.run_spec(games=75)                 # more games a pair: the controls, then the arms, top up
        self.assertEqual([c["games"] for c in self.calls if c["kind"] is None], [25, 25])
        self.assertEqual([c["numbers"] for c in self.calls if c["kind"]], [list(range(50, 75))] * 2)

    def test_a_current_control_in_the_control_folder_is_used_and_never_written(self):
        spec = dict(SPEC, pairs=[["casual/green", "casual/red"]])
        self.stand_in_run(self.entry("casual/green"), self.entry("casual/red"), 60, by="staging",
                          results_dir=self.control_dir)
        before = sorted(p.name for p in self.control_dir.iterdir())
        self.calls.clear()
        plan = experiment.plan(spec, results_dir=self.out, control_dir=self.control_dir)
        self.assertEqual(plan["controls"][0]["source"], "control_dir")
        self.assertEqual(plan["totals"], {"control_games": 0, "arm_games": 50, "games": 50})
        self.run_spec(spec, control_dir=self.control_dir)
        self.assertEqual([c["kind"] for c in self.calls], ["experiment"])
        self.assertEqual(self.calls[0]["numbers"], list(range(50)))
        self.assertEqual(sorted(p.name for p in self.control_dir.iterdir()), before)
        # Too few games there: the control is played into the experiment's own folder.
        plan = experiment.plan(spec, results_dir=self.tmp / "exp2", control_dir=self.control_dir, games=80)
        self.assertEqual(plan["controls"][0]["source"], "control")
        self.assertEqual(plan["totals"], {"control_games": 80, "arm_games": 80, "games": 160})

    def test_a_pilot_mirror_arm_keeps_the_piloted_list_in_side_as_seat_and_finds_its_edge(self):
        spec = {"name": "m", "games": 100, "pairs": [["casual/green", "casual/green"]],
                "arms": {"reck": {"pilots": {"casual/green": {"profile": "Reckless"}}, "sides": "a"}}}
        # Reckless Green takes every tenth game it would have lost.
        self.effects[("Reckless", "casual/green")] = lambda g: g % 10 == 0
        found = self.run_spec(spec)
        call = [c for c in self.calls if c["kind"]][0]
        self.assertEqual(call["a"]["pilot"]["profile"], "Reckless")
        self.assertEqual((call["b"].get("pilot") or {}).get("profile", "Default"), "Default")
        saved = forge.saved.load(call["key"], self.out / "reck")
        # Default sorts before Reckless: the piloted list is side 1 of the arm, side 0 (a) of the control.
        self.assertEqual(saved["sides"][1]["pilot"]["profile"], "Reckless")
        control = forge.saved.load(self.key(self.entry("casual/green"), self.entry("casual/green")),
                                   self.out / "control")
        self.assertEqual(saved["seeds"]["flip"], (control["seeds"]["flip"] + 0 + 1) % 2)
        row = found["arms"]["reck"]["pairs"][0]
        self.assertEqual(row["matchup"]["starter_mismatch"]["games"], 0)
        self.assertGreater(row["matchup"]["delta"], 0)
        self.assertEqual(row["matchup"]["strata"]["play"]["c"] + row["matchup"]["strata"]["draw"]["c"], 0)
        self.assertGreater(row["mirror"]["value"], 0.5)

    def test_arms_skip_the_pairs_they_dont_change(self):
        spec = {"name": "s", "games": 20, "pairs": [["casual/green", "casual/red"], ["casual/red", "casual/blue"]],
                "arms": {"reck": {"pilots": {"casual/green": {"profile": "Reckless"}}}}}
        found = self.run_spec(spec)
        self.assertEqual(found["skipped"], [{"arm": "reck", "pair": ["casual/red", "casual/blue"],
                                             "why": "the arm changes nothing in this pair"}])
        self.assertEqual(len([c for c in self.calls if c["kind"]]), 1)

    def test_override_arms_play_in_their_sets_folder_after_the_real_folders_arms(self):
        sets = {"fiery": {"status": "adopted", "files": {"f.txt": {"card": "Fiery Annihilation", "cast_target": 0.8}}},
                "remove": {"status": "experiment", "files": {"d.txt": {"card": "Devout Decree"}}},
                "flash": {"status": "experiment", "files": {"g.txt": {"card": "Gandalf the White"}}}}
        spec = {"name": "o", "games": 20, "pairs": [["casual/green", "casual/red"], ["casual/green", "casual/blue"]],
                "arms": {"none": {"overrides": [], "replace_adopted": True}, "remove": {"overrides": ["remove"]},
                         "flash": {"overrides": ["flash"]},
                         "reck": {"pilots": {"casual/blue": {"profile": "Reckless"}}}}}
        with mock.patch.object(experiment, "_sets", return_value=sets):
            found = self.run_spec(spec)
        arms = [(c["extra"]["experiment"]["arm"], c["override_sets"], c["b"]["id"]) for c in self.calls if c["kind"]]
        self.assertEqual(arms[0], ("reck", None, "casual/blue"))                 # the real folder's arms first
        # Fiery Annihilation is Green's: "none" changes both of its pairs; Devout Decree is Red's.
        self.assertEqual(sorted(arms[1:]), [("none", [], "casual/blue"), ("none", [], "casual/red"),
                                            ("remove", ["fiery", "remove"], "casual/red")])
        self.assertIn({"arm": "flash", "pair": ["casual/green", "casual/red"],
                       "why": "the arm changes nothing in this pair"}, found["skipped"])
        # The spec measures own_lost (every measure by default): every arm tees every chunk.
        self.assertEqual({c["log_every"] for c in self.calls}, {1})
        self.assertEqual(found["arms"]["none"]["kind"], "override")
        with mock.patch.object(experiment, "_sets", return_value=sets):
            limited = dict(spec, measures=["matchup"])
            self.assertEqual(experiment._log_every(experiment.check_spec(limited), "none", ["fiery"]), 1)
            self.assertEqual(experiment._log_every(experiment.check_spec(limited), "reck", ["fiery"]), 10)

    def test_the_shared_seed_arm_plays_on_the_other_pairs_stream_and_seat(self):
        spec = {"name": "sh", "games": 30, "pairs": [["casual/blue", "casual/red"], ["casual/green", "casual/blue"]],
                "arms": {"shared": {"seeds": {"stream_from": ["casual/blue", "casual/green"],
                                              "seat_of": "casual/blue"}}}}
        found = self.run_spec(spec)
        # One control each, though the stream's pair is given in the other order too; the shared arm
        # doesn't play the stream's own pair.
        controls = sorted(tuple(sorted((c["a"]["id"], c["b"]["id"]))) for c in self.calls if c["kind"] is None)
        self.assertEqual(controls, [("casual/blue", "casual/green"), ("casual/blue", "casual/red")])
        self.assertEqual([s["pair"] for s in found["skipped"]], [["casual/green", "casual/blue"]])
        call = [c for c in self.calls if c["kind"]][0]
        blue, green, red = self.entry("casual/blue"), self.entry("casual/green"), self.entry("casual/red")
        bg = forge.saved.load(self.key(blue, green), self.out / "control")
        br = forge.saved.load(self.key(blue, red), self.out / "control")
        self.assertEqual((call["seeds"]["base"], call["seeds"]["stream"]), (bg["seeds"]["base"], bg["seeds"]["stream"]))
        self.assertEqual(call["key"], forge.engine._sha({"experiment": "sh", "arm": "shared",
                                                         "control_key": br["key"]}))
        arm = forge.saved.load(call["key"], self.out / "shared")
        side_bg = [s["card_sha"] for s in bg["sides"]].index(blue["card_sha"])
        side_arm = [s["card_sha"] for s in arm["sides"]].index(blue["card_sha"])
        for g in range(30):
            self.assertEqual(seeds.deck1_side(g, arm["seeds"]["flip"]) == side_arm,
                             seeds.deck1_side(g, bg["seeds"]["flip"]) == side_bg)

    def test_an_override_arm_whose_files_changed_isnt_extended(self):
        sets = {"fiery": {"status": "adopted", "files": {"f.txt": {"card": "Fiery Annihilation"}}},
                "remove": {"status": "experiment", "files": {"d.txt": {"card": "Devout Decree"}}}}
        spec = {"name": "o", "games": 20, "pairs": [["casual/green", "casual/red"]],
                "arms": {"remove": {"overrides": ["remove"]}}}
        real, real_for = forge.overrides.ensure_deployed, forge.overrides.user_dir_for
        arm_folder = self.tmp / "arm-user"

        def folder_for(sets, **kwargs):
            found = real_for(sets, **kwargs)        # the base commit's gives the real folder: E3's another
            return arm_folder if Path(found) == Path(forge.common._user_dir()) else found

        def changed(user_dir):
            if Path(user_dir) == Path(forge.common._user_dir()):
                return real(user_dir)               # the real folder (and with it the control) is unchanged
            try:
                found = real(user_dir)
            except NotImplementedError:
                found = {"index": {}}
            return dict(found, hash="f" * 64)
        with mock.patch.object(experiment, "_sets", return_value=sets):
            self.run_spec(spec)
            with (mock.patch.object(forge.overrides, "ensure_deployed", changed),
                  mock.patch.object(forge.overrides, "user_dir_for", folder_for)):
                found = self.run_spec(dict(spec, games=30))
        self.assertEqual(len(found["failed"]), 1)
        self.assertIn("override files of the arm 'remove' changed", found["failed"][0]["error"])

    def test_it_refuses_unless_the_card_log_can_be_used(self):
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": "Not today."}):
            with self.assertRaisesRegex(forge.ForgeError, "card log .* Not today"):
                self.run_spec()
        self.assertEqual(self.calls, [])

    def test_a_failed_run_is_listed_and_the_others_go_on(self):
        real = self.stand_in_run

        def failing(a, b, games, **kwargs):
            if kwargs.get("kind") and b["id"] == "casual/red":
                raise forge.ForgeError("Forge doesn't know this card.")
            return real(a, b, games, **kwargs)
        with mock.patch.object(forge.runner, "run", failing):
            found = self.run_spec()
        self.assertEqual(found["failed"], [{"arm": "reck", "pair": ["casual/green", "casual/red"],
                                            "error": "Forge doesn't know this card."}])
        self.assertEqual(len(found["arms"]["reck"]["pairs"]), 2)

    def test_an_arm_whose_own_engine_changed_isnt_extended(self):
        self.run_spec()
        call = [c for c in self.calls if c["kind"]][0]
        path = self.out / "reck" / f"{call['key']}.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["experiment"]["engine_key"], self.key(call["a"], call["b"]))
        result["experiment"]["engine_key"] = "0" * 64      # played with, say, another Reckless profile file
        path.write_text(json.dumps(result), encoding="utf-8")
        forge.saved._read_cache.clear()
        found = self.run_spec(games=60)
        self.assertEqual(len(found["failed"]), 1)
        self.assertIn("engine of the arm 'reck'", found["failed"][0]["error"])

    def test_another_key_back_from_a_run_stops_it_as_an_engine_change(self):
        real = self.stand_in_run

        def other(a, b, games, **kwargs):
            result = real(a, b, games, **kwargs)
            return dict(result, key="f" * 64)
        with mock.patch.object(forge.runner, "run", other):
            found = self.run_spec()
        self.assertEqual({f["error"] for f in found["failed"]}, {experiment.ENGINE_CHANGED})

    def test_a_config_arm_plays_in_a_child_process_on_the_parents_controls(self):
        spec = {"name": "c", "games": 10, "pairs": [["casual/green", "casual/red"]],
                "arms": {"perf": {"config": {"forge_performance_mode": False}},
                         "reck": {"pilots": {"casual/green": {"profile": "Reckless"}}}}}
        children = []

        def child(argv, env):
            """The child process, played here: the command line with the child's environment."""
            children.append((argv, {k: env[k] for k in (experiment.CONFIG_ENV, experiment.CHILD_ENV)}))
            self.assertEqual(argv[1:4], ["-m", "decklab.lib.forge", "experiment"])
            with mock.patch.dict(os.environ, {experiment.CHILD_ENV: env[experiment.CHILD_ENV]}), \
                    mock.patch("sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8")), \
                    mock.patch("sys.stderr", io.StringIO()):
                return forge.main(argv[3:])
        with mock.patch.object(experiment, "_child", child):
            found = self.run_spec(spec, local=True)
        self.assertEqual(len(children), 1)
        argv, env = children[0]
        self.assertEqual(argv[argv.index("--only") + 1], "perf")
        self.assertIn("--local", argv)
        self.assertEqual(json.loads(Path(env[experiment.CONFIG_ENV]).read_text(encoding="utf-8")),
                         {"forge_performance_mode": False})
        kinds = [(c["kind"], (c["extra"] or {}).get("experiment", {}).get("arm")) for c in self.calls]
        self.assertEqual(kinds, [(None, None), ("experiment", "reck"), ("experiment", "perf")])
        perf = [c for c in self.calls if c["extra"] and c["extra"]["experiment"]["arm"] == "perf"][0]
        self.assertEqual(perf["numbers"], list(range(10)))
        self.assertEqual(found["arms"]["perf"]["pairs"][0]["games"]["paired"], 10)
        self.assertEqual(found["arms"]["perf"]["kind"], "other")
        self.assertEqual(found["failed"], [])
        # A child that fails fails its arm's runs, and the rest goes on.
        with mock.patch.object(experiment, "_child", return_value=3):
            found = self.run_spec(dict(spec, games=20))
        self.assertEqual(found["failed"], [{"arm": "perf", "pair": ["casual/green", "casual/red"],
                                            "error": "the config arm's process ended with exit code 3"}])

    def test_card_measures_pair_the_logged_games(self):
        """Per-card numbers from (stand-in) logs: the arm casts Grizzly Bears more, and wins with it."""
        spec = {"name": "cards", "games": 40, "pairs": [["casual/green", "casual/red"]],
                "arms": {"reck": {"pilots": {"casual/green": {"profile": "Reckless"}}}},
                "cards": {"Grizzly Bears": {"cast_target": 0.5}}}
        found = self.run_spec(spec)
        call = [c for c in self.calls if c["kind"]][0]
        arm = forge.saved.load(call["key"], self.out / "reck")
        green = [s["card_sha"] for s in arm["sides"]].index(call["a"]["card_sha"])

        def logs(path, flip, names=(), games=None):
            arm_logs = Path(path).name == arm["key"]
            out = {}
            for g in range(40):
                # Drawn in every game (one copy), cast in 40 % of the control's and 80 % of the arm's.
                cast = (g % 5 < 4) if arm_logs else (g % 5 < 2)
                row = [1, 0, 1, int(cast), 0, 3 * int(cast), 0, 0, 1, 0]
                cards, lost = [{}, {}], [{}, {}]
                cards[green] = {"grizzly bears": row}
                lost[green] = {"grizzly bears": [int(cast), int(cast and arm_logs)]}
                out[g] = {"w": None, "first": None, "r": "win", "ai_to": 0, "cards": cards, "lost": lost,
                          "errors": []}
            return out
        with mock.patch.object(experiment, "read_logs", logs):
            found = experiment.measures(spec, results_dir=self.out)
        card = found["arms"]["reck"]["cards"]["Grizzly Bears"]
        self.assertEqual(card["logged_games"], 40)
        self.assertAlmostEqual(card["cast"]["arm"]["value"], 0.8)
        self.assertAlmostEqual(card["cast"]["control"]["value"], 0.4)
        self.assertGreater(card["cast"]["rise"]["delta"], 0.25)
        self.assertGreater(card["cast"]["rise"]["low"], 0)
        self.assertAlmostEqual(card["turn"]["difference"]["delta"], 0.0)
        self.assertAlmostEqual(card["own_lost"]["arm"]["value"], 1.0)
        self.assertAlmostEqual(card["own_lost"]["control"]["value"], 0.0)
        self.assertEqual(card["win_early"]["k"], 1)


class CommandLineTests(ArmBase):
    """The experiment command (cli._cmd_experiment) with the stand-in run."""

    run_main = test_forge.CommandLineTests.run_main

    def write_spec(self, spec=SPEC):
        path = self.tmp / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_the_dry_run_lists_controls_and_arms_and_plays_nothing(self):
        # Arrange an already-deployed disposable fixture; planning must not create it.
        forge.overrides.ensure_deployed(forge.common._user_dir())
        with mock.patch.object(forge.overrides, "ensure_deployed", side_effect=AssertionError("Dry-run deploy")):
            code, out, err = self.run_main(*["experiment", str(self.write_spec()), "--dry-run", "--json",
                                            "--results-dir", str(self.out)])
            self.assertEqual(code, 0, err)
            found = json.loads(out)
            self.assertEqual(found["totals"], {"control_games": 100, "arm_games": 100, "games": 200})
            self.assertEqual([a["arm"] for a in found["arms"]], ["reck", "reck"])
            self.assertEqual(self.calls, [])
            code, out, err = self.run_main(*["experiment", str(self.write_spec()), "--dry-run",
                                            "--results-dir", str(self.out)])
            self.assertIn("In all: 200 games", out)

    def test_a_run_prints_the_report_and_writes_it(self):
        report = self.tmp / "out.md"
        code, out, err = self.run_main(*["experiment", str(self.write_spec()), "--results-dir", str(self.out),
                                        "--report", str(report), "--only", "reck", "--log-every", "5"])
        self.assertEqual(code, 0, err)
        self.assertEqual({c["log_every"] for c in self.calls if c["kind"]}, {5})
        self.assertIn("# Experiment t1", out)
        self.assertEqual(report.read_text(encoding="utf-8"), (self.out / "report.md").read_text(encoding="utf-8"))

    def test_a_bad_spec_or_arm_exits_1(self):
        code, out, err = self.run_main(*["experiment", str(self.write_spec(dict(SPEC, games=0)))])
        self.assertEqual(code, 1)
        self.assertIn("games", err)
        code, out, err = self.run_main(*["experiment", str(self.write_spec()), "--only", "nope", "--dry-run"])
        self.assertEqual(code, 1)
        self.assertIn("no arm called nope", err)


# ============================================================ the fake Forge, through R's runner.run

@unittest.skipUnless(forge.runner.RUN_FEATURES >= R_FEATURES,
                     "needs R's runner.run hooks (sim-wave3-contract.md section 8)")
class FakeForgeTests(test_forge.ForgeCase):
    """An experiment played by the fake Forge in a pool of its own: the arm plays exactly the control's
    game numbers with its seeds, the logs are tee'd, and the measures read them."""

    def setUp(self):
        super().setUp()
        _with_seqstats(self)
        self.lists = {"casual/green": GREEN, "casual/red": RED}
        summaries = {deck_id: {"id": deck_id, "title": deck_id.split("/")[1].title(), "kind": "casual",
                               "versions": ["target"]} for deck_id in self.lists}
        for p in (mock.patch.object(decks, "find_summary", side_effect=summaries.get),
                  mock.patch.object(decks, "load_deck",
                                    side_effect=lambda deck_id, version: sections(self.lists[deck_id])),
                  mock.patch.object(decks, "engine_kind", return_value="constructed"),
                  mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG))):
            p.start()
            self.addCleanup(p.stop)

    def test_a_pilot_arm_on_the_controls_games(self):
        spec = {"name": "fake", "games": 30, "pairs": [["casual/green", "casual/red"]],
                "arms": {"reck": {"pilots": {"casual/green": {"profile": "Reckless"}}}},
                "cards": {"Grizzly Bears": {"cast_target": 0.5}}}
        out = self.tmp / "exp"
        found = experiment.run(spec, by="test", results_dir=out, local=True)
        self.assertEqual(found["failed"], [])
        row = found["arms"]["reck"]["pairs"][0]
        self.assertEqual(row["games"]["paired"], 30)
        self.assertEqual(row["games"]["logged"], 30)
        self.assertEqual(row["matchup"]["starter_mismatch"]["games"], 0)
        self.assertIn("Grizzly Bears", found["arms"]["reck"]["cards"])


if __name__ == "__main__":
    unittest.main()
