"""Opt-in intent receipts precede fake thread work; no Forge or native process starts."""
import threading
import unittest

from decklab.lib import jobs


class LifecycleTests(unittest.TestCase):
    def runner(self):
        runner = jobs.Runner(max_running=1, log=lambda text: None)
        self.addCleanup(lambda: (runner.stop(), runner.join(2)))
        return runner

    def task(self, events, gate=None):
        def work(progress):
            self.assertEqual(events[:2], ["queued", "running"])
            while gate is not None and not gate.wait(0.005):
                progress(0, 1)
            progress(1, 1)
            return "synthetic"
        work._journal_event = lambda event, job: events.append(event)
        return work

    def test_intent_is_saved_before_work_and_done_is_terminal(self):
        events = []
        job = self.runner().submit("synthetic", self.task(events))
        self.assertTrue(job.wait(2))
        self.assertEqual(job.status, jobs.DONE)
        self.assertEqual(events, ["queued", "running", "done"])

    def test_refused_intent_never_enters_the_queue_or_calls_work(self):
        runner, called = self.runner(), []
        def work(progress):
            called.append(True)
        def refuse(event, job):
            raise OSError("Synthetic journal refusal")
        work._journal_event = refuse
        with self.assertRaises(OSError):
            runner.submit("synthetic", work)
        self.assertEqual(called, [])
        self.assertEqual(runner.active(), [])
        self.assertIsNone(runner.get("synthetic"))

    def test_manual_stop_and_server_shutdown_have_distinct_receipts_for_running_and_queued_jobs(self):
        for stopping in (False, True):
            with self.subTest(server_shutdown=stopping):
                runner = self.runner()
                first, second = [], []
                running = runner.submit("running", self.task(first, threading.Event()))
                # Wait for the fake work thread without a native task or unbounded sleep.
                for _ in range(200):
                    if running.status == jobs.RUNNING:
                        break
                    running._event.wait(0.001)
                queued = runner.submit("queued", self.task(second))
                if stopping:
                    runner.stop()
                else:
                    runner.cancel("running", by="Fixture")
                    runner.cancel("queued", by="Fixture")
                self.assertTrue(running.wait(2))
                self.assertTrue(queued.wait(2))
                self.assertEqual(running.status, jobs.ERROR)
                self.assertIn("interrupted" if stopping else "cancelled", first)
                self.assertEqual(second, ["queued", "interrupted" if stopping else "cancelled"])

    def test_bookkeeping_failure_does_not_prevent_a_requested_stop_or_change_existing_runner_semantics(self):
        runner, events = self.runner(), []
        work = self.task(events, threading.Event())
        def event(kind, job):
            events.append(kind)
            if kind != "queued":
                raise OSError("Synthetic later metadata failure")
        work._journal_event = event
        job = runner.submit("running", work)
        runner.cancel("running", by="Fixture")
        self.assertTrue(job.wait(2))
        self.assertEqual(job.status, jobs.ERROR)
