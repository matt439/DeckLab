"""Tests for wake-on-request's PC side: decklab/lib/keepawake.py (holding the PC awake while
Deck Lab is in use, the requests that count as use, waking from sleep), server_http noting
real requests, Tunnel.restart_now, homenet status's Sleep and Wake lines with a "wake" block,
and the nightly task's WakeToRun. No real power request is made: the power primitive, clocks
and processes are fakes.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_keepawake
"""
import contextlib
import http.client
import tempfile
import threading
import unittest
from datetime import date
from unittest import mock

from decklab.db import schedule
from decklab.lib import keepawake, server_http, tunnel
from decklab.lib.homenet import checks
from decklab.lib.homenet.common import OK, WARN


class FakePower:
    def __init__(self):
        self.held = False
        self.calls = []

    def hold(self):
        self.held = True
        self.calls.append("hold")

    def release(self):
        self.held = False
        self.calls.append("release")


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def controller(idle_minutes=20, log=None, slept=None):
    """(controller, monotonic clock, power). Its wall clock is ka.wall: moved only by the
    resume tests, so jumps of the idle clock alone never look like a sleep. slept: a fake
    sleep counter (None: the wall clock notices sleeps, as off Windows)."""
    clock = FakeClock()
    wall = FakeClock(1_700_000_000.0)
    power = FakePower()
    ka = keepawake.KeepAwake(idle_minutes, power=power, clock=wall, monotonic=clock, interval=15,
                             log=log, slept=slept)
    ka.wall = wall
    return ka, clock, power


class ActivityTests(unittest.TestCase):

    def test_real_requests_count(self):
        for method, path in (("GET", "/"), ("GET", "/?profile=matt"), ("GET", "/api/decks"),
                             ("POST", "/api/deck/save"), ("PUT", "/api/simulations"),
                             ("GET", "/api/matchups?running=1"), ("GET", "/index.html")):
            self.assertTrue(keepawake.counts_as_activity(method, path, {}), (method, path))

    def test_status_head_static_and_polls_dont(self):
        self.assertFalse(keepawake.counts_as_activity("GET", "/api/status", {}))
        self.assertFalse(keepawake.counts_as_activity("GET", "/api/status/", {}))
        self.assertFalse(keepawake.counts_as_activity("HEAD", "/", {}))
        self.assertFalse(keepawake.counts_as_activity("HEAD", "/api/decks", {}))
        for path in ("/core.js?v=3", "/style.css", "/fonts/inter.woff2", "/icons/icon-192.png", "/favicon.ico",
                     "/manifest.webmanifest"):
            self.assertFalse(keepawake.counts_as_activity("GET", path, {}), path)
        self.assertFalse(keepawake.counts_as_activity("GET", "/api/matchups?running=1",
                                                      {"X-Deck-Lab-Poll": "1"}))
        # Only exactly "1" marks a poll.
        self.assertTrue(keepawake.counts_as_activity("GET", "/api/decks", {"X-Deck-Lab-Poll": "0"}))


class ControllerTests(unittest.TestCase):

    def test_holds_after_activity_and_releases_when_idle(self):
        ka, clock, power = controller(idle_minutes=20)
        self.assertTrue(ka.tick())              # starting counts as use
        self.assertTrue(power.held)
        clock.now += 19 * 60
        self.assertTrue(ka.tick())
        clock.now += 2 * 60
        self.assertFalse(ka.tick())
        self.assertFalse(power.held)
        ka.note_activity()
        self.assertTrue(ka.tick())
        self.assertTrue(power.held)
        self.assertEqual(ka.status()["reasons"], ["in use"])
        self.assertTrue(ka.status()["holding"])
        self.assertEqual(ka.status()["idle_minutes"], 20)

    def test_providers_hold_while_busy(self):
        ka, clock, power = controller(idle_minutes=1)
        busy = {"reason": "a Forge run is going"}
        ka.add_provider(lambda: busy["reason"])
        ka.add_provider(lambda: None)
        clock.now += 3600
        self.assertTrue(ka.tick())
        self.assertEqual(ka.status()["reasons"], ["a Forge run is going"])
        busy["reason"] = None
        self.assertFalse(ka.tick())
        self.assertFalse(power.held)
        self.assertEqual(ka.status()["reasons"], [])

    def test_provider_exceptions_are_ignored_and_logged_once(self):
        said = []
        ka, clock, power = controller(idle_minutes=1, log=said.append)

        def broken():
            raise RuntimeError("no")
        ka.add_provider(broken)
        ka.add_provider(lambda: "practice hands are playing")
        clock.now += 3600
        for _ in range(3):
            self.assertTrue(ka.tick())
            clock.now += 15
        self.assertEqual(ka.status()["reasons"], ["practice hands are playing"])
        self.assertEqual(sum("busy check failed" in s for s in said), 1)

    def test_resume_calls_callbacks_and_counts_as_use(self):
        said = []
        ka, clock, power = controller(idle_minutes=1, log=said.append)
        woke = []
        ka.on_resume(lambda: woke.append(True))
        ka.on_resume(lambda: (_ for _ in ()).throw(OSError("tunnel")))     # a failing one doesn't stop it
        ka.tick()
        clock.now += 3600
        ka.wall.now += 15 + 30          # a slow tick: not a sleep
        self.assertFalse(ka.tick())
        self.assertEqual(woke, [])
        clock.now += 2 * 3600           # asleep for two hours
        ka.wall.now += 2 * 3600
        self.assertTrue(ka.tick())      # being woken is a visit on its way: held
        self.assertEqual(woke, [True])
        self.assertTrue(any("asleep" in s for s in said))

    def test_wall_clock_going_backwards_is_not_a_sleep(self):
        ka, clock, power = controller(idle_minutes=1)
        woke = []
        ka.on_resume(lambda: woke.append(True))
        ka.tick()
        clock.now += 3600
        ka.wall.now -= 3 * 3600         # a time sync moved the clock back
        self.assertFalse(ka.tick())
        ka.wall.now += 15
        self.assertFalse(ka.tick())     # and the next check measures from the new time
        self.assertEqual(woke, [])

    def test_sleep_counter_notices_sleeps_whatever_the_wall_clock_does(self):
        said = []
        asleep = FakeClock(5.0)         # seconds asleep since the PC started
        ka, clock, power = controller(idle_minutes=1, log=said.append, slept=asleep)
        woke = []
        ka.on_resume(lambda: woke.append(True))
        ka.tick()
        clock.now += 3600
        ka.wall.now += 5 * 3600         # the wall clock jumped forward: no sleep by the counter
        asleep.now += 0.02              # the two counters' granularity
        self.assertFalse(ka.tick())
        asleep.now += 60                # exactly RESUME_GAP: not yet a sleep
        self.assertFalse(ka.tick())
        asleep.now -= 1                 # backwards: ignored
        self.assertFalse(ka.tick())
        self.assertEqual(woke, [])
        asleep.now += 2 * 3600          # asleep for two hours, the wall clock unmoved
        self.assertTrue(ka.tick())
        self.assertEqual(woke, [True])
        self.assertTrue(any("about 120 minutes" in s for s in said))

    def test_a_failing_sleep_counter_is_logged_once_and_ignored(self):
        said = []

        def broken():
            raise OSError("no counter")
        ka, clock, power = controller(idle_minutes=1, log=said.append, slept=broken)
        for _ in range(3):
            self.assertTrue(ka.tick())
        self.assertEqual(sum("sleep counter failed" in s for s in said), 1)

    def test_sleep_counter_by_platform(self):
        with mock.patch.object(keepawake.sys, "platform", "linux"):
            self.assertIsNone(keepawake.sleep_counter())
        with mock.patch.object(keepawake.sys, "platform", "win32"),                 mock.patch.object(keepawake, "_windows_sleep_counter", side_effect=OSError("missing")):
            self.assertIsNone(keepawake.sleep_counter())
        fake = object()
        with mock.patch.object(keepawake, "sleep_counter", return_value=fake):
            self.assertIs(keepawake.KeepAwake(power=FakePower()).slept, fake)
        self.assertIsNone(keepawake.KeepAwake(power=FakePower(), slept=None).slept)

    @unittest.skipUnless(keepawake.sys.platform == "win32", "Windows' counters only")
    def test_windows_sleep_counter_reads(self):
        counter = keepawake._windows_sleep_counter()
        first = counter()
        self.assertGreaterEqual(first, -1.0)
        self.assertLess(abs(counter() - first), 1.0)     # awake: barely moves

    def test_module_note_activity_reaches_installed(self):
        ka, clock, power = controller(idle_minutes=1)
        clock.now += 3600
        self.assertFalse(ka.tick())
        keepawake.install(ka)
        try:
            keepawake.note_activity()
        finally:
            keepawake.install(None)
        self.assertTrue(ka.tick())
        keepawake.note_activity()       # nothing installed: no error

    def test_thread_releases_on_stop(self):
        ka, clock, power = controller()
        ka.interval = 0.01
        ka.start()
        try:
            for _ in range(200):
                if power.held:
                    break
                threading.Event().wait(0.01)
            self.assertTrue(power.held)
        finally:
            ka.stop()
        self.assertFalse(power.held)

    def test_hold_while(self):
        power = FakePower()
        with keepawake.hold_while(power):
            self.assertTrue(power.held)
        self.assertFalse(power.held)
        with self.assertRaises(ValueError):
            with keepawake.hold_while(power):
                raise ValueError
        self.assertEqual(power.calls, ["hold", "release", "hold", "release"])

    def test_wake_settings(self):
        self.assertIsNone(keepawake.wake_settings({}))
        self.assertIsNone(keepawake.wake_settings({"wake": "yes"}))
        self.assertEqual(keepawake.wake_settings({"wake": {}}), {"idle_minutes": 20, "gate": None})
        self.assertEqual(keepawake.wake_settings({"wake": {"idle_minutes": 5, "gate": "http://192.0.2.5:8650/"}}),
                         {"idle_minutes": 5, "gate": "http://192.0.2.5:8650"})
        for bad in (0, 1441, "10", True, 2.5):
            self.assertEqual(keepawake.wake_settings({"wake": {"idle_minutes": bad}})["idle_minutes"], 20)
        self.assertEqual(keepawake.idle_minutes_of({}), 20)
        self.assertEqual(keepawake.idle_minutes_of({"wake": {"idle_minutes": 45}}), 45)

    def test_platform_power_elsewhere_is_a_no_op(self):
        with mock.patch.object(keepawake.sys, "platform", "linux"):
            power = keepawake.platform_power()
        power.hold()
        power.release()
        self.assertFalse(power.held)


class ForgeCommandLineTests(unittest.TestCase):
    """python -m decklab.lib.forge holds the PC awake for a command that may play games."""

    def run_cli(self, command):
        from decklab.lib.forge import cli
        held = []

        @contextlib.contextmanager
        def hold_while(power=None):
            held.append("hold")
            yield None
            held.append("release")
        seen = []

        def run(args):
            seen.append(list(held))
            return 0
        with mock.patch.dict(cli.COMMANDS, {command: (lambda sub: sub.add_parser(command), run)}),                 mock.patch.object(keepawake, "hold_while", hold_while):
            self.assertEqual(cli.main([command]), 0)
        return seen, held

    def test_a_game_command_holds_while_it_runs(self):
        seen, held = self.run_cli("play")
        self.assertEqual(seen, [["hold"]])
        self.assertEqual(held, ["hold", "release"])

    def test_a_quick_command_doesnt(self):
        self.assertEqual(self.run_cli("status"), ([[]], []))


class ServerNotesActivityTests(unittest.TestCase):
    """server_http notes real requests only (the predicate above decides which)."""

    def test_requests(self):
        with tempfile.TemporaryDirectory() as web, mock.patch.object(server_http, "log", lambda text: None):
            httpd = server_http.make_server("127.0.0.1", 0, web_dir=web)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            noted = []
            fake = mock.Mock(note_activity=lambda: noted.append(True))
            keepawake.install(fake)
            try:
                def send(method, path, headers=None):
                    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
                    try:
                        conn.request(method, path, headers=headers or {})
                        conn.getresponse().read()
                    finally:
                        conn.close()
                    return len(noted)
                self.assertEqual(send("HEAD", "/"), 0)
                self.assertEqual(send("GET", "/api/no-such-route", {"X-Deck-Lab-Poll": "1"}), 0)
                self.assertEqual(send("GET", "/core.js"), 0)
                self.assertEqual(send("GET", "/api/no-such-route"), 1)
                self.assertEqual(send("GET", "/"), 2)
            finally:
                keepawake.install(None)
                httpd.shutdown()
                httpd.server_close()
                thread.join(5)


class TunnelRestartTests(unittest.TestCase):

    def test_restart_now_kills_cloudflared_and_skips_the_wait(self):
        said = []
        t = tunnel.Tunnel("cloudflared", "config.yml", said.append)
        proc = mock.Mock()
        proc.poll.return_value = None
        t.proc = proc
        with mock.patch("decklab.lib.forge.processes.kill_process") as kill:
            t.restart_now()
        kill.assert_called_once_with(proc)
        self.assertTrue(t._kick.is_set())       # the loop's wait returns at once
        t._stopping.set()
        t.restart_now()                          # stopping: nothing more
        self.assertEqual(kill.call_count, 1)


POWERCFG_S3 = """The following sleep states are available on this system:
    Standby (S3)
    Hibernate
    Hybrid Sleep
    Fast Startup

The following sleep states are not available on this system:
    Standby (S1)
        The system firmware does not support this standby state.
    Standby (S0 Low Power Idle)
        The system firmware does not support this standby state.
"""

POWERCFG_MODERN = """The following sleep states are available on this system:
    Standby (S0 Low Power Idle) Network Connected
    Hibernate

The following sleep states are not available on this system:
    Standby (S3)
        This standby state is disabled when S0 low power idle is supported.
"""

SLEEP_30 = "Current AC Power Setting Index: 0x00000708\nCurrent DC Power Setting Index: 0x00000384"
SLEEP_NEVER = "Current AC Power Setting Index: 0x00000000\nCurrent DC Power Setting Index: 0x00000000"
TIMERS_ON = """    Power Setting GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (Allow wake timers)
      GUID Alias: RTCWAKE
      Possible Setting Index: 000
      Possible Setting Friendly Name: Disable
      Possible Setting Index: 001
      Possible Setting Friendly Name: Enable
    Current AC Power Setting Index: 0x00000001
    Current DC Power Setting Index: 0x00000000"""
TIMERS_OFF = TIMERS_ON.replace("AC Power Setting Index: 0x00000001", "AC Power Setting Index: 0x00000000")


class HomenetWakeTests(unittest.TestCase):

    def test_sleep_line_with_wake(self):
        [ok] = checks.check_sleep(SLEEP_30, wake=True)
        self.assertEqual(ok["level"], OK)
        self.assertIn("sleeps after 30 minutes idle", ok["text"])
        self.assertIn("wake-on-request", ok["text"])
        [never] = checks.check_sleep(SLEEP_NEVER, wake=True)
        self.assertEqual(never["level"], WARN)
        self.assertIn("never sleeps, so it saves nothing", never["text"])

    def test_sleep_line_without_wake_unchanged(self):
        self.assertEqual(checks.check_sleep(SLEEP_30)[0]["level"], WARN)
        self.assertEqual(checks.check_sleep(SLEEP_NEVER)[0]["level"], OK)

    def test_wake_all_good(self):
        facts = {"errors": [], "sleep_states": POWERCFG_S3, "wake_armed": "Intel(R) Ethernet Connection I219-V\n",
                 "wake_timers": TIMERS_ON}
        lines = checks.check_wake(facts, "http://192.0.2.5:8650", {"answered": True, "awake": True})
        self.assertEqual([x["level"] for x in lines], [OK, OK, OK, OK])
        self.assertIn("I219-V", lines[1]["text"])
        self.assertIn("nightly backup can wake", lines[2]["text"])

    def test_wake_problems(self):
        facts = {"errors": [], "sleep_states": POWERCFG_MODERN, "wake_armed": "NONE\n", "wake_timers": TIMERS_OFF}
        lines = checks.check_wake(facts, "http://192.0.2.5:8650", {"answered": False, "error": "timed out"})
        self.assertEqual([x["level"] for x in lines], [WARN, WARN, WARN, WARN])
        self.assertIn("Modern Standby", lines[0]["text"])
        self.assertIn("Only allow a magic packet", lines[1]["fix"])
        self.assertIn("can't wake the PC", lines[2]["text"])
        self.assertIn("powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1", lines[2]["fix"])
        self.assertIn("timed out", lines[3]["text"])

    def test_wake_timers_important_only_warns(self):
        facts = {"errors": [], "sleep_states": POWERCFG_S3, "wake_armed": "Realtek PCIe GbE Family Controller",
                 "wake_timers": TIMERS_ON.replace("AC Power Setting Index: 0x00000001",
                                                   "AC Power Setting Index: 0x00000002")}
        lines = checks.check_wake(facts)
        self.assertEqual(lines[2]["level"], WARN)
        self.assertIn("important wake timers only", lines[2]["text"])

    def test_only_non_network_devices_armed(self):
        facts = {"errors": [], "sleep_states": POWERCFG_S3, "wake_timers": TIMERS_ON,
                 "wake_armed": "HID Keyboard Device (001)\r\nHID-compliant mouse\r\nUSB4 Root Router (1.0)\r\n",
                 "net_adapters": ["Some Adapter", "Hyper-V Virtual Ethernet Adapter"]}
        armed = checks.check_wake(facts)[1]
        self.assertEqual(armed["level"], WARN)
        self.assertIn("No network adapter may wake the PC (armed: HID Keyboard Device (001), HID-compliant mouse, "
                      "USB4 Root Router (1.0))", armed["text"])
        self.assertIn("Device Manager", armed["fix"])

    def test_network_adapter_matched_by_description_or_name(self):
        facts = {"errors": [], "sleep_states": POWERCFG_S3, "wake_timers": TIMERS_ON,
                 "wake_armed": "HID Keyboard Device\r\nAcme PCIe 2.5G Controller\r\n",
                 "net_adapters": "Acme PCIe 2.5G Controller"}         # one adapter: PowerShell gives a string
        armed = checks.check_wake(facts)[1]
        self.assertEqual(armed["level"], OK)
        self.assertEqual(armed["text"], "May wake the PC: Acme PCIe 2.5G Controller (also armed: HID Keyboard Device).")
        facts["net_adapters"] = None                    # unreadable: the name alone decides
        self.assertEqual(checks.check_wake(facts)[1]["level"], WARN)
        for name in ("Realtek 8922AE WiFi 7 PCI-E NIC", "Killer E2600 Gigabit", "Intel(R) Wi-Fi 6 AX201",
                     "Qualcomm Atheros 802.11ac", "Broadcom NetXtreme LAN"):
            self.assertEqual(checks.wake_network_adapters([name]), [name], name)
        for name in ("HID-compliant mouse", "Planar touch screen", "Electronic pen"):
            self.assertEqual(checks.wake_network_adapters([name]), [], name)

    def test_wake_unreadable_and_no_gate(self):
        facts = {"errors": ["sleep_states: no powercfg", "wake_timers: no powercfg"], "sleep_states": None,
                 "wake_armed": None, "wake_timers": None}
        lines = checks.check_wake(facts)
        self.assertEqual([x["level"] for x in lines], [WARN, WARN, WARN])
        self.assertIn("no powercfg", lines[0]["text"])
        self.assertIn("no powercfg", lines[2]["text"])

    def test_parsers(self):
        self.assertEqual(checks.sleep_states_available(POWERCFG_S3)[0], "Standby (S3)")
        self.assertNotIn("Standby (S3)", checks.sleep_states_available(POWERCFG_MODERN))
        self.assertEqual(checks.wake_armed_devices("NONE\r\n"), [])
        self.assertEqual(checks.wake_armed_devices("A\r\n\r\nB\r\n"), ["A", "B"])


class ScheduleWakeTests(unittest.TestCase):

    def task(self, wake):
        return schedule.parse_task_xml(schedule.task_xml(r"C:\Python\pythonw.exe", r"C:\repo", "u",
                                                         start=date(2026, 11, 1), wake=wake))

    def test_wake_to_run(self):
        self.assertFalse(self.task(False)["wake_to_run"])
        self.assertTrue(self.task(True)["wake_to_run"])
        self.assertIn("<WakeToRun>false</WakeToRun>", schedule.task_xml("p", "w", "u", start=date(2026, 11, 1)))

    def test_wake_wanted(self):
        self.assertTrue(schedule.wake_wanted({"wake": {"idle_minutes": 20}}))
        self.assertFalse(schedule.wake_wanted({}))

    def test_describe_warns_on_mismatch(self):
        def warnings(task, wake):
            return [x for x in schedule.describe(task, exists=lambda p: True, wake=wake) if "WakeToRun" in x
                    or "wake" in x.lower() and "WARNING" in x]
        self.assertEqual(warnings(self.task(True), True), [])
        self.assertEqual(warnings(self.task(False), False), [])
        self.assertEqual(len(warnings(self.task(False), True)), 1)
        self.assertEqual(len(warnings(self.task(True), False)), 1)
        self.assertEqual(warnings(self.task(True), None), [])


if __name__ == "__main__":
    unittest.main()
