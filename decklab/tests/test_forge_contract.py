"""Tests for the shared pieces of simulation wave 2's contract (forge-trial/sim-wave2-contract.md):
the per-game seeds (seeds.py, and Seeds.java when a JDK is installed), a request's arguments and
a warm worker's command and "play" line (runner), DeckLabSim's DLENGINE line as LogReader reads
it, the card log's turn hook and merging two batch records, the Java sources the card-log jar
is built from (simjar), the base commit's engine.py (the key before wave 2), the command line's
commands, the pool settings, and the fake Forge's v2 games and serve mode, which the packages'
tests rely on: the serve protocol as fixtures/fake_forge.py speaks it.

The wave 2 packages own their own test files; this one is the contract's and changes only with
it. No Java is needed (the Seeds.java test runs only when a JDK is found).

Run from the repo root: python -m unittest decklab.tests.test_forge_contract
"""
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, forge
from decklab.tests import test_forge

seeds = forge.seeds
runner = forge.runner
simjar = forge.simjar

SETUP = {"java": "C:/jdk/bin/java.exe", "xmx": "1024m", "jar": "forge-gui-desktop-2.0.15-jar-with-dependencies.jar",
         "decks_dir": Path("C:/data/forge/decks"), "clock_s": 120,
         "card_log": {"ready": True, "jar": "C:/data/cardlog/decklab-sim-2.0.15-0123456789ab.jar",
                      "main": "decklab.DeckLabSim", "add_opens": ["--add-opens", "java.base/java.lang=ALL-UNNAMED"]}}
STREAM = "0123456789abcdef"
build_command = test_forge._real_build_command
serve_command = test_forge._real_serve_command


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


# ============================================================ seeds

class SeedTests(unittest.TestCase):

    def test_the_vectors(self):
        for base, stream, game, seed in seeds.TEST_VECTORS:
            self.assertEqual(seeds.game_seed(base, stream, game), seed, (base, stream, game))
        self.assertEqual(seeds.mix(0), seeds.MIX_ZERO)          # SplitMix64's published first output

    def test_the_load_seed_vectors(self):
        # Wave 3's deck-order-1 (sim-wave3-contract.md section 3.2): another stream than the game's.
        self.assertEqual(seeds.LOAD_SALT.to_bytes(8, "big"), b"loadseed")
        for base, stream, game, seed in seeds.LOAD_TEST_VECTORS:
            self.assertEqual(seeds.load_seed(base, stream, game), seed, (base, stream, game))
            self.assertEqual(seeds.load_seed(base, stream, game), seeds.game_seed(base, stream ^ seeds.LOAD_SALT, game))
            self.assertNotEqual(seeds.load_seed(base, stream, game), seeds.game_seed(base, stream, game))

    def test_a_seed_is_a_long_of_0_or_more(self):
        for game in range(500):
            seed = seeds.game_seed(1, 0xFFFF0000FFFF0000, game)
            self.assertTrue(0 <= seed < 2 ** 63)
        # Neighbouring games and bases get unrelated seeds.
        self.assertEqual(len({seeds.game_seed(base, 7, game) for base in range(20) for game in range(50)}), 1000)

    def test_the_stream_of_a_pair(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        self.assertEqual(seeds.stream_of(a, b), seeds.stream_of(b, a))
        self.assertNotEqual(seeds.stream_of(a, b), seeds.stream_of(a, c))
        self.assertTrue(0 <= seeds.stream_of(a, b) < 2 ** 64)
        self.assertEqual(seeds.parse_stream(seeds.stream_hex(seeds.stream_of(a, b))), seeds.stream_of(a, b))
        self.assertEqual(seeds.stream_hex(255), "00000000000000ff")
        for bad in ("0x0123456789abcd", "+123456789abcdef", "0123456789ABCDEF", "0123456789abcde", None, 5):
            with self.assertRaises(ValueError, msg=bad):
                seeds.parse_stream(bad)

    def test_seat_blocks(self):
        self.assertEqual(seeds.SEAT_BLOCK, 25)
        self.assertEqual([seeds.deck1_side(g) for g in (0, 24, 25, 49, 50, 799)], [0, 0, 1, 1, 0, 1])
        self.assertEqual([seeds.deck1_side(g, flip=True) for g in (0, 25)], [1, 0])
        self.assertEqual((seeds.block_of(49), seeds.block_end(49), seeds.block_end(50)), (1, 50, 75))
        self.assertIn("seat-block-25", seeds.SCHEME)

    def test_seeds_py_imports_nothing_of_deck_labs(self):
        # The fake Forge loads it on its own.
        text = Path(seeds.__file__).read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"(?m)^(?:from|import) (\S+)", text), ["hashlib", "re"])

    def test_java_gives_the_same_seeds(self):
        java = forge.install.find_java(None)
        if java is None:
            self.skipTest("no JDK found")
        args = [str(x) for base, stream, game, _ in seeds.TEST_VECTORS for x in (base, seeds.stream_hex(stream), game)]
        done = subprocess.run([str(java), str(simjar.JAVA / "decklab" / "Seeds.java"), *args], capture_output=True,
                              text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([int(line) for line in done.stdout.split()], [v[3] for v in seeds.TEST_VECTORS])
        # Seeds.loadSeed is seeds.load_seed ("load" first).
        args = [str(x) for base, stream, game, _ in seeds.LOAD_TEST_VECTORS
                for x in (base, seeds.stream_hex(stream), game)]
        done = subprocess.run([str(java), str(simjar.JAVA / "decklab" / "Seeds.java"), "load", *args],
                              capture_output=True, text=True, timeout=120,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual([int(line) for line in done.stdout.split()], [v[3] for v in seeds.LOAD_TEST_VECTORS])
        # Seeds.parseStream takes only what seeds.parse_stream takes.
        for bad in ("+123456789abcdef", "0123456789ABCDEF"):
            done = subprocess.run([str(java), str(simjar.JAVA / "decklab" / "Seeds.java"), "1", bad, "0"],
                                  capture_output=True, text=True, timeout=120,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertNotEqual(done.returncode, 0, bad)


# ============================================================ a request, a worker's command and its lines

class CommandTests(unittest.TestCase):
    """runner's real command builders (test_forge's setUpModule puts the fake Forge's in their place)."""

    def test_request_args_v1_are_todays(self):
        args = runner.request_args(SETUP, "Constructed", "a.dck", "b.dck", 25, 7)
        self.assertEqual(args, ["sim", "-D", str(SETUP["decks_dir"]), "-d", "a.dck", "b.dck", "-n", "25", "-s", "7",
                                "-f", "Constructed", "-c", "120", "-a", "Default", "Default"])
        self.assertEqual(build_command(SETUP, "Constructed", "a.dck", "b.dck", 25, 7)[-len(args):], args)

    def test_request_args_v2(self):
        args = runner.request_args(SETUP, "Commander", "a.dck", "b.dck", 10, 1, {"stream": STREAM, "first": 50})
        self.assertEqual(args[-3:], ["-dlgame", STREAM, "50"])
        off = runner.request_args(SETUP, "Commander", "a.dck", "b.dck", 10, 1,
                                  {"stream": STREAM, "first": 50, "card_log": False})
        self.assertEqual(off[-4:], ["-dlgame", STREAM, "50", "-dlnocardlog"])
        with self.assertRaises(ValueError):
            runner.request_args(SETUP, "Commander", "a.dck", "b.dck", 10, 1, {"stream": "zz", "first": 0})
        with self.assertRaises(ValueError):         # Forge reads "-s -5" as an option "-5"
            runner.request_args(SETUP, "Commander", "a.dck", "b.dck", 10, -5, {"stream": STREAM, "first": 0})
        self.assertIn("-5", runner.request_args(SETUP, "Commander", "a.dck", "b.dck", 10, -5))     # v1 as ever

    def test_build_command(self):
        argv = build_command(SETUP, "Constructed", "a.dck", "b.dck", 25, 7, {"stream": STREAM, "first": 0})
        main = argv.index("decklab.DeckLabSim")
        self.assertEqual(argv[main - 2:main], ["-cp", os.pathsep.join([SETUP["card_log"]["jar"], SETUP["jar"]])])
        self.assertEqual(argv[main + 1], "sim")
        self.assertNotIn(simjar.GAME_PATCHES_OFF, argv)
        off = build_command(dict(SETUP, game_patches=False), "Constructed", "a.dck", "b.dck", 25, 7)
        self.assertLess(off.index(simjar.GAME_PATCHES_OFF), off.index("-cp"))      # a JVM flag
        plain = dict(SETUP, card_log={"ready": False})
        argv = build_command(plain, "Constructed", "a.dck", "b.dck", 25, 7)
        self.assertEqual(argv[argv.index("sim") - 2:argv.index("sim")], ["-jar", SETUP["jar"]])
        # Plain Forge's engine has no game patches, so the fork's play Forge's own code there.
        self.assertLess(argv.index(simjar.GAME_PATCHES_OFF), argv.index("-jar"))
        self.assertEqual(argv.count(simjar.GAME_PATCHES_OFF), 1)
        self.assertEqual(build_command(dict(plain, game_patches=False), "Constructed", "a.dck", "b.dck", 25, 7)
                         .count(simjar.GAME_PATCHES_OFF), 1)
        with self.assertRaises(ValueError):         # plain Forge can't play v2
            build_command(plain, "Constructed", "a.dck", "b.dck", 25, 7, {"stream": STREAM, "first": 0})

    def test_serve_command(self):
        argv = serve_command(SETUP)
        self.assertEqual(argv[-2:], ["decklab.DeckLabSim", "serve"])
        self.assertEqual(argv[:2], [SETUP["java"], "-Xmx1024m"])
        self.assertIn("-XX:ActiveProcessorCount=2", argv)
        self.assertIn(simjar.GAME_PATCHES_OFF, serve_command(dict(SETUP, game_patches=False)))
        with self.assertRaises(ValueError):
            serve_command(dict(SETUP, card_log={"ready": False}))

    def test_request_line(self):
        args = runner.request_args(SETUP, "Constructed", "a.dck", "b.dck", 25, 7)
        line = runner.request_line("run3.chunk-12", args)
        self.assertEqual(line, "play\trun3.chunk-12\t" + "\t".join(args) + "\n")
        for bad_id in ("", "a b", "a|b", "x" * 65, "a\tb"):
            with self.assertRaises(ValueError, msg=bad_id):
                runner.request_line(bad_id, args)
        with self.assertRaises(ValueError):
            runner.request_line("r1", ["sim", "-D", "C:/my\tdecks"])


class ServeEventTests(unittest.TestCase):

    def test_the_lines(self):
        ev = runner.serve_event
        self.assertIsNone(ev("Game Result: Game 1 ended in 5 ms. Ai(1)-x has won!"))
        self.assertEqual(ev("DLSERVE|ready|1|4242|0,0,0,0,0,-2,0\n"),
                         {"what": "ready", "protocol": 1, "pid": 4242, "counters": "0,0,0,0,0,-2,0"})
        self.assertEqual(ev("DLSERVE|begin|r1.c-2"), {"what": "begin", "id": "r1.c-2"})
        self.assertEqual(ev("DLSERVE|end|r1|done|25|12345|"),
                         {"what": "end", "id": "r1", "status": "done", "games": 25, "ms": 12345, "detail": ""})
        self.assertEqual(ev("DLSERVE|end|r1|error|0|3|java.lang.Oops: a|b")["detail"], "java.lang.Oops: a|b")
        self.assertEqual(ev("DLSERVE|bye|recycle"), {"what": "bye", "why": "recycle"})
        self.assertEqual(ev("DLSERVE|bad|frob"), {"what": "bad", "text": "frob"})
        self.assertEqual(ev("DLSERVE|fail|no reset"), {"what": "fail", "why": "no reset"})
        for bad in ("DLSERVE|end|r1|maybe|1|2|", "DLSERVE|end|r1|done|x|2|", "DLSERVE|ready|1", "DLSERVE|nope",
                    "DLSERVE|begin|a b", "DLSERVE|bye|"):
            with self.assertRaises(ValueError, msg=bad):
                ev(bad)
        self.assertEqual(runner.SERVE_PROTOCOL, 1)
        self.assertEqual(runner.RECYCLE_REASONS, ("clock", "ai_timeout", "crash"))
        self.assertEqual(runner.SERVE_HEAP.fullmatch(ev("DLSERVE|end|r1|done|25|9|heap_mb=61")["detail"])[1], "61")


# ============================================================ the DLENGINE line and the card log's hooks

ENGINE = "DLENGINE|v=2|seeds=game|base=1|stream=0123456789abcdef|first=50|perf=true|cardlog=on|gamepatches=on|" \
         "gamepatchids=attack-requirements-in-order-1|autoprofile=0,1|avgcmc=3,4"


class EngineLineTests(unittest.TestCase):

    def test_the_fields(self):
        self.assertEqual(forge.logreader.engine_fields(ENGINE + "\n"),
                         {"v": "2", "seeds": "game", "base": "1", "stream": STREAM, "first": "50", "perf": "true",
                          "cardlog": "on", "gamepatches": "on", "gamepatchids": "attack-requirements-in-order-1",
                          "autoprofile": "0,1", "avgcmc": "3,4"})
        self.assertEqual(forge.logreader.engine_fields("DLENGINE|v=1|junk|=x|"), {"v": "1"})
        self.assertEqual(forge.logreader.engine_fields("DLENGINE|v=1|gamepatchids=|x=1")["gamepatchids"], "")

    def test_a_reader_keeps_it_and_splits_it_by_side(self):
        for deck1, expected in ((0, [{"autoprofile": "0", "avgcmc": "3"}, {"autoprofile": "1", "avgcmc": "4"}]),
                                (1, [{"autoprofile": "1", "avgcmc": "4"}, {"autoprofile": "0", "avgcmc": "3"}])):
            r = forge.LogReader(deck1)
            self.assertEqual(r.engine_by_side(), [{}, {}])
            self.assertIsNone(r.feed(ENGINE))
            self.assertFalse(r.header)
            self.assertEqual(r.engine["first"], "50")
            self.assertEqual(r.engine_by_side(), expected)
            # After the header it's nobody's business: a game line like any other (it never comes there).
            r.feed("Ai(1)-a [Default] vs Ai(2)-b [Default] - 1 game of Constructed seed 1")
            r.feed("DLENGINE|v=9")
            self.assertEqual(r.engine["v"], "2")

    def test_turn_lines_reach_the_card_log(self):
        r = forge.LogReader(0, card_log=True)
        r.feed("Ai(1)-a [Default] vs Ai(2)-b [Default] - 1 game of Constructed seed 1")
        with mock.patch.object(forge.cardlog.Game, "turn") as turn:
            r.feed("Turn: Turn 3 (Ai(2)-b)")
        turn.assert_called_once_with(3, 2)
        self.assertIsNone(forge.cardlog.Game().turn(1, 1))      # the base commit's does nothing


class MergeRecordTests(unittest.TestCase):

    def test_merging(self):
        a = {"v": 2, "games": 3, "bad": 1, "wins": [2, 1], "first": [1, 2],
             "rows": [{"Bolt": [1, 1, 2, 1, 0, 2, 0, 0]}, {}], "commander": [{}, {"Gisa": [1, 0, 1, 4]}]}
        b = {"v": 2, "games": 2, "bad": 0, "wins": [0, 2], "first": [1, 1],
             "rows": [{"Bolt": [1, 0, 1, 1, 0, 3, 0, 0], "Shock": [1, 0, 1, 0, 1, 0, 0, 0]}, {"Forest": [2] * 8}],
             "commander": [{}, {}]}
        merged = forge.cardlog.merge_record(json.loads(json.dumps(a)), b)
        self.assertEqual(merged, {"v": 2, "games": 5, "bad": 1, "wins": [2, 3], "first": [2, 3],
                                  "rows": [{"Bolt": [2, 1, 3, 2, 0, 5, 0, 0], "Shock": [1, 0, 1, 0, 1, 0, 0, 0]},
                                           {"Forest": [2] * 8}],
                                  "commander": [{}, {"Gisa": [1, 0, 1, 4]}]})
        merged["rows"][1]["Forest"][0] = 99
        self.assertEqual(b["rows"][1]["Forest"][0], 2)          # copied, not shared
        with self.assertRaises(ValueError):
            forge.cardlog.merge_record(dict(a, v=3), b)
        with self.assertRaises(ValueError):
            forge.cardlog.merge_record(json.loads(json.dumps(a)), dict(b, rows=[{"Bolt": [1] * 10}, {}]))


# ============================================================ the jar's sources

class SourceTests(unittest.TestCase):

    def test_every_deck_lab_source_is_built_and_hashed(self):
        sources = simjar.deck_lab_sources()
        self.assertEqual(sources[0], simjar.SOURCE)
        names = {p.name for p in sources}
        self.assertTrue({"DeckLabSim.java", "DeckLabServe.java", "GameLoop.java", "Request.java", "Seeds.java",
                         "WarmState.java"} <= names)
        self.assertNotIn("Signals.java", names)     # forge.ai.AiSignals in Deck Lab's fork of Forge
        # Each class the jar must hold has its source (an inner class's is its outer class's).
        for name in simjar.SIM_CLASSES:
            outer = name.split("/")[-1].split("$")[0].removesuffix(".class") + ".java"
            self.assertIn(outer, names, name)
        self.assertIn(f'FORGE_PATCH_LIST = "{simjar.FORGE_PATCH_LIST}"',
                      (simjar.JAVA / "decklab" / "GameLoop.java").read_text(encoding="utf-8"))

    def test_only_the_game_changing_patches_are_named(self):
        patches = {"forge/ai/A.class": "a-1", "forge/ai/B.class": None, "forge/game/C.class": "c-1"}
        self.assertEqual(simjar.game_patch_ids(patches), {"forge/ai/A.class": "a-1", "forge/game/C.class": "c-1"})
        self.assertEqual(simjar.game_patch_ids({"forge/ai/B.class": None}), {})
        self.assertEqual(simjar.game_patch_ids({}), {})
        stat = mock.Mock(st_size=1, st_mtime_ns=2)
        stamp = simjar._stamp("javac", "forge.jar", stat, "s" * 64, patches)
        self.assertEqual(stamp["patches"], sorted(patches))
        self.assertEqual(stamp["game_patches"], {"forge/ai/A.class": "a-1", "forge/game/C.class": "c-1"})
        other = simjar._stamp("javac", "forge.jar", stat, "s" * 64, dict(patches, **{"forge/game/C.class": "c-2"}))
        self.assertNotEqual(simjar.jar_file("2.0.15", stamp), simjar.jar_file("2.0.15", other))

    def test_an_edit_to_any_source_changes_the_hash(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "DeckLabSim.java").write_text("class DeckLabSim {}\n", encoding="utf-8")
        with mock.patch.object(simjar, "SOURCE", tmp / "DeckLabSim.java"):
            alone = simjar.source_sha256()
            self.assertEqual(alone, simjar.source_sha256(b"class DeckLabSim {}\n"))     # as before wave 2
            (tmp / "GameLoop.java").write_text("class GameLoop {}\n", encoding="utf-8")
            two = simjar.source_sha256()
            self.assertNotEqual(two, alone)
            (tmp / "GameLoop.java").write_text("class GameLoop { }\n", encoding="utf-8")
            self.assertNotEqual(simjar.source_sha256(), two)
            (tmp / "GameLoop.java").write_text("class GameLoop {}\r\n", encoding="utf-8", newline="")
            self.assertEqual(simjar.source_sha256(), two)       # CRLF is the same source


# ============================================================ what the checks mask

class MaskTests(unittest.TestCase):

    def test_games_text_masks_frames_and_ordinals(self):
        header = "Ai(1)-a [Default] vs Ai(2)-b [Default] - 2 games of Constructed seed 1"
        plain = "\n".join([header, "Turn: Turn 1 (Ai(1)-a)", "java.util.concurrent.ExecutionException: boom",
                           "\tat forge.ai.AiController.chooseSpellAbilityToPlayFromList(AiController.java:1686)",
                           "\t... 12 more", "Game Result: Game 1 ended in 801 ms. Ai(1)-a has won!"])
        logged = "\n".join(["DLENGINE|v=2|seeds=game", header, "Turn: Turn 1 (Ai(1)-a)",
                            "java.util.concurrent.ExecutionException: boom",
                            "\tat java.base/java.lang.VirtualThread.run(VirtualThread.java:466)",
                            "\tat forge.ai.AiController.chooseSpellAbilityToPlayFromList(AiController.java:1699)",
                            "Information: DL|log|1", "Game Result: Game 7 ended in 12 ms. Ai(1)-a has won!"])
        self.assertEqual(forge.cli._games_text(plain), forge.cli._games_text(logged))
        self.assertEqual(forge.cli._games_text(logged)[0],
                         ["Turn: Turn 1 (Ai(1)-a)", "java.util.concurrent.ExecutionException: boom",
                          "Game Result: Game ? ended in ? ms. Ai(1)-a has won!"])
        self.assertIsNone(forge.cli._compare(plain, logged))
        # The exception's own line still counts.
        self.assertIsNotNone(forge.cli._compare(plain, logged.replace("boom", "bang")))


# ============================================================ the base commit's commands and settings

class CommandLineTests(unittest.TestCase):

    def test_the_commands(self):
        self.assertEqual(list(forge.cli.COMMANDS), ["status", "audit", "play", "list", "cards", "cardlog-check",
                                                    "slots", "replay", "pool", "serve-check", "field", "variant",
                                                    "experiment", "pilots", "overrides", "staged-move", "soak-probe",
                                                    "engine-check", "decisions", "upgrade-check"])
        # Each wave 2 command is tested by its owner: replay by EP's test_forge_replay, pool by PP's
        # test_forge_pool, serve-check by PJ's test_forge_servecheck.
        # upgrade-check (E11-S15) by test_forge_upgrade_check.

    def test_pool_settings(self):
        self.assertEqual((config.DEFAULTS["forge_pool_idle_s"], config.DEFAULTS["forge_pin"]), (900, True))

    def test_the_pool_outside_the_server(self):
        self.assertIsNone(forge.pool.server_pool())
        self.assertIsNone(forge.pool.status())
        with forge.pool.session(local=True) as s:
            self.assertIsInstance(s, forge.pool.Session)
        self.assertIsNone(forge.servecheck.warm_leg(None, None, None, None, []))
        self.assertFalse(forge.cores.pin(os.getpid(), 0))      # Deck Lab never pins its own process
        masks = forge.cores.core_masks()
        self.assertEqual(forge.cores.mask_for(0), masks[0] if masks else None)


# ============================================================ the fake Forge's v2 games and serve mode

class FakeCase(unittest.TestCase):
    """The fake Forge as a process, on two of test_forge's lists."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name, text in (("green", test_forge.GREEN), ("red", test_forge.RED)):
            e = test_forge.entry(text, f"casual/{name}")
            (cls.tmp / f"{name}.dck").write_text(e["dck"], encoding="utf-8")
        cls.setup = {"decks_dir": cls.tmp, "clock_s": 120, "card_log": {"ready": True}}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self, modes=""):
        env = dict(os.environ, FAKE_FORGE=modes, APPDATA=str(self.tmp))
        env.pop("FAKE_FORGE_LOG", None)
        return env

    def args(self, games, first, seed=1, d1="green.dck", d2="red.dck"):
        return runner.request_args(self.setup, "Constructed", d1, d2, games, seed, {"stream": STREAM, "first": first})

    def sim(self, args, modes=""):
        argv = [sys.executable, str(test_forge.FAKE), *args, "--card-log"]
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=self.env(modes),
                              timeout=60).stdout.splitlines()

    @staticmethod
    def games(lines, deck1=0):
        r = forge.LogReader(deck1, card_log=True)
        for line in lines:
            r.feed(line)
        return r


class FakeV2Tests(FakeCase):

    def test_a_game_is_the_same_in_any_chunk(self):
        whole = self.games(self.sim(self.args(10, 50)))
        parts = self.games(self.sim(self.args(4, 50))).games + self.games(self.sim(self.args(6, 54))).games
        self.assertEqual(whole.games, parts)
        self.assertEqual(len(whole.games), 10)
        self.assertEqual(whole.cards["bad"], 0)
        self.assertEqual(whole.engine["first"], "50")
        self.assertEqual(whole.engine["stream"], STREAM)
        # Each game has its own coin flip: the loser doesn't always start the next.
        starts = self.games(self.sim(self.args(25, 0))).games
        self.assertTrue(any(g["w"] is not None and nxt["first"] == g["w"] for g, nxt in zip(starts, starts[1:])))

    def test_failure_modes_name_the_results_game(self):
        lines = self.sim(self.args(5, 50), modes="timeout#52")
        r = self.games(lines)
        self.assertEqual([g["r"] for g in r.games], ["win", "win", "timeout", "win", "win"])

    def test_the_engine_line(self):
        lines = self.sim(self.args(1, 0))
        header = next(i for i, line in enumerate(lines) if line.startswith("Ai(1)-"))
        engine_line = next(i for i, line in enumerate(lines) if line.startswith("DLENGINE|"))
        self.assertLess(engine_line, header)
        self.assertIn("perf=false", lines[engine_line])
        prefs = self.tmp / "Forge" / "preferences"
        prefs.mkdir(parents=True, exist_ok=True)
        (prefs / "forge.preferences").write_text("PERFORMANCE_MODE=true\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.tmp / "Forge", ignore_errors=True)
        self.assertTrue(any(line.startswith("DLENGINE|") and "perf=true" in line for line in self.sim(self.args(1, 0))))
        off = self.sim(self.args(1, 0)[:-3] + ["-dlgame", STREAM, "0", "-dlnocardlog"])
        self.assertFalse(any("DL|" in line for line in off))
        self.assertTrue(any(line.startswith("DLENGINE|") and "cardlog=off" in line for line in off))

    def engine(self, args, modes="", extra=()):
        argv = [sys.executable, str(test_forge.FAKE), *args, "--card-log", *extra]
        lines = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=self.env(modes),
                               timeout=60).stdout.splitlines()
        return forge.logreader.engine_fields(next(line for line in lines if line.startswith("DLENGINE|")))

    def test_the_engine_line_names_the_game_patches_and_forges_auto_profile(self):
        fields = self.engine(self.args(1, 0))
        self.assertEqual((fields["gamepatchids"], fields["autoprofile"], fields["avgcmc"]), ("", "0,0", "2,2"))
        fields = self.engine(self.args(1, 0), "avgcmc=4,3", ["--game-patch-ids=a-1,b-2"])
        self.assertEqual((fields["gamepatchids"], fields["autoprofile"], fields["avgcmc"]), ("a-1,b-2", "1,0", "4,3"))
        control = self.tmp / "control.dck"
        control.write_text((self.tmp / "green.dck").read_text(encoding="utf-8").replace(
            "Name=", "Name=Green Control ", 1), encoding="utf-8")
        self.addCleanup(control.unlink)
        self.assertEqual(self.engine(self.args(1, 0, d2="control.dck"))["autoprofile"], "0,1")
        # test_forge's fake commands pass the card log's game patches on.
        setup = dict(self.setup, card_log=dict(test_forge.CARD_LOG, game_patches=["a-1"]))
        self.assertIn("--game-patch-ids=a-1", test_forge.fake_command(setup, "Constructed", "a", "b", 1, 1))
        self.assertIn("--game-patch-ids=a-1", test_forge.fake_serve_command(setup))


class FakeWave3Tests(FakeCase):
    """Wave 3's additions to the fake (sim-wave3-contract.md section 19.1)."""

    def run_fake(self, args, modes="", extra=()):
        argv = [sys.executable, str(test_forge.FAKE), *args, "--card-log", *extra]
        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=self.env(modes),
                              timeout=60)

    def echo(self, args, modes="", extra=()):
        lines = self.run_fake(args, modes, extra).stdout.splitlines()
        return forge.logreader.engine_fields(next(line for line in lines if line.startswith("DLENGINE|")))

    def test_the_engine_lines_wave_3_fields(self):
        fields = self.echo(self.args(1, 0))
        self.assertEqual({k: fields[k] for k in ("deckorder", "loadseed", "ai", "pilots", "aiprofiles", "overrides")},
                         {"deckorder": "0,0", "loadseed": "0", "ai": "Default,Default", "pilots": "-,-",
                          "aiprofiles": "forge", "overrides": "none"})
        on = self.echo(self.args(1, 0), extra=["--game-patch-ids=attack-requirements-in-order-1,deck-order-1"])
        self.assertEqual((on["deckorder"], on["loadseed"]), ("1,1", "1"))
        off = self.echo(self.args(1, 0), extra=["--game-patch-ids=deck-order-1", "-Ddecklab.gamePatches=off"])
        self.assertEqual((off["deckorder"], off["loadseed"], off["gamepatches"]), ("0,0", "0", "off"))
        v1 = runner.request_args(self.setup, "Constructed", "green.dck", "red.dck", 1, 1)
        self.assertEqual(self.echo(v1, extra=["--game-patch-ids=deck-order-1"])["deckorder"], "0,0")
        # LogReader splits the new seat fields by side.
        reader = forge.LogReader(1, card_log=True)
        reader.feed("DLENGINE|v=2|deckorder=1,0|ai=Reckless,Default|pilots=team-pump-1,-|autoprofile=0,1|avgcmc=2,3")
        self.assertEqual(reader.engine_by_side()[0]["ai"], "Default")
        self.assertEqual(reader.engine_by_side()[1], {"autoprofile": "0", "avgcmc": "2", "deckorder": "1",
                                                      "ai": "Reckless", "pilots": "team-pump-1"})

    def test_pilots(self):
        args = self.args(1, 0) + ["-dlpilot", "team-pump-1", "-"]
        refused = self.run_fake(args).stdout
        self.assertIn("Error: -dlpilot: no switch called team-pump-1", refused)
        self.assertNotIn("Ai(1)-", refused)
        fields = self.echo(args, extra=["--pilot-switches=aisim-hybrid-1,team-pump-1"])
        self.assertEqual(fields["pilots"], "team-pump-1,-")
        both = self.args(1, 0) + ["-dlpilot", "team-pump-1+aisim-hybrid-1", "aisim-hybrid-1"]
        self.assertEqual(self.echo(both, extra=["--pilot-switches=aisim-hybrid-1,team-pump-1"])["pilots"],
                         "team-pump-1+aisim-hybrid-1,aisim-hybrid-1")
        off = self.run_fake(args, extra=["--pilot-switches=team-pump-1", "--game-patches-off"]).stdout
        self.assertIn("Error: team-pump-1 needs game patches on", off)
        v1 = runner.request_args(self.setup, "Constructed", "green.dck", "red.dck", 1, 1) + ["-dlpilot", "-", "-"]
        self.assertIn("Error: -dlpilot needs -dlgame", self.run_fake(v1, extra=["--pilot-switches=team-pump-1"]).stdout)
        self.assertIn("Error: -dlpilot needs", self.run_fake(self.args(1, 0) + ["-dlpilot", "-"]).stdout)

    def test_ai_profiles(self):
        args = runner.request_args(self.setup, "Constructed", "green.dck", "red.dck", 1, 1,
                                   {"stream": STREAM, "first": 0})
        args[args.index("-a") + 1] = "DLAggro"
        unknown = self.run_fake(args).stdout
        self.assertIn("Unknown AI profile - DLAggro. Available profiles: Cautious, Default, Experimental, Reckless",
                      unknown)
        self.assertNotIn("Ai(1)-", unknown)
        folder = self.tmp / "profiles"
        folder.mkdir(exist_ok=True)
        (folder / "DLAggro.ai").write_text("AICardMemory=true\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        lines = self.run_fake(args, extra=[f"-Ddecklab.aiprofiles={folder}"]).stdout.splitlines()
        self.assertTrue(any(line.startswith("Ai(1)-") and "[DLAggro] vs " in line for line in lines))
        fields = forge.logreader.engine_fields(next(line for line in lines if line.startswith("DLENGINE|")))
        self.assertEqual((fields["ai"], fields["aiprofiles"]), ("DLAggro,Default", "dl"))
        gone = self.run_fake(args, extra=[f"-Ddecklab.aiprofiles={self.tmp / 'nowhere'}"])
        self.assertEqual(gone.returncode, 3)
        self.assertIn("Error: the AI profile folder", gone.stdout)
        serve = subprocess.run([sys.executable, str(test_forge.FAKE), "serve",
                                f"-Ddecklab.aiprofiles={self.tmp / 'nowhere'}"], input="", capture_output=True,
                               text=True, encoding="utf-8", env=self.env(), timeout=60)
        self.assertEqual(serve.returncode, 3)
        self.assertIn("DLSERVE|fail|the AI profile folder", serve.stdout)

    def test_the_overrides_hash_is_the_start_ups(self):
        cards = self.tmp / "Forge" / "custom" / "cards"
        cards.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.tmp / "Forge", ignore_errors=True)
        (cards / "fiery_annihilation.txt").write_bytes(b"Name:Fiery Annihilation\r\nManaCost:2 R\r\n")
        want = forge.overrides.deployed_hash(self.tmp)
        self.assertEqual(want, forge.engine._overrides(self.tmp))
        self.assertNotIn(want, ("none", "unreadable"))
        self.assertEqual(forge.overrides.deployed_index(self.tmp),     # (E3's ensure_deployed now writes the folder)
                         {"Fiery Annihilation": forge.engine._file_sha(cards / "fiery_annihilation.txt")})
        self.assertEqual(self.echo(self.args(1, 0))["overrides"], want)
        # A serve worker keeps the hash it started with.
        proc = subprocess.Popen([sys.executable, str(test_forge.FAKE), "serve"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                bufsize=1, env=self.env())
        try:
            self.assertTrue(proc.stdout.readline().startswith("Error handling"))
            while not proc.stdout.readline().startswith("DLSERVE|ready|"):
                pass
            (cards / "another.txt").write_text("Name:Another\n", encoding="utf-8")
            proc.stdin.write(runner.request_line("r1", self.args(1, 0)))
            proc.stdin.flush()
            line = proc.stdout.readline()
            while not line.startswith("DLENGINE|"):
                line = proc.stdout.readline()
            self.assertEqual(forge.logreader.engine_fields(line)["overrides"], want)
            proc.stdin.write("quit\n")
            proc.stdin.flush()
            self.assertIn("DLSERVE|bye|quit", proc.stdout.read())     # the rest, so the worker can write it
            self.assertEqual(proc.wait(timeout=30), 0)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.stdout.close()
            proc.stdin.close()

    def test_cardwins_and_slowcard(self):
        plain = self.games(self.sim(self.args(25, 0))).games
        wins = self.games(self.sim(self.args(25, 0), modes="cardwins=Overrun")).games
        # Only green (side 0, seat 1 here) holds Overrun: it wins more, and never loses a game it
        # won without the mode.
        self.assertGreater(sum(g["w"] == 0 for g in wins), sum(g["w"] == 0 for g in plain))
        self.assertFalse([i for i, (a, b) in enumerate(zip(plain, wins)) if a["w"] == 0 and b["w"] != 0])
        slow = self.games(self.sim(self.args(3, 0), modes="slowcard=Lightning Bolt@40")).games
        self.assertEqual([g["ms"] for g in slow], [g["ms"] + 40 for g in plain[:3]])
        self.assertEqual([g["ms"] for g in self.games(self.sim(self.args(3, 0), modes="slowcard=Nothing@40")).games],
                         [g["ms"] for g in plain[:3]])


class Wave3BaseTests(unittest.TestCase):
    """The base commit's frozen names (sim-wave3-contract.md section 21)."""

    def test_the_stubs_are_there(self):
        for name in ("assess_estimate", "assess_next", "decided_share", "last_look", "look", "ahead_next",
                     "anytime_range", "paired_games", "paired_diff", "paired_field", "paired_verdict", "paired_look",
                     "field_row", "field_average", "bt_component", "bt_fit", "bt_predict", "bt_rating",
                     "residual_flags", "apt_pick", "spearman"):
            self.assertTrue(callable(getattr(forge.seqstats, name)), name)
        self.assertEqual(forge.seqstats.HP_LOOKS, (400, 800, 1600, 3200))
        self.assertEqual(forge.seqstats.EQUIV, forge.views.ABOUT_EVEN)
        self.assertIsNone(forge.adaptive.last_summary({}))
        self.assertIsNone(forge.adaptive.lead_from_summary(None))
        self.assertIsNone(forge.estimate.minutes([]))
        self.assertEqual(forge.pilots.pilot_for("casual/x", "target"), {"profile": "Default", "switches": []})
        self.assertTrue(callable(forge.overrides.user_dir_for))     # E3 built it (test_forge_overrides)
        self.assertEqual(forge.runner.RUN_FEATURES, frozenset(("numbers", "seeds", "key", "kind", "extra",
                                                               "override_sets", "log_dir")))     # R built them
        self.assertEqual((config.DEFAULTS["forge_field_inflight"], config.DEFAULTS["forge_variant_margin"],
                          config.DEFAULTS["forge_variant_margin_one"]), (4, 0.02, 0.03))
        self.assertEqual(forge.logreader.SEAT_FIELDS, ("autoprofile", "avgcmc", "deckorder", "ai", "pilots"))

    def test_runs_new_keywords_wait_for_r(self):
        for keyword in ("numbers", "seeds", "key", "kind", "extra", "override_sets", "log_dir"):
            self.assertIn(keyword, forge.runner.RUN_FEATURES)       # R built them (its merge)
        with self.assertRaises(ValueError):             # E3 built pilots=: [{}, {}] isn't two pilots
            runner.request_args(SETUP, "Constructed", "a.dck", "b.dck", 1, 1, pilots=[{}, {}])

    def test_the_sets_and_the_simulation_file(self):
        sets = json.loads((forge.overrides.SETS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(sets["sets"]["fiery"]["status"], "adopted")     # the owner's decision of 2026-10-03
        self.assertEqual(list(sets["sets"]), ["fiery", "etb", "etb-flagged", "tgt", "tgt-gift", "remove", "flash",
                                              "hints", "etb-tfp", "etb-tfp-jailer", "cmdr-hints"])
        simulation = json.loads(forge.pilots.SIMULATION_FILE.read_text(encoding="utf-8"))
        self.assertEqual(simulation["pilots"]["lists"],       # the owner's decision of 2026-10-21 (AI round 1)
                         {"casual/the-free-peoples": {"profile": "Default", "switches": ["etb-harmless-1"]}})
        self.assertEqual(simulation["field"], {fmt: {"add": [], "remove": []} for fmt in ("Constructed", "Commander")})


class FakeServeTests(FakeCase):
    """The serve protocol (the contract's "Serve protocol"), as the fake speaks it."""

    def start(self, modes=""):
        proc = subprocess.Popen([sys.executable, str(test_forge.FAKE), "serve"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                bufsize=1, env=self.env(modes))
        self.addCleanup(self.stop, proc)
        lines = queue.Queue()

        def read():
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        proc.lines = lines
        return proc

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)
        for f in (proc.stdin, proc.stdout):
            try:
                f.close()
            except OSError:
                pass

    @staticmethod
    def until(proc, prefix, timeout=30):
        got = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                line = proc.lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                return got + [None]
            got.append(line)
            if line.startswith(prefix):
                return got
        raise AssertionError(f"no {prefix!r} in {got[-10:]}")

    @staticmethod
    def send(proc, text):
        proc.stdin.write(text)
        proc.stdin.flush()

    def test_requests_play_the_same_games_as_sim(self):
        proc = self.start()
        ready = self.until(proc, "DLSERVE|ready|")[-1]
        self.assertEqual(runner.serve_event(ready)["protocol"], runner.SERVE_PROTOCOL)
        self.send(proc, runner.request_line("r1", self.args(4, 50)))
        out = self.until(proc, "DLSERVE|end|r1|")
        self.assertEqual(out[0], "DLSERVE|begin|r1")
        self.assertRegex(out[-1], r"^DLSERVE\|end\|r1\|done\|4\|\d+\|heap_mb=\d+$")
        self.send(proc, runner.request_line("r2", self.args(6, 54)))
        out2 = self.until(proc, "DLSERVE|end|r2|")
        whole = self.games(self.sim(self.args(10, 50))).games
        self.assertEqual(self.games(out).games + self.games(out2).games, whole)
        self.send(proc, "nonsense\n")
        self.assertEqual(self.until(proc, "DLSERVE|bad|")[-1], "DLSERVE|bad|nonsense")
        self.send(proc, "quit\n")
        self.assertEqual(self.until(proc, "DLSERVE|bye|")[-1], "DLSERVE|bye|quit")
        self.assertEqual(proc.wait(10), 0)

    def test_cancel_stops_at_a_game_boundary(self):
        proc = self.start(modes="delay=0.3")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(20, 0)))
        got = self.until(proc, "Game Result:")
        self.send(proc, "cancel\tr1\n")
        got += self.until(proc, "DLSERVE|end|r1|")
        status, games = got[-1].split("|")[3:5]
        self.assertEqual(status, "cancelled")
        self.assertLess(int(games), 20)
        self.assertEqual(int(games), sum(1 for line in got if line.startswith("Game Result:")))
        self.send(proc, "cancel\tr9\n")             # nothing playing by that id: nothing happens
        proc.stdin.close()                          # the end of stdin ends it
        self.assertEqual(self.until(proc, "DLSERVE|bye|")[-1], "DLSERVE|bye|eof")

    def test_a_clock_stop_recycles_the_worker(self):
        proc = self.start(modes="timeout#2")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        out = self.until(proc, "DLSERVE|bye|")
        self.assertRegex(out[-2], r"^DLSERVE\|end\|r1\|recycle\|3\|\d+\|clock$")     # games 0, 1 and 2
        self.assertEqual(out[-1], "DLSERVE|bye|recycle")
        self.assertEqual(proc.wait(10), 0)

    def test_a_worker_that_dies_or_cant_start(self):
        proc = self.start(modes="crash#3")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        out = self.until(proc, "never printed")
        self.assertIsNone(out[-1])
        self.assertFalse(any(line and line.startswith("DLSERVE|end|") for line in out[:-1]))
        self.assertEqual(proc.wait(10), 1)
        proc = self.start(modes="servefail")
        self.assertRegex(self.until(proc, "DLSERVE|fail|")[-1], r"^DLSERVE\|fail\|.+")
        self.assertEqual(proc.wait(10), 3)

    def test_a_request_that_cant_start(self):
        proc = self.start(modes="noload")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        self.assertRegex(self.until(proc, "DLSERVE|end|r1|")[-1], r"^DLSERVE\|end\|r1\|error\|0\|\d+\|Could not load")
        self.send(proc, "quit\n")
        self.assertEqual(proc.wait(10), 0)
        proc = self.start(modes="badargs")         # arguments it can't read: an error, and it plays on
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        self.assertRegex(self.until(proc, "DLSERVE|end|r1|")[-1], r"^DLSERVE\|end\|r1\|error\|0\|\d+\|the request's")
        self.send(proc, "quit\n")
        self.assertEqual(self.until(proc, "DLSERVE|bye|")[-1], "DLSERVE|bye|quit")
        self.assertEqual(proc.wait(10), 0)

    def test_a_game_that_leaves_something_behind_recycles_the_worker(self):
        for mode, why in (("aitimeout#1", "ai_timeout"), ("exception#1", "crash")):
            proc = self.start(modes=mode)
            self.until(proc, "DLSERVE|ready|")
            self.send(proc, runner.request_line("r1", self.args(5, 0)))
            out = self.until(proc, "DLSERVE|bye|")
            self.assertRegex(out[-2], rf"^DLSERVE\|end\|r1\|recycle\|2\|\d+\|{why}$")     # games 0 and 1
            self.assertEqual(out[-1], "DLSERVE|bye|recycle")
            self.assertEqual(proc.wait(10), 0)
        # An AI timeout Java doesn't see (its AiController copy didn't fit): it plays on.
        proc = self.start(modes="aitimeoutunseen#1")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        out = self.until(proc, "DLSERVE|end|r1|")
        self.assertRegex(out[-1], r"^DLSERVE\|end\|r1\|done\|5\|")
        self.assertEqual(self.games(out).games[1]["ai_to"], 2)

    def test_a_java_error_that_escapes_ends_the_worker(self):
        proc = self.start(modes="throw#2")
        self.until(proc, "DLSERVE|ready|")
        self.send(proc, runner.request_line("r1", self.args(5, 0)))
        out = self.until(proc, "DLSERVE|bye|")
        self.assertRegex(out[-2], r"^DLSERVE\|end\|r1\|error\|2\|\d+\|java\.lang\.IllegalStateException")
        self.assertEqual(out[-1], "DLSERVE|bye|error")
        self.assertEqual(proc.wait(10), 1)


if __name__ == "__main__":
    unittest.main()
