"""Tests for the PC's budget of Forge processes (decklab/lib/forge/slots.py) and its users:
slots as OS locks (the lowest free ids, the budget, waiting, cancelling, a process that dies
holding slots, status), runs that start a process only in a free slot and say when they're
waiting for one (runner._play), cardlog-check's slots and the "slots" command (cli.py),
Forge's processes at below normal priority (processes.py), and practice hands, which never
wait for a Forge run.

Every test points DECKLAB_FORGE_SLOTS at a folder of its own (the test package already
points it away from the PC's real one: decklab/tests/__init__.py). The runs use the fake
Forge of test_forge.py, whose setUpModule and tearDownModule these tests share.

Run from the repo root: python -m unittest decklab.tests.test_forge_slots
"""
import _thread
import gc
import io
import json
import os
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

from decklab import tests as test_package
from decklab.lib import config, forge, goldfish, jobs
from decklab.lib.forge import cli, slots
from decklab.tests import test_forge
from decklab.tests.test_forge import GREEN, RED, entry, sections


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


def wait_for(check, seconds=10, step=0.05):
    """Wait until check() is true (True), or seconds pass (False)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(step)
    return bool(check())


class SlotFolder:
    """Mixin: a slots folder of the test's own (DECKLAB_FORGE_SLOTS) as self.slots_dir."""

    def use_own_slots(self):
        self.slots_dir = Path(tempfile.mkdtemp(prefix="decklab-slots-"))
        self.addCleanup(shutil.rmtree, self.slots_dir, ignore_errors=True)
        env = mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir)})
        env.start()
        self.addCleanup(env.stop)

    def hold(self, n, budget, what="another run"):
        """Slots held by "another run" (released when the test ends)."""
        lease = slots.claim(n, budget, wait=False, what=what)
        self.addCleanup(lease.release)
        return lease

    def held_by(self, budget, what_prefix):
        """How many slots are held by claims whose what starts with what_prefix."""
        return sum(1 for row in slots.status(budget)["slots"]
                   if row["held"] and (row["what"] or "").startswith(what_prefix))


# ============================================================ the slots themselves

class SlotTests(SlotFolder, unittest.TestCase):

    def setUp(self):
        self.use_own_slots()

    def test_the_folder_is_shared_by_every_checkout_and_can_be_named(self):
        self.assertEqual(slots.folder(), self.slots_dir)
        with mock.patch.dict(os.environ, {}):
            del os.environ[slots.ENV]
            real = slots.folder()           # only worked out: nothing is made
            os.environ["LOCALAPPDATA"] = str(self.slots_dir / "local")
            self.assertEqual(slots.folder(), self.slots_dir / "local" / "DeckLab" / "forge-slots")
        # The user's own folder, never a checkout's (another worktree wouldn't see it there).
        self.assertEqual(real.parts[-2:], ("DeckLab", "forge-slots"))
        self.assertNotIn(config.REPO, real.parents)

    def test_tests_never_use_the_pcs_real_slots(self):
        # decklab/tests/__init__.py points every test, and every process a test starts, at a
        # temporary folder of the test run's own.
        named = Path(test_package._SLOTS)
        with mock.patch.dict(os.environ, {}):
            del os.environ[slots.ENV]
            real = slots.folder()
        self.assertNotEqual(named, real)
        self.assertIn(Path(tempfile.gettempdir()).resolve(), named.resolve().parents)

    def test_claims_take_the_lowest_free_ids_within_the_budget(self):
        a = slots.claim(2, 4)
        self.assertEqual(a.ids, [0, 1])
        b = slots.claim(5, 4)                       # more than are free: the rest
        self.assertEqual(b.ids, [2, 3])
        none = slots.claim(1, 4, wait=False)
        self.assertEqual((none.ids, len(none), bool(none)), ([], 0, False))
        a.release(0)
        self.assertEqual(slots.claim(3, 4, wait=False).ids, [0])     # (released again when it's dropped)
        a.release()
        b.release()
        whole = slots.claim(4, 4)
        self.assertEqual((whole.ids, len(whole), bool(whole)), ([0, 1, 2, 3], 4, True))
        whole.release()
        for bad in ((0, 4), (1, 0), (-1, 4)):
            with self.assertRaises(ValueError):
                slots.claim(*bad)

    def test_a_claim_can_prefer_the_id_it_had(self):
        # A warm worker takes back its slot, and so its core (pool.py), when it's free.
        held = self.hold(1, 4)
        lease = slots.claim(1, 4, wait=False, prefer=2)
        self.assertEqual(lease.ids, [2])
        self.assertEqual(slots.claim(1, 4, wait=False, prefer=2).ids, [1])     # taken: the lowest free
        lease.release()
        self.assertEqual(slots.claim(1, 4, wait=False, prefer=held.ids[0]).ids, [1])
        for odd in (None, 9, -1, True):                     # not an id of the budget's: the lowest free
            with self.subTest(prefer=odd):
                self.assertEqual(slots.claim(1, 4, wait=False, prefer=odd).ids, [1])

    def test_a_smaller_budget_uses_only_the_first_slots(self):
        held = self.hold(3, 8)
        self.assertEqual(held.ids, [0, 1, 2])
        self.assertEqual(slots.claim(4, 2, wait=False).ids, [])    # a checkout set to 2 has none free
        self.assertEqual(slots.claim(1, 8, wait=False).ids, [3])

    def test_the_worker_limit_caps_every_budget(self):
        self.assertIsNone(slots.limit())
        slots.set_limit(2)
        self.addCleanup(slots.set_limit, None)
        self.assertEqual(slots.limit(), 2)
        lease = slots.claim(5, 8, wait=False)
        self.assertEqual(lease.ids, [0, 1])
        self.assertEqual(slots.claim(1, 8, wait=False).ids, [])
        self.assertEqual((slots.status(8)["budget"], slots.status(8)["limit"]), (8, 2))
        slots.set_limit(3)                  # read on every claim: a raise frees one more at once
        self.assertEqual(slots.claim(1, 8, wait=False).ids, [2])
        lease.release()
        slots.set_limit(None)
        self.assertIsNone(slots.limit())
        slots.set_limit(None)               # clearing twice is fine
        (self.slots_dir / slots.LIMIT_FILE).write_text("not json", encoding="utf-8")
        self.assertIsNone(slots.limit())    # a broken file limits nothing
        for bad in (0, -1, 1.5, "2", True):
            with self.subTest(n=bad), self.assertRaises(ValueError):
                slots.set_limit(bad)

    def test_a_waiting_claim_follows_a_raised_limit(self):
        slots.set_limit(1)
        self.addCleanup(slots.set_limit, None)
        held = self.hold(1, 4)
        got = []
        thread = threading.Thread(target=lambda: got.append(slots.claim(1, 4, poll=0.02)))
        thread.start()
        time.sleep(0.1)
        self.assertEqual(got, [])
        slots.set_limit(2)
        thread.join(5)
        self.assertEqual(got[0].ids, [1])
        got[0].release()
        held.release()

    def test_the_budget_defaults_to_forge_workers(self):
        with mock.patch.object(forge.common, "_settings", lambda: {"forge_workers": 3}):
            lease = slots.claim(10)
            self.assertEqual(lease.ids, [0, 1, 2])
            self.assertEqual(slots.status()["budget"], 3)
            lease.release()

    def test_release_with_and_dropping(self):
        with slots.claim(2, 2) as lease:
            self.assertEqual(lease.ids, [0, 1])
            self.assertEqual(slots.claim(1, 2, wait=False).ids, [])
            lease.release(1)
            lease.release(1)                # again: nothing
            lease.release(7)                # not held: nothing
            self.assertEqual(lease.ids, [0])
            other = slots.claim(1, 2, wait=False)
            self.assertEqual(other.ids, [1])
            other.release()
        self.assertEqual(lease.ids, [])
        lease.release()                     # again: nothing
        dropped = slots.claim(2, 2)
        self.assertEqual(dropped.ids, [0, 1])
        del dropped
        gc.collect()
        again = slots.claim(2, 2, wait=False)
        self.assertEqual(again.ids, [0, 1])
        again.release()
        self.assertEqual(repr(again), "<slots.Lease []>")

    def test_a_waiting_claim_gets_the_first_slot_freed(self):
        held = self.hold(2, 2)
        waits = []
        timer = threading.Timer(0.6, held.release, args=(1,))
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        lease = slots.claim(2, 2, waiting=lambda: waits.append(time.monotonic()), poll=0.05)
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertEqual(lease.ids, [1])            # only the one that was freed
        self.assertGreaterEqual(len(waits), 2)      # called before each wait
        lease.release()

    def test_cancel_and_waiting_end_a_wait_holding_nothing(self):
        held = self.hold(1, 1)
        cancel = threading.Event()
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        with self.assertRaises(slots.Cancelled):
            slots.claim(1, 1, cancel=cancel, poll=30)          # the cancel wakes it at once
        self.assertLess(time.monotonic() - started, 5)
        with self.assertRaises(slots.Cancelled):
            slots.claim(1, 1, cancel=cancel)                   # already set

        def stop():
            raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            slots.claim(1, 1, waiting=stop)
        held.release()
        self.assertEqual(slots.claim(1, 1, wait=False).ids, [0])     # nothing was left held
        # With a free slot, neither matters.
        self.assertEqual(slots.claim(1, 1, cancel=cancel, waiting=stop).ids, [0])

    def test_a_waiting_claim_says_it_waits_until_it_has_a_slot(self):
        # So a pool that frees a slot leaves it for this claim (pool.HANDOFF_S) instead of taking it back.
        held = self.hold(1, 1)
        got = {}
        thread = threading.Thread(target=lambda: got.update(lease=slots.claim(1, 1, poll=0.05, what="a check")))
        thread.start()
        self.addCleanup(thread.join, 10)
        self.assertTrue(wait_for(lambda: slots.waiting() == 1, 10))
        self.assertEqual(slots.status(1)["budget"], 1)          # a want isn't a slot
        held.release()
        thread.join(10)
        self.assertEqual(got["lease"].ids, [0])
        self.assertEqual((slots.waiting(), list(self.slots_dir.glob(slots.WANT_GLOB))), (0, []))
        got["lease"].release()
        # Nor is one left behind by a wait that's stopped, or a claim that never waited.
        held = self.hold(1, 1)
        seen = []

        def stop():
            seen.append(slots.waiting())
            raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            slots.claim(1, 1, waiting=stop)
        self.assertEqual(seen, [1])
        held.release()
        slots.claim(1, 1, wait=False).release()
        self.assertEqual((slots.waiting(), list(self.slots_dir.glob(slots.WANT_GLOB))), (0, []))

    def test_wants_leave_out_the_askers_own_and_go_with_their_process(self):
        mine, other = slots.want("a pool"), slots.want("another pool")
        self.assertEqual((slots.waiting(), slots.waiting(exclude=mine), slots.waiting(exclude=other)), (2, 1, 1))
        other.release()
        other.release()                                         # (again: nothing)
        self.assertEqual((slots.waiting(), slots.waiting(exclude=mine)), (1, 0))
        mine.release()
        self.assertEqual(slots.waiting(), 0)
        # Another process's want counts until the process ends, however it ends; its file is then deleted.
        helper = subprocess.Popen(
            [sys.executable, "-c", "import time; from decklab.lib.forge import slots;"
                                   "w = slots.want('a run elsewhere'); print(w.path, flush=True); time.sleep(60)"],
            cwd=config.REPO, stdout=subprocess.PIPE, text=True)
        self.addCleanup(helper.stdout.close)
        self.addCleanup(helper.kill)
        path = Path(helper.stdout.readline().strip())
        self.assertEqual((path.parent, slots.waiting()), (self.slots_dir, 1))
        helper.kill()
        helper.wait()
        self.assertTrue(wait_for(lambda: slots.waiting() == 0, 10))
        self.assertFalse(path.exists())
        # A folder that can't be read has none.
        with mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir / "never")}):
            self.assertEqual(slots.waiting(), 0)

    def test_status_says_who_holds_each_slot(self):
        self.assertEqual(slots.status(2)["slots"], [
            {"id": 0, "held": False, "pid": None, "what": None, "since": None, "checkout": None},
            {"id": 1, "held": False, "pid": None, "what": None, "since": None, "checkout": None}])
        self.hold(2, 3, what="matchup 0123456789ab")
        found = slots.status(3)
        self.assertEqual((found["folder"], found["budget"]), (str(self.slots_dir), 3))
        rows = found["slots"]
        self.assertEqual([(r["id"], r["held"]) for r in rows], [(0, True), (1, True), (2, False)])
        self.assertEqual({(r["pid"], r["what"], r["checkout"]) for r in rows[:2]},
                         {(os.getpid(), "matchup 0123456789ab", str(config.REPO))})
        self.assertTrue(rows[0]["since"])
        # A slot held above this budget (another checkout's bigger one) is listed too; free ones aren't.
        self.assertEqual([(r["id"], r["held"]) for r in slots.status(1)["slots"]], [(0, True), (1, True)])
        self.assertEqual(slots.claim(1, 3, wait=False).ids, [2])        # status gave every free slot back

    def test_status_of_a_folder_never_used_makes_nothing(self):
        with mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir / "never")}):
            self.assertEqual([r["held"] for r in slots.status(2)["slots"]], [False, False])
        self.assertFalse((self.slots_dir / "never").exists())

    def test_a_folder_that_cant_be_made_is_an_oserror(self):
        (self.slots_dir / "a file").write_text("not a folder", encoding="utf-8")
        with mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir / "a file" / "slots")}):
            with self.assertRaises(OSError):
                slots.claim(1, 2)

    def test_another_process_holds_slots_until_it_dies(self):
        # The lock is the OS's: a hard kill (TerminateProcess, as taskkill /F) gives the slots back.
        helper = subprocess.Popen(
            [sys.executable, "-c",
             "import time; from decklab.lib.forge import slots;"
             "lease = slots.claim(2, 3, what='a run elsewhere'); print(lease.ids, flush=True); time.sleep(60)"],
            cwd=config.REPO, stdout=subprocess.PIPE, text=True)
        self.addCleanup(helper.stdout.close)
        self.addCleanup(helper.kill)
        self.assertEqual(helper.stdout.readline().strip(), "[0, 1]")
        mine = slots.claim(3, 3, wait=False)
        self.assertEqual(mine.ids, [2])
        held = [r for r in slots.status(3)["slots"] if r["id"] < 2]
        self.assertEqual({(r["held"], r["pid"], r["what"]) for r in held}, {(True, helper.pid, "a run elsewhere")})
        helper.kill()
        helper.wait()
        got = []
        self.assertTrue(wait_for(lambda: got.extend(slots.claim(2, 3, wait=False).ids) or len(got) == 2, 10), got)
        self.assertEqual(sorted(got), [0, 1])
        mine.release()


# ============================================================ runs (runner._play)

class RunSlotTests(SlotFolder, test_forge.ForgeCase):
    """Runs with the fake Forge; config.json's forge_workers (the budget) is 4."""

    def setUp(self):
        super().setUp()
        self.settings["forge_workers"] = 4          # ForgeCase's is 2 (its 200-game runs are 2 x 100)
        self.use_own_slots()

    def run_matchup(self, games=40, **kwargs):
        kwargs.setdefault("results_dir", self.results)
        kwargs.setdefault("batch", 10)
        kwargs.setdefault("workers", 4)
        return forge.run(entry(GREEN, "casual/green"), entry(RED, "casual/red"), games, by="Matt", **kwargs)

    def saved(self):
        return test_forge.load_json(next(self.results.glob("*.json")))

    def in_background(self, **kwargs):
        """run_matchup in a thread: (the thread, out), out["result"] being its result or exception."""
        out = {}

        def go():
            try:
                out["result"] = self.run_matchup(**kwargs)
            except BaseException as e:
                out["result"] = e

        thread = threading.Thread(target=go, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 60)
        return thread, out

    def test_each_process_holds_a_slot_while_it_runs(self):
        self.fake("delay=0.1")
        seen = []
        result = self.run_matchup(progress=lambda done, total, detail: seen.append(
            (self.held_by(4, "matchup "), detail["waiting"])))
        self.assertEqual(sum(len(b["games"]) for b in result["batches"]), 40)
        self.assertEqual(max(n for n, _ in seen), 4)
        self.assertEqual({w for _, w in seen}, {None})          # never waiting
        rows = [r for r in slots.status(4)["slots"]]
        self.assertFalse(any(r["held"] for r in rows))          # all given back
        key = result["key"]
        self.fake("delay=0.05")
        whats = set()
        self.run_matchup(results_dir=self.tmp / "again", progress=lambda *a: whats.update(
            r["what"] for r in slots.status(4)["slots"] if r["held"]))
        self.assertEqual(whats, {f"matchup {key[:12]}"})

    def test_a_run_starts_as_many_processes_as_it_gets_slots(self):
        self.hold(3, 4)
        self.fake("delay=0.02")
        most = []
        result = self.run_matchup(progress=lambda *a: most.append(self.held_by(4, "matchup ")))
        # One slot free: one process at a time. Progress may be read after a batch gave its slot
        # back (a runner's slow scheduling), so 0 is fine; the start times below show the order.
        self.assertLessEqual(max(most), 1)
        self.assertEqual(len(result["batches"]), 4)
        self.assertEqual(sum(len(b["games"]) for b in result["batches"]), 40)
        times = sorted(t for _, _, t in self.starts())
        self.assertEqual(len(times), 4)
        self.assertGreater(min(b - a for a, b in zip(times, times[1:])), 0.15)     # one after another

    def test_a_run_waits_while_every_slot_is_taken_and_says_so(self):
        outside = self.hold(4, 4)
        self.fake("delay=0.01")
        details = []
        thread, out = self.in_background(progress=lambda done, total, detail: details.append(detail))
        self.assertTrue(wait_for(lambda: any(d["waiting"] for d in details), 10))
        self.assertEqual(details[-1]["waiting"], slots.WAITING)
        self.assertEqual(self.starts(), [])             # nothing started while it waits
        self.assertEqual(slots.waiting(), 1)            # and it says it waits, so pools leave it a slot they free
        outside.release()
        thread.join(60)
        self.assertNotIsInstance(out["result"], BaseException)
        self.assertEqual(out["result"]["runs"][0]["played"], 40)
        self.assertIsNone(details[-1]["waiting"])
        self.assertEqual(slots.waiting(), 0)
        self.assertFalse(any(r["held"] for r in slots.status(4)["slots"]))

    def test_a_stop_while_waiting_stops_the_run(self):
        self.hold(4, 4)

        def progress(done, total, detail):
            if detail["waiting"]:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(progress=progress)
        run = self.saved()["runs"][0]
        self.assertEqual((run["played"], run["stopped"], run["failed"], run["error"]), (0, True, 0, None))
        self.assertEqual(self.starts(), [])

    def test_ctrl_c_while_waiting_stops_the_run(self):
        self.hold(4, 4)
        timer = threading.Timer(0.8, _thread.interrupt_main)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.run_matchup()
        self.assertEqual(getattr(caught.exception, "saved_games", None), 0)
        self.assertTrue(self.saved()["runs"][0]["stopped"])
        self.assertEqual(self.starts(), [])

    def test_a_run_takes_slots_other_runs_give_up(self):
        outside = self.hold(4, 4)
        self.fake("delay=0.25")         # 2.5 s a batch
        thread, out = self.in_background()
        time.sleep(0.6)
        outside.release(0)
        outside.release(1)
        self.assertTrue(wait_for(lambda: len(self.starts()) == 2, 10))
        time.sleep(0.6)
        self.assertEqual(len(self.starts()), 2)         # two slots, two processes
        freed = time.time()
        outside.release()
        thread.join(60)
        self.assertNotIsInstance(out["result"], BaseException)
        times = sorted(t for _, _, t in self.starts())
        self.assertEqual(len(times), 4)
        self.assertGreaterEqual(times[2], freed - 0.05)
        self.assertLess(times[2] - freed, 3)            # within a try or two (SLOT_RETRY_S), and Python's start
        self.assertEqual(out["result"]["runs"][0]["played"], 40)

    def test_slots_are_given_back_after_failures_and_stops(self):
        def start(argv, cwd=None, env=None):
            raise FileNotFoundError(2, "The system cannot find the file specified")

        with mock.patch.object(forge.processes, "start_process", start), mock.patch.object(forge.common, "_log"), \
                self.assertRaises(forge.ForgeError):
            self.run_matchup()
        self.assertFalse(any(r["held"] for r in slots.status(4)["slots"]))
        self.fake("delay=0.02")

        def progress(done, total, detail):
            if done >= 5:
                raise jobs.Stopped("stop")

        with self.assertRaises(jobs.Stopped):
            self.run_matchup(results_dir=self.tmp / "stopped", progress=progress)
        self.assertFalse(any(r["held"] for r in slots.status(4)["slots"]))

    def test_the_budget_caps_more_workers_than_it_has(self):
        self.fake("delay=0.1")
        most = []
        self.run_matchup(80, workers=8, progress=lambda *a: most.append(self.held_by(8, "matchup ")))
        self.assertEqual(max(most), 4)          # config.json's forge_workers, whatever --workers asks
        self.assertEqual(len(self.starts()), 8)

    def test_unusable_slots_dont_stop_a_run(self):
        (self.slots_dir / "a file").write_text("not a folder", encoding="utf-8")
        with mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir / "a file" / "slots")}), \
                mock.patch.object(forge.common, "_log") as log:
            result = self.run_matchup()
        self.assertEqual(result["runs"][0]["played"], 40)
        said = [c.args[0] for c in log.call_args_list if "slots" in c.args[0]]
        self.assertEqual(len(said), 1)          # once a run
        self.assertIn("can't be used", said[0])

    def test_the_runs_numbers_leave_the_wait_out(self):
        outside = self.hold(4, 4)
        timer = threading.Timer(0.8, outside.release)
        timer.start()
        self.addCleanup(timer.cancel)
        self.fake("delay=0.05")
        with mock.patch.object(forge.runner, "_record", wraps=forge.runner._record) as record:
            started = time.monotonic()
            self.run_matchup()
            took = time.monotonic() - started
        stats = record.call_args.args[-1]
        self.assertGreaterEqual(stats["waited_s"], 0.6)
        self.assertEqual(stats["most_running"], 4)
        self.assertLessEqual(stats["wall_s"], round(took - stats["waited_s"], 1) + 0.2)     # from the first start
        # The run record keeps both ("workers" is the number it could have had at once).
        run = self.saved()["runs"][0]
        self.assertEqual((run["waited_s"], run["most_running"], run["wall_s"]),
                         (stats["waited_s"], 4, stats["wall_s"]))


# ============================================================ cardlog-check and the slots command

class CommandLineSlotTests(SlotFolder, test_forge.ForgeCase):
    """cardlog-check, play and the slots command; config.json's forge_workers (the budget) is 4."""

    def setUp(self):
        super().setUp()
        from decklab.lib import inventory
        from decklab.lib.inventory.files import FileInventory
        # Alias-aware CLI deck reads use a temporary backend, restored before folder cleanup.
        self.addCleanup(inventory.use(FileInventory(self.tmp)))
        self.settings["forge_workers"] = 4          # ForgeCase's is 2 (its 200-game runs are 2 x 100)
        self.use_own_slots()
        cli._said.clear()
        self.addCleanup(cli._said.clear)

    def run_main(self, *argv):
        """(exit code, stdout, stderr) of forge.main(argv)."""
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = forge.main(list(argv))
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_the_slots_command(self):
        code, out, _ = self.run_main("slots")
        self.assertEqual((code, out), (0, f"Forge processes on this PC: 0 of 4 slots in use ({self.slots_dir})\n"))
        self.hold(2, 4, what="matchup 0123456789ab")
        code, out, _ = self.run_main("slots")
        lines = out.splitlines()
        self.assertEqual(lines[0], f"Forge processes on this PC: 2 of 4 slots in use ({self.slots_dir})")
        self.assertRegex(lines[1], rf"^  slot 0: process {os.getpid()}, matchup 0123456789ab, since \S+, "
                                   + re.escape(str(config.REPO)) + "$")
        self.assertTrue(lines[2].startswith("  slot 1: "))
        found = json.loads(self.run_main("slots", "--json")[1])
        self.assertEqual(found, slots.status(4))
        self.settings["forge_workers"] = "many"
        self.assertEqual(self.run_main("slots"), (1, "", "config.json's forge_workers must be a whole number of 1 "
                                                         "or more.\n"))

    def test_a_held_slot_whose_note_cant_be_read(self):
        lease = self.hold(1, 4)
        fd = lease._fds[0]
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, b"not json")
        self.assertEqual(self.run_main("slots")[1].splitlines()[1], "  slot 0: in use (who by can't be read)")

    def test_cardlog_check_runs_each_process_in_a_slot(self):
        seen = []
        claimed = {}            # {thread: (what, the slots.Lease it claimed last)}
        real, real_claim = forge.processes.start_process, slots.claim

        def claim(n, budget=None, **kwargs):
            lease = real_claim(n, budget, **kwargs)
            claimed[threading.current_thread()] = (kwargs.get("what"), lease)
            return lease

        def start(argv, **kwargs):
            # cardlog-check's own processes, and its warm leg's (servecheck.warm_leg's, in serve-check's slots):
            # the thread that starts one holds the slot it claimed for it. (Not slots.status(), as this test
            # once asked: to find a slot free, status() locks it for a moment, so a claim by one of the check's
            # other threads at that moment passed it over and, with every other slot the check's, waited and
            # said so, slots.WAITING; about 1 run in 10, alone or in the full suite.)
            what, lease = claimed.get(threading.current_thread(), (None, slots.Lease()))
            seen.append((what, len(lease), "serve" in argv))
            return real(argv, **kwargs)

        with mock.patch.object(forge.processes, "start_process", start), mock.patch.object(slots, "claim", claim), \
                mock.patch.object(forge.simjar, "card_log", return_value=dict(test_forge.CARD_LOG)), \
                mock.patch.object(forge.runner, "build_command", test_forge.CommandLineTests.check_command(self)):
            code, _, err = self.run_main("cardlog-check", "--games", "4", "--commander-games", "2")
        self.assertEqual(code, 0, err)
        # v2: in each format 3 DeckLabSim runs and plain Forge's games one a process (12), then the warm leg's
        # fresh process for each format. Its serve worker comes through start_process once that takes a stdin
        # pipe (PP); until then servecheck._start starts it itself.
        self.assertEqual(sum(1 for _, _, serve in seen if not serve), 14)
        self.assertLessEqual(sum(1 for _, _, serve in seen if serve), 1)
        # Its own slot, taken before it started (the serve worker's: serve-check's, as the fresh processes').
        self.assertTrue(all(n == 1 and what in ("cardlog-check", "serve-check") for what, n, _ in seen), seen)
        self.assertEqual({what for what, _, _ in seen}, {"cardlog-check", "serve-check"})
        self.assertFalse(any(r["held"] for r in slots.status(4)["slots"]))
        self.assertNotIn(slots.WAITING, err)

    def test_cardlog_checks_processes_wait_for_a_slot(self):
        setup = forge.install._setup()
        outside = self.hold(4, 4)
        timer = threading.Timer(0.6, outside.release, args=(2,))
        timer.start()
        self.addCleanup(timer.cancel)
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            lease = cli._check_slot(setup)
            outside.release(3)
            other = cli._check_slot(setup)
        self.assertEqual((lease.ids, other.ids), ([2], [3]))
        self.assertEqual(err.getvalue(), slots.WAITING + "\n")      # said once
        lease.release()
        other.release()
        with mock.patch.dict(os.environ, {slots.ENV: str(self.slots_dir / "missing" / "slots")}):
            (self.slots_dir / "missing").write_text("a file", encoding="utf-8")
            with mock.patch("sys.stderr", err):
                self.assertEqual(cli._check_slot(setup).ids, [])    # unusable: the check goes on without
                cli._check_slot(setup)
        self.assertEqual(err.getvalue().count("can't be used"), 1)

    def test_play_says_when_it_waits_for_other_runs(self):
        summaries = [{"id": "casual/green", "title": "Green", "kind": "casual", "versions": ["target"]},
                     {"id": "casual/red", "title": "Red", "kind": "casual", "versions": ["target"]}]
        lists = {"casual/green": GREEN, "casual/red": RED}
        outside = self.hold(4, 4)
        timer = threading.Timer(3.5, outside.release)     # past report()'s 2 s between lines
        timer.start()
        self.addCleanup(timer.cancel)
        self.fake("delay=0.01")
        with mock.patch.object(test_forge.decks, "list_decks", return_value=summaries), \
                mock.patch.object(test_forge.decks, "beginner_box_pairings", return_value=[]), \
                mock.patch.object(test_forge.decks, "load_deck",
                                  side_effect=lambda deck_id, version: sections(lists[deck_id])):
            code, _, err = self.run_main("play", "casual/green", "casual/red", "--games", "200",
                                         "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        lines = err.splitlines()
        self.assertEqual(lines.count(f"  {slots.WAITING}"), 1)         # said once while it waited
        said = lines.index(f"  {slots.WAITING}")
        self.assertTrue(any(line.startswith("  200/200 games: A ") for line in lines[said + 1:]))


# ============================================================ priority, and practice hands

class PriorityTests(SlotFolder, unittest.TestCase):

    def setUp(self):
        self.use_own_slots()

    @unittest.skipUnless(sys.platform == "win32", "priority classes are Windows's")
    def test_forge_processes_start_below_normal_priority(self):
        code = ("import subprocess, sys, time;"
                "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
                "print(c.pid, flush=True); time.sleep(60)")
        own = priority_class(os.getpid())
        with mock.patch.object(subprocess, "Popen", wraps=subprocess.Popen) as popen:
            proc = forge.processes.start_process([sys.executable, "-c", code])
        self.addCleanup(proc.stdout.close)
        self.addCleanup(forge.kill_process, proc)
        flags = popen.call_args.kwargs["creationflags"]
        self.assertEqual(flags, subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS | 0x4)
        child = int(proc.stdout.readline())             # it was resumed (CREATE_SUSPENDED, 0x4)
        self.assertTrue(forge.in_job(proc.pid))
        # And what it starts (a java.exe that's only a launcher starts the real one) is too.
        self.assertEqual((priority_class(proc.pid), priority_class(child)),
                         (subprocess.BELOW_NORMAL_PRIORITY_CLASS, subprocess.BELOW_NORMAL_PRIORITY_CLASS))
        self.assertEqual(priority_class(os.getpid()), own)
        forge.kill_process(proc)
        proc.wait()

    def test_practice_hands_never_wait_for_forge(self):
        # Every slot is a Forge run's; practice hands' workers (2 spawned processes) don't
        # look at the slots at all, and run at once.
        self.hold(16, 16, what="matchup 0123456789ab")

        def refuse(*args, **kwargs):
            raise AssertionError("practice hands took a Forge slot")

        with mock.patch.object(slots, "claim", refuse), mock.patch.object(goldfish.runs, "CHUNK_GAMES", 100):
            started = time.monotonic()
            result = goldfish.simulate(sections(GREEN), "constructed", games=200, seed=1, workers=2)
        self.assertEqual((result["workers"], result["chunks"]), (2, 4))
        self.assertLess(time.monotonic() - started, 60)

    @unittest.skipUnless(sys.platform == "win32", "priority classes are Windows's")
    def test_practice_hands_workers_keep_normal_priority(self):
        # Their processes get only CREATE_NEW_PROCESS_GROUP added (goldfish/workers.py), never
        # Forge's lower priority, so Windows runs them ahead of Forge's game threads.
        calls = []

        class Real:
            @staticmethod
            def CreateProcess(*args):
                calls.append(args[5])
                return "started"

        self.assertEqual(goldfish.workers._GroupWinapi(Real()).CreateProcess(
            None, "python", None, None, False, 0, None, None, None), "started")
        self.assertEqual(calls, [goldfish.workers.CREATE_NEW_PROCESS_GROUP])
        self.assertFalse(calls[0] & (subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.IDLE_PRIORITY_CLASS))


def priority_class(pid):
    """Windows's priority class of process pid."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetPriorityClass.restype = wintypes.DWORD
    k32.GetPriorityClass.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        return k32.GetPriorityClass(handle)
    finally:
        k32.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
