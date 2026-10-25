"""Crash and restart tests with a synthetic pool; never start Java or a live server."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.lib.forge import checkpoints, common, engine, pool, runner, saved
from decklab.tests.test_forge_runhooks import KEY, PAIRED

ENG = {"kind": "decklab", "fixture": "checkpoint-test"}
ENTRIES = [{"card_sha": str(i) * 64, "dck": f"[Main]\n1 Fixture {i}\n", "card_count": 1,
            "kind": "constructed", "cards": {}, "seen_as": [], "sections": {}} for i in (1, 2)]


def game(number):
    return {"g": number, "w": number % 2, "r": "win", "first": 0, "rounds": 5, "ms": 100}


def fixture_run(folder, *, crash=False, drop=False, kind=None, numbers=None, save=True, eng=None,
                entries=None, fail_save=False, inspect=None):
    """Exercise the real claim, number planner, event collector, record merger and writer."""
    folder = Path(folder)
    entries = deepcopy(entries or ENTRIES)
    eng = eng or ENG
    hooks = {"numbers": numbers, "seeds": {"base": 17, "stream": "0123456789abcdef", "flip": 1},
             "kind": kind, "extra": {"paired": PAIRED} if kind == "paired" else {}, "log": None}
    setup = {"version": "fixture", "clock_s": 1, "xmx": "64m", "user_dir": folder / "user"}
    games = len(numbers) if numbers is not None else 100 if crash else 2

    class Events:
        def __init__(self, job):
            self.events = []
            first = job["ranges"][0][0]
            starts = [first, first + 25, first + 50] if crash else [first]
            for i, start in enumerate(starts):
                self.events.append(("start", i, start, 2, 0))
                for number in range(start, start + 2):
                    self.events.append(("game", i, game(number), [{"Fixture": [1, 1]}, {}], [{}, {}], None))
                self.events.append(("end", i, {"wall_s": 0.1, "drop": bool(drop and i == 1)}))
            if crash:
                # A game in a chunk without its validating end must not survive.
                self.events += [("start", 9, first + 75, 2, 0),
                                ("game", 9, game(first + 75), [{}, {}], [{}, {}], None), ("crash",)]
            else:
                self.events.append(("done", "finished"))

        def get(self, timeout=None):
            event = self.events.pop(0)
            if inspect:
                inspect(event)
            if event[0] == "crash":
                os._exit(77)  # bypass every except/finally exactly as abrupt process death does
            return event

        def get_nowait(self):
            if not self.events:
                raise queue.Empty
            return self.get()

    def place(job, **kwargs):
        return SimpleNamespace(ticket=SimpleNamespace(events=Events(job), stop=lambda: None), where="remote",
                               xmx="64m", close=lambda *a: None)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(engine, "result_fields", side_effect=lambda e, *a: {"engine": e}))
        stack.enter_context(mock.patch.object(engine, "side_fields", return_value={}))
        stack.enter_context(mock.patch.object(engine, "played_pilot", return_value={"profile": "Default", "switches": []}))
        stack.enter_context(mock.patch.object(runner, "_side", side_effect=deepcopy))
        stack.enter_context(mock.patch.object(runner, "_seen", return_value=None))
        stack.enter_context(mock.patch.object(runner, "_list_lines", return_value=[]))
        stack.enter_context(mock.patch.object(runner, "_log_names", return_value={}))
        stack.enter_context(mock.patch.object(pool, "place", side_effect=place))
        stack.enter_context(mock.patch.object(checkpoints, "SECONDS", 0))
        if fail_save:
            stack.enter_context(mock.patch.object(common, "_write_atomic", side_effect=OSError("disk full")))
        lock = runner._claim(folder, KEY) if save else None
        try:
            return runner._run(setup, KEY, eng, "Constructed", *entries, entries, games, "Test", None,
                               folder, folder, 1, 25, None, False, save, {}, exact=True, hooks=hooks)
        finally:
            if lock is not None:
                runner._release(lock, folder / f"{KEY}.lock")


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        saved._read_cache.clear()
        self.addCleanup(saved._read_cache.clear)

    def crash(self, kind=None, drop=True):
        code = ("from decklab.tests.test_forge_checkpoints import fixture_run; "
                f"fixture_run({str(self.folder)!r}, crash=True, drop={drop!r}, kind={kind!r})")
        process = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 77, process.stderr)
        result = saved.load(KEY, self.folder)
        self.assertIsNotNone(result)
        return result

    def numbers(self, result):
        return [g["g"] for batch in result["batches"] for g in batch["games"]]

    def test_hard_crash_keeps_validated_chunks_but_not_dropped_or_unfinished_ones(self):
        result = self.crash()
        self.assertEqual(self.numbers(result), [0, 1, 50, 51])
        self.assertEqual(result["next_game"], 100)
        self.assertEqual(len(result["runs"]), 1)
        self.assertTrue(result["runs"][0]["checkpoint"])
        self.assertTrue(result["runs"][0]["stopped"])
        self.assertEqual(result["batches"][0]["casts"][0]["Fixture"], [4, 4])
        self.assertEqual(result["engine"], ENG)
        self.assertEqual(result["seeds"]["base"], 17)
        self.assertEqual(result["seeds"]["stream"], "0123456789abcdef")
        self.assertEqual(result["seeds"]["flip"], 1)

    def test_restart_preserves_reserved_holes_and_does_not_duplicate_checkpoint_runs(self):
        self.crash(drop=False)
        result = fixture_run(self.folder)
        self.assertEqual(self.numbers(result), [0, 1, 25, 26, 50, 51, 100, 101])
        self.assertEqual([r["played"] for r in result["runs"]], [6, 2])
        self.assertEqual([b["n"] for b in result["batches"]], [0, 1])
        self.assertTrue(result["runs"][0]["recovered"])
        self.assertFalse(any(r.get("checkpoint") for r in result["runs"]))
        with self.assertRaises(ValueError):
            fixture_run(self.folder, numbers=[25, 26])
        self.assertEqual(saved.load(KEY, self.folder), result)

    def test_paired_recovery_can_fill_missing_games_but_never_duplicate_saved_games(self):
        self.crash(kind="paired")
        result = fixture_run(self.folder, kind="paired", numbers=[25, 26])
        self.assertEqual(sorted(self.numbers(result)), [0, 1, 25, 26, 50, 51])
        self.assertEqual(result["next_game"], 100)
        self.assertEqual(result["paired"], PAIRED)
        with self.assertRaises(ValueError):
            fixture_run(self.folder, kind="paired", numbers=[25, 26])

    def test_recovery_refuses_wrong_engine_and_list_without_changing_checkpoint(self):
        self.crash()
        before = (self.folder / f"{KEY}.json").read_bytes()
        changed = deepcopy(ENTRIES)
        changed[0]["dck"] += "1 Different\n"
        for kwargs in ({"eng": {**ENG, "fixture": "different"}}, {"entries": changed}):
            with self.subTest(kwargs=kwargs), self.assertRaises(common.ForgeError):
                fixture_run(self.folder, **kwargs)
            self.assertEqual((self.folder / f"{KEY}.json").read_bytes(), before)

    def test_disk_failure_keeps_old_checkpoint_and_refuses_to_start(self):
        self.crash()
        before = (self.folder / f"{KEY}.json").read_bytes()
        with mock.patch.object(common, "_log"), self.assertRaisesRegex(common.ForgeError, "checkpoint"):
            fixture_run(self.folder, fail_save=True)
        self.assertEqual((self.folder / f"{KEY}.json").read_bytes(), before)

    def test_success_replaces_checkpoint_without_extra_batches_and_keeps_claim(self):
        snapshots = []
        def inspect(event):
            snapshot = saved.load(KEY, self.folder)
            snapshots.append(snapshot)
            with self.assertRaisesRegex(common.ForgeError, "already being played"):
                runner._claim(self.folder, KEY)
        result = fixture_run(self.folder, inspect=inspect)
        self.assertEqual(self.numbers(result), [0, 1])
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(len(result["batches"]), 1)
        self.assertFalse(result["runs"][0].get("checkpoint"))
        self.assertEqual(snapshots[0]["next_game"], 2)
        self.assertEqual(snapshots[0]["batches"], [])
        self.assertEqual(snapshots[-1]["runs"][0]["played"], 2)

    def test_unsaved_runs_do_not_create_checkpoints(self):
        result = fixture_run(self.folder, save=False)
        self.assertEqual(len(self.numbers(result)), 2)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_midrun_disk_failure_reports_failure_and_keeps_last_durable_state(self):
        for fail_after, kept in ((1, []), (2, [0, 1])):
            with self.subTest(fail_after=fail_after):
                path = self.folder / f"{KEY}.json"
                path.unlink(missing_ok=True)
                saved._read_cache.clear()
                write = common._write_atomic
                calls = 0
                def failing(path, text):
                    nonlocal calls
                    calls += 1
                    if calls > fail_after:
                        raise OSError("disk full")
                    return write(path, text)
                with mock.patch.object(common, "_write_atomic", side_effect=failing), \
                        mock.patch.object(common, "_log"), self.assertRaises(common.ForgeError):
                    fixture_run(self.folder)
                result = saved.load(KEY, self.folder)
                self.assertEqual(self.numbers(result), kept)
                self.assertTrue(result["runs"][0]["checkpoint"])
                self.assertEqual(result["next_game"], 2)

    def test_checkpoint_throttle_does_not_recount_games_between_writes(self):
        writer = checkpoints.Writer(self.folder / "unused", lambda *args: None)
        snapshot = mock.Mock(return_value=({"games": [{"g": 0}]}, [], {}))
        with mock.patch.object(writer, "_write") as write, \
                mock.patch.object(checkpoints.time, "monotonic", side_effect=[0, 1, 2, 6]):
            writer.publish(1, snapshot)
            writer.publish(1, snapshot)
            writer.publish(2, snapshot)
            writer.publish(3, snapshot)
        self.assertEqual(snapshot.call_count, 2)
        self.assertEqual(write.call_count, 2)


if __name__ == "__main__":
    unittest.main()
