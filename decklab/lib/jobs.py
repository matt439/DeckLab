"""Background jobs for Deck Lab's server: slow work (the practice-hand
simulation and Forge matchups) runs in a thread of its own, and the page
polls for its progress and then its result.

Usage:

    from decklab.lib import jobs
    runner = jobs.Runner(max_running=1)
    job = runner.submit("goldfish:<cache key>", goldfish.get_or_simulate, sections, kind)
    runner.snapshot(job)    # {"key", "status", "progress": {"done", "total"}, "detail",
                            #  "ahead", "result", "error", "seconds"}
    runner.get("goldfish:<cache key>")      # the same Job, or None
    runner.active()         # the jobs waiting or running, in the order they run
    job.wait(5)             # block until it has finished (tests, command line)
    runner.cancel("goldfish:<cache key>", by="User1")      # Stop on the page: see below
    runner.stop()           # the server is stopping: see below
    runner.stopping         # ... True from then on
    runner.join(10)         # ... then wait for the running job to end

fn is called as fn(*args, progress=report) in one of the runner's threads.
report(done, total, detail=None) records how far it has got, with anything
else the page should see (detail: a Forge run's score so far, say); fn may
call it from any thread, and may itself use a process pool.

- One job per key: submitting a key that is queued or running joins that
  job. A finished one is handed back as it is (its result, or its error) for
  as long as it's kept, unless rerun=True, which starts it again; a running
  job is never started twice.
- At most max_running jobs run at once; the rest wait their turn in the
  order they came. At most max_queued jobs are waiting to start (one a
  thread is about to pick up counts): past that, submit() raises Busy, so
  two phones can't pile work onto the PC. (Busy's "stopping" is False
  then, and True when it's raised because the runner is stopping.)
- An exception in fn doesn't reach the caller: it's logged with its
  traceback (log), and the job keeps describe(exception) as its error. The
  server passes a describe that leaves out file paths (api._public).
- Finished jobs are kept for keep_seconds, and at most max_kept of them (the
  oldest go first), so a page polling a moment late still gets the answer.
- cancel(key, by) is Stop on the page: a waiting job is taken off the
  queue, and a running one's next report() raises Stopped, whose "by" says
  who stopped it: the first to press Stop, if two do (fn may keep what it
  has finished: a Forge run saves every game it finished, and who stopped
  it). Either way the job ends with the error STOPPED ("stopped"), and
  nothing is logged. A cancelled job that fails some other way (its fn
  raises anything but Stopped) is logged and described as usual.
- stop() is for the server stopping (Ctrl+C): no new job starts, the waiting
  ones end with an error, and the running one's next report() raises
  Stopped, so a job that reports its progress ends early (goldfish drops the
  chunks it hasn't started; a Forge run reports at least once a second, so
  it stops within about a second). A job that fails once stopping has begun
  isn't logged: its traceback would only fill the window of a server going
  away. join() then waits for the running job, so a Forge run can stop its
  processes and save every game it finished before the server exits.

A job's status goes "queued" -> "running" -> "done" or "error".
"""
import collections
import sys
import threading
import time
import traceback

QUEUED, RUNNING, DONE, ERROR = "queued", "running", "done", "error"
FINISHED = (DONE, ERROR)
STOPPED = "stopped"         # the error of a job cancel() ended
_now = time.monotonic       # the clock for timings and keep_seconds (tests replace it)


class Busy(Exception):
    """submit() when max_queued jobs are already waiting, or the runner is
    stopping: then "stopping" is True."""

    def __init__(self, message, stopping=False):
        super().__init__(message)
        self.stopping = stopping


class Stopped(Exception):
    """What a job's report() raises once its runner is stopping or the job is cancelled."""


def _log(text):
    """A line (or a traceback) to stderr, which pythonw doesn't have."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


def _describe(error):
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


class Job:
    """One piece of work. Read it through Runner.snapshot(); status, result
    and error only change under the runner's lock."""

    def __init__(self, key, fn, args, stopping=None):
        self.key, self.fn, self.args = key, fn, args
        self._stopping = stopping or threading.Event()      # the runner's, set by stop()
        self._cancelled = threading.Event()                 # set by Runner.cancel()
        self.cancelled_by = None                            # ... and who it named
        self.status = QUEUED
        self.result = None
        self.error = None
        self._reported = (0, None, None)    # (done, total, detail); total is None until fn says
        self.submitted = _now()
        self.started = None
        self.finished = None
        self._event = threading.Event()

    @property
    def progress(self):
        """(done, total) as last reported."""
        return self._reported[:2]

    @property
    def detail(self):
        """The detail last reported with the progress, or None."""
        return self._reported[2]

    def report(self, done, total, detail=None):
        """The progress callback fn gets: one tuple, so a reader never sees
        half. Raises Stopped once the runner is stopping or the job is
        cancelled; its "by" is who cancelled it (None if no one was named),
        so fn can record that."""
        self._reported = (done, total, detail)
        if self._stopping.is_set():
            raise Stopped("Deck Lab is stopping")
        if self._cancelled.is_set():
            stopped = Stopped(STOPPED)
            stopped.by = self.cancelled_by
            raise stopped

    def wait(self, timeout=None):
        """True once the job has finished (done or error), waiting up to timeout seconds."""
        return self._event.wait(timeout)


class Runner:
    """Runs submitted jobs in background threads; see the module docstring."""

    def __init__(self, max_running=1, max_queued=20, keep_seconds=15 * 60, max_kept=100,
                 log=None, describe=None, name="job"):
        if max_running < 1 or max_queued < 1:
            raise ValueError("max_running and max_queued must be at least 1")
        self.max_running = max_running
        self.max_queued = max_queued
        self.keep_seconds = keep_seconds
        self.max_kept = max_kept
        self.name = name
        self._log = log or _log
        self._describe = describe or _describe
        self._lock = threading.Lock()
        self._jobs = {}                         # key -> Job: waiting, running and kept
        self._queue = collections.deque()       # jobs waiting, oldest first
        self._threads = 0                       # worker threads alive
        self._stopping = threading.Event()      # set by stop()

    def submit(self, key, fn, *args, rerun=False):
        """The job for key: the one queued or running, a finished one (unless
        rerun), or a new one that runs fn(*args, progress=report) when a
        thread is free. Raises Busy when max_queued jobs are waiting."""
        with self._lock:
            self._prune()
            job = self._jobs.get(key)
            if job is not None and (job.status not in FINISHED or not rerun):
                return job
            if self._stopping.is_set():
                raise Busy("Deck Lab is stopping", stopping=True)
            if len(self._queue) >= self.max_queued:
                raise Busy(f"{len(self._queue)} jobs are already waiting")
            job = Job(key, fn, args, self._stopping)
            self._jobs[key] = job
            self._queue.append(job)
            if self._threads < self.max_running:
                self._threads += 1
                threading.Thread(target=self._work, name=f"{self.name}-{self._threads}",
                                 daemon=True).start()
            return job

    @property
    def stopping(self):
        """True once stop() has run: no job starts any more."""
        return self._stopping.is_set()

    def stop(self):
        """The server is stopping: start nothing more, end the waiting jobs
        with an error, and make each running job's next report() raise
        Stopped. It doesn't wait for them."""
        with self._lock:
            self._stopping.set()
            waiting = list(self._queue)
            self._queue.clear()
            for job in waiting:
                job.error, job.status, job.finished = "Deck Lab is stopping", ERROR, _now()
        for job in waiting:
            job._event.set()

    def cancel(self, key, by=None):
        """Stop the job for key (Stop on the page): a waiting one is taken off
        the queue and ends at once, and a running one's next report() raises
        Stopped (with by, who pressed Stop, as its "by"). Either way its error
        is STOPPED, and job.cancelled_by is by: the first by, when Stop is
        pressed again before the job has ended. True if there was a waiting
        or running job to stop; False if there's none, or it has finished."""
        with self._lock:
            job = self._jobs.get(key)
            if job is None or job.status in FINISHED:
                return False
            if not job._cancelled.is_set():
                job.cancelled_by = by
            job._cancelled.set()
            if job.status == RUNNING:
                return True
            self._queue.remove(job)
            job.error, job.status, job.finished = STOPPED, ERROR, _now()
        job._event.set()
        return True

    def join(self, timeout=None):
        """Wait up to timeout seconds (None: for ever) for the running jobs
        to end; for after stop(). True if none is running any more."""
        deadline = None if timeout is None else time.monotonic() + timeout
        for job in self.active():
            left = None if deadline is None else max(0.0, deadline - time.monotonic())
            if job.status == RUNNING and not job.wait(left):
                return False
        return True

    def active(self):
        """The jobs waiting or running: the running ones first (in the order
        they started), then the waiting ones in the order they'll start."""
        with self._lock:
            running = sorted((j for j in self._jobs.values() if j.status == RUNNING), key=lambda j: j.started)
            return running + list(self._queue)

    def get(self, key):
        """The job for key (waiting, running or kept), or None."""
        with self._lock:
            self._prune()
            return self._jobs.get(key)

    def snapshot(self, job):
        """A job as a JSON-ready dict: key, status, progress {done, total},
        detail (as last reported with the progress, or None), ahead (jobs
        that go before it: running ones and those queued before it; 0 unless
        queued), result, error, and seconds (running time so far, or in all;
        None while queued)."""
        with self._lock:
            ahead = 0
            if job.status == QUEUED:
                running = sum(1 for j in self._jobs.values() if j.status == RUNNING)
                ahead = running + (self._queue.index(job) if job in self._queue else 0)
            done, total, detail = job._reported
            end = job.finished if job.finished is not None else _now()
            return {
                "key": job.key,
                "status": job.status,
                "progress": {"done": done, "total": total},
                "detail": detail,
                "ahead": ahead,
                "result": job.result,
                "error": job.error,
                "seconds": round(end - job.started, 2) if job.started is not None else None,
            }

    # ------------------------------------------------------------ inside

    def _work(self):
        """A worker thread: run queued jobs until there are none, then end."""
        while True:
            with self._lock:
                if not self._queue:
                    self._threads -= 1
                    return
                job = self._queue.popleft()
                job.status = RUNNING
                job.started = _now()
            self._run(job)

    def _run(self, job):
        try:
            result = job.fn(*job.args, progress=job.report)
        except BaseException as e:      # a worker thread: nothing above it would handle this
            if job._cancelled.is_set() and isinstance(e, Stopped):
                error = STOPPED         # Stop was pressed: nothing to log
            else:
                if not self._stopping.is_set():
                    self._log(f"{self.name} {job.key!r} failed:\n{traceback.format_exc()}")
                try:
                    error = self._describe(e)
                except Exception:
                    error = type(e).__name__
            with self._lock:
                job.error, job.status, job.finished = error, ERROR, _now()
        else:
            with self._lock:
                job.result, job.status, job.finished = result, DONE, _now()
        job._event.set()

    def _prune(self):
        """Forget finished jobs past keep_seconds, then the oldest past max_kept.
        Call with the lock held."""
        now = _now()
        finished = sorted((j for j in self._jobs.values() if j.status in FINISHED), key=lambda j: j.finished)
        excess = max(0, len(finished) - self.max_kept)
        for i, job in enumerate(finished):
            if i < excess or now - job.finished > self.keep_seconds:
                del self._jobs[job.key]
