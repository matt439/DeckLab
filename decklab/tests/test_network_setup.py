"""Tests for decklab/network-setup.ps1, the one step that needs
administrator (homenet status points at it). The script is only parsed, run
with -DryRun (against stand-ins for the cmdlets it uses, too), and run
without administrator (refused); the runs are skipped if the tests run as
administrator. Nothing here changes the firewall or the network.

Run from the repo root: python scripts/test_fixtures.py
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from decklab.lib import config, homenet
from decklab.tests.homenet_support import PORT, SETUP_PS1, WINDOWS, is_admin


# ------------------------------------------------------------ network-setup.ps1

class SetupScriptTests(unittest.TestCase):
    def test_ascii_only(self):
        # Windows PowerShell 5.1 reads a file without a BOM in the ANSI code page.
        SETUP_PS1.read_bytes().decode("ascii")

    def test_every_change_is_skipped_in_a_dry_run(self):
        changing = ("Set-NetConnectionProfile", "Remove-NetFirewallRule", "New-NetFirewallRule",
                    "Set-NetFirewallRule")
        code = [line for line in SETUP_PS1.read_text(encoding="ascii").splitlines()
                if not line.lstrip().startswith("#")]
        found = 0
        for i, text in enumerate(code):
            if any(cmdlet in text for cmdlet in changing):
                found += 1
                guarded = "if (-not $DryRun)" in text or "if (-not $DryRun)" in code[i - 1]
                self.assertTrue(guarded, f"line {i + 1} changes something outside 'if (-not $DryRun)': {text}")
        self.assertEqual(found, 6)

    def test_only_python_and_deck_lab_rules_are_changed(self):
        text = SETUP_PS1.read_text(encoding="ascii")
        self.assertIn("-DisplayName 'Deck Lab (*'", text)
        self.assertNotIn("'Deck Lab*'", text)
        self.assertIn("'TCP Query User{*'", text)
        self.assertIn("'UDP Query User{*'", text)
        self.assertIn("Profile       = 'Private'", text)
        self.assertIn("RemoteAddress = 'LocalSubnet'", text)
        self.assertIn('$marker = "Added by $scriptName"', text)
        self.assertTrue(homenet.SETUP_MARKER.startswith("Added by decklab\\network-setup.ps1"))
        # New rules are for Private only; an existing rule only ever loses the Public bit.
        self.assertIsNone(re.search(r"-Profile\s+(?!Private\b|\$newProfile\b)", text))
        self.assertIsNone(re.search(r"Profile\s*=\s*'(?!Private')", text))
        self.assertIn("$bits -band (-bnot 4) -band 3", text)

    def test_never_runs_a_program(self):
        # It runs as administrator: whatever "python" on the PATH is would run with those rights.
        code = "\n".join(line for line in SETUP_PS1.read_text(encoding="ascii").splitlines()
                         if not line.lstrip().startswith("#"))
        for running in ("Start-Process", "Invoke-Expression", "iex ", "cmd /c", "sys.executable", "Get-Command"):
            self.assertNotIn(running, code)
        # The call operator & at the start of a statement or expression runs a program.
        self.assertIsNone(re.search(r"(^|[;(=|{])\s*&\s*[$'\"\w]", code, re.M))

    def test_asks_before_making_the_network_private(self):
        # A real run can't be tried here (it needs administrator), so check the order: ask (or -Yes),
        # then change. A PowerShell that can't ask (-NonInteractive) changes nothing.
        text = SETUP_PS1.read_text(encoding="ascii")
        self.assertIn("[switch]$Yes", text)
        self.assertIn("$sure = $DryRun -or $Yes", text)
        ask, sure = text.index("Read-Host"), text.index("if ($sure) {")
        change = text.index("Set-NetConnectionProfile -InterfaceIndex")
        self.assertLess(text.rindex("try {", 0, ask), ask)
        self.assertLess(ask, sure)
        self.assertLess(sure, change)
        self.assertIn("$answer = ''", text[ask:sure])          # no answer is a no

    @unittest.skipUnless(WINDOWS, "PowerShell")
    def test_parses(self):
        command = ("$e = $null; $t = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
                   f"'{SETUP_PS1}', [ref]$t, [ref]$e); $e.Count")
        done = subprocess.run([str(homenet.POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(done.stdout.strip(), "0", done.stderr)

    def run_script(self, *args):
        return subprocess.run([str(homenet.POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-File", str(SETUP_PS1), *args], capture_output=True, text=True,
                              timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)

    @unittest.skipUnless(WINDOWS and not is_admin(), "needs Windows, and must not run as administrator")
    def test_refuses_without_administrator(self):
        done = self.run_script()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("needs administrator", done.stdout)
        self.assertIn("Nothing was changed.", done.stdout)
        self.assertNotIn("1. The network", done.stdout)
        self.assertIn("    powershell -ExecutionPolicy Bypass -File decklab\\network-setup.ps1\n", done.stdout)

    @unittest.skipUnless(WINDOWS and not is_admin(), "needs Windows, and must not run as administrator")
    def test_the_refusal_keeps_the_options_given(self):
        # Run again as administrator with what it says, -PythonPrivateOnly must still be there.
        pythonw = r"C:\Program Files\Python\pythonw.exe"
        done = self.run_script("-PythonPrivateOnly", "-Pythonw", pythonw, "-Yes")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("Nothing was changed.", done.stdout)
        self.assertIn("    powershell -ExecutionPolicy Bypass -File decklab\\network-setup.ps1 -PythonPrivateOnly "
                      f'-Pythonw "{pythonw}" -Yes\n', done.stdout)

    @unittest.skipUnless(WINDOWS and not is_admin(), "needs Windows, and must not run as administrator")
    def test_dry_run(self):
        done = self.run_script("-DryRun", "-PythonPrivateOnly")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for heading in ("Dry run: nothing is changed", "1. The network", "2. Deck Lab's firewall rules",
                        "Deck Lab's port:"):
            self.assertIn(heading, done.stdout)
        self.assertNotIn("Done:", done.stdout)
        self.assertRegex(done.stdout, r"Everything is already right|A real run would make \d+ change")


# Runs network-setup.ps1 -DryRun against stand-ins for the cmdlets it uses
# (a function shadows a cmdlet of the same name), one scenario after another
# in one PowerShell, and prints each run's output and exit code as JSON. The
# stand-ins for the cmdlets that change things throw, and a dry run never
# reaches them anyway.
FAKE_CMDLETS_PS = r"""
param([string]$Scenarios, [string]$Script)
$ErrorActionPreference = 'Stop'
[Flags()] enum FakeProfile {
    Any = 0
    Domain = 1
    Private = 2
    Public = 4
}
$global:fake = $null
$global:rules = @()
function global:Get-ScheduledTask { [CmdletBinding()] param($TaskPath, $TaskName)
    if ($global:fake.task) { [pscustomobject]@{ Actions = @([pscustomobject]@{ Execute = [string]$global:fake.task }) } } }
function global:Get-NetRoute { [CmdletBinding()] param($AddressFamily, $DestinationPrefix, $PolicyStore)
    foreach ($r in @($global:fake.routes)) { if ($r) { [pscustomobject]@{ ifIndex = [int]$r.if_index; RouteMetric = [int]$r.metric; InterfaceAlias = $r.alias } } } }
function global:Get-NetAdapter { [CmdletBinding()] param([switch]$Physical, $InterfaceIndex, [switch]$IncludeHidden)
    $all = foreach ($a in @($global:fake.adapters)) { if ($a) { [pscustomobject]@{ ifIndex = [int]$a.if_index; Name = $a.name
        InterfaceDescription = $a.description; Status = $a.status; Virtual = [bool]$a.virtual; Hidden = [bool]$a.hidden } } }
    if (-not $IncludeHidden) { $all = @($all | Where-Object { -not $_.Hidden }) }
    if ($Physical) { $all = @($all | Where-Object { -not $_.Virtual }) }
    if ($InterfaceIndex) { $all = @($all | Where-Object { $_.ifIndex -eq $InterfaceIndex }) }
    $all }
function global:Get-NetIPInterface { [CmdletBinding()] param($InterfaceIndex, $AddressFamily)
    [pscustomobject]@{ InterfaceMetric = 25 } }
function global:Get-NetConnectionProfile { [CmdletBinding()] param($InterfaceIndex)
    foreach ($p in @($global:fake.adapters)) { if ($p -and $p.if_index -eq $InterfaceIndex -and $p.category) {
        [pscustomobject]@{ InterfaceAlias = $p.name; Name = $p.network; NetworkCategory = $p.category } } } }
function global:Get-NetFirewallRule { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Filter, $DisplayName)
    process { if ($Filter) { $Filter.Rule } }
    end { if ($DisplayName) { $global:rules | Where-Object { $_.DisplayName -like $DisplayName } } } }
function global:Get-NetFirewallApplicationFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule, [switch]$All)
    process { if ($Rule) { [pscustomobject]@{ Program = $Rule.Fake.program; Rule = $Rule } } }
    end { if ($All) { foreach ($r in $global:rules) { [pscustomobject]@{ Program = $r.Fake.program; Rule = $r } } } } }
function global:Get-NetFirewallPortFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
    process { [pscustomobject]@{ Protocol = $Rule.Fake.protocol; LocalPort = $Rule.Fake.local_port } } }
function global:Get-NetFirewallAddressFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
    process { [pscustomobject]@{ RemoteAddress = $Rule.Fake.remote; LocalAddress = $Rule.Fake.local } } }
function global:Get-NetFirewallInterfaceTypeFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
    process { [pscustomobject]@{ InterfaceType = $Rule.Fake.interface_type } } }
function global:Get-NetFirewallInterfaceFilter { [CmdletBinding()] param([Parameter(ValueFromPipeline = $true)]$Rule)
    process { [pscustomobject]@{ InterfaceAlias = $Rule.Fake.interfaces } } }
foreach ($name in 'New-NetFirewallRule', 'Remove-NetFirewallRule', 'Set-NetFirewallRule', 'Set-NetConnectionProfile') {
    Set-Item "function:global:$name" -Value ([scriptblock]::Create("throw 'the test reached $name'"))
}
$list = Get-Content -Raw -Encoding UTF8 $Scenarios | ConvertFrom-Json
$results = foreach ($scenario in $list) {
    $global:fake = $scenario
    $global:rules = @(foreach ($f in @($scenario.rules)) { if ($f) {
        [pscustomobject]@{ Name = $f.display; DisplayName = $f.display; Direction = $f.direction; Action = $f.action
            Enabled = $f.enabled; Profile = [FakeProfile]([int]$f.profile); Description = [string]$f.description; Fake = $f } } })
    $arguments = @{ DryRun = $true }
    foreach ($p in $scenario.args.PSObject.Properties) { $arguments[$p.Name] = $p.Value }
    $global:LASTEXITCODE = 0
    $text = (& $Script @arguments *>&1 | Out-String -Width 400)
    [pscustomobject]@{ exit = $LASTEXITCODE; output = $text }
}
ConvertTo-Json @($results) -Depth 3 -Compress
"""


def fake_rule(display, direction="Inbound", action="Allow", enabled="True", profile=2, description="",
              protocol="TCP", local_port=str(PORT), remote="LocalSubnet", local="Any", interface_type="Any",
              interfaces="Any", program="Any"):
    """A firewall rule as the stand-in cmdlets give it (NetSecurity's words; profile as its flags)."""
    return {"display": display, "direction": direction, "action": action, "enabled": enabled, "profile": profile,
            "description": description, "protocol": protocol, "local_port": local_port, "remote": remote,
            "local": local, "interface_type": interface_type, "interfaces": interfaces, "program": program}


def home(category="Private"):
    """Ethernet with the internet route, on the network 'HomeNet'."""
    return {"routes": [{"if_index": 17, "metric": 0, "alias": "Ethernet"}],
            "adapters": [{"if_index": 17, "name": "Ethernet", "description": "Realtek PCIe 2.5GbE",
                          "status": "Up", "virtual": False, "network": "HomeNet", "category": category}]}


@unittest.skipUnless(WINDOWS and not is_admin(), "needs Windows, and must not run as administrator")
class SetupScriptDecisionTests(unittest.TestCase):
    """network-setup.ps1 -DryRun against stand-in cmdlets: which rules it
    adds, removes, limits or leaves alone, and which network it picks. All
    the scenarios run in one PowerShell, in setUpClass."""

    @classmethod
    def setUpClass(cls):
        folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(folder.cleanup)
        root = Path(folder.name)
        cls.pythonw = root / "Python" / "pythonw.exe"
        cls.pythonw.parent.mkdir()
        cls.pythonw.write_bytes(b"")
        (root / "Python" / "python.exe").write_bytes(b"")
        cls.python = cls.pythonw.with_name("python.exe")
        cls.port = homenet._int(config.load().get("port"), 8642)
        good = fake_rule(f"Deck Lab (TCP {cls.port})", local_port=str(cls.port))
        port = str(cls.port)

        def prompt_rule(program, protocol, profile, enabled="True"):
            return fake_rule(program.name, protocol=protocol, local_port="Any", remote="Any", profile=profile,
                             program=str(program), enabled=enabled)
        scenarios = {
            # This PC on 2026-10-01: the right port rule, one open everywhere, and Windows' prompt rules.
            "this_pc": dict(home(), task=str(cls.pythonw), args={"PythonPrivateOnly": True}, rules=[
                good, fake_rule(f"Deck Lab (TCP {cls.port})", local_port=port, remote="Any", profile=0),
                prompt_rule(cls.python, "TCP", 6), prompt_rule(cls.python, "UDP", 6),
                prompt_rule(cls.pythonw, "TCP", 6), prompt_rule(cls.pythonw, "UDP", 6)]),
            # Rules named "Deck Lab (" that it didn't make, a block rule with its own name, and one it did make.
            "not_mine": dict(home(), task=str(cls.pythonw), args={}, rules=[
                good, fake_rule("Deck Lab (pythonw)", local_port=port, program=str(cls.pythonw)),
                fake_rule(f"Deck Lab (TCP {cls.port})", action="Block", profile=4, local_port=port, remote="Any"),
                fake_rule("Deck Lab (block on Public)", action="Block", profile=4, local_port=port),
                fake_rule("Deck Lab (my notes)", profile=7, local_port=port, remote="Any"),
                fake_rule("Deck Lab (pythonw)", direction="Outbound", local_port=port),
                fake_rule("Deck Labs Sync", profile=7, local_port="Any", remote="Any"),
                fake_rule("Deck Lab (TCP 8000)", local_port="8000", profile=7, remote="Any",
                          description=homenet.SETUP_MARKER + " so phones on the home network can reach Deck Lab.")]),
            # A right-looking rule with a narrower scope isn't "already right".
            "scope": dict(home(), task=str(cls.pythonw), args={}, rules=[
                fake_rule(f"Deck Lab (TCP {cls.port})", local_port=port, interface_type="Wireless"),
                fake_rule("Deck Lab (pythonw)", local_port=port, program=str(cls.pythonw), local="192.168.0.50")]),
            # No task and no -Pythonw: nothing about pythonw is touched, and no Python is run to find one.
            "unknown_pythonw": dict(home(), task=None, args={}, rules=[
                good, fake_rule("Deck Lab (pythonw)", local_port=port, program=r"C:\Old\pythonw.exe", profile=0,
                                description=homenet.SETUP_MARKER + " so phones ...")]),
            # The task points at a Python that's gone.
            "stale_task": dict(home(), task=r"C:\Gone\Python313\pythonw.exe", args={}, rules=[good]),
            # -PythonPrivateOnly takes only the Public bit off.
            "profiles": dict(home(), task=str(cls.pythonw), args={"PythonPrivateOnly": True}, rules=[
                good, fake_rule("Deck Lab (pythonw)", local_port=port, program=str(cls.pythonw)),
                prompt_rule(cls.python, "TCP", 0), prompt_rule(cls.python, "UDP", 4),
                prompt_rule(cls.pythonw, "TCP", 5), prompt_rule(cls.pythonw, "UDP", 3),
                prompt_rule(cls.python, "TCP", 4, enabled="False")]),
            # A full-tunnel VPN has the lowest metric and a Public network; the home network is Ethernet.
            "vpn": dict(task=str(cls.pythonw), args={}, rules=[good],
                        routes=[{"if_index": 30, "metric": 0, "alias": "WireGuard"},
                                {"if_index": 17, "metric": 25, "alias": "Ethernet"}],
                        adapters=[{"if_index": 30, "name": "WireGuard", "description": "WireGuard Tunnel",
                                   "status": "Up", "virtual": True, "network": "wg0", "category": "Public"},
                                  {"if_index": 17, "name": "Ethernet", "description": "Realtek PCIe 2.5GbE",
                                   "status": "Up", "virtual": False, "network": "HomeNet", "category": "Public"}]),
            # The home Wi-Fi on a hidden adapter (this PC's Realtek card has two: 'Wi-Fi 3' and 'Wi-Fi 4'),
            # not virtual: it's the home network, as status says too.
            "hidden_wifi": dict(task=str(cls.pythonw), args={}, rules=[good],
                                routes=[{"if_index": 7, "metric": 0, "alias": "Wi-Fi 3"}],
                                adapters=[{"if_index": 7, "name": "Wi-Fi 3", "description": "Realtek 8922AE WiFi 7",
                                           "status": "Up", "virtual": False, "hidden": True, "network": "HomeNet",
                                           "category": "Public"}]),
            # -Yes: a real run wouldn't ask.
            "yes": dict(home("Public"), task=str(cls.pythonw), args={"Yes": True}, rules=[
                good, fake_rule("Deck Lab (pythonw)", local_port=port, program=str(cls.pythonw))]),
            # No task and no -Pythonw, and a rule named 'Deck Lab (pythonw)' with no program: a port rule
            # open everywhere, which goes whichever pythonw.exe runs Deck Lab.
            "unknown_pythonw_port_rule": dict(home(), task=None, args={}, rules=[
                good, fake_rule("Deck Lab (pythonw)", local_port=port, profile=0, remote="Any")]),
            # Only a virtual adapter has the route: it's left alone.
            "virtual_only": dict(task=str(cls.pythonw), args={}, rules=[good],
                                 routes=[{"if_index": 45, "metric": 0, "alias": "vEthernet (External)"}],
                                 adapters=[{"if_index": 45, "name": "vEthernet (External)",
                                            "description": "Hyper-V Virtual Ethernet Adapter", "status": "Up",
                                            "virtual": True, "network": "HomeNet", "category": "Public"}]),
        }
        cls.names = list(scenarios)
        (root / "scenarios.json").write_text(json.dumps(list(scenarios.values())), encoding="utf-8")
        (root / "fake.ps1").write_text(FAKE_CMDLETS_PS, encoding="ascii")
        done = subprocess.run([str(homenet.POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(root / "fake.ps1"), "-Scenarios", str(root / "scenarios.json"),
                               "-Script", str(SETUP_PS1)],
                              capture_output=True, text=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            results = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise AssertionError(f"the stand-in run failed: {done.stdout}\n{done.stderr}") from None
        cls.results = dict(zip(cls.names, results))

    def output(self, name):
        result = self.results[name]
        self.assertEqual(result["exit"], 0, result["output"])
        self.assertNotIn("the test reached", result["output"])
        return result["output"]

    def test_this_pc(self):
        text = self.output("this_pc")
        self.assertIn(f"Already right: 'Deck Lab (TCP {self.port})': Allow TCP port {self.port}, on Private networks, "
                      "from the home network only (LocalSubnet)", text)
        add = text.index("Would: add 'Deck Lab (pythonw)'")
        remove = text.index(f"Would: remove 'Deck Lab (TCP {self.port})': Allow TCP port {self.port}, on every kind "
                            "of network, from any address")
        self.assertLess(add, remove)                    # the right rules go in before anything comes out
        self.assertEqual(text.count("Would: take Public networks off"), 4, text)
        self.assertEqual(text.count("(it then applies to Private networks)"), 4, text)
        self.assertIn("A real run would make 6 change(s).", text)

    def test_rules_it_didnt_make_are_left_alone(self):
        text = self.output("not_mine")
        self.assertIn("Already right: 'Deck Lab (pythonw)'", text)
        for name in (f"'Deck Lab (TCP {self.port})': Block", "'Deck Lab (block on Public)': Block",
                     "'Deck Lab (my notes)': Allow", "'Deck Lab (pythonw)': Allow TCP port"):
            self.assertIn(f"Left alone, since this script didn't make it: {name}", text)
        self.assertIn("(outbound)", text)
        self.assertNotIn("Deck Labs Sync", text)
        # Its own description marks a rule it made, whatever the name.
        self.assertIn("Would: remove 'Deck Lab (TCP 8000)'", text)
        self.assertEqual(text.count("  Would:"), 1, text)
        self.assertIn("'Deck Lab (my notes)': Allow TCP port 8642, on Domain, Private and Public networks", text)

    def test_a_narrower_scope_is_put_right(self):
        text = self.output("scope")
        self.assertIn(f"Would: remove 'Deck Lab (TCP {self.port})': Allow TCP port {self.port}, on Private networks, "
                      "from the home network only (LocalSubnet), on Wireless connections only", text)
        self.assertIn("to 192.168.0.50 only", text)
        self.assertIn("A real run would make 4 change(s).", text)

    def test_unknown_pythonw(self):
        text = self.output("unknown_pythonw")
        self.assertIn("It isn't known which pythonw.exe runs Deck Lab", text)
        self.assertIn("python -m decklab.lib.homenet install", text)
        self.assertIn("-Pythonw <path to pythonw.exe>", text)
        self.assertIn("Left alone, since it isn't known which pythonw.exe runs Deck Lab: 'Deck Lab (pythonw)'", text)
        self.assertNotIn("Would: remove 'Deck Lab (pythonw)'", text)
        self.assertNotIn("3. Block rules", text)
        self.assertIn("Everything is already right", text)

    def test_stale_task(self):
        text = self.output("stale_task")
        self.assertIn(r"The pythonw.exe from the Deck Lab task isn't there: C:\Gone\Python313\pythonw.exe", text)
        self.assertIn("install' again", text)
        self.assertIn("It isn't known which pythonw.exe runs Deck Lab", text)

    def test_only_the_public_bit_comes_off(self):
        text = self.output("profiles")
        self.assertIn("Would: take Public networks off 'python.exe': Allow TCP every port, on every kind of network", text)
        self.assertIn("(it then applies to Domain and Private networks)", text)          # Any
        self.assertIn("Would: turn off 'python.exe': Allow UDP every port, on Public networks", text)    # Public only
        self.assertIn("Would: take Public networks off 'pythonw.exe': Allow TCP every port, on Domain and Public "
                      "networks", text)
        self.assertIn("(it then applies to Domain networks)", text)                      # Domain and Public
        self.assertNotIn("'pythonw.exe': Allow UDP", text)                                # Domain and Private: no Public
        self.assertNotIn("(turned off)", text)                                            # a rule already off is left
        self.assertIn("A real run would make 3 change(s).", text)

    def test_a_vpn_is_passed_over(self):
        text = self.output("vpn")
        self.assertIn("Left alone: 'WireGuard' (WireGuard Tunnel) has an internet route, but it's a VPN", text)
        self.assertIn("'Ethernet' is on the network 'HomeNet', set to Public.", text)
        self.assertIn("only do this at home", text)
        self.assertIn("Would: set the network 'HomeNet' to Private", text)
        self.assertIn("(A real run asks first, unless it's given -Yes.)", text)
        self.assertNotIn("'wg0' to Private", text)
        self.assertLess(text.index("'HomeNet', set to Public"), text.index("Would: set the network"))

    def test_a_hidden_wifi_adapter_is_the_home_network(self):
        text = self.output("hidden_wifi")
        self.assertIn("'Wi-Fi 3' is on the network 'HomeNet', set to Public.", text)
        self.assertIn("Would: set the network 'HomeNet' to Private", text)
        self.assertNotIn("VPN or virtual adapter", text)

    def test_yes_doesnt_ask(self):
        text = self.output("yes")
        self.assertIn("Would: set the network 'HomeNet' to Private", text)
        self.assertNotIn("A real run asks first", text)
        self.assertIn("A real run would make 1 change(s).", text)

    def test_a_pythonw_named_port_rule_goes_even_when_pythonw_is_unknown(self):
        text = self.output("unknown_pythonw_port_rule")
        self.assertIn("It isn't known which pythonw.exe runs Deck Lab", text)
        self.assertIn("Would: remove 'Deck Lab (pythonw)': Allow TCP port 8642, on every kind of network, from any "
                      "address", text)
        self.assertNotIn("Left alone", text)
        self.assertIn("A real run would make 1 change(s).", text)

    def test_only_a_virtual_adapter(self):
        text = self.output("virtual_only")
        self.assertIn("No physical network adapter (cable or Wi-Fi) that's up has the internet route", text)
        self.assertNotIn("Would: set the network", text)


if __name__ == "__main__":
    unittest.main()
