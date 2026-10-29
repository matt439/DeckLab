"""Tests for decklab.lib.goldfish's runs (goldfish's runs.py, workers.py,
results.py and cli.py): simulate() in this process and in worker processes,
the saved results, the command line, and workers ending with the process
that started them. The card index (setUpModule) and the helpers come from
test_goldfish.py, which tests the card reading and the game loop.

Names the tests patch (simulate, CHUNK_GAMES, CACHE_DIR, ...) are patched on
the goldfish module whose code reads them (goldfish.runs, goldfish.cli): the
package refuses them, and TestPatchTargets checks there's no other copy.

Run from the repo root: python scripts/test_fixtures.py
"""
import importlib
import io
import json
import math
import multiprocessing
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import decks, goldfish
from decklab.tests import test_goldfish
# setUpModule and tearDownModule load and unload test_goldfish's card index for these tests too.
from decklab.tests.test_goldfish import deck_text, parse, setUpModule, tearDownModule, tolerance, walk  # noqa: F401


# --------------------------------------------------------------- results

SMALL_DECK = "Deck\n10 Forest\n7 Mountain\n4 Llanowar Elves\n4 Grizzly Bears\n4 Lightning Bolt\n4 Hill Giant\n" \
             "3 Rampant Growth\n4 Craw Wurm\n"


class TestSimulate(unittest.TestCase):

    def test_same_seed_same_result_and_json_safe(self):
        a = goldfish.simulate(parse(SMALL_DECK), "constructed", games=500, seed=9, workers=1)
        b = goldfish.simulate(parse(SMALL_DECK), "constructed", games=500, seed=9, workers=1)
        self.assertEqual(a["results"], b["results"])
        c = goldfish.simulate(parse(SMALL_DECK), "constructed", games=500, seed=10, workers=1)
        self.assertNotEqual(a["results"], c["results"])
        json.dumps(a)
        for value in walk(a):
            self.assertIsInstance(value, (dict, list, str, int, float, bool, type(None)))

    def test_mirror_image_colours_get_mirror_image_numbers(self):
        # Recheck finding: a tie between two colours went by colour or card order (Uncharted Haven's colour,
        # the basic Evolving Wilds finds, the land put on the bottom), so a deck of blue and black cards in
        # equal numbers showed a blue source on turn 1 about 6 points more often than a black one.
        n = 20_000
        result = goldfish.simulate(parse("Deck\n6 Island\n6 Swamp\n3 Uncharted Haven\n3 Evolving Wilds\n11 Opt\n"
                                         "11 Tormented Soul\n"), "constructed", games=n, turns=3, seed=9, workers=1)
        rows = {r["colour"]: r["chances"] for r in result["results"]["play"]["colours"]["by_turn"]}
        for turn, (u, b) in enumerate(zip(rows["U"], rows["B"]), 1):
            self.assertLess(abs(u - b), math.sqrt(2) * tolerance(0.5, n), turn)

    def test_results_do_not_depend_on_the_number_of_workers(self):
        # The one test of the multiprocessing path: 2 spawned workers, 10 chunks.
        with mock.patch.object(goldfish.runs, "CHUNK_GAMES", 60):
            one = goldfish.simulate(parse(SMALL_DECK), "constructed", games=300, seed=3, workers=1)
            seen = []
            two = goldfish.simulate(parse(SMALL_DECK), "constructed", games=300, seed=3, workers=2,
                                    progress=lambda done, total: seen.append((done, total)))
        self.assertEqual((one["workers"], two["workers"], one["chunks"]), (1, 2, 10))
        self.assertEqual(one["results"], two["results"])
        self.assertEqual(seen[-1], (600, 600))
        self.assertEqual(len(seen), 10)

    def test_default_seed_comes_from_the_decklist(self):
        a = goldfish.simulate(parse(SMALL_DECK), "constructed", games=50, workers=1)
        shuffled = "Deck\n" + "".join(reversed(SMALL_DECK.splitlines(keepends=True)[1:]))
        b = goldfish.simulate(parse(shuffled), "constructed", games=50, workers=1)
        c = goldfish.simulate(parse(SMALL_DECK + "1 Forest\n"), "constructed", games=50, workers=1)
        self.assertEqual((a["seed_source"], a["seed"]), ("decklist", b["seed"]))
        self.assertEqual(a["results"], b["results"])
        self.assertNotEqual(a["seed"], c["seed"])

    def test_progress_and_settings(self):
        seen = []
        result = goldfish.simulate(parse(SMALL_DECK), "constructed", games=250, turns=6, seed=1, workers=1,
                                   progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(250, 500), (500, 500)])
        self.assertEqual((result["games"], result["turns"], result["version"]), (250, 6, goldfish.GOLDFISH_VERSION))
        self.assertEqual([s["id"] for s in result["setups"]], ["play", "draw"])
        self.assertEqual(len(result["results"]["play"]["land_drops"]["on_time"]), 6)
        self.assertEqual(result["deck"], {"cards": 40, "lands": 17, "spell_lands": 0, "commanders": []})
        self.assertTrue(result["rules"] and result["definitions"] and "comp-rules" in result["sources"])

    def test_bad_settings(self):
        with self.assertRaises(ValueError):
            goldfish.simulate(parse(SMALL_DECK), "vintage", games=10, workers=1)
        with self.assertRaises(ValueError):
            goldfish.simulate(parse(SMALL_DECK), "constructed", games=0, workers=1)
        with self.assertRaises(ValueError):
            goldfish.simulate(parse(SMALL_DECK), "constructed", games=10, turns=0, workers=1)
        with self.assertRaises(ValueError):
            goldfish.simulate(parse("Deck\n5 Forest\n"), "constructed", games=10, workers=1)

    def test_companion_and_sideboard_are_not_used(self):
        text = "Companion\n1 Serra Angel\n\nDeck\n17 Forest\n23 Grizzly Bears\n\nSideboard\n4 Craw Wurm\n"
        result = goldfish.simulate(parse(text), "constructed", games=50, workers=1)
        self.assertEqual(result["deck"]["cards"], 40)
        self.assertTrue(any("companion isn't used" in w for w in result["warnings"]))
        self.assertEqual(result["results"]["play"]["first_big"]["in_deck"], 0)

    def test_deck_with_no_four_drops_says_so(self):
        result = goldfish.simulate(parse("Deck\n17 Forest\n23 Grizzly Bears\n"), "constructed", games=50,
                                   workers=1)
        first = result["results"]["play"]["first_big"]
        self.assertEqual(first["in_deck"], 0)
        self.assertIsNone(first["by_turn_4"])
        self.assertIn("no spells with mana value 4", first["note"])

    def test_cards_treated_specially_and_not_modelled(self):
        text = ("Deck\n16 Forest\n2 Rootbound Crag\n4 Llanowar Elves\n2 Sol Ring\n2 Rampant Growth\n"
                "2 Fire // Ice\n2 Opt\n2 Stormcatch Mentor\n2 Claim Jumper\n1 Notacard Atall\n5 Craw Wurm\n")
        result = goldfish.simulate(parse(text), "constructed", games=50, workers=1)
        special = {(c["name"], c["rule"]) for c in result["cards"]["special"]}
        self.assertIn(("Rootbound Crag", "enters tapped unless you control a Mountain or Forest"), special)
        self.assertIn(("Llanowar Elves", "mana creature ({G}): makes mana from the turn after it's cast"), special)
        self.assertIn(("Sol Ring", "mana rock ({C}): makes mana from the turn it's cast"), special)
        self.assertIn(("Rampant Growth", "land ramp: puts 1 land onto the battlefield tapped"), special)
        self.assertIn(("Fire // Ice", "either half can be cast"), special)
        missing = {(c["name"], c["what"]) for c in result["cards"]["not_modelled"]}
        self.assertIn(("Opt", "card draw isn't modelled"), missing)
        self.assertIn(("Stormcatch Mentor", "cost reduction isn't modelled"), missing)
        self.assertIn(("Claim Jumper", "its land search needs an opponent with more lands, so it never happens"),
                      missing)
        self.assertEqual(result["cards"]["unresolved"], [{"name": "Notacard Atall", "qty": 1, "section": "Deck"}])
        self.assertEqual(result["deck"]["cards"], 40)
        self.assertTrue(any("Notacard Atall" in w for w in result["warnings"]))

    def test_headline(self):
        result = goldfish.simulate(parse(SMALL_DECK), "constructed", games=200, seed=1, workers=1)
        h = goldfish.headline(result)
        r = result["results"]["play"]
        self.assertEqual(h["setup"], "play")
        self.assertEqual(h["mulligan_rate"], r["mulligans"]["rate"])
        self.assertEqual(h["land_3_by_3"], r["land_drops"]["on_time"][2]["chance"])
        self.assertEqual(h["big_by_4"], r["first_big"]["by_turn_4"])

    def test_headline_of_a_commander_deck_is_multiplayer(self):
        # Review finding: it gave 1v1 numbers on the play, which the shop's Commander nights aren't.
        sections = parse(deck_text({"Forest": 38, "Craw Wurm": 61}, commander="Finneas, Ace Archer"))
        result = goldfish.simulate(sections, "commander", games=100, seed=1, workers=1)
        h = goldfish.headline(result)
        self.assertEqual(h["setup"], "multiplayer")
        self.assertEqual(h["mulligan_rate"], result["results"]["multiplayer"]["mulligans"]["rate"])
        self.assertEqual(goldfish.headline(result, "play")["setup"], "play")

    def test_chances_near_0_or_1_are_not_rounded_to_them(self):
        # Review finding: 99,997 of 100,000 was stored as 1.0, so the page said 100%.
        share = goldfish._share
        self.assertEqual((share(99_997, 100_000), share(3, 100_000)), (0.99997, 0.00003))
        self.assertEqual((share(0, 7), share(7, 7), share(1, 0)), (0.0, 1.0, None))
        tiny, near = share(1, 3_000_000), share(2_999_999, 3_000_000)
        self.assertTrue(0 < tiny < 1e-6 and 1 - 1e-6 < near < 1, (tiny, near))
        self.assertEqual(share(123_456, 1_000_000), 0.123456)
        self.assertEqual(goldfish._average(12_345, 10_000, 2), 1.23)

    def test_unresolved_commander_is_named(self):
        # Review finding: a misspelt commander read as "no Commander section" and as a library card.
        text = "Commander\n1 Finneas, Ace Archr\n\nDeck\n38 Forest\n30 Craw Wurm\n31 Totally Fake Card\n" \
               "\nSideboard\n1 Another Fake\n"
        _, info = goldfish.compile_deck(parse(text), "commander")
        self.assertEqual(info["warnings"], [
            "31 cards with names that aren't Scryfall cards take a place in the library but can't be played: "
            "Totally Fake Card",
            "The commander Finneas, Ace Archr isn't a Scryfall card name, so it's never cast."])
        self.assertEqual(info["deck"]["cards"], 100)
        self.assertEqual([(u["name"], u["section"]) for u in info["unresolved"]],
                         [("Finneas, Ace Archr", "Commander"), ("Totally Fake Card", "Deck"),
                          ("Another Fake", "Sideboard")])
        _, info = goldfish.compile_deck(parse("Deck\n38 Forest\n61 Craw Wurm\n"), "commander")
        self.assertEqual(info["warnings"], ["This Commander deck has no Commander section, so no commander is cast."])
        # One card: "a name that isn't a Scryfall card takes" (it read "names that aren't Scryfall cards takes").
        _, info = goldfish.compile_deck(parse("Deck\n38 Forest\n21 Craw Wurm\n1 Totally Fake Card\n"), "constructed")
        self.assertEqual(info["warnings"], ["1 card with a name that isn't a Scryfall card takes a place in the "
                                            "library but can't be played: Totally Fake Card"])

    def test_cost_mechanics_and_other_searches_are_listed_as_not_modelled(self):
        # Review finding: Conclave Tribunal (convoke) is charged its full cost with no note; a search for a
        # card that isn't a land (Fierce Empath) had none either.
        _, info = goldfish.compile_deck(parse("Deck\n20 Plains\n1 Conclave Tribunal\n1 Fierce Empath\n"),
                                        "constructed")
        missing = {(c["name"], c["what"]) for c in info["not_modelled"]}
        self.assertIn(("Conclave Tribunal", "convoke isn't modelled: the full mana cost is paid"), missing)
        self.assertIn(("Fierce Empath", "its library search (for a card that isn't a land) isn't modelled"), missing)

    def test_a_deck_that_runs_out_of_cards_says_so(self):
        # Review finding: a 20-card half ran dry by turn 14 with --turns 20 and nothing said so.
        text = "Deck\n8 Forest\n12 Grizzly Bears\n"
        result = goldfish.simulate(parse(text), "constructed", games=20, turns=20, seed=1, workers=1)
        self.assertIn("This deck has 20 cards to draw from, so from turn 14 on the draw (turn 15 on the play) "
                      "there's no card left to draw", result["warnings"][-1])
        result = goldfish.simulate(parse(text), "constructed", games=20, turns=8, seed=1, workers=1)
        self.assertEqual(result["warnings"], [])

    def test_a_stopped_run_ends_early(self):
        # progress() raising (the server stopping) ends the run; chunks not started are dropped.
        seen = []

        def stop(done, total):
            seen.append(done)
            raise RuntimeError("stopping")

        with mock.patch.object(goldfish.runs, "CHUNK_GAMES", 30):
            with self.assertRaises(RuntimeError):
                goldfish.simulate(parse(SMALL_DECK), "constructed", games=300, seed=3, workers=2, progress=stop)
        self.assertEqual(len(seen), 1)

    def test_workers_leave_ctrl_c_to_the_server(self):
        old = signal.getsignal(signal.SIGINT)
        try:
            goldfish._start_worker()        # in this process (no parent to watch) it only ignores Ctrl+C
            self.assertIs(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        finally:
            signal.signal(signal.SIGINT, old)

    def test_workers_start_in_a_process_group_of_their_own(self):
        # Review finding: a Ctrl+C while a worker was still importing the server printed its traceback. On
        # Windows the workers start in a new process group, where Ctrl+C is off from their first moment; the
        # server keeps its own Ctrl+C.
        made = []

        class FakeWinapi:
            CloseHandle = "passed through"

            def CreateProcess(self, *args):
                made.append(args[5])
                return "process"

        winapi = goldfish._GroupWinapi(FakeWinapi())
        self.assertEqual(winapi.CreateProcess("python.exe", "cmd", None, None, False, 0, None, None, None), "process")
        self.assertEqual((made, winapi.CloseHandle), ([goldfish.CREATE_NEW_PROCESS_GROUP], "passed through"))
        if sys.platform == "win32":
            from multiprocessing import popen_spawn_win32
            real = popen_spawn_win32._winapi
            spawn = goldfish._GroupWinapi.CreateProcess
            with mock.patch.object(goldfish._GroupWinapi, "CreateProcess", autospec=True, side_effect=spawn) as create:
                goldfish.simulate(parse(SMALL_DECK), "constructed", games=40, seed=1, workers=2)
            self.assertEqual(create.call_count, 2)                  # both workers
            self.assertIs(popen_spawn_win32._winapi, real)          # and put back afterwards

    def test_a_worker_ends_when_its_parent_does(self):
        # Review finding: killing only the server (End task) left its 16 workers waiting for ever.
        reader, writer = multiprocessing.Pipe(duplex=False)
        ended = []
        watch = threading.Thread(target=goldfish._exit_with, args=(reader, ended.append), daemon=True)
        watch.start()
        time.sleep(0.1)
        self.assertEqual(ended, [])
        writer.close()                      # what a dead parent's process handle does
        watch.join(10)
        self.assertEqual(ended, [1])


class TestCache(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def run_cached(self, text=SMALL_DECK, **kw):
        settings = {"games": 100, "seed": 1, "workers": 1, "cache_dir": self.dir}
        settings.update(kw)
        return goldfish.get_or_simulate(parse(text), "constructed", **settings)

    def test_miss_then_hit(self):
        first = self.run_cached()
        self.assertFalse(first["cached"])
        self.assertEqual(len(list(self.dir.glob("*.json"))), 1)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])
        with mock.patch.object(goldfish.runs, "simulate", side_effect=AssertionError("should be cached")):
            second = self.run_cached()
        self.assertTrue(second["cached"])
        self.assertEqual(second["results"], first["results"])
        self.assertEqual(second["cache_key"], first["cache_key"])

    def test_changes_that_miss(self):
        first = self.run_cached()
        for changed in (self.run_cached(SMALL_DECK + "1 Forest\n"), self.run_cached(seed=2),
                        self.run_cached(games=101), self.run_cached(turns=7), self.run_cached(mulligans=False)):
            self.assertFalse(changed["cached"])
            self.assertNotEqual(changed["cache_key"], first["cache_key"])
        with mock.patch.object(goldfish.runs, "GOLDFISH_VERSION", goldfish.runs.GOLDFISH_VERSION + 1):
            self.assertFalse(self.run_cached()["cached"])
        self.assertTrue(self.run_cached()["cached"])

    def test_printings_and_order_do_not_matter(self):
        first = self.run_cached()
        other = SMALL_DECK.replace("10 Forest", "9 Forest\n1 Forest (FDN) 176")
        self.assertTrue(self.run_cached(other)["cached"])
        self.assertEqual(self.run_cached(other)["cache_key"], first["cache_key"])

    def test_damaged_file_is_recomputed_and_refresh(self):
        first = self.run_cached()
        path = self.dir / f"{first['cache_key']}.json"
        path.write_text("{not json", encoding="utf-8")
        again = self.run_cached()
        self.assertFalse(again["cached"])
        self.assertEqual(again["results"], first["results"])
        self.assertFalse(self.run_cached(refresh=True)["cached"])

    def test_saved_result_only_reads(self):
        sections = parse(SMALL_DECK)
        key = goldfish.cache_key(sections, "constructed", games=100, seed=1)
        self.assertIsNone(goldfish.saved_result(key, self.dir))
        self.assertEqual(list(self.dir.iterdir()), [])
        first = self.run_cached()
        self.assertEqual(first["cache_key"], key)
        saved = goldfish.saved_result(key, self.dir)
        self.assertTrue(saved["cached"])
        self.assertEqual(saved["results"], first["results"])
        with mock.patch.object(goldfish.runs, "GOLDFISH_VERSION", goldfish.runs.GOLDFISH_VERSION + 1):
            self.assertIsNone(goldfish.saved_result(key, self.dir))
        with mock.patch.object(goldfish.runs, "CACHE_DIR", self.dir):
            self.assertTrue(goldfish.saved_result(key)["cached"])
        for bad in ("../" + key[3:], key.upper(), key[:-1], None):
            with self.subTest(key=bad), self.assertRaises(ValueError):
                goldfish.saved_result(bad, self.dir)

    def test_old_results_are_pruned(self):
        with mock.patch.object(goldfish.runs, "CACHE_MAX_FILES", 2):
            for seed in (1, 2, 3):
                self.run_cached(seed=seed)
        self.assertEqual(len(list(self.dir.glob("*.json"))), 2)

    def test_saved_flag(self):
        first = self.run_cached()
        self.assertEqual((first["cached"], first["saved"]), (False, True))
        again = self.run_cached()
        self.assertEqual((again["cached"], again["saved"]), (True, True))
        self.assertNotIn("saved", json.loads((self.dir / f"{first['cache_key']}.json").read_text(encoding="utf-8")))

    def test_a_result_that_cannot_be_saved_is_still_returned(self):
        # Review finding: a data folder that can't be written threw the finished result away.
        blocked = self.dir / "goldfish"
        blocked.write_text("a file where the folder should be", encoding="utf-8")
        logs = []
        with mock.patch.object(goldfish.runs, "_log", logs.append):
            result = self.run_cached(cache_dir=blocked)
        self.assertEqual((result["cached"], result["saved"]), (False, False))
        self.assertIn("play", result["results"])
        self.assertTrue(result["warnings"][-1].startswith("This result couldn't be saved on the PC ("))
        self.assertTrue(result["warnings"][-1].endswith("), so it will be worked out again next time."))
        self.assertNotIn(str(self.dir), result["warnings"][-1])
        self.assertEqual(len(logs), 1)
        self.assertIn("couldn't be saved", logs[0])
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["goldfish"])     # no .tmp left


# ----------------------------------------------------------- command line

class TestCommandLine(unittest.TestCase):

    def run_main(self, argv):
        """(exit code, stdout, stderr) of goldfish.main(argv)."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = goldfish.main(argv)
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_near_certain_chances_are_not_printed_as_100(self):
        # Review finding: the summary printed 0.99971 as "100.0", which the page had stopped doing.
        pct = goldfish._pct
        self.assertEqual([pct(0.99971), pct(0.9994), pct(1.0), pct(0.0003), pct(0.0), pct(0.8563), pct(None)],
                         [">99.9", "99.9", "100.0", "<0.1", "0.0", "85.6", "-"])

    def test_a_pairing_id_with_its_halves_in_either_order(self):
        # Review finding: "pairing/elves+cats" (the page's own links use it) gave "No deck".
        pairing = {"id": "pairing/cats+elves", "kind": "casual", "versions": ["target"]}
        small = goldfish.simulate(parse(SMALL_DECK), "constructed", games=20, turns=4, seed=1, workers=1)
        with mock.patch.object(decks, "list_decks", return_value=[]), \
                mock.patch.object(decks, "beginner_box_pairings", return_value=[pairing]), \
                mock.patch.object(decks, "load_deck", return_value=parse(SMALL_DECK)) as load, \
                mock.patch.object(goldfish.runs, "get_or_simulate", return_value=small):
            code, out, _ = self.run_main(["pairing/elves+cats"])
            self.assertEqual(code, 0)
            self.assertEqual(load.call_args.args, ("pairing/cats+elves", "target"))
            self.assertTrue(out.startswith("pairing/elves+cats: 20 games per setup"), out)
            code, _, err = self.run_main(["pairing/elves+goblins"])
            self.assertEqual((code, err), (1, "No deck 'pairing/elves+goblins'\n"))

    def test_ctrl_c_says_stopped(self):
        # Review finding: Ctrl+C ended the command with a raw KeyboardInterrupt traceback.
        with mock.patch.object(goldfish.cli, "_main", side_effect=KeyboardInterrupt):
            code, out, err = self.run_main(["casual/gruul-ramp"])
        self.assertEqual((code, out, err), (130, "", "Stopped.\n"))


# ------------------------------------------------------------------ workers

CHILD = """
import multiprocessing, sys, time
sys.path.insert(0, sys.argv[1])
from decklab.lib import cards, decks, goldfish
cards.load(sys.argv[2])

def progress(done, total):
    print(" ".join(str(p.pid) for p in multiprocessing.active_children()), flush=True)
    time.sleep(120)         # killed here, with its workers mid-run

goldfish.simulate(decks.parse_decklist(sys.argv[3]), "constructed", games=400_000, workers=2, progress=progress)
"""


def _alive(pid):
    """Is process pid still running? (Never signals it: on Windows os.kill would end it.)"""
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)    # SYNCHRONIZE, QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102       # WAIT_TIMEOUT: still running
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class TestWorkers(unittest.TestCase):

    def test_workers_end_when_the_process_that_started_them_is_killed(self):
        # Review finding: taskkill /F on the server (not its tree) during a run left all 16 workers waiting
        # for work for ever. Here a process running a 2-worker simulation is killed on its own.
        root = str(Path(__file__).resolve().parents[2])
        index = str(test_goldfish._tmp / "index.json.gz")      # setUpModule sets test_goldfish._tmp
        child = subprocess.Popen([sys.executable, "-c", CHILD, root, index, SMALL_DECK],
                                 stdout=subprocess.PIPE, text=True)
        pids = []
        try:
            lines = []
            reader = threading.Thread(target=lambda: lines.append(child.stdout.readline()), daemon=True)
            reader.start()
            reader.join(60)
            pids = [int(p) for p in (lines[0] if lines else "").split()]
            self.assertEqual(len(pids), 2, lines)
            self.assertTrue(all(_alive(p) for p in pids))
            child.kill()                    # this process only, not its workers
            child.wait(10)
            deadline = time.monotonic() + 15
            while any(_alive(p) for p in pids) and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual([p for p in pids if _alive(p)], [])
        finally:
            child.kill()
            child.stdout.close()
            for p in pids:                  # never leave a worker behind, even if the test failed
                if _alive(p):
                    os.kill(p, signal.SIGTERM)


# ------------------------------------------------------------ patch targets

# Each name tests patch, and the goldfish module that defines and reads it.
PATCHED = {"CACHE_DIR": "runs", "CACHE_MAX_FILES": "runs", "CHUNK_GAMES": "runs", "GOLDFISH_VERSION": "runs",
           "_log": "runs", "default_workers": "runs", "get_or_simulate": "runs", "simulate": "runs",
           "_main": "cli"}


class TestPatchTargets(unittest.TestCase):

    def test_each_patched_name_has_one_binding(self):
        # A copy in another module (a from-import) or on the package would let a patch silently miss the code.
        folder = Path(goldfish.__file__).parent
        modules = [importlib.import_module(f"decklab.lib.goldfish.{p.stem}") for p in sorted(folder.glob("*.py"))
                   if p.stem not in ("__init__", "__main__")]
        self.assertEqual({n: m.__name__.rsplit(".", 1)[1] for n, m in goldfish._PATCHED.items()}, PATCHED)
        for name, owner in PATCHED.items():
            with self.subTest(name=name):
                self.assertEqual([m.__name__ for m in modules if name in vars(m)], [f"decklab.lib.goldfish.{owner}"])
                self.assertNotIn(name, vars(goldfish))
                self.assertIs(getattr(goldfish, name), getattr(getattr(goldfish, owner), name))

    def test_the_package_refuses_a_patch_of_them(self):
        for name in PATCHED:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError), mock.patch.object(goldfish, name, None):
                    pass
                with self.assertRaises(AttributeError):
                    setattr(goldfish, name, None)
                with self.assertRaises(AttributeError):
                    delattr(goldfish, name)


if __name__ == "__main__":
    unittest.main()
