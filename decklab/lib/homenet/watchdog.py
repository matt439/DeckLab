"""Restarting Deck Lab after a crash (E11-S26): the watchdog task's ensure
command, its record, and status's "Restart after a crash" lines.

install --at-logon registers a second task beside "Deck Lab": "Deck Lab
watchdog" (task.py's watchdog_xml). Every WATCHDOG_EVERY (5 minutes) while
the user is logged on it runs pythonw.exe -m decklab.lib.homenet ensure
--task "Deck Lab", which starts the server only when all of these hold:
- the "Deck Lab" task is there, can start the server, is enabled and starts
  it at logon (without --at-logon, starts are manual and off is normal);
- there's no stop marker for the port (control.read_stopped: homenet stop,
  server.py --stop, install --no-start of a server that's off and a server
  stopped on request write one; start, restart, install and the server
  itself, once listening, clear it), or the marker is a restart's whose stop
  didn't finish (it was meant to run again);
- nothing answers or holds the port, and no live server is recorded;
- it isn't starting: the logon (whose trigger starts it after TASK_DELAY)
  and the last start that was asked for (reset's asked_at) are both
  WATCHDOG_GRACE seconds ago or more, so a check that lands in a start
  neither runs the task early nor counts a restart that didn't happen;
- it hasn't given up: after WATCHDOG_GIVE_UP restarts in a row that didn't
  stay up (a server must run WATCHDOG_STABLE seconds for its restarts to stop
  counting), it stops trying until start, restart or the next logon.
It always starts the server through the "Deck Lab" task (commands._start_task),
never pythonw itself, so the server's priority and log stay the task's, and
two starts at once (the watchdog and homenet start) can't both run: the task
ignores a second start while one runs, and the server takes its port for
exclusive use. A server that's alive but stuck isn't killed: that would lose
a matchup's games, and status already shows it as a PROBLEM.

The record (record_path: watchdog-<port>.json beside the state file) keeps
the last reason, the restarts in a row, the last ten restarts and when a
start was last asked for; it starts again when the logon time changes. The
log (watchdog_log: watchdog.log beside the server's log, rotated at
WATCHDOG_LOG_BYTES) gets a line only when the reason changes or a restart
happens, never every 5 minutes, and never the server's requests: times, the
port and results only. Neither file is in git, and nothing here reaches the
page or the API.

decide() is the choice alone (pure), so it's tested on its own. The task,
the server and control are reached through commands (commands.query_task,
commands.probe, commands.server_state, commands._start_task,
commands.control), so the tests' patches there reach this module too; this
module has none of those names itself.
"""
import json
import ntpath
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from decklab.lib import config
from decklab.lib.control import open_log, write_state

from . import commands
from .common import (
    OK, PROBLEM, TASK_NAME, TASK_NOT_RUN_YET, TASK_RUNNING, TASK_TERMINATED, WARN, WATCHDOG_EVERY,
    WATCHDOG_GIVE_UP, WATCHDOG_GRACE, WATCHDOG_LOG_BYTES, WATCHDOG_STABLE, _int, _repo_rel, _when, line, norm_path,
    say, split_args, watchdog_name,
)
from .gather import step_error
from .task import parse_task_xml, watchdog_arguments

RECORD_VERSION = 1
RESTARTS_KEPT = 10
DEFAULT_PORT = 8642
AREA = "Restart after a crash"
REINSTALL = "python -m decklab.lib.homenet install --at-logon --no-start"
RECENT = timedelta(hours=24)        # a restart this recent is a WARN in status


# ------------------------------------------------------------ the record and the log

def record_path(port):
    """The watchdog's record for port: watchdog-<port>.json beside the state file."""
    return Path(commands.control.STATE_FILE).with_name(f"watchdog-{int(port)}.json")


def watchdog_log():
    """The watchdog's log: watchdog.log beside the server's log."""
    return Path(commands.control.LOG_FILE).with_name("watchdog.log")


def load_record(port):
    """The record for port (a dict; empty when there's none or it can't be read)."""
    try:
        data = json.loads(record_path(port).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_record(record, port):
    """Write the record, atomically. Raises OSError."""
    write_state(record, path=record_path(port))


def reset(port):
    """Start the record for port again, as a start that was asked for does:
    the restarts count from nothing, a give-up ends, and asked_at (now)
    keeps the watchdog off the start for WATCHDOG_GRACE seconds. Never
    raises (a record that can't be written is removed if it can be)."""
    record = _fresh(port, commands.control.logon_time())
    record["asked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        save_record(record, port)
    except OSError:
        try:
            record_path(port).unlink(missing_ok=True)
        except OSError:
            pass


def _fresh(port, logon):
    return {"version": RECORD_VERSION, "port": int(port), "logon": logon, "reason": None, "since": None,
            "failures": 0, "restarts": [], "gave_up_at": None}


def _seconds(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _same_logon(a, b):
    """True unless both logon times are known and differ."""
    then, now = _seconds(a), _seconds(b)
    return then is None or now is None or abs(then - now) <= 2


# ------------------------------------------------------------ the choice

def decide(stopped, answer, alive_state, problem, record, now, since=None):
    """What ensure does, as (action, reason). action is "start", "leave",
    "reset" (leave it, and its restarts stop counting: it has stayed up) or
    "give-up" (leave it, and stop trying). stopped is the stop marker
    (control.read_stopped) or None; answer is commands.probe's; alive_state
    the live server recorded on the port (commands.server_state) or None;
    problem why the task can't or shouldn't start it ("no-task",
    "task-broken", "task-disabled", "manual-starts", "no-config") or None;
    record the watchdog's record; now seconds since 1970; since when the
    logon or the last start that was asked for happened, whichever is later
    (seconds), or None.

    In order: a task problem; a stop marker (not a restart's: that one was
    meant to run again); Deck Lab answering (a restart
    counts as stable after WATCHDOG_STABLE seconds, from the server's start
    or else the watchdog's last restart); having given up; another program
    answering; something holding the port without answering; a live server
    recorded that isn't listening yet (or any more); a logon or a start less
    than WATCHDOG_GRACE seconds ago (it's on its way); else it's down, and is
    started unless WATCHDOG_GIVE_UP restarts in a row haven't stayed up."""
    record, answer = record or {}, answer or {}
    if problem:
        return "leave", problem
    if stopped and not stopped.get("restart"):
        return "leave", "stopped-on-purpose"
    if answer.get("answered") and answer.get("deck_lab"):
        restarts = record.get("restarts") or []
        started = _seconds((alive_state or {}).get("started"))
        if started is None and restarts:
            started = _seconds(restarts[-1].get("at"))
        if started is not None and now - started >= WATCHDOG_STABLE:
            return "reset", "running"
        return "leave", "running"
    if record.get("gave_up_at"):
        return "leave", "gave-up"
    if answer.get("answered"):
        return "leave", "another-program"
    if answer.get("listening"):
        return "leave", "not-answering"
    if alive_state:
        return "leave", "starting"
    if since is not None and now - since < WATCHDOG_GRACE:
        return "leave", "just-started"
    if (_int(record.get("failures"), 0) or 0) >= WATCHDOG_GIVE_UP:
        return "give-up", "gave-up"
    return "start", "down"


def _task_problem(task):
    if task is None:
        return "no-task"
    if commands.task_problem(task):
        return "task-broken"
    if not task.get("enabled", True):
        return "task-disabled"
    if not task.get("logon_users"):
        return "manual-starts"
    return None


def _text(reason, name, port, task=None, stopped=None, state=None, error=None, log_file=None):
    """The log's line for a reason."""
    if reason == "stopped-on-purpose":
        if (stopped or {}).get("by") == "unreadable":
            return (f"The stop marker {_repo_rel(commands.control.stop_marker_path(port))} can't be read, so it "
                    "counts as stopped on purpose: leaving Deck Lab off.")
        when = f" at {_when(stopped.get('at'))}" if stopped.get("at") else ""
        return (f"Deck Lab (port {port}) was stopped on purpose{when} ({stopped.get('by') or 'unknown'}): leaving "
                "it off until python -m decklab.lib.homenet start, restart or the next logon.")
    texts = {
        "running": f"Deck Lab is running on port {port}.",
        "another-program": f"Another program answers on port {port}: leaving it alone (Deck Lab can't start there).",
        "not-answering": (f"Something holds port {port} but doesn't answer (a stuck Deck Lab server?): leaving it "
                          "alone. python -m decklab.lib.homenet status shows it."),
        "just-started": (f"Deck Lab was started moments ago (a logon or a start that was asked for): giving it "
                         f"{WATCHDOG_GRACE} seconds to answer on port {port}."),
        "starting": (f"A Deck Lab server is recorded (process {(state or {}).get('pid')}) but doesn't answer on "
                     f"port {port}: leaving it."),
        "no-task": (f'The "{name}" task isn\'t registered, so there\'s nothing to start Deck Lab with: '
                    "python -m decklab.lib.homenet install --at-logon"),
        "task-broken": f"{commands.task_problem(task) if task else 'The task is broken'}: run python -m "
                       "decklab.lib.homenet install --at-logon again.",
        "task-disabled": f'The "{name}" task is turned off in Task Scheduler: leaving Deck Lab off.',
        "manual-starts": (f'The "{name}" task doesn\'t start Deck Lab at logon, so starts are manual: leaving it '
                          "off (install without --at-logon removes this watchdog)."),
        "no-config": (f"decklab/config.json can't be read ({error}), so the port isn't known: leaving Deck Lab "
                      "alone until it's fixed."),
        "gave-up": (f"Deck Lab didn't stay up after {WATCHDOG_GIVE_UP} restarts in a row, so the watchdog stops "
                    "trying until python -m decklab.lib.homenet start, restart or the next logon. The server's "
                    f"log may say why: {log_file}"),
    }
    return texts.get(reason, reason)


# ------------------------------------------------------------ ensure

def cmd_ensure(name=TASK_NAME, port=None):
    """What the watchdog task runs: start Deck Lab through the name task if
    it stopped unexpectedly (decide). 0 when it checked (whatever it found),
    1 when the check itself failed (the task's last result then shows it).
    With no console (pythonw), everything it and a start say goes to
    watchdog_log(); with one, its own lines go there and to the console."""
    if sys.platform != "win32":
        say("The watchdog uses Windows' Task Scheduler, so it only works on Windows.")
        return 0
    background = sys.stdout is None or sys.stderr is None
    saved = sys.stdout, sys.stderr
    stream = open_log(watchdog_log(), max_bytes=WATCHDOG_LOG_BYTES, backups=1)
    if background:
        sys.stdout = sys.stderr = stream

    def note(text):
        stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}"
        stream.write(stamped + "\n")
        if not background:
            say(stamped)

    try:
        return _ensure(name, port, note)
    except Exception:                       # noqa: BLE001 (logged, and the task's result says so)
        note(f"The watchdog's check failed:\n{traceback.format_exc()}")
        return 1
    finally:
        if background:
            sys.stdout, sys.stderr = saved
        stream.close()


def _ensure(name, port, note):
    now = datetime.now().astimezone()
    task = commands.query_task(name)
    problem, error = _task_problem(task), None
    if port is None:
        port = commands.task_port(task)
    if port is None:
        try:
            port = _int(config.load().get("port"), DEFAULT_PORT)
        except (OSError, ValueError, TypeError, AttributeError) as e:
            port, problem, error = DEFAULT_PORT, problem or "no-config", f"{type(e).__name__}: {e}"
    logon = commands.control.logon_time()
    record = load_record(port)
    if not record or not _same_logon(record.get("logon"), logon):
        record = _fresh(port, logon)        # a new logon: its restarts count from nothing
    record["logon"] = logon or record.get("logon")
    before = json.dumps(record, sort_keys=True)
    stopped = state = answer = None
    if not problem:
        stopped = commands.control.read_stopped(port, logon=logon)
    if not problem and (not stopped or stopped.get("restart")):
        state = commands.server_state(port)
        host = (state or {}).get("host") or commands.task_host(task)
        answer = commands.probe(port, commands._probe_host({"host": host}))
    since = max((t for t in (_seconds(logon), _seconds(record.get("asked_at"))) if t is not None), default=None)
    action, reason = decide(stopped, answer, state, problem, record, now.timestamp(), since)
    log_file = commands.task_log_file(task)
    if reason != record.get("reason") and action != "start":
        note(_text(reason, name, port, task, stopped, state, error, log_file))
        record["reason"], record["since"] = reason, now.isoformat(timespec="seconds")
    if action == "reset":
        record["failures"], record["gave_up_at"] = 0, None
    elif action == "give-up":
        record["gave_up_at"] = now.isoformat(timespec="seconds")
    elif action == "start":
        failures = (_int(record.get("failures"), 0) or 0) + 1
        record.update(failures=failures, reason="down", since=now.isoformat(timespec="seconds"))
        note(f"Deck Lab isn't running on port {port} and wasn't stopped on purpose: starting it through the "
             f'"{name}" task (restart {failures} of {WATCHDOG_GIVE_UP} before the watchdog gives up).')
        _save(record, port, note)           # before the start: a start that hangs still counts
        code = commands._start_task(name, port, task)
        record["restarts"] = (list(record.get("restarts") or []) + [
            {"at": now.isoformat(timespec="seconds"), "answered": code == 0}])[-RESTARTS_KEPT:]
        if code == 0:
            record["reason"] = "running"
            note("It answers again.")
        else:
            note(f"It didn't answer. The server's log may say why: {log_file}")
    if json.dumps(record, sort_keys=True) != before:
        _save(record, port, note)
    return 0


def _save(record, port, note):
    try:
        save_record(record, port)
    except OSError as e:
        note(f"Can't write {_repo_rel(record_path(port))}: {e}")


# ------------------------------------------------------------ status

def status_lines(name, port, task, facts, server_running):
    """status's "Restart after a crash" lines: the watchdog task from the
    gathered facts ("watchdog"), the record and the stop marker for port."""
    watch_facts = facts.get("watchdog")
    watch, error = None, step_error(facts, "watchdog")
    if isinstance(watch_facts, dict) and watch_facts.get("xml"):
        try:
            watch = parse_task_xml(watch_facts["xml"])
        except ValueError as e:
            error = str(e)
    return check_watchdog(task, watch, watch_facts if isinstance(watch_facts, dict) else {}, load_record(port),
                          commands.control.read_stopped(port), server_running, name=name, error=error,
                          exists=commands.file_exists, log_file=commands.task_log_file(task))


def check_watchdog(task, watchdog, info, record, stopped, server_running, name=TASK_NAME, error=None,
                   exists=None, now=None, log_file=None):
    """The Restart after a crash lines, from the server task (parse_task_xml,
    or None: then Start at logon already says so, and there's nothing here),
    the watchdog task (or None when it isn't registered), its state and last
    run (info), the watchdog's record, the stop marker (or None) and whether
    the server is running. Only a watchdog that gave up is a PROBLEM."""
    if task is None:
        return []
    exists = exists or commands.file_exists
    now = now or datetime.now().astimezone()
    at_logon = bool(task.get("logon_users"))
    watch = watchdog_name(name)
    if error and at_logon:
        return [line(WARN, AREA, f"Couldn't read the watchdog task: {error}")]
    if watchdog is None:
        if not at_logon:
            return []
        return [line(WARN, AREA, "Deck Lab starts at logon, but nothing restarts it if it stops unexpectedly: its "
                                 "task was set up before the watchdog (E11-S26).", REINSTALL)]
    if not at_logon:
        return [line(WARN, AREA, f'The "{watch}" task is there, but Deck Lab doesn\'t start at logon, so the '
                                 "watchdog only notes that starts are manual.",
                     "python -m decklab.lib.homenet install (without --at-logon) removes it; " + REINSTALL
                     + " starts Deck Lab at logon too")]
    out = _settings_lines(watchdog, name, exists)
    if not out:
        out.append(line(OK, AREA, f"Checks every {_minutes(WATCHDOG_EVERY)} and restarts Deck Lab if it stopped "
                                  "unexpectedly (not after homenet stop)."))
    record = record or {}
    log_text = f"{_repo_rel(watchdog_log())}, and the server's log ({log_file or commands.control.LOG_FILE})"
    if record.get("gave_up_at"):
        out.append(line(PROBLEM, AREA, f"The watchdog gave up at {_when(record['gave_up_at'])} after "
                                       f"{WATCHDOG_GIVE_UP} restarts in a row that didn't stay up.",
                        f"Its log: {log_text}; then python -m decklab.lib.homenet start"))
    restarts = record.get("restarts") or []
    last = restarts[-1] if restarts and isinstance(restarts[-1], dict) else None
    at = _seconds(last.get("at")) if last else None
    if at is not None:
        text = f"The watchdog restarted Deck Lab at {_when(last['at'])} after it stopped unexpectedly" + (
            "." if last.get("answered") else ", but it didn't answer.")
        if now.timestamp() - at < RECENT.total_seconds():
            out.append(line(WARN, AREA, text, f"The server's log around that time may say why it stopped: "
                                              f"{log_file or commands.control.LOG_FILE}"))
        else:
            out.append(line(OK, AREA, text))
    if stopped and stopped.get("restart") and not server_running:
        out.append(line(OK, AREA, f"A restart's stop didn't finish at {_when(stopped.get('at'))}: the watchdog "
                                  "starts Deck Lab again once it has stopped."))
    elif stopped and not server_running:
        if stopped.get("by") == "unreadable":
            out.append(line(WARN, AREA, "The stop marker can't be read, so the watchdog leaves Deck Lab off.",
                            "python -m decklab.lib.homenet start"))
        else:
            when = f" at {_when(stopped['at'])}" if stopped.get("at") else ""
            out.append(line(OK, AREA, f"Stopped on purpose{when} ({stopped.get('by') or 'unknown'}): the watchdog "
                                      "leaves it off until start, restart or your next logon."))
    run = _last_run_line(info or {}, log_text)
    if run:
        out.append(run)
    return out


def _settings_lines(watchdog, name, exists):
    """WARN lines for a watchdog task that doesn't do what install sets up."""
    out = []
    command = watchdog.get("command") or ""
    program = ntpath.expandvars(command.strip().strip('"'))
    if not program or not exists(program):
        out.append(line(WARN, AREA, f"The watchdog task starts {command or '(nothing)'}, which isn't there any "
                                    "more (was Python upgraded or moved?).", REINSTALL))
    elif ntpath.basename(norm_path(program)) != "pythonw.exe":
        out.append(line(WARN, AREA, f"The watchdog task starts {command}, not pythonw.exe, so a console window "
                                    f"flashes up every {_minutes(WATCHDOG_EVERY)}.", REINSTALL))
    if norm_path(watchdog.get("workdir")) != norm_path(config.REPO):
        out.append(line(WARN, AREA, f"The watchdog task runs in {watchdog.get('workdir') or '(no folder)'}, not "
                                    f"this repo ({config.REPO}).", REINSTALL))
    if split_args(watchdog.get("arguments")) != split_args(watchdog_arguments(name)):
        out.append(line(WARN, AREA, f"The watchdog task doesn't run ensure for the \"{name}\" task (it runs "
                                    f"{watchdog.get('arguments') or 'nothing'}).", REINSTALL))
    if WATCHDOG_EVERY not in (watchdog.get("repeats") or []):
        repeats = ", ".join(watchdog.get("repeats") or []) or "never"
        out.append(line(WARN, AREA, f"The watchdog task doesn't run every {_minutes(WATCHDOG_EVERY)} (it repeats: "
                                    f"{repeats}).", REINSTALL))
    if not watchdog.get("enabled", True):
        out.append(line(WARN, AREA, "The watchdog task is turned off (disabled) in Task Scheduler.", REINSTALL))
    logon_type = watchdog.get("logon_type")
    if logon_type and logon_type.lower() != "interactivetoken":
        out.append(line(WARN, AREA, f"The watchdog task logs on as {logon_type}, not \"Run only when user is "
                                    "logged on\" (InteractiveToken), so it can't see or start the server in your "
                                    "session.", REINSTALL))
    return out


def _last_run_line(info, log_text):
    """A WARN for a watchdog run that didn't end normally, else None."""
    result = _int(info.get("last_result"))
    result = None if result is None else result & 0xFFFFFFFF
    last_run = info.get("last_run")
    try:
        ran = datetime.fromisoformat(last_run) if last_run else None
    except ValueError:
        ran = None
    if ran is None or ran.year < 2000 or info.get("state") == "Running" or result in (
            None, 0, TASK_RUNNING, TASK_NOT_RUN_YET):
        return None
    when = ran.strftime("%Y-%m-%d %H:%M")
    if result == TASK_TERMINATED:
        return line(WARN, AREA, f"Task Scheduler ended the watchdog's check at {when}: it ran for longer than "
                                "its time limit.", f"Its log: {log_text}")
    return line(WARN, AREA, f"The watchdog's check at {when} ended with exit code {result} (0x{result:08X}).",
                f"Its log: {log_text}")


def _minutes(duration):
    minutes = _int((duration or "").removeprefix("PT").removesuffix("M"))
    return f"{minutes} minutes" if minutes else duration
