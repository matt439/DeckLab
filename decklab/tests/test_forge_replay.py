"""Tests for the replay command (python -m decklab.lib.forge replay; wave 2's contract,
forge-trial/sim-wave2-contract.md, "Command line"): after the engine changes, every saved
matchup whose two lists are still current plays with today's engine the games its result is
short of.

The runs are a stand-in for forge.runner.run, played in a stand-in for pool.session() (the
warm pool, wave 2's PP package, whose own test runs replay in the real session), so no Forge
process starts: each stand-in run saves a result of today's engine with its games added, or
does what a test asks (raise BUSY or another ForgeError, save under another key, or play until
Ctrl+C stops it through its progress callback). The saved results of earlier engines are
made by hand (test_forge.stored), with real card_shas. They share test_forge.py's setUpModule
and tearDownModule (its made-up Forge folder).

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import _thread
import json
import threading
import time
from contextlib import contextmanager
from unittest import mock

from decklab.lib import decks, forge
from decklab.tests import test_forge
from decklab.tests.test_forge import CARD_LOG, GISA, GREEN, RED, entry, sections, stored

BLUE = """Deck
4 Counterspell
4 Divination
12 Island
"""


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class StandInSession:
    """pool.session(local=...)'s stand-in: a context manager whose value runs are given (run(pool=...))."""

    def __init__(self):
        self.value = object()
        self.opened = []            # local=, each time it's entered
        self.closed = 0

    @contextmanager
    def __call__(self, *, local=False):
        self.opened.append(local)
        try:
            yield self.value
        finally:
            self.closed += 1


class ReplayTests(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.lists = {"casual/green": GREEN, "casual/red": RED, "casual/blue": BLUE, "commander/gisa": GISA}
        summaries = {deck_id: {"id": deck_id, "title": deck_id.split("/")[1].title(), "kind": deck_id.split("/")[0],
                               "versions": ["target"]} for deck_id in self.lists}
        self.session = StandInSession()
        self.calls, self.modes, self.stopped = [], {}, []
        self.late = 0               # seconds a "stop" run takes to call progress again once Ctrl+C has come
        self.playing, self.most = 0, 0
        self.lock = threading.Lock()
        for p in (mock.patch.object(decks, "find_summary", side_effect=summaries.get),
                  mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: sections(self.lists[deck_id])),
                  mock.patch.object(forge.pool, "session", self.session),
                  mock.patch.object(forge.runner, "run", self.stand_in_run),
                  mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG))):
            p.start()
            self.addCleanup(p.stop)
        self.results.mkdir()
        self.eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))

    run_main = test_forge.CommandLineTests.run_main

    def entry(self, deck_id):
        kind = "commander" if deck_id.startswith("commander/") else "constructed"
        return entry(self.lists[deck_id], deck_id, kind, title=deck_id.split("/")[1].title())

    def today(self, a, b):
        """Today's engine's key for two deck ids."""
        return forge.engine.key(self.entry(a), self.entry(b), self.eng)

    def save(self, key, a, b, games, fmt="Constructed", engine=None, card_shas=None):
        """A saved result of a and b (deck ids) with games counted games: before wave 2 (engine None), or
        of an engine of wave 2 (engine: its fields)."""
        result = stored([(0, "win", i % 2) for i in range(games)])
        result.update(key=key, format=fmt)
        found = [(sha or self.entry(deck_id)["card_sha"], deck_id) for deck_id, sha in zip((a, b), card_shas or (None, None))]
        for side, (sha, deck_id) in zip(result["sides"], sorted(found)):     # side 0: the smaller card_sha
            e = self.entry(deck_id)
            side.update(card_sha=sha, kind=e["kind"], cards=e["cards"],
                        seen_as=[{"id": deck_id, "version": "target", "title": e["title"], "source": None,
                                  "when": "2026-10-01T10:00:00"}])
        if engine is not None:
            result.update(run_version=2, engine=engine)
            if engine["kind"] == forge.engine.KIND_DECKLAB:
                # A decklab result's shape (saved._is_result): batches numbered by their first game, each game
                # its number "g", and the result's seeds.
                for batch in result["batches"]:
                    batch.pop("seed")
                    batch.pop("deck1")
                    batch["first"] = 0
                    for g, game in enumerate(batch["games"]):
                        game["g"] = g
                result.update(failed=[], next_game=games,
                              seeds={"scheme": forge.seeds.SCHEME, "base": 1, "stream": "0" * 16, "seat_block": 25,
                                     "flip": 0})
        (self.results / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")
        forge.saved._read_cache.clear()
        return result

    def stand_in_run(self, a, b, games, *, by, progress=None, results_dir=None, pool=None, exact=False, **kwargs):
        """runner.run's stand-in: today's engine's result of a and b gets games more games, unless self.modes
        says otherwise for a's id ("busy", "fail", "elsewhere", or "stop": play until progress raises, which it
        calls self.late seconds after the test's Ctrl+C at first, as a run still queued in the pool might)."""
        with self.lock:
            self.calls.append({"a": a["id"], "b": b["id"], "games": games, "by": by, "pool": pool, "exact": exact,
                               "results_dir": results_dir, **kwargs})
            self.playing += 1
            self.most = max(self.most, self.playing)
        try:
            mode = self.modes.get(a["id"]) or self.modes.get(b["id"])
            if mode == "busy":
                raise forge.ForgeError(forge.runner.BUSY)
            if mode == "fail":
                raise forge.ForgeError("Forge doesn't know this card, so the matchup can't be played: X.")
            progress(0, games, {})
            if mode == "stop":
                self.stopping.wait(5)
                time.sleep(self.late)
                done = 0
                try:
                    while True:
                        progress(done, games, {})
                        done = min(games, done + 1)
                        time.sleep(0.01)
                except forge.STOPS as e:
                    e.saved_games = done
                    with self.lock:
                        self.stopped.append((type(e), done))
                    raise
            key = forge.engine.key(a, b, self.eng)
            have = forge.saved._counted(forge.load(key, results_dir) or {})
            ids = [s["id"] for s in sorted([a, b], key=lambda e: e["card_sha"])]
            saved = self.save("0" * 63 + "1" if mode == "elsewhere" else key, *ids, have + games,
                              fmt=forge.fmt_for(a["kind"]), engine=forge.engine.result_fields(self.eng)["engine"])
            saved["runs"][-1]["played"] = games
            progress(games, games, {})
            return saved
        finally:
            with self.lock:
                self.playing -= 1

    def name(self, a, b, commander=False):
        """How replay names a matchup of two deck ids: side 0's (the smaller card_sha) first."""
        titles = [self.entry(deck_id)["title"] for deck_id in sorted((a, b), key=lambda d: self.entry(d)["card_sha"])]
        return f"{titles[0]} (target) vs {titles[1]} (target)" + (", Commander" if commander else "")

    def replay(self, *argv):
        return self.run_main("replay", "--results-dir", str(self.results), *argv)

    def earlier_results(self):
        """Green v Red before wave 2 (400 games at another clock, 800 at today's) and with plain Forge (300);
        today's engine's has 300. Blue v Red's 200 before wave 2, Gisa's mirror's 100 (Commander), and
        Green v Blue's, played with a Green list that has changed since."""
        self.save("1" * 64, "casual/green", "casual/red", 400)
        self.save("2" * 64, "casual/green", "casual/red", 800)
        plain = dict(forge.engine.result_fields(forge.engine.today("plain"))["engine"])
        self.save("3" * 64, "casual/green", "casual/red", 300, engine=plain)
        self.save(self.today("casual/green", "casual/red"), "casual/green", "casual/red", 300,
                  engine=forge.engine.result_fields(self.eng)["engine"])
        self.save("4" * 64, "casual/blue", "casual/red", 200)
        self.save("5" * 64, "commander/gisa", "commander/gisa", 100, fmt="Commander")
        self.save("6" * 64, "casual/green", "casual/blue", 800, card_shas=("f" * 64, None))

    def test_a_dry_run_lists_what_it_would_play(self):
        self.earlier_results()
        code, out, err = self.replay("--dry-run")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertEqual(sorted(lines[:-2]), sorted([
            f"{self.name('casual/blue', 'casual/red')}: 200 games (the most with an earlier engine 200, with today's 0)",
            f"{self.name('commander/gisa', 'commander/gisa', True)}: 100 games (the most with an earlier engine 100, "
            "with today's 0)",
            f"{self.name('casual/green', 'casual/red')}: 500 games (the most with an earlier engine 800, with today's 300)"]))
        self.assertEqual(lines[-2], "3 matchups to replay, 800 games.")
        # About how long: each batch of these took 10 s, so Blue v Red's 200 games 0.05 s a game, Gisa's 100 0.1 s,
        # Green v Red's 1,800 (today's 300 too) 0.022 s: 31 s of Forge processes, 2 at once (forge_workers).
        self.assertEqual(lines[-1], "That's about 1 minute with 2 games at once (forge_workers), going by how long "
                                    "these matchups' saved games took a Forge process each. It's a rough guide: those "
                                    "runs mostly had fewer games going at once, and other work on the PC or the server "
                                    "makes it longer.")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.session.opened, [])
        # The card log isn't usable for pages here (no JDK): a dry run still lists, and says replay would refuse.
        self.assertIn("replay would refuse to play", err)
        found = json.loads(self.replay("--dry-run", "--json")[1])
        self.assertEqual((found["games"], found["estimate_s"], found["workers"]), (800, 16, 2))
        green = next(item for item in found["planned"] if item["games"] == 500)
        self.assertEqual((green["target"], green["have"], green["key"], sorted(green["earlier"]), green["per_game_s"]),
                         (800, 300, self.today("casual/green", "casual/red"), ["1" * 64, "2" * 64, "3" * 64], 0.022))

    def test_a_result_re_keyed_by_a_pilot_change_is_replayed(self):
        # Green v Red's 300 games with today's engine and the default pilots; then Green's pilot gains a
        # switch (simulation.json), so those games are an earlier engine's for today's lists.
        before = self.today("casual/green", "casual/red")
        self.save(before, "casual/green", "casual/red", 300, engine=forge.engine.result_fields(self.eng)["engine"])
        self.assertEqual(forge.cli._replay_plan(self.results, self.eng), [])
        default = forge.pilots.pilot_for
        switched = lambda deck_id, version: ({"profile": "Default", "switches": ["etb-harmless-1"]}   # noqa: E731
                                             if deck_id == "casual/green" else default(deck_id, version))
        with mock.patch.object(forge.pilots, "pilot_for", side_effect=switched):
            plan = forge.cli._replay_plan(self.results, self.eng)
            self.assertEqual([(item["games"], item["target"], item["have"]) for item in plan], [(300, 300, 0)])
            self.assertEqual(plan[0]["key"], forge.engine.key(self.entry("casual/green"), self.entry("casual/red"),
                                                              self.eng))
            self.assertNotEqual(plan[0]["key"], before)

    def test_the_estimate(self):
        # Each matchup at its saved games' speed (a Forge process's seconds a game), forge_workers at once; one
        # whose saved games don't say at its format's average; none at all when a format has nothing to go by.
        item = lambda fmt, games, rate: {"format": fmt, "games": games, "per_game_s": rate}      # noqa: E731
        estimate = forge.cli._replay_estimate
        self.assertEqual(estimate([item("Constructed", 1000, 1.0), item("Commander", 100, 3.0)], 4), 325)
        self.assertEqual(estimate([item("Constructed", 1000, 1.0), item("Constructed", 300, 2.0),
                                   item("Constructed", 1300, None)], 2), 1600)    # (1000 + 600 + 1300 x 16/13) / 2
        self.assertIsNone(estimate([item("Constructed", 1000, 1.0), item("Commander", 100, None)], 4))
        self.assertIsNone(estimate([], 4))
        about = forge.cli._about
        self.assertEqual([about(s) for s in (0, 70, 125, 89 * 60, 90 * 60, 3 * 3600 + 22 * 60, 7203)],
                         ["about 1 minute", "about 1 minute", "about 2 minutes", "about 89 minutes", "about 1 hour "
                          "30 minutes", "about 3 hours 20 minutes", "about 2 hours"])
        # A matchup's speed is every saved game's of the pair in its format, today's engine's too.
        self.earlier_results()
        plan = {item["games"]: item for item in forge.cli._replay_plan(self.results, self.eng)}
        self.assertEqual({games: item["per_game_s"] for games, item in plan.items()}, {500: 0.022, 200: 0.05, 100: 0.1})
        self.save("7" * 64, "casual/blue", "casual/red", 50)
        result = json.loads((self.results / f"{'7' * 64}.json").read_text(encoding="utf-8"))
        result["batches"][0].pop("wall_s")             # a batch that doesn't say: left out
        (self.results / f"{'7' * 64}.json").write_text(json.dumps(result), encoding="utf-8")
        forge.saved._read_cache.clear()
        self.assertEqual(next(item for item in forge.cli._replay_plan(self.results, self.eng)
                              if item["games"] == 200)["per_game_s"], 0.05)
        # The start of a real replay says it too.
        code, _, err = self.replay()
        self.assertEqual(code, 0, err)
        self.assertIn("Replaying 3 matchups, 800 games, 3 at once, about 1 minute at the saved games' speed...", err)

    def test_it_refuses_unless_the_card_log_can_be_used(self):
        self.earlier_results()
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": "Not today."}):
            code, out, err = self.replay()
        self.assertEqual((code, out, err), (1, "", "Replay plays only with the card log's engine, and the card log "
                                                   "can't be used now. Not today.\n"))
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": None}):
            self.assertEqual(self.replay()[2], "Replay plays only with the card log's engine, and the card log can't "
                                               "be used now.\n")
        self.assertEqual(self.calls, [])

    def test_it_plays_the_difference_in_one_session_and_only_once(self):
        self.earlier_results()
        code, out, err = self.replay("--matchups", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted((c["games"], c["by"], c["pool"] is self.session.value, c["exact"]) for c in self.calls),
                         [(100, "replay", True, True), (200, "replay", True, True), (500, "replay", True, True)])
        self.assertEqual({c["results_dir"] for c in self.calls}, {str(self.results)})
        self.assertEqual((self.session.opened, self.session.closed), ([False], 1))
        self.assertLessEqual(self.most, 2)
        self.assertEqual(out, "Replayed 3 of 3 matchups: 800 games.\n")
        self.assertIn("Replaying 3 matchups, 800 games, 2 at once, about 1 minute at the saved games' speed...", err)
        # Today's results have the games now: again, nothing to play.
        self.calls.clear()
        code, out, _ = self.replay()
        self.assertEqual((code, out, self.calls), (0, "Nothing to replay: every current matchup has as many games "
                                                      "with today's engine.\n", []))
        self.assertEqual(self.session.opened, [False])     # no session for nothing

    def test_one_at_a_time_and_a_local_pool(self):
        self.earlier_results()
        self.assertEqual(self.replay("--matchups", "1", "--local")[0], 0)
        self.assertEqual((self.most, self.session.opened), (1, [True]))

    def test_a_matchup_being_played_is_left_for_next_time(self):
        self.earlier_results()
        self.modes["casual/blue"] = "busy"
        code, out, err = self.replay("--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertEqual(found["busy"], [self.today("casual/blue", "casual/red")])
        self.assertEqual(len(found["played"]), 2)
        self.assertEqual(sum(c["a"] == "casual/blue" or c["b"] == "casual/blue" for c in self.calls), 1)   # not again
        out = self.replay()[1]
        self.assertTrue(out.endswith("Still playing, so not replayed now (run replay again once they're done): "
                                     f"{self.name('casual/blue', 'casual/red')}.\n"), out)

    def test_a_failed_matchup_is_said_and_the_rest_go_on(self):
        self.earlier_results()
        self.modes["casual/blue"] = "fail"
        code, out, _ = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("Replayed 2 of 3 matchups: 600 games.\n", out)
        self.assertIn(f"  failed: {self.name('casual/blue', 'casual/red')}: Forge doesn't know this card", out)
        self.modes["casual/blue"] = "elsewhere"
        code, out, _ = self.replay()
        self.assertEqual(code, 1)
        self.assertIn("its games were saved with another engine than the card log's", out)

    def test_ctrl_c_stops_every_run_and_each_saves_its_games(self):
        self.earlier_results()
        self.modes = {"casual/blue": "stop", "casual/green": "stop", "casual/red": "stop", "commander/gisa": "stop"}
        self.stopping = threading.Event()
        started = threading.Barrier(2, action=lambda: (_thread.interrupt_main(), self.stopping.set()))
        real = self.stand_in_run

        def run(a, b, games, **kwargs):
            def progress(done, total, detail, inner=kwargs["progress"]):
                inner(done, total, detail)
                if done == 0 and total == games and not self.stopping.is_set():
                    started.wait(5)
            return real(a, b, games, **dict(kwargs, progress=progress))

        with mock.patch.object(forge.runner, "run", run):
            code, _, err = self.replay("--matchups", "2")
        self.assertEqual(code, 130, err)
        self.assertIn("Stopping: each matchup saves the games it finished...", err)
        # Each run was stopped through its progress callback (common.Stopped), and said what it saved.
        self.assertEqual([kind for kind, _ in self.stopped], [forge.common.Stopped] * 2)
        saved = KeyboardInterrupt()
        saved.saved_games = sum(done for _, done in self.stopped)
        self.assertEqual(err.splitlines()[-1], forge.cli._stopped_message(saved))
        self.assertEqual(len(self.calls), 2)        # the third never started
        self.assertEqual((self.session.opened, self.session.closed), ([False], 1))
        self.assertEqual(self.playing, 0)           # every run ended before the command did

    def test_ctrl_c_again_while_stopping_says_so_and_still_saves(self):
        self.earlier_results()
        self.modes = {"casual/blue": "stop", "casual/green": "stop", "casual/red": "stop", "commander/gisa": "stop"}
        self.stopping = threading.Event()
        self.late = 2.5             # the runs take a while to stop (still queued in the pool, say)

        def ctrl_c_twice():
            _thread.interrupt_main()
            self.stopping.set()
            threading.Timer(1, _thread.interrupt_main).start()      # again, while the runs are stopping

        started = threading.Barrier(2, action=ctrl_c_twice)
        real = self.stand_in_run

        def run(a, b, games, **kwargs):
            def progress(done, total, detail, inner=kwargs["progress"]):
                inner(done, total, detail)
                if done == 0 and total == games and not self.stopping.is_set():
                    started.wait(5)
            return real(a, b, games, **dict(kwargs, progress=progress))

        with mock.patch.object(forge.runner, "run", run):
            code, _, err = self.replay("--matchups", "2")
        self.assertEqual(code, 130, err)
        self.assertIn(f"Stopping: each matchup saves the games it finished...\n{forge.cli.REPLAY_STILL_STOPPING}\n", err)
        # The second Ctrl+C didn't cut the stop short: both runs stopped and saved.
        self.assertEqual([kind for kind, _ in self.stopped], [forge.common.Stopped] * 2)
        self.assertEqual(self.playing, 0)
