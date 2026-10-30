"""Real-Forge tests of serve mode (java/decklab/DeckLabServe.java) and the warm reset
(WarmState.java): reset() takes Card.cp2card back to its keys and the id counters back to
their snapshot; a warm worker plays a request as a fresh DeckLabSim process plays the same
arguments, after another matchup's requests too, in Constructed and Commander; a cancel stops a
request at a game boundary; a game the clock stops ends its request with "recycle" and the
worker exits; arguments it can't read end a request with "error" and the worker plays on.

They need Forge and a Java JDK, so they run only with DECKLAB_FORGE_TESTS=1, and they're small
(at most 3 Forge processes at once, a few games each): the card-log jar is built for this
source (as cardlog-check builds it), in the data folder. The same checks without Java, against
the fake Forge's serve mode, are test_forge_contract's FakeServeTests and test_forge_servecheck.

Real-Forge qualification requires separate explicit authorization; the default fixture runner disables it.
Run from the repo root: python -m unittest decklab.tests.test_forge_serve
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from decklab.lib.forge import cli, install, runner, servecheck, simjar
from decklab.lib.forge.logreader import SLOW_STOP

REAL = os.environ.get("DECKLAB_FORGE_TESTS") == "1"
V2_MISSING = "isn't built yet"          # GameLoop.playGames' answer before the v2 engine
FLAGS = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if sys.platform == "win32" else 0
# WarmState from outside its package (reflection: the class path is one unnamed module). A key
# in Card.cp2card at snapshot() stays and one put in after it goes, a counter moved on is put
# back, and a pass over cp2card's keys that another thread disturbs (a key whose hashCode adds
# a key, as a clock-stopped game thread still running could) is tried again, CACHE_TRIES times
# in all, and then ends with IllegalStateException, the one exception reset() throws.
PROBE = """
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.Map;

public class WarmStateProbe {
    static Map<Object, Object> cache;

    static final class Meddler {
        int meddles;

        @Override
        public int hashCode() {
            if (meddles > 0) {
                meddles--;
                cache.put(new Object(), "meddled");
            }
            return 7;
        }
    }

    public static void main(String[] args) throws Exception {
        Class<?> ws = Class.forName("decklab.WarmState");
        @SuppressWarnings("unchecked") Map<Object, Object> found = (Map<Object, Object>) field("forge.game.card.Card", "cp2card").get(null);
        cache = found;
        cache.put("start-up", "x");
        call(ws, "snapshot");
        System.out.println("problem=" + call(ws, "problem"));
        cache.put("added", "x");
        Field maxId = field("forge.game.spellability.SpellAbility", "maxId");
        Object start = call(ws, "counters");
        maxId.setInt(null, maxId.getInt(null) + 1000);
        Object moved = call(ws, "counters");
        call(ws, "reset");
        System.out.println("cp2card=" + cache.containsKey("start-up") + "," + cache.containsKey("added") + "," + cache.size());
        System.out.println("counters=" + start + ";" + moved + ";" + call(ws, "counters"));
        int tries = field("decklab.WarmState", "CACHE_TRIES").getInt(null);
        Meddler meddler = new Meddler();
        cache.put(meddler, "x");
        meddler.meddles = tries - 1;
        call(ws, "reset");
        System.out.println("tried again=" + cache.containsKey("start-up") + "," + cache.size() + "," + meddler.meddles);
        meddler = new Meddler();
        cache.put(meddler, "x");
        meddler.meddles = Integer.MAX_VALUE;
        try {
            call(ws, "reset");
            System.out.println("never settles=no exception");
        } catch (InvocationTargetException e) {
            Throwable t = e.getCause();
            System.out.println("never settles=" + t.getClass().getName() + ","
                               + (t.getCause() == null ? null : t.getCause().getClass().getName()) + ","
                               + (Integer.MAX_VALUE - meddler.meddles));
        }
        meddler.meddles = 0;
        System.out.println("problem after=" + call(ws, "problem"));
    }

    static Object call(Class<?> c, String name) throws Exception {
        Method m = c.getDeclaredMethod(name);
        m.setAccessible(true);
        return m.invoke(null);
    }

    static Field field(String c, String name) throws Exception {
        Field f = Class.forName(c).getDeclaredField(name);
        f.setAccessible(true);
        return f;
    }
}
"""


@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class ServeTests(unittest.TestCase):
    """A real serve worker on cardlog-check's lists."""

    @classmethod
    def setUpClass(cls):
        setup = install._setup()
        cls.card_log = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"],
                                       checking=True)
        if not cls.card_log["ready"]:
            raise unittest.SkipTest(cls.card_log["problem"])
        cls.folder = Path(tempfile.mkdtemp(prefix="decklab-serve-test-"))
        cls.setup = setup
        cls.launch = dict(setup, decks_dir=cls.folder, card_log=cls.card_log)
        servecheck.write_decks(cls.folder, {name: ([], cards) for name, cards in cli.CHECK_DECKS.items()})
        servecheck.write_decks(cls.folder, cli.CHECK_COMMANDER_DECKS)
        cls.env = runner._prepare_user_dir(setup["user_dir"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)
        runner._tidy_user_dir(cls.setup["user_dir"])

    def start(self, launch=None):
        """A serve worker: (its _Output, its ready event)."""
        proc = servecheck._start(runner.serve_command(launch or self.launch), self.setup["forge_dir"], self.env)
        out = servecheck._Output(proc)
        self.addCleanup(out.end)
        ready = self.until(out, "DLSERVE|ready|")[-1]
        return out, runner.serve_event(ready)

    def until(self, out, prefix, seconds=300):
        got = []
        deadline = time.monotonic() + seconds
        while True:
            line = out.get(deadline)
            if line is None:
                return got + [None]
            got.append(line)
            if line.startswith(prefix):
                return got

    @staticmethod
    def send(out, text):
        out.proc.stdin.write(text)
        out.proc.stdin.flush()

    def args(self, fmt, games, seed, launch=None, v2=None):
        decks = list(cli.CHECK_DECKS if fmt == "Constructed" else cli.CHECK_COMMANDER_DECKS)
        return runner.request_args(launch or self.launch, fmt, f"{decks[0]}.dck", f"{decks[1]}.dck", games, seed, v2)

    def test_reset_takes_cp2card_and_the_counters_back_to_the_snapshot(self):
        """Not a plain clear: cp2card's keys at snapshot() stay, later ones go (PROBE)."""
        probe = self.folder / "WarmStateProbe.java"
        probe.write_text(PROBE, encoding="utf-8")
        class_path = os.pathsep.join([self.card_log["jar"], str(self.setup["forge_dir"] / self.setup["jar"])])
        done = subprocess.run([self.setup["java"], "-cp", class_path, str(probe)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=FLAGS)
        lines = done.stdout.splitlines()
        self.assertIn("problem=null", lines, done.stdout + done.stderr)
        self.assertIn("cp2card=true,false,1", lines)            # the start-up key stays, the added one goes
        counters = next(line for line in lines if line.startswith("counters=")).split("=", 1)[1].split(";")
        self.assertEqual(counters[0], counters[2])
        self.assertNotEqual(counters[0], counters[1])
        # A pass another thread disturbs is tried again; one that never settles gives up after
        # CACHE_TRIES passes with IllegalStateException (the v2 loop's "Error:" line), and the
        # worker's state is still usable.
        self.assertIn("tried again=true,1,0", lines)
        self.assertIn("never settles=java.lang.IllegalStateException,java.util.ConcurrentModificationException,3",
                      lines)
        self.assertIn("problem after=null", lines)

    def test_warm_requests_play_the_fresh_games(self):
        """Requests of two matchups (v1), the first again at the end, each the fresh process's games."""
        a, b = (f"{name}.dck" for name in cli.CHECK_DECKS)
        k, i = (f"{name}.dck" for name in cli.CHECK_COMMANDER_DECKS)
        requests = [("Constructed", a, b, 3, 11, None), ("Constructed", b, a, 2, 12, None),
                    ("Commander", k, i, 1, 13, None)]
        self.assertIsNone(servecheck.warm_leg(self.setup, self.folder, self.env, self.card_log, requests))

    def test_warm_v2_requests_play_the_fresh_games(self):
        """The same with v2 requests, once the v2 engine is in the jar (wave 2's EJ package)."""
        stream = "0123456789abcdef"
        out, _ = self.start()
        self.send(out, runner.request_line("probe", self.args("Constructed", 1, 1, v2={"stream": stream, "first": 0})))
        if any(line and V2_MISSING in line for line in self.until(out, "DLSERVE|end|probe|")):
            self.skipTest("the v2 engine isn't in this jar yet")
        a, b = (f"{name}.dck" for name in cli.CHECK_DECKS)
        k, i = (f"{name}.dck" for name in cli.CHECK_COMMANDER_DECKS)
        requests = [("Constructed", a, b, 2, 1, {"stream": stream, "first": 23}),
                    ("Constructed", b, a, 2, 1, {"stream": stream, "first": 25}),
                    ("Commander", k, i, 1, 1, {"stream": stream, "first": 0})]
        self.assertIsNone(servecheck.warm_leg(self.setup, self.folder, self.env, self.card_log, requests))

    def test_cancel_stops_a_request_at_a_game_boundary(self):
        out, ready = self.start()
        self.assertEqual(ready["protocol"], runner.SERVE_PROTOCOL)
        self.send(out, runner.request_line("r1", self.args("Constructed", 20, 5)))
        got = self.until(out, "Game Result:")
        self.send(out, "cancel\tr1\n")
        got += self.until(out, "DLSERVE|end|r1|")
        end = runner.serve_event(got[-1])
        self.assertEqual(end["status"], "cancelled")
        self.assertLess(end["games"], 20)
        self.assertEqual(end["games"], sum(1 for line in got if line and line.startswith("Game Result:")))
        self.assertRegex(end["detail"], r"^heap_mb=\d+$")
        # It plays on: a request after a cancel is played in full.
        self.send(out, runner.request_line("r2", self.args("Constructed", 1, 6)))
        self.assertRegex(self.until(out, "DLSERVE|end|r2|")[-1], r"^DLSERVE\|end\|r2\|done\|1\|\d+\|heap_mb=\d+$")
        self.send(out, "quit\n")
        self.assertEqual(self.until(out, "DLSERVE|bye|")[-1], "DLSERVE|bye|quit")
        self.assertEqual(out.proc.wait(30), 0)

    def test_a_clock_stop_ends_the_request_and_the_worker(self):
        launch = dict(self.launch, clock_s=1)       # a Commander game takes longer than a second
        out, _ = self.start(launch)
        self.send(out, runner.request_line("r1", self.args("Commander", 3, 7, launch)))
        got = self.until(out, "DLSERVE|bye|")
        self.assertIn(SLOW_STOP, got)
        end = runner.serve_event(next(line for line in got if line and line.startswith("DLSERVE|end|r1|")))
        self.assertEqual((end["status"], end["detail"]), ("recycle", "clock"))
        results = [line for line in got if line and line.startswith("Game Result:")]
        self.assertEqual(end["games"], len(results))
        self.assertLess(end["games"], 3)            # it stopped at the game the clock stopped
        self.assertEqual(got[-1], "DLSERVE|bye|recycle")
        self.assertEqual(out.proc.wait(30), 0)

    def test_arguments_it_cant_read_end_the_request_and_it_plays_on(self):
        out, _ = self.start()
        bad = self.args("Constructed", 1, 3)
        bad[bad.index("-n") + 1] = "x"
        self.send(out, runner.request_line("r1", bad))
        got = self.until(out, "DLSERVE|end|r1|")
        self.assertTrue(any(line.startswith("Error: java.lang.NumberFormatException") for line in got))
        self.assertEqual(runner.serve_event(got[-1])["status"], "error")
        self.send(out, runner.request_line("r2", self.args("Constructed", 1, 3)))
        self.assertEqual(runner.serve_event(self.until(out, "DLSERVE|end|r2|")[-1])["status"], "done")
        out.proc.stdin.close()                      # the end of stdin ends it
        self.assertEqual(self.until(out, "DLSERVE|bye|")[-1], "DLSERVE|bye|eof")
        self.assertEqual(out.proc.wait(30), 0)


if __name__ == "__main__":
    unittest.main()
