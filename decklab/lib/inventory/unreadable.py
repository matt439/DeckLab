"""What a reader raises for an inventory source it can't read, as today's file readers raised it.

A snapshot keeps a source it couldn't read as text (Sheet.error, Product.error, Order.error: the
exception's str, see model.py), and a file that isn't there as exists False. A reader that today
let open() or csv raise (pool's collection.csv, purchases' watchlist and status.csv, the
collection page's special basics) raises the same thing again from the snapshot, so its callers
catch what they always caught and show the same words:

    unreadable.check(sheet)              # FileNotFoundError when the file isn't there; the
                                         # source's own error raised again when it couldn't be read
    unreadable.missing("magic/watchlist.csv")
    unreadable.again("'utf-8' codec can't decode byte 0xff in position 0: invalid start byte")

again() rebuilds the exception from its text: an OSError ("[Errno 13] Permission denied: ...",
a PermissionError for errno 13 so the pages' "is it open in Excel?" hint still shows), a
UnicodeDecodeError (the codec's own message, rebuilt exactly), else csv.Error (what a CSV that
can't be parsed raised). A missing file's FileNotFoundError names it where open() looked: under
the folder the snapshot was read from (Inventory.root: a test's tree, a receipt's stage), else
config.REPO. The database backend has neither missing nor unreadable sources (its snapshot
always has the files it holds), so none of this happens there.
"""
import csv
import errno
import os
import re
from pathlib import Path

_OS = re.compile(r"\[(?:Errno|WinError) (\d+)\] ")
_BYTE = re.compile(r"'(?P<codec>[^']+)' codec can't decode byte 0x(?P<byte>[0-9a-f]{2}) in position "
                   r"(?P<start>\d+): (?P<reason>.*)\Z", re.DOTALL)
_BYTES = re.compile(r"'(?P<codec>[^']+)' codec can't decode bytes in position (?P<start>\d+)-(?P<end>\d+): "
                    r"(?P<reason>.*)\Z", re.DOTALL)


def missing(path):
    """The FileNotFoundError open() raised for a repo-relative path that isn't there."""
    from decklab.lib import config, inventory
    root = inventory.current().root
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT),
                             str((Path(root) if root else config.REPO) / path))


def again(text):
    """The exception whose str is text, of the type reading the file raised (see the module
    docstring)."""
    found = _OS.match(text)
    if found:
        number = int(found[1])
        cls = {errno.EACCES: PermissionError, errno.ENOENT: FileNotFoundError}.get(number, OSError)
        return cls(text)
    found = _BYTE.match(text)
    if found:
        start = int(found["start"])
        data = bytes(start) + bytes([int(found["byte"], 16)])
        return UnicodeDecodeError(found["codec"], data, start, start + 1, found["reason"])
    found = _BYTES.match(text)
    if found:
        start, end = int(found["start"]), int(found["end"]) + 1
        return UnicodeDecodeError(found["codec"], bytes(end), start, end, found["reason"])
    return csv.Error(text)


def check(source):
    """Raise what reading source's file raised today: missing() when it isn't there (a Sheet
    with exists False), again(its error) when it couldn't be read. A product or an order record
    is always there when it's in the snapshot."""
    if getattr(source, "error", None) is not None:
        raise again(source.error)
    if getattr(source, "exists", True) is False:
        raise missing(source.path)
