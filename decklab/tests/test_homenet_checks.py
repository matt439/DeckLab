"""Tests for decklab/lib/homenet/checks.py: status's Network, Firewall,
Addresses and Sleep lines and the report, fed canned facts (among them the
PC as it was on 2026-10-01). Nothing here runs PowerShell or touches the
network.

Run from the repo root: python scripts/test_fixtures.py
"""
import os
import unittest
from unittest import mock

from decklab.lib import homenet
from decklab.lib.homenet import OK, WARN, PROBLEM
from decklab.tests.homenet_support import (
    DECK_LAB_GOOD, LAN, PORT, POWERCFG, PYTHON, PYTHON_TCP, PYTHON_UDP, PYTHONW, PYTHONW_RULE, REAL_FACTS,
    REAL_FACTS_NOON, levels, network, profiles, rule, texts,
)


# ------------------------------------------------------------ status: judging

class NetworkCheckTests(unittest.TestCase):
    def test_private_from_dhcp(self):
        lines = homenet.check_network(network())
        self.assertEqual(levels(lines), [OK])
        self.assertIn("192.0.2.10/24 from the router (DHCP)", lines[0]["text"])
        self.assertIn("Private", lines[0]["text"])

    def test_public_blocks_phones(self):
        for category in ("Public", 0, "0"):
            lines = homenet.check_network(network(category=category))
            self.assertEqual(levels(lines), [PROBLEM], category)
            self.assertIn("network-setup.ps1", lines[0]["fix"])

    def test_numeric_enums(self):
        lines = homenet.check_network(network(category=1, origin=1))
        self.assertEqual(levels(lines), [OK])
        self.assertIn("set by hand", lines[0]["text"])

    def test_domain_network(self):
        self.assertEqual(levels(homenet.check_network(network(category="DomainAuthenticated"))), [WARN])

    def test_no_route_or_address(self):
        self.assertEqual(levels(homenet.check_network({"routes": [], "interfaces": []})), [PROBLEM])
        self.assertEqual(levels(homenet.check_network(network(address="169.254.10.2"))), [PROBLEM])

    def test_couldnt_check(self):
        lines = homenet.check_network(None, "network: the cmdlet failed")
        self.assertEqual(levels(lines), [WARN])

    def vpn(self, facts, virtual=True, status="Up", metric=5):
        facts["routes"].append({"if_index": 30, "next_hop": "10.8.0.1", "metric": metric})
        facts["interfaces"].append({"if_index": 30, "alias": "VPN", "mac": None, "category": "Public",
                                    "status": status, "virtual": virtual, "if_type": 53,
                                    "ipv4": [{"address": "10.8.0.6", "prefix": 24, "origin": "Manual"}]})
        return facts

    def test_a_vpn_with_a_lower_metric_is_passed_over(self):
        # A full-tunnel VPN (WireGuard, say) has the lowest metric, but phones come in through Ethernet.
        facts = self.vpn(network())
        chosen = homenet.pick_interface(facts)
        self.assertEqual(chosen["alias"], "Ethernet")
        self.assertEqual(levels(homenet.check_network(facts)), [OK])

    def test_lowest_metric_physical_adapter_wins(self):
        facts = self.vpn(network(), virtual=False)          # a second physical adapter (Wi-Fi, say)
        self.assertEqual(homenet.pick_interface(facts)["alias"], "VPN")
        facts = self.vpn(network(), virtual=False, status="Disconnected")
        self.assertEqual(homenet.pick_interface(facts)["alias"], "Ethernet")

    def test_only_virtual_adapters(self):
        # A Hyper-V external switch carries the home network on a virtual adapter.
        facts = network()
        facts["interfaces"][0].update(alias="vEthernet (External)", virtual=True)
        chosen = homenet.pick_interface(facts)
        self.assertEqual(chosen["alias"], "vEthernet (External)")
        self.assertEqual(chosen["address"]["address"], "192.0.2.10")

    def test_lan_of(self):
        self.assertEqual(LAN["address"], "192.0.2.10")
        self.assertEqual(str(LAN["subnet"]), "192.0.2.0/24")
        self.assertEqual(LAN["kind"], "lan")
        wifi = network()
        wifi["interfaces"][0]["if_type"] = 71
        self.assertEqual(homenet.lan_of(wifi)["kind"], "wireless")
        unknown = network()
        del unknown["interfaces"][0]["if_type"]
        self.assertIsNone(homenet.lan_of(unknown)["kind"])
        self.assertIsNone(homenet.lan_of({"routes": [], "interfaces": []}))
        self.assertIsNone(homenet.lan_of(network(address="169.254.10.2")))


class FirewallValueTests(unittest.TestCase):
    def test_profile_set(self):
        everything = {"domain", "private", "public"}
        self.assertEqual(homenet.profile_set(0), everything)                  # NetSecurity's Any
        self.assertEqual(homenet.profile_set(2147483647), everything)         # the COM object's "all"
        self.assertEqual(homenet.profile_set(7), everything)
        self.assertEqual(homenet.profile_set(6), {"private", "public"})
        self.assertEqual(homenet.profile_set(2), {"private"})
        self.assertEqual(homenet.profile_set("2"), {"private"})
        self.assertEqual(homenet.profile_set("Any"), everything)
        self.assertEqual(homenet.profile_set("Private, Public"), {"private", "public"})
        self.assertEqual(homenet.profile_set(["Domain", "Private"]), {"domain", "private"})
        self.assertEqual(homenet.profile_set(None), set())

    def test_port_covered(self):
        self.assertTrue(homenet.port_covered("8642", 8642))
        self.assertTrue(homenet.port_covered("80, 8000-9000", 8642))
        self.assertTrue(homenet.port_covered("*", 8642))
        self.assertTrue(homenet.port_covered("", 8642))           # protocol Any: every port
        self.assertTrue(homenet.port_covered(["Any"], 8642))
        self.assertFalse(homenet.port_covered("80,443", 8642))
        self.assertFalse(homenet.port_covered("RPC", 8642))
        self.assertFalse(homenet.port_covered("86420", 8642))
        self.assertTrue(homenet.all_ports("*"))
        self.assertFalse(homenet.all_ports("8642"))

    def test_remote_any_and_protocol(self):
        self.assertTrue(homenet.remote_any("*"))
        self.assertTrue(homenet.remote_any("Any"))
        self.assertTrue(homenet.remote_any(None))
        self.assertFalse(homenet.remote_any("LocalSubnet"))
        self.assertFalse(homenet.remote_any(["192.0.2.0/255.255.255.0"]))
        self.assertEqual(homenet.protocol_name(6), "tcp")
        self.assertEqual(homenet.protocol_name("TCP"), "tcp")
        self.assertEqual(homenet.protocol_name(256), "any")
        self.assertEqual(homenet.protocol_name("17"), "udp")


class FirewallCheckTests(unittest.TestCase):
    def check(self, rules, profile_list=None, servers=(PYTHONW,), lan=LAN):
        firewall = {"current": 2, "profiles": profile_list or profiles(), "rules": rules}
        return homenet.check_firewall(firewall, PORT, list(servers), [PYTHON, PYTHONW], lan=lan)

    def test_the_real_pc(self):
        lines = self.check(REAL_FACTS["firewall"]["rules"])
        report = texts(lines)
        self.assertNotIn(PROBLEM, levels(lines), report)
        self.assertEqual(lines[0]["level"], OK)
        self.assertIn("'Deck Lab (TCP 8642)'", lines[0]["text"])
        broad = [item for item in lines if "every kind of network" in item["text"]]
        self.assertEqual(len(broad), 1, report)
        self.assertEqual(broad[0]["level"], WARN)
        self.assertIn("from any address", broad[0]["text"])
        self.assertIn("network-setup.ps1", broad[0]["fix"])
        python = [item for item in lines if "for python.exe" in item["text"]]
        self.assertEqual(sorted(item["text"].split(" lets ")[1].split(" in ")[0] for item in python),
                         ["every TCP port", "every UDP port"], report)
        for item in python:
            self.assertEqual(item["level"], WARN)
            self.assertIn("Private and Public", item["text"])
            self.assertIn("-PythonPrivateOnly", item["fix"])
        # The port rule covers pythonw.exe on Private networks, so Windows doesn't ask about it
        # (the real server on 8642 raised no prompt on 2026-10-01).
        nudge = [item for item in lines if "pythonw.exe (which runs" in item["text"]]
        self.assertEqual(nudge, [], report)
        self.assertEqual(len(lines), 4, report)

    def test_the_real_pc_at_noon(self):
        lines = self.check(REAL_FACTS_NOON["firewall"]["rules"])
        report = texts(lines)
        self.assertEqual(levels(lines), [OK, WARN, WARN, WARN, WARN, WARN], report)
        self.assertIn("'pythonw.exe', 'Deck Lab (TCP 8642)'", lines[0]["text"])
        self.assertEqual(sum("for pythonw.exe on Private and Public" in item["text"] for item in lines), 2, report)

    def test_pythonw_nudge_when_nothing_covers_the_port(self):
        lines = self.check([PYTHON_TCP])
        self.assertEqual(lines[0]["level"], PROBLEM)
        nudge = [item for item in lines if "pythonw.exe (which runs" in item["text"]]
        self.assertEqual(len(nudge), 1, texts(lines))
        self.assertIn("'Deck Lab (pythonw)'", nudge[0]["fix"])

    def test_python_rules_warn_only_for_public(self):
        # -PythonPrivateOnly takes only the Public bit off, so Domain alone is no warning.
        for profile_bits, warned in ((3, False), (2, False), (1, False), (4, True), (5, True), (6, True),
                                     (2147483647, True)):
            lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, dict(PYTHON_TCP, profiles=profile_bits)])
            self.assertEqual(WARN in levels(lines), warned, (profile_bits, texts(lines)))

    def test_port_rules_the_setup_script_didnt_make(self):
        mine = rule("My dev ports", ports="8000-9000", profiles=7)
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, mine])
        wide = [item for item in lines if item["level"] == WARN and "'My dev ports'" in item["text"]]
        self.assertEqual(len(wide), 1, texts(lines))
        self.assertIn("doesn't touch rules it didn't make", wide[0]["fix"])
        self.assertNotIn("It replaces", wide[0]["fix"])
        # Its own names, or its description, mean the script puts it right.
        for own in (rule("Deck Lab (TCP 8642)", profiles=7),
                    rule("Deck Lab (TCP 8642)", ports="*", profiles=7),         # every port: still its name
                    rule("Deck Lab (pythonw)", profiles=7),                     # no program: a port rule
                    rule("Deck Lab (old port)", profiles=7, description=homenet.SETUP_MARKER + " so phones ...")):
            lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, own])
            self.assertIn("It replaces the Deck Lab rules", lines[1]["fix"], texts(lines))
        self.assertTrue(homenet.made_by_setup(rule("Deck Lab (TCP 18642)"), 18642))
        self.assertFalse(homenet.made_by_setup(rule("Deck Lab (TCP 8642)"), 18642))
        self.assertTrue(homenet.made_by_setup(PYTHONW_RULE, 8642))

    def test_scope_that_takes_in_the_home_network(self):
        for scope in (dict(remote="LocalSubnet"), dict(remote="*"), dict(remote="192.0.2.0/255.255.255.0"),
                      dict(remote="192.0.2.0/24"), dict(remote="192.0.2.1-192.0.2.254"),
                      dict(remote="10.0.0.0/8,192.0.2.0/25,192.0.2.128/25"),
                      dict(remote="LocalSubnet", local="192.0.2.10"),
                      dict(remote="LocalSubnet", local="192.0.2.0/255.255.255.0"),
                      dict(remote="LocalSubnet", interface_types="Lan"),
                      dict(remote="LocalSubnet", interface_types="Lan,Wireless")):
            lines = self.check([rule("Deck Lab (TCP 8642)", **scope)], servers=(PYTHON,))
            self.assertEqual(levels(lines), [OK] if scope.get("remote") != "*" else [OK, WARN],
                             (scope, texts(lines)))

    def test_scope_that_may_leave_phones_out(self):
        cases = [(dict(remote="127.0.0.1"), "only from 127.0.0.1"),
                 (dict(remote="10.0.0.0/8"), "only from 10.0.0.0/8"),
                 (dict(remote="192.0.2.50"), "only from 192.0.2.50"),
                 (dict(remote="192.0.2.0/25"), "only from 192.0.2.0/25"),
                 (dict(remote="Intranet"), "only from Intranet"),
                 (dict(remote="LocalSubnet", local="192.0.2.50"), "only to 192.0.2.50"),
                 (dict(remote="LocalSubnet", interface_types="Wireless"), "only on Wireless connections")]
        for scope, words in cases:
            lines = self.check([rule("Deck Lab (TCP 8642)", **scope)], servers=(PYTHON,))
            self.assertEqual(levels(lines), [WARN], (scope, texts(lines)))
            self.assertIn(words, lines[0]["text"])
            self.assertIn("may not let phones on the home network in", lines[0]["text"])
            self.assertIn("network-setup.ps1", lines[0]["fix"])
        # A narrow rule beside one that covers is fine.
        lines = self.check([rule("narrow", remote="127.0.0.1"), DECK_LAB_GOOD], servers=(PYTHON,))
        self.assertEqual(levels(lines), [OK], texts(lines))
        # With the home network unknown, only scopes that take in everything count.
        self.assertEqual(levels(self.check([DECK_LAB_GOOD], servers=(PYTHON,), lan=None)), [OK])
        lines = self.check([rule("x", remote="192.0.2.0/24")], servers=(PYTHON,), lan=None)
        self.assertEqual(levels(lines), [WARN])

    def test_narrow_rule_for_one_program_and_none_for_the_other(self):
        # A server in a window (python.exe) and the task's pythonw.exe: python.exe's own rule is too
        # narrow, and nothing at all lets pythonw.exe in.
        narrow = rule("python dev", program=PYTHON, remote="127.0.0.1")
        lines = self.check([narrow], servers=(PYTHON, PYTHONW))
        report = texts(lines)
        self.assertEqual(lines[0]["level"], PROBLEM, report)
        self.assertIn("No firewall rule lets phones reach TCP 8642 on Private networks (for pythonw.exe)",
                      lines[0]["text"])
        self.assertEqual(lines[1]["level"], WARN, report)
        self.assertIn("Rule 'python dev' lets TCP 8642 in on Private networks for python.exe, but only from "
                      "127.0.0.1", lines[1]["text"])
        self.assertNotIn("pythonw.exe, but", report)
        # A narrow rule for every program is the only hope for both.
        lines = self.check([rule("narrow", remote="127.0.0.1")], servers=(PYTHON, PYTHONW))
        self.assertEqual(levels(lines)[0], WARN, texts(lines))
        self.assertIn("for python.exe, pythonw.exe, but only from 127.0.0.1", lines[0]["text"])
        self.assertNotIn(PROBLEM, levels(lines))

    def test_scope_gaps(self):
        self.assertEqual(homenet.scope_gaps(DECK_LAB_GOOD, LAN), [])
        self.assertEqual(homenet.scope_gaps({}, LAN), [])                     # older facts: no scope fields
        self.assertEqual(homenet.scope_gaps(rule("x", remote="::1,127.0.0.1", local="10.1.1.1",
                                                 interface_types="RemoteAccess"), LAN),
                         ["only from ::1,127.0.0.1", "only to 10.1.1.1", "only on RemoteAccess connections"])

    def test_after_the_setup_script(self):
        python_private = [dict(PYTHON_UDP, profiles=2), dict(PYTHON_TCP, profiles=2)]
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, *python_private])
        self.assertEqual(levels(lines), [OK], texts(lines))

    def test_no_rule(self):
        lines = self.check([PYTHON_UDP])
        self.assertEqual(lines[0]["level"], PROBLEM)
        self.assertIn("network-setup.ps1", lines[0]["fix"])

    def test_no_rule_but_private_firewall_off(self):
        lines = self.check([], profiles(private=False))
        self.assertEqual(lines[0]["level"], WARN)
        self.assertTrue(any("turned off for Private" in item["text"] for item in lines))

    def test_rule_for_python_only_doesnt_cover_pythonw(self):
        lines = self.check([rule("py", program=PYTHON, remote="LocalSubnet")])
        self.assertEqual(lines[0]["level"], PROBLEM)
        self.assertIn("pythonw.exe", lines[0]["text"])
        lines = self.check([rule("py", program=PYTHON, remote="LocalSubnet")], servers=(PYTHON,))
        self.assertEqual(lines[0]["level"], OK)

    def test_public_only_rule_doesnt_cover(self):
        lines = self.check([rule("Deck Lab (TCP 8642)", profiles=4, remote="LocalSubnet")])
        self.assertEqual(lines[0]["level"], PROBLEM)

    def test_disabled_rule_or_service_rule_doesnt_count(self):
        self.assertEqual(self.check([dict(DECK_LAB_GOOD, enabled=False)])[0]["level"], PROBLEM)
        self.assertEqual(self.check([dict(DECK_LAB_GOOD, service="Dnscache")])[0]["level"], PROBLEM)

    def test_block_rule_for_pythonw(self):
        # What Cancel on Windows' "allow this app" prompt leaves behind.
        block = rule("pythonw.exe", program=PYTHONW.lower(), ports="*", profiles=6, action=0)
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, block])
        problems = [item for item in lines if item["level"] == PROBLEM]
        self.assertEqual(len(problems), 1, texts(lines))
        self.assertIn("blocks pythonw.exe", problems[0]["text"])
        self.assertIn("network-setup.ps1", problems[0]["fix"])
        self.assertEqual(homenet.exit_code(lines), 1)

    def test_block_rule_on_public_only(self):
        block = rule("pythonw.exe", program=PYTHONW, ports="*", profiles=4, action=0)
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, block])
        self.assertNotIn(PROBLEM, levels(lines))
        self.assertTrue(any("doesn't apply to Private" in item["text"] for item in lines))

    def test_block_rule_for_the_port_and_for_other_programs(self):
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, rule("block it", action=0, profiles=2)])
        self.assertIn(PROBLEM, levels(lines))
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE,
                            rule("other", program=r"C:\Other\app.exe", ports="*", action=0, profiles=7)])
        self.assertEqual(levels(lines), [OK])
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, rule("other port", ports="80", action=0, profiles=7)])
        self.assertEqual(levels(lines), [OK])

    def test_rule_paths_with_variables(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\player\AppData\Local"}):
            block = rule("pythonw.exe", program=r"%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe",
                         ports="*", profiles=2, action=0)
            lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, block])
        self.assertIn(PROBLEM, levels(lines))

    def test_every_program_rule(self):
        open_all = rule("Open everything", ports="*", protocol=256, profiles=7)
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, open_all])
        wide = [item for item in lines if "every port, for every program" in item["text"]]
        self.assertEqual(len(wide), 1, texts(lines))
        self.assertIn("doesn't touch rules it didn't make", wide[0]["fix"])

    def test_private_rule_from_any_address(self):
        lines = self.check([rule("Deck Lab (TCP 8642)", remote="*", profiles=2), PYTHONW_RULE])
        self.assertEqual(levels(lines), [OK, WARN])
        self.assertIn("from any address", lines[1]["text"])

    def test_python_rule_for_other_ports_only(self):
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE, rule("py 5000", program=PYTHON, ports="5000", profiles=7)])
        self.assertEqual(levels(lines), [OK])

    def test_profiles(self):
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE], profiles(public=False))
        self.assertEqual(levels(lines), [OK, WARN])
        self.assertIn("turned off for Public", lines[1]["text"])
        lines = self.check([DECK_LAB_GOOD, PYTHONW_RULE], profiles(block_private=True))
        self.assertEqual(levels(lines), [OK, PROBLEM])
        self.assertIn("Block all incoming connections", lines[1]["text"])

    def test_couldnt_read(self):
        lines = homenet.check_firewall(None, PORT, [PYTHONW], [], "firewall: COM failed")
        self.assertEqual(levels(lines), [WARN])


class AddressAndSleepTests(unittest.TestCase):
    def test_addresses(self):
        lines = homenet.check_addresses(network(), "HomePC",
                                        {"answered": True, "addresses": ["192.0.2.10"]}, PORT)
        self.assertEqual(levels(lines), [OK, OK, OK])
        self.assertIn("http://192.0.2.10:8642/", lines[0]["text"])
        self.assertIn("http://homepc.local:8642/", lines[1]["text"])
        self.assertIn("00-00-5E-00-53-01", lines[2]["text"])
        self.assertIn("reserve 192.0.2.10", lines[2]["text"])
        self.assertIn("http://192.0.2.1/", lines[2]["text"])

    def test_name_not_answering_or_elsewhere(self):
        lines = homenet.check_addresses(network(), "HomePC", {"answered": False, "addresses": []}, PORT)
        self.assertEqual(levels(lines), [OK, WARN, OK])
        lines = homenet.check_addresses(network(), "HomePC",
                                        {"answered": True, "addresses": ["172.29.64.1"]}, PORT)
        self.assertEqual(levels(lines)[1], WARN)

    def test_fixed_address_needs_no_reservation(self):
        lines = homenet.check_addresses(network(origin="Manual"), "HomePC",
                                        {"answered": True, "addresses": ["192.0.2.10"]}, PORT)
        self.assertEqual(len(lines), 2)
        self.assertFalse(any("reserve" in item["text"] for item in lines))

    def test_powercfg(self):
        self.assertEqual(homenet.parse_powercfg(POWERCFG), (0, 600))
        german = POWERCFG.replace("Current AC Power Setting Index", "Aktueller Wechselstrom-Einstellungsindex")
        self.assertEqual(homenet.parse_powercfg(german), (0, 600))
        self.assertIsNone(homenet.parse_powercfg("nothing here"))
        self.assertIsNone(homenet.parse_powercfg(None))

    def test_sleep(self):
        self.assertEqual(levels(homenet.check_sleep(POWERCFG)), [OK])
        sleepy = POWERCFG.replace("AC Power Setting Index: 0x00000000", "AC Power Setting Index: 0x00000708")
        lines = homenet.check_sleep(sleepy)
        self.assertEqual(levels(lines), [WARN])
        self.assertIn("30 minutes", lines[0]["text"])
        self.assertIn("Never", lines[0]["fix"])
        self.assertEqual(levels(homenet.check_sleep(None, "power: powercfg failed")), [WARN])


class ReportTests(unittest.TestCase):
    def test_format_and_exit_code(self):
        lines = [homenet.line(OK, "Server", "Running."),
                 homenet.line(WARN, "Sleep", "Sleeps.", "Set it to Never.")]
        text = homenet.format_report(lines, header="Deck Lab status", footer="Phones are the real test.")
        self.assertIn("OK      Server: Running.", text)
        self.assertIn("WARN    Sleep: Sleeps.", text)
        self.assertIn("        Fix: Set it to Never.", text)
        self.assertIn("0 problems, 1 warning.", text)
        self.assertEqual(homenet.exit_code(lines), 0)
        self.assertEqual(homenet.exit_code(lines + [homenet.line(PROBLEM, "X", "y")]), 1)

    def test_step_error(self):
        facts = {"errors": ["network: Get-NetRoute failed", "power: powercfg missing"]}
        self.assertEqual(homenet.step_error(facts, "network"), "Get-NetRoute failed")
        self.assertIsNone(homenet.step_error(facts, "task"))
        self.assertEqual(homenet.step_error({"errors": [], "error": "PowerShell timed out"}, "task"),
                         "PowerShell timed out")


if __name__ == "__main__":
    unittest.main()
