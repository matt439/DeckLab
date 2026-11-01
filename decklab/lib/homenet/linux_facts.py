"""What homenet status reads on Linux (service.status), the counterpart of gather.py's
PowerShell: the network with the default route and its addresses (iproute2's
`ip -j`), and the firewall (firewalld, ufw or nftables), each from unprivileged
reads only. A step that can't be read gives its reason in errors, never a guess:
status then says it couldn't check (checks.py judges these facts).

    read_facts(port) -> {"network": {...} or None, "firewall": {...} or None,
                     "errors": {"network": why, "firewall": why}}

"network" has the shape checks.pick_interface reads (as Windows' facts do):
{"interfaces": [{"if_index", "alias", "status", "virtual", "mac", "ipv4":
[{"address", "prefix", "origin"}]}], "routes": [{"if_index", "metric",
"next_hop"}]}. An interface is virtual when /sys/class/net/<name> has no device
(a bridge, a VPN's tun, a container's veth); an address is Dhcp when ip calls it
dynamic, else Manual.

"firewall" is {"active": ["firewalld", "ufw", "nftables"] as running, "zone":
firewalld's zone for the interface, "port": True/False/None (firewalld lets the
port in), "mdns": True/False/None}. ufw counts as running when /etc/ufw/ufw.conf
says ENABLED=yes (its service is active even when ufw is off); its rules, like
nftables', need root to read, so they aren't.

Tests pass run (a fake of systemd._run: (exit code, stdout, stderr)) and root (a
folder of canned /sys and /etc files).
"""
import json
import re
from pathlib import Path

from decklab.lib import systemd

TIMEOUT = 5                 # seconds for one command
FIREWALLS = ("firewalld", "ufw", "nftables")


def short_name(hostname):
    """A PC's name as avahi announces it: the first label of a full name (box.home.arpa: box)."""
    return str(hostname or "").split(".", 1)[0] or str(hostname or "")


def _run(args, run=None):
    return (run or systemd._run)(args, timeout=TIMEOUT)


def _said(code, out, err):
    return " ".join((err or out or "").split())[:200] or f"exit code {code}"


def network(run=None, root=None):
    """(the network dict, None), or (None, why it couldn't be read)."""
    root = Path(root or "/")
    code, out, err = _run(["ip", "-j", "-4", "addr", "show"], run)
    if code != 0:
        return None, f"ip -j -4 addr show: {_said(code, out, err)}"
    try:
        links = json.loads(out or "[]")
        code, out, err = _run(["ip", "-j", "-4", "route", "show", "default"], run)
        if code != 0:
            return None, f"ip -j -4 route show default: {_said(code, out, err)}"
        routes = json.loads(out or "[]")
    except ValueError:
        return None, "ip's answer wasn't JSON (iproute2 older than 4.15?)"
    if not isinstance(links, list) or not isinstance(routes, list):
        return None, "ip's answer wasn't what was expected"
    interfaces, by_name = [], {}
    for link in links:
        if not isinstance(link, dict) or not link.get("ifname"):
            continue
        name = str(link["ifname"])
        flags = link.get("flags") or []
        state = str(link.get("operstate") or "").upper()
        up = state == "UP" or (state == "UNKNOWN" and "LOWER_UP" in flags)
        net = root / "sys" / "class" / "net" / name
        try:
            mac = (net / "address").read_text(encoding="ascii", errors="replace").strip() or None
        except OSError:
            mac = link.get("address")
        addresses = [{"address": a.get("local"), "prefix": a.get("prefixlen"),
                      "origin": "Dhcp" if a.get("dynamic") else "Manual"}
                     for a in link.get("addr_info") or [] if isinstance(a, dict) and a.get("local")
                     and a.get("family", "inet") == "inet"]
        interface = {"if_index": link.get("ifindex"), "alias": name, "status": "Up" if up else "Down",
                     "virtual": name == "lo" or not (net / "device").exists(), "mac": mac, "ipv4": addresses}
        interfaces.append(interface)
        by_name[name] = interface
    found = []
    for route in routes:
        if isinstance(route, dict) and route.get("dev") in by_name:
            found.append({"if_index": by_name[route["dev"]]["if_index"], "metric": route.get("metric", 0),
                          "next_hop": route.get("gateway")})
    return {"interfaces": interfaces, "routes": found}, None


def _ufw_enabled(root):
    try:
        text = (root / "etc" / "ufw" / "ufw.conf").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return re.search(r"^\s*ENABLED\s*=\s*['\"]?yes", text, re.M | re.I) is not None


def _query(args, run):
    """True for firewall-cmd's yes, False for its no, None when it couldn't say."""
    _, out, _ = _run(["firewall-cmd", *args], run)
    answer = (out or "").strip().lower()
    return answer == "yes" if answer in ("yes", "no") else None


def firewall(port, interface=None, run=None, root=None):
    """(the firewall dict, None), or (None, why it couldn't be read)."""
    root = Path(root or "/")
    code, out, err = _run(["systemctl", "is-active", *(f"{name}.service" for name in FIREWALLS)], run)
    states = (out or "").split()
    if code == 127 or len(states) != len(FIREWALLS):
        return None, f"systemctl is-active: {_said(code, out, err)}"
    active = [name for name, state in zip(FIREWALLS, states) if state == "active"
              and (name != "ufw" or _ufw_enabled(root))]
    facts = {"active": active, "zone": None, "port": None, "mdns": None}
    if "firewalld" in active:
        zone = None
        if interface:
            code, out, _ = _run(["firewall-cmd", f"--get-zone-of-interface={interface}"], run)
            zone = out.strip() if code == 0 and out.strip() else None
        if zone is None:
            code, out, _ = _run(["firewall-cmd", "--get-default-zone"], run)
            zone = out.strip() if code == 0 and out.strip() else None
        facts["zone"] = zone
        if zone:
            facts["port"] = _query([f"--zone={zone}", f"--query-port={int(port)}/tcp"], run)
            if facts["port"] is not True:
                code, out, _ = _run(["firewall-cmd", f"--zone={zone}", "--list-rich-rules"], run)
                if code == 0 and re.search(rf'port port="?{int(port)}"? protocol="?tcp"?\s+accept', out or ""):
                    facts["port"] = True
            facts["mdns"] = _query([f"--zone={zone}", "--query-service=mdns"], run)
    return facts, None


def read_facts(port, run=None, root=None):
    """status's Linux facts (see the module docstring)."""
    errors = {}
    found, why = network(run, root)
    if why:
        errors["network"] = why
    from .checks import pick_interface
    chosen = pick_interface(found)
    walls, why = firewall(port, (chosen or {}).get("alias"), run, root)
    if why:
        errors["firewall"] = why
    return {"network": found, "firewall": walls, "errors": errors}
