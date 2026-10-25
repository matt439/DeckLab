"""What the rest of homenet shares: the settings and constants, the two
output helpers, and small helpers that both the commands and the status
checks use (reading a command line, comparing paths, the checklist's lines).
Nothing here is replaced by tests, so the other modules import these names
directly."""
import ntpath
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from decklab.lib import config

TASK_NAME = "Deck Lab"
# The logon trigger waits this long. The server listens on every interface,
# so it doesn't need the network to start, but its first card-data check
# does (and a failed check waits 10 minutes before the next one); 30 seconds
# lets DHCP finish and keeps the server out of the way of the desktop loading.
TASK_DELAY = "PT30S"
# Task Scheduler's own default priority (7) is below normal and would slow
# Forge and the page; 5 is normal.
TASK_PRIORITY = 5
SERVER_SCRIPT = config.DECKLAB / "server.py"
# The watchdog task (E11-S26, watchdog.py): installed with --at-logon only,
# it runs `ensure` this often while the user is logged on, and Task Scheduler
# ends a run that takes longer than its time limit (a start waits up to
# START_WAIT). Below-normal priority, as it's only a check.
WATCHDOG_EVERY = "PT5M"
WATCHDOG_TIME_LIMIT = "PT2M"
WATCHDOG_PRIORITY = 7
WATCHDOG_GIVE_UP = 3        # restarts in a row that don't stay up before it stops trying
WATCHDOG_STABLE = 600       # seconds a server must have run for its restarts to stop counting
WATCHDOG_LOG_BYTES = 200_000    # watchdog.log is rotated at this size, keeping one old file
# After a logon (the logon trigger waits TASK_DELAY, then the server needs up
# to START_WAIT) or a start that was asked for, a server that isn't listening
# yet is starting, not down: the watchdog waits this many seconds first.
WATCHDOG_GRACE = 120
SETUP_SCRIPT = r"decklab\network-setup.ps1"
SETUP_RUN = rf"powershell -ExecutionPolicy Bypass -File {SETUP_SCRIPT}"
# The rules network-setup.ps1 makes, and the start of their description: it
# only ever removes Allow rules with these names or that description.
SETUP_RULE_NAMES = ("Deck Lab (TCP {port})", "Deck Lab (pythonw)")
SETUP_MARKER = rf"Added by {SETUP_SCRIPT}"
START_WAIT = 20         # seconds start waits for the server to answer
RERUN_AFTER = 5         # ... asking Task Scheduler once more after this many
STOP_WAIT = 30          # seconds stop waits for the server to exit (control.STOP_WAIT)
PROBE_TIMEOUT = 2       # seconds for GET /api/status
PS_TIMEOUT = 30         # seconds for the PowerShell call that gathers the facts
SCHTASKS_TIMEOUT = 30   # seconds for any one schtasks command
LOG_TAIL = 15           # log lines start shows when the server doesn't answer
OK, WARN, PROBLEM = "OK", "WARN", "PROBLEM"

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
# Task Scheduler's own result codes (LastTaskResult); anything else is the
# server's exit code.
TASK_RUNNING, TASK_NOT_RUN_YET, TASK_TERMINATED = 0x41301, 0x41303, 0x41306
TCP_MAXRT = 5          # Windows' socket option: seconds a connection attempt may take
PROFILES = ("domain", "private", "public")
PROFILE_BITS = {"domain": 1, "private": 2, "public": 4}
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
_SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
SCHTASKS = _SYSTEM32 / "schtasks.exe"
POWERSHELL = _SYSTEM32 / "WindowsPowerShell" / "v1.0" / "powershell.exe"


def watchdog_name(name=TASK_NAME):
    """The watchdog task's name for the server task name ("Deck Lab watchdog")."""
    return f"{name} watchdog"


def log(text):
    """One line to stderr (pythonw has none)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


def say(text=""):
    """A line of the command's own output (stdout)."""
    if sys.stdout is not None:
        print(text, flush=True)


def _decode(data):
    """Text from a Windows tool's output: UTF-16 with a BOM, UTF-8, or the
    console's code page."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("oem" if sys.platform == "win32" else "latin-1", "replace")


def split_args(text):
    """A Windows command line's arguments, read the way CommandLineToArgvW
    reads them: spaces separate, double quotes group, and backslashes are
    literal unless they come before a quote."""
    args, current, quoted, have, i = [], [], False, False, 0
    text = text or ""
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            j = i
            while j < len(text) and text[j] == "\\":
                j += 1
            count = j - i
            if j < len(text) and text[j] == '"':
                current.append("\\" * (count // 2))
                if count % 2:
                    current.append('"')
                    i = j + 1
                else:
                    i = j
                have = True
                continue
            current.append("\\" * count)
            have, i = True, j
            continue
        if ch == '"':
            if quoted and i + 1 < len(text) and text[i + 1] == '"':
                current.append('"')         # "" inside quotes is a literal quote
                i += 2
                continue
            quoted, have = not quoted, True
        elif ch in " \t" and not quoted:
            if have:
                args.append("".join(current))
                current, have = [], False
        else:
            current.append(ch)
            have = True
        i += 1
    if have:
        args.append("".join(current))
    return args


def norm_path(path):
    """A Windows path in one form for comparing: variables expanded, quotes
    off, separators and case made the same."""
    if not path:
        return ""
    path = ntpath.expandvars(str(path).strip().strip('"'))
    return ntpath.normcase(ntpath.normpath(path))


def loopback(host):
    """True for an address only this PC can reach (127.x.x.x, ::1, localhost)."""
    host = str(host or "").strip().lower().strip("[]")
    return host == "localhost" or host == "::1" or host.startswith("127.")


def _repo_rel(path):
    try:
        return Path(path).resolve().relative_to(config.REPO).as_posix()
    except (ValueError, OSError, TypeError):
        return str(path)


def line(level, area, text, fix=None):
    return {"level": level, "area": area, "text": text, "fix": fix}


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _when(iso):
    """A local ISO time as "2026-10-01 18:02", or the text as it is."""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(iso or "an unknown time")
