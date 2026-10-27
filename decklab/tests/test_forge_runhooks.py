"""Tests for wave 3's run-loop hooks around saved results (forge-trial/sim-wave3-contract.md section
8, package R): runner.update_result (a change to a saved result under its matchup's lock) and
saved._is_result's wave 3 kinds (paired, experiment) and adaptive summaries. The run keywords
themselves are tested with the fake Forge in test_forge_pool.py.

Run from the repo root: python -m unittest decklab.tests.test_forge_runhooks
"""
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from decklab.lib.forge import common, runner, saved

KEY = "a" * 64


def v2_result(key=KEY, **more):
    """A small v2 result, in the shape runner._record_v2 saves."""
    side = {"card_sha": "1" * 64, "dck": "[Main]\n", "card_count": 1, "kind": "constructed", "cards": {},
            "seen_as": []}
    game = {"g": 0, "w": 0, "r": "win", "first": 0, "rounds": 5, "ms": 100}
    return {"key": key, "format": "Constructed", "run_version": 2, "updated": "2026-10-03T16:00:00",
            "engine": {"kind": "decklab"},
            "seeds": {"scheme": "s", "base": 1, "stream": "0" * 16, "seat_block": 25, "flip": 0}, "next_game": 1,
            "sides": [dict(side), dict(side, card_sha="2" * 64)], "runs": [{}],
            "batches": [{"n": 0, "first": 0, "games": [game], "casts": [{}, {}], "lands": [{}, {}]}], "failed": [],
            **more}


PAIRED = {"base_key": "b" * 64, "base_side": 0, "variant_side": 1,
          "variant": {"card_sha": "3" * 64, "dck_sha": "4" * 64, "aligned_to": "1" * 64,
                      "changes": {"remove": [[1, "Fiery Annihilation"]], "add": [[1, "Rabid Gnaw"]]}}}


class IsResultTests(unittest.TestCase):

    def test_a_matchup_and_its_adaptive_summaries(self):
        self.assertTrue(saved._is_result(v2_result(), KEY))
        self.assertTrue(saved._is_result(v2_result(adaptive=[{"mode": "assess", "outcome": "precise"}]), KEY))
        self.assertFalse(saved._is_result(v2_result(adaptive={"mode": "assess"}), KEY))
        self.assertFalse(saved._is_result(v2_result(adaptive=["assess"]), KEY))
        self.assertFalse(saved._is_result(v2_result(adaptive=None), KEY))

    def test_a_paired_result_needs_its_block(self):
        self.assertTrue(saved._is_result(v2_result(kind="paired", paired_version=1, paired=PAIRED), KEY))
        self.assertFalse(saved._is_result(v2_result(kind="paired"), KEY))
        for bad in ({**PAIRED, "base_key": "B" * 64}, {**PAIRED, "base_side": 2}, {**PAIRED, "variant_side": True},
                    {**PAIRED, "variant": None}, "paired"):
            with self.subTest(bad=bad):
                self.assertFalse(saved._is_result(v2_result(kind="paired", paired=bad), KEY))
        # A paired result is always of the v2 engine.
        plain = v2_result(kind="paired", paired=PAIRED)
        del plain["seeds"], plain["engine"]
        self.assertFalse(saved._is_result(plain, KEY))

    def test_an_experiment_result_and_unknown_kinds(self):
        self.assertTrue(saved._is_result(v2_result(kind="experiment"), KEY))
        self.assertTrue(saved._is_result(v2_result(kind="experiment", experiment={"name": "m4", "arm": "fiery",
                                                                                  "control_key": "c" * 64}), KEY))
        self.assertFalse(saved._is_result(v2_result(kind="experiment", experiment="m4"), KEY))
        self.assertFalse(saved._is_result(v2_result(kind="future"), KEY))
        self.assertFalse(saved._is_result(v2_result(kind=None), KEY))



def assert_lock_given_up(case, folder, key=KEY):
    """The matchup's lock was given up: on Windows its file is gone (runner._release); elsewhere
    the 0-byte file stays, and a new claim gets the lock at once."""
    path = folder / f"{key}.lock"
    if sys.platform == "win32":
        case.assertFalse(path.exists())
    else:
        runner._release(runner._claim(folder, key), path)

class UpdateResultTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saved._read_cache.clear()
        self.addCleanup(saved._read_cache.clear)

    def write(self, result, folder=None):
        folder = folder or self.tmp
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{result['key']}.json").write_text(json.dumps(result), encoding="utf-8")

    def read(self, folder=None):
        return json.loads(((folder or self.tmp) / f"{KEY}.json").read_text(encoding="utf-8"))

    def test_it_applies_the_change_and_writes_it(self):
        self.write(v2_result())

        def add(result):
            result.setdefault("adaptive", []).append({"mode": "ahead", "outcome": "about_even"})

        out = runner.update_result(KEY, self.tmp, add)
        self.assertEqual(out["adaptive"], [{"mode": "ahead", "outcome": "about_even"}])
        self.assertEqual(self.read()["adaptive"], out["adaptive"])
        self.assertTrue(saved._is_result(self.read(), KEY))
        # A function may return the new result instead.
        out = runner.update_result(KEY, self.tmp, lambda result: dict(result, adaptive=[]))
        self.assertEqual((out["adaptive"], self.read()["adaptive"]), ([], []))
        assert_lock_given_up(self, self.tmp)

    def test_no_result_no_change(self):
        called = []
        self.assertIsNone(runner.update_result(KEY, self.tmp, called.append))
        self.assertEqual(called, [])
        with self.assertRaises(ValueError):
            runner.update_result("../x", self.tmp, called.append)

    def test_a_paired_result(self):
        self.write(v2_result(kind="paired", paired=PAIRED), self.tmp / runner.PAIRED_FOLDER)
        out = runner.update_result(KEY, self.tmp, lambda r: r.update(note=1), paired=True)
        self.assertEqual(out["note"], 1)
        self.assertEqual(self.read(self.tmp / runner.PAIRED_FOLDER)["note"], 1)
        self.assertIsNone(runner.update_result(KEY, self.tmp, lambda r: r.update(note=2)))      # not a matchup's

    def test_it_waits_for_the_lock_and_then_gives_up(self):
        self.write(v2_result())
        lock = runner._claim(self.tmp, KEY)
        released = threading.Event()

        def release():
            time.sleep(0.6)
            runner._release(lock, self.tmp / f"{KEY}.lock")
            released.set()

        threading.Thread(target=release, daemon=True).start()
        started = time.monotonic()
        out = runner.update_result(KEY, self.tmp, lambda r: r.update(note="after"))
        self.assertTrue(released.is_set())
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertEqual(out["note"], "after")
        lock = runner._claim(self.tmp, KEY)
        self.addCleanup(runner._release, lock, self.tmp / f"{KEY}.lock")
        with mock.patch.object(runner, "UPDATE_WAIT_S", 0.3), self.assertRaises(common.ForgeError) as caught:
            runner.update_result(KEY, self.tmp, lambda r: r.update(note="never"))
        self.assertEqual(str(caught.exception), runner.BUSY)
        self.assertEqual(self.read()["note"], "after")

    def test_a_write_that_fails(self):
        self.write(v2_result())
        before = deepcopy(self.read())
        with mock.patch.object(common, "_write_atomic", side_effect=OSError("disk full")), \
                mock.patch.object(common, "_log"), self.assertRaises(common.ForgeError) as caught:
            runner.update_result(KEY, self.tmp, lambda r: r.update(note=1))
        self.assertEqual(str(caught.exception), runner.NOT_SAVED)
        self.assertEqual(self.read(), before)
        assert_lock_given_up(self, self.tmp)


if __name__ == "__main__":
    unittest.main()
