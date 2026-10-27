"""Tests for decklab.lib.forge: deck files, keys, batches, reading Forge's output,
the win-rate maths, running batches, saved results, the page's views, AI limits,
housekeeping (failure logs, saving over a file that's open) and the command line.

No Java is needed: fixtures/fake_forge.py stands in for Forge (forge.runner.build_command is
replaced so it runs with this Python), in a made-up Forge folder holding the real card
scripts of fixtures/forge/cardscripts/ as its cardsfolder.zip (plus a made-up duplicate in
upcoming/), and a jar holding only a manifest that names the Forge build the card log was
checked with. fixtures/forge/*.log are real Forge 2.0.15 output, with the phase-by-phase
lines left out: from Milestone 0, one whole game (seed 7), the -c 1 run whose first two
games hit the clock, and a Rabbits vs Vampires game with three AI decision timeouts; and
from Milestone 8, cardlog-*.log, games played with the card log (DeckLabSim), each
described in fixtures/forge/cardlog-README.md (cardlog-s7.log is the same seed-7 game).
fixtures/forge/forge_cards.jsonl holds the real Scryfall cards those decks use, and
forge_tags.jsonl a made-up oracle tag tree with the real slugs power-boost-to-all and
overrun (Overrun sits two tags below power-boost-to-all, to check child tags count).

Every ForgeCase (and every other test that plays with the made-up Forge folder, through
pin_override_sets) reads Deck Lab's card-script override sets from fixtures/forge/overrides/,
a pinned copy of decklab/lib/forge/overrides/ in which only "fiery" is adopted, so no test
depends on which sets the repo has adopted since (test_forge_overrides.SetsTests checks the
repo's own sets).

DECKLAB_FORGE_TESTS=1 also runs a short real Forge matchup, with and without the card log
(Forge and a Java JDK installed). The fake Forge ignores the card log's jar: a run test that
wants the card log on patches forge.simjar.card_log to say it's ready (CARD_LOG), and
fake_command then passes --card-log, which makes the fake print DL| lines.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
Deck/model tests live in test_forge_models.py; execution and process-safety tests
live in test_forge_execution.py, and the cardlog-check tests in
test_forge_cardlog_check.py. Shared fixtures and the other CLI tests remain here.
"""
import hashlib
import importlib
import io
import json
import os
import pkgutil
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decklab.lib import cards, config, decks, forge, jobs

FIXTURES = Path(__file__).parent / "fixtures"
HERE = FIXTURES / "forge"
FAKE = FIXTURES / "fake_forge.py"
TAGS_FILE = HERE / "forge_tags.jsonl"
REAL = os.environ.get("DECKLAB_FORGE_TESTS") == "1"
_real_build_command = forge.runner.build_command    # setUpModule puts the fake in its place
_real_serve_command = forge.runner.serve_command    # ... and the fake's serve mode in this one's
# The made-up Forge's build. setUpModule puts it in simjar's checked versions in place of the real
# ones (the fork's build of the day), with the card log's source as it is, so these tests don't
# change when Deck Lab's Forge does.
CHECKED_BUILD = "2.0.15-SNAPSHOT-09.28"
# A pinned copy of the repo's override sets (sets.json and the sets' files) with only "fiery" adopted,
# copied from decklab/lib/forge/overrides/ at b91ecb5 (Forge 2.0.15). After a Forge upgrade, copy the
# repo's sets.json and set folders here again and set every set but fiery back to "experiment".
OVERRIDE_SETS = HERE / "overrides"

GREEN = """Deck
2 Llanowar Elves (FDN) 227
2 Llanowar Elves (M19) 314
4 Grizzly Bears
2 Overrun
1 Rabbit Response
1 Fiery Annihilation
2 Glorious Anthem
2 Giant Growth
6 Forest

Sideboard
2 Lightning Bolt
"""

RED = """Deck
4 Lightning Bolt
2 Fire // Ice
2 Murderous Rider // Swift End
1 Devout Decree
6 Mountain
5 Swamp
"""

GISA = """Commander
1 Ghoulcaller Gisa

Deck
4 Murderous Rider // Swift End
10 Swamp
"""

MIRROR_GISA = """Commander
1 Ghoulcaller Gisa

Deck
4 Lightning Bolt
10 Mountain
"""

_tmp = None
_patches = []


def setUpModule():
    global _tmp
    _tmp = Path(tempfile.mkdtemp())
    index = cards.build_index(HERE / "forge_cards.jsonl", TAGS_FILE, {"default_cards": "2026-09-28"},
                              log=lambda *a: None)
    cards.write_index(index, _tmp / "index.json.gz")
    cards.load(_tmp / "index.json.gz")
    make_forge(_tmp / "forge")
    for p in (mock.patch.object(forge.simjar, "CHECKED", frozenset({"2.0.15"})),
              mock.patch.object(forge.simjar, "CHECKED_BUILDS", {"2.0.15": CHECKED_BUILD}),
              mock.patch.object(forge.simjar, "CHECKED_SOURCE", {"2.0.15": forge.simjar.source_sha256()}),
              mock.patch.object(forge.runner, "build_command", fake_command),
              mock.patch.object(forge.runner, "serve_command", fake_serve_command),
              mock.patch.object(forge.ai, "TAG_FILE", TAGS_FILE)):
        p.start()
        _patches.append(p)


def tearDownModule():
    for p in reversed(_patches):
        p.stop()
    cards._index = None
    cards._tag_cache.clear()
    forge.install._status = None
    forge.install._scripts.clear()
    shutil.rmtree(_tmp, ignore_errors=True)


def make_forge(folder):
    """A Forge folder the module accepts: the jar (a manifest naming the build in
    simjar.CHECKED_BUILDS, and a list of Deck Lab's changes as the fork's build has, without a
    game-changing one, so a made-up JDK passes the card log's readiness) and cardsfolder.zip."""
    (folder / "res" / "cardsfolder").mkdir(parents=True)
    with zipfile.ZipFile(folder / "forge-gui-desktop-2.0.15-jar-with-dependencies.jar", "w") as z:
        z.writestr("META-INF/MANIFEST.MF", f"Manifest-Version: 1.0\r\nImplementation-Version: {CHECKED_BUILD}\r\n\r\n")
        z.writestr(forge.simjar.FORGE_PATCH_LIST, "forge/game/mulligan/AbstractMulligan.class -\n")
    with zipfile.ZipFile(folder / forge.SCRIPTS_ZIP, "w") as z:
        for path in sorted((HERE / "cardscripts").rglob("*.txt")):
            z.write(path, path.relative_to(HERE / "cardscripts").as_posix())


def pin_override_sets(case, folder=OVERRIDE_SETS):
    """Point forge.overrides at folder (OVERRIDE_SETS unless given) until the test ends: ForgeCase
    does it for every test, and a test case of another kind that plays with the made-up Forge
    calls it in its setUp. A test that wants other sets calls it again with their folder."""
    for p in (mock.patch.object(forge.overrides, "SETS_DIR", folder),
              mock.patch.object(forge.overrides, "SETS_FILE", folder / "sets.json")):
        p.start()
        case.addCleanup(p.stop)


def fake_command(setup, fmt, deck1, deck2, games, seed, v2=None, pilots=None):
    """runner.build_command for the fake Forge: the same request (runner.request_args, so
    v2's -dlgame too), with --card-log when the card log is ready (DeckLabSim), and then
    --game-patch-ids= its "game_patches" (the DLENGINE line's gamepatchids), and
    --game-patches-off for setup["game_patches"] False. pilots as build_command's (passed on only
    when given, as wave 2's request)."""
    more = {} if pilots is None else {"pilots": pilots}
    argv = [sys.executable, str(FAKE), *forge.runner.request_args(setup, fmt, deck1, deck2, games, seed, v2, **more)]
    log = setup.get("card_log") or {}
    if log.get("ready"):
        argv += ["--card-log", "--game-patch-ids=" + ",".join(log.get("game_patches", [])),
                 *_wave3_flags(setup)]
    if setup.get("game_patches") is False:
        argv.append("--game-patches-off")
    return argv


def _wave3_flags(setup):
    """Wave 3's flags for the fake (fixtures/fake_forge.py; sim-wave3-contract.md section 19.1):
    --pilot-switches= the card log's "pilot_switches", and -Ddecklab.aiprofiles= setup's AI
    profile folder when it has one (runner._java's flag for DeckLabSim)."""
    flags = ["--pilot-switches=" + ",".join((setup.get("card_log") or {}).get("pilot_switches", []))]
    if setup.get("aiprofiles"):
        flags.append(f"-Ddecklab.aiprofiles={setup['aiprofiles']}")
    return flags


def fake_serve_command(setup):
    """runner.serve_command for the fake Forge: its serve mode (fixtures/fake_forge.py), with
    --game-patch-ids= the card log's "game_patches"."""
    argv = [sys.executable, str(FAKE), "serve",
            "--game-patch-ids=" + ",".join((setup.get("card_log") or {}).get("game_patches", [])),
            *_wave3_flags(setup)]
    if setup.get("game_patches") is False:
        argv.append("--game-patches-off")
    return argv


# What simjar.card_log() gives when the card log can be used (the fake Forge ignores the jar).
CARD_LOG = {"ready": True, "jar": "C:/data/cardlog/decklab-sim-2.0.15-0123456789ab.jar", "main": "decklab.DeckLabSim",
            "add_opens": ["--add-opens", "java.desktop/java.beans=ALL-UNNAMED"], "game_patches": []}
NO_JDK = "The card log needs a full Java JDK (with javac and jar), and the Java that runs Forge doesn't have them."


def sections(text):
    return decks.parse_decklist(text)


def entry(text, deck_id="casual/test", kind="constructed", version="target", title=None):
    return forge.entry(deck_id, version, title or deck_id, kind, sections(text))


def alive(pid):
    """Is process pid still running?"""
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102       # WAIT_TIMEOUT
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_dead(pid, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def no_jdk_beside_python():
    """A patch of simjar._tool that finds no JDK beside sys.executable, the tests' stand-in for
    Forge's java. On Linux python and a real javac can share /usr/bin, which turned the card log
    on (and built it, for seconds, before each run) in tests that expect it off for want of a JDK.
    A made-up JDK folder (test_the_card_log_is_looked_at_every_time) is found as before."""
    real = forge.simjar._tool
    python = Path(sys.executable)
    return mock.patch.object(forge.simjar, "_tool",
                             lambda java, name: None if Path(java) == python else real(java, name))


class ForgeCase(unittest.TestCase):
    """A fresh data folder (decks, Forge user folder, results) and settings per test, with the
    pinned override sets (pin_override_sets)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        pin_override_sets(self)
        # 2 workers: a 200-game run is 2 batches of 100 (lists._batch_count), as the run tests expect.
        self.settings = {"forge_dir": str(_tmp / "forge"), "forge_java": sys.executable, "forge_workers": 2,
                         "forge_batch_games": 200, "forge_clock_s": 120, "forge_xmx": "1024m"}
        for p in (mock.patch.object(forge.common, "DATA_DIR", self.tmp / "data"),
                  mock.patch.object(forge.common, "_settings", lambda: dict(self.settings)),
                  no_jdk_beside_python()):
            p.start()
            self.addCleanup(p.stop)
        forge.install._status = None
        forge.install._scripts.clear()
        forge.saved._read_cache.clear()
        self.results = self.tmp / "results"
        self.log = self.tmp / "starts.log"
        env = mock.patch.dict(os.environ, {"FAKE_FORGE_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("FAKE_FORGE", None)

    def fake(self, modes):
        os.environ["FAKE_FORGE"] = modes

    def starts(self):
        """Complete, nonblank start records; the final append may still be in progress."""
        if not self.log.exists():
            return []
        complete = self.log.read_text(encoding="utf-8").split("\n")[:-1]
        rows = [line.split() for line in complete if line.strip()]
        return [(int(p), int(s), float(t)) for p, s, t in rows]


# ============================================================ reading Forge's output

def read_log(name, deck1=0):
    reader = forge.LogReader(deck1)
    with open(HERE / name, encoding="utf-8") as f:
        for line in f:
            reader.feed(line)
    return reader


# ============================================================ numbers


def stored(games, casts=None, cards_a=None, cards_b=None, kinds=("constructed", "constructed")):
    """A stored result made by hand: games as (winner side, result, first side)."""
    batch = {"n": 0, "seed": 1, "deck1": 0, "startup_s": 1.0, "wall_s": 10.0,
             "games": [{"w": w, "r": r, "first": f, "rounds": 5 + i % 3, "turns": 10, "ms": 800 + i,
                        "loss": "life total reached 0" if w is not None else None, "ai_to": i % 2}
                       for i, (w, r, f) in enumerate(games)],
             "casts": casts or [{}, {}], "lands": [{"Forest": len(games)}, {"Mountain": len(games)}]}
    sides = []
    for sha, listed, kind, deck_id in (("a" * 64, cards_a, kinds[0], "casual/aaa"), ("b" * 64, cards_b, kinds[1], "casual/bbb")):
        listed = listed or {"Commander": [], "Main": [[4, "Grizzly Bears"], [20, "Forest"]]}
        sides.append({"card_sha": sha, "dck": "", "card_count": 24, "kind": kind, "cards": listed,
                      "seen_as": [{"id": deck_id, "version": "target", "title": deck_id[7:].upper(), "source": None,
                                   "when": "2026-10-01T10:00:00"}]})
    return {"key": "c" * 64, "format": "Constructed", "forge_version": "2.0.15", "run_version": 1,
            "settings": {"clock_s": 120, "ai": ["Default", "Default"], "xmx": "1024m"}, "sides": sides,
            "runs": [{"when": "2026-10-01T10:00:00", "by": "Matt", "asked": len(games), "played": len(games),
                      "wall_s": 30.0, "stopped": False, "error": None}],
            "batches": [batch], "failed": [{"n": 1, "seed": 2, "deck1": 1, "error": "Forge stopped responding"}],
            "created": "2026-10-01T10:00:00", "updated": "2026-10-01T10:00:30"}


# ============================================================ running (the fake Forge)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================ status and Java

class StatusTests(ForgeCase):

    def test_ready(self):
        self.assertEqual(forge.status(), {"ready": True, "version": "2.0.15", "problem": None,
                                          "card_log": {"ready": False, "problem": NO_JDK}, "pool": None,
                                          "overrides": {"deployed": ["Fiery Annihilation"], "stale": [],
                                                        "hash": forge.overrides.deployed_hash(forge.common._user_dir())},
                                          "pilot_switches": []})
        # In the server, the warm pool's state (pool.status()).
        with mock.patch.object(forge.pool, "status", return_value={"workers": []}):
            self.assertEqual(forge.status()["pool"], {"workers": []})
        with mock.patch.object(forge.pool, "status", side_effect=RuntimeError("a bug")), \
                mock.patch.object(forge.common, "_log"):
            self.assertIsNone(forge.status()["pool"])         # status() never raises

    def test_the_card_log_is_looked_at_every_time(self):
        jdk = self.tmp / "jdk" / "bin"
        jdk.mkdir(parents=True)
        for name in ("java", "javac", "jar"):
            (jdk / (f"{name}.exe" if os.name == "nt" else name)).write_bytes(b"")
        self.settings["forge_java"] = str(jdk / ("java.exe" if os.name == "nt" else "java"))
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})
        self.settings["forge_dir"] = str(self.tmp / "forge-2.0.16")
        make_forge(self.tmp / "forge-2.0.16")
        (self.tmp / "forge-2.0.16" / "forge-gui-desktop-2.0.15-jar-with-dependencies.jar").rename(
            self.tmp / "forge-2.0.16" / "forge-gui-desktop-2.0.16-jar-with-dependencies.jar")
        found = forge.status()
        self.assertEqual((found["ready"], found["version"], found["card_log"]["ready"]), (True, "2.0.16", False))
        self.assertIn("cardlog-check", found["card_log"]["problem"])
        forge.simjar.record_checked("2.0.16", 20)       # cardlog-check, in another process say
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})     # no refresh needed

    def test_a_card_log_that_wont_build_is_off_until_it_builds(self):
        jdk = self.tmp / "jdk" / "bin"         # a made-up JDK: its javac and jar are empty files, which can't run
        jdk.mkdir(parents=True)
        for name in ("java", "javac", "jar"):
            (jdk / (f"{name}.exe" if os.name == "nt" else name)).write_bytes(b"")
        self.settings["forge_java"] = str(jdk / ("java.exe" if os.name == "nt" else "java"))
        logged = []
        p = mock.patch.object(forge.common, "_log", logged.append)      # the build's messages stay off the console
        p.start()
        self.addCleanup(p.stop)
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})
        a, b = entry(GREEN), entry(RED, deck_id="casual/red")
        result = forge.run(a, b, 200, by="test", results_dir=self.results)
        problem = "The card log couldn't be built for Forge 2.0.15."
        self.assertTrue(any("javac couldn't run" in line for line in logged))
        self.assertEqual((result["runs"][-1]["card_log"], result["runs"][-1]["card_log_problem"]), (False, problem))
        self.assertEqual(forge.status()["card_log"], {"ready": False, "problem": problem})      # the page says why

        def build(folder, jar, *args):         # one that works
            with zipfile.ZipFile(jar, "w") as z:
                for name in forge.simjar.CLASSES:
                    z.writestr(name, b"")

        with mock.patch.object(forge.simjar, "_build", build):
            # The card log's runs play the v2 engine (wave 2), whose results aren't the plain ones'.
            result = forge.run(a, b, 400, by="test", results_dir=self.tmp / "v2")
        self.assertTrue(result["runs"][-1]["card_log"])
        self.assertEqual(forge.status()["card_log"], {"ready": True, "problem": None})

    def test_not_installed(self):
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        found = forge.status()
        self.assertEqual(found, {"ready": False, "version": None,
                                 "problem": "Forge isn't installed at the folder config.json names.",
                                 "card_log": {"ready": False, "problem": "Forge can't run, so the card log can't either."},
                                 "pool": None, "overrides": {"deployed": [], "stale": [], "hash": "none"},
                                 "pilot_switches": []})
        self.settings["forge_dir"] = str(_tmp / "forge")
        self.assertTrue(forge.status()["ready"])        # checked again when it wasn't ready

    def test_no_java(self):
        self.settings["forge_java"] = str(self.tmp / "java.exe")
        found = forge.status()
        self.assertEqual((found["ready"], found["version"], found["problem"]),
                         (False, "2.0.15", "Java wasn't found, so Forge can't run."))

    def test_never_raises(self):
        with mock.patch.object(forge.common, "_settings", side_effect=ValueError("bad json")):
            found = forge.status()
        self.assertFalse(found["ready"])
        self.assertIn("settings", found["problem"])

    def test_find_java_takes_the_newest_jdk(self):
        root = self.tmp / "Program Files"
        for name in ("jdk-21.0.2", "jdk-26.0.1", "jdk-9"):
            (root / "Java" / name / "bin").mkdir(parents=True)
        exe = "java.exe" if os.name == "nt" else "java"
        for name in ("jdk-21.0.2", "jdk-26.0.1"):
            (root / "Java" / name / "bin" / exe).write_bytes(b"")
        with mock.patch.dict(os.environ, {"ProgramFiles": str(root)}):
            self.assertEqual(forge.find_java(), root / "Java" / "jdk-26.0.1" / "bin" / exe)
        self.assertIsNone(forge.find_java(str(self.tmp / "missing.exe")))
        self.assertEqual(forge.find_java(sys.executable), Path(sys.executable))

    def test_find_java_falls_back_to_java_home_then_the_path(self):
        exe = "java.exe" if os.name == "nt" else "java"
        home = self.tmp / "jdk"
        (home / "bin").mkdir(parents=True)
        (home / "bin" / exe).write_bytes(b"")
        empty = {"ProgramFiles": str(self.tmp / "no-program-files")}
        with mock.patch.dict(os.environ, {**empty, "JAVA_HOME": str(home)}):
            self.assertEqual(forge.find_java(), home / "bin" / exe)
        with mock.patch.dict(os.environ, empty), mock.patch.object(forge.install.shutil, "which",
                                                                    return_value=str(home / "bin" / exe)):
            os.environ.pop("JAVA_HOME", None)
            expected = None if os.name == "nt" else (home / "bin" / exe).resolve()
            self.assertEqual(forge.find_java(), expected)


# ============================================================ command line

class CommandLineTests(ForgeCase):

    def setUp(self):
        super().setUp()
        from decklab.lib import inventory
        from decklab.lib.inventory.files import FileInventory
        # Alias-aware deck lookup reads one inventory even when these lists are mocked.
        # Registered after ForgeCase's folder cleanup, so LIFO restores it before deletion.
        self.addCleanup(inventory.use(FileInventory(self.tmp)))
        summaries = [{"id": "casual/green", "title": "Green", "kind": "casual", "versions": ["target", "owned"]},
                     {"id": "casual/red", "title": "Red", "kind": "casual", "versions": ["target"]}]
        lists = {"casual/green": GREEN, "casual/red": RED}
        for p in (mock.patch.object(decks, "list_decks", return_value=summaries),
                  mock.patch.object(decks, "beginner_box_pairings", return_value=[]),
                  mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: sections(lists[deck_id]))):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *argv):
        """(exit code, stdout, stderr) of forge.main(argv)."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.main(list(argv))
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def play(self, *argv):
        return self.run_main("play", "casual/green", "casual/red", "--games", "200", "--results-dir", str(self.results),
                             *argv)

    def test_status(self):
        code, out, _ = self.run_main("status")
        self.assertEqual(code, 0)
        found, end = json.JSONDecoder().raw_decode(out)
        self.assertEqual(found, {"ready": True, "version": "2.0.15", "problem": None,
                                 "card_log": {"ready": False, "problem": NO_JDK}, "pool": None,
                                 "overrides": {"deployed": ["Fiery Annihilation"], "stale": [],
                                                        "hash": forge.overrides.deployed_hash(forge.common._user_dir())},
                                 "pilot_switches": []})
        self.assertEqual(out[end:].split("\n")[1:4], [f"java: {sys.executable}", f"card log: off. {NO_JDK}",
                                                     f"warm pool: {forge.cli._pool_line()}"])
        self.assertTrue(out.rstrip("\n").split("\n")[-1].startswith("build: This Forge is build "))   # not the release
        jdk = self.tmp / "jdk" / "bin"          # a made-up JDK: java, javac and jar
        jdk.mkdir(parents=True)
        for name in ("java", "javac", "jar"):
            (jdk / (f"{name}.exe" if os.name == "nt" else name)).write_bytes(b"")
        self.settings["forge_java"] = str(jdk / ("java.exe" if os.name == "nt" else "java"))
        self.assertIn("\ncard log: on (per-card stats)\n", self.run_main("status")[1])
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        code, out, _ = self.run_main("status")
        self.assertEqual(code, 1)
        self.assertIn("Forge isn't installed", out)
        self.assertIn("\nbuild: No Forge was found: download Deck Lab's Forge ", out)

    def test_cards_without_card_data(self):
        with mock.patch.object(forge.cardstats, "list_cards", return_value=None) as list_cards:
            self.assertEqual(self.run_main("cards", "casual/green", "--owned"), (0, "No card data yet.\n", ""))
        self.assertEqual(list_cards.call_args.args[1], "constructed")
        self.assertEqual(self.run_main("cards", "casual/red", "--owned"), (1, "", "casual/red has no owned-only list\n"))
        self.assertEqual(self.run_main("cards", "casual/red", "--results-dir", str(self.tmp / "nowhere"))[0], 1)

    def test_cards_prints_a_table(self):
        wr = lambda v, games: {"value": v, "low": v - 0.1, "high": v + 0.1, "games": games, "wins": round(v * games)}  # noqa: E731
        row = {"name": "Llanowar Elves", "qty": 4, "land": False, "drawn_games": 150, "drawn_share": 0.75,
               "copies_drawn": 200, "cast": 180, "cast_share": 0.9, "stuck": 10, "stuck_share": 0.05, "discarded": 2,
               "other_casts": 0, "avg_turn": 1.8, "wr_drawn": wr(0.55, 150), "wr_not": wr(0.4, 50),
               "diff": {"value": 0.15, "low": 0.02, "high": 0.28}, "judged": True, "verdict": "more"}
        forest = dict(row, name="Forest", qty=6, land=True, avg_turn=None, wr_not=None, diff=None, judged=False,
                      verdict=None)
        looting = dict(row, name="Faithless Looting", other_casts=12)
        # A land is never judged, however many games it has each way; a spell isn't until it has min_split.
        mountain = dict(forest, name="Mountain", wr_not=wr(0.3, 50), diff={"value": 0.25, "low": 0.1, "high": 0.4})
        bolt = dict(row, name="Lightning Bolt", judged=False, verdict=None)
        stats = {"games": 200, "bad": 1, "of": 400, "matchups": 2, "enough": True, "min_games": 100, "min_split": 30,
                 "rows": [row, looting, bolt, forest, mountain], "commander": []}
        with mock.patch.object(forge.cardstats, "list_cards", return_value=stats):
            code, out, _ = self.run_main("cards", "casual/green")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "casual/green (target): card data from 200 of 400 games in 2 matchups "
                                   "(1 more had a card log that failed its checks)")
        self.assertIn("can make a card look better or worse", out)
        elves = next(line for line in lines if "Llanowar Elves" in line)
        self.assertRegex(elves, r"Llanowar Elves +4 +75% +90% +5% +1\.8 +55% \(45-65\) / 40% \(30-50\) +"
                                r"\+15 \(\+2 to \+28\), won more when drawn$")
        self.assertLess(lines.index("  spells:"), lines.index("  lands:"))
        self.assertTrue(next(line for line in lines if line.startswith("  Forest")).endswith(" -"))
        self.assertTrue(next(line for line in lines if line.startswith("  Mountain"))
                        .endswith(" +25 (+10 to +40), no verdict for a land"))
        self.assertTrue(next(line for line in lines if line.startswith("  Lightning Bolt"))
                        .endswith(" +15 (+2 to +28), not enough games to tell"))
        self.assertIn("\n  A land gets no verdict: ", out)
        self.assertIn(" played ", lines[lines.index("  lands:") + 1])
        self.assertEqual(lines[-1], "  also cast from anywhere but the hand (the graveyard, exile, the library...): "
                                    "Faithless Looting 12 times")
        with mock.patch.object(forge.cardstats, "list_cards", return_value=stats):
            self.assertEqual(json.loads(self.run_main("cards", "casual/green", "--json")[1]), stats)

    def test_cards_prints_best_estimates_and_chance(self):
        # From W1-D's cardstats: each judged row has a best estimate ("shrunk"), and a range clear of 0
        # that isn't a Benjamini-Hochberg discovery among the cards compared says it's within chance.
        wr = lambda v, games: {"value": v, "low": v - 0.1, "high": v + 0.1, "games": games, "wins": round(v * games)}  # noqa: E731
        row = {"name": "Llanowar Elves", "qty": 4, "land": False, "drawn_games": 150, "drawn_share": 0.75,
               "copies_drawn": 200, "cast": 180, "cast_share": 0.9, "stuck": 10, "stuck_share": 0.05, "discarded": 2,
               "other_casts": 0, "avg_turn": 1.8, "wr_drawn": wr(0.55, 150), "wr_not": wr(0.4, 50),
               "diff": {"value": 0.15, "low": 0.02, "high": 0.28}, "shrunk": 0.061, "p": 0.003, "judged": True,
               "discovery": True, "verdict": "more"}
        chance = dict(row, name="Glorybringer", diff={"value": 0.033, "low": 0.001, "high": 0.067}, shrunk=0.026,
                      p=0.04, discovery=False, verdict="unclear")
        stats = {"games": 3600, "bad": 0, "of": 3600, "matchups": 4, "enough": True, "min_games": 800,
                 "min_split": 30, "compared": 27, "fdr": 0.1, "spread": 0.045, "spread_weight": 0.5,
                 "rows": [row, chance], "commander": []}
        with mock.patch.object(forge.cardstats, "list_cards", return_value=stats):
            out = self.run_main("cards", "casual/green")[1]
        lines = out.splitlines()
        self.assertTrue(next(line for line in lines if "Llanowar Elves" in line)
                        .endswith(" +15 (+2 to +28), best +6, won more when drawn"))
        self.assertTrue(next(line for line in lines if "Glorybringer" in line)
                        .endswith(" +3 (+0 to +7), best +3, no clear difference (range clear of 0, but within "
                                  "chance among 27 cards)"))
        self.assertIn("worked out matchup by matchup", out)
        self.assertIn("must stand out among the 27 cards compared\n  (Benjamini-Hochberg, 10% false discoveries).",
                      out)
        # One matchup: no "matchup by matchup" line.
        with mock.patch.object(forge.cardstats, "list_cards", return_value=dict(stats, matchups=1)):
            self.assertNotIn("matchup by matchup", self.run_main("cards", "casual/green")[1])

    def test_cards_prints_in_hand_by_turn_3(self):
        # Card log version 3 (test_forge_cardlog3): rows judged on whether a copy was in hand by turn 3 (basis
        # "early") show that share ("by t3") and its win rates; rows judged on drawn from games kept before it
        # (basis "drawn") say a "won more" leans with game length.
        wr = lambda v, games: {"value": v, "low": v - 0.1, "high": v + 0.1, "games": games, "wins": round(v * games)}  # noqa: E731
        row = {"name": "Llanowar Elves", "qty": 4, "land": False, "drawn_games": 150, "drawn_share": 0.75,
               "copies_drawn": 200, "cast": 180, "cast_share": 0.9, "stuck": 10, "stuck_share": 0.05, "discarded": 2,
               "other_casts": 0, "avg_turn": 1.8, "wr_drawn": wr(0.55, 150), "wr_not": wr(0.4, 50),
               "early_games": 100, "early_share": 0.5, "wr_early": wr(0.6, 100), "wr_not_early": wr(0.4, 100),
               "basis": "early", "diff": {"value": 0.2, "low": 0.06, "high": 0.33}, "shrunk": 0.08, "p": 0.003,
               "judged": True, "discovery": True, "verdict": "more"}
        stats = {"games": 200, "bad": 0, "of": 200, "matchups": 1, "enough": False, "min_games": 800, "min_split": 30,
                 "basis": "early", "early_of": 200, "compared": 20, "fdr": 0.1, "spread": 0.045, "spread_weight": 0.2,
                 "rows": [row], "commander": []}
        with mock.patch.object(forge.cardstats, "list_cards", return_value=stats):
            out = self.run_main("cards", "casual/green")[1]
        lines = out.splitlines()
        self.assertEqual(lines[lines.index("  spells:") + 1].split(),
                         ["card", "qty", "drawn", "by", "t3", "cast", "stuck", "turn", "won", "by", "t3", "/", "not",
                          "difference"])
        self.assertRegex(next(line for line in lines if "Llanowar Elves" in line),
                         r"Llanowar Elves +4 +75% +50% +90% +5% +1\.8 +60% \(50-70\) / 40% \(30-50\) +"
                         r"\+20 \(\+6 to \+33\), best \+8, won more when in hand by turn 3$")
        drawn = dict(stats, basis="drawn", early_of=0,
                     rows=[dict(row, basis="drawn", early_games=None, early_share=None, wr_early=None,
                                wr_not_early=None)])
        with mock.patch.object(forge.cardstats, "list_cards", return_value=drawn):
            out = self.run_main("cards", "casual/green")[1]
        self.assertTrue(next(line for line in out.splitlines() if "Llanowar Elves" in line)
                        .endswith(" +20 (+6 to +33), best +8, won more when drawn (leans with game length)"))
        self.assertIn("leans with game length.\n  A verdict needs 30 games each way", out)

    def check_command(self, change=None):
        """runner.build_command for cardlog-check with the fake Forge, recording each run in self.built
        ({"fmt", "card_log", "games", "seed", "v2", "game_patches", "decks"}). Plain Forge playing game g
        alone from its own seed is played by the fake as the v2 engine's game g without the card log: the
        fake's plain games follow other seeds than its v2 games, while real Forge plays the same game
        (contract section 4, which EJ's check holds it to). change(run) may give other arguments (a
        dict of request_args' to replace) for a run, to make it play other games. (The fake's v2
        games are a Match each, as in DeckLabSim and a plain one-game process, so their "Match
        Result" lines match.)"""
        self.built = []
        by_seed = {}
        for fmt, decks_, _ in forge.cli._check_legs(25, 25):
            _, stream = forge.cli._check_sides(decks_, fmt)
            for g in range(25):
                by_seed[forge.seeds.game_seed(forge.cli.CHECK_SEED, stream, g)] = (forge.seeds.stream_hex(stream), g)

        def build(setup, fmt, deck1, deck2, games, seed, v2=None):
            run = {"fmt": fmt, "card_log": bool((setup.get("card_log") or {}).get("ready")), "games": games, "seed": seed,
                   "v2": v2, "game_patches": setup.get("game_patches"), "decks": (deck1, deck2)}
            self.built.append(run)
            args = dict(fmt=fmt, deck1=deck1, deck2=deck2, games=games, seed=seed, v2=v2)
            args.update((change and change(run)) or {})
            if not run["card_log"]:
                stream, g = by_seed[args["seed"]]
                argv = fake_command(dict(setup, card_log=dict(CARD_LOG)), args["fmt"], args["deck1"], args["deck2"], 1,
                                    forge.cli.CHECK_SEED, {"stream": stream, "first": g, "card_log": False})
            else:
                argv = fake_command(setup, args["fmt"], args["deck1"], args["deck2"], args["games"], args["seed"],
                                    args["v2"])
            return argv
        return build

    def check(self, *argv, change=None):
        """cardlog-check with the fake Forge (check_command): the card log said to be ready."""
        with mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG)) as card_log, \
                mock.patch.object(forge.runner, "build_command", self.check_command(change)):
            found = self.run_main("cardlog-check", "--games", "6", "--commander-games", "2", *argv)
        self.assertTrue(card_log.call_args.kwargs["checking"])
        return found

    def made_up_jdk(self):
        """config.json's forge_java: a made-up JDK (java, javac and jar), which passes the
        card log's readiness."""
        jdk = self.tmp / "jdk" / "bin"
        jdk.mkdir(parents=True)
        for name in ("java", "javac", "jar"):
            (jdk / (f"{name}.exe" if os.name == "nt" else name)).write_bytes(b"")
        self.settings["forge_java"] = str(jdk / ("java.exe" if os.name == "nt" else "java"))

    def test_audit(self):
        code, out, _ = self.run_main("audit", "casual/green")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            # Forge's card scripts (R19): the 3 team pumps flag it as a list Forge pilots poorly. Their count
            # replaces the oracle tags' "team pump" line, so the audit gives one count.
            "casual/green (target):",
            "  Forge pilots this list poorly: 3 cards pump the whole team (3 spells)",
            "    2 Overrun: pumps the whole team, which the AI judges one creature at a time",
            "    1 Rabbit Response: pumps the whole team, which the AI judges one creature at a time"])
        code, out, _ = self.run_main("audit", "casual/red", "--json")
        self.assertEqual(json.loads(out)["cannot_play"], [{"name": "Devout Decree", "qty": 1, "why": "script"}])
        self.assertEqual(self.run_main("audit", "casual/nope"), (1, "", "No deck 'casual/nope'\n"))
        self.assertEqual(self.run_main("audit", "casual/red", "--owned"), (1, "", "casual/red has no owned-only list\n"))

    def test_play(self):
        code, out, err = self.play("--by", "User1", "--a-first")
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertRegex(lines[0], r"^Green won \d+\.\d% \(\d+\.\d%-\d+\.\d%, play/draw balanced\) of 200 games against Red$")
        self.assertTrue(lines[-1].startswith("  key "))
        self.assertTrue(err.startswith("A: Green (target, 22 cards, "))
        self.assertEqual(err.count("  200/200 games: A "), 1)          # the final numbers once
        saved = forge.load(lines[-1].split()[-1], self.results)
        self.assertEqual((saved["runs"][0]["by"], saved["runs"][0]["played"]), ("User1", 200))
        green = [s["card_sha"] for s in saved["sides"]].index(entry(GREEN)["card_sha"])
        self.assertEqual(saved["batches"][0]["deck1"], green)          # --a-first: Green is deck 1 first

    def test_play_without_saving_as_json(self):
        code, out, err = self.run_main("play", "casual/green", "casual/red", "--owned-a", "--games", "200",
                                       "--results-dir", str(self.results), "--no-save", "--json")
        self.assertEqual(code, 0, err)
        shown = json.loads(out)
        self.assertEqual((shown["view"]["games"], shown["result"]["runs"][0]["by"]), (200, "command line"))
        seen = {s["seen_as"][0]["id"]: s["seen_as"][0]["version"] for s in shown["result"]["sides"]}
        self.assertEqual(seen, {"casual/green": "owned", "casual/red": "target"})
        self.assertFalse(self.results.exists())

    def test_play_errors_are_plain_sentences(self):
        self.assertEqual(self.play("--games", "500"),
                         (1, "", "Games must be one of 200, 400, 800, 1600 or 3200.\n"))
        self.assertEqual(self.play("--games", "25", "--batch", "10"),
                         (1, "", "Games must be a whole number of batches of 10 (--batch).\n"))
        self.assertEqual(self.play("--seed-base", "-1"), (1, "", "The seed base must be 0 or more (--seed-base).\n"))
        self.assertEqual(self.run_main("play", "casual/green", "nothere.dck", "--no-save"),
                         (1, "", "There's no deck file called nothere.dck.\n"))
        empty = self.tmp / "empty.dck"
        empty.write_text("[metadata]\nName=Empty\n[Main]\n", encoding="utf-8")
        self.assertEqual(self.run_main("play", "casual/green", str(empty), "--no-save"),
                         (1, "", f"The deck file {empty} has no cards in [Main] or [Commander].\n"))
        self.assertEqual(self.run_main("play", "casual/green", "casual/nope", "--no-save"),
                         (1, "", "No deck 'casual/nope'\n"))
        self.assertEqual(self.starts(), [])

    def test_workers_and_batch_must_be_one_or_more(self):
        for flag in ("--workers", "--batch"):
            with mock.patch("sys.stderr", io.StringIO()) as err, self.assertRaises(SystemExit) as caught:
                forge.main(["play", "casual/green", "casual/red", flag, "0", "--no-save"])
            self.assertEqual(caught.exception.code, 2)
            self.assertIn(f"argument {flag}: must be a whole number of 1 or more, not '0'", err.getvalue())
        self.assertEqual(self.starts(), [])

    def test_list(self):
        self.assertEqual(self.run_main("list", "--results-dir", str(self.results)),
                         (1, "", f"There's no folder called {self.results}.\n"))
        self.results.mkdir()
        listed = self.run_main("list", "--results-dir", str(self.results))
        deployed = forge.overrides.deployed_hash(forge.common._user_dir())[:12]
        # The shipped simulation.json's pilots too: The Free Peoples' optional-target fix (adopted 2026-10-21).
        self.assertEqual(listed, (0, f"card-script overrides: Fiery Annihilation (hash {deployed})\n"
                                     "pilot of casual/the-free-peoples: Forge's AI plays it with the optional-target fix\n"
                                     "No saved matchups.\n", ""))
        self.play()
        code, out, _ = self.run_main("list", "--results-dir", str(self.results))
        self.assertEqual(code, 0)
        # Played with plain Forge (the tests' Java has no JDK, so no card log): marked so. test_forge_engine has
        # the marks of the other engines.
        self.assertRegex(out, r"^card-script overrides: [^\n]+\n(?:pilot of [^\n]+\n)*"
                              r"\S+ +200 games +\d+\.\d%  casual/green \(target\) vs casual/red \(target\)  by command line"
                              r"  \[plain Forge\]\n$")

    def test_ctrl_c_says_what_was_saved(self):
        real_tidy = forge.runner._tidy_user_dir

        def tidy(user_dir):                 # Ctrl+C as the last games end
            signal.raise_signal(signal.SIGINT)
            sum(range(1000))
            real_tidy(user_dir)

        with mock.patch.object(forge.runner, "_tidy_user_dir", tidy):
            code, _, err = self.play()
            self.assertEqual((code, err.splitlines()[-1]), (130, "Stopped: the 200 games that finished were saved."))
            code, _, err = self.play("--no-save")
            self.assertEqual((code, err.splitlines()[-1]), (130, "Stopped."))
        with mock.patch.object(forge.install, "script_index", side_effect=KeyboardInterrupt):     # before Forge starts
            code, _, err = self.play()
        self.assertEqual((code, err.splitlines()[-1]), (130, "Stopped."))
        self.assertEqual(len(forge.load(forge.matchup_key(entry(GREEN), entry(RED)), self.results)["runs"]), 1)


# ============================================================ the package

class PackageTests(unittest.TestCase):
    """forge is a package (Milestone 7). A name the tests patch or reset, or that changes
    at run time, has one binding, in the part every reader goes through: a copy (a
    from-import in another part, or one on the package) would let a patch or a reset
    miss the code without a word."""

    OWNED = {"common": ("DATA_DIR", "_settings", "_log", "_write_atomic"),
             "simjar": ("card_log", "_built", "_builds", "_build", "_manifest", "_replace", "_failed",
                        "SOURCE", "LOCK_WAIT"),
             "install": ("_status", "_known", "_scripts", "_build_index", "script_index"),
             "lists": ("_sources",),
             "processes": ("_job", "_job_warned", "_ntdll", "start_process"),
             "saved": ("_read_cache",),
             "cardstats": ("MIN_CARD_GAMES", "MIN_SPLIT_GAMES", "card_rows", "list_cards"),
             "runner": ("build_command", "_tidy_user_dir", "PROGRESS_GAP", "GAME_GRACE", "HEADER_TIMEOUT"),
             "ai": ("TAG_FILE", "MIN_GAMES_NEVER_CAST", "side_ai"),
             "views": ("list_item",)}

    def test_a_name_the_tests_patch_has_one_binding(self):
        parts = {info.name: importlib.import_module(f"decklab.lib.forge.{info.name}")
                 for info in pkgutil.iter_modules(forge.__path__) if info.name != "__main__"}
        for owner, names in self.OWNED.items():
            for name in names:
                if name == "_ntdll" and sys.platform != "win32":
                    continue
                with self.subTest(name=name):
                    self.assertEqual([part for part, module in parts.items() if name in vars(module)], [owner])
                    self.assertNotIn(name, vars(forge))
                    # Setting or patching it on the package fails, rather than changing a copy nothing reads.
                    with self.assertRaises(AttributeError):
                        setattr(forge, name, vars(parts[owner])[name])
                    with self.assertRaises(AttributeError), mock.patch.object(forge, name, None):
                        pass

    def test_list_item_side_ai_and_list_cards_read_through_to_their_part(self):
        # The api calls them as forge.list_item, forge.side_ai and forge.list_cards: a patch
        # of their part reaches it.
        for part, name in ((forge.views, "list_item"), (forge.ai, "side_ai"), (forge.cardstats, "list_cards")):
            with mock.patch.object(part, name) as patched:
                self.assertIs(getattr(forge, name), patched)
            self.assertIs(getattr(forge, name), vars(part)[name])


# ============================================================ real Forge

@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to play real Forge games")
class RealForgeTests(unittest.TestCase):

    def test_twenty_games_of_two_small_decks(self):
        forge.install._status = None
        self.assertTrue(forge.status()["ready"], forge.status()["problem"])
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        a = forge.entry("casual/test-elves", "target", "Elves", "constructed",
                        decks.parse_decklist("Deck\n4 Llanowar Elves\n4 Grizzly Bears\n4 Giant Growth\n12 Forest\n"))
        b = forge.entry("casual/test-bolts", "target", "Bolts", "constructed",
                        decks.parse_decklist("Deck\n4 Lightning Bolt\n4 Fire // Ice\n16 Mountain\n"))
        with mock.patch.object(forge.runner, "build_command", _real_build_command):
            result = forge.run(a, b, 20, by="test", results_dir=tmp, batch=10, workers=2)
        v = forge.view(result, a["card_sha"])
        self.assertEqual(v["games"], 20)
        self.assertEqual(result["failed"], [])
        self.assertEqual(sum(v["wins"]) + v["draws"] + v["timeouts"] + v["errors"], 20)
        self.assertEqual(v["on_play"]["games"] + v["on_draw"]["games"], 20)
        self.assertGreater(sum(c["casts"] for c in v["casts"][0]), 0)
        self.assertGreater(next(c for c in v["casts"][1] if c["name"] == "Fire // Ice")["casts"], 0)
        # The same seeds play the same games.
        with mock.patch.object(forge.runner, "build_command", _real_build_command):
            again = forge.run(a, b, 20, by="test", results_dir=tmp / "again", batch=10, workers=2)
        same = lambda r: [(g["w"], g["first"], g["turns"]) for b in r["batches"] for g in b["games"]]  # noqa: E731
        self.assertEqual(same(again), same(result))
        # With and without the card log (DeckLabSim): the same games, and card records only with it.
        self.assertTrue(forge.status()["card_log"]["ready"], forge.status()["card_log"]["problem"])
        self.assertTrue(result["runs"][0]["card_log"])
        for batch in result["batches"]:
            self.assertEqual(batch["cards"]["games"] + batch["cards"]["bad"], len(batch["games"]))
            self.assertEqual(batch["cards"]["bad"], 0)
        off = {"ready": False, "problem": "Off for the test."}
        with mock.patch.object(forge.runner, "build_command", _real_build_command), \
                mock.patch.object(forge.simjar, "card_log", return_value=off):
            plain = forge.run(a, b, 20, by="test", results_dir=tmp / "plain", batch=10, workers=2)
        self.assertEqual((plain["runs"][0]["card_log"], plain["runs"][0]["card_log_problem"]),
                         (False, "Off for the test."))
        self.assertTrue(all("cards" not in batch for batch in plain["batches"]))
        self.assertEqual(same(plain), same(result))
        self.assertEqual([b["casts"] for b in plain["batches"]], [b["casts"] for b in result["batches"]])


if __name__ == "__main__":
    unittest.main()
