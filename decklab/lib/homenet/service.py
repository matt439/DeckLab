"""homenet on Linux (E11-S33): the server as a systemd user service instead of the
Task Scheduler task. install writes decklab.service (unit_text) into the user's unit
folder, enables it with --at-logon (it then starts when the user's manager does: at
login, or at boot with lingering) and starts it; start, stop, restart and remove go
through systemctl --user; status reports the server, the service and the tunnel.

The service runs `python decklab/server.py --background` in the repo, so the server
logs to decklab/data/logs/server.log as the Windows task's does. Restart=on-failure
does the watchdog's job: a server that crashes is started again, one stopped on
purpose (homenet stop, systemctl stop: both SIGTERM, which the server takes as a stop
request, control.listen_for_stop) stays off. Like the watchdog it gives up after
GIVE_UP starts within GIVE_UP_WITHIN seconds (StartLimitBurst, StartLimitIntervalSec):
the unit is then "failed", which status reports; start and restart clear that first
(systemctl reset-failed). The unit carries the PATH (and JAVA_HOME) of the shell install
ran in, since a user manager's own PATH usually misses ~/.local/bin and the like (where
cloudflared or Java may be), and UMask=0077, so the log, the data folder and the files
the server writes are the user's alone. start and restart refuse, before stopping
anything, when the unit's Python or server.py has gone (unit_problem).

status reports the server, the service, the network, the firewall (firewalld, ufw or
nftables, as far as they can be read without root), the addresses phones use and the
tunnel (linux_facts.py gathers what it reads). The sleep and wake checks come from
linux_power.py when it's there (_power_lines, the hook a later change wires).

Like commands.py, everything a test replaces is looked up through its module: systemd
here (lib/systemd.py), and commands' own (control, time, find_server, probe, ...), which
this module reaches through commands rather than importing them again.
"""
import os
import re
import sys
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from decklab.db import systemd_units
from decklab.lib import access, config, systemd, tunnel

from . import commands, linux_facts, profile_config
from . import mdns as multicast
from .checks import (check_addresses, check_firewall_linux, check_network, exit_code, format_report,
                     lan_of)
from .common import (OK, PROBE_TIMEOUT, PROBLEM, SERVER_SCRIPT, START_WAIT, TASK_NAME, WARN, WATCHDOG_GIVE_UP,
                     WATCHDOG_STABLE, _int, line, log, loopback, say)
from .mdns import MDNS_WAIT

SERVICE = "decklab.service"
STOP_TIMEOUT = "90s"                # the server waits for matchups to save their games (FORGE_STOP_WAIT)
GIVE_UP = WATCHDOG_GIVE_UP          # starts within GIVE_UP_WITHIN seconds before systemd stops trying
GIVE_UP_WITHIN = int(WATCHDOG_STABLE * 1.5)     # 900 s: three failed starts 10 s apart are well within it
ENVIRONMENT = ("PATH", "JAVA_HOME")             # install's own values, written into the unit
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


def environment(env=None):
    """{name: value} of ENVIRONMENT as install's shell has them (os.environ), for the unit;
    a value a unit can't hold (a control character) is left out."""
    env = os.environ if env is None else env
    return {name: env[name] for name in ENVIRONMENT
            if env.get(name) and not any(unicodedata.category(c) == "Cc" for c in env[name])}


def unit_text(python, workdir, args, task=TASK_NAME, env=None):
    """The service unit (systemd.service(5)). python and workdir are absolute POSIX paths,
    checked as the nightly units' are (systemd_units._path); env is {name: value} for its
    Environment= lines (environment(): install's PATH and JAVA_HOME)."""
    program = systemd_units._path(python, "the Python", executable=True).replace("%", "%%")
    directory = systemd_units._path(workdir, "the repo").replace("%", "%%")
    settings = "".join(f"Environment={_quote(f'{name}={value}')}\n" for name, value in (env or {}).items())
    return f"""[Unit]
Description=Deck Lab ({task}; python -m decklab.lib.homenet install)
StartLimitIntervalSec={GIVE_UP_WITHIN}
StartLimitBurst={GIVE_UP}

[Service]
Type=simple
WorkingDirectory={directory}
{settings}UMask=0077
ExecStart=":{program}" {" ".join(_quote(a) for a in args)}
Restart=on-failure
RestartSec=10
KillMode=mixed
TimeoutStopSec={STOP_TIMEOUT}

[Install]
WantedBy=default.target
"""


def _unquote(text):
    """The values of a line's double-quoted arguments (_quote's), as they were."""
    return [a.replace('\\"', '"').replace("\\\\", "\\").replace("%%", "%")
            for a in re.findall(r'"((?:[^"\\]|\\.)*)"', text)]


def unit_parts(text):
    """What a unit's text runs: {"program", "args", "workdir", "env"} (env: {name: value} of
    its Environment= lines), or None when it has no ExecStart of install's form."""
    match = re.search(r'^ExecStart=":((?:[^"\\]|\\.)*)"(.*)$', text or "", re.M)
    if not match:
        return None
    workdir = re.search(r"^WorkingDirectory=(.*)$", text, re.M)
    env = {}
    for found in re.findall(r"^Environment=(.*)$", text, re.M):
        for item in _unquote(found):
            name, sep, value = item.partition("=")
            if sep:
                env[name] = value
    return {"program": _unquote(f'"{match.group(1)}"')[0], "args": _unquote(match.group(2)),
            "workdir": workdir.group(1).replace("%%", "%") if workdir else None, "env": env}


def _option(args, name):
    """The value after name in args (--log FILE), or None."""
    for i, arg in enumerate(args[:-1]):
        if arg == name:
            return args[i + 1]
    return None


def unit_log_file(parts):
    """The log the unit's server writes: its --log (relative to its WorkingDirectory), else
    control.LOG_FILE."""
    given = _option((parts or {}).get("args") or [], "--log")
    if not given:
        return commands.control.LOG_FILE
    path = Path(os.path.expanduser(given))
    return path if path.is_absolute() or not parts.get("workdir") else Path(parts["workdir"]) / path


def unit_problem(parts, exists=os.path.exists, runnable=None):
    """Why the unit can't start Deck Lab any more (its Python or server.py has gone: Python
    upgraded, the repo moved), or None. Like Windows' task_problem, checked before anything
    is stopped."""
    runnable = runnable or (lambda path: os.path.isfile(path) and os.access(path, os.X_OK))
    again = "run python -m decklab.lib.homenet install again"
    if not parts:
        return f"its unit doesn't run Deck Lab the way install writes it, so it can't start Deck Lab: {again}"
    if not runnable(parts["program"]):
        return f"the Python it runs ({parts['program']}) isn't there any more, so it can't start Deck Lab: {again}"
    script = next((a for a in parts["args"] if Path(a).name == "server.py"), None)
    if script and not os.path.isabs(script) and parts.get("workdir"):
        script = os.path.join(parts["workdir"], script)
    if not script or not exists(script):
        return f"the server it runs ({script or 'server.py'}) isn't there any more, so it can't start Deck Lab: {again}"
    return None


def _read_unit(unit):
    """The unit file's text, or None."""
    try:
        return (systemd.unit_dir() / unit).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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


def _usable(unit):
    """The unit's parts when it can start Deck Lab; else None, after saying why (nothing
    has been stopped or started)."""
    parts = unit_parts(_read_unit(unit))
    problem = unit_problem(parts)
    if problem:
        say(f"The {unit} service is installed, but {problem}. Nothing was stopped or started.")
        return None
    return parts


def _start(name, port, verb="start", parts=None):
    log_file = unit_log_file(parts)
    log_start = commands._file_size(log_file)
    commands._starting(port)
    # A unit that gave up (StartLimitBurst) or failed refuses to start until this.
    systemd.systemctl("reset-failed", name)
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
                         arguments(port if port_given else None, log_path, host), name, environment())
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
    say(f"  in {config.REPO}, and starts it again if it stops with an error (up to {GIVE_UP} times in "
        f"{GIVE_UP_WITHIN // 60} minutes).")
    if "PATH" in environment():
        say("  It runs with this shell's PATH" + (" and JAVA_HOME" if "JAVA_HOME" in environment() else "")
            + " (install again after changing them).")
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
    return _start(unit, port, parts=unit_parts(text))


def start(name, port):
    unit = service_name(name)
    if not _installed(unit):
        return _not_installed(unit)
    state, answer = commands.find_server(port)
    if state or answer["answered"]:
        say(commands.describe_running(state, answer, port))
        return 0 if (state or answer.get("deck_lab")) else 1
    parts = _usable(unit)
    if parts is None:
        return 1
    return _start(unit, port, parts=parts)


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
    parts = _usable(unit)
    if parts is None:
        return 1
    if not _active(unit):
        state, answer = commands.find_server(port)
        if state or answer["answered"]:
            # One started in a terminal: stop it first, so the service can have the port.
            if commands.cmd_stop(port) != 0:
                say("It wasn't started again. Once it has stopped: python -m decklab.lib.homenet start")
                return 1
    return _start(unit, port, "restart", parts)


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
    when = ("starts at boot (lingering)" if linger else "starts at logon") if enabled else "started by hand"
    text = (f"{unit} is installed ({when}); it's "
            f"{found.get('ActiveState') or '?'} ({found.get('SubState') or '?'})")
    restarts = _int(found.get("NRestarts"), 0)
    if restarts:
        text += f", restarted {restarts} time{'s' if restarts != 1 else ''} after failing"
    out = [line(OK, area, text + ".")]
    if found.get("ActiveState") == "failed":
        gave_up = found.get("Result") == "start-limit-hit"
        out.append(line(PROBLEM, area, (f"systemd gave up starting it ({GIVE_UP} starts within "
                                        f"{GIVE_UP_WITHIN // 60} minutes failed)." if gave_up else
                                        f"Its last run failed ({found.get('Result') or '?'}, exit code "
                                        f"{found.get('ExecMainStatus') or '?'})."),
                        f"See decklab/data/logs/server.log and journalctl --user -u {unit}, then: "
                        "python -m decklab.lib.homenet restart"))
    if expected is not None and current != expected:
        out.append(line(WARN, area, "Its unit isn't what install writes now (the repo moved, Python changed, or "
                                    "it was installed by an older Deck Lab).",
                        "python -m decklab.lib.homenet install"))
    problem = unit_problem(unit_parts(current)) if current else None
    if problem:
        out.append(line(PROBLEM, area, problem[0].upper() + problem[1:] + "."))
    if enabled and linger is False:
        out.append(line(WARN, area, "It starts when you log in, not at boot, and stops when you log out.",
                        "loginctl enable-linger"))
    return out


def _unit_now(name, unit):
    """The unit's file text, and what install would write now with the same arguments (and
    the unit's own Environment= values: a shell with another PATH isn't a changed unit)."""
    current = _read_unit(unit)
    if current is None:
        return None, None
    parts = unit_parts(current)
    try:
        expected = (unit_text(sys.executable, config.REPO.as_posix(), parts["args"], name, parts["env"])
                    if parts and parts["args"] else None)
    except ValueError:
        expected = None
    return current, expected


def _power_lines(settings, port, network):
    """The Sleep and Wake lines on Linux. HOOK: the keep-awake change's linux_power.py
    gives them (status_lines(settings, port, network)); until it's there, none."""
    try:
        from . import linux_power
    except ImportError:
        return []
    status_lines = getattr(linux_power, "status_lines", None)
    if status_lines is None:
        return []
    try:
        return list(status_lines(settings, port, network))
    except Exception as e:          # noqa: BLE001 (one line, never the whole status)
        return [line(WARN, "Sleep", f"Couldn't check sleep and wake: {type(e).__name__}: {e}")]


def _settings():
    try:
        return config.load()
    except (OSError, ValueError, TypeError):
        return {}


def status(name, port):
    unit = service_name(name)
    state = commands.control.read_state()
    mine = state if isinstance(state, dict) and _int(state.get("port")) == port else None
    other = state if isinstance(state, dict) and mine is None else None
    settings = _settings()
    hostname = linux_facts.short_name(commands.pc_name())
    public = (tunnel.settings_of(settings) or {}).get("hostname")
    try:
        access_port = (access.settings_of(settings) or {}).get("port") if public is not None else None
    except ValueError:
        access_port = None
    # The slow checks run side by side, as Windows' status runs them beside PowerShell.
    found = {}
    jobs = {"answer": lambda: commands.probe(port, commands._probe_host(mine)),
            "mdns": lambda: multicast.mdns_lookup(f"{hostname}.local", commands.local_ipv4())}
    if public:
        jobs["public"] = lambda: tunnel.check_public(public)
    if access_port:
        jobs["listener"] = lambda: tunnel.check_listener(access_port, public, PROBE_TIMEOUT)
    helpers = [threading.Thread(target=lambda k=k, job=job: found.update({k: job()}), daemon=True)
               for k, job in jobs.items()]
    for helper in helpers:
        helper.start()
    current, expected = _unit_now(name, unit)
    service_state = _state(unit) if current is not None else None
    facts = linux_facts.read_facts(port)
    for helper in helpers:
        helper.join(max(PROBE_TIMEOUT + MDNS_WAIT, tunnel.CHECK_TIMEOUT) + 5)
    answer = found.get("answer") or {"answered": False, "error": "the check didn't finish"}
    mdns = found.get("mdns") or {"answered": False, "addresses": [], "error": "the lookup didn't finish"}
    network = facts.get("network")

    lines = profile_config.check(settings)
    lines += commands.check_server(mine, answer, port, (mine or {}).get("log") or commands.control.LOG_FILE,
                                   commands.newest_code_mtime(), other)
    lines += check_service(name, service_state, expected, current, systemd.linger() if service_state else None)
    lines += check_network(network, facts.get("errors", {}).get("network"), linux=True)
    lines += check_firewall_linux(facts.get("firewall"), port, lan_of(network), settings.get("home_networks"),
                                  facts.get("errors", {}).get("firewall"))
    addresses = check_addresses(network, hostname, mdns, port)
    lines += addresses
    lines += _power_lines(settings, port, network)
    lines += commands.check_tunnel(settings, found.get("public"), tunnel.ingress_problems(settings, port),
                                   found.get("listener"), tunnel.credentials_problem(settings))
    header = f"Deck Lab status, {datetime.now().strftime('%Y-%m-%d %H:%M')} (port {port})"
    shown = any(entry["level"] == OK and "http://" in entry["text"] for entry in addresses)
    footer = ("These checks run on this computer, so they can't prove a phone gets through: the real test "
              + ("is opening the address above on a phone on the home Wi-Fi." if shown else
                 f"is opening http://{hostname}.local:{port}/ (or the PC's IP address) on a phone on the home "
                 "Wi-Fi."))
    say(format_report(lines, header=header, footer=footer))
    return exit_code(lines)


COMMANDS = {"install": install, "start": start, "stop": stop, "restart": restart,
            "remove": remove, "status": status}
