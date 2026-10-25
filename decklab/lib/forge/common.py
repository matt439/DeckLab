"""What the rest of the forge package shares: the constants several parts use, the data
folder, settings, errors, logging, writing a file whole, holding Ctrl+C back, and the
names Forge knows cards by.

DATA_DIR, _settings, _log and _write_atomic are read elsewhere as common.<name>, never
copied, so that one patch of each (the tests') reaches every reader."""
import os
import signal
import sys
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from decklab.lib import config, decks, jobs

FORGE_RUN_VERSION = 2           # raise when reading or pooling changes meaning; part of the engine id
                                # (engine.py). 2: wave 2's engine (2026-10-03); 1: lists.V1_RUN_VERSION
GAME_CHOICES = (200, 400, 800, 1600, 3200)
DEFAULT_GAMES = 800
AI_PROFILES = ("Default", "Default")

DATA_DIR = config.DATA / "forge"    # decks/, results/, user/, logs/, cardscripts-<version>.json

MIXED_KINDS = "A Commander deck can only play another Commander deck."


class ForgeError(Exception):
    """Forge can't play this: a plain sentence that's safe to show (no paths)."""


class Stopped(Exception):
    """A stopped run, by the contract's name. forge never raises it: a stopped run
    raises again whatever stopped it (jobs.Stopped from the page's Stop or the server
    stopping, KeyboardInterrupt from Ctrl+C). Kept so callers can name it too."""


# What stops a run on purpose (a run record says "stopped"); anything else is an error.
STOPS = (Stopped, jobs.Stopped, KeyboardInterrupt)


def _settings():
    return config.load()


def _decks_dir():
    return DATA_DIR / "decks"


def _results_dir(results_dir=None):
    return Path(results_dir) if results_dir is not None else DATA_DIR / "results"


def _user_dir():
    return DATA_DIR / "user"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _log(text):
    """A line for the server window (stderr, which pythonw doesn't have)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


def _write_atomic(path, text):
    """Write text as path, whole or not at all. On Windows a file can't be replaced
    while another handle to it is open (the server's own threads reading a result for
    another page, a virus scanner), so the replace is tried again over
    decks.REPLACE_WAITS; PermissionError if it stays open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem[:12], suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for wait in (*decks.REPLACE_WAITS, None):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if wait is None:
                    raise
            time.sleep(wait)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@contextmanager
def _interrupts_held(note=None):
    """Hold Ctrl+C back until the block is done, then raise it; with note, call note()
    for each one instead and don't raise. So a Forge process is never started without
    being noted, and a stopped run is always saved. Only the main thread gets Ctrl+C:
    elsewhere (the server's runs) this does nothing."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    caught = []

    def handler(signum, frame):
        caught.append(signum)
        if note is not None:
            note()

    try:
        old = signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError, TypeError):
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old if old is not None else signal.SIG_DFL)
        if caught and note is None:
            if old is signal.default_int_handler:
                raise KeyboardInterrupt
            if callable(old):
                old(signal.SIGINT, None)


def norm(name):
    """Forge's card lookup key: accents stripped, any case."""
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


def forge_name(name):
    """The name Forge finds for a Scryfall name: the front face of "A // B"."""
    return name.split(" // ", 1)[0].strip()


def _os_reason(e):
    """An OSError's reason in words, without the file name str(e) would add (a path),
    to go in brackets: "the system cannot find the file specified"."""
    reason = e.strerror or (e.args[0] if e.args and isinstance(e.args[0], str) else "") or type(e).__name__
    reason = reason.strip().rstrip(".")
    if reason[1:2].islower() and not reason.startswith("Windows"):
        reason = reason[:1].lower() + reason[1:]
    return reason
