"""What homenet does on the PC: the commands (install, start, stop,
restart, remove and status) and the command line (main), with what they act
on: the Task Scheduler tasks (schtasks.exe), the running server (control's
state file and stop marker, GET /api/status, its log) and this PC's name and
address. The status checklist's Server and Start at logon lines are here
too, since they read control's files. The watchdog's ensure command and its
status lines are in watchdog.py, which reaches these names through this
module.

Tests replace many of these names (_schtasks, control, probe, find_server,
time, the cmd_* functions, ...). The code that uses each one looks it up in
this module, so this is where a test patches it, and the package doesn't
offer them (test_homenet.py checks both). cmd_status reaches gather_facts
and mdns_lookup through their own modules, for the same reason."""
import argparse
import http.client
import json
import ntpath
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from decklab.lib import access, config, control, profiles, tunnel

from . import gather, profile_config, watchdog
from . import mdns as multicast         # not "mdns": cmd_status has a variable of that name
from .checks import check_addresses, check_firewall, check_network, check_sleep, exit_code, format_report, lan_of
from .common import (
    LOG_TAIL, OK, PROBE_TIMEOUT, PROBLEM, RERUN_AFTER, SCHTASKS, SCHTASKS_TIMEOUT, SERVER_SCRIPT, START_WAIT,
    STOP_WAIT, TASK_DELAY, TASK_NAME, TASK_NOT_RUN_YET, TASK_RUNNING, TASK_TERMINATED, TCP_MAXRT, WARN, WATCHDOG_EVERY,
    _SPAWN, _decode, _int, _repo_rel, _when, line, log, loopback, norm_path, say, split_args, watchdog_name,
)
from .gather import step_error
from .mdns import MDNS_WAIT
from .task import _task_file, parse_task_xml, server_arguments, task_xml, watchdog_arguments, watchdog_xml


# ------------------------------------------------------------ the task

def _python_sibling(executable, name):
    """Typed POSIX paths keep their flavour; ambiguous drive/backslash strings use Windows'."""
    executable = executable or sys.executable
    if isinstance(executable, PurePosixPath):
        return executable.with_name(name)
    text = os.fspath(executable)
    windows = bool(ntpath.splitdrive(text)[0]) or "\\" in text and not text.startswith("/")
    sibling = PureWindowsPath(text).with_name(name) if windows else Path(text).with_name(name)
    return Path(str(sibling))


def pythonw_path(executable=None):
    """The windowless pythonw.exe beside this Python (sys.executable)."""
    return _python_sibling(executable, "pythonw.exe")


def this_pythons(executable=None):
    """This Python's python.exe and pythonw.exe (Windows' firewall prompt
    makes rules for each)."""
    return [_python_sibling(executable, "python.exe"), _python_sibling(executable, "pythonw.exe")]


def pc_name():
    """This PC's name (HomePC)."""
    return socket.gethostname()


def file_exists(path):
    return os.path.exists(path)


def task_user(env=None):
    """DOMAIN\\user for the logon trigger and the principal."""
    env = os.environ if env is None else env
    user = env.get("USERNAME") or ""
    domain = env.get("USERDOMAIN") or ""
    return f"{domain}\\{user}" if domain else user


def task_problem(task, exists=None):
    """Why the task can't start Deck Lab as it stands: the program it runs,
    or the script it gives that program, isn't there (Python was upgraded or
    the repo moved). None when both are there. task is parse_task_xml's
    dict; exists(path) defaults to file_exists."""
    exists = exists or file_exists
    command = (task or {}).get("command") or ""
    program = ntpath.expandvars(command.strip().strip('"'))
    if not program or not exists(program):
        return f"The task starts {command or '(nothing)'}, which isn't there any more"
    args = split_args(task.get("arguments"))
    if not args:
        return "The task doesn't say which script to run"
    if not exists(_task_file(args[0], task.get("workdir"))):
        return f"The task runs {args[0]}, which isn't there any more"
    return None


def task_log_file(task):
    """The log the task's server writes to: its --log argument (relative to
    the task's folder), else control.LOG_FILE."""
    args = split_args((task or {}).get("arguments"))
    for i, arg in enumerate(args[1:], 1):
        if arg == "--log" and i + 1 < len(args):
            return Path(_task_file(args[i + 1], task.get("workdir")))
        if arg.startswith("--log="):
            return Path(_task_file(arg[len("--log="):], task.get("workdir")))
    return Path(control.LOG_FILE)


def _task_option(task, option):
    """The value of a --option in the task's arguments (after the script), or None."""
    args = split_args((task or {}).get("arguments"))
    for i, arg in enumerate(args[1:], 1):
        if arg == option and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(option + "="):
            return arg[len(option) + 1:]
    return None


def task_host(task):
    """The address the task's server listens on (its --host), or None."""
    return _task_option(task, "--host")


def task_port(task):
    """The port the task's server listens on (its --port), or None."""
    return _int(_task_option(task, "--port"))


def _schtasks(*args, timeout=SCHTASKS_TIMEOUT):
    """Run schtasks.exe with no window; (exit code, stdout text, stderr text).
    A schtasks that runs over timeout is killed and reported as code None."""
    try:
        done = subprocess.run([str(SCHTASKS), *args], capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=timeout, **_SPAWN)
    except subprocess.TimeoutExpired:
        return None, "", f"schtasks didn't finish within {timeout} seconds"
    except OSError as e:
        return None, "", f"schtasks can't run: {e}"
    return done.returncode, _decode(done.stdout or b""), _decode(done.stderr or b"")


def query_task(name=TASK_NAME):
    """The task's definition (parse_task_xml), or None if there's no such
    task. Read as XML (schtasks /Query /XML), never as schtasks' localized
    text."""
    code, out, _ = _schtasks("/Query", "/TN", name, "/XML")
    if code != 0 or not out.strip():
        return None
    try:
        return parse_task_xml(out)
    except ValueError:
        return None


def register_task(xml_text, name=TASK_NAME):
    """Register (or replace) the task from its XML. Returns None, or what
    schtasks said when it failed."""
    fd, path = tempfile.mkstemp(prefix="decklab-task-", suffix=".xml")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(xml_text.encode("utf-16"))          # with a BOM, as the declaration says
        code, out, err = _schtasks("/Create", "/TN", name, "/XML", path, "/F")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return None if code == 0 else _said(out, err, code)


def delete_task(name):
    """Delete the task if it's registered. Returns None (deleted, or there
    was none), or what schtasks said when it failed."""
    if query_task(name) is None:
        return None
    code, out, err = _schtasks("/Delete", "/TN", name, "/F")
    return None if code == 0 else _said(out, err, code)


def _said(out, err, code):
    text = " ".join((err or out or "").split())
    return text or f"schtasks failed (exit code {code})"


# ------------------------------------------------------------ the server

NOT_LISTENING = "nothing is listening there"


def probe(port, host="127.0.0.1", timeout=PROBE_TIMEOUT):
    """GET /api/status on the server: {"answered": False, "listening",
    "error"} when nothing answers ("listening" is True when something took
    the connection but didn't answer, False when nothing is listening, None
    when it can't be told), else {"answered": True, "deck_lab": whether it's
    Deck Lab's answer, "cards_ready", "updating", "card_error"}.

    Windows tries a refused connection three times (about 2 seconds), so
    the connection gets TCP_MAXRT of 1 second there: a closed port then
    fails in about half a second, as a timeout while connecting (checked on
    2026-10-01). A server that's there but stuck still takes the connection
    (Windows does that for it), so its timeout comes after."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    connected, quick_fail = False, False
    try:
        sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
        conn.sock = sock
        sock.settimeout(timeout)
        if sys.platform == "win32":
            try:
                sock.setsockopt(socket.IPPROTO_TCP, TCP_MAXRT, 1)
                quick_fail = True
            except OSError:
                pass
        sock.connect((host, port))
        connected = True
        conn.request("GET", "/api/status", headers={"Accept": "application/json"})
        response = conn.getresponse()
        body = response.read(65536)
    except ConnectionRefusedError:
        return {"answered": False, "listening": False, "error": NOT_LISTENING}
    except TimeoutError:
        if connected:
            return {"answered": False, "listening": True,
                    "error": f"something took the connection but didn't answer within {timeout} seconds"}
        if quick_fail:
            return {"answered": False, "listening": False, "error": NOT_LISTENING}
        return {"answered": False, "listening": None, "error": "nothing answered"}
    except (OSError, http.client.HTTPException) as e:
        return {"answered": False, "listening": None if not connected else True,
                "error": f"{type(e).__name__}: {e}"}
    finally:
        conn.close()
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        data = None
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, dict):
        return {"answered": True, "deck_lab": False, "status": response.status}
    return {"answered": True, "deck_lab": True, "status": response.status,
            "cards_ready": bool(cards.get("ready")), "updating": bool(data.get("updating")),
            "card_error": cards.get("error") or data.get("update_error")}


def server_state(port):
    """control.read_state() when it names a server on port, else None."""
    state = control.read_state()
    if isinstance(state, dict) and _int(state.get("port")) == port:
        return state
    return None


def _probe_host(state):
    host = (state or {}).get("host")
    return "127.0.0.1" if host in (None, "", "0.0.0.0", "::") else host


def find_server(port):
    """(state, probe) for the server on port: the state it recorded (None
    if it didn't) and what GET /api/status got."""
    state = server_state(port)
    return state, probe(port, _probe_host(state))


def describe_running(state, answer, port):
    """A sentence about the server that's already there on port."""
    if state:
        where = "in the background" if state.get("background") else "in a window"
        return (f"Deck Lab is already running (process {state.get('pid')}, started "
                f"{_when(state.get('started'))}, {where}).")
    if answer.get("deck_lab"):
        return (f"Deck Lab is already running on port {port}, but it didn't record itself in "
                f"{_repo_rel(control.STATE_FILE)} (it was started before Milestone 6, or from "
                "another copy of the repo), so this command can't stop it.")
    return f"Another program already answers on port {port}."


def how_to_stop(state, answer):
    if state:
        return "Stop it first with: python -m decklab.lib.homenet stop (or use restart)."
    if answer.get("deck_lab"):
        return "Stop it by pressing Ctrl+C in its window (or closing the window), then try again."
    return 'Close that program, or change "port" in decklab/config.json.'


def local_ipv4():
    """This PC's address on the network with the default route (no packet
    is sent: connecting a UDP socket only picks the route), or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))      # TEST-NET-1: never actually reached
        address = s.getsockname()[0]
        return None if address.startswith(("0.", "127.")) else address
    except OSError:
        return None
    finally:
        s.close()


def urls(port, address=None, hostname=None):
    """The addresses to open the page at: this PC, the IP address, the .local name."""
    hostname = (hostname or pc_name()).lower()
    out = [("On this PC", f"http://localhost:{port}/")]
    if address:
        out.append(("From a phone or the iPad", f"http://{address}:{port}/"))
    out.append(("Or, if the phone finds it by name", f"http://{hostname}.local:{port}/"))
    return out


def _file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _log_tail(path, lines=LOG_TAIL, start=0):
    """The last lines of the log written after byte start (all of it when
    the log is now shorter than that: it was rotated in between)."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            if size < start:
                start = 0
            f.seek(max(start, size - 16384))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return [row for row in text.splitlines() if row.strip()][-lines:]


# ------------------------------------------------------------ commands

def uses_systemd():
    """True on Linux, where main's commands act on a systemd user service (service.py)."""
    return sys.platform.startswith("linux")


def _windows_only():
    if sys.platform != "win32":
        say("Starting at logon uses Windows' Task Scheduler, so it only works on Windows.")
        return True
    return False


def profiles_ok():
    """True when config.json's profiles can be checked and pass; else False, after saying why
    (install refuses then, on Windows and Linux alike)."""
    try:
        profiles.read_checked()
    except profiles.InvalidProfiles as problem:
        say(str(problem))
        return False
    except (OSError, ValueError, TypeError):
        say("Profile configuration could not be checked. Fix decklab/config.json before installing.")
        return False
    return True


def cmd_install(name, port, no_start=False, log_path=None, port_given=False, host=None, at_logon=False):
    if not profiles_ok():
        return 1
    if _windows_only():
        return 1
    pythonw = pythonw_path()
    if not pythonw.is_file():
        say(f"pythonw.exe (the windowless Python) isn't beside this Python ({sys.executable}), so "
            "the task can't start Deck Lab without a window. Install Python from python.org, then "
            "run this again with that Python.")
        return 1
    arguments = server_arguments(SERVER_SCRIPT, port if port_given else None, log_path, host)
    error = register_task(task_xml(pythonw, arguments, config.REPO, task_user(), name, at_logon=at_logon), name)
    if error:
        say(f'The "{name}" task couldn\'t be registered: {error}')
        return 1
    task = query_task(name)
    if task is None or norm_path(task["command"]) != norm_path(pythonw):
        say(f'The "{name}" task was registered, but reading it back didn\'t show {pythonw}. '
            "Check it in Task Scheduler.")
        return 1
    if at_logon:
        say(f'Registered the "{name}" task: at each logon (after {_delay_text(TASK_DELAY)}), and on start, it starts')
    else:
        say(f'Registered the "{name}" task: python -m decklab.lib.homenet start runs it, and it starts')
    say(f"  {pythonw} {arguments}")
    say(f"  in {config.REPO}, with no window.")
    if not at_logon:
        say("It doesn't start at logon (install --at-logon turns that on).")
    if _install_watchdog(name, pythonw, at_logon) != 0:
        return 1
    if no_start:
        if at_logon:
            _leave_off(port)
        say(("It starts at the next logon, or now with: " if at_logon else "Start it with: ")
            + "python -m decklab.lib.homenet start")
        return 0
    state, answer = find_server(port)
    if not state and answer["answered"] and not answer.get("deck_lab"):
        say(f"Deck Lab can't start now, though: another program uses port {port}.")
        say(how_to_stop(state, answer))
        return 1
    if state or answer["answered"]:
        say(describe_running(state, answer, port) + " It wasn't started a second time.")
        if state and state.get("background"):
            say("To restart it as the task now says: python -m decklab.lib.homenet restart")
        elif state:
            say("To run it from the task instead: python -m decklab.lib.homenet restart")
        else:
            say(how_to_stop(state, answer))
        return 0
    _starting(port)
    return _start_task(name, port, task)


def _install_watchdog(name, pythonw, at_logon):
    """With at_logon, register the watchdog task beside the server task
    (E11-S26), else delete it if it's there: without starting at logon,
    starts are manual and Deck Lab is meant to be off until asked."""
    watch = watchdog_name(name)
    if not at_logon:
        if query_task(watch) is None:
            return 0
        error = delete_task(watch)
        if error:
            say(f'The "{watch}" task couldn\'t be removed: {error}')
            return 1
        say(f'Removed the "{watch}" task, as Deck Lab no longer starts at logon.')
        return 0
    arguments = watchdog_arguments(name)
    error = register_task(watchdog_xml(pythonw, arguments, config.REPO, task_user(), watch, start=datetime.now()),
                          watch)
    if error:
        say(f'The "{watch}" task couldn\'t be registered: {error}')
        return 1
    task = query_task(watch)
    if task is None or norm_path(task["command"]) != norm_path(pythonw):
        say(f'The "{watch}" task was registered, but reading it back didn\'t show {pythonw}. '
            "Check it in Task Scheduler.")
        return 1
    say(f'Registered the "{watch}" task: every {_delay_text(task["repeats"][0] if task["repeats"] else "")} '
        "while you're logged on it runs")
    say(f"  {pythonw} {arguments}")
    say(f'  which starts the "{name}" task if Deck Lab stopped unexpectedly (not after homenet stop).')
    return 0


def _leave_off(port):
    """install --at-logon --no-start: a Deck Lab that's off stays off until
    start or the next logon, as the install says, so the watchdog it just
    registered gets a stop marker (it would take "off with no marker" for a
    crash). A server that's running, or anything on the port, is left as it
    is: nothing is written."""
    state, answer = find_server(port)
    if state or answer.get("answered") or answer.get("listening"):
        return
    try:
        control.mark_stopped(port, "install --no-start", keep=True)
    except OSError as e:
        say(f"Couldn't record that Deck Lab stays off ({e}): the watchdog may start it within "
            f"{_delay_text(WATCHDOG_EVERY)}.")


def _starting(port):
    """Before a start that was asked for: no stop marker any more, and the
    watchdog counts its restarts from nothing again."""
    control.clear_stopped(port)
    watchdog.reset(port)


def _usable_task(name, restarting=False):
    """The task (parse_task_xml) when it's registered and the program and
    script it starts are there; else None, after saying what's wrong."""
    task = query_task(name)
    if task is None:
        say(f'The "{name}" task isn\'t registered: run python -m decklab.lib.homenet install first.')
        return None
    problem = task_problem(task)
    if problem:
        say(f"{problem}, so it can't start Deck Lab" + (" (nothing was stopped)" if restarting else "")
            + ": run python -m decklab.lib.homenet install again.")
        return None
    return task


def cmd_start(name, port):
    if _windows_only():
        return 1
    task = _usable_task(name)
    if task is None:
        return 1
    state, answer = find_server(port)
    if state or answer["answered"]:
        say(describe_running(state, answer, port))
        return 0 if (state or answer.get("deck_lab")) else 1
    _starting(port)
    return _start_task(name, port, task)


def _start_task(name, port, task=None):
    """Start the task and wait for the server to answer. When it doesn't,
    show what it wrote to its log since the start (task_log_file)."""
    log_file = task_log_file(task)
    log_start = _file_size(log_file)
    code, out, err = _schtasks("/Run", "/TN", name)
    if code != 0:
        say(f'Task Scheduler couldn\'t start the "{name}" task: {_said(out, err, code)}')
        return 1
    log(f"Starting Deck Lab (waiting up to {START_WAIT} seconds for it to answer)...")
    started, asked_again = time.monotonic(), False
    while time.monotonic() - started < START_WAIT:
        state = server_state(port)          # written once it's listening, with its address
        answer = probe(port, _probe_host(state))
        if answer["answered"]:
            if not answer.get("deck_lab"):
                say(f"Something answers on port {port}, but it isn't Deck Lab.")
                return 1
            say("Deck Lab is running.")
            host = (state or {}).get("host")
            for label, url in urls(port, None if loopback(host) else local_ipv4()):
                if loopback(host) and label != "On this PC":
                    continue
                say(f"  {label}: {url}")
            if loopback(host):
                say(f"  It listens on {host} only, so phones can't reach it.")
            return 0
        if not asked_again and time.monotonic() - started >= RERUN_AFTER:
            # A task whose last run had only just ended can still count as
            # running for a moment, and IgnoreNew then drops the start.
            _schtasks("/Run", "/TN", name)
            asked_again = True
        time.sleep(0.5)
    say(f"Deck Lab didn't answer on port {port} within {START_WAIT} seconds.")
    tail = _log_tail(log_file, start=log_start)
    if tail:
        say(f"What it wrote to its log ({log_file}) after the start:")
        for text in tail:
            say(f"  {text}")
    else:
        say(f"It wrote nothing to its log ({log_file}) after the start, so it may not have started "
            "at all. python -m decklab.lib.homenet status shows how the task last ran.")
    return 1


def cmd_stop(port):
    # First, and whether or not it's running: the watchdog then leaves it
    # off even if this stop times out and it's ended in Task Manager.
    try:
        control.mark_stopped(port, "homenet stop")
    except OSError as e:
        say(f"Couldn't record the stop ({e}): the watchdog may start Deck Lab again.")
    state, answer = find_server(port)
    result = control.request_stop(port, wait=STOP_WAIT)
    pid = (state or {}).get("pid")
    program = ntpath.basename(str((state or {}).get("python") or "pythonw.exe"))
    if result == "stopped":
        say("Deck Lab stopped.")
        return 0
    if result == "not running":
        if answer.get("deck_lab"):
            say(describe_running(state, answer, port))
            say(how_to_stop(None, answer))
            return 1
        say("Deck Lab isn't running." + (f" (Another program answers on port {port}.)"
                                         if answer["answered"] else ""))
        return 0
    if result == "timeout":
        say(f"Deck Lab was asked to stop but was still running after {STOP_WAIT} seconds"
            + (f" (process {pid})." if pid else ".")
            + f" If it doesn't stop, end {program} in Task Manager.")
        return 1
    if sys.platform.startswith("linux"):
        say(f"Deck Lab{f' (process {pid})' if pid else ''} can't be signalled from here: it may be running as "
            "another user. Stop it as that user, or press Ctrl+C in its terminal.")
        return 1
    if sys.platform != "win32":
        say("Stopping Deck Lab from here only works on Windows and Linux: press Ctrl+C in its window.")
        return 1
    # The stop event is there but can't be set from here (control.request_stop).
    who = f"Deck Lab ({program}, process {pid})" if pid else f"The Deck Lab server on port {port}"
    say(f"{who} can't be signalled from here: it may be running as administrator or in another "
        "session (another user, or a task set to run whether or not you're logged on).")
    say("Stop it with the same command from an administrator PowerShell, or end "
        + (f"{program} (process {pid})" if pid else f"the program using port {port}") + " in Task Manager.")
    return 1


def cmd_restart(name, port):
    if _windows_only():
        return 1
    task = _usable_task(name, restarting=True)
    if task is None:
        return 1
    if cmd_stop(port) != 0:
        # The stop's marker would leave Deck Lab off once it does stop (or
        # is ended in Task Manager), though a restart was asked for: a
        # restart's marker has the watchdog start it again instead.
        try:
            control.mark_stopped(port, "homenet restart", restart=True)
            say("It wasn't started again. Once it has stopped, python -m decklab.lib.homenet start starts it "
                f"(with start at logon, the watchdog does within {_delay_text(WATCHDOG_EVERY)}).")
        except OSError:
            say("It wasn't started again. Once it has stopped: python -m decklab.lib.homenet start")
        return 1
    _starting(port)
    return _start_task(name, port, task)


def cmd_remove(name, port):
    if _windows_only():
        return 1
    stopped = cmd_stop(port)
    watch = watchdog_name(name)
    if query_task(watch) is not None:
        error = delete_task(watch)
        if error:
            say(f'The "{watch}" task couldn\'t be removed: {error}')
            return 1
        say(f'Removed the "{watch}" task: nothing restarts Deck Lab after a crash.')
    if query_task(name) is None:
        say(f'The "{name}" task isn\'t registered, so there was nothing to remove.')
        return stopped
    code, out, err = _schtasks("/Delete", "/TN", name, "/F")
    if code != 0:
        say(f'The "{name}" task couldn\'t be removed: {_said(out, err, code)}')
        return 1
    say(f'Removed the "{name}" task: Deck Lab doesn\'t start at logon, and start can\'t start it until '
        "python -m decklab.lib.homenet install sets the task up again.")
    return stopped


def _delay_text(delay):
    match = re.fullmatch(r"PT(?:(\d+)M)?(?:(\d+)S)?", delay or "")
    if not match or not any(match.groups()):
        return delay or "no delay"
    minutes, seconds = (int(g or 0) for g in match.groups())
    parts = ([f"{minutes} minute{'s' * (minutes != 1)}"] if minutes else []) + \
            ([f"{seconds} second{'s' * (seconds != 1)}"] if seconds else [])
    return " ".join(parts)


# ------------------------------------------------------------ status: the server and the task

def code_changed_since(started, newest_mtime):
    """True when Deck Lab's Python code (newest_mtime, a timestamp) changed
    after the server started (its local ISO start time)."""
    if newest_mtime is None:
        return False
    try:
        when = datetime.fromisoformat(str(started))
    except (TypeError, ValueError):
        return False
    start = when.timestamp() if when.tzinfo else time.mktime(when.timetuple()) + when.microsecond / 1e6
    return newest_mtime > start + 1


def newest_code_mtime(decklab=None):
    """When Deck Lab's Python code last changed: the newest of server.py,
    every .py file under lib/ (its packages included) and the database
    package's .py files (db/*.py; not its migrations, which a restart
    doesn't apply)."""
    folder = Path(decklab or config.DECKLAB)
    times = []
    for path in [folder / "server.py", *(folder / "lib").rglob("*.py"), *(folder / "db").glob("*.py")]:
        try:
            times.append(path.stat().st_mtime)
        except OSError:
            pass
    return max(times) if times else None


def check_server(state, answer, port, log_file, code_mtime=None, other_state=None):
    """The Server lines, from the state the server recorded for port (or
    None), its answer to GET /api/status, and when Deck Lab's code last
    changed. other_state is a server recorded on another port."""
    area = "Server"
    restart = "python -m decklab.lib.homenet restart"
    if state and answer.get("deck_lab"):
        where = ("in the background (no window)" if state.get("background")
                 else "in a window (closing that window stops it)")
        log_path = state.get("log")
        text = (f"Running since {_when(state.get('started'))} (process {state.get('pid')}), {where}"
                + ("; card data ready" if answer.get("cards_ready") else "") + ". "
                + (f"Log: {log_path}" if log_path else "Its log is in its window."))
        out = [line(OK, area, text)]
        if loopback(state.get("host")):
            out.append(line(PROBLEM, area, f"It listens on {state.get('host')} only, so only this PC can "
                                           "open the page, not phones.",
                            'Take "host" out of decklab/config.json (or --host off the task: run '
                            "python -m decklab.lib.homenet install again), then restart."))
        if answer.get("updating") and not answer.get("cards_ready"):
            out.append(line(OK, area, "It's downloading the card data (the first start takes a few "
                                      "minutes); the page says so and retries by itself."))
        elif not answer.get("cards_ready"):
            reason = answer.get("card_error")
            out.append(line(WARN, area, "The card data isn't ready" + (f": {reason}" if reason else "."),
                            "It retries by itself; or run python -m decklab.lib.cards update"))
        if code_changed_since(state.get("started"), code_mtime):
            out.append(line(WARN, area, "Deck Lab's code changed after this server started, so it's "
                                        "still running the old code.", restart))
        return out
    if state:
        return [line(PROBLEM, area, f"Process {state.get('pid')} is recorded as Deck Lab's server, but "
                                    f"it doesn't answer on port {port} ({answer.get('error') or 'not Deck Lab'}).",
                     f"{restart}; if it still doesn't answer, its log may say why: "
                     f"{state.get('log') or log_file}")]
    if answer.get("answered"):
        if answer.get("deck_lab"):
            return [line(WARN, area, f"Deck Lab answers on port {port}, but it didn't record itself in "
                                     f"{_repo_rel(control.STATE_FILE)} (it was started before Milestone 6, "
                                     "or from another copy of the repo), so stop and restart can't reach it.",
                         "Press Ctrl+C in its window (or close it), then: python -m decklab.lib.homenet start")]
        return [line(PROBLEM, area, f"Another program answers on port {port}, so Deck Lab can't use it.",
                     'Close that program, or change "port" in decklab/config.json.')]
    if answer.get("listening"):
        return [line(PROBLEM, area, f"Something has port {port} open but doesn't answer ({answer.get('error')}): "
                                    "a Deck Lab server that's stuck, or another program.",
                     "If it's Deck Lab in a window, press Ctrl+C there; otherwise end the program using the "
                     "port in Task Manager (Resource Monitor > Network > Listening Ports shows which), "
                     "then: python -m decklab.lib.homenet start")]
    text = f"Deck Lab isn't running on port {port}, so the page can't open ({answer.get('error') or 'no answer'})."
    if other_state:
        text += f" A Deck Lab server is recorded on port {other_state.get('port')} instead."
    return [line(PROBLEM, area, text, "python -m decklab.lib.homenet start (install, if it isn't set "
                                      f"up yet). If it won't start, its log may say why: {log_file}")]


def check_task(task, info, script, exists=os.path.exists, error=None, user=None, pythonw=None):
    """The Start at logon lines, from the task's definition (parse_task_xml,
    or None when it isn't registered), its state and last run (info: state,
    last_run, last_result) and this repo's server.py. The task is what start
    runs, so it's checked whether or not its logon trigger is on (off, the
    default, is fine). pythonw is the pythonw.exe install would use (named
    when the task isn't set up, for network-setup.ps1 -Pythonw)."""
    area = "Start at logon"
    install = "python -m decklab.lib.homenet install"
    again = f"Run {install} again (from this repo)."
    if error:
        return [line(WARN, area, f"Couldn't read the task: {error}")]
    if task is None:
        return [line(WARN, area, "The task isn't set up, so python -m decklab.lib.homenet start can't start "
                                 "Deck Lab.",
                     install + (f" (it sets the task up to start {pythonw})" if pythonw else ""))]
    out = []
    command, args = task.get("command") or "", split_args(task.get("arguments"))
    leaf = ntpath.basename(norm_path(command))
    target = args[0] if args else ""
    if not command or not exists(ntpath.expandvars(command.strip('"'))):
        out.append(line(PROBLEM, area, f"The task starts {command or '(nothing)'}, which isn't there any "
                                       "more (was Python upgraded, moved or removed?).", again))
    elif leaf != "pythonw.exe":
        out.append(line(WARN, area, f"The task starts {command}, not pythonw.exe, so a console window "
                                    "opens (and closing it stops Deck Lab).", again))
    if not target:
        out.append(line(PROBLEM, area, "The task doesn't say which script to run.", again))
    elif norm_path(target) != norm_path(script):
        level = PROBLEM if not exists(ntpath.expandvars(target)) else WARN
        out.append(line(level, area, f"The task starts {target}, not this repo's {script}"
                        + (", and that file isn't there." if level == PROBLEM else "."), again))
    if not task.get("enabled", True):
        out.append(line(WARN, area, "The task is turned off (disabled) in Task Scheduler.", again))
    users = list(task.get("logon_users") or [])        # only enabled logon triggers
    if users and user and not any(same_user(u, user) for u in users):
        out.append(line(WARN, area, f"The task starts at {', '.join(users)}'s logon, not {user}'s.", again))
    if (task.get("time_limit") or "").upper() not in ("PT0S", ""):
        out.append(line(WARN, area, f"Task Scheduler would stop the server after {task['time_limit']} "
                                    "(an ISO 8601 duration).", again))
    out += _task_settings_lines(task, again)
    if not any(item["level"] in (WARN, PROBLEM) for item in out):
        runs = f"{command} {task.get('arguments') or ''}".rstrip()
        if users:
            out.append(line(OK, area, f"Set up: at logon, and on start, it starts {runs}."))
        else:
            out.append(line(OK, area, f"Off: Deck Lab starts only with python -m decklab.lib.homenet start, "
                                      f"which starts {runs}. ({install} --at-logon turns starting at logon "
                                      "on.)"))
    out.append(_last_run_line(info or {}, at_logon=bool(users)))
    return out


def _task_settings_lines(task, again):
    """WARN lines for task settings someone changed in Task Scheduler that
    install sets otherwise: how it logs on, its run level, its priority and
    what a second start does. A value the XML leaves out isn't judged."""
    area = "Start at logon"
    out = []
    logon_type = task.get("logon_type")
    if logon_type and logon_type.lower() != "interactivetoken":
        out.append(line(WARN, area, f"The task logs on as {logon_type}, not \"Run only when user is logged "
                                    "on\" (InteractiveToken): the server then runs in another session, where "
                                    "stop and restart can't reach it and it has no hidden window to hear "
                                    "about logging off.", again))
    if (task.get("run_level") or "").lower() == "highestavailable":
        out.append(line(WARN, area, "The task runs Deck Lab with highest privileges (as administrator), which "
                                    "it doesn't need, and stop and restart can't reach it from a normal "
                                    "PowerShell.", again))
    priority = _int(task.get("priority"))
    if priority is not None and not 4 <= priority <= 6:
        speed = ("below normal, so Forge matchups and the page are slower" if priority > 6
                 else "above normal, which can slow the rest of the PC during a matchup")
        out.append(line(WARN, area, f"The task runs at priority {priority}: {speed}.", again))
    multiple = task.get("multiple")
    if multiple and multiple.lower() != "ignorenew":
        out.append(line(WARN, area, f"A second start while it runs is set to {multiple}, not IgnoreNew (\"Do "
                                    "not start a new instance\"), so start or a logon can stop or crowd the "
                                    "running server.", again))
    return out


def same_user(trigger_user, user):
    """True when a logon trigger's user is user (DOMAIN\\name, or the name
    alone on either side). A trigger with no user, or a SID, can't be
    compared here and counts as the same."""
    if not trigger_user or trigger_user.upper().startswith("S-1-"):
        return True
    a, b = trigger_user.lower(), user.lower()
    if a == b:
        return True
    return ("\\" not in a or "\\" not in b) and a.split("\\")[-1] == b.split("\\")[-1]


def _last_run_line(info, at_logon=False):
    area = "Start at logon"
    state = info.get("state")
    result = _int(info.get("last_result"))
    result = None if result is None else result & 0xFFFFFFFF
    last_run = info.get("last_run")
    try:
        ran = datetime.fromisoformat(last_run) if last_run else None
    except ValueError:
        ran = None
    if ran is not None and ran.year < 2000:     # Task Scheduler's "never" is 1999-11-30
        ran = None
    when = ran.strftime("%Y-%m-%d %H:%M") if ran else None
    if state == "Running" or result == TASK_RUNNING:
        return line(OK, area, "The task is running now" + (f" (started {when})." if when else "."))
    if ran is None or result == TASK_NOT_RUN_YET:
        if at_logon:
            return line(OK, area, "The task hasn't run yet: it runs at the next logon "
                                  "(or now: python -m decklab.lib.homenet start).")
        return line(OK, area, "The task hasn't run yet: python -m decklab.lib.homenet start runs it.")
    if result == 0:
        return line(OK, area, f"It last ran at {when} and ended normally (stopped).")
    if result == TASK_TERMINATED:
        return line(OK, area, f"It last ran at {when} and was ended from Task Scheduler.")
    code = f"{result} (0x{result:08X})" if result is not None else "unknown"
    return line(WARN, area, f"It last ran at {when} and ended with exit code {code}: the server "
                            "couldn't start, crashed or was killed.",
                f"Its log may say why: {control.LOG_FILE}")


def check_tunnel(settings, result, ingress=None, listener=None):
    """The Tunnel lines: whether the public address (config.json's "tunnel")
    shows Cloudflare Access's login; result is tunnel.check_public's answer
    (None when there's no tunnel set up, or the check didn't finish). With
    "access" in config.json, also where cloudflared's config sends the
    hostnames (ingress: tunnel.ingress_problems' list) and whether the
    tunnel's listener refuses a visit without a login (listener:
    tunnel.check_listener's answer, None when it wasn't asked)."""
    setup = tunnel.settings_of(settings)
    if setup is None:
        return []
    area = "Tunnel"
    lines = []
    if not setup["hostname"]:
        lines.append(line(WARN, area, """config.json's "tunnel" has no "hostname", so the public address isn't """
                                      """checked."""))
    elif result is None:
        lines.append(line(WARN, area, f"The check of https://{setup['hostname']} didn't finish."))
    else:
        kind, text = result
        if kind == "login":
            lines.append(line(OK, area, f"{text}, so only the people it allows get in."))
        elif kind == "open":
            lines.append(line(PROBLEM, area, f"{text}: anyone on the internet can open and change it.",
                              "Stop Deck Lab now (python -m decklab.lib.homenet stop), then check the Deck Lab "
                              "application in Cloudflare Zero Trust (Access, Applications)."))
        else:
            lines.append(line(WARN, area, text + "."))
    try:
        port = (access.settings_of(settings) or {}).get("port")
    except ValueError as e:
        return lines + [line(PROBLEM, area, f"config.json's \"access\" is wrong: {e}. Deck Lab doesn't start "
                                            f"the tunnel without it.")]
    if port is None:
        return lines + [line(PROBLEM, area, """config.json has a "tunnel" but no "access", so Deck Lab doesn't """
                                            """start the tunnel (lib/access.py checks every outside visit's """
                                            """login).""")]
    if ingress:
        lines.append(line(PROBLEM, area, f"{setup['config']} doesn't send the tunnel to Deck Lab's tunnel listener, "
                                         f"so Deck Lab doesn't start the tunnel: {'; '.join(ingress)}.",
                          f"In {setup['config']}, set each hostname's service to http://127.0.0.1:{port}, then "
                          f"python -m decklab.lib.homenet restart."))
    elif ingress is not None:
        lines.append(line(OK, area, f"{setup['config']} sends the tunnel to Deck Lab's tunnel listener "
                                    f"(127.0.0.1:{port})."))
    if listener is not None:
        kind, text = listener
        if kind == "refuses":
            lines.append(line(OK, area, text + "."))
        elif kind == "open":
            lines.append(line(PROBLEM, area, f"{text}: something other than Deck Lab's check answers there.",
                              f"Find what listens on port {port} (Resource Monitor > Network > Listening Ports) "
                              f"and stop it, or change \"access\" \"port\" in config.json."))
        else:
            lines.append(line(WARN, area, f"{text} (is Deck Lab running?)."))
    return lines


# ------------------------------------------------------------ the status command and the command line

def cmd_status(name, port):
    started = time.monotonic()
    state = control.read_state()
    mine = state if isinstance(state, dict) and _int(state.get("port")) == port else None
    other = state if isinstance(state, dict) and mine is None else None
    hostname = pc_name()
    # The server's answer and the mDNS lookup run while PowerShell does
    # (local_ipv4 is the address on the default route, as PowerShell finds).
    found = {}
    try:
        settings = config.load()
    except (OSError, ValueError, TypeError):
        settings = {}
    public = (tunnel.settings_of(settings) or {}).get("hostname")
    try:
        access_port = (access.settings_of(settings) or {}).get("port") if public is not None else None
    except ValueError:
        access_port = None
    helpers = [threading.Thread(target=lambda: found.update(answer=probe(port, _probe_host(mine))), daemon=True),
               threading.Thread(target=lambda: found.update(mdns=multicast.mdns_lookup(f"{hostname}.local",
                                                                                       local_ipv4())),
                                daemon=True)]
    if public:
        helpers.append(threading.Thread(target=lambda: found.update(public=tunnel.check_public(public)),
                                        daemon=True))
    if access_port:
        helpers.append(threading.Thread(target=lambda: found.update(
            listener=tunnel.check_listener(access_port, public, PROBE_TIMEOUT)), daemon=True))
    for helper in helpers:
        helper.start()
    facts = gather.gather_facts(name, port)
    for helper in helpers:
        helper.join(max(PROBE_TIMEOUT + MDNS_WAIT, tunnel.CHECK_TIMEOUT) + 5)
    answer = found.get("answer") or {"answered": False, "error": "the check didn't finish"}
    mdns = found.get("mdns") or {"answered": False, "addresses": [], "error": "the lookup didn't finish"}
    network = facts.get("network")

    task_facts = facts.get("task")
    task, task_error = None, step_error(facts, "task")
    if isinstance(task_facts, dict) and task_facts.get("xml"):
        try:
            task = parse_task_xml(task_facts["xml"])
        except ValueError as e:
            task_error = str(e)
    log_file = (mine or {}).get("log") or control.LOG_FILE
    server_programs = []
    if mine and mine.get("python"):
        server_programs.append(mine["python"])
    server_programs.append(task["command"] if task and task.get("command") else str(pythonw_path()))
    python_programs = this_pythons()

    lines = profile_config.check(settings)
    lines += check_server(mine, answer, port, log_file, newest_code_mtime(), other)
    lines += check_task(task, task_facts if isinstance(task_facts, dict) else {}, str(SERVER_SCRIPT),
                        exists=file_exists, error=task_error, user=task_user(), pythonw=str(pythonw_path()))
    lines += watchdog.status_lines(name, port, task, facts, mine is not None and bool(answer.get("deck_lab")))
    lines += check_network(network, step_error(facts, "network"))
    lines += check_firewall(facts.get("firewall"), port, server_programs, python_programs,
                            step_error(facts, "firewall"), lan=lan_of(network))
    lines += check_addresses(network, hostname, mdns, port)
    lines += check_sleep(facts.get("power"), step_error(facts, "power"))
    lines += check_tunnel(settings, found.get("public"), tunnel.ingress_problems(settings, port),
                          found.get("listener"))
    seconds = time.monotonic() - started
    header = (f"Deck Lab status, {datetime.now().strftime('%Y-%m-%d %H:%M')} (port {port}; checked in "
              f"{seconds:.1f} s, of which PowerShell {facts.get('seconds', 0):.1f} s)")
    footer = ("These checks run on the PC itself, so they can't prove a phone gets through: the real test "
              "is opening the address above on a phone on the home Wi-Fi.")
    say(format_report(lines, header=header, footer=footer))
    return exit_code(lines)


def main(argv=None):
    try:
        settings, config_error = config.load(), None
    except (OSError, ValueError, TypeError) as e:     # unreadable, not JSON, or not an object
        settings, config_error = {}, f"{type(e).__name__}: {e}"
    default_port = _int(settings.get("port"), 8642)
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.homenet",
                                     description="Start, stop and restart Deck Lab in the background (at "
                                                 "logon too, if installed with --at-logon), and check "
                                                 "that phones can reach it.")
    parser.add_argument("command", choices=("install", "remove", "start", "stop", "restart", "status", "ensure"),
                        help="ensure is what the watchdog task runs (install --at-logon sets it up)")
    parser.add_argument("--no-start", action="store_true", help="install: register the task but don't start it")
    parser.add_argument("--at-logon", action="store_true",
                        help="install: also start Deck Lab at every logon (off unless this is given)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"the server's port (default {default_port}, from decklab/config.json)")
    parser.add_argument("--task", default=TASK_NAME, help=f'the task\'s name (default "{TASK_NAME}"; for testing)')
    parser.add_argument("--log", default=None, help="install: the server's log file (default: "
                                                    "decklab/data/logs/server.log)")
    parser.add_argument("--host", default=None, help="install: the address the server listens on (default: "
                                                     "all interfaces; 127.0.0.1 for a test task)")
    args = parser.parse_args(argv)
    if args.command == "ensure":
        # The port comes from the task (or config.json, read there), and a
        # config.json that can't be read is logged there, once.
        return watchdog.cmd_ensure(args.task, args.port)
    if config_error:
        where = _repo_rel(config.CONFIG_FILE)
        # stop, status and remove need only the port; install, start and
        # restart would start a server that can't read its config either.
        if args.command in ("stop", "status", "remove") and args.port is not None:
            log(f"Note: {where} can't be read ({config_error}); the server won't start until it's fixed.")
        else:
            say(f"{where} can't be read: {config_error}")
            say("Fix it first: Deck Lab's server can't start without it either. To stop Deck Lab, check on "
                f"it or remove its task meanwhile, give the port (8642 unless {where} sets another): "
                "python -m decklab.lib.homenet stop --port 8642 (or status, or remove, with --port 8642).")
            return 1
    port = args.port if args.port is not None else default_port
    if uses_systemd():
        # A systemd user service instead of Task Scheduler's task (service.py, E11-S33).
        from . import service
        if args.command == "install":
            return service.install(args.task, port, args.no_start, args.log, port_given=args.port is not None,
                                       host=args.host, at_logon=args.at_logon)
        return service.COMMANDS[args.command](args.task, port)
    if args.command == "install":
        return cmd_install(args.task, port, args.no_start, args.log, port_given=args.port is not None,
                           host=args.host, at_logon=args.at_logon)
    if args.command == "start":
        return cmd_start(args.task, port)
    if args.command == "stop":
        return cmd_stop(port)
    if args.command == "restart":
        return cmd_restart(args.task, port)
    if args.command == "remove":
        return cmd_remove(args.task, port)
    return cmd_status(args.task, port)
