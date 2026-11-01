"""Tests for decklab/wakegate/wakegate.py, the NAS's wake gate: MAC parsing, the magic packet,
the debounce, the Cloudflare restriction, the redirect target, the status answer, and the server
end to end on 127.0.0.1 with fake send and check functions (no packet is ever broadcast).

The gate is a standalone script for a container, not a package module, so it's loaded by path.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_wakegate
"""
import http.client
import importlib.util
import json
import threading
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "wakegate" / "wakegate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("decklab_wakegate_under_test", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wg = load_gate()
LOGGED = []
wg.log = LOGGED.append  # keep the test output quiet; the gate's lines are checked below
MAC = bytes.fromhex("0211223344ef")


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class FakePC:
    def __init__(self, awake=False):
        self.awake = awake
        self.checks = 0

    def __call__(self):
        self.checks += 1
        return self.awake


def make_gate(awake=False, clock=None, **settings):
    config = wg.Config(mac=MAC, pc_host="192.168.1.20", **settings)
    sent = []
    pc = FakePC(awake)
    gate = wg.Gate(config, send=sent.append, check=pc, clock=clock or Clock())
    return gate, sent, pc


class PureTests(unittest.TestCase):
    def test_parse_mac(self):
        self.assertEqual(wg.parse_mac("02:11:22:33:44:ef"), MAC)
        self.assertEqual(wg.parse_mac("02-11-22-33-44-EF"), MAC)
        self.assertEqual(wg.parse_mac(" 02:11:22:33:44:ef\n"), MAC)
        for bad in ("", None, "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "aa:bb-cc:dd:ee:ff",
                    "aabbccddeeff", "gg:bb:cc:dd:ee:ff", "a:bb:cc:dd:ee:ff"):
            with self.assertRaises(wg.ConfigError, msg=bad):
                wg.parse_mac(bad)

    def test_magic_packet(self):
        packet = wg.magic_packet(MAC)
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], MAC * 16)
        with self.assertRaises(ValueError):
            wg.magic_packet(b"\x01\x02")

    def test_is_cloudflare(self):
        self.assertFalse(wg.is_cloudflare({"Host": "nas", "Accept": "*/*"}))
        for name in ("Cf-Ray", "CF-Connecting-IP", "cf-access-jwt-assertion"):
            self.assertTrue(wg.is_cloudflare({"Host": "nas", name: "x"}), name)

    def test_route_on_the_lan(self):
        self.assertEqual(wg.route("POST", "/__wake", False), "wake")
        self.assertEqual(wg.route("GET", "/__wake", False), "not_found")
        self.assertEqual(wg.route("GET", "/__status", False), "status")
        self.assertEqual(wg.route("GET", "/__status?x=1", False), "status")
        self.assertEqual(wg.route("GET", "/", False), "page")
        self.assertEqual(wg.route("GET", "/#/deck?id=a", False), "page")
        self.assertEqual(wg.route("POST", "/api/decks", False), "not_found")
        self.assertEqual(wg.route("HEAD", "/", False), "not_found")
        self.assertEqual(wg.route("GET", "http://elsewhere.example.com/", False), "bad_request")

    def test_route_through_cloudflare_allows_only_post_wake(self):
        self.assertEqual(wg.route("POST", "/__wake", True), "wake")
        self.assertEqual(wg.route("POST", "/__wake?x=1", True), "wake")
        for method, target in (("GET", "/__status"), ("GET", "/"), ("GET", "/__wake"),
                               ("POST", "/__status"), ("GET", "/api/status"), ("HEAD", "/__wake")):
            self.assertEqual(wg.route(method, target, True), "not_found", (method, target))

    def test_pc_url_keeps_path_and_query(self):
        self.assertEqual(wg.pc_url("192.168.1.20", 8642, "/"), "http://192.168.1.20:8642/")
        self.assertEqual(wg.pc_url("192.168.1.20", 8642, "/api/x?a=1&b=two"),
                         "http://192.168.1.20:8642/api/x?a=1&b=two")
        self.assertEqual(wg.pc_url("decklab-pc", 80, "/w?"), "http://decklab-pc:80/w")
        self.assertEqual(wg.pc_url("fe80::1", 8642, "/"), "http://[fe80::1]:8642/")

    def test_pc_url_rejects_absolute_and_odd_targets(self):
        for bad in ("http://elsewhere.example.com/", "https://x/", "*", "", "elsewhere/x",
                    "/a b", "/a\r\nLocation: x", None):
            self.assertIsNone(wg.pc_url("192.168.1.20", 8642, bad), repr(bad))
        # A scheme-relative path can't make the host anyone else's.
        self.assertEqual(wg.pc_url("192.168.1.20", 8642, "//elsewhere.example.com/x"),
                         "http://192.168.1.20:8642/elsewhere.example.com/x")

    def test_config_from_env(self):
        config = wg.Config.from_env({"DECKLAB_PC_MAC": "02-11-22-33-44-ef", "DECKLAB_PC_HOST": "192.168.1.20"})
        self.assertEqual((config.mac, config.pc_host, config.pc_port, config.gate_port), (MAC, "192.168.1.20", 8642, 8650))
        self.assertEqual((config.broadcast, config.wol_port, config.min_interval, config.timeout),
                         ("255.255.255.255", 9, 30, 180))
        config = wg.Config.from_env({"DECKLAB_PC_MAC": "02:11:22:33:44:ef", "DECKLAB_PC_HOST": "pc",
                                     "DECKLAB_PC_PORT": "9000", "GATE_PORT": "9001", "WOL_BROADCAST": "192.168.1.255",
                                     "WOL_PORT": "7", "WAKE_MIN_INTERVAL": "10", "WAKE_TIMEOUT": "60"})
        self.assertEqual((config.pc_port, config.gate_port, config.broadcast, config.wol_port,
                          config.min_interval, config.timeout), (9000, 9001, "192.168.1.255", 7, 10, 60))
        good = {"DECKLAB_PC_MAC": "02:11:22:33:44:ef", "DECKLAB_PC_HOST": "pc"}
        for change in ({"DECKLAB_PC_MAC": "nope"}, {"DECKLAB_PC_HOST": ""}, {"DECKLAB_PC_HOST": "a/b"},
                       {"DECKLAB_PC_PORT": "0"}, {"GATE_PORT": "x"}, {"WOL_BROADCAST": "everyone"},
                       {"WAKE_MIN_INTERVAL": "0"}):
            with self.assertRaises(wg.ConfigError, msg=change):
                wg.Config.from_env(dict(good, **change))

    def test_main_exits_2_on_a_bad_mac(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(wg.main({"DECKLAB_PC_MAC": "bad", "DECKLAB_PC_HOST": "pc"}), 2)
        self.assertIn("DECKLAB_PC_MAC", err.getvalue())

    def test_the_example_mac_is_refused(self):
        import contextlib
        import io
        for example in ("aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF"):
            with self.assertRaises(wg.ConfigError, msg=example):
                wg.Config.from_env({"DECKLAB_PC_MAC": example, "DECKLAB_PC_HOST": "pc"})
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(wg.main({"DECKLAB_PC_MAC": example, "DECKLAB_PC_HOST": "pc"}), 2)
            self.assertIn("example", err.getvalue())
        # parse_mac alone still reads it; only the gate's settings refuse it.
        self.assertEqual(wg.parse_mac("aa:bb:cc:dd:ee:ff"), wg.PLACEHOLDER_MAC)

    def test_pc_origin_always_has_the_port(self):
        self.assertEqual(wg.pc_origin("192.168.1.20", 8642), "http://192.168.1.20:8642")
        self.assertEqual(wg.pc_origin("decklab-pc", 80), "http://decklab-pc:80")
        self.assertEqual(wg.pc_origin("fe80::1", 8642), "http://[fe80::1]:8642")

    def test_waking_page_wording_and_escaping(self):
        page = wg.waking_page("http://192.168.1.20:8642/x?a=</script><b>", 180)
        self.assertIn("Deck Lab is waking up", page)
        self.assertIn("This usually takes under a minute.", page)
        self.assertIn("Try again", page)
        self.assertIn("turned off or unplugged", page)
        self.assertIn("180 * 1000", page)
        self.assertNotIn("</script><b>", page)
        self.assertNotIn("http://", page.replace("http://192.168.1.20:8642/", ""))


class GateTests(unittest.TestCase):
    def test_debounce(self):
        clock = Clock()
        gate, sent, _ = make_gate(clock=clock, min_interval=30)
        del LOGGED[:]
        self.assertEqual(gate.wake(), (True, 30))
        self.assertEqual(sent, [wg.magic_packet(MAC)])
        self.assertEqual(LOGGED, ["wake packet sent to 255.255.255.255:9"])
        clock.now += 10
        self.assertEqual(gate.wake(), (False, 20))
        clock.now += 19.5
        self.assertEqual(gate.wake(), (False, 1))
        clock.now += 0.5
        self.assertEqual(gate.wake(), (True, 30))
        self.assertEqual(len(sent), 2)

    def test_send_failure_is_logged_and_debounced(self):
        clock = Clock()
        config = wg.Config(mac=MAC, pc_host="pc")

        def broken(packet):
            raise OSError("network unreachable")
        gate = wg.Gate(config, send=broken, check=FakePC(), clock=clock)
        del LOGGED[:]
        self.assertEqual(gate.wake(), (False, 30))
        self.assertEqual(gate.wake()[0], False)
        self.assertEqual(LOGGED, ["sending the wake packet failed: network unreachable"])

    def test_status_tracks_the_wake_attempt(self):
        clock = Clock()
        gate, _, pc = make_gate(clock=clock, timeout=180)
        self.assertEqual(gate.status(), {"awake": False, "waking": False, "since": None})
        gate.wake()
        clock.now += 12
        self.assertEqual(gate.status(), {"awake": False, "waking": True, "since": 12})
        clock.now += 40
        gate.wake()  # a later packet in the same attempt keeps its start
        self.assertEqual(gate.status()["since"], 52)
        clock.now += 200
        self.assertEqual(gate.status(), {"awake": False, "waking": False, "since": 252})
        gate.wake()  # after the timeout a new attempt begins
        self.assertEqual(gate.status()["since"], 0)
        pc.awake = True
        clock.now += 2
        self.assertEqual(gate.status(), {"awake": True, "waking": False, "since": None})
        pc.awake = False
        clock.now += 2
        self.assertEqual(gate.status(), {"awake": False, "waking": False, "since": None})

    def test_awake_is_cached_for_a_second(self):
        clock = Clock()
        gate, _, pc = make_gate(clock=clock)
        gate.awake()
        gate.awake()
        self.assertEqual(pc.checks, 1)
        clock.now += 1
        gate.awake()
        self.assertEqual(pc.checks, 2)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.gate, self.sent, self.pc = make_gate(min_interval=30)
        self.server = wg.make_server(self.gate, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def request(self, method, target, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, target, headers=headers or {})
            answer = connection.getresponse()
            return answer.status, dict(answer.getheaders()), answer.read()
        finally:
            connection.close()

    def test_status_and_wake(self):
        status, headers, body = self.request("GET", "/__status")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(json.loads(body), {"awake": False, "waking": False, "since": None,
                                            "pc": "http://192.168.1.20:8642"})
        status, _, body = self.request("POST", "/__wake")
        self.assertEqual((status, json.loads(body)), (202, {"sent": True, "retry_after": 30}))
        status, headers, body = self.request("POST", "/__wake")
        self.assertEqual(status, 202)
        self.assertFalse(json.loads(body)["sent"])
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(json.loads(self.request("GET", "/__status")[2])["waking"])

    def test_status_is_readable_only_from_the_pcs_origin(self):
        for origin in (None, "http://192.168.1.20:8642", "http://evil.example.com"):
            headers = {"Origin": origin} if origin else {}
            status, answer, body = self.request("GET", "/__status", headers)
            self.assertEqual(status, 200, origin)
            # Always the PC's own origin, never the request's echoed back.
            self.assertEqual(answer["Access-Control-Allow-Origin"], "http://192.168.1.20:8642", origin)
            self.assertEqual(answer["Vary"], "Origin")
            self.assertNotIn("Access-Control-Allow-Credentials", answer)
            self.assertEqual(json.loads(body)["pc"], "http://192.168.1.20:8642")
        self.assertEqual(self.sent, [])

    def test_other_answers_carry_no_cors_header(self):
        for method, target in (("POST", "/__wake"), ("GET", "/x"), ("GET", "/__wake")):
            _, answer, _ = self.request(method, target, {"Origin": "http://192.168.1.20:8642"})
            self.assertNotIn("Access-Control-Allow-Origin", answer, (method, target))
        self.pc.awake = True
        _, answer, _ = self.request("GET", "/x", {"Origin": "http://192.168.1.20:8642"})
        self.assertNotIn("Access-Control-Allow-Origin", answer)

    def test_a_preflight_is_harmless(self):
        status, answer, _ = self.request("OPTIONS", "/__status", {
            "Origin": "http://192.168.1.20:8642", "Access-Control-Request-Method": "GET"})
        self.assertEqual(status, 404)
        self.assertNotIn("Access-Control-Allow-Origin", answer)
        self.assertEqual(self.sent, [])
        # The gate still answers normally afterwards.
        self.assertEqual(self.request("GET", "/__status")[0], 200)

    def test_asleep_page_sends_and_serves_the_waking_page(self):
        status, headers, body = self.request("GET", "/deck?id=a&b=1", {"Host": "evil.example.com"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        page = body.decode("utf-8")
        self.assertIn("Deck Lab is waking up", page)
        self.assertIn('"http://192.168.1.20:8642/deck?id=a\\u0026b=1"', page)
        self.assertNotIn("evil.example.com", page)
        self.assertEqual(len(self.sent), 1)

    def test_awake_page_redirects_to_the_pc(self):
        self.pc.awake = True
        status, headers, _ = self.request("GET", "/x/y?z=1", {"Host": "evil.example.com"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "http://192.168.1.20:8642/x/y?z=1")
        self.assertEqual(self.sent, [])

    def test_absolute_target_is_refused(self):
        self.pc.awake = True
        status, headers, _ = self.request("GET", "http://elsewhere.example.com/")
        self.assertEqual(status, 400)
        self.assertNotIn("Location", headers)

    def test_cloudflare_may_only_post_wake(self):
        cf = {"Cf-Ray": "abc123"}
        for method, target in (("GET", "/__status"), ("GET", "/"), ("GET", "/deck"),
                               ("OPTIONS", "/__status")):
            status, answer, body = self.request(method, target, dict(cf, Origin="http://192.168.1.20:8642"))
            self.assertEqual(status, 404, target)
            self.assertNotIn("Access-Control-Allow-Origin", answer, target)
            self.assertNotIn(b"192.168.1.20", body, target)
        self.assertEqual(self.sent, [])
        status, _, body = self.request("POST", "/__wake", {"Cf-Access-Jwt-Assertion": "x"})
        self.assertEqual((status, json.loads(body)["sent"]), (202, True))
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
