"""Status's Windows facts, from one read-only PowerShell call (GATHER_PS)
that prints them as JSON. run_powershell is here beside gather_facts, its
only caller, so a test replaces it here (homenet.gather.run_powershell)."""
import base64
import json
import os
import subprocess
import sys
import time

from .common import POWERSHELL, PS_TIMEOUT, _SPAWN, _decode, watchdog_name


# ------------------------------------------------------------ status: gathering facts

# One read-only PowerShell call for every Windows fact status needs. It runs
# with no profile and no window, reads the task name and port from the
# environment (so nothing is quoted into the script; the watchdog task's name
# too, E11-S26), and prints one line of
# JSON. Each step that fails is listed in "errors" and left null, so one
# broken cmdlet doesn't hide the rest. Enums are turned into strings here,
# since PowerShell 5.1's ConvertTo-Json writes them as numbers.
GATHER_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$clock = [Diagnostics.Stopwatch]::StartNew()
$out = [ordered]@{ errors = @() }
function Step($name, [scriptblock]$block) {
    try { $out[$name] = & $block } catch { $out.errors += "${name}: $($_.Exception.Message)"; $out[$name] = $null }
}
function TaskFacts($name) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) { return $null }
    $info = Get-ScheduledTaskInfo -InputObject $task
    [ordered]@{
        xml = [string](Export-ScheduledTask -TaskPath '\' -TaskName $name)
        state = [string]$task.State
        last_run = if ($info.LastRunTime) { $info.LastRunTime.ToString('s') } else { $null }
        last_result = [int64]$info.LastTaskResult
    }
}
Step 'task' { TaskFacts $env:DECKLAB_TASK }
Step 'watchdog' { TaskFacts $env:DECKLAB_WATCHDOG_TASK }
Step 'network' {
    # ActiveStore: the routes in use now, not ones saved for adapters that are unplugged.
    $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -PolicyStore ActiveStore -ErrorAction SilentlyContinue)
    $idx = @($routes | ForEach-Object { $_.ifIndex } | Select-Object -Unique)
    $ipif = @(Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $idx -contains $_.ifIndex })
    $addrs = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $idx -contains $_.ifIndex })
    $adapters = @(Get-NetAdapter -IncludeHidden | Where-Object { $idx -contains $_.ifIndex })
    $profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
    [ordered]@{
        routes = @($routes | ForEach-Object { $r = $_
            $metric = @($ipif | Where-Object { $_.ifIndex -eq $r.ifIndex })[0].InterfaceMetric
            [ordered]@{ if_index = $r.ifIndex; next_hop = $r.NextHop; metric = [int]$r.RouteMetric + [int]$metric } })
        interfaces = @($idx | ForEach-Object { $i = $_
            $a = @($adapters | Where-Object { $_.ifIndex -eq $i })[0]
            $p = @($profiles | Where-Object { $_.InterfaceIndex -eq $i })[0]
            [ordered]@{
                if_index = $i
                alias = if ($a) { $a.Name } else { $null }
                description = if ($a) { $a.InterfaceDescription } else { $null }
                mac = if ($a) { $a.MacAddress } else { $null }
                status = if ($a) { [string]$a.Status } else { $null }
                virtual = if ($a) { [bool]$a.Virtual } else { $null }
                if_type = if ($a) { [int]$a.InterfaceType } else { $null }
                dhcp = [string](@($ipif | Where-Object { $_.ifIndex -eq $i })[0].Dhcp)
                category = if ($p) { [string]$p.NetworkCategory } else { $null }
                network_name = if ($p) { $p.Name } else { $null }
                ipv4 = @($addrs | Where-Object { $_.ifIndex -eq $i } | ForEach-Object {
                    [ordered]@{ address = $_.IPAddress; prefix = [int]$_.PrefixLength; origin = [string]$_.PrefixOrigin } })
            } })
    }
}
Step 'firewall' {
    # The firewall's COM object: complete and quick without administrator
    # (Get-NetFirewallPortFilter isn't). Only inbound rules that could
    # matter: Python's, the port's, and rules for every program and port.
    # Rules with an owner are Store apps' rules, which only apply to that app.
    $fw = New-Object -ComObject HNetCfg.FwPolicy2
    $port = [int]$env:DECKLAB_PORT
    $rules = foreach ($r in $fw.Rules) {
        if ($r.Direction -ne 1 -or $r.LocalUserOwner) { continue }
        $prog = [string]$r.ApplicationName
        $leaf = if ($prog) { [IO.Path]::GetFileName($prog) } else { '' }
        $ports = [string]$r.LocalPorts
        $hit = $false
        if ($ports -and $ports -ne '*') {
            foreach ($part in $ports.Split(',')) {
                $bits = $part.Trim().Split('-')
                if ($bits.Count -eq 2 -and $bits[0] -match '^\d+$' -and $bits[1] -match '^\d+$') {
                    if ($port -ge [int]$bits[0] -and $port -le [int]$bits[1]) { $hit = $true }
                } elseif ($bits[0] -eq "$port") { $hit = $true }
            }
        }
        $service = [string]$r.serviceName
        $everything = (-not $prog) -and (-not $service -or $service -eq '*') -and ($ports -eq '*' -or -not $ports)
        if (-not ($leaf -match '^(?i)pythonw?\.exe$' -or $hit -or $everything)) { continue }
        # The description only for Deck Lab's rules: it shows which ones network-setup.ps1 made.
        $description = if ([string]$r.Name -like 'Deck Lab (*') { [string]$r.Description } else { '' }
        [ordered]@{ name = $r.Name; program = $prog; service = $service; protocol = [int]$r.Protocol
            local_ports = $ports; remote_addresses = [string]$r.RemoteAddresses
            local_addresses = [string]$r.LocalAddresses; interface_types = [string]$r.InterfaceTypes
            enabled = [bool]$r.Enabled; profiles = [int]$r.Profiles; action = [int]$r.Action
            description = $description }
    }
    [ordered]@{
        current = [int]$fw.CurrentProfileTypes
        profiles = @(foreach ($p in @(@{n='Domain';b=1}, @{n='Private';b=2}, @{n='Public';b=4})) {
            [ordered]@{ name = $p.n; bit = $p.b; enabled = [bool]$fw.FirewallEnabled($p.b)
                block_all = [bool]$fw.BlockAllInboundTraffic($p.b) } })
        rules = @($rules)
    }
}
Step 'power' { (& "$env:SystemRoot\System32\powercfg.exe" /q SCHEME_CURRENT SUB_SLEEP STANDBYIDLE) -join "`n" }
$out.ms = $clock.ElapsedMilliseconds
$out | ConvertTo-Json -Depth 6 -Compress
"""


def run_powershell(script, env=None, timeout=PS_TIMEOUT):
    """Run a PowerShell script (no profile, no window, no prompts) and parse
    the JSON it prints. Raises RuntimeError with a plain reason."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    environ = dict(os.environ)
    environ.update(env or {})
    try:
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                              capture_output=True, stdin=subprocess.DEVNULL, env=environ, timeout=timeout,
                              **_SPAWN)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"PowerShell didn't finish within {timeout} seconds") from None
    except OSError as e:
        raise RuntimeError(f"PowerShell can't run: {e}") from None
    text = _decode(done.stdout or b"").strip()
    try:
        return json.loads(text.splitlines()[-1] if text else "")
    except (ValueError, IndexError):
        reason = " ".join(_decode(done.stderr or b"").split())[:300] or f"exit code {done.returncode}"
        raise RuntimeError(f"PowerShell's answer couldn't be read ({reason})") from None


def gather_facts(task_name, port):
    """The Windows facts for status: {"task", "watchdog", "network",
    "firewall", "power", "errors", "ms", "seconds"}. A step that couldn't run is None,
    with the reason in errors."""
    started = time.monotonic()
    if sys.platform != "win32":
        facts = {"error": "these checks only work on Windows"}
    else:
        try:
            facts = run_powershell(GATHER_PS, {"DECKLAB_TASK": task_name, "DECKLAB_PORT": str(port),
                                               "DECKLAB_WATCHDOG_TASK": watchdog_name(task_name)})
        except RuntimeError as e:
            facts = {"error": str(e)}
    if not isinstance(facts, dict):
        facts = {"error": "PowerShell's answer wasn't what was expected"}
    facts.setdefault("errors", [])
    facts["seconds"] = round(time.monotonic() - started, 1)
    return facts


def step_error(facts, step):
    """Why a step of gather_facts has no answer: its own error ("step: ..."),
    or the error that stopped the whole call. None when it ran."""
    for error in facts.get("errors") or []:
        if str(error).startswith(f"{step}: "):
            return str(error)[len(step) + 2:]
    return facts.get("error")
