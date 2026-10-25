"""Matchups runs tests; shared fixtures remain in test_matchups_api."""
import unittest
import json
import os
import sys
import threading
import time
import types
from unittest import mock
from decklab.lib import api, cards, decks, jobs
from decklab.lib import forge as real_forge
from decklab.tests import test_forge
from decklab.tests.test_api import _write
from decklab.tests.test_matchups_api import (
    GRUUL_ID, MatchupTestCase, WAIT, body, deck_file,
)


class RealForgeTests(MatchupTestCase):
    """The api over the real forge package (review finding QUALITY-2: FakeForge only stands in
    for it), with test_forge's made-up Forge folder and fixtures/fake_forge.py playing the
    games, the forge fixtures' card index, and two of test_forge's lists as deck files."""

    RED_ID, GREEN_ID = "casual/red-test", "casual/green-test"

    def setUp(self):
        super().setUp()
        root = self.box.root
        test_forge.make_forge(root / "forge-app")
        settings = {"forge_dir": str(root / "forge-app"), "forge_java": sys.executable, "forge_workers": 2,
                    "forge_batch_games": 200, "forge_clock_s": 120, "forge_xmx": "1024m"}
        for target, name, value in ((real_forge.common, "DATA_DIR", self.box.data / "forge"),
                                    (real_forge.common, "_settings", lambda: dict(settings)),
                                    (real_forge.runner, "build_command", test_forge.fake_command),
                                    # the warm pool's workers, for runs with the card log said to be ready
                                    (real_forge.runner, "serve_command", test_forge.fake_serve_command),
                                    (real_forge.ai, "TAG_FILE", test_forge.TAGS_FILE)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        test_forge.pin_override_sets(self)
        self.addCleanup(self.forget)
        self.forget()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("FAKE_FORGE", None)
        os.environ.pop("FAKE_FORGE_LOG", None)
        # The cards those lists use (the sandbox's index file, read on first use).
        index = cards.build_index(test_forge.HERE / "forge_cards.jsonl", test_forge.TAGS_FILE,
                                  {"default_cards": "2026-09-28"}, log=lambda *a: None)
        cards.write_index(index, cards.INDEX_FILE)
        cards._index = None
        _write(self.box.magic / "decks" / "casual" / "red-test.md", deck_file("Red Test", test_forge.RED))
        _write(self.box.magic / "decks" / "casual" / "green-test.md", deck_file("Green Test", test_forge.GREEN))
        sys.modules["decklab.lib.forge"] = real_forge
        self.addCleanup(sys.modules.__setitem__, "decklab.lib.forge", self.box.forge)

    def forget(self):
        real_forge.install._status = None
        real_forge.install._scripts.clear()
        real_forge.saved._read_cache.clear()
        cards._tag_cache.clear()

    def run_red_green(self, games=200, profile="matt"):
        answer = api.run_matchup(body(profile=profile, a=self.RED_ID, b=self.GREEN_ID, games=games))
        self.assertIn(answer["status"], ("queued", "running"))
        return answer["key"]

    def wait_for(self, key, games, timeout=20):
        """Poll as the page does until the run has played at least games games."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = api.matchup(key=key)["job"]
            if job and job["done"] >= games:
                return
            time.sleep(0.05)
        self.fail(f"the run didn't play {games} games")

    def test_a_run_and_every_answer_about_it(self):
        key = self.run_red_green()
        self.finish()
        done = api.matchup(self.RED_ID, None, self.GREEN_ID, None)
        self.assertEqual((done["key"], done["status"], done["notice"], done["error"]), (key, "done", None, None))
        result = done["result"]
        self.assertEqual((result["games"], result["runs"][-1]["by"], result["runs"][-1]["played"]), (200, "Matt", 200))
        # The wins are red's, then green's, whichever is the stored side 0.
        stored = real_forge.load(key)
        red = [side["card_sha"] for side in stored["sides"]].index(done["sides"][0]["card_sha"])
        won = [g["w"] for batch in stored["batches"] for g in batch["games"]]
        self.assertEqual(result["wins"], [won.count(red), won.count(1 - red)])
        self.assertEqual([(s["id"], s["kind"], s["current"]) for s in done["sides"]],
                         [(self.RED_ID, "casual", True), (self.GREEN_ID, "casual", True)])
        # Green's AI limits from the games: Fiery Annihilation never cast in 200, and the team pump.
        green_ai = done["sides"][1]["ai"]
        self.assertIn({"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}, green_ai["cannot_play"])
        self.assertEqual(green_ai["team_pump"]["copies"], 3)
        # The other way round, everything flips.
        back = api.matchup(self.GREEN_ID, None, self.RED_ID, None)
        self.assertEqual(back["result"]["wins"], list(reversed(result["wins"])))
        self.assertEqual(back["sides"][0]["ai"], green_ai)
        # By key, in the order it was asked for; and in the list, the same.
        by_key = api.matchup(key=key)
        self.assertEqual([s["id"] for s in by_key["sides"]], [self.RED_ID, self.GREEN_ID])
        self.assertEqual(by_key["result"]["wins"], result["wins"])
        listed = api.matchups()["results"]
        self.assertEqual([(item["key"], item["games"]) for item in listed], [(key, 200)])
        self.assertEqual([(s["id"], s["current"]) for s in listed[0]["sides"]],
                         [(self.RED_ID, True), (self.GREEN_ID, True)])
        self.assertEqual(listed[0]["winrate"], result["winrate"])
        # Green's deck page lists it from green's side.
        page = api.deck_view(self.GREEN_ID)["matchups"]
        self.assertEqual([s["id"] for s in page["results"][0]["sides"]], [self.GREEN_ID, self.RED_ID])
        self.assertEqual(page["results"][0]["winrate"], back["result"]["winrate"])
        self.assertEqual(page["ai"]["team_pump"]["copies"], 3)
        json.dumps([done, back, listed, page], allow_nan=False)

    def test_the_deck_page_judges_never_cast_by_all_its_games(self):
        # Before any game: only the card scripts, and "games" 0 says nothing was cast yet.
        ai = api.deck_view(self.GREEN_ID)["matchups"]["ai"]
        self.assertEqual((ai["cannot_play"], ai["games"]), ([], 0))
        self.run_red_green()
        self.finish()
        # Fiery Annihilation was cast in none of green's 200 games; red's Devout Decree is flagged by its script.
        ai = api.deck_view(self.GREEN_ID)["matchups"]["ai"]
        self.assertEqual(ai["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}])
        self.assertEqual(ai["games"], 200)
        self.assertEqual(set(ai), {"cannot_play", "commander_unplayable", "team_pump", "pilot", "unknown", "problem",
                                   "games", "other_engine_games", "other_engine_commander_unplayable"})
        self.assertEqual(ai["other_engine_games"], 0)          # (games of this list another engine played)
        red = api.deck_view(self.RED_ID)["matchups"]["ai"]
        self.assertEqual((red["cannot_play"], red["games"]), ([{"name": "Devout Decree", "qty": 1, "why": "script"}], 200))
        # A changed list has no saved games of its own, so nothing of it is judged never cast yet.
        _write(self.box.magic / "decks" / "casual" / "green-test.md",
               deck_file("Green Test", test_forge.GREEN.replace("2 Giant Growth", "3 Giant Growth")))
        ai = api.deck_view(self.GREEN_ID)["matchups"]["ai"]
        self.assertEqual((ai["cannot_play"], ai["games"]), ([], 0))
        json.dumps(ai, allow_nan=False)

    def test_the_card_stats_of_saved_games(self):
        # Card data written into a saved result by hand (the contract's "cards" record), so this doesn't
        # depend on the card log being ready: the deck pages pool it, the matchup page has each side's.
        # Wave 2: the deck page's per-card numbers pool only the card log's engine (engine.side_ids), so the run
        # is played with the card log said to be usable (runs: simjar.card_log; pages: simjar.readiness).
        for patch in (mock.patch.object(real_forge.simjar, "card_log", return_value=dict(test_forge.CARD_LOG)),
                      mock.patch.object(real_forge.simjar, "readiness", return_value={"ready": True, "problem": None})):
            patch.start()
            self.addCleanup(patch.stop)
        key = self.run_red_green()
        self.finish()
        path = self.box.data / "forge" / "results" / f"{key}.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        for batch in stored["batches"]:
            batch.pop("cards", None)
        # A decklab run saves one merged batch (the contract's "Saved result, v2"): split it in two, as two
        # runs' batches, so that one can have card data and the other not.
        merged, = stored["batches"]
        half = len(merged["games"]) // 2
        stored["batches"] = [dict(merged, games=merged["games"][:half]),
                             dict(merged, n=merged["n"] + 1, first=merged["games"][half]["g"],
                                  games=merged["games"][half:], casts=[{}, {}], lands=[{}, {}])]
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.forget()
        self.assertIsNone(api.deck_view(self.GREEN_ID)["matchups"]["cards"])
        self.assertEqual(api.matchup(key=key)["result"]["cards"], [None, None])
        # Green drew Fiery Annihilation in 40 of the first batch's games and never cast it.
        green = next(i for i, side in enumerate(stored["sides"]) if side["seen_as"][-1]["id"] == self.GREEN_ID)

        def add_record(batch, drawn):
            """batch's "cards": green drew Fiery Annihilation in drawn of its games, never cast."""
            n = len(batch["games"])
            wins = [sum(g["w"] == side for g in batch["games"]) for side in (0, 1)]
            drawn_wins = -(-wins[green] * drawn // n)    # rounded up: the games without it keep their wins possible
            rows = [{}, {}]
            if drawn:
                rows[green] = {"Fiery Annihilation": [drawn, drawn_wins, drawn, 0, drawn, 0, 0, 0]}
            batch["cards"] = {"v": 2, "games": n, "bad": 0, "wins": wins,     # version 2: 8 numbers a card, still counted
                              "first": [sum(g["first"] == side for g in batch["games"]) for side in (0, 1)],
                              "rows": rows, "commander": [{}, {}]}
            return drawn_wins

        first = stored["batches"][0]
        n = len(first["games"])
        self.assertLess(n, 200)                 # more batches, played (as it were) before the card log
        drawn_wins = add_record(first, 40)
        # The same record kept by an earlier card log (version 1, which counted a cast the AI couldn't finish
        # as a cast) isn't counted, but its games are said to be an earlier card log's ("old"), on both pages.
        older = dict(stored, batches=[dict(first, cards=dict(first["cards"], v=1)), *stored["batches"][1:]])
        path.write_text(json.dumps(older), encoding="utf-8")
        self.forget()
        cards = api.deck_view(self.GREEN_ID)["matchups"]["cards"]
        self.assertEqual((cards["games"], cards["old"], cards["of"], cards["matchups"]), (0, n, 200, 0))
        self.assertEqual([(c["games"], c["old"]) for c in api.matchup(key=key)["result"]["cards"]], [(0, n), (0, n)])
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.forget()
        page = api.deck_view(self.GREEN_ID)["matchups"]
        cards = page["cards"]
        self.assertEqual((cards["games"], cards["old"], cards["of"], cards["matchups"]), (n, 0, 200, 1))
        fiery = next(row for row in cards["rows"] if row["name"] == "Fiery Annihilation")
        self.assertEqual((fiery["drawn_games"], fiery["cast"], fiery["stuck"], fiery["wr_drawn"]["wins"]),
                         (40, 0, 40, drawn_wins))
        # Never cast in all 200 games, but only n of them have card data: how often it was drawn isn't said.
        self.assertEqual(page["ai"]["cannot_play"], [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast"}])
        # Red's page: its side of the same games, which the card log has no tallies of here.
        red = api.deck_view(self.RED_ID)["matchups"]["cards"]
        self.assertEqual((red["games"], red["of"], {row["drawn_games"] for row in red["rows"]}), (n, 200, {0}))
        # The matchup page: red's first, as it was asked; green's is its deck page's (one matchup).
        result = api.matchup(key=key)["result"]
        # (The deck page's also say how many games of other engines they leave out: none here.)
        self.assertEqual((red["other_engine_games"], cards["other_engine_games"]), (0, 0))
        self.assertEqual(result["cards"], [{k: v for k, v in stats.items() if k != "other_engine_games"}
                                           for stats in (red, cards)])
        json.dumps([page, result], allow_nan=False)
        # Every batch with card data (the others never drew it): now the AI limits say it, on both pages.
        for batch in stored["batches"][1:]:
            add_record(batch, 0)
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.forget()
        page = api.deck_view(self.GREEN_ID)["matchups"]
        self.assertEqual((page["cards"]["games"], page["cards"]["of"]), (200, 200))
        never = [{"name": "Fiery Annihilation", "qty": 1, "why": "never_cast", "drawn_games": 40}]
        self.assertEqual(page["ai"]["cannot_play"], never)
        sides = api.matchup(key=key)["sides"]
        self.assertEqual(next(s for s in sides if s["id"] == self.GREEN_ID)["ai"]["cannot_play"], never)

    def test_a_stop_keeps_every_finished_game_and_says_who(self):
        os.environ["FAKE_FORGE"] = "delay=0.01"
        key = self.run_red_green(games=400)
        self.wait_for(key, 20)
        answer = api.stop_matchup(body(profile="user1", key=key, a=self.RED_ID, b=self.GREEN_ID))
        self.assertEqual(answer["status"], "done")
        played = answer["result"]["games"]
        self.assertTrue(20 <= played < 400, played)
        self.assertEqual(answer["notice"], f"Stopped by User1 after {played} of 400 games.")
        self.assertEqual([s["id"] for s in answer["sides"]], [self.RED_ID, self.GREEN_ID])
        self.assertEqual(real_forge.load(key)["runs"][-1]["stopped_by"], "User1")
        # After a restart (the job forgotten), the notice comes from forge.view's run records alone.
        with mock.patch.object(api.forge_runs, "FORGE_JOBS", api._forge_runner()):
            self.assertEqual(api.matchup(key=key)["notice"], answer["notice"])
        # More games go on from there, and the notice is about the last run.
        os.environ.pop("FAKE_FORGE")
        self.run_red_green(games=200)
        self.finish()
        more = api.matchup(self.RED_ID, None, self.GREEN_ID, None)
        self.assertEqual((more["result"]["games"], more["notice"]), (played + 200, None))

    def test_a_stop_during_start_up_and_failed_batches(self):
        os.environ["FAKE_FORGE"] = "slowstart=5"
        key = self.run_red_green()
        deadline = time.monotonic() + 10
        while api.matchup(key=key)["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        answer = api.stop_matchup(body(profile="user1", key=key))
        self.assertEqual((answer["status"], answer["result"], answer["error"]), ("none", None, None))
        self.assertEqual(answer["notice"], "Stopped by User1 before any game finished.")
        self.assertEqual(api.matchups()["results"], [])
        self.assertEqual(api.deck_view(self.RED_ID)["matchups"]["results"], [])
        # The next run's second batch crashes: its games aren't counted, and the notice says why.
        seed = max(real_forge.plan(200, real_forge.load(key), 2), key=lambda spec: spec["n"])["seed"]
        os.environ["FAKE_FORGE"] = f"crash@{seed}#50"
        self.run_red_green()
        self.finish()
        failed = api.matchup(self.RED_ID, None, self.GREEN_ID, None)
        self.assertEqual(failed["notice"], "1 of 2 batches failed: Forge stopped with an error (exit code 1). "
                                           "Their games aren't counted.")
        self.assertEqual((failed["status"], failed["result"]["games"]), ("done", 100))



class AdaptiveRunTests(MatchupTestCase):
    """Wave 3's run modes (forge-trial/sim-wave3-contract.md sections 9.3 and 10.5): POST
    /api/matchup/run's "mode" (an adaptive run is forge.adaptive.run_adaptive), the profile's
    matchup_mode as the default, "joined", the job's plan and live range, "estimates", the summary's
    range from the page's side, and coordinator jobs (field runs, variant tests) in the running lists
    and on a matchup they play."""

    def setUp(self):
        super().setUp()
        self.adaptive_calls = []
        forge = self.forge

        def run_adaptive(entry_a, entry_b, mode, *, by, progress=None, **kwargs):
            self.adaptive_calls.append((entry_a["id"], entry_b["id"], mode, by))

            def report(done, total, detail):
                plan = {"mode": mode, "stage": 1, "next_look": 400 if mode == "ahead" else None, "max": 3200,
                        "planned": 400, "games_before": 0}
                progress(done, total, dict(detail, plan=plan, looks=[],
                                           range=[{"value": 0.6, "low": 0.5, "high": 0.7},
                                                  {"value": 0.4, "low": 0.3, "high": 0.5}]))

            return forge.run(entry_a, entry_b, 400, by=by, progress=report)

        p = mock.patch.object(self.forge, "adaptive", types.SimpleNamespace(run_adaptive=run_adaptive), create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_a_mode_plays_an_adaptive_run(self):
        self.playing()
        answer = self.play(mode="assess", games=123)            # games is read only with "fixed"
        self.assertIsNone(answer["joined"])
        self.assertTrue(self.forge.started.wait(WAIT))
        job = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")["job"]
        self.assertEqual((job["mode"], job["plan"]["mode"], job["plan"]["planned"]), ("assess", "assess", 400))
        first = self.a_first()
        self.assertEqual(job["range"], {"value": 0.6, "low": 0.5, "high": 0.7} if first
                         else {"value": 0.4, "low": 0.3, "high": 0.5})
        running = api.matchups()["running"][0]
        self.assertEqual((running["kind"], running["mode"], running["plan"]["mode"]), ("matchup", "assess", "assess"))
        self.finish()
        self.assertEqual(self.adaptive_calls, [(GRUUL_ID, GRUUL_ID, "assess", "Matt")])
        self.assertEqual(self.forge.runs[-1][2], 400)

    def test_the_profiles_mode_is_the_default_and_games_mean_fixed(self):
        api.put_settings("matt", b'{"matchup_mode": "ahead"}')
        api.run_matchup(body(profile="matt", a=GRUUL_ID, av="target", b=GRUUL_ID, bv="owned"))
        self.finish()
        self.assertEqual(self.adaptive_calls[-1][2], "ahead")
        api.run_matchup(body(profile="matt", a=GRUUL_ID, av="target", b=GRUUL_ID, bv="owned", games=200))
        self.finish()
        self.assertEqual((len(self.adaptive_calls), self.forge.runs[-1][2]), (1, 200))
        self.refused(400, self.play, mode="both", contains="mode must be one of")
        self.refused(400, self.play, mode="fixed", games=123, contains="games must be one of")

    def test_joining_a_run_says_which(self):
        self.playing()
        self.play(mode="ahead")
        self.assertTrue(self.forge.started.wait(WAIT))
        joined = self.play(mode="fixed", games=800, profile="user1")
        self.assertEqual(joined["joined"], {"mode": "ahead", "by": "Matt"})
        self.assertEqual(joined["status"], "running")
        self.finish()

    def test_estimates_come_from_forge_estimate(self):
        self.assertIsNone(api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")["estimates"])     # no estimator
        seen = []

        def matchup(entry_a, entry_b, games, p=0, results_dir=None, choices=()):
            seen.append((entry_a["kind"], games, p, list(choices)))
            return {"fixed": {"200": [1, 2]}, "assess": [3, 4], "ahead": [5, 6]}

        with mock.patch.object(self.forge, "estimate", types.SimpleNamespace(matchup=matchup), create=True):
            answer = api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")
        self.assertEqual(answer["estimates"], {"fixed": {"200": [1, 2]}, "assess": [3, 4], "ahead": [5, 6]})
        self.assertEqual(seen, [("constructed", [], 0, list(self.forge.GAME_CHOICES))])

        def broken(*a, **k):
            raise RuntimeError("no")

        with mock.patch.object(self.forge, "estimate", types.SimpleNamespace(matchup=broken), create=True):
            self.assertIsNone(api.matchup(GRUUL_ID, "target", GRUUL_ID, "owned")["estimates"])

    def test_a_stopped_runs_range_is_from_the_pages_side(self):
        self.play(mode="fixed", games=200)
        self.finish()
        real_view = self.forge.view
        summary = {"outcome": "stopped", "ranges": [{"value": 0.6, "low": 0.5, "high": 0.7},
                                                    {"value": 0.4, "low": 0.3, "high": 0.5}],
                   "range": {"value": 0.6, "low": 0.5, "high": 0.7}}

        def view(result, perspective_sha):
            return dict(real_view(result, perspective_sha), adaptive_last=summary)

        with mock.patch.object(self.forge, "view", view):
            for a, b in (("target", "owned"), ("owned", "target")):
                shown = api.matchup(GRUUL_ID, a, GRUUL_ID, b)["result"]["adaptive_last"]["range"]
                first = self.a_first((GRUUL_ID, a), (GRUUL_ID, b))
                self.assertEqual(shown["value"], 0.6 if first else 0.4)

    def coordinator(self, key, detail):
        """A COORD_JOBS job for key that reports detail, then waits until the test ends."""
        runner = jobs.Runner(max_running=2, max_queued=4, log=lambda text: None)
        p = mock.patch.object(api.forge_runs, "COORD_JOBS", runner)
        p.start()
        self.addCleanup(p.stop)
        gate, started = threading.Event(), threading.Event()
        self.addCleanup(gate.set)

        class Coordinator:
            by = "User1"

            def __call__(self, progress):
                progress(140, 400, detail)
                started.set()
                gate.wait(WAIT)
                return {}

        job = runner.submit(key, Coordinator())
        self.assertTrue(started.wait(WAIT))
        return job

    def test_coordinator_jobs_are_listed_and_play_a_matchups_pair(self):
        sha = self.sha(GRUUL_ID)
        pair_key = self.forge.matchup_key(*(self.forge.entry(GRUUL_ID, v, "", "constructed",
                                                             decks.load_deck(GRUUL_ID, v)) for v in ("target", "owned")))
        detail = {"budget": "standard", "phase": "floor",
                  "deck": {"id": GRUUL_ID, "version": "target", "title": "Gruul Test"},
                  "pairs": {pair_key: {"opponent": {"id": GRUUL_ID, "version": "owned", "title": "Gruul Test"},
                                       "done": 140, "total": 200, "wins": 77, "other": 3, "playing": True}}}
        job = self.coordinator(f"field:home:{sha}:Constructed", detail)
        running = api.matchups()["running"]
        self.assertEqual(running, [{"key": job.key, "kind": "field", "title": "Field run of Gruul Test",
                                    "by": "User1", "done": 140, "total": 400,
                                    "link": f"#/deck/{GRUUL_ID}?version=target#field", "status": "running",
                                    "ahead": 0, "sides": None, "may_stop": True}])
        self.assertEqual([r["key"] for r in api.deck_view(GRUUL_ID, "target")["matchups"]["running"]], [job.key])
        self.assertEqual(api.deck_view(GRUUL_ID, "owned")["matchups"]["running"], [])
        # The pair's record, as a matchup page of that pair shows it (F's _job_for_key hands the job over).
        snap = api.forge_runs.COORD_JOBS.snapshot(job)
        sides = [{"id": GRUUL_ID, "version": "owned"}, {"id": GRUUL_ID, "version": "target"}]
        shown = api.forge_runs._job_json(job, snap, False, key=pair_key, sides=sides)
        self.assertEqual((shown["done"], shown["total"], shown["wins"], shown["other"]), (140, 200, [60, 77], 3))
        self.assertEqual(shown["via"], {"kind": "field", "job": job.key, "title": "Field run of Gruul Test",
                                        "link": f"#/deck/{GRUUL_ID}?version=target#field", "by": "User1"})
        variant = api.forge_runs._via_json(types.SimpleNamespace(key="variant:" + "9" * 64, fn=None),
                                           {"deck": {"title": "Gruul Test"}})
        self.assertEqual((variant["title"], variant["link"]), ("Test of a change to Gruul Test",
                                                               "#/variant?test=" + "9" * 64))



class RunnerTests(unittest.TestCase):

    def test_errors_for_the_page(self):
        forge = type(sys)("decklab.lib.forge")

        class ForgeError(Exception):
            pass

        forge.ForgeError = ForgeError
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": forge}):
            self.assertEqual(api._matchup_error(ForgeError("Forge isn't installed.")), "Forge isn't installed.")
            self.assertEqual(api._matchup_error(ForgeError(r"C:\Users\someone\forge.log is broken")),
                             "forge.log is broken")
            # A stopped run raises again the jobs.Stopped its progress raised (forge.Stopped is never raised).
            self.assertEqual(api._matchup_error(jobs.Stopped("Deck Lab is stopping")), jobs.STOPPED)
            self.assertEqual(api._matchup_error(KeyError("x")), api.MATCHUP_FAILED)
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": None}):
            self.assertEqual(api._matchup_error(KeyError("x")), api.MATCHUP_FAILED)



if __name__ == "__main__":
    unittest.main()
