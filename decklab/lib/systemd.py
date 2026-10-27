"""systemd user units on Linux, for homenet's server service and the nightly timer
(E11-S33): where a user's units go, systemctl --user, and reading a unit's state.

Everything runs as the user: no root, no system units. A user manager runs only while
that user is logged in, unless lingering is on (loginctl enable-linger), which lets the
units start at boot and keep running after logging out; linger() says which.

Tests replace systemctl (and loginctl's run) here; the code using them looks them up
in this module.
"""
import os
import subprocess
import sys
from pathlib import Path

TIMEOUT = 30                        # seconds for one systemctl call


def supported():
    """True on Linux, where these units are how Deck Lab runs in the background."""
    return sys.platform.startswith("linux")


def unit_dir(env=None):
    """The folder a user's own units go in: $XDG_CONFIG_HOME/systemd/user, else ~/.config/systemd/user."""
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if base.startswith("/") else Path(env.get("HOME") or Path.home()) / ".config"
    return root / "systemd" / "user"


def _run(args, timeout=TIMEOUT):
    """(exit code, stdout, stderr) of a command; 127 when it isn't installed."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, errors="replace")
    except FileNotFoundError:
        return 127, "", f"{args[0]} isn't installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{args[0]} didn't answer within {timeout} seconds"
    except OSError as e:
        return 126, "", str(e)
    return done.returncode, done.stdout, done.stderr


def systemctl(*args, timeout=TIMEOUT):
    """systemctl --user args: (exit code, stdout, stderr)."""
    return _run(["systemctl", "--user", *args], timeout)


def said(out, err, code):
    """What a failed call said, in one line."""
    text = " ".join((err or out or "").split())
    return text or f"exit code {code}"


def show(unit, *properties):
    """{property: value} of unit from systemctl --user show, or None when the user
    manager can't be asked (not running, no systemctl)."""
    code, out, _ = systemctl("show", unit, "--no-pager", "-p", ",".join(properties))
    if code != 0:
        return None
    found = {}
    for text in out.splitlines():
        key, sep, value = text.partition("=")
        if sep:
            found[key] = value
    return found


def write_units(units, folder=None):
    """Write {file name: text} into the user unit folder (atomically, UTF-8, LF), then
    daemon-reload. None when done, else what went wrong."""
    folder = Path(folder or unit_dir())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in units.items():
            temp = folder / f".{name}.tmp"
            temp.write_bytes(text.encode("utf-8"))
            os.replace(temp, folder / name)
    except OSError as e:
        return f"the unit files couldn't be written in {folder}: {e}"
    code, out, err = systemctl("daemon-reload")
    if code != 0:
        return f"systemctl --user daemon-reload failed: {said(out, err, code)}"
    return None


def remove_units(names, folder=None):
    """Delete these unit files (those that are there) and daemon-reload. None when done,
    else what went wrong."""
    folder = Path(folder or unit_dir())
    try:
        for name in names:
            (folder / name).unlink(missing_ok=True)
    except OSError as e:
        return f"the unit files couldn't be removed from {folder}: {e}"
    code, out, err = systemctl("daemon-reload")
    if code != 0:
        return f"systemctl --user daemon-reload failed: {said(out, err, code)}"
    return None


def linger(user=None):
    """True when the user's units run without them logged in (loginctl enable-linger),
    False when they don't, None when it can't be told."""
    user = user or os.environ.get("USER") or ""
    if not user:
        return None
    code, out, _ = _run(["loginctl", "show-user", user, "-p", "Linger", "--value"])
    if code != 0:
        return None
    value = out.strip().lower()
    return True if value == "yes" else False if value == "no" else None


def linger_note():
    """A line saying the units stop at logout, when lingering is off; else None."""
    if linger() is False:
        return ("Note: systemd runs your units only while you're logged in. To run them at boot and after "
                "logging out too: loginctl enable-linger")
    return None
