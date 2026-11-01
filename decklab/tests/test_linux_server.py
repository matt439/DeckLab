"""The home listener's scope and Linux's script rule (lib/home_scope.py, server_http), the
PC's name as Linux gives it (host_allowed), Linux status's reads and judges (homenet's
linux_facts.py and checks.check_firewall_linux), and the stop wording each system gets.

Everything Linux-specific is read from canned files (/proc/net/tcp, /sys, /etc) or a fake
command runner, so these run on Windows and Linux alike; real servers listen on 127.0.0.1
only, on free ports.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_linux_server
"""
import http.client
import ipaddress
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from decklab import server  # noqa: F401 (runs build.start() before the server modules load)
from decklab.lib import home_scope, server_http
from decklab.lib.homenet import OK, PROBLEM, WARN, checks, commands, linux_facts


def end(ip, port, byteorder):
    """One end of a connection as /proc/net/tcp writes it: each 32-bit word of the address
    in the machine's byte order, then the port, in hex."""
    raw = ipaddress.ip_address(ip).packed
    if byteorder == "little":
        raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return f"{raw.hex().upper()}:{port:04X}"


def tcp_table(rows, byteorder):
    """/proc/net/tcp's text for rows of (local (ip, port), remote (ip, port), uid)."""
    out = ["  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"]
    for n, (local, remote, uid) in enumerate(rows):
        out.append(f"{n:4}: {end(*local, byteorder)} {end(*remote, byteorder)} 01 00000000:00000000 "
                   f"00:00000000 00000000 {uid:5}        0 {1000 + n} 1 0000000000000000 20 4 30 10 -1")
    return "\n".join(out) + "\n"


class ScopeTests(unittest.TestCase):

    def test_home_addresses_only(self):
        for client in ("127.0.0.1", "127.8.9.10", "::1", "10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.1.20",
                       "169.254.10.10", "fe80::1", "fe80::1%eth0", "fd12:3456::7", "::ffff:192.168.1.20",
                       "::ffff:127.0.0.1"):
            self.assertTrue(home_scope.allowed(client), client)
        for client in ("8.8.8.8", "172.32.0.1", "100.64.1.2", "203.0.113.9", "2001:db8::1", "2606:4700::1111",
                       "::ffff:8.8.8.8", "not an address", "", None):
            self.assertFalse(home_scope.allowed(client), client)

    def test_home_networks_adds_more(self):
        logged = []
        nets = home_scope.networks({"home_networks": ["100.64.0.0/10", "2001:db8::/32", "nonsense", "10.0.0.1/8"]},
                                   logged.append)
        self.assertTrue(home_scope.allowed("100.100.1.1", nets))
        self.assertTrue(home_scope.allowed("2001:db8::5", nets))
        self.assertTrue(home_scope.allowed("192.168.0.4", nets))        # the built-in ones stay
        self.assertFalse(home_scope.allowed("8.8.8.8", nets))
        self.assertEqual(len(logged), 1)
        self.assertIn("'nonsense'", logged[0])
        self.assertEqual(home_scope.networks({}), home_scope.BUILT_IN)
        logged.clear()
        self.assertEqual(home_scope.networks({"home_networks": "10.0.0.0/8"}, logged.append), home_scope.BUILT_IN)
        self.assertIn("isn't a list", logged[0])

    def test_each_refused_address_is_logged_once(self):
        refusals = home_scope.Refusals()
        self.assertTrue(refusals.first("8.8.8.8"))
        self.assertFalse(refusals.first("8.8.8.8"))
        self.assertTrue(refusals.first("1.1.1.1"))


class ScopedListenerTests(unittest.TestCase):
    """Real listeners on 127.0.0.1 whose home networks leave loopback out, so this PC's own
    requests stand for a stranger's."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.logged = []
        patch = mock.patch.object(server_http, "log", self.logged.append)
        patch.start()
        self.addCleanup(patch.stop)
        self.web = Path(folder.name)

    def serve(self, **options):
        httpd = server_http.make_server("127.0.0.1", 0, web_dir=self.web, **options)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), thread.join(5)))
        return httpd

    def get(self, httpd, path, host="127.0.0.1"):
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        try:
            conn.request("GET", path, headers={"Host": host})
            answer = conn.getresponse()
            return answer.status, answer.getheader("Content-Type"), answer.read()
        finally:
            conn.close()

    def test_a_visit_from_outside_the_home_networks_is_refused_naming_nobody(self):
        httpd = self.serve(home_networks=(ipaddress.ip_network("192.168.0.0/16"),))
        status, kind, body = self.get(httpd, "/api/status")
        self.assertEqual((status, json.loads(body)), (403, {"error": home_scope.REFUSED}))
        status, kind, body = self.get(httpd, "/")
        self.assertEqual((status, kind), (403, "text/html; charset=utf-8"))
        self.assertIn(home_scope.REFUSED.encode(), body)
        refused = [text for text in self.logged if "Refused visits from" in text]
        self.assertEqual(len(refused), 1, self.logged)                  # once per address
        self.assertIn("127.0.0.1", refused[0])
        self.assertIn('"home_networks"', refused[0])

    def test_the_default_answers_this_pc_and_the_tunnels_listener_isnt_scoped(self):
        home = self.serve()
        self.assertEqual(self.get(home, "/api/status")[0], 200)
        remote = self.serve(access=types.SimpleNamespace(), tunnel_hosts=("decklab.example.com",), home_networks=())
        status, _, body = self.get(remote, "/api/status")
        self.assertEqual(status, 400)                       # its own check (a tunnel host name), not the scope's
        self.assertNotIn(home_scope.REFUSED, json.loads(body)["error"])


class ScriptPeerTests(unittest.TestCase):

    CLIENT, SERVER = ("127.0.0.1", 51000), ("127.0.0.1", 8642)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.proc = Path(folder.name)
        (self.proc / "net").mkdir()

    def table(self, rows, name="tcp", byteorder=sys.byteorder):
        (self.proc / "net" / name).write_text(tcp_table(rows, byteorder), encoding="ascii")

    def test_the_clients_socket_and_its_owner(self):
        for byteorder in ("little", "big"):
            with self.subTest(byteorder=byteorder):
                self.table([(self.SERVER, ("0.0.0.0", 0), 1000),            # the listening socket
                            (self.SERVER, self.CLIENT, 1000),               # the server's end
                            (self.CLIENT, self.SERVER, 1001),               # the client's: another user's
                            (("127.0.0.1", 51001), self.SERVER, 1000)], byteorder=byteorder)
                self.assertEqual(home_scope.peer_uid(self.CLIENT, self.SERVER, self.proc, byteorder), 1001)
                self.assertEqual(home_scope.peer_uid(("127.0.0.1", 51001), self.SERVER, self.proc, byteorder), 1000)
                self.assertIsNone(home_scope.peer_uid(("127.0.0.1", 51002), self.SERVER, self.proc, byteorder))

    def test_ipv6_and_mapped_addresses(self):
        self.table([], "tcp")
        self.table([(("::1", 51000), ("::1", 8642), 1000),
                    (("::ffff:127.0.0.1", 51003), ("::ffff:127.0.0.1", 8642), 1002)], "tcp6", "little")
        self.assertEqual(home_scope.peer_uid(("::1", 51000), ("::1", 8642), self.proc, "little"), 1000)
        # A dual-stack listener sees an IPv4 client as ::ffff:127.0.0.1.
        self.assertEqual(home_scope.peer_uid(("127.0.0.1", 51003), ("::ffff:127.0.0.1", 8642), self.proc,
                                             "little"), 1002)

    def test_same_user_only_on_linux(self):
        self.table([(self.CLIENT, self.SERVER, 1001)], byteorder="little")
        with mock.patch.object(home_scope.sys, "platform", "linux"):
            self.assertTrue(home_scope.same_user(self.CLIENT, self.SERVER, self.proc, "little", uid=1001))
            self.assertFalse(home_scope.same_user(self.CLIENT, self.SERVER, self.proc, "little", uid=1000))
            self.assertFalse(home_scope.same_user(("127.0.0.1", 1), self.SERVER, self.proc, "little", uid=1001))
            self.assertFalse(home_scope.same_user(self.CLIENT, self.SERVER, self.proc / "none", "little", uid=1001))
        with mock.patch.object(home_scope.sys, "platform", "win32"):
            self.assertTrue(home_scope.same_user(self.CLIENT, self.SERVER, self.proc / "none", "little", uid=1))

    def test_script_peer_ok_on_linux_needs_this_users_socket(self):
        self.table([(self.CLIENT, self.SERVER, 1001)])
        handler = types.SimpleNamespace(client_address=self.CLIENT,
                                        connection=types.SimpleNamespace(getsockname=lambda: self.SERVER))
        logged = []
        with mock.patch.object(home_scope, "PROC", self.proc), mock.patch.object(server_http, "log", logged.append), \
                mock.patch.object(server_http.sys, "platform", "linux"), \
                mock.patch.object(server_http, "_OTHER_USERS", set()):
            with mock.patch.object(server_http.os, "getuid", create=True, return_value=1001):
                self.assertTrue(server_http.script_peer_ok(handler))
            with mock.patch.object(server_http.os, "getuid", create=True, return_value=1000):
                self.assertFalse(server_http.script_peer_ok(handler))
                self.assertFalse(server_http.script_peer_ok(handler))
                self.assertFalse(server_http.script_peer_ok(types.SimpleNamespace(client_address=self.CLIENT)))
        self.assertEqual(len(logged), 1, logged)               # uid 1001, once
        self.assertIn("another user's connection (uid 1001)", logged[0])
        with mock.patch.object(server_http.sys, "platform", "win32"):
            self.assertTrue(server_http.script_peer_ok(types.SimpleNamespace()))

    @unittest.skipUnless(sys.platform.startswith("linux") and Path("/proc/net/tcp").exists(), "Linux's /proc")
    def test_a_real_connection_of_this_user(self):
        import socket
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            with socket.create_connection(listener.getsockname()):
                accepted, _ = listener.accept()
                with accepted:
                    self.assertEqual(home_scope.peer_uid(accepted.getpeername(), accepted.getsockname()),
                                     os.getuid())


class HostNameTests(unittest.TestCase):

    def test_a_full_name_counts_whole_and_by_its_first_label(self):
        with mock.patch.object(server_http.socket, "gethostname", return_value="DeckLab-PC.home.arpa"):
            for host in ("decklab-pc", "decklab-pc.local", "DeckLab-PC.lan:8642", "decklab-pc.home.arpa",
                         "decklab-pc.home.arpa.local", "localhost"):
                self.assertTrue(server_http.host_allowed(host), host)
            for host in ("decklab-pc.attacker.example", "home.arpa", "arpa.local", "decklab-pcx.local"):
                self.assertFalse(server_http.host_allowed(host), host)

    def test_urls_use_the_first_label(self):
        self.assertEqual(commands.urls(8642, "192.168.1.20", "Box.home.arpa")[-1][1], "http://box.local:8642/")
        self.assertEqual(linux_facts.short_name("box.lan"), "box")
        self.assertEqual(linux_facts.short_name("HomePC"), "HomePC")


IP_ADDR = [
    {"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK", "UP", "LOWER_UP"], "operstate": "UNKNOWN",
     "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
    {"ifindex": 2, "ifname": "enp3s0", "flags": ["BROADCAST", "UP", "LOWER_UP"], "operstate": "UP",
     "addr_info": [{"family": "inet", "local": "192.168.1.20", "prefixlen": 24, "dynamic": True}]},
    {"ifindex": 5, "ifname": "docker0", "flags": ["UP"], "operstate": "DOWN",
     "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}]},
    {"ifindex": 7, "ifname": "wg0", "flags": ["POINTOPOINT", "UP", "LOWER_UP"], "operstate": "UNKNOWN",
     "addr_info": [{"family": "inet", "local": "10.8.0.2", "prefixlen": 24}]}]
IP_ROUTE = [{"dst": "default", "gateway": "192.168.1.1", "dev": "enp3s0", "protocol": "dhcp", "metric": 100},
            {"dst": "default", "dev": "wg0", "metric": 50}]


class FakeRun:
    """systemd._run for linux_facts: answers by the command's first words."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, args, timeout=None):
        self.calls.append(args)
        for words, answer in self.answers.items():
            if tuple(args[:len(words)]) == words:
                return answer
        return 127, "", f"{args[0]} isn't installed"


class LinuxFactsTests(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        net = self.root / "sys" / "class" / "net" / "enp3s0"
        (net / "device").mkdir(parents=True)
        (net / "address").write_text("00:11:22:33:44:55\n", encoding="ascii")
        self.answers = {("ip", "-j", "-4", "addr"): (0, json.dumps(IP_ADDR), ""),
                        ("ip", "-j", "-4", "route"): (0, json.dumps(IP_ROUTE), ""),
                        ("systemctl", "is-active"): (3, "inactive\ninactive\ninactive\n", "")}

    def read(self):
        run = FakeRun(self.answers)
        return linux_facts.read_facts(8642, run, self.root), run

    def test_the_network_as_pick_interface_reads_it(self):
        facts, _ = self.read()
        chosen = checks.pick_interface(facts["network"])
        # The physical adapter, though the VPN's route has the lower metric.
        self.assertEqual((chosen["alias"], chosen["address"]["address"], chosen["gateway"], chosen["mac"]),
                         ("enp3s0", "192.168.1.20", "192.168.1.1", "00:11:22:33:44:55"))
        self.assertEqual(chosen["address"]["origin"], "Dhcp")
        wg = next(i for i in facts["network"]["interfaces"] if i["alias"] == "wg0")
        self.assertEqual((wg["virtual"], wg["status"]), (True, "Up"))
        self.assertEqual(checks.check_network(facts["network"], linux=True)[0]["text"],
                         "enp3s0: 192.168.1.20/24 from the router (DHCP).")
        self.assertEqual(str(checks.lan_of(facts["network"])["subnet"]), "192.168.1.0/24")

    def test_what_couldnt_be_read_says_why(self):
        self.answers.pop(("ip", "-j", "-4", "addr"))
        self.answers.pop(("systemctl", "is-active"))
        facts, _ = self.read()
        self.assertIsNone(facts["network"])
        self.assertIn("isn't installed", facts["errors"]["network"])
        self.assertIsNone(facts["firewall"])
        self.assertIn("systemctl is-active", facts["errors"]["firewall"])
        self.assertEqual(checks.check_network(None, facts["errors"]["network"], linux=True)[0]["level"], WARN)
        self.answers[("ip", "-j", "-4", "addr")] = (0, "not json", "")
        facts, _ = self.read()
        self.assertIn("wasn't JSON", facts["errors"]["network"])

    def test_firewalld_ufw_and_nftables(self):
        facts, _ = self.read()
        self.assertEqual(facts["firewall"]["active"], [])
        # ufw's service is active even when ufw is off: its config says which.
        self.answers[("systemctl", "is-active")] = (3, "inactive\nactive\ninactive\n", "")
        self.assertEqual(self.read()[0]["firewall"]["active"], [])
        (self.root / "etc" / "ufw").mkdir(parents=True)
        (self.root / "etc" / "ufw" / "ufw.conf").write_text("# comment\nENABLED=yes\n", encoding="utf-8")
        self.assertEqual(self.read()[0]["firewall"]["active"], ["ufw"])
        self.answers[("systemctl", "is-active")] = (0, "active\ninactive\nactive\n", "")
        self.answers.update({
            ("firewall-cmd", "--get-zone-of-interface=enp3s0"): (0, "home\n", ""),
            ("firewall-cmd", "--zone=home", "--query-port=8642/tcp"): (1, "no\n", ""),
            ("firewall-cmd", "--zone=home", "--list-rich-rules"): (0, "", ""),
            ("firewall-cmd", "--zone=home", "--query-service=mdns"): (0, "yes\n", "")})
        facts, run = self.read()
        self.assertEqual(facts["firewall"], {"active": ["firewalld", "nftables"], "zone": "home", "port": False,
                                             "mdns": True})
        # A rich rule for the home network lets the port in too.
        self.answers[("firewall-cmd", "--zone=home", "--list-rich-rules")] = (
            0, 'rule family="ipv4" source address="192.168.1.0/24" port port="8642" protocol="tcp" accept\n', "")
        self.assertIs(self.read()[0]["firewall"]["port"], True)
        # No zone for the interface: the default zone; a query firewalld refuses: not known.
        self.answers[("firewall-cmd", "--get-zone-of-interface=enp3s0")] = (2, "no zone\n", "")
        self.answers[("firewall-cmd", "--get-default-zone")] = (0, "public\n", "")
        self.answers[("firewall-cmd", "--zone=public", "--query-port=8642/tcp")] = (126, "", "Authorization failed")
        facts, _ = self.read()
        self.assertEqual((facts["firewall"]["zone"], facts["firewall"]["port"], facts["firewall"]["mdns"]),
                         ("public", None, None))


class FirewallLinesTests(unittest.TestCase):
    LAN = {"subnet": ipaddress.ip_network("192.168.1.0/24")}

    def lines(self, firewall, error=None, home_networks=None):
        return checks.check_firewall_linux(firewall, 8642, self.LAN, home_networks, error)

    def test_judged(self):
        none = self.lines({"active": []})
        self.assertEqual([l["level"] for l in none], [OK])
        self.assertIn("No firewall service is on", none[0]["text"])
        self.assertIn("home network", none[0]["text"])
        self.assertIn('"home_networks"', self.lines({"active": []}, home_networks=["100.64.0.0/10"])[0]["text"])
        self.assertEqual(self.lines(None, "systemctl isn't installed")[0]["text"],
                         "Couldn't check the firewall: systemctl isn't installed")
        closed = self.lines({"active": ["firewalld"], "zone": "public", "port": False, "mdns": False})
        self.assertEqual([l["level"] for l in closed], [PROBLEM, WARN])
        self.assertIn("source address=192.168.1.0/24 port port=8642 protocol=tcp accept", closed[0]["fix"])
        self.assertIn("--add-service=mdns", closed[1]["fix"])
        self.assertEqual([l["level"] for l in self.lines({"active": ["firewalld"], "zone": "home", "port": True,
                                                         "mdns": True})], [OK])
        unknown = self.lines({"active": ["firewalld"], "zone": None, "port": None, "mdns": None})
        self.assertEqual(unknown[0]["level"], WARN)
        self.assertIn("whether it lets port 8642 in couldn't be read", unknown[0]["text"])
        ufw = self.lines({"active": ["ufw"]})
        self.assertEqual(ufw[0]["level"], WARN)
        self.assertIn("sudo ufw allow from 192.168.1.0/24 to any port 8642 proto tcp", ufw[0]["fix"])
        nft = self.lines({"active": ["nftables"]})
        self.assertIn("sudo nft list ruleset", nft[0]["fix"])
        self.assertEqual(len(self.lines({"active": ["firewalld", "nftables"], "zone": "home", "port": True})), 1)
        self.assertIn("<your home network", checks.check_firewall_linux({"active": ["ufw"]}, 8642)[0]["fix"])


class WordingTests(unittest.TestCase):
    """Text both systems share names each one's own tools."""

    STATE = {"pid": 4321, "started": "2026-11-01T10:00:00", "python": "/usr/bin/python3", "background": False,
             "log": None}

    def test_server_lines(self):
        answer = {"answered": True, "deck_lab": True, "cards_ready": True}
        for platform, words, absent in (("linux", "in a terminal (Ctrl+C there stops it)", "window"),
                                        ("win32", "in a window (closing that window stops it)", "terminal")):
            with self.subTest(platform=platform), mock.patch.object(commands.sys, "platform", platform):
                text = commands.check_server(self.STATE, answer, 8642, "server.log")[0]["text"]
                self.assertIn(words, text)
                self.assertNotIn(absent, text)
                stuck = commands.check_server(None, {"answered": False, "listening": True, "error": "timed out"},
                                              8642, "server.log")[0]["fix"]
                self.assertIn("ss -ltnp 'sport = :8642'" if platform == "linux" else "Task Manager", stuck)
                self.assertNotIn("Task Manager" if platform == "linux" else "ss -ltnp", stuck)
                self.assertIn(f"in a {'terminal' if platform == 'linux' else 'window'}",
                              commands.describe_running(self.STATE, answer, 8642))

    def test_stop_timeouts(self):
        control = mock.Mock(request_stop=mock.Mock(return_value="timeout"))
        state = {**self.STATE, "port": 8642}
        for platform, words, absent in (("linux", "kill 4321", "Task Manager"), ("win32", "Task Manager", "kill")):
            with self.subTest(platform=platform), mock.patch.object(commands.sys, "platform", platform), \
                    mock.patch.object(commands, "control", control), \
                    mock.patch.object(commands, "find_server", return_value=(state, {"answered": True})), \
                    mock.patch.object(commands, "say") as said:
                self.assertEqual(commands.cmd_stop(8642), 1)
                text = " ".join(call.args[0] for call in said.call_args_list)
                self.assertIn(words, text)
                self.assertNotIn(absent, text)
            with mock.patch.object(server.sys, "platform", platform):
                text = server._stop_message("timeout", 8642)
                self.assertIn("systemctl --user stop decklab.service" if platform == "linux" else "Task Manager",
                              text)
                self.assertNotIn("pythonw" if platform == "linux" else "systemctl", text)


if __name__ == "__main__":
    unittest.main()
