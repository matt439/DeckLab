"""Tests for engine-check (AI round 1, the ai-r1 contract's section 3.7): a new build of the fork
against the installed one, played with the fake Forge (fixtures/fake_forge.py) in two made-up
install folders. The new install's games are changed where a test needs a difference: its Forge
command runs through a small filter (FILTER) that edits a line of its output, or sets FAKE_FORGE.
No real Forge runs. The shared fixtures, setUpModule and tearDownModule stay in test_forge.

Run from the repo root: python -m unittest decklab.tests.test_forge_engine_check
"""
import json
import sys
from unittest import mock

from decklab.lib import decks, forge
from decklab.tests import test_forge
from decklab.tests.test_forge import CARD_LOG, GREEN, RED, ForgeCase, make_forge, sections

SWITCHES = ["aisim-hybrid-1", "etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1", "team-pump-1"]
# Runs the fake Forge (the rest of argv) with its stdout passed on, after the mode: "env=<FAKE_FORGE>" sets
# that first; "line=<game>" appends " (changed)" to the first "Add To Stack" line of that game (from 1), which
# changes a line but not who won, who started or how long the game took.
FILTER = '''import os, subprocess, sys
mode, argv = sys.argv[1], sys.argv[2:]
if mode.startswith("env="):
    os.environ["FAKE_FORGE"] = mode[4:]
    sys.exit(subprocess.call(argv))
target, game, done = int(mode[5:]), 1, False
proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, encoding="utf-8")
for line in proc.stdout:
    if not done and game == target and line.startswith("Add To Stack:"):
        line, done = line.rstrip("\\n") + " (changed)\\n", True
    if line.startswith("Game Result:"):
        game += 1
    sys.stdout.write(line)
sys.stdout.flush()
sys.exit(proc.wait())
'''


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class EngineCheckTests(ForgeCase):

    run_main = test_forge.CommandLineTests.run_main

    def setUp(self):
        super().setUp()
        self.old, self.new = self.tmp / "old", self.tmp / "new"
        make_forge(self.old)
        make_forge(self.new)
        self.settings["forge_dir"] = str(self.new)
        self.filter = self.tmp / "filter.py"
        self.filter.write_text(FILTER, encoding="utf-8")
        self.change = None              # the filter's mode for the new install's runs
        self.lacking = {}               # {install folder: switches its card log lacks}
        self.patches = {}               # {install folder: game patches its card log has}
        self.runs = []
        summaries = [{"id": "casual/green", "title": "Green", "kind": "casual", "versions": ["target", "owned"]},
                     {"id": "casual/red", "title": "Red", "kind": "casual", "versions": ["target"]}]
        lists = {"casual/green": GREEN, "casual/red": RED}
        for p in (mock.patch.object(decks, "list_decks", return_value=summaries),
                  mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: sections(lists[deck_id])),
                  mock.patch.object(forge.simjar, "card_log", side_effect=self.card_log),
                  mock.patch.object(forge.runner, "build_command", self.command)):
            p.start()
            self.addCleanup(p.stop)

    def card_log(self, java, forge_dir, jar, version, checking=False):
        self.assertTrue(checking)
        lacking = self.lacking.get(str(forge_dir), [])
        found = dict(CARD_LOG, pilot_switches=[s for s in SWITCHES if s not in lacking])
        if str(forge_dir) in self.patches:
            found["game_patches"] = self.patches[str(forge_dir)]
        return found

    def command(self, setup, fmt, deck1, deck2, games, seed, v2=None, pilots=None):
        self.runs.append({"forge_dir": str(setup["forge_dir"]), "fmt": fmt, "games": games, "v2": v2, "pilots": pilots,
                          "game_patches": setup.get("game_patches")})
        argv = test_forge.fake_command(setup, fmt, deck1, deck2, games, seed, v2, pilots)
        if self.change and str(setup["forge_dir"]) == str(self.new):
            argv = [sys.executable, str(self.filter), self.change, *argv]
        return argv

    def check(self, *argv):
        return self.run_main("engine-check", "--old", str(self.old), "--games", "3", "--commander-games", "1", *argv)

    def test_identical_builds(self):
        summary = self.tmp / "summary.json"
        code, out, err = self.check("--json", str(summary))
        self.assertEqual(code, 0, err)
        self.assertIn(f"old: {self.old}: build 2.0.15, engine release 2.0.15, game patches none", out)
        self.assertIn("cardlog-check-a v cardlog-check-b (Constructed): 3 of 3 games identical", out)
        self.assertIn("(Commander): 1 of 1 games identical", out)
        self.assertIn(forge.cli_engine.SAME_KEY, out)
        found = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual((found["verdict"], found["same_key"], found["old"]["forge"], len(found["pairs"])),
                         ("identical", True, "2.0.15", 2))
        self.assertEqual(set(found["pairs"][0]), {"decks", "format", "games", "identical", "lines", "first_difference",
                                                  "verdict"})
        # Each install played each pair once, card log on, game patches on, the v2 request from game 0.
        self.assertEqual(sorted((r["forge_dir"], r["fmt"], r["games"], r["v2"]["first"], r["game_patches"])
                                for r in self.runs),
                         sorted((str(d), fmt, n, 0, True) for d in (self.old, self.new)
                                for fmt, n in (("Constructed", 3), ("Commander", 1))))
        self.assertTrue(all(r["pilots"] is None for r in self.runs))

    def test_a_changed_constructed_line_fails_and_is_named(self):
        self.change = "line=2"
        code, out, err = self.check("--commander-games", "0")
        self.assertEqual(code, 1, err)
        self.assertIn("2 of 3 games identical", out)
        self.assertIn("different: game 2, line", out)
        self.assertIn("(changed)", out)
        self.assertIn(forge.cli_engine.DONT_INSTALL, out)        # the same key, yet other games

    def test_commander_games_that_end_the_same_cant_tell(self):
        self.change = "line=1"
        code, out, err = self.check("--games", "0")
        self.assertEqual(code, 3, err)
        self.assertIn("0 of 1 games identical", out)
        self.assertIn("can't tell: game 1", out)

    def test_a_game_that_hit_a_time_limit_cant_tell(self):
        self.change = "env=timeout#1"
        code, out, err = self.check("--commander-games", "0")
        self.assertEqual(code, 3, err)
        self.assertIn("can't tell", out)

    def test_different_keys_are_reported(self):
        (self.new / forge.install.BUILD_FILE).write_text(
            "build=2.0.15-decklab-bbb\nbase=forge-2.0.15\nres_sha256=" + "a" * 64 + "\n", encoding="utf-8")
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertIn("engine release 2.0.15+res.aaaaaaaaaaaa", out)
        self.assertIn("Different engine key (forge 2.0.15 -> 2.0.15+res.aaaaaaaaaaaa): saved results will be an "
                      "earlier engine.", out)
        self.assertNotIn(forge.cli_engine.DONT_INSTALL, out)

    def test_the_same_install_is_the_noise_floor(self):
        code, out, err = self.run_main("engine-check", "--old", str(self.new), "--new", str(self.new), "--games", "2",
                                       "--commander-games", "0")
        self.assertEqual(code, 0, err)
        self.assertIn(forge.cli_engine.SAME_INSTALL, out)
        self.assertNotIn(forge.cli_engine.SAME_KEY, out)
        self.assertEqual(len(self.runs), 2)                     # played twice all the same

    def test_switches(self):
        code, out, err = self.check("--switch", "etb-harmless-1", "--games", "2", "--commander-games", "0")
        self.assertEqual(code, 0, err)
        self.assertEqual({json.dumps(r["pilots"]) for r in self.runs},
                         {json.dumps([{"profile": "Default", "switches": ["etb-harmless-1"]}] * 2)})
        # A switch either install lacks, or any with game patches off: nothing plays.
        self.runs.clear()
        self.lacking[str(self.old)] = ["etb-harmless-1"]
        code, _, err = self.check("--switch", "etb-harmless-1")
        self.assertEqual(code, 2)
        self.assertIn("doesn't have the switch etb-harmless-1", err)
        code, _, err = self.check("--switch", "removal-in-combat-1", "--game-patches", "off")
        self.assertEqual(code, 2)
        self.assertIn("--game-patches off", err)
        self.assertEqual(self.runs, [])

    def test_game_patches_off(self):
        code, _, err = self.check("--game-patches", "off", "--games", "2", "--commander-games", "0")
        self.assertEqual(code, 0, err)
        self.assertEqual({r["game_patches"] for r in self.runs}, {False})

    def test_the_key_verdict_is_with_game_patches_on(self):
        # A build that only adds a game patch plays the same with patches off, but real runs (patches
        # on) take another key, so the verdict says so whatever --game-patches says.
        self.patches[str(self.new)] = ["new-patch-1"]
        summary = self.tmp / "summary.json"
        code, out, err = self.check("--game-patches", "off", "--games", "2", "--commander-games", "0",
                                    "--json", str(summary))
        self.assertEqual(code, 0, err)
        self.assertIn("Different engine key (game_patches none -> new-patch-1)", out)
        self.assertFalse(json.loads(summary.read_text(encoding="utf-8"))["same_key"])
        self.assertEqual({r["game_patches"] for r in self.runs}, {False})

    def test_the_games_follow_the_flag_not_the_knob(self):
        self.settings["forge_game_patches"] = False
        code, _, err = self.check("--games", "2", "--commander-games", "0")
        self.assertEqual(code, 0, err)
        self.assertEqual({r["game_patches"] for r in self.runs}, {True})

    def test_an_install_that_isnt_there_or_isnt_a_fork(self):
        code, _, err = self.run_main("engine-check", "--old", str(self.tmp / "nowhere"))
        self.assertEqual(code, 2)
        self.assertIn("Forge isn't installed at", err)
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False,
                                                                       "problem": forge.simjar.NOT_FORK}):
            code, _, err = self.check()
        self.assertEqual(code, 2)
        self.assertIn("isn't Deck Lab's own build", err)

    def test_it_writes_neither_the_version_nor_the_engine_memory(self):
        for name in (forge.engine.REMEMBERED, forge.install.VERSION_FILE):
            (forge.common.DATA_DIR / name).unlink(missing_ok=True)
        forge.engine._memory.clear()
        forge.install._known.clear()
        (self.new / forge.install.BUILD_FILE).write_text(
            "build=2.0.15-decklab-bbb\nbase=forge-2.0.15\nres_sha256=" + "a" * 64 + "\n", encoding="utf-8")
        self.assertEqual(self.check("--games", "1", "--commander-games", "0")[0], 0)
        for name in (forge.engine.REMEMBERED, forge.install.VERSION_FILE):
            self.assertFalse((forge.common.DATA_DIR / name).exists(), name)
