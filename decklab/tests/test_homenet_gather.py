"""Tests for decklab/lib/homenet/gather.py and mdns.py: the PowerShell call
that gathers status's facts, and the <pc>.local lookup. One check runs the
real facts script on Windows (it only reads, for a task that doesn't exist);
the mDNS lookups go to a stand-in responder on 127.0.0.1, so nothing goes on
the network.

Run from the repo root: python scripts/test_fixtures.py
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from decklab.lib import homenet
from decklab.tests.homenet_support import PORT, WINDOWS, Guarded, free_port


# ------------------------------------------------------------ mDNS

def dns_response(name, address, compress=True, qr=True):
    """A DNS response: the question, then an A record for name (by a
    compression pointer to the question's name when compress)."""
    question = homenet.mdns_query(name)[12:]
    head = struct.pack("!6H", 0, 0x8400 if qr else 0, 1, 1, 0, 0)
    rname = b"\xc0\x0c" if compress else question[:-4]
    record = rname + struct.pack("!HHIH", 1, 0x8001, 120, 4) + socket.inet_aton(address)
    return head + question + record


class MdnsTests(unittest.TestCase):
    def test_query(self):
        packet = homenet.mdns_query("HomePC.local", 7)
        self.assertEqual(packet[:12], struct.pack("!6H", 7, 0, 1, 0, 0, 0))
        self.assertEqual(packet[12:], b"\x06HomePC\x05local\x00" + struct.pack("!2H", 1, 0x8001))

    def test_answers(self):
        self.assertEqual(homenet.mdns_answers(dns_response("HomePC.local", "192.0.2.10"), "homepc.local"),
                         ["192.0.2.10"])
        self.assertEqual(homenet.mdns_answers(dns_response("HomePC.local", "192.0.2.10", compress=False),
                                              "HOMEPC.LOCAL."), ["192.0.2.10"])

    def test_ignores_queries_other_names_and_junk(self):
        self.assertEqual(homenet.mdns_answers(dns_response("HomePC.local", "1.2.3.4", qr=False), "homepc.local"), [])
        self.assertEqual(homenet.mdns_answers(dns_response("Other.local", "1.2.3.4"), "homepc.local"), [])
        good = dns_response("HomePC.local", "1.2.3.4")
        for junk in (b"", good[:20], good[:-2], b"\x00" * 12 + b"\xc0\x0c"):
            self.assertEqual(homenet.mdns_answers(junk, "homepc.local"), [])
        looping = struct.pack("!6H", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c"
        self.assertEqual(homenet.mdns_answers(looping, "homepc.local"), [])

    def test_lookup_against_a_local_responder(self):
        # A stand-in responder on 127.0.0.1, so nothing goes on the network.
        responder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        responder.bind(("127.0.0.1", 0))
        responder.settimeout(3)
        got = {}

        def answer():
            try:
                data, peer = responder.recvfrom(9000)
                got["query"] = data
                responder.sendto(dns_response("TestPC.local", "192.0.2.10"), peer)
            except OSError:
                pass
        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        try:
            with mock.patch.object(homenet.mdns, "MDNS_GROUP", responder.getsockname()):
                result = homenet.mdns.mdns_lookup("TestPC.local", None, wait=2)
        finally:
            thread.join(3)
            responder.close()
        self.assertEqual(result, {"answered": True, "addresses": ["192.0.2.10"], "error": None})
        self.assertEqual(got["query"][12:], homenet.mdns_query("TestPC.local")[12:])

    def test_lookup_without_an_answer(self):
        silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        silent.bind(("127.0.0.1", 0))
        try:
            with mock.patch.object(homenet.mdns, "MDNS_GROUP", silent.getsockname()):
                started = time.monotonic()
                result = homenet.mdns.mdns_lookup("TestPC.local", None, wait=0.3)
        finally:
            silent.close()
        self.assertFalse(result["answered"])
        self.assertLess(time.monotonic() - started, 2)


# ------------------------------------------------------------ gathering facts

class GatherTests(Guarded):
    def test_passes_task_and_port(self):
        homenet.gather.run_powershell.side_effect = None
        homenet.gather.run_powershell.return_value = {"errors": [], "task": None}
        with mock.patch.object(sys, "platform", "win32"):
            facts = homenet.gather.gather_facts("Deck Lab test", 18642)
        script, env = homenet.gather.run_powershell.call_args[0]
        self.assertIs(script, homenet.GATHER_PS)
        self.assertEqual(env, {"DECKLAB_TASK": "Deck Lab test", "DECKLAB_PORT": "18642",
                               "DECKLAB_WATCHDOG_TASK": "Deck Lab test watchdog"})
        self.assertIn("seconds", facts)

    def test_the_watchdog_task_is_read_like_the_server_task(self):
        # One PowerShell function reads both tasks, each by its own name from the environment.
        self.assertIn("Step 'task' { TaskFacts $env:DECKLAB_TASK }", homenet.GATHER_PS)
        self.assertIn("Step 'watchdog' { TaskFacts $env:DECKLAB_WATCHDOG_TASK }", homenet.GATHER_PS)
        self.assertNotIn("-TaskName $env:", homenet.GATHER_PS)

    def test_failure_is_kept_for_every_step(self):
        homenet.gather.run_powershell.side_effect = RuntimeError("PowerShell didn't finish within 30 seconds")
        with mock.patch.object(sys, "platform", "win32"):
            facts = homenet.gather.gather_facts("Deck Lab", PORT)
        self.assertEqual(homenet.step_error(facts, "firewall"), "PowerShell didn't finish within 30 seconds")

    def test_run_powershell(self):
        done = subprocess.CompletedProcess([], 0, b'{"a": 1}\r\n', b"")
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            self.assertEqual(RealPowerShell.call("x", {"K": "v"}), {"a": 1})
        args, kwargs = run.call_args
        self.assertIn("-NoProfile", args[0])
        self.assertIn("-NonInteractive", args[0])
        self.assertIn("-EncodedCommand", args[0])
        self.assertEqual(kwargs["env"]["K"], "v")
        self.assertIn("timeout", kwargs)
        if WINDOWS:
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_run_powershell_failures(self):
        with mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("powershell", 30)):
            with self.assertRaisesRegex(RuntimeError, "didn't finish"):
                RealPowerShell.call("x")
        done = subprocess.CompletedProcess([], 1, b"", b"Something broke")
        with mock.patch.object(subprocess, "run", return_value=done):
            with self.assertRaisesRegex(RuntimeError, "Something broke"):
                RealPowerShell.call("x")


class RealPowerShell:
    """The real run_powershell, from before Guarded patched it."""
    function = homenet.gather.run_powershell

    @classmethod
    def call(cls, *args, **kwargs):
        return cls.function(*args, **kwargs)


@unittest.skipUnless(WINDOWS, "the facts come from Windows")
class RealFactsTests(unittest.TestCase):
    """GATHER_PS on this PC. It only reads (the task, the network, the
    firewall's rules, powercfg), for a task name that doesn't exist."""

    def test_shape(self):
        # CI's runner (a low-priority shared machine) can take longer than the PC's 30 seconds to list the
        # firewall's rules, so there the shape is checked with more time and only the PC is held to the limit.
        ci = bool(os.environ.get("GITHUB_ACTIONS"))
        started = time.monotonic()
        facts = RealPowerShell.call(homenet.GATHER_PS, {"DECKLAB_TASK": "Deck Lab test no such task",
                                                        "DECKLAB_WATCHDOG_TASK": "Deck Lab test no such watchdog",
                                                        "DECKLAB_PORT": str(free_port())},
                                    timeout=180 if ci else homenet.PS_TIMEOUT)
        if not ci:
            self.assertLess(time.monotonic() - started, homenet.PS_TIMEOUT)
        self.assertEqual(facts["errors"], [])
        self.assertIsNone(facts["task"])
        self.assertIsNone(facts["watchdog"])
        self.assertIn("routes", facts["network"])
        self.assertEqual([p["name"] for p in facts["firewall"]["profiles"]], ["Domain", "Private", "Public"])
        self.assertIsInstance(facts["firewall"]["rules"], list)
        self.assertIsNotNone(homenet.parse_powercfg(facts["power"]))
        for item in facts["firewall"]["rules"]:
            self.assertEqual(set(item), {"name", "program", "service", "protocol", "local_ports",
                                         "remote_addresses", "local_addresses", "interface_types", "enabled",
                                         "profiles", "action", "description"})
        for item in facts["network"]["interfaces"]:
            self.assertIn("virtual", item)
            self.assertIn("if_type", item)


if __name__ == "__main__":
    unittest.main()
