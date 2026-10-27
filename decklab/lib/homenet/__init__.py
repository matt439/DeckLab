"""Start, stop and restart Deck Lab in the background (at logon too, if
asked), and check that phones can reach it (PLAN.md part 8, Milestone 6).

Usage (from the repo root):
    python -m decklab.lib.homenet install [--no-start]   set up the task start runs (and start it now)
    python -m decklab.lib.homenet install --at-logon     the same, start Deck Lab at every logon, and
                                                         restart it if it stops unexpectedly (the watchdog)
    python -m decklab.lib.homenet start                  start it now, through that task
    python -m decklab.lib.homenet stop                   stop it (a matchup saves its games first)
    python -m decklab.lib.homenet restart                after changing Deck Lab's code or a git pull
    python -m decklab.lib.homenet remove                 stop it and delete the task
    python -m decklab.lib.homenet status                 can phones reach it? what to fix if not
    python -m decklab.lib.homenet ensure                 what the watchdog task runs every 5 minutes

--port changes the port (default "port" in decklab/config.json, 8642) and
--task the task's name (default "Deck Lab"); both are there for testing
with a throwaway task. install --log PATH has the server write its log
there instead of decklab/data/logs/server.log, and install --host ADDRESS
has it listen on that address only (a test task on 127.0.0.1 doesn't make
Windows ask whether to let pythonw.exe through the firewall).

The task: install registers a Task Scheduler task, "Deck Lab" in the root
folder, for the current user only (no administrator needed). It runs
pythonw.exe (the windowless Python beside this one) with
decklab\\server.py, from the repo folder. Its logon trigger is there but
off, so Deck Lab starts only when start runs the task; install --at-logon
turns the trigger on (since 2026-10-01 it's off unless asked for, as the
user wanted manual starts). The server writes its log to
decklab/data/logs/server.log and records itself in decklab/data/server.json
(lib/control.py), which is how stop, restart and status find it. start
always goes through the task, never starts pythonw itself: a process started
from a tool's own shell can be killed when that shell's job ends.

Restarting after a crash (E11-S26, watchdog.py): install --at-logon also
registers "Deck Lab watchdog", which every 5 minutes while the user is
logged on runs ensure: it starts the "Deck Lab" task only when nothing
serves the port, the server wasn't stopped on purpose (control's stop
marker: stop writes it, start and restart clear it, and so does the server
once it's listening, so the next logon ends it too) and 3 restarts in a row
haven't failed to stay up. install without --at-logon removes it, and so
does remove. A task set up before 2026-10-20 has none until install
--at-logon --no-start runs again; status says so.

The running server keeps the code it started with, so restart after
changing Deck Lab's code or pulling from git. Re-run install after moving
the repo or upgrading Python: start and restart check that the program and
script the task starts are still there before they stop or start anything,
and status says when they aren't.

status prints a checklist, each line OK, WARN or PROBLEM with a fix, and
exits 1 when anything is a PROBLEM:
    Server          running? since when, in the background or in a window, card data, the log
    Start at logon  the task: registered, enabled, starting this repo's server with a pythonw
                    that exists, as this user while logged on, without administrator, at
                    normal priority; whether it starts at logon (off is fine); when it last
                    ran and how that ended
    Restart after a crash  the watchdog task (with start at logon): there, running ensure from
                    this repo with pythonw every 5 minutes; a recent restart, a give-up, a stop
                    on purpose, and how its last check ended
    Network         the physical connection with the default route (not a VPN): its address,
                    and Private or Public
    Firewall        a rule letting TCP <port> in on Private networks from the home network;
                    rules wider than that; block rules for Python or the port (they beat
                    allow rules); profiles turned off
    Addresses       the URLs for phones (the IP address, and <pc>.local if the PC answers mDNS),
                    and a reminder to reserve a DHCP address in the router
    Sleep           whether the PC sleeps on mains power (the page stops while it does)
The Windows facts come from one PowerShell call that prints JSON (GATHER_PS;
read-only, no administrator needed, about 2 seconds), and pure functions
judge them, so the judgements are tested with canned data. Firewall rules
are read through the firewall's COM object (HNetCfg.FwPolicy2): without
administrator, Get-NetFirewallPortFilter stops partway with "Access is
denied" and misses rules. Checks from the PC itself can't prove a phone
gets through; the real test is opening the address on a phone.

The one step that needs administrator, the firewall rules and the network
category, is decklab/network-setup.ps1 (status points at it). The router's
address reservation is done in the router's own page (README.md).

Where things are (lib/homenet/):
    common.py    the settings and constants, and helpers the others share
    task.py      the task's definition: its arguments and its XML
    commands.py  the commands and main; the task in Task Scheduler (schtasks),
                 the running server, and the Server and Start at logon checks
    gather.py    status's PowerShell call (GATHER_PS)
    mdns.py      the <pc>.local lookup
    checks.py    the Network, Firewall, Addresses and Sleep checks, and the report
    watchdog.py  ensure (restart after a crash), its record and log, and its status lines
    service.py   off Windows: the systemd user service in place of the task (E11-S33)
    __main__.py  python -m decklab.lib.homenet
The names tests replace (control, _schtasks, probe, run_powershell,
MDNS_GROUP and others) aren't offered here: they're used from their own
module, such as homenet.commands.probe, so a test can't patch a copy here
that the code never reads.
"""
from .checks import (
    _action, _address_parts, _category, _enabled, _ipv4_span, _opens, _origin, _physical_up, _profiles_text,
    _rule_program, _rule_service_any, _spans_cover, all_ports, check_addresses, check_firewall, check_network,
    check_sleep, exit_code, format_report, lan_of, made_by_setup, parse_powercfg, pick_interface, port_covered,
    profile_set, protocol_name, remote_any, scope_gaps,
)
from .commands import (
    NOT_LISTENING, _delay_text, _file_size, _last_run_line, _log_tail, _probe_host, _said, _task_settings_lines,
    _usable_task, _wait_for_start, check_server, check_task, cmd_install, cmd_restart, code_changed_since,
    delete_task, describe_running, how_to_stop, main, query_task, register_task, same_user, server_state, task_host,
    task_log_file, task_port, task_problem, urls,
)
from .common import (
    LOG_TAIL, OK, POWERSHELL, PROBE_TIMEOUT, PROBLEM, PROFILE_BITS, PROFILES, PS_TIMEOUT, RERUN_AFTER, SCHTASKS,
    SCHTASKS_TIMEOUT, SERVER_SCRIPT, SETUP_MARKER, SETUP_RULE_NAMES, SETUP_RUN, SETUP_SCRIPT, START_WAIT, STOP_WAIT,
    TASK_DELAY, TASK_NAME, TASK_NOT_RUN_YET, TASK_NS, TASK_PRIORITY, TASK_RUNNING, TASK_TERMINATED, TCP_MAXRT, WARN,
    WATCHDOG_EVERY, WATCHDOG_GIVE_UP, WATCHDOG_GRACE, WATCHDOG_LOG_BYTES, WATCHDOG_PRIORITY, WATCHDOG_STABLE,
    WATCHDOG_TIME_LIMIT, _SPAWN, _SYSTEM32, _decode, _int, _repo_rel, _when, line, log, loopback, norm_path, say,
    split_args, watchdog_name,
)
from .gather import GATHER_PS, step_error
from .mdns import MDNS_WAIT, _read_name, mdns_answers, mdns_query
from .task import _task_file, parse_task_xml, quote_arg, server_arguments, task_xml, watchdog_arguments, watchdog_xml
from .watchdog import check_watchdog, cmd_ensure, decide
