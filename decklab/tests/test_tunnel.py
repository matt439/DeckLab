"""Tests for decklab/lib/tunnel.py and status's Tunnel lines: the settings,
when the server starts the tunnel, where cloudflared's config sends it, and
how the public address's and the tunnel listener's answers are judged.
Nothing here starts cloudflared or reaches the internet.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import tunnel
from decklab.lib.homenet import OK, PROBLEM, WARN
from decklab.lib.homenet.commands import check_tunnel
from decklab.tests.test_control import free_port

ACCESS = {"team": "your-team", "aud": "ab" * 32, "port": 8644}
SETTINGS = {"tunnel": {"config": "~/.cloudflared/config.yml", "hostname": "DeckLab.Example.com"}, "access": ACCESS}
GOOD_YML = """tunnel: x
credentials-file: C:\\x.json
originRequest:
  access:
    required: true
    teamName: your-team
ingress:
  - hostname: decklab.example.com
    service: http://127.0.0.1:8644
  - hostname: www.decklab.example.com   # the www name
    service: "http://localhost:8644/"
    originRequest:
      service: http://localhost:8642
  - service: http_status:404
"""
OLD_YML = GOOD_YML.replace("127.0.0.1:8644", "localhost:8642").replace("localhost:8644/", "localhost:8642")


class SettingsTests(unittest.TestCase):
    def test_none_without_a_tunnel(self):
        for settings in ({}, None, {"tunnel": None}, {"tunnel": "x"}, {"tunnel": {"hostname": "a.com"}}):
            self.assertIsNone(tunnel.settings_of(settings))

    def test_expands_home_and_lowers_hostname(self):
        setup = tunnel.settings_of(SETTINGS)
        self.assertEqual(setup["config"], Path(os.path.expanduser("~/.cloudflared/config.yml")))
        self.assertEqual(setup["hostname"], "decklab.example.com")

    def test_public_address_for_printed_links(self):
        self.assertEqual(tunnel.public_address(SETTINGS), "https://decklab.example.com")      # E8-S21's QR code
        for settings in ({}, {"tunnel": {"config": "x"}}, {"tunnel": {"config": "x", "hostname": "a b/c"}}):
            self.assertIsNone(tunnel.public_address(settings))


class StartTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config_file = Path(folder.name) / "config.yml"
        self.config_file.write_text(GOOD_YML)
        self.program = Path(folder.name) / "cloudflared.exe"
        self.program.write_text("")
        self.settings = {"tunnel": {"config": str(self.config_file), "hostname": "decklab.example.com"},
                         "allowed_hosts": ["decklab.example.com", "www.decklab.example.com"],
                         "cloudflared": str(self.program), "access": ACCESS}
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("DECKLAB_STATE_FILE", None)
        self.logged = []
        started = mock.patch.object(tunnel.Tunnel, "start", lambda t: t)
        started.start()
        self.addCleanup(started.stop)

    def start(self, settings=None, port=8642, listener_port=8644):
        return tunnel.start(self.settings if settings is None else settings, port, 8642, self.logged.append,
                            listener_port)

    def test_starts_on_the_configured_port(self):
        t = self.start()
        self.assertIsInstance(t, tunnel.Tunnel)
        self.assertEqual(t.program, self.program)
        self.assertIn("https://decklab.example.com/", self.logged[0])

    def test_not_for_another_port_or_a_test_server(self):
        self.assertIsNone(self.start(port=8643))
        os.environ["DECKLAB_STATE_FILE"] = "x"
        self.assertIsNone(self.start())
        self.assertEqual(self.logged, [])
        self.assertFalse(tunnel.usual_server(8642, 8642))

    def test_not_without_settings(self):
        self.assertIsNone(self.start({}))

    def test_missing_config_or_program_is_logged(self):
        self.assertIsNone(self.start({**self.settings, "tunnel": {"config": str(self.config_file) + ".no"}}))
        self.assertIn("isn't there", self.logged[-1])
        self.assertIsNone(self.start({**self.settings, "cloudflared": str(self.program) + ".no"}))
        self.assertIn("isn't installed", self.logged[-1])

    def test_not_without_the_tunnels_listener(self):
        self.assertIsNone(self.start(listener_port=None))
        self.assertIn("NOT STARTED", self.logged[-1])
        self.assertIn("no listener for the tunnel", self.logged[-1])

    def test_not_when_cloudflared_still_sends_it_to_the_home_port(self):
        self.config_file.write_text(OLD_YML)
        self.assertIsNone(self.start())
        self.assertIn("NOT STARTED", self.logged[-1])
        self.assertIn("www.decklab.example.com goes to http://localhost:8642", self.logged[-1])
        self.assertIn("make it http://127.0.0.1:8644", self.logged[-1])


class IngressTests(unittest.TestCase):
    def problems(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yml"
            path.write_text(text)
            settings = {"tunnel": {"config": str(path), "hostname": "decklab.example.com"},
                        "allowed_hosts": ["www.decklab.example.com"], "access": ACCESS}
            return tunnel.ingress_problems(settings, 8642)

    def test_rules_are_read(self):
        self.assertEqual(tunnel.ingress_rules(GOOD_YML), [
            {"hostname": "decklab.example.com", "service": "http://127.0.0.1:8644"},
            {"hostname": "www.decklab.example.com", "service": "http://localhost:8644/"},
            {"service": "http_status:404"}])

    def test_good_config(self):
        self.assertEqual(self.problems(GOOD_YML), [])

    def test_home_port_is_a_problem(self):
        self.assertEqual(len(self.problems(OLD_YML)), 2)
        catch_all = GOOD_YML.replace("http_status:404", "http://localhost:8642")
        self.assertIn("the catch-all rule", self.problems(catch_all)[0])

    def test_home_port_at_any_address_of_this_pc_is_a_problem(self):
        pc = ({"deckpc", "deckpc.home.lan"}, {tunnel._address("192.168.0.20"), tunnel._address("fe80::1"),
                                               tunnel._address("2001:db8::20")})
        resolved = {"decks.lan": {tunnel._address("192.168.0.20")}, "other.lan": {tunnel._address("192.168.0.99")}}
        with mock.patch.object(tunnel, "this_pc", lambda: pc), \
                mock.patch.object(tunnel, "_resolve", lambda host: resolved.get(host, set())):
            for service in ("http://DeckPC:8642", "http://deckpc.home.lan:8642/", "http://192.168.0.20:8642",
                            "http://[2001:db8::20]:8642", "http://[fe80::1%25eth0]:8642", "http://127.8.9.1:8642",
                            "http://0.0.0.0:8642", "http://[::]:8642", "http://[::ffff:127.0.0.1]:8642",
                            "http://decks.lan:8642", "http://app.localhost:8642"):
                with self.subTest(service=service):
                    problems = self.problems(GOOD_YML.replace("http_status:404", service))
                    self.assertTrue(problems and "home listener" in problems[0], problems)
            for service in ("http://other.lan:8642", "http://192.168.0.99:8642", "http://deckpc:8643",
                            "https://deckpc", "http_status:404", "unix:/tmp/x"):
                with self.subTest(service=service):
                    self.assertEqual(self.problems(GOOD_YML.replace("http_status:404", service)), [])

    def test_this_pc_and_on_this_pc(self):
        names, addresses = tunnel.this_pc()
        self.assertTrue(names)
        self.assertTrue(tunnel._on_this_pc("localhost", (names, addresses)))
        self.assertTrue(tunnel._on_this_pc(next(iter(names)), (names, addresses)))
        self.assertTrue(tunnel._on_this_pc("::1", (set(), set())))
        self.assertFalse(tunnel._on_this_pc("192.0.2.1", (set(), set())))       # a documentation address
        self.assertEqual(tunnel._service_target("https://MyPC."), ("mypc", 443))
        self.assertIsNone(tunnel._service_target("http://[bad"))

    def test_other_port_or_a_missing_host(self):
        other = self.problems(GOOD_YML.replace("127.0.0.1:8644", "127.0.0.1:9"))
        self.assertIn("not http://127.0.0.1:8644", other[0])
        only_one = ("ingress:\n  - hostname: decklab.example.com\n    service: http://127.0.0.1:8644\n"
                    "  - service: http_status:404\n")
        self.assertIn("no rule sends www.decklab.example.com", self.problems(only_one)[0])

    def test_nothing_to_check_without_access_or_a_tunnel(self):
        self.assertIsNone(tunnel.ingress_problems({"tunnel": {"config": "x"}}))
        self.assertIsNone(tunnel.ingress_problems({"access": ACCESS}))

    def test_an_unreadable_config(self):
        settings = {"tunnel": {"config": "Z:/no/such/folder/config.yml"}, "access": ACCESS}
        self.assertIn("can't be read", tunnel.ingress_problems(settings)[0])


class ListenerCheckTests(unittest.TestCase):
    def test_nothing_listening(self):
        self.assertEqual(tunnel.check_listener(free_port(), "decklab.example.com", 2)[0], "closed")


class Response:
    def __init__(self, status, location=None, body=b""):
        self.status, self.location, self.body = status, location, body

    def getheader(self, name):
        return self.location if name == "Location" else None

    def read(self, size):
        return self.body[:size]


class CheckPublicTests(unittest.TestCase):
    def answer(self, response):
        conn = mock.Mock()
        conn.getresponse.return_value = response
        with mock.patch("http.client.HTTPSConnection", return_value=conn):
            return tunnel.check_public("decklab.example.com")

    def test_access_login(self):
        kind, _ = self.answer(Response(302, "https://decklab.cloudflareaccess.com/cdn-cgi/access/login/x"))
        self.assertEqual(kind, "login")

    def test_open_with_no_login(self):
        kind, _ = self.answer(Response(200, body=b'{"cards": {"ready": true}}'))
        self.assertEqual(kind, "open")

    def test_tunnel_down(self):
        self.assertEqual(self.answer(Response(530, body=b"error code: 1033"))[0], "down")

    def test_other_redirect_is_an_error(self):
        self.assertEqual(self.answer(Response(302, "https://example.com/"))[0], "error")

    def test_unreachable(self):
        with mock.patch("http.client.HTTPSConnection", side_effect=OSError("no route")):
            self.assertEqual(tunnel.check_public("decklab.example.com")[0], "error")


class TunnelLineTests(unittest.TestCase):
    def levels(self, result, settings=SETTINGS):
        return [l["level"] for l in check_tunnel(settings, result)]

    def test_no_line_without_a_tunnel(self):
        self.assertEqual(check_tunnel({}, None), [])

    def test_levels(self):
        self.assertEqual(self.levels(("login", "x")), [OK])
        self.assertEqual(self.levels(("open", "x")), [PROBLEM])
        self.assertEqual(self.levels(("down", "x")), [WARN])
        self.assertEqual(self.levels(None), [WARN])
        self.assertEqual(self.levels(None, {"tunnel": {"config": "c"}, "access": ACCESS}), [WARN])

    def test_a_tunnel_without_access_is_a_problem(self):
        self.assertEqual(self.levels(("login", "x"), {"tunnel": SETTINGS["tunnel"]}), [OK, PROBLEM])
        self.assertEqual(self.levels(("login", "x"), {**SETTINGS, "access": {"team": "x"}}), [OK, PROBLEM])

    def test_ingress_and_listener(self):
        lines = check_tunnel(SETTINGS, ("login", "x"), ["decklab.example.com goes to http://localhost:8642"],
                             ("refuses", "The tunnel's listener (127.0.0.1:8644) refuses visits"))
        self.assertEqual([l["level"] for l in lines], [OK, PROBLEM, OK])
        self.assertIn("http://127.0.0.1:8644", lines[1]["fix"])
        self.assertEqual([l["level"] for l in check_tunnel(SETTINGS, ("login", "x"), [], ("open", "x"))],
                         [OK, OK, PROBLEM])
        self.assertEqual([l["level"] for l in check_tunnel(SETTINGS, ("login", "x"), [], ("closed", "x"))],
                         [OK, OK, WARN])


if __name__ == "__main__":
    unittest.main()
