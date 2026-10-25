"""Tests for decklab.lib.jobs: the background job runner.

The jobs are small functions that wait on threading.Events the tests set,
so each test decides exactly when a job finishes; nothing sleeps for long.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import threading
import time
import unittest
from unittest import mock

from decklab.lib import jobs

WAIT = 5        # seconds: the longest any test waits for a thread


class Gate:
    """A job function that reports progress, then waits for release()."""

    def __init__(self, result="ok", error=None):
        self.result, self.error = result, error
        self.started = threading.Event()
        self.go = threading.Event()
        self.calls = []

    def __call__(self, *args, progress):
        self.calls.append(args)
        self.thread = threading.current_thread()
        progress(1, 4)
        self.started.set()
        if not self.go.wait(WAIT):
            raise TimeoutError("never released")
        progress(4, 4)
        if self.error:
            raise self.error
        return self.result

    def release(self):
        self.go.set()


class RunnerTestCase(unittest.TestCase):

    def setUp(self):
        self.logs = []
        self.gates = []

    def tearDown(self):
        for gate in self.gates:         # never leave a thread waiting
            gate.release()

    def runner(self, **kw):
        kw.setdefault("log", self.logs.append)
        return jobs.Runner(**kw)

    def gate(self, **kw):
        gate = Gate(**kw)
        self.gates.append(gate)
        return gate

    def finish(self, runner, job):
        self.assertTrue(job.wait(WAIT), "the job didn't finish")
        return runner.snapshot(job)


class RunTests(RunnerTestCase):

    def test_runs_in_the_background_with_progress(self):
        runner = self.runner()
        gate = self.gate(result={"answer": 42})
        job = runner.submit("a", gate, "x", 2)
        self.assertTrue(gate.started.wait(WAIT))
        self.assertIsNot(gate.thread, threading.current_thread())
        self.assertEqual((gate.thread.name, gate.thread.daemon), ("job-1", True))
        snap = runner.snapshot(job)
        self.assertEqual((snap["key"], snap["status"], snap["progress"]), ("a", "running", {"done": 1, "total": 4}))
        self.assertEqual((snap["ahead"], snap["result"], snap["error"]), (0, None, None))
        self.assertIsInstance(snap["seconds"], float)
        gate.release()
        snap = self.finish(runner, job)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"], {"answer": 42})
        self.assertEqual(snap["progress"], {"done": 4, "total": 4})
        self.assertEqual(gate.calls, [("x", 2)])
        self.assertIs(runner.get("a"), job)
        self.assertIsNone(runner.get("b"))

    def test_a_second_request_joins_the_running_job(self):
        runner = self.runner()
        gate = self.gate()
        first = runner.submit("a", gate)
        self.assertTrue(gate.started.wait(WAIT))
        other = self.gate()
        self.assertIs(runner.submit("a", other), first)
        self.assertIs(runner.submit("a", other, rerun=True), first)     # never twice at once
        gate.release()
        self.finish(runner, first)
        self.assertEqual(len(gate.calls), 1)
        self.assertEqual(other.calls, [])

    def test_a_finished_job_is_kept_until_rerun(self):
        runner = self.runner()
        gate = self.gate(error=ValueError("no good"))
        gate.release()
        job = runner.submit("a", gate)
        self.assertEqual(self.finish(runner, job)["status"], "error")
        self.assertIs(runner.submit("a", self.gate()), job)            # the error, as it is
        again = self.gate(result="fixed")
        again.release()
        new = runner.submit("a", again, rerun=True)
        self.assertIsNot(new, job)
        self.assertEqual(self.finish(runner, new)["result"], "fixed")
        self.assertIs(runner.submit("a", self.gate()), new)
        self.assertEqual(len(again.calls), 1)

    def test_errors_are_logged_and_described_not_raised(self):
        runner = self.runner(describe=lambda e: f"described: {e}")
        gate = self.gate(error=OSError(2, "No such file", r"C:\Users\someone\secret.json"))
        gate.release()
        snap = self.finish(runner, runner.submit("a", gate))
        self.assertEqual((snap["status"], snap["result"]), ("error", None))
        self.assertTrue(snap["error"].startswith("described: "))
        self.assertEqual(len(self.logs), 1)
        self.assertIn("Traceback", self.logs[0])
        self.assertIn("job 'a' failed", self.logs[0])

    def test_the_default_description_and_a_failing_one(self):
        runner = self.runner()
        gate = self.gate(error=KeyError("x"))
        gate.release()
        self.assertEqual(self.finish(runner, runner.submit("a", gate))["error"], "KeyError: 'x'")
        runner = self.runner(describe=lambda e: 1 / 0)
        gate = self.gate(error=RuntimeError("boom"))
        gate.release()
        self.assertEqual(self.finish(runner, runner.submit("a", gate))["error"], "RuntimeError")

    def test_even_a_system_exit_only_fails_the_job(self):
        runner = self.runner()

        def leave(progress):
            raise SystemExit(3)

        snap = self.finish(runner, runner.submit("a", leave))
        self.assertEqual(snap["status"], "error")
        ok = self.gate()
        ok.release()
        self.assertEqual(self.finish(runner, runner.submit("b", ok))["status"], "done")


class LimitTests(RunnerTestCase):

    def test_one_at_a_time_in_order(self):
        runner = self.runner(max_running=1)
        gates = [self.gate(result=i) for i in range(3)]
        a, b, c = (runner.submit(k, g) for k, g in zip("abc", gates))
        self.assertTrue(gates[0].started.wait(WAIT))
        self.assertEqual([runner.snapshot(j)["status"] for j in (a, b, c)], ["running", "queued", "queued"])
        self.assertEqual([runner.snapshot(j)["ahead"] for j in (a, b, c)], [0, 1, 2])
        self.assertEqual(runner.snapshot(b)["progress"], {"done": 0, "total": None})
        self.assertIsNone(runner.snapshot(b)["seconds"])
        self.assertFalse(gates[1].started.is_set())
        gates[0].release()
        self.assertTrue(gates[1].started.wait(WAIT))
        self.assertEqual([runner.snapshot(j)["status"] for j in (a, b, c)], ["done", "running", "queued"])
        self.assertEqual(runner.snapshot(c)["ahead"], 1)
        self.assertFalse(gates[2].started.is_set())
        gates[1].release()
        gates[2].release()
        self.assertEqual([self.finish(runner, j)["result"] for j in (a, b, c)], [0, 1, 2])

    def test_two_at_a_time(self):
        runner = self.runner(max_running=2)
        gates = [self.gate() for _ in range(3)]
        jobs_ = [runner.submit(k, g) for k, g in zip("abc", gates)]
        self.assertTrue(gates[0].started.wait(WAIT) and gates[1].started.wait(WAIT))
        self.assertEqual(runner.snapshot(jobs_[2])["status"], "queued")
        self.assertEqual(runner.snapshot(jobs_[2])["ahead"], 2)
        gates[1].release()
        self.assertTrue(gates[2].started.wait(WAIT))
        for gate in gates:
            gate.release()
        for job in jobs_:
            self.finish(runner, job)

    def test_too_many_waiting_is_busy(self):
        runner = self.runner(max_running=1, max_queued=2)
        first = self.gate()
        runner.submit("a", first)
        self.assertTrue(first.started.wait(WAIT))
        runner.submit("b", self.gate())
        runner.submit("c", self.gate())
        with self.assertRaises(jobs.Busy) as caught:
            runner.submit("d", self.gate())
        self.assertFalse(caught.exception.stopping)     # the queue is full; the runner isn't stopping
        self.assertIsNotNone(runner.get("c"))      # joining a waiting job is still fine
        self.assertIs(runner.submit("b", self.gate()), runner.get("b"))
        self.assertIsNone(runner.get("d"))
        with self.assertRaises(ValueError):
            jobs.Runner(max_running=0)
        with self.assertRaises(ValueError):
            jobs.Runner(max_queued=0)

    def test_threads_end_when_there_is_nothing_to_do(self):
        runner = self.runner(max_running=2, name="idle-check")
        gates = [self.gate() for _ in range(3)]
        for key, gate in zip("abc", gates):
            gate.release()
            self.finish(runner, runner.submit(key, gate))
        deadline = time.monotonic() + WAIT
        while runner._threads and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(runner._threads, 0)
        # A later job starts a thread again.
        gate = self.gate(result="later")
        gate.release()
        self.assertEqual(self.finish(runner, runner.submit("d", gate))["result"], "later")


class StopTests(RunnerTestCase):
    """stop(), for the server stopping (Ctrl+C)."""

    def test_stop_ends_the_waiting_jobs_and_the_running_one_at_its_next_report(self):
        runner = self.runner(max_running=1)
        running, waiting = self.gate(), self.gate()
        a = runner.submit("a", running)
        b = runner.submit("b", waiting)
        self.assertTrue(running.started.wait(WAIT))
        runner.stop()
        # The waiting job never starts.
        self.assertTrue(b.wait(0))
        self.assertEqual((runner.snapshot(b)["status"], runner.snapshot(b)["error"]),
                         ("error", "Deck Lab is stopping"))
        self.assertEqual(waiting.calls, [])
        # The running one ends when it next reports its progress, and nothing is logged.
        running.release()
        snap = self.finish(runner, a)
        self.assertEqual((snap["status"], snap["error"]), ("error", "Stopped: Deck Lab is stopping"))
        self.assertEqual(self.logs, [])
        with self.assertRaises(jobs.Busy) as caught:
            runner.submit("c", self.gate())
        # Busy says why, so an answer doesn't call it a full queue (review finding API-4).
        self.assertTrue(caught.exception.stopping)
        self.assertTrue(runner.stopping)
        deadline = time.monotonic() + WAIT
        while runner._threads and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(runner._threads, 0)

    def test_a_real_failure_while_stopping_is_described_but_not_logged(self):
        runner = self.runner(max_running=1)
        self.assertFalse(runner.stopping)
        started, go = threading.Event(), threading.Event()

        def fn(progress):
            started.set()
            go.wait(WAIT)
            raise OSError("disk full")

        job = runner.submit("a", fn)
        self.assertTrue(started.wait(WAIT))
        runner.stop()
        go.set()
        self.assertEqual(self.finish(runner, job)["error"], "OSError: disk full")
        self.assertEqual(self.logs, [])         # the window of a server going away

    def test_report_raises_only_once_stopping(self):
        job = jobs.Job("a", None, ())
        job.report(1, 2)
        self.assertEqual(job.progress, (1, 2))
        stopping = threading.Event()
        job = jobs.Job("b", None, (), stopping)
        stopping.set()
        with self.assertRaises(jobs.Stopped):
            job.report(2, 2)


class DetailTests(RunnerTestCase):
    """report(done, total, detail): what a Forge run shows while it plays."""

    def test_detail_goes_with_the_progress(self):
        runner = self.runner()
        started, go = threading.Event(), threading.Event()

        def scored(progress):
            progress(10, 800, {"wins": [6, 4]})
            started.set()
            go.wait(WAIT)
            progress(800, 800)
            return "played"

        job = runner.submit("a", scored)
        self.assertTrue(started.wait(WAIT))
        snap = runner.snapshot(job)
        self.assertEqual((snap["progress"], snap["detail"]), ({"done": 10, "total": 800}, {"wins": [6, 4]}))
        self.assertEqual((job.progress, job.detail), ((10, 800), {"wins": [6, 4]}))
        go.set()
        snap = self.finish(runner, job)
        self.assertEqual((snap["progress"], snap["detail"]), ({"done": 800, "total": 800}, None))

    def test_no_detail_before_the_first_report(self):
        runner = self.runner(max_running=1)
        first = self.gate()
        runner.submit("a", first)
        self.assertTrue(first.started.wait(WAIT))
        waiting = runner.submit("b", self.gate())
        self.assertEqual(runner.snapshot(waiting)["detail"], None)
        self.assertEqual(runner.snapshot(runner.get("a"))["detail"], None)     # a two-number report


class CancelTests(RunnerTestCase):
    """cancel(key): Stop on the page."""

    def test_a_waiting_job_is_taken_off_the_queue(self):
        runner = self.runner(max_running=1)
        running, waiting, last = self.gate(), self.gate(), self.gate(result="c")
        a = runner.submit("a", running)
        b = runner.submit("b", waiting)
        c = runner.submit("c", last)
        self.assertTrue(running.started.wait(WAIT))
        self.assertEqual(runner.snapshot(c)["ahead"], 2)
        self.assertTrue(runner.cancel("b"))
        self.assertTrue(b.wait(0))
        snap = runner.snapshot(b)
        self.assertEqual((snap["status"], snap["error"]), ("error", jobs.STOPPED))
        self.assertEqual(jobs.STOPPED, "stopped")
        self.assertEqual(runner.snapshot(c)["ahead"], 1)
        self.assertEqual([j.key for j in runner.active()], ["a", "c"])
        running.release()
        last.release()
        self.assertEqual(self.finish(runner, c)["result"], "c")
        self.assertEqual(self.finish(runner, a)["status"], "done")
        self.assertEqual(waiting.calls, [])
        self.assertEqual(self.logs, [])
        self.assertFalse(runner.cancel("b"))            # already over
        # A new run for the key starts afresh.
        again = self.gate(result="again")
        again.release()
        self.assertEqual(self.finish(runner, runner.submit("b", again, rerun=True))["result"], "again")

    def test_a_running_job_stops_at_its_next_report(self):
        runner = self.runner(max_running=1)
        saved = []
        started, go = threading.Event(), threading.Event()

        def forge_like(progress):
            progress(100, 800, {"wins": [60, 40]})
            started.set()
            go.wait(WAIT)
            try:
                progress(200, 800, {"wins": [120, 80]})
            except jobs.Stopped as e:
                saved.append(f"kept the finished batches, stopped by {e.by}")
                raise
            return "not stopped"

        job = runner.submit("a", forge_like)
        other = self.gate(result="next")
        other.release()
        waiting = runner.submit("b", other)
        self.assertTrue(started.wait(WAIT))
        self.assertTrue(runner.cancel("a", by="User1"))
        self.assertEqual(runner.snapshot(job)["status"], "running")     # until it next reports
        go.set()
        snap = self.finish(runner, job)
        self.assertEqual((snap["status"], snap["error"]), ("error", "stopped"))
        self.assertEqual(snap["detail"], {"wins": [120, 80]})
        self.assertEqual(saved, ["kept the finished batches, stopped by User1"])
        self.assertEqual(job.cancelled_by, "User1")
        self.assertEqual(self.logs, [])                 # a stop isn't a failure
        self.assertEqual(self.finish(runner, waiting)["result"], "next")    # the runner goes on

    def test_the_first_stop_names_who_stopped_it(self):
        # Review finding API-2: a second Stop press before the run's next report renamed who stopped it.
        runner = self.runner(max_running=1)
        started, go, seen = threading.Event(), threading.Event(), []

        def fn(progress):
            progress(0, 10)
            started.set()
            go.wait(WAIT)
            try:
                progress(1, 10)
            except jobs.Stopped as e:
                seen.append(e.by)
                raise

        job = runner.submit("a", fn)
        self.assertTrue(started.wait(WAIT))
        self.assertTrue(runner.cancel("a", by="User1"))
        self.assertTrue(runner.cancel("a", by="Matt"))      # still True: it's stopping
        go.set()
        self.assertEqual(self.finish(runner, job)["error"], jobs.STOPPED)
        self.assertEqual((seen, job.cancelled_by), (["User1"], "User1"))

    def test_a_real_failure_after_stop_is_logged_and_described(self):
        # Review finding API-3: any exception of a cancelled job was taken for the stop, and never logged.
        runner = self.runner(max_running=1)
        started, go = threading.Event(), threading.Event()

        def fn(progress):
            started.set()
            go.wait(WAIT)
            raise RuntimeError("disk full")

        job = runner.submit("a", fn)
        self.assertTrue(started.wait(WAIT))
        self.assertTrue(runner.cancel("a", by="User1"))
        go.set()
        self.assertEqual(self.finish(runner, job)["error"], "RuntimeError: disk full")
        self.assertEqual(len(self.logs), 1)
        self.assertIn("RuntimeError: disk full", self.logs[0])
        self.assertIn("Traceback", self.logs[0])

    def test_nothing_to_cancel(self):
        runner = self.runner()
        self.assertFalse(runner.cancel("nope"))
        gate = self.gate()
        gate.release()
        job = runner.submit("a", gate)
        self.finish(runner, job)
        self.assertFalse(runner.cancel("a"))
        self.assertEqual(runner.snapshot(job)["status"], "done")

    def test_a_cancelled_job_that_finishes_without_reporting_keeps_its_result(self):
        runner = self.runner()
        gate = self.gate(result="finished anyway")
        job = runner.submit("a", gate)
        self.assertTrue(gate.started.wait(WAIT))
        runner.cancel("a")
        gate.release()                  # Gate reports (4, 4) after the release: that raises
        snap = self.finish(runner, job)
        self.assertEqual((snap["status"], snap["error"]), ("error", "stopped"))

        def quiet(progress):
            quiet.started.set()
            quiet.go.wait(WAIT)
            return "done without reporting"

        quiet.started, quiet.go = threading.Event(), threading.Event()
        job = runner.submit("b", quiet)
        self.assertTrue(quiet.started.wait(WAIT))
        runner.cancel("b")
        quiet.go.set()
        self.assertEqual(self.finish(runner, job)["result"], "done without reporting")


class JoinTests(RunnerTestCase):

    def test_join_waits_for_the_running_job_after_stop(self):
        runner = self.runner(max_running=1)
        gate = self.gate()
        job = runner.submit("a", gate)
        self.assertTrue(gate.started.wait(WAIT))
        runner.stop()
        self.assertFalse(runner.join(0.05))             # still running
        gate.release()
        self.assertTrue(runner.join(WAIT))
        self.assertEqual(runner.snapshot(job)["status"], "error")
        self.assertTrue(runner.join(0))
        self.assertTrue(self.runner().join(0))          # nothing ever ran


class KeepTests(RunnerTestCase):

    def test_finished_jobs_go_after_keep_seconds(self):
        clock = [1000.0]
        with mock.patch.object(jobs, "_now", lambda: clock[0]):
            runner = self.runner(keep_seconds=60)
            gate = self.gate()
            gate.release()
            job = runner.submit("a", gate)
            self.finish(runner, job)
            clock[0] += 59
            self.assertIs(runner.get("a"), job)
            clock[0] += 2
            self.assertIsNone(runner.get("a"))
            again = self.gate(result="new")
            again.release()
            self.assertEqual(self.finish(runner, runner.submit("a", again))["result"], "new")

    def test_at_most_max_kept_finished_jobs(self):
        runner = self.runner(max_kept=2)
        for key in "abc":
            gate = self.gate(result=key)
            gate.release()
            self.finish(runner, runner.submit(key, gate))
        self.assertEqual([k for k in "abc" if runner.get(k)], ["b", "c"])

    def test_running_jobs_are_never_dropped(self):
        clock = [0.0]
        with mock.patch.object(jobs, "_now", lambda: clock[0]):
            runner = self.runner(max_running=2, keep_seconds=1, max_kept=1)
            slow = self.gate()
            job = runner.submit("slow", slow)
            self.assertTrue(slow.started.wait(WAIT))
            for key in "ab":
                gate = self.gate()
                gate.release()
                self.finish(runner, runner.submit(key, gate))
            self.assertIsNone(runner.get("a"))          # past max_kept
            self.assertIsNotNone(runner.get("b"))
            clock[0] += 100
            self.assertIsNone(runner.get("b"))          # past keep_seconds
            self.assertIs(runner.get("slow"), job)
            self.assertEqual(runner.snapshot(job)["seconds"], 100.0)
            slow.release()
            self.finish(runner, job)


if __name__ == "__main__":
    unittest.main()
