"""OS-held session leases: another live server's queue must never look crashed.

No process enumeration, PID probing, scheduler or native worker is used. Locks
are released by the OS when a process exits, including a crash.
"""
import os
from pathlib import Path
import secrets
import re

from . import lifecycle, slots


class Lease:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.token = secrets.token_hex(16)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.folder / (self.token + ".lock")
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(self.fd, b"Deck Lab run journal session\n")
            os.fsync(self.fd)
            if not slots._lock(self.fd):
                raise OSError("Session lease unavailable")
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def inactive(self, token):
        """True proven free, False held, None absent/unreadable; unknown is never resume authority."""
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            return None
        if token == self.token and self.fd is not None:
            return False
        path = self.folder / (token + ".lock")
        try:
            lifecycle._ordinary(path, directory=False)
            fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        except (OSError, lifecycle.LifecycleError):
            return None
        if not slots._lock(fd):
            os.close(fd)
            return False
        slots._drop(fd)
        return True

    def close(self):
        if self.fd is not None:
            slots._drop(self.fd)
            self.fd = None
