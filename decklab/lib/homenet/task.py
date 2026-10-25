"""The Task Scheduler tasks' definitions: the server task's arguments,
quoted the way Windows reads a command line, and its XML, which install
registers and start and status read back (parse_task_xml); and the
watchdog task's (watchdog_xml, E11-S26), which install --at-logon registers
beside it."""
import ntpath
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

from .common import (
    SERVER_SCRIPT, TASK_DELAY, TASK_NAME, TASK_NS, TASK_PRIORITY, WATCHDOG_EVERY, WATCHDOG_PRIORITY,
    WATCHDOG_TIME_LIMIT, watchdog_name,
)


def quote_arg(arg):
    """One argument for a Windows command line, quoted the way
    CommandLineToArgvW reads it back (split_args)."""
    return subprocess.list2cmdline([str(arg)])


def server_arguments(script=None, port=None, log_path=None, host=None):
    """The task's arguments: the server script (quoted), plus --host,
    --port and --log when they're given."""
    args = [str(script or SERVER_SCRIPT)]
    if host:
        args += ["--host", str(host)]
    if port is not None:
        args += ["--port", str(port)]
    if log_path:
        args += ["--log", str(log_path)]
    return " ".join(f'"{a}"' if i == 0 else quote_arg(a) for i, a in enumerate(args))


def task_xml(command, arguments, workdir, user, name=TASK_NAME, delay=TASK_DELAY,
             priority=TASK_PRIORITY, at_logon=False):
    """The task's definition, as Task Scheduler's XML (every value escaped).

    It runs as user, only while they're logged on (InteractiveToken),
    without administrator (LeastPrivilege), when start runs it. Its logon
    trigger, for user alone, is there but off unless at_logon (install
    --at-logon), so by default Deck Lab starts only when asked. No time
    limit (the default 72 hours would stop the server after three days),
    batteries don't matter, a second start while it runs is ignored, normal
    priority, and no idle or network conditions."""
    description = ("Starts Deck Lab's web server (decklab\\server.py) with no window, when "
                   "python -m decklab.lib.homenet start runs it"
                   + (", and at logon. " if at_logon else ". The logon trigger is off: install --at-logon "
                                                         "turns it on. ")
                   + "Made by: python -m decklab.lib.homenet install. Run that again after moving "
                   "the repo or upgrading Python.")
    e = escape
    triggers = f"""    <LogonTrigger>
      <Enabled>{"true" if at_logon else "false"}</Enabled>
      <UserId>{e(user)}</UserId>
      <Delay>{e(delay)}</Delay>
    </LogonTrigger>"""
    return _task_document(command, arguments, workdir, user, name, description, triggers, "PT0S", priority)


def watchdog_arguments(name=TASK_NAME):
    """The watchdog task's arguments: homenet's ensure, for the server task name."""
    return f"-m decklab.lib.homenet ensure --task {quote_arg(name)}"


def watchdog_xml(command, arguments, workdir, user, name=None, start=None, every=WATCHDOG_EVERY):
    """The watchdog task's definition (E11-S26): it runs command (pythonw.exe)
    with arguments (watchdog_arguments) every every (an ISO 8601 duration),
    forever, from start (a datetime, default now) rounded up to the next
    minute, in local time. Like the server task it runs as user only while
    they're logged on, without administrator, and a second run while one
    runs is ignored; runs missed while the PC was asleep or off are skipped,
    and Task Scheduler ends a run after WATCHDOG_TIME_LIMIT. name defaults to
    watchdog_name() of the server task. A time trigger rather than a logon
    trigger with repetition: the user never logs off, so that would only
    begin at the next logon."""
    e = escape
    name = name or watchdog_name()
    when = start or datetime.now()
    rounded = when.replace(second=0, microsecond=0)
    if rounded != when:
        rounded += timedelta(minutes=1)
    description = ("Restarts Deck Lab if it stops unexpectedly: every few minutes it runs python -m "
                   "decklab.lib.homenet ensure, which starts the server's task only when nothing serves "
                   "the port and it wasn't stopped on purpose (homenet stop). Made by: python -m "
                   "decklab.lib.homenet install --at-logon; install without --at-logon removes it.")
    triggers = f"""    <TimeTrigger>
      <Repetition>
        <Interval>{e(every)}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{rounded.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>"""
    return _task_document(command, arguments, workdir, user, name, description, triggers,
                          WATCHDOG_TIME_LIMIT, WATCHDOG_PRIORITY)


def _task_document(command, arguments, workdir, user, name, description, triggers, time_limit, priority):
    """A task's XML around its triggers, with the principal and settings
    both tasks share (every value escaped)."""
    e = escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="{TASK_NS}">
  <RegistrationInfo>
    <Author>{e(user)}</Author>
    <Description>{e(description)}</Description>
    <URI>\\{e(name)}</URI>
  </RegistrationInfo>
  <Triggers>
{triggers}
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
    <StartWhenAvailable>false</StartWhenAvailable>
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
    <ExecutionTimeLimit>{e(time_limit)}</ExecutionTimeLimit>
    <Priority>{int(priority)}</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{e(str(command))}</Command>
      <Arguments>{e(arguments)}</Arguments>
      <WorkingDirectory>{e(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def parse_task_xml(text):
    """The parts of a task's XML that status and start look at, as a dict:
    command, arguments, workdir, enabled, time_limit, priority, multiple,
    logon_users (users with an enabled logon trigger), delay, repeats (the
    repetition interval of each enabled time trigger: the watchdog's),
    logon_type, run_level. Raises ValueError for XML that isn't a task."""
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text or "")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"the task's XML can't be read: {e}") from None
    ns = {"t": TASK_NS}

    def find(path, default=None):
        node = root.find(path, ns)
        return node.text.strip() if node is not None and node.text else default

    if root.tag != f"{{{TASK_NS}}}Task":
        raise ValueError("that XML isn't a task")
    logon_users, delay = [], None
    for trigger in root.findall("t:Triggers/t:LogonTrigger", ns):
        enabled = trigger.find("t:Enabled", ns)
        if enabled is not None and (enabled.text or "").strip().lower() == "false":
            continue
        user = trigger.find("t:UserId", ns)
        logon_users.append(user.text.strip() if user is not None and user.text else None)
        node = trigger.find("t:Delay", ns)
        delay = delay or (node.text.strip() if node is not None and node.text else None)
    repeats = []                            # each enabled time trigger's repetition interval
    for trigger in root.findall("t:Triggers/t:TimeTrigger", ns):
        enabled = trigger.find("t:Enabled", ns)
        if enabled is not None and (enabled.text or "").strip().lower() == "false":
            continue
        node = trigger.find("t:Repetition/t:Interval", ns)
        if node is not None and node.text:
            repeats.append(node.text.strip())
    return {
        "command": find("t:Actions/t:Exec/t:Command"),
        "arguments": find("t:Actions/t:Exec/t:Arguments", ""),
        "workdir": find("t:Actions/t:Exec/t:WorkingDirectory"),
        "enabled": find("t:Settings/t:Enabled", "true").lower() != "false",
        "time_limit": find("t:Settings/t:ExecutionTimeLimit", "PT72H"),
        "priority": int(find("t:Settings/t:Priority", "7")),
        "multiple": find("t:Settings/t:MultipleInstancesPolicy", "IgnoreNew"),
        "logon_users": logon_users,
        "delay": delay,
        "repeats": repeats,
        "logon_type": find("t:Principals/t:Principal/t:LogonType"),
        "run_level": find("t:Principals/t:Principal/t:RunLevel"),
    }


def _task_file(path, workdir):
    """A path from the task's arguments as Task Scheduler's program sees it:
    variables expanded, and relative to the task's folder."""
    path = ntpath.expandvars(str(path).strip().strip('"'))
    if not ntpath.isabs(path) and workdir:
        path = ntpath.join(ntpath.expandvars(str(workdir).strip().strip('"')), path)
    return path
