"""Tests for adaptive matchup runs (decklab/lib/forge/adaptive.py, simulation wave 3's R12;
forge-trial/sim-wave3-contract.md section 9): the summary the page reads (last_summary,
lead_from_summary, and the lead views.view shows from it), the stages of "assess" and "ahead" runs,
a Stop between looks, the key check between stages, the progress detail, and play --until on the
command line.

Most tests stand a stub in for runner.run (StubRuns: games made up from a seeded coin, saved as a
v2 result), so no Forge process starts. Tests that judge real looks need package S's seqstats; they
skip until it's built (SEQSTATS). One test plays through the fake Forge's warm pool with its
cardwins mode (test_forge_pool's PoolCase).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_adaptive
"""
import io
import json
import random
import unittest
from unittest import mock

from decklab.lib import forge, jobs
from decklab.lib.forge import adaptive, cli, common, seqstats, views
from decklab.tests import test_forge
from decklab.tests.test_forge import GREEN, RED, entry


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def _seqstats_built():
    try:
        seqstats.last_look(3200)
        return True
    except NotImplementedError:
        return False


SEQSTATS = _seqstats_built()
NEEDS_S = "needs package S's seqstats (wave 3, merge 1)"
KEY = "e" * 64
A = {"id": "casual/aaa", "version": "target", "title": "Aaa", "kind": "constructed", "card_sha": "a" * 64,
     "card_count": 24}
B = {"id": "casual/bbb", "version": "target", "title": "Bbb", "kind": "constructed", "card_sha": "b" * 64,
     "card_count": 24}


def side(e):
    return {"card_sha": e["card_sha"], "dck": "", "card_count": 24, "kind": "constructed",
            "cards": {"Commander": [], "Main": [[4, "Grizzly Bears"], [20, "Forest"]]},
            "seen_as": [{"id": e["id"], "version": "target", "title": e["title"], "source": None,
                         "when": "2026-10-03T10:00:00"}]}


def result_with(games, key=KEY, runs=None):
    """A v2 result holding games (dicts with g, w, r, first) in one batch."""
    return {"key": key, "format": "Constructed", "forge_version": "2.0.15", "run_version": 2,
            "settings": {"clock_s": 120, "ai": ["Default", "Default"], "xmx": "1024m"},
            "seeds": {"scheme": "test", "base": 1, "stream": "0" * 16, "seat_block": 25, "flip": 0},
            "next_game": len(games), "sides": [side(A), side(B)],
            "runs": runs if runs is not None else [{"when": "2026-10-03T10:00:00", "by": "Matt", "played": len(games),
                                                    "asked": len(games), "wall_s": 10.0, "stopped": False,
                                                    "error": None, "startup_s": 1.0, "workers": 4, "failed": 0,
                                                    "pool": "local"}],
            "batches": [{"n": 0, "first": 0, "games": games, "casts": [{}, {}], "lands": [{}, {}]}] if games else [],
            "failed": [], "created": "2026-10-03T10:00:00", "updated": "2026-10-03T10:00:00"}


def made_games(first_g, n, strength, rng, draws=0.0):
    """n games numbered from first_g: side 0 wins with chance strength (a draw with chance draws)."""
    out = []
    for g in range(first_g, first_g + n):
        start = rng.randrange(2)
        if rng.random() < draws:
            w, r = None, "draw"
        else:
            w, r = (0 if rng.random() < strength else 1), "win"
        out.append({"g": g, "w": w, "r": r, "first": start, "rounds": 6, "turns": 12, "ms": 900,
                    "loss": None, "ai_to": 0})
    return out


class StubRuns:
    """runner.run's stand-in: each call adds `games` made-up games to the result KEY in results_dir
    (one batch per run, as v2 saves them), reporting progress twice, and returns it. stop_in: the
    call (from 1) that saves half its games and then raises jobs.Stopped. keys: the key each call
    returns (default KEY)."""

    def __init__(self, results_dir, strength=0.5, seed=1, draws=0.0, stop_in=None, keys=None, fail_in=None):
        self.dir, self.strength, self.draws = results_dir, strength, draws
        self.rng = random.Random(seed)
        self.stop_in, self.keys, self.fail_in = stop_in, keys, fail_in
        self.calls = []

    def __call__(self, entry_a, entry_b, games, *, by, progress=None, results_dir=None, exact=False, **kwargs):
        self.calls.append({"games": games, "exact": exact, **kwargs})
        call = len(self.calls)
        if call == self.fail_in:
            raise common.ForgeError("No games could be played: Forge stopped.")
        path = self.dir / f"{KEY}.json"
        result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else result_with([], runs=[])
        before = sum(len(b["games"]) for b in result["batches"])
        stopping = call == self.stop_in
        played = games // 2 if stopping else games
        new = made_games(before, played, self.strength, self.rng, self.draws)
        ordinal = len(result["runs"])
        result["runs"].append({"when": "2026-10-03T11:00:00", "by": by, "asked": games, "played": played,
                               "wall_s": 5.0, "stopped": stopping, "error": None, "pool": "local",
                               "games_from": before, "games_to": before + games})
        if new:
            result["batches"].append({"n": ordinal, "first": before, "games": new, "casts": [{}, {}],
                                      "lands": [{}, {}]})
        result["next_game"] = before + games
        result["key"] = KEY
        path.parent.mkdir(parents=True, exist_ok=True)
        common._write_atomic(path, json.dumps(result))
        if progress is not None:
            wins = [sum(g["w"] == s for g in new) for s in (0, 1)]
            progress(0, games, {"wins": [0, 0], "other": 0, "failed_batches": 0})
            progress(played, games, {"wins": wins, "other": played - sum(wins), "failed_batches": 0})
        if stopping:
            stop = jobs.Stopped(jobs.STOPPED)
            stop.by = "User1"
            raise stop
        out = dict(result)
        if self.keys:
            out["key"] = self.keys[min(call, len(self.keys)) - 1]
        return out


class AdaptiveCase(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.results.mkdir(parents=True, exist_ok=True)
        p = mock.patch.object(adaptive, "matchup_key", lambda a, b: KEY)
        p.start()
        self.addCleanup(p.stop)

    def stub(self, **kwargs):
        runs = StubRuns(self.results, **kwargs)
        p = mock.patch.object(adaptive.runner, "run", runs)
        p.start()
        self.addCleanup(p.stop)
        return runs

    def saved(self):
        return json.loads((self.results / f"{KEY}.json").read_text(encoding="utf-8"))

    def play(self, mode, **kwargs):
        kwargs.setdefault("results_dir", self.results)
        kwargs.setdefault("pool", object())         # never a real pool: runner.run is the stub
        return adaptive.run_adaptive(A, B, mode, by="Matt", **kwargs)


# ============================================================ the summary the page reads

class SummaryTests(test_forge.ForgeCase):

    def summary(self, **extra):
        return {"mode": "ahead", "key": KEY, "games_before": 0, "games_after": 4, "max_games": 3200,
                "stages": [], "looks": [], "outcome": "ahead", "decision": "ahead", "side": 1,
                "half_width": 0.05, "range": None, **extra}

    def test_the_last_summary_applies_while_the_result_has_its_games(self):
        games = made_games(0, 4, 0.5, random.Random(1))
        result = result_with(games)
        result["adaptive"] = [self.summary(games_after=2), self.summary()]
        self.assertEqual(adaptive.last_summary(result)["games_after"], 4)
        result["batches"][0]["games"].append(made_games(4, 1, 0.5, random.Random(2))[0])
        self.assertIsNone(adaptive.last_summary(result))         # later games: the plain view counts
        for bad in (None, [], ["x"], [{"games_after": "4"}]):
            self.assertIsNone(adaptive.last_summary(dict(result_with(games), adaptive=bad)))

    def test_the_lead_from_a_summary(self):
        self.assertEqual(adaptive.lead_from_summary(self.summary()), {"verdict": "ahead", "side": 1, "basis": "adaptive"})
        stopped = self.summary(outcome="stopped", decision="not_settled_stopped", side=None)
        self.assertEqual(adaptive.lead_from_summary(stopped), {"verdict": "not_settled", "side": None, "basis": "adaptive"})
        self.assertEqual(adaptive.lead_from_summary(self.summary(decision="about_even", side=0))["side"], None)
        for no_lead in (self.summary(mode="assess", outcome="precise", decision=None, side=None),
                        self.summary(side=None), self.summary(side=True), self.summary(decision="continue"), None):
            self.assertIsNone(adaptive.lead_from_summary(no_lead))

    def test_the_page_shows_the_summarys_lead_from_its_side(self):
        games = [dict(g, w=1) for g in made_games(0, 4, 0.5, random.Random(1))]
        result = result_with(games)
        result["adaptive"] = [self.summary()]                    # stored side 1 (Bbb) is ahead
        from_a = views.view(result, A["card_sha"])
        self.assertEqual(from_a["adaptive_last"]["outcome"], "ahead")
        self.assertEqual(from_a["lead"], {"verdict": "ahead", "side": 1, "basis": "adaptive"})
        self.assertEqual(views.view(result, B["card_sha"])["lead"]["side"], 0)

    def test_words(self):
        titles = ("Aaa", "Bbb")
        self.assertEqual(adaptive.words(self.summary(games_after=1600), titles),
                         "This run stopped at a planned check after 1,600 games: Bbb is clearly ahead.")
        self.assertEqual(adaptive.words(self.summary(outcome="precise", decision=None, side=None, half_width=0.028,
                                                     mode="assess"), titles),
                         "This run stopped at a planned check after 4 games: the win rate is known to within "
                         "±2.8 points of win rate.")
        self.assertIn("without a clear leader", adaptive.words(self.summary(outcome="not_settled",
                                                                            decision="not_settled"), titles))
        stopped = self.summary(outcome="stopped", decision="not_settled_stopped", side=None, games_after=650,
                               range={"value": 0.55, "low": 0.49, "high": 0.62})
        self.assertEqual(adaptive.words(stopped, titles), "Stopped early after 650 games, between checks. A range "
                         "that allows for stopping at any time: 49-62 %. Not settled.")
        self.assertTrue(adaptive.words(dict(stopped, decision="ahead", side=0), titles).endswith(
            "Aaa is clearly ahead even so."))
        self.assertIsNone(adaptive.words(None, titles))


# ============================================================ stages (a stub run)

class StageTests(AdaptiveCase):

    def test_modes_and_limits(self):
        for bad in ("fixed", "both", None):
            with self.assertRaises(ValueError):
                self.play(bad)
        for most in (399, 3201, 800.0, True):
            with self.assertRaises(ValueError):
                self.play("ahead", max_games=most)

    def test_an_ahead_run_looks_at_each_check_until_it_decides(self):
        runs = self.stub()
        decisions = iter(["continue", "continue", "ahead"])

        def look(games, p, n_total, *, max_games=3200, stopped=False):
            decision = next(decisions)
            return {"look": n_total, "z": 3.5 if decision == "ahead" else 1.0, "bound": 3.0, "low": 0.4,
                    "high": 0.6, "decision": decision, "side": 1 if decision == "ahead" else None}

        def ahead_next(games, p, *, max_games=3200):
            later = [x for x in (400, 800, 1600, 3200) if len(games) < x <= max_games]
            return (later[0] - len(games), later[0]) if later else (0, None)

        calls = []
        with mock.patch.object(seqstats, "look", look), mock.patch.object(seqstats, "ahead_next", ahead_next):
            result = self.play("ahead", progress=lambda done, total, detail: calls.append((done, total, detail)))
        self.assertEqual([c["games"] for c in runs.calls], [400, 400, 800])
        self.assertTrue(all(c["exact"] for c in runs.calls))
        [summary] = result["adaptive"]
        self.assertEqual(self.saved()["adaptive"], [summary])
        self.assertEqual((summary["mode"], summary["outcome"], summary["decision"], summary["side"]),
                         ("ahead", "ahead", "ahead", 1))       # look side 1 = B's stored side (A is p, side 0)
        self.assertEqual((summary["games_before"], summary["games_after"], summary["key"]), (0, 1600, KEY))
        self.assertEqual([s["games"] for s in summary["stages"]], [400, 400, 800])
        self.assertEqual([s["run"] for s in summary["stages"]], [0, 1, 2])
        self.assertEqual([lk["games"] for lk in summary["looks"]], [400, 800, 1600])
        self.assertEqual(adaptive.last_summary(result), summary)
        # Progress: the plan's total grows; the detail has the plan, the live range per side and the looks.
        totals = sorted({total for _, total, _ in calls})
        self.assertEqual(totals, [400, 800, 1600])
        done, total, detail = calls[-1]
        self.assertEqual((done, total), (1600, 1600))
        self.assertEqual(detail["plan"], {"mode": "ahead", "stage": 3, "next_look": 1600, "max": 3200,
                                          "planned": 1600, "games_before": 0})
        self.assertEqual(len(detail["looks"]), 2)
        self.assertEqual(sum(detail["wins"]) + detail["other"], 1600)
        self.assertEqual(len(detail["range"]), 2)

    def test_an_assess_run_plays_its_pilot_its_plan_and_one_top_up(self):
        runs = self.stub()
        answers = iter([(400, "pilot"), (600, "plan"), (200, "plan"), (100, "plan")])
        with mock.patch.object(seqstats, "assess_next", lambda *a, **k: next(answers)), \
                mock.patch.object(adaptive, "_half_width", lambda games, p: 0.04):
            result = self.play("assess")
        self.assertEqual([c["games"] for c in runs.calls], [400, 600, 200])
        [summary] = result["adaptive"]
        self.assertEqual([s["reason"] for s in summary["stages"]], ["pilot", "plan", "top-up"])
        self.assertEqual((summary["outcome"], summary["decision"], summary["side"]), ("capped_at_plan", None, None))
        self.assertEqual(summary["games_after"], 1200)
        self.assertIsNone(adaptive.lead_from_summary(summary))      # the plain lead stands

    def test_an_assess_run_stops_when_precise(self):
        self.stub()
        answers = iter([(400, "pilot"), (0, "precise")])
        with mock.patch.object(seqstats, "assess_next", lambda *a, **k: next(answers)):
            result = self.play("assess", max_games=1600)
        self.assertEqual(result["adaptive"][-1]["outcome"], "precise")
        self.assertEqual(result["adaptive"][-1]["max_games"], 1600)

    def test_no_check_left_plays_nothing(self):
        runs = self.stub()
        common._write_atomic(self.results / f"{KEY}.json",
                             json.dumps(result_with(made_games(0, 3300, 0.5, random.Random(3)))))
        with mock.patch.object(seqstats, "ahead_next", lambda games, p, max_games=3200: (0, None)):
            result = self.play("ahead")
        self.assertEqual(runs.calls, [])
        self.assertNotIn("adaptive", result)

    def ahead_looks(self, decisions):
        """seqstats.look and ahead_next stand-ins: look answers decisions in turn (side 0 for "ahead")."""
        decisions = iter(decisions)
        seen = []

        def look(games, p, n_total, *, max_games=3200, stopped=False):
            decision = next(decisions)
            seen.append((n_total, len(games), max_games, stopped))
            return {"look": n_total, "z": 3.5 if decision == "ahead" else 1.0, "bound": 3.0, "low": 0.6,
                    "high": 0.7, "decision": decision, "side": 0 if decision == "ahead" else None,
                    "basis": "decided"}

        def ahead_next(games, p, *, max_games=3200):
            later = [x for x in (400, 800, 1600, 3200) if len(games) < x <= max_games]
            return (later[0] - len(games), later[0]) if later else (0, None)

        for patch in (mock.patch.object(seqstats, "look", look), mock.patch.object(seqstats, "ahead_next", ahead_next)):
            patch.start()
            self.addCleanup(patch.stop)
        return seen

    def saved_games(self, n, strength=0.5):
        common._write_atomic(self.results / f"{KEY}.json",
                             json.dumps(result_with(made_games(0, n, strength, random.Random(3)))))

    def test_an_ahead_run_from_a_result_on_a_check_looks_there_first(self):
        # Section 7.3: a result already on a check makes that look first; when it decides, nothing plays and a
        # summary with no stages is recorded.
        runs = self.stub()
        self.saved_games(400, 0.85)
        seen = self.ahead_looks(["ahead"])
        result = self.play("ahead")
        self.assertEqual(runs.calls, [])
        self.assertEqual(seen, [(400, 400, 3200, False)])
        [summary] = result["adaptive"]
        self.assertEqual((summary["outcome"], summary["decision"], summary["side"]), ("ahead", "ahead", 0))
        self.assertEqual((summary["games_before"], summary["games_after"], summary["stages"]), (400, 400, []))
        self.assertEqual([lk["games"] for lk in summary["looks"]], [400])
        self.assertEqual(adaptive.last_summary(self.saved()), summary)

    def test_a_look_on_a_check_that_goes_on_plays_to_the_next(self):
        runs = self.stub()
        self.saved_games(800)
        seen = self.ahead_looks(["continue", "ahead"])
        summary = self.play("ahead")["adaptive"][-1]
        self.assertEqual([c["games"] for c in runs.calls], [800])
        self.assertEqual([n for n, *_ in seen], [800, 1600])
        self.assertEqual([lk["games"] for lk in summary["looks"]], [800, 1600])
        self.assertEqual((summary["games_before"], summary["games_after"]), (800, 1600))

    def test_a_result_at_the_last_check_gets_its_final_look(self):
        # 1,600 games with --max 1600: the final look (at 2.008) happens, and nothing plays.
        runs = self.stub()
        self.saved_games(1600)
        seen = self.ahead_looks(["not_settled"])
        result = self.play("ahead", max_games=1600)
        self.assertEqual((runs.calls, seen), ([], [(1600, 1600, 1600, False)]))
        self.assertEqual((result["adaptive"][-1]["outcome"], result["adaptive"][-1]["stages"]), ("not_settled", []))

    def test_a_result_past_max_isnt_looked_at_first(self):
        self.stub()
        self.saved_games(800)
        seen = self.ahead_looks([])
        result = self.play("ahead", max_games=400)          # 800 games: past every check up to 400
        self.assertEqual(seen, [])
        self.assertNotIn("adaptive", result)

    def test_a_failure_recording_a_stop_still_raises_the_stop(self):
        self.stub(stop_in=1)
        with mock.patch.object(adaptive._Adaptive, "_stopped", side_effect=OSError("disk gone")), \
                mock.patch.object(seqstats, "assess_next", lambda *a, **k: (400, "pilot")), \
                mock.patch.object(common, "_log") as log:
            with self.assertRaises(jobs.Stopped):
                self.play("assess")
        self.assertIn("disk gone", log.call_args[0][0])

    def test_a_failure_recording_an_error_still_raises_the_error(self):
        self.stub(fail_in=1)
        with mock.patch.object(adaptive._Adaptive, "_finish", side_effect=OSError("disk gone")), \
                mock.patch.object(seqstats, "assess_next", lambda *a, **k: (400, "pilot")), \
                mock.patch.object(common, "_log"):
            with self.assertRaisesRegex(common.ForgeError, "Forge stopped"):
                self.play("assess")

    def test_a_stop_between_checks_is_judged_as_a_stopped_look(self):
        runs = self.stub(stop_in=2)
        seen = []

        def look(games, p, n_total, *, max_games=3200, stopped=False):
            seen.append((n_total, stopped))
            return {"look": n_total, "z": 1.0, "bound": 3.0, "low": 0.45, "high": 0.6,
                    "decision": "not_settled_stopped" if stopped else "continue", "side": None}

        def ahead_next(games, p, *, max_games=3200):
            later = [x for x in (400, 800, 1600, 3200) if len(games) < x]
            return later[0] - len(games), later[0]

        with mock.patch.object(seqstats, "look", look), mock.patch.object(seqstats, "ahead_next", ahead_next), \
                mock.patch.object(seqstats, "anytime_range", lambda games, p: (0.55, 0.49, 0.62)):
            with self.assertRaises(jobs.Stopped):
                self.play("ahead")
        self.assertEqual(len(runs.calls), 2)
        self.assertEqual(seen, [(400, False), (600, True)])
        [summary] = self.saved()["adaptive"]
        self.assertEqual((summary["outcome"], summary["decision"], summary["games_after"]),
                         ("stopped", "not_settled_stopped", 600))
        self.assertEqual(summary["looks"][-1]["stopped"], True)
        self.assertEqual([s["games"] for s in summary["stages"]], [400, 200])
        self.assertEqual(summary["range"], {"value": 0.55, "low": 0.49, "high": 0.62})
        self.assertEqual(len(summary["ranges"]), 2)
        self.assertEqual(adaptive.lead_from_summary(summary)["verdict"], "not_settled")

    def test_a_stop_before_any_game_records_nothing(self):
        self.stub()

        def progress(done, total, detail):
            raise jobs.Stopped(jobs.STOPPED)

        with mock.patch.object(seqstats, "ahead_next", lambda games, p, max_games=3200: (400, 400)):
            with self.assertRaises(jobs.Stopped):
                self.play("ahead", progress=progress)
        self.assertFalse((self.results / f"{KEY}.json").exists())

    def test_another_key_between_stages_stops_the_run(self):
        runs = self.stub(keys=[KEY, "f" * 64])
        with mock.patch.object(seqstats, "look", lambda *a, **k: {"look": 400, "z": 0.5, "bound": 3.0, "low": 0.4,
                                                                    "high": 0.6, "decision": "continue", "side": None}), \
                mock.patch.object(seqstats, "ahead_next",
                                  lambda games, p, max_games=3200: (400, len(games) + 400)):
            with self.assertRaises(common.ForgeError) as caught:
                self.play("ahead")
        self.assertEqual(str(caught.exception), adaptive.ENGINE_CHANGED)
        self.assertEqual(len(runs.calls), 2)
        self.assertEqual(self.saved()["adaptive"][-1]["outcome"], "error")

    def test_an_error_is_recorded_and_raised(self):
        self.stub(fail_in=2)
        with mock.patch.object(seqstats, "look", lambda *a, **k: {"look": 400, "z": 0.5, "bound": 3.0, "low": 0.4,
                                                                    "high": 0.6, "decision": "continue", "side": None}), \
                mock.patch.object(seqstats, "ahead_next",
                                  lambda games, p, max_games=3200: (400, len(games) + 400)):
            with self.assertRaises(common.ForgeError):
                self.play("ahead")
        [summary] = self.saved()["adaptive"]
        self.assertEqual((summary["outcome"], summary["decision"], summary["games_after"]), ("error", None, 400))

    def test_the_log_options_go_to_each_stage(self):
        runs = self.stub()
        answers = iter([(400, "pilot"), (0, "precise")])
        with mock.patch.object(seqstats, "assess_next", lambda *a, **k: next(answers)):
            self.play("assess", log_dir="L", log_every=5, seed_base=3)
        self.assertEqual((runs.calls[0]["log_dir"], runs.calls[0]["log_every"], runs.calls[0]["seed_base"]), ("L", 5, 3))

    def test_the_summary_waits_for_the_matchups_lock(self):
        self.stub()
        answers = iter([(400, "pilot"), (0, "precise")])
        held = adaptive.runner._claim(self.results, KEY)
        released = []

        def sleep(seconds):
            if not released:
                adaptive.runner._release(held, self.results / f"{KEY}.lock")
                released.append(True)

        with mock.patch.object(seqstats, "assess_next", lambda *a, **k: next(answers)), \
                mock.patch.object(adaptive.time, "sleep", sleep), mock.patch.object(adaptive.runner, "update_result",
                                                                                 None, create=True):
            self.play("assess")
        self.assertEqual(released, [True])
        self.assertEqual(self.saved()["adaptive"][-1]["outcome"], "precise")


@unittest.skipUnless(SEQSTATS, NEEDS_S)
class RealLookTests(AdaptiveCase):
    """With package S's looks: a lopsided pair stops at the first check, an even one is about even or
    reaches 3,200 games, and draws that leave the lead unsettled give "not settled"."""

    def test_a_lopsided_pair_stops_at_400(self):
        self.stub(strength=0.85)
        summary = self.play("ahead")["adaptive"][-1]
        self.assertEqual((summary["outcome"], summary["games_after"], summary["side"]), ("ahead", 400, 0))
        self.assertEqual(views.view(self.saved(), A["card_sha"])["lead"]["verdict"], "ahead")

    def test_a_lopsided_400_game_result_plays_nothing(self):
        common._write_atomic(self.results / f"{KEY}.json",
                             json.dumps(result_with(made_games(0, 400, 0.85, random.Random(6)))))
        runs = self.stub(strength=0.85)
        summary = self.play("ahead")["adaptive"][-1]
        self.assertEqual(runs.calls, [])
        self.assertEqual((summary["outcome"], summary["games_before"], summary["games_after"], summary["side"]),
                         ("ahead", 400, 400, 0))
        self.assertEqual(views.view(self.saved(), A["card_sha"])["lead"]["verdict"], "ahead")

    def test_an_even_pair_ends_about_even_or_at_3200(self):
        self.stub(strength=0.5, seed=7)
        summary = self.play("ahead")["adaptive"][-1]
        # (An even pair is "ahead" by chance about 5 % of the time: the seed is fixed.)
        self.assertIn(summary["outcome"], ("about_even", "not_settled", "slightly_ahead", "ahead"))
        self.assertIn(summary["games_after"], (400, 800, 1600, 3200))
        self.assertEqual(summary["games_after"], summary["looks"][-1]["games"])
        if summary["outcome"] == "not_settled":
            self.assertEqual(summary["games_after"], 3200)

    def test_draws_that_leave_the_lead_unsettled_are_not_settled(self):
        # Side 0 wins 53 % of the decided games, a third of the games are draws: the decided share's z
        # passes 2.008 at 3,200 games, but views._lead (draws count against both decks) isn't settled.
        self.stub(strength=0.535, draws=0.33, seed=11)
        summary = self.play("ahead")["adaptive"][-1]
        if summary["games_after"] == 3200:
            last = summary["looks"][-1]
            lead = views._lead(views._games(self.saved()), 0,
                               views._winrate(views._games(self.saved()), 0)["winrate"],
                               views._comparison(views._games(self.saved()), 0))
            if lead["side"] is None:
                self.assertNotEqual(last["decision"], "ahead")

    def test_an_assess_run_from_a_result_past_the_pilot_plays_its_plan_first(self):
        # S's review: with more than 400 games saved, a half-width just over 3 points must still get its plan
        # stage (assess_next's plan_done), not stop at once as "capped at plan".
        common._write_atomic(self.results / f"{KEY}.json",
                             json.dumps(result_with(made_games(0, 1000, 0.5, random.Random(4)))))
        self.stub(strength=0.5, seed=9)
        width = adaptive._half_width(views._games(self.saved()), 0)
        summary = self.play("assess")["adaptive"][-1]
        if width > seqstats.ASSESS_HALF_WIDTH:
            self.assertEqual(summary["stages"][0]["reason"], "plan")
            self.assertGreaterEqual(summary["stages"][0]["games"], 100)
        self.assertEqual(summary["games_before"], 1000)

    def test_an_assess_run_reaches_its_half_width_or_its_plan(self):
        self.stub(strength=0.6, seed=5)
        summary = self.play("assess")["adaptive"][-1]
        self.assertIn(summary["outcome"], ("precise", "capped", "capped_at_plan"))
        self.assertEqual(summary["stages"][0], {"run": 0, "games": 400, "reason": "pilot"})
        self.assertGreater(summary["games_after"], 400)


# ============================================================ through the fake Forge

@unittest.skipUnless(SEQSTATS, NEEDS_S)
class FakeForgeTests(unittest.TestCase):
    """An "ahead" run through the fake Forge's warm pool: with cardwins, a seat holding Grizzly Bears
    early wins, so Green is far ahead and the run stops at its first check."""

    def setUp(self):
        from decklab.tests import test_forge_pool
        self.case = test_forge_pool.PoolCase("run")
        self.case.run = lambda: None
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_cardwins_makes_a_lopsided_pair_stop_at_400(self):
        self.case.fake("cardwins=Grizzly Bears")
        a, b = entry(GREEN, "casual/green"), entry(RED, "casual/red")
        result = adaptive.run_adaptive(a, b, "ahead", by="Matt", results_dir=self.case.results, local=True)
        summary = result["adaptive"][-1]
        self.assertEqual((summary["outcome"], summary["games_after"]), ("ahead", 400))
        green = 0 if result["sides"][0]["card_sha"] == a["card_sha"] else 1
        self.assertEqual(summary["side"], green)
        self.assertTrue(forge.saved._is_result(json.loads((self.case.results / f"{result['key']}.json")
                                                          .read_text(encoding="utf-8")), result["key"]))
        self.assertTrue(self.case.all_dead())


# ============================================================ the command line

class CommandLineTests(AdaptiveCase):

    def cli(self, *argv):
        """(exit code, stdout, stderr) of forge.main(argv), as test_forge's CommandLineTests run it."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.main(list(argv))
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_until_refuses_what_a_set_number_takes(self):
        for extra in (["--games", "400"], ["--batch", "50"], ["--no-save"], ["--a-first"]):
            code, _, err = self.cli("play", "x.dck", "y.dck", "--until", "ahead", *extra)
            self.assertEqual(code, 1)
            self.assertIn("doesn't go with --until", err)
        code, _, err = self.cli("play", "x.dck", "y.dck", "--max", "800")
        self.assertEqual((code, err.strip()), (1, "--max goes with --until."))
        code, _, err = self.cli("play", "x.dck", "y.dck", "--until", "assess", "--max", "300")
        self.assertIn("--max must be from 400", err)

    def nothing_played(self, mode, summary=None, strength=0.6, n=800):
        """play --until mode's stderr when run_adaptive plays nothing and returns a result of n games."""
        def run_adaptive(a, b, mode, *, by, progress=None, max_games=3200, **kwargs):
            result = result_with(made_games(0, n, strength, random.Random(2)))
            result["sides"] = [side(dict(a, id="casual/green")), side(dict(b, id="casual/red"))]
            if summary is not None:
                result["adaptive"] = [dict(summary, games_before=n, games_after=n)]
            return result

        with mock.patch.object(adaptive, "run_adaptive", run_adaptive):
            code, out, err = self.cli("play", "casual/green", "casual/red", "--until", mode)
        self.assertEqual(code, 0, err)
        return err

    def test_until_says_why_nothing_played(self):
        err = self.nothing_played("ahead", n=3200)
        self.assertIn("past every check", err)
        look = {"games": 800, "z": 3.5, "bound": 3.0, "low": 0.6, "high": 0.7, "decision": "ahead", "stopped": False}
        err = self.nothing_played("ahead", {"mode": "ahead", "key": KEY, "max_games": 3200, "stages": [],
                                            "looks": [look], "outcome": "ahead", "decision": "ahead", "side": 0,
                                            "half_width": 0.03, "range": None})
        self.assertIn("Look at 800 games: z = 3.50 >= 3.00", err)
        self.assertIn("already at a check, and that look decided", err)
        err = self.nothing_played("assess", n=3200)
        self.assertIn("already known to within", err)
        self.assertNotIn("check", err)
        err = self.nothing_played("assess", n=400)          # too few games to be within 3 points: capped
        self.assertIn("as many games as this run would play", err)

    def test_until_ahead_rounds_max_down_to_a_check_and_prints_each_look(self):
        seen = {}
        summary = {"mode": "ahead", "key": KEY, "games_before": 0, "games_after": 800, "max_games": 800,
                   "stages": [], "outcome": "ahead", "decision": "ahead", "side": 0, "half_width": 0.03,
                   "range": None,
                   "looks": [{"games": 400, "z": 1.5, "bound": 3.0, "low": 0.4, "high": 0.6, "decision": "continue",
                              "stopped": False},
                             {"games": 800, "z": 2.5, "bound": 2.008, "low": 0.51, "high": 0.6, "decision": "ahead",
                              "stopped": False}]}

        def run_adaptive(a, b, mode, *, by, progress=None, max_games=3200, **kwargs):
            seen.update(mode=mode, max_games=max_games, by=by)
            progress(0, 400, {"plan": {"mode": "ahead", "stage": 1, "next_look": 400, "max": 800, "planned": 400,
                                       "games_before": 0}, "looks": [], "wins": [0, 0], "other": 0,
                              "range": [None, None]})
            progress(0, 800, {"plan": {"mode": "ahead", "stage": 2, "next_look": 800, "max": 800, "planned": 800,
                                       "games_before": 0}, "looks": summary["looks"][:1], "wins": [250, 150],
                              "other": 0, "range": [{"value": 0.6, "low": 0.5, "high": 0.7}, None]})
            games = made_games(0, 800, 0.6, random.Random(2))
            result = result_with(games)
            result["sides"] = [side(dict(a, id="casual/green")), side(dict(b, id="casual/red"))]
            result["adaptive"] = [summary]
            return result

        with mock.patch.object(adaptive, "run_adaptive", run_adaptive):
            code, out, err = self.cli("play", "casual/green", "casual/red", "--until", "ahead", "--max", "1000")
        self.assertEqual(code, 0, err)
        self.assertEqual(seen, {"mode": "ahead", "max_games": 800, "by": "command line"})
        self.assertIn("Look at 400 games: z = 1.50 < 3.00, going on to 800", err)
        self.assertIn("Look at 800 games: z = 2.50 >= 2.01: ", err)
        self.assertIn("This run stopped at a planned check after 800 games", out)
        self.assertIn("(z = 2.50; needed 2.01)", out)

    def setUp(self):
        super().setUp()
        p = mock.patch.object(cli, "_cli_entry", lambda ref, owned: dict(
            A if "green" in ref else B, id=ref, title=ref.split("/")[-1].title()))
        p.start()
        self.addCleanup(p.stop)


if __name__ == "__main__":
    unittest.main()
