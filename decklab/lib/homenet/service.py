"""Off Windows, homenet's install, start, restart, remove and status act on a
systemd user service instead of Task Scheduler (E11-S33): decklab.service in
~/.config/systemd/user (or $XDG_CONFIG_HOME/systemd/user), run by
`systemctl --user`. install writes the unit and reloads systemd; --at-logon
enables it, so it starts with the user's systemd (at login, or at boot with
`loginctl enable-linger`). systemd restarts a server that crashes
(Restart=on-failure), which the watchdog task does on Windows; a stop that
was asked for exits 0, so it stays stopped. Stopping is homenet stop's, as on
Windows: it sends the server SIGTERM (control.request_stop), which stops it
the way Ctrl+C does.

The unit's text is made here, and read back here (read_service) for start
and status. The commands reach homenet's shared helpers through
homenet.commands at call time, so the tests that patch them there patch them
here too; systemctl and UNIT_DIR are this module's, for the tests to replace."""
import os
import re
import subprocess
import sys
from pathlib import Path

from decklab.lib import config

from .common import (
    OK, PROBLEM, SERVER_SCRIPT, STOP_WAIT, TASK_NAME, WARN, line, loopback, say,
)

SYSTEMCTL_TIMEOUT = 30          # seconds for any one systemctl command
RESTART_SEC = 10                # seconds systemd waits before restarting a crashed server
UNIT_DIR = None                 # tests set a folder; None: the user's systemd folder (unit_dir)


def unit_dir(env=None):
    """The folder systemd reads the user's own units from."""
    if UNIT_DIR is not None:
        return Path(UNIT_DIR)
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "systemd" / "user"


def unit_name(task_name=TASK_NAME):
    """decklab.service for the server, and decklab-<name>.service for a test one (--task)."""
    if task_name == TASK_NAME:
        return "decklab.service"
    slug = re.sub(r"[^a-z0-9]+", "-", str(task_name).lower()).strip("-") or "test"
    return f"decklab-{slug}.service"


def systemctl(*args, timeout=SYSTEMCTL_TIMEOUT):
    """Run systemctl --user; (exit code, stdout text, stderr text). Code None when it ran over
    timeout or isn't there (the text says which)."""
    try:
        done = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", f"systemctl --user {' '.join(args)} didn't finish within {timeout} seconds"
    except OSError as e:
        return None, "", f"systemctl can't run ({e}): this needs systemd"
    return done.returncode, done.stdout or "", done.stderr or ""


def _said(out, err, code):
    text = (err or out or "").strip().splitlines()
    return text[-1] if text else f"exit code {code}"


def _quote(arg):
    """One ExecStart argument, double-quoted as systemd unquotes it (systemd.syntax(7)), with
    % doubled (a specifier otherwise). ExecStart's ':' prefix leaves $ alone."""
    text = str(arg)
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValueError(f"{text!r} has a control character, which a unit file can't hold.")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def server_argv(script=None, port=None, log_path=None, host=None):
    """The server's command line after the Python: the script, --background, and --host,
    --port and --log when given. The log is always a file, so start can show its tail."""
    argv = [str(script or SERVER_SCRIPT), "--background"]
    if host:
        argv += ["--host", str(host)]
    if port is not None:
        argv += ["--port", str(port)]
    argv += ["--log", str(log_path or _homenet().control.LOG_FILE)]
    return argv


def service_unit(python, argv, workdir, at_logon=False):
    """The unit's text. Type=simple: started once the process is (start then waits for the
    server to answer). KillMode=mixed: SIGTERM to the server, which stops its own children
    (Forge, the tunnel); after TimeoutStopSec, SIGKILL to anything left."""
    python, workdir = str(python), str(workdir)
    for value, what in ((python, "The Python"), (workdir, "The repo folder")):
        if not value.startswith("/"):
            raise ValueError(f"{what} ({value}) isn't an absolute path.")
    if "\n" in workdir or workdir.endswith("\\"):
        raise ValueError(f"The repo folder ({workdir!r}) can't be written in a unit file.")
    command = " ".join([_quote(":" + python)] + [_quote(a) for a in argv])
    return f"""# Made by: python -m decklab.lib.homenet install{" --at-logon" if at_logon else ""}. Run that again after
# moving the repo or upgrading Python; python -m decklab.lib.homenet remove takes it away.
[Unit]
Description=Deck Lab web server
StartLimitIntervalSec=10min
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory={workdir.replace("%", "%%")}
ExecStart={command}
Restart=on-failure
RestartSec={RESTART_SEC}
TimeoutStopSec={STOP_WAIT + 30}
KillMode=mixed

[Install]
WantedBy=default.target
"""


def _unquote(text):
    """service_unit's ExecStart back to its words (only the double-quoted form it writes)."""
    words = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
    return [re.sub(r"\\(.)", r"\1", w).replace("%%", "%") for w in words]


def parse_unit(text):
    """{"python", "argv", "workdir"} from a unit's text (service_unit's form)."""
    found = {"python": None, "argv": [], "workdir": None}
    for raw in text.splitlines():
        key, _, value = raw.partition("=")
        if key == "ExecStart":
            words = _unquote(value)
            if words:
                found["python"] = words[0][1:] if words[0].startswith(":") else words[0]
                found["argv"] = words[1:]
        elif key == "WorkingDirectory":
            found["workdir"] = value.replace("%%", "%")
    return found


def read_service(name=TASK_NAME):
    """The installed unit (parse_unit, plus "unit" and "path"), or None when there's none."""
    path = unit_dir() / unit_name(name)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        return {"unit": unit_name(name), "path": path, "python": None, "argv": [], "workdir": None,
                "error": f"{path} can't be read: {e}"}
    return dict(parse_unit(text), unit=unit_name(name), path=path)


def service_problem(service, exists=os.path.exists):
    """Why the unit can't start Deck Lab as it stands, or None."""
    if service.get("error"):
        return service["error"]
    if not service.get("python") or not exists(service["python"]):
        return f"The service starts {service.get('python') or '(nothing)'}, which isn't there any more"
    if not service.get("argv") or not exists(service["argv"][0]):
        return f"The service runs {(service.get('argv') or ['(nothing)'])[0]}, which isn't there any more"
    return None


def _option(service, option):
    argv = (service or {}).get("argv") or []
    for i, arg in enumerate(argv[1:], 1):
        if arg == option and i + 1 < len(argv):
            return argv[i + 1]
    return None


def service_log_file(service):
    return Path(_option(service, "--log") or _homenet().control.LOG_FILE)


def show(unit):
    """{property: value} of the unit as systemd has it now, or {} when systemctl can't say."""
    code, out, _ = systemctl("show", unit, "--property=LoadState,ActiveState,SubState,UnitFileState,"
                                           "ExecMainStatus,NRestarts")
    if code != 0:
        return {}
    return dict(row.split("=", 1) for row in out.splitlines() if "=" in row)


def _reload():
    code, out, err = systemctl("daemon-reload")
    return None if code == 0 else _said(out, err, code)


# ------------------------------------------------------------ the commands

def _homenet():
    from . import commands      # imported when used: commands imports this module
    return commands


def install(name, port, no_start=False, log_path=None, port_given=False, host=None, at_logon=False):
    """homenet install off Windows (commands.cmd_install has checked the profiles first)."""
    homenet = _homenet()
    unit = unit_name(name)
    argv = server_argv(SERVER_SCRIPT, port if port_given else None, log_path, host)
    try:
        text = service_unit(sys.executable, argv, config.REPO, at_logon)
    except ValueError as e:
        say(f"The {unit} unit can't be written: {e}")
        return 1
    path = unit_dir() / unit
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        say(f"The {unit} unit couldn't be written to {path}: {e}")
        return 1
    error = _reload()
    if error:
        say(f"Wrote {path}, but systemd couldn't reload its units: {error}. Is this a systemd user session?")
        return 1
    code, out, err = systemctl("enable" if at_logon else "disable", unit)
    if code != 0:
        say(f"Wrote {path}, but systemctl --user {'enable' if at_logon else 'disable'} {unit} failed: "
            f"{_said(out, err, code)}")
        return 1
    service = read_service(name)
    if service is None or service.get("python") != sys.executable:
        say(f"Wrote {path}, but reading it back didn't show {sys.executable}. Check the file.")
        return 1
    say(f"Installed the {unit} systemd user service ({path}): "
        + ("it starts with your systemd user session, and on homenet start; it runs"
           if at_logon else "python -m decklab.lib.homenet start runs it; it runs"))
    say(f"  {sys.executable} {' '.join(argv)}")
    say(f"  in {config.REPO}. systemd restarts it if it stops unexpectedly.")
    if at_logon:
        say("  To start it at boot rather than when you log in: loginctl enable-linger")
    else:
        say("It doesn't start at logon (install --at-logon turns that on).")
    if no_start:
        say(("It starts at the next logon, or now with: " if at_logon else "Start it with: ")
            + "python -m decklab.lib.homenet start")
        return 0
    state, answer = homenet.find_server(port)
    if not state and answer["answered"] and not answer.get("deck_lab"):
        say(f"Deck Lab can't start now, though: another program uses port {port}.")
        say(homenet.how_to_stop(state, answer))
        return 1
    if state or answer["answered"]:
        say(homenet.describe_running(state, answer, port) + " It wasn't started a second time.")
        say("To run it from the service instead: python -m decklab.lib.homenet restart")
        return 0
    homenet._starting(port)
    return _start_service(name, port, service)


def _usable_service(name, restarting=False):
    service = read_service(name)
    if service is None:
        say(f"The {unit_name(name)} service isn't installed: run python -m decklab.lib.homenet install first.")
        return None
    problem = service_problem(service, _homenet().file_exists)
    if problem:
        say(f"{problem}, so it can't start Deck Lab" + (" (nothing was stopped)" if restarting else "")
            + ": run python -m decklab.lib.homenet install again.")
        return None
    return service


def start(name, port):
    homenet = _homenet()
    service = _usable_service(name)
    if service is None:
        return 1
    state, answer = homenet.find_server(port)
    if state or answer["answered"]:
        say(homenet.describe_running(state, answer, port))
        return 0 if (state or answer.get("deck_lab")) else 1
    homenet._starting(port)
    return _start_service(name, port, service)


def _start_service(name, port, service):
    homenet = _homenet()
    unit = unit_name(name)
    log_file = service_log_file(service)
    log_start = homenet._file_size(log_file)
    # A server that crashed too often in a row is left failed by StartLimitBurst: start clears that.
    systemctl("reset-failed", unit)
    code, out, err = systemctl("start", unit)
    if code != 0:
        say(f"systemd couldn't start {unit}: {_said(out, err, code)}")
        return 1
    return homenet._wait_for_start(port, log_file, log_start, how=f"systemctl --user status {unit}")


def restart(name, port):
    homenet = _homenet()
    service = _usable_service(name, restarting=True)
    if service is None:
        return 1
    if homenet.cmd_stop(port) != 0:
        say("It wasn't started again. Once it has stopped: python -m decklab.lib.homenet start")
        return 1
    homenet._starting(port)
    return _start_service(name, port, service)


def remove(name, port):
    homenet = _homenet()
    stopped = homenet.cmd_stop(port)
    unit = unit_name(name)
    path = unit_dir() / unit
    if not path.exists():
        say(f"The {unit} service isn't installed, so there was nothing to remove.")
        return stopped
    systemctl("stop", unit)         # stopped already, unless homenet stop couldn't reach it
    code, out, err = systemctl("disable", unit)
    if code != 0:
        say(f"systemctl --user disable {unit} failed: {_said(out, err, code)}")
        return 1
    try:
        path.unlink()
    except OSError as e:
        say(f"{path} couldn't be removed: {e}")
        return 1
    error = _reload()
    if error:
        say(f"Removed {path}, but systemd couldn't reload its units: {error}")
        return 1
    say(f"Removed the {unit} service: Deck Lab doesn't start at logon, and start can't start it until "
        "python -m decklab.lib.homenet install sets it up again.")
    return stopped


# ------------------------------------------------------------ status

def status_lines(name, port, server_running, exists=os.path.exists, systemd=None):
    """status's Start at logon and Restart after a crash lines off Windows, from the unit file
    and systemd's view of it (systemd: show()'s dict; None asks systemd)."""
    area = "Start at logon"
    service = read_service(name)
    unit = unit_name(name)
    if service is None:
        return [line(WARN, area, f"The {unit} systemd user service isn't installed, so start can't start "
                                 "Deck Lab and it doesn't start at logon.",
                     "python -m decklab.lib.homenet install (--at-logon to start it at logon)")]
    problem = service_problem(service, exists)
    if problem:
        return [line(PROBLEM, area, f"{problem}, so the service can't start Deck Lab.",
                     "python -m decklab.lib.homenet install")]
    facts = show(unit) if systemd is None else systemd
    if not facts or facts.get("LoadState") not in (None, "loaded"):
        return [line(WARN, area, f"{service['path']} is there, but systemd doesn't have it loaded "
                                 f"({facts.get('LoadState') or 'systemctl --user could not say'}).",
                     "systemctl --user daemon-reload, or python -m decklab.lib.homenet install again")]
    lines = []
    if service.get("workdir") and os.path.normcase(service["workdir"]) != os.path.normcase(str(config.REPO)):
        lines.append(line(WARN, area, f"The service runs in {service['workdir']}, not this repo ({config.REPO}).",
                          "python -m decklab.lib.homenet install"))
    host = _option(service, "--host")
    where = f", listening on {host} only" if host and loopback(host) else ""
    if facts.get("UnitFileState") == "enabled":
        lines.append(line(OK, area, f"The {unit} service starts Deck Lab with your systemd user session{where}."))
    else:
        lines.append(line(OK, area, f"The {unit} service is installed{where}; it doesn't start at logon "
                                    "(install --at-logon turns that on)."))
    if facts.get("ActiveState") == "failed":
        lines.append(line(PROBLEM, "Restart after a crash",
                          f"systemd gave up restarting {unit} after it kept stopping "
                          f"(exit status {facts.get('ExecMainStatus') or '?'}).",
                          f"journalctl --user -u {unit}, and its log ({service_log_file(service)}); then "
                          "python -m decklab.lib.homenet start"))
    elif server_running and facts.get("ActiveState") != "active":
        lines.append(line(WARN, "Restart after a crash", f"Deck Lab is running, but not as the {unit} service, "
                                                         "so nothing restarts it after a crash.",
                          "python -m decklab.lib.homenet restart"))
    else:
        restarts = facts.get("NRestarts")
        lines.append(line(OK, "Restart after a crash", f"systemd restarts Deck Lab after a crash"
                          + (f" (it has {restarts} times since it was started)" if restarts not in (None, "0")
                             else "") + "."))
    return lines
