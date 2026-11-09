"""Own a cross-check worker and every descendant, including after its leader exits.

Windows assigns a suspended worker to a private kill-on-close Job Object before
letting any code run. POSIX workers own a process group; their Forge children
must inherit that group so cancellation can kill the whole run together.
"""
import errno
import os
import signal
import subprocess
import sys
import weakref
from contextlib import contextmanager

WAIT_SECONDS = 5


def _windows():
    return sys.platform == "win32"


def _forge_processes():
    from decklab.lib.forge import processes
    return processes


def _close_holder(holder):
    if holder:
        _forge_processes()._k32.CloseHandle(holder.pop())


def _wait(process):
    try:
        process.wait(timeout=WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=WAIT_SECONDS)


def spawn(argv, *, cwd, env, stdout, stderr):
    """Start a strictly owned process with separate caller-owned output files.

    No shell or inherited stdin. Ownership failures refuse before the suspended
    Windows process can run; they never fall back to an unowned child.
    """
    if (stdout is None or stderr is None or stdout is stderr
            or isinstance(stdout, int) or isinstance(stderr, int)):
        raise ValueError("Separate stdout and stderr files are required.")
    common = dict(cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
    forge = _forge_processes()
    if not _windows():
        return subprocess.Popen(forge._niced(argv), start_new_session=True, **common)
    job = forge._new_job()
    holder = [job]
    process, handle = None, None
    try:
        process = subprocess.Popen(argv, creationflags=forge._SPAWN_FLAGS | forge._SUSPENDED, **common)
        rights = forge.PROCESS_SET_QUOTA | forge.PROCESS_TERMINATE | forge.PROCESS_SUSPEND_RESUME
        handle = forge._k32.OpenProcess(rights, False, process.pid)
        if not handle or not forge._k32.AssignProcessToJobObject(job, handle):
            raise OSError(errno.EPERM, "The cross-check worker could not join its private job.")
        process._crosscheck_job = holder
        weakref.finalize(process, _close_holder, holder)
        if forge._ntdll.NtResumeProcess(handle) != 0:
            raise OSError(errno.EPERM, "The owned cross-check worker could not resume.")
        return process
    except BaseException:
        try:
            forge._k32.TerminateJobObject(job, 1)
            if process is not None:
                if process.poll() is None:
                    process.kill()
                _wait(process)
        finally:
            _close_holder(holder)
        raise
    finally:
        if handle:
            forge._k32.CloseHandle(handle)


def terminate(process):
    """Kill and reap this worker's entire ownership scope, even after leader exit."""
    holder = getattr(process, "_crosscheck_job", None)
    try:
        if _windows():
            if holder:
                for job in list(holder):
                    _forge_processes()._k32.TerminateJobObject(job, 1)
        else:
            try:
                # The group can still contain children after process.poll() says done.
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        _wait(process)
    finally:
        if holder:
            _close_holder(holder)


@contextmanager
def install_inherited_group_launch():
    """Within an isolated POSIX worker, keep Forge's JVM inside the owned group.

    Existing Forge's normal launcher creates its own session. That is appropriate
    in Deck Lab's main process but would escape this outer worker's cancellation
    group. This local context changes only this disposable worker's launcher.
    Windows keeps Forge's normal nested Job Objects, inherited from our outer job.
    """
    if _windows():
        yield
        return
    if os.getpid() != os.getpgrp() or os.getpid() != os.getsid(0):
        raise RuntimeError("Forge group inheritance requires an isolated session leader.")
    forge = _forge_processes()
    original = forge.start_process

    def inherited(argv, cwd=None, env=None, stdin=False):
        return subprocess.Popen(forge._niced(argv), cwd=cwd, env=env,
                                stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)

    forge.start_process = inherited
    try:
        yield
    finally:
        forge.start_process = original


inherited_forge_children = install_inherited_group_launch
