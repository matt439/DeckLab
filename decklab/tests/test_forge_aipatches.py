"""Tests for Deck Lab's changes to Forge's AI classes, in its fork of Forge since 2026-10-11 (the
fork's decklab branch; until then copies in the card log's jar; the wave 2 contract's
"Game-changing patches", decklab/forge-trial/sim-wave2-contract.md):

- AiController (sim-investigation.md R14a): each AI decision's "Game AI Eval" on a virtual
  thread, or on a platform thread while an earlier eval still runs (forge.ai.AiSignals.LIVE_EVALS
  above 0), with the AiSignals counts. It plays the same games ("-" in Forge's list).
- AiAttackController (R14b): the checks of which attackers must attack run in turn, in attacker
  order, instead of on a thread pool, unless -Ddecklab.gamePatches=off. It changes games
  (attack-requirements-in-order-1 in Forge's list).

The fork holds their source, so what they keep of Forge's own code is the fork's to show (its
diff against tag forge-2.0.15). With DECKLAB_FORGE_TESTS=1 and the fork's build installed, a test
probe (PROBE, compiled here) plays a few games: no platform eval threads while LIVE_EVALS is 0
and platform ones while it's held above 0, the same games either way; AI timeouts counted (an AI
timeout of 0 s); a task that throws, or overflows its stack, passes that attacker over and the
game goes on (a copy of the fork's class that does both, from the fork's source: FORK); the same
seed plays the same game, forced attackers in the same order, in two JVMs; and with
-Ddecklab.gamePatches=off the class plays Forge's thread pool.

Real-Forge qualification requires separate explicit authorization; the default fixture runner disables it.
Run from the repo root: python -m unittest decklab.tests.test_forge_aipatches
"""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.tests import test_forge_simjar as base

simjar = forge.simjar
cli = forge.cli
AICONTROLLER = "forge/ai/AiController.class"
ATTACK = "forge/ai/AiAttackController.class"
ATTACK_ID = "attack-requirements-in-order-1"
# The fork of Forge's clone (its decklab branch checked out): the throwing test's class is made from its source.
FORK = Path(os.environ.get("DECKLAB_FORGE_FORK") or Path(__file__).resolve().parents[2].parent / "forge")
FORK_ATTACK = FORK / "forge-ai" / "src" / "main" / "java" / "forge" / "ai" / "AiAttackController.java"


PROBE = r'''package decklabprobe;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.List;
import java.util.Random;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import decklab.DeckLabSim;
import forge.GuiDesktop;
import forge.ai.AiSignals;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.Game;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.player.RegisteredPlayer;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.util.MyRandom;
import forge.view.TimeLimitedCodeBlock;

/*
 * Deck Lab's test probe for its changes to Forge's AI classes (decklab/tests/test_forge_aipatches.py):
 *   hold <n> sim <args>                 DeckLabSim sim, with forge.ai.AiSignals.LIVE_EVALS held n above 0
 *   timeout <s> <folder> <a> <b> <seed> one Constructed game with the game's AI timeout set to s seconds
 * Both print "PROBE|end|timeouts=<AiSignals.AI_TIMEOUTS>|live=<AiSignals.LIVE_EVALS>" as the JVM exits.
 */
public final class AiPatchProbe {
    public static void main(String[] args) throws Exception {
        Runtime.getRuntime().addShutdownHook(new Thread(() -> System.out.println(
                "PROBE|end|timeouts=" + AiSignals.AI_TIMEOUTS.get() + "|live=" + AiSignals.LIVE_EVALS.get())));
        if (args[0].equals("hold")) {
            AiSignals.LIVE_EVALS.addAndGet(Integer.parseInt(args[1]));
            DeckLabSim.main(Arrays.copyOfRange(args, 2, args.length));
            return;
        }
        System.setProperty("java.awt.headless", "true");
        System.setProperty("java.util.Arrays.useLegacyMergeSort", "true");
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        MyRandom.setRandom(new Random(Long.parseLong(args[5])));
        GameRules rules = new GameRules(GameType.Constructed);
        rules.setAppliedVariants(EnumSet.of(GameType.Constructed));
        List<RegisteredPlayer> players = new ArrayList<>();
        for (int i = 0; i < 2; i++) {
            Deck deck = DeckSerializer.fromFile(new File(args[2], args[3 + i]));
            RegisteredPlayer rp = new RegisteredPlayer(deck);
            rp.setPlayer(GamePlayerUtil.createAiPlayer("Ai(" + (i + 1) + ")-" + deck.getName(), i, "Default"));
            players.add(rp);
        }
        Match match = new Match(rules, players, "Probe");
        Game game = match.createGame();
        game.setNoGUIUser();
        game.AI_TIMEOUT = Integer.parseInt(args[1]);
        try {
            TimeLimitedCodeBlock.runWithTimeout(() -> match.startGame(game), 120, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            System.out.println("PROBE|clock");
        }
        for (int i = 0; i < 50 && AiSignals.LIVE_EVALS.get() > 0; i++) {
            Thread.sleep(100);      // an eval cancelled at its timeout ends at its next check
        }
        System.out.println("PROBE|game|turn=" + game.getPhaseHandler().getTurn() + "|over=" + game.isGameOver());
        System.out.flush();
        System.exit(0);
    }
}
'''
# A copy of the fork's AiAttackController whose first attacker's task throws (with
# -Ddecklab.probe.throwFirst=true and two or more attackers) and whose second attacker's task
# overflows the game thread's stack (three or more attackers: a real StackOverflowError, from
# endless recursion), and which says what it does: (exact line in the fork's, what goes in its place).
THROWING = [
    ("                tasks.add(() -> {",
     '                tasks.add(() -> { if (Boolean.getBoolean("decklab.probe.throwFirst") && this.attackers.size() > 1 '
     '&& attacker == this.attackers.get(0)) { System.out.println("PROBE|threw|" + attacker); '
     'throw new IllegalStateException("probe: the first attacker\'s task throws"); } '
     'if (Boolean.getBoolean("decklab.probe.throwFirst") && this.attackers.size() > 2 '
     '&& attacker == this.attackers.get(1)) { System.out.println("PROBE|overflowed|" + attacker); '
     'new Object() { int down(int n) { return down(n + 1) + 1; } }.down(0); }'),
    ("                        numForcedAttackers.incrementAndGet();",
     '                        numForcedAttackers.incrementAndGet(); System.out.println("PROBE|forced|" + attacker);'),
    ("            try { if (DECKLAB_IN_ORDER) { for (Callable<Integer> task : tasks) { try { task.call(); } "
     "catch (Exception | StackOverflowError e) { } } } else",
     '            System.out.println("PROBE|declare|" + tasks.size()); try { if (DECKLAB_IN_ORDER) { '
     'for (Callable<Integer> task : tasks) { try { task.call(); } catch (Exception | StackOverflowError e) { } } } else'),
]
# Creatures that must attack (Rabblemaster and Warboss force their Goblins too), against the
# card-log check's blue-black deck, which blocks.
FORCED = ["4 Crazed Goblin", "4 Valley Dasher", "4 Goblin Guide", "4 Goblin Rabblemaster", "4 Legion Warboss",
          "4 Bloodrock Cyclops", "4 Reckless Brute", "4 Juggernaut", "4 Lightning Bolt", "24 Mountain"]
SEED = 7
RE_JVM_LOG = re.compile(r"^\[\d+\.\d+s\]")         # -Xlog lines
RE_POOL_THREAD = re.compile(r'exiting \(name: "pool-\d+-thread-\d+"')


def _javac(java, classpath, out, sources):
    javac = Path(java).parent / ("javac.exe" if os.name == "nt" else "javac")
    done = subprocess.run([str(javac), "-encoding", "UTF-8", "-cp", os.pathsep.join(map(str, classpath)),
                           "-d", str(out), *map(str, sources)], capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise AssertionError(f"javac failed:\n{done.stdout}{done.stderr}")


def _play(argv, setup, env, out, started=None):
    """Run one Forge process (below normal priority, in Deck Lab's job) to its end; its output
    goes in out[argv's tag]. Killed after 600 s."""
    proc = forge.processes.start_process(argv[1:], cwd=setup["forge_dir"], env=env)
    timer = threading.Timer(600, forge.processes.kill_process, args=(proc,))
    timer.start()
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if started is not None and cli.RE_HEADER.match(line):
                started.set()
        proc.wait()
    finally:
        timer.cancel()
        forge.processes.kill_process(proc)
        proc.stdout.close()
        if started is not None:
            started.set()
    out[argv[0]] = "".join(lines)


@unittest.skipUnless(base.REAL, "set DECKLAB_FORGE_TESTS=1 to play games with the real JDK and Forge")
class RealGameTests(unittest.TestCase):
    """A few real games through the test probe: at most 3 Forge processes at once."""

    @classmethod
    def setUpClass(cls):
        cls.setup = forge.install._setup()
        if not simjar.forge_patches(cls.setup["forge_dir"] / cls.setup["jar"]):
            raise unittest.SkipTest("the installed Forge isn't Deck Lab's build of its fork")
        if not FORK_ATTACK.is_file():
            raise unittest.SkipTest(f"the fork of Forge isn't cloned at {FORK} (DECKLAB_FORGE_FORK)")
        cls.tmp = Path(tempfile.mkdtemp())
        try:
            cls._prepare()
            cls._play_all()
        except BaseException:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _prepare(cls):
        setup, tmp = cls.setup, cls.tmp
        with mock.patch.object(forge.common, "DATA_DIR", tmp / "data"):
            simjar._built.clear()
            cls.log = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"], checking=True)
            simjar._built.clear()
        assert cls.log["ready"], cls.log
        forge_jar = setup["forge_dir"] / setup["jar"]
        (tmp / "probe" / "decklabprobe").mkdir(parents=True)
        (tmp / "probe" / "decklabprobe" / "AiPatchProbe.java").write_text(PROBE, encoding="utf-8")
        _javac(setup["java"], [cls.log["jar"], forge_jar], tmp / "probe-classes",
               [tmp / "probe" / "decklabprobe" / "AiPatchProbe.java"])
        text = FORK_ATTACK.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        for old, new in THROWING:
            assert text.count(f"\n{old}\n") == 1, old
            text = text.replace(f"\n{old}\n", f"\n{new}\n")
        (tmp / "throwing" / "forge" / "ai").mkdir(parents=True)
        (tmp / "throwing" / "forge" / "ai" / "AiAttackController.java").write_text(text, encoding="utf-8")
        _javac(setup["java"], [cls.log["jar"], forge_jar], tmp / "throwing-classes",
               [tmp / "throwing" / "forge" / "ai" / "AiAttackController.java"])
        cls.decks = tmp / "decks"
        cls.decks.mkdir()
        for name, cards in (("forced", FORCED), ("blockers", cli.CHECK_DECKS["cardlog-check-b"])):
            (cls.decks / f"{name}.dck").write_text(f"[metadata]\nName={name}\n[Main]\n" + "\n".join(cards) + "\n",
                                                   encoding="utf-8", newline="\n")

    @classmethod
    def _command(cls, tag, probe, games=0, jvm=(), first=()):
        """[tag, argv]: the probe in the card log's launch (game patches on), with probe's
        arguments in place of DeckLabSim's main class ("hold n" keeps DeckLabSim's sim
        arguments after it), the folders first on the class path and the JVM flags jvm."""
        launch = dict(cls.setup, decks_dir=cls.decks, card_log=cls.log)
        argv = forge.runner.build_command(launch, "Constructed", "forced.dck", "blockers.dck", games or 1, SEED)
        i = argv.index("-cp")
        argv[i + 1] = os.pathsep.join([*map(str, first), str(cls.tmp / "probe-classes"), argv[i + 1]])
        if probe[0] == "hold":
            argv[i + 2:i + 3] = ["decklabprobe.AiPatchProbe", *probe]
        else:
            argv[i + 2:] = ["decklabprobe.AiPatchProbe", *probe]
        return [tag, argv[0], *jvm, *argv[1:]]

    @classmethod
    def _play_all(cls):
        env = forge.runner._prepare_user_dir(cls.setup["user_dir"])
        xlog = ("-Xlog:os+thread=info", "-Xlog:class+load=info")
        waves = [
            [cls._command("virtual", ("hold", "0"), 3, xlog), cls._command("platform", ("hold", "1"), 3, xlog),
             cls._command("again", ("hold", "0"), 3)],
            [cls._command("timeouts", ("timeout", "0", str(cls.decks), "forced.dck", "blockers.dck", str(SEED))),
             cls._command("throwing", ("hold", "0"), 3, ("-Ddecklab.probe.throwFirst=true",),
                          first=(cls.tmp / "throwing-classes",)),
             cls._command("off", ("hold", "0"), 3, (simjar.GAME_PATCHES_OFF, "-Xlog:os+thread=info"))],
        ]
        cls.out = {}
        marker = forge.runner._first_use_marker(cls.setup["user_dir"], cls.setup["version"])
        for wave in waves:
            threads = []
            for i, argv in enumerate(wave):
                started = threading.Event() if not marker.exists() and i == 0 else None
                t = threading.Thread(target=_play, args=(argv, cls.setup, env, cls.out, started))
                t.start()
                threads.append(t)
                if started is not None:
                    started.wait(600)       # a new Forge user folder: the first process starts alone
            for t in threads:
                t.join()
            try:
                marker.touch()
            except OSError:
                pass
        forge.runner._tidy_user_dir(cls.setup["user_dir"])

    def games(self, tag):
        """Each game's lines, without the JVM's -Xlog lines, timings masked, attackers in Forge's order."""
        text = "\n".join(line for line in self.out[tag].splitlines() if not RE_JVM_LOG.match(line))
        return [[cli.RE_TIMING.sub("?", line) for line in game] for game in cli._split_games(text)]

    def end(self, tag):
        found = re.findall(r"^PROBE\|end\|timeouts=(\d+)\|live=(-?\d+)$", self.out[tag], re.M)
        self.assertEqual(len(found), 1, self.out[tag][-2000:])
        return tuple(map(int, found[0]))

    def platform_evals(self, tag):
        """Platform "Game AI Eval" threads that ended (-Xlog:os+thread: "JavaThread exiting
        (name: "Game AI Eval", ...)"); virtual threads aren't JavaThreads and aren't logged."""
        return sum(1 for line in self.out[tag].splitlines()
                   if RE_JVM_LOG.match(line) and 'exiting (name: "Game AI Eval"' in line)

    def pool_threads(self, tag):
        """Threads of an Executors default thread factory ("pool-<n>-thread-<m>") that ended,
        from -Xlog:os+thread as platform_evals."""
        return sum(1 for line in self.out[tag].splitlines()
                   if RE_JVM_LOG.match(line) and RE_POOL_THREAD.search(line))

    def engine(self, tag):
        """The run's DLENGINE fields."""
        found = [line for line in self.out[tag].splitlines() if line.startswith(forge.logreader.ENGINE_PREFIX)]
        self.assertEqual(len(found), 1, self.out[tag][-2000:])
        return forge.logreader.engine_fields(found[0])

    def test_the_classes_are_loaded_from_forges_jar(self):
        for cls in ("forge.ai.AiController", "forge.ai.AiAttackController", "forge.ai.AiSignals"):
            found = re.search(rf"\] {re.escape(cls)} source: (.+)$", self.out["virtual"], re.M)
            self.assertIsNotNone(found, cls)
            self.assertIn(self.setup["jar"], found[1])

    def test_a_virtual_thread_unless_an_eval_still_runs(self):
        self.assertEqual(len(self.games("virtual")), 3)
        self.assertEqual(self.platform_evals("virtual"), 0)
        self.assertGreater(self.platform_evals("platform"), 10)
        self.assertEqual(self.end("virtual"), (0, 0))
        self.assertEqual(self.end("platform"), (0, 1))     # every eval counted itself up and down again

    def test_the_same_games_on_either_thread(self):
        self.assertEqual(self.games("platform"), self.games("virtual"))

    def test_the_same_seed_attacks_in_the_same_order_every_time(self):
        games = self.games("again")
        self.assertEqual(len(games), 3)
        self.assertEqual(games, self.games("virtual"))      # attackers as Forge listed them, not sorted
        several = [line for game in games for line in game
                   if line.startswith("Combat: ") and cli.RE_ATTACKERS.match(line) and " and " in line]
        self.assertGreater(len(several), 3)

    def test_ai_timeouts_are_counted(self):
        out = self.out["timeouts"]
        timeouts, live = self.end("timeouts")
        self.assertGreater(timeouts, 0)
        self.assertEqual(timeouts, out.count(forge.logreader.AI_TIMEOUT))
        self.assertEqual(live, 0)
        self.assertRegex(out, r"(?m)^PROBE\|game\|turn=\d+\|over=true$")

    def test_a_task_that_throws_leaves_the_others_forced(self):
        out = self.out["throwing"]
        self.assertEqual(len(self.games("throwing")), 3)                 # every game played to the end
        self.assertNotIn("probe: the first attacker's task throws", out)  # passed over, never printed
        self.assertNotIn("StackOverflowError", out)                      # nor the overflow
        declarations, threw_then_forced, overflowed_then_forced = [], 0, 0
        for line in out.splitlines():
            if line.startswith("PROBE|declare|"):
                declarations.append([])
            elif line.startswith(("PROBE|threw|", "PROBE|overflowed|", "PROBE|forced|")) and declarations:
                declarations[-1].append(line.split("|", 2)[1:])
        for found in declarations:
            failed = {what: [card for w, card in found if w == what] for what in ("threw", "overflowed")}
            forced = [card for what, card in found if what == "forced"]
            self.assertFalse(set(failed["threw"] + failed["overflowed"]) & set(forced), found)
            if failed["threw"] and forced:
                threw_then_forced += 1
            if failed["overflowed"] and forced:
                overflowed_then_forced += 1
        self.assertGreater(threw_then_forced, 0, "no declaration had a task throw and another attacker forced")
        self.assertGreater(overflowed_then_forced, 0,
                           "no declaration had a task overflow its stack and another attacker forced")
        self.assertEqual(self.end("throwing"), (0, 0))

    def test_game_patches_off_plays_forges_thread_pool(self):
        # The same class with -Ddecklab.gamePatches=off: Forge's own forced-attacker thread pool,
        # a new one for each attack declaration; with the switch on, the checks run on the game
        # thread. Both kinds of run also have Forge's start-up pools and a single-thread executor
        # per game (TimeLimitedCodeBlock: the game's own thread), all named "pool-<n>-thread-<m>",
        # so the off run, playing as many games of the same decks and seed, has more of them.
        self.assertEqual(len(self.games("off")), 3)
        on = max(self.pool_threads("virtual"), self.pool_threads("platform"))
        self.assertGreater(self.pool_threads("off"), on + 3)
        for tag in ("virtual", "platform"):
            with self.subTest(tag):
                self.assertEqual(self.engine(tag)["gamepatches"], "on")
        self.assertEqual(self.engine("off")["gamepatches"], "off")
        self.assertIn(ATTACK_ID, self.engine("off")["gamepatchids"].split(","))     # loaded, playing Forge's code
        self.assertEqual(self.end("off"), (0, 0))


if __name__ == "__main__":
    unittest.main()
