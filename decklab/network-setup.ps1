<#
Deck Lab's one administrator step: let phones and the iPad on the home network
reach Deck Lab, and nothing more.

HOW TO RUN IT
  1. Set up the "Deck Lab" task first, from a normal PowerShell in the repo folder:

         python -m decklab.lib.homenet install

     This script reads from that task which pythonw.exe runs Deck Lab. It
     never runs Python, or any other program, to find out: it runs as
     administrator, and a program found on the PATH would then run with
     those rights.
  2. Open PowerShell with "Run as administrator" (right-click PowerShell in
     the Start menu), go to the repo folder, and run:

         powershell -ExecutionPolicy Bypass -File decklab\network-setup.ps1

     Only run it at home: it tells Windows to trust the network the PC is on.
     If Windows treats that network as Public, the script names it and asks
     before making it Private.

  Options:
      -DryRun             Only show what it would do. Needs no administrator.
      -PythonPrivateOnly  Also take Public networks off Python's own firewall
                          rules (the ones Windows' "allow this app" prompt
                          made), so Python can't take connections on Public
                          networks (cafe or hotel Wi-Fi). Nothing else in them
                          changes; a rule that was for Public networks only is
                          turned off instead.
      -Pythonw <path>     The pythonw.exe that runs Deck Lab, when the "Deck Lab"
                          task isn't set up (python -m decklab.lib.homenet
                          status names it).
      -Yes                Make the network Private without asking (for a
                          PowerShell that can't ask, such as one started
                          with -NonInteractive). Only at home.

WHAT IT DOES, IN ORDER
  1. Network: the home network is the one on the physical network adapter
     (cable or Wi-Fi) that is up and has the internet route; VPN and virtual
     adapters are left alone. If Windows treats that network as Public, it
     names the network and, once you say it's your home network (or with
     -Yes), sets it to Private. Windows blocks phones on Public networks.
  2. Deck Lab's firewall rules: makes sure these two inbound rules exist,
     both for Private networks and for devices on the home network only
     ("LocalSubnet"):
        "Deck Lab (TCP 8642)"  lets the page's port in (the port comes from
                               decklab\config.json; 8642 if it doesn't say)
        "Deck Lab (pythonw)"   lets the pythonw.exe that runs Deck Lab in the
                               background take connections on that port, so
                               Windows never asks about it. (Pressing Cancel on
                               that question adds a rule that BLOCKS it.) Only
                               when it knows which pythonw.exe that is.
     It adds the missing ones first, then removes the other ALLOW rules it
     would have made: ones with those two names (for example one open on
     every kind of network) or with its own description ("Added by
     decklab\network-setup.ps1"). Any other rule whose name starts with
     "Deck Lab (" is listed and left alone.
  3. Removes BLOCK rules that Windows' "allow this app" prompt made for that
     Python's python.exe or pythonw.exe. Block rules beat allow rules.
  4. Lists that Python's ALLOW rules that also apply to Public networks. With
     -PythonPrivateOnly it takes Public networks off them.

  It never touches other programs' rules, never opens anything on Public or
  Domain networks, and is safe to run again: a second run finds everything
  right and changes nothing.

  Afterwards, check from a normal PowerShell or command prompt with:
      python -m decklab.lib.homenet status

  Never forward the port on the router: Deck Lab has no login.
#>
param(
    [switch]$DryRun,
    [switch]$PythonPrivateOnly,
    [string]$Pythonw,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$changes = 0
$scriptName = 'decklab\network-setup.ps1'
# The start of the description of every rule this script makes. With the two
# rule names, it's how the script tells its own rules from anyone else's.
$marker = "Added by $scriptName"

# Prints what was done, or with -DryRun what would be done, and counts it.
function Change([string]$text) {
    if ($DryRun) { Write-Host "  Would: $text" } else { Write-Host "  Done:  $text" }
    $script:changes++
}

# A path in one form for comparing: variables expanded, full, lower case.
function Normalize-Path([string]$path) {
    if (-not $path) { return '' }
    $expanded = [Environment]::ExpandEnvironmentVariables($path.Trim().Trim('"'))
    try { $expanded = [IO.Path]::GetFullPath($expanded) } catch { }
    return $expanded.ToLowerInvariant()
}

# A firewall rule with what its filters say: ports, addresses, program,
# interface types and interfaces.
function Describe-Rule($rule) {
    $ports = $rule | Get-NetFirewallPortFilter
    $addresses = $rule | Get-NetFirewallAddressFilter
    $app = $rule | Get-NetFirewallApplicationFilter
    $types = $rule | Get-NetFirewallInterfaceTypeFilter
    $interfaces = $rule | Get-NetFirewallInterfaceFilter
    [pscustomobject]@{
        Rule          = $rule
        Name          = $rule.Name
        DisplayName   = $rule.DisplayName
        Description   = [string]$rule.Description
        Direction     = [string]$rule.Direction
        Enabled       = [string]$rule.Enabled
        Action        = [string]$rule.Action
        Profile       = [string]$rule.Profile
        Protocol      = [string]$ports.Protocol
        LocalPort     = (@($ports.LocalPort) -join ',')
        Remote        = (@($addresses.RemoteAddress) -join ',')
        Local         = (@($addresses.LocalAddress) -join ',')
        InterfaceType = [string]$types.InterfaceType
        Interfaces    = (@($interfaces.InterfaceAlias) -join ',')
        Program       = [string]$app.Program
    }
}

# One line about a rule: its name, what it lets in or blocks, and where.
function Show-Rule($r) {
    $ports = if ($r.LocalPort -eq 'Any') { 'every port' } else { "port $($r.LocalPort)" }
    $profileNames = @($r.Profile -split ', ')
    $networks = if ($r.Profile -eq 'Any') { 'every kind of network' }
                elseif ($profileNames.Count -gt 1) { "$($profileNames[0..($profileNames.Count - 2)] -join ', ') and $($profileNames[-1]) networks" }
                else { "$($r.Profile) networks" }
    $from = if ($r.Remote -eq 'Any') { 'any address' } elseif ($r.Remote -eq 'LocalSubnet') { 'the home network only (LocalSubnet)' } else { $r.Remote }
    $what = "$($r.Action) $($r.Protocol) $ports, on $networks, from $from"
    if ($r.Local -and $r.Local -ne 'Any') { $what += ", to $($r.Local) only" }
    if ($r.InterfaceType -and $r.InterfaceType -ne 'Any') { $what += ", on $($r.InterfaceType) connections only" }
    if ($r.Interfaces -and $r.Interfaces -ne 'Any') { $what += ", on $($r.Interfaces) only" }
    if ($r.Program -and $r.Program -ne 'Any') { $what += ", for $($r.Program)" }
    if ($r.Direction -and $r.Direction -ne 'Inbound') { $what += " ($($r.Direction.ToLower()))" }
    if ($r.Enabled -ne 'True') { $what += ' (turned off)' }
    return "'$($r.DisplayName)': $what"
}

# --- Before anything: administrator? ---------------------------------------

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$repo = Split-Path -Parent $PSScriptRoot

if (-not $isAdmin -and -not $DryRun) {
    # The command to run again keeps the options given, so -PythonPrivateOnly isn't lost on the way.
    $again = "powershell -ExecutionPolicy Bypass -File $scriptName"
    if ($PythonPrivateOnly) { $again += ' -PythonPrivateOnly' }
    if ($Pythonw) { $again += " -Pythonw `"$Pythonw`"" }
    if ($Yes) { $again += ' -Yes' }
    Write-Host "This script changes the firewall and the network setting, which needs administrator."
    Write-Host "Nothing was changed."
    Write-Host ""
    Write-Host "Open PowerShell with 'Run as administrator' (right-click PowerShell in the Start menu), then:"
    Write-Host "    cd `"$repo`""
    Write-Host "    $again"
    Write-Host ""
    Write-Host "To only see what it would do (no administrator needed), add -DryRun."
    exit 1
}

if ($DryRun) {
    Write-Host "Dry run: nothing is changed; each 'Would:' line is what a real run would do."
    if (-not $isAdmin) { Write-Host "(Not running as administrator, which a real run needs.)" }
    Write-Host ""
}

try {
    # --- The port, from decklab\config.json (8642 if it doesn't say) -------

    $port = 8642
    $configFile = Join-Path $PSScriptRoot 'config.json'
    if (Test-Path $configFile) {
        $settings = Get-Content -Raw -Encoding UTF8 $configFile | ConvertFrom-Json
        if ($null -ne $settings.port) { $port = [int]$settings.port }
    }
    if ($port -lt 1 -or $port -gt 65535) { throw "the port in decklab\config.json ($port) isn't a port number" }
    $portRuleName = "Deck Lab (TCP $port)"
    $pythonwRuleName = 'Deck Lab (pythonw)'
    Write-Host "Deck Lab's port: $port"

    # --- Which pythonw.exe runs Deck Lab ------------------------------------
    # The one the "Deck Lab" task starts, or -Pythonw. Nothing is run to
    # find it: this script runs as administrator, so running "python" from the
    # PATH would run whatever is first there with administrator rights.

    $pythonwFrom = 'the -Pythonw option'
    if (-not $Pythonw) {
        $task = Get-ScheduledTask -TaskPath '\' -TaskName 'Deck Lab' -ErrorAction SilentlyContinue
        if ($task -and @($task.Actions).Count -gt 0 -and $task.Actions[0].Execute) {
            $Pythonw = [Environment]::ExpandEnvironmentVariables(([string]$task.Actions[0].Execute).Trim().Trim('"'))
            $pythonwFrom = 'the Deck Lab task'
        }
    }
    if ($Pythonw -and -not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
        Write-Host "The pythonw.exe from $pythonwFrom isn't there: $Pythonw"
        if ($pythonwFrom -eq 'the Deck Lab task') {
            Write-Host "(Was Python upgraded or moved? Then run 'python -m decklab.lib.homenet install' again.)"
        }
        $Pythonw = $null
    }
    if ($Pythonw) {
        $Pythonw = [IO.Path]::GetFullPath($Pythonw)
        Write-Host "The pythonw.exe that runs Deck Lab: $Pythonw (from $pythonwFrom)"
    } else {
        Write-Host "It isn't known which pythonw.exe runs Deck Lab, so the '$pythonwRuleName' rule and steps 3"
        Write-Host "and 4 are skipped, and any '$pythonwRuleName' rule there is now is left as it is. To include them:"
        Write-Host "  - run 'python -m decklab.lib.homenet install' first (from a normal PowerShell), then this again; or"
        Write-Host "  - run this again with -Pythonw <path to pythonw.exe> (python -m decklab.lib.homenet status names it)."
    }
    Write-Host ""

    # --- 1. The network: Private, not Public --------------------------------
    # The home network is on a physical adapter (cable or Wi-Fi) that is up
    # and has the internet route now (ActiveStore). A VPN often has a lower
    # metric, but phones don't come in through it, and making a VPN or a
    # virtual adapter Private would trust whatever is behind it. "Physical"
    # is the adapter's Virtual flag, hidden adapters included, the same test
    # homenet status uses (Get-NetAdapter -Physical leaves out hidden ones,
    # and a Wi-Fi card can show up as a hidden adapter).

    Write-Host "1. The network"
    $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -PolicyStore ActiveStore -ErrorAction SilentlyContinue)
    $physical = @(Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue |
                  Where-Object { -not $_.Virtual -and [string]$_.Status -eq 'Up' })
    $best = $null
    $bestMetric = [int]::MaxValue
    foreach ($route in $routes) {
        $adapter = @($physical | Where-Object { $_.ifIndex -eq $route.ifIndex })[0]
        if (-not $adapter) {
            $other = Get-NetAdapter -InterfaceIndex $route.ifIndex -IncludeHidden -ErrorAction SilentlyContinue
            $which = if ($other) { "'$($other.Name)' ($($other.InterfaceDescription))" } else { "Interface $($route.ifIndex)" }
            Write-Host "  Left alone: $which has an internet route, but it's a VPN or virtual adapter (or isn't up), not the home network's cable or Wi-Fi."
            continue
        }
        $ipInterface = Get-NetIPInterface -InterfaceIndex $route.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
        if (-not $ipInterface) { continue }
        $metric = [int]$route.RouteMetric + [int]$ipInterface.InterfaceMetric
        if ($metric -lt $bestMetric) { $best = $route; $bestMetric = $metric }
    }
    if (-not $best) {
        if ($routes.Count -gt 0) {
            Write-Host "  No physical network adapter (cable or Wi-Fi) that's up has the internet route, so this step is skipped."
            Write-Host "  If the home network comes through an adapter above (a Hyper-V switch, say), set it to Private in"
            Write-Host "  Settings > Network & internet."
        } else {
            Write-Host "  No network connection with an internet route was found, so this step is skipped."
        }
    } else {
        $connection = @(Get-NetConnectionProfile -InterfaceIndex $best.ifIndex -ErrorAction SilentlyContinue)[0]
        if (-not $connection) {
            Write-Host "  Windows has no network profile for '$($best.InterfaceAlias)' yet, so this step is skipped."
        } else {
            $category = [string]$connection.NetworkCategory
            Write-Host "  '$($connection.InterfaceAlias)' is on the network '$($connection.Name)', set to $category."
            if ($category -eq 'Public') {
                Write-Host "  That should be your home network: Private tells Windows to trust it, so only do this at home."
                $sure = $DryRun -or $Yes
                if (-not $sure) {
                    try {
                        $answer = Read-Host "  Is '$($connection.Name)' your home network? Type y to set it to Private"
                    } catch {
                        $answer = ''
                        Write-Host "  (This PowerShell can't ask. At home, run it again with -Yes to set it to Private.)"
                    }
                    $sure = "$answer".Trim() -match '^(?i)y(es)?$'
                }
                if ($sure) {
                    if (-not $DryRun) {
                        Set-NetConnectionProfile -InterfaceIndex $best.ifIndex -NetworkCategory Private
                    }
                    Change "set the network '$($connection.Name)' to Private (Windows blocks phones on Public networks)"
                    if ($DryRun -and -not $Yes) { Write-Host "  (A real run asks first, unless it's given -Yes.)" }
                } else {
                    Write-Host "  Left as Public. Phones can't reach Deck Lab on it; run this again at home to change it."
                }
            } elseif ($category -eq 'Private') {
                Write-Host "  Already Private: nothing to do."
            } else {
                Write-Host "  It's a work (domain) network, which Windows doesn't let this script change; Deck Lab's rules cover Private networks only."
            }
        }
    }
    Write-Host ""

    # --- 2. Deck Lab's own firewall rules ------------------------------------
    # Keep a rule that's exactly one of the wanted ones. Add the wanted rules
    # that are missing BEFORE removing anything, so phones aren't shut out if
    # adding fails. Then remove the other Allow rules this script would have
    # made (its two names, or its description). Rules it didn't make are only
    # listed, and so is a pythonw rule while it's unknown which pythonw.exe
    # runs Deck Lab.

    Write-Host "2. Deck Lab's firewall rules"
    $wanted = @(@{ DisplayName = $portRuleName; Program = $null })
    if ($Pythonw) { $wanted += @{ DisplayName = $pythonwRuleName; Program = $Pythonw } }
    $existing = @(Get-NetFirewallRule -DisplayName 'Deck Lab (*' -ErrorAction SilentlyContinue |
                  Where-Object { $_.DisplayName -like 'Deck Lab (*' } | ForEach-Object { Describe-Rule $_ })
    $kept = @{}
    $unwanted = @()
    $others = @()
    foreach ($r in $existing) {
        $match = $null
        foreach ($w in $wanted) {
            if ($kept.ContainsKey($w.DisplayName)) { continue }
            $programOk = if ($w.Program) { (Normalize-Path $r.Program) -eq (Normalize-Path $w.Program) } else { $r.Program -eq 'Any' }
            if ($r.DisplayName -eq $w.DisplayName -and $r.Direction -eq 'Inbound' -and $r.Enabled -eq 'True' -and
                $r.Action -eq 'Allow' -and $r.Profile -eq 'Private' -and $r.Protocol -eq 'TCP' -and
                $r.LocalPort -eq "$port" -and $r.Remote -eq 'LocalSubnet' -and $r.Local -eq 'Any' -and
                $r.InterfaceType -eq 'Any' -and $r.Interfaces -eq 'Any' -and $programOk) { $match = $w; break }
        }
        $madeHere = $r.Direction -eq 'Inbound' -and $r.Action -eq 'Allow' -and
                    ($r.DisplayName -eq $portRuleName -or $r.DisplayName -eq $pythonwRuleName -or $r.Description -like "$marker*")
        # Only a rule for a program can be pythonw's; one named 'Deck Lab
        # (pythonw)' with no program is just another port rule.
        $forPythonw = $r.Program -and $r.Program -ne 'Any'
        if ($match) {
            $kept[$match.DisplayName] = $true
            Write-Host "  Already right: $(Show-Rule $r)"
        } elseif ($madeHere -and $forPythonw -and -not $Pythonw) {
            Write-Host "  Left alone, since it isn't known which pythonw.exe runs Deck Lab: $(Show-Rule $r)"
        } elseif ($madeHere) {
            $unwanted += $r
        } else {
            $others += $r
        }
    }
    foreach ($w in $wanted) {
        if ($kept.ContainsKey($w.DisplayName)) { continue }
        $rule = @{
            DisplayName   = $w.DisplayName
            Direction     = 'Inbound'
            Action        = 'Allow'
            Protocol      = 'TCP'
            LocalPort     = $port
            Profile       = 'Private'
            RemoteAddress = 'LocalSubnet'
            Enabled       = 'True'
            Description   = "$marker so phones on the home network can reach Deck Lab. Private networks and the local subnet only. Run that script again to put it right."
        }
        if ($w.Program) { $rule.Program = $w.Program }
        if (-not $DryRun) { New-NetFirewallRule @rule | Out-Null }
        $for = if ($w.Program) { ", for $($w.Program)" } else { '' }
        Change "add '$($w.DisplayName)': Allow TCP port $port, on Private networks, from the home network only (LocalSubnet)$for"
    }
    foreach ($r in $unwanted) {
        if (-not $DryRun) { Remove-NetFirewallRule -Name $r.Name }
        Change "remove $(Show-Rule $r)"
    }
    foreach ($r in $others) {
        Write-Host "  Left alone, since this script didn't make it: $(Show-Rule $r)"
    }
    Write-Host ""

    # --- 3 and 4. Python's own rules ----------------------------------------
    # Only the rules for this Python's python.exe and pythonw.exe (the folder
    # pythonw.exe is in). Other programs' rules are never looked at.

    if ($Pythonw) {
        $folder = Split-Path -Parent $Pythonw
        $ours = @((Join-Path $folder 'python.exe'), (Join-Path $folder 'pythonw.exe')) | ForEach-Object { Normalize-Path $_ }
        $pythonRules = @(Get-NetFirewallApplicationFilter -All |
                         Where-Object { $ours -contains (Normalize-Path $_.Program) } |
                         Get-NetFirewallRule |
                         Where-Object { [string]$_.Direction -eq 'Inbound' })

        Write-Host "3. Block rules for $folder\python.exe and pythonw.exe"
        $blocks = @($pythonRules | Where-Object { [string]$_.Action -eq 'Block' })
        if ($blocks.Count -eq 0) { Write-Host "  None: nothing to do." }
        foreach ($rule in $blocks) {
            $r = Describe-Rule $rule
            if ($rule.Name -like 'TCP Query User{*' -or $rule.Name -like 'UDP Query User{*') {
                if (-not $DryRun) { Remove-NetFirewallRule -Name $rule.Name }
                Change "remove $(Show-Rule $r) (Windows' prompt made it)"
            } else {
                Write-Host "  Left alone, since Windows' prompt didn't make it: $(Show-Rule $r)"
                Write-Host "  If phones can't connect, delete it in 'Windows Defender Firewall with Advanced Security' > Inbound Rules."
            }
        }
        Write-Host ""

        # Only the Public bit comes off; Domain and Private stay as they were
        # (Any, 0, is Domain, Private and Public). A rule left with no network
        # at all is turned off, since Profile 0 would mean every network.
        Write-Host "4. Python's allow rules that also apply to Public networks"
        $public = @($pythonRules | Where-Object {
            [string]$_.Action -eq 'Allow' -and [string]$_.Enabled -eq 'True' -and
            (([int]$_.Profile -eq 0) -or ([int]$_.Profile -band 4)) })
        if ($public.Count -eq 0) { Write-Host "  None: nothing to do." }
        foreach ($rule in $public) {
            $r = Describe-Rule $rule
            if (-not $PythonPrivateOnly) {
                Write-Host "  $(Show-Rule $r)"
                continue
            }
            $bits = if ([int]$rule.Profile -eq 0) { 7 } else { [int]$rule.Profile }
            $left = $bits -band (-bnot 4) -band 3
            if ($left -eq 0) {
                if (-not $DryRun) { Set-NetFirewallRule -Name $rule.Name -Enabled False }
                Change "turn off $(Show-Rule $r) (it was for Public networks only)"
            } else {
                $names = @()
                if ($left -band 1) { $names += 'Domain' }
                if ($left -band 2) { $names += 'Private' }
                $newProfile = $names -join ', '
                if (-not $DryRun) { Set-NetFirewallRule -Name $rule.Name -Profile $newProfile }
                Change "take Public networks off $(Show-Rule $r) (it then applies to $($names -join ' and ') networks)"
            }
        }
        if ($public.Count -gt 0 -and -not $PythonPrivateOnly) {
            Write-Host "  Left as they are. Run again with -PythonPrivateOnly to take Public networks off them"
            Write-Host "  (Python programs then can't take connections on Public networks, such as cafe Wi-Fi)."
        }
        Write-Host ""
    }
} catch {
    Write-Host ""
    Write-Host "Stopped: $($_.Exception.Message)"
    if ($changes -gt 0 -and -not $DryRun) {
        Write-Host "The changes listed above were made before it stopped. Running the script again is safe."
    }
    exit 1
}

if ($DryRun) {
    if ($changes -eq 0) { Write-Host "Everything is already right: a real run would change nothing." }
    else { Write-Host "A real run would make $changes change(s). Run it as administrator without -DryRun." }
} else {
    if ($changes -eq 0) { Write-Host "Everything was already right: nothing changed." }
    else { Write-Host "Made $changes change(s)." }
    Write-Host "Check with: python -m decklab.lib.homenet status"
}
exit 0
