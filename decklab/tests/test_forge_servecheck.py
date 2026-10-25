"""Tests for decklab.lib.forge.servecheck, the warm-equivalence check, and the serve-check
command, without Java: the check's requests (chunks across a seat-block boundary, the worker's
order with a repeat), how two copies of a request's games are compared (Constructed line for
line with a warm replay for a difference, Commander by outcome, time limits, the card log), and
warm_leg against the fake Forge (fixtures/fake_forge.py: its sim mode as the fresh processes,
its serve mode as the warm worker): the same games give None, a worker that recycles or hits a
time limit is replaced and a v2 request goes on in the new one, a difference only the worker
makes fails, and what can't be played raises ForgeError with no process left running.

The real-Java checks are test_forge_serve (DECKLAB_FORGE_TESTS=1).

Run from the repo root: python -m unittest decklab.tests.test_forge_servecheck
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.tests import test_forge

servecheck = forge.servecheck
runner = forge.runner
seeds = forge.seeds
STREAM = "0123456789abcdef"
ATTACK_ORDER_ID = "attack-requirements-in-order-1"     # wave 2's R14b (in Forge's jar's list)


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def v2(first, stream=STREAM):
    return {"stream": stream, "first": first}


# ============================================================ the check's requests

class RequestTests(unittest.TestCase):

    def test_cuts_differ_in_size_and_never_span_a_seat_block(self):
        self.assertEqual(servecheck._cuts(19, 12), [(19, 3), (22, 3), (25, 2), (27, 4)])
        self.assertEqual(servecheck._cuts(24, 3), [(24, 1), (25, 2)])
        for first, games in ((0, 1), (0, 60), (13, 40), (49, 2)):
            cuts = servecheck._cuts(first, games)
            self.assertEqual(sum(n for _, n in cuts), games)
            self.assertEqual([g for g, _ in cuts], [first] + [g + n for g, n in cuts[:-1]])
            for g, n in cuts:
                self.assertEqual(seeds.block_of(g), seeds.block_of(g + n - 1))

    def test_check_requests(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        legs = [("Constructed", {name: ([], cards) for name, cards in forge.cli.CHECK_DECKS.items()}, 12),
                ("Commander", forge.cli.CHECK_COMMANDER_DECKS, 3)]
        requests = servecheck.check_requests(tmp, legs, 1)
        a, b = (f"{name}.dck" for name in forge.cli.CHECK_DECKS)
        k, i = (f"{name}.dck" for name in forge.cli.CHECK_COMMANDER_DECKS)
        stream = seeds.stream_hex(seeds.stream_of(*(forge.entry_from_dck(tmp / d)["card_sha"] for d in (a, b))))
        self.assertEqual(requests[:4], [("Constructed", a, b, 3, 1, v2(19, stream)),
                                        ("Constructed", a, b, 3, 1, v2(22, stream)),
                                        ("Constructed", b, a, 2, 1, v2(25, stream)),     # the next seat block
                                        ("Constructed", b, a, 4, 1, v2(27, stream))])
        self.assertEqual([r[1:4] + (r[5]["first"],) for r in requests[4:]], [(k, i, 1, 24), (i, k, 2, 25)])
        self.assertIn("[Commander]\n1 Krenko, Mob Boss\n", (tmp / k).read_text(encoding="utf-8"))
        # v1: each chunk a batch of its own seed, the same decks and sizes.
        old = servecheck.check_requests(tmp, legs, 1, v1=True)
        self.assertEqual([r[:4] for r in old], [r[:4] for r in requests])
        self.assertEqual([r[4:] for r in old], [(1, None), (2, None), (3, None), (4, None), (1, None), (2, None)])

    def test_warm_decks_need_the_attack_checks_in_order(self):
        built_in = dict(test_forge.CARD_LOG, game_patches=[ATTACK_ORDER_ID])
        self.assertEqual(servecheck.ATTACK_ORDER, ATTACK_ORDER_ID)
        self.assertIs(servecheck.warm_decks({}, built_in), servecheck.WARM_DECKS)
        self.assertIs(servecheck.warm_decks({"game_patches": True}, built_in), servecheck.WARM_DECKS)
        self.assertEqual(servecheck.warm_decks({"game_patches": False}, built_in), {})    # Forge's code plays
        self.assertEqual(servecheck.warm_decks({}, test_forge.CARD_LOG), {})             # not in Forge's jar

    def test_the_workers_order(self):
        requests = [("Constructed", "a.dck", "b.dck", 3, 1, v2(19)), ("Constructed", "a.dck", "b.dck", 3, 1, v2(22)),
                    ("Constructed", "b.dck", "a.dck", 2, 1, v2(25)), ("Constructed", "c.dck", "d.dck", 3, 1, v2(22)),
                    ("Constructed", "d.dck", "c.dck", 3, 1, v2(25)), ("Commander", "k.dck", "i.dck", 1, 1, v2(24))]
        # Matchups in turn, each one's last request first, then the first played again.
        self.assertEqual(servecheck._order(requests), [2, 4, 5, 1, 3, 0, 2])
        self.assertEqual(servecheck._order(requests[:1]), [0, 0])


# ============================================================ starting a worker

class StartTests(unittest.TestCase):
    """servecheck._start: a process with a stdin pipe, by start_process once it has a stdin
    option (wave 2's PP), until then by its own copy of start_process's Windows start."""

    ECHO = [sys.executable, "-c", "print('got ' + input())"]

    def talk(self, proc):
        """Send proc a line and read its answer, then end it."""
        out = servecheck._Output(proc)
        try:
            proc.stdin.write("ping\n")
            proc.stdin.flush()
            return out.get(time.monotonic() + 30)
        finally:
            out.end(wait=10)

    def test_start_process_with_a_stdin_option(self):
        calls = []

        def start_process(argv, cwd=None, env=None, stdin=subprocess.DEVNULL):
            calls.append((argv, cwd, env, stdin))
            return "proc"
        with mock.patch.object(forge.processes, "start_process", start_process):
            self.assertEqual(servecheck._start(["java"], "dir", {"A": "1"}), "proc")
        self.assertEqual(calls, [(["java"], "dir", {"A": "1"}, subprocess.PIPE)])
        self.assertTrue(calls[0][3])        # a pipe too where the option is a bool (stdin=False)

    def test_its_own_start_has_a_stdin_pipe(self):
        proc = servecheck._start(self.ECHO, None, None)
        self.assertEqual(self.talk(proc), "got ping")
        self.assertTrue(test_forge.wait_dead(proc.pid))

    @unittest.skipUnless(sys.platform == "win32", "Windows' job objects")
    def test_its_own_start_joins_the_job_and_says_once_when_it_cant(self):
        logged = []
        with (mock.patch.object(forge.processes, "_job_warned", False),
              mock.patch.object(forge.common, "_log", logged.append)):
            proc = servecheck._start(self.ECHO, None, None)
            self.assertTrue(forge.processes.in_job(proc.pid))
            self.assertEqual(self.talk(proc), "got ping")
            self.assertEqual(logged, [])
            with mock.patch.object(forge.processes._k32, "AssignProcessToJobObject", lambda job, handle: 0):
                for _ in range(2):
                    proc = servecheck._start(self.ECHO, None, None)
                    self.assertEqual(self.talk(proc), "got ping")
        self.assertEqual(len(logged), 1)
        self.assertIn("couldn't join Deck Lab's job", logged[0])


# ============================================================ comparing two copies

def fake_lines(args, modes=""):
    """What the fake DeckLabSim prints for request args (from "sim" on)."""
    argv = [sys.executable, str(test_forge.FAKE), *args, "--card-log"]
    env = dict(os.environ, FAKE_FORGE=modes)
    env.pop("FAKE_FORGE_LOG", None)
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60).stdout.splitlines()


def copy_of(lines, fmt="Constructed"):
    """A _Copy of one output."""
    part = servecheck._Part()
    for line in lines:
        part.add(line)
    copy = servecheck._Copy(fmt)
    copy.add(part)
    return copy


def changed(lines, game, old, new):
    """lines with the first line of game (from 1) that starts with old changed to start with new
    (new may hold line breaks: more lines)."""
    out, seen, done = [], 0, False
    for line in lines:
        if seen == game - 1 and not done and line.startswith(old):
            line, done = new + line[len(old):], True
        if line.startswith("Game Result:"):
            seen += 1
        out += line.split("\n")
    return out


def drawn(lines, game):
    """lines with game's (from 1) Game Result line a draw's."""
    return [f"Game Result: Game {game} ended in a Draw! Took 5 ms." if line.startswith(f"Game Result: Game {game} ")
            else line for line in lines]


class CompareTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name, text in (("green", test_forge.GREEN), ("red", test_forge.RED), ("gisa", test_forge.GISA),
                           ("mirror", test_forge.MIRROR_GISA)):
            kind = "commander" if "gisa" in text.lower() else "constructed"
            e = test_forge.entry(text, f"casual/{name}", kind=kind)
            (cls.tmp / f"{name}.dck").write_text(e["dck"], encoding="utf-8")
        setup = {"decks_dir": cls.tmp, "clock_s": 120}
        cls.request = ("Constructed", "green.dck", "red.dck", 4, 1, v2(20))
        cls.lines = fake_lines(runner.request_args(setup, *cls.request))
        cls.commander = ("Commander", "gisa.dck", "mirror.dck", 3, 1, v2(0))
        cls.commander_lines = fake_lines(runner.request_args(setup, *cls.commander))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def compare(self, warm, replay=None, fresh=None, request=None, cut=False):
        request = request or self.request
        fresh = copy_of(fresh or (self.lines if request is self.request else self.commander_lines), request[0])
        warm = copy_of(warm, request[0])
        warm.cut = cut
        calls = []

        def again(i):
            calls.append(i)
            return replay(i) if replay else self.fail("no replay expected")
        found = servecheck._compare(request, fresh, warm, 3, 7, again)
        return found, calls

    def test_the_same_games(self):
        self.assertEqual(self.compare(self.lines), ([], []))
        # WARNING:, blank and DLSERVE| lines, timings, the games' places and stack frames don't count.
        noisy = []
        for line in self.lines:
            if line.startswith("Game Result:"):
                line = line.replace("ended in ", "ended in 9").replace("Game Result: Game ", "Game Result: Game 7")
            noisy.append(line)
            if line.startswith("Turn: Turn 2 "):
                noisy += ["", "WARNING: A terminally deprecated method", "DLSERVE|bad|x", "\tat forge.Foo.bar(Foo.java:1)"]
        self.assertEqual(self.compare(noisy), ([], []))

    def test_masks(self):
        copy = copy_of(["Ai(1)-a [Default] vs Ai(2)-b [Default] - 1 game of Constructed seed 1",
                        "Combat: Ai(1)-a assigned Goblin (12), Bear (11) and Ape (13) to attack Ai(2)-b.",
                        "Information: DL|log|1", "", "WARNING: x", "\tat a.b(C.java:1)", "\t... 3 more",
                        "java.lang.NullPointerException: x", "Game Outcome: Match Duration 0m : 07s",
                        "Game Result: Game 4 ended in 812 ms. Ai(1)-a has won!"])
        self.assertEqual(copy.masked(0), [
            "Combat: Ai(1)-a assigned Ape (13), Bear (11), Goblin (12) to attack Ai(2)-b.",
            "Information: DL|log|1", "java.lang.NullPointerException: x", "Game Outcome: Match Duration ?",
            "Game Result: Game ? ended in ? ms. Ai(1)-a has won!"])

    def test_a_constructed_difference_is_played_again(self):
        warm = changed(self.lines, 2, "Add To Stack: ", "Add To Stack:  ")
        fresh_game = copy_of(self.lines).masked(1)
        found, calls = self.compare(warm, replay=lambda i: fresh_game)
        self.assertEqual(calls, [1])
        self.assertEqual([kind for kind, _ in found], ["unsure"])
        self.assertIn("game 21", found[0][1])
        self.assertIn("didn't come back", found[0][1])
        warm_game = copy_of(warm).masked(1)
        found, _ = self.compare(warm, replay=lambda i: warm_game)
        self.assertEqual([kind for kind, _ in found], ["failed"])
        self.assertIn("differed again", found[0][1])
        found, _ = self.compare(warm, replay=lambda i: None)        # the replay hit a time limit
        self.assertEqual([kind for kind, _ in found], ["unsure"])

    def test_a_different_outcome_or_card_log_fails_at_once(self):
        found, calls = self.compare(drawn(self.lines, 3))
        self.assertEqual(([kind for kind, _ in found], calls), (["failed"], []))
        self.assertIn("fresh and", found[0][1])
        found, calls = self.compare(changed(self.lines, 1, "Information: DL|zone|", "Information: DL|zone|0"))
        self.assertEqual(([kind for kind, _ in found], calls), (["failed"], []))
        self.assertIn("only the card log's lines differ", found[0][1])
        engine = [line.replace("avgcmc=2,2", "avgcmc=4,4") for line in self.lines]
        found, _ = self.compare(engine)
        self.assertEqual([kind for kind, _ in found], ["failed"])
        self.assertIn("DLENGINE", found[0][1])

    def test_time_limits_make_it_unsure(self):
        # A time limit in an earlier game of the fresh process (and the warm one): no replay, unsure.
        fresh = changed(self.lines, 2, "Turn: Turn 1 ", "AI eval thread at timeout:\nTurn: Turn 1 ")
        warm = changed(fresh, 3, "Add To Stack: ", "Add To Stack:  ")
        found, calls = self.compare(warm, fresh=fresh)
        self.assertEqual(([kind for kind, _ in found], calls), (["unsure"], []))
        self.assertIn("game 22", found[0][1])
        self.assertIn("time limits", found[0][1])
        # In the warm game itself.
        warm = changed(self.lines, 3, "Turn: Turn 1 ", "Stopping slow match as draw\nTurn: Turn 1 ")
        found, calls = self.compare(warm)
        self.assertEqual(([kind for kind, _ in found], calls), (["unsure"], []))

    def test_commander_games_by_outcome(self):
        lines = changed(self.commander_lines, 2, "Add To Stack: ", "Add To Stack:  ")
        self.assertEqual(self.compare(lines, request=self.commander), ([], []))
        found, calls = self.compare(drawn(self.commander_lines, 2), request=self.commander)
        self.assertEqual(([kind for kind, _ in found], calls), (["unsure"], []))
        self.assertIn("doesn't play a Commander game the same way every time", found[0][1])

    def test_games_the_worker_didnt_play(self):
        cut = self.lines[:max(i for i, line in enumerate(self.lines) if line.startswith("Game Result: Game 3"))]
        found, _ = self.compare(cut, cut=True)        # a v1 batch the worker was replaced in
        self.assertEqual([kind for kind, _ in found], ["unsure"])
        self.assertIn("weren't compared", found[0][1])
        for warm, fresh in ((cut, None), (self.lines, cut)):      # fewer or more games for no reason
            found, _ = self.compare(warm, fresh=fresh)
            self.assertEqual([kind for kind, _ in found], ["failed"])

    def test_card_log_findings(self):
        request = self.request
        self.assertEqual(servecheck._card_log_findings(request, copy_of(self.lines), "warm"), [])
        bad = [line for line in self.lines if not line.startswith("Information: DL|log|")]
        found = servecheck._card_log_findings(request, copy_of(bad), "warm")
        self.assertTrue(found and all(kind == "failed" for kind, _ in found))
        self.assertIn("played warm: The card log wrote its lines in 0 of the 4", found[0][1])
        lines = [line for line in self.commander_lines if not line.startswith("Information: DL|commander|2|")]
        found = servecheck._card_log_findings(self.commander, copy_of(lines, "Commander"), "fresh")
        self.assertTrue(any("both commanders" in line for _, line in found))

    def test_the_verdict(self):
        self.assertIsNone(servecheck._verdict([], "2.0.15"))
        kind, lines = servecheck._verdict([("unsure", "a; it hit one of Forge's time limits"), ("failed", "b")], "2.0.15")
        self.assertEqual(kind, "failed")
        self.assertEqual(lines, ["A warm worker didn't play the same games as fresh processes with Forge 2.0.15:",
                                 "  a; it hit one of Forge's time limits", "  b"])
        kind, lines = servecheck._verdict([("unsure", "a; it hit one of Forge's time limits")], None)
        self.assertEqual(kind, "unsure")
        self.assertIn("less busy", lines[-1])
        self.assertTrue(servecheck._verdict([("unsure", "a")], None)[1][-1].endswith("Run it again."))


# ============================================================ warm_leg against the fake Forge

class WarmLegTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, text, kind in (("green", test_forge.GREEN, "constructed"), ("red", test_forge.RED, "constructed"),
                                 ("gisa", test_forge.GISA, "commander"), ("mirror", test_forge.MIRROR_GISA, "commander")):
            e = test_forge.entry(text, f"casual/{name}", kind=kind)
            (self.tmp / f"{name}.dck").write_text(e["dck"], encoding="utf-8")
        (self.tmp / "user").mkdir()
        self.setup = {"forge_dir": self.tmp, "clock_s": 120, "workers": 4, "version": "2.0.15",
                      "user_dir": self.tmp / "user"}
        self.log = self.tmp / "starts.log"
        self.env = dict(os.environ, APPDATA=str(self.tmp), FAKE_FORGE="", FAKE_FORGE_LOG=str(self.log))
        self.plays = []
        real_play = servecheck._Worker.play

        def play(worker, request_id, args, games):
            self.plays.append((worker.out.proc.pid, request_id, args))
            return real_play(worker, request_id, args, games)
        patcher = mock.patch.object(servecheck._Worker, "play", play)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.all_dead)

    def all_dead(self):
        pids = {pid for pid, _, _ in self.plays}
        if self.log.exists():
            pids |= {int(line.split()[0]) for line in self.log.read_text(encoding="utf-8").splitlines()}
        for pid in pids:
            self.assertTrue(test_forge.wait_dead(pid), f"process {pid} is still running")

    def leg(self, requests, modes=""):
        self.env["FAKE_FORGE"] = modes
        with redirect_stderr(io.StringIO()) as err:
            found = servecheck.warm_leg(self.setup, self.tmp, self.env, test_forge.CARD_LOG, requests)
        self.err = err.getvalue()
        return found

    @staticmethod
    def first_of(args):
        """A request's (first game, games) from its arguments."""
        return int(args[args.index("-dlgame") + 2]), int(args[args.index("-n") + 1])

    def test_the_same_games_pass(self):
        requests = [("Constructed", "green.dck", "red.dck", 3, 1, v2(22)), ("Constructed", "red.dck", "green.dck", 2, 1, v2(25)),
                    ("Constructed", "green.dck", "red.dck", 3, 5, None), ("Commander", "gisa.dck", "mirror.dck", 2, 1, v2(0))]
        self.assertIsNone(self.leg(requests))
        # One worker played them in its own order, the first again at the end.
        self.assertEqual(len({pid for pid, _, _ in self.plays}), 1)
        played = [args for _, _, args in self.plays]
        expected = [runner.request_args(dict(self.setup, decks_dir=self.tmp), *requests[i])
                    for i in servecheck._order(requests)]
        self.assertEqual(played, expected)
        self.assertEqual(len({request_id for _, request_id, _ in self.plays}), len(played))
        self.assertIn("unpinned", self.err)

    def test_the_worker_is_pinned_to_its_slots_core(self):
        pins = []
        with mock.patch.object(forge.cores, "pin", lambda pid, slot: pins.append((pid, slot)) or True):
            self.assertIsNone(self.leg([("Constructed", "green.dck", "red.dck", 2, 1, v2(0)),
                                        ("Constructed", "green.dck", "red.dck", 2, 1, v2(2))]))
        worker = self.plays[0][0]
        self.assertEqual(pins, [(worker, 0)] * (1 + len(self.plays)))      # at its start and before each request
        self.assertIn("pinned to core 0", self.err)

    def test_a_worker_that_recycles_is_replaced(self):
        # Its clock stops game 23, the last of its request: the next request goes to a new worker.
        requests = [("Constructed", "green.dck", "red.dck", 4, 1, v2(20)), ("Constructed", "red.dck", "green.dck", 2, 1, v2(25))]
        self.assertIsNone(self.leg(requests, "timeout#23"))
        workers = [pid for pid, _, _ in self.plays]
        self.assertEqual([self.first_of(args) for _, _, args in self.plays], [(25, 2), (20, 4), (25, 2)])
        self.assertEqual(len(set(workers)), 2)
        self.assertNotEqual(workers[1], workers[2])

    def test_a_v2_request_goes_on_in_a_new_worker(self):
        for modes in ("timeout#21", "exception#21", "aitimeoutunseen#21"):
            # Java recycles after game 21 (a clock stop, a crash), or the check kills the worker
            # there (an AI timeout only its lines show): games 22-23 go to a new worker.
            self.plays.clear()
            spied = []

            # The copies' games, by outcome only: the fake keeps a running score in its Match
            # Result lines over a process's v2 games, where Forge has a Match per game, so a
            # resumed part's lines differ there (CompareTests compare lines).
            def compare(request, fresh, warm, *rest):
                spied.append((servecheck._outcomes(fresh), servecheck._outcomes(warm)))
                return []
            with mock.patch.object(servecheck, "_compare", compare):
                self.assertIsNone(self.leg([("Constructed", "green.dck", "red.dck", 4, 1, v2(20))], modes))
            # The repeat goes the same way.
            self.assertEqual([self.first_of(args) for _, _, args in self.plays], [(20, 4), (22, 2)] * 2, modes)
            self.assertEqual(len({pid for pid, _, _ in self.plays}), 3, modes)
            self.assertEqual(len(spied), 2)
            for fresh, warm in spied:
                self.assertEqual(fresh, warm)
                self.assertEqual(len(warm), 4)

    def test_a_v1_batch_cut_short_is_unsure(self):
        found = self.leg([("Constructed", "green.dck", "red.dck", 3, 5, None)], "timeout@5#2")
        self.assertEqual(found[0], "unsure")
        self.assertIn("weren't compared", "\n".join(found[1]))

    def test_a_difference_only_the_worker_makes_fails(self):
        real_start = servecheck._start
        for modes, words in (("avgcmc=4,3", "DLENGINE"), ("badcardlog#21", "card log")):
            def start(argv, cwd, env):
                return real_start(argv, cwd, dict(env, FAKE_FORGE=modes) if "serve" in argv else env)
            with mock.patch.object(servecheck, "_start", start):
                found = self.leg([("Constructed", "green.dck", "red.dck", 3, 1, v2(20))])
            self.assertEqual(found[0], "failed", modes)
            self.assertIn(words, "\n".join(found[1]))

    def test_what_cant_be_played_raises(self):
        request = [("Constructed", "green.dck", "red.dck", 2, 1, v2(0))]
        fresh = "couldn't be played by a fresh process"     # the fresh process may fail first
        for modes, words in (("servefail", ["A warm worker couldn't start"]),
                             ("noload", ["couldn't play the check's request: Could not load deck", fresh]),
                             ("unsupported", [f"{fresh}. Forge doesn't know these cards"]),
                             ("crash#1", ["stopped part way", f"{fresh}. Forge stopped with an error"])):
            with self.assertRaises(forge.ForgeError, msg=modes) as caught:
                self.leg(request, modes)
            self.assertTrue(any(w in str(caught.exception) for w in words), (modes, str(caught.exception)))


# ============================================================ the command

class CommandTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        setup = {"forge_dir": self.tmp, "jar": "forge.jar", "version": "2.0.15", "java": "java", "user_dir": self.tmp,
                 "clock_s": 120, "workers": 4}
        self.calls = []
        self.answer = None

        def leg(setup_, folder, env, card_log, requests):
            self.calls.append((setup_, Path(folder), card_log, requests))
            return self.answer
        self.setup = setup
        self.game_patches = [ATTACK_ORDER_ID]        # R14b built in (warm_decks)
        for p in (mock.patch.object(forge.cli, "_setup", lambda: dict(self.setup)),
                  mock.patch.object(forge.simjar, "card_log", lambda *a, **k: dict(
                      test_forge.CARD_LOG, game_patches=self.game_patches, checking=k)),
                  mock.patch.object(forge.cli, "_prepare_user_dir", lambda user_dir: {"APPDATA": str(user_dir)}),
                  mock.patch.object(servecheck, "warm_leg", leg)):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        """(exit code, stdout, stderr) of serve-check with argv."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.cli.main(["serve-check", *argv])
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_it_checks_cardlog_checks_lists_and_its_own(self):
        code, out, err = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("A warm worker played the same 21 games as fresh processes with Forge 2.0.15.", out)
        (setup, folder, card_log, requests), = self.calls
        self.assertEqual(card_log["checking"], {"checking": True})       # built for this source, as cardlog-check
        self.assertFalse(folder.exists())                               # the decks' folder is tidied away
        names = {name for _, d1, d2, *_ in requests for name in (d1, d2)}
        self.assertEqual(names, {f"{name}.dck" for name in [*forge.cli.CHECK_DECKS, *servecheck.WARM_DECKS,
                                                            *forge.cli.CHECK_COMMANDER_DECKS]})
        self.assertEqual(sum(r[3] for r in requests if r[0] == "Commander"), servecheck.COMMANDER_GAMES)
        self.assertTrue(all(r[5] for r in requests))
        self.assertIn("(v2)", err)

    def test_without_the_attack_checks_in_order(self):
        """Without R14b in play, the double-faced and adventure lists are left out, and it says so."""
        for game_patches, setup in (([], {}), ([ATTACK_ORDER_ID], {"game_patches": False})):
            self.calls.clear()
            self.game_patches = game_patches
            self.setup = dict(self.setup, **setup)
            code, out, err = self.run_cli()
            self.assertEqual(code, 0)
            self.assertIn("the same 15 games", out)
            names = {name for _, d1, d2, *_ in self.calls[0][3] for name in (d1, d2)}
            self.assertFalse(names & {f"{name}.dck" for name in servecheck.WARM_DECKS})
            self.assertIn("lists of double-faced and adventure cards are left out", err)

    def test_options(self):
        self.run_cli("--games", "8", "--commander-games", "1", "--v1")
        requests = self.calls[0][3]
        self.assertEqual(sum(r[3] for r in requests), 8 + 4 + 1)
        self.assertTrue(all(r[5] is None for r in requests))

    def test_what_it_says_when_games_differ(self):
        self.answer = ("failed", ["A warm worker didn't play the same games as fresh processes with Forge 2.0.15:",
                                  "  x"])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("  x\nA warm pool would play other games", out)
        self.answer = ("unsure", ["head", "  y", "So the check can't tell... Run it again."])
        code, out, _ = self.run_cli()
        self.assertEqual(code, 1)
        self.assertNotIn("A warm pool would", out)

    def test_without_the_card_log(self):
        with mock.patch.object(forge.simjar, "card_log", lambda *a, **k: {"ready": False, "problem": "No JDK."}):
            code, out, err = self.run_cli()
        self.assertEqual((code, self.calls), (1, []))
        self.assertIn("No JDK.", err)


if __name__ == "__main__":
    unittest.main()
