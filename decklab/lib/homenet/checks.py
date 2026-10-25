"""The status checklist's Network, Firewall, Addresses and Sleep lines, and
the report: pure functions that judge the facts gather_facts found, so
they're tested with canned facts. (The Server and Start at logon lines are
in commands.py, beside the control module they read.)"""
import ipaddress
import ntpath
import re
import textwrap

from .common import (
    OK, PROBLEM, PROFILE_BITS, PROFILES, SETUP_MARKER, SETUP_RULE_NAMES, SETUP_RUN, WARN, _int, line, norm_path,
)


# ------------------------------------------------------------ status: judging (pure)

def _category(value):
    """A network category as a word: Public, Private or DomainAuthenticated."""
    names = {"0": "Public", "1": "Private", "2": "DomainAuthenticated"}
    text = str(value) if value is not None else ""
    return names.get(text, text)


def _origin(value):
    """An address's PrefixOrigin as a word (Dhcp, Manual, ...)."""
    names = {"0": "Other", "1": "Manual", "2": "WellKnown", "3": "Dhcp", "4": "RouterAdvertisement"}
    text = str(value) if value is not None else ""
    return names.get(text, text)


def _physical_up(interface):
    """True unless the adapter is known to be virtual (a VPN, Hyper-V, WSL)
    or not up. network-setup.ps1 uses the same test (the Virtual flag,
    hidden adapters included), so the two pick the same network."""
    status = str(interface.get("status") or "Up")
    return status.lower() == "up" and interface.get("virtual") is not True


def pick_interface(network):
    """The home network's interface: of those carrying an IPv4 default
    route, the lowest-metric physical adapter that's up (a full-tunnel VPN
    usually has a lower metric, but phones don't come in through it), else
    the lowest-metric one (a Hyper-V switch can carry the home network).
    Its usable IPv4 address is "address" (None when it has none), and its
    route's next hop "gateway". None when no interface has a route."""
    if not isinstance(network, dict):
        return None
    interfaces = {_int(i.get("if_index")): i for i in network.get("interfaces") or [] if isinstance(i, dict)}
    routes = sorted((r for r in network.get("routes") or [] if isinstance(r, dict)
                     and _int(r.get("if_index")) in interfaces),
                    key=lambda r: (not _physical_up(interfaces[_int(r.get("if_index"))]),
                                   _int(r.get("metric"), 1 << 30)))
    for route in routes:
        chosen = dict(interfaces[_int(route["if_index"])])
        addresses = [a for a in chosen.get("ipv4") or [] if isinstance(a, dict) and a.get("address")
                     and not str(a["address"]).startswith("169.254.")]
        chosen["address"] = addresses[0] if addresses else None
        chosen["gateway"] = route.get("next_hop")
        return chosen
    return None


def check_network(network, error=None):
    """The Network lines: the connection with the default route and its
    category (Public blocks phones)."""
    area = "Network"
    setup = (f"Run {SETUP_RUN} in an administrator PowerShell, at home: it names the network and asks "
             "before setting it to Private.")
    if network is None and error:
        return [line(WARN, area, f"Couldn't check the network: {error}")]
    chosen = pick_interface(network)
    if chosen is None:
        return [line(PROBLEM, area, "No network connection with a default route (is the cable in?).")]
    address = chosen.get("address")
    if address is None:
        return [line(PROBLEM, area, f"{chosen.get('alias') or 'The connection'} has no IPv4 address yet.",
                     "Check the cable or Wi-Fi, and that the router is on.")]
    origin = _origin(address.get("origin"))
    how = "from the router (DHCP)" if origin.lower() == "dhcp" else "set by hand" if origin.lower() == "manual" \
        else f"({origin})"
    name = chosen.get("alias") or "The connection"
    category = _category(chosen.get("category"))
    where = (f"{name}" + (f" ({chosen['description']})" if chosen.get("description") else "")
             + f": {address['address']}/{address.get('prefix')} {how}")
    if category == "Private":
        return [line(OK, area, f"{where}, on a Private network.")]
    if category == "Public":
        return [line(PROBLEM, area, f"{where}. Windows treats this network ('{chosen.get('network_name')}') "
                                    "as Public, which blocks phones.", setup)]
    if category == "DomainAuthenticated":
        return [line(WARN, area, f"{where}, on a work (domain) network: Deck Lab's firewall rule covers "
                                 "Private networks only.")]
    return [line(WARN, area, f"{where}; Windows didn't say whether the network is Private or Public.")]


def profile_set(value):
    """A firewall rule's profiles as a set of "domain", "private", "public",
    from any form PowerShell gives: a number (the COM object's bit mask, all
    = 0x7FFFFFFF; NetSecurity's flags, Any = 0), or text like "Any",
    "Private" or "Private, Public"."""
    if value is None or isinstance(value, bool):
        return set()
    if isinstance(value, (list, tuple)):
        return set().union(*(profile_set(v) for v in value)) if value else set()
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        number = int(text)
        if number == 0 or number < 0 or number & 0x7 == 0x7:
            return set(PROFILES)
        return {name for name, bit in PROFILE_BITS.items() if number & bit}
    words = {w for w in re.split(r"[\s,|;]+", text.lower()) if w}
    if words & {"any", "all"}:
        return set(PROFILES)
    return words & set(PROFILES)


def _profiles_text(profiles):
    names = [p.capitalize() for p in PROFILES if p in profiles]
    if set(profiles) >= set(PROFILES):
        return "every kind of network (Domain, Private and Public)"
    if len(names) == 1:
        return f"{names[0]} networks"
    return f"{', '.join(names[:-1])} and {names[-1]} networks"


def protocol_name(value):
    """A rule's protocol as "tcp", "udp", "any" or the text it was."""
    text = str(value if value is not None else "").strip().lower()
    return {"6": "tcp", "17": "udp", "256": "any", "": "any", "*": "any"}.get(text, text)


def port_covered(local_ports, port):
    """True when a rule's local ports (COM text like "8642", "8000-9000,80"
    or "*"; or NetSecurity's list) include port. Keywords like RPC don't."""
    if local_ports is None:
        return True
    parts = local_ports if isinstance(local_ports, (list, tuple)) else str(local_ports).split(",")
    parts = [str(p).strip() for p in parts if str(p).strip()]
    if not parts:
        return True
    for part in parts:
        if part.lower() in ("*", "any"):
            return True
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if match and int(match[1]) <= port <= int(match[2]):
            return True
        if part.isdigit() and int(part) == port:
            return True
    return False


def all_ports(local_ports):
    """True when a rule covers every port ("*", "Any" or nothing)."""
    return port_covered(local_ports, -1)


def _address_parts(addresses):
    """A rule's address list (COM text like "LocalSubnet,10.0.0.1-10.0.0.9",
    or a list) as lower-case entries."""
    if addresses is None:
        return []
    parts = addresses if isinstance(addresses, (list, tuple)) else str(addresses).split(",")
    return [str(p).strip().lower() for p in parts if str(p).strip()]


def remote_any(remote):
    """True when a rule takes connections from any address."""
    parts = _address_parts(remote)
    return not parts or any(p in ("*", "any") for p in parts)


def _ipv4_span(entry):
    """(first, last) as numbers for one IPv4 entry of a rule's addresses
    ("192.168.0.5", "192.168.0.0/24", "192.168.0.0/255.255.255.0",
    "10.0.0.1-10.0.0.9"); None for a keyword, IPv6 or anything else."""
    try:
        if "-" in entry:
            first, last = (ipaddress.IPv4Address(p.strip()) for p in entry.split("-", 1))
            return int(first), int(last)
        network = ipaddress.IPv4Network(entry.strip(), strict=False)
        return int(network.network_address), int(network.broadcast_address)
    except ValueError:
        return None


def lan_of(network):
    """The home network as status's firewall check needs it, from the facts'
    network (pick_interface): {"address": "192.0.2.10", "subnet": an
    IPv4Network, "kind": "lan", "wireless", "remoteaccess" or None}, or None
    when there's no address."""
    chosen = pick_interface(network)
    address = (chosen or {}).get("address")
    if not address:
        return None
    try:
        subnet = ipaddress.IPv4Network(f"{address['address']}/{_int(address.get('prefix'), 32)}", strict=False)
    except ValueError:
        return None
    # The firewall's interface types: Wireless is Wi-Fi (IANA type 71),
    # RemoteAccess is dial-up and VPN (PPP 23, tunnel 131), Lan the rest.
    if_type = _int(chosen.get("if_type"))
    kind = None if if_type is None else {71: "wireless", 23: "remoteaccess", 131: "remoteaccess"}.get(if_type, "lan")
    return {"address": address["address"], "subnet": subnet, "kind": kind}


def scope_gaps(rule, lan):
    """How a rule's scope may leave phones on the home network out, as
    phrases ([] when it takes them all in): remote addresses that aren't
    any, LocalSubnet or the whole subnet; local addresses without the PC's
    address; interface types without the home network's. With lan None
    (unknown), only scopes that take in everything count."""
    gaps = []
    remote = _address_parts(rule.get("remote_addresses"))
    if not remote_any(remote) and "localsubnet" not in remote:
        spans = sorted(span for span in map(_ipv4_span, remote) if span)
        needed = None
        if lan:
            subnet = lan["subnet"]
            first, last = int(subnet.network_address), int(subnet.broadcast_address)
            needed = (first + 1, last - 1) if subnet.prefixlen <= 30 else (first, last)
        if not (needed and _spans_cover(spans, *needed)):
            gaps.append(f"only from {rule.get('remote_addresses')}")
    local = _address_parts(rule.get("local_addresses"))
    if not remote_any(local):
        mine = int(ipaddress.IPv4Address(lan["address"])) if lan else None
        if mine is None or not any(span and span[0] <= mine <= span[1] for span in map(_ipv4_span, local)):
            gaps.append(f"only to {rule.get('local_addresses')}")
    types = {t.strip().lower() for t in str(rule.get("interface_types") or "").split(",") if t.strip()}
    kind = (lan or {}).get("kind")
    if types and "all" not in types and "any" not in types and kind not in types:
        gaps.append(f"only on {rule.get('interface_types')} connections")
    return gaps


def _spans_cover(spans, first, last):
    """True when the (sorted) spans together cover first..last."""
    need = first
    for start, end in spans:
        if start > need:
            break
        need = max(need, end + 1)
        if need > last:
            return True
    return need > last


def _rule_program(rule):
    program = str(rule.get("program") or "").strip()
    return None if program.lower() in ("", "*", "any") else norm_path(program)


def _rule_service_any(rule):
    return str(rule.get("service") or "").strip().lower() in ("", "*", "any")


def _enabled(rule):
    value = rule.get("enabled")
    return value is True or str(value).strip().lower() in ("true", "1")


def _action(rule):
    """ "allow" or "block" (COM: 1 / 0; NetSecurity: Allow / Block, or 2 / 4)."""
    text = str(rule.get("action")).strip().lower()
    return {"1": "allow", "2": "allow", "allow": "allow", "0": "block", "4": "block", "block": "block"}.get(text, text)


def _opens(rule, port):
    """True when an enabled rule covers TCP port for some program."""
    return (_enabled(rule) and protocol_name(rule.get("protocol")) in ("tcp", "any")
            and port_covered(rule.get("local_ports"), port))


def made_by_setup(rule, port):
    """True for a rule network-setup.ps1 made, and so puts right: one of its
    two names, or its description."""
    names = [name.format(port=port).lower() for name in SETUP_RULE_NAMES]
    return (str(rule.get("name") or "").lower() in names
            or str(rule.get("description") or "").lower().startswith(SETUP_MARKER.lower()))


def check_firewall(firewall, port, server_programs, python_programs, error=None, lan=None):
    """The Firewall lines, from the inbound rules gathered (Python's, the
    port's, and every-program rules), the profiles, the programs the server
    runs as (server_programs: the running server's Python, the task's
    pythonw.exe), this Python's python.exe and pythonw.exe (python_programs;
    paths, any form) and the home network (lan_of; None when unknown)."""
    area = "Firewall"
    setup = f"Run {SETUP_RUN} in an administrator PowerShell."
    manual = ("Check it in Windows Defender Firewall with Advanced Security > Inbound Rules; "
              "network-setup.ps1 doesn't touch rules it didn't make.")
    if firewall is None:
        return [line(WARN, area, f"Couldn't read the firewall: {error or 'no answer'}")]
    rules = [r for r in firewall.get("rules") or [] if isinstance(r, dict)]
    servers = [norm_path(p) for p in server_programs if p]
    servers = list(dict.fromkeys(servers))
    pythons = set(norm_path(p) for p in python_programs if p) | set(servers)
    profiles = {str(p.get("name", "")).lower(): p for p in firewall.get("profiles") or [] if isinstance(p, dict)}
    private_off = profiles.get("private", {}).get("enabled") is False
    out = []

    def applies(rule, program):
        prog = _rule_program(rule)
        return _rule_service_any(rule) and (prog is None or prog == program)

    # 1. Something must let TCP <port> in on Private networks from the home
    #    network, for each program the server runs as. A rule whose
    #    addresses or interface types may leave phones out is "partial".
    covering, partial = {}, {}
    for program in servers:
        allowed = [r for r in rules if _action(r) == "allow" and _opens(r, port)
                   and applies(r, program) and "private" in profile_set(r.get("profiles"))]
        covering[program] = [r for r in allowed if not scope_gaps(r, lan)]
        partial[program] = [r for r in allowed if scope_gaps(r, lan)]
    missing = [p for p in servers if not covering[p]]
    uncovered = [p for p in missing if not partial[p]]
    if uncovered:
        leaves = ", ".join(ntpath.basename(p) for p in uncovered)
        if private_off:
            out.append(line(WARN, area, f"No rule lets TCP {port} in on Private networks for {leaves}; "
                                        "phones only get in because the Private firewall is off.", setup))
        else:
            out.append(line(PROBLEM, area, f"No firewall rule lets phones reach TCP {port} on Private networks "
                                           f"(for {leaves}).", setup))

    # Each partial rule, with the programs it's the only hope for: a
    # program's own rule covers that program alone.
    unsure = {}
    for program in missing:
        for rule in partial[program]:
            unsure.setdefault(id(rule), (rule, []))[1].append(program)
    for rule, programs in unsure.values():
        leaves = ", ".join(ntpath.basename(p) for p in programs)
        out.append(line(WARN, area, f"Rule '{rule.get('name')}' lets TCP {port} in on Private networks for "
                                    f"{leaves}, but {' and '.join(scope_gaps(rule, lan))}, so it may not "
                                    "let phones on the home network in.",
                        setup + " It adds Deck Lab's own rules, for the whole home network."))
    if not missing:
        names = list(dict.fromkeys(r.get("name") or "?" for p in servers for r in covering[p]))
        out.append(line(OK, area, f"TCP {port} is let in on Private networks (rule "
                                  + ", ".join(f"'{n}'" for n in names[:3]) + ")."))

    # 2. Block rules beat allow rules.
    for rule in rules:
        if _action(rule) != "block" or not _enabled(rule):
            continue
        prog = _rule_program(rule)
        if not _rule_service_any(rule):
            continue
        if prog is not None and prog not in pythons:
            continue
        if prog is None and not _opens(rule, port):
            continue
        if prog is not None and not (protocol_name(rule.get("protocol")) in ("tcp", "any")
                                     and port_covered(rule.get("local_ports"), port)):
            continue
        rule_profiles = profile_set(rule.get("profiles"))
        who = ntpath.basename(prog) if prog else f"TCP {port}"
        text = (f"Rule '{rule.get('name')}' blocks {who} on {_profiles_text(rule_profiles)}. "
                "Block rules beat allow rules")
        fix = (f"{setup} It removes the block rules Windows' \"allow this app\" prompt made; if this one "
               "is still there after that, delete it in Windows Defender Firewall with Advanced Security "
               "> Inbound Rules.")
        if "private" in rule_profiles:
            out.append(line(PROBLEM, area, text + ", so phones can't connect.", fix))
        else:
            out.append(line(WARN, area, text + " (it doesn't apply to Private networks, so it doesn't "
                                               "block phones at home).", fix))

    # 3. Allow rules wider than needed: the port open on Public or Domain
    #    networks or to any address, or this Python's ports open on Public
    #    networks (what network-setup.ps1 -PythonPrivateOnly takes off).
    #    Windows' prompt makes Python's rules open to any address even on
    #    Private networks, and may tick Domain too; that's left alone.
    for rule in rules:
        if _action(rule) != "allow" or not _enabled(rule) or not _rule_service_any(rule):
            continue
        prog = _rule_program(rule)
        rule_profiles = profile_set(rule.get("profiles"))
        wide = rule_profiles & {"public", "domain"}
        if prog is not None and prog in pythons:
            if "public" not in rule_profiles:
                continue
            protocol = protocol_name(rule.get("protocol"))
            if protocol not in ("tcp", "udp", "any"):
                continue
            if all_ports(rule.get("local_ports")):
                ports = f"every {protocol.upper() + ' ' if protocol != 'any' else ''}port"
            elif protocol in ("tcp", "any") and port_covered(rule.get("local_ports"), port):
                ports = f"TCP {port}"
            else:
                continue                # other ports only: not Deck Lab's business
            out.append(line(WARN, area, f"Rule '{rule.get('name')}' lets {ports} in for {ntpath.basename(prog)} "
                                        f"on {_profiles_text(rule_profiles)}"
                                        + (", from any address" if remote_any(rule.get("remote_addresses")) else "")
                                        + ": wider than Deck Lab needs.",
                            f"Run {SETUP_RUN} -PythonPrivateOnly in an administrator PowerShell; it takes "
                            "Public networks off Python's rules (and turns off one left with none)."))
        elif prog is None and _opens(rule, port):
            open_any = remote_any(rule.get("remote_addresses"))
            if not wide and not open_any:
                continue
            everything = all_ports(rule.get("local_ports"))
            what = "every port, for every program," if everything else f"TCP {port}"
            reasons = [f"on {_profiles_text(rule_profiles)}"] + (["from any address"] if open_any else [])
            # The script removes any Allow rule with its names or description,
            # whatever ports it opens.
            fix = (setup + " It replaces the Deck Lab rules with ones for Private networks and the home "
                   "network only." if made_by_setup(rule, port) else manual)
            out.append(line(WARN, area, f"Rule '{rule.get('name')}' lets {what} in "
                                        + ", ".join(reasons) + ": wider than Deck Lab needs.", fix))

    # 4. The task's pythonw.exe with no rule that lets the port in on
    #    Private networks: Windows may ask whether to allow it the first
    #    time it listens, and Cancel there adds block rules. A port rule is
    #    enough to stop the question (seen on 2026-10-01: the real server on
    #    8642 raised none, a test server on an uncovered port did).
    for program in servers:
        if ntpath.basename(program) != "pythonw.exe" or covering[program] or partial[program]:
            continue
        if not any(_rule_program(r) == program and _action(r) == "allow" and _enabled(r) for r in rules):
            out.append(line(WARN, area, "pythonw.exe (which runs Deck Lab in the background) has no firewall "
                                        "rule of its own, so Windows may ask whether to allow it the first time "
                                        "it starts. Choose Allow on private networks; Cancel adds a rule that "
                                        "blocks it.", setup + " It adds 'Deck Lab (pythonw)'."))

    # 5. Firewall profiles.
    for name in PROFILES:
        profile = profiles.get(name)
        if not profile:
            continue
        if profile.get("enabled") is False:
            out.append(line(WARN, area, f"The firewall is turned off for {name.capitalize()} networks.",
                            "Turn it back on in Windows Security > Firewall & network protection."))
        elif name == "private" and profile.get("block_all"):
            out.append(line(PROBLEM, area, "\"Block all incoming connections\" is on for Private networks, "
                                           "which blocks phones whatever the rules say.",
                            "Turn it off in Windows Security > Firewall & network protection > Private network."))
    return out


def check_addresses(network, hostname, mdns, port):
    """The Addresses lines: the URLs for phones, whether <pc>.local
    answered, and the DHCP reservation reminder."""
    area = "Addresses"
    chosen = pick_interface(network)
    address = (chosen or {}).get("address")
    host = f"{hostname.lower()}.local"
    out = []
    if address:
        out.append(line(OK, area, f"From a phone or the iPad: http://{address['address']}:{port}/"))
    if mdns.get("answered"):
        mine = address and address["address"] in mdns.get("addresses", [])
        if mine or not address:
            out.append(line(OK, area, f"Or by name: http://{host}:{port}/ (the PC answers to {host}, "
                                      "which iPhones and iPads understand; some Android phones don't)."))
        else:
            out.append(line(WARN, area, f"The PC answers to {host} with {', '.join(mdns['addresses'])}, "
                                        f"not {address['address']}, so the name may lead phones elsewhere.",
                            "Use the IP address on phones."))
    else:
        reason = f" ({mdns['error']})" if mdns.get("error") else ""
        out.append(line(WARN, area, f"The PC didn't answer to {host} within a second{reason}, so phones may "
                                    "not find it by name.", "Use the IP address on phones."))
    if address and _origin(address.get("origin")).lower() == "dhcp":
        mac = (chosen or {}).get("mac") or "the adapter's MAC address"
        out.append(line(OK, area, f"The address came from the router (DHCP), so it can change. Unless it's "
                                  f"already done, reserve {address['address']} for this PC in the router "
                                  f"(MAC address {mac}) on the router's page, "
                                  f"http://{(chosen or {}).get('gateway') or '192.168.0.1'}/ (usually "
                                  "under DHCP Server > Address Reservation). "
                                  "status can't tell whether it's reserved."))
    return out


def parse_powercfg(text):
    """(AC seconds, DC seconds) from powercfg /q's output for one setting.
    The labels are translated in other languages, but the two current values
    are always its last two hex numbers, AC first. None if there aren't two."""
    numbers = re.findall(r"0x([0-9a-fA-F]+)", text or "")
    if len(numbers) < 2:
        return None
    return int(numbers[-2], 16), int(numbers[-1], 16)


def check_sleep(power_text, error=None):
    area = "Sleep"
    values = parse_powercfg(power_text)
    if values is None:
        return [line(WARN, area, f"Couldn't read the sleep setting{': ' + error if error else ''}.")]
    ac = values[0]
    if ac == 0:
        return [line(OK, area, "The PC never sleeps on mains power, so the page stays up.")]
    minutes = ac / 60
    shown = f"{minutes:g} minute{'s' * (minutes != 1)}" if ac % 60 == 0 else f"{ac} seconds"
    return [line(WARN, area, f"The PC sleeps after {shown} on mains power, and the page stops while it sleeps.",
                 "Settings > System > Power > Screen and sleep: set \"When plugged in, put my device to "
                 "sleep after\" to Never.")]


def exit_code(lines):
    return 1 if any(item["level"] == PROBLEM for item in lines) else 0


def format_report(lines, width=100, header=None, footer=None):
    """The checklist as text: one entry per line, its fix indented below."""
    out = [header, ""] if header else []
    for item in lines:
        tag = f"{item['level']:<8}"
        text = textwrap.fill(f"{item['area']}: {item['text']}", width=width, initial_indent=tag,
                             subsequent_indent=" " * 8)
        out.append(text)
        if item.get("fix"):
            out.append(textwrap.fill(f"Fix: {item['fix']}", width=width, initial_indent=" " * 8,
                                     subsequent_indent=" " * 13))
    problems = sum(item["level"] == PROBLEM for item in lines)
    warnings = sum(item["level"] == WARN for item in lines)
    out += ["", f"{problems} problem{'s' * (problems != 1)}, {warnings} warning{'s' * (warnings != 1)}."]
    if footer:
        out.append(textwrap.fill(footer, width=width))
    return "\n".join(out)
