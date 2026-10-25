"""Writing a deck file straight into a test's files-backend tree (moved here from lib/decks in
phase 5: Deck Lab itself saves decks only through the inventory's deck operations).

    sha = deck_files.write_deck_file(path, text, None)         # create
    deck_files.write_deck_file(path, new_text, sha)            # replace, if nobody changed it

The write drops the request's pinned inventory snapshot (inventory.invalidate()), so what the
test reads next sees the file it wrote. The path is checked as the deck tables' refresh checks
it (decks._checked_path: a space's casual or commander folder, a valid slug). Tests patch
decks.REPLACE_WAITS, so the retries read it there at each write.
"""
import hashlib
import os
import threading
import time

from decklab.lib import decks

_write_lock = threading.Lock()


class ConflictError(Exception):
    """The file on disk changed since it was loaded (or already exists)."""


class FileBusyError(PermissionError):
    """The deck file stayed open in another program (Windows won't replace a
    file while it's open), so it wasn't written. str(error) says so in plain
    words, with no path; the file is unchanged, and saving again once it's
    closed works."""


def write_deck_file(path, text, expected_sha256):
    """Write a deck file if nobody else changed it. Returns the new sha256.

    expected_sha256 is the hash from when the file was loaded, or None to
    create a new file. Raises ConflictError if the file on disk has a different
    hash, or already exists when creating. The text is written byte for byte
    as UTF-8, so its line endings are kept.
    """
    path = decks._checked_path(path)
    data = text if isinstance(text, bytes) else text.encode("utf-8")
    with _write_lock:
        if expected_sha256 is None:
            path.parent.mkdir(parents=True, exist_ok=True)     # a person's first deck makes the folder
            try:
                with open(path, "xb") as f:
                    f.write(data)
            except FileExistsError:
                raise ConflictError(f"{path.name} already exists") from None
        else:
            try:
                current = hashlib.sha256(path.read_bytes()).hexdigest()
            except FileNotFoundError:
                raise ConflictError(f"{path.name} was deleted since it was loaded") from None
            if current != expected_sha256:
                raise ConflictError(f"{path.name} changed since it was loaded")
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                tmp.write_bytes(data)
                _replace(tmp, path, expected_sha256)
            finally:
                tmp.unlink(missing_ok=True)
    from decklab.lib import inventory
    inventory.invalidate()          # this test's next read sees the file it wrote
    return hashlib.sha256(data).hexdigest()


def _replace(tmp, path, expected_sha256=None):
    """os.replace(tmp, path), tried again for a moment while something has
    the file open (on Windows a file can't be replaced while any other handle
    to it is open). Before each new try the file must still be the one loaded
    (ConflictError otherwise); if it stays open, FileBusyError, with the file
    unchanged. expected_sha256 None skips the "still the one loaded" check."""
    for wait in (*decks.REPLACE_WAITS, None):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if wait is None:
                raise FileBusyError(f"{path.name} is open in another program, so it couldn't be saved "
                                    f"(nothing was changed); close it or wait a moment, then save again") from None
        time.sleep(wait)
        if expected_sha256 is None:
            continue
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            raise ConflictError(f"{path.name} was deleted since it was loaded") from None
        except OSError:
            continue
        if current != expected_sha256:
            raise ConflictError(f"{path.name} changed since it was loaded")
