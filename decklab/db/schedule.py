"""The "Deck Lab database backup" Task Scheduler task: every day at 03:30 it runs
`pythonw.exe -m decklab.db nightly` (nightly.py) in the repo folder, with no window.

It runs as the current user, only while they're logged on (InteractiveToken), without
administrator (LeastPrivilege): a backup_dir on a network share (the household's NAS) is
reached with the password in that user's Credential Manager, so the copy works only as them. StartWhenAvailable catches up a run the PC
was off for; a second start while one runs is ignored; two hours is the most it may take.

It's registered from its XML with schtasks /Create /XML, through homenet's helpers (the
"Deck Lab" server task is registered the same way). install refuses a Python that can't
import psycopg, since the task would run that Python's pythonw.exe every night for nothing.
Register it from the system python (python -m decklab.db schedule install), which finds the
.venv's psycopg itself (lib/venv.py): the .venv's pythonw.exe is a launcher that starts a second
process, which the task's time limit may leave running. status warns when the task runs one.

On Linux the same job is a systemd user service and timer instead (E11-S33): install writes
decklab-nightly.service and decklab-nightly.timer (systemd_units.nightly_units, with this
Python and this repo) into the user's unit folder and enables the timer; remove disables it
and deletes both; status reads them back through systemctl --user (lib/systemd.py).
Persistent=true catches up a run the PC was off for, as StartWhenAvailable does.
"""
import ntpath
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from decklab.lib import config

TASK_NAME = "Deck Lab database backup"
UNSUPPORTED = ("The nightly task uses Windows' Task Scheduler or Linux's systemd; here, run "
               "python -m decklab.db nightly from cron.")
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
AT = "03:30"
TIME_LIMIT = "PT2H"
ARGUMENTS = "-m decklab.db nightly"
PRIORITY = 7                       # Task Scheduler's default: below normal, out of the way


def _homenet():
    # Imported when used: homenet.commands brings in the server's modules, which nothing
    # else here needs (and the XML tests don't).
    from decklab.lib.homenet import commands
    return commands


def preview_systemd(unit, python, workdir, at=None, say=print):
    """Print one unit preview. This never inspects the host, reads data or installs units."""
    from decklab.db import systemd_units
    if unit not in ("service", "timer"):
        raise ValueError("preview-systemd requires --unit service or --unit timer.")
    units = systemd_units.nightly_units(python, workdir, AT if at is None else at)
    name = systemd_units.SERVICE if unit == "service" else systemd_units.TIMER
    say(units[name].rstrip("\n"))
    return 0


def task_xml(command, workdir, user, start=None, at=AT, name=TASK_NAME):
    """The task's definition as Task Scheduler's XML (every value escaped). start is the
    first day (default today); the trigger repeats daily from there at `at`, local time."""
    e = escape
    start = start or date.today()
    description = ("Backs up Deck Lab's database every night: pg_dump (copied to backup_dir, if set), prune old dumps, CSV export "
                   "to the export repo, a check of the data, and a monthly restore check (python -m decklab.db "
                   "nightly; its log is "
                   "decklab\\data\\logs\\db.log). Made by: python -m decklab.db schedule install. Run that again "
                   "after moving the repo or upgrading Python.")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Author>{e(user)}</Author>
    <Description>{e(description)}</Description>
    <URI>\\{e(name)}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start:%Y-%m-%d}T{e(at)}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{e(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>{TIME_LIMIT}</ExecutionTimeLimit>
    <Priority>{int(PRIORITY)}</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{e(str(command))}</Command>
      <Arguments>{e(ARGUMENTS)}</Arguments>
      <WorkingDirectory>{e(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def parse_task_xml(text):
    """What status looks at in the task's XML, as a dict: command, arguments, workdir, enabled,
    start (the trigger's StartBoundary), days (its interval), catch_up (StartWhenAvailable),
    time_limit, multiple, logon_type, run_level, user. Raises ValueError for XML that isn't a task."""
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text or "")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"the task's XML can't be read: {e}") from None
    if root.tag != f"{{{TASK_NS}}}Task":
        raise ValueError("that XML isn't a task")
    ns = {"t": TASK_NS}

    def find(path, default=None):
        node = root.find(path, ns)
        return node.text.strip() if node is not None and node.text else default

    trigger = "t:Triggers/t:CalendarTrigger/"
    return {
        "command": find("t:Actions/t:Exec/t:Command"),
        "arguments": find("t:Actions/t:Exec/t:Arguments", ""),
        "workdir": find("t:Actions/t:Exec/t:WorkingDirectory"),
        "enabled": find("t:Settings/t:Enabled", "true").lower() != "false",
        "start": find(trigger + "t:StartBoundary"),
        "trigger_enabled": find(trigger + "t:Enabled", "true").lower() != "false",
        "days": find(trigger + "t:ScheduleByDay/t:DaysInterval"),
        "catch_up": find("t:Settings/t:StartWhenAvailable", "false").lower() == "true",
        "time_limit": find("t:Settings/t:ExecutionTimeLimit", "PT72H"),
        "multiple": find("t:Settings/t:MultipleInstancesPolicy", "IgnoreNew"),
        "logon_type": find("t:Principals/t:Principal/t:LogonType"),
        "run_level": find("t:Principals/t:Principal/t:RunLevel"),
        "user": find("t:Principals/t:Principal/t:UserId"),
    }


def query_task(name=TASK_NAME):
    """The task (parse_task_xml), or None when it isn't registered."""
    code, out, _ = _homenet()._schtasks("/Query", "/TN", name, "/XML")
    if code != 0 or not out.strip():
        return None
    try:
        return parse_task_xml(out)
    except ValueError:
        return None


def psycopg_problem():
    """Why this Python can't run the nightly job (psycopg missing, even with the .venv's
    packages on its path: lib/venv.py), or None."""
    try:
        import psycopg  # noqa: F401
    except ImportError:
        venv = r".venv\Scripts\python" if sys.platform == "win32" else ".venv/bin/python"
        return (f"psycopg can't be imported by this Python ({sys.executable}), even with the repo's .venv "
                f"packages, so the task would fail every night. Install them ({venv} -m pip "
                "install -r decklab/requirements.txt), then run python -m decklab.db schedule install with "
                "the system python.")
    return None


def in_venv(program):
    """True when program (the task's command) is inside a .venv folder: the venv's launcher,
    not the system python the task should run."""
    parts = ntpath.normpath(str(program or "").strip('"')).replace("/", "\\").lower().split("\\")
    return ".venv" in parts


def _same(a, b):
    return bool(a and b) and ntpath.normcase(ntpath.normpath(str(a).strip('"'))) == \
        ntpath.normcase(ntpath.normpath(str(b).strip('"')))


def install(name=TASK_NAME, say=print):
    """Register (or replace) the task. Returns 0, or 1 when it can't be."""
    if _systemd().supported():
        return install_systemd(say)
    if sys.platform != "win32":
        say(UNSUPPORTED)
        return 1
    problem = psycopg_problem()
    if problem:
        say(problem)
        return 1
    homenet = _homenet()
    pythonw = homenet.pythonw_path()
    if not pythonw.is_file():
        say(f"pythonw.exe (the windowless Python) isn't beside this Python ({sys.executable}), so the task "
            "can't run without a window.")
        return 1
    error = homenet.register_task(task_xml(pythonw, config.REPO, homenet.task_user(), name=name), name)
    if error:
        say(f'The "{name}" task couldn\'t be registered: {error}')
        return 1
    task = query_task(name)
    if task is None or not _same(task["command"], pythonw):
        say(f'The "{name}" task was registered, but reading it back didn\'t show {pythonw}. '
            "Check it in Task Scheduler.")
        return 1
    say(f'Registered the "{name}" task: every day at {AT} (or as soon as the PC is on after that), it runs')
    say(f"  {pythonw} {ARGUMENTS}")
    say(f"  in {config.REPO}, as {homenet.task_user()}, with no window. Its log: decklab\\data\\logs\\db.log")
    return 0


def remove(name=TASK_NAME, say=print):
    """Delete the task. Returns 0 (also when there was none), or 1 when it couldn't be deleted."""
    if _systemd().supported():
        return remove_systemd(say)
    if sys.platform != "win32":
        say(UNSUPPORTED)
        return 1
    homenet = _homenet()
    if query_task(name) is None:
        say(f'The "{name}" task isn\'t registered, so there was nothing to remove.')
        return 0
    code, out, err = homenet._schtasks("/Delete", "/TN", name, "/F")
    if code != 0:
        say(f'The "{name}" task couldn\'t be removed: {homenet._said(out, err, code)}')
        return 1
    say(f'Removed the "{name}" task: the database is no longer backed up each night.')
    return 0


def describe(task, exists=None):
    """status's lines for a task (parse_task_xml's dict, or None)."""
    exists = exists or (lambda p: Path(p).exists())
    if task is None:
        return [f'Nightly task: "{TASK_NAME}" isn\'t registered (python -m decklab.db schedule install).']
    time = (task["start"] or "")[11:16] or "?"
    lines = [f'Nightly task: "{TASK_NAME}" runs {task["command"]} {task["arguments"]}',
             f"  in {task['workdir']}, daily at {time}"
             + (", catching up after the PC was off" if task["catch_up"] else "")
             + f", as {task['user']}."]
    if not task["enabled"] or not task["trigger_enabled"]:
        lines.append("  WARNING: it's disabled, so nothing is backed up.")
    program = (task["command"] or "").strip('"')
    if not program or not exists(program):
        lines.append(f"  WARNING: {program or '(nothing)'} isn't there any more; run schedule install again.")
    if task["workdir"] and not _same(task["workdir"], config.REPO):
        lines.append(f"  WARNING: it runs in {task['workdir']}, not this repo ({config.REPO}).")
    if program and in_venv(program):
        lines.append("  WARNING: it runs the .venv's pythonw.exe, a launcher that starts a second process; run "
                     "python -m decklab.db schedule install with the system python.")
    if task["arguments"].split() != ARGUMENTS.split():
        lines.append(f"  WARNING: its arguments aren't {ARGUMENTS}; run schedule install again.")
    return lines


def status(name=TASK_NAME):
    """The schedule status command's lines."""
    if _systemd().supported():
        return status_systemd()
    if sys.platform != "win32":
        return ["Nightly task: only Windows' Task Scheduler and Linux's systemd are supported; run "
                "python -m decklab.db nightly from cron."]
    return describe(query_task(name))


# ------------------------------------------------------------------ Linux: a systemd user timer

def _systemd():
    from decklab.lib import systemd
    return systemd


def _units():
    """The service and timer as install writes them now: this Python, this repo, AT."""
    from decklab.db import systemd_units
    return systemd_units.nightly_units(sys.executable, config.REPO.as_posix(), AT)


def install_systemd(say=print):
    """Write and enable decklab-nightly.service and .timer. Returns 0, or 1 when it can't."""
    from decklab.db import systemd_units
    systemd = _systemd()
    problem = psycopg_problem()
    if problem:
        say(problem)
        return 1
    try:
        units = _units()
    except ValueError as e:
        say(f"The nightly units can't be written for this Python and repo: {e}")
        return 1
    error = systemd.write_units(units)
    if error:
        say(f"The nightly timer couldn't be installed: {error}")
        return 1
    code, out, err = systemd.systemctl("enable", "--now", systemd_units.TIMER)
    if code != 0:
        say(f"The nightly timer was written but couldn't be enabled: {systemd.said(out, err, code)}")
        return 1
    folder = systemd.unit_dir()
    say(f"Installed the nightly timer: every day at {AT} (or as soon as the PC is on after that), "
        f"{systemd_units.SERVICE} runs")
    say(f"  {sys.executable} {ARGUMENTS}")
    say(f"  in {config.REPO}. Its units are in {folder}; its log: decklab/data/logs/db.log "
        f"(and journalctl --user -u {systemd_units.SERVICE}).")
    note = systemd.linger_note()
    if note:
        say(note)
    return 0


def remove_systemd(say=print):
    """Disable the timer and delete both units. Returns 0 (also when there were none), or 1."""
    from decklab.db import systemd_units
    systemd = _systemd()
    folder = systemd.unit_dir()
    names = (systemd_units.TIMER, systemd_units.SERVICE)
    if not any((folder / n).exists() for n in names):
        say("The nightly timer isn't installed, so there was nothing to remove.")
        return 0
    code, out, err = systemd.systemctl("disable", "--now", systemd_units.TIMER)
    if code != 0 and (folder / systemd_units.TIMER).exists():
        say(f"The nightly timer couldn't be disabled: {systemd.said(out, err, code)}")
        return 1
    error = systemd.remove_units(names)
    if error:
        say(f"The nightly timer couldn't be removed: {error}")
        return 1
    say("Removed the nightly timer: the database is no longer backed up each night.")
    return 0


def _usec_time(value):
    """systemctl show's time ("Mon 2026-10-26 03:30:00 AEST"), or None when it's unset."""
    value = (value or "").strip()
    return None if value in ("", "n/a", "0") else value


def status_systemd():
    """status's lines for the systemd timer."""
    from decklab.db import systemd_units
    systemd = _systemd()
    folder = systemd.unit_dir()
    timer_file, service_file = folder / systemd_units.TIMER, folder / systemd_units.SERVICE
    if not timer_file.exists() or not service_file.exists():
        return [f"Nightly timer: {systemd_units.TIMER} isn't installed (python -m decklab.db schedule install)."]
    lines = [f"Nightly timer: {systemd_units.TIMER} runs {systemd_units.SERVICE} daily at {AT}, catching up "
             f"after the PC was off ({folder})."]
    timer = systemd.show(systemd_units.TIMER, "UnitFileState", "ActiveState", "NextElapseUSecRealtime",
                         "LastTriggerUSec")
    if timer is None:
        lines.append("  WARNING: systemctl --user can't be asked about it (is the user manager running?).")
        return lines
    if timer.get("UnitFileState") != "enabled" or timer.get("ActiveState") != "active":
        lines.append(f"  WARNING: it isn't enabled and active ({timer.get('UnitFileState') or '?'}, "
                     f"{timer.get('ActiveState') or '?'}), so nothing is backed up: run schedule install again.")
    if _usec_time(timer.get("NextElapseUSecRealtime")):
        lines.append(f"  Next run: {_usec_time(timer['NextElapseUSecRealtime'])}.")
    service = systemd.show(systemd_units.SERVICE, "Result", "ExecMainStatus") or {}
    last = _usec_time(timer.get("LastTriggerUSec"))
    if last:
        result = service.get("Result") or "?"
        lines.append(f"  Last run: {last}, " + ("it succeeded." if result == "success" else
                                                 f"it failed ({result}, exit code "
                                                 f"{service.get('ExecMainStatus') or '?'}): see "
                                                 "decklab/data/logs/db.log."))
    try:
        expected = _units()
        current = {n: (folder / n).read_text(encoding="utf-8") for n in expected}
    except (OSError, UnicodeDecodeError, ValueError):
        current, expected = None, {}
    if current is not None and current != expected:
        lines.append(f"  WARNING: its units aren't what install writes now (for {sys.executable} in "
                     f"{config.REPO}); run python -m decklab.db schedule install again.")
    note = systemd.linger_note()
    if note:
        lines.append("  " + note)
    return lines
