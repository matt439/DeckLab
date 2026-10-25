"""What the homenet tests share (test_homenet.py, test_homenet_checks.py,
test_homenet_gather.py, test_homenet_watchdog.py and test_network_setup.py): canned facts, among them
the PC as it was on 2026-10-01, a stand-in for control, and Guarded, the
base class that keeps the real schtasks, PowerShell and control out of reach.
discover doesn't collect this module: its name doesn't start with test_.
"""
import ctypes
import io
import socket
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from decklab.lib import config, homenet

WINDOWS = sys.platform == "win32"
SETUP_PS1 = config.DECKLAB / "network-setup.ps1"
PYDIR = r"C:\Users\player\AppData\Local\Python\pythoncore-3.14-64"
PYTHON = PYDIR + r"\python.exe"
PYTHONW = PYDIR + r"\pythonw.exe"
SCRIPT = r"C:\VSProjects\TradingCardCollection\decklab\server.py"
PORT = 8642         # only ever a number in canned facts; nothing connects to it


def free_port():
    """A port nothing listens on (never 8642: the OS hands out high ports)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def is_admin():
    if not WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return True         # can't tell: act as if it is, and skip the risky tests


def levels(lines):
    return [item["level"] for item in lines]


def texts(lines):
    return "\n".join(f"{item['level']} {item['text']} | {item.get('fix') or ''}" for item in lines)


# ------------------------------------------------------------ canned facts

def rule(name, program="", protocol=6, ports="8642", remote="*", profiles=2, action=1, enabled=True,
         service="", local="*", interface_types="All", description=""):
    """A firewall rule the way the facts script prints it (the COM object's numbers)."""
    return {"name": name, "program": program, "service": service, "protocol": protocol, "local_ports": ports,
            "remote_addresses": remote, "local_addresses": local, "interface_types": interface_types,
            "enabled": enabled, "profiles": profiles, "action": action, "description": description}


DECK_LAB_GOOD = rule("Deck Lab (TCP 8642)", remote="LocalSubnet", profiles=2)
DECK_LAB_BROAD = rule("Deck Lab (TCP 8642)", remote="*", profiles=2147483647)
PYTHON_UDP = rule("python.exe", program=PYTHON.lower(), protocol=17, ports="*", profiles=6)
PYTHON_TCP = rule("python.exe", program=PYTHON.lower(), protocol=6, ports="*", profiles=6)
PYTHONW_RULE = rule("Deck Lab (pythonw)", program=PYTHONW, remote="LocalSubnet", profiles=2)
# What Windows' "allow this app" prompt left for pythonw.exe at 11:42 on
# 2026-10-01 (a test server on an uncovered port asked; see REAL_FACTS_NOON).
PYTHONW_UDP = rule("pythonw.exe", program=PYTHONW.lower(), protocol=17, ports="*", profiles=6)
PYTHONW_TCP = rule("pythonw.exe", program=PYTHONW.lower(), protocol=6, ports="*", profiles=6)


def profiles(domain=True, private=True, public=True, block_private=False):
    return [{"name": "Domain", "bit": 1, "enabled": domain, "block_all": False},
            {"name": "Private", "bit": 2, "enabled": private, "block_all": block_private},
            {"name": "Public", "bit": 4, "enabled": public, "block_all": False}]


def network(category="Private", origin="Dhcp", address="192.0.2.10", extra_routes=()):
    return {
        "routes": [{"if_index": 17, "next_hop": "192.0.2.1", "metric": 20}, *extra_routes],
        "interfaces": [{"if_index": 17, "alias": "Ethernet", "description": "Realtek PCIe 2.5GbE Family Controller",
                        "mac": "00-00-5E-00-53-01", "status": "Up", "virtual": False, "if_type": 6,
                        "dhcp": "Enabled", "category": category, "network_name": "Network",
                        "ipv4": [{"address": address, "prefix": 24, "origin": origin}]}],
    }


LAN = homenet.lan_of(network())     # 192.0.2.10 on 192.0.2.0/24, wired


POWERCFG = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x00000000
    Current DC Power Setting Index: 0x00000258"""

# This PC on the morning of 2026-10-01: Private network from DHCP, the right
# Deck Lab rule plus one open everywhere, Windows' prompt rules for
# python.exe on Private and Public, pythonw.exe with no rule of its own (the
# port rule covers it, so Windows doesn't ask), every profile on, never
# sleeps, no task.
REAL_FACTS = {
    "errors": [], "ms": 1482, "seconds": 2.2, "task": None, "network": network(),
    "firewall": {"current": 6, "profiles": profiles(),
                 "rules": [PYTHON_UDP, PYTHON_TCP, DECK_LAB_GOOD, DECK_LAB_BROAD]},
    "power": POWERCFG,
}


def task_definition(command=PYTHONW, arguments=None, enabled=True, time_limit="PT0S", users=("HOMEPC\\player",),
                    logon_type="InteractiveToken", run_level="LeastPrivilege", priority=5, multiple="IgnoreNew"):
    return {"command": command, "arguments": f'"{SCRIPT}"' if arguments is None else arguments,
            "workdir": r"C:\VSProjects\TradingCardCollection", "enabled": enabled, "time_limit": time_limit,
            "priority": priority, "multiple": multiple, "logon_users": list(users), "delay": "PT30S",
            "logon_type": logon_type, "run_level": run_level}


# The same PC at noon: the task installed and running, and the two rules
# Windows' prompt made for pythonw.exe (TCP and UDP, every port, Private and
# Public). status then gave 0 problems and 5 warnings.
REAL_FACTS_NOON = {
    "errors": [], "ms": 2100, "seconds": 2.1, "network": network(),
    "task": {"xml": homenet.task_xml(PYTHONW, f'"{homenet.SERVER_SCRIPT}"', config.REPO, "HOMEPC\\player",
                                     at_logon=True),
             "state": "Running", "last_run": "2026-10-01T11:49:46", "last_result": 267009},
    "firewall": {"current": 6, "profiles": profiles(),
                 "rules": [PYTHONW_UDP, PYTHONW_TCP, PYTHON_UDP, PYTHON_TCP, DECK_LAB_GOOD, DECK_LAB_BROAD]},
    "power": POWERCFG,
}


LOGON = "2026-10-18T07:58:12+00:00"     # the logon time fake_control's session has


def fake_control(state=None, stop="not running"):
    """A stand-in for decklab.lib.control: the real one reads and signals
    the real state file and server, and writes the real stop marker. Its
    stop markers are kept in markers (port -> marker), from this logon
    (LOGON); each function is a Mock, so a test can see the calls."""
    markers = {}

    def mark_stopped(port, by, path=None, keep=False, restart=False):
        if keep and port in markers:
            return False
        markers[port] = {"version": 1, "port": port, "at": "2026-10-20T18:02:11+10:00", "by": by, "logon": LOGON}
        if restart:
            markers[port]["restart"] = True
        return True

    fake = types.SimpleNamespace(
        STATE_FILE=Path(tempfile.gettempdir()) / "decklab-test-no-such-state.json",
        LOG_FILE=Path(tempfile.gettempdir()) / "decklab-test-no-such-log.log",
        markers=markers,
        read_state=mock.Mock(return_value=state),
        request_stop=mock.Mock(return_value=stop),
        mark_stopped=mock.Mock(side_effect=mark_stopped),
        clear_stopped=mock.Mock(side_effect=lambda port, path=None: markers.pop(port, None) is not None),
        read_stopped=mock.Mock(side_effect=lambda port, path=None, logon=None: markers.get(port)),
        logon_time=mock.Mock(return_value=LOGON),
    )
    fake.stop_marker_path = lambda port, path=None: Path(fake.STATE_FILE).with_name(f"stopped-{port}.json")
    return fake


def running_state(port=PORT, background=True, started="2026-10-01T18:02:11", python=PYTHONW):
    return {"version": 1, "pid": 4242, "host": "0.0.0.0", "port": port, "started": started,
            "python": python, "log": r"C:\VSProjects\TradingCardCollection\decklab\data\logs\server.log",
            "background": background}


class Quiet:
    """Capture stdout and stderr of a command."""

    def __enter__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self._o, self._e = redirect_stdout(self.out), redirect_stderr(self.err)
        self._o.__enter__()
        self._e.__enter__()
        return self

    def __exit__(self, *exc):
        self._e.__exit__(*exc)
        self._o.__exit__(*exc)

    @property
    def text(self):
        return self.out.getvalue() + self.err.getvalue()


class FakeTime:
    """homenet.commands' time module in command tests (start's wait): sleep
    moves a pretend clock on (the real time.sleep is never patched: other
    tests' threads use it)."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    mktime = staticmethod(time.mktime)


class Guarded(unittest.TestCase):
    """Every test gets a fake control, whose state file and log are in a
    folder of the test's own (where the watchdog's record and log go too),
    and schtasks and PowerShell that fail the test if it reaches them
    without saying so."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.control = fake_control()
        self.control.STATE_FILE = self.data / "server.json"
        self.control.LOG_FILE = self.data / "logs" / "server.log"
        self.patch("decklab.lib.homenet.commands.control", self.control)
        self.schtasks = self.patch("decklab.lib.homenet.commands._schtasks",
                                   side_effect=AssertionError("schtasks reached without a mock"))
        self.patch("decklab.lib.homenet.gather.run_powershell", side_effect=AssertionError("PowerShell reached"))
        # config.json's tunnel stays out of status: it would reach the internet.
        self.patch("decklab.lib.tunnel.settings_of", return_value=None)
        self.patch("decklab.lib.tunnel.check_public", side_effect=AssertionError("public address reached"))

    def patch(self, target, new=mock.DEFAULT, **kwargs):
        patcher = mock.patch(target, new, **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value
