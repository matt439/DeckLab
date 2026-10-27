"""homenet on Linux (E11-S33): the server as a systemd user service instead of the
Task Scheduler task. install writes decklab.service (unit_text) into the user's unit
folder, enables it with --at-logon (it then starts when the user's manager does: at
login, or at boot with lingering) and starts it; start, stop, restart and remove go
through systemctl --user; status reports the server, the service and the tunnel.

The service runs `python decklab/server.py --background` in the repo, so the server
logs to decklab/data/logs/server.log as the Windows task's does. Restart=on-failure
does the watchdog's job: a server that crashes is started again, one stopped on
purpose (homenet stop, systemctl stop: both SIGTERM, which the server takes as a stop
request, control.listen_for_stop) stays off. The firewall, sleep and mDNS checks of
Windows' status aren't made here.

Like commands.py, everything a test replaces is looked up through its module: systemd
here (lib/systemd.py), and commands' own (control, time, find_server, probe, ...), which
this module reaches through commands rather than importing them again.
"""
import re
import sys
import unicodedata
from datetime import datetime

from decklab.db import systemd_units
from decklab.lib import config, systemd, tunnel

from . import commands, profile_config
from .checks import exit_code, format_report
from .common import OK, PROBLEM, SERVER_SCRIPT, START_WAIT, TASK_NAME, WARN, _int, line, log, loopback, say

SERVICE = "decklab.service"
STOP_TIMEOUT = "90s"                # the server waits for matchups to save their games (FORGE_STOP_WAIT)
# KillMode=mixed: a stop sends SIGTERM to the server only, which stops its Forge games itself (as
# Ctrl+C does); whatever is left of the service when the server has gone, or at the timeout, is killed.


def service_name(task=TASK_NAME):
    """The unit's file name: decklab.service, or for another --task (tests) its slug."""
    if task == TASK_NAME:
        return SERVICE
    slug = re.sub(r"[^a-z0-9]+", "-", str(task).lower()).strip("-") or "decklab"
    return f"{slug}.service"


def _quote(arg):
    """One ExecStart argument, double-quoted with systemd's C-style escapes, with % doubled."""
    text = str(arg)
    if any(unicodedata.category(c) == "Cc" for c in text):
        raise ValueError(f"{text!r} has a control character, which a unit file can't hold.")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def arguments(port=None, log_path=None, host=None, script=None):
    """The server's arguments: the script, --background, then --host, --port and --log when given."""
    args = [str(script or SERVER_SCRIPT), "--background"]
    if host:
        args += ["--host", str(host)]
    if port is not None:
        args += ["--port", str(int(port))]
    if log_path:
        args += ["--log", str(log_path)]
    return args


def unit_text(python, workdir, args, task=TASK_NAME):
    """The service unit (systemd.service(5)). python and workdir are absolute POSIX paths,
    checked as the nightly units' are (systemd_units._path)."""
    program = systemd_units._path(python, "the Python", executable=True).replace("%", "%%")
    directory = systemd_units._path(workdir, "the repo").replace("%", "%%")
    return f"""[Unit]
Description=Deck Lab ({task}; python -m decklab.lib.homenet install)

[Service]
Type=simple
WorkingDirectory={directory}
ExecStart=":{program}" {" ".join(_quote(a) for a in args)}
Restart=on-failure
RestartSec=10
KillMode=mixed
TimeoutStopSec={STOP_TIMEOUT}

[Install]
WantedBy=default.target
"""


def _state(name):
    """The unit's systemctl show properties, or None when the manager can't be asked."""
    return systemd.show(name, "LoadState", "UnitFileState", "ActiveState", "SubState", "MainPID", "Result",
                        "ExecMainStatus", "ExecMainStartTimestamp", "NRestarts")


def _installed(name):
    return (systemd.unit_dir() / name).is_file()


def _not_installed(name):
    say(f"The {name} service isn't installed: run python -m decklab.lib.homenet install first.")
    return 1


def _wait_for_answer(port, log_file, log_start):
    """After systemctl start or restart: wait for Deck Lab to answer on port, as the
    Windows start does (commands._start_task)."""
    log(f"Starting Deck Lab (waiting up to {START_WAIT} seconds for it to answer)...")
    started = commands.time.monotonic()
    while commands.time.monotonic() - started < START_WAIT:
        state = commands.server_state(port)
        answer = commands.probe(port, commands._probe_host(state))
        if answer["answered"]:
            if not answer.get("deck_lab"):
                say(f"Something answers on port {port}, but it isn't Deck Lab.")
                return 1
            say("Deck Lab is running.")
            host = (state or {}).get("host")
            for label, url in commands.urls(port, None if loopback(host) else commands.local_ipv4()):
                if loopback(host) and label != "On this PC":
                    continue
                say(f"  {label}: {url}")
            if loopback(host):
                say(f"  It listens on {host} only, so phones can't reach it.")
            return 0
        commands.time.sleep(0.5)
    say(f"Deck Lab didn't answer on port {port} within {START_WAIT} seconds.")
    tail = commands._log_tail(log_file, start=log_start)
    if tail:
        say(f"What it wrote to its log ({log_file}) after the start:")
        for text in tail:
            say(f"  {text}")
    else:
        say(f"It wrote nothing to its log ({log_file}) after the start. journalctl --user -u {SERVICE} "
            "shows what systemd saw.")
    return 1


def _start(name, port, verb="start"):
    log_file = commands.control.LOG_FILE
    log_start = commands._file_size(log_file)
    commands._starting(port)
    code, out, err = systemd.systemctl(verb, name)
    if code != 0:
        say(f"systemd couldn't {verb} {name}: {systemd.said(out, err, code)}")
        return 1
    return _wait_for_answer(port, log_file, log_start)


def install(name, port, no_start=False, log_path=None, port_given=False, host=None, at_logon=False):
    if not commands.profiles_ok():
        return 1
    unit = service_name(name)
    try:
        text = unit_text(sys.executable, config.REPO.as_posix(),
                         arguments(port if port_given else None, log_path, host), name)
    except ValueError as e:
        say(f"The {unit} service can't be written for this Python and repo: {e}")
        return 1
    error = systemd.write_units({unit: text})
    if error:
        say(f"The {unit} service couldn't be installed: {error}")
        return 1
    code, out, err = systemd.systemctl("enable" if at_logon else "disable", unit)
    if code != 0:
        say(f"The {unit} service was written, but couldn't be {'enabled' if at_logon else 'disabled'}: "
            f"{systemd.said(out, err, code)}")
        return 1
    say(f"Installed the {unit} systemd user service ({systemd.unit_dir() / unit}): it runs")
    say(f"  {sys.executable} {' '.join(arguments(port if port_given else None, log_path, host))}")
    say(f"  in {config.REPO}, and starts it again if it stops with an error.")
    if at_logon:
        say("It starts when you log in.")
        note = systemd.linger_note()
        if note:
            say(note)
    else:
        say("It doesn't start at logon (install --at-logon turns that on).")
    if no_start:
        say(("It starts at the next logon, or now with: " if at_logon else "Start it with: ")
            + "python -m decklab.lib.homenet start")
        return 0
    state, answer = commands.find_server(port)
    if not state and answer["answered"] and not answer.get("deck_lab"):
        say(f"Deck Lab can't start now, though: another program uses port {port}.")
        return 1
    if state or answer["answered"]:
        say(commands.describe_running(state, answer, port) + " It wasn't started a second time.")
        say("To run it from the service instead: python -m decklab.lib.homenet restart")
        return 0
    return _start(unit, port)


def start(name, port):
    unit = service_name(name)
    if not _installed(unit):
        return _not_installed(unit)
    state, answer = commands.find_server(port)
    if state or answer["answered"]:
        say(commands.describe_running(state, answer, port))
        return 0 if (state or answer.get("deck_lab")) else 1
    return _start(unit, port)


def _active(unit):
    found = _state(unit) if _installed(unit) else None
    return bool(found) and found.get("ActiveState") in ("active", "activating", "reloading")


def stop(name, port):
    """systemctl stop when the service runs; else the stop request any server on port
    hears (commands.cmd_stop: SIGTERM to the process the state file names)."""
    unit = service_name(name)
    if not _active(unit):
        return commands.cmd_stop(port)
    try:
        commands.control.mark_stopped(port, "homenet stop")
    except OSError as e:
        say(f"Couldn't record the stop ({e}).")
    code, out, err = systemd.systemctl("stop", unit, timeout=120)
    if code != 0:
        say(f"systemd couldn't stop {unit}: {systemd.said(out, err, code)}")
        return 1
    say("Deck Lab stopped.")
    return 0


def restart(name, port):
    unit = service_name(name)
    if not _installed(unit):
        return _not_installed(unit)
    if not _active(unit):
        state, answer = commands.find_server(port)
        if state or answer["answered"]:
            # One started in a terminal: stop it first, so the service can have the port.
            if commands.cmd_stop(port) != 0:
                say("It wasn't started again. Once it has stopped: python -m decklab.lib.homenet start")
                return 1
    return _start(unit, port, "restart")


def remove(name, port):
    unit = service_name(name)
    stopped = stop(name, port) if _installed(unit) else commands.cmd_stop(port)
    if not _installed(unit):
        say(f"The {unit} service isn't installed, so there was nothing to remove.")
        return stopped
    code, out, err = systemd.systemctl("disable", unit)
    if code != 0:
        say(f"The {unit} service couldn't be disabled: {systemd.said(out, err, code)}")
        return 1
    error = systemd.remove_units([unit])
    if error:
        say(f"The {unit} service couldn't be removed: {error}")
        return 1
    say(f"Removed the {unit} service: Deck Lab doesn't start at logon, and start can't start it until "
        "python -m decklab.lib.homenet install sets it up again.")
    return stopped


def check_service(name, found, expected=None, current=None, linger=None):
    """The Service lines, from the unit's systemctl show properties (None: not asked),
    its file's text and the text install would write now."""
    area = "Service"
    unit = service_name(name)
    if current is None:
        return [line(WARN, area, f"The {unit} systemd user service isn't installed, so Deck Lab runs only "
                                 "when started by hand.",
                     "python -m decklab.lib.homenet install (--at-logon to start it when you log in)")]
    if found is None:
        return [line(WARN, area, f"{unit} is installed, but systemctl --user can't be asked about it "
                                 "(is the user manager running?).")]
    enabled = found.get("UnitFileState") == "enabled"
    text = (f"{unit} is installed ({'starts at logon' if enabled else 'started by hand'}); it's "
            f"{found.get('ActiveState') or '?'} ({found.get('SubState') or '?'})")
    restarts = _int(found.get("NRestarts"), 0)
    if restarts:
        text += f", restarted {restarts} time{'s' if restarts != 1 else ''} after failing"
    out = [line(OK, area, text + ".")]
    if found.get("ActiveState") == "failed":
        out.append(line(PROBLEM, area, f"Its last run failed ({found.get('Result') or '?'}, exit code "
                                       f"{found.get('ExecMainStatus') or '?'}).",
                        f"See decklab/data/logs/server.log and journalctl --user -u {unit}, then: "
                        "python -m decklab.lib.homenet restart"))
    if expected is not None and current != expected:
        out.append(line(WARN, area, "Its unit isn't what install writes now (the repo moved or Python changed).",
                        "python -m decklab.lib.homenet install"))
    if enabled and linger is False:
        out.append(line(WARN, area, "It starts when you log in, not at boot, and stops when you log out.",
                        "loginctl enable-linger"))
    return out


def _unit_now(name, unit):
    """The unit's file text, and what install would write now with the same arguments."""
    path = systemd.unit_dir() / unit
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None
    match = re.search(r'^ExecStart=":[^"]*" (.*)$', current, re.M)
    try:
        args = [a.replace('\\"', '"').replace("\\\\", "\\").replace("%%", "%")
                for a in re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))] if match else None
        expected = unit_text(sys.executable, config.REPO.as_posix(), args, name) if args else None
    except ValueError:
        expected = None
    return current, expected


def status(name, port):
    unit = service_name(name)
    state = commands.control.read_state()
    mine = state if isinstance(state, dict) and _int(state.get("port")) == port else None
    other = state if isinstance(state, dict) and mine is None else None
    try:
        settings = config.load()
    except (OSError, ValueError, TypeError):
        settings = {}
    answer = commands.probe(port, commands._probe_host(mine))
    current, expected = _unit_now(name, unit)
    found = _state(unit) if current is not None else None
    public = (tunnel.settings_of(settings) or {}).get("hostname")
    lines = profile_config.check(settings)
    lines += commands.check_server(mine, answer, port, (mine or {}).get("log") or commands.control.LOG_FILE,
                                   commands.newest_code_mtime(), other)
    lines += check_service(name, found, expected, current, systemd.linger() if found else None)
    lines += commands.check_tunnel(settings, tunnel.check_public(public) if public else None,
                                   tunnel.ingress_problems(settings, port))
    header = f"Deck Lab status, {datetime.now().strftime('%Y-%m-%d %H:%M')} (port {port})"
    footer = ("These checks run on this computer, so they can't prove a phone gets through: the real test "
              "is opening the address above on a phone on the home Wi-Fi.")
    say(format_report(lines, header=header, footer=footer))
    return exit_code(lines)


COMMANDS = {"install": install, "start": start, "stop": stop, "restart": restart,
            "remove": remove, "status": status}
