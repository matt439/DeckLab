"""Restarting Deck Lab from the page: a named home admin's, through the tunnel too, so a
"Restart needed" banner seen on a phone can be dealt with without the PC.

    GET  /api/server/restart   {"may_restart", "why_not", "busy", "restarting"}
    POST /api/server/restart   {"profile", "anyway"?: bool} -> 202 {"restarting": true,
                                "started_at"} (the running server's, build.status()'s, so the
                                page knows the new one by a different started_at)

The server can't restart itself: it starts `python -m decklab.lib.homenet restart --port P
--after HELPER_DELAY` as a separate process that outlives it (on Windows out of any job it can break away from,
on Linux in a transient systemd unit of its own, since the service's stop kills what's left
in its cgroup), which waits HELPER_DELAY seconds (so this answer gets back to the page, through the tunnel
too, before the server and cloudflared stop), then stops this server as `homenet stop` does (its Forge games stop and
save what finished) and starts the task or service again. What that process says goes to
decklab/data/logs/restart.log.

Refused (why_not, and POST's 409, in plain words naming nobody) when:
- the server isn't the background one on its usual port (a test's server, one started in a
  terminal): homenet would start the task's, not this one;
- the task (Windows) or service (Linux) isn't there to start it again;
- the checkout has uncommitted application changes, or its version can't be checked
  (AGENTS.md: commit before restarting), since the new server would run them;
- a restart was asked for in the last RESTART_GRACE seconds.
Forge matchups, field runs, variant tests and practice hands in progress are "busy": the POST
answers 409 with them unless "anyway", as they stop (keeping the games they finished).
Migrations are never applied here: `python -m decklab.db migrate` stays on the PC.
"""
import os
import subprocess
import sys
import threading
import time

from decklab.lib import build, config, control, tunnel

from . import guard
from .common import ApiError, _load_json

MAX_BODY = 1024
RESTART_GRACE = 180         # seconds a restart asked for counts as under way
HELPER_DELAY = 3            # seconds the helper waits before stopping the server
EARLY_EXIT_WAIT = 1.0       # seconds to wait for the helper failing at once (under HELPER_DELAY)
NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200      # CREATE_NEW_PROCESS_GROUP: the server's Ctrl+C doesn't reach it
BREAKAWAY = 0x01000000      # CREATE_BREAKAWAY_FROM_JOB
LOG_FILE = control.LOG_FILE.with_name("restart.log")

_lock = threading.Lock()
_asked_at = None            # time.monotonic() of the last restart this server started


def _admin():
    viewer = guard.viewer()
    guard.require(viewer, "server.restart")
    return viewer


def _restarting():
    return _asked_at is not None and time.monotonic() - _asked_at < RESTART_GRACE


def _own_state():
    """This server's record (control.read_state) when it's the background one on its usual
    port, else None."""
    found = control.read_state()
    if not found or found.get("pid") != os.getpid() or not found.get("background"):
        return None
    port = found.get("port")
    return found if tunnel.usual_server(port, config.load().get("port", 8642)) else None


def _supervisor_problem():
    """Why nothing would start Deck Lab again after it stops, or None."""
    from decklab.lib import homenet
    if sys.platform == "win32":
        task = homenet.query_task(homenet.TASK_NAME)
        if task is None:
            return "Deck Lab isn't set up to start in the background, so it can't be restarted from here."
        if homenet.task_problem(task):
            return "Deck Lab's background task needs setting up again on the PC, so it can't be restarted from here."
        return None
    if sys.platform.startswith("linux"):
        from decklab.lib.homenet import service
        if not service._active(service.service_name(homenet.TASK_NAME)):
            return "Deck Lab isn't running as its background service, so it can't be restarted from here."
        return None
    return "Deck Lab can only be restarted from here on Windows or Linux."


def _code_problem():
    found = build.status()
    if found.get("error") or found.get("latest_dirty") is None:
        return "Deck Lab couldn't check its code's version, so it isn't restarted from here. Restart it on the PC."
    if found["latest_dirty"]:
        return ("Deck Lab's code on the PC has changes that aren't committed. Commit them first: "
                "a restart would run them.")
    return None


def _why_not():
    if _restarting():
        return "Deck Lab is already restarting."
    if _own_state() is None:
        return "This Deck Lab wasn't started in the background on its usual port, so it can't be restarted from here."
    return _code_problem() or _supervisor_problem()


def _busy():
    """What a restart would stop, in plain words: [] when nothing is running."""
    from . import forge_runs, practice
    out = []
    matchups = sum(1 for job in forge_runs.FORGE_JOBS.active())
    coordinated = sum(1 for job in forge_runs.COORD_JOBS.active())
    hands = sum(1 for job in practice.JOBS.active())
    if matchups:
        out.append(f"{matchups} Forge matchup{'s' if matchups != 1 else ''} playing or waiting")
    if coordinated:
        out.append(f"{coordinated} field run{'s' if coordinated != 1 else ''} or variant test{'s' if coordinated != 1 else ''}")
    if hands:
        out.append(f"{hands} practice-hand run{'s' if hands != 1 else ''}")
    return out


def view():
    """GET /api/server/restart (the module docstring), for a named home admin."""
    _admin()
    why = _why_not()
    return {"may_restart": why is None, "why_not": why, "busy": _busy(), "restarting": _restarting()}


def _command(port):
    helper = [sys.executable, "-m", "decklab.lib.homenet", "restart", "--port", str(port), "--after", str(HELPER_DELAY)]
    if sys.platform.startswith("linux"):
        # Its own transient unit: the service's stop kills whatever is left in the service's cgroup. The
        # unit's output goes to the journal unless it's sent to the log.
        return ["systemd-run", "--user", "--collect", "--quiet", f"--working-directory={config.REPO}",
                f"--property=StandardOutput=append:{LOG_FILE}", f"--property=StandardError=append:{LOG_FILE}", *helper]
    return helper


def _launch(port):
    """Start the restart helper; the Popen. OSError when it can't be started."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "ab") as log:
        log.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} Restart asked for from the page.\n".encode("utf-8"))
        log.flush()
        options = dict(cwd=str(config.REPO), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        if sys.platform != "win32":
            return subprocess.Popen(_command(port), start_new_session=True, **options)
        try:
            return subprocess.Popen(_command(port), creationflags=NO_WINDOW | NEW_GROUP | BREAKAWAY, **options)
        except OSError:
            # A job that doesn't allow breaking away: Task Scheduler's ends its processes
            # only when the task is ended, not when the server exits by itself.
            return subprocess.Popen(_command(port), creationflags=NO_WINDOW | NEW_GROUP, **options)


def restart(body):
    """POST /api/server/restart (the module docstring)."""
    global _asked_at
    viewer = _admin()       # refuse anyone else before reading the body
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, "The restart request is too large.")
    data = _load_json(body, "The restart request")
    if not isinstance(data, dict) or not set(data) <= {"profile", "anyway"} or not isinstance(data.get("anyway", False), bool):
        raise ApiError(400, "The restart request takes only the profile and anyway.")
    if data.get("profile") != viewer["id"]:
        raise ApiError(403, "You can only make changes as yourself.")
    with _lock:
        why = _why_not()
        if why:
            raise ApiError(409, why)
        busy = _busy()
        if busy and not data.get("anyway"):
            raise ApiError(409, "Restarting now would stop " + "; ".join(busy)
                           + ". Games already finished are kept.", busy=busy)
        started_at = build.status().get("started_at")
        try:
            proc = _launch(_own_state()["port"])
        except OSError:
            raise ApiError(500, "Deck Lab couldn't start its restart. Restart it on the PC.") from None
        try:
            code = proc.wait(EARLY_EXIT_WAIT)
        except subprocess.TimeoutExpired:
            code = None
        # Linux's systemd-run returns once the unit has started; elsewhere the helper exiting
        # this soon (it waits HELPER_DELAY before anything) means it couldn't even start.
        if code not in (None, 0) or (code == 0 and sys.platform == "win32"):
            raise ApiError(500, "Deck Lab's restart didn't start (decklab/data/logs/restart.log on the PC says why).")
        _asked_at = time.monotonic()
    return {"restarting": True, "started_at": started_at}
