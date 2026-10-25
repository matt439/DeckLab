"""The goldfish package's worker processes: _run_chunk() plays one chunk of
games (in a spawned worker, or in-process), with a cache of engines per
process; _start_worker() is each worker's first step; _NewProcessGroups
starts workers in a process group of their own on Windows. Workers pickle
_run_chunk and _start_worker by name, so they stay here, with _ENGINES.
"""
import multiprocessing
import multiprocessing.connection
import os
import random
import signal
import sys
import threading

from .engine import _Engine, _play_games

_ENGINES = {}


def _start_worker():
    """A worker process's first step. Ctrl+C in the server window is the
    server's to handle (Windows sends it to every process on the console),
    so the worker ignores it. And the worker ends when the process that
    started it has gone: killed (Task Manager's End task, taskkill /F), that
    process can't stop its workers, which would otherwise wait for work for
    ever."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=_exit_with, args=(parent.sentinel,), name="parent-watch", daemon=True).start()


def _exit_with(sentinel, exit=os._exit):
    """Wait until sentinel (the parent process's handle) is signalled, then
    end this process at once."""
    multiprocessing.connection.wait([sentinel])
    exit(1)


# Windows: a worker's own "ignore Ctrl+C" (_start_worker) only begins once it
# has imported the server, and a Ctrl+C before that filled the window with
# its traceback. So the workers start in a process group of their own, where
# Windows has Ctrl+C off from the first moment (CREATE_NEW_PROCESS_GROUP),
# while the server keeps its own Ctrl+C. multiprocessing has no setting for
# that, so while a run starts its workers, its spawn code's CreateProcess
# adds the flag (_NewProcessGroups); one run at a time.
CREATE_NEW_PROCESS_GROUP = 0x00000200
_SPAWN_LOCK = threading.Lock()


class _NewProcessGroups:
    """`with _NewProcessGroups():` multiprocessing's spawn starts each process
    in a new process group (Windows; elsewhere it does nothing)."""

    def __enter__(self):
        _SPAWN_LOCK.acquire()
        self.module = None
        if sys.platform == "win32":
            try:
                from multiprocessing import popen_spawn_win32
                self.real = popen_spawn_win32._winapi
                popen_spawn_win32._winapi = _GroupWinapi(self.real)
                self.module = popen_spawn_win32
            except (ImportError, AttributeError):
                pass            # a Python without these: workers start as before
        return self

    def __exit__(self, *exc):
        try:
            if self.module is not None:
                self.module._winapi = self.real
        finally:
            _SPAWN_LOCK.release()


class _GroupWinapi:
    """The _winapi module, except that CreateProcess (application, command
    line, process and thread attributes, inherit handles, creation flags,
    ...) adds CREATE_NEW_PROCESS_GROUP to the creation flags."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def CreateProcess(self, *args, **kwargs):
        args = list(args)
        if len(args) > 5 and isinstance(args[5], int):
            args[5] |= CREATE_NEW_PROCESS_GROUP
        return self._real.CreateProcess(*args, **kwargs)


def _run_chunk(task):
    """One chunk of games, in a worker process (or in-process): task is
    (model key, model, setup, turns, games, seed, mulligans)."""
    key, model, setup, turns, games, seed, mulligans = task
    engine = _ENGINES.get(key)
    if engine is None:
        if len(_ENGINES) > 8:
            _ENGINES.clear()
        engine = _ENGINES[key] = _Engine(model)
    return _play_games(engine, setup, turns, games, random.Random(seed), mulligans)
